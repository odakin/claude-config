#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Abbreviation hygiene for LaTeX manuscripts: each abbreviation is defined once, at the FIRST body
occurrence of its long form; it is not used before that; the long form does not return afterwards;
and an abbreviation ending in a period is not followed by a plain (inter-sentence) space.

Why (2026-09-11): two independent sweeps of one manuscript (the author's own pass and a
pre-submission gate run by another session) both reported "no abbreviation used before its
definition" while the introduction still spelled out three terms before their definitions in
later sections. They checked only the first criterion. The check needs both:
  (1) the abbreviation does not appear before its definition, and
  (2) the definition sits at the first body occurrence of the long form.
Convention and rationale: claude-config conventions/latex.md#abbreviation-first-occurrence.

Findings (body = after \\end{abstract}; the abstract is self-contained and skipped):
  D1  the same "(ABBR)" definition appears more than once in the body
  D2  ABBR is used before its definition
  D3  the long form occurs in the body before the definition (the definition is not at the first occurrence)
  D4  the long form recurs after the definition (sectioning titles and --allow phrases are exempt)
  S1  "et al." / "e.g." / "i.e." / "cf." / "vs." / "Ref." / "Eq." / "Fig." / "Sec." / "App." / "Tab."
      followed by a plain space before a word: LaTeX sets an inter-sentence space ("et al.\\ ", "Ref.~")
  U   (info only) capitalized tokens of two or more letters used in body prose with no definition
The long form is inferred from the words before "(ABBR)" whose initials spell ABBR (hyphens split
words, "of/and/the/for" may be skipped), or from a single word containing the letters in order
("ultraviolet (UV)"). Pass --long ABBR='long form' when inference fails (e.g. 1PI).

Usage:
  check-abbreviations.py paper.tex [--allow PHRASE]... [--long ABBR=LONG]... [--ignore TOK,TOK]
                         [--display-macro al,als] [--no-info]
  check-abbreviations.py --selftest
