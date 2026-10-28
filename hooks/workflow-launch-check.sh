#!/usr/bin/env bash
# workflow-launch-check.sh — Fable の session からの Workflow は agent ごとの model の指定を求め、 週の切替の前に使い切る workflow は切替時刻で agent を止める
#
# 正本: claude-config/hooks/workflow-launch-check.sh (setup.sh が ~/.claude/hooks/ に symlink、 hooks/settings-entries.json で
#       PreToolUse[*] に登録 = 切替時刻を過ぎた後の subagent の tool 呼び出しを止めるため全 tool を見る)
#
# 動作の実体 = scripts/session-launch-check.py --workflow-gate (述語・文面・限界は engine の冒頭)。 PREMIUM_GATE の機械だけで効く。
# 速い道: tool が Workflow でなく、 切替時刻の記録 (<state>/*.stop-at.json) も無ければ python を起動しない。
# 規約 = conventions/multi-session-coordination.md#workflow-agent-model
#
# 故障: engine 不在・python 不在・例外は通す (exit 0)。 止めるのは engine が exit 2 を返した時だけ。
# 環境変数: SESSION_LAUNCH_CHECK_DISABLE=1 (一時無効、 session-launch-check.sh と共通) / SESSION_LAUNCH_CHECK_ENGINE (test 用) /
#           SESSION_LAUNCH_STATE_DIR (test 用)
set -u
[ "${SESSION_LAUNCH_CHECK_DISABLE:-}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
input="$(cat)"
state="${SESSION_LAUNCH_STATE_DIR:-$HOME/.claude/state/session-launch}"
case "$input" in
  *'"tool_name":"Workflow"'*|*'"tool_name": "Workflow"'*) ;;
  *) ls "$state"/*.stop-at.json >/dev/null 2>&1 || exit 0 ;;
esac
if [ -n "${SESSION_LAUNCH_CHECK_ENGINE:-}" ]; then
  ENGINE="$SESSION_LAUNCH_CHECK_ENGINE"
else
  HERE="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}" 2>/dev/null)"
  ENGINE="$HERE/../scripts/session-launch-check.py"
fi
[ -f "$ENGINE" ] || exit 0
printf '%s' "$input" | python3 "$ENGINE" --workflow-gate
rc=$?
[ "$rc" = 2 ] && exit 2
exit 0
