#!/usr/bin/env python3
"""session-model.py — print the model a Claude Code session actually runs on (read from its transcript), before sending it work.

The title tag `[model: …]`, the chip text and the sessions registry do not say which model a session runs on;
the transcript does (every assistant turn carries `message.model`, and it can change mid-session when the app-wide
picker is switched). This CLI resolves a target and prints the last assistant turn's model, its tier, and when
that turn was — the check to make before a `SendMessage` / board `request` to an existing session
(conventions/multi-session-coordination.md#delegate-model-routing). Read-only.

Usage:
  session-model.py <target>            target = session id or its prefix (0123abcd), a `local_…` host id
                                       (the from-session of a cross-session message), or a substring of the
                                       name ListAgents shows
  session-model.py self                this session (a worker checks the model and effort it was started on)
  session-model.py self --expect-model M [--expect-effort E]
                                       a worker's step 0: compare the app's record of this session (= the next
                                       turn's values) and this turn's values (what the CLI sent to the API = the
                                       transcript's `api-request`; the transcript's model when none is logged) with
                                       what the hand-off asked for. ✅ = go on / ⏸ = stop, and before stopping send
                                       the printed line to the session that started this one (the app's record names
                                       it, for a card the owner clicked too). The line says when it was written: it
                                       can be held and arrive after the `go`
  session-model.py --live              every live session on this machine with its model
  session-model.py <target> --json     machine-readable rows
  session-model.py --selftest

Exit: 0 = every matched session has a model / 2 = nothing matched / 3 = matched but no transcript or no assistant
turn yet (a session that has not answered has no model on record — the app-wide picker decides when it does).
With --expect-*: 0 = the app's record matches / 4 = it differs or cannot be read (the worker stops at its step 0).

Why the line to the starter (measured): a worker stopped at its step 0 ends its turn, and the app tells the session
that started it about a child's turn end only when none of that session's other children is running. A requester
with other children running stayed idle until the owner's next message (the owner had clicked a card, which no tool
call of the requester's sees). A SendMessage from a child did start a turn in an idle requester while its other
children ran.
Engine = scripts/lib/session_model.py (env overrides CLAUDE_SESSIONS_DIR / CLAUDE_PROJECTS_DIR for tests).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import session_model as sm  # noqa: E402


def fmt(row: dict) -> str:
    sid = row["sessionId"][:8]
    model = row["model"] or "?"
    when = f" (最後の応答 {row['model_at'][:16]})" if row.get("model_at") else " (応答がまだ無い = model は記録に無い)"
    name = f"  name={row['name']}" if row.get("name") else ""
    status = f"  status={row['status']}" if row.get("status") else ""
    cfg = f"  config={row['config']}" if row.get("config") and row["config"] != "default" else ""
    to = f"  SendMessage to={row['address']}" if row.get("address") else ""
    app = ""
    if row.get("app_model") or row.get("app_effort"):
        app = f"  app の記録={row.get('app_model') or '?'} effort={row.get('app_effort') or '?'}"
        if row.get("model") and row.get("app_model") and row["model"] != row["app_model"]:
            app += " (次の turn から = 最後の応答の model と違う)"
    if row.get("turn_effort"):
        app += f"  この turn の API={row.get('turn_model') or '?'} effort={row['turn_effort']}"
    return f"{sid}  {model}  tier={row['tier'] or '?'}{when}{app}{status}{name}{cfg}{to}"


def matches(want: str, got: str) -> bool:
    """A tier word (opus / fable / …) matches any model of that tier; a full model id matches itself."""
    w = (want or "").strip().lower()
    if not w:
        return True
    if w in ("fable", "opus", "sonnet", "haiku", "mythos"):
        return sm.tier(got or "") == ("fable" if w == "mythos" else w)
    return w == (got or "").strip().lower()


def with_starter(row: dict) -> dict:
    """The row with app_local (its `local_…`) and app_parent (the `local_…` of the session that started it, a clicked
    card included) from the app's record; unchanged when the app has no record of it."""
    try:
        import desktop_sessions as ds
        host = row.get("host") or ""
        rec = ds.find(host if host.startswith("local_") else row.get("sessionId", "")) or {}
    except Exception:
        rec = {}
    return {**row, "app_local": row.get("app_local") or rec.get("local_id", ""),
            "app_parent": row.get("app_parent") or rec.get("parent", "")}


