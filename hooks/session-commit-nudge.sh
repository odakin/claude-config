#!/usr/bin/env bash
# session-commit-nudge.sh
#
# 同 session 内で Edit/Write した repo が turn 終了時に WT dirty (= 未 commit)
# のまま残っているのを Stop hook で nudge する。 並行 session 干渉 (= 別
# session が WT を「拾って」 commit + push してしまい semantic drift を生む)
# を予防、 自 session の commit discipline を強化。
#
# Why this exists (= 2026-05-26 RCA):
#
#   2026-05-26 私 (Claude) session が NHWG43 一連の作業で:
#     - 3 mail 送信、 ~10 file 編集 across 3 repos (email-office /
#       research-collab / 研究 LaTeX project) を 1 session で実施
#     - **commit を 1 回も打たなかった**。 user の「送って記録」 指示で
#       「記録 = yaml file 編集」 と等式化、 commit + push まで拡張せず
#     - user の別 session が WT dirty を発見 → 親切に commit + push
#       (= 16:09 / 16:10 commit) → 私 session memory は「未 commit」 のまま
#     - file content 経由の間接 commit (= 別 session が yaml log を読み
#       commit message に転写) で意味的には integral だが、 author intent
#       検証なしで commit + push される脆弱性が露呈
#
#   既存 git-state-nudge.sh は DIRTY_COUNT > 0 単独を nudge 対象外にして
#   ある (= 2026-04-08 noise 削減判断、 STALE_DIRT = 24h 同 porcelain hash
#   不変 でのみ fire)。 結果として「fresh session 内で蓄積した未 commit」
#   は どの既存 hook にも引っ掛からなかった。
#
#   本 hook が埋める gap = 「same session 内で M ファイル累積、 active
#   editing なので STALE 化せず、 各 file は git-state-nudge.sh 経路に乗ら
#   ない」 case を Stop boundary で expose。
#
# Naming convention (= conventions/hook-authoring.md#naming-convention):
#   `-nudge` suffix = non-blocking、 stdout に injection、 exit 0 (= 規約通り)
#
# Modes (起動引数で dispatch):
#   track   (PostToolUse Edit/Write/MultiEdit):
#     - stdin JSON から session_id + tool_input.file_path 抽出
#     - file_path から repo root 解決 (= git rev-parse --show-toplevel)
#     - $STATE_DIR/<session_id>.list に repo path append (= dedup)
#     - silent (exit 0、 stdout 出力なし)
#     - Bash から呼ぶ道具が書いた file の repo は、 道具の側が scripts/lib/session_touch.py の register() で同じ list に足す (本 hook は Edit / Write / MultiEdit しか見ない = conventions/multi-session-coordination.md#script-writes-count-as-touch)
#
#   nudge   (Stop):
#     - stdin JSON から session_id 抽出
#     - $STATE_DIR/<session_id>.list を読み、 各 repo に git status --porcelain
#     - DIRTY > 0 の repo を集計、 1 件以上で stdout に nudge text injection
#     - 層1 の repo (claude-config・ai-collaboration) を push できない人の clone では、 「commit + push」 の
#       代わりに「PR にする」 を出す (engine = 本 repo の scripts/upstream-pr.py の status --brief。 dirty だけで
#       なく upstream より先の commit も拾う = push を断られて手元に残った commit)。 engine が黙る
#       (所有者・変更なし) repo は従来どおり dirty の行に回る。 python3 / engine が無ければ従来どおり
#     - 状態 hash で同 dirty set への重複 nudge を suppress (= 同 turn 内
#       で複数 Stop が連続発火しても rep noise を出さない)
#     - stop_hook_active=true なら exit 0 (= recursive loop 防止)
#
# State directory:
#   default: ~/.claude/state/session-touch/
#   override: SESSION_TOUCH_STATE_DIR env (= test 用 isolation)
#   file format:
#     <session_id>.list    — 1 行 1 repo root (dedup)
#     <session_id>.nudged  — 直近 nudge した dirty 状態の sha1 hash
#
# Silent on (= exit 0 + 何も出力なし):
#   - jq 不在 / stdin 空 / JSON malformed
#   - session_id 抽出失敗
#   - file_path が git repo 外 (= /tmp/foo 等)
#   - touch list 不在 (= 当該 session で edit 0 回)
#   - 触った全 repo が WT clean
#   - 同 dirty hash で前回 nudge 済
#
# Cleanup:
#   状態 file は session_id keyed、 自動削除なし。 蓄積は小さい (= 数百
#   bytes/session)。 cron-like cleanup は future work。
#
# Test isolation:
#   SESSION_TOUCH_STATE_DIR=/tmp/test-xyz/ を env で指定すると state dir 隔離。
#   UPSTREAM_PR_ENGINE=<path> で層1 の PR の engine を差し替える (空 = engine 無し)。
#   test script (= session-commit-nudge.test.sh) はこれを使う。
#
# bash 3.2 互換:
#   macOS stock /bin/bash で動作必須 (= conventions/hook-authoring.md#bash32-heredoc-parser-bug)。
#   $(...) + heredoc body の quote escape は本 hook では使わない (= 純 bash
#   logic のみ、 Python heredoc 等の interop なし)。

