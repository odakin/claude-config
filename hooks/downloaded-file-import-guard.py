#!/usr/bin/env python3
"""downloaded-file-import-guard.py — PreToolUse(Bash): ネット由来の file (Downloads の下と、 ダウンロードの印つき) を git の作業 tree へ cp / mv / 展開する command を、 scripts/downloaded-file-scan.py の検査の記録が無ければ deny する (conventions/downloaded-file-scan.md#import-net)

判定の本体 = scripts/downloaded-file-scan.py の find_issues (この file は入出力だけを持つ = 述語を 1 か所に置き、
  校正 〔calibrate-bash-command-pattern.py --func shape_issues〕 と本番で同じ関数を使う)。
止めるもの: cp / mv / ditto / rsync / install / ln / unzip / tar の展開で、 ネット由来の file を git の作業 tree
  (HOME 自身を除く) に入れ、 その file の検査の記録が無い・要確認・未検査の部分ありのもの。
通すもの: 検査の記録が「要確認なし」 の file / 取り込み先が repo の外 / command の中の
  `downloaded-file-scan: accepted <理由>` (本人が取り込むと決めたときだけ書く)。
出力: permissionDecision=deny + 検査の command。 誤検出のコストは検査 1 回 (file 数個で 1 秒未満)。
fail-open: 読めない入力・engine が無い・engine の例外は黙って通す。
opt-out = CLAUDE_DOWNLOAD_IMPORT_GUARD=0 (本人の明示の指示があるときだけ = agent-rule-ownership.md#guard-escape-hatch)。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "scripts", "downloaded-file-scan.py"))
PREFILTER = re.compile(r"\b(?:cp|mv|ditto|rsync|install|ln|unzip|tar|gcp|gmv)\b")


def _load_engine():
    spec = importlib.util.spec_from_file_location("downloaded_file_scan", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    if os.environ.get("CLAUDE_DOWNLOAD_IMPORT_GUARD", "") == "0":
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not PREFILTER.search(cmd):
        return 0
    try:
        eng = _load_engine()
        issues = eng.find_issues(cmd, data.get("cwd") or os.getcwd(), os.path.expanduser("~"))
        if not issues:
            return 0
        reason = eng.reason_text(issues, ENGINE)
    except Exception:  # fail-open
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
