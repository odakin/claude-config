#!/usr/bin/env python3
"""reply-position-refs.py — LaTeX の返答書の中で、 返答書の中の位置を指す句 (see the end of this letter / below / above / see our reply to R2) と `\\ref` を一覧にし、 指す先が残っているかを数える (engine = scripts/lib/reply_letter.py、 --selftest)。

なぜ存在するか: 批判役の判定の後に返答書の末尾の一覧を削ったが、 別の答えの「末尾の一覧を見よ」 の句は残り、
指す先の無い句のまま共著者に送った (実測)。 削った人は削った塊を見ていて、 その塊を指す句が別の答えにあることを見ない。
規約 = conventions/rebuttal-letter.md#stepwise-edit-proposals の 3 (組で入れた直しは両向きに当て外しする) と
#pre-send-verification-sheet の 3 (照合票の後に変えた所・削った所は照らし直す)。 差分を作る道具から呼ぶ。

機械で指す先を決める句:
  - 手紙の末尾 (end of this letter / closing list of this letter / listed at the end の類): 最後の答えの後から結び
    (Sincerely / Yours … / Best regards) までに本文があるか。 無ければ ✗。
  - 別の答え (our reply to R2 / see A3 の類): その番号の referee の項目 (`\\R2`) か答え (`\\A2`) があるか。
  - `\\ref{…}`・`\\eqref{…}`・`\\autoref{…}`・`\\cref{…}`: その label が返答書の中で `\\label` されているか
    (無ければ「返答書の外の label」 = 原稿の label なら xr などで繋いでいるかを人が見る)。
機械で決めない句 (一覧だけ出す): below / above / the following / as follows / given above / as noted above。
使い方:
  python3 reply-position-refs.py --reply reply.tex [--quote-macro Q] [--item-macro A] [--referee-macro R] [--json]
  python3 reply-position-refs.py --selftest
終了値: 0 = 指す先の無い句なし / 1 = 指す先の無い句がある / 2 = 使い方の誤り。
見ないもの: 句の指す先の中身が、 句の言うこと (末尾で述べたという X) を含むか。 「below」「above」 の指す先。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import reply_letter as rl  # noqa: E402

END_OF_LETTER = re.compile(r"(?:the\s+)?end\s+of\s+(?:this|the|our)\s+(?:letter|reply|response)"
                           r"|(?:the\s+)?(?:closing|final|last)\s+(?:list|paragraph|section)\s+of\s+(?:this|the|our)\s+(?:letter|reply)"
                           r"|listed\s+at\s+the\s+end", re.I)
OTHER_ANSWER = re.compile(r"(?:our\s+)?(?:reply|replies|answer|answers|response|responses)\s+to\s+(?:the\s+)?"
                          r"(?:(?:Referee's\s+)?(?:comment|point|question)\s+)?(?P<lab>[RA]?)\s*(?P<no>\d+)\b"
                          r"|\bsee\s+(?P<lab2>[RA])(?P<no2>\d+)\b", re.I)
VAGUE = re.compile(r"\b(?:as\s+noted\s+above|given\s+above|shown\s+above|as\s+explained\s+above|above|below"
                   r"|the\s+following|as\s+follows)\b", re.I)
REF_CMD = re.compile(r"\\(ref|eqref|autoref|cref|Cref|pageref)\{([^}]*)\}")
CLOSING = re.compile(r"\b(?:Sincerely|Yours\s+(?:sincerely|faithfully|truly)|(?:With\s+)?(?:best|kind|warm)\s+regards)\b", re.I)


def plain_words(s: str) -> int:
    s = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", s)
    s = re.sub(r"[{}\\$&%~^_\[\]]", " ", s)
    return len([w for w in s.split() if re.search(r"[A-Za-z]{2,}", w)])


def analyse(reply: str, quote_macro: str = "Q", item_macro: str = "A", referee_macro: str = "R") -> dict:
    text = rl.strip_comments(reply)
    answers = rl.segment_answers(text, quote_macro, item_macro)
    b0, b1 = rl.body_span(text)
    out = {"checked": [], "vague": []}
    # 最後の答えの後から結びまで
    last_end = max((a.end for a in answers), default=b0)
    cm = CLOSING.search(text, last_end, b1)
    tail_end = cm.start() if cm else b1
    tail = text[last_end:tail_end]
    tail_words = plain_words(re.sub(r"\\end\{itemize\}", " ", tail))
    items_present = set(re.findall(r"\\(?:" + re.escape(referee_macro) + "|" + re.escape(item_macro) + r")(\d+)\b", text))
    labels = set(re.findall(r"\\label\{([^}]*)\}", text))

    letter = rl.letter_spans(text, answers, referee_macro, item_macro)

    def in_letter(pos):
        return any(s <= pos < e for s, e in letter)

    def where(pos):
        a = rl.answer_at(answers, pos)
        return a.label if a else ("(引用の中)" if rl.in_quotes(answers, pos) else "(答えの外)")

    def ctx(pos, span=70):
        return " ".join(text[max(b0, pos - span):pos + span].split())

    for m in END_OF_LETTER.finditer(text, b0, b1):
        if not in_letter(m.start()):
            continue
        ok = tail_words >= 5 and m.start() < last_end
        out["checked"].append({"kind": "手紙の末尾", "phrase": " ".join(m.group(0).split()), "line": rl.line_of(text, m.start()),
                               "answer": where(m.start()), "target_exists": ok,
                               "target": (" ".join(tail.split())[:120] if ok else "(最後の答えの後、 結びの前に本文が無い)"),
                               "context": ctx(m.start())})
    for m in OTHER_ANSWER.finditer(text, b0, b1):
        if not in_letter(m.start()):
            continue
        no = m.group("no") or m.group("no2")
        ok = no in items_present
        out["checked"].append({"kind": "別の答え", "phrase": " ".join(m.group(0).split()), "line": rl.line_of(text, m.start()),
                               "answer": where(m.start()), "target_exists": ok,
                               "target": f"項目 {no}" + ("" if ok else " が返答書に無い"), "context": ctx(m.start())})
    for m in REF_CMD.finditer(text, b0, b1):
        ok = m.group(2) in labels
        out["checked"].append({"kind": "\\" + m.group(1), "phrase": " ".join(m.group(0).split()), "line": rl.line_of(text, m.start()),
                               "answer": where(m.start()), "target_exists": ok,
                               "target": "返答書の中の \\label" if ok else "返答書の外の label (xr などで繋いでいるかを見る)",
                               "context": ctx(m.start())})
    for m in VAGUE.finditer(text, b0, b1):
        if not in_letter(m.start()) or END_OF_LETTER.search(text[max(0, m.start() - 40):m.end() + 40]):
            continue
        out["vague"].append({"phrase": " ".join(m.group(0).split()), "line": rl.line_of(text, m.start()), "answer": where(m.start()),
                             "context": ctx(m.start())})
    out["checked"].sort(key=lambda x: x["line"])
    out["counts"] = {"checked": len(out["checked"]),
                     "missing_target": sum(1 for x in out["checked"] if not x["target_exists"]
                                           and not x["kind"].startswith("\\")),
                     "external_ref": sum(1 for x in out["checked"] if not x["target_exists"] and x["kind"].startswith("\\")),
                     "vague": len(out["vague"])}
    return out


def render(res: dict) -> str:
    c = res["counts"]
    lines = [f"位置を指す句 {c['checked']} (指す先が無い {c['missing_target']} / 返答書の外の label {c['external_ref']}) "
             f"/ 機械で指す先を決めない句 {c['vague']}"]
    for x in res["checked"]:
        mark = "✓" if x["target_exists"] else ("·" if x["kind"].startswith("\\") else "✗")
        lines.append(f"  {mark} 行 {x['line']} {x['answer']} [{x['kind']}] 「{x['phrase']}」 → {x['target']}")
    for x in res["vague"]:
        lines.append(f"  ? 行 {x['line']} {x['answer']} 「{x['phrase']}」: {x['context']}")
    return "\n".join(lines)


SELF_WITH = r"""\begin{document}
\begin{itemize}
\R1 Is the test fast? Is it safe?
\A1
\Q{Is the test fast?}
Yes (see the end of this letter).
\Q{Is it safe?}
Yes; see our reply to R2 and Eq.~\eqref{eq:x} below.
\R2 Why?
\A2
\Q{Why?}
Because of the cache, as noted above.
\end{itemize}
Finally, the following changes unrelated to the comments were made: a typo was corrected in the text.
Sincerely yours,
\end{document}
"""
SELF_WITHOUT = SELF_WITH.replace(
    "Finally, the following changes unrelated to the comments were made: a typo was corrected in the text.\n", "")


def selftest() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + msg)
        ok = ok and cond
    r1 = analyse(SELF_WITH)
    r2 = analyse(SELF_WITHOUT)
    e1 = [x for x in r1["checked"] if x["kind"] == "手紙の末尾"]
    e2 = [x for x in r2["checked"] if x["kind"] == "手紙の末尾"]
    check(len(e1) == 1 and e1[0]["target_exists"], "末尾の段落があれば末尾を指す句は通す")
    check(len(e2) == 1 and not e2[0]["target_exists"], "末尾の段落を削ると末尾を指す句を出す")
    oa = [x for x in r1["checked"] if x["kind"] == "別の答え"]
    check(len(oa) == 1 and oa[0]["target_exists"], "「our reply to R2」 は R2 があれば通す")
    r3 = analyse(SELF_WITH.replace("our reply to R2", "our reply to R5"))
    check(any(x["kind"] == "別の答え" and not x["target_exists"] for x in r3["checked"]), "無い項目を指す句を出す")
    check(any(x["kind"] == "\\eqref" and not x["target_exists"] for x in r1["checked"]), "返答書の外の label を数える")
    check(r1["counts"]["vague"] >= 2, "below・as noted above を一覧に出す")
    check(r2["counts"]["missing_target"] == 1 and r1["counts"]["missing_target"] == 0, "数え")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--reply", type=Path)
    ap.add_argument("--quote-macro", default="Q")
    ap.add_argument("--item-macro", default="A")
    ap.add_argument("--referee-macro", default="R")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.reply:
        ap.print_usage(sys.stderr)
        return 2
    res = analyse(a.reply.read_text(encoding="utf-8"), a.quote_macro, a.item_macro, a.referee_macro)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))
    return 1 if res["counts"]["missing_target"] else 0


if __name__ == "__main__":
    sys.exit(main())
