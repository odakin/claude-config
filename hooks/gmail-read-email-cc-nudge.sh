#!/usr/bin/env bash
# gmail-read-email-cc-nudge.sh — PostToolUse hook (layer 1)
#
# 正本: ~/Claude/claude-config/hooks/gmail-read-email-cc-nudge.sh
# 配信: claude-config/setup.sh install_hooks (= ~/.claude/hooks/ に symlink +
#       settings.json の PostToolUse に登録、 matcher = ^mcp__gmail.*__read_email$)
#
# 動作 (= 非 block、 -nudge):
#   Gmail MCP の read_email の出力のヘッダの段 (最初の空行まで) が To 行を持ち Cc 行を持たない時に、
#   「この出力は Cc を出さない (Cc 行が無い ≠ Cc が空)。 Cc を述べる前にヘッダを読む」
#   を 1 行 inject する。 出力に Cc 行があれば silent (= server が Cc を出す版に
#   なったら自然に黙る)。 To 行の無い出力 (エラー等) も silent。
#
# 背景: conventions/mcp.md#gmail-read-email-omits-cc — read_email が出すヘッダは
#   Subject・From・To・Date だけで、 To が並ぶので一覧が完全に見える。 その出力から
#   「この便は Cc に誰も入っていない」 と述べる誤りが、 規則の文を足した後も続いた
#   (実測)。 文は読む turn で当たらない = 読んだ瞬間に出す。
#
# 読み手の command: 層の外の読み手 (account-direct.py) が置いてあればそれを名指し、
#   無ければ Gmail API の metadata 読み (mcp.md の節) を指す。
#
# テスト env:
#   GMAIL_CC_NUDGE_READER   読み手 script の path (既定 = ~/Claude/gmail-mcp-config/scripts/account-direct.py)
#
# 安全: 全 path で fail-open (exit 0)。

set -uo pipefail

INPUT="$(cat 2>/dev/null || true)"

# 応答の本文 = 文字列ならそのまま、 content block の配列なら text を連結
if command -v jq >/dev/null 2>&1; then
  TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)"
  MSG_ID="$(printf '%s' "$INPUT" | jq -r '.tool_input.messageId // .tool_input.message_id // empty' 2>/dev/null || true)"
  RESP="$(printf '%s' "$INPUT" | jq -r '(.tool_response // .tool_result // empty)
    | if type == "string" then . elif type == "array" then (map(.text? // "") | join("\n")) else tojson end' 2>/dev/null || true)"
else
  TOOL_NAME="$(printf '%s' "$INPUT" | grep -oE '"tool_name"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
  MSG_ID="$(printf '%s' "$INPUT" | grep -oE '"messageId"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
  RESP="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
r=json.load(sys.stdin); r=r.get("tool_response", r.get("tool_result", ""))
print(r if isinstance(r, str) else "\n".join(b.get("text", "") for b in r if isinstance(b, dict)) if isinstance(r, list) else json.dumps(r))' 2>/dev/null || true)"
fi

# matcher の防御的再 check (= settings の matcher は正規表現の部分一致になりうる)
case "$TOOL_NAME" in
  mcp__gmail*__read_email) : ;;
  *) exit 0 ;;
esac

[ -z "$RESP" ] && exit 0

# 見るのはヘッダの段 (最初の空行まで) だけ。 本文の「Cc: ○○様」 の行 (宛名の直下に Cc を書く流儀) は
# ヘッダの Cc ではない = それを Cc と読むと、 まさにこの罠の場面で黙る (実測の出力で確かめた)
HEADERS="$(printf '%s\n' "$RESP" | awk 'NF == 0 { exit } { print }')"
printf '%s\n' "$HEADERS" | grep -qiE '^To:[[:space:]]' || exit 0
printf '%s\n' "$HEADERS" | grep -qiE '^Cc:[[:space:]]' && exit 0

ACCOUNT="$(printf '%s' "$TOOL_NAME" | sed -nE 's/^mcp__gmail-([A-Za-z0-9_]+)__read_email$/\1/p')"
READER="${GMAIL_CC_NUDGE_READER:-$HOME/Claude/gmail-mcp-config/scripts/account-direct.py}"

if [ -f "$READER" ] && [ -n "$ACCOUNT" ]; then
  READER_SHOWN="${READER/#$HOME/~}"
  HOW="python3 $READER_SHOWN $ACCOUNT get ${MSG_ID:-<message id>}"
else
  HOW="Gmail API の messages.get (format=metadata, metadataHeaders=Cc)"
fi

MSG="⚠️ read_email は Cc を出さない (出力に Cc 行が無い ≠ Cc が空)。 この mail の Cc を述べる・判断に使う・返信で引き継ぐ前にヘッダを読む: $HOW (conventions/mcp.md#gmail-read-email-omits-cc)"

if command -v jq >/dev/null 2>&1; then
  jq -n --arg msg "$MSG" '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": $msg}}'
else
  esc="$(printf '%s' "$MSG" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null)" || exit 0
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s}}\n' "$esc"
fi

exit 0
