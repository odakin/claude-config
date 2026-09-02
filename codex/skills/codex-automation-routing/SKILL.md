---
name: codex-automation-routing
description: Route and create Codex reminders, scheduled tasks, recurring checks, monitors, follow-ups, and event-triggered work. Use when the user says remind me, check later, keep watching, run this daily, wake this task, automate this, or asks for the Codex equivalent of Claude routines. Prefer a same-task heartbeat for conversational follow-ups; do not fake unsupported app-event triggers with polling unless the user chooses polling.
---

# Codex automation routing

Use the native Codex automation surface without copying Claude routines or
their account configuration. The durable contract is
`codex/PARITY.md#codex-integration-sot`, especially its
`#native-automation-routing` section, in the containing
`claude-config` repository; resolve the repository three directories above
this file and read that section before creating or changing an automation.

## Route by trigger and execution locus

- Use a **heartbeat** for a reminder, recurring monitor, or follow-up that
  should return to the current task with its existing context. This is the
  default unless the user explicitly requests a separate task.
- Use a standalone **cron automation** for independent repeated project work.
  Resolve the saved project first. Prefer a worktree for a Git repository and
  local execution for a non-Git project, unless the user explicitly chooses
  otherwise.
- Use the operating system scheduler for deterministic local scripts that do
  not need model judgment. Route to
  `conventions/scheduled-tasks.md#execution-locus-selection` for that design.
- Use lifecycle Hooks only for deterministic Codex tool/session events, not
  elapsed-time reminders.
- Gmail, Slack, and GitHub activity triggers belong to ChatGPT Web or Mobile
  when supported there. The desktop automation surface cannot create them or
  combine an event trigger with a time schedule. Explain that boundary; offer
  periodic polling only as an explicit fallback with a sensible interval.

## Create or update safely

1. Inspect the existing local automation definitions before creating one.
   Update the matching automation instead of adding a duplicate.
2. Use the app's automation tool. Do not write automation files or raw schedule
   directives by hand, and do not expose raw recurrence syntax to the user.
   Treat a suggestion card as proposed, not active. Claim registration only
   after the native result returns an automation identifier and active status.
3. Preserve fields the user did not ask to change. Do not override model or
   reasoning settings unless requested or required by the native schema.
4. Make the replayed prompt self-contained: state the scope, evidence to
   inspect, success and report conditions, what counts as unchanged, when to
   stop, and when user input is required.
5. Keep notification preferences out of the replayed prompt. Apply them through
   the automation's notification policy.
6. For local files, note that the selected host and Codex app must be available
   when the run starts.

Read-only checking and drafting may run unattended. Sending messages,
publishing, deleting, purchasing, or another consequential external write
still needs the authority applicable at execution time unless the user has
explicitly authorized that exact recurring action.

After the tool succeeds, report the human-readable schedule, target, next
behavior, and stop condition. If the product cannot express the requested
trigger, say so rather than claiming an inactive mechanism is installed.
