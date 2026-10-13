#!/usr/bin/env bash
# new-personal-layer.test.sh — Isolated creation, identity, refusal, and private GitHub arguments.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

source = Path(sys.argv[1])
checks = 0
with tempfile.TemporaryDirectory() as directory:
    for identity, github in ((False, False), (True, False), (True, True), (False, True)):
        base = Path(directory) / f'{identity}-{github}'
        root = base / 'claude-config'
        (root / 'scripts').mkdir(parents=True)
        shutil.copytree(source/'templates/personal-layer', root/'templates/personal-layer')
        shutil.copyfile(source/'scripts/new-personal-layer.sh', root/'scripts/new-personal-layer.sh')
        (root/'scripts/install-session-trailer.sh').write_text('test "$1" = --refuse-existing\nprintf "%s\\n" "$2" >> "$HOME/trailer-install"\n')
        home = base/'home'
        binary = home/'bin'
        binary.mkdir(parents=True)
        env = dict(os.environ, HOME=str(home), GIT_CONFIG_NOSYSTEM='1',
                   GIT_CONFIG_GLOBAL=str(home/'.gitconfig'), CLAUDE_PERSONAL_LAYER='none',
                   PATH=str(binary)+os.pathsep+os.environ['PATH'])
        for key in tuple(env):
            if key.startswith(('GIT_AUTHOR_', 'GIT_COMMITTER_')):
                env.pop(key)
        if identity:
            for key, value in (('name','Fixture'),('email','fixture@example.com')):
                subprocess.run(['git','config','--global','user.'+key,value],env=env,check=True)
        gh = binary/'gh'
        gh.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$HOME/gh-calls"\n')
        gh.chmod(0o755)
        command=['bash',str(root/'scripts/new-personal-layer.sh'),'my-prefs','--name','Fixture']
        if github: command.append('--github')
        result=subprocess.run(command,env=env,capture_output=True,text=True)
        assert result.returncode==0, result.stderr
        layer=base/'my-prefs'
        assert (layer/'.claude-personal-layer').is_file()
        assert (layer/'AGENTS.md').is_file() and (layer/'codex/AGENTS.md').is_file()
        assert '<your' not in (layer/'CLAUDE.md').read_text() and 'Fixture' in (layer/'CLAUDE.md').read_text()
        head=subprocess.run(['git','-C',str(layer),'rev-parse','--verify','HEAD'],env=env,capture_output=True).returncode==0
        assert head==identity
        assert (home/'trailer-install').exists()==identity
        before=(layer/'CLAUDE.md').read_bytes()
        assert subprocess.run(command,env=env,capture_output=True).returncode!=0
        assert (layer/'CLAUDE.md').read_bytes()==before
        command[2]='second-prefs'
        assert subprocess.run(command,env=env,capture_output=True).returncode!=0
        assert not (base/'second-prefs').exists()
        if github:
            calls=(home/'gh-calls').read_text()
            assert '--private' in calls and '--public' not in calls
            assert ('--push' in calls)==identity
        else:
            assert not (home/'gh-calls').exists()
        checks += 9
print(f'new personal layer: {checks}/{checks} PASS')
PY