Exit 1 when any D1-D4 or S1 finding is reported (U never fails the run).
"""
import argparse
import re
import sys

STOP = {"of", "and", "the", "for", "in", "on", "to", "a", "an"}
DISPLAY_ENVS = ("equation", "align", "gather", "multline", "eqnarray", "displaymath", "alignat", "flalign")
REF_CMDS = ("label", "ref", "eqref", "cref", "Cref", "labelcref", "autoref", "cite", "citep", "citet",
            "citealp", "includegraphics", "url", "bibliography", "bibliographystyle", "input", "include")
SPACE_ABBR = r"(?:et al|e\.g|i\.e|cf|vs|resp|Refs?|Eqs?|Figs?|Secs?|Apps?|Tabs?)"
TITLE = re.compile(r"\\(?:part|chapter|(?:sub)*section|paragraph)\*?\s*[\[{]")


def _blank(s):
    return re.sub(r"[^\n]", " ", s)


def mask(tex, display_macros=()):
    """Blank comments, math and reference arguments, keeping newlines (line numbers survive)."""
    out = []
    for line in tex.split("\n"):
        if line.lstrip().startswith("%"):
            out.append("")
        else:
            out.append(re.sub(r"(?<!\\)%.*$", "", line))
    t = "\n".join(out)
    for env in DISPLAY_ENVS:
        t = re.sub(r"\\begin\{%s\*?\}.*?\\end\{%s\*?\}" % (env, env), lambda m: _blank(m.group(0)), t, flags=re.S)
    t = re.sub(r"\\\[.*?\\\]", lambda m: _blank(m.group(0)), t, flags=re.S)
    t = re.sub(r"\\\(.*?\\\)", lambda m: _blank(m.group(0)), t, flags=re.S)
    t = re.sub(r"(?<!\\)\$\$.*?(?<!\\)\$\$", lambda m: _blank(m.group(0)), t, flags=re.S)
    t = re.sub(r"(?<!\\)\$[^$]*?(?<!\\)\$", lambda m: _blank(m.group(0)), t, flags=re.S)
    for mac in display_macros:
        t = _blank_macro(t, mac)
    t = re.sub(r"\\(%s)\*?(\[[^\]]*\])*\{[^}]*\}" % "|".join(REF_CMDS), lambda m: _blank(m.group(0)), t)
    return t


def _blank_macro(t, mac):
    """Blank \\mac{...} with balanced braces (custom display wrappers such as \\al{...})."""
    res, i, pat = [], 0, re.compile(r"\\%s\s*\{" % re.escape(mac))
    while True:
        m = pat.search(t, i)
        if not m:
            res.append(t[i:])
            return "".join(res)
        res.append(t[i:m.start()])
        depth, j = 1, m.end()
        while j < len(t) and depth:
            if t[j] == "{" and t[j - 1] != "\\":
                depth += 1
            elif t[j] == "}" and t[j - 1] != "\\":
                depth -= 1
            j += 1
        res.append(_blank(t[m.start():j]))
        i = j


def infer_long(before, abbr):
    letters = [c.lower() for c in abbr if c.isalpha()]
    if not letters or any(c.isdigit() for c in abbr):
        return None
    words = re.findall(r"[A-Za-z]+(?:-+[A-Za-z]+)*", before)
    parts = []                                       # (word_index, part)
    for wi, w in enumerate(words):
        for p in re.split(r"-+", w):
            parts.append((wi, p))
    k, j, first_wi = len(letters) - 1, len(parts) - 1, None
    while k >= 0 and j >= 0:
        wi, p = parts[j]
        if p[0].lower() == letters[k]:
            first_wi, k = wi, k - 1
        elif p.lower() in STOP and first_wi is not None:
            pass
        else:
            break
        j -= 1
    if k < 0 and first_wi is not None:
        return " ".join(words[first_wi:])
    if words:                                        # one word holding the letters in order: "ultraviolet (UV)"
        w = words[-1]
        if w[0].lower() == letters[0]:
            pos = 0
            for c in letters:
                pos = w.lower().find(c, pos)
                if pos < 0:
                    return None
                pos += 1
            return w
    return None


def long_regex(long_form):
    parts = [re.escape(p) for p in re.split(r"[-\s]+", long_form.strip()) if p]
    return re.compile(r"(?<![A-Za-z])" + r"[-\s~]+".join(parts) + r"(?![A-Za-z])", re.I)


def line_of(t, pos):
    return t.count("\n", 0, pos) + 1


def check(tex, allow=(), longs=None, ignore=(), display_macros=(), info=True):
    longs = dict(longs or {})
    t = mask(tex, display_macros)
    m_end = re.search(r"\\end\{abstract\}", t)
    b0 = m_end.end() if m_end else (re.search(r"\\begin\{document\}", t).end() if re.search(r"\\begin\{document\}", t) else 0)
    m_bib = re.search(r"\\begin\{thebibliography\}|\\bibliography\s*\{", t[b0:])
    b1 = b0 + m_bib.start() if m_bib else len(t)
    body = t[:b1]
    title_spans = []
    for m in TITLE.finditer(body, b0):
        depth, j = 1, m.end()
        while j < len(body) and depth:
            depth += {"{": 1, "}": -1}.get(body[j], 0) if body[j] in "{}" else 0
            j += 1
        title_spans.append((m.start(), j))
    allow_spans = []
    for a in allow:
        for m in long_regex(a).finditer(body, b0):
            allow_spans.append((m.start(), m.end()))

    def exempt(s, e):
        return any(a <= s < b for a, b in title_spans) or any(not (e <= a or s >= b) for a, b in allow_spans)

    findings, infos = [], []
    defs = {}
    for m in re.finditer(r"\(([A-Z0-9][A-Za-z0-9]*[A-Z0-9])\)", body[b0:]):
        abbr = m.group(1)
        if sum(c.isupper() or c.isdigit() for c in abbr) < 2 or abbr.isdigit():
            continue
        pos = b0 + m.start()
        defs.setdefault(abbr, []).append(pos)
    for abbr, poss in sorted(defs.items(), key=lambda kv: kv[1][0]):
        d = poss[0]
        if len(poss) > 1:
            findings.append((line_of(t, poss[1]), "D1", abbr, "defined again (first definition at L%d)" % line_of(t, d)))
        use = re.compile(r"(?<![A-Za-z0-9\\{(])%s(?![A-Za-z])" % re.escape(abbr))
        for m in use.finditer(body, b0, d):
            findings.append((line_of(t, m.start()), "D2", abbr, "used before its definition at L%d" % line_of(t, d)))
            break
        lf = longs.get(abbr) or infer_long(body[max(b0, d - 200):d], abbr)
        if not lf:
            infos.append((line_of(t, d), "U", abbr, "long form not inferred; pass --long %s='...' to check D3/D4" % abbr))
            continue
        rx = long_regex(lf)
        def_long = None
        for m in rx.finditer(body, b0, d + 1):
            if body[m.end():d].strip() == "":
                def_long = m
        for m in rx.finditer(body, b0):
            if def_long and m.start() == def_long.start():
                continue
            if exempt(m.start(), m.end()):
                continue
            where = "before" if m.start() < d else "after"
            code = "D3" if where == "before" else "D4"
            findings.append((line_of(t, m.start()), code, abbr,
                             "long form '%s' %s the definition at L%d" % (lf, where, line_of(t, d))))
    for m in re.finditer(r"\b%s\.(?=[ \t]+[A-Za-z\\(\[])" % SPACE_ABBR, body[b0:]):
        pos = b0 + m.start()
        findings.append((line_of(t, pos), "S1", m.group(0), "plain space after the period sets an inter-sentence space; use '\\ ' or '~'"))
    if info:
        seen = set(defs) | set(ignore)
        for m in re.finditer(r"(?<![A-Za-z0-9\\{(])([A-Z][A-Z0-9]+)(?![A-Za-z])", body[b0:]):
            tok = m.group(1)
            if tok in seen or any(ch.isdigit() for ch in tok):   # identifiers such as grant numbers
                continue
            seen.add(tok)
            infos.append((line_of(t, b0 + m.start()), "U", tok, "capitalized token with no definition in the body"))
    return sorted(findings), sorted(infos)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tex", nargs="?")
    ap.add_argument("--allow", action="append", default=[], help="fixed-name phrase exempt from D3/D4 (repeatable)")
    ap.add_argument("--long", action="append", default=[], help="ABBR=long form, when inference fails (repeatable)")
    ap.add_argument("--ignore", default="", help="comma-separated tokens to leave out of the info list")
    ap.add_argument("--display-macro", default="", help="comma-separated custom display wrappers, e.g. al,als")
    ap.add_argument("--no-info", action="store_true", help="suppress the informational U list")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv[1:])
    if a.selftest:
        return selftest()
    if not a.tex:
        ap.error("tex file required")
    tex = open(a.tex, encoding="utf-8").read()
    longs = dict(x.split("=", 1) for x in a.long)
    macros = [m for m in a.display_macro.split(",") if m]
    ignore = [x for x in a.ignore.split(",") if x]
    findings, infos = check(tex, a.allow, longs, ignore, macros, info=not a.no_info)
    for ln, code, what, msg in findings:
        print("%s:%d: [%s] %s: %s" % (a.tex, ln, code, what, msg))
    for ln, code, what, msg in infos:
        print("%s:%d: [%s info] %s: %s" % (a.tex, ln, code, what, msg))
    print("%d finding(s), %d info" % (len(findings), len(infos)))
    return 1 if findings else 0


def selftest():
    bad = r"""\begin{document}
