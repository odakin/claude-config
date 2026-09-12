#!/usr/bin/env python3
"""公開図 (PDF / PNG) を pixel から数値に読み戻す — 枠・目盛りを検出して軸を較正し、点と境界線を data 座標で返す。

用途 = 本文の式・数値と図が整合するかの照合、 referee / 審査委員として他人の図を検算するとき、
自分の図の軸ラベルと描画内容の drift 検出。 目視で「だいたい合っている」 と言う代わりに数値を出す。
規約 = conventions/matplotlib-figure-qa.md#read-back-published-figure

前提 = 直交 1 枠の 2D plot (log / linear)、 枠線が図中で最も長い直線。 対数軸なら --xlog / --ylog。
較正は「目盛り pixel ↔ 目盛り値」 の 2 点以上。 目盛り pixel は --xticks auto で検出するか明示する。

  # PDF の 2 頁目の図を 400 dpi で描画し、 x 目盛り 3 本を自動検出して 1e-60,1e-30,1e0 に対応づける
  read-plot-axes.py --pdf paper.pdf --page 2 --dpi 400 --clip 60,55,300,260 \\
      --xlog --xticks auto --xvalues 1e-60,1e-30,1e0 \\
      --ylog --yticks auto --yvalues 1e0,1e-10,1e-20 --dots --line right

  # pixel ↔ 値を直接与える (目盛り検出が効かない図)
  read-plot-axes.py --image fig.png --xlog --xmap 430:1e-60,1148.5:1e0 --ylog --ymap 118:1e0,784.5:1e-20 --dots

出力 = 枠 / 目盛り / 点 (data 座標) / 境界線の傾きと不変量 (log-log なら log x + a log y = const)。
--json で機械可読。 --selftest は既知の図を matplotlib で作って往復検査 (foil つき)。
"""
from __future__ import annotations

import argparse
import json
import math
import sys

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit("numpy が要る: pip install numpy")


# ---------------------------------------------------------------- image load

def load_gray(path: str) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(path).convert("L")).astype(int)


def render_pdf(path: str, page: int, dpi: int, clip: str | None) -> np.ndarray:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    pg = doc[page - 1]
    rect = None
    if clip:
        x0, y0, x1, y1 = (float(v) for v in clip.split(","))
        rect = fitz.Rect(x0, y0, x1, y1)
    pix = pg.get_pixmap(dpi=dpi, clip=rect)
    buf = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n >= 3:  # RGB(A) -> luma
        return (0.299 * buf[:, :, 0] + 0.587 * buf[:, :, 1] + 0.114 * buf[:, :, 2]).astype(int)
    return buf[:, :, 0].astype(int)


# ------------------------------------------------------------- detection

def detect_frame(dark: np.ndarray, frac: float = 0.5) -> dict:
    """図中で最も長い horizontal / vertical の暗線を枠とみなす。"""
    h, w = dark.shape
    rows = np.where(dark.sum(axis=1) > frac * w)[0]
    cols = np.where(dark.sum(axis=0) > frac * h)[0]
    if rows.size < 2 or cols.size < 2:
        raise SystemExit(
            f"枠を検出できない (長い暗線 rows={rows.size} cols={cols.size})。"
            " --threshold を上げるか --frame で明示する"
        )
    return {"top": int(rows.min()), "bottom": int(rows.max()),
            "left": int(cols.min()), "right": int(cols.max())}


def _clusters(idx: np.ndarray, gap: int = 2) -> list[float]:
    out: list[list[int]] = []
    for i in idx:
        if out and i - out[-1][-1] <= gap:
            out[-1].append(int(i))
        else:
            out.append([int(i)])
    return [float(np.mean(c)) for c in out]


def detect_ticks(dark: np.ndarray, frame: dict, axis: str, depth: int = 12,
                 min_len: int = 3) -> list[float]:
    """枠の外側の帯にある目盛りの中心 pixel。 axis='x' は下辺の下、 'y' は左辺の左。"""
    if axis == "x":
        band = dark[frame["bottom"] + 2: frame["bottom"] + 2 + depth, :].sum(axis=0)
    else:
        band = dark[:, max(frame["left"] - 2 - depth, 0): max(frame["left"] - 2, 1)].sum(axis=1)
    return _clusters(np.where(band >= min_len)[0])


