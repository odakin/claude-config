#!/usr/bin/env bash
# staged-conflict-markers.test.sh — staged-conflict-markers.sh の self-test (hermetic)
#
# fixture の conflict marker は printf で動的構築する (= 本 test file 自体が行頭 marker
# literal を持つと、 gate 自身 + run-all-checks 検査 6 に self-hit するため。
# CLAUDE.md §Test file の literal 禁止 と同系の test-file discipline)。
set -u

LIB="$(cd "$(dirname "$0")" && pwd)/staged-conflict-markers.sh"
if [ ! -f "$LIB" ]; then
    echo "SKIP: lib not found: $LIB"
    exit 0
fi
# shellcheck source=/dev/null
. "$LIB"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP" || exit 1
git init -q .
git config user.email "noreply@anthropic.com"
git config user.name "test"
git config commit.gpgsign false

# 行頭 marker を動的構築 (literal 禁止)
MK_OPEN="$(printf '<%.0s' 1 2 3 4 5 6 7)"    # <<<<<<<
MK_CLOSE="$(printf '>%.0s' 1 2 3 4 5 6 7)"   # >>>>>>>

PASS=0; FAIL=0
check() {
    # $1 = expected rc (0/1), $2 = label
    local exp="$1" label="$2" rc
    if check_staged_conflict_markers >/dev/null 2>&1; then rc=0; else rc=1; fi
    if [ "$rc" = "$exp" ]; then
        PASS=$((PASS + 1)); echo "✅ $label (rc=$rc)"
    else
        FAIL=$((FAIL + 1)); echo "❌ $label (expected rc=$exp, got rc=$rc)"
    fi
}

# T1: clean file → pass
echo "hello" > a.txt
git add a.txt
check 0 "T1 clean staged file → pass"
git commit -qm "a"

# T2: 行頭 marker 入り staged → block
{
    printf '%s HEAD\n' "$MK_OPEN"
    echo "body"
    printf '%s some-branch\n' "$MK_CLOSE"
} > b.txt
git add b.txt
check 1 "T2 行頭 marker staged → block"
git reset -q -- b.txt && rm -f b.txt

# T3: indent された marker (引用) → pass
printf '    %s HEAD (quoted example)\n' "$MK_OPEN" > c.txt
git add c.txt
check 0 "T3 indent 引用 marker → pass"
git commit -qm "c"

# T4: marker は working tree のみ・index は clean → pass (gate は index を読む)
echo "clean" > d.txt
git add d.txt
printf '%s HEAD\n' "$MK_OPEN" >> d.txt   # worktree のみ汚す
check 0 "T4 worktree のみ汚染 (index clean) → pass"
git checkout -q -- d.txt 2>/dev/null || true
git commit -qm "d"

# T5: escape hatch env → pass
printf '%s HEAD\n' "$MK_OPEN" > e.txt
git add e.txt
_rc=0
CLAUDE_SKIP_CONFLICT_GATE=1
export CLAUDE_SKIP_CONFLICT_GATE
if check_staged_conflict_markers >/dev/null 2>&1; then _rc=0; else _rc=1; fi
unset CLAUDE_SKIP_CONFLICT_GATE
if [ "$_rc" = "0" ]; then PASS=$((PASS + 1)); echo "✅ T5 CLAUDE_SKIP_CONFLICT_GATE=1 → pass"; else FAIL=$((FAIL + 1)); echo "❌ T5 escape hatch が効かない"; fi
git reset -q -- e.txt && rm -f e.txt

# T6: binary file 内の marker bytes → pass (grep -I)
printf 'BIN\000\000\n%s HEAD\n' "$MK_OPEN" > f.bin
git add f.bin
check 0 "T6 binary file → pass (grep -I)"
git reset -q -- f.bin && rm -f f.bin

# T7: 削除 commit (D) は scan 対象外 → pass
git rm -q c.txt
check 0 "T7 削除のみ staged → pass (diff-filter=ACMR)"

echo "--- staged-conflict-markers.test: PASS=$PASS FAIL=$FAIL ---"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
