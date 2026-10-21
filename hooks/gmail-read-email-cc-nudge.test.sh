#!/usr/bin/env bash
# gmail-read-email-cc-nudge.test.sh — 発火 / 沈黙の検査
#
# 正本: ~/Claude/claude-config/hooks/gmail-read-email-cc-nudge.test.sh
# 合成の入力だけを使う (実在の mail・アドレスを書かない)。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/gmail-read-email-cc-nudge.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook が無い: $HOOK"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq が無い (入力の組み立てに使う)"; exit 0; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
READER="$TMP/reader.py"
: > "$READER"
export GMAIL_CC_NUDGE_READER="$READER"

pass=0
fail=0

input() {  # $1 = tool_name / $2 = tool_response (文字列) / $3 = 'array' なら content block の配列にする
  if [ "${3:-}" = array ]; then
    jq -n --arg t "$1" --arg r "$2" '{tool_name: $t, tool_input: {messageId: "abc123"}, tool_response: [{type: "text", text: $r}]}'
  else
    jq -n --arg t "$1" --arg r "$2" '{tool_name: $t, tool_input: {messageId: "abc123"}, tool_response: $r}'
  fi
}

check() {  # $1 = label / $2 = 期待 (fire|silent) / $3 = 出力に含むべき語 (fire のとき、 空なら見ない) / $4 = 入力
  local out
  out="$(printf '%s' "$4" | bash "$HOOK" 2>/dev/null)"
  local got=silent
  printf '%s' "$out" | grep -q 'read_email は Cc を出さない' && got=fire
  if [ "$got" = "$2" ] && { [ -z "${3:-}" ] || printf '%s' "$out" | grep -qF -- "$3"; }; then
    pass=$((pass+1)); echo "✅ $1"
  else
    fail=$((fail+1)); echo "❌ $1 (期待 $2 / 実際 $got)"; printf '%s\n' "$out" | sed 's/^/    /'
  fi
}

NO_CC=$'Thread ID: t1\nSubject: Re: 件名\nFrom: a@example.org\nTo: b@example.org\nDate: Mon, 1 Jan 2026 00:00:00 +0900\n\n本文'
WITH_CC=$'Thread ID: t1\nSubject: Re: 件名\nFrom: a@example.org\nTo: b@example.org\nCc: c@example.org\nDate: Mon, 1 Jan 2026 00:00:00 +0900\n\n本文'
BODY_CC=$'Thread ID: t1\nSubject: Re: 件名\nFrom: a@example.org\nTo: b@example.org\nDate: Mon, 1 Jan 2026 00:00:00 +0900\n\n甲野様\nCc: 乙川様\n\n本文'
ERROR_RESP='Error: Requested entity was not found.'

check "Cc 行の無い read_email → 出す (account と id を名指す)" fire "lab get abc123" "$(input mcp__gmail-lab__read_email "$NO_CC")"
check "content block の配列 (JSON の \\n) でも出す" fire "lab get abc123" "$(input mcp__gmail-lab__read_email "$NO_CC" array)"
check "本文の「Cc: ○○様」 はヘッダの Cc でない → 出す" fire "lab get abc123" "$(input mcp__gmail-lab__read_email "$BODY_CC" array)"
check "Cc 行がある → 黙る" silent "" "$(input mcp__gmail-lab__read_email "$WITH_CC")"
check "Cc 行がある (配列) → 黙る" silent "" "$(input mcp__gmail-lab__read_email "$WITH_CC" array)"
check "To 行の無いエラー → 黙る" silent "" "$(input mcp__gmail-lab__read_email "$ERROR_RESP")"
check "read_email 以外の tool → 黙る" silent "" "$(input mcp__gmail-lab__search_emails "$NO_CC")"
check "gmail でない server → 黙る" silent "" "$(input mcp__other__read_email "$NO_CC")"
check "空の応答 → 黙る" silent "" "$(input mcp__gmail-lab__read_email "")"
GMAIL_CC_NUDGE_READER="$TMP/none.py" check "読み手が無い → API の読み方を指す" fire "metadataHeaders=Cc" "$(input mcp__gmail-lab__read_email "$NO_CC")"
check "壊れた入力 → 黙る (fail-open)" silent "" "not json"

echo "pass=$pass fail=$fail"
[ "$fail" = 0 ]
