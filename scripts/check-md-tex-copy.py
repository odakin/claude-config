#!/usr/bin/env python3
"""md が正本・TeX が写しのノートで、 写しの文が正本と一致しているか、 写しが古くなっていないかを見る (骨格 raw/ と数式を直した TeX の突き合わせ)。

骨格は md-note-to-tex.py が作る。 考え方と手順 = conventions/latex.md#md-tex-source-and-copy

数式を TeX に直す作業は「転記」ではなく「生成」になりうる (語の置換・数値の
書き換えが申告なしに混じる)。ここでは次の 3 つの列が raw と一致することを見る。

  1. 日本語の字 (ひらがな・カタカナ・漢字・句読点・かぎ括弧) の並び
  2. 数字の並び (1 字ずつ。上付き・下付きの Unicode 数字は普通の数字に直してから比べる)
  3. 4 字以上の英字の語の並び (TeX の命令名と環境名は除く)

見ないもの: 文字で描いた図 (verbatim。TikZ の図に差し替える前提)、\\input の行、表の列幅、コメント、
数式の意味 (記号の取り違え、上付きと下付きの取り違え)。それは組んだ
PDF を読んで確かめる。

使い方:
  check-md-tex-copy.py DIR
    DIR/raw/sec-*.tex と DIR/sec-*.tex を比べる。不一致があれば exit 1。
  check-md-tex-copy.py DIR --source NOTE.md
    上に加えて、正本の md から raw を作り直し、保存してある raw と比べる。
    違えば「md を直したのに TeX の写しが古い」ので exit 1 (どの節かを言う)。
    pandoc が無いマシンでは、この比較だけ飛ばす。
"""
import re
import sys
import unicodedata
from pathlib import Path

SUBSUP = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")


def strip_comments(t: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", t)


def streams(t: str):
    t = strip_comments(t).translate(SUBSUP)
    # 文字で描いた図 (verbatim) は TikZ の図 (fig-*.tex) に差し替えるので比べない
    t = re.sub(r"\\begin\{verbatim\}.*?\\end\{verbatim\}", "", t, flags=re.S)
    t = re.sub(r"\\input\{[^}]*\}", "", t)
    # 表の列幅の指定は組版の調整なので比べない。欧文のアクセントは TeX の書き方でも同じ字とみなす
    t = "\n".join(l for l in t.split("\n") if "\\real{" not in l)
    for cmd, comb in (("'", "\u0301"), ('"', "\u0308"), (".", "\u0307"), ("`", "\u0300")):
        t = re.sub(r"\{?\\" + re.escape(cmd) + r"\{?([A-Za-z])\}?\}?", lambda m: unicodedata.normalize("NFC", m.group(1) + comb), t)
    cjk = [c for c in t if ("\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff"
                             or c in "、。「」『』・")]
    # 環境の名前 (pmatrix を \pmat{} に直す、など) と命令名は語に数えない
    nocmd = re.sub(r"\\(?:begin|end)\{[A-Za-z*]+\}", " ", t)
    nocmd = re.sub(r"\\[A-Za-z@]+\*?", " ", nocmd)
    # 数は「数字 1 字ずつの並び」で比べる。数の単位で切ると、p₁² (raw では 12 と続く) と
    # p_1^2 (TeX では 1 と 2 に割れる) が別物に見える
    nums = re.findall(r"\d", nocmd)
    words = [unicodedata.normalize("NFC", w) for w in re.findall(r"[A-Za-zÀ-ÿŻńü]{4,}", nocmd)]
    return {"日本語": cjk, "数": nums, "英字の語": words}


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b)) if len(a) != len(b) else None


def stale_sections(d: Path, source: Path):
    """正本の md から raw を作り直し、保存してある raw と並びが違う節を返す。"""
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("pandoc"):
        print("⚠️ pandoc が無いので、md と TeX の写しの鮮度は比べていない")
        return []
    conv = Path(__file__).with_name("md-note-to-tex.py")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, str(conv), str(source), tmp], check=True, capture_output=True)
        fresh = {p.name: streams(p.read_text(encoding="utf-8")) for p in (Path(tmp) / "raw").glob("sec-*.tex")}
    kept = {p.name: streams(p.read_text(encoding="utf-8")) for p in (d / "raw").glob("sec-*.tex")}
    return sorted(n for n in set(fresh) | set(kept) if fresh.get(n) != kept.get(n))


def main() -> int:
    d = Path(sys.argv[1])
    bad = 0
    if "--source" in sys.argv:
        source = Path(sys.argv[sys.argv.index("--source") + 1])
        stale = stale_sections(d, source)
        for n in stale:
            print(f"✗ {n}: 正本の {source.name} が変わっている (TeX の写しが古い。直し方 = conventions/latex.md#md-tex-source-and-copy)")
        bad += len(stale)
    for raw in sorted((d / "raw").glob("sec-*.tex")):
        new = d / raw.name
        if not new.exists():
            print(f"⏳ {raw.name}: まだ無い")
            bad += 1
            continue
        a, b = streams(raw.read_text(encoding="utf-8")), streams(new.read_text(encoding="utf-8"))
        ok = True
        for key in a:
            i = first_diff(a[key], b[key])
            if i is not None:
                ok = False
                sep = "" if key == "日本語" else " "
                print(f"✗ {raw.name} [{key}] {i} 番目から不一致")
                print(f"    raw: {sep.join(a[key][max(0, i - 12):i + 12])}")
                print(f"    new: {sep.join(b[key][max(0, i - 12):i + 12])}")
        if ok:
            print(f"✓ {raw.name}")
        else:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
