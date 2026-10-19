#!/usr/bin/env python3
"""本文の図・表が付録の頁に流れていないかを、 組版後の .aux で確かめる (float ごとの頁と、 付録の始まりの頁を比べる)。

なぜ (実測): `[t]` の図が本文の終わりで溜まり、 付録と文献表の後ろの最後の頁にまとめて出た。 PDF の本文から
「Fig. N」 の行を探す確かめ方は、 雑誌の class ごとに caption の書式が違い (「Fig. 1:」 / 「Fig. 1 」 / 「FIG. 1.」)、
本文の行頭の「Fig. 3 shows」 も拾う。 .aux の `\\newlabel` は float の中の `\\label` が置かれた頁を持つので、 書式に依らない。
直し方と文献表の位置 = conventions/latex.md#figures-in-body-references-last。

使い方:
    python3 latex-float-placement.py paper.tex            # 同じ dir の paper.aux を読む (latexmk の後)
    python3 latex-float-placement.py paper.tex --aux build/paper.aux [--strict]
    python3 latex-float-placement.py --selftest

判定:
  - source を `\\input` / `\\include` も開いて読み、 `%` コメントを除き、 figure / table (* つきも) の環境ごとに中の
    `\\label` を集める。 最初の `\\appendix` より前の float を「本文の float」 とする。
  - 付録の始まりの頁 = .aux の目次の行のうち、 番号が英大文字の section (`\\numberline {A}`) の最小の頁。
  - 本文の float の頁 > 付録の始まりの頁 → DRIFT (exit 1)。 同じ頁 → SAME-PAGE (付録の見出しより上か下かは .aux では
    分からない。 `--strict` で exit 1)。 `\\label` の無い float は NOLABEL (頁が分からない = 確かめていない、 と出す)。
  - 文献表 (`\\bibliography{` / `thebibliography` / `\\printbibliography`) が source で `\\appendix` の前か後ろかも出す
    (判定はしない = どちらに置くかは分野の慣例と投稿先の雛形で決まる)。
exit: 0 = DRIFT なし / 1 = DRIFT あり (--strict なら SAME-PAGE も) / 2 = 入力が無い・付録が無いのに --strict 以外の問題。
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

FLOAT_RE = re.compile(r"\\begin\{(figure|table)(\*?)\}(.*?)\\end\{\1\2\}", re.S)
LABEL_RE = re.compile(r"\\label(?:\[[^\]]*\])?\{([^}]*)\}")
NEWLABEL_RE = re.compile(r"\\newlabel\{([^}]*)\}\{\{([^}]*)\}\{([^}]*)\}")
APPTOC_RE = re.compile(r"\\contentsline \{section\}\{\\numberline \{([A-Z])\}.*?\}\{(\d+)\}\{", re.S)
BIB_RE = re.compile(r"\\bibliography\{|\\begin\{thebibliography\}|\\printbibliography")


def strip_comments(t: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*", "", l) for l in t.split("\n"))


def expand(path: Path, depth: int = 0) -> str:
    """`\\input{x}` / `\\include{x}` を中身に置き換えた source (コメントは除く)。 見つからない file はそのまま残す。"""
    t = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    if depth > 8:
        return t

    def sub(m):
        name = m.group(2).strip()
        cand = [path.parent / name, path.parent / (name + ".tex")]
        for c in cand:
            if c.is_file():
                return expand(c, depth + 1)
        return m.group(0)
    return re.sub(r"\\(input|include)\{([^}]*)\}", sub, t)


def analyze(tex: Path, aux: Path) -> dict:
    src = expand(tex)
    app = src.find("\\appendix")
    bib = BIB_RE.search(src)
    floats = []
    for m in FLOAT_RE.finditer(src):
        labels = LABEL_RE.findall(m.group(3))
        floats.append({"kind": m.group(1), "pos": m.start(), "labels": labels,
                       "body": app < 0 or m.start() < app})
    auxt = aux.read_text(encoding="utf-8", errors="replace")
    pages = {}
    for lab, num, page in NEWLABEL_RE.findall(auxt):
        if lab.endswith("@cref"):
            continue
        pages[lab] = (num, page)
    app_pages = [int(p) for _, p in APPTOC_RE.findall(auxt)]
    app_page = min(app_pages) if app_pages else None
    rows = []
    for f in floats:
        lab = next((l for l in f["labels"] if l in pages), None)
        if not f["labels"]:
            status, num, page = "NOLABEL", "?", "?"
        elif lab is None:
            status, num, page = "NOPAGE", "?", "?"
        else:
            num, page = pages[lab]
            status = "OK"
            if f["body"] and app_page is not None and page.isdigit():
                if int(page) > app_page:
                    status = "DRIFT"
                elif int(page) == app_page:
                    status = "SAME-PAGE"
        rows.append({"kind": f["kind"], "label": lab or (f["labels"][0] if f["labels"] else "-"),
                     "num": num, "page": page, "where": "本文" if f["body"] else "付録", "status": status})
    bib_where = None
    if bib:
        bib_where = "付録の後ろ" if (app >= 0 and bib.start() > app) else ("付録の前" if app >= 0 else "付録なし")
    return {"rows": rows, "appendix_page": app_page, "has_appendix": app >= 0, "bibliography": bib_where}


def selftest() -> int:
    tex = ("\\documentclass{article}\n\\begin{document}\n\\section{Intro}\n"
           "\\begin{figure}[t]\\caption{a}\\label{fig:a}\\end{figure}\n"
           "\\begin{figure}[t]\\caption{b}\\label{fig:b}\\end{figure}\n"
           "% \\begin{figure}\\label{fig:commented}\\end{figure}\n"
           "\\input{part}\n"
           "\\appendix\n\\section{Extra}\n\\begin{table}\\caption{t}\\label{tab:x}\\end{table}\n"
           "\\bibliography{refs}\n\\end{document}\n")
    part = "\\begin{figure*}\\caption{c}\\end{figure*}\n\\begin{figure}\\caption{d}\\label{fig:d}\\end{figure}\n"
    aux = ("\\newlabel{fig:a}{{1}{2}{a}{figure.1}{}}\n\\newlabel{fig:a@cref}{{[figure][1][]1}{[1][2][]2}{}{}{}}\n"
           "\\newlabel{fig:b}{{2}{9}{b}{figure.2}{}}\n\\newlabel{fig:d}{{4}{7}{d}{figure.4}{}}\n"
           "\\@writefile{toc}{\\contentsline {section}{\\numberline {1}Intro}{1}{section.1}\\protected@file@percent }\n"
           "\\@writefile{toc}{\\contentsline {section}{\\numberline {A}Extra}{7}{appendix.A}\\protected@file@percent }\n"
           "\\newlabel{tab:x}{{1}{8}{t}{table.1}{}}\n")
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "p.tex").write_text(tex, encoding="utf-8")
        (dp / "part.tex").write_text(part, encoding="utf-8")
        (dp / "p.aux").write_text(aux, encoding="utf-8")
        r = analyze(dp / "p.tex", dp / "p.aux")
    st = {row["label"]: row["status"] for row in r["rows"]}
    want = {"fig:a": "OK", "fig:b": "DRIFT", "-": "NOLABEL", "fig:d": "SAME-PAGE", "tab:x": "OK"}
    ok = st == want and r["appendix_page"] == 7 and r["bibliography"] == "付録の後ろ" and len(r["rows"]) == 5
    if not ok:
        print("FAIL", st, r["appendix_page"], r["bibliography"])
    print("selftest:", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tex", nargs="?")
    ap.add_argument("--aux")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.tex:
        ap.error("tex file を 1 つ")
    tex = Path(a.tex)
    aux = Path(a.aux) if a.aux else tex.with_suffix(".aux")
    for p in (tex, aux):
        if not p.is_file():
            print(f"{p}: file が無い (aux は組版の後にできる)", file=sys.stderr)
            return 2
    r = analyze(tex, aux)
    print(f"== {tex}: 付録の始まり = {r['appendix_page'] or '(付録なし)'} 頁 / 文献表 = {r['bibliography'] or '(見つからない)'}")
    for row in r["rows"]:
        print(f"   {row['status']:9s} {row['kind']} {row['num']:>3} p.{row['page']:>4}  {row['where']}  {row['label']}")
    bad = [x for x in r["rows"] if x["status"] == "DRIFT" or (a.strict and x["status"] == "SAME-PAGE")]
    unk = [x for x in r["rows"] if x["status"] in ("NOLABEL", "NOPAGE")]
    if unk:
        print(f"   ⚠️ 頁が分からない float {len(unk)} 件 = 確かめていない (\\label を float の中に置く)")
    if bad:
        print(f"   🔴 本文の float が付録の頁に流れた: {len(bad)} 件 → conventions/latex.md#figures-in-body-references-last")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
