#!/usr/bin/env python3
"""Repair latexdiff output made with --math-markup=fine, and splice in whole-equation markup where fine is unreadable.

Why: --math-markup=fine marks only the changed tokens inside an equation (the
reviewer sees `R0 -> R1` instead of the whole equation struck out and rewritten),
but on a real manuscript it breaks in a few recurring ways (measured):

  1. an accent macro is left outside the markup in front of it:
       `\\widehat \\DIFadd{L^i}`  -> TeX: "Missing { inserted" ... cascade
  2. the second argument of \\frac falls outside the \\DIFadd that holds \\frac:
       `\\DIFadd{... \\frac{A}<newline>}{\\DIFadd{B}}`
       -> "Argument of \\frac has an extra }" / "Paragraph ended before \\frac"
  3. on the deleted side, a command latexdiff cannot wrap is commented out
     (`%DIFDELCMD <`), so the deleted equation renders without it and reads wrong:
       `{A \\over B}` loses the fraction bar, `\\widehat O` loses the hat,
       `L \\gtrsim` loses the relation.
  4. a layout change (row vector -> column vector, `\\left( ... \\right)` moved)
     is unreadable token by token: the new column shows with a few struck commas
     and the old row is not visible at all.

`fix` repairs 1-3 in place.  `splice` handles 4: run latexdiff a second time
with --math-markup=whole on the same inputs, then replace only the equations
carrying the given labels in the fine output by the whole output's
"old (struck) + new (underlined)" pair.  Everything else keeps the fine marks.

Usage:
  latexdiff-fine-fixups.py fix diff.tex [--accents name,name]
  latexdiff-fine-fixups.py splice diff.tex whole.tex --labels eq:a,eq:b
  latexdiff-fine-fixups.py --selftest

Run `fix` before scripts/check-latexdiff-math-markup.py --scan (it removes the
unmarked deleted commands of class 3) and run scripts/latexdiff-strip-dup-labels.py
on whole.tex before `splice`.  For class 4 the remaining unmarked
`\\left(` / `\\right)` can also be avoided by replacing them with plain `(` `)` on
both sides before latexdiff.  Convention: conventions/latex.md#latexdiff-fine-markup.
"""
import re
import sys

ACCENTS = ["widehat", "hat", "bar", "tilde", "widetilde", "vec", "overline", "overrightarrow",
           "dot", "ddot", "check", "breve", "acute", "grave"]


def _group_end(t, i):
    """Index of the } that closes the { at t[i]."""
    assert t[i] == "{"
    d = 0
    for k in range(i, len(t)):
        if t[k] == "{":
            d += 1
        elif t[k] == "}":
            d -= 1
            if d == 0:
                return k
    raise ValueError("unbalanced braces from %d" % i)


def fix(s, accents=ACCENTS):
    counts = {}
    # 1. accent outside the markup -> inside
    alt = "|".join(sorted(set(accents), key=len, reverse=True))
    s, counts["accent"] = re.subn(r"\\(%s)\s*\\(DIFadd|DIFdel)\{" % alt, r"\\\2{\\\1 ", s)
    # 2. second argument of \frac outside the \DIFadd that holds \frac
    n, key = 0, "}\n}{\\DIFadd{"
    while True:
        i = s.find(key)
        if i < 0:
            break
        j = i + len("}\n}{\\DIFadd")
        k = _group_end(s, j)
        if k + 1 >= len(s) or s[k + 1] != "}":
            break  # not the shape we know; leave it for the TeX log
        s = s[:i] + "}{" + s[j + 1:k] + "}\n}" + s[k + 2:]
        n += 1
    counts["frac"] = n
    # 3. deleted-side commands commented out with %DIFDELCMD -> back inside \DIFdel
    s, counts["over"] = re.subn(
        r"%DIFDELCMD < \{%%%\n\\DIFdel\{(.*?)\}%DIFDELCMD < \\over\s*%%%\n\\DIFdel\{(.*?)\}%DIFDELCMD < \}\n(?:%DIFDELCMD <\s*%%%\n)?",
        r"\\DIFdel{{\1 \\over \2}}\n", s, flags=re.S)
    s, counts["cmd-before"] = re.subn(r"%DIFDELCMD < (\\[A-Za-z]+)\s*%%%\n\\DIFdel\{", r"\\DIFdel{\1 ", s)
    s, counts["cmd-after"] = re.subn(r"\n\}%DIFDELCMD < (\\[A-Za-z]+)\s*\n%DIFDELCMD < %%%\n", r" \1}\n", s)
    return s, counts


