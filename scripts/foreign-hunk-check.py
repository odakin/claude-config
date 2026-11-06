#!/usr/bin/env python3
"""foreign-hunk-check.py — git commit の直前に、 commit に入る差分の hunk のうち、 この session の書き込み (Edit / Write / MultiEdit / NotebookEdit の文と Bash の command の文) のどこにも無い追加行を持つ hunk を見つける (並列の session の未 commit の変更を自分の commit に巻き込まないため)。

## なぜ

同じ作業 tree を並列の session が触ると、 `git commit -- <path>` は相手の未 commit の hunk も一緒に commit する
(守れるのは file の単位まで = [`conventions/multi-session-coordination.md#staging-window-race`](../conventions/multi-session-coordination.md#staging-window-race))。
規約の防御は commit の直前に自分の hunk の数を数える reflex (`#behind-check-in-chain`) と、 混ざっていたときに自分の分だけを
commit する道具 ([`git-commit-own-hunk.py`](git-commit-own-hunk.py) = `#temp-index-commit`) で、 数える段は止められた command の
出し直しで落ちる (`#reissue-keeps-checks`、 実測)。 本 engine は数える段を機械にする: hunk の数でなく中身で、 自分が書いた文に
無い追加行を名指す。

## 述語 (`find_issues(command, cwd, transcript)`)

1. command の中の `git commit` を探す (heredoc の本文と quote の中は見ない。 `cd` の行き先と `git -C` を追う)。 同じ command の
   `git add <path>` も数える (commit の前に stage される)。 `--amend`・一時 index (`GIT_INDEX_FILE=`)・merge / rebase /
   cherry-pick の途中は見ない (差分が自分の書き込みと対応しない)。
2. commit に入る差分を作る: path を指定した commit = HEAD と作業 tree の差 (その path だけ)、 `-a` = 追跡中の全 file、
   素の commit = index の差。 同じ command で add される未追跡の file は全行を追加とみなす。 差分は command を走らせる前の
   作業 tree なので、 同じ command の中で書く変更 (sed・生成器) は見えない (= 誤検出にもならない)。
3. この session の会話記録 (と subagent の記録) から、 書き込みの文を集める: その file への Edit の new_string・old_string、
   Write の content、 NotebookEdit の new_source = 「同じ file の文」。 他の file への書き込みと Bash の command の文
   (引用文字列・heredoc の本文の行・JSON の escape を戻した写しを含む) = 「session の文」 (scratchpad に書いた候補を `cp`
   した変更、 置換の道具に渡した断片、 heredoc・sed で書いた変更を拾う)。
4. file ごとに分ける (`file_class`): この session の Bash の command が書いた (かもしれない) file = **道具** (道具・script が
   書いた行は会話記録から読めない = 見ない。 既定は広く取る = 出力の向け先・写しの先・その場の置換・heredoc の script の
   書き込みに加え、 読むだけ・git でない部分が path の語として渡した file も。 `FOREIGN_HUNK_TOOL=strict` で書き込みの形だけ)、
   Edit / Write で書いた file = **編集**、 `git add` に名指した file・dir の中 = **名指し** (生成器の出力)、 どれでもない
   file = **未接触**。 未接触の file は path を指定した commit では見ない (自分で名指した file = 生成物・道具の出力)、
   素の commit と `-a` では file ごとに 1 件出す (並列の session が stage した file を巻き込む形)。
5. 編集の file の塊の追加行のうち、 空白と記号だけでなく 3 文字以上の行を、 同じ file の文の行と照合する (一致・行の一部 =
   Edit の断片・似た行)。 外れた行を session の文の中に探す。 どちらにも無い行が 1 つでもある塊 = 由来の分からない塊。
   削除だけの塊は、 削った行が old_string・Write の前提・session の文に無ければ数える (`--added-only` で外す)。
6. 由来の分からない塊が無ければ黙る。 あれば file・行の番号・最初の行を名指し、 自分の分だけを commit する道具を示す。

## 射程と誤検出の源 (扱い)

- **道具が書いた変更** (台帳を書く script・生成器・置換の道具): 行が会話記録に無い。 道具の file は見ない (= 道具と相手が
  同じ file に書いた形は射程外 = 見落とす側)。 path を渡さずに書く道具 (id から file を決める台帳の道具など) の file は、
  Edit でも触っていれば編集の file として照合し、 道具の行は誤検出になる (校正の数 = 個人層の記録)。 根本の限界 = 会話記録の
  文で由来を当てる述語は、 道具・script が書いた行を見分けられない (確かめるなら tool の呼び出しの前後の file の状態を記録する
  別の作り = 毎回の呼び出しに git status と hash の費用が掛かる)。
- **`git pull --rebase`・`git merge` の後**: HEAD が進むだけで差分は自分の変更のまま。 衝突の解決の途中 (MERGE_HEAD など) は見ない。
- **改行・空白だけの塊**: 数えない (3 文字未満・記号だけの行も)。
- **index に入れた新しい file**: 全行を追加として照合する (Write で作った file は content と照合して通る)。
- **binary**: 拡張子 (PDF・Office・画像・音声ほか) と制御文字で外し、 textconv も外す (PDF は NUL を持たず text と読まれる
  ことがある = 実測)。 git-crypt の file だけは textconv で平文に戻して見る。
- **pre-commit が書き換える内容**: commit の前に見るので影響しない。
- **別の機械・別の道具 (Codex・人の手)**: その session の会話記録に無いので由来が分からない = 正しく出す側。
- **見ない**: `git commit` を内側で打つ script (台帳の道具・掲示板の CLI) = command に `git commit` が無い。

## 使い方

    foreign-hunk-check.py --check '<command>' [--cwd DIR] [--transcript PATH]   # 1 回の判定 (hook と同じ述語)
    foreign-hunk-check.py --hook                                                # PreToolUse(Bash) の JSON を stdin から
    foreign-hunk-check.py --replay [--since YYYY-MM-DD] [--projects DIR ...]    # 会話記録の commit を再生して数える (校正)
    foreign-hunk-check.py --selftest

hook の出力 = `FOREIGN_HUNK_MODE` (既定 `notice` = 止めずに知らせる / `deny` = 止める / `deny-once` = 同じ塊の組は 1 回だけ止め、
打ち直しは通す (記録 = `~/.claude/state/foreign-hunk/<session>.txt`、 `FOREIGN_HUNK_STATE_DIR` で差し替え) / `off`)。
道具の file の取り方 = `FOREIGN_HUNK_TOOL` (既定 広い / `strict`)。 全ての error で黙る (fail-open)。
"""
from __future__ import annotations

import difflib
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import time

# ---------------------------------------------------------------- command の解析 (cd-git-write-guard.py と同じ区切り方)

QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SEP = re.compile(r"&&|\|\||;|\||&|\(|\)|\n")
LEADING_KW = {"do", "then", "else", "elif", "if", "while", "until", "{", "!", "time", "command", "builtin", "test", "["}
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
GIT_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
# git commit の option のうち値を次の語に取るもの
COMMIT_OPT_WITH_ARG = {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message", "--author",
                       "--date", "--cleanup", "-t", "--template", "--fixup", "--squash", "--trailer", "--pathspec-from-file"}
