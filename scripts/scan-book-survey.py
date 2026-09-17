#!/usr/bin/env python3
"""書籍のスキャン PDF を棚卸しするための下見: 刷り色の測定・奥付と目次の候補・文字層 (OCR) の語検索・ノンブルのずれ・奥付と見開きの確認画像。--selftest 内蔵。

なぜ層1 にあるか
----------------
他人から共有された書籍スキャンの束を「書誌・刷り色・関連箇所」 で棚卸しするとき、 1 冊ごとに同じ
下見を手書きの inline python で繰り返すことになる (実測)。 下見の壊れ方も毎回同じなので道具にした:

  1. **colorspace は刷り色ではない** — 全ページ DeviceGray のスキャンは、 原本が単色刷りなのか
     スキャナの設定で色が落ちたのか区別できない (= 判定不能と書く)。 自動カラー判別のスキャナは
     ページごとに RGB / Gray / 1-bit を選ぶので、 RGB ページだけ彩度を測り、 色相の分布を見る
     (1 色だけ = 二色刷り、 複数色 = フルカラーの候補。 最後は縮小画像で目視)。
  2. **文字層は案内板** — OCR の文字層は語の出現ページを探すのには使えるが、 奥付の日付・ISBN・
     人名・数式・引用は崩れる。 それらは `colophon` / `render` の画像で読む。 検索 0 件は不在の証明にならない。
  3. **本のページと PDF のページはずれる** — 引用や記録は本のノンブルで書きたい。 `offset` が
     ページ上下端の数字だけのブロックから差を推定する (章の扉など数字の無いページは外れる)。
  4. **出力が大きい** — 前付けを丸ごと text で出すと数万 token になる。 `text --compact` は
     点線リーダと数字だけの行を落とし、 ページごとに文字数を切る。

⚠️ 第三者の著作物: 出力画像 (`--out-dir`) は repo の外 (既定 = 一時 dir) に置き、 git に入れない。
手順と記録の書き方 = conventions/scanned-book-survey.md。

使い方
------
  scan-book-survey.py digest BOOK.pdf [--no-color] [--kw 名前=正規表現 ...]
  scan-book-survey.py find   BOOK.pdf 正規表現 [正規表現 ...]
  scan-book-survey.py text   BOOK.pdf 3-5,9 [--compact] [--max-chars 1500]
  scan-book-survey.py offset BOOK.pdf 40-50
  scan-book-survey.py render BOOK.pdf 19,35 [--zoom 1.4] [--clip 0.0,0.5] [--out-dir DIR]
  scan-book-survey.py colophon BOOK.pdf 281 [--frac 0.4,1.0] [--thumbs 52,97] [--out-dir DIR]
  scan-book-survey.py --selftest

ページ番号はすべて PDF の 1 始まり。 依存 = PyMuPDF (fitz)、 numpy、 Pillow (colophon のみ)。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    sys.exit("PyMuPDF (fitz) が要る: pip install pymupdf")

# 数字だけ・点線リーダだけの行 (目次の OCR で大量に出る)
FILLER = re.compile(r"^[\s\.．・…‥,，、。:：;；\-－—–_~〜\|｜'\"`\*＊•●◆■□◇○°\(\)（）\[\]0-9０-９IVXivxlLⅠⅡⅢⅣⅤ]*$")
COLOPHON = re.compile(r"ISBN|第\s*[0-9０-９一二三四五六七八九十]+\s*刷|発\s*行\s*所|発行者|初\s*版")
TOC = re.compile(r"目\s*次|CONTENTS|Contents")
PREFACE = re.compile(r"まえがき|はじめに|序\s*文|序\s*章|前書き|緒言|Preface|PREFACE")
HUES = [(15, "赤"), (45, "橙"), (70, "黄"), (160, "緑"), (200, "青緑"), (260, "青"), (320, "紫"), (345, "赤紫"), (360, "赤")]


def parse_pages(spec: str, n: int) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [p for p in out if 1 <= p <= n]


def compress(nums: list[int]) -> str:
    runs: list[list[int]] = []
    for x in nums:
        if runs and runs[-1][1] == x - 1:
            runs[-1][1] = x
        else:
            runs.append([x, x])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def compact(text: str) -> str:
    keep = [ln.strip() for ln in text.split("\n") if ln.strip() and not FILLER.match(ln.strip())]
    return re.sub(r"[\.．・…‥]{3,}", "…", " / ".join(keep))


def image_components(doc, xref: int, csname: str) -> int:
    """画像の色成分数 (1 = グレー)。 ICCBased は profile の /N を読む (PyMuPDF で作った画像や一部の PDF はこの形)。"""
    fixed = {"DeviceGray": 1, "CalGray": 1, "DeviceRGB": 3, "CalRGB": 3, "Lab": 3, "DeviceCMYK": 4}
    if csname in fixed:
        return fixed[csname]
    try:
        kind, val = doc.xref_get_key(xref, "ColorSpace")
        text = doc.xref_object(int(val.split()[0])) if kind == "xref" else val
        m = re.search(r"/ICCBased\s+(\d+)\s+0\s+R", text)
        if m:
            n = doc.xref_get_key(int(m.group(1)), "N")[1]
            return int(n)
    except Exception:
        pass
    return 3  # 分からないものは色ありとして測る側に倒す


def page_colorspaces(doc, i: int) -> str:
    kinds = sorted({f"{im[5]}/{im[4]}/n{image_components(doc, im[0], im[5])}" for im in doc[i].get_images(full=True)})
    return "+".join(kinds) or "none"


def hue_name(h: float) -> str:
    for lim, name in HUES:
        if h < lim:
            return name
    return "赤"


def color_measure(page, zoom: float = 0.12, sat: float = 0.30, val: float = 0.25):
    """縮小描画して、彩度 > sat かつ明度 > val の画素の割合と、その画素の色相 (度) を返す。"""
    import numpy as np

    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).astype(np.float32) / 255
    mx, mn = a.max(axis=2), a.min(axis=2)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    mask = (s > sat) & (mx > val)
    hues = np.zeros(0, dtype=np.float32)
    if mask.any():
        sel = a[mask]
        r, g, b = sel[:, 0], sel[:, 1], sel[:, 2]
        hi, lo = sel.max(axis=1), sel.min(axis=1)
        d = np.maximum(hi - lo, 1e-6)
        h = np.where(hi == r, ((g - b) / d) % 6, np.where(hi == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
        hues = h.astype(np.float32)
    return float(mask.mean()), hues


def hue_arc(hues, cover: float = 0.9) -> float:
    """色相 (度) の cover 割合を含む最小の円弧の幅。 1 色のインクなら、 色の名前の境目で割れても狭く出る。"""
    import numpy as np

    if len(hues) == 0:
        return 0.0
    hist, _ = np.histogram(np.asarray(hues) % 360, bins=72, range=(0, 360))  # 5 度刻み
    need = cover * hist.sum()
    doubled = np.concatenate([hist, hist])
    best = 360.0
    for start in range(72):
        acc = 0
        for width in range(1, 73):
            acc += doubled[start + width - 1]
            if acc >= need:
                best = min(best, width * 5.0)
                break
    return best


def measure_colors(doc, threshold: float = 0.004, per_page: int = 400) -> dict:
    import numpy as np

    kinds: dict[str, int] = {}
    nongray: list[int] = []
    colored: list[int] = []
    names: dict[str, int] = {}
    pool = []
    for i in range(doc.page_count):
        key = page_colorspaces(doc, i)
        kinds[key] = kinds.get(key, 0) + 1
        if key != "none" and any(not part.endswith("/n1") for part in key.split("+")):
            nongray.append(i + 1)
            frac, hues = color_measure(doc[i])
            if frac > threshold:
                colored.append(i + 1)
                for x in hues:
                    nm = hue_name(float(x))
                    names[nm] = names.get(nm, 0) + 1
                pool.append(hues[:: max(1, len(hues) // per_page)])
    total = sum(names.values()) or 1
    share = {k: round(v * 100 / total) for k, v in sorted(names.items(), key=lambda kv: -kv[1])}
    arc = hue_arc(np.concatenate(pool)) if pool else 0.0
    if not nongray:
        verdict = "判定不能 (全ページがグレーで取り込まれている)"
    elif not colored:
        verdict = "単色の可能性 (カラーで取り込まれたページに彩色が無い)"
    elif arc <= 60:
        verdict = (f"二色刷りの候補 (彩色画素の 9 割が幅 {arc:.0f} 度の色相に収まる。"
                   " 1 色に絞ったフルカラーとは区別できないので縮小画像で確かめる)")
    else:
        verdict = f"多色の候補 (彩色画素の 9 割を含む色相の幅 {arc:.0f} 度。 表紙など一部だけかを縮小画像で確かめる)"
    return {"colorspaces": kinds, "nongray": nongray, "colored": colored, "hue_share": share,
            "hue_arc": arc, "verdict": verdict}


def find_pages(doc, pattern: str) -> list[int]:
    rx = re.compile(pattern)
    return [i + 1 for i in range(doc.page_count) if rx.search(doc[i].get_text().replace("\n", ""))]


def estimate_offset(doc, pages: list[int]) -> tuple[list[tuple[int, list[int]]], list[tuple[int, int]]]:
    """ページ上下端 12% にある数字だけのブロックをノンブルとみなし、 (PDF − ノンブル) の頻度を返す。"""
    seen: list[tuple[int, list[int]]] = []
    diffs: dict[int, int] = {}
    for p in pages:
        page = doc[p - 1]
        h = page.rect.height
        nums = []
        for b in page.get_text("blocks"):
            txt = b[4].strip()
            if re.fullmatch(r"\d{1,4}", txt) and (b[1] < h * 0.12 or b[3] > h * 0.88):
                nums.append(int(txt))
        seen.append((p, nums))
        for x in nums:
            diffs[p - x] = diffs.get(p - x, 0) + 1
    return seen, sorted(diffs.items(), key=lambda kv: -kv[1])


def digest(doc, color: bool = True, kws: list[tuple[str, str]] | None = None, colophon_chars: int = 900) -> str:
    n = doc.page_count
    lines = [f"pages={n} producer={doc.metadata.get('producer')}"]
    if color:
        c = measure_colors(doc)
        lines += [f"colorspaces: {c['colorspaces']}",
                  f"non-gray pages: {compress(c['nongray'])}",
                  f"colored pages: {len(c['colored'])} → {compress(c['colored'])[:200]}",
                  f"hue share %: {c['hue_share']}",
                  f"刷り色の見立て: {c['verdict']}"]
    colo = [i for i in range(max(0, n - 20), n) if COLOPHON.search(doc[i].get_text())]
    lines.append(f"colophon candidates: {[i + 1 for i in colo]}")
    for i in colo[-2:]:
        lines.append(f"--- PDF p{i + 1}: {compact(doc[i].get_text())[:colophon_chars]}")
    toc = [i + 1 for i in range(min(40, n)) if TOC.search(doc[i].get_text())]
    pre = [i + 1 for i in range(min(30, n)) if PREFACE.search(doc[i].get_text()[:200])]
    lines.append(f"toc candidates: {toc}  preface candidates: {pre}")
    for name, pat in kws or []:
        hits = find_pages(doc, pat)
        lines.append(f"  {name}: {len(hits)} → {compress(hits)[:150]}")
    lines.append("⚠️ 文字層 (OCR) の検索 0 件は不在の証明にならない。 奥付の日付・ISBN・人名は colophon の画像で読む。")
    return "\n".join(lines)


def default_out_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "scan-book-survey")
    os.makedirs(d, exist_ok=True)
    return d


def stem_of(path: str) -> str:
    return re.sub(r"[^\w]+", "_", os.path.basename(path).rsplit(".", 1)[0])[:30]


def render_pages(doc, path: str, pages: list[int], zoom: float, clip: tuple[float, float] | None, out_dir: str) -> list[str]:
    outs = []
    for p in pages:
        page = doc[p - 1]
        r = page.rect
        rect = fitz.Rect(0, r.height * clip[0], r.width, r.height * clip[1]) if clip else None
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        out = os.path.join(out_dir, f"{stem_of(path)}_p{p}.png")
        pix.save(out)
        outs.append(out)
    return outs


def colophon_image(doc, path: str, page_no: int, frac: tuple[float, float] | None, thumbs: list[int], out_dir: str,
                   thumb_zoom: float = 0.42, max_h: int = 1800) -> str:
    """奥付の書誌ブロック (高解像) と、 色を見たいページの縮小を 1 枚にまとめる。"""
    from PIL import Image

    page = doc[page_no - 1]
    r = page.rect
    if frac is None:
        blocks = [b for b in page.get_text("blocks") if COLOPHON.search(b[4]) or re.search(r"著\s*者|版", b[4])]
        frac = ((max(0, min(b[1] for b in blocks) - 20) / r.height, min(r.height, max(b[3] for b in blocks) + 20) / r.height)
                if blocks else (0.3, 1.0))
    pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), clip=fitz.Rect(0, r.height * frac[0], r.width, r.height * frac[1]))
    top = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    row = []
    for t in thumbs:
        tp = doc[t - 1].get_pixmap(matrix=fitz.Matrix(thumb_zoom, thumb_zoom))
        row.append(Image.frombytes("RGB", (tp.width, tp.height), tp.samples))
    w = max([top.width] + ([sum(x.width for x in row)] if row else []))
    h = top.height + (max(x.height for x in row) if row else 0)
    canvas = Image.new("RGB", (w, h), "white")
    canvas.paste(top, (0, 0))
    x = 0
    for im in row:
        canvas.paste(im, (x, top.height))
        x += im.width
    if canvas.height > max_h:
        s = max_h / canvas.height
        canvas = canvas.resize((int(canvas.width * s), max_h))
    out = os.path.join(out_dir, f"colophon_{stem_of(path)}.png")
    canvas.save(out)
    return out


def _pair(s: str | None) -> tuple[float, float] | None:
    if not s:
        return None
    a, b = s.split(",")
    return float(a), float(b)


def selftest() -> int:
    """合成 PDF (グレー画像のページ・青 1 色のページ・目次・奥付・ノンブル付きのページ) で各機能を確かめる。"""
    import numpy as np

    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    tmp = tempfile.mkdtemp(prefix="scan-book-survey-selftest-")
    doc = fitz.open()
    W, H = 300, 420
    # p1: グレー画像 + 目次
    p = doc.new_page(width=W, height=H)
    gray = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 60, 80), False)
    gray.set_rect(gray.irect, (128,))
    p.insert_image(fitz.Rect(20, 60, 140, 220), pixmap=gray)
    p.insert_text((20, 40), "CONTENTS ..... 1", fontsize=12)
    # p2: RGB 画像に青い帯 (二色刷りの模擬)
    p = doc.new_page(width=W, height=H)
    rgb = np.full((80, 60, 3), 255, dtype=np.uint8)
    rgb[:20, :, :] = (30, 60, 220)
    pm = fitz.Pixmap(fitz.csRGB, 60, 80, rgb.tobytes(), False)
    p.insert_image(fitz.Rect(0, 0, W, H), pixmap=pm)
    # p3-p6: ノンブル (PDF − 2) を下端に置いた本文
    for k in range(3, 7):
        p = doc.new_page(width=W, height=H)
        p.insert_text((20, 100), f"body text sample term {k}", fontsize=11)
        p.insert_text((W / 2, H - 15), str(k - 2), fontsize=9)
    # p7: 奥付
    p = doc.new_page(width=W, height=H)
    p.insert_text((20, 200), "ISBN 978-0-00-000000-0", fontsize=10)
    path = os.path.join(tmp, "synthetic-book.pdf")
    doc.save(path)
    doc.close()

    d = fitz.open(path)
    c = measure_colors(d)
    check(c["nongray"] == [2], f"non-gray pages {c['nongray']}")
    check(c["colored"] == [2], f"colored pages {c['colored']}")
    check(list(c["hue_share"])[:1] == ["青"], f"hue share {c['hue_share']}")
    check(c["verdict"].startswith("二色刷り"), f"verdict {c['verdict']}")
    check(find_pages(d, r"sample\s*term") == [3, 4, 5, 6], f"find {find_pages(d, r'sample term')}")
    _, diffs = estimate_offset(d, parse_pages("3-6", d.page_count))
    check(diffs and diffs[0] == (2, 4), f"offset {diffs}")
    dg = digest(d, color=False, kws=[("st", "sample")])
    check("colophon candidates: [7]" in dg, "colophon candidate")
    check("toc candidates: [1]" in dg, "toc candidate")
    sample = "第1章\n.....\n12\n本文"
    got = compact(sample)
    check(got == "第1章 / 本文", f"compact {got!r}")
    check(parse_pages("1-3,9,99", 10) == [1, 2, 3, 9], "parse_pages")
    check(compress([1, 2, 3, 5, 7, 8]) == "1-3,5,7-8", "compress")
    outs = render_pages(d, path, [2], 0.5, (0.0, 0.5), tmp)
    check(os.path.exists(outs[0]), "render")
    try:
        img = colophon_image(d, path, 7, None, [2], tmp)
        check(os.path.exists(img), "colophon image")
    except ImportError:
        print("(Pillow が無いので colophon の検査は省略)")
    # 全ページグレーなら判定不能
    g = fitz.open()
    gp = g.new_page(width=W, height=H)
    gp.insert_image(fitz.Rect(0, 0, W, H), pixmap=gray)
    check(measure_colors(g)["verdict"].startswith("判定不能"), "gray-only verdict")

    if fails:
        print("selftest FAIL:", *fails, sep="\n  ")
        return 1
    print("selftest OK: colorspace/hue verdict, find, offset, digest candidates, compact, render, colophon image")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("digest"); s.add_argument("pdf"); s.add_argument("--no-color", action="store_true")
    s.add_argument("--kw", action="append", default=[], help="名前=正規表現 (文字層で出現ページを数える)")
    s = sub.add_parser("find"); s.add_argument("pdf"); s.add_argument("patterns", nargs="+")
    s = sub.add_parser("text"); s.add_argument("pdf"); s.add_argument("pages")
    s.add_argument("--compact", action="store_true"); s.add_argument("--max-chars", type=int, default=0)
    s = sub.add_parser("offset"); s.add_argument("pdf"); s.add_argument("pages")
    s = sub.add_parser("render"); s.add_argument("pdf"); s.add_argument("pages")
    s.add_argument("--zoom", type=float, default=1.4); s.add_argument("--clip"); s.add_argument("--out-dir")
    s = sub.add_parser("colophon"); s.add_argument("pdf"); s.add_argument("page", type=int)
    s.add_argument("--frac"); s.add_argument("--thumbs", default=""); s.add_argument("--out-dir")
    a = ap.parse_args(argv)

    doc = fitz.open(a.pdf)
    if a.cmd == "digest":
        kws = []
        for item in a.kw:
            name, _, pat = item.partition("=")
            kws.append((name, pat or name))
        print(f"## {os.path.basename(a.pdf)}")
        print(digest(doc, color=not a.no_color, kws=kws))
    elif a.cmd == "find":
        for pat in a.patterns:
            hits = find_pages(doc, pat)
            print(f"{pat}: {len(hits)} pages: {compress(hits)}")
    elif a.cmd == "text":
        for p in parse_pages(a.pages, doc.page_count):
            t = doc[p - 1].get_text()
            t = compact(t) if a.compact else t
            if a.max_chars:
                t = t[: a.max_chars]
            print(f"===== PDF p{p}\n{t}")
    elif a.cmd == "offset":
        seen, diffs = estimate_offset(doc, parse_pages(a.pages, doc.page_count))
        for p, nums in seen:
            print(p, nums)
        print("PDF − ノンブル (頻度順):", diffs[:3] or "推定できず (数字だけのブロックが無い)")
    elif a.cmd == "render":
        out = a.out_dir or default_out_dir()
        for o in render_pages(doc, a.pdf, parse_pages(a.pages, doc.page_count), a.zoom, _pair(a.clip), out):
            print(o)
    elif a.cmd == "colophon":
        out = a.out_dir or default_out_dir()
        thumbs = parse_pages(a.thumbs, doc.page_count) if a.thumbs else []
        print(colophon_image(doc, a.pdf, a.page, _pair(a.frac), thumbs, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
