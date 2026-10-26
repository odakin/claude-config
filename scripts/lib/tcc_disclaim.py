#!/usr/bin/env python3
"""tcc_disclaim.py — macOS で、 子 process を「自分がプライバシー許可 (TCC) の責任者」 として起動する。

なぜ存在するか (一般形、 実測は下の層の記録):
  macOS のプライバシー許可 (カレンダー・連絡先・写真など) は、 起動した側を辿った「責任者」 の process で判定される。
  Claude Code desktop の Bash から呼んだ CLI は Claude の helper app が責任者になり、 その helper が利用目的の宣言
  (Info.plist の NSCalendarsUsageDescription など) を持たないと、 確認の画面も出ずに拒否される。 システム設定の
  その項目 (カレンダー等) には「＋」 が無いので、 人が足して直すこともできない。 CLI 自身が許可を持っていても
  (launchd の定期ジョブなど、 CLI が自分の責任者になる経路で付与済み) この経路では効かない。
  posix_spawn に responsibility の disclaim を付けて起動すると、 子が自分の責任者になり、 CLI 自身の許可で動く
  (Terminal や launchd が子を起動するときと同じ)。

使い方:
    from tcc_disclaim import run_disclaimed
    r = run_disclaimed(["/path/to/cli", "arg"], cwd="/dir", timeout=10)
    if r is not None and r.returncode == 0: ... r.stdout ...
  戻り値 = Result(returncode, stdout, stderr) (str)。 timeout で kill したら returncode = -9 で stderr に一言。
  macOS 以外・関数が無い・起動に失敗したときは None = 呼び元は従来の経路に戻る。
  終わるまで待たずに出力を流して読むなら spawn_disclaimed (pid を返す。 子の fd は {子の fd: 親の fd} で渡し、
  渡さない fd は親のものを継ぐ。 待つのは呼び元 = os.waitpid)。 使い手 = scripts/claude-stream-log.py (無人の claude を
  責任者のまま起動して出力を log に直す)。

⚠️ 子の許可がまだ無ければ、 子の名前で確認の画面が出て、 応答があるまで子は待つ = timeout で kill する
  (無人の hook から呼ぶなら timeout を短く)。 ⚠️ 責任者を子に移すのは、 子が自分の許可で動くべきときだけに使う
  (親の権限を借りて許可を迂回するものではない = 子に許可が無ければ拒否か確認の画面になる)。
  使う関数 (responsibility_spawnattrs_setdisclaim) は libSystem の非公開 API。 無ければ None。
正本 = conventions/macos-notification-db.md#tcc-responsible-process
test = `python3 scripts/lib/tcc_disclaim.py --selftest`
"""
from __future__ import annotations

import ctypes
import os
import select
import signal
import sys
import time
from typing import NamedTuple


class Result(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def _libc():
    if sys.platform != "darwin":
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None
    return libc if hasattr(libc, "responsibility_spawnattrs_setdisclaim") else None


def spawn_disclaimed(argv: list[str], cwd: str | None = None, env: dict | None = None,
                     fds: dict[int, int] | None = None) -> int | None:
    """argv を disclaim つきで起動して pid を返す (待たない)。 起動できなければ None。

    fds = {子の fd: 親の fd} (例 {0: devnull, 1: pipe の書き口})。 渡した親の fd は子では閉じる (dup2 の後)。
    渡さない fd は親のものを継ぐ。 argv[0] は絶対 path か cwd 相対 (PATH を引かない)。"""
    libc = _libc()
    if libc is None or not argv:
        return None
    prog = os.fsencode(argv[0])
    if b"/" not in prog:
        return None  # PATH を引かない (呼び元が絶対 path か cwd 相対を渡す)
    vp = ctypes.c_void_p
    attr, fa = vp(), vp()
    if libc.posix_spawnattr_init(ctypes.byref(attr)) != 0:
        return None
    libc.responsibility_spawnattrs_setdisclaim.argtypes = [ctypes.POINTER(vp), ctypes.c_int]
    if libc.responsibility_spawnattrs_setdisclaim(ctypes.byref(attr), 1) != 0:
        libc.posix_spawnattr_destroy(ctypes.byref(attr))
        return None
    libc.posix_spawn_file_actions_init(ctypes.byref(fa))
    pid = ctypes.c_int()
    try:
        pairs = dict(fds or {})
        for child_fd, parent_fd in pairs.items():
            libc.posix_spawn_file_actions_adddup2(ctypes.byref(fa), parent_fd, child_fd)
        for parent_fd in set(pairs.values()) - set(pairs):
            libc.posix_spawn_file_actions_addclose(ctypes.byref(fa), parent_fd)
        if cwd:
            if not hasattr(libc, "posix_spawn_file_actions_addchdir_np"):
                return None
            libc.posix_spawn_file_actions_addchdir_np(ctypes.byref(fa), os.fsencode(cwd))
        c_argv = (ctypes.c_char_p * (len(argv) + 1))(*[os.fsencode(a) for a in argv], None)
        envl = [os.fsencode(f"{k}={v}") for k, v in (env if env is not None else os.environ).items()]
        c_env = (ctypes.c_char_p * (len(envl) + 1))(*envl, None)
        rc = libc.posix_spawn(ctypes.byref(pid), prog, ctypes.byref(fa), ctypes.byref(attr), c_argv, c_env)
    finally:
        libc.posix_spawn_file_actions_destroy(ctypes.byref(fa))
        libc.posix_spawnattr_destroy(ctypes.byref(attr))
    return pid.value if rc == 0 else None


def run_disclaimed(argv: list[str], cwd: str | None = None, timeout: float = 10.0,
                   env: dict | None = None) -> Result | None:
    """argv を disclaim つきで起動し、 stdout / stderr を集めて返す。 起動できなければ None。"""
    if _libc() is None or not argv or b"/" not in os.fsencode(argv[0]):
        return None
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    try:
        # 読み口 (out_r / err_r) は子に渡さない = 子の側で閉じる (渡すと子が持ち続け、 親の読みが EOF にならない)
        for fd in (out_r, err_r):
            os.set_inheritable(fd, False)
        spawned = spawn_disclaimed(argv, cwd=cwd, env=env, fds={1: out_w, 2: err_w})
    finally:
        os.close(out_w)
        os.close(err_w)
    if spawned is None:
        os.close(out_r)
        os.close(err_r)
        return None
    pid = spawned
    bufs = {out_r: b"", err_r: b""}
    open_fds = [out_r, err_r]
    deadline = time.monotonic() + timeout
    killed = False
    while open_fds:
        left = deadline - time.monotonic()
        if left <= 0:
            os.kill(pid, signal.SIGKILL)
            killed = True
            break
        ready, _, _ = select.select(open_fds, [], [], min(left, 1.0))
        for fd in ready:
            chunk = os.read(fd, 65536)
            if chunk:
                bufs[fd] += chunk
            else:
                open_fds.remove(fd)
    for fd in (out_r, err_r):
        os.close(fd)
    _, status = os.waitpid(pid, 0)
    code = -9 if killed else (os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status))
    err = bufs[err_r].decode("utf-8", "replace")
    if killed:
        err += f"\n[tcc_disclaim] {timeout:g} 秒で応答が無く kill した (許可の確認の画面を待っていた可能性)"
    return Result(code, bufs[out_r].decode("utf-8", "replace"), err)


