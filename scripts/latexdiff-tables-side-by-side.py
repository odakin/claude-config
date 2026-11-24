#!/usr/bin/env python3
"""latexdiff-tables-side-by-side.py — 表 (tabular) を塊として比べた latexdiff の出力で、 消えた側の表を戻し、 前の表を赤・新しい表を青で上下に並べる。--selftest 内蔵。

なぜ: latexdiff は表の中の語を語の列で対応させるので、 行や欄の文が変わった表の差分は、 語が隣の欄に入り込んで読めなくなる
(実測)。 列の指定を変えた表は組版が止まる ([`../conventions/latex.md#latexdiff-tabular-colspec`](../conventions/latex.md#latexdiff-tabular-colspec))。
latexdiff に表を絵と同じ塊として渡す (`--config 'PICTUREENV=(?:picture|DIFnomarkup|tabular)[\\w\\d*@]*'`) と、
前の表は `%DIFDELCMD < ` の comment になり、 新しい表は印なしで入る = 組版は通るが、 前の表が PDF から消える。
この道具はその comment を戻して色を付ける。 表の中の 1 語ずつの差は出ない = 2 つの表を上下に並べて読む形。

何をするか (DIFF.tex を書き換える):
  同じ場所で入れ替わった表 (削除の直後に追加)  -> `{\\color{red}<前の表>}\\par\\medskip` + `{\\color{blue}<新しい表>}`
  相手の無い消えた表 (消した・移した元)        -> `{\\color{red}<前の表>}`
  相手の無い足した表 (足した・移した先)        -> `{\\color{blue}<新しい表>}`
  浮動体 (table) の中の印 (`\\DIFdelbeginFL` など) と外の印 (`\\DIFdelbegin`) の両方を扱う。 置き換えた数を出す。
止まる: 差分の preamble が色の package (color / xcolor) を読まない (exit 2)。
警告 (exit 1): 置き換えた後も `%DIFDELCMD < \\begin{tabular}` が残る (形が想定と違う) /
  表の中に `\\DIFadd` / `\\DIFdel` がある (表を塊として比べていない = PICTUREENV に tabular を足していない)。

順番: latexdiff (上の PICTUREENV つき) → この道具 → 組版 → 表の頁を画像で見る
(道具 = `latexdiff-changed-pages.py --render`)。 表を塊にすると表の中の数式・文は着色されない = 表の変更は並べた 2 つで読む、 と送る相手に書く。

Usage
    latexdiff-tables-side-by-side.py DIFF.tex [--old-color red] [--new-color blue] [--gap '\\medskip']
    latexdiff-tables-side-by-side.py --selftest
"""
import argparse
import re
import sys

DEL = r"\\DIFdelbegin(FL)? %DIFDELCMD < (\\begin\{tabular\}.*?)%DIFDELCMD < %%%\n\\DIFdelend(?:FL)? "
ADD = r"\\DIFaddbegin(FL)? (\\begin\{tabular\}.*?\\end\{tabular\})\n?\\DIFaddend(?:FL)? ?"
PAIR_RE = re.compile(DEL + ADD, re.S)
DEL_RE = re.compile(DEL, re.S)
ADD_RE = re.compile(ADD, re.S)
COLOR_RE = re.compile(r"\\(?:RequirePackage|usepackage)(?:\[[^\]]*\])?\{[^}]*\b(?:x?color)\b[^}]*\}")
TABULAR_RE = re.compile(r"\\begin\{tabular\}.*?\\end\{tabular\}", re.S)


def uncomment(block):
    """`%DIFDELCMD < ` の comment を外した前の表 (末尾が \\end{tabular} であることを確かめる)。"""
    lines = [re.sub(r"^%DIFDELCMD < ", "", line) for line in block.rstrip("\n").split("\n")]
    old = "\n".join(lines).rstrip()
    if "%DIFDELCMD" in old or not old.endswith("\\end{tabular}"):
        raise ValueError("消えた表の形が想定と違う: " + old[-80:])
    return old


def transform(text, old_color="red", new_color="blue", gap="\\medskip"):
    """書き換えた本文と (入れ替え, 消えた表, 足した表) の数を返す。"""
    red = "{\\color{%s}" % old_color
    blue = "{\\color{%s}" % new_color
    text, n_pair = PAIR_RE.subn(lambda m: red + uncomment(m.group(2)) + "}\\par" + gap + "\n" + blue + m.group(4) + "}\n", text)
    text, n_del = DEL_RE.subn(lambda m: red + uncomment(m.group(2)) + "}\n", text)
    text, n_add = ADD_RE.subn(lambda m: blue + m.group(2) + "}\n", text)
    return text, (n_pair, n_del, n_add)


