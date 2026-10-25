#!/usr/bin/env bash
# workflow-fanout-check.test.sh — workflow-fanout-check.sh の self-test (hermetic)
#
# 正本: claude-config/hooks/workflow-fanout-check.test.sh
# 実行: bash hooks/workflow-fanout-check.test.sh (run-all-checks.sh が自動発見)。 承認の前の候補の写しからも回る
#       (engine = env WORKFLOW_FANOUT_ENGINE か、 隣の ../scripts/ か、 ~/Claude/claude-config/scripts/)。
#
# 象限: pass (Workflow 以外の tool / 宣言のある script / enforce の印が無い = 数だけ出す / DISABLE / node が無い・engine が
#       無い・入力が読めない = fail-open) と block (enforce の印があり、 宣言の無い並べすぎ・観点の分割)。 印は temp dir。
# 歯: engine の judge が問題を返さなくなると block の 2 case が落ちる。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/workflow-fanout-check.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 0; }
command -v node >/dev/null 2>&1 || { echo "SKIP: node not available (the engine dry-runs scripts with node)"; exit 0; }
if [ -z "${WORKFLOW_FANOUT_ENGINE:-}" ]; then
  for c in "$HERE/../scripts/workflow-estimate.py" "$HOME/Claude/claude-config/scripts/workflow-estimate.py"; do
    [ -f "$c" ] && { WORKFLOW_FANOUT_ENGINE="$c"; break; }
  done
fi
[ -f "${WORKFLOW_FANOUT_ENGINE:-}" ] || { echo "FAIL: engine not found"; exit 1; }
export WORKFLOW_FANOUT_ENGINE

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export WORKFLOW_FANOUT_ENFORCE_MARKER="$TMP/enforce.on"
unset WORKFLOW_FANOUT_DISABLE WORKFLOW_FANOUT_ENFORCE WORKFLOW_ESTIMATE_NODE

pass=0; fail=0; results=()

ev() { # <script text> [<tool name>] -> hook input JSON
  python3 -c 'import json, sys; print(json.dumps({"hook_event_name": "PreToolUse", "tool_name": sys.argv[2], "tool_input": {"script": sys.argv[1]}}))' "$1" "${2:-Workflow}"
}

run() { # <json> -> "rc=<n> out=<stdout+stderr>"
  local out rc
  out="$(printf '%s' "$1" | bash "$HOOK" 2>&1)"; rc=$?
  printf 'rc=%s out=%s' "$rc" "$out"
}

check() { # <label> <expect rc> <json> [<output must contain>]
  local label="$1" expect="$2" json="$3" needle="${4:-}" got rc
  got="$(run "$json")"; rc="${got#rc=}"; rc="${rc%% *}"
  if [ "$rc" = "$expect" ] && { [ -z "$needle" ] || [[ "$got" == *"$needle"* ]]; }; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect rc=$expect got: ${got:0:200})")
  fi
}

BIG='export const meta = { name: "t", description: "t" }
const S = { type: "object", properties: { tasks: { type: "array", items: { type: "object", properties: { title: { type: "string" } } } } } }
const ITEMS = ["a", "b", "c", "d"]
await pipeline(ITEMS, it => agent("read " + it, { label: "read:" + it, schema: S }),
  (r, it) => parallel(r.tasks.map(t => () => parallel(["state", "rules"].map(l => () => agent("v " + it + t.title + l, { label: "verify:" + it + ":" + l }))))))'
DECL='export const meta = { name: "t", description: "t" }
// workflow-size: 9 — 4 入力を読み、 入力ごとに 1 本で判定、 批評 1
const ITEMS = ["a", "b", "c", "d"]
await pipeline(ITEMS, it => agent("read " + it, { label: "read:" + it }), (r, it) => agent("verify all " + it, { label: "verify:" + it }))
await agent("critic", { label: "critic" })'

check "other tool passes silently"                0 "$(ev "$BIG" Bash)"
check "no enforce marker: exit 0 with the numbers" 0 "$(ev "$BIG")" "additionalContext"
touch "$WORKFLOW_FANOUT_ENFORCE_MARKER"
check "enforce: undeclared fan-out is stopped"    2 "$(ev "$BIG")" "宣言の無い点"
check "enforce: the stop names the lens split"     2 "$(ev "$BIG")" "観点"
check "enforce: a declared script passes"         0 "$(ev "$DECL")"
WORKFLOW_FANOUT_DISABLE=1 check "DISABLE=1 passes" 0 "$(ev "$BIG")"
WORKFLOW_ESTIMATE_NODE="$TMP/no-node" check "no node: fail-open" 0 "$(ev "$BIG")"
WORKFLOW_FANOUT_ENGINE="$TMP/missing.py" check "missing engine: fail-open" 0 "$(ev "$BIG")"
check "unreadable input: fail-open"               0 "not json"

printf '%s\n' "${results[@]}"
echo "workflow-fanout-check.test.sh: $pass passed, $fail failed"
[ "$fail" = 0 ]
