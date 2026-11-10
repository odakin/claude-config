"""pending_cards.py — この session が出した card (`start_session` の提案) のうち、 押されていないものと、 本人がまだ見ていないものを、 会話記録と desktop app の記録から数える部品 (点呼の Stop hook と、 card を出した依頼を拾い直す見張りが、 同じ述語で読む)

なぜ (正本 = conventions/multi-session-coordination.md#pending-card-rollcall):
  自動の知らせや別の session の message で始まった turn では worker を直接起こせず、 card しか出せない。 card は
  出した時点の会話の中にだけ描かれ、 その後に本人の発言でない turn の返事が積もると最新の返事から消える (実測)。
  押されていない card を一か所に見せるのは Claude しかいないので、 最新の返事に
  点呼の 1 行を書かせる。 ただし本人が見て押さなかった card を繰り返すと風景になる = 「まだ見ていない」 を数える。

述語:
  - card = `start_session` (旧 `spawn_task`) の結果の `Proposed "<題>" (task_id: task_…)`。 題・時刻・hand-off 文の
    掲示板の request id (`request \`<id>\``) を持つ。
  - 押された = (1) app の記録で `spawnedFrom.taskId` がその id の session が在る (押した瞬間にできる、 実測)
    (2) 会話記録の「The user started your proposal task_…」 (起こした側の次の turn に遅れて届く、 実測)
    (3) この session が `start_session` に `proposal_id` を渡して起こした。
  - 取り下げ = `dismiss_task` の結果の「Task task_… withdrawn」。 期限切れ = 出してから 7 日 (app の期限)。
  - 掲示板で引き受け済み = card の hand-off 文が名指す request に、 誰かの claim・submit・accept・abandoned・done が
    在る (最後が release なら戻る)。 別の窓が同じ依頼を起こし直して片付けた card を数え続けない (実測)。 掲示板は
    `<base>/*/events` と `<base>/*/board/events` (`<base>` = この repo の親) か env PENDING_CARDS_BOARD_ROOTS (`:` 区切り)。
  - 本人の turn = user の行のうち `origin.kind == "human"` (自動の知らせ = task-notification・別の session の message
    = peer・子の知らせ・Stop hook の差し戻しは本人の発言でない)。 origin を持たない古い記録では、 isMeta でなく
    自動の知らせの書き出しで始まらない行を本人の turn と見る。
  - まだ見ていない card = 押されておらず、 出した後に始まった本人の turn が 0 回か、 1 回でそれが今の turn
    (= 本人が話した turn への返事が最後の点呼)。 今の本人の turn の発言が「あとで」 なら見たものとする。
Read-only、 例外を外に出さない (呼ぶ hook は fail-open)。 env CLAUDE_DESKTOP_SESSIONS_DIR で app の記録の dir を差し替える (試験)。
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re
import time

PROPOSED = re.compile(r'Proposed "(?P<title>.*?)" \(task_id: (?P<tid>task_[0-9a-zA-Z]+)\)')
STARTED = re.compile(r"The user started your proposal (task_[0-9a-zA-Z]+)")
WITHDRAWN = re.compile(r"Task (task_[0-9a-zA-Z]+) withdrawn")
REQUEST = re.compile(r"request `(\d{8}T\d{6}Z-[a-z]+-[0-9a-f]{6})`")
TAG = re.compile(r"^\s*\[[^\]]*\]\s*")
EXPIRE_SECONDS = 7 * 86400
ROLLCALL_MARK = "🃏 押されていない card"
LATER_WORDS = {"あとで", "あとで押す", "後で", "後で押す", "あとでおす"}
AUTOMATED_PREFIXES = ("<task-notification>", "<system-reminder>", "Another Claude session sent a message",
                      "Stop hook feedback", "Background (from the session", "This session is being continued",
                      "[Request interrupted", "[Cross-session", "Base directory for this skill")
SESSION_TOOLS = ("start_session", "spawn_task")
DISMISS_TOOLS = ("dismiss_task",)


def _blocks(e: dict) -> list:
    c = (e.get("message") or {}).get("content")
    return c if isinstance(c, list) else []


def _text_of(e: dict) -> str:
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    out = []
    for b in c if isinstance(c, list) else []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text") or "")
    return "\n".join(out)


def _result_text(b: dict) -> str:
    c = b.get("content")
    if isinstance(c, str):
        return c
    return "\n".join(x.get("text") or "" for x in c if isinstance(x, dict)) if isinstance(c, list) else ""


def _ts(e: dict) -> float:
    s = e.get("timestamp")
    if not isinstance(s, str):
        return 0.0
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _is_tool_result_row(e: dict) -> bool:
    return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in _blocks(e))


def starter_rows(entries: list[dict]) -> list[int]:
    """turn を始めた user の行の添字 (tool_result を運ぶ行と Stop hook の差し戻しは除く)。"""
    out = []
    for i, e in enumerate(entries):
        if e.get("type") != "user" or _is_tool_result_row(e):
            continue
        if e.get("isMeta") and _text_of(e).lstrip().startswith("Stop hook feedback"):
            continue
        out.append(i)
    return out


def owner_rows(entries: list[dict]) -> list[int]:
    """本人の発言で始まった turn の行の添字。"""
    users = [i for i in starter_rows(entries)]
    has_origin = any(isinstance(entries[i].get("origin"), dict) for i in users)
    out = []
    for i in users:
        e = entries[i]
        o = e.get("origin")
        if has_origin:
            if isinstance(o, dict) and o.get("kind") == "human":
                out.append(i)
            continue
        if e.get("isMeta"):
            continue
        if _text_of(e).lstrip().startswith(AUTOMATED_PREFIXES):
            continue
        out.append(i)
    return out


def _owner_words(e: dict) -> str:
    """本人の発言から system-reminder の塊を除いた本文。"""
    t = _text_of(e)
    t = re.sub(r"<system-reminder>.*?</system-reminder>", "", t, flags=re.S)
    return t.strip()


def short_name(title: str) -> str:
    t = title or ""
    while TAG.match(t):
        t = TAG.sub("", t, count=1)
    return t.strip() or (title or "").strip()


def _app_started_ids(task_ids: set[str], since: float, until: float | None = None) -> set[str]:
    """app の記録で、 card から起きた session (spawnedFrom.taskId) の task id。 until (epoch 秒) があれば、
    その時刻までにできた session だけ (過去の turn を流し直すときに、 その時点で押されていたかを見る)。"""
    if not task_ids:
        return set()
    base = os.environ.get("CLAUDE_DESKTOP_SESSIONS_DIR") or os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code-sessions")
    found: set[str] = set()
    try:
        paths = glob.glob(os.path.join(base, "*", "*", "local_*.json"))
    except Exception:
        return found
    for p in paths:
        try:
            if os.path.getmtime(p) < since - 120:
                continue
            with open(p, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            continue
        if "taskId" not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        sf = d.get("spawnedFrom") if isinstance(d, dict) else None
        tid = sf.get("taskId") if isinstance(sf, dict) else None
        if tid in task_ids:
            made = d.get("createdAt") if isinstance(d.get("createdAt"), (int, float)) else 0
            if until is None or (made and made / 1000.0 <= until):
                found.add(tid)
    return found


TAKEN_KINDS = {"claim", "submit", "accept", "abandoned", "done"}


def _board_roots() -> list[str]:
    env = os.environ.get("PENDING_CARDS_BOARD_ROOTS")
    if env is not None:
        return [r for r in env.split(":") if r]
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
    return glob.glob(os.path.join(base, "*")) + glob.glob(os.path.join(base, "*", "board"))


def _board_taken_ids(request_ids: set[str], until: float | None = None) -> set[str]:
    """掲示板で引き受け済みの request id (until があればその時刻までの event だけを見る)。"""
    taken: set[str] = set()
    for rid in request_ids:
        threads = set()
        for r in _board_roots():
            for f in glob.glob(os.path.join(r, "events", "*", "*", f"*--{rid}.json")):
                threads.add(os.path.dirname(f))
        last = None
        for t in threads:
            for f in glob.glob(os.path.join(t, "*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        d = json.load(fh)
                except (OSError, ValueError):
                    continue
                if not isinstance(d, dict) or d.get("request_id") != rid:
                    continue
                k = d.get("kind")
                if k not in TAKEN_KINDS and k != "release":
                    continue
                at = _ts({"timestamp": d.get("created_at")})
                if until is not None and at and at > until:
                    continue
                if last is None or at >= last[0]:
                    last = (at, k)
        if last and last[1] in TAKEN_KINDS:
            taken.add(rid)
    return taken


def cards(entries: list[dict], now: float | None = None, use_app_records: bool = True,
          app_until: float | None = None) -> list[dict]:
    """この session の card の一覧。 各要素 = {task_id, title, name, ts, row, request_id, status}。
    status = pending / started / withdrawn / expired。"""
    now = time.time() if now is None else now
    uses: dict[str, tuple[str, dict]] = {}
    found: dict[str, dict] = {}
    started: set[str] = set()
    withdrawn: set[str] = set()
    for i, e in enumerate(entries):
        if e.get("type") == "assistant":
            for b in _blocks(e):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    name = str(b.get("name") or "")
                    uses[str(b.get("id"))] = (name, b.get("input") if isinstance(b.get("input"), dict) else {})
            continue
        if e.get("type") != "user":
            continue
        for b in _blocks(e):
            if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                continue
            name, inp = uses.get(str(b.get("tool_use_id")), ("", {}))
            text = _result_text(b)
            if name.endswith(SESSION_TOOLS):
                m = PROPOSED.search(text)
                if m and m.group("tid") not in found:
                    rq = REQUEST.search(str(inp.get("prompt") or ""))
                    found[m.group("tid")] = {"task_id": m.group("tid"), "title": m.group("title"),
                                             "name": short_name(m.group("title")), "ts": _ts(e), "row": i,
                                             "request_id": rq.group(1) if rq else None}
                pid = inp.get("proposal_id")
                if pid and not b.get("is_error") and "error" not in text[:200].lower():
                    started.add(str(pid))
            elif name.endswith(DISMISS_TOOLS):
                for m in WITHDRAWN.finditer(text):
                    withdrawn.add(m.group(1))
        for m in STARTED.finditer(_text_of(e)):
            started.add(m.group(1))
    if use_app_records:
        open_ids = {t for t in found if t not in started and t not in withdrawn}
        if open_ids:
            since = min(found[t]["ts"] for t in open_ids) or 0.0
            started |= _app_started_ids(open_ids, since, app_until)
            rids = {found[t]["request_id"] for t in open_ids if found[t]["request_id"] and t not in started}
            if rids:
                done = _board_taken_ids(rids, app_until)
                started |= {t for t in open_ids if found[t]["request_id"] in done}
    out = []
    for tid, c in found.items():
        if tid in started:
            c["status"] = "started"
        elif tid in withdrawn:
            c["status"] = "withdrawn"
        elif c["ts"] and now - c["ts"] > EXPIRE_SECONDS:
            c["status"] = "expired"
        else:
            c["status"] = "pending"
        out.append(c)
    out.sort(key=lambda c: c["row"])
    return out


def unseen_pending(entries: list[dict], now: float | None = None, use_app_records: bool = True,
                   app_until: float | None = None) -> list[dict]:
    """押されておらず、 本人がまだ見ていない card (点呼に載せる card)。"""
    pend = [c for c in cards(entries, now, use_app_records, app_until) if c["status"] == "pending"]
    if not pend:
        return []
    owners = owner_rows(entries)
    starters = starter_rows(entries)
    current = starters[-1] if starters else -1
    current_is_owner = bool(owners) and owners[-1] == current
    later = current_is_owner and _owner_words(entries[current]) in LATER_WORDS
    out = []
    for c in pend:
        after = [o for o in owners if o > c["row"]]
        if not after:
            out.append(c)
        elif len(after) == 1 and after[0] == current and not later:
            out.append(c)
    return out


def pending_request_ids(entries: list[dict], now: float | None = None, use_app_records: bool = True) -> set[str]:
    """押されていない card の hand-off 文が名指す掲示板の request id (見張りが拾い直さない依頼)。"""
    return {c["request_id"] for c in cards(entries, now, use_app_records)
            if c["status"] == "pending" and c.get("request_id")}


def request_thread(rid: str) -> str | None:
    """掲示板の request id → その依頼の「project/thread」 (request の event の file の在り処から)。 無ければ None。"""
    for r in _board_roots():
        for f in glob.glob(os.path.join(r, "events", "*", "*", f"*--{rid}.json")):
            thread_dir = os.path.dirname(f)
            return os.path.basename(os.path.dirname(thread_dir)) + "/" + os.path.basename(thread_dir)
    return None


def pending_threads(entries: list[dict], now: float | None = None, use_app_records: bool = True) -> set[str]:
    """押されていない card の依頼の「project/thread」 (turn の終わりの検査が 📮 の行として問い直さない thread)。"""
    out = set()
    for rid in pending_request_ids(entries, now, use_app_records):
        t = request_thread(rid)
        if t:
            out.add(t)
    return out


def rollcall_line(unseen: list[dict]) -> str:
    names = "・".join(c["name"] for c in unseen)
    return f"{ROLLCALL_MARK} {len(unseen)} 枚: {names} — 押すか「起こして」 の一言で全部起こします"


def has_rollcall(text: str, n: int) -> bool:
    for line in (text or "").splitlines():
        if ROLLCALL_MARK in line and re.search(rf"(?<!\d){n}\s*枚", line):
            return True
    return False


def find_transcript(session_id: str) -> str | None:
    """session の id (全体か頭 8 字以上) から会話記録の file を探す (~/.claude と ~/.claude-* の projects の下)。"""
    sid = (session_id or "").strip()
    if len(sid) < 8 or not re.fullmatch(r"[0-9a-f-]+", sid):
        return None
    home = os.path.expanduser("~")
    roots = [os.path.join(home, ".claude", "projects")] + glob.glob(os.path.join(home, ".claude-*", "projects"))
    hits = []
    for r in roots:
        hits += glob.glob(os.path.join(r, "*", sid + "*.jsonl"))
    return max(hits, key=os.path.getmtime) if hits else None


def load_entries(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        return []
    return out
