#!/usr/bin/env python3
"""pdf-render-equal.py — 2 つの PDF が同じに描けるかを画素で比べる (driver を helper 呼び出しに置き換えた・生成器を作り直したとき、 出力が変わっていないことの根拠にする。 違えば最初に違う頁と、 違う画素の数・囲む矩形 〔PDF pt〕 を出す)

なぜ: 様式の driver や図の生成器を直すと、 text だけの照合 (頁数・文字列・image の数) は通るのに **置き場所が数 pt ずれる**
ことがある。 紙に出ると目立つが、 file の比較でも text の比較でも出ない。 描いて画素で比べると、 ずれたかどうかと
「どこが」 が同時に出る。 逆に、 画素が全部同じなら「出力は変わっていない」 を根拠つきで言える。

使い方:
  pdf-render-equal.py A.pdf B.pdf [--dpi 150] [--pages 1,3-4] [--max-pages-reported 5] [--json]
  pdf-render-equal.py --selftest
exit: 0 = 全頁一致 / 1 = 違いあり・頁数が違う / 2 = 引数・file の誤り

勘所:
- **dpi は低くしない** (既定 150)。 低いと 1 pt 未満のずれが同じ画素に丸められて「一致」 と出る。 位置の検査なら 150 以上。
- **font を埋め込んだ PDF 同士でも、 描く側 (PyMuPDF の版・OS の font) が違えば画素は変わりうる** = 同じ機械・同じ版で、
  直す前と直した後を続けて描いて比べる (別の機械で描いた古い出力と比べない)。
- 「画素が同じ」 は**見た目が同じ**を意味するだけで、 中身 (text 層・font の埋め込み・頁の役割の宣言) が同じとは言わない =
  紙に出す前の検査 (頁の役割・font) は別に回す。
- 比較の前に、 両方の PDF を**同じ道具で作る** (片方だけ raster 化しない)。 raster 版と vector 版は必ず違う。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    print("pdf-render-equal: PyMuPDF (fitz) が要る: pip install pymupdf", file=sys.stderr)
    sys.exit(2)


def parse_pages(spec: str, n: int) -> list:
    """'1,3-4' → [0,2,3] (1 起点で受けて 0 起点で返す)。 spec が空なら全頁。"""
    if not spec:
        return list(range(n))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    bad = [p + 1 for p in out if p < 0 or p >= n]
    if bad:
        raise SystemExit(f"pdf-render-equal: 頁 {bad} は 1..{n} の外")
    return sorted(set(out))


def _diff_box(pix_a, pix_b):
    """違う画素の数と、 それを囲む矩形を画像の px で返す ((count, x0, y0, x1, y1))。 同じなら (0, None…)。"""
    sa, sb = pix_a.samples, pix_b.samples
    w, h, n = pix_a.width, pix_a.height, pix_a.n
    count = 0
    x0 = y0 = None
    x1 = y1 = -1
    row = w * n
    for y in range(h):
        ra, rb = sa[y * row:(y + 1) * row], sb[y * row:(y + 1) * row]
        if ra == rb:
            continue
        for x in range(w):
            if ra[x * n:(x + 1) * n] != rb[x * n:(x + 1) * n]:
                count += 1
                x0 = x if x0 is None else min(x0, x)
                x1 = max(x1, x)
                y0 = y if y0 is None else min(y0, y)
                y1 = max(y1, y)
    return count, x0, y0, x1, y1


def compare(path_a, path_b, dpi: int = 150, pages: str = "") -> dict:
    """{equal, pages: [{page, equal, diff_pixels, box_pt, total_pixels}], note} を返す。"""
    da, db = fitz.open(str(path_a)), fitz.open(str(path_b))
    res = {"a": str(path_a), "b": str(path_b), "dpi": dpi, "equal": True, "pages": [], "note": ""}
    if da.page_count != db.page_count:
        res["equal"] = False
        res["note"] = f"頁数が違う: {da.page_count} ≠ {db.page_count}"
        return res
    scale = dpi / 72.0
    for p in parse_pages(pages, da.page_count):
        pa, pb = da[p], db[p]
        if (round(pa.rect.width, 2), round(pa.rect.height, 2)) != (round(pb.rect.width, 2), round(pb.rect.height, 2)):
            res["equal"] = False
            res["pages"].append({"page": p + 1, "equal": False, "diff_pixels": None,
                                 "box_pt": None, "note": f"頁の大きさが違う: {pa.rect} ≠ {pb.rect}"})
            continue
        ia, ib = pa.get_pixmap(dpi=dpi), pb.get_pixmap(dpi=dpi)
        if ia.samples == ib.samples:
            res["pages"].append({"page": p + 1, "equal": True, "diff_pixels": 0, "box_pt": None,
                                 "total_pixels": ia.width * ia.height})
            continue
        res["equal"] = False
        count, x0, y0, x1, y1 = _diff_box(ia, ib)
        box_pt = None if x0 is None else [round(x0 / scale, 1), round(y0 / scale, 1),
                                          round((x1 + 1) / scale, 1), round((y1 + 1) / scale, 1)]
        res["pages"].append({"page": p + 1, "equal": False, "diff_pixels": count, "box_pt": box_pt,
                             "total_pixels": ia.width * ia.height})
    return res


def _selftest():
    d = Path(tempfile.mkdtemp())
    def make(path, text, x=72.0):
        doc = fitz.open(); page = doc.new_page(width=300, height=200)
        page.insert_text((x, 100), text, fontname="helv", fontsize=14); doc.save(str(path))
    a, b, c, two = d / "a.pdf", d / "b.pdf", d / "c.pdf", d / "two.pdf"
    make(a, "same"); make(b, "same"); make(c, "same", x=74.0)       # c = 2 pt ずらしただけ
    doc = fitz.open(); doc.new_page(width=300, height=200); doc.new_page(width=300, height=200); doc.save(str(two))
    ok = 0
    r = compare(a, b); assert r["equal"] and r["pages"][0]["diff_pixels"] == 0, r; ok += 1
    r = compare(a, c); assert not r["equal"] and r["pages"][0]["diff_pixels"] > 0, r
    box = r["pages"][0]["box_pt"]; assert box and 60 <= box[0] <= 120 and 80 <= box[1] <= 110, box; ok += 1
    r = compare(a, two); assert not r["equal"] and "頁数" in r["note"], r; ok += 1
    r = compare(a, c, dpi=4)                                        # 粗く描くと 2 pt のずれが消えうる
    assert r["pages"][0]["diff_pixels"] <= compare(a, c, dpi=150)["pages"][0]["diff_pixels"], "dpi を上げるほど見える"
    ok += 1
    r = compare(two, two, pages="2"); assert r["equal"] and [p["page"] for p in r["pages"]] == [2], r; ok += 1
    assert parse_pages("1,3-4", 5) == [0, 2, 3]; ok += 1
    print(f"pdf-render-equal selftest: {ok}/6 PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a", nargs="?"); ap.add_argument("b", nargs="?")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--pages", default="", help="1 起点、 '1,3-4'。 既定 = 全頁")
    ap.add_argument("--max-pages-reported", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest(); return 0
    if not a.a or not a.b:
        ap.error("PDF を 2 つ (or --selftest)")
    for p in (a.a, a.b):
        if not Path(p).is_file():
            print(f"pdf-render-equal: 無い file: {p}", file=sys.stderr); return 2
    res = compare(a.a, a.b, a.dpi, a.pages)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2)); return 0 if res["equal"] else 1
    if res["note"]:
        print(f"  ✗ {res['note']}")
    diff = [p for p in res["pages"] if not p["equal"]]
    for p in diff[:a.max_pages_reported]:
        if p.get("note"):
            print(f"  ✗ p.{p['page']}: {p['note']}")
        else:
            pct = 100.0 * p["diff_pixels"] / p["total_pixels"]
            print(f"  ✗ p.{p['page']}: 違う画素 {p['diff_pixels']} ({pct:.3f}%)、 囲む矩形 (pt) = {p['box_pt']}")
    if len(diff) > a.max_pages_reported:
        print(f"  … ほか {len(diff) - a.max_pages_reported} 頁")
    if res["equal"]:
        print(f"  ✓ 全 {len(res['pages'])} 頁が画素まで一致 ({a.dpi} dpi) — 出力は変わっていない")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
