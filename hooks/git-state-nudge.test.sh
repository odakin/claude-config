#!/usr/bin/env bash
# git-state-nudge.test.sh — git-state-nudge.sh の self-test (決定的 mock git repo ベース)
#
# 正本: claude-config/hooks/git-state-nudge.test.sh
# 実行: bash hooks/git-state-nudge.test.sh (run-all-checks.sh が自動発見)
#
# scope: 挙動固定できる決定的サブセットのみ (= spec 全体ではない):
#   case (1) orphan-tree / case (2) just-committed-not-pushed / case (3)
#   first-sighting divergence + 各 suppression。 時間依存の STALE_DIRT
#   (porcelain hash 24h age) と claude-config update notifier は
#   fixture で決定的に再現できないため対象外 (前者は 24h 実待ちが必要、
#   後者は $HOME/Claude/claude-config 実 clone 前提 — HOME override で
#   構造的に silent になることだけ暗黙に担保される)。
#
# 流儀は stale-read-nudge.test.sh 踏襲: HOME を temp に override して
# state dir (~/.claude/state/git-nudge) を隔離、 fixture は generic 名のみ。
# hook は cwd の repo を見るので、 各 assert は cd <repo> して起動する。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/git-state-nudge.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 0; }
command -v jq  >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }

pass=0; fail=0; results=()

BASE="$(mktemp -d)"
STATE_HOME="$BASE/home"
mkdir -p "$STATE_HOME"
trap 'rm -rf "$BASE"' EXIT

git_quiet() { git -C "$1" "${@:2}" >/dev/null 2>&1; }
setup_ident() {
  git -C "$1" config user.email noreply@anthropic.com
  git -C "$1" config user.name  tester
  git -C "$1" config commit.gpgsign false
}

# ---------- mock repos ----------
# REMOTE (bare) を共有 origin として:
#   CLEAN  = sync 済 (silent 期待)
#   BEHIND = origin が 1 commit 先行 (case 3: BEHIND 期待)
#   AHEAD  = local が 1 commit 先行、 commit は過去日付 (case 3: AHEAD 期待)
#   FRESH  = local commit 直後 (case 2: just-committed 期待)
#   ORPHAN = HEAD と @{u} に共通祖先なし (case 1: ORPHAN TREE 期待)
REMOTE="$BASE/remote.git"
git init -q --bare "$REMOTE"
git -C "$REMOTE" symbolic-ref HEAD refs/heads/main

SEED="$BASE/seed"
git init -q "$SEED"
git -C "$SEED" symbolic-ref HEAD refs/heads/main
setup_ident "$SEED"
printf 'v1\n' > "$SEED/file.md"
git_quiet "$SEED" add -A
git_quiet "$SEED" commit -m init
git_quiet "$SEED" remote add origin "$REMOTE"
git_quiet "$SEED" push -u origin main

# BEHIND だけ origin 前進「前」に clone (= behind 1 になる)。 CLEAN / AHEAD /
# FRESH は前進「後」に clone して sync 済から出発させる (= 各 case を pure に保つ)。
BEHIND="$BASE/behind"; git clone -q "$REMOTE" "$BEHIND"; setup_ident "$BEHIND"

# origin を 1 commit 進める (BEHIND の fetch は hook の first-sighting 経路が
# 自分で行う = fetch 動作そのものも検証される)
printf 'v2\n' >> "$SEED/file.md"
git_quiet "$SEED" commit -am v2
git_quiet "$SEED" push origin main

CLEAN="$BASE/clean";  git clone -q "$REMOTE" "$CLEAN";  setup_ident "$CLEAN"
AHEAD="$BASE/ahead";  git clone -q "$REMOTE" "$AHEAD";  setup_ident "$AHEAD"
FRESH="$BASE/fresh";  git clone -q "$REMOTE" "$FRESH";  setup_ident "$FRESH"

# AHEAD: 過去日付 commit (HEAD_AGE > 60s にして case 2 を bypass し case 3 に落とす)
printf 'local\n' >> "$AHEAD/file.md"
GIT_COMMITTER_DATE="2020-01-01T00:00:00 +0000" GIT_AUTHOR_DATE="2020-01-01T00:00:00 +0000" \
  git -C "$AHEAD" commit -aqm "old local work"

