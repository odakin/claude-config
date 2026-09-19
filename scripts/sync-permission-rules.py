#!/usr/bin/env python3
"""sync-permission-rules.py — settings.json の permission rule を spec (JSON) の宣言どおりに揃える (冪等)

usage:
  sync-permission-rules.py --spec SPEC.json [--settings PATH]           # 監査: 揃っていなければ列挙して exit 1
  sync-permission-rules.py --spec SPEC.json [--settings PATH] --apply   # 適用: 変更した時だけ出力、 exit 0
  sync-permission-rules.py --selftest

  SPEC     = {"ask": {"required": [...], "superseded": {"旧 rule": "置き換え先"}}, "deny": {...}}
             spec の中の文字列の `${HOME}` は実行したマシンの home に展開する (= 絶対 path を含む
             rule を git に載せた 1 つの spec で複数マシンに配れる)。 form / 意味の正本 = engine の
             docstring (required / superseded / retired_re / "_" 始まりの注釈 key)
  PATH     = 既定 ~/.claude/settings.json (symlink なら実体を書く)
  失敗 (file 不在 / JSON 破損 / spec 不正) = stderr に理由、 exit 2、 何も書かない

使い方の想定: 個人層が必須 rule の spec を git に置き、 session 開始の auto-apply 層から毎回
--apply を呼ぶ (= あるマシンで直した rule が、 他マシンでも次の session 開始で揃う)。
engine = scripts/lib/permission_rules.py、 規約 = conventions/multi-machine-state.md#gate-rules-reassert-every-session
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import permission_rules  # noqa: E402


def _expand(obj, home: str):
    """spec の中の文字列の ${HOME} を home に展開する (dict の key も対象)。"""
    if isinstance(obj, str):
        return obj.replace("${HOME}", home)
    if isinstance(obj, list):
        return [_expand(x, home) for x in obj]
    if isinstance(obj, dict):
        return {_expand(k, home): _expand(v, home) for k, v in obj.items()}
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--spec", type=Path)
    ap.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return permission_rules.selftest()
    if not a.spec:
        ap.error("--spec が必要")
    try:
        spec = _expand(json.loads(a.spec.read_text(encoding="utf-8")), str(Path.home()).rstrip("/"))
        if a.apply:
            for line in permission_rules.apply(a.settings, spec):
                print(line)
            return 0
        gaps = permission_rules.audit(a.settings, spec)
    except Exception as e:
        print(f"sync-permission-rules: {e}", file=sys.stderr)
        return 2
    for line in gaps:
        print(line)
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
