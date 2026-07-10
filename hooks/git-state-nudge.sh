#!/usr/bin/env bash
# git-state-nudge.sh — PostToolUse(Bash): 直近 commit の未 push 検出 + first-sighting で fetch+stale 検出
#
# PostToolUse(Bash) hook: nudge Claude when a git repo has state needing
# attention. The hook is the SOLE git-state monitor — it subsumes the
# former SessionStart hook (`session-git-check.sh`) by performing a
# one-time `git fetch` on first-sighting of a repo, so remote-divergence
# detection still happens but without the noise of a notification on
# every session startup.
#
# Cases handled (per repo, in priority order):
#
#   (1) "Orphan tree on origin" — HEAD has NO common ancestor with @{u}.
#       This is the unambiguous signature of a re-init force-push from
#       elsewhere (a failure mode that previously fooled Claude on
#       2026-04-07 into interpreting AHEAD commits as "missing push"
#       instead of orphans on a force-rewritten remote). The nudge tells
#       Claude that AHEAD commits are likely ORPHANED, not unpushed,
#       and to investigate before pushing.
#       NOTE: an earlier version also detected `forced-update` in the
#       origin/<branch> reflog, but that was too eager — the reflog entry
#       persists for ~90 days even after `git reset --hard` resolves the
#       issue, causing perpetual re-warning. The merge-base check is
#       dynamic and auto-clears.
#
#   (2) "Just committed but not pushed" — HEAD ahead of upstream AND
#       last commit within the last 60 seconds. Enforces CONVENTIONS §4
#       "コミット後は常に push" by surfacing a reminder right after the
#       commit, when there is no excuse to defer.
#
#   (3) "First sighting of an out-of-sync repo (within the last 4 hours)"
#       — first time the hook sees this repo within SEEN_THRESHOLD, AND
#       (AHEAD > 0, BEHIND > 0, or STALE_DIRT). Catches the case where
#       the session base directory is not a git repo (e.g. ~/Claude)
#       and Claude cd's into a sub-repo that already had unresolved
#       divergence or abandoned WIP.
#       The 4-hour window is a deliberate cross-session choice to avoid
#       spamming when the user opens multiple short sessions in quick
#       succession. On first sighting, a one-time `git fetch` (5s
#       timeout) is run so the BEHIND check sees fresh remote state.
#
#       NOTE on STALE_DIRT (added 2026-04-08): an earlier version of
#       case (3) stripped DIRTY_COUNT entirely for noise reduction
#       (most WIP is intentional and Claude runs `git status` anyway).
#       The 2026-04-08 refinement re-adds a *narrower* dirty signal:
#       STALE_DIRT, defined as "the same porcelain set unchanged for
#       >24h". This catches cross-session WIP leakage (the failure
#       mode found during the 2026-04-08 morning sweep) WITHOUT
#       re-introducing the original noise — active multi-day refactors
#       continually mutate the dirty set, so their porcelain hash is
#       never stale and no warning fires. Per-hash NUDGED guard
#       prevents repeat warnings for an intentionally-persistent
#       dirty set across sessions.
#       Mtime-based detection was rejected because it is fooled by
#       build artifact rebuilds (e.g. .pdf regenerated from a stale
#       .tex shows a "fresh" mtime even though the .tex hasn't been
#       touched, leaving the genuinely-stale source invisible).
#       Bootstrap caveat: pre-existing dirt at the time this feature
#       was deployed is not warned for ~24h after deployment, since
#       age starts fresh on the first observation. Future leakage is
#       caught immediately.
#
# Multi-repo follow (Fix B, 2026-04-07):
#   The hook reads the bash command from the Claude Code hook protocol
#   stdin JSON and additionally checks any literal `git -C <path>` and
#   `git --git-dir=<path>` targets. Variable-substituted paths (e.g.
#   `git -C "$d"` inside a for loop) are NOT resolved — those will only
#   be checked if cwd later changes into the repo. A diagnostic line is
#   emitted when `git -C` is seen but no literal path could be
#   extracted, so Claude knows the safety net is partial for that call.
#
# Silent when:
#   - All inspected repos are clean and in sync
#   - Already nudged for the same HEAD sha (cases 1, 2 — push and
#     orphan-tree reminders share NUDGED_FILE keyed by HEAD sha)
#   - Already nudged for the same porcelain hash (case 3 STALE_DIRT —
#     a separate state file STATE_DIR/<repo>.stale-nudged keyed by
#     porcelain hash, not HEAD sha; see "Suppression scopes" below)
#   - Repo has been seen recently (within 4h) AND HEAD has not advanced
#
# Design notes:
#   - First-sighting branch does ONE `git fetch` per repo (5s timeout).
#     Subsequent calls within the 4h window skip fetch entirely → fast.
#   - State is kept in $HOME/.claude/state/git-nudge/ as small marker
#     files. Cross-session state is acceptable here — the goal is to
#     avoid re-nudging within minutes, not enforce per-session freshness.
#   - Output to stdout is injected into the session as context (per the
#     Claude Code hook spec for PostToolUse).
#
# Suppression scopes (two independent mechanisms):
#   1. Per-HEAD-sha NUDGED_FILE — used by case (1) orphan-tree and
#      case (2) just-committed-not-pushed. Each HEAD produces at most
#      ONE warning of each kind, no matter how many Bash calls follow.
#      Case (1) uses suffix "-orphan" so the orphan-tree warning and
#      the push reminder don't shadow each other for the same HEAD.
#   2. Per-porcelain-hash STALE_NUDGED_FILE — used by case (3)
#      STALE_DIRT. The key is the sha1 of `git status --porcelain`
#      output, NOT HEAD sha, because abandoned WIP can persist across
#      many HEADs (the user keeps committing other things) and a
#      single HEAD can host many distinct dirty sets over its
#      lifetime. Each "dirty episode" deserves at most one warning,
#      scoped to the porcelain hash itself. The marker is cleared
#      whenever the working tree becomes clean, so a recurring hash
#      after a clean state warns anew.

