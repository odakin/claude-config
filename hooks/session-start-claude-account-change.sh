#!/usr/bin/env bash
# session-start-claude-account-change.sh — SessionStart hook (layer 1, claude-config)
#
# 正本: claude-config/hooks/session-start-claude-account-change.sh
# install: claude-config/setup.sh が ~/.claude/hooks/ に symlink +
#          ~/.claude/settings.json の SessionStart entries にマージ
#
# 目的:
#   ~/.claude.json の userID を machine-local stash (~/.claude/last-claude-userid)
#   と比較し、 変化を検知したら user に「Claude account 切替が発生した」 と告げ
#   reconcile 手順 (= scheduled task 再登録 + self-hosted MCP 健全性確認) を surface。
#
# Why this exists (= 2026-06-26 odafgpt 移行 RCA):
#   Claude account を切り替えると ① user-OAuth したアプリ内蔵 connector ② scheduled task
#   ③ 揮発 session 状態 が消える。 ②③ は機械検知できないので、 ① を「self-hosted MCP に
#   migrate 済」 という前提のもと、 切替自体を検知して ② の reregister を促す surface。
#
# 設計上の安全:
#   - fail-open: 全 error path で silent exit 0
#   - 該当なし (= userID 不変) なら完全沈黙
#   - 1 回 surface した後 stash を current に進めて静かに (= 同 switch で何度も surface しない)
#     → user が実際に reconcile したかは別問題。 未実行なら scheduled task 不発火等で別経路で surface
#
# Layer-1 (claude-config, public) の design contract:
#   - 本 hook は odakin-specific path / repo 名を hardcode しない。
#   - 個人層 (= layer 3) の reconcile 拡張は <personal-layer>/account-change-extra.md
#     を optional に拾って surface に append (= foreign user は extension 無くても動く)。
#   - foreign user (= claude-config のみ利用) でも generic reconcile 手順は表示される。
#
# 復元・テスト用 env override:
#   CLAUDE_ACCT_CHANGE_FORCE         1 なら SessionStart event check を skip + force surface
#   CLAUDE_ACCT_CHANGE_CLAUDE_JSON   ~/.claude.json の代替 path (test 用)
#   CLAUDE_ACCT_CHANGE_STASH         last-claude-userid stash の代替 path (test 用)
#   CLAUDE_ACCT_CHANGE_EXTRA_FILE    extension file の代替 path (test 用、 personal-layer 検出 bypass)
#   CLAUDE_ACCT_CHANGE_NO_STASH      1 なら stash 更新を skip (test 用)
#   CLAUDE_PERSONAL_LAYER            個人層 dir を明示指定 (or 'none' で検出無効化、 find-personal-layer.sh 経由)

set -uo pipefail  # -e は使わない (fail-open 契約と両立しないため、 hook-authoring.md#shebang-set-policy)

CLAUDE_JSON="${CLAUDE_ACCT_CHANGE_CLAUDE_JSON:-$HOME/.claude.json}"
STASH="${CLAUDE_ACCT_CHANGE_STASH:-$HOME/.claude/last-claude-userid}"

# ---------- 0. SessionStart 以外は silent ----------
if [ "${CLAUDE_ACCT_CHANGE_FORCE:-0}" != "1" ]; then
  raw="$(cat 2>/dev/null || true)"
  case "$raw" in
    *'"SessionStart"'*) : ;;
    *) exit 0 ;;
  esac
fi

