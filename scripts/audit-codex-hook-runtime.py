#!/usr/bin/env python3
"""Read Codex hook trust through hooks/list; distinguish trusted configuration from untested live dispatch.

# agent-authority:file

Uses the selected installed Codex executable's public app-server protocol.
Starts no task/model and changes no trust/configuration. A fresh server reads
persisted state; an already-running task may still have an older hook snapshot.
Output always says live_dispatch=not_tested. Actual tool rejection plus an
allowed control must be observed separately (conventions/agent-rule-ownership.md).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time


def assess(data: dict, needle: str) -> tuple[dict, int]:
    if not isinstance(data, dict):
        raise ValueError("unexpected hooks/list response")
    rows = data.get("data")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("unexpected hooks/list response")
    row = rows[0]
    if not isinstance(row, dict) or not isinstance(row.get("hooks"), list):
        raise ValueError("unexpected hooks/list row")
    if row.get("errors"):
        raise ValueError("Codex reported hook configuration errors")
    if any(not isinstance(h, dict) for h in row["hooks"]):
        raise ValueError("unexpected hooks/list hook")
    hooks = []
    for h in row["hooks"]:
        # hooks/list also contains valid prompt, agent and MCP handlers without a command field.
        if h.get("handlerType") in ("prompt", "agent", "mcpTool"):
            continue
        if h.get("handlerType") not in (None, "command") or not isinstance(h.get("command"), str):
            raise ValueError("unexpected command hook metadata")
        if needle in h["command"]:
            hooks.append(h)
    states = [{k: h.get(k) for k in ("eventName", "matcher", "enabled", "trustStatus", "source")} for h in hooks]
    expected = {"Bash", "apply_patch", "stop"}
    active = set()
    for hook in hooks:
        if hook.get("enabled") is not True or hook.get("trustStatus") not in ("trusted", "managed"):
            continue
        if hook.get("eventName") == "stop":
            if re.search(r"(?:^|\s)--stop(?:\s|$)", hook.get("command", "")):
                active.add("stop")
            continue
        if hook.get("eventName") != "preToolUse":
            continue
        matcher = hook.get("matcher") or ""
        if not isinstance(matcher, str):
            raise ValueError("unexpected hook matcher")
        try:
            re.compile(matcher)
        except re.error as exc:
            raise ValueError("invalid hook matcher") from exc
        for name in ("Bash", "apply_patch"):
            aliases = (name, "Edit", "Write") if name == "apply_patch" else (name,)
            if matcher in ("", "*") or any(re.search(matcher, alias) for alias in aliases):
                active.add(name)
    missing = sorted(expected - active)
    ready = not missing
    return {"configuration": "ready_for_live_probe" if ready else "not_armed",
            "hooks": states, "missing": missing, "live_dispatch": "not_tested"}, 0 if ready else 1


def read_hooks(binary: str, cwd: str, timeout: float) -> dict:
    process = subprocess.Popen([binary, "app-server", "--stdio"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    messages: queue.Queue = queue.Queue()
    def reader():
        try:
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            messages.put(None)
    worker = threading.Thread(target=reader, daemon=True)
    worker.start()
    deadline = time.monotonic() + timeout
    def send(value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()
    def receive(ident):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("hooks/list timed out")
            try:
                value = messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError("hooks/list timed out") from exc
            if value is None:
                raise RuntimeError("Codex app-server exited before responding")
            if isinstance(value, dict) and value.get("id") == ident:
                if "error" in value:
                    raise RuntimeError("Codex app-server rejected hooks/list")
                return value.get("result", {})
    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "rule-guard-audit", "version": "1"},
            "capabilities": {"experimentalApi": True}}})
        receive(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "hooks/list", "params": {"cwds": [cwd]}})
        return receive(2)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        process.stdin.close()
        worker.join(timeout=1)
        process.stdout.close()


def selftest() -> int:
    def fixture(trust="trusted", enabled=True):
        return {"data": [{"errors": [], "hooks": [{"eventName": "preToolUse", "matcher": name,
            "enabled": enabled, "trustStatus": trust, "source": "user", "command": "python3 manuscript_claim_guard.py"}
            for name in ("Bash", "apply_patch")] + [{"eventName": "stop", "matcher": None,
            "enabled": enabled, "trustStatus": trust, "source": "user",
            "command": "python3 manuscript_claim_guard.py --stop"}]}]}
    checks = []
    result, rc = assess(fixture(), "manuscript_claim_guard.py")
    checks.append(("trusted is ready, never proof of live dispatch", rc == 0 and result["live_dispatch"] == "not_tested"))
    for state in ("untrusted", "modified"):
        checks.append((state + " cannot be reported armed", assess(fixture(state), "manuscript_claim_guard.py")[1] == 1))
    checks.append(("disabled trusted hook is not armed", assess(fixture(enabled=False), "manuscript_claim_guard.py")[1] == 1))
    missing = fixture(); missing["data"][0]["hooks"].pop(1)
    checks.append(("one missing matcher is not armed", assess(missing, "manuscript_claim_guard.py")[1] == 1))
    combined = fixture(); combined["data"][0]["hooks"].pop(1)
    combined["data"][0]["hooks"][0]["matcher"] = "^(Bash|Edit)$"
    checks.append(("regex and patch aliases follow the documented matcher", assess(combined, "manuscript_claim_guard.py")[1] == 0))
    for state in ("untrusted", "modified"):
        stop = fixture(); stop["data"][0]["hooks"][-1]["trustStatus"] = state
        result, rc = assess(stop, "manuscript_claim_guard.py")
        checks.append(("Stop " + state + " is explicitly missing", rc == 1 and result.get("missing") == ["stop"]))
    for field, value in (("enabled", False), ("command", "python3 manuscript_claim_guard.py")):
        stop = fixture(); stop["data"][0]["hooks"][-1][field] = value
        result, rc = assess(stop, "manuscript_claim_guard.py")
        checks.append(("Stop " + field + " is required", rc == 1 and result.get("missing") == ["stop"]))
    stop = fixture(); stop["data"][0]["hooks"].pop()
    result, rc = assess(stop, "manuscript_claim_guard.py")
    checks.append(("absent Stop is not armed", rc == 1 and result.get("missing") == ["stop"]))
    checks.append(("managed hooks are ready", assess(fixture("managed"), "manuscript_claim_guard.py")[1] == 0))
    for kind in ("prompt", "agent", "mcpTool"):
        mixed = fixture()
        mixed["data"][0]["hooks"].append({"handlerType": kind, "eventName": "stop",
                                        "enabled": True, "trustStatus": "trusted"})
        checks.append(("valid " + kind + " handler does not invalidate command-hook audit",
                       assess(mixed, "manuscript_claim_guard.py")[1] == 0))
        mixed["data"][0]["hooks"].pop(-2)  # Only the unrelated non-command Stop remains.
        result, rc = assess(mixed, "manuscript_claim_guard.py")
        checks.append((kind + " handler does not satisfy the reporting Stop requirement",
                       rc == 1 and result["missing"] == ["stop"]))
    malformed = [None, {"data": [None]}, {"data": [{"hooks": [None]}]}]
    bad_regex = fixture(); bad_regex["data"][0]["hooks"][0]["matcher"] = "["
    malformed.append(bad_regex)
    for value in malformed:
        try:
            assess(value, "manuscript_claim_guard.py")
        except Exception as exc:
            checks.append(("malformed configuration is inspection failure", isinstance(exc, ValueError)))
        else:
            checks.append(("malformed configuration is inspection failure", False))
    errors = fixture(); errors["data"][0]["errors"] = [{"message": "bad config"}]
    try:
        assess(errors, "manuscript_claim_guard.py")
    except ValueError:
        checks.append(("configuration errors are inspection failure", True))
    else:
        checks.append(("configuration errors are inspection failure", False))
    for name, ok in checks:
        print(("PASS: " if ok else "FAIL: ") + name)
    return 0 if all(ok for _, ok in checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--codex", default="codex", help="installed executable; select the Desktop binary explicitly when auditing Desktop")
    parser.add_argument("--cwd", default=str(Path.cwd()))
    parser.add_argument("--command-substring", default="manuscript_claim_guard.py")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    try:
        binary = shutil.which(args.codex)
        if not binary:
            raise FileNotFoundError("selected Codex executable missing")
        report, rc = assess(read_hooks(binary, str(Path(args.cwd).resolve()), args.timeout), args.command_substring)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return rc
    except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
        print(json.dumps({"configuration": "inspection_unavailable", "error_type": type(exc).__name__,
                          "live_dispatch": "not_tested"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
