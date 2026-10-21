#!/usr/bin/env bash
# codex-headless-launch-check.test.sh — codex-headless-launch-check.sh の self-test (engine の selftest + hook の入出力)
#
# 正本: claude-config/hooks/codex-headless-launch-check.test.sh
# 実行: bash hooks/codex-headless-launch-check.test.sh (run-all-checks.sh が自動発見)。 候補の dir からも回る:
#       CODEX_HEADLESS_LAUNCH_CHECK_ENGINE=<claude-config>/scripts/codex-headless-launch-check.py bash <候補>/codex-headless-launch-check.test.sh
#
# 歯: engine を外すと block の case が落ちる / 本物の incident の形 (封じた sandbox で REVIEW-SPEC を読ませる headless の起動) を再現する。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/codex-headless-launch-check.sh"
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 0; }
ENGINE="${CODEX_HEADLESS_LAUNCH_CHECK_ENGINE:-$HERE/../scripts/codex-headless-launch-check.py}"
export CODEX_HEADLESS_LAUNCH_CHECK_ENGINE="$ENGINE"
unset CODEX_HEADLESS_LAUNCH_CHECK_DISABLE

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }
j() { python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":sys.argv[2],"tool_input":{"command":sys.argv[1]}}))' "$1" "$2"; }

echo "=== engine selftest ==="
python3 "$ENGINE" --selftest >/dev/null 2>&1 && ok "codex-headless-launch-check --selftest" || ng "engine selftest"

echo "=== hook: incident shape (sealed sandbox, headless exec) ==="
mkdir -p "$TMP/sb"; : > "$TMP/sb/REVIEW-SPEC.md"
CMD="cd \"$TMP/sb\" && caffeinate -i codex exec --json -o \"$TMP/final.txt\" --skip-git-repo-check 'Read REVIEW-SPEC.md in this directory and carry it out. token = T'"
out="$(j "$CMD" "$TMP" | bash "$HOOK" 2>&1)"; rc=$?
[ "$rc" = 2 ] && [[ "$out" == *codex-app-launch.py* ]] && ok "headless 盲検 → exit 2 + アプリに出る起こし方" || ng "incident not blocked (rc=$rc)"
j "CODEX_EXEC_REASON='この機械に Codex アプリが無い' $CMD" "$TMP" | bash "$HOOK" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "理由つき → 通す" || ng "reasoned launch blocked (rc=$rc)"
j "codex exec 'summarise the build log'" "$TMP" | bash "$HOOK" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "掲示板・盲検でない codex exec → 通す" || ng "plain exec blocked (rc=$rc)"
j "git status" "$TMP" | bash "$HOOK" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "codex を含まない Bash → engine を起動しない" || ng "unrelated command blocked (rc=$rc)"
CODEX_HEADLESS_LAUNCH_CHECK_ENGINE="$TMP/none.py" bash "$HOOK" < <(j "$CMD" "$TMP") >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "engine 不在 → fail-open" || ng "engine missing blocked (rc=$rc)"

echo "result: $pass pass / $fail fail"
[ "$fail" = 0 ]
