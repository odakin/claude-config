#!/usr/bin/env python3
"""git-amend-shared-clone.py — 並列の session が居うる clone での git commit --amend と、 直前の commit の成否に繋がらない git push を止める PreToolUse(Bash) の述語と本体 (find_issues(command) = 校正の道具が呼ぶ形、 --selftest)。 規約 = conventions/multi-session-coordination.md#no-amend-in-shared-worktree / #confirm-commit-landed

Why:
  amend は path で絞れず、 HEAD の commit を置き換える。 同じ clone に別の session が居ると、 次の 2 つの形で
  手元と remote が分かれる (どちらも実測):
  (1) 直前に別の session が積んだ commit を、 自分の message で上書きする。
  (2) HEAD が自分の未 push の commit でも、 amend の pre-commit の hook が走る間に、 別の session の push が
      amend の前の commit を remote に出す。 その session の commit は index.lock で止まっていたが、 commit の
      出力を pipe で切り `;` で繋いでいたので push だけが走った。
  (2) は amend を始める前に「HEAD が自分の commit で未 push か」 を確かめても防げない (確かめた時点では正しい)。
  規則の文はあっても amend は打たれ続けた (実測) = 文は打つ瞬間に発火しない。

止めるもの (heredoc の本文と quote の中身は見ない):
  A. `git commit … --amend …` (--no-edit / --only / -m / -F / -C との組み合わせも)。 次のどれか 1 つで止める:
     1. この機械で生きている別の session (全部の設定フォルダの Claude の刻印と、 Codex の thread) の cwd が、
        repo の top・その下・その上 (祖先) のどれか。 session は作業ルートで始まって repo に cd するので、
        cwd からはどの clone を触るかが分からない = 祖先も数える。
     2. HEAD がもう remote-tracking の branch に載っている (amend すると remote と分かれる)。
     3. HEAD の commit の Agent-Session trailer がこの session でない (別の session か人の commit)。
     4. 生きている session の刻印・Codex の thread・repo の状態・この session の id が読めない (止める側に倒す)。
     どれにも当たらなければ通す (例 = 自分だけが使う一時の worktree、 機械にこの session しか居ないときの
     自分の未 push の HEAD)。 `--fixup=amend:<commit>` は rebase までは履歴を書き換えないので対象外。
  B. 同じ command の中で `git push` が、 直前の `git commit` の成否に繋がっていない形:
     間の区切りに `;` / 改行 / `||` / `&` がある (前に set -e があれば `;` と改行は繋がっているとみなす)、
     または commit を pipe で次の command に流している (`git commit … | tail …`) のに前に set -o pipefail が無い。
     commit が止まっても push が走り、 HEAD にある別の session の commit (や amend の途中の commit) を出す。

出力: permissionDecision=deny + 直し方。 読めない入力・想定外の例外は黙って通す (tool call を止めない)。
  opt-out: CLAUDE_AMEND_GUARD=0 (CLAUDE_*_GUARD の形 = 外すには本人の承認が要る)。
  test 用の置き換え: CLAUDE_SESSIONS_DIR (刻印の dir、 lib/claude_config_dirs.py) / CODEX_HOME (Codex の thread)。
使い方:
  hook の入口から main() (stdin = PreToolUse の JSON)
  python3 git-amend-shared-clone.py --selftest
  calibrate-bash-command-pattern.py --hook scripts/git-amend-shared-clone.py --func find_amend
  calibrate-bash-command-pattern.py --hook scripts/git-amend-shared-clone.py --func find_unguarded_push
"""
from __future__ import annotations

import glob
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

HEREDOC_START = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")
REDIRECT_AMP = re.compile(r"(?<=[<>])&|&(?=>)")
SEP = re.compile(r"&&|\|\||\|&|[;&|()\n]")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
LEADING = {"command", "builtin", "exec", "time", "nohup", "env", "then", "do", "else", "elif", "if", "while", "until", "!", "{"}
GIT_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
COMMIT_OPT_WITH_ARG = {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message",
                       "-t", "--template", "--author", "--date", "--cleanup", "--trailer", "--fixup", "--squash",
                       "--pathspec-from-file"}
SET_ERREXIT = re.compile(r"^-[a-zA-Z]*e[a-zA-Z]*$")
OPT_OUT_ENV = "CLAUDE_AMEND_GUARD"
AMEND_ANCHOR = "claude-config/conventions/multi-session-coordination.md#no-amend-in-shared-worktree"
PUSH_ANCHOR = "claude-config/conventions/multi-session-coordination.md#confirm-commit-landed"


