#!/usr/bin/env bash
# new-personal-layer.sh — Create a sibling personal layer from templates; --github publishes only a private repo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 - "$ROOT" "$@" <<'PY'
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
parser = argparse.ArgumentParser(description='Create a new personal layer beside claude-config. Existing layers are never replaced.')
parser.add_argument('directory', help='new sibling directory, e.g. my-prefs')
parser.add_argument('--name', help='display name for the home instruction title; defaults to the directory name')
parser.add_argument('--github', action='store_true', help='create a private GitHub repository with gh')
args = parser.parse_args(sys.argv[2:])
destination = Path(args.directory).expanduser()
if not destination.is_absolute():
    destination = root.parent / destination
destination = destination.absolute()
base = root.parent.resolve()
if destination.parent.resolve() != base or destination.name in ('.', '..'):
    parser.error('the new layer must be a sibling of claude-config')
if destination.exists() or destination.is_symlink():
    parser.error('destination already exists; refusing to replace it')
if args.github and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', destination.name):
    parser.error('--github requires a plain repository name without spaces or leading options')
configured = os.environ.get('CLAUDE_PERSONAL_LAYER', '')
if configured and configured != 'none' and (Path(configured).expanduser() / '.claude-personal-layer').is_file():
    parser.error('a personal layer is already configured')
if any((path / '.claude-personal-layer').is_file() for path in base.iterdir() if path.is_dir()):
    parser.error('a personal layer already exists beside claude-config')
if args.github:
    subprocess.run(['gh', 'auth', 'status'], check=True)
templates = root / 'templates/personal-layer'
files = ('CLAUDE.md', 'AGENTS.md', 'repos.md', 'user-profile.md', 'shared-project-keys.md', 'codex/AGENTS.md')
replacements = {'<your-name>': args.name or destination.name, '<your>-prefs': destination.name,
                '<base>': '..', '<this-layer>': '.'}
with tempfile.TemporaryDirectory(prefix='.personal-layer-', dir=base) as temporary:
    staging = Path(temporary) / destination.name
    staging.mkdir()
    for name in files:
        text = (templates / (name + '.template')).read_text()
        for before, after in replacements.items():
            text = text.replace(before, after)
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    (staging / '.claude-personal-layer').touch()
    subprocess.run(['git', 'init', '-b', 'main', str(staging)], check=True)
    identity = [subprocess.run(['git', 'config', '--global', '--get', 'user.' + key],
                               capture_output=True, text=True).stdout.strip() for key in ('name', 'email')]
    committed = all(identity)
    if committed:
        subprocess.run(['bash', str(root / 'scripts/install-session-trailer.sh'), '--refuse-existing', str(staging)], check=True)
        subprocess.run(['git', '-C', str(staging), 'add', '--', *files, '.claude-personal-layer'], check=True)
        subprocess.run(['git', '-C', str(staging), 'commit', '-m', 'Initialize personal layer'], check=True)
    # mkdir reserves the name without replacing a directory created by another invocation.
    destination.mkdir()
    for path in staging.iterdir():
        path.rename(destination / path.name)
if args.github:
    command = ['gh', 'repo', 'create', destination.name, '--private', '--source', str(destination), '--remote', 'origin']
    if committed:
        command.append('--push')
    subprocess.run(command, check=True)
print('Created:', destination)
if not committed:
    print('Initial commit skipped: set global Git user.name and user.email, then commit the template files.')
print('Fill in user-profile.md and repos.md, then rerun setup.sh to select the personal layer.')
PY
