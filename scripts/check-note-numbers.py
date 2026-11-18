#!/usr/bin/env python3
"""check-note-numbers.py — 記録 (note) に写した小数・百分率が、 それを出した出力に字のまま在るかを行ごとに並べる。 --selftest。

使い方:
  python3 scripts/check-note-numbers.py <note.md> --outputs <file か dir> [<file か dir> ...]
  (dir は中の *.txt / *.out / *.log / *.json / *.csv を読む。 --ext で拡張子を替える)

note の小数 (2.513 / 41.7 / 0.73 など、 小数点以下 1 桁以上) と、 その百分率を拾い、
出力のどれにも同じ字の並び (前後が数字・点でない) が無いものを、 note の行番号と行の頭つきで出す。
拾わないもの: fenced code block の中、 「§」 の直後 (節番号)、 前後が語の文字・点・slash・colon の数
(版番号 2.0.2・path・時刻)。 出力の側は字のままの一致だけを見る (丸め・表記の換算はしない)。

並んだ数は誤りとは限らない: 丸めて写した数 (出力 0.731 → note 0.73)、 本文に書いた定数、
別の道具の出力から写した数も並ぶ。 1 件ずつ、 丸め元が出力にあるか・どこから来た数かを読む。
並んだ数のうち、 丸め元の候補が「1 桁だけ多く、 最後の桁が 5」 の出力 (出力 1.2345 → note 1.235 / 1.234) には
「二重丸めの恐れ」 の印を付ける: 出力はそれ自体が表示の桁で丸めた値なので、 元の値 (1.23448) が
どちらに丸まるかは出力からは決まらない。 出力の桁を増やして出し直してから写す。
逆に、 並ばなかった数が正しい場所から来たとは限らない (同じ字の数が別の行・別の量にあっても一致になる)。
向きは締めの道具の数値照合 (scripts/lib/output_numbers.py = 出力の数が記録にあるか) の逆で、 両方を回す。
規則の正本 = conventions/scientific-computing.md#note-numbers-against-outputs。

終了値: 0 = 並ぶ数なし / 1 = 並ぶ数あり / 2 = 入力の誤り。
"""
import argparse
import os
import re
import sys
import tempfile
from decimal import Decimal

NOTE_NUM = re.compile(r"(?<![\w.:/§])(\d+\.\d+)(?![\w.:/])")
DEFAULT_EXT = (".txt", ".out", ".log", ".json", ".csv")


def note_numbers(text):
    """(line number, number string, line) for each number outside fenced code blocks."""
    out, fenced = [], False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        for m in NOTE_NUM.finditer(line):
            out.append((i, m.group(1), line))
    return out


def read_outputs(paths, exts):
    chunks = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in sorted(files):
                    if f.endswith(exts):
                        with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                            chunks.append(fh.read())
        elif os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as fh:
                chunks.append(fh.read())
        else:
            raise FileNotFoundError(p)
    return "\n".join(chunks)


def in_outputs(num, outputs):
    return re.search(r"(?<![\d.])" + re.escape(num) + r"(?![\d])", outputs) is not None


OUT_NUM = re.compile(r"(?<![\d.])(\d+\.\d+)(?![\d])")


def double_rounding_sources(num, outputs):
    """Output numbers with one more decimal ending in 5 that round to either neighbour of num.

    Such an output is itself rounded for display, so the value behind it may round to num
    or to the next number at num's precision; num cannot be trusted without more digits.
    """
    d = len(num.split(".")[1])
    ulp = Decimal(1).scaleb(-d)
    n = Decimal(num)
    hits = []
    for m in OUT_NUM.finditer(outputs):
        x = m.group(1)
        frac = x.split(".")[1]
        if len(frac) != d + 1 or not frac.endswith("5"):
            continue
        p = Decimal(x[:-1])
        if n in (p, p + ulp) and x not in hits:
            hits.append(x)
    return hits


