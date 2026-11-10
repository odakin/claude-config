#!/usr/bin/env bash
# pending-card-rollcall.test.sh — 点呼の Stop hook の鳴る形と黙る形を、 本体の selftest と、 hook の file を直接呼ぶ形の両方で確かめる
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${PENDING_CARDS_ROOT:-$(cd "$HERE/.." && pwd)}"
source "$ROOT/scripts/lib/test-err-trap.sh"
python3 "$ROOT/scripts/pending-cards.py" --selftest
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DESKTOP_SESSIONS_DIR="$TMP/app" PENDING_CARDS_BOARD_ROOTS="$TMP/board" PENDING_CARDS_ENGINE="$ROOT/scripts/pending-cards.py"
mkdir -p "$TMP/app"
NOW="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
cat > "$TMP/t.jsonl" <<JSONL
{"type":"user","timestamp":"$NOW","origin":{"kind":"task-notification"},"message":{"role":"user","content":"<task-notification>x</task-notification>"}}
{"type":"assistant","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_1","name":"mcp__ccd_session__start_session","input":{"initiation":"own_initiative","prompt":"do it"}}]}}
{"type":"user","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_1","content":[{"type":"text","text":"Proposed \"[local推奨] 例の仕事\" (task_id: task_test01). The user sees a card."}]}]}}
{"type":"assistant","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"text","text":"card を出しました。"}]}}
JSONL
run() { printf '%s' "$1" | python3 "$HERE/pending-card-rollcall.py"; }
out="$(run "{\"transcript_path\":\"$TMP/t.jsonl\",\"stop_hook_active\":false}")"
case "$out" in *'"block"'*'1 枚: 例の仕事'*) echo "ok   hook の file: 点呼なし → 止める" ;; *) echo "FAIL 点呼なし: $out"; exit 1 ;; esac
out="$(run "{\"transcript_path\":\"$TMP/t.jsonl\",\"stop_hook_active\":true}")"
[ -z "$out" ] && echo "ok   hook の file: stop_hook_active → 黙る" || { echo "FAIL stop_hook_active: $out"; exit 1; }
out="$(run "{\"transcript_path\":\"$TMP/none.jsonl\"}")"
[ -z "$out" ] && echo "ok   hook の file: 記録が無い → 黙る" || { echo "FAIL 記録なし: $out"; exit 1; }
out="$(PENDING_CARDS_ENGINE="$TMP/missing.py" run "{\"transcript_path\":\"$TMP/t.jsonl\"}")"
[ -z "$out" ] && echo "ok   hook の file: 本体が無い → 黙る" || { echo "FAIL 本体なし: $out"; exit 1; }
echo "PASS"
