#!/usr/bin/env bash
# codex-hooks.test.sh — Codex hook schema and adapter behavior tests

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Report the failing line and command instead of a silent exit 1.
. "$SCRIPT_DIR/../../scripts/lib/test-err-trap.sh"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT

python3 -m json.tool "$SCRIPT_DIR/hooks.json" >/dev/null
grep -q 'pre_tool_policy.py' "$SCRIPT_DIR/hooks.json"
grep -q 'resume_context.py' "$SCRIPT_DIR/hooks.json"
grep -q 'session_provenance.py' "$SCRIPT_DIR/hooks.json"
test -f "$SCRIPT_DIR/session_stamp.py"
grep -q 'session_touch.py' "$SCRIPT_DIR/hooks.json"
python3 - "$SCRIPT_DIR/hooks.json" <<'PY'
import json
import sys

hooks = json.load(open(sys.argv[1], encoding="utf-8"))["hooks"]
assert any(
    group.get("matcher") == "Bash"
    and any("session_provenance.py" in hook.get("command", "") for hook in group.get("hooks", []))
    for group in hooks["PreToolUse"]
)
assert any(
    group.get("matcher") == "Bash"
    and any("session_touch.py" in hook.get("command", "") for hook in group.get("hooks", []))
    for group in hooks["PreToolUse"]
)
assert any(
    group.get("matcher") == "apply_patch"
    and any("session_touch.py" in hook.get("command", "") for hook in group.get("hooks", []))
    for group in hooks["PreToolUse"]
)
assert any(
    any("session_provenance.py" in hook.get("command", "") for hook in group.get("hooks", []))
    for group in hooks["SessionStart"]
)
assert any(
    any("session_provenance.py" in hook.get("command", "") for hook in group.get("hooks", []))
    for group in hooks["UserPromptSubmit"]
)
PY

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

TOUCH_REMOTE="$TEMP_ROOT/touch-remote.git"
TOUCH_REPO="$TEMP_ROOT/touch"
git init -q --bare "$TOUCH_REMOTE"
git clone -q "$TOUCH_REMOTE" "$TOUCH_REPO"
# Name the branch: CI's git defaults to master, Apple Git's system config to main.
git -C "$TOUCH_REPO" symbolic-ref HEAD refs/heads/main
git -C "$TOUCH_REPO" config user.name Test
git -C "$TOUCH_REPO" config user.email "test""@""example.invalid"
printf 'base\n' > "$TOUCH_REPO/edited.txt"
git -C "$TOUCH_REPO" add edited.txt
git -C "$TOUCH_REPO" commit -qm 'Initial fixture'
git -C "$TOUCH_REPO" push -qu origin HEAD:main
git -C "$TOUCH_REPO" branch --set-upstream-to=origin/main main >/dev/null

make_touch_input() {
  TEST_REPO="$1" TEST_SESSION="$2" TEST_EVENT="$3" TEST_TOOL="$4" TEST_COMMAND="$5" \
    python3 - <<'PY'
import json
import os

print(json.dumps({
    "hook_event_name": os.environ["TEST_EVENT"],
    "tool_name": os.environ["TEST_TOOL"],
    "session_id": os.environ["TEST_SESSION"],
    "cwd": os.environ["TEST_REPO"],
    "tool_input": {
        "command": os.environ["TEST_COMMAND"],
        "workdir": os.environ["TEST_REPO"],
    },
}))
PY
}

make_stop_input() {
  TEST_REPO="$1" TEST_SESSION="$2" TEST_ACTIVE="$3" python3 - <<'PY'
import json
import os

print(json.dumps({
    "hook_event_name": "Stop",
    "session_id": os.environ["TEST_SESSION"],
    "cwd": os.environ["TEST_REPO"],
    "stop_hook_active": os.environ["TEST_ACTIVE"] == "true",
}))
PY
}