def missing(note_text, outputs):
    seen, rows = set(), []
    for ln, num, line in note_numbers(note_text):
        if in_outputs(num, outputs):
            continue
        rows.append((ln, num, line.strip()[:100], num in seen, double_rounding_sources(num, outputs)))
        seen.add(num)
    return rows


def selftest():
    note = "\n".join([
        "# 結果",
        "比は 2.513〜2.517 で、 割合は 41.7%。",       # both in outputs
        "丸めて 0.73 と書いた。",                         # output has 0.731 only → listed
        "§4.3 を見る。 版 2.0.2 と path a/1.5/b。",        # section, version, path → not picked
        "```",
        "python3 x.py --tol 0.25",                        # fenced → not picked
        "```",
        "定数 6.022 を使う。",                             # not in outputs → listed
        "もう一度 0.73。",                                  # repeated → listed, marked as repeat
    ])
    outputs = "ratio 2.513 2.517\nshare 41.7%\np5 0.731\n"
    rows = missing(note, outputs)
    got = [(ln, num, rep) for ln, num, _l, rep, _d in rows]
    assert got == [(3, "0.73", False), (8, "6.022", False), (9, "0.73", True)], got
    assert all(not r[4] for r in rows), rows                 # 0.731 does not end in 5
    # double rounding: the output 1.2345 is itself rounded (the value behind it is 1.23448)
    dr = missing("値は 1.235。\n値は 1.234。\n別の値 1.23。\n", "x = 1.2345\n")
    assert [(r[1], r[4]) for r in dr] == [("1.235", ["1.2345"]), ("1.234", ["1.2345"]), ("1.23", [])], dr
    assert double_rounding_sources("3.7", "x 3.75 y") == ["3.75"]
    assert double_rounding_sources("3.7", "x 3.65 y") == ["3.65"]   # 3.65 may round to 3.6 or 3.7
    assert double_rounding_sources("3.7", "x 3.85 y") == []
    assert not in_outputs("5.81", "x 5.812 y")          # no prefix match inside a longer number
    assert in_outputs("5.81", "x 5.81, y")
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "sub"))
        with open(os.path.join(d, "sub", "a.out.txt"), "w") as f:
            f.write("v 3.14\n")
        with open(os.path.join(d, "skip.png"), "w") as f:
            f.write("v 2.71\n")
        txt = read_outputs([d], DEFAULT_EXT)
        assert "3.14" in txt and "2.71" not in txt, txt
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("note", nargs="?")
    ap.add_argument("--outputs", nargs="+", default=[])
    ap.add_argument("--ext", nargs="+", default=list(DEFAULT_EXT))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    if not a.note or not a.outputs:
        ap.error("note と --outputs が要る")
    try:
        with open(a.note, encoding="utf-8") as fh:
            note_text = fh.read()
        outputs = read_outputs(a.outputs, tuple(a.ext))
    except (OSError, FileNotFoundError) as e:
        print(f"読めない: {e}", file=sys.stderr)
        return 2
    rows = missing(note_text, outputs)
    total = len(note_numbers(note_text))
    for ln, num, line, rep, dr in rows:
        mark = f"  ⚠️ 二重丸めの恐れ (出力 {', '.join(dr)} は表示の桁で丸めた値)" if dr else ""
        print(f"{a.note}:{ln}: {num}{' (再出)' if rep else ''}{mark}  | {line}")
    uniq = len({r[1] for r in rows})
    ndr = len({r[1] for r in rows if r[4]})
    print(f"note の数 {total} 個のうち、 出力に字のまま無いもの {len(rows)} 個 (異なる値 {uniq})。"
          " 丸めて写した数・本文の定数も並ぶ = 1 件ずつ丸め元と出どころを読む")
    if ndr:
        print(f"⚠️ 二重丸めの恐れ {ndr} 値: 出力の桁を増やして出し直してから写す"
              " (conventions/scientific-computing.md#note-numbers-against-outputs)")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
