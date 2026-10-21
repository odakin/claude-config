#!/usr/bin/env bash
# codex-headless-launch-check.sh — 掲示板の依頼の worker や盲検の判定 session を headless の codex exec で起こす Bash を止め、 Codex アプリに出る起こし方を出す (理由を書けば通す)
#
# 正本: claude-config/hooks/codex-headless-launch-check.sh (setup.sh が ~/.claude/hooks/ に symlink、 hooks/settings-entries.json で
#       PreToolUse[Bash] に登録)
#
# 動作の実体 = scripts/codex-headless-launch-check.py (述語・文面・限界は engine の冒頭)。
# 規約 = ai-collaboration board/CONTRACT.md#codex-worker-launch / cold-eyes-isolation.md §2-5
#
# 故障: engine 不在・python 不在・例外は通す (exit 0)。 止めるのは engine が exit 2 を返した時だけ。
# 環境変数: CODEX_HEADLESS_LAUNCH_CHECK_DISABLE=1 (一時無効) / CODEX_HEADLESS_LAUNCH_CHECK_ENGINE (test 用)
set -u
[ "${CODEX_HEADLESS_LAUNCH_CHECK_DISABLE:-}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
# cheap prefilter: the engine is started only when the command names codex
case "$INPUT" in *codex*) ;; *) exit 0 ;; esac
if [ -n "${CODEX_HEADLESS_LAUNCH_CHECK_ENGINE:-}" ]; then
  ENGINE="$CODEX_HEADLESS_LAUNCH_CHECK_ENGINE"
else
  HERE="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}" 2>/dev/null)"
  ENGINE="$HERE/../scripts/codex-headless-launch-check.py"
fi
[ -f "$ENGINE" ] || exit 0
printf '%s' "$INPUT" | python3 "$ENGINE"
rc=$?
[ "$rc" = 2 ] && exit 2
exit 0
