#!/usr/bin/env python3
"""Prose gates for LaTeX manuscripts: appendix order by first main-text reference, italic section leads, sentence length, position words, strong-word inventory.

Why (2026-09).  Pre-submission gates kept re-running four prose sweeps with throw-away scripts
written against one manuscript (a hard-coded line range for the roadmap paragraph, one display
wrapper, an appendix label accepted only within two lines of its \\section), so every re-gate of
a new revision started from scratch and the sweeps could drift between runs.  The rules are
claude-config conventions/paper-audit.md #appendix-order-by-first-reference,
#sentence-length-audit, #relocation-rebinding-sweep and #claim-strength-three-tests; this script
is their mechanical part.  Reading the sentences stays with the human: only the appendix order
and an italic section lead are findings by themselves.  The italic-lead gate (I1) is the
mechanical part of conventions/writing-discipline.md #no-italic-section-lead: an italic summary
sentence at the head of a section, once written, is copied to the other sections, and a review
that reads it for content passes it (measured), so the head of every heading is checked.

Source handling (line numbers are kept): comments are dropped, and a comment-only line does not
break a paragraph; math (inline, display environments, \\[...\\], $$...$$, and --display-macro
wrappers such as \\al{...}) counts as one word, shown as "0" in snippets; a reference command
(\\cref{...}, \\cite{...}) counts as one word; \\label and other non-printing arguments count as
none; a footnote is counted as its own text, not as part of the sentence that carries it.
Includes are not followed.  The body starts after \\end{abstract} (or \\begin{document}) and ends
at the bibliography or \\end{document}.

Findings (exit 1):
  A1  the appendices (\\section after \\appendix; an "Acknowledgments" section and an empty,
      label-less heading such as \\section*{Appendix} are skipped) are not in the order in which
      the main text (before \\appendix, roadmap paragraph excluded) first references them.  A
      reference to any label defined inside an appendix (an equation, a subsection) counts as a
      reference to that appendix.
  A2  an appendix that the main text never references outside the roadmap paragraph
      (--allow-unreferenced LABEL exempts one, e.g. an appendix that is genuinely an outlook).
  A3  the roadmap paragraph names the appendices in an order different from the file order.
  I1  a \\part / \\chapter / \\section / \\subsection / \\subsubsection (starred or not, appendices
      included) whose first printed material is italic text of --lead-min-words words or more
      (default 5; math counts as one word): \\emph{...}, \\textit{...}, \\textsl{...}, a group
      {\\itshape ...} / {\\em ...} / {\\it ...} / {\\slshape ...} / {\\sl ...}, a bare \\itshape
      or \\begin{itshape} up to the end of the paragraph, or a one-argument macro that the
      preamble defines as one of these (\\newcommand{\\lead}[1]{\\textit{#1}}; --italic-macro
      names more).  Blank lines, comments, \\label, \\noindent and vertical spacing between the
      heading and the text are skipped; \\paragraph headings are not checked.  A shorter italic
      span that ends in "." or ":" is listed as info: it is a run-in label, which is the rule
      #no-run-in-labels, not this gate; one emphasized word (\\emph{Spin} is ...) is neither.
Review lists (printed for reading; with --strict, L and P items also fail the run; W never does):
  L   sentences longer than --max-words words (default 40), longest first.
  P   position words that a relocation silently rebinds: previous / next / following / preceding
      (sub)section / appendix / chapter / paragraph, above / below, the former / the latter,
      aforementioned, hereafter; display-line positions (the second / last line of Eq. N), which a
      re-broken display silently rebinds (name the term instead: "the two mass terms of Eq. N").
  W   strong-word inventory: counts for only, unique(ly), complete(ly), automatically, every,
      whole, exact(ly), all orders, never, always, first time, novel, universal(ly), guarantee(d/s);
      lines for the rarer ones.

The roadmap paragraph is the main-text paragraph matching --roadmap (default: "organized as
follows", "the rest / remainder of this paper", "this paper is organized / structured");
--roadmap-lines A-B names it explicitly.  The excluded lines are printed, so a wrong guess shows.
Only that paragraph is excluded: a reference from any other paragraph of the introduction (say, a
results summary that points to an appendix) counts, because the rule excludes the roadmap, not
the introduction.  Excluding more is an author's reading, so it is explicit, never a default:
--exclude-section REGEX drops whole sections from the first-reference count (e.g. an
introduction whose results summary points to appendices, when the author treats it like the
roadmap), and the excluded line ranges are printed.

Usage:
  check-paper-prose.py paper.tex [--display-macro al,als] [--max-words 40] [--only A,I,L,P,W]
                       [--roadmap REGEX]... [--roadmap-lines A-B] [--exclude-section REGEX]...
                       [--allow-unreferenced LABEL]... [--italic-macro lead,summary]
                       [--lead-min-words 5] [--strict]
  check-paper-prose.py --selftest
Exit 0 = no finding, 1 = findings, 2 = input error.
"""
import argparse
import bisect
import collections
import os
import re
import subprocess
import sys
import tempfile

