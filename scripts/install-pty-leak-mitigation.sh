#!/bin/sh
# install-pty-leak-mitigation.sh — pty-leak-watch.sh watchdog + persistent bump LaunchDaemon を現ユーザに 1 コマンド install（--persist / --replace-agent / --replace-daemon、idempotent、macOS 限定）
# install-pty-leak-mitigation.sh — macOS Claude.app の pty leak 緩和を現ユーザに install。
# 原理 doc: conventions/macos-claude-app-pty-leak.md (= 説明・判断材料)。
# このスクリプト + pty-leak-watch.sh が段階 bump 数列 / LaunchDaemon plist /
# watchdog ロジック / 配線の SoT (= doc 側に複製しない、 drift 防止)。
#
# 既定 (sudo 不要): pty-leak-watch.sh を LaunchAgent として配線 (= 枯渇前に通知)。
#   bash scripts/install-pty-leak-mitigation.sh
# --persist (admin password 1 回): reboot 後も kern.tty.ptmx_max=958 を維持する
#   LaunchDaemon を追加 install (= 511 復帰の罠を解消)。
#   bash scripts/install-pty-leak-mitigation.sh --persist
# --replace-agent <label> / --replace-daemon <label>: 旧ラベルの install を置換
#   (= 個人ラベルからの移行用、 旧を bootout+rm してから新を入れる)。
#
# idempotent。 macOS 以外では no-op。 LaunchAgent は launchd 直起動なので watchdog
# 自身は pty を消費しない。 真の回収は Claude.app restart (doc 参照)。

case "$(uname -s)" in
  Darwin) ;;
  *) echo "[skip] pty-leak mitigation is macOS-only (got $(uname -s))"; exit 0 ;;
esac

PERSIST=0
OLD_AGENT=""
OLD_DAEMON=""
while [ $# -gt 0 ]; do
  case "$1" in
    --persist) PERSIST=1 ;;
    --replace-agent) OLD_AGENT="$2"; shift ;;
    --replace-daemon) OLD_DAEMON="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

SELF_DIR=$(cd "$(dirname "$0")" && pwd)
WATCH_SH="$SELF_DIR/pty-leak-watch.sh"
[ -f "$WATCH_SH" ] || { echo "[err] missing $WATCH_SH"; exit 1; }
chmod +x "$WATCH_SH"

UID_NUM=$(id -u)
AGENT_LABEL="com.claude-config.pty-leak-watch"
AGENT_PLIST="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

# 旧 agent を置換するなら先に撤去
if [ -n "$OLD_AGENT" ]; then
  launchctl bootout "gui/$UID_NUM/$OLD_AGENT" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$OLD_AGENT.plist"
  echo "[ok] removed old agent: $OLD_AGENT"
fi

cat > "$AGENT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$AGENT_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>$WATCH_SH</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/pty-leak-watch.err</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID_NUM/$AGENT_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$AGENT_PLIST"
echo "[ok] watchdog agent installed: $AGENT_LABEL (every 300s, warns at 85%/93%)"

if [ "$PERSIST" -eq 1 ]; then
  DAEMON_LABEL="com.claude-config.ptmx-bump"
  DEST="/Library/LaunchDaemons/$DAEMON_LABEL.plist"
  TMP="/tmp/$DAEMON_LABEL.plist"
  cat > "$TMP" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.claude-config.ptmx-bump</string>
  <key>RunAtLoad</key><true/>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string><string>-c</string>
    <string>cur=$(sysctl -n kern.tty.ptmx_max); for n in 512 514 518 526 542 574 638 766 894 958; do if [ "$n" -gt "$cur" ]; then sysctl kern.tty.ptmx_max=$n; fi; done</string>
  </array>
</dict>
</plist>
EOF
  CLEAN=""
  if [ -n "$OLD_DAEMON" ]; then
    CLEAN="launchctl bootout system/$OLD_DAEMON 2>/dev/null; rm -f /Library/LaunchDaemons/$OLD_DAEMON.plist; "
  fi
  osascript -e "do shell script \"${CLEAN}cp $TMP $DEST && chown root:wheel $DEST && chmod 644 $DEST && launchctl bootout system/$DAEMON_LABEL 2>/dev/null; launchctl bootstrap system $DEST\" with administrator privileges"
  echo "[ok] persistent bump daemon installed: $DAEMON_LABEL (raises ptmx_max to 958 at boot)"
fi

MAX=$(sysctl -n kern.tty.ptmx_max 2>/dev/null)
USED=$(lsof /dev/ptmx 2>/dev/null | grep -c /dev/ptmx)
echo "[info] current pty pool: $USED / $MAX"
echo "[note] leak の回収は Claude.app restart のみ。 watchdog/bump は壁の手前で稼ぐ緩和。"
