#!/usr/bin/env python3
"""Overlay a seal / signature image onto a generated PDF — keeping its color.

Why overlay on the PDF instead of embedding in the source workbook
------------------------------------------------------------------
Office form templates commonly ship with ``page_setup.blackAndWhite = True``.
That flag serves a purpose: input-cell background fills (orange / blue hints)
are suppressed in print, so the printed form looks like the official one.
But the same flag renders **any embedded image in monochrome** — a red seal
comes out gray (measured 2026-07-27 on a university travel form).

Turning the flag off recovers the red seal but leaks every background fill
onto paper, changing the form's appearance. The clean split is:

* keep the workbook black-and-white (form looks official), and
* stamp the seal onto the **PDF** afterwards, where page setup has no say.

A second benefit: the workbook stays pristine (no drawing parts added), so
none of the openpyxl / drawing round-trip hazards apply.

Placement is anchored to *text on the page* (e.g. the person's printed name),
not to pixel coordinates, so it survives layout drift between regenerations.

Usage
-----
    overlay-seal-pdf.py IN.pdf --out OUT.pdf \\
        --place 'page=1,anchor=尾田 欣也,occurrence=1,size=22,dx=6,dy=0' --image seal1.png \\
        --place 'page=3,anchor=尾田 欣也,size=26,dx=10' --image seal2.png

* ``--place`` and ``--image`` are paired in order (Nth place uses Nth image).
* ``anchor`` is searched with ``page.search_for``; ``occurrence`` picks the
  Nth hit (1-based, default 1).
* The image's left edge lands at the anchor's right edge + ``dx``; vertically
  centered on the anchor line + ``dy``. ``size`` is the square edge in points.
* In-place editing is refused: ``--out`` must differ from the input.

* ``avoid=h`` (default on) nudges the seal vertically off ruled lines: a
  printed seal crossing a black rule is a giveaway (a real impression inks
  *over* the line; a printed one visibly loses to it). The engine collects
  horizontal line segments from ``page.get_drawings()``, computes the chord
  length where each crosses the seal's inscribed circle, and picks the
  vertical shift (at most 0.6 x size) minimizing total crossing; ties prefer
  the smallest shift. When no shift clears every line (e.g. a table row
  shorter than the seal), it reports the residual crossing — consider a
  smaller ``size`` that fits inside the row.

Verification built in: after stamping, each target region is rasterized and
asserted to contain saturated-red pixels (a gray/monochrome seal fails the
run). Exit 2 on any failure; the output file is removed.
"""
from __future__ import annotations

import argparse
import os
import sys

import fitz


def parse_place(spec: str) -> dict:
    out = {"occurrence": 1, "size": 24.0, "dx": 6.0, "dy": 0.0, "avoid": "h"}
    for chunk in spec.split(","):
        if "=" not in chunk:
            sys.exit(f"bad --place chunk: {chunk!r} (expected key=value)")
        k, v = chunk.split("=", 1)
        k = k.strip()
        if k == "anchor":
            out["anchor"] = v
        elif k in ("page", "occurrence"):
            out[k] = int(v)
        elif k in ("size", "dx", "dy"):
            out[k] = float(v)
        elif k == "avoid":
            out[k] = v  # "h" = avoid horizontal rules (default), "none" = off
        else:
            sys.exit(f"unknown --place key: {k!r}")
    for req in ("page", "anchor"):
        if req not in out:
            sys.exit(f"--place needs {req}=: {spec!r}")
    return out


def hline_ys(page: fitz.Page, rect: fitz.Rect) -> list:
    """Horizontal ruled-line y's near rect (from vector drawings; thin rects count)."""
    ys = []
    pad = rect.height
    for dr in page.get_drawings():
        for item in dr["items"]:
            if item[0] == "l":
                q1, q2 = item[1], item[2]
                if abs(q1.y - q2.y) < 0.7 and min(q1.x, q2.x) < rect.x1 and max(q1.x, q2.x) > rect.x0 \
                        and rect.y0 - pad < q1.y < rect.y1 + pad:
                    ys.append((q1.y + q2.y) / 2)
            elif item[0] == "re":
                r = item[1]
                if r.height < 1.5 and r.width > 5 and r.x0 < rect.x1 and r.x1 > rect.x0 \
                        and rect.y0 - pad < r.y0 < rect.y1 + pad:
                    ys.append((r.y0 + r.y1) / 2)
    return sorted(set(round(y, 1) for y in ys))


