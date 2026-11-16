#!/usr/bin/env python3
"""git-write-landed-check.py — Bash で打った git commit / git push が実際に入ったかを、 走った後に確かめる。

呼び手 = hooks/git-state-nudge.sh (PostToolUse Bash)。 command に commit か push の語がある時だけ、 hook の
stdin JSON をそのまま本 file の stdin に渡す。 本 file は窓に返す文 (1 件 1 行) を stdout に出し、 何も無ければ
何も出さない。 JSON に包んで additionalContext にするのは呼び手 (git-state-nudge.sh)。

見るもの (正本 = 本 file の冒頭):
  - `git … commit … -- <path>…` (path を名指した commit): 走った後もその path が変更のまま (`git status
    --porcelain -- <path>`) なら「commit が入っていない」。 名指した dir の下の未追跡の file は数えない
    (pathspec の commit は未追跡を入れないので、 入らなくて当然)。 名指した file そのものが未追跡のままなら数える。
  - path を名指さない commit: index に残り (`git diff --cached`) があれば数える。 `-a` / `--all` なら追跡中の
    file の変更 (`git diff`) も数える。
  - `git … push`: 走った後に upstream より先の commit (`git rev-list --count @{u}..HEAD`) が残っていれば
    「push が終わっていない」。 upstream の無い branch・別の remote や refspec を名指した push・--dry-run は見ない。
見ないもの: 名指していない file・並列の窓の変更 (Stop の網 session-commit-nudge.sh の誤報の元)・読むだけの
command の出力の絞り方 (止めると窓の文脈が溢れる)。 変数・command 置換を含む path (`"$r"` など) は解けないので
見ない (黙る)。 相対の cd の後の -C の無い git も見ない (hook の cwd が cd の前か後か分からない)。 同じ command の
中で後から同じ repo に index か HEAD を動かす git を打っていれば、 前の commit は見ない (後の状態を前の commit の
結果と読めない)。 push も同じ repo で後に commit などがあれば見ない。

鳴った path は session ごとの印 (<state>/<session_id>.landed-flagged、 1 行 = 「repo の root<TAB>repo からの path」)
に書く。 Stop の網 (session-commit-nudge.sh nudge) はその path を同じ turn の数から外し、 読んだら印を消す
(二重に鳴らさない)。 state = $SESSION_TOUCH_STATE_DIR か ~/.claude/state/session-touch/ (Stop の網と同じ)。

試験: python3 hooks/git-write-landed-check.py --selftest (一時の repo を作って確かめる)。
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

SEPARATOR_CHARS = set(";&|\n()")
# index か HEAD を動かす git の subcommand (後に在れば前の commit を見ない)
STATE_MOVERS = {"add", "rm", "mv", "reset", "restore", "stash", "checkout", "switch", "apply", "am",
                "cherry-pick", "merge", "rebase", "revert", "pull", "commit", "update-index", "read-tree"}
PUSH_BLOCKERS = {"commit", "push", "reset", "rebase", "pull", "merge", "cherry-pick", "revert", "am"}
COMMIT_VALUE_OPTS = {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message",
                     "--author", "--date", "-t", "--template", "--fixup", "--squash", "--cleanup",
                     "--trailer", "-u", "--untracked-files"}
COMMIT_SKIP_FLAGS = {"--dry-run", "-p", "--patch", "--interactive", "--pathspec-from-file"}
PUSH_SKIP_FLAGS = {"--dry-run", "-n", "--tags", "--delete", "-d", "--mirror", "--all", "--prune"}
PUSH_VALUE_OPTS = {"--repo", "--receive-pack", "--exec", "--push-option", "-o"}
GIT_VALUE_OPTS = {"-c", "--namespace", "--exec-path", "--config-env"}
DYNAMIC = re.compile(r"[$`*?]")
WORD = re.compile(r"\b(commit|push)\b")


def tokens(command: str) -> list[str] | None:
    """shell の語に割る (引用を外す・区切りを 1 語に)。 割れなければ None (= 黙る)。"""
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.commenters = ""
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        return None


def segments(toks: list[str]) -> list[list[str]]:
    """区切り (; && || | & 改行 括弧) で割り、 redirect (2>&1・>/dev/null) の語を落とす。"""
    out: list[list[str]] = []
    cur: list[str] = []
    skip_next = False
    for t in toks:
        if skip_next:
            skip_next = False
            continue
        if t and set(t) <= SEPARATOR_CHARS:
            if cur:
                out.append(cur)
            cur = []
            continue
        if t and set(t) <= set("<>&"):
            # 直前の fd の数字 (2>&1 の 2) と、 行き先の語 (1・/dev/null) を落とす
            if cur and cur[-1].isdigit():
                cur.pop()
            skip_next = True
            continue
        cur.append(t)
    if cur:
        out.append(cur)
    return out


def expand(path: str) -> Path:
    if path == "~" or path.startswith("~/"):
        path = str(Path.home()) + path[1:]
    return Path(path)


def parse_git(seg: list[str]) -> tuple[list[str], str, list[str]] | None:
    """('-C' の path の並び, subcommand, その引数) か None。 先頭の VAR=x・command・env は飛ばす。"""
    i = 0
    while i < len(seg) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]) or seg[i] in ("command", "env", "exec")):
        i += 1
    if i >= len(seg) or not (seg[i] == "git" or seg[i].endswith("/git")):
        return None
    i += 1
    cdirs: list[str] = []
    while i < len(seg):
        t = seg[i]
        if t == "-C" and i + 1 < len(seg):
            cdirs.append(seg[i + 1])
            i += 2
        elif t in ("--git-dir", "--work-tree") or t.startswith("--git-dir=") or t.startswith("--work-tree="):
            return None  # 作業 tree を別に名指す形は見ない
        elif t in GIT_VALUE_OPTS and i + 1 < len(seg):
            i += 2
        elif t.startswith("-"):
            i += 1
        else:
            return cdirs, t, seg[i + 1:]
    return None


def parse_commit(args: list[str]) -> dict | None:
    """{'paths': [...], 'all': bool} か None (見ない形)。"""
    paths: list[str] = []
    all_flag = False
    i = 0
    while i < len(args):
        t = args[i]
        if t == "--":
            paths.extend(args[i + 1:])
            break
        if t in COMMIT_SKIP_FLAGS or t.startswith("--pathspec-from-file="):
            return None
        if t in ("-a", "--all"):
            all_flag = True
        elif t in COMMIT_VALUE_OPTS:
            i += 1
        elif t.startswith("--"):
            pass
        elif t.startswith("-") and len(t) > 1:
            short = t[1:]
            if re.fullmatch(r"[a-zA-Z]+", short):
                # 束ねた短い flag (-qam "msg" など)。 値を取る文字 (m F C c t) が出たら、 その後ろの文字が値
                # (-mMSG)、 最後の文字なら次の語が値
                for k, ch in enumerate(short):
                    if ch == "a":
                        all_flag = True
                    if ch in "mFCct":
                        if k == len(short) - 1:
                            i += 1
                        break
        else:
            paths.append(t)
        i += 1
    return {"paths": paths, "all": all_flag}


def parse_push(args: list[str]) -> dict | None:
    pos: list[str] = []
    i = 0
    while i < len(args):
        t = args[i]
        if t in PUSH_SKIP_FLAGS or t.startswith("--delete=") or t.startswith("--repo="):
            return None
        if t in PUSH_VALUE_OPTS:
            i += 2
            continue
        if not t.startswith("-"):
            pos.append(t)
        i += 1
    return {"remote": pos[0] if pos else None, "refspecs": pos[1:]}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None


def out(repo: Path, *args: str) -> str | None:
    r = git(repo, *args)
    return r.stdout if r is not None and r.returncode == 0 else None


def porcelain_entries(repo: Path, paths: list[str]) -> list[tuple[str, str]]:
    r = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    if r is None or r.returncode != 0:
        return []
    items = r.stdout.split("\0")
    entries: list[tuple[str, str]] = []
    k = 0
    while k < len(items):
        e = items[k]
        if len(e) < 4:
            k += 1
            continue
        xy, p = e[:2], e[3:]
        entries.append((xy, p))
        k += 2 if xy[0] in "RC" else 1  # rename / copy は元の path が次に続く
    return entries


def named_paths(paths: list[str], prefix: str, top: str) -> set[str]:
    named = set()
    for p in paths:
        if p.startswith("/"):
            named.add(os.path.normpath(os.path.relpath(p, top)))
        else:
            named.add(os.path.normpath(prefix + p))
    return named


def check_commit(repo_dir: Path, spec: dict) -> list[str]:
    """入っていない path (repo の root から) の並び。"""
    top = out(repo_dir, "rev-parse", "--show-toplevel")
    if top is None:
        return []
    prefix = (out(repo_dir, "rev-parse", "--show-prefix") or "").strip()
    if spec["paths"]:
        named = named_paths(spec["paths"], prefix, top.strip())
        missing = []
        for xy, p in porcelain_entries(repo_dir, spec["paths"]):
            if xy == "!!":
                continue
            if xy == "??" and os.path.normpath(p) not in named:
                continue
            missing.append(p)
        return missing
    left = (out(repo_dir, "diff", "--cached", "--name-only") or "").splitlines()
    if spec["all"]:
        left += (out(repo_dir, "diff", "--name-only") or "").splitlines()
    return sorted({x for x in left if x})


def check_push(repo_dir: Path, spec: dict) -> tuple[int, int] | None:
    """(upstream より先の数, upstream の方が先の数) か None (見ない)。"""
    up = out(repo_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up is None:
        return None
    up = up.strip()
    up_remote, _, up_branch = up.partition("/")
    if spec["remote"] and spec["remote"] != up_remote:
        return None
    if spec["refspecs"]:
        branch = (out(repo_dir, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
        ok = {branch, "HEAD", f"HEAD:{up_branch}", f"{branch}:{up_branch}", f"HEAD:refs/heads/{up_branch}",
              f"{branch}:refs/heads/{up_branch}"}
        if any(r.lstrip("+") not in ok for r in spec["refspecs"]):
            return None
    ahead = out(repo_dir, "rev-list", "--count", f"{up}..HEAD")
    behind = out(repo_dir, "rev-list", "--count", f"HEAD..{up}")
    if ahead is None:
        return None
    return int(ahead.strip() or 0), int((behind or "0").strip() or 0)


def repo_root(d: Path) -> str | None:
    if not d.is_dir():
        return None
    top = out(d, "rev-parse", "--show-toplevel")
    return top.strip() if top else None


def plan(command: str, cwd: Path) -> list[tuple[str, Path, dict, str]]:
    """[(commit|push, repo の dir, spec, repo の root)] のうち、 同じ command の後の git に上書きされない分。"""
    toks = tokens(command)
    if toks is None:
        return []
    base: Path | None = cwd
    ops: list[tuple[str, Path | None, dict | None, str | None]] = []
    for seg in segments(toks):
        if seg[0] in ("cd", "pushd") and len(seg) >= 2:
            arg = seg[1]
            if DYNAMIC.search(arg) or not (arg.startswith("/") or arg.startswith("~")):
                base = None  # 相対の cd = 以後の -C の無い git は見ない
            else:
                base = expand(arg)
            continue
        g = parse_git(seg)
        if g is None:
            continue
        cdirs, sub, args = g
        d: Path | None = base
        if any(DYNAMIC.search(c) for c in cdirs):
            d = None
        else:
            for c in cdirs:
                if c.startswith("/") or c.startswith("~"):
                    d = expand(c)
                elif d is not None:
                    d = d / c
        spec = None
        if sub == "commit":
            spec = parse_commit(args)
            if spec is not None and any(DYNAMIC.search(p) for p in spec["paths"]):
                spec = None
        elif sub == "push":
            spec = parse_push(args)
        root = repo_root(d) if (d is not None and (sub in STATE_MOVERS or sub == "push")) else None
        ops.append((sub, d, spec, root))
    result = []
    for k, (sub, d, spec, root) in enumerate(ops):
        if sub not in ("commit", "push") or spec is None or d is None or root is None:
            continue
        # 後の git: 同じ repo、 または repo が解けない (変数の -C など) ものは同じ repo かもしれないと読む
        later = [o[0] for o in ops[k + 1:] if o[3] == root or o[3] is None]
        if sub == "commit" and any(s in STATE_MOVERS for s in later):
            continue
        if sub == "push" and any(s in PUSH_BLOCKERS for s in later):
            continue
        result.append((sub, d, spec, root))
    return result


def state_dir() -> Path:
    return Path(os.environ.get("SESSION_TOUCH_STATE_DIR") or Path.home() / ".claude/state/session-touch")


def short(root: str) -> str:
    return os.path.basename(root.rstrip("/")) or root


def run(payload: dict) -> tuple[list[str], list[tuple[str, str]]]:
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not WORD.search(command):
        return [], []
    cwd = Path(payload.get("cwd") or os.getcwd())
    lines: list[str] = []
    flagged: list[tuple[str, str]] = []
    for sub, d, spec, root in plan(command, cwd):
        if sub == "commit":
            missing = check_commit(d, spec)
            if missing:
                shown = ", ".join(missing[:5]) + (f" ほか {len(missing) - 5} file" if len(missing) > 5 else "")
                what = "名指した file が" if spec["paths"] else ("追跡中の変更が" if spec["all"] else "index に")
                lines.append(f"⚠️ commit が入っていない: {short(root)} の {shown} ({what}まだ残る)。"
                             f" 出力を絞らずに git -C {root} status を読み、 commit を打ち直す")
                flagged += [(root, p) for p in missing]
        else:
            res = check_push(d, spec)
            if res and res[0] > 0:
                ahead, behind = res
                extra = f"、 upstream の方が {behind} commit 先 = 取り込んでから push" if behind else ""
                lines.append(f"⚠️ push が終わっていない: {short(root)} (upstream より {ahead} commit 先{extra})。"
                             f" 出力を絞らずに push を打ち直す")
    return lines, flagged


def record_flagged(session_id: str, flagged: list[tuple[str, str]]) -> None:
    if not session_id or not flagged or not re.fullmatch(r"[A-Za-z0-9._-]+", session_id):
        return
    try:
        d = state_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{session_id}.landed-flagged", "a", encoding="utf-8") as f:
            for root, p in flagged:
                f.write(f"{root}\t{p}\n")
    except OSError:
        pass


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        lines, flagged = run(payload)
    except Exception:  # noqa: BLE001 — hook は窓を止めない
        return 0
    if lines:
        record_flagged(str(payload.get("session_id") or ""), flagged)
        print("\n".join(lines))
    return 0


# ---------------------------------------------------------------- selftest
def selftest() -> int:
    fails: list[str] = []
    n = 0

    def check(name: str, cond: bool) -> None:
        nonlocal n
        n += 1
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp).resolve()
        ident = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "noreply@anthropic.com",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        os.environ.update(ident)
        os.environ["SESSION_TOUCH_STATE_DIR"] = str(t / "state")
        env = dict(os.environ)

        def sh(cmd: str, cwd: Path) -> None:
            subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True)

        remote = t / "remote.git"
        sh(f"git init -q --bare {remote} && git -C {remote} symbolic-ref HEAD refs/heads/main", t)
        repo = t / "repo"
        sh(f"git init -q {repo} && git -C {repo} symbolic-ref HEAD refs/heads/main && "
           f"git -C {repo} config commit.gpgsign false", t)
        (repo / "a.md").write_text("1\n")
        (repo / "sub").mkdir()
        (repo / "sub/b.md").write_text("1\n")
        sh(f"git add -A && git commit -qm init && git remote add origin {remote} && git push -qu origin main", repo)

        def go(cmd: str, cwd: Path = repo, sid: str = "s1") -> list[str]:
            sh(cmd, cwd)
            lines, flagged = run({"tool_input": {"command": cmd}, "cwd": str(cwd), "session_id": sid})
            record_flagged(sid, flagged)
            return lines

        # 1. 名指した commit が通った → 黙る
        (repo / "a.md").write_text("2\n")
        check("path commit landed is silent", go("git commit -qm x -- a.md") == [])
        # 2. pre-commit が断った commit → 出力を絞っても鳴る。 後ろの push は「push の失敗」 と読まない
        hook = repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        (repo / "a.md").write_text("3\n")
        got = go(f"git -C {repo} commit -qm y -- a.md 2>&1 | grep -E 'rejected|ERROR'; git -C {repo} push -q", cwd=t)
        check("failed path commit rings", any("commit が入っていない" in s and "a.md" in s for s in got))
        check("push after the failed commit is not read as a push failure", not any("push が" in s for s in got))
        fl = t / "state/s1.landed-flagged"
        check("flagged path recorded for the Stop net", fl.exists() and f"{repo}\ta.md" in fl.read_text())
        hook.unlink()
        # 3. 名指さない file の変更 (並列の窓) は数えない
        (repo / "sub/b.md").write_text("other window\n")
        check("unnamed dirty file not counted", go("git commit -qm z -- a.md") == [])
        # 4. 名指した dir の下の未追跡は数えない / 名指した未追跡の file そのものは数える
        (repo / "sub/new.md").write_text("n\n")
        check("untracked under a named dir ignored", go("git add sub/b.md && git commit -qm d -- sub") == [])
        (repo / "c.md").write_text("c\n")
        check("named untracked file rings", any("c.md" in s for s in go("git commit -qm e -- c.md")))
        # 5. path を名指さない commit: 通れば黙る、 index に残れば鳴る
        (repo / "a.md").write_text("4\n")
        check("index commit landed silent", go("git add a.md && git commit -qm f") == [])
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        (repo / "a.md").write_text("4b\n")
        check("index commit refused rings", any("index に" in s for s in go("git add a.md && git commit -qm f2 >/dev/null")))
        hook.unlink()
        sh("git commit -qm f3", repo)
        # 6. 後に同じ repo の index を動かす git があれば、 前の commit を見ない
        (repo / "a.md").write_text("5\n")
        check("later add suppresses the earlier commit check", go("git commit -qm g; git add a.md") == [])
        sh("git commit -qm h", repo)
        # 7. push: 通った push は黙る、 断られた push は絞った出力でも鳴る
        check("push landed silent", go("git push -q") == [])
        (repo / "a.md").write_text("6\n")
        sh("git commit -qam i", repo)
        rh = remote / "hooks/pre-receive"
        rh.write_text("#!/bin/sh\nexit 1\n")
        rh.chmod(0o755)
        check("refused push rings", any("push が終わっていない" in s for s in go("git push -q 2>/dev/null | tail -1")))
        rh.unlink()
        # 8. 別の remote・tag の push は見ない
        check("push to another remote skipped", go("git push -q fork main") == [])
        check("tag push skipped", go("git push --tags") == [])
        sh("git push -q", repo)
        # 9. 変数を含む path・-C・相対 cd の後は黙る
        (repo / "a.md").write_text("7\n")
        check("dynamic path skipped", run({"tool_input": {"command": 'git commit -m x -- "$f"'},
                                          "cwd": str(repo)}) == ([], []))
        check("dynamic -C skipped", run({"tool_input": {"command": 'git -C "$r" commit -m x -- a.md'},
                                         "cwd": str(repo)}) == ([], []))
        check("relative cd skipped", run({"tool_input": {"command": "cd sub && git commit -m x -- ../a.md"},
                                          "cwd": str(repo)}) == ([], []))
        check("absolute cd followed", any("a.md" in s for s in run(
            {"tool_input": {"command": f"cd {repo} && git commit -m x -- a.md"}, "cwd": str(t)})[0]))
        # 10. 語に割る: heredoc の commit message・2>&1・束ねた -am・-mMSG
        toks = tokens('git commit -m "$(cat <<\'EOF\'\nmsg\nEOF\n)" -- x.md 2>&1 | tail -2')
        segs = segments(toks or [])
        g = parse_git(segs[0]) if segs else None
        check("heredoc message parsed", g is not None and g[1] == "commit"
              and parse_commit(g[2]) == {"paths": ["x.md"], "all": False})
        check("bundled -qam", parse_commit(["-qam", "msg"]) == {"paths": [], "all": True})
        check("-mMSG keeps paths", parse_commit(["-mfix", "p.md"]) == {"paths": ["p.md"], "all": False})
        check("no commit/push word = no work", run({"tool_input": {"command": "ls"}, "cwd": str(repo)}) == ([], []))
        check("unparsable command is silent", run({"tool_input": {"command": "git commit -m 'x"},
                                                   "cwd": str(repo)}) == ([], []))
    if fails:
        print(f"git-write-landed-check selftest: {len(fails)}/{n} FAIL: " + "; ".join(fails))
        return 1
    print(f"git-write-landed-check selftest: {n}/{n} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
