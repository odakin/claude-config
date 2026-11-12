#!/usr/bin/env python3
"""owner_turn.py — what the owner typed in a Claude Code session, and which of it is the owner's latest input.

Why: a gate that lets an expensive choice through on "the owner's words" has to know that the words are the owner's
and that they were said for the work now being started. Measured: a requester attached the owner's words for an
earlier request to a later one, and the gate checked only that some words were attached. Words from before the
owner's latest input belong to an earlier request; the requester asks again instead of reusing them.

The owner's prompts = what the person typed: no tool results, meta lines, compact summaries, other sessions'
messages, task notifications, hook feedback, skill bodies or harness prompts; a prompt typed while a turn ran (a
`queued_command` attachment from a human) counts. Every reader of "the owner's last prompts" uses this one filter
(session-launch-check.py's owner_prompts delegates here).

The owner's latest input = the owner's last typed prompt that started a turn, plus the prompts the owner typed
after it while turns ran (queued). A turn started by another session's message or a task notification is not a
new input of the owner's: the owner's latest input is still the last one the person typed.

API (read-only, never raises on a broken or missing file):
  owner_entries(path)            -> [{"ts", "queued", "text"}] oldest first
  latest_input(entries)          -> the tail of entries that is the owner's latest input
  find_quote(path, quote, now)   -> {"found", "in_latest", "when", "later", "minutes", "latest"}
  transcript_for(session_id)     -> the transcript path of a session id (full id or a unique prefix) or None

CLI: owner_turn.py --transcript <path> [--quote '<words>'] / --session <id> ... / --selftest
Used by: the board gate that lets a model through on the owner's words (ai-collaboration board/CONTRACT.md#launch-model-allow)
and the launch check's premium gate (session-launch-check.py).
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re
import sys

GENERATED_PROMPT = ("<command-", "<local-command", "<task-notification>", "<cross-session-message", "Another Claude session",
                    "Stop hook feedback", "Base directory for this skill", "Caveat:", "<system-reminder>", "[Request interrupted")


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _parse_ts(ts):
    try:
        return _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _text_of(e: dict) -> tuple[str, bool]:
    """(the owner's text, queued) of one transcript entry, or ("", False) when it is not the owner's prompt."""
    if not isinstance(e, dict) or e.get("isMeta") or e.get("isSidechain") or e.get("isCompactSummary"):
        return "", False
    text, queued = "", False
    if e.get("type") == "user":
        if e.get("turnOrigin") not in (None, "human") or e.get("promptSource") == "system":
            return "", False
        c = (e.get("message") or {}).get("content")
        if isinstance(c, str):
            text = c
        elif isinstance(c, list) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            text = "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    elif e.get("type") == "attachment":
        a = e.get("attachment") or {}
        if (isinstance(a, dict) and a.get("type") == "queued_command" and a.get("commandMode") == "prompt"
                and isinstance(a.get("origin"), dict) and a["origin"].get("kind") == "human"):
            p = a.get("prompt")
            text = p if isinstance(p, str) else "".join(
                b.get("text", "") for b in (p or []) if isinstance(b, dict) and b.get("type") == "text")
            queued = True
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text or "", flags=re.S).strip()
    if not text or text.startswith(GENERATED_PROMPT):
        return "", False
    return text, queued


def owner_entries(path) -> list[dict]:
    out: list[dict] = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return out
    with fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            text, queued = _text_of(e)
            if text:
                out.append({"ts": e.get("timestamp"), "queued": queued, "text": text})
    return out


def latest_input(entries: list[dict]) -> list[dict]:
    starts = [i for i, e in enumerate(entries) if not e.get("queued")]
    return entries[starts[-1]:] if starts else list(entries)


def find_quote(path, quote: str, now: _dt.datetime | None = None) -> dict:
    """Where the owner said `quote` (whitespace-normalized substring of one prompt): the last such prompt."""
    q = _norm(quote)
    entries = owner_entries(path)
    latest = latest_input(entries)
    res = {"found": False, "in_latest": False, "when": None, "later": None, "minutes": None,
           "latest": [_norm(e["text"])[:120] for e in latest]}
    if not q:
        return res
    hit = next((i for i in range(len(entries) - 1, -1, -1) if q in _norm(entries[i]["text"])), None)
    if hit is None:
        return res
    first_latest = len(entries) - len(latest)
    res.update(found=True, in_latest=hit >= first_latest, when=entries[hit]["ts"], later=len(entries) - 1 - hit)
    t = _parse_ts(entries[hit]["ts"])
    if t is not None:
        now = now or _dt.datetime.now(_dt.timezone.utc)
        res["minutes"] = max(0, int((now - t).total_seconds() // 60))
    return res


def _session_model():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("session_model", os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_model.py"))
    sm = ilu.module_from_spec(spec)
    spec.loader.exec_module(sm)
    return sm


def transcript_for(session_id: str) -> str | None:
    """A full session id, or a prefix of one that names a single transcript on this machine (every config dir)."""
    sid = (session_id or "").strip()
    if not re.fullmatch(r"[0-9a-f-]{8,36}", sid):
        return None
    try:
        sm = _session_model()
        p = sm.transcript_path(sid)
        if p:
            return p
        hits = sorted({f for root in sm.projects_dirs() for f in glob.glob(os.path.join(glob.escape(root), "*", glob.escape(sid) + "*.jsonl"))})
    except Exception:
        return None
    ids = {os.path.basename(f) for f in hits}
    return max(hits, key=os.path.getmtime) if len(ids) == 1 else None


def _selftest() -> int:
    import tempfile
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(("PASS " if ok else "FAIL ") + name)
        fails += 0 if ok else 1

    def user(ts, text, **kw):
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}, **kw}

    def queued(ts, text, kind="human"):
        return {"type": "attachment", "timestamp": ts,
                "attachment": {"type": "queued_command", "commandMode": "prompt", "origin": {"kind": kind}, "prompt": text}}

    rows = [
        user("2026-01-01T00:00:00Z", "first request: put the X job on the top model"),
        {"type": "assistant", "timestamp": "2026-01-01T00:00:05Z", "message": {"content": [{"type": "text", "text": "ok"}]}},
        {"type": "user", "timestamp": "2026-01-01T00:00:06Z", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        user("2026-01-01T00:01:00Z", "<cross-session-message from=\"x\">a peer asks</cross-session-message>"),
        user("2026-01-01T00:01:10Z", "Stop hook feedback: write the line"),
        queued("2026-01-01T00:02:00Z", "also do Y"),
        queued("2026-01-01T00:02:10Z", "<task-notification>done</task-notification>", kind="human"),
        queued("2026-01-01T00:02:20Z", "a peer queued this", kind="peer"),
        user("2026-01-01T00:03:00Z", "<system-reminder>injected</system-reminder>"),
        user("2026-01-01T00:04:00Z", "meta line", isMeta=True),
        user("2026-01-01T00:05:00Z", "second request: the proviso, add all three"),
        "not json",
        queued("2026-01-01T00:05:30Z", "the sheet waits until everything is decided"),
        user("2026-01-01T00:05:40Z", "<task-notification>a watcher</task-notification>"),
    ]
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "t.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
        ents = owner_entries(p)
        check("owner entries = typed prompts only (peer, hook, tool result, notice, meta, injected out)",
              [e["text"][:6] for e in ents] == ["first ", "also d", "second", "the sh"])
        check("queued flags", [e["queued"] for e in ents] == [False, True, False, True])
        lat = latest_input(ents)
        check("latest input = last typed prompt + queued after it", [e["text"][:6] for e in lat] == ["second", "the sh"])
        now = _dt.datetime(2026, 1, 1, 0, 10, tzinfo=_dt.timezone.utc)
        r = find_quote(p, "put the X job on the top model", now)
        check("an earlier request's words: found, not in the latest input", r["found"] and not r["in_latest"] and r["later"] == 3 and r["minutes"] == 10)
        r = find_quote(p, "the proviso,   add all three", now)
        check("the latest typed prompt, whitespace normalized: in the latest input", r["found"] and r["in_latest"] and r["later"] == 1)
        r = find_quote(p, "the sheet waits", now)
        check("a prompt queued after the latest typed one: in the latest input", r["in_latest"])
        r = find_quote(p, "also do Y", now)
        check("a prompt queued before the latest typed one: not in the latest input", r["found"] and not r["in_latest"])
        check("a paraphrase is not found", not find_quote(p, "add the proviso", now)["found"])
        check("empty words are not found", not find_quote(p, "  ", now)["found"])
        check("a peer's words are not the owner's", not find_quote(p, "a peer asks", now)["found"])
        check("a missing file: nothing found", not find_quote(os.path.join(td, "none.jsonl"), "x")["found"] and owner_entries(None) == [])
        check("transcript_for refuses a non-id", transcript_for("role-x-y") is None and transcript_for("") is None)
    print(f"{'OK' if not fails else 'FAILED'}: {fails} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcript")
    ap.add_argument("--session")
    ap.add_argument("--quote")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    path = a.transcript or (transcript_for(a.session) if a.session else None)
    if not path:
        print("no transcript", file=sys.stderr)
        return 2
    if a.quote is not None:
        print(json.dumps(find_quote(path, a.quote), ensure_ascii=False, indent=1))
    else:
        for e in latest_input(owner_entries(path)):
            print(("(queued) " if e["queued"] else "") + _norm(e["text"])[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
