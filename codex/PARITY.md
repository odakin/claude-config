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
superseded capability claims, the Hook adapter contract, and the aggregate
runner/CI/pre-commit trigger wiring. It intentionally does not claim to detect
arbitrary semantic restatements; the thin secondary documents and ordinary
review cover that remaining judgment. The repository's pre-commit hook runs
the same check as an early warning; CI remains the blocking layer.

### Fact placement and evidence

Keep each Codex fact in the one home that owns its lifecycle:

| Need | Home |
| --- | --- |
| Clone-user command and the minimum replacement warning | `README.md` / `README.ja.md` |
| Durable architecture, autonomy boundary, layer placement, platform scope, and verification contract | This document |
| Owner-specific cross-machine bootstrap choice and concise Codex overlay | The owner's private layer-3 record; the public personal-layer template only explains the boundary and required source shape |
| Current, short-lived work state | `SESSION.md`, as a pointer here rather than a second technical record |
| Actual links, configuration, and requested project Git guards on one machine | `scripts/audit-codex-integration.sh` |
| Hook client trust decision | The Codex client on that machine |

“Installed” is not a single claim. The contract checker verifies source and
trigger wiring; fixture and hook tests verify behavior; the aggregate runner
and CI make those tests fire; the audit verifies layer-4 wiring; and the
client trust review is the remaining product-controlled step. Do not collapse
one green layer into evidence for another.

