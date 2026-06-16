#!/usr/bin/env python3
"""
close-pdf-form-boxes.py — Excel→PDF 出力で落ちたフォームの枠罫線を検出して閉じる。

WHY (office-automation.md#excel-pdf-bottom-border-drop):
  Excel は PDF / 印刷出力時に、 セル枠 (特にフォーム最下部の結合セル) の罫線を落とす
  ことがある。 罫線は xlsx に定義済 (openpyxl read-back で出る) なのに出力 PDF だけで
  消える。 日本の行政・学術様式は全項目を枠で囲う文化なので、 枠が「下線が無くて開いて」
  見えたら**それは設計ではなく必ず出力欠落** (= user 原則 2026-06-16「枠の下線が無くて
  開いている事は有り得ない」)。 → 機械的に全部検出して閉じる。

WHAT:
  PDF のベクター線だけを使い (= xlsx 不要・engine 非依存)、 「縦線 2 本が共有する y 区間で、
  上辺か下辺の横線が片方だけ欠けた矩形 (= 3 辺あって 1 辺欠け = 開いた枠)」 を検出し、
  欠けた辺を draw して閉じる。 横線対で縦辺が欠けた場合も対称に閉じる。
  ⚠️ fill-in 下線 (= 縦線対を持たない単独の水平線) には触れない (= 枠ではないので
  誤って枠化しない = 設計を壊さない)。

SCOPE / 限界:
  - 「1 辺だけ欠けた枠」 を閉じる (= Excel の典型故障)。 2 辺以上欠けた枠 (= 極めて稀) は
    対象外 (3 辺の存在を手掛かりにするため)。
  - 生成物 PDF への後描画なので、 PDF を**再生成したら再度かける** (= xlsx→PDF pipeline の
    最後に挟む)。 冪等 (= 既に閉じている枠は再実行しても二重描画しない、 presence 判定で skip)。

USAGE:
  close-pdf-form-boxes.py input.pdf [output.pdf]   # 既定は in-place
  close-pdf-form-boxes.py input.pdf --dry-run       # 検出のみ報告 (描かない)
  close-pdf-form-boxes.py input.pdf --selftest      # 内蔵 self-test
"""
import sys, os

SNAP = 1.0     # 同一線とみなす座標スナップ (= 二重描画される細線を 1 本に、 整数丸め)
MTOL = 2.5     # 線の存在判定の許容 (= この距離内に線があれば「在る」)
MINBOX = 8.0   # これ未満の y/x 共有は箱とみなさない (= 偶発交差の除外)
WIDTH = 0.75   # 閉じ線の太さ (= thin 罫線相当)


def _merge(intervals, tol):
    """(lo, hi) 区間群を重なり (tol 許容) でマージして極大区間に。"""
    if not intervals:
        return []
    ivs = sorted(intervals)
    out = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= out[-1][1] + tol:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(x) for x in out]


def _covered(intervals, lo, hi, tol):
    """[lo, hi] が区間群の和で覆われているか (= 線がその範囲を span するか)。"""
    cur = lo
    for a, b in sorted(intervals):
        if a > cur + tol:
            return False
        cur = max(cur, b)
        if cur >= hi - tol:
            return True
    return cur >= hi - tol


def _segments(page):
    """page のベクター線を (水平線群 by y, 縦線群 by x) に。 座標は SNAP 丸め。"""
    hs, vs = {}, {}   # y(snapped) -> [(x0,x1)] ,  x(snapped) -> [(y0,y1)]
    def snap(v):
        return round(v / SNAP) * SNAP
    def add_seg(x0, y0, x1, y1):
        if abs(y0 - y1) <= 1.0 and abs(x0 - x1) > 1.0:        # 水平
            y = snap((y0 + y1) / 2)
            hs.setdefault(y, []).append((min(x0, x1), max(x0, x1)))
        elif abs(x0 - x1) <= 1.0 and abs(y0 - y1) > 1.0:      # 垂直
            x = snap((x0 + x1) / 2)
            vs.setdefault(x, []).append((min(y0, y1), max(y0, y1)))
    for dr in page.get_drawings():
        for it in dr["items"]:
            if it[0] == "l":
                add_seg(it[1].x, it[1].y, it[2].x, it[2].y)
            elif it[0] == "re":
                r = it[1]
                add_seg(r.x0, r.y0, r.x1, r.y0)
                add_seg(r.x0, r.y1, r.x1, r.y1)
                add_seg(r.x0, r.y0, r.x0, r.y1)
                add_seg(r.x1, r.y0, r.x1, r.y1)
    hs = {y: _merge(v, MTOL) for y, v in hs.items()}
    vs = {x: _merge(v, MTOL) for x, v in vs.items()}
    return hs, vs


def _h_present(hs, y, x0, x1):
    segs = []
    for hy, ivs in hs.items():
        if abs(hy - y) <= MTOL:
            segs += ivs
    return _covered(segs, x0, x1, MTOL)


def _v_present(vs, x, y0, y1):
    segs = []
    for vx, ivs in vs.items():
        if abs(vx - x) <= MTOL:
            segs += ivs
    return _covered(segs, y0, y1, MTOL)


