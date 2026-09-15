#!/usr/bin/env python3
"""explain-sensitive-hits.py — 実名 gate (Tier B) の finding を「どの種類の term が・どの行で」 当たったかに分解する (手元で判断する道具)。

正本: claude-config/scripts/explain-sensitive-hits.py
規律: conventions/confidential-repo-boundary.md#tree-finding-resolution

Why: Tier B は漏洩を増やさないために **件数と file 名しか出さない** (gate の出力は log や通知に残る)。
その代わり、 finding を決着させる人は「姓だけの短い term が地名に当たったのか / 氏名が書かれているのか」 を
自分で調べる必要があり、 毎回その場の grep を書いていた (実測)。 本 script は gate と **同じ除外**
(許可複合語・公刊済みの書誌・generated: 宣言) を当てた上で残る hit を、 term を伏せたまま種類つきで出す。

出力 (既定は term を伏せる):
  path:line  [姓2字|3字以上|ASCII]  行の本文 (term の部分を 〔姓2字〕 等に置換)
  種類の読み方:
    姓2字  … 地名・歴史上の人物名・普通語の一部なら個人層の compound_allow 候補 / 人を指すなら本文を直す
    3字以上 / ASCII … 氏名かその一部。 本文を直す (公刊済みの書誌なら構造 〔arXiv id / DOI〕 を持たせる)
  --reveal を付けると term を伏せずに出す (手元の terminal でだけ使う。 出力を記録・通知・commit に貼らない)

使い方:
  explain-sensitive-hits.py --repo DIR [--reveal]     # tracked file (text) を gate と同じ除外つきで
  explain-sensitive-hits.py --selftest
exit: 0 = 残る hit 無し / 1 = 残る hit あり / 2 = usage / 3 = 検出語 file が無い
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from published_metadata import metadata_line_numbers  # noqa: E402
from public_tree_accept import generated_files  # noqa: E402

WORD = r"[A-Za-z0-9_]"


def personal_layer() -> Path | None:
    env = os.environ.get("CLAUDE_PERSONAL_LAYER")
    if env:
        return Path(env)
    base = Path.home() / "Claude"
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if (d / ".claude-personal-layer").exists():
                return d
    return None


def load_terms(path: Path) -> tuple:
    """(ascii, non_ascii, allow) — 行の種類は lib/sensitive-terms.sh と同じ。"""
    ascii_, na, allow = [], [], []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if raw.startswith("!"):
            if raw[1:]:
                allow.append(raw[1:])
        elif all(32 <= ord(c) < 127 for c in raw):
            ascii_.append(raw)
        else:
            na.append(raw)
    return ascii_, na, allow


def classify(term: str) -> str:
    if term.isascii():
        return "ASCII"
    return "姓2字" if len(term) <= 2 else "3字以上"


def hits_in_line(line: str, ascii_, na, allow) -> list:
    for w in allow:
        line = line.replace(w, " ")
    found = []
    for t in na:
        if t in line:
            found.append(t)
    for t in ascii_:
        if re.search(rf"(?<!{WORD}){re.escape(t)}(?!{WORD})", line):
            found.append(t)
    # 長い term を含む短い term (= prefix) は長い方に吸収する
    return [t for t in found if not any(t != u and t in u for u in found)]


def mask(line: str, terms: list) -> str:
    for t in sorted(terms, key=len, reverse=True):
        line = line.replace(t, f"〔{classify(t)}〕")
    return line


def explain_repo(repo: Path, terms_file: Path, reveal=False, out=print) -> int:
    ascii_, na, allow = load_terms(terms_file)
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    if r.returncode != 0:
        out(f"✗ not a git repo: {repo}")
        return 2
    generated, problems, _ = generated_files(repo)
    for p in problems:
        out(f"  ✗ {p}")
    n = 0
    kinds = {}
    for rel in r.stdout.decode("utf-8", "replace").split("\0"):
        if not rel or rel in generated or rel == ".claude/public-tree-accept.txt":
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        skip = metadata_line_numbers(rel, text)
        for i, line in enumerate(text.split("\n"), 1):
            if i in skip:
                continue
            terms = hits_in_line(line, ascii_, na, allow)
            if not terms:
                continue
            n += 1
            ks = sorted({classify(t) for t in terms})
            for k in ks:
                kinds[k] = kinds.get(k, 0) + 1
            shown = line if reveal else mask(line, terms)
            out(f"{rel}:{i}  [{'|'.join(ks)}]  {shown.strip()[:180]}")
    if n:
        summary = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
        out(f"✗ [explain-sensitive-hits] {repo.name}: 除外後に {n} 行 ({summary})。 "
            f"姓2字だけの行 = 人でなければ compound_allow 候補 / それ以外 = 本文を直す")
        return 1
    out(f"ok [explain-sensitive-hits] {repo.name}: 除外後に残る hit は無い")
    return 0


def selftest() -> int:
    fails = 0

    def expect(name, cond):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name)
        fails += 0 if cond else 1

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        terms = td / "terms.txt"
        terms.write_text("# c\n甲野\n甲野太郎\nJane Roe\n!甲野町\n")
        repo = td / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "map.txt").write_text("// 甲野町西部\n// 甲野さんと\n")
        (repo / "notes.md").write_text("甲野太郎 が書いた\n- [Jane Roe paper](https://arxiv.org/abs/2609.00001)\nby Jane Roe\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        lines = []
        rc = explain_repo(repo, terms, out=lines.append)
        body = "\n".join(lines)
        expect("allowed compound line is not reported", "map.txt:1" not in body)
        expect("bare surname is reported as 姓2字", "map.txt:2  [姓2字]" in body)
        expect("full name absorbs its prefix (reported as 3字以上 only)", "notes.md:1  [3字以上]" in body)
        expect("published-link-only md line is excluded", "notes.md:2" not in body)
        expect("ASCII name in prose is reported", "notes.md:3  [ASCII]" in body)
        expect("default output masks the term", "甲野" not in body.replace("甲野町", "") and "Jane Roe" not in body)
        expect("rc 1 when hits remain", rc == 1)
        lines2 = []
        explain_repo(repo, terms, reveal=True, out=lines2.append)
        expect("--reveal shows the term", any("甲野さん" in l for l in lines2))
    print(f"explain-sensitive-hits selftest: {'OK' if fails == 0 else f'{fails} FAIL'}")
    return 1 if fails else 0


def main(argv: list) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--repo" not in argv or argv.index("--repo") + 1 >= len(argv):
        print(__doc__, file=sys.stderr)
        return 2
    repo = Path(argv[argv.index("--repo") + 1]).expanduser().resolve()
    layer = personal_layer()
    terms = layer / "sensitive-terms.txt" if layer else None
    if not terms or not terms.is_file():
        print("✗ sensitive-terms.txt が見つからない (個人層が無い / 未生成 = build-sensitive-terms.py --write)")
        return 3
    return explain_repo(repo, terms, reveal="--reveal" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
