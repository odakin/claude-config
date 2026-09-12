#!/usr/bin/env python3
"""Expand the manuscript's display-math wrapper macros into real environments.

    \\al{...}   ->  \\begin{align}...\\end{align}       (wrapper macros)
    \\nn        ->  \\nonumber\\\\                      (row-break macros)

Why: latexdiff recognises math by environment name.  A change inside ``\\al{...}``
is seen as "one macro argument replaced by another", so the old formula is
commented out (``%DIFDELCMD``) and the new one is inserted without any markup:
the equation change is invisible in the diff PDF (probed in a private paper
repo, 2026-09-08: a sign flip in an appendix equation came out uncoloured).
And latexdiff splits math markup only at ``\\\\`` / ``&``, so a row-break macro
left inside ``\\DIFadd{...}`` breaks the build ("Misplaced alignment tab") at
math-markup coarse and whole.  ``scripts/latexdiff-review-snapshot.sh`` applies
this expansion to both sides before calling latexdiff, and
``scripts/check-latexdiff-math-markup.py`` gates the result.  The expansion is
semantically a no-op for LaTeX.

Which macros: **derived from the preamble of the input file** (nothing is
hard-coded, so a new wrapper such as ``\\eq{}`` or a redefinition of ``\\nn``
is picked up automatically):
- wrapper  = ``\\newcommand{\\X}[1]{\\begin{ENV}#1\\end{ENV}}`` (ENV any display-math
  environment, ``\\renewcommand`` / ``\\providecommand`` too);
- row-break = zero-argument ``\\newcommand{\\X}{BODY}`` whose BODY contains ``\\\\``
  (BODY is substituted verbatim).
``--preamble FILE`` derives from another file (e.g. when the input is a fragment).

Rules
- The argument is the balanced-brace group after the wrapper.  Inside it a
  backslash escapes the next character (``\\{``, ``\\}``, ``\\\\``, ``\\%``) and an
  unescaped ``%`` starts a comment that runs to the end of the line (braces in a
  comment do not count).
- Occurrences in the comment part of a line are left alone.
- A macro must be a complete control word: ``\\als{`` is not ``\\al{``, ``\\alpha`` is
  never touched, an escaped backslash (``\\\\al{``) is not a macro, and the
  definition lines themselves are untouched (``\\al}`` / the ``\\newcommand{\\nn}``
  prefix are recognised).
- Everything else is byte-identical.  Wrapped bodies are expanded recursively.

Usage
    expand-display-math.py [--preamble FILE] IN.tex OUT.tex    (OUT may be '-')
    expand-display-math.py --list IN.tex        (print the derived macro sets)
    expand-display-math.py --json IN.tex        (same, as JSON: the other two
                                                 scripts read it instead of
                                                 hard-coding macro names)
    expand-display-math.py --selftest
"""
import json
import re
import sys

DISPLAY_ENVS = ("align", "align*", "equation", "equation*", "gather", "gather*", "multline",
                "multline*", "eqnarray", "eqnarray*", "flalign", "flalign*", "alignat", "alignat*")
DEF_PREFIXES = ("\\newcommand{", "\\renewcommand{", "\\providecommand{", "\\def",
                "\\newcommand*{", "\\renewcommand*{", "\\providecommand*{")
WRAPPER_RE = re.compile(
    r"^\s*\\(?:re|provide)?newcommand\*?\s*\{\\([A-Za-z]+)\}\s*\[1\]\s*\{\s*"
    r"\\begin\{([A-Za-z*]+)\}\s*#1\s*\\end\{\2\}\s*\}", re.M)
ZEROARG_RE = re.compile(r"^\s*\\(?:re|provide)?newcommand\*?\s*\{\\([A-Za-z]+)\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}", re.M)


