#!/usr/bin/env bash
# live-engine-edit-guard.test.sh — live-engine-edit-guard.py の検査 (初回は止める / 再送は通す / 再送の前の別の Edit は止める / file が変われば改めて止める / 読まれない file は通す / MultiEdit・Write は通す / nudge mode)
set -uo pipefail

HOOK="${LIVE_ENGINE_EDIT_GUARD_HOOK:-$(cd "$(dirname "$0")" && pwd)/live-engine-edit-guard.py}"
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
# edit_json <session> <tool> <path> [old] [new]
edit_json() { printf '{"session_id":"%s","hook_event_name":"PreToolUse","tool_name":"%s","tool_input":{"file_path":"%s","old_string":"%s","new_string":"%s"}}' "$1" "$2" "$3" "${4:-1}" "${5:-3}"; }

out="$(run "$(edit_json s1 Edit "$TMP/tools/engine.py")")"
if printf '%s' "$out" | grep -q '"permissionDecision": "deny"' && printf '%s' "$out" | grep -q 'mock の git hook pre-commit'; then
  ok "T1 読まれている file の初めての Edit は止め、 呼び元を出す"
else ng "T1: ${out:-silent}"; fi

out="$(run "$(edit_json s1 Edit "$TMP/tools/engine.py")")"
if [ -z "$out" ]; then ok "T2 同じ session の同じ Edit の再送は通す"; else ng "T2: $out"; fi

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

# 同じ message に並べた 3 本: 1 本目を止めた後、 中身の違う 2・3 本目も止める (2026-10-21〜)
o1="$(run "$(edit_json s8 Edit "$TMP/tools/engine.py" a b)")"
o2="$(run "$(edit_json s8 Edit "$TMP/tools/engine.py" c d)")"
o3="$(run "$(edit_json s8 Edit "$TMP/tools/engine.py" e f)")"
if printf '%s' "$o1" | grep -q deny && printf '%s' "$o2" | grep -q deny && printf '%s' "$o3" | grep -q deny \
   && printf '%s' "$o2" | grep -q "再送がまだ無い"; then
  ok "T8 止めた後、 再送の前に来た別の Edit も止める (同じ message の 2 本目以降)"
else ng "T8: o1=${o1:-silent} o2=${o2:-silent} o3=${o3:-silent}"; fi

o4="$(run "$(edit_json s8 Edit "$TMP/tools/engine.py" c d)")"
o5="$(run "$(edit_json s8 Edit "$TMP/tools/engine.py" a b)")"
o6="$(run "$(edit_json s8 Edit "$TMP/tools/engine.py" c d)")"
if printf '%s' "$o4" | grep -q deny && [ -z "$o5" ] && [ -z "$o6" ]; then
  ok "T9 通るのは止めた Edit の再送だけ、 通った後はこの file を止めない"
else ng "T9: o4=${o4:-silent} o5=${o5:-silent} o6=${o6:-silent}"; fi

o7="$(run "$(edit_json s10 Edit "$TMP/tools/engine.py" a b)")"
sleep 1; printf 'print(9)\n' > "$TMP/tools/engine.py.wip"; mv -f "$TMP/tools/engine.py.wip" "$TMP/tools/engine.py"
o8="$(run "$(edit_json s10 Edit "$TMP/tools/engine.py" x y)")"
o9="$(run "$(edit_json s10 Edit "$TMP/tools/engine.py" x y)")"
if printf '%s' "$o7" | grep -q deny && printf '%s' "$o8" | grep -q "呼び元" && [ -z "$o9" ]; then
  ok "T10 止めた後に file が別の手段で変わったら、 控えを捨てて改めて 1 回止める (閉じ込めない)"
else ng "T10: o7=${o7:-silent} o8=${o8:-silent} o9=${o9:-silent}"; fi

mkdir -p "$TMP/state"
printf '["%s"]' "$LIVE" > "$TMP/state/s11.json"
o11="$(run "$(edit_json s11 Edit "$TMP/tools/engine.py" q r)")"
if [ -z "$o11" ]; then ok "T11 旧形式の状態 (止めた file の list) は通した扱い"; else ng "T11: $o11"; fi

echo "live-engine-edit-guard test: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
