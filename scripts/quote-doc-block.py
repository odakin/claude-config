#!/usr/bin/env python3
"""quote-doc-block.py — 規約・規則の markdown から、 節 (anchor・見出し)・箇条の 1 項・その中の引用の塊を逐語で抜き、 依頼の文に逐語で入っているかを確かめる (別の agent への依頼に規約の指示を要約せず差し込むため、 --selftest)。

なぜ存在するか: 批判役への依頼に規約の初回の指示を「入れる」 規則があったのに、 依頼を書いた者が要約して写し、
指示の句 (「複数の指摘は一つずつ扱い」 ほか) が落ちた (実測)。 落ちたのは写す段なので、 人が写さず道具が差し込み、
出す前に逐語で入ったかを道具が確かめる。 規約 = conventions/rebuttal-letter.md#answer-fit-check の 1。

塊の選び方 (どれか 1 つ):
  --anchor ID    = `<a id="ID">` のある行。 見出しの行なら、 同じか上の位の次の見出しまで。 箇条の行なら、 その項の終わりまで。
                   段落の中なら、 その段落の終わりまで。
  --heading 文字 = その文字を含む見出しの節。
  --item 文字    = その文字を含む箇条の 1 項 (行頭の `-`・`*`・`1.` から、 次の同じ深さの項・見出し・空行の後の地の文まで)。
                   --heading・--item の文字が 2 つ以上の行に当たれば止まる (exit 1) = その塊にだけある句で選ぶ
                   (日付や file 名は、 後から足した別の項にも出る)。
  --part quote   = 選んだ塊の中の引用 (`>` で始まる行) だけを、 `>` を外して返す (既定)。 --part body = 塊の全部 (見出しの行を除く)。
使い方:
  python3 quote-doc-block.py extract --doc conventions/rebuttal-letter.md --anchor answer-fit-critic-instructions
  python3 quote-doc-block.py check --doc <md> --anchor <id> --in <依頼の文の file>     (逐語で入っていなければ exit 1)
  python3 quote-doc-block.py --selftest
比べ方: 空白・改行の並びを 1 つの空白に寄せ、 行頭の `> ` を外して、 塊の全体が依頼の文の部分文字列かを見る
(入っていなければ、 最初に見つからない行を出す)。 字の違い (句読点・語の言い換え) は寄せない。
終了値: 0 = 抜けた / 入っている、 1 = 塊が見つからない / 入っていない、 2 = 使い方の誤り。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s")
ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+\.)\s")


def _section_from(lines: list[str], i: int) -> list[str]:
    m = HEADING.match(lines[i])
    level = len(m.group(1))
    out = []
    for j in range(i + 1, len(lines)):
        h = HEADING.match(lines[j])
        if h and len(h.group(1)) <= level:
            break
        out.append(lines[j])
    return out


def _item_from(lines: list[str], i: int) -> list[str]:
    m = ITEM.match(lines[i])
    indent = len(m.group(1)) if m else 0
    out = [lines[i]]
    blank = False
    for j in range(i + 1, len(lines)):
        ln = lines[j]
        if HEADING.match(ln):
            break
        mm = ITEM.match(ln)
        if mm and len(mm.group(1)) <= indent:
            break
        if not ln.strip():
            blank = True
            out.append(ln)
            continue
        lead = len(ln) - len(ln.lstrip())
        if blank and lead <= indent and not ln.lstrip().startswith(">"):
            break
        blank = False
        out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return out


def _paragraph_from(lines: list[str], i: int) -> list[str]:
    out = []
    for j in range(i, len(lines)):
        if not lines[j].strip():
            break
        out.append(lines[j])
    return out


class Ambiguous(ValueError):
    """選ぶ文字が 2 つ以上の見出し・箇条に当たった (どれを抜くか決められない)。"""


def select(md: str, *, anchor: str | None = None, heading: str | None = None, item: str | None = None) -> list[str] | None:
    """塊を 1 つ選ぶ。 --heading・--item の文字が 2 つ以上の見出し・箇条の行に当たれば Ambiguous を上げる
    (最初の 1 つを黙って選ぶと、 後から足した別の項が同じ語を含んだとき違う塊を抜く = 実測)。"""
    lines = md.split("\n")
    hits = []
    for i, ln in enumerate(lines):
        if anchor is not None and (f'<a id="{anchor}"' in ln or f"<a id='{anchor}'" in ln):
            hits.append(i)
        elif heading is not None and HEADING.match(ln) and heading in ln:
            hits.append(i)
        elif item is not None and ITEM.match(ln) and item in ln:
            hits.append(i)
    if not hits:
        return None
    if len(hits) > 1:
        shown = "; ".join(f"行 {i + 1}: {lines[i].strip()[:60]}" for i in hits[:5])
        raise Ambiguous(f"{len(hits)} か所に当たる ({shown})。 その塊にだけある句で選ぶ")
    i = hits[0]
    ln = lines[i]
    if HEADING.match(ln):
        return _section_from(lines, i)
    if ITEM.match(ln):
        return _item_from(lines, i)
    return _paragraph_from(lines, i)


def part_of(block: list[str], part: str) -> str:
    if part == "body":
        return "\n".join(block).strip("\n")
    q = [re.sub(r"^\s*>\s?", "", ln) for ln in block if ln.lstrip().startswith(">")]
    return "\n".join(q).strip("\n")


def extract(md: str, *, part: str = "quote", **sel) -> str | None:
    block = select(md, **sel)
    if block is None:
        return None
    text = part_of(block, part)
    return text if text.strip() else None


def _norm(s: str) -> str:
    s = "\n".join(re.sub(r"^\s*>\s?", "", ln) for ln in s.split("\n"))
    return re.sub(r"\s+", " ", s).strip()


def contains_verbatim(haystack: str, block: str) -> tuple[bool, str | None]:
    """塊の全体が haystack に逐語で入っているか。 入っていなければ、 最初に見つからない行を返す。"""
    h, b = _norm(haystack), _norm(block)
    if b in h:
        return True, None
    for ln in block.split("\n"):
        n = _norm(ln)
        if n and n not in h:
            return False, ln.strip()
    return False, "(行は全部あるが、 並びか間の字が違う)"


SELF_MD = """# Title