# Dirty after an apply_patch baseline blocks completion, including when the task
# starts in a parent workspace and the patch path identifies the nested repo.
DIRTY_PATCH="*** Begin Patch
*** Update File: $TOUCH_REPO/edited.txt
*** End Patch"
make_touch_input "$TEMP_ROOT" dirty-session PreToolUse apply_patch "$DIRTY_PATCH" \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" track
printf 'uncommitted\n' >> "$TOUCH_REPO/edited.txt"
make_stop_input "$TOUCH_REPO" dirty-session false \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" nudge \
  > "$TEMP_ROOT/nudge-dirty.json"
python3 - "$TEMP_ROOT/nudge-dirty.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["decision"] == "block"
assert "dirty" in payload["reason"]
assert "CONVENTIONS.md#completion-git-gate" in payload["reason"]
PY

# Codex's stop_hook_active recursion guard permits only one continuation. The
# second pass stays loud but does not create an infinite continuation loop.
make_stop_input "$TOUCH_REPO" dirty-session true \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" nudge \
  > "$TEMP_ROOT/nudge-active.json"
python3 - "$TEMP_ROOT/nudge-active.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert "decision" not in payload
assert "unresolved state remains" in payload["systemMessage"]
PY

git -C "$TOUCH_REPO" restore edited.txt
make_stop_input "$TOUCH_REPO" dirty-session false \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" nudge \
  > "$TEMP_ROOT/nudge-clean.json"
python3 - "$TEMP_ROOT/nudge-clean.json" <<'PY'
import json
import sys

assert json.load(open(sys.argv[1], encoding="utf-8")) == {}
PY

# A not-yet-existing nested directory still resolves through its nearest
# existing ancestor to the enclosing repository.
NESTED_PATCH="*** Begin Patch
*** Add File: $TOUCH_REPO/new/deep/file.txt
*** End Patch"
make_touch_input "$TEMP_ROOT" nested-session PreToolUse apply_patch "$NESTED_PATCH" \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" track
NESTED_STATE="$(TEST_SESSION=nested-session python3 - <<'PY'
import hashlib
import os
print(hashlib.sha256(os.environ["TEST_SESSION"].encode()).hexdigest() + ".json")
PY
)"
python3 - "$TEMP_ROOT/state/$NESTED_STATE" "$TOUCH_REPO" <<'PY'
import json
import os
import sys

repos = json.load(open(sys.argv[1], encoding="utf-8"))["repos"]
assert os.path.realpath(sys.argv[2]) in repos
PY

# A commit-only call is remembered and the resulting ahead state blocks Stop.
make_touch_input "$TOUCH_REPO" ahead-session PreToolUse Bash 'git commit -m split' \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" track
printf 'ahead\n' > "$TOUCH_REPO/ahead.txt"
git -C "$TOUCH_REPO" add ahead.txt
git -C "$TOUCH_REPO" commit -qm 'Ahead fixture'
make_stop_input "$TOUCH_REPO" ahead-session false \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" nudge \
  > "$TEMP_ROOT/nudge-ahead.json"
python3 - "$TEMP_ROOT/nudge-ahead.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["decision"] == "block"
reason = payload["reason"]
assert "commit and push were split into separate calls" in reason
assert "ahead=1, behind=0" in reason
PY

# The later push resolves the gate; this proves the previous Stop, not a vague
# reminder, detects the unsafe gap between commit and a separate push call.
git -C "$TOUCH_REPO" push -qu origin HEAD:main
make_stop_input "$TOUCH_REPO" ahead-session false \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" nudge \
  > "$TEMP_ROOT/nudge-pushed.json"
python3 - "$TEMP_ROOT/nudge-pushed.json" <<'PY'
import json
import sys

assert json.load(open(sys.argv[1], encoding="utf-8")) == {}
PY

# An unchanged pre-existing dirty path is not attributed to this task. A
# separate explicit-path commit can be pushed while that baseline dirt remains.
printf 'pre-existing user work\n' >> "$TOUCH_REPO/edited.txt"
make_touch_input "$TOUCH_REPO" baseline-dirty-session PreToolUse Bash 'git commit -m owned -- owned.txt' \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" track
printf 'owned\n' > "$TOUCH_REPO/owned.txt"
git -C "$TOUCH_REPO" add owned.txt
git -C "$TOUCH_REPO" commit -qm 'Owned fixture' -- owned.txt
git -C "$TOUCH_REPO" push -qu origin HEAD:main
make_stop_input "$TOUCH_REPO" baseline-dirty-session false \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" nudge \
  > "$TEMP_ROOT/nudge-baseline-dirty.json"
