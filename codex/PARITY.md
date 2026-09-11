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
| Product-neutral requirement that every repository expose a thin root `AGENTS.md` | `CONVENTIONS.md#agent-instruction-entrypoints`; this document owns only Codex discovery mechanics |
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

### <a id="project-instruction-discovery"></a>Project instruction discovery and the root `AGENTS.md`

Source check: 2026-09-11. The official [Codex `AGENTS.md` documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md) says Codex builds an instruction chain once per run: global `AGENTS.override.md` or `AGENTS.md`, then at most one instruction file per directory from the project root down to the starting working directory. The default project names are `AGENTS.override.md` and `AGENTS.md`; another name such as `CLAUDE.md` is considered only when that machine's `project_doc_fallback_filenames` lists it. A later shell `cd` into a nested repository does not establish that its instructions were added to the already-built chain.

Therefore every repository governed by these conventions carries a tracked, non-empty, ordinary root `AGENTS.md`. The product-neutral semantic contract and file ownership are canonical in [`CONVENTIONS.md#agent-instruction-entrypoints`](../CONVENTIONS.md#agent-instruction-entrypoints); shared-project instantiation is in [`conventions/shared-repo.md#agent-entrypoint`](../conventions/shared-repo.md#agent-entrypoint). The file is a thin dispatcher: it requires the agent to read root `CLAUDE.md`, `SESSION.md`, and their task-relevant source-of-truth pointers, while leaving project rules, current state, and decisions in their existing homes. This avoids a second hand-maintained rule corpus while giving Codex a deterministic entry point.

If a task starts in a parent workspace and only later selects a nested repository, the agent must read that repository's root `AGENTS.md` before acting; for sustained work, the task should start with that repository as its project root so native discovery covers it. A machine-local fallback filename is optional convenience, not cross-machine or collaborator evidence. `scripts/setup-codex.sh` must not create or edit layer-2 project files: templates create the entry point during project setup, and `scripts/audit-codex-integration.sh --repo <path>` reports a missing, untracked, symlinked, or incomplete root entry point.

### <a id="session-handoff-contract"></a>Session handoff contract

The semantic procedure is owned by
[the shared update protocol](../CONVENTIONS.md#auto-update-protocol), with
[the no-durable-record boundary](../CONVENTIONS.md#session-no-durable-record).
[Global instructions](HOME-AGENTS.md), [workspace instructions](AGENTS.md),
and the [operations](skills/claude-config-operations/SKILL.md) /
[integration](skills/claude-config-conventions/SKILL.md) skills route to that
same procedure. The global instructions make it a standing instruction for every installed Codex;
`resume_context.py` restores its compact reminder at a SessionStart boundary.
The completion Git gate below also points to it when unresolved repository
state makes a handoff incomplete; it does not classify arbitrary SESSION prose
as a factual ledger.

`check-codex-integration.py` requires these entry points to retain the protocol
pointer; hook fixtures verify the emitted reminder. These checks protect the
wiring, not the semantic correctness of a handoff. The agent must read the
result as a fresh session before declaring completion. A clean worktree alone
is not evidence of a usable handoff. Hooks remain supplementary: the global
instruction applies to shell edits and clean commits too.

Use the installer to refresh a managed personal composite after changing the
public entry point; updating the source alone does not refresh an already
rendered composite. The local audit verifies installation, not that another
running session has reread instructions or that a client delivered a hook.

### <a id="completion-git-gate-hook"></a>Completion Git gate and Stop forcing function

The product-neutral semantic rule is
[`CONVENTIONS.md#completion-git-gate`](../CONVENTIONS.md#completion-git-gate).
Its general mechanism-design basis is
[`completion-boundary-state-gate`](../docs/convention-design-principles.md#completion-boundary-state-gate).
The global and workspace Codex instructions plus the operations and integration
skills are short firing stubs to that one home; they do not become competing
sources of truth.

`codex/hooks/session_touch.py` is the Codex-specific forcing function. On
`PreToolUse` for `apply_patch` and `Bash`, it records the pre-work Git signature
of repositories resolved from the event cwd, tool workdir, patch targets, and
explicit `cd` / `git -C` paths. It also records a `git commit` command that does
not contain `git push`. At `Stop`, a changed repository is checked for:

- task-created dirty state relative to the recorded baseline;
- fetched-upstream ahead/behind counts;
- a configured upstream when remotes exist; and
- exact equality between local `HEAD` and the branch head returned by live
  `git ls-remote`.

An unresolved state returns the [official Codex Hook](https://learn.chatgpt.com/docs/hooks) Stop output
`{"decision":"block","reason":"..."}`. Codex then receives one automatic
continuation prompt to commit/push/verify or to report a legitimate exception.
`stop_hook_active` prevents an infinite continuation loop; if state is still
unresolved on that second Stop, the hook remains loud but cannot force a second
continuation in the same turn. This is the product contract, not a claim of
absolute enforcement.

Coverage has four honest limits. Tool hooks can miss specialized execution
paths; a user must trust the current hook definition in the client; arbitrary
shell syntax cannot be resolved perfectly; and a task that mutates a repository
without any matched `PreToolUse` event has no reliable pre-work baseline. The
PostToolUse fallback treats such an observation conservatively. Pre-existing,
unchanged dirty state is not attributed to this task, and repositories with no
remote are left to the documented exception path. Git-side content gates and
the instruction entry points therefore remain authoritative alongside this
turn-end guard.

`codex-hooks.test.sh` supplies negative controls for dirty completion,
commit-only/ahead completion, a later separate push, and behind state. The
integration checker preserves the firing stubs and Hook wiring; the machine
audit verifies the installed links and completion-gate implementation. These
tests prove adapter behavior, not client delivery or trust on every frontend.

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
window, billing or credit policy, a run's reported usable window, the observed
compaction trigger, and post-compaction recovery quality into one number. The
general measurement and matched-run comparison protocol is canonical in
[context-capacity evidence layers](../docs/convention-design-principles.md#context-capacity-evidence-layers).

For Codex investigations, prefer official product documentation over live
runtime or server reports, and prefer those reports over bundled client
catalog metadata. A clean numerical ratio is a hypothesis, not a supported
backend contract. An API pricing cutoff does not by itself document the
ChatGPT-authenticated Codex default window or Codex credit policy. Record the
surface, authentication and billing route, client version, model,
instruction/tool prefix, usage events, and recovery result in the private case
ledger. Until a configuration field's product semantics are documented and
verified, keep them as an unresolved question rather than turning local
metadata into a durable prescription.

The official
[Codex configuration reference](https://learn.chatgpt.com/ja-JP/docs/config-file/config-reference)
defines `total` as counting the full active context and `body_after_prefix` as
counting only growth after the carried-over compaction-window prefix. This
resolves the scope definition; it does not establish the first-compaction
default, make the original startup prefix free, or prove that a larger manual
window is supported by the selected backend.

#### <a id="long-context-opt-in"></a>Long-context opt-in: published guidance and verification boundary

Source check: 2026-09-06. The [official model documentation](https://learn.chatgpt.com/docs/models#configure-your-default-local-model)
states that the ChatGPT desktop app, Codex CLI, and IDE extension use the same
`config.toml`. Switching from macOS desktop to CLI is not a prerequisite in the
published configuration procedure.

Tibo (@thsottiaux) published a [GPT-5.6 Sol configuration recipe](https://x.com/thsottiaux/status/2089082893804896524)
and a [follow-up announcing ChatGPT-account support](https://x.com/thsottiaux/status/2089143488696705077)
on 2026-08-16/17 (timezone-dependent). Both original posts were read directly
in a browser. The follow-up says the feature previously required API keys and
was enabled for ChatGPT accounts too. This is first-party announcement evidence,
not a backend-capacity measurement or a per-account credit specification.

The published recipe puts these keys at the top level of `~/.codex/config.toml`,
before section headers, then restarts the client and starts a new task:

```toml
model = "gpt-5.6-sol"
model_context_window = 1000000
model_auto_compact_token_limit = 900000
```

The [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
defines the selected window and compaction threshold separately. The announcement
explains the smaller default as a performance/cost choice. Keep this recipe
scoped to the named model and recheck the sources before applying it to another
model, client version, or authentication route. The installer does not enable it.

A requested budget, an accepted client/backend ceiling, the reported effective
window, and the actual compaction point remain separate measurements. A `1M`
setting is not proof that a run receives one million usable input tokens.
Verify the new task's reported window and actual behavior after an authorized
configuration change. When available, compare the same task's usage event
`token_count.info.model_context_window` with its session-turn diagnostics
`full_context_window_limit`, `auto_compact_scope_limit`, and
`auto_compact_limit_scope`. These distinguish the runtime-reported window and
resolved compaction threshold from the requested configuration. A reported
threshold is not an observed compaction event, and a numerical match with model
metadata does not by itself prove the internal capping algorithm. Keep exact
host/task observations in the owner's investigation record.

Do not copy API long-context price multipliers into a
ChatGPT Codex credit claim: the exact credit conversion remains unestablished
by these sources. Larger context also does not guarantee better recovery or
output quality. This source check did not run a long-context experiment.

When diagnosing early compaction, inventory the active context by ownership:
product-owned system/developer and built-in-tool prefix, user-controlled global
and project instructions, optional tool/MCP schemas, and accumulated turn/tool
output. Reduce the controllable always-on inputs through pointers, task-specific
reads, scoped tools, and bounded output, then remeasure with marginal A/B runs.
This can recover usable budget; it does not establish or change the
product-selected context window. Treat any inaccessible product prefix as an
explicit comparison confounder rather than assigning its cost to `SESSION.md`
or an instruction file by elimination.

**Hand-off specs from Claude to Codex.** When a Claude session hands a long
derivation or generation task to a Codex session, the spec must use the receiver's verified
effective window (conservatively the default if untested) and allow for automatic compaction: minimise the read set
and require step-wise durable commits, per
[`conventions/output-cap-death-loop.md#context-compaction-loss`](../conventions/output-cap-death-loop.md#context-compaction-loss).
A cross-vendor worker also tends to promote its findings into shared sources of
truth by default; say "no promotion, proposals go in results" explicitly and let
the requester promote after receipt
([`conventions/physics-verification-cycle.md#campaign-tooling`](../conventions/physics-verification-cycle.md#campaign-tooling) H).

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
Codex-specific overlay, not the owner's full `CLAUDE.md`. The other six
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

## <a id="git-session-provenance"></a>Git session provenance

New AI-origin commits use one vendor-neutral trailer block:

```text
Agent-Session: codex:<native-session-id>
Agent-Model: <active-runtime-model-id>
Agent-Effort: <effective-effort-or-unknown>
```

Claude uses the same keys with the `claude:` namespace. Existing
`Claude-Session:` commits remain valid legacy history; the hook preserves them
when the old message is carried through amend, rebase, or cherry-pick, and does
not add a second carrier. `git commit --amend -m` replaces the whole message;
when Git does not pass the original commit id to the hook, the amending session
becomes the new carrier. These
fields identify the transport session and inference configuration, not the
human or machine that made a judgment. Host, account, project content, and
transcript text never enter the trailer.

The [official Codex Hook contract](https://learn.chatgpt.com/docs/hooks)
(checked 2026-09-11) supplies `session_id` and the active `model` to command
hooks. It does not document an effective reasoning-effort field. The stable
public [Codex environment-variable list](https://learn.chatgpt.com/docs/config-file/environment-variables)
(checked 2026-09-11) does not include `CODEX_SESSION_ID` or `CODEX_THREAD_ID`.
Accordingly, the lifecycle adapter caches hook-supplied model metadata at
`SessionStart`, `UserPromptSubmit`, and `PreToolUse(Bash)` in machine-local
Codex state; the Git hook accepts an explicit
`CLAUDE_CONFIG_AGENT_SESSION`, `CLAUDE_CONFIG_AGENT_MODEL`, and
`CLAUDE_CONFIG_AGENT_EFFORT`, and treats the observed
`CODEX_SESSION_ID` / `CODEX_THREAD_ID` shell variables only as fail-open
compatibility probes. If the hook cache is absent, the Git hook reads only the
local Codex `threads` row whose id exactly matches the current session and
schema-probes the metadata columns before use. This read-only compatibility path
does not inspect transcript content and fails safely if the local state schema
changes.

The active model is expected because the official hook contract supplies it,
but hook delivery and local state can still both be unavailable. If neither
source resolves the model, the Git hook writes `Agent-Model: unknown`, emits a
warning, and allows the commit to continue. A configured default must not be
presented as the run's effective value. This is field-wise: one unavailable
field does not suppress the known fields in the same provenance record, and a
degraded provenance annotation does not invalidate the underlying commit. The
general record-design rule is
[`required-field-fabrication`](../docs/convention-design-principles.md#required-field-fabrication).
The placement of resolution precedence in one shared owner follows the
[`shared-field-resolver`](../docs/convention-design-principles.md#shared-field-resolver)
rule.

`scripts/setup-codex.sh --repo <path>` installs the Git hook in exact,
repeatable repositories. `--repo-root <path>` explicitly selects that
directory plus its immediate child repositories; it does not recurse or scan
the user's machine. A child symlink or child whose resolved Git top-level lies
outside the selected root is skipped; select it explicitly with `--repo` if
intended. The input path and the resolved Git top-level are separate trust
boundaries; the general rule is
[`post-resolution-scope-revalidation`](../docs/convention-design-principles.md#post-resolution-scope-revalidation).
All selected hooks are preflighted before any mutation. A
user-managed `prepare-commit-msg` makes default mode refuse the whole install;
`--replace` preserves a timestamped backup. Cloning alone still changes
nothing. `scripts/audit-codex-integration.sh --repo <path>` checks the installed
stub separately from lifecycle-Hook trust. Trust is required for the primary
automatic model cache, while the Git hook and exact-session local-state
fallback remain the commit-path mechanism.

Live dogfood on 2026-09-11 produced commit `08f0f6d` with a valid Codex session
but `Agent-Model: unknown`. The same task's exact local thread row contained
the active model, and the official hook contract also guaranteed that field.
This proved that model `unknown` was usually a transport failure rather than
the expected healthy state, and motivated the prompt-time cache, local-state
fallback, and explicit warning above. It did not prove that transport failure
is impossible, so the warning does not block the commit. A fresh task is still
required to verify live
`UserPromptSubmit` delivery; direct fixtures verify the logic in the current
task.

The repository opt-out is `git config agent.sessionTrailer false`; the legacy
`claude.sessionTrailer` and `codex.sessionTrailer` keys are also honored. The
hook remains fail-open. Missing active-model metadata becomes an explicit
`unknown` plus warning rather than a commit blocker. Therefore a missing
trailer is not proof of a human-only commit: it can also mean absent repository
wiring or an unsupported runtime, which the audit must distinguish.

### <a id="session-provenance-implementation"></a>Implementation and verification map

| Responsibility | Owning source |
| --- | --- |
| Hook event wiring | [`codex/hooks/hooks.json`](hooks/hooks.json) |
| Shared validation, precedence, cache, and exact-session fallback | [`scripts/session_provenance_cache.py`](../scripts/session_provenance_cache.py) |
| Thin lifecycle cache adapter | [`codex/hooks/session_provenance.py`](hooks/session_provenance.py) |
| Conversation stamp and SessionStart context | [`codex/hooks/session_stamp.py`](hooks/session_stamp.py), [`codex/hooks/resume_context.py`](hooks/resume_context.py) |
| Git trailer transaction | [`scripts/prepare-commit-msg-session.sh`](../scripts/prepare-commit-msg-session.sh) |
| Repository and machine-local wiring | [`scripts/install-session-trailer.sh`](../scripts/install-session-trailer.sh), [`scripts/setup-codex.sh`](../scripts/setup-codex.sh) |
| Installed-state and source-contract audits | [`scripts/audit-codex-integration.sh`](../scripts/audit-codex-integration.sh), [`scripts/check-codex-integration.py`](../scripts/check-codex-integration.py) |
| Completion-state baseline, live-remote comparison, and turn-end continuation | [`codex/hooks/session_touch.py`](hooks/session_touch.py), wired by [`codex/hooks/hooks.json`](hooks/hooks.json) |
| Behavioral regression | [`codex/hooks/codex-hooks.test.sh`](hooks/codex-hooks.test.sh), [`scripts/prepare-commit-msg-session.test.sh`](../scripts/prepare-commit-msg-session.test.sh), [`scripts/setup-codex.test.sh`](../scripts/setup-codex.test.sh), [`scripts/run-all-checks.sh`](../scripts/run-all-checks.sh) |

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

### <a id="mail-approval-boundary"></a>Mail approval and runtime boundary

An owner-selected mail skill may route Codex to an existing account gateway and
the generic [reviewed reply transaction](../conventions/gmail-sending.md#reviewed-reply-bundle).
Keep account paths, style guides, and receipts in their owning private/local
layers. No copied Claude settings or credentials are needed.

The reusable installer is `scripts/codex_mail_install.py`, with explicit
`--skill` and `--helper` paths; private installers are thin bindings. Its scope
is the mail skill link, launcher, send rule and receipt directory, separate from
the global integration installer's managed targets. Runtime selection/audit
semantics belong to [bound command runtimes](../conventions/shell-env.md#bound-command-runtime).

A distinct `send` subcommand lets a locally installed Codex
[`prefix_rule` with `decision = "prompt"`](https://learn.chatgpt.com/docs/agent-configuration/rules)
cover the canonical command prefix without matching read/preview commands.
Rules load at startup; file installation does not prove live loading or a
visible approval dialog. They govern matching commands outside the sandbox,
not arbitrary Python code or every tool path. Verify with `codex execpolicy
check`; never grant broad allow rules or bypass sandbox permissions for mail.

The [official Hook contract](https://learn.chatgpt.com/ja-JP/docs/hooks)
(checked 2026-09-06) does **not** support `PreToolUse`'s
`permissionDecision: "ask"`: it reports a failed hook and continues the tool.
Do not transplant that Claude mechanism into Codex. Explicit send approval
remains primary; fingerprints check integrity and execution rules provide a
product-controlled backstop. Neither proves human intent.

### Managed lifecycle subset

Codex provides `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
and `Stop` hooks among its lifecycle events. This integration maps only the
high-signal, product-neutral subset:

| Codex event | Managed behavior | Boundary |
| --- | --- | --- |
| `PreToolUse(apply_patch)` | Blocks Tier-A structural leak patterns while editing a repository marked public, and records the completion-gate baseline for resolved patch targets. | Git pre-commit and commit-message gates remain authoritative for all write paths; completion behavior is owned by [`#completion-git-gate-hook`](#completion-git-gate-hook). |
| `SessionStart` | Restores a compact reminder to read the active project instructions and `SESSION.md`, constructs the conversation-start identity stamp, and caches hook-supplied session/model provenance. | It reads only current hook input and local runtime facts; it does not discover personal-layer data or session history. |
| `UserPromptSubmit` | Refreshes the active model cache before every user turn, including after a model change. On the first prompt of a session only, re-injects the identity stamp as `additionalContext` (see [`#conversation-start-stamp`](#conversation-start-stamp)). | The cache step emits no output and stores only validated session/model metadata; the stamp step fires once per session and stays silent outside the workspace root. |
| `PreToolUse(Bash)` | Refreshes the machine-local session/model provenance cache and records a Git baseline for completion-gate targets. | It neither authorizes nor rewrites the command; the detailed state predicate is owned by [`#completion-git-gate-hook`](#completion-git-gate-hook). |
| `PostToolUse(apply_patch)` + `Stop` | Provides a conservative tracking fallback, then blocks one turn-end continuation when task-created dirt or local/live-remote head drift remains. At the first `Stop` of a session, also records (observe) or sends back once (block) a first turn whose replies never led with the identity stamp. | It never commits or pushes automatically; `stop_hook_active`, client trust, path resolution, and specialized execution paths bound enforcement as documented in [`#completion-git-gate-hook`](#completion-git-gate-hook). The stamp check reads only the current session's rollout and is evaluated once per session. |

This subset intentionally does **not** import owner-private deadline ledgers or
their SessionStart horizon output. Therefore, a reminder being visible in
Claude hooks does not establish reminder coverage in Codex. Time-based human
delivery must use a native Codex automation when judgment or thread continuity
is required, or a product-independent OS scheduler when the check is
deterministic and local. For local OS notifications, select the execution locus
per recipient rather than placing the job behind a shared singleton host gate
([scheduled-tasks.md#per-recipient-notification-locus](../conventions/scheduled-tasks.md#per-recipient-notification-locus)).

The managed hook-code inventory is
[`pre_tool_policy.py`](hooks/pre_tool_policy.py),
[`resume_context.py`](hooks/resume_context.py),
[`session_provenance.py`](hooks/session_provenance.py),
[`session_stamp.py`](hooks/session_stamp.py),
[`first_prompt_stamp.py`](hooks/first_prompt_stamp.py),
[`first_turn_stamp_check.py`](hooks/first_turn_stamp_check.py), and
[`session_touch.py`](hooks/session_touch.py); its regression suite is
[`codex-hooks.test.sh`](hooks/codex-hooks.test.sh).

## <a id="machine-local-provenance"></a>Machine-local provenance

### <a id="conversation-start-stamp"></a>Conversation-start identity stamp

The first user-visible reply after `startup`, `resume`, or `clear` begins with
one exact, single-line, best-effort stamp:

```text
🖥 <host> · Codex <surface|surface unknown> · account unknown · session <id8|unknown> · model <slug|unknown> · effort <level|unknown>
```

`Codex` is the fixed product identity of this integration, not best-effort
runtime metadata. It is always printed literally. An unavailable runtime field
may become `unknown`, but the product identity must not disappear with it.

The SessionStart adapter builds the remaining fields from the local hook
process hostname and the official Hook `session_id` / `model` fields. Effective
effort is used only when supplied at runtime or recovered from the session
provenance cache.
Surface is `desktop` only when the current process exposes the observed Codex
app-tools pipe; that variable is not a stable public contract, so its absence
is `surface unknown`, not an inference of CLI. The official Hook schema has no
account or surface field, and the stable public environment-variable list has
no current-account identity field. Therefore account remains literal
`account unknown` until a separately verified Codex-native account probe
exists. Claude CLI authentication or a configured default must never fill it.
Known host, surface, session, or model fields remain visible when another
field is unknown; the stamp is not an all-or-nothing record.

[`codex/hooks/session_stamp.py`](hooks/session_stamp.py) is the deterministic
fallback when lifecycle context was not delivered. It uses the same
exact-session, read-only local-state resolver after the primary hook cache, so
a valid local Codex task does not lose its active model merely because context
injection was missed. Global instructions require it as the first tool call
and require its output to lead the first reply unchanged. A compaction boundary
restores work context but does not restamp. Hook installation and model-visible
delivery remain separate evidence; a new task after trust review is the
end-to-end activation test.

Two more adapters reuse the Claude-side logic in
[`scripts/first_reply_stamp.py`](../scripts/first_reply_stamp.py), so both
products apply one predicate. [`first_prompt_stamp.py`](hooks/first_prompt_stamp.py)
re-injects the same stamp right after the first user prompt, where it is closer
to the first reply than the SessionStart context. [`first_turn_stamp_check.py`](hooks/first_turn_stamp_check.py)
runs at the first `Stop` and checks whether any reply in that turn led with the
stamp, reading the event's `transcript_path` when supplied, otherwise the
session's own rollout located by session id; `last_assistant_message` is also
counted when supplied. Sub-agent rollouts are skipped. Its mode (`observe`
records only, `block` sends one continuation) is shared with Claude through
`DEFAULT_STOP_MODE` and `FIRST_REPLY_STAMP_STOP`. The workspace-root scope, the
opt-out, and the measured failure pattern that motivated both steps are in
[`multi-account-machine-surface.md#first-reply-stamp-mechanism`](../conventions/multi-account-machine-surface.md#first-reply-stamp-mechanism).
Their behavior is fixture-tested; live Codex delivery of the UserPromptSubmit
context still awaits a fresh task after trust review.

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
atomicity, session/model cache behavior, Claude/Codex/unknown Git trailer
paths, and dirty-worktree nudge de-duplication/reset. They run through the
repository's aggregate local checks and CI.

Codex requires review and trust for changed user hooks. Treat an installed
`hooks.json` as configured, not as verified active, until the client has
accepted that trust review. The audit reports installation state only.

## Deliberate non-equivalences

The following Claude-only mechanisms are intentionally not copied or emulated
as hidden background processes:

- Claude-specific memory guards and its account-discovery mechanism, because
  their target paths and account state belong to Claude rather than Codex.
  Codex has the narrower best-effort conversation stamp above and reports its
  missing account honestly;
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
