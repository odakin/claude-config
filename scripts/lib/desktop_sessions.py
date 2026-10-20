#!/usr/bin/env python3
"""desktop_sessions.py — the Claude desktop app's own record of a Code session: the model and effort it will run the next turn on, its title and the session that started it.

Why: a session started with the desktop app's `start_session` has no assistant turn yet when the call returns, so its
transcript cannot say its model (scripts/lib/session_model.py reads the transcript). The app's record already holds
the model and effort the app started it with, and it is where `set_session_model` / `set_session_effort` land. Measured:
`start_session` ignores a `model` above the caller's own family and an `effort` it does not take, without an error,
and the record shows what the session really got (conventions/multi-session-coordination.md#desktop-start-model-cap).

Where (measured on a desktop install): ~/Library/Application Support/Claude/claude-code-sessions/<account uuid>/
<environment uuid>/local_<uuid>.json — fields sessionId (`local_…`), cliSessionId (the transcript id), model, effort,
title, spawnedFrom.sessionId (the parent's `local_…`), isArchived, createdAt / lastActivityAt (epoch ms).
Read-only, never raises. Env override (tests): CLAUDE_DESKTOP_SESSIONS_DIR (the claude-code-sessions dir).
"""
from __future__ import annotations

import glob
import json
import os
import re
import time

LOCAL_RE = re.compile(r"local_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RECENT_DAYS = 3  # a transcript-id lookup reads only records touched this recently (the store holds every session ever)


def root() -> str:
    return os.environ.get("CLAUDE_DESKTOP_SESSIONS_DIR") or os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code-sessions")


def _norm(d: dict, path: str) -> dict:
    sf = d.get("spawnedFrom") if isinstance(d.get("spawnedFrom"), dict) else {}
    return {"local_id": str(d.get("sessionId") or ""), "cli_id": str(d.get("cliSessionId") or ""),
            "model": str(d.get("model") or ""), "effort": str(d.get("effort") or ""),
            "title": str(d.get("title") or ""), "parent": str(sf.get("sessionId") or ""),
            "archived": bool(d.get("isArchived")), "created_ms": d.get("createdAt") or 0,
            "last_activity_ms": d.get("lastActivityAt") or 0, "path": path}


def _load(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return _norm(d, path) if isinstance(d, dict) else None


def find(session_id: str) -> dict | None:
    """The app's record for a `local_…` id, or for a transcript id (full, or a prefix of 8+ characters); else None."""
    try:
        sid = (session_id or "").strip()
        if not sid:
            return None
        base = root()
        if sid.startswith("local_"):
            hits = glob.glob(os.path.join(base, "*", "*", sid + ".json"))
            return _load(max(hits, key=os.path.getmtime)) if hits else None
        if len(sid) < 8 or not re.fullmatch(r"[0-9a-f-]+", sid):
            return None
        cutoff = time.time() - RECENT_DAYS * 86400
        paths = [p for p in glob.glob(os.path.join(base, "*", "*", "local_*.json")) if os.path.getmtime(p) >= cutoff]
        for p in sorted(paths, key=os.path.getmtime, reverse=True):
            try:
                with open(p, encoding="utf-8") as fh:
                    raw = fh.read()
            except OSError:
                continue
            if sid not in raw:
                continue
            rec = _load(p)
            if rec and rec["cli_id"].startswith(sid):
                return rec
        return None
    except Exception:
        return None


def wait_for(local_id: str, seconds: float = 3.0, step: float = 0.25) -> dict | None:
    """find() with a short wait: the record appears as start_session returns, sometimes a moment after."""
    end = time.time() + seconds
    while True:
        rec = find(local_id)
        if rec or time.time() >= end:
            return rec
        time.sleep(step)


def selftest() -> int:
    import tempfile

    fails = []

    def check(label: str, ok: bool) -> None:
        print(("ok: " if ok else "NG: ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_DESKTOP_SESSIONS_DIR"] = td
        d = os.path.join(td, "acct", "env")
        os.makedirs(d)
        lid = "local_0123abcd-0000-4000-8000-000000000001"
        with open(os.path.join(d, lid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"sessionId": lid, "cliSessionId": "deadbeef-1111-4222-8333-444455556666",
                       "model": "claude-opus-5-5", "effort": "xhigh", "title": "worker A",
                       "spawnedFrom": {"sessionId": "local_parent"}, "isArchived": False}, fh)
        r = find(lid)
        check("local id → model / effort / parent", bool(r) and r["model"] == "claude-opus-5-5"
              and r["effort"] == "xhigh" and r["parent"] == "local_parent")
        r = find("deadbeef")
        check("transcript id prefix → same record", bool(r) and r["local_id"] == lid)
        check("unknown id → None", find("local_ffffffff-0000-4000-8000-000000000009") is None and find("abc") is None)
        with open(os.path.join(d, "local_broken.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("broken record does not raise", find("local_broken") is None)
        check("LOCAL_RE finds an id in a tool result",
              LOCAL_RE.search(f"Started session \"x\" (session_id: {lid}, name: w)").group(0) == lid)
        del os.environ["CLAUDE_DESKTOP_SESSIONS_DIR"]
    print("selftest:", "PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    for a in sys.argv[1:]:
        print(json.dumps(find(a), ensure_ascii=False))
