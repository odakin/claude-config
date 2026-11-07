#!/usr/bin/env bash
# foreign-hunk-commit-nudge.test.sh — engine の selftest + hook 入出力 (相手の hunk → 知らせ / 自分の hunk だけ → 無音 / deny・off / 壊れた入力・engine 不在は無音)
#
# 正本: claude-config/hooks/foreign-hunk-commit-nudge.test.sh。 engine は FOREIGN_HUNK_ENGINE か、 この file の 1 つ上の scripts/

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/foreign-hunk-commit-nudge.py"
ENGINE="${FOREIGN_HUNK_ENGINE:-$HERE/../scripts/foreign-hunk-check.py}"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 不在"; exit 0; }
command -v git >/dev/null 2>&1 || { echo "SKIP: git 不在"; exit 0; }

pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

echo "=== engine (--selftest) ==="
st="$(python3 "$ENGINE" --selftest 2>&1)"; rc=$?
printf '%s\n' "$st" | tail -1 | sed 's/^/  /'
[ "$rc" -eq 0 ] && ok "engine selftest" || ng "engine selftest rc=$rc"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z
R="$TMP/repo"; mkdir -p "$R"
git -C "$R" init -q -b main
git -C "$R" -c user.email=t@example.invalid -c user.name=t commit -q --allow-empty -m init
printf '# Doc\n\nbase line of the doc\n' > "$R/doc.md"
git -C "$R" add doc.md
git -C "$R" -c user.email=t@example.invalid -c user.name=t commit -q -m doc --no-verify
printf '# Doc\n\nbase line of the doc\nmy own added sentence\n' > "$R/doc.md"

TR="$TMP/s.jsonl"
python3 - "$TR" "$R/doc.md" <<'EOF'
import json, sys
tr, doc = sys.argv[1:3]
with open(tr, "w") as f:
    f.write(json.dumps({"type": "assistant", "timestamp": "2000-01-01T00:00:01Z", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Edit",
         "input": {"file_path": doc, "old_string": "base line of the doc\n", "new_string": "base line of the doc\nmy own added sentence\n"}}]}}) + "\n")
EOF
payload() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","cwd":sys.argv[1],"transcript_path":sys.argv[2],"tool_input":{"command":sys.argv[3]}}))' "$R" "$TR" "$1"; }
run() { FOREIGN_HUNK_ENGINE="$ENGINE" python3 "$HOOK"; }

echo "=== hook 入出力 ==="
out="$(payload "git commit -q -m m -- doc.md" | env -u FOREIGN_HUNK_MODE FOREIGN_HUNK_ENGINE="$ENGINE" python3 "$HOOK")"
[ -z "$out" ] && ok "自分の hunk だけ → 無音" || ng "自分の hunk だけで出力: $out"

printf '# Doc\n\nthe other session added this\n\nbase line of the doc\nmy own added sentence\n' > "$R/doc.md"
out="$(payload "git commit -q -m m -- doc.md" | env -u FOREIGN_HUNK_MODE FOREIGN_HUNK_ENGINE="$ENGINE" python3 "$HOOK")"
case "$out" in
  *additionalContext*'doc.md:3'*'other session added this'*'git-commit-own-hunk.py'*) ok "相手の hunk → file・行・最初の行・道具を名指して知らせる" ;;
  *) ng "知らせが出ない / 形が違う: $out" ;;
esac
case "$out" in
  *permissionDecision*) ng "既定 (notice) なのに decision を出した" ;;
  *) ok "既定は止めない (decision を出さない)" ;;
esac
printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert d["hookEventName"]=="PreToolUse"' \
  && ok "出力は PreToolUse の JSON" || ng "JSON 形が違う"

out="$(payload "git commit -q -m m -- doc.md" | FOREIGN_HUNK_MODE=deny FOREIGN_HUNK_ENGINE="$ENGINE" python3 "$HOOK")"
case "$out" in *'"permissionDecision": "deny"'*) ok "FOREIGN_HUNK_MODE=deny → deny" ;; *) ng "deny されない: $out" ;; esac
out="$(payload "git commit -q -m m -- doc.md" | FOREIGN_HUNK_MODE=off FOREIGN_HUNK_ENGINE="$ENGINE" python3 "$HOOK")"
[ -z "$out" ] && ok "FOREIGN_HUNK_MODE=off → 無音" || ng "off で出力: $out"
out="$(payload "git status" | env -u FOREIGN_HUNK_MODE FOREIGN_HUNK_ENGINE="$ENGINE" python3 "$HOOK")"
[ -z "$out" ] && ok "git commit の無い command → 無音" || ng "commit 無しで出力: $out"
out="$(printf 'not json' | FOREIGN_HUNK_ENGINE="$ENGINE" python3 "$HOOK")"; rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && ok "壊れた入力 → 無音で通す" || ng "壊れた入力 rc=$rc out=$out"
# engine が無いと入口は stdin を読まずに終わる = pipe で渡すと、 後から書く payload の側が閉じた pipe に当たり
# pipefail で rc が 120 になる (入口ではなく試験の競合)。 file から渡して入口の終了値だけを見る
payload "git commit -q -m m -- doc.md" > "$TMP/payload.json"
out="$(FOREIGN_HUNK_ENGINE="$TMP/missing.py" python3 "$HOOK" < "$TMP/payload.json")"; rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && ok "engine 不在 → 無音で通す" || ng "engine 不在 rc=$rc out=$out"
out="$(python3 -c 'import json; print(json.dumps({"tool_name":"Edit","tool_input":{"file_path":"x"}}))' | FOREIGN_HUNK_ENGINE="$ENGINE" python3 "$HOOK")"
[ -z "$out" ] && ok "Bash 以外 → 無音" || ng "Bash 以外で出力: $out"

echo "foreign-hunk-commit-nudge test: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