def detect_dots(img: np.ndarray, frame: dict, threshold: int, min_area: int, max_area: int,
                max_extent: int, min_fill: float = 0.72,
                max_aspect: float = 1.25) -> list[tuple[float, float]]:
    """枠内の塗り潰し marker (連結成分) の重心 pixel。

    ⚠️ 枠の内側に文字がある図では、 文字も「小さく暗い連結成分」 として候補に上がる。
    円盤は bounding box の π/4 ≈ 0.785 を埋め縦横がほぼ等しいので、 充填率 (min_fill) と
    縦横比 (max_aspect) で落とす。 それでも残る場合は --min-area / --max-area で面積を絞る。
    """
    sub = img[frame["top"]: frame["bottom"] + 1, frame["left"]: frame["right"] + 1] < threshold
    lab, n = _label(sub)
    out = []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if not (min_area <= ys.size <= max_area):
            continue
        w = xs.max() - xs.min() + 1
        h = ys.max() - ys.min() + 1
        if w > max_extent or h > max_extent:
            continue
        if max(w, h) / min(w, h) > max_aspect:      # 円盤は正方の bbox
            continue
        if ys.size / (w * h) < min_fill:            # 塗り潰しか (文字は筆画なので低い)
            continue
        out.append((float(xs.mean() + frame["left"]), float(ys.mean() + frame["top"])))
    return sorted(out, key=lambda p: (p[1], p[0]))


def _label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    try:
        from scipy import ndimage

        return ndimage.label(mask)
    except ImportError:
        pass
    lab = np.zeros(mask.shape, dtype=int)
    cur = 0
    h, w = mask.shape
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or lab[sy, sx]:
                continue
            cur += 1
            stack = [(sy, sx)]
            lab[sy, sx] = cur
            while stack:
                y, x = stack.pop()
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = cur
                        stack.append((ny, nx))
    return lab, cur


def boundary_points(dark: np.ndarray, frame: dict, side: str, inset: int = 3) -> np.ndarray:
    """各行 (または列) で枠の内側にある最も端の暗 pixel = 境界線の軌跡。"""
    pts = []
    t, b = frame["top"] + inset, frame["bottom"] - inset
    l, r = frame["left"] + inset, frame["right"] - inset
    if side in ("right", "left"):
        for y in range(t, b):
            xs = np.where(dark[y, l:r])[0] + l
            if xs.size:
                pts.append((float(xs.max() if side == "right" else xs.min()), float(y)))
    else:
        for x in range(l, r):
            ys = np.where(dark[t:b, x])[0] + t
            if ys.size:
                pts.append((float(x), float(ys.max() if side == "bottom" else ys.min())))
    return np.array(pts, dtype=float)


# ------------------------------------------------------------- calibration

class Axis:
    """pixel ↔ data の 1 次写像 (log 軸なら data は log10)。"""

    def __init__(self, pixels, values, log: bool):
        self.log = log
        v = [math.log10(x) for x in values] if log else list(values)
        p = list(pixels)
        if len(p) != len(v) or len(p) < 2:
            raise SystemExit(f"較正点が足りない: pixel {len(p)} 個 vs 値 {len(v)} 個 (2 点以上、同数)")
        self.slope, self.intercept = np.polyfit(np.array(p), np.array(v), 1)
        resid = max(abs(self.slope * pp + self.intercept - vv) for pp, vv in zip(p, v))
        self.residual = float(resid)
        # 読み取り精度の下限 = 1 pixel 相当 (目盛り重心は ±0.5 px でしか決まらない)
        self.per_px = abs(float(self.slope))

    def to_data(self, px: float) -> float:
        return float(self.slope * px + self.intercept)

    def fmt(self, px: float) -> str:
        d = self.to_data(px)
        return f"1e{d:.2f}" if self.log else f"{d:.4g}"


def parse_map(spec: str) -> tuple[list[float], list[float]]:
    pix, val = [], []
    for part in spec.split(","):
        p, v = part.split(":")
        pix.append(float(p))
        val.append(float(v))
    return pix, val


# ------------------------------------------------------------------- report

