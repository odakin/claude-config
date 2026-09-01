# Codex workspace conventions

This workspace uses the shared operational conventions in this repository.
This file is public layer-1 content. It may be installed at the root of a
user's Codex workspace by `scripts/setup-codex.sh`; that local link is
layer-4 wiring and intentionally does not change Claude Code's configuration
or behavior.

## Start and resume work

For work inside a Git repository, begin by fetching its remote when one
exists, checking status, and reading the repository's `AGENTS.md` or
`CLAUDE.md`. Read `SESSION.md`, when present, before editing.

Use `SESSION.md` for current task state, decisions, blockers, and next steps.
Keep durable project instructions in the repository instruction file and
design rationale in `DESIGN.md`. Do not create those files for a trivial,
one-off request.

## Shared conventions

`CONVENTIONS.md` at this repository root is the shared source of truth for
information placement, Git workflow, safety, verification, and concise
reporting. Before specialized work, open only the relevant document listed in
`conventions/README.md`—for example, the documents for office files, LaTeX,
research email, web automation, multi-session coordination, scientific
computing, or scheduled tasks.

Always render and inspect a changed visual artifact before reporting its
status. Before a meaningful commit, inspect the staged diff and check
consistency, compatibility with project instructions, unnecessary duplication,
and sensitive-data exposure.

## Four-layer boundary

Respect the audience order: common conventions (layer 1), shared project
(layer 2), owner-private cross-machine information (layer 3), and
machine-local volatile state (layer 4). A layer may depend only on the same or
a wider-audience layer. Shared-project instructions and committed artifacts
must be self-contained: they may not depend on private personal-layer content
or machine-local paths.

Layers are defined by **audience**, not by distribution mechanism. Layer 2 is
the shared project's own content (conventions, data, manuscripts) addressed to
its collaborators; layer 3 is the owner's private preference and rule content
addressed to the owner's machines. Installer, symlink, and marker machinery
only *materializes* a layer on a machine — that wiring is a layer-4 local
fact, not a layer itself.

Do not automatically read, copy, or expose personal-layer files, credentials,
or local agent history. Use them only when the user explicitly puts the data in
scope. Keep secrets and owner-specific data out of public repositories,
generated examples, commit messages, and external services.

## Safety and scope

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

- Do not expose secrets, personal data, or private-project details in public
  repositories, commit messages, pull requests, or generated examples.
- Do not make external, destructive, costly, or scope-expanding changes without
  the user's authorization.
- State the boundaries of a review or audit; a completed checklist alone is not
  evidence that no issue exists.

## Codex-specific mapping

For Codex integration architecture, lifecycle-Hook coverage, platform scope,
and verification, use the `claude-config-conventions` skill. Its canonical
technical source is `codex/PARITY.md`; do not reconstruct the contract from
old session notes. Git-side gates and project instructions remain authoritative
for committed public content.

Do not run `setup.sh` or modify `~/.claude/` while configuring Codex.

Use the `claude-config-conventions` skill when installing, updating, auditing,
or extending this shared Codex integration.

Use the `claude-config-operations` skill when a task may benefit from the
shared runbooks or reusable scripts in this repository.
