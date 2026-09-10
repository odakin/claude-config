#!/usr/bin/env python3
"""Cache hook metadata and resolve current Codex thread provenance read-only."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
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


def codex_state_databases(environment: dict[str, str] | None = None) -> list[Path]:
    environment = environment or dict(os.environ)
    configured_root = environment.get("CODEX_SQLITE_HOME") or environment.get("CODEX_HOME")
    root = Path(configured_root) if configured_root else Path.home() / ".codex"
    if root.is_file():
        return [root]
    try:
        databases = list(root.glob("state_*.sqlite"))
    except OSError:
        return []

    def database_version(path: Path) -> int:
        match = re.fullmatch(r"state_(\d+)\.sqlite", path.name)
        return int(match.group(1)) if match else -1

    databases.sort(key=database_version, reverse=True)
    development_database = root / "sqlite" / "codex-dev.db"
    if development_database.is_file():
        databases.append(development_database)
    return databases


def codex_thread_metadata(
    session_id: str,
    environment: dict[str, str] | None = None,
) -> dict[str, str]:
    """Read only the exact current-thread row from Codex's local state."""
    if not SAFE_SESSION.fullmatch(session_id):
        return {}
    for database in codex_state_databases(environment):
        try:
            connection = sqlite3.connect(
                database.resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=0.2,
            )
            try:
                connection.execute("PRAGMA query_only = ON")
                columns = {
                    str(row[1]) for row in connection.execute("PRAGMA table_info(threads)")
                }
                selected = [name for name in ("model", "reasoning_effort") if name in columns]
                if "model" not in selected:
                    continue
                row = connection.execute(
                    f"SELECT {', '.join(selected)} FROM threads WHERE id = ?",
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            continue
        if row is None:
            continue
        raw = dict(zip(selected, row))
        values: dict[str, str] = {}
        model = raw.get("model")
        if isinstance(model, str) and model != "unknown" and SAFE_MODEL.fullmatch(model):
            values["model"] = model
        effort = raw.get("reasoning_effort")
        if isinstance(effort, str) and effort != "unknown" and SAFE_EFFORT.fullmatch(effort):
            values["effort"] = effort
        if values:
            return values
    return {}


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
        if isinstance(model, str) and model != "unknown" and SAFE_MODEL.fullmatch(model):
            values["model"] = model
        effort = effort_from_event(event)
        if effort:
            values["effort"] = effort
        if agent == "codex":
            for key, value in codex_thread_metadata(session_id).items():
                if not values.get(key) or values[key] == "unknown":
                    values[key] = value
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


def cli_main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(arguments) != 2 or arguments[0] != "--resolve-codex":
        print("usage: session_provenance_cache.py --resolve-codex <session-id>", file=sys.stderr)
        return 2
    for key, value in codex_thread_metadata(arguments[1]).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
