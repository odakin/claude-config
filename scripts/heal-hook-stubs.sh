#!/usr/bin/env bash
# heal-hook-stubs.sh — 壊れた git hook を直す: 過去の installer が書き換えた git 管理下の stub を track 版に戻す + macOS に exec で kill される hook を同じ中身の新しい file に作り直す (冪等・直すものが無ければ無音)
#
# 使い方 (base 省略時は $HOME/Claude):
#   heal-hook-stubs.sh [<base>]             # 直す。 直した行と WARNING を 1 行ずつ出す
#   heal-hook-stubs.sh --surface [<base>]   # 直して、 結果を 3 つの見出し (戻した / 作り直した / 要対応) に分けて出す
#                                           # (SessionStart の注入用。 直すものが無ければ無音)
#   heal-hook-stubs.sh --check [<base>]     # 書かない。 macOS に exec で kill される hook と runner を 1 行ずつ出し、 あれば exit 1
#   commit が "hook ... died of signal 9" で止まったら、 その場で引数なしで 1 回走らせる
#
# (1) 過去の installer が書き換えた「git 管理下の hook stub」 を track 版に戻す (--check では飛ばす)
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
#   規約 = conventions/hook-authoring.md#killed-hook-stub (macOS 側の仕組み = conventions/macos-exec-policy-kill.md)
#
# 出力の契約 (--surface と、 これを取り込む SessionStart hook が頼る。 文言を変えるなら両方を直す):
#   "hook stub restored to the tracked version: <path>"             = (1) 戻した
#   "<label> recreated (macOS was killing it on exec): <path>"      = (2) 作り直した
#   それ以外の行 (WARNING: ... still killed ... / script のエラー)     = 要対応
#   "killed: <path>"                                                = --check の finding
#
# 何のため: installer は setup.sh 実行時にしか走らないので、 installer 側を直しても他マシンの状態は残る。
#   SessionStart から毎回呼ぶことで、 git pull だけで各マシンが直り、 commit が止まる前に気づける。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/hook-stub.sh
. "$SCRIPT_DIR/lib/hook-stub.sh"

MODE=heal
case "${1:-}" in
  --surface) MODE=surface; shift ;;
  --check) MODE=check; shift ;;
  -h | --help) sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
BASE="${1:-$HOME/Claude}"
[ -d "$BASE" ] || exit 0

EXEC_CHECK=0
[ "$_HOOK_EXEC_OS" = Darwin ] && EXEC_CHECK=1
KILLED=0

seen="|"
visit() {  # $1 = file, $2 = label。 実体ごとに 1 回だけ見る (symlink でなければ subshell を作らない)
  local real="$1"
  if [ -L "$1" ]; then real="$(hook_real_path "$1")" || return 0; fi
  case "$seen" in *"|$real|"*) return 0 ;; esac
  seen="$seen$real|"
  if [ "$MODE" = check ]; then
    if hook_exec_killed "$1"; then
      KILLED=$((KILLED + 1))
      echo "killed: $1"
    fi
  else
    hook_exec_heal "$1" "$2" 2>&1 || true
  fi
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

heal_all() {
  local d repo hp hd h
  for d in "$BASE"/*/; do
    repo="${d%/}"
    [ -e "$repo/.git" ] || continue
    hp="$(git -C "$repo" config --get core.hooksPath 2>/dev/null || true)"

    # ---- (1) track 済み stub の drift (repo 内の相対 hooksPath だけ) ----
    case "$MODE:$hp" in
      check:* | *: | *:/* | *:"~"*) ;;
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
      visit "$h" "hook"
      stub_runner "$h" || continue
      [ -f "$STUB_RUNNER" ] && visit "$STUB_RUNNER" "hook runner"
    done
  done
}

# --surface: 出力の契約に沿って 3 つの見出しに分ける
surface_section() {  # $1 = 見出し, $2 = 行, $3 = hook-authoring.md の anchor
  [ -n "$2" ] || return 0
  printf '%s\n%s\n\n  一般則: claude-config/conventions/hook-authoring.md#%s\n\n' \
    "$1" "$(printf '%s\n' "$2" | sed 's/^/  /')" "$3"
}

if [ "$MODE" = surface ]; then
  out="$(heal_all 2>&1)"
  [ -n "$out" ] || exit 0
  restored="$(printf '%s\n' "$out" | grep -F 'restored to the tracked version' || true)"
  recreated="$(printf '%s\n' "$out" | grep -F 'recreated (macOS' || true)"
  other="$(printf '%s\n' "$out" | grep -v -F -e 'restored to the tracked version' -e 'recreated (macOS' | grep -v '^[[:space:]]*$' || true)"
  surface_section "🧹 git 管理下の hook stub を track 版に戻した (= 過去の installer が書き換えた差分。 自動 pull の stash 衝突の元):" "$restored" installer-tracked-stub
  surface_section "🧹 macOS に exec で kill されていた git hook を、 同じ中身の新しい file に作り直した (= commit が died of signal 9 で止まる元):" "$recreated" killed-hook-stub
  surface_section "⚠️ git hook の修復で要対応 (= 作り直しても macOS に kill される hook は、 その repo の commit が止まる):" "$other" killed-hook-stub
  exit 0
fi

heal_all
[ "$MODE" = check ] && [ "$KILLED" -gt 0 ] && exit 1
exit 0
