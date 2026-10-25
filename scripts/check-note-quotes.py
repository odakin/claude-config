#!/usr/bin/env python3
r"""check-note-quotes.py — Check that a review note's quotations of a manuscript are verbatim and sit on the lines the note cites: every 「…」 (or "…" / “…”) fragment must be a substring of a source file, and a `:NNN「…」` citation must find the fragment on line NNN; --selftest.

Why: a proposal note, referee report or checklist locates each finding by quoting the source. A paraphrase
dressed as a quotation (a dropped `~\cite{…}` or `\emph{…}`, a table cell written as "Column: value") sends
the authors looking for text that does not exist, and a citation whose line number has drifted points at the
wrong sentence. Checking by eye misses both (実測: a note written with the source open still carried
paraphrases dressed as quotations).

What counts as a quotation:
  * Japanese corner brackets 「…」 (default), plus "…" and “…” with --ascii-quotes.
  * Inside a quotation, an ellipsis ("..." or "…") separates fragments; each fragment is checked alone.
  * --only-lines REGEX restricts the check to note lines that match (e.g. item headers '^\*\*').
  * A citation is `:NNN` written immediately before the opening bracket (`/ :120「…」`); the first fragment
    must occur on line NNN of one of the --cite-source files (several files = the note mixes them).
Fragments shorter than --min-chars (default 1) are skipped.

Usage:
  python3 check-note-quotes.py --note NOTE.md --source draft.tex [--source supp.tex]
                               [--cite-source draft.tex ...] [--only-lines REGEX] [--ascii-quotes]
Exit: 0 = all verbatim / 1 = a fragment or citation does not match / 2 = usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

JP_QUOTE = re.compile(r"「(.+?)」")
ASCII_QUOTES = (re.compile(r'"([^"\n]+?)"'), re.compile(r"“([^”\n]+?)”"))
ELLIPSIS = re.compile(r"\.\.\.|…")
CITE = re.compile(r":(\d+)\s*$")


def fragments(span: str, min_chars: int) -> list[str]:
    out = []
    for part in ELLIPSIS.split(span):
        part = part.strip().strip(".").strip()
        if len(part) >= min_chars:
            out.append(part)
    return out


def quotations(line: str, ascii_quotes: bool) -> list[tuple[int, str]]:
    """(start offset, inner text) of each quotation on the line."""
    found = [(m.start(), m.group(1)) for m in JP_QUOTE.finditer(line)]
    if ascii_quotes:
        for rx in ASCII_QUOTES:
            found += [(m.start(), m.group(1)) for m in rx.finditer(line)]
    return sorted(found)


def check(note: str, sources: list[str], cite_sources: list[list[str]], *,
          only_lines: str | None = None, ascii_quotes: bool = False,
          min_chars: int = 1) -> list[str]:
    """Returns one message per problem (empty = all verbatim)."""
    problems = []
    corpus = "\n".join(sources)
    only = re.compile(only_lines) if only_lines else None
    for n, line in enumerate(note.splitlines(), 1):
        if only and not only.search(line):
            continue
        for start, span in quotations(line, ascii_quotes):
            frags = fragments(span, min_chars)
            for f in frags:
                if f not in corpus:
                    problems.append(f"note:{n}: not verbatim: {f[:100]!r}")
            m = CITE.search(line[:start])
            if m and frags and cite_sources:
                ln = int(m.group(1))
                hit = any(0 < ln <= len(lines) and frags[0] in lines[ln - 1]
                          for lines in cite_sources)
                if not hit:
                    problems.append(f"note:{n}: cited line {ln} does not contain {frags[0][:60]!r}")
    return problems


def selftest() -> int:
    src = ("intro line\n"
           "The widget count is $n=4.20$ in the blue box.\n"
           "A red lamp means one thing~\\cite{X} only.\n"
           "Columns & apples; pears\n")
    note = ("**1.** / :2「The widget count is $n=4.20$」\n"                     # ok + cite ok
            "**2.** / :3「A red lamp means one thing only」\n"                    # dropped ~\cite -> not verbatim
            "**3.** / :2「A red lamp means ... only」\n"                          # fragments ok, cite wrong line
            "**4.** 「Columns: apples; pears」\n"                                 # paraphrased cell
            "plain prose 「not checked here」 because of --only-lines\n"
            '**5.** "widget count" ascii\n')
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "src.tex"
        p.write_text(src, encoding="utf-8")
        lines = src.splitlines()
        probs = check(note, [src], [lines], only_lines=r"^\*\*")
        ok = True

        def expect(label, cond):
            nonlocal ok
            print(("ok   " if cond else "FAIL ") + label)
            ok &= cond

        expect("verbatim quote with a correct citation passes",
               not any("note:1" in m for m in probs))
        expect("a dropped \\cite is reported", any("note:2: not verbatim" in m for m in probs))
        expect("ellipsis fragments pass, a wrong line citation is reported",
               any("note:3: cited line 2" in m for m in probs)
               and not any("note:3: not verbatim" in m for m in probs))
        expect("a paraphrased table cell is reported", any("note:4: not verbatim" in m for m in probs))
        expect("--only-lines skips other lines", not any("note:5" in m for m in probs))
        expect("ascii quotes are off by default", not any("note:6" in m for m in probs))
        probs2 = check(note, [src], [lines], only_lines=r"^\*\*", ascii_quotes=True)
        expect("--ascii-quotes checks \"…\" too (verbatim here)", not any("note:6" in m for m in probs2))
        expect("min-chars skips short fragments",
               not check("「xy」", ["zz"], [], min_chars=3))
        rc = main(["--note", str(p), "--source", str(p)])
        expect("CLI exit 0 when the note quotes nothing", rc == 0)
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--note", type=Path)
    ap.add_argument("--source", type=Path, action="append", default=[])
    ap.add_argument("--cite-source", type=Path, action="append", default=[],
                    help="files whose line numbers the note cites (default: the --source files)")
    ap.add_argument("--only-lines", help="check only note lines matching this regex")
    ap.add_argument("--ascii-quotes", action="store_true", help='also check "…" and “…”')
    ap.add_argument("--min-chars", type=int, default=1)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.note or not a.source:
        ap.error("--note and at least one --source are required")
    read = lambda p: p.read_text(encoding="utf-8", errors="replace")
    sources = [read(p) for p in a.source]
    cites = [read(p).splitlines() for p in (a.cite_source or a.source)]
    probs = check(read(a.note), sources, cites, only_lines=a.only_lines,
                  ascii_quotes=a.ascii_quotes, min_chars=a.min_chars)
    for m in probs:
        print(m)
    print(f"{len(probs)} problem(s)")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
