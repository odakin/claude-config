#!/usr/bin/env python3
"""Check the model policy before dispatching a prompt to a board worker."""

import runpy
from pathlib import Path


if __name__ == "__main__":
    launcher = Path(__file__).resolve().parents[2] / "scripts" / "codex-app-launch.py"
    raise SystemExit(runpy.run_path(str(launcher))["check_prompt"]())
