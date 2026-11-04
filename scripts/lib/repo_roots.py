#!/usr/bin/env python3
"""repo_roots.py — 走査の root を 1 つの repo として見るか、 直下の子の repo を数えるかの共通の判定 (repo を並べた作業ルートを fleet scan する道具が使う)。

`root_is_repo(root)` = root 直下に `.git` があり、 その repo が commit か tracked file を持つときだけ True。
commit も tracked file も無い空の repo (repo を並べた作業ルートで誤って `git init` した形) は False = 呼ぶ側は
直下の子の repo を数える。 git が読めずに判定できないとき (gitdir が壊れている・所有者の検査で断られる) は True
= `.git` の有無だけで決めていた従来の結果を変えない。

なぜ: 「root に `.git` があれば root だけを走査し、 無ければ直下の子の repo」 という判定は、 作業ルートに空の repo が
  1 つできるだけで子の repo を全部隠す。 隠れた道具は root の 0 件の file を走査して何も出さない = 失敗が「異常なし」
  に見える (実測 = 作業ルートで単独の `cd` が戻された後の `git init` が作業ルートに repo を作り、 節参照の検査・壊れた
  text の検査・学生の識別子の棚卸しなど同じ形の道具が揃って root だけを見ていた)。 空の repo を作る経路 =
  conventions/claude-code-permissions.md#cd-with-git-goes-to-classifier (単独の cd の行き先は session の folder の中に)。

使い方: 子の列挙 (隠し dir・symlink を除くか) は呼ぶ側の規則のままにし、 root の判定だけをこれに替える。
    if root_is_repo(root):
        return [root]
    return sorted(d for d in root.iterdir() if d.is_dir() and (d / ".git").exists())

commit 中の repo の pre-commit から呼ばれても、 その repo の一時 index (GIT_INDEX_FILE など) を root の読みに
持ち込まない (env から外して git を呼ぶ)。

selftest: python3 scripts/lib/repo_roots.py --selftest
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Union

# commit 中の repo の pre-commit から呼ばれると、 これらが別の repo の読みを commit 中の repo の index に向ける
_GIT_REPO_ENV = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")


def _git(root: Path, *args: str) -> "subprocess.CompletedProcess[bytes] | None":
    env = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_ENV}
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError):
        return None


def root_is_repo(root: Union[str, Path]) -> bool:
    """root を 1 つの repo として走査するか (上の規則)。"""
    root = Path(root)
    if not (root / ".git").exists():
        return False
    head = _git(root, "rev-parse", "-q", "--verify", "HEAD^{commit}")
    if head is not None and head.returncode == 0:
        return True  # commit がある = 普通の repo (速い道)
    files = _git(root, "ls-files", "-z")
    if files is None or files.returncode != 0:
        return True  # 判定できない = 従来どおり root を repo とみなす
    return bool(files.stdout.strip(b"\0"))  # commit が無くても tracked file があれば repo


def selftest() -> int:
    import tempfile

    fails = []

    def expect(label: str, ok: bool) -> None:
        print(("  ok: " if ok else "  NG: ") + label)
        if not ok:
            fails.append(label)

    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")

    def sh(cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True, check=True)

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        plain = t / "plain"
        plain.mkdir()
        expect("`.git` の無い dir = repo でない", not root_is_repo(plain))
        empty = t / "empty"
        empty.mkdir()
        sh(empty, "init", "-q")
        (empty / "child").mkdir()
        sh(empty / "child", "init", "-q")
        expect("commit も tracked file も無い空の repo = repo とみなさない (陽性対照 = 子を隠す形)", not root_is_repo(empty))
        staged = t / "staged"
        staged.mkdir()
        sh(staged, "init", "-q")
        (staged / "a.md").write_text("x\n", encoding="utf-8")
        sh(staged, "add", "a.md")
        expect("commit が無くても tracked file があれば repo", root_is_repo(staged))
        committed = t / "committed"
        committed.mkdir()
        sh(committed, "init", "-q")
        (committed / "a.md").write_text("x\n", encoding="utf-8")
        sh(committed, "add", "a.md")
        sh(committed, "commit", "-qm", "init")
        expect("commit のある repo = repo", root_is_repo(committed))
        broken = t / "broken"
        broken.mkdir()
        (broken / ".git").write_text("gitdir: " + str(t / "no-such-gitdir") + "\n", encoding="utf-8")
        expect("git が読めない (gitdir が無い) = 判定できない = 従来どおり repo", root_is_repo(broken))
        saved = {k: os.environ.get(k) for k in ("GIT_INDEX_FILE", "GIT_DIR")}
        os.environ["GIT_INDEX_FILE"] = str(committed / ".git" / "index")
        os.environ["GIT_DIR"] = str(committed / ".git")
        try:
            expect("commit 中の別の repo の GIT_INDEX_FILE / GIT_DIR を読みに持ち込まない", not root_is_repo(empty))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    print("selftest " + ("ok" if not fails else "FAIL (%d)" % len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    for a in sys.argv[1:]:
        print(f"{a}\t{'repo' if root_is_repo(a) else '子の repo を数える'}")