python3 - "$TEMP_ROOT/nudge-baseline-dirty.json" <<'PY'
import json
import sys

assert json.load(open(sys.argv[1], encoding="utf-8")) == {}
PY
git -C "$TOUCH_REPO" restore edited.txt

# A fetched upstream advance is classified as behind, while ls-remote verifies
# that the comparison uses the live remote branch head.
OTHER_REPO="$TEMP_ROOT/other"
git clone -q "$TOUCH_REMOTE" "$OTHER_REPO"
git -C "$OTHER_REPO" config user.name Test
git -C "$OTHER_REPO" config user.email "test""@""example.invalid"
git -C "$OTHER_REPO" checkout -q main
make_touch_input "$TOUCH_REPO" behind-session PreToolUse apply_patch "$DIRTY_PATCH" \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" track
printf 'local work\n' >> "$TOUCH_REPO/edited.txt"
printf 'remote work\n' > "$OTHER_REPO/remote.txt"
git -C "$OTHER_REPO" add remote.txt
git -C "$OTHER_REPO" commit -qm 'Remote fixture'
git -C "$OTHER_REPO" push -qu origin HEAD:main
git -C "$TOUCH_REPO" fetch -q origin
make_stop_input "$TOUCH_REPO" behind-session false \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" nudge \
  > "$TEMP_ROOT/nudge-behind.json"
python3 - "$TEMP_ROOT/nudge-behind.json" <<'PY'
import json
import sys

reason = json.load(open(sys.argv[1], encoding="utf-8"))["reason"]
assert "behind=1" in reason
assert "local HEAD" in reason
PY

# stale-state prune: a >30-day-old file is removed on the next track, a fresh one survives
STALE_FILE="$TEMP_ROOT/state/stale-session.json"
printf '/nonexistent\n' > "$STALE_FILE"
touch -t 202601010000 "$STALE_FILE"
make_touch_input "$TOUCH_REPO" prune-session PreToolUse Bash 'git status' \
  | CODEX_SESSION_TOUCH_STATE_DIR="$TEMP_ROOT/state" python3 "$SCRIPT_DIR/session_touch.py" track
