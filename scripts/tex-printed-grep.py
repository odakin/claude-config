#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TeX の source を、 PDF に印字される部分だけで grep する。

素の grep は `%` の後ろと `\\begin{comment}` の中にも当たるので、 寝かせた文を「原稿にある」 と読む。
`grep -v '^%'` では comment 環境の中も行末の comment も落とせない。
この道具は `%` の後ろ、 `\\begin{comment}` 〜 `\\end{comment}`、 `\\iffalse` 〜 `\\fi` を外して探し、
一致を file:行番号:行 で出す。 外した所の一致は件数を最後に出す (`--hidden` で行も出す)。
本文に 0 件でも外した所の件数が見えるので、 「本文に無い」 と「寝かせてある」 を見分けられる。
`--no-keys` は `\\label` `\\ref` `\\eqref` `\\cite` などの鍵の引数を外して探す。 鍵を変えずに用語だけを置き換えたとき、
鍵の中の古い語で一致が埋まらない (鍵は印字されない)。
規則 = conventions/latex.md#commented-out-not-present。

使い方:
  python3 scripts/tex-printed-grep.py [-i] [--hidden] [--no-keys] PATTERN FILE [FILE ...]
  python3 scripts/tex-printed-grep.py --selftest

PATTERN は Python の正規表現で、 1 行ごとに当てる (文が行をまたぐ原稿では語を短くする)。
終了値: 本文に一致あり 0、 無し 1 (grep と同じ)、 引数の誤り 2。

射程外: `\\input` の展開はしない (file を全部渡す)。 `\\iffalse` の入れ子と、 `\\ifx` などの条件分岐の
どちらが印字されるかは見ない。 図の中の文字列と macro の定義の中は、 ただの source の行として扱う。
"""
import argparse
import re
import sys

VERBATIM_ENVS = ("verbatim", "Verbatim", "lstlisting", "minted")
BEGIN_VERBATIM = re.compile(r"\\begin\{(" + "|".join(VERBATIM_ENVS) + r")\}")
KEY_ARG = re.compile(r"(\\(?:label|ref|eqref|pageref|autoref|[cC]ref|[a-zA-Z]*cite[a-zA-Z]*\*?)(?:\[[^\]]*\])*\{)[^{}]*(\})")


def comment_start(line):
    """行の中で TeX の comment を始める `%` の位置 (無ければ None)。 `\\%` と `\\verb` は飛ばす。"""
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            m = re.match(r"\\verb\*?(.)", line[i:])
            if m:
                end = line.find(m.group(1), i + m.end())
                i = n if end < 0 else end + 1
                continue
            i += 2
            continue
        if ch == "%":
            return i
        i += 1
    return None


def classify(lines):
    """1 行ごとに (印字される部分, 外した部分) を返す。"""
    out = []
    in_comment_env = in_iffalse = False
    verbatim = None
    for line in lines:
        if verbatim:
            out.append((line, ""))
            if "\\end{" + verbatim + "}" in line:
                verbatim = None
            continue
        if in_comment_env:
            out.append(("", line))
            if re.match(r"\s*\\end\{comment\}", line):
                in_comment_env = False
            continue
        cut = comment_start(line)
        code = line if cut is None else line[:cut]
        tail = "" if cut is None else line[cut:]
        if in_iffalse:
            out.append(("", line))
            if re.search(r"\\fi\b", code):
                in_iffalse = False
            continue
        if re.match(r"\s*\\begin\{comment\}", code):
            in_comment_env = True
            out.append(("", line))
            continue
        if re.search(r"\\iffalse\b", code):
            if not re.search(r"\\fi\b", code):
                in_iffalse = True
            out.append(("", line))
            continue
        m = BEGIN_VERBATIM.search(code)
        if m and ("\\end{" + m.group(1) + "}") not in code:
            verbatim = m.group(1)
            out.append((line, ""))
            continue
        out.append((code, tail))
    return out


def search(path, regex, no_keys=False):
    """(印字される一致の [(行番号, 行)], 外した所の一致の [(行番号, 行)]) を返す。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    printed, hidden = [], []
    for no, (code, rest) in enumerate(classify(lines), 1):
        if no_keys:
            code, rest = KEY_ARG.sub(r"\1\2", code), KEY_ARG.sub(r"\1\2", rest)
        if code and regex.search(code):
            printed.append((no, lines[no - 1]))
        elif rest and regex.search(rest):
            hidden.append((no, lines[no - 1]))
    return printed, hidden


