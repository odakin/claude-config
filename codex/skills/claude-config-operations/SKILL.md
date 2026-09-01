---
name: claude-config-operations
description: Route a Codex task to the relevant shared claude-config convention or reusable script. Use for document automation, Git safeguards, research workflows, web or macOS operations, scheduled work, and other tasks covered by claude-config; not for unrelated ordinary code changes.
---

# claude-config operations for Codex

Use this skill to access the shared operational knowledge base without copying
its runbooks into Codex-specific instructions. Resolve the containing
`claude-config` repository from this skill's symlink; its root is three
directories above this file.

## Route before acting

Read the applicable high-level safety and workflow rules in `CONVENTIONS.md`.
Then use `conventions/README.md` to load only the runbook whose trigger matches
the task. Do not bulk-load the convention directory.

Use the existing reusable scripts from `scripts/` when the selected runbook
identifies one. Preserve their validation or render-and-inspect steps; a
successful command alone does not establish a correct visual artifact.

## Four-layer boundary

Keep the audience order intact: layer 1 common conventions, layer 2 shared
project, layer 3 owner-private cross-machine information, and layer 4
machine-local state. A layer may structurally depend only on the same or a
wider-audience layer. In particular, never make a shared-project artifact
depend on a personal-layer file, owner-specific path, credential, or local
agent state.

The Codex integration intentionally installs only layer-1 instructions. Do not
discover, copy, or load a Claude personal layer automatically. If a task needs
owner-private data, require the user to place that specific data in scope and
keep it out of layer-1/2 outputs.

## Common routes

- **Current work, resuming, Git, reviews, or public safety:** `CONVENTIONS.md`,
  the repository instruction file, `SESSION.md`, and the relevant Git scripts.
  Use `scripts/audit-codex-integration.sh --repo <path>` to inspect existing
  agent-independent Git guards without changing them.
- **PDF, DOCX, XLSX, PPTX, forms, or print artifacts:** the office and PDF
  runbooks indexed in `conventions/README.md`, plus Codex's corresponding
  document, spreadsheet, presentation, or PDF capabilities.
- **LaTeX, papers, talks, research data, or scientific computing:** route from
  the index to the relevant research runbook and use the established project
  validation workflow.
- **Web, browser, email, Dropbox, Discord, GitHub, or other accounts:** load
  the relevant runbook first. Never copy Claude MCP credentials or account
  configuration into Codex; request an explicitly scoped Codex connection when
  one is needed.
- **Recurring work:** use Codex task automation when it fits the requested
  workflow. Claude-specific hook or routine mechanisms do not carry over.

## Boundaries

Claude Code event hooks do not have a Codex equivalent. Apply their intent via
project instructions, explicit checks, and Git-side gates; do not claim a
background Hook was installed. Do not run `setup.sh` or write to `~/.claude/`
as part of Codex setup or task execution.
