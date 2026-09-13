#!/usr/bin/env python3
"""fold-dated-bullets.py — SESSION.md などの日付 bullet の連続ブロックを、要約 1 本 (+ 追記点の行) に畳み、全文を archive へ verbatim で退避する。相対 link は archive の深さに付け替え、退避の完全性を検算してから書く。

memory-file-slimming.md #verbatim-retreat の機械化。 2026-09-13 に 40 本の bullet を手書き script で畳んだ回、
(1) 相対 link が archive の深さで 39 本切れて staged link guard に止められ、 (2) 移した行が全部 archive に在るかを
別の snippet で確かめ直した。 この 2 手を 1 本にする。

usage:
    python3 fold-dated-bullets.py SESSION.md --prefix '- **2026-09-13 ' \
        --archive SESSION-archive/2026-09.md --heading '2026-09-13 の SESSION bullet (verbatim 退避)' \
        --summary-file summary.md [--marker '- **2026-09-13 以降の pass (追記はここ)**:'] [--dry-run]
    python3 fold-dated-bullets.py --selftest

規則 (1 つでも破れたら何も書かない):
  - `--prefix` で始まる行が 1 つ以上あり、 すべて連続している (途中に別の行が挟まるなら畳む範囲を人が決める)
  - archive に同じ見出しがまだ無い (二重退避の防止)
  - 付け替え後の各行が archive の追記部分にそのまま在る (link target の深さ以外は 1 文字も変えない)
  - 付け替えた link の着地先が実在する (実在しない link は元の file でも切れていたので、 付け替えずに報告)
要約は `--summary-file` の中身をそのまま 1 行 (末尾改行は除く) として置く。 ⚠️ 要約行が `--prefix` で始まる形
(「- **2026-09-13 のまとめ**」) だと、 同じ prefix で 2 回目を回したとき要約も畳む対象に入る。 同じ見出しなら拒否されるが、
見出しを変えると通るので、 2 回目は `--dry-run` の件数を見てから。 `--marker` は要約の直後に置く行
(並列 session が以後の bullet をそこへ足すための追記点。 multi-session-coordination.md #fold-with-append-point)。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

LINK = re.compile(r"\]\(([^)\s]+)\)")


def _rebase_target(target: str, src_dir: Path, dst_dir: Path) -> tuple[str, bool]:
    """Return (new_target, changed). URLs, pure anchors and absolute paths are kept."""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#") or target.startswith("/"):
        return target, False
    path, sep, anchor = target.partition("#")
    if not path:
        return target, False
    resolved = os.path.normpath(src_dir / path)
    new_path = os.path.relpath(resolved, dst_dir)
    new = new_path + (sep + anchor if sep else "")
    return new, new != target


def rebase_links(line: str, src_dir: Path, dst_dir: Path) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(m: re.Match) -> str:
        target = m.group(1)
        new, changed = _rebase_target(target, src_dir, dst_dir)
        if changed:
            landing = os.path.normpath(dst_dir / new.partition("#")[0])
            if not os.path.exists(landing):
                missing.append(target)
                return m.group(0)
        return "](" + new + ")"

    return LINK.sub(sub, line), missing


def fold(src: Path, prefix: str, archive: Path, heading: str, summary: str, marker: str | None,
         dry_run: bool = False) -> int:
    lines = src.read_text(encoding="utf-8").split("\n")
    idx = [i for i, l in enumerate(lines) if l.startswith(prefix)]
    if not idx:
        print(f"✗ no line starts with {prefix!r} in {src}", file=sys.stderr)
        return 1
    if idx != list(range(idx[0], idx[-1] + 1)):
        gaps = sorted(set(range(idx[0], idx[-1] + 1)) - set(idx))
        print(f"✗ the {len(idx)} bullets are not contiguous (other lines at {[g + 1 for g in gaps][:5]}); "
              f"decide the fold range by hand", file=sys.stderr)
        return 1
    block = [lines[i] for i in idx]
    arch_text = archive.read_text(encoding="utf-8") if archive.exists() else ""
    head_line = f"## {heading}"
    if head_line in arch_text.split("\n"):
        print(f"✗ {archive} already has the heading {head_line!r}", file=sys.stderr)
        return 1
    rebased, broken = [], []
    for l in block:
        new, miss = rebase_links(l, src.parent.resolve(), archive.parent.resolve())
        rebased.append(new)
        broken += miss
    appended = "\n\n" + head_line + "\n\n" + "\n".join(rebased) + "\n"
    new_arch = arch_text.rstrip("\n") + appended
    # completeness: every moved line, link targets aside, is in the appended part
    strip = lambda s: LINK.sub("]()", s)
    if [strip(x) for x in rebased] != [strip(x) for x in block] or not all(x in appended for x in rebased):
        print("✗ internal check failed: the archived block differs from the moved block beyond link targets",
              file=sys.stderr)
        return 1
    new_lines = lines[:idx[0]] + [summary] + ([marker] if marker else []) + lines[idx[-1] + 1:]
    changed = sum(1 for a, b in zip(block, rebased) if a != b)
    print(f"{'[dry-run] ' if dry_run else ''}fold {len(block)} bullet(s) from {src} -> 1 summary"
          f"{' + marker' if marker else ''}; archive {archive} gets {len(block)} line(s) "
          f"({changed} with re-based links)")
    for t in sorted(set(broken)):
        print(f"  ⚠️ link already broken in the source, left as is: {t}")
    if not dry_run:
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(new_arch, encoding="utf-8")
        src.write_text("\n".join(new_lines), encoding="utf-8")
    return 0


def selftest() -> int:
    failed = []

    def expect(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failed.append(name)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "review").mkdir(); (root / "review" / "a.md").write_text("x", encoding="utf-8")
        (root / "notes").mkdir(); (root / "notes" / "b.md").write_text("y", encoding="utf-8")
        s = root / "SESSION.md"
        s.write_text("# S\n\n## Current state\n\n"
                     "- **2026-09-13 pass 1**: see [a](review/a.md) and [b](notes/b.md#sec).\n"
                     "- **2026-09-13 pass 2**: [web](https://example.org) [self](#top) [gone](review/none.md)\n"
                     "- **2026-09-12 older**: keep\n\n## Next\n", encoding="utf-8")
        arch = root / "SESSION-archive" / "2026-09.md"
        arch.parent.mkdir(); arch.write_text("# archive\n", encoding="utf-8")
        rc = fold(s, "- **2026-09-13 ", arch, "2026-09-13 bullets", "- **2026-09-13 summary**", "- **later passes here**:")
        expect("fold returns 0", rc == 0)
        st, at = s.read_text(encoding="utf-8"), arch.read_text(encoding="utf-8")
        expect("session keeps the summary, the marker and the older bullet, drops the folded ones",
               "- **2026-09-13 summary**\n- **later passes here**:\n- **2026-09-12 older**" in st and "pass 1" not in st)
        expect("archive links re-based to its depth (../review, ../notes with anchor)",
               "](../review/a.md)" in at and "](../notes/b.md#sec)" in at)
        expect("URLs and pure anchors untouched", "](https://example.org)" in at and "](#top)" in at)
        expect("an already broken link is left as it was", "](review/none.md)" in at)
        rc2 = fold(s, "- **2026-09-13 ", arch, "2026-09-13 bullets", "x", None)
        expect("re-run with the same heading is refused (the summary line itself starts with the prefix)", rc2 == 1)
        s2 = root / "S2.md"; s2.write_text("- **x other**\n", encoding="utf-8")
        expect("no line with the prefix: exit 1", fold(s2, "- **2026-09-13 ", arch, "new heading", "x", None) == 1)
        s.write_text("- **d pass 1**\nother\n- **d pass 2**\n", encoding="utf-8")
        before = s.read_text(encoding="utf-8")
        expect("non-contiguous block: exit 1", fold(s, "- **d ", arch, "d", "sum", None) == 1)
        expect("... and the file is unchanged", s.read_text(encoding="utf-8") == before)
        s.write_text("- **e pass**\n", encoding="utf-8")
        expect("heading already in the archive: exit 1",
               fold(s, "- **e ", arch, "2026-09-13 bullets", "sum", None) == 1)
    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--archive", type=Path, required=True)
    ap.add_argument("--heading", required=True)
    ap.add_argument("--summary-file", type=Path, required=True)
    ap.add_argument("--marker")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    summary = a.summary_file.read_text(encoding="utf-8").rstrip("\n")
    if "\n" in summary:
        ap.error("the summary must be a single line (one bullet)")
    return fold(a.src, a.prefix, a.archive, a.heading, summary, a.marker, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
