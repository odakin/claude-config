#!/usr/bin/env python3
"""Markdown のノートを、 手元の TeX preamble に載る骨格 (raw/) へ機械で変える (正本が md、 TeX が写しのときの写し作りの前半。 構造だけ)。

pandoc に構造 (見出し・表・箇条書き・リンク) を任せ、後処理で TeX 側の仕掛けに寄せる。
数式の Unicode 表記 (P₁、α ≥ 1、|n⟩ など) はここでは触らない。そこは人 (または
別 context の worker) が節ごとに直し、check-md-tex-copy.py で
日本語の文と数字が md と一致することを確かめる。
考え方と手順 = conventions/latex.md#md-tex-source-and-copy

使い方:
  md-note-to-tex.py NOTE.md OUTDIR
    OUTDIR/raw/sec-head.tex (章見出しと前書き) と OUTDIR/raw/sec-NN.tex (節ごと) を書く。
    見出しの手書きの番号が自動の番号と合わなければ ⚠️ を出して exit 1。

md 側の約束: 章 = `#`、節 = `## N. 題`、小節 = `### N.M 題` (節は 0 から数える)。
  anchor は見出しの直前の行に `<a id="x"></a>`。
TeX 側に要る定義: \\chk{札}、\\doi{DOI}、\\repofile{path}{text}、longtable / booktabs / array / calc。

後処理の中身:
  - `<a id="x"></a>` + 見出し → 見出しの \\label{x}
  - 見出しの手書きの番号 (「3. 」「3.1 」) を外す。自動の番号と一致するかを検査する
  - `[BS-1]` 形の検算番号 (md では code span) → \\chk{BS-1}
  - DOI のリンク → \\doi{...}、repo 内への相対リンク → \\repofile{path}{text}
"""
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    src, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    md = src.read_text(encoding="utf-8")

    # anchor 行 + 見出し → pandoc の見出し属性
    md = re.sub(r'<a id="([^"]+)"></a>\n(#+ [^\n]+)', r"\2 {#\1}", md)
    # 残った inline の anchor は \label 相当の目印にする
    md = re.sub(r'<a id="([^"]+)"></a>', r"`@@LABEL:\1@@`", md)

    tex = subprocess.run(
        ["pandoc", "-f", "markdown+tex_math_single_backslash+pipe_tables-smart-auto_identifiers",
         "-t", "latex", "--wrap=none", "--top-level-division=chapter"],
        input=md, capture_output=True, text=True, check=True).stdout

    tex = re.sub(r"\\texttt\{@@LABEL:([^@]+)@@\}", r"\\label{\1}", tex)
    # 検算番号
    tex = re.sub(r"\\texttt\{\{\[\}([A-Za-z0-9-]+)\{\]\}\}", r"\\chk{\1}", tex)
    # DOI と相対リンク
    tex = re.sub(r"\\href\{https://doi\.org/([^}]+)\}\{[^}]*\}", r"\\doi{\1}", tex)
    tex = re.sub(r"\\href\{(?!https?:)([^}]+)\}\{", r"\\repofile{\1}{", tex)
    # pandoc の飾り
    tex = tex.replace("\\tightlist\n", "")
    # 表の飾り (見出し cell の minipage、caption 用の group) を外す
    tex = re.sub(r"\\begin\{minipage\}\[b\]\{\\linewidth\}\\raggedright\n(.*?)\n\\end\{minipage\}", r"\1", tex, flags=re.S)
    tex = tex.replace("{\\def\\LTcaptype{none} % do not increment counter\n", "")
    tex = tex.replace("\\end{longtable}\n}", "\\end{longtable}")
    tex = re.sub(r"\\def\\labelenumi\{\\arabic\{enumi\}\.\}\n", "", tex)

    # 見出し: 手書きの番号を外し、自動の番号と突き合わせる
    sec = sub = -1
    out_lines = []
    problems = []
    for line in tex.split("\n"):
        m = re.match(r"\\(section|subsection)\{(.*)\}\\label\{([^}]+)\}$", line) or \
            re.match(r"\\(section|subsection)\{(.*)\}$", line)
        if m:
            kind, title = m.group(1), m.group(2)
            label = m.group(3) if m.lastindex == 3 else None
            if kind == "section":
                sec, sub = sec + 1, 0
                n = re.match(r"(\d+)\. (.*)", title)
                if not n or int(n.group(1)) != sec:
                    problems.append(f"section 番号が合わない: {title!r} (自動 {sec})")
                title = n.group(2) if n else title
            else:
                sub += 1
                n = re.match(r"(\d+)\.(\d+) (.*)", title)
                if not n or (int(n.group(1)), int(n.group(2))) != (sec, sub):
                    problems.append(f"subsection 番号が合わない: {title!r} (自動 {sec}.{sub})")
                title = n.group(3) if n else title
            line = f"\\{kind}{{{title}}}" + (f"\\label{{{label}}}" if label else "")
        out_lines.append(line)
    tex = "\n".join(out_lines)

    # 節ごとに分ける (章見出しと前書きは sec-head)
    parts = re.split(r"(?=^\\section\{)", tex, flags=re.M)
    raw = outdir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "sec-head.tex").write_text(parts[0], encoding="utf-8")
    for i, p in enumerate(parts[1:]):
        (raw / f"sec-{i:02d}.tex").write_text(p, encoding="utf-8")
    for p in problems:
        print("⚠️", p)
    print(f"{len(parts) - 1} 節を {raw} に書いた")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