set -uo pipefail
# NOTE: deliberately NOT using `set -e`. The hook contains many `grep`
# and `git` calls that may legitimately exit non-zero (no match, no
# upstream, etc.); set -e would kill the hook on the first such call.
# Each command that needs failure handling does so explicitly.

STATE_DIR="$HOME/.claude/state/git-nudge"
mkdir -p "$STATE_DIR" 2>/dev/null || exit 0

NOW="$(date +%s)"
SEEN_THRESHOLD=14400  # 4 hours
RECENT_COMMIT_WINDOW=60  # seconds

# ----------------------------------------------------------------------
# check_repo_state <repo_root> <label_prefix>
#
# Inspects the repo at <repo_root> and emits warnings to stdout for any
# of cases (1)-(3) above. <label_prefix> is prepended to the repo path
# in output (empty for cwd, "[git -C] " for follow targets).
# Returns 0 always; never fatal.
# ----------------------------------------------------------------------
check_repo_state() {
  local REPO_ROOT="$1"
  local LABEL_PREFIX="$2"

  [ -z "$REPO_ROOT" ] && return 0
  [ -d "$REPO_ROOT/.git" ] || [ -f "$REPO_ROOT/.git" ] || return 0

  # Per-repo state markers (sha1 of repo path → filename).
  local REPO_HASH
  if command -v shasum >/dev/null 2>&1; then
    REPO_HASH="$(printf '%s' "$REPO_ROOT" | shasum | cut -d' ' -f1)"
  elif command -v sha1sum >/dev/null 2>&1; then
    REPO_HASH="$(printf '%s' "$REPO_ROOT" | sha1sum | cut -d' ' -f1)"
  else
    REPO_HASH="$(printf '%s' "$REPO_ROOT" | tr '/' '_')"
  fi
  local SEEN_FILE="$STATE_DIR/$REPO_HASH.seen"
  local NUDGED_FILE="$STATE_DIR/$REPO_HASH.nudged"

  # Determine first-sighting status (within SEEN_THRESHOLD).
  local FIRST_SIGHTING=0
  if [ ! -f "$SEEN_FILE" ]; then
    FIRST_SIGHTING=1
  else
    local SEEN_MTIME
    # BSD/GNU stat 両対応 (数値検証分岐、 stale-read-nudge.sh と同 fix、 2026-07-10)
    SEEN_MTIME="$(stat -f %m "$SEEN_FILE" 2>/dev/null)"
    case "$SEEN_MTIME" in ''|*[!0-9]*) SEEN_MTIME="$(stat -c %Y "$SEEN_FILE" 2>/dev/null)" ;; esac
    case "$SEEN_MTIME" in ''|*[!0-9]*) SEEN_MTIME="$NOW" ;; esac
    local SEEN_AGE=$((NOW - SEEN_MTIME))
    [ "$SEEN_AGE" -gt "$SEEN_THRESHOLD" ] && FIRST_SIGHTING=1
  fi
  touch "$SEEN_FILE" 2>/dev/null || true

  # On first sighting, do a one-time `git fetch` (with short timeout).
  if [ "$FIRST_SIGHTING" -eq 1 ]; then
    if command -v timeout >/dev/null 2>&1; then
      timeout 5 git -C "$REPO_ROOT" fetch --quiet 2>/dev/null || true
    elif command -v gtimeout >/dev/null 2>&1; then
      gtimeout 5 git -C "$REPO_ROOT" fetch --quiet 2>/dev/null || true
    else
      git -C "$REPO_ROOT" fetch --quiet 2>/dev/null || true
    fi
  fi

  # Gather repo state.
  local UPSTREAM
  UPSTREAM="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref '@{u}' 2>/dev/null || echo '')"
  local DIRTY_COUNT
  DIRTY_COUNT="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  local AHEAD=0 BEHIND=0
  if [ -n "$UPSTREAM" ]; then
    AHEAD="$(git -C "$REPO_ROOT" rev-list --count "$UPSTREAM..HEAD" 2>/dev/null || echo 0)"
    BEHIND="$(git -C "$REPO_ROOT" rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)"
  fi

  # Stale-dirt detection (porcelain-hash-age based — see header comment).
  # The signal is: "the same set of dirty files has been here, unchanged,
  # for >24h". The porcelain output is hashed and stored under STATE_DIR;
  # the hash file's mtime is the timestamp of *first* observation of this
  # exact set, so age accumulates as long as the set stays identical.
  # Active editing mutates the set → file is rewritten → age resets.
  local STALE_DIRT=0
  local PAGE_HOURS=0
  local PORCELAIN_FILE="$STATE_DIR/$REPO_HASH.porcelain"
  local STALE_NUDGED_FILE="$STATE_DIR/$REPO_HASH.stale-nudged"
  if [ "$DIRTY_COUNT" -gt 0 ]; then
    local PORCELAIN_HASH=""
    if command -v shasum >/dev/null 2>&1; then
      PORCELAIN_HASH="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | shasum | cut -d' ' -f1)"
    elif command -v sha1sum >/dev/null 2>&1; then
      PORCELAIN_HASH="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | sha1sum | cut -d' ' -f1)"
    fi
    local PORCELAIN_LAST=""
    [ -f "$PORCELAIN_FILE" ] && PORCELAIN_LAST="$(cat "$PORCELAIN_FILE" 2>/dev/null || echo '')"
    if [ -n "$PORCELAIN_HASH" ] && [ "$PORCELAIN_LAST" = "$PORCELAIN_HASH" ]; then
      # Same dirty set as last seen — measure how long it has persisted.
      local PMTIME PAGE
      # BSD/GNU stat 両対応 (数値検証分岐、 同上)
      PMTIME="$(stat -f %m "$PORCELAIN_FILE" 2>/dev/null)"
      case "$PMTIME" in ''|*[!0-9]*) PMTIME="$(stat -c %Y "$PORCELAIN_FILE" 2>/dev/null)" ;; esac
      case "$PMTIME" in ''|*[!0-9]*) PMTIME="$NOW" ;; esac
      PAGE=$((NOW - PMTIME))
      PAGE_HOURS=$((PAGE / 3600))
      if [ "$PAGE" -gt 86400 ]; then
        STALE_DIRT=1
        # Per-hash NUDGED guard: don't repeat the same warning for the
        # same dirty set (e.g. user intentionally leaves WIP in a
        # scratch repo). The guard is cleared when the set changes or
        # when the working tree becomes clean.
        local LAST_WARNED_HASH=""
        [ -f "$STALE_NUDGED_FILE" ] && LAST_WARNED_HASH="$(cat "$STALE_NUDGED_FILE" 2>/dev/null || echo '')"
        [ "$LAST_WARNED_HASH" = "$PORCELAIN_HASH" ] && STALE_DIRT=0
      fi
    elif [ -n "$PORCELAIN_HASH" ]; then
      # New or changed dirty set — record current state, age starts at 0.
      echo "$PORCELAIN_HASH" > "$PORCELAIN_FILE" 2>/dev/null || true
    fi
  elif [ -f "$PORCELAIN_FILE" ] || [ -f "$STALE_NUDGED_FILE" ]; then
    # Working tree clean — discard porcelain markers so each dirty
    # episode is treated independently (same hash recurring later
    # should warn anew, not be silently suppressed by stale state).
    rm -f "$PORCELAIN_FILE" "$STALE_NUDGED_FILE" 2>/dev/null || true
  fi

  # Fix A (2026-04-07, refined): detect orphan-tree only.
  # An earlier version also grep'd `git reflog -1 origin/main` for the
  # string `forced-update`, but that was too eager: the reflog entry is
  # historical and persists for ~90 days. After resolving the divergence
  # by `git reset --hard`, the warning kept firing. The `merge-base`
  # check below is dynamic — it auto-clears when state is resolved.
  # Generic ahead/behind divergence (e.g. rebase force-push that does
  # share a merge-base) is caught by case (3) first-sighting, with the
  # interpretation discipline in push-workflow.md telling Claude to run
  # the 4 queries before assuming "push 忘れ".
  local ORPHAN_TREE=0
  if [ -n "$UPSTREAM" ] && [ "$AHEAD" -gt 0 ] && [ "$BEHIND" -gt 0 ]; then
    if ! git -C "$REPO_ROOT" merge-base HEAD "$UPSTREAM" >/dev/null 2>&1; then
      ORPHAN_TREE=1
    fi
  fi

  local HEAD_SHA HEAD_TS HEAD_AGE
  HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo '')"
  HEAD_TS="$(git -C "$REPO_ROOT" log -1 --format=%ct HEAD 2>/dev/null || echo 0)"
  HEAD_AGE=999999
  [ "$HEAD_TS" -gt 0 ] && HEAD_AGE=$((NOW - HEAD_TS))

  local ALREADY_NUDGED_SHA=""
  [ -f "$NUDGED_FILE" ] && ALREADY_NUDGED_SHA="$(cat "$NUDGED_FILE" 2>/dev/null || echo '')"

  # Decision logic — case (1) [orphan-tree] takes top priority.
  local ORPHAN_NUDGE=0
  local RECENT_COMMIT_NUDGE=0
  local FIRST_SIGHTING_NUDGE=0

  if [ "$ORPHAN_TREE" -eq 1 ] && [ "$ALREADY_NUDGED_SHA" != "${HEAD_SHA}-orphan" ]; then
    ORPHAN_NUDGE=1
  fi

  if [ "$AHEAD" -gt 0 ] && [ "$HEAD_AGE" -le "$RECENT_COMMIT_WINDOW" ] \
     && [ "$ALREADY_NUDGED_SHA" != "$HEAD_SHA" ]; then
    RECENT_COMMIT_NUDGE=1
  fi

  # Refined case (3): fire on AHEAD/BEHIND (divergence) OR STALE_DIRT
  # (porcelain hash unchanged for >24h). Plain DIRTY_COUNT > 0 still
  # does NOT trigger — see header comment for the rationale of the
  # narrower stale-dirt signal.
  if [ "$FIRST_SIGHTING" -eq 1 ]; then
    if [ "$AHEAD" -gt 0 ] || [ "$BEHIND" -gt 0 ] || [ "$STALE_DIRT" -eq 1 ]; then
      FIRST_SIGHTING_NUDGE=1
    fi
  fi

  # ---- Emit ----
  # Case (1): orphan-tree (highest priority). Concise — emit just enough
  # for Claude to recognize the situation and investigate.
  if [ "$ORPHAN_NUDGE" -eq 1 ]; then
    printf '[git-nudge] %s%s\n' "$LABEL_PREFIX" "$REPO_ROOT"
    printf '  - ORPHAN TREE: HEAD has NO common ancestor with %s\n' "$UPSTREAM"
    printf '  - This signals a remote re-init / force-push, not "push 忘れ".\n'
    printf '    INVESTIGATE before pushing — your %s AHEAD commit(s) may be ORPHANED.\n' "$AHEAD"
    echo "${HEAD_SHA}-orphan" > "$NUDGED_FILE" 2>/dev/null || true
    return 0
  fi

  # Case (2): just-committed-not-pushed.
  #
  # Default: nudge only (per CONVENTIONS §4「コミット後は常に push」—
  # recommendation, not strict enforcement).
  #
  # Opt-in auto-push (2026-04-14): set CLAUDE_GIT_AUTO_PUSH=1 in the
  # environment and the hook itself will run `git push` after any commit
  # that's AHEAD>0 / BEHIND=0. Users with strict "commit → push atomicity"
  # discipline typically want this; default claude-config users can stay
  # with nudge-only.
  # BEHIND > 0 always falls back to nudge (rebase first).
  if [ "$RECENT_COMMIT_NUDGE" -eq 1 ]; then
    printf '[git-nudge] %s%s\n' "$LABEL_PREFIX" "$REPO_ROOT"
    printf '  - You just committed (%ss ago); HEAD is %s commit(s) ahead of %s.\n' \
      "$HEAD_AGE" "$AHEAD" "$UPSTREAM"
    if [ "$BEHIND" -gt 0 ]; then
      printf '  - DIVERGED: also %s commit(s) BEHIND %s.\n' "$BEHIND" "$UPSTREAM"
      printf '  - Run `git pull --rebase` first, then `git push`. A plain push\n'
      printf '    will be rejected as non-fast-forward. (auto-push skipped)\n'
    elif [ "${CLAUDE_GIT_AUTO_PUSH:-0}" = "1" ]; then
      # Attempt auto-push (opt-in). Timeout guards against credential
      # prompts / hung network. Output captured to be shown in nudge.
      local PUSH_OUT PUSH_RC
      PUSH_OUT="$(cd "$REPO_ROOT" && timeout 20 git push 2>&1)"
      PUSH_RC=$?
      if [ "$PUSH_RC" -eq 0 ]; then
        printf '  - Auto-pushed (CLAUDE_GIT_AUTO_PUSH=1).\n'
      else
        printf '  - AUTO-PUSH FAILED (rc=%s). Investigate:\n' "$PUSH_RC"
        printf '%s\n' "$PUSH_OUT" | sed 's/^/      /'
        printf '  - Resolve and push manually before continuing.\n'
      fi
    else
      printf '  - Per CONVENTIONS §4: コミット後は常に push. Run `git push` now\n'
      printf '    unless you are intentionally stacking commits.\n'
      printf '  - (Opt-in: export CLAUDE_GIT_AUTO_PUSH=1 to have this hook auto-push.)\n'
    fi
    echo "$HEAD_SHA" > "$NUDGED_FILE" 2>/dev/null || true
    return 0
  fi

  # Case (3): first-sighting of stale state.
  if [ "$FIRST_SIGHTING_NUDGE" -eq 1 ]; then
    printf '[git-nudge] %s%s (first time touching this repo within ~4h)\n' "$LABEL_PREFIX" "$REPO_ROOT"
    if [ "$STALE_DIRT" -eq 1 ]; then
      printf '  - %s dirty file(s), unchanged set for ~%dh — possibly abandoned WIP from an earlier session\n' \
        "$DIRTY_COUNT" "$PAGE_HOURS"
      # Record warned hash so we don't repeat for the same dirty set.
      # Re-read PORCELAIN_FILE to avoid relying on in-memory variable
      # scope (the detection block above writes the hash to that file
      # only when it changes; the value is current here regardless).
      local _ph
      _ph="$(cat "$PORCELAIN_FILE" 2>/dev/null || echo '')"
      [ -n "$_ph" ] && echo "$_ph" > "$STALE_NUDGED_FILE" 2>/dev/null || true
    elif [ "$DIRTY_COUNT" -gt 0 ]; then
      printf '  - %s uncommitted change(s) inherited from earlier work\n' "$DIRTY_COUNT"
    fi
    if [ "$AHEAD" -gt 0 ]; then
      printf '  - AHEAD by %s commit(s) — investigate and push if appropriate\n' "$AHEAD"
    fi
    if [ "$BEHIND" -gt 0 ]; then
      printf '  - BEHIND by %s commit(s) — pull before working\n' "$BEHIND"
    fi
    printf '  - Investigate this state before starting work; do not silently overwrite or commit on top.\n'
    return 0
  fi

  return 0
}

# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

# Read the bash command from the Claude Code hook protocol stdin JSON.
# Failures (no stdin, no jq, malformed JSON) → BASH_CMD stays empty.
BASH_CMD=""
if command -v jq >/dev/null 2>&1 && [ ! -t 0 ]; then
  STDIN_JSON="$(cat 2>/dev/null || true)"
  if [ -n "$STDIN_JSON" ]; then
    BASH_CMD="$(printf '%s' "$STDIN_JSON" | jq -r '.tool_input.command // empty' 2>/dev/null || echo '')"
  fi
fi

# Track repos already inspected so we don't double-warn for cwd + git -C
# pointing at the same place.
CHECKED_REPOS=""

# Check 1: cwd, if it's inside a git work tree.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  CWD_REPO="$(git rev-parse --show-toplevel 2>/dev/null || echo '')"
  if [ -n "$CWD_REPO" ]; then
    check_repo_state "$CWD_REPO" ""
    CHECKED_REPOS="|$CWD_REPO|"
  fi
fi

# Check 2 (Fix B, 2026-04-07): literal `git -C <path>` and
# `git --git-dir=<path>` targets in the bash command. Variable
# substitutions ($var, ${var}, "$var") are NOT resolved — those will
# fall back to cwd-based detection on later calls.
if [ -n "$BASH_CMD" ]; then
  # Match unquoted literal paths (no whitespace, no shell metachars).
  PATHS_UNQUOTED="$(printf '%s\n' "$BASH_CMD" \
    | grep -oE 'git +(-C +|--git-dir=)[A-Za-z0-9._/~-]+' 2>/dev/null \
    | sed -E 's/^git +(-C +|--git-dir=)//' || true)"
  # Match double-quoted literal paths (no $ inside, so excludes "$d").
  PATHS_QUOTED="$(printf '%s\n' "$BASH_CMD" \
    | grep -oE 'git +(-C +|--git-dir=)"[^"$]+"' 2>/dev/null \
    | sed -E 's/^git +(-C +|--git-dir=)"//; s/"$//' || true)"

  ALL_PATHS="$(printf '%s\n%s\n' "$PATHS_UNQUOTED" "$PATHS_QUOTED" | grep -v '^$' || true)"

  # NOTE: an earlier version emitted a `[git-nudge:hint]` message when
  # `git -C` was seen but no literal path could be extracted (e.g.
  # `git -C "$d"` in a loop). It was deliberately removed as noise:
  # the hint fires on every variable-substituted git -C call but never
  # corresponds to an actual problem — it's just teaching, and the user
  # only needs to be taught once. Variable-path operations are now
  # silently uncovered by the hook; the user can `cd <repo> && git ...`
  # if they want safety-net warnings.

  if [ -n "$ALL_PATHS" ]; then
    while IFS= read -r path; do
      [ -z "$path" ] && continue
      # Tilde expansion (~/foo → $HOME/foo). Only handles leading "~/"
      # since ~user/ is rarely used in `git -C` arguments.
      case "$path" in
        "~/"*) path="${HOME}/${path:2}" ;;
        "~")   path="${HOME}" ;;
      esac
      # Resolve to absolute path.
      if [ -d "$path" ]; then
        ABS_PATH="$(cd "$path" 2>/dev/null && pwd)" || continue
      else
        continue
      fi
      # Verify it's a git repo and get the work tree root.
      git -C "$ABS_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue
      REPO_ROOT="$(git -C "$ABS_PATH" rev-parse --show-toplevel 2>/dev/null || echo '')"
      [ -z "$REPO_ROOT" ] && continue
      # Skip if already checked (cwd or earlier `git -C` target).
      case "$CHECKED_REPOS" in
        *"|$REPO_ROOT|"*) continue ;;
      esac
      check_repo_state "$REPO_ROOT" "[git -C] "
      CHECKED_REPOS="${CHECKED_REPOS}${REPO_ROOT}|"
    done <<< "$ALL_PATHS"
  fi
