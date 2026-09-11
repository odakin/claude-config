#!/usr/bin/env bash
# with-gnu-userland.test.sh — with-gnu-userland.sh の self-test (Homebrew の GNU userland が無い環境 = CI の ubuntu は SKIP)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Report the failing line and command instead of a silent exit 1.
. "$SCRIPT_DIR/lib/test-err-trap.sh"
WRAP="$SCRIPT_DIR/with-gnu-userland.sh"

# SKIP は「GNU 版が無い」 (exit 2 + 専用 message) のときだけ — 実行権限の欠落などを SKIP に化けさせない
rc=0
probe="$("$WRAP" true 2>&1)" || rc=$?
if [ "$rc" -eq 2 ] && [ "${probe#*no Homebrew GNU userland}" != "$probe" ]; then
  echo "SKIP: no Homebrew GNU userland on this machine (brew install coreutils)"
  exit 0
fi
[ "$rc" -eq 0 ]

# GNU の stat が先に来る (BSD の stat は --version を知らない)
case "$("$WRAP" stat --version 2>/dev/null)" in
  *"GNU coreutils"*) ;;
  *) echo "stat under the wrapper is not GNU" >&2; exit 1 ;;
esac
# 動かすのは GNU 版だけ — python3 の解決先は変わらない
[ "$("$WRAP" sh -c 'command -v python3' 2>/dev/null)" = "$(command -v python3)" ]
# exit status をそのまま返す
rc=0
"$WRAP" sh -c 'exit 3' 2>/dev/null || rc=$?
[ "$rc" -eq 3 ]
# --clean-env: 空の一時 HOME を渡し、 終わったら消す
out="$("$WRAP" --clean-env sh -c 'printf "%s %s" "$HOME" "$(ls -A "$HOME" | wc -l)"' 2>/dev/null)"
clean_home="${out% *}"
[ "$clean_home" != "$HOME" ]
[ "${out##* }" -eq 0 ]
[ ! -e "$clean_home" ]
# --clean-env: git の system config も読ませない (CI の git と同じ既定にする)
[ "$("$WRAP" --clean-env sh -c 'printf %s "${GIT_CONFIG_NOSYSTEM:-}"' 2>/dev/null)" = 1 ]

echo "with-gnu-userland tests passed"
