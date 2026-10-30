#!/usr/bin/env python3
"""latexdiff for the text, a tree comparison for the equations: only the changed symbols are marked.

latexdiff --math-markup=fine compares a flat list of tokens, so on a real manuscript it matches
`_{a` across braces (the deleted side then carries a bare `}`, written \\MBLOCKRIGHTBRACE, and TeX
stops) and it pairs a deleted display with the next new one (two equations end up in one).  Its
`whole` mode avoids both but strikes a whole equation for one changed subscript.

Here the equations never reach latexdiff.  Every display of both versions is replaced by a
placeholder, the same placeholder for an old display and the new display it corresponds to, so
latexdiff sees the text only.  The pairs are compared here on the parse tree: groups, fractions,
delimiters, macro arguments and sub/superscripts are matched as units, so every \\DIFadd / \\DIFdel
holds balanced material by construction.  Afterwards the placeholders are filled in.  A formula
`$...$` that latexdiff shows old struck + new underlined is compared the same way, and so is a
formula that changed inside a tikzpicture.

  latexdiff-eqtree.py protect o.tex n.tex table.json [ids]   (o.tex and n.tex are rewritten)
  latexdiff --type=UNDERLINE --disable-citation-markup --append-safecmd=... o.tex n.tex > diff.tex
  latexdiff-eqtree.py restore diff.tex table.json [old.aux]  (old.aux = aux file of the old version)
  pdflatex diff.tex
  latexdiff-eqtree.py overflow diff.log diff.tex table.json > ids   (displays over the column by > 12 pt)
  ... and once more from a copy of o.tex, n.tex with `ids`: the widest row of those gets a second line
  latexdiff-eqtree.py --selftest

Input: one flat file per version, comments stripped, wrapper macros of display math already expanded
(expand-display-math.py).  Convention: conventions/latex.md#latexdiff-eqtree.

Every rendered equation is read back before use: dropping the additions must give the old equation
and dropping the deletions the new one, token by token (spacing and delimiter size aside).  A
mismatch stops the run, so a wrong mark cannot reach the PDF.  check-latexdiff-math-markup.py --scan
returns 0 on the equations here by construction (they hold no latexdiff markup), so it proves
nothing about them: latexdiff-views-check.py is the check of the finished document.

Equation numbers follow the new version.  A display that exists only on the old side has no number,
and a deleted sentence that cites it prints its old number.  What is not a change: spacing, the size
of a delimiter (\\pn{..}, ( .. ), \\Big( .. \\Big) are the same bracket), where a row breaks.

A pair with little in common (WHOLE_BELOW) is shown whole, old struck + new underlined.  A display
latexdiff takes out in one place and puts in at another has moved: struck there, underlined here.
Arguments of macros defined in the preamble are read from \\newcommand; macros that only wrap a
bracket are listed in DELIM_MACRO.
"""
import json
import re
import sys

# --- what a control word means to the comparison -------------------------------------------------
NEUTRAL = {",", ";", ":", "!", " ", "quad", "qquad", "enspace", "thinspace", "autospace",
           "displaystyle", "textstyle", "scriptstyle", "nonscript", "hfill", "/"}
NEUTRAL_ARG = {"phantom", "hphantom", "vphantom", "hspace", "vspace", "mspace"}
STRUCT = {"nonumber", "notag", "allowdisplaybreaks", "displaybreak", "noindent"}
STRUCT_ARG = {"label", "tag", "intertext"}
OPAQUE1 = {"text", "tx", "mbox", "textrm", "textbf", "textit", "mr", "mathrm", "mc", "mathcal", "bs",
           "boldsymbol", "mathbf", "mathbb", "mathfrak", "mathsf", "mathscr", "eqref", "ref", "cite",
           "bm", "slashed", "operatorname"}
RECUR1 = {"sqrt", "ol", "overline", "underline", "hat", "widehat", "tilde", "widetilde", "bar", "dot",
          "ddot", "vec", "check", "breve", "overrightarrow", "mathop", "mathrel", "mathbin",
          "mathord", "ket", "bra", "Ket", "Bra", "Braket", "underbrace", "overbrace",
          "DIFadd", "DIFdel"}
RECUR2 = {"overset", "underset", "stackrel", "frac", "dfrac", "tfrac", "braket"}
DELIM_MACRO = {"fn": "(", "pn": "(", "paren": "(", "sqbr": "[", "ab": "|"}
SIZED = {"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "Bigl", "biggl", "Biggl",
         "bigr", "Bigr", "biggr", "Biggr", "bigm", "Bigm", "biggm", "Biggm"}
OPEN_OF = {")": "(", "]": "[", "\\}": "\\{"}
LOW = set("+-=,.;:()[]|/<>") | {"\\times", "\\cdot", "\\pm", "\\mp", "\\simeq", "\\sim", "\\approx",
                               "\\to", "\\geq", "\\leq", "\\gg", "\\ll", "\\equiv"}
CTRL = re.compile(r"\\([A-Za-z]+\*?|.)", re.S)
ROWOPT = re.compile(r"\*?\s*(\[[^\]]*\])?")
SIM_MIN = 0.45        # two nodes are compared inside only if at least this similar
SIM_KEEP = 0.25       # the same for two fractions, two brackets or two groups
GAP = 0.3             # price of opening a run of changes: prefers contiguous matches
ISLAND = 1.3          # a kept stretch lighter than this, between two changes, is not worth keeping
ROW_LIMIT = 44        # a row of the two-column page holds about this much weight
PAIR_BREAK = 20       # an old and a new piece side by side get their own rows from this weight on
ALIAS = {}          # \\newcommand{\\a}{\\b}: a behaves as b
USER_ARGS = {}      # \\newcommand{\\a}[n]{...}: a takes n arguments
USER_NOARG = set()
unknown_cmds = {}   # followed by a brace, not known to take an argument: reported, taken to have none


class Node:
    pass


class Tok(Node):
    def __init__(self, t):
        self.t, self.canon = t, t
        self.w = 0.3 if t in LOW else (0.5 if t.isdigit() else 1.0)

    def render(self):
        return self.t + " " if self.t[0] == "\\" and self.t[-1].isalpha() else self.t


class Struct(Node):
    """Alignment and bookkeeping: taken from the new side, never marked."""
    w, canon = 0.0, ""

    def __init__(self, t):
        self.t = t

    def render(self):
        return self.t + " "


class Neutral(Struct):
    """Spacing: taken from the new side, dropped from the old side, not a change."""


class Script(Node):
    def __init__(self, c):
        self.c = c


class Open(Node):
    def __init__(self, k, t, lr=False):
        self.k, self.t, self.lr = k, t, lr


class Close(Node):
    def __init__(self, k, t, lr=False):
        self.k, self.t, self.lr = k, t, lr


