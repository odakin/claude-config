#!/usr/bin/env python3
"""calibrate-final-message-pattern.py — 発話を見る Stop hook の句を、 過去の transcript の各 turn の最終 assistant 発話に当てて検出数と例を出す（導入前の誤検出の見積もり用。 turn の境界は hook と同じ scripts/lib/transcript_turns.py、 --skip-quoted / --exclude-sentence-with で hook の除外を再現、 --selftest。 conventions/hook-authoring.md#text-pattern-stop-hook）

使い方:
  calibrate-final-message-pattern.py --pattern 'REGEX' [--sessions 120]
      [--glob '~/.claude/projects/*/*.jsonl'] [--skip-quoted] [--exclude-sentence-with 自動 ...]
      [--samples 20]
出力: sessions / turns / hits と、 hit ごとに session id の先頭 8 桁と前後の文脈。 誤検出かどうかは
  人が読んで数える (= 句の一致は意図を識別しない。 hook-authoring.md#hook-no-go-judgment)。 1 turn の最終発話につき
  hit は 1 回まで数える (= hook が 1 回 block するのと同じ単位)。
⚠️ transcript は local の private data。 出力 (文脈の抜粋) を公開の場所に貼らない。
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from transcript_turns import (inside_quote, load_entries, sentence_around,  # noqa: E402
                              turn_final_texts)

DEFAULT_GLOB = "~/.claude/projects/*/*.jsonl"


def scan(files, pat, skip_quoted=False, exclude_words=(), samples=20):
    """→ (turns, hits, [(session8, 文脈)])"""
    n_turns = n_hits = 0
    out = []
    for fp in files:
        try:
            entries = load_entries(fp)
        except OSError:
            continue
        for text in turn_final_texts(entries):
            n_turns += 1
            for m in pat.finditer(text):
                if skip_quoted and inside_quote(text, m.start()) and inside_quote(text, m.end()):
                    continue
                if exclude_words and any(w in sentence_around(text, m.start(), m.end())
                                         for w in exclude_words):
                    continue
                n_hits += 1
                if len(out) < samples:
                    ctx = text[max(0, m.start() - 40): m.end() + 20].replace("\n", " ")
                    out.append((Path(fp).stem[:8], ctx))
                break
    return n_turns, n_hits, out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Stop hook の句を過去の最終発話で校正する")
    ap.add_argument("--pattern", help="Python の正規表現")
    ap.add_argument("--sessions", type=int, default=120, help="新しい順に何 session 見るか")
    ap.add_argument("--glob", default=DEFAULT_GLOB)
    ap.add_argument("--skip-quoted", action="store_true", help="「」『』の中に丸ごと収まる match を除く")
    ap.add_argument("--exclude-sentence-with", action="append", default=[], metavar="WORD",
                    help="この語を含む文の match を除く (繰り返し可)")
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.pattern:
        ap.error("--pattern が要る")
    files = sorted(glob.glob(os.path.expanduser(args.glob)), key=os.path.getmtime)[-args.sessions:]
    n_turns, n_hits, out = scan(files, re.compile(args.pattern), args.skip_quoted,
                                args.exclude_sentence_with, args.samples)
    print(f"sessions={len(files)} turns={n_turns} hits={n_hits}")
    for sid, ctx in out:
        print(f" - {sid} … {ctx}")
    return 0


def selftest() -> int:
    import json
    checks = []

    def ck(name, cond):
        checks.append((name, bool(cond)))

    def line(o):
        return json.dumps(o, ensure_ascii=False) + "\n"

    def user(t):
        return line({"type": "user", "message": {"content": t}})

    def tool_result():
        return line({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})

    def asst(t=None, tool=False):
        blocks = [{"type": "tool_use", "name": "Bash", "input": {}}] if tool else []
        if t is not None:
            blocks.append({"type": "text", "text": t})
        return line({"type": "assistant", "message": {"content": blocks}})

    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "aaaaaaaa-1.jsonl"
        p1.write_text(
            user("やって") + asst("途中の説明。") + asst(tool=True) + tool_result()
            + asst("iMac で次を 1 回実行してください。")          # turn 1: hit
            + user("次") + asst("「iMac で 1 回実行してください」のような句を拾う hook です。")  # 引用
            + user("次") + asst("自動で出るので、 そのとき 1 回実行してください。")         # 「自動」
            + user("次") + asst("何もしなくて大丈夫です。")                                  # 無関係
            + "{broken json\n",
            encoding="utf-8")
        p2 = Path(td) / "bbbbbbbb-2.jsonl"
        p2.write_text(user("やって") + asst(tool=True) + tool_result(), encoding="utf-8")  # 発話なし

        from transcript_turns import current_turn_final, turns as split_turns
        entries = load_entries(p1)
        ck("壊れた行は飛ばす", len(entries) == 11)
        ck("tool_result の user 行は turn の境界にしない", len(split_turns(entries)) == 4)
        ck("最終発話 = turn の最後の text", turn_final_texts(entries)[0] == "iMac で次を 1 回実行してください。")
        final, tools = current_turn_final(entries)
        ck("今の turn = 最後の実 user 以降", final == "何もしなくて大丈夫です。" and tools == 0)
        ck("発話の無い turn は数えない", turn_final_texts(load_entries(p2)) == [])

        pat = re.compile(r"(?:1 ?回|次)[^。\n]{0,40}実行してください")
        files = [str(p1), str(p2)]
        t, h, out = scan(files, pat)
        ck("除外なし: 4 turn 中 3 hit", (t, h) == (4, 3))
        t, h, out = scan(files, pat, skip_quoted=True)
        ck("--skip-quoted で引用の例示を除く", h == 2)
        t, h, out = scan(files, pat, skip_quoted=True, exclude_words=["自動"])
        ck("--exclude-sentence-with で carrier を名指しした文を除く", h == 1 and out[0][0] == "aaaaaaaa")
        ck("inside_quote: 括弧の中で始まり外まで続く match は引用扱いしない",
           not inside_quote("「次に」と言われたら実行", len("「次に」と言われたら")))

    fails = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'✅' if ok else '❌'} {n}")
    print(f"--- calibrate-final-message-pattern selftest: PASS={len(checks) - len(fails)} FAIL={len(fails)} ---")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
