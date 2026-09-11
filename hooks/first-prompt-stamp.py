#!/usr/bin/env python3
"""first-prompt-stamp.py — UserPromptSubmit: session の最初の prompt に限り、 完全な自己同定 stamp を再注入 (I7)

logic の正本 = scripts/first_reply_stamp.py (Claude / Codex 共通)。 本 file は入口だけ。
出力は JSON の additionalContext のみ (= model だけに届き、 user の画面には出ない)。
fail-open: module 不在・例外は無出力で exit 0。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    import first_reply_stamp
except Exception:
    sys.exit(0)

sys.exit(first_reply_stamp.hook_main("claude", "prompt"))
