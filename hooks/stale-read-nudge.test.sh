#!/usr/bin/env bash
# stale-read-nudge.test.sh — logic selftest (= 決定的 mock git repo ベース)
#
# 正本: ~/Claude/claude-config/hooks/stale-read-nudge.test.sh
#
# mock repo (= behind 状態を実 git で再現) で発火 4 条件を検証する。 transcript 依存の
# retroactive selftest (mcp-search-zero-result.test.sh の §B 型) は本 incident
# (discord.md behind 12) の transcript が当 session に無いため非採用 — 代わりに incident
# の本質 (= behind 区間で変更された file を読む → 発火 / 無変更 file → silent) を mock で
# 決定的に再現する。 leak 防止: fixture は generic 名のみ (= 実 private repo 名・PII 不使用)。
#
# 各 case は HOME を temp に override して state (= cache / nudged marker) を隔離する。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/stale-read-nudge.sh"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 0; }
command -v jq  >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }

pass=0
fail=0
results=()

BASE="$(mktemp -d)"
STATE_HOME="$BASE/home"
mkdir -p "$STATE_HOME"
trap 'rm -rf "$BASE"' EXIT

git_quiet() { git -C "$1" "${@:2}" >/dev/null 2>&1; }

# ---------- mock repo 構築 ----------
# REMOTE (bare) ← WORK (behind 1: tracked.md だけ upstream で v2 に進む) / CLEAN (sync 済)
REMOTE="$BASE/remote.git"
WORK="$BASE/work"
ADV="$BASE/adv"
CLEAN="$BASE/clean"
NOUP="$BASE/noupstream"

git init -q --bare "$REMOTE"
git -C "$REMOTE" symbolic-ref HEAD refs/heads/main        # bare HEAD を main に固定 (= 古い git の master default で clone checkout が空になるのを防ぐ)

git init -q "$WORK"
git -C "$WORK" symbolic-ref HEAD refs/heads/main          # branch 名を git version 非依存で main に固定
git -C "$WORK" config user.email noreply@anthropic.com
git -C "$WORK" config user.name  tester
git -C "$WORK" config commit.gpgsign false
printf 'v1\n' > "$WORK/tracked.md"
printf 'unchanged\n' > "$WORK/other.md"
git_quiet "$WORK" add -A
git_quiet "$WORK" commit -m init
git_quiet "$WORK" remote add origin "$REMOTE"
git_quiet "$WORK" push -u origin main

# origin を 1 commit 進める (tracked.md だけ変更) → WORK が behind 1 になる
git clone -q "$REMOTE" "$ADV"
git -C "$ADV" config user.email noreply@anthropic.com
git -C "$ADV" config user.name  tester
git -C "$ADV" config commit.gpgsign false
printf 'v2\n' >> "$ADV/tracked.md"
git_quiet "$ADV" commit -am v2
git_quiet "$ADV" push origin main

# WORK の @{u} (origin/main) を進める (= fetch only、 HEAD は v1 のまま)
git_quiet "$WORK" fetch origin

# CLEAN = sync 済 clone (behind 0)
git clone -q "$REMOTE" "$CLEAN"

# NOUP = upstream 無しの git repo
git init -q "$NOUP"
git -C "$NOUP" symbolic-ref HEAD refs/heads/main
git -C "$NOUP" config user.email noreply@anthropic.com
git -C "$NOUP" config user.name  tester
git -C "$NOUP" config commit.gpgsign false
printf 'x\n' > "$NOUP/file.md"
git_quiet "$NOUP" add -A
git_quiet "$NOUP" commit -m init

# 非 git path
NONGIT="$BASE/plain.txt"
printf 'hello\n' > "$NONGIT"

# ---------- helper ----------
run_hook() { # <file> [force]
  local file="$1" force="${2:-0}"
  local input
  input="$(jq -nc --arg p "$file" '{tool_name:"Read",tool_input:{file_path:$p}}')"
  printf '%s' "$input" | HOME="$STATE_HOME" STALE_READ_FORCE="$force" "$HOOK" 2>/dev/null || true
}

assert() { # <label> <expect 0|1> <file> [force]
  local label="$1" expect="$2" file="$3" force="${4:-0}"
  local out actual=0
  out="$(run_hook "$file" "$force")"
  printf '%s' "$out" | grep -q 'stale-read' && actual=1
  if [ "$actual" = "$expect" ]; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect actual=$actual)")
  fi
}

echo "=== logic tests (mock git repo) ==="

# 핵 incident reproduction: behind 区間で変更された file を読む → 発火
assert "T1: incident型 (behind ∧ 当該 file 変更) → 発火" 1 "$WORK/tracked.md"

# 重複抑制: 同 file 2 回目は silent (T1 で 1 回鳴った直後)
assert "T2: 重複抑制 (同 repo/file/upstream で 2 回目) → silent" 0 "$WORK/tracked.md"

# ★ 誤爆抑制の核心: behind でも当該 file 無変更なら silent
assert "T3: ★核心 (behind だが当該 file 無変更) → silent" 0 "$WORK/other.md"

# sync 済 repo → silent
assert "T4: sync 済 repo (behind 0) → silent" 0 "$CLEAN/tracked.md"

# upstream 無し repo → silent
assert "T5: upstream 無し repo → silent" 0 "$NOUP/file.md"

# 非 git path → silent
assert "T6: 非 git path → silent" 0 "$NONGIT"

# 存在しない file → silent (fail-open)
assert "T7: 存在しない file_path → silent" 0 "$BASE/does-not-exist/x.md"

# FORCE: behind=0 の sync 済 file でも出力 path を強制発火 (= 出力 path test)
assert "T8: FORCE bypass で出力 path 発火" 1 "$CLEAN/other.md" 1

# 出力が valid JSON か (additionalContext)
echo ""
echo "=== output shape ==="
OUT_JSON="$(run_hook "$WORK/tracked.md" 1)"
if printf '%s' "$OUT_JSON" | jq -e '.hookSpecificOutput.additionalContext | test("stale-read")' >/dev/null 2>&1; then
  pass=$((pass+1)); results+=("✅ T9: stdout は valid JSON で additionalContext に警告を含む")
else
  fail=$((fail+1)); results+=("❌ T9: stdout JSON / additionalContext 不正")
fi

# 警告本文に最新確認コマンドが含まれるか
if printf '%s' "$OUT_JSON" | jq -r '.hookSpecificOutput.additionalContext' 2>/dev/null | grep -q 'git -C'; then
  pass=$((pass+1)); results+=("✅ T10: 警告本文に pull / show の最新確認コマンドを含む")
else
  fail=$((fail+1)); results+=("❌ T10: 最新確認コマンド欠落")
fi

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
