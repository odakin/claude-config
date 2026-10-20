#!/usr/bin/env python3
"""busy-worker-stop-check.py — 動いている (busy) worker session を止める操作 (`claude stop|kill|rm <id>`、 desktop の stop_session / archive_session) を、 本人に聞く前の 1 回目は止める (hook の engine。 正本 = conventions/multi-session-coordination.md#ask-before-stopping-a-busy-worker)。

Why (実測): 見え方や model を直すために、 動いている worker を止めて起こし直すと、 止めた worker が読み込みに使った分の
使用料がそのまま無駄になる (起こし直した session は同じ読み込みをもう一度やる)。 止めた worker の記録は残り、
`claude --resume <id>` や attach で続きを出せる = 止めずに済む道がたいてい在る。 止めるかは費用を払う本人が決める。
止める側の session は「直したい」 気持ちで動いているので、 散文の規則だけでは手が先に出る。

述語:
  - Bash: command に `claude … stop|kill|rm` がある → command の中の session id らしい語 (8 桁以上の 16 進) を全部拾い、
    live の registry (全 config dir、 scripts/lib/session_model.py) で status = busy のものだけを対象にする
    (for 文の id の並びも拾う。 終わって idle の worker の片付けは止めない)。
  - mcp `…__stop_session` / `…__archive_session`: tool_input.session_id (`local_…` か transcript id) の status が busy なら対象。
  - 対象があれば、 その target について「止めた時刻」 を session ごとの state に記録して止める (exit 2、 理由に model と
    動いた時間 = 本人に聞く 1 行の材料)。 止めた時刻より後に本人の発言 (人の入力。 他 session からの message・hook の
    差し戻し・task の通知は数えない) があれば通す = 聞いて答えをもらった後の 2 回目は通る。
  - Bash だけ: 本人が直前の発言で止めるよう明示に言ったなら、 command に `# stop-ok: <本人の発言の一部を逐語で>` を
    付けると、 その文字列が本人の最新の発言に在る時に限って 1 回目から通す (逐語でなければ通さない)。

故障は通す (読めない入力・registry が読めない・例外 = exit 0)。
env: BUSY_WORKER_STOP_CHECK_DISABLE=1 / BUSY_WORKER_STOP_STATE_DIR (test) / CLAUDE_SESSIONS_DIR・CLAUDE_PROJECTS_DIR (test)。
self-test: python3 scripts/busy-worker-stop-check.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import session_model as sm  # noqa: E402

RULE = "claude-config/conventions/multi-session-coordination.md#ask-before-stopping-a-busy-worker"
CLI_STOP = re.compile(r"\bclaude\b[^|;&\n]*?\b(stop|kill|rm)\b")   # cheap prefilter only; the command word decides
# The command word is read after heredoc bodies and quoted strings are blanked (the same reading as
# hooks/cd-git-write-guard.py): text that only mentions `claude stop <id>` (an echo, a commit message, a document
# written through a heredoc) is not a stop (measured: a heredoc that quoted the words was stopped).
QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SEP = re.compile(r"&&|\|\||;|\||&|\(|\)|\n")
LEADING_KW = {"do", "then", "else", "elif", "if", "while", "until", "{", "!", "time", "command", "builtin", "exec", "env", "nohup"}
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
ID_TOKEN =re.compile(r"(?<![0-9a-zA-Z_-])([0-9a-f]{8}(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?)(?![0-9a-zA-Z_])")
STOP_OK = re.compile(r"#\s*stop-ok:\s*(.+?)\s*$", re.M)
NOT_HUMAN = ("<task-notification", "<cross-session-message", "Another Claude session sent a message", "Stop hook feedback",
             "<local-command", "<command-name>", "<command-message>", "<side-sessions-event", "[Request interrupted")
TAIL_BYTES = 512 * 1024


def state_dir() -> str:
    return os.environ.get("BUSY_WORKER_STOP_STATE_DIR") or os.path.expanduser("~/.claude/state/busy-worker-stop")


def _state_path(sid: str) -> str:
    return os.path.join(state_dir(), re.sub(r"[^A-Za-z0-9_.-]", "_", sid or "unknown") + ".json")


def load_state(sid: str) -> dict:
    try:
        with open(_state_path(sid), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(sid: str, d: dict) -> None:
    os.makedirs(state_dir(), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state_dir(), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, _state_path(sid))


def _human_text(e: dict) -> str:
    """The text of a person's prompt in one transcript entry, '' for anything else."""
    a = e.get("attachment")
    if isinstance(a, dict):
        if a.get("type") == "queued_command" and (a.get("origin") or {}).get("kind") == "human":
            p = a.get("prompt")
            if isinstance(p, list):
                p = " ".join(x.get("text", "") for x in p if isinstance(x, dict) and x.get("type") == "text"
                             and "<system-reminder>" not in x.get("text", ""))
            return str(p or "")
        return ""
    if e.get("type") != "user" or e.get("isMeta"):
        return ""
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return ""
        c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
                     and not b.get("text", "").lstrip().startswith("<system-reminder>"))
    if not isinstance(c, str):
        return ""
    t = c.strip()
    if not t or any(t.startswith(x) or x in t[:200] for x in NOT_HUMAN):
        return ""
    return t


