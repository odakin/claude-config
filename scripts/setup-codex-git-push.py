#!/usr/bin/env python3
"""Install or audit an opt-in Codex rule for prompt-free normal Git pushes.

The managed rule allows only `git push origin main` and
`git push origin master`. Common destructive or scope-expanding push flags
remain prompt-gated.
The rule changes sandbox escalation handling, not repository checks or the
authorization boundary recorded by the user's own workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MARKER = "# Managed by claude-config/scripts/setup-codex-git-push.py\n"
RULE_NAME = "claude-config-git-push.rules"


def desired() -> str:
    return MARKER + """prefix_rule(
    pattern = ["git", "push", "origin", ["main", "master"]],
    decision = "allow",
    justification = "Normal pushes to the default branch are owner-authorized after repository checks",
    match = [
        "git push origin main",
        "git push origin master",
    ],
    not_match = [
        "git push origin feature",
        "git push --force origin main",
    ],
)

prefix_rule(
    pattern = ["git", "push", ["--force", "-f", "--force-with-lease", "--force-if-includes", "--delete", "-d", "--mirror", "--prune", "--all", "--tags", "--follow-tags"]],
    decision = "prompt",
    justification = "Destructive or scope-expanding pushes require explicit approval",
)

prefix_rule(
    pattern = ["git", "push", "origin", ["main", "master"], ["--force", "-f", "--force-with-lease", "--force-if-includes", "--delete", "-d", "--mirror", "--prune", "--all", "--tags", "--follow-tags"]],
    decision = "prompt",
    justification = "Destructive or scope-expanding pushes require explicit approval",
)
"""


def apply(codex_dir: Path, install: bool = False) -> Path:
    codex_dir = codex_dir.expanduser().resolve()
    target = codex_dir / "rules" / RULE_NAME
    expected = desired()

    if target.is_symlink() or (target.exists() and not target.read_text(encoding="utf-8").startswith(MARKER)):
        raise ValueError(f"unmanaged rule target; left unchanged: {target}")

    if install:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(expected)

    if not target.is_file() or target.read_text(encoding="utf-8") != expected:
        raise ValueError(f"normal-push rule missing or stale; run --install: {target}")
    if target.stat().st_mode & 0o077:
        raise ValueError(f"rule file must be private (0600): {target}")

    print(f"Codex normal-push rule verified: {target}")
    print("Restart Codex or start a fresh task before relying on newly installed rules.")
    return target


def execpolicy(rule: Path, command: list[str], home: Path) -> dict[str, object] | None:
    codex = shutil.which("codex")
    if not codex:
        return None
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    environment["CODEX_HOME"] = str(home / ".codex")
    completed = subprocess.run(
        [codex, "execpolicy", "check", "--rules", str(rule), "--", *command],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    return json.loads(completed.stdout)


def selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="setup-codex-git-push-") as temporary:
        root = Path(temporary)
        try:
            apply(root)
        except ValueError:
            pass
        else:
            print("[FAIL] audit accepted a missing rule")
            return 1

        target = apply(root, install=True)
        apply(root, install=True)
        apply(root)
        if target.stat().st_mode & 0o777 != 0o600:
            print("[FAIL] installed rule mode is not 0600")
            return 1

        cases = [
            (["git", "push", "origin", "main"], "allow"),
            (["git", "push", "origin", "master"], "allow"),
            (["git", "push", "origin", "main", "--force"], "prompt"),
            (["git", "push", "--force", "origin", "main"], "prompt"),
            (["git", "push", "origin", "main", "--delete"], "prompt"),
            (["git", "push", "origin", "main", "--tags"], "prompt"),
        ]
        for command, expected in cases:
            payload = execpolicy(target, command, root)
            if payload is None:
                print("[SKIP] codex CLI unavailable; execpolicy integration not exercised")
                break
            if payload.get("decision") != expected:
                print(f"[FAIL] execpolicy {command}: {payload.get('decision')} != {expected}")
                return 1

        conflict_root = root / "conflict"
        conflict_target = conflict_root / "rules" / RULE_NAME
        conflict_target.parent.mkdir(parents=True)
        conflict_target.write_text("user-managed rule\n", encoding="utf-8")
        try:
            apply(conflict_root, install=True)
        except ValueError:
            pass
        else:
            print("[FAIL] unmanaged rule target was replaced")
            return 1
        if conflict_target.read_text(encoding="utf-8") != "user-managed rule\n":
            print("[FAIL] unmanaged rule target changed")
            return 1

    print("setup-codex-git-push selftest: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--selftest", action="store_true")
    parser.add_argument("--codex-dir", type=Path, default=Path.home() / ".codex")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    try:
        apply(args.codex_dir, install=args.install)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
