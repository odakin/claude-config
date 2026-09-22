#!/usr/bin/env python3
"""manuscript-claim-guard.py — PreToolUse(Edit|Write|MultiEdit|Bash): 原稿の保護領域 (表題・概要・序論・結論・数式) と agent の権限規約を、著者の項目ごとの承認なしに書き換える編集・commit を deny (engine = scripts/manuscript-claim-guard.py、 正本 = conventions/manuscript-claim-ownership.md)

# agent-authority:file

薄い adapter: event を engine の `hook claude` にそのまま渡す。 述語・承認・限界は engine と正本 doc が持つ。
engine が見つからない・例外 = 検査不能として deny。 git 側の最後の砦は scripts/pre-commit-bib と
scripts/public-precommit-runner.sh から呼ぶ同じ engine。

`--canary [--caller NAME]` = このマシンの本番配線 (settings.json の entry + install 済み hook + git pre-commit の
呼び出し) が、 合成の原稿で「概要の 1 文の削除」 を deny し「冠詞だけの修正」 を通すかを 1 行 (ARMED / NOT ARMED)
で返し、 その判定と時刻と呼び元を machine-local の state (canary-liveness.json) に書く。 hook は fail-open
なので、 配線切れは canary でしか見えない。 呼び元 = 個人層の run-all-checks (`--caller run-all-checks`) と
下の `--liveness`。

`--liveness [--max-age-hours H] [--silent-days D]` = SessionStart の面 (settings-entries.json で配線)。 state が
無い / H 時間 (既定 24) より古ければ canary を走らせ直し、 NOT ARMED と、 D 日 (既定 14) より長く報告の途絶えた
呼び元を 1 行ずつ出す。 健全なら沈黙、 exit は常に 0。 呼び元の script は canary の呼び出し行だけを
agent-authority の block で守る (= その file の他の行は普通に直せる)。 block の外側からの迂回 (手前の exit 0・
helper 関数の差し替え = canary が走らない / `|| true` = 失敗が消える) は止めずに、 ここで「報告が途絶えた」
「NOT ARMED」 として表に出す。 判断の記録と残る穴 = conventions/agent-rule-ownership.md#wiring-scope。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import runpy
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "scripts", "manuscript-claim-guard.py"))
if not os.path.isfile(ENGINE):
    ENGINE = os.path.expanduser("~/Claude/claude-config/scripts/manuscript-claim-guard.py")
HOOK_NAME = "manuscript-claim-guard.py"
STATE_FILE = "canary-liveness.json"
SESSION_CALLER = "session-start"


def state_path() -> str:
    base = os.environ.get("MANUSCRIPT_CLAIM_GUARD_STATE_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", "state", "manuscript-claim-guard")
    return os.path.join(base, STATE_FILE)


def load_state() -> dict | None:
    try:
        with open(state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def age_hours(stamp: object) -> float:
    """ISO 時刻からの経過 (時間)。 読めなければ無限大 (= 古い扱い)。"""
    try:
        when = datetime.datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return float("inf")
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds() / 3600


def record(armed: bool, detail: str, caller: str | None) -> bool:
    """判定・時刻・呼び元を state に書く。 書けなければ False (呼び元は表示だけ続ける)。"""
    state = load_state() or {}
    callers = state.get("callers") if isinstance(state.get("callers"), dict) else {}
    if caller:
        callers[caller] = now_iso()
    state.update({"v": 1, "armed": bool(armed), "detail": detail, "at": now_iso(),
                  "host": socket.gethostname(), "callers": callers})
    path = state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def probe() -> tuple[bool, str]:
    """本番配線を合成の原稿で確かめる。 (armed, 1 行の説明)。"""
    home = os.path.expanduser("~")
    settings = os.path.join(home, ".claude", "settings.json")
    try:
        with open(settings, encoding="utf-8") as fh:
            conf = json.load(fh)
    except (OSError, ValueError) as e:
        return False, f"settings.json が読めない: {e}"
    if conf.get("disableAllHooks") is True:
        return False, "settings.json に disableAllHooks: true"
    hook, wired = "", set()
    for ent in (conf.get("hooks") or {}).get("PreToolUse") or []:
        for h in ent.get("hooks") or []:
            c = h.get("command", "")
            if HOOK_NAME in c:
                hook = os.path.expanduser(c.split()[0].replace("~", home, 1))
                for t in ("Edit", "Write", "MultiEdit", "Bash"):
                    try:
                        if re.fullmatch(ent.get("matcher", ""), t):
                            wired.add(t)
                    except re.error:
                        pass
    missing = {"Edit", "Write", "MultiEdit", "Bash"} - wired
    if missing:
        return False, (f"settings.json の PreToolUse に {'/'.join(sorted(missing))} の entry が無い"
                       " → claude-config/scripts/sync-hook-settings.sh")
    if not (os.path.isfile(hook) and os.access(hook, os.X_OK)):
        return False, f"install 済み hook が無い / 実行不可: {hook}"
    precommit = os.path.join(os.path.dirname(ENGINE), "pre-commit-bib")
    try:
        git_wired = "manuscript-claim-guard.py" in open(precommit, encoding="utf-8").read()
    except OSError:
        git_wired = False
    if not git_wired:
        return False, "scripts/pre-commit-bib が engine を呼んでいない"
    with tempfile.TemporaryDirectory() as td:
        repo = os.path.join(td, "paper")
        os.makedirs(os.path.join(repo, "src"))
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   MANUSCRIPT_CLAIM_GUARD_STATE_DIR=os.path.join(td, "state"))
        subprocess.run(["git", "init", "-q", repo], env=env, capture_output=True, check=False)
        tex = os.path.join(repo, "src", "main.tex")
        with open(tex, "w", encoding="utf-8") as fh:
            fh.write("\\title{Canary}\n\\begin{abstract}\nClaim one holds. Claim two holds.\n\\end{abstract}\n")

        def decide(old: str, new: str) -> bool:
            data = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": "canary-0",
                               "cwd": repo, "tool_input": {"file_path": tex, "old_string": old, "new_string": new}})
            try:
                p = subprocess.run([hook], input=data, capture_output=True, text=True, timeout=30, env=env)
            except (OSError, subprocess.TimeoutExpired):
                return False
            return '"permissionDecision": "deny"' in p.stdout

        bad = []
        if not decide(" Claim two holds.", ""):
            bad.append("概要の 1 文の削除が deny されない")
        if decide("Claim one holds.", "The claim one holds."):
            bad.append("冠詞だけの修正が deny される")
    if bad:
        return False, " / ".join(bad)
    return True, ("settings の Edit/Write/MultiEdit/Bash + install 済み hook が合成原稿の概要の削除を deny し、"
                  " 冠詞の修正を通す。 git 側 = pre-commit-bib が engine を呼ぶ")


def canary(caller: str | None) -> int:
    armed, detail = probe()
    record(armed, detail, caller)
    print(("ARMED" if armed else "NOT ARMED") + f": manuscript-claim-guard ({detail})")
    return 0 if armed else 1


def liveness(max_age_hours: float, silent_days: float) -> int:
    state = load_state()
    if state is None or age_hours(state.get("at")) > max_age_hours:
        armed, detail = probe()
        record(armed, detail, SESSION_CALLER)
        state = load_state()
    lines = []
    if state is None:
        lines.append("🔴 manuscript-claim-guard: canary の記録が書けない (" + os.path.dirname(state_path()) + ")。"
                     " 配線の確認 = python3 ~/Claude/claude-config/hooks/manuscript-claim-guard.py --canary")
    else:
        if not state.get("armed"):
            lines.append(f"🔴 manuscript-claim-guard: NOT ARMED — {state.get('detail', '')} (確認 {str(state.get('at', ''))[:16]})。"
                         " 直す = claude-config/scripts/sync-hook-settings.sh、 正本 = conventions/manuscript-claim-ownership.md#adoption")
        callers = state.get("callers") if isinstance(state.get("callers"), dict) else {}
        for caller, stamp in sorted(callers.items()):
            if caller == SESSION_CALLER:
                continue
            days = age_hours(stamp) / 24
            if days > silent_days:
                shown = "不明" if days == float("inf") else f"{days:.0f} 日"
                lines.append(f"🟡 manuscript-claim-guard: {caller} からの canary の報告が {shown} 無い (最後 = {str(stamp)[:10]})。"
                             " その呼び出しが外れたか、 手前で止まっている (呼び元 script の agent-authority block の外側を見る:"
                             " conventions/agent-rule-ownership.md#wiring-scope)")
    if lines:
        print("\n".join(lines))
    return 0


def main(argv: list[str]) -> int:
    if "--canary" in argv:
        caller = argv[argv.index("--caller") + 1] if "--caller" in argv and argv.index("--caller") + 1 < len(argv) else None
        return canary(caller)
    if "--liveness" in argv:
        # SessionStart の入力 (JSON) は使わないが読み切る = 書き手が EPIPE になって stdout ごと落とされないため
        try:
            if not sys.stdin.isatty():
                sys.stdin.read()
        except (OSError, ValueError):
            pass

        def num(flag: str, default: float) -> float:
            if flag in argv and argv.index(flag) + 1 < len(argv):
                try:
                    return float(argv[argv.index(flag) + 1])
                except ValueError:
                    return default
            return default
        return liveness(num("--max-age-hours", 24.0), num("--silent-days", 14.0))
    if not os.path.isfile(ENGINE):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "manuscript-claim-guard: inspection unavailable (missing engine); repair and retry."}}))
        return 0
    sys.argv = [ENGINE, "hook", "claude"]
    sys.dont_write_bytecode = True
    try:
        runpy.run_path(ENGINE, run_name="__main__")
    except (SystemExit, Exception) as exc:
        if not isinstance(exc, SystemExit) or exc.code not in (None, 0):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": "manuscript-claim-guard: inspection unavailable (engine failure); repair and retry."}}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
