#!/usr/bin/env python3
"""Inject a short, source-of-truth reminder at Codex session boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from session_provenance_cache import SAFE_SESSION, resolve_codex_metadata  # noqa: E402
from session_stamp import build_stamp, worker_host  # noqa: E402


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
        return 0
    source = str(event.get("source", "startup"))
    host = worker_host()
    session_id = str(event.get("session_id", ""))
    metadata = resolve_codex_metadata(session_id, event)
    model = metadata.get("model", "unknown")
    effort = metadata.get("effort", "unknown")
    if SAFE_SESSION.fullmatch(session_id):
        provenance_context = (
            "For a Codex-origin Git commit, ensure the managed prepare-commit-msg hook "
            f"is installed; this task's provenance is codex:{session_id}, model={model}, "
            f"effort={effort}. If the shell does not propagate these values to Git, prefix "
            f"that commit with CLAUDE_CONFIG_AGENT_SESSION=codex:{session_id}, "
            f"CLAUDE_CONFIG_AGENT_MODEL={model}, and CLAUDE_CONFIG_AGENT_EFFORT={effort}; "
            "keep unknown literal rather than inventing a value. "
        )
    else:
        provenance_context = (
            "Before a Codex-origin Git commit, ensure the managed Agent-Session "
            "prepare-commit-msg hook is installed; no valid session id was supplied to "
            "this SessionStart hook, so do not fabricate one. "
        )
    if source in {"startup", "resume", "clear"}:
        stamp_context = (
            "The first user-visible reply after this session boundary must begin, before "
            "any other text, with the exact one-line identity stamp between these newline "
            "boundaries:\n"
            f"{build_stamp(event)}\n"
            "Keep every field, including unknown; never replace an "
            "unknown account or surface with a guess. "
        )
    else:
        stamp_context = ""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "This is a session or compaction boundary. Before acting, re-read the "
                "nearest project AGENTS.md or CLAUDE.md and SESSION.md when present. "
                f"{stamp_context}"
                f"{provenance_context}"
                f"The worker host for this session is {host}. A title, prior message, or "
                "report from another host is only an observation: before claiming or acting "
                "on a machine-local fact, verify it on this host with hostname and the "
                "relevant audit, then state the checked host, time, and scope. "
                "At handoff, SESSION.md must show the current work, stopping point, next action, "
                "and direct pointers to owning records; no durable records or separate closure report. "
                "Follow CONVENTIONS.md#auto-update-protocol before finishing. "
                "Keep durable facts in their source-of-truth files, perform ordinary "
                "safe local work autonomously, and do not request step-by-step confirmation."
            ),
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