GIT_ADD_OPT_WITH_ARG = {"--chmod", "--pathspec-from-file"}


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _segments(cmd: str) -> list[tuple[str, str]]:
    """(元の部分, その部分の env 代入を含む先頭) の list。 heredoc の本文と quote の中の区切りは区切りにしない。"""
    masked = QUOTED.sub(_blank, HEREDOC.sub(_blank, cmd))
    spans, start = [], 0
    for m in SEP.finditer(masked):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(cmd)))
    out = []
    for a, b in spans:
        if masked[a:b].strip():
            out.append(cmd[a:b].strip())
    return out


def _words(seg: str) -> tuple[list[str], list[str]]:
    """(語, 先頭の env 代入)。"""
    try:
        words = shlex.split(seg, comments=True)
    except ValueError:
        words = seg.split()
    env = []
    while words and (words[0] in LEADING_KW or ASSIGN.match(words[0])):
        if ASSIGN.match(words[0]):
            env.append(words[0])
        words = words[1:]
    return words, env


def _resolve(target: str | None, here: str | None, home: str) -> str | None:
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


def _git_sub(words: list[str]) -> tuple[str | None, int, str | None]:
    """(subcommand, その語の位置, -C の dir)。 git でなければ (None, -1, None)。"""
    if not words or os.path.basename(words[0]) != "git":
        return None, -1, None
    i, cdir = 1, None
    while i < len(words):
        w = words[i]
        if w in GIT_OPT_WITH_ARG:
            if w == "-C" and i + 1 < len(words):
                cdir = words[i + 1]
            i += 2
            continue
        if w.startswith("-"):
            i += 1
            continue
        return w, i, cdir
    return None, -1, cdir


class Target:
    """commit 1 つの対象。 mode = "paths" | "index+paths" | "all" | "index"、 paths = 指定した path (絶対)、 added = 同じ
    command で git add する path (絶対)、 skip = 見ない理由 (空 = 見る)。 素の class にしてある = importlib で読む側の
    Python 3.9 で dataclass が落ちないため (data-pipeline-automation.md#importlib-dataclass)。"""

    def __init__(self, repo: str, mode: str, paths=None, added=None, skip: str = ""):
        self.repo, self.mode, self.skip = repo, mode, skip
        self.paths: list[str] = list(paths or [])
        self.added: list[str] = list(added or [])


def _repo_root(d: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def commit_targets(command: str, cwd: str | None, home: str | None = None) -> list[Target]:
    """command の中の git commit ごとの Target。 git commit が無ければ空。"""
    home = home or os.path.expanduser("~")
    here = os.path.realpath(cwd) if cwd else None
    added: dict[str, list[str]] = {}
    out: list[Target] = []
    for seg in _segments(command):
        words, env = _words(seg)
        if not words:
            continue
        if words[0] in ("cd", "pushd"):
            arg = next((w for w in words[1:] if not w.startswith("-") or w == "-"), None)
            here = _resolve(arg, here, home)
            continue
        sub, at, cdir = _git_sub(words)
        if sub not in ("add", "commit"):
            continue
        base = _resolve(cdir, here, home) if cdir else here
        if base is None:
            continue
        repo = _repo_root(base)
        if repo is None:
            continue
        args = words[at + 1:]
        if sub == "add":
            i = 0
            while i < len(args):
                a = args[i]
                if a in GIT_ADD_OPT_WITH_ARG:
                    i += 2
                    continue
                if a.startswith("-"):
                    i += 1
                    continue
                added.setdefault(repo, []).append(os.path.realpath(os.path.join(base, a)))
                i += 1
            continue
        t = Target(repo=repo, mode="index", added=list(added.get(repo, [])))
        if any(e.startswith("GIT_INDEX_FILE=") for e in env):
            t.skip = "一時 index"
        i, after_dd, paths, include = 0, False, [], False
        while i < len(args):
            a = args[i]
            if after_dd:
                paths.append(a)
            elif a == "--":
                after_dd = True
            elif a in COMMIT_OPT_WITH_ARG:
                i += 1
            elif a.startswith("--") and "=" in a:
                pass
            elif a in ("-a", "--all"):
                t.mode = "all"
            elif a == "--amend":
                t.skip = t.skip or "amend"
            elif a in ("-i", "--include"):
                include = True
            elif a.startswith("-") and len(a) > 1 and not a.startswith("--"):
                flags = a[1:]
                if "a" in flags and not any(c in flags for c in "mFCct"):
                    t.mode = "all"
                # -qm 'msg' のように値を取る短い option で終わる束は次の語を値に取る
                if flags[-1:] in ("m", "F", "C", "c", "t"):
                    i += 1
            elif not a.startswith("-"):
                paths.append(a)
            i += 1
        if paths:
            t.mode = "index+paths" if include else "paths"
            t.paths = [os.path.realpath(os.path.join(base, p)) for p in paths]
        gitdir = os.path.join(repo, ".git")
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
            if os.path.exists(os.path.join(gitdir, marker)):
                t.skip = t.skip or ("途中の " + marker)
        out.append(t)
    return out


# ---------------------------------------------------------------- 差分

class Hunk:
    """差分の塊。 path = 絶対 path、 start = 新しい側の最初の行 (1 始まり)。"""

    def __init__(self, path: str, start: int, added: list, removed: list):
        self.path, self.start, self.added, self.removed = path, start, added, removed


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


# 中身を行で照合できない file (PDF は NUL を持たず git が text と読むことがある = 実測で PDF・docx の「行」 が出た)
BINARY_EXT = {".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".zip", ".gz", ".tar", ".7z", ".png", ".jpg",
              ".jpeg", ".gif", ".heic", ".webp", ".ico", ".mp3", ".m4a", ".wav", ".aiff", ".mp4", ".mov", ".key", ".pages",
              ".numbers", ".ttf", ".otf", ".woff", ".woff2", ".sqlite", ".db", ".pyc", ".bin", ".dat", ".npz", ".npy", ".pkl"}
CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f]")


def _binary_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in BINARY_EXT


def parse_diff(text: str, repo: str) -> list[Hunk]:
    out: list[Hunk] = []
    path, cur = None, None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            path, cur = None, None
            continue
        if path and _binary_path(path):
            continue
        if line.startswith("+++ "):
            p = line[4:]
            if p.startswith('"'):
                try:
                    p = p.encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1").decode("utf-8")
                except (UnicodeError, ValueError):
                    pass
                p = p.strip('"')
            path = None if p == "/dev/null" else os.path.join(repo, p[2:] if p.startswith("b/") else p)
            continue
        if line.startswith("--- "):
            continue
        m = HUNK_RE.match(line)
        if m and path:
            cur = Hunk(path=path, start=int(m.group(3)), added=[], removed=[])
            out.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            cur.added.append(line[1:])
        elif line.startswith("-"):
            cur.removed.append(line[1:])
    return [h for h in out if not any(CONTROL.search(x) for x in h.added + h.removed)]


def diff_hunks(repo: str, head: list[str], paths: list[str] | None = None) -> list[Hunk]:
    """`git <head...> -U0 -- <paths>` の塊 (head = ["diff", "HEAD"] / ["diff", "--cached"] / ["show", "--format=", <rev>])。
    textconv は外す (PDF などを変換した行を照合しない)。 ただし git-crypt の file は textconv で平文に戻す
    (外すと暗号文の binary になり、 その file を見なくなる)。"""
    base = ["-U0", "--no-color", "--no-ext-diff", "--no-renames"]
    tail = ["--", *paths] if paths else []
    text = _git(repo, *head, *base, "--no-textconv", *tail, timeout=60)
    hunks = parse_diff(text, repo)
    binaries = re.findall(r"^Binary files .*? and b/(.+) differ$", text, re.M)
    if binaries:
        attrs = _git(repo, "check-attr", "diff", "--", *binaries)
        crypt = [m.group(1) for m in re.finditer(r"^(.+): diff: git-crypt$", attrs, re.M)]
        if crypt:
            hunks += parse_diff(_git(repo, *head, *base, "--", *crypt, timeout=60), repo)
    return hunks


