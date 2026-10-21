#!/usr/bin/env python3
"""Let latexdiff mark only the changed tokens inside in-line math ($...$), as --math-markup=fine does for displays.

Why: latexdiff tokenizes an in-line formula `$...$` / `\\(...\\)` as ONE word, so
--math-markup=fine (which marks single tokens inside display equations) does not
reach it: a one-symbol change such as `$m_P^2/(2\\gamma)$ -> $M_P^2/(2\\gamma)$`
is shown as the whole formula struck out and the whole new formula underlined,
and a long in-line formula printed twice runs off the right margin (measured on
a 46-page manuscript; the author asked for in-line math to show only the
changed part, like the displays).

How: before latexdiff, `wrap` turns every in-line formula of the document body
into an environment, `\\begin{difinlinemath}...\\end{difinlinemath}`, on BOTH
sides; latexdiff is told it is a math environment
(`--add-to-config="MATHENV=difinlinemath"`) and diffs its content token by token.
After latexdiff, `unwrap` turns the environment back into `$...$`.  One
latexdiff habit needs repair: a formula that is deleted as a whole is re-typeset
in the replacement environment for deleted math (`displaymath`), i.e. it would
jump out of the line; `unwrap` puts it back in line as `$\\DIFdel{...}$`.

`wrap` also rewrites `\\frac{A}{B}` as `{A\\over B}` in in-line AND display math:
latexdiff takes `\\frac{..}{..}` as one token too, so `\\frac{m^2}{2} -> \\frac{M^2}{2}`
otherwise prints both fractions; the two forms print the same.

What `wrap` leaves alone: the preamble, comments, `\\$`, `$$...$$`, `\\[...\\]`, the
in-line math inside display environments (equation, align, ... ; `\\text{..$x$..}`
stays `$x$`) and verbatim.  `unwrap` fails (exit 1) if any `difinlinemath`
remains, so a shape it does not know cannot reach the PDF unnoticed.

Pipeline (--math-markup=fine):
  wrap old.tex old-w.tex; wrap new.tex new-w.tex
  latexdiff --math-markup=fine --add-to-config="MATHENV=difinlinemath" old-w.tex new-w.tex > diff.tex
  latexdiff-fine-fixups.py fix diff.tex
  check-latexdiff-math-markup.py --scan diff.tex   (counts difinlinemath as math)
  latexdiff-inline-math.py unwrap diff.tex
  pdflatex diff.tex

Usage:
  latexdiff-inline-math.py wrap in.tex out.tex
  latexdiff-inline-math.py unwrap diff.tex          (in place)
  latexdiff-inline-math.py --selftest

Convention: conventions/latex.md#latexdiff-fine-markup.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ENV = "difinlinemath"
BEGIN, END = "\\begin{%s}" % ENV, "\\end{%s}" % ENV
# the space after \begin{..} matters: latexdiff reads `\begin{env}{...}` / `\begin{env}[...]` with no space as
# environment ARGUMENTS (as in \begin{alignat}{2}), so a formula starting with `{` lost its pairing (measured)
OPEN = BEGIN + " "
# display / array environments whose content is copied untouched (in-line math inside \text{} stays $..$)
DISPLAY_ENVS = ("equation", "align", "gather", "multline", "eqnarray", "flalign", "alignat",
                "displaymath", "math", "split", "verbatim", "Verbatim", "lstlisting", "comment")
VERBATIM_ENVS = ("verbatim", "Verbatim", "lstlisting", "comment")
DISPLAY_RE = re.compile(r"\\begin\{((?:%s)\*?)\}" % "|".join(DISPLAY_ENVS))


def _close_inline(s, i, closer):
    """Index of the closing delimiter of an in-line formula whose content starts at s[i]."""
    depth, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            if closer == "\\)" and s.startswith("\\)", i) and depth == 0:
                return i
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "%":
            i = s.find("\n", i)
            if i < 0:
                break
            continue
        elif c == "$" and closer == "$" and depth <= 0:
            return i
        i += 1
    raise ValueError("unclosed in-line math starting near: %r" % s[max(0, i - 60):i][:80])


def _group_end(s, i):
    """Index of the } that closes the { at s[i] (backslash escapes skipped)."""
    depth = 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced braces")


def frac_to_over(s):
    """`\\frac{A}{B}` -> `{A\\over B}` (recursively).  latexdiff takes `\\frac{..}{..}` as ONE token, so a
    one-symbol change in a numerator marks the whole fraction twice; `\\over` splits it into tokens.  The
    two print the same in text style.  Fractions whose arguments are not both braced are left as they are."""
    out, i = [], 0
    while True:
        m = re.compile(r"\\frac(?![A-Za-z])\s*\{").search(s, i)
        if not m:
            out.append(s[i:])
            return "".join(out)
        a0 = m.end() - 1
        a1 = _group_end(s, a0)
        k = a1 + 1
        while k < len(s) and s[k] in " \t\n":
            k += 1
        if k >= len(s) or s[k] != "{":
            out.append(s[i:m.end()])
            i = m.end()
            continue
        b1 = _group_end(s, k)
        out.append(s[i:m.start()])
        out.append("{" + frac_to_over(s[a0 + 1:a1]) + "\\over " + frac_to_over(s[k + 1:b1]) + "}")
        i = b1 + 1


def wrap(text):
    head, sep, body = text.partition("\\begin{document}")
    if not sep:
        raise ValueError("no \\begin{document}")
    out, i, n, count = [], 0, len(body), 0
    while i < n:
        c = body[i]
        if c == "%":
            j = body.find("\n", i)
            j = n if j < 0 else j + 1
            out.append(body[i:j])
            i = j
        elif c == "\\":
            if body.startswith("\\[", i):
                j = body.find("\\]", i + 2)
                j = n if j < 0 else j + 2
                out.append(body[i:j])
                i = j
            elif body.startswith("\\(", i):
                j = _close_inline(body, i + 2, "\\)")
                out.append(OPEN + frac_to_over(body[i + 2:j]) + END)
                count += 1
                i = j + 2
            elif body.startswith("\\verb", i) and i + 5 < n and not body[i + 5].isalpha():
                k = i + 5 + (body[i + 5] == "*")
                j = body.find(body[k], k + 1) + 1
                out.append(body[i:j])
                i = j
            else:
                m = DISPLAY_RE.match(body, i)
                if m:
                    end = "\\end{%s}" % m.group(1)
                    j = body.find(end, m.end())
                    if j < 0:
                        out.append(body[i:])
                        break
                    inner = body[m.end():j]
                    if m.group(1).rstrip("*") not in VERBATIM_ENVS:
                        inner = frac_to_over(inner)  # the same one-token \frac in displays
                    out.append(body[i:m.end()] + inner + end)
                    i = j + len(end)
                else:
                    out.append(body[i:i + 2])
                    i += 2
        elif c == "$":
            if body.startswith("$$", i):
                j = body.find("$$", i + 2)
                j = n if j < 0 else j + 2
                out.append(body[i:j])
                i = j
            else:
                j = _close_inline(body, i + 1, "$")
                out.append(OPEN + frac_to_over(body[i + 1:j]) + END)
                count += 1
                i = j + 1
        else:
            j = i
            while j < n and body[j] not in "%\\$":
                j += 1
            out.append(body[i:j])
            i = j
    return head + sep + "".join(out), count


# A formula deleted as a whole: latexdiff re-typesets it in `displaymath` (its MATHREPL) and comments
# the original environment lines out.  Put it back in line.
DELETED_RE = re.compile(
    r"\\begin\{displaymath\}%DIFAUXCMD\n%DIFDELCMD < \\begin\{" + ENV + r"\}[^\n]*\n"
    r"(.*?)\n?\\end\{displaymath\}%DIFAUXCMD\n%DIFDELCMD < \\end\{" + ENV + r"\}[ \t]*(?:%%%)?[ \t]*\n",
    re.S)


def unwrap(text):
    text, n_del = DELETED_RE.subn(lambda m: "$" + m.group(1).rstrip("\n") + "$%\n", text)
    # every remaining marker must be live code, in begin/end pairs; a commented-out one is a shape we do not know
    left = [ln for ln in text.splitlines() if ENV in ln and "%" in ln.split(ENV, 1)[0]]
    if left or text.count(BEGIN) != text.count(END):
        raise ValueError("%d commented-out %s line(s), begin/end %d/%d (a shape unwrap does not know), first: %r"
                         % (len(left), ENV, text.count(BEGIN), text.count(END), (left or [""])[0][:120]))
    n_env = text.count(BEGIN)
    text = text.replace(OPEN, "$").replace(BEGIN, "$").replace(END, "$")
    return text, n_env, n_del


def _run_selftest():
    ok = True

    def check(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print("FAIL", name, "\n got: %r\nwant: %r" % (got, want))

    pre = "\\documentclass{article}\n\\newcommand{\\x}{$y$}\n\\begin{document}\n"
    w, c = wrap(pre + "a $x_{1}$ b \\$5 % $no$\n\\(z\\) $$d$$ \\[e\\]\n"
                "\\begin{align}f \\text{ if $g$}\\end{align} $\\text{h $i$}$ \\verb|$v$|\n")
    check("wrap", w, pre + "a %sx_{1}%s b \\$5 %% $no$\n%sz%s $$d$$ \\[e\\]\n"
          "\\begin{align}f \\text{ if $g$}\\end{align} %s\\text{h $i$}%s \\verb|$v$|\n"
          % (OPEN, END, OPEN, END, OPEN, END))
    check("wrap count", c, 3)
    w, _ = wrap(pre + "\\begin{equation*}x=\\frac{a}{b}\\end{equation*} \\begin{verbatim}\\frac{a}{b}\\end{verbatim}")
    check("wrap display frac", w, pre + "\\begin{equation*}x={a\\over b}\\end{equation*} \\begin{verbatim}\\frac{a}{b}\\end{verbatim}")
    check("frac", frac_to_over("a\\frac{b\\frac{c}{d}}{2\\gamma} \\frac12 \\fracx"),
          "a{b{c\\over d}\\over 2\\gamma} \\frac12 \\fracx")
    d = ("Here \\DIFdelbegin \\begin{displaymath}%DIFAUXCMD\n%DIFDELCMD < " + BEGIN + "%%%\n\\DIFdel{x+y}\n"
         "\\end{displaymath}%DIFAUXCMD\n%DIFDELCMD < " + END + " %%%\n\\DIFdelend is gone, "
         + BEGIN + "\\DIFdelbegin \\DIFdel{m}\\DIFdelend \\DIFaddbegin \\DIFadd{M}\\DIFaddend _P" + END + ".")
    u, n_env, n_del = unwrap(d)
    check("unwrap", u, "Here \\DIFdelbegin $\\DIFdel{x+y}$%\n\\DIFdelend is gone, "
          "$\\DIFdelbegin \\DIFdel{m}\\DIFdelend \\DIFaddbegin \\DIFadd{M}\\DIFaddend _P$.")
    check("unwrap counts", (n_env, n_del), (1, 1))
    try:
        unwrap("x %DIFDELCMD < " + BEGIN + " y")
        ok = False
        print("FAIL unwrap must refuse an unknown leftover")
    except ValueError:
        pass
    # end to end through latexdiff, when it is installed
    old = pre + ("It is $m_\\mathrm{P}^2/(2\\gamma)$ times. Here $x+y$ is gone. Form $\\frac{m^2}{2} e$. "
                 "Kept $a=b$.\n\\begin{equation}E = m c^2\\end{equation}\n\\end{document}\n")
    new = old.replace("$m_", "$M_").replace("Here $x+y$ is gone", "Here is gone").replace("m c^2", "m c^3").replace("{m^2}", "{M^2}")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "old.tex").write_text(wrap(old)[0])
        (t / "new.tex").write_text(wrap(new)[0])
        try:
            r = subprocess.run(["latexdiff", "--math-markup=fine", "--add-to-config=MATHENV=" + ENV,
                                str(t / "old.tex"), str(t / "new.tex")], capture_output=True, text=True)
        except FileNotFoundError:
            r = None
        if r is not None and r.returncode == 0:
            body = unwrap(r.stdout)[0].split("\\begin{document}", 1)[1]
            check("e2e: one symbol marked in line", "$\\DIFdelbegin \\DIFdel{m}\\DIFdelend \\DIFaddbegin "
                  "\\DIFadd{M}\\DIFaddend _\\mathrm{P}^2/(2\\gamma)$" in body, True)
            check("e2e: deleted formula stays in line", "$\\DIFdel{x+y}$" in body and "displaymath" not in body, True)
            check("e2e: display still fine", "\\DIFadd{^3}" in body, True)
            check("e2e: unchanged formula untouched", "$a=b$" in body, True)
            check("e2e: formula starting with a fraction, one symbol marked",
                  "${\\DIFdelbegin \\DIFdel{m}\\DIFdelend \\DIFaddbegin \\DIFadd{M}\\DIFaddend ^2\\over 2} e$" in body, True)
        else:
            print("(skip) latexdiff end-to-end check: latexdiff not runnable")
    print("selftest:", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main(argv):
    if argv[1:] == ["--selftest"]:
        return _run_selftest()
    if len(argv) == 4 and argv[1] == "wrap":
        text, count = wrap(Path(argv[2]).read_text(encoding="utf-8"))
        Path(argv[3]).write_text(text, encoding="utf-8")
        print("wrapped %d in-line formula(s) -> %s" % (count, argv[3]))
        return 0
    if len(argv) == 3 and argv[1] == "unwrap":
        p = Path(argv[2])
        try:
            text, n_env, n_del = unwrap(p.read_text(encoding="utf-8"))
        except ValueError as e:
            print("unwrap: %s" % e, file=sys.stderr)
            return 1
        p.write_text(text, encoding="utf-8")
        print("unwrapped %d in-line formula(s), %d deleted as a whole put back in line" % (n_env, n_del))
        return 0
    print("usage: latexdiff-inline-math.py wrap in out | unwrap diff | --selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
