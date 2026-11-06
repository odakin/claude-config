#!/usr/bin/env python3
"""解答用紙・書類の写真 (前処理済み) の右に余白を足し、 赤で点と直し方を書き、 解答の行に下線・丸・矢印を引く。

    python3 annotate-scan.py <spec.json> <in.jpg> <out.jpg> [--font F] [--margin 0.62] [--quality 88]
    python3 annotate-scan.py --grid <in.jpg> <out.jpg>      # 座標を読むための格子 (縦線 = 横 5% ごと、 横線 = 縦 2% ごと)
    python3 annotate-scan.py --selftest

spec = {"total": "17.5", "max": "35",                 # 余白の上に「合計 17.5 / 35」 (total が無ければ書かない)
        "total_y": 0.165, "top": 0.235,                # 合計の高さと、 最初の注記を置ける高さ (割合。 既定は左の値)
        "notes": [note, ...]}
note = {"label": "問2 (1)", "score": "0 / 5",        # 見出し (label と score を並べる)
        "y": 0.34,                                     # 注記を置きたい高さ = 解答のその行の高さ (割合)
        "target": [x, y] | null,                       # 矢印の先 (解答用紙の上、 割合)
        "text": "… $数式$ …" | null,                   # 改行は \\n。 $…$ は matplotlib の mathtext で組む (上付き・分数・根号)
        "marks": [["u", x0, x1, y], ["c", x0, y0, x1, y1]]}   # 下線 / 丸 (楕円)
- 座標はすべて元の画像に対する割合 (0〜1)。 先に --grid の画像で、 間違えた行の高さと矢印の先を読む。
- 注記は上から順に積み、 前の注記と重なるときは下へずらす。 長い行は「。 」 の後ろで折り返し (数式の中では切らない)、
  それでも余白からはみ出す行は字を小さくする。 全体が下にはみ出すときは全体の字を小さくする。
- mathtext が無い (matplotlib が無い) と $…$ は組めない = 止める。 和文の font は --font か機械の既定 (macOS の
  ヒラギノ角ゴシック W6 / Linux の Noto Sans CJK / Windows の 游ゴシック・メイリオ) から探す。
- 使い方・注記の書き方の規則 (解答の行を読み直して書く・全員分を目で確かめる) = conventions/exam-grading-return.md#red-annotation。
"""
import argparse
import io
import json
import math
import os
import sys
import tempfile

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    print("annotate-scan: Pillow が要る = pip install Pillow", file=sys.stderr)
    sys.exit(2)

RED = (215, 0, 0)
FONT_CANDIDATES = (
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
)


def find_font(explicit=None):
    for p in ([explicit] if explicit else []) + list(FONT_CANDIDATES):
        if p and os.path.exists(p):
            return p
    sys.exit("annotate-scan: 和文の font が見つからない = --font <ttf/ttc の path> で渡す")


_MT = None


def _mathtext():
    global _MT
    if _MT is None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            from matplotlib import mathtext
            from matplotlib.font_manager import FontProperties
        except ImportError:
            sys.exit("annotate-scan: $…$ の数式には matplotlib が要る = pip install matplotlib")
        matplotlib.rcParams["mathtext.fontset"] = "cm"
        _MT = (mathtext, FontProperties)
    return _MT


