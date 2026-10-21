#!/usr/bin/env python3
"""worker-safety-stop-guard.py — stop SendMessage to a local session with a recorded provider refusal."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "worker-safety-stop.py"), run_name="__main__")
