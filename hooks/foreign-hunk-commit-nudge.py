#!/usr/bin/env python3
"""foreign-hunk-commit-nudge.py — PreToolUse(Bash): git commit に、 この session が書いた文に無い変更の塊 (並列の session の未 commit の hunk かもしれない) が入るとき、 file と行を名指して知らせる入口 (止めない)。 述語・本体・--selftest = scripts/foreign-hunk-check.py

規約 = conventions/multi-session-coordination.md#staging-window-race (自分の分だけを commit する道具 = #temp-index-commit)。
知らせは commit の前に出るが、 止めないので command はそのまま走る = 混ざったと分かったら持ち主の session に知らせる
(#staging-window-race の事後責務)。 `FOREIGN_HUNK_MODE=deny` で止める、 `off` で黙る。
engine が無い・壊れているときは黙って通す (tool call を止めない)。
"""
import importlib.util
import os
import sys
from pathlib import Path

ENGINE = Path(os.environ.get("FOREIGN_HUNK_ENGINE") or Path(__file__).resolve().parents[1] / "scripts" / "foreign-hunk-check.py")


def _load():
    spec = importlib.util.spec_from_file_location("foreign_hunk_check", ENGINE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["foreign_hunk_check"] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    try:
        engine = _load()
    except Exception:
        raise SystemExit(0)
    raise SystemExit(engine.main(sys.argv[1:] or ["--hook"]))
