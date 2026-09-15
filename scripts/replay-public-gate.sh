#!/usr/bin/env bash
# replay-public-gate.sh — 公開 repo の直近の commit を「今の」 pre-commit gate に通し直し、 今なら止まる commit を出す
#
# 正本: claude-config/scripts/replay-public-gate.sh
# 規律: conventions/confidential-repo-boundary.md#gate-change-replays-unattended-writers
#
# Why: gate (検出語の再生成・Tier の追加・runner の修正) を締めると、 **その前に立っている無人の書き手**
#   (日次の digest を archive に commit する routine 等) が、 次に似た出力を出した日に黙って止まる。
#   書き手は失敗を warning で握りつぶす設計のことが多く、 transport が壊れたことに誰も気づかない。
#   実測: 検出語を締めた後、 論文を記録する bot の archive が「共著者名」 と「手元の原稿と同じ要旨」 で
#   必ず止まる状態になっていたが、 その日の出力には偶然どちらも無く、 次に載る日まで表に出なかった。
#   ∴ gate を変えたら、 無人の書き手の **過去の出力** を今の gate に通して先に壊れ方を見る。
#
# 機構: 各 commit C について、 C が変えた file だけを temp repo に置く — 親の版を base として commit →
#   C の版で上書きして stage → public-precommit-runner.sh を実行 (= C の差分だけが「追加行」 に見える。
#   Tier A-E と書誌・複合語の除外が commit 時と同じに効く)。 本物の repo は読むだけ。
#   ⚠️ 見るのは **今の** 検出語と runner。 過去にその commit が通ったかではない。
#
# usage:
#   replay-public-gate.sh [--repo DIR] [--last N] [--since WHEN] [--path PATHSPEC]
#     --repo  対象 repo (既定 = cwd の repo)
#     --last  直近 N commit (既定 10)。 --path を付けると、 その path を触った commit だけを数える
#     --since git log の --since (例: "14 days ago")。 定期実行ではこれを付ける = 直した後も履歴に残る古い commit で
#             永久に赤くならないように、 窓を「次の出力が似ていそうな直近」 に限る
#     --path  例: archive  (無人の書き手が書く場所に絞る)
#   replay-public-gate.sh --selftest
#
# exit: 0 = 全部通る / 1 = 今なら止まる commit がある / 2 = usage / 3 = runner 不在

set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SELF_DIR/public-precommit-runner.sh"

REPO=""
LAST=10
PATHSPEC=""
SINCE=""

replay_one() {
  # $1 = repo, $2 = commit。 stdout = runner の出力。 return = runner の rc
  local repo="$1" c="$2" tmp rc
  tmp="$(mktemp -d)" || return 3
  (
    cd "$tmp" || exit 3
    git init -q
    git config user.email "replay@example.com"
    git config user.name "replay"
    mkdir -p .claude
    touch .claude/public-repo.marker
    git add -A && git commit -qm base --allow-empty
    local st path
    # 親の版を base に
    while IFS=$'\t' read -r st path; do
      [ -n "$path" ] || continue
      case "$st" in
        M*|D*)
          mkdir -p "$(dirname "$path")"
          git -C "$repo" show "$c^:$path" > "$path" 2>/dev/null || rm -f "$path"
          ;;
      esac
    done < <(git -C "$repo" diff-tree --no-commit-id --name-status -r "$c")
    git add -A >/dev/null 2>&1 && git commit -qm parent --allow-empty
    # C の版で上書き
    while IFS=$'\t' read -r st path; do
      [ -n "$path" ] || continue
      case "$st" in
        A*|M*)
          mkdir -p "$(dirname "$path")"
          git -C "$repo" show "$c:$path" > "$path" 2>/dev/null
          ;;
        D*) rm -f "$path" ;;
      esac
    done < <(git -C "$repo" diff-tree --no-commit-id --name-status -r "$c")
    git add -A -f >/dev/null 2>&1
    "$RUNNER" 2>&1
  )
  rc=$?
  rm -rf "$tmp"
  return "$rc"
}

