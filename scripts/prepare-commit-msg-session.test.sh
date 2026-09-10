#!/usr/bin/env bash
# prepare-commit-msg-session.test.sh — prepare-commit-msg-session.sh の selftest
#
# 契約 (run-all-checks.sh §環境依存 test の扱い): 依存が無い時は SKIP を出して exit 0。
# 依存 = git のみ。
#
# 検査:
#   - session 未設定 → 変化なし (= 人手 commit を汚さない)
#   - Claude / Codex / 明示 vendor-neutral source → Agent-Session trailer
#   - 別 session / 別 vendor / legacy trailer / amend でも最初の carrier を保存
#   - generic + legacy opt-out、message injection 拒否、comment/trailer 構造
#   - e2e commit から %(trailers:key=...) で機械抽出できる

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
( unset CLAUDE_CONFIG_AGENT_SESSION CLAUDE_CODE_SESSION_ID CODEX_SESSION_ID CODEX_THREAD_ID; bash "$RUNNER" "$f" )
if [ "$(cat "$f")" = "subject only" ]; then
    ok "1. session 未設定 → 変化なし"
else
    ng "1. session 未設定 → 変化なし" "$(cat "$f")"
fi

f="$WORK/m2"; printf 'subject line\n' > "$f"
CLAUDE_CODE_SESSION_ID="$SID" CLAUDE_CONFIG_AGENT_MODEL="claude-opus-test" \
  CLAUDE_EFFORT="high" bash "$RUNNER" "$f"
if grep -qx "Agent-Session: claude:$SID" "$f" \
   && grep -qx "Agent-Model: claude-opus-test" "$f" \
   && grep -qx "Agent-Effort: high" "$f"; then
    ok "2. Claude session → agent/model/effective-effort trailer"
else
    ng "2. Claude session → agent/model/effective-effort trailer" "$(cat "$f")"
fi

CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
n="$(grep -c '^Agent-Session:' "$f")"
if [ "$n" -eq 1 ]; then
    ok "3. 二重実行 → 1 行のまま (冪等)"
else
    ng "3. 二重実行 → 1 行のまま (冪等)" "count=$n"$'\n'"$(cat "$f")"
fi

f="$WORK/m3"; printf 'subject line\n' > "$f"
( unset CLAUDE_CONFIG_AGENT_SESSION CLAUDE_CODE_SESSION_ID CODEX_THREAD_ID; \
  CODEX_SESSION_ID="$SID" CLAUDE_CONFIG_AGENT_MODEL="gpt-test" \
  CLAUDE_CONFIG_AGENT_EFFORT="xhigh" bash "$RUNNER" "$f" )
if grep -qx "Agent-Session: codex:$SID" "$f" \
   && grep -qx "Agent-Model: gpt-test" "$f" \
   && grep -qx "Agent-Effort: xhigh" "$f"; then
    ok "4. Codex session env → agent/model/effort trailer"
else
    ng "4. Codex session env → agent/model/effort trailer" "$(cat "$f")"
fi

f="$WORK/m4"; printf 'subject line\n' > "$f"
STATE_DIR="$WORK/state"
mkdir -p "$STATE_DIR"
printf 'model=gpt-cached\neffort=medium\n' > "$STATE_DIR/$SID2.env"
( unset CLAUDE_CONFIG_AGENT_SESSION CLAUDE_CODE_SESSION_ID CODEX_SESSION_ID; \
  CODEX_THREAD_ID="$SID2" CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR="$STATE_DIR" \
  bash "$RUNNER" "$f" )
if grep -qx "Agent-Session: codex:$SID2" "$f" \
   && grep -qx "Agent-Model: gpt-cached" "$f" \
   && grep -qx "Agent-Effort: medium" "$f"; then
    ok "5. Codex thread fallback + hook metadata cache → trailer"
else
    ng "5. Codex thread fallback + hook metadata cache → trailer" "$(cat "$f")"
fi

f="$WORK/m5"; printf 'subject line\n' > "$f"
CLAUDE_CONFIG_AGENT_SESSION="worker:$SID" CLAUDE_CONFIG_AGENT_MODEL="model-v1" \
  CLAUDE_CONFIG_AGENT_EFFORT="low" bash "$RUNNER" "$f"
