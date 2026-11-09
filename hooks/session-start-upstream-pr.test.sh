#!/usr/bin/env bash
# session-start-upstream-pr.test.sh — self-tests for session-start-upstream-pr.sh (配線だけを見る: engine は stub。 判定の中身 = scripts/upstream-pr.py --selftest)
#
# 実行: bash hooks/session-start-upstream-pr.test.sh

set -u
HOOK="$(cd "$(dirname "$0")" && pwd)/session-start-upstream-pr.sh"
[ -f "$HOOK" ] || { echo "ERROR: $HOOK が無い"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 が無い"; exit 0; }

PASS=0
FAIL=0
TEST_ROOT="$(mktemp -d -t session-start-upstream-pr-test.XXXXXX)"
trap 'rm -rf "$TEST_ROOT"' EXIT

STUB="$TEST_ROOT/stub-upstream-pr.py"
printf '%s\n' 'import os, sys' \
  'open(os.environ["STUB_LOG"], "a").write(" ".join(sys.argv[1:]) + "\n")' \
  'cmd = sys.argv[1] if len(sys.argv) > 1 else ""' \
  'say = os.environ.get("STUB_STATUS" if cmd == "status" else "STUB_AFTER", "")' \
  'if say: print(say)' > "$STUB"
export STUB_LOG="$TEST_ROOT/stub.log"
: > "$STUB_LOG"
START='{"hook_event_name": "SessionStart", "source": "startup"}'

run_hook() {  # run_hook <stdin> <status の出力> <after の出力> [env の追加 (KEY=VALUE)]
  local IN="$1" ST="$2" AF="$3"
  shift 3
  printf '%s' "$IN" | env UPSTREAM_PR_ENGINE="$STUB" STUB_STATUS="$ST" STUB_AFTER="$AF" "$@" bash "$HOOK" 2>/dev/null
}

check() {  # check <名前> <期待の部分文字列、 空 = 無出力> <出力>
  local NAME="$1" WANT="$2" OUT="$3"
  if [ -z "$WANT" ]; then
    if [ -z "$OUT" ]; then PASS=$((PASS+1)); printf '  ✓ %s (silent)\n' "$NAME"
    else FAIL=$((FAIL+1)); printf '  ✗ %s — expected silence, got: %s\n' "$NAME" "$(printf '%s' "$OUT" | head -1)"; fi
  else
    case "$OUT" in
      *"$WANT"*) PASS=$((PASS+1)); printf '  ✓ %s\n' "$NAME" ;;
      *) FAIL=$((FAIL+1)); printf '  ✗ %s — missing %s, got: %s\n' "$NAME" "$WANT" "$(printf '%s' "$OUT" | head -1)" ;;
    esac
  fi
}

echo "=== session-start-upstream-pr.sh tests ==="
LINE="📤 claude-config (/x): upstream に入っていない手元の変更 — push できない = fork から PR"
OUT="$(run_hook "$START" "" "")"
check "case 1: engine silent (owner / no changes) → silent" "" "$OUT"
OUT="$(run_hook "$START" "$LINE" "")"
check "case 2: engine has a block → passed on" "$LINE" "$OUT"
check "case 2b: wrapped in one system-reminder" "<system-reminder>" "$OUT"
OUT="$(run_hook "$START" "" "claude-config: PR が merge された: https://example.invalid/pull/1")"
check "case 3: after's notice alone → passed on" "merge された" "$OUT"
OUT="$(run_hook '{"hook_event_name": "Stop"}' "$LINE" "")"
check "case 4: not a SessionStart event → silent" "" "$OUT"
OUT="$(run_hook "$START" "$LINE" "" CLAUDE_UPSTREAM_PR=0)"
check "case 5: kill switch → silent" "" "$OUT"
OUT="$(printf '%s' "$START" | env UPSTREAM_PR_ENGINE="$TEST_ROOT/missing.py" bash "$HOOK" 2>/dev/null)"
check "case 6: engine missing → silent" "" "$OUT"
: > "$STUB_LOG"
run_hook "$START" "" "" >/dev/null
if grep -q -- "status --quiet-errors --timeout 8" "$STUB_LOG" && grep -q -- "after --timeout 8" "$STUB_LOG"; then
  PASS=$((PASS+1)); printf '  ✓ case 7: calls status and after with the network limit\n'
else
  FAIL=$((FAIL+1)); printf '  ✗ case 7: engine calls were: %s\n' "$(tr '\n' '|' < "$STUB_LOG")"
fi

echo ""
echo "=== Result: PASS=$PASS FAIL=$FAIL ==="
[ "$FAIL" -eq 0 ]
