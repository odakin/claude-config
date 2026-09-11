"""transcript_turns.py — Claude Code の transcript (jsonl) を turn に分けて最終 assistant 発話を取り出す共通部品（Stop hook の「今の turn の最終発話」 と、 過去 transcript で句を校正する calibrate-final-message-pattern.py が同じ境界で読む。 引用の中かの判定 inside_quote と、 match を含む 1 文を返す sentence_around も持つ）

turn の境界 = type が user で、 content が tool_result の list でない行 (= 実 user メッセージ)。
最終発話 = その turn の assistant 行のうち、 最後の空でない text block。
読めない行は飛ばす (= 壊れた行 1 本で全体を捨てない)。 呼び出し側の hook は import 失敗も含めて fail-open にする。
使い方と校正の手順 = conventions/hook-authoring.md#text-pattern-stop-hook。
"""
from __future__ import annotations

import json

OPEN_Q, CLOSE_Q = "「『", "」』"


def load_entries(path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if isinstance(e, dict):
                out.append(e)
    return out


def _blocks(e: dict) -> list:
    c = (e.get("message") or {}).get("content")
    return c if isinstance(c, list) else []


def is_real_user(e: dict) -> bool:
    """実 user メッセージか (= tool_result を運ぶ user 行は turn の境界にしない)。"""
    if e.get("type") != "user":
        return False
    return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in _blocks(e))


def summarize(turn: list[dict]) -> tuple[str, int]:
    """turn の entry 列 → (最終 text, tool_use の数)。"""
    final, tools = "", 0
    for e in turn:
        if e.get("type") != "assistant":
            continue
        for b in _blocks(e):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                tools += 1
            elif b.get("type") == "text" and (b.get("text") or "").strip():
                final = b["text"]
    return final, tools


def current_turn(entries: list[dict]) -> list[dict]:
    """末尾から遡って最後の実 user メッセージ以降 (無ければ全体)。 Stop hook が見る「今の turn」。"""
    for i in range(len(entries) - 1, -1, -1):
        if is_real_user(entries[i]):
            return entries[i:]
    return entries


def current_turn_final(entries: list[dict]) -> tuple[str, int]:
    return summarize(current_turn(entries))


def turns(entries: list[dict]) -> list[list[dict]]:
    out, cur = [], []
    for e in entries:
        if is_real_user(e):
            if cur:
                out.append(cur)
            cur = [e]
        else:
            cur.append(e)
    if cur:
        out.append(cur)
    return out


def turn_final_texts(entries: list[dict]) -> list[str]:
    """全 turn の最終発話 (発話の無い turn は除く)。 校正用。"""
    return [t for t in (summarize(x)[0] for x in turns(entries)) if t]


def inside_quote(text: str, i: int) -> bool:
    """位置 i が 「」 / 『』 の中か。 match の始点と終点が両方中なら「例示の引用」 とみなせる。"""
    depth = 0
    for ch in text[:i]:
        if ch in OPEN_Q:
            depth += 1
        elif ch in CLOSE_Q and depth:
            depth -= 1
    return depth > 0


def sentence_around(text: str, start: int, end: int) -> str:
    """[start, end) を含む 1 文 (= 。 と改行で区切る)。"""
    s = max(text.rfind("。", 0, start), text.rfind("\n", 0, start)) + 1
    ends = [i for i in (text.find("。", end), text.find("\n", end)) if i != -1]
    return text[s:(min(ends) if ends else len(text))]
