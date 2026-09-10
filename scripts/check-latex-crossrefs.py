#!/usr/bin/env python3
"""Find bare parenthetical cross-references in manuscripts adopting that style.

Usage:
  python3 check-latex-crossrefs.py paper.tex appendix.tex [--report audit.json]
  python3 check-latex-crossrefs.py paper.tex --baseline HEAD --report audit.json
  python3 check-latex-crossrefs.py paper.tex --list-all
  python3 check-latex-crossrefs.py --selftest

Checks literal parentheses and the common \\pn{...} wrapper. Recognizes
\\cref/\\Cref, ranges, \\autoref, and explicit Sec./Section/Appendix/Fig./Eq.
plus \\ref, including line breaks, multiple references, and literal numbers.
Bare "see"/"see also" lists are candidates too. Qualified prose such as
"as derived in Sec.~\\ref{sec:proof}" is not a bare reference.

Comments, verbatim-like environments, \\verb, and standard math regions
(including \\al/\\als) are masked without changing source positions.
Only supplied files are inspected; includes and arbitrary macros are not
expanded. --list-all exposes qualified parenthetical references for review.
No automatic rewrite is attempted: the actual relation must be read.
--baseline REF additionally checks that reference commands, label bindings,
citations, and protected math/comment/verbatim regions have not changed.

Exit 1 means bare candidates remain, 0 means none in the inspected syntax,
and 2 means an input/CLI error. This heuristic is not a full TeX/style proof.
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


def mask_nonprose(text, protected=None):
    chars = list(text)
    i = 0
    while i < len(text):
        end = None
        if text[i] == "%" and not escaped(text, i):
            end = text.find("\n", i)
            if end < 0:
                end = len(text)
        elif not escaped(text, i):
            verb = re.match(r"\\verb\*?([^A-Za-z\s])", text[i:])
            env = BEGIN.match(text, i)
            wrapper = MATH_WRAPPER.match(text, i)
            if verb:
                delimiter = verb.group(1)
                end = text.find(delimiter, i+verb.end())
                end = len(text) if end < 0 else end+1
            elif env:
                delimiter = r"\end{" + env.group(1) + "}"
                end = closing_end(text, env.end(), delimiter)
            elif wrapper:
                end = balanced_end(text, wrapper.end()-1)
            elif text.startswith(r"\(", i) or text.startswith(r"\[", i):
                end = closing_end(text, i+2, r"\)" if text[i+1] == "(" else r"\]")
            elif text[i] == "$":
                delimiter = "$$" if text.startswith("$$", i) else "$"
                end = closing_end(text, i+len(delimiter), delimiter)
        if end is not None:
            if protected is not None:
                protected.append(text[i:end])
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


def baseline_check(path, text, revision):
    root = Path(subprocess.check_output(
        ["git", "-C", str(path.resolve().parent), "rev-parse", "--show-toplevel"], text=True).strip())
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--verify", revision+"^{commit}"], text=True).strip()
    relative = path.resolve().relative_to(root).as_posix()
    before = subprocess.check_output(["git", "-C", str(root), "show", commit+":"+relative]).decode("utf-8")
    prior = inspect_text(before, path)
    return {"path": str(path), "baseline_commit": commit,
            "baseline_bare_count": sum(row["bare"] for row in prior),
            "baseline_parenthetical_count": len(prior), **compare_text(before, text)}


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
    print(f"PASS: {len(cases)} syntax/false-positive cases and source positions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--list-all", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", help="git revision for preservation checks")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.files:
        parser.error("supply explicit .tex files or --selftest")
    rows = []
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
        if args.baseline:
            try:
                checks.append(baseline_check(path, text, args.baseline))
            except (OSError, subprocess.CalledProcessError, ValueError) as error:
                parser.error(str(error))
    bare = [row for row in rows if row["bare"]]
    for row in rows if args.list_all else bare:
        tag = "BARE" if row["bare"] else "REVIEW"
        shown = " ".join(row["text"].split())
        print(f'{row["path"]}:{row["line"]}:{row["column"]}: {tag}: {shown}')
    print(f"{len(bare)} bare candidates; {len(rows)} parenthetical references; {len(inputs)} files")
    changed = []
    for check in checks:
        failed = [key for key, value in check.items() if value is False]
        print(f'{check["path"]}: preservation '+("FAIL "+", ".join(failed) if failed else "PASS"))
        changed.extend(failed)
    if args.report:
        args.report.write_text(json.dumps({
            "inputs": inputs, "bare_count": len(bare), "parenthetical_count": len(rows),
            "findings": rows,
            "source_sha256": hashes, "preservation": checks,
            "scope": "Supplied files, recognized source syntax only; no include or macro expansion.",
        }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return int(bool(bare or changed))


if __name__ == "__main__":
    raise SystemExit(main())
