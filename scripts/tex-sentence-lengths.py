#!/usr/bin/env python3
"""LaTeX 原稿の英文の文の長さを数える (概数) — 文の数・中央値・N 語超の件数と、 長い順の一覧 (tex の行番号つき)。

なぜ (実測): AI の校閲が「長いので分けよ」 と挙げた文の一覧は全数でなかった (挙げた文の約 3 倍の文が 60 語を超えていた)。
文の長さの規律 (conventions/writing-discipline.md#plain-short-sentences) を原稿全体に当てるには、 一覧を頼まずに数える。
共同研究者の側でも同じ数え方で前後を比べられるよう、 判定は単純な規則だけにしてある (概数であって構文解析ではない)。

使い方:
    python3 tex-sentence-lengths.py paper.tex [more.tex ...] [--over 40] [--joins [--joins-min 20]] [--display-macro al] [--json]
    python3 tex-sentence-lengths.py --selftest

数え方:
  - `\\begin{document}` 以降を読み、 `%` コメント行と行末コメントを除く。
  - display 環境 (equation / align / gather / multline / figure / table / tabular / thebibliography / longtable、 * つきも)
    を除き、 その中の点では文を切らない。 display を macro で書く原稿は `--display-macro NAME` (繰り返し可) で
    `\\NAME{...}` を括弧の釣り合いを取って除く (例: `\\al{...}` を align の代わりに使う家風)。
  - インライン数式 `$...$` と `\\cite` / `\\ref` / `\\eqref` / `\\cref` / `\\label` 類は 1 語として数える。
  - 略語の点 (Ref. Eq. Sec. Fig. App. e.g. i.e. vs. al. cf. など) では切らない。 文末 = `.` `!` `?` の後に空白と
    大文字・`\\`・`$` が続く所、 または空行。 英字の語だけを数える (20 文字未満の断片は捨てる)。
  - `--over N` = N 語を超える文を長い順に、 文の始まりの概ねの行番号つきで出す。
  - 閾値の既定 = 30, 40, 50, 60, 80 語 (`--thresholds 40,60` で変える)。
  - `--joins` = `--joins-min` 語以上 (既定 20) の文のうち、 独立した節を `, and` / `, so` / `, but` / `, while` / `, or` /
    `, whereas` でつないだらしい文 (接続詞の後が限定詞・代名詞・数式・前置詞で始まる = `C<数>`) と、 最初の comma の前に
    9 語以上の句を置いた文 (`L`) を、 原稿の順に出す。 長さの閾値の下に残る読みにくい文の候補 (実測: N 語超の文を半分に
    減らした後もまだ長いと言われ、 残っていたのはこの形だった)。 名詞の並列 (`A, B, and the C`) も拾う = 1 件ずつ読む。
exit: 0 = 数えた / 2 = 入力の file が無い・読めない。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
from pathlib import Path

ABBR = r"\b(Ref|Refs|Eq|Eqs|Sec|Secs|Fig|Figs|App|Apps|Tab|cf|e\.g|i\.e|vs|al|Phys|Rev|Lett|Nat|Opt|No|Vol)\."
DISPLAY = (r"\\begin\{(equation|align|gather|multline|figure|table|tabular|thebibliography|longtable)\*?\}"
           r".*?\\end\{\1\*?\}")
# --joins: 接続詞の後が節の頭らしい語 (限定詞・代名詞・数式・前置詞) のときだけ数え、 語の並列 (「A, B, or C」) の大半を外す
JOIN_START = (r"(?:the|a|an|its|it|their|they|we|this|that|these|those|each|every|no|both|any|one|our|MATH|"
              r"inside|outside|below|above|at|in|for|with|from|on|by|there|here|then|only|all|most|neither|nor)\b")
JOIN = re.compile(r",\s+(?:and|so|but|while|or|whereas)\s+" + JOIN_START, re.I)
LONG_LEAD_WORDS = 9


def load(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").split("\n")
    start = next((i for i, l in enumerate(lines) if "\\begin{document}" in l), 0)
    out = []
    for n, l in enumerate(lines[start:], start=start + 1):
        if l.lstrip().startswith("%"):
            continue
        out.append((n, re.sub(r"(?<!\\)%.*", "", l)))
    return out


def strip_macros(t: str, macros: list[str]) -> str:
    """`\\NAME{...}` を括弧の釣り合いを取って同じ長さの空白に置き換える (位置 = 行番号の対応を保つ)。"""
    for name in macros:
        key = "\\" + name + "{"
        out, i = [], 0
        while True:
            j = t.find(key, i)
            if j < 0:
                out.append(t[i:])
                break
            out.append(t[i:j])
            k, depth = j + len(key), 1
            while k < len(t) and depth:
                depth += {"{": 1, "}": -1}.get(t[k], 0)
                k += 1
            out.append(" " * (k - j))
            i = k
        t = "".join(out)
    return t


def clean(t: str) -> str:
    t = re.sub(DISPLAY, " ", t, flags=re.S)
    t = re.sub(r"\$[^$]*\$", " MATH ", t)
    t = re.sub(r"\\(cite|cref|Cref|ref|eqref|label|autoref)\w*\s*(\[[^\]]*\])?\{[^}]*\}", " REF ", t)
    t = re.sub(r"\\(begin|end)\{[^}]*\}", " ", t)
    t = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", "", t)
    t = re.sub(r"[{}~]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def sentences(path: Path, macros: list[str]) -> list[tuple[int, int, str]]:
    """(語数, 行番号, 整えた文) の list。"""
    text, marks = "", []
    for n, l in load(path):
        marks.append((len(text), n))
        text += l + "\n"
    text = re.sub(DISPLAY, lambda m: " " * len(m.group(0)), text, flags=re.S)
    text = strip_macros(text, macros)
    text = re.sub(ABBR, lambda m: m.group(0).replace(".", "\x00"), text)
    out, pos = [], 0
    for m in re.finditer(r"[.!?](?=\s+[A-Z\\$])|\n\s*\n", text):
        seg, seg_start, pos = text[pos:m.end()], pos, m.end()
        c = clean(seg.replace("\x00", "."))
        if len(c) < 20:
            continue
        w = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", c))
        lead = len(seg) - len(seg.lstrip())
        line = max((n for off, n in marks if off <= seg_start + lead), default=1)
        out.append((w, line, c))
    return out


def joins(sents: list[tuple[int, int, str]], min_words: int) -> list[dict]:
    """節をつないだらしい文と、 最初の comma の前に長い句を置いた文 (min_words 語以上、 原稿の順)。"""
    out = []
    for w, line, t in sents:
        k = len(JOIN.findall(t))
        lead = re.match(r"^([^,]{0,200}),", t)
        long_lead = bool(lead) and len(lead.group(1).split()) >= LONG_LEAD_WORDS
        if w >= min_words and (k or long_lead):
            out.append({"words": w, "line": line, "joins": k, "long_lead": long_lead, "text": t})
    return out


def summarize(path: Path, macros: list[str], thresholds: list[int], joins_min: int | None = None) -> dict:
    s = sentences(path, macros)
    ws = sorted(w for w, _, _ in s)
    if not ws:
        return {"file": str(path), "sentences": 0}
    r = {
        "file": str(path), "sentences": len(ws), "median": statistics.median(ws),
        "mean": round(sum(ws) / len(ws), 1), "longest": ws[-1],
        "over": {str(th): sum(1 for w in ws if w > th) for th in thresholds},
        "items": [{"words": w, "line": line, "text": c} for w, line, c in sorted(s, reverse=True)],
    }
    if joins_min is not None:
        r["joins"] = joins(s, joins_min)
    return r


def selftest() -> int:
    long_sentence = " ".join(["word"] * 45) + "."
    body = ("\\documentclass{article}\n% preamble comment\n\\begin{document}\n"
            "This is a short sentence with Ref.~\\cite{x} inside it. "
            "We cite Eq.~\\eqref{e1} and $a+b$ here as single words.\n"
            "\\begin{equation} x = 1. Y = 2. \\end{equation}\n"
            "Consider the relation \\al{ alpha + beta + gamma + delta + epsilon + zeta } which is written as a macro.\n"
            "% a commented line. With dots.\n\n"
            "It " + long_sentence + "\n\\end{document}\n")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.tex"
        p.write_text(body, encoding="utf-8")
        plain = summarize(p, [], [40])
        withm = summarize(p, ["al"], [40])
    ok = True
    # 文: (1) short (2) We cite (3) Consider ... (4) It word×45。 equation の中の点では切らない、 コメント行は数えない
    if plain["sentences"] != 4 or withm["sentences"] != 4:
        print(f"FAIL sentences = {plain['sentences']} / {withm['sentences']} (want 4 / 4)"); ok = False
    cons = lambda r: next(it["words"] for it in r["items"] if it["text"].startswith("Consider"))
    if cons(plain) != cons(withm) + 6:  # --display-macro が無いと \al の中の 6 語が文に数えられる
        print(f"FAIL --display-macro: {cons(plain)} vs {cons(withm)} (want +6)"); ok = False
    if withm["over"]["40"] != 1 or withm["longest"] != 46:
        print(f"FAIL long sentence: over40={withm['over']['40']} longest={withm['longest']}"); ok = False
    first = min(withm["items"], key=lambda it: it["line"])
    if "Ref." not in first["text"] or first["line"] not in (3, 4):  # 略語の点で切らない、 行は文の始まりの概ね
        print(f"FAIL abbreviation / line: {first}"); ok = False
    jbody = ("\\begin{document}\n"
             "The sample is heated once in the oven, and the color is checked after every minute of the run. "
             "We use the flour, the sugar, and the butter in every batch of the recipe here. "
             "Water boils near the top of the pot and steam leaves the lid from many places at once. "
             "After the last step of the long procedure in the corner of the old laboratory, the result is written down.\n"
             "\\end{document}\n")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "j.tex"
        p.write_text(jbody, encoding="utf-8")
        hits = summarize(p, [], [40], joins_min=10)["joins"]
    got = [(h["text"].split()[0], h["joins"], h["long_lead"]) for h in hits]
    # 1 = 2 節を comma + and でつないだ文 / 2 = 名詞の並列 (拾う = 誤検出の型) / 3 = comma の無い文は拾わない / 4 = 前置の長い句
    if got != [("The", 1, False), ("We", 1, False), ("After", 0, True)]:
        print(f"FAIL --joins: {got}"); ok = False
    print("selftest:", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--over", type=int)
    ap.add_argument("--display-macro", action="append", default=[], metavar="NAME")
    ap.add_argument("--thresholds", default="30,40,50,60,80")
    ap.add_argument("--joins", action="store_true", help="list sentences that join independent clauses or open with a long phrase")
    ap.add_argument("--joins-min", type=int, default=20, metavar="N", help="with --joins: only sentences of at least N words")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.files:
        ap.error("file を 1 つ以上")
    ths = [int(x) for x in a.thresholds.split(",") if x.strip()]
    results = []
    for f in a.files:
        p = Path(f)
        if not p.is_file():
            print(f"{f}: file が無い", file=sys.stderr)
            return 2
        results.append(summarize(p, a.display_macro, ths, a.joins_min if a.joins else None))
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0
    for r in results:
        if not r["sentences"]:
            print(f"== {r['file']}: 文が 0"); continue
        print(f"== {r['file']}: {r['sentences']} 文, 中央値 {r['median']} 語, 平均 {r['mean']}, 最長 {r['longest']}")
        for th, k in r["over"].items():
            print(f"   {th} 語超: {k} ({100 * k / r['sentences']:.0f}%)")
        if a.over is not None:
            for it in r["items"]:
                if it["words"] > a.over:
                    print(f"   {it['words']:3d} 語  l.{it['line']}: {it['text'][:100]}…")
        if "joins" in r:
            print(f"   節をつないだ文・前置の長い文の候補 ({a.joins_min} 語以上): {len(r['joins'])}")
            for it in r["joins"]:
                flag = (f"C{it['joins']}" if it["joins"] else "  ") + (" L" if it["long_lead"] else "  ")
                print(f"   l.{it['line']:<5d} {it['words']:3d} 語 {flag}  {it['text'][:100]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
