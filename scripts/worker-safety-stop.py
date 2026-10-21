#!/usr/bin/env python3
"""worker-safety-stop.py — inspect refusal metadata and stop sends to a refused local session.

Usage: --inspect <jsonl> (metadata only), --selftest, or hook JSON on stdin.
PreToolUse SendMessage only: exact local registry address, then typed refusal
markers in its transcript. Exit 2 refuses the send; unknown warns and returns 0.
No retries, automatic closure, launch, claim release, model switch, or text matching.
This does not establish a permanent provider lock; it prevents work resubmission
into the same refused context. Missing/remote logs, SDK/app sends, Codex tools,
and refusals without typed records are not covered. Full scans may reach timeout
on very large logs; the harness timeout is not a successful check.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import session_model as sm
import worker_safety_stop as safety


def check_send(event, sessions=None, path_resolver=None):
    if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "SendMessage":
        return 0, ""
    inp = event.get("tool_input") or {}
    if not isinstance(inp, dict):
        return 0, "worker-safety-stop: 送信先を確認できません。"
    row = safety.resolve_target(inp.get("to") or inp.get("recipient"), sm.live_sessions() if sessions is None else sessions)
    if not row:
        return 0, "worker-safety-stop: 宛先の停止状態は未確認です (この機械で一意に解決できません)。"
    status = safety.inspect((path_resolver or sm.transcript_path)(row["sessionId"], row.get("cwd")))
    if status["state"] == "refused":
        return 2, ("安全フィルタによる停止が記録された窓なので、SendMessage を止めました。"
                   "同じ窓へ続きを送らず、停止した返答を再現しないでください。"
                   "掲示板に停止と引継ぎ先を記録し、現在の claim を手放してください。"
                   "窓を閉じる必要があれば本人に確認し、再開する仕事の範囲も本人に判断を戻してください。"
                   "停止を通すための別モデルへの自動再送はしません。")
    if status["state"] == "unknown":
        return 0, "worker-safety-stop: 会話記録を検査できず、停止状態は未確認です。"
    return 0, ""


def selftest():
    import tempfile
    safety.selftest()
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp)/"session.jsonl"
        row = {"sessionId": "aaaaaaaa-1111-2222-3333-444444444444", "host": "local_test", "cwd": temp}
        event = {"hook_event_name": "PreToolUse", "tool_name": "SendMessage", "tool_input": {"to": "local_test", "message": "continue"}}
        check = lambda e: check_send(e, [row], lambda *_: path)
        path.write_text(json.dumps({"type": "user", "isMeta": True, "refusedMessageId": "synthetic", "message": {"content": "DO_NOT_EMIT"}})+"\n")
        assert check(event)[0] == 2
        assert "DO_NOT_EMIT" not in check(event)[1]
        assert check({**event, "tool_name": "Read"}) == (0, "")
        assert check({**event, "hook_event_name": "PostToolUse"}) == (0, "")
        assert check({**event, "tool_input": {"recipient": "local_test"}})[0] == 2
        path.write_text(json.dumps({"type": "user", "message": {"content": "safeguards flagged this message"}})+"\n")
        assert check(event) == (0, "")
        path.unlink(); assert check(event)[0] == 0 and "未確認" in check(event)[1]
        assert check({**event, "tool_input": {"to": "remote"}})[0] == 0
    print("worker-safety-stop CLI: 8 checks")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inspect")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.inspect:
        print(json.dumps(safety.inspect(args.inspect)))
        return 0
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("input")
        rc, message = check_send(event)
    except Exception as exc:
        print("worker-safety-stop: 検査不能 ("+type(exc).__name__+")。停止状態は未確認です。", file=sys.stderr)
        return 0
    if message:
        if rc == 2:
            print(message, file=sys.stderr)
        else:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}}, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
