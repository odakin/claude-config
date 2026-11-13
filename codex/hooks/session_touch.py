#!/usr/bin/env python3
"""Track repositories touched by Codex and enforce the completion Git gate.

This is a turn-end forcing function, not an auto-commit or auto-push engine.
PreToolUse captures repository baselines before Bash/apply_patch work. Stop
then checks repositories whose state changed, compares local HEAD with the
configured upstream's live remote head, and asks Codex for one continuation
when unresolved Git state remains. The head comparison is skipped when the
upstream is a local non-bare checkout that has the tracked branch checked out
and refuses a push to it (Git's default), because no push can land there; a
review copy cloned from a local working tree is the usual case. Task-created
dirt is still reported.

Semantic rule: CONVENTIONS.md#completion-git-gate.
Codex coverage: codex/PARITY.md#completion-git-gate-hook.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:
    fcntl = None  # Legacy gate still runs where locking is unavailable.

PRUNE_AGE_SECONDS = 30 * 24 * 60 * 60
PATCH_PATH_RE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.MULTILINE)
ACK_RE = re.compile(r"git-gate-ack ([0-9a-f]{64})")
SNAPSHOT_BYTES = 16 * 1024 * 1024
# A simple argv or a chain of simple Git commands only. Shell expansions,
# redirects, variables, and unfamiliar forms cannot establish path ownership.
SHELL_SPECIAL = re.compile(r"[\n\r;&|<>$`*?{}()~#\\]")
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
            errors="surrogateescape",
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


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_stamp(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def literal_rel(root: Path, value: str) -> str:
    """Validate the path without following symlinks into another tree."""
    path = Path(value)
    if path.is_absolute():
        path = path.relative_to(root)
    if not path.parts or any(part in (".", "..", ".git") for part in path.parts):
        raise ValueError("not a literal worktree path")
    full = root / path
    if full.resolve() != full:
        raise ValueError("path has a symlink component")
    return path.as_posix()


def file_snapshot(root: Path, rel: str, remaining: int) -> tuple[list[Any], tuple[int, ...] | None, int]:
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise ValueError("safe file reads are unavailable")
    directories = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    parent = os.open(root, directories)
    try:
        *folders, name = Path(rel).parts
        for folder in folders:
            child = os.open(folder, directories, dir_fd=parent)
            os.close(parent)
            parent = child
        try:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return ["absent"], None, 0
        if not stat.S_ISREG(before.st_mode) or before.st_size > remaining:
            raise ValueError("unsupported or oversized worktree file")
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as fh:
            stamp = file_stamp(before)
            if file_stamp(os.fstat(fh.fileno())) != stamp:
                raise ValueError("file changed while opening")
            contents = fh.read(before.st_size + 1)
            if len(contents) != before.st_size or file_stamp(os.fstat(fh.fileno())) != stamp:
                raise ValueError("file changed while reading")
        return ["regular", stat.S_IMODE(before.st_mode), hashlib.sha256(contents).hexdigest()], stamp, len(contents)
    finally:
        os.close(parent)


def status_output(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "--no-optional-locks", "status", "--porcelain=v2",
             "-z", "--no-renames", "--untracked-files=all"],
            capture_output=True, timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return os.fsdecode(result.stdout) if result.returncode == 0 else None


def clean_gitlink_head(root: Path, rel: str) -> str:
    child = root / literal_rel(root, rel)
    if git_root(child) != child:
        raise ValueError("submodule checkout is unavailable")
    head = run_git(child, "rev-parse", "--verify", "HEAD", timeout=1)
    if (head is None or head.returncode or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", head.stdout.strip())
        or status_output(child) != ""):
        raise ValueError("submodule checkout is not verifiably clean")
    return head.stdout.strip()


def repo_signature(root: Path, *, with_identity: bool = False) -> dict[str, Any] | None:
    head = run_git(root, "rev-parse", "--verify", "HEAD", timeout=1)
    raw = status_output(root)
    if head is None or head.returncode or raw is None:
        return None
    rows = raw.split("\0")[:-1]
    identity = worktree_identity(root) if with_identity and rows else None
    result = {"head": head.stdout.strip(), "status_hash": digest(raw),
              "dirty_count": len(rows), "paths": None}
    paths: dict[str, str] = {}
    stamps: dict[str, tuple[int, ...] | None] = {}
    gitlinks: dict[str, str] = {}
    remaining = SNAPSHOT_BYTES
    try:
        for row in rows:
            # v2 ordinary entries include all HEAD and index modes and blob IDs.
            # A clean submodule checked out at a different commit is readable
            # as Git metadata. Conflicts and dirty submodule contents stay loud.
            if row.startswith("1 "):
                parts = row.split(" ", 8)
                if len(parts) != 9:
                    return result
                meta, name = parts[:8], parts[8]
                if parts[1:6] == [".M", "SC..", "160000", "160000", "160000"] and parts[6] == parts[7]:
                    rel = literal_rel(root, name)
                    if rel != name or rel in paths:
                        return result
                    gitlinks[rel] = clean_gitlink_head(root, rel)
                    paths[rel] = digest([meta, gitlinks[rel]])
                    continue
                if parts[2] != "N..." or any(
                    mode not in {"000000", "100644", "100755"} for mode in parts[3:6]
                ):
                    return result
            elif row.startswith("? "):
                meta, name = ["?"], row[2:]
            else:
                return result
            rel = literal_rel(root, name)
            if rel != name or rel in paths:
                return result
            worktree, stamp, size = file_snapshot(root, rel, remaining)
            remaining -= size
            paths[rel] = digest([meta, worktree])
            stamps[rel] = stamp
        # A changed listing or a file changed while a sibling was hashed makes
        # this snapshot unusable. Always validate HEAD again when there is dirt.
        if rows:
            if status_output(root) != raw:
                return result
            check_head = run_git(root, "rev-parse", "--verify", "HEAD", timeout=1)
            if check_head is None or check_head.returncode or check_head.stdout != head.stdout:
                return result
            for rel, before in stamps.items():
                try:
                    after = file_stamp((root / literal_rel(root, rel)).lstat())
                except FileNotFoundError:
                    after = None
                if before != after:
                    return result
            if any(clean_gitlink_head(root, rel) != oid for rel, oid in gitlinks.items()):
                return result
    except (OSError, RuntimeError, ValueError):
        return result
    result["paths"] = paths
    if gitlinks:
        result["gitlinks"] = {rel: paths[rel] for rel in gitlinks}
    if identity is not None and worktree_identity(root) == identity:
        result["identity"] = identity
    return result


def worktree_identity(root: Path) -> list[Any] | None:
    branch = run_git(root, "symbolic-ref", "--quiet", "HEAD", timeout=1)
    gitdir = run_git(root, "rev-parse", "--absolute-git-dir", timeout=1)
    if branch is None or branch.returncode or gitdir is None or gitdir.returncode:
        return None
    try:
        if git_root(root) != root:
            return None
        git_path = Path(gitdir.stdout.rstrip("\n")).resolve(strict=True)
        git_stat, root_stat = git_path.stat(), root.stat()
        return [str(root), root_stat.st_dev, root_stat.st_ino, str(git_path),
                git_stat.st_dev, git_stat.st_ino, branch.stdout.strip()]
    except (OSError, RuntimeError):
        return None


def git_paths_from_tool(event: dict[str, Any], roots: set[Path]) -> dict[str, set[str]] | None:
    """Paths a supported tool invocation can write, or None when uncertain."""
    command = command_text(event)
    data = event.get("tool_input")
    cwd = Path(str((data.get("workdir") if isinstance(data, dict) else None)
                   or event.get("cwd", "."))).resolve()
    touched: dict[str, set[str]] = {}
    def remember(values: list[str], directory: Path) -> None:
        for value in values:
            if not value or value.startswith(("-", ":")) or SHELL_SPECIAL.search(value):
                raise ValueError("nonliteral path")
            full = directory / value
            root = git_root(full)
            if root is None or root not in roots or full.is_dir():
                raise ValueError("unresolved path")
            touched.setdefault(str(root), set()).add(literal_rel(root, str(full)))
    try:
        if event.get("tool_name") == "apply_patch":
            targets = PATCH_PATH_RE.findall(command)
            if not targets or not command.startswith("*** Begin Patch\n"):
                return None
            remember(targets, cwd)
            return touched
        for component in command.split("&&"):
            if SHELL_SPECIAL.search(component):
                return None
            words = shlex.split(component)
            if not words or words[0] != "git":
                return None
            base = cwd
            if words[1:2] == ["-C"] and len(words) >= 4:
                base = (cwd / words[2]).resolve()
                words = [words[0], *words[3:]]
            verb, *args = words[1:]
            if verb in {"status", "diff", "log", "rev-parse", "ls-remote", "show",
                        "branch", "remote", "fetch", "push"}:
                # branch and remote have mutating forms; only accept their
                # explicit read-only forms here. Checkout changes are unknown.
                if verb == "branch" and args not in ([], ["--show-current"]):
                    return None
                if verb == "remote" and args not in ([], ["-v"]):
                    return None
                if any(arg.startswith(("--ext-diff", "--textconv", "--output",
                                       "--exec", "--receive-pack", "--upload-pack")) for arg in args):
                    return None
            elif verb == "add":
                remember(args[1:] if args[:1] == ["--"] else args, base)
                if not args or args == ["--"]:
                    return None
            elif verb == "commit" and args[:1] == ["-m"] and len(args) >= 2:
                if len(args) > 2:
                    if args[2] != "--" or len(args) < 4:
                        return None
                    remember(args[3:], base)
                else:
                    staged = run_git(base, "diff", "--cached", "--name-only", "--no-renames", "-z", timeout=1)
                    if staged is None or staged.returncode:
                        return None
                    root = git_root(base)
                    if root is None:
                        return None
                    remember(staged.stdout.split("\0")[:-1], root)
            else:
                return None
        return touched
    except (OSError, RuntimeError, ValueError):
        return None


def receipt_manifest(session: str, root: Path, entry: dict[str, Any],
                     current: dict[str, Any]) -> dict[str, Any] | None:
    paths = current.get("paths")
    own_paths = entry.get("own_paths", [])
    baseline = entry.get("baseline")
    identity = current.get("identity")
    if (not session or not isinstance(paths, dict) or not isinstance(own_paths, list)
        or not all(isinstance(p, str) for p in own_paths)
        or not isinstance(baseline, dict) or not isinstance(identity, list)
        or not identity or identity[0] != str(root)):
        return None
    # A legacy tracker has no epoch or per-path history. Bind to its original
    # baseline instead. An explicit owner confirmation is required either way.
    epoch = entry.get("epoch") or digest(baseline)
    day = datetime.datetime.now().astimezone().date().isoformat()
    # A gitlink observation identifies a warning, not reviewed file content.
    if current.get("gitlinks"):
        return None
    eligible = {path: value for path, value in paths.items() if path not in own_paths}
    return ({"session": session, "worktree": identity, "epoch": epoch,
             "day": day, "paths": eligible} if eligible else None)


def acknowledged_paths(session: str, root: Path, entry: dict[str, Any],
                       current: dict[str, Any]) -> set[str]:
    receipt = entry.get("receipt")
    if not isinstance(receipt, dict) or set(receipt) != {"digest", "manifest", "invalidated"}:
        return set()
    stored = receipt["manifest"]
    invalidated = receipt["invalidated"]
    if (not isinstance(stored, dict) or digest(stored) != receipt["digest"]
        or not isinstance(stored.get("paths"), dict) or not isinstance(invalidated, list)
        or not all(isinstance(path, str) for path in invalidated)):
        return set()
    fresh = receipt_manifest(session, root, entry, current)
    keys = ("session", "worktree", "epoch", "day")
    comparable = fresh is not None and all(stored.get(key) == fresh[key] for key in keys)
    unchanged = {path for path, fingerprint in stored["paths"].items()
                 if comparable and fresh["paths"].get(path) == fingerprint and path not in invalidated}
    # Record observed changes, even if bytes later return to the reviewed value.
    receipt["invalidated"] = sorted(set(stored["paths"]) - unchanged)
    return unchanged


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "repos": {}}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("repos"), dict):
        return None
    return value


def save_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def state_lock(path: Path):
    if fcntl is None:
        yield False
        return
    # A separately stored lock remains valid across atomic state replacement.
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield True


def prune_stale_state(directory: Path) -> None:
    cutoff = time.time() - PRUNE_AGE_SECONDS
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for path in entries:
        try:
            if path.suffix == ".json" and path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def track(event: dict[str, Any]) -> int:
    if event.get("hook_event_name") not in {"PreToolUse", "PostToolUse"}:
        return 0
    if event.get("tool_name") not in {"Bash", "apply_patch"}:
        return 0
    roots = target_repositories(event)
    before = event.get("hook_event_name") == "PreToolUse"
    command = command_text(event)
    split_commit = bool(GIT_COMMIT_RE.search(command) and not GIT_PUSH_RE.search(command))
    directory = state_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        prune_stale_state(directory)
        path = state_path(event)
        with state_lock(path) as locked:
            state = load_state(path)
            if state is None:
                return 0
            repos = state["repos"]
            writes = git_paths_from_tool(event, roots) if locked else None
            for root in roots:
                key = str(root)
                entry = repos.get(key)
                if not isinstance(entry, dict):
                    signature = repo_signature(root)
                    entry = {
                        "baseline": signature,
                        "post_only_fallback": not before,
                        "commit_without_push": False,
                        "epoch": secrets.token_hex(16),
                        "unknown_write": not before,
                        "own_paths": [],
                    }
                    repos[key] = entry
                if split_commit:
                    entry["commit_without_push"] = True
            if writes is None:
                # An unresolved tool can write outside its reported cwd.
                for entry in repos.values():
                    if isinstance(entry, dict):
                        entry["unknown_write"] = True
            else:
                for key, names in writes.items():
                    entry = repos[key]
                    own_paths = entry.setdefault("own_paths", [])
                    if isinstance(own_paths, list) and all(isinstance(path, str) for path in own_paths):
                        entry["own_paths"] = sorted(set(own_paths) | names)
                    else:
                        entry["unknown_write"] = True
                        entry["receipt"] = None
            if repos:
                save_state(path, state)
    except OSError:
        pass
    return 0


def review(event: dict[str, Any]) -> int:
    """Print the current candidate for one explicit repo without recording it."""
    session = event.get("session_id")
    requested = event.get("cwd")
    if not isinstance(session, str) or not session or not isinstance(requested, str):
        return 2
    root = git_root(Path(requested).resolve())
    state = load_state(state_path(event))
    entry = state["repos"].get(str(root)) if state is not None else None
    if root is not None and isinstance(entry, dict) and fcntl is not None:
        current = repo_signature(root, with_identity=True)
        manifest = receipt_manifest(session, root, entry, current) if current is not None else None
        if manifest is not None:
            emit({"repository": str(root), "branch": manifest["worktree"][-1],
                  "paths": manifest["paths"],
                  "review": ("Confirm only after checking the exact current diff and verifying that"
                             " every listed path belongs to someone else."),
                  "tracking_incomplete": (entry.get("unknown_write", True)
                                          or not isinstance(entry["baseline"].get("paths"), dict)),
                  "owner_prompt": "git-gate-ack " + digest(manifest)})
            return 0
    print("No reviewable Git gate exception for this repository and session.", file=sys.stderr)
    return 2


def acknowledge(event: dict[str, Any]) -> int:
    """Record an exact manifest only from the native user prompt lifecycle."""
    prompt = event.get("prompt")
    session = event.get("session_id")
    if (event.get("hook_event_name") != "UserPromptSubmit" or not isinstance(prompt, str)
        or not isinstance(session, str) or not session or not (match := ACK_RE.fullmatch(prompt.strip()))):
        return 0
    path = state_path(event)
    found = False
    try:
        with state_lock(path) as locked:
            state = load_state(path)
            matches = []
            for key, entry in state["repos"].items() if locked and state is not None else ():
                if not isinstance(entry, dict):
                    continue
                root = Path(key)
                current = repo_signature(root, with_identity=True)
                manifest = receipt_manifest(session, root, entry, current) if current is not None else None
                if manifest is not None and digest(manifest) == match[1]:
                    matches.append((entry, manifest))
            if len(matches) == 1:
                entry, manifest = matches[0]
                entry["receipt"] = {"digest": match[1], "manifest": manifest, "invalidated": []}
                save_state(path, state)
                found = True
    except OSError:
        pass
    message = ("Recorded the reviewed Git gate state for this session." if found else
               "Git gate acknowledgement did not match a currently reviewable snapshot. No exception recorded.")
    emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": message}})
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


def remote_count(root: Path) -> int | None:
    result = run_git(root, "remote", timeout=3)
    if result is None or result.returncode != 0:
        return None
    return len([line for line in result.stdout.splitlines() if line])


def local_push_target(root: Path, remote: str) -> Path | None:
    """Return the directory a remote's push URL names when it is on this machine."""
    result = run_git(root, "remote", "get-url", "--push", remote, timeout=3)
    if result is None or result.returncode != 0:
        return None
    url = result.stdout.strip()
    if url.startswith("file://"):
        url = url[len("file://"):]
    elif "://" in url or re.match(r"^[^/]+:", url):
        return None
    path = Path(url).expanduser()
    if not path.is_absolute():
        path = root / path
    return path if path.is_dir() else None


