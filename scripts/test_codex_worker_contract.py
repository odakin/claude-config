#!/usr/bin/env python3
"""test_codex_worker_contract.py — record-context boundaries and scoped observations (--selftest, --against OLD_HOOK)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parent/'lib'))
import codex_worker_contract as contract
import worker_observations as records

PARENT='11111111-1111-4111-8111-111111111111'
CHILD='22222222-2222-4222-8222-222222222222'


def selftest(against=None):
    with tempfile.TemporaryDirectory() as td:
        root=Path(td).resolve()
        saved={k:os.environ.get(k) for k in ('CODEX_THREAD_ID','CODEX_SESSION_ID','CODEX_WORKER_RECORD_DIR')}
        os.environ['CODEX_THREAD_ID']=PARENT
        os.environ.pop('CODEX_SESSION_ID',None)
        os.environ['CODEX_WORKER_RECORD_DIR']=str(root/'records')
        try:
            event={'hook_event_name':'SubagentStart','session_id':PARENT,'agent_id':CHILD,'turn_id':'synthetic-turn'}
            if against:
                p=subprocess.run([sys.executable,str(against)],input=json.dumps(event),text=True,capture_output=True,check=True)
                assert contract.MARKER in p.stdout, 'old Codex hook does not deliver the subagent record clause'
            else:
                assert contract.MARKER in json.dumps(contract.handle(event),ensure_ascii=False)
            event={'hook_event_name':'UserPromptSubmit','session_id':CHILD,'turn_id':'child-turn','prompt':'synthetic task'}
            result=contract.handle(event)
            assert result['hookSpecificOutput']['additionalContext'] == contract.CLAUSE
            assert contract.CLAUSE.splitlines()[3].startswith('作業の最後に、次の3項目を簡潔に報告してください。')
            assert contract.MARKER in result['hookSpecificOutput']['additionalContext']
            assert 'permissionDecision' not in json.dumps(result) and 'updatedInput' not in json.dumps(result)
            assert contract.handle(dict(event,session_id=PARENT)) is None
            assert contract.handle(dict(event,prompt='')) is None
            assert contract.handle(dict(event,prompt=contract.CLAUSE)) is None
            os.environ.pop('CODEX_THREAD_ID')
            assert contract.handle(event) is None
            assert contract.handle(event,'claude') is None
            os.environ['CODEX_THREAD_ID']=PARENT
            assert contract.MARKER in json.dumps(contract.handle(event,'claude'),ensure_ascii=False)
            for cmd in ('codex exec task','claude -p task','claude --bare -p task','env -i codex exec task'):
                output=contract.handle({'hook_event_name':'PreToolUse','session_id':PARENT,'tool_use_id':cmd,
                                        'tool_name':'Bash','tool_input':{'command':cmd}})
                assert 'updatedInput' not in json.dumps(output) and 'permissionDecision' not in json.dumps(output)
            missing=contract.handle({'hook_event_name':'PreToolUse','tool_name':'mcp__codex_app__create_thread',
                                     'tool_input':{'prompt':'synthetic task','target':{'type':'projectless'}}})
            assert missing['hookSpecificOutput']['permissionDecision']=='deny'
            assert contract.handle({'hook_event_name':'PreToolUse','tool_name':'mcp__codex_app__create_thread',
                                    'tool_input':{'prompt':'synthetic task'+contract.CLAUSE}}) is None
            assert contract.handle({'hook_event_name':'PreToolUse','tool_name':'mcp__another__create_thread',
                                    'tool_input':{'prompt':'synthetic task'}}) is None
            print('OK: native/headless context, root and empty controls, unchanged Bash input, narrow other-session guard')

            log=root/'child.jsonl'
            old=json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':'OLDER_UNRELATED'}]}})+'\n'
            log.write_text(old)
            start={'session_id':CHILD,'prompt':'first task','transcript_path':str(log)}
            records.observe(start,'claude','prompt',parent=PARENT)
            report='discarded / noticed / unverified'
            with log.open('a') as f:
                f.write(json.dumps({'type':'assistant','message':{'content':[{'type':'thinking','thinking':'NEVER_EXPORT'}, {'type':'text','text':report}]}})+'\n')
            records.observe(dict(start,last_assistant_message=report),'claude','stop',parent=PARENT)
            rows, errors=records.read(PARENT)
            assert not errors
            found, errors=records.claude_reports([r for r in rows if r.get('position')])
            assert not errors and found[0]['text']==report
            assert 'OLDER_UNRELATED' not in json.dumps(found) and 'NEVER_EXPORT' not in json.dumps(found)
            assert all('first task' not in p.read_text() for p in (root/'records').rglob('*.json'))
            records.observe(dict(start,prompt='resumed task'),'claude','prompt',parent=PARENT)
            with log.open('a') as f:f.write(json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':'second report'}]}})+'\n')
            records.observe(dict(start,last_assistant_message='second report'),'claude','stop',parent=PARENT)
            rows,_=records.read(PARENT)
            found,errors=records.claude_reports([r for r in rows if r.get('position')])
            assert len(found)==2 and not errors
            print('OK: exact invocation ranges, resumed reports, no prompt/reasoning copies or older report borrowing')
            late=root/'late.jsonl'
            late_event={'session_id':'33333333-3333-4333-8333-333333333333','prompt':'late fixture','transcript_path':str(late)}
            records.observe(late_event,'claude','prompt',parent=PARENT)
            records.observe(dict(late_event,last_assistant_message='late report'),'claude','stop',parent=PARENT)
            late.write_text(old+json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':'late report'}]}})+'\n')
            late_rows,_=records.read(PARENT)
            found,errors=records.claude_reports([r for r in late_rows if r['child']==late_event['session_id']])
            assert found[0]['text']=='late report' and not errors
            print('OK: delayed transcript flush recovers only the observed Stop hash')

            records.mark_collected(PARENT,'synthetic-repo@verified')
            before,_=records.read(PARENT)
            records.observe(event,'codex','prompt',parent=PARENT)
            now=time.time_ns()+(records.RETENTION+1)*1_000_000_000
            count=records.prune_collected(now_ns=now)
            remaining,errors=records.read(PARENT)
            assert count==len(before) and len(remaining)==1 and not errors
            assert records.prune_collected(now_ns=now)==0
            print('OK: only acknowledged metadata expires; newer uncollected evidence survives')
        finally:
            for key,value in saved.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value
    return 0


if __name__=='__main__':
    old=Path(sys.argv[sys.argv.index('--against')+1]) if '--against' in sys.argv else None
    raise SystemExit(selftest(old))
