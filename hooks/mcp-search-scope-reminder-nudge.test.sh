#!/usr/bin/env bash
# mcp-search-scope-reminder-nudge.test.sh — logic + retroactive selftest
#
# 正本: ~/Claude/claude-config/hooks/mcp-search-scope-reminder-nudge.test.sh
#
# テストの 2 段構え:
#   §A logic test: 合成 stdin JSON で fire / silent の判定が正しいか
#   §B retroactive selftest: 2026-06-20 layer-3 RCA の起票 transcript
#       (= odakin の個人層 transcript dir、 file 名は cold-eyes session が直接
#        渡された path を参照する形にして public layer 1 には焼かない) から
#       実 tool calls を抽出して当時 hook が wire されていたら fire したか検証
#
# §B は plan §「cold-eyes 任務 3」 (= 起票 transcript で retroactive selftest が
# pass まで詰める) の機械化。 当時の actual call (= search_threads / search_emails
# 系の tool_use) で hook が必ず fire することを確認 → 配信時点で過去 trap が
# 機械的に検出されることを担保。 transcript 中の特定 query 文字列 (= 人名等の
# private content) は public layer 1 で出さない、 環境変数 override + 個人層
# plan への pointer 経由で対応。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/mcp-search-scope-reminder-nudge.sh"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

pass=0
fail=0
results=()

# expect: 0=silent (exit 0 + no stdout), 1=fire (exit 0 + stdout contains 🔌 or ⚠️)
assert_fire() {
  local label="$1" expect="$2" input="$3"
  local out exit_code
  out="$(printf '%s' "$input" | "$HOOK" 2>/dev/null)" || true
  exit_code=$?
  local actual=0
  if printf '%s' "$out" | grep -qE '⚠️ MCP search'; then actual=1; fi
  if [ "$actual" = "$expect" ] && [ "$exit_code" = 0 ]; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect actual=$actual exit=$exit_code)")
  fi
}

echo "=== §A logic tests (= 合成 stdin JSON) ==="

# A1. Cowork search_threads (= 起票 RCA の対象 tool 型) → FIRE
# 注: UUID + query は generic placeholder (= public layer 1 leak 防止、
#     実 transcript の固有名は §B retroactive で env 変数経由のみ参照)
assert_fire "A1: Cowork connector search_threads with query" 1 \
  '{"tool_name":"mcp__example-uuid-0000-0000__search_threads","tool_input":{"query":"example-query"}}'

# A2. gongrzhe gmail-<alias1> search_emails → FIRE
# 注: alias 名は generic placeholder (= alias-a/-b)。 layer 1 leak 防止のため
#     実 alias (= odakin の所属示唆につながる組合せ) は public test に出さない
assert_fire "A2: gmail-<alias-a> search_emails" 1 \
  '{"tool_name":"mcp__gmail-alias-a__search_emails","tool_input":{"query":"foo"}}'

# A3. gmail-<alias2> search_emails → FIRE (= 別 alias で同 matcher が拾うか)
assert_fire "A3: gmail-<alias-b> search_emails" 1 \
  '{"tool_name":"mcp__gmail-alias-b__search_emails","tool_input":{"query":"x"}}'

# A4. Calendar list_events → FIRE (scope risk あり)
assert_fire "A4: calendar list_events" 1 \
  '{"tool_name":"mcp__example-cal-uuid__list_events","tool_input":{"calendarId":"primary"}}'

# A5. Cowork get_thread (targeted ID で取得、 scope risk 無し) → SILENT
assert_fire "A5: Cowork get_thread (targeted) → silent" 0 \
  '{"tool_name":"mcp__example-uuid-1__get_thread","tool_input":{"threadId":"abc"}}'

# A6. gmail read_email (targeted ID) → SILENT
assert_fire "A6: gmail read_email (targeted) → silent" 0 \
  '{"tool_name":"mcp__gmail-alias-a__read_email","tool_input":{"messageId":"abc"}}'

# A7. unrelated Bash → SILENT
assert_fire "A7: Bash tool → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"ls"}}'

# A8. empty stdin → SILENT (fail-open)
assert_fire "A8: empty stdin → silent" 0 ''

# A9. malformed JSON → SILENT (fail-open)
assert_fire "A9: malformed JSON → silent" 0 'not-json-at-all'

# A10. FORCE bypass で arbitrary tool でも FIRE
out="$(printf '%s' '{"tool_name":"Bash"}' | MCP_SCOPE_REMINDER_FORCE=1 "$HOOK" 2>/dev/null)" || true
if printf '%s' "$out" | grep -qE '⚠️ MCP search'; then
  pass=$((pass+1)); results+=("✅ A10: FORCE bypass on Bash")
