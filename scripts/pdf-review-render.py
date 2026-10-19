#!/usr/bin/env python3
"""pdf-review-render.py — 様式の PDF を目視用の PNG にする。 住所・口座・電話の行は塗ってから書き出す。--selftest 内蔵。

用途: 記入した様式 (旅費・謝金・届) の配置を agent が画像で確かめるとき。 画像は会話の記録に残るので、
切り取りの位置を目分量で決めると、 隣の欄の住所・口座が写る (実測)。
この道具は書き出す前に次の 2 つを塗る (字の層の位置から決める = 目分量を使わない):
  1. 見出しの語 (既定 = 銀行振込口座・振込先・口座番号・口座名義・金融機関・支店・住所・現住所・自宅・電話・TEL・携帯・郵便番号・〒)
     の行 = 見出しの語の高さの帯を、 語の左端から頁の右端まで。 見出しの右で折り返して続く行 (住所の 2 行目) も塗る
     (見出しより左に語がある行 = 次の欄で止める。 それでも足りない様式は `--below <pt>` で下へ延ばす)
  2. 値の形の語 = 7 桁の数字 (口座番号) / 電話番号 / 郵便番号 / 5 桁-6〜8 桁 (ゆうちょの記号番号) の語の箱
塗った数は頁ごとに出す。 値そのものは出さない。

⚠️ 字の層が無い頁 (scan・raster にした PDF) は位置を決められないので書き出さない (塗らずに書き出すなら --allow-unmasked)。
⚠️ 塗るのは見出しの語と値の形で見つかる所だけ = 書き出した画像を Read する前に、 塗りが要る行を覆っているかを
   `--list` の数で確かめ、 様式に別の見出し (例: 「振込を希望する口座」) があれば --label で足す。

使い方:
  pdf-review-render.py <pdf> [--pages 1,3-4] [--dpi 110] [--out <dir>] [--clip x0,y0,x1,y1] [--label <語> ...] [--below 0]
  pdf-review-render.py <pdf> --list            # 頁ごとの塗る数と字の層の有無だけ (画像を作らない)
  pdf-review-render.py <pdf> --audit           # 塗りの外に残る 4 桁以上の数字・番地らしい語を形だけで (9 / 字 / a)。 画像を Read する前に回す
  pdf-review-render.py --selftest
--out の既定 = 一時 dir の `pdf-review-render/<名前>/` (repo の中に画像を残さない = 塗っていない氏名などが commit に紛れない)。
--clip は pt 単位 (左上原点、 頁の座標)。
OS: macOS / Linux / Windows (PyMuPDF だけ)。
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

LABELS = ["銀行振込口座", "振込口座", "振込先", "口座番号", "口座名義", "金融機関", "支店", "現住所", "住所", "住　所", "住 所",
          "自宅", "電話", "電　話", "TEL", "Tel", "携帯", "郵便番号", "〒", "Address"]
VALUE_SHAPES = [
    re.compile(r"(?<![0-9])[0-9]{7}(?![0-9])"),                                  # 口座番号
    re.compile(r"(?<![0-9])[0-9]{5}-[0-9]{6,8}(?![0-9])"),                       # ゆうちょ
    re.compile(r"(?<![0-9])(?:\+81-?|0)[0-9]{1,4}-[0-9]{1,4}-[0-9]{3,4}(?![0-9])"),  # 電話
    re.compile(r"(?<![0-9])0[789]0[0-9]{8}(?![0-9])"),
    re.compile(r"〒?\s?(?<![0-9])[0-9]{3}-[0-9]{4}(?![0-9])"),                   # 郵便番号
]


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def parse_pages(spec, n):
    if not spec:
        return list(range(n))
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out += [i - 1 for i in range(lo, hi + 1) if 1 <= i <= n]
    return out


def _continued_bottom(words, label, bottom):
    """見出しの右で折り返して続く行 (住所の 2 行目など) の下端まで延ばす。 見出しより左に語がある行 = 次の欄なので止める。
    実測: 住所が「〒・都道府県市区」 と「町名・番地」 の 2 行に折り返し、 見出しの行だけを塗ると番地が残った。"""
    line_h = max(label.y1 - label.y0, 6.0)
    center = (label.y0 + label.y1) / 2
    while True:
        nxt = [w for w in words if center + 0.6 * line_h < (w[1] + w[3]) / 2 <= center + 1.6 * line_h]
        if not nxt or any(w[2] <= label.x1 for w in nxt) or not any(w[0] >= label.x1 - 2 for w in nxt):
            return bottom
        center = sum((w[1] + w[3]) / 2 for w in nxt) / len(nxt)
        bottom = max(bottom, max(w[3] for w in nxt) + 2)


def mask_rects(page, labels, below=0.0):
    """塗る矩形の list (頁の座標)。 字の層が無ければ None。"""
    import fitz
    words = page.get_text("words")
    if not words and not page.get_text("text").strip():
        return None
    rects = []
    W = page.rect.width
    for label in labels:
        for r in page.search_for(label):
            bottom = _continued_bottom(words, r, r.y1 + 2)
            rects.append(fitz.Rect(r.x0, r.y0 - 2, W, bottom + below))
    for w in words:
        text = unicodedata.normalize("NFKC", w[4])
        if any(p.search(text) for p in VALUE_SHAPES):
            rects.append(fitz.Rect(w[0] - 1, w[1] - 1, w[2] + 1, w[3] + 1))
    return rects


_ADDR_CHARS = re.compile(r"[都道府県市区町村郡丁番号]")


def shape(text):
    """値を出さない形 (数字 → 9、 英字 → a、 漢字かな → 字)。"""
    text = re.sub(r"[0-9０-９]", "9", text)
    text = re.sub(r"[A-Za-z]", "a", text)
    return re.sub(r"[一-龥ぁ-んァ-ヶー]", "字", text)


def audit(pdf, pages=None, labels=None, below=0.0):
    """[(頁番号, 塗る数, 塗りの外に残る「4 桁以上の数字・番地らしい語」 の形の list)]。 字の層が無い頁は None。
    画像を読む前に、 塗りが要る行を覆っているかを確かめる (実測: 見出しの行だけを塗ると、 折り返した番地が残った)。"""
    import fitz
    doc = fitz.open(str(pdf))
    res = []
    for i in parse_pages(pages, doc.page_count):
        page = doc[i]
        rects = mask_rects(page, labels or LABELS, below)
        if rects is None:
            res.append((i + 1, 0, None))
            continue
        left = []
        for w in page.get_text("words"):
            r = fitz.Rect(w[:4])
            if any(m.contains(r) or abs(m & r) > 0.6 * abs(r) for m in rects):
                continue
            t = w[4]
            if len(re.sub(r"\D", "", t)) >= 4 or (_ADDR_CHARS.search(t) and re.search(r"[0-9０-９]", t)):
                left.append(shape(t)[:24])
        res.append((i + 1, len(rects), left))
    return res


def render(pdf, out_dir, pages=None, dpi=110, clip=None, labels=None, below=0.0, allow_unmasked=False, list_only=False):
    """[(頁番号, 塗った数, 出した path か理由)]。"""
    import fitz
    doc = fitz.open(str(pdf))
    res = []
    for i in parse_pages(pages, doc.page_count):
        page = doc[i]
        rects = mask_rects(page, labels or LABELS, below)
        if rects is None and not allow_unmasked:
            res.append((i + 1, 0, "字の層が無い = 塗る位置を決められない (書き出さない、 --allow-unmasked で塗らずに)"))
            continue
        if list_only:
            res.append((i + 1, len(rects or []), "—"))
            continue
        for r in rects or []:
            page.draw_rect(r, color=(0, 0, 0), fill=(0, 0, 0), overlay=True)
        kw = {"dpi": dpi}
        if clip:
            kw["clip"] = fitz.Rect(*clip)
        pix = page.get_pixmap(**kw)
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{Path(pdf).stem}-p{i + 1}{'-clip' if clip else ''}.png"
        pix.save(str(dest))
        res.append((i + 1, len(rects or []), str(dest)))
    return res


def main(argv=None):
    _utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--pages")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--out")
    ap.add_argument("--clip", help="x0,y0,x1,y1 (pt)")
    ap.add_argument("--label", action="append", default=[], help="塗る見出しの語を足す (既定の語に加える)")
    ap.add_argument("--below", type=float, default=0.0, help="見出しの下に塗りを延ばす高さ (pt)")
    ap.add_argument("--allow-unmasked", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--audit", action="store_true",
                    help="画像を作らず、 塗りの外に残る 4 桁以上の数字・番地らしい語を形だけで出す (日付・番号か、 塗り漏れかを見分ける)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.pdf:
        ap.error("PDF が要る")
    pdf = Path(a.pdf).expanduser()
    out = Path(a.out).expanduser() if a.out else Path(tempfile.gettempdir()) / "pdf-review-render" / pdf.stem
    clip = [float(x) for x in a.clip.split(",")] if a.clip else None
    if a.audit:
        for page_no, n, left in audit(pdf, a.pages, LABELS + a.label, a.below):
            print(f"p{page_no}: 字の層が無い" if left is None else f"p{page_no}: 塗り {n} / 塗りの外の数字・番地らしい語 {len(left)}: {left}")
        return 0
    rows = render(pdf, out, a.pages, a.dpi, clip, LABELS + a.label, a.below, a.allow_unmasked, a.list)
    for page_no, n, where in rows:
        print(f"p{page_no}: 塗った {n} 箇所 → {where}")
    if any("字の層が無い" in w for _, _, w in rows):
        return 2
    return 0


def selftest():
    import fitz
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and bool(cond)

    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "form.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 100), "Name: Kakuu Taro", fontsize=11)
        page.insert_text((50, 140), "TEL 090-0000-1234", fontsize=11)
        page.insert_text((50, 180), "No 7654321", fontsize=11)
        page.insert_text((50, 220), "Title: test", fontsize=11)
        page.insert_text((50, 300), "Address Kaku-ken Kaku-shi", fontsize=11)   # 見出しの右で 2 行に折り返す住所
        page.insert_text((120, 313), "Shiken 9-8-7", fontsize=11)
        page.insert_text((50, 340), "Note: other field", fontsize=11)
        doc.new_page(width=595, height=842)  # 字の層が無い頁
        doc.save(str(pdf))
        rows = render(pdf, Path(d) / "out", list_only=True)
        expect("見出し (TEL) と値の形 (電話・7 桁) を数える", rows[0][1] >= 3)
        expect("字の層が無い頁は書き出さない", "字の層が無い" in rows[1][2])
        rows = render(pdf, Path(d) / "out", pages="1")
        png = Path(rows[0][2])
        expect("PNG を書く", png.exists())
        # 塗った所は黒、 塗っていない見出し (Name の行) は白地が残る
        pix = fitz.Pixmap(str(png))
        s = 110 / 72

        def dark(x, y):
            r, g, b = pix.pixel(int(x * s), int(y * s))[:3]
            return r + g + b < 60

        expect("電話の行は右端まで塗る", dark(400, 136) and dark(300, 136))
        expect("7 桁の数字の語を塗る", dark(80, 176))
        expect("関係の無い行は塗らない", not dark(400, 96) and not dark(400, 216))
        expect("見出しの右で折り返した 2 行目も塗る", dark(160, 310))
        expect("見出しより左に語がある次の行 (次の欄) は塗らない", not dark(300, 336))
        rc = main([str(pdf), "--pages", "2"])
        expect("字の層が無い頁だけを頼むと exit 2", rc == 2)
        rows = audit(pdf)
        expect("audit: 塗った語は数えず、 形だけを返す (値を出さない)",
               rows[0][2] is not None and all("1234" not in x and "7654" not in x for x in rows[0][2])
               and rows[1][2] is None)
    print("pdf-review-render selftest:", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