def problems(text):
    out = []
    if "%DIFDELCMD < \\begin{tabular}" in text:
        out.append("置き換えた後も comment の表が残った (形が想定と違う): 該当の区画を読んで直す")
    for m in TABULAR_RE.finditer(text):
        if re.search(r"\\DIF(?:add|del)\b|\\DIF(?:add|del)(?:begin|end)", m.group(0)):
            out.append("表の中に差分の印がある = 表を塊として比べていない (latexdiff の PICTUREENV に tabular を足す)")
            break
    return out


def run(path, old_color, new_color, gap):
    text = open(path, encoding="utf-8").read()
    if not COLOR_RE.search(text):
        print("止まる: 差分の preamble が color / xcolor を読まない (色を付けられない)", file=sys.stderr)
        return 2
    new, (n_pair, n_del, n_add) = transform(text, old_color, new_color, gap)
    if new != text:
        open(path, "w", encoding="utf-8").write(new)
    print(f"表: 入れ替え {n_pair} (前 = {old_color}・新 = {new_color} で上下に) / 消えた表 {n_del} / 足した表 {n_add}")
    warn = problems(new)
    for w in warn:
        print("⚠️ " + w)
    return 1 if warn else 0


SAMPLE = r"""\documentclass{article}
\RequirePackage{color}\definecolor{RED}{rgb}{1,0,0}\definecolor{BLUE}{rgb}{0,0,1} %DIF PREAMBLE
\begin{document}
\begin{table}[h]
\centering
\DIFdelbeginFL %DIFDELCMD < \begin{tabular}{lll}
%DIFDELCMD < Fruit & Colour & Taste \\
%DIFDELCMD < Apple & red & sweet \\
%DIFDELCMD < \end{tabular}
%DIFDELCMD < %%%
\DIFdelendFL \DIFaddbeginFL \begin{tabular}{lp{0.4\textwidth}l}
Fruit & Colour, longer & Taste \\
Apple & green & sweet \\
\end{tabular}
\DIFaddendFL \caption{Fruits.}
\end{table}
A loose table:

\DIFdelbegin %DIFDELCMD < \begin{tabular}{cc}
%DIFDELCMD < 1 & 2 \\
%DIFDELCMD < \end{tabular}
%DIFDELCMD < %%%
\DIFdelend \DIFaddbegin \begin{tabular}{ccc}
1 & 2 & 3 \\
\end{tabular}
\DIFaddend

Text after.
\end{document}
"""

LONE = r"""\RequirePackage{color}
\DIFdelbeginFL %DIFDELCMD < \begin{tabular}{c}
%DIFDELCMD < moved \\
%DIFDELCMD < \end{tabular}
%DIFDELCMD < %%%
\DIFdelendFL \caption{A.}
text \DIFaddbeginFL \begin{tabular}{c}
moved \\
\end{tabular}
\DIFaddendFL \caption{B.}
"""


def selftest():
    import os
    import tempfile
    checks = []
    out, n = transform(SAMPLE)
    checks.append(("2 組の入れ替え (浮動体の中と外)", n == (2, 0, 0)))
    checks.append(("前の表の comment を外した", "{\\color{red}\\begin{tabular}{lll}\nFruit & Colour & Taste \\\\" in out))
    checks.append(("新しい表は青", "{\\color{blue}\\begin{tabular}{lp{0.4\\textwidth}l}" in out))
    checks.append(("浮動体の外の表も並べた", "{\\color{red}\\begin{tabular}{cc}" in out and "{\\color{blue}\\begin{tabular}{ccc}" in out))
    checks.append(("caption を残した", "}\n\\caption{Fruits.}" in out))
    checks.append(("印が残らない", "%DIFDELCMD" not in out and "\\DIFaddbegin" not in out and "\\DIFdelbegin" not in out))
    checks.append(("警告なし", problems(out) == []))
    out2, n2 = transform(LONE)
    checks.append(("相手の無い表 = 消えた 1・足した 1", n2 == (0, 1, 1) and "{\\color{red}\\begin{tabular}{c}\nmoved" in out2))
    raw = "\\begin{tabular}{c}\n\\DIFaddbegin \\DIFadd{x} \\DIFaddend \\\\\n\\end{tabular}\n"
    checks.append(("塊にしていない表を警告", any("PICTUREENV" in w for w in problems(raw))))
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "diff.tex")
        open(p, "w", encoding="utf-8").write(SAMPLE.replace("\\RequirePackage{color}", ""))
        checks.append(("色の package が無ければ止まる", run(p, "red", "blue", "\\medskip") == 2))
        open(p, "w", encoding="utf-8").write(SAMPLE)
        checks.append(("書き換えて 0", run(p, "red", "blue", "\\medskip") == 0 and "%DIFDELCMD" not in open(p, encoding="utf-8").read()))
    bad = [name for name, ok in checks if not ok]
    for name in bad:
        print("FAIL:", name)
    print(f"selftest: {len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("diff")
    ap.add_argument("--old-color", default="red")
    ap.add_argument("--new-color", default="blue")
    ap.add_argument("--gap", default="\\medskip")
    a = ap.parse_args(argv)
    return run(a.diff, a.old_color, a.new_color, a.gap)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
