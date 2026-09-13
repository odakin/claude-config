#!/usr/bin/env python3
"""scan-private-vocabulary.py — Audit a public repo for rare vocabulary it shares with your non-public repos (technical words, LaTeX control words, Japanese compounds, decimals): the reading list for paraphrased leaks that the verbatim gate cannot see; terminal output only, not a gate; --selftest

Why (2026-09-13): a sweep of two public convention repos for content taken from unpublished manuscripts. The
verbatim gate (check-unpublished-quote.py) stops copied sentences, but an example that was rewritten in one's own
words still carries the document's distinctive words: a model name, a macro, a parameter value. Listing the rare
tokens that a public repo shares with non-public repos gave the candidate list for that sweep; the same list is
what CLAUDE.md #non-identifier-content-leak asks for as "the term list of the case" before a hoist commit.

What it does:
  1. Repos = git work trees directly under BASE (default $CLAUDE_BASE, else ~/Claude).
     public = has .claude/public-repo.marker (the switch the public-repo gates use); non-public = the rest.
  2. Tokens per repo from tracked text files (git ls-files; symlinks, binaries, locked git-crypt blobs and files
     over 3 MB are skipped): words of >= 4 characters (lower-cased, hyphen-joined), LaTeX control words (\\foo),
     runs of >= 3 kanji/katakana, decimals with >= 3 decimal places.
  3. Candidates = tokens of the scanned public repo that occur in at least one source repo (default: every
     non-public repo; narrow with --source) and in at most --df-max repos outside the scanned ones.
     Rows (TSV): token, df, source repos, hits (file:count, or file:line in --diff / --staged mode).

Usage:
  scan-private-vocabulary.py --scan REPO [--scan REPO ...] [--df-max 8] [--base DIR] [--source NAME ...] [--exclude NAME ...]
  scan-private-vocabulary.py --scan REPO --diff A..B       only tokens on lines added in the range (file:line hits)
  scan-private-vocabulary.py --scan REPO --staged          only tokens on staged added lines (run before a hoist commit)
  scan-private-vocabulary.py --scan REPO --source-ext .tex --kinds word,control,decimal
                                                          manuscripts only, without Japanese runs (far fewer rows)
  scan-private-vocabulary.py --selftest

Read the output as a reading list, not as findings: published literature shares vocabulary with private
manuscripts all the time, and a rewritten example with no rare shared token is invisible here. Review remarks and
process history use ordinary words; search those by process words
(docs/convention-design-principles.md#sweep-null-needs-per-form-control).
The output names non-public repos and prints their vocabulary: keep it in the terminal or a scratch file, never
in a public repo or a commit message.
Exit: 0 = ran (with or without rows) / 2 = usage error.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = Path(".claude") / "public-repo.marker"
TEXT_EXTS = {".md", ".tex", ".py", ".yaml", ".yml", ".txt", ".sh", ".json", ".toml", ".m", ".wl", ".ipynb",
             ".csv", ".rst", ".html", ".js", ".ts", ""}
MAX_BYTES = 3_000_000
WORD = re.compile(r"(?<![A-Za-z0-9_\\])[A-Za-z][A-Za-z0-9]*(?:[-–][A-Za-z0-9]+)*")
CONTROL = re.compile(r"\\[A-Za-z]{2,}")
JAPANESE = re.compile(r"[一-鿿゠-ヿー]{3,}")
DECIMAL = re.compile(r"(?<![\d.])\d+\.\d{3,}(?![\d.])")
WARNING = "# local audit output: it names non-public repos and prints their vocabulary; do not paste it into a public repo"


KINDS = ("word", "control", "japanese", "decimal")


def tokens_of(text: str, kinds: tuple[str, ...] = KINDS) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    if "word" in kinds:
        for m in WORD.finditer(text):
            if len(m.group(0)) >= 4:
                c[m.group(0).lower()] += 1
    for kind, rx in (("control", CONTROL), ("japanese", JAPANESE), ("decimal", DECIMAL)):
        if kind in kinds:
            for m in rx.finditer(text):
                c[m.group(0)] += 1
    return c


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=300)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def work_trees(base: Path) -> list[Path]:
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / ".git").exists())


def readable_text(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        if path.suffix.lower() not in TEXT_EXTS:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if data.startswith(b"\x00GITCRYPT") or b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", "replace")


def repo_tokens(repo: Path, kinds: tuple[str, ...] = KINDS, source_exts: tuple[str, ...] = (),
                per_file: bool = False):
    """(all tokens, tokens of files with source_exts — or all when empty —, per-file counts)."""
    total: set[str] = set()
    source: set[str] = set()
    files: dict[str, collections.Counter] = {}
    for rel in git(repo, "ls-files", "-z").split("\0"):
        if not rel:
            continue
        text = readable_text(repo / rel)
        if text is None:
            continue
        counts = tokens_of(text, kinds)
        total.update(counts)
        if not source_exts or Path(rel).suffix.lower() in source_exts:
            source.update(counts)
        if per_file:
            files[rel] = counts
    return total, source, files


def added_lines(repo: Path, diff_range: str | None, staged: bool) -> list[tuple[str, int, str]]:
    args = ["diff", "--no-color", "--no-ext-diff", "-U0"]
    args += ["--cached"] if staged else [diff_range]
    out, path, line = [], None, 0
    for raw in git(repo, *args).splitlines():
        if raw.startswith("+++ "):
            path = None if raw[4:] == "/dev/null" else raw[6:] if raw.startswith("+++ b/") else raw[4:]
        elif raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path is not None:
            out.append((path, line, raw[1:]))
            line += 1
    return out


def scan(base: Path, scan_names: list[str], df_max: int, sources: list[str], exclude: list[str],
         diff_range: str | None = None, staged: bool = False, kinds: tuple[str, ...] = KINDS,
         source_exts: tuple[str, ...] = ()) -> list[tuple[str, int, str, str]]:
    trees = [p for p in work_trees(base) if p.name not in exclude]
    names = {p.name for p in trees}
    missing = [n for n in scan_names if n not in names]
    if missing:
        raise SystemExit(f"not a work tree under {base}: {', '.join(missing)}")
    non_public = {p.name for p in trees if not (p / MARKER).exists()}
    source_set = set(sources) if sources else non_public
    df: collections.Counter = collections.Counter()
    by_repo: dict[str, set[str]] = {}
    for p in trees:
        if p.name in scan_names:
            continue
        toks, src, _ = repo_tokens(p, kinds, source_exts)
        by_repo[p.name] = src
        df.update(toks)
    rows = []
    for name in scan_names:
        repo = base / name
        if diff_range or staged:
            hits: dict[str, list[str]] = collections.defaultdict(list)
            for path, line, text in added_lines(repo, diff_range, staged):
                for tok in tokens_of(text, kinds):
                    hits[tok].append(f"{name}/{path}:{line}")
            candidates = hits
        else:
            _, _, files = repo_tokens(repo, kinds, per_file=True)
            hits = collections.defaultdict(list)
            for rel, counts in files.items():
                for tok, n in counts.items():
                    hits[tok].append(f"{name}/{rel}:{n}")
            candidates = hits
        for tok, where in candidates.items():
            srcs = sorted(r for r in source_set if tok in by_repo.get(r, ()))
            if not srcs or df[tok] > df_max:
                continue
            rows.append((tok, df[tok], ",".join(srcs), " ".join(sorted(set(where)))))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows


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
        base = Path(td)
        texts = {
            "pub": "# notes\nThe capacitor flux law with \\fluxcap at 0.4271 and 架空連結語彙 in common words.\n"
                   "version 1.2.3 and common words\n",
            "pub2": "common words only\n",
            "privA": "Private capacitor draft: \\fluxcap = 0.4271, 架空連結語彙, common words.\n",
            "privB": "unrelated common words\n",
            "privC": "common words again\n",
        }
        for name, body in texts.items():
            repo = base / name
            repo.mkdir()
            run_git(repo, "init", "-q")
            (repo / "doc.md").write_text(body, encoding="utf-8")
            if name.startswith("pub"):
                (repo / ".claude").mkdir()
                (repo / ".claude" / "public-repo.marker").write_text("public\n", encoding="utf-8")
            run_git(repo, "add", "-A")
            run_git(repo, "commit", "-q", "-m", "init")
        (base / "privA" / "locked.md").write_bytes(b"\x00GITCRYPT\x00lockedterm lockedterm")
        run_git(base / "privA", "add", "locked.md")
        (base / "pub" / "extra.md").write_text("lockedterm appears here\n", encoding="utf-8")
        run_git(base / "pub", "add", "extra.md")
        run_git(base / "pub", "commit", "-q", "-m", "extra")
        (base / "notes-dir").mkdir()  # not a work tree: ignored

        rows = scan(base, ["pub"], df_max=2, sources=[], exclude=[])
        toks = {r[0]: r for r in rows}
        check("a rare word shared with a non-public repo is listed", "capacitor" in toks)
        check("a LaTeX control word is listed", "\\fluxcap" in toks)
        check("a decimal with >= 3 places is listed", "0.4271" in toks)
        check("a Japanese compound is listed", "架空連結語彙" in toks)
        check("the source column names the non-public repo", toks.get("capacitor", ("", 0, ""))[2] == "privA")
        check("hits carry file:count in tree mode", "pub/doc.md:1" in toks.get("capacitor", ("", 0, "", ""))[3])
        check("a word in more repos than --df-max is dropped", "common" not in toks and "words" not in toks)
        check("a version string is not a decimal token", "1.2.3" not in toks and "2.3" not in toks)
        check("a locked git-crypt blob contributes nothing  [foil: encrypted file read as text]",
              "lockedterm" not in toks)
        check("the other public repo is not a source", all("pub2" not in r[2] for r in rows))
        check("--source narrows the source side", scan(base, ["pub"], 2, ["privB"], []) == [])
        check("--exclude removes a repo from sources and df",
              "capacitor" not in {r[0] for r in scan(base, ["pub"], 2, [], ["privA"])})
        check("--kinds keeps only the chosen token kinds",
              {r[0] for r in scan(base, ["pub"], 2, [], [], kinds=("japanese",))} == {"架空連結語彙"})
        (base / "privA" / "draft.tex").write_text("\\fluxcap in the manuscript\n", encoding="utf-8")
        run_git(base / "privA", "add", "draft.tex")
        tex_only = {r[0] for r in scan(base, ["pub"], 2, [], [], source_exts=(".tex",))}
        check("--source-ext counts a source token only from files with that suffix",
              "\\fluxcap" in tex_only and "capacitor" not in tex_only)

        with open(base / "pub" / "doc.md", "a", encoding="utf-8") as fh:
            fh.write("staged line with capacitor only\n")
        run_git(base / "pub", "add", "doc.md")
        staged = {r[0]: r for r in scan(base, ["pub"], 2, [], [], staged=True)}
        check("--staged lists only tokens on added lines", set(staged) == {"capacitor"})
        added_at = texts["pub"].count("\n") + 1
        check("--staged hits carry file:line of the added line",
              staged.get("capacitor", ("", 0, "", ""))[3] == f"pub/doc.md:{added_at}")
        run_git(base / "pub", "commit", "-q", "-m", "more")
        ranged = {r[0] for r in scan(base, ["pub"], 2, [], [], diff_range="HEAD~1..HEAD")}
        check("--diff A..B lists only tokens added in the range", ranged == {"capacitor"})

        me = os.path.abspath(__file__)
        r = subprocess.run([sys.executable, me, "--base", str(base), "--scan", "pub", "--df-max", "2"],
                           capture_output=True, text=True)
        check("CLI prints the local-only warning first", r.returncode == 0 and r.stdout.startswith(WARNING))
        r = subprocess.run([sys.executable, me, "--base", str(base)], capture_output=True, text=True)
        check("CLI without --scan is a usage error", r.returncode == 2)
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scan", action="append", default=[], metavar="REPO", help="public repo name under BASE")
    ap.add_argument("--base", type=Path, default=Path(os.environ.get("CLAUDE_BASE", str(Path.home() / "Claude"))))
    ap.add_argument("--df-max", type=int, default=8, help="drop tokens found in more repos than this (outside --scan)")
    ap.add_argument("--source", action="append", default=[], metavar="NAME", help="count only these repos as sources")
    ap.add_argument("--exclude", action="append", default=[], metavar="NAME", help="ignore this repo entirely")
    ap.add_argument("--kinds", default=",".join(KINDS),
                    help="comma list of token kinds: " + ",".join(KINDS) + " (default: all)")
    ap.add_argument("--source-ext", action="append", default=[], metavar="EXT",
                    help="count a token as coming from a source repo only when it occurs in files with this "
                         "suffix, e.g. .tex for manuscripts (repeatable; default: every text file)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--diff", metavar="A..B", help="only tokens on lines added in this range")
    mode.add_argument("--staged", action="store_true", help="only tokens on staged added lines")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.scan:
        ap.error("--scan REPO is required")
    kinds = tuple(k for k in (s.strip() for s in a.kinds.split(",")) if k)
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        ap.error(f"unknown --kinds: {', '.join(unknown)} (choose from {', '.join(KINDS)})")
    exts = tuple(e.lower() if e.startswith(".") else "." + e.lower() for e in a.source_ext)
    rows = scan(a.base.expanduser(), a.scan, a.df_max, a.source, a.exclude, a.diff, a.staged, kinds, exts)
    print(WARNING)
    for row in rows:
        print("\t".join(str(c) for c in row))
    print(f"# {len(rows)} candidate token(s); read them, they are not findings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
