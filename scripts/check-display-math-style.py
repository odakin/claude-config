#!/usr/bin/env python3
"""Display-math house-style gate for LaTeX manuscripts (2026-09-09).

Two rules from the odakin-prefs paper-style `#display-math-house-style`
(2026-07-20 author rulings, violated again on 2026-09-08 in a new appendix):

  1. inside display math the fraction is \\frac, never \\tfrac
     ("\\tfrac in a display only makes it small"; \\tfrac is for inline math
     and table cells);
  2. several equations on one display row are aligned with `&=` + bare `&`
     (rl columns), not separated by \\qquad; \\qquad is for condition
     modifiers only (`, \\qquad n \\ge 3`).

Display regions = the amsmath environments (align, align*, equation, equation*,
gather, gather*, multline, multline*, eqnarray, eqnarray*, flalign) plus
wrapper macros that hide such an environment (default `\\al{...}` and
`\\als{...}`; override with --wrapper a,b,c).  Table environments are not
display regions, so a \\tfrac in a tabular cell is not flagged.

Rule 2 heuristic per row (rows split at `\\\\` and `\\nn`): flag when the row
contains \\qquad, has at least two relation signs (`=`, `:=`, `\\equiv`,
`\\supset`, `\\simeq`, `\\approx`, `\\ne`), and the number of relation signs
exceeds the number of `&`.  A row `A &= B, \\qquad C = D` is flagged (the
second equation is not aligned); `x = y, \\qquad n \\ge 3` is not.

Usage:
  check-display-math-style.py paper.tex [more.tex ...] [--wrapper al,als]
  check-display-math-style.py --selftest

Exit code 1 when any finding is reported (so it can gate a build), 0 otherwise.
Findings are heuristics: read them, do not auto-fix.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ENVS = ("align", "align*", "equation", "equation*", "gather", "gather*", "multline",
        "multline*", "eqnarray", "eqnarray*", "flalign", "flalign*")
REL = re.compile(r"(?<![<>!:])=|:=|\\equiv\b|\\supset\b|\\simeq\b|\\approx\b|\\ne\b")


def _strip_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        i = 0
        while True:
            k = line.find("%", i)
            if k < 0:
                break
            if k > 0 and line[k - 1] == "\\":
                i = k + 1
                continue
            line = line[:k]
            break
        out.append(line)
    return "\n".join(out)


def _balanced_arg(text: str, start: int) -> int:
    """`start` points at '{'; return index just past the matching '}' (or -1)."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def display_regions(text: str, wrappers: tuple[str, ...]) -> list[tuple[int, int, str]]:
    """Return (start, end, kind) of every display region (character offsets)."""
    regions: list[tuple[int, int, str]] = []
    for env in ENVS:
        e = re.escape(env)
        for m in re.finditer(r"\\begin\{" + e + r"\}", text):
            end = text.find("\\end{" + env + "}", m.end())
            if end < 0:
                continue
            regions.append((m.end(), end, env))
    for w in wrappers:
        for m in re.finditer(r"\\" + re.escape(w) + r"(?![A-Za-z])\s*\{", text):
            brace = text.find("{", m.start())
            end = _balanced_arg(text, brace)
            if end < 0:
                continue
            regions.append((brace + 1, end - 1, "\\" + w + "{}"))
    regions.sort()
    return regions


def check_text(text: str, wrappers: tuple[str, ...] = ("al", "als")) -> list[tuple[int, str]]:
    """Return (line number, message) findings for one file's text."""
    clean = _strip_comments(text)
    findings: list[tuple[int, str]] = []
    for start, end, kind in display_regions(clean, wrappers):
        body = clean[start:end]
        base_line = clean.count("\n", 0, start) + 1
        for m in re.finditer(r"\\tfrac(?![A-Za-z])", body):
            findings.append((base_line + body.count("\n", 0, m.start()),
                             f"\\tfrac inside display ({kind}); house style = \\frac"))
        # rule 2: rows (split at \\ and \nn, keeping exact offsets)
        starts = [0] + [m.end() for m in re.finditer(r"\\\\|\\nn(?![A-Za-z])", body)]
        ends = [m.start() for m in re.finditer(r"\\\\|\\nn(?![A-Za-z])", body)] + [len(body)]
        for s, e in zip(starts, ends):
            row = body[s:e]
            q = row.find("\\qquad")
            if q < 0:
                continue
            rels = len(REL.findall(row))
            amps = row.count("&")
            if rels >= 2 and rels > amps:
                line = base_line + body.count("\n", 0, s + q)
                findings.append((line, f"\\qquad separates {rels} relations on one row of {kind} "
                                       f"(house style = `&=` + bare `&` rl alignment)"))
    return sorted(set(findings))


def selftest() -> int:
    ok = True

    def expect(cond: bool, name: str) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    good = r"""
Text with inline $\tfrac12$ is fine.
\al{
a	&=	\frac12 b,	&
c	&:=	d,
	\label{eq:x}
}
\begin{equation}
x = y, \qquad n \ge 3
\end{equation}
\begin{tabular}{ll}
$\tfrac14 b_0$ & ok \\
\end{tabular}
% \al{ \tfrac12 } commented out
"""
    expect(check_text(good) == [], "clean file has no findings")
    bad = r"""
\al{
b_{0}=4,\qquad
b_{2}=-\tfrac13 R,\qquad
b_{4}=\tfrac1{360} X,
	\label{eq:y}
}
\begin{align}
A &= B, \qquad C = D \\
E &= F
\end{align}
\als{ p = \tfrac{1}{2} q }
"""
    f = check_text(bad)
    msgs = [m for _, m in f]
    expect(sum("tfrac" in m for m in msgs) == 3, f"three \\tfrac findings (got {sum('tfrac' in m for m in msgs)})")
    expect(sum("qquad" in m for m in msgs) == 2, f"two \\qquad-row findings (got {sum('qquad' in m for m in msgs)})")
    expect(any(ln == 3 for ln, m in f if "qquad" in m), "row finding carries the row's line number")
    custom = r"\dm{ u = \tfrac12 v }"
    expect(check_text(custom, ("dm",)) != [] and check_text(custom) == [], "wrapper list is configurable")
    nested = r"\al{ \pn{\frac{a}{b}} = c \qquad \text{and} \qquad d \ne e }"
    expect(len(check_text(nested)) == 1, "nested braces parsed; one row finding")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--wrapper", default="al,als", help="comma list of display wrapper macro names (default al,als)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.files:
        ap.error("give at least one .tex file or --selftest")
    wrappers = tuple(w.strip() for w in a.wrapper.split(",") if w.strip())
    total = 0
    for f in a.files:
        text = Path(f).read_text(encoding="utf-8")
        for ln, msg in check_text(text, wrappers):
            print(f"{f}:{ln}: {msg}")
            total += 1
    print(f"{'FAIL' if total else 'PASS'}: {total} finding(s) in {len(a.files)} file(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