def last_human(path: str) -> tuple[str, str]:
    """(timestamp, text) of the person's latest prompt in a transcript, ('', '') when none is found."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return "", ""
    best = ("", "")
    for line in raw.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        t = _human_text(e)
        ts = str(e.get("timestamp") or "")
        if t and ts >= best[0]:
            best = (ts, t)
    return best


def busy_targets(ids: list[str]) -> list[dict]:
    out, seen = [], set()
    for t in ids:
        try:
            rows = sm.resolve(t)
        except Exception:
            rows = []
        for r in rows:
            if r.get("status") != "busy" or r["sessionId"] in seen:
                continue
            seen.add(r["sessionId"])
            try:
                d = sm.describe(r)
            except Exception:
                d = r
            out.append(d)
    return out


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def stops_a_session(cmd: str) -> bool:
    """Whether a segment of the command runs `claude … stop|kill|rm` (the command word is `claude` or a path to it,
    after variable assignments and control words; heredoc bodies and quoted strings do not count)."""
    masked = QUOTED.sub(_blank, HEREDOC.sub(_blank, cmd))
    for seg in SEP.split(masked):
        words = seg.split()
        while words and (words[0] in LEADING_KW or ASSIGN.match(words[0])):
            words = words[1:]
        if not words or os.path.basename(words[0]) != "claude":
            continue
        sub = next((w for w in words[1:] if not w.startswith("-")), "")
        if sub in ("stop", "kill", "rm"):
            return True
    return False


def targets_of(inp: dict) -> tuple[list[str], str]:
    tool, ti = inp.get("tool_name") or "", inp.get("tool_input") or {}
    if tool == "Bash":
        cmd = ti.get("command") or ""
        if not CLI_STOP.search(cmd) or not stops_a_session(cmd):
            return [], ""
        masked = HEREDOC.sub(_blank, cmd)   # ids in a for-loop list count; ids inside a heredoc body do not
        return [m.group(1) for m in ID_TOKEN.finditer(masked)], cmd
    if tool.endswith("__stop_session") or tool.endswith("__archive_session"):
        s = (ti.get("session_id") or "").strip()
        return ([s] if s and s != "self" else []), ""
    return [], ""


def _minutes_since(row: dict) -> str:
    started = None
    import glob
    for sdir in sm.sessions_dirs():
        for p in glob.glob(os.path.join(sdir, "*.json")):
            try:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d.get("sessionId") == row.get("sessionId"):
                started = d.get("startedAt")
                break
        if started is not None:
            break
    if not isinstance(started, (int, float)):
        return ""
    return f"{max(0, int((time.time() * 1000 - started) / 60000))} 分前に起動"


def check(inp: dict) -> tuple[int, str]:
    ids, cmd = targets_of(inp)
    if not ids:
        return 0, ""
    busy = busy_targets(ids)
    if not busy:
        return 0, ""
    sid = inp.get("session_id") or ""
    st = load_state(sid)
    h_ts, h_text = last_human(inp.get("transcript_path") or "")
    m = STOP_OK.search(cmd) if cmd else None
    if m and m.group(1).strip() and h_text and m.group(1).strip() in h_text:
        return 0, ""
    pending = [b for b in busy if not (st.get(b["sessionId"]) and h_ts and h_ts > st[b["sessionId"]])]
    if not pending:
        for b in busy:
            st.pop(b["sessionId"], None)
        save_state(sid, st)
        return 0, ""
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    for b in pending:
        st.setdefault(b["sessionId"], now)
    save_state(sid, st)
    lines = []
    for b in pending:
        bits = [b.get("model") or "model 不明", _minutes_since(b), b.get("name") or ""]
        lines.append(f"  - {b['sessionId'][:8]}: " + " / ".join(x for x in bits if x))
    return 2, ("🛑 busy-worker-stop-check: 動いている worker を止める操作なので、 本人に聞く前の 1 回目は止めた。\n"
               + "\n".join(lines) + "\n"
               "  止めると、 その worker が読み込みに使った分の使用料が無駄になる (起こし直すと同じ読み込みをもう一度やる)。"
               " 見え方を変えたいだけなら止めずに済む道がある (記録は残る = `claude attach <id>` / `claude --resume <id>`)。\n"
               "  本人に 1 行で聞く: 何を (上の model と動いた時間)、 なぜ止めたいか、 止めずに済む道。 本人が答えた後なら同じ操作は通る。\n"
               "  本人が直前の発言で止めるよう明示に言っているなら、 Bash の command に `# stop-ok: <その発言の一部を逐語で>` を付けて打ち直す。"
               f" 規約 = {RULE}")


def main() -> int:
    if os.environ.get("BUSY_WORKER_STOP_CHECK_DISABLE") == "1":
        return 0
    try:
        inp = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    if inp.get("hook_event_name") not in (None, "", "PreToolUse"):
        return 0
    try:
        rc, txt = check(inp)
    except Exception:
        return 0  # fail-open
    if rc == 2:
        sys.stderr.write(txt + "\n")
    return rc


def selftest() -> int:
    import uuid

    fails = []

    def ok(label: str, cond: bool) -> None:
        print(("ok: " if cond else "NG: ") + label)
        if not cond:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        sdir, pdir, stdir = (os.path.join(td, x) for x in ("sessions", "projects", "state"))
        os.makedirs(sdir)
        os.makedirs(os.path.join(pdir, "-w"))
        os.environ.update(CLAUDE_SESSIONS_DIR=sdir, CLAUDE_PROJECTS_DIR=pdir, BUSY_WORKER_STOP_STATE_DIR=stdir)
        busy_id, idle_id = "b0b0b0b0-0000-4000-8000-00000000000b", "a0a0a0a0-0000-4000-8000-00000000000a"
        for n, (sid_, status) in enumerate(((busy_id, "busy"), (idle_id, "idle"))):
            with open(os.path.join(sdir, f"{n}.json"), "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "sessionId": sid_, "cwd": "/w", "name": f"worker {n}", "status": status,
                           "hostSessionId": f"local_{n:08d}-0000-4000-8000-000000000000", "startedAt": int(time.time() * 1000) - 6 * 60000}, fh)
        with open(os.path.join(pdir, "-w", busy_id + ".jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"model": "claude-fable-5-1"}, "timestamp": "t"}) + "\n")
        tr = os.path.join(td, "launcher.jsonl")

        def transcript(*rows: tuple[str, str]) -> None:
            with open(tr, "w", encoding="utf-8") as fh:
                for ts, text in rows:
                    fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}, "timestamp": ts}, ensure_ascii=False) + "\n")

        def run(tool: str, ti: dict, sid: str = "L") -> tuple[int, str]:
            return check({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "session_id": sid, "transcript_path": tr})

        transcript(("2026-01-01T00:00:00.000Z", "worker が見えない"))
        cmd = "CLAUDE_CONFIG_DIR=/x claude stop b0b0b0b0 2>&1 | tail -1"
        rc, txt = run("Bash", {"command": cmd})
        ok("busy worker, no answer yet → blocked with model and minutes", rc == 2 and "claude-fable-5-1" in txt and "分前に起動" in txt)
        rc, _ = run("Bash", {"command": cmd})
        ok("second try with no new human prompt → still blocked", rc == 2)
        transcript(("2026-01-01T00:00:00.000Z", "x"), ("2099-01-01T00:00:00.000Z", "うん、止めていいよ"))
        rc, _ = run("Bash", {"command": cmd})
        ok("after the person answered → passes", rc == 0)
        rc, _ = run("Bash", {"command": "for id in a0a0a0a0 c0c0c0c0; do claude stop $id; done"}, sid="L2")
        ok("finished idle workers in a loop → passes (cleanup)", rc == 0)
        rc, _ = run("Bash", {"command": "for id in a0a0a0a0 b0b0b0b0; do claude stop $id; done"}, sid="L3")
        ok("a busy one among the loop's ids → blocked", rc == 2)
        transcript(("2026-01-01T00:00:00.000Z", "その worker は止めて"))
        rc, _ = run("Bash", {"command": cmd + "  # stop-ok: その worker は止めて"}, sid="L4")
        ok("stop-ok quoting the person's latest words → passes", rc == 0)
        rc, _ = run("Bash", {"command": cmd + "  # stop-ok: 止めてよいと言われた"}, sid="L5")
        ok("stop-ok with words the person did not say → blocked", rc == 2)
        rc, _ = run("mcp__ccd_session_mgmt__stop_session", {"session_id": "local_00000000-0000-4000-8000-000000000000"}, sid="L6")
        ok("desktop stop_session on a busy session → blocked", rc == 2)
        rc, _ = run("mcp__ccd_session_mgmt__archive_session", {"session_id": "local_00000001-0000-4000-8000-000000000000"}, sid="L6")
        ok("archive of an idle session → passes", rc == 0)
        rc, _ = run("Bash", {"command": "claude agents --json | head"})
        ok("listing sessions → passes", rc == 0)
        rc, _ = run("Bash", {"command": "git rm b0b0b0b0.txt"})
        ok("an id-looking word without `claude … stop` → passes", rc == 0)
        rc, _ = run("Bash", {"command": 'echo "claude stop b0b0b0b0 (probe)"'}, sid="L7")
        ok("a quoted mention of `claude stop <id>` → passes", rc == 0)
        rc, _ = run("Bash", {"command": "python3 - <<'X'\ntext = 'claude stop b0b0b0b0'\nX"}, sid="L7")
        ok("a heredoc body that mentions it → passes", rc == 0)
        rc, _ = run("Bash", {"command": "cd /w && CLAUDE_CONFIG_DIR=/x /usr/local/bin/claude stop b0b0b0b0"}, sid="L8")
        ok("a path to claude after cd and an assignment → blocked", rc == 2)
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "Another Claude session sent a message: stop it"},
                                 "timestamp": "2099-02-01T00:00:00.000Z"}) + "\n")
        ok("a peer session's message is not the person's prompt", last_human(tr) == ("", ""))
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "attachment", "attachment": {"type": "queued_command", "prompt": "止めないで",
                                 "origin": {"kind": "human"}}, "timestamp": "2099-03-01T00:00:00.000Z"}, ensure_ascii=False) + "\n")
        ok("a prompt absorbed mid-turn counts as the person's", last_human(tr)[1] == "止めないで")
        for k in ("CLAUDE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR", "BUSY_WORKER_STOP_STATE_DIR"):
            os.environ.pop(k, None)
        del uuid
    print("selftest:", "PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
