#!/usr/bin/env python3
"""git-drop-path-history.py — ある file の全版を git の履歴から落とす (不可逆) を、 予行演習・本番・他 machine の追従の 3 段で安全に行う。

## なぜ要るのか

git-crypt のように版ごとに全文の blob が積まれる file (大きな台帳など) は、 分割しても過去の版が履歴に残り、
repo は縮まない。 落とすには履歴を書き換えて force-push するしかなく、 失敗すると取り返しがつかない:
他の machine の clone は古い履歴のまま分岐し、 他の session の push を消し、 commit の message に残した
判断の記録が消え、 書類に書いた commit 番号が引けなくなる。 本 script はその穴を 1 段ずつ塞ぐ。
手順と理由の正本 = [`docs/sensitive-repo-patterns.ja.md#pattern-2-4`](../docs/sensitive-repo-patterns.ja.md#pattern-2-4)。

## 3 段

    # 1. 予行演習 (remote と手元の checkout には触らない): remote から mirror clone → 書き換え → 検証
    python3 git-drop-path-history.py rehearse --remote git@host:owner/repo.git --path TODO.yaml --work ~/backup/rewrite --name repo

    # 2. 本番 (不可逆): 予行演習の後に remote も手元も進んでいないことを確かめてから force-push、 手元は ref だけ動かす
    python3 git-drop-path-history.py apply --work ~/backup/rewrite --name repo --local ~/src/repo [--map-out repo.commit-map]

    # 3. 他の machine で 1 回: 手元の HEAD と「落とした file を除いて同じ中身」 の commit が新しい履歴に在るときだけ ref を動かす
    python3 git-drop-path-history.py follow --local ~/src/repo --path TODO.yaml

    # 4. (任意) 手元を今すぐ縮める: 旧 object は手元の reflog が掴んでいて、 放っておけば 30 日後の自動 gc まで残る
    python3 git-drop-path-history.py shrink --local ~/src/repo

- 予行演習は **remote からの mirror clone** で行う (手元の checkout から clone すると stash など手元の ref まで運ぶ)。
  `--prune-empty never` で、 その file だけを変えた commit も空 commit として残す (message に残した判断の記録を失わない。
  大きさは blob で決まるのでほぼ変わらない)。 検証 = file が残る commit 0 件 / 既定 branch の tree が不変 / commit 数が不変。
  旧 SHA → 新 SHA の対応表 (`<name>.commit-map`) を残す (書類に書いた旧番号を後から引く)。
- 本番は remote の先頭が予行演習の時の値か (`--force-with-lease`)、 手元の HEAD がそれと同じか、 を確かめ、 違えば止まる。
  手元は中身が同じなので `git reset --keep` で ref だけ動かす (未 commit の変更は保たれる)。
- 追従は、 見つからなければ止まる (= 未 push の commit がある)。 `git pull --rebase` は古い commit を新しい履歴に積み直すので使わない。
  出力: 揃えた時は「揃えた」 を含む 1 行 (呼び元が 1 回だけ知らせる目印)、 既に揃っている / clone が無い時は exit 0、 止まった時は exit 1。
- 本番・追従の直後、 手元の `.git` は書き換え前より**大きい** (旧 object を reflog が掴んだまま新しい object が増える、 実測)。
  `shrink` は届かない reflog を今すぐ切って gc する。 stash が在れば止まる (古い stash は reflog にしか無く、 切ると消える)。
  戻れなくなるのは手元だけ = 書き換えの前に取った bundle が控え。

## 限界

- `rehearse` は `git filter-repo` が要る (`pip install --user git-filter-repo`)。 Claude Code の auto mode は scratch の複製に対して
  でも filter-repo を破壊的な git 操作として止める (実測) = rehearse と apply は本人が terminal で走らせる。
- `--selftest` は filter-repo を使わない部分 (追従の照合・本番の前提の検査と push・reset) を合成の repo で確かめる。
  filter-repo を通す経路は `--selftest-rewrite` (本人の terminal で、 合成の repo だけを書き換える)。
- remote が縮むのは host 側の gc の後 (GitHub は数日〜数か月)。 pull request の ref など消せない ref が在ると旧 object は残る
  (`rehearse` が ref の一覧を出す)。 書き換えの前に `git bundle create <file> --all` で控えを取る。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GIT_ENV_DROP = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY")


def _env() -> dict:
    """hook から呼ばれても別 repo の index を読まない (hook-authoring.md#hook-git-env-cross-repo)。"""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    return env


def git(repo, *args, check=True, capture=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=capture, text=True, env=_env())
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or '').strip()[:300]}")
    return (r.stdout or "").strip()


