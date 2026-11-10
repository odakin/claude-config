#!/usr/bin/env python3
"""chat-math-display-fix.py — MessageDisplay: 返事の文のうち desktop の Code タブが生の TeX のまま出す数式を、 意味を変えずに描ける形へ書き換えて、 画面の表示だけを差し替える (会話記録と Claude が読む文は元のまま)

何を塞ぐか (正本 = conventions/chat-math-rendering.md#code-tab-display-fix):
  Stop の chat-math-render-guard は返事が画面に出た後に走るので、 崩れた版は本人の画面に残り、 直した版と 2 通並ぶ。
  MessageDisplay は返事の文を画面に出す前に呼ばれ、 返した displayContent が元の文の代わりに出る (公式の hooks の説明)。
書き換え = 同じ dir の chat-math-render-guard.py の fix_text: 本体の判定式で落ちる式だけを、 区切りの付け替え
  (`$…$` → 直前に空白の `\\(…\\)`)・1 文字の添字と上付きの `{}`・`\\(` の前の空白・表のセルの `|` → `\\vert`・`\\[…\\]` → `$$…$$`・
  数だけの式 → 地の文、 で直し、 直した行が同じ判定式を通るときだけ差し替える。 直せない式と数式でない `$` (金額・shell の変数) は触らない。
fire = 環境変数 CLAUDE_CODE_ENTRYPOINT が claude-desktop / claude-desktop-3p。 desktop は engine を SDK の形で動かすので、 hook は
  返事 1 つにつき書き終えた後に全文で 1 回呼ばれ、 差し替えた文が書き終えた返事として desktop に届く。 書いている途中の小分けの
  文は元のまま届く (実測 = 埋込 engine 2.1.317 を同じ flag で動かした出力)。 画面の試験 (desktop app 4.23118.0) = 書き終えた返事は
  差し替えた文で描かれ、 session を離れて戻ってもそのまま (正本 = conventions/chat-math-rendering.md#code-tab-display-fix)。
  CHAT_MATH_DISPLAY_FIX_ANY=1 なら entrypoint を問わない (試験用)。
挙動: 書き換えたときだけ hookSpecificOutput.displayContent を出す。 走るたびに session ごとの印を $TMPDIR/chat-math-display-fix/
  に置く (Stop の hook が「この session では画面に出たのは直した文」 と読む)。 直した数を計器 (~/.claude/state/chat-math-events.jsonl)
  に足す。 対話の端末 (行のまとまりごとに呼ばれる) では、 code block と `$$` block の開閉を返事の id ごとの一時 file で引き継ぐ。
  fail-open: 入力の壊れ・部品の読み込みの失敗・例外は何も出さない (= 元の文が出る)。
部品 = 同じ dir の chat-math-render-guard.py (~/.claude/hooks の symlink でも、 Windows の copy でも、 この file の隣に在る)。
test = hooks/chat-math-display-fix.test.sh
"""
from __future__ import annotations

import os
import sys

DESKTOP_ENTRYPOINTS = ("claude-desktop", "claude-desktop-3p")


def _load_guard():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.path.dirname(os.path.realpath(__file__))):
        p = os.path.join(d, "chat-math-render-guard.py")
        if os.path.isfile(p):
            spec = importlib.util.spec_from_file_location("chat_math_render_guard", p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    return None


def _state_path(base: str, key: str, guard) -> str | None:
    if not isinstance(key, str) or not guard.SESSION_ID_OK.fullmatch(key):
        return None
    return os.path.join(base, key)


def main() -> int:
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT") not in DESKTOP_ENTRYPOINTS and not os.environ.get("CHAT_MATH_DISPLAY_FIX_ANY"):
        return 0
    import json
    import tempfile
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or not isinstance(payload.get("delta"), str):
        return 0
    guard = _load_guard()
    if guard is None:
        return 0
    delta = payload["delta"]
    sid = payload.get("session_id") if isinstance(payload.get("session_id"), str) else ""
    base = os.path.join(tempfile.gettempdir(), "chat-math-display-fix")
    try:
        os.makedirs(base, exist_ok=True)
        marker = guard.display_marker_path(sid)
        if marker:
            with open(marker, "w", encoding="utf-8") as f:
                f.write("1")
    except Exception:
        pass
    final = payload.get("final") is not False
    index = payload.get("index") if isinstance(payload.get("index"), int) else 0
    mid = payload.get("message_id") if isinstance(payload.get("message_id"), str) else ""
    state_file = _state_path(base, "msg-" + mid, guard) if mid else None
    state = None
    if index > 0 and state_file and os.path.isfile(state_file):
        try:
            with open(state_file, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = None
    try:
        fixed, fixes, _, new_state = guard.fix_text(delta, state)
    except Exception:
        return 0
    try:
        if state_file:
            if final:
                if os.path.exists(state_file):
                    os.remove(state_file)
            else:
                with open(state_file, "w", encoding="utf-8") as f:
                    json.dump(new_state, f)
    except Exception:
        pass
    if fixes:
        guard.record_event(sid, "display_fix", len(fixes))
    if fixed != delta:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "MessageDisplay", "displayContent": fixed}},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
