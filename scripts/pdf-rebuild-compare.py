#!/usr/bin/env python3
"""2 つの PDF (記録に残した版と、 今の道具で作り直した版) が紙として同じかを、 頁数・語・画像・描画命令・画素の差で照合する。--selftest 内蔵。

なぜ要るか: engine の置き場所を移した・recipe を書き換えた後に、 過去に作って記録した出力と同じ案件から作り直した出力を
比べる作業 (規約 = [`conventions/form-case-pipeline.md#rebuild-equivalence`](../conventions/form-case-pipeline.md#rebuild-equivalence))
を、 session の使い捨ての比較 script で回していた (実測。 使い捨ては記入済みの様式と同じ scratch に置かれ、 個人情報の
複製と一緒に消えた = 次の照合で同じ比較を書き直すことになる)。 gate と selftest は既知の壊れ方しか見ないので、
「移しただけのつもりで紙が変わっていないか」 は実物を比べるまで分からない。

役割の切り分け (重ならない):
  - formcase の regate = 今ある出力を今の関門に通し直す (欠陥のある世代を止める)
  - pdf-print-preflight --changed-from = 前に刷った版と頁ごとに見た目が違うか (刷り直す頁を選ぶ、 はい / いいえだけ)
  - 本 script = 2 つの版の差を軸ごとに数え、 規約の「差の読み方」 のどれに当たるかの材料を出す (同じと言える根拠を残す)

比べる軸 (頁ごと):
  words     語の多重集合の差 (消えた語・足された語)
  invisible 足された語のうち、 その位置に画素差が無いもの = 描画に出ない字層の候補 (図形の字のうち枠で切れて見えない部分 など)
  images    画像の数と位置 (bbox を 0.5 pt に丸める)
  drawings  描画命令 (位置・塗り色・線の色)。 同じ位置・同じ色の「塗り + 線」 の 1 命令と「塗り」「線」 の 2 命令は同じに数える
  pixels    同じ dpi で灰色に描き、 64 階調を超えて違う画素の数・頁を 20 の横帯に分けた分布・差の bbox (pt)。 頁の寸法が
            丸めで違う (595.28×841.89 ⇄ 595×842) ときは共通の範囲だけを比べる
  position  両方に 1 回ずつ出る語の左上を組にして、 x と y それぞれ「新 = 拡縮 × 旧 + 移動」 を最小二乗で当てる
            (拡縮 1.000 で移動だけなら体裁の差、 量を pt で出す)

判定: 全軸で差が無い頁 = same。 差があれば軸ごとに数を出す (exit 1)。 「差が無い」 と「差の読み方で説明がつく」 は別:
説明がつくかは人が規約の読み方に照らして決める (本 script は材料を出すだけ)。 --zoom-dir を付けると、 画素差の bbox を
新旧それぞれ拡大した PNG を書く (差を目で見る)。

使い方:
    python3 pdf-rebuild-compare.py OLD.pdf NEW.pdf [--dpi 150] [--zoom-dir DIR] [--json]
    python3 pdf-rebuild-compare.py --selftest

exit: 0 = 全頁 same / 1 = 差がある / 2 = 読めない
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

PIXEL_LEVEL = 64      # 灰色 256 階調でこれを超える差を「違う画素」 と数える (print_pages.changed_pages と同じ)
BANDS = 20            # 画素差の分布を見る横帯の数
ROUND = 0.5           # 位置を丸める単位 (pt)


def _need_fitz():
    if fitz is None:
        sys.exit("PyMuPDF (fitz) が要る: pip install pymupdf")


def _r(v):
    return round(v / ROUND) * ROUND


def _rect_key(r):
    return (_r(r.x0), _r(r.y0), _r(r.x1), _r(r.y1))


def _color(c):
    return tuple(round(x, 3) for x in c) if c else None


def words(page):
    """[(x0, y0, x1, y1, text)] = 語の位置と文字列。"""
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]


def images(page):
    return sorted(_rect_key(fitz.Rect(i["bbox"])) for i in page.get_image_info())


def drawings(page):
    """描画命令を (位置, 塗り色, 線の色) の多重集合にする。 同じ位置の「塗りだけ」 と「線だけ」 は 1 つに合わせる
    (= 「塗り + 線」 の 1 命令と同じに数える)。 続けて置いた塗りと線は PyMuPDF が読む時に既に 1 つ (type fs) にするので、
    ここで合わせるのは間に別の命令が挟まった組 (実測)。"""
    fills, strokes, both = [], [], []
    for d in page.get_drawings():
        k = _rect_key(d["rect"])
        t = d.get("type")
        if t == "fs":
            both.append((k, _color(d.get("fill")), _color(d.get("color"))))
        elif t == "f":
            fills.append((k, _color(d.get("fill"))))
        elif t == "s":
            strokes.append((k, _color(d.get("color"))))
    left = collections.Counter(strokes)
    out = list(both)
    for k, fc in fills:
        match = next((s for s in left if s[0] == k and left[s] > 0), None)
        if match:
            left[match] -= 1
            out.append((k, fc, match[1]))
        else:
            out.append((k, fc, None))
    for (k, sc), n in left.items():
        out.extend([(k, None, sc)] * n)
    return collections.Counter(out)


def pixel_diff(p_old, p_new, dpi):
    """共通の範囲を同じ dpi で灰色に描いて比べる。 (違う画素の数, 帯ごとの数, 差の bbox (pt) か None, clip)。"""
    clip = fitz.Rect(0, 0, min(p_old.rect.width, p_new.rect.width), min(p_old.rect.height, p_new.rect.height))
    a = p_old.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=clip)
    b = p_new.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=clip)
    w, h = min(a.width, b.width), min(a.height, b.height)
    sa, sb = a.samples, b.samples
    n, bands = 0, [0] * BANDS
    x0 = y0 = None
    x1 = y1 = -1
    for y in range(h):
        ra, rb = y * a.width, y * b.width
        for x in range(w):
            if abs(sa[ra + x] - sb[rb + x]) > PIXEL_LEVEL:
                n += 1
                bands[min(BANDS - 1, y * BANDS // h)] += 1
                x0 = x if x0 is None else min(x0, x)
                y0 = y if y0 is None else min(y0, y)
                x1, y1 = max(x1, x), max(y1, y)
    s = 72.0 / dpi
    box = fitz.Rect(x0 * s, y0 * s, (x1 + 1) * s, (y1 + 1) * s) if n else None
    return n, bands, box, clip


def pixel_diff_at(p_old, p_new, rect, dpi):
    """rect の中だけの違う画素の数 (足された語が描画に出ているかを見る)。"""
    rect = fitz.Rect(rect) & p_old.rect & p_new.rect
    if rect.is_empty:
        return 0
    a = p_old.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=rect)
    b = p_new.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=rect)
    w, h = min(a.width, b.width), min(a.height, b.height)
    return sum(1 for y in range(h) for x in range(w)
               if abs(a.samples[y * a.width + x] - b.samples[y * b.width + x]) > PIXEL_LEVEL)


def _fit(pairs):
    """[(old, new)] に new = s × old + t を最小二乗で当てる。 (s, t, 最大の残差)。 組が 2 未満か old が 1 点なら None。"""
    if len(pairs) < 2:
        return None
    n = len(pairs)
    mx = sum(o for o, _ in pairs) / n
    my = sum(v for _, v in pairs) / n
    sxx = sum((o - mx) ** 2 for o, _ in pairs)
    if sxx < 1e-9:
        return None
    s = sum((o - mx) * (v - my) for o, v in pairs) / sxx
    t = my - s * mx
    return s, t, max(abs(v - (s * o + t)) for o, v in pairs)


def position(w_old, w_new):
    """両方に 1 回ずつ出る語の左上を組にして、 x と y の拡縮・移動を当てる。 {x: (s, t, res), y: …, pairs: n} か None。"""
    co = collections.Counter(w[4] for w in w_old)
    cn = collections.Counter(w[4] for w in w_new)
    uniq = [t for t in co if co[t] == 1 and cn.get(t) == 1]
    if not uniq:
        return None
    o = {w[4]: w for w in w_old}
    m = {w[4]: w for w in w_new}
    fx = _fit([(o[t][0], m[t][0]) for t in uniq])
    fy = _fit([(o[t][1], m[t][1]) for t in uniq])
    return {"x": fx, "y": fy, "pairs": len(uniq)}


def compare_page(p_old, p_new, dpi=150):
    wo, wn = words(p_old), words(p_new)
    co = collections.Counter(w[4] for w in wo)
    cn = collections.Counter(w[4] for w in wn)
    removed = sorted((co - cn).elements())
    added = sorted((cn - co).elements())
    left = collections.Counter(added)
    invisible = []
    for w in wn:
        if left[w[4]] > 0:
            left[w[4]] -= 1
            if pixel_diff_at(p_old, p_new, fitz.Rect(w[:4]), dpi) == 0:
                invisible.append(w[4])
    io, inew = images(p_old), images(p_new)
    do, dn = drawings(p_old), drawings(p_new)
    npx, bands, box, clip = pixel_diff(p_old, p_new, dpi)
    pos = position(wo, wn)
    size_old = (round(p_old.rect.width, 2), round(p_old.rect.height, 2))
    size_new = (round(p_new.rect.width, 2), round(p_new.rect.height, 2))
    rep = {
        "size": {"old": size_old, "new": size_new},
        "words": {"removed": removed, "added": added},
        "invisible": invisible,
        "images": {"old": len(io), "new": len(inew), "same": io == inew},
        "drawings": {"old": sum(do.values()), "new": sum(dn.values()),
                     "only_old": sum((do - dn).values()), "only_new": sum((dn - do).values())},
        "pixels": {"count": npx, "bands": bands,
                   "bbox": [round(v, 1) for v in box] if box else None},
        "position": pos,
    }
    rep["diff_axes"] = diff_axes(rep)
    return rep


def diff_axes(rep):
    axes = []
    if rep["size"]["old"] != rep["size"]["new"]:
        axes.append("size")
    if rep["words"]["removed"] or rep["words"]["added"]:
        axes.append("words")
    if rep["invisible"]:
        axes.append("invisible")
    if not rep["images"]["same"]:
        axes.append("images")
    if rep["drawings"]["only_old"] or rep["drawings"]["only_new"]:
        axes.append("drawings")
    if rep["pixels"]["count"]:
        axes.append("pixels")
    p = rep["position"]
    if p and any(f and (abs(f[0] - 1) > 1e-3 or abs(f[1]) > 0.05) for f in (p["x"], p["y"])):
        axes.append("position")
    return axes


def compare(old_path, new_path, dpi=150, zoom_dir=None):
    _need_fitz()
    do, dn = fitz.open(old_path), fitz.open(new_path)
    pages = []
    for i in range(min(do.page_count, dn.page_count)):
        rep = compare_page(do[i], dn[i], dpi)
        rep["page"] = i + 1
        if zoom_dir and rep["pixels"]["bbox"]:
            os.makedirs(zoom_dir, exist_ok=True)
            r = fitz.Rect(rep["pixels"]["bbox"]) + (-6, -6, 6, 6)
            for tag, d in (("old", do), ("new", dn)):
                pr = r & d[i].rect
                if not pr.is_empty:
                    d[i].get_pixmap(dpi=dpi * 3, clip=pr).save(
                        os.path.join(zoom_dir, f"p{i + 1}-diff-{tag}.png"))
        pages.append(rep)
    return {"pages_old": do.page_count, "pages_new": dn.page_count, "dpi": dpi, "pages": pages,
            "same": do.page_count == dn.page_count and all(not p["diff_axes"] for p in pages)}


def report_lines(res):
    out = [f"頁数: 旧 {res['pages_old']} / 新 {res['pages_new']}"
           + ("" if res["pages_old"] == res["pages_new"] else "  ← 違う (多い側の頁は比べていない)")]
    for p in res["pages"]:
        if not p["diff_axes"]:
            out.append(f"p{p['page']}: same")
            continue
        out.append(f"p{p['page']}: 差 = {', '.join(p['diff_axes'])}")
        if "size" in p["diff_axes"]:
            out.append(f"  寸法: 旧 {p['size']['old']} / 新 {p['size']['new']} (共通の範囲だけ画素を比べた)")
        if p["words"]["removed"] or p["words"]["added"]:
            out.append(f"  語: 消えた {p['words']['removed'][:20]} / 足された {p['words']['added'][:20]}")
        if p["invisible"]:
            out.append(f"  描画に出ない足された語 (その位置に画素差なし) = 見えない字層の候補: {p['invisible'][:20]}")
        if not p["images"]["same"]:
            out.append(f"  画像: 旧 {p['images']['old']} / 新 {p['images']['new']} (数か位置が違う)")
        d = p["drawings"]
        if d["only_old"] or d["only_new"]:
            out.append(f"  描画命令: 旧 {d['old']} / 新 {d['new']} (旧にだけ {d['only_old']}、 新にだけ {d['only_new']}。"
                       " 塗り + 線の分け方の差は数えていない)")
        px = p["pixels"]
        if px["count"]:
            hot = [f"{k + 1}:{v}" for k, v in enumerate(px["bands"]) if v]
            out.append(f"  画素: {px['count']} 個 (帯 {len(hot)}/{BANDS} に散る: {' '.join(hot[:10])}) bbox {px['bbox']} pt")
        pos = p["position"]
        if pos and "position" in p["diff_axes"]:
            fx, fy = pos["x"], pos["y"]
            fmt = lambda f: (f"拡縮 {f[0]:.4f} 移動 {f[1]:+.2f} pt 残差 {f[2]:.2f}" if f else "当てられない")
            out.append(f"  位置 ({pos['pairs']} 語の組): x {fmt(fx)} / y {fmt(fy)}")
    out.append("判定: " + ("全頁 same" if res["same"] else
                           "差がある = form-case-pipeline.md#rebuild-equivalence の「差の読み方」 で名指しして確かめる"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old", nargs="?")
    ap.add_argument("new", nargs="?")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--zoom-dir", help="画素差の bbox を新旧それぞれ拡大した PNG を書く dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.old and a.new):
        ap.error("OLD.pdf と NEW.pdf が要る")
    try:
        res = compare(a.old, a.new, a.dpi, a.zoom_dir)
    except Exception as e:  # 読めない PDF
        print(f"読めない: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else "\n".join(report_lines(res)))
    return 0 if res["same"] else 1


def selftest():
    import tempfile
    _need_fitz()
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("[PASS] " if cond else "[FAIL] ") + name)
        ok = ok and bool(cond)

    def build(path, *, text=("Alpha", "Beta", "Gamma"), dx=0.0, split=False, hidden=None, image=True,
              pages=1, size=(595.28, 841.89)):
        doc = fitz.open()
        for _ in range(pages):
            p = doc.new_page(width=size[0], height=size[1])
            for k, t in enumerate(text):
                p.insert_text((72 + dx + 80 * k, 100), t, fontsize=14)
            p.insert_text((72 + dx, 400), "Omega", fontsize=14)
            r = fitz.Rect(72 + dx, 200, 272 + dx, 260)
            rule = lambda: p.draw_line((300 + dx, 600), (500 + dx, 600), color=(0, 0, 0))
            if split:  # 間に別の命令を挟む (続けて置いた塗りと線は PyMuPDF が読む時に 1 命令に合わせる = 実測)
                p.draw_rect(r, fill=(0.9, 0.9, 0.2), color=None)
                rule()
                p.draw_rect(r, color=(0, 0, 0.8), fill=None)
            else:
                p.draw_rect(r, color=(0, 0, 0.8), fill=(0.9, 0.9, 0.2))
                rule()
            if image:
                pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), 0)
                pm.set_rect(pm.irect, (200, 30, 30))
                p.insert_image(fitz.Rect(400 + dx, 500, 460 + dx, 560), pixmap=pm)
            if hidden:
                p.insert_text((72 + dx, 300), hidden, fontsize=14, render_mode=3)
        doc.save(path)

    def quiet_main(argv):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return main(argv)

    with tempfile.TemporaryDirectory() as td:
        P = lambda n: os.path.join(td, n + ".pdf")
        build(P("base"))
        build(P("same"))
        build(P("word"), text=("Alpha", "Beta", "Delta"))
        build(P("split"), split=True)
        build(P("hidden"), hidden="Ghost")
        build(P("shift"), dx=0.4)
        build(P("noimg"), image=False)
        build(P("twopage"), pages=2)
        build(P("rounded"), size=(595, 842))

        r = compare(P("base"), P("same"))
        check("identical rebuild: every axis same, exit 0", r["same"] and quiet_main([P("base"), P("same")]) == 0)
        r = compare(P("base"), P("word"))["pages"][0]
        check("changed word: removed and added words named",
              r["words"]["removed"] == ["Gamma"] and r["words"]["added"] == ["Delta"])
        check("changed word: pixel difference found near the word",
              r["pixels"]["count"] > 0 and r["pixels"]["bbox"][1] < 110)
        check("changed word: a visible added word is not an invisible-layer candidate", r["invisible"] == [])
        r = compare(P("base"), P("split"))["pages"][0]
        check("fill + stroke in one command equals fill and stroke in two", "drawings" not in r["diff_axes"])
        r = compare(P("base"), P("hidden"))["pages"][0]
        check("hidden text layer: added word with no pixel difference is flagged",
              r["invisible"] == ["Ghost"] and r["pixels"]["count"] == 0)
        r = compare(P("base"), P("shift"))["pages"][0]
        fx = (r["position"] or {}).get("x")
        check("whole-page shift: scale 1 and the translation measured in pt",
              fx and abs(fx[0] - 1) < 1e-3 and abs(fx[1] - 0.4) < 0.05 and "position" in r["diff_axes"])
        check("whole-page shift: no word added or removed", not r["words"]["removed"] and not r["words"]["added"])
        r = compare(P("base"), P("noimg"))["pages"][0]
        check("removed image: image count differs", r["images"]["old"] == 1 and r["images"]["new"] == 0
              and "images" in r["diff_axes"])
        res = compare(P("base"), P("twopage"))
        check("page count differs: not same, exit 1",
              not res["same"] and res["pages_new"] == 2 and quiet_main([P("base"), P("twopage")]) == 1)
        r = compare(P("base"), P("rounded"))["pages"][0]
        check("page size rounded (595.28 vs 595): size named, content compared on the common area",
              "size" in r["diff_axes"] and not r["words"]["added"] and not r["words"]["removed"])
        zd = os.path.join(td, "zoom")
        compare(P("base"), P("word"), zoom_dir=zd)
        check("--zoom-dir writes old and new crops of the difference",
              os.path.exists(os.path.join(zd, "p1-diff-old.png")) and os.path.exists(os.path.join(zd, "p1-diff-new.png")))
        check("report names the axes", any("差 = words" in ln for ln in report_lines(compare(P("base"), P("word")))))
    print("selftest:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
