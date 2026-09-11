#!/usr/bin/env bash
# install-hook-stubs.test.sh — hook stub installer 3 本 + heal-hook-stubs.sh の test (lib/hook-stub.sh の規約)
#
# 規約 = installer は git が track している file を書き換えない (conventions/hook-authoring.md#installer-tracked-stub):
#   T1 track 済みの "$HOME/..." 形 stub (同じ runner) → 書き換えない
#   T2 track 済みで別の場所を指す stub → 書き換えない (警告だけ)
#   T3 untrack の古い stub (.git/hooks) → 最新化する
#   T4 repo 内 hooksPath の untrack trailer stub → .git/info/exclude に 1 行
#   T5 通常の .git/hooks → exclude に触らない
#   T6 過去の installer が track 済み stub に書いた差分 → installer 実行で track 版に戻る
#   T7 heal-hook-stubs.sh → installer の書いた差分だけ戻し、 user の手直しには触らない
#   T8 track 済みの自前 pre-commit (stub でない) → 退避も上書きもしない
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "  ok: $1"; }
ng() { FAIL=$((FAIL+1)); echo "  NG: $1"; }

mkrepo() {  # $1 = dir, $2 = "public" なら marker を置く
  git init -q "$1"
  git -C "$1" config user.name t
  git -C "$1" config user.email t@example.invalid
  git -C "$1" config commit.gpgsign false
  if [ "${2:-}" = "public" ]; then
    mkdir -p "$1/.claude"
    : > "$1/.claude/public-repo.marker"
  fi
}
home_rel="${HERE/#$HOME/\$HOME}"
stub() {  # $1 = exec target
  printf '#!/bin/bash\n# Stub installed by claude-config/scripts/install-x.sh\n# Do not edit.\nexec "%s" "$@"\n' "$1"
}
clean() { [ -z "$(git -C "$1" status --porcelain -- "$2")" ]; }

# 共通 fixture: hooksPath = scripts/hooks、 "$HOME/..." 形 stub を track
mk_tracked_repo() {  # $1 = dir
  mkrepo "$1" public
  git -C "$1" config core.hooksPath scripts/hooks
  mkdir -p "$1/scripts/hooks"
  stub "$home_rel/public-precommit-runner.sh" > "$1/scripts/hooks/pre-commit"
  stub "$home_rel/commit-msg-leak-guard-runner.sh" > "$1/scripts/hooks/commit-msg"
  chmod +x "$1/scripts/hooks/pre-commit" "$1/scripts/hooks/commit-msg"
  git -C "$1" add -A && git -C "$1" commit -q --no-verify -m init
}

echo "=== T1: tracked \$HOME-form stubs stay untouched ==="
R="$TMP/r1"; mk_tracked_repo "$R"
bash "$HERE/install-public-precommit.sh" "$R" >/dev/null 2>&1
bash "$HERE/install-public-commit-msg.sh" "$R" >/dev/null 2>&1
clean "$R" scripts/hooks && ok "tracked stubs not rewritten" || ng "worktree dirtied: $(git -C "$R" status --porcelain)"

echo "=== T2: tracked stub pointing elsewhere is left alone (warning only) ==="
stub "/old/place/public-precommit-runner.sh" > "$R/scripts/hooks/pre-commit"
git -C "$R" commit -q --no-verify -am "old path"
err="$(bash "$HERE/install-public-precommit.sh" "$R" 2>&1 >/dev/null)"
clean "$R" scripts/hooks && ok "tracked stub not rewritten" || ng "tracked stub rewritten"
case "$err" in *"not rewriting"*) ok "warning printed" ;; *) ng "no warning (got: $err)" ;; esac

echo "=== T3: untracked stale stub in .git/hooks is refreshed ==="
R3="$TMP/r3"; mkrepo "$R3" public
stub "/old/place/public-precommit-runner.sh" > "$R3/.git/hooks/pre-commit"
bash "$HERE/install-public-precommit.sh" "$R3" >/dev/null 2>&1
grep -qF "exec \"$HERE/public-precommit-runner.sh\"" "$R3/.git/hooks/pre-commit" && ok "stale stub refreshed" || ng "not refreshed: $(cat "$R3/.git/hooks/pre-commit")"

