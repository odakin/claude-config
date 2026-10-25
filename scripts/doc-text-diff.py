#!/usr/bin/env python3
"""同じ文書の 2 つの版 (docx / pdf / md / txt の任意の組) の文字の差を出す — 改訂版を verbatim で取り込む前後の照合用。--selftest 内蔵 (network 不要)。

なぜ層1 にあるか
----------------
他人が書いた文書の改訂版を受け取り、 手元の写し (markdown など) に一字一句そのまま当てる作業は繰り返し来る。
そのたびに使い捨ての照合を書くと、 (a) 形式ごとの抽出 (docx の表・PDF の行の並び) を毎回書き直し、
(b) 「照合して差 0」 と記録した根拠が file に残らない (実測)。
取り込みの手順 = 古い版と新しい版の差を出す → 差だけを写しに当てる → 写しと新しい版を照合して、 残る差が
意図した置き換え (写しの側だけの注記など) だけであることを確かめる。 2 回とも本 script で回せる。

比べ方
------
- 既定 = 空白 (ASCII の空白・改行・全角空白) を全部除いて、 文字単位で比べる (difflib)。
  形式の違い (PDF の改行・docx の段落・markdown の記号) を吸収し、 文字の足し引きだけを出す。
- `--whitespace` = 空白の連なりを 1 個に詰めて比べ、 **空白だけが違う箇所**を出す。
  行・段落の継ぎ目に当たる差は既定で隠す (`--show-line-end` で出す)。
  ⚠️ PDF の空白は信用できない: PyMuPDF は既定で字の間の見た目の隙間に空白を補う。
  Word が和文と半角数字の間に入れる自動の空き (和欧間) も空白として出る (実測)。
  PDF 側は `--pdf-real-spaces` (= TEXT_INHIBIT_SPACES、 PDF に実在する空白の字だけ) と併用する。
  それでも全角空白・行末の空白は PDF から確定できないことがある = 空白まで要るなら docx をもらう。

形式ごとの抽出
--------------
- docx: 本文の段落と表を出現順に (表は行ごとにセルを空白で連結)。 標準 library だけ (zip + XML)。
  削除の変更履歴 (w:delText) は入らない。 リスト記号 (自動の番号・黒丸) は字に入らない。
  黄色などのマーカー (`w:highlight`) と黒以外の色の字 (`w:color`) の run の数も数える。
- pdf: 頁ごとに行を y → x の順に並べ直す (素の `get_text()` は格納順で、 表・多段組で順が崩れる =
  `conventions/office-automation.md#pdf-table-layout-aware-reading`)。 PyMuPDF が要る。
  黄色っぽい塗りの矩形 (Word のマーカーは PDF では塗りの矩形になる) と、 黒以外の色の字の span を数える
  (空白だけの span は数えない)。 行頭の黒丸 (• ● ◦ ▪) はリスト記号として除く。
- md: 見出し・引用・リスト・表の罫線行・強調の記号・link の記法・`<br>`・HTML の tag を除いて字だけにする
  (tag の中の字は残す)。
- txt: そのまま。

使い方
------
  doc-text-diff.py old.docx new.pdf                 # 文字の差 (空白を除く)
  doc-text-diff.py copy.md new.pdf --context 20     # 取り込んだ後の照合
  doc-text-diff.py old.docx new.pdf --whitespace --pdf-real-spaces
  doc-text-diff.py new.pdf --dump > new.txt         # 抽出だけ (照合の根拠を残すとき)
  doc-text-diff.py old.docx new.pdf --json
  doc-text-diff.py --selftest

出力: 差ごとに 1 行 (`#番号 種類: …前の文脈【A: …】→【B: …】後の文脈…`)、 最後に差の数・一致率・各 file の印
(マーカー・色) の数。 終了値: 差が 0 なら 0、 差があれば 1、 使い方の誤り・読めない file は 2。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(tag: str) -> str:
    return "{%s}%s" % (W_NS, tag)


# ---------------------------------------------------------------- extraction

def _para_text(p) -> str:
    parts = []
    for el in p.iter():
        if el.tag == _w("t"):
            parts.append(el.text or "")
        elif el.tag == _w("tab"):
            parts.append("\t")
        elif el.tag in (_w("br"), _w("cr")):
            parts.append("\n")
    return "".join(parts)


def extract_docx(path: str):
    """docx の本文を出現順の行 (段落・表の行) にする。 返り値 = (行の list, 印の数の dict)。"""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(_w("body"))
    if body is None:
        return [], {"highlight": 0, "color": 0}
    lines: list[str] = []

    def walk(container):
        for child in container:
            if child.tag == _w("p"):
                lines.append(_para_text(child))
            elif child.tag == _w("tbl"):
                for tr in child.iter(_w("tr")):
                    cells = []
                    for tc in tr.findall(_w("tc")):
                        cells.append("".join(_para_text(p) for p in tc.findall(_w("p"))))
                    lines.append(" ".join(cells))
            elif child.tag == _w("sdt"):
                content = child.find(_w("sdtContent"))
                if content is not None:
                    walk(content)

    walk(body)
    marks = {"highlight": 0, "color": 0}
    for r in body.iter(_w("r")):
        rpr = r.find(_w("rPr"))
        if rpr is None or not "".join(t.text or "" for t in r.iter(_w("t"))).strip():
            continue
        hl = rpr.find(_w("highlight"))
        if hl is not None and hl.get(_w("val"), "none") != "none":
            marks["highlight"] += 1
        col = rpr.find(_w("color"))
        if col is not None and col.get(_w("val"), "auto").lower() not in ("auto", "000000"):
            marks["color"] += 1
    return lines, marks


_BULLET = re.compile(r"^\s*[•●◦▪]\s*")


def extract_pdf(path: str, real_spaces: bool = False):
    """PDF の行を頁ごとに y → x の順に並べる。 返り値 = (行の list, 印の数の dict)。"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("doc-text-diff: PDF を読むには PyMuPDF が要る (pip install pymupdf)")
    flags = getattr(fitz, "TEXTFLAGS_DICT", 0)
    if real_spaces:
        flags |= fitz.TEXT_INHIBIT_SPACES
    lines: list[str] = []
    marks = {"highlight": 0, "color": 0}
    with fitz.open(path) as doc:
        for page in doc:
            rows = []
            for b in page.get_text("dict", flags=flags)["blocks"]:
                for ln in b.get("lines", []):
                    text = "".join(s["text"] for s in ln["spans"])
                    for s in ln["spans"]:
                        if s.get("color", 0) != 0 and s["text"].strip():
                            marks["color"] += 1
                    if text.strip():
                        rows.append((ln["bbox"][1], ln["bbox"][0], text))
            rows.sort()
            merged: list[list] = []
            for y, x, text in rows:
                if merged and abs(merged[-1][0] - y) < 2.0:
                    merged[-1][1].append((x, text))
                else:
                    merged.append([y, [(x, text)]])
            for _, parts in merged:
                parts.sort()
                lines.append(_BULLET.sub("", " ".join(t for _, t in parts)))
            for dr in page.get_drawings():
                f = dr.get("fill")
                if f and len(f) >= 3 and f[0] > 0.85 and f[1] > 0.85 and f[2] < 0.4:
                    marks["highlight"] += 1
    return lines, marks