def push_refused_by_checkout(root: Path, remote: str, merge_ref: str) -> bool:
    """True when the upstream is a local non-bare checkout whose checked-out branch
    is the push target and which refuses that push, so a push cannot land."""
    target = local_push_target(root, remote)
    if target is None:
        return False
    bare = run_git(target, "rev-parse", "--is-bare-repository", timeout=3)
    if bare is None or bare.returncode != 0 or bare.stdout.strip() != "false":
        return False
    head = run_git(target, "symbolic-ref", "--quiet", "HEAD", timeout=3)
    if head is None or head.returncode != 0 or head.stdout.strip() != merge_ref:
        return False
    deny = run_git(target, "config", "--get", "receive.denyCurrentBranch", timeout=3)
    value = deny.stdout.strip().lower() if deny is not None and deny.returncode == 0 else ""
    return value in ("", "refuse", "true")


def repo_issues(root: Path, entry: dict[str, Any], session: str = "",
                observation: dict[str, Any] | None = None) -> list[str]:
    current = repo_signature(root, with_identity=observation is not None or "receipt" in entry)
    if observation is not None:
        observation["snapshot"] = current
    baseline = entry.get("baseline")
    if current is None or not isinstance(baseline, dict):
        return [f"{root}: Git state could not be read"]
    paths, initial_paths = current.get("paths"), baseline.get("paths")
    if isinstance(paths, dict) and isinstance(initial_paths, dict):
        changed_status = paths != initial_paths
    elif "paths" not in baseline:
        # Preserve version 1's original baseline comparison. Only a fresh,
        # explicitly acknowledged manifest can establish exact path evidence.
        status = run_git(root, "status", "--porcelain=v1", "--untracked-files=all", timeout=1)
        if status is None or status.returncode:
            return [f"{root}: Git state could not be read"]
        changed_status = hashlib.sha256(status.stdout.encode("utf-8", errors="surrogateescape")).hexdigest() != baseline.get("status_hash")
    else:
        changed_status = bool(current.get("dirty_count")) or current.get("status_hash") != baseline.get("status_hash")
    had_receipt = "receipt" in entry
    accepted = acknowledged_paths(session, root, entry, current) if had_receipt else set()
    if observation is not None:
        observation["accepted_paths"] = sorted(accepted)
    if not current.get("dirty_count"):
        entry.pop("receipt", None)
    own_paths = entry.get("own_paths")
    own_dirty = isinstance(paths, dict) and isinstance(own_paths, list) and any(
        isinstance(path, str) and path in paths for path in own_paths
    )
    unresolved_dirt = (changed_status or own_dirty or had_receipt
                       or not isinstance(paths, dict)
                       or bool(current.get("gitlinks"))
                       or bool(entry.get("post_only_fallback")))
    changed = (current.get("head") != baseline.get("head") or changed_status
               or bool(current.get("dirty_count") and unresolved_dirt)
               or bool(entry.get("post_only_fallback")) or bool(entry.get("commit_without_push")))
    if not changed:
        return []
    issues: list[str] = []
    unacknowledged = current.get("dirty_count", 0) - len(accepted)
    if unacknowledged and unresolved_dirt:
        detail = ("exact dirty state could not be read" if not isinstance(paths, dict)
                  else "check which changes belong to this task")
        issues.append(f"{root}: dirty ({unacknowledged} unacknowledged current path(s); {detail})")

    def finish(verified_upstream: tuple[str, str, str] | None = None) -> list[str]:
        if issues or not (accepted or verified_upstream):
            return issues
        latest = repo_signature(root, with_identity=observation is not None or had_receipt)
        if (latest != current or
            (verified_upstream is not None and upstream_info(root) != verified_upstream)):
            if had_receipt:
                acknowledged_paths(session, root, entry, latest or {})
            issues.append(f"{root}: Git state changed during verification; retry the check")
        return issues

    remotes = remote_count(root)
    if remotes is None:
        issues.append(f"{root}: configured remotes could not be read")
        return issues
    if remotes == 0:
        return finish()
    upstream = upstream_info(root)
    if upstream is None:
        issues.append(f"{root}: remote exists but the current branch has no configured upstream")
        return issues
    branch, remote, merge_ref = upstream
    if push_refused_by_checkout(root, remote, merge_ref):
        return finish()
    remote_head, remote_error = live_remote_head(root, remote, merge_ref)
    if remote_error:
        issues.append(f"{root}: live remote head could not be verified ({remote_error})")
        return issues
    local_head = str(current.get("head", ""))
    if local_head == remote_head:
        return finish(upstream)

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


