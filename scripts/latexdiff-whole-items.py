#!/usr/bin/env python3
"""Rebuild one list (itemize / enumerate) in a latexdiff output so that each item is deleted, added or kept whole.

Why: latexdiff matches words across item boundaries when items are deleted
from a list.  In the PDF a deleted item seems to keep a word ("Sec."), a kept
item seems to lose one, and empty bullets appear between deleted items
(measured: a closing list of a reply letter that lost five of seven items).
For a list whose items are entries (changes, references, tasks) the reader
needs "this entry went, that one stayed".  Same idea as replacing a whole
equation in ``latexdiff-fine-fixups.py splice``: take the list from both
sides and write it again from whole items.

What it does: finds the first ``\\begin{ENV}`` after an anchor string (which
must occur exactly once in each of DIFF, OLD and NEW), splits the items at
``\\item`` (not ``\\itemtag``), compares items with whitespace collapsed and the
commands named by ``--ignore-cmd`` removed (item tags added only to the new
side), and replaces the list body in DIFF:
  old item also in new  -> ``\\item <old text>``                              (no markup)
  old item not in new   -> ``\\item \\DIFdelbegin \\DIFdel{<text>}\\DIFdelend``
  new item not in old   -> ``\\item \\DIFaddbegin \\DIFadd{<text>}\\DIFaddend``
``--tag-first-change '<tex>'`` puts ``\\DIFadd{<tex>}`` (e.g. ``\\itemtag{A3}``) in front of
the first changed item.  Kept items must keep their relative order (else exit 2;
a reordered list is not a list of whole deletions and additions).  Items with
a nested list are refused (exit 2).  Run it after ``latexdiff-fine-fixups.py`` and
before the build; check the page image afterwards.

Usage
    latexdiff-whole-items.py DIFF.tex OLD.tex NEW.tex --after 'Finally, the following' [--env itemize]
                             [--ignore-cmd itemtag] [--tag-first-change '\\itemtag{A3}']
    latexdiff-whole-items.py --selftest
"""
import argparse
import re
import sys

ITEM_RE = re.compile(r"\\item(?![A-Za-z])")


def find_list(s, after, env):
    if s.count(after) != 1:
        raise ValueError(f"anchor found {s.count(after)} times (need exactly 1): {after[:40]!r}")
    i = s.index(after)
    b = s.find("\\begin{" + env + "}", i)
    if b < 0:
        raise ValueError(f"no \\begin{{{env}}} after the anchor")
    a = b + len("\\begin{" + env + "}")
    e = s.find("\\end{" + env + "}", a)
    if e < 0:
        raise ValueError(f"no \\end{{{env}}} after the anchor")
    body = s[a:e]
    if "\\begin{" in body:
        raise ValueError("an item contains a nested environment; not handled")
    return a, e, body


def split_items(body, ignore):
    raw = [re.sub(r"\s+", " ", x).strip() for x in ITEM_RE.split(body)[1:]]
    out = []
    for x in raw:
        for c in ignore:
            x = re.sub(r"\\" + re.escape(c) + r"\{[^{}]*\}\s*", "", x)
        out.append(x.strip())
    return out


def rebuild(diff, old, new, after, env="itemize", ignore=("itemtag",), tag=None):
    _, _, ob = find_list(old, after, env)
    _, _, nb = find_list(new, after, env)
    o, n = split_items(ob, ignore), split_items(nb, ignore)
    if [x for x in o if x in n] != [x for x in n if x in o]:
        raise ValueError("kept items changed their order")
    a, e, _ = find_list(diff, after, env)
    lines, tagged = [], False

    def lead():
        nonlocal tagged
        if tag and not tagged:
            tagged = True
            return "\\DIFaddbegin \\DIFadd{" + tag + "}\\DIFaddend "
        return ""
    for x in o:
        if x in n:
            lines.append("\\item " + x)
        else:
            lines.append("\\item " + lead() + "\\DIFdelbegin \\DIFdel{" + x + "}\\DIFdelend")
    for x in n:
        if x not in o:
            lines.append("\\item " + lead() + "\\DIFaddbegin \\DIFadd{" + x + "}\\DIFaddend")
    stats = (len(o), len(n), sum(x not in n for x in o), sum(x not in o for x in n))
    return diff[:a] + "\n" + "\n".join(lines) + "\n" + diff[e:], stats


