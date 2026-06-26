#!/usr/bin/env bash
# session-start-claude-account-change.test.sh — self-test for the layer-1 SessionStart hook.

set -u
HOOK="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/session-start-claude-account-change.sh"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
ng()  { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

make_claude_json() {  # $1 = userID
  printf '{"userID":"%s","numStartups":1,"projects":{}}' "$1" > "$TMP/claude.json"
}

run_hook() {  # $1 = extra file path (or empty)
  local extra="${1:-}"
  printf '{"hook_event_name":"SessionStart"}' | \
  CLAUDE_PERSONAL_LAYER=none \
  CLAUDE_ACCT_CHANGE_CLAUDE_JSON="$TMP/claude.json" \
  CLAUDE_ACCT_CHANGE_STASH="$TMP/last-uid" \
  CLAUDE_ACCT_CHANGE_EXTRA_FILE="$extra" \
  bash "$HOOK"
}

# ---------- T1: 非 SessionStart event silent ----------
echo "=== T1: 非 SessionStart silent ==="
make_claude_json "userA"
out="$(printf '{"hook_event_name":"PreToolUse"}' | \
  CLAUDE_PERSONAL_LAYER=none \
  CLAUDE_ACCT_CHANGE_CLAUDE_JSON="$TMP/claude.json" \
  CLAUDE_ACCT_CHANGE_STASH="$TMP/last-uid" \
  bash "$HOOK")"
[ -z "$out" ] && ok "non-SessionStart silent" || ng "non-SessionStart should be silent (got: $out)"

# ---------- T2: claude.json 不在 silent ----------
echo "=== T2: claude.json 不在 silent ==="
rm -f "$TMP/claude.json" "$TMP/last-uid"
out="$(run_hook)"
[ -z "$out" ] && ok "missing claude.json silent" || ng "should silent (got: $out)"

# ---------- T3: 初回検知 → 「初回検知」 surface ----------
echo "=== T3: 初回検知 → surface ==="
make_claude_json "useridA12345"
rm -f "$TMP/last-uid"
out="$(run_hook)"
case "$out" in
  *"初回検知"*"useridA1234"*) ok "初回 detection fires" ;;
  *) ng "初回 missing (got: $out)" ;;
esac
[ "$(cat "$TMP/last-uid" 2>/dev/null)" = "useridA12345" ] && ok "stash updated" || ng "stash not updated"

# ---------- T4: 同 userID → silent ----------
echo "=== T4: 同 userID silent ==="
make_claude_json "useridA12345"
printf 'useridA12345\n' > "$TMP/last-uid"
out="$(run_hook)"
[ -z "$out" ] && ok "no-change silent" || ng "should silent (got: $out)"

# ---------- T5: switch → 「切替検知」 + 「scheduled task」 generic guidance ----------
echo "=== T5: switch → 切替 + generic reconcile ==="
make_claude_json "useridB67890"
printf 'useridA12345\n' > "$TMP/last-uid"
out="$(run_hook)"
case "$out" in
  *"切替検知"*"useridA1234"*"useridB6789"*) ok "switch detection fires" ;;
  *) ng "switch missing (got: $out)" ;;
esac
case "$out" in
  *"scheduled task"*"claude mcp list"*) ok "generic reconcile present" ;;
  *) ng "generic reconcile missing" ;;
esac
[ "$(cat "$TMP/last-uid")" = "useridB67890" ] && ok "stash updated to new" || ng "stash not updated"

# ---------- T6: 2 回目 silent ----------
echo "=== T6: 2 回目 silent ==="
out="$(run_hook)"
[ -z "$out" ] && ok "second run silent" || ng "should silent (got: $out)"

# ---------- T7: 個人層 extension file → 追加 surface ----------
echo "=== T7: extension file 取り込み ==="
make_claude_json "useridC11111"
rm -f "$TMP/last-uid"
printf '%s\n' "- 当機 reconcile: foo bar" > "$TMP/extra.md"
out="$(run_hook "$TMP/extra.md")"
case "$out" in
  *"foo bar"*) ok "extension file content included" ;;
  *) ng "extension content missing (got: $out)" ;;
esac
case "$out" in
  *"個人層"*) ok "extension section labeled" ;;
  *) ng "extension section header missing" ;;
esac

# ---------- T8: userID field 不在 silent ----------
echo "=== T8: userID 不在 silent ==="
printf '{"numStartups":1}' > "$TMP/claude.json"
out="$(run_hook)"
[ -z "$out" ] && ok "missing userID silent" || ng "should silent (got: $out)"

# ---------- T9: desktop surface bridge (~/.claude/surface/) ----------
echo "=== T9: surface bridge writes ~/.claude/surface/ ==="
SURF="$HOME/.claude/surface/claude-account-change.txt"
SURF_BAK=""
[ -f "$SURF" ] && SURF_BAK="$(mktemp)" && cp "$SURF" "$SURF_BAK"
rm -f "$SURF"
make_claude_json "useridD22222"
rm -f "$TMP/last-uid"
out="$(run_hook)"
if [ -f "$SURF" ] && grep -q "切替検知\|初回検知" "$SURF"; then
  ok "surface file written"
else
  ng "surface file not written"
fi
# 復元
if [ -n "$SURF_BAK" ]; then mv "$SURF_BAK" "$SURF"; else rm -f "$SURF"; fi

echo
echo "=== Result: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