if grep -qx "Agent-Session: worker:$SID" "$f" \
   && grep -qx "Agent-Model: model-v1" "$f" \
   && grep -qx "Agent-Effort: low" "$f"; then
    ok "6. 明示 vendor-neutral metadata → trailer"
else
    ng "6. 明示 vendor-neutral metadata → trailer" "$(cat "$f")"
fi

( unset CLAUDE_CONFIG_AGENT_SESSION CLAUDE_CODE_SESSION_ID CODEX_THREAD_ID; CODEX_SESSION_ID="$SID2" bash "$RUNNER" "$f" )
n="$(grep -c '^Agent-Session:' "$f")"
if [ "$n" -eq 1 ] && grep -qx "Agent-Session: worker:$SID" "$f"; then
    ok "7. 別 vendor で再実行 → 最初の session を保存"
else
    ng "7. 別 vendor で再実行 → 最初の session を保存" "count=$n"$'\n'"$(cat "$f")"
fi

f="$WORK/m6"; printf 'subject line\n' > "$f"
git config agent.sessionTrailer false
CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
if ! grep -q '^Agent-Session:' "$f"; then
    ok "8. opt-out (agent.sessionTrailer=false) → 付かない"
else
    ng "8. opt-out (agent.sessionTrailer=false) → 付かない" "$(cat "$f")"
fi
git config --unset agent.sessionTrailer

git config claude.sessionTrailer false
CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
if ! grep -q '^Agent-Session:' "$f"; then
    ok "9. legacy opt-out (claude.sessionTrailer=false) → 付かない"
else
    ng "9. legacy opt-out (claude.sessionTrailer=false) → 付かない" "$(cat "$f")"
fi
git config --unset claude.sessionTrailer

inj_fail=""
for bad in "codex:abc def" "codex:abc:def" "codex:abc
def" "" "codex:abc/../def" ":abc"; do
    f="$WORK/m7"; printf 'subject line\n' > "$f"
    ( unset CLAUDE_CODE_SESSION_ID CODEX_SESSION_ID CODEX_THREAD_ID; \
      CLAUDE_CONFIG_AGENT_SESSION="$bad" bash "$RUNNER" "$f" )
    if grep -q '^Agent-Session:' "$f"; then
        inj_fail="$inj_fail [$bad]"
    fi
done
if [ -z "$inj_fail" ]; then
    ok "10. 不正な session 値 → 付かない (injection 拒否)"
else
    ng "10. 不正な session 値 → 付かない (injection 拒否)" "leaked:$inj_fail"
fi

f="$WORK/m8"; printf 'subject line\n' > "$f"
( unset CLAUDE_CONFIG_AGENT_SESSION CLAUDE_CONFIG_AGENT_MODEL CLAUDE_CONFIG_AGENT_EFFORT \
  CLAUDE_CODE_SESSION_ID CODEX_THREAD_ID CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR; \
  CODEX_HOME="$WORK/no-codex-home" CODEX_SESSION_ID="$SID" bash "$RUNNER" "$f" )
if grep -qx 'Agent-Model: unknown' "$f" && grep -qx 'Agent-Effort: unknown' "$f"; then
    ok "11. metadata 不明 → 捏造せず unknown"
else
    ng "11. metadata 不明 → 捏造せず unknown" "$(cat "$f")"
fi

f="$WORK/m9"
printf 'subject line\n\nbody paragraph.\n\nCo-Authored-By: Someone <s@example.invalid>\n' > "$f"
CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
# 同一 trailer block = Co-Authored-By 行と Agent-Session 行の間に空行が無い
if grep -qx "Agent-Session: claude:$SID" "$f" \
   && awk '/^Co-Authored-By:/{co=NR} /^Agent-Session:/{as=NR} /^Agent-Model:/{am=NR} /^Agent-Effort:/{ae=NR} END{exit !(as==co+1 && am==as+1 && ae==am+1)}' "$f"; then
    ok "12. 既存 Co-Authored-By と同一 trailer block に入る"
