#!/usr/bin/env python3
"""shared-tree-stash-guard.py — 未 commit の変更が居る作業 tree での git stash・--autostash を止める PreToolUse(Bash) の入口 (他の session の作業を退避させない)。 述語・本体・--selftest = scripts/git-stash-shared-tree.py

規約 = conventions/multi-session-coordination.md#autostash-foreign-wip。 engine が無い・壊れているときは黙って通す (tool call を止めない)。
"""
import importlib.util
import os
import sys
from pathlib import Path

ENGINE = Path(os.environ.get("SHARED_TREE_STASH_ENGINE") or Path(__file__).resolve().parents[1] / "scripts" / "git-stash-shared-tree.py")


def _load():
    spec = importlib.util.spec_from_file_location("git_stash_shared_tree", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    try:
        engine = _load()
    except Exception:
        raise SystemExit(0)
    raise SystemExit(engine.main(sys.argv[1:]))
