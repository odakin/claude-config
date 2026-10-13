#!/usr/bin/env python3
"""headless_record_clause.py — 共通のheadless記録条項runner・shell解析・実行記録。--selftest。

# agent-authority:file

Literal simple commands only: quote-aware word spans distinguish executable
positions from arguments, comments, substitutions and heredoc data. Insert a
runner before the executable; preserve every original shell byte. The runner
receives expanded argv and uses the shared worker_record_clause.py text.
Claude: append to --append-system-prompt (preserving an existing text/file).
Codex exec: append to the prompt argument, or stream a footer after stdin when
the prompt comes from stdin. Config, environment, cwd, redirections and exit
status remain with the original command. Permission decisions stay with the
normal tool policy; hook/parser/preparation failures are non-blocking.

Observation: the parent transcript retains the original command, not updatedInput.
When session_id and tool_use_id are supplied, record selected/applied/failed phases
in the parent config's state/headless-record-clause directory. Bind each attempt
to parent session, tool call, original-command SHA-256 and launch index. The runner
records argv preparation or stdin delivery, not model receipt/compliance. Failure
records win over a delayed stdin success. Original prompt/command text is omitted;
files are mode 0600 in private directories. Metadata also records actual cwd/config
and an explicitly provided Claude session ID for precise transcript lookup.
Recording failure never prevents injection. These local records are not a security
boundary or an authenticated audit log; missing records remain unverified.
New records also bind the parent transcript path. The report reader prunes records
older than 30 days only after that transcript is gone (and no same-session copy is
found in its searched projects directories). Age alone never expires a readable
parent's evidence. Legacy records lacking that path, corrupt records and symlinks
are retained. Cleanup runs with the reader, outside the latency-sensitive hook.

Scope: POSIX Bash simple command lists/pipelines/subshells, literal executable
names/paths, assignment/env/command/exec prefixes. Unsupported shell grammar,
shell -c, substitutions, computed commands, aliases/functions, script contents
and scheduler launches are not inspected. Codex exec subcommands and image
options are not rewritten. A Claude resume can retain a previously snapshotted
system prompt; insertion is not evidence the resumed model received it. This
is an advisory instruction, not a guarantee of worker compliance.

Usage: hook stdin JSON; --run <claude|codex> ... for explicit wrapper use;
       --selftest [--against OLD_HOOK] runs synthetic shell/worker fixtures.
End-to-end receipt regression: scripts/headless-worker-reports.py --selftest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import time
import uuid

MARKER = '記録の約束'
ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*=')
CONTROL = {'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do',
           'done', 'case', 'esac', 'select', 'function', 'coproc', 'time',
           '{', '}', '[[', ']]', '!'}
REDIRECT = re.compile(r'(?:[0-9]+)?(?:<<-|<<<|<<|>>|>&|<&|<>|>\||>|<)|&>>?')
CLAUDE_VALUES = {
    '--append-system-prompt', '--append-system-prompt-file', '--system-prompt',
    '--system-prompt-file', '--model', '--effort', '--settings', '--agents',
    '--agent', '--input-format', '--output-format', '--json-schema',
    '--permission-mode', '--permission-prompts', '--session-id', '--name', '-n',
    '--max-turns', '--max-budget-usd', '--setting-sources', '--debug-file',
    '--fallback-model', '--system-prompt-snapshot', '--plugin-dir', '--plugin-url',
}
CLAUDE_VARIADIC = {'--add-dir', '--allowedTools', '--allowed-tools', '--disallowedTools',
                   '--disallowed-tools', '--mcp-config', '--tools', '--file', '--betas'}
CLAUDE_OPTIONAL = {'--resume', '-r', '--from-pr', '--worktree', '-w', '--debug', '-d',
                   '--teleport', '--remote-control', '--cloud', '--prompt-suggestions'}
CLAUDE_FLAGS = {'-p', '--print', '-c', '--continue', '--bare', '--no-session-persistence',
                '--verbose', '--strict-mcp-config', '--chrome', '--no-chrome',
                '--include-hook-events', '--include-partial-messages', '--disable-slash-commands',
                '--allow-dangerously-skip-permissions', '--dangerously-skip-permissions',
                '--fork-session', '--replay-user-messages', '--forward-subagent-text',
                '--ide', '--safe-mode', '--restricted', '--bg', '--background', '--brief',
                '--ax-screen-reader', '--exclude-dynamic-system-prompt-sections',
                '-h', '--help', '-v', '--version'}
CODEX_VALUES = {'-c', '--config', '-m', '--model', '-p', '--profile', '-s',
                '--sandbox', '-C', '--cd', '--add-dir', '--enable', '--disable',
                '--local-provider', '--thread-source', '--output-schema',
                '--color', '-o', '--output-last-message', '-a', '--ask-for-approval'}
CODEX_FLAGS = {'--json', '--experimental-json', '--ephemeral', '--ignore-user-config',
               '--ignore-rules', '--skip-git-repo-check', '--strict-config', '--oss',
               '--approve-for-me', '--dangerously-bypass-approvals-and-sandbox',
               '--dangerously-bypass-hook-trust', '--full-auto', '--search',
               '--no-alt-screen'}
CONTEXT_KEYS = {'version', 'root', 'session_id', 'tool_use_id', 'command_sha256',
                'launch_index', 'kind', 'issued_ns', 'attempt'}
OPTIONAL_CONTEXT_KEYS = {'parent_transcript'}
RECEIPT_RETENTION_NS = 30 * 24 * 60 * 60 * 1_000_000_000
RECEIPT_STATES = {'selected', 'added', 'present', 'empty', 'unsupported',
                  'prepare_failed', 'exec_failed', 'stdin_failed', 'stdin_unconsumed'}
FAILURE_STATES = {'unsupported', 'prepare_failed', 'exec_failed', 'stdin_failed', 'stdin_unconsumed'}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def receipt_root(transcript: str | Path | None = None) -> Path:
    if transcript:
        path = Path(transcript).expanduser().resolve()
        if path.parent.parent.name == 'projects':
            return path.parent.parent.parent / 'state' / 'headless-record-clause'
    cfg = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').expanduser()
    return cfg.resolve() / 'state' / 'headless-record-clause'


def valid_context(ctx) -> bool:
    return (isinstance(ctx, dict) and CONTEXT_KEYS <= set(ctx) <= CONTEXT_KEYS | OPTIONAL_CONTEXT_KEYS and ctx['version'] == 1
            and ('parent_transcript' not in ctx or
                 (isinstance(ctx['parent_transcript'], str) and
                  Path(ctx['parent_transcript']).is_absolute() and
                  Path(ctx['parent_transcript']).suffix == '.jsonl'))
            and all(isinstance(ctx[k], str) and 0 < len(ctx[k]) <= 4096
                    for k in ('root', 'session_id', 'tool_use_id', 'command_sha256', 'kind', 'attempt'))
            and Path(ctx['root']).is_absolute() and ctx['kind'] in ('claude', 'codex')
            and re.fullmatch(r'[0-9a-f]{64}', ctx['command_sha256']) is not None
            and re.fullmatch(r'[0-9a-f]{32}', ctx['attempt']) is not None
            and type(ctx['launch_index']) is int and ctx['launch_index'] >= 0
            and type(ctx['issued_ns']) is int and ctx['issued_ns'] > 0)


def record_receipt(ctx, state: str, worker=None) -> None:
    """Atomic, private metadata only. A failure event cannot race away an applied event.

    Each attempt has separate selected/applied/failed files; the reader gives
    failure priority and chooses the latest issued attempt per launch position.
    Neither command nor prompt text is stored. Recording errors never block.
    """
    if ctx is None:
        return
    temporary = None
    try:
        if not valid_context(ctx) or state not in RECEIPT_STATES:
            raise ValueError('invalid receipt context')
        root = Path(ctx['root'])
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent = root / digest(ctx['session_id'])
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        call = digest(ctx['tool_use_id'] + '\0' + ctx['command_sha256'])
        phase = 'failed' if state in FAILURE_STATES else 'selected' if state == 'selected' else 'applied'
        dest = parent / f"{call}-{ctx['launch_index']}-{ctx['attempt']}-{phase}.json"
        row = dict(ctx, state=state, recorded_at=datetime.now(timezone.utc).isoformat())
        if worker:
            row['worker'] = worker
        fd, temporary = tempfile.mkstemp(prefix='.', dir=parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(row, stream, ensure_ascii=False)
            stream.write('\n')
        os.replace(temporary, dest)
        temporary = None
    except Exception as exc:
        warn('注入記録を書けません (' + type(exc).__name__ + ')。起動は続行します。')
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def read_receipts(root: Path, session: str, tool_id: str, command: str) -> list[dict]:
    """Read only the exact parent/session/tool/command key, never nearby sessions."""
    if not session or not tool_id:
        return []
    command_hash = digest(command)
    call = digest(tool_id + '\0' + command_hash)
    attempts = {}
    for path in (root / digest(session)).glob(call + '-*.json'):
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            ctx = {k: row[k] for k in CONTEXT_KEYS | OPTIONAL_CONTEXT_KEYS if k in row}
            if not valid_context(ctx) or row.get('state') not in RECEIPT_STATES:
                raise ValueError('invalid receipt')
            worker = row.get('worker', {})
            if not isinstance(worker, dict) or set(worker) - {'cwd', 'config_dir', 'session_id', 'resume'}:
                raise ValueError('invalid worker metadata')
            if any(not isinstance(worker[k], str) or not Path(worker[k]).is_absolute()
                   for k in ('cwd', 'config_dir') if k in worker):
                raise ValueError('invalid worker path')
            if (ctx['session_id'], ctx['tool_use_id'], ctx['command_sha256']) != (session, tool_id, command_hash):
                continue
            if Path(ctx['root']).resolve() != root.resolve():
                continue
            key = ctx['launch_index'], ctx['attempt']
            priority = 2 if row['state'] in FAILURE_STATES else 0 if row['state'] == 'selected' else 1
            if key not in attempts or priority > attempts[key][0]:
                attempts[key] = priority, row
        except (OSError, ValueError, KeyError, TypeError):
            return [{'state': 'unreadable', 'launch_index': 0}]
    latest = {}
    for _, row in attempts.values():
        i = row['launch_index']
        if i not in latest or row['issued_ns'] > latest[i]['issued_ns']:
            latest[i] = row
    return [latest[i] for i in sorted(latest)]


def receipt_context(ev: dict, command: str, index: int, kind: str):
    if not all(isinstance(ev.get(k), str) and ev[k] for k in ('session_id', 'tool_use_id')):
        return None
    ctx = dict(version=1, root=str(receipt_root(ev.get('transcript_path'))),
                session_id=ev['session_id'], tool_use_id=ev['tool_use_id'],
                command_sha256=digest(command), launch_index=index, kind=kind,
                issued_ns=time.time_ns(), attempt=uuid.uuid4().hex)
    path = ev.get('transcript_path')
    if isinstance(path, str) and Path(path).suffix == '.jsonl':
        ctx['parent_transcript'] = str(Path(path).expanduser().resolve())
    return ctx


def prune_receipts(root: Path, projects=(), now_ns=None) -> dict:
    """Remove only old, valid orphan files; never read or delete parent transcripts.

    Check both issue time and last write time: a long-running worker can write a
    fresh phase for an old attempt. Unknown provenance and filesystem errors keep
    evidence. Per-file unlink plus a stat recheck preserves new concurrent writes;
    nonempty directories are never recursively removed.
    """
    result = {'removed': 0, 'retained': 0, 'errors': 0}
    cutoff = (time.time_ns() if now_ns is None else now_ns) - RECEIPT_RETENTION_NS
    root = Path(root)
    if root.is_symlink():
        return result
    try:
        parents = list(root.iterdir())
    except FileNotFoundError:
        return result
    except OSError:
        result['errors'] += 1
        return result
    search = list(dict.fromkeys([root.parent.parent / 'projects', *map(Path, projects)]))
    transcript_names = set()
    try:
        for directory in search:
            try:
                with os.scandir(directory) as entries:
                    children = [Path(p.path) for p in entries if p.is_dir()]
            except FileNotFoundError:
                continue
            for child in children:
                with os.scandir(child) as entries:
                    transcript_names.update(p.name for p in entries if p.name.endswith('.jsonl'))
    except OSError:
        result['errors'] += 1
        return result  # An unreadable search location is not proof of absence.
    for parent in parents:
        if parent.is_symlink() or not re.fullmatch(r'[0-9a-f]{64}', parent.name) or not parent.is_dir():
            continue
        try:
            paths = list(parent.iterdir())
        except OSError:
            result['errors'] += 1
            continue
        for path in paths:
            try:
                stat = path.lstat()
                if path.is_symlink() or not path.is_file() or stat.st_mtime_ns >= cutoff:
                    result['retained'] += 1
                    continue
                row = json.loads(path.read_text(encoding='utf-8'))
                ctx = {k: row[k] for k in CONTEXT_KEYS | OPTIONAL_CONTEXT_KEYS if k in row}
                if not valid_context(ctx) or 'parent_transcript' not in ctx or row.get('state') not in RECEIPT_STATES:
                    result['retained'] += 1
                    continue
                phase = 'failed' if row['state'] in FAILURE_STATES else 'selected' if row['state'] == 'selected' else 'applied'
                call = digest(ctx['tool_use_id'] + '\0' + ctx['command_sha256'])
                expected = f"{call}-{ctx['launch_index']}-{ctx['attempt']}-{phase}.json"
                if (path.name != expected or parent.name != digest(ctx['session_id']) or
                        Path(ctx['root']).resolve() != root.resolve() or ctx['issued_ns'] >= cutoff):
                    result['retained'] += 1
                    continue
                transcript = Path(ctx['parent_transcript'])
                try:
                    transcript.stat()
                    exists = True
                except FileNotFoundError:
                    # Use filename equality, not a glob containing a session ID.
                    names = {transcript.name, ctx['session_id'] + '.jsonl'}
                    exists = bool(names & transcript_names)
                current = path.lstat()
                unchanged = (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) == (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)
                if exists or not unchanged:
                    result['retained'] += 1
                    continue
                path.unlink()
                result['removed'] += 1
            except (OSError, ValueError, TypeError, KeyError):
                result['errors'] += 1
        try:
            parent.rmdir()  # Only empty receipt directories, never their contents.
        except OSError:
            pass
    return result


def worker_metadata(args: list[str], kind: str | None) -> dict:
    result = {'cwd': str(Path.cwd()), 'config_dir': str(Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home()/'.claude').expanduser().resolve())}
    if kind == 'claude':
        options = list(claude_option_indices(args))
        result['resume'] = any(key in ('--resume', '-r', '--continue', '-c') for _, key in options)
        for i, key in options:
            if key == '--session-id':
                value = args[i].partition('=')[2] if '=' in args[i] else args[i+1]
                if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value):
                    result['session_id'] = value
    return result


@dataclass
class Word:
    raw: str
    start: int
    end: int
    value: str | None


def quoted_end(text: str, i: int, quote: str) -> int:
    """Consume a quote without executing its contents, including nested $()."""
    i += 1
    while i < len(text):
        if text[i] == '\\' and quote != "'":
            i += 2
        elif text[i] == quote:
            return i + 1
        elif quote == '"' and text.startswith(('$(', '${'), i):
            i = expansion_end(text, i + 1)
        elif quote == '"' and text[i] == '`':
            i = quoted_end(text, i, '`')
        else:
            i += 1
    raise ValueError('unclosed quote')


def expansion_end(text: str, i: int) -> int:
    """Consume a balanced expansion as opaque data; nested heredocs are unsupported."""
    opening = text[i]
    closing = ')' if opening == '(' else '}'
    depth = 1
    i += 1
    while i < len(text):
        if text.startswith('<<', i):
            raise ValueError('heredoc within expansion')
        if text[i] == '\\':
            i += 2
        elif text[i] in "'\"`":
            i = quoted_end(text, i, text[i])
        elif text.startswith(('$(', '${'), i):
            i = expansion_end(text, i + 1)
        elif text[i] == opening:
            depth += 1
            i += 1
        elif text[i] == closing:
            depth -= 1
            i += 1
            if depth == 0:
                return i
        else:
            i += 1
    raise ValueError('unclosed expansion')


def read_word(text: str, start: int) -> Word:
    i = start
    while i < len(text):
        ch = text[i]
        if text.startswith(('$(', '${', '<(', '>('), i):
            i = expansion_end(text, i + 1)
        elif text.startswith("$'", i):
            # ANSI-C quotes permit escaped single quotes; keep their contents opaque.
            i += 2
            while i < len(text) and text[i] != "'":
                i += 2 if text[i] == '\\' else 1
            if i == len(text):
                raise ValueError('unclosed ANSI-C quote')
            i += 1
        elif ch in "'\"`":
            i = quoted_end(text, i, ch)
        elif ch == '\\':
            if i + 1 == len(text):
                raise ValueError('trailing escape')
            i += 2
        elif ch.isspace() or ch in ';&|()<>':
            break
        else:
            i += 1
    raw = text[start:i]
    if not raw:
        raise ValueError('empty word')
    if any(x in raw for x in ('$', '`', '<(', '>(')):
        value = None
    else:
        logical, quote, j = [], None, 0
        while j < len(raw):
            ch = raw[j]
            if ch == '\\' and quote != "'" and j + 1 < len(raw):
                if raw[j + 1] != '\n':
                    logical.append(raw[j:j + 2])
                j += 2
                continue
            if ch in "'\"" and (quote is None or quote == ch):
                quote = ch if quote is None else None
            logical.append(ch)
            j += 1
        parts = shlex.split(''.join(logical), comments=False, posix=True)
        if len(parts) != 1:
            raise ValueError('nonliteral word')
        value = parts[0]
    return Word(raw, start, i, value)


def shell_commands(text: str) -> list[list[Word]]:
    """Conservative simple-command lexer. Never return a partial parse."""
    commands, current, docs = [], [], []
    i = groups = 0

    def finish():
        if current:
            if current[0].value in CONTROL:
                raise ValueError('compound shell command')
            commands.append(current[:])
            current.clear()

    while i < len(text):
        ch = text[i]
        if text.startswith('\\\n', i):
            i += 2
        elif ch in ' \t\r':
            i += 1
        elif ch == '#':
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
        elif ch == '\n':
            finish()
            i += 1
            for delimiter, strip_tabs in docs:
                found = False
                while i < len(text):
                    end = text.find('\n', i)
                    end = len(text) if end < 0 else end
                    line = text[i:end]
                    i = min(end + 1, len(text))
                    if (line.lstrip('\t') if strip_tabs else line) == delimiter:
                        found = True
                        break
                if not found:
                    raise ValueError('unclosed heredoc')
            docs.clear()
        elif text.startswith(('<(', '>('), i):
            word = read_word(text, i)
            current.append(word)
            i = word.end
        elif (match := REDIRECT.match(text, i)) is not None:
            operator = match.group()
            i = match.end()
            while i < len(text) and text[i] in ' \t':
                i += 1
            target = read_word(text, i)
            i = target.end
            if operator.lstrip('0123456789') in ('<<', '<<-'):
                if target.value is None:
                    raise ValueError('nonliteral heredoc delimiter')
                docs.append((target.value, operator.endswith('-')))
        elif ch in ';&|':
            finish()
            i += 1
        elif ch == '(':
            if current:
                raise ValueError('function or unsupported parentheses')
            groups += 1
            i += 1
        elif ch == ')':
            finish()
            groups -= 1
            if groups < 0:
                raise ValueError('unmatched parentheses')
            i += 1
        else:
            word = read_word(text, i)
            current.append(word)
            i = word.end
    finish()
    if docs or groups:
        raise ValueError('incomplete shell command')
    return commands


def executable_index(words: list[Word]) -> int | None:
    i = 0
    while i < len(words):
        if ASSIGNMENT.match(words[i].raw):
            i += 1
            continue
        name = words[i].value
        if name is None:
            return None
        if name in ('command', 'exec'):
            i += 1
            if i < len(words) and words[i].value == '--':
                i += 1
            elif i < len(words) and (words[i].value or '').startswith('-'):
                return None
        elif Path(name).name == 'env':
            i += 1
            while i < len(words):
                value = words[i].value or ''
                if value == '--':
                    i += 1
                    break
                if ASSIGNMENT.match(words[i].raw) or value in ('-i', '--ignore-environment'):
                    i += 1
                elif value in ('-u', '--unset', '-C', '--chdir'):
                    i += 2
                elif value.startswith(('--unset=', '--chdir=')):
                    i += 1
                elif value.startswith('-'):
                    return None
                else:
                    break
        else:
            return i
    return None


def claude_option_indices(args: list[str | None]):
    i = 1
    while i < len(args):
        arg = args[i] or ''
        if arg == '--':
            return
        key = arg.partition('=')[0]
        yield i, key
        i += 1
        if '=' in arg:
            continue
        if key in CLAUDE_VALUES:
            i += 1
        elif key in CLAUDE_OPTIONAL and i < len(args) and not (args[i] or '').startswith('-'):
            i += 1
        elif key in CLAUDE_VARIADIC:
            while i < len(args) and not (args[i] or '').startswith('-'):
                i += 1


def codex_prompt_index(args: list[str | None]) -> int | None:
    """Return prompt position, len(argv) for stdin, or None for unsupported argv."""
    i, command_seen, prompt = 1, False, None
    while i < len(args):
        arg = args[i]
        if arg is None:
            # A dynamic positional prompt is fine; dynamic options are not inferred.
            if not command_seen or prompt is not None:
                return None
            prompt = i
            i += 1
            continue
        if arg == '--':
            if not command_seen or prompt is not None or i + 2 != len(args):
                return None
            return i + 1
        key = arg.partition('=')[0]
        if key in CODEX_VALUES:
            if '=' not in arg:
                if i + 1 == len(args):
                    return None
                i += 1
        elif arg.startswith(('-c', '-m', '-p', '-s', '-C', '-o')) and not arg.startswith('--') and len(arg) > 2:
            pass
        elif arg in CODEX_FLAGS:
            pass
        elif arg.startswith('-') and arg != '-':
            return None
        elif not command_seen:
            if arg not in ('exec', 'e'):
                return None
            command_seen = True
        elif prompt is not None or arg in ('resume', 'fork', 'review', 'help'):
            return None
        else:
            prompt = i
        i += 1
    return (len(args) if prompt is None else prompt) if command_seen else None


def worker_kind(args: list[str | None]) -> str | None:
    if not args or args[0] is None:
        return None
    name = Path(args[0]).name
    if name == 'claude':
        options = [key for _, key in claude_option_indices(args)]
        if not any(x in options for x in ('--help', '-h', '--version', '-v')) and any(x in options for x in ('-p', '--print')):
            return 'claude'
    if name == 'codex' and codex_prompt_index(args) is not None:
        return 'codex'
    return None


def rewrite(ev: dict) -> dict | None:
    if ev.get('hook_event_name', 'PreToolUse') != 'PreToolUse' or ev.get('tool_name') != 'Bash':
        return None
    inp = ev.get('tool_input')
    if not isinstance(inp, dict) or not isinstance(inp.get('command'), str):
        return None
    command = inp['command']
    positions = []
    for words in shell_commands(command):
        i = executable_index(words)
        kind = worker_kind([w.value for w in words[i:]]) if i is not None else None
        if kind:
            positions.append((words[i].start, kind))
    if not positions:
        return None
    for index in reversed(range(len(positions))):
        pos, kind = positions[index]
        ctx = receipt_context(ev, inp['command'], index, kind)
        prefix = shlex.quote(sys.executable) + ' ' + shlex.quote(str(Path(__file__).resolve()))
        if ctx:
            token = json.dumps(ctx, ensure_ascii=False, separators=(',', ':'))
            prefix += ' --receipt-context ' + shlex.quote(token)
            record_receipt(ctx, 'selected')
        prefix += ' --run '
        command = command[:pos] + prefix + command[pos:]
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                  'updatedInput': dict(inp, command=command)}}


def warn(message: str) -> None:
    try:
        if sys.stderr is not None:
            print('headless-record-clause-nudge: ' + message, file=sys.stderr)
    except Exception:
        pass


def claude_args(args: list[str], clause: str) -> list[str]:
    out = list(args)
    options = list(claude_option_indices(args))
    # A literal positional prompt can already carry the user's own record clause.
    known = CLAUDE_VALUES | CLAUDE_VARIADIC | CLAUDE_OPTIONAL | CLAUDE_FLAGS
    unambiguous = all(not key.startswith('-') or key in known for _, key in options)
    if unambiguous and any(MARKER in args[i] for i, key in options if key and not key.startswith('-')):
        return args
    if '--' in args and any(MARKER in arg for arg in args[args.index('--') + 1:]):
        return args
    appends = [(i, key) for i, key in options if key in ('--append-system-prompt', '--append-system-prompt-file')]
    if len({key for _, key in appends}) > 1:
        raise ValueError('conflicting append options')
    if appends:
        i, key = appends[-1]  # CLI's last value wins; preserve earlier arguments.
        inline = '=' in args[i]
        old = args[i].partition('=')[2] if inline else args[i + 1]
        if key.endswith('-file'):
            old = Path(old).read_text(encoding='utf-8')
        if MARKER in old:
            return args
        replacement = ['--append-system-prompt', old + clause]
        out[i:i + (1 if inline else 2)] = replacement
    else:
        out[1:1] = ['--append-system-prompt', clause.lstrip()]
    if any(key in ('--resume', '-r', '--continue', '-c') for _, key in options):
        warn('resume の system prompt snapshot は追加条項を保持しない場合があります。worker の受領を確認してください。')
    return out


def append_stdin(clause: str, ctx=None, worker=None) -> None:
    """POSIX pipe relay: stream original input unchanged, then append the clause.

    Allocate/fork before changing fd 0, so preparation failures leave stdin
    untouched. The runner execs the worker (same process and exit status);
    the small relay exits on EOF or a closed reader. No prompt file is persisted.
    """
    if os.isatty(0):
        raise ValueError('interactive stdin')
    os.fstat(0)  # A closed stdin must not be reused as one of the pipe descriptors.
    read_fd, write_fd = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        os.close(read_fd)
        os.close(write_fd)
        raise
    if pid == 0:
        # Let init reap the relay; do not leave a zombie in a long-running worker.
        try:
            relay = os.fork()
        except OSError:
            os._exit(1)
        if relay:
            os._exit(0)
        try:
            os.close(read_fd)
            marker = MARKER.encode('utf-8')
            tail = b''
            found = False
            has_content = False
            with os.fdopen(write_fd, 'wb', buffering=0) as output:
                while True:
                    data = os.read(0, 65536)
                    if not data:
                        break
                    found = found or marker in tail + data
                    has_content = has_content or bool(data.strip())
                    tail = data[-len(marker):]
                    view = memoryview(data)
                    while view:
                        view = view[output.write(view):]
                if has_content and not found:
                    view = memoryview(clause.encode('utf-8'))
                    while view:
                        view = view[output.write(view):]
                # Write the receipt before EOF reaches a full-input reader.
                record_receipt(ctx, 'present' if found else 'added' if has_content else 'empty', worker)
        except BrokenPipeError:
            record_receipt(ctx, 'stdin_unconsumed', worker)
        except Exception:
            record_receipt(ctx, 'stdin_failed', worker)
            warn('stdin の追加処理に失敗しました。worker の受領を確認してください。')
        finally:
            os._exit(0)
    os.close(write_fd)
    _, status = os.waitpid(pid, 0)
    if status:
        os.close(read_fd)
        raise OSError('relay preparation failed')
    try:
        os.dup2(read_fd, 0)
    finally:
        os.close(read_fd)


def run_worker(args: list[str], ctx=None) -> int:
    if not args:
        warn('--run requires an executable')
        return 2
    original = list(args)
    worker = None
    try:
        from worker_record_clause import CLAUSE
        clause = CLAUSE
        kind = worker_kind(args)
        try:
            worker = worker_metadata(args, kind) if ctx else None
        except Exception:
            warn('補助メタデータを取得できません。条項の注入は続行します。')
        if kind == 'claude':
            args = claude_args(args, clause)
            record_receipt(ctx, 'added' if args != original else 'present', worker)
        elif kind == 'codex':
            i = codex_prompt_index(args)
            if i < len(args) and args[i] != '-':
                if args[i].strip() and MARKER not in args[i]:
                    args[i] += clause
                record_receipt(ctx, 'added' if args != original else 'present' if args[i].strip() else 'empty', worker)
            else:
                append_stdin(clause, ctx, worker)
        else:
            record_receipt(ctx, 'unsupported', worker)
            warn('この起動形式は自動注入の対象外です。記録の約束を起動文に書いてください。')
    except Exception as exc:
        record_receipt(ctx, 'prepare_failed', worker)
        warn('注入の準備を省略 (' + type(exc).__name__ + ')。元の worker を起動します。')
        args = original
    try:
        os.execvp(args[0], args)
    except OSError as exc:
        record_receipt(ctx, 'exec_failed', worker)
        # An oversized added argument must not prevent the original launch.
        import errno
        if exc.errno == errno.E2BIG and args != original:
            warn('追加後の引数が長すぎるため、元の worker を起動します。')
            os.execvp(original[0], original)
        warn('worker の起動に失敗 (' + type(exc).__name__ + ')')
        return 127 if exc.errno == errno.ENOENT else 126


def main() -> int:
    arguments, ctx = sys.argv[1:], None
    if arguments[:1] == ['--receipt-context'] and len(arguments) >= 3:
        try:
            candidate = json.loads(arguments[1])
            if valid_context(candidate):
                ctx = candidate
        except Exception:
            warn('注入記録の識別情報を読めません。起動は続行します。')
        arguments = arguments[2:]
    if arguments[:1] == ['--run']:
        return run_worker(arguments[1:], ctx)
    if '--selftest' in sys.argv[1:]:
        target = Path(sys.argv[sys.argv.index('--against') + 1]).resolve() if '--against' in sys.argv else Path(__file__).resolve()
        return selftest(target)
    try:
        out = rewrite(json.loads(sys.stdin.read() or '{}'))
        if out is not None:
            print(json.dumps(out, ensure_ascii=False))
    except Exception:
        pass  # A malformed event or unsupported shell form never blocks the tool.
    return 0


def selftest(hook):
    import subprocess
    import tempfile
    from worker_record_clause import CLAUSE
    checks = []

    def check(ok, label):
        checks.append(bool(ok))
        print(('OK ' if ok else 'FAIL ') + label)

    check(CLAUSE.splitlines()[3].startswith('作業の最後に、次の3項目を簡潔に報告してください。'),
          'shared clause requests final report items')

    def invoke(command, **event):
        ev = dict(hook_event_name='PreToolUse', tool_name='Bash',
                  tool_input={'command': command, 'timeout': 90000,
                              'run_in_background': True})
        ev.update(event)
        p = subprocess.run([sys.executable, str(hook)], input=json.dumps(ev),
                           text=True, capture_output=True)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout) if p.stdout.strip() else None

    positives = [
        "claude -p 'task'", "claude --print 'task'",
        "cd /tmp && MODE=x env OTHER=y claude -p 'task' > run.log 2>&1",
        "cat input | codex exec - --json", "codex -c model=sample exec 'task'",
        "codex e 'task'", "command claude -p \"$(cat input)\"",
        "claude -p <<'END'\nquoted task\nEND\n",
        "(cd /tmp && claude -p 'task')", "exec /opt/sample/claude --print 'task'",
    ]
    for cmd in positives:
        out = invoke(cmd)
        part = (out or {}).get('hookSpecificOutput', {})
        inp = part.get('updatedInput', {})
        check(inp.get('command', cmd) != cmd, 'inject: ' + cmd.splitlines()[0])
        if inp:
            check(inp['timeout'] == 90000 and inp['run_in_background'] is True
                  and 'permissionDecision' not in part, 'keep tool inputs and permission flow')
            check(invoke(inp['command']) is None, 'rewrite is idempotent')

    negatives = [
        "git commit -m 'mention claude -p and codex exec'",
        'echo "claude -p task"', "rg 'codex exec' source.py",
        "python3 -c 'print(\"claude -p task\")'", "claude 'ordinary prompt'",
        'codex --help', 'claude --help -p', 'codex exec --help',
        "cat <<'END'\nclaude -p task\ncodex exec task\nEND\n",
        "printf '%s' \"$(echo 'claude -p task')\"",
        "echo $(printf 'codex exec task')", "echo `printf 'claude -p task'`",
        "echo $'text; claude -p task'", "printf '%s' ${x:-claude -p task}",
        'echo x > claude', 'command -v claude', 'env --help claude -p task',
        'for x in claude -p task; do echo "$x"; done',
        "worker() { claude -p task; }; worker", "sh -c 'claude -p task'",
        "'clau" + "\\\n" + "de' -p task",
        'claude -p "unfinished', 'cat <<END\nclaude -p task\n',
    ]
    for cmd in negatives:
        check(invoke(cmd) is None, 'leave data/unsupported syntax: ' + cmd.splitlines()[0])
    check(invoke('claude -p task', tool_name='Read') is None, 'only Bash')
    check(invoke('claude -p task', hook_event_name='PostToolUse') is None, 'only PreToolUse')
    for raw in ['not json', '[]', 'null', '{"tool_input": null}']:
        p = subprocess.run([sys.executable, str(hook)], input=raw, text=True, capture_output=True)
        check(p.returncode == 0 and not p.stdout.strip(), 'malformed input fails open')

    if not all(checks):
        print(f'selftest: {sum(checks)}/{len(checks)} checks; command injection failed')
        return 1

    with tempfile.TemporaryDirectory(prefix='record-clause-test-') as td:
        root = Path(td)
        fake = '#!' + sys.executable + '\nimport json,sys,os\nprint(json.dumps({"argv":sys.argv[1:],"stdin":sys.stdin.read(),"cwd":os.getcwd(),"value":os.getenv("SAMPLE")}))\nsys.exit(int(os.getenv("SAMPLE_EXIT", "0")))\n'
        for name in ('claude', 'codex'):
            f = root / name
            f.write_text(fake, encoding='utf-8')
            f.chmod(0o755)
        (root / 'prompt.txt').write_text('original stdin; $value\n', encoding='utf-8')
        (root / 'system.txt').write_text('original system text', encoding='utf-8')
        env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'])

        def execute(cmd):
            out = invoke(cmd)
            rewritten = (out or {}).get('hookSpecificOutput', {}).get('updatedInput', {}).get('command', cmd)
            return subprocess.run(['/bin/bash', '-c', rewritten], cwd=root, env=env,
                                  stdin=subprocess.DEVNULL, text=True, capture_output=True)

        cases = [
            ('claude -p "task" < prompt.txt', 'claude'),
            ('claude --print "$(cat prompt.txt)"', 'claude'),
            ("claude -p <<'END'\noriginal heredoc\nEND\n", 'claude'),
            ('claude -p task --append-system-prompt "existing system"', 'claude'),
            ('claude -p task --append-system-prompt-file system.txt', 'claude'),
            ('codex exec -c developer_instructions=original "task" < prompt.txt', 'codex'),
            ('codex exec - < prompt.txt', 'codex'),
            ("codex exec <<'END'\noriginal heredoc\nEND\n", 'codex'),
            ('cat prompt.txt | codex exec --json', 'codex'),
        ]
        for cmd, kind in cases:
            p = execute(cmd)
            check(p.returncode == 0, 'shell execution succeeds: ' + cmd.splitlines()[0])
            data = json.loads(p.stdout)
            check('記録の約束' in json.dumps(data, ensure_ascii=False), 'clause reaches worker')
            if '< prompt.txt' in cmd:
                check(data['stdin'].startswith('original stdin; $value\n'), 'input file bytes preserved')
            if '--append-system-prompt "existing' in cmd:
                check(any('existing system' in x and '記録の約束' in x for x in data['argv']), 'existing system instruction preserved')
            if '--append-system-prompt-file' in cmd:
                check(any('original system text' in x and '記録の約束' in x for x in data['argv']), 'system instruction file preserved')
            if 'developer_instructions=' in cmd:
                check('developer_instructions=original' in data['argv'], 'Codex config override preserved')
            if 'heredoc' in cmd:
                check(data['stdin'].startswith('original heredoc\n'), 'heredoc body preserved')
        p = execute('SAMPLE=kept SAMPLE_EXIT=7 claude -p task')
        check(p.returncode == 7 and json.loads(p.stdout)['value'] == 'kept', 'environment and child exit code preserved')
        p = execute("claude -p first; codex exec second")
        check(len(p.stdout.splitlines()) == 2 and all('記録の約束' in json.dumps(json.loads(x), ensure_ascii=False) for x in p.stdout.splitlines()), 'each launch receives its own clause')
        p = execute("printf '%s' 'claude -p; codex exec'")
        check(p.stdout == 'claude -p; codex exec', 'quoted command mention remains byte identical')
        for cmd in ('codex exec - < /dev/null', "codex exec ''"):
            p = execute(cmd)
            check('記録の約束' not in json.dumps(json.loads(p.stdout), ensure_ascii=False),
                  'empty task remains empty instead of starting a new task')
    print(f'selftest: {sum(checks)}/{len(checks)} checks')
    return 0 if all(checks) else 1




if __name__ == '__main__':
    raise SystemExit(main())
