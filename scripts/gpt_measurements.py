#!/usr/bin/env python3
"""[forwarder → ai-collaboration/scripts/gpt_measurements.py] 

移設済 (2026-09-06)。 正本 = ~/Claude/ai-collaboration/scripts/gpt_measurements.py。 旧 path からの `import` / 実行を壊さないための forwarder:
module として import されたら正本の全 symbol を re-export、 script として実行されたら正本を同じ argv で exec。
"""
import importlib.util as _ilu, pathlib as _pl, subprocess as _sp, sys as _sys

_L1 = _pl.Path.home() / "Claude" / "ai-collaboration" / "scripts" / "gpt_measurements.py"
if not _L1.exists():
    raise SystemExit(f"✗ forwarder: {_L1} not found (clone odakin/ai-collaboration)")
if __name__ == "__main__":
    _sys.exit(_sp.call([_sys.executable, str(_L1), *_sys.argv[1:]]))
_spec = _ilu.spec_from_file_location("gpt_measurements", _L1)
_mod = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_mod)
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