def seq_canon(xs):
    return " ".join(x.canon for x in xs if x.canon)


def seq_w(xs):
    return sum(x.w for x in xs)


def spans_rows(x):
    if isinstance(x, Atom):
        return x.nuc is not None and spans_rows(x.nuc)
    return isinstance(x, Delim) and any(type(k) is Struct or spans_rows(k) for k in x.kids)


def apart(nodes):
    """The nodes with every delimiter pair that spans rows taken apart: a mark cannot cross a row."""
    out = []
    for x in nodes:
        if not spans_rows(x):
            out.append(x)
        elif isinstance(x, Atom):
            inner = apart([x.nuc])
            out.extend(inner[:-1])
            out.append(Atom(inner[-1], x.sub, x.sup))
        else:
            out.append(Tok(x.o.strip()))
            out.extend(apart(x.kids))
            out.append(Tok(x.c.strip()))
    return out


def seq_render(xs):
    return "".join(x.render() for x in xs)


class Group(Node):
    def __init__(self, kids):
        self.kids = kids
        self.w = seq_w(kids)
        real = [x for x in kids if x.canon]
        self.canon = real[0].canon if len(real) == 1 else "{" + seq_canon(kids) + "}"

    def render(self):
        return "{" + seq_render(self.kids) + "}"


class Frac(Node):
    def __init__(self, num, den):
        self.num, self.den = num, den
        self.w = 0.5 + seq_w(num) + seq_w(den)
        self.canon = "frac(" + seq_canon(num) + "|" + seq_canon(den) + ")"

    def render(self):
        return "{" + seq_render(self.num) + " \\over " + seq_render(self.den) + "}"


class Delim(Node):
    def __init__(self, k, kids, o, c):
        self.k, self.kids, self.o, self.c = k, kids, o, c
        self.w = 0.6 + seq_w(kids)
        self.canon = k + "<" + seq_canon(kids) + ">"

    def render(self):
        return self.o + seq_render(self.kids) + self.c


class Cmd(Node):
    def __init__(self, name, opt, args, opaque):
        self.name, self.opt, self.args, self.opaque = name, opt, args, opaque
        self.w = 1.0 + (0 if opaque else sum(a.w for a in args))
        arg_c = ",".join(a if isinstance(a, str) else a.canon for a in args) if opaque else \
            ",".join(a.canon for a in args)
        self.canon = "\\" + name + "[" + (opt or "") + "]{" + arg_c + "}"

    def render(self):
        o = "[" + self.opt + "]" if self.opt else ""
        a = "".join("{" + x + "}" for x in self.args) if self.opaque else "".join(x.render() for x in self.args)
        return "\\" + self.name + o + a


class Atom(Node):
    def __init__(self, nuc, sub, sup):
        self.nuc, self.sub, self.sup = nuc, sub, sup
        self.w = (nuc.w if nuc else 0) + (sub.w if sub else 0) + (sup.w if sup else 0)
        self.canon = (nuc.canon if nuc else "") + ("_(" + sub.canon + ")" if sub else "") + \
            ("^(" + sup.canon + ")" if sup else "")

    def render(self):
        return (self.nuc.render() if self.nuc else "{}") + ("_" + self.sub.render() if self.sub else "") + \
            ("^" + self.sup.render() if self.sup else "")


class Env(Node):
    def __init__(self, name, opt, kids):
        self.name, self.opt, self.kids = name, opt, kids
        self.w = 1.0 + seq_w(kids)
        self.canon = "env:" + name + "<" + seq_canon(kids) + ">"

    def render(self):
        return "\\begin{" + self.name + "}" + self.opt + seq_render(self.kids) + "\\end{" + self.name + "}"


# --- parser ----------------------------------------------------------------------------------------
def brace_arg(s, i):
    """Verbatim content of the brace group at or after s[i]; returns (content, index after it)."""
    while s[i].isspace():
        i += 1
    if s[i] != "{":
        m = CTRL.match(s, i)
        if m:
            return m.group(0), m.end()
        return s[i], i + 1
    d, k = 0, i
    while True:
        c = s[k]
        if c == "\\":
            k += 2
            continue
        d += c == "{"
        d -= c == "}"
        k += 1
        if d == 0:
            return s[i + 1:k - 1], k


def load_macros(text):
    """Macro definitions of the preamble: how many arguments a macro takes decides how it parses."""
    head = text[:text.index("\\begin{document}")]
    for m in re.finditer(r"\\(?:re|provide)?newcommand\*?\s*\{?\\([A-Za-z]+)\}?\s*(?:\[(\d)\])?(\[[^\]]*\])?\s*\{", head):
        name, n = m.group(1), int(m.group(2) or 0)
        body = brace_arg(head, m.end() - 1)[0].strip()
        if n:
            USER_ARGS[name] = n - (1 if m.group(3) else 0)
        elif re.fullmatch(r"\\[A-Za-z]+", body):
            ALIAS[name] = body[1:]
        else:
            USER_NOARG.add(name)
    for m in re.finditer(r"\\DeclareMathOperator\*?\s*\{\\([A-Za-z]+)\}", head):
        USER_NOARG.add(m.group(1))


