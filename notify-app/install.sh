#!/bin/sh
# install.sh — 通知アプリ (ClaudeReminder.app) を source から build して deploy する。
#
# 何のアプリか: macOS 通知の**投稿元**。 これがあると ① 通知の click が「スクリプトエディタの
#   空の書類選択ダイアログ」 ではなく、 決めた行き先に着く ② 通知設定にこのアプリで 1 行立つ
#   (= 音・表示スタイル・グループ化を決められる)。 正本 = conventions/macos-clickable-notifications.md
#
# 配る物に環境を焼かない: home は実行時の $HOME から取る。 bundle id と click 先は引数 / env。
#
# usage:
#   sh install.sh [--ensure]            build + deploy (--ensure = source が変わった時だけ作り直す)
#   sh install.sh --status              今の状態を出すだけ
#   sh install.sh --uninstall           アプリと click 配線を消す
#   引数:
#     --bundle-id <id>        既定 com.claude-config.ClaudeReminder (既存 app があればそれを継ぐ)
#     --click-script <path>   通知を押した時に /bin/sh で実行する script。 ~/.claude/notify-click.sh
#                             に symlink する (= 中身は呼ぶ側の層が持つ)
#     --app <path>            既定 ~/Applications/ClaudeReminder.app
#
# ⚠️ **bundle id を変えると別のアプリになり、 通知の許可を出し直すことになる** (= 名前は最初に
#    決める)。 同じ bundle id での rebuild では通知の許可は維持される (実測)。 ただし TCC
#    (画面収録・アプリ管理等) は cdhash 基準なので rebuild で消える —
#    conventions/macos-clickable-notifications.md#rebuild-and-identity
set -eu

APP="${CLAUDE_NOTIFY_APP:-$HOME/Applications/ClaudeReminder.app}"
BUNDLE_ID="${CLAUDE_NOTIFY_BUNDLE_ID:-}"
CLICK_SRC=""
MODE="install"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
CLICK_DST="$HOME/.claude/notify-click.sh"

while [ $# -gt 0 ]; do
  case "$1" in
    --ensure)       MODE="ensure"; shift ;;
    --status)       MODE="status"; shift ;;
    --uninstall)    MODE="uninstall"; shift ;;
    --bundle-id)    BUNDLE_ID="${2:-}"; shift 2 ;;
    --click-script) CLICK_SRC="${2:-}"; shift 2 ;;
    --app)          APP="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

_current_bundle_id() {
  [ -f "$APP/Contents/Info.plist" ] || return 1
  /usr/bin/defaults read "$APP/Contents/Info" CFBundleIdentifier 2>/dev/null
}

_status() {
  printf 'app        : %s %s\n' "$APP" "$([ -d "$APP" ] && echo '(あり)' || echo '(なし)')"
  printf 'bundle id  : %s\n' "$(_current_bundle_id 2>/dev/null || echo '(未配置)')"
  printf 'click 先   : %s %s\n' "$CLICK_DST" \
    "$([ -e "$CLICK_DST" ] && echo "-> $(readlink "$CLICK_DST" 2>/dev/null || echo 'file')" || echo '(なし = ~/.claude/surface を開く)')"
  printf 'queue      : %s\n' "$HOME/.claude/state/claude-notify-queue.tsv"
}

case "$MODE" in
  status) _status; exit 0 ;;
  uninstall)
    rm -rf "$APP"; rm -f "$CLICK_DST"
    echo "削除しました: $APP"
    echo "⚠️ 通知設定に残った項目は「システム設定 > 通知」 から手で消してください。"
    exit 0 ;;
esac

case "$(uname -s)" in
  Darwin) ;;
  *) echo "macOS 専用です (no-op)"; exit 0 ;;
esac

# bundle id: 明示 > 既存 app から継承 > 既定 (= 黙って identity を変えない)
if [ -z "$BUNDLE_ID" ]; then
  BUNDLE_ID="$(_current_bundle_id 2>/dev/null || true)"
  [ -n "$BUNDLE_ID" ] || BUNDLE_ID="com.claude-config.ClaudeReminder"
fi

# click 先の配線 (symlink = 中身の更新は呼ぶ側の層で完結する)
if [ -n "$CLICK_SRC" ]; then
  if [ -f "$CLICK_SRC" ]; then
    mkdir -p "$(dirname "$CLICK_DST")"
    ln -sfn "$CLICK_SRC" "$CLICK_DST"
  else
    echo "WARN: --click-script が見つかりません: $CLICK_SRC (click 先は既定のまま)" >&2
  fi
fi

SRC="$SRC_DIR/ClaudeReminder.applescript"
STAMP="$APP/Contents/Resources/.source-sha"
NEW_SHA="$(shasum "$SRC" 2>/dev/null | awk '{print $1}')-$BUNDLE_ID"

if [ "$MODE" = "ensure" ] && [ -d "$APP" ] && [ "$(cat "$STAMP" 2>/dev/null || echo)" = "$NEW_SHA" ]; then
  # source も bundle id も変わっていない = 作り直さない (= cdhash を無駄に変えない)
  exit 0
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

osacompile -o "$STAGE/ClaudeReminder.app" "$SRC"
plutil -replace CFBundleIdentifier -string "$BUNDLE_ID" "$STAGE/ClaudeReminder.app/Contents/Info.plist"
plutil -replace CFBundleName -string "Claude リマインダー" "$STAGE/ClaudeReminder.app/Contents/Info.plist"
# Dock に出さない (通知は出せる)。 LSBackgroundOnly にすると通知を出せなくなるので使わない。
plutil -replace LSUIElement -bool true "$STAGE/ClaudeReminder.app/Contents/Info.plist"
printf '%s' "$NEW_SHA" > "$STAGE/ClaudeReminder.app/Contents/Resources/.source-sha"
codesign -f -s - "$STAGE/ClaudeReminder.app" >/dev/null 2>&1 || true

mkdir -p "$(dirname "$APP")"
rm -rf "$APP"
ditto "$STAGE/ClaudeReminder.app" "$APP"

# LaunchServices に今すぐ登録 (= 初回の投稿前に通知設定へ 1 行立てる)
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" >/dev/null 2>&1 || true

echo "配置しました: $APP"
_status