set -uo pipefail

# Self-dogfood verified 2026-05-26 (= session that authored this hook).
STATE_DIR="${SESSION_TOUCH_STATE_DIR:-$HOME/.claude/state/session-touch}"
mkdir -p "$STATE_DIR" 2>/dev/null || exit 0

MODE="${1:-}"
case "$MODE" in
  track|nudge) ;;
  *) exit 0 ;;  # unknown mode → silent
esac

# Read stdin JSON
STDIN_JSON=""
if command -v jq >/dev/null 2>&1 && [ ! -t 0 ]; then
  STDIN_JSON="$(cat 2>/dev/null || true)"
fi
[ -z "$STDIN_JSON" ] && exit 0

# Extract session_id (= claude code hook protocol field)
SESSION_ID="$(printf '%s' "$STDIN_JSON" | jq -r '.session_id // empty' 2>/dev/null || echo '')"
[ -z "$SESSION_ID" ] && exit 0

TOUCH_FILE="$STATE_DIR/$SESSION_ID.list"
NUDGED_FILE="$STATE_DIR/$SESSION_ID.nudged"

# ----------------------------------------------------------------------
# resolve_repo_root <path>: echo enclosing git repo root or empty
# ----------------------------------------------------------------------
resolve_repo_root() {
  local FPATH="$1"
  [ -z "$FPATH" ] && return 0
  local DIR
  if [ -d "$FPATH" ]; then
    DIR="$FPATH"
  else
    DIR="$(dirname "$FPATH" 2>/dev/null || echo '')"
  fi
  [ -z "$DIR" ] && return 0
  [ ! -d "$DIR" ] && return 0
  git -C "$DIR" rev-parse --show-toplevel 2>/dev/null || true
}

# ----------------------------------------------------------------------
# add_repo <repo_root>: append to touch list if not already present
# ----------------------------------------------------------------------
add_repo() {
  local REPO="$1"
  [ -z "$REPO" ] && return 0
  if [ -f "$TOUCH_FILE" ] && grep -qxF "$REPO" "$TOUCH_FILE" 2>/dev/null; then
    return 0  # already present
  fi
  echo "$REPO" >> "$TOUCH_FILE" 2>/dev/null || true
}

# ----------------------------------------------------------------------
# compute_sha1 <string>: echo sha1 hash or empty if no tool available
# ----------------------------------------------------------------------
compute_sha1() {
  local INPUT="$1"
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$INPUT" | shasum | cut -d' ' -f1
  elif command -v sha1sum >/dev/null 2>&1; then
    printf '%s' "$INPUT" | sha1sum | cut -d' ' -f1
  fi
}

