#!/usr/bin/env python3
"""Calibrate a digitized seal PNG against a *printed* reference — stroke width and ink color.

Why this exists
---------------
A seal PNG that looks right on screen prints wrong: laser printers sink
saturated dark reds into muddy brown, and thin vectorized strokes come out
thinner still. The ground truth is a **side-by-side photo**: stamp the real
seal next to the printed image on the same sheet, photograph both together
(same lighting), and measure the difference. This tool applies the two
corrections that measurement yields:

1. **Stroke width** — dilate the alpha channel; newly grown pixels take the
   color of their nearest original pixel (nearest-neighbor inpaint via
   ``scipy.ndimage.distance_transform_edt``), so the photographic ink
   texture extends outward instead of forming a dark rim (a naive
   Max/Min-filter on RGB creates an outline artifact).
2. **Ink color** — affine per-channel remap ``c' = c*mul + add`` on the
   sRGB channels. Affine (not flat fill) preserves the ink-density texture.
   Direction for laser printers: raise R, lift G/B floors slightly — the
   print process will sink R and lift G/B back toward the real vermilion.

Measurement recipe (do this BEFORE picking numbers)
---------------------------------------------------
On one photo containing both the real impression and the printed one:

* diameter ratio  ->  point size for the PDF overlay
  (real_px / printed_px * printed_pt = real seal in points)
* dark-quartile RGB of each  ->  color remap direction
* red-pixel coverage of the bounding circle  ->  dilation radius
  (tune --dilate so the source coverage rises by the same factor the
  print needs; printing itself adds ~+0.1 coverage from dot gain)

Usage
-----
    tune-seal-image.py IN.png --out OUT.png [--dilate 3]
        [--r-mul 1.25] [--g-mul 1.6] [--g-add 30] [--b-mul 1.6] [--b-add 18]
    tune-seal-image.py IN.png --report          # measure only, no output

Batch: run in a loop; identical parameters keep a variant pool consistent.
The transform is deterministic. Iterate: print a test page, photograph next
to the real seal, re-measure, adjust. One loop is usually enough.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
from PIL import Image, ImageFilter

try:
    from scipy.ndimage import distance_transform_edt
except ImportError:
    distance_transform_edt = None


def measure(img: Image.Image) -> dict:
    a = np.asarray(img.convert("RGBA")).astype(int)
    op = a[:, :, 3] > 200
    if not op.any():
        sys.exit("no opaque pixels")
    cols = a[:, :, :3][op]
    ys, xs = np.where(op)
    d = ((xs.max() - xs.min()) + (ys.max() - ys.min())) / 2
    lum = cols.sum(axis=1)
    dark = cols[np.argsort(lum)[: max(1, len(cols) // 4)]].mean(axis=0)
    return {
        "mean_rgb": tuple(cols.mean(axis=0).round(0).astype(int)),
        "dark_rgb": tuple(dark.round(0).astype(int)),
        "coverage": round(float(op.sum() / (np.pi * (d / 2) ** 2)), 3),
        "diameter_px": round(float(d)),
        "opaque_px": int(op.sum()),
    }


def tune(img: Image.Image, dilate: int, r_mul: float, g_mul: float, g_add: float,
         b_mul: float, b_add: float) -> Image.Image:
    a = np.asarray(img.convert("RGBA")).astype(np.uint8)
    if dilate > 0:
        if distance_transform_edt is None:
            sys.exit("scipy required for --dilate (pip install scipy)")
        alpha = a[:, :, 3]
        al_d = np.asarray(Image.fromarray(alpha).filter(ImageFilter.MaxFilter(2 * dilate + 1)))
        orig = alpha > 50
        _, idx = distance_transform_edt(~orig, return_indices=True)
        grow = (al_d > 50) & ~orig
        out = a.copy()
        for ch in range(3):
            out[:, :, ch][grow] = a[:, :, ch][idx[0][grow], idx[1][grow]]
        out[:, :, 3] = al_d
        a = out
    f = a.astype(float)
    m = a[:, :, 3] > 0
    f[:, :, 0] = np.clip(f[:, :, 0] * r_mul, 0, 255)
    f[:, :, 1] = np.clip(f[:, :, 1] * g_mul + g_add * m, 0, 255)
    f[:, :, 2] = np.clip(f[:, :, 2] * b_mul + b_add * m, 0, 255)
    f[:, :, 3] = a[:, :, 3]
    return Image.fromarray(f.astype(np.uint8))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out")
    ap.add_argument("--report", action="store_true", help="measure only")
    ap.add_argument("--dilate", type=int, default=3, help="stroke dilation radius in px (0 = off)")
    ap.add_argument("--r-mul", type=float, default=1.25)
    ap.add_argument("--g-mul", type=float, default=1.6)
    ap.add_argument("--g-add", type=float, default=30.0)
    ap.add_argument("--b-mul", type=float, default=1.6)
    ap.add_argument("--b-add", type=float, default=18.0)
    args = ap.parse_args()

    src = Image.open(args.input)
    if args.report:
        print(args.input, measure(src))
        return
    if not args.out:
        sys.exit("--out required (in-place refused)")
    res = tune(src, args.dilate, args.r_mul, args.g_mul, args.g_add, args.b_mul, args.b_add)
    res.save(args.out)
    print(args.input, "->", args.out)
    print("  before:", measure(src))
    print("  after :", measure(res))


if __name__ == "__main__":
    main()
