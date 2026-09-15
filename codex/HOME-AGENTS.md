# Global Codex bootstrap

This public layer-1 file is the small instruction kernel loaded before Codex
can open task-specific sources. Keep trigger conditions and imperative pointers
here; keep rule bodies in their canonical documents. The contract is
`codex/PARITY.md#instruction-entrypoint-kernel`.

Resolve layer-1 pointers from the `claude-config` repository containing the
generated header's `public-source`, or the real target of
`~/.codex/AGENTS.md`; never resolve them against an unrelated working directory.

## Repository routing

For Git work, fetch first when a remote exists. Before editing, read the
repository-root `AGENTS.md`, then `CLAUDE.md`, `SESSION.md`, and only the
task-relevant sources they name. If a task started in a parent workspace and
later enters a nested repository, read that nested root `AGENTS.md` manually;
a shell `cd` does not rebuild the startup chain. The semantic and discovery
contracts are `CONVENTIONS.md#agent-instruction-entrypoints` and
`codex/PARITY.md#project-instruction-discovery`.

Use the `claude-config-conventions` skill for this Codex integration and treat
`codex/PARITY.md#codex-integration-sot` as its technical source of truth. Use
`claude-config-operations` for covered runbooks and reusable scripts, and
`codex-automation-routing` for reminders, schedules, monitors, and follow-ups.

## Delivery and handoff

Before a Codex-origin commit, read and apply
`codex/PARITY.md#git-session-provenance`; the commit must carry
`Agent-Session`, `Agent-Model`, and `Agent-Effort`, preserving literal
`unknown` when verified runtime data is unavailable.

Before reporting an authorized change complete, read and apply
`CONVENTIONS.md#completion-git-gate`. For handoff or session closure, read and
apply `CONVENTIONS.md#auto-update-protocol` and
`CONVENTIONS.md#session-no-durable-record`. Do not restate those procedures in
this entry point.

## Context and machine-local truth

Keep global startup context compact. Open detailed runbooks and private records
as on-demand sources; see `codex/PARITY.md#codex-integration-sot`.

### Session identity stamp

At the first user-visible reply after startup, resume, or clear, begin with the
exact identity stamp injected by the SessionStart Hook. Keep the literal product
identity `Codex` and all `unknown` fields. If the stamp is absent, make the
first tool call `python3 "$HOME/.codex/claude-config-hooks/session_stamp.py"`
and use its output unchanged. Do not restamp after compaction alone. Source:
`codex/PARITY.md#conversation-start-stamp`.

Before a machine-local claim or action, verify the current host with `hostname`
and the relevant audit; never infer it from a title, transcript, or another
host's report. Source: `codex/PARITY.md#machine-local-provenance`.

## Boundaries

Respect the audience order: public common rules (layer 1), shared-project
content (layer 2), owner-private cross-machine content (layer 3), and
machine-local state (layer 4). A shared project must not depend on layers 3 or
4. Do not discover or expose private files, credentials, personal data, or
local agent history. Source: `codex/PARITY.md#four-layer-architecture`.

Treat a request to change, build, or fix as authority for ordinary safe local
work. Ask before external, destructive, costly, or materially scope-expanding
actions not already authorized. Do not alter Claude Code configuration while
configuring Codex. Source: `codex/PARITY.md#codex-integration-sot`.
