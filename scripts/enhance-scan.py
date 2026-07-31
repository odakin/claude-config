#!/usr/bin/env python3
"""手書き文書の撮影写真の可読化: 紙の切り出し + 照明ムラ除去 + コントラスト伸張 + タイル出力。

机の上に置いた紙をスマホで撮った写真 (= 斜め照明・机の写り込み・薄い鉛筆) を、
モデルが読める形に前処理する。 スキャナを通していない「撮っただけ」 の紙
(答案・手書きノート・書類・ホワイトボード等) を大量に読むときに使う。

規約: conventions/photographed-document-transcription.md

処理:
  1. 背景除算 (shading correction) で照明ムラを消す
  2. 低周波成分から紙の外接矩形を取って切り出す (机を捨てて文字あたりの画素を稼ぐ)
  3. 紙の内部だけで統計を取ってコントラストを伸張 (薄い鉛筆を黒側へ寄せる)
  4. モデルの画像入力上限 (長辺 ~1568px) に合わせてタイル分割

Usage:
    enhance-scan.py <src.jpg> <outstem> [--tiles tb|lr|q|RxC|1] [--width 1560] [--rot 0]

    # A4 縦 1 枚を上下 2 分割 (既定。 ふつうの手書き文書はこれで十分読める)
    enhance-scan.py page-1.jpg /tmp/page-1- --tiles tb

    # 書き込みが密なものは格子分割で解像度を稼ぐ (行 x 列)
    #   → 3a.jpg 3b.jpg … のように {行}{列} の suffix が付く
    enhance-scan.py dense-1.jpg /tmp/dense-1- --tiles 4x2

    # 紙が横向きに写っている写真は --rot で立てる (時計回りに 90 度なら -90)
    enhance-scan.py sideways.jpg /tmp/sideways- --rot -90 --tiles 4x2

⚠️ 出力タイルの長辺は 1560 前後に収めること。 それより大きくしてもモデル側で
   ~1568px に縮小されるだけで、 かえって 1 文字あたりの画素が減る。

初出: 2026-07 (紙の試験答案 + 手書き持ち込み資料 の一括読み取り)。
"""
import sys
import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage


def flatten(path, rot=0):
    im = ImageOps.exif_transpose(Image.open(path)).convert("L")
    if rot:
        im = im.rotate(rot, expand=True)
    g = np.asarray(im, dtype=np.float32)
    # 照明ムラは低周波なので、 縮小画像でぼかしてから戻す (= フル解像度での
    # 巨大 sigma の gaussian は 4000x2268 で数十秒かかり実用にならない)
    k = 8
    small = g[::k, ::k]
    bs = ndimage.gaussian_filter(small, sigma=max(small.shape) / 28.0)
    bg = ndimage.zoom(bs, (g.shape[0] / bs.shape[0], g.shape[1] / bs.shape[1]), order=1)
    bg = bg[:g.shape[0], :g.shape[1]]
    if bg.shape != g.shape:                      # zoom の丸めずれを吸収
        bg = np.pad(bg, ((0, g.shape[0] - bg.shape[0]), (0, g.shape[1] - bg.shape[1])), mode="edge")
    return g / np.maximum(bg, 1.0), bg


def otsu(v):
    h, edges = np.histogram(v, bins=256)
    p = h / h.sum()
    c = np.cumsum(p)
    mids = (edges[:-1] + edges[1:]) / 2
    mu = np.cumsum(p * mids)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = (mu[-1] * c - mu) ** 2 / (c * (1 - c))
    return mids[np.nanargmax(var)]


def _longest_run(v, soft_expand=True):
    """1D 明度プロファイルで「明るい」 最長連続区間を返す。

    ⚠️ 中点しきい値だけで切ると紙の縁 (= 影で暗い) を机と誤判定して内側を切り落とす
    (= 答案左端の小問ラベルが欠ける事故)。 中点で芯を見つけたあと、 低いしきい値で
    外側へ広げ直す 2 段構えにする。
    """
    lo, hi = float(v.min()), float(v.max())
    idx = np.where(v > (lo + hi) / 2)[0]
    if len(idx) == 0:
        return 0, len(v) - 1
    runs = np.split(idx, np.where(np.diff(idx) != 1)[0] + 1)
    r = max(runs, key=len)
    a, b = int(r[0]), int(r[-1])
    if not soft_expand:
        return a, b
    soft = lo + 0.18 * (hi - lo)          # 縁の影まで拾う緩いしきい値
    while a > 0 and v[a - 1] > soft:
        a -= 1
    while b < len(v) - 1 and v[b + 1] > soft:
        b += 1
    return a, b


