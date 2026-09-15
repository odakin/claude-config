#!/usr/bin/env python3
"""Find locally cloned, self-owned Git repositories absent from a registry.

The engine is owner-neutral: callers provide the workspace root, Markdown
registry, accepted GitHub owners, and explicit exclusions. It reports only
local repositories owned by those identities; registry entries not cloned on
this machine are not errors. Exit 1 means missing registrations, 0 is silent.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROW_RE = re.compile(r"^\|\s*`([^`/]+)/?`", re.MULTILINE)
GITHUB_OWNER_RE = re.compile(
    r"(?:https?://github\.com/|ssh://git@github\.com/|git@github\.com:)([^/]+)/"
)


def registered_repos(text: str) -> set[str]:
    return {match.group(1) for match in ROW_RE.finditer(text)}


def github_owner(url: str) -> str | None:
    match = GITHUB_OWNER_RE.search(url)
    return match.group(1) if match else None


def git_remote(directory: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def owned_local_repos(root: Path, owners: set[str]) -> dict[str, str]:
    repos: dict[str, str] = {}
    if not root.is_dir():
        return repos
    wanted = {owner.casefold() for owner in owners}
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not (directory / ".git").exists():
            continue
        url = git_remote(directory)
        owner = github_owner(url)
        if owner and owner.casefold() in wanted:
            repos[directory.name] = url
    return repos


def find_missing(
    root: Path,
    registry: Path,
    owners: set[str],
    exclusions: set[str],
) -> dict[str, str]:
    try:
        registered = registered_repos(registry.read_text(encoding="utf-8"))
    except OSError:
        return {}
    local = owned_local_repos(root, owners)
    return {
        name: url
        for name, url in local.items()
        if name not in registered and name not in exclusions
    }


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []
    sample = "| `one/` | note |\n| `two-three` | note |\n"
    checks.append(("Markdown registry parser", registered_repos(sample) == {"one", "two-three"}))
    checks.extend(
        [
            ("HTTPS owner", github_owner("https://github.com/example/repo.git") == "example"),
            ("SCP owner", github_owner("git@github.com:example/repo.git") == "example"),
            ("SSH URL owner", github_owner("ssh://git@github.com/example/repo.git") == "example"),
            ("non-GitHub remote", github_owner("https://git.example/repo.git") is None),
        ]
    )
    with tempfile.TemporaryDirectory(prefix="repo-registration-") as temporary:
        root = Path(temporary)
        for name, owner in (("registered", "example"), ("missing", "example"), ("foreign", "other")):
            directory = root / name
            subprocess.run(["git", "init", "-q", str(directory)], check=True)
            subprocess.run(
                ["git", "-C", str(directory), "remote", "add", "origin", f"git@github.com:{owner}/{name}.git"],
                check=True,
            )
        registry = root / "repos.md"
        registry.write_text("| `registered/` | present |\n", encoding="utf-8")
        missing = find_missing(root, registry, {"example"}, set())
        checks.append(("only owned unregistered repo is reported", set(missing) == {"missing"}))
        checks.append(("explicit exclusion works", not find_missing(root, registry, {"example"}, {"missing"})))
        checks.append(("missing registry fails open", not find_missing(root, root / "absent.md", {"example"}, set())))
    ok = True
    for label, condition in checks:
        print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
        ok = ok and condition
    print("check-repo-registration selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--owner", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return run_selftest()
    if args.root is None or args.registry is None or not args.owner:
        parser.error("--root, --registry, and at least one --owner are required")
    missing = find_missing(args.root, args.registry, set(args.owner), set(args.exclude))
    if not missing:
        return 0
    print(f"Repository registry is missing {len(missing)} self-owned local repo(s):")
    for name, url in sorted(missing.items()):
        print(f"  {name} ({url})")
    print(f"  Add them to {args.registry} or pass --exclude with a documented reason.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
