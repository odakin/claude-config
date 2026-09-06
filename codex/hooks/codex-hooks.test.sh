#!/usr/bin/env bash
# codex-hooks.test.sh — Codex hook schema and adapter behavior tests

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT

python3 -m json.tool "$SCRIPT_DIR/hooks.json" >/dev/null
grep -q 'pre_tool_policy.py' "$SCRIPT_DIR/hooks.json"
grep -q 'resume_context.py' "$SCRIPT_DIR/hooks.json"
grep -q 'session_touch.py' "$SCRIPT_DIR/hooks.json"

PUBLIC_REPO="$TEMP_ROOT/public"
mkdir -p "$PUBLIC_REPO/.git" "$PUBLIC_REPO/.claude"
touch "$PUBLIC_REPO/.claude/public-repo.marker"
make_pretool_input() {
  TEST_REPO="$1" TEST_KIND="$2" python3 - <<'PY'
import json
import os

values = {
    "email": "owner" + "@" + "example.edu",
    "absolute-path": "/Users/" + "owner",
    "ipv4": "203.0.113." + "9",
    "token": "gh" + "p_" + ("a" * 30),
    "discord": "<@" + "123456789012345678" + ">",
    "allowlisted-email": "noreply" + "@" + "github.com",
    "removed-email": "owner" + "@" + "example.edu",
}
kind = os.environ["TEST_KIND"]
prefix = "-" if kind == "removed-email" else "+"
command = (
    "*** Begin Patch\n"
    "*** Update File: README.md\n"
    "@@\n"
    f"{prefix}{values[kind]}\n"
    "*** End Patch"
)
print(
    json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "cwd": os.environ["TEST_REPO"],
            "tool_input": {"command": command},
        }
    )
)
PY
}

assert_denied() {
  local kind="$1"
  local expected_category="$2"
  local output="$TEMP_ROOT/deny-${kind}.json"
  make_pretool_input "$PUBLIC_REPO" "$kind" |
    python3 "$SCRIPT_DIR/pre_tool_policy.py" > "$output"
  python3 - "$output" "$expected_category" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
result = payload["hookSpecificOutput"]
assert result["hookEventName"] == "PreToolUse"
assert result["permissionDecision"] == "deny"
assert sys.argv[2] in result["permissionDecisionReason"]
PY
}

assert_silent() {
  local repository="$1"
  local kind="$2"
  local output="$TEMP_ROOT/silent-${kind}.json"
  make_pretool_input "$repository" "$kind" |
    python3 "$SCRIPT_DIR/pre_tool_policy.py" > "$output"
  [ ! -s "$output" ]
}

assert_denied email email
assert_denied absolute-path 'absolute macOS path'
assert_denied ipv4 'public IPv4 address'
assert_denied token 'token prefix'
assert_denied discord 'Discord identifier'
assert_silent "$PUBLIC_REPO" allowlisted-email
assert_silent "$PUBLIC_REPO" removed-email

PRIVATE_REPO="$TEMP_ROOT/private"
mkdir -p "$PRIVATE_REPO/.git"
assert_silent "$PRIVATE_REPO" email

TOUCH_REPO="$TEMP_ROOT/touch"
git -C "$TEMP_ROOT" init -q touch
TOUCH_INPUT="$(TEST_REPO="$TOUCH_REPO" python3 -c 'import json, os; print(json.dumps({"hook_event_name":"PostToolUse","tool_name":"apply_patch","session_id":"test-session","cwd":os.environ["TEST_REPO"]}))')"
printf '%s' "$TOUCH_INPUT" | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" \
  python3 "$SCRIPT_DIR/session_touch.py" track
printf 'uncommitted\n' > "$TOUCH_REPO/edited.txt"
STOP_INPUT="$(TEST_REPO="$TOUCH_REPO" python3 -c 'import json, os; print(json.dumps({"hook_event_name":"Stop","session_id":"test-session","cwd":os.environ["TEST_REPO"],"stop_hook_active":False}))')"
printf '%s' "$STOP_INPUT" | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" \
  python3 "$SCRIPT_DIR/session_touch.py" nudge > "$TEMP_ROOT/nudge.json"
python3 - "$TEMP_ROOT/nudge.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert "still dirty" in payload["systemMessage"]
assert "CONVENTIONS.md#auto-update-protocol" in payload["systemMessage"]
PY

printf '%s' "$STOP_INPUT" | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" \
  python3 "$SCRIPT_DIR/session_touch.py" nudge > "$TEMP_ROOT/nudge-repeat.json"
python3 - "$TEMP_ROOT/nudge-repeat.json" <<'PY'
import json
import sys

assert json.load(open(sys.argv[1], encoding="utf-8")) == {}
PY

rm "$TOUCH_REPO/edited.txt"
printf '%s' "$STOP_INPUT" | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" \
  python3 "$SCRIPT_DIR/session_touch.py" nudge > "$TEMP_ROOT/nudge-clean.json"
python3 - "$TEMP_ROOT/nudge-clean.json" <<'PY'
import json
import sys

assert json.load(open(sys.argv[1], encoding="utf-8")) == {}
PY

printf 'uncommitted again\n' > "$TOUCH_REPO/edited.txt"
printf '%s' "$STOP_INPUT" | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" \
  python3 "$SCRIPT_DIR/session_touch.py" nudge > "$TEMP_ROOT/nudge-renewed.json"
python3 - "$TEMP_ROOT/nudge-renewed.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert "still dirty" in payload["systemMessage"]
assert "CONVENTIONS.md#auto-update-protocol" in payload["systemMessage"]
PY

# stale-state prune: a >30-day-old file is removed on the next track, a fresh one survives
STALE_FILE="$TEMP_ROOT/state/stale-session.repos"
printf '/nonexistent\n' > "$STALE_FILE"
touch -t 202601010000 "$STALE_FILE"
printf '%s' "$TOUCH_INPUT" | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" \
  python3 "$SCRIPT_DIR/session_touch.py" track
[ ! -e "$STALE_FILE" ]
ls "$TEMP_ROOT/state"/*.repos >/dev/null

printf '%s' '{"hook_event_name":"SessionStart"}' | python3 "$SCRIPT_DIR/resume_context.py" > "$TEMP_ROOT/resume.json"
python3 - "$TEMP_ROOT/resume.json" <<'PY'
import json
import socket
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
context = payload["hookSpecificOutput"]["additionalContext"]
host = socket.gethostname().split(".")[0]
assert f"The worker host for this session is {host}." in context
assert "verify it on this host with hostname" in context
assert "do not request step-by-step confirmation" in context
assert "stopping point, next action" in context
assert "no durable records or separate closure report" in context
assert "CONVENTIONS.md#auto-update-protocol" in context
PY

echo "Codex hook tests passed"
