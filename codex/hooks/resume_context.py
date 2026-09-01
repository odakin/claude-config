#!/usr/bin/env python3
"""Inject a short, source-of-truth reminder at Codex session boundaries."""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
        return 0
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "This is a session or compaction boundary. Before acting, re-read the "
                "nearest project AGENTS.md or CLAUDE.md and SESSION.md when present. "
                "Keep durable facts in their source-of-truth files, perform ordinary "
                "safe local work autonomously, and do not request step-by-step confirmation."
            ),
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
