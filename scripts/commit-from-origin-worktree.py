#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自分の変更を origin/<branch> から切った使い捨て worktree で commit・push する (live checkout の未 commit 変更・未 push commit・index に一切触れず、 相手の未 push commit を巻き込んで公開しない)。 git-crypt repo も復号済みで扱い、 push 直前の再 fetch + rebase、 衝突時は push せず worktree を残す。--selftest 内蔵。

手順の正本 = [`conventions/multi-session-coordination.md#foreign-wip-scratch-worktree`](../conventions/multi-session-coordination.md#foreign-wip-scratch-worktree)。
本 script はその機械化。 手で踏むと毎回 7 コマンド + git-crypt の 3 行 + 後始末で、 省略が起きる
(2026-09-12〜13: live checkout から push した回の多くは behind が 0 であることしか確かめず、 ahead の中身が
自分の commit だけかは見ていなかった。 相手の未 push commit が local に居れば一緒に公開する構造だった。
事後監査 = [`audit-push-provenance.py`](audit-push-provenance.py) で、 その 40 回の push 範囲に他 session の commit は
0 件 = 実害なしの near-miss。 防いでいたのは偶然で、 本 script では構造的に起きない)。

使い方:

    python3 commit-from-origin-worktree.py --repo ~/Claude/claude-config -m msg.txt \\
        --copy /path/to/edited.md:conventions/edited.md \\
        --check 'python3 scripts/run-all-checks.sh'
    python3 commit-from-origin-worktree.py --repo R -m msg.txt --apply 'python3 "$LIVE/../x.py" conventions/a.md'
    python3 commit-from-origin-worktree.py --selftest

- `--copy SRC:DST` (複数可) = SRC の中身を worktree の DST (repo 相対) に置く。 SRC は scratchpad でも live の
  tree でもよいが、 **file 全体が自分の変更であるときだけ**使う (相手の hunk が混ざった live の file を写すと、
  相手の未 commit 変更を公開する。 その場合は正本の hash-object 手順)。
  既定では、 DST の live HEAD 版と origin 版が違う (= upstream が変えた / live の未 push commit が触った) と拒否する
  (丸ごと置換は前者を黙って巻き戻し、 後者を公開する)。 `--apply` で origin 版に編集をやり直すか、 意図した置換なら
  `--allow-overwrite`。
- `--apply CMD` = worktree を cwd に bash で走らせる変更 command。 環境変数 `LIVE` (live の top) と `WT` を渡す。
- `--check CMD` = stage 後・commit 前に worktree で走らせる検査。 非 0 なら commit しない。
- `--remove-live-copies` = push 後、 live の tree に在る**未追跡**の SRC を、 `origin/<branch>:<DST>` と一致を
  確かめてから消す (残すと相手の pull が untracked overwrite で止まる)。 live で**追跡中の file を直接編集**して
  出した場合は消さずに、 origin と一致していれば追いつき方を出す: 同じ中身の変更が unstaged のままだと
  `merge --ff-only` は「would be overwritten」 で止まり、 `git add -- <path>` で index を揃えると fast-forward が通って
  clean になる (2026-09-13 実測)。

exit: 0 = push 済 / 1 = commit 前に止めた (変更なし・検査失敗・hook 拒否) / 2 = rebase 衝突 (push せず、
worktree を残して path を出す) / 3 = push が retry 後も失敗。
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def git(repo: Path, *args: str, check: bool = True, binary: bool = False, env=None):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=not binary, env=env)
    if check and r.returncode != 0:
        err = r.stderr if not binary else r.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"git {' '.join(args)} failed: {err.strip()}")
    return r


