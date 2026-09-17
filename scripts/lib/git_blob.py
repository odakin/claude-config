#!/usr/bin/env python3
"""git の blob を worktree に出したときの中身で読む helper (git-crypt で暗号化される path も平文で)。

由来 (実測): `git show :<path>` / `git show <rev>:<path>` は blob をそのまま返すので、 git-crypt で暗号化される
path では暗号文 (先頭 `\\0GITCRYPT`) になる。 検査がそれを binary / 空 / 別物として読むと、 暗号化が既定の repo では
中身を見ないまま結論を出す (行頭 conflict marker の gate が素通りした。 bash 版の対処 = lib/staged-conflict-markers.sh)。
`git cat-file --filters <spec>` は smudge filter を通すので、 unlock 済みなら平文で返る
(同じ読み方の前例 = check-doc-truncation.py / check-ledger-merge-loss.py)。

- `--filters` が失敗したら (lock 中で復号できない等) `git show` に戻す = 従来と同じ中身 (fail-open)
- `GIT_LFS_SKIP_SMUDGE=1` = 検査のために LFS の object を取りに行かない (pointer のまま読む)

使い方:

    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from git_blob import read_blob, read_blob_text
    rc, data = read_blob(":notes/a.md", cwd=repo)          # bytes
    text = read_blob_text(f"{commit}:{rel}", cwd=repo)     # str (読めなければ None)

python3 git_blob.py で selftest (一時 repo で staged / commit の blob、 git-crypt があれば暗号化 path も確かめる)。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional, Tuple


def _run(args, cwd, timeout):
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, check=False, timeout=timeout)


def read_blob(spec: str, cwd=None, timeout: Optional[float] = None) -> Tuple[int, bytes]:
    """spec = ":<path>" (index) か "<rev>:<path>"。 (returncode, bytes) を返す。"""
    r = _run(["cat-file", "--filters", spec], cwd, timeout)
    if r.returncode == 0:
        return 0, r.stdout
    r = _run(["show", spec], cwd, timeout)
    return r.returncode, r.stdout


def read_blob_text(spec: str, cwd=None, timeout: Optional[float] = None, errors: str = "replace") -> Optional[str]:
    """read_blob を UTF-8 で decode。 読めなければ None。"""
    rc, data = read_blob(spec, cwd=cwd, timeout=timeout)
    return data.decode("utf-8", errors=errors) if rc == 0 else None


def selftest() -> int:
    import tempfile
    fails = []

    def expect(label, ok):
        print(("  ok: " if ok else "  NG: ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

        def git(*a, cwd=td):
            return subprocess.run(["git", *a], cwd=cwd, env=env, capture_output=True, check=False)

        if git("init", "-q").returncode != 0:
            print("SKIP: git not available")
            return 0
        git("config", "user.email", "t@example.invalid")
        git("config", "user.name", "t")
        with open(os.path.join(td, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("first 日本語\n")
        git("add", "a.txt")
        expect("staged blob of a plain path", read_blob_text(":a.txt", cwd=td) == "first 日本語\n")
        git("commit", "-qm", "a")
        with open(os.path.join(td, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("second\n")
        git("add", "a.txt")
        expect("commit blob differs from the index", read_blob_text("HEAD:a.txt", cwd=td) == "first 日本語\n"
               and read_blob_text(":a.txt", cwd=td) == "second\n")
        expect("missing path -> None", read_blob_text(":nope.txt", cwd=td) is None)

        # git-crypt が無い環境 (CI) でも同じ class を確かめる: 可逆な clean / smudge filter (rot13) を掛けると、 index の
        # blob は clean 後の形になり、 `git show` は別物を、 smudge を通す読み方は worktree と同じ中身を返す
        rt = os.path.join(td, "rot")
        os.makedirs(rt)
        git("init", "-q", cwd=rt)
        rot = "tr 'A-Za-z' 'N-ZA-Mn-za-m'"
        git("config", "filter.rot.clean", rot, cwd=rt)
        git("config", "filter.rot.smudge", rot, cwd=rt)
        with open(os.path.join(rt, ".gitattributes"), "w", encoding="utf-8") as fh:
            fh.write("f.yaml filter=rot\n")
        with open(os.path.join(rt, "f.yaml"), "w", encoding="utf-8") as fh:
            fh.write("status: open\n")
        git("add", "-A", cwd=rt)
        raw = subprocess.run(["git", "show", ":f.yaml"], cwd=rt, env=env, capture_output=True).stdout
        expect("fixture (no git-crypt needed): the raw staged blob of a filtered path is the cleaned form",
               raw == b"fgnghf: bcra\n")
        expect("filtered staged path is read through smudge", read_blob_text(":f.yaml", cwd=rt) == "status: open\n")

        if shutil.which("git-crypt") is None:
            print("SKIP: git-crypt tests (git-crypt not installed)")
        else:
            cr = os.path.join(td, "crypt")
            os.makedirs(cr)
            git("init", "-q", cwd=cr)
            git("config", "user.email", "t@example.invalid", cwd=cr)
            git("config", "user.name", "t", cwd=cr)
            subprocess.run(["git-crypt", "init"], cwd=cr, capture_output=True, check=False)
            with open(os.path.join(cr, ".gitattributes"), "w", encoding="utf-8") as fh:
                fh.write("* filter=git-crypt diff=git-crypt\n.gitattributes !filter !diff\n")
            with open(os.path.join(cr, "s.md"), "w", encoding="utf-8") as fh:
                fh.write("secret line\n")
            git("add", "-A", cwd=cr)
            raw = subprocess.run(["git", "show", ":s.md"], cwd=cr, capture_output=True).stdout
            expect("fixture: the raw staged blob is ciphertext", raw.startswith(b"\0GITCRYPT"))
            expect("encrypted staged path is read as plaintext", read_blob_text(":s.md", cwd=cr) == "secret line\n")
            git("commit", "-qm", "s", cwd=cr)
            expect("encrypted commit blob is read as plaintext", read_blob_text("HEAD:s.md", cwd=cr) == "secret line\n")
    print("git_blob selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