# ----------------------------------------------------------------------
# upstream_pr_engine: 層1 の PR の engine (本 repo の scripts/upstream-pr.py) の path を ENGINE と
# ENGINE_REPO に置く (無ければ空)。 ~/.claude/hooks/ の symlink を辿って本 repo を特定する
# ----------------------------------------------------------------------
ENGINE=""
ENGINE_REPO=""
upstream_pr_engine() {
  local SELF LINK
  if [ "${UPSTREAM_PR_ENGINE+set}" = "set" ]; then
    [ -n "$UPSTREAM_PR_ENGINE" ] && [ -f "$UPSTREAM_PR_ENGINE" ] && ENGINE="$UPSTREAM_PR_ENGINE"
    return 0
  fi
  command -v python3 >/dev/null 2>&1 || return 0
  SELF="${BASH_SOURCE[0]}"
  while [ -L "$SELF" ]; do
    LINK="$(readlink "$SELF")"
    case "$LINK" in /*) SELF="$LINK" ;; *) SELF="$(dirname "$SELF")/$LINK" ;; esac
  done
  ENGINE_REPO="$(cd "$(dirname "$SELF")/.." 2>/dev/null && pwd -P)" || return 0
  [ -f "$ENGINE_REPO/scripts/upstream-pr.py" ] && ENGINE="$ENGINE_REPO/scripts/upstream-pr.py"
  return 0
}

# ----------------------------------------------------------------------
# layer1_candidate <repo_root>: engine の述語 (本 repo / base の repo の名が claude-config・ai-collaboration)
# の上位集合 = python を起こす前の絞り (conventions/hook-authoring.md#prefilter-superset-of-predicate)
# ----------------------------------------------------------------------
layer1_candidate() {
  local REPO="$1" URLS
  [ -n "$ENGINE_REPO" ] && [ "$REPO" = "$ENGINE_REPO" ] && return 0
  [ -n "$(git -C "$REPO" config --get upstream-pr.base 2>/dev/null)" ] && return 0
  URLS="$(git -C "$REPO" config --get-regexp '^remote\..*\.url$' 2>/dev/null || true)"
  case "$URLS" in *claude-config*|*ai-collaboration*) return 0 ;; esac
  return 1
}

case "$MODE" in
  track)
    # PostToolUse Edit/Write/MultiEdit → track repo
    FILE_PATH="$(printf '%s' "$STDIN_JSON" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo '')"
    [ -z "$FILE_PATH" ] && exit 0
    REPO_ROOT="$(resolve_repo_root "$FILE_PATH")"
    add_repo "$REPO_ROOT"
    exit 0
    ;;

  nudge)
    # Stop hook → check touched repos, nudge if any dirty
    # Prevent recursive loop (= Stop hook can re-trigger Stop in some configs)
    STOP_HOOK_ACTIVE="$(printf '%s' "$STDIN_JSON" | jq -r '.stop_hook_active // false' 2>/dev/null || echo 'false')"
    [ "$STOP_HOOK_ACTIVE" = "true" ] && exit 0

    [ ! -f "$TOUCH_FILE" ] && exit 0

    # Build nudge body, listing each dirty repo with file count.
    # 層1 の repo で push できない人の clone は L1_BODY (PR の勧め) に回し、 dirty の行には入れない
    upstream_pr_engine
    BODY=""
    L1_BODY=""
    while IFS= read -r REPO; do
      [ -z "$REPO" ] && continue
      [ ! -d "$REPO" ] && continue
      if [ -n "$ENGINE" ] && layer1_candidate "$REPO"; then
        L1_OUT="$(python3 "$ENGINE" status --brief --quiet-errors --timeout 8 --repo "$REPO" 2>/dev/null || true)"
        if [ -n "$L1_OUT" ]; then
          L1_BODY="${L1_BODY}${L1_OUT}
"
          continue
        fi
      fi
      DIRTY_COUNT="$(git -C "$REPO" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
      if [ "$DIRTY_COUNT" -gt 0 ]; then
        BODY="${BODY}  - ${REPO}: ${DIRTY_COUNT} file(s) dirty
"
      fi
    done < "$TOUCH_FILE"

    [ -z "$BODY" ] && [ -z "$L1_BODY" ] && exit 0  # all clean → silent

    # Dedup: same dirty-state hash since last nudge → silent
    STATE_HASH="$(compute_sha1 "$BODY$L1_BODY")"
    LAST_NUDGED=""
    [ -f "$NUDGED_FILE" ] && LAST_NUDGED="$(cat "$NUDGED_FILE" 2>/dev/null || echo '')"
    if [ -n "$STATE_HASH" ] && [ "$STATE_HASH" = "$LAST_NUDGED" ]; then
      exit 0
    fi
    [ -n "$STATE_HASH" ] && echo "$STATE_HASH" > "$NUDGED_FILE" 2>/dev/null

    # Emit nudge (= system reminder injection per Stop hook contract)
    if [ -n "$BODY" ]; then
      printf '[session-commit-nudge] このセッションで編集した repo に未 commit 残:\n'
      printf '%s' "$BODY"
      printf 'セッション終了前に commit + push 推奨 (= 別 session に WT を「拾われ」 て\n'
      printf '意図しない commit + push されるのを防ぐ、 CLAUDE.md §17 圧力 (4))。\n'
    fi
    if [ -n "$L1_BODY" ]; then
      printf '[session-commit-nudge] 層1 の repo に upstream へ入っていない変更がある (この clone では push できない = commit + push でなく PR):\n'
      printf '%s' "$L1_BODY"
    fi
    exit 0
    ;;
esac

exit 0
