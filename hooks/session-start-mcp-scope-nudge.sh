#!/usr/bin/env bash
# session-start-mcp-scope-nudge.sh — SessionStart hook (layer 1)
#
# 正本: ~/Claude/claude-config/hooks/session-start-mcp-scope-nudge.sh
# 配信: claude-config/setup.sh install_hooks (= ~/.claude/hooks/ に symlink +
#       settings.json の SessionStart に登録、 matcher なし)
#
# 動作 (= 非 block、 -nudge):
#   session 開始時に「machine 上に register 済 MCP account / connector の
#   list」 + 「session-active subset は別物の可能性、 universal claim 前に
#   verify する規律」 を inject する。 該当 register が 0 なら silent。
#   (2026-06-20 追加) §4b で write/send capability の anchor も inject =
#   「Cowork connector は send_email を出さない、 send は standalone alias /
#   account-direct.py」 = read scope の null trap とは別軸の write-tool 不在 trap。
#
#   foreign user (= ~/.gmail-mcp / desktop config 不在) では generic な
#   meta-reminder 1 文だけ inject (= 「MCP 経由検索の null は scope unknown
#   を universalize しない」)、 何も無ければ silent。
#
# 出力経路:
#   stdout = additionalContext JSON (= CLI session に inject)
#   副作用 = $HOME/.claude/surface/mcp-scope.txt に同 reminder を書出し
#           (= desktop Cowork session は SessionStart 注入が dropped されるが、
#            file 副作用は走る、 odakin-prefs/CLAUDE.md の surface 読込指示で
#            拾われる。 hook-authoring.md#frontend-dependent-cowork / lib-surface.sh と同 pattern)
#
# 設計動機 (= 2026-06-20 layer-3 RCA、 個人層 plan 参照):
#   起票 session は Cowork desktop frontend の `--allowedTools` 制限により
#   単一 Gmail account のみ wired、 残り account は session 内で見えなかった。
#   session 開始時にこの非対称性が明示されていれば、 0 件結果を「Gmail で
#   0 件」 と universalize する slip を予防できた可能性ある。 詳細 RCA + 設計:
#   ~/Claude/odakin-prefs/plans/2026-06-20-mcp-scope-guard-hooks.md (= 個人層、
#   実 incident の固有名・thread 内容は public layer 1 に出さない方針)
#   §4b write/send capability block の設計動機 = 2026-06-20 write-tool RCA: 上記 RCA の
#   姉妹 incident。 Cowork connector に send_email が無いのを「メール送信できない」 と
#   誤解しうる (= read scope の null universalization とは別軸の capability 不在 trap)。
#   詳細 = ~/Claude/odakin-prefs/plans/2026-06-20-write-tool-availability-defense.md
#
# Honest framing (= cold-eyes 設計判断):
#   本 hook は「filesystem に register 済の account 名」 を列挙するだけで、
#   「session-active 状態」 は判別しない (= hook process から確実に判別する
#   経路が無い、 SessionStart の stdin は wired tool list を expose しない)。
#   従って reminder は「以下が register 済、 session subset は別物の可能性、
#   ToolSearch で verify せよ (= deferred tool list で実 wire を確認、 gmail は
#   alias 名 = account)」 という stance を取る。 false confidence (= 「✅ personal
#   wired」 と書いて実は subset 外) を避ける。 ⚠️ get_profile という MCP tool は
#   現行 setup に存在しない (= 旧 built-in connector の名残、 mcp.md §共通「確認方法」)。
#
# Enumeration source:
#   (a) $HOME/.gmail-mcp/<account>/credentials.json 群 (= gongrzhe gmail-mcp 系)
#   (b) (検出のみ) Cowork desktop connector の存在 (= ~/Library/Application Support/
#       Claude/claude_desktop_config.json の mcpServers エントリ、 UUID 形式の
#       connector は wire scope が UI 任せで filesystem から不明、 honest に
#       「UUID connector は scope 不明」 と書く)
#
# 二次 trap:
#   reminder が読み飛ばされる可能性は起票者 author confession の通り。 本 hook
#   は session 冒頭の anchoring (= early framing) として効くので、 後続の
#   Hook A (PreToolUse) + Hook B (PostToolUse 0-件) と組合せて多層化する。
#
# 安全: 全 path で fail-open (= session 起動を絶対に止めない)。 該当無し silent。
#
# テスト用 env:
#   CLAUDE_MCP_SCOPE_FORCE=1     SessionStart event check を skip + 必ず出力

set -uo pipefail

# ---------- 0. SessionStart 以外は silent ----------
if [ "${CLAUDE_MCP_SCOPE_FORCE:-0}" != "1" ]; then
  raw="$(cat 2>/dev/null || true)"
  case "$raw" in
    *'"SessionStart"'*) : ;;
    *) exit 0 ;;
  esac
fi

