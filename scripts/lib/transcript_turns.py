"""transcript_turns.py — Claude Code の transcript (jsonl) を turn に分けて最終 assistant 発話を取り出す共通部品（Stop hook の「今の turn の最終発話」 と、 過去 transcript で句を校正する calibrate-final-message-pattern.py が同じ境界で読む。 引用の中かの判定 inside_quote と、 match を含む 1 文を返す sentence_around も持つ）

turn の境界 = type が user で、 content が tool_result の list でない行 (= 実 user メッセージ)。
最終発話 = その turn の assistant 行のうち、 最後の空でない text block。
読めない行は飛ばす (= 壊れた行 1 本で全体を捨てない)。 呼び出し側の hook は import 失敗も含めて fail-open にする。
使い方と校正の手順 = conventions/hook-authoring.md#text-pattern-stop-hook。
session の情報 (始めたフォルダ・cwd の履歴・追加フォルダ・entrypoint) も読む: 基準フォルダ = 最初の environment
snapshot の workingDirectory (各行の cwd は Bash の cd で変わるので、 最初の cwd は fallback)。
transcript を証拠に使う手順 = conventions/debugging-discipline.md#transcript-screenshots。
"""
from __future__ import annotations

import json
import os

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


# ---- session の情報 ------------------------------------------------------------------

def _env_snapshots(entries: list[dict]):
    for e in entries:
        a = e.get("attachment") if isinstance(e, dict) else None
        if isinstance(a, dict) and a.get("type") == "environment" and isinstance(a.get("snapshot"), dict):
            yield a["snapshot"]


def session_additional_dirs(entries: list[dict], settings_paths: list[str] | None = None) -> list[str]:
    """session に追加したフォルダ。 transcript の environment snapshot を優先し、 無ければ settings の additionalDirectories。"""
    out: list[str] = []
    for snap in _env_snapshots(entries):
        for d in snap.get("additionalWorkingDirectories") or []:
            if isinstance(d, str) and d not in out:
                out.append(d)
    if out:
        return out
    for sp in settings_paths if settings_paths is not None else [os.path.expanduser("~/.claude/settings.json")]:
        try:
            with open(sp, encoding="utf-8") as f:
                dirs = (json.load(f).get("permissions") or {}).get("additionalDirectories") or []
        except Exception:
            continue
        out.extend(d for d in dirs if isinstance(d, str) and d not in out)
    return out


def session_root_and_cwds(entries: list[dict]) -> tuple[str | None, list[str]]:
    """transcript → (session を始めた folder, 出現した cwd の新しい順の list)。
    session を始めた folder = 最初の environment snapshot の workingDirectory、 無ければ最初に現れた cwd。"""
    root = next((s.get("workingDirectory") for s in _env_snapshots(entries)
                 if isinstance(s.get("workingDirectory"), str)), None)
    order: list[str] = []
    for e in entries:
        c = e.get("cwd") if isinstance(e, dict) else None
        if not isinstance(c, str) or not c:
            continue
        if root is None:
            root = c
        if c in order:
            order.remove(c)
        order.append(c)
    return root, list(reversed(order))


def session_entrypoint(entries: list[dict]) -> str | None:
    for e in entries:
        ep = e.get("entrypoint") if isinstance(e, dict) else None
        if isinstance(ep, str) and ep:
            return ep
    return None


