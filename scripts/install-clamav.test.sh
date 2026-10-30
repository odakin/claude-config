#!/usr/bin/env bash
# install-clamav.test.sh — install-clamav.sh の test (偽の brew と freshclam で、 足りないものだけ揃う・既存の設定を触らない・更新なしを成功と読む・失敗の値を返す)
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL="$SELF_DIR/install-clamav.sh"
pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
P="$T/prefix"
mkdir -p "$T/bin" "$P/bin" "$P/etc/clamav" "$P/var/lib/clamav"
cat > "$T/bin/brew" <<EOF
#!/usr/bin/env bash
case "\$1" in
  --prefix) echo "$P" ;;
  install)
    echo "install \$2" >> "$T/brew.log"
    printf '#!/usr/bin/env bash\necho ClamAV 9.9.9\n' > "$P/bin/clamscan"
    cat > "$P/bin/freshclam" <<'INNER'
#!/usr/bin/env bash
echo run >> "\$FRESHCLAM_LOG"
[ -n "\${FRESHCLAM_RC:-}" ] && exit "\$FRESHCLAM_RC"
touch "\$FRESHCLAM_DB/main.cvd" "\$FRESHCLAM_DB/daily.cld"
INNER
    chmod +x "$P/bin/clamscan" "$P/bin/freshclam"
    printf 'Example\nDatabaseMirror x\n' > "$P/etc/clamav/freshclam.conf.sample"
    ;;
esac
EOF
chmod +x "$T/bin/brew"
export CLAMAV_BREW="$T/bin/brew" FRESHCLAM_LOG="$T/fresh.log" FRESHCLAM_DB="$P/var/lib/clamav"

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

FRESHCLAM_RC=1 bash "$TOOL" --update; rc=$?
[ "$rc" -eq 0 ] && ok "--update: 更新なし (1) は成功" || ng "--update の 1 が rc=$rc"
FRESHCLAM_RC=52 bash "$TOOL" --update >/dev/null 2>&1; rc=$?
[ "$rc" -eq 52 ] && ok "--update: 失敗の値を返す" || ng "--update の 52 が rc=$rc"

CLAMAV_BREW=/nonexistent bash "$TOOL" --check >/dev/null 2>&1; rc=$?
[ "$rc" -eq 1 ] && ok "Homebrew が無ければ 1" || ng "brew 無しで rc=$rc"

echo "=== 結果: PASS=$pass FAIL=$fail ==="
exit "$fail"
