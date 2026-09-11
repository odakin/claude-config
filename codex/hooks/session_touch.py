#!/usr/bin/env python3
"""Track repositories touched by Codex and enforce the completion Git gate.

This is a turn-end forcing function, not an auto-commit or auto-push engine.
PreToolUse captures repository baselines before Bash/apply_patch work. Stop
then checks repositories whose state changed, compares local HEAD with the
configured upstream's live remote head, and asks Codex for one continuation
when unresolved Git state remains.

Semantic rule: CONVENTIONS.md#completion-git-gate.
Codex coverage: codex/PARITY.md#completion-git-gate-hook.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PRUNE_AGE_SECONDS = 30 * 24 * 60 * 60
PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
GIT_COMMIT_RE = re.compile(r"(?:^|[;&|]\s*|\s)git(?:\s+-C\s+\S+)?\s+commit(?:\s|$)")
GIT_PUSH_RE = re.compile(r"(?:^|[;&|]\s*|\s)git(?:\s+-C\s+\S+)?\s+push(?:\s|$)")


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


def state_path(event: dict[str, Any]) -> Path:
    return state_dir() / f"{state_key(event)}.json"


def run_git(root: str | Path, *args: str, timeout: int = 8) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_root(path: Path) -> Path | None:
    candidate = path if path.is_dir() else path.parent
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    result = run_git(candidate, "rev-parse", "--show-toplevel", timeout=3)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return Path(value) if value else None


def command_text(event: dict[str, Any]) -> str:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    value = tool_input.get("command", tool_input.get("patch", ""))
    return value if isinstance(value, str) else ""


def command_paths(command: str, cwd: Path) -> set[Path]:
    paths: set[Path] = set()
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens[:-1]):
        if token in {"-C", "cd"}:
            value = Path(tokens[index + 1])
            paths.add(value if value.is_absolute() else cwd / value)
    return paths


def target_repositories(event: dict[str, Any]) -> set[Path]:
    cwd = Path(str(event.get("cwd", "."))).resolve()
    tool_input = event.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("workdir"), str):
        cwd = Path(tool_input["workdir"]).resolve()
    command = command_text(event)
    paths: set[Path] = {cwd}
    if event.get("tool_name") == "apply_patch":
        for target in PATCH_PATH_RE.findall(command):
            path = Path(target)
            paths.add(path if path.is_absolute() else cwd / path)
    elif event.get("tool_name") == "Bash":
        paths.update(command_paths(command, cwd))
    return {root for path in paths if (root := git_root(path.resolve())) is not None}


def repo_signature(root: Path) -> dict[str, Any] | None:
    head = run_git(root, "rev-parse", "HEAD", timeout=3)
    status = run_git(root, "status", "--porcelain=v1", "--untracked-files=all", timeout=3)
    if head is None or status is None or head.returncode != 0 or status.returncode != 0:
        return None
    porcelain = status.stdout
    return {
        "head": head.stdout.strip(),
        "status_hash": hashlib.sha256(porcelain.encode("utf-8")).hexdigest(),
        "dirty_count": len(porcelain.splitlines()),
    }


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "repos": {}}
    if not isinstance(value, dict) or not isinstance(value.get("repos"), dict):
        return {"version": 1, "repos": {}}
    return value


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")


def prune_stale_state(directory: Path) -> None:
    cutoff = time.time() - PRUNE_AGE_SECONDS
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for path in entries:
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def track(event: dict[str, Any]) -> int:
    if event.get("hook_event_name") not in {"PreToolUse", "PostToolUse"}:
        return 0
    if event.get("tool_name") not in {"Bash", "apply_patch"}:
        return 0
    roots = target_repositories(event)
    if not roots:
        return 0
    before = event.get("hook_event_name") == "PreToolUse"
    command = command_text(event)
    split_commit = bool(GIT_COMMIT_RE.search(command) and not GIT_PUSH_RE.search(command))
    directory = state_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        prune_stale_state(directory)
        path = state_path(event)
        state = load_state(path)
        repos = state["repos"]
        for root in roots:
            key = str(root)
            entry = repos.get(key)
            if not isinstance(entry, dict):
                signature = repo_signature(root)
                if signature is None:
                    continue
                entry = {
                    "baseline": signature,
                    "post_only_fallback": not before,
                    "commit_without_push": False,
                }
                repos[key] = entry
            if split_commit:
                entry["commit_without_push"] = True
        save_state(path, state)
    except OSError:
        pass
    return 0


def upstream_info(root: Path) -> tuple[str, str, str] | None:
    branch_result = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD", timeout=3)
    if branch_result is None or branch_result.returncode != 0:
        return None
    branch = branch_result.stdout.strip()
    remote_result = run_git(root, "config", "--get", f"branch.{branch}.remote", timeout=3)
    merge_result = run_git(root, "config", "--get", f"branch.{branch}.merge", timeout=3)
    if (
        remote_result is None
        or merge_result is None
        or remote_result.returncode != 0
        or merge_result.returncode != 0
    ):
        return None
    return branch, remote_result.stdout.strip(), merge_result.stdout.strip()


def live_remote_head(root: Path, remote: str, merge_ref: str) -> tuple[str | None, str | None]:
    result = run_git(root, "ls-remote", "--exit-code", remote, merge_ref, timeout=8)
    if result is None:
        return None, "remote query timed out or could not start"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return None, detail[-1] if detail else f"git ls-remote exited {result.returncode}"
    fields = result.stdout.split()
    if not fields:
        return None, f"remote ref {merge_ref} was not found"
    return fields[0], None


def tracking_counts(root: Path) -> tuple[int, int] | None:
    result = run_git(root, "rev-list", "--left-right", "--count", "HEAD...@{u}", timeout=3)
    if result is None or result.returncode != 0:
        return None
    try:
        ahead, behind = (int(value) for value in result.stdout.split())
    except (TypeError, ValueError):
        return None
    return ahead, behind


def remote_count(root: Path) -> int:
    result = run_git(root, "remote", timeout=3)
    if result is None or result.returncode != 0:
        return 0
    return len([line for line in result.stdout.splitlines() if line])


def repo_issues(root: Path, entry: dict[str, Any]) -> list[str]:
    current = repo_signature(root)
    baseline = entry.get("baseline")
    if current is None or not isinstance(baseline, dict):
        return [f"{root}: Git state could not be read"]
    changed = (
        current.get("head") != baseline.get("head")
        or current.get("status_hash") != baseline.get("status_hash")
        or bool(entry.get("post_only_fallback"))
        or bool(entry.get("commit_without_push"))
    )
    if not changed:
        return []

    issues: list[str] = []
    if current.get("status_hash") != baseline.get("status_hash") and current.get("dirty_count"):
        issues.append(f"{root}: dirty ({current['dirty_count']} path(s) differ from the pre-work baseline)")

    remotes = remote_count(root)
    upstream = upstream_info(root)
    if remotes == 0:
        return issues
    if upstream is None:
        issues.append(f"{root}: remote exists but the current branch has no configured upstream")
        return issues
    branch, remote, merge_ref = upstream
    remote_head, remote_error = live_remote_head(root, remote, merge_ref)
    if remote_error:
        issues.append(f"{root}: live remote head could not be verified ({remote_error})")
        return issues
    local_head = str(current.get("head", ""))
    if local_head == remote_head:
        return issues

    counts = tracking_counts(root)
    if counts is None:
        relation = "local and live remote heads differ; fetch is required to classify direction"
    else:
        ahead, behind = counts
        relation = f"ahead={ahead}, behind={behind} against the local tracking ref (which may be stale)"
    split = " commit and push were split into separate calls;" if entry.get("commit_without_push") else ""
    issues.append(
        f"{root}: local HEAD {local_head[:12]} != {remote}/{branch} {str(remote_head)[:12]};"
        f"{split} {relation}"
    )
    return issues


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def nudge(event: dict[str, Any]) -> int:
    if event.get("hook_event_name") != "Stop":
        return 0
    path = state_path(event)
    state = load_state(path)
    repos = state.get("repos", {})
    issues: list[str] = []
    for root_value, entry in repos.items():
        if isinstance(root_value, str) and isinstance(entry, dict):
            issues.extend(repo_issues(Path(root_value), entry))
    if not issues:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        emit({})
        return 0

    detail = " | ".join(issues)
    reason = (
        "Completion Git gate found unresolved repository state: "
        f"{detail}. Before reporting completion, inspect dirty/ahead/behind state, "
        "commit the authorized task paths, and push in the same command chain; then "
        "verify local HEAD equals the live remote branch head. If a documented exception "
        "applies, do not claim completion silently: state the exact repository, residual "
        "state, and reason. See CONVENTIONS.md#completion-git-gate."
    )
    if event.get("stop_hook_active") is True:
        emit({"systemMessage": reason + " Stop hooks resume a turn at most once; unresolved state remains."})
    else:
        emit({"decision": "block", "reason": reason})
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"track", "nudge"}:
        return 2
    event = read_event()
    return track(event) if sys.argv[1] == "track" else nudge(event)


if __name__ == "__main__":
    raise SystemExit(main())
