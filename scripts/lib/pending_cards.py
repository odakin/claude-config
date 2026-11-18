"""pending_cards.py — この session が出した card (`start_session` の提案) を、 同じ依頼の出し直しを 1 本に結んで数え、 押されていないもの・前の turn に出したまま返事の上に流れたもの (一番下に出し直す card) を会話記録と desktop app の記録から引く部品 (点呼と出し直しの Stop hook と、 card を出した依頼を拾い直す見張りが、 同じ述語で読む)

なぜ (正本 = conventions/multi-session-coordination.md#pending-card-rollcall):
  自動の知らせや別の session の message で始まった turn では worker を直接起こせず、 card しか出せない。 card は
  出した時点の会話の中にだけ描かれ、 その後に返事が積もると最新の返事から上に流れて見えなくなる (実測)。 だから
  押されていない card は turn の終わりごとに取り下げて一番下に出し直し、 点呼の 1 行と締めの箱のボタンも残す。
  本人が「あとで」 と言った card と、 最初に出してから 7 日を過ぎた card は出し直さない。

述語:
  - card = `start_session` (旧 `spawn_task`) の結果の `Proposed "<題>" (task_id: task_…)`。 題・時刻・元の入力・
    hand-off 文の掲示板の request id (`request \\`<id>\\``) を持つ。
  - 依頼の鎖 = 同じ request id の card (request id が無ければ同じ仕事の名前 = 題から頭の `[…]` を外したもの)。
    出し直した card は前の card の続きとして数える (7 日の期限・「あとで」 は鎖の最初の card から数える)。
  - 押された = (1) app の記録で `spawnedFrom.taskId` がその id の session が在る (押した瞬間にできる、 実測)
    (2) 会話記録の「The user started your proposal task_…」 (起こした側の次の turn に遅れて届く、 実測)、 届く前は
    起こした側の app の記録に積まれた同じ文 (起きた session が消されると (1) が消える = こちらでしか分からない、 実測)
    (3) この session が `start_session` に `proposal_id` を渡して起こした (4) `dismiss_task` が押されていた・押した瞬間・
    編集して押した返事を返した (7 通りの返事の読み分け = 下の WITHDRAWN の上の注)。
  - 取り下げ = `dismiss_task` の結果の「Task task_… withdrawn」。 本人が閉じた・app に card が無い = 返事が
    「already dismissed」「No pending task」 (出し直さず点呼にも載せない)。 本人が文を編集した = 返事が
    「Not withdrawn: … edited …」 (取り下げも出し直しもせず、 点呼に残して card の上で押すか閉じるよう頼む)。
    期限切れ = 出してから 7 日 (app の期限)。
  - 掲示板で引き受け済み = card の hand-off 文が名指す request に、 誰かの claim・submit・accept・abandoned・done が
    在る (最後が release なら戻る)。 掲示板は `<base>/*/events` と `<base>/*/board/events` (`<base>` = この repo の親)
    か env PENDING_CARDS_BOARD_ROOTS (`:` 区切り)。
  - 鎖の状態 = started (どれかの card が押された・掲示板で引き受け済み) / withdrawn (最後の card が取り下げ) /
    expired (最初の card から 7 日) / later (最初の card の後に本人が「あとで」) / pending (それ以外 = 点呼に載せる)。
  - 出し直す鎖 = pending で、 最後の card が今の turn より前の turn に出たもの。 今の turn = 最後の turn を始めた
    user の行から (tool_result を運ぶ行と Stop hook の差し戻しは turn を始めない)。
  - 取り下げたまま = 点呼の差し戻し (REISSUE_HEAD を含む Stop hook の差し戻し) がその card の id を名指した後に
    取り下げ、 同じ鎖の新しい card が無い鎖 (出し直しを落とした)。
  - 2 人目になる card = 同じ鎖の card が押された後に出た、 まだ押されていない card (取り下げの結果を読む前に出し直し、
    取り下げが押されていた返事だった形)。 題か prompt に `[再起票]` があれば数えない (本人が 2 つ目を求めた)。
  - 本人の発言 = user の行のうち `origin.kind == "human"` (自動の知らせ = task-notification・別の session の message
    = peer・子の知らせ・Stop hook の差し戻しは本人の発言でない)。 origin を持たない古い記録では、 isMeta でなく
    自動の知らせの書き出しで始まらない行を本人の発言と見る。 turn の途中に打った発言 (queued_command) も読む。
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
# dismiss_task の返事は 7 通り (app 本体の表 = 画面の bundle の `{dismissed:…, already_started:…, …}`、 版 5.1231)。
# 文は app の版で変わる (旧い文も読む。 実測)。 読み分け:
#   取り下げた (dismissed)              「Task <id> withdrawn …」
#   押されていた (already_started)      「Task <id> is no longer pending …」 / 旧い文「Task <id> was already started …」
#   押した瞬間 (starting)              「The user has just clicked Start on task <id> …」
#   編集して押した (edited_start)        「Not withdrawn: the user edited the message of <id> and has just clicked Start …」
#   本人が閉じた (already_dismissed)    「Task <id> was already dismissed …」 → 出し直さず点呼にも載せない
#   card が無い (not_found)            「No pending task with id <id> … Do not re-flag it …」 → 同じ
#   本人が文を編集した (edited)          「Not withdrawn: the user edited the message of <id>, so only its card starts it …」
#                                      → 取り下げも出し直しもしない。 点呼に残し、 card の上で押すか閉じるよう頼む
WITHDRAWN = re.compile(r"Task (task_[0-9a-zA-Z]+) withdrawn")
ALREADY_STARTED = re.compile(
    r"Task (task_[0-9a-zA-Z]+) (?:was already started|is no longer pending)"
    r"|has just clicked Start on task (task_[0-9a-zA-Z]+)"
    r"|edited the message of (task_[0-9a-zA-Z]+) and has just clicked Start")
ALREADY_DISMISSED = re.compile(r"Task (task_[0-9a-zA-Z]+) was already dismissed")
NOT_FOUND = re.compile(r"No pending task with id (task_[0-9a-zA-Z]+)")
EDITED = re.compile(r"edited the message of (task_[0-9a-zA-Z]+), so only its card starts it")


def _ids(rx: re.Pattern, text: str) -> list[str]:
    """正規表現のどれかの group に入った task id。"""
    return [g for m in rx.finditer(text) for g in m.groups() if g]
TASK_ID = re.compile(r"task_[0-9a-zA-Z]+")
REQUEST = re.compile(r"request `(\d{8}T\d{6}Z-[a-z]+-[0-9a-f]{6})`")
TAG = re.compile(r"^\s*\[[^\]]*\]\s*")
EXPIRE_SECONDS = 7 * 86400
ROLLCALL_MARK = "🃏 押されていない card"
REISSUE_HEAD = "🔁 押されていない card を一番下に出し直す"
OVERRIDE = "[再起票]"
LATER_WORDS = {"あとで", "あとで押す", "後で", "後で押す", "あとでおす"}
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


def _is_stop_feedback(e: dict) -> bool:
    return bool(e.get("isMeta")) and _text_of(e).lstrip().startswith("Stop hook feedback")


def starter_rows(entries: list[dict]) -> list[int]:
    """turn を始めた user の行の添字 (tool_result を運ぶ行と Stop hook の差し戻しは除く)。"""
    out = []
    for i, e in enumerate(entries):
        if e.get("type") != "user" or _is_tool_result_row(e) or _is_stop_feedback(e):
            continue
        out.append(i)
    return out


def current_turn_start(entries: list[dict]) -> int:
    s = starter_rows(entries)
    return s[-1] if s else -1


REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
NOT_OWNER = ("<task-notification", "<cross-session-message", "Another Claude session sent a message", "Stop hook feedback",
             "Background (from the session", "This session is being continued", "[Request interrupted",
             "[Cross-session", "Base directory for this skill")


def _owner_words(e: dict) -> str:
    """本人の発言の本文 (system-reminder の塊を除く)。 turn の途中に打った発言 (queued_command の attachment) も読む。"""
    a = e.get("attachment")
    if isinstance(a, dict):
        p = a.get("prompt")
        if isinstance(p, list):
            p = " ".join(x.get("text", "") for x in p if isinstance(x, dict) and x.get("type") == "text")
        return REMINDER.sub("", str(p or "")).strip()
    return REMINDER.sub("", _text_of(e)).strip()


def owner_rows(entries: list[dict]) -> list[int]:
    """本人の発言の行の添字 (turn を始めた user の行と、 turn の途中に打った発言の attachment)。
    見分け方 = conventions/hook-authoring.md#transcript-human-vs-peer-message: origin.kind == "human" を持つ行。
    origin が human でも、 起動文 (「Background (from the session …」) と別 session の message の形の本文は外す。
    API の誤りの直後の「Try again」 (app の再試行) も外す。 origin をどの行も持たない古い記録では、 isMeta でなく
    自動の知らせの書き出しで始まらない user の行を本人の発言と見る。"""
    has_origin = any(isinstance(e.get("origin"), dict) or isinstance((e.get("attachment") or {}).get("origin"), dict)
                     for e in entries if e.get("type") in ("user", "attachment"))
    out = []
    prev_api_error = False
    for i, e in enumerate(entries):
        if e.get("type") == "assistant":
            prev_api_error = bool(e.get("isApiErrorMessage"))
            continue
        a = e.get("attachment")
        if isinstance(a, dict):
            if a.get("type") == "queued_command" and (a.get("origin") or {}).get("kind") == "human":
                t = _owner_words(e)
                if t and not any(t.startswith(x) or x in t[:200] for x in NOT_OWNER):
                    out.append(i)
            continue
        if e.get("type") != "user" or _is_tool_result_row(e) or e.get("isCompactSummary"):
            continue
        o = e.get("origin")
        if has_origin:
            if not (isinstance(o, dict) and o.get("kind") == "human"):
                continue
        elif e.get("isMeta"):
            continue
        t = _owner_words(e)
        if not t or any(t.startswith(x) or x in t[:200] for x in NOT_OWNER):
            continue
        if prev_api_error and t.startswith("Try again"):
            continue
        out.append(i)
    return out


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
        # 起こした側の記録に積まれた「The user started your proposal task_…」 (次の turn に届く前の知らせ)。 起きた
        # session を本人が消すと spawnedFrom の記録も消えるので、 こちらでしか押されたと分からない (実測)。 時刻を
        # 持たないので、 流し直し (until あり) では使わない
        if until is None and "started your proposal" in raw:
            found |= {m.group(1) for m in STARTED.finditer(raw) if m.group(1) in task_ids}
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
    """この session の card の一覧。 各要素 = {task_id, title, name, ts, row, request_id, input, key, status,
    pressed (本人が押した・起こした = 掲示板の引き受けは含まない), withdrawn_row}。
    status = pending / started / withdrawn / closed (本人が閉じた・app に card が無い) / edited (本人が文を編集した) /
    expired (started は掲示板の引き受けを含む)。"""
    now = time.time() if now is None else now
    uses: dict[str, tuple[str, dict]] = {}
    found: dict[str, dict] = {}
    started: set[str] = set()
    withdrawn: dict[str, int] = {}
    closed: set[str] = set()
    edited: set[str] = set()
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
                    title = m.group("title")
                    rid = rq.group(1) if rq else None
                    found[m.group("tid")] = {"task_id": m.group("tid"), "title": title, "name": short_name(title),
                                             "ts": _ts(e), "row": i, "request_id": rid, "input": dict(inp),
                                             "key": ("request:" + rid) if rid else ("name:" + short_name(title))}
                pid = inp.get("proposal_id")
                if pid and not b.get("is_error") and "error" not in text[:200].lower():
                    started.add(str(pid))
            elif name.endswith(DISMISS_TOOLS):
                for m in WITHDRAWN.finditer(text):
                    withdrawn.setdefault(m.group(1), i)
                started.update(_ids(ALREADY_STARTED, text))
                closed.update(_ids(ALREADY_DISMISSED, text) + _ids(NOT_FOUND, text))
                edited.update(_ids(EDITED, text))
        for m in STARTED.finditer(_text_of(e)):
            started.add(m.group(1))
    if use_app_records:
        open_ids = {t for t in found if t not in started and t not in withdrawn and t not in closed}
        if open_ids:
            since = min(found[t]["ts"] for t in open_ids) or 0.0
            started |= _app_started_ids(open_ids, since, app_until)
    board_done: set[str] = set()
    if use_app_records:
        rids = {c["request_id"] for t, c in found.items()
                if c["request_id"] and t not in started and t not in withdrawn}
        if rids:
            taken = _board_taken_ids(rids, app_until)
            board_done = {t for t, c in found.items() if c["request_id"] in taken}
    out = []
    for tid, c in found.items():
        c["pressed"] = tid in started
        c["withdrawn_row"] = withdrawn.get(tid)
        if tid in started or tid in board_done:
            c["status"] = "started"
        elif tid in withdrawn:
            c["status"] = "withdrawn"
        elif tid in closed:
            c["status"] = "closed"
        elif c["ts"] and now - c["ts"] > EXPIRE_SECONDS:
            c["status"] = "expired"
        elif tid in edited:
            c["status"] = "edited"
        else:
            c["status"] = "pending"
        out.append(c)
    out.sort(key=lambda c: c["row"])
    return out


def chains(entries: list[dict], now: float | None = None, use_app_records: bool = True,
           app_until: float | None = None, cs: list[dict] | None = None) -> list[dict]:
    """同じ依頼の card を 1 本に結んだ鎖の一覧。 各要素 = {key, name, request_id, cards (出した順), latest,
    origin_ts, status}。 status = started / withdrawn / closed / expired / later / edited / pending。"""
    now = time.time() if now is None else now
    cs = cards(entries, now, use_app_records, app_until) if cs is None else cs
    by: dict[str, list[dict]] = {}
    for c in cs:
        by.setdefault(c["key"], []).append(c)
    later_rows = [o for o in owner_rows(entries) if _owner_words(entries[o]) in LATER_WORDS]
    out = []
    for key, group in by.items():
        group.sort(key=lambda c: c["row"])
        first, latest = group[0], group[-1]
        origin = first["ts"] or 0.0
        if any(c["status"] == "started" for c in group):
            st = "started"
        elif latest["status"] == "withdrawn":
            st = "withdrawn"
        elif latest["status"] == "closed":
            st = "closed"
        elif latest["status"] == "expired" or (origin and now - origin > EXPIRE_SECONDS):
            st = "expired"
        elif any(o > first["row"] for o in later_rows):
            st = "later"
        elif latest["status"] == "edited":
            st = "edited"
        else:
            st = "pending"
        out.append({"key": key, "name": latest["name"], "request_id": latest["request_id"], "cards": group,
                    "latest": latest, "origin_ts": origin, "status": st})
    out.sort(key=lambda ch: ch["latest"]["row"])
    return out


def active_chains(chs: list[dict]) -> list[dict]:
    """点呼に載せる鎖 (押されていない・取り下げていない・本人が閉じていない・7 日の内・「あとで」 と言われていない。
    本人が文を編集した card も載せる = card の上で押してもらう)。"""
    return [ch for ch in chs if ch["status"] in ("pending", "edited")]


def edited_chains(chs: list[dict]) -> list[dict]:
    """本人が文を編集した card の鎖 (取り下げも出し直しもしない。 app の返事 = card の上で押すか閉じるよう頼む)。"""
    return [ch for ch in chs if ch["status"] == "edited"]


def reissue_due(entries: list[dict], chs: list[dict]) -> list[dict]:
    """一番下に出し直す鎖 = 点呼に載せる鎖のうち、 最後の card が今の turn より前の turn に出たもの (編集された card は除く)。"""
    start = current_turn_start(entries)
    return [ch for ch in chs if ch["status"] == "pending" and ch["latest"]["row"] < start]


def to_withdraw(ch: dict) -> list[dict]:
    """出し直すときに取り下げる card (その鎖の、 押されていない・取り下げていない・期限の内の card 全部)。"""
    return [c for c in ch["cards"] if c["status"] == "pending"]


def second_worker_cards(chs: list[dict], now: float | None = None) -> list[dict]:
    """押すと同じ依頼の 2 人目になる card = 同じ鎖の card が押された後に出た、 押されていない card。"""
    now = time.time() if now is None else now
    out = []
    for ch in chs:
        pressed_rows = [c["row"] for c in ch["cards"] if c.get("pressed")]
        if not pressed_rows:
            continue
        for c in ch["cards"]:
            if c.get("pressed") or c.get("withdrawn_row") is not None or c["row"] < min(pressed_rows):
                continue
            inp = c.get("input") or {}
            if OVERRIDE in (c["title"] or "") or OVERRIDE in str(inp.get("prompt") or ""):
                continue
            if c["ts"] and now - c["ts"] > EXPIRE_SECONDS:
                continue
            out.append(c)
    return out


def reissue_feedback_rows(entries: list[dict], since: int = -1) -> list[int]:
    """点呼の差し戻し (この hook が出した出し直しの指示) の行。"""
    return [i for i, e in enumerate(entries) if i > since and _is_stop_feedback(e) and REISSUE_HEAD in _text_of(e)]


def dropped_chains(entries: list[dict], chs: list[dict], now: float | None = None) -> list[dict]:
    """出し直しを落とした鎖 = 今の turn の点呼の差し戻しが名指した card を取り下げ、 同じ鎖の新しい card が無いもの。"""
    now = time.time() if now is None else now
    start = current_turn_start(entries)
    fb = reissue_feedback_rows(entries, start)
    if not fb:
        return []
    named: dict[str, int] = {}
    for r in fb:
        for t in TASK_ID.findall(_text_of(entries[r])):
            named.setdefault(t, r)
    out = []
    for ch in chs:
        if ch["status"] != "withdrawn":
            continue
        last = ch["latest"]
        r = named.get(last["task_id"])
        if r is not None and last.get("withdrawn_row") is not None and last["withdrawn_row"] > r:
            if not (ch["origin_ts"] and now - ch["origin_ts"] > EXPIRE_SECONDS):
                out.append(ch)
    return out


def pending_request_ids(entries: list[dict], now: float | None = None, use_app_records: bool = True) -> set[str]:
    """押されていない card の hand-off 文が名指す掲示板の request id (見張りが拾い直さない依頼)。"""
    return {c["request_id"] for c in cards(entries, now, use_app_records)
            if c["status"] in ("pending", "edited") and c.get("request_id")}


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


def rollcall_line(active: list[dict]) -> str:
    names = "・".join(ch["name"] for ch in active)
    tail = "起こします" if len(active) == 1 else "全部起こします"
    return f"{ROLLCALL_MARK} {len(active)} 枚: {names} — 押すか「起こして」 の一言で{tail}"


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
