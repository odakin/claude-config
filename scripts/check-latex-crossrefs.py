#!/usr/bin/env python3
"""Find bare parenthetical cross-references and misplaced \\labelcref numbers.

Usage:
  python3 check-latex-crossrefs.py paper.tex appendix.tex [--report audit.json]
  python3 check-latex-crossrefs.py paper.tex --baseline HEAD --report audit.json
  python3 check-latex-crossrefs.py paper.tex --list-all
  python3 check-latex-crossrefs.py paper.tex --no-labelcref-form
  python3 check-latex-crossrefs.py --selftest

Checks literal parentheses and the common \\pn{...} wrapper. Recognizes
\\cref/\\Cref, ranges, \\autoref, and explicit Sec./Section/Appendix/Fig./Eq.
plus \\ref, including line breaks, multiple references, and literal numbers.
Bare "see"/"see also" lists are candidates too. Qualified prose such as
"as derived in Sec.~\\ref{sec:proof}" is not a bare reference.

It also checks where each \\labelcref stands, for the two-tier style in which
\\cref prints "Eq. (N)" where a reference stands on its own and a bare "(N)"
from "noun~\\labelcref" sits in apposition right after a noun:
  comma-apposition      the number floats between commas after a noun.
  independent-position  after a preposition, conjunction, article, copula, or
                        listed verb ("from", "nor", "in~"), at the start of a
                        sentence, paragraph, footnote, or caption, or right
                        after a heading or display math.
                        A "~" does not make this position appositive.
  missing-tie           after a noun, inline math, or macro argument, but with a
                        breakable space instead of "~". A second item joined by
                        "and"/"or"/"to" to a preceding reference also needs "~".
A range end "--\\labelcref" and a comma-separated item after a reference are
accepted. Inline wrappers such as \\blue{...} and bare {...} groups are
looked through. Words
outside the closed function-word list count as nouns, so an unlisted verb
before "~\\labelcref" is not reported. A \\labelcref already reported as a
bare parenthetical is not reported again. --no-labelcref-form skips this check
for manuscripts that do not use the two-tier style.

Comments, verbatim-like environments, \\verb, and standard math regions
(including \\al/\\als) are masked without changing source positions.
Only supplied files are inspected; includes and arbitrary macros are not
expanded. --list-all exposes qualified parenthetical references and the
accepted range ends and list items for review.
No automatic rewrite is attempted: the actual relation must be read.
--baseline REF additionally checks that reference commands, label bindings,
citations, and protected math/comment/verbatim regions have not changed.

Exit 1 means bare or \\labelcref-placement candidates remain, 0 means none in
the inspected syntax, and 2 means an input/CLI error. This heuristic is not a
full TeX/style proof.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import subprocess
from pathlib import Path


REF = re.compile(
    r"\\(?P<cmd>[cC]ref(?:range)?|[cC]pageref(?:range)?|[aA]utoref|"
    r"[nN]ameref|labelcref|eqref|pageref|ref)\*?\s*\{[^{}]*\}"
    r"(?:\s*\{[^{}]*\})?"
)
TYPE = re.compile(
    r"\b(?:Secs?|Sects?|Sections?|Appendix|Appendices|Apps?|Figures?|Figs?|"
    r"Equations?|Eqs?|Tables?|Tabs?|Chapters?|Chaps?|Theorems?|Lemmas?|"
    r"Propositions?|Corollaries)\b\.?", re.I
)
IGNORED_ENVS = (
    "comment", "verbatim", "Verbatim", "lstlisting", "minted",
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "eqnarray", "eqnarray*", "flalign", "flalign*",
)
BEGIN = re.compile(r"\\begin\s*\{(" + "|".join(map(re.escape, IGNORED_ENVS)) + r")\}")
MATH_WRAPPER = re.compile(r"\\(?:al|als)\s*\{")
VERB = re.compile(r"\\verb\*?([^A-Za-z\s])")
VERBATIM_ENVS = ("verbatim", "Verbatim", "lstlisting", "minted")
LABELCREF = re.compile(r"\\labelcref\s*\{[^{}]*\}")
REF_TAIL = re.compile(
    r"\\(?:[cC]ref(?:range)?|[aA]utoref|labelcref|eqref|ref)\*?\s*\{[^{}]*\}"
    r"(?:\s*\{[^{}]*\})?\s*$"
)
TEX_INVISIBLE = re.compile(r"(?:%[^\n]*\n[ \t]*)*")
# After these words a bare number stands on its own (the \cref position), even with "~".
# Any other word before "~\labelcref" is taken as the noun the number is attached to.
FUNCTION_WORDS = frozenset("""
    about above across after against along among around as at before behind below beside
    besides between beyond by cf despite during except for from in including inside into like
    near of on onto over per since than through throughout to toward towards under unlike until
    upon via with within without
    and or nor but whereas while whether if because although though unless
    hence thus therefore then also so
    the a an this that these those its their our each every both either neither all any some no
    is are was were be been being become becomes became remain remains
    give gives gave given yield yields satisfy satisfies obey obeys imply implies see use uses
    used using apply applies applied applying combine combines combining combined substitute
    substituting inserting compare comparing recover recovers reproduce reproduces
