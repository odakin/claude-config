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
PUBLIC_INPUT="$(TEST_REPO="$PUBLIC_REPO" python3 -c 'import json, os; address = "owner" + "@" + "example.edu"; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"apply_patch","cwd":os.environ["TEST_REPO"],"tool_input":{"command":f"*** Begin Patch\n*** Update File: README.md\n@@\n+{address}\n*** End Patch"}}))')"
printf '%s' "$PUBLIC_INPUT" | python3 "$SCRIPT_DIR/pre_tool_policy.py" > "$TEMP_ROOT/deny.json"
python3 - "$TEMP_ROOT/deny.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
PY

PRIVATE_REPO="$TEMP_ROOT/private"
mkdir -p "$PRIVATE_REPO/.git"
PRIVATE_INPUT="$(TEST_REPO="$PRIVATE_REPO" python3 -c 'import json, os; address = "owner" + "@" + "example.edu"; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"apply_patch","cwd":os.environ["TEST_REPO"],"tool_input":{"command":f"*** Begin Patch\n*** Update File: README.md\n@@\n+{address}\n*** End Patch"}}))')"
printf '%s' "$PRIVATE_INPUT" | python3 "$SCRIPT_DIR/pre_tool_policy.py" > "$TEMP_ROOT/private.json"
[ ! -s "$TEMP_ROOT/private.json" ]

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
PY

printf '%s' '{"hook_event_name":"SessionStart"}' | python3 "$SCRIPT_DIR/resume_context.py" > "$TEMP_ROOT/resume.json"
python3 - "$TEMP_ROOT/resume.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
assert "do not request step-by-step confirmation" in payload["hookSpecificOutput"]["additionalContext"]
PY

echo "Codex hook tests passed"
