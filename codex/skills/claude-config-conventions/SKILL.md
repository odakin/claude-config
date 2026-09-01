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

Use `scripts/setup-codex.sh` from the repository root. It installs only two
symlinks: a workspace-root `AGENTS.md` and this skill under `~/.codex/skills`.
It refuses to overwrite a user-managed target unless `--replace` is explicit.
It can optionally set Codex's default reasoning effort and safe-local approval
policy, preserving a timestamped backup of `config.toml` first.

Validate with `scripts/setup-codex.test.sh` and the repository's standard
checks. Confirm that no file below `~/.claude/` changed. Commit and push only
after normal repository review and the user's authorization.

## Scope boundaries

Codex does not expose Claude Code's per-tool event-hook system. Preserve the
shared Git-side protections where applicable, but do not claim an equivalent
automatic Hook was installed when it was not. Keep the Codex instructions
short and route detailed behavior to the existing on-demand conventions.
