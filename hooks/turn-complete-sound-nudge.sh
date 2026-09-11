#!/usr/bin/env bash
# turn-complete-sound-nudge.sh — 応答が終わるたびに音を鳴らす Stop hook (opt-in、 既定は無音。 conventions/macos-claude-app-notifications.md#turn-complete-sound-hook)
#
# なぜ: Claude for Mac は「タスク完了」 の通知をアプリの仕様で常に無音にする (設定では変えられない)。
#   完了を音で知りたいときの代替。 block も model 向け出力もしない (音を鳴らすだけ)。
#
# opt-in (machine-local):
#   ~/.claude/turn-complete-sound.on  が在れば鳴らす / ~/.claude/turn-complete-sound.off が在れば鳴らさない (off 優先)。
#   .on の 1 行目に音声 file の path を書くとその音を使う (既定 /System/Library/Sounds/Glass.aiff、 先頭 ~/ は展開)。
#   env CLAUDE_TURN_SOUND=1 / 0 は marker より優先して on / off。
#
# 鳴らさない場合:
#   - stop_hook_active=true (= 別の Stop hook が block して turn が続いた後の 2 回目以降)
#   - CLAUDE_CODE_ENTRYPOINT が許可 list に無い。 既定 = claude-desktop だけ (実測で確かめた値)。
#     headless (`claude -p` 等) で夜中に鳴らさないための gate。 対話 CLI でも鳴らしたいなら
#     CLAUDE_TURN_SOUND_ENTRYPOINTS="claude-desktop cli" のように空白区切りで足す (headless の値は足さない)
#   - 再生コマンドか音声 file が無い (macOS 以外 = afplay 無し)
#
# 挙動: 再生は前景で待つ (-t 3 で上限。 background にすると hook の終了で切られ得る)。
#   鳴らしたら時刻を ~/.claude/state/turn-complete-sound.last に書く (確認用)。 fail-open = 常に exit 0。
#
# test 用 env: CLAUDE_TURN_SOUND_HOME ($HOME の代替) / CLAUDE_TURN_SOUND_PLAYER (afplay の代替)

set -u

INPUT="$(cat 2>/dev/null || true)"
if command -v jq >/dev/null 2>&1; then
  ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || echo false)"
else
  case "$INPUT" in *'"stop_hook_active":true'*|*'"stop_hook_active": true'*) ACTIVE=true ;; *) ACTIVE=false ;; esac
fi
[ "$ACTIVE" = "true" ] && exit 0

H="${CLAUDE_TURN_SOUND_HOME:-$HOME}"
ON="$H/.claude/turn-complete-sound.on"
OFF="$H/.claude/turn-complete-sound.off"
case "${CLAUDE_TURN_SOUND:-}" in
  0) exit 0 ;;
  1) ;;
  *) [ -e "$OFF" ] && exit 0
     [ -e "$ON" ] || exit 0 ;;
esac

EP="${CLAUDE_CODE_ENTRYPOINT:-}"
ALLOWED=0
for e in ${CLAUDE_TURN_SOUND_ENTRYPOINTS:-claude-desktop}; do
  [ "$e" = "$EP" ] && ALLOWED=1
done
[ "$ALLOWED" = 1 ] || exit 0

PLAYER="${CLAUDE_TURN_SOUND_PLAYER:-afplay}"
command -v "$PLAYER" >/dev/null 2>&1 || exit 0

SND="/System/Library/Sounds/Glass.aiff"
if [ -f "$ON" ]; then
  first="$(sed -n '1{s/^[[:space:]]*//;s/[[:space:]]*$//;p;}' "$ON" 2>/dev/null || true)"
  case "$first" in "~/"*) first="$H/${first#\~/}" ;; esac
  [ -n "$first" ] && [ -f "$first" ] && SND="$first"
fi
[ -f "$SND" ] || exit 0

"$PLAYER" -t 3 "$SND" >/dev/null 2>&1 || true
mkdir -p "$H/.claude/state" 2>/dev/null \
  && date '+%Y-%m-%dT%H:%M:%S' > "$H/.claude/state/turn-complete-sound.last" 2>/dev/null || true
exit 0
