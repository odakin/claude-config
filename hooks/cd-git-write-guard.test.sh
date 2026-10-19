#!/usr/bin/env bash
# cd-git-write-guard.test.sh — 述語の selftest + hook 入出力 (deny の JSON / cd なしは無音 / opt-out / Bash 以外は無音)
#
# 正本: claude-config/hooks/cd-git-write-guard.test.sh

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/cd-git-write-guard.py"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 不在 — selftest 省略"; exit 0; }

pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

echo "=== 述語 (--selftest) ==="
st="$(python3 "$HOOK" --selftest 2>&1)"; rc=$?
printf '%s\n' "$st" | sed 's/^/  /'
[ "$rc" -eq 0 ] && ok "selftest" || ng "selftest rc=$rc"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/here" "$TMP/repo"
json() { # <cwd> <command>
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","cwd":sys.argv[1],"tool_input":{"command":sys.argv[2]}}))' "$1" "$2"
}

echo "=== hook 入出力 ==="
out="$(json "$TMP/here" "cd $TMP/repo && git add a && git commit -q -m m -- a && git push -q" | env -u CLAUDE_CD_GIT_GUARD python3 "$HOOK")"
case "$out" in
  *'"permissionDecision": "deny"'*'cd <repo>'*) ok "別 dir への cd + commit/push → deny + 直し方" ;;
  *) ng "deny されない: $out" ;;
esac
case "$out" in
  *commit-from-origin-worktree.py*) ok "止めの文に subagent の commit の経路がある" ;;
  *) ng "止めの文に subagent の経路が無い: $out" ;;
esac
printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert d["hookEventName"]=="PreToolUse"' \
  && ok "出力は PreToolUse の JSON" || ng "JSON 形が違う"
out="$(json "$TMP/repo" "cd $TMP/repo && git commit -q -m m -- a && git push -q" | env -u CLAUDE_CD_GIT_GUARD python3 "$HOOK")"
[ -z "$out" ] && ok "行き先が今の作業ディレクトリと同じ cd は通す" || ng "同じ dir の cd で出力: $out"
out="$(json "$TMP/repo" "git add a && git commit -q -m m -- a && git push -q" | env -u CLAUDE_CD_GIT_GUARD python3 "$HOOK")"
[ -z "$out" ] && ok "cd なしの git 連結は通す" || ng "cd なしで出力: $out"
out="$(json "$TMP/here" "git -C $TMP/repo push" | env -u CLAUDE_CD_GIT_GUARD python3 "$HOOK")"
[ -n "$out" ] && ok "git -C … push → deny" || ng "git -C … push で無音"
out="$(json "$TMP/here" "cd $TMP/repo && git push" | CLAUDE_CD_GIT_GUARD=0 python3 "$HOOK")"
[ -z "$out" ] && ok "opt-out (CLAUDE_CD_GIT_GUARD=0)" || ng "opt-out が効かない"
out="$(printf '{"tool_name":"Read","tool_input":{"file_path":"x"}}' | python3 "$HOOK")"
[ -z "$out" ] && ok "Bash 以外は無音" || ng "Read で出力: $out"
out="$(printf 'not json' | python3 "$HOOK")"; rc=$?
[ -z "$out" ] && [ "$rc" -eq 0 ] && ok "読めない入力は fail-open" || ng "壊れた入力で rc=$rc out=$out"

echo "=== 結果: PASS=$pass FAIL=$fail ==="
exit "$fail"
