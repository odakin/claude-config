#!/usr/bin/env bash
# known-error-nudge.test.sh — known-error-nudge.py の検査 (鳴る / 黙る / 1 session 1 回 / 台帳の点検)
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/known-error-nudge.py"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export KNOWN_ERROR_NUDGE_STATE_DIR="$TMP/state"
pass=0; fail=0
ok() { pass=$((pass+1)); echo "✅ $1"; }
ng() { fail=$((fail+1)); echo "❌ $1"; }
run() { printf '%s' "$1" | python3 "$HOOK"; }

FAIL_JSON='{"session_id":"s1","hook_event_name":"PostToolUseFailure","tool_name":"Bash","tool_input":{"command":"python3 x.py"},"error":"Exit code 1\n  File \"x.py\", line 2\nSyntaxError: Non-UTF-8 code starting with '"'"'\\xe3'"'"' in file x.py on line 2, but no encoding declared"}'

out="$(run "$FAIL_JSON")"
if printf '%s' "$out" | grep -q 'batch-text-edits.md#system-python-long-multibyte-line' \
   && printf '%s' "$out" | grep -q '"hookEventName": "PostToolUseFailure"'; then ok "T1 失敗した Bash のエラー文で鳴る (event 名は受けたもの)"
else ng "T1: ${out:-silent}"; fi

out="$(run "$FAIL_JSON")"
if [ -z "$out" ]; then ok "T2 同じ session の同じ壊れ方は 2 回目に黙る"; else ng "T2 鳴った: $out"; fi

out="$(run "${FAIL_JSON/\"s1\"/\"s2\"}")"
if [ -n "$out" ]; then ok "T3 別の session では再び鳴る"; else ng "T3 黙った"; fi

OK_JSON='{"session_id":"s3","hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"git commit"},"tool_response":{"stdout":"","stderr":"error: .git/hooks/pre-commit died of signal 9"}}'
out="$(run "$OK_JSON")"
if printf '%s' "$out" | grep -q 'hook-authoring.md#killed-hook-stub' \
   && printf '%s' "$out" | grep -q '"hookEventName": "PostToolUse"'; then ok "T4 成功した Bash の stderr でも鳴る"
else ng "T4: ${out:-silent}"; fi

out="$(run '{"session_id":"s4","hook_event_name":"PostToolUseFailure","tool_name":"Bash","error":"Exit code 1\nNo such file or directory"}')"
if [ -z "$out" ]; then ok "T5 台帳に無いエラーでは黙る"; else ng "T5 鳴った: $out"; fi

out="$(run '{"session_id":"s5","hook_event_name":"PostToolUseFailure","tool_name":"Read","error":"Non-UTF-8 code starting with"}')"
if [ -z "$out" ]; then ok "T6 Bash 以外の tool では黙る"; else ng "T6 鳴った: $out"; fi

echo '{ broken' > "$TMP/broken.json"
out="$(KNOWN_ERROR_NUDGE_REGISTRY="$TMP/broken.json" run "${FAIL_JSON/\"s1\"/\"s6\"}")"; rc=$?
if [ -z "$out" ] && [ $rc -eq 0 ]; then ok "T7 台帳が壊れていても黙って exit 0 (fail-open)"; else ng "T7 rc=$rc out=$out"; fi

printf '%s' '{"entries":[{"match":"ab+c","regex":true,"doc":"conventions/batch-text-edits.md"}]}' > "$TMP/re.json"
out="$(KNOWN_ERROR_NUDGE_REGISTRY="$TMP/re.json" run '{"session_id":"s7","hook_event_name":"PostToolUseFailure","tool_name":"Bash","error":"x abbbc y"}')"
if printf '%s' "$out" | grep -q 'batch-text-edits.md'; then ok "T8 regex の entry が当たる"; else ng "T8: ${out:-silent}"; fi

if python3 "$HOOK" --check >/dev/null; then ok "T9 本物の台帳は --check を通る (doc・anchor・本文の文字列)"
else ng "T9: $(python3 "$HOOK" --check)"; fi

printf '%s' '{"entries":[{"match":"この文字列はどの規約にも無い 7f3a","doc":"conventions/batch-text-edits.md"},{"match":"x","doc":"conventions/batch-text-edits.md#no-such-anchor"},{"match":"y","doc":"conventions/no-such-doc.md"}]}' > "$TMP/badreg.json"
res="$(KNOWN_ERROR_NUDGE_REGISTRY="$TMP/badreg.json" python3 "$HOOK" --check)"; rc=$?
if [ $rc -eq 1 ] && printf '%s' "$res" | grep -q '本文に無い' && printf '%s' "$res" | grep -q 'anchor が無い' \
   && printf '%s' "$res" | grep -q 'doc が無い'; then ok "T10 --check が 3 種の誤りを止める"
else ng "T10 rc=$rc $res"; fi

ARCH='{"session_id":"s8","hook_event_name":"PostToolUse","tool_name":"mcp__ccd_session_mgmt__archive_session","tool_input":{"session_id":"local_x"},"tool_response":[{"type":"text","text":"Session local_x (\"t\") was not archived: it still has live work (an agent run, a Remote Control client, a queued message or a background task). Wait or ask the user; they can also archive it from the sidebar."}]}'
out="$(run "$ARCH")"
if printf '%s' "$out" | grep -q 'multi-session-coordination.md#tidy-after-child-turn-ends'; then ok "T11 archive_session の「live work」 の断り (MCP の content) で鳴る"
else ng "T11: ${out:-silent}"; fi

out="$(run "${ARCH/archive_session/stop_session}")"
if [ -z "$out" ]; then ok "T12 見ていない MCP の tool (stop_session) では黙る"; else ng "T12 鳴った: $out"; fi

echo "==== RESULT: PASS=$pass FAIL=$fail ===="
[ "$fail" -eq 0 ]
