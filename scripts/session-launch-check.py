#!/usr/bin/env python3
"""session-launch-check.py — desktop の start_session で起こした session が、 頼んだ model と effort で起きたかを app の記録で確かめ、 違えば直し方を出し、 直るまで go の SendMessage を止める (hook の engine。 正本 = conventions/multi-session-coordination.md#desktop-start-model-cap)。

Why (実測): desktop app の `start_session` は `model` を呼び元と同じか安い family までしか受けず、 高い指定は黙って捨てる
(Opus の session から Fable を頼むと Opus で起きる)。 `effort` も同じく黙って呼び元のものになることがある。 返りの文は
「Started session」 だけで、 何で起きたかを言わない。 新しい session は最初の turn をすぐ始めるので、 記録の model を
直す (`set_session_model` / `set_session_effort`) のは最初の turn の後になり、 worker の最初の turn の最中に切り替えると
効かなかった例がある。 起こした側が「起きた」 と言う前に、 app の記録 (scripts/lib/desktop_sessions.py) を読む。

mode (hook の入力の hook_event_name + tool_name で選ぶ = `auto`):
  PreToolUse(start_session)   掲示板の request を経ずに worker を起こす start_session を止める (opt-in = 下の BOARD_FIRST)。
                              prompt に掲示板の request id があり、 その request の起動の記録 (掲示板の outbox の
                              `<request id>.launch.json`、 board.py request --surface desktop が書く) があれば、 model・effort が
                              記録と違う start_session を止める (= 起こし方は掲示板の request が決める)。
  PostToolUse(start_session)  返りの `local_…` の app の記録を読み、 頼んだ model・effort (prompt の「This window must run on
                              <model> at <effort> effort」、 無ければ start_session の引数) と比べる。 違えば additionalContext で
                              直し方 (set_session_model / set_session_effort → worker の 1 行を待つ → 記録を読む → go) を出し、
                              起こした session ごとの台帳 (~/.claude/state/session-launch/<session>.json) に残す。
  (start_session の後と go の SendMessage が通る時) 掲示板の launch 記録が detach を求めていれば、 detach_session を出すよう
                              additionalContext で知らせる (子の turn の終わりの知らせと本人への問いを依頼元に来させない)。
  PostToolUse(set_session_model / set_session_effort)  台帳の「頼んだ値」 を起こした側の最新の指定に揃える。
  PreToolUse(SendMessage)     宛先が台帳で未解決の session なら app の記録を読み直す。 合っていれば通し、 違えば止める。
                              本人がその model でよいと言ったなら message に `[model-ok]` を入れれば通る (= 本人が app で
                              model を変えた場合を止め続けない)。

BOARD_FIRST: `~/.claude/session-launch-board-first.on` が在るか env SESSION_LAUNCH_BOARD_FIRST=1 のとき、 initiation が
user_asked の start_session は prompt に掲示板の request id が無いと止める (title か prompt に `[no-board]` で通す)。
既定は off (層1 の利用者が掲示板を使うとは限らない)。

故障は通す (読めない入力・記録が見つからない・例外 = exit 0)。 止めるのは条件が成り立った時だけ。
env: SESSION_LAUNCH_CHECK_DISABLE=1 / SESSION_LAUNCH_STATE_DIR (test) / CLAUDE_DESKTOP_SESSIONS_DIR (test) /
     SESSION_LAUNCH_WAIT (記録を待つ秒、 既定 3)。
self-test: python3 scripts/session-launch-check.py --selftest
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
import desktop_sessions as ds  # noqa: E402

try:
    import session_model as sm  # noqa: E402
except Exception:  # pragma: no cover
    sm = None

RULE = "claude-config/conventions/multi-session-coordination.md#desktop-start-model-cap"
DETACH_RULE = "claude-config/conventions/multi-session-coordination.md#worker-surface-visibility"
OK_TOKEN = "[model-ok]"
NO_BOARD = "[no-board]"
MUST_RUN = re.compile(r"must run on (claude-[a-z0-9.-]+?)(?: at ([a-z]+) effort)?[.\s:*]", re.I)
REQUEST_ID = re.compile(r"request `?(\d{8}T\d{6}Z-[a-z]+-[0-9a-f]{6})`?")
BOARD_ROOT = re.compile(r"--root (\S+)")
TIER_WORDS = {"fable", "opus", "sonnet", "haiku", "mythos"}


def state_dir() -> str:
    return os.environ.get("SESSION_LAUNCH_STATE_DIR") or os.path.expanduser("~/.claude/state/session-launch")


def flatten(resp) -> str:
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return " ".join(flatten(x) for x in resp)
    if isinstance(resp, dict):
        if isinstance(resp.get("text"), str):
            return resp["text"]
        return " ".join(flatten(v) for v in resp.values())
    return str(resp)


def tier(model: str) -> str:
    m = (model or "").lower()
    if m in TIER_WORDS:
        return "fable" if m == "mythos" else m
    if sm is not None:
        return sm.tier(m)
    for k in ("fable", "opus", "sonnet", "haiku"):
        if k in m:
            return k
    return ""


def requested(ti: dict) -> tuple[str, str]:
    """(model, effort) the launcher asked for: the hand-off line wins over the start_session arguments."""
    prompt = ti.get("prompt") or ""
    m = MUST_RUN.search(prompt + " ")
    model = (m.group(1) if m else "") or (ti.get("model") or "")
    effort = ((m.group(2) if m else "") or (ti.get("effort") or "")).lower()
    return model.strip(), effort.strip()


def model_matches(want: str, got: str) -> bool:
    if not want:
        return True
    if want.lower() in TIER_WORDS:
        return tier(want) == tier(got)
    return want.lower() == (got or "").lower()


def mismatch(want_model: str, want_effort: str, rec: dict) -> list[str]:
    out = []
    if want_model and not model_matches(want_model, rec.get("model", "")):
        out.append(f"model = {rec.get('model') or '?'} (頼んだのは {want_model})")
    if want_effort and want_effort != (rec.get("effort") or "").lower():
        out.append(f"effort = {rec.get('effort') or '?'} (頼んだのは {want_effort})")
    return out


# ---- ledger (per launching session) ----

def _ledger_path(sid: str) -> str:
    return os.path.join(state_dir(), re.sub(r"[^A-Za-z0-9_.-]", "_", sid or "unknown") + ".json")


def load(sid: str) -> list[dict]:
    try:
        with open(_ledger_path(sid), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def save(sid: str, entries: list[dict]) -> None:
    os.makedirs(state_dir(), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state_dir(), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(entries[-50:], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _ledger_path(sid))


def upsert(sid: str, local_id: str, **fields) -> dict:
    entries = load(sid)
    hit = next((e for e in entries if e.get("local_id") == local_id), None)
    if hit is None:
        hit = {"local_id": local_id}
        entries.append(hit)
    hit.update(fields)
    hit["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save(sid, entries)
    return hit


# ---- modes ----

def board_launch_record(prompt: str) -> dict | None:
    rid, root = REQUEST_ID.search(prompt or ""), BOARD_ROOT.search(prompt or "")
    if not rid or not root:
        return None
    p = os.path.join(os.path.expanduser(root.group(1)), ".local", "outbox", rid.group(1) + ".launch.json")
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def board_first_on() -> bool:
    return os.environ.get("SESSION_LAUNCH_BOARD_FIRST") == "1" or os.path.exists(
        os.path.expanduser("~/.claude/session-launch-board-first.on"))


def pre_start(inp: dict) -> tuple[int, str]:
    ti = inp.get("tool_input") or {}
    if ti.get("proposal_id") and not ti.get("prompt"):
        return 0, ""
    prompt, title = ti.get("prompt") or "", ti.get("title") or ""
    if (ti.get("initiation") == "user_asked" and board_first_on() and not REQUEST_ID.search(prompt)
            and NO_BOARD not in title + prompt):
        return 2, ("🛑 session-launch-check: worker は掲示板の request を経て起こす (この機械の設定 = 掲示板を経路の軸にする)。\n"
                   "  1. board.py request … --to claude --to-session role-<project>-<仕事> --surface desktop で依頼を出す\n"
                   "  2. 出力の start_session の引数 (model・effort・title・prompt) で起こす\n"
                   f"  掲示板を通さない理由があるなら title か prompt に {NO_BOARD} と理由を書いて出し直す。 規約 = {RULE}")
    rec = board_launch_record(prompt)
    if rec:
        want_m, want_e = (rec.get("model") or ""), (rec.get("effort") or "")
        got_m, got_e = (ti.get("model") or ""), (ti.get("effort") or "")
        diffs = []
        if want_m and got_m and not model_matches(want_m, got_m):
            diffs.append(f"model {got_m} (掲示板の request は {want_m})")
        if want_e and got_e and want_e != got_e:
            diffs.append(f"effort {got_e} (掲示板の request は {want_e})")
        if diffs:
            return 2, ("🛑 session-launch-check: 起こし方は掲示板の request が決める。 start_session の引数が request の記録と違う: "
                       + " / ".join(diffs) + "。\n  request の出力の start_session の引数で出し直す。 model を変えるなら request を出し直す"
                       f" (記録 = {rec.get('_path', 'outbox の launch.json')})。 規約 = {RULE}")
    return 0, ""


def post_start(inp: dict) -> str:
    text = flatten(inp.get("tool_response"))
    m = ds.LOCAL_RE.search(text)
    if not m or "Started session" not in text:
        return ""
    local_id = m.group(0)
    ti = inp.get("tool_input") or {}
    want_m, want_e = requested(ti)
    if not want_m and not want_e:
        return ""
    rec = ds.wait_for(local_id, float(os.environ.get("SESSION_LAUNCH_WAIT", "3")))
    sid = inp.get("session_id") or ""
    if not rec:
        upsert(sid, local_id, want_model=want_m, want_effort=want_e, state="unknown", title=ti.get("title") or "")
        return (f"[session-launch-check] {local_id} の app の記録がまだ読めない = 何の model で起きたか確かめられていない。"
                f" 「起きた」 と言う前に python3 ~/Claude/claude-config/scripts/session-model.py {local_id} で読む。")
    diffs = mismatch(want_m, want_e, rec)
    detach = bool((board_launch_record(ti.get("prompt") or "") or {}).get("detach"))
    upsert(sid, local_id, want_model=want_m, want_effort=want_e, state="mismatch" if diffs else "ok", detach=detach,
           got_model=rec.get("model", ""), got_effort=rec.get("effort", ""), title=ti.get("title") or rec.get("title", ""))
    if not diffs:
        return detach_note(local_id) if detach else ""
    steps = []
    model_off = bool(want_m) and not model_matches(want_m, rec.get("model", ""))
    if model_off:
        steps.append(f"set_session_model(session_id={local_id}, model={want_m})")
    if want_e and (model_off or want_e != (rec.get("effort") or "").lower()):
        # after a model switch the effort moved to another value (measured), so it is set again even when it matched
        steps.append(f"その後に set_session_effort(session_id={local_id}, effort={want_e})")
    return ("⚠️ session-launch-check: start_session で起こした session は、 app の記録で "
            + " / ".join(diffs) + " で起きた。 start_session は呼び元より高い model と受けない effort を黙って捨てる (実測)。\n"
            f"  直し方: (1) {' と '.join(steps)} を出す (2) worker は hand-off 文の model の確かめで最初の turn を止める = その 1 行の"
            " 知らせを待つ (worker の turn の最中の切り替えは効かなかった例がある) (3) python3 ~/Claude/claude-config/scripts/"
            f"session-model.py {local_id} で app の記録が頼んだ値になったのを読む (4) go を送る。\n"
            f"  記録が合うまで、 この session への SendMessage はこの検査が止める (本人がこの model でよいと言ったなら message に"
            f" {OK_TOKEN})。 本人に「起きた」 と言うのは (3) の後。"
            + (" go の後に detach_session (掲示板の request の指定)。" if detach else "") + f" 規約 = {RULE}")


def detach_note(local_id: str) -> str:
    return (f"[session-launch-check] {local_id} は頼んだ model・effort で動いている。 掲示板の request の指定どおり、 いま"
            f" detach_session(session_id={local_id}) を出す = 一覧の上の段に独立させ、 子の turn の終わりの知らせと本人への問いを"
            f"依頼元に来させない (本人は worker の窓で答える。 提出と blocker は掲示板の watch で届く)。 規約 = {DETACH_RULE}")


def post_set(inp: dict) -> str:
    ti = inp.get("tool_input") or {}
    local_id = ti.get("session_id") or ""
    sid = inp.get("session_id") or ""
    if not local_id.startswith("local_"):
        return ""
    hit = next((e for e in load(sid) if e.get("local_id") == local_id), None)
    if hit is None:
        return ""
    if ti.get("model"):
        upsert(sid, local_id, want_model=ti["model"], state="pending")
    if ti.get("effort"):
        upsert(sid, local_id, want_effort=str(ti["effort"]).lower(), state="pending")
    return ""


def resolve_to(to: str) -> str:
    """SendMessage `to` → the `local_…` id when it names a desktop session (local id, uds address, or registry)."""
    t = (to or "").strip()
    if t.startswith("local_"):
        return t
    if sm is None:
        return ""
    try:
        for s in sm.live_sessions():
            if t and (s.get("address") == t or s.get("sessionId", "").startswith(t)) and s.get("host", "").startswith("local_"):
                return s["host"]
    except Exception:
        return ""
    return ""


def pre_send(inp: dict) -> tuple[int, str]:
    ti = inp.get("tool_input") or {}
    sid = inp.get("session_id") or ""
    entries = load(sid)
    if not entries:
        return 0, ""
    local_id = resolve_to(ti.get("to") or "")
    hit = next((e for e in entries if e.get("local_id") == local_id), None) if local_id else None
    if not hit or hit.get("state") == "ok":
        return 0, ""
    msg = (ti.get("message") or "") + " " + (ti.get("summary") or "")
    after = detach_note(local_id) if hit.get("detach") else ""   # the go passes: the worker can leave the requester now
    if OK_TOKEN in msg:
        upsert(sid, local_id, state="ok", accepted=True)
        return 0, after
    rec = ds.find(local_id)
    if not rec:
        return 0, ""
    diffs = mismatch(hit.get("want_model", ""), hit.get("want_effort", ""), rec)
    if not diffs:
        upsert(sid, local_id, state="ok", got_model=rec.get("model", ""), got_effort=rec.get("effort", ""))
        return 0, after
    return 2, (f"🛑 session-launch-check: 宛先 {local_id} ({hit.get('title', '')[:40]}) は app の記録で " + " / ".join(diffs)
               + "。 まだ頼んだ model・effort になっていない。\n"
               f"  set_session_model / set_session_effort を出し (worker の turn が終わってから)、 python3 ~/Claude/claude-config/"
               f"scripts/session-model.py {local_id} で記録が合ったのを読んでから送る。 本人がこの model でよいと言った"
               f"なら message に {OK_TOKEN} を入れて送る。 規約 = {RULE}")


def route(inp: dict) -> str:
    ev, tool = inp.get("hook_event_name") or "", inp.get("tool_name") or ""
    if tool.endswith("__start_session"):
        return "pre-start" if ev == "PreToolUse" else ("post-start" if ev == "PostToolUse" else "")
    if ev == "PostToolUse" and (tool.endswith("__set_session_model") or tool.endswith("__set_session_effort")):
        return "post-set"
    if ev == "PreToolUse" and tool == "SendMessage":
        return "pre-send"
    return ""


def emit_context(ev: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": ev, "additionalContext": text}}, ensure_ascii=False))


def run(inp: dict) -> int:
    mode = route(inp)
    if mode == "pre-start":
        rc, txt = pre_start(inp)
    elif mode == "pre-send":
        rc, txt = pre_send(inp)
    elif mode == "post-start":
        rc, txt = 0, post_start(inp)
    elif mode == "post-set":
        rc, txt = 0, post_set(inp)
    else:
        return 0
    if rc == 2:
        sys.stderr.write(txt + "\n")
        return 2
    if txt:
        emit_context(inp.get("hook_event_name") or "PostToolUse", txt)
    return 0


def main() -> int:
    if os.environ.get("SESSION_LAUNCH_CHECK_DISABLE") == "1":
        return 0
    try:
        inp = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    try:
        return run(inp)
    except Exception:
        return 0  # fail-open


def selftest() -> int:
    import io
    import contextlib

    fails = []

    def check(label: str, ok: bool) -> None:
        print(("ok: " if ok else "NG: ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        os.environ.update(SESSION_LAUNCH_STATE_DIR=os.path.join(td, "state"), CLAUDE_DESKTOP_SESSIONS_DIR=os.path.join(td, "app"),
                          SESSION_LAUNCH_WAIT="0")
        os.environ.pop("SESSION_LAUNCH_BOARD_FIRST", None)
        app = os.path.join(td, "app", "acct", "env")
        os.makedirs(app)
        lid = "local_aaaaaaaa-0000-4000-8000-000000000001"
        board = os.path.join(td, "board")
        os.makedirs(os.path.join(board, ".local", "outbox"))
        rid = "20260101T000000Z-claude-0000a1"

        def app_rec(model: str, effort: str) -> None:
            with open(os.path.join(app, lid + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"sessionId": lid, "cliSessionId": "bbbbbbbb-0000-4000-8000-000000000002", "model": model,
                           "effort": effort, "title": "worker A"}, fh)

        handoff = (f"You are the board worker for role `role-x-w`, request `{rid}`, spec `plans/s.md`; execute it yourself."
                   f" This window must run on claude-fable-5-1 at high effort.\n1. `python3 /e/board.py inbox --root {board}"
                   " --agent claude --session role-x-w --sync`")

        def call(ev: str, tool: str, ti: dict, resp=None, sid: str = "launcher-1") -> tuple[int, str, str]:
            inp = {"hook_event_name": ev, "tool_name": tool, "tool_input": ti, "session_id": sid}
            if resp is not None:
                inp["tool_response"] = resp
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = run(inp)
            return rc, out.getvalue(), err.getvalue()

        started = [{"type": "text", "text": f'Started session "worker A" (session_id: {lid}, name: worker-a). It runs on its own'}]
        st = {"initiation": "user_asked", "title": "worker A · Fable high", "prompt": handoff, "model": "claude-fable-5-1",
              "effort": "high"}

        check("requested() reads the hand-off line", requested(st) == ("claude-fable-5-1", "high"))
        check("requested() falls back to arguments", requested({"prompt": "x", "model": "claude-opus-5-5"}) == ("claude-opus-5-5", ""))

        app_rec("claude-opus-5-5", "xhigh")  # the measured cap: Opus caller, Fable asked
        rc, out, _ = call("PostToolUse", "mcp__ccd_session__start_session", st, started)
        check("post-start: capped model and effort → advice with both setters",
              rc == 0 and "set_session_model" in out and "set_session_effort" in out and "claude-opus-5-5" in out)
        check("ledger records the mismatch", load("launcher-1")[0]["state"] == "mismatch")

        rc, _, err = call("PreToolUse", "SendMessage", {"to": lid, "message": "go — claim して進めて"})
        check("pre-send: go to a still-mismatched worker → blocked", rc == 2 and "model-ok" in err)

        rc, _, _ = call("PreToolUse", "SendMessage", {"to": "local_other", "message": "hi"})
        check("pre-send: an unrelated session → pass", rc == 0)

        rc, _, _ = call("PostToolUse", "mcp__ccd_session_mgmt__set_session_model", {"session_id": lid, "model": "claude-fable-5-1"}, "ok")
        app_rec("claude-fable-5-1", "high")
        rc, _, _ = call("PreToolUse", "SendMessage", {"to": lid, "message": "go"})
        check("pre-send: record now matches → pass and ledger ok", rc == 0 and load("launcher-1")[0]["state"] == "ok")

        app_rec("claude-opus-5-5", "xhigh")
        upsert("launcher-1", lid, state="mismatch")
        rc, _, _ = call("PreToolUse", "SendMessage", {"to": lid, "message": "proceed on opus [model-ok] (本人が Opus を選んだ)"})
        check("pre-send: [model-ok] lets the user's own choice through", rc == 0 and load("launcher-1")[0]["state"] == "ok")

        app_rec("claude-fable-5-1", "high")
        rc, out, _ = call("PostToolUse", "mcp__ccd_session__start_session", st, started, sid="launcher-2")
        check("post-start: started as asked → silent", rc == 0 and out == "" and load("launcher-2")[0]["state"] == "ok")

        rc, out, _ = call("PostToolUse", "mcp__ccd_session__start_session", {"initiation": "own_initiative", "title": "t", "prompt": "p"},
                          "Noted (position 1, task_id: task_000000aa).")
        check("post-start: a proposal card (no session yet) → silent", rc == 0 and out == "")

        rc, _, _ = call("PreToolUse", "mcp__ccd_session__start_session", {"initiation": "user_asked", "title": "t", "prompt": "do x"})
        check("pre-start: board-first off by default → pass", rc == 0)
        os.environ["SESSION_LAUNCH_BOARD_FIRST"] = "1"
        rc, _, err = call("PreToolUse", "mcp__ccd_session__start_session", {"initiation": "user_asked", "title": "t", "prompt": "do x"})
        check("pre-start: board-first on, no request id → blocked", rc == 2 and "掲示板" in err)
        rc, _, _ = call("PreToolUse", "mcp__ccd_session__start_session", {"initiation": "user_asked", "title": "t [no-board] 一回限り", "prompt": "do x"})
        check("pre-start: [no-board] → pass", rc == 0)
        rc, _, _ = call("PreToolUse", "mcp__ccd_session__start_session", {"initiation": "own_initiative", "title": "t", "prompt": "do x"})
        check("pre-start: a proposal card is not a start → pass", rc == 0)
        os.environ.pop("SESSION_LAUNCH_BOARD_FIRST")

        with open(os.path.join(board, ".local", "outbox", rid + ".launch.json"), "w", encoding="utf-8") as fh:
            json.dump({"model": "claude-fable-5-1", "effort": "high", "surface": "desktop"}, fh)
        rc, _, err = call("PreToolUse", "mcp__ccd_session__start_session", dict(st, model="claude-opus-5-5"))
        check("pre-start: arguments differ from the board's launch record → blocked", rc == 2 and "掲示板の request" in err)
        rc, _, _ = call("PreToolUse", "mcp__ccd_session__start_session", st)
        check("pre-start: arguments equal the record → pass", rc == 0)

        with open(os.path.join(board, ".local", "outbox", rid + ".launch.json"), "w", encoding="utf-8") as fh:
            json.dump({"model": "claude-fable-5-1", "effort": "high", "surface": "desktop", "detach": True}, fh)
        app_rec("claude-fable-5-1", "high")
        rc, out, _ = call("PostToolUse", "mcp__ccd_session__start_session", st, started, sid="launcher-3")
        check("post-start: right model and the record asks detach → detach_session note", rc == 0 and "detach_session" in out)
        app_rec("claude-opus-5-5", "xhigh")
        rc, out, _ = call("PostToolUse", "mcp__ccd_session__start_session", st, started, sid="launcher-4")
        check("post-start: capped and detach → the fix ends with detach after go", "detach_session" in out and "set_session_model" in out)
        app_rec("claude-fable-5-1", "high")
        rc, out, _ = call("PreToolUse", "SendMessage", {"to": lid, "message": "go"}, sid="launcher-4")
        check("pre-send: go passes once fixed → detach_session note", rc == 0 and "detach_session" in out)

        check("route ignores other tools", route({"hook_event_name": "PreToolUse", "tool_name": "Bash"}) == "")
        for k in ("SESSION_LAUNCH_STATE_DIR", "CLAUDE_DESKTOP_SESSIONS_DIR", "SESSION_LAUNCH_WAIT"):
            os.environ.pop(k, None)
    print("selftest:", "PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
