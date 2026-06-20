#!/usr/bin/env bash
# mcp-search-zero-result-nudge.test.sh — logic + retroactive selftest
#
# 正本: ~/Claude/claude-config/hooks/mcp-search-zero-result-nudge.test.sh
#
# §A logic: clear zero pattern と hit pattern を分けて、 fire / silent を検証
# §B retroactive: 起票 transcript の実 tool_result から 0 件 case を抽出して
#                  Hook が必ず fire することを確認

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/mcp-search-zero-result-nudge.sh"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

pass=0
fail=0
results=()

assert_fire() {
  local label="$1" expect="$2" input="$3"
  local out exit_code
  out="$(printf '%s' "$input" | "$HOOK" 2>/dev/null)" || true
  exit_code=$?
  local actual=0
  if printf '%s' "$out" | grep -qE '🛑 MCP search 0 件'; then actual=1; fi
  if [ "$actual" = "$expect" ] && [ "$exit_code" = 0 ]; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect actual=$actual exit=$exit_code)")
  fi
}

echo "=== §A logic tests ==="

# === FIRE cases (= clear zero markers) ===
assert_fire "A1: Cowork 'No threads found'" 1 \
  '{"tool_name":"mcp__dcfb814b-X__search_threads","tool_response":"No threads found"}'

assert_fire "A2: gongrzhe 'Found 0 messages'" 1 \
  '{"tool_name":"mcp__gmail-personal__search_emails","tool_response":"Found 0 messages matching the query"}'

assert_fire "A3: empty messages array" 1 \
  '{"tool_name":"mcp__gmail-lab__search_emails","tool_response":"{\"messages\": []}"}'

assert_fire "A4: empty threads array" 1 \
  '{"tool_name":"mcp__gmail-cis__search_emails","tool_response":"{\"threads\":[]}"}'

assert_fire "A5: resultSizeEstimate 0" 1 \
  '{"tool_name":"mcp__gmail-personal__search_emails","tool_response":"{\"resultSizeEstimate\":0}"}'

assert_fire "A6: literal empty array" 1 \
  '{"tool_name":"mcp__gmail-lab__list_messages","tool_response":"[]"}'

assert_fire "A7: literal null" 1 \
  '{"tool_name":"mcp__gmail-personal__search_emails","tool_response":"null"}'

assert_fire "A8: 該当なし (Japanese)" 1 \
  '{"tool_name":"mcp__gmail-lab__search_emails","tool_response":"検索結果: 該当なし"}'

# === SILENT cases (= hit results、 false positive 防止) ===
assert_fire "A9: 1-message hit (short metadata)" 0 \
  '{"tool_name":"mcp__gmail-personal__search_emails","tool_response":"[{\"id\":\"abc\",\"threadId\":\"def\"}]"}'

assert_fire "A10: 10-message hit" 0 \
  '{"tool_name":"mcp__gmail-personal__search_emails","tool_response":"Found 10 messages: [{\"id\":\"a\"},{\"id\":\"b\"}]"}'

assert_fire "A11: thread with content" 0 \
  '{"tool_name":"mcp__example-uuid-0__search_threads","tool_response":"[{\"threadId\":\"abc\",\"subject\":\"hello\",\"snippet\":\"sample content\"}]"}'

assert_fire "A12: unrelated tool (Bash) → silent" 0 \
  '{"tool_name":"Bash","tool_response":"No matches"}'

assert_fire "A13: get_thread (targeted, not search) → silent" 0 \
  '{"tool_name":"mcp__dcfb814b-X__get_thread","tool_response":"{}"}'

# === FORCE bypass ===
out="$(printf '%s' '{"tool_name":"Bash","tool_response":"foo"}' | MCP_ZERO_NUDGE_FORCE=1 "$HOOK" 2>/dev/null)" || true
if printf '%s' "$out" | grep -qE '🛑 MCP search 0 件'; then
  pass=$((pass+1)); results+=("✅ A14: FORCE bypass fires on any tool")
else
  fail=$((fail+1)); results+=("❌ A14: FORCE bypass failed")
fi

# === surface file ===
SURFACE_FILE="$HOME/.claude/surface/mcp-zero-result.txt"
rm -f "$SURFACE_FILE" 2>/dev/null || true
echo '{"tool_name":"mcp__gmail-personal__search_emails","tool_response":"Found 0 messages"}' | "$HOOK" >/dev/null 2>&1 || true
if [ -f "$SURFACE_FILE" ] && grep -q 'MCP search 0' "$SURFACE_FILE"; then
  pass=$((pass+1)); results+=("✅ A15: surface file written")
else
  fail=$((fail+1)); results+=("❌ A15: surface file not written")
fi

# ---------- §B retroactive selftest ----------
echo ""
echo "=== §B retroactive selftest (= 起票 transcript の tool_result から 0 件 case 抽出) ==="

