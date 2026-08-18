#!/usr/bin/env bash
# gmail-mcp-engines.test.sh — gmail MCP engine 2 本 (reauth / install-runtime-links) の hermetic self-test
#
# ネットワーク・ブラウザ・実 credential を一切使わない: 入力検証 (alias)、
# unverified-reauth gate、ciphertext/空 canonical guard、backup・dir の permission
# 矯正、冪等性、bash 3.2 + set -u の空配列 guard のみを検証する。
# OAuth flow 本体 (state/PKCE の live 動作) は次回の実 reauth で人間が確認する領域。

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REAUTH="$HERE/gmail-mcp-reauth.sh"
INSTALL="$HERE/gmail-mcp-install-runtime-links.sh"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
ng()  { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# engine は $HOME/.gmail-mcp を見る — 実環境を汚さないよう HOME を隔離
FAKE_HOME="$TMP/home"
mkdir -p "$FAKE_HOME"

mode_of() { python3 -c "import os,sys;print(oct(os.stat(sys.argv[1]).st_mode & 0o777))" "$1"; }

REPO="$TMP/repo"
mkdir -p "$REPO/secrets"

# ---------- T1: reauth — alias validation ----------
echo "=== T1: reauth — 不正 alias の拒否 (traversal / ERE metachar / dot) ==="
for bad in '../evil' 'a|b' 'a b' '.d' 'a/x' '..'; do
    out="$(HOME="$FAKE_HOME" bash "$REAUTH" "$REPO" "$bad" 2>&1)"; rc=$?
    if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q "invalid account alias"; then
        ok "reject '$bad'"
    else
        ng "should reject '$bad' (rc=$rc, out=$out)"
    fi
done
# 正常 alias は validation を通過して次の check (dir 不在) に進む
out="$(HOME="$FAKE_HOME" bash "$REAUTH" "$REPO" good_alias-1 2>&1)"; rc=$?
if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q "Account directory not found"; then
    ok "valid alias passes validation (fails later on missing dir)"
else
    ng "valid alias should reach dir check (rc=$rc, out=$out)"
fi

# ---------- T2: reauth — unverified gate ----------
echo "=== T2: reauth — expected email 解決不能なら中止 (guard 空振り防止) ==="
mkdir -p "$FAKE_HOME/.gmail-mcp/testacct"
printf '{"installed":{"client_id":"cid.example","client_secret":"cs-example"}}' \
    > "$FAKE_HOME/.gmail-mcp/testacct/gcp-oauth.keys.json"
# accounts.yaml は意図的に置かない → expected email 解決不能
out="$(HOME="$FAKE_HOME" bash "$REAUTH" "$REPO" testacct 2>&1)"; rc=$?
if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q "REAUTH_ALLOW_UNVERIFIED"; then
    ok "unverified reauth refused"
else
    ng "unverified reauth should be refused (rc=$rc, out=$out)"
fi
if printf '%s' "$out" | grep -q "accounts.google.com"; then
    ng "auth URL must not be built/printed before the gate"
else
    ok "no auth URL before gate (browser flow not reached)"
fi

# ---------- T3: reauth — client_secret 欠落は即 fail (masking 防止) ----------
echo "=== T3: reauth — keys file に client_secret 欠落 → 明示 fail ==="
printf '{"installed":{"client_id":"cid.example"}}' \
    > "$FAKE_HOME/.gmail-mcp/testacct/gcp-oauth.keys.json"
out="$(HOME="$FAKE_HOME" bash "$REAUTH" "$REPO" testacct 2>&1)"; rc=$?
if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q "client_secret"; then
    ok "missing client_secret fails loudly"
else
    ng "missing client_secret should fail loudly (rc=$rc, out=$out)"
fi

# ---------- T4: install — ciphertext canonical → abort ----------
echo "=== T4: install — ciphertext canonical → abort ==="
printf '\000GITCRYPT\000junk' > "$REPO/secrets/gmail-alpha-credentials.json"
printf '{"installed":{"client_id":"x"}}' > "$REPO/secrets/gmail-gcp-oauth.keys.json"
out="$(HOME="$FAKE_HOME" bash "$INSTALL" "$REPO" 2>&1)"; rc=$?
if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q "ciphertext"; then
    ok "ciphertext aborts"
else
    ng "ciphertext should abort (rc=$rc, out=$out)"
fi
if [ ! -e "$FAKE_HOME/.gmail-mcp/alpha/credentials.json" ]; then
    ok "no link created for ciphertext canonical"
else
    ng "link must not be created for ciphertext canonical"
fi

# ---------- T5: install — happy path + permission 矯正 + backup ----------
echo "=== T5: install — 実 file 置換 + backup 0600 + dir 0700 + canonical 0600 ==="
printf '{"refresh_token":"new"}' > "$REPO/secrets/gmail-alpha-credentials.json"
chmod 644 "$REPO/secrets/gmail-alpha-credentials.json"
mkdir -p "$FAKE_HOME/.gmail-mcp/alpha"
printf '{"refresh_token":"old-machine-local"}' > "$FAKE_HOME/.gmail-mcp/alpha/credentials.json"
chmod 644 "$FAKE_HOME/.gmail-mcp/alpha/credentials.json"   # 弱 mode の実 file が居る状況を再現
out="$(HOME="$FAKE_HOME" bash "$INSTALL" "$REPO" 2>&1)"; rc=$?
[ $rc -eq 0 ] && ok "install succeeds" || ng "install should succeed (rc=$rc, out=$out)"
if [ -L "$FAKE_HOME/.gmail-mcp/alpha/credentials.json" ]; then
    ok "runtime is a symlink"
else
    ng "runtime should be a symlink"
fi
backup="$(ls "$FAKE_HOME/.gmail-mcp/alpha/credentials.json.premigration."* 2>/dev/null | head -1)"
if [ -n "$backup" ] && [ "$(mode_of "$backup")" = "0o600" ]; then
    ok "premigration backup exists with 0600 (was 644)"
else
    ng "premigration backup missing or wrong mode (backup=$backup)"
fi
[ "$(mode_of "$REPO/secrets/gmail-alpha-credentials.json")" = "0o600" ] \
    && ok "canonical corrected to 0600" || ng "canonical should be 0600"
[ "$(mode_of "$REPO/secrets")" = "0o700" ] \
    && ok "secrets dir corrected to 0700" || ng "secrets dir should be 0700"
[ "$(mode_of "$FAKE_HOME/.gmail-mcp")" = "0o700" ] \
    && ok "~/.gmail-mcp corrected to 0700" || ng "~/.gmail-mcp should be 0700"
[ "$(mode_of "$FAKE_HOME/.gmail-mcp/alpha")" = "0o700" ] \
    && ok "account dir corrected to 0700" || ng "account dir should be 0700"

# ---------- T6: install — 冪等 (再実行で変更なし) ----------
echo "=== T6: install — 冪等 ==="
out="$(HOME="$FAKE_HOME" bash "$INSTALL" "$REPO" 2>&1)"; rc=$?
if [ $rc -eq 0 ] && printf '%s' "$out" | grep -q "変更なし"; then
    ok "second run is a no-op"
else
    ng "second run should be a no-op (rc=$rc, out=$out)"
fi

# ---------- T7: install — 空 canonical → abort ----------
echo "=== T7: install — 空 canonical → abort ==="
: > "$REPO/secrets/gmail-beta-credentials.json"
out="$(HOME="$FAKE_HOME" bash "$INSTALL" "$REPO" 2>&1)"; rc=$?
if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q "不在または空"; then
    ok "empty canonical aborts"
else
    ng "empty canonical should abort (rc=$rc, out=$out)"
fi
rm "$REPO/secrets/gmail-beta-credentials.json"

# ---------- T8: install — 不正 alias の canonical 名は skip (非致命) ----------
echo "=== T8: install — 不正 alias 名の canonical を skip ==="
touch "$REPO/secrets/gmail-a b-credentials.json"
out="$(HOME="$FAKE_HOME" bash "$INSTALL" "$REPO" 2>&1)"; rc=$?
if [ $rc -eq 0 ] && printf '%s' "$out" | grep -q "alias が不正"; then
    ok "weird alias skipped, run continues"
else
    ng "weird alias should be skipped non-fatally (rc=$rc, out=$out)"
fi
rm "$REPO/secrets/gmail-a b-credentials.json"

# ---------- T9: install — credentials 0 件 (初回 setup) でも keys link は張る ----------
echo "=== T9: install — 0 account でも keys のみ link (bash 3.2 空配列 guard) ==="
REPO2="$TMP/repo2"
mkdir -p "$REPO2/secrets"
printf '{"installed":{"client_id":"x"}}' > "$REPO2/secrets/gmail-gcp-oauth.keys.json"
FAKE_HOME2="$TMP/home2"; mkdir -p "$FAKE_HOME2"
out="$(HOME="$FAKE_HOME2" bash "$INSTALL" "$REPO2" 2>&1)"; rc=$?
if [ $rc -eq 0 ] && [ -L "$FAKE_HOME2/.gmail-mcp/gcp-oauth.keys.json" ]; then
    ok "zero-account run links client keys"
else
    ng "zero-account run should link client keys (rc=$rc, out=$out)"
fi

# ---------- T10: install — 既存 0644 backup / legacy dir の self-heal ----------
echo "=== T10: install — 既存 backup / legacy 残骸の mode self-heal (0600/0700) ==="
# 旧版 engine が残した状況を再現: 0644 の premigration/expired backup + 755 の legacy dir
legacy="$FAKE_HOME/.gmail-mcp/ATTIC-legacy"
mkdir -p "$legacy"
chmod 755 "$legacy"
printf '{"old":"keys"}' > "$legacy/oauth-keys.json"
chmod 644 "$legacy/oauth-keys.json"
printf '{"old":"token"}' > "$FAKE_HOME/.gmail-mcp/alpha/credentials.json.expired.20200101000000"
chmod 644 "$FAKE_HOME/.gmail-mcp/alpha/credentials.json.expired.20200101000000"
out="$(HOME="$FAKE_HOME" bash "$INSTALL" "$REPO" 2>&1)"; rc=$?
[ $rc -eq 0 ] && ok "install succeeds with legacy debris present" \
    || ng "install should succeed (rc=$rc, out=$out)"
[ "$(mode_of "$legacy/oauth-keys.json")" = "0o600" ] \
    && ok "legacy loose secret healed to 0600" || ng "legacy loose secret should be 0600"
[ "$(mode_of "$FAKE_HOME/.gmail-mcp/alpha/credentials.json.expired.20200101000000")" = "0o600" ] \
    && ok "expired backup healed to 0600" || ng "expired backup should be 0600"
[ "$(mode_of "$legacy")" = "0o700" ] \
    && ok "legacy dir healed to 0700" || ng "legacy dir should be 0700"
# 再実行 (= 既に clean) では self-heal は無音
out="$(HOME="$FAKE_HOME" bash "$INSTALL" "$REPO" 2>&1)"; rc=$?
if [ $rc -eq 0 ] && ! printf '%s' "$out" | grep -q "mode 矯正"; then
    ok "self-heal silent when already clean"
else
    ng "self-heal should be silent on clean rerun (rc=$rc, out=$out)"
fi

# ---------- T11: reauth — consent URL を browser 起動の argv に載せない ----------
echo "=== T11: reauth — browser 起動の argv hygiene (URL は env 経由、 ps 採取窓なし) ==="
# port 8370 を先に塞いで手動 mode に落とす (= listener の 300s 待ちを踏まずに
# open_browser 呼び出し → input() EOF 即死、 で決定的に終わる)。stub browser が
# argv と REAUTH_OPEN_URL env を記録する。
STUBS="$TMP/stubs"; RECORD="$TMP/record"
mkdir -p "$STUBS" "$RECORD"
for stub in osascript xdg-open open; do
    cat > "$STUBS/$stub" <<EOF
#!/bin/bash
printf '%s\n' "\$@" > "$RECORD/argv"
printf '%s\n' "\${REAUTH_OPEN_URL:-}" > "$RECORD/env_url"
exit 0
EOF
    chmod +x "$STUBS/$stub"
done
# best-effort で 8370 を占有 (既に使用中でも手動 mode になるので OK)
python3 -c "
import http.server, socketserver
try:
    s = socketserver.TCPServer(('127.0.0.1', 8370), http.server.BaseHTTPRequestHandler)
    s.serve_forever()
except OSError:
    pass
" &
PORT_HOG=$!
sleep 1
printf '{"installed":{"client_id":"cid.example","client_secret":"cs-example"}}' \
    > "$FAKE_HOME/.gmail-mcp/testacct/gcp-oauth.keys.json"
out="$(HOME="$FAKE_HOME" PATH="$STUBS:$PATH" REAUTH_ALLOW_UNVERIFIED=1 \
       bash "$REAUTH" "$REPO" testacct </dev/null 2>&1)" || true
kill "$PORT_HOG" 2>/dev/null; wait "$PORT_HOG" 2>/dev/null
# stub は Popen で fire-and-forget — record file を最大 5 秒 poll
for _i in 1 2 3 4 5 6 7 8 9 10; do
    [ -s "$RECORD/env_url" ] && break
    sleep 0.5
done
if [ -f "$RECORD/argv" ]; then
    ok "browser stub invoked"
else
    ng "browser stub was not invoked (out=$out)"
fi
if [ "$(uname)" = "Darwin" ]; then
    if [ -f "$RECORD/argv" ] && ! grep -q "accounts.google.com" "$RECORD/argv"; then
        ok "macOS: consent URL not in browser argv"
    else
        ng "macOS: consent URL must not appear in argv (argv=$(cat "$RECORD/argv" 2>/dev/null))"
    fi
    if grep -q "accounts.google.com" "$RECORD/env_url" 2>/dev/null \
       && grep -q "state=" "$RECORD/env_url" 2>/dev/null \
       && grep -q "code_challenge=" "$RECORD/env_url" 2>/dev/null; then
        ok "macOS: URL (with state + code_challenge) delivered via env"
    else
        ng "macOS: env REAUTH_OPEN_URL should carry the full URL (env_url=$(cat "$RECORD/env_url" 2>/dev/null))"
    fi
else
    # Linux: xdg-open は URL を argv に取る以外の入口が無い = 文書化済みの残余。
    # ここでは「URL が browser に渡っている」 挙動だけを確認する (SKIP 相当の注記)。
    if [ -f "$RECORD/argv" ] && grep -q "accounts.google.com" "$RECORD/argv"; then
        ok "linux: xdg-open received URL (argv residual is documented, not asserted away)"
    else
        ng "linux: xdg-open should receive the URL (argv=$(cat "$RECORD/argv" 2>/dev/null))"
    fi
fi

echo ""
echo "== gmail-mcp-engines: PASS=$PASS FAIL=$FAIL =="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