TURN_TAIL_BYTES = 512 * 1024
TURN_FULL_SCAN_MAX = 16 * 1024 * 1024
# the session's own turns (measured: the api-request entries of recent desktop transcripts were all querySource "sdk")
MAIN_QUERY_SOURCES = (None, "sdk", "repl_main_thread")


def this_turn(path: str) -> dict:
    """{"model", "effort", "at"} that the CLI sent in this session's last API request (the transcript's `api-request`
    entry: params.model / params.output_config.effort); {} when the transcript holds none (a CLI that does not log it).

    Why next to the app's record: the record is what the NEXT turn runs on (set_session_* land there at once), and the
    turn running now keeps the value it started with (measured: a worker's first turn sent effort xhigh while the record
    said xhigh; the turn after set_session_effort max sent max). A switch that lands after this turn started but before
    its step 0 reads the record would read the new value while this turn runs on the old one."""
    def scan(chunk: bytes) -> dict:
        last = {}
        for raw in chunk.split(b"\n"):
            if b'"api-request"' not in raw:
                continue
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(e, dict) or e.get("type") != "api-request":
                continue
            if e.get("querySource") not in MAIN_QUERY_SOURCES:  # a side call (another model) would not be this turn
                continue
            p = e.get("params") if isinstance(e.get("params"), dict) else {}
            oc = p.get("output_config") if isinstance(p.get("output_config"), dict) else {}
            last = {"model": str(p.get("model") or ""), "effort": str(oc.get("effort") or "").lower(),
                    "at": str(e.get("timestamp") or "")}
        return last
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TURN_TAIL_BYTES:
                fh.seek(size - TURN_TAIL_BYTES)
                fh.readline()
                hit = scan(fh.read())
                if hit or size > TURN_FULL_SCAN_MAX:
                    return hit
                fh.seek(0)
            return scan(fh.read())
    except (OSError, TypeError):
        return {}


def bare_model(m: str) -> str:
    """'claude-opus-5-5[1m]' → 'claude-opus-5-5' (the context-size suffix is not another model)."""
    return re.sub(r"\[[^\]]*\]$", "", (m or "").strip())


