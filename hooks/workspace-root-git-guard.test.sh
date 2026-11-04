#!/usr/bin/env bash
# workspace-root-git-guard.test.sh — engine の selftest + hook 入出力 (作業ルートの git init = deny / path を書いた形・Bash 以外・読めない入力 = 無音)
#
# 正本: claude-config/hooks/workspace-root-git-guard.test.sh

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/workspace-root-git-guard.py"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 不在 — selftest 省略"; exit 0; }

pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

echo "=== 述語 (engine の --selftest) ==="
st="$(python3 "$HOOK" --selftest 2>&1)"; rc=$?
printf '%s\n' "$st" | sed 's/^/  /'
[ "$rc" -eq 0 ] && ok "selftest" || ng "selftest rc=$rc"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/ws/a/.git" "$TMP/ws/b/.git"
json() { # <tool> <cwd> <command>
  python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[1],"cwd":sys.argv[2],"tool_input":{"command":sys.argv[3]}}))' "$1" "$2" "$3"
}

echo "=== hook 入出力 ==="
out="$(json Bash "$TMP/ws" "git init -q && git add main.tex" | python3 "$HOOK")"
case "$out" in
  *'"permissionDecision": "deny"'*'git init <dir>'*) ok "作業ルートの path の無い git init + add → deny + 直し方" ;;
  *) ng "deny にならない: $out" ;;
esac
out="$(json Bash "$TMP/ws" "git init -q newrepo && git -C newrepo add x" | python3 "$HOOK")"
[ -z "$out" ] && ok "path を書いた git init / -C の add → 無音" || ng "path を書いた形で出た: $out"
out="$(json Bash "$TMP/ws/a" "git add x && git commit -m y" | python3 "$HOOK")"
[ -z "$out" ] && ok "子の repo の中の add / commit → 無音" || ng "子の repo の中で出た: $out"
out="$(json Write "$TMP/ws" "git init" | python3 "$HOOK")"
[ -z "$out" ] && ok "Bash 以外の tool → 無音" || ng "Bash 以外で出た: $out"
out="$(printf 'not json' | python3 "$HOOK")"; rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && ok "読めない入力 → 無音で exit 0 (fail-open)" || ng "読めない入力: rc=$rc out=$out"

echo "--- $pass passed, $fail failed"
[ "$fail" -eq 0 ]
