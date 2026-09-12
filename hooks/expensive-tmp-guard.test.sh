#!/usr/bin/env bash
# expensive-tmp-guard.test.sh — expensive-tmp-guard.sh の self-test (hermetic)
#
# 正本: claude-config/hooks/expensive-tmp-guard.test.sh
# 実行: bash hooks/expensive-tmp-guard.test.sh (run-all-checks.sh が自動発見)
#
# 象限: ask ((A) Audiveris / (B) oemer / (C) ML training の /tmp 出力) /
#       pass (安価 render・リポ内出力・非対象 command)。
# 本 hook に deny 象限は無い (設計上 ask のみ、 false positive は allow で通す
# 前提の弱検出)。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/expensive-tmp-guard.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }

pass=0; fail=0; results=()

decision() { # <json input> -> "ask" or ""
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null \
    | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null
}

assert() { # <label> <expect: ask|pass> <command string>
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

echo "=== ask 象限 ==="
assert "A1: Audiveris -output /tmp/"        ask  "Audiveris -batch -output /tmp/ocr-run score.pdf"
assert "A2: audiveris (小文字) --output"     ask  "audiveris --output /tmp/exp1 input.pdf"
assert "A3: audiveris -output=/tmp/"        ask  "audiveris -output=/tmp/exp2 input.pdf"
assert "A4: oemer -o /tmp/"                 ask  "oemer -o /tmp/omr-out sheet.png"
assert "A5: oemer --output-dir /tmp/"       ask  "oemer --output-dir /tmp/omr2 sheet.png"
assert "A6: python train --checkpoint-dir"  ask  "python train.py --epochs 10 --checkpoint-dir /tmp/ckpt"
assert "A7: python finetune --save-dir"     ask  "python finetune_model.py --save-dir /tmp/run1"

echo "=== pass 象限 ==="
assert "P1: 安価 render (pdftoppm) は対象外" pass "pdftoppm -png score.pdf /tmp/preview"
assert "P2: Audiveris リポ内出力"            pass "Audiveris -batch -output scores/work-ocr-experiments score.pdf"
assert "P3: oemer リポ内出力"                pass "oemer -o data/ocr-oemer/sheet1 sheet.png"
assert "P4: python train リポ内 checkpoint"  pass "python train.py --checkpoint-dir data/checkpoints/run1"
assert "P5: /tmp/ を含まない command"        pass "ls -la && git status"
assert "P6: /tmp/ はあるが非対象 tool"        pass "cp notes.md /tmp/notes-backup.md"
assert "P7: 空 stdin"                        pass ""

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
