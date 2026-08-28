#!/usr/bin/env python3
"""fix-bib-unicode.py — Unicode→LaTeX 変換スクリプト
Replace non-LaTeX characters in LaTeX source files with LaTeX equivalents.

Works on any LaTeX-related file (.tex, .bib, .bst, .cls, .sty, etc.).

Handles two kinds of input:
  1. Literal \\UTF{xxxx} / \\CID{xxx} escape strings (from some export tools)
  2. Raw Unicode characters (from copy-paste or web downloads)

En/em-dash conversion is **math-mode aware** (see _fix_dashes_math_aware):
in text a Unicode en/em-dash is the LaTeX --/--- ligature, but in math mode
those render as 2/3 minus signs, so a dash there is normalized to a single
ASCII '-'. (RCA: a "$<en-dash>$" silently became "$--$" = two minuses and
shipped to a coauthor before being caught. conventions/latex.md#pre-commit-hook.)

Exit codes:
  0 - no changes needed
  1 - file(s) were modified (caller should re-stage)

Self-test:  python3 fix-bib-unicode.py --selftest
"""

import re
import sys

# -- Mapping tables ----------------------------------------------

# \UTF{xxxx} string escapes  ->  LaTeX
UTF_MAP = {
    "00E0": r"{\`a}",   # a-grave
    "00E1": r"{\'a}",   # a-acute
    "00E4": r'{\"a}',   # a-umlaut
    "00C4": r'{\"A}',   # A-umlaut
    "00E8": r"{\`e}",   # e-grave
    "00E9": r"{\'e}",   # e-acute
    "00ED": r"{\'i}",   # i-acute
    "00F1": r"{\~n}",   # n-tilde
    "00F6": r'{\"o}',   # o-umlaut
    "00D6": r'{\"O}',   # O-umlaut
    "00FC": r'{\"u}',   # u-umlaut
    "00DC": r'{\"U}',   # U-umlaut
    "00DF": r"{\ss}",   # eszett
    "00A0": " ",         # non-breaking space
    "2013": "--",        # en-dash
    "2014": "---",       # em-dash
    "201C": "``",        # left double quote
    "201D": "''",        # right double quote
    "201E": r"\glqq{}",  # German opening quote
}

CID_MAP = {
    "122": r"\grqq{}",   # German closing quote
}

# Raw Unicode codepoints -> LaTeX (keys matched verbatim against file chars).
UNICODE_MAP = {
    "à": r"{\`a}",
    "á": r"{\'a}",
    "ä": r'{\"a}',
    "Ä": r'{\"A}',
    "è": r"{\`e}",
    "é": r"{\'e}",
    "í": r"{\'i}",
    "ñ": r"{\~n}",
    "ö": r'{\"o}',
    "Ö": r'{\"O}',
    "ü": r'{\"u}',
    "Ü": r'{\"U}',
    "ß": r"{\ss}",
    " ": " ",
    "–": "--",
    "—": "---",
    "“": "``",
    "”": "''",
    "„": r"\glqq{}",
    "φ": r"$\varphi$",
}

# En/em-dash need math-mode awareness (see module docstring + walker below).
_DASH_TEXT = {"–": "--", "—": "---"}

# Environments that switch into math mode (starred variants included). Math-only
# *sub*-environments (array/cases/aligned/split/matrix...) are intentionally NOT
# listed: they only ever appear nested inside one of these, whose depth already
# covers them, so listing them would risk an unbalanced counter.
_MATH_ENVS = {
    "math", "displaymath",
    "equation", "equation*",
    "align", "align*", "alignat", "alignat*", "flalign", "flalign*",
    "gather", "gather*", "multline", "multline*", "eqnarray", "eqnarray*",
}

_BEGIN_END_RE = re.compile(r"\\(begin|end)\{([^}]*)\}")


# -- Processing --------------------------------------------------

def _fix_dashes_math_aware(content: str) -> tuple[str, int]:
    """En/em-dash -> ASCII '-' inside math, --/--- in text (and comments).

    Returns (new_content, n_dashes_normalized_in_math). A lightweight LaTeX
    tokenizer tracks math state ($...$, $$...$$, \\(...\\), \\[...\\], and the
    math environments in _MATH_ENVS), honoring backslash escapes (\\$, \\%,
    \\\\) and %-comments. Known limitation: a dash inside \\text{...}/\\mbox{...}
    nested in math is still treated as math (rare; would need brace tracking).
    """
    out = []
    i, n = 0, len(content)
    in_comment = inline = display = False
    env_depth = 0
    math_dashes = 0
    while i < n:
        c = content[i]

        if in_comment:
            if c == "\n":
                in_comment = False
                out.append(c)
            elif c in _DASH_TEXT:          # comments render nothing; keep old
                out.append(_DASH_TEXT[c])  # text behavior (-- / ---)
            else:
                out.append(c)
            i += 1
            continue

        if c == "\\":
            nxt = content[i + 1] if i + 1 < n else ""
            if nxt == "(":
                inline = True; out.append("\\("); i += 2; continue
            if nxt == ")":
                inline = False; out.append("\\)"); i += 2; continue
            if nxt == "[":
                display = True; out.append("\\["); i += 2; continue
            if nxt == "]":
                display = False; out.append("\\]"); i += 2; continue
            m = _BEGIN_END_RE.match(content, i)
            if m:
                if m.group(2) in _MATH_ENVS:
                    if m.group(1) == "begin":
                        env_depth += 1
                    else:
                        env_depth = max(0, env_depth - 1)
                out.append(m.group(0)); i = m.end(); continue
            # generic escape: emit backslash + next char verbatim so that
            # \$ \% \& \\ etc. neither toggle math nor start a comment.
            if nxt:
                out.append(c + nxt); i += 2
            else:
                out.append(c); i += 1
            continue

        if c == "%":
            in_comment = True
            out.append(c); i += 1; continue

        if c == "$":
            if content[i + 1:i + 2] == "$":
                display = not display
                out.append("$$"); i += 2
            else:
                inline = not inline
                out.append("$"); i += 1
            continue

        if c in _DASH_TEXT:
            if inline or display or env_depth > 0:
                out.append("-"); math_dashes += 1
            else:
                out.append(_DASH_TEXT[c])
            i += 1
            continue

        out.append(c); i += 1

    return "".join(out), math_dashes