selftest() {
  local td fails=0 out rc
  td="$(mktemp -d)"
  export CLAUDE_PERSONAL_LAYER="$td/layer"
  mkdir -p "$CLAUDE_PERSONAL_LAYER"
  touch "$CLAUDE_PERSONAL_LAYER/.claude-personal-layer"
  echo "# mock personal layer" > "$CLAUDE_PERSONAL_LAYER/CLAUDE.md"   # find-personal-layer.sh は CLAUDE.md も要る
  printf '%s\n' 'MOCK_REPLAY_TERM' > "$CLAUDE_PERSONAL_LAYER/sensitive-terms.txt"
  (
    cd "$td" && git init -q r && cd r
    git config user.email "t@example.com"; git config user.name t
    printf 'hello\n' > a.txt && git add a.txt && git commit -qm one
    printf 'hello\nMOCK_REPLAY_TERM here\n' > a.txt && git add a.txt && git commit -qm two
    printf 'plain\n' > b.txt && git add b.txt && git commit -qm three
  )
  out="$(replay_one "$td/r" "$(git -C "$td/r" rev-parse HEAD~1)")"; rc=$?
  if [ "$rc" -eq 1 ]; then echo "PASS commit adding a term is blocked now"; else echo "FAIL term commit rc=$rc"; fails=$((fails+1)); fi
  out="$(replay_one "$td/r" "$(git -C "$td/r" rev-parse HEAD)")"; rc=$?
  if [ "$rc" -eq 0 ]; then echo "PASS plain commit passes"; else echo "FAIL plain commit rc=$rc"; fails=$((fails+1)); fi
  out="$(replay_one "$td/r" "$(git -C "$td/r" rev-parse HEAD~2)")"; rc=$?
  if [ "$rc" -eq 0 ]; then echo "PASS root commit (no parent) is replayed"; else echo "FAIL root commit rc=$rc"; fails=$((fails+1)); fi
  rm -rf "$td"
  if [ "$fails" -eq 0 ]; then echo "replay-public-gate selftest: OK"; return 0; fi
  echo "replay-public-gate selftest: $fails FAIL"; return 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) shift; REPO="${1:-}" ;;
    --last) shift; LAST="${1:-10}" ;;
    --path) shift; PATHSPEC="${1:-}" ;;
    --since) shift; SINCE="${1:-}" ;;
    --selftest) [ -x "$RUNNER" ] || exit 3; selftest; exit $? ;;
    -h|--help) awk '/^set -uo pipefail/ { exit } { print }' "$0"; exit 0 ;;
    *) echo "replay-public-gate.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -x "$RUNNER" ] || { echo "replay-public-gate.sh: runner not executable: $RUNNER" >&2; exit 3; }
if [ -n "$REPO" ]; then
  REPO="$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null)"
else
  REPO="$(git rev-parse --show-toplevel 2>/dev/null)"
fi
[ -n "$REPO" ] || { echo "replay-public-gate.sh: not a git repo" >&2; exit 2; }

LOG_ARGS=(--no-merges --format=%H -n "$LAST")
[ -n "$SINCE" ] && LOG_ARGS+=(--since "$SINCE")
if [ -n "$PATHSPEC" ]; then
  COMMITS="$(git -C "$REPO" log "${LOG_ARGS[@]}" -- "$PATHSPEC")"
else
  COMMITS="$(git -C "$REPO" log "${LOG_ARGS[@]}")"
fi

blocked=0
total=0
for c in $COMMITS; do
  total=$((total + 1))
  out="$(replay_one "$REPO" "$c")"; rc=$?
  if [ "$rc" -ne 0 ]; then
    blocked=$((blocked + 1))
    printf '🔴 %s %s — 今の gate なら止まる\n' "$(git -C "$REPO" log -1 --format='%h %ad' --date=short "$c")" "$(git -C "$REPO" log -1 --format=%s "$c" | cut -c1-60)"
    # 行の本文は出さない (= runner の見出し行だけ。 実名 gate は件数と file 名しか出さない)
    printf '%s\n' "$out" | grep -E '^\[(tier-|unpublished-quote|activity-facts|confidential-leak)|commit rejected by|^  [^ ].*(prose run|quoted span|FACT:|TERM)' | head -6 | sed 's/^/    /'
  fi
done
name="$(basename "$REPO")"
if [ "$blocked" -gt 0 ]; then
  echo "✗ [replay-public-gate] $name: 直近 $total commit${PATHSPEC:+ ($PATHSPEC)} のうち $blocked 本が今の gate で止まる — 無人の書き手なら次の同種の出力で commit が失敗する"
  echo "  → 誤検知なら検出器側を直す (conventions/confidential-repo-boundary.md#tree-finding-resolution)、 本物なら書き手の出力を直す"
  exit 1
fi
echo "ok [replay-public-gate] $name: 直近 $total commit${PATHSPEC:+ ($PATHSPEC)} は今の gate を通る"
exit 0
