#!/usr/bin/env bash
# mcp-search-scope-reminder-nudge.sh — PreToolUse hook (layer 1)
#
# 正本: ~/Claude/claude-config/hooks/mcp-search-scope-reminder-nudge.sh
# 配信: claude-config/setup.sh install_hooks (= ~/.claude/hooks/ に symlink +
#       settings.json の PreToolUse に登録、 matcher = mcp__.*__(search_threads|...))
#
# 動作 (= 非 block、 -nudge):
#   Gmail / Calendar / Slack 等の MCP search-style tool 呼び出し直前に、
#   wire scope の不可視性を思い出させる system-reminder を inject する。
#   stdout = additionalContext JSON (CLI session に inject)、 副作用で
#   $HOME/.claude/surface/mcp-search-reminder.txt に同 reminder を書出し
#   (= desktop Cowork session は SessionStart 経由で読まれる fallback、
#   hook-authoring.md §9.3 / lib-surface.sh と同 pattern)。
#
# Matcher (settings.json 側):
#   mcp__.*__(search_threads|search_emails|list_messages|list_threads|search_threads_by|list_events)
#   = scope universalization のリスクがある「広く scan」 系のみ対象。
#   read_email / get_thread / get_event 等の targeted retrieval (= 明示 ID で
#   1 件取る) は scope の問題が無いので除外。
#
# 設計動機 (= 2026-06-20 layer-3 RCA、 詳細は odakin-prefs 内 plan 参照):
#   起票 session で `mcp__<UUID>__search_threads` (= 単一 account のみ wired
#   な Cowork connector) で人名 query 0 件 → 「Gmail で 0 件」 に scope を
#   universalize → 「Mac Mail 全 sweep 0 件で確定」 と 5 回宣言 → user 複数回
#   push でようやく別 Gmail account 経由で実 thread を発見。 真因 = MCP tool
#   metadata が wire account を expose せず、 0 件結果を「私の sight に入った
#   範囲」 でなく「scope 全体」 に slip させた。 詳細 RCA + cold-eyes 設計史
#   は layer 3 (個人層) の plan に分離 (= 実 incident の固有名・往来内容は
#   public 出さない、 mechanism のみ layer 1)。
#
# Why nudge (not ask/deny):
#   search 自体は read-only で副作用なし、 block すると normal な探索 flow を
#   壊す。 必要なのは「結果を universal claim に slip させない」 reflex の起動
#   なので、 informational reminder で sufficient。 さらに以下の 2 mechanism:
#   (1) fill-in template ("verified scope = ___, NOT verified = ___") を
#       提供して空欄を埋めさせる (= 単なる「気をつけて」 より強い anchoring)
#   (2) ペア hook (mcp-search-zero-result-nudge.sh、 PostToolUse) が
#       0 件結果時に強い reminder を再 inject する (= decision point の直前)
#
# 二次 trap (= 起票者の author confession、 cold-eyes も自覚):
#   reminder は「読み飛ばす Claude」 の前で必ずしも機能しない。 本 hook 単独で
#   trap 完全防止と claim しない。 補完: ① C (= SessionStart enumeration、
#   起動時 anchor) + ② B (= 0-result 時の強 reminder) + ③ user 側 wire 拡張
#   (= Cowork connector に personal Gmail 追加) で多層防御。
#
# 出力経路 (= warn mode、 hook-authoring.md §3 に従う):
#   stdout = `hookSpecificOutput.additionalContext` + `systemMessage` (= 2 経路
#     defensive 併用、 spec 確度が build 依存のため)
#   stderr = narrative log (= ask/deny 時の確実経路、 allow 時は best-effort)
#   permissionDecision は出さない (= 通常 permission flow を維持)
#
# 安全: 全 path で fail-open (= tool call を絶対に止めない)、 exit 0 統一。
#
# テスト用 env:
#   MCP_SCOPE_REMINDER_FORCE=1  matcher で絞られていない呼び出しでも発火させる
#                               (= retroactive selftest 用)

set -uo pipefail

# 入力 = PreToolUse の stdin JSON (= {tool_name, tool_input, ...})。 空でも OK。
INPUT="$(cat 2>/dev/null || true)"

# tool_name の抽出 (jq が無い環境への fail-open: grep で代替)
if command -v jq >/dev/null 2>&1; then
  TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)"
else
  TOOL_NAME="$(printf '%s' "$INPUT" | grep -oE '"tool_name"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
fi

