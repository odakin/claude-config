#!/usr/bin/env python3
"""verify-verbatim-move.py — 「移しただけ」 の変更を読まずに検算する: 指定 file から消えた行が、すべて移動先 (同じ file を含む) に追加行として現れるかを git の差分で数える。markdown link の深さの付け替えは --normalize-links で同一視する。

用途:
  - SESSION.md の bullet を archive へ退避した commit (memory-file-slimming.md #verbatim-retreat)。
    fold-dated-bullets.py は自分の書き込みを内部で検算するが、 手で移した・別の道具で移した変更はこれで確かめる。
  - 原稿の段落 MOVE commit (paper-audit.md #relocation-rebinding-sweep ルール 1 = verbatim-first) で、
    「MOVE:」 と名乗った commit に書き換えが混ざっていないか。 同じ file 内の移動も数える。
  2026-09-13: 40 bullet の退避を別 snippet で確かめ直した回と、 段落構成の MOVE を目で追った回から。

usage:
    python3 verify-verbatim-move.py --from SESSION.md --to SESSION-archive/2026-09.md [--rev A..B] [--normalize-links]
    python3 verify-verbatim-move.py --from paper.tex --to paper.tex --rev HEAD~1..HEAD      # 同じ file 内の MOVE
    python3 verify-verbatim-move.py --selftest

--rev を省くと HEAD と working tree の差分を見る (`--rev X` だけなら X と working tree)。 同じ commit で source の他の行も直したときは `--removed-prefix` で移した行だけに絞る。 空行は数えない。 多重集合で数える (同じ行が 2 回消えたら 2 回現れる必要)。
--from に指定した file の削除行のうち、 追加行 (全 --to の合計) で賄えないものを列挙し、 1 行でもあれば exit 1。
移動先が複数なら `--to` を繰り返す (`--to a --to b`)。 無い path・未追跡の file は数える前に exit 2 で止める
(git diff はどちらにも「差分なし」 を返し、 偽の FAIL / PASS になる)。
追加行が削除行より多いのは許す (要約や見出しを足すのは移動と両立する)。 書き換えを許さない検査なので、
移動と同時に文言を直した commit は FAIL が正しい (直すなら移動と別の commit にする)。
"""
from __future__ import annotations

import argparse
import collections
import re
import subprocess
import sys
import tempfile
from pathlib import Path

LINK_TARGET = re.compile(r"\]\((?:\.\./)+")


def _diff_lines(repo: Path, rev: str | None, path: str) -> tuple[list[str], list[str]]:
    args = ["git", "-C", str(repo), "diff", "--no-color", "-U0"]
    if rev:
        args.append(rev)
    args += ["--", path]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    removed, added = [], []
    for line in out.split("\n"):
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
    return removed, added


def normalize(line: str, links: bool) -> str:
    return LINK_TARGET.sub("](", line) if links else line


def path_problems(repo: Path, rev: str | None, paths: list[str]) -> list[str]:
    """差分を数える前に path を確かめる。 git diff は無い path にも未追跡の file にも「差分なし」 を返すので、
    そのまま数えると「移した行が現れない」 という偽の FAIL (移動先側) か偽の PASS (移動元側) になる。
    実測: `--to a.md,b.md` と 1 つに書き、 存在しない path「a.md,b.md」 として全行が missing と出た。"""
    ends = [x for x in (rev or "").split("..") if x] or ["HEAD"]
    out = []
    for path in paths:
        tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", path],
                                 capture_output=True).returncode == 0
        in_rev = any(subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{e}:{path}"],
                                    capture_output=True).returncode == 0 for e in ends)
        if tracked or in_rev:
            continue
        if (repo / path).exists():
            out.append(f"{path}: 未追跡 = git diff に出ない (`git add -N {path}` してから数える)")
        elif "," in path:
            out.append(f"{path}: 無い path。 移動先が複数なら --to を 1 path ずつ繰り返す (--to a --to b)")
        else:
            out.append(f"{path}: 無い path (working tree にも {' / '.join(ends)} にも無い)")
    return out


def verify(repo: Path, rev: str | None, src: str, dsts: list[str], links: bool,
           removed_prefix: str | None = None) -> tuple[list[str], int, int]:
    removed, added_src = _diff_lines(repo, rev, src)
    if removed_prefix is not None:
        removed = [x for x in removed if x.startswith(removed_prefix)]
    pool = collections.Counter()
    for d in dsts:
        _, added = _diff_lines(repo, rev, d) if d != src else (None, added_src)
        pool.update(normalize(x, links) for x in added if x.strip())
    missing = []
    want = [x for x in removed if x.strip()]
    for x in want:
        k = normalize(x, links)
        if pool[k] > 0:
            pool[k] -= 1
        else:
            missing.append(x)
    return missing, len(want), sum(pool.values())


