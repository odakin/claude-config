#!/usr/bin/env python3
"""workspace-root-git-guard.py — PreToolUse(Bash): repo を並べた作業ルートで、 path を書かない `git init` と書き込みの git を止める (判定の engine = scripts/workspace-root-git-guard.py、 規約 = conventions/claude-code-permissions.md#cd-with-git-goes-to-classifier)。

この file は入口だけで、 述語・直し方の文・selftest は engine が持つ。 engine が見つからない checkout では黙って通す (fail-open)。
test = hooks/workspace-root-git-guard.test.sh
"""
import os
import runpy
import sys

ENGINE = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, "scripts", "workspace-root-git-guard.py")

if __name__ == "__main__":
    if not os.path.isfile(ENGINE):
        sys.exit(0)
    sys.argv = [ENGINE] + (sys.argv[1:] or ["--hook"])
    runpy.run_path(ENGINE, run_name="__main__")
