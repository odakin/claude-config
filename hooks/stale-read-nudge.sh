#!/usr/bin/env bash
# stale-read-nudge.sh — PostToolUse(Read) hook (layer 1)
#
# 正本: ~/Claude/claude-config/hooks/stale-read-nudge.sh
# 配信: claude-config/setup.sh install_hooks (= ~/.claude/hooks/ に symlink +
#       settings.json の PostToolUse に登録、 matcher = "Read")
#
# 動作 (= 非 block、 -nudge):
#   Read tool で読まれた file が「origin に未取込みの変更がある behind リポの、
#   まさにその behind 区間で変更された file」 だった時 *だけ* stale 警告を
#   additionalContext で inject する。 それ以外は silent。
#
#   = git-state-nudge.sh (PostToolUse(Bash)) の Read 経路版。 git-state-nudge は
#   Bash command しか見ないため、 Read tool で stale file を読んで判断する経路は
#   機械的に丸裸だった (= 2026-06-21 RCA)。 本 hook がその穴を塞ぐ。
#
# 発火 4 条件 (= 誤爆抑制が肝):
#   (1) file_path の dir が git work tree 配下 (rev-parse --show-toplevel)
#   (2) その repo が upstream に対し behind (rev-list --count HEAD..@{u} > 0)
#   (3) ★ 当該 file が behind 区間で実変更されている (git log HEAD..@{u} -- <file>
#       が non-empty) — これが誤爆抑制の核心。 behind でもその file が無変更なら
#       読んでも stale でないので黙る。 (3) を外すと behind の全 repo で全 Read が
#       鳴って useless になる。
#   (4) 同 (repo, file, upstream-sha) で一度だけ (= 重複抑制 marker)。 upstream が
#       進む (= 新たな fetch) と key が変わり再警告。 pull すれば (2)(3) が消えて発火しない。
#
# fetch しない (= 設計判断、 plan §設計判断):
#   Read は高頻度なので hook 内 fetch はしない。 @{u} の鮮度は (a) git-state-nudge.sh
#   の first-sighting one-time fetch (4h window) / (b) session 開始時の sync sweep /
#   (c) 手動 git fetch に依存する。 fetch していないと「実は behind なのに @{u} が古くて
#   behind=0 に見える」 miss が起きうる trade-off を受容 (= 高頻度 Read での fetch コスト >
#   この miss の害)。
#
# cost (= per-repo behind cache で軽量化):
#   sync 済 repo (= 大多数) 配下の連続 Read で rev-list を毎回撃たないよう、 per-repo の
#   behind count を $HOME/.claude/state/stale-read/<hash>.behind に short-TTL (120s) cache。
#   cache hit ∧ behind=0 なら即 silent。 behind>0 の repo でも最終発火は常に live の
#   git log HEAD..@{u} -- <file> で決まるので、 cache が stale (= pull 後も古い behind>0 を
#   保持) でも誤爆しない (= (3) が live)。 SessionStart で全 repo list を作る 2 段方式は配線増 +
#   maintenance ゆえ不採用、 per-repo short-TTL cache で同等の軽量化を単一 hook で達成する
#   (= cold-eyes 判断)。
#
# desktop gap (= CLI only):
#   Claude desktop (Cowork) app は PostToolUse hook の model 向き出力 (additionalContext) を
#   honor しない (hook-authoring.md#frontend-dependent-cowork)。 → 本 hook は CLI session でのみ効く。 desktop 主運用
#   では個人層 (layer 3) の read-stale 規律が唯一の防御。 surface file fallback (= session 冒頭読込) は
#   per-file・時限的な本警告と相性が悪く (= 古い無関係警告が次 session 冒頭に出る noise)、 意図的に
#   不採用 (= mcp-search-zero-result とは別判断、 あちらは session 冒頭 anchoring に価値がある別 incident)。
#
# 設計動機:
#   behind なリポの stale file を read-only で読んで「古い版に無い記述を『無い』」 と誤断定する
#   failure mode を機械的に防ぐ。 read-only safe バイアス (= 書かない/push しないから安全) が罠で、
#   stale file で事実主張すると結論が腐る。 規律本体は個人層 (layer 3) の read-stale 規律
#   (= Read 前に sync 解消 or stale 確認)、 本 hook はその機械化 backstop。 ⚠️ hook は「reminder を
#   読み飛ばす Claude」 の前で必ず機能する保証はない = 規律が本体、 hook は補完。
#
# 安全: 全 path で fail-open (= Read を絶対に止めない、 exit 0 のみ、 stdin/jq/git 不在で silent)。
#
# テスト env:
#   STALE_READ_FORCE=1   behind/changed/marker gate を bypass して必ず発火 (= 出力 path test 用、
#                        repo 検出 (1) は通す = mock repo を input に要する)

set -uo pipefail
# NOTE: set -e は使わない — git/grep が legitimately 非0 を返す (no upstream / no match 等)。
# 各 gate は明示的に分岐する。

FORCE="${STALE_READ_FORCE:-0}"

# ---------- 0. stdin + jq guard (= fail-open) ----------
command -v jq >/dev/null 2>&1 || exit 0
[ -t 0 ] && exit 0
STDIN_JSON="$(cat 2>/dev/null || true)"
[ -n "$STDIN_JSON" ] || exit 0

