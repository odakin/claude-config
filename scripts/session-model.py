#!/usr/bin/env python3
"""session-model.py — print the model a Claude Code session actually runs on (read from its transcript), before sending it work.

The title tag `[model: …]`, the chip text and the sessions registry do not say which model a session runs on;
the transcript does (every assistant turn carries `message.model`, and it can change mid-session when the app-wide
picker is switched). This CLI resolves a target and prints the last assistant turn's model, its tier, and when
that turn was — the check to make before a `SendMessage` / board `request` to an existing session
(conventions/multi-session-coordination.md#delegate-model-routing). Read-only.

Usage:
  session-model.py <target>            target = session id or its prefix (5d7b7b2e), a `local_…` host id
                                       (the from-session of a cross-session message), or a substring of the
                                       name ListAgents shows
  session-model.py --live              every live session on this machine with its model
  session-model.py <target> --json     machine-readable rows
  session-model.py --selftest

Exit: 0 = every matched session has a model / 2 = nothing matched / 3 = matched but no transcript or no assistant
turn yet (a session that has not answered has no model on record — the app-wide picker decides when it does).
Engine = scripts/lib/session_model.py (env overrides CLAUDE_SESSIONS_DIR / CLAUDE_PROJECTS_DIR for tests).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import session_model as sm  # noqa: E402


def fmt(row: dict) -> str:
    sid = row["sessionId"][:8]
    model = row["model"] or "?"
    when = f" (最後の応答 {row['model_at'][:16]})" if row.get("model_at") else " (応答がまだ無い = model は記録に無い)"
    name = f"  name={row['name']}" if row.get("name") else ""
    status = f"  status={row['status']}" if row.get("status") else ""
    return f"{sid}  {model}  tier={row['tier'] or '?'}{when}{status}{name}"


def selftest() -> int:
    import subprocess
    import tempfile
    import uuid

    fails: list[str] = []

    def check(label: str, ok: bool) -> None:
        print(("ok: " if ok else "NG: ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        sdir, pdir = os.path.join(td, "sessions"), os.path.join(td, "projects")
        os.makedirs(sdir)
        os.makedirs(os.path.join(pdir, "-w-p"))
        sid, sid2 = str(uuid.uuid4()), str(uuid.uuid4())

        def line(kind: str, model: str | None, ts: str, text: str = "x") -> str:
            msg = {"role": kind, "content": text}
            if model is not None:
                msg["model"] = model
            return json.dumps({"type": kind, "message": msg, "timestamp": ts}, ensure_ascii=False)

        tr = os.path.join(pdir, "-w-p", f"{sid}.jsonl")
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write(line("user", None, "t0") + "\n")
            fh.write(line("assistant", "claude-fable-5-1", "t1") + "\n")
            fh.write(line("assistant", "<synthetic>", "t2") + "\n")
            fh.write(line("assistant", "claude-opus-5-5", "t3") + "\n")
        with open(os.path.join(sdir, "1.json"), "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "sessionId": sid, "cwd": "/w/p", "name": "テスト session A",
                       "hostSessionId": "local_aaa", "status": "idle"}, fh)
        with open(os.path.join(sdir, "2.json"), "w", encoding="utf-8") as fh:  # registered but no transcript yet
            json.dump({"pid": os.getpid(), "sessionId": sid2, "cwd": "/w/p", "name": "テスト session B",
                       "hostSessionId": "local_bbb", "status": "idle"}, fh)
        with open(os.path.join(sdir, "3.json"), "w", encoding="utf-8") as fh:  # dead process = not live
            json.dump({"pid": 2 ** 30, "sessionId": str(uuid.uuid4()), "cwd": "/w/p", "name": "dead", "status": "idle"}, fh)
        env = dict(os.environ, CLAUDE_SESSIONS_DIR=sdir, CLAUDE_PROJECTS_DIR=pdir)
        os.environ.update(CLAUDE_SESSIONS_DIR=sdir, CLAUDE_PROJECTS_DIR=pdir)

        info = sm.last_model(tr)
        check("the last assistant turn's model wins, <synthetic> is skipped", bool(info) and info["model"] == "claude-opus-5-5" and info["at"] == "t3")
        check("a mid-session model change is seen at the end, not the start", info and info["model"] != "claude-fable-5-1")
        # tail read: a big transcript with the answer at the end / a big transcript whose tail has no assistant turn
        big = os.path.join(pdir, "-w-p", f"{sid2}.jsonl")
        with open(big, "w", encoding="utf-8") as fh:
            fh.write(line("assistant", "claude-fable-5", "t0") + "\n")
            for i in range(3000):
                fh.write(line("user", None, f"u{i}", "y" * 200) + "\n")
        info = sm.last_model(big)
        check("tail without an assistant turn falls back to a full scan", bool(info) and info["model"] == "claude-fable-5" and info["tail"] is False)
        with open(big, "a", encoding="utf-8") as fh:
            fh.write(line("assistant", "claude-opus-5", "t9") + "\n")
        info = sm.last_model(big)
        check("an assistant turn in the tail is found without a full scan", bool(info) and info["model"] == "claude-opus-5" and info["tail"] is True)
        os.remove(big)
        check("no assistant turn yet → None", sm.last_model(os.path.join(pdir, "-w-p", "nope.jsonl")) is None)
        check("tier from the model id", (sm.tier("claude-fable-5-1"), sm.tier("claude-opus-5-5"), sm.tier("claude-mythos-5-1"), sm.tier(""), sm.tier("x")) == ("fable", "opus", "fable", "", "unknown"))
        live = sm.live_sessions()
        check("dead processes are not live", [s["name"] for s in live] == ["テスト session A", "テスト session B"] or sorted(s["name"] for s in live) == ["テスト session A", "テスト session B"])
        check("resolve by id prefix", [s["sessionId"] for s in sm.resolve(sid[:8])] == [sid])
        check("resolve by host id", [s["sessionId"] for s in sm.resolve("local_aaa")] == [sid])
        check("resolve by name substring", [s["sessionId"] for s in sm.resolve("session A")] == [sid])
        check("unknown target resolves to nothing", sm.resolve("local_zzz") == [] and sm.resolve("no such name") == [])
        d = sm.describe(sm.resolve(sid[:8])[0])
        check("describe adds model / tier / time", d["model"] == "claude-opus-5-5" and d["tier"] == "opus" and d["model_at"] == "t3")
        d2 = sm.describe(sm.resolve("local_bbb")[0])
        check("a live session without a transcript has an empty model", d2["model"] == "" and d2["tier"] == "")
        check("model_of never raises and returns '' when unknown", sm.model_of("no-such-id") == "" and sm.model_of(sid, "/w/p") == "claude-opus-5-5")
        # the CLI: exit codes
        me = os.path.abspath(__file__)
        r = subprocess.run([sys.executable, me, sid[:8]], env=env, capture_output=True, text=True)
        check("CLI prints the model and exits 0", r.returncode == 0 and "claude-opus-5-5" in r.stdout and "tier=opus" in r.stdout)
        r = subprocess.run([sys.executable, me, "local_zzz"], env=env, capture_output=True, text=True)
        check("CLI exits 2 when nothing matches", r.returncode == 2)
        r = subprocess.run([sys.executable, me, "session B"], env=env, capture_output=True, text=True)
        check("CLI exits 3 when the session has no model on record", r.returncode == 3 and "応答がまだ無い" in r.stdout)
        r = subprocess.run([sys.executable, me, "--live", "--json"], env=env, capture_output=True, text=True)
        rows = json.loads(r.stdout or "[]")
        check("--live --json lists live sessions with models", r.returncode in (0, 3) and {x["sessionId"] for x in rows} == {sid, sid2})
    print("session-model selftest: " + ("ALL PASS" if not fails else f"FAILED {len(fails)}"))
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("target", nargs="?", help="session id / prefix, local_… host id, or a substring of the name")
    ap.add_argument("--live", action="store_true", help="every live session on this machine")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.live:
        rows = [sm.describe(s) for s in sm.live_sessions()]
    elif a.target:
        rows = [sm.describe(s) for s in sm.resolve(a.target)]
    else:
        ap.print_help()
        return 2
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for r in rows:
            print(fmt(r))
        if not rows:
            print("(該当する session が無い = 生きている session の name / id / local_… host id と一致しない)")
    if not rows:
        return 2
    return 0 if all(r["model"] for r in rows) else 3


if __name__ == "__main__":
    raise SystemExit(main())
