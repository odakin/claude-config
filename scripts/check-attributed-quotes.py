#!/usr/bin/env python3
"""check-attributed-quotes.py — 共著者・編集者・referee に出す文の下書きで、 他人 (referee・共著者・文献) に帰して鉤括弧・引用符で引いた文が原文の部分文字列かを数え、 違うものを行で出す (空白・改行・引用符は寄せて比べる。 engine = scripts/lib/attributed_quotes.py、 --selftest)。

なぜ存在するか: 下請けの要約を平易に書き直す段で、 言い換えが鉤括弧の中に入って「referee は … と言っているだけ」 の
引用の形で外に出た (実測)。 目で読み返すと書き手は原文の意味で読むので見落とす。 規約 =
conventions/rebuttal-letter.md#pre-send-verification-sheet (送る前の照合票。 この結果は照合票の「照らしたこと」 の 1 行で、
帰属の語の無い引用・括らない言い換え・文脈の切り離しは「照らしていないこと」 に書く)。

送信の道具から呼ばれる形: scripts/discord-post.py と送信の CLI (個人層の Gmail の送信の CLI など) の
--quote-source <原文の file> = 送る前にこの検査を回し、 他人に帰した引用が原文に無ければ --send を止める
(--allow-unmatched-quote '<理由>' で理由つきで通す)。 --quote-source が無いときは、 帰属の語のある引用の件数を 1 行で知らせるだけ。

使い方:
  python3 check-attributed-quotes.py --draft msg.txt --source decision.txt [--source other.txt]
                                     [--attrib <名前> ...] [--all] [--min-chars 5] [--json]
  python3 check-attributed-quotes.py --selftest
  --attrib = 帰属の語に足す語 (人名など。 規約の側に名前を書かず、 呼び手が渡す)
  --all    = 帰属の語に依らず、 全部の引用を他人に帰した引用として照らす
終了値: 0 = 他人に帰した引用はどれも原文にある / 1 = 原文に無い (か片の順が違う) ものがある / 2 = 使い方の誤り。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import attributed_quotes as aq  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--draft", type=Path, help="送る文の下書き (UTF-8)")
    ap.add_argument("--source", type=Path, action="append", default=[], help="原文の file (複数可)")
    ap.add_argument("--attrib", action="append", default=[], help="帰属の語に足す語 (人名など)")
    ap.add_argument("--all", action="store_true", help="全部の引用を他人に帰した引用として照らす")
    ap.add_argument("--min-chars", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return aq.selftest()
    if not a.draft or not a.source:
        ap.error("--draft と、 少なくとも 1 つの --source が要る")
    for p in [a.draft, *a.source]:
        if not p.is_file():
            ap.error(f"file が無い: {p}")
    read = lambda p: p.read_text(encoding="utf-8", errors="replace")
    quotes = aq.check_text(read(a.draft), [read(p) for p in a.source], tuple(a.attrib),
                           all_quotes=a.all, min_chars=a.min_chars)
    if a.json:
        print(json.dumps([dict(line=q.line, text=q.text, form=q.form, attrib=q.attrib,
                               status=q.status, missing=q.missing, failure=q.failure)
                          for q in quotes], ensure_ascii=False, indent=1))
    else:
        print("\n".join(aq.format_report(quotes, label=a.draft.name)))
    return 1 if aq.failures(quotes) else 0


if __name__ == "__main__":
    sys.exit(main())