def parse_seq(s, i, stop):
    items = []
    n = len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
        elif c == "%":
            j = s.find("\n", i)
            i = n if j < 0 else j + 1
        elif c == "}":
            if stop == "}":
                return finish(items), i + 1
            raise ValueError("stray } at %d: %r" % (i, s[max(0, i - 40):i + 10]))
        elif c == "{":
            kids, i = parse_seq(s, i + 1, "}")
            items.append(Group(kids))
        elif c in "_^":
            items.append(Script(c))
            i += 1
        elif c == "&":
            items.append(Struct("&"))
            i += 1
        elif c == "~":
            items.append(Neutral("~"))
            i += 1
        elif c == "\\":
            m = CTRL.match(s, i)
            name, j = m.group(1), m.end()
            kind = ALIAS.get(name, name)
            if name == "\\":
                mo = ROWOPT.match(s, j)
                items.append(Struct("\\\\" + (mo.group(1) or "")))
                i = mo.end()
            elif name == "begin":
                env, j2 = brace_arg(s, j)
                opt = ""
                if s[j2] == "{":   # \begin{array}{cc}
                    a, j3 = brace_arg(s, j2)
                    opt, j2 = "{" + a + "}", j3
                kids, i = parse_seq(s, j2, "\\end{" + env + "}")
                items.append(Env(env, opt, kids))
            elif name == "end":
                env, j2 = brace_arg(s, j)
                if stop != "\\end{" + env + "}":
                    raise ValueError("unexpected \\end{%s}" % env)
                return finish(items), j2
            elif name in SIZED:
                while s[j].isspace():
                    j += 1
                md = CTRL.match(s, j)
                d, j2 = (md.group(0), md.end()) if md else (s[j], j + 1)
                text = "\\" + name + " " + d
                if name == "left":        # \left and \right must stay a pair, whatever the delimiter
                    items.append(Open(d, text, True))
                elif name == "right":
                    items.append(Close(OPEN_OF.get(d, d), text, True))
                elif d in "([" or d == "\\{":
                    items.append(Open(d, text))
                elif d in ")]" or d == "\\}":
                    items.append(Close(OPEN_OF[d], text))
                else:
                    items.append(Tok(text))
                i = j2
            elif kind in DELIM_MACRO:
                while s[j].isspace():
                    j += 1
                if s[j] != "{":
                    raise ValueError("\\%s without a brace argument" % name)
                kids, i = parse_seq(s, j + 1, "}")
                k = DELIM_MACRO[kind]
                items.append(Delim(k, kids, "\\" + name + "{", "}"))
            elif name in NEUTRAL:
                items.append(Neutral(m.group(0)))
                i = j
            elif name in NEUTRAL_ARG:
                a, i = brace_arg(s, j)
                items.append(Neutral("\\" + name + "{" + a + "}"))
            elif name in STRUCT:
                items.append(Struct("\\" + name))
                i = j
            elif name in STRUCT_ARG:
                a, i = brace_arg(s, j)
                items.append(Struct("\\" + name + "{" + a + "}"))
            elif kind in OPAQUE1:
                opt = None
                if s[j] == "[":
                    e = s.index("]", j)
                    opt, j = s[j + 1:e], e + 1
                a, i = brace_arg(s, j)
                items.append(Cmd(name, opt, [a], True))
            elif kind in RECUR1 or kind in RECUR2 or kind in USER_ARGS:
                opt = None
                if s[j] == "[":
                    e = s.index("]", j)
                    opt, j = s[j + 1:e], e + 1
                args = []
                for _ in range(USER_ARGS.get(kind, 2 if kind in RECUR2 else 1)):
                    while s[j].isspace():
                        j += 1
                    if s[j] == "{":
                        kids, j = parse_seq(s, j + 1, "}")
                    else:
                        a, j = brace_arg(s, j)
                        kids, _x = parse_seq(a + "}", 0, "}")
                    args.append(Group(kids))
                i = j
                if kind in ("frac", "dfrac", "tfrac"):
                    items.append(Frac(args[0].kids, args[1].kids))
                else:
                    items.append(Cmd(name, opt, args, False))
            elif name in ("{", "}"):
                t = m.group(0)
                items.append(Open(t, t) if name == "{" else Close(OPEN_OF[t], t))
                i = j
            elif name == "over":
                items.append(Tok("\\over"))
                i = j
            else:
                k = j
                while k < n and s[k].isspace():
                    k += 1
                if k < n and s[k] == "{" and name not in USER_NOARG:
                    unknown_cmds[name] = unknown_cmds.get(name, 0) + 1
                items.append(Tok(m.group(0)))
                i = j
        elif c.isdigit():
            j = i
            while j < n and (s[j].isdigit() or (s[j] == "." and j + 1 < n and s[j + 1].isdigit())):
                j += 1
            items.append(Tok(s[i:j]))
            i = j
        elif c in "([":
            items.append(Open(c, c))
            i += 1
        elif c in ")]":
            items.append(Close(OPEN_OF[c], c))
            i += 1
        else:
            items.append(Tok(c))
            i += 1
    if stop is not None:
        raise ValueError("unclosed %s" % stop)
    return finish(items)


def finish(items):
    """Match delimiters (a sized pair may span rows), then build fractions and sub/superscripts."""
    stack, out = [], []
    for x in glue(items):
        if isinstance(x, Open):
            stack.append((x, len(out)))
            out.append(x)
        elif isinstance(x, Close):
            hit = None
            for q in range(len(stack) - 1, -1, -1):
                if stack[q][0].lr == x.lr and (x.lr or stack[q][0].k == x.k):
                    hit = q
                    break
            if hit is None:
                out.append(Tok(x.t))
            else:
                op, pos = stack[hit]
                del stack[hit:]
                kids = finish(out[pos + 1:])
                del out[pos:]
                out.append(Delim(op.k if op.k == x.k else op.k + x.k, kids, op.t, x.t))
        else:
            out.append(x)
    out = [Tok(x.t) if isinstance(x, Open) else x for x in out]
    ks = [q for q, x in enumerate(out) if isinstance(x, Tok) and x.t == "\\over"]
    if ks and not any(type(x) is Struct for x in out):
        k = ks[0]
        return [Frac(scripts(out[:k]), scripts(out[k + 1:]))]
    return scripts(out)


def scripts(items):
    out, i = [], 0
    while i < len(items):
        x = items[i]
        if isinstance(x, Script):
            nuc = None
            if out and not isinstance(out[-1], (Struct, Script)) and not isinstance(out[-1], Atom):
                nuc = out.pop()
                sub = sup = None
            elif out and isinstance(out[-1], Atom):
                last = out.pop()
                nuc, sub, sup = last.nuc, last.sub, last.sup
            else:
                sub = sup = None
            arg = items[i + 1]
            arg = arg if isinstance(arg, Group) else Group([arg])
            if x.c == "_":
                sub = arg
            else:
                sup = arg
            out.append(Atom(nuc, sub, sup))
            i += 2
        else:
            out.append(x)
            i += 1
    return out


def parse(s):
    return parse_seq(s, 0, None)


def glue(items):
    """`\\Delta T` is one symbol for the comparison."""
    out, i = [], 0
    while i < len(items):
        x = items[i]
        nxt = items[i + 1] if i + 1 < len(items) else None
        if isinstance(x, Tok) and x.t == "\\Delta" and isinstance(nxt, Tok) and nxt.t.isalpha():
            out.append(Tok("\\Delta " + nxt.t))
            i += 2
        else:
            out.append(x)
            i += 1
    return out


# --- comparison --------------------------------------------------------------------------------------
memo_score = {}


def unwrap(x):
    while isinstance(x, Group):
        real = [k for k in x.kids if k.canon]
        if len(real) != 1:
            break
        x = real[0]
    return x


def as_atom(x):
    return x if isinstance(x, Atom) else Atom(x, None, None)


def real(xs):
    return [x for x in xs if x.canon]


def seq_score(a, b):
    return align(real(a), real(b))[0]


def script_score(a, b):
    if a is None or b is None:
        return 0.0
    return seq_score(a.kids, b.kids)


