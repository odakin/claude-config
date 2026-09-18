#!/usr/bin/env bash
# heal-hook-stubs.sh — 壊れた git hook を直す: 過去の installer が書き換えた git 管理下の stub を track 版に戻す + macOS に exec で kill される hook を同じ中身の新しい file に作り直す (冪等・直すものが無ければ無音)
#
# 使い方:
#   heal-hook-stubs.sh [<base>]      # base 省略時は $HOME/Claude
#   commit が "hook ... died of signal 9" で止まったら、 その場でこれを 1 回走らせる
#
# (1) 過去の installer が書き換えた「git 管理下の hook stub」 を track 版に戻す
#   対象: <base>/*/ のうち core.hooksPath が repo 内 (相対 path) を指す repo。
#   その hooks dir の track 済み file が worktree で変更されていて、 worktree 側が installer の書く 4 行
#   (shebang / 「# Stub installed by claude-config/」 / Do not edit / exec) そのままで、 track 版の exec 先が
#   実在するときだけ戻す。 1 行でも手で足した stub や、 track 版が壊れている stub には触らない。
#   規約 = conventions/hook-authoring.md#installer-tracked-stub
#
# (2) macOS に exec で kill される hook を、 同じ bytes・同じ mode の新しい inode に作り直す (macOS のみ)
#   対象: <base>/*/ の全 repo で git が実際に使う hooks dir の hook (名前に . を含む sample・退避・一時 file は除く) と、
#   stub の exec 先 (runner)。 symlink は実体で重複を除く。 bash の script だけを検査する (1 行も走らせない)。
#   作り直しても kill されるものは WARNING を出して残す (繰り返さない)。
#   規約 = conventions/hook-authoring.md#killed-hook-stub
#
# 何のため: installer は setup.sh 実行時にしか走らないので、 installer 側を直しても他マシンの状態は残る。
#   SessionStart から毎回呼ぶことで、 git pull だけで各マシンが直り、 commit が止まる前に気づける。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/hook-stub.sh
. "$SCRIPT_DIR/lib/hook-stub.sh"

BASE="${1:-$HOME/Claude}"
[ -d "$BASE" ] || exit 0

EXEC_CHECK=0
[ "$_HOOK_EXEC_OS" = Darwin ] && EXEC_CHECK=1

seen="|"
heal_once() {  # $1 = file, $2 = label。 実体ごとに 1 回だけ見る (symlink でなければ subshell を作らない)
  local real="$1"
  if [ -L "$1" ]; then real="$(hook_real_path "$1")" || return 0; fi
  case "$seen" in *"|$real|"*) return 0 ;; esac
  seen="$seen$real|"
  hook_exec_heal "$1" "$2" 2>&1 || true
}

# stub の 4 行目 (exec "<runner>" "$@") から runner を STUB_RUNNER に入れる (fork しない)
stub_runner() {  # $1 = hook
  local l1 l2 l3 l4
  STUB_RUNNER=""
  { IFS= read -r l1; IFS= read -r l2; IFS= read -r l3; IFS= read -r l4; } < "$1" 2>/dev/null || true
  case "${l2:-}" in "# Stub installed by claude-config/"*) ;; *) return 1 ;; esac
  case "${l4:-}" in 'exec "'*'" "$@"') ;; *) return 1 ;; esac
  l4="${l4#exec \"}"
  l4="${l4%\" \"\$@\"}"
  STUB_RUNNER="${l4/#\$HOME/$HOME}"
}

for d in "$BASE"/*/; do
  repo="${d%/}"
  [ -e "$repo/.git" ] || continue
  hp="$(git -C "$repo" config --get core.hooksPath 2>/dev/null || true)"

  # ---- (1) track 済み stub の drift (repo 内の相対 hooksPath だけ) ----
  case "$hp" in
    "" | /* | "~"*) ;;
    *)
      if ! git -C "$repo" diff --quiet -- "$hp" 2>/dev/null; then
        git -C "$repo" diff --name-only -- "$hp" 2>/dev/null | while IFS= read -r f; do
          [ -n "$f" ] && hook_stub_restore_drift "$repo" "$repo/$f" || true
        done
      fi
      ;;
  esac

  # ---- (2) macOS に exec で kill される hook (git が実際に使う hooks dir) ----
  [ "$EXEC_CHECK" = 1 ] || continue
  case "$hp" in
    "") if [ -d "$repo/.git" ]; then hd="$repo/.git/hooks"
        else hd="$(git -C "$repo" rev-parse --git-path hooks 2>/dev/null)" || continue; fi ;;
    "~"*) hd="$HOME${hp#\~}" ;;
    *) hd="$hp" ;;
  esac
  case "$hd" in /*) ;; *) hd="$repo/$hd" ;; esac
  [ -d "$hd" ] || continue
  for h in "$hd"/*; do
    case "${h##*/}" in *.* | *~) continue ;; esac   # git の hook 名に . は無い (.sample / .bak / 一時 file を除く)
    [ -f "$h" ] && [ -x "$h" ] || continue
    heal_once "$h" "hook"
    stub_runner "$h" || continue
    [ -f "$STUB_RUNNER" ] && heal_once "$STUB_RUNNER" "hook runner"
  done
done
exit 0
