#!/usr/bin/env python3
"""Expand one-argument macros whose body wraps a paragraph-level environment (quote, center, itemize, ...) before latexdiff.

    \\newcommand\\Q[1]{\\begin{quote}\\color{teal}#1\\end{quote}}
    \\Q{text}   ->  \\begin{quote}\\color{teal}text\\end{quote}

Why: latexdiff treats a changed or added macro call as one token and wraps the
whole call in ``\\DIFadd{...}`` (an underline box = LR mode).  A paragraph-level
environment inside that box stops the build with ``LaTeX Error: Not allowed in
LR mode`` followed by ``Extra }`` / ``Missing } inserted`` (measured: a reply
letter whose quoted referee sentences were ``\\Q{...}``; one changed quote broke
the diff build).  Expanding the macro on both sides lets latexdiff see the
environment and mark only the changed words inside it.  For a display-math
wrapper (``\\al{...}`` = align) use ``expand-display-math.py``; this tool skips
math environments so the two never expand the same macro.

Which macros: derived from the preamble of the input (nothing hard-coded):
``\\newcommand``/``\\renewcommand``/``\\providecommand`` (starred too) of a
macro with exactly one argument (``[1]``), the name written ``\\X`` or ``{\\X}``,
whose body contains ``\\begin{ENV}`` with ENV not a display-math environment and
uses ``#1`` exactly once.  The body is substituted with ``#1`` replaced by the
argument.  ``--preamble FILE`` derives from another file.

Rules: only the text after ``\\begin{document}`` is rewritten (definitions are
untouched).  The argument is the balanced-brace group after the macro; inside
it a backslash escapes the next character and an unescaped ``%`` starts a
comment to the end of the line (braces in a comment do not count).
Occurrences in the comment part of a line are left alone.  A macro must be a
complete control word (``\\Qx{`` is not ``\\Q{``).  Arguments are expanded
recursively.  An unbalanced argument stops with exit 2.

Usage
    latexdiff-expand-env-macros.py [--preamble FILE] IN.tex OUT.tex   (OUT may be '-'; IN = OUT is fine)
    latexdiff-expand-env-macros.py --list IN.tex
    latexdiff-expand-env-macros.py --selftest
"""
import re
import sys

MATH_ENVS = {"align", "align*", "equation", "equation*", "gather", "gather*", "multline",
             "multline*", "eqnarray", "eqnarray*", "flalign", "flalign*", "alignat", "alignat*",
             "displaymath", "math"}
DEF_RE = re.compile(r"\\(?:(?:re)?new|provide)command\*?\s*(?:\{\\([A-Za-z]+)\}|\\([A-Za-z]+))\s*\[1\]\s*\{")


def strip_comments(text):
    return "\n".join(re.sub(r"(?<!\\)%.*", "", ln) for ln in text.split("\n"))


def balanced(s, i):
    """s[i-1] == '{'; return the index after the matching '}' (escapes and % comments respected) or -1."""
    depth = 1
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            j = s.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def derive_macros(text):
    pre = strip_comments(text.split("\\begin{document}", 1)[0])
    macros = {}
    for m in DEF_RE.finditer(pre):
        name = m.group(1) or m.group(2)
        end = balanced(pre, m.end())
        if end < 0:
            continue
        body = pre[m.end():end - 1]
        envs = re.findall(r"\\begin\{([A-Za-z*]+)\}", body)
        if body.count("#1") == 1 and envs and not any(e in MATH_ENVS for e in envs):
            macros[name] = body
        elif name in macros:
            del macros[name]          # a later redefinition that does not qualify wins
    return macros


def expand_text(s, macros):
    if not macros:
        return s, 0
    pat = re.compile(r"\\(" + "|".join(sorted(map(re.escape, macros), key=len, reverse=True)) + r")(?![A-Za-z])\s*\{")
    out, i, n = [], 0, 0
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            return "".join(out), n
        # skip a match inside a comment or after an escaping backslash
        line_start = s.rfind("\n", 0, m.start()) + 1
        prefix = s[line_start:m.start()]
        bs = len(prefix) - len(prefix.rstrip("\\"))
        if re.search(r"(?<!\\)%", prefix) or bs % 2 == 1:
            out.append(s[i:m.end()])
            i = m.end()
            continue
        end = balanced(s, m.end())
        if end < 0:
            raise ValueError(f"unbalanced argument of \\{m.group(1)} at offset {m.start()}")
        arg, k = expand_text(s[m.end():end - 1], macros)
        out.append(s[i:m.start()] + macros[m.group(1)].replace("#1", arg))
        n += 1 + k
        i = end


