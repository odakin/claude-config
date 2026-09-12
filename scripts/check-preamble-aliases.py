#!/usr/bin/env python3
r"""check-preamble-aliases.py — flag raw notation where the preamble defines an alias.

Canonical layer-1 source:
https://github.com/odakin/claude-config/blob/main/scripts/check-preamble-aliases.py
Distribution contract:
https://github.com/odakin/claude-config/blob/main/conventions/shared-repo.md#style-checker-mirror
Project copies are generated mirrors so collaborators and CI can run the gate
offline without an owner-specific repository or machine path — do not edit a
copy. Everything project-specific belongs in that project's
``.claude/preamble-aliases.json``, never in this file.

Enforces the rule in ``conventions/latex.md#macro-alias-forcing-function``: if the
preamble defines a macro for a concept, the body must not spell that concept out
in raw primitive notation.  Nothing about any one manuscript is hard-coded — the
alias vocabulary is **derived from the preamble of the file being checked**, so a
new ``\newcommand`` is enforced from the moment it is defined:

    \newcommand{\rh}{\hat\rho}        body "\hat\rho"    -> use \rh
    \newcommand{\wh}[1]{\widehat{#1}} body "\widehat{X}" -> use \wh
    \newcommand{\al}[1]{\begin{align}#1\end{align}}
                                      body "\begin{align}...\end{align}" -> use \al

Matching is token-based, not textual, so LaTeX-equivalent spellings collapse onto
one pattern: whitespace after a control word is ignored and braces around a single
token are optional (``\hat\rho`` = ``\hat \rho`` = ``\hat{\rho}``).  A control word
must match whole (``\hat`` never matches inside ``\hatwhole``) and so must a letter
run (a pattern for ``T_\tx{D}`` does not fire inside ``ST_\tx{D}``).  When several
patterns overlap, only the longest is reported, which is what catches a **compound
macro written longhand out of legitimate atoms** (``\hat\rho_\S`` is reported as
``\rhS``, not as ``\rh``) — the bypass class that atom-level greps miss.

False positives are designed out rather than filtered after the fact.  Skipped:

1. Anything in a TeX comment, and anything inside verbatim-like environments.
2. The preamble itself, and any body line that is a definition (``\newcommand`` and
   friends) — a macro is allowed to spell out what it defines.
3. **Bodies with no control sequence at all.**  This is the important one:
   ``\DeclareMathOperator{\Tr}{Tr}`` has body "Tr", and a checker that took it
   literally would flag the letters "Tr" throughout the manuscript.  Prose macros
   (``\newcommand{\etal}{et al.}``) go the same way.  Plain-text bodies are outside
   what this class of check can judge, so they are never reported, in strict mode
   either.  (See the "mechanize の限界" note in latex.md: a rule that cannot
   distinguish raw from correct must stay with discipline, not become a noisy gate.)
4. **Bodies that are a single control sequence which is itself defined in the
   preamble** (``\newcommand{\cond}{{\Ih}}`` where ``\Ih`` is an alias).  That is a
   semantic renaming of an alias, not a raw form, so uses of ``\Ih`` are correct and
   must not be rewritten to ``\cond``.  A single *undefined* control sequence is the
   opposite case and is reported (``\newcommand{\h}{\hat}`` -> raw ``\hat``).
5. **Patterns that begin with an argument placeholder**
   (``\newcommand{\opa}[1]{{#1}^{}}``).  Such a pattern is anchored on nothing and
   matches ordinary structure rather than a notation.  A body that begins with a
   literal is fine even when that literal is plain text (``T_\tx{D}``), because a
   letter run has to match whole.
6. **Argument-taking macros whose placeholders are not ``#1..#n`` each exactly once
   in order** — matching those needs a back-reference, and guessing produces noise.

Items 4 and 5 are reported under ``--strict``, which is for exploring a manuscript,
not for gating it.  Math-mode vs text-mode is *not* tracked (custom display
wrappers make it unreliable); a body that uses ``\text`` outside math is reported
like any other use.

Repo-specific values that cannot be derived — a compound whose raw spelling has no
single preamble body, a macro to exempt, a soft-only warning — go in
``.claude/preamble-aliases.json`` at the repo root (found by walking up from the
target; ``--config`` overrides, and a file next to the script is the last resort),
so the engine itself stays identical everywhere it is mirrored.  That file is also
the **opt-in switch**: the personal-layer pre-commit chain gates a repo exactly
when it exists, so no repo starts failing commits until someone has decided what
its findings mean.

    {"targets": ["main.tex", "part2/main.tex"],
     "preamble": "preamble.tex",
     "ignore_macros": ["\\cond"],
     "soft_macros": ["\\red"],
     "extra_hard": [{"pattern": "\\\\Tr\\\\sqbr\\{", "label": "\\Tr\\sqbr{",
                     "suggest": "\\Tr\\fnl{"}],
     "extra_soft": [{"pattern": "\\\\red\\{", "label": "\\red{...} (drafting marker?)"}]}

``--fix`` rewrites the raw forms in place *through the same matcher that found
them*, which is the only reason a sweep of this size is safe to run at all: the
replacement comes from the token span the matcher consumed, not from a regex
written by hand a second time.  It writes the alias that the manuscript already
uses when several share a body, keeps the argument text verbatim, inserts a space
when the alias would otherwise run into a following letter (``\Ah`` + ``B``), and
re-runs to a fixed point so a finding nested inside another's argument is not
undone by the outer rewrite.  Config-declared ``extra_hard`` regexes are reported
but never auto-fixed (a regex has no argument structure to carry over).  It is a
source rewrite: read the diff and rebuild the PDF before committing.

Exit 0 = clean or soft-only, 1 = hard violations, 2 = a target could not be read.

Usage:
  check-preamble-aliases.py                 # targets from config, else *.tex in cwd
  check-preamble-aliases.py paper.tex ...   # explicit targets
  check-preamble-aliases.py --preamble preamble.tex fragment.tex
  check-preamble-aliases.py --list paper.tex     # show the derived patterns
  check-preamble-aliases.py --json paper.tex
  check-preamble-aliases.py --fix paper.tex      # rewrite raw -> alias in place
  check-preamble-aliases.py --strict paper.tex   # exploratory, noisier
  check-preamble-aliases.py --selftest
"""
import argparse
import json
import os
import re
import sys
import tempfile

