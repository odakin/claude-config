#!/usr/bin/env python3
"""印刷直前の PDF preflight — 「画面で見えた」 を印刷の保証にしない機械 gate (office-automation.md#print-preflight)。

検査 (1 つでも 🔴 なら exit 1):
  1. page 数     : --template <雛形.pdf> または --expect-pages N と一致するか (= 様式が 2 頁にはみ出す事故)
  2. font        : PyMuPDF が描いた文字 (組み込み helv/tiro/japan/china-* 等 = 非埋め込み、 および
                   PyMuPDF 埋め込みの Type0/CFF) が残っていないか (= printer 側で文字化け、 OTF 埋め込みでも化けた実績)
  3. 色          : 画像 (認印等) が載っている PDF を raster 化するなら RGB で、 の注意 (情報)

オプション:
  --rasterize OUT.pdf [--dpi 600]  : 検査後に RGB raster 版を書き出す (font 問題を原理的に消す印刷用)
  --selftest                       : 合成 PDF で FAIL/PASS の両方を確認

使い方:
  python3 pdf-print-preflight.py form_print.pdf --template blank.pdf
  python3 pdf-print-preflight.py form_print.pdf --expect-pages 1 --rasterize form_print_raster.pdf

設計: 2026-08-21 に同じ 1 枚の様式を 4 回刷り直した RCA (2 頁はみ出し → 組み込み font 文字化け →
raster を gray にして認印が黒 → 値の位置ずれ) から。 各失敗は個別には既知だったが印刷前に**機械で**
確認する段が無かった。 本 script はその段。 視覚確認 (crop 画像) は別途必須 (= 位置ずれは font/頁数では出ない)。
"""
import argparse
import os
import sys
import tempfile

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    print("pdf-print-preflight: PyMuPDF (fitz) が必要: pip install pymupdf", file=sys.stderr)
    sys.exit(2)

# PyMuPDF の組み込み font (非埋め込み)。 get_fonts() の basefont / ref 名に現れる。
BUILTIN_FONT_NAMES = {
    "helv", "heit", "hebo", "hebi", "tiro", "tibo", "tiit", "tibi", "cour", "cobo", "coit", "cobi",
    "symb", "zadb", "japan", "china-s", "china-t", "korea",
}
BUILTIN_BASEFONTS = {
    "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
    "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
    "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
    "Symbol", "ZapfDingbats", "Gothic", "Mincho", "Song", "Ming", "Dotum", "Batang",
}


def inspect(path, expect_pages=None, template=None):
    """return (findings:list[str], infos:list[str])"""
    findings, infos = [], []
    doc = fitz.open(path)
    n = doc.page_count
    if template:
        tn = fitz.open(template).page_count
        if n != tn:
            findings.append(f"🔴 page 数 {n} ≠ 雛形 {tn} ({os.path.basename(template)}) — 様式がはみ出している")
        else:
            infos.append(f"page 数 {n} = 雛形 ✓")
    if expect_pages is not None:
        if n != expect_pages:
            findings.append(f"🔴 page 数 {n} ≠ 期待 {expect_pages}")
        else:
            infos.append(f"page 数 {n} = 期待 ✓")

    risky = []
    has_image = False
    for page in doc:
        for f in page.get_fonts(full=True):
            # (xref, ext, type, basefont, name, encoding, referencer)
            xref, ext, ftype, basefont, name = f[0], f[1], f[2], f[3], f[4]
            base = basefont.split("+")[-1]
            nonembedded = (ext == "n/a")
            if name in BUILTIN_FONT_NAMES or base in BUILTIN_BASEFONTS or nonembedded:
                risky.append(f"{basefont} ({ftype}, ref={name}, ext={ext})")
            elif ftype == "Type0" and "+" not in basefont:
                # PyMuPDF の insert_font(fontfile=) は subset prefix 無しの Type0 で埋め込む
                risky.append(f"{basefont} ({ftype}, PyMuPDF 埋め込みの疑い = printer で化けた実績あり)")
        if page.get_images():
            has_image = True
    if risky:
        uniq = sorted(set(risky))
        findings.append("🔴 printer で化けうる font が残っている (PyMuPDF 描画 / 非埋め込み): " + "; ".join(uniq)
                        + " → 印刷用は --rasterize で RGB raster 版を作って刷る")
    else:
        infos.append("font: PyMuPDF 描画 / 非埋め込み font なし ✓")
    if has_image:
        infos.append("画像あり (認印等) — raster 化するなら RGB (gray にすると朱が黒になる)")
    return findings, infos


def rasterize(src, out, dpi=600):
    doc = fitz.open(src)
    o = fitz.open()
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
        np_ = o.new_page(width=page.rect.width, height=page.rect.height)
        np_.insert_image(np_.rect, pixmap=pix)
    o.save(out, deflate=True)
    return out


def selftest():
    d = tempfile.mkdtemp()
    # A: PyMuPDF 組み込み japan font で文字 → FAIL
    a = os.path.join(d, "a.pdf")
    doc = fitz.open(); p = doc.new_page(); p.insert_text((72, 72), "テスト", fontname="japan"); doc.save(a)
    fa, _ = inspect(a, expect_pages=1)
    assert any("font" in x for x in fa), fa
    # B: raster 版 → PASS
    b = os.path.join(d, "b.pdf"); rasterize(a, b, dpi=72)
    fb, ib = inspect(b, expect_pages=1)
    assert not fb, fb
    assert any("画像あり" in x for x in ib)
    # C: page 数不一致 → FAIL
    c = os.path.join(d, "c.pdf")
    doc = fitz.open(); doc.new_page(); doc.new_page(); doc.save(c)
    fc, _ = inspect(c, template=b)
    assert any("page 数" in x for x in fc), fc
    # D: 文字なし 1 頁 → PASS
    e = os.path.join(d, "d.pdf"); doc = fitz.open(); doc.new_page(); doc.save(e)
    fd, _ = inspect(e, template=b)
    assert not fd, fd
    print("pdf-print-preflight selftest: 4/4 PASS")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--template", help="雛形 PDF (page 数比較)")
    ap.add_argument("--expect-pages", type=int)
    ap.add_argument("--rasterize", metavar="OUT_PDF", help="検査後に RGB raster 版を書き出す")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return 0
    if not a.pdf:
        ap.error("pdf を指定 (or --selftest)")
    findings, infos = inspect(a.pdf, a.expect_pages, a.template)
    for i in infos:
        print("  ·", i)
    for f in findings:
        print(" ", f)
    if a.rasterize:
        out = rasterize(a.pdf, a.rasterize, a.dpi)
        print(f"  ✅ raster 版: {out} ({os.path.getsize(out)//1024} KB, {a.dpi} dpi RGB) — 印刷はこちらを lp に渡す")
        return 0 if not any("page 数" in f for f in findings) else 1
    if findings:
        print("  ✗ preflight FAIL — このまま lp に渡さない")
        return 1
    print("  ✓ preflight PASS (位置ずれは別途 crop 画像で目視)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