# matcher で既に絞られているはずだが、 defensive に再 check (= settings.json 側
# 配線ミスや FORCE bypass 時の保護、 全く無関係な tool call で発火しない)
if [ "${MCP_SCOPE_REMINDER_FORCE:-0}" != "1" ]; then
  case "$TOOL_NAME" in
    mcp__*__search_threads | mcp__*__search_emails | mcp__*__list_messages | \
    mcp__*__list_threads  | mcp__*__search_threads_by | mcp__*__list_events) : ;;
    *) exit 0 ;;
  esac
fi

# domain 判定 (= reminder text 内の例示を絞るため、 全 case で同じ template)
DOMAIN="unknown"
case "$TOOL_NAME" in
  *gmail* | *__search_threads | *__search_emails | *__list_messages | *__list_threads | *__search_threads_by)
    DOMAIN="Gmail" ;;
  *calendar* | *__list_events)
    DOMAIN="Calendar" ;;
esac

# 既知 Gmail account 列挙 (= filesystem 由来、 session-active subset とは別)。
# foreign user は ~/.gmail-mcp/ 不在 → 空文字、 reminder text は generic に縮む。
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

# reminder 本文 (= 単純な「気をつけて」 ではなく、 fill-in template を提示して
# 空欄を埋めさせることで anchoring を強める。 = 起票者 author confession の
# 二次 trap 緩和、 plan §「ある可能性」)
REMINDER="⚠️ MCP search tool 呼び出し (= scope universalization trap zone)

tool: $TOOL_NAME"

if [ -n "$KNOWN_ACCOUNTS" ] && [ "$DOMAIN" = "Gmail" ]; then
  REMINDER="$REMINDER
known Gmail accounts on this machine: $KNOWN_ACCOUNTS
⚠️ session-active subset may be SMALLER (= Cowork desktop session の --allowedTools 制限、
   詳細: claude-config/conventions/mcp.md §「desktop Cowork session の --allowedTools 制限」)。"
fi

REMINDER="$REMINDER

null / 0 件結果は「scope 全体に無い」 ではなく「私の sight に入った範囲に無い」 を意味する。

universal claim (= 「$DOMAIN で 0 件」 「全 sweep 完了」 「該当無し」 「確定」 「verify 完了」)
を書く前に、 次の fill-in template で scope を明示する:

  ┌─────────────────────────────────────────────┐
  │ Verified scope = _____________________      │
  │ NOT verified  = _____________________      │
  │ (該当 0 件 / hit N 件)                     │
  └─────────────────────────────────────────────┘

scope を埋められないなら、 結論を保留して以下のいずれかを実施:
  1. ToolSearch で「mcp__」 接頭の全 tool を確認 → wire 済 account を enumerate
  2. 残り account 経路 (= Python 直叩き wrapper) を回す (gmail-mcp-config/scripts/account-direct.py)
  3. user に「以下の account のみ verify 済、 残りは未 verify」 と honest に framing

設計動機: 2026-06-20 layer-3 RCA (= 単一 Gmail account のみ wired で「Gmail 0 件」 と
  universalize、 user 複数回 push でようやく別 account に到達 → 該当 thread 発見)。
  詳細: 個人層 plan (~/Claude/odakin-prefs/plans/2026-06-20-mcp-scope-guard-hooks.md)"

# ---------- surface file (= desktop Cowork session の SessionStart 読込 path) ----------
# hook-authoring.md §9.3: desktop frontend は PreToolUse 出力をモデルに honor しない
# が file 副作用は走る。 surface 経由で次 session に持ち越し可能。
SURFACE_DIR="$HOME/.claude/surface"
mkdir -p "$SURFACE_DIR" 2>/dev/null || true
{ printf '# 🔌 MCP search scope reminder (= 直近の search tool 呼び出し、 universal claim 前に scope 確認)\n\n'
  printf '%s\n' "$REMINDER"; } > "$SURFACE_DIR/mcp-search-reminder.txt" 2>/dev/null || true

# ---------- stderr (= narrative log、 ask/deny 時の確実経路 / allow 時 best-effort) ----------
printf '%s\n' "$REMINDER" >&2

# ---------- stdout (= JSON、 hookSpecificOutput.additionalContext + systemMessage の
#                       2 経路 defensive、 hook-authoring §3 warn-mode 仕様) ----------
# permissionDecision は出さない (= 通常 permission flow を維持、 read-only tool に
# 不必要な block / ask を入れない)
if command -v jq >/dev/null 2>&1; then
  jq -n --arg msg "$REMINDER" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "additionalContext": $msg
    },
    "systemMessage": $msg
  }'
else
  # jq 不在環境への fail-open: 最低限の JSON を手書き (= surface file は既に書込済)
  esc="$(printf '%s' "$REMINDER" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "[mcp-search-scope-reminder] $TOOL_NAME")"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":%s},"systemMessage":%s}\n' "$esc" "$esc"
fi

exit 0
