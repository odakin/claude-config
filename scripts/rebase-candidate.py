#!/usr/bin/env python3
"""rebase-candidate.py — 全文の候補を、 動いた今の土台の版の上に作り直す (前の土台と前の候補の差の塊を、 今の土台の同じ文にちょうど 1 回ずつ当てる)。

なぜ:
  保護された file を「全文の候補 + SHA-256」 で出して本人の答えを待つ間に、 他の session の commit で土台の版が動くことがある
  (実測)。 動いた版に古い全文をそのまま当てると、 その間に入った他の変更を黙って消す
  (conventions/multi-session-coordination.md#parallel-full-text-candidates)。 手で塊を探して当て直すと、 当たる位置を
  取り違えても気づかない。 この道具は、 前の土台と前の候補を行で比べて変わった塊を出し、 塊の前の文 (消す・置き換える行) が
  今の土台にちょうど 1 回現れるときだけ当てる。 1 つでも当たらない・2 回以上当たる塊があれば何も書かずに止まる
  (推測で位置を選ばない)。 足すだけの塊は、 前の行を錨にする (錨が 1 回でなければ止まる)。

使い方:
  rebase-candidate.py <前の土台> <前の候補> <今の土台> <書き出す候補>
  rebase-candidate.py --selftest
終了値: 0 = 書いた / 1 = 当たらない塊があり書かなかった / 2 = 引数の誤り。
限界: 塊の前の文が今の土台で直されていれば止まる (= その塊は人が見て作り直す)。 当てた結果の意味は見ない = 作り直した候補は
  SHA-256 が変わるので、 本人の答えを SHA-256 に結ぶ運用では見せ直す
  (conventions/agent-rule-ownership.md#owner-answer-in-another-window の 4)。
"""
from __future__ import annotations

import difflib
import sys
import tempfile
from pathlib import Path


def rebase(old_base: str, old_cand: str, new_base: str) -> tuple[str | None, list[str]]:
    """(作り直した候補, 塊ごとの報告)。 当たらない塊があれば (None, 報告)。"""
    a, b = old_base.splitlines(True), old_cand.splitlines(True)
    out, notes = new_base, []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old_s, new_s = "".join(a[i1:i2]), "".join(b[j1:j2])
        if not old_s:  # 足すだけの塊 = 前の行を錨にする (先頭に足す塊は次の行を錨にする)
            if i1 > 0:
                anchor = a[i1 - 1]
                old_s, new_s = anchor, anchor + new_s
            elif a:
                anchor = a[0]
                old_s, new_s = anchor, new_s + anchor
            else:
                return None, ["前の土台が空 = 錨が無い"]
        n = out.count(old_s)
        if n != 1:
            return None, notes + [f"止めた: 前の土台の {i1 + 1} 行目からの塊 ({tag}) が今の土台に {n} 回現れる (1 回でない)"]
        out = out.replace(old_s, new_s)
        notes.append(f"当てた: 前の土台の {i1 + 1}〜{max(i1 + 1, i2)} 行目 ({tag})")
    return out, notes


def selftest() -> int:
    bad = 0

    def check(label: str, ok: bool) -> None:
        nonlocal bad
        bad += not ok
        print(("ok   " if ok else "FAIL ") + label)

    base = "a\nb\nc\nd\ne\n"
    cand = "a\nB\nc\nd\nd2\ne\n"  # b を直し、 d の後に 1 行足した
    moved = "x\na\nb\nc\nd\ne\nz\n"  # 他の変更 = 先頭と末尾に 1 行ずつ
    out, _ = rebase(base, cand, moved)
    check("動いた土台に塊を当て、 他の変更 (先頭・末尾の行) を残す", out == "x\na\nB\nc\nd\nd2\ne\nz\n")
    out, notes = rebase(base, cand, "a\nb2\nc\nd\ne\n")
    check("塊の前の文が今の土台で直されていれば止まる (書かない)", out is None and "0 回" in notes[-1])
    out, notes = rebase(base, cand, "a\nb\nc\nb\nd\ne\n")
    check("塊の前の文が今の土台に 2 回現れれば止まる", out is None and "2 回" in notes[-1])
    out, _ = rebase(base, "top\n" + base, "x\n" + base)
    check("先頭に足す塊は次の行を錨にする", out == "x\ntop\na\nb\nc\nd\ne\n")
    out, _ = rebase(base, base, "q\n")
    check("差の無い候補は今の土台をそのまま返す", out == "q\n")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        for name, text in (("ob", base), ("oc", cand), ("nb", moved)):
            (p / name).write_text(text, encoding="utf-8")
        rc = main([str(p / "ob"), str(p / "oc"), str(p / "nb"), str(p / "out")])
        check("CLI: 書いて 0 で終わる", rc == 0 and (p / "out").read_text(encoding="utf-8") == "x\na\nB\nc\nd\nd2\ne\nz\n")
        (p / "nb").write_text("a\nb2\nc\nd\ne\n", encoding="utf-8")
        rc = main([str(p / "ob"), str(p / "oc"), str(p / "nb"), str(p / "out2")])
        check("CLI: 当たらなければ 1 で終わり、 書かない", rc == 1 and not (p / "out2").exists())
    print("selftest:", "ok" if not bad else f"{bad} FAIL")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv == ["--selftest"]:
        return selftest()
    if len(argv) != 4 or any(a.startswith("-") for a in argv):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        print("使い方: rebase-candidate.py <前の土台> <前の候補> <今の土台> <書き出す候補>", file=sys.stderr)
        return 2
    texts = [Path(x).read_text(encoding="utf-8") for x in argv[:3]]
    out, notes = rebase(*texts)
    for n in notes:
        print(n)
    if out is None:
        print("書かなかった (当たらない塊を人が見て作り直す)", file=sys.stderr)
        return 1
    Path(argv[3]).write_text(out, encoding="utf-8")
    print(f"書いた: {argv[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
