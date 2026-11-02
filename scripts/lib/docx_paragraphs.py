#!/usr/bin/env python3
"""docx_paragraphs.py — docx の XML (word/document.xml ほか) を段落に切る共有の部品。 自己終了の空段落 `<w:p .../>` を 1 段落として数え、 textbox の中の段落を外の段落と重ねない。

WHY (conventions/office-automation.md#docx-paragraph-split):
  様式の記入行は自己終了の空段落 `<w:p w14:paraId="…"/>` であることが多い。 その場で書いた正規表現
  `<w:p[ >].*?</w:p>` (や `<w:p(?:\\s[^>]*)?>.*?</w:p>`) は開きの tag の `[^>]*` が末尾の `/` まで食べるので、
  自己終了の段落を開きの tag と読み、 次の段落の `</w:p>` までを 1 つに抱き込む。 script からは記入行が見えず、
  記入の値を新しい段落として足すことになり、 行の送りが固定の様式 (docGrid type="lines") では 1 行ぶん頁を押す
  (実測: 1 頁の様式が 2 頁にはみ出した)。 段落の数も 1 つ少なく見えるので、 雛形との比較も黙って通る。
  正規表現を毎回書かずに、 この部品で切る。

WHAT:
  paragraphs(xml) -> [Para]          全段落 (textbox の中も)、 開きの位置の順。 Para = index / start / end /
                                     self_closing / container / para_id / nested / text
  top_level(xml) -> [Para]           外側の段落だけ (重ならない = 書き換えに使う)
  replace(xml, {i: new_xml}) -> xml  top_level の i 番目を差し替える (他の byte はそのまま)
  counts(xml) -> {container: 数}     入れ物 (本文 / 表の cell / textbox) ごとの段落の数 (自己終了を含む)
  runs(para_xml) -> [str]            段落の run (textbox の中の段落の run は除く)
  read_part(docx, part) -> str       zip から XML を読む (既定 = word/document.xml)
  PARA_RE                            どうしても正規表現 1 本で済ませたい時の形 (自己終了を先に試す)。
                                     ⚠️ textbox の中の段落とは重なる = 書き換えには top_level を使う

  入れ物の名前: 本文 = "body"、 表の cell = "body/tbl0/tr1/tc2" (入れ子の表は続けて伸びる)、 textbox =
  "body/p<paraId>/txbx0" (paraId が無ければ "p")。

CLI:
  python3 docx_paragraphs.py dump <file.docx> [--part word/header1.xml]   # 番号・入れ物・自己終了・paraId・字
  python3 docx_paragraphs.py count <file.docx>                            # 入れ物ごとの数
  python3 docx_paragraphs.py --selftest

使い方 (記入の script):
  import sys; sys.path.insert(0, os.path.expanduser("~/Claude/claude-config/scripts/lib"))
  from docx_paragraphs import read_part, top_level, replace
  xml = read_part("雛形.docx"); ps = top_level(xml)
  xml = replace(xml, {ps[34].index_top: new_paragraph_xml})
"""
from __future__ import annotations

import re
import sys
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import unescape

# 自己終了を先に試す。 開きの tag の属性は `/` で終わらない形に限る (= 自己終了を開きと読まない)
PARA_RE = r"<w:p(?=[\s/>])[^>]*/>|<w:p(?=[\s>])(?:\s[^>]*[^/>])?>.*?</w:p>"

_TOKEN = re.compile(r"<(/?)(w:p|w:tbl|w:tr|w:tc|w:txbxContent)(?=[\s/>])([^>]*)>")
_PARA_ID = re.compile(r'\bw14:paraId="([^"]*)"')
_T = re.compile(r"<w:t(?=[\s>/])[^>]*?(?:/>|>(.*?)</w:t>)", re.S)
_TAB = re.compile(r"<w:tab(?=[\s/>])[^>]*/>")
_RUN = re.compile(r"<w:r(?=[\s>])[^>]*>.*?</w:r>", re.S)
_SHORT = {"w:tbl": "tbl", "w:tr": "tr", "w:tc": "tc", "w:txbxContent": "txbx"}


@dataclass
class Para:
    index: int            # 全段落の中の番号 (開きの順)
    start: int
    end: int
    self_closing: bool
    container: str
    para_id: str
    nested: bool          # 別の段落の中 (textbox) に在る
    text: str = ""
    index_top: int = -1   # 外側の段落の中の番号 (nested なら -1)


def _attrs_self_closing(attrs: str) -> bool:
    return attrs.rstrip().endswith("/")