def score(a, b):
    """Weight of what a and b have in common (0 = nothing worth comparing inside)."""
    if a.canon == b.canon:
        return a.w
    key = (a.canon, b.canon)    # by content: an id can be reused once a temporary node is gone
    if key in memo_score:
        return memo_score[key]
    x, y, r = unwrap(a), unwrap(b), 0.0
    if x.canon == y.canon:
        r = x.w
    elif isinstance(x, Atom) or isinstance(y, Atom):
        p, q = as_atom(x), as_atom(y)
        if p.nuc is not None and q.nuc is not None:
            r += score(p.nuc, q.nuc)
        r += script_score(p.sub, q.sub) + script_score(p.sup, q.sup)
    elif isinstance(y, Cmd) and not y.opaque and len(y.args) == 1 and y.args[0].canon == x.canon:
        r = x.w            # a symbol that got an accent or a root
    elif isinstance(x, Cmd) and not x.opaque and len(x.args) == 1 and x.args[0].canon == y.canon:
        r = y.w
    elif isinstance(x, Group) and isinstance(y, Group):
        r = seq_score(x.kids, y.kids)
    elif isinstance(x, Frac) and isinstance(y, Frac):
        r = 0.5 + seq_score(x.num, y.num) + seq_score(x.den, y.den)
    elif isinstance(x, Delim) and isinstance(y, Delim) and x.k == y.k:
        r = 0.6 + seq_score(x.kids, y.kids)
    elif isinstance(x, Cmd) and isinstance(y, Cmd) and x.name == y.name and not x.opaque and \
            x.opt == y.opt and len(x.args) == len(y.args):
        r = 1.0 + sum(score(p, q) for p, q in zip(x.args, y.args))
    elif isinstance(x, Env) and isinstance(y, Env) and x.name == y.name:
        r = 1.0 + seq_score(x.kids, y.kids)
    memo_score[key] = r
    return r


def similar(a, b):
    s = score(a, b)
    if a.canon == b.canon or s >= SIM_MIN * 0.5 * (a.w + b.w):
        return s
    x, y = unwrap(a), unwrap(b)
    if isinstance(x, Atom) and isinstance(y, Atom) and x.nuc and y.nuc and x.nuc.canon == y.nuc.canon:
        return max(s, 0.5)     # the same symbol: only its scripts differ
    # a fraction or a bracket stays one while part of it survives (a bracket may also have grown a lot)
    if type(x) is type(y) and isinstance(x, (Frac, Delim, Group)) and s >= SIM_KEEP * 0.5 * (a.w + b.w):
        return s
    return s if min(a.w, b.w) >= 2 and s >= 0.6 * min(a.w, b.w) else 0.0


def align(a, b):
    """Best alignment of two node lists: (score, ops), ops = [(i, j)], i or j None for a deletion/addition."""
    n, m = len(a), len(b)
    if not n or not m:
        return 0.0, [(i, None) for i in range(n)] + [(None, j) for j in range(m)]
    # A[i][j]: best score of the rest when the previous step was a match; B: when it was a change
    A = [[0.0] * (m + 1) for _ in range(n + 1)]
    B = [[0.0] * (m + 1) for _ in range(n + 1)]
    S = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            S[i][j] = similar(a[i], b[j])
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i == n and j == m:
                continue
            ga = B[i + 1][j] if i < n else -1e9
            gb = B[i][j + 1] if j < m else -1e9
            ma = S[i][j] + A[i + 1][j + 1] if i < n and j < m and S[i][j] > 0 else -1e9
            A[i][j] = max(ma, max(ga, gb) - GAP)
            B[i][j] = max(ma, ga, gb)
    i, j, inmatch, ops = 0, 0, True, []
    while i < n or j < m:
        cur = A[i][j] if inmatch else B[i][j]
        pen = GAP if inmatch else 0.0
        ma = S[i][j] + A[i + 1][j + 1] if i < n and j < m and S[i][j] > 0 else -1e9
        if abs(ma - cur) < 1e-9:
            ops.append((i, j))
            i, j, inmatch = i + 1, j + 1, True
        elif i < n and abs(B[i + 1][j] - pen - cur) < 1e-9:
            ops.append((i, None))
            i, inmatch = i + 1, False
        else:
            ops.append((None, j))
            j, inmatch = j + 1, False
    return sum(S[i][j] for i, j in ops if i is not None and j is not None), ops


def clean_islands(a, b, ops):
    """A kept scrap between two changes reads worse than one clean replacement."""
    runs = []
    for op in ops:
        kind = op[0] is not None and op[1] is not None
        if runs and runs[-1][0] == kind:
            runs[-1][1].append(op)
        else:
            runs.append((kind, [op]))
    out = []
    for k, (kept, r) in enumerate(runs):
        if kept and 0 < k < len(runs) - 1:
            w = sum(b[j].w for _, j in r)
            changed = sum(a[i].w for i, _ in runs[k - 1][1] + runs[k + 1][1] if i is not None) + \
                sum(b[j].w for _, j in runs[k - 1][1] + runs[k + 1][1] if j is not None)
            equal = all(a[i].canon == b[j].canon for i, j in r)
            if equal and w < ISLAND and changed > 6 * w:
                out.extend([(i, None) for i, _ in r] + [(None, j) for _, j in r])
                continue
        out.extend(r)
    # inside a gap, deletions first
    res, gap = [], []
    for op in out:
        if op[0] is not None and op[1] is not None:
            res.extend(sorted(gap, key=lambda o: o[0] is None))
            gap = []
            res.append(op)
        else:
            gap.append(op)
    return res + sorted(gap, key=lambda o: o[0] is None)


def mark_del(t):
    return "\\DIFdel{" + t + "}" if t.strip() else ""


def mark_add(t):
    return "\\DIFadd{" + t + "}" if t.strip() else ""


def mark_cells(nodes, mark):
    """Mark a run of nodes; rows and cells of the new side stay outside the marks."""
    out, cur = [], []
    for x in apart(nodes):
        if type(x) is Struct:
            if cur:
                out.append(mark(seq_render(cur)))
                cur = []
            out.append(x.render())
        else:
            cur.append(x)
    if cur:
        out.append(mark(seq_render(cur)))
    return "".join(out)


