#!/usr/bin/env python3
"""印刷直前の PDF preflight — 「画面で見えた」 を印刷の保証にしない機械 gate (office-automation.md#print-preflight)。

検査 (1 つでも 🔴 なら exit 1):
  1. page 数     : --template <雛形.pdf> または --expect-pages N と一致するか (= 様式が 2 頁にはみ出す事故)。
                   ⚠️ 一致は「はみ出していない」 しか言わない。 どの頁を刷るかは 5.
  2. font        : PyMuPDF が描いた文字 (組み込み helv/tiro/japan/china-* 等 = 非埋め込み、 および
                   PyMuPDF 埋め込みの Type0/CFF) が残っていないか (= printer 側で文字化け、 OTF 埋め込みでも化けた実績)
  3. 色          : 画像 (認印等) が載っている PDF を raster 化するなら RGB で、 の注意 (情報)
  4. 用紙        : 頁の寸法と名前 (A4 等) を表示 (情報)。 ⚠️ lp の media 指定は本体の用紙設定を上書きしない
                   (実測) ので、 刷る前に本体の用紙サイズとトレイの紙を確認する
  5. 頁の役割    : 全頁が「窓口に出す頁」 か (office-automation.md#print-submission-pages-only、 lib/print_pages.py)。
                   file に宣言 (作った道具が書く) があればそれを読み、 提出でない頁 (説明書き・記載例・控え・マスタ・白紙)
                   が入っていれば 🔴。 宣言が無ければ見出しから推定し、 記載例・控え・注意事項・白紙に見える頁と、
                   宣言の無い 2 頁以上の file は 🔴 (= どの頁を出すかを --pages で決めてから刷る)。 頁の一覧を毎回出す
  ※ 2. は PyMuPDF 製に限らない: headless browser の print-to-PDF が書く Type3 font も非埋め込み扱いで FAIL になる (実測)

オプション:
  --rasterize OUT.pdf [--dpi 600]  : 検査後に RGB raster 版を書き出す (font 問題を原理的に消す印刷用)
  --extract OUT.pdf                : 頁を選んだ vector 版を書き出す (Word / Excel が直接吐いた PDF 等、 raster が要らない時)
  --pages SPEC                     : OUT に入れる頁 (all / 1-2,4 / changed)。 入れた頁を「提出」 と宣言して OUT に書く。
                                     ⚠️ lp -o page-ranges は無視される queue がある (実測) = 刷る頁だけの file を作る
  --include-flagged REASON         : 説明書き・記載例等に見える頁を、 理由つきで OUT に残す (理由は宣言に記録)
  --changed-from OLD.pdf           : 前に刷った版と頁ごとに比べ、 変わった頁を出す (--pages changed = その頁だけ刷り直す)
  --selftest                       : 合成 PDF で FAIL/PASS の両方を確認

使い方:
  python3 pdf-print-preflight.py form_print.pdf --template blank.pdf
  python3 pdf-print-preflight.py form.pdf --rasterize form_print.pdf --pages 1-2      # 窓口に出す 2 頁だけ刷る
  python3 pdf-print-preflight.py new.pdf --changed-from printed.pdf --rasterize re.pdf --pages changed

設計: 2026-08-21 に同じ 1 枚の様式を 4 回刷り直した RCA (2 頁はみ出し → 組み込み font 文字化け →
raster を gray にして認印が黒 → 値の位置ずれ) から。 各失敗は個別には既知だったが印刷前に**機械で**
確認する段が無かった。 本 script はその段。 視覚確認 (crop 画像) は別途必須 (= 位置ずれは font/頁数では出ない)。
5. は、 頁数の検査が様式付属の説明書きの頁まで「期待どおり」 と通した実測から (頁数は刷る頁の集合を問わない)。
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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from print_pages import ROLES, changed_pages, classify, parse_pages, problems, read_record, write_record  # noqa: E402
from seal_artifact import MARKER, copy_marker, mark_doc  # noqa: E402

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


# 寸法 (mm を丸めた短辺・長辺) → 名前
PAPER_NAMES = {(210, 297): "A4", (148, 210): "A5", (297, 420): "A3", (182, 257): "B5 JIS", (176, 250): "B5 ISO",
               (257, 364): "B4 JIS", (216, 279): "Letter", (100, 148): "はがき"}

PAGE_FIX = ("→ 窓口に出す頁だけの file を作って刷る: pdf-print-preflight.py <元の PDF> --rasterize <刷る.pdf> --pages <頁> "
            "(説明書き等に見える頁を残すなら --include-flagged '<理由>')")


def inspect(path, expect_pages=None, template=None, pages_check=True):
    """return (findings:list[str], infos:list[str])"""
    findings, infos = [], []
    doc = fitz.open(path)
    n = doc.page_count
    if template:
        tn = fitz.open(template).page_count
        if n != tn:
            findings.append(f"🔴 page 数 {n} ≠ 雛形 {tn} ({os.path.basename(template)}) — 様式がはみ出している")
        else:
            infos.append(f"page 数 {n} = 雛形 ✓ (= はみ出していない。 どの頁を刷るかは下の頁の一覧)")
    if expect_pages is not None:
        if n != expect_pages:
            findings.append(f"🔴 page 数 {n} ≠ 期待 {expect_pages}")
        else:
            infos.append(f"page 数 {n} = 期待 ✓ (= はみ出していない。 どの頁を刷るかは下の頁の一覧)")

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
        shown = "; ".join(uniq[:5]) + (f"; … 他 {len(uniq) - 5} 個" if len(uniq) > 5 else "")
        findings.append(f"🔴 printer で化けうる font が {len(uniq)} 個残っている (PyMuPDF 描画 / 非埋め込み): " + shown
                        + " → 印刷用は --rasterize で RGB raster 版を作って刷る")
    else:
        infos.append("font: PyMuPDF 描画 / 非埋め込み font なし ✓")
    if has_image:
        infos.append("画像あり (認印等) — raster 化するなら RGB (gray にすると朱が黒になる)")
    sizes = sorted({(round(pg.rect.width * 25.4 / 72), round(pg.rect.height * 25.4 / 72)) for pg in doc})
    labels = []
    for w, h in sizes:
        nm = PAPER_NAMES.get((min(w, h), max(w, h)))
        labels.append(f"{w}×{h} mm" + (f" ({nm})" if nm else ""))
    infos.append("用紙: " + ", ".join(labels)
                 + " — lp の media 指定は本体の用紙設定を上書きしない = 本体の用紙サイズとトレイの紙を確認")
    if pages_check:
        blocking, lines = problems(doc)
        rec = read_record(doc)
        infos.append(f"頁の一覧 ({n} 頁" + (f"、 宣言 = {rec.get('src', '?')}" if rec else "、 宣言なし") + "):")
        infos.extend("   " + x for x in lines)
        for b in blocking:
            findings.append(f"🔴 頁: {b}")
        if blocking:
            findings.append("   " + PAGE_FIX)
    return findings, infos


def _select(doc, spec, changed=None):
    """(頁番号 list, 入れた頁で推定が疑わしいもの, 宣言上は提出でない頁)"""
    if (spec or "").strip().lower() == "changed":
        if changed is None:
            raise ValueError("--pages changed には --changed-from が要る")
        if not changed:
            raise ValueError("変わった頁が無い = 刷り直す頁は無い")
        sel = list(changed)
    else:
        sel = parse_pages(spec, doc.page_count)
    rec = read_record(doc)
    decl = rec["pages"] if rec and len(rec["pages"]) == doc.page_count else None
    flagged, declared_off = [], []
    for k in sel:
        if decl and decl[k - 1]["role"] != "submit":
            declared_off.append(f"p.{k} {ROLES.get(decl[k - 1]['role'])} (宣言)")
            continue
        g = classify(doc[k - 1])
        if g["role"] and not decl:
            flagged.append(f"p.{k} {ROLES[g['role']]}? ({g['why']})")
    return sel, flagged, declared_off


def write_selected(src, out, sel, raster, dpi=600, src_label="", include_flagged=None):
    """src の sel 頁 (1 始まり) だけを out に書き、 「提出」 と宣言する。 raster = RGB で描き直す。"""
    doc = fitz.open(src)
    rec = read_record(doc)
    decl = rec["pages"] if rec and len(rec["pages"]) == doc.page_count else None
    o = fitz.open()
    labels = []
    for k in sel:
        page = doc[k - 1]
        g = classify(page)
        labels.append((decl[k - 1].get("label") if decl else "") or g["heading"])
        if raster:
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
            np_ = o.new_page(width=page.rect.width, height=page.rect.height)
            np_.insert_image(np_.rect, pixmap=pix)
        else:
            o.insert_pdf(doc, from_page=k - 1, to_page=k - 1)
    copy_marker(doc, o)  # 紙専用の印 (lib/seal_artifact.py) を引き継ぐ
    dropped = []
    for k in range(1, doc.page_count + 1):
        if k in sel:
            continue
        role = decl[k - 1]["role"] if decl else (classify(doc[k - 1])["role"] or "unselected")
        label = (decl[k - 1].get("label") if decl else "") or classify(doc[k - 1])["heading"]
        dropped.append({"from": k, "role": role, "label": label[:40]})
    src_name = os.path.basename(src)
    by = src_label or f"pdf-print-preflight --pages {','.join(map(str, sel))} ({src_name})"
    write_record(o, [{"role": "submit", "label": lb} for lb in labels], by, dropped=dropped,
                 include_flagged=include_flagged)
    o.save(out, garbage=3, deflate=True)
    return out


def rasterize(src, out, dpi=600):
    """全頁を RGB raster に (頁を選ばない従来の経路)。 src の頁の宣言と紙専用の印を引き継ぐ。"""
    doc = fitz.open(src)
    o = fitz.open()
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
        np_ = o.new_page(width=page.rect.width, height=page.rect.height)
        np_.insert_image(np_.rect, pixmap=pix)
    copy_marker(doc, o)  # 紙専用の印 (lib/seal_artifact.py) を raster 版へ引き継ぐ (印影が画素に焼かれて見分けられなくなるため)
    rec = read_record(doc)
    if rec is not None and len(rec["pages"]) == doc.page_count:
        write_record(o, rec["pages"], rec.get("src", ""), rec.get("dropped"), rec.get("include_flagged"))
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
    # D: 文字なし 1 頁 → 白紙として FAIL (頁の検査)、 頁の検査を外せば PASS
    e = os.path.join(d, "d.pdf"); doc = fitz.open(); doc.new_page(); doc.save(e)
    fd, idd = inspect(e, template=b)
    assert any("白紙" in x for x in fd), fd
    fd2, _ = inspect(e, template=b, pages_check=False)
    assert not fd2, fd2
    # E: PyMuPDF の新規頁 (既定 A4) に用紙名が付く
    assert any(x.startswith("用紙: 210×297 mm (A4)") for x in idd), idd
    # F: 紙専用の印 (seal_artifact.MARKER) は raster 版へ引き継がれ、 印の無い入力には付かない
    f = os.path.join(d, "f.pdf"); doc = fitz.open(); doc.new_page(); mark_doc(doc); doc.save(f)
    g = os.path.join(d, "g.pdf"); rasterize(f, g, dpi=36)
    assert MARKER in (fitz.open(g).metadata.get("keywords") or "")
    h = os.path.join(d, "h.pdf"); rasterize(e, h, dpi=36)
    assert MARKER not in (fitz.open(h).metadata.get("keywords") or "")
    # G: 様式 2 頁 + 説明書き 2 頁 (宣言なし) → 頁の検査が FAIL、 --pages 1-2 で作った file は PASS
    four = os.path.join(d, "four.pdf")
    doc = fitz.open()
    for title in ("甲 申請書", "研究計画書", "本制度について", "【表示例】"):
        p = doc.new_page(); p.insert_text((72, 72), title, fontname="japan", fontsize=16)
        p.insert_text((72, 110), "本文", fontname="japan")
        p.draw_line((60, 200), (500, 200))
    mark_doc(doc)
    doc.save(four)
    f4, i4 = inspect(four)
    assert any("宣言が無い" in x for x in f4) and any("p.4 記載例?" in x for x in f4), f4
    assert any("p.3 ⚠️ 説明書き?" in x for x in i4), i4
    two = os.path.join(d, "two.pdf")
    write_selected(four, two, [1, 2], raster=True, dpi=36)
    f2, i2 = inspect(two, expect_pages=2)
    assert not f2, f2
    rec = read_record(fitz.open(two))
    assert [x["role"] for x in rec["pages"]] == ["submit", "submit"] and len(rec["dropped"]) == 2, rec
    assert MARKER in (fitz.open(two).metadata.get("keywords") or "")
    # H: 疑わしい頁を選ぶと _select が名指しする / 宣言で提出でない頁は宣言側で名指し
    _, flagged, off = _select(fitz.open(four), "3-4")
    assert len(flagged) == 2 and not off, (flagged, off)
    bad = fitz.open(two)
    write_record(bad, [{"role": "submit"}, {"role": "instructions", "label": "説明"}], "selftest")
    _, flagged, off = _select(bad, "all")
    assert off and not flagged, (flagged, off)
    # I: 変わった頁だけ刷り直す
    newer = fitz.open(four)
    newer[1].insert_text((72, 150), "訂正", fontname="japan")
    nf = os.path.join(d, "new.pdf"); newer.save(nf)
    assert changed_pages(fitz.open(nf), fitz.open(four)) == [2]
    # J: 宣言つき raster (頁を選ばない経路) は宣言を引き継ぐ
    r2 = os.path.join(d, "r2.pdf"); rasterize(two, r2, dpi=36)
    assert read_record(fitz.open(r2)) is not None and not inspect(r2)[0]
    print("pdf-print-preflight selftest: 10/10 PASS")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--template", help="雛形 PDF (page 数比較)")
    ap.add_argument("--expect-pages", type=int)
    ap.add_argument("--rasterize", metavar="OUT_PDF", help="検査後に RGB raster 版を書き出す")
    ap.add_argument("--extract", metavar="OUT_PDF", help="頁を選んだ vector 版を書き出す (--pages と使う)")
    ap.add_argument("--pages", help="OUT に入れる頁 = 窓口に出す頁 (all / 1-2,4 / changed)")
    ap.add_argument("--include-flagged", metavar="REASON", help="説明書き等に見える頁を理由つきで残す")
    ap.add_argument("--changed-from", metavar="OLD_PDF", help="前に刷った版と頁ごとに比べる")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return 0
    if not a.pdf:
        ap.error("pdf を指定 (or --selftest)")
    if a.rasterize and a.extract:
        ap.error("--rasterize と --extract はどちらか 1 つ")
    out = a.rasterize or a.extract
    if a.pages and not out:
        ap.error("--pages は --rasterize か --extract と使う (刷る頁だけの file を作る)")

    changed = None
    if a.changed_from:
        changed = changed_pages(fitz.open(a.pdf), fitz.open(a.changed_from))
        same = [k for k in range(1, fitz.open(a.pdf).page_count + 1) if k not in changed]
        print(f"  · 前に刷った版 ({os.path.basename(a.changed_from)}) と比べて変わった頁: "
              + (", ".join(f"p.{k}" for k in changed) or "なし") + " / 同じ頁: " + (", ".join(f"p.{k}" for k in same) or "なし"))
        if changed and same:
            print("    → 刷り直すのは変わった頁だけでよい: --pages changed")

    if a.pages:
        src_doc = fitz.open(a.pdf)
        try:
            sel, flagged, off = _select(src_doc, a.pages, changed)
        except ValueError as e:
            print(f"  🔴 {e}")
            return 1
        if off:
            print("  🔴 宣言で窓口に出さないとされた頁を選んでいる: " + ", ".join(off))
            if not a.include_flagged:
                print("  ✗ 書かない。 本当に刷るなら --include-flagged '<理由>'")
                return 1
        if flagged and not a.include_flagged:
            print("  🔴 窓口に出さない頁に見える頁を選んでいる: " + ", ".join(flagged))
            print("  ✗ 書かない。 --pages から外す。 本当に窓口に出す (or 読むために刷る) なら --include-flagged '<理由>'")
            return 1
        write_selected(a.pdf, out, sel, raster=bool(a.rasterize), dpi=a.dpi, include_flagged=a.include_flagged)
        kind = f"raster 版 ({a.dpi} dpi RGB)" if a.rasterize else "vector 版"
        print(f"  ✅ {kind}: {out} ({os.path.getsize(out)//1024} KB、 元の {src_doc.page_count} 頁から "
              + ", ".join(f"p.{k}" for k in sel) + " を提出頁として宣言) — 印刷はこちらを lp に渡す")
        findings, infos = inspect(out, a.expect_pages, a.template)
        for i in infos:
            print("  ·", i)
        for f in findings:
            print(" ", f)
        return 1 if findings else 0

    findings, infos = inspect(a.pdf, a.expect_pages, a.template)
    for i in infos:
        print("  ·", i)
    for f in findings:
        print(" ", f)
    if a.rasterize:
        out = rasterize(a.pdf, a.rasterize, a.dpi)
        print(f"  ✅ raster 版: {out} ({os.path.getsize(out)//1024} KB, {a.dpi} dpi RGB) — 印刷はこちらを lp に渡す")
        of, _ = inspect(out, a.expect_pages, a.template)
        page_bad = [f for f in of if f.startswith("🔴 頁:") or "page 数" in f]
        if page_bad:
            print("  ⚠️ この raster は頁の検査で止まる (lp の前の gate も同じ判定):")
            for f in page_bad:
                print("   ", f)
            print("   ", PAGE_FIX)
        return 0 if not any("page 数" in f or f.startswith("🔴 頁:") for f in of) else 1
    if a.extract:
        print("  🔴 --extract は --pages と使う")
        return 1
    if findings:
        print("  ✗ preflight FAIL — このまま lp に渡さない")
        return 1
    print("  ✓ preflight PASS (位置ずれは別途 crop 画像で目視)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
