#!/usr/bin/env python3
"""Show the board's pending threads at a Codex session start (Codex adapter of ai-collaboration's board-session-start.py).

Claude sessions get the board's actionable threads at session start from a SessionStart hook; a Codex session had only
an instruction to read the board, which depends on the model following it. This adapter runs the same engine
(`<workspace>/ai-collaboration/board/board-session-start.py`, layer 1, cloned next to claude-config) on the local
checkouts (`--no-sync`: the hook must stay fast, and the Codex sandbox has no network for the task anyway) and passes
on only `hookSpecificOutput.additionalContext`, the field the other Codex SessionStart adapters already use.

Silent when: the event is not a session start (startup / resume / clear), the cwd is outside the workspace that holds
claude-config (a sealed review sandbox lives outside it; the engine also refuses inside one), the engine is absent, it
prints nothing (no actionable thread), or anything fails (fail-open). Reads only.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

CONFIG_ROOT = Path(__file__).resolve().parent.parent.parent
WORKSPACE = CONFIG_ROOT.parent
ENGINE = WORKSPACE / "ai-collaboration" / "board" / "board-session-start.py"
TIMEOUT = 8


def inside_workspace(cwd: str) -> bool:
    try:
        path = Path(cwd).resolve()
    except (OSError, RuntimeError):
        return False
    return path == WORKSPACE or WORKSPACE in path.parents


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw or "{}")
    except (OSError, ValueError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
        return 0
    if str(event.get("source", "startup")) not in {"startup", "resume", "clear"}:
        return 0
    if not inside_workspace(str(event.get("cwd") or "")) or not ENGINE.is_file():
        return 0
    try:
        proc = subprocess.run([sys.executable, str(ENGINE), "--no-sync", "--timeout", str(TIMEOUT - 2)],
                              input=raw, capture_output=True, text=True, timeout=TIMEOUT)
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0
    specific = (payload or {}).get("hookSpecificOutput") if isinstance(payload, dict) else None
    if not isinstance(specific, dict) or not specific.get("additionalContext"):
        return 0
    context = (specific["additionalContext"] + "\n(Codex: 自分の番の依頼は inbox --agent codex --session $CODEX_THREAD_ID で読む。"
               " --sync と投稿は network が要る = 承認を経る)")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
