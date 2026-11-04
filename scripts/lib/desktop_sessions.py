#!/usr/bin/env python3
"""desktop_sessions.py — the Claude desktop app's own record of a Code session: the model and effort it will run the next turn on, its title and the session that started it.

Why: a session started with the desktop app's `start_session` has no assistant turn yet when the call returns, so its
transcript cannot say its model (scripts/lib/session_model.py reads the transcript). The app's record already holds
the model and effort the app started it with, and it is where `set_session_model` / `set_session_effort` land. Measured:
`start_session` ignores a `model` above the caller's own family and an `effort` it does not take, without an error,
and the record shows what the session really got (conventions/multi-session-coordination.md#desktop-start-model-cap).

Where (measured on a desktop install): ~/Library/Application Support/Claude/claude-code-sessions/<account uuid>/
<environment uuid>/local_<uuid>.json — fields sessionId (`local_…`), cliSessionId (the transcript id), model, effort,
title, spawnedFrom.sessionId (the parent's `local_…`), lineageDetached (detached from that parent = no longer its child),
isArchived, createdAt / lastActivityAt (epoch ms).
`lineage` = the app's own reading of that parent link, copied from the app's main process (measured on app 4.16336.0;
recheck = `scripts/claude-app-bundle.py grep --where asar 'initiator:"claude"'`): a `spawnedFrom` with `sideSession`
true and no user fork is a side session Claude started (initiator "claude"); a fork, or a `spawnedFrom` without
`sideSession`, is one the user placed (initiator "user"). A session started from a proposal card the user clicked
carries `sideSession` true as well (measured), so it is a "claude" child. `detach_session` moves only "claude"
children: `"self"` from the child, or the child's id from its parent (`detachable_by_self` / `detachable_by_parent`,
= the app's own checks); the user moves a "user" child from the sidebar.
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


def lineage(d: dict) -> dict | None:
    """The app's parent link of a raw record: {parent, kind, initiator, parent_deleted}, or None (top level / detached).
    kind = side_session / hand_off / fork / suggested_task (the app's names). Mirrors the app (module docstring)."""
    if not isinstance(d, dict) or d.get("lineageDetached"):
        return None
    sid = d.get("sessionId")
    sf = d.get("spawnedFrom") if isinstance(d.get("spawnedFrom"), dict) else None
    n = sf if sf and sf.get("sessionId") and sf.get("sessionId") != sid else None
    r = d.get("forkedFromSessionId") or None
    r = None if r == sid else r
    deleted = n.get("deletedParent") if n else None
    deleted_id = deleted.get("sessionId") if isinstance(deleted, dict) else None
    if n and n.get("sideSession") and not n.get("userFork") and (r is None or r == n["sessionId"] or r == deleted_id):
        return {"parent": str(n["sessionId"]), "kind": "hand_off" if n.get("handOff") else "side_session",
                "initiator": "claude", "parent_deleted": deleted is not None}
    if r is not None:
        return {"parent": str(r), "kind": "fork", "initiator": "user", "parent_deleted": False}
    if n:
        return {"parent": str(n["sessionId"]), "kind": "suggested_task", "initiator": "user",
                "parent_deleted": deleted is not None}
    return None


def detachable_by_self(rec: dict | None) -> bool:
    """`detach_session("self")` in this session would move it to top level (the app refuses a "user" child)."""
    lin = (rec or {}).get("lineage")
    return bool(lin) and lin["initiator"] == "claude"


def detachable_by_parent(rec: dict | None, parent_local: str) -> bool:
    """`detach_session(<this session's local id>)` in `parent_local` would move it (the app's isChildSessionOf:
    a "claude" child of that parent whose parent was not deleted)."""
    lin = (rec or {}).get("lineage")
    return (bool(lin) and bool(parent_local) and lin["parent"] == parent_local and lin["initiator"] == "claude"
            and not lin["parent_deleted"])


def _norm(d: dict, path: str) -> dict:
    sf = d.get("spawnedFrom") if isinstance(d.get("spawnedFrom"), dict) else {}
    return {"local_id": str(d.get("sessionId") or ""), "cli_id": str(d.get("cliSessionId") or ""),
            "model": str(d.get("model") or ""), "effort": str(d.get("effort") or ""),
            "title": str(d.get("title") or ""), "parent": str(sf.get("sessionId") or ""),
            "archived": bool(d.get("isArchived")), "detached": bool(d.get("lineageDetached")),
            "lineage": lineage(d),
            "created_ms": d.get("createdAt") or 0,
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
              and r["effort"] == "xhigh" and r["parent"] == "local_parent" and r["detached"] is False)
        did = "local_0123abcd-0000-4000-8000-000000000002"
        with open(os.path.join(d, did + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"sessionId": did, "cliSessionId": "cafef00d-2222-4222-8333-444455556666",
                       "spawnedFrom": {"sessionId": "local_parent"}, "lineageDetached": True}, fh)
        check("a record detached from its parent → detached (still names the parent)",
              find(did)["detached"] is True and find(did)["parent"] == "local_parent")
        check("detached → no lineage, neither side can detach it",
              find(did)["lineage"] is None and not detachable_by_self(find(did))
              and not detachable_by_parent(find(did), "local_parent"))
        check("spawnedFrom without sideSession → a child the user placed (suggested_task): no detach_session",
              find(lid)["lineage"]["initiator"] == "user" and not detachable_by_self(find(lid))
              and not detachable_by_parent(find(lid), "local_parent"))
        # the shape of a session started from a proposal card the user clicked (measured record, ids made up)
        cid = "local_0123abcd-0000-4000-8000-000000000003"
        with open(os.path.join(d, cid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"sessionId": cid, "cliSessionId": "0badc0de-3333-4222-8333-444455556666",
                       "spawnedFrom": {"sessionId": "local_parent", "taskId": "task_0000abcd", "sideSession": True,
                                       "sharedFolder": True, "name": "w"}}, fh)
        r = find(cid)
        check("card-started side session → a claude child: self and its parent can detach it, another session cannot",
              r["lineage"] == {"parent": "local_parent", "kind": "side_session", "initiator": "claude",
                               "parent_deleted": False}
              and detachable_by_self(r) and detachable_by_parent(r, "local_parent")
              and not detachable_by_parent(r, "local_other") and not detachable_by_parent(r, ""))
        check("hand-off and user fork follow the app",
              lineage({"sessionId": "a", "spawnedFrom": {"sessionId": "p", "sideSession": True, "handOff": True}})["kind"]
              == "hand_off"
              and lineage({"sessionId": "a", "spawnedFrom": {"sessionId": "p", "sideSession": True, "userFork": True},
                           "forkedFromSessionId": "p"})["initiator"] == "user"
              and lineage({"sessionId": "a", "forkedFromSessionId": "q"})["kind"] == "fork"
              and lineage({"sessionId": "a"}) is None and lineage({"sessionId": "a", "spawnedFrom": {"sessionId": "a"}}) is None)
        r = lineage({"sessionId": "a", "spawnedFrom": {"sessionId": "p", "sideSession": True,
                                                      "deletedParent": {"sessionId": "p0"}}})
        check("a deleted parent: self can still detach, the parent link cannot",
              r["initiator"] == "claude" and r["parent_deleted"] is True
              and not detachable_by_parent({"lineage": r}, "p") and detachable_by_self({"lineage": r}))
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
