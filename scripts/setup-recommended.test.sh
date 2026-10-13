#!/usr/bin/env bash
# setup-recommended.test.sh — Exercise opt-in recommendations with a temporary HOME and command stubs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT/setup.sh" <<'PY'
import os
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
parse = source[source.index('NO_CLONE=0'):source.index('# --- GitHub')]
parts = source[source.index('JHEP_SRC="$SCRIPT_DIR/JHEP.bst"'):source.index('# --- 7. Install')]
watchdog = source[source.index('# --- 10. (macOS)'):source.index('echo "=== Done ==="')]
checks = 0
with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    for label, flag, environment, owner, install in (
        ('default', [], '0', 'fixture', False), ('flag', ['--recommended'], '0', 'fixture', True),
        ('env', [], '1', 'fixture', True), ('owner', [], '0', 'odakin', True)):
        home = base / label
        binary = home / 'bin'
        scripts = home / 'source/scripts'
        binary.mkdir(parents=True)
        scripts.mkdir(parents=True)
        (home / 'source/JHEP.bst').write_text('fixture')
        stubs = {
            'kpsewhich':'printf "%s\\n" "$HOME/texmf"',
            'git':'if [ "$#" = 3 ]; then echo author@example.invalid; else printf "%s\\n" "$*" >> "$HOME/git-calls"; fi',
            'gh':'printf "%s+%s@%s\\n" 1 fixture users.noreply.github.com',
            'uname':'echo Darwin',
        }
        for name, body in stubs.items():
            path = binary / name
            path.write_text('#!/bin/bash\n' + body + '\n')
            path.chmod(0o755)
        (scripts / 'install-pty-leak-mitigation.sh').write_text('printf "%s\\n" "$*" >> "$HOME/watchdog-calls"\n')
        code = parse + '\nGH_USER=' + owner + '\nSCRIPT_DIR="$HOME/source"\n' + parts + '\n' + watchdog
        env = dict(os.environ, HOME=str(home), SHELL='/bin/zsh', CLAUDE_RECOMMENDED=environment,
                   PATH=str(binary) + os.pathsep + os.environ['PATH'])
        subprocess.run(['bash', '-eu', '-c', code, 'fixture', *flag], env=env, capture_output=True, text=True, check=True)
        assert (home / 'texmf/bibtex/bst/local/JHEP.bst').exists() == install, label
        assert (home / 'git-calls').exists() == install, label
        assert (home / '.zshrc').exists() == install, label
        assert (home / 'watchdog-calls').exists() == (label in ('flag', 'env')), label
        if (home / 'watchdog-calls').exists():
            assert (home / 'watchdog-calls').read_text() == '\n', 'must never pass --persist'
        checks += 4
        subprocess.run(['bash', '-eu', '-c', code, 'fixture', *flag], env=env, capture_output=True, text=True, check=True)
        assert (home / '.zshrc').exists() == install, label
        if install:
            assert (home / '.zshrc').read_text().count('setopt interactive_comments') == 1, label
        checks += 1
print(f'recommended setup: {checks}/{checks} PASS')
PY
