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

Every config dir on the machine is read (`~/.claude`, `$CLAUDE_CONFIG_DIR`, `~/.claude-*` = lib/claude_config_dirs.py):
a session started with another config dir (an account-pinned Remote Control server = a session started from a phone,
a headless job) registers and writes its transcript there, and is live all the same. Each live row carries the
config dir's label and the session's socket address (`uds:<path>`), which SendMessage accepts as `to` across config
dirs and accounts on this machine (conventions/multi-account-machine-surface.md#peer-discovery-across-config-dirs).

Env overrides (tests, fixtures): CLAUDE_SESSIONS_DIR, CLAUDE_PROJECTS_DIR (one dir each; replaces the scan).

Convention: conventions/multi-session-coordination.md#delegate-model-routing (read the actual model before
sending work to a session).
"""
from __future__ import annotations

import glob
import json
import os
import re

try:  # sibling module; this file is also loaded by path (spec_from_file_location) without lib/ on sys.path
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "claude_config_dirs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_config_dirs.py"))
    _ccd = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_ccd)
except Exception:  # pragma: no cover - an old checkout without the module: the default dir only
    _ccd = None

TAIL_BYTES = 256 * 1024
_UUID_RE = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_ID_RE = re.compile(r"^[0-9a-f-]{4,36}$")
# model id substring → tier (ordered: the first match wins)
TIERS = (("mythos", "fable"), ("fable", "fable"), ("opus", "opus"), ("sonnet", "sonnet"), ("haiku", "haiku"))


def sessions_dirs() -> list[str]:
    """Every live-session registry dir on this machine (one per config dir)."""
    if _ccd is not None:
        return _ccd.sessions_dirs()
    return [os.environ.get("CLAUDE_SESSIONS_DIR") or os.path.expanduser("~/.claude/sessions")]


def sessions_dir() -> str:
    """The first registry dir (kept for older callers; new code reads sessions_dirs())."""
    dirs = sessions_dirs()
    return dirs[0] if dirs else os.path.expanduser("~/.claude/sessions")


def projects_dirs() -> list[str]:
    if _ccd is not None:
        return _ccd.projects_dirs()
    override = os.environ.get("CLAUDE_PROJECTS_DIR")
    if override:
        return [override]
    return [os.path.expanduser("~/.claude/projects")] + sorted(glob.glob(os.path.expanduser("~/.claude-*/projects")))


def _config_label(path: str) -> str:
    return _ccd.label_of(path) if _ccd is not None else ""


def _address(entry: dict) -> str:
    if _ccd is not None:
        return _ccd.socket_address(entry)
    sock = entry.get("messagingSocketPath")
    return f"uds:{sock}" if isinstance(sock, str) and sock.endswith(".sock") else ""


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
    """Sessions whose process is alive, from every config dir's registry: sessionId / name / host / cwd / status /
    pid / config (the config dir's label, '' when unknown) / address (`uds:<socket>`, '' when the registry has none)."""
    out = []
    seen: set[str] = set()
    for sdir in sessions_dirs():
        for f in glob.glob(os.path.join(sdir, "*.json")):
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
            if d["sessionId"] in seen:
                continue
            seen.add(d["sessionId"])
            out.append({"sessionId": d["sessionId"], "name": str(d.get("name") or ""),
                        "host": str(d.get("hostSessionId") or ""), "cwd": str(d.get("cwd") or ""),
                        "status": str(d.get("status") or ""), "pid": pid,
                        "config": _config_label(sdir), "address": _address(d)})
    out.sort(key=lambda s: s["sessionId"])
    return out


def live_address(session_id: str) -> dict | None:
    """The one live session with this id (exact, or a prefix of 8+ characters), with its `address`; else None.
    Never raises."""
    try:
        sid = (session_id or "").strip()
        if len(sid) < 8:
            return None
        hits = [s for s in live_sessions() if s["sessionId"] == sid or s["sessionId"].startswith(sid)]
        return hits[0] if len(hits) == 1 else None
    except Exception:
        return None


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


def _app_record(s: dict) -> dict | None:
    """The desktop app's record (model / effort the next turn runs on), for a session the app started; else None."""
    try:
        _spec2 = _ilu.spec_from_file_location(
            "desktop_sessions", os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop_sessions.py"))
        ds = _ilu.module_from_spec(_spec2)
        _spec2.loader.exec_module(ds)
        host = s.get("host") or ""
        return ds.find(host) if host.startswith("local_") else ds.find(s["sessionId"])
    except Exception:
        return None


def describe(s: dict) -> dict:
    """Add path / model / model_at / tier / tail to a session row (empty strings when unknown), and for a desktop
    session app_model / app_effort = the app's record, which is what the next turn runs on (a session that has not
    answered yet has no model in its transcript; set_session_model lands in the record first)."""
    path = s.get("path") or transcript_path(s["sessionId"], s.get("cwd") or None)
    info = last_model(path) if path else None
    rec = _app_record(s)
    return {**s, "path": path or "", "model": info["model"] if info else "", "model_at": info["at"] if info else "",
            "tier": tier(info["model"]) if info else "", "tail": bool(info and info.get("tail")),
            "app_model": (rec or {}).get("model", ""), "app_effort": (rec or {}).get("effort", "")}


def model_of(session_id: str, cwd: str | None = None) -> str:
    """Convenience for callers that only want the model id ('' when unknown). Never raises."""
    try:
        p = transcript_path(session_id, cwd)
        info = last_model(p) if p else None
        return info["model"] if info else ""
    except Exception:
        return ""


def _last_tool_use(path: str) -> tuple[str, str]:
    """(timestamp, input as JSON text) of the last tool_use in a transcript's tail, ('', '') when none."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()
            raw = fh.read()
    except OSError:
        return "", ""
    best = ("", "")
    for line in raw.split(b"\n"):
        if b"tool_use" not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("type") != "assistant":
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                best = (str(e.get("timestamp") or ""), json.dumps(b.get("input"), ensure_ascii=False))
    return best


def acting_transcript(session_id: str, needles: list[str], max_age_s: float = 900) -> dict | None:
    """The transcript that is running a command right now: the session's own, or one of its subagents' (Agent tool).

    A subagent shares its parent's session id and environment (measured: no variable of its own), so a command it runs
    names the parent. Its turns are written to `<parent transcript dir>/<parent id>/subagents/agent-<id>.jsonl`, and the
    tool call being executed is that file's last tool_use. Among the parent and its recently written subagents, the one
    whose last tool_use contains every needle (e.g. the request id and the subcommand) is the actor. Returns
    {"path", "model", "subagent": bool} or None (no match = the caller falls back to the session's own model).
    """
    try:
        import time as _time
        p = transcript_path(session_id)
        if not p:
            return None
        cands = [p] + [q for q in glob.glob(os.path.join(p[:-len(".jsonl")], "subagents", "agent-*.jsonl"))
                       if _time.time() - os.path.getmtime(q) <= max_age_s]
        hits = []
        for c in cands:
            ts, text = _last_tool_use(c)
            if text and all(n in text for n in needles):
                hits.append((ts, c))
        if not hits:
            return None
        ts, c = max(hits)
        info = last_model(c)
        return {"path": c, "model": info["model"] if info else "", "subagent": c != p}
    except Exception:
        return None
