#!/usr/bin/env python3
"""Record (observe) or send back once (block) a first Codex turn whose replies never led with the identity stamp.

Shared logic and mode (DEFAULT_STOP_MODE, env FIRST_REPLY_STAMP_STOP): scripts/first_reply_stamp.py.
Contract: codex/PARITY.md#conversation-start-stamp. Fail-open.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
try:
    import first_reply_stamp
except Exception:
    raise SystemExit(0)

raise SystemExit(first_reply_stamp.hook_main("codex", "stop"))
