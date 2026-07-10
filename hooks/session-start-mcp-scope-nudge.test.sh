#!/usr/bin/env bash
# session-start-mcp-scope-nudge.test.sh
#
# §A logic: SessionStart event filter / fail-open / surface file
# §B accuracy: 当 machine の register 済 Gmail account 列挙が ~/.gmail-mcp/ と一致

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/session-start-mcp-scope-nudge.sh"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

# foreign-user / CI 環境 (= ~/.gmail-mcp も desktop config も不在 = register 0 件) では
# hook は設計上 silent exit するため owner 前提の fire assertion が成立しない -> SKIP を宣言
# (run-all-checks.sh の契約: 前提が無い test は SKIP を出力して exit 0、 silent skip 禁止)
DESKTOP_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
if [ ! -d "$HOME/.gmail-mcp" ] && [ ! -f "$DESKTOP_CFG" ]; then
  echo "SKIP: register 済 MCP が 0 件の環境 (foreign user / CI) — owner 前提の fire assertion は対象外"
  exit 0
fi

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

# ---------- §D write/send capability block (= 2026-06-20 write-tool RCA、 axis B) ----------
# tool 名に send verb が無い = capability 不在の guarantee ではない、 を session 冒頭で anchor。
echo ""
echo "=== §D write/send capability anchor ==="

out="$(printf '%s' '{"hook_event_name":"SessionStart","source":"startup"}' | "$HOOK" 2>&1)"

# D1. capability block の鍵概念が全部出る
missing_d=""
for key in "write/send capability" "send_email" "アプリ内蔵 connector" "account-direct.py"; do
  if ! printf '%s' "$out" | grep -qF "$key"; then
    missing_d="$missing_d [$key]"
  fi
done
if [ -z "$missing_d" ]; then
  pass=$((pass+1)); results+=("✅ D1: capability block の鍵概念が全て output に含まれる")
else
  fail=$((fail+1)); results+=("❌ D1: capability 鍵概念欠落:$missing_d")
fi

# D2. 「read-only」 と書かず「send 不可」 と正確に framing している (= 起票 plan の誤 framing 修正)
if printf '%s' "$out" | grep -qF 'send 不可' && printf '%s' "$out" | grep -qF 'draft 作成'; then
  pass=$((pass+1)); results+=("✅ D2: 「send 不可」 + draft 可 と正確に framing (read-only と誤記しない)")
else
  fail=$((fail+1)); results+=("❌ D2: capability の正確 framing 欠落")
fi

# D3. KNOWN_GMAIL がある machine では send route に alias 列が出る / 無い machine でも fail-open
if [ -d "$HOME/.gmail-mcp" ] && ls "$HOME/.gmail-mcp"/*/credentials.json >/dev/null 2>&1; then
  if printf '%s' "$out" | grep -qF 'register 済 alias:'; then
    pass=$((pass+1)); results+=("✅ D3: standalone alias 登録 machine で send route に alias 列挙")
  else
    fail=$((fail+1)); results+=("❌ D3: alias 登録あるのに send route に列挙なし")
  fi
else
  # foreign / standalone 未 register でも capability block は出る (DESKTOP_CONNECTORS 経由) か silent
  results+=("⚠️ D3: standalone alias 未 register — send route 列挙 skip")
fi

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit $fail