## <a id="first"></a>First section

Some text.

> 1. Read the two files.
> 2. Judge each paragraph one by one.

After the quote.

### Sub

More.

## Second

- item one
- **comparison**: check that both words are of the same kind.
  It continues here.
- item three
"""


def selftest() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + msg)
        ok = ok and cond
    q = extract(SELF_MD, anchor="first")
    check(q == "1. Read the two files.\n2. Judge each paragraph one by one.", "anchor の節から引用の塊を抜く")
    body = extract(SELF_MD, anchor="first", part="body")
    check(body is not None and "### Sub" in body and "## Second" not in body, "節は下の位の見出しを含み、 同じ位で止まる")
    it = extract(SELF_MD, item="comparison", part="body")
    check(it is not None and it.endswith("It continues here.") and "item three" not in it, "箇条の 1 項を続きの行ごと抜く")
    check(extract(SELF_MD, heading="Second", part="body") is not None, "見出しの文字で節を選ぶ")
    check(extract(SELF_MD, anchor="missing") is None, "無い anchor は None")
    request = "Please do this:\n1. Read the two files.\n2. Judge each paragraph\none by one.\nThanks."
    check(contains_verbatim(request, q)[0], "改行の位置が違っても逐語なら入っている")
    short = "Please do this:\n1. Read the two files.\n2. Judge the paragraphs."
    good, miss = contains_verbatim(short, q)
    check(not good and miss == "2. Judge each paragraph one by one.", "要約した行を最初に見つからない行として出す")
    two = SELF_MD + "- another item that also says comparison\n"
    try:
        extract(two, item="comparison", part="body")
        check(False, "2 つの箇条に当たる文字は止める")
    except Ambiguous:
        check(True, "2 つの箇条に当たる文字は止める")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("cmd", choices=["extract", "check"])
    ap.add_argument("--doc", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--anchor")
    g.add_argument("--heading")
    g.add_argument("--item")
    ap.add_argument("--part", choices=["quote", "body"], default="quote")
    ap.add_argument("--in", dest="infile", type=Path, help="check: 依頼の文の file")
    a = ap.parse_args(argv)
    try:
        text = extract(a.doc.read_text(encoding="utf-8"), part=a.part, anchor=a.anchor, heading=a.heading, item=a.item)
    except Ambiguous as e:
        print(f"✗ 塊を 1 つに決められない ({a.doc}): {e}", file=sys.stderr)
        return 1
    if text is None:
        print(f"✗ 塊が見つからない ({a.doc}、 {a.anchor or a.heading or a.item}、 part={a.part})", file=sys.stderr)
        return 1
    if a.cmd == "extract":
        print(text)
        return 0
    if not a.infile:
        print("check には --in が要る", file=sys.stderr)
        return 2
    good, miss = contains_verbatim(a.infile.read_text(encoding="utf-8"), text)
    print(("✓ 逐語で入っている" if good else f"✗ 逐語で入っていない。 最初に見つからない行: {miss}")
          + f" ({a.anchor or a.heading or a.item})")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
