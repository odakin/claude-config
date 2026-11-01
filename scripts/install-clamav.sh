#!/usr/bin/env bash
# install-clamav.sh — ClamAV (ネット由来の file の署名 scan) を Homebrew で入れ、 freshclam の設定と定義の取得までを揃える (冪等、 --check / --update つき)。 conventions/downloaded-file-scan.md#clamav-install
#
# usage: install-clamav.sh [--check | --update]
#   (なし)    足りないものだけ揃える: brew install clamav → freshclam.conf → 定義の取得 (無いか古いとき)
#   --check   書かずに、 足りないもの (定義が古い = daily が CLAMAV_MAX_AGE_DAYS 日より前、 を含む) を出して exit 1 (揃っていれば 0)
#   --update  定義を更新する (定期 job が呼ぶ。 終了値 = freshclam のもの、 更新なしも 0)
#
# 既知の不具合への自動の手当て (#openssl4-signature-bug): Homebrew の clamav が openssl@4 と組まれていると、 定義の署名を確かめられず、
# どの定義も読み込みの試験で捨てられる (実測。 Homebrew/homebrew-core#322048、 Cisco-Talos/clamav#1887)。 freshclam の失敗がこの形
# (出力に Incorrect digital signature / Database test FAILED / Malformed database ∧ libclamav が openssl@4 に link) なら、 原因を 1 行出し、
# openssl@3 で組まれた 1.5.4 の bottle (homebrew-core の PIN_COMMIT の formula、 bottle の sha256 はその formula が持つ) に入れ替えて pin し、
# もう 1 回取る。 固定した時の homebrew-core の版を PIN_MARK に書き、 --update はその版が変わったら固定を外して試す
# (定義が読み込めれば戻したまま、 読めなければ固定し直す)。 ⚠️ 「NULL X509 store」 の行は直った状態でも出る = 診断には使わない。
#
# 定義の毎日の更新は入れない (label と時刻は呼び出し側の層が決める = install-launchd-cron.sh の cmd routine に --update を呼ぶ shim を渡す)。
# launchd の PATH には Homebrew が無いので brew は固定の path も探す。 常駐の clamd は使わない。
# 環境変数: CLAMAV_MAX_AGE_DAYS = 定義が古いとみなす日数 (既定 4)
#   test 用: CLAMAV_BREW = brew の path / CLAMAV_OTOOL・CLAMAV_CURL・CLAMAV_PLUTIL = otool・curl・plutil の代わり
# 依存: bash 3.2 compatible。

set -u

MODE=install
for arg in "$@"; do
  case "$arg" in
    --check) MODE=check ;;
    --update) MODE=update ;;
    *) echo "usage: install-clamav.sh [--check | --update]" >&2; exit 2 ;;
  esac
done

find_brew() {
  if [ -n "${CLAMAV_BREW:-}" ]; then
    [ -x "$CLAMAV_BREW" ] && printf '%s\n' "$CLAMAV_BREW"
    return
  fi
  command -v brew 2>/dev/null && return
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$p" ] && { printf '%s\n' "$p"; return; }
  done
}

BREW="$(find_brew)"
if [ -z "$BREW" ]; then
  echo "install-clamav: Homebrew が無い (conventions/downloaded-file-scan.md#clamav-install)" >&2
  exit 1
fi
PREFIX="$("$BREW" --prefix)"
CONF="$PREFIX/etc/clamav/freshclam.conf"
DB="$PREFIX/var/lib/clamav"
MAX_AGE_DAYS="${CLAMAV_MAX_AGE_DAYS:-4}"
OTOOL="${CLAMAV_OTOOL:-otool}"
CURL="${CLAMAV_CURL:-curl}"
PLUTIL="${CLAMAV_PLUTIL:-plutil}"
PIN_COMMIT=10b454e5158c18e560b6dc1e32af551b14a912eb   # homebrew-core の clamav 1.5.4 (openssl@3) の formula の commit
PIN_TAP=local/clamav-pin
PIN_MARK="$DB/.install-clamav-pin"   # 中身 = 固定した時の homebrew-core の clamav の版 (例 1.5.4_1)

