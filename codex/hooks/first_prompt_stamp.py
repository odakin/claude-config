#!/usr/bin/env python3
"""Re-inject the identity stamp right after the first user prompt of a Codex session.

Shared logic (Claude and Codex): scripts/first_reply_stamp.py.
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

raise SystemExit(first_reply_stamp.hook_main("codex", "prompt"))