fi

# ----------------------------------------------------------------------
# claude-config update notifier (2026-04-07)
# ----------------------------------------------------------------------
# Detect when this machine's claude-config clone has advanced past the
# last HEAD this hook saw, and show what changed + what action (if any)
# the user should take. Triggered by `git pull` of claude-config: the
# pull updates the working tree, the symlinked hook source is
# automatically live, and the next Bash call here notices the HEAD move.
#
# Why this lives inside git-state-nudge.sh and not in a separate hook
# or script: this hook already fires on every Bash call and is
# auto-updated via the ~/.claude/hooks symlink. Adding a new hook would
# require setup.sh to install it, which has a chicken-and-egg problem
# on machines where the new install hasn't run yet. Putting it here
# means: pull → next Bash call → notification, no extra steps.
#
# Silent on:
#   - claude-config not present
#   - HEAD unchanged since last check
#
# First run (no marker file): emits a one-line welcome with current
# HEAD, no diff (we don't know what to compare against).

CC_DIR="$HOME/Claude/claude-config"
if [ -d "$CC_DIR/.git" ]; then
  CC_HEAD="$(git -C "$CC_DIR" rev-parse HEAD 2>/dev/null || echo '')"
  CC_MARKER="$STATE_DIR/claude-config.last-head"
  CC_LAST=""
  [ -f "$CC_MARKER" ] && CC_LAST="$(cat "$CC_MARKER" 2>/dev/null || echo '')"

  if [ -n "$CC_HEAD" ] && [ "$CC_HEAD" != "$CC_LAST" ]; then
    # Persist new HEAD before printing, so a hook crash mid-print doesn't
    # cause repeated re-display on every subsequent Bash call.
    echo "$CC_HEAD" > "$CC_MARKER" 2>/dev/null || true

    if [ -z "$CC_LAST" ]; then
      # First run after this notifier was deployed. Just announce.
      printf '[claude-config] update notifier active (HEAD %s)\n' "${CC_HEAD:0:7}"
      printf '  - From now on, this hook will tell you what changed when you `git pull`\n'
      printf '  - Check ~/Claude/claude-config/SESSION.md for recent activity\n'
    else
      # Subsequent run: claude-config moved. Show what changed and what to do.
      printf '[claude-config] HEAD moved %s -> %s — recent commits:\n' \
        "${CC_LAST:0:7}" "${CC_HEAD:0:7}"
      git -C "$CC_DIR" log --no-merges --format='  · %h %s' "$CC_LAST..$CC_HEAD" 2>/dev/null \
        | head -10

      CHANGED="$(git -C "$CC_DIR" diff --name-only "$CC_LAST" "$CC_HEAD" 2>/dev/null || echo '')"
      ACTION_NEEDED=0

      if printf '%s' "$CHANGED" | grep -qE '^setup\.sh' 2>/dev/null; then
        printf '  ⚠ setup.sh changed → re-run: `cd ~/Claude/claude-config && ./setup.sh`\n'
        ACTION_NEEDED=1
      fi
      if printf '%s' "$CHANGED" | grep -qE '^hooks/' 2>/dev/null; then
        printf '  ℹ hooks/ source updated (auto-live via symlink, no restart)\n'
      fi
      if printf '%s' "$CHANGED" | grep -qE '^conventions/' 2>/dev/null; then
        printf '  ℹ conventions/ updated — read git log above for impact\n'
      fi
      if printf '%s' "$CHANGED" | grep -qE '^CONVENTIONS\.md$' 2>/dev/null; then
        printf '  ℹ CONVENTIONS.md updated — read git log above for impact\n'
      fi
      # If setup.sh changed, also imply potential settings.json reshape
      if [ "$ACTION_NEEDED" -eq 1 ]; then
        printf '  ⚠ After re-running setup.sh, restart Claude Code if settings.json changed\n'
      fi
      printf '  - Full details: ~/Claude/claude-config/SESSION.md\n'
    fi
  fi
fi

exit 0
