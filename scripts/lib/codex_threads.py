#!/usr/bin/env python3
"""codex_threads.py — Codex threads on this machine: which are live, their cwd / title / model, and the command that hands one a message.

Why: Claude and Codex sessions on one machine coordinate through the board, and a post is a record, not a push
(ai-collaboration board CONTRACT#post-then-push). A Claude session is reached by SendMessage (`uds:` address,
lib/claude_config_dirs.py). A Codex thread has no SendMessage, but the Codex CLI has `codex queue --thread <id>
--message <text>`, which queues a user message for an existing thread. Measured with CLI 0.159.2 on one machine:

  - a thread loaded in a running client received the queued message as a new turn right after its current turn ended
    (a one-shot `codex exec` then exits and aborts that new turn; a desktop or TUI thread stays loaded);
  - a thread not loaded anywhere keeps the message in the queue until it is next opened.

Live = the thread's writer lock (`<CODEX_HOME>/thread-writer-locks/<id>.lock`) is held open by some process (read with
`lsof`; nothing here takes or tests a lock). A held lock with no threads row is not always an unreadable record.
Measured with CLI 0.166.0-alpha.6: each sub-agent the client spawns gets a guardian (approval reviewer) thread a few tens
of ms later, whose writer lock is held from creation while its row, rollout file and history are written only when its
first review turn starts; a guardian that is never asked to review stays lock-only until the client shuts it down. Once
its row exists it is a sub-agent (is_subagent), so such a thread is never anyone's peer. Metadata comes from Codex's local state database, opened read-only through
the same resolver the provenance hook uses (session_provenance_cache.codex_state_databases). Both are undocumented
local layout: every reader fails open (None / empty), so a changed layout reads as "unknown", never as an error and
never as "not live". Writes nothing. Convention: conventions/multi-account-machine-surface.md#codex-peers.

CLI: codex_threads.py [--live] [--json] | --resolve <id-or-prefix> | --selftest
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from session_provenance_cache import codex_state_databases  # one resolver for the state DB location
except Exception:  # pragma: no cover - partial checkout
    codex_state_databases = None

# The app bundle's CLI is current with the desktop app; a PATH `codex` (npm) can be older and lack `queue`.
BUNDLE_PATHS = (
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
    "/Applications/ChatGPT.app/Contents/Resources/codex",
)
THREAD_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PREFIX = re.compile(r"[0-9a-f][0-9a-f-]{7,35}")
COLUMNS = ("id", "cwd", "title", "name", "model", "reasoning_effort", "source", "updated_at", "archived")


def codex_home(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("CODEX_HOME") or Path(env.get("HOME", str(Path.home()))) / ".codex")


def held_lock_ids(env: dict | None = None, runner=None) -> set[str] | None:
    """Thread ids whose writer lock some process holds open; None when that cannot be read (no lsof, timeout)."""
    locks = codex_home(env) / "thread-writer-locks"
    if not locks.is_dir():
        return set()
    try:
        if runner is None:
            if not shutil.which("lsof"):
                return None
            proc = subprocess.run(["lsof", "-Fn", "+d", str(locks)], capture_output=True, text=True, timeout=5)
            if proc.returncode not in (0, 1):  # 1 = nothing open in the directory
                return None
            out = proc.stdout
        else:
            out = runner(locks)
    except (OSError, subprocess.SubprocessError):
        return None
    ids = set()
    for line in (out or "").splitlines():
        if line.startswith("n") and line.endswith(".lock"):
            stem = Path(line[1:]).name[:-5]
            if THREAD_ID.fullmatch(stem):
                ids.add(stem)
    return ids


def _connect(env: dict | None):
    if codex_state_databases is None:
        return None
    for database in codex_state_databases(dict(os.environ if env is None else env)):
        try:
            con = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)
            con.execute("PRAGMA query_only = ON")
            cols = {str(r[1]) for r in con.execute("PRAGMA table_info(threads)")}
            if "id" in cols:
                return con, [c for c in COLUMNS if c in cols]
            con.close()
        except (OSError, sqlite3.Error):
            continue
    return None


def thread_rows(ids=None, prefix: str | None = None, env: dict | None = None) -> list[dict]:
    """Rows of the threads table for the given ids, or for ids starting with `prefix`. [] when unreadable."""
    got = _connect(env)
    if got is None:
        return []
    con, cols = got
    try:
        sel = ", ".join(cols)
        if prefix is not None:
            rows = con.execute(f"SELECT {sel} FROM threads WHERE id LIKE ? LIMIT 3", (prefix + "%",)).fetchall()
        else:
            ids = list(ids or [])
            if not ids:
                return []
            marks = ",".join("?" * len(ids))
            rows = con.execute(f"SELECT {sel} FROM threads WHERE id IN ({marks})", ids).fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def resolve(token: str, env: dict | None = None) -> str | None:
    """A full thread id from a full id or a unique prefix (8+ characters, e.g. the hand-off name's native id)."""
    token = (token or "").strip().lower()
    if THREAD_ID.fullmatch(token):
        return token
    if not PREFIX.fullmatch(token):
        return None
    rows = thread_rows(prefix=token, env=env)
    return rows[0]["id"] if len(rows) == 1 else None


def is_subagent(row: dict) -> bool:
    """A sub-agent thread (a reviewer the client spawned) is live but not anyone's peer."""
    return "subagent" in str(row.get("source") or "")


def live_threads(env: dict | None = None, runner=None, cwd: str | None = None) -> list[dict] | None:
    """Live top-level threads (optionally in one cwd), newest first; None when liveness cannot be read."""
    held = held_lock_ids(env, runner)
    if held is None:
        return None
    rows = [r for r in thread_rows(sorted(held), env=env) if not is_subagent(r) and not r.get("archived")]
    if cwd:
        rows = [r for r in rows if r.get("cwd") == cwd]
    for r in rows:
        r["live"] = True
    return sorted(rows, key=lambda r: -(r.get("updated_at") or 0))


def codex_binary(env: dict | None = None, which=None) -> str | None:
    env = os.environ if env is None else env
    explicit = env.get("CODEX_CLI_PATH")
    candidates = ([explicit] if explicit else []) + list(BUNDLE_PATHS)
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return (which or shutil.which)("codex")


def queue_command(thread_id: str, message: str, env: dict | None = None, which=None) -> list[str] | None:
    binary = codex_binary(env, which)
    return [binary, "queue", "--thread", thread_id, "--message", message] if binary else None


def queue_hint(thread_id: str, message: str = "<thread id と書いた中身を 1 行>", env: dict | None = None, which=None) -> str:
    cmd = queue_command(thread_id, message, env, which)
    if cmd is None:
        return f"codex queue --thread {thread_id} --message '<1 行>' (codex CLI がこの機械に見つからない)"
    return " ".join(shlex.quote(c) for c in cmd[:-1]) + " " + shlex.quote(message)


def describe(row: dict) -> str:
    title = " ".join(str(row.get("name") or row.get("title") or "").split())[:60]
    model = row.get("model") or "model ?"
    effort = f" {row['reasoning_effort']}" if row.get("reasoning_effort") else ""
    return f"{str(row.get('id'))[:8]} / {model}{effort} / {row.get('cwd') or '?'}" + (f" 「{title}」" if title else "")


def _selftest() -> int:
    import tempfile
    checks = []
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        locks = home / "thread-writer-locks"
        locks.mkdir()
        a, b, c = ("01a00000-0000-7000-8000-00000000000a", "01a00000-0000-7000-8000-00000000000b",
                   "01b00000-0000-7000-8000-00000000000c")
        for t in (a, b, c):
            (locks / f"{t}.lock").write_text("")
        (locks / ".coordination.lock").write_text("")
        db = sqlite3.connect(home / "state_5.sqlite")
        db.execute("CREATE TABLE threads (id TEXT, cwd TEXT, title TEXT, model TEXT, reasoning_effort TEXT, source TEXT,"
                   " updated_at INTEGER, archived INTEGER, unknown_extra TEXT)")
        db.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)", [
            (a, "/w/p", "first", "m-1", "low", "vscode", 2, 0, ""),
            (b, "/w/q", "guardian", "m-2", None, '{"subagent":{"other":"guardian"}}', 3, 0, ""),
            (c, "/w/p", "second", "m-1", "high", "exec", 1, 0, ""),
        ])
        db.commit(); db.close()
        env = {"HOME": td, "CODEX_HOME": td}
        held = lambda _d: f"p1\nf3\nn{locks}/{a}.lock\nn{locks}/.coordination.lock\np2\nn{locks}/{b}.lock\n"
        checks.append(("held locks parse ids, skip the coordination lock", held_lock_ids(env, held) == {a, b}))
        live = live_threads(env, held)
        checks.append(("live = held lock, sub-agent threads left out", [r["id"] for r in live] == [a]))
        checks.append(("cwd filter", live_threads(env, held, cwd="/w/q") == []))
        checks.append(("unreadable liveness is None, not empty", live_threads(env, lambda _d: (_ for _ in ()).throw(OSError())) is None))
        checks.append(("full id resolves as given", resolve(c.upper(), env) == c))
        checks.append(("unique prefix resolves", resolve("01b00000", env) == c))
        checks.append(("ambiguous prefix does not resolve", resolve("01a00000", env) is None))
        checks.append(("non-id text does not resolve", resolve("role-x", env) is None))
        rows = thread_rows([c], env=env)
        checks.append(("schema probe keeps known columns only", rows and "unknown_extra" not in rows[0] and rows[0]["model"] == "m-1"))
        checks.append(("missing state db reads as empty", thread_rows([a], env={"HOME": td, "CODEX_HOME": str(home / "none")}) == []))
        exe = home / "codex"
        exe.write_text("#!/bin/sh\n"); exe.chmod(0o755)
        cmd = queue_command(a, "hello 'x'", {"CODEX_CLI_PATH": str(exe), "HOME": td}, which=lambda _n: None)
        checks.append(("queue command uses the explicit CLI", cmd == [str(exe), "queue", "--thread", a, "--message", "hello 'x'"]))
        hint = queue_hint(a, "hello 'x'", {"CODEX_CLI_PATH": str(exe), "HOME": td}, which=lambda _n: None)
        checks.append(("hint is shell-quoted", shlex.split(hint)[-1] == "hello 'x'"))
        no_cli = queue_hint(a, env={"CODEX_CLI_PATH": str(home / "absent"), "HOME": td}, which=lambda _n: None)
        checks.append(("missing CLI is said, not hidden", "見つからない" in no_cli or os.path.isfile(BUNDLE_PATHS[0])))
        checks.append(("describe names model, effort and cwd", describe(live[0]).startswith(a[:8] + " / m-1 low / /w/p")))
    for name, ok in checks:
        print(("PASS: " if ok else "FAIL: ") + name)
    return 0 if all(ok for _, ok in checks) else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="live top-level threads only")
    ap.add_argument("--resolve", help="full thread id from an id or a unique prefix")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.resolve:
        tid = resolve(a.resolve)
        print(tid or "")
        return 0 if tid else 1
    rows = live_threads()
    if rows is None:
        print("Codex の thread が生きているかは読めない (lsof が無いか失敗)", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"🤖 {describe(r)}\n     知らせる = {queue_hint(r['id'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
