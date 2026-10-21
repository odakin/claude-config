#!/usr/bin/env bash
# zsh-word-split-guard.test.sh — 述語の selftest + hook 入出力 (deny の JSON / == だけの語と PIPESTATUS は判断なしの updatedInput / 素の log show は deny / zsh 以外は無音 / opt-out / Bash 以外は無音)
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

EQ='{"tool_name":"Bash","tool_input":{"command":"echo ======; echo after","description":"d"}}'
echo "=== equals の書き換え (判断なしの updatedInput) ==="
out="$(printf '%s' "$EQ" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert "permissionDecision" not in d; assert d["updatedInput"]["command"]==chr(101)+"cho "+chr(39)+"======"+chr(39)+"; echo after" and d["updatedInput"]["description"]=="d", d' \
  && ok "== だけの語 → quote した command を updatedInput で返す (判断なし、 他の field は残す)" || ng "書き換えの出力が違う: $out"
out="$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"echo =python3"}}' | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
case "$out" in *'"permissionDecision": "deny"'*) ok "=X (=cmd を意図しうる) は今まで通り deny" ;; *) ng "=X が deny されない: $out" ;; esac

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
LOGBAD='{"tool_name":"Bash","tool_input":{"command":"log show --last 5m 2>/dev/null | grep -c x"}}'
out="$(printf '%s' "$LOGBAD" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
case "$out" in
  *'"permissionDecision": "deny"'*'/usr/bin/log show'*) ok "zsh + 素の log show → deny + full path の直し方" ;;
  *) ng "素の log show が deny されない: $out" ;;
esac
LOGEQ='{"tool_name":"Bash","tool_input":{"command":"echo ======; log show --last 5m"}}'
out="$(printf '%s' "$LOGEQ" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
case "$out" in
  *'"permissionDecision": "deny"'*) ok "== の書き換えができる command でも、 素の log show があれば書き換えずに deny" ;;
  *) ng "== と log show の組で deny されない: $out" ;;
esac
out="$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"/usr/bin/log show --last 5m"}}' | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
[ -z "$out" ] && ok "/usr/bin/log show は通す" || ng "full path で出力: $out"

echo "=== PIPESTATUS の書き換え (判断なしの updatedInput) ==="
want_cmd() {  # $1 = hook の出力 / $2 = 期待する command (env で渡す = quote を重ねない)
  printf '%s' "$1" | WANT="$2" python3 -c 'import json,os,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert "permissionDecision" not in d, d; assert d["updatedInput"]["command"]==os.environ["WANT"], d["updatedInput"]["command"]'
}
PS='{"tool_name":"Bash","tool_input":{"command":"a | b; echo \"exit=${PIPESTATUS[0]}\"","description":"d"}}'
out="$(printf '%s' "$PS" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
want_cmd "$out" 'a | b; echo "exit=${pipestatus[1]}"' \
  && ok "\${PIPESTATUS[0]} → \${pipestatus[1]} を updatedInput で返す (判断なし)" || ng "PIPESTATUS の書き換えが違う: $out"
PSEQ='{"tool_name":"Bash","tool_input":{"command":"echo ======; a | b; echo ${PIPESTATUS[1]}"}}'
out="$(printf '%s' "$PSEQ" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
want_cmd "$out" "echo '======'; a | b; echo \${pipestatus[2]}" \
  && ok "== の quote と PIPESTATUS の書き換えを 1 回で両方当てる" || ng "== と PIPESTATUS の組の書き換えが違う: $out"
PSBAD='{"tool_name":"Bash","tool_input":{"command":"a | b; echo ${PIPESTATUS[$i]}"}}'
out="$(printf '%s' "$PSBAD" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/zsh python3 "$HOOK")"
case "$out" in
  *'"permissionDecision": "deny"'*'pipestatus'*) ok "変数の添字の PIPESTATUS は deny + 直し方" ;;
  *) ng "変数の添字の PIPESTATUS が deny されない: $out" ;;
esac
out="$(printf '%s' "$PS" | env -u CLAUDE_ZSH_SPLIT_GUARD -u CLAUDE_CODE_SHELL SHELL=/bin/bash python3 "$HOOK")"
[ -z "$out" ] && ok "bash では PIPESTATUS を書き換えない" || ng "bash で PIPESTATUS を書き換えた: $out"
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