def paragraphs(xml: str) -> list[Para]:
    """全段落を開きの位置の順に返す。 閉じの無い段落 (壊れた XML) は文書の末尾までとする。"""
    frames: list[dict] = [{"name": "body", "counts": {}, "kind": "body"}]
    open_paras: list[Para] = []
    out: list[Para] = []

    def child(kind: str) -> str:
        f = frames[-1]
        n = f["counts"].get(kind, 0)
        f["counts"][kind] = n + 1
        return f"{_SHORT[kind]}{n}"

    for m in _TOKEN.finditer(xml):
        closing, tag, attrs = m.group(1), m.group(2), m.group(3)
        if tag == "w:p":
            if closing:
                if open_paras:
                    p = open_paras.pop()
                    p.end = m.end()
                    # 段落の frame を閉じる (段落の中で開いた frame は textbox の閉じで既に外れている)
                    while len(frames) > 1 and frames[-1]["kind"] != "p":
                        frames.pop()
                    if len(frames) > 1:
                        frames.pop()
                continue
            container = "/".join(f["name"] for f in frames)
            pid_m = _PARA_ID.search(attrs)
            p = Para(index=len(out), start=m.start(), end=m.end(), self_closing=_attrs_self_closing(attrs),
                     container=container, para_id=pid_m.group(1) if pid_m else "", nested=bool(open_paras))
            out.append(p)
            if not p.self_closing:
                open_paras.append(p)
                frames.append({"name": f"p{p.para_id}" if p.para_id else "p", "counts": {}, "kind": "p"})
            continue
        if closing:
            # 対応する frame まで閉じる
            for k in range(len(frames) - 1, 0, -1):
                if frames[k]["kind"] == tag:
                    del frames[k:]
                    break
            continue
        if _attrs_self_closing(attrs):
            child(tag)  # 空の表・cell も番号は進める
            continue
        name = child(tag)
        frames.append({"name": name, "counts": {}, "kind": tag})
    for p in open_paras:  # 閉じの無い段落
        p.end = len(xml)
    _fill_text(xml, out)
    top = 0
    for p in out:
        if not p.nested:
            p.index_top = top
            top += 1
    return out


def _strip_nested(xml: str, p: Para, all_paras: list[Para]) -> str:
    """段落の XML から、 その中の (textbox の) 段落を除いた字列。"""
    body = xml[p.start:p.end]
    inner = [q for q in all_paras if q is not p and p.start < q.start and q.end <= p.end]
    if not inner:
        return body
    pieces, cur = [], p.start
    for q in sorted(inner, key=lambda q: q.start):
        if q.start < cur:
            continue
        pieces.append(xml[cur:q.start])
        cur = q.end
    pieces.append(xml[cur:p.end])
    return "".join(pieces)


def _text_of(fragment: str) -> str:
    fragment = _TAB.sub("<w:t>\t</w:t>", fragment)
    return unescape("".join(m.group(1) or "" for m in _T.finditer(fragment)), {"&quot;": '"', "&apos;": "'"})


def _fill_text(xml: str, ps: list[Para]) -> None:
    for p in ps:
        p.text = "" if p.self_closing else _text_of(_strip_nested(xml, p, ps))


def top_level(xml: str) -> list[Para]:
    return [p for p in paragraphs(xml) if not p.nested]


def para_xml(xml: str, p: Para, all_paras: list[Para] | None = None) -> str:
    """段落の XML (textbox の中の段落は除く)。"""
    return _strip_nested(xml, p, all_paras if all_paras is not None else paragraphs(xml))


def runs(fragment: str) -> list[str]:
    """段落の XML から run を順に返す。 textbox の中の段落は先に para_xml で除いておく。"""
    return _RUN.findall(fragment)


def replace(xml: str, mapping: dict[int, str]) -> str:
    """top_level の番号 → 新しい段落の XML。 番号が無ければ KeyError (黙って足さない)。"""
    tops = top_level(xml)
    for i in mapping:
        if not 0 <= i < len(tops):
            raise KeyError(f"段落 {i} は無い (外側の段落は {len(tops)} 個)")
    out, cur = [], 0
    for p in tops:
        if p.index_top in mapping:
            out.append(xml[cur:p.start])
            out.append(mapping[p.index_top])
            cur = p.end
    out.append(xml[cur:])
    return "".join(out)