DISPLAY_ENVS = ("equation", "align", "gather", "multline", "eqnarray", "displaymath", "alignat",
                "flalign", "dmath")
TOKEN_CMDS = ("ref", "eqref", "cref", "Cref", "labelcref", "autoref", "nameref", "pageref", "vref",
              "cite", "citep", "citet", "citealp", "Cite")
BLANK_CMDS = ("label", "includegraphics", "url", "bibliography", "bibliographystyle", "input",
              "include", "begin", "end", "vspace", "hspace")
SECTION = re.compile(r"\\(?:part|chapter|(?:sub)*section|paragraph)\*?\s*(?:\[[^\]]*\])?\{")
SEC_RE = re.compile(r"\\section\*?\s*(?:\[[^\]]*\])?\{")
REF_RE = re.compile(r"\\[A-Za-z]*ref\*?\s*\{([^}]*)\}")
LABEL_RE = re.compile(r"\\label\s*\{([^}]*)\}")
ENV_LINE = re.compile(r"\\(begin|end)\{([A-Za-z]+)\*?\}")
ROADMAP_DEFAULT = (r"(?i)organi[sz]ed as follows",
                   r"(?i)the (?:rest|remainder) of (?:this|the) (?:paper|article)",
                   r"(?i)(?:this|the) (?:paper|article) is (?:organi[sz]ed|structured)")
POSITION = re.compile(r"(?i)\b(?:previous|next|following|preceding|foregoing)\s+(?:sub)?"
                      r"(?:sections?|appendix|appendices|chapters?|paragraphs?)\b"
                      r"|\b(?:above|below|hereafter|aforementioned)\b|\bthe\s+(?:former|latter)\b"
                      r"|\b(?:first|second|third|fourth|fifth|last|upper|lower|top|bottom)\s+lines?\s+of\b"
                      r"|\b(?:in|on)\s+the\s+(?:first|second|third|fourth|fifth|last|upper|lower|top|bottom)\s+lines?\b")
STRONG = re.compile(r"(?i)\b(only|unique(?:ly)?|complete(?:ly)?|automatically|every|whole|exact(?:ly)?|"
                    r"all orders|never|always|first time|novel|universal(?:ly)?|guarantee[sd]?)\b")
STRONG_FREQUENT = {"only", "every", "exact", "exactly", "complete"}
SENT_END = re.compile(r"[.!?]['\")\]}]*(?=\s)")
ABBR_END = re.compile(r"(?:\bet al|\be\.g|\bi\.e|\bcf|\bvs|\bresp|\bRefs?|\bEqs?|\bFigs?|\bSecs?|"
                      r"\bSects?|\bApps?|\bTabs?|\bNo|\bVol|\bpp?|\bch|\bDr|\bProf|\bSt|"
                      r"(?<![A-Za-z])[A-Z])\.$")
TAIL = re.compile(r"(?:\\end\{[^}]*\}|\\\]|\$\$|\}|\\label\{[^}]*\}|\\nonumber|\\notag|\\\\|"
                  r"\\[,;:!]|\s)+$")
LEAD_HEAD = re.compile(r"\\(?:part|chapter|(?:sub)*section)\*?\s*(?:\[[^\]]*\])?\{")
ITALIC_CMDS = ("emph", "textit", "textsl")
ITALIC_DECLS = ("itshape", "em", "it", "slshape", "sl")
LEAD_SKIP = re.compile(r"\s+|\\label\s*\{[^}]*\}|\\noindent(?![A-Za-z])|\\(?:small|med|big)skip(?![A-Za-z])|"
                       r"\\[vh]space\*?\s*\{[^}]*\}|\\phantomsection(?![A-Za-z])")
_IT_BODY = (r"(?:\\(?:%s)\s*\{\s*#1\s*\}|\{\s*\\(?:%s)(?![A-Za-z])\s*#1\s*\})"
            % ("|".join(ITALIC_CMDS), "|".join(ITALIC_DECLS)))
WRAPPER_DEF = re.compile(r"\\(?:(?:(?:re)?new|provide)command|DeclareRobustCommand)\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?"
                         r"\s*\[1\]\s*\{\s*" + _IT_BODY
                         + r"|\\(?:New|Renew|Provide)DocumentCommand\s*\{?\s*\\([A-Za-z@]+)\s*\}?\s*\{\s*m\s*\}\s*\{\s*"
                         + _IT_BODY + r"|\\def\s*\\([A-Za-z@]+)\s*#1\s*\{\s*" + _IT_BODY)


# --------------------------------------------------------------------------- masking
def strip_comments(tex):
    out = []
    for line in tex.split("\n"):
        out.append("" if line.lstrip().startswith("%") else re.sub(r"(?<!\\)%.*$", "", line))
    return "\n".join(out)


def _blank(s):
    return re.sub(r"[^\n]", " ", s)


def _token(s, period=False):
    """One word "0" (plus "." when the span ended a sentence); length and newlines are kept."""
    out = list(_blank(s))
    for i, ch in enumerate(out):
        if ch != "\n":
            out[i] = "0"
            if period and i + 1 < len(out) and out[i + 1] != "\n":
                out[i + 1] = "."
            break
    return "".join(out)


