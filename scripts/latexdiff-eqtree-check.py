#!/usr/bin/env python3
"""latexdiff-eqtree-check.py -- check the marks on the displayed equations of a diff against the two versions, without latexdiff-eqtree.py.

  latexdiff-eqtree-check.py <old.tex> <new.tex> <diff.tex> [--table out.md]

old.tex and new.tex are the flat versions given to `latexdiff-eqtree.py protect` (before it rewrites them); diff.tex is
the finished diff.  The comparison here is its own: a numbered equation is the rows of a display up to and including
the row that holds its \\label (the unnumbered rows before it belong to it, and rows after the last label to the last
one); two equations are the same when their tokens are the same, apart from spacing, \\label, \\nonumber, row breaks,
alignment tabs, \\left / \\right and the size of a delimiter (latexdiff-eqtree.py does not mark those either).

What a reader of the diff should see (conventions/latex.md#latexdiff-eqtree-moved-sections):
  - an equation that did not move: no mark when it is the same, marks when it changed;
  - an equation that moved: struck where it was and underlined where it is, as the text around it, whatever changed
    inside it (the text of a moved block is not compared word by word either);
  - an equation that only one version has: struck or underlined.
"Moved" is read from the text: a display between \\DIFaddbegin and \\DIFaddend (or \\DIFdelbegin / \\DIFdelend) of
diff.tex stands in a block of text that latexdiff took out or put in.

Checks (exit 1 if one fails):
  1. a display inside an added block is underlined whole, one inside a deleted block struck whole; a display outside the
     blocks is never underlined or struck whole (that would be an equation shown as deleted + added where it stands);
  2. every equation of the new version outside the blocks has an old equation of the same label (or, unlabeled, the same
     content), and it carries marks exactly when its content differs from that old equation;
  3. every equation of the new version inside an added block is either new (no old equation with its label) or moved:
     its old equation appears struck whole inside a deleted block, and that block is not the one right before (or after)
     the added block = latexdiff's replacement in place (that would be an equation that stayed, shown deleted + added);
  4. every old equation appears once: as the old side of a display outside the blocks, or struck in a deleted block.
The table (--table) lists the equations that changed without moving and the equations that moved, by label.
"""
import argparse
import bisect
import re
import sys

DISPLAY = re.compile(r"\\begin\{(align|equation|gather|multline|eqnarray)(\*?)\}(.*?)\\end\{\1\2\}", re.S)
TOKEN = re.compile(r"\\[A-Za-z]+\*?|\\.|[^\s]", re.S)
SKIP_TOK = {"\\,", "\\;", "\\:", "\\!", "\\ ", "\\quad", "\\qquad", "\\enspace", "\\thinspace", "\\nonumber", "\\notag",
            "\\left", "\\right", "\\big", "\\Big", "\\bigg", "\\Bigg", "\\bigl", "\\Bigl", "\\biggl", "\\Biggl",
            "\\bigr", "\\Bigr", "\\biggr", "\\Biggr", "\\bigm", "\\Bigm", "&", "\\displaystyle"}
LABEL = re.compile(r"\\label\{([^}]*)\}")


def brace_end(s, i):
    """s[i] == '{': the index after its closing brace."""
    d = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
            if d == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced braces")


def view(s, keep):
    """The text with \\DIFadd{..} / \\DIFdel{..} resolved: keep = 'old' drops additions, 'new' drops deletions."""
    out, i = [], 0
    drop, unwrap = ("\\DIFadd{", "\\DIFdel{") if keep == "old" else ("\\DIFdel{", "\\DIFadd{")
    while i < len(s):
        if s.startswith(drop, i):
            i = brace_end(s, i + len(drop) - 1)
        elif s.startswith(unwrap, i):
            j = brace_end(s, i + len(unwrap) - 1)
            out.append(view(s[i + len(unwrap):j - 1], keep))
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def tokens(s):
    s = LABEL.sub(" ", s)
    s = re.sub(r"\\\\\*?(\[[^\]]*\])?", " ", s)
    return [t for t in TOKEN.findall(s) if t not in SKIP_TOK]


def key(s, braces=True):
    t = tokens(s)
    return " ".join(x for x in t if braces or x not in "{}")


