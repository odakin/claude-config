#!/usr/bin/env bash
# session-launch-check.sh — desktop の start_session で起こした worker が頼んだ model・effort で起きたかを app の記録で確かめ、 違えば直し方を出し、 直るまで go の SendMessage を止める (opt-in で掲示板を経ない worker の起動も止める)
#
# 正本: claude-config/hooks/session-launch-check.sh (setup.sh が ~/.claude/hooks/ に symlink、 hooks/settings-entries.json で
#       PreToolUse[mcp__.*__start_session] / PreToolUse[SendMessage] / PostToolUse[mcp__.*__(start_session|set_session_model|set_session_effort)] に登録)
#
# 動作の実体 = scripts/session-launch-check.py auto (mode は hook の入力で選ぶ。 述語・文面・限界は engine の冒頭)。
# 規約 = conventions/multi-session-coordination.md#desktop-start-model-cap
#
# 故障: engine 不在・python 不在・例外は通す (exit 0)。 止めるのは engine が exit 2 を返した時だけ。
# 環境変数: SESSION_LAUNCH_CHECK_DISABLE=1 (一時無効、 escape-hatch-guard の対象) / SESSION_LAUNCH_CHECK_ENGINE (test 用)
set -u
[ "${SESSION_LAUNCH_CHECK_DISABLE:-}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
if [ -n "${SESSION_LAUNCH_CHECK_ENGINE:-}" ]; then
  ENGINE="$SESSION_LAUNCH_CHECK_ENGINE"
else
  HERE="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}" 2>/dev/null)"
  ENGINE="$HERE/../scripts/session-launch-check.py"
fi
[ -f "$ENGINE" ] || exit 0
python3 "$ENGINE"
rc=$?
[ "$rc" = 2 ] && exit 2
exit 0