def signature(repo, rev: str, drop_path: str) -> str:
    """落とす file を除いた tree の指紋 (= 中身が同じかの判定)。"""
    listing = git(repo, "ls-tree", "-r", rev)
    lines = [l for l in listing.splitlines() if l.split("\t", 1)[-1] != drop_path]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def filter_repo_bin() -> str | None:
    found = shutil.which("git-filter-repo")
    if found:
        return found
    for base in (Path.home() / "Library/Python").glob("*/bin/git-filter-repo"):
        return str(base)
    return None


# ---------------------------------------------------------------- rehearse

def cmd_rehearse(a) -> int:
    fr = filter_repo_bin()
    if not fr:
        print("git-filter-repo が無い (pip install --user git-filter-repo)", file=sys.stderr)
        return 2
    work = Path(a.work).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    mirror = work / f"{a.name}.git"
    if mirror.exists():
        shutil.rmtree(mirror)
    subprocess.run(["git", "clone", "-q", "--mirror", a.remote, str(mirror)], check=True, env=_env())
    refs = git(mirror, "for-each-ref", "--format=%(refname)").splitlines()
    old_main = git(mirror, "rev-parse", a.branch)
    old_tree = git(mirror, "rev-parse", f"{a.branch}^{{tree}}")
    n_before = int(git(mirror, "rev-list", "--count", "--all"))
    size_before = git(mirror, "count-objects", "-vH")
    print(f"########## {a.name}")
    print(f"  前: {_pack(size_before)} / commit {n_before} / ref {len(refs)}: {' '.join(r.replace('refs/', '') for r in refs)}")
    env = _env()
    env["PATH"] = str(Path(fr).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run(["git", "-C", str(mirror), "filter-repo", "--force", "--prune-empty", "never",
                    "--path", a.path, "--invert-paths"], check=True, env=env, stdout=subprocess.DEVNULL)
    git(mirror, "reflog", "expire", "--expire=now", "--all")
    git(mirror, "gc", "-q", "--prune=now")
    n_after = int(git(mirror, "rev-list", "--count", "--all"))
    left = git(mirror, "log", "--all", "--oneline", "--", a.path)
    print(f"  後: {_pack(git(mirror, 'count-objects', '-vH'))} / commit {n_after}")
    ok = True
    print(f"  {a.path} が残る commit: {len(left.splitlines()) if left else 0} (0 のはず)")
    ok &= not left
    same_tree = git(mirror, "rev-parse", f"{a.branch}^{{tree}}") == old_tree
    print(f"  {a.branch} の中身: {'同じ' if same_tree else '❌ 変わった'} (tree {old_tree[:12]})")
    ok &= same_tree
    print(f"  commit 数: {'同じ' if n_after == n_before else f'❌ {n_before} → {n_after}'}")
    ok &= n_after == n_before
    (work / f"{a.name}.old-main").write_text(old_main + "\n")
    (work / f"{a.name}.remote").write_text(a.remote + "\n")
    cm = mirror / "filter-repo" / "commit-map"
    if cm.exists():
        shutil.copy(cm, work / f"{a.name}.commit-map")
    print(f"  {a.branch}: {old_main[:12]} → {git(mirror, 'rev-parse', a.branch)[:12]}")
    if not ok:
        print("  ❌ 検証に落ちた = 本番に進まない", file=sys.stderr)
        return 1
    print("  予行演習 OK (本番 = apply)")
    return 0


def _pack(count_objects: str) -> str:
    for line in count_objects.splitlines():
        if line.startswith("size-pack"):
            return line
    return "size-pack: ?"


# ---------------------------------------------------------------- apply

def cmd_apply(a) -> int:
    work = Path(a.work).expanduser()
    mirror, old_f, remote_f = work / f"{a.name}.git", work / f"{a.name}.old-main", work / f"{a.name}.remote"
    if not (mirror.is_dir() and old_f.is_file() and remote_f.is_file()):
        print(f"{a.name}: 予行演習の結果が無い (先に rehearse)", file=sys.stderr)
        return 2
    old = old_f.read_text().strip()
    remote = remote_f.read_text().strip()
    local = Path(a.local).expanduser()
    now = git(local, "ls-remote", remote, f"refs/heads/{a.branch}").split("\t")[0] if remote else ""
    if now != old:
        print(f"{a.name}: remote の {a.branch} が予行演習の後に進んだ ({old[:7]} → {now[:7]})。 rehearse をやり直す", file=sys.stderr)
        return 1
    head = git(local, "rev-parse", "HEAD")
    if head != old:
        print(f"{a.name}: 手元の HEAD ({head[:7]}) が remote の {a.branch} と違う (未 push の commit?)。 push してから rehearse をやり直す",
              file=sys.stderr)
        return 1
    if git(mirror, "remote", check=False) and "origin" in git(mirror, "remote").split():
        git(mirror, "remote", "set-url", "origin", remote)
    else:
        git(mirror, "remote", "add", "origin", remote)
    git(mirror, "push", "-q", f"--force-with-lease={a.branch}:{old}", "origin", f"refs/heads/{a.branch}:refs/heads/{a.branch}")
    git(local, "fetch", "-q", "origin")
    git(local, "reset", "-q", "--keep", f"origin/{a.branch}")
    new = git(local, "rev-parse", "HEAD")
    print(f"{a.name}: remote と手元: {a.branch} = {new[:7]} (旧 {old[:7]})")
    cm = work / f"{a.name}.commit-map"
    if a.map_out and cm.exists():
        shutil.copy(cm, Path(a.map_out).expanduser())
        print(f"  旧 → 新 SHA の対応表: {a.map_out}")
    print(f"  手元の .git は旧 object を reflog が掴んだまま (30 日後の自動 gc まで)。 今すぐ縮めるなら shrink --local {local}")
    return 0


# ---------------------------------------------------------------- follow

def cmd_follow(a) -> int:
    local = Path(a.local).expanduser()
    name = local.name
    if not (local / ".git").exists():
        print(f"{name}: clone が無い = skip")
        return 0
    git(local, "fetch", "-q", "origin")
    target = f"origin/{a.branch}"
    if subprocess.run(["git", "-C", str(local), "merge-base", "--is-ancestor", "HEAD", target],
                      capture_output=True, env=_env()).returncode == 0:
        print(f"{name}: 既に新しい履歴 (fast-forward で追いつける) = skip")
        return 0
    want = signature(local, "HEAD", a.path)
    found = ""
    for c in git(local, "rev-list", f"--max-count={a.max}", target).splitlines():
        if signature(local, c, a.path) == want:
            found = c
            break
    if not found:
        print(f"{name}: 手元の HEAD と同じ中身の commit が新しい履歴に無い = 未 push の commit がある。 中身を確かめてから手で揃える "
              f"(git pull --rebase はしない = 古い commit を新しい履歴に積み直す)", file=sys.stderr)
        return 1
    git(local, "reset", "-q", "--keep", target)
    print(f"{name}: 新しい履歴に揃えた (手元の HEAD = 新履歴の {found[:7]} と同じ中身 → {a.branch} = {git(local, 'rev-parse', '--short', 'HEAD')})")
    return 0


# ---------------------------------------------------------------- shrink

def cmd_shrink(a) -> int:
    local = Path(a.local).expanduser()
    name = local.name
    if not (local / ".git").exists():
        print(f"{name}: clone が無い = skip")
        return 0
    if git(local, "stash", "list"):
        print(f"{name}: stash が在る = 止まる (古い stash は reflog にしか無く、 reflog を切ると消える。 先に stash を片付ける)",
              file=sys.stderr)
        return 1
    before = git(local, "count-objects", "-vH")
    git(local, "reflog", "expire", "--expire-unreachable=now", "--all")
    git(local, "gc", "-q", "--prune=now")
    after = git(local, "count-objects", "-vH")
    print(f"{name}: 手元を縮めた ({_pack(before)} → {_pack(after)})")
    return 0


# ---------------------------------------------------------------- selftest

def _fixture(tmp: Path):
    """旧履歴 (P を持つ) を remote に置き、 手元に clone、 P を除いた同じ中身の新履歴を作る (filter-repo を使わない)。"""
    env = dict(_env(), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    os.environ.update({k: env[k] for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                                           "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")})
    remote = tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True, env=_env())
    src = tmp / "src"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True, env=_env())
    steps = [({"ledger.yaml": "a\n", "x.txt": "1\n"}, "c1"), ({"ledger.yaml": "b\n", "x.txt": "2\n"}, "c2"),
             ({"ledger.yaml": None, "x.txt": "3\n"}, "c3")]
    for files, msg in steps:
        for f, body in files.items():
            if body is None:
                git(src, "rm", "-q", f)
            else:
                (src / f).write_text(body)
                git(src, "add", f)
        git(src, "commit", "-q", "-m", msg)
    git(src, "remote", "add", "origin", str(remote))
    git(src, "push", "-q", "origin", "main")
    # 新履歴 (ledger.yaml を除く同じ中身) を別 repo で作る
    new = tmp / "new"
    subprocess.run(["git", "init", "-q", "-b", "main", str(new)], check=True, env=_env())
    for body, msg in (("1\n", "c1"), ("2\n", "c2"), ("3\n", "c3")):
        (new / "x.txt").write_text(body)
        git(new, "add", "x.txt")
        git(new, "commit", "-q", "--allow-empty", "-m", msg)
    return remote, src, new