def diff_seq(a, b, rowbreak=False):
    """Render b with the changes from a marked.  Structure and spacing come from b; a's are dropped."""
    breaks = {}
    ra = []
    for x in a:
        if isinstance(x, Struct):
            if rowbreak and x.t.startswith("\\\\"):
                breaks[len(ra)] = True
            continue
        if x.canon:
            ra.append(x)
    rb_idx = [q for q, x in enumerate(b) if x.canon]
    rb = [b[q] for q in rb_idx]
    ops = clean_islands(ra, rb, align(ra, rb)[1])
    out, q, adds, dels = [], 0, [], []

    def flush():
        nonlocal adds, dels
        if dels:
            parts, cur, weight = [], [], 0.0
            for idx in dels:
                if breaks.get(idx) and cur and weight > ROW_LIMIT * 0.5:
                    parts.append(cur)
                    cur, weight = [], 0.0
                cur.append(ra[idx])
                weight += ra[idx].w
            parts.append(cur)
            for p, part in enumerate(parts):
                if p:
                    out.append("\\nonumber\\\\ &\\quad ")
                out.append(mark_cells([x for x in apart(part) if type(x) is not Struct], mark_del))
            if rowbreak and adds and seq_w([ra[x] for x in dels]) + seq_w(adds) > PAIR_BREAK:
                out.append("\\nonumber\\\\ &\\quad ")
        if adds:
            out.append(mark_cells(adds, mark_add))
        adds, dels = [], []

    def emit_structure(upto):
        nonlocal q
        while q < upto:
            x = b[q]
            if type(x) is Struct:
                if adds:
                    flush()      # deletions wait for the row that holds their replacement
                out.append(x.render())
            elif adds:
                adds.append(x)
            else:
                out.append(x.render())
            q += 1

    for i, j in ops:
        if i is not None and j is None:
            dels.append(i)
        elif i is None:
            emit_structure(rb_idx[j])
            adds.append(rb[j])
            q = rb_idx[j] + 1
        else:
            emit_structure(rb_idx[j])
            flush()
            out.append(pair(ra[i], rb[j], rowbreak))
            q = rb_idx[j] + 1
    flush()
    emit_structure(len(b))
    return "".join(out)


def pair(a, b, rowbreak=False):
    """Render two nodes judged similar."""
    if a.canon == b.canon:
        return b.render()
    x, y = unwrap(a), unwrap(b)
    if x.canon == y.canon:
        return b.render()
    if isinstance(x, Atom) or isinstance(y, Atom):
        p, q = as_atom(x), as_atom(y)
        if p.nuc is None or q.nuc is None:
            nuc = mark_del(p.nuc.render()) if p.nuc else ""
            nuc += mark_add(q.nuc.render()) if q.nuc else ""
        elif p.nuc.canon == q.nuc.canon:
            nuc = q.nuc.render()
        elif similar(p.nuc, q.nuc):
            nuc = pair(p.nuc, q.nuc, rowbreak)
        else:
            nuc = mark_del(p.nuc.render()) + mark_add(q.nuc.render())
        return (nuc or "{}") + pair_script("_", p.sub, q.sub) + pair_script("^", p.sup, q.sup)
    if isinstance(x, Group) and isinstance(y, Group):
        return "{" + diff_seq(x.kids, y.kids) + "}"
    if isinstance(x, Frac) and isinstance(y, Frac):
        return "{" + diff_seq(x.num, y.num) + " \\over " + diff_seq(x.den, y.den) + "}"
    if isinstance(x, Delim) and isinstance(y, Delim) and x.k == y.k:
        return y.o + diff_seq(x.kids, y.kids, rowbreak and spans_rows(y)) + y.c
    if isinstance(x, Cmd) and isinstance(y, Cmd) and x.name == y.name and not x.opaque:
        o = "[" + y.opt + "]" if y.opt else ""
        return "\\" + y.name + o + "".join(
            "{" + diff_seq(p.kids, q.kids) + "}" for p, q in zip(x.args, y.args))
    if isinstance(x, Env) and isinstance(y, Env) and x.name == y.name:
        return "\\begin{" + y.name + "}" + y.opt + diff_seq(x.kids, y.kids) + "\\end{" + y.name + "}"
    return mark_del(a.render()) + mark_add(b.render())


def pair_script(c, p, q):
    if p is None and q is None:
        return ""
    if p is None:   # a lone script is written on a doubled empty base, which view() recognizes
        return mark_add("{}{}" + c + q.render())
    if q is None:
        return mark_del("{}{}" + c + p.render())
    if p.canon == q.canon:
        return c + q.render()
    return c + "{" + diff_seq(p.kids, q.kids) + "}"


# --- reading a rendered formula back ----------------------------------------------------------------
def view(s, keep):
    """The formula with \\DIFadd or \\DIFdel removed: keep = 'old' keeps deletions, 'new' additions."""
    out, i = [], 0
    drop, take = ("\\DIFadd{", "\\DIFdel{") if keep == "old" else ("\\DIFdel{", "\\DIFadd{")
    while i < len(s):
        if s.startswith(drop, i) or s.startswith(take, i):
            is_drop = s.startswith(drop, i)
            a, j = brace_arg(s, i + 8 - 1)
            if not is_drop:
                v = view(a, keep)
                out.append(v[4:] if v[:5] in ("{}{}_", "{}{}^") else v)   # see pair_script
            i = j
        elif s[i] == "\\":
            m = CTRL.match(s, i)
            out.append(m.group(0))
            i = m.end()
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def canon_of(s):
    return seq_canon(parse(s))


def check_formula(rendered, old, new, where):
    for side, src in (("old", old), ("new", new)):
        got, want = canon_of(view(rendered, side)), canon_of(src)
        if got != want:
            k = next((q for q, (x, y) in enumerate(zip(got, want)) if x != y), min(len(got), len(want)))
            raise SystemExit("eqdiff: %s side of %s does not read back:\n got  %s\n want %s\n rendered %s" % (
                side, where, got[max(0, k - 60):k + 60], want[max(0, k - 60):k + 60], rendered[:400]))


def diff_inline(old, new):
    """Marked formula for two in-line formulas (without the dollars)."""
    r = diff_seq(parse(old), parse(new))
    check_formula(r, old, new, "formula " + new[:50])
    return r


# --- displays --------------------------------------------------------------------------------------
DISPLAY = re.compile(r"\\begin\{(align|equation|gather|multline|eqnarray)(\*?)\}(.*?)\\end\{\1\2\}", re.S)
TIKZ_B, TIKZ_E = r"\begin{tikzpicture}", r"\end{tikzpicture}"
WHOLE_BELOW = 0.50    # a pair with less in common than this is shown old struck + new underlined


def ph(pid):
    """Three plain words: latexdiff merges a common stretch of fewer tokens into the changes around it
    (MINWORDSBLOCK = 3), so a one-word placeholder between new sentences would be taken out and put back."""
    return "EQBLKa%dq EQBLKb%dq EQBLKc%dq" % (pid, pid, pid)


def body_start(s):
    return s.index(r"\begin{document}") + len(r"\begin{document}")


def find_tikz(s):
    """Outermost tikzpictures of the body, depth-aware: [(start, end)]."""
    res, i = [], body_start(s)
    while True:
        j = s.find(TIKZ_B, i)
        if j < 0:
            return res
        d, k = 0, j
        while True:
            if s.startswith(TIKZ_B, k):
                d, k = d + 1, k + len(TIKZ_B)
            elif s.startswith(TIKZ_E, k):
                d, k = d - 1, k + len(TIKZ_E)
                if d == 0:
                    break
            else:
                k += 1
        res.append((j, k))
        i = k