def selftest() -> int:
    failed = []

    def expect(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failed.append(name)

    def git(repo, *a):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        git(repo, "init", "-q"); git(repo, "config", "user.name", "t"); git(repo, "config", "user.email", "t@t")
        (repo / "S.md").write_text("# S\n- **a** see [x](review/x.md)\n- **b** two\nkeep\n", encoding="utf-8")
        (repo / "arch").mkdir(); (repo / "arch" / "A.md").write_text("# A\n", encoding="utf-8")
        (repo / "p.tex").write_text("P1 first.\n\nP2 second.\n\nP3 third.\n", encoding="utf-8")
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "init")
        # move two bullets to the archive, re-basing the link, and add a summary line
        (repo / "S.md").write_text("# S\n- **summary**\nkeep\n", encoding="utf-8")
        (repo / "arch" / "A.md").write_text("# A\n\n## moved\n- **a** see [x](../review/x.md)\n- **b** two\n", encoding="utf-8")
        m, n, extra = verify(repo, None, "S.md", ["arch/A.md"], links=True)
        expect("archive move with link re-basing passes with --normalize-links", m == [] and n == 2)
        m, n, _ = verify(repo, None, "S.md", ["arch/A.md"], links=False)
        expect("... and names the re-based line without it", m == ["- **a** see [x](review/x.md)"])
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "move")
        # paragraph MOVE inside one file: P3 before P1
        (repo / "p.tex").write_text("P3 third.\n\nP1 first.\n\nP2 second.\n", encoding="utf-8")
        m, n, _ = verify(repo, None, "p.tex", ["p.tex"], links=False)
        expect("same-file paragraph MOVE passes", m == [] and n >= 1)
        # MOVE with a rewrite: fails and names the rewritten line
        (repo / "p.tex").write_text("P3 third, reworded.\n\nP1 first.\n\nP2 second.\n", encoding="utf-8")
        m, _, _ = verify(repo, None, "p.tex", ["p.tex"], links=False)
        expect("MOVE mixed with a rewrite fails and names the removed line", m == ["P3 third."])
        git(repo, "checkout", "--", "p.tex")
        # --rev form over the committed move
        m, n, _ = verify(repo, "HEAD~1..HEAD", "S.md", ["arch/A.md"], links=True)
        expect("--rev A..B checks a committed move", m == [] and n == 2)
        (repo / "S.md").write_text("# S (retitled)\n- **summary**\nkeep\n", encoding="utf-8")
        m, n, _ = verify(repo, "HEAD~1", "S.md", ["arch/A.md"], links=True)
        expect("an unrelated edit in the same source fails the plain check", m == ["# S"])
        m, n, _ = verify(repo, "HEAD~1", "S.md", ["arch/A.md"], links=True, removed_prefix="- **")
        expect("--removed-prefix limits the check to the moved bullets", m == [] and n == 2)
        pr = path_problems(repo, None, ["S.md", "arch/A.md,p.tex"])
        expect("a comma-joined --to is reported as a missing path with the repeat-the-flag hint (not as missing lines)",
               len(pr) == 1 and "--to を 1 path ずつ" in pr[0])
        (repo / "arch" / "new.md").write_text("- **a** see [x](../review/x.md)\n", encoding="utf-8")
        pr = path_problems(repo, "HEAD~1..HEAD", ["arch/new.md", "S.md"])
        expect("an untracked destination is reported (git diff would show nothing for it)",
               len(pr) == 1 and "git add -N" in pr[0])
    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--rev", help="A..B (default: HEAD vs working tree)")
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--to", dest="dsts", action="append", required=True)
    ap.add_argument("--normalize-links", action="store_true")
    ap.add_argument("--removed-prefix", help="only check removed lines starting with this (e.g. the folded bullets), "
                    "when the same commit also edited other lines of the source")
    a = ap.parse_args()
    probs = path_problems(a.repo, a.rev, [a.src] + [d for d in a.dsts if d != a.src])
    if probs:
        for x in probs:
            print("✗ " + x)
        return 2
    missing, n, extra = verify(a.repo, a.rev, a.src, a.dsts, a.normalize_links, a.removed_prefix)
    if missing:
        print(f"✗ {len(missing)} of {n} removed line(s) from {a.src} do not reappear in {', '.join(a.dsts)}:")
        for x in missing[:20]:
            print("  - " + x[:160])
        return 1
    print(f"✓ all {n} removed non-empty line(s) from {a.src} reappear in {', '.join(a.dsts)} "
          f"({extra} added line(s) beyond the move)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