def _ends_sentence(span):
    return TAIL.sub("", span).endswith(".")


def _display(m):
    return _token(m.group(0), _ends_sentence(m.group(0)))


def _balanced_end(t, j):
    """Index just past the brace that closes the group opened right before position j."""
    depth = 1
    while j < len(t) and depth:
        if t[j] == "{" and t[j - 1] != "\\":
            depth += 1
        elif t[j] == "}" and t[j - 1] != "\\":
            depth -= 1
        j += 1
    return j


def _mask_macro(t, mac):
    res, i, pat = [], 0, re.compile(r"\\%s\s*\{" % re.escape(mac))
    while True:
        m = pat.search(t, i)
        if not m:
            res.append(t[i:])
            return "".join(res)
        res.append(t[i:m.start()])
        j = _balanced_end(t, m.end())
        span = t[m.start():j]
        res.append(_token(span, _ends_sentence(span)))
        i = j


def mask(c, display_macros=()):
    """Comment-stripped source -> prose of the same length, math and reference commands as one-word tokens."""
    t = c
    for env in DISPLAY_ENVS:
        t = re.sub(r"\\begin\{%s\*?\}.*?\\end\{%s\*?\}" % (env, env), _display, t, flags=re.S)
    t = re.sub(r"\\\[.*?\\\]", _display, t, flags=re.S)
    t = re.sub(r"(?<!\\)\$\$.*?(?<!\\)\$\$", _display, t, flags=re.S)
    for mac in display_macros:
        t = _mask_macro(t, mac)
    t = re.sub(r"\\\(.*?\\\)", lambda m: _token(m.group(0)), t, flags=re.S)
    t = re.sub(r"(?<!\\)\$[^$]*?(?<!\\)\$", lambda m: _token(m.group(0)), t, flags=re.S)
    t = re.sub(r"\\href\s*\{[^}]*\}", lambda m: _blank(m.group(0)), t)
    t = re.sub(r"\\(?:%s)\*?(?:\[[^\]]*\])*\{[^}]*\}" % "|".join(TOKEN_CMDS), lambda m: _token(m.group(0)), t)
    t = re.sub(r"\\(?:%s)\*?(?:\[[^\]]*\])*\{[^}]*\}" % "|".join(BLANK_CMDS), lambda m: _blank(m.group(0)), t)
    return t


def split_footnotes(t):
    """Blank \\footnote{...} out of `t` (length kept); return (text, [(start, end)] of the bodies)."""
    spans, out, i, pat = [], [], 0, re.compile(r"\\footnote\s*(?:\[[^\]]*\])?\{")
    while True:
        m = pat.search(t, i)
        if not m:
            out.append(t[i:])
            return "".join(out), spans
        out.append(t[i:m.start()])
        j = _balanced_end(t, m.end())
        spans.append((m.end(), j - 1))
        out.append(_blank(t[m.start():j]))
        i = j


def words(s):
    s = re.sub(r"\\[A-Za-z@]+\*?", " ", s)
    s = re.sub(r"[{}\[\]~]", " ", s)
    return [w for w in s.split() if re.search(r"[A-Za-z0-9]", w)]


def line_of(t, pos):
    return t.count("\n", 0, pos) + 1


# --------------------------------------------------------------------------- structure
def body_bounds(c):
    """(first body line, appendix line or None, last body line, start offset, end offset) of the
    comment-stripped text; lines are 1-based, the offsets cut mid-line when the abstract ends there."""
    m = re.search(r"\\end\{abstract\}", c) or re.search(r"\\begin\{document\}", c)
    start = m.end() if m else 0
    e = re.search(r"\\bibliography\{|\\begin\{thebibliography\}|\\printbibliography|\\end\{document\}", c[start:])
    end = start + e.start() if e else len(c)
    a = re.search(r"^[ \t]*\\appendix\b", c[start:end], re.M)
    app = line_of(c, start + a.start()) if a else None
    return line_of(c, start), app, line_of(c, end), start, end


def is_break(orig):
    s = orig.strip()
    if not s or SECTION.match(s) or s.startswith("\\item") or s.startswith("\\appendix"):
        return True
    m = ENV_LINE.match(s)
    return bool(m and m.group(2) not in DISPLAY_ENVS)


def paragraphs(orig_lines, masked_lines, lo, hi):
    """Lists of (line number, masked text); original blank lines, sectioning, \\item and
    non-math environment boundaries separate them (comment-only lines do not)."""
    cur = []
    for n in range(lo, hi + 1):
        o = orig_lines[n - 1]
        if is_break(o) and not o.lstrip().startswith("%"):
            if cur:
                yield cur
            cur = []
            if o.strip().startswith("\\item") and words(masked_lines[n - 1]):
                cur = [(n, masked_lines[n - 1])]
            continue
        cur.append((n, masked_lines[n - 1]))
    if cur:
        yield cur