def find_open_edges(page):
    """欠けた枠の辺 (= 描くべき線) を [(x0,y0,x1,y1, which)] で返す。"""
    hs, vs = _segments(page)
    todo = []
    vx = sorted(vs.keys())
    # --- 縦線対 → 上/下の横線が片方欠け (= Excel の主故障) ---
    for i, xL in enumerate(vx):
        for xR in vx[i + 1:]:
            for (a1, b1) in vs[xL]:
                for (a2, b2) in vs[xR]:
                    yt, yb = max(a1, a2), min(b1, b2)
                    if yb - yt < MINBOX:
                        continue
                    # 隣接性: xL..xR の間にこの y 区間と重なる縦線があれば「隣接でない」
                    if any(xL < xm < xR and any(max(yt, c) < min(yb, d) - MTOL for (c, d) in vs[xm]) for xm in vx):
                        continue
                    top = _h_present(hs, yt, xL, xR)
                    bot = _h_present(hs, yb, xL, xR)
                    if top and not bot:
                        todo.append((xL, yb, xR, yb, "bottom"))
                    elif bot and not top:
                        todo.append((xL, yt, xR, yt, "top"))
    # --- 横線対 → 左/右の縦線が片方欠け (= 稀、 対称処理) ---
    hy = sorted(hs.keys())
    for i, yT in enumerate(hy):
        for yB in hy[i + 1:]:
            for (a1, b1) in hs[yT]:
                for (a2, b2) in hs[yB]:
                    xl, xr = max(a1, a2), min(b1, b2)
                    if xr - xl < MINBOX:
                        continue
                    if any(yT < ym < yB and any(max(xl, c) < min(xr, d) - MTOL for (c, d) in hs[ym]) for ym in hy):
                        continue
                    left = _v_present(vs, xl, yT, yB)
                    right = _v_present(vs, xr, yT, yB)
                    if left and not right:
                        todo.append((xr, yT, xr, yB, "right"))
                    elif right and not left:
                        todo.append((xl, yT, xl, yB, "left"))
    # 重複除去
    uniq = []
    for e in todo:
        if not any(abs(e[0]-u[0]) < SNAP and abs(e[1]-u[1]) < SNAP and abs(e[2]-u[2]) < SNAP and abs(e[3]-u[3]) < SNAP for u in uniq):
            uniq.append(e)
    return uniq


def close_boxes(in_pdf, out_pdf=None, dry_run=False):
    import fitz
    out_pdf = out_pdf or in_pdf
    d = fitz.open(in_pdf)
    total = 0
    for pno, page in enumerate(d):
        edges = find_open_edges(page)
        for (x0, y0, x1, y1, which) in edges:
            total += 1
            print(f"  p{pno+1}: 開いた枠の{which}辺を閉じる  ({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f})")
            if not dry_run:
                sh = page.new_shape()
                sh.draw_line(fitz.Point(x0, y0), fitz.Point(x1, y1))
                sh.finish(color=(0, 0, 0), width=WIDTH)
                sh.commit()
    if total == 0:
        print("  開いた枠なし (= 全ての枠が閉じている)")
    elif not dry_run:
        tmp = out_pdf + ".tmp"
        d.save(tmp); d.close(); os.replace(tmp, out_pdf)
        print(f"✅ {total} 辺を閉じて保存: {out_pdf}")
    else:
        print(f"(dry-run) {total} 辺が欠けている")
    return total


def _selftest():
    """3 辺の箱 (= 下辺欠け) を作り、 検出→閉じ→再検出 0 を確認。"""
    import fitz
    d = fitz.open()
    pg = d.new_page(width=300, height=300)
    sh = pg.new_shape()
    # 箱: 左(50)・右(150) 縦線 y50..150、 上辺 y50 のみ (下辺 y150 を欠く)
    sh.draw_line(fitz.Point(50, 50), fitz.Point(50, 150))
    sh.draw_line(fitz.Point(150, 50), fitz.Point(150, 150))
    sh.draw_line(fitz.Point(50, 50), fitz.Point(150, 50))
    sh.finish(color=(0, 0, 0), width=0.75); sh.commit()
    p = "/tmp/_cpfb_selftest.pdf"; d.save(p); d.close()
    n1 = close_boxes(p, dry_run=True)
    assert n1 == 1, f"下辺欠けを検出できず (got {n1})"
    close_boxes(p)
    n2 = close_boxes(p, dry_run=True)
    assert n2 == 0, f"閉じた後も欠けと判定 (冪等性 NG, got {n2})"
    os.remove(p)
    print("✅ selftest OK (検出 1 / 閉じ後 0 = 冪等)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selftest" in args:
        _selftest(); sys.exit(0)
    if not args:
        print(__doc__); sys.exit(1)
    dry = "--dry-run" in args
    paths = [a for a in args if not a.startswith("--")]
    inp = paths[0]
    out = paths[1] if len(paths) > 1 else None
    close_boxes(inp, out, dry_run=dry)
