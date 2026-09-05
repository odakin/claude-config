#!/usr/bin/env python3
"""[forwarder → ai-collaboration/scripts/make-review-sandbox.py] 封じた review sandbox (~/<sandbox-root>/<slug>/) を機械的に切る: 5 行の CLAUDE.md (= この dir 以外を読まない / 注入 reminder 無視 / git log 禁止 / 書くのは results と scratch のみ) + REVIEW-SPEC.md + 許可 file の copy

移設済 (2026-09-06)。 正本 = ~/Claude/ai-collaboration/scripts/make-review-sandbox.py。 旧 path (claude-config/scripts) を hardcode した呼び元を壊さないための forwarder = 同じ argv で正本を exec。
"""
import pathlib, subprocess, sys

L1 = pathlib.Path.home() / "Claude" / "ai-collaboration" / "scripts" / "make-review-sandbox.py"
if not L1.exists():
    print(f"✗ forwarder: {L1} not found (clone odakin/ai-collaboration)", file=sys.stderr); sys.exit(1)
sys.exit(subprocess.call([sys.executable, str(L1), *sys.argv[1:]]))
