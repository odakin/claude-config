#!/usr/bin/env bash
# spawn-dedupe-guard.test.sh — spawn-dedupe-guard.sh の self-test (hermetic)
#
# 正本: claude-config/hooks/spawn-dedupe-guard.test.sh
# 実行: bash hooks/spawn-dedupe-guard.test.sh (run-all-checks.sh が自動発見)
#
# 象限: block (同じ title の chip が pending / 同じ title の session が稼働中) / pass (別の依頼・[再起票]・engine 不在 = fail-open)。
# 刻印・台帳・transcript は temp dir (環境変数で差し替え)。 pid はこの shell (生きている)。
# 歯: engine を外すと block の 2 case が落ちる (= 直す前の部品で落ちる形)。
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/spawn-dedupe-guard.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 0; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_SESSIONS_DIR="$TMP/sessions" CLAUDE_PROJECTS_DIR="$TMP/projects" SPAWN_DEDUPE_STATE_DIR="$TMP/state" \
       SPAWN_DEDUPE_EXT="$TMP/no-ext.py"
mkdir -p "$CLAUDE_SESSIONS_DIR" "$CLAUDE_PROJECTS_DIR" "$SPAWN_DEDUPE_STATE_DIR"
unset SPAWN_DEDUPE_DISABLE

pass=0; fail=0; results=()
SID="aaaaaaaa-0000-0000-0000-000000000000"
TITLE="[local推奨] 合成の依頼 A の見直し"

run_hook() { # <json> -> prints "rc=<n> err=<stderr>"
  local err rc
  err="$(printf '%s' "$1" | bash "$HOOK" 2>&1 >/dev/null)"; rc=$?
  printf 'rc=%s err=%s' "$rc" "$err"
}

assert_rc() { # <label> <expect rc> <json> [<stderr must contain>]
  local label="$1" expect="$2" json="$3" needle="${4:-}" got rc
  got="$(run_hook "$json")"; rc="${got#rc=}"; rc="${rc%% *}"
  if [ "$rc" = "$expect" ] && { [ -z "$needle" ] || [[ "$got" == *"$needle"* ]]; }; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect rc=$expect got: ${got:0:160})")
  fi
}

pre() { python3 -c 'import json,sys; print(json.dumps({"session_id": sys.argv[1], "hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__spawn_task", "tool_input": {"title": sys.argv[2], "tldr": sys.argv[3], "prompt": "x"}}))' "$SID" "$1" "${2:-t}"; }
post() { python3 -c 'import json,sys; print(json.dumps({"session_id": sys.argv[1], "hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_session__spawn_task", "tool_input": {"title": sys.argv[2], "prompt": "x"}, "tool_response": "Noted (position 1, task_id: task_0000c0de). A chip is showing"}))' "$SID" "$1"; }
dismiss() { python3 -c 'import json,sys; print(json.dumps({"session_id": sys.argv[1], "hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_session__dismiss_task", "tool_input": {"task_id": "task_0000c0de"}, "tool_response": sys.argv[2]}))' "$SID" "$1"; }

# 1. 何も無い → pass
assert_rc "fresh chip passes" 0 "$(pre "$TITLE")"
# 2. chip を出した (台帳 pending) → 同じ title は block、 別の title は pass
printf '%s' "$(post "$TITLE")" | bash "$HOOK" >/dev/null 2>&1
assert_rc "same title while pending → block (exit 2, reason on stderr)" 2 "$(pre "[worktree推奨] 合成の依頼 A の見直し")" "task_0000c0de"
assert_rc "different request → pass" 0 "$(pre "[local推奨] 別の依頼")"
assert_rc "[再起票] in tldr → pass (warn only)" 0 "$(pre "$TITLE" "[再起票] 本人が 2 つ目を求めた")"
# 3. dismiss が withdrawn → pass、 その後 同じ title の session が稼働中 → block
printf '%s' "$(dismiss "Task task_0000c0de withdrawn — the chip is no longer shown to the user.")" | bash "$HOOK" >/dev/null 2>&1
assert_rc "withdrawn → pass" 0 "$(pre "$TITLE")"
python3 -c 'import json,sys,time; json.dump({"pid": int(sys.argv[3]), "sessionId": "bbbbbbbb-1111", "cwd": "/x", "name": sys.argv[2], "startedAt": int(time.time()*1000)}, open(sys.argv[1], "w"))' "$CLAUDE_SESSIONS_DIR/111.json" "$TITLE" "$$"
assert_rc "live session with same title → block, names it" 2 "$(pre "$TITLE")" "bbbbbbbb"
# 4. fail-open: engine 不在 / 無効化
SPAWN_DEDUPE_ENGINE="$TMP/missing.py" assert_rc "engine missing → pass (fail-open)" 0 "$(pre "$TITLE")"
SPAWN_DEDUPE_DISABLE=1 assert_rc "SPAWN_DEDUPE_DISABLE=1 → pass" 0 "$(pre "$TITLE")"

printf '%s\n' "${results[@]}"
echo "spawn-dedupe-guard.test: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
