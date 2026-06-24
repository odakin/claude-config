#!/usr/bin/env python3
"""雛形 PDF への直接印字エンジン (= office-automation.md #pdf-prefill-direct の汎用実装)。

行政・学術様式の「標題・押印マーク等が drawing の xlsx」 を openpyxl で編集すると drawing が
全消失する (#openpyxl-destroys-drawings)。 紙提出だけが必要な場合の最速安全経路 =
雛形 xlsx を Excel で PDF 化 (drawing は render 済) → その PDF に本エンジンで値を印字。

組み込み済みの安全装置 (= 2026-06-11 の印刷事故 3 連 RCA を全て機械化):
  - 座標は label 語の bbox から導出 (hardcode しない、 雛形改訂に頑健)
  - 文字照合は全て NFKC (= CJK 互換字形の false negative 回避, #pdf-text-match-nfkc)
  - `=TODAY()` 由来の `#+` overflow は redact で除去 (矩形 shrink で隣接巻き添え防止)
  - フォントは実 file 埋め込み + subset (組み込み "japan" は glyph 不描画 renderer あり)
  - 検証内蔵 (全挿入値の存在 + `##` 残存 + ページ数)
  - 印刷用に 600dpi ラスタ版も生成 (= subset font の printer RIP 化け対策, #print-raster-pdf)

使い方 (library): 様式ごとの driver script が import して使う。
    from pdf_form_fill import build_document
    build_document(template_pdf="form.pdf",
                   page_contains=["銀行振込口座"], page_not_contains=[],
                   items=[{"anchor": "所属:", "occurrence": 0, "dx": 8, "text": "〇〇学科"},
                          {"anchor": "殿", "align": "right", "dx": -4, "text": "山田 太郎"}],
                   out_base="out/dir/書類名")
  → 書類名_filled.pdf (確認用) + 書類名_raster.pdf (印刷用) を生成、 検証 fail は例外。

item の仕様:
  anchor      : ページ上の label 語 (NFKC 一致、 get_text("words") の 1 語)
  occurrence  : 同語が複数あるとき何番目か (y→x 順、 default 0)
  dx, dy      : anchor の右端 (align=left) / 左端 (align=right) からの offset (pt)
  align       : "left" (= anchor の右に置く、 default) / "right" (= text 右端を anchor 左端に合わせる)
  text        : 印字する文字列。 "\n" 区切りで複数行 (行送りは fontsize*1.45)
  size        : fontsize (default 9)
  verify      : False にすると検証対象から外す (= "✓" 等、 重複しうる短い記号用)
  type        : "check" で anchor (= "□..." 等の checkbox 語) の □ 内に ✓ をベクター描画
                (= font の ✓ glyph 有無に非依存)。 text 不要、 検証・二重印字 guard 対象外。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

import fitz

# overlay フォント候補 (= macOS の既知 path)。 ⚠️ 先頭 = 游ゴシック Regular (= Office 同梱)
# = Excel が吐く雛形 PDF の既定日本語フォント。 雛形と overlay でフォントが違うと太さ・字形が
# 不揃いになる (#pdf-prefill-font-match。 Arial Unicode は太く雛形と不揃いになった実害が origin)。
# 非 macOS (= Linux 等) ではこれらは存在しないので pick_font が fontconfig (fc-match) で
# Noto Sans CJK 等に解決し、 それも無ければ build_document(font=...) を要求する。
FONT_CANDIDATES = [
    "/Applications/Microsoft Excel.app/Contents/Resources/DFonts/YuGothR.ttc",
    "/Applications/Microsoft Word.app/Contents/Resources/DFonts/YuGothR.ttc",
    "/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts/YuGothR.ttc",
    "/Library/Fonts/Arial Unicode.ttf",          # fallback (= 太め、 雛形と不揃いになる)
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
]
# 雛形 PDF の埋込フォント基底名 (= subset prefix 除去後) → 揃える system font file。
KNOWN_TEMPLATE_FONTS = {
    "YuGothic": [
        "/Applications/Microsoft Excel.app/Contents/Resources/DFonts/YuGothR.ttc",
        "/Applications/Microsoft Word.app/Contents/Resources/DFonts/YuGothR.ttc",
    ],
    "Hiragino": ["/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"],
}
XLSX_TO_PDF = Path(__file__).resolve().parent / "xlsx-to-pdf.sh"

# 各種ダッシュ/ハイフンを ASCII '-' に畳む (= 埋込フォント subset がハイフン '-' を
# 抽出時 U+2010/U+2011 等に round-trip するため、 検証の substring 照合が空振りする。
# #pdf-text-match-nfkc の dash 拡張)。
_DASH_MAP = {ord(c): "-" for c in "‐‑‒–—―−﹣－"}


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def flat(s: str) -> str:
    """NFKC + ダッシュ正規化 (= 照合専用、 描画は変えない)。"""
    return nfkc(s).translate(_DASH_MAP)


def _first_existing(paths):
    return next((p for p in paths if Path(p).exists()), None)


def _has_cjk(path: str) -> bool:
    """font file が CJK glyph を持つか (= 「日」 で判定)。 fc-match は family 不在時に
    非 CJK のデフォルト font を返すため、 採用前に必ず CJK 被覆を検証する (= 豆腐防止)。"""
    try:
        return bool(fitz.Font(fontfile=path).has_glyph(ord("日")))
    except Exception:
        return False


def _fc_match(family: str):
    """非 macOS: fontconfig (fc-match) で family 名 → 実 font file を解決 (= OS 非依存の CJK 解決)。
    ⚠️ fc-match は不在 family でもデフォルト font を返すので、 CJK 被覆を検証してから返す。"""
    if not shutil.which("fc-match"):
        return None
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", family],
                             capture_output=True, text=True, timeout=5)
        p = out.stdout.strip()
        return p if p and Path(p).exists() and _has_cjk(p) else None
    except Exception:
        return None


# 非 macOS で CJK glyph を持つ font を family 名で探す順 (= fontconfig 経由)。
_CJK_FAMILIES = ("Yu Gothic", "Noto Sans CJK JP", "Noto Sans JP", "Hiragino Sans", "IPAGothic")


def pick_font(template_pdf=None) -> str:
    """overlay フォントを選ぶ。 template_pdf を渡すと雛形の埋込フォントに合わせる
    (#pdf-prefill-font-match)。 macOS は既知 path、 非 macOS は fontconfig で CJK font を解決。
    どれも無ければ FileNotFoundError (= build_document(font=...) で明示指定を要求)。"""
    if template_pdf is not None:
        try:
            doc = fitz.open(str(template_pdf))
            names = [f[3].split("+")[-1] for pg in doc for f in pg.get_fonts(full=True)]
            body = [n for n in names if "Bold" not in n]   # 値の本文は Regular に揃える
            for key, files in KNOWN_TEMPLATE_FONTS.items():
                if any(key in n for n in body):
                    hit = _first_existing(files) or _fc_match("Yu Gothic" if key == "YuGothic" else key)
                    if hit:
                        return hit
        except Exception:
            pass
    hit = _first_existing(FONT_CANDIDATES)          # macOS 既知 path (= 高速)
    if hit:
        return hit
    for fam in _CJK_FAMILIES:                        # 非 macOS (Linux 等): fontconfig で名前解決
        fc = _fc_match(fam)
        if fc:
            return fc
    raise FileNotFoundError(
        "CJK glyph を持つ font が見つかりません。 macOS は Office (游ゴシック) / Arial Unicode、 "
        "非 macOS は fontconfig に Noto Sans CJK 等を入れるか、 build_document(font='/path/to.ttf') "
        "で明示指定してください。")


def ensure_template_pdf(template_xlsx: Path) -> Path:
    """xlsx → PDF (Excel 経由、 drawing render 済)。 PDF が新しければ再生成しない。"""
    pdf = template_xlsx.with_suffix(".pdf")
    if not pdf.exists() or pdf.stat().st_mtime < template_xlsx.stat().st_mtime:
        subprocess.run(["zsh", str(XLSX_TO_PDF), str(template_xlsx)],
                       check=True, capture_output=True)
    if not pdf.exists():
        raise RuntimeError(f"雛形 PDF 生成失敗: {template_xlsx} (Excel が必要)")
    return pdf


def find_page(doc: "fitz.Document", contains: list, not_contains: list = ()) -> int:
    """内容特徴語でページを特定 (= ページ番号 hardcode 禁止)。"""
    for i, page in enumerate(doc):
        t = nfkc(page.get_text())
        if all(c in t for c in contains) and not any(c in t for c in not_contains):
            return i
    raise LookupError(f"該当ページなし: contains={contains}")


def word_rect(page, label: str, occurrence: int = 0) -> "fitz.Rect":
    hits = [fitz.Rect(w[:4]) for w in page.get_text("words") if nfkc(w[4]) == nfkc(label)]
    hits.sort(key=lambda r: (round(r.y0), r.x0))
    if len(hits) <= occurrence:
        raise LookupError(f"anchor 語「{label}」(#{occurrence}) が見つからない (雛形改訂?)")
    return hits[occurrence]


def _draw_check(page, r: "fitz.Rect") -> None:
    """anchor (= "□普通" 等の checkbox 語) の □ 内に ✓ をベクター描画。
    font の ✓ glyph 有無に依存せず確実に印字する (= □ は語頭の全角1字、 r.x0 が □ の左端)。"""
    bw = r.y1 - r.y0
    x0 = r.x0 + 1.0
    p1 = fitz.Point(x0 + 1.0, r.y0 + bw * 0.55)
    p2 = fitz.Point(x0 + bw * 0.42, r.y1 - 1.5)
    p3 = fitz.Point(x0 + bw * 0.95, r.y0 + 1.5)
    page.draw_line(p1, p2, width=1.1, color=(0, 0, 0))
    page.draw_line(p2, p3, width=1.1, color=(0, 0, 0))


def redact_hash_runs(page) -> int:
    """`####` 等 (= =TODAY() の列幅 overflow、 個数は出力時の列幅依存) を除去。"""
    rects = [fitz.Rect(w[:4]) for w in page.get_text("words") if re.fullmatch(r"#+", w[4])]
    for r in rects:
        page.add_redact_annot(fitz.Rect(r.x0 + 2, r.y0 + 1, r.x1, r.y1 - 1))
    if rects:
        page.apply_redactions()
    return len(rects)


def redact_words(page, words: list) -> int:
    """数式由来の不要表示 (= 例: 空参照の "0") を語単位で除去。 矩形は shrink。"""
    rects = [fitz.Rect(w[:4]) for w in page.get_text("words") if w[4] in words]
    for r in rects:
        page.add_redact_annot(fitz.Rect(r.x0 + 0.5, r.y0 + 0.5, r.x1 - 0.5, r.y1 - 0.5))
    if rects:
        page.apply_redactions()
    return len(rects)


def build_document(template_pdf, page_contains, items, out_base,
                   page_not_contains=(), drop_words=(), dpi=600,
                   font=None, check_double_print=True, assert_present=()) -> dict:
    """1 書類 (= 1 ページ) を生成。 return = {"filled": path, "raster": path}。

    font=None なら雛形 PDF の埋込フォントに自動マッチ (#pdf-prefill-font-match)。
    check_double_print=True で「雛形に既に存在する値を再印字 = 二重印字」 を検出して
    例外 (#pdf-prefill-template-prefilled)。 申請者欄等が雛形に prefill 済の様式で、
    その値を誤って item に入れると重なる事故を loud fail させる (= 黙って二重刷りを防ぐ)。
    雛形が legitimately 同値を持つ item は `allow_preexisting: True` で個別 opt-out。
    assert_present = 雛形に prefill 済で item には入れない値 (= 申請者ブロック等) のうち、
    出力に存在することを sanity-check したいもの。 別財源で雛形を差し替えて prefill 値が
    欠落した時に loud fail させる (= check_double_print の対称: 再印字を止める一方、 こちらは
    「在るべき prefill が消えていないか」 を検証。 #pdf-prefill-template-prefilled)。"""
    font = font or pick_font(template_pdf)
    src = fitz.open(str(template_pdf))
    pno = find_page(src, list(page_contains), list(page_not_contains))
    doc = fitz.open()
    doc.insert_pdf(src, from_page=pno, to_page=pno)
    page = doc[0]

    # --- 二重印字 guard (= 雛形に既に値がある欄を item に入れていないか、 印字前に検出) ---
    if check_double_print:
        base_t = flat(page.get_text()).replace(" ", "").replace("\n", "")
        clashes = sorted({
            str(it["text"]) for it in items
            if it.get("type") != "check"
            and it.get("verify", True) and not it.get("allow_preexisting", False)
            and len(str(it["text"]).strip()) >= 2
            and flat(str(it["text"]).replace("\n", "")).replace(" ", "") in base_t
        })
        if clashes:
            raise AssertionError(
                f"二重印字の恐れ ({out_base}): 次の値は雛形 PDF に既に存在する "
                f"(= item から外すか allow_preexisting:True、 #pdf-prefill-template-prefilled): {clashes}")

    redact_hash_runs(page)
    if drop_words:
        redact_words(page, list(drop_words))

    overlay_font = fitz.Font(fontfile=font)   # = 右寄せ印字の文字幅計測用 (= fitz.Font.text_length)
    for it in items:
        r = word_rect(page, it["anchor"], it.get("occurrence", 0))
        if it.get("type") == "check":
            _draw_check(page, r)
            continue
        size = it.get("size", 9)
        F = dict(fontname="JPF", fontfile=font, fontsize=size)
        lines = str(it["text"]).split("\n")
        if it.get("align", "left") == "right":
            width = max(overlay_font.text_length(ln, fontsize=size) for ln in lines)
            x = r.x0 - width + it.get("dx", -4)
        else:
            x = r.x1 + it.get("dx", 6)
        y = r.y1 + it.get("dy", 0)
        for ln in lines:
            page.insert_text((x, y), ln, **F)
            y += size * 1.45

    doc.subset_fonts()
    out_filled = Path(f"{out_base}_filled.pdf")
    out_filled.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_filled, garbage=3, deflate=True)

    # --- 検証 (機械層): 全値の存在 (NFKC + dash 正規化) + ## 残存 + ページ数 ---
    t = flat(fitz.open(out_filled)[0].get_text())
    expected = [str(it["text"]).replace("\n", "") for it in items
                if it.get("verify", True) and it.get("type") != "check"]
    expected += [str(x) for x in assert_present]   # = 雛形 prefill 済の sanity-check (欠落で fail)
    missing = [e for e in expected if flat(e).replace(" ", "") not in t.replace(" ", "").replace("\n", "")]
    if missing or "##" in t or fitz.open(out_filled).page_count != 1:
        raise AssertionError(f"検証 FAIL ({out_base}): missing={missing} hash={'##' in t}")

    # --- 印刷用ラスタ (WYSIWYG 保証) ---
    pg = fitz.open(out_filled)[0]
    png = out_filled.with_suffix(".tmp.png")
    pg.get_pixmap(dpi=dpi).save(png)
    rast = fitz.open()
    np_ = rast.new_page(width=pg.rect.width, height=pg.rect.height)
    np_.insert_image(np_.rect, filename=str(png))
    out_raster = Path(f"{out_base}_raster.pdf")
    rast.save(out_raster, deflate=True)
    png.unlink()
    return {"filled": out_filled, "raster": out_raster}