else
  fail=$((fail+1)); results+=("❌ A10: FORCE bypass failed to fire")
fi

# A11. surface file が書かれるか確認 (= desktop fallback path)
SURFACE_FILE="$HOME/.claude/surface/mcp-search-reminder.txt"
rm -f "$SURFACE_FILE" 2>/dev/null || true
echo '{"tool_name":"mcp__gmail-personal__search_emails","tool_input":{"query":"x"}}' | "$HOOK" >/dev/null 2>&1 || true
if [ -f "$SURFACE_FILE" ] && grep -q 'MCP search' "$SURFACE_FILE"; then
  pass=$((pass+1)); results+=("✅ A11: surface file written")
else
  fail=$((fail+1)); results+=("❌ A11: surface file not written or empty")
fi

# ---------- §B retroactive selftest ----------
echo ""
echo "=== §B retroactive selftest (= 起票 transcript の実 tool calls) ==="

# 起票 transcript path (= 2026-06-20 RCA。 環境変数で override 可)
TRANSCRIPT="${MCP_SCOPE_REMINDER_TRANSCRIPT:-$HOME/.claude/projects/-Users-odakin-Claude-claude-config/55a33041-51ff-469a-a3ee-f8bff1f10d41.jsonl}"

if [ ! -f "$TRANSCRIPT" ]; then
  echo "  ⚠️ transcript not found: $TRANSCRIPT — §B skipped"
  echo "     (foreign user の場合は §A だけで OK、 odakin 当該 machine では §B も走る)"
else
  # 起票 transcript から「fire すべきだった tool calls」 を抽出して投入。
  # plan §「cold-eyes 任務 3」 が要求する「当時 flag されるべき箇所が全部検出される」
  # を測定 — 0 件 hit を出した search call を全件 hook に投入して全て fire するか。
  if ! command -v python3 >/dev/null 2>&1; then
    echo "  ⚠️ python3 not found — §B skipped"
  else
    cases_json="$(python3 - "$TRANSCRIPT" <<'PYEOF'
import json, sys
trans = sys.argv[1]
cases = []
with open(trans) as f:
    for i, line in enumerate(f, 1):
        try: d = json.loads(line)
        except: continue
        msg = d.get('message',{})
        c = msg.get('content')
        if not isinstance(c, list): continue
        for item in c:
            if not isinstance(item, dict): continue
            if item.get('type') != 'tool_use': continue
            name = item.get('name','')
            # 起票 trap の対象は search_threads / search_emails / list_messages 系
            if not any(s in name for s in ['search_threads','search_emails','list_messages','list_threads','list_events']):
                continue
            inp = item.get('input',{})
            payload = {"tool_name": name, "tool_input": inp}
            cases.append({"line": i, "tool": name, "input_json": json.dumps(payload)})
print(json.dumps(cases))
PYEOF
)"

    total="$(printf '%s' "$cases_json" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    fired=0
    missed=0
    sample_miss=""

    # 全件投入して fire 数を count
    while IFS= read -r case_input; do
      [ -n "$case_input" ] || continue
      line_no="$(printf '%s' "$case_input" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d["line"])' 2>/dev/null || echo "?")"
      tool_name="$(printf '%s' "$case_input" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d["tool"])' 2>/dev/null || echo "?")"
      payload="$(printf '%s' "$case_input" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d["input_json"])' 2>/dev/null || echo "{}")"
      out="$(printf '%s' "$payload" | "$HOOK" 2>/dev/null)" || true
      if printf '%s' "$out" | grep -qE '⚠️ MCP search'; then
        fired=$((fired+1))
      else
        missed=$((missed+1))
        if [ -z "$sample_miss" ]; then
          sample_miss="L${line_no} ${tool_name}"
        fi
      fi
    done < <(printf '%s' "$cases_json" | python3 -c '
import json, sys
for c in json.load(sys.stdin):
    print(json.dumps(c))
')

    echo "  起票 transcript 中の search-style tool_use: $total 件"
    echo "  hook fire: $fired / miss: $missed"

    if [ "$total" -gt 0 ] && [ "$missed" = "0" ]; then
      pass=$((pass+1)); results+=("✅ B1: retroactive selftest — 全 $total 件 fire")
    elif [ "$total" = "0" ]; then
      results+=("⚠️ B1: transcript に該当 tool call なし (= 検出 logic 不整合 or 別 transcript)")
      fail=$((fail+1))
    else
      results+=("❌ B1: $missed/$total miss (sample: $sample_miss)")
      fail=$((fail+1))
    fi
  fi
fi

# ---------- 結果 ----------
echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit $fail
