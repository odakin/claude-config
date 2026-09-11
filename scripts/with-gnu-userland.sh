#!/usr/bin/env bash
# with-gnu-userland.sh — macOS で Homebrew の GNU coreutils / sed / grep / findutils を PATH 先頭に差して command を走らせる (CI の ubuntu と同じ BSD/GNU 差を push 前に再現)
#
# 正本: claude-config/scripts/with-gnu-userland.sh
# 規約: conventions/hook-authoring.md#set-e-test-failure-report (push 前の GNU 実行)、
#       conventions/debugging-discipline.md#one-variable-per-arm (動かすのは GNU 版だけ)
#
# Usage:
#   scripts/with-gnu-userland.sh bash scripts/setup-codex.test.sh
#   scripts/with-gnu-userland.sh --clean-env bash scripts/setup-codex.test.sh
#     --clean-env: env -i で空の一時 HOME、 PATH = GNU + /usr/bin:/bin:/usr/sbin:/sbin、
#                  GIT_CONFIG_NOSYSTEM=1 (Apple Git の system config は init.defaultBranch=main
#                  を持つが CI の git は master — それを読むと branch 名を仮定した test が手元だけ通る)
#                  ⚠️ HOME を変えるので pip --user の site-packages も見えなくなる = python の
#                  selftest を含む run-all-checks 一式には使わない (shell test 単体向け)
#
# - 前置するのは <prefix>/opt/<pkg>/libexec/gnubin だけ (= Homebrew が unprefixed の GNU 名だけを
#   並べた dir)。 /opt/homebrew/bin を丸ごと前置すると python3 など無関係な binary まで動く
# - awk は動かさない (ubuntu の既定 awk は mawk で、 gawk ではない)
# - uname で BSD/GNU を選ぶ script は macOS 上では BSD 側を選ぶ = GNU 側の分岐はここでは試せない
# - GNU 版が 1 つも見つからなければ exit 2 (brew install coreutils [gnu-sed grep findutils])
set -euo pipefail

clean_env=0
if [ "${1:-}" = "--clean-env" ]; then clean_env=1; shift; fi
if [ "$#" -eq 0 ]; then
  echo "usage: ${0##*/} [--clean-env] <command...>" >&2
  exit 2
fi

gnu_path=""
for prefix in ${HOMEBREW_PREFIX:+"$HOMEBREW_PREFIX"} /opt/homebrew /usr/local; do
  for pkg in coreutils gnu-sed grep findutils; do
    dir="$prefix/opt/$pkg/libexec/gnubin"
    case ":$gnu_path:" in *":$dir:"*) continue ;; esac
    if [ -d "$dir" ]; then gnu_path="$gnu_path${gnu_path:+:}$dir"; fi
  done
done
if [ -z "$gnu_path" ]; then
  echo "${0##*/}: no Homebrew GNU userland found (brew install coreutils gnu-sed grep findutils)" >&2
  exit 2
fi
echo "${0##*/}: GNU first on PATH: $gnu_path" >&2

if [ "$clean_env" -eq 1 ]; then
  clean_home="$(mktemp -d)"
  trap 'rm -rf "$clean_home"' EXIT
  rc=0
  env -i HOME="$clean_home" PATH="$gnu_path:/usr/bin:/bin:/usr/sbin:/sbin" GIT_CONFIG_NOSYSTEM=1 \
    "$@" || rc=$?
  exit "$rc"
fi
export PATH="$gnu_path:$PATH"
exec "$@"
