#!/usr/bin/env bash
# worker-launch-checks.test.sh — session-launch-check.sh と busy-worker-stop-check.sh の self-test (engine の selftest + hook の入出力)
#
# 正本: claude-config/hooks/worker-launch-checks.test.sh
# 実行: bash hooks/worker-launch-checks.test.sh (run-all-checks.sh が自動発見)。 候補の dir からも回る:
#       ENGINE_DIR=<claude-config>/scripts bash <候補>/worker-launch-checks.test.sh
#
# 歯: engine を外すと block の case が落ちる / 本物の incident の形 (Fable を頼んで Opus で起きた・busy の worker への claude stop) を再現する。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="${ENGINE_DIR:-$HERE/../scripts}"
LAUNCH="$HERE/session-launch-check.sh"; STOP="$HERE/busy-worker-stop-check.sh"
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 0; }
export SESSION_LAUNCH_CHECK_ENGINE="$ENGINE_DIR/session-launch-check.py" BUSY_WORKER_STOP_CHECK_ENGINE="$ENGINE_DIR/busy-worker-stop-check.py"
unset SESSION_LAUNCH_CHECK_DISABLE BUSY_WORKER_STOP_CHECK_DISABLE SESSION_LAUNCH_BOARD_FIRST

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

echo "=== engine selftests ==="
python3 "$SESSION_LAUNCH_CHECK_ENGINE" --selftest >/dev/null 2>&1 && ok "session-launch-check --selftest" || ng "session-launch-check --selftest"
python3 "$BUSY_WORKER_STOP_CHECK_ENGINE" --selftest >/dev/null 2>&1 && ok "busy-worker-stop-check --selftest" || ng "busy-worker-stop-check --selftest"

echo "=== session-launch-check.sh: Fable を頼んで Opus で起きた ==="
export SESSION_LAUNCH_STATE_DIR="$TMP/state" CLAUDE_DESKTOP_SESSIONS_DIR="$TMP/app" SESSION_LAUNCH_WAIT=0
LID="local_aaaaaaaa-0000-4000-8000-000000000001"
mkdir -p "$TMP/app/a/e"
printf '{"sessionId":"%s","cliSessionId":"bbbbbbbb-0000-4000-8000-000000000002","model":"claude-opus-5-5","effort":"xhigh"}' "$LID" > "$TMP/app/a/e/$LID.json"
POST='{"hook_event_name":"PostToolUse","tool_name":"mcp__ccd_session__start_session","session_id":"L","tool_input":{"initiation":"user_asked","title":"W","prompt":"This window must run on claude-fable-5-1 at high effort.\n1. x"},"tool_response":[{"type":"text","text":"Started session \"W\" (session_id: '"$LID"', name: w)."}]}'
out="$(printf '%s' "$POST" | bash "$LAUNCH")"; rc=$?
[ "$rc" = 0 ] && [[ "$out" == *set_session_model* ]] && ok "post-start → additionalContext に直し方" || ng "post-start rc=$rc out=${out:0:120}"
SEND='{"hook_event_name":"PreToolUse","tool_name":"SendMessage","session_id":"L","tool_input":{"to":"'"$LID"'","message":"go"}}'
printf '%s' "$SEND" | bash "$LAUNCH" >/dev/null 2>&1; rc=$?
[ "$rc" = 2 ] && ok "go to the capped worker → exit 2" || ng "go was not blocked (rc=$rc)"
SESSION_LAUNCH_CHECK_ENGINE="$TMP/none.py" bash "$LAUNCH" <<<"$SEND" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "engine 不在 → fail-open" || ng "engine 不在で止まった (rc=$rc)"

echo "=== busy-worker-stop-check.sh: busy の worker への claude stop ==="
export CLAUDE_SESSIONS_DIR="$TMP/sessions" CLAUDE_PROJECTS_DIR="$TMP/projects" BUSY_WORKER_STOP_STATE_DIR="$TMP/stop"
mkdir -p "$CLAUDE_SESSIONS_DIR" "$CLAUDE_PROJECTS_DIR/-w"
printf '{"pid":%s,"sessionId":"b0b0b0b0-0000-4000-8000-00000000000b","cwd":"/w","name":"w","status":"busy"}' "$$" > "$CLAUDE_SESSIONS_DIR/1.json"
STOPJ='{"hook_event_name":"PreToolUse","tool_name":"Bash","session_id":"L","transcript_path":"/nonexistent","tool_input":{"command":"claude stop b0b0b0b0"}}'
printf '%s' "$STOPJ" | bash "$STOP" >/dev/null 2>&1; rc=$?
[ "$rc" = 2 ] && ok "busy worker → exit 2" || ng "busy worker was not blocked (rc=$rc)"
OTHER='{"hook_event_name":"PreToolUse","tool_name":"Bash","session_id":"L","tool_input":{"command":"git status"}}'
printf '%s' "$OTHER" | bash "$STOP" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "他の Bash → 通す (engine を起動しない)" || ng "他の Bash が止まった (rc=$rc)"

echo "result: $pass pass / $fail fail"
[ "$fail" = 0 ]
