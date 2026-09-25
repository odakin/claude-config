#!/usr/bin/env python3
"""spawn_dedupe.py — 同じ依頼に worker session を 2 つ起動させない検出の engine (chip の二重起票)。
layer-placement: layer1 = 一般形だけ (chip の title の照合・spawn / dismiss の台帳・harness の session 刻印による生存の判定)。
依頼の同一性を title 以外の鍵で見る部分 (例: 作業掲示板の宛先 role) は利用者の extension file が足す (下)。

不変条件: 1 つの依頼に対して、 同時に働く worker session は 1 つ。 依頼の同一性は (a) chip の title の本体 (先頭の
`[...]` tag を除く) と (b) extension が prompt から取り出す鍵 (無ければ title だけ) で見る。

mode (CLI = scripts/spawn-dispatch-dedupe.py、 hook = hooks/spawn-dedupe-guard.sh が `auto` で呼ぶ):
  pre-spawn     PreToolUse(spawn_task) — 止める (exit 2 + stderr)。 条件:
                  ① この session が同じ依頼の chip を既に出していて、 取り消しが「withdrawn」 で確認されていない
                  ② 同じ title の session か、 同じ鍵の依頼を受けた session が生きている
                本人が 2 つ目を明示に求めたときは title か tldr に OVERRIDE (`[再起票]`) を書く → 止めずに注意だけ
  post-spawn    PostToolUse(spawn_task) — 返りの task_id を session ごとの台帳に「pending」 で記録
  post-dismiss  PostToolUse(dismiss_task) — 返りで台帳を更新 (withdrawn / started / dismissed)。
                「already started」 なら「作り直さず SendMessage で訂正」 を注入

材料 (どれも読むだけ):
  - harness の session 刻印 `~/.claude/sessions/<pid>.json` (pid が生きている = 稼働中。 chip から起動した
    session は `name` に chip の title をそのまま持つ)
  - 台帳 `~/.claude/state/spawn-dispatch/<sessionId>.json` (この engine だけが書く、 30 日で片付ける)
  - extension が読む transcript `~/.claude/projects/<cwd を - に>/<sessionId>.jsonl` (helper = transcript_path / human_text)

extension (任意): `~/.claude/spawn-dedupe-ext.py` (env SPAWN_DEDUPE_EXT で差し替え) に
  request_keys(prompt: str) -> set[str]         # chip の prompt が宛てる依頼の鍵
  session_keys(sid: str, cwd: str) -> set[str]  # 稼働中の session が受けた依頼の鍵 (人間の発話から)
  FOOTER = "…"                                  # 止めた理由の末尾に足す 1 行 (経緯の所在など、 任意)
を定義する。 読めない・例外 = title だけで見る (extension の故障で止めない)。

故障の扱い: 例外・入力不足は全部「通す」 (exit 0)。 止めるのは上の条件が成り立った時だけ
(= 故障の合図を違反の合図と同じ値にしない、 docs/convention-design-principles.md#failure-exit-equals-violation-exit)。
exit 2 で spawn_task が実際に止まることは実測 (tool の結果が hook の stderr を持つ error になり task_id は付かない。
dismiss で withdrawn を読んだ次の応答の spawn_task だけが通った)。

環境変数 (test 用の差し替え): CLAUDE_SESSIONS_DIR / CLAUDE_PROJECTS_DIR / SPAWN_DEDUPE_STATE_DIR / SPAWN_DEDUPE_EXT /
SPAWN_DEDUPE_DISABLE=1
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import tempfile
import time

SESSIONS_DIR = os.environ.get("CLAUDE_SESSIONS_DIR") or os.path.expanduser("~/.claude/sessions")
PROJECTS_DIR = os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")
STATE_DIR = os.environ.get("SPAWN_DEDUPE_STATE_DIR") or os.path.expanduser("~/.claude/state/spawn-dispatch")
EXT_PATH = os.environ.get("SPAWN_DEDUPE_EXT") or os.path.expanduser("~/.claude/spawn-dedupe-ext.py")

OVERRIDE = "[再起票]"
TAG_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)+")
TASK_ID_RE = re.compile(r"task_id:\s*(task_[0-9A-Za-z]+)")
SYSREM_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
LEDGER_TTL_DAYS = 30
RULE = "conventions/multi-session-coordination.md#chip-correction-by-message"


# ── 共通部品 (extension も使う) ─────────────────────────────

def core_title(title: str) -> str:
    """chip の title から先頭の `[local推奨]` `[model: …]` 等の tag を外し、 空白を畳んだ本体。"""
    return " ".join(TAG_RE.sub("", title or "").split())


def flatten(resp) -> str:
    """tool_response (str / list / dict) を 1 つの文字列に。"""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return " ".join(flatten(x) for x in resp)
    if isinstance(resp, dict):
        if "text" in resp and isinstance(resp["text"], str):
            return resp["text"]
        return " ".join(flatten(v) for v in resp.values())
    return str(resp)


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except Exception:
        return True  # 判定できないものは生きている扱い (見逃すより止めすぎる側)
    return True


def live_sessions(self_sid: str = "") -> list:
    """稼働中の session (自分を除く) = [{pid, sid, cwd, name, age_min}]。 刻印が読めない・pid が死んでいるものは除く。"""
    out = []
    for f in glob.glob(os.path.join(SESSIONS_DIR, "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        sid = d.get("sessionId") or ""
        pid = d.get("pid")
        if not sid or pid is None or sid == self_sid:
            continue
        if not pid_alive(pid):
            continue
        started = d.get("startedAt")
        age = None
        if isinstance(started, (int, float)):
            age = max(0, int((time.time() * 1000 - started) // 60000))
        out.append({"pid": pid, "sid": sid, "cwd": d.get("cwd") or "", "name": d.get("name") or "", "age_min": age})
    return out


def transcript_path(sid: str, cwd: str) -> str:
    p = os.path.join(PROJECTS_DIR, re.sub(r"[^A-Za-z0-9]", "-", cwd or ""), sid + ".jsonl")
    if os.path.isfile(p):
        return p
    hits = glob.glob(os.path.join(PROJECTS_DIR, "*", sid + ".jsonl"))
    return hits[0] if hits else ""


def human_text(obj: dict) -> str:
    """transcript の 1 record から人間の発話だけ (compaction の要約・meta・別 session からの message・tool 結果は空)。"""
    if obj.get("type") != "user" or obj.get("isCompactSummary") or obj.get("isMeta"):
        return ""
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    else:
        return ""
    if "<cross-session-message" in text:
        return ""
    return SYSREM_RE.sub("", text)


def desc(s: dict) -> str:
    age = "" if s.get("age_min") is None else f"、 {s['age_min']} 分前に起動"
    name = f"「{s['name']}」" if s.get("name") else "(名前なし)"
    return f"session {s['sid'][:8]} (pid {s['pid']}{age}) {name}"


# ── extension ──────────────────────────────────────────────

class _NoExt:
    FOOTER = ""

    @staticmethod
    def request_keys(prompt: str) -> set:
        return set()

    @staticmethod
    def session_keys(sid: str, cwd: str) -> set:
        return set()


def load_ext(path: str | None = None):
    """extension file を読む。 無い・読めない = _NoExt (title だけで見る)。"""
    path = path or EXT_PATH
    if not path or not os.path.isfile(path):
        return _NoExt
    try:
        import runpy

        ns = runpy.run_path(path)
    except Exception:
        return _NoExt

    class Ext:
        FOOTER = str(ns.get("FOOTER") or "")

        @staticmethod
        def request_keys(prompt: str) -> set:
            fn = ns.get("request_keys")
            try:
                return set(fn(prompt)) if callable(fn) else set()
            except Exception:
                return set()

        @staticmethod
        def session_keys(sid: str, cwd: str) -> set:
            fn = ns.get("session_keys")
            try:
                return set(fn(sid, cwd)) if callable(fn) else set()
            except Exception:
                return set()

    return Ext


# ── 台帳 (この session が出した chip) ──────────────────────

def _ledger_file(sid: str) -> str:
    return os.path.join(STATE_DIR, re.sub(r"[^A-Za-z0-9_-]", "_", sid) + ".json")


def load_ledger(sid: str) -> list:
    if not sid:
        return []
    try:
        with open(_ledger_file(sid), encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("entries", []) if isinstance(d, dict) else []
    except Exception:
        return []


def save_ledger(sid: str, entries: list) -> None:
    if not sid:
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    path = _ledger_file(sid)
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"session_id": sid, "entries": entries}, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    cutoff = time.time() - LEDGER_TTL_DAYS * 86400     # 古い session の台帳を片付ける (読むのは同じ session だけ)
    for f in glob.glob(os.path.join(STATE_DIR, "*.json")):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
        except Exception:
            pass


def _same_request(entry: dict, core: str, keys: set) -> bool:
    return bool((core and entry.get("core") == core) or (keys & set(entry.get("keys") or entry.get("roles") or [])))


# ── 各 mode ───────────────────────────────────────────────

def pre_spawn(inp: dict, ext=None):
    """→ (rc, text)。 rc 2 = 止める (text は stderr へ)、 rc 0 + text = 注意だけ (additionalContext)。"""
    ext = ext or load_ext()
    ti = inp.get("tool_input") or {}
    sid = inp.get("session_id") or ""
    title = ti.get("title") or ""
    core = core_title(title)
    keys = set(ext.request_keys(ti.get("prompt") or ""))
    override = OVERRIDE in title or OVERRIDE in (ti.get("tldr") or "")
    if not core and not keys:
        return 0, ""

    reasons = []
    for e in load_ledger(sid):
        if not _same_request(e, core, keys):
            continue
        st = e.get("state")
        if st == "pending":
            reasons.append(
                f"この session が出した同じ依頼の chip {e.get('task_id')} (「{e.get('title')}」) は、 取り消しがまだ確認されていない "
                f"(dismiss_task が「withdrawn」 を返していない)。 本人は chip を十数秒で押すので、 取り消しの結果を読む前に作り直すと二重起動になる。 "
                f"dismiss_task だけを出し、 その結果を読んだ**次の応答**で決める = withdrawn なら作り直す / already started なら作り直さず、 "
                f"起動した session に SendMessage で訂正する。 取り消しと作り直しを同じ応答に並べない")
        elif st == "started":
            reasons.append(
                f"この session が出した同じ依頼の chip {e.get('task_id')} は既に起動している (dismiss が already started を返した)。 "
                f"作り直さず、 起動した session に SendMessage で訂正する (ListAgents で title の session を探す)")

    for s in live_sessions(sid):
        if core and core_title(s["name"]) == core:
            reasons.append(f"同じ title の session が稼働中: {desc(s)}。 訂正はその session に SendMessage で送る")
            continue
        if keys:
            both = keys & set(ext.session_keys(s["sid"], s["cwd"]))
            if both:
                reasons.append(f"同じ依頼 ({', '.join(sorted(both))}) の worker が稼働中: {desc(s)}。 "
                               f"新しい chip は作らず、 その session に SendMessage で訂正・追加を送る")

    if not reasons:
        return 0, ""
    body = "\n".join(f"  - {r}" for r in dict.fromkeys(reasons))
    tail = f"規約 = {RULE} (不変条件: 1 つの依頼に同時に働く worker は 1 つ)" + (f"。 {ext.FOOTER}" if ext.FOOTER else "")
    if override:
        return 0, (f"[spawn-dedupe-guard] {OVERRIDE} の指定があるので止めなかった。 同じ依頼の worker が既に在る:\n{body}\n"
                   f"本人が 2 つ目を明示に求めたのでなければ、 すぐ dismiss_task で取り消す。 {tail}")
    return 2, (f"🛑 spawn-dedupe-guard: 同じ依頼の worker を 2 つ起動させる chip なので止めた。\n{body}\n"
               f"本人が 2 つ目を明示に求めた時だけ、 title か tldr に `{OVERRIDE}` を書いて出し直す。 {tail}")


def post_spawn(inp: dict, ext=None) -> str:
    ext = ext or load_ext()
    ti = inp.get("tool_input") or {}
    sid = inp.get("session_id") or ""
    m = TASK_ID_RE.search(flatten(inp.get("tool_response")))
    if not sid or not m:
        return ""
    entries = [e for e in load_ledger(sid) if e.get("task_id") != m.group(1)]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    entries.append({"task_id": m.group(1), "title": ti.get("title") or "", "core": core_title(ti.get("title") or ""),
                    "keys": sorted(ext.request_keys(ti.get("prompt") or "")), "state": "pending",
                    "created": now, "updated": now})
    save_ledger(sid, entries)
    return ""


def post_dismiss(inp: dict) -> str:
    ti = inp.get("tool_input") or {}
    sid = inp.get("session_id") or ""
    tid = ti.get("task_id") or ""
    text = flatten(inp.get("tool_response"))
    if "already started" in text:
        st = "started"
    elif "already dismissed" in text:
        st = "dismissed"
    elif "withdrawn" in text:
        st = "withdrawn"
    else:
        return ""
    if sid and tid:
        entries = load_ledger(sid)
        hit = False
        for e in entries:
            if e.get("task_id") == tid:
                e["state"], e["updated"], hit = st, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), True
        if not hit:
            entries.append({"task_id": tid, "title": "", "core": "", "keys": [], "state": st})
        save_ledger(sid, entries)
    if st == "started":
        return (f"[spawn-dedupe-guard] chip {tid} は起動済みで取り消せなかった = その依頼の worker は既に働いている。 "
                f"**同じ依頼の chip を作り直さない**。 直したいこと (仕様の訂正・依頼 id など) は、 ListAgents で chip の title の session を探して "
                f"SendMessage で送る。 同じ応答で既に作り直しを出していたら、 後から起動した方に「何もせず終了」 を頼む ({RULE})")
    return ""


def route(inp: dict) -> str:
    """hook の入力 (hook_event_name + tool_name) から mode。 該当しなければ空 = 何もしない。"""
    ev = inp.get("hook_event_name") or ""
    tool = inp.get("tool_name") or ""
    if tool.endswith("__spawn_task"):
        return {"PreToolUse": "pre-spawn", "PostToolUse": "post-spawn"}.get(ev, "")
    if tool.endswith("__dismiss_task") and ev == "PostToolUse":
        return "post-dismiss"
    return ""


def run(mode: str, inp: dict, ext=None) -> int:
    """mode を 1 回。 stdout = additionalContext の JSON (注意)、 stderr + 2 = 止める。 故障は 0。 ext = extension (既定 = load_ext())。"""
    if mode == "auto":
        mode = route(inp)
    try:
        if mode == "pre-spawn":
            rc, text = pre_spawn(inp, ext)
            if rc == 2:
                sys.stderr.write(text + "\n")
                return 2
            if text:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}, ensure_ascii=False))
            return 0
        if mode == "post-spawn":
            text = post_spawn(inp, ext)
        elif mode == "post-dismiss":
            text = post_dismiss(inp)
        else:
            return 0
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}, ensure_ascii=False))
    except Exception as exc:  # 故障は通す (違反と同じ値にしない)
        sys.stderr.write(f"(spawn-dedupe: {mode} を検査できなかった: {exc.__class__.__name__}: {exc})\n")
    return 0


# ── selftest (合成の刻印・台帳・transcript、 fake の extension) ──

def selftest() -> int:
    global SESSIONS_DIR, PROJECTS_DIR, STATE_DIR
    saved = (SESSIONS_DIR, PROJECTS_DIR, STATE_DIR)
    fails = []

    def check(name, cond):
        print(("  ✓ " if cond else "  ✗ ") + name)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        SESSIONS_DIR, PROJECTS_DIR, STATE_DIR = (os.path.join(tmp, x) for x in ("sessions", "projects", "state"))
        for d in (SESSIONS_DIR, PROJECTS_DIR, STATE_DIR):
            os.makedirs(d)
        cwd = "/tmp/synthetic/Claude"                       # 合成の cwd (絶対 path の形は公開 repo の gate が拾うので /Users を使わない)
        pdir = os.path.join(PROJECTS_DIR, "-tmp-synthetic-Claude")
        os.makedirs(pdir)
        me = "aaaaaaaa-0000-0000-0000-000000000000"
        title = "[local推奨] [model: opus xhigh] 合成の依頼 A の見直し"
        key_re = re.compile(r"依頼の鍵\s*=\s*(key-[a-z0-9-]+)")

        # fake の extension = 「依頼の鍵 = key-…」 を prompt と人間の発話から取る (実際の extension は利用者側)
        class Ext:
            FOOTER = "経緯 = (test)"

            @staticmethod
            def request_keys(prompt):
                return set(key_re.findall(prompt or ""))

            @staticmethod
            def session_keys(sid, cwd_):
                path = transcript_path(sid, cwd_)
                keys = set()
                if not path:
                    return keys
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        try:
                            keys |= set(key_re.findall(human_text(json.loads(line))))
                        except Exception:
                            pass
                return keys

        worker_prompt = "君は worker。 依頼の鍵 = key-alpha、 thread = x/y。 別 session (key-other) が設計中なので触らない。"

        def spawn_inp(t=title, p=worker_prompt, tldr="x", sid=me):
            return {"session_id": sid, "tool_input": {"title": t, "tldr": tldr, "prompt": p}}

        def add_live(key, sid, name, first_prompt=None, extra_lines=()):
            with open(os.path.join(SESSIONS_DIR, f"{key}.json"), "w") as fh:
                json.dump({"pid": os.getpid(), "sessionId": sid, "cwd": cwd, "name": name,
                           "startedAt": int(time.time() * 1000) - 60000}, fh)
            with open(os.path.join(pdir, sid + ".jsonl"), "w") as fh:
                if first_prompt is not None:
                    fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": first_prompt}}, ensure_ascii=False) + "\n")
                for ln in extra_lines:
                    fh.write(json.dumps(ln, ensure_ascii=False) + "\n")

        check("core_title strips leading tags", core_title(title) == "合成の依頼 A の見直し")
        check("route: PreToolUse spawn → pre-spawn",
              route({"hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__spawn_task"}) == "pre-spawn")
        check("route: PostToolUse dismiss → post-dismiss",
              route({"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_session__dismiss_task"}) == "post-dismiss")
        check("route: UserPromptSubmit / Bash → nothing (利用者側の hook の領分)",
              route({"hook_event_name": "UserPromptSubmit"}) == "" and route({"hook_event_name": "PostToolUse", "tool_name": "Bash"}) == "")
        check("load_ext: 無い path は title だけ", load_ext(os.path.join(tmp, "none.py")).request_keys("依頼の鍵 = key-a") == set())
        with open(os.path.join(tmp, "ext.py"), "w") as fh:
            fh.write("import re\nFOOTER = 'f'\ndef request_keys(p):\n    return set(re.findall(r'key-[a-z]+', p or ''))\n"
                     "def session_keys(sid, cwd):\n    return {'key-alpha'}\n")
        e2 = load_ext(os.path.join(tmp, "ext.py"))
        check("load_ext: file の request_keys / session_keys / FOOTER を読む",
              e2.request_keys("x key-alpha y") == {"key-alpha"} and e2.session_keys("s", "c") == {"key-alpha"} and e2.FOOTER == "f")
        with open(os.path.join(tmp, "bad.py"), "w") as fh:
            fh.write("raise RuntimeError('broken ext')\n")
        check("load_ext: 壊れた extension は title だけ (止めない)", load_ext(os.path.join(tmp, "bad.py")).request_keys("key-alpha") == set())

        # 1. 何も無い → 通す
        rc, _ = pre_spawn(spawn_inp(), Ext)
        check("fresh chip passes", rc == 0)
        # 2. 出した chip (pending) と同じ title → 止める (取り消しの確認前)
        post_spawn({"session_id": me, "tool_input": spawn_inp()["tool_input"],
                    "tool_response": [{"type": "text", "text": "Noted (position 1, task_id: task_000000aa). A chip is showing"}]}, Ext)
        check("post-spawn records pending with keys",
              [e["state"] for e in load_ledger(me)] == ["pending"] and load_ledger(me)[0]["keys"] == ["key-alpha"])
        rc, txt = pre_spawn(spawn_inp(p=worker_prompt.replace("x/y", "z/w")), Ext)
        check("same title while pending → block", rc == 2 and "task_000000aa" in txt and "🛑" in txt)
        rc, _ = pre_spawn(spawn_inp(t="[worktree推奨] 別の言い方"), Ext)
        check("same key, different title, pending → block", rc == 2)
        rc, _ = pre_spawn(spawn_inp(t="[local推奨] 別件", p="依頼の鍵 = key-other-thing。"), Ext)
        check("different request passes", rc == 0)
        rc, _ = pre_spawn(spawn_inp(t="[worktree推奨] 別の言い方"), _NoExt)
        check("extension 無し = title だけで見る (鍵が同じでも title が違えば通す)", rc == 0)
        # 3. dismiss が already started → 台帳 started + 注意、 同じ title は live で止める
        add_live(111, "bbbbbbbb-1111", title, worker_prompt)
        note = post_dismiss({"session_id": me, "tool_input": {"task_id": "task_000000aa"},
                             "tool_response": "Task task_000000aa was already started by the user — it's no longer pending and can't be withdrawn."})
        check("post-dismiss already started → state started + nudge", load_ledger(me)[0]["state"] == "started" and "作り直さない" in note)
        rc, txt = pre_spawn(spawn_inp(), Ext)
        check("same title after started (live) → block, names the live session", rc == 2 and "bbbbbbbb" in txt)
        # 4. override → 注意だけ
        rc, txt = pre_spawn(spawn_inp(tldr="[再起票] 本人が 2 つ目を求めた"), Ext)
        check("override [再起票] → warn only", rc == 0 and "[再起票]" in txt)
        # 5. withdrawn → 台帳は通すが、 live に同じ title があれば止める / live が消えれば通す
        post_dismiss({"session_id": me, "tool_input": {"task_id": "task_000000aa"},
                      "tool_response": "Task task_000000aa withdrawn — the chip is no longer shown to the user."})
        os.remove(os.path.join(SESSIONS_DIR, "111.json"))
        rc, _ = pre_spawn(spawn_inp(), Ext)
        check("withdrawn + no live duplicate → pass", rc == 0)
        # 6. 台帳に無い (別 session 由来・貼り付けで始めた) worker が同じ鍵で稼働 → 止める (title が違っても)
        add_live(222, "cccccccc-2222", "貼り付けで始めた session", worker_prompt)
        rc, txt = pre_spawn(spawn_inp(t="[local推奨] 新しい title", sid="dddddddd"), Ext)
        check("live worker with same key (pasted) → block", rc == 2 and "cccccccc" in txt)
        # 7. 依頼元らしい transcript (要約 / cross-session message / tool_result で鍵に触れただけ) は worker と数えない
        os.remove(os.path.join(SESSIONS_DIR, "222.json"))
        add_live(333, "eeeeeeee-3333", "依頼元", "別の話題", extra_lines=[
            {"type": "user", "isCompactSummary": True, "message": {"content": "要約: 依頼の鍵 = key-alpha"}},
            {"type": "user", "message": {"content": "Another Claude session sent a message:\n<cross-session-message from=\"x\">依頼の鍵 = key-alpha</cross-session-message>"}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "依頼の鍵 = key-alpha"}]}},
        ])
        rc, _ = pre_spawn(spawn_inp(t="[local推奨] 新しい title", sid="dddddddd"), Ext)
        check("requester-like transcript (summary / cross-session / tool_result) not counted", rc == 0)
        # 8. 故障は通す: 壊れた台帳・刻印・pid 死亡
        with open(_ledger_file("hhhhhhhh"), "w") as fh:
            fh.write("{broken")
        with open(os.path.join(SESSIONS_DIR, "bad.json"), "w") as fh:
            fh.write("not json")
        import subprocess
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        with open(os.path.join(SESSIONS_DIR, "dead.json"), "w") as fh:
            json.dump({"pid": dead.pid, "sessionId": "dead", "cwd": cwd, "name": title}, fh)
        rc, _ = pre_spawn(spawn_inp(sid="hhhhhhhh"), Ext)
        check("broken ledger / bad stamp / dead pid → pass", rc == 0)
        # 9. run(): auto の経路で exit 2 と stderr、 post-spawn は 0
        import io
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            post_spawn({"session_id": "iiiiiiii", "tool_input": spawn_inp()["tool_input"],
                        "tool_response": "Noted (position 1, task_id: task_000000bb)."}, Ext)
            rc = run("auto", dict(spawn_inp(sid="iiiiiiii"), hook_event_name="PreToolUse", tool_name="mcp__ccd_session__spawn_task"))
        finally:
            sys.stderr = old
        check("run auto: duplicate → 2 with stderr", rc == 2 and "🛑" in err.getvalue())

    SESSIONS_DIR, PROJECTS_DIR, STATE_DIR = saved
    print(f"spawn_dedupe selftest: {'FAIL ' + str(len(fails)) if fails else 'PASS'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else 0)
