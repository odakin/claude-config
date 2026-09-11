#!/usr/bin/env bash
# install-hook-stubs.test.sh — install-public-precommit / install-public-commit-msg / install-session-trailer の冪等性 test
#
# 検査すること (2026-09-12):
#   1. repo が "$HOME/..." 形の stub を track している (core.hooksPath が repo 内) とき、 同じ runner を
#      指すなら書き換えない = worktree が汚れない
#   2. 別の runner を指す古い stub は従来どおり最新化する
#   3. prepare-commit-msg stub が repo 内 hooksPath に untracked で置かれたら .git/info/exclude に載る
#   4. 通常の .git/hooks に置く場合は exclude に何も足さない
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "  ok: $1"; }
ng() { FAIL=$((FAIL+1)); echo "  NG: $1"; }

mkrepo() {  # $1 = dir
  git init -q "$1"
  git -C "$1" config user.name t
  git -C "$1" config user.email t@example.invalid
  git -C "$1" config commit.gpgsign false
  mkdir -p "$1/.claude"
  : > "$1/.claude/public-repo.marker"
}

# 1. tracked "$HOME/..." 形 stub (hooksPath = repo 内) は書き換えない
echo "=== T1: tracked \$HOME-form stubs stay untouched ==="
R="$TMP/r1"; mkrepo "$R"
git -C "$R" config core.hooksPath scripts/hooks
mkdir -p "$R/scripts/hooks"
home_rel="${HERE/#$HOME/\$HOME}"
for pair in "pre-commit:public-precommit-runner.sh" "commit-msg:commit-msg-leak-guard-runner.sh"; do
  hook="${pair%%:*}"; runner="${pair#*:}"
  printf '#!/bin/bash\n# Stub\nexec "%s/%s" "$@"\n' "$home_rel" "$runner" > "$R/scripts/hooks/$hook"
  chmod +x "$R/scripts/hooks/$hook"
done
git -C "$R" add -A && git -C "$R" commit -q --no-verify -m init
bash "$HERE/install-public-precommit.sh" "$R" >/dev/null 2>&1
bash "$HERE/install-public-commit-msg.sh" "$R" >/dev/null 2>&1
st="$(git -C "$R" status --porcelain -- scripts/hooks/pre-commit scripts/hooks/commit-msg)"
[ -z "$st" ] && ok "tracked stubs not rewritten" || ng "worktree dirtied: $st"

# 2. 別 runner を指す古い stub は最新化する
echo "=== T2: stale stub is refreshed ==="
printf '#!/bin/bash\n# Stub\nexec "/old/place/public-precommit-runner.sh" "$@"\n' > "$R/scripts/hooks/pre-commit"
bash "$HERE/install-public-precommit.sh" "$R" >/dev/null 2>&1
grep -qF "exec \"$HERE/public-precommit-runner.sh\"" "$R/scripts/hooks/pre-commit" && ok "stale stub refreshed" || ng "stale stub not refreshed: $(cat "$R/scripts/hooks/pre-commit")"

# 3. repo 内 hooksPath に置いた untracked trailer stub は exclude に載る (2 回走らせても 1 行)
echo "=== T3: untracked in-worktree trailer stub is excluded ==="
bash "$HERE/install-session-trailer.sh" "$R" >/dev/null 2>&1
bash "$HERE/install-session-trailer.sh" "$R" >/dev/null 2>&1
st="$(git -C "$R" status --porcelain -- scripts/hooks/prepare-commit-msg)"
[ -z "$st" ] && ok "trailer stub hidden from status" || ng "trailer stub still shows: $st"
n="$(grep -cxF '/scripts/hooks/prepare-commit-msg' "$R/.git/info/exclude" 2>/dev/null || true)"
[ "$n" = "1" ] && ok "exclude entry written once" || ng "exclude entry count = $n"

# 4. 通常の .git/hooks は exclude に触らない
echo "=== T4: plain .git/hooks install leaves exclude alone ==="
R2="$TMP/r2"; mkrepo "$R2"
before="$(cat "$R2/.git/info/exclude" 2>/dev/null || true)"
bash "$HERE/install-session-trailer.sh" "$R2" >/dev/null 2>&1
after="$(cat "$R2/.git/info/exclude" 2>/dev/null || true)"
[ -x "$R2/.git/hooks/prepare-commit-msg" ] && ok "stub installed in .git/hooks" || ng "stub missing"
[ "$before" = "$after" ] && ok "exclude unchanged" || ng "exclude changed"

echo
echo "=== Result: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
