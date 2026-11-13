#!/usr/bin/env python3
"""Surface accepted local workers from the existing close checker without dispatching work."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
THREAD_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
EVENT_ID = re.compile(r"\d{8}T\d{6}Z-[a-z0-9][a-z0-9-]{5,63}")


def board_roots(workspace):
    if configured := os.environ.get("CODEX_THREAD_CLOSE_BOARD_ROOTS"):
        return configured.split(os.pathsep)
    engine = workspace / "ai-collaboration" / "board"
    if not (engine / "board_config.py").is_file():
        return []
    sys.path.insert(0, str(engine))
    try:
        from board_config import discover
        return [str(row["root"]) for row in discover(workspace)
                if (row["config"] or {}).get("audience") == "owner"]
    finally:
        sys.path.remove(str(engine))


def observation(event, checker, runner=subprocess.run, select_roots=board_roots):
    kind = event.get("hook_event_name")
    if kind not in {"SessionStart", "Stop"} or event.get("stop_hook_active") is True:
        return {}
    if kind == "SessionStart" and event.get("source") != "resume":
        return {}
    parent = str(event.get("session_id") or "")
    cwd = event.get("cwd")
    if not cwd or not THREAD_ID.fullmatch(parent):
        return {}
    workspace = checker.parent.parent.parent.resolve()
    current = Path(cwd).resolve()
    if not current.is_relative_to(workspace):
        return {}
    for directory in (current, *current.parents):
        for name in ("AGENTS.md", "CLAUDE.md"):
            try:
                with (directory / name).open(encoding="utf-8") as source:
                    if source.read(128).lstrip().startswith("# Isolated"):
                        return {}
            except FileNotFoundError:
                continue
        if directory == workspace:
            break
    roots = select_roots(workspace)
    if not roots:
        return {}
    argv = [sys.executable, "-B", str(checker), "parent", parent, "--json"]
    for root in roots:
        argv.extend(("--board-root", root))
    process = runner(argv,
                     check=True, capture_output=True, text=True, timeout=8)
    rows = json.loads(process.stdout)
    eligible = set()
    for row in rows:
        check = row.get("check") or {}
        thread, receipt = row.get("thread", ""), row.get("acceptance", "")
        if (not row.get("error") and check.get("wrap_only") and check.get("wrap") in {"missing", "stale"}
                and THREAD_ID.fullmatch(thread) and EVENT_ID.fullmatch(receipt)):
            eligible.add((thread, receipt))
    if not eligible:
        return {}
    matches = ", ".join(f"{thread} ({receipt})" for thread, receipt in sorted(eligible)[:5])
    remaining = f" and {len(eligible) - 5} more" if len(eligible) > 5 else ""
    message = (f"Accepted workers to recheck for wrap: {matches}{remaining}. "
               "Sync the board and check these workers before assigning another task or requesting wrap.")
    if kind == "Stop":
        return {"systemMessage": message}
    return {"hookSpecificOutput": {"hookEventName": kind, "additionalContext": message}}


if __name__ == "__main__":
    try:
        payload = observation(json.load(sys.stdin), ROOT / "scripts" / "codex-thread-close.py")
        if payload:
            print(json.dumps(payload))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        pass
