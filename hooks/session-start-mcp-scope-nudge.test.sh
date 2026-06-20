#!/usr/bin/env bash
# session-start-mcp-scope-nudge.test.sh
#
# §A logic: SessionStart event filter / fail-open / surface file
# §B accuracy: 当 machine の register 済 Gmail account 列挙が ~/.gmail-mcp/ と一致

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/session-start-mcp-scope-nudge.sh"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

pass=0; fail=0; results=()

echo "=== §A logic tests ==="

# A1. SessionStart event → FIRE
out="$(printf '%s' '{"hook_event_name":"SessionStart","source":"startup"}' | "$HOOK" 2>&1)" || true
if printf '%s' "$out" | grep -q '🔌 MCP scope reminder'; then
  pass=$((pass+1)); results+=("✅ A1: SessionStart → fires")
else
  fail=$((fail+1)); results+=("❌ A1: SessionStart → did not fire")
fi

# A2. non-SessionStart event → SILENT
out="$(printf '%s' '{"hook_event_name":"PreToolUse"}' | "$HOOK" 2>&1)" || true
if [ -z "$out" ]; then
  pass=$((pass+1)); results+=("✅ A2: non-SessionStart → silent")
else
  fail=$((fail+1)); results+=("❌ A2: non-SessionStart → not silent: $out")
fi

# A3. FORCE bypass: arbitrary stdin でも FIRE
out="$(printf '%s' 'not-json' | CLAUDE_MCP_SCOPE_FORCE=1 "$HOOK" 2>&1)" || true
if printf '%s' "$out" | grep -q '🔌 MCP scope reminder'; then
  pass=$((pass+1)); results+=("✅ A3: FORCE bypass → fires")
else
  fail=$((fail+1)); results+=("❌ A3: FORCE bypass → did not fire")
fi

# A4. surface file が書かれる
SURFACE_FILE="$HOME/.claude/surface/mcp-scope.txt"
rm -f "$SURFACE_FILE" 2>/dev/null || true
printf '%s' '{"hook_event_name":"SessionStart","source":"startup"}' | "$HOOK" >/dev/null 2>&1 || true
if [ -f "$SURFACE_FILE" ] && grep -q 'MCP scope reminder' "$SURFACE_FILE"; then
  pass=$((pass+1)); results+=("✅ A4: surface file written")
else
  fail=$((fail+1)); results+=("❌ A4: surface file not written")
fi

# A5. system-reminder tag を出す (= Claude が context として認識する形式)
out="$(printf '%s' '{"hook_event_name":"SessionStart","source":"startup"}' | "$HOOK")"
if printf '%s' "$out" | grep -q '<system-reminder>' && printf '%s' "$out" | grep -q '</system-reminder>'; then
  pass=$((pass+1)); results+=("✅ A5: system-reminder tags present")
else
  fail=$((fail+1)); results+=("❌ A5: system-reminder tags missing")
fi

# A6. fail-open: 全 exit 0
exit_code=0
printf '' | "$HOOK" >/dev/null 2>&1 || exit_code=$?
if [ "$exit_code" = 0 ]; then
  pass=$((pass+1)); results+=("✅ A6: empty stdin → exit 0 (fail-open)")
else
  fail=$((fail+1)); results+=("❌ A6: empty stdin → exit $exit_code")
fi

# A7. desktop frontend detection
out="$(CLAUDE_CODE_ENTRYPOINT=claude-desktop printf '%s' '{"hook_event_name":"SessionStart","source":"startup"}' | "$HOOK" 2>&1)"
out2="$(CLAUDE_CODE_ENTRYPOINT=claude-desktop bash -c 'printf "%s" "{\"hook_event_name\":\"SessionStart\",\"source\":\"startup\"}" | "$1"' _ "$HOOK" 2>&1)"
if printf '%s' "$out2" | grep -q 'claude-desktop 検出'; then
  pass=$((pass+1)); results+=("✅ A7: desktop frontend detected")
else
  fail=$((fail+1)); results+=("❌ A7: desktop frontend detection failed")
fi

# ---------- §B accuracy: 列挙が filesystem と一致するか ----------
echo ""
echo "=== §B accuracy: 列挙 vs ~/.gmail-mcp/ ==="

if [ -d "$HOME/.gmail-mcp" ]; then
  # filesystem 由来の ground truth (= credentials.json を持つ dir)
  expected=""
  for d in "$HOME/.gmail-mcp"/*/; do
    [ -d "$d" ] || continue
    base="$(basename "$d")"
    case "$base" in accounts|server|node_modules) continue ;; esac
    [ -f "$d/credentials.json" ] || continue
    expected="${expected:+$expected }$base"
  done

  out="$(printf '%s' '{"hook_event_name":"SessionStart","source":"startup"}' | "$HOOK" 2>&1)"
  reported_line="$(printf '%s' "$out" | grep -oE 'Gmail account \(= ~/.gmail-mcp/\): [a-z]+(\s+[a-z]+)*' | head -1)"
  reported="$(printf '%s' "$reported_line" | sed -E 's/.*: //')"

  # sort + compare
  ex_sorted="$(printf '%s\n' $expected | sort | tr '\n' ' ' | sed 's/ $//')"
  re_sorted="$(printf '%s\n' $reported | sort | tr '\n' ' ' | sed 's/ $//')"
  if [ "$ex_sorted" = "$re_sorted" ] && [ -n "$ex_sorted" ]; then
    pass=$((pass+1)); results+=("✅ B1: 列挙一致 (expected/reported: $ex_sorted)")
  else
    fail=$((fail+1)); results+=("❌ B1: 列挙不一致 (expected=$ex_sorted reported=$re_sorted)")
  fi
else
  results+=("⚠️ B1: ~/.gmail-mcp/ 不在 — §B skipped (foreign user 等)")
fi

# ---------- §C retroactive 検証 ----------
# 起票 session の真因 = lab Gmail のみ wired で他 account が見えなかった。
# 当 hook が起動時に発火していたら「register 済 4 account」 が表示されて
# scope ギャップが session 冒頭に明示されていた = それを再現確認。
echo ""
echo "=== §C retroactive scope-gap reproduction ==="

out="$(printf '%s' '{"hook_event_name":"SessionStart","source":"startup"}' | "$HOOK" 2>&1)"
expected_keys=("Gmail account" "session-active subset may be smaller" "universal claim" "Verified" "NOT verified")
# Plan §「cold-eyes 任務 3 retroactive selftest」 は起票時に hook が wire されていたら
# scope-gap が冒頭で見えたか の reproduction。 reminder 文の鍵概念が含まれることを確認。
missing=""
for key in "Gmail account" "session-active" "universal claim" "Verified scope" "NOT verified"; do
  if ! printf '%s' "$out" | grep -q "$key"; then
    missing="$missing [$key]"
  fi
done
if [ -z "$missing" ]; then
  pass=$((pass+1)); results+=("✅ C1: scope-gap 起票時に見えていたであろう鍵概念が全て output に含まれる")
else
  fail=$((fail+1)); results+=("❌ C1: 鍵概念欠落:$missing")
fi

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit $fail
