#!/usr/bin/env bash
# owner-asks.test.sh — owner-asks.sh (本人への問いと答えの台帳の hook の入口) の試験
# 一時の掲示板 (.local を持つ dir)・設定・状態の dir を作り、 event ごとに hook を呼んで出力を確かめる。
# engine は隣の checkout の ai-collaboration/board/board_asks.py (無ければ skip = exit 0)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/owner-asks.sh"
ENGINE="${BOARD_ASKS_ENGINE:-$(cd "$HERE/../.." && pwd)/ai-collaboration/board/board_asks.py}"
[ -f "$ENGINE" ] || { echo "skip: engine が無い ($ENGINE)"; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "skip: jq が無い"; exit 0; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/board/.local" "$T/state"
printf '{"root": "%s", "prefix": {"%s": "Z"}}\n' "$T/board" "$(hostname -s 2>/dev/null || hostname)" > "$T/cfg.json"
export BOARD_ASKS_CONFIG="$T/cfg.json" BOARD_ASKS_ENGINE="$ENGINE" BOARD_ASKS_STATE_DIR="$T/state" BOARD_ASKS_VALIDATOR="$T/none.py"
fail=0
check() { if eval "$2"; then :; else echo "FAIL: $1"; fail=1; fi; }
out="$(BOARD_ASKS_PREFIX=Z python3 "$ENGINE" ask --root "$T/board" --session s1 --text '問い一' --recommend 'はい' --ground choice)"
check '問いを立てると印つきの段が出る (中身が先、 印は後ろ)' '[[ "$out" == *"問い一 〔問 Z1〕"* ]]'
tr="$T/t.jsonl"
jq -nc '{type:"user",message:{role:"user",content:"見せて"}}' > "$tr"
jq -nc '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:"### 1. 報告\n問い一 〔問 Z1〕"}]}}' >> "$tr"
out="$(jq -nc --arg t "$tr" '{hook_event_name:"Stop",session_id:"s1",transcript_path:$t}' | "$HOOK")"
check 'Stop: 印つきの問いは差し戻さない' '[ -z "$out" ]'
out="$(jq -nc --arg t "$tr" '{hook_event_name:"UserPromptSubmit",session_id:"s1",transcript_path:$t,prompt:"１はメールで伝えよう"}' | "$HOOK")"
check 'UserPromptSubmit: 見出しの番号と並ぶ問いへの「１は…」 は推定' '[[ "$out" == *"🔒"* ]]'
check '推定の印の file ができる' '[ -f "$T/state/s1.guess" ]'
out="$(jq -nc '{hook_event_name:"PreToolUse",session_id:"s1",tool_name:"SendMessage",tool_input:{}}' | "$HOOK")"
check 'PreToolUse: 推定のあいだ別の session への message を止める' '[ "$(printf "%s" "$out" | jq -r .hookSpecificOutput.permissionDecision)" = deny ]'
out="$(jq -nc '{hook_event_name:"PreToolUse",session_id:"s2",tool_name:"SendMessage",tool_input:{}}' | "$HOOK")"
check 'PreToolUse: 推定の無い session は止めない' '[ -z "$out" ]'
out="$(jq -nc --arg t "$tr" '{hook_event_name:"UserPromptSubmit",session_id:"s1",transcript_path:$t,prompt:"Z1 のこと"}' | "$HOOK")"
check 'UserPromptSubmit: 印で答え直すと確定' '[[ "$out" == *"確かめた読み"* ]]'
out="$(jq -nc '{hook_event_name:"PreToolUse",session_id:"s1",tool_name:"SendMessage",tool_input:{}}' | "$HOOK")"
check 'PreToolUse: 確定の後は止めない' '[ -z "$out" ]'
out="$(jq -nc '{hook_event_name:"SessionStart",session_id:"s1",source:"compact"}' | "$HOOK")"
check 'SessionStart: 答えの出た問いを本人の語で出す' '[[ "$(printf "%s" "$out" | jq -r .hookSpecificOutput.additionalContext)" == *"Z1 のこと"* ]]'
out="$(jq -nc '{hook_event_name:"PreCompact",session_id:"s1",trigger:"auto"}' | "$HOOK")"
check 'PreCompact: 要約への指示に印を出す' '[[ "$out" == *"Z1"* ]]'
jq -nc '{type:"user",message:{role:"user",content:"次は？"}}' >> "$tr"
jq -nc '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:"これで進めてよいですか"}]}}' >> "$tr"
out="$(jq -nc --arg t "$tr" '{hook_event_name:"Stop",session_id:"s3",transcript_path:$t}' | "$HOOK")"
check 'Stop: 印の無い問いは差し戻す' '[ "$(printf "%s" "$out" | jq -r .decision)" = block ]'
out="$(BOARD_ASKS_CONFIG="$T/missing.json" bash -c "jq -nc '{hook_event_name:\"Stop\",session_id:\"s3\"}' | '$HOOK'")"
check '設定が無ければ何もしない' '[ -z "$out" ]'
out="$(env -u BOARD_ASKS_PREFIX python3 "$ENGINE" ask --root "$T/board" --session s4 --text '問い二' --ground fact)"
check 'hook が渡した字を engine が残し、 手で打つ ask も同じ字' '[[ "$out" == *"〔問 Z2〕"* ]]'
# 前の Stop の後の返事だけを読む (app が Stop ごとに書く stop_hook_summary の行が区切り): 印の無い問いで 1 回差し戻した後、
# 背景の作業の知らせで始まる次の turn に問いが無ければ、 前の段を読み直して差し戻さない (直す前の engine はここで鳴った)
tr2="$T/t2.jsonl"
jq -nc '{type:"user",message:{role:"user",content:"状況は？"}}' > "$tr2"
jq -nc '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:"A と B のどちらにするか決めてください。"}]}}' >> "$tr2"
out="$(jq -nc --arg t "$tr2" '{hook_event_name:"Stop",session_id:"s6",transcript_path:$t}' | "$HOOK")"
check 'Stop: 印の無い問いは差し戻す (前の Stop の区切りが無い会話記録)' '[ "$(printf "%s" "$out" | jq -r .decision)" = block ]'
jq -nc '{type:"system",subtype:"stop_hook_summary"}' >> "$tr2"
jq -nc '{type:"user",message:{role:"user",content:"<task-notification>done</task-notification>"}}' >> "$tr2"
jq -nc '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:"背景の作業が終わりました。"}]}}' >> "$tr2"
out="$(jq -nc --arg t "$tr2" '{hook_event_name:"Stop",session_id:"s6",transcript_path:$t}' | "$HOOK")"
check 'Stop: 前の Stop の後の turn に問いが無ければ、 前の段を読み直して差し戻さない' '[ -z "$out" ]'
printf 'import sys\nsys.stderr.write("boom\\n")\nsys.exit(2)\n' > "$T/broken.py"
out="$(BOARD_ASKS_ENGINE="$T/broken.py" bash -c "jq -nc '{hook_event_name:\"Stop\",session_id:\"s5\",transcript_path:\"$tr\"}' | '$HOOK'")"
check 'engine が落ちても何も出さない' '[ -z "$out" ]'
check 'engine の失敗を記録に残す' 'grep -q "Stop s5 rc=2" "$T/state/hook-errors.log" && grep -q boom "$T/state/hook-errors.log"'
[ "$fail" = 0 ] && echo "owner-asks.test: OK" || { echo "owner-asks.test: FAIL"; exit 1; }
