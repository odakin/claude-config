#!/bin/bash
# gmail-mcp-reauth.sh — 多アカウント Gmail MCP の OAuth (再)認証エンジン (generic、 layer 1 が実行実体。 runbook = conventions/gmail-mcp-multiaccount.md)
#
# Usage: gmail-mcp-reauth.sh <config-repo-dir> [account|all]
#   <config-repo-dir>: your private config repo (accounts.yaml + secrets/ を持つ dir)
#   account: any alias with a ~/.gmail-mcp/<alias>/ directory (default: personal)
#   "all" re-auths every alias found under ~/.gmail-mcp/
# 呼び出しは private repo 側の 2 行 wrapper (reauth.sh) 経由を推奨 — engine は
# git pull で更新されるので、 credential を触る script として pull 時の diff review 推奨。
#
# Flow:
#   1. Reads OAuth client credentials from ~/.gmail-mcp/<account>/gcp-oauth.keys.json
#   2. Opens browser with Google OAuth consent URL (state nonce + PKCE S256 付き)
#   3. Captures auth code via local HTTP server (auto) or URL paste (fallback) —
#      どちらの経路も state 一致を検証する
#   4. Exchanges auth code (+ code_verifier) for tokens and saves to credentials.json
#   5. Kills the corresponding MCP server process so Claude Code auto-restarts it
#
# Security:
#   - Tokens are stored in your PRIVATE config repo, git-crypt ENCRYPTED
#     (~/.gmail-mcp/<account>/credentials.json is a symlink to the repo's
#     secrets/gmail-<account>-credentials.json; this script writes THROUGH the
#     symlink so the canonical gets the new token — commit + push it afterwards)
#   - credentials.json has 0600 permissions (owner-only read/write)
#   - Expired credentials are backed up (max 3 kept, chmod 600)
#   - OAuth keys (client_id/secret) stay in ~/.gmail-mcp/ only
#   - All values passed to Python via environment variables (no shell interpolation)
#   - Account alias is validated to a plain token (path traversal / pgrep regex
#     injection 防止)
#   - OAuth callback は state nonce 一致のみ受理 + PKCE S256 (偽 callback 先着 /
#     code 横取りの両方を塞ぐ)。手動 URL 貼付 fallback でも state を検証
#   - accounts.yaml から expected email を解決できない reauth は既定で中止
#     (= 認証後 getProfile 照合の空振り防止。意図的に進むなら REAUTH_ALLOW_UNVERIFIED=1)

set -euo pipefail

REPO_DIR="${1:-}"
if [ -z "$REPO_DIR" ] || [ ! -d "$REPO_DIR" ]; then
    echo "Usage: $0 <config-repo-dir> [account|all]" >&2
    echo "Error: config repo dir が不正: '$REPO_DIR'" >&2
    exit 1
fi
REPO_DIR="$(cd "$REPO_DIR" && pwd)"

# Resolve the expected email for an account alias from accounts.yaml (git-crypt
# decrypted locally). Empty if accounts.yaml is locked/unreadable — the caller
# treats empty as a hard stop unless REAUTH_ALLOW_UNVERIFIED=1 (the getProfile
# post-auth verification is the compensating control for the OAuth flow, so a
# silent skip would disarm it). reauth.sh is plaintext in git, so emails are
# NEVER hardcoded here — they are read at runtime from the encrypted accounts.yaml.
get_expected_email() {
    local acct="$1"
    local ACCOUNTS_YAML="$REPO_DIR/accounts.yaml"
    [ -f "$ACCOUNTS_YAML" ] || return 0
    ACCT="$acct" ACCOUNTS_YAML="$ACCOUNTS_YAML" python3 -c "
import yaml, os, sys
try:
    d = yaml.safe_load(open(os.environ['ACCOUNTS_YAML']))
except Exception:
    sys.exit(0)
for entry in (d or {}).get('gmail_mcp', []):
    for a in entry.get('accounts', []) or []:
        if a.get('alias') == os.environ['ACCT']:
            print(a.get('email','')); sys.exit(0)
" 2>/dev/null
}

