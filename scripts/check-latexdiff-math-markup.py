#!/usr/bin/env python3
"""Gate against latexdiff silently dropping equation changes (2026-09-08).

Two failure modes, both giving a diff PDF that compiles with 0 errors and yet
shows NO colour for an equation that did change (found in a private paper repo):

  1. display-math wrapper macros (a ``\\newcommand`` hiding ``\\begin{align}``):
     latexdiff sees a macro-argument replacement, not an equation change
     -> scripts/expand-display-math.py;
  2. argument-taking user macros inside math: not on latexdiff's safe-command
     list, so the changed token is inserted without \\DIFadd and the old one is
     commented out with %DIFDELCMD
     -> scripts/latexdiff-safecmd.py (--append-safecmd, derived from the preamble).

scripts/latexdiff-review-snapshot.sh applies both and then runs --scan on the
diff, so a silent miss stops the run instead of reaching a coauthor.

Modes
  --scan DIFF.tex   Count the places inside display math where latexdiff changed
                    something WITHOUT colouring it (a %DIFDELCMD payload that is a
                    real command, or an unmarked insertion inside \\DIFaddbegin..end).
                    Prints the integer; --verbose also lists line numbers.
  --selftest [paper.tex]
                    Push a synthetic change through the real pipeline (expand +
                    latexdiff coarse + safecmd) for EVERY argument-taking macro of
                    the preamble, plus structural cases (subscript, \\frac, row
                    break, nested wrapper, plain token, sign flip in front of a
                    macro), and assert the change is marked.  A macro added to the
                    preamble later is picked up automatically.  Without an argument
                    a built-in synthetic manuscript is used, so the gate is testable
                    in CI with no manuscript present; with one, that manuscript's
                    own macros are exercised.  The scanner's own foils always run on
                    the built-in preamble.
                    Needs latexdiff on PATH (SKIP, exit 0, if absent).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# Built-in manuscript for a standalone run: one wrapper, one starred wrapper, one row break,
# argument-taking macros of 1 and 3 arguments, and a review-colour macro that must be excluded.
SYNTHETIC_TEX = "\n".join([
    r"\documentclass{article}",
    r"\usepackage{amsmath}",
    r"\newcommand{\al}[1]{\begin{align}#1\end{align}}",
    r"\newcommand{\als}[1]{\begin{align*}#1\end{align*}}",
    r"\newcommand{\nn}{\nonumber\\}",
    r"\newcommand{\pn}[1]{\left(#1\right)}",
    r"\newcommand{\os}[3]{\overset{#2}{#1}{}^{#3}}",
    r"\newcommand{\red}[1]{\textcolor{red}{#1}}",
    r"\begin{document}",
    "",
])
COLOUR_MACROS = ("red", "blue", "green", "magenta", "cyan", "orange", "yellow")
MATH_ENVS = ("align", "align*", "equation", "equation*", "gather", "gather*",
             "multline", "multline*", "eqnarray", "eqnarray*", "flalign", "flalign*")
ARGDEF_RE = re.compile(
    r"^\s*\\(?:re|provide)?newcommand\*?\s*\{?\\([A-Za-z]+)\}?\s*\[(\d+)\](\[[^\]]*\])?", re.M)


COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")
# Structural material that latexdiff never wraps in \DIFadd/\DIFdel (it would break the environment),
# so finding it outside a \DIFadd{..} group, or as a %DIFDELCMD payload, is not a lost colour.
# Everything amsmath/LaTeX offers for equation *structure*; math *content* is never in this set.
STRUCTURAL_WORDS = [
    "begin", "end", "label", "tag", "notag", "nonumber", "intertext", "shortintertext",
    "allowdisplaybreaks", "displaybreak", "hline", "cline", "multicolumn", "DIFaddbegin", "DIFaddend",
    "DIFdelbegin", "DIFdelend", "DIFaddincludegraphics", "DIFdelincludegraphics", "DIFAUXCMD",
    "qedhere", "eqno", "leqno", "nobreak", "newpage", "pagebreak", "nopagebreak", "linebreak",
    "vspace", "smallskip", "medskip", "bigskip", "noindent", "par",
]
# LATEXDIFF_BENIGN_EXTRA="foo,bar" adds control words for a manuscript that uses something else structural
STRUCTURAL_WORDS += [w for w in os.environ.get("LATEXDIFF_BENIGN_EXTRA", "").split(",") if w]
_SW = "|".join(re.escape(w) for w in STRUCTURAL_WORDS)
# a control word from the set with any bracket/brace arguments, or \\ with optional [len], or &, or punctuation
BENIGN_ADD_TOKENS = re.compile(
    r"\\(?:%s)\b\*?(?:\s*\[[^\]]*\]|\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})*|\\\\(?:\[[^\]]*\])?|&|[\s,.;]" % _SW)
BENIGN_DELCMD = re.compile(r"^(?:%s)*\s*$" % BENIGN_ADD_TOKENS.pattern)
# \[ / \] only when the backslash is not itself escaped (\\[2mm] is a row break with spacing, not math)
MATH_TOKEN_RE = re.compile(r"\\begin\{(%s)\}|\\end\{(%s)\}|(?<!\\)(\\\[)|(?<!\\)(\\\])" % (
    "|".join(re.escape(e) for e in MATH_ENVS), "|".join(re.escape(e) for e in MATH_ENVS)))


def _strip_groups(seg, cmd):
    """Remove every cmd{...} (balanced braces) from seg."""
    out, i, n = [], 0, len(seg)
    while i < n:
        j = seg.find(cmd + "{", i)
        if j < 0:
            out.append(seg[i:])
            break
        out.append(seg[i:j])
        k, depth = j + len(cmd) + 1, 1
        while k < n and depth:
            if seg[k] == "\\":
                k += 2
                continue
            depth += seg[k] == "{"
            depth -= seg[k] == "}"
            k += 1
        i = k
    return "".join(out)


def scan(path, verbose=False):
    """Count places inside display math where latexdiff changed something WITHOUT colouring it.

    Two signatures (both were observed in this manuscript on 2026-09-08):
      (d) a "%DIFDELCMD < <payload>" comment inside math whose payload is a real
          command (not just \\label / \\begin / \\end / \\nonumber / \\\\): the old
          form of a token was commented out instead of struck through;
      (a) a \\DIFaddbegin ... \\DIFaddend span inside math that still contains
          non-benign material outside every \\DIFadd{..} group: a new token was
          inserted without underline/colour (e.g. \\DIFadd{-}\\pn{J_1+J_2} where
          the whole \\pn{..} is new).  This one leaves no comment trace, so (d)
          alone misses the eq. (129) pattern.
    Math depth is measured on the code text (comments blanked), so the
    "%DIFDELCMD < \\begin{align}" comment-outs of a deleted equation do not
    open environments that never close.
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    code = COMMENT_RE.sub(lambda m: " " * len(m.group(0)), text)
    # math spans on the code text
    spans, depth, start = [], 0, None
    for m in MATH_TOKEN_RE.finditer(code):
        if m.group(1) or m.group(3):
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth = max(0, depth - 1)
            if depth == 0 and start is not None:
                spans.append((start, m.end()))
                start = None
    if start is not None:
        spans.append((start, len(code)))

    def in_math(pos):
        return any(s <= pos < e for s, e in spans)

    def lineno(pos):
        return text.count("\n", 0, pos) + 1

    hits = []
    for m in re.finditer(r"%DIFDELCMD <\s?([^\n]*?)(?:%%%)?[ \t]*$", text, re.M):
        if in_math(m.start()) and not BENIGN_DELCMD.match(m.group(1)):
            hits.append((lineno(m.start()), "del: " + m.group(1).strip()[:70]))
    for m in re.finditer(r"\\DIFaddbegin\b(.*?)\\DIFaddend\b", code, re.S):
        if not in_math(m.start()):
            continue
        left = BENIGN_ADD_TOKENS.sub("", _strip_groups(m.group(1), "\\DIFadd"))
        if left.strip():
            hits.append((lineno(m.start()), "add: " + " ".join(left.split())[:70]))
    hits.sort()
    if verbose:
        for no, what in hits:
            print("  unmarked change inside math at line %d (%s)" % (no, what))
    return len(hits)


