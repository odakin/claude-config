#!/usr/bin/env bash
# agents-entrypoint-warn.test.sh — CLAUDE.md だけの repo で鳴り、 AGENTS.md を stage / track すると・opt-out で・CLAUDE.md が無いと鳴らない
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/agents-entrypoint-warn.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
fail=0
check() {   # check <name> <want: warn|silent>
    local err
    err="$(cd "$T/r" && warn_missing_agents_entrypoint 2>&1)"
    case "$2:$err" in
        warn:*"AGENTS.md が無い"*|silent:) echo "  PASS: $1" ;;
        *) echo "  FAIL: $1 (stderr: ${err:0:120})"; fail=1 ;;
    esac
}
mkdir -p "$T/r" && git -C "$T/r" init -q
printf 'x\n' > "$T/r/README.md" && git -C "$T/r" add README.md
check "CLAUDE.md の無い repo は鳴らない" silent
printf '# c\n' > "$T/r/CLAUDE.md" && git -C "$T/r" add CLAUDE.md
check "CLAUDE.md だけの repo は鳴る" warn
git -C "$T/r" config agent.entrypointWarn false
check "opt-out で鳴らない" silent
git -C "$T/r" config --unset agent.entrypointWarn
printf '# a\n' > "$T/r/AGENTS.md" && git -C "$T/r" add AGENTS.md
check "この commit で AGENTS.md を足すなら鳴らない" silent
echo "==== RESULT: $([ "$fail" -eq 0 ] && echo PASS || echo FAIL) ===="
exit $fail