def split_sentences(text):
    """[(offset, sentence)] for one joined paragraph."""
    out, begin = [], 0
    for m in SENT_END.finditer(text):
        p = m.start()
        if text[p] == "." and ABBR_END.search(text[max(0, p - 8):p + 1]):
            continue
        rest = text[m.end():].lstrip()
        if rest and not (rest[0].isupper() or rest[0].isdigit() or rest[0] in "\\("):
            continue
        out.append((begin, text[begin:m.end()]))
        begin = m.end()
    if text[begin:].strip():
        out.append((begin, text[begin:]))
    return out


def sentences(par):
    """[(line, n words, snippet)] for a paragraph from paragraphs()."""
    starts, parts, off = [], [], 0
    for _n, txt in par:
        starts.append(off)
        parts.append(txt)
        off += len(txt) + 1
    text = " ".join(parts)
    out = []
    for o, s in split_sentences(text):
        lead = len(s) - len(s.lstrip())
        ln = par[bisect.bisect_right(starts, o + lead) - 1][0]
        w = words(s)
        if w:
            out.append((ln, len(w), " ".join(s.split())))
    return out


def line_offsets(c):
    return [0] + [m.end() for m in re.finditer("\n", c)]


# --------------------------------------------------------------------------- checks
def appendices(c, a_off, end_off):
    """[{line, title, labels}] for the \\section blocks between a_off and end_off."""
    heads = []
    for m in SEC_RE.finditer(c, a_off, end_off):
        j = _balanced_end(c, m.end())
        heads.append((m.start(), j, " ".join(c[m.end():j - 1].split())))
    out = []
    for i, (s0, t_end, title) in enumerate(heads):
        s1 = heads[i + 1][0] if i + 1 < len(heads) else end_off
        labels = [x.strip() for x in LABEL_RE.findall(c, s0, s1)]
        if re.search(r"(?i)acknowledg", title):
            continue
        if not labels and not c[t_end:s1].strip():
            continue  # an empty heading such as \section*{Appendix}
        out.append({"line": line_of(c, s0), "title": title, "labels": labels, "first": None, "via": None})
    return out


def italic_wrappers(preamble):
    """One-argument macros that the preamble defines as italic text (\\newcommand{\\lead}[1]{\\textit{#1}})."""
    return sorted({next(g for g in m.groups() if g) for m in WRAPPER_DEF.finditer(preamble)})


def italic_leads(c, masked, start, wrappers=()):
    """[(line, n words, heading, snippet, span ends a sentence)] for the headings after offset `start`
    whose first printed material is italic text; `masked` is mask(c) (same length)."""
    cmd = re.compile(r"\\(?:%s)\s*\{" % "|".join(re.escape(w) for w in ITALIC_CMDS + tuple(wrappers)))
    group = re.compile(r"\{\s*\\(?:%s)(?![A-Za-z])" % "|".join(ITALIC_DECLS))
    bare = re.compile(r"\\(?:itshape|slshape)(?![A-Za-z])|\\begin\{(?:itshape|em)\}")
    out = []
    for m in LEAD_HEAD.finditer(c, start):
        j = _balanced_end(c, m.end())
        head = c[m.start():j].split("{", 1)[0].lstrip("\\") + " " + repr(" ".join(c[m.end():j - 1].split()))
        while True:
            s = LEAD_SKIP.match(c, j)
            if not s:
                break
            j = s.end()
        mo = cmd.match(c, j)
        if mo:
            k = _balanced_end(c, mo.end())
            body = c[mo.end():k - 1], masked[mo.end():k - 1]
        elif group.match(c, j):
            k = _balanced_end(c, j + 1)
            body = c[j + 1:k - 1], masked[j + 1:k - 1]
        elif bare.match(c, j):
            b0 = bare.match(c, j).end()
            e = re.search(r"\n[ \t]*\n|\\end\{(?:itshape|em)\}", c[b0:])
            k = b0 + (e.start() if e else len(c) - b0)
            body = c[b0:k], masked[b0:k]
        else:
            continue
        ends = TAIL.sub("", body[0]).rstrip().endswith((".", ":"))
        out.append((line_of(c, j), len(words(body[1])), head, " ".join(c[j:k].split())[:110], ends))
    return out


