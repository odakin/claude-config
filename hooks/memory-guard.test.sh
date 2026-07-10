#!/usr/bin/env bash
# memory-guard.test.sh — memory-guard.sh (Edit/Write 用) の self-test (hermetic)
#
# 正本: claude-config/hooks/memory-guard.test.sh
# 実行: bash hooks/memory-guard.test.sh (run-all-checks.sh が自動発見)
#
# 象限: deny (memory dir への書き込み) / pass (MEMORY.md whitelist・
#       machine-local escape hatch・非 memory path)。
# 本 hook に ask 象限は無い (2026-04-17 に ask → deny 格上げ済)。
#
# hook は file_path の文字列パターンしか見ないので filesystem fixture 不要。
# path は架空値 (実 user 名・実 home を使わない)。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/memory-guard.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }

pass=0; fail=0; results=()

MEM="/home/tester/.claude/projects/-home-tester-work/memory"

decision() { # <json input> -> "deny" or ""
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null \
    | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null
}

assert() { # <label> <expect: deny|pass> <json>
  local label="$1" expect="$2" json="$3" got
  got="$(decision "$json")"
  [ -z "$got" ] && got="pass"
  if [ "$got" = "$expect" ]; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect got=$got)")
  fi
}

mk_write() { # <file_path> <content>
  jq -nc --arg p "$1" --arg c "$2" '{tool_name:"Write",tool_input:{file_path:$p,content:$c}}'
}
mk_edit() { # <file_path> <new_string>
  jq -nc --arg p "$1" --arg s "$2" '{tool_name:"Edit",tool_input:{file_path:$p,new_string:$s}}'
}

echo "=== deny 象限 ==="
assert "D1: memory への Write"          deny "$(mk_write "$MEM/feedback_foo.md" "some fact")"
assert "D2: memory への Edit"           deny "$(mk_edit "$MEM/reference_bar.md" "updated fact")"

echo "=== pass 象限 ==="
assert "P1: MEMORY.md (index) は許可"   pass "$(mk_write "$MEM/MEMORY.md" "- [x](y.md) — index line")"
assert "P2: machine-local marker (Write)" pass "$(mk_write "$MEM/reference_hw.md" "<!-- machine-local: this-box quirk -->
fact body")"
assert "P3: machine-local marker (Edit)"  pass "$(mk_edit "$MEM/reference_hw.md" "<!-- machine-local: gpu quirk --> new")"
assert "P4: 非 memory path"             pass "$(mk_write "/home/tester/notes/memo.md" "regular note")"
assert "P5: /memory/ 文字列を含まない"   pass "$(mk_write "/home/tester/docs/a.md" "text")"
assert "P6: file_path 無し input"       pass "$(jq -nc '{tool_name:"Write",tool_input:{}}')"
assert "P7: 空 stdin"                   pass ""

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
