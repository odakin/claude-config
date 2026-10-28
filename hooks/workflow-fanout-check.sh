#!/usr/bin/env bash
# workflow-fanout-check.sh — Workflow を起こす前に script を空回しし、 agent の本数・波数・観点の分割・再開で cache が返る本数を出す (enforce の印があれば、 一度に走れる本数を越える並べ方は起動の前に本人に聞き、 宣言の無い観点の分割・再開を止める)
#
# 正本: claude-config/hooks/workflow-fanout-check.sh (setup.sh が ~/.claude/hooks/ に symlink、 hooks/settings-entries.json で
#       PreToolUse[^Workflow$] に登録)
#
# 動作の実体 = scripts/workflow-estimate.py --hook (述語・文面・限界は engine の冒頭)。
# 規約 = conventions/multi-session-coordination.md#workflow-fan-out
#
# 故障: engine 不在・python 不在・node 不在・例外は通す (exit 0)。 止めるのは engine が exit 2 を返した時だけ
#       (= enforce の印 ~/.claude/workflow-fanout-enforce.on か env WORKFLOW_FANOUT_ENFORCE=1 があり、 宣言の無い形のとき)。
#       本人に聞くのは engine が permissionDecision = ask を出した時 (同じ印があり、 一度に走れる本数を越える形。 宣言では通らない)。
# 環境変数: WORKFLOW_FANOUT_DISABLE=1 (一時無効) / WORKFLOW_FANOUT_ENGINE (test 用)
set -u
[ "${WORKFLOW_FANOUT_DISABLE:-}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
if [ -n "${WORKFLOW_FANOUT_ENGINE:-}" ]; then
  ENGINE="$WORKFLOW_FANOUT_ENGINE"
else
  HERE="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}" 2>/dev/null)"
  ENGINE="$HERE/../scripts/workflow-estimate.py"
fi
[ -f "$ENGINE" ] || exit 0
python3 "$ENGINE" --hook
rc=$?
[ "$rc" = 2 ] && exit 2
exit 0
