#!/usr/bin/env python3
"""[forwarder → ai-collaboration/scripts/verification-campaign-report.py] verify-to-learn campaign の集計: ledger.yaml (3 状態 / tier / readings) + git 由来の所要・entries per commit + efficacy proxy (受領側記入 novel_to_requester) を results.md の AUTO block に焼き、👁 未了 ite

移設済 (2026-09-06)。 正本 = ~/Claude/ai-collaboration/scripts/verification-campaign-report.py。 旧 path (claude-config/scripts) を hardcode した呼び元を壊さないための forwarder = 同じ argv で正本を exec。
"""
import pathlib, subprocess, sys

L1 = pathlib.Path.home() / "Claude" / "ai-collaboration" / "scripts" / "verification-campaign-report.py"
if not L1.exists():
    print(f"✗ forwarder: {L1} not found (clone odakin/ai-collaboration)", file=sys.stderr); sys.exit(1)
sys.exit(subprocess.call([sys.executable, str(L1), *sys.argv[1:]]))
