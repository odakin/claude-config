#!/usr/bin/env bash
# shared-tree-stash-guard.test.sh — shared-tree-stash-guard.py の検査 (未 commit の変更がある tree の autostash・stash で deny / clean な tree・list・理由つきは通す / 壊れた入力・engine の不在で黙る)
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/shared-tree-stash-guard.py"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
# 候補の dir から回すときは層1 の checkout の engine を使う
if [ -z "${SHARED_TREE_STASH_ENGINE:-}" ] && [ ! -f "$(dirname "$HOOK")/../scripts/git-stash-shared-tree.py" ]; then
  export SHARED_TREE_STASH_ENGINE="$HOME/Claude/claude-config/scripts/git-stash-shared-tree.py"
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { pass=$((pass+1)); echo "✅ $1"; }
ng() { fail=$((fail+1)); echo "❌ $1"; }
ev() { python3 -c 'import json,sys; print(json.dumps({"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": sys.argv[1], "tool_input": {"command": sys.argv[2]}}))' "$1" "$2"; }
run() { ev "$1" "$2" | env -u CLAUDE_SHARED_TREE_STASH python3 "$HOOK"; }

R="$TMP/repo"
mkdir -p "$R"
git -C "$R" init -q
git -C "$R" config user.email t@example.invalid
git -C "$R" config user.name t
printf 'a\n' > "$R/a.md"
git -C "$R" add a.md
git -C "$R" commit -q -m init

out="$(run "$R" 'git pull -q --rebase --autostash && git push -q')"
[ -z "$out" ] && ok "T1 clean な tree の autostash は通す" || ng "T1 鳴った: $out"

printf 'b\n' >> "$R/a.md"
out="$(run "$R" 'git pull -q --rebase --autostash && git push -q')"
if printf '%s' "$out" | grep -q '"permissionDecision": "deny"' && printf '%s' "$out" | grep -q 'a.md' && printf '%s' "$out" | grep -q 'rev-list'; then
  ok "T2 未 commit の変更がある tree の autostash は deny (path と直し方つき)"
else ng "T2: ${out:-silent}"; fi

out="$(run "$R" 'git stash')"
printf '%s' "$out" | grep -q '"permissionDecision": "deny"' && ok "T3 素の git stash は deny" || ng "T3: ${out:-silent}"

out="$(run "$R" 'git stash list')"
[ -z "$out" ] && ok "T4 git stash list は通す" || ng "T4 鳴った: $out"

out="$(run "$R" 'git stash  # [stash-ok: 自分の scratch の変更だけ]')"
[ -z "$out" ] && ok "T5 理由つきの [stash-ok: …] は通す" || ng "T5 鳴った: $out"

out="$(run "$R" 'git commit -q -m "git stash しない" -- a.md')"
[ -z "$out" ] && ok "T6 quote の中の言及は見ない" || ng "T6 鳴った: $out"

out="$(printf 'not json' | python3 "$HOOK")"; rc=$?
[ -z "$out" ] && [ "$rc" = 0 ] && ok "T7 壊れた入力では黙って exit 0" || ng "T7 rc=$rc out=$out"

mkdir -p "$TMP/lone/hooks"
cp "$HOOK" "$TMP/lone/hooks/"
out="$(ev "$R" 'git stash' | env -u SHARED_TREE_STASH_ENGINE python3 "$TMP/lone/hooks/shared-tree-stash-guard.py")"; rc=$?
[ -z "$out" ] && [ "$rc" = 0 ] && ok "T8 engine が無ければ黙って exit 0" || ng "T8 rc=$rc out=$out"

out="$(ev "$R" 'git stash' | CLAUDE_SHARED_TREE_STASH=0 python3 "$HOOK")"
[ -z "$out" ] && ok "T9 opt-out (CLAUDE_SHARED_TREE_STASH=0)" || ng "T9 鳴った: $out"

python3 "$HOOK" --selftest >/dev/null && ok "T10 engine の --selftest が通る" || ng "T10 selftest が落ちた"

echo "passed=$pass failed=$fail"
[ "$fail" = 0 ]
