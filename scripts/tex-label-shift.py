#!/usr/bin/env python3
"""LaTeX 原稿の 2 つの版 (git の commit) を別 dir で組み、 式・節・図表・文献の番号がどう動いたかを .aux から出す。

なぜ (実測): 改訂版に返答書を書くと、 文中の式・節・文献の番号を「改訂版のもの」 と断る 1 文が要る。
その 1 文は「何がずれたか」 だけを言うべきで (例: 式番号は N 番以降が 1 大きい、 節と文献は同じ)、
それを言い切るには両方の版を組んで全 label を突き合わせるしかない。 投稿版の PDF が手元に無いときも、
git に投稿版の commit があれば組み直せる。 手で .aux を眺めると、 ずれた範囲・ずれていない種類の
どちらかを見落とす。

使い方:
    python3 tex-label-shift.py --repo <原稿の git dir> --old <commit> [--new <commit>] [--main paper.tex]
                               [--label KEY ...] [--json]
    python3 tex-label-shift.py --selftest

  --new を省くと作業木 (未 commit の変更を含む) を組む。
  --label KEY = その label の番号を旧 → 新で出す (返答書が引く式など、 繰り返し可)。

出すもの:
  - 各版の頁数と LaTeX の error の数 (.log から)
  - 節・付録・図・表などの式以外の label で番号が変わったもの (無ければ「全部同じ」)
  - 式の label: 番号が同じ数・ずれた数・ずれ幅ごとの範囲 (旧の番号で) ・ 新しく足された label・消えた label
  - 文献: 本数・並びが同じか・番号が変わった key
  式かどうかは hyperref の anchor (\\newlabel の 4 つ目の欄が equation.…) で決め、 anchor が無ければ key の頭 (eq) で決める。
  cleveref の `@cref` の label は数えない。

組み方: git archive で一時 dir に展開し、 pdflatex → (bib があれば) bibtex → pdflatex × 2。 図・bst など git にある file は
そのまま入る。 git に無い file (手元だけの図) が要る原稿は組めない = error の数で分かる。
exit: 0 = 比べた / 1 = どちらかの版が組めなかった (.aux が無い) / 2 = 引数・git の誤り。
stdlib だけ (pdflatex・bibtex・git は PATH から)。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path

NEWLABEL = re.compile(r"\\newlabel\{([^}]*)\}\{\{([^}]*)\}\{([^}]*)\}(?:\{([^}]*)\}\{([^}]*)\})?")
BIBCITE = re.compile(r"\\bibcite\{([^}]*)\}\{([^}]*)\}")


def parse_aux(text: str) -> tuple[dict[str, dict], dict[str, str]]:
    """\\newlabel と \\bibcite を読む。 label = {key: {num, page, anchor}}、 bib = {key: num}。"""
    labels: dict[str, dict] = {}
    for m in NEWLABEL.finditer(text):
        key = m.group(1)
        if key.endswith("@cref"):
            continue
        labels[key] = {"num": m.group(2), "page": m.group(3), "anchor": m.group(5) or ""}
    bib = {m.group(1): m.group(2) for m in BIBCITE.finditer(text)}
    return labels, bib


def is_equation(key: str, info: dict) -> bool:
    if info.get("anchor"):
        return info["anchor"].startswith(("equation.", "AMS."))
    return key.lower().startswith("eq")


def compare(old: tuple[dict, dict], new: tuple[dict, dict]) -> dict:
    (lo, bo), (ln, bn) = old, new
    out: dict = {"other_changed": [], "eq_same": 0, "eq_shift": {}, "only_new": [], "only_old": []}
    shifts: dict[str, list[str]] = defaultdict(list)
    for key, info in lo.items():
        if key not in ln:
            out["only_old"].append((key, info["num"]))
            continue
        a, b = info["num"], ln[key]["num"]
        if is_equation(key, info):
            if a == b:
                out["eq_same"] += 1
            elif a.isdigit() and b.isdigit():
                shifts[f"{int(b) - int(a):+d}"].append(a)
            else:
                out["other_changed"].append((key, a, b))
        elif a != b:
            out["other_changed"].append((key, a, b))
    for delta, nums in shifts.items():
        ints = sorted(int(x) for x in nums)
        out["eq_shift"][delta] = {"count": len(ints), "from": ints[0], "to": ints[-1]}
    out["only_new"] = sorted((k, v["num"]) for k, v in ln.items() if k not in lo)
    out["bib"] = {
        "old": len(bo), "new": len(bn),
        "same_order": sorted(bo, key=lambda k: int(bo[k]) if bo[k].isdigit() else 0)
        == sorted(bn, key=lambda k: int(bn[k]) if bn[k].isdigit() else 0),
        "changed": sorted((k, bo[k], bn[k]) for k in bo if k in bn and bo[k] != bn[k]),
    }
    return out


def run_quiet(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build(repo: Path, rev: str | None, main: str, tmp: Path) -> dict:
    """rev = None は作業木。 一時 dir に展開して組み、 aux・頁数・error を返す。"""
    dest = tmp / (rev or "worktree")
    dest.mkdir(parents=True)
    if rev is None:
        files = subprocess.run(["git", "-C", str(repo), "ls-files", "-co", "--exclude-standard"],
                               capture_output=True, text=True, check=True).stdout.split("\n")
        for f in filter(None, files):
            src = repo / f
            if src.is_file():
                (dest / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / f)
    else:
        arch = tmp / f"{rev}.tar"
        subprocess.run(["git", "-C", str(repo), "archive", "-o", str(arch), rev], check=True)
        with tarfile.open(arch) as t:
            t.extractall(dest)
    stem = Path(main).stem
    run_quiet(["pdflatex", "-interaction=nonstopmode", main], dest)
    aux = dest / f"{stem}.aux"
    if aux.exists() and re.search(r"\\bibdata\{", aux.read_text(errors="replace")):
        run_quiet(["bibtex", stem], dest)
    run_quiet(["pdflatex", "-interaction=nonstopmode", main], dest)
    run_quiet(["pdflatex", "-interaction=nonstopmode", main], dest)
    log = (dest / f"{stem}.log").read_text(errors="replace") if (dest / f"{stem}.log").exists() else ""
    pages = re.search(r"Output written on .*?\((\d+) pages?", log)
    return {
        "aux": aux.read_text(errors="replace") if aux.exists() else None,
        "pages": int(pages.group(1)) if pages else None,
        "errors": len(re.findall(r"^!", log, re.M)),
    }


def report(old_rev: str, new_rev: str, bo: dict, bn: dict, cmp: dict, labels: list[str],
           lo: dict, ln: dict) -> list[str]:
    lines = [f"旧 {old_rev}: {bo['pages']} 頁, errors={bo['errors']} / 新 {new_rev}: {bn['pages']} 頁, errors={bn['errors']}"]
    if cmp["other_changed"]:
        lines.append("式以外の label で番号が変わったもの:")
        lines += [f"  {k}: {a} → {b}" for k, a, b in cmp["other_changed"]]
    else:
        lines.append("式以外の label (節・付録・図・表など): 番号は全部同じ")
    lines.append(f"式の label: 番号が同じ {cmp['eq_same']}")
    for delta, s in sorted(cmp["eq_shift"].items()):
        lines.append(f"  ずれ {delta}: {s['count']} 個 (旧の ({s['from']})〜({s['to']}))")
    if cmp["only_new"]:
        lines.append("新しく足された label: " + ", ".join(f"{k}=({v})" for k, v in cmp["only_new"]))
    if cmp["only_old"]:
        lines.append("消えた label: " + ", ".join(f"{k}=({v})" for k, v in cmp["only_old"]))
    b = cmp["bib"]
    lines.append(f"文献: {b['old']} → {b['new']} 本, 並び{'は同じ' if b['same_order'] else 'が違う'}"
                 + (", 番号が変わった key: " + ", ".join(f"{k} [{x}]→[{y}]" for k, x, y in b["changed"]) if b["changed"] else ""))
    for key in labels:
        lines.append(f"  {key}: {lo.get(key, {}).get('num', '?')} → {ln.get(key, {}).get('num', '?')}")
    return lines


def selftest() -> int:
    old = r"""\newlabel{sec:a}{{2.1}{3}{A}{subsection.2.1}{}}
