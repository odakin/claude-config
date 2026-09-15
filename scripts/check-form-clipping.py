#!/usr/bin/env python3
"""
check-form-clipping.py — 生成 form PDF で「記入値が描画時に clip された」のを機械検出。

(clip に加えて、 数式で複製された欄の欠け・罫線/他の字へのはみ出し・###・縮み過ぎも見る = 下の WHAT。)

WHY (office-automation-principles の検証 3 層 = 機械/視覚/実機。 従来その「機械」層は
文字 clipping を *捕捉不能* と設計上あきらめ、 視覚層 (人の目) 頼りだった
[principles.md §2 の表「捕まえられないもの = 文字切れ」]。 人が見落とせば素通り。
謝金様式の所属見切れ RCA = 結合セル (例 G13:M13) に長い所属名 (16 字相当)
を固定 14pt で書くと両端が clip → セル値は完全なので diff-form-xlsx では出ず、 視覚確認も
所属行を凝視しないと気づかない → 人の目だけが gate だった)。 ここを埋める。

WHAT: 雛形 (template) と記入済 (filled) を diff して **記入セル (= 値が変わったセル)**
だけを取り、 生成 PDF と次の面で照合する:
  1. clip       = 各記入値が PDF の抽出テキスト (全ページ連結 + NFKC 正規化 + 空白除去) に
                  完全な部分文字列として現れるか。 一部だけ (最長片 ≥3 字、 欠落 ≥3 字) = clip 疑い。
                  ほぼ現れない (最長片 < 3 字) = 別ページ/別 sheet (flag しない)
  2. fan-out    = 同じ値を持つ記入セルが k 個あるのに、 PDF に完全な形で m < k 回しか無い
                  (= 数式で他 sheet に複製された欄の 1 つだけが切れた。 全体の部分文字列 search は
                  他の 1 箇所で hit して見逃す)。 数式セルは filled を data_only で読むので、
                  **Excel が保存した workbook (数式の計算済み値つき)** を渡すと射程に入る
  3. overflow   = 完全に描かれた値の字が、 罫線の上に乗る / 他の字と重なる (= 折り返した行が欄の
                  上下にはみ出す、 折り返さない文字列が隣の欄へ伸びる)。 字の text 層は全文残るので
                  1・2 では見えない。 字の box (PyMuPDF rawdict の char bbox = em box) の中央部
                  (上下左右 15% を除く) を罫線 (Excel が塗りの細い矩形で描く線) が横切るか、
                  別の字の box と 35% 超重なるか
  4. hash       = PDF に `###` がある (= 数値・日付が欄の幅に入らず Excel が # で埋めた)
  5. small      = (``--min-scale K`` の時) 記入値の描画の字の大きさ (字の box の高さ) が、 その cell の font size の
                  K 倍未満 (= 紙 1 枚に収める設定で、 行を伸ばし過ぎ・値が長過ぎて page 全体が縮み過ぎた)。
                  font が小さい欄そのものは見ない (倍率で見る)

雛形 diff で「記入値だけ」に絞るのが肝 (= テンプレの注意書きラベルや他 sheet の固定文を
誤検出しない。 diff-form-xlsx と同じ契約)。 閾値「欠落 ≥ 3 字」で正規化由来の 1-2 字差も除外。
PDF に載らない sheet の値は、 呼び元が filled からその sheet を雛形の値に戻して渡す (= 2 の k を数え過ぎない)。

LIMIT (= 視覚確認を置換しない): レンダラによっては clip しても text 層に全文を残す
(clip-path 方式) ことがある。 LibreOffice / Excel は実測で truncate するため 1 で捕まるが
engine 依存。 3 は線を塗りの矩形 / line で描く renderer を前提にする (Excel の PDF は実測で矩形)。
罫線の無い余白へのはみ出しで他の字にも当たらないもの、 1・2 は 4 字未満 / 3 は 2 字未満の値を見ない (短い部分一致の誤検出)。
本検出は「機械層の第一防衛線」 であって pdf-visual-confirm を置換しない。

USAGE:
  check-form-clipping.py <template.xlsx> <filled.xlsx> <form.pdf>   # exit 1 if 疑いあり
  check-form-clipping.py --json <tpl> <filled> <pdf>                # 結果を JSON で (呼び元が欄を直す用)
  check-form-clipping.py --min-scale 0.6 <tpl> <filled> <pdf>       # 5 (縮み過ぎ) も見る
  check-form-clipping.py --sizes <tpl> <filled> <pdf>               # 記入値ごとの描画の大きさと倍率を一覧 (閾値の較正用)
  check-form-clipping.py --min-len N <tpl> <filled> <pdf>           # 最短照合字数 (既定 4)
  check-form-clipping.py --selftest                                 # 内蔵 self-test (file 不要)
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import defaultdict

_GLYPH_SKIP = set("☑□■✓✔☐−—–-〇○●◯ 　")
MISSING_MIN = 3   # この字数以上が欠けたら clip とみなす (1-2 字は正規化/描画差として無視)
FRAG_MIN = 3      # この字数以上の連続片が在る = そのセルがこの PDF 上に在る証拠
EDGE = 0.15       # 字の box の端のこの割合は罫線が掛かっても「横切る」 と数えない (下線・枠の内側の余白)
OVERLAP = 0.35    # 別の字の box とこの割合を超えて重なったら重なり
RULE_THICK = 2.0  # これ以下の太さの塗り矩形を罫線とみなす (pt)
OVERFLOW_MIN_LEN = 2  # はみ出しは 2 字の値から見る (位置で判定するので短い部分一致の誤検出が起きにくい)


def _norm(s: str) -> str:
    """NFKC 正規化 + 空白除去 (= ⾼→高 等の互換字、 折り返し空白、 全/半角差を吸収)。"""
    s = unicodedata.normalize("NFKC", s)
    return "".join(ch for ch in s if not ch.isspace())


def _checkable(raw, min_len):
    if not isinstance(raw, str) or raw.startswith("="):
        return None
    needle = _norm(raw)
    if len(needle) < min_len or all(ch in _GLYPH_SKIP for ch in needle):
        return None
    return needle


def _longest_common_substring_len(needle: str, hay: str) -> int:
    best = 0
    n = len(needle)
    for i in range(n):
        if n - i <= best:
            break
        j = i + best + 1
        while j <= n and needle[i:j] in hay:
            best = j - i
            j += 1
    return best


def _count(needle: str, hay: str) -> int:
    n, i = 0, hay.find(needle)
    while i >= 0:
        n += 1
        i = hay.find(needle, i + len(needle))
    return n


def find_clipping(values, pdf_text, min_len=4):
    """純関数 (= selftest 可能)。 values: [(loc, raw_value)] / pdf_text: str。
    返り値: [(loc, value, frag_len, value_len)] = clip 疑い (1) と fan-out の欠け (2)。
    fan-out の欠けは frag_len = value_len (= 完全な形はあるが数が足りない) で、 loc は同じ値の全セル。"""
    hay = _norm(pdf_text)
    flagged = []
    by_needle = defaultdict(list)
    for loc, raw in values:
        needle = _checkable(raw, min_len)
        if needle is not None:
            by_needle[needle].append((loc, raw))
    for needle, cells in by_needle.items():
        m = _count(needle, hay)
        if m == 0:
            frag = _longest_common_substring_len(needle, hay)
            if frag >= FRAG_MIN and (len(needle) - frag) >= MISSING_MIN:
                flagged += [(loc, raw, frag, len(needle)) for loc, raw in cells]
            # frag 小 = 別ページ/別 sheet / 欠落 1-2 字 = 描画差 → flag しない
        elif m < len(cells):
            flagged.append((", ".join(loc for loc, _ in cells), cells[0][1], len(needle), len(needle)))
    return flagged


def _page_model(page):
    """page の (正規化した字の列, 字ごとの box, 横の罫線 [(x0,x1,y)], 縦の罫線 [(y0,y1,x)])。"""
    import fitz

    chars, rects = [], []
    for b in page.get_text("rawdict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                for ch in sp["chars"]:
                    for n in _norm(ch["c"]):
                        chars.append(n)
                        rects.append(fitz.Rect(ch["bbox"]))
    hs, vs = [], []
    for path in page.get_drawings():
        for it in path["items"]:
            if it[0] == "re":
                r = it[1]
                if r.height <= RULE_THICK and r.width > r.height:
                    hs.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
                elif r.width <= RULE_THICK and r.height > r.width:
                    vs.append((r.y0, r.y1, (r.x0 + r.x1) / 2))
                elif path.get("type") != "f":          # 線で描いた枠 = 4 辺 (塗りの面は線でない)
                    hs += [(r.x0, r.x1, r.y0), (r.x0, r.x1, r.y1)]
                    vs += [(r.y0, r.y1, r.x0), (r.y0, r.y1, r.x1)]
            elif it[0] == "l":
                a, b2 = it[1], it[2]
                if abs(a.y - b2.y) < 0.5:
                    hs.append((min(a.x, b2.x), max(a.x, b2.x), a.y))
                elif abs(a.x - b2.x) < 0.5:
                    vs.append((min(a.y, b2.y), max(a.y, b2.y), a.x))
    return "".join(chars), rects, hs, vs


def _crossing(r, hs, vs):
    ex, ey = EDGE * r.width, EDGE * r.height
    for x0, x1, y in hs:
        if r.y0 + ey < y < r.y1 - ey and x0 < r.x1 - ex and x1 > r.x0 + ex:
            return f"横の罫線 y={y:.1f}"
    for y0, y1, x in vs:
        if r.x0 + ex < x < r.x1 - ex and y0 < r.y1 - ey and y1 > r.y0 + ey:
            return f"縦の罫線 x={x:.1f}"
    return None


def _overlapping(k, rects, own, chars):
    r = rects[k]
    a = r.width * r.height
    if a <= 0:
        return None
    for i, o in enumerate(rects):
        if i in own or chars[i] in _GLYPH_SKIP:
            continue
        inter = r & o
        if inter.is_empty:
            continue
        oa = o.width * o.height
        if oa > 0 and (inter.width * inter.height) / min(a, oa) > OVERLAP:
            return f"字「{chars[i]}」と重なる"
    return None


def rendered_sizes_pages(values, pages, min_len=4):
    """記入値の occurrence ごとの描画の字の大きさ (字の box の高さの中央値 pt)。 [(loc, value, page, pt)]。"""
    import statistics

    out = []
    for loc, raw in values:
        needle = _checkable(raw, min_len)
        if needle is None:
            continue
        for pi, (chars, rects, _hs, _vs) in enumerate(pages):
            i = chars.find(needle)
            while i >= 0:
                hs = [rects[k].height for k in range(i, i + len(needle)) if chars[k] not in _GLYPH_SKIP]
                if hs:
                    out.append((loc, raw, pi + 1, round(statistics.median(hs), 2)))
                i = chars.find(needle, i + len(needle))
    return out


def find_overflow_pages(values, pages, min_len=4):
    """values: [(loc, raw)] / pages: [(chars, rects, hs, vs)] (_page_model の出力)。
    返り値: [(loc, value, page_1based, n_bad_chars, example)]。 完全に描かれた occurrence だけを見る。"""
    out = []
    for loc, raw in values:
        needle = _checkable(raw, min_len)
        if needle is None:
            continue
        for pi, (chars, rects, hs, vs) in enumerate(pages):
            i = chars.find(needle)
            while i >= 0:
                own = set(range(i, i + len(needle)))
                bad = []
                for k in sorted(own):
                    if chars[k] in _GLYPH_SKIP:
                        continue
                    why = _crossing(rects[k], hs, vs) or _overlapping(k, rects, own, chars)
                    if why:
                        bad.append(f"「{chars[k]}」{why}")
                if bad:
                    out.append((loc, raw, pi + 1, len(bad), bad[0]))
                i = chars.find(needle, i + len(needle))
    return out


def find_overflow(values, pdf_path, min_len=4):
    import fitz

    with fitz.open(pdf_path) as d:
        return find_overflow_pages(values, [_page_model(pg) for pg in d], min_len)


def find_small(values, pdf_path, fonts, min_scale, min_len=4):
    """描画の字の大きさ / その cell の font size が min_scale 未満の記入値 (= 紙 1 枚に収めるために page 全体が
    縮み過ぎた)。 fonts = {loc: font size}。 返り値 [(loc, value, page, 描画 pt, 倍率)]。"""
    import fitz

    with fitz.open(pdf_path) as d:
        pages = [_page_model(pg) for pg in d]
    out = []
    for loc, raw, page, pt in rendered_sizes_pages(values, pages, min_len):
        sz = fonts.get(loc)
        if sz and pt / sz < min_scale:
            out.append((loc, raw, page, pt, round(pt / sz, 3)))
    return out


def find_hash(pdf_text):
    return "###" in pdf_text


def _input_cells(template_path, filled_path):
    """雛形と記入済を diff して、 値が変わった (= 記入された) 文字列セルだけ返す (数式は計算済みの値で)。"""
    import openpyxl
    tpl = openpyxl.load_workbook(template_path, data_only=True)
    fil = openpyxl.load_workbook(filled_path, data_only=True)
    tmap = {}
    for ws in tpl.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None:
                    tmap[(ws.title, c.coordinate)] = c.value
    out = []
    for ws in fil.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.strip() and tmap.get((ws.title, c.coordinate)) != v:
                    out.append((f"{ws.title}!{c.coordinate}", v))
    return out


def _input_fonts(filled_path):
    """cell → font size (pt)。"""
    import openpyxl
    fil = openpyxl.load_workbook(filled_path)
    return {f"{ws.title}!{c.coordinate}": float(c.font.sz) for ws in fil.worksheets for row in ws.iter_rows()
            for c in row if c.value is not None and c.font is not None and c.font.sz}


def _extract_pdf_text(path):
    import fitz
    with fitz.open(path) as d:
        return "\n".join(pg.get_text() for pg in d)


def check(template, filled, pdf, min_len=4, min_scale=None):
    values = _input_cells(template, filled)
    text = _extract_pdf_text(pdf)
    return {"values": len(values),
            "clip": [{"loc": l, "value": v, "frag": f, "len": n} for l, v, f, n in find_clipping(values, text, min_len)],
            "overflow": [{"loc": l, "value": v, "page": p, "chars": n, "example": e}
                         for l, v, p, n, e in find_overflow(values, pdf, min(min_len, OVERFLOW_MIN_LEN))],
            "small": ([{"loc": l, "value": v, "page": p, "pt": s, "scale": k}
                       for l, v, p, s, k in find_small(values, pdf, _input_fonts(filled), min_scale, min_len)]
                      if min_scale else []),
            "hash": find_hash(text)}


def _selftest():
    # 注: literal は全て架空 (= 公開 layer の PII leak 防止)。 ロジックを exercise するだけ。
    import os
    import tempfile

    cases = []
    vals = [("S!G13", "国立アイウエオ加速器研究機構（略称）"),
            ("S!Y13", "甲野 太郎"), ("S!Q13", "研究員")]
    pdf = "所属 アイウエオ加速器研究機構（ 職名 研究員 氏名 甲野 太郎"
    f = find_clipping(vals, pdf)
    cases.append(("clip 検出 (結合セルの長文)", [l for l, *_ in f] == ["S!G13"]))
    cases.append(("非clip (短い所属は収まる)", find_clipping(
        [("S!G13", "架空女子大学大学院")], "所属 架空女子大学大学院 職名") == []))
    cases.append(("NFKC 互換字を同一視", find_clipping(
        [("S!A1", "あいう大学")], "あいう⼤学") == []))  # ⼤=U+2F24 → NFKC → 大
    cases.append(("別ページ非検出", find_clipping(
        [("S!A1", "まったく無関係な長い文字列")], "ここには別の短い内容のみ") == []))
    cases.append(("折返し空白吸収", find_clipping(
        [("S!A1", "カキクケコサシスセソ")], "カキクケコ\nサシスセソ") == []))
    cases.append(("欠落1字は無視 (先頭タブ)", find_clipping(
        [("S!A1", "\tあいうえおかきくけこさしすせそ")],
        "あいうえおかきくけこさしすせそ") == []))
    cases.append(("部分一致(欠落2字)は無視", find_clipping(
        [("S!A1", "あい承認欄")], "ここに承認欄あり") == []))  # frag=3 だが欠落2字
    fan = [("A!G17", "架空の研究課題に関する会合"), ("B!E25", "架空の研究課題に関する会合")]
    cases.append(("fan-out: 2 セルの値が PDF に 1 回だけ完全 = 検出",
                  len(find_clipping(fan, "用務 架空の研究課題に関する会合 依頼書 架空の研究課題に関す")) == 1))
    cases.append(("fan-out: 2 回とも完全なら非検出",
                  find_clipping(fan, "架空の研究課題に関する会合 / 架空の研究課題に関する会合") == []))
    cases.append(("hash: ### を検出", find_hash("出発 ####### 帰着") and not find_hash("# 1")))

    try:
        import fitz
    except ImportError:
        print("  [SKIP] overflow (PyMuPDF 不在)")
        fitz = None
    if fitz is not None:
        td = tempfile.mkdtemp()
        path = os.path.join(td, "t.pdf")
        font = os.environ.get("CHECK_FORM_CLIPPING_TEST_FONT")   # 無ければ PyMuPDF 同梱の CJK font
        doc = fitz.open()
        pg = doc.new_page(width=400, height=300)
        kw = {"fontfile": font, "fontname": "F0"} if font else {"fontname": "japan"}
        pg.insert_text((20, 50), "アイウエオカキクケコ", fontsize=12, **kw)        # 罫線の上に乗る
        pg.draw_rect(fitz.Rect(10, 45.5, 300, 46.5), color=None, fill=(0, 0, 0))
        pg.insert_text((20, 100), "サシスセソタチツテト", fontsize=12, **kw)       # 下に罫線 (字の外)
        pg.draw_rect(fitz.Rect(10, 103.5, 300, 104.5), color=None, fill=(0, 0, 0))
        pg.insert_text((20, 150), "ナニヌネノハヒフヘホ", fontsize=12, **kw)       # 別の字と重なる
        pg.insert_text((50, 151), "マミムメモ", fontsize=12, **kw)
        doc.save(path)
        doc.close()
        ov = find_overflow([("S!A1", "アイウエオカキクケコ"), ("S!A2", "サシスセソタチツテト"),
                            ("S!A3", "ナニヌネノハヒフヘホ")], path)
        locs = sorted({o[0] for o in ov})
        cases.append(("overflow: 罫線が字を横切る = 検出", "S!A1" in locs))
        cases.append(("overflow: 字の下の罫線 (下線) は非検出", "S!A2" not in locs))
        cases.append(("overflow: 別の字と重なる = 検出", "S!A3" in locs))
        path2 = os.path.join(td, "s.pdf")
        doc = fitz.open()
        pg = doc.new_page(width=400, height=300)
        pg.insert_text((20, 50), "ヤユヨラリルレロ", fontsize=5, **kw)      # cell は 12pt = 半分未満に縮んで描かれた
        pg.insert_text((20, 100), "ワヲンアイウエオ", fontsize=12, **kw)
        doc.save(path2)
        doc.close()
        small = find_small([("S!B1", "ヤユヨラリルレロ"), ("S!B2", "ワヲンアイウエオ")], path2,
                           {"S!B1": 12.0, "S!B2": 12.0}, 0.6)
        cases.append(("small: cell の font の 0.6 倍未満で描かれた記入値 = 検出 / 等倍は非検出",
                      [s[0] for s in small] == ["S!B1"]))
    ok = True
    for name, res in cases:
        print(f"  [{'PASS' if res else 'FAIL'}] {name}")
        ok = ok and res
    print("selftest:", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("template", nargs="?")
    ap.add_argument("filled", nargs="?")
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--min-len", type=int, default=4)
    ap.add_argument("--min-scale", type=float, default=None)
    ap.add_argument("--sizes", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest())
    if not (args.template and args.filled and args.pdf):
        ap.error("template.xlsx filled.xlsx form.pdf を指定 (または --selftest)")

    if args.sizes:
        import fitz
        with fitz.open(args.pdf) as d:
            pages = [_page_model(pg) for pg in d]
        fonts = _input_fonts(args.filled)
        for loc, v, p, pt in rendered_sizes_pages(_input_cells(args.template, args.filled), pages, args.min_len):
            sz = fonts.get(loc)
            print(f"p.{p}\t{pt}\t{round(pt / sz, 3) if sz else '-'}\t{loc}\t{v[:30]!r}")
        sys.exit(0)
    res = check(args.template, args.filled, args.pdf, min_len=args.min_len, min_scale=args.min_scale)
    bad = bool(res["clip"] or res["overflow"] or res["hash"] or res["small"])
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(1 if bad else 0)
    if not bad:
        print(f"✓ 切れ・はみ出し・### なし (記入セル {res['values']} 件を照合)")
        sys.exit(0)
    if res["clip"]:
        print(f"⚠️  clip 疑い {len(res['clip'])} 件 (= 記入値が PDF 描画で truncate された可能性):")
        for c in res["clip"]:
            if c["frag"] == c["len"]:
                print(f"  {c['loc']}: 値「{c['value']}」 は数式などで複数の欄に出るが、 完全な形で描かれていない欄がある")
            else:
                print(f"  {c['loc']}: 値「{c['value']}」({c['len']}字) のうち最長 {c['frag']}字 しか描画されていない")
    if res["overflow"]:
        print(f"⚠️  はみ出し {len(res['overflow'])} 件 (= 字が罫線・他の字に掛かっている):")
        for o in res["overflow"]:
            print(f"  {o['loc']} (p.{o['page']}): 値「{o['value'][:40]}」 の {o['chars']} 字。 例 = {o['example']}")
    if res["hash"]:
        print("⚠️  PDF に ### がある (= 数値・日付が欄の幅に入らない)")
    if res["small"]:
        print(f"⚠️  cell の font の {args.min_scale} 倍未満に縮んで描かれた記入値 {len(res['small'])} 件 (= 紙 1 枚に収めるため page が縮み過ぎた):")
        for s in res["small"][:12]:
            print(f"  {s['loc']} (p.{s['page']}): {s['pt']}pt = {s['scale']} 倍 「{s['value'][:30]}」")
    print("対処: 結合セルなら font size を下げる (shrink_to_fit は無効) / 行高を足して折り返す / 欄の幅を広げる。")
    print("      office-automation.md#merged-cell-text-clipping 参照。視覚確認も併用。")
    sys.exit(1)


if __name__ == "__main__":
    main()