def _blank(s: str, keep_newlines: bool = True) -> str:
    return re.sub(r"[^\n]" if keep_newlines else r".", " ", s, flags=re.S)


def _strip_heredocs(cmd: str) -> str:
    """heredoc の本文 (目印の行の次の行から終わりの語の行まで) を同じ長さの空白にする。 目印の行の残り
    (`<<'EOF' && git push` の `&& git push`) は残す = command の続きなので。"""
    out = list(cmd)
    pos = 0
    while True:
        m = HEREDOC_START.search(cmd, pos)
        if not m:
            break
        nl = cmd.find("\n", m.end())
        if nl < 0:
            break
        word = m.group(2)
        end = re.compile(r"\n[ \t]*" + re.escape(word) + r"[ \t]*(?=\n|$)").search(cmd, nl)
        stop = end.end() if end else len(cmd)
        for i in range(nl, stop):
            out[i] = " "
        pos = stop
    return "".join(out)


def _pieces(cmd: str) -> list[dict]:
    """command を区切りで割った部分の list。 各要素 = {words, raw0, sep (直後の区切り。 末尾は None)}。"""
    stripped = _strip_heredocs(cmd)
    # 引用符の中の改行も消す = 複数行の commit message の改行を command の区切りと読まない
    masked = QUOTED.sub(lambda m: _blank(m.group(0), keep_newlines=False), stripped)
    masked = REDIRECT_AMP.sub(" ", masked)
    out, start = [], 0
    for m in SEP.finditer(masked):
        out.append((start, m.start(), m.group(0)))
        start = m.end()
    out.append((start, len(cmd), None))
    pieces = []
    for a, b, sep in out:
        text = stripped[a:b]
        if not masked[a:b].strip():
            pieces.append({"words": [], "raw0": "", "sep": sep})
            continue
        try:
            words = shlex.split(text, comments=True)
        except ValueError:
            words = text.split()
        raw0 = words[0] if words else ""
        while words and (words[0] in LEADING or ASSIGN.match(words[0])):
            words = words[1:]
        pieces.append({"words": words, "raw0": raw0, "sep": "|" if sep == "|&" else sep})
    return pieces


def _parse_git(words: list[str]):
    """(subcommand, 残りの語, -C の行き先)。 git でなければ None。"""
    if not words or os.path.basename(words[0]) != "git":
        return None
    i, cdir = 1, None
    while i < len(words):
        w = words[i]
        if w in GIT_OPT_WITH_ARG:
            arg = words[i + 1] if i + 1 < len(words) else ""
            if w == "-C":
                cdir = arg if cdir is None or os.path.isabs(arg) else os.path.join(cdir, arg)
            i += 2
            continue
        if w.startswith("-"):
            i += 1
            continue
        return w, words[i + 1:], cdir
    return None


def _is_amend(rest: list[str]) -> bool:
    i = 0
    while i < len(rest):
        w = rest[i]
        if w == "--":
            return False
        if w.startswith("--am") and "--amend".startswith(w):
            return True
        if w in COMMIT_OPT_WITH_ARG:
            i += 2
            continue
        i += 1
    return False


def find_amend(command: str) -> list[str]:
    """校正用の純粋な述語 A: amend の commit の形の名前の list (repo・session の状態は見ない)。"""
    if "--am" not in command:
        return []
    out = []
    for p in _pieces(command):
        g = _parse_git(p["words"])
        if g and g[0] == "commit" and _is_amend(g[1]):
            out.append("git commit --amend")
    return out


def _set_flags(words: list[str]) -> tuple[bool, bool]:
    """`set …` の語から (errexit, pipefail) が立つか。"""
    if not words or words[0] != "set":
        return False, False
    errexit = pipefail = False
    args = words[1:]
    for i, w in enumerate(args):
        if SET_ERREXIT.match(w):
            errexit = True
        if w in ("-o", "-eo", "-euo", "-ueo", "-oe") or (w.startswith("-") and w.endswith("o")):
            nxt = args[i + 1] if i + 1 < len(args) else ""
            pipefail = pipefail or nxt == "pipefail"
            errexit = errexit or nxt == "errexit"
    return errexit, pipefail


