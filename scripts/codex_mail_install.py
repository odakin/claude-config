#!/usr/bin/env python3
"""Install/audit only the owner-selected Codex mail skill and narrow prompt rule.

No credential, Claude settings, or general Codex permissions are read/changed.
Use --codex-dir with a temporary directory for isolated installer tests.
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

MARKER = "# Managed by the reviewed-mail installer\n"


def desired(codex_dir, helper, marker=MARKER, interpreter=None):
    # A stable launcher avoids cwd-dependent shell PATH and Python site-packages.
    for command in ([] if interpreter else ["python3.12", "python3.14", "python3.13", "python3.11", "python3.10", "python3"]):
        candidate = shutil.which(command)
        if candidate and subprocess.run([candidate, "-c", "import sys;sys.exit(sys.version_info < (3,10))"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            interpreter = candidate
            break
    if not interpreter:
        raise ValueError("Install Python 3.10+; no supported interpreter found")
    launcher = codex_dir / "bin/codex-mail"
    script = "#!/bin/sh\n" + marker + "exec " + shlex.quote(interpreter) + " " + shlex.quote(str(helper)) + ' "$@"\n'
    rule = marker + "prefix_rule(\n    pattern = " + json.dumps([str(launcher), "send"]) + ",\n"
    rule += '    decision = "prompt",\n'
    rule += '    justification = "Send only the reviewed mail after explicit user send approval",\n)\n'
    return helper, interpreter, script, rule


def apply(codex_dir, source, helper, install=False, marker=MARKER):
    codex_dir, source, helper = [Path(p).expanduser().resolve() for p in (codex_dir, source, helper)]
    link = codex_dir / "skills/codex-mail-workflow"
    rules = codex_dir / "rules/codex-mail.rules"
    store = codex_dir / "mail-workflow"
    launcher = codex_dir / "bin/codex-mail"
    # Preflight every target before mutation. Never replace a user's content.
    if (link.exists() or link.is_symlink()) and (not link.is_symlink() or link.resolve() != source):
        raise ValueError("Unmanaged skill target; left unchanged")
    if rules.is_symlink() or (rules.exists() and not rules.read_text().startswith(marker)):
        raise ValueError("Unmanaged rule target; left unchanged")
    if store.is_symlink() or (store.exists() and not store.is_dir()):
        raise ValueError("Runtime store must be a real directory")
    if launcher.is_symlink() or (launcher.exists() and not launcher.read_text().startswith("#!/bin/sh\n" + marker)):
        raise ValueError("Unmanaged launcher target; left unchanged")
    if not (source / "SKILL.md").is_file() or not helper.is_file():
        raise ValueError("Missing source skill/helper")
    interpreter = None
    if not install and launcher.exists():
        parts = shlex.split(launcher.read_text().splitlines()[-1])
        if len(parts) != 4 or parts[0] != "exec" or parts[2:] != [str(helper), "$@"]:
            raise ValueError("Managed launcher shape changed")
        interpreter = parts[1]
    helper, interpreter, launcher_text, rule = desired(codex_dir, helper, marker, interpreter)
    subprocess.run([interpreter, "-c", "import sys;sys.exit(sys.version_info < (3,10))"], check=True)
    subprocess.run([interpreter, str(helper), "--help"], check=True, stdout=subprocess.DEVNULL)
    if install:
        link.parent.mkdir(parents=True, exist_ok=True)
        rules.parent.mkdir(parents=True, exist_ok=True)
        launcher.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink(): link.symlink_to(source, target_is_directory=True)
        fd = os.open(rules, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600); f.write(rule)
        fd = os.open(launcher, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o700)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o700); f.write(launcher_text)
        store.mkdir(mode=0o700, exist_ok=True)
        store.chmod(0o700)
    if not link.is_symlink() or link.resolve() != source or not rules.exists() or rules.read_text() != rule:
        raise ValueError("Mail wiring missing/stale; run --install")
    if not launcher.exists() or launcher.read_text() != launcher_text or launcher.stat().st_mode & 0o777 != 0o700:
        raise ValueError("Mail launcher missing/stale; run --install")
    subprocess.run([str(launcher), "--help"], check=True, stdout=subprocess.DEVNULL)
    if rules.stat().st_mode & 0o077:
        raise ValueError("Rule file must be private (0600)")
    if not store.is_dir() or store.stat().st_mode & 0o077:
        raise ValueError("Runtime store missing or not private (0700)")
    print("Skill link, launcher, prompt-rule source, and Python helper import verified.")
    print("Client rule loading and approval UI require a fresh task; no email was sent.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--install", action="store_true")
    p.add_argument("--codex-dir", type=Path, default=Path.home() / ".codex")
    p.add_argument("--skill", type=Path, required=True)
    p.add_argument("--helper", type=Path, required=True)
    a = p.parse_args()
    try: apply(a.codex_dir, a.skill, a.helper, a.install)
    except Exception as e: p.exit(1, f"ERROR: {e}\n")
