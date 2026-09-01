#!/usr/bin/env python3
"""check-codex-integration.py — Codex SoT, session drift, Hook, and trigger-wiring gate.

The durable technical source of truth is codex/PARITY.md#codex-integration-sot.
This checker deliberately verifies only objective invariants:

* every Codex-facing entry point routes to that source;
* SESSION.md does not reintroduce durable implementation details
  (scoped to paragraphs that mention Codex — the token vocabulary
  overlaps Claude-side hook work, which is legitimate in SESSION.md);
* known superseded capability claims do not return;
* the shipped Hooks configuration names the expected local adapters.
* the aggregate runner, CI, and pre-commit warning keep the contract and
  adapter tests wired to an automatic trigger.

It cannot decide whether arbitrary prose expresses the same idea as the
source of truth. That remains a review concern; keeping secondary documents
as thin pointers makes that semantic surface small.

Usage:
  check-codex-integration.py [--root PATH] [--check]
  check-codex-integration.py --selftest
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Iterable


CANONICAL_POINTER = "codex/PARITY.md#codex-integration-sot"
ENTRY_POINTS = (
    "README.md",
    "README.ja.md",
    "SESSION.md",
    "DESIGN.md",
    "codex/HOME-AGENTS.md",
    "codex/AGENTS.md",
    "codex/skills/claude-config-conventions/SKILL.md",
    "codex/skills/claude-config-operations/SKILL.md",
    "templates/personal-layer/README.md",
)
SESSION_DURABLE_TOKENS = (
    "~/.codex",
    "PreToolUse",
    "PostToolUse",
    "SessionStart",
    "approval_policy",
    "sandbox_mode",
    "hooks.json",
)
SUPERSEDED_CLAIMS = (
    "Codex currently has no supported equivalent to Claude Code's per-tool",
    "Codex does not have Claude Code's equivalent per-tool event-hook mechanism",
)
HOOK_ADAPTERS = {
    "SessionStart": "resume_context.py",
    "PreToolUse": "pre_tool_policy.py",
    "PostToolUse": "session_touch.py",
    "Stop": "session_touch.py",
}
WIRING_REQUIREMENTS = {
    "scripts/run-all-checks.sh": (
        "check-codex-integration.py --check",
        "codex/hooks/*.test.sh",
    ),
    ".github/workflows/checks.yml": ("bash scripts/run-all-checks.sh",),
    ".claude/pre-commit-extra.sh": ("check-codex-integration.py --check",),
}


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read {path}: {exc}") from exc


def hook_commands(payload: object, event_name: str) -> list[str]:
    if not isinstance(payload, dict):
        return []
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get(event_name)
    if not isinstance(groups, list):
        return []
    commands: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        adapters = group.get("hooks")
        if not isinstance(adapters, list):
            continue
        for adapter in adapters:
            if isinstance(adapter, dict) and isinstance(adapter.get("command"), str):
                commands.append(adapter["command"])
    return commands


def check(root: Path) -> list[str]:
    errors: list[str] = []
    parity = root / "codex/PARITY.md"
    try:
        parity_text = text(parity)
    except RuntimeError as exc:
        return [str(exc)]
    if 'id="codex-integration-sot"' not in parity_text:
        errors.append("codex/PARITY.md: missing canonical codex-integration-sot anchor")

    for relative in ENTRY_POINTS:
        path = root / relative
        try:
            content = text(path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        if CANONICAL_POINTER not in content:
            errors.append(f"{relative}: missing pointer to {CANONICAL_POINTER}")
        for stale in SUPERSEDED_CLAIMS:
            if stale in content:
                errors.append(f"{relative}: superseded capability claim is present")

    for stale in SUPERSEDED_CLAIMS:
        if stale in parity_text:
            errors.append("codex/PARITY.md: superseded capability claim is present")

    try:
        session = text(root / "SESSION.md")
    except RuntimeError:
        session = ""
    # Scope the durable-detail scan to "## " entries that mention Codex: the
    # token vocabulary (PreToolUse, SessionStart, ...) is shared with Claude
    # Code's own hook system, and Claude-side hook work is a legitimate SESSION
    # topic. Entry granularity (not paragraph) so a Codex heading covers its
    # whole body even when the body itself doesn't repeat the word.
    codex_sections = [
        section for section in ("\n" + session).split("\n## ") if "codex" in section.lower()
    ]
    for token in SESSION_DURABLE_TOKENS:
        if any(token in section for section in codex_sections):
            errors.append(f"SESSION.md: durable Codex implementation detail must live in {CANONICAL_POINTER}: {token}")

    config = root / "codex/hooks/hooks.json"
    try:
        hook_config = json.loads(text(config))
    except (RuntimeError, json.JSONDecodeError) as exc:
        errors.append(f"{config.relative_to(root)}: invalid JSON: {exc}")
    else:
        for event_name, adapter in HOOK_ADAPTERS.items():
            if not any(adapter in command for command in hook_commands(hook_config, event_name)):
                errors.append(f"codex/hooks/hooks.json: {event_name} does not invoke {adapter}")

    for relative, fragments in WIRING_REQUIREMENTS.items():
        path = root / relative
        try:
            content = text(path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        for fragment in fragments:
            if fragment not in content:
                errors.append(f"{relative}: missing Codex integration wiring: {fragment}")
    return errors


def print_errors(errors: Iterable[str]) -> int:
    errors = list(errors)
    if not errors:
        print("Codex integration contract: OK")
        return 0
    for error in errors:
        print(f"ERROR: {error}")
    return 1


def fixture(root: Path) -> None:
    for relative in ENTRY_POINTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CANONICAL_POINTER + chr(10), encoding="utf-8")
    parity = root / "codex/PARITY.md"
    parity.write_text('<a id="codex-integration-sot"></a>' + chr(10), encoding="utf-8")
    hook_config = root / "codex/hooks/hooks.json"
    hook_config.parent.mkdir(parents=True, exist_ok=True)
    hooks = {
        name: [{"hooks": [{"command": f"python3 {adapter}"}]}]
        for name, adapter in HOOK_ADAPTERS.items()
    }
    hook_config.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    for relative, fragments in WIRING_REQUIREMENTS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(fragments) + "\n", encoding="utf-8")


def selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="check-codex-integration-") as temporary:
        root = Path(temporary)
        fixture(root)
        clean_errors = check(root)
        if clean_errors:
            print("FAIL: clean fixture", clean_errors)
            return 1

        (root / "README.md").write_text("missing pointer" + chr(10), encoding="utf-8")
        errors = check(root)
        if not any(error.startswith("README.md: missing pointer") for error in errors):
            print("FAIL: missing README pointer was not detected")
            return 1

        fixture(root)
        (root / "SESSION.md").write_text(
            CANONICAL_POINTER + chr(10) + "approval_policy" + chr(10),
            encoding="utf-8",
        )
        errors = check(root)
        if not any(error.startswith("SESSION.md: durable") for error in errors):
            print("FAIL: durable SESSION detail was not detected")
            return 1

        fixture(root)
        (root / "SESSION.md").write_text(
            CANONICAL_POINTER
            + chr(10) * 2
            + "## Claude hook maintenance"
            + chr(10) * 2
            + "Refined the PreToolUse nudge and the hooks.json-free settings merge."
            + chr(10),
            encoding="utf-8",
        )
        errors = check(root)
        if any(error.startswith("SESSION.md: durable") for error in errors):
            print("FAIL: Claude-side hook vocabulary outside a Codex entry was flagged")
            return 1

        fixture(root)
        (root / "SESSION.md").write_text(
            CANONICAL_POINTER
            + chr(10) * 2
            + "## Codex integration status"
            + chr(10) * 2
            + "Set approval_policy in the local config."
            + chr(10),
            encoding="utf-8",
        )
        errors = check(root)
        if not any(error.startswith("SESSION.md: durable") for error in errors):
            print("FAIL: durable detail in a Codex entry body was not detected")
            return 1

        fixture(root)
        (root / "codex/AGENTS.md").write_text(
            CANONICAL_POINTER + chr(10) + SUPERSEDED_CLAIMS[0] + chr(10),
            encoding="utf-8",
        )
        errors = check(root)
        if not any(error.startswith("codex/AGENTS.md: superseded") for error in errors):
            print("FAIL: superseded capability claim was not detected")
            return 1

        fixture(root)
        hook_path = root / "codex/hooks/hooks.json"
        hook_path.write_text('{"hooks": {"Stop": []}}', encoding="utf-8")
        errors = check(root)
        if not any("SessionStart does not invoke" in error for error in errors):
            print("FAIL: missing Hook adapter was not detected")
            return 1

        fixture(root)
        (root / ".github/workflows/checks.yml").write_text("name: checks\n", encoding="utf-8")
        errors = check(root)
        if not any(error.startswith(".github/workflows/checks.yml: missing Codex integration wiring") for error in errors):
            print("FAIL: missing CI wiring was not detected")
            return 1

    print("check-codex-integration selftest: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--check", action="store_true", help="Check the repository contract (the default).")
    parser.add_argument("--selftest", action="store_true", help="Run hermetic checker fixtures.")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    return print_errors(check(args.root.resolve()))


if __name__ == "__main__":
    raise SystemExit(main())
