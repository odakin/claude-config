#!/bin/sh
# claude-notify.sh — macOS 通知を出す唯一の入口 (= 押すと行き先がある通知)。
#
# なぜ各 script が直に osascript を呼ばないか:
#   `osascript -e 'display notification ...'` の通知は macOS が **スクリプトエディタ**の通知
#   として扱う。 通知の click は「投稿したアプリを activate する」 動作しか持たないので、
#   押すとスクリプトエディタが前面に出て空の書類選択ダイアログが開くだけになる。
#   投稿元を notify-app/ の applet に一本化すると、 click が決めた行き先に着く。
#   正本 = conventions/macos-clickable-notifications.md
#
# 動作: queue (TSV) に 1 行足して `open -a` でアプリを起こすだけ。 投稿はアプリがやる。
#   アプリが無い / 未許可 / 起動失敗なら osascript で出す (= fail-open。 通知が消えるより
#   押せない通知の方がまし)。
#
# usage:
#   sh claude-notify.sh --title "..." [--body "..."] [--sound Basso]
#   sh claude-notify.sh --status
#   sh claude-notify.sh --enable [--force]   # 許可を実測してからアプリ経路に切替える
#   sh claude-notify.sh --disable            # 旧経路に戻す
#   sh claude-notify.sh --selftest
#
# env:
#   CLAUDE_NOTIFY_APP        アプリの path (既定 ~/Applications/ClaudeReminder.app)
#   CLAUDE_NOTIFY_QUEUE      queue の path (既定 ~/.claude/state/claude-notify-queue.tsv)
#   CLAUDE_NOTIFY_OK_MARKER  切替え済み marker (既定 ~/.claude/state/claude-notify-app.ok)
#   CLAUDE_NOTIFY_DRYRUN     1 なら queue に書くだけでアプリを起こさない (test 用)
set -u

APP="${CLAUDE_NOTIFY_APP:-$HOME/Applications/ClaudeReminder.app}"
QUEUE="${CLAUDE_NOTIFY_QUEUE:-$HOME/.claude/state/claude-notify-queue.tsv}"
# 安全弁: この機械で「アプリの通知が実際に出せる」 と実測できるまでは旧経路で鳴らす。
# 新しいアプリの通知は既定で notificationsAllowed=false (= 通知センターに溜まるだけで
# バナーも音も出ない) なので、 許可の前に切替えると通知が黙って消える。
OKMARK="${CLAUDE_NOTIFY_OK_MARKER:-$HOME/.claude/state/claude-notify-app.ok}"

TITLE=""
BODY=""
SOUND="Basso"
ACTION=""
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --title) TITLE="${2:-}"; shift 2 ;;
    --body)  BODY="${2:-}";  shift 2 ;;
    --sound) SOUND="${2:-}"; shift 2 ;;
    --status)
      printf 'app   : %s %s\n' "$APP" "$([ -d "$APP" ] && echo '(あり)' || echo '(なし)')"
      printf 'queue : %s %s\n' "$QUEUE" "$([ -s "$QUEUE" ] && echo '(残がある)' || echo '(空)')"
      printf 'click : %s\n' "$([ -e "$HOME/.claude/notify-click.sh" ] && echo 'あり' || echo 'なし (= ~/.claude/surface を開く)')"
      printf '経路  : %s\n' "$([ -f "$OKMARK" ] && echo 'アプリ (押せる通知)' || echo '旧 osascript (押しても行き先なし) — 許可の実測待ち')"
      exit 0 ;;
    --enable)   ACTION=enable; shift ;;
    --force)    FORCE=1; shift ;;
    --disable)  rm -f "$OKMARK"; echo "旧経路に戻しました"; exit 0 ;;
    --selftest) SELFTEST=1; shift ;;
    *) shift ;;
  esac
done

# 1 行 1 通知の TSV なので tab / 改行は潰す
_flatten() {
  printf '%s' "$1" | tr '\t\n\r' '   '
}

_bundle_id() {
  /usr/bin/defaults read "$APP/Contents/Info" CFBundleIdentifier 2>/dev/null
}

# --enable は「人が切替えを宣言する」 だけでは足りない (実害: 許可が入る前に切替えて、
# 通知が通知センターに溜まるだけの状態になった)。 実際に 1 通投げて NotificationCenter の
# log を読み、 出せる状態かを**実測してから**切替える。
_probe_allowed() {
  bundle="$(_bundle_id)"
  [ -n "$bundle" ] || { echo "unknown"; return; }
  since="$(date '+%Y-%m-%d %H:%M:%S')"
  mkdir -p "$(dirname "$QUEUE")" 2>/dev/null || true
  printf '%s\t%s\t%s\n' "通知の確認" "これが見えていれば許可は入っています" "Glass" >> "$QUEUE"
  open -a "$APP" >/dev/null 2>&1 || { rm -f "$QUEUE"; echo "unknown"; return; }
  sleep 4
  lines="$(log show --start "$since" --style compact \
    --predicate 'process == "NotificationCenter"' 2>/dev/null | grep -F "$bundle")"
  # 否定側の証拠 (許可されていない時にだけ出る)
  if printf '%s' "$lines" | grep -q 'notificationsAllowed: false'; then
    echo "false"; return
  fi
  # 肯定側の証拠 (許可されている時にだけ出る)。 片側だけ見ると、 許可された途端に
  # 「読めません」 になって人に目視を押し付けることになる (実害)。
  if printf '%s' "$lines" | grep -q 'Playing notification sound'; then
    echo "true"; return
  fi
  # 配送はされたが音の行が無い (= おやすみモード等)。 断定しない。
  echo "unknown"
}

