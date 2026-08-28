#!/usr/bin/env bash
# bash-search-zero-result-nudge.test.sh — logic + incident-reproduction selftest
#
# 正本: <claude-config>/hooks/bash-search-zero-result-nudge.test.sh
#
# §A logic: detector A (tree-search null / glob 不成立) と detector B
#   (truncate-before-grep) の fire / silent 境界 + rate-limit + FORCE + surface file
# §B incident reproduction: 2026-08-24 の 2 実 incident の command 形を
#   決定的 fixture として再現し、 hook が fire することを固定する
#   (= sibling の transcript-依存 §B と違い inline fixture = 全環境で決定的。
#    fixture path は架空 〔/tmp/demo-*〕 = public repo に private repo 名を焼かない)

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/bash-search-zero-result-nudge.sh"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

MARKER='🛑 ローカル検索 null'
pass=0
fail=0
results=()

# rate-limit を無効化した isolated 環境で 1 fixture を流す
assert_fire() {
  local label="$1" expect="$2" input="$3"
  local out actual=0
  local sdir
  sdir="$(mktemp -d)"
  out="$(printf '%s' "$input" | BASH_SEARCH_NUDGE_STATE_DIR="$sdir" BASH_SEARCH_NUDGE_WINDOW=0 "$HOOK" 2>/dev/null)" || true
  rm -rf "$sdir" 2>/dev/null || true
  if printf '%s' "$out" | grep -qF "$MARKER"; then actual=1; fi
  if [ "$actual" = "$expect" ]; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect actual=$actual)")
  fi
}

echo "=== §A logic tests ==="

# === detector A: FIRE ===
assert_fire "A1: grep -rn <dir> 空出力 → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"grep -rn needle /tmp/demo-repo-a/"},"tool_response":{"stdout":"","stderr":""}}'

assert_fire "A2: find <dir> -name 空出力 → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"find /tmp/demo-repo-a /tmp/demo-repo-b -name \"*spec*\" 2>/dev/null"},"tool_response":{"stdout":"","stderr":""}}'

assert_fire "A3: zsh glob 不成立 (no matches found) → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"ls -1 /tmp/demo-hooks/mcp-search-*.sh"},"tool_response":{"stdout":"","stderr":"(eval):1: no matches found: /tmp/demo-hooks/mcp-search-*.sh"}}'

assert_fire "A4: git grep 空出力 → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"git grep needle -- docs/"},"tool_response":{"stdout":"","stderr":""}}'

assert_fire "A5: string 型 tool_response (空) + grep -R → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"grep -Rn pat /tmp/demo-dir"},"tool_response":""}'

# === detector A: SILENT (= FP 防止の境界) ===
assert_fire "A6: grep -rn <dir> hit あり → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"grep -rn needle /tmp/demo-repo-a/"},"tool_response":{"stdout":"/tmp/demo-repo-a/x.md:3:needle here","stderr":""}}'

assert_fire "A7: 単一 file grep 空出力 (leak check 型、 -r なし) → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"grep -inE \"password|token\" /tmp/draft.md"},"tool_response":{"stdout":"","stderr":""}}'

assert_fire "A8: pipe 入力 grep 空出力 (git diff | grep) → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"git diff --unified=0 | grep \"^+\" | grep -inE \"secret\""},"tool_response":{"stdout":"","stderr":""}}'

assert_fire "A9: find hit あり → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"find /tmp/demo -name \"*.md\""},"tool_response":{"stdout":"/tmp/demo/a.md","stderr":""}}'

assert_fire "A10: 非検索 command の空出力 (mkdir) → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"mkdir -p /tmp/demo-out"},"tool_response":{"stdout":"","stderr":""}}'

assert_fire "A11: 非 Bash tool → silent" 0 \
  '{"tool_name":"Read","tool_input":{"file_path":"/tmp/x.md"},"tool_response":"no matches found"}'

# === detector B: FIRE (= 構造 signal、 hit 有無に関わらず) ===
assert_fire "B1: sed -n 窓 → grep (hit あり) → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"mycli --help 2>&1 | sed -n \"40,200p\" | grep -iE \"import|share|export\""},"tool_response":{"stdout":"  --file <specs...>  File resources","stderr":""}}'

assert_fire "B2: head → grep → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"mycli --help | head -60 | grep -i import"},"tool_response":{"stdout":"","stderr":""}}'

assert_fire "B3: tail -100 → grep → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"tail -100 /tmp/app.log | grep ERROR"},"tool_response":{"stdout":"","stderr":""}}'

