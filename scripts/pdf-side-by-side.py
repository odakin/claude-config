#!/usr/bin/env python3
"""2 つの PDF の同じ箇所を左右に並べた比較頁を作る: 案を決めるのは source でなく組版された姿。

用途は **gate ではなく意思決定**。 記法・語順・体裁に複数案があるとき、 source の diff を見せても
「実際どう見えるか」 は決められない (著者 2026-09-12「ソースだけじゃ分からん。 実際に見ないと」)。
各案を別に組んでおき、 決定点の語句を anchor にして左右 zoom を並べれば、 著者は 1 枚で選べる。

組版の機械比較 (error / 未定義参照 / overfull / label→頁 の drift) は別の道具の仕事:
ai-collaboration `scripts/compare-tex-builds.py`。 本 script は「人が見て選ぶ面」 だけを作る。

    python3 pdf-side-by-side.py --left a.pdf --right b.pdf \\
        --label-left 'subscript' --label-right 'superscript' \\
        --anchor 'The sum of the amputated' --anchor 'we obtain the LL WT identity' \\
        --out compare/

    python3 pdf-side-by-side.py --left a.pdf --right b.pdf --diff-pages   # 本文が違う頁を全部、頁ごと
    python3 pdf-side-by-side.py --selftest

出力: `<out>/compare.pdf` (1 anchor = 1 頁) と `<out>/cmp-NN.png` (同じものの画像、 chat に貼る用)。

注意 (実測 2026-09-12):
* **anchor は両版で同じ語句**を選ぶ。 案によって語句自体が変わる箇所は、 変わらない直前の文を anchor に。
* `--up/--down` は anchor 行の上下に何 pt 取るかで、 display を含めたいときは `--down` を大きく。
* 見つからない anchor は警告して飛ばす (片側だけ見つかった場合も)。 静かに欠けない。
* PNG は `--zoom` 倍で描く。 chat に貼るなら 1.5 前後が読める下限。
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - environment dependent
    fitz = None

MARGIN = 40.0  # 左右の余白を落として本文だけを切る


def _find(doc, phrase):
    for i, page in enumerate(doc):
        hits = page.search_for(phrase)
        if hits:
            return i, hits[0]
    return None, None


def _clip(rect, up, down, width, height):
    return fitz.Rect(MARGIN, max(0.0, rect.y0 - up), width - MARGIN, min(height, rect.y1 + down))


def build(left_path, right_path, anchors, out_dir, label_left, label_right, up, down, scale, zoom, diff_pages):
    left = fitz.open(left_path)
    right = fitz.open(right_path)
    width, height = left[0].rect.width, left[0].rect.height
    os.makedirs(out_dir, exist_ok=True)
    comp = fitz.open()
    missing = []

    def header(page, text_l, text_r, half):
        page.insert_text((8, 16), text_l, fontsize=11, color=(0.8, 0, 0))
        page.insert_text((half + 38, 16), text_r, fontsize=11, color=(0, 0, 0.8))

    for phrase in anchors:
        il, rl = _find(left, phrase)
        ir, rr = _find(right, phrase)
        if il is None or ir is None:
            missing.append((phrase, il is not None, ir is not None))
            continue
        cl = _clip(rl, up, down, width, height)
        cr = _clip(rr, up, down, width, height)
        w = cl.width
        h = max(cl.height, cr.height)
        page = comp.new_page(width=2 * w * scale + 30, height=h * scale + 24)
        header(page, "%s  p.%d  [%s]" % (label_left, il + 1, phrase[:48]), "%s  p.%d" % (label_right, ir + 1), w * scale)
        page.show_pdf_page(fitz.Rect(0, 24, w * scale, 24 + cl.height * scale), left, il, clip=cl)
        page.show_pdf_page(fitz.Rect(w * scale + 30, 24, 2 * w * scale + 30, 24 + cr.height * scale), right, ir, clip=cr)
        page.draw_line((w * scale + 15, 0), (w * scale + 15, h * scale + 24), color=(0.6, 0.6, 0.6))

    if diff_pages:
        for i in range(min(len(left), len(right))):
            if left[i].get_text() == right[i].get_text():
                continue
            page = comp.new_page(width=2 * width + 30, height=height + 24)
            header(page, "%s  p.%d" % (label_left, i + 1), "%s  p.%d" % (label_right, i + 1), width)
            page.show_pdf_page(fitz.Rect(0, 24, width, height + 24), left, i)
            page.show_pdf_page(fitz.Rect(width + 30, 24, 2 * width + 30, height + 24), right, i)
            page.draw_line((width + 15, 0), (width + 15, height + 24), color=(0.6, 0.6, 0.6))

    if not len(comp):
        print("no comparison page produced (no anchor matched, no differing page)", file=sys.stderr)
        return comp, missing
    pdf_path = os.path.join(out_dir, "compare.pdf")
    comp.save(pdf_path)
    for i, page in enumerate(comp):
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(os.path.join(out_dir, "cmp-%02d.png" % (i + 1)))
    print("%d comparison page(s) -> %s (+ cmp-NN.png)" % (len(comp), pdf_path))
    for phrase, in_left, in_right in missing:
        where = "left" if in_left else ("right" if in_right else "neither side")
        print("  ! anchor not paired (%s only): %s" % (where, phrase[:70]), file=sys.stderr)
    return comp, missing


def selftest():
    tmp = fitz.open()
    for text in ("alpha shared line\nleft variant body", "alpha shared line\nright variant body"):
        page = tmp.new_page()
        page.insert_text((72, 100), text.split("\n")[0], fontsize=12)
        page.insert_text((72, 130), text.split("\n")[1], fontsize=12)
    a = fitz.open()
    a.insert_pdf(tmp, from_page=0, to_page=0)
    b = fitz.open()
    b.insert_pdf(tmp, from_page=1, to_page=1)
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        pa, pb = os.path.join(d, "a.pdf"), os.path.join(d, "b.pdf")
        a.save(pa)
        b.save(pb)
        comp, missing = build(pa, pb, ["alpha shared line", "no such phrase"], os.path.join(d, "out"),
                              "L", "R", 6.0, 40.0, 1.6, 1.5, False)
        assert len(comp) == 1, len(comp)
        assert missing and missing[0][0] == "no such phrase", missing
        assert os.path.exists(os.path.join(d, "out", "cmp-01.png"))
    print("selftest OK (1 paired anchor, 1 unpaired reported)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="side-by-side comparison pages of two PDF variants")
    ap.add_argument("--left")
    ap.add_argument("--right")
    ap.add_argument("--anchor", action="append", default=[], help="phrase present in both PDFs (repeatable)")
    ap.add_argument("--diff-pages", action="store_true", help="also pair every page whose text differs")
    ap.add_argument("--label-left", default="LEFT")
    ap.add_argument("--label-right", default="RIGHT")
    ap.add_argument("--up", type=float, default=6.0, help="pt kept above the anchor line (default 6)")
    ap.add_argument("--down", type=float, default=120.0, help="pt kept below the anchor line (default 120)")
    ap.add_argument("--scale", type=float, default=1.6, help="magnification inside the comparison page")
    ap.add_argument("--zoom", type=float, default=1.5, help="PNG rendering factor")
    ap.add_argument("--out", default="pdf-side-by-side")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if fitz is None:
        print("PyMuPDF (fitz) is required: python3 -m pip install pymupdf", file=sys.stderr)
        return 2
    if a.selftest:
        selftest()
        return 0
    if not (a.left and a.right):
        ap.error("--left and --right are required (or --selftest)")
    if not a.anchor and not a.diff_pages:
        ap.error("give at least one --anchor, or --diff-pages")
    _, missing = build(a.left, a.right, a.anchor, a.out, a.label_left, a.label_right, a.up, a.down, a.scale, a.zoom, a.diff_pages)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
