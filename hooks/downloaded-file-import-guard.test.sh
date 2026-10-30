#!/usr/bin/env bash
# downloaded-file-import-guard.test.sh — engine の selftest + hook 入出力 (未検査の取り込み → deny / 検査の後は無音 / heredoc・repo の外・accepted・opt-out・Bash 以外・壊れた入力・engine 不在は無音)
#
# 正本: claude-config/hooks/downloaded-file-import-guard.test.sh
# 試す hook は一時 root の hooks/ に写し、 scripts/ は claude-config の scripts への symlink 1 本にする
# (hook は自分の realpath の ../scripts から engine を読む。 承認前の候補の dir からも同じ形で回せる)。

set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_SRC="$SELF_DIR/downloaded-file-import-guard.py"
[ -f "$HOOK_SRC" ] || { echo "FAIL: hook が無い: $HOOK_SRC"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 不在"; exit 0; }
if [ -f "$SELF_DIR/../scripts/downloaded-file-scan.py" ]; then
  SCRIPTS="$(cd "$SELF_DIR/../scripts" && pwd)"
else
  SCRIPTS="${CLAUDE_CONFIG_ROOT:-$HOME/Claude/claude-config}/scripts"
fi
[ -f "$SCRIPTS/downloaded-file-scan.py" ] || { echo "SKIP: engine が無い: $SCRIPTS"; exit 0; }

pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/root/hooks" "$T/bare/hooks" "$T/home/Downloads" "$T/home/repo/.git" "$T/home/repo/docs" "$T/elsewhere"
cp "$HOOK_SRC" "$T/root/hooks/" && cp "$HOOK_SRC" "$T/bare/hooks/"
ln -s "$SCRIPTS" "$T/root/scripts"
HOOK="$T/root/hooks/downloaded-file-import-guard.py"
ENGINE="$T/root/scripts/downloaded-file-scan.py"
# 偽の HOME にすると user site-packages (PyMuPDF) が消え、 engine の PDF の段が SKIP になる = 本物を PYTHONPATH で渡す
USER_SITE="$(python3 -c 'import site; print(site.getusersitepackages())' 2>/dev/null || true)"
[ -n "$USER_SITE" ] && export PYTHONPATH="${USER_SITE}${PYTHONPATH:+:$PYTHONPATH}"
export HOME="$T/home" DOWNLOADED_FILE_SCAN_STATE="$T/state" DOWNLOADED_FILE_SCAN_CLAMSCAN=none
unset CLAUDE_DOWNLOAD_IMPORT_GUARD DOWNLOADED_FILE_SCAN_SOURCES
printf 'plain text\n' > "$T/home/Downloads/notes.txt"
REPO="$T/home/repo"

json() { # <cwd> <command> — harness が渡す key を全部持つ形 (hook-authoring.md#delivery-audit-method の 3 = hook_event_name の無い合成入力にしない)
  python3 -c 'import json,sys; print(json.dumps({"session_id":"test-session","transcript_path":"/nonexistent.jsonl","cwd":sys.argv[1],"permission_mode":"default","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[2],"description":"test"}}))' "$1" "$2"
}
run() { json "$1" "$2" | python3 "$HOOK"; }

echo "=== engine (--selftest) ==="
st="$(python3 "$ENGINE" --selftest 2>&1)"; rc=$?
printf '%s\n' "$st" | tail -1 | sed 's/^/  /'
[ "$rc" -eq 0 ] && ok "engine の selftest" || { printf '%s\n' "$st" | grep FAIL; ng "engine の selftest rc=$rc"; }

echo "=== hook 入出力 ==="
CP="cp ~/Downloads/notes.txt $REPO/docs/"
out="$(run "$REPO" "$CP")"
case "$out" in
  *'"permissionDecision": "deny"'*downloaded-file-scan.py*notes.txt*) ok "未検査の file を repo へ cp → deny + 検査の command" ;;
  *) ng "deny されない: $out" ;;
esac
printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert d["hookEventName"]=="PreToolUse"' \
  && ok "出力は PreToolUse の JSON" || ng "JSON の形が違う"
python3 "$ENGINE" "$T/home/Downloads/notes.txt" >/dev/null 2>&1
out="$(run "$REPO" "$CP")"
[ -z "$out" ] && ok "検査の後の同じ cp は無音" || ng "検査の後も出力: $out"
printf 'changed\n' >> "$T/home/Downloads/notes.txt"
out="$(run "$REPO" "$CP")"
[ -n "$out" ] && ok "中身が変わった file は未検査に戻る" || ng "中身が変わっても無音"
out="$(run "$REPO" "cat > n.md <<'EOF'
$CP
EOF")"
[ -z "$out" ] && ok "heredoc の本文の cp は無音" || ng "heredoc で出力: $out"
out="$(run "$REPO" "cp ~/Downloads/notes.txt $T/elsewhere/")"
[ -z "$out" ] && ok "取り込み先が repo の外は無音" || ng "repo の外で出力: $out"
out="$(run "$REPO" "$CP  # downloaded-file-scan: accepted 本人が決めた")"
[ -z "$out" ] && ok "accepted の印は無音" || ng "accepted で出力: $out"
out="$(json "$REPO" "$CP" | CLAUDE_DOWNLOAD_IMPORT_GUARD=0 python3 "$HOOK")"
[ -z "$out" ] && ok "opt-out (CLAUDE_DOWNLOAD_IMPORT_GUARD=0)" || ng "opt-out が効かない"
out="$(printf '{"session_id":"test-session","hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"x"}}' | python3 "$HOOK")"
[ -z "$out" ] && ok "Bash 以外は無音" || ng "Read で出力: $out"
out="$(printf 'not json' | python3 "$HOOK")"; rc=$?
[ -z "$out" ] && [ "$rc" -eq 0 ] && ok "読めない入力は fail-open" || ng "壊れた入力で rc=$rc out=$out"
out="$(json "$REPO" "$CP" | python3 "$T/bare/hooks/downloaded-file-import-guard.py")"; rc=$?
[ -z "$out" ] && [ "$rc" -eq 0 ] && ok "engine が無い配置は fail-open" || ng "engine 不在で rc=$rc out=$out"

echo "=== 結果: PASS=$pass FAIL=$fail ==="
exit "$fail"
