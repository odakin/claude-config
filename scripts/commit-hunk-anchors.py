#!/usr/bin/env python3
"""commit-hunk-anchors.py — Where did each hunk of a commit land? file, new-side line and the nearest section anchor (Markdown <a id>) or Python def/class, without printing any changed text, so a cleanup or leak ledger can cite locations only; --selftest

Why (2026-09-13): the record of a public-repo cleanup must not repeat what was removed. A results table of
92 rows (file / section anchor / class / commit) was filled from this kind of listing; filling it by reading
the diffs invites copying the removed wording into the record, and from there into commit messages.

Output (TSV): commit, file, new-side start line, location
  location = '#<anchor>'            nearest preceding <a id="..."> in a Markdown file, when no heading lies
                                    between it and the hunk (heading text is never printed)
             'heading L<n> (no anchor)[ after #<anchor>]'   the section has a heading without an anchor
             'def <name>' / 'class <name>'                   nearest preceding Python definition
             'module docstring' / 'module top'               Python hunks before any definition
             'line <n>'                                      other text files
             'deleted file' / 'binary'
--summary prints one row per (file, location) with the number of hunks instead.

Usage:
  commit-hunk-anchors.py [--repo DIR] REV [REV ...]      REV = a commit or an A..B range
  commit-hunk-anchors.py [--repo DIR] --summary A..B
  commit-hunk-anchors.py --selftest
"""
from __future__ import annotations

import argparse
import ast
import collections
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ANCHOR = re.compile(r'<a id="([^"]+)"')
HEADING = re.compile(r"^#{1,6}\s")
DEFN = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr.decode("utf-8", "replace").strip() or f"git {' '.join(args)} failed")
    return r.stdout.decode("utf-8", "replace")


def commits(repo: Path, rev: str) -> list[str]:
    if ".." in rev:
        return [c for c in git(repo, "rev-list", "--reverse", rev).split() if c]
    return [git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").strip()]


def markdown_location(lines: list[str], start: int) -> str:
    anchor = anchor_line = heading_line = None
    for i in range(min(start, len(lines)) - 1, -1, -1):
        if anchor is None:
            m = ANCHOR.search(lines[i])
            if m:
                anchor, anchor_line = m.group(1), i + 1
        if heading_line is None and HEADING.match(lines[i]):
            heading_line = i + 1
        if anchor is not None and heading_line is not None:
            break
    if anchor is not None and (heading_line is None or anchor_line >= heading_line):
        return f"#{anchor}"
    if heading_line is not None:
        return f"heading L{heading_line} (no anchor)" + (f" after #{anchor}" if anchor else "")
    return "before any heading"


def python_location(text: str, lines: list[str], start: int) -> str:
    for i in range(min(start, len(lines)) - 1, -1, -1):
        m = DEFN.match(lines[i])
        if m:
            return f"{'class' if lines[i].lstrip().startswith('class') else 'def'} {m.group(1)}"
    try:
        body = ast.parse(text).body
    except SyntaxError:
        body = []
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str) and start <= (body[0].end_lineno or 0):
        return "module docstring"
    return "module top"


def hunks(repo: Path, commit: str) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    path = None
    deleted = False
    cache: dict[str, tuple[str, list[str]]] = {}
    for raw in git(repo, "show", "--no-color", "--no-ext-diff", "--unified=0", "--format=", commit).splitlines():
        if raw.startswith("diff --git "):
            path, deleted = None, False
        elif raw.startswith("Binary files "):
            m = re.search(r" and (?:b/)?(.+) differ$", raw)
            rows.append((m.group(1) if m else "?", 0, "binary"))
        elif raw.startswith("--- ") and raw[4:].strip() != "/dev/null":
            path = raw[6:] if raw.startswith("--- a/") else raw[4:]
        elif raw.startswith("+++ "):
            if raw[4:].strip() == "/dev/null":
                deleted = True
                rows.append((path or "?", 0, "deleted file"))
            else:
                path = raw[6:] if raw.startswith("+++ b/") else raw[4:]
        elif raw.startswith("@@") and path and not deleted:
            m = HUNK.match(raw)
            if not m:
                continue
            start = max(int(m.group(1)), 1)
            if path not in cache:
                text = git(repo, "show", f"{commit}:{path}")
                cache[path] = (text, text.splitlines())
            text, lines = cache[path]
            if path.endswith(".md"):
                loc = markdown_location(lines, start)
            elif path.endswith(".py"):
                loc = python_location(text, lines, start)
            else:
                loc = f"line {start}"
            rows.append((path, start, loc))
    return rows


