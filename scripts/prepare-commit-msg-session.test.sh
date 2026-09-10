#!/usr/bin/env bash
# prepare-commit-msg-session.test.sh — prepare-commit-msg-session.sh の selftest
#
# 契約 (run-all-checks.sh §環境依存 test の扱い): 依存が無い時は SKIP を出して exit 0。
# 依存 = git のみ。
#
# 検査:
#   1. session 未設定 → 変化なし (= 人手 commit を汚さない)
#   2. session 設定 → trailer 付与
#   3. 二重実行 → 1 行のまま (冪等)
#   4. 別 session で再実行 → やはり 1 行のまま (= amend / rebase で増殖しない)
#   5. opt-out (claude.sessionTrailer=false) → 付かない
#   6. 不正な session 値 (改行 / 空白 / コロン) → 付かない (injection 拒否)
#   7. 既存 Co-Authored-By と同一 trailer block に入る
#   8. comment 行が保たれ、 trailer は comment より前に入る
#   9. e2e: 実 commit から %(trailers:key=...) で機械抽出できる
#  10. e2e: --amend で増えない

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/prepare-commit-msg-session.sh"

command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 0; }
if [ ! -f "$RUNNER" ]; then
    echo "  ✗ runner not found: $RUNNER"
    exit 1
fi

PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "  ✓ $1"; }
ng() { FAIL=$((FAIL+1)); echo "  ✗ $1"; [ $# -ge 2 ] && printf '%s\n' "$2" | sed 's/^/      /'; }

WORK="$(mktemp -d)" || { echo "SKIP: mktemp -d failed"; exit 0; }
trap 'rm -rf "$WORK"' EXIT

SID="0123abcd-4567-89ef-0123-456789abcdef"
SID2="ffffffff-0000-1111-2222-333333333333"

# hook の実行時 cwd は repo root。 git config を読むので test も repo 内で回す。
REPO="$WORK/repo"
mkdir -p "$REPO"
(
    cd "$REPO" || exit 1
    git init -q . 2>/dev/null
    git config user.email "test@example.invalid"
    git config user.name "Test"
    git config commit.gpgsign false
    # global に core.hooksPath が刺さっていても本 test が壊れないよう明示 (絶対 path)
    git config core.hooksPath "$REPO/.git/hooks"
) || { echo "SKIP: git init failed"; exit 0; }

cd "$REPO" || { echo "SKIP: cannot cd to test repo"; exit 0; }

# ---- 単体 (runner を直接呼ぶ) ----

f="$WORK/m1"; printf 'subject only\n' > "$f"
( unset CLAUDE_CODE_SESSION_ID; bash "$RUNNER" "$f" )
if [ "$(cat "$f")" = "subject only" ]; then
    ok "1. session 未設定 → 変化なし"
else
    ng "1. session 未設定 → 変化なし" "$(cat "$f")"
fi

f="$WORK/m2"; printf 'subject line\n' > "$f"
CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
if grep -qx "Claude-Session: $SID" "$f"; then
    ok "2. session 設定 → trailer 付与"
else
    ng "2. session 設定 → trailer 付与" "$(cat "$f")"
fi

CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
n="$(grep -c '^Claude-Session:' "$f")"
if [ "$n" -eq 1 ]; then
    ok "3. 二重実行 → 1 行のまま (冪等)"
else
    ng "3. 二重実行 → 1 行のまま (冪等)" "count=$n"$'\n'"$(cat "$f")"
fi

CLAUDE_CODE_SESSION_ID="$SID2" bash "$RUNNER" "$f"
n="$(grep -c '^Claude-Session:' "$f")"
if [ "$n" -eq 1 ] && grep -qx "Claude-Session: $SID" "$f"; then
    ok "4. 別 session で再実行 → 増殖せず最初の session を保存"
else
    ng "4. 別 session で再実行 → 増殖せず最初の session を保存" "count=$n"$'\n'"$(cat "$f")"
fi

f="$WORK/m3"; printf 'subject line\n' > "$f"
git config claude.sessionTrailer false
CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
if ! grep -q '^Claude-Session:' "$f"; then
    ok "5. opt-out (claude.sessionTrailer=false) → 付かない"
else
    ng "5. opt-out (claude.sessionTrailer=false) → 付かない" "$(cat "$f")"
fi
git config --unset claude.sessionTrailer

inj_fail=""
for bad in "abc def" "abc:def" "abc
def" "" "abc/../def"; do
    f="$WORK/m4"; printf 'subject line\n' > "$f"
    CLAUDE_CODE_SESSION_ID="$bad" bash "$RUNNER" "$f"
    if grep -q '^Claude-Session:' "$f"; then
        inj_fail="$inj_fail [$bad]"
    fi
done
if [ -z "$inj_fail" ]; then
    ok "6. 不正な session 値 → 付かない (injection 拒否)"
else
    ng "6. 不正な session 値 → 付かない (injection 拒否)" "leaked:$inj_fail"
fi

f="$WORK/m5"
printf 'subject line\n\nbody paragraph.\n\nCo-Authored-By: Someone <s@example.invalid>\n' > "$f"
CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
# 同一 trailer block = Co-Authored-By 行と Claude-Session 行の間に空行が無い
if grep -qx "Claude-Session: $SID" "$f" \
   && awk '/^Co-Authored-By:/{co=NR} /^Claude-Session:/{cs=NR} END{exit !(cs==co+1)}' "$f"; then
    ok "7. 既存 Co-Authored-By と同一 trailer block に入る"
else
    ng "7. 既存 Co-Authored-By と同一 trailer block に入る" "$(cat "$f")"
fi

f="$WORK/m6"
printf 'subject line\n\n# comment kept by git\n# another comment\n' > "$f"
CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
trailer_ln="$(grep -n '^Claude-Session:' "$f" | head -1 | cut -d: -f1)"
comment_ln="$(grep -n '^# comment kept by git' "$f" | head -1 | cut -d: -f1)"
if [ -n "$trailer_ln" ] && [ -n "$comment_ln" ] && [ "$trailer_ln" -lt "$comment_ln" ]; then
    ok "8. comment 行が保たれ、 trailer は comment より前"
else
    ng "8. comment 行が保たれ、 trailer は comment より前" "trailer=$trailer_ln comment=$comment_ln"$'\n'"$(cat "$f")"
fi

# ---- e2e (stub を .git/hooks に置いて実 commit) ----

mkdir -p "$REPO/.git/hooks"
printf '#!/bin/bash\nexec "%s" "$@"\n' "$RUNNER" > "$REPO/.git/hooks/prepare-commit-msg"
chmod +x "$REPO/.git/hooks/prepare-commit-msg"

echo hello > "$REPO/a.txt"
git add a.txt 2>/dev/null
if CLAUDE_CODE_SESSION_ID="$SID" git commit -q -m "e2e subject" 2>/dev/null; then
    got="$(git log -1 --format='%(trailers:key=Claude-Session,valueonly)' | tr -d '\n')"
    if [ "$got" = "$SID" ]; then
        ok "9. e2e: 実 commit から trailer を機械抽出できる"
    else
        ng "9. e2e: 実 commit から trailer を機械抽出できる" "got='$got' want='$SID'"
    fi

    if CLAUDE_CODE_SESSION_ID="$SID2" git commit -q --amend -m "e2e subject amended" 2>/dev/null; then
        n="$(git log -1 --format='%B' | grep -c '^Claude-Session:')"
        if [ "$n" -eq 1 ]; then
            ok "10. e2e: --amend で増えない"
        else
            ng "10. e2e: --amend で増えない" "count=$n"$'\n'"$(git log -1 --format='%B')"
        fi
    else
        echo "  ~ 10. SKIP: git commit --amend failed in sandbox"
    fi
else
    echo "  ~ 9/10. SKIP: git commit failed in sandbox (identity/signing?)"
fi

echo ""
echo "prepare-commit-msg-session.test.sh: PASS=$PASS FAIL=$FAIL"
exit $((FAIL > 0 ? 1 : 0))