def derive_macros(text):
    """Return (wrappers, rowbreaks): {name: env}, {name: replacement} from the preamble of text."""
    body = text.split("\\begin{document}", 1)[0]
    code = "\n".join(re.sub(r"(?<!\\)%.*", "", ln) for ln in body.split("\n"))
    wrappers, rowbreaks = {}, {}
    for m in WRAPPER_RE.finditer(code):
        if m.group(2) in DISPLAY_ENVS:
            wrappers[m.group(1)] = m.group(2)          # later definitions win
    for m in ZEROARG_RE.finditer(code):
        name, rep = m.group(1), m.group(2)
        if "\\\\" in rep:
            rowbreaks[name] = rep
        elif name in rowbreaks:
            del rowbreaks[name]
    return wrappers, rowbreaks


def _is_macro_start(text, i):
    """True if text[i] == '\\\\' begins a control word (odd run of backslashes)."""
    n = 0
    j = i
    while j >= 0 and text[j] == "\\":
        n += 1
        j -= 1
    return n % 2 == 1


def _find_group_end(text, start):
    """Index of the '}' closing the group whose '{' is at start-1. None if unbalanced."""
    depth = 1
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            nl = text.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _control_word(text, i):
    """The letters of the control word starting at text[i] == '\\\\' ('' if none)."""
    j = i + 1
    while j < len(text) and text[j].isalpha():
        j += 1
    return text[i + 1:j]


def _in_definition(text, i):
    head = text[max(0, i - 24):i]
    return any(head.endswith(p) for p in DEF_PREFIXES)


def expand(text, wrappers, rowbreaks):
    out = []
    i = 0
    n = len(text)
    in_comment = False
    while i < n:
        c = text[i]
        if c == "\n":
            in_comment = False
            out.append(c)
            i += 1
            continue
        if in_comment:
            out.append(c)
            i += 1
            continue
        if c == "\\":
            if _is_macro_start(text, i):
                word = _control_word(text, i)
                after = i + 1 + len(word)
                if word in wrappers and text.startswith("{", after):
                    end = _find_group_end(text, after + 1)
                    if end is not None:
                        env = wrappers[word]
                        body = text[after + 1:end]
                        out.append("\\begin{%s}%s\\end{%s}" % (env, expand(body, wrappers, rowbreaks), env))
                        i = end + 1
                        continue
                if word in rowbreaks and not _in_definition(text, i):
                    out.append(rowbreaks[word])
                    i = after
                    continue
            # any other control sequence / escaped char: copy '\\' + next char verbatim
            out.append(text[i:i + 2])
            i += 2
            continue
        if c == "%":
            in_comment = True
        out.append(c)
        i += 1
    return "".join(out)