def envs(s):
    """Display environments of the body as dicts, in order."""
    tikz = find_tikz(s)
    res = []
    for m in DISPLAY.finditer(s, body_start(s)):
        if any(a <= m.start() < b for a, b in tikz):
            continue
        tree = parse(m.group(3))
        labels = [x.t[7:-1] for x in tree if type(x) is Struct and x.t.startswith("\\label{")]
        res.append({"name": m.group(1), "star": m.group(2), "src": m.group(3), "span": m.span(),
                    "tree": tree, "labels": labels, "w": seq_w(tree)})
    return res


def env_sim(a, b):
    s = seq_score(a["tree"], b["tree"])
    return s / (0.5 * (a["w"] + b["w"])) if a["w"] + b["w"] else 1.0


def pair_envs(o, n):
    """Order-preserving pairing of old and new displays: a shared label or enough in common."""
    N, M = len(o), len(n)
    S = [[0.0] * M for _ in range(N)]
    for i in range(N):
        for j in range(M):
            if abs(i - j) > 60 and not set(o[i]["labels"]) & set(n[j]["labels"]):
                continue
            sim = 1.0 if o[i]["tree"] and seq_canon(o[i]["tree"]) == seq_canon(n[j]["tree"]) else env_sim(o[i], n[j])
            same = bool(set(o[i]["labels"]) & set(n[j]["labels"]))
            if same:
                S[i][j] = 3.0 + sim
            elif sim >= 0.45:
                S[i][j] = sim
    B = [[0.0] * (M + 1) for _ in range(N + 1)]
    for i in range(N - 1, -1, -1):
        for j in range(M - 1, -1, -1):
            B[i][j] = max(B[i + 1][j], B[i][j + 1], S[i][j] + B[i + 1][j + 1] if S[i][j] else -1)
    pairs, i, j = [], 0, 0
    while i < N and j < M:
        if S[i][j] and abs(B[i][j] - S[i][j] - B[i + 1][j + 1]) < 1e-9:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif abs(B[i][j] - B[i + 1][j]) < 1e-9:
            i += 1
        else:
            j += 1
    return pairs


def width(x, f=1.0):
    """Rough printed width of a node in em (f = font scale); only rows that are clearly too wide matter."""
    if isinstance(x, Neutral):
        return 1.0 * f if "quad" in x.t else 0.0
    if isinstance(x, Struct):
        return 0.0
    if isinstance(x, Tok):
        return f * (1.6 if x.t in LOW and x.t not in ",.;()[]|" else 0.5 if x.t in ",.;()[]|"
                    else 0.5 * len(x.t) if x.t.isdigit() else 1.6 if x.t.startswith("\\Delta ") else 1.0)
    if isinstance(x, Group):
        return sum(width(k, f) for k in x.kids)
    if isinstance(x, Frac):
        return 0.4 * f + max(sum(width(k, f) for k in x.num), sum(width(k, f) for k in x.den))
    if isinstance(x, Delim):
        return 0.9 * f + sum(width(k, f) for k in x.kids)
    if isinstance(x, Atom):
        return (width(x.nuc, f) if x.nuc else 0) + max(width(x.sub, 0.7 * f) if x.sub else 0,
                                                       width(x.sup, 0.7 * f) if x.sup else 0)
    if isinstance(x, Cmd):
        if x.opaque:
            return f * (1.0 if len(x.args[0]) < 2 else 0.5 * len(x.args[0]))
        return (1.0 * f if x.name == "sqrt" else 0.0) + sum(width(k, f) for k in x.args)
    if isinstance(x, Env):
        return 2.0 * f + 0.6 * sum(width(k, f) for k in x.kids)
    return 0.0


def split_widest_row(body):
    """The widest row of a display that overflowed (the old symbols are printed too) gets a second line."""
    tree = parse(body)
    rows, cur = [], []
    for k, x in enumerate(tree):
        cur.append(k)
        if type(x) is Struct and x.t.startswith("\\\\"):
            rows.append(cur)
            cur = []
    rows.append(cur)
    row = max(rows, key=lambda r: sum(width(tree[k]) for k in r))
    total = sum(width(tree[k]) for k in row)
    cells = [k for k in row if type(tree[k]) is Struct and tree[k].t == "&"]
    if len(cells) >= 3:     # `a &= b, & c &= d`: the second formula goes under the first
        cut, drop = cells[1], True
    else:
        best, done, cut, drop = None, sum(width(tree[k]) for k in row if k < (cells[-1] if cells else 0)), None, False
        for k in row:
            if type(tree[k]) is Struct or (cells and k < cells[-1]):
                continue
            if done > total * 0.3 and (best is None or abs(done - total / 2) < best):
                best, cut = abs(done - total / 2), k
            done += width(tree[k])
    out = []
    for k, x in enumerate(tree):
        if k == cut:
            out.append("\\nonumber\\\\ " if drop else "\\nonumber\\\\ &\\quad ")
            if drop:
                continue
        out.append(x.render())
    return "".join(out)


def render_pair(a, b, split=False):
    """Rendered display for a paired old and new environment, and how it was shown."""
    env = b["name"] + b["star"]
    if seq_canon(a["tree"]) == seq_canon(b["tree"]):
        return "\\begin{%s}%s\\end{%s}" % (env, b["src"], env), "same"
    if env_sim(a, b) < WHOLE_BELOW:
        return render_old(a) + "\n" + render_new(b), "whole"
    body = diff_seq(a["tree"], b["tree"], rowbreak=env.startswith("align") or env.startswith("eqnarray"))
    if split and env.startswith("align"):
        body = split_widest_row(body)
    check_formula(body, a["src"], b["src"], "display " + ",".join(b["labels"] or ["(no label)"]))
    return "\\begin{%s}%s\\end{%s}" % (env, body, env), "fine"


def render_cells(tree, mark):
    """Every cell of a one-sided display marked, the alignment kept."""
    out, cell = [], []

    def flush():
        nonlocal cell
        if cell:
            out.append(mark(seq_render(cell)))
        cell = []

    for x in apart(tree):
        if type(x) is Struct:
            if x.t.startswith("\\label") or x.t in ("\\nonumber", "\\notag"):
                if mark is mark_del:
                    continue
            flush()
            out.append(x.render())
        else:
            cell.append(x)
    flush()
    return "".join(out)


def render_old(a):
    env = a["name"] + "*" if a["name"] != "eqnarray" else "eqnarray*"
    body = render_cells(a["tree"], mark_del)
    if canon_of(view(body, "old")) != canon_of(a["src"]):
        raise SystemExit("eqdiff: a deleted display does not read back: " + a["src"][:200])
    return "\\begin{%s}%s\\end{%s}" % (env, body, env)


