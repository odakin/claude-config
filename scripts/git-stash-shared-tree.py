#!/usr/bin/env python3
"""git-stash-shared-tree.py — 未 commit の変更が居る作業 tree で git stash・--autostash を打つ Bash command を止める PreToolUse(Bash) の述語と本体 (find_issues(command) = 校正の道具が呼ぶ形、 --selftest)。 規約 = conventions/multi-session-coordination.md#autostash-foreign-wip

Why:
  同じ作業ディレクトリを複数の session が使うとき、 tree の未 commit の変更は他の session の作業でありうる。
  stash・autostash はそれを作業 tree から一時的に消して戻す = その間に相手が file を読み書きすると食い違い、
  戻すときに upstream の変更と重なれば相手の file の中で conflict する。 別の session から起こされた session の
  起動の文は stash を禁じているが、 文は書く瞬間に発火しない (実測: 起動の文に禁止があり、 pull は空振り =
  upstream に新しい commit が無いのに、 push の前の習慣で `git pull --rebase --autostash` を打ち、 他の session の
  未 commit の変更を退避して戻した。 衝突は無かった)。

止めるもの (heredoc の本文と quote の中身は見ない):
  - `git stash` / `git stash push|save|-u|-p …` (= 作業 tree から退避) — tree に未 commit の変更があるとき
  - `git pull|rebase|merge … --autostash`、 `git -c rebase.autoStash=true …` / `-c merge.autoStash=true …` — 同じ条件
  - `git config … rebase.autoStash|merge.autoStash true` — 同じ条件 (以後の pull が黙って退避する)
  - `git stash pop|apply|drop|clear|branch|store|create` — tree の状態によらず (stash の一覧は repo の全 session で共有 =
    他の session の stash を戻す・消す。 conventions/multi-session-coordination.md#stash-push-noop)
  通すもの: `git stash list|show`、 `--no-autostash`、 未 commit の変更が無い tree での退避 (退避するものが無い)、
  理由つきの `[stash-ok: <理由>]` を command に書いたもの (自分だけの変更だと確かめたとき)。
  tree の判定は `git status --porcelain --untracked-files=no` (`-u` / `-a` / `--include-untracked` / `--all` なら untracked も)。
  行き先の repo = `git -C <dir>` → 同じ command の前の `cd <dir>` → hook の cwd。 読めない行き先 (変数・$(…)) は止める側に倒す。

出力: permissionDecision=deny + 直し方 (push だけなら pull しない / ff の取り込み / origin から切った worktree)。
  読めない入力・想定外の例外は黙って通す (tool call を止めない)。 opt-out: CLAUDE_SHARED_TREE_STASH=0。
使い方:
  hook の入口から main() (stdin = PreToolUse の JSON)
  python3 git-stash-shared-tree.py --selftest
  calibrate-bash-command-pattern.py --hook scripts/git-stash-shared-tree.py   (find_issues を過去の Bash に当てる)
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?=\n|$)", re.S)
QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")
SEP = re.compile(r"&&|\|\||[;&|()\n]")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
LEADING = {"command", "builtin", "exec", "time", "nohup", "env", "then", "do", "else", "if", "while", "until", "!", "{"}
GIT_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
READ_ONLY_STASH = {"list", "show"}
SHARED_LIST_STASH = {"pop", "apply", "drop", "clear", "branch", "store", "create"}
STASH_SUBCOMMANDS = READ_ONLY_STASH | SHARED_LIST_STASH | {"push", "save"}
AUTOSTASH_KEY = re.compile(r"^(rebase|merge)\.autostash=(true|yes|on|1)?$", re.I)
TRUE_VALUES = {"true", "yes", "on", "1"}
BYPASS = re.compile(r"\[stash-ok:\s*[^\]\s][^\]]*\]")
OPT_OUT_ENV = "CLAUDE_SHARED_TREE_STASH"
ANCHOR = "claude-config/conventions/multi-session-coordination.md#autostash-foreign-wip"


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _segments(cmd: str) -> list[str]:
    masked = QUOTED.sub(_blank, HEREDOC.sub(_blank, cmd))
    out, start = [], 0
    for m in SEP.finditer(masked):
        out.append((start, m.start()))
        start = m.end()
    out.append((start, len(cmd)))
    return [cmd[a:b].strip() for a, b in out if masked[a:b].strip()]


def _words(seg: str) -> list[str]:
    try:
        words = shlex.split(seg, comments=True)
    except ValueError:
        words = seg.split()
    while words and (words[0] in LEADING or ASSIGN.match(words[0])):
        words = words[1:]
    return words


def _parse_git(words: list[str]):
    """(subcommand, 残りの語, -C の行き先, -c の値の list)。 git でなければ None。"""
    if not words or os.path.basename(words[0]) != "git":
        return None
    i, cdir, confs = 1, None, []
    while i < len(words):
        w = words[i]
        if w in GIT_OPT_WITH_ARG:
            arg = words[i + 1] if i + 1 < len(words) else ""
            if w == "-C":
                cdir = arg if cdir is None or os.path.isabs(arg) else os.path.join(cdir, arg)
            elif w == "-c":
                confs.append(arg)
            i += 2
            continue
        if w.startswith("-"):
            i += 1
            continue
        return w, words[i + 1:], cdir, confs
    return None


def _issues_in(words: list[str]) -> list[tuple[str, str | None, bool, bool]]:
    """(検出の名前, -C の行き先, 退避で untracked も含むか, tree の状態によらず止めるか) の list。"""
    parsed = _parse_git(words)
    if not parsed:
        return []
    sub, rest, cdir, confs = parsed
    out = []
    if sub == "stash":
        args = [w for w in rest if not w.startswith("-") and not re.match(r"^[0-9]*[<>]", w)]
        action = args[0] if args and args[0] in STASH_SUBCOMMANDS else "push"
        untracked = any(w in ("-u", "--include-untracked", "-a", "--all") for w in rest)
        if action in READ_ONLY_STASH:
            return []
        if action in SHARED_LIST_STASH:
            return [(f"git stash {action}", cdir, False, True)]
        return [(f"git stash {action if args and args[0] == action else ''}".rstrip(), cdir, untracked, False)]
    if sub in ("pull", "rebase", "merge"):
        if "--autostash" in rest:
            out.append((f"git {sub} --autostash", cdir, False, False))
        for c in confs:
            if AUTOSTASH_KEY.match(c):
                out.append((f"git -c {c.split('=')[0]}=true {sub}", cdir, False, False))
    if sub == "config":
        vals = [w for w in rest if not w.startswith("-")]
        if len(vals) >= 2 and re.fullmatch(r"(rebase|merge)\.autostash", vals[0], re.I) and vals[1].lower() in TRUE_VALUES:
            out.append((f"git config {vals[0]} {vals[1]}", cdir, False, False))
    return out


def find_issues(command: str) -> list[str]:
    """校正用の純粋な述語: 止める候補の形の名前の list (tree の状態は見ない)。"""
    names = []
    for seg in _segments(command):
        names += [name for name, _, _, _ in _issues_in(_words(seg))]
    return names


def _resolve(target: str | None, here: str | None) -> str | None:
    if target is None:
        return here
    if "$" in target or "`" in target or target == "-":
        return None
    t = os.path.expanduser(target)
    if not os.path.isabs(t):
        if here is None:
            return None
        t = os.path.join(here, t)
    return os.path.realpath(t)


def _dirty(repo: str, untracked: bool) -> list[str] | None:
    """未 commit の変更の path の list。 repo でなければ []、 読めなければ None。"""
    args = ["git", "-C", repo, "status", "--porcelain", "--untracked-files=" + ("normal" if untracked else "no")]
    try:
        r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=8)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return [] if "not a git repository" in r.stderr else None
    return [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]


def decide(command: str, cwd: str | None) -> str | None:
    """止める理由の本文か None。"""
    if BYPASS.search(command):
        return None
    here = os.path.realpath(cwd) if cwd else None
    reasons = []
    for seg in _segments(command):
        words = _words(seg)
        if words and words[0] in ("cd", "pushd"):
            here = _resolve(words[1] if len(words) > 1 else os.path.expanduser("~"), here)
            continue
        for name, cdir, untracked, always in _issues_in(words):
            repo = _resolve(cdir, here) if cdir is not None else here
            if always:
                reasons.append(f"`{name}` (stash の一覧は同じ repo の全 session で共有 = 他の session の stash を戻す・消しうる)")
                continue
            if repo is None:
                reasons.append(f"`{name}` (行き先の repo が読めない = 止める側に倒した)")
                continue
            dirty = _dirty(repo, untracked)
            if dirty is None:
                reasons.append(f"`{name}` ({repo} の状態が読めない = 止める側に倒した)")
            elif dirty:
                shown = ", ".join(dirty[:4]) + (f" ほか {len(dirty) - 4}" if len(dirty) > 4 else "")
                reasons.append(f"`{name}` ({repo} に未 commit の変更: {shown})")
    if not reasons:
        return None
    return (
        "[shared-tree-stash] " + " / ".join(reasons) + "。\n"
        "未 commit の変更は他の session の作業でありうる。 stash・autostash はそれを作業 tree から一時的に消して戻す "
        "(その間に相手が読み書きすると食い違い、 戻すときに upstream の変更と重なれば相手の file の中で conflict する)。 "
        "別の session から起こされた session の起動の文は stash を禁じている。\n"
        "直し方:\n"
        "  1. 自分の commit を出すだけなら pull しない: `git fetch` → `git rev-list --count HEAD..@{u}` が 0 なら `git push`\n"
        "  2. 遅れていて手元に未 push の commit が無い: `git merge --ff-only @{u}` (重ならない未 commit の変更はそのまま残る。 重なれば git が止める)\n"
        "  3. 遅れていて未 push の commit もある: `scripts/commit-from-origin-worktree.py` (origin から切った worktree で commit・push) か "
        "multi-session-coordination.md#merge-blocked-by-foreign-staged の手順\n"
        "  自分だけの変更だと確かめて退避が要るなら、 理由を command に `# [stash-ok: <理由>]` と書く。\n"
        "正本 = " + ANCHOR
    )


def hook(raw: str) -> str | None:
    if os.environ.get(OPT_OUT_ENV, "") == "0":
        return None
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return None
    if data.get("tool_name") != "Bash":
        return None
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if "stash" not in cmd.lower():
        return None
    reason = decide(cmd, data.get("cwd") or os.getcwd())
    if not reason:
        return None
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False)


def selftest() -> int:
    fails = 0

    def check(name: str, cond: bool) -> None:
        nonlocal fails
        print(("  ok   " if cond else "  FAIL ") + name)
        fails += 0 if cond else 1

    fi = find_issues
    check("pull --rebase --autostash", fi("git pull -q --rebase --autostash && git push -q") == ["git pull --autostash"])
    check("rebase / merge --autostash", fi("git fetch && git rebase --autostash @{u}") == ["git rebase --autostash"]
          and fi("git merge --autostash @{u}") == ["git merge --autostash"])
    check("bare stash and push forms", fi("git stash") == ["git stash"] and fi("git stash -u") == ["git stash"]
          and fi("git stash push -m x -- a.md") == ["git stash push"])
    check("list / show pass", fi("git stash list") == [] and fi("git stash show -p stash@{0}") == [])
    check("pop / drop / clear are found", fi("git stash pop") == ["git stash pop"] and fi("git stash drop stash@{1}") == ["git stash drop"]
          and fi("git stash clear") == ["git stash clear"])
    check("-c rebase.autoStash=true", fi("git -c rebase.autoStash=true pull --rebase") == ["git -c rebase.autoStash=true pull"])
    check("-c …=false and --no-autostash pass", fi("git -c rebase.autoStash=false pull") == []
          and fi("git pull --rebase --no-autostash") == [])
    check("config autostash true", fi("git config rebase.autostash true") == ["git config rebase.autostash true"]
          and fi("git config --global merge.autoStash false") == [])
    check("quoted message passes", fi('git commit -q -m "git stash してから pull --autostash" -- a.md') == [])
    check("heredoc body passes", fi("cat > m.txt <<'EOF'\ngit stash\ngit pull --autostash\nEOF\ngit commit -F m.txt") == [])
    check("git not at word 0 passes", fi("echo git stash && grep -n autostash x.md") == [])
    check("env prefix and -C", fi("GIT_TRACE=0 git -C ../repo stash") == ["git stash"])
    check("pathspec without push is a push", fi("git stash -- src/a.tex") == ["git stash"])
    check("redirection is not the action", fi("git stash 2>/dev/null") == ["git stash"] and fi("git stash list 2>&1") == [])

    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "r")
        os.makedirs(repo)
        run = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True)  # noqa: E731
        run("init", "-q")
        run("config", "user.email", "t@example.invalid")
        run("config", "user.name", "t")
        with open(os.path.join(repo, "a.md"), "w") as fh:
            fh.write("a\n")
        run("add", "a.md")
        run("commit", "-q", "-m", "init")
        check("clean tree: autostash passes", decide("git pull --rebase --autostash", repo) is None)
        check("clean tree: pop is still stopped", decide("git stash pop", repo) is not None)
        with open(os.path.join(repo, "untracked.md"), "w") as fh:
            fh.write("u\n")
        check("untracked only: plain stash passes", decide("git stash", repo) is None)
        check("untracked only: stash -u is stopped", decide("git stash -u", repo) is not None)
        with open(os.path.join(repo, "a.md"), "a") as fh:
            fh.write("b\n")
        r = decide("git pull -q --rebase --autostash && git push -q", repo)
        check("dirty tree: autostash is stopped with the path and the fixes", r is not None and "a.md" in r and "rev-list" in r)
        check("cd into the repo is followed", decide(f"cd {repo} && git stash", tmp) is not None
              and decide(f"cd {tmp} && git stash", repo) is None)
        check("-C into the repo is followed", decide(f"git -C {repo} stash", tmp) is not None)
        check("unreadable target is stopped", decide("cd $X && git stash", repo) is not None)
        check("bypass with a reason", decide("git stash  # [stash-ok: my own scratch edit]", repo) is None
              and decide("git stash  # [stash-ok: ]", repo) is not None)
        out = hook(json.dumps({"tool_name": "Bash", "cwd": repo, "tool_input": {"command": "git stash"}}))
        check("hook emits a PreToolUse deny", out is not None and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny")
        check("hook is silent for other tools and broken input", hook('{"tool_name":"Read"}') is None and hook("not json") is None)
        os.environ[OPT_OUT_ENV] = "0"
        check("opt-out", hook(json.dumps({"tool_name": "Bash", "cwd": repo, "tool_input": {"command": "git stash"}})) is None)
        del os.environ[OPT_OUT_ENV]
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    try:
        out = hook(sys.stdin.read())
    except Exception:  # never break the tool call
        return 0
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
