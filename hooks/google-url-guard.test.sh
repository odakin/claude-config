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
assert "P8: drive 共有リンク (usp=sharing)"     pass "echo 'https://drive.google.com/drive/folders/FAKEfolder01?usp=sharing'"
assert "P9: docs 共有リンク (usp=drive_link)"   pass "echo 'https://docs.google.com/document/d/FAKEdoc01/edit?usp=drive_link'"
# 共有リンクでも /u/N/ は (A) で ask のまま (= 例外は authuser 軸だけに効く)
assert "A7: 共有リンクでも /u/N/ は ask"        ask  "echo 'https://drive.google.com/u/1/drive/folders/FAKEfolder01?usp=sharing'"

# Edit tool の content 経由でも同じ scan が効くこと (tostring 経路)
json="$(jq -nc '{tool_name:"Edit",tool_input:{file_path:"/tmp/x.md",new_string:"link: https://docs.google.com/u/2/document/d/FAKEID/edit"}}')"
got="$(decision "$json")"
if [ "$got" = "ask" ]; then
  pass=$((pass+1)); results+=("✅ A6: Edit new_string 内の /u/N/ も検出")
else
  fail=$((fail+1)); results+=("❌ A6: Edit new_string 内の /u/N/ (got=${got:-pass})")
fi

# 自己参照の除外: guard 自身の source / test は違反 URL を literal で持つ必要がある
json="$(jq -nc '{tool_name:"Edit",tool_input:{file_path:"/x/claude-config/hooks/google-url-guard.test.sh",new_string:"assert ask https://drive.google.com/u/1/drive/folders/FAKE01"}}')"
got="$(decision "$json")"
if [ -z "$got" ] || [ "$got" = "pass" ]; then
  pass=$((pass+1)); results+=("✅ P10: 自分の test への Edit は自己参照として skip")
else
  fail=$((fail+1)); results+=("❌ P10: 自分の test への Edit が ask された (got=$got)")
fi

# ⚠️ 除外は自分自身に限る: 別 hook の source は従来どおり検査対象
json="$(jq -nc '{tool_name:"Edit",tool_input:{file_path:"/x/claude-config/hooks/other-guard.sh",new_string:"url=https://drive.google.com/u/1/drive/folders/FAKE01"}}')"
got="$(decision "$json")"
if [ "$got" = "ask" ]; then
  pass=$((pass+1)); results+=("✅ A9: 別 hook の source は検査対象のまま")
else
  fail=$((fail+1)); results+=("❌ A9: hooks/ 配下を広く除外してしまっている (got=${got:-pass})")
fi

# 非退行: 普通の file への Edit は従来どおり ask
json="$(jq -nc '{tool_name:"Edit",tool_input:{file_path:"/x/notes/memo.md",new_string:"see https://drive.google.com/u/1/drive/folders/FAKE01"}}')"
got="$(decision "$json")"
if [ "$got" = "ask" ]; then
  pass=$((pass+1)); results+=("✅ A8: 通常 file への Edit は ask のまま")
else
  fail=$((fail+1)); results+=("❌ A8: 通常 file への Edit が素通り (got=${got:-pass})")
fi

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
