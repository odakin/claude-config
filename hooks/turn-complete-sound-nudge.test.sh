#!/usr/bin/env bash
# turn-complete-sound-nudge.test.sh — opt-in marker / entrypoint gate / stop_hook_active / 音声 path の selftest (実際には鳴らさない)
#
# 正本: claude-config/hooks/turn-complete-sound-nudge.test.sh
# 再生コマンドは fake player (引数を log に書くだけ) に差し替え、 $HOME は一時 dir に差し替える。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/turn-complete-sound-nudge.sh"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PLAYER="$TMP/fake-player"
LOG="$TMP/played"
printf '#!/bin/sh\necho "$@" >> "%s"\n' "$LOG" > "$PLAYER"
chmod +x "$PLAYER"
SND="$TMP/sound.aiff"
: > "$SND"

pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

mkhome() {  # $1 = dir, $2 = on|off|onoff|none, $3 = .on の 1 行目
  mkdir -p "$1/.claude"
  case "$2" in
    on)    printf '%s\n' "${3:-}" > "$1/.claude/turn-complete-sound.on" ;;
    off)   : > "$1/.claude/turn-complete-sound.off" ;;
    onoff) printf '%s\n' "${3:-}" > "$1/.claude/turn-complete-sound.on"; : > "$1/.claude/turn-complete-sound.off" ;;
  esac
}

# run HOME ENTRYPOINT ACTIVE [VAR=VALUE ...] → 再生の引数 (無ければ空) を stdout、 exit code は RC に
run() {
  local home="$1" ep="$2" active="$3"; shift 3
  rm -f "$LOG"
  printf '{"hook_event_name":"Stop","stop_hook_active":%s}' "$active" | \
    env -u CLAUDE_TURN_SOUND -u CLAUDE_TURN_SOUND_ENTRYPOINTS \
      CLAUDE_TURN_SOUND_HOME="$home" CLAUDE_TURN_SOUND_PLAYER="$PLAYER" CLAUDE_CODE_ENTRYPOINT="$ep" "$@" \
      bash "$HOOK" >/dev/null 2>&1
  RC=$?
  [ -f "$LOG" ] && cat "$LOG"
  return 0
}

H_NONE="$TMP/h-none"; mkhome "$H_NONE" none
H_ON="$TMP/h-on";     mkhome "$H_ON" on "$SND"
H_OFF="$TMP/h-off";   mkhome "$H_OFF" onoff "$SND"
H_TILDE="$TMP/h-tilde"; mkhome "$H_TILDE" on "~/my.aiff"; : > "$H_TILDE/my.aiff"

echo "=== opt-in marker ==="
out="$(run "$H_NONE" claude-desktop false)"
[ -z "$out" ] && ok "marker 無し = 鳴らない (既定は無音)" || ng "marker 無しで鳴った: $out"
out="$(run "$H_ON" claude-desktop false)"
[ "$out" = "-t 3 $SND" ] && ok ".on + desktop = .on の path を鳴らす" || ng "鳴らない / 引数違い: '$out'"
[ -f "$H_ON/.claude/state/turn-complete-sound.last" ] && ok "鳴らした時刻を state に書く" || ng "state file が無い"
out="$(run "$H_OFF" claude-desktop false)"
[ -z "$out" ] && ok ".off は .on より優先" || ng ".off があるのに鳴った"
out="$(run "$H_TILDE" claude-desktop false)"
[ "$out" = "-t 3 $H_TILDE/my.aiff" ] && ok ".on の ~/ を展開" || ng "~/ 展開: '$out'"

echo "=== env override ==="
out="$(run "$H_ON" claude-desktop false CLAUDE_TURN_SOUND=0)"
[ -z "$out" ] && ok "CLAUDE_TURN_SOUND=0 は marker より優先" || ng "=0 で鳴った"

echo "=== entrypoint gate ==="
out="$(run "$H_ON" sdk-cli false)"
[ -z "$out" ] && ok "headless (sdk-cli) = 鳴らない" || ng "headless で鳴った"
out="$(run "$H_ON" "" false)"
[ -z "$out" ] && ok "entrypoint 不明 = 鳴らない" || ng "entrypoint 空で鳴った"
out="$(run "$H_ON" cli false)"
[ -z "$out" ] && ok "cli は既定の許可 list 外" || ng "既定で cli が鳴った"
out="$(run "$H_ON" cli false 'CLAUDE_TURN_SOUND_ENTRYPOINTS=claude-desktop cli')"
[ "$out" = "-t 3 $SND" ] && ok "CLAUDE_TURN_SOUND_ENTRYPOINTS で cli を足せる" || ng "list 追加が効かない: '$out'"

echo "=== stop_hook_active / fail-open ==="
out="$(run "$H_ON" claude-desktop true)"
[ -z "$out" ] && ok "stop_hook_active=true = 鳴らない (2 回目)" || ng "2 回目で鳴った"
run "$H_ON" claude-desktop false CLAUDE_TURN_SOUND_PLAYER=/nonexistent/player >/dev/null
[ "$RC" = 0 ] && ok "再生コマンド無し = exit 0" || ng "exit $RC"
H_BADSND="$TMP/h-badsnd"; mkhome "$H_BADSND" on "/nonexistent/x.aiff"
out="$(run "$H_BADSND" claude-desktop false)"
case "$out" in ""|"-t 3 /System/Library/Sounds/Glass.aiff") ok ".on の path が無ければ既定音 (無い環境では鳴らさない)" ;; *) ng "path 不在時: '$out'" ;; esac

echo
echo "=== Result: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
