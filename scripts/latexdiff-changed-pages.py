#!/usr/bin/env python3
"""latexdiff の PDF から、 差分の色 (追加・削除) が出ている頁だけを残す: 変わった頁を印でなく差分そのもので選ぶ。

共著者に「変わった頁だけ」 の diff PDF を渡すとき、 頁を項目の印 (`\\itemtag{A1}` など) のある頁で選ぶと、
**頁をまたぐ節・段落・式の続きの頁が落ちる** (印は変更の書き出しに 1 つしか付かないため。 実測)。
本 script は各頁の文字と線・矩形の色を見て、 latexdiff の追加色・削除色が 1 つでもある頁を全部残す。
印は頁を選ぶためでなく、 一覧と照らして読むための目印として使う (規約 = conventions/latex.md#latexdiff-item-labels)。

    python3 latexdiff-changed-pages.py diff.pdf                         # diff.pdf をその場で絞る
    python3 latexdiff-changed-pages.py diff.pdf --out changed.pdf --keep 1   # 1 頁目 (説明の頁) は必ず残す
    python3 latexdiff-changed-pages.py diff.pdf --list                  # 絞らずに頁番号だけ出す
    python3 latexdiff-changed-pages.py diff.pdf --render DIR            # 差分の頁の画像と、 色の所の拡大を DIR に書く (PDF は変えない)
    python3 latexdiff-changed-pages.py --selftest

`--render` は、 組版エラー 0・無印 0 の後に変えた所を目で確かめる段 (conventions/latex.md#latexdiff-fine-markup) の画像を作る:
差分の色がある頁の全体 (`pNN.png`) と、 色の付いた文字・線を段 (2 段組の左右) ごとに縦に近いものでまとめた拡大 (`pNN-K.png`)。
印の付き方 (足した行の印がずれていないか、 消した式が読めるか) は拡大で見る。 手で頁を切り出して画像にする作業が繰り返し要ったため (実測)。

色の既定 = latexdiff の `--type=UNDERLINE` / `CFONT` / `COLOR` の既定 (追加 = blue `#0000ff`、 削除 = red `#ff0000`)。
preamble で色を変えた原稿は `--color '#rrggbb'` を繰り返して渡す (渡すと既定を置き換える)。
文字の色 (追加・削除の本文、 着色された数式) に加えて、 線と矩形の色 (`\\sout` の取消線、 新しい図の枠) も見る。

注意:
* 原稿そのものが同じ色を使っている (`hyperref` の `colorlinks` で link が blue、 `\\textcolor{red}` の注記) と、
  変わっていない頁も残る。 残りすぎたら `--list` で頁を見て、 原稿の色と被らない差分の色を preamble で決める。
* 1 頁も差分の色が無いときは exit 1 で止まる (= 色の設定が原稿と合っていない、 または差分が空。 黙って空の PDF を作らない)。
* 文字を持たない図 (画像だけの差し替え) は、 latexdiff が枠を付けない設定だと拾えない。 図の頁は `--keep` で足す。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

DEFAULT_COLORS = ("#0000ff", "#ff0000")


def parse_color(s: str) -> tuple[float, float, float]:
    h = s.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"color は #rrggbb で渡す: {s!r}")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _close(a, b, tol=0.02) -> bool:
    return a is not None and len(a) >= 3 and all(abs(float(x) - y) <= tol for x, y in zip(a[:3], b))


def _span_rgb(c: int) -> tuple[float, float, float]:
    return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0


def page_has_colors(page, colors) -> bool:
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if not span.get("text", "").strip():
                    continue
                rgb = _span_rgb(int(span.get("color", 0)))
                if any(_close(rgb, c) for c in colors):
                    return True
    for d in page.get_drawings():
        for key in ("color", "fill"):
            if any(_close(d.get(key), c) for c in colors):
                return True
    return False


def colored_rects(page, colors) -> list:
    """差分の色を持つ文字の span と線・矩形の範囲 (fitz.Rect) の一覧。"""
    import fitz
    out = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip() and any(_close(_span_rgb(int(span.get("color", 0))), c) for c in colors):
                    out.append(fitz.Rect(span["bbox"]))
    for d in page.get_drawings():
        if any(_close(d.get(key), c) for key in ("color", "fill") for c in colors):
            out.append(fitz.Rect(d["rect"]))
    return out


def change_clusters(page, colors, gap: float = 40.0) -> list:
    """色の範囲を段 (左右) ごとに、 縦の隙間が gap pt 以下のものでまとめた拡大の範囲。 段をまたぐ範囲 (1 段の概要など) は全幅。"""
    import fitz
    w, mid = page.rect.width, page.rect.width / 2
    groups: dict[str, list] = {"L": [], "R": [], "W": []}
    for r in colored_rects(page, colors):
        if r.x0 < mid - 5 and r.x1 > mid + 5:
            groups["W"].append(r)
        else:
            groups["L" if (r.x0 + r.x1) / 2 < mid else "R"].append(r)
    xs = {"L": (8.0, mid + 2), "R": (mid - 2, w - 8.0), "W": (8.0, w - 8.0)}   # 段の境で行の頭・末尾を切らない
    found: dict[str, list] = {}
    for key in ("W", "L", "R"):
        found[key] = []
        for r in sorted(groups[key], key=lambda r: r.y0):
            if found[key] and r.y0 - found[key][-1].y1 <= gap:
                found[key][-1] |= r
            else:
                found[key].append(fitz.Rect(r))
    # 1 段の塊 (概要など) の中の短い span は左右に振り分けられる = 全幅の塊と縦に重なる左右の塊は全幅の塊に入れる
    changed = True
    while changed:
        changed = False
        for i in range(len(found["W"])):
            for key in ("L", "R"):
                for r in list(found[key]):
                    wr = found["W"][i]
                    if r.y0 <= wr.y1 + gap and r.y1 >= wr.y0 - gap:
                        found["W"][i] = wr | r      # Rect の |= は名前を付け替えるだけなので、 一覧に書き戻す
                        found[key].remove(r)
                        changed = True
    clips = [fitz.Rect(xs[key][0], max(0, r.y0 - 30), xs[key][1], min(page.rect.height, r.y1 + 24))
             for key in ("W", "L", "R") for r in found[key]]
    return sorted(clips, key=lambda r: (r.y0, r.x0))


def render_changes(pdf_path: str, colors, outdir: str, zoom: float = 2.2, page_zoom: float = 0.8) -> list[str]:
    """差分の色がある頁の全体と、 色の所の拡大を PNG に書く。 書いた file の一覧を返す。"""
    import fitz
    os.makedirs(outdir, exist_ok=True)
    doc = fitz.open(pdf_path)
    written = []
    try:
        for i, pg in enumerate(doc):
            if not page_has_colors(pg, colors):
                continue
            p = os.path.join(outdir, f"p{i + 1:02d}.png")
            pg.get_pixmap(matrix=fitz.Matrix(page_zoom, page_zoom)).save(p)
            written.append(p)
            for k, clip in enumerate(change_clusters(pg, colors), 1):
                q = os.path.join(outdir, f"p{i + 1:02d}-{k}.png")
                pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip).save(q)
                written.append(q)
    finally:
        doc.close()
    return written


def changed_pages(pdf_path: str, colors) -> tuple[list[int], int]:
    import fitz
    doc = fitz.open(pdf_path)
    try:
        return [i + 1 for i, pg in enumerate(doc) if page_has_colors(pg, colors)], len(doc)
    finally:
        doc.close()


def write_pages(src: str, pages: list[int], out: str) -> None:
    import fitz
    d = fitz.open(src)
    o = fitz.open()
    for p in pages:
        o.insert_pdf(d, from_page=p - 1, to_page=p - 1)
    d.close()
    tmp = out + ".tmp.pdf"
    o.save(tmp)
    o.close()
    os.replace(tmp, out)


def selftest() -> int:
    import fitz
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "diff.pdf")
        doc = fitz.open()
        p = doc.new_page(); p.insert_text((72, 72), "unchanged page", color=(0, 0, 0))
        p = doc.new_page(); p.insert_text((72, 72), "added text", color=(0, 0, 1))
        p = doc.new_page(); p.insert_text((72, 72), "deleted text body", color=(0, 0, 0))
        p.draw_rect(fitz.Rect(72, 80, 200, 81), color=(1, 0, 0), fill=(1, 0, 0))  # \sout の線
        p = doc.new_page(); p.insert_text((72, 72), "continuation in black", color=(0, 0, 0))
        p = doc.new_page(); p.insert_text((72, 72), "custom color", color=(0, 0.5, 0))
        doc.save(src); doc.close()
        cols = [parse_color(c) for c in DEFAULT_COLORS]
        got, n = changed_pages(src, cols)
        assert n == 5 and got == [2, 3], got
        got2, _ = changed_pages(src, [parse_color("#008000")])
        assert got2 == [5], got2
        out = os.path.join(td, "out.pdf")
        write_pages(src, sorted(set(got) | {1}), out)
        d = fitz.open(out); m = len(d); first = d[0].get_text(); d.close()
        assert m == 3 and "unchanged page" in first, (m, first)
        try:
            parse_color("blue")
        except ValueError:
            pass
        else:
            raise AssertionError("bad color accepted")
        # --render: 色のある頁 (2・3) の全体と拡大だけを書く。 2 段の左右に離れた追加は別の拡大になる
        p = fitz.open(src)
        pg = p.new_page(); pg.insert_text((60, 100), "left added", color=(0, 0, 1)); pg.insert_text((400, 500), "right added", color=(0, 0, 1))
        p.save(os.path.join(td, "diff2.pdf")); p.close()
        rd = os.path.join(td, "views")
        files = render_changes(os.path.join(td, "diff2.pdf"), cols, rd)
        names = sorted(os.path.basename(f) for f in files)
        assert names == ["p02-1.png", "p02.png", "p03-1.png", "p03.png", "p06-1.png", "p06-2.png", "p06.png"], names
        assert all(os.path.getsize(f) > 0 for f in files)
        # 全幅の行と、 同じ高さの左右の短い span は 1 枚の拡大にまとまり、 範囲は両方を含む
        q = fitz.open(); pg = q.new_page()
        pg.insert_text((60, 200), "a full-width added line that crosses the middle of the page", color=(0, 0, 1))
        pg.insert_text((60, 215), "left", color=(0, 0, 1)); pg.insert_text((420, 230), "right", color=(0, 0, 1))
        cl = change_clusters(pg, cols)
        assert len(cl) == 1 and cl[0].y1 >= 230 and cl[0].y0 <= 190, cl
        q.close()
    print("selftest: 6 checks ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--out", help="出力先 (既定 = 入力をその場で置き換える)")
    ap.add_argument("--keep", type=int, action="append", default=[], help="必ず残す頁 (1 始まり、 繰り返し可)")
    ap.add_argument("--color", action="append", default=[], help="差分の色 #rrggbb (繰り返し可、 渡すと既定を置き換える)")
    ap.add_argument("--list", action="store_true", help="絞らずに、 差分の色がある頁番号だけ出す")
    ap.add_argument("--render", metavar="DIR", help="絞らずに、 差分の頁の画像 (pNN.png) と色の所の拡大 (pNN-K.png) を DIR に書く")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.pdf:
        ap.error("PDF を渡す")
    colors = [parse_color(c) for c in (a.color or DEFAULT_COLORS)]
    got, n = changed_pages(a.pdf, colors)
    if not got:
        print(f"差分の色の頁が 0 (全 {n} 頁)。 色の設定 (--color) と原稿の preamble を確かめる", file=sys.stderr)
        return 1
    keep = sorted(set(got) | {k for k in a.keep if 1 <= k <= n})
    print("changed", got, "kept", keep, f"of {n}")
    if a.render:
        for f in render_changes(a.pdf, colors, a.render):
            print(f)
        return 0
    if a.list:
        return 0
    write_pages(a.pdf, keep, a.out or a.pdf)
    print(a.out or a.pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
