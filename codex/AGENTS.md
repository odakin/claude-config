# Codex workspace dispatcher

This public layer-1 file may be linked into a user's Codex workspace. Global
bootstrap rules belong in `codex/HOME-AGENTS.md`; this file only routes work to
the owning sources. Follow `codex/PARITY.md#instruction-entrypoint-kernel` and
do not duplicate rule bodies here. Resolve its pointers from this link's real
`claude-config` repository, not from the workspace directory.

For work in a Git repository, follow the global bootstrap, then read the
repository-root `AGENTS.md` first, followed by `CLAUDE.md`, `SESSION.md`, and
their task-relevant pointers. If the repository was entered after task startup,
read its root `AGENTS.md` manually. Sources:
`CONVENTIONS.md#agent-instruction-entrypoints` and
`codex/PARITY.md#project-instruction-discovery`.

For Codex integration work, use the `claude-config-conventions` skill and read
`codex/PARITY.md#codex-integration-sot`. Before reporting a change complete,
apply `CONVENTIONS.md#completion-git-gate`. For handoff, apply
`CONVENTIONS.md#auto-update-protocol` and
`CONVENTIONS.md#session-no-durable-record`.
