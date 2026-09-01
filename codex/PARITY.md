# Codex capability map

This document records the deliberate boundary between the shared
`claude-config` layer and Codex. It is an implementation map, not a claim that
two different products expose identical internals.

## Active Codex integration

`scripts/setup-codex.sh` installs the following managed symlinks:

- `~/AGENTS.md` — minimal, public layer-1 instructions for Codex work outside
  the default Codex workspace.
- `~/Documents/Codex/AGENTS.md` — shared project lifecycle, safety, and
  verification instructions.
- `~/.codex/skills/claude-config-conventions` — maintenance instructions for
  this integration.
- `~/.codex/skills/claude-config-operations` — an on-demand router to the
  shared operational runbooks and scripts.

The installer can also set Codex's top-level `model_reasoning_effort`,
`approval_policy = "on-request"`, and `sandbox_mode = "workspace-write"`.
That enables ordinary, in-scope local work without weakening safeguards for
external, destructive, costly, or out-of-scope actions.

## Four-layer architecture

Codex follows the same audience order as the shared configuration:

| Layer | Audience | Codex handling |
| --- | --- | --- |
| 1. Common conventions | public/shared | The global and Codex-workspace `AGENTS.md` files, the shared skills, and public runbooks. |
| 2. Shared project | project collaborators | The project's own instructions and committed artifacts; it may depend on layer 1 only. |
| 3. Personal layer | owner across machines | Owner-private preferences and mappings. Codex does not discover, copy, or inject these automatically. |
| 4. Local state | one machine | Codex configuration, local session state, and machine facts. It is not committed to a shared project. |

The only automatic Codex instructions are layer 1. This prevents a private
personal layer from silently entering a collaborator-visible project context.
An explicit, user-scoped task may use layer-3 data, but must preserve the
boundary when it writes to a layer-2 or layer-1 repository.

Run `scripts/audit-codex-integration.sh` to inspect this installation. Add one
or more `--repo <path>` arguments to inspect the applicable Git-side gates in
specific repositories. The audit is read-only.

## Shared operational capabilities

The following are agent-independent assets. Codex uses them directly through
the operations skill; they are not copied into a second, drifting source tree.

- `CONVENTIONS.md`, `SESSION.md`, project instruction files, and the on-demand
  runbooks indexed by `conventions/README.md`.
- Document, PDF, spreadsheet, presentation, LaTeX, research, web, and macOS
  operating procedures, together with their reusable scripts under `scripts/`.
- Git-side protections: the LaTeX/conflict pre-commit guard and, for a
  repository explicitly marked public, the file-body and commit-message leak
  gates. These run independently of whichever coding agent made the change.
- Scheduled or recurring work where Codex offers its own task automation. The
  convention still applies; its execution mechanism is Codex automation rather
  than a Claude-specific routine trigger.

## Deliberate non-equivalences

Codex currently has no supported equivalent to Claude Code's per-tool
`PreToolUse`, `PostToolUse`, `SessionStart`, or `Stop` hooks. Accordingly, the
following Claude-only mechanisms are not installed or emulated as hidden
background processes:

- tool-event guards and nudges, including the Claude memory guard and
  Claude-specific session reminders;
- Claude Desktop shell-snapshot repair, folder-picker pinning, and the
  Claude.app PTY workaround;
- Claude settings, MCP server definitions, credentials, account state, and
  personal-memory files.

Do not copy credentials or private personal-layer data from Claude into Codex.
Connect an equivalent Codex integration only when the user explicitly scopes
the account and data that it may access.

Keeping these boundaries explicit protects existing Claude users: the Codex
installer never runs `setup.sh` and never writes below `~/.claude/`.