def _unguarded_push(pieces: list[dict]) -> list[str]:
    out = []
    errexit = pipefail = False
    last_commit = None  # (index, errexit の時点の値, pipefail の時点の値)
    for j, p in enumerate(pieces):
        e, pf = _set_flags(p["words"])
        errexit, pipefail = errexit or e, pipefail or pf
        g = _parse_git(p["words"])
        if not g:
            continue
        if g[0] == "commit":
            last_commit = (j, errexit, pipefail)
            continue
        if g[0] != "push" or last_commit is None:
            continue
        i, e_at, pf_at = last_commit
        last_commit = None  # 同じ commit の後の 2 つ目の push は再試行 (`git push || (git pull --rebase && git push)`) = 見ない
        seps = [pieces[k]["sep"] for k in range(i, j) if pieces[k]["sep"] not in ("(", ")")]
        cond_then = pieces[i]["raw0"] in ("if", "while", "until") and any(
            pieces[k]["raw0"] in ("then", "do") for k in range(i + 1, j + 1))
        # `git commit … || { echo …; exit 1; }` / `|| exit 1` = commit の失敗で抜ける = 後ろは commit の成否に繋がっている
        exits_on_fail = pieces[i]["sep"] == "||" and any(
            pieces[k]["words"][:1] in (["exit"], ["return"]) for k in range(i + 1, j))
        why = None
        if pieces[i]["sep"] == "|" and not pf_at:
            why = "commit の出力を pipe で流している (set -o pipefail が無い = commit の終了値が消える)"
        elif exits_on_fail:
            why = None
        elif "||" in seps:
            why = "間に `||` がある"
        elif "&" in seps:
            why = "間に `&` がある (背景で走る)"
        elif any(s in (";", "\n") for s in seps) and not e_at and not cond_then:
            why = "間の区切りが `;` か改行"
        if why:
            out.append("git push after unchecked commit: " + why)
    return out


def find_unguarded_push(command: str) -> list[str]:
    """校正用の純粋な述語 B: 直前の commit の成否に繋がらない push の形の list。"""
    if "push" not in command or "commit" not in command:
        return []
    return _unguarded_push(_pieces(command))


def find_issues(command: str) -> list[str]:
    return find_amend(command) + find_unguarded_push(command)


# ---- 状態を見る部分 (A だけ) ----

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


def _git(repo: str, *args: str) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, encoding="utf-8", errors="replace", timeout=8)
    except (OSError, subprocess.SubprocessError) as exc:
        return 99, "", str(exc)
    return r.returncode, r.stdout, r.stderr


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except Exception:
        return True
    return True


