#!/usr/bin/env python3
"""test-worker-safety-stop.py — synthetic regression checks for refusal handling and duplicate guidance.

Run --selftest. Uses isolated registry/transcript fixtures and actual CLI/hook
processes; never sends a message or invokes a provider. Contains no real log text.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE / "lib"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selftest():
    count = 0
    def check(label, condition):
        nonlocal count
        assert condition, label
        count += 1
        print("ok: " + label)
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        sid="aaaaaaaa-1111-2222-3333-444444444444";sessions=root/"registry";projects=root/"projects";sessions.mkdir();(projects/"-fixture").mkdir(parents=True)
        transcript=projects/"-fixture"/(sid+".jsonl")
        (sessions/"live.json").write_text(json.dumps({"pid":os.getpid(),"sessionId":sid,"hostSessionId":"local_fixture","cwd":"/fixture","name":"fixture-worker"}))
        env={**os.environ,"CLAUDE_SESSIONS_DIR":str(sessions),"CLAUDE_PROJECTS_DIR":str(projects)}
        event={"hook_event_name":"PreToolUse","session_id":"sender","tool_name":"SendMessage","tool_input":{"to":"local_fixture","message":"continue"}}
        hook=HERE.parent/"hooks"/"worker-safety-stop-guard.py"
        def invoke():
            return subprocess.run([sys.executable,str(hook)],input=json.dumps(event),env=env,capture_output=True,text=True)
        transcript.write_text(json.dumps({"type":"user","isMeta":True,"refusedMessageId":"fixture-refusal","message":{"content":"CANARY_NOTICE"}})+"\n")
        out=invoke();check("actual hook refuses recorded refusal with exit 2",out.returncode==2 and "SendMessage" in out.stderr)
        check("hook does not emit message text","CANARY" not in out.stdout+out.stderr)
        transcript.write_text(json.dumps({"type":"user","message":{"content":"safeguards flagged this message"}})+"\n")
        out=invoke();check("actual hook allows ordinary quoted notice",out.returncode==0 and not out.stdout)
        transcript.unlink();out=invoke();check("missing transcript is visibly unknown",out.returncode==0 and "未確認" in out.stdout)

        dedupe=load("spawn_dedupe_fixture",HERE/"lib"/"spawn_dedupe.py")
        dedupe.SESSIONS_DIR=str(sessions);dedupe.PROJECTS_DIR=str(projects);dedupe.STATE_DIR=str(root/"ledger")
        transcript.write_text(json.dumps({"type":"user","isMeta":True,"refusedMessageId":"fixture-refusal"})+"\n")
        rc,msg=dedupe.pre_spawn({"session_id":"sender","tool_input":{"title":"fixture-worker","prompt":"fixture"}},ext=dedupe._NoExt())
        check("refused live process still prevents duplicate spawn",rc==2)
        check("duplicate message asks owner about closure", "閉じてよいか本人に確認" in msg and "同じ窓への SendMessage は送らず" in msg)
        transcript.write_text(json.dumps({"type":"user","message":{"content":"ordinary"}})+"\n")
        rc,msg=dedupe.pre_spawn({"session_id":"sender","tool_input":{"title":"fixture-worker","prompt":"fixture"}},ext=dedupe._NoExt())
        check("ordinary live duplicate still blocked",rc==2 and "通常の訂正" in msg)
        transcript.unlink()
        rc,msg=dedupe.pre_spawn({"session_id":"sender","tool_input":{"title":"fixture-worker","prompt":"fixture"}},ext=dedupe._NoExt())
        check("unreadable duplicate status is visibly unknown",rc==2 and "未確認" in msg)
    print(f"test-worker-safety-stop: {count} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
