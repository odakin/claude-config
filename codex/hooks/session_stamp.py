#!/usr/bin/env python3
"""Render a Codex conversation-start stamp with explicit product identity."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import sys


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from session_provenance_cache import SAFE_SESSION, resolve_codex_metadata  # noqa: E402


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
    metadata = resolve_codex_metadata(session_id, event, environment) if session_id else {}
    model = metadata.get("model", "unknown")
    effort = metadata.get("effort", "unknown")

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
