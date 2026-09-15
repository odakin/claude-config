#!/usr/bin/env bash
# office-inplace-guard.test.sh — 述語の selftest + hook 入出力 (deny の JSON / 読めない入力で死なない / opt-out) + カナリア (偽 HOME の本番配線で ARMED / NOT ARMED)
#
# 正本: claude-config/hooks/office-inplace-guard.test.sh
# office-staging: exempt guard の test fixture (in-place の例文を hook に食わせる)

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/office-inplace-guard.py"
ROOT="$(cd "$HERE/.." && pwd)"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 不在 — test 省略"; exit 0; }

pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/office-inplace-guard-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

echo "=== 述語 (--selftest) ==="
st="$(python3 "$HOOK" --selftest 2>&1)"; rc=$?
printf '%s\n' "$st" | sed 's/^/  /'
[ "$rc" -eq 0 ] && ok "selftest" || ng "selftest rc=$rc"

run_hook() { # <json> [env...]
  local json="$1"; shift
  printf '%s' "$json" | env -u CLAUDE_OFFICE_INPLACE_GUARD HOME="$TMP/home" "$@" python3 "$HOOK"
}

BAD='{"tool_name":"Bash","cwd":"/tmp","tool_input":{"command":"osascript -e '"'"'tell application \"Microsoft Excel\" to open POSIX file \"/tmp/example/form.xlsx\"'"'"'"}}'
GOOD='{"tool_name":"Bash","cwd":"/tmp","tool_input":{"command":"xlsx-to-pdf.sh /tmp/example/form.xlsx"}}'

echo "=== hook 入出力 ==="
out="$(run_hook "$BAD")"
case "$out" in
  *'"permissionDecision": "deny"'*'office-stage-run.sh'*'office-pregranted-staging-dir'*) ok "in-place の inline osascript → deny + 直し方 + 正本" ;;
  *) ng "deny されない: $out" ;;
esac
printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert d["hookEventName"]=="PreToolUse" and d["permissionDecisionReason"]' \
  && ok "出力は PreToolUse の JSON" || ng "JSON 形が違う"
out="$(run_hook "$GOOD")"
[ -z "$out" ] && ok "wrapper は通す" || ng "wrapper で出力: $out"
out="$(run_hook "$BAD" CLAUDE_OFFICE_INPLACE_GUARD=0)"
[ -z "$out" ] && ok "opt-out (CLAUDE_OFFICE_INPLACE_GUARD=0)" || ng "opt-out が効かない"
out="$(run_hook '{"tool_name":"Read","tool_input":{"file_path":"/tmp/example/form.xlsx"}}')"
[ -z "$out" ] && ok "Bash 以外は無音" || ng "Read で出力: $out"
out="$(printf 'not json' | python3 "$HOOK")"; rc=$?
{ [ -z "$out" ] && [ "$rc" -eq 0 ]; } && ok "壊れた JSON は黙って通す (fail-open)" || ng "壊れた JSON: rc=$rc out=$out"
out="$(head -c 4096 /dev/urandom | python3 "$HOOK" 2>&1)"; rc=$?
{ [ -z "$out" ] && [ "$rc" -eq 0 ]; } && ok "binary stdin でも死なない" || ng "binary stdin: rc=$rc out=$out"
out="$(run_hook '{"tool_name":"Bash","tool_input":{"command":["not","a","string"]}}')"; rc=$?
{ [ -z "$out" ] && [ "$rc" -eq 0 ]; } && ok "command が文字列でない入力" || ng "非文字列 command: rc=$rc out=$out"
# 実 file: 読めない binary の script を実行する command (= 検査対象の file が壊れていても死なない)
head -c 2048 /dev/urandom > "$TMP/driver.py"
out="$(run_hook '{"tool_name":"Bash","cwd":"'"$TMP"'","tool_input":{"command":"python3 driver.py"}}')"; rc=$?
{ [ -z "$out" ] && [ "$rc" -eq 0 ]; } && ok "binary の script file でも死なない" || ng "binary script: rc=$rc out=$out"

echo "=== カナリア (偽 HOME の本番配線) ==="
H="$TMP/canary-home"
mkdir -p "$H/.claude"
out="$(HOME="$H" python3 "$HOOK" --canary --force-applicable 2>&1)"; rc=$?
{ [ "$rc" -ne 0 ] && case "$out" in NOT\ ARMED*) true ;; *) false ;; esac; } \
  && ok "settings.json が無い → NOT ARMED (rc!=0)" || ng "settings 無しで: rc=$rc $out"
printf '{}\n' > "$H/.claude/settings.json"
out="$(HOME="$H" python3 "$HOOK" --canary --force-applicable 2>&1)"; rc=$?
{ [ "$rc" -ne 0 ] && case "$out" in *entry*) true ;; *) false ;; esac; } \
  && ok "entry が無い → NOT ARMED (entry)" || ng "entry 無しで: rc=$rc $out"
if command -v jq >/dev/null 2>&1; then
  # 本物の配線経路 (sync-hook-settings.sh) で偽 settings に入れる = list に登録漏れがあればここで落ちる
  bash "$ROOT/scripts/sync-hook-settings.sh" "$H/.claude/settings.json" >/dev/null 2>&1
  out="$(HOME="$H" python3 "$HOOK" --canary --force-applicable 2>&1)"; rc=$?
  { [ "$rc" -eq 0 ] && case "$out" in ARMED*) true ;; *) false ;; esac; } \
    && ok "sync-hook-settings.sh で配線 → ARMED" || ng "配線後: rc=$rc $out"
  # install 済み hook が壊れている (= 常に通す) → NOT ARMED
  rm -f "$H/.claude/hooks/office-inplace-guard.py"
  printf '#!/bin/sh\ncat >/dev/null\nexit 0\n' > "$H/.claude/hooks/office-inplace-guard.py"
  chmod +x "$H/.claude/hooks/office-inplace-guard.py"
  out="$(HOME="$H" python3 "$HOOK" --canary --force-applicable 2>&1)"; rc=$?
  { [ "$rc" -ne 0 ] && case "$out" in *deny*) true ;; *) false ;; esac; } \
    && ok "何も止めない hook → NOT ARMED (カナリアを deny しない)" || ng "壊れた hook で: rc=$rc $out"
else
  echo "  SKIP  jq 不在 — sync-hook-settings.sh 経由の ARMED 検査を省略"
fi

echo
echo "=== Result: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
