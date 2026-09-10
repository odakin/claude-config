#!/usr/bin/env python3
"""Cache hook-supplied session model/effort metadata for the Git provenance trailer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile


SAFE_SESSION = re.compile(r"^[A-Za-z0-9_-]+$")
SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+\[\]-]*$")
SAFE_EFFORT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def effort_from_event(event: dict[str, object]) -> str:
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


def state_directory(agent: str) -> Path:
    override = os.environ.get("CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR")
    if override:
        return Path(override)
    if agent == "codex":
        root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    else:
        root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return root / "state" / "session-provenance"


def read_existing(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"model", "effort"}:
                values[key] = value
    except OSError:
        pass
    return values


def main(agent: str) -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            return 0
        session_id = event.get("session_id")
        if not isinstance(session_id, str) or not SAFE_SESSION.fullmatch(session_id):
            return 0

        state_dir = state_directory(agent)
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = state_dir / f"{session_id}.env"
        existing = read_existing(target)
        values = dict(existing)

        model = event.get("model")
        if isinstance(model, str) and SAFE_MODEL.fullmatch(model):
            values["model"] = model
        effort = effort_from_event(event)
        if effort:
            values["effort"] = effort
        if not values or values == existing:
            return 0

        handle, temporary_name = tempfile.mkstemp(prefix=f".{session_id}.", dir=state_dir)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                for key in ("model", "effort"):
                    if key in values:
                        stream.write(f"{key}={values[key]}\n")
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, target)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    except (OSError, ValueError, TypeError):
        pass
    return 0
