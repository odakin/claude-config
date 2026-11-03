#!/usr/bin/env python3
"""wrap-reply-knowledge-check.py — Stop: 締め (/wrap) の turn で、 返事にしか無い知見の照合 (session-reply-knowledge-report.py --check) が通っていなければ 1 回だけ差し戻す

何を塞ぐか (正本 = conventions/closing-sweep.md#reply-knowledge):
  締めの表で「会話を頭から読む」 行だけ道具が無く、 道具のある行を全部回して締め、 返事にしか無い導出を記録しないまま
  「足したものは無い」 と報告した (実測)。 道具を足しても、 回すかは締める側の手に残るので、 締めの turn の終わりで回したかを見る。
logic の正本 = scripts/session-reply-knowledge-report.py の stop_check / hook_stop_main (本 file は入口だけ)。
記録の末尾 4 MB だけを読み、 締めの印が無ければすぐ戻る。 自分の差し戻しは 1 turn に 1 回 (他の hook の差し戻しの後も判定する)。
fail-open: 部品の不在・例外は無出力で exit 0。
"""
import importlib.util
import sys
from pathlib import Path

try:
    _p = Path(__file__).resolve().parent.parent / "scripts" / "session-reply-knowledge-report.py"
    _spec = importlib.util.spec_from_file_location("session_reply_knowledge_report", _p)
    _m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_m)
except Exception:
    sys.exit(0)

sys.exit(_m.hook_stop_main())
