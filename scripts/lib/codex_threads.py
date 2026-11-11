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
its row exists it is a sub-agent (is_subagent), so such a thread is never anyone's peer. A thread that has run a turn has
a rollout file from that turn's first event, so unstarted_lock_ids() names a held lock with neither a row nor a rollout
(`sessions/` or `archived_sessions/`, any suffix) as a thread that never ran; a rollout without a row, or anything it
cannot read, stays unknown.

Metadata comes from Codex's local state database, found through the same resolver the provenance hook uses
(session_provenance_cache.codex_state_databases) and opened read-only. Measured: the database is in WAL mode, and when
every Codex connection has closed it, its -wal/-shm files are gone and a read-only connection cannot open it ("unable to
open database file") while the app is still running. Then _connect() opens it read-write without create (mode=rw) and
with query_only on: SQLite makes the -wal/-shm side files as any client would, and the connection writes no data.
(immutable=1 is not used: if Codex starts writing during the read, it would read a torn page without an error.) A sandbox
that cannot write CODEX_HOME (Codex's workspace-write) cannot make those side files, so there a closed database should
read as unknown rather than as rows (not measured).

Both are undocumented local layout: every reader fails open, so a changed layout reads as "unknown", never as an error
and never as "not live". thread_rows() returns [] both for absent rows and for an unreadable database; live_threads()
returns None when locks are held but the database cannot be opened, and unstarted_lock_ids() returns None when the locks,
the database or the rollout directories cannot be read. Writes no data (the side files above are SQLite's own).
Convention: conventions/multi-account-machine-surface.md#codex-peers.

CLI: codex_threads.py [--live] [--json] | --resolve <id-or-prefix> | --unstarted | --selftest
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


def _open_state(database: Path, timeout: float):
    """(connection, columns) on one state database, or None. Read-only first; a closed WAL database (no -wal/-shm)
    refuses read-only, so then read-write without create and query_only on (module docstring)."""
    for mode in ("ro", "rw"):
        con = None
        try:
            con = sqlite3.connect(database.resolve().as_uri() + f"?mode={mode}", uri=True, timeout=timeout)
            con.execute("PRAGMA query_only = ON")
            cols = {str(r[1]) for r in con.execute("PRAGMA table_info(threads)")}
        except (OSError, sqlite3.Error):
            if con is not None:
                con.close()
            continue
        if "id" in cols:
            return con, [c for c in COLUMNS if c in cols]
        con.close()
        return None  # opened, but no threads table: the other mode reads the same schema
    return None


def _connect(env: dict | None, timeout: float = 0.2):
    if codex_state_databases is None:
        return None
    for database in codex_state_databases(dict(os.environ if env is None else env)):
        got = _open_state(database, timeout)
        if got is not None:
            return got
    return None


def _query_rows(ids=None, prefix: str | None = None, env: dict | None = None) -> list[dict] | None:
    """Rows for the given ids, or for ids starting with `prefix`; None when no state database can be read."""
    got = _connect(env)
    if got is None:
        return None
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
        return None
    finally:
        con.close()


def thread_rows(ids=None, prefix: str | None = None, env: dict | None = None) -> list[dict]:
    """Rows of the threads table for the given ids, or for ids starting with `prefix`. [] when unreadable."""
    return _query_rows(ids, prefix, env) or []


def rollout_ids(env: dict | None = None) -> set[str] | None:
    """Thread ids named by a file under `<CODEX_HOME>/sessions/` or `archived_sessions/` (any suffix, `.zst` included).
    None when `sessions/` is missing or a directory cannot be walked, so an unread rollout is never read as absent."""
    home = codex_home(env)
    if not (home / "sessions").is_dir():
        return None
    failed = []
    ids = set()
    for sub in ("sessions", "archived_sessions"):
        root = home / sub
        if not root.exists():
            continue  # nothing archived yet
        for _dir, _dirs, files in os.walk(root, onerror=failed.append):
            for name in files:
                ids.update(THREAD_ID.findall(name.lower()))
    return None if failed else ids


def unstarted_lock_ids(ids=None, env: dict | None = None, runner=None) -> set[str] | None:
    """Held-lock ids (or the given ids) with neither a threads row nor a rollout file: threads that never ran a turn,
    such as a guardian not yet asked to review. None when the locks, the state database or the rollouts cannot be read.
    Rows are read before rollouts, so a thread whose first turn starts between the two reads has a rollout by then and
    stays out of this set (unknown), never in it."""
    held = set(ids) if ids is not None else held_lock_ids(env, runner)
    if held is None:
        return None
    if not held:
        return set()
    rows = _query_rows(sorted(held), env=env)
    if rows is None:
        return None
    rolled = rollout_ids(env)
    if rolled is None:
        return None
    return held - {r["id"] for r in rows} - rolled


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
    """Live top-level threads (optionally in one cwd), newest first; None when liveness cannot be read (no lock
    reading, or locks held while the state database cannot be opened)."""
    held = held_lock_ids(env, runner)
    if held is None:
        return None
    if not held:
        return []
    found = _query_rows(sorted(held), env=env)
    if found is None:
        return None
    rows = [r for r in found if not is_subagent(r) and not r.get("archived")]
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

        # Lock-only threads: d = no row, no rollout (never ran); e = rollout but no row; f = archived .zst rollout only
        d, e, f = ("01c00000-0000-7000-8000-00000000000d", "01c00000-0000-7000-8000-00000000000e",
                   "01c00000-0000-7000-8000-00000000000f")
        day = home / "sessions" / "2026" / "01" / "02"
        day.mkdir(parents=True)
        (day / f"rollout-2026-01-02T03-04-05-{e}.jsonl").write_text("{}\n")
        (home / "archived_sessions").mkdir()
        (home / "archived_sessions" / f"rollout-2026-01-02T03-04-06-{f}.jsonl.zst").write_bytes(b"")
        held4 = lambda _d: "p1\n" + "".join(f"n{locks}/{t}.lock\n" for t in (a, d, e, f))
        unstarted = unstarted_lock_ids(env=env, runner=held4)
        checks.append(("held lock with neither row nor rollout = never ran", unstarted == {d}))
        checks.append(("rollout without a row stays unknown, not never-ran", unstarted is not None and e not in unstarted))
        checks.append(("archived .zst rollout counts as having run", unstarted is not None and f not in unstarted))
        checks.append(("given ids are checked as given", unstarted_lock_ids([a, d], env=env) == {d}))
        checks.append(("no held lock = empty, not unknown", unstarted_lock_ids(env=env, runner=lambda _d: "") == set()))
        checks.append(("unreadable locks = None", unstarted_lock_ids(env=env, runner=lambda _d: (_ for _ in ()).throw(OSError())) is None))
        if os.geteuid() != 0:
            blocked = home / "archived_sessions" / "blocked"
            blocked.mkdir()
            blocked.chmod(0)
            try:
                checks.append(("a rollout directory that cannot be walked = None", unstarted_lock_ids([d], env=env) is None))
            finally:
                blocked.chmod(0o755)
        no_sessions = home / "no-sessions"
        no_sessions.mkdir()
        shutil.copy(home / "state_5.sqlite", no_sessions / "state_5.sqlite")
        env2 = {"HOME": td, "CODEX_HOME": str(no_sessions)}
        checks.append(("no sessions/ directory = None", unstarted_lock_ids([d], env=env2) is None))
        broken = home / "broken"
        (broken / "sessions").mkdir(parents=True)
        (broken / "thread-writer-locks").mkdir()
        (broken / "state_5.sqlite").write_bytes(b"not a database" * 64)
        env3 = {"HOME": td, "CODEX_HOME": str(broken)}
        held_broken = lambda _d: f"p1\nn{broken}/thread-writer-locks/{a}.lock\n"
        checks.append(("unreadable state db = None for never-ran", unstarted_lock_ids([d], env=env3) is None))
        checks.append(("unreadable state db with held locks: live is None, not empty", live_threads(env3, held_broken) is None))
        checks.append(("unreadable state db: thread_rows keeps its [] contract", thread_rows([a], env=env3) == []))

        # A closed WAL database (every connection gone, -wal/-shm removed) still reads, and its data is not written
        wal = home / "wal"
        (wal / "thread-writer-locks").mkdir(parents=True)
        w = sqlite3.connect(wal / "state_5.sqlite")
        w.execute("PRAGMA journal_mode = WAL")
        w.execute("CREATE TABLE threads (id TEXT, cwd TEXT, source TEXT, updated_at INTEGER, archived INTEGER)")
        w.execute("INSERT INTO threads VALUES (?,?,?,?,?)", (a, "/w/p", "vscode", 2, 0))
        w.commit()
        w.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        w.close()
        # macOS's SQLite keeps the side files on close (persistent WAL); Codex's own SQLite removes them. Remove them
        # here after the full checkpoint, as Codex leaves the database.
        for p in wal.iterdir():
            if p.name.startswith("state_5.sqlite-"):
                p.unlink()
        before = (wal / "state_5.sqlite").read_bytes()
        try:
            probe = sqlite3.connect((wal / "state_5.sqlite").as_uri() + "?mode=ro", uri=True)
            try:
                probe.execute("SELECT count(*) FROM threads").fetchone()
                ro_refused = False
            finally:
                probe.close()
        except sqlite3.Error:
            ro_refused = True
        env4 = {"HOME": td, "CODEX_HOME": str(wal)}
        held_wal = lambda _d: f"p1\nn{wal}/thread-writer-locks/{a}.lock\n"
        if ro_refused:
            checks.append(("closed WAL database: read-only alone refuses it (the case the fallback serves)", True))
        else:
            print(f"INFO: SQLite {sqlite3.sqlite_version} opened the closed WAL database read-only; fallback not exercised")
        checks.append(("closed WAL database: rows still read", [r["id"] for r in thread_rows([a], env=env4)] == [a]))
        checks.append(("closed WAL database: live threads still read", [r["id"] for r in live_threads(env4, held_wal) or []] == [a]))
        checks.append(("closed WAL database: the database file is not written", (wal / "state_5.sqlite").read_bytes() == before))
        checks.append(("read-write fallback does not create a missing database",
                       _open_state(wal / "absent.sqlite", 0.2) is None and not (wal / "absent.sqlite").exists()))
    for name, ok in checks:
        print(("PASS: " if ok else "FAIL: ") + name)
    return 0 if all(ok for _, ok in checks) else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="live top-level threads only")
    ap.add_argument("--resolve", help="full thread id from an id or a unique prefix")
    ap.add_argument("--unstarted", action="store_true", help="held-lock ids that never ran a turn (no row, no rollout)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.resolve:
        tid = resolve(a.resolve)
        print(tid or "")
        return 0 if tid else 1
    if a.unstarted:
        ids = unstarted_lock_ids()
        if ids is None:
            print("一度も動いていない thread かは読めない (lsof・状態 DB・rollout の dir のどれかが読めない)", file=sys.stderr)
            return 3
        print(json.dumps(sorted(ids)) if a.json else "\n".join(sorted(ids)))
        return 0
    rows = live_threads()
    if rows is None:
        print("Codex の thread が生きているかは読めない (lsof が無いか失敗、 または lock があるのに状態 DB が開けない)",
              file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"🤖 {describe(r)}\n     知らせる = {queue_hint(r['id'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
