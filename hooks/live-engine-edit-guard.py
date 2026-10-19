#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live-engine-edit-guard.py — PreToolUse(Edit): hook や git の hook が作業 tree から直接読む file を、 その session で初めて Edit するとき 1 回だけ止め、 写しで直すか 1 回で済ませるかを決めさせる

なぜ:
  settings の hook と各 repo の git hook (pre-commit ほか) は、 呼ぶ script を作業 tree の file のまま読む。 その file を Edit で
  何回にも分けて直すと、 途中の形を同じ機械の別の session が走らせる (実測: 検査の engine を分けて直す途中、 読む側と受ける側の
  形が食い違った数分間に別の session の commit が走り、 検査が異常終了して fail-open で素通りした)。 規約はあったが守られず
  2 回目が起きた = 文でなく機械にした。 規則 = conventions/hook-authoring.md#live-hook-edit-runs-elsewhere。

動作:
  - 読まれている file の一覧 = scripts/live-engine-paths.py (settings の hook と git hook から辿る、 30 分 cache)。
  - Edit の対象がその一覧にあり、 この session でその file をまだ止めていなければ deny (理由に呼び元と直し方)。
    同じ file の 2 回目からは止めない (= 1 か所だけの直しなら、 同じ Edit を打ち直すだけで通る)。
  - MultiEdit・Write は止めない (1 回で file 全体を書く = 途中の形が出ない)。
  - 一覧が作れない・入力が壊れている → 何もしない (fail-open)。
env: LIVE_ENGINE_EDIT_GUARD_MODE=nudge (止めずに知らせるだけ)、 LIVE_ENGINE_EDIT_STATE_DIR (状態の dir)、
     LIVE_ENGINE_PATHS_ENGINE (engine の path、 test 用)。 一覧の cache の場所 = engine の LIVE_ENGINE_PATHS_CACHE
"""
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
ENGINE = os.environ.get("LIVE_ENGINE_PATHS_ENGINE") or os.path.join(REPO, "scripts", "live-engine-paths.py")
STATE_DIR = os.environ.get("LIVE_ENGINE_EDIT_STATE_DIR") or os.path.expanduser("~/.claude/state/live-engine-edit-guard")
KEEP_DAYS = 14


def load_engine():
    spec = importlib.util.spec_from_file_location("live_engine_paths", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def state_path(session):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session or "nosession")
    return os.path.join(STATE_DIR, safe + ".json")


def load_seen(session):
    try:
        with open(state_path(session), encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(session, seen):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = state_path(session) + ".{}.tmp".format(os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f, ensure_ascii=False)
        os.replace(tmp, state_path(session))
        cutoff = time.time() - KEEP_DAYS * 86400
        for name in os.listdir(STATE_DIR):
            p = os.path.join(STATE_DIR, name)
            if name.endswith(".json") and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except Exception:
        pass


def reason(path, caller):
    name = os.path.basename(path)
    return "\n".join([
        "🛑 live-engine-edit-guard: この file は hook か git の hook が作業 tree から直接読む (呼び元 = {})。".format(caller),
        "  Edit を何回にも分けると、 途中の形を同じ機械の別の session が走らせる (実測: 検査が異常終了して commit が素通りした)。",
        "  - 直すのが 1 か所だけ (この Edit の後で file が一貫した形になる) → 同じ Edit をもう一度打つ (この session のこの file は以後止めない)",
        "  - 2 か所以上 → 同じ dir の写し (例 `.{}.wip`) に Edit を重ね、 試してから `mv -f` で入れる (rename は原子的)。".format(name),
        "    1 回の Write で全文を置き換える形も、 途中の形が出ない",
        "  正本 = claude-config/conventions/hook-authoring.md#live-hook-edit-runs-elsewhere",
    ])


def run_hook():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if payload.get("tool_name") != "Edit":
        return 0
    path = str((payload.get("tool_input") or {}).get("file_path") or "")
    if not path:
        return 0
    eng = load_engine()
    caller = eng.caller_of(path)
    if not caller:
        return 0
    real = os.path.realpath(path)
    session = str(payload.get("session_id") or "")
    seen = load_seen(session)
    if real in seen:
        return 0
    save_seen(session, seen | {real})
    text = reason(real, caller)
    if os.environ.get("LIVE_ENGINE_EDIT_GUARD_MODE") == "nudge":
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}
    else:
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": text}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run_hook())
    except Exception:
        sys.exit(0)
