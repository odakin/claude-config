#!/bin/bash
# Test for standing-cc-guard.sh (config は fixture = STANDING_CC_CONFIG で渡す)
set -uo pipefail
HOOK="$(dirname "$0")/standing-cc-guard.sh"
PASS=0; FAIL=0
run_assert() {
    local name="$1" expected="$2" got="$3"
    if [ "$expected" = "$got" ]; then echo "✓ $name"; PASS=$((PASS+1))
    else echo "✗ $name (expected=$expected, got=$got)"; FAIL=$((FAIL+1)); fi
}
TMPDIR="$(mktemp -d)"; trap 'rm -rf "$TMPDIR"' EXIT
CFG="$TMPDIR/cc.yaml"
cat > "$CFG" <<'YAML'
label: "テスト用の定型メール"
reason_doc: "docs/cc.md"
trigger_keywords:
  - "様式14"
  - "宿泊予約"
exclusion_keywords:
  - "事前案内"
required_cc:
  - aaa@example.com
  - bbb@example.com
inactive_cc:
  - zzz@example.com   # 休業中
YAML
decision() {
    STANDING_CC_CONFIG="$CFG" bash "$HOOK" <<<"$1" 2>/dev/null | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null
}
run_assert "別 tool は素通し" "" "$(decision '{"tool_name":"Bash","tool_input":{"command":"様式14"}}')"
run_assert "trigger + Cc 全員 → pass" "" "$(decision '{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"様式14","body":"x","cc":["aaa@example.com","bbb@example.com"]}}')"
run_assert "trigger + Cc 不足 → ask" "ask" "$(decision '{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"様式14","body":"x","cc":["aaa@example.com"]}}')"
run_assert "trigger なし → pass" "" "$(decision '{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"打ち合わせ","body":"x","cc":[]}}')"
run_assert "trigger + exclusion → pass" "" "$(decision '{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"様式14 事前案内","body":"x","cc":[]}}')"
run_assert "body 側 trigger + 不足 → ask" "ask" "$(decision '{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"ご連絡","body":"宿泊予約の件です","cc":[]}}')"
run_assert "休止の宛先 → ask (trigger 無しでも)" "ask" "$(decision '{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"打ち合わせ","body":"x","cc":["zzz@example.com"]}}')"
run_assert "必須全員 + 休止の宛先 → ask" "ask" "$(decision '{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"様式14","body":"x","cc":["aaa@example.com","bbb@example.com","zzz@example.com"]}}')"
# tools を指定すると、 それ以外の send_email は見ない
printf 'tools:\n  - mcp__gmail-y__send_email\n' >> "$CFG"
run_assert "tools 指定外の send_email は素通し" "" "$(decision '{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"様式14","body":"x","cc":[]}}')"
run_assert "tools 指定の tool は検査" "ask" "$(decision '{"tool_name":"mcp__gmail-y__send_email","tool_input":{"subject":"様式14","body":"x","cc":[]}}')"
# config 未設定 = fail-open
out="$(bash "$HOOK" <<<'{"tool_name":"mcp__gmail-x__send_email","tool_input":{"subject":"様式14","body":"x","cc":[]}}' 2>/dev/null)"
run_assert "config 未設定 → 何もしない" "" "$out"
echo ""; echo "PASS: $PASS, FAIL: $FAIL"
[ "$FAIL" = "0" ]
