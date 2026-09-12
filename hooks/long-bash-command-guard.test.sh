#!/usr/bin/env bash
# long-bash-command-guard.test.sh — long-bash-command-guard.sh の self-test (配信対象外)
#
# 実行: bash hooks/long-bash-command-guard.test.sh   (exit code = fail 数)

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/long-bash-command-guard.sh"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq が無いので skip (hook 自体も fail-open)"
  exit 0
fi

pass=0
fail=0
results=()

# rc <limit> <command string> → hook の exit code
rc() {
  local lim="$1" cmd="$2" json
  json="$(jq -nc --arg c "$cmd" '{hook_event_name:"PreToolUse",tool_name:"Bash",tool_input:{command:$c}}')"
  if [ -n "$lim" ]; then
    printf '%s' "$json" | CLAUDE_LONG_BASH_LIMIT="$lim" "$HOOK" >/dev/null 2>&1
  else
    printf '%s' "$json" | "$HOOK" >/dev/null 2>&1
  fi
  echo $?
}

assert() { # <label> <expect rc> <got rc>
  if [ "$2" = "$3" ]; then
    pass=$((pass+1)); results+=("✅ $1")
  else
    fail=$((fail+1)); results+=("❌ $1 (expect rc=$2 got rc=$3)")
  fi
}

short="$(printf 'a%.0s' $(seq 1 100))"
long_ascii="$(printf 'a%.0s' $(seq 1 4000))"
long_cjk="$(printf '日%.0s' $(seq 1 4000))"   # 4000 codepoint / 12000 byte

echo "=== 既定閾値 (3000) ==="
assert "T1: 短い command は通る"            0 "$(rc '' "$short")"
assert "T2: 4000 文字 ASCII は block"       2 "$(rc '' "$long_ascii")"
assert "T3: 4000 文字 CJK も block (= byte でなく codepoint で測る)" \
                                            2 "$(rc '' "$long_cjk")"

echo "=== 境界 ==="
assert "T4: limit ちょうどは通る"           0 "$(rc 10 '0123456789')"
assert "T5: limit +1 は block"              2 "$(rc 10 '0123456789X')"

echo "=== 無効化・退行 ==="
assert "T6: limit=0 は無効化 (長くても通る)" 0 "$(rc 0 "$long_ascii")"
assert "T7: limit が非数値なら fail-open"    0 "$(rc 'abc' "$long_ascii")"
assert "T8: command が無い input は通る"     0 "$(printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{}}' | "$HOOK" >/dev/null 2>&1; echo $?)"
assert "T9: 空 stdin は通る"                 0 "$(printf '' | "$HOOK" >/dev/null 2>&1; echo $?)"

# block 時に stderr で代替手段を案内しているか (= Claude が書き換えられる情報を持つ)
msg="$(jq -nc --arg c "$long_ascii" '{hook_event_name:"PreToolUse",tool_name:"Bash",tool_input:{command:$c}}' | "$HOOK" 2>&1 >/dev/null || true)"
case "$msg" in
  *分割*|*scratchpad*) pass=$((pass+1)); results+=("✅ T10: block 時に代替手段を案内") ;;
  *) fail=$((fail+1)); results+=("❌ T10: block 時の stderr に代替手段が無い") ;;
esac

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