def check(tex, display_macros=(), max_words=40, only="AILPW", roadmap=ROADMAP_DEFAULT, roadmap_lines=None,
          allow_unreferenced=(), strict=False, exclude_sections=(), italic_macros=(), lead_min_words=5):
    """Returns (findings, infos, review) with entries (line, code, message); review is a dict of lists."""
    c = strip_comments(tex)
    lo, app, hi, s_off, e_off = body_bounds(c)
    masked_all = mask(c, display_macros)
    masked = _blank(masked_all[:s_off]) + masked_all[s_off:e_off] + _blank(masked_all[e_off:])
    prose, notes = split_footnotes(masked)
    orig_lines, masked_lines, prose_lines = tex.split("\n"), masked.split("\n"), prose.split("\n")
    findings, infos = [], []
    review = {"L": [], "P": [], "W": []}
    main_hi = (app - 1) if app else hi

    road = set()
    if roadmap_lines:
        road = set(range(roadmap_lines[0], roadmap_lines[1] + 1))
    else:
        pats = [re.compile(p) for p in roadmap]
        for par in paragraphs(orig_lines, prose_lines, lo, main_hi):
            if any(p.search(" ".join(t for _, t in par)) for p in pats):
                road |= {n for n, _ in par}
    if road and "A" in only:
        infos.append((min(road), "roadmap", f"lines {min(road)}-{max(road)} are the roadmap paragraph "
                                            f"(excluded from first references)"))

    if "A" in only:
        if app is None:
            infos.append((lo, "A", "no \\appendix: appendix checks skipped"))
        else:
            offs = line_offsets(c)
            a_off = offs[app - 1]
            apps = appendices(c, a_off, e_off)
            owner = {lab: k for k, a in enumerate(apps) for lab in a["labels"]}
            excl = set()
            if exclude_sections:
                pats_x = [re.compile(p) for p in exclude_sections]
                heads = [(m.start(), " ".join(c[m.end():_balanced_end(c, m.end()) - 1].split()))
                         for m in SEC_RE.finditer(c, s_off, a_off)]
                for i, (h0, title) in enumerate(heads):
                    if any(p.search(title) for p in pats_x):
                        h1 = heads[i + 1][0] if i + 1 < len(heads) else a_off
                        x0, x1 = line_of(c, h0), line_of(c, h1) - 1
                        excl |= set(range(x0, x1 + 1))
                        infos.append((x0, "excluded", f"section {title!r} (lines {x0}-{x1}) is excluded from "
                                                      f"first references (--exclude-section)"))
            roadmap_seq = []
            for m in REF_RE.finditer(c, s_off, a_off):
                ln = line_of(c, m.start())
                for key in (x.strip() for x in m.group(1).split(",")):
                    k = owner.get(key)
                    if k is None:
                        continue
                    if ln in road:
                        if k not in roadmap_seq:
                            roadmap_seq.append(k)
                    elif ln not in excl and apps[k]["first"] is None:
                        apps[k]["first"], apps[k]["via"] = ln, key

            def name(k):
                lab = apps[k]["labels"][0] if apps[k]["labels"] else "no label"
                return f"{apps[k]['title']!r} <{lab}>"
            for k, a in enumerate(apps):
                if a["first"] is None:
                    if not set(a["labels"]) & set(allow_unreferenced):
                        findings.append((a["line"], "A2", f"appendix {name(k)} is never referenced in the main "
                                                          f"text outside the roadmap"))
                else:
                    infos.append((a["line"], "A", f"appendix {k + 1} {name(k)}: first main-text reference at "
                                                  f"line {a['first']} ({a['via']})"))
            refd = [k for k, a in enumerate(apps) if a["first"] is not None]
            by_ref = sorted(refd, key=lambda k: apps[k]["first"])
            if refd != by_ref:
                findings.append((apps[refd[0]]["line"], "A1",
                                 "appendices are not in order of first main-text reference: file order "
                                 + ", ".join(name(k) for k in refd) + " / first-reference order "
                                 + ", ".join(name(k) for k in by_ref)))
            if roadmap_seq != sorted(roadmap_seq):
                findings.append((min(road), "A3", "the roadmap names the appendices in the order "
                                 + ", ".join(name(k) for k in roadmap_seq) + " (file order differs)"))

    if "I" in only:
        d = re.search(r"\\begin\{document\}", c)
        d_off = d.end() if d else 0
        auto = italic_wrappers(c[:d_off])
        if auto:
            infos.append((1, "I", "italic wrapper macros from the preamble: " + ", ".join("\\" + w for w in auto)))
        for ln, n, head, snip, ends in italic_leads(c, masked_all, d_off, tuple(auto) + tuple(italic_macros)):
            if n >= lead_min_words:
                findings.append((ln, "I1", f"{head} opens with italic text of {n} words (an italic lead: "
                                           f"write a short roman purpose sentence, or delete it if the section "
                                           f"says it anyway): {snip}"))
            elif ends and n >= 1:
                infos.append((ln, "I", f"{head} opens with a short italic run-in label ({n} words; the rule is "
                                       f"#no-run-in-labels): {snip}"))

    if "L" in only:
        pars = list(paragraphs(orig_lines, prose_lines, lo, hi))
        for s, e in notes:
            ln0 = line_of(masked, s)
            pars.append([(ln0 + k, x) for k, x in enumerate(masked[s:e].split("\n"))])
        for par in pars:
            for ln, n, snip in sentences(par):
                if n > max_words:
                    review["L"].append((ln, "L", f"{n} words: {snip[:110]}"))
        review["L"].sort(key=lambda x: -int(x[2].split()[0]))
    if "P" in only or "W" in only:
        counts = collections.Counter()
        for n in range(lo, hi + 1):
            txt = masked_lines[n - 1]
            if "P" in only:
                for m in POSITION.finditer(txt):
                    review["P"].append((n, "P", f"{m.group(0)!r}: {' '.join(orig_lines[n - 1].split())[:110]}"))
            if "W" in only:
                for m in STRONG.finditer(txt):
                    wd = m.group(1).lower()
                    counts[wd] += 1
                    if wd not in STRONG_FREQUENT:
                        review["W"].append((n, "W", f"{m.group(0)!r}: {' '.join(orig_lines[n - 1].split())[:110]}"))
        if "W" in only:
            infos.append((lo, "W", "strong-word counts: " + (", ".join(f"{w} {k}" for w, k in counts.most_common())
                                                            or "none")))
    if strict:
        findings += review["L"] + review["P"]
    return findings, infos, review