FILE_PATH="$(printf '%s' "$STDIN_JSON" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo '')"
[ -n "$FILE_PATH" ] || exit 0

# ---------- helper: sha1 of a string (path → state filename) ----------
_hash() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum | cut -d' ' -f1
  elif command -v sha1sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha1sum | cut -d' ' -f1
  else
    printf '%s' "$1" | tr -c 'A-Za-z0-9' '_'
  fi
}

# ---------- 1. git work tree 判定 ----------
DIR="$(dirname "$FILE_PATH")"
[ -d "$DIR" ] || exit 0
REPO_ROOT="$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null || echo '')"
[ -n "$REPO_ROOT" ] || exit 0

UPSTREAM="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref '@{u}' 2>/dev/null || echo '')"
[ -n "$UPSTREAM" ] || exit 0

STATE_DIR="$HOME/.claude/state/stale-read"
mkdir -p "$STATE_DIR" 2>/dev/null || exit 0

NOW="$(date +%s)"
CACHE_TTL=120
REPO_HASH="$(_hash "$REPO_ROOT")"
BEHIND_CACHE="$STATE_DIR/$REPO_HASH.behind"

# ---------- 2. behind 判定 (= per-repo short-TTL cache 経由) ----------
BEHIND=""
if [ -f "$BEHIND_CACHE" ]; then
  CMTIME="$(stat -f %m "$BEHIND_CACHE" 2>/dev/null || stat -c %Y "$BEHIND_CACHE" 2>/dev/null || echo 0)"
  if [ $((NOW - CMTIME)) -lt "$CACHE_TTL" ]; then
    BEHIND="$(cat "$BEHIND_CACHE" 2>/dev/null || echo '')"
  fi
fi
if [ -z "$BEHIND" ]; then
  BEHIND="$(git -C "$REPO_ROOT" rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)"
  printf '%s' "$BEHIND" > "$BEHIND_CACHE" 2>/dev/null || true
fi
# 非数値防御
case "$BEHIND" in ''|*[!0-9]*) BEHIND=0 ;; esac

if [ "$FORCE" != "1" ]; then
  [ "$BEHIND" -gt 0 ] || exit 0
fi

# ---------- 3. ★ 当該 file が behind 区間で実変更されたか (= live、 誤爆抑制の核心) ----------
# repo-relative path (symlink 等で prefix strip 失敗時は absolute のまま — git -C は両方受ける)
REL="${FILE_PATH#"$REPO_ROOT"/}"
CHANGED_LOG=""
if [ "$BEHIND" -gt 0 ]; then
  CHANGED_LOG="$(git -C "$REPO_ROOT" log --oneline "HEAD..$UPSTREAM" -- "$REL" 2>/dev/null | head -6 || echo '')"
fi
if [ "$FORCE" != "1" ]; then
  [ -n "$CHANGED_LOG" ] || exit 0
else
  [ -n "$CHANGED_LOG" ] || CHANGED_LOG="(forced test — no real diff)"
  [ "$BEHIND" -gt 0 ] || BEHIND=1
fi

# ---------- 4. 重複抑制 marker (= per (repo,file,upstream-sha)) ----------
UPSTREAM_SHA="$(git -C "$REPO_ROOT" rev-parse "$UPSTREAM" 2>/dev/null || echo 'unknown')"
NUDGED="$STATE_DIR/$(_hash "$REPO_ROOT|$FILE_PATH|$UPSTREAM_SHA").nudged"
if [ "$FORCE" != "1" ]; then
  [ -f "$NUDGED" ] && exit 0
  touch "$NUDGED" 2>/dev/null || true
fi

# ---------- 5. 警告本文 ----------
REMINDER="⚠️ stale-read: behind なリポの未取込み変更がある file を読んだ (= 判断の土台にする前に最新を確認)

file:   $REL
repo:   $REPO_ROOT  (behind $BEHIND vs $UPSTREAM)

今 Read した内容は origin の最新ではない可能性がある (= この file が behind 区間で変更されている)。
内容で「X は無い / 未整備 / こうなっている」 と結論する前に、 以下のいずれかで最新を確認:
  - git -C \"$REPO_ROOT\" pull        (= dirty なら stash → ff-pull、 別 session の WIP に注意)
  - git -C \"$REPO_ROOT\" show $UPSTREAM:$REL   (= pull せず最新版だけ見る)

未取込みの該当 commit (HEAD..$UPSTREAM -- $REL):
$CHANGED_LOG

規律: work-discipline.md A 節「behind なリポのファイルを読んで判断する前に sync 解消 or stale 確認」
  (= read-only でも「読むだけ」 を例外にしない。 push 作業と違い pull が随伴強制されないので最も危険)"

printf '%s\n' "$REMINDER" >&2

# ---------- 6. stdout JSON (= PostToolUse additionalContext + systemMessage、 hook-authoring.md#warn-mode-spec-uncertainty) ----------
jq -n --arg msg "$REMINDER" '{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": $msg
  },
  "systemMessage": $msg
}'

exit 0
