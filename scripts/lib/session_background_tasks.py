#!/usr/bin/env python3
"""session_background_tasks.py — 1 つの Claude Code session が仕掛けて今も生きている背景の作業 (Bash の run_in_background・前景から背景へ移った command・Monitor) を並べ、 見張りか・Monitor の残り秒を付ける (照合の道具 child-wrap-check.py と締めの手順 conventions/closing-sweep.md#stop-own-watches の共通の部品。 `<id|self>` で CLI)。

Why (実測): desktop app は、 session の背景の作業が生きている間はその session の archive を断る。 断りの文は
「agent の作業・Remote Control・配達待ちの message・背景の作業」 を並べるだけで、 どれかを言わない。 背景の作業を
session の記憶で数えると漏れる (Monitor は turn が終わっても期限まで生き、 期限が来ると session を起こす。 閉じた依頼に
仕掛けた掲示板の watch は何時間も終わらない)。 親が照合の道具で「畳んでよい」 と読んだ直後に app が断る食い違いの元。

How:
  - 生きている作業 = session の engine の process (live の registry の pid) の直下の shell
    (`<sh> -c source …/shell-snapshots/snapshot-…`)。 MCP の server も直下に並ぶが形が違う。 呼んだ側の process の
    祖先 (前景で走っているこの command) は数えない。
  - 名前 = 会話記録: Bash の結果「Command running in background with ID: <id>」「moved to the background (ID: <id>)」、
    Monitor の結果「Monitor started (task <id>, expires in …|timeout <n>ms|persistent …)」。 終わり = task の知らせの
    <status> (completed / failed / killed / stopped) と TaskStop の「Successfully stopped task: <id>」。
  - shell と作業の対応: shell の fd 1 が `tasks/<id>.output` (背景の Bash は生きている間開いている。 前景の command も
    同じ形で開く = 会話記録に背景の記録が無ければ前景)。 Monitor の file は終わるまで作られない = shell の
    `eval '<command>'` を Monitor の command と照合する。
  - 見張り = Monitor と、 command の形が WATCH_FORMS (掲示板の watch・touching --wait、 照合の --wait / --wait-due、
    起動の確かめの --wait-first-turn) のもの (引用符の中の語は見ない)。 ほかは計算などとして「止めない」 側に出す。
  - session が turn の途中 (registry の status が busy / waiting) なら、 会話記録に背景の記録の無い shell (= 前景の
    command) は数えない。
読めないとき (ps・lsof が無い、 registry に pid が無い) は None = 「無い」 と言わない。 見ないもの: subagent の背景・
workflow・cron の予約・Remote Control (app は数えるが engine 直下の shell にならない or 形を確かめていない)。
Usage:
  session_background_tasks.py <self|local_…|transcript id> [--json]
      exit 0 = 生きている背景の作業なし / 1 = ある (見張りには TaskStop の 1 行が付く) / 2 = 数えられない
  session_background_tasks.py --selftest
"""
from __future__ import annotations

import calendar
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import session_model as sm  # noqa: E402

START_BG = re.compile(r"Command running in background with ID: (\w+)")
MOVED_BG = re.compile(r"moved to the background \(ID: (\w+)\)")
MON_START = re.compile(r"Monitor started \(task (\w+), ([^)]*)\)")
NOTE_BLOCK = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
NOTE_ID = re.compile(r"<task-id>(\w+)</task-id>")
NOTE_END = re.compile(r"<status>(completed|failed|killed|stopped)</status>")
STOPPED = re.compile(r"Successfully stopped task: (\w+)")
SHELL = re.compile(r"^(?:\S*/)?(?:zsh|bash|sh)\s+-c\s+.*shell-snapshots/snapshot-", re.S)
EVAL_BODY = re.compile(r"\beval '((?:[^']|'\\'')*)'")
QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
# The watches this layer's tools start (the same command segment; quoted strings are blanked first, so a summary that
# says "watch" is not one). A Monitor is always a watch.
WATCH_FORMS = (
    re.compile(r"\bboard\.py\b[^\n|;&]*?\swatch(?:\s|$)"),
    re.compile(r"\bboard\.py\b[^\n|;&]*?\stouching\b[^\n|;&]*?\s--wait\b"),
    re.compile(r"\bchild-wrap-check\.py\b[^\n|;&]*?\s--wait(?:-due)?\b"),
    re.compile(r"\bsession-launch-check\.py\b[^\n|;&]*?\s--wait-first-turn\b"),
)
SOON_S = 60  # a watch that expires within this many seconds: wait instead of asking anyone to stop it