# --------------------------------------------------------------------------- CLI
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tex", nargs="?")
    ap.add_argument("--display-macro", default="", help="comma-separated custom display wrappers, e.g. al,als")
    ap.add_argument("--max-words", type=int, default=40)
    ap.add_argument("--only", default="A,I,L,P,W", help="subset of A,I,L,P,W")
    ap.add_argument("--roadmap", action="append", default=None, help="regex for the roadmap paragraph (repeatable)")
    ap.add_argument("--roadmap-lines", default=None, help="A-B: the roadmap paragraph's line range")
    ap.add_argument("--exclude-section", action="append", default=[],
                    help="regex on a \\section title whose references do not count as first references (repeatable)")
    ap.add_argument("--allow-unreferenced", action="append", default=[], help="appendix label exempt from A2")
    ap.add_argument("--italic-macro", default="",
                    help="comma-separated one-argument macros that print italic text, beyond those the preamble defines")
    ap.add_argument("--lead-min-words", type=int, default=5, help="I1: italic text of this many words at a heading")
    ap.add_argument("--strict", action="store_true", help="L and P items fail the run too")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv[1:])
    if a.selftest:
        return selftest()
    if not a.tex:
        ap.error("tex file required")
    try:
        tex = open(a.tex, encoding="utf-8").read()
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    rl = None
    if a.roadmap_lines:
        try:
            x, y = (int(v) for v in a.roadmap_lines.split("-"))
            rl = (x, y)
        except ValueError:
            print("ERROR: --roadmap-lines wants A-B", file=sys.stderr)
            return 2
    only = "".join(x.strip().upper() for x in a.only.split(","))
    findings, infos, review = check(tex, [m for m in a.display_macro.split(",") if m], a.max_words, only,
                                    tuple(a.roadmap) if a.roadmap else ROADMAP_DEFAULT, rl,
                                    a.allow_unreferenced, a.strict, a.exclude_section,
                                    [m for m in a.italic_macro.split(",") if m], a.lead_min_words)
    for ln, code, msg in findings:
        print(f"{a.tex}:{ln}: [{code}] {msg}")
    for ln, code, msg in infos:
        print(f"{a.tex}:{ln}: [{code} info] {msg}")
    heads = {"L": f"sentences over {a.max_words} words (read, split at the claim boundaries)",
             "P": "position words (resolve each against the text as it now stands)",
             "W": "strong words, rarer ones (three tests: false? generic? tautology?)"}
    for key in "LPW":
        if key in only:
            print(f"--- {key}: {heads[key]}: {len(review[key])}")
            for ln, code, msg in review[key]:
                print(f"{a.tex}:{ln}: [{code}] {msg}")
    print(f"{len(findings)} finding(s); review L={len(review['L'])} P={len(review['P'])} W={len(review['W'])}")
    return 1 if findings else 0


# --------------------------------------------------------------------------- selftest
BAD = r"""\documentclass{article}
\begin{document}
\begin{abstract} Only an abstract, exactly. \end{abstract}
\section{Introduction}
We derive the action $S_{\rm below}$; the details are in Appendix~\ref{app:b}.
% A commented reference to Appendix~\ref{app:c} does not count, nor does "above" here.
The result above is exact, as Smith et al.\ showed in Ref.~\cite{s} and e.g.\ in Eq.~\eqref{eq:a1}.

This paper is organized as follows.
Appendix~\ref{app:b} reviews the method and Appendix~\ref{app:a} collects the algebra.

\section{Main}
A long sentence follows here with many words to exceed the limit $a+b=c$ and it keeps going on and on with more and more words that add nothing new at all but keep the count rising steadily until it passes forty words easily.
Short host sentence.\footnote{This footnote rambles on with enough words to exceed the limit by itself because it keeps adding clause after clause without any real content at all until the reader is tired of it, which takes forty words and then some more.}
The identity reads
\begin{equation}
  x = y \,.
\end{equation}
This starts a new sentence, as the previous section showed.
\appendix
\section*{Appendix}

\section{Algebra}\label{app:a}
\begin{equation} a = b \label{eq:a1} \end{equation}
\section{Method}\label{app:b}
The next appendix is unrelated.
\section{Unused}
\label{app:c}
Nothing refers here.
\section*{Acknowledgments}
Thanks.
\end{document}
"""

