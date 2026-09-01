#!/usr/bin/env python3
"""Inject a short, source-of-truth reminder at Codex session boundaries."""

from __future__ import annotations

import json
import socket
import sys


def worker_host() -> str:
    """Return the local hook process's short hostname without failing a start hook."""
    try:
        return socket.gethostname().split(".")[0] or "unknown-host"
    except OSError:
        return "unknown-host"


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
        return 0
    host = worker_host()
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "This is a session or compaction boundary. Before acting, re-read the "
                "nearest project AGENTS.md or CLAUDE.md and SESSION.md when present. "
                f"The worker host for this session is {host}. A title, prior message, or "
                "report from another host is only an observation: before claiming or acting "
                "on a machine-local fact, verify it on this host with hostname and the "
                "relevant audit, then state the checked host, time, and scope. "
                "Keep durable facts in their source-of-truth files, perform ordinary "
                "safe local work autonomously, and do not request step-by-step confirmation."
            ),
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
