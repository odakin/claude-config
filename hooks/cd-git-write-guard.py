#!/usr/bin/env python3
"""cd-git-write-guard.py — PreToolUse(Bash): 別の dir への cd と git commit / push を 1 つの command に入れた形 (と git -C … commit / push) を止め、 cd を単独の 1 回に分けて打ち直させる (conventions/claude-code-permissions.md#cd-with-git-goes-to-classifier)。

Why:
  Claude Code は compound command を部分ごとに allow rule と照合するが、 **cd で別の dir に移って
  同じ command の中で git を実行する形は、 各部分が rule に当たっても確認に回す** (移った先の
  git hook が動きうるため。 公式 docs `permissions` の Read-only commands の節)。 auto mode では
  その確認を classifier が担うので、 `Bash(git commit:*)` / `Bash(git push *)` を allow に入れていても、
  `cd <repo> && git add … && git commit … && git push` は毎回 classifier の判定になり、 文脈しだいで
  止められる (実測 = 記録を残すだけの commit と push が、 commit message の文脈から「実世界の取引」 と判定されて止まった)。
  `git -C <dir> commit` も先頭が `git commit` でないので rule に当たらず、 同じく classifier に回る。

  Bash tool の作業ディレクトリは次の呼び出しに引き継がれるので、 **cd だけを 1 回打ち、 次の呼び出しで
  git を cd も -C も付けずに打てば**、 各部分が allow rule に当たって classifier を通らない。
  これは危険だから止める gate ではなく、 同じ結果を rule に当たる形で打ち直させる誘導
  (= 止められて user の承認を待つ時間を消すのが目的。 long-bash-command-guard.sh と同じ型)。

述語:
  - heredoc の本文と quote の中身は見ない (commit message に cd や && が書いてあっても当たらない)
  - command を ; && || | & ( ) 改行 で部分に割り、 先頭の制御語・変数代入を外して最初の語を見る
  - cd / pushd の行き先を、 その時点の dir から解決する (~ / $HOME / 相対 path)。 行き先が
    読めない (cd - / $(…) / 未知の変数) なら「別の dir」 とみなす
  - 別の dir に移った後の部分に git commit / git push があれば止める
  - cd が無くても git -C <dir> commit / push は止める (rule に当たらない形)
  - git の大域 option (-c k=v / --git-dir=… / --no-pager 等) は飛ばして subcommand を見る
  - 行き先が今の dir と同じ cd (= 何もしない cd) は止めない

出力: permissionDecision=deny + 直し方。 誤検出のコストは打ち直し 1 回。 fail-open (読めない入力は黙って通す)。
opt-out: CLAUDE_CD_GIT_GUARD=0 (escape-hatch-guard.py の対象 = 本人の承認が要る)。
self-test: python3 hooks/cd-git-write-guard.py --selftest / bash hooks/cd-git-write-guard.test.sh
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SEP = re.compile(r"&&|\|\||;|\||&|\(|\)|\n")
LEADING_KW = {"do", "then", "else", "elif", "if", "while", "until", "{", "!", "time", "command", "builtin"}
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
GIT_WRITE = {"commit", "push"}
# 値を次の語に取る git の大域 option
GIT_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}

FIX = (
    "直し方 (同じ結果を allow rule に当たる形で):\n"
    "  1. `cd <repo>` だけを 1 回の Bash で打つ (作業ディレクトリは次の呼び出しに引き継がれる)\n"
    "  2. 次の Bash で `git add <新規> && git commit -q -m \"…\" -- <paths>` と `git push` を、 cd も -C も付けずに打つ\n"
    "     (git 同士の && は各部分が rule に当たるので構わない。 fetch や rev-list の確認も同じ呼び出しに入れてよい)\n"
    "行き先が今の作業ディレクトリと同じなら、 cd を消すだけでよい。\n"
    "subagent (Agent tool の子) では単独の cd が次の呼び出しに残らない = scripts/commit-from-origin-worktree.py で commit・push する (claude-code-permissions.md#subagent-commit-route)。\n"
    "正本 = claude-config/conventions/claude-code-permissions.md#cd-with-git-goes-to-classifier"
)


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _masked(cmd: str) -> str:
    """heredoc の本文と quote の中身を同じ長さの空白にする (位置を保ったまま区切りの対象から外す)。"""
    return QUOTED.sub(_blank, HEREDOC.sub(_blank, cmd))


def _segments(cmd: str) -> list[str]:
    """区切りで割った部分を、 元の文字列 (quote を保ったまま) で返す。 heredoc の本文は捨てる。"""
    masked = _masked(cmd)
    out, start = [], 0
    for m in SEP.finditer(masked):
        out.append((start, m.start()))
        start = m.end()
    out.append((start, len(cmd)))
    segs = []
    for a, b in out:
        if not masked[a:b].strip():
            continue  # heredoc の本文だけの部分 (masked では空白) は見ない
        segs.append(cmd[a:b].strip())
    return segs


def _words(seg: str) -> list[str]:
    try:
        words = shlex.split(seg, comments=True)
    except ValueError:
        words = seg.split()
    while words and (words[0] in LEADING_KW or ASSIGN.match(words[0])):
        words = words[1:]
    return words


def _resolve(target: str | None, here: str | None, home: str) -> str | None:
    """cd の行き先を絶対 path に。 読めなければ None (= 別の dir とみなす)。"""
    if target is None or target == "":
        return home
    if target == "-" or "$(" in target or "`" in target:
        return None
    t = target.replace("${HOME}", home).replace("$HOME", home)
    if t == "~" or t.startswith("~/"):
        t = home + t[1:]
    if "$" in t or t.startswith("~"):
        return None
    if not os.path.isabs(t):
        if here is None:
            return None
        t = os.path.join(here, t)
    return os.path.realpath(t)


def _git_sub(words: list[str]) -> tuple[str | None, bool]:
    """(subcommand, -C が在ったか)。 git でなければ (None, False)。"""
    if not words or os.path.basename(words[0]) != "git":
        return None, False
    i, has_c = 1, False
    while i < len(words):
        w = words[i]
        if w in GIT_OPT_WITH_ARG:
            has_c = has_c or w == "-C"
            i += 2
            continue
        if w.startswith("-"):
            i += 1
            continue
        return w, has_c
    return None, has_c


def find_issue(cmd: str, cwd: str | None, home: str) -> str | None:
    """止める理由 (1 行) か None。"""
    start = os.path.realpath(cwd) if cwd else None
    here = start
    moved = None  # 別の dir に移った cd の表記
    for seg in _segments(cmd):
        words = _words(seg)
        if not words:
            continue
        head = words[0]
        if head in ("cd", "pushd"):
            arg = next((w for w in words[1:] if not w.startswith("-") or w == "-"), None)
            dest = _resolve(arg, here, home)
            here = dest
            if dest is None or start is None or dest != start:
                moved = " ".join(words[:2])
            else:
                moved = None
            continue
        sub, has_c = _git_sub(words)
        if sub in GIT_WRITE:
            if moved:
                return f"`{moved}` の後に `git {sub}` (= 別の dir への cd と git を 1 つの command に入れた形)"
            if has_c:
                return f"`git -C … {sub}` (= 先頭が `git {sub}` でないので allow rule に当たらない形)"
    return None


def reason_text(issue: str) -> str:
    return (
        "[cd-git-write-guard] " + issue + "。\n"
        "この形は `Bash(git commit:*)` / `Bash(git push *)` を allow に入れていても rule に当たらず、 "
        "auto mode では classifier の判定に回って止められることがある "
        "(cd で移った先の git hook が動きうるため = 公式 docs permissions の Read-only commands の節)。\n" + FIX
    )


def main() -> int:
    if os.environ.get("CLAUDE_CD_GIT_GUARD", "") == "0":
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if "git" not in cmd:
        return 0
    try:
        issue = find_issue(cmd, data.get("cwd") or os.getcwd(), os.path.expanduser("~"))
    except Exception:  # fail-open
        return 0
    if not issue:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason_text(issue),
    }}, ensure_ascii=False))
    return 0


def selftest() -> int:
    fails = 0
    home = "/home/u"
    cwd = "/home/u/Claude"

    def check(cmd: str, want: bool, label: str, here: str | None = cwd) -> None:
        nonlocal fails
        got = find_issue(cmd, here, home)
        ok = bool(got) == want
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got!r})"))
        fails += 0 if ok else 1

    # 止める (実例と同形)
    check('cd ~/Claude/repo && git add d.txt && git commit -q -m "m" -- a b && git push -q && git log -1',
          True, "cd → add → commit → push の連結")
    check("cd ~/Claude/repo && git fetch -q && git rev-list --count HEAD..@{u} && git push -q",
          True, "cd → push")
    check("cd ../other; git commit -m x", True, "相対 path の cd と ; 区切り")
    check("(cd /tmp/x && git push)", True, "subshell の中")
    check("cd - && git push", True, "cd - (行き先が読めない)")
    check('cd "$(git rev-parse --show-toplevel)" && git commit -m x', True, "$(…) の行き先")
    check("git -C /home/u/Claude/repo commit -m x", True, "git -C … commit")
    check("git -C /home/u/Claude/repo push", True, "git -C … push")
    check("cd ~/Claude/r && GIT_EDITOR=true git commit --amend", True, "変数代入つきの git")
    check("cd ~/Claude/r && git -c user.name=x commit -m y", True, "大域 option -c の後の commit")
    # 止めない
    check('git add d.txt && git commit -q -m "m" -- a b && git push -q', False, "cd なしの git 連結")
    check("cd ~/Claude && git commit -m x", False, "行き先が今の dir と同じ cd")
    check("cd . && git push", False, "cd . (何もしない)")
    check("cd ~/Claude/r && git log -1 && git status", False, "cd の後が読み取りの git だけ")
    check("cd ~/Claude/r", False, "cd だけ")
    check("git -C /home/u/Claude/r log -1", False, "git -C の読み取り")
    check('git commit -m "cd ~/x && git push"', False, "commit message の中の cd と push")
    check("git commit -F - <<'EOF'\ncd ~/x\ngit push\nEOF", False, "heredoc の本文")
    check("grep -n 'cd .* && git commit' hooks/x.py", False, "quote の中の pattern")
    check("echo cd; echo git push", False, "echo の引数")
    check("cd ~/Claude/r && python3 x.py push", False, "git 以外の push")
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
