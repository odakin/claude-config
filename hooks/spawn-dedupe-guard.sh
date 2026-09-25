#!/usr/bin/env bash
# spawn-dedupe-guard.sh — 同じ依頼の worker を 2 つ起動させる chip (spawn_task) を止める + chip の台帳を付ける
#
# 正本: claude-config/hooks/spawn-dedupe-guard.sh (setup.sh が ~/.claude/hooks/ に symlink、 hooks/settings-entries.json で
#       PreToolUse[mcp__.*__spawn_task] と PostToolUse[mcp__.*__(spawn_task|dismiss_task)] に登録)
#
# 動作 (判定の実体 = scripts/spawn-dispatch-dedupe.py auto → scripts/lib/spawn_dedupe.py):
#   PreToolUse(spawn_task)    同じ依頼 (title の本体、 または extension が出す鍵) の chip を、 この session が出していて取り消しが
#                             「withdrawn」 で確認されていない / 同じ title・同じ鍵の session が生きている → exit 2 で止める
#                             (理由は stderr = model に届く。 本人が 2 つ目を求めた時は title か tldr に `[再起票]` → 注意だけ)
#   PostToolUse(spawn_task)   返りの task_id を session ごとの台帳 (~/.claude/state/spawn-dispatch/) に pending で記録
#   PostToolUse(dismiss_task) 返りで台帳を更新。 「already started」 なら「作り直さず SendMessage で訂正」 を注入
#
# Why: 「取り消し → 作り直し」 を 1 応答に並べると、 dismiss の already started を読む前に同じ title の chip が出て
#      同じ仕事が 2 session になる (本人は chip を十数秒で押す = 実測)。 規約 = conventions/multi-session-coordination.md#chip-correction-by-message
#
# 故障: engine 不在・python 不在・入力不足・例外は全部通す (exit 0)。 止めるのは条件が成り立った時だけ
#       (= 故障の合図を違反の合図と同じ値にしない)。 exit 2 で spawn_task が止まることは実測 (tool の結果が hook error になり task_id は付かない)。
#
# 環境変数: SPAWN_DEDUPE_DISABLE=1 (一時無効) / SPAWN_DEDUPE_ENGINE (test 用に engine を差し替え) /
#           CLAUDE_SESSIONS_DIR・CLAUDE_PROJECTS_DIR・SPAWN_DEDUPE_STATE_DIR・SPAWN_DEDUPE_EXT (engine の test 用)
set -u
[ "${SPAWN_DEDUPE_DISABLE:-}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
if [ -n "${SPAWN_DEDUPE_ENGINE:-}" ]; then
  ENGINE="$SPAWN_DEDUPE_ENGINE"
else
  HERE="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}" 2>/dev/null)"
  ENGINE="$HERE/../scripts/spawn-dispatch-dedupe.py"
fi
[ -f "$ENGINE" ] || exit 0
python3 "$ENGINE" auto
rc=$?
[ "$rc" = 2 ] && exit 2
exit 0
