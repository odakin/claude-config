#!/usr/bin/env bash
# owner-asks.sh — 本人への問いと答えの台帳 (ai-collaboration/board/board_asks.py) の hook の入口: 答えを問いに結ぶ・結び先の決まらない答えのあいだ効く操作を止める・印の無い問いを差し戻す・開始と圧縮の前後に問いと答えを出す
#
# event ごとに engine の subcommand を呼ぶ (hook の JSON は stdin のまま渡し、 engine の出力をそのまま返す):
#   UserPromptSubmit → hook-prompt (本人の答えを問いに結び、 結び方を Claude に渡す)
#   PreToolUse       → hook-pretool (結び先の決まらない答えのあいだ、 送信・決定の記録・別 session への message・畳む操作を止める)
#   Stop             → hook-stop (印の無い問いを 1 回差し戻す・返事に出した印を記録する)
#   PreCompact       → hook-precompact (要約に問いと答えを残す指示 = 本体が要約の指示に足す)
#   SessionStart     → hook-sessionstart (この session の開いた問いと答えの出た問いを出す)
# 設定: 個人層の board-asks.json ({"root": "<作業ルートからの掲示板の dir>", "prefix": {"<hostname -s>": "<英大文字 1 字>"}})。
#   個人層 = 作業ルートの CLAUDE.md の symlink の先の dir (setup.sh の個人層の仕組み)。 BOARD_ASKS_CONFIG で上書き。
#   設定・engine が無ければ何もしない (exit 0)。 試験用の上書き = BOARD_ASKS_ENGINE / BOARD_ASKS_VALIDATOR。
# 速さ: PreToolUse は、 その session の「結び先の決まらない答え」 の印の file (<state dir>/<session>.guess) が無ければ
#   python を起こさない (jq と file の有無だけ)。
# 失敗は止めない側に倒す (jq・python・engine が無い・engine の例外 = 何も出さず exit 0)。 engine の例外と 0 でない終了は
#   <state dir>/hook-errors.log に 1 件ずつ書く (黙って死なない。 256 KB を超えたら 1 世代だけ残して回す)。
# 印の字: board-asks.json の prefix を BOARD_ASKS_PREFIX で渡す。 engine はそれを台帳の隣に残し、 手で打つ ask も同じ字を使う。
set -u
input="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
event="$(printf '%s' "$input" | jq -r '.hook_event_name // empty' 2>/dev/null)"
[ -n "$event" ] || exit 0
session="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
state_dir="${BOARD_ASKS_STATE_DIR:-$HOME/.claude/state/board-asks}"
if [ "$event" = "PreToolUse" ]; then
  safe="$(printf '%s' "$session" | LC_ALL=C tr -c 'A-Za-z0-9_-' '_' | cut -c1-80)"
  [ -n "$safe" ] && [ -f "$state_dir/$safe.guess" ] || exit 0
fi
case "$event" in
  UserPromptSubmit) sub=hook-prompt ;;
  PreToolUse) sub=hook-pretool ;;
  Stop) sub=hook-stop ;;
  PreCompact) sub=hook-precompact ;;
  SessionStart) sub=hook-sessionstart ;;
  *) exit 0 ;;
esac
self="$(readlink -f "$0" 2>/dev/null || printf '%s' "$0")"
cc_root="$(cd "$(dirname "$self")/.." 2>/dev/null && pwd)"
base="$(dirname "$cc_root")"
engine="${BOARD_ASKS_ENGINE:-$base/ai-collaboration/board/board_asks.py}"
[ -f "$engine" ] || exit 0
cfg="${BOARD_ASKS_CONFIG:-}"
if [ -z "$cfg" ] && [ -L "$base/CLAUDE.md" ]; then
  cfg="$(dirname "$(readlink -f "$base/CLAUDE.md")")/board-asks.json"
fi
[ -n "$cfg" ] && [ -f "$cfg" ] || exit 0
root_rel="$(jq -r '.root // empty' "$cfg" 2>/dev/null)"
[ -n "$root_rel" ] || exit 0
case "$root_rel" in
  /*) root="$root_rel" ;;
  "~"*) root="$HOME${root_rel#\~}" ;;
  *) root="$base/$root_rel" ;;
esac
[ -d "$root" ] || exit 0
host="$(hostname -s 2>/dev/null || hostname)"
prefix="$(jq -r --arg h "$host" '(.prefix // {})[$h] // .default_prefix // empty' "$cfg" 2>/dev/null)"
validator="${BOARD_ASKS_VALIDATOR:-$cc_root/scripts/owner-ask-validate.py}"
mkdir -p "$state_dir" 2>/dev/null || true
log="$state_dir/hook-errors.log"
err="$(mktemp "${TMPDIR:-/tmp}/owner-asks-err.XXXXXX" 2>/dev/null)" || err=/dev/null
printf '%s' "$input" | BOARD_ASKS_PREFIX="$prefix" BOARD_ASKS_VALIDATOR="$validator" BOARD_ASKS_STATE_DIR="$state_dir" \
  python3 "$engine" "$sub" --root "$root" 2>"$err"
rc=$?
if [ "$err" != /dev/null ]; then
  if [ "$rc" -ne 0 ] || [ -s "$err" ]; then
    if [ -f "$log" ] && [ "$(wc -c <"$log" 2>/dev/null || echo 0)" -gt 262144 ]; then
      mv -f "$log" "$log.1" 2>/dev/null || true
    fi
    { printf '%s %s %s rc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$event" "$session" "$rc"; tail -n 20 "$err"; } >>"$log" 2>/dev/null || true
  fi
  rm -f "$err"
fi
exit 0
