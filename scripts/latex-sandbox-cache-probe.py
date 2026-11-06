#!/usr/bin/env python3
"""Compare LuaLaTeX cache layouts in an isolated, synthetic document build.

Usage: python3 scripts/latex-sandbox-cache-probe.py [--work-dir NEW_DIR]
       python3 scripts/latex-sandbox-cache-probe.py --selftest

Creates two independent builds: an absolute cache with a separate output
directory, and a copied source built inside its output directory with
TEXMFCACHE and TEXMFVAR both set to '.'.
The command and working directory are recorded separately in report.json.
Existing work directories are rejected; originals and user settings are never
modified. Only an ASCII synthetic fixture is compiled. No shell-escape flag
or permission change is used. Run in the environment being diagnosed.

Exit 0: the relative-cache build completed without fontloader/glyph errors.
Exit 1: that build failed. Exit 2: unavailable engine or invalid input.
An absolute-cache failure is evidence for comparison, not proof of its cause.
The work directory is retained for inspection; remove it after saving any
needed evidence. A successful run is not a visual-quality assertion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


FIXTURE = r"""\documentclass{article}
\begin{document}
Cache probe: text and $\alpha+1$.
\end{document}
"""

WRITE_PROBE = r'''local lfs = require("lfs")
kpse.set_program_name("lualatex")
local path = assert(arg[1], "cache directory argument is required")
print("is_directory=" .. tostring(lfs.isdir(path)))
print("native_write_checker=" .. type(lfs.iswritablefile))
print("expanded_cache=" .. kpse.expand_var("$TEXMFCACHE"))
local name = path .. "/write-probe.tmp"
local file, err = io.open(name, "wb")
print("write_ok=" .. tostring(file ~= nil))
if file then file:close(); os.remove(name) else print(tostring(err)) end
'''


def classify(returncode: int, log: str, pdf_exists: bool) -> dict:
    errors = []
    if returncode:
        errors.append('process-failed')
    for tag, pattern in [
        ('no-writeable-cache', r'no writeable cache path'),
        ('fontloader-failed', r'FATAL ERROR|Failed to load .fontloader'),
        ('tex-error', r'^!'),
        ('missing-glyph', r'^Missing character:'),
    ]:
        if re.search(pattern, log, re.M):
            errors.append(tag)
    if not pdf_exists or 'Output written on' not in log:
        errors.append('pdf-incomplete')
    return {'returncode': returncode, 'errors': errors, 'completed': not errors}


def run_case(engine: str, base: Path, relative: bool, timeout: int) -> dict:
    name = 'relative-cache' if relative else 'absolute-cache'
    case = base / name
    source = case / 'input'
    output = case / 'output'
    source.mkdir(parents=True)
    output.mkdir()
    (source / 'probe.tex').write_text(FIXTURE, encoding='ascii')
    env = os.environ.copy()
    if relative:
        shutil.copy2(source / 'probe.tex', output / 'probe.tex')
        cwd = output
        env.update(TEXMFCACHE='.', TEXMFVAR='.')
        command = [engine, '-interaction=nonstopmode', '-halt-on-error', 'probe.tex']
    else:
        cache, var = case / 'cache', case / 'var'
        cache.mkdir()
        var.mkdir()
        cwd = source
        env.update(TEXMFCACHE=str(cache), TEXMFVAR=str(var))
        command = [engine, '-interaction=nonstopmode', '-halt-on-error',
                   '-output-directory=' + str(output), 'probe.tex']
    write_probe = None
    texlua = shutil.which('texlua')
    if texlua:
        lua_file = case / 'write-probe.lua'
        lua_file.write_text(WRITE_PROBE, encoding='ascii')
        cache_directory = output if relative else cache
        check = subprocess.run([texlua, str(lua_file), str(cache_directory)], cwd=cwd,
                               env=env, capture_output=True, text=True, errors='replace', timeout=30)
        (case / 'write-probe.txt').write_text(check.stdout + check.stderr)
        write_probe = {'returncode': check.returncode, 'write_ok': 'write_ok=true' in check.stdout}
    try:
        done = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                              text=True, errors='replace', timeout=timeout)
        code, stdout = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        raw = exc.stdout or b''
        stdout = raw.decode(errors='replace') if isinstance(raw, bytes) else raw
        stdout += '\nBuild timed out.\n'
    (case / 'console.txt').write_text(stdout)
    log_path = output / 'probe.log'
    log = log_path.read_text(errors='replace') if log_path.exists() else stdout
    result = classify(code, log, (output / 'probe.pdf').is_file())
    result.update(case=name, cwd=str(cwd), command=command,
                  cache=env['TEXMFCACHE'], var=env['TEXMFVAR'],
                  texlua_write_probe=write_probe)
    return result


def selftest() -> None:
    success = 'Output written on probe.pdf (1 page).\n'
    assert classify(0, success, True)['completed']
    assert not classify(1, success, True)['completed']
    assert not classify(0, success, False)['completed']
    assert not classify(0, 'incomplete', True)['completed']
    for message in ['no writeable cache path', 'FATAL ERROR',
                    '! Undefined control sequence.', 'Missing character: x']:
        assert not classify(0, message + '\n' + success, True)['completed']
    print('selftest: healthy build and 7 false-success cases checked')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    engine = shutil.which('lualatex')
    if not engine:
        parser.error('lualatex is unavailable')
    if not 1 <= args.timeout <= 300:
        parser.error('timeout must be between 1 and 300 seconds')
    if args.work_dir:
        base = args.work_dir.resolve()
        if base.exists():
            parser.error('work-dir must not exist; use a new directory')
        base.mkdir(parents=True)
    else:
        base = Path(tempfile.mkdtemp(prefix='latex-cache-probe-')).resolve()
    report = {'schema_version': 1,
              'fixture_sha256': hashlib.sha256(FIXTURE.encode('ascii')).hexdigest(),
              'cases': [run_case(engine, base, relative, args.timeout)
                        for relative in (False, True)],
              'limits': 'Synthetic build only; environment-specific observation, not causal proof.'}
    (base / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'work_dir': str(base), **report}, indent=2))
    return 0 if report['cases'][1]['completed'] else 1


if __name__ == '__main__':
    sys.exit(main())