[ -f "$CLAUDE_JSON" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

current_uid="$(CLAUDE_JSON="$CLAUDE_JSON" python3 -c '
import json, os, sys
try:
    d = json.load(open(os.environ["CLAUDE_JSON"]))
    uid = d.get("userID", "")
    print(uid if uid else "")
except Exception:
    sys.exit(0)
' 2>/dev/null || true)"

[ -z "$current_uid" ] && exit 0

# Read stash (= last seen userID). If absent, treat as "first time".
prev_uid=""
if [ -f "$STASH" ]; then
  prev_uid="$(cat "$STASH" 2>/dev/null | tr -d '[:space:]' || true)"
fi

# No change → silent
if [ "$current_uid" = "$prev_uid" ]; then
  exit 0
fi

# ---------- Compose surface ----------
short_cur="${current_uid:0:12}…"
short_prev=""
if [ -n "$prev_uid" ]; then short_prev="${prev_uid:0:12}…"; fi

if [ -z "$prev_uid" ]; then
  banner="初回検知: Claude account = $short_cur"
  intro="このマシン初回起動 (= stash 不在)。 現在の Claude account の userID を記録し、 今後切替が起きたら自動 surface します。"
else
  banner="🔀 Claude account 切替検知: $short_prev → $short_cur"
  intro="Claude account が切り替わりました。 切替で消える状態の reconcile が必要です。"
fi

generic_reconcile=$(cat <<'GENERIC'
切替で消えるもの (= 一般 Claude account 切替セマンティクス):
  ① user-OAuth したアプリ内蔵 connector (= UUID 形式 MCP) → 新 account 下で消える
     対策: 必要なら Claude Code desktop app の設定 UI で再認証、 もしくは self-hosted stdio MCP に migrate
  ② scheduled task (= 切替先 Claude account の registry には未登録 = 宙吊り)
     対策: 既存の routine 一覧を別経路 (= 個人層 helper or 手書き) で吸い出して
     `create_scheduled_task` で再登録
  ③ 揮発 session 状態 (= spawn_task 親子・chip 状態は消える)
     対策: 切替前に spec を file-handoff 形式で push してから switch

self-hosted stdio MCP は ~/.claude.json project scope ゆえ切替で残る:
  確認: claude mcp list
GENERIC
)

# ---------- 個人層 extension を optional 取り込み ----------
extra=""
extra_file="${CLAUDE_ACCT_CHANGE_EXTRA_FILE:-}"
if [ -z "$extra_file" ]; then
  # find-personal-layer.sh を source して layer 検出 (= 各 user の hook 拡張ファイルを探す)
  fpl_lib="$(dirname "${BASH_SOURCE[0]:-$0}")/../scripts/lib/find-personal-layer.sh"
  if [ -f "$fpl_lib" ]; then
    # shellcheck source=/dev/null
    . "$fpl_lib"
    if command -v find_personal_layer >/dev/null 2>&1; then
      layer="$(find_personal_layer)"
      if [ -n "$layer" ] && [ -f "$layer/account-change-extra.md" ]; then
        extra_file="$layer/account-change-extra.md"
      fi
    fi
  fi
fi
if [ -n "$extra_file" ] && [ -f "$extra_file" ]; then
  extra="$(cat "$extra_file" 2>/dev/null || true)"
fi

out="$banner

$intro

$generic_reconcile"

if [ -n "$extra" ]; then
  out="$out

個人層 (= $(basename "$(dirname "$extra_file")")) 固有の reconcile 拡張:
$extra"
fi

out="$out

stash 更新済 → 同 switch では 2 回目以降 surface しません。"

# ---------- desktop surface bridge (= inline、 layer 1 は layer 3 lib に依存しない) ----------
SURF_DIR="$HOME/.claude/surface"
mkdir -p "$SURF_DIR" 2>/dev/null || true
{ printf '# 🔀 Claude account 切替検知\n\n'; printf '%s\n' "$out"; } > "$SURF_DIR/claude-account-change.txt" 2>/dev/null || true

# ---------- Update stash (= 同 switch で 2 回目以降は silent) ----------
if [ "${CLAUDE_ACCT_CHANGE_NO_STASH:-0}" != "1" ]; then
  mkdir -p "$(dirname "$STASH")" 2>/dev/null || true
  printf '%s\n' "$current_uid" > "$STASH" 2>/dev/null || true
fi

# ---------- CLI output ----------
printf '<system-reminder>\n'
printf '%s\n' "$out"
printf '</system-reminder>\n'
exit 0
