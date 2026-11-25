#!/usr/bin/env python3
"""Require a recorded same-turn check before a native internal Codex launch."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

TOOLS = {
    "Agent", "spawn_agent", "collaboration.spawn_agent", "collaboration__spawn_agent",
}
BOARD_HEADER = re.compile(r"Codex same-turn board check ([0-9]{8}T[0-9]{6}Z-codex-[a-f0-9]{6})\.")
PROJECT_HEADER = "Codex same-turn project check."
ENABLE_FILE = "recorded-internal-checks.on"
LIMIT = 65536
REASON = (
    "内部の子に渡すのは、同じターンで答えを使う小さな照合だけです。"
    "掲示板で依頼を --surface agent と理由付きで記録し、出力された起動文の全文を渡してください。"
    "掲示板のない作業にはリポジトリ内の照合記録を使います。"
    "成果物を持つ仕事は掲示板から可視窓を起こしてください。"
)


def git_value(root, *args):
    value = subprocess.run(
        ["git", "-C", str(root), "rev-parse", *args],
        capture_output=True, text=True, timeout=2, check=True,
    ).stdout.strip()
    return value


def read_record(path):
    with path.open("rb") as stream:
        payload = stream.read(LIMIT + 1)
    if len(payload) > LIMIT:
        raise ValueError("record exceeds the protocol limit")
    return payload


def board_record_matches(prompt, lines, session):
    match = BOARD_HEADER.fullmatch(lines[0])
    if not match or len(lines) < 2 or not lines[1].startswith("Board root: "):
        return False
    root = Path(lines[1].removeprefix("Board root: "))
    if not root.is_absolute() or not (root / "board.json").is_file():
        return False
    request = match.group(1)
    if (root / ".local").is_dir() and not git_value(root, "--show-prefix"):
        directory = root / ".local/outbox"
    else:
        common = Path(git_value(root, "--path-format=absolute", "--git-common-dir"))
        prefix = git_value(root, "--show-prefix").rstrip("/")
        directory = common / "board-outbox" / (prefix.replace("/", "_") or "root")
    record = json.loads(read_record(directory / f"{request}.launch.json"))
    return (
        isinstance(record, dict)
        and record.get("request_id") == request
        and record.get("surface") == "agent"
        and record.get("requester") == session
        and record.get("handoff_sha256") == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    )


def project_record_matches(prompt, lines, session, cwd):
    if len(lines) < 5 or lines[0] != PROJECT_HEADER or not lines[1].startswith("Record: "):
        return False
    if lines[2] != "Parent session: " + session or not lines[3].startswith("Reason: "):
        return False
    record_path = Path(lines[1].removeprefix("Record: "))
    if record_path.is_absolute() or not lines[3].removeprefix("Reason: ").strip():
        return False
    root = Path(git_value(cwd, "--show-toplevel")).resolve()
    if (root / "board.json").is_file() or (root / "board/board.json").is_file():
        return False
    target = (root / record_path).resolve()
    return root in target.parents and read_record(target) == prompt.encode("utf-8")


def handle(event, codex_home):
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
        return None
    if event.get("tool_name") not in TOOLS or not (codex_home / ENABLE_FILE).is_file():
        return None
    inputs = event.get("tool_input")
    prompt = inputs.get("message") if isinstance(inputs, dict) else None
    session, cwd = event.get("session_id"), event.get("cwd")
    if isinstance(prompt, str) and isinstance(session, str) and session:
        lines = prompt.splitlines()
        try:
            if lines and (
                board_record_matches(prompt, lines, session)
                or isinstance(cwd, str) and cwd and project_record_matches(prompt, lines, session, Path(cwd))
            ):
                return None
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": REASON,
    }}


def main():
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    result = handle(json.load(sys.stdin), home)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
