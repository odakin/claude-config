#!/usr/bin/env bash
# value-index-output-nudge.test.sh — value-index-output-nudge.py の検査 (鳴る / 値を出さない / 1 session 1 回 / 黙る / 個人層なし)
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/value-index-output-nudge.py"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
ENGINE_DEFAULT="$(cd "$(dirname "$0")/.." && pwd)/scripts/check-value-index.py"
export VALUE_INDEX_ENGINE="${VALUE_INDEX_ENGINE:-$ENGINE_DEFAULT}"
[ -f "$VALUE_INDEX_ENGINE" ] || VALUE_INDEX_ENGINE="$HOME/Claude/claude-config/scripts/check-value-index.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export VALUE_INDEX_OUTPUT_STATE_DIR="$TMP/state"
LAYER="$TMP/layer"
mkdir -p "$LAYER/private"
touch "$LAYER/.claude-personal-layer"
echo "# mock" > "$LAYER/CLAUDE.md"
printf '## <a id="leak-index"></a>index\n\n- digits: `090-0000-1234` (mock の携帯)\n- date: `1971-02-03` (mock の生年月日)\n' > "$LAYER/private/v.md"
printf 'private/v.md#leak-index\n' > "$LAYER/value-index.txt"
export CLAUDE_PERSONAL_LAYER="$LAYER"
pass=0; fail=0
ok() { pass=$((pass+1)); echo "✅ $1"; }
ng() { fail=$((fail+1)); echo "❌ $1"; }
run() { printf '%s' "$1" | python3 "$HOOK"; }

BASH_HIT='{"session_id":"s1","hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"cat x"},"tool_response":{"stdout":"連絡先 090 0000 1234\n","stderr":""}}'
out="$(run "$BASH_HIT")"
if printf '%s' "$out" | grep -q 'mock の携帯' && ! printf '%s' "$out" | grep -q '1234'; then ok "T1 Bash の出力の値で鳴り、 種類だけを出す (値は出さない)"
else ng "T1: ${out:-silent}"; fi

out="$(run "$BASH_HIT")"
if [ -z "$out" ]; then ok "T2 同じ session の同じ種類は 2 回目に黙る"; else ng "T2 鳴った: $out"; fi

READ_HIT='{"session_id":"s1","hook_event_name":"PostToolUse","tool_name":"Read","tool_response":{"type":"text","file":{"content":"生年月日 1971年2月3日"}}}'
out="$(run "$READ_HIT")"
if printf '%s' "$out" | grep -q 'mock の生年月日' && ! printf '%s' "$out" | grep -q '携帯'; then ok "T3 Read の結果の別の種類では鳴る (知らせ済みの種類は出さない)"
else ng "T3: ${out:-silent}"; fi

out="$(run '{"session_id":"s2","hook_event_name":"PostToolUse","tool_name":"Bash","tool_response":{"stdout":"id 1090000012345 は無関係","stderr":""}}')"
if [ -z "$out" ]; then ok "T4 長い数字の中の同じ数字列では黙る"; else ng "T4 鳴った: $out"; fi

out="$(CLAUDE_PERSONAL_LAYER=none run "${BASH_HIT/\"s1\"/\"s3\"}")"
if [ -z "$out" ]; then ok "T5 個人層が無ければ黙る"; else ng "T5 鳴った: $out"; fi

printf '\0GITCRYPT\0x' > "$LAYER/private/v.md"
out="$(run "${BASH_HIT/\"s1\"/\"s4\"}")"
if [ -z "$out" ]; then ok "T6 索引が暗号化されたまま (鍵の無い機械) なら黙る"; else ng "T6 鳴った: $out"; fi

out="$(printf 'not json' | python3 "$HOOK"; echo "rc=$?")"
if [ "$out" = "rc=0" ]; then ok "T7 壊れた入力は黙って rc 0"; else ng "T7: $out"; fi

echo "value-index-output-nudge test: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
