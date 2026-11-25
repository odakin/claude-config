#!/usr/bin/env bash
# owner-asks.test.sh — owner-asks.sh (本人への問いと答えの台帳の hook の入口) の試験
# 一時の掲示板 (.local を持つ dir)・設定・状態の dir を作り、 event ごとに hook を呼んで出力を確かめる。
# engine は隣の checkout の ai-collaboration/board/board_asks.py (無ければ skip = exit 0)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/owner-asks.sh"
if [ -n "${BOARD_ASKS_TEST_HOOK:-}" ]; then
  HOOK="$BOARD_ASKS_TEST_HOOK"
fi
ENGINE="${BOARD_ASKS_ENGINE:-$(cd "$HERE/../.." && pwd)/ai-collaboration/board/board_asks.py}"
[ -f "$ENGINE" ] || { echo "skip: engine が無い ($ENGINE)"; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "skip: jq が無い"; exit 0; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/board/.local" "$T/state"
printf '{"root": "%s", "prefix": {"%s": "Z"}}\n' "$T/board" "$(hostname -s 2>/dev/null || hostname)" > "$T/cfg.json"
export BOARD_ASKS_CONFIG="$T/cfg.json" BOARD_ASKS_ENGINE="$ENGINE" BOARD_ASKS_STATE_DIR="$T/state" BOARD_ASKS_VALIDATOR="$T/none.py"
fail=0
check() { if eval "$2"; then :; else echo "FAIL: $1"; fail=1; fi; }
out="$(BOARD_ASKS_PREFIX=Z python3 "$ENGINE" ask --root "$T/board" --session s1 --about '試験の台帳で立てる話' --text '問い一' --recommend 'はい' --ground choice --prior-term 試験 --prior '無し (見た範囲 = 試験の台帳)')"
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
out="$(env -u BOARD_ASKS_PREFIX python3 "$ENGINE" ask --root "$T/board" --session s4 --about '試験の台帳で立てる話' --text '問い二' --ground fact)"
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

# One real hook chain with synthetic questions, a recipient and a protected candidate. Optional approval
# checks use the actual downstream readers. The fixture never calls a sender or changes a live file.
if ! python3 -B - "$ENGINE" "$HOOK" "$T" <<'PY'
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

engine, hook, root = sys.argv[1], sys.argv[2], Path(sys.argv[3])
board = root / "board"
session = "group-chain"
ledger = board / ".local" / "asks.jsonl"
transcript = root / "group-chain.jsonl"


def cli(*args):
    return subprocess.run([sys.executable, "-B", engine, *args, "--root", str(board), "--session", session],
                          encoding="utf-8", capture_output=True, check=True).stdout.strip()


def pretool(tool, **tool_input):
    return event("PreToolUse", tool_name=tool, tool_input=tool_input).get("hookSpecificOutput", {})


def event(name, **kwargs):
    data = dict(hook_event_name=name, session_id=session, transcript_path=str(transcript), **kwargs)
    result = subprocess.run(["bash", hook], input=json.dumps(data), encoding="utf-8",
                            capture_output=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def row(role, content):
    stamp = "2026-01-01T00:00:00Z"
    with transcript.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(type=role, timestamp=stamp, message=dict(role=role, content=content)),
                                ensure_ascii=False) + "\n")


def reply(text, extra=()):
    row("assistant", [{"type": "text", "text": text}, *extra])


def prompt(text):
    result = event("UserPromptSubmit", prompt=text)
    row("user", text)
    return result.get("hookSpecificOutput", {}).get("additionalContext", "")


def rows():
    return [json.loads(line) for line in ledger.read_text().splitlines()]


questions = ("資料を日付順に並べるか", "見出しを短くするか", "別表を一枚にまとめるか")
for question in questions:
    cli("ask", "--groupable", "--ground", "choice", "--about", "資料を読みやすくする話",
        "--text", question, "--recommend", "この案で作る",
        "--prior-term", "資料", "--prior", "無し (見た範囲 = 試験)")
