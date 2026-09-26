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
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time


BUNDLE_PATHS = (
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
    "/Applications/ChatGPT.app/Contents/Resources/codex",
)


def discover_codex(requested="auto", *, process_lines=None, bundle_paths=None, which=None):
    """Prefer a running app executable, then current/legacy bundles, then PATH."""
    which = which or shutil.which
    if requested != "auto":
        found = which(requested)
        if not found:
            raise FileNotFoundError("selected Codex executable missing")
        return str(Path(found).resolve()), "explicit"
    if process_lines is None:
        try:
            result = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=3)
            process_lines = result.stdout.splitlines() if result.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            process_lines = []
    for line in process_lines:
        path = line.strip()
        if (".app/Contents/" in path and path.endswith(("/Contents/MacOS/codex", "/Contents/Resources/codex"))
                and Path(path).is_file() and os.access(path, os.X_OK)):
            return str(Path(path).resolve()), "process"
    for path in BUNDLE_PATHS if bundle_paths is None else bundle_paths:
        if Path(path).is_file() and os.access(path, os.X_OK):
            return str(Path(path).resolve()), "bundle"
    found = which("codex")
    if found:
        return str(Path(found).resolve()), "PATH"
    raise FileNotFoundError("Codex executable unavailable")


def default_cache():
    return Path.home() / ".claude" / "state" / "codex-hook-trust.json"


def write_cache(path, report):
    """Atomically publish one observation; never touch Codex trust settings."""
    path = Path(path).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
    resolved = path.resolve()
    if (path.is_symlink() or codex_home == resolved or codex_home in resolved.parents
            or path.name.lower() in ("config.toml", "hooks.json", "settings.json", "settings.local.json")):
        raise ValueError("cache destination must not be a configuration file or symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".codex-hook-trust-", delete=False) as fh:
            temp = fh.name
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temp, path)
        temp = None
    finally:
        if temp is not None:
            os.unlink(temp)


def read_cache(path, now=None):
    """Read only. Missing, malformed or future-dated observations cannot be green."""
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("cache_version") != 1
                or value.get("configuration") not in ("ready_for_live_probe", "not_armed", "inspection_unavailable")):
            raise ValueError("cache schema")
        stamp = datetime.fromisoformat(value["checked_at"])
        if stamp.tzinfo is None:
            raise ValueError("cache timestamp")
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        if age < -300:
            raise ValueError("future cache timestamp")
        if not isinstance(value.get("missing", []), list) or any(not isinstance(s, str) for s in value.get("missing", [])):
            raise ValueError("cache missing list")
        value["cache_stale"] = age > 2 * 24 * 60 * 60
        return value
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"configuration": "inspection_unavailable", "error_type": type(exc).__name__,
                "cache_unavailable": True, "live_dispatch": "not_tested"}


def one_line(value, limit=400):
    return " ".join(str(value).split())[:limit]


def surface_line(report):
    state = report.get("configuration")
    stale = " (古い: 2日超)" if report.get("cache_stale") else ""
    path_note = " [PATH の codex、app とは別物かもしれない]" if report.get("binary_source") == "PATH" else ""
    if state == "ready_for_live_probe":
        if stale:
            return "⚠️ Codex の hook 信頼: 監査cacheが古い (2日超)。dashboardで再監査する。"
        return "⚠️ " + path_note.strip() if path_note else ""
    if state == "not_armed":
        binary = shlex.quote(one_line(report.get("binary") or "codex"))
        return ("🔴 Codex の hook 信頼が落ちている: missing = " + one_line(report.get("missing", []))
                + stale + "、付け直し = terminalで " + binary + " を起動して /hooks" + path_note)
    suffix = "、監査cache未取得・読取不能" if report.get("cache_unavailable") else ""
    return "⚠️ Codex の hook 信頼: 検査不能 (" + one_line(report.get("error_type", "UnknownState")) + ")" + suffix + stale + path_note


