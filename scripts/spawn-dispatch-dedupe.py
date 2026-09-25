#!/usr/bin/env python3
"""spawn-dispatch-dedupe.py — 同じ依頼に worker session を 2 つ起動させない検出 (chip の二重起票) の CLI。
実体 = lib/spawn_dedupe.py (chip の title の照合・spawn / dismiss の台帳・session 刻印による生存の判定)。
hook = hooks/spawn-dedupe-guard.sh が `auto` で呼ぶ (PreToolUse spawn_task = 止める / PostToolUse spawn_task・dismiss_task = 台帳)。
依頼の同一性を title 以外の鍵で見る利用者側の extension = ~/.claude/spawn-dedupe-ext.py (lib の docstring)。

使い方:
  python3 spawn-dispatch-dedupe.py auto < hook-input.json         # hook から (event と tool で分岐)
  python3 spawn-dispatch-dedupe.py pre-spawn|post-spawn|post-dismiss < hook-input.json
  python3 spawn-dispatch-dedupe.py --selftest
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import spawn_dedupe as SD  # noqa: E402


def main(argv: list) -> int:
    if os.environ.get("SPAWN_DEDUPE_DISABLE") == "1":
        return 0
    if len(argv) < 2:
        print(__doc__)
        return 0
    if argv[1] == "--selftest":
        return SD.selftest()
    try:
        inp = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if not isinstance(inp, dict):
        return 0
    return SD.run(argv[1], inp)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
