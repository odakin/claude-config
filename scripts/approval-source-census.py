#!/usr/bin/env python3
"""Count user-message leading tags without printing bodies, paths or session identifiers; --selftest.

Only explicitly supplied transcript roots are scanned. Codex's two carriers
are counted separately, not added into an estimate of distinct human turns.
Claude's human-origin sample requires type=user and turnOrigin=human. Missing
or unreadable input is reported as an inspection failure, never as zero data.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


def guard_module():
    spec = importlib.util.spec_from_file_location("approval_source_guard", Path(__file__).with_name("manuscript-claim-guard.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def user_texts(row):
    """Return carrier and user text; never return source identifiers or paths."""
    if not isinstance(row, dict):
        return
    if row.get("type") == "user" and row.get("turnOrigin") == "human":
        if row.get("isMeta") or row.get("isSidechain") or row.get("promptSource") == "system":
            return
        content = (row.get("message") or {}).get("content")
        if isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                return
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(content, str):
            yield "claude_human", content
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return
    if row.get("type") == "event_msg" and payload.get("type") == "user_message":
        if isinstance(payload.get("message"), str):
            yield "codex_event_msg", payload["message"]
    if row.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
        content = payload.get("content")
        if isinstance(content, list) and all(isinstance(b, dict) and b.get("type") in ("input_text", "input_image") for b in content):
            yield "codex_response_item", "".join(b.get("text", "") for b in content if b.get("type") == "input_text")


def census(roots, tag_re, strip_patterns=()):
    samples = {k: {"messages": 0, "empty": 0, "non_tag": 0, "agents_prefix": 0,
                   "tags": Counter(), "tags_after_known_blocks": Counter()}
               for k in ("codex_event_msg", "codex_response_item", "claude_human")}
    errors, seen, read = Counter(), set(), 0
    def files_in(root):
        if root.is_file():
            yield root
            return
        def unreadable(exc):
            errors[type(exc).__name__] += 1
        for folder, _dirs, names in os.walk(root, onerror=unreadable, followlinks=False):
            for name in names:
                if name.endswith(".jsonl"):
                    yield Path(folder) / name
    for root in roots:
        if not root.exists():
            errors["missing_root"] += 1
            continue
        for path in files_in(root):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            errors["invalid_json"] += 1
                            continue
                        for carrier, text in user_texts(row):
                            sample = samples[carrier]
                            sample["messages"] += 1
                            remaining = text
                            for pattern in strip_patterns:
                                remaining = pattern.sub("", remaining)
                            after = tag_re.match(remaining)
                            if after:
                                sample["tags_after_known_blocks"][after.group(1)[:80]] += 1
                            match = tag_re.match(text)
                            if match:
                                # Bound diagnostic labels: the complete message is never emitted.
                                sample["tags"][match.group(1)[:80]] += 1
                            elif text.lstrip().startswith("# AGENTS.md instructions"):
                                sample["agents_prefix"] += 1
                            elif not text.strip():
                                sample["empty"] += 1
                            else:
                                sample["non_tag"] += 1
                read += 1
            except (OSError, UnicodeError, TypeError, AttributeError) as exc:
                errors[type(exc).__name__] += 1
    return {"files_read": read, "samples": samples, "inspection_errors": dict(errors)}


def selftest():
    import tempfile
    tag_re = re.compile(r"^\s*<([A-Za-z_][\w:-]*)(?=[\s>/])")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        rows = [
            {"type": "user", "turnOrigin": "human", "message": {"content": " <foo>PRIVATE_BODY</foo>"}},
            {"type": "user", "turnOrigin": "human", "isMeta": True, "message": {"content": "<meta>PRIVATE_BODY</meta>"}},
            {"type": "user", "turnOrigin": "peer", "message": {"content": "<peer>PRIVATE_BODY</peer>"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "a < b"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<turn_aborted>PRIVATE_BODY"}]}},
        ]
        p = root / "private-session-id.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        result = census([root, p], tag_re)
        assert result["files_read"] == 1 and not result["inspection_errors"]
        assert result["samples"]["claude_human"]["tags"] == {"foo": 1}
        assert result["samples"]["codex_response_item"]["tags"] == {"turn_aborted": 1}
        assert result["samples"]["codex_event_msg"]["non_tag"] == 1
        rendered = json.dumps(result)
        assert "PRIVATE_BODY" not in rendered and str(p) not in rendered and "private-session-id" not in rendered
        assert census([root / "missing"], tag_re)["inspection_errors"] == {"missing_root": 1}
        import subprocess
        loop = root / "private-loop.jsonl"
        loop.symlink_to(loop.name)
        failed = subprocess.run([sys.executable, __file__, "--root", str(root)], capture_output=True, text=True)
        assert failed.returncode == 3 and str(root) not in failed.stdout + failed.stderr
        assert "PRIVATE_BODY" not in failed.stdout + failed.stderr and not failed.stderr
        if os.name != "nt" and os.geteuid() != 0:
            denied = root / "private-unreadable"
            denied.mkdir()
            denied.chmod(0)
            try:
                failed = subprocess.run([sys.executable, __file__, "--root", str(denied)], capture_output=True, text=True)
                assert failed.returncode == 3 and json.loads(failed.stdout)["inspection_errors"] == {"PermissionError": 1}
                assert str(denied) not in failed.stdout + failed.stderr and not failed.stderr
            finally:
                denied.chmod(0o700)
    print("approval-source-census: carrier isolation, origin filter, bounded labels, privacy and missing-input checks passed")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", action="append", type=Path, default=[], help="explicit transcript directory or JSONL file; repeatable")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.root:
        parser.error("at least one --root is required")
    try:
        guard = guard_module()
        result = census(args.root, guard.LEADING_USER_TAG_RE, (guard.SYSTEM_REMINDER_RE, guard.HOOK_PROMPT_RE))
    except Exception as exc:
        # A malformed tree or transcript must not expose a path in a traceback.
        result = {"inspection_errors": {type(exc).__name__: 1}, "inspection_unavailable": True}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 3 if result["inspection_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