def expect_report(row: dict, want_model: str, want_effort: str) -> tuple[int, str]:
    """(exit, text) of a worker's step 0: do the app's record (the next turn's values) and this turn (what the CLI sent
    to the API, `turn_model` / `turn_effort` from this_turn; the transcript's model when no API request is logged) match
    what the hand-off asked for? On a mismatch the text carries the SendMessage line to the session that started this
    one (the app's record names it), with the time it was written (a held message can arrive after the `go`)."""
    got_m, got_e = row.get("app_model") or "", (row.get("app_effort") or "").lower()
    turn_m = bare_model(row.get("turn_model") or row.get("model") or "")
    turn_e = (row.get("turn_effort") or "").lower()
    asked = " / ".join(x for x in (want_model, f"effort {want_effort}" if want_effort else "") if x)
    if not (got_m or got_e):
        diffs = ["app の記録が読めない"]
    else:
        diffs = [] if matches(want_model, got_m) else [f"model {got_m or '?'}"]
        if want_effort and want_effort.lower() != got_e:
            diffs.append(f"effort {got_e or '?'}")
    turn_diffs = [] if not turn_m or matches(want_model, turn_m) else [f"model {turn_m}"]
    if want_effort and turn_e and want_effort.lower() != turn_e:
        turn_diffs.append(f"effort {turn_e}")
    now_txt = (f"、 この turn に API へ送った値 ({turn_m or '?'} / effort {turn_e})" if turn_e else "")
    if not diffs and not turn_diffs:
        return 0, f"✅ app の記録 ({got_m} / effort {got_e}){now_txt} は頼まれた {asked} と合う = 手順 1 へ進む"
    me = row.get("app_local") or row.get("host") or str(row.get("sessionId", ""))[:8]
    parent = row.get("app_parent") or ""
    stamp = time.strftime("%H:%M")
    if not diffs:
        # the record already holds the asked values (the starter switched it after this turn began): the next turn runs on
        # them, so the starter only sends `go`
        line = (f"go 待ち ({stamp} 時点): この窓 ({me}) のこの turn は {' / '.join(turn_diffs)} で動いている (API に送った値)。"
                f" app の記録は頼まれた {asked} に直っている = 次の turn から合う。 依頼の中身はまだ読んでいない。 go を送ってください"
                " (set_session_model / set_session_effort は済んでいる。 この 1 行より後に go を送っていれば、 この 1 行は読み捨てる)。")
        out = [f"⏸ この turn は {' / '.join(turn_diffs)} で動いている (API に送った値)。 app の記録は頼まれた {asked} に直っている"
               " = 次の turn から合う。 依頼の中身を読まずにこの turn を止め、 go で次の turn を始める。"]
    else:
        line = (f"go 待ち ({stamp} 時点): この窓 ({me}) は app の記録で {' / '.join(diffs)}、 頼まれたのは {asked}。 依頼の中身はまだ"
                " 読んでいない。 set_session_model / set_session_effort で直してから go を送ってください (この 1 行より後に直して"
                " go を送っていれば、 この 1 行は読み捨てる)。")
        out = [f"⏸ app の記録が頼まれた {asked} と違う ({' / '.join(diffs)}) = 依頼の中身を読まずに止まる。"]
    if parent:
        out.append("  止まる前に、 起こした session へ次の 1 行を SendMessage で送る (起こした側のほかの子が動いていると、"
                   " この窓の turn の終わりでは起こした側が起きない。 message は起こす = 実測):")
        out.append(f'  SendMessage(to={parent}, message="{line}")')
    else:
        out.append("  起こした session が app の記録に無い = 止まると 1 行で言うだけ。")
    return 4, "\n".join(out)


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
        # every config dir on the machine: a session registered under ~/.claude-<x> is live too, with its address
        home = os.path.join(td, "home")
        for cfg in (".claude", ".claude-alpha"):
            os.makedirs(os.path.join(home, cfg, "sessions"))
            os.makedirs(os.path.join(home, cfg, "projects", "-w-p"))
        sid3, sid4 = str(uuid.uuid4()), str(uuid.uuid4())
        for cfg, s, pidfile in ((".claude", sid3, "11.json"), (".claude-alpha", sid4, "12.json")):
            with open(os.path.join(home, cfg, "sessions", pidfile), "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "sessionId": s, "cwd": "/w/p", "name": f"in {cfg}",
                           "messagingSocketPath": f"/tmp/cc-socks/{pidfile[:2]}.sock"}, fh)
            with open(os.path.join(home, cfg, "projects", "-w-p", f"{s}.jsonl"), "w", encoding="utf-8") as fh:
                fh.write(line("assistant", "claude-opus-5-5", "t1") + "\n")
        for k in ("CLAUDE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR"):
            os.environ.pop(k, None)
        os.environ["CLAUDE_CONFIG_DIRS_HOME"] = home
        live = {s["sessionId"]: s for s in sm.live_sessions()}
        check("a session in another config dir (~/.claude-<x>) is live", sid4 in live and sid3 in live)
        check("live rows carry the config label and the socket address",
              live.get(sid4, {}).get("config") == "alpha" and live.get(sid4, {}).get("address") == "uds:/tmp/cc-socks/12.sock"
              and live.get(sid3, {}).get("config") == "default")
        check("live_address finds a session by prefix in any config dir",
              (sm.live_address(sid4[:8]) or {}).get("address") == "uds:/tmp/cc-socks/12.sock" and sm.live_address("short") is None)
        check("the model of a session in another config dir is read from its own transcript", sm.model_of(sid4, "/w/p") == "claude-opus-5-5")
        env2 = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR")}
        r = subprocess.run([sys.executable, me, sid4[:8]], env=env2, capture_output=True, text=True)
        check("CLI prints the config and the SendMessage address", r.returncode == 0 and "config=alpha" in r.stdout
              and "SendMessage to=uds:/tmp/cc-socks/12.sock" in r.stdout)
        os.environ.pop("CLAUDE_CONFIG_DIRS_HOME", None)
        # --expect-*: a worker's step 0 against the app's record
        base = {"sessionId": sid, "host": "local_me", "app_local": "local_me", "app_parent": "local_dad"}
        rc, out = expect_report({**base, "app_model": "claude-opus-5-5", "app_effort": "max"}, "opus", "max")
        check("expect: a tier word matches the record's model and the effort matches → ✅ exit 0", rc == 0 and out.startswith("✅"))
        rc, out = expect_report({**base, "app_model": "claude-opus-5-5", "app_effort": "xhigh"}, "opus", "max")
        check("expect: the effort differs → ⏸ exit 4 with the SendMessage line to the starter",
              rc == 4 and "SendMessage(to=local_dad" in out and "effort xhigh" in out and "opus / effort max" in out)
        rc, out = expect_report({**base, "app_model": "claude-opus-5-5", "app_effort": "max"}, "claude-fable-5-1", "max")
        check("expect: a full model id differs → ⏸ naming the model", rc == 4 and "model claude-opus-5-5" in out)
        rc, out = expect_report({**base, "app_parent": "", "app_model": "claude-opus-5-5", "app_effort": "high"}, "opus", "max")
        check("expect: no starter on record → ⏸ without a SendMessage line", rc == 4 and "SendMessage(" not in out)
        rc, out = expect_report({"sessionId": sid, "app_model": "", "app_effort": ""}, "opus", "max")
        check("expect: no app record → ⏸ (cannot confirm = stop)", rc == 4 and "読めない" in out)
        check("expect: no effort asked → the model alone decides",
              expect_report({**base, "app_model": "claude-opus-5-5", "app_effort": "high"}, "opus", "")[0] == 0)
        r = subprocess.run([sys.executable, me, "local_zzz", "--expect-model", "opus"], env=env, capture_output=True, text=True)
        check("CLI --expect-* with nothing matched → exit 4 (stop)", r.returncode == 4)
        adir = os.path.join(td, "app", "acct", "env")
        os.makedirs(adir)
        with open(os.path.join(adir, "local_aaa.json"), "w", encoding="utf-8") as fh:
            json.dump({"sessionId": "local_aaa", "cliSessionId": sid, "model": "claude-opus-5-5", "effort": "xhigh",
                       "spawnedFrom": {"sessionId": "local_starter", "taskId": "task_0000aaaa"}}, fh)
        os.environ["CLAUDE_DESKTOP_SESSIONS_DIR"] = os.path.join(td, "app")
        st = with_starter({"sessionId": sid, "host": "local_aaa"})
        check("with_starter: the app's record names the starter and this window's local id",
              st.get("app_parent") == "local_starter" and st.get("app_local") == "local_aaa")
        check("with_starter: no app record → the row unchanged", with_starter({"sessionId": "x", "host": "local_none"}).get("app_parent") == "")
        # this turn = what the CLI sent to the API; the record = the next turn (a switch can land in between)
        rc, out = expect_report({**base, "app_model": "claude-opus-5-5", "app_effort": "max", "turn_model": "claude-opus-5-5",
                                 "turn_effort": "xhigh"}, "opus", "max")
        check("expect: record fixed but this turn sent xhigh → ⏸ asking only for go, with the time",
              rc == 4 and "go を送ってください" in out and "直っている" in out and "SendMessage(to=local_dad" in out
              and "時点" in out and "effort xhigh" in out)
        rc, out = expect_report({**base, "app_model": "claude-opus-5-5", "app_effort": "max", "turn_model": "claude-opus-5-5[1m]",
                                 "turn_effort": "max"}, "opus", "max")
        check("expect: record and this turn both max → ✅ naming this turn's values", rc == 0 and "この turn に API へ送った値" in out)
        rc, out = expect_report({**base, "app_model": "claude-fable-5-1", "app_effort": "high", "model": "claude-opus-5-5"},
                                "claude-fable-5-1", "high")
        check("expect: record switched to Fable but this turn ran Opus (no API log) → ⏸ on the transcript's model",
              rc == 4 and "model claude-opus-5-5" in out)
        rc, out = expect_report({**base, "app_model": "claude-opus-5-5", "app_effort": "xhigh", "turn_effort": "xhigh"}, "opus", "max")
        check("expect: record and this turn xhigh → ⏸ asking to set then go, the line says when it was written",
              rc == 4 and "直してから go" in out and "時点" in out and "読み捨てる" in out)
        tt = os.path.join(pdir, "-w-p", "turns.jsonl")
        with open(tt, "w", encoding="utf-8") as fh:
            for src, eff in (("sdk", "xhigh"), ("sdk", "max"), ("some_side_call", "low")):
                fh.write(json.dumps({"type": "api-request", "querySource": src, "timestamp": "t", "params": {
                    "model": "claude-opus-5-5", "output_config": {"effort": eff}}}) + "\n")
        check("this_turn: the last main request wins, a side call is skipped", this_turn(tt).get("effort") == "max")
        check("this_turn: no api-request / no file → {}", this_turn(tr) == {} and this_turn(os.path.join(td, "none")) == {})
        check("bare_model drops the context-size suffix", bare_model("claude-opus-5-5[1m]") == "claude-opus-5-5")
        # the CLI's step 0 on itself reads this turn from its own transcript
        with open(tr, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "api-request", "querySource": "sdk", "timestamp": "t4",
                                 "params": {"model": "claude-opus-5-5", "output_config": {"effort": "xhigh"}}}) + "\n")
        env3 = dict(env, CLAUDE_CODE_SESSION_ID=sid, CLAUDE_DESKTOP_SESSIONS_DIR=os.path.join(td, "app"))
        r = subprocess.run([sys.executable, me, "self", "--expect-model", "opus", "--expect-effort", "xhigh"], env=env3,
                           capture_output=True, text=True)
        check("CLI self --expect-*: record and this turn xhigh → ✅ exit 0 naming this turn",
              r.returncode == 0 and "この turn の API=claude-opus-5-5 effort=xhigh" in r.stdout and "✅" in r.stdout)
        r = subprocess.run([sys.executable, me, "self", "--expect-model", "opus", "--expect-effort", "max"], env=env3,
                           capture_output=True, text=True)
        check("CLI self --expect-effort max on an xhigh record and turn → exit 4 with the line to the starter",
              r.returncode == 4 and "SendMessage(to=local_starter" in r.stdout)
        os.environ.pop("CLAUDE_DESKTOP_SESSIONS_DIR", None)
    print("session-model selftest: " + ("ALL PASS" if not fails else f"FAILED {len(fails)}"))
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("target", nargs="?", help="session id / prefix, local_… host id, or a substring of the name")
    ap.add_argument("--live", action="store_true", help="every live session on this machine")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--expect-model", default="", help="a worker's step 0: the model the hand-off asked for")
    ap.add_argument("--expect-effort", default="", help="a worker's step 0: the effort the hand-off asked for")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.live:
        rows = [sm.describe(s) for s in sm.live_sessions()]
    elif a.target:
        target = a.target
        if target == "self":  # the session running this command (Claude Code puts its id in the Bash env)
            target = os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
        rows = [sm.describe(s) for s in sm.resolve(target)]
    else:
        ap.print_help()
        return 2
    if (a.expect_model or a.expect_effort) and not a.json:
        if len(rows) != 1:
            print("(該当する session が無い・1 つに決まらない)" if not rows else "\n".join(fmt(r) for r in rows))
            print("⏸ この窓の app の記録を 1 つに決められない = 依頼の中身を読まずに止まる。")
            return 4
        row = {**rows[0], **{"turn_" + k: v for k, v in this_turn(rows[0].get("path") or "").items()}}
        print(fmt(row))
        rc, text = expect_report(with_starter(row), a.expect_model, a.expect_effort)
        print(text)
        return rc
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
