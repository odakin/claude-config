#!/usr/bin/env python3
"""Check a finished latexdiff document against the two versions it claims to compare.

A marked document can compile cleanly, pass check-latexdiff-math-markup.py --scan and still show the
wrong thing, and a scan of the markup says nothing when the marks came from another tool
(latexdiff-eqtree.py).  So read the printed result instead: from diff.tex make two documents,

    additions kept, deletions dropped  -> must print as the new version
    deletions kept, additions dropped  -> must print as the old version

compile them and the two versions with the same bibliography, and compare the extracted characters.
Characters, not words: line breaks, hyphenation and page order then do not matter.  The check knows
nothing of how the marks were made.

    latexdiff-views-check.py diff.tex old.tex new.tex [--engine pdflatex]
    latexdiff-views-check.py --same a.pdf b.pdf     (the same text on every page? for two builds of one input)
    latexdiff-views-check.py --selftest

All three files in one directory, with the figures and the .bbl of diff.tex beside them (old.tex and
new.tex must be flat, as given to latexdiff).  Exit 1 if a character other than a digit, a bracket or
a hyphen differs on the new side: the new version has to come back exactly.  The old side is printed
for reading: numbers of displays that exist only in the new version stay as empty numbered lines, and
a section or caption that exists only there leaves its label, so it does not come back exactly.
Convention: conventions/latex.md#latexdiff-views-check.
"""
import collections
import os
import re
import shutil
import subprocess
import sys
import tempfile

NOISE = set("0123456789()[]-–—")


def build(name, engine):
    for _ in range(2):
        subprocess.run([engine, "-interaction=nonstopmode", name + ".tex"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def text_of(pdf):
    import fitz
    t = "\n".join(p.get_text() for p in fitz.open(pdf))
    return re.sub(r"-\n", "", t)


def chars(t):
    return collections.Counter(c for c in t if not c.isspace())


def words(t):
    return collections.Counter(re.findall(r"[^\W\d_]{2,}", t))


def compare(view, plain):
    """(characters that differ apart from numbers and brackets, the words that differ)."""
    a, b = text_of(view), text_of(plain)
    x, y = chars(a), chars(b)
    d = {c: v for c, v in ((x - y) + (y - x)).items() if c not in NOISE}
    wa, wb = words(a), words(b)
    return d, sorted((wa - wb).items()), sorted((wb - wa).items())


def run(diff, old, new, engine="pdflatex"):
    d = os.path.dirname(os.path.abspath(diff))
    os.chdir(d)
    s = open(os.path.basename(diff), encoding="utf-8").read()
    key = r"\begin{document}"
    bbl = os.path.splitext(os.path.basename(diff))[0] + ".bbl"
    for name, add, dele in (("view_new", "#1", ""), ("view_old", "", "#1")):
        t = s.replace(key, key + r"\renewcommand{\DIFadd}[1]{%s}\renewcommand{\DIFdel}[1]{%s}" % (add, dele), 1)
        open(name + ".tex", "w", encoding="utf-8").write(t)
    for src, name in ((new, "plain_new"), (old, "plain_old")):
        shutil.copy(src, name + ".tex")
    for name in ("view_new", "view_old", "plain_new", "plain_old"):
        if os.path.exists(bbl):
            shutil.copy(bbl, name + ".bbl")
        build(name, engine)
    bad = 0
    for tag, view, plain in (("new", "view_new.pdf", "plain_new.pdf"), ("old", "view_old.pdf", "plain_old.pdf")):
        dc, only_view, only_plain = compare(view, plain)
        print("%s side: %d characters differ apart from numbers and brackets" % (tag, sum(dc.values())))
        if dc:
            print("  words only in the view:", only_view[:40])
            print("  words only in the version:", only_plain[:40])
        bad += tag == "new" and bool(dc)
    return 1 if bad else 0


def same(a, b):
    import fitz
    x, y = fitz.open(a), fitz.open(b)
    equal = sum(p.get_text() == q.get_text() for p, q in zip(x, y))
    print("%d and %d pages, %d with the same text" % (x.page_count, y.page_count, equal))
    return 0 if x.page_count == y.page_count == equal else 1


def selftest():
    if shutil.which("pdflatex") is None:
        print("SKIP: pdflatex not on PATH")
        return 0
    try:
        import fitz  # noqa: F401
    except ImportError:
        print("SKIP: PyMuPDF not available")
        return 0
    head = "\\documentclass{article}\n"
    marks = "\\newcommand{\\DIFadd}[1]{#1}\n\\newcommand{\\DIFdel}[1]{#1}\n"
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        try:
            for name, body in (("o", "One two three."), ("n", "One four three.")):
                open(os.path.join(tmp, name + ".tex"), "w").write(head + "\\begin{document}\n" + body + "\n\\end{document}\n")
            good = head + marks + "\\begin{document}\nOne \\DIFdel{two}\\DIFadd{four} three.\n\\end{document}\n"
            wrong = head + marks + "\\begin{document}\nOne \\DIFdel{two}\\DIFadd{five} three.\n\\end{document}\n"
            p = os.path.join(tmp, "d.tex")
            open(p, "w").write(good)
            first = run(p, "o.tex", "n.tex")
            os.chdir(cwd)
            open(p, "w").write(wrong)
            second = run(p, "o.tex", "n.tex")
        finally:
            os.chdir(cwd)
    ok = first == 0 and second == 1
    print("selftest:", "ok" if ok else "FAILED (%d, %d)" % (first, second))
    return 0 if ok else 1


def main(argv):
    if argv[1:] == ["--selftest"]:
        return selftest()
    if len(argv) == 4 and argv[1] == "--same":
        return same(argv[2], argv[3])
    args = [a for a in argv[1:] if not a.startswith("--")]
    engine = "pdflatex"
    if "--engine" in argv:
        engine = argv[argv.index("--engine") + 1]
        args.remove(engine)
    if len(args) != 3:
        print(__doc__)
        return 2
    return run(*args, engine=engine)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
