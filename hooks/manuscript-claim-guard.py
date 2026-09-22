#!/usr/bin/env python3
"""manuscript-claim-guard.py — PreToolUse(Edit|Write|MultiEdit|Bash): 原稿の保護領域 (表題・概要・序論・結論・数式) と agent の権限規約を、著者の項目ごとの承認なしに書き換える編集・commit を deny (engine = scripts/manuscript-claim-guard.py、 正本 = conventions/manuscript-claim-ownership.md)

# agent-authority:file

薄い adapter: event を engine の `hook claude` にそのまま渡す。 述語・承認・限界は engine と正本 doc が持つ。
engine が見つからない・例外 = 検査不能として deny。 git 側の最後の砦は scripts/pre-commit-bib と
scripts/public-precommit-runner.sh から呼ぶ同じ engine。

`--canary` = このマシンの本番配線 (settings.json の entry + install 済み hook + git pre-commit の呼び出し) が、
合成の原稿で「概要の 1 文の削除」 を deny し「冠詞だけの修正」 を通すかを 1 行 (ARMED / NOT ARMED) で返す。
hook は fail-open なので、 配線切れは canary でしか見えない。 呼び元 = 個人層の run-all-checks。
"""
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "scripts", "manuscript-claim-guard.py"))
if not os.path.isfile(ENGINE):
    ENGINE = os.path.expanduser("~/Claude/claude-config/scripts/manuscript-claim-guard.py")
HOOK_NAME = "manuscript-claim-guard.py"


def canary() -> int:
    home = os.path.expanduser("~")
    settings = os.path.join(home, ".claude", "settings.json")
    try:
        with open(settings, encoding="utf-8") as fh:
            conf = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"NOT ARMED: manuscript-claim-guard (settings.json が読めない: {e})")
        return 1
    if conf.get("disableAllHooks") is True:
        print("NOT ARMED: manuscript-claim-guard (settings.json に disableAllHooks: true)")
        return 1
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
        print(f"NOT ARMED: manuscript-claim-guard (settings.json の PreToolUse に {'/'.join(sorted(missing))} の entry が無い"
              " → claude-config/scripts/sync-hook-settings.sh)")
        return 1
    if not (os.path.isfile(hook) and os.access(hook, os.X_OK)):
        print(f"NOT ARMED: manuscript-claim-guard (install 済み hook が無い / 実行不可: {hook})")
        return 1
    precommit = os.path.join(os.path.dirname(ENGINE), "pre-commit-bib")
    try:
        git_wired = "manuscript-claim-guard.py" in open(precommit, encoding="utf-8").read()
    except OSError:
        git_wired = False
    if not git_wired:
        print("NOT ARMED: manuscript-claim-guard (scripts/pre-commit-bib が engine を呼んでいない)")
        return 1
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
        print("NOT ARMED: manuscript-claim-guard (" + " / ".join(bad) + ")")
        return 1
    print("ARMED: manuscript-claim-guard (settings の Edit/Write/MultiEdit/Bash + install 済み hook が合成原稿の概要の削除を"
          " deny し、 冠詞の修正を通す。 git 側 = pre-commit-bib が engine を呼ぶ)")
    return 0


if __name__ == "__main__":
    if "--canary" in sys.argv[1:]:
        sys.exit(canary())
    if not os.path.isfile(ENGINE):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "manuscript-claim-guard: inspection unavailable (missing engine); repair and retry."}}))
        sys.exit(0)
    sys.argv = [ENGINE, "hook", "claude"]
    sys.dont_write_bytecode = True
    try:
        runpy.run_path(ENGINE, run_name="__main__")
    except (SystemExit, Exception) as exc:
        if not isinstance(exc, SystemExit) or exc.code not in (None, 0):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": "manuscript-claim-guard: inspection unavailable (engine failure); repair and retry."}}))
    sys.exit(0)
