#!/usr/bin/env python3
"""markdown の `#anchor` 付き link を PATH で解決し、着地先の file にその anchor が実在するかを検査する (repo 内の自己参照も対象、 basename 一致でなく path 解決なので同名 file が複数 repo にあっても取り違えない)。--selftest 内蔵。

[`check-inbound-refs.py`](check-inbound-refs.py) との分担:

- `check-inbound-refs.py` = 「**この repo を restructure したら下流が壊れるか**」。 target repo への
  参照を **basename** で索引し、 target の外にある source を走査する。 target repo の内部参照は
  「その repo の自分の問題」 として意図的に除外している。
- 本 script = 「**書いた link は、 その path が指す file でちゃんと解決するか**」。 全 file の全 link を
  path で解決するので、 **同じ file の中の自己参照**も、 **repo をまたぐ相対 path**も見る。

2026-09-06 の layer-1 分割 (5 doc が claude-config → ai-collaboration、 claude-config には転送 stub が
残る) 以降、 同じ basename が 2 repo に在る。 basename 索引はこれを取り違えるので、 path 解決の目が
別に要る (2026-09-12: 取り違えで 29 件の偽陽性、 同時に**既存の検査がどれも見ていなかった壊れた
自己参照**が 20 件以上見つかった)。

使い方:

    python3 check-md-anchors.py                     # ~/Claude 配下を全部
    python3 check-md-anchors.py --base ~/Claude --repo claude-config --repo ai-collaboration
    python3 check-md-anchors.py --list              # 壊れている参照元を全部出す
    python3 check-md-anchors.py --quiet             # 緑のときは何も言わない

anchor は 明示の `<a id="...">` / `id='...'` と、 見出しから作る GitHub 風 slug の和で判定する
(slug の計算は `check-inbound-refs.py` の `gh_slug` + `rendered_heading_text` を import して共有 = 2 実装にしない)。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from importlib import import_module
    _cir = import_module("check-inbound-refs".replace("-", "_"))  # type: ignore
    gh_slug, rendered_heading_text = _cir.gh_slug, _cir.rendered_heading_text
except Exception:                                     # module name has dashes; load by path
    import importlib.util
    _p = Path(__file__).with_name("check-inbound-refs.py")
    _spec = importlib.util.spec_from_file_location("_cir", _p)
    _m = importlib.util.module_from_spec(_spec)        # type: ignore
    _spec.loader.exec_module(_m)                       # type: ignore
    gh_slug, rendered_heading_text = _m.gh_slug, _m.rendered_heading_text

SKIP_DIRS = {".git", "node_modules", "_site", "build", "dist", ".venv", "venv",
             ".next", "out", "__pycache__", ".cache", "worktrees", "PackageCache"}
LINK = re.compile(r"\[[^\]]*\]\((?!https?:|mailto:|#?$)([^)\s]+)\)")
EXPLICIT = re.compile(r"""id=["']([^"']+)["']""")
FENCE = re.compile(r"^(```|~~~)[^\n]*\n.*?^\1[ \t]*$", re.M | re.S)
CODE_SPAN = re.compile(r"`[^`\n]*`")
LINE_ANCHOR = re.compile(r"^L\d+(?:-L?\d+)?$")   # GitHub / editor line refs, not headings
_cache: dict[Path, set] = {}


def live_markdown(text: str) -> str:
    """Drop fenced blocks and inline code spans: a link shown AS SYNTAX (`[x](#slug)`) is an
    example, not a link. Link text that merely contains code (`` [`name`](#a) ``) survives as
    `[](#a)`, so real links with backticked labels are still checked."""
    return CODE_SPAN.sub("", FENCE.sub("", text))


def is_checkable_fragment(frag: str) -> bool:
    return not LINE_ANCHOR.match(frag) and "<" not in frag and ">" not in frag


def anchors_of(p: Path) -> set:
    if p in _cache:
        return _cache[p]
    try:
        body = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        _cache[p] = set()
        return _cache[p]
    body = FENCE.sub("", body)        # a `# comment` inside a bash fence is not a heading
    ids = set(EXPLICIT.findall(body))
    for h in re.findall(r"^#{1,6}\s+(.*)$", body, re.M):
        ids.add(gh_slug(rendered_heading_text(h)))
    _cache[p] = ids
    return ids


def scan(base: Path, repos: list[str]) -> tuple[dict[str, list[str]], int]:
    broken: dict[str, list[str]] = {}
    checked = 0
    roots = [base / r for r in repos] if repos else [base]
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                src = Path(dirpath) / fn
                try:
                    text = src.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for m in LINK.finditer(live_markdown(text)):
                    path_part, sep, frag = m.group(1).partition("#")
                    if not sep or not frag or not is_checkable_fragment(frag):
                        continue
                    dest = (src.parent / path_part).resolve() if path_part else src
                    checked += 1
                    if not dest.exists() or dest.suffix != ".md":
                        continue          # missing paths are check-inbound-refs' business
                    if frag not in anchors_of(dest):
                        try:
                            key = f"{dest.relative_to(base)}#{frag}"
                        except ValueError:
                            key = f"{dest}#{frag}"
                        broken.setdefault(key, []).append(str(src.relative_to(base)))
    return broken, checked


def selftest() -> int:
    import tempfile
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "r1").mkdir()
        (base / "r2").mkdir()
        # r2/doc.md holds the real anchor; r1/doc.md is a stub WITHOUT it (the split shape)
        (base / "r2" / "doc.md").write_text(
            '<a id="real"></a>\n## Some Heading\n', encoding="utf-8")
        (base / "r1" / "doc.md").write_text("stub, no anchors\n", encoding="utf-8")
        (base / "r1" / "src.md").write_text(
            "ok cross-repo [x](../r2/doc.md#real)\n"
            "ok heading slug [y](../r2/doc.md#some-heading)\n"
            "broken [z](../r2/doc.md#missing)\n"
            "self ok [s](#here)\n<a id=\"here\"></a>\n"
            "self broken [t](#nowhere)\n"
            "no fragment [u](../r2/doc.md)\n"
            "external [v](https://example.com/a#b)\n", encoding="utf-8")
        broken, checked = scan(base, [])
        keys = set(broken)
        check("cross-repo link to the real anchor resolves (not matched against the stub)",
              not any("#real" in k for k in keys))
        check("heading slug resolves", not any("some-heading" in k for k in keys))
        check("broken cross-repo anchor is reported", any(k.endswith("doc.md#missing")
                                                          for k in keys))
        check("broken SAME-FILE anchor is reported  [check-inbound-refs does not look here]",
              any(k.endswith("src.md#nowhere") for k in keys))
        check("working same-file anchor is not reported", not any("#here" in k for k in keys))
        # 7 links in the fixture; the external one and the fragment-less one are not counted
        check("external and fragment-less links are ignored", checked == 5)
        check("exactly 2 broken", len(broken) == 2)

    # GitHub slugs, code spans, fences, line refs (2026-09-13 false-positive fixes)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "d.md").write_text(
            "## foo.py — bar.yaml → baz\n"
            "```bash\n# not-a-heading\n```\n"
            "ok github double dash [a](#foopy--baryaml--baz)\n"
            "collapsed form is NOT github's [b](#foopy-baryaml-baz)\n"
            "syntax example `[x](#shown-as-code)` is not a link\n"
            "```md\n[y](#inside-fence)\n```\n"
            "line ref [c](#L53) and range [d](#L10-L20)\n"
            "placeholder [e](#<slug>)\n"
            "backticked label is still a link [`name`](#really-missing)\n"
            "fence heading must not count [f](#not-a-heading)\n", encoding="utf-8")
        broken, _ = scan(base, [])
        keys = {k.split("#", 1)[1] for k in broken}
        check("GitHub double-dash slug resolves (spaces are not collapsed)",
              "foopy--baryaml--baz" not in keys)
        check("the collapsed slug is reported  [foil for the old \\s+ collapse]",
              "foopy-baryaml-baz" in keys)
        check("link shown inside an inline code span is not checked", "shown-as-code" not in keys)
        check("link inside a fenced block is not checked", "inside-fence" not in keys)
        check("#L53 / #L10-L20 line refs are not checked", not ({"L53", "L10-L20"} & keys))
        check("<slug> placeholder is not checked", "<slug>" not in keys)
        check("a real link whose label is backticked is still checked  [foil for over-stripping]",
              "really-missing" in keys)
        check("a `# comment` inside a fence does not create an anchor",
              "not-a-heading" in keys)
    check("a link inside a heading contributes only its label to the slug",
          gh_slug(rendered_heading_text("1.2 the artifact [anchor.py](scripts/anchor.py)"))
          == "12-the-artifact-anchorpy")
    check("an explicit <a id> tag contributes nothing to the heading slug",
          gh_slug(rendered_heading_text('<a id="x"></a>2.4 Errata marker')) == "24-errata-marker")
    check("gh_slug matches github-slugger on the em-dash case",
          gh_slug("sync-shared-style.py — shared-style-targets.yaml → paper-style-l2.md")
          == "sync-shared-stylepy--shared-style-targetsyaml--paper-style-l2md")

    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--base", type=Path, default=Path.home() / "Claude")
    p.add_argument("--repo", action="append", default=[])
    p.add_argument("--list", action="store_true", help="print every source of every break")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        return selftest()

    broken, checked = scan(a.base, a.repo)
    if not broken:
        if not a.quiet:
            print(f"[check-md-anchors] {checked} anchored link(s): all resolve")
        return 0
    total = sum(len(v) for v in broken.values())
    print(f"[check-md-anchors] {total} ref(s) to {len(broken)} anchor(s) that do not exist "
          f"in the file the path lands on (of {checked} checked)")
    for key, srcs in sorted(broken.items(), key=lambda kv: -len(kv[1])):
        print(f"  {key}   <- {len(srcs)} ref(s)")
        for s in (srcs if a.list else srcs[:2]):
            print(f"      {s}")
        if not a.list and len(srcs) > 2:
            print(f"      ... +{len(srcs) - 2} (--list for all)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
