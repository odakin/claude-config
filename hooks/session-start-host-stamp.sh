#!/usr/bin/env bash
# session-start-host-stamp.sh — SessionStart: 自己同定 stamp (host · surface = account · session) を注入 (I7)
#
# session の worker が「どのマシン・どの account で動いているか」 を会話ログに自己申告させる
# stamp (= conventions/multi-account-machine-surface.md の invariant I7)。 最初の返信の冒頭に
# 1 行出させることで、 bridge が死んで session が応答しなくなった後でも scroll-back を見るだけで
# 「どのマシンに行けば復旧できるか」 が分かる。
#
# 本体 logic は scripts/first_reply_stamp.py (Claude / Codex 共通の正本)。 本 file は薄い wrapper
# = 旧 path (~/.claude/hooks/session-start-host-stamp.sh) を保つための入口。 同じ機構の残り 2 本:
#   hooks/first-prompt-stamp.py      (UserPromptSubmit: 最初の prompt の直後に完全な stamp を再注入)
#   hooks/first-turn-stamp-check.py  (Stop: 最初の turn に stamp が一度も無ければ記録 / 差し戻し)
# 設計と実測 = conventions/multi-account-machine-surface.md#first-reply-stamp-mechanism
#
# fail-open: python3 不在・module 不在・例外は無出力で exit 0 (session を止めない)。

set -u
command -v python3 >/dev/null 2>&1 || exit 0

# symlink (~/.claude/hooks/ → <base>/claude-config/hooks/) を辿って repo を特定する
SELF="${BASH_SOURCE[0]}"
while [ -L "$SELF" ]; do
  LINK="$(readlink "$SELF")"
  case "$LINK" in /*) SELF="$LINK" ;; *) SELF="$(dirname "$SELF")/$LINK" ;; esac
done
ROOT="$(cd "$(dirname "$SELF")/.." 2>/dev/null && pwd)" || exit 0
MODULE="$ROOT/scripts/first_reply_stamp.py"
[ -f "$MODULE" ] || exit 0

python3 "$MODULE" hook claude session-start 2>/dev/null || true
exit 0