def expand(text, macros):
    k = text.find("\\begin{document}")
    if k < 0:
        body, n = expand_text(text, macros)
        return body, n
    body, n = expand_text(text[k:], macros)
    return text[:k] + body, n


def selftest():
    pre = ("\\documentclass{article}\n\\usepackage{xcolor}\n"
           "\\newcommand\\Q[1]{\\begin{quote}\\color{teal}#1\\end{quote}}\n"
           "\\newcommand{\\C}[1]{\\begin{center}#1\\end{center}}\n"
           "\\newcommand{\\al}[1]{\\begin{align}#1\\end{align}}\n"
           "\\newcommand\\R[1]{\\item[R#1:]}\n")
    cases = [
        ("basic", "\\Q{Is this right?}\n", "\\begin{quote}\\color{teal}Is this right?\\end{quote}\n"),
        ("braced definition", "\\C{x}", "\\begin{center}x\\end{center}"),
        ("math wrapper left alone", "\\al{a=b}", "\\al{a=b}"),
        ("no environment left alone", "\\R1", "\\R1"),
        ("prefix not matched", "\\Qx{a}", "\\Qx{a}"),
        ("escaped brace inside", "\\Q{a \\} b}", "\\begin{quote}\\color{teal}a \\} b\\end{quote}"),
        ("comment line untouched", "% see \\Q{x}\n", "% see \\Q{x}\n"),
        ("brace in an argument comment", "\\Q{a % }\nb}", "\\begin{quote}\\color{teal}a % }\nb\\end{quote}"),
        ("escaped backslash is not a macro", "\\\\Q{a}", "\\\\Q{a}"),
        ("nested", "\\C{\\Q{a}}", "\\begin{center}\\begin{quote}\\color{teal}a\\end{quote}\\end{center}"),
        ("multi-line argument", "\\Q{line one\nline two}", "\\begin{quote}\\color{teal}line one\nline two\\end{quote}"),
    ]
    macros = derive_macros(pre + "\\begin{document}\n")
    bad = 0
    if set(macros) != {"Q", "C"}:
        print("FAIL derive:", sorted(macros))
        bad += 1
    for name, src, want in cases:
        doc = pre + "\\begin{document}\n" + src + "\n\\end{document}\n"
        got, _ = expand(doc, macros)
        exp = pre + "\\begin{document}\n" + want + "\n\\end{document}\n"
        if got != exp:
            bad += 1
            print(f"FAIL {name}: {got.split(chr(92) + 'begin{document}', 1)[1]!r}")
    # definitions untouched
    got, _ = expand(pre + "\\begin{document}\n\\end{document}\n", macros)
    if not got.startswith(pre):
        bad += 1
        print("FAIL definitions changed")
    # redefinition that no longer wraps an environment removes the macro
    m2 = derive_macros(pre + "\\renewcommand\\Q[1]{\\textit{#1}}\n\\begin{document}\n")
    if "Q" in m2:
        bad += 1
        print("FAIL redefinition not honoured")
    try:
        expand(pre + "\\begin{document}\n\\Q{a\n\\end{document}\n", macros)
        bad += 1
        print("FAIL unbalanced not detected")
    except ValueError:
        pass
    print(f"selftest: {len(cases) + 4 - bad}/{len(cases) + 4} passed")
    return 1 if bad else 0


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    pre_file = None
    if len(argv) >= 2 and argv[0] == "--preamble":
        pre_file, argv = argv[1], argv[2:]
    if len(argv) == 2 and argv[0] == "--list":
        src = open(argv[1], encoding="utf-8").read()
        for k, v in sorted(derive_macros(open(pre_file, encoding="utf-8").read() if pre_file else src).items()):
            print(f"\\{k}  ->  {v}")
        return 0
    if len(argv) != 2:
        print(__doc__.split("Usage", 1)[1], file=sys.stderr)
        return 2
    src = open(argv[0], encoding="utf-8").read()
    macros = derive_macros(open(pre_file, encoding="utf-8").read() if pre_file else src)
    try:
        out, n = expand(src, macros)
    except ValueError as e:
        print(f"latexdiff-expand-env-macros: {e}", file=sys.stderr)
        return 2
    if argv[1] == "-":
        sys.stdout.write(out)
    else:
        open(argv[1], "w", encoding="utf-8").write(out)
    names = ", ".join("\\" + k for k in sorted(macros)) or "no macro"
    print(f"expanded {n} call(s) of {names}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