def _git(repo: str, *args: str, timeout: int = 20) -> str:
    r = subprocess.run(["git", "-C", repo, "-c", "core.quotepath=false", *args], capture_output=True, text=True,
                       timeout=timeout, errors="replace")
    return r.stdout if r.returncode == 0 else ""


def _untracked(repo: str, paths: list[str]) -> list[str]:
    if not paths:
        return []
    rel = [os.path.relpath(p, repo) for p in paths]
    out = _git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", *rel)
    return [os.path.join(repo, x) for x in out.split("\0") if x]


def _new_file_hunk(path: str) -> Hunk | None:
    if _binary_path(path):
        return None
    try:
        if os.path.getsize(path) > 2_000_000:
            return None
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError):
        return None
    if CONTROL.search(text[:8000]):
        return None
    return Hunk(path=path, start=1, added=text.split("\n"), removed=[])


def target_hunks(t: Target) -> list[Hunk]:
    hunks: list[Hunk] = []
    rel = lambda ps: [os.path.relpath(p, t.repo) for p in ps]  # noqa: E731
    if t.mode == "paths":
        hunks += diff_hunks(t.repo, ["diff", "HEAD"], rel(t.paths))
        news = [p for p in _untracked(t.repo, t.paths) if any(p == a or p.startswith(a.rstrip("/") + "/") for a in t.added)]
    elif t.mode == "all":
        hunks += diff_hunks(t.repo, ["diff", "HEAD"])
        news = _untracked(t.repo, t.added)
    else:  # index / index+paths
        hunks += diff_hunks(t.repo, ["diff", "--cached"])
        extra = t.added + (t.paths if t.mode == "index+paths" else [])
        if extra:
            seen = {h.path for h in hunks}
            hunks += [h for h in diff_hunks(t.repo, ["diff", "HEAD"], rel(extra)) if h.path not in seen]
        news = _untracked(t.repo, extra)
    for p in news:
        h = _new_file_hunk(p)
        if h:
            hunks.append(h)
    return hunks


# ---------------------------------------------------------------- この session の書き込み

WRITE_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}


class Corpus:
    """この session の書き込みの文。 same = realpath -> その file への書き込みの文、 olds = realpath -> old_string (削除の
    照合)、 whole = Write で丸ごと書いた realpath、 texts = session の文 (全部の書き込みと Bash の command)。"""

    def __init__(self):
        self.same: dict[str, list[str]] = {}
        self.olds: dict[str, list[str]] = {}
        self.whole: set = set()
        self.texts: list[str] = []
        self.bash: list[str] = []
        self.frags: list[str] = []   # Bash の引用文字列と heredoc の本文の行 (sed・置換の道具・script に渡した断片)
        self.added_args: list[str] = []   # この session が `git add` に名指した path・dir (`-A`・`.` だけは数えない)
        self._blob: str | None = None
        self._seg: dict = {}

    def add_use(self, name: str, inp: dict) -> None:
        if name == "Bash":
            c = inp.get("command")
            if isinstance(c, str) and c:
                self.texts.append(c)
                self.bash.append(c)
                for m in QUOTED.finditer(c):
                    self.frags.extend(_frag_lines(m.group(0)[1:-1]))
                for m in HEREDOC.finditer(c):
                    self.frags.extend(_frag_lines(m.group(0)))
                if "add" in c:
                    for seg in _segments(c):
                        words, _env = _words(seg)
                        sub, at, _cdir = _git_sub(words)
                        if sub == "add":
                            self.added_args.extend(a.rstrip("/") for a in words[at + 1:]
                                                   if not a.startswith("-") and a.strip("./"))
                self._blob = None
            return
        if name not in WRITE_TOOLS:
            return
        fp = inp.get("file_path") or inp.get("notebook_path")
        if not isinstance(fp, str) or not fp:
            return
        rp = os.path.realpath(fp)
        news, olds = [], []
        if name == "Edit":
            news.append(inp.get("new_string") or "")
            olds.append(inp.get("old_string") or "")
        elif name == "MultiEdit":
            for e in inp.get("edits") or []:
                if isinstance(e, dict):
                    news.append(e.get("new_string") or "")
                    olds.append(e.get("old_string") or "")
        elif name == "Write":
            news.append(inp.get("content") or "")
            self.whole.add(rp)
        elif name == "NotebookEdit":
            news.append(inp.get("new_source") or "")
        news = [x for x in news if isinstance(x, str) and x]
        self.same.setdefault(rp, []).extend(news)
        self.olds.setdefault(rp, []).extend(x for x in olds if isinstance(x, str) and x)
        self.texts.extend(news)
        self._blob = None
        self._seg.pop(rp, None)

    def segments(self, rp: str) -> list[str]:
        if rp not in self._seg:
            segs = []
            for t in self.same.get(rp, []):
                segs.extend(s.strip() for s in t.split("\n") if s.strip())
            self._seg[rp] = segs
        return self._seg[rp]

    def blob(self) -> str:
        """session の文の全部。 JSON・Python の文字列の escape (\\n・\\"・\\\\) を戻した写しも足す (置換の組を JSON の
        file に書いて道具に渡した変更は、 escape されたまま記録に残る)。"""
        if self._blob is None:
            raw = "\n".join(self.texts)
            self._blob = raw + "\n" + raw.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
        return self._blob


FRAG_MIN = 10   # Bash の断片を行の一部と見る最短の長さ (短い語は多くの行に当たる)


def _frag_lines(text: str) -> list[str]:
    out = []
    for s in text.replace("\\n", "\n").split("\n"):
        s = s.strip()
        if len(s) >= FRAG_MIN:
            out.append(s)
    return out


def _transcript_files(transcript: str) -> list[str]:
    """会話記録とその subagent の記録 (<dir>/<session id>/subagents/*.jsonl)。"""
    files = [transcript]
    base = transcript[:-6] if transcript.endswith(".jsonl") else transcript
    files += sorted(glob.glob(os.path.join(base, "subagents", "*.jsonl")))
    return files


