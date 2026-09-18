#!/usr/bin/env python3
"""Codex PreToolUse guard for manuscript claims and agent-authority rules.

# agent-authority:file

Thin adapter: passes the event to `scripts/manuscript-claim-guard.py hook codex`,
the same predicate the Claude hook and the Git pre-commit call. Semantic home:
`conventions/manuscript-claim-ownership.md`. Missing engine or an exception is
fail-open; the Git-side check remains the last line.
"""

from __future__ import annotations

import os
import runpy
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "scripts", "manuscript-claim-guard.py"))

if __name__ == "__main__":
    if not os.path.isfile(ENGINE):
        sys.exit(0)
    sys.argv = [ENGINE, "hook", "codex"]
    sys.dont_write_bytecode = True
    try:
        runpy.run_path(ENGINE, run_name="__main__")
    except SystemExit:
        pass
    except Exception as exc:  # fail-open (one line; no repr, which can carry whole blob bytes)
        print(f"manuscript_claim_guard: {type(exc).__name__}: {' '.join(str(exc).split())[:200]}", file=sys.stderr)
    sys.exit(0)
