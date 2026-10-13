#!/usr/bin/env bash
# install-docx-decl-patch.test.sh — Explicit interpreter and two-Python installation using isolated stubs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT/scripts/install-docx-decl-patch.sh" <<'PY'
import os
from pathlib import Path
import subprocess
import sys
import tempfile

installer=Path(sys.argv[1])
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    runtimes=[]
    for name in ('system','package'):
        binary=root/name
        binary.mkdir()
        runtime=binary/'python3'
        runtime.write_text('#!/bin/bash\ncase "$*" in *getusersitepackages*) printf "%s\\n" "$HOME/'+name+'-site";; *) exit 1;; esac\n')
        runtime.chmod(0o755)
        runtimes.append(runtime)
    # An isolated source copy replaces only the hard-coded discovery list with test runtimes.
    # --python tests the public interface without touching any host interpreter.
    env=dict(os.environ,HOME=directory,PATH=str(root/'system')+':'+str(root/'package')+':/usr/bin:/bin')
    for runtime in runtimes:
        result=subprocess.run(['bash',str(installer),'--python',str(runtime)],env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    for name in ('system','package'):
        site=root/(name+'-site')
        assert (site/'docx_decl_patch.py').is_symlink()
        assert (site/'docx_decl_patch.pth').read_text()=='import docx_decl_patch\n'
    before=(root/'system-site/docx_decl_patch.pth').stat().st_mtime_ns
    subprocess.run(['bash',str(installer),'--python',str(runtimes[1])],env=env,capture_output=True,check=True)
    assert (root/'system-site/docx_decl_patch.pth').stat().st_mtime_ns==before
    result=subprocess.run(['bash',str(installer),'--python',str(root/'missing')],env=env,capture_output=True)
    assert result.returncode!=0
print('docx interpreter selection: 6/6 PASS')
PY
