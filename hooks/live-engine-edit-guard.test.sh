#!/usr/bin/env bash
# live-engine-edit-guard.test.sh — live-engine-edit-guard.py の検査 (初回は止める / 2 回目は通す / 読まれない file は通す / MultiEdit・Write は通す / nudge mode)
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/live-engine-edit-guard.py"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
ENGINE_DEFAULT="$(cd "$(dirname "$0")/.." && pwd)/scripts/live-engine-paths.py"
export LIVE_ENGINE_PATHS_ENGINE="${LIVE_ENGINE_PATHS_ENGINE:-$ENGINE_DEFAULT}"
[ -f "$LIVE_ENGINE_PATHS_ENGINE" ] || LIVE_ENGINE_PATHS_ENGINE="$HOME/Claude/claude-config/scripts/live-engine-paths.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export LIVE_ENGINE_EDIT_STATE_DIR="$TMP/state"
export LIVE_ENGINE_PATHS_CACHE="$TMP/cache.json"
mkdir -p "$TMP/tools"
printf 'print(1)\n' > "$TMP/tools/engine.py"
printf 'print(2)\n' > "$TMP/tools/other.py"
LIVE="$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$TMP/tools/engine.py")"
python3 - "$TMP/cache.json" "$LIVE" <<'PY'
import json, sys, time
json.dump({"built": time.time(), "live": {sys.argv[2]: "mock の git hook pre-commit"}}, open(sys.argv[1], "w"))
PY
pass=0; fail=0
ok() { pass=$((pass+1)); echo "✅ $1"; }
ng() { fail=$((fail+1)); echo "❌ $1"; }
run() { printf '%s' "$1" | python3 "$HOOK"; }
edit_json() { printf '{"session_id":"%s","hook_event_name":"PreToolUse","tool_name":"%s","tool_input":{"file_path":"%s","old_string":"1","new_string":"3"}}' "$1" "$2" "$3"; }

out="$(run "$(edit_json s1 Edit "$TMP/tools/engine.py")")"
if printf '%s' "$out" | grep -q '"permissionDecision": "deny"' && printf '%s' "$out" | grep -q 'mock の git hook pre-commit'; then
  ok "T1 読まれている file の初めての Edit は止め、 呼び元を出す"
else ng "T1: ${out:-silent}"; fi

out="$(run "$(edit_json s1 Edit "$TMP/tools/engine.py")")"
if [ -z "$out" ]; then ok "T2 同じ session の同じ file の 2 回目は通す"; else ng "T2: $out"; fi

out="$(run "$(edit_json s2 Edit "$TMP/tools/engine.py")")"
if [ -n "$out" ]; then ok "T3 別の session では初回にまた止める"; else ng "T3 黙った"; fi

out="$(run "$(edit_json s1 Edit "$TMP/tools/other.py")")"
if [ -z "$out" ]; then ok "T4 読まれていない file は通す"; else ng "T4: $out"; fi

out="$(run "$(edit_json s4 MultiEdit "$TMP/tools/engine.py")")$(run "$(edit_json s4 Write "$TMP/tools/engine.py")")"
if [ -z "$out" ]; then ok "T5 MultiEdit と Write は通す (1 回で全体を書く)"; else ng "T5: $out"; fi

out="$(LIVE_ENGINE_EDIT_GUARD_MODE=nudge run "$(edit_json s5 Edit "$TMP/tools/engine.py")")"
if printf '%s' "$out" | grep -q additionalContext && ! printf '%s' "$out" | grep -q permissionDecision; then ok "T6 nudge mode は止めずに知らせる"
else ng "T6: ${out:-silent}"; fi

out="$(printf 'not json' | python3 "$HOOK"; echo "rc=$?")"
if [ "$out" = "rc=0" ]; then ok "T7 壊れた入力は黙って rc 0"; else ng "T7: $out"; fi

echo "live-engine-edit-guard test: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