def iter_tool_uses(path: str, with_cwd: bool = False):
    """(timestamp, id, name, input) を記録の順に (with_cwd なら 5 つめにその行の cwd)。 読めない行は飛ばす。"""
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            if '"tool_use"' not in line or ('"type":"tool_use"' not in line and '"type": "tool_use"' not in line):
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            msg = e.get("message") if isinstance(e, dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
                    row = (e.get("timestamp") or "", b.get("id") or "", b.get("name") or "", b["input"])
                    yield row + (e.get("cwd"),) if with_cwd else row


def session_corpus(transcript: str | None, before: str | None = None, skip_id: str | None = None) -> Corpus:
    """この session の書き込みの文。 before (ISO の時刻) より前の tool 呼び出しだけ (replay 用)。"""
    c = Corpus()
    if not transcript:
        return c
    for p in _transcript_files(transcript):
        for ts, uid, name, inp in iter_tool_uses(p):
            if before and ts and ts > before:
                continue
            if skip_id and uid == skip_id:
                continue
            c.add_use(name, inp)
    return c


# ---------------------------------------------------------------- 照合

TRIVIAL = re.compile(r"^[\s\W_]*$")
MIN_LEN = 3
FRAGMENT_MIN = 6       # Edit の断片 (行の一部だけを置き換えた new_string) を行の一部と見る最短の長さ
SIMILAR = 0.8          # 後の Edit で一部が変わった行を自分の行と見る似方 (SequenceMatcher.ratio)
SIMILAR_MAX_SEGS = 4000


def meaningful(line: str) -> bool:
    s = line.strip()
    return len(s) >= MIN_LEN and not TRIVIAL.match(s)


def line_is_own(line: str, rp: str, c: Corpus) -> str:
    """'same' (同じ file の文) / 'session' (session の文) / '' (由来が分からない)。"""
    s = line.strip()
    segs = c.segments(rp)
    if rp in c.whole or segs:
        segset = set(segs)
        if s in segset:
            return "same"
        for g in segs:
            if (len(g) >= FRAGMENT_MIN and g in s) or (len(s) >= 8 and s in g):
                return "same"
        if len(segs) <= SIMILAR_MAX_SEGS:
            for g in segs:
                if abs(len(g) - len(s)) <= max(len(s), len(g)) * (1 - SIMILAR) + 2:
                    if difflib.SequenceMatcher(None, s, g, autojunk=False).ratio() >= SIMILAR:
                        return "same"
    if len(s) >= 8 and s in c.blob():
        return "session"
    for f in c.frags:
        if f in s and len(f) >= 0.3 * len(s):
            return "session"
    return ""


class Issue:
    """由来の分からない塊。 kind = "added" | "removed"、 first = 由来の分からない最初の行、 tool_hint = session の command が
    その file の名前を書いていた (道具が書いた可能性)。"""

    def __init__(self, path: str, start: int, first: str, kind: str, tool_hint: bool, lines=None):
        self.path, self.start, self.first, self.kind, self.tool_hint = path, start, first, kind, tool_hint
        self.lines: list[str] = list(lines or [first])  # 由来の分からない行の全部 (deny-once の鍵)


# 既定 = 広い (path の語として渡しただけでも道具の file)。 校正: 狭い (書き込みの形だけ) は判定する塊が増えるが、
# 増えた分はほぼ道具の書いた行の誤検出だった (実測、 数 = 個人層の記録)。 狭い版は FOREIGN_HUNK_TOOL=strict
TOOL_STRICT = os.environ.get("FOREIGN_HUNK_TOOL", "broad") == "strict"


def _git_added_by_name(rp: str, c: Corpus) -> bool:
    """この session が `git add` に、 この file かその上の dir を名指したか (生成器の出力の dir を足した形)。"""
    for a in c.added_args:
        a = a.lstrip("./") if a.startswith("./") else a
        if a and (rp.endswith("/" + a) or ("/" + a + "/") in rp):
            return True
    return False


def file_class(rp: str, c: Corpus, strict: bool | None = None) -> str:
    """'edited' = この session が Edit / Write で書いた file (行を照合する) / 'tool' = この session の Bash の command が
    書いた (かもしれない) file (道具・script が書いた分は記録から読めない = 判定しない。 strict = 書き込みの形だけ、
    広い = path の語として渡しただけでも) / 'named' = Edit も道具もしていないが `git add` に名指した file・dir の中
    (生成器の出力) / 'untouched' = どれでもない。"""
    strict = TOOL_STRICT if strict is None else strict
    if _named_in_bash(rp, c, strict=strict):
        return "tool"
    if rp in c.whole or c.same.get(rp):
        return "edited"
    if _git_added_by_name(rp, c):
        return "named"
    return "untouched"


def foreign_hunks(hunks: list[Hunk], c: Corpus, added_only: bool = False, mode: str = "paths",
                  skipped: dict | None = None, strict: bool | None = None) -> list[Issue]:
    """由来の分からない塊。 file ごとに file_class で分ける: edited = 行を照合、 tool = 見ない (skipped に数える)、
    untouched = path を指定した commit では見ない (自分で名指した file = 生成物・道具の出力)、 素の commit・-a では file ごとに
    1 件 (並列の session が stage した file を巻き込む形 = #staging-window-race)。"""
    out = []
    cls: dict[str, str] = {}
    flagged_untouched: set = set()
    for h in hunks:
        rp = os.path.realpath(h.path)
        k = cls.setdefault(rp, file_class(rp, c, strict))
        if k != "edited":
            if skipped is not None:
                skipped[k] = skipped.get(k, 0) + 1
            if k == "untouched" and mode in ("index", "all") and rp not in flagged_untouched:
                lines = [x.strip() for x in h.added + h.removed if meaningful(x)]
                if lines:
                    flagged_untouched.add(rp)
                    out.append(Issue(rp, h.start, lines[0][:80], "untouched", False, lines))
            continue
        add = [x for x in h.added if meaningful(x)]
        if add:
            bad = [x for x in add if not line_is_own(x, rp, c)]
            if bad:
                out.append(Issue(rp, h.start, bad[0].strip()[:80], "added", _named_in_bash(rp, c), [x.strip() for x in bad]))
            continue
        if added_only:
            continue
        rem = [x for x in h.removed if meaningful(x)]
        if not rem or rp in c.whole:
            continue
        olds = "\n".join(c.olds.get(rp, []))
        blob = c.blob()
        bad = [x.strip() for x in rem if x.strip() not in olds and x.strip() not in blob]
        if bad:
            out.append(Issue(rp, h.start, bad[0][:80], "removed", _named_in_bash(rp, c), bad))
    return out


# file を読むだけ・git の command (commit の `-- <path>` も) は「道具が書いた」 の印にしない
READ_ONLY_HEADS = {"git", "cat", "head", "tail", "less", "more", "grep", "rg", "wc", "ls", "test", "[", "echo", "printf",
                   "diff", "cmp", "shasum", "md5", "stat", "file", "open", "realpath", "readlink", "basename", "dirname"}


# 書き込みの形 (strict の時に「道具が書いた」 と見る形): 書く道具の先頭の語・書く option・書く subcommand
COPY_HEADS = {"cp", "mv", "rsync", "install", "ln", "ditto", "tee"}
INPLACE_HEADS = {"sed", "gsed", "perl"}
WRITE_WORDS = {"--write", "--apply", "--fix", "--in-place", "--inplace", "--update", "--edit", "--record", "--append",
               "--replace", "--replace-str", "--version", "--set", "--mark", "--migrate", "--rewrite", "--output", "-o",
               "apply", "write", "record", "update", "set", "migrate", "sync", "fix", "rewrite", "add", "edit"}
WRITE_CALL = re.compile(r"\.write\(|write_text\(|write_bytes\(|open\([^)]*['\"][wa]b?['\"]|json\.dump\(|yaml\.(?:safe_)?dump\(|os\.replace\(|shutil\.(?:copy|move)")


def _named_in_bash(rp: str, c: Corpus, strict: bool = False) -> bool:
    """session の Bash の command がこの file を書いた (か、 書いたかもしれない) か。
    strict=False: 読むだけ・git でない部分が path の語として渡した (確かめの script に渡しただけでも数える = 広い)。
    strict=True: 書き込みの形だけ = 出力の向け先 (`>`・`>>`・tee)、 写しの先 (cp・mv の最後の語)、 その場の置換
    (sed -i・perl -pi)、 書く option・subcommand つきで path を渡した script、 heredoc の script の本文が file の名前と
    書き込みの呼び出しを両方持つ。 どちらも要約の文や loop の値の中に名前が出るだけのものは数えない (実測で印が立ちすぎた)。"""
    name = os.path.basename(rp)
    if len(name) < 4:
        return False
    redirect = re.compile(r"(?:>>?|>\|)\s*['\"]?\S*" + re.escape(name))
    for cmd in c.bash:
        if name not in cmd:
            continue
        for m in HEREDOC.finditer(cmd):
            if name in m.group(0) and WRITE_CALL.search(m.group(0)):
                return True
        for seg in _segments(cmd):
            if name not in seg:
                continue
            if redirect.search(QUOTED.sub(_blank, seg)):
                return True   # cat > file・echo >> file (先頭の語が読む道具でも書いている)
            words, _env = _words(seg)
            head = os.path.basename(words[0]) if words else ""
            named = [w for w in words[1:] if os.path.basename(w.rstrip("/")) == name]
            if not named:
                continue
            if head in COPY_HEADS:
                if head == "tee" or os.path.basename(words[-1].rstrip("/")) == name:
                    return True
                continue
            if head in INPLACE_HEADS:
                if any(w.startswith("-i") or w.startswith("-pi") for w in words[1:]):
                    return True
                continue
            if head in READ_ONLY_HEADS:
                continue
            if not strict or any(w in WRITE_WORDS or w.split("=")[0] in WRITE_WORDS for w in words[1:]):
                return True
    return False


def find_issues(command: str, cwd: str | None = None, transcript: str | None = None,
                corpus: Corpus | None = None, added_only: bool = False) -> list[Issue]:
    """hook と校正の共通の述語。 git commit が無い・見ない形なら空。"""
    if "commit" not in command or "git" not in command:
        return []
    targets = [t for t in commit_targets(command, cwd) if not t.skip]
    if not targets:
        return []
    c = corpus if corpus is not None else session_corpus(transcript)
    c.add_use("Bash", {"command": command})   # 同じ command で道具を回して書く file も「道具」 に数える
    issues: list[Issue] = []
    for t in targets:
        issues += foreign_hunks(target_hunks(t), c, added_only, mode=t.mode)
    return issues


# ---------------------------------------------------------------- hook

def message(issues: list[Issue], cwd: str | None) -> str:
    base = cwd or os.getcwd()
    rows = []
    for i in issues[:6]:
        rel = os.path.relpath(i.path, base)
        rows.append(f"  - {rel}:{i.start} {'足した行' if i.kind == 'added' else '消した行'}「{i.first}」"
                    + (" (この session の command がこの file を名指している = 道具が書いた変更なら自分の分)" if i.tool_hint else ""))
    more = f"\n  … ほか {len(issues) - 6} 件" if len(issues) > 6 else ""
    return ("[foreign-hunk-check] この commit に、 この session が書いた文に無い変更の塊が "
            f"{len(issues)} 件入る (並列の session の未 commit の変更かもしれない):\n" + "\n".join(rows) + more + "\n"
            "自分の変更でなければ、 自分の分だけを commit する: python3 ~/Claude/claude-config/scripts/git-commit-own-hunk.py "
            "(--replace か --version。 正本 = conventions/multi-session-coordination.md#temp-index-commit)。 "
            "自分の変更 (道具・script が書いた分) なら、 そのまま進めてよい。 commit した後に気づいたら、 持ち主の session に知らせる。")


def _state_dir() -> str:
    return os.environ.get("FOREIGN_HUNK_STATE_DIR") or os.path.expanduser("~/.claude/state/foreign-hunk")


def _seen_before(session: str, issues: list[Issue]) -> bool:
    """deny-once: 同じ session が同じ塊の組で前に止められていれば True (今回は通す)。 初めてなら記録して False。
    記録に失敗したら True (止めっぱなしにしない = fail-open)。"""
    import hashlib
    key = hashlib.sha1("\n".join(sorted(f"{i.path}\0{i.kind}\0" + "\0".join(i.lines) for i in issues)).encode()).hexdigest()
    sid = "".join(ch for ch in (session or "nosession") if ch.isalnum() or ch in "-_")[:80] or "nosession"
    path = os.path.join(_state_dir(), sid + ".txt")
    try:
        seen = set(open(path).read().split()) if os.path.exists(path) else set()
        if key in seen:
            return True
        os.makedirs(_state_dir(), exist_ok=True)
        with open(path, "a") as f:
            f.write(key + "\n")
        return False
    except OSError:
        return True


def hook_main() -> int:
    mode = os.environ.get("FOREIGN_HUNK_MODE", "notice")
    if mode == "off":
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
        if data.get("tool_name") != "Bash":
            return 0
        cmd = (data.get("tool_input") or {}).get("command") or ""
        if "commit" not in cmd:
            return 0
        issues = find_issues(cmd, data.get("cwd"), data.get("transcript_path"))
    except Exception:  # fail-open
        return 0
    if not issues:
        return 0
    text = message(issues, data.get("cwd"))
    deny = mode == "deny"
    if mode == "deny-once":
        deny = not _seen_before(data.get("session_id") or "", issues)
        text += ("\n(同じ塊の組で打ち直すと次は通す = 自分の変更と確かめたら、 同じ command をそのまま打ち直す。 "
                 "止められた command は 1 段も走っていない = 数える段・fetch の段も一緒に打ち直す)" if deny
                 else "\n(前に知らせた同じ塊の組なので通した)")
    if deny:
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": text}}
    else:
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}
    print(json.dumps(out, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- 校正 (会話記録の commit の再生)

def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))


