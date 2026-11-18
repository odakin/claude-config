#!/usr/bin/env python3
"""tex-new-symbols.py — 案を当てた LaTeX の写しにだけ現れる記号 (macro と添字つきの記号) を、 基準の版 (投稿版・主筆の版) と比べて数える (--selftest)。

なぜ存在するか: 改訂の原稿と返答書に referee が読んだ投稿版に無い記号を持ち込む、 共有の file への追記で主筆の版に
無い記号を使う、 のどちらも差分を目で読むと見落とす (実測)。 規約 = conventions/rebuttal-letter.md#no-new-notation、
共有の file での同じ規則 = conventions/shared-repo.md#typo-vs-calculation。

何を見るか: 案の写し (--proposal) に出てきて、 基準 (--base。 繰り返すと和集合) に一度も出てこない
  (1) macro (`\\foo`)
  (2) 添字つきの記号 (`X_{...}`・`\\alpha_{...}`)。 添字の中の空白は寄せ、 添字が 1 文字か 1 macro なら括弧を外して
      数える (`x_i`・`x_{i}`・`x_{ i }` は同じ記号)。 添字の中の括弧は 1 段まで (`X_{\\mathrm{eff}}`)。
  comment (`%` から行末。 `\\%` は comment でない) と改行の `\\\\` は両方から外す。
  --math-only = 数式の中だけを見る ($…$・$$…$$・\\(…\\)・\\[…\\] と equation / align / gather / multline / eqnarray /
  displaymath / math / flalign / alignat の環境、 * つきも)。 返答書のように地の文の macro が多い file を、
  投稿版と比べるときに使う。

使い方:
  python3 tex-new-symbols.py --base submitted.tex --proposal revised.tex [--base current.tex ...] [--proposal reply.tex ...]
                             [--math-only] [--ignore '<正規表現>' ...] [--json]
  python3 tex-new-symbols.py --selftest
  記号の基準: 改訂と返答書 = referee が読んだ投稿版。 共有の file への追記 = 主筆の版。 承認済みで入った書き方の違い
  (図の書き方・添字の付け方) まで出るときは、 今の版も --base に足す (和集合 = 「この案が足したもの」 だけが残る)。
  --ignore = 出さない記号の正規表現 (出力の字面に re.search で当てる。 例 = '^\\\\(label|ref|eqref|cite)$')。
出すもの: 記号ごとに、 案の写しで最初に出る所 (`file:行`。 行は改行だけで数える = grep・editor と同じ)。
終了値: 0 = 案だけの記号は無い / 1 = ある / 2 = 使い方の誤り・file が読めない。

限界 (目で見るもの): 正規表現の網なので、 次は拾わない。 添字の無い新しい 1 文字の記号 (投稿版に無い y を足した)・
上付きだけの記号 (`x^{(2)}`)・アクセントの付け替え (`\\tilde x` → `\\hat x` は macro の差としてだけ出る)・文の中の
新しい語・既存の記号を `\\newcommand` で別の名に包んだもの (名は出るが中身は見ない)。 書き方だけの違い
(`v_{a}` と `v^i_{a}`、 `\\rm` と `\\mathrm`) は別の記号として出る。 `\\input` / `\\include` の先は読まない
(読む file を全部 --base / --proposal に渡す)。 verbatim の中も記号として数える。 --math-only の切り出しは
`\\text{…}` の中の `$` と、 環境の入れ子を数えない。
stdlib only / 公開層 (例と試験の材料は架空の tex)。 file は変えない。 実行時間 = 1 秒未満。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MACRO = re.compile(r"\\[A-Za-z]+")
_SUB_BODY = r"(?:\{(?:[^{}]|\{[^{}]*\})*\}|\\[A-Za-z]+|[A-Za-z0-9])"
SUBSCRIPTED = re.compile(r"(\\[A-Za-z]+|[A-Za-z])\s*_\s*(" + _SUB_BODY + r")")
_SUB_TOKEN = re.compile(r"\\[A-Za-z]+|\\.|\S")
MATH_ENVS = ("equation", "align", "gather", "multline", "eqnarray", "displaymath", "math", "flalign", "alignat")
_BEGIN_ENV = re.compile(r"\\begin\{(" + "|".join(MATH_ENVS) + r")(\*?)\}")


def strip_comments(text: str) -> str:
    """Drop `%` to end of line (an escaped `\\%` is not a comment) and the `\\\\` line break; keep every newline."""
    out = []
    for line in text.split("\n"):
        i, n = 0, len(line)
        while i < n:
            c = line[i]
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == "%":
                break
            i += 1
        out.append(line[:i].replace("\\\\", "  "))
    return "\n".join(out)


def math_only(text: str) -> str:
    """Blank everything outside math (newlines kept, so line numbers stay)."""
    keep = [False] * len(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        start = end = None
        if c == "\\" and i + 1 < n:
            m = _BEGIN_ENV.match(text, i)
            if m:
                close = "\\end{" + m.group(1) + m.group(2) + "}"
                start, j = m.end(), text.find(close, m.end())
                end, nxt = (n, n) if j < 0 else (j, j + len(close))
            elif text[i + 1] in "[(":
                close = "\\]" if text[i + 1] == "[" else "\\)"
                start, j = i + 2, text.find(close, i + 2)
                end, nxt = (n, n) if j < 0 else (j, j + 2)
            else:
                i += 2
                continue
        elif c == "$":
            delim = "$$" if text.startswith("$$", i) else "$"
            start = i + len(delim)
            j = start
            while True:
                j = text.find(delim, j)
                if j < 0 or text[j - 1] != "\\":
                    break
                j += 1
            end, nxt = (n, n) if j < 0 else (j, j + len(delim))
        if start is None:
            i += 1
            continue
        for k in range(start, end):
            keep[k] = True
        i = nxt
    return "".join(ch if (keep[k] or ch == "\n") else " " for k, ch in enumerate(text))


def _sub_key(base: str, body: str) -> str:
    inner = body[1:-1] if body.startswith("{") else body
    toks = _SUB_TOKEN.findall(inner)
    parts = []
    for k, t in enumerate(toks):
        parts.append(t)
        if re.fullmatch(r"\\[A-Za-z]+", t) and k + 1 < len(toks) and toks[k + 1][:1].isalpha():
            parts.append(" ")
    joined = "".join(parts)
    return f"{base}_{joined}" if len(toks) == 1 else f"{base}_{{{joined}}}"


def symbols(text: str, only_math: bool) -> tuple[dict[str, int], dict[str, int]]:
    """({macro: first line}, {subscripted symbol: first line}) of a tex source."""
    t = strip_comments(text)
    if only_math:
        t = math_only(t)
    line_starts = [0] + [k + 1 for k, ch in enumerate(t) if ch == "\n"]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    macros: dict[str, int] = {}
    for m in MACRO.finditer(t):
        macros.setdefault(m.group(0), line_of(m.start()))
    subs: dict[str, int] = {}
    for m in SUBSCRIPTED.finditer(t):
        subs.setdefault(_sub_key(m.group(1), m.group(2)), line_of(m.start()))
    return macros, subs


def only_in(bases: list[tuple[str, str]], proposals: list[tuple[str, str]], only_math: bool,
            ignore: list[re.Pattern]) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    """Symbols in the proposals that no base has: ([(macro, file, line)], [(subscripted, file, line)])."""
    base_m: set[str] = set()
    base_s: set[str] = set()
    for _, text in bases:
        m, s = symbols(text, only_math)
        base_m |= set(m)
        base_s |= set(s)
    new_m: dict[str, tuple[str, int]] = {}
    new_s: dict[str, tuple[str, int]] = {}
    for name, text in proposals:
        m, s = symbols(text, only_math)
        for sym, line in m.items():
            if sym not in base_m:
                new_m.setdefault(sym, (name, line))
        for sym, line in s.items():
            if sym not in base_s:
                new_s.setdefault(sym, (name, line))

    def keep(sym: str) -> bool:
        return not any(p.search(sym) for p in ignore)

    return ([(k, *v) for k, v in sorted(new_m.items()) if keep(k)],
            [(k, *v) for k, v in sorted(new_s.items()) if keep(k)])


def selftest() -> int:
    fails: list[str] = []

    def check(label: str, got, want) -> None:
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    def run(base, prop, only_math=False, ignore=()):
        bases = [(f"b{i}.tex", b) for i, b in enumerate([base] if isinstance(base, str) else base)]
        m, s = only_in(bases, [("p.tex", prop)], only_math, [re.compile(p) for p in ignore])
        return [x[0] for x in m], [x[0] for x in s]

    base = r"$\int_0^T f(t)\,dt$ and $x$"
    check("new macro and new subscripted symbol", run(base, base + "\n" + r"$F_T$ and $\xi$"), ([r"\xi"], ["F_T"]))
    check("same file", run(base, base), ([], []))
    check("comment is not a symbol", run(base, base + r" % \commentmacro y_{k}"), ([], []))
    check("escaped percent is not a comment", run(r"50\% of $y$", r"50\% of $y$ and $\zeta$"), ([r"\zeta"], []))
    check("subscript forms are one symbol", run(r"$x_{i}$ and $\sigma_{\rm tot}$", r"$x_i$, $x_{ i }$, $\sigma_{\rm  tot}$"),
          ([], []))
    check("nested braces in a subscript", run("$X$", r"$X_{\mathrm{eff}}$"), ([r"\mathrm"], [r"X_{\mathrm{eff}}"]))
    check("macro subscript", run("$x$", r"$x_\mu$"), ([r"\mu"], [r"x_\mu"]))
    check("line break is not a macro", run("a", r"a \\beta"), ([], []))
    check("union of bases", run([r"$\alpha$", r"$\gamma$"], r"$\alpha + \gamma$"), ([], []))
    check("whole text sees text macros", run("$a$", r"$a$ \textbf{b} $\beta_{k}$"), ([r"\beta", r"\textbf"], [r"\beta_k"]))
    check("math only drops text macros", run("$a$", r"$a$ \textbf{b} $\beta_{k}$", only_math=True), ([r"\beta"], [r"\beta_k"]))
    check("math only sees environments", run("$a$", "text y_{n}\n\\begin{align*} z_{n} \\end{align*}", only_math=True),
          ([], ["z_n"]))
    check("math only, escaped dollar", run("$a$", r"costs \$5 and $\delta$", only_math=True), ([r"\delta"], []))
    check("ignore pattern", run("$a$", r"$a$ \label{e1}", ignore=[r"^\\label$"]), ([], []))
    # line numbers count newlines only (a form feed must not add a line, conventions/shell-multibyte-truncation.md)
    m, _ = only_in([("b.tex", "a")], [("p.tex", "a\n\x0cb\n$\\eta$")], False, [])
    check("line counts newlines only", m, [(r"\eta", "p.tex", 3)])
    if fails:
        print("selftest FAILED")
        for f in fails:
            print("  " + f)
        return 1
    print("selftest OK (15 cases)")
    return 0


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", action="append", default=[], help="記号の基準の tex (繰り返すと和集合)")
    ap.add_argument("--proposal", action="append", default=[], help="案を当てた写しの tex (繰り返せる)")
    ap.add_argument("--math-only", action="store_true", help="数式の中だけを見る")
    ap.add_argument("--ignore", action="append", default=[], help="出さない記号の正規表現")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.base or not a.proposal:
        ap.print_usage(sys.stderr)
        print("--base と --proposal を 1 つ以上渡す", file=sys.stderr)
        return 2
    try:
        bases = [(p, _read(p)) for p in a.base]
        props = [(p, _read(p)) for p in a.proposal]
        ignore = [re.compile(p) for p in a.ignore]
    except (OSError, re.error) as e:
        print(f"読めない: {e}", file=sys.stderr)
        return 2
    macros, subs = only_in(bases, props, a.math_only, ignore)
    if a.json:
        print(json.dumps({"base": a.base, "proposal": a.proposal, "math_only": a.math_only,
                          "macros": [{"symbol": s, "file": f, "line": n} for s, f, n in macros],
                          "subscripted": [{"symbol": s, "file": f, "line": n} for s, f, n in subs]},
                         ensure_ascii=False, indent=1))
    else:
        print(f"基準: {' + '.join(a.base)} / 案: {' + '.join(a.proposal)} / 範囲: {'数式の中だけ' if a.math_only else '全文'}")
        if not macros and not subs:
            print("案だけの記号は無い (macro 0・添字つきの記号 0)。 添字の無い 1 文字・上付きだけの記号・文の語は目で見る")
        for title, rows in (("案だけの macro", macros), ("案だけの添字つきの記号", subs)):
            if rows:
                print(f"{title}: {len(rows)}")
                width = max(len(s) for s, _, _ in rows)
                for s, f, n in rows:
                    print(f"  {s.ljust(width)}  {f}:{n}")
    return 1 if (macros or subs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