def _live_claude(self_sid: str | None) -> list[dict] | None:
    """自分以外の生きている Claude session の [{id, cwd}]。 刻印の dir が読めなければ None。"""
    try:
        import claude_config_dirs as ccd
        dirs = ccd.sessions_dirs()
    except Exception:
        dirs = [os.environ.get("CLAUDE_SESSIONS_DIR") or os.path.expanduser("~/.claude/sessions")]
    rows = []
    for sdir in dirs:
        if os.path.exists(sdir) and not os.access(sdir, os.R_OK | os.X_OK):
            return None
        for f in glob.glob(os.path.join(sdir, "*.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
            except Exception:
                continue
            sid, pid, cwd = d.get("sessionId") or "", d.get("pid"), d.get("cwd") or ""
            if not sid or sid == self_sid or not isinstance(pid, int) or not cwd or not _pid_alive(pid):
                continue
            rows.append({"id": "claude:" + sid[:8], "cwd": cwd})
    return rows


def _live_codex() -> list[dict] | None:
    try:
        import codex_threads as ct
    except Exception:
        return []
    try:
        rows = ct.live_threads()
    except Exception:
        return None
    if rows is None:
        return None
    return [{"id": "codex:" + str(r.get("id", ""))[:8], "cwd": r.get("cwd") or ""} for r in rows if r.get("cwd")]


def _related(cwd: str, top: str) -> bool:
    c = os.path.realpath(cwd)
    return c == top or c.startswith(top + os.sep) or top.startswith(c.rstrip(os.sep) + os.sep)


def amend_reasons(repo: str, self_sid: str | None) -> list[str]:
    """repo での amend を止める理由の list (空 = 通す)。"""
    rc, out, err = _git(repo, "rev-parse", "--show-toplevel")
    if rc != 0:
        return [] if "not a git repository" in err else [f"{repo} の repo の状態が読めない = 止める側に倒した"]
    top = os.path.realpath(out.strip())
    reasons = []
    rc, out, _ = _git(top, "rev-parse", "--verify", "-q", "HEAD")
    if rc != 0:
        return []  # まだ commit が無い = amend する commit が無い
    rc, out, err = _git(top, "branch", "-r", "--contains", "HEAD")
    if rc != 0:
        reasons.append("HEAD が remote に載っているかが読めない")
    else:
        remotes = [ln.strip() for ln in out.splitlines() if ln.strip() and "->" not in ln]
        if remotes:
            reasons.append(f"HEAD がもう remote に載っている ({', '.join(remotes[:3])}) = amend すると remote と分かれる")
    rc, out, _ = _git(top, "log", "-1", "--format=%(trailers:key=Agent-Session,valueonly,separator=%x2C)")
    trailers = [t.strip() for t in out.strip().split(",") if t.strip()] if rc == 0 else []
    if not self_sid:
        reasons.append("この session の id が読めない = HEAD が自分の commit か確かめられない")
    elif f"claude:{self_sid}" not in trailers:
        who = ", ".join(trailers) if trailers else "trailer なし (人の commit か古い commit)"
        reasons.append(f"HEAD の commit がこの session のものでない ({who})")
    claude, codex = _live_claude(self_sid), _live_codex()
    if claude is None or codex is None:
        reasons.append("生きている別の session が読めない (" + ("Claude の刻印" if claude is None else "Codex の thread") + ") = 止める側に倒した")
    near = [r for r in (claude or []) + (codex or []) if _related(r["cwd"], top)]
    if near:
        shown = ", ".join(f"{r['id']} ({r['cwd']})" for r in near[:3]) + (f" ほか {len(near) - 3}" if len(near) > 3 else "")
        reasons.append(f"この clone に居うる別の session: {shown}")
    return reasons


def decide(command: str, cwd: str | None, self_sid: str | None) -> str | None:
    """止める理由の本文か None。"""
    pieces = _pieces(command)
    here = os.path.realpath(cwd) if cwd else None
    amend_msgs = []
    for p in pieces:
        words = p["words"]
        if words and words[0] in ("cd", "pushd"):
            here = _resolve(words[1] if len(words) > 1 else os.path.expanduser("~"), here)
            continue
        g = _parse_git(words)
        if not (g and g[0] == "commit" and _is_amend(g[1])):
            continue
        repo = _resolve(g[2], here) if g[2] is not None else here
        if repo is None:
            amend_msgs.append("行き先の repo が読めない = 止める側に倒した")
            continue
        amend_msgs += amend_reasons(repo, self_sid)
    push_msgs = _unguarded_push(pieces) if "push" in command else []
    parts = []
    if amend_msgs:
        parts.append(
            "[amend-shared-clone] `git commit --amend` を止めた: " + " / ".join(amend_msgs) + "。\n"
            "amend は HEAD の commit を置き換える。 同じ clone に別の session が居ると、 直前に別の session が積んだ commit を"
            "上書きするか、 amend の hook が走る間に別の session の push が amend の前の commit を remote に出して、 手元と remote が"
            "分かれる (HEAD が自分の未 push の commit でも起きる)。\n"
            "直し方: message の誤りは次の commit の本文に「<hash> の message の訂正: …」 と書いて直す。 中身の直しも次の commit にする。\n"
            "もう amend して手元と remote が分かれたら: 自分の commit の上に何も乗っていなければ、 元の commit と tree が同じことを"
            "確かめて `git reset --soft <元の commit>`。 上に別の session の commit が乗っていれば、 どの commit も書き換えずに"
            "合流の commit で繋ぐ。\n正本 = " + AMEND_ANCHOR)
    if push_msgs:
        whys = sorted({m.split(": ", 1)[1] for m in push_msgs})
        parts.append(
            "[amend-shared-clone] `git push` が直前の `git commit` の成否に繋がっていない (" + " / ".join(whys) + ")。\n"
            "commit が hook や index.lock で止まっても push が走り、 HEAD にある別の session の commit (や amend の途中の commit) を"
            "remote に出す。\n"
            "直し方: `git commit … && git push` と `&&` で繋ぐ。 commit の出力を pipe で切らない (要るなら `> <file> 2>&1` に出して後で読む)。 "
            "commit の成否だけを見るなら push を付けずに `; echo \"commit_exit=$?\"`。\n正本 = " + PUSH_ANCHOR)
    return "\n\n".join(parts) or None


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
    if "commit" not in cmd or ("--am" not in cmd and "push" not in cmd):
        return None
    reason = decide(cmd, data.get("cwd") or os.getcwd(), data.get("session_id"))
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

    fa, fp = find_amend, find_unguarded_push
    check("amend forms", fa("git commit --amend --no-edit") == ["git commit --amend"]
          and fa("git commit -q --amend --only -F m.txt") == ["git commit --amend"]
          and fa("GIT_EDITOR=true git -C ../r commit --amend") == ["git commit --amend"]
          and fa("git commit --amen -m x") == ["git commit --amend"])
    check("not amend", fa("git commit -m x -- a.md") == [] and fa("git commit --fixup=amend:HEAD~1") == []
          and fa("git commit -m --amend") == [] and fa("git commit -m x -- --amend") == [])
    check("quoted and heredoc --amend pass", fa('git commit -m "do not use --amend" -- a') == []
          and fa("git commit -F - -- a <<'EOF'\nnever git commit --amend here\nEOF") == [])
    check("git not at word 0 passes", fa("echo git commit --amend") == [] and fa("grep -n -- '--amend' x.md") == [])
    check("push after && is fine", fp("git commit -q -m x -- a && git push -q") == []
          and fp("git add a && git commit -m x -- a 2>&1 && git push") == []
          and fp("git commit -m x -- a && git push; git status") == [])
    check("push after ; or newline", len(fp("git commit -m x -- a; git push")) == 1
          and len(fp("git commit -m x -- a\ngit push")) == 1)
    check("the observed shape (pipe + ;)", len(fp("git commit -q -F m -- a 2>&1 | tail -2; git log --oneline -1 && git push -q")) == 1)
    check("pipe then &&", len(fp("git commit -q -F m -- a 2>&1 | tail -2 && git push")) == 1)
    check("pipefail and errexit", fp("set -o pipefail; git commit -m x | tail -2 && git push") == []
          and fp("set -euo pipefail\ngit commit -m x -- a\ngit push") == []
          and fp("set -e; git commit -m x; git push") == []
          and len(fp("set -e; git commit -m x | tail -1; git push")) == 1)
    check("|| and &", len(fp("git commit -m x || git push")) == 1 and len(fp("git commit -m x & git push")) == 1)
    check("later pipe does not matter", fp("git commit -m x && git log -1 | head -1 && git push") == [])
    check("heredoc message keeps the marker line", fp("git commit -q -F - -- a <<'EOF' && git push -q; echo x\nbody; git push\nEOF") == []
          and len(fp("git commit -q -F - -- a <<'EOF'\nbody\nEOF\ngit push")) == 1)
    check("multi-line quoted message is one command", fp('git commit -q -m "line 1\n\nCo-Authored-By: x" -- a && git push') == []
          and fp('git commit -m "$(cat <<\'EOF\'\nmsg; git push\nEOF\n)" && git push') == [])
    check("if/then", fp("if git commit -m x -- a; then git push; fi") == [])
    check("commit || exit", fp('git commit -q -F m -- a || { echo "ABORT commit"; exit 1; }\ngit push -q') == []
          and fp("git commit -m x || exit 1; git push") == [])
    check("retry push after the first", fp("git commit -m x && (git push -q || (git pull --rebase -q && git push -q))") == [])
    check("echo of the exit status does not gate", len(fp('git commit -m x -- a; echo "rc=$?"; git push')) == 1)
    check("push without a commit", fp("git fetch && git push") == [] and fp("git push; git status") == [])
    check("subshell", fp("git commit -m x && (git push)") == [] and len(fp("git commit -m x; (git push)")) == 1)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = os.path.realpath(tmp)
        sess = os.path.join(tmp, "sessions")
        os.makedirs(sess)
        os.environ["CLAUDE_SESSIONS_DIR"] = sess
        os.environ["CODEX_HOME"] = os.path.join(tmp, "codex-home")
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        repo = os.path.join(tmp, "work", "r")
        os.makedirs(repo)
        run = lambda *a, cwd=repo: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)  # noqa: E731
        run("init", "-q", "-b", "main")
        run("config", "user.email", "t@example.invalid")
        run("config", "user.name", "t")
        with open(os.path.join(repo, "a.md"), "w") as fh:
            fh.write("a\n")
        run("add", "a.md")
        me, other = "11111111-aaaa-bbbb-cccc-000000000001", "22222222-aaaa-bbbb-cccc-000000000002"
        run("commit", "-q", "-m", "init", "-m", f"Agent-Session: claude:{me}")

        def rec(name: str, sid: str, cwd: str, pid: int | None = None) -> None:
            with open(os.path.join(sess, name + ".json"), "w") as fh:
                json.dump({"pid": os.getpid() if pid is None else pid, "sessionId": sid, "cwd": cwd}, fh)

        def clear() -> None:
            for f in glob.glob(os.path.join(sess, "*.json")):
                os.remove(f)

        check("alone, own unpushed HEAD: pass", amend_reasons(repo, me) == [])
        rec("self", me, repo)
        check("own record is not another session", amend_reasons(repo, me) == [])
        rec("o1", other, tmp)
        check("other session at an ancestor: stop", any("居うる" in r for r in amend_reasons(repo, me)))
        clear()
        rec("o2", other, os.path.join(repo, "sub"))
        check("other session inside the repo: stop", any("居うる" in r for r in amend_reasons(repo, me)))
        clear()
        rec("o3", other, os.path.join(tmp, "elsewhere"))
        check("other session in a sibling dir: pass", amend_reasons(repo, me) == [])
        clear()
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        rec("o4", other, tmp, pid=dead.pid)
        check("dead session record: pass", amend_reasons(repo, me) == [])
        clear()
        check("unknown self id: stop", any("id が読めない" in r for r in amend_reasons(repo, None)))
        check("HEAD of another session: stop", any("のものでない" in r for r in amend_reasons(repo, other)))
        run("commit", "-q", "--allow-empty", "-m", "by a person")
        check("HEAD without a trailer: stop", any("trailer なし" in r for r in amend_reasons(repo, me)))
        run("commit", "-q", "--allow-empty", "-m", "mine", "-m", f"Agent-Session: claude:{me}")
        bare = os.path.join(tmp, "remote.git")
        run("init", "-q", "--bare", bare, cwd=tmp)
        run("remote", "add", "origin", bare)
        run("push", "-q", "origin", "main")
        check("HEAD already pushed: stop", any("remote に載っている" in r for r in amend_reasons(repo, me)))
        run("commit", "-q", "--allow-empty", "-m", "mine 2", "-m", f"Agent-Session: claude:{me}")
        check("unpushed own HEAD above a pushed one: pass", amend_reasons(repo, me) == [])
        global _live_codex
        real_codex = _live_codex
        _live_codex = lambda: None  # noqa: E731
        check("unreadable Codex threads: stop", any("読めない" in r for r in amend_reasons(repo, me)))
        _live_codex = real_codex
        os.chmod(sess, 0)
        check("unreadable session records: stop", any("読めない" in r for r in amend_reasons(repo, me)))
        os.chmod(sess, 0o755)
        check("not a repo: pass", amend_reasons(tmp, me) == [])
        check("decide follows cd", decide(f"cd {repo} && git commit --amend --no-edit", tmp, me) is None)
        rec("o5", other, tmp)
        r = decide(f"cd {repo} && git commit --amend --no-edit", tmp, me)
        check("decide stops with the fix and anchor", r is not None and "次の commit" in r and "#no-amend-in-shared-worktree" in r)
        check("unreadable cd target: stop", decide("cd $X && git commit --amend", tmp, me) is not None)
        out = hook(json.dumps({"tool_name": "Bash", "cwd": repo, "session_id": me,
                               "tool_input": {"command": "git commit --amend --no-edit"}}))
        check("hook emits a PreToolUse deny", out is not None and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny")
        out = hook(json.dumps({"tool_name": "Bash", "cwd": repo, "session_id": me,
                               "tool_input": {"command": "git commit -m x -- a.md | tail -1; git push"}}))
        check("hook stops the unguarded push", out is not None and "#confirm-commit-landed" in out)
        check("hook is silent for other tools, plain commits and broken input",
              hook('{"tool_name":"Read"}') is None and hook("not json") is None
              and hook(json.dumps({"tool_name": "Bash", "cwd": repo, "session_id": me,
                                   "tool_input": {"command": "git commit -m x -- a.md && git push"}})) is None)
        os.environ[OPT_OUT_ENV] = "0"
        check("opt-out", hook(json.dumps({"tool_name": "Bash", "cwd": repo, "session_id": me,
                                          "tool_input": {"command": "git commit --amend"}})) is None)
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