def crossing(cy: float, radius: float, ys: list) -> float:
    """Total chord length where horizontal lines cross the inscribed circle."""
    total = 0.0
    for y in ys:
        d = abs(y - cy)
        if d < radius:
            total += 2 * (radius ** 2 - d ** 2) ** 0.5
    return total


def avoid_hlines(page: fitz.Page, rect: fitz.Rect, size: float) -> fitz.Rect:
    """Shift rect vertically to minimize ruled-line crossings (printed-seal giveaway)."""
    radius = size / 2
    cy = (rect.y0 + rect.y1) / 2
    ys = hline_ys(page, rect)
    if not ys:
        return rect
    cands = {0.0}
    for y in ys:  # shifts that just clear each line (0.5pt margin)
        for sgn in (-1, 1):
            shift = (y + sgn * (radius + 0.5)) - cy
            if abs(shift) <= 0.6 * size:
                cands.add(round(shift, 1))
    best = min(cands, key=lambda sh: (round(crossing(cy + sh, radius, ys), 2), abs(sh)))
    res = crossing(cy + best, radius, ys)
    if best != 0.0:
        print(f"  avoid=h: shifted {best:+.1f}pt (crossing {crossing(cy, radius, ys):.1f} -> {res:.1f}pt)")
    if res > 0.5:
        print(f"  ⚠️ avoid=h: {res:.1f}pt of ruled line still crossed (row shorter than seal? consider smaller size)")
    return fitz.Rect(rect.x0, rect.y0 + best, rect.x1, rect.y1 + best)


def red_fraction(page: fitz.Page, rect: fitz.Rect) -> float:
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect)
    total = red = 0
    step = max(1, pix.width // 24)
    for x in range(0, pix.width, step):
        for y in range(0, pix.height, step):
            r, g, b = pix.pixel(x, y)[:3]
            total += 1
            if r > 110 and r - g > 40 and r - b > 40:
                red += 1
    return red / total if total else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--place", action="append", required=True, help="page=N,anchor=TEXT[,occurrence=N,size=PT,dx=PT,dy=PT]")
    ap.add_argument("--image", action="append", required=True, help="image path, one per --place (paired in order)")
    args = ap.parse_args()

    if os.path.abspath(args.out) == os.path.abspath(args.pdf):
        sys.exit("--out must differ from the input (in-place refused)")
    if len(args.place) != len(args.image):
        sys.exit(f"{len(args.place)} --place vs {len(args.image)} --image (must pair up)")

    doc = fitz.open(args.pdf)
    targets = []
    for spec, image in zip(args.place, args.image):
        p = parse_place(spec)
        if not os.path.exists(image):
            sys.exit(f"image not found: {image}")
        page = doc[p["page"] - 1]
        hits = page.search_for(p["anchor"])
        if len(hits) < p["occurrence"]:
            sys.exit(f'anchor {p["anchor"]!r} occurrence {p["occurrence"]}: only {len(hits)} hit(s) on page {p["page"]}')
        a = hits[p["occurrence"] - 1]
        size = p["size"]
        x0 = a.x1 + p["dx"]
        y0 = (a.y0 + a.y1) / 2 - size / 2 + p["dy"]
        rect = fitz.Rect(x0, y0, x0 + size, y0 + size)
        if p.get("avoid", "h") == "h":
            rect = avoid_hlines(page, rect, size)
        page.insert_image(rect, filename=image, keep_proportion=True, overlay=True)
        targets.append((p["page"], rect, image))

    doc.save(args.out)
    doc.close()

    check = fitz.open(args.out)
    failures = []
    for pageno, rect, image in targets:
        frac = red_fraction(check[pageno - 1], rect)
        if frac < 0.02:
            failures.append(f"page {pageno} {os.path.basename(image)}: red fraction {frac:.3f} (< 0.02)")
    if failures:
        os.remove(args.out)
        sys.exit("seal color verification failed (output removed):\n  " + "\n  ".join(failures))
    for pageno, rect, image in targets:
        print(f"ok: p{pageno} {os.path.basename(image)} at ({rect.x0:.0f},{rect.y0:.0f}) size {rect.width:.0f}pt")


if __name__ == "__main__":
    main()
