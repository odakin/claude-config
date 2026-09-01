#!/usr/bin/env python3
"""Codex PreToolUse guard for Tier-A structural leaks in public repositories."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ABS_PATH_RE = re.compile(r"/Users/[a-z][a-z0-9_-]*")
IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
TOKEN_RE = re.compile(r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{30,}")
DISCORD_RE = re.compile(r"<@&?\d{17,20}>")
PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
EMAIL_ALLOWLIST = {"noreply@anthropic.com", "noreply@github.com", "support@github.com"}


def read_event() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def patch_text(tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    candidate = tool_input.get("command", tool_input.get("patch", ""))
    if not isinstance(candidate, str):
        return ""
    if "*** Begin Patch" not in candidate:
        return candidate
    added = [
        line[1:]
        for line in candidate.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    return "\n".join(added)


def enclosing_repo(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def target_repositories(command: str, cwd: str) -> set[Path]:
    base = Path(cwd or ".").resolve()
    targets = PATCH_PATH_RE.findall(command)
    paths = [Path(target) if Path(target).is_absolute() else base / target for target in targets]
    if not paths:
        paths = [base]
    return {repo for path in paths if (repo := enclosing_repo(path.resolve())) is not None}


def public_repository(command: str, cwd: str) -> bool:
    return any((repo / ".claude" / "public-repo.marker").is_file() for repo in target_repositories(command, cwd))


def public_hits(text: str) -> list[str]:
    hits: list[str] = []
    if any(email.lower() not in EMAIL_ALLOWLIST for email in EMAIL_RE.findall(text)):
        hits.append("email")
    if ABS_PATH_RE.search(text):
        hits.append("absolute macOS path")
    if TOKEN_RE.search(text):
        hits.append("token prefix")
    if DISCORD_RE.search(text):
        hits.append("Discord identifier")
    for value in IPV4_RE.findall(text):
        try:
            octets = [int(part) for part in value.split(".")]
        except ValueError:
            continue
        if any(part > 255 for part in octets):
            continue
        first, second = octets[:2]
        private_or_local = (
            value in {"0.0.0.0", "255.255.255.255"}
            or first in {10, 127}
            or (first == 172 and 16 <= second <= 31)
            or (first == 192 and second == 168)
            or (first == 169 and second == 254)
        )
        if not private_or_local:
            hits.append("public IPv4 address")
            break
    return hits


def deny(hits: list[str]) -> None:
    categories = ", ".join(hits)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Public-repository edit blocked by the structural leak guard "
                f"({categories}). Replace the value with a safe placeholder or "
                "keep it in an explicitly scoped private location. Git-side leak "
                "checks remain the authoritative backstop."
            ),
        }
    }
    print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    event = read_event()
    if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "apply_patch":
        return 0
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    command = tool_input.get("command", tool_input.get("patch", ""))
    if not isinstance(command, str) or not public_repository(command, str(event.get("cwd", ""))):
        return 0
    hits = public_hits(patch_text(tool_input))
    if hits:
        deny(hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