labels = [record["label"] for record in rows() if record.get("session") == session and record["type"] == "ask"]
assert len(labels) == 3, labels
row("user", "問いを見せて")
reply(cli("list", "--open", "--block"))
assert "結び先が決まらない" in prompt("全部おすすめで")
assert pretool("SendMessage").get("permissionDecision") == "deny"
reading = cli("group-reading")
candidate = root / "sample.md"
candidate.write_text("Synthetic protected candidate.\n", encoding="utf-8")
sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
protected_prompt = f"sample.md の候補 {sha[:12]} を適用してよいですか"
reply(reading, [{"type": "tool_use", "id": "fake-wrap", "name": "mcp__ccd_turn__wrap_up",
                 "input": {"recap": protected_prompt, "ask": protected_prompt,
                           "actions": [{"label": "はい"}]}}])
assert "まだ結んでいない" in prompt("はい")
assert pretool("SendMessage").get("permissionDecision") == "deny"
reply(reading)
assert "確かめた読み" in prompt("yoi！")
answer = [record for record in rows() if record.get("binding") == "confirmed" and record.get("session") == session]
assert len(answer) == 1 and answer[0]["labels"] == labels
assert answer[0]["reading"] == reading and answer[0]["confirm"] == "yoi！"
assert not pretool("SendMessage")
approve_command = f"python3 /synthetic/agent-rule-guard.py approve --file sample.md --candidate {candidate} --latest"
assert pretool("Bash", command=approve_command).get("permissionDecision") == "deny"
send_command = "python3 /synthetic/send_mail.py --to test@example.invalid --subject Sample --send"
assert pretool("Bash", command=send_command).get("permissionDecision") == "deny"
assert pretool("mcp__gmail-test__send_email", to=["test@example.invalid"]).get("permissionDecision") == "deny"
reply(f"{questions[0]} ({labels[0]}) の答えを記録しました。")
assert event("Stop").get("decision") == "block"
active = event("SessionStart", source="compact").get("hookSpecificOutput", {}).get("additionalContext", "")
assert all(label in active for label in labels) and "全部おすすめで" in active

guard_path = os.environ.get("BOARD_ASKS_APPROVAL_ENGINE")
if guard_path:
    spec = importlib.util.spec_from_file_location("approval_engine", guard_path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    def bind_protected():
        lines = []
        messages = guard.user_messages(transcript, choice_answers=True, lines=lines)
        return guard.owner_relay_binding(transcript, lines, len(messages) - 1, "sample.md", str(candidate))

    assert not bind_protected()[0], "group assent bound to the protected candidate"
else:
    print("skip: protected approval reader (BOARD_ASKS_APPROVAL_ENGINE unset)")

reply(protected_prompt)
prompt("この候補を適用してよい")
assert not pretool("Bash", command=approve_command)
if guard_path:
    assert bind_protected() == (sha[:12], ""), "the separate protected approval fixture did not bind"
    print("owner-asks: protected approval reader rejects the grouped turn and accepts the separate candidate")

mail_hook = os.environ.get("BOARD_ASKS_MAIL_APPROVAL_HOOK")
if mail_hook:
    result = subprocess.run(["bash", mail_hook], input=json.dumps(
        dict(tool_name="Bash", tool_input=dict(command=send_command))),
        encoding="utf-8", capture_output=True, check=True)
    decision = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
    assert decision == "ask", decision
    assert not pretool("Bash", command=send_command)
    print("owner-asks: outbound send still asks for separate tool approval")
else:
    print("skip: mail approval hook (BOARD_ASKS_MAIL_APPROVAL_HOOK unset)")
PY
then
  fail=1
fi
[ "$fail" = 0 ] && echo "owner-asks.test: OK" || { echo "owner-asks.test: FAIL"; exit 1; }
