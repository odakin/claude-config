#!/usr/bin/env python3
"""md の表の列数を点呼する (code fence の外だけ)。

md の表の中の `|x|` (絶対値の棒) は列の区切りになる。 列が header より多い行は、 GFM では余りの列が
黙って捨てられ、 表の中身が消える。 式の多いノートで起きやすく、 書いた本人の editor では気づきにくい。
行の先頭が `|` というだけで表と見なす置換は、 code fence の中の式まで書き換える (実測) ので、
ここでは fence を追い、 header と区切りの行の組で表を見つけてから数える。

使い方:
  python3 scripts/check-md-tables.py FILE.md [...]        列数が header と違う行を出す (あれば exit 1)
  python3 scripts/check-md-tables.py --fix FILE.md [...]  列が多い行の `|x|` の形を `\\|x\\|` に直す
  python3 scripts/check-md-tables.py --selftest

--fix が触るのは列が多すぎる行だけで、 棒の内側に空白が無い組 (`|x|`) を左から直し、 列数が合った所で止める。
合わなければその行は元のまま報告に残す (どの棒が区切りかは機械に決められない = 手で直す)。
"""
import re
import sys

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
DELIM = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def pipes(line):
    """escape されていない `|` の位置。"""
    return [i for i, c in enumerate(line) if c == "|" and (i == 0 or line[i - 1] != "\\")]


def columns(line):
    """行の列数 (先頭と末尾の棒は区切りでなく枠)。"""
    s = line.strip()
    n = len(pipes(s)) + 1
    if s.startswith("|"):
        n -= 1
    if s.endswith("|") and not s.endswith("\\|"):
        n -= 1
    return n


def tables(lines):
    """(行番号 0 起点, header の列数) を本体の行ごとに返す。 header と区切りの行も数える。"""
    fence = None
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):]:
                fence = None
            i += 1
            continue
        if m:
            fence = m.group(1)
            i += 1
            continue
        if i + 1 < len(lines) and "|" in line and "|" in lines[i + 1] and DELIM.match(lines[i + 1]):
            cols = columns(lines[i + 1])
            out.append((i, cols))
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                out.append((i, cols))
                i += 1
            continue
        i += 1
    return out


def fix_row(line, cols):
    """列が多い行の `|x|` を左から escape する。 合わなければ None。"""
    if columns(line) <= cols:
        return None
    s = line
    while columns(s) > cols:
        ps = pipes(s)
        for a, b in zip(ps, ps[1:]):
            if a + 1 == b:
                continue
            if not s[a + 1].isspace() and not s[b - 1].isspace() and (a > 0 and s[:a].strip()):
                s = s[:a] + "\\|" + s[a + 1:b] + "\\|" + s[b + 1:]
                break
        else:
            return None
    return s if columns(s) == cols else None


def check(text, fix=False):
    lines = text.split("\n")
    bad = []
    for i, cols in tables(lines):
        if columns(lines[i]) != cols:
            new = fix_row(lines[i], cols) if fix else None
            if new is None:
                bad.append((i + 1, columns(lines[i]), cols, lines[i]))
            else:
                lines[i] = new
    return "\n".join(lines), bad


def selftest():
    src = "\n".join([
        "| a | b |",
        "|---|---|",
        "| |x| ≪ 1 | 2 |",
        "| 3 | \\|y\\| |",
        "|p|q|",
        "",
        "```",
        "|z|²/|w|² = 1",
        "| not | a | table |",
        "|---|---|---|",
        "| one | two |",
        "```",
        "",
        "text |x| outside",
    ])
    out, bad = check(src)
    assert [b[0] for b in bad] == [3], bad
    fixed, bad = check(src, fix=True)
    assert not bad, bad
    assert "| \\|x\\| ≪ 1 | 2 |" in fixed, fixed
    assert "|z|²/|w|² = 1" in fixed and "text |x| outside" in fixed, fixed  # fence の中と地の文は触らない
    assert "|p|q|" in fixed  # 列数の合う詰めた行は触らない
    assert check(fixed, fix=True)[0] == fixed  # 2 回当てても変わらない
    # 空白の入った棒は機械に決められない = 残す
    amb = "| a | b |\n|---|---|\n| 1 | 2 | 3 |\n"
    assert check(amb, fix=True)[1] and check(amb, fix=True)[0] == amb
    # 長い fence の中の短い fence は閉じない
    nest = "````\n```\n| a | b |\n|---|---|\n| |x| | 2 |\n```\n````\n"
    assert not check(nest)[1]
    print("selftest ok")


def main(argv):
    if "--selftest" in argv:
        selftest()
        return 0
    fix = "--fix" in argv
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    rc = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        new, bad = check(text, fix=fix)
        if fix and new != text:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            print(f"{f}: 直した")
        for n, got, want, line in bad:
            rc = 1
            print(f"{f}:{n}: 列 {got}、 header は {want}: {line[:100]}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
