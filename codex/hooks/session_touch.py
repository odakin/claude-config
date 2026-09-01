#!/usr/bin/env python3
"""Track Codex apply_patch work and nudge about unintended dirty worktrees."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def read_event() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def state_dir() -> Path:
    value = os.environ.get("CODEX_SESSION_TOUCH_STATE_DIR")
    return Path(value) if value else Path.home() / ".codex" / "state" / "claude-config-session-touch"


def state_key(event: dict[str, Any]) -> str:
    session_id = str(event.get("session_id", ""))
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def git_root(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    root = result.stdout.strip()
    return root or None


def emit_stop(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def track(event: dict[str, Any]) -> int:
    if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") != "apply_patch":
        return 0
    root = git_root(str(event.get("cwd", "")))
    if not root:
        return 0
    directory = state_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        touched = directory / f"{state_key(event)}.repos"
        existing = set(touched.read_text(encoding="utf-8").splitlines()) if touched.exists() else set()
        if root not in existing:
            with touched.open("a", encoding="utf-8") as handle:
                handle.write(f"{root}\n")
    except OSError:
        pass
    return 0


def dirty_count(root: str) -> int:
    try:
        result = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return 0
    return len(result.stdout.splitlines())


def nudge(event: dict[str, Any]) -> int:
    if event.get("hook_event_name") != "Stop" or event.get("stop_hook_active") is True:
        emit_stop({})
        return 0
    directory = state_dir()
    touched = directory / f"{state_key(event)}.repos"
    if not touched.is_file():
        emit_stop({})
        return 0
    try:
        roots = [line for line in touched.read_text(encoding="utf-8").splitlines() if line]
    except OSError:
        emit_stop({})
        return 0
    dirty = [(root, dirty_count(root)) for root in roots]
    dirty = [(root, count) for root, count in dirty if count]
    snapshot = "\n".join(f"{root}\t{count}" for root, count in dirty)
    marker = directory / f"{state_key(event)}.nudge"
    try:
        if snapshot and marker.is_file() and marker.read_text(encoding="utf-8") == snapshot:
            emit_stop({})
            return 0
        if snapshot:
            marker.write_text(snapshot, encoding="utf-8")
    except OSError:
        pass
    if not dirty:
        emit_stop({})
        return 0
    listing = "; ".join(f"{root} ({count} dirty file(s))" for root, count in dirty)
    emit_stop(
        {
            "systemMessage": (
                "[claude-config] This session edited a repository that is still dirty: "
                f"{listing}. Review it and commit only when that is within the requested workflow; "
                "do not leave unintended worktree state for another session to pick up."
            )
        }
    )
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"track", "nudge"}:
        return 2
    event = read_event()
    return track(event) if sys.argv[1] == "track" else nudge(event)


if __name__ == "__main__":
    raise SystemExit(main())
