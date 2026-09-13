#!/usr/bin/env python3
r"""tex-first-use.py — Is a notation explained where the reader first meets it? Lists the first body uses of a regex with line and section, checks the first one against the line of the defining \label (a reference to that label near the use counts as a pointer), and lists \cref-type references to equations that are printed further down.

Why (2026-09-13): two author questions on one manuscript were answered with hand-written greps.
(1) "Is the (anti)symmetrization notation explained where it first appears?" Its defining equation sat
hundreds of lines below the first bracketed index group, and the first uses had no pointer to it.
(2) An equation cited by \cref before it was printed needed a gloss at the point of use.
check-abbreviations.py answers (1) for abbreviations only, and check-latex-crossrefs.py checks the form
of references, not their order. Convention = conventions/latex.md#notation-first-use.

Usage:
  tex-first-use.py paper.tex --pattern REGEX [--pattern REGEX]... [--exclude REGEX] [--defined-at LABEL]
                   [--window N] [--first N] [--include-abstract] [--stop-at REGEX]
  tex-first-use.py paper.tex --forward-refs [--ref-prefix eq:]...
  tex-first-use.py --selftest

Body = after \begin{document} (the whole file if absent), comments removed, the abstract skipped unless
--include-abstract, up to the first line matching --stop-at (e.g. '\\appendix'). One hit per line.
--exclude REGEX drops a match when REGEX also matches at the same position (e.g. '\^\{\(\d\)' for ^{(2)}).
--defined-at LABEL: exit 1 when the first use comes more than --window lines (default 3) before
\label{LABEL} and no reference to LABEL stands before it or within --window lines after it (a footnote at an
earlier, related notation that points to LABEL counts); exit 2 when the label is absent.
--forward-refs lists labels (default prefix eq:; --ref-prefix '' = all) that are referenced before the line
of their \label, with the first such use and the count. These are candidates to read, not errors: a forward
reference that says what the symbol is at that point is fine. They do not change the exit code.
"""
from __future__ import annotations

import argparse
import re
import sys