def selftest():
    import os
    import tempfile

    src = "\n".join([
        r"\documentclass{article}",
        r"\begin{document}",
        r"alpha printed 100\% beta % gamma trailing",
        r"% delta full comment",
        r"\begin{comment}",
        r"epsilon in comment env",
        r"\end{comment}",
        r"\iffalse",
        r"zeta in iffalse",
        r"\fi",
        r"\begin{verbatim}",
        r"eta % in verbatim",
        r"\end{verbatim}",
        r"\verb|%| theta",
        r"iota \label{lambda key}\eqref{mu key}\cite[p.~1]{nu key} xi",
        r"\end{document}",
    ])
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.tex")
    with open(p, "w", encoding="utf-8") as f:
        f.write(src)
    cases = [
        ("alpha", 1, 0), ("beta", 1, 0), ("gamma", 0, 1), ("delta", 0, 1),
        ("epsilon", 0, 1), ("zeta", 0, 1), ("eta %", 1, 0), ("theta", 1, 0),
    ]
    ok = True
    for pat, want_p, want_h in cases:
        pr, hi = search(p, re.compile(pat))
        if (len(pr), len(hi)) != (want_p, want_h):
            print(f"FAIL {pat}: printed {len(pr)} hidden {len(hi)}", file=sys.stderr)
            ok = False
    for pat, want_plain, want_no_keys in [
        ("iota", 1, 1), ("xi", 1, 1), ("lambda key", 1, 0), ("mu key", 1, 0), ("nu key", 1, 0),
    ]:
        plain, keyless = len(search(p, re.compile(pat))[0]), len(search(p, re.compile(pat), no_keys=True)[0])
        if (plain, keyless) != (want_plain, want_no_keys):
            print(f"FAIL --no-keys {pat}: plain {plain} no_keys {keyless}", file=sys.stderr)
            ok = False
    os.remove(p)
    os.rmdir(d)
    print("selftest ok" if ok else "selftest FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="TeX の印字される行だけを grep する")
    ap.add_argument("pattern", nargs="?")
    ap.add_argument("files", nargs="*")
    ap.add_argument("-i", "--ignore-case", action="store_true")
    ap.add_argument("--hidden", action="store_true", help="外した所の一致の行も出す")
    ap.add_argument("--no-keys", action="store_true", help="\\label \\ref \\cite などの鍵の引数を外して探す")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.pattern or not a.files:
        ap.print_usage(sys.stderr)
        return 2
    try:
        regex = re.compile(a.pattern, re.I if a.ignore_case else 0)
    except re.error as e:
        print(f"正規表現の誤り: {e}", file=sys.stderr)
        return 2
    n_printed = n_hidden = 0
    for path in a.files:
        try:
            printed, hidden = search(path, regex, no_keys=a.no_keys)
        except OSError as e:
            print(f"読めない: {path}: {e}", file=sys.stderr)
            return 2
        for no, line in printed:
            print(f"{path}:{no}:{line}")
        if a.hidden:
            for no, line in hidden:
                print(f"{path}:{no}:[印字されない] {line}")
        n_printed += len(printed)
        n_hidden += len(hidden)
    print(f"印字される一致 {n_printed} 件 / 外した所の一致 {n_hidden} 件", file=sys.stderr)
    return 0 if n_printed else 1


if __name__ == "__main__":
    sys.exit(main())
