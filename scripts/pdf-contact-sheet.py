#!/usr/bin/env python3
"""pdf-contact-sheet.py — PDF の頁 (スライド・図) を縮小して 1 枚の一覧 PNG に並べる。 --selftest 内蔵。

用途: スライドや図を組み直すたびに「全頁を一度に目で見る」 (beamer-slides.md §9 の視覚 QA ループ)。
1 頁ずつ画像にして開くと、 頁をまたぐ揃い (題の行数・余白・色の配分) と、 どの頁がはみ出したかが一度に見えない。
複数の PDF を渡すと順に並べる (図の PDF の束 = 1 file 1 頁 でもよい)。

- 透明な頁 (matplotlib の transparent=True の図) は --bg の色の上に置く。 暗い地の図は --bg '#121417' で見る
- 頁の縦横比は 1 つめの頁に揃えた枠に、 縦横比を保って収める
- 書き出すのは PyMuPDF だけ (PIL 不要): 1 枚の大きな頁に各頁を vector のまま置き、 最後に 1 回だけ画像にする

使い方:
  pdf-contact-sheet.py deck.pdf [--cols 3] [--width 1800] [--pages 1,3-5] [--bg '#FAFAF7'] [--labels] [--out sheet.png]
  pdf-contact-sheet.py figures/*.pdf --cols 4
  pdf-contact-sheet.py --selftest
--out の既定 = 一時 dir の `pdf-contact-sheet/<1 つめの名前>.png` (repo の中に画像を残さない = 中身の入った画像が commit に紛れない)。
--pages は 1 つの PDF を渡したときだけ効く。 OS: macOS / Linux / Windows (PyMuPDF だけ)。
"""
from __future__ import annotations

import argparse
import math
import sys
import tempfile
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    print("pdf-contact-sheet: PyMuPDF (fitz) が要る = pip install pymupdf", file=sys.stderr)
    sys.exit(2)


def parse_pages(spec: str | None, n: int) -> list[int]:
    """'1,3-5' → 0 始まりの頁番号の list。 None = 全頁。 範囲外は止める。"""
    if not spec:
        return list(range(n))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
        else:
            lo = hi = int(part)
        if lo < 1 or hi > n or lo > hi:
            raise ValueError(f"頁の指定 {part!r} が 1..{n} の外")
        out.extend(range(lo - 1, hi))
    return out


def hex_rgb(s: str) -> tuple[float, float, float]:
    s = s.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"色は #RRGGBB で: {s!r}")
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


def build(items: list[tuple[str, int]], cols: int, width: int, bg: str, gap: int = 6,
          labels: bool = False) -> "fitz.Pixmap":
    """items = [(pdf の path, 0 始まりの頁)]。 → 一覧の Pixmap (1 pt = 1 px)。"""
    if not items:
        raise ValueError("並べる頁が無い")
    docs: dict[str, fitz.Document] = {}

    def doc(p):
        if p not in docs:
            docs[p] = fitz.open(p)
        return docs[p]

    first = doc(items[0][0])[items[0][1]].rect
    cols = max(1, min(cols, len(items)))
    cell_w = (width - (cols - 1) * gap) / cols
    cell_h = cell_w * first.height / first.width
    rows = math.ceil(len(items) / cols)
    W, H = width, rows * cell_h + (rows - 1) * gap
    out = fitz.open()
    page = out.new_page(width=W, height=H)
    page.draw_rect(page.rect, color=None, fill=(0.63, 0.63, 0.63))
    fill = hex_rgb(bg)
    for k, (path, pno) in enumerate(items):
        x0 = (k % cols) * (cell_w + gap)
        y0 = (k // cols) * (cell_h + gap)
        r = fitz.Rect(x0, y0, x0 + cell_w, y0 + cell_h)
        page.draw_rect(r, color=None, fill=fill)
        page.show_pdf_page(r, doc(path), pno, keep_proportion=True)
        if labels:
            page.insert_text((r.x0 + 4, r.y0 + 12), f"{k + 1}", fontsize=10, color=(0.85, 0.1, 0.4))
    pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    for d in docs.values():
        d.close()
    return pix


def selftest() -> int:
    fails = []

    def check(cond, name):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "src.pdf"
        d = fitz.open()
        colors = [(1, 0, 0), (0, 0.6, 0), (0, 0, 1)]
        for c in colors:
            p = d.new_page(width=160, height=90)  # 16:9
            p.draw_rect(p.rect, color=None, fill=c)
        d.save(src)
        d.close()
        tr = Path(td) / "transparent.pdf"
        d = fitz.open()
        p = d.new_page(width=160, height=90)
        p.draw_rect(fitz.Rect(70, 35, 90, 55), color=None, fill=(0, 0, 0))
        d.save(tr)
        d.close()

        pix = build([(str(src), i) for i in range(3)], cols=2, width=406, bg="#FFFFFF", gap=6)
        check(pix.width == 406, "幅は --width の px")
        check(pix.height == round(2 * (200 * 90 / 160) + 6), "高さ = 行の数 × 枠の高さ (1 つめの頁の縦横比) + 隙間")
        check(pix.pixel(100, 56)[:3] == (255, 0, 0), "1 頁目は左上の枠")
        check(pix.pixel(306, 56)[:3] == (0, 153, 0), "2 頁目は右上の枠")
        check(pix.pixel(100, 174)[:3] == (0, 0, 255), "3 頁目は 2 行目の左")
        check(pix.pixel(306, 174)[:3] == (160, 160, 160), "余った枠は隙間の灰色")

        pix2 = build([(str(tr), 0)], cols=3, width=320, bg="#121417")
        check(pix2.pixel(10, 10)[:3] == (18, 20, 23), "透明な頁は --bg の色の上に置く")
        check(pix2.pixel(160, 90)[:3] == (0, 0, 0), "透明な頁の中身は残る")

        check(parse_pages("1,3-4", 5) == [0, 2, 3], "頁の指定 1,3-4")
        try:
            parse_pages("6", 5)
            check(False, "範囲外の頁は止める")
        except ValueError:
            check(True, "範囲外の頁は止める")
        try:
            hex_rgb("#12345")
            check(False, "色の形が違えば止める")
        except ValueError:
            check(True, "色の形が違えば止める")
    print("pdf-contact-sheet selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="PDF の頁を縮小して 1 枚の一覧 PNG に並べる")
    ap.add_argument("pdfs", nargs="*")
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--width", type=int, default=1800, help="一覧の幅 (px)")
    ap.add_argument("--pages", help="1 つの PDF の頁 (例 1,3-5)")
    ap.add_argument("--bg", default="#FAFAF7", help="頁の地の色 (透明な頁がこの上に乗る)")
    ap.add_argument("--labels", action="store_true", help="枠の左上に通し番号を入れる")
    ap.add_argument("--out", help="PNG の path (既定 = 一時 dir の pdf-contact-sheet/<名前>.png)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.pdfs:
        ap.error("PDF を 1 つ以上")
    items: list[tuple[str, int]] = []
    for path in args.pdfs:
        with fitz.open(path) as d:
            n = d.page_count
        pages = parse_pages(args.pages, n) if (args.pages and len(args.pdfs) == 1) else list(range(n))
        items.extend((path, i) for i in pages)
    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "pdf-contact-sheet" / (Path(args.pdfs[0]).stem + ".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    build(items, args.cols, args.width, args.bg, labels=args.labels).save(str(out))
    print(f"{out}  ({len(items)} 頁)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
