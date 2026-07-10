#!/usr/bin/env bash
# google-url-guard.test.sh — google-url-guard.sh の self-test (hermetic)
#
# 正本: claude-config/hooks/google-url-guard.test.sh
# 実行: bash hooks/google-url-guard.test.sh (run-all-checks.sh が自動発見)
#
# 象限: ask ((A) /u/N/ slot index / (B) account-sensitive URL の authuser 欠落)
#       / pass (authuser 付き・非対象 URL・placeholder)。
# 本 hook に deny 象限は無い (設計上 ask のみ)。
#
# fixture の URL はすべて架空 ID (実 document / class ID を使わない)。
# authuser の email 値も placeholder 形。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/google-url-guard.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }

pass=0; fail=0; results=()

decision() { # <json input> -> "ask" or ""
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null \
    | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null
}

assert() { # <label> <expect: ask|pass> <content string (Bash command 扱い)>
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

AU="authuser=someone%40example.com"

echo "=== ask 象限 ==="
assert "A1: /u/N/ slot index"                 ask  "open 'https://docs.google.com/u/1/document/d/FAKEID123/edit'"
assert "A2: classroom URL authuser 無し"       ask  "echo https://classroom.google.com/c/FAKEclass01"
assert "A3: docs URL authuser 無し"            ask  "echo https://docs.google.com/document/d/FAKEdoc01/edit"
assert "A4: drive folder authuser 無し"        ask  "echo https://drive.google.com/drive/folders/FAKEfolder01"
assert "A5: gmail view authuser 無し"          ask  "echo https://mail.google.com/mail/u0inbox"

echo "=== pass 象限 ==="
assert "P1: authuser 付き classroom"           pass "echo 'https://classroom.google.com/c/FAKEclass01?$AU'"
assert "P2: authuser 付き docs"                pass "echo 'https://docs.google.com/document/d/FAKEdoc01/edit?$AU'"
assert "P3: placeholder {classId} は skip"     pass "echo 'https://classroom.google.com/c/{classId}'"
assert "P4: 非 account-sensitive root URL"     pass "echo https://classroom.google.com/"
assert "P5: google.com を含まない command"      pass "echo https://example.com/u/1/page"
assert "P6: 一般 google.com URL (非対象 path)" pass "echo https://www.google.com/search?q=test"
assert "P7: 空 stdin"                          pass ""

# Edit tool の content 経由でも同じ scan が効くこと (tostring 経路)
json="$(jq -nc '{tool_name:"Edit",tool_input:{file_path:"/tmp/x.md",new_string:"link: https://docs.google.com/u/2/document/d/FAKEID/edit"}}')"
got="$(decision "$json")"
if [ "$got" = "ask" ]; then
  pass=$((pass+1)); results+=("✅ A6: Edit new_string 内の /u/N/ も検出")
else
  fail=$((fail+1)); results+=("❌ A6: Edit new_string 内の /u/N/ (got=${got:-pass})")
fi

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
