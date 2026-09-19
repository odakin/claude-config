#!/usr/bin/env python3
"""campussquare-roster-split.py — CampusSquare の「全担当科目の名簿 CSV」 を、科目 (コマ) ごとの成績登録用の名簿 CSV の形に分ける。

CampusSquare の成績登録画面から落とせる名簿 CSV は 2 種類あり、形が違う (実測):
- 全担当科目を 1 file にしたもの: 学生氏名カナの列がある
- 科目 1 つの画面から落としたもの: カナの列が無い。 同じ授業に付いた旧課程の別の時間割番号の学生も同じ file に入る
  (新課程の番号の行 → 旧課程の番号の行の順)。 file 名は慣習的に <年度>_<新課程の番号>.csv
本 script は前者から後者を作る: カナの列を落とし、 指定した番号の行を指定順に集める。 行の bytes はカナの field を
除いてそのまま (CP932・CRLF・全 field quoted・header の空白も元のまま)。 形式の一般則 =
conventions/campussquare.md#roster-grade-csv。

  python3 campussquare-roster-split.py SRC.csv --course OUT1.csv=100001,900001 --course OUT2.csv=100002
      → 件数だけ出す (dry-run)。 --write で書く (既にある file は上書きしない)
  --selftest : 合成の CSV で回す

終了コード: 0 = 成功 / 1 = 指定の番号が名簿に無い・書き先が既にある / 2 = 入力の形が想定外。
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ENC = "cp932"
FIELD = re.compile(r'"[^"]*"[^,]*')  # quoted field + その後ろの空白 (header は `"x" ,"y"` 形)


def fields(line: str) -> list[str]:
    return FIELD.findall(line)


def value(tok: str) -> str:
    return tok.strip().strip('"').strip()


def split(src_text: str, courses: list[tuple[str, list[str]]]) -> dict[str, str]:
    """courses = [(書き先の名前, [新課程の番号, 旧課程の番号...]), ...] → {書き先: 本文}"""
    lines = [l for l in src_text.split("\r\n") if l]
    if not lines:
        raise ValueError("空の CSV")
    header = fields(lines[0])
    kana = [i for i, t in enumerate(header) if "カナ" in t]
    code_col = next((i for i, t in enumerate(header) if "時間割番号" in t), None)
    if len(kana) != 1 or code_col is None:
        raise ValueError(f"header が想定外 (カナ列 {len(kana)} 個、 時間割番号列 {code_col})")
    k = kana[0]

    def drop(toks):
        return ",".join(t for i, t in enumerate(toks) if i != k)

    rows = [fields(l) for l in lines[1:]]
    for r in rows:
        if len(r) != len(header):
            raise ValueError(f"列数が header と違う行: {len(r)} != {len(header)}")
    out = {}
    for dest, codes in courses:
        picked = []
        for c in codes:
            sel = [r for r in rows if value(r[code_col]) == c]
            if not sel:
                raise LookupError(f"{c} が名簿に無い ({dest})")
            picked += sel
        out[dest] = "\r\n".join([drop(header)] + [drop(r) for r in picked]) + "\r\n"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", nargs="?")
    ap.add_argument("--course", action="append", default=[], metavar="OUT=CODE[,CODE...]")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.src or not a.course:
        ap.error("SRC と --course が要る")
    courses = []
    for spec in a.course:
        dest, _, codes = spec.rpartition("=")
        if not dest or not codes:
            ap.error(f"--course の形が違う: {spec}")
        courses.append((dest, [c.strip() for c in codes.split(",") if c.strip()]))
    text = Path(a.src).read_bytes().decode(ENC)
    try:
        out = split(text, courses)
    except LookupError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    rc = 0
    for dest, codes in courses:
        body = out[dest]
        n = body.count("\r\n") - 1
        p = Path(dest)
        if a.write:
            if p.exists():
                print(f"❌ 既にある (上書きしない): {p}", file=sys.stderr)
                rc = 1
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body.encode(ENC))
        print(f"{'書いた' if a.write else 'dry-run'}: {p} {n} 行 ({', '.join(codes)})")
    return rc


# ---------------------------------------------------------------- selftest

HDR = ('"年度(Academic Year)" ,"※時間割番号(Course Code)" ,"曜日・時限(Day/Period)" ,"※学生番号(Student ID No.)" ,'
       '"学生氏名(Student\'s Name)" ,"学生氏名カナ(Student\'s Name)" ,"※登録用評価(Letter Grade)" ,"E-mail"')


def _row(code, sid, name, kana):
    return f'"2030","{code}","金2(Fri 2)","{sid}","{name}","{kana}","","{sid.lower()}@example.invalid"'


def selftest() -> int:
    fails = []

    def check(cond, name):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    src = "\r\n".join([HDR,
                       _row("OLD1", "X0001", "甲野 太郎", "ｺｳﾉ ﾀﾛｳ"),
                       _row("NEW1", "Y0001", "乙山 花子", "ｵﾂﾔﾏ ﾊﾅｺ"),
                       _row("NEW2", "Y0002", "丙川 次郎", "ﾍｲｶﾜ ｼﾞﾛｳ"),
                       _row("NEW1", "Y0003", "丁田 三郎", "ﾃｲﾀﾞ ｻﾌﾞﾛｳ")]) + "\r\n"
    out = split(src, [("a.csv", ["NEW1", "OLD1"]), ("b.csv", ["NEW2"])])
    a_lines = out["a.csv"].split("\r\n")
    check(all("ｶﾅ" not in l and "ｺｳﾉ" not in l for l in a_lines) and "カナ" not in a_lines[0],
          "カナの列を header と行の両方から落とす")
    check(a_lines[0].startswith('"年度(Academic Year)" ,"※時間割番号(Course Code)" ,') and a_lines[0].count(" ,") == 6,
          "header の空白 (` ,`) は元のまま")
    check([l.split(",")[3] for l in a_lines[1:-1]] == ['"Y0001"', '"Y0003"', '"X0001"'],
          "新課程の番号の行 → 旧課程の番号の行の順に集める")
    check(out["a.csv"].endswith("\r\n") and "\n" not in out["a.csv"].replace("\r\n", ""), "改行は CRLF で末尾にも付ける")
    check(out["b.csv"].count("\r\n") == 2, "他の科目の行を混ぜない")
    try:
        split(src, [("c.csv", ["NOPE"])])
        check(False, "名簿に無い番号は LookupError")
    except LookupError:
        check(True, "名簿に無い番号は LookupError")
    with tempfile.TemporaryDirectory() as d:
        sp, dest = Path(d) / "all.csv", Path(d) / "sub" / "x.csv"
        sp.write_bytes(src.encode(ENC))
        rc1 = main([str(sp), "--course", f"{dest}=NEW2"])
        rc2 = main([str(sp), "--course", f"{dest}=NEW2", "--write"])
        body = dest.read_bytes().decode(ENC) if dest.exists() else ""
        rc3 = main([str(sp), "--course", f"{dest}=NEW2", "--write"])
        check(rc1 == 0 and rc2 == 0 and "丙川" in body, "--write で CP932 の file を書く (無ければ dry-run)")
        check(rc3 == 1 and dest.read_bytes().decode(ENC) == body, "既にある file は上書きせず exit 1")
    print("campussquare-roster-split selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
