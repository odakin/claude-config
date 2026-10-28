#!/usr/bin/env python3
"""cli-binary-read-nudge.py — Claude Code 本体 (CLI の binary・埋込 engine・app の bundle) を使い捨ての code で読む Bash に、 道具 claude-app-bundle.py を 1 session に 1 回知らせる PreToolUse の入口 (止めない)。 述語・本体・--selftest = scripts/cli-binary-read-check.py

規約 = conventions/claude-app-bundle-reading.md。 engine が無い・壊れているときは黙って通す (tool call を止めない)。
"""
import importlib.util
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "scripts" / "cli-binary-read-check.py"


def _load():
    spec = importlib.util.spec_from_file_location("cli_binary_read_check", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    try:
        engine = _load()
    except Exception:
        raise SystemExit(0)
    raise SystemExit(engine.main(sys.argv[1:]))
