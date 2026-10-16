"""Read explicitly addressed Codex threads through app-server; never list history.

Only thread/read, skills/list and hooks/list are exposed. No model turn, approval,
trust write, message, or configuration mutation is started by this client.
The app-server's stderr is kept (last lines only) so an exit at start reports its
cause. Measured: app-server exits at start when it cannot write its state under
CODEX_HOME, which is what happens inside the Codex workspace-write sandbox; the
error then names the remedy (run the command outside the sandbox).
"""
from __future__ import annotations

import collections
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


def runtime_binary(requested='auto'):
    path = Path(__file__).resolve().parents[1] / 'audit-codex-hook-runtime.py'
    spec = importlib.util.spec_from_file_location('codex_wrap_runtime_audit', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.discover_codex(requested)[0]


STDERR_LINES = 20
STATE_FAILURE = 'state runtime'


def exit_message(stderr_lines, environ=None):
    """Explain an app-server exit from its stderr; name the sandbox remedy when it applies."""
    environ = os.environ if environ is None else environ
    lines = [line.strip() for line in stderr_lines if line.strip()]
    detail = ' | '.join(lines)[-600:]
    message = 'app-server exited' + (': ' + detail if detail else ' (no stderr)')
    if STATE_FAILURE in detail or environ.get('CODEX_SANDBOX'):
        message += ('; app-server must write its state under CODEX_HOME, which the Codex '
                    'workspace-write sandbox does not allow: rerun this command outside the '
                    'Codex sandbox (an approved escalated command)')
    return message


class Reader:
    def __init__(self, binary='auto', timeout=30):
        self.binary = runtime_binary(binary)
        self.timeout = timeout
        self.serial = 0
        self.process = None

    def __enter__(self):
        self.process = subprocess.Popen([self.binary, 'app-server', '--stdio'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
        self.messages = queue.Queue()
        self.stderr_tail = collections.deque(maxlen=STDERR_LINES)
        def drain_stderr():
            for line in self.process.stderr:
                self.stderr_tail.append(line.rstrip('\n'))
        self.stderr_worker = threading.Thread(target=drain_stderr, daemon=True)
        self.stderr_worker.start()
        def receive():
            try:
                for line in self.process.stdout:
                    try:
                        self.messages.put(json.loads(line))
                    except ValueError:
                        continue
            finally:
                self.messages.put(None)
        self.worker = threading.Thread(target=receive, daemon=True)
        self.worker.start()
        try:
            self._call('initialize', {'clientInfo': {'name':'wrap-reader', 'version':'1'},
                                      'capabilities': {'experimentalApi':True}})
            self.process.stdin.write('{"method":"initialized","params":{}}\n')
            self.process.stdin.flush()
        except Exception:
            self.close()
            raise
        return self

    def _exited(self):
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        self.stderr_worker.join(timeout=1)
        return RuntimeError(exit_message(list(self.stderr_tail)))

    def _call(self, method, params):
        self.serial += 1
        ident = self.serial
        try:
            self.process.stdin.write(json.dumps({'id':ident, 'method':method, 'params':params})+'\n')
            self.process.stdin.flush()
        except BrokenPipeError:
            raise self._exited() from None
        deadline = time.monotonic()+self.timeout
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError(method+' timed out')
            try:
                value = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(method+' timed out') from exc
            if value is None:
                raise self._exited()
            if isinstance(value, dict) and value.get('id') == ident:
                if 'error' in value:
                    raise RuntimeError(method+' unavailable: '+str(value['error'].get('code','unknown')))
                return value.get('result')

    def call(self, method, params):
        if method not in {'thread/read', 'skills/list', 'hooks/list'}:
            raise ValueError('read-only client method refused')
        return self._call(method, params)

    def thread(self, ident):
        value = self.call('thread/read', {'threadId':ident, 'includeTurns':True})
        thread = value.get('thread') if isinstance(value, dict) else None
        if not isinstance(thread, dict) or thread.get('id') != ident or not isinstance(thread.get('turns'), list):
            raise ValueError('thread/read returned an unexpected identity or shape')
        return thread

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
            self.worker.join(timeout=1)
            self.stderr_worker.join(timeout=1)

    def __exit__(self, *_):
        self.close()