CANONICAL = "https://github.com/odakin/claude-config/blob/main/scripts/check-preamble-aliases.py"

TOKEN_RE = re.compile(r"\\[A-Za-z]+|\\[^A-Za-z\s]|[A-Za-z]+|[0-9]+|[ \t\r\n]+|.", re.S)

VERBATIM_ENVS = ("verbatim", "Verbatim", "lstlisting", "minted", "alltt", "comment")

DEF_COMMANDS = (
    r"\newcommand", r"\renewcommand", r"\providecommand", r"\def", r"\let",
    r"\DeclareMathOperator", r"\NewDocumentCommand", r"\RenewDocumentCommand",
    r"\DeclareRobustCommand", r"\DeclarePairedDelimiter",
)

MAX_ARG_TOKENS = 400          # widest gap an argument placeholder may span
MAX_LINES_SHOWN = 5


class Arg:
    """Argument placeholder inside a derived pattern."""

    __slots__ = ()

    def __repr__(self):
        return "#"


ARG = Arg()


class Tok:
    __slots__ = ("text", "line", "start", "end")

    def __init__(self, text, line, start, end):
        self.text = text
        self.line = line
        self.start = start                            # char offset into the scanned text
        self.end = end


# --------------------------------------------------------------------------- #
# source preparation
# --------------------------------------------------------------------------- #
def mask(line, keep=0):
    """Replace everything from `keep` on with spaces, preserving the line's length."""
    return line[:keep] + " " * (len(line) - keep)


def strip_comment(line):
    r"""Blank out from the first unescaped % to end of line.

    Masked with spaces rather than truncated so the scanned text keeps the file's
    exact geometry: every token's character offset is also its offset in the file,
    which is what lets ``--fix`` rewrite the original bytes, and what keeps line
    numbers honest.
    """
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            i += 2
            continue
        if line[i] == "%":
            return mask(line, i)
        i += 1
    return line


def blank_verbatim(lines):
    """Blank out verbatim-like environments (their content is not LaTeX notation)."""
    out = []
    open_env = None
    for line in lines:
        if open_env is None:
            m = re.search(r"\\begin\{(" + "|".join(VERBATIM_ENVS) + r")\*?\}", line)
            if m:
                open_env = m.group(1)
                out.append(mask(line))
                continue
            out.append(line)
        else:
            if re.search(r"\\end\{" + re.escape(open_env) + r"\*?\}", line):
                open_env = None
            out.append(mask(line))
    return out