LEAD = r"""\documentclass{article}
\newcommand{\lead}[1]{\textit{#1}}
\newcommand\plain[1]{\textbf{#1}}
\begin{document}
\section{Setup}\label{sec:setup}

% a comment between the heading and the lead
\emph{The action has one invariant, and the invariant fixes every divergence $\Gamma$ of the sector.}
Roman text follows.
\subsection{Short label}
\emph{What is not claimed.} The paragraph starts here.
\subsection{One emphasized word}
\emph{Spin} is emphasized at the head; this is not a lead.
\section*{Starred}
{\itshape A grouped declaration wraps the first sentence of this section in italics.} Rest.
\subsection{Macro}
\noindent\lead{A wrapper macro from the preamble prints italic text too.}
\subsection{Bold macro}
\plain{A bold wrapper is not italic and is not this gate.}
\section{Inline}\label{sec:inline} \textit{Five words are enough here.}
\section{Roman purpose}
This section derives the action; \emph{nothing} here is italic at the head.
\paragraph{Run-in heading.} \emph{A paragraph heading is not checked by this gate, even when long.}
\end{document}
"""


def selftest():
    failed = []

    def expect(name, cond, detail=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   <- {detail}" if detail and not cond else ""))
        if not cond:
            failed.append(name)

    lines = BAD.split("\n")
    at = lambda s: next(i for i, x in enumerate(lines, 1) if s in x)  # noqa: E731
    f, inf, rv = check(BAD)
    codes = sorted(c for _, c, _ in f)
    expect("findings A1 (order) + A2 (unreferenced) + A3 (roadmap order), nothing else",
           codes == ["A1", "A2", "A3"], codes)
    a2 = [m for _, c, m in f if c == "A2"]
    expect("A2 names only the unreferenced appendix (a commented reference does not count; the empty "
           "\\section*{Appendix} heading and Acknowledgments are not appendices)",
           len(a2) == 1 and "app:c" in a2[0], a2)
    expect("a label several lines below its \\section is still found", "app:c" in (a2[0] if a2 else ""))
    a1 = [m for _, c, m in f if c == "A1"][0] if "A1" in codes else ""
    expect("A1: a reference to an equation inside an appendix counts as referencing it",
           a1.index("app:b") < a1.rindex("app:a") if a1 else False, a1)
    expect("roadmap paragraph detected and excluded", any(c == "roadmap" and f"lines {at('organized')}-" in m
                                                          for _, c, m in inf), inf)
    longs = {(ln, m.split(":")[0]) for ln, _, m in rv["L"]}
    expect("long sentences: the 43-word one (math counts once) and the 41-word footnote, not its 3-word host",
           longs == {(at("A long sentence"), "43 words"), (at("Short host"), "41 words")}
           and not any("Short host" in m for _, _, m in rv["L"]), rv["L"])
    par = [(n, t) for n, t in enumerate(mask(strip_comments(BAD)).split("\n"), 1) if n == at("The result")]
    expect("et al.\\ / Ref.~ / e.g.\\ do not end a sentence", len(sentences(par)) == 1, sentences(par))
    body = list(paragraphs(lines, mask(strip_comments(BAD)).split("\n"), 1, len(lines)))
    all_s = [s for p in body for s in sentences(p)]
    expect("a display ending in a period ends the sentence",
           not any("identity" in s and "starts" in s for _, _, s in all_s), [s for _, _, s in all_s if "identity" in s])
    pos = sorted(n for n, _, _ in rv["P"])
    expect("position words: 'above' (prose), 'the previous section', 'The next appendix'; not in math or comments",
           pos == sorted([at("The result above"), at("previous section"), at("next appendix")]), rv["P"])
    mini = mask(strip_comments(r"The terms in the second line of Eq.~\eqref{eq:x} and the last line of "
                                r"\cref{eq:y} differ, as $x$ in the first line shows; the line of sight and the first term are unrelated."))
    hits = [m.group(0).lower() for m in POSITION.finditer(mini)]
    expect("display-line positions (one hit per phrase): 'in the second line (of)', 'last line of', "
           "'in the first line'; not 'line of sight' / 'the first term'",
           hits == ["in the second line", "last line of", "in the first line"], hits)
    expect("strong words: body only (the abstract's 'Only' / 'exactly' on the same line are skipped)",
           any(c == "W" and "exact 1" in m and "only" not in m and "exactly" not in m for _, c, m in inf),
           [m for _, c, m in inf if c == "W"])

    good = (BAD.replace(r"\section{Algebra}\label{app:a}" + "\n" + r"\begin{equation} a = b \label{eq:a1} \end{equation}" + "\n"
                        + r"\section{Method}\label{app:b}" + "\n" + "The next appendix is unrelated.",
                        r"\section{Method}\label{app:b}" + "\n" + "The next appendix is unrelated." + "\n"
                        + r"\section{Algebra}\label{app:a}" + "\n" + r"\begin{equation} a = b \label{eq:a1} \end{equation}")
            .replace(r"Appendix~\ref{app:b} reviews the method and Appendix~\ref{app:a} collects the algebra.",
                     r"Appendix~\ref{app:b} reviews the method, Appendix~\ref{app:a} collects the algebra.")
            .replace("This starts a new sentence", r"Appendix~\ref{app:c} is empty. This starts a new sentence"))
    f2, _, _ = check(good)
    expect("reordered appendices and roadmap, every appendix referenced: no finding", f2 == [], f2)
    f3, _, _ = check(BAD, allow_unreferenced=["app:c"])
    expect("--allow-unreferenced exempts an outlook appendix from A2", "A2" not in [c for _, c, _ in f3])
    f6, inf6, _ = check(good, exclude_sections=["^Introduction$"])
    a2x = sorted(m.split("<")[1].split(">")[0] for _, c, m in f6 if c == "A2")
    expect("--exclude-section: references inside the excluded section do not count (app:a, app:b become A2; "
           "app:c, referenced in Main, does not); the roadmap inside it still feeds A3",
           a2x == ["app:a", "app:b"] and {c for _, c, _ in f6} == {"A2"}
           and any(c == "excluded" and "lines 4-" in m for _, c, m in inf6), (a2x, f6))
    f4, _, _ = check(good, strict=True)
    expect("--strict turns the L and P review items into findings", {c for _, c, _ in f4} == {"L", "P"},
           {c for _, c, _ in f4})
    f5, inf5, _ = check(BAD.replace("\\appendix\n", ""), only="A")
    expect("no \\appendix: A checks skipped with a note", f5 == [] and any("no \\appendix" in m for _, _, m in inf5))
    al = BAD.replace("The identity reads\n\\begin{equation}\n  x = y \\,.\n\\end{equation}",
                     "The identity reads\n\\al{\n  x = y \\,.\n}")
    al_lines = al.split("\n")
    al_prose, _ = split_footnotes(mask(strip_comments(al), ["al"]))
    al_s = [s for p in paragraphs(al_lines, al_prose.split("\n"), 1, len(al_lines)) for s in sentences(p)]
    expect("--display-macro wrapper counts as math and can end a sentence",
           any(s.startswith("The identity reads 0.") for _, _, s in al_s), [s for _, _, s in al_s if "identity" in s])

    ll = LEAD.split("\n")
    lat = lambda s: next(i for i, x in enumerate(ll, 1) if s in x)  # noqa: E731
    fl, infl, _ = check(LEAD)
    i1 = sorted(ln for ln, c, _ in fl if c == "I1")
    expect("I1: an italic lead after a blank line, a comment and \\label; a {\\itshape} group; a preamble "
           "wrapper after \\noindent; \\textit on the heading's own line (5 words = the default threshold)",
           i1 == sorted([lat("The action has"), lat("A grouped"), lat("A wrapper macro"), lat("Five words")])
           and {c for _, c, _ in fl} == {"I1"}, fl)
    expect("I1: math counts as one word (the first lead has 15 words)",
           any(ln == lat("The action has") and "of 15 words" in m for ln, c, m in fl), fl)
    il = [(ln, m) for ln, c, m in infl if c == "I"]
    expect("I info: the preamble wrapper \\lead is found (\\plain, a bold wrapper, is not); a short italic "
           "label ending in '.' is listed as a run-in label, not a finding",
           any("\\lead" in m and "\\plain" not in m for _, m in il)
           and [ln for ln, m in il if "run-in" in m] == [lat("What is not claimed")], il)
    expect("I1: one emphasized word, a roman purpose sentence, a bold wrapper and a \\paragraph heading are not leads",
           not {lat("Spin"), lat("This section derives"), lat("A bold wrapper"), lat("Run-in heading")} & set(i1))
    fl6, infl6, _ = check(LEAD, lead_min_words=6)
    expect("--lead-min-words 6: the 5-word lead drops to a run-in info line",
           lat("Five words") not in [ln for ln, c, _ in fl6 if c == "I1"]
           and lat("Five words") in [ln for ln, c, m in infl6 if c == "I" and "run-in" in m], (fl6, infl6))
    fm, _, _ = check(LEAD.replace(r"\newcommand{\lead}[1]{\textit{#1}}", ""), italic_macros=["lead"])
    expect("--italic-macro names a wrapper the preamble does not define",
           lat("A wrapper macro") in [ln for ln, c, _ in fm if c == "I1"], fm)
    pw = italic_wrappers("\\providecommand{\\pl}[1]{\\textit{#1}}\n")
    expect("I1: a wrapper defined with \\providecommand is read like \\newcommand", pw == ["pl"], pw)
    fa, _, _ = check(LEAD, only="ALPW")
    expect("--only without I skips the gate", "I1" not in {c for _, c, _ in fa}, fa)
    with tempfile.TemporaryDirectory() as td:
        pb, pg, pl = (os.path.join(td, x) for x in ("bad.tex", "good.tex", "lead.tex"))
        for p, txt in ((pb, BAD), (pg, good), (pl, LEAD)):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(txt)

        def run(*a):
            return subprocess.run([sys.executable, os.path.abspath(__file__), *a], capture_output=True,
                                  text=True).returncode
        expect("CLI exit 1 on findings (appendix order; italic lead), 0 on the clean fixture and with "
               "--only that leaves out I, 2 on a missing file",
               (run(pb), run(pg), run(pl), run(pl, "--only", "A,L,P,W"), run(os.path.join(td, "none.tex")))
               == (1, 0, 1, 0, 2))
    print(f"selftest: {'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