def _derived(text):
    """(wrappers, rowbreaks) of this preamble, from the expander (never hard-coded here)."""
    p = os.path.join(HERE, "expand-display-math.py")
    fd, path = tempfile.mkstemp(suffix=".tex")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        out = subprocess.run([sys.executable, p, "--json", path],
                             capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(path)
    d = json.loads(out)
    return d.get("wrappers", {}), d.get("rowbreaks", {})


def _arg_macros(text, expanded=()):
    body = text.split("\\begin{document}", 1)[0]
    skip = set(expanded) | set(COLOUR_MACROS)
    out = []
    for m in ARGDEF_RE.finditer(body):
        name, n, opt = m.group(1), int(m.group(2)), m.group(3)
        if name in skip:
            continue
        out.append((name, n - (1 if opt else 0)))
    return out


def _preamble(text):
    """The manuscript preamble (macro definitions) up to and including \\begin{document}."""
    return text.split("\\begin{document}", 1)[0] + "\\begin{document}\n"


def _safecmd_for(preamble_text, tmp):
    p = os.path.join(tmp, "pre.tex")
    with open(p, "w", encoding="utf-8") as f:
        f.write(preamble_text)
    return subprocess.run([sys.executable, os.path.join(HERE, "latexdiff-safecmd.py"), p],
                          capture_output=True, text=True, check=True).stdout.strip()


def _run_pipeline(base, live, safecmd, tmp, preamble):
    """Real pipeline on a synthetic pair: manuscript preamble + body -> expand (macros derived
    from that preamble) -> latexdiff coarse with the safe list; return the diff text."""
    exp = os.path.join(HERE, "expand-display-math.py")
    paths = {}
    for tag, src in (("base", base), ("live", live)):
        p = os.path.join(tmp, tag + ".tex")
        with open(p, "w", encoding="utf-8") as f:
            f.write(preamble + src + "\n\\end{document}\n")
        subprocess.run([sys.executable, exp, p, p], check=True)
        paths[tag] = p
    r = subprocess.run(["latexdiff", "--encoding=utf8", "--math-markup=coarse",
                        "--append-safecmd=" + safecmd, paths["base"], paths["live"]],
                       capture_output=True, text=True, check=True)
    return r.stdout


def _selftest(tex_path=None):
    if tex_path:
        with open(tex_path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = SYNTHETIC_TEX
    preamble = _preamble(text)
    wrappers, rowbreaks = _derived(preamble)
    # concrete names for the structural cases, taken from THIS preamble
    WRAP = next((k for k, v in wrappers.items() if not v.endswith("*")), None)
    STAR = next((k for k, v in wrappers.items() if v.endswith("*")), None)
    RB = next(iter(rowbreaks), None)
    argm = _arg_macros(text, set(wrappers) | set(rowbreaks))
    ARG1 = next((k for k, a in argm if a == 1), None)
    # no wrapper macro in this manuscript: use a real environment, the arg-macro cases still apply
    wo, wc = ("\\%s{" % WRAP, "}") if WRAP else ("\\begin{align}", "\\end{align}")
    # a manuscript that later adds an environment-hiding wrapper and a new row-break macro
    preamble2 = preamble.replace("\\begin{document}",
                                 "\\newcommand{\\eqq}[1]{\\begin{equation}#1\\end{equation}}\n"
                                 "\\newcommand{\\rb}{\\notag\\\\[1mm]}\n\\begin{document}")
    cases = []
    for name, n in argm:
        args_old = "".join("{x%d}" % i for i in range(n))
        args_new = "{z0}" + "".join("{x%d}" % i for i in range(1, n))
        cases.append(("macro \\%s [%d]" % (name, n),
                      "%sa = \\%s%s + b%s" % (wo, name, args_old, wc),
                      "%sa = \\%s%s + b%s" % (wo, name, args_new, wc)))
    cases += [
        ("subscript", "%sa = J_{1}%s" % (wo, wc), "%sa = J_{2}%s" % (wo, wc)),
        ("frac", "%sa = \\frac{x+y}{2}%s" % (wo, wc), "%sa = \\frac{x-y}{2}%s" % (wo, wc)),
        ("plain token", "%sa = x + y%s" % (wo, wc), "%sa = x - y%s" % (wo, wc)),
    ]
    if RB:
        cases.append(("second row after \\%s" % RB,
                      "%sa &= x \\%s b &= y%s" % (wo, RB, wc),
                      "%sa &= x \\%s b &= z%s" % (wo, RB, wc)))
    if ARG1:
        cases += [
            ("nested \\%s in \\%s" % (ARG1, ARG1),
             "%sa = \\%s{\\%s{x}+y}%s" % (wo, ARG1, ARG1, wc),
             "%sa = \\%s{\\%s{z}+y}%s" % (wo, ARG1, ARG1, wc)),
            ("sign flip in front of \\%s (uncoloured-insertion pattern)" % ARG1,
             "%sG = J_1 + J_2 ,%s" % (wo, wc),
             "%sG = -\\%s{J_1 + J_2} ,%s" % (wo, ARG1, wc)),
        ]
        if STAR:
            cases.append(("starred wrapper",
                          "\\%s{a = \\%s{x}}" % (STAR, ARG1),
                          "\\%s{a = \\%s{z}}" % (STAR, ARG1)))
    cases2 = [  # need preamble2 (derived wrappers / row breaks / safe list must follow a changed preamble)
        ("new wrapper \\eqq{} derived from preamble", "\\eqq{a = \\pn{x}}", "\\eqq{a = \\pn{z}}"),
        ("new row-break \\rb derived from preamble", "\\al{a &= x \\rb b &= y}", "\\al{a &= x \\rb b &= z}"),
        ("new wrapper: unsafe macro inside is still coloured", "\\eqq{a = \\os{e}{T}{}}", "\\eqq{a = \\os{e}{K}{}}"),
    ]
    bad = 0
    # the scanner's own foils never depend on the manuscript: they run on the built-in preamble
    syn = _preamble(SYNTHETIC_TEX)
    with tempfile.TemporaryDirectory() as tmp:
        safecmd = _safecmd_for(preamble, tmp)
        safecmd2 = _safecmd_for(preamble2, tmp)
        syn_safe = _safecmd_for(syn, tmp)
        # (i) the scanner itself: a diff made WITHOUT the safe list must be flagged, with it must be clean,
        #     and whole-equation add/delete with structural commands must not be flagged.
        for label, sc, base, live, want in (
            ("scan flags unsafe macro (del+add)", "zzzunused", "\\al{a = \\pn{x}}", "\\al{a = \\pn{z}}", (1, 2)),  # noqa: E501
            ("scan flags unmarked add, eq. 129 pattern", "zzzunused",
             "\\al{G = J_1 + J_2 ,}", "\\al{G = -\\pn{J_1 + J_2} ,}", (1, 1)),
            ("scan clean with safe macro", safecmd, "\\al{a = \\pn{x}}", "\\al{a = \\pn{z}}", (0, 0)),
            ("scan ignores deleted equation", safecmd,
             "t\n\\al{a = \\pn{x} \\label{eq:x}}\nu", "t\nu", (0, 0)),
            ("scan ignores added equation", safecmd,
             "t\nu", "t\n\\al{a &= \\pn{x} \\nn b &= y \\label{eq:x}}\nu", (0, 0)),
            ("scan ignores added equation with tag/notag/intertext/displaybreaks", safecmd,
             "t\nu", "t\n\\al{a &= \\pn{x} \\tag{A} \\\\[2mm] \\allowdisplaybreaks\n"
             "\\intertext{and} b &= y \\notag \\\\ c &= 1 \\nonumber \\label{eq:y}}\nu", (0, 0)),
            ("scan ignores text-only change", safecmd,
             "t\n\\al{a = \\pn{x}}\nu \\pn{x}", "s\n\\al{a = \\pn{x}}\nu \\pn{z}", (0, 0)),
            ("scan: LATEXDIFF_BENIGN_EXTRA=pn silences a declared-structural word (knob works)", "zzzunused",
             "\\al{a = \\pn{x}}", "\\al{a = \\pn{z}}", (0, 0)),
        ):
            p = os.path.join(tmp, "scan.tex")
            sc = syn_safe if sc != "zzzunused" else sc
            with open(p, "w", encoding="utf-8") as f:
                f.write(_run_pipeline(base, live, sc, tmp, syn))
            if "LATEXDIFF_BENIGN_EXTRA" in label:   # the env var is read at import time -> subprocess
                env = dict(os.environ, LATEXDIFF_BENIGN_EXTRA="pn")
                got = int(subprocess.run([sys.executable, __file__, "--scan", p], env=env,
                                         capture_output=True, text=True, check=True).stdout.split()[-1])
            else:
                got = scan(p)
            ok = want[0] <= got <= want[1]
            bad += not ok
            if not ok or "--verbose" in sys.argv:
                print(("PASS " if ok else "FAIL ") + label + ("" if ok else " (got %d, want %s)" % (got, want)))
                if not ok:
                    scan(p, verbose=True)
        # (ii) every argument-taking preamble macro + structural cases through the real pipeline
        for name, base, live, sc, pre in ([c + (safecmd, preamble) for c in cases]
                                          + [c + (safecmd2, preamble2) for c in cases2]):
            diff = _run_pipeline(base, live, sc, tmp, pre).split("\\begin{document}", 1)[-1]
            m = re.search(r"\\begin\{(?:align|equation)\*?\}(.*?)\\end\{(?:align|equation)\*?\}", diff, re.S)
            eq = m.group(1) if m else ""
            marked = "\\DIFadd" in eq and "\\DIFdel" in eq
            unmarked_cmd = "%DIFDELCMD" in eq
            ok = marked and not unmarked_cmd
            bad += not ok
            if not ok or "--verbose" in sys.argv:
                print(("PASS " if ok else "FAIL ") + name)
                if not ok:
                    print("   ", " ".join(eq.split()))
    total = len(cases) + len(cases2) + 8
    print("%d/%d PASS (%s; safecmd: %d macros; wrappers/row-breaks derived from the preamble)"
          % (total - bad, total, tex_path or "built-in synthetic manuscript",
             safecmd.count(",") + 1))
    return 1 if bad else 0


def main(argv):
    if "--scan" in argv:
        path = argv[argv.index("--scan") + 1]
        print(scan(path, verbose="--verbose" in argv))
        return 0
    if "--selftest" in argv:
        rest = [a for a in argv[1:] if not a.startswith("--")]
        if shutil.which("latexdiff") is None:
            print("SKIP: latexdiff not on PATH — the pipeline gate was not exercised")
            return 0
        return _selftest(rest[0] if rest else None)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
