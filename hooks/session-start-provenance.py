#!/usr/bin/env python3
"""Cache Claude SessionStart model metadata for Agent-Session Git trailers."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from session_provenance_cache import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main("claude"))