have_defs() {
  { [ -f "$DB/main.cvd" ] || [ -f "$DB/main.cld" ]; } && { [ -f "$DB/daily.cvd" ] || [ -f "$DB/daily.cld" ]; }
}

# daily は毎日配られる = MAX_AGE_DAYS 日より前のままなら更新が止まっている
fresh_defs() {
  [ -n "$(find "$DB" -maxdepth 1 \( -name daily.cvd -o -name daily.cld \) -mtime -"$MAX_AGE_DAYS" 2>/dev/null)" ]
}

RUN_LOG="$(mktemp "${TMPDIR:-/tmp}/install-clamav.XXXXXX")"
trap 'rm -f "$RUN_LOG" "$RUN_LOG.probe"' EXIT

# freshclam の終了値は更新なしも 0 (man freshclam の RETURN CODES)。 それ以外は失敗としてそのまま返す。 出力は診断のために RUN_LOG にも残す
update_defs() {
  "$PREFIX/bin/freshclam" --quiet > "$RUN_LOG" 2>&1
  local rc=$?
  cat "$RUN_LOG"
  return $rc
}

# 定義を実際に読み込めるか (更新なしの freshclam は読み込みを試さないので、 engine を替えた後はこれで確かめる)
defs_load() {
  : > "$RUN_LOG.probe"
  "$PREFIX/bin/clamscan" --no-summary "$RUN_LOG.probe" > "$RUN_LOG" 2>&1
  [ $? -le 1 ]
}

# 直前の失敗が #openssl4-signature-bug の形か
openssl4_sig_bug() {
  grep -q -e 'Incorrect digital signature' -e 'Database test FAILED' -e 'Malformed database' "$RUN_LOG" 2>/dev/null || return 1
  "$OTOOL" -L "$PREFIX"/opt/clamav/lib/libclamav*.dylib 2>/dev/null | grep -q 'openssl@4'
}

# homebrew-core の clamav の版 (例 1.5.4_1)。 取れなければ失敗
core_version() {
  local j v r
  j="$("$BREW" info --json=v2 homebrew/core/clamav 2>/dev/null)" || return 1
  v="$(printf '%s' "$j" | "$PLUTIL" -extract formulae.0.versions.stable raw -o - - 2>/dev/null)" || return 1
  [ -n "$v" ] || return 1
  r="$(printf '%s' "$j" | "$PLUTIL" -extract formulae.0.revision raw -o - - 2>/dev/null)" || r=0
  if [ -z "$r" ] || [ "$r" = 0 ]; then printf '%s\n' "$v"; else printf '%s_%s\n' "$v" "$r"; fi
}

pin_openssl3() {
  echo "install-clamav: 原因 = Homebrew の clamav が openssl@4 と組まれていて、 定義の署名を確かめられない (Homebrew/homebrew-core#322048)。 openssl@3 で組まれた 1.5.4 に入れ替えて固定する (conventions/downloaded-file-scan.md#openssl4-signature-bug)" >&2
  local cv repo f
  cv="$(core_version)" || cv=unknown
  export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_AUTOREMOVE=1
  repo="$("$BREW" --repository "$PIN_TAP" 2>/dev/null)"
  if [ -z "$repo" ] || [ ! -d "$repo" ]; then
    "$BREW" tap-new --no-git "$PIN_TAP" > /dev/null || { echo "install-clamav: tap-new $PIN_TAP に失敗" >&2; return 1; }
    repo="$("$BREW" --repository "$PIN_TAP")"
  fi
  mkdir -p "$repo/Formula"
  f="$repo/Formula/clamav.rb"
  "$CURL" -fsSL "https://raw.githubusercontent.com/Homebrew/homebrew-core/$PIN_COMMIT/Formula/c/clamav.rb" -o "$f.tmp" \
    || { echo "install-clamav: formula ($PIN_COMMIT) を取れない" >&2; rm -f "$f.tmp"; return 1; }
  # 別の tap の formula は bottle を自分の tap の置き場に探す = homebrew-core の置き場を指させる
  awk '{print} /^  bottle do$/{print "    root_url \"https://ghcr.io/v2/homebrew/core\""}' "$f.tmp" > "$f"
  rm -f "$f.tmp"
  grep -q 'root_url "https://ghcr.io/v2/homebrew/core"' "$f" || { echo "install-clamav: formula に bottle の節が無い" >&2; return 1; }
  "$BREW" unpin clamav > /dev/null 2>&1
  "$BREW" uninstall --ignore-dependencies clamav > /dev/null 2>&1
  if ! "$BREW" install --force-bottle "$PIN_TAP/clamav"; then
    echo "install-clamav: 固定の版を入れられない = homebrew-core の版に戻す" >&2
    "$BREW" install clamav > /dev/null 2>&1
    return 1
  fi
  "$BREW" pin clamav
  printf '%s\n' "$cv" > "$PIN_MARK"
}