def _selftest():
    W = {"al": "align", "als": "align*"}
    R = {"nn": "\\nonumber\\\\"}
    cases = [
        ("plain", "a \\al{x=1} b", "a \\begin{align}x=1\\end{align} b"),
        ("starred", "\\als{x=1}", "\\begin{align*}x=1\\end{align*}"),
        ("nested braces + label",
         "\\al{\\frac{a}{b} = \\{c\\} \\label{eq:x}}",
         "\\begin{align}\\frac{a}{b} = \\{c\\} \\label{eq:x}\\end{align}"),
        ("two consecutive", "\\al{a}\\al{b}",
         "\\begin{align}a\\end{align}\\begin{align}b\\end{align}"),
        ("comment line untouched", "% \\al{old}\nx", "% \\al{old}\nx"),
        ("comment tail untouched", "x % see \\al{old}\n\\al{y}",
         "x % see \\al{old}\n\\begin{align}y\\end{align}"),
        ("comment inside arg with brace",
         "\\al{a % }\nb}", "\\begin{align}a % }\nb\\end{align}"),
        ("alpha untouched", "\\alpha{x}", "\\alpha{x}"),
        ("escaped backslash not a macro", "\\\\al{x}", "\\\\al{x}"),
        ("definition line untouched",
         "\\newcommand{\\al}[1]{\\begin{align}#1\\end{align}}",
         "\\newcommand{\\al}[1]{\\begin{align}#1\\end{align}}"),
        ("multiline body",
         "\\al{\na &= b \\nn\nc &= d\n}", "\\begin{align}\na &= b \\nonumber\\\\\nc &= d\n\\end{align}"),
        ("unbalanced left alone", "\\al{x", "\\al{x"),
        ("nested wrapper", "\\al{\\al{x}}",
         "\\begin{align}\\begin{align}x\\end{align}\\end{align}"),
        ("byte identity elsewhere", "Text\\%\\{\\}\n\\begin{align}a\\end{align}",
         "Text\\%\\{\\}\n\\begin{align}a\\end{align}"),
        ("nn expanded", "\\al{a \\nn b}", "\\begin{align}a \\nonumber\\\\ b\\end{align}"),
        ("nn at end of line", "a\\nn\nb", "a\\nonumber\\\\\nb"),
        ("nn definition untouched", "\\newcommand{\\nn}{\\nonumber\\\\}",
         "\\newcommand{\\nn}{\\nonumber\\\\}"),
        ("nnx untouched", "\\nnx", "\\nnx"),
        ("nn in comment untouched", "% \\nn\n", "% \\nn\n"),
    ]
    bad = 0
    for name, src, want in cases:
        got = expand(src, W, R)
        ok = got == want
        bad += not ok
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else "\n  got:  %r\n  want: %r" % (got, want)))
    # derivation from a preamble
    pre = (
        "\\newcommand{\\al}[1]{\\begin{align}#1\\end{align}}\n"
        "\\newcommand{\\als}[1]{\\begin{align*}#1\\end{align*}}\n"
        "\\newcommand{\\eq}[1]{ \\begin{equation} #1 \\end{equation} }\n"
        "\\newcommand{\\box}[1]{\\begin{center}#1\\end{center}}\n"       # not a display env
        "\\newcommand{\\nn}{\\nonumber\\\\}\n"
        "\\newcommand{\\nl}{\\\\[2mm]}\n"
        "\\newcommand{\\ov}{\\over}\n"
        "% \\newcommand{\\hid}[1]{\\begin{align}#1\\end{align}}\n"
        "\\renewcommand{\\nn}{\\notag\\\\}\n"
        "\\begin{document}\n\\newcommand{\\late}[1]{\\begin{align}#1\\end{align}}\n"
    )
    w, r = derive_macros(pre)
    dcases = [
        ("derived wrappers", w, {"al": "align", "als": "align*", "eq": "equation"}),
        ("derived rowbreaks (redefinition wins)", r, {"nn": "\\notag\\\\", "nl": "\\\\[2mm]"}),
        ("derived end-to-end", expand(pre + "\\eq{a \\nl b}", w, r),
         pre + "\\begin{equation}a \\\\[2mm] b\\end{equation}"),
    ]
    for name, got, want in dcases:
        ok = got == want
        bad += not ok
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else "\n  got:  %r\n  want: %r" % (got, want)))
    total = len(cases) + len(dcases)
    print("%d/%d PASS" % (total - bad, total))
    return 1 if bad else 0


def main(argv):
    if len(argv) == 2 and argv[1] == "--selftest":
        return _selftest()
    preamble_path = None
    if "--preamble" in argv:
        k = argv.index("--preamble")
        preamble_path = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    if len(argv) == 3 and argv[1] in ("--list", "--json"):
        with open(argv[2], encoding="utf-8") as f:
            w, r = derive_macros(f.read())
        if argv[1] == "--json":
            print(json.dumps({"wrappers": w, "rowbreaks": r}, ensure_ascii=False))
        else:
            print("wrappers:", w)
            print("rowbreaks:", r)
        return 0
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        src = f.read()
    pre = src
    if preamble_path:
        with open(preamble_path, encoding="utf-8") as f:
            pre = f.read()
    w, r = derive_macros(pre)
    res = expand(src, w, r)
    if argv[2] == "-":
        sys.stdout.write(res)
    else:
        with open(argv[2], "w", encoding="utf-8") as f:
            f.write(res)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
