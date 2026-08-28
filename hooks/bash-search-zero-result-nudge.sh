#!/usr/bin/env bash
# bash-search-zero-result-nudge.sh — PostToolUse(Bash): ローカル discovery 検索の null (tree 検索空振り / glob 不成立) + truncate-before-grep pipeline を検出し「部分 scope の null で不在断定するな」 の scope 宣言 template を inject
#
# 正本: <claude-config>/hooks/bash-search-zero-result-nudge.sh
# 配信: setup.sh install_hooks (= ~/.claude/hooks/ に symlink + settings.json の
#       PostToolUse に登録、 matcher = Bash)
#
# 動作 (= 非 block、 -nudge):
#   sibling = mcp-search-zero-result-nudge.sh (外部 MCP search の 0 件) の
#   **ローカル版**。 外部 search null には nudge があるのに、 手元の grep/find の
#   null には無い非対称 (= 「1 repo だけ grep して『存在しない』」 「help 出力を
#   途中まで読んで『flag 無し』」 が素通り) を埋める。 decision-point 直前
#   (= 「null だったから X は無い」 と次 token で書く瞬間) の anchoring。
#
# detector:
#   A (tree-search null): 再帰 / tree 検索 (= grep -r/-R/--recursive、 git grep、
#     find <dir> -name/-iname/-path/-regex) の出力が完全空、 または zsh glob
#     不成立 ("no matches found")。 tree 検索は discovery-shaped = null を
#     universal absence に変換する誘惑が強い。
#   B (truncate-before-grep): pipeline で head / tail / sed -n (= 窓切り詰め) が
#     grep 系より **前** の segment にある = grep は切り詰めた窓の上しか見ていない。
#     正常 idiom は grep→head の順なので、 逆順は構造自体が signal (hit 有無に
#     関わらず fire)。 `tail -f` は stream 監視 idiom ゆえ除外。
#
# FP 設計 (= conservative、 miss を許容して FP を避ける — sibling と同哲学):
#   - 単一 file への grep / pipe 入力の grep は対象外 (= leak check の
#     「0 hit = clean」 は bounded 検証で正当、 鳴らさない)
#   - 出力が 1 byte でもあれば A は沈黙 (= `|| echo` fallback 付きも沈黙 = miss 側)
#   - rate limit (default 180s、 state = ~/.claude/state/bash-search-nudge/)
#   - 既知の miss (= 射程外、 意図的): 単一 path の存在 probe (ls -d X / test -e)、
#     Read tool の offset/limit 部分読み、 `grep -c` の "0" 出力、 rg (未使用)。
#     単一 path probe は discovery か bounded 検証かが機械判別不能 = claim 時の
#     scope 宣言規律 (個人層 CLAUDE.md inline §3) が floor。
#
# 設計動機 (2026-08-24 同一 session 2 連発、 個人層 RCA):
#   ① 別 repo に実在する doc を 1 repo 相当の検索 null で「存在しない stale」 と
#      誤報告 (= sweep の finding 報告そのものが部分 scope null だった)
#   ② CLI --help 227 行を先頭 ~200 行 + 切り詰め窓 grep で読み「該当 flag 無し」 を
#      公開 issue コメントに記載 (= 結論は偶然正しかったが導出が不健全)
#   詳細 = odakin-prefs/plans/2026-08-24-chat-to-code-bridge.md §4 (= 個人層)
#
# 出力経路: stdout JSON additionalContext + systemMessage + surface file
#   (sibling と同 pattern。 desktop は model 向け出力を捨てる 〔hook-authoring.md
#   #frontend-dependent-cowork〕 ため surface file が fallback)
# 安全: 全 path で fail-open。
#
# テスト env:
#   BASH_SEARCH_NUDGE_FORCE=1       matcher / 検出 / rate-limit を bypass して必ず発火
#   BASH_SEARCH_NUDGE_STATE_DIR     state dir override (test 隔離用)
#   BASH_SEARCH_NUDGE_WINDOW        rate-limit 秒数 override (0 = 無効化)

set -uo pipefail

INPUT="$(cat 2>/dev/null || true)"
[ -z "$INPUT" ] && exit 0

