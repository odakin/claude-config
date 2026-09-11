#!/usr/bin/env python3
"""first-turn-stamp-check.py — Stop: 最初の turn のどの返信の 1 行目にも自己同定 stamp が無ければ記録 (observe) / 1 回だけ差し戻す (block)

logic・mode の正本 = scripts/first_reply_stamp.py (DEFAULT_STOP_MODE、 env FIRST_REPLY_STAMP_STOP で上書き)。
本 file は入口だけ。 1 session につき評価は最初の Stop の 1 回 (以後の turn では transcript を読まない)。
fail-open: module 不在・例外は無出力で exit 0。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    import first_reply_stamp
except Exception:
    sys.exit(0)

sys.exit(first_reply_stamp.hook_main("claude", "stop"))