def splice(fine, whole, labels):
    done = []
    for lab in labels:
        key = "\\label{%s}" % lab
        if fine.count(key) != 1 or whole.count(key) != 1:
            raise ValueError("label %s: %d in fine, %d in whole (need exactly 1 each)" % (lab, fine.count(key), whole.count(key)))
        k = whole.index(key)
        starts = list(re.finditer(r"\\DIFaddbegin \\begin\{([A-Za-z]+)\}", whole[:k]))
        if not starts:
            raise ValueError("label %s: no added environment before it in the whole output" % lab)
        env = starts[-1].group(1)
        a0 = starts[-1].start()
        end_add = "\\end{%s}\\DIFaddend" % env
        a1 = whole.index(end_add, k) + len(end_add)
        dels = list(re.finditer(r"\\DIFdelbegin \\begin\{%s\*?\}" % env, whole[:a0]))
        if not dels:
            raise ValueError("label %s: no deleted copy before the added one" % lab)
        d0 = dels[-1].start()
        if whole[whole.index("\\DIFdelend", d0) + len("\\DIFdelend"):a0].strip():
            raise ValueError("label %s: text between the deleted and the added copy" % lab)
        k = fine.index(key)
        f0 = fine.rindex("\\begin{%s}" % env, 0, k)
        f1 = fine.index("\\end{%s}" % env, k) + len("\\end{%s}" % env)
        fine = fine[:f0] + whole[d0:a1] + fine[f1:]
        done.append(lab)
    return fine, done


def selftest():
    ok = True

    def check(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print("FAIL", name, "\n got: %r\nwant: %r" % (got, want))

    s, c = fix("x\\widehat \\DIFadd{L^i}y")
    check("accent", s, "x\\DIFadd{\\widehat L^i}y")
    s, c = fix("x\\ol \\DIFdel{a}", accents=ACCENTS + ["ol"])
    check("accent-extra", s, "x\\DIFdel{\\ol a}")
    s, c = fix("\\DIFadd{\\sum\\frac{a+b}\n}{\\DIFadd{c_{1}}} .")
    check("frac", s, "\\DIFadd{\\sum\\frac{a+b}{c_{1}}\n} .")
    s, c = fix("+ \\DIFdelbegin %DIFDELCMD < {%%%\n\\DIFdel{a-b }%DIFDELCMD < \\over  %%%\n\\DIFdel{c}%DIFDELCMD < }\n%DIFDELCMD <     %%%\n\\DIFdelend")
    check("over", s, "+ \\DIFdelbegin \\DIFdel{{a-b  \\over c}}\n\\DIFdelend")
    s, c = fix("\\DIFdel{x\\,}%DIFDELCMD < \\widehat %%%\n\\DIFdel{O }\\DIFdelend")
    check("cmd-before", s, "\\DIFdel{x\\,}\\DIFdel{\\widehat O }\\DIFdelend")
    s, c = fix("\\DIFdelbegin \\DIFdel{L\n}%DIFDELCMD < \\gtrsim\n%DIFDELCMD < %%%\n\\DIFdelend")
    check("cmd-after", s, "\\DIFdelbegin \\DIFdel{L \\gtrsim}\n\\DIFdelend")
    fine = "a\n\\begin{align}\nx &= (y)^t\\label{eq:q}\n\\end{align}\nb"
    whole = ("a\n\\DIFdelbegin \\begin{align*}\n\\DIFdel{x} &\\DIFdel{= y}\n\\end{align*}%DIFAUXCMD\n\\DIFdelend "
             "\\DIFaddbegin \\begin{align}\n\\DIFadd{x} &\\DIFadd{= (y)^t\\label{eq:q}}\n\\end{align}\\DIFaddend \nb")
    got, done = splice(fine, whole, ["eq:q"])
    check("splice", got, "a\n" + whole[2:whole.index("\\DIFaddend") + len("\\DIFaddend")] + "\nb")
    check("splice-done", done, ["eq:q"])
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if len(argv) >= 3 and argv[1] == "fix":
        p = argv[2]
        acc = ACCENTS
        if "--accents" in argv:
            acc = ACCENTS + [a for a in argv[argv.index("--accents") + 1].split(",") if a]
        s, c = fix(open(p, encoding="utf-8").read(), acc)
        open(p, "w", encoding="utf-8").write(s)
        print("fixups: " + " ".join("%s %d" % kv for kv in c.items()))
        return 0
    if len(argv) >= 4 and argv[1] == "splice" and "--labels" in argv:
        labels = [x for x in argv[argv.index("--labels") + 1].split(",") if x]
        fine = open(argv[2], encoding="utf-8").read()
        whole = open(argv[3], encoding="utf-8").read()
        out, done = splice(fine, whole, labels)
        open(argv[2], "w", encoding="utf-8").write(out)
        print("whole-equation markup spliced for: " + ", ".join(done))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
