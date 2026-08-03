#!/usr/bin/env bash
# session-commit-nudge.test.sh — self-tests for session-commit-nudge.sh
#
# 設計: hook に claude-code 互換の JSON を stdin で食わせ、 stdout/stderr +
#       exit code を確認。 test isolation は SESSION_TOUCH_STATE_DIR env で
#       state dir を /tmp/test-... に隔離 (= 本物の ~/.claude/state を汚染
#       しない)。
#
# 実行: bash session-commit-nudge.test.sh
#       全 pass で exit 0、 fail があれば exit 1

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/session-commit-nudge.sh"
[ -x "$HOOK" ] || { echo "ERROR: $HOOK not executable"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq required"; exit 1; }

PASS=0
FAIL=0
FAILED_CASES=""

# Isolated state + repo dirs (= test 全 case 共有、 各 case で session_id 分離)
TEST_ROOT="$(mktemp -d -t session-commit-nudge-test.XXXXXX)"
# 被検体 hook は repo path を `git rev-parse --show-toplevel` で得る。 Git for Windows は
# これを native 形式 (= "C:/Users/...") で返す一方、 mktemp -d は MSYS 形式 (= "/tmp/...")
# を返すため、 期待値と実出力が同じ dir を指したまま文字列として一致しない。 生成直後に
# 同じ native 形式へ畳んでおく (cygpath 不在の POSIX では no-op)。
if command -v cygpath >/dev/null 2>&1; then
  TEST_ROOT="$(cygpath -m "$TEST_ROOT")"
fi
export SESSION_TOUCH_STATE_DIR="$TEST_ROOT/state"
mkdir -p "$SESSION_TOUCH_STATE_DIR"

# Cleanup on exit
trap 'rm -rf "$TEST_ROOT"' EXIT

# ----------------------------------------------------------------------
# mk_repo <name>: create a git repo under $TEST_ROOT/repos/<name>,
#                 init with one committed file, echo absolute path
# ----------------------------------------------------------------------
mk_repo() {
  local NAME="$1"
  local REPO="$TEST_ROOT/repos/$NAME"
  mkdir -p "$REPO"
  ( cd "$REPO" && \
    git init --quiet --initial-branch=main && \
    git config user.email "noreply@anthropic.com" && \
    git config user.name "Test" && \
    echo "baseline" > baseline.txt && \
    git add baseline.txt && \
    git commit --quiet -m "init" ) >/dev/null 2>&1
  echo "$REPO"
}

# ----------------------------------------------------------------------
# call_hook <mode> <session_id> <json_body>: invoke hook with stdin
#                                            echo stdout
# ----------------------------------------------------------------------
call_hook() {
  local MODE="$1" SID="$2" BODY="$3"
  printf '%s' "$BODY" | jq --arg sid "$SID" '. + {session_id: $sid}' \
    | "$HOOK" "$MODE" 2>/dev/null
}

# ----------------------------------------------------------------------
# track_edit <session_id> <file_path>: simulate PostToolUse Edit
# ----------------------------------------------------------------------
track_edit() {
  local SID="$1" FPATH="$2"
  local JSON
  JSON="$(jq -n --arg fp "$FPATH" --arg sid "$SID" \
    '{session_id: $sid, tool_input: {file_path: $fp}}')"
  printf '%s' "$JSON" | "$HOOK" track >/dev/null 2>&1
}

# ----------------------------------------------------------------------
# stop_check <session_id>: simulate Stop hook, echo stdout
# ----------------------------------------------------------------------
stop_check() {
  local SID="$1"
  local JSON
  JSON="$(jq -n --arg sid "$SID" \
    '{session_id: $sid, stop_hook_active: false}')"
  printf '%s' "$JSON" | "$HOOK" nudge 2>/dev/null
}

# ----------------------------------------------------------------------
# assert helpers
# ----------------------------------------------------------------------
assert_silent() {
  local name="$1" output="$2"
  if [ -z "$output" ]; then
    PASS=$((PASS+1))
    printf '  ✓ %s (silent)\n' "$name"
  else
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  ✗ ${name} (expected silent, got: $(printf '%s' "$output" | head -1))\n"
    printf '  ✗ %s — got: %s\n' "$name" "$(printf '%s' "$output" | head -1)"
  fi
}

assert_nudge() {
  local name="$1" output="$2" expected_substr="$3"
  if printf '%s' "$output" | grep -q "session-commit-nudge"; then
    if [ -z "$expected_substr" ] || printf '%s' "$output" | grep -q "$expected_substr"; then
      PASS=$((PASS+1))
      printf '  ✓ %s (nudge fired)\n' "$name"
    else
      FAIL=$((FAIL+1))
      FAILED_CASES="${FAILED_CASES}  ✗ ${name} (nudge fired but missing '$expected_substr')\n"
      printf '  ✗ %s (nudge fired but missing %s)\n' "$name" "$expected_substr"
    fi
  else
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  ✗ ${name} (expected nudge, got: $(printf '%s' "$output" | head -1))\n"
    printf '  ✗ %s — expected nudge, got: %s\n' "$name" "$(printf '%s' "$output" | head -1)"
  fi
}

# ======================================================================
# Test cases
# ======================================================================

echo "=== session-commit-nudge.sh tests ==="

# --- case 1: edit + commit → Stop silent ---
SID="sid-case1-$$"
REPO1="$(mk_repo case1)"
echo "v1" > "$REPO1/file1.txt"
track_edit "$SID" "$REPO1/file1.txt"
( cd "$REPO1" && git add file1.txt && git commit --quiet -m "case1 commit" ) >/dev/null 2>&1
OUT="$(stop_check "$SID")"
assert_silent "case 1: edit + commit → silent" "$OUT"

# --- case 2: edit + no commit → nudge ---
SID="sid-case2-$$"
REPO2="$(mk_repo case2)"
echo "v1" > "$REPO2/file1.txt"
track_edit "$SID" "$REPO2/file1.txt"
OUT="$(stop_check "$SID")"
assert_nudge "case 2: edit + no commit → nudge" "$OUT" "$REPO2"

# --- case 3: 2 repos, commit one, leave other dirty → nudge for the dirty one only ---
SID="sid-case3-$$"
REPO3A="$(mk_repo case3a)"
REPO3B="$(mk_repo case3b)"
echo "x" > "$REPO3A/file.txt"
echo "y" > "$REPO3B/file.txt"
track_edit "$SID" "$REPO3A/file.txt"
track_edit "$SID" "$REPO3B/file.txt"
( cd "$REPO3A" && git add file.txt && git commit --quiet -m "case3a commit" ) >/dev/null 2>&1
OUT="$(stop_check "$SID")"
assert_nudge "case 3: split outcome → nudge for dirty only" "$OUT" "$REPO3B"
if printf '%s' "$OUT" | grep -q "$REPO3A"; then
  FAIL=$((FAIL+1))
  FAILED_CASES="${FAILED_CASES}  ✗ case 3 over-report (committed repo also listed)\n"
  printf '  ✗ case 3 over-report — REPO3A should NOT appear\n'
else
  PASS=$((PASS+1))
  printf '  ✓ case 3 no over-report (committed repo silent)\n'
fi

# --- case 4: no edit, no track → silent ---
SID="sid-case4-$$"
OUT="$(stop_check "$SID")"
assert_silent "case 4: no edit → silent" "$OUT"

# --- case 5: edit + revert via git checkout → silent ---
SID="sid-case5-$$"
REPO5="$(mk_repo case5)"
echo "modified" > "$REPO5/baseline.txt"
track_edit "$SID" "$REPO5/baseline.txt"
( cd "$REPO5" && git checkout -- baseline.txt ) >/dev/null 2>&1
OUT="$(stop_check "$SID")"
assert_silent "case 5: edit + revert → silent" "$OUT"

# --- case 6: same dirty state, repeat Stop → 2nd silent (state hash dedup) ---
SID="sid-case6-$$"
REPO6="$(mk_repo case6)"
echo "v1" > "$REPO6/file.txt"
track_edit "$SID" "$REPO6/file.txt"
OUT1="$(stop_check "$SID")"
OUT2="$(stop_check "$SID")"
assert_nudge "case 6a: first Stop with dirty → nudge" "$OUT1" "$REPO6"
assert_silent "case 6b: repeat Stop same state → silent" "$OUT2"

# --- case 7: same repo edited twice (= dedup in touch list) ---
SID="sid-case7-$$"
REPO7="$(mk_repo case7)"
echo "v1" > "$REPO7/file.txt"
track_edit "$SID" "$REPO7/file.txt"
echo "v2" > "$REPO7/file.txt"
track_edit "$SID" "$REPO7/file.txt"
TOUCH_LINES="$(wc -l < "$SESSION_TOUCH_STATE_DIR/$SID.list" 2>/dev/null || echo 0)"
if [ "$TOUCH_LINES" -eq 1 ]; then
  PASS=$((PASS+1))
  printf '  ✓ case 7: dedup in touch list (1 line)\n'
else
  FAIL=$((FAIL+1))
  FAILED_CASES="${FAILED_CASES}  ✗ case 7 dedup failed (lines=$TOUCH_LINES)\n"
  printf '  ✗ case 7 dedup failed (lines=%s)\n' "$TOUCH_LINES"
fi

# --- case 8: file outside any git repo → no add ---
SID="sid-case8-$$"
NONGIT="$TEST_ROOT/nongit-$$"
mkdir -p "$NONGIT"
echo "x" > "$NONGIT/file.txt"
track_edit "$SID" "$NONGIT/file.txt"
if [ -s "$SESSION_TOUCH_STATE_DIR/$SID.list" ]; then
  FAIL=$((FAIL+1))
  FAILED_CASES="${FAILED_CASES}  ✗ case 8 non-git file should not be tracked\n"
  printf '  ✗ case 8 non-git file leaked into touch list\n'
else
  PASS=$((PASS+1))
  printf '  ✓ case 8: non-git file → not tracked\n'
fi

# --- case 9: different session_ids isolated ---
SID_A="sid-case9a-$$"
SID_B="sid-case9b-$$"
REPO9A="$(mk_repo case9a)"
REPO9B="$(mk_repo case9b)"
echo "x" > "$REPO9A/file.txt"
echo "y" > "$REPO9B/file.txt"
track_edit "$SID_A" "$REPO9A/file.txt"
track_edit "$SID_B" "$REPO9B/file.txt"
OUT_A="$(stop_check "$SID_A")"
OUT_B="$(stop_check "$SID_B")"
if printf '%s' "$OUT_A" | grep -q "$REPO9A" && ! printf '%s' "$OUT_A" | grep -q "$REPO9B" \
   && printf '%s' "$OUT_B" | grep -q "$REPO9B" && ! printf '%s' "$OUT_B" | grep -q "$REPO9A"; then
  PASS=$((PASS+1))
  printf '  ✓ case 9: session_id isolation\n'
else
  FAIL=$((FAIL+1))
  FAILED_CASES="${FAILED_CASES}  ✗ case 9 session isolation broken\n"
  printf '  ✗ case 9 session isolation broken\n'
fi

# --- case 10: stop_hook_active=true → silent (recursive guard) ---
SID="sid-case10-$$"
REPO10="$(mk_repo case10)"
echo "x" > "$REPO10/file.txt"
track_edit "$SID" "$REPO10/file.txt"
JSON="$(jq -n --arg sid "$SID" '{session_id: $sid, stop_hook_active: true}')"
OUT="$(printf '%s' "$JSON" | "$HOOK" nudge 2>/dev/null)"
assert_silent "case 10: stop_hook_active=true → silent" "$OUT"

# --- case 11: no jq output JSON → silent (no session_id) ---
OUT="$(echo '{"foo": "bar"}' | "$HOOK" nudge 2>/dev/null)"
assert_silent "case 11: malformed/no session_id → silent" "$OUT"

# ======================================================================
echo ""
echo "=== Result: PASS=$PASS FAIL=$FAIL ==="
if [ "$FAIL" -gt 0 ]; then
  echo ""
  printf 'Failed cases:\n'
  printf '%b\n' "$FAILED_CASES"
  exit 1
fi
exit 0
