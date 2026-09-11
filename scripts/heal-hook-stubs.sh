#!/usr/bin/env bash
# heal-hook-stubs.sh — 過去の installer が書き換えた「git 管理下の hook stub」 を track 版に戻す (冪等・差分なしは無音)
#
# 使い方:
#   heal-hook-stubs.sh [<base>]      # base 省略時は $HOME/Claude
#
# 対象: <base>/*/ のうち core.hooksPath が repo 内 (相対 path) を指す repo。
#   その hooks dir の track 済み file が worktree で変更されていて、 変更が installer の書いた stub
#   (header 「# Stub installed by claude-config/」) で、 track 版の exec 先が実在するときだけ戻す。
#   user が手で直した stub や、 track 版が壊れている stub には触らない。
#
# 何のため: installer は setup.sh 実行時にしか走らないので、 installer 側を直しても既に汚れた
#   worktree は他マシンで残る。 SessionStart から毎回呼ぶことで、 git pull だけで各マシンが直る。
#   規約 = conventions/hook-authoring.md#installer-tracked-stub
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/hook-stub.sh
. "$SCRIPT_DIR/lib/hook-stub.sh"

BASE="${1:-$HOME/Claude}"
[ -d "$BASE" ] || exit 0

for d in "$BASE"/*/; do
  repo="${d%/}"
  [ -e "$repo/.git" ] || continue
  hp="$(git -C "$repo" config --get core.hooksPath 2>/dev/null)" || continue
  case "$hp" in "" | /* | "~"*) continue ;; esac
  git -C "$repo" diff --quiet -- "$hp" 2>/dev/null && continue
  git -C "$repo" diff --name-only -- "$hp" 2>/dev/null | while IFS= read -r f; do
    [ -n "$f" ] && hook_stub_restore_drift "$repo" "$repo/$f" || true
  done
done
exit 0