def _epoch(ts: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError):
        return 0.0


def _duration(spec: str) -> tuple[float | None, bool]:
    """(seconds, persistent) from the Monitor start's parenthesis: 'expires in 4m 30s …' / 'timeout 15000ms' / 'persistent …'."""
    s = (spec or "").strip()
    if s.startswith("persistent"):
        return None, True
    m = re.match(r"timeout (\d+)ms", s)
    if m:
        return int(m.group(1)) / 1000, False
    m = re.match(r"expires in ((?:\d+\s*[hms]\s*)+)", s)
    if m:
        unit = {"h": 3600, "m": 60, "s": 1}
        return float(sum(int(n) * unit[u] for n, u in re.findall(r"(\d+)\s*([hms])", m.group(1)))), False
    return None, False


def _texts(e: dict) -> list[str]:
    """Texts of one transcript entry where a task notification can arrive (not tool results, not the assistant)."""
    out = []
    a = e.get("attachment")
    if isinstance(a, dict) and isinstance(a.get("prompt"), str):
        out.append(a["prompt"])
    if isinstance(e.get("content"), str):
        out.append(e["content"])
    if e.get("type") == "user":
        c = (e.get("message") or {}).get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out += [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
    return out


def _result_text(b: dict) -> str:
    c = b.get("content")
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
    return str(c or "")


def scan_transcript(path: str) -> dict[str, dict]:
    """task id -> {kind: bash|monitor, command, description, started (ISO), expires_at (epoch|None), persistent, ended}."""
    uses: dict[str, dict] = {}
    tasks: dict[str, dict] = {}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return tasks
    with fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            ts = str(e.get("timestamp") or "")
            content = (e.get("message") or {}).get("content")
            if e.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        uses[str(b.get("id") or "")] = {"name": str(b.get("name") or ""), "input": b.get("input") or {}}
                continue
            if e.get("type") == "user" and isinstance(content, list):
                for b in content:
                    if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                        continue
                    text, use = _result_text(b), uses.get(str(b.get("tool_use_id") or ""), {})
                    inp = use.get("input") or {}
                    m = START_BG.search(text) or MOVED_BG.search(text)
                    if m and use.get("name") == "Bash":
                        tasks[m.group(1)] = {"kind": "bash", "command": str(inp.get("command") or ""),
                                             "description": str(inp.get("description") or ""), "started": ts,
                                             "expires_at": None, "persistent": False, "ended": ""}
                    m = MON_START.search(text)
                    if m and use.get("name") == "Monitor":
                        dur, persistent = _duration(m.group(2))
                        tasks[m.group(1)] = {"kind": "monitor", "command": str(inp.get("command") or ""),
                                             "description": str(inp.get("description") or ""), "started": ts,
                                             "expires_at": (_epoch(ts) + dur) if dur is not None and ts else None,
                                             "persistent": persistent, "ended": ""}
                    for sid in STOPPED.findall(text) if use.get("name") == "TaskStop" else []:
                        if sid in tasks:
                            tasks[sid]["ended"] = ts or "stopped"
            for t in _texts(e):
                for blk in NOTE_BLOCK.findall(t):
                    if NOTE_END.search(blk):
                        for sid in NOTE_ID.findall(blk):
                            if sid in tasks:
                                tasks[sid]["ended"] = ts or "ended"
    return tasks


def _ps() -> dict[int, dict] | None:
    try:
        out = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    procs = {}
    for ln in out.splitlines():
        parts = ln.strip().split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = {"ppid": int(parts[1]), "command": parts[2] if len(parts) > 2 else ""}
    return procs


def _stdout_files(pids: list[int]) -> dict[int, str]:
    """pid -> the path its fd 1 writes to (lsof); {} when lsof is missing."""
    if not pids:
        return {}
    try:
        out = subprocess.run(["lsof", "-a", "-d", "1", "-Fn", "-p", ",".join(map(str, pids))],
                             capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    files, cur = {}, None
    for ln in out.splitlines():
        if ln.startswith("p") and ln[1:].isdigit():
            cur = int(ln[1:])
        elif ln.startswith("n") and cur is not None:
            files[cur] = ln[1:]
    return files


def _ancestors(procs: dict[int, dict], pid: int) -> set[int]:
    out, seen = set(), 0
    while pid in procs and seen < 64:
        out.add(pid)
        pid, seen = procs[pid]["ppid"], seen + 1
    return out


def eval_body(command: str) -> str:
    m = EVAL_BODY.search(command or "")
    return m.group(1).replace("'\\''", "'") if m else ""


def is_watch(kind: str, command: str) -> bool:
    if kind == "monitor":
        return True
    masked = QUOTED.sub(" ", command or "")
    return any(p.search(masked) for p in WATCH_FORMS)


def _session_row(target: str) -> dict | None:
    t = (target or "").strip()
    if t == "self":
        t = os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    if not t:
        return None
    try:
        rows = [r for r in sm.resolve(t) if r.get("pid")]
    except Exception:
        return None
    return rows[0] if len(rows) == 1 else None


def list_tasks(target: str = "", *, row: dict | None = None, path: str | None = None, procs: dict | None = None,
               files: dict | None = None, now: float | None = None, me: int | None = None) -> list[dict] | None:
    """The session's live background work: [{id, kind, what, watch, expires_in, persistent, pid, note}], None = cannot count.
    `row` / `path` / `procs` / `files` / `me` are for tests (default: the live registry, ps, lsof, this process)."""
    row = row or _session_row(target)
    if not row or not isinstance(row.get("pid"), int):
        return None
    procs = _ps() if procs is None else procs
    if procs is None:
        return None
    now = time.time() if now is None else now
    path = path if path is not None else (row.get("path") or sm.transcript_path(row["sessionId"]) or "")
    recorded = scan_transcript(path)
    mine = _ancestors(procs, os.getpid() if me is None else me)
    shells = [p for p, d in procs.items() if d["ppid"] == row["pid"] and p not in mine and SHELL.match(d["command"])]
    files = _stdout_files(shells) if files is None else files
    busy = str(row.get("status") or "") in ("busy", "waiting")
    out = []
    for p in sorted(shells):
        body = eval_body(procs[p]["command"])
        f = files.get(p, "")
        tid = os.path.basename(f)[:-len(".output")] if f.endswith(".output") and os.path.basename(os.path.dirname(f)) == "tasks" else ""
        rec = recorded.get(tid) if tid else None
        if rec is None and not tid:
            hits = [(k, r) for k, r in recorded.items() if r["command"].strip() and r["command"].strip() == body.strip()
                    and not r["ended"]]
            hits.sort(key=lambda kr: (kr[1]["kind"] != "monitor", kr[1]["started"]), reverse=False)
            if hits:
                tid, rec = hits[-1]
        if rec is None and busy:
            continue  # a shell with no background record while the session is mid-turn = its foreground command
        kind = rec["kind"] if rec else "bash"
        cmd = rec["command"] if rec else body
        exp = rec.get("expires_at") if rec else None
        out.append({"id": tid or f"pid {p}", "kind": kind, "pid": p,
                    "what": (rec.get("description") if rec else "") or " ".join(cmd.split())[:90],
                    "watch": is_watch(kind, cmd), "persistent": bool(rec and rec.get("persistent")),
                    "expires_in": max(0, int(exp - now)) if exp else None,
                    "note": "" if rec else "会話記録に背景の記録が無い (前景から移った command か、 記録の前に読んだ)"
                            if tid else "会話記録と照合できない shell"})
    return out


def describe(t: dict) -> str:
    kind = "Monitor" if t["kind"] == "monitor" else "Bash"
    bits = [f"{t['id']}  {kind}「{t['what']}」"]
    if t["watch"]:
        left = ("期限なし (TaskStop まで)" if t["persistent"] else f"あと {t['expires_in']} 秒で期限切れ"
                if t["expires_in"] is not None else "")
        bits.append("見張り" + (f"・{left}" if left else ""))
    else:
        bits.append("見張りでない (計算など) = 止めない")
    if t.get("note"):
        bits.append(t["note"])
    return "  ".join(bits)


def child_next_step(tasks: list[dict]) -> str:
    """The parent's next move for a child whose background work is still alive (one line)."""
    watches = [t for t in tasks if t["watch"]]
    others = [t for t in tasks if not t["watch"]]
    out = []
    if watches:
        soon = [t for t in watches if t["expires_in"] is not None and t["expires_in"] <= SOON_S]
        if len(soon) == len(watches):
            out.append(f"見張りは {max(t['expires_in'] for t in soon)} 秒以内に期限切れ = 子に message を送らずに待ってから畳む")
        else:
            ids = " ".join(t["id"] for t in watches)
            out.append(f"子に 1 通で頼む:「背景の見張り {ids} を TaskStop で止めて、 ほかは何もせず turn を終えて」"
                       " (止めた後に `--wait` で turn の終わりを待つ)")
    if others:
        out.append("見張りでない背景の作業 (" + ", ".join(t["id"] for t in others) + ") は終わるまで待つ"
                   " (動いている間は app が archive を断る。 子の報告にその名前と、 止めてよいかがあるかを見る)")
    return " / ".join(out)


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__.split("Usage:")[1].strip())
        return 2
    rows = list_tasks(args[0])
    if rows is None:
        print(f"⚠️ {args[0]} の背景の作業を数えられない (live の registry に pid が無い・1 つに決まらない、 または ps が無い) = 「無い」 とは言えない")
        return 2
    if "--json" in argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    elif not rows:
        print(f"🔎 {args[0]} の背景の作業: 生きているものは無い")
    else:
        print(f"🔎 {args[0]} の背景の作業: {len(rows)} 件が生きている")
        for t in rows:
            print("  - " + describe(t) + (f"  → TaskStop {t['id']}" if t["watch"] and not t["id"].startswith("pid ") else ""))
        if any(t["watch"] for t in rows):
            print("  見張りは TaskStop で止める。 見張りでないものは止めずに、 依頼元への報告に名前を書く")
    return 1 if rows else 0


def selftest() -> int:
    import tempfile

    fails = []

    def ok(label: str, cond: bool) -> None:
        print(("ok: " if cond else "NG: ") + label)
        if not cond:
            fails.append(label)

    def use(i: str, name: str, inp: dict, ts: str) -> str:
        return json.dumps({"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "tool_use", "id": i, "name": name, "input": inp}]}})

    def res(i: str, text: str, ts: str) -> str:
        return json.dumps({"type": "user", "timestamp": ts, "message": {"content": [
            {"type": "tool_result", "tool_use_id": i, "content": text}]}})

    def note(tid: str, status: str | None, ts: str) -> str:
        body = f"<task-notification>\n<task-id>{tid}</task-id>\n" + (f"<status>{status}</status>\n" if status else "<event>x</event>\n")
        return json.dumps({"type": "attachment", "timestamp": ts, "attachment": {"type": "queued_command", "prompt": body + "</task-notification>"}})

    watch_cmd = "python3 ~/b/board.py watch --root /r --agent claude --session s --request R1"
    calc_cmd = "python3 long_calc.py --n 9"
    mon_cmd = "until test -f /tmp/x; do sleep 5; done; echo done"
    lines = [
        use("u1", "Bash", {"command": watch_cmd, "description": "Watch the board request", "run_in_background": True}, "2026-01-01T00:00:00.000Z"),
        res("u1", "Command running in background with ID: bwatch01. Output is being written to: /t/tasks/bwatch01.output", "2026-01-01T00:00:01.000Z"),
        use("u2", "Bash", {"command": calc_cmd, "description": "Run the long calculation"}, "2026-01-01T00:00:02.000Z"),
        res("u2", "Command did not complete within its 120s timeout and was moved to the background (ID: bcalc002).", "2026-01-01T00:02:02.000Z"),
        use("u3", "Monitor", {"command": mon_cmd, "description": "wait for the file", "timeout_ms": 300000}, "2026-01-01T00:03:00.000Z"),
        res("u3", "Monitor started (task bmon0003, expires in 5m unless the source ends first; you get one notice at expiry)", "2026-01-01T00:03:00.000Z"),
        use("u4", "Monitor", {"command": "tail -f /x | grep --line-buffered E", "description": "old monitor", "timeout_ms": 60000}, "2026-01-01T00:03:10.000Z"),
        res("u4", "Monitor started (task bmon0004, expires in 1m unless the source ends first)", "2026-01-01T00:03:10.000Z"),
        note("bmon0004", "completed", "2026-01-01T00:04:10.000Z"),
        note("bmon0003", None, "2026-01-01T00:04:20.000Z"),  # an event only: the monitor keeps running
        use("u5", "Bash", {"command": "sleep 999", "description": "stopped one", "run_in_background": True}, "2026-01-01T00:05:00.000Z"),
        res("u5", "Command running in background with ID: bstop005.", "2026-01-01T00:05:01.000Z"),
        use("u6", "TaskStop", {"task_id": "bstop005"}, "2026-01-01T00:05:30.000Z"),
        res("u6", "Successfully stopped task: bstop005 (sleep 999)", "2026-01-01T00:05:31.000Z"),
        use("u7", "Bash", {"command": "python3 board.py note --summary 'we watch it later'", "run_in_background": True}, "2026-01-01T00:06:00.000Z"),
        res("u7", "Command running in background with ID: bnote007.", "2026-01-01T00:06:01.000Z"),
        use("u8", "Monitor", {"command": "sleep 20; echo ok", "description": "short probe", "timeout_ms": 45000}, "2026-01-01T00:06:30.000Z"),
        res("u8", "Monitor started (task bmon0008, expires in 45s unless the source ends first)", "2026-01-01T00:06:30.000Z"),
    ]
    with tempfile.TemporaryDirectory() as td:
        tr = os.path.join(td, "s.jsonl")
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        rec = scan_transcript(tr)
        ok("background Bash, moved-to-background Bash and Monitors are recorded", set(rec) >= {"bwatch01", "bcalc002", "bmon0003", "bmon0004", "bstop005"})
        ok("a Monitor's expiry is its start + 'expires in 5m'", rec["bmon0003"]["expires_at"] == _epoch("2026-01-01T00:03:00") + 300)
        ok("a notification with a status ends the task", bool(rec["bmon0004"]["ended"]))
        ok("an event-only notification does not end the monitor", rec["bmon0003"]["ended"] == "")
        ok("TaskStop's success ends the task", bool(rec["bstop005"]["ended"]))
        ok("durations: '4m 30s' / 'timeout 15000ms' / persistent", _duration("expires in 4m 30s unless") == (270.0, False)
           and _duration("timeout 15000ms") == (15.0, False) and _duration("persistent — runs until TaskStop") == (None, True))

        def sh(body: str) -> str:
            return ("/bin/zsh -c source /h/.claude/shell-snapshots/snapshot-zsh-1-x.sh 2>/dev/null || true && eval '"
                    + body.replace("'", "'\\''") + "' < /dev/null && pwd -P >| /tmp/claude-1-cwd")
        procs = {
            100: {"ppid": 1, "command": "claude --output-format stream-json"},
            201: {"ppid": 100, "command": sh(watch_cmd)},
            202: {"ppid": 100, "command": sh(calc_cmd)},
            203: {"ppid": 100, "command": sh(mon_cmd)},
            204: {"ppid": 100, "command": "node /x/server.mjs"},
            205: {"ppid": 100, "command": sh("git status")},          # a foreground command (no background record)
            206: {"ppid": 100, "command": sh("python3 me.py")},       # this process's own shell (an ancestor)
            207: {"ppid": 206, "command": "python3 me.py"},
            208: {"ppid": 100, "command": sh("python3 board.py note --summary 'we watch it later'")},
            209: {"ppid": 100, "command": sh("sleep 20; echo ok")},
        }
        files = {201: "/t/tasks/bwatch01.output", 202: "/t/tasks/bcalc002.output", 205: "/t/tasks/bfg00005.output",
                 206: "/t/tasks/bme00006.output", 208: "/t/tasks/bnote007.output"}
        now = _epoch("2026-01-01T00:07:00")
        idle = {"sessionId": "s", "pid": 100, "status": "idle"}
        got = list_tasks(row=idle, path=tr, procs=procs, files=files, now=now, me=207)
        by = {t["id"]: t for t in got or []}
        ok("the board watch is a watch", by.get("bwatch01", {}).get("watch") is True)
        ok("the moved-to-background calculation is not a watch", by.get("bcalc002", {}).get("watch") is False)
        ok("the Monitor (no file) is matched by its command, with seconds left",
           by.get("bmon0003", {}).get("kind") == "monitor" and by["bmon0003"]["expires_in"] == 60)
        ok("an MCP server is not a background task", not any(t["pid"] == 204 for t in got))
        ok("this command's own shell is not counted", not any(t["pid"] == 206 for t in got))
        ok("'watch' inside a quoted summary is not a watch", by.get("bnote007", {}).get("watch") is False)
        ok("an idle session's shell with no record is still listed (with a note)", any(t["pid"] == 205 and t["note"] for t in got))
        busy = dict(idle, status="busy")
        got_b = list_tasks(row=busy, path=tr, procs=procs, files=files, now=now, me=207)
        ok("a busy session's foreground command is not counted", not any(t["pid"] == 205 for t in got_b or []))
        ok("a busy session's background tasks are still counted", {"bwatch01", "bcalc002", "bmon0003"} <= {t["id"] for t in got_b or []})
        ok("no registry pid = cannot count (None), not 'none'", list_tasks(row={"sessionId": "s", "status": "idle"}, path=tr, procs=procs, files=files) is None)
        step = child_next_step([by["bwatch01"], by["bcalc002"]])
        ok("next step names the watch to stop and says to wait for the calculation", "bwatch01" in step and "TaskStop" in step
           and "bcalc002" in step and "終わるまで待つ" in step)
        soon = list_tasks(row=idle, path=tr, procs={100: procs[100], 209: procs[209]}, files={}, now=_epoch("2026-01-01T00:07:00"), me=1)
        ok("a short probe Monitor (45 s) about to expire = wait, no message",
           len(soon or []) == 1 and soon[0]["expires_in"] == 15 and "待ってから畳む" in child_next_step(soon))
        ok("describe says how long a watch has left", "あと 60 秒" in describe(by["bmon0003"]))
    print(("selftest: FAIL " + ", ".join(fails)) if fails else "selftest: all pass")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
