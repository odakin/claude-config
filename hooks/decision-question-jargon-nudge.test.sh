#!/usr/bin/env bash
# decision-question-jargon-nudge.test.sh — 本人への問いの作業側の語の注意 hook の selftest (合成の問いで、 当たり / 通す / fail-open / 3 つの面 / 文面)
#
# 正本: claude-config/hooks/decision-question-jargon-nudge.test.sh (run-all-checks.sh が自動発見)
# §A 当たり (Stop): 掲示板の動詞 / 問いの item の sub-bullet の符号 / 追記 N / event id / [check] / 個人の一覧の語 (pointer つき)
# §B 通す: 問いでない行の符号 / 説明つきの符号 (= が続く) / 「」 の例示 / 紙の大きさ・chip・元号 / 大文字の Accept / 個人の一覧が無い / 普通の語の問い
# §C fail-open: stop_hook_active / transcript 不在 / DISABLE / engine 不在 / 一覧が両方無い
# §D tool の面: AskUserQuestion の当たりと通す / wrap_up の recap / deny mode / 対象外の tool
# §E 文面: 返事の全文の出し直しを求めない (hook-authoring.md#stop-hook-addendum-not-reemission)
# §F engine の --selftest
# 文は全部合成 (本人の原文・原稿の語・固有名は入れない = 公開 repo)。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/decision-question-jargon-nudge.sh"
TERMS="$HERE/decision-question-jargon-terms.txt"
# engine = hook の隣の scripts/、 無ければ層1 の checkout (候補の写しの dir から回すとき)。 hook にも同じ engine を使わせる
ENGINE="${DECISION_QUESTION_JARGON_ENGINE:-$HERE/../scripts/decision-question-jargon.py}"
[ -f "$ENGINE" ] || ENGINE="${CLAUDE_CONFIG_ROOT:-$HOME/Claude/claude-config}/scripts/decision-question-jargon.py"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
[ -f "$TERMS" ] || { echo "FAIL: terms not found: $TERMS"; exit 1; }
[ -f "$ENGINE" ] || { echo "FAIL: engine not found: $ENGINE"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export TMPDIR="$TMP"
export DECISION_QUESTION_JARGON_TERMS="$TERMS" DECISION_QUESTION_JARGON_EXT="$TMP/ext.txt" DECISION_QUESTION_JARGON_ENGINE="$ENGINE"
unset DECISION_QUESTION_JARGON_DISABLE DECISION_QUESTION_JARGON_TOOL_MODE
printf 'pointer: personal/chat-style.md#x\nre:推す\\s*[=＝]\n呼び名A\n' > "$TMP/ext.txt"

pass=0; fail=0; results=()
ok() { pass=$((pass+1)); results+=("✅ $1"); }
ng() { fail=$((fail+1)); results+=("❌ $1 ($2)"); }

mktranscript() {  # path, final_text
  {
    jq -nc '{type:"user", message:{content:"やって"}}'
    jq -nc '{type:"assistant", message:{content:[{type:"tool_use", name:"Bash", input:{command:"true"}}]}}'
    jq -nc '{type:"user", message:{content:[{type:"tool_result", content:"ok"}]}}'
    jq -nc --arg t "$2" '{type:"assistant", message:{content:[{type:"text", text:$t}]}}'
  } > "$1"
}
run_stop() {  # transcript, [stop_hook_active]
  jq -nc --arg p "$1" --argjson a "${2:-false}" '{hook_event_name:"Stop", transcript_path:$p, stop_hook_active:$a}' | bash "$HOOK"
}
expect_stop() {  # name, fire|silent, final_text, [needle in output]
  local tr="$TMP/$RANDOM$RANDOM.jsonl" out
  mktranscript "$tr" "$3"
  out="$(run_stop "$tr")"
  if [ "$2" = "fire" ]; then
    if printf '%s' "$out" | grep -q '"decision": *"block"' && { [ -z "${4:-}" ] || printf '%s' "$out" | grep -qF -- "$4"; }; then ok "$1"
    else ng "$1" "expect fire${4:+ with $4}, got: ${out:-silent}"; fi
  else
    if [ -z "$out" ]; then ok "$1"; else ng "$1" "expect silent, got: ${out:0:200}"; fi
  fi
}
run_tool() {  # tool_name, tool_input_json
  jq -nc --arg n "$1" --argjson i "$2" '{hook_event_name:"PreToolUse", tool_name:$n, tool_input:$i}' | bash "$HOOK"
}

# §A 当たり (Stop)
expect_stop "A1 掲示板の動詞" fire "確かめました。この依頼を accept してよいですか？" "accept"
expect_stop "A2 問いの item の sub-bullet の符号" fire $'2. **案を当てるか**: 推す答えは次です。\n   - 例外 2 つ (W-3・X-7)。\n   - 範囲外の直しも含める。' "W-3"
expect_stop "A3 追記 N" fire "報告書の追記 4–8 を事後確認でよいですか。" "追記 4"
expect_stop "A4 event id" fire "20261015T054335Z-abcdef の依頼を閉じてよいですか。" "20261015T054335Z-abcdef"
expect_stop "A5 [check]" fire "赤字 [check] 7 か所を外してよいか。" "[check]"
expect_stop "A6 個人の一覧の語 + pointer" fire "1. 文献を引くか。 推す = 引く。" "personal/chat-style.md#x"
expect_stop "A7 台帳の符号 (小文字の説明なし)" fire "C3 の記号はどちらにしますか。" "C3"

# §B 通す
expect_stop "B1 問いでない行の符号" silent $'commit W-3 を push しました。\n\n次は何をしますか。'
expect_stop "B2 説明つきの符号 (= が続く)" silent "1. Q14 = 赤字 4 か所を外してよいか → はい"
expect_stop "B3 「」 の中の例示" silent "返事に「accept」 のような語を使わない方がよいですか。"
expect_stop "B4 紙の大きさ・chip・元号" silent "A4 で刷ってよいですか。 M5 の設定も切りますか。 R9 の調書を出しますか。"
expect_stop "B5 大文字の Accept (UI のボタン名)" silent "招待の Accept を押してよいですか。"
expect_stop "B6 普通の語の問い" silent "文献を引くか、 引かないか。 どちらにしますか。"
tr="$TMP/noext.jsonl"; mktranscript "$tr" "1. 文献を引くか。 推す = 引く。"
out="$(jq -nc --arg p "$tr" '{hook_event_name:"Stop", transcript_path:$p}' | DECISION_QUESTION_JARGON_EXT="$TMP/no-such-ext.txt" bash "$HOOK")"
[ -z "$out" ] && ok "B7 個人の一覧が無ければその語では鳴らない" || ng "B7" "got: ${out:0:200}"

# §C fail-open
tr="$TMP/guard.jsonl"; mktranscript "$tr" "この依頼を accept してよいですか？"
out="$(run_stop "$tr" true)"; [ -z "$out" ] && ok "C1 stop_hook_active は沈黙" || ng "C1" "fired"
out="$(jq -nc '{hook_event_name:"Stop", transcript_path:"/nonexistent/x.jsonl"}' | bash "$HOOK")"; [ -z "$out" ] && ok "C2 transcript 不在は沈黙" || ng "C2" "fired"
out="$(jq -nc --arg p "$tr" '{hook_event_name:"Stop", transcript_path:$p}' | DECISION_QUESTION_JARGON_DISABLE=1 bash "$HOOK")"; [ -z "$out" ] && ok "C3 DISABLE=1 は沈黙" || ng "C3" "fired"
out="$(jq -nc --arg p "$tr" '{hook_event_name:"Stop", transcript_path:$p}' | DECISION_QUESTION_JARGON_ENGINE="$TMP/no-engine.py" bash "$HOOK")"; [ -z "$out" ] && ok "C4 engine 不在は沈黙" || ng "C4" "fired"
cp "$ENGINE" "$TMP/engine-nolib.py"
out="$(jq -nc --arg p "$tr" '{hook_event_name:"Stop", transcript_path:$p}' | CLAUDE_CONFIG_ROOT="$TMP/no-such-root" DECISION_QUESTION_JARGON_ENGINE="$TMP/engine-nolib.py" bash "$HOOK")"
[ -z "$out" ] && ok "C7 層1 部品 (transcript_turns) が読めなければ沈黙" || ng "C7" "fired: ${out:0:120}"
out="$(jq -nc --arg p "$tr" '{hook_event_name:"Stop", transcript_path:$p}' | DECISION_QUESTION_JARGON_TERMS="$TMP/no-terms.txt" DECISION_QUESTION_JARGON_EXT="$TMP/no-ext.txt" bash "$HOOK")"
[ -z "$out" ] && ok "C5 一覧が両方無ければ沈黙" || ng "C5" "fired"
out="$(printf 'not json' | bash "$HOOK")"; [ -z "$out" ] && ok "C6 入力が JSON でなければ沈黙" || ng "C6" "fired"

# §D tool の面
out="$(run_tool AskUserQuestion '{"questions":[{"question":"reviewer をこの session に移して accept してよいですか？","header":"x","options":[{"label":"移す","description":"human handover で移す"},{"label":"置く","description":"そのまま"}]}]}')"
if printf '%s' "$out" | grep -qF '"hookEventName": "PreToolUse"' && printf '%s' "$out" | grep -qF 'additionalContext' && printf '%s' "$out" | grep -qF 'handover'; then ok "D1 選択肢 UI の作業側の語に注意 (additionalContext)"; else ng "D1" "got: ${out:0:200}"; fi
out="$(run_tool AskUserQuestion '{"questions":[{"question":"文献を引きますか？","header":"x","options":[{"label":"引く","description":"序論に 1 文"},{"label":"引かない","description":"そのまま"}]}]}')"
[ -z "$out" ] && ok "D2 普通の語の選択肢 UI は沈黙" || ng "D2" "got: ${out:0:200}"
out="$(run_tool mcp__ccd_turn__wrap_up '{"recap":"残りは報告書 Q19 の追記 4–8 の確認です。","ask":"一覧にしますか？","actions":[{"label":"一覧に","message":"一覧にして"}]}')"
if printf '%s' "$out" | grep -qF 'additionalContext' && printf '%s' "$out" | grep -qF 'Q19'; then ok "D3 turn 終わりの箱の recap の符号に注意"; else ng "D3" "got: ${out:0:200}"; fi
out="$(jq -nc '{hook_event_name:"PreToolUse", tool_name:"AskUserQuestion", tool_input:{questions:[{question:"この依頼を accept してよいですか？",header:"x",options:[{label:"はい",description:"する"}]}]}}' | DECISION_QUESTION_JARGON_TOOL_MODE=deny bash "$HOOK")"
if printf '%s' "$out" | grep -qF '"permissionDecision": "deny"' && printf '%s' "$out" | grep -qF 'accept'; then ok "D4 deny mode は止めて理由を返す"; else ng "D4" "got: ${out:0:200}"; fi
out="$(run_tool Bash '{"command":"accept W-3"}')"; [ -z "$out" ] && ok "D5 対象外の tool は沈黙" || ng "D5" "got: ${out:0:200}"
out="$(run_tool AskUserQuestion '{"questions":[{"question":"Q14 = 赤字 4 か所を外しますか？","header":"x","options":[{"label":"外す","description":"4 か所とも"}]}]}')"
[ -z "$out" ] && ok "D6 選択肢 UI でも説明つきの符号は通す" || ng "D6" "got: ${out:0:200}"

# §E 文面
tr="$TMP/e1.jsonl"; mktranscript "$tr" "この依頼を accept してよいですか？"
out="$(run_stop "$tr")"
if printf '%s' "$out" | grep -qF '短い追記' && ! printf '%s' "$out" | grep -qF '同じ内容で終了' && printf '%s' "$out" | grep -qF 'concise-output.md#decision-questions'; then ok "E1 差し戻しは問いの部分の短い追記を求め、 正本を名指す"; else ng "E1" "got: ${out:0:300}"; fi

# §F engine の selftest
if python3 "$ENGINE" --selftest >/dev/null 2>&1; then ok "F1 engine --selftest"; else ng "F1 engine --selftest" "$(python3 "$ENGINE" --selftest 2>&1 | grep '❌' | head -3)"; fi

for r in "${results[@]}"; do echo "  $r"; done
echo "--- decision-question-jargon-nudge.test: PASS=$pass FAIL=$fail ---"
[ "$fail" -eq 0 ]
