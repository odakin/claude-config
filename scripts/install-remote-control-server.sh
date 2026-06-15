#!/bin/sh
# install-remote-control-server.sh — Claude Code Remote Control サーバーモードを launchd で常駐化。
# 原理 doc: conventions/remote-control-server.md (= 要件・落とし穴・troubleshooting)。
# このスクリプトが plist / label / KeepAlive 設計の SoT (= doc 側に複製しない、 drift 防止)。
#
# 効果: `claude remote-control` (= スマホ / claude.ai/code から自マシンに新規セッションを
# 生やせる待ち受けサーバー) を login 時自動起動 + 自動復帰 (再起動 / ネットワーク断 / crash /
# 未認証) で常駐させる。常時起動しているマシンで 1 回実行すれば以後手入れ不要。
#
# usage (idempotent):
#   sh scripts/install-remote-control-server.sh [--dir DIR] [--replace-agent LABEL]
#   sh scripts/install-remote-control-server.sh --status
#   sh scripts/install-remote-control-server.sh --uninstall
#
# --dir DIR: リモート生成セッションの root (既定: $HOME)。サーバーはこの dir で起動し、
#   リモートから作る新規セッションは全てここを cwd に持つ (= 既定 --spawn same-dir。
#   モバイル UI に「リポ選択」が出ても same-dir では cwd を変えない、 2026-06-12 実測)。
# --replace-agent LABEL: 旧 (個人) ラベルの登録を bootout + rm してから入れる移行用。
#
# ⚠️ 設計上の注意 (= 変更する人へ):
# - 起動は non-TTY のまま直接 exec する。script(1) 等で PTY を与えると launchd の
#   stdin (/dev/null) EOF が端末 close として claude に届き graceful exit →
#   KeepAlive で 60 秒周期の接続/切断 cycling になる (2026-06-12 実測 RCA)。
# - 認証 (claude.ai OAuth) や初回同意が無いとサーバーは起動拒否で即 exit するが、
#   KeepAlive + ThrottleInterval が 60 秒間隔で retry するため、解消後に自動で生き返る
#   (= preflight 失敗でも install は完了させる)。
# - plist には PATH 依存の `claude` でなく preflight で解決した $CLAUDE_BIN の絶対パスを
#   焼き込む。さもないと claude が plist の PATH 外 (= 非標準 install 先) にある環境で
#   preflight だけ通り launchd が永久 cycling する (native install の ~/.local/bin は
#   auto-update を跨いで安定するので絶対パス焼き込みで問題ない)。

case "$(uname -s)" in
  Darwin) ;;
  *) echo "[skip] Remote Control server install is macOS-only (got $(uname -s))"; exit 0 ;;
esac

LABEL="com.claude-config.remote-control-server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/$LABEL.log"
UID_N=$(id -u)
RC_DIR="$HOME"
OLD_AGENT=""
MODE="install"

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) RC_DIR="$2"; shift ;;
    --replace-agent) OLD_AGENT="$2"; shift ;;
    --status) MODE="status" ;;
    --uninstall) MODE="uninstall" ;;
    *) echo "usage: $0 [--dir DIR] [--replace-agent LABEL] [--status|--uninstall]" >&2; exit 2 ;;
  esac
  shift
done

status() {
  if launchctl print "gui/$UID_N/$LABEL" >/dev/null 2>&1; then
    launchctl print "gui/$UID_N/$LABEL" | grep -E 'state =|pid =|last exit code' | sed 's/^[[:space:]]*/  /'
    echo "  log: $LOG"
    [ -f "$LOG" ] && { echo "  --- log tail ---"; tail -5 "$LOG" | sed 's/^/  /'; }
  else
    echo "not installed ($LABEL)"
  fi
}

case "$MODE" in
  status) status; exit 0 ;;
  uninstall)
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null
    rm -f "$PLIST"
    echo "[ok] uninstalled ($LABEL)"
    exit 0 ;;
esac

# --- preflight ----------------------------------------------------------------
[ -d "$RC_DIR" ] || { echo "[error] --dir not found: $RC_DIR" >&2; exit 1; }
case "$RC_DIR" in
  *[\&\<\>\"]*) echo "[error] --dir contains XML-unsafe characters (& < > \"): $RC_DIR" >&2; exit 1 ;;
esac

CLAUDE_BIN="$HOME/.local/bin/claude"
[ -x "$CLAUDE_BIN" ] || CLAUDE_BIN="$(command -v claude || true)"
[ -n "$CLAUDE_BIN" ] || { echo "[error] claude binary not found (native install expected at ~/.local/bin/claude)" >&2; exit 1; }

echo "[preflight] probing 'claude remote-control' for ~8s..."
TMPLOG=$(mktemp)
( cd "$RC_DIR" && exec "$CLAUDE_BIN" remote-control ) >"$TMPLOG" 2>&1 &
PRE_PID=$!
sleep 8
kill "$PRE_PID" 2>/dev/null
wait "$PRE_PID" 2>/dev/null
AUTH_NG=0; CONSENT_NG=0
grep -q "must be logged in" "$TMPLOG" && AUTH_NG=1
grep -q "Enable Remote Control?" "$TMPLOG" && CONSENT_NG=1
rm -f "$TMPLOG"

# --- install (idempotent) -----------------------------------------------------
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

if [ -n "$OLD_AGENT" ]; then
  launchctl bootout "gui/$UID_N/$OLD_AGENT" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/$OLD_AGENT.plist"
  echo "[ok] removed old agent ($OLD_AGENT)"
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; cd "$RC_DIR" &amp;&amp; exec "$CLAUDE_BIN" remote-control</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null
sleep 1
launchctl bootstrap "gui/$UID_N" "$PLIST" || { echo "[error] launchctl bootstrap failed" >&2; exit 1; }
launchctl kickstart "gui/$UID_N/$LABEL" 2>/dev/null

echo "[ok] installed ($LABEL, dir=$RC_DIR)"
if [ "$AUTH_NG" = 1 ]; then
  cat <<'MSG'

[warn] auth preflight failed: stored credential is not a claude.ai OAuth login.
       Run once in a terminal:   claude auth login
       (sign in with your claude.ai subscription account; API keys are not supported)
       The server self-heals within 60s after login — no re-install needed.
MSG
fi
if [ "$CONSENT_NG" = 1 ]; then
  cat <<'MSG'

[warn] first-run consent pending: run `claude remote-control` once in a terminal
       and answer y to "Enable Remote Control?" (persisted; the launchd server
       then self-heals within 60s — no re-install needed).
MSG
fi
echo
status