# ORPHAN: 独立 history の repo に origin を接ぎ木 (merge-base なし)
ORPHAN="$BASE/orphan"
git init -q "$ORPHAN"
git -C "$ORPHAN" symbolic-ref HEAD refs/heads/main
setup_ident "$ORPHAN"
printf 'unrelated\n' > "$ORPHAN/other.md"
git_quiet "$ORPHAN" add -A
GIT_COMMITTER_DATE="2020-01-01T00:00:00 +0000" GIT_AUTHOR_DATE="2020-01-01T00:00:00 +0000" \
  git -C "$ORPHAN" commit -qm "unrelated root"
git_quiet "$ORPHAN" remote add origin "$REMOTE"
git_quiet "$ORPHAN" fetch origin
git_quiet "$ORPHAN" branch -u origin/main main

# ---------- helper ----------
run_hook() { # <repo dir> [command string]
  local dir="$1" cmd="${2:-git status}"
  local input
  input="$(jq -nc --arg c "$cmd" '{tool_name:"Bash",tool_input:{command:$c}}')"
  ( cd "$dir" && printf '%s' "$input" | HOME="$STATE_HOME" bash "$HOOK" 2>/dev/null ) || true
}

assert_out() { # <label> <repo> <grep pattern (期待出力)>
  local label="$1" dir="$2" pat="$3" out
  out="$(run_hook "$dir")"
  if printf '%s' "$out" | grep -q "$pat"; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (pattern '$pat' not in output: ${out:0:120})")
  fi
}

assert_silent() { # <label> <repo>
  local label="$1" dir="$2" out
  out="$(run_hook "$dir")"
  if [ -z "$out" ]; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expected silent, got: ${out:0:120})")
  fi
}

echo "=== case 別 発火 ==="
assert_silent "T1: sync 済 repo → silent" "$CLEAN"
assert_out    "T2: case3 BEHIND (first-sighting fetch 込み) → 発火" "$BEHIND" "BEHIND by 1"
assert_out    "T3: case3 AHEAD (過去 commit) → 発火"               "$AHEAD"  "AHEAD by 1"
assert_out    "T4: case1 ORPHAN TREE → 発火"                       "$ORPHAN" "ORPHAN TREE"

echo "=== suppression ==="
assert_silent "T5: BEHIND 2 回目 (seen 済 4h 窓内) → silent" "$BEHIND"
assert_silent "T6: ORPHAN 2 回目 (同 HEAD nudged 済) → silent" "$ORPHAN"

echo "=== case 2: just-committed ==="
printf 'wip\n' >> "$FRESH/file.md"
git_quiet "$FRESH" commit -am "fresh work"
out="$(run_hook "$FRESH")"
if printf '%s' "$out" | grep -q "just committed"; then
  pass=$((pass+1)); results+=("✅ T7: commit 直後 (age<60s) → push reminder 発火")
else
  fail=$((fail+1)); results+=("❌ T7: push reminder 不発 (got: ${out:0:120})")
fi
assert_silent "T8: 同 HEAD 2 回目 → silent" "$FRESH"

echo "=== multi-repo follow (git -C literal path) ==="
# cwd = 非 repo、 command 中の literal `git -C <behind2>` を追跡できるか。
# BEHIND とは別 clone を使う (BEHIND は seen 済で suppress されるため)。
BEHIND2="$BASE/behind2"; git clone -q "$REMOTE" "$BEHIND2"; setup_ident "$BEHIND2"
git_quiet "$BEHIND2" reset --hard HEAD~1
out="$(run_hook "$BASE" "git -C $BEHIND2 log --oneline")"
if printf '%s' "$out" | grep -q '\[git -C\].*behind2\|behind2.*first time'; then
  pass=$((pass+1)); results+=("✅ T9: git -C literal path の repo も検査される")
else
  fail=$((fail+1)); results+=("❌ T9: git -C follow 不発 (got: ${out:0:120})")
fi

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