def paper_bbox(bg):
    """ぼかし画像 (= 紙は明るく机は暗い) から紙の外接矩形。

    ⚠️ 罠 2 つ (2026-07-31 実装時に両方踏んだ):
      1. 背景除算後の画像では机も 1.0 付近になり紙/机を判別できない → 低周波 bg で判別する。
      2. 連結成分 + Otsu は机の照明反射 (ハイライト) を紙と繋げてしまい全面を返す
         → 行・列の明度プロファイルの「最長連続区間」 で取る方が頑健。
         列は紙が画面幅の大半を占めて対比が弱いので、 先に行で絞ってから列を測る。
    """
    H, W = bg.shape
    # 行は厳しめ (= 上下は机が広く写り込むので広げない)、 列は緩め (= 左右は本文が
    # 縁ぎりぎりまで書かれていて切ると小問ラベルが欠ける)
    y0, y1 = _longest_run(bg.mean(axis=1), soft_expand=False)
    x0, x1 = _longest_run(bg[y0:y1 + 1].mean(axis=0), soft_expand=True)
    # ⚠️ 余白は widen 側に倒す (= 文字が 1 文字でも欠けると転記が壊れる。 机が少し
    #    写り込む損より、 小問ラベルや行頭が切れる損の方がはるかに大きい)
    padx, pady = int(W * 0.035), int(H * 0.012)
    return (max(0, x0 - padx), max(0, y0 - pady), min(W, x1 + padx), min(H, y1 + pady))


def enhance(path, rot=0):
    flat, bg = flatten(path, rot)
    x0, y0, x1, y1 = paper_bbox(bg)
    roi = ndimage.median_filter(flat[y0:y1, x0:x1], size=3)   # 紙の粒子を落とす
    # ⚠️ 統計は「確実に紙」 の内側だけで取る。 切り出し矩形の縁には机が残るので、
    #    roi 全体で percentile を取ると暗い机に引っ張られて伸張が効かなくなる。
    h, w = roi.shape
    inner = roi[int(h * .10):int(h * .90), int(w * .10):int(w * .90)]
    # ⚠️ 紙の地は「高い percentile」 では取れない (= 光の反射が外れ値として上に出る)。
    #    紙は画素の大多数なので中央値が地。 上側 (反射) は clip して捨てる。
    paper = np.median(inner)
    lo = np.percentile(inner, 0.5)     # 最も濃い筆跡
    out = np.clip((roi - lo) / max(paper - lo, 1e-6), 0, 1)
    out = out ** 1.4                   # 中間調 (薄い鉛筆) を黒側へ寄せる
    return Image.fromarray((out * 255).astype(np.uint8))


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help") else 2)
    src, stem = sys.argv[1], sys.argv[2]
    a = sys.argv[3:]
    tiles = a[a.index("--tiles") + 1] if "--tiles" in a else "tb"
    width = int(a[a.index("--width") + 1]) if "--width" in a else 1600
    rot = int(a[a.index("--rot") + 1]) if "--rot" in a else 0

    im = enhance(src, rot)
    w, h = im.size
    ov = 0.03
    if tiles == "tb":
        parts = [("T", (0, 0, w, int(h * (0.5 + ov)))), ("B", (0, int(h * (0.5 - ov)), w, h))]
    elif tiles == "lr":
        parts = [("L", (0, 0, int(w * (0.5 + ov)), h)), ("R", (int(w * (0.5 - ov)), 0, w, h))]
    elif "x" in tiles:                       # --tiles RxC (= 行 x 列 の格子分割)
        r, c = (int(v) for v in tiles.split("x"))
        parts = []
        for i in range(r):
            for j in range(c):
                y0 = int(h * (i / r - (ov if i else 0)))
                y1 = int(h * ((i + 1) / r + (ov if i < r - 1 else 0)))
                x0 = int(w * (j / c - (ov if j else 0)))
                x1 = int(w * ((j + 1) / c + (ov if j < c - 1 else 0)))
                parts.append((f"{i+1}{chr(97+j)}", (x0, y0, x1, y1)))
    elif tiles == "q":
        parts = [("1", (0, 0, w, int(h * (0.25 + ov)))),
                 ("2", (0, int(h * (0.25 - ov)), w, int(h * (0.5 + ov)))),
                 ("3", (0, int(h * (0.5 - ov)), w, int(h * (0.75 + ov)))),
                 ("4", (0, int(h * (0.75 - ov)), w, h))]
    else:
        parts = [("", (0, 0, w, h))]
    for tag, box in parts:
        p = im.crop(box)
        p.thumbnail((width, width))
        out = f"{stem}{tag}.jpg"
        p.save(out, quality=92)
        print(out, p.size)


if __name__ == "__main__":
    main()