def render_new(b):
    env = b["name"] + b["star"]
    body = render_cells(b["tree"], mark_add)
    if canon_of(view(body, "new")) != canon_of(b["src"]):
        raise SystemExit("eqdiff: an added display does not read back: " + b["src"][:200])
    return "\\begin{%s}%s\\end{%s}" % (env, body, env)


def mark_picture(x, y):
    """The new picture, with each formula that differs from the old picture marked."""
    lx, ly = x.split("\n"), y.split("\n")
    if x == y or len(lx) != len(ly):
        return y
    out = []
    for p, q in zip(lx, ly):
        fp, fq = [t for f, t in split_inline(p) if f], split_inline(q)
        if p != q and len(fp) == sum(1 for f, _ in fq if f):
            old, res = iter(fp), ""
            for f, t in fq:
                res += "$" + diff_inline(next(old), t) + "$" if f else t
            q = res
        out.append(q)
    return "\n".join(out)


def protect(op, np, tp, wide=None):
    o, n = open(op, encoding="utf-8").read(), open(np, encoding="utf-8").read()
    wide = set(open(wide).read().split()) if wide else set()
    load_macros(o)
    load_macros(n)
    eo, en = envs(o), envs(n)
    pairs = pair_envs(eo, en)
    table, rep_o, rep_n = {}, [], []
    report = []
    pid = 0
    done_o, done_n = set(), set()
    for i, j in pairs:
        pid += 1
        text, how = render_pair(eo[i], en[j], str(pid) in wide)
        table[str(pid)] = {"text": text, "how": how, "old": render_old(eo[i]), "new": render_new(en[j])}
        rep_o.append((eo[i]["span"], ph(pid)))
        rep_n.append((en[j]["span"], ph(pid)))
        done_o.add(i)
        done_n.add(j)
        report.append({"id": pid, "how": how, "labels": en[j]["labels"], "old_labels": eo[i]["labels"],
                       "sim": round(env_sim(eo[i], en[j]), 3)})
    for i, e in enumerate(eo):
        if i not in done_o:
            pid += 1
            table[str(pid)] = {"text": render_old(e), "how": "deleted"}
            rep_o.append((e["span"], ph(pid)))
            report.append({"id": pid, "how": "deleted", "labels": [], "old_labels": e["labels"], "sim": 0})
    for j, e in enumerate(en):
        if j not in done_n:
            pid += 1
            table[str(pid)] = {"text": render_new(e), "how": "added"}
            rep_n.append((e["span"], ph(pid)))
            report.append({"id": pid, "how": "added", "labels": e["labels"], "old_labels": [], "sim": 0})
    # pictures: the same trick (latexdiff mangles nested tikzpictures)
    to, tn = find_tikz(o), find_tikz(n)
    if len(to) == len(tn):
        for (a, b), (c, d) in zip(to, tn):
            pid += 1
            table[str(pid)] = {"text": mark_picture(o[a:b], n[c:d]), "how": "picture"}
            rep_o.append(((a, b), ph(pid)))
            rep_n.append(((c, d), ph(pid)))

    def apply(s, reps):
        for (a, b), ph in sorted(reps, reverse=True):
            s = s[:a] + ph + s[b:]
        return s

    open(op, "w", encoding="utf-8").write(apply(o, rep_o))
    open(np, "w", encoding="utf-8").write(apply(n, rep_n))
    json.dump({"table": table, "report": report}, open(tp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    how = {}
    for r in report:
        how[r["how"]] = how.get(r["how"], 0) + 1
    print("displays:", how)


# --- filling the placeholders in ---------------------------------------------------------------------
def fill(s, table, moved):
    """Replace placeholders; one that sits inside \\DIFdel{...} or \\DIFadd{...} splits that group."""
    pat = re.compile(r"EQBLKa(\d+)q\s+EQBLKb\1q\s+EQBLKc\1q")
    while True:
        m = pat.search(s)
        if not m:
            if "EQBLK" in s:
                raise SystemExit("eqdiff: a placeholder was split by latexdiff")
            return s
        e = table[m.group(1)]
        if s[s.rfind("\n", 0, m.start()) + 1:].startswith("%"):
            raise SystemExit("eqdiff: placeholder %s in a comment" % m.group(0))
        # the \DIFadd{ / \DIFdel{ around the placeholder, if any
        st = max(s.rfind("\\DIFadd{", 0, m.start()), s.rfind("\\DIFdel{", 0, m.start()))
        if st >= 0:
            end = brace_arg(s, st + 8 - 1)[1]
            if end > m.end():
                # latexdiff took this display out here or put it in here: it moved, or its text did
                side = "old" if s[st:st + 8] == "\\DIFdel{" else "new"
                moved.append(m.group(1))
                cmd, before, after = s[st:st + 8], s[st + 8:m.start()], s[m.end():end - 1]
                piece = (cmd + before + "}" if before.strip() else "") + "\n" + e.get(side, e["text"]) + "\n" + \
                    (cmd + after + "}" if after.strip() else "")
                s = s[:st] + piece + s[end:]
                continue
        s = s[:m.start()] + e["text"] + s[m.end():]


DIFPAIR = re.compile(r"\\DIFdelbegin \\DIFdel\{")


def split_inline(t):
    """[(is_formula, text)] for a stretch of text."""
    parts, i = [], 0
    for m in re.finditer(r"(?<!\\)\$(.+?)(?<!\\)\$", t, re.S):
        if m.start() > i:
            parts.append((False, t[i:m.start()]))
        parts.append((True, m.group(1)))
        i = m.end()
    if i < len(t):
        parts.append((False, t[i:]))
    return parts


def inline_pairs(s, log):
    """`\\DIFdel{... $a$ ...}\\DIFadd{... $b$ ...}`: mark inside a and b when they are similar."""
    out, pos = [], 0
    for m in DIFPAIR.finditer(s):
        if m.start() < pos:
            continue
        x, e1 = brace_arg(s, m.end() - 1)
        tail = s[e1:]
        mid = re.match(r"\s*\\DIFdelend\s*\\DIFaddbegin\s*\\DIFadd\{", tail)
        if not mid:
            continue
        ybrace = e1 + mid.end() - 1
        y, e2 = brace_arg(s, ybrace)
        mend = re.match(r"\s*\\DIFaddend ?", s[e2:])
        if not mend:
            continue
        px, py = split_inline(x), split_inline(y)
        fx = [t for f, t in px if f]
        fy = [t for f, t in py if f]
        if not fx or not fy:
            continue
        nx, ny = [parse(t) for t in fx], [parse(t) for t in fy]
        gx, gy = [Group(t) for t in nx], [Group(t) for t in ny]
        match = {}
        ops = align(gx, gy)[1]
        for i, j in ops:
            if i is not None and j is not None:
                match[i] = j
        if not match:
            log["whole"] += len(fx)
            log["left"].append((fx, fy))
            continue
        # walk the old parts; a matched formula closes the runs of both sides up to it
        res, ix, qy = [], 0, 0
        pending_x = []

        def flush_y(upto):
            nonlocal qy
            t = ""
            while qy < len(py) and not (py[qy][0] and fy_index[qy] == upto):
                f, v = py[qy]
                t += ("$" + v + "$") if f else v
                qy += 1
            return t

        fy_index, c = {}, 0
        for q, (f, _) in enumerate(py):
            if f:
                fy_index[q] = c
                c += 1
        for f, v in px:
            if f and ix in match:
                j = match[ix]
                dtext = "".join(pending_x)
                atext = flush_y(j)
                res.append(("\\DIFdelbegin \\DIFdel{" + dtext + "}\\DIFdelend " if dtext.strip() else "") +
                           ("\\DIFaddbegin \\DIFadd{" + atext + "}\\DIFaddend " if atext.strip() else ""))
                res.append("$" + diff_inline(v, fy[j]) + "$")
                qy += 1
                pending_x = []
                log["fine"] += 1
                ix += 1
            else:
                pending_x.append(("$" + v + "$") if f else v)
                ix += 1 if f else 0
        dtext = "".join(pending_x)
        atext = flush_y(-1)
        res.append(("\\DIFdelbegin \\DIFdel{" + dtext + "}\\DIFdelend " if dtext.strip() else "") +
                   ("\\DIFaddbegin \\DIFadd{" + atext + "}\\DIFaddend " if atext.strip() else atext))
        out.append(s[pos:m.start()])
        out.append("".join(res))
        pos = e2 + mend.end()
    out.append(s[pos:])
    return "".join(out)


def old_refs(s, aux):
    """A deleted sentence may cite a deleted equation: print the old number instead of (??)."""
    have = set(re.findall(r"\\label\{([^}]*)\}", s))
    num = dict(re.findall(r"\\newlabel\{([^}]*)\}\{\{([^}]*)\}", open(aux, encoding="utf-8", errors="replace").read()))
    n = 0

    def sub(m):
        nonlocal n
        lab = m.group(1)
        if lab in have or lab not in num:
            return m.group(0)
        n += 1
        return "(" + num[lab] + ")"

    s = re.sub(r"\\eqref\{([^}]*)\}", sub, s)
    print("references to old-only equations printed with their old number:", n)
    return s


def restore(dp, tp, aux=None):
    data = json.load(open(tp, encoding="utf-8"))
    s = open(dp, encoding="utf-8").read()
    moved = []
    s = fill(s, data["table"], moved)
    log = {"fine": 0, "whole": 0, "left": []}
    s = inline_pairs(s, log)
    if aux:
        s = old_refs(s, aux)
    open(dp, "w", encoding="utf-8").write(s)
    print("in-line formulas marked inside:", log["fine"], "/ left as a replacement:", log["whole"])
    data["moved"], data["inline_left"] = moved, log["left"]
    json.dump(data, open(tp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    pairs = [r for r in data["report"] if r["how"] in ("same", "fine")]
    print("moved:", sorted({",".join(r["labels"]) for r in pairs if str(r["id"]) in moved}))
    print("shown whole:", [",".join(r["labels"]) for r in data["report"] if r["how"] == "whole"])
    print("marked symbol by symbol:", sum(r["how"] == "fine" for r in data["report"]))


def overflow(lp, dp, tp):
    """Print the ids of the marked displays that overflowed their column by more than 12 pt."""
    table = json.load(open(tp, encoding="utf-8"))["table"]
    lines = open(dp, encoding="utf-8").read().split("\n")
    log = open(lp, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"Overfull \\hbox \(([\d.]+)pt too wide\) detected at line (\d+)", log):
        if float(m.group(1)) > 12:
            line = lines[int(m.group(2)) - 1]
            for k, e in table.items():
                if e["how"] == "fine" and e["text"] in line:
                    print(k)


def selftest():
    cases = [
        (r"\exp\fn{-{1\over2c_{a+b}}(x-y\Delta t)^2}", r"\exp\fn{-{1\over2}(x-y\Delta t)(M^{-1})^{ij}(z-y\Delta t)}"),
        (r"a_{b}+c", r"a_{d}+c"),
        (r"s_{t}", r"\widetilde{s}_{t}"),
        (r"{a\over b}+c", r"\frac{a}{b+2}+c"),
        (r"\begin{cases}a&b\\c&d\end{cases}", r"\begin{cases}a&b\\c&e\end{cases}"),
        (r"x^2", r"x"),
        (r"x", r"x_{1}^{2}"),
    ]
    ok = True
    for old, new in cases:
        r = diff_seq(parse(old), parse(new), rowbreak=True)
        try:
            check_formula(r, old, new, "selftest")
        except SystemExit as ex:
            ok = False
            print(ex)
        if "\\DIFadd" not in r and "\\DIFdel" not in r:
            ok = False
            print("no mark:", old, new, r)
    load_macros("\\newcommand{\\twoarg}[2]{#1#2}\n\\newcommand{\\al}{\\sqrt}\n\\begin{document}")
    r = diff_seq(parse(r"\twoarg{a}{b}+\al{c}"), parse(r"\twoarg{a}{d}+\al{e}"))
    if "\\twoarg{a}{\\DIFdel{b}\\DIFadd{d}}" not in r or "\\al{\\DIFdel{c}\\DIFadd{e}}" not in r:
        ok = False
        print("macro from the preamble:", r)
    pic = mark_picture("\\node {$f\\fn{a-b}$};\nx", "\\node {$f\\fn{a-c}$};\nx")
    if "\\DIFdel{b}" not in pic or "\\DIFadd{c}" not in pic or not pic.startswith("\\node {$"):
        ok = False
        print("picture:", pic)
    for old, new in ((r"a+\pn{b}", r"a+(b)"), (r"x\exp(-1)", r"x\exp\Big(-1\Big)"),
                     (r"a &= b \nonumber\\ &\quad+c", r"a &= b+c \label{eq:x}")):
        same = diff_seq(parse(old), parse(new))
        if "DIF" in same:   # delimiter size and row layout are not changes
            ok = False
            print("marked:", same)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["--selftest"]:
        sys.exit(selftest())
    if len(a) in (4, 5) and a[0] == "protect":
        protect(*a[1:])
    elif len(a) == 4 and a[0] == "overflow":
        overflow(a[1], a[2], a[3])
    elif len(a) in (3, 4) and a[0] == "restore":
        restore(*a[1:])
    else:
        sys.exit(__doc__)
    if unknown_cmds:
        print("followed by a brace, taken to have no argument (a macro with one breaks the marks):",
              sorted(unknown_cmds))
