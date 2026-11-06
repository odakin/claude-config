#!/usr/bin/env python3
"""Count the paragraphs of a latexdiff output that contain a change but no item tag (``\\itemtag{...}``).

Why: a diff that readers check against a numbered list of changes carries a tag
at each change (conventions/latex.md#latexdiff-item-labels).  A change made
without a tag (a forgotten one, or one latexdiff moved away from its tag) is
then easy to miss: the reader looks for tags.  This counts paragraphs (text
between blank lines after ``\\begin{document}``) that have ``\\DIFadd`` / ``\\DIFdel``
markup and no tag command, and prints each one.

Limit: a tag anywhere in the paragraph counts, so a paragraph with two changes
and one tag passes; give every change its own tag where the tags are put
(the script that writes the tagged copy), and use this as the net.

Usage
    latexdiff-untagged-changes.py DIFF.tex [--tag-cmd itemtag] [--strict]
        last line = number of untagged paragraphs (exit 0; --strict: exit 1 when > 0)
    latexdiff-untagged-changes.py --selftest
"""
import argparse
import re
import sys

MARK_RE = re.compile(r"\\DIF(?:add|del)(?:begin|end)?(?:FL)?\b|\\DIF(?:add|del)\{")


def untagged(text, tag_cmd="itemtag"):
    k = text.find("\\begin{document}")
    body = text[k:] if k >= 0 else text
    changed, bad = 0, []
    for p in re.split(r"\n\s*\n", body):
        if MARK_RE.search(p):
            changed += 1
            if "\\" + tag_cmd + "{" not in p:
                bad.append(p)
    return changed, bad


def selftest():
    doc = ("\\providecommand{\\DIFadd}[1]{#1}\n\\begin{document}\n"
           "Same text.\n\n"
           "A \\DIFaddbegin \\DIFadd{\\itemtag{A1}new}\\DIFaddend{} word.\n\n"
           "B \\DIFdelbegin \\DIFdel{old}\\DIFdelend{} word.\n\n"
           "C \\DIFadd{\\mytag{x}y}\n\\end{document}\n")
    bad = 0
    c, u = untagged(doc)
    if c != 3 or len(u) != 2 or not u[0].startswith("B"):
        bad += 1
        print("FAIL default tag:", c, [x[:10] for x in u])
    c2, u2 = untagged(doc, "mytag")
    if c2 != 3 or len(u2) != 2:
        bad += 1
        print("FAIL other tag:", c2, len(u2))
    if untagged("\\begin{document}\nplain\n\\end{document}")[0] != 0:
        bad += 1
        print("FAIL no change")
    print(f"selftest: {3 - bad}/3 passed")
    return 1 if bad else 0


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description="Count changed paragraphs without an item tag in a latexdiff output.")
    ap.add_argument("diff")
    ap.add_argument("--tag-cmd", default="itemtag")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    c, u = untagged(open(a.diff, encoding="utf-8").read(), a.tag_cmd)
    for p in u:
        print("--- no tag:", re.sub(r"\s+", " ", p)[:300])
    print(f"paragraphs with changes: {c}")
    print(len(u))
    return 1 if (a.strict and u) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