def fix_content(content: str) -> tuple[str, bool, int]:
    """Return (fixed_content, was_changed, n_math_dashes)."""
    original = content

    # Pass 1: \UTF{xxxx}
    def replace_utf(m):
        code = m.group(1).upper()
        return UTF_MAP.get(code, m.group(0))

    content = re.sub(r"\\UTF\{([0-9A-Fa-f]+)\}", replace_utf, content)

    # Pass 2: \CID{xxx}
    def replace_cid(m):
        code = m.group(1)
        return CID_MAP.get(code, m.group(0))

    content = re.sub(r"\\CID\{([0-9]+)\}", replace_cid, content)

    # Pass 3a: raw Unicode (non-dash) - context-free global replace
    for char, latex in UNICODE_MAP.items():
        if char in _DASH_TEXT:
            continue
        content = content.replace(char, latex)

    # Pass 3b: raw Unicode en/em-dash - math-mode aware
    content, math_dashes = _fix_dashes_math_aware(content)

    return content, content != original, math_dashes


# -- Self-test ---------------------------------------------------

def _selftest() -> None:
    EN, EM = "–", "—"
    cases = [
        (f"${EN}$", "$-$"),                                   # the incident
        (f"a {EN} b", "a -- b"),                              # text en-dash
        (f"a {EM} b", "a --- b"),                             # text em-dash
        (f"$a {EN} b$", "$a - b$"),                           # inline math
        (f"$$a {EM} b$$", "$$a - b$$"),                       # display $$
        (f"\\[a {EN} b\\]", "\\[a - b\\]"),                   # display \[ \]
        (f"\\(a {EN} b\\)", "\\(a - b\\)"),                   # inline \( \)
        (f"\\begin{{align}} a {EN} b \\end{{align}}",
         "\\begin{align} a - b \\end{align}"),                # math env
        (f"\\begin{{equation}} x{EN}y \\end{{equation}}",
         "\\begin{equation} x-y \\end{equation}"),
        (f"\\begin{{align}}\\begin{{array}}{{c}} a{EN}b \\end{{array}}\\end{{align}}",
         "\\begin{align}\\begin{array}{c} a-b \\end{array}\\end{align}"),
        (f"\\$5{EN}10", "\\$5--10"),                          # escaped $ = text
        (f"% c $5 a{EN}b\nc{EN}d", "% c $5 a--b\nc--d"),      # comment $ no-toggle
        (f"$x$ a{EN}b", "$x$ a--b"),                          # text after math
        ("café", "caf{\\'e}"),                          # non-dash unchanged
        ("a--b", "a--b"),                                          # ascii untouched
        (f"text {EM} dash", "text --- dash"),
    ]
    ok = 0
    for src, want in cases:
        got, _, _ = fix_content(src)
        if got == want:
            ok += 1
        else:
            print(f"FAIL: {src!r}\n  got:  {got!r}\n  want: {want!r}",
                  file=sys.stderr)
    # idempotency: a second pass must be a fixed point
    idem = True
    for src, _want in cases:
        once, _, _ = fix_content(src)
        twice, _, _ = fix_content(once)
        if once != twice:
            print(f"FAIL(idempotency): {src!r} -> {once!r} -> {twice!r}",
                  file=sys.stderr)
            idem = False
    print(f"selftest: {ok}/{len(cases)} passed; idempotent={idem}",
          file=sys.stderr)
    sys.exit(0 if ok == len(cases) and idem else 1)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        _selftest()
        return
    if not args:
        print(f"Usage: {sys.argv[0]} FILE [FILE ...]", file=sys.stderr)
        sys.exit(2)

    any_changed = False
    for path in args:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError as e:
            # Vendored third-party LaTeX (e.g. lineno.sty is Latin-1) is not
            # ours to normalize — skip it byte-for-byte instead of crashing
            # the whole pre-commit hook. Repos can also opt such paths out
            # explicitly via the `-latex-autofix` git attribute.
            print(f"  skip (not UTF-8, left byte-for-byte): {path} ({e.reason})",
                  file=sys.stderr)
            continue
        fixed, changed, math_dashes = fix_content(content)
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                f.write(fixed)
            print(f"  fixed: {path}")
            any_changed = True
        if math_dashes:
            print(f"  note: {path}: normalized {math_dashes} en/em-dash inside "
                  f"math to ASCII '-' (math has no en/em-dash; verify intent)",
                  file=sys.stderr)

    sys.exit(1 if any_changed else 0)


if __name__ == "__main__":
    main()