echo "=== T4: untracked in-worktree trailer stub is excluded ==="
bash "$HERE/install-session-trailer.sh" "$R" >/dev/null 2>&1
bash "$HERE/install-session-trailer.sh" "$R" >/dev/null 2>&1
clean "$R" scripts/hooks/prepare-commit-msg && ok "trailer stub hidden from status" || ng "trailer stub still shows"
n="$(grep -cxF '/scripts/hooks/prepare-commit-msg' "$R/.git/info/exclude" 2>/dev/null || true)"
[ "$n" = "1" ] && ok "exclude entry written once" || ng "exclude entry count = $n"

echo "=== T5: plain .git/hooks install leaves exclude alone ==="
R5="$TMP/r5"; mkrepo "$R5"
before="$(cat "$R5/.git/info/exclude" 2>/dev/null || true)"
bash "$HERE/install-session-trailer.sh" "$R5" >/dev/null 2>&1
after="$(cat "$R5/.git/info/exclude" 2>/dev/null || true)"
[ -x "$R5/.git/hooks/prepare-commit-msg" ] && ok "stub installed in .git/hooks" || ng "stub missing"
[ "$before" = "$after" ] && ok "exclude unchanged" || ng "exclude changed"

echo "=== T6: installer restores its own past drift on a tracked stub ==="
R6="$TMP/r6"; mk_tracked_repo "$R6"
stub "$HERE/public-precommit-runner.sh" > "$R6/scripts/hooks/pre-commit"   # = 旧 installer が書いた absolute 形
clean "$R6" scripts/hooks && ng "fixture should be dirty" || ok "fixture dirty (old installer drift)"
out="$(bash "$HERE/install-public-precommit.sh" "$R6" 2>&1)"
clean "$R6" scripts/hooks && ok "drift restored to tracked version" || ng "still dirty (got: $out)"

echo "=== T7: heal-hook-stubs.sh restores installer drift only ==="
H="$TMP/heal"; mkdir -p "$H"
mk_tracked_repo "$H/a"
stub "$HERE/commit-msg-leak-guard-runner.sh" > "$H/a/scripts/hooks/commit-msg"          # installer drift
mk_tracked_repo "$H/b"
printf '#!/bin/bash\n# my own tweak\nexec "%s/public-precommit-runner.sh" "$@"\n' "$HERE" > "$H/b/scripts/hooks/pre-commit"   # user の手直し
out="$(bash "$HERE/heal-hook-stubs.sh" "$H" 2>&1)"
clean "$H/a" scripts/hooks && ok "installer drift healed" || ng "a still dirty"
clean "$H/b" scripts/hooks && ng "user edit was reverted" || ok "user edit left alone"
case "$out" in *"restored"*"/a/"*) ok "heal reported" ;; *) ng "heal output: $out" ;; esac
out2="$(bash "$HERE/heal-hook-stubs.sh" "$H" 2>&1)"
[ -z "$out2" ] && ok "second run silent" || ng "second run not silent: $out2"

echo "=== T8: tracked custom pre-commit is neither moved nor overwritten ==="
R8="$TMP/r8"; mkrepo "$R8" public
git -C "$R8" config core.hooksPath .githooks
mkdir -p "$R8/.githooks"
printf '#!/bin/bash\necho custom\n' > "$R8/.githooks/pre-commit"; chmod +x "$R8/.githooks/pre-commit"
git -C "$R8" add -A && git -C "$R8" commit -q --no-verify -m init
bash "$HERE/install-public-precommit.sh" "$R8" >/dev/null 2>&1
clean "$R8" .githooks && ok "custom hook untouched" || ng "custom hook changed: $(git -C "$R8" status --porcelain)"
ls "$R8/.githooks" | grep -q '\.bak-' && ng "backup created" || ok "no backup created"

echo
echo "=== Result: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