def replay(projects: list[str], since: str, roots: list[str], verbose: bool = False) -> dict:
    """会話記録の session ごとに、 その session の印 (Agent-Session: claude:<id>) を持つ commit を探し、 commit を作った
    Bash の command を時刻と hook と同じ解析で当て、 その時点までの書き込みの文で commit の差分を判定する (hook は commit の
    前の作業 tree を見るが、 ここは commit の差分を見る = 同じ command の中の書き込みは、 その command を session の文に
    足して打ち消す)。 確かめ = 由来の分からない行のうち 12 文字以上の行の過半が、 同じ file への他の session の Edit / Write
    の文 (commit の時刻より前) にあれば「他の session の行が入った」 と数える (Bash で書いた他の session の行は数えない =
    下限)。"""
    transcripts = []
    t0 = time.mktime(time.strptime(since, "%Y-%m-%d"))
    for pd in projects:
        transcripts += [p for p in glob.glob(os.path.join(pd, "*", "*.jsonl")) if os.path.getmtime(p) >= t0]
    sid_of = {os.path.basename(p)[:-6]: p for p in transcripts}
    # 他の session の書き込みの行の索引: (realpath, 12 文字以上の行) -> {session: 最初の時刻}。 削除は old_string の行
    index: dict[tuple, dict[str, str]] = {}
    old_index: dict[tuple, dict[str, str]] = {}
    main_of: dict[str, list] = {}
    sub_of: dict[str, list] = {}

    def put(ix, rp, text, sid, ts):
        if not isinstance(text, str):
            return
        for s in text.split("\n"):
            s = s.strip()
            if len(s) >= 12:
                d = ix.setdefault((rp, s), {})
                if sid not in d or (ts or "") < d[sid]:
                    d[sid] = ts or ""

    for sid, p in sid_of.items():
        files = _transcript_files(p)
        main_of[sid] = list(iter_tool_uses(files[0], with_cwd=True))
        sub_of[sid] = [r for f in files[1:] for r in iter_tool_uses(f, with_cwd=True)]
        for ts, _uid, name, inp, _cwd in main_of[sid] + sub_of[sid]:
            if name not in WRITE_TOOLS:
                continue
            fp = inp.get("file_path") or inp.get("notebook_path")
            if not isinstance(fp, str) or not fp:
                continue
            rp = os.path.realpath(fp)
            if name == "MultiEdit":
                for e in inp.get("edits") or []:
                    if isinstance(e, dict):
                        put(index, rp, e.get("new_string"), sid, ts)
                        put(old_index, rp, e.get("old_string"), sid, ts)
            else:
                put(index, rp, inp.get("new_string") or inp.get("content") or inp.get("new_source"), sid, ts)
                put(old_index, rp, inp.get("old_string"), sid, ts)
    commits: dict[str, list] = {}
    for repo in roots:
        out = _git(repo, "log", "--no-merges", f"--since={since}",
                   "--format=%H%x1f%ct%x1f%(trailers:key=Agent-Session,valueonly,separator=%x2C)", timeout=60)
        for row in out.split("\n"):
            parts = row.split("\x1f")
            if len(parts) != 3 or not parts[2].startswith("claude:"):
                continue
            commits.setdefault(parts[2].split(",")[0][7:].strip(), []).append((repo, parts[0], int(parts[1])))
    stats = {"sessions": 0, "commits": 0, "commits_by_git_commit": 0, "not_judged": 0, "fired": 0,
             "fired_confirmed": 0, "fired_untouched_only": 0, "hunks": 0, "hunks_skipped_tool": 0,
             "hunks_skipped_untouched": 0, "issues": 0, "issues_confirmed": 0, "by_mode": {}, "seconds": 0.0, "examples": []}
    t_start = time.time()
    for sid, cl in commits.items():
        if sid not in main_of:
            continue
        stats["sessions"] += 1
        bash = sorted(((ts, uid, inp.get("command") or "", cwd) for ts, uid, name, inp, cwd in main_of[sid] + sub_of[sid]
                       if name == "Bash" and ts and "commit" in (inp.get("command") or "")), key=lambda x: x[0])
        for repo, h, ct in cl:
            stats["commits"] += 1
            # commit の時刻の直前 (5 分以内) の、 この repo への git commit の部分を持つ Bash (時刻は秒の丸めに 3 秒の余裕)。
            # git commit を内側で打つ道具の commit は当たらない = hook の射程外
            hit = None
            for ts, uid, cmd, cwd in bash:
                if not (_iso(ct - 300) <= ts[:19] <= _iso(ct + 3)):
                    continue
                tg = [t for t in commit_targets(cmd, cwd) if os.path.realpath(t.repo) == os.path.realpath(repo)]
                if tg:
                    hit = (ts, uid, cmd, tg)
            if hit is None:
                continue
            ts, uid, cmd, tg = hit
            stats["commits_by_git_commit"] += 1
            live = [t for t in tg if not t.skip]
            if not live:
                stats["not_judged"] += 1
                continue
            mode = live[-1].mode
            stats["by_mode"][mode] = stats["by_mode"].get(mode, 0) + 1
            c = Corpus()
            # 本体の記録は順に読み、 commit の呼び出しで切る (時刻の欄が空の行がある = 時刻で切ると後の呼び出しが混ざる、
            # 実測)。 subagent の記録は時刻で切る
            for ts2, uid2, name, inp, _cwd in main_of[sid]:
                if uid2 == uid:
                    break
                c.add_use(name, inp)
            for ts2, uid2, name, inp, _cwd in sub_of[sid]:
                if ts2 and ts2 <= ts and uid2 != uid:
                    c.add_use(name, inp)
            c.add_use("Bash", {"command": cmd})
            hunks = diff_hunks(repo, ["show", "--format=", h])
            stats["hunks"] += len(hunks)
            for variant, strict in (("broad", False), ("strict", True)):
                sk: dict = {}
                iss = foreign_hunks(hunks, c, mode=mode, skipped=sk, strict=strict)
                v = stats.setdefault(variant, {"fired": 0, "issues": 0, "skipped": {}, "commits": []})
                for k2, n2 in sk.items():
                    v["skipped"][k2] = v["skipped"].get(k2, 0) + n2
                if iss:
                    v["fired"] += 1
                    v["issues"] += len(iss)
                    v["commits"].append(h[:8])
                if strict == TOOL_STRICT:   # 例と確かめは既定の版で
                    issues = iss
            if not issues:
                continue
            stats["fired"] += 1
            stats["issues"] += len(issues)
            others = []
            for i in issues:
                ix = old_index if i.kind == "removed" else index
                long_lines = [x for x in i.lines if len(x) >= 12]
                found: dict[str, int] = {}
                for x in long_lines:
                    for s2, t2 in ix.get((i.path, x), {}).items():
                        if s2 != sid and t2 <= _iso(ct + 3):
                            found[s2] = found.get(s2, 0) + 1
                best = max(found.items(), key=lambda kv: kv[1]) if found else None
                ok = bool(best and long_lines and best[1] * 2 > len(long_lines))
                others.append([best[0]] if ok else [])
            n_conf = sum(1 for o in others if o)
            stats["issues_confirmed"] += n_conf
            if n_conf:
                stats["fired_confirmed"] += 1
            elif all(i.kind == "untouched" for i in issues):
                stats["fired_untouched_only"] += 1
            stats["examples"].append({"session": sid[:8], "repo": os.path.basename(repo), "commit": h[:8], "mode": mode,
                                      "cmd": cmd[:160], "n_issues": len(issues),
                                      "issues": [{"path": os.path.relpath(i.path, repo), "line": i.start, "kind": i.kind,
                                                  "first": i.first[:60], "n_lines": len(i.lines),
                                                  "other_sessions": [s[:8] for s in o]}
                                                 for i, o in list(zip(issues, others))[:6]]})
    stats["seconds"] = round(time.time() - t_start, 1)
    return stats