_fallback() {
  # 従来経路 (= スクリプトエディタ名義。 押しても行き先は無いが、 出ないよりまし)
  t="$(printf '%s' "$1" | sed 's/\\//g; s/"/'"'"'/g')"
  b="$(printf '%s' "$2" | sed 's/\\//g; s/"/'"'"'/g')"
  osascript -e "display notification \"$b\" with title \"$t\" sound name \"$3\"" \
    >/dev/null 2>&1 || true
}

if [ "$ACTION" = "enable" ]; then
  if [ ! -d "$APP" ]; then
    echo "アプリがありません: $APP"
    echo "先に notify-app/install.sh を実行してください"
    exit 1
  fi
  allowed="$(_probe_allowed)"
  case "$allowed" in
    true)
      mkdir -p "$(dirname "$OKMARK")"; date > "$OKMARK"
      echo "✅ 通知が許可されているのを実測しました → アプリ経路に切替えました" ;;
    false)
      echo "❌ まだ許可が入っていません (実測: notificationsAllowed = false)"
      echo "   = 通知センターに溜まるだけで、 バナーも音も出ません。 切替えません。"
      echo "   「システム設定 > 通知」 で許可 → もう一度 --enable"
      exit 1 ;;
    *)
      if [ "$FORCE" = "1" ]; then
        mkdir -p "$(dirname "$OKMARK")"; date > "$OKMARK"
        echo "⚠️ 許可状態を実測できませんでしたが --force 指定なので切替えました"
      else
        echo "⚠️ 許可状態を実測できませんでした (log から読めず)"
        echo "   いま 1 通投げたので、 バナーが出たかを目で見て:"
        echo "     出た   → --enable --force"
        echo "     出ない → 「システム設定 > 通知」 で許可してから、 もう一度 --enable"
        exit 1
      fi ;;
  esac
  exit 0
fi

if [ "${SELFTEST:-0}" = "1" ]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  PASS=0; FAIL=0
  _assert() {
    if [ "$2" = "$3" ]; then echo "[PASS] $1"; PASS=$((PASS+1));
    else echo "[FAIL] $1"; echo "       got:  $2"; echo "       want: $3"; FAIL=$((FAIL+1)); fi
  }
  echo "=== claude-notify.sh --selftest ==="

  CLAUDE_NOTIFY_QUEUE="$tmp/q.tsv" CLAUDE_NOTIFY_DRYRUN=1 \
    sh "$0" --title "T1" --body "B1" --sound "Glass" >/dev/null 2>&1
  _assert "(i) queue に TSV 1 行が書かれる" \
    "$(cat "$tmp/q.tsv")" "$(printf 'T1\tB1\tGlass')"

  CLAUDE_NOTIFY_QUEUE="$tmp/q.tsv" CLAUDE_NOTIFY_DRYRUN=1 \
    sh "$0" --title "T2" --body "B2" >/dev/null 2>&1
  _assert "(ii) 2 件目は append される (= 取りこぼさない)" \
    "$(wc -l < "$tmp/q.tsv" | tr -d ' ')" "2"

  CLAUDE_NOTIFY_QUEUE="$tmp/q2.tsv" CLAUDE_NOTIFY_DRYRUN=1 \
    sh "$0" --title "多  行" --body "$(printf 'a\nb\tc')" >/dev/null 2>&1
  _assert "(iii) 本文の改行・tab は潰れて 1 行のまま" \
    "$(wc -l < "$tmp/q2.tsv" | tr -d ' ')" "1"
  _assert "(iv) 潰した後も field は 3 つ" \
    "$(awk -F'\t' '{print NF}' "$tmp/q2.tsv")" "3"

  # marker が無ければアプリ経路に入らない (= 許可前に通知が消えない)
  CLAUDE_NOTIFY_QUEUE="$tmp/q3.tsv" CLAUDE_NOTIFY_OK_MARKER="$tmp/none.ok" \
    CLAUDE_NOTIFY_APP="$tmp/nonexistent.app" \
    sh "$0" --title "T3" --body "B3" >/dev/null 2>&1
  _assert "(v) marker 無しでは queue に書かない (= 旧経路へ落ちる)" \
    "$([ -f "$tmp/q3.tsv" ] && echo exists || echo absent)" "absent"

  echo ""
  echo "=== selftest: $PASS passed, $FAIL failed ==="
  [ "$FAIL" -eq 0 ] || exit 1
  exit 0
fi

[ -n "$TITLE" ] || exit 0

# 許可が実測できていない間は旧経路 (= 押せないが見える)
if [ ! -f "$OKMARK" ] && [ "${CLAUDE_NOTIFY_DRYRUN:-0}" != "1" ]; then
  _fallback "$TITLE" "$BODY" "$SOUND"
  exit 0
fi

mkdir -p "$(dirname "$QUEUE")" 2>/dev/null || true
printf '%s\t%s\t%s\n' "$(_flatten "$TITLE")" "$(_flatten "$BODY")" "$(_flatten "$SOUND")" \
  >> "$QUEUE" 2>/dev/null || true

[ "${CLAUDE_NOTIFY_DRYRUN:-0}" = "1" ] && exit 0

if [ -d "$APP" ] && open -a "$APP" >/dev/null 2>&1; then
  exit 0
fi

# アプリが無い/起動できない: queue を掃除して従来経路へ
rm -f "$QUEUE" 2>/dev/null || true
_fallback "$TITLE" "$BODY" "$SOUND"
exit 0
