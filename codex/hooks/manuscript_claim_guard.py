#!/usr/bin/env python3
"""Codex PreToolUse guard for manuscript claims and agent-authority rules.

# agent-authority:file

Thin adapter: passes the event to `scripts/manuscript-claim-guard.py hook codex`,
the same predicate the Claude hook and the Git pre-commit call. Semantic home:
`conventions/manuscript-claim-ownership.md`. Missing or broken engine denies the
pending call as uninspected; it never grants permission to weaken a restriction.
"""

from __future__ import annotations

import os
import json
import runpy
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "scripts", "manuscript-claim-guard.py"))

def unavailable(kind):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
        "permissionDecision": "deny", "permissionDecisionReason":
        f"manuscript-claim-guard: inspection unavailable ({kind}); repair the guard and retry; do not disable it."}}))

if __name__ == "__main__":
    if "--stop" in sys.argv[1:]:  # Stop の面: 記録した承認を最後の返事に書かせる。 壊れていたら通す (fail-open)
        if os.path.isfile(ENGINE):
            sys.argv = [ENGINE, "stop", "codex"]
            sys.dont_write_bytecode = True
            try:
                runpy.run_path(ENGINE, run_name="__main__")
            except (SystemExit, Exception):
                pass
        sys.exit(0)
    if not os.path.isfile(ENGINE):
        unavailable("missing engine")
        sys.exit(0)
    sys.argv = [ENGINE, "hook", "codex"]
    sys.dont_write_bytecode = True
    try:
        runpy.run_path(ENGINE, run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            unavailable("engine exit")
    except Exception as exc:
        unavailable(type(exc).__name__)
    sys.exit(0)
