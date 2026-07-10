#!/usr/bin/env bash
# merge-hook-event.test.sh — merge_hook_event の self-test (hermetic、 実 settings.json 不使用)
# 実行: bash scripts/lib/merge-hook-event.test.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=merge-hook-event.sh
. "$HERE/merge-hook-event.sh"

command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not installed"; exit 0; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
S="$TMP/settings.json"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); }
miss() { FAIL=$((FAIL+1)); echo "  MISS: $1"; }

ENTRIES='[
  {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/a-guard.sh"}]},
  {"matcher": "Read", "hooks": [{"type": "command", "command": "~/.claude/hooks/b-nudge.sh"}]},
  {"matcher": "Edit", "hooks": [{"type": "command", "command": "~/.claude/hooks/c-multi.sh track"}]}
]'
STOP_ENTRIES='[
  {"hooks": [{"type": "command", "command": "~/.claude/hooks/c-multi.sh nudge"}]}
]'

# --- case 1: event キー不在 -> 全 entries 設置 ---
echo '{"hooks": {}}' > "$S"
merge_hook_event "PostToolUse" "$ENTRIES" "$S" >/dev/null
n=$(jq '.hooks.PostToolUse | length' "$S")
[ "$n" = "3" ] && ok || miss "case1: expected 3 entries, got $n"

# --- case 2: 冪等 (再実行で無変更) ---
before=$(cat "$S")
merge_hook_event "PostToolUse" "$ENTRIES" "$S" >/dev/null
after=$(cat "$S")
[ "$before" = "$after" ] && ok || miss "case2: not idempotent"

# --- case 3: 部分欠落 -> 欠落分だけ追加 ---
echo '{"hooks": {"PostToolUse": [
  {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/a-guard.sh"}]}
]}}' > "$S"
merge_hook_event "PostToolUse" "$ENTRIES" "$S" >/dev/null
n=$(jq '.hooks.PostToolUse | length' "$S")
[ "$n" = "3" ] && ok || miss "case3: expected 3 after fill, got $n"
jq -e '.hooks.PostToolUse[] | select(.hooks[].command | contains("b-nudge.sh"))' "$S" >/dev/null \
  && ok || miss "case3: b-nudge.sh not added"

# --- case 4: 絶対 path で既存 -> contains 一致で重複追加しない ---
echo '{"hooks": {"PostToolUse": [
  {"matcher": "Bash", "hooks": [{"type": "command", "command": "/opt/claude/hooks/a-guard.sh"}]},
  {"matcher": "Read", "hooks": [{"type": "command", "command": "/opt/claude/hooks/b-nudge.sh"}]},
  {"matcher": "Edit", "hooks": [{"type": "command", "command": "/opt/claude/hooks/c-multi.sh track"}]}
]}}' > "$S"
merge_hook_event "PostToolUse" "$ENTRIES" "$S" >/dev/null
n=$(jq '.hooks.PostToolUse | length' "$S")
[ "$n" = "3" ] && ok || miss "case4: absolute-path entries duplicated (got $n)"

# --- case 5: 引数付き同名 script の別 mode は独立 (track 済でも nudge は別 event に入る) ---
echo '{"hooks": {"PostToolUse": [
  {"matcher": "Edit", "hooks": [{"type": "command", "command": "~/.claude/hooks/c-multi.sh track"}]}
]}}' > "$S"
merge_hook_event "Stop" "$STOP_ENTRIES" "$S" >/dev/null
jq -e '.hooks.Stop[] | select(.hooks[].command | contains("c-multi.sh nudge"))' "$S" >/dev/null \
  && ok || miss "case5: arg-variant hook not installed into Stop"

# --- case 6: 導出リストが JSON と一致 (hardcode 無しの根拠) ---
derived=$(printf '%s' "$ENTRIES" | jq -r '.[].hooks[]?.command | sub("^.*/hooks/"; "")' | tr '\n' ' ')
[ "$derived" = "a-guard.sh b-nudge.sh c-multi.sh track " ] && ok || miss "case6: derived list mismatch: '$derived'"

echo ""
echo "=== Result: PASS=$PASS FAIL=$FAIL ==="
[ "$FAIL" -eq 0 ]
