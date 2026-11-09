#!/usr/bin/env python3
"""upstream-pr.py — 層1 の repo (claude-config・ai-collaboration) を push できない人の clone で、 手元の変更を「気づく → 準備 → 本人の 1 回の確認 → fork から PR → 手元の main を upstream に戻す」 まで運ぶ (status / prepare / send / restore / after)。 所有者 (push できる人) の機械では何もしない。 --selftest 内蔵。

## なぜ在るか

層1 の repo に push できるのは所有者だけで、 ほかの人の手元の変更は fork からの PR でしか upstream に入らない。
手順は文書 (closing-sweep.md の PR の節) にしか無かったので、 締めの外で書き換えた変更は commit されても push を
断られて手元に残り、 共同研究者の clone では最新化が止まり続けた。 この道具は手順を 1 本にまとめ、 どの入口
(turn の終わり・session の開始・共同研究者の点検) からも同じ形で呼べ、 公開の前の漏洩の検査を飛ばせないようにする。

## 段

  status   作業中の変更・upstream より先の commit・push できるか・fork の remote・gh の有無と認証・出して閉じていない PR を
           repo ごとに 1 block で出す。 変更が無ければ何も出さない。 push できる人 (所有者) にも何も出さない。 公開しない
  prepare  変更を upstream の最新から切った branch `upstream-pr/<slug>` に移す (作業中の変更は 1 commit に、 手元の commit は
           cherry-pick)。 枝は .git の中の一時の作業場所で組む = 本人の作業ツリーには触らない。 下の漏洩の検査を回し、
           PR の本文の雛形を作る。 公開しない
  send     本人の OK の後に (--yes)、 漏洩の検査をもう一度回して通ったときだけ fork へ push → `gh pr create`。 公開する
  restore  手元の main を upstream に合わせる。 変更は PR の branch と backup の ref (refs/upstream-pr/backup/<時刻>) に残る。
           stash は使わない。 公開しない
  after    出した PR が merge されたら手元の branch を消す。 merge されずに閉じたら 1 回だけ伝える。 公開しない
  drop     準備したが出さないと決めた PR を捨てる (branch の先は backup の ref に残る)。 公開しない

所有者の判定: GitHub の権限で admin、 または push できて repo の持ち主と同じ login なら所有者 = 何もしない。
push できるが所有者でない人 (書き込み権限のある第三者) は origin の branch から PR (main には push しない)。
push できない人は fork から PR。 最後に確かめた結果は .git/upstream-pr/permission.json に 24 時間残し、 gh が使えない
ときはその結果を使う (所有者の機械で、 一時の network の切れで黙るのをやめないため)。 PR の記録 = 同じ dir の state.json
(lock の中でだけ書く)、 隣の repo の公開状態の cache = visibility.json (7 日)。

## 漏洩の検査 (fork への push の前。 走れなければ出さない)

PR に載る面の全部 = 各 commit の足した行・各 commit の message・新しく入る file の名前・branch 名・PR の題と本文・
commit の author と committer の email。
  - 各 commit の足した行に、 公開 repo の pre-commit と同じ runner (public-precommit-runner.sh) を当てる。 PR の題・本文・
    branch 名・commit の message・新しく入る file の名前は 1 つの text にして最後の commit の足した行と一緒に当てる
    (= 構造の検査 〔email・home の path・IP・token〕 も掛かる)。 runner は tree の棚卸しと同じ印 (CLAUDE_PUBLIC_GATE_REPORT_LEAK_PASS=1) で呼び、
    「漏洩の段を通った」 の 1 行が出たときだけ通ったとする
  - 各 commit の message と、 PR の題・本文に commit message の検査 (commit-msg-leak-guard-runner.sh) を当てる
  - 隣にある private な repo の文を逐語の検査 (check-unpublished-quote.py) の源にする: 同じ親の dir にある git repo の
    うち、 公開の印 (.claude/public-repo.marker) が無く、 GitHub で public でないもの (remote の無いもの・GitHub の外の
    もの・gh で確かめられないものを含む) の文 (.md .tex .txt .yaml .yml .rst .org)。 個人層の無い人でも、 共同研究の
    原稿や記録の文がそのまま PR に上がるのを止める
  - この session で非公開の source から読んだ値の検査 (check-session-carryover.py) を、 session の env があるときに当てる
  - author と committer の email が GitHub の noreply でなければ止める (noreply の値は gh api user から出す)
  - 隣の private な repo の名前が PR に出るときは止めずに知らせる (確認の問いの行に載る)
  - 検査の engine は upstream の版 (<base remote>/<base branch> の scripts/) を .git の中に取り出して使う = 手元で
    検査を書き換えていても、 その変更で検査が弱まらない (取り出せないときは手元の版を使い、 そう言う)
  - 言い換えは機械に掛からない: prepare の後に agent が「この PR から、 その人・第三者・未公開の原稿について何が
    分かるか」 を 1 回当て、 結果を確認の問いの行に書く (claude-config/CLAUDE.md#non-identifier-content-leak)

## 終了値

  0 = 済んだ / 何もすることが無い   1 = 漏洩の検査が止めた (send しない)   2 = 使い方・前提の誤り (競合を含む)
  3 = 検査が走らなかった (send しない)   4 = この環境では書けない・network が無い → 承認の要る command として 1 回出す
  5 = gh が無い・login していない

## 呼び方

  upstream-pr.py status [--repo DIR ...] [--json]      (--repo の既定 = この道具の repo と、 隣の ai-collaboration)
  upstream-pr.py prepare --repo DIR --slug NAME --title TITLE [--body-file F] [--paths P ... | --commits SHA ...] [--reset-author]
                 (--paths も --commits も無ければ、 作業中の変更の全部と upstream より先の commit の全部を 1 本の PR に。
                  片方だけ渡すと、 もう片方は入れない。 --commits all = 先の commit の全部)
  upstream-pr.py send --repo DIR --slug NAME --yes [--title TITLE] [--body-file F]
  upstream-pr.py restore --repo DIR
  upstream-pr.py after [--repo DIR ...]
  upstream-pr.py drop --repo DIR --slug NAME
  upstream-pr.py --selftest

手元の設定 (git config、 clone ごと): upstream-pr.disable = true で何も出さない / upstream-pr.base = owner/repo で base の
repo を明示する (remote の URL から読めないとき)。 試験用の env: UPSTREAM_PR_ENGINE_DIR (検査の engine の dir) /
UPSTREAM_PR_GH (gh の path、 空 = gh が無い)。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

try:  # Windows (MSYS) の python には無い = 排他の lock を省く
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

SELF = Path(__file__).resolve()
TOOL_SCRIPTS = SELF.parent
TOOL_REPO = TOOL_SCRIPTS.parent
STATE_DIRNAME = "upstream-pr"
BRANCH_PREFIX = "upstream-pr/"
BACKUP_PREFIX = "refs/upstream-pr/backup/"
PERM_TTL = 24 * 3600
VIS_TTL = 7 * 24 * 3600
SOURCE_SUFFIXES = (".md", ".tex", ".txt", ".yaml", ".yml", ".rst", ".org")
BODY_PLACEHOLDER = "<!-- upstream-pr:"
TEXT_FILE = ".upstream-pr-text.md"
NOREPLY_RE = re.compile(r"^(?:\d+\+)?[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?@users\.noreply\.github\.com$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
GITHUB_RE = re.compile(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/*$")
AGENT_ENV = ("CLAUDE_CONFIG_AGENT_SESSION", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "CODEX_THREAD_ID")
ENGINE_FILES = ("public-precommit-runner.sh", "commit-msg-leak-guard-runner.sh", "check-unpublished-quote.py")
RUNNER_PASS = "[public-precommit-runner] leak tiers passed"
NETWORK_HINTS = ("error connecting", "dial tcp", "no such host", "could not resolve", "timeout", "timed out",
                 "network is unreachable", "connection refused", "connection reset", "temporary failure in name resolution")
AUTH_HINTS = ("gh auth login", "not logged", "authentication", "bad credentials", "http 401", "requires authentication")

EXIT_OK, EXIT_BLOCKED, EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_APPROVAL, EXIT_NO_GH = 0, 1, 2, 3, 4, 5


class Fail(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


# ----------------------------------------------------------------------------- process helpers
def clean_env(extra=None, drop=()):
    env = dict(os.environ)
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"):
        env.pop(k, None)
    env["GIT_LITERAL_PATHSPECS"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    for k in drop:
        env.pop(k, None)
    if extra:
        env.update(extra)
    return env


def git(repo, *args, check=True, env=None, input=None, timeout=300):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env or clean_env(),
                       input=input, timeout=timeout)
    if check and r.returncode != 0:
        raise Fail(EXIT_USAGE, f"git {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r


def git_bytes(repo, *args, env=None, input=None):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=env or clean_env(), input=input)
    return r


def hooks_off(repo_state_dir: Path):
    empty = repo_state_dir / "no-hooks"
    empty.mkdir(parents=True, exist_ok=True)
    return ["-c", f"core.hooksPath={empty}"]


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def tool_cmd(*args):
    return "python3 " + shlex.join([str(SELF), *[str(a) for a in args]])


# ----------------------------------------------------------------------------- gh
def classify_gh_error(text: str) -> str:
    t = text.lower()
    if any(h in t for h in NETWORK_HINTS):
        return "network"
    if any(h in t for h in AUTH_HINTS):
        return "auth"
    if "404" in t or "not found" in t:
        return "notfound"
    return "error"


def gh_exe():
    if "UPSTREAM_PR_GH" in os.environ:  # 試験用: 空 = gh が無い
        return os.environ["UPSTREAM_PR_GH"] or None
    return shutil.which("gh")


def gh_run(args, cwd=None, timeout=60):
    """(rc, stdout, stderr, kind). kind = ok / no-gh / network / auth / notfound / error."""
    exe = gh_exe()
    if not exe:
        return 127, "", "", "no-gh"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, cwd=cwd, env=clean_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout", "network"
    if r.returncode == 0:
        return 0, r.stdout, r.stderr, "ok"
    return r.returncode, r.stdout, r.stderr, classify_gh_error(r.stderr + r.stdout)


def gh_json(args, cwd=None):
    rc, out, err, kind = gh_run(args, cwd=cwd)
    if kind != "ok":
        return None, kind, (err or out).strip()[:300]
    try:
        return json.loads(out or "null"), "ok", ""
    except json.JSONDecodeError:
        return None, "error", "gh の出力が JSON でない"


def gh_missing_line(kind: str) -> str:
    if kind == "no-gh":
        return "gh が無い: gh (GitHub CLI) を入れて `gh auth login` を 1 回 (それまでも prepare と restore は手元で動く = 最新化を止めない)"
    return "gh が login していない: `gh auth login` を 1 回 (それまでも prepare と restore は手元で動く = 最新化を止めない)"


def parse_slug(url: str):
    m = GITHUB_RE.search((url or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


# ----------------------------------------------------------------------------- repo context
class Repo:
    def __init__(self, path):
        path = Path(os.path.expanduser(str(path)))
        if not path.is_dir():
            raise Fail(EXIT_USAGE, f"dir が無い: {path}")
        r = git(path, "rev-parse", "--show-toplevel", check=False)
        if r.returncode != 0:
            raise Fail(EXIT_USAGE, f"git の repo でない: {path}")
        self.root = Path(r.stdout.strip())
        common = git(self.root, "rev-parse", "--git-common-dir").stdout.strip()
        self.common = (self.root / common).resolve() if not os.path.isabs(common) else Path(common)
        self.state_dir = self.common / STATE_DIRNAME
        self.name = self.root.name
        remotes = git(self.root, "remote").stdout.split()
        self.base_remote = "upstream" if "upstream" in remotes else "origin"
        self.has_remote = self.base_remote in remotes
        self.base_branch = self._base_branch()
        self.base_ref = f"refs/remotes/{self.base_remote}/{self.base_branch}"
        self.slug = (self.config("upstream-pr.base") or
                     parse_slug(git(self.root, "remote", "get-url", self.base_remote, check=False).stdout))
        self.origin_slug = parse_slug(git(self.root, "remote", "get-url", "origin", check=False).stdout)
        self.remotes = remotes

    def config(self, key):
        r = git(self.root, "config", "--get", key, check=False)
        return r.stdout.strip() or None

    def disabled(self):
        return (self.config("upstream-pr.disable") or "").lower() in ("1", "true", "yes", "on")

    def _base_branch(self):
        r = git(self.root, "symbolic-ref", "--short", "-q", f"refs/remotes/{self.base_remote}/HEAD", check=False)
        name = r.stdout.strip()
        if name.startswith(self.base_remote + "/"):
            return name[len(self.base_remote) + 1:]
        return self.config("upstream-pr.base-branch") or "main"

    def rev(self, ref):
        r = git(self.root, "rev-parse", "-q", "--verify", ref + "^{commit}", check=False)
        return r.stdout.strip() or None

    def current_branch(self):
        return git(self.root, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip() or None

    # --- state
    def load_state(self):
        p = self.state_dir / "state.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"prs": {}}

    def save_state(self, st):
        self._write_json("state.json", st)

    # cache (権限・隣の repo の公開状態) は state.json と別の file = lock の外で書いても PR の記録を上書きしない
    def load_cache(self, name):
        try:
            return json.loads((self.state_dir / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_cache(self, name, data):
        try:
            self._write_json(f"{name}.json", data)
        except OSError:
            pass

    def _write_json(self, fname, data):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.state_dir, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, self.state_dir / fname)

    def lock(self):
        return _Lock(self.state_dir / "lock")


class _Lock:
    def __init__(self, path: Path):
        self.path, self.fh = path, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        if fcntl:
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if fcntl and self.fh:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
        if self.fh:
            self.fh.close()


def ensure_writable(repo: Repo, what: str):
    """sandbox (Codex など) で .git に書けないなら、 承認の要る command として出す (終了値 4)。"""
    try:
        repo.state_dir.mkdir(parents=True, exist_ok=True)
        fd, p = tempfile.mkstemp(dir=repo.common, prefix=".upstream-pr-probe-")
        os.close(fd)
        os.unlink(p)
    except OSError:
        raise Fail(EXIT_APPROVAL, approval_text(f"この環境では {repo.common} に書けない (sandbox)", what))


def approval_text(reason: str, what: str) -> str:
    argv = [a for a in sys.argv[1:]]
    return (f"{reason}。 次の command を承認の要る command として 1 回出す ({what}):\n  "
            f"python3 {shlex.join([str(SELF), *argv])}")


# ----------------------------------------------------------------------------- local changes
def wip_paths(repo: Repo):
    out = git(repo.root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    items = out.split("\0")
    paths, i = [], 0
    while i < len(items):
        it = items[i]
        if not it:
            i += 1
            continue
        code, path = it[:2], it[3:]
        paths.append(path)
        if code[0] in "RC":  # rename / copy: 次の要素が元の path
            i += 1
            if i < len(items) and items[i]:
                paths.append(items[i])
        i += 1
    return sorted(set(paths))


def untracked_paths(repo: Repo):
    out = git(repo.root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    return [p for p in out.split("\0") if p]


def ahead_commits(repo: Repo):
    if not repo.rev(repo.base_ref):
        return [], 0
    if (repo.current_branch() or "").startswith(BRANCH_PREFIX):
        return [], 0  # PR の branch を手元で使っている = その commit は PR に入っている
    commits = git(repo.root, "rev-list", "--reverse", "--no-merges", f"{repo.base_ref}..HEAD").stdout.split()
    merges = git(repo.root, "rev-list", "--merges", f"{repo.base_ref}..HEAD").stdout.split()
    return commits, len(merges)


def snapshot_tree(repo: Repo, paths=None):
    """作業ツリーの今の中身 (untracked を含む) の tree を、 本人の index に触らずに作る。"""
    with tempfile.TemporaryDirectory() as td:
        env = clean_env({"GIT_INDEX_FILE": os.path.join(td, "index")})
        git(repo.root, "read-tree", "HEAD", env=env)
        if paths is None:
            git(repo.root, "add", "-A", env=env)
        elif paths:
            git(repo.root, "add", "-A", "--", *paths, env=env)
        return git(repo.root, "write-tree", env=env).stdout.strip()


def subject(repo: Repo, sha: str) -> str:
    return git(repo.root, "log", "-1", "--format=%s", sha).stdout.strip()


# ----------------------------------------------------------------------------- permission
def permission(repo: Repo, refresh=False):
    """{'role': owner|writer|none|None, 'login', 'id', 'unknown': <理由>, 'stale': bool}"""
    cache = repo.load_cache("permission") or None
    if cache and cache.get("slug") != repo.slug:
        cache = None
    if cache and not refresh and time.time() - cache.get("checked_epoch", 0) < PERM_TTL:
        return dict(cache, stale=False)
    if not repo.slug:
        return {"role": None, "unknown": "not-github"}
    user, kind, _ = gh_json(["api", "user"])
    info = None
    if user is not None:
        info, kind, _ = gh_json(["api", f"repos/{repo.slug}"])
    if user is None or info is None:
        if cache:
            return dict(cache, stale=True, unknown=kind)
        return {"role": None, "unknown": kind}
    perms = info.get("permissions") or {}
    owner_login = ((info.get("owner") or {}).get("login") or "")
    login = user.get("login") or ""
    if perms.get("admin") or (perms.get("push") and login.lower() == owner_login.lower()):
        role = "owner"
    elif perms.get("push"):
        role = "writer"
    else:
        role = "none"
    cache = {"slug": repo.slug, "role": role, "login": login, "id": user.get("id"), "owner": owner_login,
             "fork": bool(info.get("fork")), "parent": ((info.get("parent") or {}).get("full_name")),
             "checked_epoch": int(time.time())}
    repo.save_cache("permission", cache)
    return dict(cache, stale=False)


def noreply_line(perm) -> str:
    if perm and perm.get("login") and perm.get("id"):
        addr = f"{perm['id']}+{perm['login']}@users.noreply.github.com"
        return f"git config user.email {addr}"
    return "git config user.email <id>+<login>@users.noreply.github.com  (値 = gh api user の id と login)"


# ----------------------------------------------------------------------------- leak inspection
def personal_layer() -> str:
    lib = TOOL_SCRIPTS / "lib" / "find-personal-layer.sh"
    if os.environ.get("CLAUDE_PERSONAL_LAYER"):
        return os.environ["CLAUDE_PERSONAL_LAYER"]
    if not lib.is_file() or not shutil.which("bash"):
        return "none"
    r = subprocess.run(["bash", "-c", '. "$1" && find_personal_layer', "_", str(lib)], capture_output=True, text=True)
    return r.stdout.strip() or "none"


def engine_dir():
    """(dir, note)。 upstream の版の scripts/ を .git の中に取り出す (手元で検査を書き換えていても弱まらない)。"""
    override = os.environ.get("UPSTREAM_PR_ENGINE_DIR")
    if override:
        return Path(override), "env で指定した版"
    try:
        tool = Repo(TOOL_REPO)
        tree = git(tool.root, "rev-parse", "-q", "--verify", f"{tool.base_ref}:scripts", check=False).stdout.strip()
        if not tree:
            raise Fail(EXIT_UNAVAILABLE, "upstream の scripts/ が無い")
        dest = tool.state_dir / f"engine-{tree[:12]}"
        if not all((dest / f).is_file() for f in ENGINE_FILES):
            data = git_bytes(tool.root, "archive", "--format=tar", f"{tool.base_ref}:scripts")
            if data.returncode != 0:
                raise Fail(EXIT_UNAVAILABLE, "git archive に失敗")
            tool.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(dir=tool.state_dir, prefix=".engine-"))
            with tarfile.open(fileobj=io.BytesIO(data.stdout)) as tf:
                members = [m for m in tf.getmembers()
                           if not m.name.startswith("/") and ".." not in Path(m.name).parts]
                if hasattr(tarfile, "data_filter"):
                    tf.extractall(tmp, members=members, filter="data")
                else:  # pragma: no cover (python < 3.12 で filter の無い版)
                    tf.extractall(tmp, members=members)
            shutil.rmtree(dest, ignore_errors=True)
            os.replace(tmp, dest)
            for old in tool.state_dir.glob("engine-*"):
                if old != dest:
                    shutil.rmtree(old, ignore_errors=True)
        return dest, f"upstream の版 ({tool.base_remote}/{tool.base_branch})"
    except (Fail, OSError, tarfile.TarError, subprocess.SubprocessError):
        return TOOL_SCRIPTS, "手元の版 (upstream の版を取り出せなかった)"


def visibility(repo: Repo, d: Path, cache: dict):
    url = git(d, "remote", "get-url", "origin", check=False).stdout.strip()
    if not url:
        return "private"  # remote が無い
    slug = parse_slug(url)
    if not slug:
        return "private"  # GitHub の外 = 確かめられない = 源に入れる (止める側)
    hit = cache.get(slug)
    if hit and time.time() - hit.get("epoch", 0) < VIS_TTL:
        return hit["vis"]
    info, kind, _ = gh_json(["api", f"repos/{slug}"])
    vis = "public" if (info is not None and info.get("private") is False) else "private"
    if kind in ("ok", "notfound"):
        cache[slug] = {"vis": vis, "epoch": int(time.time())}
    return vis


def sources_config(repo: Repo):
    """隣の private な repo の文を逐語の検査の源にする config を書く。 (path, private な repo の名前)"""
    parent = repo.root.parent
    cache = repo.load_cache("visibility")
    private = []
    for d in sorted(parent.iterdir()):
        try:
            if not d.is_dir() or d.name.startswith("."):
                continue
            if (d / ".claude" / "public-repo.marker").exists() or d.resolve() == repo.root.resolve():
                continue
            if (d / ".git").exists() and visibility(repo, d, cache) != "public":
                private.append(d)
        except OSError:
            continue
    repo.save_cache("visibility", cache)
    # engine の discover は root の直下の dir を全部たどってから exclude で落とす = 親が home なら ~/Library まで歩く。
    # private な repo だけへの symlink を並べた dir を root にする (直下の名前 = repo の名前 = 定型文の除外も repo 単位で効く)
    root = repo.state_dir / "sources"
    shutil.rmtree(root, ignore_errors=True)  # 中の symlink だけを消す (先は辿らない)
    use_discover = not any(ch.isspace() for ch in str(root))
    try:
        root.mkdir(parents=True, exist_ok=True)
        for d in private:
            (root / d.name).symlink_to(d, target_is_directory=True)
    except OSError:
        use_discover = False
    if use_discover:
        lines = [f"discover: {root} {' '.join(SOURCE_SUFFIXES)}"]
    else:  # path に空白がある・symlink を作れない = repo ごとの glob (定型文の除外は効かない = 止める側に倒れる)
        lines = [f"include: {d}/**/*{suf}" for d in private for suf in SOURCE_SUFFIXES]
    path = repo.state_dir / "unpublished-sources.txt"
    path.write_text("# upstream-pr.py が書いた = 隣の private な repo を逐語の検査の源にする (手で直さない)\n"
                    + "\n".join(lines) + "\n", encoding="utf-8")
    return path, [d.name for d in private]


class Scan:
    def __init__(self):
        self.blocked, self.unavailable, self.warnings, self.notes = [], [], [], []

    @property
    def result(self):
        if self.blocked:
            return "blocked"
        if self.unavailable:
            return "unavailable"
        return "pass"

    def as_dict(self):
        return {"result": self.result, "blocked": self.blocked, "unavailable": self.unavailable,
                "warnings": self.warnings, "notes": self.notes, "at": now_iso()}


def _tail(text, n=14):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _hit_lines(text):
    keep = [ln for ln in text.splitlines()
            if re.search(r"\[tier-|rejected|BLOCK|\[unpublished-quote\]|\[activity-facts\]|\[confidential-leak\]|"
                         r"\[value-index\]|hits:|^\s+\[", ln)]
    return "\n".join(keep[:16]) or _tail(text)


def run_engine(cmd, cwd, env, timeout=600):
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"起動できない: {exc!r}"


def check_staged(wt: Path, label: str, eng: Path, layer: str, sources: Path, scan: Scan):
    staged = git(wt, "diff", "--cached", "--name-only", "--diff-filter=d").stdout.strip()
    if not staged:
        return
    env = clean_env({"CLAUDE_PUBLIC_GATE_REPORT_LEAK_PASS": "1", "CLAUDE_PERSONAL_LAYER": layer}, drop=AGENT_ENV)
    rc, out = run_engine(["bash", str(eng / "public-precommit-runner.sh")], wt, env)
    if RUNNER_PASS in out:
        pass
    elif "commit rejected" in out or "check-student-identifiers: BLOCK" in out:
        scan.blocked.append(f"{label}: 公開 repo の pre-commit の検査が止めた\n{_hit_lines(out)}")
    else:
        scan.unavailable.append(f"{label}: 公開 repo の pre-commit の検査が最後まで走らなかった (rc={rc})\n{_tail(out, 6)}")
    env = clean_env({"CLAUDE_PERSONAL_LAYER": layer}, drop=AGENT_ENV)
    rc, out = run_engine([sys.executable, str(eng / "check-unpublished-quote.py"), "--config", str(sources)], wt, env)
    if rc == 1 and "[unpublished-quote] the staged change contains" in out:
        scan.blocked.append(f"{label}: 隣の private な repo の文がそのまま入っている\n{_hit_lines(out)}")
    elif rc not in (0, 1):
        scan.unavailable.append(f"{label}: 隣の private な repo の文の検査が走らなかった (rc={rc})\n{_tail(out, 4)}")
    sc = eng / "check-session-carryover.py"
    if sc.is_file() and (os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_CARRYOVER_TRANSCRIPT")):
        rc, out = run_engine([sys.executable, str(sc), "--staged", "--repo", str(wt)], wt,
                             clean_env({"CLAUDE_PERSONAL_LAYER": layer}))
        if rc == 1 and "check-session-carryover: BLOCK" in out:
            scan.blocked.append(f"{label}: この session で非公開の source から読んだ値が入っている\n{_hit_lines(out)}")


def check_message(wt: Path, label: str, text: str, eng: Path, layer: str, sources: Path, scan: Scan):
    with tempfile.NamedTemporaryFile("w", suffix=".msg", delete=False, encoding="utf-8") as f:
        f.write(text)
        msg = f.name
    try:
        env = clean_env({"CLAUDE_PERSONAL_LAYER": layer}, drop=AGENT_ENV)
        rc, out = run_engine(["bash", str(eng / "commit-msg-leak-guard-runner.sh"), msg, "message"], wt, env)
        if rc == 1:
            scan.blocked.append(f"{label}: commit message の検査が止めた\n{_hit_lines(out)}")
        elif rc != 0 or "matcher library missing" in out:
            scan.unavailable.append(f"{label}: commit message の検査が走らなかった (rc={rc})\n{_tail(out, 4)}")
        rc, out = run_engine([sys.executable, str(eng / "check-unpublished-quote.py"), "--config", str(sources),
                              "--message-file", msg], wt, env)
        if rc == 1 and "[unpublished-quote] the commit message contains" in out:
            scan.blocked.append(f"{label}: 隣の private な repo の文がそのまま入っている\n{_hit_lines(out)}")
        elif rc not in (0, 1):
            scan.unavailable.append(f"{label}: 隣の private な repo の文の検査が走らなかった (rc={rc})")
    finally:
        os.unlink(msg)


def pr_text(branch, title, body, messages, files=()):
    parts = [f"branch: {branch}", f"title: {title}", "", body or "", ""]
    if files:  # file の名前も公開される面 (名前に人名・案件名が入る形を構造の検査と語の検査に掛ける)
        parts += ["files:"] + [f"  {f}" for f in files] + [""]
    for i, m in enumerate(messages, 1):
        parts += [f"commit {i}:", m, ""]
    return "\n".join(parts)


def scan_branch(repo: Repo, slug: str, base_sha: str, title: str, body: str, perm) -> Scan:
    scan = Scan()
    branch = BRANCH_PREFIX + slug
    eng, note = engine_dir()
    scan.notes.append(f"検査の engine = {note}")
    missing = [f for f in ENGINE_FILES if not (eng / f).is_file()]
    if missing or not shutil.which("bash"):
        scan.unavailable.append(f"検査の engine が読めない ({', '.join(missing) or 'bash が無い'}) = 出さない")
        return scan
    layer = personal_layer()
    # 逐語の検査の索引の cache を .git の中に置く = sandbox (Codex) で ~/.cache に書けなくても走る
    os.environ["XDG_CACHE_HOME"] = str(repo.state_dir / "cache")
    sources, private_names = sources_config(repo)
    scan.notes.append(f"逐語の検査の源 = 隣の private な repo {len(private_names)} 個")
    commits = git(repo.root, "rev-list", "--reverse", f"{base_sha}..{branch}").stdout.split()
    if not commits:
        scan.unavailable.append("PR の branch に commit が無い")
        return scan
    for c in commits:
        ae, ce = git(repo.root, "log", "-1", "--format=%ae%x00%ce", c).stdout.strip().split("\0")
        for who, addr in (("author", ae), ("committer", ce)):
            if not NOREPLY_RE.match(addr):
                scan.blocked.append(f"commit {c[:7]} の {who} の email が GitHub の noreply でない ({addr}) = 公開の履歴に"
                                    f"焼き付く。 直し方: {noreply_line(perm)} を打ってから prepare を --reset-author つきで"
                                    f"やり直す")
    messages = [git(repo.root, "log", "-1", "--format=%B", c).stdout for c in commits]
    files = git(repo.root, "diff", "--name-only", "--diff-filter=AR", f"{base_sha}..{branch}").stdout.split("\n")
    text = pr_text(branch, title, body, messages, [f for f in files if f])
    wt = repo.state_dir / f"scan-{slug}"
    _drop_worktree(repo, wt)
    ho = hooks_off(repo.state_dir)
    git(repo.root, *ho, "worktree", "add", "-q", "--detach", str(wt), commits[-1])
    try:
        extra = wt / ".claude" / "pre-commit-extra.sh"
        for i, c in enumerate(commits):
            # HEAD = 親、 index = この commit = 「この commit で足した行」 が staged に見える
            git(wt, *ho, "reset", "-q", "--hard", c)
            git(wt, "reset", "-q", "--soft", f"{c}^")
            if extra.exists():  # repo 固有の commit 規律 = 漏洩の検査でない (重い) ので鎖を切る。 staged の中身は変えない
                extra.chmod(extra.stat().st_mode & ~0o111)
            label = f"commit {c[:7]} ({subject(repo, c)[:50]})"
            if i == len(commits) - 1:
                (wt / TEXT_FILE).write_text(text, encoding="utf-8")
                git(wt, "add", "-f", "--", TEXT_FILE)
                label += " + PR の題・本文・branch 名・commit message"
            check_staged(wt, label, eng, layer, sources, scan)
            check_message(wt, f"commit {c[:7]} の message", messages[i], eng, layer, sources, scan)
        check_message(wt, "PR の題と本文", f"{title}\n\n{body}\n\nbranch: {branch}\n", eng, layer, sources, scan)
        added = git(repo.root, "diff", "-U0", "--no-color", f"{base_sha}..{branch}").stdout
        hay = (added + "\n" + text).lower()
        for name in private_names:
            if len(name) >= 4 and re.search(rf"(?<![a-z0-9_-]){re.escape(name.lower())}(?![a-z0-9_-])", hay):
                scan.warnings.append(f"隣の private な repo の名前「{name}」 が PR に出る (公開してよいか本人に聞く)")
    finally:
        _drop_worktree(repo, wt)
    return scan


def _drop_worktree(repo: Repo, wt: Path):
    if wt.exists():
        git(repo.root, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(wt, ignore_errors=True)
    git(repo.root, "worktree", "prune", check=False)


# ----------------------------------------------------------------------------- branch building
def build_branch(repo: Repo, slug, base_sha, commits, paths, title, reset_author):
    branch = BRANCH_PREFIX + slug
    ho = hooks_off(repo.state_dir)
    wip_tree = snapshot_tree(repo, paths) if paths else None
    wt = repo.state_dir / f"build-{slug}"
    _drop_worktree(repo, wt)
    git(repo.root, *ho, "worktree", "add", "-q", "-b", branch, str(wt), base_sha)
    ok = False
    try:
        for c in commits:
            r = git(wt, *ho, "cherry-pick", "--allow-empty", c, check=False)
            if r.returncode != 0:
                git(wt, "cherry-pick", "--abort", check=False)
                raise Fail(EXIT_USAGE, f"手元の commit {c[:7]} ({subject(repo, c)[:50]}) を upstream の最新の上に載せられない"
                                       f" (競合)。 その commit を直すか、 --commits / --paths で分けて PR にする")
            if reset_author:
                git(wt, *ho, "commit", "-q", "--amend", "--no-edit", "--reset-author")
        if paths:
            diff = git_bytes(repo.root, "diff", "--binary", "HEAD", wip_tree, "--", *paths)
            if diff.returncode != 0:
                raise Fail(EXIT_USAGE, "作業中の変更の差分を作れない")
            if diff.stdout.strip():
                r = git_bytes(wt, "apply", "--3way", "--whitespace=nowarn", input=diff.stdout)
                if r.returncode != 0:
                    raise Fail(EXIT_USAGE, "作業中の変更を upstream の最新の上に当てられない (競合): "
                                           + r.stderr.decode("utf-8", "replace").strip()[:300])
                r = git(wt, *ho, "commit", "-q", "-m", title, check=False)
                if r.returncode != 0:
                    raise Fail(EXIT_USAGE, "作業中の変更を commit できない (user.name / user.email が無い?): "
                                           + (r.stderr or r.stdout).strip()[:300])
        if git(repo.root, "rev-parse", branch).stdout.strip() == base_sha:
            raise Fail(EXIT_USAGE, "PR にする変更が upstream に既に入っている (branch に差分が無い)")
        ok = True
    finally:
        _drop_worktree(repo, wt)
        if not ok:
            git(repo.root, "branch", "-D", branch, check=False)
    return branch


BODY_TEMPLATE = """{marker} この行を消して、 下の 4 節を書く (誰が読んでも分かる一般形で。 その人・第三者・未公開の原稿のことを書かない) -->
## 概要

