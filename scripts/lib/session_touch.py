"""session_touch.py — script が書いた file の repo を、 その session の「触った repo」 の list に載せる (hooks/session-commit-nudge.sh が読む)。

なぜ: session-commit-nudge.sh は PostToolUse の Edit / Write / MultiEdit で触った repo を数え、 turn の終わりに未 commit を催促する。
Bash から呼ばれた script (台帳を書く道具など) が書いた file は数えない = 書いたまま commit せずに別の仕事へ移っても催促が出なかった
(実測: 記録の道具で台帳を書いた session が commit しないまま 1 日以上生き、 その未 commit の変更が upstream の同じ file と重なって
同期の最新化を止め、 別の機械の session が同じ記録を二重に書いた)。 書く道具がここを呼べば、 Edit / Write と同じ催促に乗る。

state の形は hook と同じ (= <dir>/<session id>.list、 1 行 1 repo root、 重複なし)。 session の id が無い (= hook の外・無人の定期
実行の外側の script) なら何もしない。 失敗しても黙る (書く道具を止めない)。
env: SESSION_TOUCH_STATE_DIR (hook と同じ、 test 用) / CLAUDE_CODE_SESSION_ID (Claude Code の Bash の環境に在る)。
selftest: python3 session_touch.py --selftest
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def state_dir() -> Path:
    return Path(os.environ.get("SESSION_TOUCH_STATE_DIR") or (Path.home() / ".claude" / "state" / "session-touch"))


def register(paths, session_id: str | None = None) -> list[str]:
    """paths (書いた file か dir) の git repo root を session の list に足す。 足した・既に在った root の list を返す。"""
    sid = session_id if session_id is not None else os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not sid or "/" in sid or sid.startswith("."):
        return []
    roots: list[str] = []
    for p in paths:
        try:
            q = Path(p)
            cwd = q if q.is_dir() else q.parent
            r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                roots.append(r.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    roots = list(dict.fromkeys(roots))
    if not roots:
        return []
    try:
        d = state_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{sid}.list"
        have = set(f.read_text(encoding="utf-8").splitlines()) if f.exists() else set()
        new = [r for r in roots if r not in have]
        if new:
            with open(f, "a", encoding="utf-8") as fh:
                for r in new:
                    fh.write(r + "\n")
    except OSError:
        return []
    return roots


def _selftest() -> int:
    import tempfile
    fails = 0

    def check(cond, name):
        nonlocal fails
        print(("  PASS: " if cond else "  FAIL: ") + name)
        fails += 0 if cond else 1

    keep = os.environ.get("SESSION_TOUCH_STATE_DIR")
    with tempfile.TemporaryDirectory() as td:
        T = Path(td).resolve()
        os.environ["SESSION_TOUCH_STATE_DIR"] = str(T / "state")
        try:
            repo = T / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            (repo / "inbox").mkdir()
            f1, f2 = repo / "inbox" / "a.yaml", repo / "b.yaml"
            f1.write_text("x\n", encoding="utf-8")
            f2.write_text("y\n", encoding="utf-8")
            root = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
            got = register([f1, f2], session_id="sess-1")
            lst = (T / "state" / "sess-1.list").read_text(encoding="utf-8").splitlines()
            check(got == [root] and lst == [root], "書いた 2 file の repo root を 1 行だけ載せる (hook と同じ形)")
            register([f1], session_id="sess-1")
            check((T / "state" / "sess-1.list").read_text(encoding="utf-8").splitlines() == [root], "2 回目は足さない (重複なし)")
            outside = T / "plain.txt"
            outside.write_text("z\n", encoding="utf-8")
            check(register([outside], session_id="sess-2") == [] and not (T / "state" / "sess-2.list").exists(),
                  "git の外の file は何もしない")
            check(register([f1], session_id="") == [] and register([f1], session_id="../x") == [],
                  "session の id が無い・形が変なら何もしない")
        finally:
            if keep is None:
                os.environ.pop("SESSION_TOUCH_STATE_DIR", None)
            else:
                os.environ["SESSION_TOUCH_STATE_DIR"] = keep
    print(f"selftest: {'PASS' if not fails else 'FAIL'} ({fails} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__)
    sys.exit(2)
