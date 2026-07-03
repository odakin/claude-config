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
#   その config-dir で `CLAUDE_CONFIG_DIR=DIR claude auth login` 済が前提 (= 唯一の interactive 段。
#   workspace trust + RC 初回同意は install 時に自動 seed される、 下の設計 note 参照)。
#   --status / --uninstall でその 2 本目を対象にするときも同じ --label-suffix を渡す。
# --no-preflight: 起動前の 8 秒 probe を skip (= SessionStart hook 等から呼ぶとき、 install を
#   ブロックしない。 probe は auth/consent/version の hint 専用で install には不要、 KeepAlive が
#   自動復帰。 なお `claude --version` に依存する version gate は probe と独立なので --no-preflight
#   でも走る)。
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
# - install 時に workspace trust + RC 初回同意を config JSON へ自動 seed する (= headless-ready 化、
#   2026-07-02)。両者は interactive dialog 由来の `.claude.json` flag に過ぎず、 launchd の
#   non-TTY server は dialog を出せない — virgin config dir (= per-account pinned dir 新設直後)
#   だと OAuth 済でも "Workspace not trusted" → exit 1 → KeepAlive 永久 cycling の silent 死になる
#   (2026-07-02 実測 RCA、 conventions/remote-control-server.md#ts-workspace-trust)。
#   セキュリティ根拠: 「この dir を root に server を install する」 という user の明示行為が
#   trust dialog の確認内容そのものなので、 seed は consent の機械化であって bypass ではない。
#   seed 対象は指定 --dir 1 個のみ。 python3 不在 / JSON 破損時は fail-open で skip + warn
#   (= preflight の TRUST_NG backstop が拾う)。

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

# --- account 可視命名 (= multi-account 構成の picker / session 名曖昧性解消) -------------------
# --label-suffix (= account alias) がある場合、 server の表示名と spawn session 名 prefix に
# "<host-short>-<alias>" を焼く (例: myhost-alice)。 スマホの環境 picker と「最近の項目」 で
# どの account の server / session か一目で分かる (= 無いと同 host の 2 server が同名で並ぶ)。
# 古い CLI は flag 未対応の可能性があるため capability-gated (= 未対応なら従来 hostname 既定)。
RC_NAME_ARGS=""
if [ -n "$LABEL_SUFFIX" ]; then
  HOST_SHORT="$(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')"
  if [ -n "$HOST_SHORT" ]; then
    RC_HELP="$("$CLAUDE_BIN" remote-control --help 2>/dev/null || true)"
    printf '%s' "$RC_HELP" | grep -q -- '--name' \
      && RC_NAME_ARGS=" --name \"$HOST_SHORT-$LABEL_SUFFIX\""
    printf '%s' "$RC_HELP" | grep -q -- '--remote-control-session-name-prefix' \
      && RC_NAME_ARGS="$RC_NAME_ARGS --remote-control-session-name-prefix \"$HOST_SHORT-$LABEL_SUFFIX\""
  fi
fi

# --- headless-ready seed (= workspace trust + RC 初回同意、 設計 note は冒頭コメント) ---------
# probe より前に seed する (= virgin dir でも probe が trust を素通りして auth 検査まで届く)。
# config JSON の場所: CLAUDE_CONFIG_DIR 指定時は $CONFIG_DIR/.claude.json、 既定は ~/.claude.json。
CFG_JSON="$HOME/.claude.json"
[ -n "$CONFIG_DIR" ] && CFG_JSON="$CONFIG_DIR/.claude.json"
if command -v python3 >/dev/null 2>&1; then
  RC_DIR="$RC_DIR" CFG_JSON="$CFG_JSON" python3 - <<'PY' || echo "[warn] headless seed failed (fail-open); preflight TRUST warning below applies"
import json, os, sys, tempfile
cfg = os.environ["CFG_JSON"]; rc_dir = os.environ["RC_DIR"]
data = {}
if os.path.exists(cfg):
    try:
        with open(cfg) as f:
            data = json.load(f)
    except Exception:
        print(f"[warn] {cfg} unreadable JSON; not seeding (repair it, then re-run install)")
        sys.exit(0)
projects = data.setdefault("projects", {})
if rc_dir not in projects:
    # interactive 承認が作る entry と同じ field set (= 実機で検証済の shape、 欠け field 起因の
    # 未知挙動を避ける)。 既存 entry には trust flag だけ立てて他は触らない。
    projects[rc_dir] = {
        "allowedTools": [], "mcpContextUris": [], "mcpServers": {},
        "enabledMcpjsonServers": [], "disabledMcpjsonServers": [],
        "hasTrustDialogAccepted": True, "projectOnboardingSeenCount": 0,
        "hasClaudeMdExternalIncludesApproved": False,
        "hasClaudeMdExternalIncludesWarningShown": False,
        "hasCompletedProjectOnboarding": True,
    }
    changed = ["workspace-trust (new project entry)"]
else:
    changed = []
    if not projects[rc_dir].get("hasTrustDialogAccepted"):
        projects[rc_dir]["hasTrustDialogAccepted"] = True
        changed.append("workspace-trust")
if not data.get("remoteDialogSeen"):
    data["remoteDialogSeen"] = True
    changed.append("remote-consent")
if changed:
    d = os.path.dirname(cfg) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".claude.json.seed.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cfg)  # mkstemp = 0600 で原本と同等の秘匿
    print("[ok] headless-ready seed: " + ", ".join(changed) + " -> " + cfg)
