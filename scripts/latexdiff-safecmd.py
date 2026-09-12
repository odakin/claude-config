#!/usr/bin/env python3
"""Derive latexdiff's --append-safecmd list from the manuscript preamble.

latexdiff wraps changed math tokens in \\DIFadd{..}/\\DIFdel{..} only if every
command inside the token is on its "safe command" list.  A user macro that is
not on the list (a user macro taking arguments, say ``\\pn{..}``) is treated as
unsafe: the old form is commented out with %DIFDELCMD and the new form is
inserted *without* markup, so a change that lives only inside such a macro is
invisible in the diff PDF (silent miss, probed 2026-09-08).  A manuscript's own
math/text macros are all safe to colour.

This script prints the comma-separated list of names of all macros defined in
the preamble (\\newcommand, \\renewcommand, \\providecommand, \\DeclareMathOperator,
\\def), minus the ones that expand-display-math.py expands away (**derived from
the same file**, not hard-coded) and minus review-colour / structural names that
must never be wrapped.  scripts/latexdiff-review-snapshot.sh passes the list to
latexdiff --append-safecmd.

Usage: latexdiff-safecmd.py paper.tex        -> prints "pn,Paren,os,..."
       latexdiff-safecmd.py --selftest
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NEVER_SAFE = {
    "red", "blue", "green", "magenta", "cyan", "orange", "yellow",  # review colouring (cleaned anyway)
    "appendix", "maketitle", "section", "subsection", "label", "cite", "ref", "cref",  # structural
}
DEF_RE = re.compile(
    r"^\s*\\(?:re|provide)?(?:newcommand|command)\*?\s*\{?\\([A-Za-z]+)\}?"
    r"|^\s*\\DeclareMathOperator\*?\s*\{\\([A-Za-z]+)\}"
    r"|^\s*\\def\s*\\([A-Za-z]+)",
    re.M,
)


def expanded_names(text):
    """Names expand-display-math.py expands away (wrappers + row breaks), derived from this text.

    Asking the expander keeps the two scripts from drifting apart; if it is missing
    (script copied out alone) nothing is excluded, which only over-colours.
    """
    exp = os.path.join(HERE, "expand-display-math.py")
    if not os.path.exists(exp):
        return set()
    fd, path = tempfile.mkstemp(suffix=".tex")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        out = subprocess.run([sys.executable, exp, "--json", path],
                             capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(path)
    d = json.loads(out)
    return set(d.get("wrappers", {})) | set(d.get("rowbreaks", {}))


def safe_names(text):
    body = text.split("\\begin{document}", 1)[0]
    expanded = expanded_names(text)
    names = []
    for m in DEF_RE.finditer(body):
        name = next(g for g in m.groups() if g)
        if name in expanded or name in NEVER_SAFE or name in names:
            continue
        names.append(name)
    return names


def _selftest():
    src = (
        "\\newcommand{\\pn}[1]{(#1)}\n\\renewcommand{\\vec}[1]{\\boldsymbol{#1}}\n"
        "\\DeclareMathOperator{\\tr}{tr}\n\\def\\bb{\\mathbf{b}}\n"
        "\\newcommand{\\al}[1]{\\begin{align}#1\\end{align}}\n\\newcommand{\\nn}{\\nonumber\\\\}\n"
        "\\newcommand{\\red}[1]{\\textcolor{red}{#1}}\n% \\newcommand{\\hidden}{x}\n"
        "\\renewcommand{\\appendix}{\\clearpage}\n"
        "\\begin{document}\n\\newcommand{\\late}{y}\n"
    )
    got = safe_names(src)
    want = ["pn", "vec", "tr", "bb"]
    ok = got == want
    print(("PASS" if ok else "FAIL") + " safe_names: %r" % got + ("" if ok else " want %r" % want))
    # the wrapper/row-break exclusion must come from the file, not from a fixed list:
    # rename them and the new names must be excluded instead.
    src2 = src.replace("\\al}", "\\eqq}").replace("\\nn}", "\\rb}")
    got2 = safe_names(src2)
    ok2 = "eqq" not in got2 and "rb" not in got2 and "al" not in got2 and got2 == want
    print(("PASS" if ok2 else "FAIL") + " derived exclusion: %r" % got2)
    return 0 if (ok and ok2) else 1


def main(argv):
    if len(argv) == 2 and argv[1] == "--selftest":
        return _selftest()
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        print(",".join(safe_names(f.read())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
