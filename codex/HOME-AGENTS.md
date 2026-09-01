# Global Codex conventions

Apply the shared `claude-config` conventions in every local Codex session.
This file is public layer-1 content. `scripts/setup-codex.sh` may link it into
`~/.codex/AGENTS.md`, but that installed path and its trust state are
machine-local layer-4 wiring. This content must remain useful without access
to owner-private data.

For Git work, fetch first when a remote exists, inspect the project
instructions and `SESSION.md`, and preserve the project's own instructions.
Use the `claude-config-conventions` skill when installing, updating, auditing,
or extending this Codex integration.
Use the `claude-config-operations` skill when a task may be covered by the
shared operational runbooks or scripts.

## Four-layer boundary

Respect the audience order: common conventions (layer 1), shared project
(layer 2), owner-private cross-machine information (layer 3), and
machine-local volatile state (layer 4). A layer may depend only on the same or
a wider-audience layer. In particular, a shared project must be self-contained
and must not depend on a private personal layer or a machine-local path.

Do not automatically read, copy, or expose personal-layer files, credentials,
or local agent history. Use them only when the user explicitly puts the data in
scope. Keep secrets and owner-specific data out of public repositories,
generated examples, commit messages, and external services.

## Autonomous in-scope work

Treat a request to change, build, or fix as authorization for the ordinary,
safe local work needed to complete it: inspect files and logs, edit in-scope
code, and run relevant non-destructive validation. Do not request an extra
confirmation for each such step. Follow the repository's normal Git workflow
when the user has asked for it.

Ask before an external write not already in the user's stated scope, a
destructive action, a purchase or other costly action, or a material expansion
of scope. An execution environment may still enforce a technical permission
gate; treat that as a boundary, not as a reason to add conversational
confirmation for safe local work.

Native Codex hooks provide a second safety layer for selected high-signal
events. They do not replace project Git hooks or the boundaries above, and
they must never cause Claude Code configuration to be read or changed.
