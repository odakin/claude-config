# Codex workspace conventions

This workspace uses the shared operational conventions in this repository.
This file is installed at the root of the user's Codex workspace by
`scripts/setup-codex.sh`; it intentionally does not change Claude Code's
configuration or behavior.

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

## Safety and scope

- Do not expose secrets, personal data, or private-project details in public
  repositories, commit messages, pull requests, or generated examples.
- Do not make external, destructive, costly, or scope-expanding changes without
  the user's authorization.
- State the boundaries of a review or audit; a completed checklist alone is not
  evidence that no issue exists.

## Codex-specific mapping

Claude Code event hooks are not available as equivalent Codex event hooks.
Apply their intent through these instructions, project Git hooks, and explicit
checks. Do not run `setup.sh` or modify `~/.claude/` while configuring Codex.

Use the `claude-config-conventions` skill when installing, updating, auditing,
or extending this shared Codex integration.
