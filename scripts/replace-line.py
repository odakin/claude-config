#!/usr/bin/env python3
"""replace-line.py — 一意 prefix assert 付きの 1 行置換 (= 「検証してから書く」 の機械化)。

長大な 1 行単位の構造 (= CLAUDE.md の bullet / markdown table の row / yaml の 1 行 field)
を安全に置換するための最小 helper。 Edit tool の exact-match は数 KB の CJK 長行では
実務上使いにくく、 sed / 行番号指定は「別の行を書き換えた」 事故 (= 行番号 drift /
pattern 多重 hit) を静かに通す。 本 script は **「prefix がちょうど 1 行に一致する」 を
書き込みの前提条件として assert** し、 0 件 / 2 件以上なら何も書かずに error exit する。

主用途 = memory file の縮退 (= conventions/memory-file-slimming.md の手順 4)。
汎用の行置換にも使える。

usage:
    python3 replace-line.py <file> <prefix> < new_line.txt
      - <file> 内で <prefix> で始まる行がちょうど 1 行であることを assert
        (0 or 2+ は書き込まずに exit 1)
      - stdin の内容 (末尾改行は補完) でその行を丸ごと置換
      - before/after のバイト差を stdout に報告 (= 縮退の実測に使う)
    python3 replace-line.py --selftest   # tempdir fixture による回帰テスト

設計判断:
  - 置換単位は「行」 のみ (= 複数行 block は対象外)。 複数行の置換は Edit tool /
    専用 script の領分 — 本 script は「1 行が長大で他に安全な道具が無い」 niche だけを埋める。
  - prefix は正規表現でなく literal startswith (= quoting 事故の余地を消す)。
  - 一致 0 件も error (= 「もう置換済みだった」 を silent success にしない。 冪等に
    再実行したい呼び出し側は exit code で分岐する)。
"""

from __future__ import annotations

import sys
from pathlib import Path


def replace_line(path: Path, prefix: str, new_text: str) -> tuple[int, int, int]:
    """path 内の prefix 一意一致行を new_text で置換。 (line_no, old_bytes, new_bytes) を返す。

    一致がちょうど 1 行でなければ SystemExit(1)。
    """
    if not new_text.endswith("\n"):
        new_text += "\n"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    hits = [i for i, l in enumerate(lines) if l.startswith(prefix)]
    if len(hits) != 1:
        raise SystemExit(
            f"ERROR: prefix matched {len(hits)} lines (need exactly 1): {prefix!r}")
    i = hits[0]
    old_b = len(lines[i].encode("utf-8"))
    new_b = len(new_text.encode("utf-8"))
    lines[i] = new_text
    path.write_text("".join(lines), encoding="utf-8")
    return i + 1, old_b, new_b


def selftest() -> None:
    import tempfile

    ok = 0

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        if not cond:
            sys.exit(f"selftest FAIL: {name}")
        ok += 1

    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "t.md"

        # 1) 正常置換: 一意 prefix の行だけが置き換わり、 他行は byte 不変
        f.write_text("- **a**: old payload\n- **b**: keep\n", encoding="utf-8")
        ln, ob, nb = replace_line(f, "- **a**:", "- **a**: new\n")
        check("line no", ln == 1)
        check("old bytes", ob == len("- **a**: old payload\n".encode()))
        check("replaced", f.read_text() == "- **a**: new\n- **b**: keep\n")

        # 2) 末尾改行の補完
        replace_line(f, "- **b**:", "- **b**: v2")
        check("newline appended", f.read_text().endswith("- **b**: v2\n"))

        # 3) 0 件一致 = error、 file 不変
        before = f.read_text()
        try:
            replace_line(f, "- **zzz**:", "x")
            check("zero-hit raises", False)
        except SystemExit:
            check("zero-hit raises", True)
        check("zero-hit no write", f.read_text() == before)

        # 4) 多重一致 = error、 file 不変
        f.write_text("- dup: 1\n- dup: 2\n", encoding="utf-8")
        try:
            replace_line(f, "- dup:", "x")
            check("multi-hit raises", False)
        except SystemExit:
            check("multi-hit raises", True)
        check("multi-hit no write", f.read_text() == "- dup: 1\n- dup: 2\n")

        # 5) CJK 長行の byte 計測 (= UTF-8 バイト数で報告する契約)
        f.write_text("- 長い行: " + "あ" * 10 + "\n", encoding="utf-8")
        _, ob, nb = replace_line(f, "- 長い行:", "- 長い行: 短\n")
        check("cjk old bytes", ob == len(("- 長い行: " + "あ" * 10 + "\n").encode("utf-8")))
        check("cjk new bytes", nb == len("- 長い行: 短\n".encode("utf-8")))

    print(f"selftest: {ok}/{ok} PASS")


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        selftest()
        return
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip())
    path, prefix = Path(sys.argv[1]), sys.argv[2]
    new_text = sys.stdin.read()
    ln, old_b, new_b = replace_line(path, prefix, new_text)
    print(f"L{ln}: {old_b} B -> {new_b} B (saved {old_b - new_b} B)")


if __name__ == "__main__":
    main()
