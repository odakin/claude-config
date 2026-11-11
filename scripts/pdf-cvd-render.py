#!/usr/bin/env python3
"""pdf-cvd-render.py — PDF の各頁を PNG にし、 色覚 3 型 (P・D・T) と grayscale の見え方を並べて作る。 --selftest 内蔵。

用途: スライドや図の「色だけに頼っていないか」 を目で確かめる (beamer-slides.md §16 の 3 = 地 + 2 色)。
2 色の系列が、 色を失っても線種・点の形・直接ラベルで区別できるかを、 頁ごとの 5 枚 (元・protan・deutan・tritan・gray) で見る。

- 色覚の変換 = Machado, Oliveira, Fernandes (2009) の severity 1.0 の行列を線形 sRGB で掛ける
- grayscale = 線形の相対輝度 (0.2126, 0.7152, 0.0722) を sRGB に戻した値
- 行列の積は np.einsum で書く: macOS の Accelerate に繋いだ numpy は `@` で偽の
  "divide by zero / overflow encountered in matmul" を出すことがある (実測、 scientific-computing.md#cas-library-traps)
- 一覧にまとめるのは pdf-contact-sheet.py か、 --sheet で頁ごとに 5 枚を横に並べた PNG

使い方:
  python3 pdf-cvd-render.py deck.pdf OUTDIR [--dpi 130] [--sheet]
  python3 pdf-cvd-render.py --selftest
出力: OUTDIR/<pdf名>-p<N>.png と -p<N>-{protan,deutan,tritan,gray}.png (--sheet なら -p<N>-cvd-sheet.png も)
"""
import argparse
import os
import sys

import numpy as np

MATRICES = {
    "protan": np.array([[0.152286, 1.052583, -0.204868],
                        [0.114503, 0.786281, 0.099216],
                        [-0.003882, -0.048116, 1.051998]]),
    "deutan": np.array([[0.367322, 0.860646, -0.227968],
                        [0.280085, 0.672501, 0.047413],
                        [-0.011820, 0.042940, 0.968881]]),
    "tritan": np.array([[1.255528, -0.076749, -0.178779],
                        [-0.078411, 0.930809, 0.147602],
                        [0.004733, 0.691367, 0.303900]]),
}
LUMA = np.array([0.2126, 0.7152, 0.0722])


def to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)


def variants(img):
    """img: (h, w, 3) floats in [0, 1] sRGB. Returns dict name -> (h, w, 3) uint8."""
    lin = to_linear(img)
    out = {"orig": (img * 255).round().astype(np.uint8)}
    for name, m in MATRICES.items():
        out[name] = (to_srgb(np.einsum("hwc,kc->hwk", lin, m)) * 255).round().astype(np.uint8)
    g = (to_srgb(np.einsum("hwc,c->hw", lin, LUMA)) * 255).round().astype(np.uint8)
    out["gray"] = np.repeat(g[..., None], 3, axis=2)
    return out


def render(pdf, outdir, dpi, sheet):
    import fitz
    from PIL import Image
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf))[0]
    doc = fitz.open(pdf)
    for i, page in enumerate(doc, 1):
        pix = page.get_pixmap(dpi=dpi)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[..., :3] / 255.0
        v = variants(arr)
        Image.fromarray(v["orig"]).save(f"{outdir}/{base}-p{i}.png")
        for name in ("protan", "deutan", "tritan", "gray"):
            Image.fromarray(v[name]).save(f"{outdir}/{base}-p{i}-{name}.png")
        if sheet:
            row = np.concatenate([v[k] for k in ("orig", "protan", "deutan", "tritan", "gray")], axis=1)
            Image.fromarray(row).save(f"{outdir}/{base}-p{i}-cvd-sheet.png")
    print(f"{len(doc)} pages -> {outdir}")


def selftest():
    # white and black are fixed points of every matrix (rows sum to 1) and of grayscale
    img = np.array([[[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]])
    v = variants(img)
    for name in ("protan", "deutan", "tritan", "gray"):
        assert np.all(np.abs(v[name].astype(int) - v["orig"].astype(int)) <= 1), name
    # grayscale of a known colour: #FAF9F6 -> 0.976 (sRGB of its relative luminance)
    c = np.array([[[0xFA, 0xF9, 0xF6]]]) / 255.0
    g = variants(c)["gray"][0, 0, 0] / 255.0
    assert abs(g - 0.976) < 0.004, g
    # pure red and pure green collapse toward each other for deutan (the case the tool exists for)
    rg = np.array([[[1.0, 0.0, 0.0], [0.0, 0.6, 0.0]]])
    d = variants(rg)["deutan"].astype(float)
    o = variants(rg)["orig"].astype(float)
    assert np.linalg.norm(d[0, 0] - d[0, 1]) < np.linalg.norm(o[0, 0] - o[0, 1]), "deutan should reduce red-green distance"
    print("selftest: PASS (fixed points, known grayscale value, red-green collapse under deutan)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("outdir", nargs="?")
    ap.add_argument("--dpi", type=int, default=130)
    ap.add_argument("--sheet", action="store_true", help="also write one PNG per page with the 5 renders side by side")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    if not a.pdf or not a.outdir:
        ap.error("pdf and outdir are required (or --selftest)")
    render(a.pdf, a.outdir, a.dpi, a.sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