def notice_paths_valid(paths: Any) -> bool:
    if not isinstance(paths, dict):
        return False
    for name, fingerprint in paths.items():
        if (not isinstance(name, str) or not name or "\x00" in name
            or not Path(name).parts or Path(name).is_absolute()
            or Path(name).as_posix() != name or any(p in {".", "..", ".git"} for p in Path(name).parts)
            or not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None):
            return False
    return True


def notice_baseline_valid(baseline: Any, *, legacy_gitlink: bool = False) -> bool:
    if (not isinstance(baseline, dict)
        or not isinstance(baseline.get("head"), str)
        or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", baseline["head"]) is None
        or not isinstance(baseline.get("status_hash"), str)
        or re.fullmatch(r"[0-9a-f]{64}", baseline["status_hash"]) is None
        or type(baseline.get("dirty_count")) is not int or baseline["dirty_count"] < 0):
        return False
    # Older hooks could not snapshot a lone checkout mismatch. On upgrade,
    # deduplicate that verified warning after it has been emitted once.
    if legacy_gitlink and baseline.get("paths") is None and baseline["dirty_count"] == 1:
        return True
    return "paths" not in baseline or (notice_paths_valid(baseline["paths"])
                                      and len(baseline["paths"]) == baseline["dirty_count"])


def notice_receipt_valid(receipt: Any) -> bool:
    if (not isinstance(receipt, dict) or set(receipt) != {"digest", "manifest", "invalidated"}
        or not isinstance(receipt["manifest"], dict)
        or set(receipt["manifest"]) != {"session", "worktree", "epoch", "day", "paths"}):
        return False
    manifest = receipt["manifest"]
    identity = manifest["worktree"]
    if (not isinstance(manifest["session"], str) or not manifest["session"] or "\x00" in manifest["session"]
        or not isinstance(identity, list) or len(identity) != 7
        or not all(isinstance(identity[i], str) and "\x00" not in identity[i]
                   and Path(identity[i]).is_absolute() for i in (0, 3))
        or not all(type(identity[i]) is int and identity[i] >= 0 for i in (1, 2, 4, 5))
        or not isinstance(identity[6], str) or "\x00" in identity[6] or not identity[6].startswith("refs/heads/")
        or len(identity[6]) <= len("refs/heads/")
        or not isinstance(manifest["epoch"], str)
        or re.fullmatch(r"[0-9a-f]{32}(?:[0-9a-f]{32})?", manifest["epoch"]) is None
        or not isinstance(manifest["day"], str) or not notice_paths_valid(manifest["paths"])
        or not isinstance(receipt["invalidated"], list)
        or not all(isinstance(p, str) and p in manifest["paths"] for p in receipt["invalidated"])
        or digest(manifest) != receipt["digest"]):
        return False
    try:
        return datetime.date.fromisoformat(manifest["day"]).isoformat() == manifest["day"]
    except ValueError:
        return False