def report(repo: Path, revs: list[str], summary: bool) -> list[str]:
    out = []
    counts: collections.Counter = collections.Counter()
    for rev in revs:
        for c in commits(repo, rev):
            short = c[:7]
            for path, line, loc in hunks(repo, c):
                if summary:
                    counts[(path, loc)] += 1
                else:
                    out.append(f"{short}\t{path}\t{line}\t{loc}")
    if summary:
        out = [f"{n}\t{path}\t{loc}" for (path, loc), n in sorted(counts.items())]
    return out


def selftest() -> int:
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    env = dict(os.environ, GIT_AUTHOR_NAME="selftest", GIT_AUTHOR_EMAIL="selftest@example.invalid",
               GIT_COMMITTER_NAME="selftest", GIT_COMMITTER_EMAIL="selftest@example.invalid")

    def run_git(repo: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *args],
                       check=True, capture_output=True, env=env)

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        run_git(repo, "init", "-q")
        doc = ["# Title", "", '## <a id="first"></a>First section', "", "alpha", "beta", "",
               "## Second section without anchor", "", "gamma", "", '- <a id="inline-item"></a>**item**', "delta"]
        (repo / "doc.md").write_text("\n".join(doc) + "\n", encoding="utf-8")
        code = ['"""Module docstring', "second line", '"""', "import os", "", "", "def work():", "    return 1",
                "", "", "class Box:", "    size = 2"]
        (repo / "tool.py").write_text("\n".join(code) + "\n", encoding="utf-8")
        (repo / "data.txt").write_text("one\ntwo\n", encoding="utf-8")
        (repo / "old.md").write_text("gone\n", encoding="utf-8")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", "init")

        secret = "SENTINELWORD"
        doc2 = doc[:]
        doc2[4] = f"alpha {secret}"            # under #first
        doc2[9] = f"gamma {secret}"            # under a heading without anchor
        doc2[12] = f"delta {secret}"           # under the inline anchor
        (repo / "doc.md").write_text("\n".join(doc2) + "\n", encoding="utf-8")
        code2 = code[:]
        code2[1] = f"second {secret}"          # docstring
        code2[7] = f"    return 2  # {secret}"  # in def work
        code2[11] = f"    size = 3  # {secret}"  # in class Box
        (repo / "tool.py").write_text("\n".join(code2) + "\n", encoding="utf-8")
        (repo / "data.txt").write_text(f"one\n{secret}\n", encoding="utf-8")
        (repo / "img.bin").write_bytes(b"\x00\x01\x02" * 10)
        (repo / "old.md").unlink()
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", "change")

        rows = report(repo, ["HEAD"], summary=False)
        text = "\n".join(rows)
        locs = {(r.split("\t")[1], r.split("\t")[3]) for r in rows}
        check("a hunk under an anchored heading reports the anchor", ("doc.md", "#first") in locs)
        check("a hunk under a heading without an anchor says so, with the earlier anchor",
              ("doc.md", "heading L8 (no anchor) after #first") in locs)
        check("an inline list anchor counts as the nearest anchor", ("doc.md", "#inline-item") in locs)
        check("a Python hunk inside the module docstring", ("tool.py", "module docstring") in locs)
        check("a Python hunk after def reports the def", ("tool.py", "def work") in locs)
        check("a Python hunk after class reports the class", ("tool.py", "class Box") in locs)
        check("other text files report the line", ("data.txt", "line 2") in locs)
        check("a binary file is listed as binary", ("img.bin", "binary") in locs)
        check("a deleted file is listed as deleted", ("old.md", "deleted file") in locs)
        check("no changed text is printed  [foil: a ledger row that repeats the removed wording]", secret not in text)
        check("heading text is not printed", "Second section" not in text and "First section" not in text)
        summary = report(repo, ["HEAD~1..HEAD"], summary=True)
        check("--summary counts hunks per (file, location) over a range",
              "1\tdoc.md\t#first" in summary and len(summary) == len(set(locs)))
        me = os.path.abspath(__file__)
        r = subprocess.run([sys.executable, me, "--repo", str(repo), "HEAD"], capture_output=True, text=True)
        check("CLI prints the same rows", r.returncode == 0 and r.stdout.strip().splitlines() == rows)
        r = subprocess.run([sys.executable, me, "--repo", str(repo)], capture_output=True, text=True)
        check("CLI without REV is a usage error", r.returncode == 2)
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("revs", nargs="*", metavar="REV")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--summary", action="store_true", help="one row per (file, location) with the hunk count")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.revs:
        ap.error("REV is required (a commit or an A..B range)")
    for row in report(a.repo, a.revs, a.summary):
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