TRANSCRIPT="${MCP_ZERO_NUDGE_TRANSCRIPT:-$HOME/.claude/projects/-Users-odakin-Claude-claude-config/55a33041-51ff-469a-a3ee-f8bff1f10d41.jsonl}"

if [ ! -f "$TRANSCRIPT" ]; then
  echo "  ⚠️ transcript not found — §B skipped"
elif ! command -v python3 >/dev/null 2>&1; then
  echo "  ⚠️ python3 not found — §B skipped"
else
  # tool_use_id を介して assistant の tool_use と user の tool_result を pair 化
  cases_json="$(python3 - "$TRANSCRIPT" <<'PYEOF'
import json, sys
trans = sys.argv[1]

# (a) tool_use を collect (tool_use_id → name)
# (b) user の tool_result を collect (tool_use_id → response text)
tool_uses = {}
tool_results = {}
search_keywords = ['search_threads','search_emails','list_messages','list_threads','list_events']

with open(trans) as f:
    for line_i, line in enumerate(f, 1):
        try: d = json.loads(line)
        except: continue
        msg = d.get('message',{})
        c = msg.get('content')
        if not isinstance(c, list): continue
        for item in c:
            if not isinstance(item, dict): continue
            if item.get('type') == 'tool_use':
                tid = item.get('id')
                name = item.get('name','')
                if tid and any(s in name for s in search_keywords):
                    tool_uses[tid] = {'name': name, 'line': line_i}
            elif item.get('type') == 'tool_result':
                tid = item.get('tool_use_id')
                if not tid: continue
                # tool result content can be str or list of {type:text, text:...}
                rc = item.get('content','')
                if isinstance(rc, list):
                    text = '\n'.join(it.get('text','') for it in rc if isinstance(it, dict))
                else:
                    text = str(rc)
                tool_results[tid] = {'text': text, 'line': line_i}

# Pair up + identify 0-result cases
cases = []
for tid, use in tool_uses.items():
    if tid not in tool_results: continue
    res = tool_results[tid]
    txt = res['text']
    # Detect zero patterns (= same as hook regex, ground truth)
    is_zero = False
    txt_trim = txt.strip()
    if not txt_trim or txt_trim in ('null','""','[]','{}'):
        is_zero = True
    else:
        import re
        zero_patterns = [
            r'no (messages|threads|results|events|emails) found',
            r'^0 (results|matches|messages|threads)',
            r'found 0 (results|matches|messages|threads|emails|events)',
            r'"(messages|threads|events|results)"\s*:\s*\[\s*\]',
            r'該当なし',
            r'^0 件', r'^0件',
            r'empty result',
            r'no matching',
            r'"resultSizeEstimate"\s*:\s*0\b',
        ]
        for p in zero_patterns:
            if re.search(p, txt, re.IGNORECASE | re.MULTILINE):
                is_zero = True; break
    if is_zero:
        cases.append({
            'use_line': use['line'],
            'res_line': res['line'],
            'tool': use['name'],
            'response': txt[:500],  # cap for safety
        })
print(json.dumps(cases))
PYEOF
)"

  total="$(printf '%s' "$cases_json" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  fired=0
  missed=0
  sample_miss=""

  while IFS= read -r case_input; do
    [ -n "$case_input" ] || continue
    line_no="$(printf '%s' "$case_input" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d["use_line"])' 2>/dev/null || echo "?")"
    tool_name="$(printf '%s' "$case_input" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d["tool"])' 2>/dev/null || echo "?")"
    payload="$(printf '%s' "$case_input" | python3 -c '
import json, sys
d = json.loads(sys.stdin.read())
print(json.dumps({"tool_name": d["tool"], "tool_response": d["response"]}))
' 2>/dev/null || echo "{}")"

    out="$(printf '%s' "$payload" | "$HOOK" 2>/dev/null)" || true
    if printf '%s' "$out" | grep -qE '🛑 MCP search 0 件'; then
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

  echo "  起票 transcript 中の 0-result tool call (ground truth detector で抽出): $total 件"
  echo "  hook fire: $fired / miss: $missed"

  if [ "$total" -gt 0 ] && [ "$missed" = "0" ]; then
    pass=$((pass+1)); results+=("✅ B1: retroactive selftest — 全 $total 件 fire")
  elif [ "$total" = "0" ]; then
    # 0 件のときは「ground truth detector が起票 transcript から 0-result case を
    # 1 件も拾えなかった」 = 検出条件が起票時の実 response format に追従できていない可能性
    results+=("⚠️ B1: 0-result case 抽出ゼロ (= 起票 transcript format mismatch、 要確認)")
    fail=$((fail+1))
  else
    results+=("❌ B1: $missed/$total miss (sample: $sample_miss)")
    fail=$((fail+1))
  fi
fi

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit $fail
