#!/usr/bin/env bash
# zsh-word-split-guard.test.sh — 述語の selftest + hook 入出力 (deny の JSON / zsh 以外は無音 / opt-out / Bash 以外は無音)
#
# 正本: claude-config/hooks/zsh-word-split-guard.test.sh

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/zsh-word-split-guard.py"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 不在 — selftest 省略"; exit 0; }

pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

echo "=== 述語 (--selftest) ==="
st="$(python3 "$HOOK" --selftest 2>&1)"; rc=$?
printf '%s\n' "$st" | sed 's/^/  /'
[ "$rc" -eq 0 ] && ok "selftest" || ng "selftest rc=$rc"

BAD='{"tool_name":"Bash","tool_input":{"command":"ids=$(gh run list); for id in $ids; do echo $id; done"}}'
GOOD='{"tool_name":"Bash","tool_input":{"command":"gh run list | while read -r id; do echo $id; done"}}'

echo "=== hook 入出力 ==="
out="$(printf '%s' "$BAD" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
case "$out" in
  *'"permissionDecision": "deny"'*'while read -r'*) ok "zsh + 分割されない loop → deny + 直し方" ;;
  *) ng "deny されない: $out" ;;
esac
printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert d["hookEventName"]=="PreToolUse"' \
  && ok "出力は PreToolUse の JSON" || ng "JSON 形が違う"
out="$(printf '%s' "$GOOD" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
[ -z "$out" ] && ok "while read は通す" || ng "while read で出力: $out"
out="$(printf '%s' "$BAD" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/bash python3 "$HOOK")"
[ -z "$out" ] && ok "bash では何もしない (分割される)" || ng "bash で出力: $out"
out="$(printf '%s' "$BAD" | env -u CLAUDE_ZSH_SPLIT_GUARD SHELL=/bin/bash CLAUDE_CODE_SHELL=/bin/zsh python3 "$HOOK")"
[ -n "$out" ] && ok "CLAUDE_CODE_SHELL が SHELL より優先" || ng "CLAUDE_CODE_SHELL=zsh で無音"
out="$(printf '%s' "$BAD" | env -u CLAUDE_CODE_SHELL SHELL=/bin/zsh CLAUDE_ZSH_SPLIT_GUARD=0 python3 "$HOOK")"
[ -z "$out" ] && ok "opt-out (CLAUDE_ZSH_SPLIT_GUARD=0)" || ng "opt-out が効かない"
out="$(printf '{"tool_name":"Read","tool_input":{"file_path":"x"}}' | SHELL=/bin/zsh python3 "$HOOK")"
[ -z "$out" ] && ok "Bash 以外は無音" || ng "Read で出力: $out"
out="$(printf 'not json' | SHELL=/bin/zsh python3 "$HOOK")"; rc=$?
{ [ -z "$out" ] && [ "$rc" -eq 0 ]; } && ok "読めない入力は黙って通す (fail-open)" || ng "壊れた入力: rc=$rc out=$out"

echo
echo "=== Result: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
