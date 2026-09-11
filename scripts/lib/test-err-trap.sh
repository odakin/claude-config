#!/usr/bin/env bash
# test-err-trap.sh — set -e の bash test で落ちた assertion の行とコマンドを stderr に出す ERR trap (sourceable lib)
#
# 正本: claude-config/scripts/lib/test-err-trap.sh
# 呼び元: bare `[ ... ]` / `grep -q` を assertion にする set -euo pipefail の test 群
#         (`grep -l test-err-trap.sh` で列挙)。 自身の検査 = test-err-trap.test.sh
#
# 背景: set -e の test は assertion が落ちると無言で exit 1 し、 CI log には
#   run-all-checks.sh の "✗ test: <name>" しか残らない。 2026-09-01〜09-11 に main の
#   checks が push 225 回連続で red だった原因は setup-codex.test.sh の BSD 専用
#   `stat -f '%Lp'` 1 行だったが、 log に行が出ないため特定が遅れた。
#
# 使い方 (set -euo pipefail の後、 最初の assertion より前。 caller の shell で set -E が有効になる):
#   . "$SCRIPT_DIR/lib/test-err-trap.sh"
# 失敗時の stderr (1 行):
#   <test>: FAIL at line <N>: <command の 1 行目>
#   <test>: FAIL at line <呼び出し行> (in run_setup): <command>     ← 関数内の失敗
#
# 設計 (bash 3.2.57 / 5.3.9 で実測):
# - set -E: 無いと関数内の失敗は trap に届かず無言で exit する
# - BASH_SUBSHELL > 0 では出さない: `[ "$(cmd)" = x ]` の cmd の失敗が subshell 側と外側で
#   二重に出るのを防ぎ、 外側の 1 行だけにする
# - 関数内の行番号は出さない: bash 3.2 は関数内の $LINENO を関数定義の行で返す。
#   代わりに 3.2 でも正しい呼び出し行 (BASH_LINENO) と関数名を出す
# - exit status は変えない (trap の後 set -e が元の status で exit する)
# 行番号の精度: bash 5 (CI の ubuntu) は失敗した command の行 (複数行 command は先頭行)。
#   bash 3.2 (macOS /bin/bash) は 1 行の command なら同じ。 複数行 command は末尾行、
#   top-level の if / for / while の中の失敗はその複合 command の先頭か末尾の行になる。
#   既知の穴: bash 3.2 では top-level の `( ... )` subshell の失敗は無言のまま (5.x は出る)。
set -E
trap '_test_err_trap "$LINENO" "$BASH_COMMAND"' ERR
_test_err_trap() {
  [ "${BASH_SUBSHELL:-0}" -eq 0 ] || return 0
  local line="$1" fns="" i=1 nl=$'\n'
  local cmd="${2%%$nl*}"
  [ "$cmd" = "$2" ] || cmd="$cmd ..."
  # FUNCNAME[i] は BASH_LINENO[i] 行で呼ばれた — main の呼び出し行まで遡る
  while [ "$i" -lt $(( ${#FUNCNAME[@]} - 1 )) ]; do
    fns="${FUNCNAME[$i]}${fns:+ > $fns}"
    line="${BASH_LINENO[$i]}"
    i=$((i + 1))
  done
  echo "${0##*/}: FAIL at line $line${fns:+ (in $fns)}: $cmd" >&2
}
