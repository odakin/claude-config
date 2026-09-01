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
the relevant document.

## Installation and updates

Use `scripts/setup-codex.sh` from the repository root. The repository's
instructions, skills, and hook code are public layer-1 source; the installer
creates layer-4 links at `~/.codex/AGENTS.md`, the local Codex workspace root,
two skills, and the hook bundle (`~/.codex/claude-config-hooks` plus
`~/.codex/hooks.json`). A clone does not affect another user's home directory
until they run this installer. It refuses to overwrite a user-managed target
unless `--replace` is explicit. It can optionally set Codex's default reasoning
effort and safe-local approval policy, preserving a timestamped backup of
`config.toml` first.

Validate with `scripts/setup-codex.test.sh`,
`scripts/audit-codex-integration.sh`, and the repository's standard checks.
Confirm that no file below `~/.claude/` changed. Commit and push only after
normal repository review and the user's authorization.

## Scope boundaries

Codex hooks are native but not interchangeable with Claude hooks. Use only the
Codex hook schema and the selected, product-neutral policies in
`codex/hooks/`; do not point Codex at Claude hook scripts or configuration.
Keep Git-side protections authoritative for committed public content. A newly
installed or changed user hook needs Codex trust review before it runs; verify
configuration, logic, and trust separately.

Do not confuse a shared project (layer 2) with an owner-private personal
layer (layer 3): the former is for collaborators, the latter is cross-machine
only for one owner. Neither may be silently created or populated by this
layer-4 installer.