# 固定した後に homebrew-core の clamav の版が変わったら、 固定を外して試す (読めなければ固定し直す)
try_unpin() {
  [ -f "$PIN_MARK" ] || return 0
  local cv
  cv="$(core_version)" || return 0
  [ "$cv" = "$(cat "$PIN_MARK")" ] && return 0
  echo "install-clamav: homebrew-core の clamav が $cv になった = 固定を外して試す" >&2
  export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_AUTOREMOVE=1
  "$BREW" unpin clamav > /dev/null 2>&1
  "$BREW" uninstall --ignore-dependencies clamav > /dev/null 2>&1
  "$BREW" untap "$PIN_TAP" > /dev/null 2>&1
  if ! "$BREW" install clamav; then
    pin_openssl3
    return
  fi
  rm -f "$PIN_MARK"
  if defs_load; then
    echo "install-clamav: homebrew-core の clamav $cv で定義を読めた = 固定を外したまま" >&2
    return 0
  fi
  if openssl4_sig_bug; then
    pin_openssl3
    return
  fi
  cat "$RUN_LOG"
  return 1
}

# 定義を取る。 失敗が #openssl4-signature-bug なら入れ替えてもう 1 回
update_with_fix() {
  update_defs
  local rc=$?
  [ $rc -eq 0 ] && return 0
  openssl4_sig_bug || return $rc
  pin_openssl3 || return $rc
  update_defs
}

case "$MODE" in
  check)
    missing=""
    [ -x "$PREFIX/bin/clamscan" ] || missing="$missing clamscan"
    [ -f "$CONF" ] || missing="$missing freshclam.conf"
    if ! have_defs; then
      missing="$missing 定義"
    elif ! fresh_defs; then
      missing="$missing 定義が古い(daily が ${MAX_AGE_DAYS} 日より前)"
    fi
    if [ -n "$missing" ]; then
      echo "install-clamav: 足りない =$missing"
      exit 1
    fi
    exit 0
    ;;
  update)
    [ -x "$PREFIX/bin/freshclam" ] || { echo "install-clamav: freshclam が無い" >&2; exit 1; }
    try_unpin
    update_with_fix
    exit $?
    ;;
esac

if [ ! -x "$PREFIX/bin/clamscan" ]; then
  "$BREW" install clamav || exit 1
fi
if [ ! -f "$CONF" ]; then
  [ -f "$CONF.sample" ] || { echo "install-clamav: $CONF.sample が無い" >&2; exit 1; }
  sed 's/^Example/#Example/' "$CONF.sample" > "$CONF" || exit 1
fi
if ! have_defs || ! fresh_defs; then
  update_with_fix || { echo "install-clamav: 定義の取得に失敗 (freshclam の出力は上)" >&2; exit 1; }
fi
echo "install-clamav: 揃っている ($("$PREFIX/bin/clamscan" --version 2>/dev/null))"