SECTION = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{(.*)")
REF = re.compile(r"\\(?:cref|Cref|ref|eqref|labelcref|autoref|cpageref|Cpageref|crefrange)\*?\s*\{([^}]*)\}")
LABEL = re.compile(r"\\label\s*\{([^}]*)\}")


def strip_comment(line: str) -> str:
    out, i = [], 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            out.append(line[i:i + 2])
            i += 2
            continue
        if line[i] == "%":
            break
        out.append(line[i])
        i += 1
    return "".join(out)


def body_lines(lines, include_abstract=False, stop_at=None):
    start = 0
    for i, l in enumerate(lines):
        if "\\begin{document}" in strip_comment(l):
            start = i + 1
            break
    stop = re.compile(stop_at) if stop_at else None
    in_abs = False
    for i in range(start, len(lines)):
        t = strip_comment(lines[i])
        if "\\end{document}" in t or (stop and stop.search(t)):
            break
        if not include_abstract:
            if "\\begin{abstract}" in t:
                in_abs = True
            if in_abs:
                if "\\end{abstract}" in t:
                    in_abs = False
                continue
        yield i + 1, t


def sections(lines):
    cur, appendix, in_body, out = "(before the first heading)", False, False, []
    for l in lines:
        t = strip_comment(l)
        in_body = in_body or "\\begin{document}" in t
        if in_body and re.match(r"\s*\\appendix\b", t):   # not \let\origappendix\appendix in the preamble
            appendix = True
        m = SECTION.search(t)
        if m:
            title, depth, end = m.group(2), 1, len(m.group(2))
            for k, ch in enumerate(title):
                depth += ch == "{"
                depth -= ch == "}"
                if depth == 0:
                    end = k
                    break
            cur = ("appendix " if appendix else "") + f"{m.group(1)} {title[:end].strip()}"
        out.append(cur)
    return out


def label_lines(lines):
    found = {}
    for i, l in enumerate(lines, 1):
        for m in LABEL.finditer(strip_comment(l)):
            found.setdefault(m.group(1).strip(), i)
    return found


def first_uses(lines, pattern, exclude=None, n=3, **body_kw):
    pat, exc, hits = re.compile(pattern), re.compile(exclude) if exclude else None, []
    for ln, t in body_lines(lines, **body_kw):
        for m in pat.finditer(t):
            if exc and exc.match(t, m.start()):
                continue
            hits.append((ln, t))
            break
        if len(hits) >= n:
            break
    return hits


def ref_line(lines, label, near, hi):
    """The reference to label closest to line `near`, among lines 1..hi."""
    found = [i for i in range(1, min(hi, len(lines)) + 1)
             for m in REF.finditer(strip_comment(lines[i - 1]))
             if label in (x.strip() for x in m.group(1).split(","))]
    return min(found, key=lambda i: abs(i - near)) if found else None


def check_definition(lines, hits, label, window, secs):
    d = label_lines(lines).get(label)
    if d is None:
        return 2, f"✗ \\label{{{label}}} not found"
    if not hits:
        return 0, f"no body use; \\label{{{label}}} at L{d}"
    ln = hits[0][0]
    if ln >= d or d - ln <= window:
        return 0, f"✓ first use L{ln} is at the definition \\label{{{label}}} L{d}"
    p = ref_line(lines, label, ln, ln + window)
    if p:
        return 0, f"✓ first use L{ln} precedes the definition L{d}; a reference to it stands at L{p}"
    return 1, (f"✗ first use L{ln} ({secs[ln - 1][:40]}) precedes the definition L{d} ({secs[d - 1][:40]}) "
               f"with no reference to {label} before it or within {window} lines after it: "
               f"explain the notation there or point to L{d}")


def forward_refs(lines, prefixes=("eq:",), **body_kw):
    labels, seen = label_lines(lines), {}
    for ln, t in body_lines(lines, **body_kw):
        for m in REF.finditer(t):
            for lab in (x.strip() for x in m.group(1).split(",")):
                if not lab or not any(lab.startswith(p) for p in prefixes):
                    continue
                d = labels.get(lab)
                if d and d > ln:
                    if lab in seen:
                        seen[lab][2] += 1
                    else:
                        seen[lab] = [ln, d, 1]
    return sorted((v[0], lab, v[1], v[2]) for lab, v in seen.items())


def selftest() -> int:
    failed = []

    def expect(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failed.append(name)

    doc = r"""\documentclass{article}
\newcommand{\x}{y}
\begin{document}
\begin{abstract}
Abstract uses $T_{[ab]}$.
\end{abstract}
\section{Intro}
% commented $T_{(ab)}$
We write $T_{[\mu\nu]}$ here.
Price 5\% of $F^{(2)}$ only.
See \cref{eq:later} and \cref{sec:later}.
Again \cref{eq:early,eq:later}.
\begin{equation} a = b \label{eq:early} \end{equation}
\section{Later}\label{sec:later}
\begin{equation}
T_{[ab]} = \tfrac12 (T_{ab} - T_{ba})
\label{eq:later}
\end{equation}
\appendix
\section{Conventions}
$S_{(ab)}$ is defined by
\begin{equation} S_{(ab)} = \tfrac12(S_{ab}+S_{ba}) \label{eq:sym} \end{equation}
\end{document}""".split("\n")
    secs = sections(doc)
    anti, sym, order = r"[_^]\{\s*\[", r"[_^]\{\s*\(", r"\^\{\(\d\)"
    expect("comments: escaped \\% kept, % and \\\\% cut",
           strip_comment(r"5\% of") == r"5\% of" and strip_comment("a % b") == "a "
           and strip_comment(r"x\\% c") == "x\\\\")
    h = first_uses(doc, anti)
    expect("abstract skipped by default: first bracket use at L9", bool(h) and h[0][0] == 9)
    expect("--include-abstract counts the abstract (L5)", first_uses(doc, anti, include_abstract=True)[0][0] == 5)
    expect("commented use ignored; without --exclude the order label ^{(2)} is the first paren use (L10)",
           first_uses(doc, sym)[0][0] == 10)
    hs = first_uses(doc, sym, exclude=order)
    expect("--exclude drops ^{(2)}: first paren use at L21", bool(hs) and hs[0][0] == 21)
    expect("section attribution: L9 in Intro, L21 in the appendix section",
           "Intro" in secs[8] and secs[20].startswith("appendix") and "Conventions" in secs[20])
    expect("use right at the defining equation passes", check_definition(doc, hs, "eq:sym", 3, secs)[0] == 0)
    code, msg = check_definition(doc, h, "eq:later", 3, secs)
    expect("early use with a \\cref to the definition nearby passes (pointer at L11)", code == 0 and "L11" in msg)
    code, msg = check_definition(doc, h, "eq:later", 1, secs)
    expect("the same use without a pointer inside the window fails", code == 1 and "L9" in msg and "L17" in msg)
    expect("missing label: exit 2", check_definition(doc, h, "eq:none", 3, secs)[0] == 2)
    expect("--stop-at \\appendix: no paren use left",
           first_uses(doc, sym, exclude=order, stop_at=r"\\appendix") == [])
    fr = forward_refs(doc)
    expect("forward refs (eq: only): eq:later first at L11 with 2 uses, eq:early at L12",
           fr == [(11, "eq:later", 17, 2), (12, "eq:early", 13, 1)])
    expect("--ref-prefix '' also lists sec:later", any(x[1] == "sec:later" for x in forward_refs(doc, [""])))
    doc2 = [r"\let\origappendix\appendix", r"\begin{document}", r"\section{A}",
            r"Notation\footnote{Parentheses denote symmetrization, \cref{eq:sym}.} for $T_{[ab]}$.",
            "a", "b", "c", "d", r"Then $S_{(ab)}$ appears.", "e", "f", "g", r"\appendix", r"\section{B}",
            r"\begin{equation} S_{(ab)} = S_{ba} \label{eq:sym} \end{equation}", r"\end{document}"]
    secs2 = sections(doc2)
    expect("a preamble \\let of \\appendix does not turn the body into an appendix",
           secs2[8] == "section A" and secs2[14].startswith("appendix"))
    code, msg = check_definition(doc2, first_uses(doc2, sym), "eq:sym", 3, secs2)
    expect("a pointer five lines before the first use counts (L4)", code == 0 and "L4" in msg)
    doc3 = doc2[:3] + [r"Notation for $T_{[ab]}$."] + doc2[4:]
    expect("without that pointer the same use fails",
           check_definition(doc3, first_uses(doc3, sym), "eq:sym", 3, sections(doc3))[0] == 1)
    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tex")
    ap.add_argument("--pattern", action="append", default=[])
    ap.add_argument("--exclude")
    ap.add_argument("--defined-at")
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--first", type=int, default=3)
    ap.add_argument("--include-abstract", action="store_true")
    ap.add_argument("--stop-at")
    ap.add_argument("--forward-refs", action="store_true")
    ap.add_argument("--ref-prefix", action="append")
    a = ap.parse_args()
    if not a.pattern and not a.forward_refs:
        ap.error("give --pattern and/or --forward-refs")
    if a.defined_at and not a.pattern:
        ap.error("--defined-at needs --pattern")
    lines = open(a.tex, encoding="utf-8").read().split("\n")
    kw = dict(include_abstract=a.include_abstract, stop_at=a.stop_at)
    secs, rc = sections(lines), 0
    for p in a.pattern:
        hits = first_uses(lines, p, a.exclude, a.first, **kw)
        print(f"pattern {p}")
        for ln, t in hits:
            print(f"  L{ln:<6}{secs[ln - 1][:48]:<50}{t.strip()[:110]}")
        if not hits:
            print("  (no body use)")
        if a.defined_at:
            code, msg = check_definition(lines, hits, a.defined_at, a.window, secs)
            print("  " + msg)
            rc = max(rc, code)
    if a.forward_refs:
        fr = forward_refs(lines, a.ref_prefix if a.ref_prefix is not None else ["eq:"], **kw)
        print(f"forward references: {len(fr)} label(s) cited before their \\label (read the first use for a gloss)")
        for ln, lab, d, cnt in fr:
            print(f"  L{ln:<6}{lab} -> \\label at L{d} ({secs[d - 1][:40]}); {cnt} use(s) before it")
    return rc


if __name__ == "__main__":
    sys.exit(main())
