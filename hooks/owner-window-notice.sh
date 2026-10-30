#!/usr/bin/env bash
# owner-window-notice.sh — PreToolUse(SendMessage / send_message / Bash の board.py note・request・handover): 宛先が user の直接話している session なら、 送る前に 1 行知らせる (止めない)
#
# 正本: claude-config/hooks/owner-window-notice.sh (setup.sh と pull の post-merge が ~/.claude/hooks/ に symlink、
#       hooks/settings-entries.json で PreToolUse[SendMessage|mcp__ccd_session_mgmt__send_message|Bash] に登録)
#
# 動作の実体 = scripts/owner-window-notice.py (宛先の解決・user の最後の発言の判定・1 時間に 1 回・文面・校正は engine の冒頭)。
# Bash では `board.py` を含む command だけを engine に渡す (他の Bash は python を起動しない)。
# 規約 = conventions/multi-session-coordination.md#owner-driven-window-no-funnel
#
# 止めない: engine は additionalContext だけを出し、 permissionDecision を出さない。 この入口も常に exit 0。
# 故障: engine 不在・python 不在・例外は黙って通す。
# 環境変数: OWNER_WINDOW_NOTICE_DISABLE=1 (一時無効) / OWNER_WINDOW_NOTICE_ENGINE (test 用)
set -u
[ "${OWNER_WINDOW_NOTICE_DISABLE:-}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
case "$INPUT" in
  *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*)
    case "$INPUT" in *board.py*) ;; *) exit 0 ;; esac ;;
esac
if [ -n "${OWNER_WINDOW_NOTICE_ENGINE:-}" ]; then
  ENGINE="$OWNER_WINDOW_NOTICE_ENGINE"
else
  HERE="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}" 2>/dev/null)"
  ENGINE="$HERE/../scripts/owner-window-notice.py"
fi
[ -f "$ENGINE" ] || exit 0
printf '%s' "$INPUT" | python3 "$ENGINE" 2>/dev/null
exit 0
