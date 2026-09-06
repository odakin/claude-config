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
    "codex/skills/codex-automation-routing/SKILL.md",
    "templates/personal-layer/README.md",
)
SESSION_HANDOFF_REQUIREMENTS = {
    "codex/HOME-AGENTS.md": ("CONVENTIONS.md#auto-update-protocol", "CONVENTIONS.md#session-no-durable-record"),
    "codex/hooks/resume_context.py": ("CONVENTIONS.md#auto-update-protocol",),
    "codex/hooks/session_touch.py": ("CONVENTIONS.md#auto-update-protocol",),
    "codex/PARITY.md": ('id="session-handoff-contract"',),
}

SESSION_DURABLE_TOKENS = (
    "~/.codex",
    "PreToolUse",
    "PostToolUse",
    "SessionStart",
    "approval_policy",
    "sandbox_mode",
    "hooks.json",
    "auto_compact_token_limit",
    "compaction threshold",
)
SUPERSEDED_CLAIMS = (
    "Codex currently has no supported equivalent to Claude Code's per-tool",
    "Codex does not have Claude Code's equivalent per-tool event-hook mechanism",
    "same target is effectively free",
    "同じ目標は実質無料",
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
PERSONAL_OVERLAY_REQUIREMENTS = {
    "codex/PARITY.md": (
        "--personal-layer <path>",
        "<path>/codex/AGENTS.md",
        "post-merge.d",
    ),
    "scripts/setup-codex.sh": (
        "--personal-layer",
        "--refresh-personal-layer",
        "global-personal-composite",
    ),
    "scripts/audit-codex-integration.sh": (
        "global-personal-composite",
        "personal-layer pull refresh",
    ),
    "templates/personal-layer/codex/AGENTS.md.template": (
        "Personal Codex overlay",
        "Personal-source routing",
    ),
}
CONTEXT_BUDGET_REQUIREMENTS = {
    "codex/PARITY.md": (
        "## Context-budget discipline",
        "does not set\na compaction threshold",
        "Runtime diagnostics are layer-4 observations",
        'id="context-capacity-diagnosis"',
        "advertised model/API capacity",
        "billing or credit policy",
        "An API pricing cutoff",
        "carried-over compaction-window prefix",
        "marginal A/B runs",
        "A clean numerical ratio is a hypothesis",
    ),
    "codex/HOME-AGENTS.md": (
        "Keep global startup context compact.",
        "on-demand sources",
    ),
    "docs/convention-design-principles.md": (
        'id="context-capacity-evidence-layers"',
        "model / API advertised capacity",
        "billing / credit policy",
        "product-owned prefix",
        "retained useful context",
    ),
    "README.md": ("context-capacity-evidence-layers", "billing or credit policy"),
    "README.ja.md": ("context-capacity-evidence-layers", "課金・credit"),
}
MACHINE_PROVENANCE_REQUIREMENTS = {
    "codex/PARITY.md": (
        'id="machine-local-provenance"',
        "A session title, a prior message, or an audit/report from another\nhost is an observation",
        "verify it locally with `hostname`",
    ),
    "codex/HOME-AGENTS.md": (
        "## Machine-local truth",
        "A title, prior message, or report from another host is only an observation",
        "verify it locally (`hostname` and the relevant audit)",
    ),
}
AUTOMATION_ROUTING_REQUIREMENTS = {
    "codex/PARITY.md": (
        'id="native-automation-routing"',
        "Heartbeat attached to the current task",
        "Standalone cron automation",
        "ChatGPT Web/Mobile event trigger",
        "Deduplicate first.",
        "Creation-state and schedule semantics",
        "automation identifier and active",
        "Composer\navailability proves",
    ),
    "codex/skills/codex-automation-routing/SKILL.md": (
        "#native-automation-routing",
        "same-task heartbeat",
        "automation definitions before creating one",
        "do not expose raw recurrence syntax",
        "suggestion card as proposed, not active",
        "destination-side object or receipt",
    ),
    "docs/convention-design-principles.md": (
        'id="automation-trigger-routing"',
        'id="activation-evidence-ladder"',
        "操作可能性と対象の存在状態を分ける",
    ),
    "README.md": ("codex/PARITY.md#native-automation-routing",),
    "README.ja.md": ("codex/PARITY.md#native-automation-routing",),
    "scripts/setup-codex.sh": ("codex-automation-routing",),
    "scripts/audit-codex-integration.sh": ("codex-automation-routing",),
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

    for relative, fragments in SESSION_HANDOFF_REQUIREMENTS.items():
        try:
            content = text(root / relative)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        for fragment in fragments:
            if fragment not in content:
                errors.append(f"{relative}: missing session handoff wiring: {fragment}")

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
    for relative, fragments in PERSONAL_OVERLAY_REQUIREMENTS.items():
        path = root / relative
        try:
            content = text(path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        for fragment in fragments:
            if fragment not in content:
                errors.append(f"{relative}: missing personal-overlay contract: {fragment}")
    for relative, fragments in CONTEXT_BUDGET_REQUIREMENTS.items():
        path = root / relative
        try:
            content = text(path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        for fragment in fragments:
            if fragment not in content:
                errors.append(f"{relative}: missing context-budget contract: {fragment}")
    for relative, fragments in MACHINE_PROVENANCE_REQUIREMENTS.items():
        path = root / relative
        try:
            content = text(path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        for fragment in fragments:
            if fragment not in content:
                errors.append(f"{relative}: missing machine-provenance contract: {fragment}")
    for relative, fragments in AUTOMATION_ROUTING_REQUIREMENTS.items():
        path = root / relative
        try:
            content = text(path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        for fragment in fragments:
            if fragment not in content:
                errors.append(f"{relative}: missing automation-routing contract: {fragment}")
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
    for relative, fragments in PERSONAL_OVERLAY_REQUIREMENTS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(existing + "\n".join(fragments) + "\n", encoding="utf-8")
    for relative, fragments in CONTEXT_BUDGET_REQUIREMENTS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(existing + "\n".join(fragments) + "\n", encoding="utf-8")
    for relative, fragments in MACHINE_PROVENANCE_REQUIREMENTS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(existing + "\n".join(fragments) + "\n", encoding="utf-8")
    for relative, fragments in AUTOMATION_ROUTING_REQUIREMENTS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(existing + "\n".join(fragments) + "\n", encoding="utf-8")


    for relative, fragments in SESSION_HANDOFF_REQUIREMENTS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(existing + "\n".join(fragments) + "\n", encoding="utf-8")


def selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="check-codex-integration-") as temporary:
        root = Path(temporary)
        fixture(root)
        clean_errors = check(root)
        if clean_errors:
            print("FAIL: clean fixture", clean_errors)
            return 1

        for relative in SESSION_HANDOFF_REQUIREMENTS:
            fixture(root)
            path = root / relative
            fragment = SESSION_HANDOFF_REQUIREMENTS[relative][0]
            path.write_text(path.read_text().replace(fragment, "removed-handoff-pointer"))
            if not any("missing session handoff wiring" in error for error in check(root)):
                print("FAIL: missing handoff wiring was not detected", relative)
                return 1
        fixture(root)

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

        fixture(root)
        (root / "scripts/setup-codex.sh").write_text(
            "\n".join(PERSONAL_OVERLAY_REQUIREMENTS["scripts/setup-codex.sh"][:-1]) + "\n",
            encoding="utf-8",
        )
        errors = check(root)
        if not any(error.startswith("scripts/setup-codex.sh: missing personal-overlay") for error in errors):
            print("FAIL: missing personal-overlay wiring was not detected")
            return 1

        fixture(root)
        (root / "codex/HOME-AGENTS.md").write_text(
            CANONICAL_POINTER + chr(10), encoding="utf-8"
        )
        errors = check(root)
        if not any(error.startswith("codex/HOME-AGENTS.md: missing context-budget") for error in errors):
            print("FAIL: missing context-budget contract was not detected")
            return 1

        fixture(root)
        (root / "codex/HOME-AGENTS.md").write_text(
            CANONICAL_POINTER + chr(10), encoding="utf-8"
        )
        errors = check(root)
        if not any(error.startswith("codex/HOME-AGENTS.md: missing machine-provenance") for error in errors):
            print("FAIL: missing machine-provenance contract was not detected")
            return 1

        fixture(root)
        (root / "codex/skills/codex-automation-routing/SKILL.md").write_text(
            CANONICAL_POINTER + chr(10), encoding="utf-8"
        )
        errors = check(root)
        if not any(error.startswith("codex/skills/codex-automation-routing/SKILL.md: missing automation-routing") for error in errors):
            print("FAIL: missing automation-routing contract was not detected")
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
