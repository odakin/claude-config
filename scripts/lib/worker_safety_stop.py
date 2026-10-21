"""Inspect typed refusal markers without emitting conversation or reasoning text.

Only assistant stop_reason=refusal and harness-injected refusedMessageId count.
A quoted notice, idle status, or tool failure does not. This is a conservative
history check, not proof of a permanent provider lock. Later successful turns do
not erase the marker. Never sends, closes, starts, or changes a model.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

_CATEGORIES = {"cyber", "bio", "frontier_llm", "reasoning_extraction", "general_harms"}


def marker(record):
    if not isinstance(record, dict) or record.get("isSidechain"):
        return None
    if (record.get("type") == "user" and record.get("isMeta") is True
            and isinstance(record.get("refusedMessageId"), str) and record["refusedMessageId"]):
        return {"source": "refusedMessageId", "category": None}
    message = record.get("message")
    if (record.get("type") == "assistant" and isinstance(message, dict)
            and message.get("stop_reason") == "refusal"):
        details = message.get("stop_details")
        category = details.get("category") if isinstance(details, dict) else None
        return {"source": "stop_reason", "category": category if isinstance(category, str) and category in _CATEGORIES else None}
    return None


def inspect(path):
    """Full local log scan; malformed/missing logs are unknown, never healthy."""
    found = None
    malformed = False
    try:
        with Path(path).open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except ValueError:
                    malformed = True
                    continue
                value = marker(record)
                if value:
                    timestamp = record.get("timestamp")
                    found = {**value, "line": number,
                             "timestamp": timestamp if isinstance(timestamp, str) and re.fullmatch(r"[0-9T:Z.+-]+", timestamp) else None}
    except (OSError, UnicodeError, TypeError, ValueError):
        return {"state": "refused", **found} if found else {"state": "unknown"}
    if found:
        return {"state": "refused", **found}
    return {"state": "unknown" if malformed else "no_refusal_observed"}


def resolve_target(target, sessions):
    """Exact local/socket address or unambiguous native id prefix; no fuzzy title."""
    if not isinstance(target, str) or not target:
        return None
    matches = [s for s in sessions if target in (s.get("host"), s.get("address"), s.get("sessionId"))
               or (re.fullmatch(r"[0-9a-f-]{8,36}", target) and s.get("sessionId", "").startswith(target))]
    return matches[0] if len(matches) == 1 else None


def selftest():
    import tempfile
    checks = 0
    def check(value):
        nonlocal checks
        assert value
        checks += 1
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "records.jsonl"
        def write(records):
            path.write_text("".join(json.dumps(r) + "\n" for r in records))
        provider = {"type": "assistant", "timestamp": "2099-01-01T01:00:00Z", "message": {
            "stop_reason": "refusal", "stop_details": {"category": "reasoning_extraction", "explanation": "DO_NOT_EMIT"},
            "content": [{"type": "thinking", "thinking": "DO_NOT_EMIT"}]}}
        harness = {"type": "user", "isMeta": True, "refusedMessageId": "synthetic-message", "message": {"content": "DO_NOT_EMIT"}}
        for r in (provider, harness):
            write([r]); answer = inspect(path)
            check(answer["state"] == "refused")
            check("DO_NOT_EMIT" not in json.dumps(answer))
        for r in ({"type": "user", "message": {"content": json.dumps(provider)}},
                  {"type": "user", "refusedMessageId": "quoted", "message": {}},
                  {"type": "user", "message": {"content": [{"type": "tool_result", "content": json.dumps(provider), "is_error": True}]}},
                  {**provider, "isSidechain": True}, {"status": "idle"}):
            write([r]); check(inspect(path)["state"] == "no_refusal_observed")
        write([harness, {"type": "assistant", "message": {"stop_reason": "end_turn"}}])
        check(inspect(path)["state"] == "refused")
        path.write_text("{unfinished"); check(inspect(path)["state"] == "unknown")
        check(inspect(Path(temp)/"missing")["state"] == "unknown")
        sid = "a"*8 + "-1111-2222-3333-444444444444"
        row = {"sessionId": sid, "host": "local_test", "address": "uds:/tmp/example.sock", "name": "Title"}
        for address in (sid, sid[:8], row["host"], row["address"]):
            check(resolve_target(address, [row]) == row)
        check(resolve_target("Title", [row]) is None)
        check(resolve_target(sid[:8], [row, {**row, "sessionId": sid[:-1]+"5"}]) is None)
    print(f"worker_safety_stop: {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
