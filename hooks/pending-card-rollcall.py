#!/usr/bin/env python3
"""pending-card-rollcall.py — Stop: この session が出した card のうち押されておらず本人がまだ見ていないものがあるのに、 最新の返事に点呼の 1 行 (「🃏 押されていない card N 枚」) が無ければ、 書く 1 行を添えて 1 回だけ止める

本体 = scripts/pending-cards.py の --stop (述語 = scripts/lib/pending_cards.py)。 この file は本体を呼ぶだけ。
正本 = conventions/multi-session-coordination.md#pending-card-rollcall。 本体が見つからない・例外は黙る (fail-open)。
test = hooks/pending-card-rollcall.test.sh
"""
import importlib.util
import os
import sys


def main() -> int:
    try:
        engine = os.environ.get("PENDING_CARDS_ENGINE") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "scripts", "pending-cards.py")
        if not os.path.isfile(engine):
            return 0
        spec = importlib.util.spec_from_file_location("pending_cards_cli", engine)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.stop_main()
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
