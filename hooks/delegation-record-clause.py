#!/usr/bin/env python3
"""delegation-record-clause.py — 委任時に成果報告の3項目を追加する (PreToolUse[Agent])。

報告項目は、捨てた案と理由・作業中の発見・未確認事項。
成果物の受領と後の整理に必要な項目を、最初の依頼で伝える。
共通文面は scripts/lib/worker_record_clause.py が所有する。

動作:
  PreToolUse で tool_name が Agent (旧名 Task) の時だけ、 tool_input.prompt の末尾に下の CLAUSE を足した
  updatedInput を返す。 prompt に MARKER が既にあれば何もしない (冪等 = 手で書いた・再送した指示に二重に足さない)。
  止めない・許可の判断はしない (permissionDecision を返さない = 通常の許可の流れのまま)。 全 error path で fail-open。
  agent の再開 (SendMessage) には足さない = 最初の指示で約束は渡っている。

配線: hooks/settings-entries.json の PreToolUse[Agent|Task] (setup.sh / scripts/sync-hook-settings.sh が ~/.claude/settings.json へ)。
後から引く道具: scripts/subagent-reports.py (受け渡しの報告の全部と、 agent が書いた file)、
               scripts/search-agent-transcripts.py --session <id> (agent の記録も読む)。

usage:
  delegation-record-clause.py            # hook (stdin = PreToolUse JSON)
  delegation-record-clause.py --selftest
"""
from __future__ import annotations

import json
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/lib'))
from worker_record_clause import MARKER, CLAUSE

TOOLS = ("Agent", "Task")


def rewrite(ev: dict) -> dict | None:
    """hook の出力 (dict) か、 何もしないなら None。"""
    if ev.get("hook_event_name", "PreToolUse") != "PreToolUse":
        return None
    if ev.get("tool_name") not in TOOLS:
        return None
    inp = ev.get("tool_input")
    if not isinstance(inp, dict):
        return None
    prompt = inp.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or MARKER in prompt:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "updatedInput": dict(inp, prompt=prompt.rstrip() + CLAUSE)}}


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    try:
        out = rewrite(json.loads(sys.stdin.read() or "{}"))
        if out is not None:
            print(json.dumps(out, ensure_ascii=False))
    except Exception:  # noqa: BLE001  fail-open: hook の故障で委ねる操作を止めない
        pass
    return 0


def selftest() -> int:
    import subprocess
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and bool(cond)

    ev = {"hook_event_name": "PreToolUse", "tool_name": "Agent",
          "tool_input": {"description": "d", "prompt": "調べて直して", "subagent_type": "general-purpose",
                         "run_in_background": True}}
    out = rewrite(ev)
    new = (out or {}).get("hookSpecificOutput", {}).get("updatedInput", {})
    expected = (
        "作業の最後に、次の3項目を簡潔に報告してください。成果物のfileに書く場合は、そのpathを報告してください。"
        "該当が無い項目は「なし」と書いてください。"
    )
    check(CLAUSE.splitlines()[3] == expected, "report introduction requests only deliverable items")
    check(new.get("prompt", "").endswith(CLAUSE), "Agent receives the full shared report contract")
    check(new.get("prompt", "").startswith("調べて直して") and MARKER in new.get("prompt", ""), "Agent: 指示の末尾に約束の段を足す")
    check({k: v for k, v in new.items() if k != "prompt"} == {k: v for k, v in ev["tool_input"].items() if k != "prompt"},
          "prompt 以外の入力は変えない")
    check("permissionDecision" not in (out or {}).get("hookSpecificOutput", {}), "許可の判断は返さない")
    check(rewrite(dict(ev, tool_input=dict(ev["tool_input"], prompt=new.get("prompt", "")))) is None, "既に約束がある指示には足さない (冪等)")
    check(rewrite(dict(ev, tool_name="Task")) is not None, "旧名 Task にも足す")
    check(rewrite(dict(ev, tool_name="Bash", tool_input={"command": "ls"})) is None, "Agent 以外は何もしない")
    check(rewrite(dict(ev, hook_event_name="PostToolUse")) is None, "PreToolUse 以外は何もしない")
    check(rewrite(dict(ev, tool_input=dict(ev["tool_input"], prompt=""))) is None, "空の指示には足さない")
    r = subprocess.run([sys.executable, __file__], input="not json", capture_output=True, text=True)
    check(r.returncode == 0 and r.stdout.strip() == "", "壊れた stdin は fail-open (無言 exit 0)")
    r = subprocess.run([sys.executable, __file__], input=json.dumps(ev, ensure_ascii=False), capture_output=True, text=True)
    check(r.returncode == 0 and '"updatedInput"' in r.stdout and MARKER in json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["prompt"],
          "新しい process で stdin JSON → updatedInput の JSON")
    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
