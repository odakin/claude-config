#!/usr/bin/env bash
# busy-worker-stop-check.sh — PreToolUse(Bash / stop_session / archive_session): 動いている worker session を止める操作を、 本人が発言する前の 1 回目は止める (聞いて答えをもらった後の同じ操作は通す)
#
# 正本: claude-config/hooks/busy-worker-stop-check.sh (setup.sh が ~/.claude/hooks/ に symlink、 hooks/settings-entries.json で
#       PreToolUse[Bash|mcp__.*__(stop_session|archive_session)] に登録)
#
# 動作の実体 = scripts/busy-worker-stop-check.py (述語・文面・限界は engine の冒頭)。 Bash では `claude … stop|kill|rm` を
# 含む command だけを engine に渡す (他の Bash は python を起動しない)。
# 規約 = conventions/multi-session-coordination.md#ask-before-stopping-a-busy-worker
#
# 故障: engine 不在・python 不在・例外は通す (exit 0)。
# 環境変数: BUSY_WORKER_STOP_CHECK_DISABLE=1 (一時無効、 escape-hatch-guard の対象) / BUSY_WORKER_STOP_CHECK_ENGINE (test 用)
set -u
[ "${BUSY_WORKER_STOP_CHECK_DISABLE:-}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
case "$INPUT" in
  *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*)
    printf '%s' "$INPUT" | grep -Eq 'claude[^"]*\b(stop|kill|rm)\b' || exit 0 ;;
esac
if [ -n "${BUSY_WORKER_STOP_CHECK_ENGINE:-}" ]; then
  ENGINE="$BUSY_WORKER_STOP_CHECK_ENGINE"
else
  HERE="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}" 2>/dev/null)"
  ENGINE="$HERE/../scripts/busy-worker-stop-check.py"
fi
[ -f "$ENGINE" ] || exit 0
printf '%s' "$INPUT" | python3 "$ENGINE"
rc=$?
[ "$rc" = 2 ] && exit 2
exit 0
