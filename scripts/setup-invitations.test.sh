#!/usr/bin/env bash
# setup-invitations.test.sh — Pending invitations print commands without accepting or cloning.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT/setup.sh" <<'PY'
import os
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
block = source[source.index('# Pending invitations'):source.index('# --- 5a. Personal home')]
with tempfile.TemporaryDirectory() as directory:
    home = Path(directory)
    binary = home / 'bin'
    binary.mkdir()
    gh = binary / 'gh'
    gh.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$HOME/calls"\nprintf "%s" "$FIXTURE_INVITATIONS"\n')
    gh.chmod(0o755)
    env = dict(os.environ, HOME=directory, PATH=str(binary)+os.pathsep+os.environ['PATH'],
               FIXTURE_INVITATIONS='42\tfixture/example\n43\tfixture/second\n')
    code = 'GH_USER=fixture\nCLAUDE_DIR="$HOME/work space"\n' + block
    output = subprocess.run(['bash','-eu','-c',code], env=env, capture_output=True, text=True, check=True).stdout
    assert 'PATCH user/repository_invitations/42' in output
    assert 'gh repo clone fixture/example' in output and 'work\\ space/example' in output
    assert (home/'calls').read_text().count('\n') == 1
    assert '--method' not in (home/'calls').read_text() and 'repo clone' not in (home/'calls').read_text()
    for payload in ('', 'bad\tfixture/example\n42\tinvalid;command\n'):
        env['FIXTURE_INVITATIONS'] = payload
        output = subprocess.run(['bash','-eu','-c',code], env=env, capture_output=True, text=True, check=True).stdout
        assert 'gh repo clone' not in output and '--method PATCH' not in output
print('invitation display: 6/6 PASS')
PY
