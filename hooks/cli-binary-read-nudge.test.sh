#!/usr/bin/env bash
# cli-binary-read-nudge.test.sh — cli-binary-read-nudge.py の検査 (本体の binary を読む Bash で鳴る / 1 session 1 回 / 道具と無関係な command・壊れた入力・engine の不在で黙る)
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/cli-binary-read-nudge.py"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export CLI_BINARY_READ_NUDGE_STATE_DIR="$TMP/state"
pass=0; fail=0
ok() { pass=$((pass+1)); echo "✅ $1"; }
ng() { fail=$((fail+1)); echo "❌ $1"; }
# 書き手を pipeline の外に出す: hook が stdin を読まずに exit する経路で printf が SIGPIPE (141) になり、
# pipefail の下でその値を hook の終了値として読んでしまう (hook-authoring.md#hook-stdin-pipe-sigpipe)
run() { python3 "$HOOK" < <(printf '%s' "$1"); }
ev() { python3 -c 'import json,sys; print(json.dumps({"session_id": sys.argv[1], "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": sys.argv[2]}}))' "$1" "$2"; }

READ_CMD='strings ~/.local/share/claude/versions/2.1.309 | grep remote-control'
out="$(run "$(ev s1 "$READ_CMD")")"
if printf '%s' "$out" | grep -q 'claude-app-bundle.py' && printf '%s' "$out" | grep -q '"hookEventName": "PreToolUse"'; then
  ok "T1 本体の binary を strings で読む command で鳴る"
else ng "T1: ${out:-silent}"; fi

out="$(run "$(ev s1 "$READ_CMD")")"
[ -z "$out" ] && ok "T2 同じ session の 2 回目は黙る" || ng "T2 鳴った: $out"

out="$(run "$(ev s2 'python3 ~/Claude/claude-config/scripts/claude-app-bundle.py grep foo --where engine')")"
[ -z "$out" ] && ok "T3 道具そのものを使う command では黙る" || ng "T3 鳴った: $out"

out="$(run "$(ev s3 'ls -la ~/.local/share/claude/versions/')")"
[ -z "$out" ] && ok "T4 置き場所を ls するだけでは黙る" || ng "T4 鳴った: $out"

out="$(run 'not json')"
[ -z "$out" ] && ok "T5 壊れた入力では黙る" || ng "T5 鳴った: $out"

# engine の無い配置 (hook だけを写した dir) では黙って通す
mkdir -p "$TMP/lone/hooks"
cp "$HOOK" "$TMP/lone/hooks/"
out="$(python3 "$TMP/lone/hooks/cli-binary-read-nudge.py" < <(ev s4 "$READ_CMD"))"; rc=$?
[ -z "$out" ] && [ "$rc" = 0 ] && ok "T6 engine が無ければ黙って exit 0" || ng "T6 rc=$rc out=$out"

python3 "$HOOK" --selftest >/dev/null && ok "T7 engine の --selftest が通る" || ng "T7 selftest が落ちた"

echo "passed=$pass failed=$fail"
[ "$fail" = 0 ]