def rows(body):
    """Top-level rows of a display body (not inside braces or a nested environment)."""
    res, start, depth, env, i = [], 0, 0, 0, 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            m = re.match(r"\\(begin|end)\{[^}]*\}", body[i:])
            if m:
                env += 1 if m.group(1) == "begin" else -1
                i += m.end()
                continue
            if body.startswith("\\\\", i) and depth == 0 and env == 0:
                m = re.match(r"\\\\\*?(\[[^\]]*\])?", body[i:])
                res.append(body[start:i])
                i += m.end()
                start = i
                continue
            i += 2
            continue
        depth += 1 if c == "{" else -1 if c == "}" else 0
        i += 1
    res.append(body[start:])
    return res


def equations(body):
    """[(label or None, text)] of a display body: each numbered row with the unnumbered rows before it."""
    eqs, cur = [], []
    for r in rows(body):
        cur.append(r)
        labs = LABEL.findall(r)
        if labs:
            eqs.append((labs[0], " ".join(cur)))
            cur = []
    if cur and "".join(cur).strip():
        if eqs:
            eqs[-1] = (eqs[-1][0], eqs[-1][1] + " " + " ".join(cur))
        else:
            eqs.append((None, " ".join(cur)))
    return eqs


def displays(s):
    b = s.find("\\begin{document}")
    return [(m.start(), m.end(), m.group(3)) for m in DISPLAY.finditer(s, max(b, 0))]


def block_state(s, pos):
    """'add' / 'del' / None: whether pos lies between \\DIFaddbegin and \\DIFaddend (or the del pair)."""
    for kind in ("add", "del"):
        opened = s.count("\\DIF%sbegin" % kind, 0, pos) - s.count("\\DIF%send" % kind, 0, pos)
        if opened > 0:
            return kind
    return None


def blocks(s):
    """[(kind, start, end)] of the \\DIFaddbegin..\\DIFaddend and \\DIFdelbegin..\\DIFdelend spans, in order."""
    res = []
    for kind in ("add", "del"):
        for m in re.finditer(r"\\DIF%sbegin(.*?)\\DIF%send" % (kind, kind), s, re.S):
            res.append((kind, m.start(), m.end()))
    return sorted(res, key=lambda b: b[1])


def block_at(bl, pos):
    return next((k for k, (_, a, b) in enumerate(bl) if a <= pos < b), None)


def replacement_pair(s, bl, i, j):
    """Blocks i and j are one replacement in place: a deleted and an added block with only space between."""
    if i is None or j is None:
        return False
    a, b = sorted((i, j))
    return b == a + 1 and {bl[a][0], bl[b][0]} == {"add", "del"} and not s[bl[a][2]:bl[b][1]].strip()


SENTENCE = re.compile(r"(?<=[.?!])\s+(?=[A-Z\\])")


def anchors(text):
    """The sentences of the text between the displays, and for each display the number of sentences before it:
    (keys, {display start: count}).  Very short pieces (a lone command) are left out: they repeat across the
    document and would pair wrongly."""
    b = max(text.find("\\begin{document}"), 0)
    keys, anchor, pos = [], {}, b
    for m in list(DISPLAY.finditer(text, b)) + [None]:
        seg = text[pos:m.start() if m else len(text)]
        for p in re.split(r"\n\s*\n", seg):
            for sent in SENTENCE.split(" ".join(p.split())):
                if len(sent) >= 25:
                    keys.append(sent)
        if m:
            anchor[m.start()] = len(keys)
            pos = m.end()
    return keys, anchor


def weighted_lcs(a, b):
    """Pairs (i, j) of equal items kept in order, the most words in common: what latexdiff, which aligns words, keeps.
    (difflib's longest-block-first matching keeps the other side of a swap of two long blocks: measured.)"""
    w = [len(x.split()) for x in a]
    N, M = len(a), len(b)
    where = {}
    for j, y in enumerate(b):
        where.setdefault(y, []).append(j)
    nxt = [0] * (M + 1)
    rows = [None] * (N + 1)
    rows[N] = nxt
    for i in range(N - 1, -1, -1):
        cur = [0] * (M + 1)
        hits = set(where.get(a[i], ()))
        for j in range(M - 1, -1, -1):
            best = max(nxt[j], cur[j + 1])
            if j in hits:
                best = max(best, w[i] + nxt[j + 1])
            cur[j] = best
        rows[i] = cur
        nxt = cur
    pairs, i, j = [], 0, 0
    while i < N and j < M:
        if a[i] == b[j] and rows[i][j] == w[i] + rows[i + 1][j + 1]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif rows[i][j] == rows[i + 1][j]:
            i += 1
        else:
            j += 1
    return pairs


