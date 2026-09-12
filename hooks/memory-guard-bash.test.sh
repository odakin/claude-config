#!/usr/bin/env bash
# memory-guard-bash.test.sh — memory-guard-bash.sh (Bash 用) の self-test (hermetic)
#
# 正本: claude-config/hooks/memory-guard-bash.test.sh
# 実行: bash hooks/memory-guard-bash.test.sh (run-all-checks.sh が自動発見)
#
# 象限: deny (redirect / tee / cp / mv による memory 書き込み) / pass
#       (MEMORY.md whitelist・machine-local escape hatch・read 系・非 memory)。
# 本 hook に ask 象限は無い (2026-04-17 に deny 格上げ済)。
#
# ⚠️ WRITE_PATTERN の既知の検出限界 (python -c / heredoc / printf redirect 等)
# は仕様 — ここでは「検出しないこと」を回帰仕様として P6/P7 で固定する
# (= 将来 pattern を広げたら test も意図的に更新する)。 限界の説明は
# hook header 参照。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/memory-guard-bash.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }

pass=0; fail=0; results=()

MEM="/home/tester/.claude/projects/-home-tester-work/memory"

decision() { # <json input> -> "deny" or ""
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null \
    | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null
}

assert() { # <label> <expect: deny|pass> <command string>
  local label="$1" expect="$2" cmd="$3" got json
  json="$(jq -nc --arg c "$cmd" '{tool_name:"Bash",tool_input:{command:$c}}')"
  got="$(decision "$json")"
  [ -z "$got" ] && got="pass"
  if [ "$got" = "$expect" ]; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect got=$got)")
  fi
}

echo "=== deny 象限 ==="
assert "D1: > redirect"        deny "echo 'new fact' > $MEM/feedback_x.md"
assert "D2: >> append"         deny "echo 'more' >> $MEM/reference_y.md"
assert "D3: tee"               deny "echo body | tee $MEM/reference_z.md"
assert "D4: cp"                deny "cp /tmp/draft.md $MEM/feedback_w.md"
assert "D5: mv"                deny "mv /tmp/draft.md $MEM/reference_v.md"

echo "=== pass 象限 ==="
assert "P1: MEMORY.md への redirect は許可" pass "echo '- entry' >> $MEM/MEMORY.md"
assert "P2: machine-local escape hatch"     pass "echo 'fact' > $MEM/reference_hw.md # machine-local: this-box quirk"
assert "P3: read 系 (cat)"                  pass "cat $MEM/reference_y.md"
assert "P4: read 系 (ls/grep)"              pass "ls $MEM/ && grep -r keyword $MEM/"
assert "P5: 非 memory path への redirect"   pass "echo x > /home/tester/notes/memo.md"
assert "P6: 検出限界の固定: python -c 経由" pass "python3 -c \"open('$MEM/f.md','w').write('x')\""
assert "P7: 検出限界の固定: printf redirect 変数経由" pass "OUT=$MEM/f.md; printf 'x' > \$OUT"
assert "P8: 空 command"                     pass ""

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
