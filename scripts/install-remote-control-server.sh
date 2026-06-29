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
#   sh scripts/install-remote-control-server.sh [--dir DIR] [--config-dir DIR] [--label-suffix SUF] [--replace-agent LABEL]
#   sh scripts/install-remote-control-server.sh --status [--label-suffix SUF]
#   sh scripts/install-remote-control-server.sh --uninstall [--label-suffix SUF]
#
# --dir DIR: リモート生成セッションの root (既定: $HOME)。サーバーはこの dir で起動し、
#   リモートから作る新規セッションは全てここを cwd に持つ (= 既定 --spawn same-dir。
#   モバイル UI に「リポ選択」が出ても same-dir では cwd を変えない、 2026-06-12 実測)。
# --config-dir DIR + --label-suffix SUF: 別アカウントの認証ストア (CLAUDE_CONFIG_DIR=DIR) で
#   2 本目以降のサーバーを同一マシンに共存させる (= スマホから複数アカウントの新規セッションを
#   選べる)。別アカウントには必ず distinct な --label-suffix を付ける (= plist / log path 衝突回避)。
#   その config-dir で `CLAUDE_CONFIG_DIR=DIR claude auth login` 済 + 初回同意 y が前提。
#   --status / --uninstall でその 2 本目を対象にするときも同じ --label-suffix を渡す。
# --no-preflight: 起動前の 8 秒 probe を skip (= SessionStart hook 等から呼ぶとき、 install を
#   ブロックしない。 probe は auth/consent の hint 専用で install には不要、 KeepAlive が自動復帰)。
# --replace-agent LABEL: 旧 (個人) ラベルの登録を bootout + rm してから入れる移行用。
#
# ⚠️ 設計上の注意 (= 変更する人へ):
# - 起動は non-TTY のまま直接 exec する。script(1) 等で PTY を与えると launchd の
#   stdin (/dev/null) EOF が端末 close として claude に届き graceful exit →
#   KeepAlive で 60 秒周期の接続/切断 cycling になる (2026-06-12 実測 RCA)。
# - 認証 (claude.ai OAuth) や初回同意が無いとサーバーは起動拒否で即 exit するが、
#   KeepAlive + ThrottleInterval が 60 秒間隔で retry するため、解消後に自動で生き返る
#   (= preflight 失敗でも install は完了させる)。
# - preflight / plist の両方で ANTHROPIC_API_KEY と CLAUDE_CODE_OAUTH_TOKEN を unset する。
#   RC は claude.ai OAuth 必須で、これらが env に居ると inference-only credential を掴んで
#   起動拒否される (= 公式 docs troubleshooting)。launchd は通常これらを継承しないが
#   `launchctl setenv` 等で混入し得るので防御的に消す (= 未 set なら no-op)。
# - plist は PATH 依存の `exec claude` を使う (= 起動毎に PATH 再解決するので claude の
#   再 install / 移動に強い)。絶対バイナリパスは焼き込まない (= 移動で stale 化し永久
#   cycling する弱点を避ける、 = 公開ツールとして多様な install を壊さない)。preflight が
#   解決した claude の dir を PATH 先頭に足すので、非標準 install 先でも起動する (= preflight
#   と plist の解決経路を一致させる、 標準 install 先なら重複するだけで無害)。

case "$(uname -s)" in
  Darwin) ;;
  *) echo "[skip] Remote Control server install is macOS-only (got $(uname -s))"; exit 0 ;;
esac

LABEL_BASE="com.claude-config.remote-control-server"
UID_N=$(id -u)
RC_DIR="$HOME"
OLD_AGENT=""
MODE="install"
CONFIG_DIR=""
LABEL_SUFFIX=""
NO_PREFLIGHT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) RC_DIR="$2"; shift ;;
    --config-dir) CONFIG_DIR="$2"; shift ;;
    --label-suffix) LABEL_SUFFIX="$2"; shift ;;
    --no-preflight) NO_PREFLIGHT=1 ;;
    --replace-agent) OLD_AGENT="$2"; shift ;;
    --status) MODE="status" ;;
    --uninstall) MODE="uninstall" ;;
    *) echo "usage: $0 [--dir DIR] [--config-dir DIR] [--label-suffix SUF] [--no-preflight] [--replace-agent LABEL] [--status|--uninstall]" >&2; exit 2 ;;
  esac
  shift
done