\newlabel{eq:x}{{42}{10}{}{equation.4.42}{}}
\newlabel{eq:y}{{43}{11}{}{equation.4.43}{}}
\newlabel{eq:y@cref}{{[equation][43][]43}{11}}
\newlabel{tab:t}{{1}{30}{}{table.1}{}}
\bibcite{A}{1}
\bibcite{B}{2}
"""
    new = r"""\newlabel{sec:a}{{2.1}{3}{A}{subsection.2.1}{}}
\newlabel{eq:x}{{42}{10}{}{equation.4.42}{}}
\newlabel{eq:new}{{43}{10}{}{equation.4.43}{}}
\newlabel{eq:y}{{44}{11}{}{equation.4.44}{}}
\newlabel{tab:t}{{1}{30}{}{table.1}{}}
\bibcite{A}{1}
\bibcite{B}{2}
"""
    cmp = compare(parse_aux(old), parse_aux(new))
    ok = (cmp["eq_same"] == 1 and cmp["eq_shift"] == {"+1": {"count": 1, "from": 43, "to": 43}}
          and cmp["other_changed"] == [] and cmp["only_new"] == [("eq:new", "43")]
          and cmp["bib"]["same_order"] and not cmp["bib"]["changed"])
    plain = parse_aux(r"\newlabel{eqA}{{3}{1}}" + "\n" + r"\newlabel{secB}{{2}{1}}")[0]
    ok = ok and is_equation("eqA", plain["eqA"]) and not is_equation("secB", plain["secB"])
    print("selftest:", "PASS" if ok else f"FAIL {cmp}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--old")
    ap.add_argument("--new", help="省くと作業木")
    ap.add_argument("--main", default="paper.tex")
    ap.add_argument("--label", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.repo or not a.old:
        ap.error("--repo と --old が要る")
    for tool in ("git", "pdflatex"):
        if not shutil.which(tool):
            print(f"{tool} が PATH に無い", file=sys.stderr)
            return 2
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        try:
            bo = build(a.repo, a.old, a.main, tmp)
            bn = build(a.repo, a.new, a.main, tmp)
        except subprocess.CalledProcessError as e:
            print(f"git の誤り: {e}", file=sys.stderr)
            return 2
    if bo["aux"] is None or bn["aux"] is None:
        print("組めなかった版がある (.aux が無い)", file=sys.stderr)
        return 1
    po, pn = parse_aux(bo["aux"]), parse_aux(bn["aux"])
    cmp = compare(po, pn)
    if a.json:
        print(json.dumps({"old": {k: bo[k] for k in ("pages", "errors")},
                          "new": {k: bn[k] for k in ("pages", "errors")}, **cmp}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(report(a.old, a.new or "作業木", bo, bn, cmp, a.label, po[0], pn[0])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