[ ! -e "$STALE_FILE" ]
ls "$TEMP_ROOT/state"/*.json >/dev/null

PROVENANCE_STATE="$TEMP_ROOT/provenance-state"
printf '%s' '{"hook_event_name":"SessionStart","session_id":"codex-test-session","model":"gpt-test"}' \
  | CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$PROVENANCE_STATE" \
    python3 "$SCRIPT_DIR/session_provenance.py"
grep -qx 'model=gpt-test' "$PROVENANCE_STATE/codex-test-session.env"
printf '%s' '{"hook_event_name":"UserPromptSubmit","session_id":"codex-test-session","model":"gpt-test-prompt"}' \
  | CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$PROVENANCE_STATE" \
    python3 "$SCRIPT_DIR/session_provenance.py"
grep -qx 'model=gpt-test-prompt' "$PROVENANCE_STATE/codex-test-session.env"
printf '%s' '{"hook_event_name":"PreToolUse","session_id":"codex-test-session","model":"gpt-test-2","effort":{"level":"xhigh"}}' \
  | CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$PROVENANCE_STATE" \
    python3 "$SCRIPT_DIR/session_provenance.py"
grep -qx 'model=gpt-test-2' "$PROVENANCE_STATE/codex-test-session.env"
grep -qx 'effort=xhigh' "$PROVENANCE_STATE/codex-test-session.env"

STAMP="$(CODEX_APP_TOOLS_PIPE_PATH="$TEMP_ROOT/fake-app-pipe" \
  CODEX_SESSION_ID="codex-test-session" \
  CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$PROVENANCE_STATE" \
  python3 "$SCRIPT_DIR/session_stamp.py")"
python3 - "$STAMP" <<'PY'
import socket
import sys

host = socket.gethostname().split(".")[0]
assert sys.argv[1] == (
    f"🖥 {host} · Codex desktop · account unknown · session codex-te "
    "· model gpt-test-2 · effort xhigh"
)
PY

THREAD_STATE="$TEMP_ROOT/thread-state"
mkdir -p "$THREAD_STATE"
python3 - "$THREAD_STATE/state_9.sqlite" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute(
    "CREATE TABLE threads (id TEXT PRIMARY KEY, model TEXT, reasoning_effort TEXT)"
)
connection.execute(
    "INSERT INTO threads VALUES (?, ?, ?)",
    ("sqlite-test-session", "gpt-thread-state", "medium"),
)
connection.commit()
connection.close()
PY
STAMP_THREAD_STATE="$(env -u CODEX_APP_TOOLS_PIPE_PATH -u CODEX_SQLITE_HOME \
  CODEX_HOME="$THREAD_STATE" CODEX_SESSION_ID="sqlite-test-session" \
  CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$TEMP_ROOT/no-provenance-cache" \
  python3 "$SCRIPT_DIR/session_stamp.py")"
python3 - "$STAMP_THREAD_STATE" <<'PY'
import socket
import sys

host = socket.gethostname().split(".")[0]
assert sys.argv[1] == (
    f"🖥 {host} · Codex surface unknown · account unknown · session sqlite-t "
    "· model gpt-thread-state · effort medium"
)
PY

STAMP_UNKNOWN="$(env -u CODEX_APP_TOOLS_PIPE_PATH -u CODEX_SESSION_ID -u CODEX_THREAD_ID \
  -u CODEX_SQLITE_HOME \
  CODEX_HOME="$TEMP_ROOT/no-codex-home" python3 "$SCRIPT_DIR/session_stamp.py")"
case "$STAMP_UNKNOWN" in
  *'Codex surface unknown · account unknown · session unknown · model unknown · effort unknown') ;;
  *) echo "unexpected unknown stamp: $STAMP_UNKNOWN" >&2; exit 1 ;;
esac

printf '%s' '{"hook_event_name":"SessionStart","source":"startup","session_id":"codex-test-session","model":"gpt-test","effort":{"level":"high"}}' \
  | CODEX_APP_TOOLS_PIPE_PATH="$TEMP_ROOT/fake-app-pipe" \
    python3 "$SCRIPT_DIR/resume_context.py" > "$TEMP_ROOT/resume.json"
python3 - "$TEMP_ROOT/resume.json" <<'PY'
import json
import socket
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
context = payload["hookSpecificOutput"]["additionalContext"]
host = socket.gethostname().split(".")[0]
assert f"The worker host for this session is {host}." in context
assert (
    f"🖥 {host} · Codex desktop · account unknown · session codex-te "
    "· model gpt-test · effort high"
) in context
assert "first user-visible reply" in context
assert "codex:codex-test-session, model=gpt-test, effort=high" in context
assert "CLAUDE_CONFIG_AGENT_MODEL=gpt-test" in context
assert "verify it on this host with hostname" in context
assert "do not request step-by-step confirmation" in context
assert "stopping point, next action" in context
assert "no durable records or separate closure report" in context
assert "CONVENTIONS.md#auto-update-protocol" in context
assert "repository-root AGENTS.md first" in context
assert "nested root AGENTS.md manually" in context
assert "shell cd does not prove it was in the startup chain" in context
PY

printf '%s' '{"hook_event_name":"SessionStart","source":"compact","session_id":"codex-test-session","model":"gpt-test"}' \
  | CODEX_APP_TOOLS_PIPE_PATH="$TEMP_ROOT/fake-app-pipe" \
    python3 "$SCRIPT_DIR/resume_context.py" > "$TEMP_ROOT/compact.json"
python3 - "$TEMP_ROOT/compact.json" <<'PY'
import json
import sys

context = json.load(open(sys.argv[1], encoding="utf-8"))["hookSpecificOutput"]["additionalContext"]
assert "first user-visible reply" not in context
assert "account unknown" not in context
PY

echo "Codex hook tests passed"
