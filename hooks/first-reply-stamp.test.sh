#!/usr/bin/env bash
# first-reply-stamp.test.sh — 自己同定 stamp の UserPromptSubmit / Stop 入口 test
#
# 判定 logic 本体 (範囲・最初の turn・1 回印・observe/block・Codex rollout) は
# scripts/first_reply_stamp.py --selftest が持つ。 ここではそれを走らせたうえで、 hook の
# 入口 (hooks/first-prompt-stamp.py / first-turn-stamp-check.py) が stdin の event を受けて
# 期待どおりの JSON を返すかを、 2026-09-11 の失敗の形 (状況報告が最初の text) で確かめる。

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BASE="$(cd "$ROOT/.." && pwd)"
pass=0; fail=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ok()  { pass=$((pass+1)); }
ng()  { fail=$((fail+1)); echo "FAIL: $1"; [ -n "${2:-}" ] && echo "  got: $2"; }

if python3 "$ROOT/scripts/first_reply_stamp.py" --selftest >"$TMP/selftest.txt" 2>&1; then
  ok
else
  ng "module selftest" "$(grep -E '❌|Traceback|Error' "$TMP/selftest.txt" | head -5)"
fi

export FIRST_REPLY_STAMP_WHO="desktop = someone@example.invalid"
export FIRST_REPLY_STAMP_STATE_DIR="$TMP/state"
unset FIRST_REPLY_STAMP FIRST_REPLY_STAMP_STOP CLAUDE_CODE_ENTRYPOINT 2>/dev/null || true

# 失敗の形の transcript: 状況報告 → tool → 最終 message、 stamp 無し
cat >"$TMP/miss.jsonl" <<'EOF'
{"type":"user","message":{"content":"spec を読んで実行して"}}
{"type":"assistant","message":{"content":[{"type":"text","text":"Status: spec read; now reading…"},{"type":"tool_use","name":"Bash","input":{"command":"true"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","content":"ok"}]}}
{"type":"assistant","message":{"content":[{"type":"text","text":"結果です"}]}}
EOF

UP="{\"hook_event_name\":\"UserPromptSubmit\",\"session_id\":\"t-up-1\",\"cwd\":\"$BASE\",\"prompt\":\"やって\"}"
out="$(printf '%s' "$UP" | python3 "$HERE/first-prompt-stamp.py")"
if printf '%s' "$out" | python3 -c 'import json,sys; c=json.load(sys.stdin)["hookSpecificOutput"]; assert c["hookEventName"]=="UserPromptSubmit" and "🖥 " in c["additionalContext"] and "t-up-1" in c["additionalContext"]' 2>/dev/null; then ok; else ng "UPS: 最初の prompt で additionalContext に stamp" "$out"; fi
out="$(printf '%s' "$UP" | python3 "$HERE/first-prompt-stamp.py")"
[ -z "$out" ] && ok || ng "UPS: 2 回目は沈黙" "$out"
out="$(printf '%s' 'not json' | python3 "$HERE/first-prompt-stamp.py")"; rc=$?
[ -z "$out" ] && [ "$rc" -eq 0 ] && ok || ng "UPS: 壊れた stdin は fail-open" "$out rc=$rc"

ST="{\"hook_event_name\":\"Stop\",\"session_id\":\"t-st-1\",\"cwd\":\"$BASE\",\"transcript_path\":\"$TMP/miss.jsonl\",\"stop_hook_active\":false}"
out="$(printf '%s' "$ST" | python3 "$HERE/first-turn-stamp-check.py")"
[ -z "$out" ] && grep -q '"t-st-1"' "$TMP/state/stop-log.jsonl" 2>/dev/null && ok \
  || ng "Stop (既定 = observe): 無出力で記録だけ" "$out"
out="$(printf '%s' "${ST/t-st-1/t-st-2}" | FIRST_REPLY_STAMP_STOP=block python3 "$HERE/first-turn-stamp-check.py")"
if printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["decision"]=="block" and "🖥 " in d["reason"]' 2>/dev/null; then ok; else ng "Stop (block): decision=block + stamp" "$out"; fi
out="$(printf '%s' "${ST/t-st-1/t-st-3}" | FIRST_REPLY_STAMP_STOP=off python3 "$HERE/first-turn-stamp-check.py")"
[ -z "$out" ] && ok || ng "Stop (off): 沈黙" "$out"

# 既定 mode は observe (block へ上げるのは観測の後 = 値の変更は commit で残す)
grep -q '^DEFAULT_STOP_MODE = "observe"' "$ROOT/scripts/first_reply_stamp.py" && ok \
  || ng "DEFAULT_STOP_MODE が observe でない (上げたなら本 test も更新する)"

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