This Codex-specific map applies, without copying Claude implementation, the
shared [SESSION snapshot rule](../CONVENTIONS.md#session-no-durable-record),
[layer-3 boundary](../docs/personal-layer.md), and
[hook-delivery evidence model](../conventions/hook-authoring.md#delivery-audit-method).

### Context-budget discipline

The global instruction entry points stay compact. Detailed public runbooks and
the owner-private corpus are task-specific, on-demand sources: inspect only
the relevant source, using targeted searches and bounded excerpts rather than
loading broad document trees or verbose command output into a session.

Automatic context compaction is product-controlled. The installer does not set
a compaction threshold or any undocumented setting intended to control one.
Do not infer such a control from local runtime files or from API-specific
features; record a supported product control here only after it is documented
and verified. Runtime diagnostics are layer-4 observations, not evidence that
they caused a particular compaction pattern. Their diagnosis and repair belong
in the applicable private task ledger as a layer-4 maintenance record, never
in a public `SESSION.md`.

### <a id="context-capacity-diagnosis"></a>Context-capacity diagnosis

Do not collapse advertised model/API capacity, the product/client-selected
window, a run's reported usable window, the observed compaction trigger, and
post-compaction recovery quality into one number. The general measurement and
matched-run comparison protocol is canonical in
[context-capacity evidence layers](../docs/convention-design-principles.md#context-capacity-evidence-layers).

For Codex investigations, prefer official product documentation over live
runtime or server reports, and prefer those reports over bundled client
catalog metadata. A clean numerical ratio is a hypothesis, not a supported
backend contract. Record the surface, authentication route, client version,
model, instruction/tool prefix, usage events, and recovery result in the
private case ledger. Until a configuration field's product semantics are
documented and verified, keep them as an unresolved question rather than
turning local metadata into a durable prescription.

## Active Codex integration

The public source lives in this layer-1 repository: `codex/HOME-AGENTS.md`,
`codex/AGENTS.md`, the three skills, the hook implementation, and `hooks.json`.
`scripts/setup-codex.sh` is an explicit **layer-4 installer**. Its default
mode creates seven managed links below the user's Codex locations:

- `~/.codex/AGENTS.md` — the local global-instruction entry point;
- `~/Documents/Codex/AGENTS.md` — a local Codex-workspace entry point;
- the three skills below `~/.codex/skills/`;
- `~/.codex/claude-config-hooks` — the local link to the public hook code;
- `~/.codex/hooks.json` — the local Hook configuration link.

The links make the layer-4 installation consume versioned layer-1 source.
That lower-to-upper dependency is valid; the paths, trust decisions, and
whether the links exist are still machine-local layer-4 facts.

An owner who explicitly passes `--personal-layer <path>` may replace only the
global `~/.codex/AGENTS.md` link with a mode-`0600`, generated layer-4
composite. It concatenates the public `codex/HOME-AGENTS.md` with the
selected layer-3 `<path>/codex/AGENTS.md`; the latter is deliberately a short
Codex-specific overlay, not the owner's full `CLAUDE.md`. The other five
managed links stay unchanged. The marker `.claude-personal-layer` and
non-empty overlay are required, but the installer never searches for a
personal layer: choosing its path is an explicit owner action.

The generated file is local state, not a tracked copy. The installer writes a
personal-layer `post-merge.d` refresh extension only when it can safely use
the existing managed dispatcher, so personal-layer `git pull` refreshes an
already selected composite. A public-layer pull does the same once the
current `setup.sh`-generated post-merge hook is installed. If a user-managed
`post-merge` cannot be chained safely, installation still preserves it and
the audit reports the unavailable automatic refresh. The refresh command
never creates a new binding or discovers a layer.

Before mutating anything, the default installer mode preflights every managed
target. A user-managed conflict therefore leaves no partial links, migration,
or configuration update behind; `--replace` is the explicit opt-in that backs
up and replaces conflicts.

A fresh clone does **not** write to the cloner's `~/.codex`. To enable the
integration on that machine, the cloner explicitly runs the installer. Later
`git pull` updates the layer-1 sources selected by ordinary links; an opted-in
composite refreshes after personal-layer pulls, and after public pulls once the
current `setup.sh` post-merge hook is installed. This installer does
not create or alter a consuming project's layer-2 settings.

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
| 3. Personal layer | owner across machines | The owner's private, cross-machine preferences, concise Codex overlay, and bootstrap record. Codex never discovers it. Only an explicit owner-selected installer invocation can materialize its short overlay in layer 4. |
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
collaborator-visible project context. The selected global composite is local
to the owner's Codex home and never makes a layer-2 project depend on layer 3.
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

## <a id="native-automation-routing"></a>Native automation routing

Codex automation is not one mechanism. Select the firing surface by the event
that must wake the work and by the execution locus it needs:

| Need | Native route | Context and locus |
| --- | --- | --- |
| Remind, re-check, monitor, or follow up in this task | **Heartbeat attached to the current task** | Returns to the same task and can use its existing context. This is the default for conversational follow-ups. |
| Independent repeated project work | **Standalone cron automation** | Starts a separate run against one saved project. Use a worktree for Git repositories by default and local execution for non-Git projects. |
| Deterministic local script with no model judgment | **launchd / cron / platform scheduler** | Runs on the selected machine without model tokens. The generic locus rule remains [`scheduled-tasks.md#execution-locus-selection`](../conventions/scheduled-tasks.md#execution-locus-selection). |
| Deterministic Codex tool or session event | **Codex lifecycle Hook** | Fires on the supported lifecycle event; it is not a clock or an inbox watcher. |
| Gmail, Slack, or GitHub activity | **ChatGPT Web/Mobile event trigger**, where available | Event triggers are configured on Web/Mobile, not Desktop/CLI/IDE, and cannot be combined with a time schedule. Periodic polling is a distinct, explicitly chosen fallback. |

The current official product guide is
[Scheduled tasks in Codex](https://learn.chatgpt.com/docs/automations). Verify
it before relying on a product-availability fact: supported surfaces and
trigger types can change independently of this repository.

### Automation construction contract

1. **Deduplicate first.** Inspect the existing local automation definitions,
   identify a match by purpose and target, and update it rather than creating a
   second scheduler for the same obligation. Preserve fields outside the
   user's requested change.
2. **Use the native management surface.** Create, view, update, pause, or delete
   automations through the Codex app automation tool. Do not hand-edit its
   machine-local files, invent a cron workaround for a same-task heartbeat, or
   present raw recurrence syntax to the user.
3. **Write a replayable prompt.** Name the scope and evidence sources, the
   success/report condition, the unchanged-state behavior, the stop condition,
   and the conditions that require user input. A standalone run must not depend
   on an unstated earlier conversation.
4. **Keep authority explicit.** Read-only checks and drafts may run unattended.
   Sending, publishing, deleting, purchasing, or another consequential
   external write requires the applicable authority at execution time unless
   the user explicitly authorized that exact recurring action.
5. **Make inactivity visible.** Report the human-readable schedule, target,
   notification policy, and stop behavior after creation. If the requested
   trigger is unavailable on the current surface, say that it was not installed
   and point to the supported surface; do not let an inert configuration look
   active.

### Creation-state and schedule semantics

The management surface distinguishes **proposal** from **activation**.
`suggested_create` renders a user-facing proposal card; that card alone is not
evidence that an automation is registered. Claim activation only after the
native create/update result supplies an automation identifier and active
status. Later health is a separate claim established by a run record or
heartbeat. This is the product-specific application of
[`activation-evidence-ladder`](../docs/convention-design-principles.md#activation-evidence-ladder).

For a heartbeat that resumes an external create/send workflow, inspect both
the automation state and the destination-side object or receipt. Composer
availability proves that the product permits creation; it does not prove that
the object was never created. Search for the existing topic, message, or
record before asking to create a duplicate, and use its URL or identifier plus
read-back content as completion evidence.

An immediate heartbeat create may reject an explicit timezone-anchored start
date because the app owns local-wall-clock conversion. When that happens,
either use the supported suggestion flow and report it as awaiting acceptance,
or express an equivalent unambiguous native schedule without the rejected
anchor. Never silently shift the requested wall-clock time. One-shot follow-up
semantics must be visible in both the human-readable report and the replayed
prompt's stop condition.

The route selection itself follows the product-neutral five-axis rule in
[`automation-trigger-routing`](../docs/convention-design-principles.md#automation-trigger-routing):
wake event, model judgment, context continuity, execution locus, and authority.

For local projects, the selected computer and Codex app must be available when
the task runs. A task that only needs a hosted service should not be made
machine-dependent without reason. Keep notification policy in automation
metadata rather than in the replayed prompt.

## Native lifecycle hooks

Codex provides `PreToolUse`, `PostToolUse`, `SessionStart`, and `Stop` hooks.
This integration maps only the high-signal, product-neutral subset:

| Codex event | Managed behavior | Boundary |
| --- | --- | --- |
| `PreToolUse(apply_patch)` | Blocks Tier-A structural leak patterns while editing a repository marked public. | Git pre-commit and commit-message gates remain authoritative for all write paths. |
| `SessionStart` | Restores a compact reminder to read the active project instructions and `SESSION.md`, and identifies the local hook process's worker host. | It reads only that local runtime fact; it does not discover personal-layer data or session history. |
| `PostToolUse(apply_patch)` + `Stop` | Tracks a touched Git repository in machine-local Codex state and reports unintended dirty worktree state at turn end. | It does not commit or push automatically. |

## <a id="machine-local-provenance"></a>Machine-local provenance

The SessionStart reminder obtains the short hostname only from the current
hook process. A session title, a prior message, or an audit/report from another
host is an observation, not proof of this machine's state. Before claiming or
acting on a machine-local fact, verify it locally with `hostname` and the
relevant audit; state the checked host, time, and scope in the conclusion.
This is a runtime guard, not durable session state and not a source of
personal-layer discovery.

When that conclusion lands on a public surface (a public repo's file,
commit message, or issue), write the host as an attribute ("the laptop",
"the MacBook-side machine"), not the hostname literal — machine names often
embed personal names, and the literal belongs in the owner's private layer.

The executable tests cover each supported public-leak category, allowlisted and
removed patch text, private-repository pass-through, default-refuse installer
atomicity, and dirty-worktree nudge de-duplication/reset. They run through the
repository's aggregate local checks and CI.

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