def extract_md(text: str) -> list[str]:
    """markdown の記号を除いて字だけの行にする (tag の中の字は残す)。"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s and set(s) <= set("|-: ") and "-" in s:          # 表の罫線行
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):           # 水平線
            continue
        line, is_heading = re.subn(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*>\s?", "", line)
        if not is_heading:  # 見出しの「1. 」 は見出しの字 (リスト記号でない)
            line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)
        line = re.sub(r"<br\s*/?>", "\n", line, flags=re.I)
        line = re.sub(r"</?[A-Za-z][^>]*>", "", line)
        line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = line.replace("**", "").replace("__", "").replace("`", "")
        line = re.sub(r"(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![*\w])", r"\1", line)
        if line.lstrip().startswith("|"):
            line = re.sub(r"\s*\|\s*", " ", line).strip()
        out.extend(line.split("\n"))
    return out


def extract(path: str, real_spaces: bool = False):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return extract_docx(path)
    if ext == ".pdf":
        return extract_pdf(path, real_spaces)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if ext in (".md", ".markdown"):
        return extract_md(text), {"highlight": 0, "color": 0}
    return text.splitlines(), {"highlight": 0, "color": 0}


# ---------------------------------------------------------------- comparison

def join_chars(lines: list[str]) -> str:
    return "".join(re.sub(r"[\s　]+", "", ln) for ln in lines)


def join_ws(lines: list[str]):
    """空白の連なり (全角は残す) を 1 個に詰めて連結する。 返り値 = (文字列, 行の継ぎ目の位置の集合)。"""
    buf = ""
    joins = set()
    for ln in lines:
        ln = re.sub(r"[ \t\r\n]+", " ", ln)
        if not ln:
            continue
        if buf:
            joins.add(len(buf))
            if buf.endswith(" ") and ln.startswith(" "):
                ln = ln[1:]
        buf += ln
    return buf, joins


def _near(pos_set, lo: int, hi: int) -> bool:
    return any(lo - 1 <= p <= hi + 1 for p in pos_set)


def compare(a_lines, b_lines, whitespace=False, show_line_end=False, context=20, max_seg=200):
    if whitespace:
        a, a_joins = join_ws(a_lines)
        b, b_joins = join_ws(b_lines)
    else:
        a, b = join_chars(a_lines), join_chars(b_lines)
        a_joins = b_joins = set()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    diffs = []
    hidden = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        sa, sb = a[i1:i2], b[j1:j2]
        if whitespace:
            if re.sub(r"\s", "", sa) != re.sub(r"\s", "", sb):
                continue  # 字の差は既定の比べ方で見る
            if not show_line_end and (_near(a_joins, i1, i2) or _near(b_joins, j1, j2)):
                hidden += 1
                continue
        diffs.append({
            "tag": tag, "a": sa[:max_seg], "b": sb[:max_seg],
            "before": a[max(0, i1 - context):i1], "after": a[i2:i2 + context],
            "a_pos": i1, "b_pos": j1,
        })
    return {"diffs": diffs, "ratio": round(sm.ratio(), 4), "len_a": len(a), "len_b": len(b),
            "hidden_line_end": hidden}


def render(res, name_a, name_b, marks_a, marks_b, whitespace) -> str:
    out = []
    for k, d in enumerate(res["diffs"], 1):
        out.append(f"#{k} {d['tag']}: …{d['before']}【A: {d['a']!r}】→【B: {d['b']!r}】{d['after']}…"
                   if whitespace else
                   f"#{k} {d['tag']}: …{d['before']}【A: {d['a']}】→【B: {d['b']}】{d['after']}…")
    mode = "空白だけの差" if whitespace else "字の差 (空白を除く)"
    out.append(f"{mode}: {len(res['diffs'])} 件 / 一致率 {res['ratio']} / A = {name_a} ({res['len_a']} 字) / "
               f"B = {name_b} ({res['len_b']} 字)")
    if whitespace and res["hidden_line_end"]:
        out.append(f"行・段落の継ぎ目に当たる空白の差 {res['hidden_line_end']} 件は隠した (--show-line-end で出す)")
    out.append(f"印: A = マーカー {marks_a['highlight']}・色 {marks_a['color']} / "
               f"B = マーカー {marks_b['highlight']}・色 {marks_b['color']}")
    return "\n".join(out)


# ---------------------------------------------------------------- selftest

def _make_docx(path: str) -> None:
    doc = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}"><w:body>
<w:p><w:r><w:t>架空大学は 1900 年に</w:t></w:r><w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>開校</w:t></w:r><w:r><w:t>した。</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:color w:val="EE0000"/></w:rPr><w:t>注意書き</w:t></w:r><w:r><w:rPr><w:color w:val="EE0000"/></w:rPr><w:t xml:space="preserve"> </w:t></w:r><w:r><w:delText>消した字</w:delText></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>甲</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>乙</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)


def selftest() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + name)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "a.docx")
        _make_docx(p)
        lines, marks = extract_docx(p)
        check("docx: 段落と表を出現順に", lines == ["架空大学は 1900 年に開校した。", "注意書き ", "甲 乙"])
        check("docx: 削除の変更履歴は入らない", all("消した字" not in ln for ln in lines))
        check("docx: マーカー 1・色 1 (空白だけの run は数えない)", marks == {"highlight": 1, "color": 1})

        md = ("# 見出し\n\n## 2. 節\n\n**架空大学**は 1900 年に<mark class=\"x\">開校</mark>した。\n\n"
              "| 列1 | 列2 |\n|---|---|\n| 甲 | 乙 |\n\n---\n\n- [項目](http://example.invalid) の `語`\n*(草稿)*\n")
        got = join_chars(extract_md(md))
        check("md: 記号を除いて字だけ (見出しの番号は残す)", got == "見出し2.節架空大学は1900年に開校した。列1列2甲乙項目の語(草稿)")

        r = compare(["架空大学は1900年に開校した。"], ["架空大学は 1900 年に開学した。"])
        check("字の差: 1 件 (校→学)", len(r["diffs"]) == 1 and r["diffs"][0]["a"] == "校" and r["diffs"][0]["b"] == "学")

        r = compare(["A B"], ["A  B"], whitespace=True)
        check("空白: 連なりは 1 個に詰める", r["diffs"] == [])
        r = compare(["AB"], ["A B"], whitespace=True)
        check("空白: 足された空白を出す", len(r["diffs"]) == 1 and r["diffs"][0]["b"] == " ")
        r = compare(["あいうえお"], ["あいう ", "えお"], whitespace=True)
        check("空白: 行の継ぎ目の差は既定で隠す", r["diffs"] == [] and r["hidden_line_end"] == 1)
        r = compare(["あいうえお"], ["あいう ", "えお"], whitespace=True, show_line_end=True)
        check("空白: --show-line-end で出す", len(r["diffs"]) == 1)

        check("PDF の行頭の黒丸を除く", _BULLET.sub("", "• 項目") == "項目")
        try:
            import fitz  # noqa: F401
            have_fitz = True
        except ImportError:
            have_fitz = False
        if have_fitz:
            import fitz
            pp = os.path.join(td, "b.pdf")
            d = fitz.open()
            pg = d.new_page()
            pg.draw_rect(fitz.Rect(70, 80, 200, 100), color=None, fill=(1, 1, 0))
            pg.insert_text((72, 96), "Line two", fontsize=12)
            pg.insert_text((72, 60), "Line one", fontsize=12, color=(0.93, 0, 0))
            d.save(pp)
            d.close()
            lines, marks = extract_pdf(pp)
            check("pdf: 行を y の順に並べ直す", lines == ["Line one", "Line two"])
            check("pdf: 黄色の塗り 1・色の字 1", marks == {"highlight": 1, "color": 1})
        else:
            print("skip pdf: PyMuPDF が無い")
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="同じ文書の 2 つの版の文字の差を出す (docx / pdf / md / txt)")
    ap.add_argument("a", nargs="?", help="古い版 (または --dump の対象)")
    ap.add_argument("b", nargs="?", help="新しい版")
    ap.add_argument("--whitespace", action="store_true", help="空白だけが違う箇所を出す")
    ap.add_argument("--show-line-end", action="store_true", help="行・段落の継ぎ目に当たる空白の差も出す")
    ap.add_argument("--pdf-real-spaces", action="store_true", help="PDF に実在する空白の字だけを拾う")
    ap.add_argument("--context", type=int, default=20, help="差の前後に出す字数 (既定 20)")
    ap.add_argument("--dump", action="store_true", help="1 つ目の file の抽出結果を行ごとに出すだけ")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.a or (not args.dump and not args.b):
        ap.print_usage(sys.stderr)
        return 2
    for p in (args.a, args.b) if not args.dump else (args.a,):
        if not os.path.isfile(p):
            print(f"doc-text-diff: file が無い: {p}", file=sys.stderr)
            return 2
    a_lines, marks_a = extract(args.a, args.pdf_real_spaces)
    if args.dump:
        print("\n".join(a_lines))
        print(f"# 印: マーカー {marks_a['highlight']}・色 {marks_a['color']}", file=sys.stderr)
        return 0
    b_lines, marks_b = extract(args.b, args.pdf_real_spaces)
    res = compare(a_lines, b_lines, args.whitespace, args.show_line_end, args.context)
    if args.json:
        res["marks"] = {"a": marks_a, "b": marks_b}
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(render(res, args.a, args.b, marks_a, marks_b, args.whitespace))
    return 1 if res["diffs"] else 0


if __name__ == "__main__":
    sys.exit(main())
