#!/usr/bin/env python3
"""LaTeX で組んだ返答書・手紙の語数を、 自分の文と引用 (referee の文など) に分けて数える。 git の前の版との比較つき。

なぜ (実測): 返答書は「短いほどよい」 (書けば書くほど指摘が正当に見える) ので、 直すたびに語数の前後を
記録したい。 ところが本文の語数には引用した referee の文も入り、 引用は削れない。 自分の文だけを数えないと、
縮めた量が分からない。 文の長さ (scripts/tex-sentence-lengths.py) は平明さの物差しにならない
(全文が 30 語以下でも「読みづらい」 と返された実測がある) ので、 これは長さでなく量を見る道具。

使い方:
    python3 letter-word-count.py response.tex [more.tex ...] [--quote-env referee] [--git-rev HEAD~3] [--json]
    python3 letter-word-count.py reply.tex --part-macro A --quote-macro R --quote-env quote
    python3 letter-word-count.py --selftest

  --quote-env NAME = 引用に使っている環境 (`\\begin{NAME}…\\end{NAME}`)。 繰り返し可。 省くと全部を自分の文として数える。
  --part-macro NAME = 本文をこの macro (`\\NAME`) の所で部分に分け、 部分ごとの語数も出す (返答書の答えの `\\A` など)。 繰り返し可。
  --quote-macro NAME = この macro で始まる部分を丸ごと引用として数える (referee の文を `\\R` のような macro の後に
      置く雛形 = 環境で囲まないので --quote-env では分けられない)。 繰り返し可、 --part-macro も兼ねる。
      部分は次の part / quote の macro か、 `\\end{itemize|enumerate|description}` で終わる (その後の結びは「後」 の部分)。
  --git-rev REV = 同じ file の git の版 REV も数えて並べる (file の dir の git で `git show REV:<path>`)。

なぜ --quote-macro (実測): referee の文を `\\R` (= `\\item[R:]` の macro) の後に書く雛形の返答書では、 --quote-env だけだと
referee の文が自分の文に数えられ、 自分の文の語数が referee の文の分だけ多く出た。

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


def split_envs(t: str, quote_envs: list[str]) -> tuple[int, int]:
    """(引用の環境の外の語数, 環境の中の語数)。"""
    quoted = 0
    own = t
    for env in quote_envs:
        pat = re.compile(r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{" + re.escape(env) + r"\}", re.S)
        quoted += sum(words(q) for q in pat.findall(own))
        own = pat.sub(" ", own)
    return words(own), quoted


def parts(b: str, part_macros: list[str], quote_macros: list[str]) -> list[tuple[str, str, str]]:
    """本文を macro の所で分けた (ラベル, macro 名か ''、 中身) の列。 最初の macro の前は「前置き」、 list の終わりの後は「後」。"""
    names = sorted(set(part_macros) | set(quote_macros), key=len, reverse=True)
    pat = re.compile(r"\\(" + "|".join(map(re.escape, names)) + r")(?![A-Za-z])"
                     r"|\\end\{(?:itemize|enumerate|description)\}")
    out, label, name, start, seen = [], "前置き", "", 0, {}
    for m in pat.finditer(b):
        out.append((label, name, b[start:m.start()]))
        if m.group(1):
            name = m.group(1)
            seen[name] = seen.get(name, 0) + 1
            label = f"{name}#{seen[name]}"
        else:
            label, name = "後", ""
        start = m.end()
    out.append((label, name, b[start:]))
    return [p for p in out if words(p[2]) or p[1]]


def count(tex: str, quote_envs: list[str], part_macros: list[str] | None = None,
          quote_macros: list[str] | None = None) -> dict:
    b = re.sub(r"(?<!\\)%.*", "", body(tex))
    part_macros, quote_macros = part_macros or [], quote_macros or []
    if not part_macros and not quote_macros:
        own, quoted = split_envs(b, quote_envs)
        return {"body": words(b), "own": own, "quoted": quoted}
    rows, own_t, quoted_t = [], 0, 0
    for label, name, text in parts(b, part_macros, quote_macros):
        if name in quote_macros:
            own, quoted = 0, words(text)
        else:
            own, quoted = split_envs(text, quote_envs)
        rows.append({"part": label, "own": own, "quoted": quoted, "quote_macro": name in quote_macros})
        own_t += own
        quoted_t += quoted
    return {"body": words(b), "own": own_t, "quoted": quoted_t, "parts": rows}


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
    print("selftest (引用の環境):", "PASS" if ok else f"FAIL {c}")
    # referee の文を \R の後に置く雛形 (環境で囲まない)。 % の中の \A は分けない。 \Alpha は \A と取り違えない。
    tex2 = r"""\documentclass{article}\begin{document}
Dear Editor, we reply below.
\begin{itemize}
\R1) The referee asks a question here.
\A We answer briefly. % \A in a comment
\begin{quote} Quoted manuscript text. \end{quote}
\R2) Another question $\Alpha$.
\A Second answer.
\end{itemize}
Sincerely yours.
\end{document}"""
    c2 = count(tex2, ["quote"], ["A"], ["R"])
    got = [(p["part"], p["own"], p["quoted"]) for p in c2["parts"]]
    # R#2 の $\Alpha$ は command なので語に数えない (3 語)。 \A で割ると A の部分が 1 つ増えて落ちる。
    want = [("前置き", 5, 0), ("R#1", 0, 7), ("A#1", 3, 3), ("R#2", 0, 3), ("A#2", 2, 0), ("後", 2, 0)]
    ok2 = got == want and (c2["body"], c2["own"], c2["quoted"]) == (25, 12, 13)
    print("selftest (macro で始まる引用):", "PASS" if ok2 else f"FAIL {got} {c2['body'], c2['own'], c2['quoted']}")
    return 0 if ok and ok2 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--quote-env", action="append", default=[])
    ap.add_argument("--part-macro", action="append", default=[])
    ap.add_argument("--quote-macro", action="append", default=[])
    ap.add_argument("--git-rev")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    cnt = lambda t: count(t, a.quote_env, a.part_macro, a.quote_macro)
    rows = []
    for f in a.files:
        if not f.is_file():
            print(f"file が無い: {f}", file=sys.stderr)
            return 2
        row = {"file": str(f), "now": cnt(f.read_text(encoding="utf-8"))}
        if a.git_rev:
            old = git_text(f, a.git_rev)
            if old is None:
                print(f"git の版が読めない: {a.git_rev}:{f}", file=sys.stderr)
                return 2
            row["rev"] = {"rev": a.git_rev, **cnt(old)}
        rows.append(row)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    fmt_parts = lambda c: " / ".join(
        f"{p['part']} 引用 {p['quoted']}" if p["quote_macro"]
        else f"{p['part']} {p['own']}" + (f" (+引用 {p['quoted']})" if p["quoted"] else "")
        for p in c["parts"])
    for r in rows:
        n = r["now"]
        line = f"{r['file']}: 本文 {n['body']} 語 (自分の文 {n['own']} / 引用 {n['quoted']})"
        if "rev" in r:
            o = r["rev"]
            line += f"  ← {o['rev']}: 本文 {o['body']} (自分の文 {o['own']} / 引用 {o['quoted']})"
        print(line)
        if "parts" in n:
            print("  部分: " + fmt_parts(n))
            if "rev" in r:
                print(f"  部分 ({r['rev']['rev']}): " + fmt_parts(r["rev"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
