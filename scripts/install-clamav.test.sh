#!/usr/bin/env bash
# install-clamav.test.sh — install-clamav.sh の test (偽の brew と freshclam で、 足りないものだけ揃う・既存の設定を触らない・freshclam の失敗の値をそのまま返す・定義が古いと出す・openssl@4 の署名の不具合なら固定の版に入れ替え、 homebrew-core の版が変わったら外して試す)
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL="$SELF_DIR/install-clamav.sh"
pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
P="$T/prefix"
mkdir -p "$T/bin" "$P/bin" "$P/etc/clamav" "$P/var/lib/clamav"
# 偽の brew: install は clamscan / freshclam を置く。 BUGGY_CORE=1 のとき homebrew-core の clamav は openssl@4 で組まれた版 (= $T/ossl4)、
# local/clamav-pin/clamav は openssl@3 の版 (= ossl4 を消す)。 info は $T/core-v・core-r の版を返す
cat > "$T/bin/brew" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$T/brew.all"
last="\${!#}"
case "\$1" in
  --prefix) echo "$P" ;;
  --repository) [ -d "$T/tap" ] && echo "$T/tap" ;;
  tap-new) mkdir -p "$T/tap" ;;
  untap) rm -rf "$T/tap" ;;
  info) printf '{"v":"%s","r":"%s"}\n' "\$(cat "$T/core-v" 2>/dev/null || echo 1.5.4)" "\$(cat "$T/core-r" 2>/dev/null || echo 1)" ;;
  install)
    echo "install \$last" >> "$T/brew.log"
    if [ "\$last" = local/clamav-pin/clamav ]; then rm -f "$T/ossl4"
    elif [ "\${BUGGY_CORE:-0}" = 1 ]; then touch "$T/ossl4"
    else rm -f "$T/ossl4"; fi
    mkdir -p "$P/opt/clamav/lib"
    if [ -f "$T/ossl4" ]; then ssl=openssl@4; else ssl=openssl@3; fi
    printf '\\0\\0/x/opt/%s/lib/libcrypto.dylib\\0' "\$ssl" > "$P/opt/clamav/lib/libclamav.12.dylib"
    cat > "$P/bin/clamscan" <<'INNER'
#!/usr/bin/env bash
[ "\$1" = --version ] && { echo ClamAV 9.9.9; exit 0; }
[ -f "\$STATE_DIR/ossl4" ] && { echo "LibClamAV Error: Malformed database"; exit 2; }
exit 0
INNER
    cat > "$P/bin/freshclam" <<'INNER'
#!/usr/bin/env bash
echo run >> "\$FRESHCLAM_LOG"
[ -n "\${FRESHCLAM_RC:-}" ] && exit "\$FRESHCLAM_RC"
echo "ERROR: NULL X509 store"
if [ -f "\$STATE_DIR/ossl4" ]; then
  echo "WARNING: [LibClamAV] cli_loadinfo: Incorrect digital signature"
  echo "ERROR: Database test FAILED."
  exit 8
fi
touch "\$FRESHCLAM_DB/main.cvd" "\$FRESHCLAM_DB/daily.cld"
INNER
    chmod +x "$P/bin/clamscan" "$P/bin/freshclam"
    printf 'Example\nDatabaseMirror x\n' > "$P/etc/clamav/freshclam.conf.sample"
    ;;
esac
EOF
cat > "$T/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=""
while [ $# -gt 0 ]; do [ "$1" = -o ] && { out="$2"; shift; }; shift; done
printf 'class Clamav < Formula\n  bottle do\n    sha256 arm64_tahoe: "x"\n  end\nend\n' > "$out"
EOF
cat > "$T/bin/plutil" <<'EOF'
#!/usr/bin/env bash
j="$(cat)"
case "$2" in
  *versions.stable) printf '%s' "$j" | sed 's/.*"v":"\([^"]*\)".*/\1/' ;;
  *revision) printf '%s' "$j" | sed 's/.*"r":"\([^"]*\)".*/\1/' ;;
esac
EOF
chmod +x "$T/bin/brew" "$T/bin/curl" "$T/bin/plutil"
export CLAMAV_BREW="$T/bin/brew" FRESHCLAM_LOG="$T/fresh.log" FRESHCLAM_DB="$P/var/lib/clamav" STATE_DIR="$T" \
  CLAMAV_CURL="$T/bin/curl" CLAMAV_PLUTIL="$T/bin/plutil"

out="$(bash "$TOOL" --check 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && case "$out" in *clamscan*定義*) true ;; *) false ;; esac \
  && ok "--check: 足りないものを出して 1" || ng "--check rc=$rc: $out"

out="$(bash "$TOOL" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && [ -x "$P/bin/clamscan" ] && ok "入れる" || ng "入れる rc=$rc: $out"
grep -q '^#Example' "$P/etc/clamav/freshclam.conf" && ! grep -q '^Example' "$P/etc/clamav/freshclam.conf" \
  && ok "freshclam.conf の Example を外す" || ng "conf の Example"
[ -f "$P/var/lib/clamav/main.cvd" ] && ok "定義を取る" || ng "定義が無い"

bash "$TOOL" --check >/dev/null 2>&1 && ok "--check: 揃えば 0" || ng "--check が 0 でない"