def dirty_notice_manifest(
    session: str, observations: list[tuple[Path, dict[str, Any], dict[str, Any], list[str]]],
) -> dict[str, Any] | None:
    """Identify a repeated notification, never an approved dirty-state exception.

    Full snapshots must still be readable and stable. Only the unresolved
    path set and repository scope identify repeated dirt notifications.
    Changes to HEAD, content, index, or mode do not re-arm the same paths.
    Other Git issues remain loud.
    """
    if not session or fcntl is None:
        return None
    repos: dict[str, Any] = {}
    for root, entry, observation, issues in observations:
        if not issues:
            continue
        current = observation.get("snapshot")
        own_paths = entry.get("own_paths", [])
        receipt = entry.get("receipt")
        gitlinks = current.get("gitlinks", {}) if isinstance(current, dict) else {}
        legacy_gitlink = bool(gitlinks) and current.get("dirty_count") == len(gitlinks) == 1
        if (not notice_baseline_valid(entry.get("baseline"), legacy_gitlink=legacy_gitlink)
            or ("epoch" in entry and (not isinstance(entry["epoch"], str)
                or re.fullmatch(r"[0-9a-f]{32}(?:[0-9a-f]{32})?", entry["epoch"]) is None))
            or ("receipt" in entry and not notice_receipt_valid(receipt))):
            continue
        accepted = observation.get("accepted_paths")
        if (len(issues) != 1
            or not issues[0].startswith(f"{root}: dirty (")
            or not isinstance(current, dict) or not isinstance(current.get("paths"), dict)
            or not isinstance(current.get("identity"), list)
            or not isinstance(own_paths, list) or not all(isinstance(p, str) for p in own_paths)
            or not isinstance(accepted, list) or not all(isinstance(p, str) for p in accepted)
            or not set(accepted) <= set(current["paths"])
            or repo_signature(root, with_identity=True) != current):
            continue
        repos[str(root)] = {"worktree": current["identity"],
                            "unresolved_paths": sorted(set(current["paths"]) - set(accepted)),
                            "epoch": entry.get("epoch") or digest(entry.get("baseline"))}
        if gitlinks:
            repos[str(root)]["gitlinks"] = gitlinks
    return {"version": 1, "session": session,
            "day": datetime.datetime.now().astimezone().date().isoformat(), "repos": repos}


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def nudge(event: dict[str, Any]) -> int:
    if event.get("hook_event_name") != "Stop":
        return 0
    path = state_path(event)
    state = load_state(path)
    session = event.get("session_id")
    issues: list[str] = []
    observations = []
    duplicates: set[str] = set()
    if state is None:
        issues.append("Git gate state could not be read")
        state = {"repos": {}}
    # The remote query can take time. Never hold the tracker lock while
    # probing it; if a tracker changed the state meanwhile, leave it intact.
    before = digest(state)
    for root_value, entry in state["repos"].items():
        if isinstance(root_value, str) and isinstance(entry, dict):
            root = Path(root_value)
            observation: dict[str, Any] = {}
            found = repo_issues(root, entry, session if isinstance(session, str) else "", observation)
            issues.extend(found)
            observations.append((root, entry, observation, found))
        else:
            issues.append("Git gate repository state is malformed")
    notice = (dirty_notice_manifest(session if isinstance(session, str) else "", observations)
              if type(state.get("version")) is int and state["version"] == 1 else None)
    keep = any(isinstance(entry, dict) and "receipt" in entry for entry in state["repos"].values())
    last_notice = state.get("last_dirty_notice")
    keep_notice = (isinstance(last_notice, dict)
                   and last_notice.get("session") == session
                   and last_notice.get("day") == datetime.datetime.now().astimezone().date().isoformat())
    if path.exists() or state["repos"]:
        try:
            with state_lock(path) as locked:
                if digest(load_state(path)) != before:
                    issues.append("Git gate state changed during verification; retry the check")
                elif locked:
                    if notice is not None:
                        previous = last_notice.get("repos") if keep_notice and last_notice.get("version") == 1 else None
                        if not isinstance(previous, dict):
                            previous = {}
                        # Repositories not visited in this tracking period have no
                        # new evidence to invalidate a previously displayed notice.
                        tracked = state["repos"]
                        for key, prior in previous.items():
                            if key not in tracked and isinstance(prior, dict):
                                notice["repos"][key] = prior
                        for root, entry, observation, found in observations:
                            key = str(root)
                            prior = previous.get(key)
                            if not isinstance(prior, dict):
                                continue
                            now = notice["repos"].get(key)
                            if now is None:
                                if not found and (observation.get("snapshot") or {}).get("dirty_count") == 0:
                                    notice["repos"][key] = prior
                                    # The next tracked write begins a new epoch even if
                                    # another repository still has unresolved work.
                                    tracked.pop(key, None)
                            elif ({**prior, "epoch": now["epoch"]} == now
                                  and (prior.get("epoch") == now["epoch"]
                                       or not set(now["unresolved_paths"]).intersection(entry.get("own_paths", [])))):
                                duplicates.add(found[0])
                                notice["repos"][key] = prior
                    has_notice = notice is not None and bool(notice["repos"])
                    if has_notice:
                        state["last_dirty_notice"] = notice
                    else:
                        state.pop("last_dirty_notice", None)
                    if not issues and not keep:
                        if not has_notice:
                            path.unlink(missing_ok=True)
                            emit({})
                            return 0
                        state["repos"] = {}
                    if digest(state) != before:
                        save_state(path, state)
        except OSError:
            duplicates.clear()
            issues.append("Git gate state could not be verified")
    issues = [issue for issue in issues if issue not in duplicates]
    if not issues:
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
    if len(sys.argv) != 2 or sys.argv[1] not in {"track", "nudge", "review", "acknowledge"}:
        return 2
    event = read_event()
    return {"track": track, "nudge": nudge, "review": review, "acknowledge": acknowledge}[sys.argv[1]](event)


if __name__ == "__main__":
    raise SystemExit(main())