# === detector B: SILENT (= 正常 idiom / 除外) ===
assert_fire "B4: grep → head (正常 idiom) → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"grep -n pattern /tmp/big.txt | head -5"},"tool_response":{"stdout":"3:pattern","stderr":""}}'

assert_fire "B5: tail -f → grep (stream 監視 idiom) → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"tail -f /tmp/app.log | grep --line-buffered ERROR"},"tool_response":{"stdout":"","stderr":""}}'

assert_fire "B6: sed 置換 (s///、 -n なし) → grep → silent" 0 \
  '{"tool_name":"Bash","tool_input":{"command":"sed \"s/foo/bar/\" /tmp/x.txt | grep bar"},"tool_response":{"stdout":"bar","stderr":""}}'

# === rate limit ===
sdir="$(mktemp -d)"
in_a='{"tool_name":"Bash","tool_input":{"command":"grep -rn needle /tmp/demo-repo-a/"},"tool_response":{"stdout":"","stderr":""}}'
out1="$(printf '%s' "$in_a" | BASH_SEARCH_NUDGE_STATE_DIR="$sdir" BASH_SEARCH_NUDGE_WINDOW=9999 "$HOOK" 2>/dev/null)" || true
out2="$(printf '%s' "$in_a" | BASH_SEARCH_NUDGE_STATE_DIR="$sdir" BASH_SEARCH_NUDGE_WINDOW=9999 "$HOOK" 2>/dev/null)" || true
rm -rf "$sdir" 2>/dev/null || true
if printf '%s' "$out1" | grep -qF "$MARKER" && ! printf '%s' "$out2" | grep -qF "$MARKER"; then
  pass=$((pass+1)); results+=("✅ R1: rate limit — 1 回目 fire / 窓内 2 回目 silent")
else
  fail=$((fail+1)); results+=("❌ R1: rate limit (out1=$(printf '%s' "$out1" | grep -cF "$MARKER") out2=$(printf '%s' "$out2" | grep -cF "$MARKER"))")
fi

# === FORCE bypass ===
out="$(printf '%s' '{"tool_name":"Read","tool_response":"hits everywhere"}' | BASH_SEARCH_NUDGE_FORCE=1 "$HOOK" 2>/dev/null)" || true
if printf '%s' "$out" | grep -qF "$MARKER"; then
  pass=$((pass+1)); results+=("✅ F1: FORCE bypass fires on any tool")
else
  fail=$((fail+1)); results+=("❌ F1: FORCE bypass failed")
fi

# === surface file ===
SURFACE_FILE="$HOME/.claude/surface/bash-search-zero.txt"
rm -f "$SURFACE_FILE" 2>/dev/null || true
sdir="$(mktemp -d)"
printf '%s' "$in_a" | BASH_SEARCH_NUDGE_STATE_DIR="$sdir" BASH_SEARCH_NUDGE_WINDOW=0 "$HOOK" >/dev/null 2>&1 || true
rm -rf "$sdir" 2>/dev/null || true
if [ -f "$SURFACE_FILE" ] && grep -q 'ローカル検索 null' "$SURFACE_FILE"; then
  pass=$((pass+1)); results+=("✅ S1: surface file written")
else
  fail=$((fail+1)); results+=("❌ S1: surface file not written")
fi

# ---------- §B incident reproduction (= 2026-08-24 の 2 実 incident、 決定的 inline) ----------
echo ""
echo "=== §B incident reproduction ==="

# incident ①: 複数 repo を find で -name 検索 → null → 「doc は存在しない (stale)」 と
# 誤断定した形 (実体は検索対象外の sibling repo に実在した)。 path は架空に一般化。
assert_fire "I1: incident① 型 = 2-repo find -name null → fire" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"find /tmp/repo-x /tmp/repo-y -name \"*schedule-spec*\" -not -path \"*/.git/*\" 2>/dev/null"},"tool_response":{"stdout":"","stderr":""}}'

# incident ②: --help 全 227 行のうち sed -n の窓 (40-200 行) の上で grep して
# 「該当 flag 無し」 と断定した形 (hit はあったが窓外 201-227 行が未検査)。
assert_fire "I2: incident② 型 = --help | sed -n 窓 | grep → fire (hit あり)" 1 \
  '{"tool_name":"Bash","tool_input":{"command":"\"$CL\" --help 2>&1 | sed -n \"40,200p\" | grep -iE \"import|share|export|url|conversation\""},"tool_response":{"stdout":"  --chrome    Enable Claude in Chrome integration","stderr":""}}'

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit $fail
