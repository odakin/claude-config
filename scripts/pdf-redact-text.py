#!/usr/bin/env python3
"""pdf-redact-text.py — PDF の中の指定文字列 (暗証番号・口座番号など) を黒塗りし、 消えたことを文字層と画像で確かめる。

用途: 事務や第三者に出す PDF (予約確認・領収書・明細) に、 出す必要のない秘密 (予約の暗証番号 / PIN、 口座番号、
会員番号) が印字されているとき、 その文字列だけを塗りつぶした写しを作る。 元の PDF は変えない。

  python3 pdf-redact-text.py booking.pdf --text 1234 -o booking-redacted.pdf --png-dir /tmp/check
    → booking-redacted.pdf + 塗った頁の PNG (目視用) + 当たった箇所の前後の文字 (誤爆していないかを見る)

処理:
  1. 各頁で `--text` を検索 (PyMuPDF search_for)。 当たった矩形ごとに、 前後の文字を出す
     (= 短い数字は日付や金額の一部にも当たる。 意図しない箇所を塗っていないかを人が読む)。
  2. redaction annotation を置いて apply_redactions = **文字層からも消える** (上に黒い四角を描くだけの方法は、
     下の文字が copy / 抽出で読めてしまうので使わない)。
  3. 出力を開き直し、 全頁の文字層に `--text` が残っていないことを確かめる。 `--png-dir` があれば塗った頁を PNG にする。

終了コード: 0 = 全 text が 1 回以上当たり、 出力に残っていない / 1 = 当たらない text がある (`--allow-missing` で許す) か
出力に残った / 2 = 実行不能。

⚠️ 限界: 文字層の無い頁 (スキャン画像・文字をパスで描いた PDF) の文字は検索に当たらない = 当たり 0 件は「無い」 の
証明にならない。 文字層が無い頁は警告し、 その場合は PNG を目で見て判断する。
⚠️ 日本語 locale の PDF で和文 font が埋め込まれておらず項目名が豆腐 (□) になることがある (実測) = 文字層にも出ない。
出す書類として読めるかは PNG で確かめ、 読めなければ元のサイトで英語表示に切り替えて取り直す。

  --selftest : 合成 PDF で 1-3 を通す
"""
import argparse
import os
import sys
import tempfile

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    print("PyMuPDF (fitz) が必要: pip install pymupdf", file=sys.stderr)
    sys.exit(2)


def _context(page, rect, pad=60):
    box = fitz.Rect(rect.x0 - pad, rect.y0 - 2, rect.x1 + pad, rect.y1 + 2)
    return " ".join(page.get_textbox(box).split())


def redact(src, texts, out, png_dir=None, allow_missing=False, dpi=110):
    doc = fitz.open(src)
    hits = {t: 0 for t in texts}
    hit_pages = set()
    for pno, page in enumerate(doc, 1):
        if not page.get_text().strip():
            print(f"⚠️ p.{pno}: 文字層が無い = 検索に当たらない。 PNG で目視すること")
        for t in texts:
            for r in page.search_for(t):
                print(f"p.{pno}: '{t}' ← 前後「{_context(page, r)}」")
                page.add_redact_annot(r, fill=(0, 0, 0))
                hits[t] += 1
                hit_pages.add(pno)
        page.apply_redactions()
    doc.save(out, garbage=3, deflate=True)
    doc.close()

    ok = True
    for t, n in hits.items():
        if n == 0:
            print(f"{'⚠️' if allow_missing else '❌'} '{t}' は 1 回も当たらなかった")
            ok = ok and allow_missing
    chk = fitz.open(out)
    text_all = "".join(p.get_text() for p in chk)
    for t in texts:
        if t in text_all:
            print(f"❌ 出力の文字層に '{t}' が残っている")
            ok = False
    if png_dir:
        os.makedirs(png_dir, exist_ok=True)
        for pno in sorted(hit_pages):
            path = os.path.join(png_dir, f"{os.path.splitext(os.path.basename(out))[0]}-p{pno}.png")
            chk[pno - 1].get_pixmap(dpi=dpi).save(path)
            print(f"PNG: {path}")
    chk.close()
    print(("OK" if ok else "NG") + f": {out} (当たり {sum(hits.values())} 箇所)")
    return 0 if ok else 1


def selftest():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in.pdf")
        out = os.path.join(d, "out.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Customer reference: 40-000")
        page.insert_text((72, 96), "PIN code: 9731")
        page.insert_text((72, 120), "Total JPY 1,000")
        doc.save(src)
        doc.close()
        rc = redact(src, ["9731"], out)
        remaining = "".join(p.get_text() for p in fitz.open(out))
        cases = [
            ("rc == 0", rc == 0),
            ("PIN が文字層から消えた", "9731" not in remaining),
            ("他の行は残る", "Customer reference" in remaining and "Total JPY" in remaining),
            ("当たらない text は NG", redact(src, ["nothere"], out) == 1),
            ("--allow-missing なら OK", redact(src, ["nothere"], out, allow_missing=True) == 0),
        ]
    ok = all(v for _, v in cases)
    for name, v in cases:
        print(("PASS " if v else "FAIL ") + name)
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--text", action="append", default=[], help="塗る文字列 (複数可)")
    ap.add_argument("-o", "--out")
    ap.add_argument("--png-dir")
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.pdf or not a.text or not a.out:
        ap.error("pdf / --text / -o が必要")
    if os.path.abspath(a.pdf) == os.path.abspath(a.out):
        ap.error("元の PDF を上書きしない (-o に別の path)")
    sys.exit(redact(a.pdf, a.text, a.out, a.png_dir, a.allow_missing))


if __name__ == "__main__":
    main()