def stays(old, new):
    """For each display start of the two versions, its interval between sentences that keep their order: a function
    (old start, new start) -> True when the two lie in the same interval (the equation did not move relative to the
    text that stayed).  The sentences are paired here (weighted_lcs), not by latexdiff."""
    ko, ao = anchors(old)
    kn, an = anchors(new)
    pairs = weighted_lcs(ko, kn)
    mo, mn = [i for i, _ in pairs], [j for _, j in pairs]

    def interval(m, count):
        return bisect.bisect_right(m, count - 1)      # how many paired sentences lie before the display

    return lambda so, sn: interval(mo, ao[so]) == interval(mn, an[sn])


def marks(body):
    """'none', 'add-whole', 'del-whole' or 'inside' (some symbols marked)."""
    has_add, has_del = "\\DIFadd{" in body, "\\DIFdel{" in body
    if not has_add and not has_del:
        return "none"
    if has_add and not has_del and not key(view(body, "old")):
        return "add-whole"
    if has_del and not has_add and not key(view(body, "new")):
        return "del-whole"
    return "inside"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("diff")
    ap.add_argument("--table")
    a = ap.parse_args()
    old, new, diff = (open(p, encoding="utf-8").read() for p in (a.old, a.new, a.diff))
    fails = []
    # the equations of the two versions
    O, N = {}, {}
    o_unl, n_unl = [], []
    old_disp = []        # per old display: [(label or ("unlabeled", k), token key without braces)]
    disp_at = {"old": {}, "new": {}}    # label -> start of its display
    for side, store, unl, text in (("old", O, o_unl, old), ("new", N, n_unl, new)):
        for s0, _, body in displays(text):
            d = []
            for lab, t in equations(body):
                if lab is None:
                    d.append((("unlabeled", len(unl)), key(t, braces=False)))
                    unl.append(t)
                elif lab in store:
                    fails.append("label %s twice in one version" % lab)
                else:
                    d.append((lab, key(t, braces=False)))
                    store[lab] = t
                    disp_at[side][lab] = s0
            if store is O:
                old_disp.append(d)
    o_unl_keys = [key(t, braces=False) for t in o_unl]
    old_seen = {lab: 0 for lab in O}
    o_unl_seen = [0] * len(o_unl)
    changed, moved, new_only, same = [], [], [], 0
    struck = []          # token keys (without braces) of the equations struck whole inside deleted blocks
    struck_at = []       # the block of each of them
    added_at = {}        # label -> the block of its underlined equation
    bl = blocks(diff)
    for start, end, body in displays(diff):
        where, how = block_state(diff, start), marks(body)
        eqs = equations(body)
        if where == "add" and how != "add-whole":
            fails.append("display in an added block not underlined whole: %s" % body[:80])
        if where == "del" and how != "del-whole":
            fails.append("display in a deleted block not struck whole: %s" % body[:80])
        if where is None and how in ("add-whole", "del-whole"):
            fails.append("display outside the blocks shown whole (%s): %s" % (how, body[:80]))
        if where == "del":
            struck.append(key(view(body, "old"), braces=False))
            struck_at.append(block_at(bl, start))
            continue
        for lab, t in eqs:
            # the renderer may add braces around a marked cell: read back without braces
            nt, ot = key(view(t, "new"), braces=False), key(view(t, "old"), braces=False)
            if lab is None:
                # an unlabeled equation is matched by its content
                if where == "add":
                    if nt in o_unl_keys:
                        moved.append(("(unlabeled)", "unlabeled, moved"))
                    else:
                        new_only.append("(unlabeled)")
                    continue
                if ot in o_unl_keys:
                    k = o_unl_keys.index(ot)
                    o_unl_seen[k] += 1
                    if (ot != nt) != (how == "inside"):
                        fails.append("unlabeled equation: marks do not match its change: %s" % t[:80])
                    if ot != nt:
                        changed.append(("(unlabeled)", how))
                    else:
                        same += 1
                else:
                    fails.append("unlabeled equation outside the blocks with no old equation: %s" % t[:80])
                continue
            if lab not in N:
                fails.append("label %s of diff.tex not in the new version" % lab)
                continue
            if nt != key(N[lab], braces=False):
                fails.append("label %s: the new side of diff.tex differs from the new version" % lab)
            if where == "add":
                if lab in O:
                    moved.append((lab, "same" if key(O[lab]) == key(N[lab]) else "content changed"))
                    added_at[lab] = block_at(bl, start)
                else:
                    new_only.append(lab)
                continue
            if lab not in O:
                fails.append("label %s outside the blocks but not in the old version" % lab)
                continue
            old_seen[lab] += 1
            if ot != key(O[lab], braces=False):
                fails.append("label %s: the old side of diff.tex differs from the old version" % lab)
            differs = key(O[lab]) != key(N[lab])
            marked = view(t, "old") != view(t, "new")
            if differs != marked:
                fails.append("label %s: %s but %s" % (lab, "changed" if differs else "unchanged",
                                                      "marked" if marked else "unmarked"))
            if differs:
                changed.append((lab, "symbols marked"))
            else:
                same += 1
    # every struck display is exactly a run of consecutive equations of one old display (a display that the diff cut
    # into pieces gives one run per piece); the equations of the run are struck in that block
    struck_of = {}       # label, or ("unlabeled", k), -> the block of the struck display holding it
    for K, blk in zip(struck, struck_at):
        hit = None
        for d in old_disp:
            for i in range(len(d)):
                acc = ""
                for j in range(i, len(d)):
                    acc = (acc + " " + d[j][1]).strip()
                    if len(acc) > len(K):
                        break
                    if acc == K and not any(x[0] in struck_of for x in d[i:j + 1]):
                        hit = d[i:j + 1]
                        break
                if hit:
                    break
            if hit:
                break
        if hit is None:
            fails.append("struck display that is no run of old equations: %s" % K[:80])
            continue
        for ident, _ in hit:
            struck_of[ident] = blk
            if isinstance(ident, tuple):
                o_unl_seen[ident[1]] += 1
            else:
                old_seen[ident] += 1
    for lab, _ in moved:
        if lab == "(unlabeled)":
            continue
        if lab not in struck_of:
            fails.append("label %s moved, but its old equation is not struck in a deleted block" % lab)
        elif replacement_pair(diff, bl, struck_of[lab], added_at.get(lab)):
            fails.append("label %s did not move but is shown deleted + added where it stands" % lab)
    # moved or not, read from the text that kept its order (difflib on the paragraphs), not from latexdiff
    stay = stays(old, new)
    shown_moved = {lab for lab, _ in moved}
    for lab in N:
        if lab not in O:
            continue
        s = stay(disp_at["old"][lab], disp_at["new"][lab])
        if s and lab in shown_moved:
            fails.append("label %s stayed among the text that kept its order, but is shown struck + underlined" % lab)
        if not s and lab not in shown_moved:
            fails.append("label %s moved relative to the text that kept its order, but is shown in place" % lab)
    for lab, n in old_seen.items():
        if n != 1:
            fails.append("old equation %s appears %d times in diff.tex" % (lab, n))
    for k, n in enumerate(o_unl_seen):
        if n != 1:
            fails.append("old unlabeled equation appears %d times: %s" % (n, o_unl[k][:80]))
    deleted = [lab for lab in O if lab not in N]
    print("equations: %d unchanged in place, %d changed in place, %d moved, %d new, %d deleted"
          % (same, len(changed), len(moved), len(new_only), len(deleted)))
    print("changed in place:", [lab for lab, _ in changed])
    print("moved:", [lab for lab, _ in moved])
    print("moved with a change inside (shown whole, as moved text):", [lab for lab, h in moved if h == "content changed"])
    print("new:", new_only, " deleted:", deleted)
    if a.table:
        with open(a.table, "w", encoding="utf-8") as f:
            f.write("| equation (label) | in place or moved | content | shown as |\n|---|---|---|---|\n")
            for lab, h in changed:
                f.write("| `%s` | in place | changed | %s |\n" % (lab, h))
            for lab, h in moved:
                f.write("| `%s` | moved | %s | struck at the old place, underlined at the new |\n" % (lab, h))
            for lab in new_only:
                f.write("| `%s` | new | — | underlined |\n" % lab)
            for lab in deleted:
                f.write("| `%s` | deleted | — | struck |\n" % lab)
    for x in fails:
        print("FAIL:", x)
    print("ok" if not fails else "%d failures" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
