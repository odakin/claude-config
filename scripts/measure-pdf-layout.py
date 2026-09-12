#!/usr/bin/env python3
"""組版された PDF の版面を実測する — 「指定したのに効いていない」 を目視でなく数値で捕まえる.

対象は LaTeX に限らない。 error も warning も出さずに指定が無視される型
(用紙サイズ・表の幅指定・ラベルの縦位置・格子の間隔) は、 出力を測らないと
気づけない。 規約側の正本 = conventions/latex.md#silent-typesetting-traps。

できること:

  --size    用紙サイズと A4 / Letter 判定 (documentclass の指定が PDF に
            届いていない型の一発診断)
  --rules   水平罫線の y と、 罫線で区切られた各行の高さ。 表の行が意図した
            高さになっているか、 複数頁で揃っているかを見る
  --labels  与えた正規表現に一致する語について、 それが属する行の中心から
            どれだけずれているかを pt で出す (ラベルの縦中央合わせの調整用)
  --edges   描画物の右端・下端と、 紙の縁までの余白

⚠️ 「点線の格子の 1 目盛を測る」 機能は持たない。 点線は dash 属性つきの 1 本の
stroke path として出てくるので、 個別の点を数える素朴な実装では表の縦罫線を
拾ってしまう (2026-09-12 に実測で判明し、 推測で測る機能を載せるより持たない方を
選んだ)。 目盛を測るなら描画の dash 情報まで見る別実装が要る。

罫線と図の座標軸はどちらも「幅があって高さがほぼゼロ」 なので、 幅の閾値
(--rule-min-width) で切り分ける。 既定は表の罫線を拾い図の軸を捨てる側に倒してある。

使い方:
    measure-pdf-layout.py FILE.pdf --size --rules --edges
    measure-pdf-layout.py FILE.pdf --page 2 --labels '^Fig'
    measure-pdf-layout.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys

PAPERS = {(595.28, 841.89): "A4", (612.0, 792.0): "Letter",
          (841.89, 1190.55): "A3", (420.94, 595.28): "A5"}


def _fitz():
    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("PyMuPDF が要る: pip3 install --user pymupdf")
    return fitz


def paper_name(w: float, h: float, tol: float = 1.5) -> str:
    for (pw, ph), name in PAPERS.items():
        if abs(w - pw) < tol and abs(h - ph) < tol:
            return name
        if abs(w - ph) < tol and abs(h - pw) < tol:
            return name + " (横)"
    return "不明"


def horizontal_rules(page, min_width: float, max_height: float = 1.2) -> list[float]:
    """水平罫線の y 座標 (昇順・重複除去)。幅の閾値で図の座標軸を除外する。"""
    ys = {round(d["rect"].y0, 1) for d in page.get_drawings()
          if d["rect"].height < max_height and d["rect"].width > min_width}
    return sorted(ys)


def label_offsets(page, pattern: str, rules: list[float]):
    """pattern に一致する語の、属する行の中心からのずれ (pt)。"""
    rx = re.compile(pattern)
    out = []
    for w in page.get_text("words"):
        if not rx.search(w[4]):
            continue
        c = (w[1] + w[3]) / 2
        above = [r for r in rules if r < c]
        below = [r for r in rules if r > c]
        if above and below:
            mid = (max(above) + min(below)) / 2
            out.append((w[4], round(c, 1), round(mid, 1), round(c - mid, 1)))
    return out


def run(args) -> int:
    fitz = _fitz()
    doc = fitz.open(args.pdf)
    pages = range(doc.page_count) if args.page is None else [args.page - 1]
    if args.page is not None and not (0 <= args.page - 1 < doc.page_count):
        sys.exit(f"頁 {args.page} は無い (全 {doc.page_count} 頁)")

    if args.size:
        r = doc[0].rect
        print(f"用紙 {r.width:.2f} x {r.height:.2f} pt = {paper_name(r.width, r.height)}"
              f" / 全 {doc.page_count} 頁")
        sizes = {(round(doc[i].rect.width, 2), round(doc[i].rect.height, 2))
                 for i in range(doc.page_count)}
        if len(sizes) > 1:
            print(f"  ⚠️ 頁で用紙が違う: {sorted(sizes)}")

    for i in pages:
        page = doc[i]
        head = f"--- p{i + 1} ---"
        rules = horizontal_rules(page, args.rule_min_width)
        if args.rules:
            print(head)
            print(f"  水平罫線 y: {rules}")
            if len(rules) > 1:
                hs = [round(b - a, 1) for a, b in zip(rules, rules[1:])]
                print(f"  行の高さ: {hs}")
        if args.edges:
            rects = [d["rect"] for d in page.get_drawings()]
            if rects:
                print(head if not args.rules else "")
                print(f"  描画の右端 {max(r.x1 for r in rects):.1f} / 下端 "
                      f"{max(r.y1 for r in rects):.1f} / 紙の下まで "
                      f"{page.rect.height - max(r.y1 for r in rects):.1f} pt")
        if args.labels:
            for name, c, mid, off in label_offsets(page, args.labels, rules):
                print(f"  {name}: 中心 {c} / 枠中心 {mid} / ずれ {off:+.1f} pt")
    return 0


def selftest() -> int:
    """合成 PDF を作って各測定を検算する (外部の組版系に依存しない)。"""
    fitz = _fitz()
    doc = fitz.open()
    page = doc.new_page(width=595.28, height=841.89)   # A4
    for y in (100.0, 200.0, 350.0):                     # 罫線 3 本 → 行 2 つ
        page.draw_line((40, y), (500, y), width=0.4)
    page.insert_text((60, 155), "L1")                   # 1 行目のほぼ中央
    tmp = fitz.open("pdf", doc.tobytes())
    p = tmp[0]
    ok = True

    name = paper_name(p.rect.width, p.rect.height)
    ok &= name == "A4"
    print(f"  用紙判定: {name} {'OK' if name == 'A4' else 'NG'}")

    rules = horizontal_rules(p, min_width=300)
    hit = len(rules) == 3
    ok &= hit
    print(f"  罫線 3 本: {rules} {'OK' if hit else 'NG'}")

    offs = label_offsets(p, "L1", rules)
    hit = len(offs) == 1 and abs(offs[0][3]) < 10
    ok &= hit
    print(f"  ラベルのずれ: {offs} {'OK' if hit else 'NG'}")

    # 図の軸を罫線と誤認しないこと (幅の閾値を上げると細い線は落ちる)
    hit = horizontal_rules(p, min_width=600) == []
    ok &= hit
    print(f"  幅の閾値で除外: {'OK' if hit else 'NG'}")

    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--page", type=int, help="1 始まり。省略で全頁")
    ap.add_argument("--size", action="store_true", help="用紙サイズと A4/Letter 判定")
    ap.add_argument("--rules", action="store_true", help="水平罫線と行の高さ")
    ap.add_argument("--edges", action="store_true", help="描画の右端・下端と余白")
    ap.add_argument("--labels", metavar="REGEX", help="語の縦位置のずれ")
    ap.add_argument("--rule-min-width", type=float, default=380.0,
                    help="これより幅の広い水平線だけを罫線とみなす (既定 380 pt)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.pdf:
        ap.error("PDF を指定するか --selftest")
    if not any((args.size, args.rules, args.edges, args.labels)):
        args.size = args.rules = args.edges = True
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
