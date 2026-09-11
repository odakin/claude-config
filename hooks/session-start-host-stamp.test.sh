#!/usr/bin/env bash
# session-start-host-stamp.test.sh — SessionStart stamp hook の入口 test
#
# 判定 logic 本体の test は scripts/first_reply_stamp.py --selftest (first-reply-stamp.test.sh が呼ぶ)。
# ここでは wrapper が stdin を module に渡し、 symlink 経由でも repo を見つけることを確かめる。
# account 軸は FIRST_REPLY_STAMP_WHO で固定する (= test が実マシンの account に依存しない)。

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/session-start-host-stamp.sh"
BASE="$(cd "$HERE/../.." && pwd)"
pass=0; fail=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export FIRST_REPLY_STAMP_WHO="desktop = someone@example.invalid"
export FIRST_REPLY_STAMP_STATE_DIR="$TMP/state"

run_hook() { # <hook path> <stdin>
  printf '%s' "$2" | bash "$1" 2>/dev/null
}

expect_contains() { # <desc> <needle> <stdin> [hook]
  local out
  out="$(run_hook "${4:-$HOOK}" "$3")"
  if printf '%s' "$out" | grep -qF "$2"; then
    pass=$((pass+1))
  else
    fail=$((fail+1)); echo "FAIL: $1"; echo "  wanted: $2"; echo "  got: $out"
  fi
}

expect_silent() { # <desc> <stdin>
  local out
  out="$(run_hook "$HOOK" "$2")"
  if [ -z "$out" ]; then
    pass=$((pass+1))
  else
    fail=$((fail+1)); echo "FAIL: $1 (expected silent)"; echo "  got: $out"
  fi
}

host="$(python3 -c 'import socket; print(socket.gethostname().split(".")[0])')"
SS="{\"hook_event_name\":\"SessionStart\",\"session_id\":\"abcdef12-3456-7890-aaaa-bbbbccccdddd\",\"source\":\"startup\",\"cwd\":\"$BASE\"}"

expect_contains "SessionStart で hostname を含む stamp"       "🖥 ${host}"          "$SS"
expect_contains "session id 先頭 8 桁"                         "abcdef12"            "$SS"
expect_contains "account 軸 (whoami の結果) を載せる"          "someone@example.invalid" "$SS"
expect_contains "最初の text の定義 (途中経過を含む) を示す"   "途中経過"             "$SS"
expect_contains "system-reminder 包装"                         "<system-reminder>"   "$SS"
expect_contains "session_id 欠落でも host は出す"              "session unknown"     "{\"hook_event_name\":\"SessionStart\",\"cwd\":\"$BASE\"}"
expect_silent   "PreToolUse では沈黙"   '{"hook_event_name":"PreToolUse","tool_name":"Bash"}'
expect_silent   "空 stdin では沈黙"     ''
expect_silent   "workspace の外 (盲検 sandbox) では沈黙" "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"x\",\"cwd\":\"$TMP\"}"

# symlink 経由 (~/.claude/hooks/ と同じ置き方) でも repo の module を見つける
ln -s "$HOOK" "$TMP/linked-host-stamp.sh"
expect_contains "symlink 経由でも動く" "🖥 ${host}" "$SS" "$TMP/linked-host-stamp.sh"

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