def result_code(report):
    if report.get("configuration") == "not_armed":
        return 1
    if report.get("configuration") == "ready_for_live_probe" and not report.get("cache_stale"):
        return 0
    return 3


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
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp).resolve()
        running = root / "Example App.app/Contents/MacOS/codex"
        bundle = root / "Bundle.app/Contents/Resources/codex"
        for path in (running, bundle):
            path.parent.mkdir(parents=True)
            path.write_text("synthetic executable\n")
            path.chmod(0o755)
        absent = lambda _name: None
        checks.append(("auto prefers running app, including spaces", discover_codex(
            process_lines=[str(running)], bundle_paths=[str(bundle)], which=absent) == (str(running), "process")))
        checks.append(("auto skips obsolete bundle paths", discover_codex(
            process_lines=[], bundle_paths=[str(root / "obsolete"), str(bundle)], which=absent) == (str(bundle), "bundle")))
        checks.append(("auto PATH fallback is identified", discover_codex(
            process_lines=[], bundle_paths=[], which=lambda _name: str(bundle)) == (str(bundle), "PATH")))
        try:
            discover_codex(process_lines=[], bundle_paths=[], which=absent)
        except FileNotFoundError:
            checks.append(("auto with no executable fails inspection", True))
        else:
            checks.append(("auto with no executable fails inspection", False))
        cache = root / "state/trust.json"
        now = datetime.now(timezone.utc)
        good, _ = assess(fixture(), "manuscript_claim_guard.py")
        good.update(cache_version=1, checked_at=now.isoformat(), binary=str(bundle), binary_source="bundle")
        write_cache(cache, good)
        before = cache.read_bytes()
        checks.append(("fresh ready cache is silent", surface_line(read_cache(cache, now)) == ""))
        checks.append(("cache reading never changes bytes", cache.read_bytes() == before))
        checks.append(("cache file is private", cache.stat().st_mode & 0o777 == 0o600))
        protected = root / "hooks.json"
        protected.write_text("keep existing configuration")
        alias = root / "cache-alias.json"
        alias.symlink_to(protected)
        for target in (protected, alias):
            try:
                write_cache(target, good)
            except ValueError:
                checks.append(("cache writer refuses configuration or symlink targets", protected.read_text() == "keep existing configuration"))
            else:
                checks.append(("cache writer refuses configuration or symlink targets", False))
        bad, _ = assess(fixture("untrusted"), "manuscript_claim_guard.py")
        bad.update(cache_version=1, checked_at=now.isoformat(), binary=str(bundle))
        write_cache(cache, bad)
        checks.append(("untrusted cache renders red", surface_line(read_cache(cache, now)).startswith("🔴")))
        unknown = dict(good, configuration="inspection_unavailable", error_type="TimeoutError")
        write_cache(cache, unknown)
        checks.append(("inspection failure cache renders warning", surface_line(read_cache(cache, now)).startswith("⚠️")))
        from datetime import timedelta
        write_cache(cache, good)
        stale = read_cache(cache, now + timedelta(days=3))
        checks.append(("old ready cache is not silent success", "古い" in surface_line(stale) and result_code(stale) == 3))
        write_cache(cache, bad)
        checks.append(("old untrusted cache remains red and marked old", surface_line(read_cache(cache, now + timedelta(days=3))).startswith("🔴")
                       and "古い" in surface_line(read_cache(cache, now + timedelta(days=3)))))
        checks.append(("absent cache is inspection failure", result_code(read_cache(root / "absent")) == 3))
        for invalid in ([], {"configuration": "ready_for_live_probe"}, dict(good, checked_at=(now + timedelta(days=1)).isoformat())):
            cache.write_text(json.dumps(invalid))
            checks.append(("invalid cache cannot look ready", surface_line(read_cache(cache, now)).startswith("⚠️")))
        checks.append(("PATH-ready observation carries runtime warning", "PATH" in surface_line(dict(good, binary_source="PATH"))))
    for name, ok in checks:
        print(("PASS: " if ok else "FAIL: ") + name)
    return 0 if all(ok for _, ok in checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--codex", default="auto", help="auto: running app, known bundles, then PATH; or an explicit executable")
    parser.add_argument("--cwd", default=str(Path.cwd()))
    parser.add_argument("--command-substring", default="manuscript_claim_guard.py")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--cache", nargs="?", const=str(default_cache()), help="write the observation to this machine-local cache")
    parser.add_argument("--read-cache", action="store_true", help="read the cache only; start no process and write nothing")
    parser.add_argument("--surface", action="store_true", help="print one diagnostic line; a fresh ready app configuration is silent")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.read_cache:
        report = read_cache(args.cache or default_cache())
        output = surface_line(report) if args.surface else json.dumps(report, ensure_ascii=False, indent=2)
        if output:
            print(output)
        return result_code(report)
    report = {"cache_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(), "live_dispatch": "not_tested"}
    try:
        binary, source = discover_codex(args.codex)
        report.update(binary=binary, binary_source=source)
        version = subprocess.run([binary, "--version"], stdin=subprocess.DEVNULL, capture_output=True,
                                 text=True, timeout=min(args.timeout, 5), check=True)
        report["binary_version"] = one_line(version.stdout.strip() or "unknown", 160)
        if source == "PATH":
            report["binary_warning"] = "PATH の codex、app とは別物かもしれない"
        observation, _ = assess(read_hooks(binary, str(Path(args.cwd).resolve()), args.timeout), args.command_substring)
        report.update(observation)
    except (OSError, RuntimeError, ValueError, TimeoutError, subprocess.SubprocessError) as exc:
        report.update(configuration="inspection_unavailable", error_type=type(exc).__name__)
    if args.cache:
        try:
            write_cache(args.cache, report)
        except (OSError, ValueError) as exc:
            report.update(configuration="inspection_unavailable", error_type=type(exc).__name__, cache_write_failed=True)
    output = surface_line(report) if args.surface else json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        print(output)
    return result_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