else
    ng "12. 既存 Co-Authored-By と同一 trailer block に入る" "$(cat "$f")"
fi

f="$WORK/m10"
printf 'subject line\n\n# comment kept by git\n# another comment\n' > "$f"
CLAUDE_CODE_SESSION_ID="$SID" bash "$RUNNER" "$f"
trailer_ln="$(grep -n '^Agent-Session:' "$f" | head -1 | cut -d: -f1)"
comment_ln="$(grep -n '^# comment kept by git' "$f" | head -1 | cut -d: -f1)"
if [ -n "$trailer_ln" ] && [ -n "$comment_ln" ] && [ "$trailer_ln" -lt "$comment_ln" ]; then
    ok "13. comment 行が保たれ、 trailer は comment より前"
else
    ng "13. comment 行が保たれ、 trailer は comment より前" "trailer=$trailer_ln comment=$comment_ln"$'\n'"$(cat "$f")"
fi

f="$WORK/m11"
printf 'subject line\n\nClaude-Session: %s\n' "$SID" > "$f"
( unset CLAUDE_CONFIG_AGENT_SESSION CLAUDE_CODE_SESSION_ID CODEX_THREAD_ID; CODEX_SESSION_ID="$SID2" bash "$RUNNER" "$f" )
if grep -qx "Claude-Session: $SID" "$f" && ! grep -q '^Agent-Session:' "$f"; then
    ok "14. legacy trailer → 新 key を増殖させず最初の session を保存"
else
    ng "14. legacy trailer → 新 key を増殖させず最初の session を保存" "$(cat "$f")"
fi

# ---- e2e (stub を .git/hooks に置いて実 commit) ----

mkdir -p "$REPO/.git/hooks"
printf '#!/bin/bash\nexec "%s" "$@"\n' "$RUNNER" > "$REPO/.git/hooks/prepare-commit-msg"
chmod +x "$REPO/.git/hooks/prepare-commit-msg"

echo hello > "$REPO/a.txt"
git add a.txt 2>/dev/null
if CLAUDE_CONFIG_AGENT_SESSION="codex:$SID" CLAUDE_CONFIG_AGENT_MODEL="gpt-test" \
  CLAUDE_CONFIG_AGENT_EFFORT="xhigh" git commit -q -m "e2e subject" 2>/dev/null; then
    got="$(git log -1 --format='%(trailers:key=Agent-Session,valueonly)' | tr -d '\n')"
    if [ "$got" = "codex:$SID" ]; then
        ok "15. e2e: 実 commit から trailer を機械抽出できる"
    else
        ng "15. e2e: 実 commit から trailer を機械抽出できる" "got='$got' want='codex:$SID'"
    fi

    if CLAUDE_CONFIG_AGENT_SESSION="claude:$SID2" CLAUDE_CONFIG_AGENT_MODEL="claude-test" \
      CLAUDE_CONFIG_AGENT_EFFORT="high" git commit -q --amend -m "e2e subject amended" 2>/dev/null; then
        n="$(git log -1 --format='%B' | grep -c '^Agent-Session:')"
        if [ "$n" -eq 1 ] \
          && [ "$(git log -1 --format='%(trailers:key=Agent-Session,valueonly)' | tr -d '\n')" = "claude:$SID2" ] \
          && [ "$(git log -1 --format='%(trailers:key=Agent-Model,valueonly)' | tr -d '\n')" = "claude-test" ]; then
            ok "16. e2e: --amend -m は 1 block のまま amending session を記録"
        else
            ng "16. e2e: --amend -m は 1 block のまま amending session を記録" "count=$n"$'\n'"$(git log -1 --format='%B')"
        fi
    else
        echo "  ~ 16. SKIP: git commit --amend failed in sandbox"
    fi
else
    echo "  ~ 15/16. SKIP: git commit failed in sandbox (identity/signing?)"
fi

echo ""
echo "prepare-commit-msg-session.test.sh: PASS=$PASS FAIL=$FAIL"
exit $((FAIL > 0 ? 1 : 0))
