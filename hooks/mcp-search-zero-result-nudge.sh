#!/usr/bin/env bash
# mcp-search-zero-result-nudge.sh — PostToolUse hook (layer 1)
#
# 正本: ~/Claude/claude-config/hooks/mcp-search-zero-result-nudge.sh
# 配信: claude-config/setup.sh install_hooks (= ~/.claude/hooks/ に symlink +
#       settings.json の PostToolUse に登録、 matcher = mcp__.*__(search_threads|...))
#
# 動作 (= 非 block、 -nudge):
#   Gmail / Calendar 等の MCP search-style tool が **0 件 / empty 結果**を
#   返した直後に、 「scope universalization 禁止 + scope enumeration template」
#   の強 reminder を inject する。 結果に hit がある時は silent (= noise 抑制)。
#
#   sibling = mcp-search-scope-reminder-nudge.sh (PreToolUse、 tool 呼び出し
#   直前の anchoring)。 本 hook (PostToolUse) は decision-point 直前 (=
#   「0 件だったから X は無い」 と次 token で書く瞬間) の 2 段目 anchoring。
#
# 0-件検出 (= conservative: 明確 zero pattern のみ flag、 ambiguous は silent):
#   (a) tool_response が完全空 / null (= "" or "null", 全角空白等 trim 後)
#   (b) "no messages found" / "no threads found" / "no results" / "0 results"
#   (c) "messages": [] / "threads": [] / "events": [] / "results": []
#   (d) "Found 0" / "0 件" / "該当なし"
#
#   ⚠️ length-based heuristic (旧版 < 80 chars) は廃止: 1-message 結果でも
#   `[{"id":"..","threadId":".."}]` ~40 chars 等で false-positive 量産。
#   明確な zero marker が無い response は silent pass (= Hook A の PreToolUse
#   anchoring が既に効いている、 重複 nudge より miss を許容)。 false positive
#   を避ける方を強く優先 = normal flow の noise 抑制 + Claude が hook 出力
#   全般を discount し始める二次 decay 予防 (hook-authoring.md#hook-no-go-judgment)。
#
# Matcher (settings.json 側): Hook A と同じ
#   mcp__.*__(search_threads|search_emails|list_messages|list_threads|search_threads_by|list_events)
#
# 設計動機 (= 2026-06-20 layer-3 RCA、 個人層 plan 参照):
#   起票 session で 単一 account wired のアプリ内蔵 connector search_threads の 0 件結果を
#   「Gmail で 0 件」 「Mac Mail 全 sweep 0 件」 と 5 回 universalize。 fill-in
#   template 無しでは scope を埋めずに summary 形成へ滑り込んだ。 本 hook は
#   0 件結果の PostToolUse で「scope enumerate せよ」 を強制 inject する 2 段目
#   防御 (= 実 incident の固有名・thread 内容は public layer 1 に出さない、
#   mechanism のみ。 詳細 = odakin-prefs/plans/2026-06-20-mcp-scope-guard-hooks.md)。
#
# 二次 trap (= author confession):
#   起票 transcript で同 trap が 5 回連続発生した状況では reminder が出ていても
#   無視された可能性ある。 本 hook の効果は仮説段階。 ただし PreToolUse Hook A
#   (= 呼び出し直前の anchoring) + Hook C (= SessionStart の scope enumeration)
#   との多層で leverage は強化される。
#
# 出力経路: stdout JSON additionalContext + surface file (Hook A と同 pattern)
# 安全: 全 path で fail-open。
#
# テスト env:
#   MCP_ZERO_NUDGE_FORCE=1      matcher / 検出 logic を bypass して必ず発火

set -uo pipefail

INPUT="$(cat 2>/dev/null || true)"

if command -v jq >/dev/null 2>&1; then
  TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)"
  TOOL_RESPONSE="$(printf '%s' "$INPUT" | jq -r '.tool_response // .tool_result // empty' 2>/dev/null || true)"
else
  TOOL_NAME="$(printf '%s' "$INPUT" | grep -oE '"tool_name"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
  TOOL_RESPONSE="$INPUT"  # fail-open: 全 input を scan 対象に (= jq 無し環境)
fi

# matcher 防御的再 check
if [ "${MCP_ZERO_NUDGE_FORCE:-0}" != "1" ]; then
  case "$TOOL_NAME" in
    mcp__*__search_threads | mcp__*__search_emails | mcp__*__list_messages | \
    mcp__*__list_threads  | mcp__*__search_threads_by | mcp__*__list_events) : ;;
    *) exit 0 ;;
  esac
fi

# tool_response が空 / null なら fallback として INPUT 全体を scan 対象に
# (= MCP server や Claude Code build によっては tool_response が別 key に格納
# される可能性、 conservative に対応)
[ -z "$TOOL_RESPONSE" ] && TOOL_RESPONSE="$INPUT"

# ---------- 0-件検出 (= 明確 marker のみ、 length heuristic 廃止) ----------
IS_ZERO=0

# FORCE bypass: 必ず 0-件扱い (= test 用)
if [ "${MCP_ZERO_NUDGE_FORCE:-0}" = "1" ]; then
  IS_ZERO=1
fi

