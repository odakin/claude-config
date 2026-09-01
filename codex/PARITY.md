# Codex capability map

This document records the deliberate boundary between the shared
`claude-config` layer and Codex. It is an implementation map, not a claim that
two different products expose identical internals.

## <a id="codex-integration-sot"></a>Source of truth and maintenance

This is the durable layer-1 source of truth for the Codex integration:
architecture, layer placement, installer contract, Hook coverage and limits,
platform scope, and verification. Keep product-specific implementation facts
here rather than restating them in `SESSION.md`, skills, or project
instructions.

The public quickstart command belongs in [README.md](../README.md#use-with-codex)
because a clone user needs it before reading project instructions. The README
is otherwise an entry point to this document. `SESSION.md` holds only the
current implementation state and a pointer here; commit history is `git log`.
Machine-specific install, configuration, and Hook-trust state are layer-4
facts: inspect them with `scripts/audit-codex-integration.sh` instead of
recording them in this repository.

`scripts/check-codex-integration.py --check` enforces the mechanically
verifiable part of this arrangement in local checks and CI: canonical pointers,
the absence of durable Codex implementation detail in `SESSION.md`, known
superseded capability claims, and the Hook adapter contract. It intentionally
does not claim to detect arbitrary semantic restatements; the thin secondary
documents and ordinary review cover that remaining judgment. The repository's
pre-commit hook runs the same check as an early warning; CI remains the
blocking layer.

## Active Codex integration

The public source lives in this layer-1 repository: `codex/HOME-AGENTS.md`,
`codex/AGENTS.md`, both skills, the hook implementation, and `hooks.json`.
`scripts/setup-codex.sh` is an explicit **layer-4 installer**. On one machine
it creates six managed links below the user's Codex locations:

- `~/.codex/AGENTS.md` — the local global-instruction entry point;
- `~/Documents/Codex/AGENTS.md` — a local Codex-workspace entry point;
- the two skills below `~/.codex/skills/`;
- `~/.codex/claude-config-hooks` — the local link to the public hook code;
- `~/.codex/hooks.json` — the local Hook configuration link.

The links make the layer-4 installation consume versioned layer-1 source.
That lower-to-upper dependency is valid; the paths, trust decisions, and
whether the links exist are still machine-local layer-4 facts.

A fresh clone does **not** write to the cloner's `~/.codex`. To enable the
integration on that machine, the cloner explicitly runs the installer. Later
`git pull` updates the layer-1 sources already selected by those links. This
installer does not create or alter a consuming project's layer-2 settings.

The installer can also set Codex's top-level `model_reasoning_effort`,
`approval_policy = "on-request"`, and `sandbox_mode = "workspace-write"`.
That enables ordinary, in-scope local work without weakening safeguards for
external, destructive, costly, or out-of-scope actions.

## Platform scope

The Codex installer is intentionally POSIX-oriented: it uses Bash, Python, and
symlinks. Native Windows support for `scripts/setup-codex.sh` is currently
unsupported and unvalidated. A contribution adding it must provide a
platform-appropriate installer and tests, retain default-refuse behavior, and
preserve the no-`~/.claude`-writes boundary.

This limitation applies only to the Codex installer. The repository's existing
Windows bootstrap for Claude Code remains supported and unaffected.

## Four-layer architecture

Codex follows the same audience order as the shared configuration:

| Layer | Audience | Codex handling |
| --- | --- | --- |
| 1. Common conventions | public/shared | This repository's generic instructions, skills, hook code, templates, and runbooks. |
| 2. Shared project | project collaborators | That project's own committed instructions and artifacts. It may use layer-1 material, but must be self-contained and must not depend on a personal or machine-local path. |
| 3. Personal layer | owner across machines | The owner's private, cross-machine preferences and bootstrap record. Codex does not discover, copy, or inject it automatically. |
| 4. Local state | one machine | `~/.codex` configuration, links, Hook trust, local session state, and machine facts. It is not committed to a shared project. |

Layers are defined by **audience**, not by distribution mechanism: layer 2 is
the shared project's own content (conventions, data, manuscripts), and layer 3
is the owner's private preference and rule content — not a "mechanical
install/sync layer". The installer and symlink machinery only materializes a
layer on a machine; that wiring is a layer-4 local fact, not a layer itself.

Layer 2 and layer 3 are intentionally different audiences: layer 2 is shared
with the project's collaborators; layer 3 is private to one owner but synced
across that owner's machines. An owner may record the per-machine Codex
bootstrap procedure in layer 3, but the actual `~/.codex` links and trust stay
in layer 4. No layer-2 project is made to depend on this local installation.

This prevents a private personal layer from silently entering a
collaborator-visible project context. An explicit, user-scoped task may use
layer-3 data, but must preserve the boundary when it writes to a layer-2 or
layer-1 repository.

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

## Native lifecycle hooks

Codex provides `PreToolUse`, `PostToolUse`, `SessionStart`, and `Stop` hooks.
This integration maps only the high-signal, product-neutral subset:

| Codex event | Managed behavior | Boundary |
| --- | --- | --- |
| `PreToolUse(apply_patch)` | Blocks Tier-A structural leak patterns while editing a repository marked public. | Git pre-commit and commit-message gates remain authoritative for all write paths. |
| `SessionStart` | Restores a compact reminder to read the active project instructions and `SESSION.md`. | It does not discover personal data or session history. |
| `PostToolUse(apply_patch)` + `Stop` | Tracks a touched Git repository in machine-local Codex state and reports unintended dirty worktree state at turn end. | It does not commit or push automatically. |

Codex requires review and trust for changed user hooks. Treat an installed
`hooks.json` as configured, not as verified active, until the client has
accepted that trust review. The audit reports installation state only.

## Deliberate non-equivalences

The following Claude-only mechanisms are intentionally not copied or emulated
as hidden background processes:

- Claude-specific memory guards and account/session reminders, because their
  target paths and account state belong to Claude rather than Codex;
- Claude Desktop shell-snapshot repair, folder-picker pinning, and the
  Claude.app PTY workaround;
- Claude settings, MCP server definitions, credentials, account state, and
  personal-memory files.

Do not copy credentials or private personal-layer data from Claude into Codex.
Connect an equivalent Codex integration only when the user explicitly scopes
the account and data that it may access.

Hooks are a guardrail rather than a complete enforcement boundary: hosted tools
and some specialised tool paths are not observable. This is why the
agent-independent Git-side protections remain in place.

Keeping these boundaries explicit protects existing Claude users: the Codex
installer never runs `setup.sh` and never writes below `~/.claude/`.