def analyse(img: np.ndarray, args) -> dict:
    dark = img < args.threshold
    frame = detect_frame(dark) if not args.frame else dict(
        zip(("left", "top", "right", "bottom"), (float(v) for v in args.frame.split(","))))
    out: dict = {"frame": frame, "shape": list(img.shape)}

    def axis_for(kind: str) -> Axis:
        mapspec = getattr(args, f"{kind}map")
        if mapspec:
            pix, val = parse_map(mapspec)
        else:
            tickspec = getattr(args, f"{kind}ticks")
            valspec = getattr(args, f"{kind}values")
            if not (tickspec and valspec):
                raise SystemExit(f"--{kind}map か (--{kind}ticks + --{kind}values) が要る")
            pix = (detect_ticks(dark, frame, kind) if tickspec == "auto"
                   else [float(v) for v in tickspec.split(",")])
            val = [float(v) for v in valspec.split(",")]
            out[f"{kind}ticks_px"] = pix
            if len(pix) != len(val):
                raise SystemExit(
                    f"{kind} 目盛りの検出数 {len(pix)} が値の数 {len(val)} と合わない "
                    f"(検出 pixel = {['%.1f' % p for p in pix]})。 --{kind}ticks に pixel を明示する"
                )
        return Axis(pix, val, getattr(args, f"{kind}log"))

    ax = axis_for("x")
    ay = axis_for("y")
    out["calibration"] = {
        "x": {"log": ax.log, "residual": ax.residual, "per_px": ax.per_px},
        "y": {"log": ay.log, "residual": ay.residual, "per_px": ay.per_px},
    }

    if args.dots:
        dots = detect_dots(img, frame, args.dot_threshold, args.min_area, args.max_area,
                           args.max_extent, args.min_fill, args.max_aspect)
        out["dots"] = [{"px": [round(px, 1), round(py, 1)],
                        "x": ax.fmt(px), "y": ay.fmt(py),
                        "x_data": ax.to_data(px), "y_data": ay.to_data(py)} for px, py in dots]

    if args.line:
        pts = boundary_points(dark, frame, args.line)
        if pts.size:
            xs = np.array([ax.to_data(p) for p in pts[:, 0]])
            ys = np.array([ay.to_data(p) for p in pts[:, 1]])
            keep = slice(len(xs) // 10, len(xs) - len(xs) // 10)  # 端は枠・ラベルを拾う
            slope, intercept = np.polyfit(xs[keep], ys[keep], 1)
            resid = float(np.max(np.abs(ys[keep] - (slope * xs[keep] + intercept))))
            span = float(np.ptp(ys[keep])) or 1.0
            out["line"] = {
                "side": args.line, "n_points": int(len(xs)),
                "slope": float(slope), "intercept": float(intercept),
                "max_residual": resid,
                "trustworthy": bool(resid < 0.05 * span),
                "invariant": (f"log10(y) {'-' if slope < 0 else '+'} "
                              f"{abs(slope):.3g}*log10(x) = {intercept:.3f}"),
            }
    return out


def render_text(out: dict) -> str:
    L = [f"frame  left={out['frame']['left']} right={out['frame']['right']} "
         f"top={out['frame']['top']} bottom={out['frame']['bottom']}"]
    for k in ("xticks_px", "yticks_px"):
        if k in out:
            L.append(f"{k:10s} {['%.1f' % v for v in out[k]]}")
    c = out["calibration"]
    L.append(f"calib  x: log={c['x']['log']} residual={c['x']['residual']:.3f} "
             f"1px={c['x']['per_px']:.3f} | y: log={c['y']['log']} "
             f"residual={c['y']['residual']:.3f} 1px={c['y']['per_px']:.3f}")
    L.append("       ⚠ 読み取り精度の下限 = 上の 1px 値 (log 軸なら dex)。 これより細かい桁を主張しない")
    for d in out.get("dots", []):
        L.append(f"dot    px={d['px']}  x={d['x']}  y={d['y']}")
    if "line" in out:
        ln = out["line"]
        L.append(f"line   side={ln['side']} n={ln['n_points']} slope={ln['slope']:.3f} "
                 f"intercept={ln['intercept']:.3f} maxres={ln['max_residual']:.3f}")
        L.append(f"       {ln['invariant']}")
        if not ln["trustworthy"]:
            L.append("       ❌ 残差が大きい = この側の端 pixel は 1 本の直線ではない "
                     "(文字・網掛け・曲線を拾っている)。 図を crop するか --line を使わず "
                     "点の読み取りだけを使う")
    return "\n".join(L)


# ------------------------------------------------------------------ selftest

def selftest() -> int:
    """既知の図を作って往復で読み戻す。 foil = 点を 1 つ消したら検出数が減ることまで見る。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("SKIP: matplotlib が無い (selftest は図の生成に要る)")
        return 0
    import tempfile
    import os

    ok = True

    def check(name, got, want, tol):
        nonlocal ok
        good = abs(got - want) <= tol
        ok &= good
        print(f"  {'OK ' if good else 'FAIL'} {name}: got {got:.4g} want {want:.4g} (tol {tol:g})")

    # 既知の真値: log-log、 境界線 log10 y = -1*log10 x + C、 点 2 つ
    C = -14.8
    dots_true = [(1e-67, 1e-4), (1e-67, 1e-18)]
    xlim, ylim = (1e-70, 1e10), (1e-25, 1e2)

    def build(path, with_second_dot=True):
        fig, ax = plt.subplots(figsize=(5, 4), dpi=120)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        gx = np.logspace(math.log10(xlim[0]), math.log10(xlim[1]), 400)
        ax.plot(gx, 10 ** (C - np.log10(gx)), color="black", lw=1.6)
        pts = dots_true if with_second_dot else dots_true[:1]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "o", color="black", ms=7, ls="none")
        ax.set_xticks([1e-60, 1e-30, 1e0])
        ax.set_yticks([1e0, 1e-10, 1e-20])
        fig.savefig(path, facecolor="white")
        plt.close(fig)

    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "a.png")
        build(p1)
        img = load_gray(p1)
        dark = img < 100
        frame = detect_frame(dark)
        print(f"  frame = {frame}")

        xt = detect_ticks(dark, frame, "x")
        yt = detect_ticks(dark, frame, "y")
        print(f"  ticks x={['%.1f' % v for v in xt]} y={['%.1f' % v for v in yt]}")
        check("x tick count", len(xt), 3, 0)
        check("y tick count", len(yt), 3, 0)
        if len(xt) != 3 or len(yt) != 3:
            print("FAIL: 目盛り検出が 3 本にならない")
            return 1

        ax_ = Axis(xt, [1e-60, 1e-30, 1e0], True)
        ay_ = Axis(yt, [1e0, 1e-10, 1e-20], True)
        # 目盛り重心は ±0.5 px でしか決まらないので、 残差の許容は 1 pixel 相当の dex で測る
        print(f"  1 pixel = {ax_.per_px:.3f} dex (x) / {ay_.per_px:.3f} dex (y)")
        check("x calib residual", ax_.residual, 0.0, ax_.per_px)
        check("y calib residual", ay_.residual, 0.0, ay_.per_px)

        dots = detect_dots(img, frame, 100, 15, 4000, 40)
        check("dot count", len(dots), 2, 0)
        for (px, py), (tx, ty) in zip(dots, sorted(dots_true, key=lambda t: -t[1])):
            check(f"dot x (1e{math.log10(tx):.0f})", ax_.to_data(px), math.log10(tx), 0.8)
            check(f"dot y (1e{math.log10(ty):.0f})", ay_.to_data(py), math.log10(ty), 0.5)

        pts = boundary_points(dark, frame, "right")
        xs = np.array([ax_.to_data(p) for p in pts[:, 0]])
        ys = np.array([ay_.to_data(p) for p in pts[:, 1]])
        keep = slice(len(xs) // 10, len(xs) - len(xs) // 10)
        slope, intercept = np.polyfit(xs[keep], ys[keep], 1)
        check("line slope", float(slope), -1.0, 0.05)
        check("line intercept (C)", float(intercept), C, 0.3)

        # foil: 点を 1 つ消したら検出数が 1 に落ちること (= 検出器が定数を返していない)
        p2 = os.path.join(td, "b.png")
        build(p2, with_second_dot=False)
        foil = detect_dots(load_gray(p2), frame, 100, 15, 4000, 40)
        check("foil dot count", len(foil), 1, 0)

    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image")
    ap.add_argument("--pdf")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--clip", help="PDF 座標 x0,y0,x1,y1 (pt)")
    ap.add_argument("--threshold", type=int, default=100, help="線とみなす明度 (既定 100)")
    ap.add_argument("--dot-threshold", type=int, default=80)
    ap.add_argument("--frame", help="left,top,right,bottom を明示 (既定 = 自動検出)")
    for k in "xy":
        ap.add_argument(f"--{k}log", action="store_true")
        ap.add_argument(f"--{k}map", help=f"{k} の pixel:値 を 2 点以上 (例 430:1e-60,1148:1e0)")
        ap.add_argument(f"--{k}ticks", help="auto か pixel の列")
        ap.add_argument(f"--{k}values", help="目盛りの値の列 (--%sticks と同数・同順)" % k)
    ap.add_argument("--dots", action="store_true", help="塗り潰し marker を読む")
    ap.add_argument("--line", choices=["right", "left", "top", "bottom"],
                    help="その側の境界線を直線 fit する")
    ap.add_argument("--min-area", type=int, default=20)
    ap.add_argument("--max-area", type=int, default=6000)
    ap.add_argument("--max-extent", type=int, default=60)
    ap.add_argument("--min-fill", type=float, default=0.72,
                    help="marker とみなす bounding box 充填率の下限 (円盤 = 0.785)")
    ap.add_argument("--max-aspect", type=float, default=1.25, help="marker の縦横比の上限")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not (args.image or args.pdf):
        ap.error("--image か --pdf のどちらかが要る (--selftest も可)")

    img = load_gray(args.image) if args.image else render_pdf(args.pdf, args.page, args.dpi, args.clip)
    out = analyse(img, args)
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else render_text(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