# (a) 完全空 / null (= trim 後に空 or リテラル "null")
if [ "$IS_ZERO" = 0 ]; then
  trimmed="$(printf '%s' "$TOOL_RESPONSE" | tr -d '[:space:]')"
  if [ -z "$trimmed" ] || [ "$trimmed" = "null" ] || [ "$trimmed" = '""' ] || [ "$trimmed" = '[]' ] || [ "$trimmed" = '{}' ]; then
    IS_ZERO=1
  fi
fi

# (b)-(d) 高信号 zero-pattern (= 大文字小文字無視、 word boundary は緩く)
if [ "$IS_ZERO" = 0 ]; then
  if printf '%s' "$TOOL_RESPONSE" | grep -qiE \
      'no (messages|threads|results|events|emails) found|^0 (results|matches|messages|threads)|found 0 (results|matches|messages|threads|emails|events)|"(messages|threads|events|results)":[[:space:]]*\[[[:space:]]*\]|該当なし|^0 件|^0件|empty result|no matching|"resultSizeEstimate":[[:space:]]*0\b'; then
    IS_ZERO=1
  fi
fi

# 0 件と判定できなければ silent (= hit がある時 noise を出さない)
[ "$IS_ZERO" = 0 ] && exit 0

# domain 判定 (= reminder 内 example の絞り込み用)
DOMAIN="this MCP tool"
case "$TOOL_NAME" in
  *gmail* | *__search_threads | *__search_emails | *__list_messages | *__list_threads | *__search_threads_by)
    DOMAIN="Gmail" ;;
  *calendar* | *__list_events)
    DOMAIN="Calendar" ;;
esac

# 既知 Gmail account 列挙 (Hook A と同 logic)
KNOWN_ACCOUNTS=""
if [ -d "$HOME/.gmail-mcp" ]; then
  for d in "$HOME/.gmail-mcp"/*/; do
    [ -d "$d" ] || continue
    base="$(basename "$d")"
    case "$base" in accounts|server|node_modules) continue ;; esac
    if [ -f "$d/credentials.json" ]; then
      KNOWN_ACCOUNTS="${KNOWN_ACCOUNTS:+$KNOWN_ACCOUNTS }$base"
    fi
  done
fi

REMINDER="🛑 MCP search 0 件結果 — scope universalization 禁止 zone

tool: $TOOL_NAME
result: 0 件 / empty"

if [ -n "$KNOWN_ACCOUNTS" ] && [ "$DOMAIN" = "Gmail" ]; then
  REMINDER="$REMINDER
known Gmail accounts on this machine: $KNOWN_ACCOUNTS
session-active subset may be smaller (= Claude Code desktop --allowedTools 制限)。"
fi

REMINDER="$REMINDER

⚠️ 次の token で禁止する claim:
  ❌ 「$DOMAIN で 0 件」          ← scope unspecified
  ❌ 「Gmail に無い」              ← scope unspecified
  ❌ 「該当なしで確定」            ← scope unspecified
  ❌ 「全 sweep 完了」             ← scope unspecified
  ❌ 「<人名> 過去往来 0」         ← scope unspecified
  ❌ 「Mac Mail 全 N 件で確定」    ← 検証経路 1 つを「全」 と表現

✅ 必須 fill-in template (= 1 行も省略禁止):

  Verified scope = ____ (この tool が見えた account / 範囲を列挙)
  NOT verified  = ____ (まだ見ていない account / 範囲を列挙)
  Result        = 0 件 in [Verified scope]

NOT verified が空でない場合、 結論を保留して以下のいずれか:
  1. 残り account 経路を回す (= Python wrapper / 別 MCP / ToolSearch で connector 探索)
  2. user に「以下のみ verify、 残り未 verify」 と honest に framing して判断を渡す

設計動機: 2026-06-20 layer-3 RCA — 単一 Gmail account のみ wired で人名 query
  0 件 → 「Gmail で 0 件」 → 「Mac Mail 全 sweep 0 件で確定」 5 回宣言 → user 複数回
  push でようやく別 account 経路で実 thread を発見。 詳細:
  ~/Claude/odakin-prefs/plans/2026-06-20-mcp-scope-guard-hooks.md (= 個人層)"

# ---------- surface file (= desktop fallback、 hook-authoring.md#frontend-dependent-cowork) ----------
SURFACE_DIR="$HOME/.claude/surface"
mkdir -p "$SURFACE_DIR" 2>/dev/null || true
{ printf '# 🛑 MCP search 0 件 (= 直前の search tool 結果、 universal claim 禁止)\n\n'
  printf '%s\n' "$REMINDER"; } > "$SURFACE_DIR/mcp-zero-result.txt" 2>/dev/null || true

printf '%s\n' "$REMINDER" >&2

# stdout JSON (= PostToolUse の additionalContext + systemMessage、 spec
# 確度が build 依存ゆえ 2 経路併用。 hook-authoring.md#warn-mode-spec-uncertainty)
if command -v jq >/dev/null 2>&1; then
  jq -n --arg msg "$REMINDER" '{
    "hookSpecificOutput": {
      "hookEventName": "PostToolUse",
      "additionalContext": $msg
    },
    "systemMessage": $msg
  }'
else
  esc="$(printf '%s' "$REMINDER" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "[mcp-search-zero-result] $TOOL_NAME returned 0")"
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s},"systemMessage":%s}\n' "$esc" "$esc"
fi

exit 0
