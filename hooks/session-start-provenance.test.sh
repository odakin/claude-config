#!/usr/bin/env bash
# session-start-provenance.test.sh — Claude session model cache の fixture test

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# Report the failing line and command instead of a silent exit 1.
. "$SCRIPT_DIR/../scripts/lib/test-err-trap.sh"
HOOK="$SCRIPT_DIR/session-start-provenance.py"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT
STATE_DIR="$TEMP_ROOT/state"
SID="claude-test-session"

out="$(
  printf '%s' '{"hook_event_name":"SessionStart","session_id":"claude-test-session","model":"claude-opus-test[1m]"}' \
    | CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$STATE_DIR" python3 "$HOOK"
)"
[ -z "$out" ]
grep -qx 'model=claude-opus-test\[1m\]' "$STATE_DIR/$SID.env"

# Later input without model must not erase the SessionStart value.
printf '%s' '{"hook_event_name":"PreToolUse","session_id":"claude-test-session","effort":{"level":"high"}}' \
  | CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$STATE_DIR" python3 "$HOOK"
grep -qx 'model=claude-opus-test\[1m\]' "$STATE_DIR/$SID.env"
grep -qx 'effort=high' "$STATE_DIR/$SID.env"

# Invalid metadata is a silent fail-open and must not create a path outside the state dir.
printf '%s' '{"hook_event_name":"SessionStart","session_id":"../bad","model":"bad model"}' \
  | CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$STATE_DIR" python3 "$HOOK"
[ ! -e "$TEMP_ROOT/bad.env" ]

echo "session-start provenance tests passed"
