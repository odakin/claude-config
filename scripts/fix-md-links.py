#!/usr/bin/env python3
"""markdown の相対 link のうち着地先 file が無いものを分類し、答えが一意に決まる 2 型 (../ の段数ずれ・git が記録した改名) だけ直す。解決は renderer と同じ (symlink は実体 path、%XX decode、`:行番号` 無視、code span・fence・$数式$ の中は link でない)、書換えは link target の終端まで一致した時だけ・保護領域の外だけ、書換え後に「差は link target の中だけ・新しい着地先は全て実在・対象 file ごとに差が在る」 を自己検証する。--selftest 内蔵。

分類 (`--list` で全件):

| class        | 意味 | --fix |
|--------------|------|-------|
| depth        | `../` を 0..6 段試して着地先が **1 つだけ** 存在する (sub-dir・SESSION-archive/ へ移したのに link を張り直していない) | 直す |
| renamed      | git が改名を記録しており (`git log --diff-filter=R -M -z`)、その先が実在する | 直す |
| ambiguous    | 複数の段数で存在する | 触らない |
| verbatim     | 直せるが、生の記録 (`/raw/`・dialogue・transcript) の中 = 他者の出力の写し | 触らない |
| gone         | 同じ名前の file がどこにも無い / 改名先も消えた | 触らない (報告のみ) |
| not-a-path   | 拡張子が無い・空白や `\\` を含む (数式・散文・件名の一覧を link と誤認したもの) | 触らない |

使い方:

    python3 fix-md-links.py --base ~/Claude                   # 分類の件数
    python3 fix-md-links.py --base ~/Claude --list            # 全件
    python3 fix-md-links.py --base . --strict                 # depth / renamed が 1 件でもあれば exit 1 (suite 用)
    python3 fix-md-links.py --base ~/Claude --fix --exclude 'repo/path/example-doc.md'

`--fix` は書き換えた file を `CHANGED<TAB>path` で出すだけで commit はしない。 commit する側は
**`git diff -z --name-only` で path を取る** (非 ASCII の file 名は `-z` 無しだと 8 進 escape 付きで
quote され、 下流の検証に渡すと「差分 0 行」 で**空振りして PASS する** = 2026-09-13 実測、
claude-config `debugging-discipline.md#tooling-that-lies-on-binary-and-non-ascii`)。

起源 (2026-09-13): 素朴に数えた着地先の無い相対 link 898 本のうち 457 本は symlink の複製を symlink の
場所から解決した測定側の誤りで、 renderer と同じ解決では 8,718 本中 505 本。 直したのは 255 箇所 (段数ずれ
219 + 改名・移動 31 + 削除済み file への permalink 5、 13 repo・47 file)、 残りは数式・件名一覧の誤認と後継の無い削除。 途中で踏んだ罠 = 前方一致の置換が長い link を
書き換えた / 非 ASCII path の quote で検証が空振りした — どちらも selftest の foil。
正本 = `docs/convention-design-principles.md#link-target-rot`。
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("_cma", Path(__file__).with_name("check-md-anchors.py"))
_cma = _ilu.module_from_spec(_spec)                     # type: ignore
_spec.loader.exec_module(_cma)                          # type: ignore
LINK, protected_mask, split_target = _cma.LINK, _cma.protected_mask, _cma.split_target
iter_markdown_sources, rel_to = _cma.iter_markdown_sources, _cma.rel_to

VERBATIM = re.compile(r"/raw/|dialogue|transcript", re.I)
FIXABLE = ("depth", "renamed")
MAX_DEPTH = 6


def _exists(p: Path) -> bool:
    try:
        return p.exists()
    except OSError:              # e.g. name too long
        return False


class Git:
    """Per-repo rename maps from `git log -z` (NUL-separated: no path quoting)."""

    def __init__(self):
        self.roots: dict[Path, Path | None] = {}
        self.maps: dict[Path, dict[str, str]] = {}

    def root(self, d: Path) -> Path | None:
        if d not in self.roots:
            r = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True)
            self.roots[d] = Path(r.stdout.strip()).resolve() if r.returncode == 0 else None
        return self.roots[d]

    def renames(self, root: Path) -> dict[str, str]:
        if root not in self.maps:
            out = subprocess.run(["git", "-C", str(root), "log", "--all", "--diff-filter=R", "-M",
                                  "--name-status", "-z", "--format="], capture_output=True).stdout
            fields = [f for f in out.decode("utf-8", "surrogateescape").split("\0")]
            mp: dict[str, str] = {}
            i = 0
            while i + 2 < len(fields):
                st = fields[i].strip()
                if st.startswith("R"):
                    mp.setdefault(fields[i + 1], fields[i + 2])     # newest rename wins (log order)
                    i += 3
                else:
                    i += 1
            self.maps[root] = mp
        return self.maps[root]


def classify(src: Path, path_part: str, git: Git) -> tuple[str, str | None]:
    """(class, new_path_part or None). path_part is the raw (still %XX-encoded) path."""
    real_dir = src.resolve().parent
    dec = unquote(path_part)
    if _exists(real_dir / dec):
        return "ok", None
    if dec.startswith("~/"):                                      # `~/x` never resolves in a renderer
        home = Path.home() / dec[2:]
        return ("renamed", os.path.relpath(home, real_dir)) if _exists(home) else ("gone", None)
    # "Is this a path at all?" is decided on the RAW target: a real file name with a space arrives
    # as %20 (the link regex never captures a literal space), and a formula carries `\`.
    if "\\" in path_part or dec.startswith("/"):
        return "not-a-path", None
    core_dec = re.sub(r"^(?:\.\./|\./)+", "", dec)
    core_raw = re.sub(r"^(?:\.\./|\./)+", "", path_part)
    hits = [k for k in range(MAX_DEPTH + 1) if core_dec and _exists(real_dir / ("../" * k + core_dec))]
    # A target with no extension is a path only if it resolves at some depth or is an explicit
    # directory (`dir/`). Otherwise it is prose: `(2)`, `(通知)`, and mail subjects that carry a
    # date slash like `(通知:7/18締切)` all look like `a/b` but are not paths (2026-09-13: 16 such
    # subjects were misfiled as "gone" when a bare `/` was taken as proof of a path).
    if not Path(dec).suffix and not dec.endswith("/") and not hits:
        return "not-a-path", None
    if len(hits) == 1:
        return "depth", "../" * hits[0] + core_raw
    if len(hits) > 1:
        return "ambiguous", None
    root = git.root(real_dir)
    if root is not None:
        meant = os.path.relpath(os.path.normpath(real_dir / dec), root)
        chain, hops = meant, set()
        ren = git.renames(root)
        while chain in ren and chain not in hops:
            hops.add(chain)
            chain = ren[chain]
        if chain != meant and _exists(root / chain):
            return "renamed", os.path.relpath(root / chain, real_dir)
    return "gone", None


def scan(base: Path, repos: list[str], excludes: list[str], include_verbatim: bool):
    git = Git()
    rows = []            # (src, rel, raw_target, class, new_path_part)
    for src in iter_markdown_sources(base, repos):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = rel_to(base, src)
        mask = protected_mask(text)
        for m in LINK.finditer(text):
            if mask[m.start()]:
                continue
            path_part, _suffix, _frag = split_target(m.group(1))
            if not path_part or "<" in path_part or "{" in path_part:
                continue
            cls, new = classify(src, path_part, git)
            if cls == "ok":
                continue
            if cls in FIXABLE and not include_verbatim and VERBATIM.search("/" + rel):
                cls, new = "verbatim", None
            if cls in FIXABLE and any(fnmatch.fnmatch(rel, g) for g in excludes):
                cls, new = "excluded", None
            rows.append((src, rel, m.group(1), cls, new))
    return rows


def rewrite(text: str, fixes: dict[str, str]) -> tuple[str, int]:
    """Rewrite link targets whose path part EXACTLY equals a key, outside protected regions.
    Matching is per parsed link, never a substring replace: fixing `notes/a` must not touch
    `](notes/a-b.md)` (the prefix-collision bug of a `str.replace("](" + key)` fixer)."""
    mask = protected_mask(text)
    out, last, n = [], 0, 0
    for m in LINK.finditer(text):
        if mask[m.start()]:
            continue
        path_part, suffix, frag = split_target(m.group(1))
        if path_part not in fixes:
            continue
        new_target = fixes[path_part] + suffix + (("#" + frag) if frag else "")
        g0, g1 = m.span(1)
        out.append(text[last:g0])
        out.append(new_target)
        last = g1
        n += 1
    out.append(text[last:])
    return "".join(out), n


TGT = re.compile(r"\]\(([^)\s]+)\)")


def verify(path: Path, old: str, new: str) -> list[str]:
    """Self-check of a rewrite: same line count, differences only inside link targets, every
    new target resolves, and there IS a difference (a no-op 'fix' is a failure, not a pass)."""
    errs = []
    a, b = old.split("\n"), new.split("\n")
    if old == new:
        return [f"{path}: no change (vacuous fix)"]
    if len(a) != len(b):
        return [f"{path}: line count changed {len(a)} -> {len(b)}"]
    for la, lb in zip(a, b):
        if la == lb:
            continue
        if TGT.sub("](T)", la) != TGT.sub("](T)", lb):
            errs.append(f"{path}: change outside a link target: {lb[:100]}")
        for t in set(TGT.findall(lb)) - set(TGT.findall(la)):
            pp, _s, _f = split_target(t)
            if pp and not pp.startswith(("http:", "https:", "mailto:")) \
                    and not _exists(path.resolve().parent / unquote(pp)):
                errs.append(f"{path}: new target does not resolve: {t}")
    return errs


def run_fix(rows) -> tuple[list[str], list[str]]:
    per_file: dict[Path, dict[str, str]] = defaultdict(dict)
    for src, _rel, target, cls, new in rows:
        if cls in FIXABLE:
            per_file[src.resolve()][split_target(target)[0]] = new
    changed, errors = [], []
    for real, fixes in per_file.items():
        old = real.read_text(encoding="utf-8")
        new, n = rewrite(old, fixes)
        errs = verify(real, old, new)
        if errs:
            errors += errs
            continue                         # never write a file that fails its own check
        real.write_text(new, encoding="utf-8")
        changed.append(str(real))
    return changed, errors


# ---------------------------------------------------------------- selftest


def selftest() -> int:
    import tempfile
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        repo = base / "repo"
        (repo / "SESSION-archive").mkdir(parents=True)
        (repo / "analyses" / "archive").mkdir(parents=True)
        (repo / "notes").mkdir()
        (repo / "notes" / "a").mkdir()
        (repo / "notes" / "a-b.md").write_text("x\n", encoding="utf-8")
        (repo / "notes" / "t a.md").write_text("x\n", encoding="utf-8")
        (repo / "DESIGN.md").write_text("x\n", encoding="utf-8")
        (repo / "tool.py").write_text("x\n", encoding="utf-8")
        # git repo with a recorded rename: notes/2026-01-01-conv.tex -> notes/conv.tex
        g = lambda *c: subprocess.run(["git", "-C", str(repo), *c], capture_output=True, check=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        (repo / "notes" / "2026-01-01-conv.tex").write_text("\\relax\n" * 20, encoding="utf-8")
        g("add", "-A"); g("commit", "-q", "-m", "a")
        g("mv", "notes/2026-01-01-conv.tex", "notes/conv.tex"); g("commit", "-q", "-m", "rename")

        arch = repo / "SESSION-archive" / "2026-01.md"
        (repo / "SESSION-archive" / "DESIGN.md.local").write_text("x\n", encoding="utf-8")
        body = (
            "correct sibling that shares the broken key as a prefix [k](DESIGN.md.local)\n"
            "moved into archive, depth off [d](DESIGN.md) and [e](notes/a-b.md#sec)\n"
            "short key must not rewrite a longer link [p](notes/a) vs [q](notes/a-b.md)\n"
            "editor line ref [l](tool.py:12)\n"
            "encoded [u](notes/t%20a.md)\n"
            "renamed [r](../notes/2026-01-01-conv.tex)\n"
            "example `[x](DESIGN.md)` stays as written\n"
            "formula $[a,b](2)$ and subject [重要](通知) are not paths\n"
            "a mail subject with a date slash [件名](通知:7/18締切) is not a path either\n"
            "an explicit dir link that is gone [z](old-examples/)\n"
            "gone [g](nowhere/deleted.md)\n"
        )
        arch.write_text(body, encoding="utf-8")
        raw_dir = repo / "raw"
        raw_dir.mkdir()
        (raw_dir / "memo.md").write_text("[v](DESIGN.md)\n", encoding="utf-8")   # would be depth

        rows = scan(base, ["repo"], [], False)
        cls = {(r[1], r[2]): r[3] for r in rows}
        a = "repo/SESSION-archive/2026-01.md"
        check("depth error after an archive move is classified", cls.get((a, "DESIGN.md")) == "depth")
        check("editor :line suffix is resolved on the path part", cls.get((a, "tool.py:12")) == "depth")
        check("%20 path is decoded before resolving", cls.get((a, "notes/t%20a.md")) == "depth")
        check("git-recorded rename is followed",
              cls.get((a, "../notes/2026-01-01-conv.tex")) == "renamed")
        check("code-span example is not a link", (a, "DESIGN.md") in cls and
              sum(1 for r in rows if r[1] == a and r[2] == "DESIGN.md") == 1)
        check("formula and mail-subject brackets are not paths",
              cls.get((a, "2")) is None and cls.get((a, "通知")) == "not-a-path")
        check("deleted target is 'gone' (reported, not fixed)", cls.get((a, "nowhere/deleted.md")) == "gone")
        check("a date slash in a mail subject does not make it a path  [foil for `/` = path]",
              cls.get((a, "通知:7/18締切")) == "not-a-path")
        check("an explicit missing dir link (`dir/`) is 'gone', not prose",
              cls.get((a, "old-examples/")) == "gone")
        check("fixable link inside a raw/ record is left as verbatim",
              cls.get(("repo/raw/memo.md", "DESIGN.md")) == "verbatim")

        # teeth of the prefix foil: the naive fixer really does break the correct sibling
        naive = body.replace("](DESIGN.md", "](../DESIGN.md")
        check("naive str.replace fixer breaks the correct sibling link (the foil has teeth)",
              "[k](../DESIGN.md.local)" in naive)
        changed, errors = run_fix(rows)
        new = arch.read_text(encoding="utf-8")
        check("exact-target rewrite leaves the correct sibling link alone  [foil: prefix replace]",
              "[k](DESIGN.md.local)" in new)
        check("fix writes the archive file and reports no self-check errors",
              str(arch.resolve()) in changed and not errors)
        check("depth fixed, fragment kept", "[e](../notes/a-b.md#sec)" in new and "[d](../DESIGN.md)" in new)
        check("line suffix kept", "[l](../tool.py:12)" in new)
        check("rename rewritten to the successor", "[r](../notes/conv.tex)" in new)
        check("short key notes/a did NOT rewrite the longer link  [foil: prefix replace]",
              "[p](../notes/a)" in new and "[q](../notes/a-b.md)" in new
              and "../../notes/a-b.md" not in new)
        check("code-span example untouched  [foil: protected region]", "`[x](DESIGN.md)`" in new)
        check("gone target untouched", "[g](nowhere/deleted.md)" in new)
        check("raw/ record untouched", (raw_dir / "memo.md").read_text() == "[v](DESIGN.md)\n")
        rows2 = scan(base, ["repo"], [], False)
        check("after fix nothing fixable remains", not [r for r in rows2 if r[3] in FIXABLE])

        # verify() gate itself
        check("verify rejects a change outside a link target  [foil]",
              verify(arch, "see [a](x.md) now\n", "SEE [a](x.md) now\n") != [])
        check("verify rejects a no-op (vacuous) fix  [foil]", verify(arch, "same\n", "same\n") != [])
        check("verify rejects an unresolvable new target  [foil]",
              verify(arch, "[a](x.md)\n", "[a](../missing.md)\n") != [])

    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", type=Path, default=Path.home() / "Claude")
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[], help="glob (relative to base) never fixed")
    ap.add_argument("--include-verbatim", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any depth/renamed link remains")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    rows = scan(a.base, a.repo, a.exclude, a.include_verbatim)
    counts = Counter(r[3] for r in rows)
    if a.fix:
        changed, errors = run_fix(rows)
        for c in changed:
            print(f"CHANGED\t{c}")
        for e in errors:
            print(f"[SELF-CHECK FAIL, file not written] {e}")
        rows = scan(a.base, a.repo, a.exclude, a.include_verbatim)
        counts = Counter(r[3] for r in rows)
        if errors:
            return 1
    fixable = counts["depth"] + counts["renamed"]
    if not (a.quiet and fixable == 0):
        print(f"[fix-md-links] relative links with a missing target: {len(rows)}  "
              + "  ".join(f"{k}={v}" for k, v in counts.most_common()))
    if a.list:
        for _src, rel, target, cls, new in sorted(rows, key=lambda r: (r[3], r[1])):
            print(f"  {cls:10s} {rel}  ::  {target}" + (f"  ->  {new}" if new else ""))
    elif fixable and not a.quiet:
        for _src, rel, target, cls, new in rows:
            if cls in FIXABLE:
                print(f"  {cls:8s} {rel}  ::  {target}  ->  {new}")
    return 1 if (a.strict and fixable) else 0


if __name__ == "__main__":
    sys.exit(main())
