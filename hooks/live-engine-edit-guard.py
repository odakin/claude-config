#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live-engine-edit-guard.py — PreToolUse(Edit): hook や git の hook が作業 tree から直接読む file を、 その session で初めて Edit するとき止め、 写しで直すか 1 回で済ませるかを決めさせる

なぜ:
  settings の hook と各 repo の git hook (pre-commit ほか) は、 呼ぶ script を作業 tree の file のまま読む。 その file を Edit で
  何回にも分けて直すと、 途中の形を同じ機械の別の session が走らせる (実測: 検査の engine を分けて直す途中、 読む側と受ける側の
  形が食い違った数分間に別の session の commit が走り、 検査が異常終了して fail-open で素通りした)。 規約はあったが守られず
  2 回目が起きた = 文でなく機械にした。 規則 = conventions/hook-authoring.md#live-hook-edit-runs-elsewhere。

動作:
  - 読まれている file の一覧 = scripts/live-engine-paths.py (settings の hook と git hook から辿る、 30 分 cache)。
  - Edit の対象がその一覧にあり、 この session でその file をまだ止めていなければ deny (理由に呼び元と直し方)。 止めた Edit の
    中身 (old_string・new_string・replace_all) を控える。
  - 止めた後は、 控えた Edit と同じ中身の再送だけを通し、 その file はそこから止めない (= 1 か所だけの直しなら、 同じ Edit を
    打ち直すだけで通る)。 再送の前に来た、 同じ file への別の Edit は止め続ける (2026-10-21〜。 それまでは止めるのが初めての
    1 回だけで、 同じ file への Edit を 1 つの message に並べると最初の 1 本だけが止まり、 2 本目以降が通って途中の形の file が
    残った = 実測 2 回)。
  - 止めた後に file が別の手段で変わった (写しから `mv -f` で入れた・Write で全文を書いた) なら、 控えを捨て、 次の Edit を
    改めて止める (= 再送しないまま閉じ込めない)。
  - MultiEdit・Write は止めない (1 回で file 全体を書く = 途中の形が出ない)。
  - 一覧が作れない・入力が壊れている → 何もしない (fail-open)。
env: LIVE_ENGINE_EDIT_GUARD_MODE=nudge (止めずに知らせるだけ)、 LIVE_ENGINE_EDIT_STATE_DIR (状態の dir)、
     LIVE_ENGINE_PATHS_ENGINE (engine の path、 test 用)。 一覧の cache の場所 = engine の LIVE_ENGINE_PATHS_CACHE
"""
import hashlib
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


def load_state(session):
    """{path: {"state": "released"} か {"state": "pending", "sig", "head", "fp"}}。 旧形式 (path の list) は released。"""
    try:
        with open(state_path(session), encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, list):
        return {p: {"state": "released"} for p in data}
    return data if isinstance(data, dict) else {}


def save_state(session, state):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = state_path(session) + ".{}.tmp".format(os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, state_path(session))
        cutoff = time.time() - KEEP_DAYS * 86400
        for name in os.listdir(STATE_DIR):
            p = os.path.join(STATE_DIR, name)
            if name.endswith(".json") and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except Exception:
        pass


def edit_sig(tool_input):
    """Edit の中身の指紋 (old_string・new_string・replace_all)。"""
    key = json.dumps([tool_input.get("old_string", ""), tool_input.get("new_string", ""),
                      bool(tool_input.get("replace_all", False))], ensure_ascii=False)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def file_fp(path):
    try:
        st = os.stat(path)
        return "{}:{}".format(st.st_mtime_ns, st.st_size)
    except OSError:
        return ""


def reason(path, caller):
    name = os.path.basename(path)
    return "\n".join([
        "🛑 live-engine-edit-guard: この file は hook か git の hook が作業 tree から直接読む (呼び元 = {})。".format(caller),
        "  Edit を何回にも分けると、 途中の形を同じ機械の別の session が走らせる (実測: 検査が異常終了して commit が素通りした)。",
        "  - 直すのが 1 か所だけ (この Edit の後で file が一貫した形になる) → 同じ Edit をもう一度打つ (この session のこの file は以後止めない)。",
        "    再送の前に来た同じ file への別の Edit は止める (同じ message に並べた 2 本目以降も)",
        "  - 2 か所以上 → 同じ dir の写し (例 `.{}.wip`) に Edit を重ね、 試してから `mv -f` で入れる (rename は原子的)。".format(name),
        "    1 回の Write で全文を置き換える形も、 途中の形が出ない",
        "  正本 = claude-config/conventions/hook-authoring.md#live-hook-edit-runs-elsewhere",
    ])


def reason_waiting(path, head):
    name = os.path.basename(path)
    return "\n".join([
        "🛑 live-engine-edit-guard: この file への先の Edit を止めていて、 その再送がまだ無い = 別の Edit は通さない。",
        "  止めた Edit の old_string の先頭: {!r}".format(head),
        "  - 直すのが止めた Edit の 1 か所だけ → その Edit を同じ中身で打ち直す (通ればこの file は以後止めない)",
        "  - 2 か所以上 → 同じ dir の写し (例 `.{}.wip`) に Edit を重ね、 試してから `mv -f` で入れる (file が変われば控えは消える)".format(name),
        "  正本 = claude-config/conventions/hook-authoring.md#live-hook-edit-runs-elsewhere",
    ])


def emit(text, deny):
    if deny:
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": text}}
    else:
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")


def run_hook():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if payload.get("tool_name") != "Edit":
        return 0
    tool_input = payload.get("tool_input") or {}
    path = str(tool_input.get("file_path") or "")
    if not path:
        return 0
    eng = load_engine()
    caller = eng.caller_of(path)
    if not caller:
        return 0
    real = os.path.realpath(path)
    session = str(payload.get("session_id") or "")
    state = load_state(session)
    cur = state.get(real) or {}
    nudge = os.environ.get("LIVE_ENGINE_EDIT_GUARD_MODE") == "nudge"
    sig, fp = edit_sig(tool_input), file_fp(real)
    if cur.get("state") == "released":
        return 0
    if cur.get("state") == "pending" and cur.get("fp") == fp:
        if cur.get("sig") == sig:
            state[real] = {"state": "released"}
            save_state(session, state)
            return 0
        emit(reason_waiting(real, cur.get("head", "")), deny=True)
        return 0
    # 初めて (または止めた後に file が別の手段で変わった): 止めて、 この Edit を控える
    if nudge:
        state[real] = {"state": "released"}
        save_state(session, state)
        emit(reason(real, caller), deny=False)
        return 0
    state[real] = {"state": "pending", "sig": sig, "fp": fp,
                   "head": str(tool_input.get("old_string", ""))[:60]}
    save_state(session, state)
    emit(reason(real, caller), deny=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run_hook())
    except Exception:
        sys.exit(0)
