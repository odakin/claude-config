---
name: claude-config-conventions
description: Apply or maintain the shared claude-config operational conventions in Codex, including its Codex installer and workspace instructions. Use for Codex convention setup, synchronization, audits, or extensions; not for ordinary project work.
---

# claude-config conventions for Codex

This skill maintains the Codex integration shipped by the `claude-config`
repository. Keep the Claude and Codex layers separate: never alter
`~/.claude/`, Claude Code settings, or the existing `setup.sh` merely to
configure Codex.

## Locate the source of truth

This installed skill is a symlink to
`claude-config/codex/skills/claude-config-conventions`. Resolve the containing
repository from this file's path; the repository root is three directories
above it. Read `CONVENTIONS.md` before changing the integration. For a
task-specific convention, route through `conventions/README.md` and load only
the relevant document. Then read
`codex/PARITY.md#codex-integration-sot`: it is the single durable source for
the Codex architecture, layer boundaries, platform scope, and Hook contract.

## Installation and updates

Use `scripts/setup-codex.sh` from the repository root. A clone has no effect
on another user's home directory until that user runs the installer. Follow the
installer contract in `codex/PARITY.md#codex-integration-sot` rather than
copying its technical details into this skill.

Validate with `scripts/setup-codex.test.sh`,
`scripts/audit-codex-integration.sh`, and the repository's standard checks.
Confirm that no file below `~/.claude/` changed. Commit and push only after
normal repository review and the user's authorization.

## Scope boundaries

Use only the Codex hook schema and the selected, product-neutral policies in
`codex/hooks/`; do not point Codex at Claude hook scripts or configuration.
Keep Git-side protections authoritative for committed public content. Treat
configuration, logic, and Hook trust as separate checks.

Do not confuse a shared project (layer 2) with an owner-private personal
layer (layer 3): the former is for collaborators, the latter is cross-machine
only for one owner. The installer never creates, discovers, or populates
either. An owner may explicitly select a short layer-3 `codex/AGENTS.md`
overlay; only the generated local layer-4 composite consumes it.