\begin{abstract} The general-coordinate (GC) symmetry and the Nambu--Goldstone mode. \end{abstract}
\section{Introduction}
We study general-coordinate invariance of the hidden-local-Lorentz scenario.
The general-coordinate (GC) transformation acts on $x^{GC}$.
Later the general coordinate identity holds.
Smith et al. derived it, see Ref. \cite{x} and Ref.~\cite{y}.
The NG mode appears first here.
The Nambu--Goldstone (NG) field is the mode.
The local Lorentz (LL) group and the ultraviolet (UV) cutoff, and the one-particle-irreducible (1PI) function.
The Natural Sciences and Engineering Research Council (NSERC) and the functional renormalization group (FRG).
\section{The general-coordinate transformation}
\al{ GC + LL \text{Nambu--Goldstone} }
% The general-coordinate identity in a comment is ignored.
\end{document}
"""
    f, i = check(bad, allow=["hidden-local-Lorentz"], longs={"1PI": "one-particle-irreducible"}, display_macros=["al"])
    got = sorted((c, w) for _, c, w, _ in f)
    exp = sorted([("D3", "GC"), ("D4", "GC"), ("S1", "et al."), ("S1", "Ref."), ("D2", "NG")])
    assert got == exp, (got, exp)
    assert infer_long("the Natural Sciences and Engineering Research Council", "NSERC") == "Natural Sciences and Engineering Research Council"
    assert infer_long("the National Natural Science Foundation of China", "NSFC") == "Natural Science Foundation of China"  # letters spell 4 of 5 words; the span still catches the full name
    assert infer_long("the functional renormalization group", "FRG") == "functional renormalization group"
    assert infer_long("the would-be Nambu--Goldstone", "NG") == "Nambu--Goldstone"
    assert infer_long("an ultraviolet", "UV") == "ultraviolet"
    assert infer_long("the local Lorentz", "LL") == "local Lorentz"
    assert infer_long("the Lie-derivative", "LD") == "Lie-derivative"
    assert infer_long("the one-particle-irreducible", "1PI") is None
    good = bad.replace("We study general-coordinate invariance", "We study GC invariance")
    good = good.replace("Later the general coordinate identity holds.", "Later the GC identity holds.")
    good = good.replace("Smith et al. derived it, see Ref. \\cite{x}", "Smith et al.\\ derived it, see Ref.~\\cite{x}")
    good = good.replace("The general-coordinate (GC) symmetry and", "The GC symmetry and")
    good = good.replace("We study GC invariance", "We study general-coordinate (GC) invariance").replace(
        "The general-coordinate (GC) transformation acts", "The GC transformation acts")
    good = good.replace("The NG mode appears first here.\n", "")
    f2, _ = check(good, allow=["hidden-local-Lorentz"], longs={"1PI": "one-particle-irreducible"}, display_macros=["al"])
    assert f2 == [], f2
    f3, _ = check(bad, allow=[], longs={"1PI": "one-particle-irreducible"}, display_macros=["al"])
    assert ("D3", "LL") in [(c, w) for _, c, w, _ in f3], f3
    print("selftest OK (D1-D4, S1, long-form inference, allow list, comment and math masking)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