def _default_roots(base: str) -> list[str]:
    roots = []
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        if os.path.isdir(os.path.join(d, ".git")):
            roots.append(d)
    return roots


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    import tempfile
    fails = []

    def check(name, ok):
        print(("PASS: " if ok else "FAIL: ") + name)
        if not ok:
            fails.append(name)

    env = dict(os.environ, GIT_AUTHOR_DATE="2000-01-01T00:00:00Z", GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)

    def git(repo, *a):
        subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)

    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.realpath(os.path.join(tmp, "r"))
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "t@example.invalid")
        git(repo, "config", "user.name", "t")
        doc = os.path.join(repo, "doc.md")
        with open(doc, "w") as f:
            f.write("# Doc\n\nfirst line of the document\n\nsecond paragraph here\n")
        git(repo, "add", "doc.md")
        git(repo, "commit", "-q", "-m", "init", "--no-verify")
        # 自分の Edit: 段落を 1 行足す。 相手: 別の段落を 1 行足す (未 commit)
        mine = "my added sentence about the build"
        with open(doc, "a") as f:
            f.write(mine + "\n")
        c = Corpus()
        c.add_use("Edit", {"file_path": doc, "old_string": "second paragraph here\n", "new_string": "second paragraph here\n" + mine + "\n"})
        check("own Edit only: nothing to report",
              find_issues("git commit -q -m 'x' -- doc.md", repo, corpus=c) == [])
        with open(doc) as f:
            body = f.read()
        with open(doc, "w") as f:
            f.write(body.replace("# Doc\n", "# Doc\n\nthe other session's paragraph\n"))
        got = find_issues("git commit -q -m 'x' -- doc.md", repo, corpus=c)
        check("a hunk from the other session is named", len(got) == 1 and "other session" in got[0].first and got[0].kind == "added")
        check("message names the file and the line", "doc.md:3" in message(got, repo))
        check("a heredoc message does not hide the commit",
              len(find_issues("git commit -q -F - -- doc.md <<'EOF'\nmsg; git status\nEOF", repo, corpus=c)) == 1)
        check("the same commit chained after fetch and a count test is found",
              len(find_issues('git fetch -q && test "$(git diff -U0 -- doc.md | grep -c \'^@@\')" = 2 && git commit -q -m m -- doc.md', repo, corpus=c)) == 1)
        check("cd to the repo is followed", len(find_issues(f"cd {repo} && git commit -m m -- doc.md", tmp, corpus=c)) == 1)
        check("git -C is followed", len(find_issues(f"git -C {repo} commit -m m -- doc.md", tmp, corpus=c)) == 1)
        check("a commit with no git commit in it is ignored", find_issues("git status && echo commit", repo, corpus=c) == [])
        check("amend is not judged", find_issues("git commit --amend --no-edit -- doc.md", repo, corpus=c) == [])
        check("a temporary index commit is not judged",
              find_issues("GIT_INDEX_FILE=/tmp/i git commit -m m", repo, corpus=c) == [])
        # 相手の行が Bash の heredoc にあれば自分の分 (session の文)
        c2 = Corpus()
        c2.add_use("Edit", {"file_path": doc, "old_string": "a", "new_string": mine})
        c2.add_use("Bash", {"command": "python3 - <<'EOF'\nopen('doc.md','a').write(\"the other session's paragraph\")\nEOF"})
        check("a line written by this session's Bash counts as own",
              find_issues("git commit -m m -- doc.md", repo, corpus=c2) == [])
        # Edit の断片 (行の中の語だけを置き換えた) は行の一部として自分の分
        with open(doc, "w") as f:
            f.write(body.replace("first line of the document", "first line of the revised document"))
        c3 = Corpus()
        c3.add_use("Edit", {"file_path": doc, "old_string": "of the document", "new_string": "of the revised document"})
        c3.add_use("Edit", {"file_path": doc, "old_string": "x", "new_string": mine})
        check("an Edit that replaced part of a line counts the whole line as own",
              find_issues("git commit -m m -- doc.md", repo, corpus=c3) == [])
        # 後の Edit で一部が変わった行 (似た行) は自分の分
        with open(doc, "w") as f:
            f.write(body.replace(mine, "my added sentence about the builds"))
        c4 = Corpus()
        c4.add_use("Edit", {"file_path": doc, "old_string": "x", "new_string": mine})
        check("a line later changed by a few characters still counts as own",
              find_issues("git commit -m m -- doc.md", repo, corpus=c4) == [])
        # 空白だけ・記号だけの hunk は数えない
        with open(doc, "w") as f:
            f.write(body + "\n\n---\n")
        check("blank and symbol-only lines are not counted", find_issues("git commit -m m -- doc.md", repo, corpus=c4) == [])
        # 消しただけの hunk: 自分の old_string なら通る、 相手の削除なら出す
        with open(doc, "w") as f:
            f.write("# Doc\n\nsecond paragraph here\n" + mine + "\n")
        c5 = Corpus()
        c5.add_use("Edit", {"file_path": doc, "old_string": "first line of the document\n\n", "new_string": ""})
        c5.add_use("Edit", {"file_path": doc, "old_string": "x", "new_string": mine})
        check("a deletion from this session's old_string counts as own", find_issues("git commit -m m -- doc.md", repo, corpus=c5) == [])
        got = find_issues("git commit -m m -- doc.md", repo, corpus=c4)
        check("a deletion this session did not make is named", len(got) == 1 and got[0].kind == "removed")
        check("--added-only leaves deletions out", find_issues("git commit -m m -- doc.md", repo, corpus=c4, added_only=True) == [])
        # 新しい file を同じ command で add: 全行を追加として照合する (Write の content なら通る、 後から足された行は出す)
        new = os.path.join(repo, "new.md")
        with open(new, "w") as f:
            f.write("a new file written here\nan extra line from elsewhere\n")
        with open(doc, "w") as f:
            f.write(body + mine + "\n")
        c6 = Corpus()
        c6.add_use("Edit", {"file_path": doc, "old_string": "x", "new_string": mine})
        c6.add_use("Write", {"file_path": new, "content": "a new file written here\n"})
        got = find_issues("git add new.md && git commit -m m -- doc.md new.md", repo, corpus=c6)
        check("an untracked file added in the same command is judged line by line",
              len(got) == 1 and got[0].path == os.path.realpath(new) and got[0].first == "an extra line from elsewhere")
        c7 = Corpus()
        c7.add_use("Edit", {"file_path": doc, "old_string": "x", "new_string": mine})
        c7.add_use("Bash", {"command": "python3 tool.py --write new.md"})
        sk: dict = {}
        c7.add_use("Bash", {"command": "git add new.md && git commit -m m -- doc.md new.md"})
        got = foreign_hunks(target_hunks(commit_targets("git add new.md && git commit -m m -- doc.md new.md", repo)[0]), c7, skipped=sk)
        check("a file this session's command passed as a path (a tool wrote it) is not judged, and is counted",
              got == [] and sk.get("tool") == 1)
        # 「道具の file」 の狭い判定 (既定) と広い判定
        cc = Corpus()
        cc.add_use("Bash", {"command": "cat > notes/new.md <<'EOF'\nbody\nEOF"})
        check("a file written by `cat >` (a reading command with a redirect) is a tool file", file_class(new, cc) == "tool")
        cc = Corpus()
        cc.add_use("Edit", {"file_path": new, "old_string": "x", "new_string": "y"})
        cc.add_use("Bash", {"command": "python3 scripts/check-links.py --files new.md --list"})
        check("a checker given the path without a write option: strict = edited, broad = tool",
              file_class(new, cc, strict=True) == "edited" and file_class(new, cc, strict=False) == "tool")
        cc = Corpus()
        cc.add_use("Bash", {"command": "python3 - <<'EOF'\nopen('new.md', 'w').write('x')\nEOF"})
        check("a heredoc script that opens the file for writing is a tool file", file_class(new, cc, strict=True) == "tool")
        cc = Corpus()
        cc.add_use("Bash", {"command": "python3 build.py && git add -A data docs"})
        check("a file under a dir this session named in git add is named (generator output)",
              file_class(os.path.join(repo, "docs", "ep", "index.html"), cc) == "named"
              and file_class(os.path.join(repo, "other", "x.md"), cc) == "untouched")
        cc = Corpus()
        cc.add_use("Bash", {"command": "cp /tmp/candidate.md new.md && cp new.md /tmp/backup.md"})
        check("cp counts the destination only", file_class(new, cc) == "tool" and file_class(doc, cc) == "untouched")
        c9 = Corpus()
        c9.add_use("Edit", {"file_path": doc, "old_string": "x", "new_string": mine})
        check("a file the session never touched, named in a path commit, is not judged",
              find_issues("git add new.md && git commit -m m -- doc.md new.md", repo, corpus=c9) == [])
        # 断片と escape: 置換の道具に渡した引用文字列・JSON に escape して書いた置換の組
        with open(new, "w") as f:
            f.write("a new file written here\nthe replacement text passed to a tool\nbeta line two of the edits file\n")
        c8 = Corpus()
        c8.add_use("Write", {"file_path": new, "content": "a new file written here\n"})
        c8.add_use("Bash", {"command": "python3 apply.py --old 'x' --new 'replacement text passed to a tool'"})
        c8.add_use("Write", {"file_path": os.path.join(tmp, "edits.json"), "content": '{"new": "alpha line one\\nbeta line two of the edits file"}'})
        check("a quoted fragment of this session's command and a JSON-escaped line count as own",
              find_issues("git add new.md && git commit -m m -- new.md", repo, corpus=c8) == [])
        # binary (PDF は NUL を持たず text と読まれることがある) は見ない
        pdf = os.path.join(repo, "a.pdf")
        with open(pdf, "w") as f:
            f.write("%PDF-1.7\n<</Type/Catalog>>\n")
        check("a PDF is not judged", find_issues("git add a.pdf && git commit -m m -- a.pdf", repo, corpus=Corpus()) == [])
        os.remove(pdf)
        # 素の commit は index を見る (相手が add した file も出す)
        os.remove(new)
        other = os.path.join(repo, "other.md")
        with open(other, "w") as f:
            f.write("staged by the other session\n")
        git(repo, "add", "other.md")
        got = find_issues("git commit -m m", repo, corpus=c6)
        check("a plain commit judges the index (a file the other session staged)",
              any(i.path == os.path.realpath(other) for i in got))
        check("a path commit leaves the other staged file out",
              not any(i.path == os.path.realpath(other) for i in find_issues("git commit -m m -- doc.md", repo, corpus=c6)))
        git(repo, "reset", "-q", "--", "other.md")
        # merge の途中は見ない
        open(os.path.join(repo, ".git", "MERGE_HEAD"), "w").close()
        check("a commit in the middle of a merge is not judged", find_issues("git commit -m m -- doc.md", repo, corpus=Corpus()) == [])
        os.remove(os.path.join(repo, ".git", "MERGE_HEAD"))
        # 会話記録から読む (subagent の記録も)
        tr = os.path.join(tmp, "s.jsonl")
        with open(tr, "w") as f:
            f.write(json.dumps({"type": "assistant", "timestamp": "2000-01-01T00:00:01Z", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": doc, "old_string": "x", "new_string": mine}}]}}) + "\n")
            f.write('{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":"ok"}]}}\n')
        os.makedirs(os.path.join(tmp, "s", "subagents"))
        with open(os.path.join(tmp, "s", "subagents", "a.jsonl"), "w") as f:
            f.write(json.dumps({"type": "assistant", "timestamp": "2000-01-01T00:00:02Z", "message": {"content": [
                {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": doc, "old_string": "y", "new_string": "line by a subagent of this session"}}]}}) + "\n")
        with open(doc, "w") as f:
            f.write(body + mine + "\nline by a subagent of this session\n")
        check("the transcript and its subagents are read", find_issues("git commit -m m -- doc.md", repo, transcript=tr) == [])
        check("before= keeps only the calls up to the time",
              "line by a subagent of this session" not in "\n".join(session_corpus(tr, before="2000-01-01T00:00:01Z").texts))
        # hook の入出力
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m m -- doc.md"}, "cwd": repo, "transcript_path": tr})
        with open(doc, "w") as f:
            f.write(body + mine + "\nline by a subagent of this session\nthe other session's line\n")
        here = os.path.abspath(__file__)
        r = subprocess.run([sys.executable, here, "--hook"], input=payload, capture_output=True, text=True,
                           env=dict(os.environ, FOREIGN_HUNK_MODE="notice"))
        out = json.loads(r.stdout or "{}").get("hookSpecificOutput", {})
        check("hook notice mode: additionalContext, no decision", "additionalContext" in out and "permissionDecision" not in out)
        r = subprocess.run([sys.executable, here, "--hook"], input=payload, capture_output=True, text=True,
                           env=dict(os.environ, FOREIGN_HUNK_MODE="deny"))
        out = json.loads(r.stdout or "{}").get("hookSpecificOutput", {})
        check("hook deny mode: deny with the reason", out.get("permissionDecision") == "deny" and "doc.md" in out.get("permissionDecisionReason", ""))
        st = os.path.join(tmp, "state")
        once = dict(os.environ, FOREIGN_HUNK_MODE="deny-once", FOREIGN_HUNK_STATE_DIR=st)
        p2 = json.dumps({**json.loads(payload), "session_id": "s1"})
        r1 = subprocess.run([sys.executable, here, "--hook"], input=p2, capture_output=True, text=True, env=once)
        r2 = subprocess.run([sys.executable, here, "--hook"], input=p2, capture_output=True, text=True, env=once)
        o1 = json.loads(r1.stdout or "{}").get("hookSpecificOutput", {})
        o2 = json.loads(r2.stdout or "{}").get("hookSpecificOutput", {})
        check("hook deny-once: the first time denies, the same set re-issued passes with a note",
              o1.get("permissionDecision") == "deny" and "permissionDecision" not in o2 and "通した" in o2.get("additionalContext", ""))
        with open(doc, "a") as f:
            f.write("yet another line from elsewhere\n")
        r3 = subprocess.run([sys.executable, here, "--hook"], input=p2, capture_output=True, text=True, env=once)
        check("hook deny-once: a new hunk in the set denies again",
              json.loads(r3.stdout or "{}").get("hookSpecificOutput", {}).get("permissionDecision") == "deny")
        r = subprocess.run([sys.executable, here, "--hook"], input="not json", capture_output=True, text=True)
        check("hook fails open on bad input", r.returncode == 0 and not r.stdout.strip())
        r = subprocess.run([sys.executable, here, "--hook"], input=payload, capture_output=True, text=True,
                           env=dict(os.environ, FOREIGN_HUNK_MODE="off"))
        check("hook off mode is silent", not r.stdout.strip())
    print(f"foreign-hunk-check selftest: {len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selftest"]:
        return selftest()
    if argv[:1] == ["--hook"]:
        return hook_main()
    if argv[:1] == ["--check"] and len(argv) >= 2:
        cwd, tr = os.getcwd(), None
        rest = argv[2:]
        if "--cwd" in rest:
            cwd = rest[rest.index("--cwd") + 1]
        if "--transcript" in rest:
            tr = rest[rest.index("--transcript") + 1]
        issues = find_issues(argv[1], cwd, tr)
        print(message(issues, cwd) if issues else "由来の分からない変更の塊は無い")
        return 1 if issues else 0
    if argv[:1] == ["--replay"]:
        since = argv[argv.index("--since") + 1] if "--since" in argv else time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400))
        projects = [argv[i + 1] for i, a in enumerate(argv) if a == "--projects"] or [
            d for d in (os.path.expanduser("~/.claude/projects"),) + tuple(glob.glob(os.path.expanduser("~/.claude-*/projects"))) if os.path.isdir(d)]
        base = argv[argv.index("--base") + 1] if "--base" in argv else os.path.expanduser("~/Claude")
        stats = replay(projects, since, _default_roots(base))
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        return 0
    print(__doc__.split("## 使い方")[1].split("hook の出力")[0].strip())
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