# ---------- 1. 既知 Gmail account 列挙 (filesystem 由来) ----------
KNOWN_GMAIL=""
if [ -d "$HOME/.gmail-mcp" ]; then
  for d in "$HOME/.gmail-mcp"/*/; do
    [ -d "$d" ] || continue
    base="$(basename "$d")"
    case "$base" in accounts|server|node_modules) continue ;; esac
    if [ -f "$d/credentials.json" ]; then
      KNOWN_GMAIL="${KNOWN_GMAIL:+$KNOWN_GMAIL }$base"
    fi
  done
fi

# ---------- 2. desktop Cowork connector 検出 (= 名前で識別可能な範囲のみ) ----------
# UUID 形式の connector は wire scope が UI 任せで filesystem から不明。
# claude_desktop_config.json に mcpServers エントリがあれば server 名は拾える。
DESKTOP_CONNECTORS=""
DESKTOP_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
if [ -f "$DESKTOP_CFG" ] && command -v jq >/dev/null 2>&1; then
  DESKTOP_CONNECTORS="$(jq -r '.mcpServers // {} | keys[]?' "$DESKTOP_CFG" 2>/dev/null | tr '\n' ' ' | sed 's/ $//')"
fi

# ---------- 3. frontend 判定 (= Cowork desktop か否か、 hook-authoring §9.3) ----------
FRONTEND="${CLAUDE_CODE_ENTRYPOINT:-unknown}"
IS_DESKTOP=0
case "$FRONTEND" in
  claude-desktop) IS_DESKTOP=1 ;;
esac

# ---------- 4. reminder 本文構築 ----------
# 該当 register が完全に 0 件 (= foreign user 等) なら silent exit
if [ -z "$KNOWN_GMAIL" ] && [ -z "$DESKTOP_CONNECTORS" ]; then
  exit 0
fi

REMINDER="🔌 MCP scope reminder (= universal claim 前に確認、 2026-06-20 layer-3 RCA hard 防御)
"

if [ -n "$KNOWN_GMAIL" ]; then
  REMINDER="${REMINDER}
machine 上 register 済 Gmail account (= ~/.gmail-mcp/): $KNOWN_GMAIL"
fi

if [ -n "$DESKTOP_CONNECTORS" ]; then
  REMINDER="${REMINDER}
desktop config の MCP servers: $DESKTOP_CONNECTORS"
fi

REMINDER="${REMINDER}

⚠️ register 済 ≠ session-active。 当 session で実際 wire されている tool subset は
   ToolSearch の deferred tools list / mcp__* で始まる tool が見えるかで verify する
   (= Cowork desktop session の --allowedTools は subset に絞る、 詳細
   claude-config/conventions/mcp.md#desktop-allowedtools-restriction)。

universal claim を書く前の必須 anchoring (= 起票 RCA で破綻した 4 軸 sweep の修復):

  ❌ 禁止: 「Gmail で 0 件」 「Gmail に該当なし」 「Mail 全 sweep 0 件」 等の
            scope unspecified な absence claim
  ✅ 必須 fill-in template (= Hook A / B と整合、 universal claim 前に空欄を埋めて framing):

       Verified scope = ____ (= 実際に check 済の account / 範囲を列挙)
       NOT verified  = ____ (= まだ check できていない account / 範囲を列挙)
       Result        = N 件 in [Verified scope]

0 件結果に対する 4 経路:
  1. session で見える MCP search tool を ToolSearch で enumerate
  2. 見えない account は ~/Claude/gmail-mcp-config/scripts/account-direct.py で Python 直叩き
  3. それでも null なら user に「以下のみ verify、 残り <list> は未 verify」 と honest framing
  4. Cowork desktop session なら user 操作で connector 追加を依頼 (= user 経路)"

# ---------- 4b. write/send capability (= read scope と別軸、 2026-06-20 write-tool RCA) ----------
# tool 名に send verb が「無い」 のは capability 不在の guarantee ではない: 別 connector type が
# 同 account で send を出す。 Cowork connector の capability は filesystem から推定不可だが、
# name PATTERN (= UUID vs alias) で capability TYPE は確実に判別できる (= blocker (3) の非対称性)。
if [ -n "$KNOWN_GMAIL" ]; then
  SEND_ROUTE="standalone mcp__gmail-<alias>__send_email (= register 済 alias: $KNOWN_GMAIL)"
else
  SEND_ROUTE="この machine に standalone alias は未 register (= account-direct.py か user に依頼)"
fi
REMINDER="${REMINDER}

✉️ write/send capability (= read と別軸、 universal claim template とは別の trap):
   tool 名に send/delete/modify verb が「無い」 のは「操作不能」 ではなく「この connector が
   出さない」 だけ。 ❌「Cowork に send_email が無い → メール送信できない」 と即断するな。
   - Cowork hosted connector (mcp__<UUID>__*) = read (search_threads/get_thread) +
     draft 作成 (create_draft) + label 操作のみ。 send_email / delete_email / modify_email は
     expose しない (= 「read-only」 ではなく「send 不可」 が正確 — draft/label は書ける)。
   - send/delete/modify は: $SEND_ROUTE
     ✅ 「送れない」 と結論する前に ToolSearch で mcp__gmail-<alias>__send_email の wire を確認。"

if [ "$IS_DESKTOP" = 1 ]; then
  REMINDER="${REMINDER}

⚠️ CLAUDE_CODE_ENTRYPOINT=claude-desktop 検出 — 本 session は Cowork desktop。
   --allowedTools 制限により $HOME/.gmail-mcp/* の subset しか wire されない可能性高い。
   ToolSearch で mcp__gmail-<alias> を query し、 実際に wire された alias を確認せよ
   (= alias 名 = account、 get_profile という MCP tool は無い)。"
fi

REMINDER="${REMINDER}

全文 RCA + 設計: ~/Claude/odakin-prefs/plans/2026-06-20-mcp-scope-guard-hooks.md"

# ---------- 5. surface file (= desktop fallback、 hook-authoring §9.3) ----------
SURFACE_DIR="$HOME/.claude/surface"
mkdir -p "$SURFACE_DIR" 2>/dev/null || true
{ printf '%s\n' "$REMINDER"; } > "$SURFACE_DIR/mcp-scope.txt" 2>/dev/null || true

# ---------- 6. stdout (= system-reminder で session 冒頭 inject、 CLI path) ----------
printf '<system-reminder>\n'
printf '%s\n' "$REMINDER"
printf '</system-reminder>\n'

exit 0
