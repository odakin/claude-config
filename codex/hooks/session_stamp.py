#!/usr/bin/env python3
"""Render a Codex conversation-start stamp with explicit product identity."""

from __future__ import annotations

import os
from pathlib import Path
import re
import socket


SAFE_SESSION = re.compile(r"^[A-Za-z0-9_-]+$")
SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+\[\]-]*$")
SAFE_EFFORT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def worker_host() -> str:
    try:
        return socket.gethostname().split(".")[0] or "host unknown"
    except OSError:
        return "host unknown"


def runtime_surface(environment: dict[str, str]) -> str:
    # This app-pipe variable is an observed compatibility signal, not a stable
    # public Codex contract. Absence therefore stays unknown rather than being
    # guessed as CLI.
    return "desktop" if environment.get("CODEX_APP_TOOLS_PIPE_PATH") else "surface unknown"


def event_effort(event: dict[str, object]) -> str:
    value = event.get("effort")
    if isinstance(value, dict):
        value = value.get("level")
    if not isinstance(value, str):
        for key in ("reasoning_effort", "model_reasoning_effort"):
            candidate = event.get(key)
            if isinstance(candidate, str):
                value = candidate
                break
    return value if isinstance(value, str) and SAFE_EFFORT.fullmatch(value) else ""


def cached_metadata(session_id: str, environment: dict[str, str]) -> dict[str, str]:
    override = environment.get("CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR")
    root = Path(override) if override else Path(
        environment.get("CODEX_HOME", str(Path.home() / ".codex"))
    ) / "state" / "session-provenance"
    values: dict[str, str] = {}
    try:
        for line in (root / f"{session_id}.env").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"model", "effort"}:
                values[key] = value
    except OSError:
        pass
    return values


def build_stamp(
    event: dict[str, object] | None = None,
    environment: dict[str, str] | None = None,
) -> str:
    event = event or {}
    environment = environment or dict(os.environ)

    session_value = event.get("session_id")
    if not isinstance(session_value, str) or not SAFE_SESSION.fullmatch(session_value):
        session_value = environment.get("CODEX_SESSION_ID") or environment.get("CODEX_THREAD_ID") or ""
    session_id = session_value if SAFE_SESSION.fullmatch(session_value) else ""
    cache = cached_metadata(session_id, environment) if session_id else {}

    model_value = event.get("model")
    model = model_value if isinstance(model_value, str) else ""
    model = model or environment.get("CLAUDE_CONFIG_AGENT_MODEL", "") or cache.get("model", "")
    if not SAFE_MODEL.fullmatch(model):
        model = "unknown"

    effort = event_effort(event)
    effort = effort or environment.get("CLAUDE_CONFIG_AGENT_EFFORT", "") or cache.get("effort", "")
    if not SAFE_EFFORT.fullmatch(effort):
        effort = "unknown"

    session_short = session_id[:8] if session_id else "unknown"
    return (
        f"🖥 {worker_host()} · Codex {runtime_surface(environment)} · account unknown "
        f"· session {session_short} · model {model} · effort {effort}"
    )


def main() -> int:
    print(build_stamp())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
