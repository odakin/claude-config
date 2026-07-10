#!/bin/sh
# pty-leak-watch.sh — macOS Claude.app pty leak watchdog（LaunchAgent、枯渇前に macOS 通知、conventions/macos-claude-app-pty-leak.md）
# pty-leak-watch.sh — macOS の pty プール (kern.tty.ptmx_max) が Claude.app の
# /dev/ptmx leak で枯渇する前に通知する watchdog。
# 正本 doc: conventions/macos-claude-app-pty-leak.md
# install:  scripts/install-pty-leak-mitigation.sh が LaunchAgent として配線する。
#
# LaunchAgent から launchd 直起動で回るので、 この script 自身は pty を確保しない
# (= leak を増やさない)。 枯渇 (max/max) してからでは sysctl bump も restart 操作も
# pty を取れず deadlock になるため、 「壁の手前」 で通知して Claude.app restart を促す。

MAX=$(sysctl -n kern.tty.ptmx_max 2>/dev/null)
USED=$(lsof /dev/ptmx 2>/dev/null | grep -c /dev/ptmx)
LOG="$HOME/Library/Logs/pty-leak-watch.log"

[ -z "$MAX" ] && exit 0
[ "$MAX" -gt 0 ] 2>/dev/null || exit 0

PCT=$(( USED * 100 / MAX ))
TS=$(date '+%Y-%m-%d %H:%M:%S')

# 最大保持プロセス (= 通常 Claude)
TOP=$(lsof /dev/ptmx 2>/dev/null | grep /dev/ptmx | awk '{print $1, $2}' | sort | uniq -c | sort -rn | head -1 | sed 's/^ *//')

# log は 70% 以上のときだけ (= 肥大防止、 leak の時系列を残す)
if [ "$PCT" -ge 70 ]; then
  echo "$TS used=$USED max=$MAX pct=${PCT}% top=[$TOP]" >> "$LOG"
fi

# 通知: 93% で危機 / 85% で警告
if [ "$PCT" -ge 93 ]; then
  osascript -e "display notification \"pty ${USED}/${MAX} (${PCT}%) 枯渇寸前 — 今すぐ Claude.app restart を。枯渇後は復旧操作も pty を取れず不能\" with title \"pty leak 危機\" sound name \"Sosumi\"" >/dev/null 2>&1
elif [ "$PCT" -ge 85 ]; then
  osascript -e "display notification \"pty ${USED}/${MAX} (${PCT}%) — 作業の区切りで Claude.app restart を\" with title \"pty leak 警告\" sound name \"Basso\"" >/dev/null 2>&1
fi

exit 0
