#!/usr/bin/env python3
"""codex-wrap-inventory.py — Codexの指定sessionの会話・道具・委譲先をread-onlyで集める。--selftest。

Uses thread/read(includeTurns=true), not a scan of unrelated local history.
Pass the full session ID from SessionStart. Only exposed reasoning summaries
(the typed summary field) are collected; raw/encrypted reasoning is never exported. User-message transport labels are not proof of human approval.
Subagents are followed only from a spawn in the addressed parent, and their
parentThreadId is checked. Every resumed turn's final report is retained.
Unavailable children, unknown tool forms, incomplete calls and text-only launch
candidates stay visible; none are silently counted as zero activity.

Headless command parsing shares the vendor-neutral runner's conservative lexer.
Board/token commands and other-session tools are reported as explicit routes for
the owning wrap skill to inspect; this program never posts or consumes a marker.
Artifacts are paths from recorded file changes; shell-created files and outputs
inside scripts still need inspection of the reported commands and worker reports.
Default text truncation is labeled; --max-chars 0 and --json preserve full visible
messages/tool outputs. Treat that output as private session material.
Command outputs also feed the shared reconciliation in lib/output_numbers.py
(the sole source for its rules and limits). Summary/commands show 🔢 candidates;
JSON includes number_results, number_repos and numbers_not_recorded (call count).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from codex_thread_reader import Reader
import headless_record_clause as headless
import worker_observations as observations
import output_numbers

HINT = re.compile(r'\b(?:claude\b[^\n]*?\s(?:-p|--print)\b|codex\s+(?:exec|e)\b)')
KNOWN_PASSIVE = {'sleep', 'contextCompaction', 'plan', 'webSearch', 'imageView',
                 'imageGeneration', 'enteredReviewMode', 'exitedReviewMode', 'hookPrompt'}


def visible_text(content):
    if not isinstance(content, list):
        return content if isinstance(content, str) else ''
    return '\n'.join(x['text'] for x in content if isinstance(x, dict) and
                     x.get('type') in ('text', 'input_text', 'output_text') and isinstance(x.get('text'), str))


def shell_payload(command):
    # The native execution item records the transport shell around the input.
    # Decode only a literal shell -c argument; never execute history as code.
    try:
        args = shlex.split(command)
    except ValueError:
        return command
    if len(args) == 3 and Path(args[0]).name in ('sh','bash','zsh') and args[1] in ('-c','-lc','-cl','-lic'):
        return args[2]
    return command


def command_routes(command):
    command = shell_payload(command)
    routes, launches = [], []
    try:
        commands = headless.shell_commands(command)
    except ValueError:
        return [], ([{'evidence':'text_only', 'kind':'unresolved'}] if HINT.search(command) else []), True
    for words in commands:
        position = headless.executable_index(words)
        args = [w.value for w in words[position:]] if position is not None else []
        worker_args = args
        explicit = False
        if args and args[0] and Path(args[0]).name.startswith('python') and len(args)>2 and args[1] and Path(args[1]).name in ('headless-record-clause-nudge.py','headless_record_clause.py'):
            if '--run' in args[2:]:
                worker_args = args[args.index('--run',2)+1:]
                explicit = True
        kind = headless.worker_kind(worker_args)
        if kind:
            launches.append({'evidence':'executable_position', 'kind':kind,
                             'marker_in_command':headless.MARKER in command, 'explicit_runner':explicit})
        # Exact executable/script position, not a filename mentioned by echo/grep.
        script_at = 1 if args and args[0] and Path(args[0]).name.startswith('python') else 0
        name = Path(args[script_at]).name if len(args) > script_at and args[script_at] else ''
        if name in ('board.py', 'surface-spawn-results.py'):
            routes.append({'route':'board' if name == 'board.py' else 'token', 'argv':args, 'action':args[script_at+1] if len(args)>script_at+1 else 'unspecified'})
    if not launches and HINT.search(command):
        launches.append({'evidence':'text_only', 'kind':'unresolved'})
    return routes, launches, False


def summarize(thread):
    if not isinstance(thread, dict) or not isinstance(thread.get('id'), str) or not isinstance(thread.get('turns'), list):
        raise ValueError('unsupported thread shape')
    out = {'id':thread['id'], 'parent':thread.get('parentThreadId'), 'cwd':thread.get('cwd'),
           'model':thread.get('model'), 'status':thread.get('status'),
           'messages':[], 'reasoning_summaries':[], 'tools':[], 'files':[], 'spawns':[], 'headless':[],
           'routes':[], 'warnings':[]}
    for turn in thread['turns']:
        if not isinstance(turn, dict) or not isinstance(turn.get('items'), list):
            out['warnings'].append('unreadable turn')
            continue
        tid = turn.get('id')
        for item in turn['items']:
            if not isinstance(item, dict):
                out['warnings'].append('unreadable item')
                continue
            typ, iid = item.get('type'), item.get('id')
            if typ == 'userMessage':
                out['messages'].append({'turn':tid, 'id':iid, 'role':'userMessage', 'text':visible_text(item.get('content'))})
            elif typ == 'agentMessage':
                out['messages'].append({'turn':tid, 'id':iid, 'role':'assistant',
                                        'phase':item.get('phase'), 'text':item.get('text','')})
            elif typ == 'reasoning':
                # Public-facing summary only. Never fall back to content or
                # encrypted_content even if a provider happens to expose them.
                summary=item.get('summary')
                valid=isinstance(summary,list) and all(isinstance(x,str) for x in summary)
                text='\n'.join(summary) if valid else ''
                state='available' if text.strip() else 'not_exposed'
                if summary is not None and not valid:
                    state='unreadable'
                    out['warnings'].append('reasoning summary format unreadable: '+str(iid))
                out['reasoning_summaries'].append({'turn':tid,'id':iid,'source':'reasoning.summary',
                                                    'availability':state,'text':text})
            elif typ == 'commandExecution':
                command = item.get('command')
                if not isinstance(command, str):
                    out['warnings'].append('command input missing: '+str(iid))
                    continue
                out['tools'].append({'turn':tid, 'id':iid, 'tool':'Bash', 'input':command,
                                     'output':item.get('aggregatedOutput'), 'cwd':item.get('cwd'),
                                     'status':item.get('status'), 'exit_code':item.get('exitCode')})
                routes, launches, unsupported = command_routes(command)
                for route in routes:
                    out['routes'].append(dict(route, call=iid))
                for launch in launches:
                    out['headless'].append(dict(launch, call=iid, command=command, cwd=item.get('cwd'),
                                               status=item.get('status'), exit_code=item.get('exitCode')))
                out['tools'][-1]['shell_parse'] = 'unsupported' if unsupported else 'simple_commands'
                if unsupported and HINT.search(command):
                    out['warnings'].append('delegation candidate in uninspected shell grammar: '+str(iid))
            elif typ == 'fileChange':
                if not isinstance(item.get('changes'), list):
                    out['warnings'].append('file change list unreadable: '+str(iid))
                    continue
                for change in item['changes']:
                    if isinstance(change, dict) and isinstance(change.get('path'), str):
                        out['files'].append({'turn':tid,'call':iid,'path':change['path'],
                                             'kind':change.get('kind'),'status':item.get('status')})
            elif typ == 'subAgentActivity':
                target=item.get('agentThreadId')
                out['tools'].append({'turn':tid,'id':iid,'tool':'hostedSubagentActivity','input':item.get('agentPath'),
                                     'output':item.get('kind'),'status':item.get('kind')})
                if item.get('kind')=='started' and isinstance(target,str) and target!=thread['id']:
                    out['spawns'].append({'id':target,'call':iid,'status':'started','agent_path':item.get('agentPath'),
                                          'marker_in_prompt':None,'source':'hosted_activity'})
                elif not isinstance(target,str):
                    out['warnings'].append('hosted agent identity unavailable: '+str(iid))
            elif typ == 'collabAgentToolCall':
                tool = item.get('tool')
                out['tools'].append({'turn':tid,'id':iid,'tool':tool,'input':item.get('prompt'),
                                     'output':item.get('agentsStates'),'status':item.get('status')})
                if tool not in ('spawnAgent','sendInput','resumeAgent','wait','closeAgent','sendMessage','followupTask','interruptAgent','listAgents'):
                    out['warnings'].append('unsupported collab tool: '+str(tool))
                if item.get('senderThreadId') != thread['id']:
                    out['warnings'].append('collab sender mismatch: '+str(iid))
                    continue
                if tool == 'spawnAgent':
                    receivers = item.get('receiverThreadIds')
                    if not isinstance(receivers, list) or not receivers:
                        out['warnings'].append('spawn has no resolved child: '+str(iid))
                    else:
                        for child in receivers:
                            if isinstance(child, str) and child != thread['id']:
                                out['spawns'].append({'id':child,'call':iid,'status':item.get('status'),
                                                      'marker_in_prompt':headless.MARKER in (item.get('prompt') or '')})
                            else:
                                out['warnings'].append('invalid child identity: '+str(iid))
            elif typ in ('mcpToolCall','dynamicToolCall'):
                name = item.get('tool','')
                result = item.get('result') if typ == 'mcpToolCall' else item.get('contentItems')
                out['tools'].append({'turn':tid,'id':iid,'tool':name,'namespace':item.get('server',item.get('namespace')),
                                     'input':item.get('arguments'),'output':result,'status':item.get('status')})
                if re.search(r'(?:create_thread|send_message_to_thread|fork_thread|handoff_thread)$', name):
                    out['routes'].append({'route':'other_session','call':iid,'tool':name,
                                           'arguments':item.get('arguments'),'result':result})
                elif name.rsplit('__',1)[-1].rsplit('.',1)[-1] in {
                        'set_thread_archived','set_thread_read_state','set_thread_title',
                        'list_threads','read_thread','wait_threads','navigate_to_codex_page',
                        'read_thread_terminal','list_archived_threads'}:
                    pass  # These tools manage/read threads; their inputs/results remain above.
                elif any(x in name for x in ('spawn','agent','thread')):
                    out['warnings'].append('unclassified delegation tool: '+str(name))
            elif typ not in KNOWN_PASSIVE:
                out['warnings'].append('unsupported item type: '+str(typ))
    return out


def collect(root_id, read_thread, max_threads=128):
    root = read_thread(root_id)
    if not isinstance(root, dict) or root.get('id') != root_id:
        raise ValueError('root identity mismatch')
    result = {'root':root_id,'threads':[],'unavailable':[],'scope':'addressed parent and verified spawned descendants'}
    pending = [(root,None)]
    seen = set()
    while pending:
        thread, parent = pending.pop(0)
        ident = thread['id']
        if ident in seen:
            continue
        if len(seen) >= max_threads:
            result['unavailable'].append({'id':ident,'reason':'explicit thread limit reached; rerun with a higher limit'})
            continue
        if parent is not None and thread.get('parentThreadId') != parent:
            result['unavailable'].append({'id':ident,'reason':'parent identity mismatch; body not exported'})
            continue
        seen.add(ident)
        view = summarize(thread)
        result['threads'].append(view)
        for spawn in view['spawns']:
            if spawn['id'] in seen:
                continue
            try:
                child = read_thread(spawn['id'])
                if not isinstance(child, dict) or child.get('id') != spawn['id']:
                    raise ValueError('child identity mismatch')
                pending.append((child,ident))
            except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                result['unavailable'].append({'id':spawn['id'],'reason':type(exc).__name__})
    return result


def add_observed_workers(data, read_thread, directory=None, max_threads=128):
    """Supplement native edges with the exact turns/ranges observed by worker hooks."""
    data['worker_observations']=[]
    data['claude_reports']=[]
    seen={t['id'] for t in data['threads']}
    index=0
    while index<len(data['threads']):
        parent=data['threads'][index]
        index+=1
        if not observations.SID.fullmatch(parent['id']):continue
        rows,errors=observations.read(parent['id'],directory)
        parent['warnings'].extend('observation: '+e for e in errors)
        data['worker_observations'].extend(rows)
        launched={x['kind'] for x in parent['headless'] if x['evidence']=='executable_position' and x.get('status')=='completed'}
        observed={x['vendor'] for x in rows if x['phase']=='prompt'}
        for vendor in sorted(launched-observed):
            parent['warnings'].append(vendor+' launch has no worker-side observation; inspect stdout/artifacts and hook/environment coverage')
        reports,errors=observations.claude_reports(rows)
        data['claude_reports'].extend(reports)
        parent['warnings'].extend(errors)
        ids={r['child'] for r in rows if r['vendor']=='codex' and r['phase'] in ('prompt','subagent_start')}
        for child_id in sorted(ids-seen):
            if len(seen)>=max_threads:
                data['unavailable'].append({'id':child_id,'reason':'explicit thread limit reached; rerun with a higher limit'})
                continue
            selected=[r for r in rows if r['child']==child_id]
            native=any(r['phase']=='subagent_start' for r in selected)
            turns={r['turn'] for r in selected if r['phase'] in ('prompt','stop') and isinstance(r.get('turn'),str)}
            hashes={r['report_hash'] for r in selected if r.get('report_hash')}
            try:
                child=read_thread(child_id)
                if child.get('id')!=child_id:raise ValueError('child identity mismatch')
                if native:
                    if child.get('parentThreadId')!=parent['id']:raise ValueError('native parent identity mismatch')
                elif turns:
                    child=dict(child,turns=[t for t in child.get('turns',[]) if t.get('id') in turns])
                    if not child['turns']:raise ValueError('observed worker turns unavailable')
                else:
                    # Older/ephemeral interfaces without turn IDs expose only a Stop-hash match.
                    kept=[]
                    for turn in child.get('turns',[]):
                        items=[m for m in turn.get('items',[]) if m.get('type')=='agentMessage' and
                               m.get('phase')!='commentary' and isinstance(m.get('text'),str) and observations.digest(m['text']) in hashes]
                        if items:kept.append(dict(turn,items=items))
                    if not kept:raise ValueError('scoped worker reports unavailable; inspect parent stdout/artifacts')
                    child=dict(child,turns=kept)
                view=summarize(child)
                view['relation']='native_subagent' if native else 'observed_Codex_environment'
                data['threads'].append(view)
                seen.add(child_id)
                # Native descendants remain bound to this verified worker, never to cwd proximity.
                for spawn in view['spawns']:
                    if spawn['id'] in seen:continue
                    remaining=max_threads-len(seen)
                    if remaining<1:
                        data['unavailable'].append({'id':spawn['id'],'reason':'explicit thread limit reached; rerun with a higher limit'})
                        continue
                    branch=collect(spawn['id'],read_thread,remaining)
                    if branch['threads'][0]['parent']!=child_id:
                        raise ValueError('worker descendant parent mismatch')
                    for descendant in branch['threads']:
                        if descendant['id'] not in seen:
                            data['threads'].append(descendant);seen.add(descendant['id'])
                    data['unavailable'].extend(branch['unavailable'])
            except (OSError,ValueError,RuntimeError,TimeoutError,KeyError,TypeError) as exc:
                data['unavailable'].append({'id':child_id,'reason':str(exc),'fallback':'parent command output and declared artifacts'})
    return data


def number_repos(data):
    """Resolve only recorded working directories, change paths and command paths."""
    candidates = set()

    def add(path, cwd=None):
        if not isinstance(path, str) or not path:
            return
        if '\0' in path or '\n' in path:
            return
        p = Path(path).expanduser()
        if not p.is_absolute():
            if not isinstance(cwd, str) or not Path(cwd).is_absolute():
                return
            p = Path(cwd) / p
        candidates.add(p)

    for thread in data['threads']:
        cwd = thread.get('cwd')
        add(cwd)
        for change in thread['files']:
            add(change['path'], cwd)
        for tool in thread['tools']:
            if tool['tool'] != 'Bash':
                continue
            working = tool.get('cwd') or cwd
            add(working)
            try:
                words = shlex.split(shell_payload(tool['input']))
            except ValueError:
                # Keep the verified cwd/files; never interpret shell code.
                continue
            for i, word in enumerate(words):
                if word.startswith(('/', '~/', './', '../')) or (i and words[i-1] in ('cd', '-C')):
                    add(word, working)
    directories = set()
    for path in candidates:
        try:
            while not path.is_dir() and path != path.parent:
                path = path.parent
            directories.add(path)
        except OSError:
            continue
    repos = set()
    for directory in sorted(directories):
        try:
            result = subprocess.run(['git', '-C', str(directory), 'rev-parse', '--show-toplevel'],
                                    text=True, capture_output=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                repos.add(str(Path(result.stdout.strip()).resolve()))
        except (OSError, subprocess.SubprocessError):
            continue
    return sorted(repos)


def add_number_inventory(data):
    """Reconcile native command output, never messages or tool transport metadata."""
    repos = number_repos(data)
    rows = []
    for thread in data['threads']:
        for tool in thread['tools']:
            if tool['tool'] != 'Bash' or not isinstance(tool.get('output'), str):
                continue
            nums = output_numbers.result_numbers(tool['output'])
            if nums:
                rows.append({'thread': thread['id'], 'turn': tool['turn'], 'call': tool['id'],
                             'command': tool['input'], 'cwd': tool.get('cwd') or thread.get('cwd'),
                             'status': tool.get('status'), 'exit_code': tool.get('exit_code'), 'numbers': nums})
    # One record search per repo, even when many command outputs repeat a value.
    unique = list(dict.fromkeys(n for row in rows for n in row['numbers']))
    recorded = set(output_numbers.numbers_recorded(unique, repos))
    for row in rows:
        row['recorded'] = [n for n in row['numbers'] if n in recorded]
    data['number_repos'] = repos
    data['number_results'] = rows
    data['numbers_not_recorded'] = sum(len(r['recorded']) < len(r['numbers']) for r in rows)
    return data


def print_report(data, max_chars, section='all', call_id=None):
    def show(value):
        text = value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
        if max_chars and len(text) > max_chars:
            return text[:max_chars]+f'\n[truncated: {len(text)} chars; use --max-chars 0]'
        return text
    print('Codex wrap inventory:',data['root'])
    print('scope:',data['scope'])
    for thread in data['threads']:
        print(f"\n== {'parent' if thread['id']==data['root'] else 'spawned child'} {thread['id']} cwd={thread['cwd']} status={thread['status']}")
        for message in thread['messages'] if section in ('all','messages') else []:
            print(f"-- {message['role']} / {message.get('phase','')} / turn {message['turn']}")
            print(show(message['text']))
        summaries=thread.get('reasoning_summaries',[])
        if section in ('all','messages') or (section=='workers' and thread['id']!=data['root']):
            for summary in summaries:
                print('exposed reasoning summary / turn',summary['turn'],'/',summary['availability'])
                if summary['text']:print(show(summary['text']))
        if section=='summary':
            print('exposed reasoning summaries:',sum(x['availability']=='available' for x in summaries),
                  'not exposed/unreadable:',sum(x['availability']!='available' for x in summaries))
        for tool in thread['tools'] if section in ('all','commands') else []:
            if call_id and tool['id'] != call_id: continue
            print(f"-- tool {tool['tool']} / {tool.get('status')} / {tool['id']}")
            print(show(tool.get('input')))
            print('result:',show(tool.get('output')))
        if section in ('summary','workers'):
            print('visible messages:',len(thread['messages']),'tool calls:',len(thread['tools']))
        if section=='workers' and thread['id']!=data['root']:
            for message in thread['messages']:
                if message['role']=='assistant' and message.get('phase')!='commentary':
                    print('report / turn',message['turn'],show(message['text']))
        print('recorded file changes:',show(thread['files']))
        print('headless candidates:',show(thread['headless']))
        print('board/token/other-session routes:',show(thread['routes']))
        for warning in thread['warnings']:
            print('WARNING:',warning)
    if section in ('all','workers','summary'):
        print('worker hook observations:',show(data.get('worker_observations',[])))
        for report in data.get('claude_reports',[]):
            print('Claude observed report:',report['child'],report.get('agent'),report['source'])
            print(show(report['text']))
    for missing in data['unavailable']:
        print('UNAVAILABLE:',missing)
    if section in ('all', 'summary', 'commands'):
        print('数値の照合で探した repo:', ', '.join(data.get('number_repos', [])) or 'なし')
        lost = [r for r in data.get('number_results', []) if len(r['recorded']) < len(r['numbers'])
                and (not call_id or r['call'] == call_id)]
        if lost:
            print('🔢 探した記録と照合できなかった数値の候補:', len(lost), '件'
                  ' (規則と限界: scripts/lib/output_numbers.py)。'
                  ' 1 件ずつ記録するか、記録しない理由を確かめる:')
            for row in lost:
                missing = [n for n in row['numbers'] if n not in row['recorded']]
                print('  thread', row['thread'], 'call', row['call'], '/', row['status'],
                      'exit', row['exit_code'], '→', ', '.join(missing))
                print('   ', row['command'].splitlines()[0][:100])
    print('Other-session routes need their native reader; board/token state must be synchronized by the owning workflow.')


def selftest():
    from copy import deepcopy
    parent, child, foreign = 'parent-fixture','child-fixture','foreign-fixture'
    def thread(ident, parent_id, items):
        return {'id':ident,'parentThreadId':parent_id,'cwd':'/synthetic','status':{'type':'idle'},
                'turns':[{'id':'first','items':items}]}
    spawn={'type':'collabAgentToolCall','id':'spawn-one','senderThreadId':parent,'tool':'spawnAgent',
           'status':'completed','receiverThreadIds':[child],'prompt':'Task','agentsStates':{}}
    rows={parent:thread(parent,None,[{'type':'userMessage','id':'user','content':[{'type':'text','text':'Wrap fixture.'}]},
                                    {'type':'reasoning','id':'private','content':'NEVER_EXPORT_PRIVATE_REASONING'},spawn,
                                    {'type':'commandExecution','id':'shell','command':'claude -p task; codex exec task',
                                     'cwd':'/synthetic','status':'completed','aggregatedOutput':'fixture output','exitCode':0},
                                    {'type':'commandExecution','id':'mention','command':"echo 'try codex exec task'",'status':'completed'},
                                    {'type':'commandExecution','id':'board','command':'python3 /fixture/board.py claim --session role-fixture --request fixture', 'status':'completed'},
                                    {'type':'mcpToolCall','id':'other','tool':'create_thread','arguments':{'prompt':'fixture'},'result':{},'status':'completed'}]),
          child:thread(child,parent,[{'type':'agentMessage','id':'report-one','text':'discarded / noticed / unverified','phase':'final'},
                                     {'type':'fileChange','id':'edit','status':'completed','changes':[{'path':'/synthetic/report.md','kind':{'type':'add'}}]}]),
          foreign:thread(foreign,None,[{'type':'agentMessage','id':'unrelated','text':'UNRELATED_BODY','phase':'final'}])}
    rows[child]['turns'].append({'id':'resumed','items':[{'type':'agentMessage','id':'report-two','text':'second report','phase':'final'}]})
    called=[]
    def read(ident):
        called.append(ident)
        return rows[ident]
    result=collect(parent,read)
    assert called==[parent,child]
    assert len(result['threads'][1]['messages'])==2 and result['threads'][1]['files'][0]['path'].endswith('report.md')
    text=json.dumps(result)
    assert 'NEVER_EXPORT' not in text and 'UNRELATED_BODY' not in text
    assert [x['evidence'] for x in result['threads'][0]['headless']]==['executable_position','executable_position','text_only']
    assert [x['route'] for x in result['threads'][0]['routes']]==['board','other_session']
    print('OK: own messages, actual commands/results, all resumed reports, file paths and explicit handoff routes')
    controls=thread(parent,None,[
        {'type':'sleep','id':'wait-passive','durationMs':30000},
        {'type':'mcpToolCall','id':'archive','tool':'set_thread_archived','arguments':{'threadId':child},'status':'completed'},
        {'type':'mcpToolCall','id':'archive-qualified','tool':'mcp__codex_app__set_thread_archived','arguments':{},'status':'completed'},
        {'type':'dynamicToolCall','id':'wait','tool':'wait_threads','arguments':{},'status':'completed'},
        {'type':'mcpToolCall','id':'unknown','tool':'spawn_unknown_thread','arguments':{},'status':'completed'},
        {'type':'mcpToolCall','id':'create','tool':'create_thread','arguments':{},'status':'completed'}])
    managed=summarize(controls)
    assert managed['warnings']==['unclassified delegation tool: spawn_unknown_thread']
    assert len(managed['tools'])==5 and [x['tool'] for x in managed['routes']]==['create_thread']
    print('OK: known thread management retains tool evidence without false delegation warnings; unknown delegation remains visible')

    changed=deepcopy(rows)
    changed[child]['parentThreadId']=foreign
    assert collect(parent,changed.__getitem__)['unavailable'][0]['reason'].startswith('parent identity mismatch')
    def absent(ident):
        if ident==child: raise RuntimeError('unavailable')
        return rows[ident]
    assert collect(parent,absent)['unavailable']
    changed[parent]['turns'][0]['items'].append({'type':'newUnknownTool','id':'new'})
    assert summarize(changed[parent])['warnings']
    assert command_routes("echo 'python3 board.py claim'")[0]==[]
    assert command_routes("/bin/zsh -lc 'python3 /fixture/board.py claim --session role-fixture'")[0][0]['route']=='board'
    assert command_routes("/bin/bash -lc 'claude -p task'")[1][0]['evidence']=='executable_position'
    assert command_routes('if true; then codex exec task; fi')[2]
    assert len(collect(parent,rows.__getitem__,max_threads=1)['unavailable'])==1
    print('OK: unrelated child bodies, unavailable history, unknown formats and limits remain explicit')
    hosted=deepcopy(rows)
    hosted[parent]['turns'][0]['items']=[{'type':'subAgentActivity','id':'hosted-start','kind':'started','agentPath':'/root/fixture','agentThreadId':child}]
    assert len(collect(parent,hosted.__getitem__)['threads'])==2
    print('OK: hosted subagent activity links use the actual agent thread ID')
    summary_items=[{'type':'reasoning','id':'visible','summary':['Visible decision summary.'],
                    'content':['PRIVATE_RAW_SENTINEL'],'encrypted_content':'PRIVATE_ENCRYPTED_SENTINEL'},
                   {'type':'reasoning','id':'missing','content':['PRIVATE_RAW_SENTINEL']},
                   {'type':'reasoning','id':'malformed','summary':{'unknown':'PRIVATE_UNKNOWN_SENTINEL'}}]
    view=summarize(thread(parent,None,summary_items))
    assert [x['availability'] for x in view['reasoning_summaries']]==['available','not_exposed','unreadable']
    assert view['reasoning_summaries'][0]['text']=='Visible decision summary.'
    assert view['warnings'] and 'PRIVATE_' not in json.dumps(view)
    print('OK: exposed summaries collected; missing/malformed explicit; raw and encrypted reasoning excluded')
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        fake=Path(tmp)/'codex'
        fake.write_text('#!/bin/sh\necho "Error: failed to initialize sqlite state runtime under /synthetic/.codex" >&2\nexit 1\n')
        fake.chmod(0o755)
        message=''
        try:
            with Reader(str(fake),timeout=10):
                pass
        except RuntimeError as exc:
            message=str(exc)
        assert 'failed to initialize sqlite state runtime' in message, message
        assert 'outside the Codex sandbox' in message, message
    print('OK: an app-server that exits at start reports its stderr and the sandbox remedy')

    # Use the real CLI on synthetic thread/read records. These repositories are
    # outside the source tree so fixture literals cannot satisfy their own search.
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        repo, changed_repo, command_repo, unrelated = [base / name for name in
            ('working repo', 'changed', 'command', 'unrelated')]
        for directory, number in ((repo, '0.2394'), (changed_repo, '0.8842'),
                                  (command_repo, '0.7136'), (unrelated, '0.5615')):
            directory.mkdir()
            subprocess.run(['git', 'init', '-q', str(directory)], check=True)
            (directory / 'note.md').write_text(number + '\n', encoding='utf-8')
            subprocess.run(['git', '-C', str(directory), 'add', 'note.md'], check=True)
        fixture_thread = thread(parent, None, [
            {'type': 'agentMessage', 'id': 'prose', 'text': '0.9898', 'phase': 'final'},
            {'type': 'commandExecution', 'id': 'numbers', 'command': 'python3 calc.py',
             'cwd': str(repo), 'status': 'completed', 'exitCode': 0,
             'aggregatedOutput': '0.23940 0.5615 0.88420 0.71360'},
            {'type': 'fileChange', 'id': 'change', 'status': 'completed',
             'changes': [{'path': 'changed/note.md', 'kind': {'type': 'update'}}]},
            {'type': 'commandExecution', 'id': 'command-path',
             'command': 'python3 ' + shlex.quote(str(command_repo / 'calc.py')),
             'cwd': str(base), 'status': 'completed', 'aggregatedOutput': 'no numeric result'},
            {'type': 'commandExecution', 'id': 'no-output', 'command': 'echo 0.9898',
             'status': 'inProgress', 'aggregatedOutput': None}])
        fixture_thread['cwd'] = str(base)
        fixture = base / 'thread.json'
        fixture.write_text(json.dumps({parent: fixture_thread}), encoding='utf-8')
        cli = [sys.executable, str(Path(__file__).resolve()), parent, '--fixture', str(fixture),
               '--record-dir', str(base / 'observations')]
        rendered = subprocess.run(cli, capture_output=True, text=True, check=True).stdout
        inventory = json.loads(subprocess.run(cli + ['--json'], capture_output=True, text=True, check=True).stdout)
        assert '🔢' in rendered and '→ 0.5615' in rendered, rendered
        assert inventory['numbers_not_recorded'] == 1
        assert inventory['number_repos'] == sorted(str(p.resolve()) for p in (repo, changed_repo, command_repo))
        assert inventory['number_results'][0]['recorded'] == ['0.23940', '0.88420', '0.71360']
        assert '0.9898' not in str(inventory['number_results'])
        assert len(inventory['number_results']) == 1
        assert number_repos({'threads': [summarize(thread(parent, None, []))]}) == []
        print('OK: Codex fixture CLI emits 🔢 and JSON count without blocking; cwd/change/command paths only; prose, absent output and unrelated repo excluded')

    return 0


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('session',nargs='?',help='explicit full SessionStart ID; inherited environment IDs may name an ancestor')
    ap.add_argument('--codex',default='auto')
    ap.add_argument('--fixture',type=Path,help='synthetic thread/read response map; no app-server connection')
    ap.add_argument('--max-chars',type=int,default=2000)
    ap.add_argument('--max-threads',type=int,default=128)
    ap.add_argument('--section',choices=('all','summary','messages','commands','workers'),default='summary')
    ap.add_argument('--call-id',help='show one recorded tool call with --section commands')
    ap.add_argument('--record-dir',type=Path,help='worker observation directory (isolated fixtures may override it)')
    ap.add_argument('--mark-collected',metavar='DURABLE_REFERENCE',help='acknowledge this parent observation set after reviewing and recording it')
    ap.add_argument('--prune-collected',action='store_true')
    ap.add_argument('--json',action='store_true')
    ap.add_argument('--selftest',action='store_true')
    args=ap.parse_args()
    if args.selftest:return selftest()
    if args.prune_collected:
        print('removed collected observations:',observations.prune_collected(args.record_dir))
        return 0
    if not args.session:ap.error('full session ID is required (from SessionStart)')
    if args.max_chars<0 or args.max_threads<1:ap.error('invalid output/thread limit')
    try:
        if args.mark_collected:
            observations.mark_collected(args.session,args.mark_collected,args.record_dir)
            print('collected observation set:',args.session)
            return 0
        if args.fixture:
            fixture=json.loads(args.fixture.read_text(encoding='utf-8'))
            def read(ident):
                if ident not in fixture:raise RuntimeError('fixture thread unavailable')
                return fixture[ident].get('thread',fixture[ident])
            data=add_observed_workers(collect(args.session,read,args.max_threads),read,args.record_dir,args.max_threads)
        else:
            with Reader(args.codex) as reader:
                data=add_observed_workers(collect(args.session,reader.thread,args.max_threads),reader.thread,args.record_dir,args.max_threads)
        add_number_inventory(data)
        if args.json:print(json.dumps(data,ensure_ascii=False,indent=2))
        else:print_report(data,args.max_chars,args.section,args.call_id)
        return 2 if data['unavailable'] or any(t['warnings'] for t in data['threads']) else 0
    except (OSError,ValueError,RuntimeError,TimeoutError,KeyError,TypeError) as exc:
        print('UNAVAILABLE: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