reauth_account() {
    local ACCOUNT="$1"

    # Alias must be a plain token — it is interpolated into filesystem paths and
    # a pgrep -f pattern below. Reject traversal (`..`), ERE metachars (`|` の
    # alternation は中間枝が無制約になり任意プロセス kill に化ける)、その他の
    # surprise (confused-deputy な呼び出しへの防御)。
    case "$ACCOUNT" in
        *[!A-Za-z0-9_-]*|"")
            echo "Error: invalid account alias '$ACCOUNT' (allowed: letters, digits, _, -)" >&2
            return 1
            ;;
    esac

    local BASE_DIR="$HOME/.gmail-mcp"
    local ACCOUNT_DIR="$BASE_DIR/$ACCOUNT"
    export OAUTH_KEYS="$ACCOUNT_DIR/gcp-oauth.keys.json"
    local CREDS_FILE="$ACCOUNT_DIR/credentials.json"

    # Validate
    if [ ! -d "$ACCOUNT_DIR" ]; then
        echo "Error: Account directory not found: $ACCOUNT_DIR"
        echo "Available accounts:"
        ls -d "$BASE_DIR"/*/ 2>/dev/null | xargs -I{} basename {}
        return 1
    fi

    if [ ! -f "$OAUTH_KEYS" ]; then
        echo "Error: OAuth keys not found: $OAUTH_KEYS"
        return 1
    fi

    # Extract client credentials via environment variables (no shell interpolation)
    CLIENT_ID=$(python3 -c "import json,os; print(json.load(open(os.environ['OAUTH_KEYS']))['installed']['client_id'])" 2>/dev/null) || {
        echo "Error: Failed to read client_id from $OAUTH_KEYS"
        return 1
    }
    export CLIENT_ID
    # 代入と export を分離 (export VAR=$(...) は python の失敗 exit code を mask する)
    CLIENT_SECRET=$(python3 -c "import json,os; print(json.load(open(os.environ['OAUTH_KEYS']))['installed']['client_secret'])" 2>/dev/null) || {
        echo "Error: Failed to read client_secret from $OAUTH_KEYS"
        return 1
    }
    export CLIENT_SECRET

    # Resolve expected email (for login_hint + post-auth verification). Empty =
    # accounts.yaml locked / missing / no entry / PyYAML 欠落 — どれも認証後の
    # account 一致検証 (getProfile 照合) を空振りさせるので、既定では中止する。
    local EXPECTED_EMAIL=""
    EXPECTED_EMAIL=$(get_expected_email "$ACCOUNT") || true
    export REAUTH_EXPECTED_EMAIL="$EXPECTED_EMAIL"

    local HINT=""
    if [ -z "$EXPECTED_EMAIL" ]; then
        if [ "${REAUTH_ALLOW_UNVERIFIED:-0}" != "1" ]; then
            echo "❌ accounts.yaml から alias '$ACCOUNT' の期待 email を解決できません" >&2
            echo "   (accounts.yaml が locked / 不在 / entry 無し / PyYAML 欠落)。" >&2
            echo "   認証後のアカウント一致検証 (getProfile 照合) が空振りになるため中止します。" >&2
            echo "   → git-crypt unlock + accounts.yaml の entry を確認してから再実行。" >&2
            echo "   → 意図して未検証で進む場合のみ REAUTH_ALLOW_UNVERIFIED=1 を付ける。" >&2
            return 1
        fi
        echo "⚠️  REAUTH_ALLOW_UNVERIFIED=1: アカウント検証なしで続行 (アカウント選び間違いは検出されない)"
    else
        HINT="&login_hint=$(REAUTH_EXPECTED_EMAIL="$EXPECTED_EMAIL" python3 -c "import urllib.parse,os;print(urllib.parse.quote(os.environ['REAUTH_EXPECTED_EMAIL']))")"
        echo "対象アカウント: $EXPECTED_EMAIL (login_hint で事前選択 + 認証後に検証)"
    fi

    local SCOPES="https://www.googleapis.com/auth/gmail.settings.basic+https://www.googleapis.com/auth/gmail.modify"

    # Determine redirect URI: try port-based (auto capture) first, fall back to plain localhost
    # GCP OAuth allows http://localhost with any port for native apps
    local LISTEN_PORT=8370
    local REDIRECT="http://localhost:${LISTEN_PORT}"

    # Backup existing credentials (keep max 3). The glob is ".expired*" (no dot
    # before the wildcard) so the timestamp-less ".expired" form left over from
    # the original reauth design also gets included in rotation — the dotted glob
    # used previously left a timestamp-less .expired untouched on personal/
    # forever (observed 2026-04-27 audit).
    # ⚠️ cp (not mv): since 2026-07-25 (D) migration CREDS_FILE is a symlink into
    # the gmail-mcp-config repo. mv would rename the symlink away and the token
    # write below would then create a machine-local real file, silently forking
    # state from the repo canonical. cp follows the symlink (content backup) and
    # leaves the link intact so the write goes through to the canonical.
    local BACKUP_FILE=""
    if [ -f "$CREDS_FILE" ]; then
        BACKUP_FILE="${CREDS_FILE}.expired.$(date +%Y%m%d%H%M%S)"
        cp -p "$CREDS_FILE" "$BACKUP_FILE"
        chmod 600 "$BACKUP_FILE"   # cp -p は旧 mode を保存する — token backup は必ず 0600 に矯正
        ls -t "${CREDS_FILE}.expired"* 2>/dev/null | tail -n +4 | xargs rm -f 2>/dev/null
        echo "Backed up existing credentials"
    fi
    export REAUTH_BACKUP_FILE="$BACKUP_FILE"

    # CSRF / code-injection 対策 (純 stdlib):
    #   state nonce  = callback が「この実行の consent の応答」であることの検証。
    #                  不一致の request (drive-by page / 同一マシン他プロセスの偽
    #                  callback) は 400 で無視して本物を待ち続ける。
    #   PKCE (S256)  = 万一 code が横取りされても、code_verifier を知らない攻撃者は
    #                  token 交換できない。
    local STATE PKCE_VERIFIER PKCE_CHALLENGE
    STATE="$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")"
    PKCE_VERIFIER="$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")"
    PKCE_CHALLENGE="$(PKCE_VERIFIER="$PKCE_VERIFIER" python3 -c "
import hashlib, base64, os
v = os.environ['PKCE_VERIFIER'].encode()
print(base64.urlsafe_b64encode(hashlib.sha256(v).digest()).rstrip(b'=').decode())")"
    export REAUTH_STATE="$STATE"
    export REAUTH_PKCE_VERIFIER="$PKCE_VERIFIER"

    # Build auth URL (login_hint pre-selects the right account in the consent UI)
    local AUTH_URL="https://accounts.google.com/o/oauth2/auth?client_id=${CLIENT_ID}&redirect_uri=${REDIRECT}&response_type=code&scope=${SCOPES}&access_type=offline&prompt=consent&state=${STATE}&code_challenge=${PKCE_CHALLENGE}&code_challenge_method=S256${HINT}"

    echo ""
    echo "=== Gmail MCP Re-authentication: $ACCOUNT ==="
    echo ""

    # Try auto-capture with local HTTP server
    export REAUTH_REDIRECT="$REDIRECT"
    export REAUTH_CREDS_FILE="$CREDS_FILE"
    export REAUTH_AUTH_URL="$AUTH_URL"
    export REAUTH_PORT="$LISTEN_PORT"
    export REAUTH_ACCOUNT="$ACCOUNT"

    # Print URL on stdout so the user (or an agent driving the script) can click it
    # manually if `open` fails to foreground the browser. Observed 2026-04-27:
    # `open` exit=0 but the browser didn't surface, and the URL had to be
    # reconstructed from gcp-oauth.keys.json by hand.
    echo ""
    echo "If the browser does not open, click this URL manually:"
    echo "  $AUTH_URL"
    echo ""

    python3 << 'PYEOF'
import json, urllib.request, urllib.parse, time, os, stat, subprocess, sys
from http.server import HTTPServer, BaseHTTPRequestHandler

auth_code = None
auth_error = None
port = int(os.environ['REAUTH_PORT'])
expected_state = os.environ['REAUTH_STATE']

def open_browser(url):
    # ブラウザ起動は best-effort — 失敗しても URL は stdout に印字済みなので手動で開ける。
    # (`open` 不在の非 macOS 環境で FileNotFoundError = OSError が port-in-use と
    # 誤診されないよう、listener 生成の except とは分離する。)
    try:
        subprocess.Popen([('open' if sys.platform == 'darwin' else 'xdg-open'), url],
                         stdout=subprocess.DEVNULL)
    except Exception as e:
        print(f"⚠️  ブラウザ自動起動失敗 ({e}) — 上に印字した URL を手動で開いてください")

class CallbackHandler(BaseHTTPRequestHandler):
    def _respond(self, status, message):
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

    def do_GET(self):
        global auth_code, auth_error
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        # state nonce 一致が最初の gate — 不一致 (drive-by / 偽 callback / favicon 等の
        # 無関係 request) は 400 で無視し、loop 側で本物の callback を待ち続ける。
        if params.get('state', [None])[0] != expected_state:
            self._respond(400, '❌ state 不一致 — このリクエストは無視されました。')
            return
        if params.get('error', [None])[0]:
            auth_error = params['error'][0]
            self._respond(200, '❌ 認証が拒否またはキャンセルされました。ターミナルを確認してください。')
            return
        code = params.get('code', [None])[0]
        if code:
            auth_code = code
            self._respond(200, '✅ 認証成功！このタブは閉じてOKです。')
        else:
            self._respond(400, '❌ 認証コードが取得できませんでした。')

    def log_message(self, format, *args):
        pass

server = None
try:
    server = HTTPServer(('127.0.0.1', port), CallbackHandler)
except OSError:
    print(f"ポート {port} が使用中。手動モードに切り替えます。")

if server is not None:
    # per-request timeout を短くして loop する (1 リクエストで打ち切らない):
    # 偽/無関係 request が先着しても本物の callback を deadline まで待てる。
    server.timeout = 5
    deadline = time.time() + 300
    open_browser(os.environ['REAUTH_AUTH_URL'])
    acct = os.environ.get('REAUTH_ACCOUNT', '?')
    print(f"[{acct}] ブラウザで承認してください — Google アカウント選択画面では必ず {acct} に対応するアカウントを選ぶこと（自動キャプチャ待機中: port {port}, timeout 300s）...")

    while auth_code is None and auth_error is None and time.time() < deadline:
        server.handle_request()
    server.server_close()

    if auth_error:
        print(f"Error: 認証が完了しませんでした ({auth_error})")
        sys.exit(1)
    if not auth_code:
        print("Error: タイムアウトまたはコールバック失敗")
        sys.exit(1)
else:
    # Port in use — fall back to manual
    redirect_plain = "http://localhost"
    auth_url_plain = os.environ['REAUTH_AUTH_URL'].replace(
        f"http://localhost:{port}", redirect_plain)
    os.environ['REAUTH_REDIRECT'] = redirect_plain

    open_browser(auth_url_plain)
    print("ブラウザで承認後、'localhost refused to connect' の画面で")
    print("アドレスバーの URL をコピーして貼り付けてください:")
    url = input("URL: ").strip()
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    # 貼付経路でも state を検証 — phishing された/別フローの URL はここで落ちる
    if params.get('state', [None])[0] != expected_state:
        print("Error: state 不一致 — 貼られた URL はこの実行の認証フローのものではありません")
        sys.exit(1)
    auth_code = params.get('code', [None])[0]
    if not auth_code:
        print("Error: 認証コードを取得できません")
        sys.exit(1)

print("認証コード取得。トークン交換中...")

# Exchange code for tokens (PKCE: code_verifier は consent 時の code_challenge と対)
data = urllib.parse.urlencode({
    'code': auth_code,
    'client_id': os.environ['CLIENT_ID'],
    'client_secret': os.environ['CLIENT_SECRET'],
    'redirect_uri': os.environ['REAUTH_REDIRECT'],
    'grant_type': 'authorization_code',
    'code_verifier': os.environ['REAUTH_PKCE_VERIFIER'],
}).encode()

req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, method='POST')
try:
    resp = urllib.request.urlopen(req)
    tokens = json.loads(resp.read())

    if 'error' in tokens:
        print(f"Error: {tokens['error']} - {tokens.get('error_description','')}")
        sys.exit(1)

    tokens['expiry_date'] = int((time.time() + tokens.get('expires_in', 3600)) * 1000)

    creds_path = os.environ['REAUTH_CREDS_FILE']
    # (D) 移行後 creds_path は repo canonical への symlink。open/chmod は symlink を
    # 辿って canonical に書く (= 意図どおり。書いた後は repo の commit + push が必要)。
    # os.open(…, 0o600) で born-0600 にする (open('w') は umask 依存で一瞬 644 の
    # file が生まれてから chmod する窓があった)。
    fd = os.open(creds_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(tokens, f, indent=2)

    os.chmod(creds_path, stat.S_IRUSR | stat.S_IWUSR)   # 既存 file だった場合の mode 矯正

    rt_expires = tokens.get('refresh_token_expires_in', 'unknown')
    if isinstance(rt_expires, int):
        rt_info = f"{rt_expires / 86400:.0f} days"
    else:
        rt_info = str(rt_expires)

    print(f"✅ トークン保存: {creds_path}")
    print(f"   refresh_token: {'yes' if 'refresh_token' in tokens else 'NO'}")
    print(f"   refresh_token寿命: {rt_info}")

    # Verify the authenticated account == expected (prevents the silent
    # account-swap bug: choosing the wrong Google account in the consent screen
    # would otherwise save a wrong-account token under this alias, undetected —
    # exactly what happened to cis on 2026-04-27, observed 2026-06-01).
    expected = os.environ.get('REAUTH_EXPECTED_EMAIL', '').strip()
    actual = ''
    prof_err = None
    for _attempt in range(3):
        try:
            prof_req = urllib.request.Request(
                'https://gmail.googleapis.com/gmail/v1/users/me/profile',
                headers={'Authorization': 'Bearer ' + tokens['access_token']})
            actual = json.loads(urllib.request.urlopen(prof_req).read()).get('emailAddress', '')
            break
        except Exception as e:
            prof_err = e
            time.sleep(2)
    if not actual:
        # 検証不能のまま token を残すのは guard の空振り — 声高に表示する
        print(f"   🚨 account 検証不能 (getProfile 3 回失敗: {prof_err})")
        print(f"      token は保存されたが正しいアカウントか未確認 — reauth を再実行して検証を通すこと")
    if actual:
        if expected and actual.lower() != expected.lower():
            print(f"❌ アカウント不一致: 期待 {expected} / 実際 {actual}")
            print(f"   間違ったアカウントを選択しました。保存した token を破棄します。")
            print(f"   再実行して、アカウント選択画面で必ず {expected} を選んでください。")
            # ⚠️ symlink 対応: 誤 token は既に canonical (symlink 先) に書かれている。
            # os.remove(symlink) は link だけ消して誤 token を repo に残すので、
            # backup から実体へ復元する (backup 不在時のみ実体を削除)。
            real = os.path.realpath(creds_path)
            backup = os.environ.get('REAUTH_BACKUP_FILE', '').strip()
            try:
                if backup and os.path.exists(backup):
                    with open(backup, 'rb') as bf, open(real, 'wb') as rf:
                        rf.write(bf.read())
                    print(f"   旧 token を backup から復元: {backup}")
                else:
                    os.remove(real)
            except OSError as e:
                print(f"   🚨 誤 token の破棄/復元に失敗 ({e}) — 手動で {real} を処置してください (backup: {backup or 'なし'})")
            sys.exit(2)
        print(f"   ✅ authenticated as: {actual}" + ("（期待と一致）" if expected else ""))
    if os.path.islink(creds_path):
        print("   ⚠️ token は repo canonical に書かれました → config repo を commit + push (= 他マシンへ配布)")

except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP Error {e.code}: {body}")
    sys.exit(1)
PYEOF

    local py_exit=$?
    if [ $py_exit -ne 0 ]; then
        echo "Re-authentication failed for $ACCOUNT"
        return 1
    fi

    # Kill MCP server process so Claude Code auto-restarts it with new credentials
    kill_mcp_server "$ACCOUNT"

    echo ""
    echo "=== $ACCOUNT: 完了 ==="
    echo ""
}

kill_mcp_server() {
    local ACCOUNT="$1"

    # Find MCP server processes that reference this account's credentials
    # (ACCOUNT は reauth_account 冒頭で plain token に検証済 = pattern 注入不能)
    local PIDS
    PIDS=$(pgrep -f "gmail-mcp/${ACCOUNT}/credentials" 2>/dev/null || true)

    if [ -n "$PIDS" ]; then
        echo "MCP サーバーを再起動: $ACCOUNT (PIDs: $PIDS)"
        echo "$PIDS" | xargs kill 2>/dev/null || true
        echo "Claude Code が自動的に MCP サーバーを再起動します。"
    else
        echo "実行中の MCP サーバーなし ($ACCOUNT)。"
    fi
}

# Main
ACCOUNT="${2:-personal}"

if [ "$ACCOUNT" = "all" ]; then
    echo "=== 全アカウント再認証 ==="
    for d in "$HOME/.gmail-mcp"/*/; do
        acct="$(basename "$d")"
        [ -e "$d/gcp-oauth.keys.json" ] || continue   # account dir 以外 (backup 等) を skip
        reauth_account "$acct" || echo "⚠️  $acct 失敗。次へ..."
    done
    echo "=== 全アカウント完了 ==="
else
    reauth_account "$ACCOUNT"
fi
