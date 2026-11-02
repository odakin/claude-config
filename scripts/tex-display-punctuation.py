#!/usr/bin/env python3
"""LaTeX 原稿の display 数式の末尾の句読点と、 直後の散文の頭が合わない所を挙げる (式は書き換えず、 散文の側を直すための候補)。

なぜ (実測): 文を分ける・display の後ろの節を消す・文を移す編集の後に、 display の末尾が period なのに次の文が
小文字の where / which で始まる所 (文が途中で切れている) が、 盲検と AI の監査を通った原稿に 2 か所残っていた。
display の中は式なので句読点も式の一部で、 散文を直す pass では書き換えない = 散文の側を合わせる
(conventions/paper-audit.md#relocation-rebinding-sweep の (h))。 目で探すと display の数だけ見落とす。

挙げる 3 型 (どれも候補 = 1 件ずつ読む):
  PERIOD->lower  末尾が `.` で、 次の語が小文字で始まる (where / which / and …) = 文が切れている
  COMMA->Upper   末尾が `,` で、 次の語が大文字で始まる = 新しい文が comma の後に続いている
                 (Eq. / Eqs. / Fig. / Sec. / Ref. / Table / Appendix などの参照の語と、 1 文字の大文字は除く)
  NONE->Upper    末尾に句読点が無く、 次の語が大文字で始まる = period の落ちの候補
次が LaTeX の command (`\\section` / `\\begin{figure}` など)・数式・空の所は挙げない。

display = 環境 (equation / align / gather / multline / eqnarray / flalign / alignat、 * つきも) と `\\[ … \\]`、
`--display-macro NAME` (繰り返し可) の `\\NAME{…}` (括弧の釣り合いで閉じを探す。 `\\{` `\\}` `\\\\` は 2 字で 1 つ =
括弧に数えない = `\\phantom{…\\Big\\{}` の閉じない `\\{` で display が文書の終わりまで伸びない)。
末尾の判定は `\\label{…}` `\\nonumber` `\\notag` `\\nn` と空白・`\\\\` を除いた最後の文字。 `%` コメントは除く (行番号は保つ)。

使い方:
    python3 tex-display-punctuation.py paper.tex [more.tex ...] [--display-macro al] [--display-macro als]
    python3 tex-display-punctuation.py --selftest
exit: 0 = 候補なし / 1 = 候補あり / 2 = 入力の file が無い・読めない。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ENVS = ("equation", "align", "gather", "multline", "eqnarray", "flalign", "alignat")
REF_WORDS = {"Eq.", "Eqs.", "Fig.", "Figs.", "Sec.", "Secs.", "Ref.", "Refs.", "Table", "Tables",
             "Appendix", "Appendices", "App.", "Chap.", "Chapter", "Section", "Figure", "Equation"}
TRAILING = re.compile(r"(\\label\{[^}]*\}|\\nonumber\b|\\notag\b|\\nn\b|\\\\|\s)+$")
# 句点を閉じの手前に置く書き方 (`\text{(IBP).}`・`\tx{etc.}`・`… . \end{cases}`・`R^2. \;}`) を読むため、
# 末尾の閉じ括弧・`\end{…}`・`\right` の区切り・間隔の command も外してから最後の文字を見る
CLOSERS = re.compile(r"(\\label\{[^}]*\}|\\nonumber\b|\\notag\b|\\nn\b|\\\\|\\end\{[A-Za-z*]+\}"
                     r"|\\right(?:\\[{}|]|[.)\]|])|\\[,;:! ]|\\q?quad\b|\}|&|\s)+$")


def strip_comments(t: str) -> str:
    """`%` から行末までを同じ長さの空白に置き換える (`\\%` は残す)。 位置 = 行番号の対応を保つ。"""
    out = []
    for line in t.split("\n"):
        m = re.search(r"(?<!\\)%", line)
        out.append(line[:m.start()] + " " * (len(line) - m.start()) if m else line)
    return "\n".join(out)


def close_brace(t: str, i: int) -> int:
    """t[i] == '{' に対応する '}' の位置。 `\\` の後の 1 字は数えない。 閉じが無ければ -1。"""
    depth, j = 0, i
    while j < len(t):
        c = t[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def displays(t: str, macros: list[str]) -> list[tuple[int, int, str]]:
    """(display の始まり, 終わりの次の位置, 中身) の一覧を位置の順に。"""
    out = []
    env_re = re.compile(r"\\begin\{(" + "|".join(ENVS) + r")(\*?)\}")
    for m in env_re.finditer(t):
        end_tag = "\\end{" + m.group(1) + m.group(2) + "}"
        e = t.find(end_tag, m.end())
        if e >= 0:
            out.append((m.start(), e + len(end_tag), t[m.end():e]))
    for m in re.finditer(r"\\\[", t):
        e = t.find("\\]", m.end())
        if e >= 0:
            out.append((m.start(), e + 2, t[m.end():e]))
    for name in macros:
        for m in re.finditer(r"\\" + re.escape(name) + r"\{", t):
            b = m.end() - 1
            e = close_brace(t, b)
            if e >= 0:
                out.append((m.start(), e + 1, t[b + 1:e]))
    out.sort()
    # 入れ子 (display の中の display) は外側だけを残す
    kept, last_end = [], -1
    for s, e, body in out:
        if s >= last_end:
            kept.append((s, e, body))
            last_end = e
    return kept


def last_mark(body: str) -> str:
    b = CLOSERS.sub("", body)
    return b[-1:] if b else ""


def next_word(t: str, pos: int) -> str:
    m = re.match(r"\s*(\S+)", t[pos:])
    return m.group(1) if m else ""


def classify(mark: str, word: str) -> str:
    if not word or word[0] in "\\$" or not word[0].isalpha():
        return ""
    if mark == "." and word[0].islower():
        return "PERIOD->lower"
    if mark == "," and word[0].isupper():
        head = re.match(r"[A-Za-z]+\.?", word).group(0)  # `Eq.~\eqref{…}` → `Eq.`
        if head in REF_WORDS or len(head.rstrip(".")) == 1:
            return ""
        return "COMMA->Upper"
    if mark not in ".,;:" and word[0].isupper():
        return "NONE->Upper"
    return ""


def scan(text: str, macros: list[str]) -> list[tuple[int, str, str, str]]:
    t = strip_comments(text)
    found = []
    for s, e, body in displays(t, macros):
        mark = last_mark(body)
        word = next_word(t, e)
        kind = classify(mark, word)
        if kind:
            line = t.count("\n", 0, s) + 1
            tail = re.sub(r"\s+", " ", TRAILING.sub("", body))[-40:]
            found.append((line, kind, tail, word))
    return found


def selftest() -> int:
    sample = (
        "Text before.\n"
        "\\al{a &= b.\\label{eq:a}}\n"                     # 1: period -> lower 'where' = 挙げる
        "where $a$ is the length.\n"
        "\\al{c &= d,\\label{eq:c}}\n"                     # 2: comma -> 'The' = 挙げる
        "The next sentence starts here.\n"
        "\\al{e &= f,}\n"                                  # 3: comma -> 'Eq.' = 挙げない
        "Eq.~\\eqref{eq:a} gives it.\n"
        "\\al{g &= h\\label{eq:g}}\n"                      # 4: none -> lower 'is' = 挙げない
        "is the definition.\n"
        "\\al{f &= \\exp\\Big\\{ a\\nn &\\phantom{= \\exp\\Big\\{} + c \\Big\\}.}\n"  # 5: \\{ を数えない = 閉じが見つかる
        "The text goes on.\n"
        "\\begin{equation} k = l \\end{equation}\n"         # 6: none -> 'Here' = 挙げる
        "Here we stop.\n"
        "\\al{m &= n.}\n"                                  # 7: 次が command = 挙げない
        "\\section{Next}\n"
        "% \\al{x &= y.} where  (comment = 数えない)\n"
        "\\al{p &= q &&\\text{(by parts).}}\n"             # 8: 句点が text の中 = 挙げない
        "Hence the rest.\n"
        "\\al{r = \\begin{cases} 1 & \\tx{if } s,\\\\ 0 & \\tx{otherwise.} \\end{cases}}\n"  # 9: cases の中の句点 = 挙げない
        "We go on.\n"
    )
    got = [(line, kind, word) for line, kind, _tail, word in scan(sample, ["al"])]
    want = [(2, "PERIOD->lower", "where"), (4, "COMMA->Upper", "The"), (12, "NONE->Upper", "Here")]
    ok = got == want
    if not ok:
        print(f"FAIL: got {got}\n      want {want}")
    print("selftest:", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--display-macro", action="append", default=[], metavar="NAME")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.files:
        ap.error("file を渡す (または --selftest)")
    total = 0
    for f in a.files:
        p = Path(f)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"読めない: {f}: {exc}", file=sys.stderr)
            return 2
        for line, kind, tail, word in scan(text, a.display_macro):
            print(f"{f}:{line}: {kind}: …{tail} | 次: {word[:40]}")
            total += 1
    print(f"候補: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