def selftest() -> int:
    fails = []

    def check(label, ok):
        print(("  ok: " if ok else "  NG: ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        remote, src, new = _fixture(tmp)
        check("指紋は落とす file を除いて比べる (c2 と c3 は x.txt が違う)",
              signature(src, "HEAD~1", "ledger.yaml") != signature(src, "HEAD", "ledger.yaml"))
        check("指紋: 旧 c2 (ledger あり) と新 c2 (ledger なし) は同じ中身",
              signature(src, "HEAD~1", "ledger.yaml") == signature(new, "HEAD~1", "ledger.yaml"))
        # 手元 = 旧 c2 の clone (未 push なし)、 もう 1 つ = 旧 c3 に未 push の commit を足した clone
        a = tmp / "a"
        subprocess.run(["git", "clone", "-q", str(remote), str(a)], check=True, env=_env())
        git(a, "reset", "-q", "--hard", "HEAD~1")
        b = tmp / "b"
        subprocess.run(["git", "clone", "-q", str(remote), str(b)], check=True, env=_env())
        (b / "x.txt").write_text("unpushed\n")
        git(b, "commit", "-q", "-am", "unpushed")
        (a / "scratch.txt").write_text("keep me\n")  # 未追跡 file は reset --keep で残る
        # remote を新履歴に置き換える (合成の remote だけ)
        git(new, "push", "-q", "--force", str(remote), "main:main")
        ns = argparse.Namespace(local=str(a), path="ledger.yaml", branch="main", max=50)
        rc = cmd_follow(ns)
        check("追従: 同じ中身の commit が新履歴に在れば揃える (exit 0)", rc == 0)
        check("追従: 揃えた後の HEAD = 新履歴の先頭 (fast-forward できる位置)",
              git(a, "rev-parse", "HEAD") == git(new, "rev-parse", "HEAD"))
        check("追従: 未追跡の file は残る", (a / "scratch.txt").exists())
        check("追従: 2 回目は「既に」 で exit 0", cmd_follow(ns) == 0)
        nb = argparse.Namespace(local=str(b), path="ledger.yaml", branch="main", max=50)
        check("追従: 未 push の commit がある clone は止まる (exit 1、 ref は動かない)",
              cmd_follow(nb) == 1 and git(b, "log", "-1", "--format=%s") == "unpushed")
        check("追従: clone が無ければ skip (exit 0)",
              cmd_follow(argparse.Namespace(local=str(tmp / "none"), path="ledger.yaml", branch="main", max=50)) == 0)

        # apply の前提の検査と本番 (合成の remote に対してだけ push する)
        remote2 = tmp / "remote2.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote2)], check=True, env=_env())
        git(src, "push", "-q", str(remote2), "main:main")
        local2 = tmp / "local2"
        subprocess.run(["git", "clone", "-q", str(remote2), str(local2)], check=True, env=_env())
        work = tmp / "work"
        work.mkdir()
        subprocess.run(["git", "clone", "-q", "--mirror", str(new), str(work / "r.git")], check=True, env=_env())
        git(work / "r.git", "remote", "remove", "origin")
        old = git(src, "rev-parse", "HEAD")
        (work / "r.remote").write_text(str(remote2) + "\n")
        (work / "r.old-main").write_text("0" * 40 + "\n")
        na = argparse.Namespace(work=str(work), name="r", local=str(local2), branch="main", map_out=None)
        check("本番: remote が予行演習の後に進んでいたら止まる (push しない)",
              cmd_apply(na) == 1 and git(local2, "ls-remote", str(remote2), "refs/heads/main").split("\t")[0] == old)
        (work / "r.old-main").write_text(old + "\n")
        (local2 / "x.txt").write_text("local edit\n")
        git(local2, "commit", "-q", "-am", "local only")
        check("本番: 手元に未 push の commit があれば止まる", cmd_apply(na) == 1)
        git(local2, "reset", "-q", "--hard", "origin/main")
        (local2 / "wip.txt").write_text("uncommitted\n")
        check("本番: 前提が揃えば force-push して手元を揃える", cmd_apply(na) == 0)
        check("本番: remote と手元が新履歴の先頭",
              git(local2, "rev-parse", "HEAD") == git(new, "rev-parse", "HEAD")
              == git(local2, "ls-remote", str(remote2), "refs/heads/main").split("\t")[0])
        check("本番: 手元の未 commit の file は残る", (local2 / "wip.txt").exists())
        # shrink: 手元の reflog だけが掴む旧 commit を落とす / stash が在れば止まる
        gone = git(local2, "rev-parse", "HEAD")
        (local2 / "x.txt").write_text("to be orphaned\n")
        git(local2, "commit", "-q", "-am", "orphan")
        orphan = git(local2, "rev-parse", "HEAD")
        git(local2, "reset", "-q", "--keep", gone)
        git(local2, "stash", "-q", "-u")
        check("縮める: stash が在れば止まる (reflog を切らない)",
              cmd_shrink(argparse.Namespace(local=str(local2))) == 1
              and subprocess.run(["git", "-C", str(local2), "cat-file", "-e", orphan], env=_env()).returncode == 0)
        git(local2, "stash", "pop", "-q")
        check("縮める: 前提が揃えば届かない旧 commit が消える",
              cmd_shrink(argparse.Namespace(local=str(local2))) == 0
              and subprocess.run(["git", "-C", str(local2), "cat-file", "-e", orphan], capture_output=True,
                                 env=_env()).returncode != 0)
        check("縮める: 手元の HEAD と未追跡の file はそのまま",
              git(local2, "rev-parse", "HEAD") == gone and (local2 / "wip.txt").exists())
        check("hook の env (GIT_INDEX_FILE) を子の git に渡さない",
              "GIT_INDEX_FILE" not in _env() if "GIT_INDEX_FILE" in os.environ else True)
    print(f"selftest: {'FAILED ' + str(len(fails)) if fails else 'ALL PASS'}")
    return 1 if fails else 0


def selftest_rewrite() -> int:
    """filter-repo を通す経路 (本人の terminal で): 合成の remote を rehearse → apply。"""
    if not filter_repo_bin():
        print("SKIP: git-filter-repo が無い")
        return 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        remote, src, _new = _fixture(tmp)
        local = tmp / "local"
        subprocess.run(["git", "clone", "-q", str(remote), str(local)], check=True, env=_env())
        ns = argparse.Namespace(remote=str(remote), path="ledger.yaml", work=str(tmp / "work"), name="r", branch="main")
        rc1 = cmd_rehearse(ns)
        rc2 = cmd_apply(argparse.Namespace(work=str(tmp / "work"), name="r", local=str(local), branch="main",
                                           map_out=str(tmp / "r.commit-map")))
        left = git(local, "log", "--all", "--oneline", "--", "ledger.yaml")
        ok = rc1 == 0 and rc2 == 0 and not left and (tmp / "r.commit-map").exists()
        print(f"selftest-rewrite: {'ALL PASS' if ok else 'FAILED'} (rehearse {rc1} / apply {rc2} / 残る版 {len(left.splitlines()) if left else 0})")
        return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--selftest-rewrite", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("rehearse")
    r.add_argument("--remote", required=True)
    r.add_argument("--path", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--name", required=True)
    r.add_argument("--branch", default="main")
    p = sub.add_parser("apply")
    p.add_argument("--work", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--local", required=True)
    p.add_argument("--branch", default="main")
    p.add_argument("--map-out")
    f = sub.add_parser("follow")
    f.add_argument("--local", required=True)
    f.add_argument("--path", required=True)
    f.add_argument("--branch", default="main")
    f.add_argument("--max", type=int, default=300)
    k = sub.add_parser("shrink")
    k.add_argument("--local", required=True)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.selftest_rewrite:
        return selftest_rewrite()
    if a.cmd == "rehearse":
        return cmd_rehearse(a)
    if a.cmd == "apply":
        return cmd_apply(a)
    if a.cmd == "follow":
        return cmd_follow(a)
    if a.cmd == "shrink":
        return cmd_shrink(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
