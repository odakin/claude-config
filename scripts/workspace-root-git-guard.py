#!/usr/bin/env python3
"""workspace-root-git-guard.py — repo を並べた作業ルート (自身は repo でない dir) で、 path を書かない `git init` と書き込みの git (`add` / `commit` 等) を打つ Bash を、 実行の前に止める判定 (PreToolUse の hook が呼ぶ engine)。

なぜ: 単独の `cd` の行き先が session の folder の外 (scratchpad・/tmp) だと、 desktop の Code タブは作業ディレクトリを
  作業ルートに戻す (「Shell cwd was reset」)。 気づかずに次の呼び出しで `git init && git add … && git commit …` を打つと、
  作業ルートに repo ができる (実測 = 2 回。 できた空の repo は「root に .git があれば root だけを走査」 する fleet の検査から
  子の repo を全部隠した)。 規約 = conventions/claude-code-permissions.md#cd-with-git-goes-to-classifier。
  道具の側の root の判定 = scripts/lib/repo_roots.py (空の repo なら子を数える)。 本 engine は repo ができる前に止める網。

述語 (command の文字列から決める。 読めないものは通す = fail-open):
  - quote の中身と heredoc の本文は見ない (echo の中・commit message の中の `git init` では止めない)
  - command を ; && || | & ( ) 改行 で部分に割り、 部分ごとに先頭の変数代入・制御語を外して最初の語を見る
  - `cd <dir>` / `pushd <dir>` は行き先を今の dir から解決して以降の部分に効かせる (`~` `$HOME` と相対 path。
    それ以外の変数・`$(…)` = 行き先が読めない = 以降は止めない)
  - `git` は大域 option を飛ばして subcommand を見る。 `-C <dir>` / `--git-dir` / `--work-tree` / 先頭の `GIT_DIR=` /
    `GIT_WORK_TREE=` があれば行き先を書いた形 = 止めない
  - `git init` は path の引数があればその dir、 無ければ今の dir が行き先。 行き先が作業ルートなら止める (`git init .` も)
  - 書き込みの subcommand (WRITE_SUBS) は今の dir が作業ルートなら止める
  - 作業ルート = dir で、 直下に git repo (`<子>/.git`) が 2 つ以上あり、 自身は commit も tracked file も持たない
    (= lib/repo_roots.root_is_repo が False。 空の `.git` があっても作業ルートに数える)

出力 (--hook): stdin の PreToolUse の JSON を読み、 当たれば permissionDecision=deny + 直し方。 誤検出のコストは打ち直し 1 回。
  作業ルートで本当に打つなら行き先を path で書く (`git -C <作業ルート> …`) = 書いた形は止めない。
CLI: workspace-root-git-guard.py --check '<command>' [--cwd DIR]   当たりを 1 行ずつ出す (校正・調べ物)
     workspace-root-git-guard.py --selftest                          一時 dir の陽性・陰性対照
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    from repo_roots import root_is_repo
except Exception:  # pragma: no cover — lib が無い checkout = 判定できない = 通す
    root_is_repo = None  # type: ignore[assignment]

DOC = "claude-config/conventions/claude-code-permissions.md#cd-with-git-goes-to-classifier"
WRITE_SUBS = {"add", "commit", "rm", "mv", "reset", "restore", "checkout", "switch", "stash", "clean", "merge",
              "rebase", "pull", "cherry-pick", "revert", "am", "apply", "tag", "branch", "worktree", "submodule"}
# git の大域 option のうち値を次の語に取るもの
GIT_OPT_WITH_ARG = {"-c", "--namespace", "--exec-path", "--config-env"}
INIT_OPT_WITH_ARG = {"-b", "--initial-branch", "--template", "--separate-git-dir", "--object-format", "--ref-format",
                     "--shared"}
CONTROL = {"if", "then", "else", "elif", "do", "while", "until", "time", "!", "{", "}", "exec", "command", "builtin",
           "nohup", "env"}
QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
HEREDOC_OP = re.compile(r"<<-?(?!<)")  # quote の外の `<<` (位置は quote を空白にした行で探す。 `<<<` は here-string)
HEREDOC_DELIM = re.compile(r"[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")  # 区切りの名前は元の行から読む (`'EOF'` も)
SEP = re.compile(r"\|\||&&|[;|&()\n]")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _strip_heredocs(cmd: str) -> str:
    """heredoc の本文を空白にする (行の数と位置は保つ)。"""
    lines = cmd.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        delims = []
        for op in HEREDOC_OP.finditer(QUOTED.sub(_blank, line)):
            d = HEREDOC_DELIM.match(line, op.end())
            if d:
                delims.append(d.group(2))
        i += 1
        for delim in delims:
            while i < len(lines):
                body = lines[i]
                out.append(" " * len(body))
                i += 1
                if body.strip() == delim:
                    break
    return "\n".join(out)


def segments(cmd: str) -> List[str]:
    """quote の中身を保ったまま、 quote の外の区切りで割った部分 (heredoc の本文は空白)。"""
    text = _strip_heredocs(cmd)
    blanked = QUOTED.sub(_blank, text)
    out, start = [], 0
    for m in SEP.finditer(blanked):
        out.append(text[start:m.start()])
        start = m.end()
    out.append(text[start:])
    return [s for s in (x.strip() for x in out) if s]


def _words(seg: str) -> Optional[List[str]]:
    try:
        return shlex.split(seg, comments=True)
    except ValueError:
        return None


def is_workspace_root(d: Optional[Path]) -> bool:
    if d is None or root_is_repo is None:
        return False
    try:
        if not d.is_dir():
            return False
        n = 0
        for c in d.iterdir():
            if c.is_dir() and not c.is_symlink() and (c / ".git").exists():
                n += 1
                if n >= 2:
                    break
        if n < 2:
            return False
        return not root_is_repo(d)
    except OSError:
        return False


def _resolve(tok: str, cur: Optional[Path], home: str) -> Optional[Path]:
    """cd の行き先。 読めなければ None。"""
    if cur is None:
        return None
    t = tok
    if t in ("~", "$HOME", "${HOME}"):
        return Path(home)
    for pre in ("~/", "$HOME/", "${HOME}/"):
        if t.startswith(pre):
            t = os.path.join(home, t[len(pre):])
            break
    if "$" in t or "`" in t or t == "-":
        return None
    p = Path(t) if os.path.isabs(t) else cur / t
    return Path(os.path.normpath(str(p)))


def find_issues(command: str, cwd: str, home: Optional[str] = None) -> List[str]:
    """当たりの説明の list (空 = 通す)。"""
    home = home or os.path.expanduser("~")
    if "git" not in command:
        return []
    cur: Optional[Path] = Path(cwd) if cwd else None
    issues: List[str] = []
    root_cache: dict = {}

    def ws(d: Optional[Path]) -> bool:
        if d is None:
            return False
        k = str(d)
        if k not in root_cache:
            root_cache[k] = is_workspace_root(d)
        return root_cache[k]

    for seg in segments(command):
        words = _words(seg)
        if not words:
            continue
        env_names = set()
        while words and (ASSIGN.match(words[0]) or words[0] in CONTROL):
            if ASSIGN.match(words[0]):
                env_names.add(words[0].split("=", 1)[0])
            words = words[1:]
        if not words:
            continue
        head = words[0]
        if head in ("cd", "pushd"):
            args = [w for w in words[1:] if not w.startswith("-")]
            cur = _resolve(args[0], cur, home) if args else Path(home)
            continue
        if os.path.basename(head) != "git":
            continue
        rest = words[1:]
        explicit = bool(env_names & {"GIT_DIR", "GIT_WORK_TREE"})
        i = 0
        while i < len(rest) and rest[i].startswith("-"):
            w = rest[i]
            if w == "-C" or w.startswith("--git-dir") or w.startswith("--work-tree"):
                explicit = True
                if w in ("-C", "--git-dir", "--work-tree"):
                    i += 1
            elif w in GIT_OPT_WITH_ARG:
                i += 1
            i += 1
        if explicit or i >= len(rest):
            continue
        sub, args = rest[i], rest[i + 1:]
        if sub == "init":
            target, j = None, 0
            while j < len(args):
                a = args[j]
                if a in INIT_OPT_WITH_ARG:
                    j += 2
                    continue
                if a.startswith("-"):
                    j += 1
                    continue
                target = a
                break
            dest = cur if target is None else _resolve(target, cur, home)
            if ws(dest):
                issues.append(f"`git init` の行き先 = 作業ルート `{dest}`" + (" (path を書いていない)" if target is None else ""))
        elif sub in WRITE_SUBS and ws(cur):
            issues.append(f"`git {sub}` を作業ルート `{cur}` で打っている (行き先の repo を書いていない)")
    return issues


def reason_text(issues: List[str]) -> str:
    return ("[workspace-root-git-guard] " + " / ".join(issues) + "。\n"
            "作業ルートは repo を並べた dir で、 自身は repo でない。 単独の `cd` が戻された (「Shell cwd was reset」) 後に、"
            " 行き先のつもりの git が作業ルートで走る形の疑い (実測 = 作業ルートに空の repo ができ、 fleet の検査を盲目にした)。\n"
            "直し方: 行き先の dir を path で書く — `git init <dir>` / `git -C <dir> add …` / commit は"
            " `GIT_DIR=<dir>/.git GIT_WORK_TREE=<dir> git commit …` (`git -C … commit` は cd の guard が止める)。"
            " 作業ルートで本当に打つなら `git -C <作業ルート> …` と書く (書いた形は止めない)。\n"
            f"正本 = {DOC}")


def hook_main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    try:
        issues = find_issues(cmd, data.get("cwd") or os.getcwd())
    except Exception:  # fail-open
        return 0
    if issues:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason_text(issues)}}, ensure_ascii=False))
    return 0


def selftest() -> int:
    import subprocess
    import tempfile
    fails: List[str] = []

    def expect(label: str, ok: bool) -> None:
        print(("  ok: " if ok else "  NG: ") + label)
        if not ok:
            fails.append(label)

    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")

    def git(d: Path, *a: str) -> None:
        subprocess.run(["git", *a], cwd=str(d), env=env, capture_output=True, check=True)

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        w = t / "ws"
        for r in ("r1", "r2"):
            (w / r).mkdir(parents=True)
            git(w / r, "init", "-q")
            (w / r / "a.md").write_text("x\n", encoding="utf-8")
            git(w / r, "add", "a.md")
            git(w / r, "commit", "-qm", "init")
        (w / "notes").mkdir()
        one = t / "one"
        (one / "r").mkdir(parents=True)
        git(one / "r", "init", "-q")
        out = t / "scratch"
        out.mkdir()
        W, H = str(w), str(t)

        def hit(cmd: str, cwd: str = W) -> bool:
            return bool(find_issues(cmd, cwd, H))
        expect("陽性対照 (実測の形): 作業ルートで path の無い git init + add + commit",
               len(find_issues("git init -q && git add main.tex && git commit -qm base", W, H)) == 3)
        expect("git init . = 作業ルート", hit("git init ."))
        expect("作業ルートの直下の repo でない dir から ../ の git init も行き先で見る", hit("git init ..", str(w / "notes")))
        expect("陰性: git init <新しい dir> (path を書いた)", not hit("git init -q newrepo && git -C newrepo add x"))
        expect("陰性: 子の repo の中の add / commit", not hit("git add a.md && git commit -m x", str(w / "r1")))
        expect("陰性: 同じ command の中で子の repo へ cd してから", not hit("cd r1 && git add a.md && git commit -m y"))
        expect("陰性: 作業ルートの外へ cd してから git init (同じ command の中の cd は効く)",
               not hit(f"cd {out} && git init -q && git add x"))
        expect("陰性: 行き先を書いた形 (-C / GIT_DIR / --git-dir)",
               not hit(f"git -C {out} init -q && GIT_DIR={out}/.git GIT_WORK_TREE={out} git add x && "
                       f"git --git-dir={out}/.git commit -m z"))
        expect("陰性: 読み取りの git (status / log / diff)", not hit("git status && git log -1 && git diff"))
        expect("陰性: quote の中・heredoc の本文の git init",
               not hit("echo \"git init\" && cat > f.txt <<'EOF'\ngit init\ngit add x\nEOF\n"))
        expect("陰性: 行き先が読めない cd の後は止めない (fail-open)", not hit("cd \"$X\" && git init"))
        expect("陰性: 直下の repo が 1 つの dir は作業ルートでない", not hit("git init", str(one)))
        git(w, "init", "-q")  # 空の repo ができた後も作業ルートに数える
        expect("空の .git のある作業ルートも止める (commit も tracked file も無い)", hit("git add x"))
        (w / "top.md").write_text("x\n", encoding="utf-8")
        git(w, "add", "top.md")
        git(w, "commit", "-qm", "top")
        expect("陰性: 自身が commit を持つ repo になった dir は作業ルートでない", not hit("git add top.md"))
        # hook の入出力
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git init -q"}, "cwd": str(t / "ws2")})
        (t / "ws2" / "a" / ".git").mkdir(parents=True)
        (t / "ws2" / "b" / ".git").mkdir(parents=True)
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--hook"], input=payload,
                           capture_output=True, text=True)
        expect("--hook: 当たり = deny と直し方", r.returncode == 0 and '"deny"' in r.stdout and "git init <dir>" in r.stdout)
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--hook"], input="not json",
                           capture_output=True, text=True)
        expect("--hook: 読めない入力は黙って通す (fail-open)", r.returncode == 0 and r.stdout == "")
    print("selftest " + ("ok" if not fails else "FAIL (%d)" % len(fails)))
    return 1 if fails else 0


def main() -> int:
    a = sys.argv[1:]
    if a == ["--selftest"]:
        return selftest()
    if a == ["--hook"]:
        return hook_main()
    if a[:1] == ["--check"] and len(a) >= 2:
        cwd = a[a.index("--cwd") + 1] if "--cwd" in a else os.getcwd()
        for x in find_issues(a[1], cwd):
            print(x)
        return 0
    print(__doc__.split("\n", 1)[0])
    return 2


if __name__ == "__main__":
    sys.exit(main())