## 背景 (何が困っていたか)

## 変更

## 検証
"""


def body_ok(body: str) -> bool:
    if not body or BODY_PLACEHOLDER in body:
        return False
    text = "\n".join(ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#"))
    return bool(text.strip())


def changed_files(repo: Repo, base_sha, branch):
    return git(repo.root, "diff", "--name-only", f"{base_sha}..{branch}").stdout.split()


def ask_line(repo: Repo, entry) -> str:
    files = entry.get("files", [])
    shown = ", ".join(files[:4]) + (f" ほか {len(files) - 4}" if len(files) > 4 else "")
    res = {"pass": "通った (機械の検査。 言い換えは agent が当てる)", "blocked": "止めた", "unavailable": "走らなかった"}
    line = f"{repo.name}: 「{entry.get('title')}」 | {shown} | 漏洩の検査 = {res.get(entry.get('scan', {}).get('result'), '未')}"
    warns = entry.get("scan", {}).get("warnings") or []
    if warns:
        line += " | ⚠️ " + " / ".join(warns)
    return line


# ----------------------------------------------------------------------------- commands
def cmd_prepare(a) -> int:
    repo = Repo(a.repo)
    if not SLUG_RE.match(a.slug or ""):
        raise Fail(EXIT_USAGE, "--slug は英小文字・数字・. _ - の 48 字まで (branch 名 upstream-pr/<slug> になる)")
    if not (a.title or "").strip():
        raise Fail(EXIT_USAGE, "--title が要る (PR の題。 作業中の変更の commit message にもなる)")
    ensure_writable(repo, f"PR の準備「{a.title}」")
    perm = permission(repo)
    if perm.get("role") == "owner":
        print(f"{repo.name}: push できる (所有者) = PR にせず main に直接 commit する。 何もしない")
        return EXIT_OK
    if not repo.has_remote:
        raise Fail(EXIT_USAGE, f"remote {repo.base_remote} が無い")
    with repo.lock():
        notes = []
        r = git(repo.root, "fetch", "-q", repo.base_remote, repo.base_branch, check=False, timeout=120)
        if r.returncode != 0:
            notes.append(f"upstream の最新を取れなかった ({repo.base_remote}/{repo.base_branch} は手元の記録の版)")
        base_sha = repo.rev(repo.base_ref)
        if not base_sha:
            raise Fail(EXIT_USAGE, f"{repo.base_ref} が無い (git fetch {repo.base_remote} を 1 回)")
        all_commits, merges = ahead_commits(repo)
        all_paths = wip_paths(repo)
        if a.commits is None and a.paths is None:
            commits, paths = all_commits, all_paths
        else:
            if a.commits is None:
                commits = []
            elif a.commits == ["all"]:
                commits = all_commits
            else:
                want = [repo.rev(c) for c in a.commits]
                if None in want or any(c not in all_commits for c in want):
                    raise Fail(EXIT_USAGE, "--commits に upstream より先の手元の commit でないものがある")
                commits = [c for c in all_commits if c in want]
            if a.paths is None:
                paths = []
            elif a.paths == ["all"]:
                paths = all_paths
            else:
                paths = [p for p in a.paths]
                stray = [p for p in paths if p not in all_paths]
                if stray:
                    raise Fail(EXIT_USAGE, f"--paths に作業中の変更でない path がある: {', '.join(stray[:5])}")
        if merges:
            notes.append(f"手元の merge commit {merges} 本は PR に入れない (中身の commit は入る)")
        if not commits and not paths:
            print(f"{repo.name}: PR にする手元の変更が無い")
            return EXIT_OK
        st = repo.load_state()
        old = st.get("prs", {}).get(a.slug)
        branch = BRANCH_PREFIX + a.slug
        if old and old.get("state") == "sent":
            raise Fail(EXIT_USAGE, f"{branch} は PR として出した ({old.get('url')})。 別の --slug にする")
        if repo.rev(f"refs/heads/{branch}"):
            if not old:
                raise Fail(EXIT_USAGE, f"branch {branch} が既にある (この道具の記録に無い)。 別の --slug にする")
            git(repo.root, "branch", "-D", branch)
        build_branch(repo, a.slug, base_sha, commits, paths, a.title.strip(), a.reset_author)
        body_path = repo.state_dir / f"{a.slug}.body.md"
        if a.body_file:
            body_path.write_text(Path(a.body_file).read_text(encoding="utf-8"), encoding="utf-8")
        elif not body_path.exists():
            body_path.write_text(BODY_TEMPLATE.format(marker=BODY_PLACEHOLDER), encoding="utf-8")
        body = body_path.read_text(encoding="utf-8")
        scan = scan_branch(repo, a.slug, base_sha, a.title.strip(), body, perm)
        entry = {"branch": branch, "title": a.title.strip(), "body_file": str(body_path), "base": repo.slug,
                 "base_branch": repo.base_branch, "base_sha": base_sha, "state": "prepared",
                 "files": changed_files(repo, base_sha, branch), "commits": commits, "paths": paths,
                 "scan": scan.as_dict(), "prepared_at": now_iso()}
        st.setdefault("prs", {})[a.slug] = entry
        repo.save_state(st)
    print(f"{repo.name}: PR の branch {branch} を作った (upstream {repo.base_remote}/{repo.base_branch} から。"
          f" 作業ツリーはそのまま)")
    for n in notes + scan.notes:
        print(f"  · {n}")
    print(f"  変えた file {len(entry['files'])} 個: {', '.join(entry['files'][:8])}")
    _print_scan(scan)
    if scan.result == "pass":
        if not body_ok(body):
            print(f"  → PR の本文を書く: {body_path} (または send --body-file <file>)")
        print("  → 送る前に agent が当てる問い: 「この PR から、 その人・第三者・未公開の原稿について何が分かるか」"
              " (claude-config/CLAUDE.md#non-identifier-content-leak)。 答えを確認の問いの行に書く")
        print(f"  → 確認の問いの行 (その turn の PR を全部並べて 1 回だけ聞く): {ask_line(repo, entry)}")
        print(f"  → 本人の OK の後: {tool_cmd('send', '--repo', repo.root, '--slug', a.slug, '--yes')}")
        return EXIT_OK
    return EXIT_BLOCKED if scan.result == "blocked" else EXIT_UNAVAILABLE


def _print_scan(scan: Scan):
    if scan.result == "pass":
        print("  漏洩の検査 = 通った (機械の検査。 言い換えは機械に掛からない)")
    for w in scan.warnings:
        print(f"  ⚠️ {w}")
    for b in scan.blocked:
        print("  🛑 " + b.replace("\n", "\n     "))
    for u in scan.unavailable:
        print("  ⛔ " + u.replace("\n", "\n     "))
    if scan.result == "blocked":
        print("  → 漏洩の検査が止めた = 出さない。 中身を一般形に直して prepare をやり直す")
    elif scan.result == "unavailable":
        print("  → 検査が走らなかった = 出さない (直してから prepare をやり直す)")


def cmd_send(a) -> int:
    repo = Repo(a.repo)
    st = repo.load_state()
    entry = st.get("prs", {}).get(a.slug)
    if not entry or entry.get("state") != "prepared":
        raise Fail(EXIT_USAGE, f"--slug {a.slug} の準備済みの PR が無い (先に prepare)")
    what = f"PR「{entry['title']}」、 file {', '.join(entry.get('files', [])[:6])}"
    ensure_writable(repo, what)
    if not a.yes:
        raise Fail(EXIT_USAGE, "send は公開の発信 = 本人の OK の後に --yes をつけて呼ぶ")
    title = (a.title or entry["title"]).strip()
    body_path = Path(entry["body_file"])
    if a.body_file:
        body_path.write_text(Path(a.body_file).read_text(encoding="utf-8"), encoding="utf-8")
    body = body_path.read_text(encoding="utf-8") if body_path.exists() else ""
    if not body_ok(body):
        raise Fail(EXIT_USAGE, f"PR の本文がまだ雛形のまま: {body_path} を書く (または --body-file)")
    rc, _, _, kind = gh_run(["--version"])
    if kind == "no-gh":
        raise Fail(EXIT_NO_GH, gh_missing_line("no-gh"))
    perm = permission(repo, refresh=True)
    if perm.get("unknown") == "network":
        raise Fail(EXIT_APPROVAL, approval_text("GitHub に届かない (network が無い)", what))
    if perm.get("unknown") == "auth":
        raise Fail(EXIT_NO_GH, gh_missing_line("auth"))
    if perm.get("stale") or perm.get("role") is None:
        raise Fail(EXIT_UNAVAILABLE, f"push できるかを確かめられない ({perm.get('unknown')}) = 出さない")
    if perm["role"] == "owner":
        print(f"{repo.name}: push できる (所有者) = PR にしない。 何もしない")
        return EXIT_OK
    with repo.lock():
        st = repo.load_state()
        entry = st.get("prs", {}).get(a.slug) or entry
        if entry.get("state") != "prepared":
            raise Fail(EXIT_USAGE, f"--slug {a.slug} は別の呼び出しが先に出した ({entry.get('url')})")
        branch = entry["branch"]
        scan = scan_branch(repo, a.slug, entry["base_sha"], title, body, perm)
        entry["scan"] = scan.as_dict()
        st["prs"][a.slug] = entry
        repo.save_state(st)
        if scan.result != "pass":
            print(f"{repo.name}: 送らなかった")
            _print_scan(scan)
            return EXIT_BLOCKED if scan.result == "blocked" else EXIT_UNAVAILABLE
        if perm["role"] == "writer":
            remote, head = repo.base_remote, branch
        else:
            remote = ensure_fork_remote(repo, perm, what)
            head = f"{perm['login']}:{branch}"
        push_err = ""
        for attempt in range(4):
            r = git(repo.root, "push", "-q", remote, f"refs/heads/{branch}:refs/heads/{branch}", check=False, timeout=180)
            if r.returncode == 0:
                push_err = ""
                break
            push_err = (r.stderr or r.stdout).strip()
            if classify_gh_error(push_err) == "network" and attempt == 0:
                raise Fail(EXIT_APPROVAL, approval_text("push が GitHub に届かない (network が無い)", what))
            time.sleep(3 if attempt < 3 else 0)  # 作った直後の fork はすぐには受けないことがある
        if push_err:
            raise Fail(EXIT_UNAVAILABLE, f"push に失敗: {push_err[:300]}")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(body)
            bf = f.name
        try:
            rc, out, err, kind = gh_run(["pr", "create", "--repo", repo.slug, "--base", entry["base_branch"],
                                         "--head", head, "--title", title, "--body-file", bf], cwd=str(repo.root))
        finally:
            os.unlink(bf)
        if kind != "ok":
            raise Fail(EXIT_UNAVAILABLE, f"gh pr create に失敗 (branch は {remote} に push 済み): {(err or out).strip()[:300]}")
        url = (out.strip().splitlines() or [""])[-1].strip()
        m = re.search(r"/pull/(\d+)", url)
        entry.update({"state": "sent", "url": url, "number": int(m.group(1)) if m else None, "head_remote": remote,
                      "title": title, "sent_at": now_iso()})
        st["prs"][a.slug] = entry
        repo.save_state(st)
    print(f"{repo.name}: PR を出した: {url}")
    print(f"  → 手元の main を upstream に戻す: {tool_cmd('restore', '--repo', repo.root)}")
    print(f"  → PR を待つ間この変更を手元で使うなら: git -C {shlex.quote(str(repo.root))} switch {branch}"
          f" (戻す = git switch {repo.base_branch})")
    return EXIT_OK


def ensure_fork_remote(repo: Repo, perm, what) -> str:
    if repo.base_remote == "upstream" and repo.origin_slug and \
            repo.origin_slug.split("/")[0].lower() == (perm.get("login") or "").lower():
        return "origin"  # origin が本人の fork
    if "fork" in repo.remotes:
        return "fork"
    info, kind, err = gh_json(["api", "-X", "POST", f"repos/{repo.slug}/forks"])
    if info is None:
        if kind == "network":
            raise Fail(EXIT_APPROVAL, approval_text("fork を作れない (network が無い)", what))
        raise Fail(EXIT_UNAVAILABLE, f"fork を作れない: {err}")
    origin_url = git(repo.root, "remote", "get-url", repo.base_remote, check=False).stdout.strip()
    url = info.get("ssh_url") if origin_url.startswith(("git@", "ssh://")) else info.get("clone_url")
    url = url or info.get("clone_url") or info.get("ssh_url")
    git(repo.root, "remote", "add", "fork", url)
    repo.remotes.append("fork")
    return "fork"


def cmd_restore(a) -> int:
    repo = Repo(a.repo)
    ensure_writable(repo, "手元の main を upstream に戻す (変更は backup の ref に残る)")
    cur = repo.current_branch()
    if cur != repo.base_branch:
        raise Fail(EXIT_USAGE, f"今の branch は {cur or '(detached)'}。 git switch {repo.base_branch} の後に restore")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        if (repo.common / marker).exists() or (Path(git(repo.root, "rev-parse", "--git-dir").stdout.strip()) / marker).exists():
            raise Fail(EXIT_USAGE, f"途中の操作 ({marker}) がある = 先に終えるか abort する")
    with repo.lock():
        notes = []
        r = git(repo.root, "fetch", "-q", repo.base_remote, repo.base_branch, check=False, timeout=120)
        if r.returncode != 0:
            notes.append("upstream の最新を取れなかった (手元の記録の版に合わせる)")
        base_sha = repo.rev(repo.base_ref)
        if not base_sha:
            raise Fail(EXIT_USAGE, f"{repo.base_ref} が無い")
        paths = wip_paths(repo)
        commits, merges = ahead_commits(repo)
        head = repo.rev("HEAD")
        if not paths and not commits and not merges:
            if head != base_sha and git(repo.root, "merge-base", "--is-ancestor", head, base_sha, check=False).returncode == 0:
                git(repo.root, *hooks_off(repo.state_dir), "merge", "-q", "--ff-only", base_sha)
                print(f"{repo.name}: 手元の変更は無い。 main を upstream に進めた")
            else:
                print(f"{repo.name}: 戻すものが無い (main は upstream と同じ)")
            return EXIT_OK
        untracked = untracked_paths(repo)
        tree = snapshot_tree(repo)
        backup = git(repo.root, "commit-tree", tree, "-p", head, "-m",
                     f"upstream-pr backup before restore ({len(paths)} 作業中の file, {len(commits)} commit)").stdout.strip()
        ref = BACKUP_PREFIX + stamp()
        git(repo.root, "update-ref", ref, backup)
        if git(repo.root, "rev-parse", f"{ref}^{{tree}}").stdout.strip() != tree:
            raise Fail(EXIT_UNAVAILABLE, "backup の ref を確かめられない = 戻さない")
        git(repo.root, *hooks_off(repo.state_dir), "reset", "-q", "--hard", base_sha)
        for p in untracked:
            fp = repo.root / p
            try:
                if fp.is_file() or fp.is_symlink():
                    fp.unlink()
                d = fp.parent
                while d != repo.root and d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
                    d = d.parent
            except OSError:
                pass
        st = repo.load_state()
        st.setdefault("backups", []).append({"ref": ref, "at": now_iso(), "paths": paths, "commits": commits})
        repo.save_state(st)
        prs = [e for e in st.get("prs", {}).values() if e.get("state") in ("prepared", "sent")]
    print(f"{repo.name}: main を upstream ({repo.base_remote}/{repo.base_branch}) に戻した")
    for n in notes:
        print(f"  · {n}")
    print(f"  変更 (作業中の file {len(paths)} 個・commit {len(commits)} 本) は backup の ref {ref} に残した")
    for e in prs:
        print(f"  PR の branch {e['branch']}: {e.get('url') or '(まだ出していない)'}")
    print(f"  取り出すとき: git -C {shlex.quote(str(repo.root))} checkout {ref} -- <path>"
          f" / 手元の commit = git cherry-pick <sha>")
    return EXIT_OK


def cmd_after(a) -> int:
    rc_all = EXIT_OK
    for rp in repos_from_args(a.repo):
        try:
            repo = Repo(rp)
        except Fail:
            continue
        st = repo.load_state()
        sent = {k: e for k, e in st.get("prs", {}).items() if e.get("state") == "sent" and e.get("number")}
        if not sent:
            continue
        ensure_writable(repo, "出した PR の後片付け (手元の branch を消すだけ)")
        with repo.lock():
            st = repo.load_state()
            for slug in list(sent):
                e = st.get("prs", {}).get(slug)
                if not e or e.get("state") != "sent":
                    continue
                info, kind, err = gh_json(["api", f"repos/{e['base']}/pulls/{e['number']}"])
                if info is None:
                    if kind == "network":
                        raise Fail(EXIT_APPROVAL, approval_text("GitHub に届かない (network が無い)", "出した PR の後片付け"))
                    if kind in ("no-gh", "auth"):
                        print(f"{repo.name}: {gh_missing_line(kind)}")
                        rc_all = EXIT_NO_GH
                        break
                    continue
                if info.get("merged") or info.get("merged_at"):
                    git(repo.root, "branch", "-D", e["branch"], check=False)
                    st["prs"].pop(slug, None)
                    print(f"{repo.name}: PR が merge された: {e['url']} (手元の branch {e['branch']} を消した)")
                elif info.get("state") == "closed" and not e.get("closed_notified"):
                    e["closed_notified"] = now_iso()
                    print(f"{repo.name}: PR が merge されずに閉じた: {e['url']} (変更は branch {e['branch']} と backup の"
                          f" ref に残る。 要らなければ git branch -D {e['branch']})")
            repo.save_state(st)
    return rc_all


def cmd_drop(a) -> int:
    repo = Repo(a.repo)
    ensure_writable(repo, f"準備した PR {a.slug} を捨てる (branch の先は backup の ref に残る)")
    with repo.lock():
        st = repo.load_state()
        e = st.get("prs", {}).get(a.slug)
        if not e:
            raise Fail(EXIT_USAGE, f"--slug {a.slug} の PR の記録が無い")
        if e.get("state") == "sent":
            raise Fail(EXIT_USAGE, f"{e.get('url')} は出した PR = GitHub で閉じれば after が片付ける")
        tip = repo.rev(f"refs/heads/{e['branch']}")
        ref = ""
        if tip:
            ref = f"{BACKUP_PREFIX}dropped-{a.slug}-{stamp()}"
            git(repo.root, "update-ref", ref, tip)
            git(repo.root, "branch", "-D", e["branch"])
        st["prs"].pop(a.slug, None)
        repo.save_state(st)
    print(f"{repo.name}: 準備した PR {e['branch']} を捨てた" + (f" (中身は {ref} に残る)" if ref else ""))
    return EXIT_OK


def repos_from_args(given):
    if given:
        return given
    out = [TOOL_REPO]
    sib = TOOL_REPO.parent / "ai-collaboration"
    if (sib / ".git").exists():
        out.append(sib)
    return out


def status_one(repo: Repo):
    """表示する block の dict。 黙るなら None。"""
    if repo.disabled():
        return None
    paths = wip_paths(repo)
    commits, merges = ahead_commits(repo)
    st = repo.load_state()
    prs = st.get("prs", {})
    open_prs = [e for e in prs.values() if e.get("state") == "sent"]
    prepared = [e for e in prs.values() if e.get("state") == "prepared"]
    if not paths and not commits and not merges and not prepared and not open_prs:
        return None
    if not repo.slug:
        return {"repo": str(repo.root), "name": repo.name, "role": None, "unknown": "not-github",
                "paths": paths, "commits": commits}
    perm = permission(repo)
    if perm.get("role") == "owner":
        return None
    login = perm.get("login")
    return {"repo": str(repo.root), "name": repo.name, "role": perm.get("role"), "unknown": perm.get("unknown"),
            "login": login, "paths": paths, "commits": [[c, subject(repo, c)] for c in commits], "merges": merges,
            "fork_remote": ("fork" in repo.remotes) or (repo.base_remote == "upstream"),
            "prepared": [[k, ask_line(repo, e)] for k, e in prs.items() if e.get("state") == "prepared"],
            "open": [e.get("url") for e in open_prs],
            "branch": repo.current_branch(), "base": f"{repo.base_remote}/{repo.base_branch}"}


def cmd_status(a) -> int:
    blocks = []
    for rp in repos_from_args(a.repo):
        try:
            b = status_one(Repo(rp))
        except Fail as exc:
            if a.repo:
                print(f"⚠️ upstream-pr status: {exc.msg}")
            continue
        if b:
            blocks.append(b)
    if a.json:
        print(json.dumps(blocks, ensure_ascii=False, indent=1))
        return EXIT_OK
    for b in blocks:
        root = b["repo"]
        if b.get("unknown") == "not-github":
            print(f"📤 {b['name']}: upstream に入っていない手元の変更があるが、 remote が GitHub でないので PR にできない"
                  f" ({root})")
            continue
        route = {"writer": "push できるが所有者でない = origin の branch から PR", "none": "push できない = fork から PR"}
        print(f"📤 {b['name']} ({root}): upstream ({b['base']}) に入っていない手元の変更 — "
              f"{route.get(b['role'], 'push できるか未確認')}")
        if b["paths"]:
            more = f" ほか {len(b['paths']) - 6}" if len(b["paths"]) > 6 else ""
            print(f"  作業中の変更 {len(b['paths'])} file: {', '.join(b['paths'][:6])}{more}")
        if b["commits"]:
            print(f"  upstream より先の commit {len(b['commits'])} 本: "
                  + " / ".join(f"{c[:7]} {s[:40]}" for c, s in b["commits"][:4]))
        if b.get("merges"):
            print(f"  手元の merge commit {b['merges']} 本 (PR には中身の commit だけが入る)")
        if b["role"] is None:
            print(f"  {gh_missing_line(b.get('unknown') or 'no-gh')}" if b.get("unknown") in ("no-gh", "auth")
                  else f"  push できるかを確かめられなかった ({b.get('unknown')})")
        else:
            print(f"  gh = 使える (login {b.get('login')}) / "
                  + ("fork の remote = ある" if b["fork_remote"] else "fork の remote = 無い (send が作る)"))
        for slug, line in b["prepared"]:
            print(f"  準備済み (まだ出していない): {line} (出さないなら {tool_cmd('drop', '--repo', root, '--slug', slug)})")
        if b["open"]:
            print(f"  出して閉じていない PR {len(b['open'])} 本: {', '.join(u for u in b['open'] if u)}"
                  f" (閉じたら {tool_cmd('after', '--repo', root)})")
        if b["paths"] or b["commits"]:
            print("  → 本人に 1 回聞く (3 つのどれか): PR にする = "
                  f"{tool_cmd('prepare', '--repo', root, '--slug', '<短い名>', '--title', '<題>')}"
                  " / 個人層に移す (その機械だけの調整) = 中身を個人層に移してから restore"
                  f" / 捨てる = {tool_cmd('restore', '--repo', root)} (backup の ref に残る)")
    return EXIT_OK


# ----------------------------------------------------------------------------- selftest
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
st_path = os.environ["FAKE_GH_STATE"]
st = json.load(open(st_path))
args = sys.argv[1:]
with open(st_path + ".log", "a") as f:
    f.write(json.dumps(args) + "\n")
def out(obj):
    print(json.dumps(obj)); sys.exit(0)
if st.get("network_down") and args[:1] != ["--version"]:
    sys.stderr.write("error connecting to api.github.com\n"); sys.exit(1)
if args[:1] == ["--version"]:
    print("gh version 0.0 (fake)"); sys.exit(0)
if not st.get("authed", True):
    sys.stderr.write("To get started with GitHub CLI, please run:  gh auth login\n"); sys.exit(4)
if args[:2] == ["api", "user"]:
    out({"login": st["login"], "id": st["id"]})
if args[:1] == ["api"] and "-X" in args and args[-1].endswith("/forks"):
    out({"full_name": st["login"] + "/repo", "clone_url": st["fork_url"], "ssh_url": st["fork_url"]})
if args[:1] == ["api"] and "/pulls/" in args[-1]:
    n = args[-1].rsplit("/", 1)[1]
    out(st["pulls"].get(n, {"state": "open", "merged": False}))
if args[:1] == ["api"] and args[1].startswith("repos/"):
    slug = args[1][len("repos/"):]
    if slug == st["base"]:
        out({"owner": {"login": st["owner"]}, "permissions": st["perm"], "fork": False, "private": False})
    if slug in st.get("visibility", {}):
        out({"private": st["visibility"][slug] == "private"})
    sys.stderr.write("HTTP 404: Not Found\n"); sys.exit(1)
if args[:2] == ["pr", "create"]:
    st.setdefault("created", []).append(args)
    json.dump(st, open(st_path, "w"))
    print("https://github.com/" + st["base"] + "/pull/7"); sys.exit(0)
sys.stderr.write("fake gh: unhandled " + " ".join(args) + "\n"); sys.exit(1)
'''


def selftest() -> int:
    if not shutil.which("git") or not shutil.which("bash"):
        print("SKIP: upstream-pr selftest (git か bash が無い)")
        return 0
    missing = [f for f in ENGINE_FILES if not (TOOL_SCRIPTS / f).is_file()]
    if missing:
        print(f"SKIP: upstream-pr selftest (検査の engine が無い: {missing})")
        return 0
    fails = []

    def expect(name, cond, detail=""):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)
            if detail:
                print("     " + str(detail).replace("\n", "\n     ")[:3000])

    tmp = Path(tempfile.mkdtemp(prefix="upstream-pr-selftest-"))
    try:
        home = tmp / "home"
        home.mkdir()
        bindir = tmp / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(FAKE_GH)
        (bindir / "gh").chmod(0o755)
        state_file = tmp / "gh-state.json"
        login, uid = "contrib", 4242
        noreply = f"{uid}+{login}@users.noreply.github.com"
        base_env = clean_env(drop=AGENT_ENV + ("CLAUDE_CARRYOVER_TRANSCRIPT",))
        base_env.update({"HOME": str(home), "XDG_CACHE_HOME": str(tmp / "cache"), "CLAUDE_PERSONAL_LAYER": "none",
                         "UPSTREAM_PR_ENGINE_DIR": os.environ.get("UPSTREAM_PR_ENGINE_DIR") or str(TOOL_SCRIPTS),
                         "FAKE_GH_STATE": str(state_file),
                         "UPSTREAM_PR_GH": str(bindir / "gh"),
                         "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z",
                         "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z"})
        base_env.pop("GIT_LITERAL_PATHSPECS", None)

        def sh(*cmd, cwd=None, env=None, check=True):
            r = subprocess.run(list(map(str, cmd)), cwd=cwd, env=env or base_env, capture_output=True, text=True)
            if check and r.returncode != 0:
                raise RuntimeError(f"{cmd}: {r.stderr}")
            return r

        def gh_state(**kw):
            st = {"login": login, "id": uid, "owner": "upstream-owner", "base": "upstream-owner/claude-config",
                  "perm": {"push": False, "admin": False}, "pulls": {}, "fork_url": str(tmp / "fork.git"),
                  "visibility": {}}
            st.update(kw)
            state_file.write_text(json.dumps(st))
            if os.path.exists(str(state_file) + ".log"):
                os.unlink(str(state_file) + ".log")

        def gh_log():
            p = Path(str(state_file) + ".log")
            return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

        def tool(*args, env=None):
            return sh(sys.executable, SELF, *args, env=env, check=False)

        # upstream (bare) + fork (bare) + 作業の親 dir (clone と隣の private な repo)
        seed = tmp / "seed"
        sh("git", "init", "-q", "-b", "main", seed)
        for k, v in (("user.name", "Seed"), ("user.email", "1+seed" + "@users.noreply.github.com")):
            sh("git", "-C", seed, "config", k, v)
        (seed / ".claude").mkdir()
        (seed / ".claude" / "public-repo.marker").write_text("")
        (seed / "README.md").write_text("# demo\n\nA small public repository used by the selftest.\n")
        sh("git", "-C", seed, "add", "-A")
        sh("git", "-C", seed, "commit", "-q", "-m", "init")
        sh("git", "clone", "-q", "--bare", seed, tmp / "up.git")
        sh("git", "init", "-q", "--bare", tmp / "fork.git")
        parent = tmp / "work"
        parent.mkdir()
        clone = parent / "claude-config"

        def fresh_clone():
            if clone.exists():
                shutil.rmtree(clone)
            sh("git", "clone", "-q", tmp / "up.git", clone)
            for k, v in (("user.name", "Contrib"), ("user.email", noreply),
                         ("upstream-pr.base", "upstream-owner/claude-config")):
                sh("git", "-C", clone, "config", k, v)

        priv = parent / "private-notes"
        sh("git", "init", "-q", "-b", "main", priv)
        secret = ("The calibration of the detector arrays drifted overnight because the cooling loop "
                  "pressure regulator failed twice before dawn.")
        (priv / "notes.md").write_text(f"# notes\n\n{secret}\n")

        def run_status():
            return tool("status", "--repo", clone)

        # 1. 所有者: 変更があっても黙る、 prepare は何もしない
        fresh_clone()
        gh_state(login="upstream-owner", perm={"push": True, "admin": True})
        (clone / "README.md").write_text("# demo\n\nowner edit\n")
        r = run_status()
        expect("owner: status prints nothing", r.returncode == 0 and r.stdout.strip() == "", r.stdout + r.stderr)
        r = tool("prepare", "--repo", clone, "--slug", "x", "--title", "t")
        branches = sh("git", "-C", clone, "branch", "--list", "upstream-pr/*").stdout.strip()
        expect("owner: prepare does nothing", r.returncode == 0 and "何もしない" in r.stdout and not branches,
               r.stdout + r.stderr)
        expect("owner: no push / pr create", not any(c[:2] == ["pr", "create"] for c in gh_log()))
        r = tool("status", "--repo", clone, env=dict(base_env, UPSTREAM_PR_GH=""))
        expect("owner: silent from cached role even without gh", r.stdout.strip() == "", r.stdout)

        # 2. 変更の無い clone は黙る
        fresh_clone()
        gh_state()
        r = run_status()
        expect("no changes: status prints nothing", r.returncode == 0 and r.stdout.strip() == "", r.stdout + r.stderr)

        # 3. 作業中の変更 + 手元の commit → status が 1 block、 prepare が branch を作る
        (clone / "tool-notes.md").write_text("# tool notes\n\nA general note about running the checks.\n")
        sh("git", "-C", clone, "add", "tool-notes.md")
        sh("git", "-C", clone, "commit", "-q", "-m", "Add a general note")
        (clone / "README.md").write_text("# demo\n\nA small public repository used by the selftest, now clearer.\n")
        (clone / "extra.md").write_text("Another general paragraph.\n")
        r = run_status()
        expect("contributor: status shows the block",
               "作業中の変更 2 file" in r.stdout and "先の commit 1 本" in r.stdout and "fork から PR" in r.stdout,
               r.stdout + r.stderr)
        before = sh("git", "-C", clone, "status", "--porcelain").stdout
        r = tool("prepare", "--repo", clone, "--slug", "clarify-readme", "--title", "Clarify the README")
        expect("prepare: passes the leak checks", r.returncode == 0 and "漏洩の検査 = 通った" in r.stdout, r.stdout + r.stderr)
        log = sh("git", "-C", clone, "log", "--format=%s", "origin/main..upstream-pr/clarify-readme").stdout.split("\n")
        expect("prepare: branch = upstream main + 2 commits",
               [x for x in log if x] == ["Clarify the README", "Add a general note"], log)
        expect("prepare: working tree untouched", sh("git", "-C", clone, "status", "--porcelain").stdout == before)
        r = tool("send", "--repo", clone, "--slug", "clarify-readme", "--yes")
        expect("send: refuses the template body", r.returncode == EXIT_USAGE and "雛形" in r.stderr, r.stdout + r.stderr)
        body = tmp / "body.md"
        body.write_text("## 概要\n\nThe README says what the repository is for.\n\n## 検証\n\nRead it.\n")
        r = tool("send", "--repo", clone, "--slug", "clarify-readme", "--body-file", body)
        expect("send: needs --yes", r.returncode == EXIT_USAGE and "--yes" in r.stderr, r.stdout + r.stderr)
        r = tool("send", "--repo", clone, "--slug", "clarify-readme", "--yes", "--body-file", body)
        created = json.loads(state_file.read_text()).get("created", [])
        expect("send: opens the PR from the fork", r.returncode == 0 and "pull/7" in r.stdout and created
               and created[0][created[0].index("--head") + 1] == f"{login}:upstream-pr/clarify-readme",
               r.stdout + r.stderr + str(created))
        pushed = sh("git", "--git-dir", tmp / "fork.git", "branch", "--list").stdout
        expect("send: branch pushed to the fork", "upstream-pr/clarify-readme" in pushed, pushed)
        r = tool("restore", "--repo", clone)
        head = sh("git", "-C", clone, "rev-parse", "HEAD").stdout.strip()
        upmain = sh("git", "-C", clone, "rev-parse", "origin/main").stdout.strip()
        refs = sh("git", "-C", clone, "for-each-ref", "--format=%(refname)", BACKUP_PREFIX).stdout.split()
        kept = sh("git", "-C", clone, "show", f"{refs[0]}:extra.md", check=False).stdout if refs else ""
        expect("restore: main = upstream, clean tree, backup kept",
               r.returncode == 0 and head == upmain and not sh("git", "-C", clone, "status", "--porcelain").stdout
               and "Another general paragraph" in kept and not (clone / "extra.md").exists(), r.stdout + r.stderr)
        expect("restore: PR branch kept", bool(sh("git", "-C", clone, "rev-parse", "-q", "--verify",
                                                   "upstream-pr/clarify-readme", check=False).stdout.strip()))
        r = run_status()
        expect("after restore: status lists the open PR only",
               "出して閉じていない PR 1 本" in r.stdout and "作業中の変更" not in r.stdout, r.stdout)
        st = json.loads(state_file.read_text())
        st["pulls"] = {"7": {"state": "closed", "merged": False}}
        state_file.write_text(json.dumps(st))
        r1, r2 = tool("after", "--repo", clone), tool("after", "--repo", clone)
        expect("after: closed without merge is told once",
               "merge されずに閉じた" in r1.stdout and "merge されずに閉じた" not in r2.stdout, r1.stdout + r2.stdout)
        st["pulls"] = {"7": {"state": "closed", "merged": True}}
        state_file.write_text(json.dumps(st))
        r = tool("after", "--repo", clone)
        gone = not sh("git", "-C", clone, "rev-parse", "-q", "--verify", "upstream-pr/clarify-readme",
                      check=False).stdout.strip()
        expect("after: merged PR's branch removed", "merge された" in r.stdout and gone, r.stdout + r.stderr)

        # 4. 漏洩の検査が止める形
        fresh_clone()
        gh_state()
        addr = "someone" + "@" + "example-lab.ac.jp"
        (clone / "contact.md").write_text(f"Write to {addr} for details.\n")
        r = tool("prepare", "--repo", clone, "--slug", "leak-email", "--title", "Add contact")
        expect("leak: an e-mail address in an added line is stopped",
               r.returncode == EXIT_BLOCKED and "tier-a/email" in r.stdout, r.stdout + r.stderr)
        r = tool("send", "--repo", clone, "--slug", "leak-email", "--yes", "--body-file", body)
        expect("leak: send refuses and pushes nothing",
               r.returncode == EXIT_BLOCKED and not json.loads(state_file.read_text()).get("created"),
               r.stdout + r.stderr)
        fresh_clone()
        (clone / f"contact-{addr}.md").write_text("A general paragraph about the checks.\n")
        r = tool("prepare", "--repo", clone, "--slug", "leak-name", "--title", "Add a paragraph")
        expect("leak: an e-mail address in a new file's name is stopped",
               r.returncode == EXIT_BLOCKED and "tier-a/email" in r.stdout, r.stdout + r.stderr)
        fresh_clone()
        (clone / "ok.md").write_text("A general paragraph about the checks.\n")
        tool("prepare", "--repo", clone, "--slug", "body-leak", "--title", "Add a paragraph")
        home_path = "/" + "Users" + "/someone/work/data"
        body2 = tmp / "body2.md"
        body2.write_text(f"## 概要\n\nI ran it from {home_path} on my machine.\n")
        r = tool("send", "--repo", clone, "--slug", "body-leak", "--yes", "--body-file", body2)
        expect("leak: a home path in the PR body is stopped",
               r.returncode == EXIT_BLOCKED and "tier-a/abs_path" in r.stdout, r.stdout + r.stderr)
        fresh_clone()
        (clone / "copied.md").write_text(f"# log\n\n{secret}\n")
        r = tool("prepare", "--repo", clone, "--slug", "copied", "--title", "Add a log")
        expect("leak: text of a private sibling repo is stopped",
               r.returncode == EXIT_BLOCKED and "隣の private な repo の文" in r.stdout, r.stdout + r.stderr)
        sh("git", "-C", priv, "remote", "add", "origin", "https://github.com/contrib/private-notes.git")
        gh_state(visibility={"contrib/private-notes": "public"})
        r = tool("prepare", "--repo", clone, "--slug", "copied", "--title", "Add a log")
        expect("leak: a sibling that is public on GitHub is not a source", r.returncode == 0, r.stdout + r.stderr)
        sh("git", "-C", priv, "remote", "remove", "origin")
        r = run_status()
        expect("status: a prepared PR offers drop", "準備済み" in r.stdout and " drop " in r.stdout, r.stdout)
        r = tool("drop", "--repo", clone, "--slug", "copied")
        dropped = sh("git", "-C", clone, "for-each-ref", "--format=%(refname)", BACKUP_PREFIX + "dropped-*").stdout
        gone = not sh("git", "-C", clone, "rev-parse", "-q", "--verify", "upstream-pr/copied", check=False).stdout.strip()
        expect("drop: branch removed, tip kept in a backup ref", r.returncode == 0 and gone and dropped.strip(),
               r.stdout + r.stderr)
        loose = parent / "scratch"  # git repo でない dir = 源に入れない
        loose.mkdir()
        loose_text = ("Seventeen lantern festivals brightened the harbour district while porters carried "
                      "copper kettles uphill.")
        (loose / "draft.md").write_text(loose_text + "\n")
        fresh_clone()
        (clone / "loose.md").write_text(loose_text + "\n")
        r = tool("prepare", "--repo", clone, "--slug", "loose", "--title", "Add a paragraph")
        expect("sources: a sibling dir that is not a git repo is not a source", r.returncode == 0, r.stdout + r.stderr)
        shutil.rmtree(loose)
        fresh_clone()
        gh_state()
        sh("git", "-C", clone, "config", "user.email", "contrib" + "@" + "example-lab.ac.jp")
        (clone / "ok.md").write_text("A general paragraph about the checks.\n")
        r = tool("prepare", "--repo", clone, "--slug", "real-email", "--title", "Add a paragraph")
        expect("leak: a non-noreply author e-mail is stopped",
               r.returncode == EXIT_BLOCKED and "noreply" in r.stdout and noreply in r.stdout, r.stdout + r.stderr)
        r = tool("prepare", "--repo", clone, "--slug", "real-email", "--title", "Add a paragraph",
                 env=dict(base_env, UPSTREAM_PR_ENGINE_DIR=str(tmp / "no-engine")))
        expect("unavailable: missing engine = not sent", r.returncode == EXIT_UNAVAILABLE and "読めない" in r.stdout,
               r.stdout + r.stderr)

        # 5. gh が無い: status は 1 行を出し、 prepare と restore は手元で動き、 send は止まる
        fresh_clone()
        gh_state()
        (clone / "ok.md").write_text("A general paragraph about the checks.\n")
        nogh = dict(base_env, UPSTREAM_PR_GH="")
        r = tool("status", "--repo", clone, env=nogh)
        expect("no gh: status tells how to install it", "gh が無い" in r.stdout and "gh auth login" in r.stdout,
               r.stdout + r.stderr)
        r = tool("prepare", "--repo", clone, "--slug", "nogh", "--title", "Add a paragraph", env=nogh)
        expect("no gh: prepare still works locally", r.returncode == 0, r.stdout + r.stderr)
        r = tool("send", "--repo", clone, "--slug", "nogh", "--yes", "--body-file", body, env=nogh)
        expect("no gh: send stops with the install line",
               r.returncode == EXIT_NO_GH and "gh auth login" in r.stderr, r.stdout + r.stderr)
        r = tool("restore", "--repo", clone, env=nogh)
        expect("no gh: restore still works", r.returncode == 0 and not (clone / "ok.md").exists(), r.stdout + r.stderr)

        # 6. 書き込み権限のある第三者: origin の branch から PR、 main には push しない
        fresh_clone()
        gh_state(perm={"push": True, "admin": False})
        (clone / "ok.md").write_text("A general paragraph about the checks.\n")
        tool("prepare", "--repo", clone, "--slug", "writer", "--title", "Add a paragraph")
        up_main = sh("git", "--git-dir", tmp / "up.git", "rev-parse", "main").stdout
        r = tool("send", "--repo", clone, "--slug", "writer", "--yes", "--body-file", body)
        up_branches = sh("git", "--git-dir", tmp / "up.git", "branch", "--list").stdout
        expect("writer: pushes a branch to origin, not main",
               r.returncode == 0 and "upstream-pr/writer" in up_branches
               and sh("git", "--git-dir", tmp / "up.git", "rev-parse", "main").stdout == up_main, r.stdout + r.stderr)

        # 7. sandbox: .git に書けない → 承認の要る command として出す
        fresh_clone()
        gh_state()
        (clone / "ok.md").write_text("A general paragraph about the checks.\n")
        gitdir = clone / ".git"
        (gitdir / STATE_DIRNAME).mkdir(exist_ok=True)
        os.chmod(gitdir / STATE_DIRNAME, 0o555)
        os.chmod(gitdir, 0o555)
        try:
            r = tool("prepare", "--repo", clone, "--slug", "sandbox", "--title", "Add a paragraph")
        finally:
            os.chmod(gitdir, 0o755)
            os.chmod(gitdir / STATE_DIRNAME, 0o755)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            print("skip sandbox case (root ignores the permission bits)")
        else:
            expect("sandbox: prints the command to run with approval",
                   r.returncode == EXIT_APPROVAL and "承認の要る command" in r.stderr and "prepare" in r.stderr,
                   r.stdout + r.stderr)
        gh_state(network_down=True)
        tool("prepare", "--repo", clone, "--slug", "net", "--title", "Add a paragraph")
        r = tool("send", "--repo", clone, "--slug", "net", "--yes", "--body-file", body)
        expect("no network: send prints the command to run with approval",
               r.returncode == EXIT_APPROVAL and "network" in r.stderr, r.stdout + r.stderr)
    finally:
        for dp, dns, _ in os.walk(tmp):
            for d in dns:
                try:
                    os.chmod(os.path.join(dp, d), 0o755)
                except OSError:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"upstream-pr selftest: {'FAIL ' + str(len(fails)) if fails else 'all ok'}")
    return 1 if fails else 0


# ----------------------------------------------------------------------------- main
def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status")
    p.add_argument("--repo", action="append")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("prepare")
    p.add_argument("--repo", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--body-file")
    p.add_argument("--paths", nargs="+")
    p.add_argument("--commits", nargs="+")
    p.add_argument("--reset-author", action="store_true")
    p = sub.add_parser("send")
    p.add_argument("--repo", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--title")
    p.add_argument("--body-file")
    p = sub.add_parser("restore")
    p.add_argument("--repo", required=True)
    p = sub.add_parser("after")
    p.add_argument("--repo", action="append")
    p = sub.add_parser("drop")
    p.add_argument("--repo", required=True)
    p.add_argument("--slug", required=True)
    a = ap.parse_args()
    try:
        return {"status": cmd_status, "prepare": cmd_prepare, "send": cmd_send, "restore": cmd_restore,
                "after": cmd_after, "drop": cmd_drop}[a.cmd](a)
    except Fail as exc:
        print(exc.msg, file=sys.stderr)
        return exc.code
    except subprocess.TimeoutExpired as exc:
        print(f"時間切れ: {exc.cmd}", file=sys.stderr)
        return EXIT_UNAVAILABLE


if __name__ == "__main__":
    sys.exit(main())