def _selftest() -> int:
    ok = fail = 0

    def check(cond: bool, label: str) -> None:
        nonlocal ok, fail
        print(("  PASS: " if cond else "  FAIL: ") + label)
        ok, fail = ok + bool(cond), fail + (not cond)

    if _libc() is None:
        print("  SKIP: macOS で disclaim の関数がある機械だけで回す")
        return 0
    r = run_disclaimed(["/bin/sh", "-c", "pwd; echo err >&2; exit 3"], cwd="/usr", timeout=5)
    check(r is not None and r.returncode == 3 and r.stdout.strip() == "/usr" and r.stderr.strip() == "err",
          "stdout・stderr・終了値・cwd を返す")
    r = run_disclaimed(["/bin/sleep", "5"], timeout=0.5)
    check(r is not None and r.returncode == -9 and "kill" in r.stderr, "timeout で kill して -9 を返す")
    check(run_disclaimed(["sh", "-c", "true"]) is None, "PATH を引く名前は起動しない (None)")
    check(run_disclaimed([]) is None, "空の argv は None")
    r = run_disclaimed(["/bin/sh", "-c", "printf %s \"$X\""], env={"X": "値"}, timeout=5)
    check(r is not None and r.stdout == "値", "env を渡せる (非 ASCII も)")
    # spawn_disclaimed: 流して読む経路 (stdin を /dev/null に、 stdout を pipe に、 stderr は継ぐ)
    rd, wr = os.pipe()
    dn = os.open(os.devnull, os.O_RDONLY)
    pid = spawn_disclaimed(["/bin/sh", "-c", "read x; echo \"got=$x\"; exit 4"], fds={0: dn, 1: wr})
    os.close(wr)
    os.close(dn)
    out = b""
    while pid is not None:
        chunk = os.read(rd, 4096)
        if not chunk:
            break
        out += chunk
    os.close(rd)
    st = os.waitpid(pid, 0)[1] if pid is not None else 0
    check(pid is not None and out == b"got=\n" and os.WEXITSTATUS(st) == 4,
          "spawn_disclaimed: pid を返し、 渡した fd (stdin = /dev/null・stdout = pipe) で動き、 終了値を waitpid で読める")
    getter = getattr(_libc(), "responsibility_get_pid_responsible_for_pid", None)
    if getter is not None:
        getter.argtypes, getter.restype = [ctypes.c_int], ctypes.c_int
        pid = spawn_disclaimed(["/bin/sleep", "1"])
        time.sleep(0.2)
        check(pid is not None and getter(pid) == pid, "spawn_disclaimed の子は自分が責任者 (responsible pid = 自分)")
        if pid is not None:
            os.waitpid(pid, 0)
    check(spawn_disclaimed(["sleep", "1"]) is None, "spawn_disclaimed も PATH を引く名前は起動しない (None)")
    print(f"\n==== RESULT: PASS={ok} FAIL={fail} ====")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv[1:] else 2)
