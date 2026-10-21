#!/usr/bin/env python3
"""LaTeX で組んだ返答書・手紙の語数を、 自分の文と引用 (referee の文など) に分けて数える。 git の前の版との比較つき。

なぜ (実測): 返答書は「短いほどよい」 (書けば書くほど指摘が正当に見える) ので、 直すたびに語数の前後を
記録したい。 ところが本文の語数には引用した referee の文も入り、 引用は削れない。 自分の文だけを数えないと、
縮めた量が分からない。 文の長さ (scripts/tex-sentence-lengths.py) は平明さの物差しにならない
(全文が 30 語以下でも「読みづらい」 と返された実測がある) ので、 これは長さでなく量を見る道具。

使い方:
    python3 letter-word-count.py response.tex [more.tex ...] [--quote-env referee] [--git-rev HEAD~3] [--json]
    python3 letter-word-count.py --selftest

  --quote-env NAME = 引用に使っている環境 (`\\begin{NAME}…\\end{NAME}`)。 繰り返し可。 省くと全部を自分の文として数える。
  --git-rev REV = 同じ file の git の版 REV も数えて並べる (file の dir の git で `git show REV:<path>`)。

数え方 (概数): `\\begin{document}`〜`\\end{document}` の間。 `%` コメントを除き、 command 名を落として引数の中身は残す
(`\\textbf{Response.}` は 1 語)。 英数字を含む空白区切りの塊を 1 語とする。 `~` は空白。
exit: 0 = 数えた / 2 = file が無い・git の版が読めない。 stdlib だけ。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def body(tex: str) -> str:
    m = re.search(r"\\begin\{document\}(.*)\\end\{document\}", tex, re.S)
    return m.group(1) if m else tex


def strip(t: str) -> str:
    t = re.sub(r"(?<!\\)%.*", "", t)
    t = re.sub(r"\\begin\{[^}]*\}|\\end\{[^}]*\}", " ", t)
    t = re.sub(r"\\\\(\[[^\]]*\])?", " ", t)
    t = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", t)
    return re.sub(r"[{}~]", " ", t)


def words(t: str) -> int:
    return len([w for w in re.split(r"\s+", strip(t)) if re.search(r"[A-Za-z0-9]", w)])


def count(tex: str, quote_envs: list[str]) -> dict:
    b = body(tex)
    quoted = 0
    own = b
    for env in quote_envs:
        pat = re.compile(r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{" + re.escape(env) + r"\}", re.S)
        quoted += sum(words(q) for q in pat.findall(own))
        own = pat.sub(" ", own)
    return {"body": words(b), "own": words(own), "quoted": quoted}


def git_text(path: Path, rev: str) -> str | None:
    top = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode:
        return None
    rel = path.resolve().relative_to(Path(top.stdout.strip()).resolve())
    r = subprocess.run(["git", "-C", top.stdout.strip(), "show", f"{rev}:{rel.as_posix()}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def selftest() -> int:
    tex = r"""\documentclass{article}\begin{document}
% a comment that is not counted
\noindent We thank the referee.~Point~1.
\begin{referee}
Quoted words here.
\end{referee}
\textbf{Response.} Short answer (Sec.~3.1).
\end{document}"""
    c = count(tex, ["referee"])
    ok = c == {"body": 14, "own": 11, "quoted": 3}
    print("selftest:", "PASS" if ok else f"FAIL {c}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--quote-env", action="append", default=[])
    ap.add_argument("--git-rev")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    rows = []
    for f in a.files:
        if not f.is_file():
            print(f"file が無い: {f}", file=sys.stderr)
            return 2
        row = {"file": str(f), "now": count(f.read_text(encoding="utf-8"), a.quote_env)}
        if a.git_rev:
            old = git_text(f, a.git_rev)
            if old is None:
                print(f"git の版が読めない: {a.git_rev}:{f}", file=sys.stderr)
                return 2
            row["rev"] = {"rev": a.git_rev, **count(old, a.quote_env)}
        rows.append(row)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    for r in rows:
        n = r["now"]
        line = f"{r['file']}: 本文 {n['body']} 語 (自分の文 {n['own']} / 引用 {n['quoted']})"
        if "rev" in r:
            o = r["rev"]
            line += f"  ← {o['rev']}: 本文 {o['body']} (自分の文 {o['own']} / 引用 {o['quoted']})"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
