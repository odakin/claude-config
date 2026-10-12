#!/usr/bin/env python3
"""latexdiff の PDF から、 差分の色 (追加・削除) が出ている頁だけを残す: 変わった頁を印でなく差分そのもので選ぶ。

共著者に「変わった頁だけ」 の diff PDF を渡すとき、 頁を項目の印 (`\\itemtag{A1}` など) のある頁で選ぶと、
**頁をまたぐ節・段落・式の続きの頁が落ちる** (印は変更の書き出しに 1 つしか付かないため。 実測)。
本 script は各頁の文字と線・矩形の色を見て、 latexdiff の追加色・削除色が 1 つでもある頁を全部残す。
印は頁を選ぶためでなく、 一覧と照らして読むための目印として使う (規約 = conventions/latex.md#latexdiff-item-labels)。

    python3 latexdiff-changed-pages.py diff.pdf                         # diff.pdf をその場で絞る
    python3 latexdiff-changed-pages.py diff.pdf --out changed.pdf --keep 1   # 1 頁目 (説明の頁) は必ず残す
    python3 latexdiff-changed-pages.py diff.pdf --list                  # 絞らずに頁番号だけ出す
    python3 latexdiff-changed-pages.py --selftest

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
    print("selftest: 4 checks ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--out", help="出力先 (既定 = 入力をその場で置き換える)")
    ap.add_argument("--keep", type=int, action="append", default=[], help="必ず残す頁 (1 始まり、 繰り返し可)")
    ap.add_argument("--color", action="append", default=[], help="差分の色 #rrggbb (繰り返し可、 渡すと既定を置き換える)")
    ap.add_argument("--list", action="store_true", help="絞らずに、 差分の色がある頁番号だけ出す")
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
    if a.list:
        return 0
    write_pages(a.pdf, keep, a.out or a.pdf)
    print(a.out or a.pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