def selftest():
    old = "x\nFinally, the list:\n\\begin{itemize}\n\\item Sec.~A moved.\n\\item New Sec.~B.\n\\item Sec.~C: a note.\n\\item Typos.\n\\end{itemize}\nend\n"
    new = "x\nFinally, the list:\n\\begin{itemize}\n\\item \\itemtag{T1}Sec.~C: a note.\n\\item Typos.\n\\end{itemize}\nend\n"
    diff = ("x\nFinally, the list:\n\\begin{itemize}\n\\item \\DIFdelbegin \\DIFdel{Sec.~A moved.\n}%DIFDELCMD < \\item %%%\n"
            "\\item%DIFAUXCMD\n\\DIFdel{New }\\DIFdelend Sec.~\\DIFdelbegin \\DIFdel{B.}\\DIFdelend C: a note.\n\\item Typos.\n\\end{itemize}\nend\n")
    bad = 0
    got, st = rebuild(diff, old, new, "Finally, the list:", tag="\\itemtag{T1}")
    want_body = ("\n\\item \\DIFaddbegin \\DIFadd{\\itemtag{T1}}\\DIFaddend \\DIFdelbegin \\DIFdel{Sec.~A moved.}\\DIFdelend\n"
                 "\\item \\DIFdelbegin \\DIFdel{New Sec.~B.}\\DIFdelend\n\\item Sec.~C: a note.\n\\item Typos.\n")
    if st != (4, 2, 2, 0) or want_body not in got or got.count("%DIFDELCMD") != 0 or not got.endswith("\\end{itemize}\nend\n"):
        bad += 1
        print("FAIL deletions:", st, repr(got))
    new2 = new.replace("\\item Typos.", "\\item Typos.\n\\item Added entry.")
    got2, st2 = rebuild(diff, old, new2, "Finally, the list:")
    if st2[3] != 1 or "\\DIFadd{Added entry.}" not in got2:
        bad += 1
        print("FAIL addition:", st2)
    new3 = new.replace("\\item \\itemtag{T1}Sec.~C: a note.\n\\item Typos.", "\\item Typos.\n\\item Sec.~C: a note.")
    try:
        rebuild(diff, old, new3, "Finally, the list:")
        bad += 1
        print("FAIL reorder not refused")
    except ValueError:
        pass
    try:
        rebuild(diff + "Finally, the list:", old, new, "Finally, the list:")
        bad += 1
        print("FAIL duplicate anchor not refused")
    except ValueError:
        pass
    old4 = old.replace("\\item Typos.", "\\item Typos.\n\\begin{itemize}\\item x\\end{itemize}")
    try:
        rebuild(diff, old4, new, "Finally, the list:")
        bad += 1
        print("FAIL nested list not refused")
    except ValueError:
        pass
    # \itemtag is not an \item
    if split_items("\\item \\itemtag{Z}a \\item b", ("itemtag",)) != ["a", "b"]:
        bad += 1
        print("FAIL itemtag split")
    print(f"selftest: {6 - bad}/6 passed")
    return 1 if bad else 0


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description="Rebuild one list in a latexdiff output from whole items.")
    ap.add_argument("diff")
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--after", required=True, help="anchor text just before the list (exactly once in each file)")
    ap.add_argument("--env", default="itemize")
    ap.add_argument("--ignore-cmd", action="append", default=None, help="one-argument command to drop before comparing items (default itemtag)")
    ap.add_argument("--tag-first-change", default=None)
    a = ap.parse_args(argv)
    ignore = tuple(a.ignore_cmd) if a.ignore_cmd else ("itemtag",)
    try:
        d = open(a.diff, encoding="utf-8").read()
        out, st = rebuild(d, open(a.old, encoding="utf-8").read(), open(a.new, encoding="utf-8").read(),
                          a.after, a.env, ignore, a.tag_first_change)
    except ValueError as e:
        print(f"latexdiff-whole-items: {e}", file=sys.stderr)
        return 2
    open(a.diff, "w", encoding="utf-8").write(out)
    print(f"list: {st[0]} old items, {st[1]} new items, {st[2]} deleted whole, {st[3]} added whole")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