# --config-dir DIR: 別アカウントの認証ストア (CLAUDE_CONFIG_DIR) を使う = 1 マシンに複数
#   アカウントのサーバーを共存させるとき。空 = 既定 (~/.claude.json)。別アカウントには
#   distinct な --label-suffix を付けて label 衝突 (= plist / log path 共有) を避ける。
LABEL="$LABEL_BASE"
[ -n "$LABEL_SUFFIX" ] && LABEL="$LABEL_BASE.$LABEL_SUFFIX"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/$LABEL.log"

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
if [ -n "$CONFIG_DIR" ]; then
  case "$CONFIG_DIR" in
    *[\&\<\>\"]*) echo "[error] --config-dir contains XML-unsafe characters (& < > \"): $CONFIG_DIR" >&2; exit 1 ;;
  esac
  mkdir -p "$CONFIG_DIR"
fi

CLAUDE_BIN="$HOME/.local/bin/claude"
[ -x "$CLAUDE_BIN" ] || CLAUDE_BIN="$(command -v claude || true)"
[ -n "$CLAUDE_BIN" ] || { echo "[error] claude binary not found (native install expected at ~/.local/bin/claude)" >&2; exit 1; }

AUTH_NG=0; CONSENT_NG=0
# --no-preflight: 8 秒 probe を skip (= SessionStart hook 等から呼ぶとき。 probe は auth/consent の
# hint を出すだけで install 自体には不要 — KeepAlive が解消後 60s で自動復帰する)。
if [ "$NO_PREFLIGHT" != "1" ]; then
  echo "[preflight] probing 'claude remote-control' for ~8s..."
  TMPLOG=$(mktemp)
  ( unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; [ -n "$CONFIG_DIR" ] && export CLAUDE_CONFIG_DIR="$CONFIG_DIR"; cd "$RC_DIR" && exec "$CLAUDE_BIN" remote-control ) >"$TMPLOG" 2>&1 &
  PRE_PID=$!
  sleep 8
  kill "$PRE_PID" 2>/dev/null
  wait "$PRE_PID" 2>/dev/null
  # RC の auth 失敗は複数文言 (= subscription 必須 / full-scope token 要 / org policy / 未 enable)。
  # preflight hint なので広めに拾う (= 取りこぼしても install は続行し log に実 error が出る)。
  grep -qE "must be logged in|requires a claude.ai subscription|full-scope login token|disabled by your organization|not yet enabled for your account" "$TMPLOG" && AUTH_NG=1
  grep -q "Enable Remote Control?" "$TMPLOG" && CONSENT_NG=1
  rm -f "$TMPLOG"
fi

# --- install (idempotent) -----------------------------------------------------
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
CLAUDE_DIR=$(dirname "$CLAUDE_BIN")   # preflight 解決先を plist PATH 先頭へ (= 非標準 install 先対応)
case "$CLAUDE_DIR" in
  *[\&\<\>\"]*) echo "[error] claude install dir contains XML-unsafe characters: $CLAUDE_DIR" >&2; exit 1 ;;
esac
CONFIG_EXPORT=""
[ -n "$CONFIG_DIR" ] && CONFIG_EXPORT="export CLAUDE_CONFIG_DIR=\"$CONFIG_DIR\"; "

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
    <string>unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; ${CONFIG_EXPORT}export PATH="$CLAUDE_DIR:\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; cd "$RC_DIR" &amp;&amp; exec claude remote-control</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

# ⚠️ bootout は非同期 — busy な稼働サービス (= active polling 中の remote-control) は即死しない。
# 即 bootstrap すると残留参照で "Bootstrap failed: 5: Input/output error" になりサービスが落ちたまま
# になる (2026-06-29 RCA: 稼働中サーバーの再 install で実発生)。 → 完全に消えるまで poll してから
# bootstrap、 さらに bootstrap 自体も数回 retry (各 retry 前に bootout 再試行) で race に強くする。
launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null
i=0
while launchctl print "gui/$UID_N/$LABEL" >/dev/null 2>&1 && [ "$i" -lt 10 ]; do
  sleep 1
  i=$((i + 1))
done
bs_ok=0
j=0
while [ "$j" -lt 5 ]; do
  if launchctl bootstrap "gui/$UID_N" "$PLIST" 2>/dev/null; then bs_ok=1; break; fi
  launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null
  sleep 1
  j=$((j + 1))
done
[ "$bs_ok" = 1 ] || { echo "[error] launchctl bootstrap failed after retries" >&2; exit 1; }
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
