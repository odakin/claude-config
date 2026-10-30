#!/usr/bin/env bash
# install-clamav.sh — ClamAV (ネット由来の file の署名 scan) を Homebrew で入れ、 freshclam の設定と定義の取得までを揃える (冪等、 --check / --update つき)。 conventions/downloaded-file-scan.md#clamav-install
#
# usage: install-clamav.sh [--check | --update]
#   (なし)    足りないものだけ揃える: brew install clamav → freshclam.conf → 定義の取得
#   --check   書かずに、 足りないものを出して exit 1 (揃っていれば 0)
#   --update  定義を更新する (定期 job が呼ぶ。 終了値 = freshclam のもの、 更新なしも 0)
#
# 定義の毎日の更新は入れない (label と時刻は呼び出し側の層が決める = install-launchd-cron.sh の cmd routine に --update を呼ぶ shim を渡す)。
# launchd の PATH には Homebrew が無いので brew は固定の path も探す。 常駐の clamd は使わない。
# 環境変数 (test 用): CLAMAV_BREW = brew の path
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

have_defs() {
  { [ -f "$DB/main.cvd" ] || [ -f "$DB/main.cld" ]; } && { [ -f "$DB/daily.cvd" ] || [ -f "$DB/daily.cld" ]; }
}

# freshclam の終了値は更新なしも 0 (man freshclam の RETURN CODES)。 それ以外は失敗としてそのまま返す
update_defs() {
  "$PREFIX/bin/freshclam" --quiet
}

case "$MODE" in
  check)
    missing=""
    [ -x "$PREFIX/bin/clamscan" ] || missing="$missing clamscan"
    [ -f "$CONF" ] || missing="$missing freshclam.conf"
    have_defs || missing="$missing 定義"
    if [ -n "$missing" ]; then
      echo "install-clamav: 足りない =$missing"
      exit 1
    fi
    exit 0
    ;;
  update)
    [ -x "$PREFIX/bin/freshclam" ] || { echo "install-clamav: freshclam が無い" >&2; exit 1; }
    update_defs
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
if ! have_defs; then
  update_defs || { echo "install-clamav: 定義の取得に失敗" >&2; exit 1; }
fi
echo "install-clamav: 揃っている ($("$PREFIX/bin/clamscan" --version 2>/dev/null))"