class Annotator:
    def __init__(self, src, spec, font, margin=0.62):
        self.src, self.spec, self.font, self.margin = src.convert("RGB"), spec, font, margin
        self.W, self.H = self.src.size

    def seg_image(self, seg, is_math, px):
        if is_math:
            mathtext, FontProperties = _mathtext()
            buf = io.BytesIO()
            mathtext.math_to_image(f"${seg}$", buf, prop=FontProperties(size=px * 1.08), dpi=72, format="png",
                                   color="#d70000")
            buf.seek(0)
            return Image.open(buf).convert("RGBA")
        f = ImageFont.truetype(self.font, px)
        x1 = f.getbbox(seg)[2]
        img = Image.new("RGBA", (max(1, x1) + 2, int(px * 1.25)), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((0, int(px * 0.1)), seg, font=f, fill=RED + (255,))
        return img

    def render_lines(self, text, px):
        """[(line_height, [segment images])]"""
        out = []
        for line in text.split("\n"):
            parts = line.split("$")
            imgs = [self.seg_image(p, i % 2 == 1, px) for i, p in enumerate(parts) if p]
            out.append((max([int(px * 1.25)] + [g.size[1] for g in imgs]), imgs))
        return out

    def _width(self, line, px):
        return sum(g.size[0] + int(lh * 0.06) for lh, imgs in self.render_lines(line, px) for g in imgs)

    def wrap(self, text, tp, avail):
        """長い行は「。 」 の後ろで改行する (字を縮める前に。 数式の中では切らない)。"""
        lines = []
        for line in text.split("\n"):
            while True:
                w = self._width(line, tp)
                cut = line.rfind("。 ", 0, len(line) - 2)
                if w <= avail or cut < 0 or line.count("$", 0, cut) % 2:
                    break
                while cut > 0:  # 収まる位置まで切る点を戻す
                    head_ = line[:cut + 1]
                    if self._width(head_, tp) <= avail or head_.count("。 ") == 0:
                        break
                    nc = line.rfind("。 ", 0, cut)
                    if nc < 0 or line.count("$", 0, nc) % 2:
                        break
                    cut = nc
                lines.append(line[:cut + 1])
                line = line[cut + 2:]
            lines.append(line)
        return "\n".join(lines)

    def layout(self, scale):
        W, H = self.W, self.H
        sp, tp = int(0.024 * H * scale), int(0.0145 * H * scale)
        blocks, cursor = [], int(self.spec.get("top", 0.235) * H)
        avail = int(W * self.margin) - int(W * 0.03) - 30
        self.overflow = []
        for n in self.spec["notes"]:
            head = self.render_lines(f"{n['label']}  {n['score']}", sp)
            body, tpn = [], tp
            text = n.get("text") or ""
            n = {**n, "text": self.wrap(text, tp, avail) if text else None}
            while n.get("text"):
                body = self.render_lines(n["text"], tpn)
                wid = max(sum(g.size[0] + int(lh * 0.06) for g in imgs) for lh, imgs in body)
                if wid <= avail or tpn < tp * 0.7:
                    if wid > avail:
                        self.overflow.append(n["label"])
                    break
                tpn = int(tpn * 0.94)
            h = sum(lh + int(sp * 0.15) for lh, _ in head) + sum(lh + int(tpn * 0.2) for lh, _ in body)
            y0 = max(int(n["y"] * H), cursor)
            blocks.append((n, y0, head, body, sp, tpn, h))
            cursor = y0 + h + int(0.012 * H)
        return blocks, cursor

    def render(self):
        W, H = self.W, self.H
        scale = 1.0
        blocks, end = self.layout(scale)
        while end > 0.985 * H and scale > 0.6:
            scale -= 0.05
            blocks, end = self.layout(scale)
        im = Image.new("RGB", (int(W * (1 + self.margin)), H), (255, 255, 255))
        im.paste(self.src, (0, 0))
        d = ImageDraw.Draw(im)
        d.line([(W + 4, 0), (W + 4, H)], fill=(235, 180, 180), width=3)
        lw = max(3, W // 500)
        X0 = int(W * 1.03)

        def paste_lines(lines, x, y, gap):
            for lh, imgs in lines:
                cx = x
                for g in imgs:
                    im.paste(g, (cx, y + (lh - g.size[1]) // 2), g)
                    cx += g.size[0] + int(lh * 0.06)
                y += lh + gap
            return y

        def arrow(p0, p1):
            d.line([p0, p1], fill=RED, width=lw)
            a = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
            L = 0.012 * H
            for s in (+0.45, -0.45):
                d.line([p1, (int(p1[0] - L * math.cos(a + s)), int(p1[1] - L * math.sin(a + s)))], fill=RED, width=lw)

        if self.spec.get("total") is not None:
            mx = self.spec.get("max")
            label = f"合計 {self.spec['total']}" + (f" / {mx}" if mx is not None else "")
            paste_lines(self.render_lines(label, int(0.032 * H)), X0, int(self.spec.get("total_y", 0.165) * H), 0)
        for n, y0, head, body, sp, tp, _h in blocks:
            y = paste_lines(head, X0, y0, int(sp * 0.15))
            paste_lines(body, X0, y, int(tp * 0.2))
            if n.get("target"):
                tx, ty = n["target"]
                arrow((W + 10, y0 + head[0][0] // 2 + int(0.006 * H)), (int(tx * W), int(ty * H)))
            for m in n.get("marks", []):
                if m[0] == "u":
                    _, x0, x1, yy = m
                    d.line([(int(x0 * W), int(yy * H)), (int(x1 * W), int(yy * H))], fill=RED, width=lw)
                elif m[0] == "c":
                    _, x0, y0_, x1, y1 = m
                    d.ellipse([(int(x0 * W), int(y0_ * H)), (int(x1 * W), int(y1 * H))], outline=RED, width=lw)
        self.blocks, self.scale = blocks, scale
        return im


def grid_image(src, font, max_side=1560):
    im = src.convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(font, max(10, int(H * 0.012)))
    for i in range(0, 101, 5):
        x = int(i / 100 * W)
        d.line([(x, 0), (x, H)], fill=(0, 160, 255), width=2)
        d.text((x + 3, 3), f"{i}", fill=(0, 110, 255), font=f)
    for j in range(0, 101, 2):
        y = int(j / 100 * H)
        d.line([(0, y), (W, y)], fill=(255, 140, 0), width=2)
        d.text((3, y + 3), f"{j}", fill=(255, 80, 0), font=f)
    im.thumbnail((max_side, max_side))
    return im


def selftest():
    fails = []

    def check(cond, name, detail=""):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)
            if detail:
                print("     " + str(detail)[:600])

    try:
        font = find_font()
    except SystemExit:
        print("SKIP: 和文の font が無い機械 (selftest は font を要る)")
        return 0
    W, H = 1000, 1400
    src = Image.new("RGB", (W, H), (255, 255, 255))
    ImageDraw.Draw(src).line([(100, 560), (500, 560)], fill=(0, 0, 0), width=3)
    long = "これは長い注記の一文目です。 ここで折り返されるはずの二文目がとても長く続いていきます。 三文目もあります。"
    spec = {"total": "7", "max": "10", "notes": [
        {"label": "問1", "score": "2 / 5", "y": 0.38, "target": [0.30, 0.40], "text": long,
         "marks": [["u", 0.10, 0.50, 0.42], ["c", 0.60, 0.30, 0.80, 0.36]]},
        {"label": "問2", "score": "5 / 5", "y": 0.39, "target": None, "text": None},
    ]}
    a = Annotator(src, spec, font)
    im = a.render()
    check(im.size == (int(W * 1.62), H), "出力の幅 = 元の幅 × (1 + 余白)", im.size)
    px = im.getpixel((300, int(0.42 * H)))
    check(px[0] > 180 and px[1] < 60 and px[2] < 60, "下線が解答用紙の指定の高さに赤で引かれる", px)
    margin = im.crop((W + 10, 0, im.size[0], H))
    reds = sum(1 for p in margin.getdata() if p[0] > 180 and p[1] < 80 and p[2] < 80)
    check(reds > 500, "余白に赤の字がある", reds)
    n0 = a.blocks[0][0]
    check(n0["text"].count("\n") >= 1 and all(not ln.startswith(" ") for ln in n0["text"].split("\n")),
          "長い行は「。 」 の後ろで折り返す (次の行の頭に空白を残さない)", n0["text"])
    b0, b1 = a.blocks[0], a.blocks[1]
    check(b1[1] >= b0[1] + b0[6], "後の注記は前の注記と重ならない位置へ下げる", (b0[1], b0[6], b1[1]))
    check(a.blocks[0][1] >= int(0.38 * H), "注記は指定の高さより上に置かない", a.blocks[0][1])
    # 合計の行: total が無ければ書かない
    a2 = Annotator(src, {"notes": []}, font)
    im2 = a2.render()
    top = im2.crop((W + 10, int(0.15 * H), im2.size[0], int(0.21 * H)))
    check(not any(p[0] > 180 and p[1] < 80 for p in top.getdata()), "total が無ければ合計を書かない")
    g = grid_image(src, font)
    check(max(g.size) <= 1560 and g.getpixel((0, 0)) != (255, 255, 255), "格子の画像は縮小して線を引く", g.size)
    # 数式 (matplotlib があるときだけ)
    try:
        import matplotlib  # noqa: F401
        have_mpl = True
    except ImportError:
        have_mpl = False
    if have_mpl:
        plain = a.render_lines("あいう", 40)[0][0]
        frac = a.render_lines(r"$\frac{K}{3}(VN)^{1/3}U^{-2/3}$", 40)[0][0]
        check(frac > plain, "$…$ の分数は組まれて (行が高くなって) 描かれる", (plain, frac))
        spec3 = {"notes": [{"label": "問3", "score": "0 / 5", "y": 0.5, "target": None,
                            "text": r"正しくは $\lambda^3$。 長い文が続いて余白を越えそうでも $x^2$ の中では切らない。"}]}
        a3 = Annotator(src, spec3, font)
        a3.render()
        t3 = a3.blocks[0][0]["text"]
        check(all(ln.count("$") % 2 == 0 for ln in t3.split("\n")), "数式の中では折り返さない", t3)
    else:
        print("SKIP: matplotlib が無い = $…$ の検査を飛ばす")
    with tempfile.TemporaryDirectory() as td:
        sp, ip, op = (os.path.join(td, n) for n in ("s.json", "in.jpg", "out.jpg"))
        json.dump(spec, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
        src.save(ip, quality=92)
        rc = main([sp, ip, op])
        check(rc == 0 and os.path.exists(op), "CLI が画像を書く")
    print(f"\n{'FAIL' if fails else 'OK'}: {len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description="解答用紙の写真に赤で点と直し方を書き込む (余白・下線・丸・矢印)")
    ap.add_argument("--grid", action="store_true", help="座標を読むための格子の画像を書く (in out の 2 つ)")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--font", default=None)
    ap.add_argument("--margin", type=float, default=0.62, help="右に足す余白の幅 (元の幅に対する割合)")
    ap.add_argument("--quality", type=int, default=88)
    a = ap.parse_args(argv)
    font = find_font(a.font)
    if a.grid:
        if len(a.paths) != 2:
            ap.error("--grid は <in.jpg> <out.jpg>")
        grid_image(Image.open(a.paths[0]), font).save(a.paths[1], quality=85)
        print(a.paths[1])
        return 0
    if len(a.paths) != 3:
        ap.error("<spec.json> <in.jpg> <out.jpg>")
    spec = json.load(open(a.paths[0], encoding="utf-8"))
    ann = Annotator(Image.open(a.paths[1]), spec, font, a.margin)
    im = ann.render()
    for label in ann.overflow:
        print(f"⚠️ {os.path.basename(a.paths[1])} {label}: 行が余白からはみ出す", file=sys.stderr)
    im.save(a.paths[2], quality=a.quality)
    print(a.paths[2], im.size, f"scale={ann.scale:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