""".split())
# After a reference, these join the next number as the second item of a pair or range.
CONNECTOR_WORDS = frozenset("and or nor to through versus vs".split())
# Groups that start a new text unit; other macro groups such as \blue{...} are looked through.
BLOCK_GROUPS = frozenset("""
    footnote caption section subsection subsubsection paragraph subparagraph chapter part
    title item
""".split())
BOUNDARY_WORDS = frozenset("item par newline noindent indent".split())
WRAPPER_OPEN = re.compile(r"\\([A-Za-z]+)\*?(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})*\s*\{$")


def escaped(text, i):
    count = 0
    i -= 1
    while i >= 0 and text[i] == "\\":
        count += 1
        i -= 1
    return count % 2 == 1


def balanced_end(text, start):
    depth = 0
    for i in range(start, len(text)):
        if escaped(text, i):
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i+1
    return len(text)


def closing_end(text, start, delimiter):
    i = start
    while True:
        i = text.find(delimiter, i)
        if i < 0:
            return len(text)
        if not escaped(text, i):
            return i+len(delimiter)
        i += len(delimiter)


def mask_nonprose(text, protected=None, regions=None):
    chars = list(text)
    i = 0
    while i < len(text):
        end = None
        kind = None
        if text[i] == "%" and not escaped(text, i):
            end = text.find("\n", i)
            if end < 0:
                end = len(text)
            kind = "comment"
        elif not escaped(text, i):
            verb = VERB.match(text, i)
            env = BEGIN.match(text, i)
            wrapper = MATH_WRAPPER.match(text, i)
            if verb:
                delimiter = verb.group(1)
                end = text.find(delimiter, verb.end())
                end = len(text) if end < 0 else end+1
                kind = "verbatim"
            elif env:
                delimiter = r"\end{" + env.group(1) + "}"
                end = closing_end(text, env.end(), delimiter)
                kind = ("comment" if env.group(1) == "comment" else
                        "verbatim" if env.group(1) in VERBATIM_ENVS else "display")
            elif wrapper:
                end = balanced_end(text, wrapper.end()-1)
                kind = "display"
            elif text.startswith(r"\(", i) or text.startswith(r"\[", i):
                end = closing_end(text, i+2, r"\)" if text[i+1] == "(" else r"\]")
                kind = "inline" if text[i+1] == "(" else "display"
            elif text[i] == "$":
                delimiter = "$$" if text.startswith("$$", i) else "$"
                end = closing_end(text, i+len(delimiter), delimiter)
                kind = "display" if delimiter == "$$" else "inline"
        if end is not None:
            if protected is not None:
                protected.append(text[i:end])
            if regions is not None:
                regions.append((i, end, kind))
            for j in range(i, end):
                if chars[j] != "\n":
                    chars[j] = " "
            i = end
        else:
            i += 1
    return "".join(chars)


def parenthetical_regions(text):
    stack = []
    regions = []
    for i, char in enumerate(text):
        if escaped(text, i):
            continue
        if char == "(":
            stack.append(i)
        elif char == ")" and stack:
            start = stack.pop()
            regions.append((start, i+1, start+1, i, "parentheses"))
    for match in re.finditer(r"\\pn\s*\{", text):
        end = balanced_end(text, match.end()-1)
        regions.append((match.start(), end, match.end(), end-1, "pn-wrapper"))
    return sorted(regions)


def classify(body):
    refs = list(REF.finditer(body))
    without_refs = REF.sub("", body)
    typed = bool(TYPE.search(without_refs))
    # (\ref{eq:x}) is the ordinary equation-number notation, not (Eq. ...).
    automatic_type = any(m.group("cmd") not in ("ref", "eqref", "pageref") for m in refs)
    literal_number = bool(re.search(r"\b(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\b", without_refs))
    if not (automatic_type or typed and (refs or literal_number)):
        return None
    rest = without_refs
    rest = TYPE.sub("", rest)
    rest = re.sub(r"\b(?:see|also|and|or|respectively)\b", "", rest, flags=re.I)
    rest = re.sub(r"\b(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*|[IVX]+)\b", "", rest)
    rest = re.sub(r"\\[,;:! ]|[\s~.,;:&(){}\[\]\-–—]+", "", rest)
    return {"bare": not rest, "reference_commands": [m.group(0) for m in refs]}


def inspect_text(text, path="<memory>"):
    masked = mask_nonprose(text)
    findings = []
    for start, end, body_start, body_end, kind in parenthetical_regions(masked):
        classification = classify(masked[body_start:body_end])
        if classification is not None:
            findings.append({
                "path": str(path), "line": text.count("\n", 0, start)+1,
                "column": start-text.rfind("\n", 0, start),
                "kind": kind, "text": text[start:end], **classification,
            })
    return findings


def skip_back(text, ends, p):
    """Move p left over whitespace and comments, which separate tokens invisibly."""
    while p > 0:
        region = ends.get(p)
        if region and region[1] == "comment":
            p = region[0]
        elif text[p-1] in " \t\r\n":
            p -= 1
        else:
            break
    return p


def reference_before(text, ends, p):
    """True when a reference command ends before p, allowing one comma in between."""
    p = skip_back(text, ends, p)
    if p > 0 and text[p-1] == "," and not escaped(text, p-1):
        p = skip_back(text, ends, p-1)
    return bool(REF_TAIL.search(text[max(0, p-400):p]))


def labelcref_role(text, ends, s):
    """Return (role, tied) for the token in front of the command starting at s.

    role is noun, independent, comma, joined (and/or/to after a reference), or
    continued (range end or list item after a reference). tied means "~" or no
    breakable space stands between that token and the command.
    """
    p = skip_back(text, ends, s)
    if re.search(r"\n[ \t]*\n", text[p:s]):
        return "independent", False  # a blank line starts a new paragraph
    tied = bool(TEX_INVISIBLE.fullmatch(text[p:s]))
    if p > 0 and text[p-1] == "~" and not escaped(text, p-1):
        p = skip_back(text, ends, p-1)
    while p > 1 and text[p-1] in ",;:!" and escaped(text, p-1):
        p = skip_back(text, ends, p-2)  # \, \; \: \! are kerns, not break points
    if p == 0:
        return "independent", tied
    region = ends.get(p)
    if region:
        return ("independent" if region[1] == "display" else "noun"), tied
    head = text[max(0, p-120):p]
    char = text[p-1]
    if char.isalpha():
        word = re.search(r"[A-Za-z]+$", head)
        if word is None:
            return "noun", tied
        start = p-len(word.group(0))
        if start > 0 and text[start-1] == "\\" and not escaped(text, start-1):
            return ("independent" if word.group(0) in BOUNDARY_WORDS else "noun"), tied
        lower = word.group(0).lower()
        if lower in CONNECTOR_WORDS and reference_before(text, ends, start):
            return "joined", tied
        return ("independent" if lower in FUNCTION_WORDS else "noun"), tied
    if char == "." and not escaped(text, p-1):
        word = re.search(r"([A-Za-z]+)\.$", head)
        if word and TYPE.fullmatch(word.group(0)):
            return "noun", tied
        if word and word.group(1).lower() in CONNECTOR_WORDS and reference_before(
                text, ends, p-len(word.group(0))):
            return "joined", tied
        return "independent", tied
    if char == ",":
        return ("continued" if reference_before(text, ends, p-1) else "comma"), tied
    if char in "-\u2013":
        return "continued", tied
    if char == "{" and not escaped(text, p-1):
        wrapper = WRAPPER_OPEN.search(head)
        if wrapper is None:
            return labelcref_role(text, ends, p-1)
        if wrapper.group(1) not in BLOCK_GROUPS:
            return labelcref_role(text, ends, p-len(wrapper.group(0)))
        return "independent", tied
    if char == "}":
        closing = re.search(r"\\([A-Za-z]+)\*?(?:\s*\[[^\]]*\])?\s*\{[^{}]*\}$", head)
        if closing and closing.group(1) in BLOCK_GROUPS | {"begin", "end"}:
            return "independent", tied
    if char == "\\" and p > 1 and text[p-2] == "\\" and not escaped(text, p-2):
        return "independent", tied  # after a \\ line break
    if char in ":;!?(\u2014":
        return "independent", tied
    return "noun", tied


def inspect_labelcref(text, path="<memory>"):
    regions = []
    masked = mask_nonprose(text, regions=regions)
    ends = {end: (start, kind) for start, end, kind in regions}
    reported = []
    for start, end, body_start, body_end, _ in parenthetical_regions(masked):
        classification = classify(masked[body_start:body_end])
        if classification is not None and classification["bare"]:
            reported.append((start, end))
    findings = []
    for match in LABELCREF.finditer(masked):
        s = match.start()
        if escaped(text, s) or any(start <= s < end for start, end in reported):
            continue
        role, tied = labelcref_role(text, ends, s)
        if role == "continued":
            form = "continuation"
        elif role == "comma":
            form = "comma-apposition"
        elif role == "independent":
            form = "independent-position"
        elif not tied:
            form = "missing-tie"
        else:
            continue
        context = max(0, s-50)
        space = text.find(" ", context, s)
        if context and space >= 0:
            context = space+1
        findings.append({
            "path": str(path), "line": text.count("\n", 0, s)+1,
            "column": s-text.rfind("\n", 0, s), "form": form,
            "candidate": form != "continuation", "text": text[context:match.end()],
        })
    return findings


def compare_text(before, after):
    protected_before, protected_after = [], []
    mask_nonprose(before, protected_before)
    mask_nonprose(after, protected_after)
    labels = re.compile(r"\\label\s*\{[^{}]*\}")
    cites = re.compile(r"\\cite[a-zA-Z]*\*?(?:\s*\[[^\]]*\])*\s*\{[^{}]*\}")
    keyed_macros = re.compile(r"\\[A-Za-z]+\*?\s*\{[A-Za-z][\w-]*:[^{}]*\}")
    return {
        "reference_commands_unchanged": Counter(m.group(0) for m in REF.finditer(before))
                                       == Counter(m.group(0) for m in REF.finditer(after)),
        "label_bindings_unchanged": Counter(labels.findall(before)) == Counter(labels.findall(after)),
        "citations_unchanged": Counter(cites.findall(before)) == Counter(cites.findall(after)),
        "label_keyed_macros_unchanged": Counter(keyed_macros.findall(before))
                                      == Counter(keyed_macros.findall(after)),
        "protected_regions_unchanged": protected_before == protected_after,
    }


def baseline_check(path, text, revision, labelcref=True):
    root = Path(subprocess.check_output(
        ["git", "-C", str(path.resolve().parent), "rev-parse", "--show-toplevel"], text=True).strip())
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--verify", revision+"^{commit}"], text=True).strip()
    relative = path.resolve().relative_to(root).as_posix()
    before = subprocess.check_output(["git", "-C", str(root), "show", commit+":"+relative]).decode("utf-8")
    prior = inspect_text(before, path)
    counts = {"baseline_bare_count": sum(row["bare"] for row in prior),
              "baseline_parenthetical_count": len(prior)}
    if labelcref:
        counts["baseline_labelcref_candidate_count"] = sum(
            row["candidate"] for row in inspect_labelcref(before, path))
    return {"path": str(path), "baseline_commit": commit, **counts, **compare_text(before, text)}


def selftest():
    cases = [
        (r"A (\cref{sec:a}).", 1),
        (r"A (\Cref{sec:a,sec:b}).", 1),
        (r"A (Sec.~\ref{sec:a}).", 1),
        ("A (Section\n\\ref{sec:a}).", 1),
        (r"A (Secs.~\ref{sec:a} and \ref{sec:b}).", 1),
        (r"A (Appendix~\ref{app:a}).", 1),
        (r"A (see also Fig.~\ref{fig:a}).", 1),
        (r"A (Eq.~\ref{eq:a}).", 1),
        (r"A (\autoref{sec:a}).", 1),
        (r"A (\crefrange{sec:a}{sec:b}).", 1),
        (r"A \pn{Sec.~\ref{sec:a}}.", 1),
        (r"A (Sec. 4.2).", 1),
        (r"A (Appendix B).", 1),
        (r"A (as derived in Sec.~\ref{sec:a}).", 0),
        (r"Section~\ref{sec:a} defines A.", 0),
        (r"The expression (\ref{eq:a}) vanishes.", 0),
        ("A % (Sec.~\\ref{sec:a})\nB.", 0),
        (r"A \% (Sec.~\ref{sec:a}).", 1),
        (r"\verb|(Sec.~\ref{sec:a})|", 0),
        (r"\begin{comment}(Sec.~\ref{sec:a})\end{comment}", 0),
        (r"\begin{verbatim}(Sec.~\ref{sec:a})\end{verbatim}", 0),
        (r"$f(x)$ and \(x\) \[y\] \al{x=(\ref{eq:a})}", 0),
        ("A % ignored\n(Sec.~\\ref{sec:a})", 1),
    ]
    for text, count in cases:
        rows = inspect_text(text)
        assert sum(row["bare"] for row in rows) == count, (text, rows, count)
    row = inspect_text(cases[-1][0])[0]
    assert row["line"] == 2 and row["column"] == 1
    assert len(inspect_text(cases[13][0])) == 1  # --list-all exposes qualified prose.
    before = r"A (Sec.~\ref{sec:a}); $x=1$."
    after = r"A is defined in Sec.~\ref{sec:a}; $x=1$."
    assert all(compare_text(before, after).values())
    assert not compare_text(before, after.replace("sec:a", "sec:b"))["reference_commands_unchanged"]
    assert not compare_text(before, after.replace("x=1", "x=2"))["protected_regions_unchanged"]
    assert not compare_text(r"\label{x}", r"\label{y}")["label_bindings_unchanged"]
    assert not compare_text(r"\cite{x}", r"\cite{y}")["citations_unchanged"]
    assert not compare_text(r"\er{eq:x}", r"\er{eq:y}")["label_keyed_macros_unchanged"]
    placement = [
        # (source, candidate forms in order, accepted range ends and list items)
        (r"The boundary flux, \labelcref{eq:a,eq:b}, is conserved.", ["comma-apposition"], 0),
        (r"This matches the bulk rule, \labelcref{eq:a}.", ["comma-apposition"], 0),
        (r"This follows from \labelcref{eq:a}.", ["independent-position"], 0),
        (r"Neither parity nor \labelcref{eq:a} fixes the sign.", ["independent-position"], 0),
        (r"The sum in~\labelcref{eq:a} converges.", ["independent-position"], 0),
        (r"We stop here. \labelcref{eq:a} holds.", ["independent-position"], 0),
        (r"We use \blue{\labelcref{eq:a}} here.", ["independent-position"], 0),
        (r"This holds.\footnote{\labelcref{eq:a} is exact.}", ["independent-position"], 0),
        ("\\begin{equation}x\\end{equation}\n\\labelcref{eq:a} holds.", ["independent-position"], 0),
        (r"Combining \labelcref{eq:a}--\labelcref{eq:b} gives the bound.", ["independent-position"], 1),
        ("Some text\n\n\\labelcref{eq:a} holds.", ["independent-position"], 0),
        ("\\section{Results}\n\\labelcref{eq:a} holds.", ["independent-position"], 0),
        (r"The rule {\labelcref{eq:a}} holds.", ["missing-tie"], 0),
        (r"The constraint \labelcref{eq:a} holds.", ["missing-tie"], 0),
        ("The constraint\n\\labelcref{eq:a} holds.", ["missing-tie"], 0),
        (r"The bounds~\labelcref{eq:a} and \labelcref{eq:b} agree.", ["missing-tie"], 0),
        (r"The field $\phi$ \labelcref{eq:a} is real.", ["missing-tie"], 0),
        (r"The flux \textcolor{red}{\labelcref{eq:a}} is conserved.", ["missing-tie"], 0),
        (r"The identities \labelcref{eq:a}--\labelcref{eq:b} hold.", ["missing-tie"], 1),
        (r"The constraint~\labelcref{eq:a} holds.", [], 0),
        (r"The identities~\labelcref{eq:a}--\labelcref{eq:b} hold.", [], 1),
        (r"The bounds~\labelcref{eq:a} and~\labelcref{eq:b} agree.", [], 0),
        (r"The relations~\labelcref{eq:a}, \labelcref{eq:b}, and~\labelcref{eq:c} hold.", [], 1),
        (r"Equations~\labelcref{eq:a} to~\labelcref{eq:b} are linear.", [], 0),
        (r"We use \cref{eq:a} and \Cref{eq:b}.", [], 0),
        (r"Equation~\labelcref{eq:a} is linear.", [], 0),
        (r"The field $\phi$~\labelcref{eq:a} is real.", [], 0),
        (r"The flux~\blue{\labelcref{eq:a}} is conserved.", [], 0),
        (r"The flux\,\labelcref{eq:a} is conserved.", [], 0),
        ("The constraint~%\n  \\labelcref{eq:a} holds.", [], 0),
        ("A % the constraint \\labelcref{eq:a}\nB.", [], 0),
        (r"$x = \labelcref{eq:a}$ and \[y \labelcref{eq:b}\]", [], 0),
        (r"A (\labelcref{eq:a}).", [], 0),
    ]
    for text, forms, accepted in placement:
        rows = inspect_labelcref(text)
        assert [row["form"] for row in rows if row["candidate"]] == forms, (text, rows, forms)
        assert sum(not row["candidate"] for row in rows) == accepted, (text, rows, accepted)
    assert sum(row["bare"] for row in inspect_text(placement[-1][0])) == 1  # reported once
    row = inspect_labelcref("A\nThe constraint \\labelcref{eq:a}.")[0]
    assert row["line"] == 2 and row["column"] == 16
    print(f"PASS: {len(cases)} syntax/false-positive cases, {len(placement)} "
          "\\labelcref placement cases, and source positions")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--list-all", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", help="git revision for preservation checks")
    parser.add_argument("--no-labelcref-form", action="store_true",
                        help="skip the \\labelcref placement check")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.files:
        parser.error("supply explicit .tex files or --selftest")
    rows = []
    placements = []
    inputs = []
    checks = []
    hashes = {}
    for path in args.files:
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as error:
            parser.error(str(error))
        inputs.append(str(path))
        hashes[str(path)] = hashlib.sha256(raw).hexdigest()
        rows.extend(inspect_text(text, path))
        if not args.no_labelcref_form:
            placements.extend(inspect_labelcref(text, path))
        if args.baseline:
            try:
                checks.append(baseline_check(path, text, args.baseline, not args.no_labelcref_form))
            except (OSError, subprocess.CalledProcessError, ValueError) as error:
                parser.error(str(error))
    bare = [row for row in rows if row["bare"]]
    misplaced = [row for row in placements if row["candidate"]]
    order = {path: index for index, path in enumerate(inputs)}
    shown_rows = [(row, "BARE" if row["bare"] else "REVIEW", "")
                  for row in (rows if args.list_all else bare)]
    shown_rows += [(row, row["form"].upper() if row["candidate"] else "REVIEW", "...")
                   for row in (placements if args.list_all else misplaced)]
    shown_rows.sort(key=lambda item: (order[item[0]["path"]], item[0]["line"], item[0]["column"]))
    for row, tag, prefix in shown_rows:
        shown = " ".join(row["text"].split())
        print(f'{row["path"]}:{row["line"]}:{row["column"]}: {tag}: {prefix}{shown}')
    placement_summary = ("\\labelcref placement not checked" if args.no_labelcref_form
                         else f"{len(misplaced)} \\labelcref placement candidates")
    print(f"{len(bare)} bare candidates; {len(rows)} parenthetical references; "
          f"{placement_summary}; {len(inputs)} files")
    changed = []
    for check in checks:
        failed = [key for key, value in check.items() if value is False]
        print(f'{check["path"]}: preservation '+("FAIL "+", ".join(failed) if failed else "PASS"))
        changed.extend(failed)
    if args.report:
        args.report.write_text(json.dumps({
            "inputs": inputs, "bare_count": len(bare), "parenthetical_count": len(rows),
            "findings": rows,
            "labelcref_placement": {
                "checked": not args.no_labelcref_form,
                "candidate_count": len(misplaced), "findings": placements,
            },
            "source_sha256": hashes, "preservation": checks,
            "scope": "Supplied files, recognized source syntax only; no include or macro expansion; "
                     "\\labelcref placement uses a closed function-word list.",
        }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return int(bool(bare or misplaced or changed))


if __name__ == "__main__":
    raise SystemExit(main())