printf '# 本人の設定\n' > "$P/etc/clamav/freshclam.conf"
bash "$TOOL" >/dev/null 2>&1
[ "$(grep -c install "$T/brew.log")" -eq 1 ] && ok "2 回目は brew install しない" || ng "brew を 2 回呼んだ"
[ "$(wc -l < "$T/fresh.log" | tr -d ' ')" -eq 1 ] && ok "2 回目は定義を取り直さない" || ng "freshclam を 2 回呼んだ"
grep -q '本人の設定' "$P/etc/clamav/freshclam.conf" && ok "既存の設定を触らない" || ng "設定を上書きした"

FRESHCLAM_RC=0 bash "$TOOL" --update; rc=$?
[ "$rc" -eq 0 ] && ok "--update: 更新なし (0) は成功" || ng "--update の 0 が rc=$rc"
for code in 1 52 54; do
  FRESHCLAM_RC=$code bash "$TOOL" --update >/dev/null 2>&1; rc=$?
  [ "$rc" -eq "$code" ] && ok "--update: 失敗の値 $code をそのまま返す" || ng "--update の $code が rc=$rc"
done
grep -q -e tap-new -e '^pin' "$T/brew.all" && ng "署名の不具合でない失敗で入れ替えた" || ok "署名の不具合でない失敗では入れ替えない"

# 定義が古い = 更新が止まっている
touch -t 202001010000 "$P/var/lib/clamav/daily.cld"
out="$(bash "$TOOL" --check 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && case "$out" in *定義が古い*) true ;; *) false ;; esac \
  && ok "--check: daily が古ければ出して 1" || ng "古い定義の --check rc=$rc: $out"
bash "$TOOL" >/dev/null 2>&1
bash "$TOOL" --check >/dev/null 2>&1 && ok "古い定義は install で取り直す" || ng "古い定義が残った"

# openssl@4 の署名の不具合: 原因を出し、 固定の版に入れ替えて pin、 もう 1 回取る
touch "$T/ossl4"; printf '\0/x/opt/openssl@4/lib/libcrypto.4.dylib\0' > "$P/opt/clamav/lib/libclamav.12.dylib"; echo 1.5.4 > "$T/core-v"; echo 1 > "$T/core-r"; : > "$T/brew.all"
out="$(bash "$TOOL" --update 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok "署名の不具合: 入れ替えて取り直し 0" || ng "署名の不具合で rc=$rc: $out"
case "$out" in *原因*openssl@4*) ok "署名の不具合: 原因を出す" ;; *) ng "原因が出ない: $out" ;; esac
grep -q 'install --force-bottle local/clamav-pin/clamav' "$T/brew.all" && grep -q '^pin clamav' "$T/brew.all" \
  && ok "署名の不具合: 固定の版を入れて pin" || ng "固定の版の install / pin が無い"
grep -q 'root_url "https://ghcr.io/v2/homebrew/core"' "$T/tap/Formula/clamav.rb" \
  && ok "固定の formula は homebrew-core の bottle を指す" || ng "root_url が無い"
[ "$(cat "$P/var/lib/clamav/.install-clamav-pin" 2>/dev/null)" = 1.5.4_1 ] \
  && ok "固定した時の homebrew-core の版を記録" || ng "PIN_MARK が 1.5.4_1 でない"

# homebrew-core の版が同じなら何もしない
: > "$T/brew.all"
bash "$TOOL" --update >/dev/null 2>&1; rc=$?
[ "$rc" -eq 0 ] && ! grep -q -e untap -e unpin "$T/brew.all" && ok "版が同じなら固定のまま" || ng "版が同じなのに外した rc=$rc"

# 版が変わってもまだ壊れていれば固定し直す
echo 2 > "$T/core-r"; : > "$T/brew.all"
out="$(BUGGY_CORE=1 bash "$TOOL" --update 2>&1)"; rc=$?
grep -q '^untap local/clamav-pin' "$T/brew.all" && grep -q 'install --force-bottle local/clamav-pin/clamav' "$T/brew.all" \
  && [ "$(cat "$P/var/lib/clamav/.install-clamav-pin" 2>/dev/null)" = 1.5.4_2 ] && [ "$rc" -eq 0 ] \
  && ok "版が変わってまだ壊れていれば固定し直す" || ng "固定し直さない rc=$rc: $out"

# 直った版が出たら固定を外したまま
echo 3 > "$T/core-r"; : > "$T/brew.all"
out="$(bash "$TOOL" --update 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && [ ! -f "$P/var/lib/clamav/.install-clamav-pin" ] && ! grep -q 'local/clamav-pin/clamav' "$T/brew.all" \
  && case "$out" in *固定を外したまま*) true ;; *) false ;; esac \
  && ok "直った版なら固定を外したまま" || ng "直った版で rc=$rc: $out"

CLAMAV_BREW=/nonexistent bash "$TOOL" --check >/dev/null 2>&1; rc=$?
[ "$rc" -eq 1 ] && ok "Homebrew が無ければ 1" || ng "brew 無しで rc=$rc"

echo "=== 結果: PASS=$pass FAIL=$fail ==="
exit "$fail"