PY
else
  echo "[warn] python3 not found; cannot seed workspace trust / RC consent."
  echo "       Run once manually: cd \"$RC_DIR\" && ${CONFIG_DIR:+CLAUDE_CONFIG_DIR=$CONFIG_DIR }claude   (accept trust)"
  echo "       then: claude remote-control   (answer y)"
fi

AUTH_NG=0; CONSENT_NG=0; VERSION_NG=0; TRUST_NG=0
# RC は v2.1.139 以上を要求 (= 公式 min。 旧 CLI で叩くと misleading な "Remote Control is not
# enabled for your account" が返り、 org policy blocker と誤読して support に issue を切りに走る
# trap の元 → 直接発火の runtime signal 〔`too old for Remote Control`〕 と、 probe を待たない
# deterministic な version parse の 2 経路で拾う。 parse 失敗は silent skip (= fail-open)。
MIN_VER="2.1.139"
CLAUDE_VER=$("$CLAUDE_BIN" --version 2>/dev/null | awk 'NR==1{for(i=1;i<=NF;i++)if($i~/^[0-9]+(\.[0-9]+)+$/){print $i;exit}}')
if [ -n "$CLAUDE_VER" ]; then
  # sort -V の highest が MIN_VER なら CLAUDE_VER < MIN_VER (= 昇順末尾 == MIN_VER ∧ 等しくない)
  HIGHEST=$(printf '%s\n%s\n' "$CLAUDE_VER" "$MIN_VER" | sort -V | tail -1)
  [ "$HIGHEST" = "$MIN_VER" ] && [ "$CLAUDE_VER" != "$MIN_VER" ] && VERSION_NG=1
fi
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
  # version 起因は VERSION_NG に分離 (= fix hint「claude update / PATH 修正」 が AUTH と別)。
  grep -qE "too old for Remote Control" "$TMPLOG" && VERSION_NG=1
  # RC の auth 失敗は複数文言 (= subscription 必須 / full-scope token 要 / org policy / 未 enable /
  # v2.1.53 misleading 変種 `is not enabled for your account` (= 「未 enable」 と別 wording) /
  # 新 CLI が ANTHROPIC_API_KEY 混入時に返す `requires claude.ai subscription auth`)。
  # preflight hint なので広めに拾う (= 取りこぼしても install は続行し log に実 error が出る)。
  # ⚠️ この subshell は ANTHROPIC_API_KEY を unset するので key 混入 error は本 probe 単独では
  # 発火しないが、 別経路 (= 手動 `claude remote-control`) の diagnostic に流用可能なので載せる。
  grep -qE "must be logged in|requires a claude\\.ai subscription|full-scope login token|disabled by your organization|not yet enabled for your account|is not enabled for your account|requires claude\\.ai subscription auth" "$TMPLOG" && AUTH_NG=1
  grep -q "Enable Remote Control?" "$TMPLOG" && CONSENT_NG=1
  # 通常は直前の seed が通すので発火しない backstop (= seed が python3 不在 / JSON 破損で skip
  # された時だけ出る)。 conventions/remote-control-server.md#ts-workspace-trust
  grep -q "Workspace not trusted" "$TMPLOG" && TRUST_NG=1
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
    <string>unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; ${CONFIG_EXPORT}export PATH="$CLAUDE_DIR:\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; cd "$RC_DIR" &amp;&amp; exec claude remote-control$RC_NAME_ARGS</string>
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
if [ "$VERSION_NG" = 1 ]; then
  # $CLAUDE_VER が空 (parse fail) の時は runtime signal (= `too old for Remote Control`) 経由で
  # ここに来ている。 その場合も同じ fix hint で十分。
  cat <<MSG

[warn] Claude Code CLI version is older than $MIN_VER (Remote Control minimum).
       Detected: ${CLAUDE_VER:-unknown} at $CLAUDE_BIN
       Fix options (any one):
         - claude update
         - ensure the newest install is first in PATH — macOS \`path_helper\` (\`/etc/zprofile\`)
           can push \`/usr/local/bin\` ahead of user-scoped \`~/.npm-global/bin\` even when
           \`.zshenv\` re-prepends; \`~/.zprofile\` re-prepend is one fix
         - remove the older install (typical suspect: \`/usr/local/bin/claude\` left by an
           old \`npm install -g\` under root)
       See conventions/remote-control-server.md "Troubleshooting" for details.
       The server self-heals within 60s after the CLI update — no re-install needed.
MSG
fi
if [ "$AUTH_NG" = 1 ]; then
  cat <<'MSG'

[warn] auth preflight failed: stored credential is not a claude.ai OAuth login.
       Run once in a terminal:   claude auth login
       (sign in with your claude.ai subscription account; API keys are not supported)
       If `ANTHROPIC_API_KEY` is set in your shell, `unset` it before `claude auth login`
       (RC requires claude.ai OAuth; an env-set API key overrides OAuth for the same shell).
       The launchd plist unsets it defensively so the running server is unaffected, but
       your install/verify shell can still be tripped by it. See conventions/
       remote-control-server.md "Troubleshooting" for details.
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
if [ "$TRUST_NG" = 1 ]; then
  cat <<MSG

[warn] workspace trust missing and automatic seed did not take effect
       (python3 missing or unreadable config JSON). The server will cycle with
       "Workspace not trusted" until fixed. Run once in a terminal:
         cd "$RC_DIR" && ${CONFIG_DIR:+CLAUDE_CONFIG_DIR=$CONFIG_DIR }claude
       and accept the trust dialog. The server self-heals within 60s.
       See conventions/remote-control-server.md#ts-workspace-trust
MSG
fi
echo
status