def prepare(path):
    r"""Read a tex file -> (lines, body_start_index or None, original text).

    Lines are masked, never shortened, and every join puts exactly one newline back,
    so ``"\n".join(lines)`` is the original text with comments and verbatim turned
    into spaces — same length, same offsets, same line numbers.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        original = f.read()
    lines = [strip_comment(l) for l in original.split("\n")]
    body_start = None
    for i, line in enumerate(lines):
        if r"\begin{document}" in line:
            body_start = i
            break
    return lines, body_start, original


def tokenize(text, first_line, first_offset=0):
    toks = []
    line = first_line
    for m in TOKEN_RE.finditer(text):
        s = m.group()
        if s[0] in " \t\r\n":
            line += s.count("\n")
            continue
        toks.append(Tok(s, line, first_offset + m.start(), first_offset + m.end()))
        line += s.count("\n")
    return toks


def collapse(items, text_of):
    """Drop braces that wrap exactly one token; repeat to a fixed point."""
    for _ in range(6):
        out = []
        i = 0
        n = len(items)
        changed = False
        while i < n:
            if (text_of(items[i]) == "{" and i + 2 < n and text_of(items[i + 2]) == "}"
                    and text_of(items[i + 1]) not in ("{", "}")):
                inner = items[i + 1]
                if isinstance(inner, Tok):
                    # The surviving token stands for the whole "{X}" in the source, so
                    # --fix replaces the braces too instead of leaving a stray "}".
                    inner.start = items[i].start
                    inner.end = items[i + 2].end
                out.append(inner)
                i += 3
                changed = True
                continue
            out.append(items[i])
            i += 1
        items = out
        if not changed:
            break
    return items


# --------------------------------------------------------------------------- #
# preamble -> alias vocabulary
# --------------------------------------------------------------------------- #
def read_group(s, i):
    """s[i] == '{' -> (content, index just past the matching '}') or (None, i)."""
    if i >= len(s) or s[i] != "{":
        return None, i
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\" and j + 1 < len(s):
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return None, i


def find_def_aliases(text):
    """Names that a repo uses as a stand-in for \\newcommand (\\let\\nc\\newcommand ...)."""
    names = set()
    for m in re.finditer(r"\\let\s*\\([A-Za-z]+)\s*=?\s*\\(?:re|provide)?newcommand\b", text):
        names.add(m.group(1))
    for m in re.finditer(r"\\(?:re|provide)?newcommand\*?\s*\{\s*\\([A-Za-z]+)\s*\}\s*"
                         r"\{\s*\\(?:re|provide)?newcommand\*?\s*\}", text):
        names.add(m.group(1))
    return names


def parse_definitions(text):
    """-> {macro name: body string}. Later definitions win (they are what TeX uses)."""
    alias = find_def_aliases(text)
    heads = ["(?:re|provide)?newcommand", "DeclareRobustCommand", "DeclareMathOperator"]
    heads += [re.escape(a) for a in sorted(alias)]
    head_re = re.compile(
        r"\\(?:" + "|".join(heads) + r")\*?\s*"
        r"(?:\{\s*\\([A-Za-z]+)\s*\}|\\([A-Za-z]+))\s*"
        r"(?:\[\s*\d+\s*\]\s*)?(?:\[[^\]\n]*\]\s*)?")
    defs = {}
    for m in head_re.finditer(text):
        name = m.group(1) or m.group(2)
        body, _ = read_group(text, m.end())
        if body is not None:
            defs["\\" + name] = body
    for m in re.finditer(r"\\def\s*\\([A-Za-z]+)\s*(?=\{)", text):
        body, _ = read_group(text, m.end())
        if body is not None:
            defs["\\" + m.group(1)] = body
    return defs


def build_pattern(body, defined, strict):
    """Body string -> (items, display) or None when the body is not a raw form we judge."""
    toks = tokenize(body, 1)
    items = []
    i = 0
    seen = []
    while i < len(toks):
        if toks[i].text == "#" and i + 1 < len(toks) and toks[i + 1].text.isdigit():
            seen.append(toks[i + 1].text)
            items.append(ARG)
            i += 2
            continue
        items.append(toks[i].text)
        i += 1
    items = collapse(items, lambda x: "" if x is ARG else x)

    if seen and seen != [str(k + 1) for k in range(len(seen))]:
        return None                                   # rule 6: needs a back-reference
    if not items:
        return None
    cs = [x for x in items if x is not ARG and x.startswith("\\")]
    if not cs:
        return None                                   # rule 3: plain text, never judged
    if any(c in DEF_COMMANDS for c in cs):
        return None
    if items[0] is ARG and not strict:
        return None                                   # rule 5: unanchored
    if len(items) == 1 and items[0] in defined:
        if not strict:
            return None                               # rule 4: alias of an alias
    display = re.sub(r"\s+", " ", body).strip()
    return items, display


class Pattern:
    def __init__(self, items, display, macros, soft):
        self.items = items
        self.display = display
        self.macros = macros
        self.soft = soft

    @property
    def suggest(self):
        return " / ".join(self.macros)


def render(items):
    """Token list -> a readable one-line spelling (used for expanded variants)."""
    out = ""
    prev = ""
    for it in items:
        t = "{...}" if it is ARG else it
        if prev.startswith("\\") and len(prev) > 1 and prev[1].isalpha() and t[:1].isalnum():
            out += " "
        out += t
        prev = t
    return out


def zero_arg_bodies(defs):
    """Macros whose body takes no argument, as token lists (for chained expansion)."""
    zero = {}
    for name, body in defs.items():
        if "#" in body:
            continue
        toks = collapse([t.text for t in tokenize(body, 1)], lambda x: x)
        if toks:
            zero[name] = toks
    return zero


def expansions(items, own, zero, limit=4, max_items=60):
    r"""Every level of expanding the zero-argument aliases inside a body.

    A compound alias is often defined in terms of other aliases
    (``\newcommand{\TD}{T_\tx{D}}`` on top of ``\newcommand{\tx}{\text}``), so the
    fully raw spelling (``T_\text{D}``) never appears literally in any one
    definition.  Each level is registered as its own pattern for the same macro,
    which is what catches a raw form written in the underlying primitives.
    """
    out = [items]
    seen = {tuple("#" if x is ARG else x for x in items)}
    cur = items
    for _ in range(limit):
        nxt, changed = [], False
        for it in cur:
            if it is not ARG and it != own and it in zero:
                nxt.extend(zero[it])
                changed = True
            else:
                nxt.append(it)
        if not changed or len(nxt) > max_items:
            break
        cur = collapse(nxt, lambda x: "" if x is ARG else x)
        key = tuple("#" if x is ARG else x for x in cur)
        if key in seen:
            break
        seen.add(key)
        out.append(cur)
    return out


def derive_patterns(defs, ignore, soft_macros, strict):
    zero = zero_arg_bodies(defs)
    grouped = {}
    for name, body in defs.items():
        if name in ignore:
            continue
        built = build_pattern(body, defs, strict)
        if built is None:
            continue
        items, display = built
        for level, variant in enumerate(expansions(items, name, zero)):
            if not variant or variant[0] is ARG:
                continue
            if not any(x is not ARG and x.startswith("\\") for x in variant):
                continue
            key = tuple("#" if x is ARG else x for x in variant)
            slot = grouped.setdefault(key, (variant, display if level == 0 else render(variant), []))
            if name not in slot[2]:
                slot[2].append(name)
    pats = []
    for items, display, macros in grouped.values():
        macros.sort()
        pats.append(Pattern(items, display, macros,
                            all(m in soft_macros for m in macros)))
    pats.sort(key=lambda p: (-len(p.items), p.display))
    return pats


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
def _match(items, ii, hay, hi, args):
    """-> (end, arg_spans) or None. arg_spans are the token ranges an argument ate."""
    while ii < len(items):
        item = items[ii]
        if item is ARG:
            depth = 0
            j = hi
            while j <= len(hay) and (j - hi) <= MAX_ARG_TOKENS:
                if depth == 0 and j > hi:
                    got = _match(items, ii + 1, hay, j, args + [(hi, j)])
                    if got is not None:
                        return got
                if j == len(hay):
                    break
                t = hay[j].text
                if t == "{":
                    depth += 1
                elif t == "}":
                    depth -= 1
                    if depth < 0:
                        break
                j += 1
            return None
        if hi >= len(hay) or hay[hi].text != item:
            return None
        ii += 1
        hi += 1
    return hi, args


def literal_positions(start, end, arg_spans):
    inside = set()
    for a, b in arg_spans:
        inside.update(range(a, b))
    return [p for p in range(start, end) if p not in inside]


def scan(hay, patterns):
    r"""-> list of (pattern, start, end), keeping one reading per stretch of text.

    Two findings conflict only when they claim the same *literal* tokens: that is
    the ``\hat\rho`` / ``\hat\rho_\S`` case, where the longer reading (``\rhS``) is
    the right one and the shorter (``\rh``) is the same text read again.  A finding
    that sits inside another one's **argument** is not a re-reading and is kept —
    a wrapper such as ``{\color{Orange}#1}`` can span several paragraphs, and
    treating its argument as covered would silently hide every raw form inside it.
    """
    index = {}
    for pos, t in enumerate(hay):
        index.setdefault(t.text, []).append(pos)
    raw = []
    for pat in patterns:
        for pos in index.get(pat.items[0], ()):
            got = _match(pat.items, 0, hay, pos, [])
            if got is not None:
                raw.append((pat, pos, got[0], got[1]))
    raw.sort(key=lambda h: (h[1], -(h[2] - h[1])))
    claimed = set()
    kept = []
    for pat, start, end, arg_spans in raw:
        own = literal_positions(start, end, arg_spans)
        if any(p in claimed for p in own):
            continue
        claimed.update(own)
        kept.append((pat, start, end, arg_spans))
    return kept


DEF_LINE_RE = re.compile(r"^\s*\\(?:" + "|".join(c[1:] for c in DEF_COMMANDS) + r")\b")


def is_definition_line(line):
    r"""A line that *starts* a definition (it may legitimately spell out a raw form).

    Anchored at the start, and matched as a whole control word, on purpose: these
    manuscripts write one paragraph per line, so blanking any line that merely
    mentions ``\newcommand`` in prose would drop a whole paragraph from the scan,
    and an unanchored ``\def`` would also swallow every ``\definecolor`` line.
    """
    return bool(DEF_LINE_RE.match(line))


# --------------------------------------------------------------------------- #
# one file
# --------------------------------------------------------------------------- #
def check_file(tex_path, cfg, strict, preamble_override):
    lines, body_start, original = prepare(tex_path)
    if preamble_override:
        pre_lines, _, _ = prepare(preamble_override)
        preamble_text = "\n".join(pre_lines)
        first_body_line = 0
    else:
        if body_start is None:
            return None
        preamble_text = "\n".join(lines[:body_start])
        first_body_line = body_start

    defs = parse_definitions(preamble_text)
    ignore = set(cfg.get("ignore_macros", []))
    soft_macros = set(cfg.get("soft_macros", []))
    patterns = derive_patterns(defs, ignore, soft_macros, strict)

    body_lines = blank_verbatim(lines[first_body_line:])
    body_lines = [mask(l) if is_definition_line(l) else l for l in body_lines]
    body_offset = sum(len(l) + 1 for l in lines[:first_body_line])
    hay = collapse(tokenize("\n".join(body_lines), first_body_line + 1, body_offset),
                   lambda t: t.text)

    hard, soft = {}, {}
    found = scan(hay, patterns)
    for pat, start, _end, _args in found:
        bucket = soft if pat.soft else hard
        bucket.setdefault(pat.suggest, (pat, []))[1].append(hay[start].line)

    for rule in cfg.get("extra_hard", []):
        _apply_extra(rule, body_lines, first_body_line, hard)
    for rule in cfg.get("extra_soft", []):
        _apply_extra(rule, body_lines, first_body_line, soft)

    used = {}
    for t in hay:
        if t.text.startswith("\\"):
            used[t.text] = used.get(t.text, 0) + 1

    return {
        "file": tex_path,
        "macros_defined": len(defs),
        "patterns": len(patterns),
        "hard": _as_rows(hard, used),
        "soft": _as_rows(soft, used),
        "_found": found,
        "_hay": hay,
        "_original": original,
        "_used": used,
    }


# --------------------------------------------------------------------------- #
# --fix: rewrite raw forms through the same matcher that found them
# --------------------------------------------------------------------------- #
def strip_outer_braces(s):
    """'{a+b}' -> 'a+b', but leave '{a}+{b}' alone (its braces do not pair)."""
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return s
    depth = 0
    for i, c in enumerate(s):
        if c == "\\":
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[1:-1] if i == len(s) - 1 else s
    return s


def pick_alias(pat, used):
    """Which alias to write when several macros share one body: the one in use."""
    return sorted(pat.macros, key=lambda m: (-used.get(m, 0), len(m), m))[0]


def build_replacement(pat, hay, start, end, arg_spans, text, used):
    repl = pick_alias(pat, used)
    for a, b in arg_spans:
        inner = text[hay[a].start:hay[b - 1].end] if b > a else ""
        repl += "{" + strip_outer_braces(inner) + "}"
    return repl


def fix_text(text, hay, found, used):
    r"""Apply one pass of non-overlapping replacements, right to left.

    Findings nested inside another finding's argument are left for the next pass:
    splicing an outer span would otherwise reinstate the argument's original bytes
    and silently undo the inner fix.
    """
    spans = []
    taken = []
    for pat, start, end, arg_spans in sorted(found, key=lambda f: f[1]):
        if pat.soft:
            continue
        lo, hi = hay[start].start, hay[end - 1].end
        if any(lo < b and a < hi for a, b in taken):
            continue                                   # overlaps a chosen span
        taken.append((lo, hi))
        spans.append((lo, hi, build_replacement(pat, hay, start, end, arg_spans, text, used)))
    out = text
    for lo, hi, repl in sorted(spans, reverse=True):
        tail = out[hi:hi + 1]
        if repl[-1:].isalpha() and tail.isalpha():
            repl += " "                                # \rh + X must not become \rhX
        out = out[:lo] + repl + out[hi:]
    return out, len(spans)


def fix_file(tex_path, cfg, strict, preamble_override, max_passes=8):
    """Rewrite raw forms in place. -> (replacements, remaining hard findings) or None."""
    total = 0
    for _ in range(max_passes):
        res = check_file(tex_path, cfg, strict, preamble_override)
        if res is None:
            return None
        new_text, n = fix_text(res["_original"], res["_hay"], res["_found"], res["_used"])
        if not n or new_text == res["_original"]:
            break
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        total += n
    res = check_file(tex_path, cfg, strict, preamble_override)
    return total, sum(r["count"] for r in res["hard"]), res


def _apply_extra(rule, body_lines, first_body_line, bucket):
    pat = re.compile(rule["pattern"])
    hits = [first_body_line + 1 + i for i, l in enumerate(body_lines) if pat.search(l)]
    if hits:
        key = rule.get("suggest", rule.get("label", rule["pattern"]))
        entry = bucket.setdefault(key, (None, []))
        bucket[key] = (entry[0], entry[1] + hits)
        bucket[key + "\0label"] = rule.get("label", rule["pattern"])


def _as_rows(bucket, used):
    rows = []
    for key, value in bucket.items():
        if key.endswith("\0label"):
            continue
        pat, hits = value
        label = pat.display if pat is not None else bucket.get(key + "\0label", key)
        row = {"raw": label, "use": key, "count": len(hits), "lines": sorted(hits)}
        if pat is not None:
            # How often the manuscript actually uses the alias it is being told to
            # use.  Zero means the preamble defines an alias the author never
            # writes, so the finding is usually a dead or semantic-only macro
            # rather than drift: decide once, then put it in ignore_macros.
            row["alias_use"] = {m: used.get(m, 0) for m in pat.macros}
        rows.append(row)
    rows.sort(key=lambda r: (-r["count"], r["raw"]))
    return rows


# --------------------------------------------------------------------------- #
# config / targets
# --------------------------------------------------------------------------- #
REPO_CONFIG = os.path.join(".claude", "preamble-aliases.json")


def find_repo_config(start):
    r"""Walk up from `start` looking for `.claude/preamble-aliases.json`.

    Its presence is how a repo opts in: the personal-layer pre-commit chain gates
    a repo exactly when this file exists, so adding the config *is* the wiring —
    no per-repo hook script, and no repo is gated by surprise.
    """
    d = os.path.abspath(start)
    while True:
        candidate = os.path.join(d, REPO_CONFIG)
        if os.path.isfile(candidate):
            return candidate
        if os.path.isdir(os.path.join(d, ".git")):
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load_config(explicit, target_hint=None):
    path = explicit
    if not path:
        start = target_hint or os.getcwd()
        path = find_repo_config(start if os.path.isdir(start) else os.path.dirname(start) or ".")
    if not path:
        here = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.join(here, "check-preamble-aliases.config.json")
        path = candidate if os.path.isfile(candidate) else None
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f), os.path.dirname(os.path.dirname(os.path.abspath(path))) \
                if os.path.basename(os.path.dirname(path)) == ".claude" \
                else os.path.dirname(os.path.abspath(path))
    return {}, os.getcwd()


def default_targets(cfg, cfg_dir):
    if cfg.get("targets"):
        return [os.path.join(cfg_dir, t) for t in cfg["targets"]]
    found = []
    for name in sorted(os.listdir(".")):
        if name.endswith(".tex"):
            try:
                with open(name, encoding="utf-8", errors="replace") as f:
                    if r"\begin{document}" in f.read():
                        found.append(name)
            except OSError:
                pass
    return found


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def print_rows(rows, mark):
    if not rows:
        print("  ✓ none")
        return
    for r in rows:
        note = ""
        if "alias_use" in r:
            counts = r["alias_use"]
            if not any(counts.values()):
                note = "   [alias never used in this body — dead or semantic-only?]"
            else:
                note = "   [" + ", ".join(f"{m} {n}×" for m, n in counts.items()) + "]"
        print(f'  {mark} {r["count"]:>3}× raw "{r["raw"]}" → use {r["use"]}{note}')
        shown = r["lines"][:MAX_LINES_SHOWN]
        extra = "" if len(r["lines"]) <= MAX_LINES_SHOWN else f', ... +{len(r["lines"]) - MAX_LINES_SHOWN} more'
        print(f'      L{", L".join(str(x) for x in shown)}{extra}')


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__.splitlines()[0])
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--preamble", help="derive the vocabulary from this file instead")
    ap.add_argument("--config", help="JSON config (default: next to this script)")
    ap.add_argument("--strict", action="store_true", help="exploratory: also unanchored / alias-of-alias")
    ap.add_argument("--list", action="store_true", help="print the derived patterns and stop")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix", action="store_true",
                    help="rewrite the raw forms in place (derived findings only)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    cfg, cfg_dir = load_config(args.config, args.targets[0] if args.targets else None)
    targets = args.targets or default_targets(cfg, cfg_dir)
    preamble = args.preamble or (os.path.join(cfg_dir, cfg["preamble"]) if cfg.get("preamble") else None)
    if not targets:
        print("ERROR: no .tex target given and none found", file=sys.stderr)
        return 2

    if args.fix:
        rc = 0
        for t in targets:
            if not os.path.isfile(t):
                print(f"ERROR: {t}: not found", file=sys.stderr)
                rc = 2
                continue
            got = fix_file(t, cfg, args.strict, preamble)
            if got is None:
                print(rf"ERROR: {t}: \begin{{document}} not found (use --preamble)", file=sys.stderr)
                rc = 2
                continue
            applied, remaining, res = got
            print(f"{t}: {applied} replacement(s) written, {remaining} hard finding(s) left")
            if remaining:
                print_rows(res["hard"], "❌")
        print("\n⚠️ --fix is a source rewrite: read the diff and rebuild the PDF before committing.")
        return rc

    if args.list:
        for t in targets:
            lines, body_start, _ = prepare(t)
            text = "\n".join(lines[:body_start]) if body_start is not None else "\n".join(lines)
            if preamble:
                pl, _, _ = prepare(preamble)
                text = "\n".join(pl)
            defs = parse_definitions(text)
            pats = derive_patterns(defs, set(cfg.get("ignore_macros", [])),
                                   set(cfg.get("soft_macros", [])), args.strict)
            print(f"{t}: {len(defs)} definitions -> {len(pats)} patterns")
            for p in pats:
                print(f'  {p.suggest:<24} ← "{p.display}"')
        return 0

    results, unreadable = [], []
    for t in targets:
        if not os.path.isfile(t):
            unreadable.append(f"{t}: not found")
            continue
        res = check_file(t, cfg, args.strict, preamble)
        if res is None:
            unreadable.append(rf"{t}: \begin{{document}} not found (use --preamble)")
            continue
        results.append(res)

    hard_total = sum(sum(r["count"] for r in x["hard"]) for x in results)
    soft_total = sum(sum(r["count"] for r in x["soft"]) for x in results)

    results = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    if args.json:
        print(json.dumps({"results": results, "errors": unreadable,
                          "hard_total": hard_total, "soft_total": soft_total}, indent=2))
    else:
        for i, res in enumerate(results):
            if i:
                print("\n" + "=" * 70)
            print(f'\nChecking {res["file"]} '
                  f'({res["macros_defined"]} preamble definitions → {res["patterns"]} patterns)\n')
            print("=== Hard violations (preamble defines an alias for this raw form) ===")
            print_rows(res["hard"], "❌")
            print("\n=== Soft warnings (config-declared: review, may be intentional) ===")
            print_rows(res["soft"], "⚠️ ")
        print("\n" + "-" * 70)
        for e in unreadable:
            print(f"❌ ERROR: {e}")
        if not unreadable and hard_total == 0 and soft_total == 0:
            print("✓ PASS: no raw form found for which the preamble defines an alias.")
        elif not unreadable and hard_total == 0:
            print(f"⚠ SOFT-WARN: {soft_total} soft warning(s).")
        elif hard_total:
            print(f"❌ FAIL: {hard_total} hard violation(s) + {soft_total} soft warning(s).")
            print("\nSee conventions/latex.md#macro-alias-forcing-function")

    if unreadable:
        return 2
    return 1 if hard_total else 0


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
PREAMBLE = r"""
\documentclass{article}
\newcommand{\h}{\hat}
\newcommand{\tx}{\text}
\newcommand{\wh}[1]{\widehat{#1}}
\newcommand{\rh}{\hat\rho}
\newcommand{\rhS}{\hat\rho_\S}
\newcommand{\Ih}{\hat I}
\newcommand{\cond}{{\Ih}}
\newcommand{\pn}[1]{\left(#1\right)}
\newcommand{\paren}[1]{\left(#1\right)}
\newcommand{\opa}[1]{{#1}^{}}
\newcommand{\swap}[2]{#2#1}
\newcommand{\TD}{T_\tx{D}}
\DeclareMathOperator{\Tr}{Tr}
\newcommand{\etal}{et al.}
%\newcommand{\ghost}{\mathbb{G}}
"""


def _run(body, extra_pre="", **kw):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.tex")
        with open(p, "w", encoding="utf-8") as f:
            f.write(PREAMBLE + extra_pre + "\\begin{document}\n" + body + "\n\\end{document}\n")
        res = check_file(p, kw.get("cfg", {}), kw.get("strict", False), None)
    return {r["use"]: r["count"] for r in res["hard"]}, {r["use"]: r["count"] for r in res["soft"]}


def selftest():
    fails = []

    def want(body, expected, note, **kw):
        hard, _soft = _run(body, **kw)
        if hard != expected:
            fails.append(f"{note}: got {hard}, want {expected}")

    # --- positives -------------------------------------------------------- #
    want(r"$\hat A$", {"\\h": 1}, "single undefined cs body is a raw form")
    want(r"$\hat \rho$ and $\hat{\rho}$ and $\hat\rho$", {"\\rh": 3},
         "space and brace variants collapse onto one pattern")
    want(r"$\widehat{X}$", {"\\wh": 1}, "argument macro")
    want(r"$\widehat{A+B}$", {"\\wh": 1}, "argument macro over a multi-token argument")
    want(r"$\left( a+b \right)$", {"\\paren / \\pn": 1},
         "macros sharing a body are reported together")
    want(r"$T_\tx{D}$", {"\\TD": 1}, "compound built from legitimate atoms")
    want(r"$T_\text{D}$", {"\\TD": 1},
         "compound reported once at full length, not as its \\tx part")

    # --- overlap: longest wins -------------------------------------------- #
    want(r"$\hat\rho_\S$", {"\\rhS": 1}, "compound bypass beats the atom pattern")
    want("{\\color{Orange}first $\\hat A$\n\npara two $\\widehat{B}$}",
         {"\\orange": 1, "\\h": 1, "\\wh": 1},
         "a wrapper's argument does not hide the raw forms inside it",
         extra_pre="\\newcommand{\\orange}[1]{{\\color{Orange}#1}}\n")

    # --- negatives (false-positive fixtures) ------------------------------ #
    want(r"The \Tr of a matrix. Trace, Trotter, contribution.", {},
         "plain-text body (\\DeclareMathOperator) never fires")
    want(r"Smith \etal\ showed that et al. is prose.", {},
         "prose macro body never fires")
    want(r"$\Ih$ and $\cond$", {}, "alias of an alias is not a raw form")
    want(r"$\hatwhole{X}$", {}, "a control word matches whole, not as a prefix")
    want(r"$ST_\text{D}$", {"\\tx": 1},
         "letter runs match whole: \\TD does not fire inside ST_, only its \\tx part")
    want("% a comment with $\\hat\\rho$ in it", {}, "comments are stripped")
    want("\\begin{verbatim}\n\\hat\\rho\n\\end{verbatim}", {}, "verbatim is skipped")
    want(r"\newcommand{\later}{\hat\rho}", {}, "definition lines in the body are exempt")
    want(r"$x^{}$ and $y^{}$", {}, "unanchored pattern (\\opa) is off by default")
    want(r"$ba$", {}, "placeholder reuse/reorder (\\swap) is not matched")
    want(r"$\pn{a+b}$ $\wh{X}$ $\rhS$ $\TD$", {}, "correct alias use is clean")
    want(r"$\mathbb{G}$", {}, "commented-out definitions do not create patterns")

    # --- config ----------------------------------------------------------- #
    want(r"$\hat A$", {}, "ignore_macros suppresses a pattern",
         cfg={"ignore_macros": ["\\h"]})
    hard, soft = _run(r"$\hat A$", cfg={"soft_macros": ["\\h"]})
    if hard or soft.get("\\h") != 1:
        fails.append(f"soft_macros: hard={hard} soft={soft}")
    hard, _ = _run(r"$\Tr\sqbr{X}$",
                   cfg={"extra_hard": [{"pattern": r"\\Tr\\sqbr\{", "label": r"\Tr\sqbr{",
                                        "suggest": r"\Tr\fnl{"}]})
    if hard.get(r"\Tr\fnl{") != 1:
        fails.append(f"extra_hard rule: {hard}")

    # --- strict ----------------------------------------------------------- #
    hard, _ = _run(r"$\Ih$", strict=True)
    if hard.get("\\cond") != 1:
        fails.append(f"--strict should surface alias-of-alias: {hard}")

    # --- repo config discovery (= the opt-in switch) ------------------------ #
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".git"))
        os.makedirs(os.path.join(d, ".claude"))
        os.makedirs(os.path.join(d, "src"))
        with open(os.path.join(d, ".claude", "preamble-aliases.json"), "w", encoding="utf-8") as f:
            json.dump({"ignore_macros": ["\\para"], "targets": ["src/main.tex"]}, f)
        tex = os.path.join(d, "src", "main.tex")
        with open(tex, "w", encoding="utf-8") as f:
            f.write(PREAMBLE + "\\begin{document}\n$\\hat A$\n\\end{document}\n")
        cfg, cfg_dir = load_config(None, tex)
        if cfg.get("ignore_macros") != ["\\para"]:
            fails.append(f"repo config not discovered from a target path: {cfg}")
        if os.path.realpath(cfg_dir) != os.path.realpath(d):
            fails.append("repo config dir should be the repo root, not .claude/")
        if [os.path.relpath(p, d) for p in default_targets(cfg, cfg_dir)] != ["src/main.tex"]:
            fails.append("config targets should resolve against the repo root")
        os.makedirs(os.path.join(d, "sub", ".git"))
        if find_repo_config(os.path.join(d, "sub")) is not None:
            fails.append("discovery must stop at a .git boundary, not leak from a parent repo")

    # --- --fix -------------------------------------------------------------- #
    def want_fix(body, expected, note, **kw):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.tex")
            head = PREAMBLE + kw.pop("extra_pre", "") + "\\begin{document}\n"
            with open(p, "w", encoding="utf-8") as f:
                f.write(head + body + "\n\\end{document}\n")
            got = fix_file(p, kw.get("cfg", {}), False, None)
            with open(p, encoding="utf-8") as f:
                out = f.read()
            got_body = out[len(head):].rsplit("\\end{document}", 1)[0].rstrip("\n")
        if got_body != expected:
            fails.append(f"--fix {note}: got {got_body!r}, want {expected!r}")
        elif got[1]:
            fails.append(f"--fix {note}: {got[1]} finding(s) left")

    want_fix(r"$\hat \rho$ and $\hat{\rho}$", r"$\rh$ and $\rh$", "space and brace variants")
    want_fix(r"$\widehat{A+B}$", r"$\wh{A+B}$", "argument is carried over")
    want_fix(r"$\widehat{X}$", r"$\wh{X}$", "single-token argument keeps its braces")
    want_fix(r"$\left( a+b \right)$", r"$\pn{a+b}$",
             "of two macros sharing a body, the one in use is written")
    want_fix(r"$\hat\rho_\S$", r"$\rhS$", "the compound, not the atom")
    want_fix(r"$\hat{A}B$", r"$\Ah B$", "a space is inserted so \\Ah B does not become \\AhB",
             extra_pre="\\newcommand{\\Ah}{\\hat A}\n")
    want_fix("{\\color{Orange}x $\\hat A$}", r"\orange{x $\h A$}",
             "a nested finding inside an argument survives the outer rewrite",
             extra_pre="\\newcommand{\\orange}[1]{{\\color{Orange}#1}}\n")
    want_fix("% keep $\\hat\\rho$ here\n$\\hat\\rho$", "% keep $\\hat\\rho$ here\n$\\rh$",
             "comments are not rewritten")

    # --- exit codes ------------------------------------------------------- #
    with tempfile.TemporaryDirectory() as d:
        clean = os.path.join(d, "clean.tex")
        dirty = os.path.join(d, "dirty.tex")
        with open(clean, "w", encoding="utf-8") as f:
            f.write(PREAMBLE + "\\begin{document}\n$\\rh$\n\\end{document}\n")
        with open(dirty, "w", encoding="utf-8") as f:
            f.write(PREAMBLE + "\\begin{document}\n$\\hat\\rho$\n\\end{document}\n")
        frag = os.path.join(d, "frag.tex")
        with open(frag, "w", encoding="utf-8") as f:
            f.write("$\\hat\\rho$\n")
        pre = os.path.join(d, "pre.tex")
        with open(pre, "w", encoding="utf-8") as f:
            f.write(PREAMBLE)
        import io
        import contextlib
        for argv, expected, note in (
            ([clean], 0, "clean file exits 0"),
            ([dirty], 1, "hard violation exits 1"),
            ([os.path.join(d, "missing.tex")], 2, "missing target exits 2"),
            ([frag], 2, "no \\begin{document} and no --preamble exits 2"),
            (["--preamble", pre, frag], 1, "--preamble derives from another file"),
            (["--json", dirty], 1, "--json keeps the exit code"),
            (["--list", dirty], 0, "--list exits 0"),
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(argv)
            if rc != expected:
                fails.append(f"{note}: rc={rc} want {expected}")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--json", dirty])
        payload = json.loads(buf.getvalue())
        if payload["hard_total"] != 1 or not payload["results"][0]["hard"][0]["lines"]:
            fails.append(f"--json payload: {payload}")

    if fails:
        print("check-preamble-aliases selftest: FAIL")
        for f in fails:
            print("  ✗ " + f)
        return 1
    print("check-preamble-aliases selftest: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
