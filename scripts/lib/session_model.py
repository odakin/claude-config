#!/usr/bin/env python3
"""session_model.py — a Claude Code session's actual model, read from its transcript (never from a title or a tag).

Why: the model a session runs on is not written where a sender looks. A chip title's `[model: …]` tag is a
recommendation the launcher may not follow; the desktop model picker is app-wide and can change mid-session;
`ListAgents` and the sessions registry show names, not models. The only record is the transcript: every
assistant turn carries `message.model`, so the last assistant turn's model is "the model this session runs on
now" (measured: sessions whose first and last turns differ exist, so the first turn is not enough).

Where the facts live (Claude Code, measured on a desktop install):
  ~/.claude/sessions/<pid>.json          live registry: sessionId, name (= what ListAgents shows), hostSessionId
                                         (`local_…`, the `from-session` of cross-session messages), cwd, status.
                                         No model field.
  ~/.claude/projects/<cwd>/<sessionId>.jsonl   transcript; `<synthetic>` is not a model and is skipped.

Reading: transcripts reach tens of MB, so read the tail (TAIL_BYTES) first and fall back to a full scan only
when the tail holds no assistant turn. Everything here is read-only and never raises on a broken file.

Env overrides (tests, other config dirs): CLAUDE_SESSIONS_DIR, CLAUDE_PROJECTS_DIR (one dir; the default also
scans ~/.claude-*/projects for headless config dirs).

Convention: conventions/multi-session-coordination.md#delegate-model-routing (read the actual model before
sending work to a session).
"""
from __future__ import annotations

import glob
import json
import os
import re

TAIL_BYTES = 256 * 1024
_UUID_RE = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_ID_RE = re.compile(r"^[0-9a-f-]{4,36}$")
# model id substring → tier (ordered: the first match wins)
TIERS = (("mythos", "fable"), ("fable", "fable"), ("opus", "opus"), ("sonnet", "sonnet"), ("haiku", "haiku"))


def sessions_dir() -> str:
    return os.environ.get("CLAUDE_SESSIONS_DIR") or os.path.expanduser("~/.claude/sessions")


def projects_dirs() -> list[str]:
    override = os.environ.get("CLAUDE_PROJECTS_DIR")
    if override:
        return [override]
    return [os.path.expanduser("~/.claude/projects")] + sorted(glob.glob(os.path.expanduser("~/.claude-*/projects")))


def tier(model: str) -> str:
    """'fable' / 'opus' / 'sonnet' / 'haiku' / 'unknown' ('' for an empty model)."""
    m = (model or "").lower()
    if not m:
        return ""
    for key, t in TIERS:
        if key in m:
            return t
    return "unknown"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except Exception:
        return True
    return True


def transcript_path(session_id: str, cwd: str | None = None) -> str | None:
    for root in projects_dirs():
        if cwd:
            p = os.path.join(root, cwd.replace("/", "-"), f"{session_id}.jsonl")
            if os.path.isfile(p):
                return p
        hits = glob.glob(os.path.join(root, "*", f"{session_id}.jsonl"))
        if hits:
            return max(hits, key=os.path.getmtime)
    return None


def _scan(chunk: bytes) -> dict | None:
    last = None
    for raw in chunk.split(b"\n"):
        if b"assistant" not in raw or b'"model"' not in raw:  # cheap prefilter; the harness writes compact JSON
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("type") != "assistant":
            continue
        m = (e.get("message") or {}).get("model")
        if isinstance(m, str) and m and not m.startswith("<"):
            last = {"model": m, "at": str(e.get("timestamp", ""))}
    return last


def last_model(path: str) -> dict | None:
    """{"model", "at", "tail": bool} of the last assistant turn, or None (no assistant turn, or unreadable).

    tail=True means the tail read was enough (the usual case); False means a full scan was needed.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()  # drop the line cut by the seek
                hit = _scan(fh.read())
                if hit:
                    hit["tail"] = True
                    return hit
                fh.seek(0)
            hit = _scan(fh.read())
    except OSError:
        return None
    if hit:
        hit["tail"] = False
    return hit


def live_sessions() -> list[dict]:
    """Sessions whose process is alive, from the registry: sessionId / name / host / cwd / status / pid."""
    out = []
    for f in glob.glob(os.path.join(sessions_dir(), "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not isinstance(d.get("sessionId"), str) or not d["sessionId"]:
            continue
        pid = d.get("pid")
        if isinstance(pid, int) and not _pid_alive(pid):
            continue
        out.append({"sessionId": d["sessionId"], "name": str(d.get("name") or ""), "host": str(d.get("hostSessionId") or ""),
                    "cwd": str(d.get("cwd") or ""), "status": str(d.get("status") or ""), "pid": pid})
    out.sort(key=lambda s: s["sessionId"])
    return out


def resolve(target: str) -> list[dict]:
    """Sessions matching target: a session id or its prefix, a `local_…` host id, or a substring of the name.

    A session id that is not live is still resolved through its transcript (status "(not live)").
    """
    t = (target or "").strip()
    if not t:
        return []
    live = live_sessions()
    if t.startswith("local_"):
        return [s for s in live if s["host"] == t]
    if _ID_RE.fullmatch(t):
        hits = [s for s in live if s["sessionId"].startswith(t)]
        if hits:
            return hits
        seen: set[str] = set()
        for root in projects_dirs():
            for p in glob.glob(os.path.join(root, "*", f"{t}*.jsonl")):
                sid = os.path.basename(p)[:-len(".jsonl")]
                if _UUID_RE.match(sid) and sid not in seen:
                    seen.add(sid)
                    hits.append({"sessionId": sid, "name": "", "host": "", "cwd": "", "status": "(not live)",
                                 "pid": None, "path": p})
        return hits
    return [s for s in live if t in s["name"]]


def describe(s: dict) -> dict:
    """Add path / model / model_at / tier / tail to a session row (empty strings when unknown)."""
    path = s.get("path") or transcript_path(s["sessionId"], s.get("cwd") or None)
    info = last_model(path) if path else None
    return {**s, "path": path or "", "model": info["model"] if info else "", "model_at": info["at"] if info else "",
            "tier": tier(info["model"]) if info else "", "tail": bool(info and info.get("tail"))}


def model_of(session_id: str, cwd: str | None = None) -> str:
    """Convenience for callers that only want the model id ('' when unknown). Never raises."""
    try:
        p = transcript_path(session_id, cwd)
        info = last_model(p) if p else None
        return info["model"] if info else ""
    except Exception:
        return ""
