#!/usr/bin/env bash
# worker-launch-checks.test.sh — session-launch-check.sh・workflow-launch-check.sh・busy-worker-stop-check.sh の self-test (engine の selftest + hook の入出力)
#
# 正本: claude-config/hooks/worker-launch-checks.test.sh
# 実行: bash hooks/worker-launch-checks.test.sh (run-all-checks.sh が自動発見)。 候補の dir からも回る:
#       ENGINE_DIR=<claude-config>/scripts bash <候補>/worker-launch-checks.test.sh
#
# 歯: engine を外すと block の case が落ちる / 本物の incident の形 (Fable を頼んで Opus で起きた・busy の worker への claude stop・
#     Fable の session で model を書かない workflow・切替時刻を過ぎて働き続ける workflow の agent) を再現する。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="${ENGINE_DIR:-$HERE/../scripts}"
LAUNCH="$HERE/session-launch-check.sh"; STOP="$HERE/busy-worker-stop-check.sh"; WF="$HERE/workflow-launch-check.sh"
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

echo "=== workflow-launch-check.sh: Fable の session の workflow と切替時刻 ==="
export SESSION_LAUNCH_PREMIUM_GATE=1
printf '%s\n%s\n' '{"type":"user","message":{"role":"user","content":"Fable にふさわしい仕事をやろう"}}' \
  '{"type":"assistant","message":{"role":"assistant","model":"claude-fable-5-1","content":[]}}' > "$TMP/wf.jsonl"
WFJ='{"hook_event_name":"PreToolUse","tool_name":"Workflow","session_id":"W","transcript_path":"'"$TMP/wf.jsonl"'","tool_input":{"script":"await agent(\"check (x)\", {label: \"a\"})"}}'
printf '%s' "$WFJ" | bash "$WF" >/dev/null 2>&1; rc=$?
[ "$rc" = 2 ] && ok "Fable の session・model の無い agent → exit 2" || ng "model の無い agent が通った (rc=$rc)"
WFJ2='{"hook_event_name":"PreToolUse","tool_name":"Workflow","session_id":"W","transcript_path":"'"$TMP/wf.jsonl"'","tool_input":{"script":"await agent(\"check (x)\", {label: \"a\", model: \"claude-opus-5-5\"})"}}'
printf '%s' "$WFJ2" | bash "$WF" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "agent が model を書く → 通す" || ng "model を書いた agent が止まった (rc=$rc)"
printf 'import sys\nsys.exit(2)\n' > "$TMP/always2.py"
BASHJ='{"hook_event_name":"PreToolUse","tool_name":"Bash","session_id":"W","agent_id":"a1","tool_input":{"command":"ls"}}'
SESSION_LAUNCH_CHECK_ENGINE="$TMP/always2.py" bash "$WF" <<<"$BASHJ" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "Workflow 以外・切替時刻の記録なし → engine を起動しない" || ng "記録が無いのに engine が走った (rc=$rc)"
mkdir -p "$SESSION_LAUNCH_STATE_DIR"
printf '{"stop_at": %s, "iso": "t", "notified": false}' "$(( $(date +%s) - 60 ))" > "$SESSION_LAUNCH_STATE_DIR/W.stop-at.json"
printf '%s' "$BASHJ" | bash "$WF" >/dev/null 2>&1; rc=$?
[ "$rc" = 2 ] && ok "切替時刻の後の subagent の tool → exit 2" || ng "切替時刻の後の subagent が止まらない (rc=$rc)"
SESSION_LAUNCH_CHECK_ENGINE="$TMP/none.py" bash "$WF" <<<"$BASHJ" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "engine 不在 → fail-open" || ng "engine 不在で止まった (rc=$rc)"
unset SESSION_LAUNCH_PREMIUM_GATE

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