def counts(xml: str) -> dict[str, int]:
    c: dict[str, int] = {}
    for p in paragraphs(xml):
        c[p.container] = c.get(p.container, 0) + 1
    return c


def read_part(docx, part: str = "word/document.xml") -> str:
    with zipfile.ZipFile(docx) as z:
        return z.read(part).decode("utf-8")


def _cli(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--selftest":
        return _selftest()
    cmd, rest = argv[0], argv[1:]
    part = "word/document.xml"
    if "--part" in rest:
        k = rest.index("--part")
        part = rest[k + 1]
        rest = rest[:k] + rest[k + 2:]
    if cmd not in ("dump", "count") or len(rest) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    xml = read_part(rest[0], part)
    if cmd == "count":
        for k, v in counts(xml).items():
            print(f"{v:5d}  {k}")
        print(f"{len(paragraphs(xml)):5d}  (全部、 自己終了を含む)")
        return 0
    for p in paragraphs(xml):
        flag = "/>" if p.self_closing else "  "
        nest = "↳" if p.nested else " "
        print(f"{p.index:4d} {nest} {flag} {p.para_id or '-':8s} {p.container:24s} {p.text[:60]!r}")
    return 0


def _selftest() -> int:
    xml = ("<w:body>"
           f'<w:p w14:paraId="A1"><w:r><w:t>見出し</w:t></w:r></w:p>'
           f'<w:p w14:paraId="A2"/>'                                     # 自己終了 (記入行)
           f'<w:p w14:paraId="A3"><w:r><w:t>次の見出し</w:t></w:r></w:p>'
           "<w:p/>"
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>甲</w:t></w:r></w:p><w:p/></w:tc>'
           "<w:tc><w:p><w:r><w:t>乙</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
           '<w:p w14:paraId="B1"><w:r><w:pict><w:txbxContent><w:p><w:r><w:t>枠の字</w:t></w:r></w:p>'
           "</w:txbxContent></w:pict></w:r><w:r><w:t>外の字</w:t></w:r></w:p>"
           "</w:body>")
    ps = paragraphs(xml)
    tops = top_level(xml)
    naive = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    regex = re.findall(PARA_RE, xml, re.S)
    checks = [
        ("全段落 = 9 (自己終了 3 と textbox の中 1 を含む)", len(ps) == 9),
        ("外側の段落 = 8", len(tops) == 8),
        ("自己終了の記入行を 1 段落と読む", ps[1].self_closing and ps[1].para_id == "A2" and ps[1].text == ""),
        ("その次の見出しは別の段落", ps[2].text == "次の見出し"),
        ("素朴な正規表現は記入行を抱き込む (= 1 つ少ない)", sum("A2" in s for s in naive) == 1
         and not any(s.startswith('<w:p w14:paraId="A2"/>') and s.endswith("/>") for s in naive)),
        ("PARA_RE は自己終了を別に拾う", '<w:p w14:paraId="A2"/>' in regex),
        ("表の cell の入れ物", ps[4].container == "body/tbl0/tr0/tc0" and ps[5].container == "body/tbl0/tr0/tc0"
         and ps[6].container == "body/tbl0/tr0/tc1"),
        ("textbox の入れ物と nested", ps[8].nested and ps[8].container == "body/pB1/txbx0" and ps[8].text == "枠の字"),
        ("外の段落の字に textbox の字を混ぜない", ps[7].text == "外の字"),
        ("counts", counts(xml) == {"body": 5, "body/tbl0/tr0/tc0": 2, "body/tbl0/tr0/tc1": 1, "body/pB1/txbx0": 1}),
    ]
    new = replace(xml, {1: f'<w:p w14:paraId="A2"><w:r><w:t>記入</w:t></w:r></w:p>'})
    ps2 = paragraphs(new)
    checks += [
        ("replace は数を変えない", len(ps2) == 9 and ps2[1].text == "記入" and ps2[2].text == "次の見出し"),
        ("replace は他の byte を変えない", new.replace('<w:p w14:paraId="A2"><w:r><w:t>記入</w:t></w:r></w:p>',
                                                    '<w:p w14:paraId="A2"/>') == xml),
    ]
    try:
        replace(xml, {99: "<w:p/>"})
        checks.append(("無い番号は KeyError", False))
    except KeyError:
        checks.append(("無い番号は KeyError", True))
    checks.append(("run は textbox の外だけ", len(runs(para_xml(xml, ps[7], ps))) == 2))
    ok = True
    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"\n{'ALL PASS' if ok else 'FAILURES'} ({sum(p for _, p in checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
