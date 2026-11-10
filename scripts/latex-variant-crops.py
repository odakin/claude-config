#!/usr/bin/env python3
"""同じ LaTeX 原稿を組み替えた版 (書体・macro・版面の候補) から、 同じ source の範囲を synctex で切り出して版ごとに縦に並べ、 見比べの 1 枚の PNG にする。--selftest 内蔵、規律 = conventions/latex.md#variant-comparison-images

使い方 (各版の dir に、 写した .tex と、 それを `-synctex=1` で組んだ PDF と .synctex.gz がある):

    python3 latex-variant-crops.py --tex main.tex \
        --variant now=build/cur --variant b=build/b --variant d=build/d \
        --caption 'now=Computer Modern Sans|upright' --caption 'b=Latin Modern Sans|slanted' \
        --region '1. First display|We now compare the two terms|where $\\vmag:=' \
        --region '2. Appendix display|\\label{eq:sum-rule}|which proves the bound' \
        --dpi 220 --colors 128 --out compare.png

- `--region 'TITLE|START|END'`: START と END は .tex の中の文字列 (正規表現ではない)。 START を含む行から、
  その行以降で END を最初に含む行までを 1 つの範囲にする。 版ごとに自分の .tex で行を探すので、 preamble に
  行を足した版でも同じ範囲が取れる (行番号で指すと版ごとにずれる)。 START はどの版の .tex でも 1 回だけ
  現れること (2 回以上なら止める = 版の間で別の所を切り出さないため)。
- 範囲の各行を `synctex view -i 行:0:<tex> -o <pdf>` で引き、 最初に出る頁の箱の上端から最後の箱の基準線までを、
  左右の余白 (`--margin`、 pt) を除いた幅で描く。 下端は基準線の後の最初の白い行で切る (次の行の頭を入れない)。
  範囲が頁をまたぐなら最初の頁の分だけを描き、 そう出力に書く。
- 版の札は `--variant` の LABEL、 札の下の小さい行は `--caption 'LABEL=1 行目|2 行目'`。
  札・題は欧文で書く (PNG の文字は Helvetica = 日本語の字形が無い)。
- `--colors N` は色を N 色に減らす (文字と罫だけの画像は 128 色で見た目が変わらず 半分以下の大きさになる)。

出力の切り出しの数値 (版・範囲ごとの頁・上端・下端) を表で出す = 切り出しの再現の記録。
要るもの: synctex (TeX Live)、 PyMuPDF、 Pillow。 原稿を組むのはこの道具の外 (`latexmk` を各版の dir で)。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

LABEL_W, PAD, GAP, TITLE_H = 330, 18, 6, 70
FONT = "/System/Library/Fonts/Helvetica.ttc"


def anchor_lines(text: str, start: str, end: str) -> tuple[int, int]:
    """START を含む行 (1 つだけ) から、 その行以降で END を最初に含む行まで = (first, last) (1 から)。"""
    lines = text.split("\n")
    hits = [i for i, ln in enumerate(lines) if start in ln]
    if len(hits) != 1:
        raise ValueError(f"start anchor {start!r} occurs {len(hits)} times (need exactly 1)")
    a = hits[0]
    for j in range(a, len(lines)):
        if end in lines[j]:
            return a + 1, j + 1
    raise ValueError(f"end anchor {end!r} not found at or after line {a + 1}")


def parse_synctex(out: str) -> list[tuple[int, float, float]]:
    """`synctex view` の出力を [(頁, 箱の上端 = v - H, 基準線 v)] にする (pt、 頁の左上が原点)。"""
    boxes = []
    for blk in out.split("Output:")[1:]:
        g = dict(re.findall(r"^(\w+):(.*)$", blk, re.M))
        if {"Page", "v", "H"} <= set(g):
            boxes.append((int(g["Page"]), float(g["v"]) - float(g["H"]), float(g["v"])))
    return boxes


def region_rect(boxes: list[tuple[int, float, float]], pad_top: float = 4.0) -> tuple[int, float, float, bool]:
    """箱の並び → (頁, 上端, 基準線の最大, 頁をまたいだか)。 最初に出る頁 (番号の最小) の箱だけを使う。"""
    if not boxes:
        raise ValueError("synctex returned no box for this range (was the PDF built with -synctex=1?)")
    page = min(p for p, _, _ in boxes)
    on = [b for b in boxes if b[0] == page]
    return page, min(t for _, t, _ in on) - pad_top, max(v for _, _, v in on), len(on) != len(boxes)


def cut_at_white(img, start_row: int, threshold: int = 250):
    """start_row 以降で最初の白い行 (全画素が threshold 以上) の 2 px 下で切る。 無ければ切らない。"""
    for y in range(max(0, start_row), img.height):
        if all(lo >= threshold for lo, _ in img.crop((0, y, img.width, y + 1)).getextrema()):
            return img.crop((0, 0, img.width, min(y + 2, img.height)))
    return img


def synctex_boxes(vdir: Path, tex: str, pdf: str, line: int) -> list[tuple[int, float, float]]:
    out = subprocess.run(["synctex", "view", "-i", f"{line}:0:{tex}", "-o", pdf],
                         cwd=vdir, capture_output=True, text=True).stdout
    return parse_synctex(out)


def crop_region(vdir: Path, tex: str, first: int, last: int, dpi: int, margin: float):
    import fitz
    from PIL import Image
    pdf = Path(tex).stem + ".pdf"
    boxes = [b for ln in range(first, last + 1) for b in synctex_boxes(vdir, tex, pdf, ln)]
    page, top, base, spans = region_rect(boxes)
    pg = fitz.open(str(vdir / pdf))[page - 1]
    pix = pg.get_pixmap(dpi=dpi, clip=fitz.Rect(margin, top, pg.rect.width - margin, base + 9))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img = cut_at_white(img, int((base + 1 - top) * dpi / 72))
    return img, {"page": page, "top": round(top, 1), "base": round(base, 1), "spans_pages": spans,
                 "px": img.size}


def compose(blocks: list[tuple[str, list[tuple[str, list[str], object]]]]):
    """[(題, [(札, 札の下の行, 切り出した画像)])] → 1 枚の画像。"""
    from PIL import Image, ImageDraw, ImageFont
    try:
        ft, fl, fs = (ImageFont.truetype(FONT, n) for n in (40, 44, 26))
    except OSError:
        ft = fl = fs = ImageFont.load_default()
    out = []
    for title, strips in blocks:
        w = LABEL_W + max(s.width for _, _, s in strips)
        h = TITLE_H + sum(s.height + GAP for _, _, s in strips) + PAD
        b = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(b)
        d.rectangle([0, 0, w, TITLE_H - 10], fill=(232, 236, 244))
        d.text((PAD, 14), title, fill="black", font=ft)
        y = TITLE_H
        for k, (label, caption, s) in enumerate(strips):
            d.rectangle([0, y, LABEL_W - 12, y + s.height], fill=(244, 244, 244))
            d.text((PAD, y + 12), label, fill=(60, 60, 60) if k == 0 else (170, 30, 30), font=fl)
            for n, line in enumerate(caption):
                d.text((PAD, y + 66 + 32 * n), line, fill="black", font=fs)
            b.paste(s, (LABEL_W, y))
            d.line([LABEL_W, y + s.height + GAP // 2, w, y + s.height + GAP // 2], fill=(200, 200, 200), width=1)
            y += s.height + GAP
        out.append(b)
    img = Image.new("RGB", (max(b.width for b in out), sum(b.height for b in out) + 20 * (len(out) - 1)), "white")
    y = 0
    for b in out:
        img.paste(b, (0, y))
        y += b.height + 20
    return img


def selftest() -> int:
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    tex = "\\documentclass{article}\n\\newcommand{\\x}{y}\n\\begin{document}\nAlpha start here\nmiddle\nthe end mark\nagain the end mark\n\\end{document}\n"
    check("anchors: start line through the first end line after it", anchor_lines(tex, "start here", "end mark") == (4, 6))
    shifted = tex.replace("\\newcommand{\\x}{y}\n", "\\newcommand{\\x}{y}\n\\newcommand{\\z}{w}\n")
    check("anchors: a line added to the preamble shifts both ends by one (why anchors, not line numbers)",
          anchor_lines(shifted, "start here", "end mark") == (5, 7))
    for bad, why in (("the end mark", "a start anchor that occurs twice is refused  [foil]"),
                     ("not in text", "a missing start anchor is refused  [foil]")):
        try:
            anchor_lines(tex, bad, "x")
            check(why, False)
        except ValueError:
            check(why, True)
    out = ("This is SyncTeX command line utility\nSyncTeX result begin\n"  # synthetic boxes
           "Output:main.pdf\nPage:3\nx:150.0\ny:190.0\nh:150.0\nv:200.0\nW:100.0\nH:20.0\nbefore:\n"
           "Output:main.pdf\nPage:3\nx:80.0\ny:145.0\nh:80.0\nv:150.0\nW:400.0\nH:10.0\nbefore:\n"
           "Output:main.pdf\nPage:4\nx:80.0\ny:95.0\nh:80.0\nv:100.0\nW:400.0\nH:10.0\nSyncTeX result end\n")
    bx = parse_synctex(out)
    check("synctex: three boxes with top = v - H", [round(t, 1) for _, t, _ in bx] == [180.0, 140.0, 90.0])
    page, top, base, spans = region_rect(bx)
    check("region: the first page only, top padded by 4 pt, base = largest baseline, page break reported",
          (page, round(top, 1), base, spans) == (3, 136.0, 200.0, True))
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("[SKIP] image checks: Pillow not installed")
        return 0 if ok else 1
    im = Image.new("RGB", (100, 60), "white")
    dr = ImageDraw.Draw(im)
    dr.rectangle([10, 5, 90, 20], fill="black")    # the region's last line
    dr.rectangle([10, 40, 90, 55], fill="black")   # the next line's ascenders
    check("white cut: stops in the gap before the next line", cut_at_white(im, 21).height == 23)
    check("white cut: no white row below -> unchanged", cut_at_white(Image.new("RGB", (5, 5), "black"), 0).height == 5)
    s = Image.new("RGB", (400, 50), "white")
    c = compose([("T", [("now", ["a", "b"], s), ("b", [], s)]), ("U", [("now", [], s)])])
    check("compose: width = label column + strip, height = titles + strips + gaps",
          c.size == (LABEL_W + 400, (TITLE_H + 2 * (50 + GAP) + PAD) + 20 + (TITLE_H + 50 + GAP + PAD)))
    have = all(shutil.which(t) for t in ("synctex",))
    print("[INFO] synctex on PATH" if have else "[SKIP] synctex not on PATH (only the pure functions were checked)")
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tex", help="the .tex file name inside each variant dir (e.g. main.tex)")
    p.add_argument("--variant", action="append", default=[], metavar="LABEL=DIR",
                   help="a built variant; the first one is drawn as the reference (grey label)")
    p.add_argument("--caption", action="append", default=[], metavar="LABEL=LINE|LINE",
                   help="small lines under a variant label")
    p.add_argument("--region", action="append", default=[], metavar="TITLE|START|END")
    p.add_argument("--dpi", type=int, default=220)
    p.add_argument("--margin", type=float, default=72.0, help="left/right margin cut away, in pt (default 72)")
    p.add_argument("--colors", type=int, default=0, help="reduce to N colours (0 = keep RGB)")
    p.add_argument("--out", type=Path)
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        return selftest()
    if not (a.tex and a.variant and a.region and a.out):
        p.error("give --tex, --variant (one or more), --region (one or more) and --out")
    if not shutil.which("synctex"):
        print("synctex not on PATH (TeX Live)", file=sys.stderr)
        return 2
    variants = []
    for v in a.variant:
        label, _, d = v.partition("=")
        variants.append((label, Path(d)))
    captions = {}
    for c in a.caption:
        label, _, rest = c.partition("=")
        captions[label] = rest.split("|") if rest else []
    blocks = []
    print("region | variant | lines | page | top pt | base pt | px")
    for spec in a.region:
        parts = spec.split("|")
        if len(parts) != 3:
            p.error(f"--region needs TITLE|START|END: {spec!r}")
        title, start, end = parts
        strips = []
        for label, vdir in variants:
            first, last = anchor_lines((vdir / a.tex).read_text(encoding="utf-8"), start, end)
            img, info = crop_region(vdir, a.tex, first, last, a.dpi, a.margin)
            note = "  (range continues on the next page: only the first page drawn)" if info["spans_pages"] else ""
            print(f"{title} | {label} | {first}-{last} | {info['page']} | {info['top']} | {info['base']} | "
                  f"{info['px'][0]}x{info['px'][1]}{note}")
            strips.append((label, captions.get(label, []), img))
        blocks.append((title, strips))
    img = compose(blocks)
    if a.colors:
        from PIL import Image
        img = img.quantize(colors=a.colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    img.save(a.out, dpi=(a.dpi, a.dpi), optimize=True)
    print(f"wrote {a.out} {img.size[0]}x{img.size[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