def fetch(repo: Path) -> None:
    """fetch, retrying once on the ref-lock race of two concurrent fetches (#concurrent-fetch-ref-lock)."""
    r = git(repo, "fetch", "-q", "origin", check=False)
    if r.returncode != 0 and "cannot lock ref" in r.stderr:
        time.sleep(1)
        r = git(repo, "fetch", "-q", "origin", check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git fetch failed: {r.stderr.strip()}")


def default_branch(live: Path) -> str:
    r = git(live, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if r.returncode == 0 and r.stdout.strip().startswith("origin/"):
        return r.stdout.strip()[len("origin/"):]
    return git(live, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def names_z(repo: Path, *args: str) -> list[str]:
    out = git(repo, *args, binary=True).stdout
    return [n for n in out.decode("utf-8", "surrogateescape").split("\0") if n]


def add_worktree(live: Path, wt: Path, branch: str, log) -> None:
    crypt = git(live, "config", "--get", "filter.git-crypt.smudge", check=False).returncode == 0
    if not crypt:
        git(live, "worktree", "add", "-q", "--detach", str(wt), f"origin/{branch}")
        return
    # git-crypt: the key lives in the COMMON git dir; a worktree's own git dir cannot see it and the
    # smudge filter fails on checkout. Create without checkout, link the key dir, then check out.
    git(live, "worktree", "add", "-q", "--no-checkout", "--detach", str(wt), f"origin/{branch}")
    common = Path(git(live, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    wt_gitdir = Path(git(wt, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip())
    if (common / "git-crypt").exists() and not (wt_gitdir / "git-crypt").exists():
        os.symlink(common / "git-crypt", wt_gitdir / "git-crypt")
    git(wt, "checkout", "-q")
    log("[worktree] git-crypt repo: key dir linked, checked out decrypted")


def remove_worktree(live: Path, tmp: Path, wt: Path) -> None:
    git(live, "worktree", "remove", "--force", str(wt), check=False)
    git(live, "worktree", "prune", check=False)
    shutil.rmtree(tmp, ignore_errors=True)


def commit_from_origin_worktree(live: Path, message: str, copies=(), apply_cmd: str | None = None,
                                check_cmd: str | None = None, branch: str | None = None,
                                remove_live_copies: bool = False, retries: int = 3,
                                before_push=None, log=print, allow_overwrite: bool = False) -> int:
    live = Path(git(live, "rev-parse", "--show-toplevel").stdout.strip())
    branch = branch or default_branch(live)
    snap_head = git(live, "rev-parse", "HEAD").stdout
    snap_status = git(live, "status", "--porcelain=v1", "-z", binary=True).stdout
    fetch(live)
    # A copy replaces the whole file. It is only safe when the version the edit started from (live HEAD)
    # is the version origin has now: otherwise it silently reverts a change someone pushed, or publishes
    # a foreign UNPUSHED commit's hunk that sits in the live base.
    blob = lambda ref, p: (lambda r: r.stdout.strip() if r.returncode == 0 else None)(
        git(live, "rev-parse", "-q", "--verify", f"{ref}:{p}", check=False))
    stale = [d for _s, d in copies if blob("HEAD", d) != blob(f"origin/{branch}", d)]
    if stale and not allow_overwrite:
        for d in stale:
            log(f"[stop] {d}: live HEAD and origin/{branch} hold different versions; a whole-file copy would "
                f"revert an upstream change or publish an unpushed one. Redo the edit on the origin version "
                f"(--apply), or pass --allow-overwrite if replacing it is intended")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="origin-worktree-"))
    wt = tmp / live.name
    keep = False
    try:
        add_worktree(live, wt, branch, log)
        for src, dst in copies:
            d = wt / dst
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, d)
        if apply_cmd:
            env = dict(os.environ, LIVE=str(live), WT=str(wt))
            r = subprocess.run(["bash", "-c", apply_cmd], cwd=wt, env=env, capture_output=True, text=True)
            if r.returncode != 0:
                log(r.stdout + r.stderr)
                log("[stop] --apply failed; nothing committed")
                return 1
        git(wt, "add", "-A")
        staged = names_z(wt, "diff", "--cached", "-z", "--name-only")
        if not staged:
            log("[stop] the change set is empty (vacuous); nothing committed")
            return 1
        log("[staged] " + "  ".join(staged))
        if check_cmd:
            r = subprocess.run(["bash", "-c", check_cmd], cwd=wt, capture_output=True, text=True,
                               env=dict(os.environ, LIVE=str(live), WT=str(wt)))
            if r.returncode != 0:
                log((r.stdout + r.stderr)[-3000:])
                log("[stop] --check failed in the worktree; nothing committed")
                return 1
        r = subprocess.run(["git", "-C", str(wt), "commit", "-q", "-F", "-"], input=message,
                           capture_output=True, text=True)
        if r.returncode != 0:
            log(r.stdout + r.stderr)
            log("[stop] git commit failed (a hook refused?); nothing committed")
            return 1
        for attempt in range(1, retries + 1):
            if before_push:
                before_push(attempt)
            fetch(wt)
            if git(wt, "merge-base", "--is-ancestor", f"origin/{branch}", "HEAD", check=False).returncode != 0:
                rb = git(wt, "rebase", "-q", f"origin/{branch}", check=False)
                if rb.returncode != 0:
                    git(wt, "rebase", "--abort", check=False)
                    keep = True
                    log(rb.stdout + rb.stderr)
                    log(f"[conflict] origin/{branch} moved and the rebase conflicts; NOT pushed. worktree kept at {wt}\n"
                        f"  generated files: take upstream, regenerate there, commit, then push HEAD:{branch}")
                    return 2
            p = git(wt, "push", "-q", "origin", f"HEAD:refs/heads/{branch}", check=False)
            if p.returncode == 0:
                break
            log(f"[retry {attempt}] push rejected: {p.stderr.strip()[:200]}")
        else:
            keep = True
            log(f"[stop] push failed {retries} times; worktree kept at {wt}")
            return 3
        head = git(wt, "rev-parse", "HEAD").stdout.strip()
        fetch(wt)
        published = git(wt, "merge-base", "--is-ancestor", head, f"origin/{branch}", check=False).returncode == 0
        files = names_z(wt, "show", "-z", "--name-only", "--format=", head)
        log(f"[pushed] {head[:10]} -> origin/{branch} ({len(files)} file(s))" + ("" if published else "  ⚠ not visible on origin yet"))
        if remove_live_copies:
            for src, dst in copies:
                s = Path(src).absolute()
                if live not in s.parents:
                    continue
                rel = os.path.relpath(s, live)
                blob = git(live, "show", f"origin/{branch}:{dst}", check=False, binary=True)
                if git(live, "ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0:
                    # tracked in live: never delete or revert. If it now equals origin, say how to catch
                    # live up: with the identical change UNSTAGED `merge --ff-only` aborts ("would be
                    # overwritten"); once the index holds the same blob the fast-forward goes through clean.
                    if rel == dst and blob.returncode == 0 and s.exists() and s.read_bytes() == blob.stdout:
                        log(f"[live] {rel} is tracked and now equals origin/{branch}; to catch live up: "
                            f"git -C {live} add -- {shlex.quote(rel)} && git -C {live} merge --ff-only origin/{branch}")
                    continue
                if blob.returncode == 0 and s.exists() and s.read_bytes() == blob.stdout:
                    s.unlink()
                    log(f"[live] removed untracked copy {rel} (identical to origin/{branch}:{dst})")
                else:
                    log(f"[live] kept {rel}: differs from origin/{branch}:{dst}")
        if git(live, "rev-parse", "HEAD").stdout != snap_head:
            log("⚠ live HEAD moved during the run (another session?); this script did not touch it")
        elif git(live, "status", "--porcelain=v1", "-z", binary=True).stdout != snap_status and not remove_live_copies:
            log("⚠ live status changed during the run (another session?); this script did not touch it")
        return 0
    finally:
        if not keep:
            remove_worktree(live, tmp, wt)


# ---------------------------------------------------------------- selftest


def selftest() -> int:
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    quiet = lambda *_a, **_k: None
    with tempfile.TemporaryDirectory() as td:
        T = Path(td).resolve()
        sh = lambda repo, *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)
        src = T / "src"
        subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
        for rp in (src,):
            sh(rp, "config", "user.email", "t@t"); sh(rp, "config", "user.name", "t")
        (src / "a.md").write_text("base\n", encoding="utf-8")
        (src / "§ 記録.md").write_text("記録\n", encoding="utf-8")
        sh(src, "add", "-A"); sh(src, "commit", "-q", "-m", "base")
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(T / "remote.git")], check=True)
        live, other = T / "live", T / "other"
        for c in (live, other):
            subprocess.run(["git", "clone", "-q", str(T / "remote.git"), str(c)], check=True)
            sh(c, "config", "user.email", "t@t"); sh(c, "config", "user.name", "t")
        remote = T / "remote.git"
        # foreign state in live: a dirty tracked file, a staged file, and an UNPUSHED commit
        (live / "foreign.md").write_text("foreign unpushed\n", encoding="utf-8")
        sh(live, "add", "foreign.md"); sh(live, "commit", "-q", "-m", "foreign unpushed commit")
        (live / "a.md").write_text("foreign dirty edit\n", encoding="utf-8")
        (live / "staged-foreign.md").write_text("x\n", encoding="utf-8")
        sh(live, "add", "staged-foreign.md")
        head0 = sh(live, "rev-parse", "HEAD").stdout
        status0 = sh(live, "status", "--porcelain=v1").stdout
        edited = T / "scratch-new §.md"
        edited.write_text("my change\n", encoding="utf-8")

        def other_pushes(attempt):
            if attempt == 1:
                (other / "b.md").write_text("other session\n", encoding="utf-8")
                sh(other, "add", "b.md"); sh(other, "commit", "-q", "-m", "other"); sh(other, "push", "-q")

        rc = commit_from_origin_worktree(live, "add note\n", copies=[(edited, "docs/new §.md")],
                                         check_cmd='test -f "docs/new §.md"', before_push=other_pushes, log=quiet)
        tree = sh(remote, "ls-tree", "-r", "--name-only", "-z", "main").stdout.split("\0")
        check("the change is pushed, non-ASCII path included", rc == 0 and "docs/new §.md" in tree)
        check("origin moved before the push and the commit was rebased onto it", "b.md" in tree)
        check("the foreign UNPUSHED commit was not published  [foil: a push from live would publish it]",
              "foreign.md" not in tree and "foreign unpushed commit" in sh(live, "log", "--format=%s", "origin/main..main").stdout)
        check("live HEAD, dirty file and index are untouched",
              sh(live, "rev-parse", "HEAD").stdout == head0 and sh(live, "status", "--porcelain=v1").stdout == status0
              and (live / "a.md").read_text() == "foreign dirty edit\n")
        check("the worktree is removed", len(sh(live, "worktree", "list").stdout.strip().splitlines()) == 1)

        before = sh(remote, "rev-parse", "main").stdout
        rc = commit_from_origin_worktree(live, "x\n", copies=[(edited, "docs/other.md")], check_cmd="false", log=quiet)
        check("a failing --check commits and pushes nothing", rc == 1 and sh(remote, "rev-parse", "main").stdout == before)
        rc = commit_from_origin_worktree(live, "x\n", apply_cmd="true", log=quiet)
        check("an empty change set is refused (vacuous)", rc == 1 and sh(remote, "rev-parse", "main").stdout == before)

        conflict_src = T / "a-mine.md"
        conflict_src.write_text("mine\n", encoding="utf-8")

        def other_conflicts(attempt):
            if attempt == 1:
                sh(other, "pull", "-q")
                (other / "a.md").write_text("theirs\n", encoding="utf-8")
                sh(other, "commit", "-qam", "theirs"); sh(other, "push", "-q")

        msgs = []
        rc = commit_from_origin_worktree(live, "mine\n", copies=[(conflict_src, "a.md")], before_push=other_conflicts,
                                         log=lambda m: msgs.append(m))
        kept = next((m.split("worktree kept at ")[1].split("\n")[0] for m in msgs if "worktree kept at" in m), "")
        check("a rebase conflict stops before the push and keeps the worktree",
              rc == 2 and "theirs" in sh(remote, "show", "main:a.md").stdout and kept and Path(kept).is_dir())
        if kept:
            subprocess.run(["git", "-C", str(live), "worktree", "remove", "--force", kept], capture_output=True)
            shutil.rmtree(Path(kept).parent, ignore_errors=True)

        # an untracked copy placed in live is removed only when origin holds the same bytes
        (live / "notes").mkdir()
        mine = live / "notes" / "mine.md"
        mine.write_text("mine exactly\n", encoding="utf-8")
        rc = commit_from_origin_worktree(live, "notes\n", copies=[(mine, "notes/mine.md")],
                                         remove_live_copies=True, log=quiet)
        check("--remove-live-copies deletes the untracked live copy once origin has identical bytes",
              rc == 0 and not mine.exists())
        check("the tracked foreign dirty file in live is still there", (live / "a.md").read_text() == "foreign dirty edit\n")

        # my change edited IN live on a tracked file: pushed from the worktree, live is left untouched and
        # gets the catch-up recipe; the recipe works, and the unstaged form really aborts (foil)
        probe = T / "probe"
        subprocess.run(["git", "clone", "-q", str(remote), str(probe)], capture_output=True, check=True)
        sh(probe, "config", "user.email", "t@t"); sh(probe, "config", "user.name", "t")
        (probe / "tracked.md").write_text("v1\n", encoding="utf-8")
        sh(probe, "add", "tracked.md"); sh(probe, "commit", "-q", "-m", "tracked v1"); sh(probe, "push", "-q")
        sh(probe, "fetch", "-q")
        (probe / "tracked.md").write_text("v2 mine\n", encoding="utf-8")
        msgs2 = []
        rc = commit_from_origin_worktree(probe, "v2\n", copies=[(probe / "tracked.md", "tracked.md")],
                                         remove_live_copies=True, log=lambda m: msgs2.append(m))
        hint = next((m for m in msgs2 if "is tracked and now equals" in m), "")
        check("a tracked live copy is left in place and the catch-up recipe is printed",
              rc == 0 and hint and (probe / "tracked.md").read_text() == "v2 mine\n")
        sh(probe, "fetch", "-q")
        aborted = subprocess.run(["git", "-C", str(probe), "merge", "--ff-only", "origin/main"],
                                 capture_output=True, text=True).returncode != 0
        subprocess.run(["bash", "-c", hint.split("to catch live up: ", 1)[1]], capture_output=True)
        check("the recipe catches live up cleanly, and without `add` the fast-forward aborts (the foil has teeth)",
              aborted and sh(probe, "status", "--porcelain").stdout == ""
              and sh(probe, "rev-parse", "HEAD").stdout == sh(probe, "rev-parse", "origin/main").stdout)

        # whole-file copy guard: upstream changed the file / the live base carries a foreign unpushed hunk
        sh(other, "pull", "-q")
        (other / "shared.md").write_text("v1\n", encoding="utf-8")
        sh(other, "add", "shared.md"); sh(other, "commit", "-q", "-m", "v1"); sh(other, "push", "-q")
        sh(live, "fetch", "-q")
        (other / "shared.md").write_text("v2 upstream\n", encoding="utf-8")
        sh(other, "commit", "-qam", "v2"); sh(other, "push", "-q")
        my_v1_edit = T / "shared-mine.md"
        my_v1_edit.write_text("v1 plus my line\n", encoding="utf-8")
        before = sh(remote, "rev-parse", "main").stdout
        rc = commit_from_origin_worktree(live, "x\n", copies=[(my_v1_edit, "shared.md")], log=quiet)
        check("a copy of a file that changed upstream since the live base is refused  [foil: silent revert]",
              rc == 1 and sh(remote, "rev-parse", "main").stdout == before)
        (live / "foreign.md").write_text("foreign unpushed\nplus a foreign hunk\n", encoding="utf-8")
        sh(live, "commit", "-q", "-m", "foreign hunk, unpushed", "--", "foreign.md")
        mixed = T / "foreign-mine.md"
        mixed.write_text("foreign unpushed\nplus a foreign hunk\nplus mine\n", encoding="utf-8")
        rc = commit_from_origin_worktree(live, "x\n", copies=[(mixed, "foreign.md")], log=quiet)
        check("a copy whose live base carries a foreign unpushed commit is refused  [foil: publish by copy]",
              rc == 1 and "foreign.md" not in sh(remote, "ls-tree", "--name-only", "main").stdout)

        if shutil.which("git-crypt"):
            cs = T / "crypt-src"
            subprocess.run(["git", "init", "-q", "-b", "main", str(cs)], check=True)
            sh(cs, "config", "user.email", "t@t"); sh(cs, "config", "user.name", "t")
            subprocess.run(["git-crypt", "init"], cwd=cs, capture_output=True, check=True)
            (cs / ".gitattributes").write_text("secret.txt filter=git-crypt diff=git-crypt\n", encoding="utf-8")
            (cs / "secret.txt").write_text("plain secret\n", encoding="utf-8")
            sh(cs, "add", "-A"); sh(cs, "commit", "-q", "-m", "base")
            subprocess.run(["git", "clone", "-q", "--bare", str(cs), str(T / "crypt.git")], check=True)
            sh(cs, "remote", "add", "origin", str(T / "crypt.git")); sh(cs, "fetch", "-q", "origin")
            sh(cs, "branch", "-q", "-u", "origin/main")
            plain = subprocess.run(["git", "-C", str(cs), "worktree", "add", "-q", "--detach", str(T / "plainwt"),
                                    "origin/main"], capture_output=True, text=True)
            check("git-crypt: a plain worktree add fails at the smudge filter (the foil has teeth)",
                  plain.returncode != 0 and "smudge" in plain.stderr)
            subprocess.run(["git", "-C", str(cs), "worktree", "prune"], capture_output=True)
            shutil.rmtree(T / "plainwt", ignore_errors=True)
            addition = T / "note.md"
            addition.write_text("crypt repo note\n", encoding="utf-8")
            rc = commit_from_origin_worktree(cs, "note\n", copies=[(addition, "note.md")],
                                             check_cmd='grep -q "plain secret" secret.txt', log=quiet)
            enc = subprocess.run(["git", "-C", str(T / "crypt.git"), "show", "main:secret.txt"], capture_output=True).stdout
            check("git-crypt: the worktree is decrypted (check read the plaintext) and the push succeeds",
                  rc == 0 and b"plain secret" not in enc and "note.md" in
                  sh(T / "crypt.git", "ls-tree", "--name-only", "main").stdout)
        else:
            print("[SKIP] git-crypt not installed")
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=Path, help="the live checkout (never modified)")
    ap.add_argument("-m", "--message-file", type=Path)
    ap.add_argument("--copy", action="append", default=[], metavar="SRC:DST")
    ap.add_argument("--apply", metavar="CMD")
    ap.add_argument("--check", metavar="CMD")
    ap.add_argument("--branch")
    ap.add_argument("--remove-live-copies", action="store_true")
    ap.add_argument("--allow-overwrite", action="store_true",
                    help="let --copy replace a file whose live-HEAD and origin versions differ")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.repo and a.message_file and (a.copy or a.apply)):
        ap.error("--repo, -m and at least one of --copy / --apply are required")
    copies = []
    for c in a.copy:
        s, sep, d = c.rpartition(":")
        if not sep or not s or not d or os.path.isabs(d):
            ap.error(f"--copy wants SRC:DST with DST relative to the repo: {c!r}")
        copies.append((Path(s).expanduser(), d))
    return commit_from_origin_worktree(a.repo, a.message_file.read_text(encoding="utf-8"), copies, a.apply,
                                       a.check, a.branch, a.remove_live_copies, allow_overwrite=a.allow_overwrite)


if __name__ == "__main__":
    sys.exit(main())
