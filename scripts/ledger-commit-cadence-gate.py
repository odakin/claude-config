#!/usr/bin/env python3
"""[forwarder → ai-collaboration/scripts/ledger-commit-cadence-gate.py] YAML ledger の commit cadence gate (pre-commit): 1 commit で追加される list entry (`- id:`) が N 個を超えたら refuse、escape env は hygiene log に記録 + worker scope gate (= env CAMPAIGN_WORKER_DIR が

移設済 (2026-09-06)。 正本 = ~/Claude/ai-collaboration/scripts/ledger-commit-cadence-gate.py。 旧 path (claude-config/scripts) を hardcode した呼び元を壊さないための forwarder = 同じ argv で正本を exec。
"""
import pathlib, subprocess, sys

L1 = pathlib.Path.home() / "Claude" / "ai-collaboration" / "scripts" / "ledger-commit-cadence-gate.py"
if not L1.exists():
    print(f"✗ forwarder: {L1} not found (clone odakin/ai-collaboration)", file=sys.stderr); sys.exit(1)
sys.exit(subprocess.call([sys.executable, str(L1), *sys.argv[1:]]))
