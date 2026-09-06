#!/usr/bin/env bash
# Exercise reviewed replies without credentials, network, or agent state.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
python3 "$ROOT/test_reviewed_mail.py"
python3 "$ROOT/test_reviewed_mail_cli.py"
python3 "$ROOT/test_codex_mail_install.py"