FORCE="${BASH_SEARCH_NUDGE_FORCE:-0}"

if command -v jq >/dev/null 2>&1; then
  TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)"
  COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
  RESPONSE="$(printf '%s' "$INPUT" | jq -r '
    (.tool_response // .tool_result // "") |
    if type == "object" then ((.stdout // "") + "\n" + (.stderr // ""))
    else tostring end' 2>/dev/null || true)"
else
  # jq 無し環境: command 抽出は quoting で壊れるので detector B は skip、
  # A は response 側 signal (glob null) のみ (= fail-open 縮退)
  TOOL_NAME="$(printf '%s' "$INPUT" | grep -oE '"tool_name"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
  COMMAND=""
  RESPONSE="$INPUT"
fi

# matcher 防御的再 check
if [ "$FORCE" != "1" ]; then
  [ "$TOOL_NAME" = "Bash" ] || exit 0
fi

FIRED=""
DETECTOR_DESC=""

# ---------- detector B: truncate-before-grep ----------
# naive '|' split (quoted '|' の誤 split は truncator/grep 語 match に達しないので実害無し)
if [ -n "$COMMAND" ]; then
  B_HIT="$(printf '%s' "$COMMAND" | awk '
    BEGIN { RS="|"; i = 0; trunc = -1; grepseg = -1 }
    {
      i++
      seg = $0
      if (trunc < 0) {
        if (seg ~ /(^|[[:space:];&(])head([[:space:]]|$)/) trunc = i
        else if (seg ~ /(^|[[:space:];&(])tail([[:space:]]|$)/ && seg !~ /tail[[:space:]]+-[a-zA-Z]*f/) trunc = i
        else if (seg ~ /(^|[[:space:];&(])sed[[:space:]]+-n([[:space:]]|$)/) trunc = i
      }
      if (grepseg < 0 && seg ~ /(^|[[:space:];&(])(grep|egrep|fgrep)([[:space:]]|$)/) grepseg = i
    }
    END { if (trunc > 0 && grepseg > 0 && trunc < grepseg) print "yes" }' 2>/dev/null || true)"
  if [ "$B_HIT" = "yes" ]; then
    FIRED="B"
    DETECTOR_DESC="truncate-before-grep (= head/tail/sed -n が grep より前 → grep は切り詰めた窓しか見ていない)"
  fi
fi

# ---------- detector A: tree-search null / glob 不成立 ----------
if [ -z "$FIRED" ]; then
  A_STRUCT=0
  if [ -n "$COMMAND" ]; then
    # (a) grep 系の再帰 flag (= grep 語直後から flag token 列を walk して r/R 入り token を探す。
    #     pattern 引数中の "-r" 文字列や別 command の -rf との誤結合を防ぐため、
    #     dash-flag token の連なりの中だけを見る)
    if printf '%s' "$COMMAND" | grep -qE '(^|[[:space:];&|(])(grep|egrep|fgrep)[[:space:]]+((-[a-zA-Z]+|--[a-z-]+)[[:space:]]+)*(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)([[:space:]]|$)'; then
      A_STRUCT=1
    # (b) git grep (= repo tree 検索)
    elif printf '%s' "$COMMAND" | grep -qE '(^|[[:space:];&|(])git[[:space:]]+grep[[:space:]]'; then
      A_STRUCT=1
    # (c) find + 検索述語
    elif printf '%s' "$COMMAND" | grep -qE '(^|[[:space:];&|(])find[[:space:]][^|]*-(iname|name|path|regex)[[:space:]]'; then
      A_STRUCT=1
    fi
  fi
  GLOB_NULL=0
  if printf '%s' "$RESPONSE" | grep -q 'no matches found'; then
    GLOB_NULL=1
  fi
  if [ "$GLOB_NULL" = 1 ]; then
    FIRED="A"
    DETECTOR_DESC="glob 不成立 (= 'no matches found'、 pattern discovery の null)"
  elif [ "$A_STRUCT" = 1 ]; then
    trimmed="$(printf '%s' "$RESPONSE" | tr -d '[:space:]')"
    if [ -z "$trimmed" ]; then
      FIRED="A"
      DETECTOR_DESC="tree 検索空振り (= grep -r / git grep / find の出力が完全空)"
    fi
  fi
fi

# FORCE: 検出に関わらず fire (= test 用)
if [ "$FORCE" = "1" ] && [ -z "$FIRED" ]; then
  FIRED="A"
  DETECTOR_DESC="(forced)"
fi

[ -z "$FIRED" ] && exit 0

# ---------- rate limit (= FP 許容度の主対策、 FORCE は bypass + stamp 汚染なし) ----------
STATE_DIR="${BASH_SEARCH_NUDGE_STATE_DIR:-$HOME/.claude/state/bash-search-nudge}"
WINDOW="${BASH_SEARCH_NUDGE_WINDOW:-180}"
if [ "$FORCE" != "1" ]; then
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  STAMP="$STATE_DIR/last-fire"
  now="$(date +%s 2>/dev/null || echo 0)"
  if [ -f "$STAMP" ] && [ "$WINDOW" -gt 0 ] 2>/dev/null; then
    last="$(cat "$STAMP" 2>/dev/null || echo 0)"
    case "$last" in (*[!0-9]*) last=0 ;; esac
    if [ $(( now - last )) -lt "$WINDOW" ]; then
      exit 0
    fi
  fi
  printf '%s' "$now" > "$STAMP" 2>/dev/null || true
fi

# command 表示 (= 多バイト安全な文字単位 truncate、 shell-multibyte-truncation.md)
CMD_SHOW="$(printf '%s' "$COMMAND" | python3 -c 'import sys; s = sys.stdin.read().replace("\n", " "); print(s[:200] + ("…" if len(s) > 200 else ""))' 2>/dev/null || printf '%s' "$COMMAND" | head -1)"

REMINDER="🛑 ローカル検索 null — 部分 scope で不在断定しない zone

detector: $FIRED = $DETECTOR_DESC
command: $CMD_SHOW

⚠️ 次の token で禁止する claim (= scope 未宣言のまま):
  ❌ 「存在しない / 無い / 見つからなかった」 で確定
  ❌ 「〜という flag / file / 設定は無い」 (= 窓の外・他 repo/dir 未確認のまま)

✅ 断定するなら 1 行で scope を埋める:
  見た scope = ____ / NOT = ____ / null in [見た scope]

広げる例 (= 正しい行動の限界費用をゼロに):
  ・同じ検索を 1 つ上の階層 or sibling repo 群で再実行 (grep -r / find <上位 dir>)
  ・切り詰め (head / sed -n) を外して全長で再実行、 または | wc -l で全長を先に確認

設計動機: 2026-08-24 同一 session 2 連発 (= 1 repo の検索 null で「doc 不在」 誤断定
  〔実体は sibling repo に実在〕 / --help を途中窓で grep して「flag 無し」 を公開 issue に
  投稿)。 単一 path の存在 probe と Read 部分読みは本 hook の射程外 = claim 時の
  scope 宣言が floor。 詳細 = odakin-prefs/plans/2026-08-24-chat-to-code-bridge.md §4"

# ---------- surface file (= desktop fallback) ----------
SURFACE_DIR="$HOME/.claude/surface"
mkdir -p "$SURFACE_DIR" 2>/dev/null || true
{ printf '# 🛑 ローカル検索 null (= 直前の Bash 検索、 universal claim 禁止)\n\n'
  printf '%s\n' "$REMINDER"; } > "$SURFACE_DIR/bash-search-zero.txt" 2>/dev/null || true

printf '%s\n' "$REMINDER" >&2

# stdout JSON (= additionalContext + systemMessage の 2 経路併用、 sibling と同 spec 対応)
if command -v jq >/dev/null 2>&1; then
  jq -n --arg msg "$REMINDER" '{
    "hookSpecificOutput": {
      "hookEventName": "PostToolUse",
      "additionalContext": $msg
    },
    "systemMessage": $msg
  }'
else
  esc="$(printf '%s' "$REMINDER" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "[bash-search-zero] local search returned null")"
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s},"systemMessage":%s}\n' "$esc" "$esc"
fi

exit 0
