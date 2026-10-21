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
  PreToolUse(Agent / Task)    BOARD_FIRST の機械の desktop の session で、 掲示板の worker (prompt に role と request id) か
                              Fable の Agent tool の呼び出しを止める (subagent は一覧に出ない)。 `[subagent-ok: 理由]` で通す。
  PreToolUse(SendMessage)     宛先が台帳で未解決の session なら app の記録を読み直す。 合っていれば通し、 違えば止める。
                              本人がその model でよいと言ったなら message に `[model-ok]` を入れれば通る (= 本人が app で
                              model を変えた場合を止め続けない)。
  PreToolUse(set_session_model / set_session_effort)  PREMIUM_GATE の機械で、 Fable (上位 tier) か max への引き上げは、
                              起こした時の理由 (台帳) か本人の直近の名指しが無いと止める。

BOARD_FIRST: `~/.claude/session-launch-board-first.on` が在るか env SESSION_LAUNCH_BOARD_FIRST=1 のとき、 initiation が
user_asked の start_session は prompt に掲示板の request id が無いと止める (title か prompt に `[no-board]` で通す)。
hand-off が掲示板の依頼を名指すのにこの機械に起動の記録が無い start_session (本人が押す card も) も止め、
`board.py launch --request <id>` で記録と引数を作らせる (相手側の AI が出した依頼・別の機械で出した依頼)。
既定は off (層1 の利用者が掲示板を使うとは限らない)。 起動の記録は whole-repo の掲示板なら `<root>/.local/outbox`、
project の repo の中の掲示板なら `<git common dir>/board-outbox/<path>` (board.py の outbox_dir と同じ)。

PREMIUM_GATE: `~/.claude/session-launch-premium-gate.on` が在るか env SESSION_LAUNCH_PREMIUM_GATE=1 のとき、 上位 tier
(Fable) か effort max を頼む start_session (card も。 引数・hand-off の「must/should run on … at … effort」・title の
`[model: …]` のどれかで) と、 そこへ上げる set_session_model / set_session_effort を、 本人の直近 3 回の発言の名指し
(打ち消し・疑いの文は数えない) か理由 (`[model-reason: …]` / `[effort-reason: …]`、 掲示板の記録の reason、
`--note-reason`) が無いと止める。 仕事の性質を語で判定はしない (実測 = 人が選んだ model を依頼の語の規則で当てると、 どの規則も
外れた)。 既定は off。 規約 = conventions/multi-session-coordination.md#premium-launch-reason。

故障は通す (読めない入力・記録が見つからない・例外 = exit 0)。 止めるのは条件が成り立った時だけ。
env: SESSION_LAUNCH_CHECK_DISABLE=1 / SESSION_LAUNCH_STATE_DIR (test) / CLAUDE_DESKTOP_SESSIONS_DIR (test) /
     SESSION_LAUNCH_BOARD_FIRST_MARKER / SESSION_LAUNCH_PREMIUM_GATE_MARKER (test: the markers' paths) /
     SESSION_LAUNCH_WAIT (記録を待つ秒、 既定 3)。
self-test: python3 scripts/session-launch-check.py --selftest
理由を後から残す: python3 scripts/session-launch-check.py --note-reason <local_…> '<理由>'
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

def board_named(prompt: str) -> tuple[str, str]:
    """(request id, board root) a hand-off names, or ('', '')."""
    rid, root = REQUEST_ID.search(prompt or ""), BOARD_ROOT.search(prompt or "")
    if not rid or not root:
        return "", ""
    return rid.group(1), os.path.expanduser(root.group(1).rstrip("`'\").,;:"))


def outbox_dirs(root: str) -> list[str]:
    """Where board.py keeps a board's outbox (board.py outbox_dir): `<root>/.local/outbox` for a whole-repo board, else
    `<git common dir>/board-outbox/<path of the board in its repo>`. Reading only the first missed every record of a
    board inside a project repo (measured: a co-author board's records were all under .git/board-outbox/)."""
    out = [os.path.join(root, ".local", "outbox")]
    try:
        import subprocess
        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=5).stdout.strip()
        common, prefix = git("rev-parse", "--path-format=absolute", "--git-common-dir"), git("rev-parse", "--show-prefix")
        if common:
            out.append(os.path.join(common, "board-outbox", prefix.rstrip("/").replace("/", "_") or "root"))
    except Exception:
        pass
    return out


def board_launch_record(prompt: str) -> dict | None:
    rid, root = board_named(prompt)
    if not rid:
        return None
    for d in outbox_dirs(root):
        p = os.path.join(d, rid + ".launch.json")
        try:
            with open(p, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            rec.setdefault("_path", p)
            return rec
    return None


def board_first_on() -> bool:
    marker = os.environ.get("SESSION_LAUNCH_BOARD_FIRST_MARKER") or os.path.expanduser("~/.claude/session-launch-board-first.on")
    return os.environ.get("SESSION_LAUNCH_BOARD_FIRST") == "1" or os.path.exists(marker)


# ---- premium gate (top tier / max effort need a stated reason) ----

PREMIUM_RULE = "claude-config/conventions/multi-session-coordination.md#premium-launch-reason"
MODEL_REASON = re.compile(r"\[model-reason:\s*([^\]]{12,})\]")
EFFORT_REASON = re.compile(r"\[effort-reason:\s*([^\]]{12,})\]")
RUN_LINE = re.compile(r"(?:must|should) run on (claude-[a-z0-9.-]+|fable|opus|sonnet|haiku|mythos)\b([^.\n]{0,40}?\bat ([a-z]+) effort)?", re.I)
TITLE_TAG = re.compile(r"\[model:\s*([^\]]+)\]", re.I)
NAMES_TOP = re.compile(r"fable|フェイブル|mythos", re.I)
NAMES_MAX = re.compile(r"(?<![a-z-])max(?![a-z-])|マックス", re.I)
# 名指しでなく打ち消し・疑い (「要らん」「じゃなくて大丈夫？」) を名指しと数えない = 迷えば理由を求める側に倒す
NEGATED = re.compile(r"要らん|要らな|いらん|いらな|不要|じゃなく|ではなく|でなく|やめ|使わな|もったいな|過剰")
GENERATED_PROMPT = ("<command-", "<local-command", "<task-notification>", "<cross-session-message", "Another Claude session",
                    "Stop hook feedback", "Base directory for this skill", "Caveat:", "<system-reminder>", "[Request interrupted")
OWNER_WINDOW = 3


def premium_gate_on() -> bool:
    marker = os.environ.get("SESSION_LAUNCH_PREMIUM_GATE_MARKER") or os.path.expanduser("~/.claude/session-launch-premium-gate.on")
    return os.environ.get("SESSION_LAUNCH_PREMIUM_GATE") == "1" or os.path.exists(marker)


def premium_asked(ti: dict) -> tuple[bool, bool, list[str]]:
    """(top tier asked, max effort asked, where): the start_session arguments, the hand-off's run line ("must/should run
    on <model> at <effort> effort") and the card's title tag `[model: …]`. A card that named Fable max only in its title
    and its hand-off prose still started a Fable-max request (measured)."""
    top, mx, where = False, False, []
    if tier(str(ti.get("model") or "")) == "fable":
        top = True; where.append(f"model 引数 {ti.get('model')}")
    if str(ti.get("effort") or "").lower() == "max":
        mx = True; where.append("effort 引数 max")
    for m in RUN_LINE.finditer(ti.get("prompt") or ""):
        if tier(m.group(1)) == "fable":
            top = True; where.append(f"prompt「run on {m.group(1)}」")
        if (m.group(3) or "").lower() == "max":
            mx = True; where.append("prompt「at max effort」")
    for m in TITLE_TAG.finditer(ti.get("title") or ""):
        words = re.split(r"[\s/]+", m.group(1).strip().lower())
        if any(tier(w) == "fable" for w in words):
            top = True; where.append(f"title [model: {m.group(1).strip()}]")
        if "max" in words:
            mx = True; where.append(f"title [model: {m.group(1).strip()}] の max")
    return top, mx, list(dict.fromkeys(where))


def owner_prompts(path: str, last: int = OWNER_WINDOW) -> list[str]:
    """The owner's own last `last` prompts in a Claude transcript (typed by the person: no tool results, meta lines,
    compact summaries, other sessions' messages, hook feedback or skill bodies; a prompt queued mid-turn counts)."""
    out: list[str] = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return out
    with fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict) or e.get("isMeta") or e.get("isSidechain") or e.get("isCompactSummary"):
                continue
            text = ""
            if e.get("type") == "user":
                if e.get("turnOrigin") not in (None, "human") or e.get("promptSource") == "system":
                    continue
                c = (e.get("message") or {}).get("content")
                if isinstance(c, str):
                    text = c
                elif isinstance(c, list) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                    text = "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            elif e.get("type") == "attachment":
                a = e.get("attachment") or {}
                if (isinstance(a, dict) and a.get("type") == "queued_command" and a.get("commandMode") == "prompt"
                        and isinstance(a.get("origin"), dict) and a["origin"].get("kind") == "human"):
                    p = a.get("prompt")
                    text = p if isinstance(p, str) else "".join(
                        b.get("text", "") for b in (p or []) if isinstance(b, dict) and b.get("type") == "text")
            text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text or "", flags=re.S).strip()
            if text and not text.startswith(GENERATED_PROMPT):
                out.append(text)
    return out[-last:]


def _mentions(rx: re.Pattern, t: str) -> list[bool]:
    """One bool per mention of the word: False when its own sentence goes on to negate or doubt it (「Fable Max 要らんやろ」
    「Fable じゃなくて大丈夫？」). Only the span from the word to the end of its sentence or clause (。？！ or a colon, at most
    20 characters on) is read: a long request that names Fable Max and negates something else further on is a naming
    (measured)."""
    out = []
    for m in rx.finditer(t):
        stop = re.search(r"[。？?！!：:\n]", t[m.end():m.end() + 20])
        span = t[m.start():m.end() + (stop.start() if stop else 20)]
        out.append(not NEGATED.search(span))
    return out


def owner_named(path: str) -> tuple[bool, bool, str]:
    """(named the top tier, named max, the message) in the owner's last prompts; the owner's latest word on each wins,
    and a message whose mention is negated or doubted is not a naming."""
    top, mx, quote = False, False, ""
    for t in owner_prompts(path):   # oldest first
        for rx, which in ((NAMES_TOP, "top"), (NAMES_MAX, "max")):
            states = _mentions(rx, t)
            if not states:
                continue
            yes = all(states)
            if which == "top":
                top = yes
            else:
                mx = yes
            quote = t if yes else quote
    return top, mx, quote[:120]


def premium_missing(top: bool, mx: bool, text: str, transcript: str, rec_reason: str = "") -> list[str]:
    """What is missing for a top-tier / max launch: [] when the owner named it in their last prompts, or a reason token
    (or a reason the board's launch record carries) stands for it."""
    named_top, named_max, _ = owner_named(transcript)
    miss = []
    if top and not (named_top or MODEL_REASON.search(text) or rec_reason):
        miss.append("Fable")
    if mx and not (named_max or EFFORT_REASON.search(text) or rec_reason):
        miss.append("max")
    return miss


def premium_refusal(miss: list[str], where: list[str]) -> str:
    return ("🛑 session-launch-check: " + " と ".join(miss) + " を選ぶには理由が要る (この機械の設定 = 高い model と effort は理由つきで選ぶ)。"
            f" 頼んだ所 = {' / '.join(where) or '?'}。 本人の直近 {OWNER_WINDOW} 回の発言に名指しが無い。\n"
            "  先に問う: この仕事は、 worker 自身が物理の中身 (導出・式の展開・議論が正しいか・どう述べるか) を判断し、 生み出すか。"
            " 与えられた前後の文や明示の基準に照らして読む仕事 (英文の検品・記法の置換・規則や道具の直し・RCA) なら、"
            " 一段下の model と effort (例 = Opus xhigh) で起こす。\n"
            "  要るなら理由を書いて出し直す: Fable = [model-reason: worker が何を導出・判断するか]、 max = [effort-reason: なぜ xhigh で"
            " 届かないか] を title か prompt に (掲示板の request なら --reason)。 起こした後の set_session_model / set_session_effort で"
            " 上げる時も、 起こした時の理由か本人の名指しが要る (理由を後から残す = python3 ~/Claude/claude-config/scripts/"
            "session-launch-check.py --note-reason <local_…> '<理由>')。 本人に聞くなら 1 行で: 何を・どの model と effort で・なぜ。"
            f" 規約 = {PREMIUM_RULE}")


def pre_start(inp: dict) -> tuple[int, str]:
    ti = inp.get("tool_input") or {}
    if ti.get("proposal_id") and not ti.get("prompt"):
        return 0, ""
    prompt, title = ti.get("prompt") or "", ti.get("title") or ""
    rid, root = board_named(prompt)
    rec = board_launch_record(prompt)
    if board_first_on() and NO_BOARD not in title + prompt:
        if ti.get("initiation") == "user_asked" and not REQUEST_ID.search(prompt):
            return 2, ("🛑 session-launch-check: worker は掲示板の request を経て起こす (この機械の設定 = 掲示板を経路の軸にする)。\n"
                       "  1. board.py request … --to claude --to-session role-<project>-<仕事> --surface desktop で依頼を出す\n"
                       "  2. 出力の start_session の引数 (model・effort・title・prompt) で起こす\n"
                       f"  掲示板を通さない理由があるなら title か prompt に {NO_BOARD} と理由を書いて出し直す。 規約 = {RULE}")
        if rid and rec is None:
            # A card or a start written by hand for a request someone else posted (a co-author's AI, another machine) has
            # no launch record here, so neither the model nor the effort was checked against anything (measured: a card
            # for a co-author's review request went out as Fable max by hand).
            return 2, (f"🛑 session-launch-check: この hand-off は掲示板の依頼 {rid} を名指すが、 この機械に起動の記録が無い"
                       " (相手側の AI や別の機械が出した依頼)。 手で書いた引数は model・effort を何とも照合しない。\n"
                       f"  python3 ~/Claude/ai-collaboration/board/board.py launch --root {root} --request {rid} --agent claude --session <自分の id>"
                       " [--expect-model … --effort … --reason '…'] で記録と start_session の引数を作り、 出た引数で起こす"
                       " (本人が押す card なら initiation だけ own_initiative に替える)。"
                       f" 掲示板を通さない理由があるなら {NO_BOARD} と理由。 規約 = {RULE}")
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
    if premium_gate_on():
        top, mx, where = premium_asked(ti)
        if rec and tier(rec.get("model") or "") == "fable":
            top = True; where.append(f"掲示板の記録 model {rec.get('model')}")
        if rec and (rec.get("effort") or "").lower() == "max":
            mx = True; where.append("掲示板の記録 effort max")
        if top or mx:
            miss = premium_missing(top, mx, title + " " + prompt, inp.get("transcript_path") or "", (rec or {}).get("reason") or "")
            if miss:
                return 2, premium_refusal(miss, where)
    return 0, ""


def pre_set(inp: dict) -> tuple[int, str]:
    """set_session_model to the top tier / set_session_effort to max: the reason the launch carried (the ledger), or the
    owner's naming in their last prompts. The app caps a start at the launcher's model, so the raise happens here
    (measured: the owner refused the raise of a card's worker to Fable here)."""
    if not premium_gate_on():
        return 0, ""
    ti = inp.get("tool_input") or {}
    local_id = ti.get("session_id") or ""
    top = bool(ti.get("model")) and tier(str(ti["model"])) == "fable"
    mx = str(ti.get("effort") or "").lower() == "max"
    if not (top or mx):
        return 0, ""
    entries = load(inp.get("session_id") or "")
    hit = next((e for e in entries if local_id and e.get("local_id") == local_id), None)
    if hit is None and local_id:
        rec = ds.find(local_id) or {}
        title = rec.get("title") or ""
        hit = next((e for e in reversed(entries) if title and e.get("title") == title and e.get("reason")), None)
    miss = premium_missing(top, mx, "", inp.get("transcript_path") or "", (hit or {}).get("reason") or "")
    if not miss:
        return 0, ""
    what = (f"model {ti.get('model')}" if top else "") + (" / " if top and mx else "") + ("effort max" if mx else "")
    return 2, premium_refusal(miss, [f"{local_id} を {what} に上げる"])


def launch_reason(ti: dict) -> str:
    """The reason a launch gave for the top tier or max (a token in title/prompt, or the board's launch record)."""
    text = (ti.get("title") or "") + " " + (ti.get("prompt") or "")
    m = MODEL_REASON.search(text) or EFFORT_REASON.search(text)
    return (m.group(1).strip() if m else "") or ((board_launch_record(ti.get("prompt") or "") or {}).get("reason") or "")


def post_start(inp: dict) -> str:
    text = flatten(inp.get("tool_response"))
    ti = inp.get("tool_input") or {}
    task = re.search(r"task_id: (task_[0-9a-z]+)", text)
    if task and "Started session" not in text and ti.get("title"):
        # A card: no session until the owner clicks it, so the later raise (set_session_model) finds the card by title.
        reason = launch_reason(ti)
        if reason:
            upsert(inp.get("session_id") or "", "proposal:" + task.group(1), title=ti["title"], reason=reason, state="proposal")
        return ""
    m = ds.LOCAL_RE.search(text)
    if not m or "Started session" not in text:
        return ""
    local_id = m.group(0)
    want_m, want_e = requested(ti)
    reason = launch_reason(ti)
    if reason:
        upsert(inp.get("session_id") or "", local_id, reason=reason, title=ti.get("title") or "")
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


AGENT_OK = "[subagent-ok"


def pre_agent(inp: dict) -> tuple[int, str]:
    """BOARD_FIRST machines, desktop sessions: an Agent tool call that is a board worker (its prompt names a role and a
    request) or runs on the top tier (Fable = the owner's physics workers) is stopped once. A subagent is not listed in
    the app, so the owner cannot see or talk to it (measured twice: "throw it to an agent" became a subagent).
    `[subagent-ok: <reason>]` in the description or prompt passes work the owner does not watch."""
    if not board_first_on() or os.environ.get("CLAUDE_CODE_ENTRYPOINT") != "claude-desktop":
        return 0, ""
    ti = inp.get("tool_input") or {}
    text = (ti.get("description") or "") + " " + (ti.get("prompt") or "")
    if AGENT_OK in text:
        return 0, ""
    why = []
    rec = board_launch_record(text)
    if (rec or {}).get("surface") == "agent":   # the request itself asked for a subagent (--surface agent)
        return 0, ""
    if REQUEST_ID.search(text) and "role-" in text:
        why.append("prompt が掲示板の request の worker (role と request id)")
    if tier(str(ti.get("model") or "")) == "fable":
        why.append(f"model = {ti.get('model')} (Fable の仕事 = 本人に見せる worker)")
    if not why:
        return 0, ""
    return 2, ("🛑 session-launch-check: Agent tool の subagent は app の一覧に出ない = 本人が見ることも話しかけることもできない。 "
               + " / ".join(why) + "。\n"
               "  本人に見せる worker は、 掲示板の request (desktop の session からは既定で desktop) → 出力の引数で start_session。"
               " 既に request を出したなら、 その出力の start_session の引数で起こす。\n"
               f"  本人が見ない手元の調査・検算なら description か prompt に {AGENT_OK}: 理由] を書いて出し直す"
               " (掲示板で受けるなら request は --surface agent)。 規約 = " + RULE)


def route(inp: dict) -> str:
    ev, tool = inp.get("hook_event_name") or "", inp.get("tool_name") or ""
    if tool.endswith("__start_session"):
        return "pre-start" if ev == "PreToolUse" else ("post-start" if ev == "PostToolUse" else "")
    if tool.endswith("__set_session_model") or tool.endswith("__set_session_effort"):
        return "post-set" if ev == "PostToolUse" else ("pre-set" if ev == "PreToolUse" else "")
    if ev == "PreToolUse" and tool == "SendMessage":
        return "pre-send"
    if ev == "PreToolUse" and tool in ("Agent", "Task"):
        return "pre-agent"
    return ""


def emit_context(ev: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": ev, "additionalContext": text}}, ensure_ascii=False))


def run(inp: dict) -> int:
    mode = route(inp)
    if mode == "pre-start":
        rc, txt = pre_start(inp)
    elif mode == "pre-send":
        rc, txt = pre_send(inp)
    elif mode == "pre-agent":
        rc, txt = pre_agent(inp)
    elif mode == "pre-set":
        rc, txt = pre_set(inp)
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
                          SESSION_LAUNCH_WAIT="0", SESSION_LAUNCH_BOARD_FIRST_MARKER=os.path.join(td, "no-marker"))
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

        os.environ["SESSION_LAUNCH_BOARD_FIRST"] = "1"
        saved_ep = os.environ.get("CLAUDE_CODE_ENTRYPOINT")
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "claude-desktop"
        rc, _, err = call("PreToolUse", "Agent", {"description": "design study", "model": "fable", "run_in_background": True,
                                                  "prompt": handoff})
        check("pre-agent: a Fable board worker as a subagent → blocked", rc == 2 and "start_session" in err)
        rc, _, _ = call("PreToolUse", "Agent", {"description": "env probe", "model": "haiku", "prompt": "print env names"})
        check("pre-agent: a small local probe → pass", rc == 0)
        rc, _, _ = call("PreToolUse", "Agent", {"description": "[subagent-ok: 手元の検算] check", "model": "fable", "prompt": "x"})
        check("pre-agent: [subagent-ok: …] → pass", rc == 0)
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
        rc, _, _ = call("PreToolUse", "Agent", {"description": "d", "model": "fable", "prompt": handoff})
        check("pre-agent: not a desktop session → pass", rc == 0)
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "claude-desktop"
        with open(os.path.join(board, ".local", "outbox", rid + ".launch.json"), "w", encoding="utf-8") as fh:
            json.dump({"model": "claude-opus-5-5", "surface": "agent"}, fh)
        rc, _, _ = call("PreToolUse", "Agent", {"description": "d", "model": "opus", "prompt": handoff})
        check("pre-agent: the request was posted with --surface agent → pass", rc == 0)
        if saved_ep is None:
            os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)
        else:
            os.environ["CLAUDE_CODE_ENTRYPOINT"] = saved_ep
        os.environ.pop("SESSION_LAUNCH_BOARD_FIRST", None)

        # ---- premium gate: the measured card (a co-author's prose review sent out as Fable max by hand)
        tr = os.path.join(td, "launcher.jsonl")

        def owner_said(*texts: str) -> None:
            rows = [{"type": "user", "message": {"role": "user", "content": "Stop hook feedback: Fable max"}, "isMeta": True},
                    {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "Fable"}]}}]
            rows += [{"type": "user", "message": {"role": "user", "content": t}} for t in texts]
            with open(tr, "w", encoding="utf-8") as fh:
                fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

        card = {"initiation": "own_initiative", "title": "[local推奨] [model: fable max] 共著者の英文の直しの検品",
                "prompt": f"You are the board worker for role `role-p-r`, request `{rid}` on the p board (`--root {os.path.join(td, 'nob')}`);"
                          " execute it yourself. This window should run on Fable at max effort.\n0. …"}

        def start(ti: dict, sid: str = "launcher-5") -> tuple[int, str]:
            inp = {"hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__start_session", "tool_input": ti,
                   "session_id": sid, "transcript_path": tr}
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = run(inp)
            return rc, err.getvalue()

        owner_said("続きをやって", "締めて")
        os.environ["SESSION_LAUNCH_PREMIUM_GATE_MARKER"] = os.path.join(td, "no-premium-marker")
        check("premium: gate off by default → the card passes", start(card)[0] == 0)
        os.environ["SESSION_LAUNCH_PREMIUM_GATE"] = "1"
        rc, err = start(card)
        check("premium: the measured card (title + prose say Fable max, owner never named it) → blocked on both",
              rc == 2 and "Fable と max" in err and "物理の中身" in err)
        check("premium_asked reads title tag and prose", premium_asked(card)[:2] == (True, True))
        owner_said("これは Fable Max の worker に投げて")
        check("premium: the owner named Fable Max in a recent prompt → pass", start(card)[0] == 0)
        owner_said("これは Fable Max の worker に投げて", "この仕事に Fable Max は要らない。")
        check("premium: the owner's latest word negates → blocked again", start(card)[0] == 2)
        owner_said("下書きは Fable じゃなくて大丈夫？")
        fable_only = dict(card, title="[local推奨] [model: fable xhigh] 付録の下書き", prompt=card["prompt"].replace("at max effort", "at xhigh effort"))
        check("premium: a doubt is not a naming → blocked", start(fable_only)[0] == 2)
        owner_said("次の仕事を Fable Max の worker に投げて：  段落は 1 つじゃなくて 2 つに。 5 点目は要らない。")
        check("premium: a naming whose request negates something else further on → pass", start(card)[0] == 0)
        owner_said("締めて")
        reasons = dict(card, prompt=card["prompt"] + " [model-reason: 新しい極限の式を worker が導出し直す] [effort-reason: 長い導出を 1 回の turn で通す]")
        check("premium: both reason tokens → pass", start(reasons)[0] == 0)
        half = dict(card, prompt=card["prompt"] + " [model-reason: 新しい極限の式を worker が導出し直す]")
        rc, err = start(half)
        check("premium: a model reason does not cover max → blocked on max only", rc == 2 and "max を選ぶ" in err and "Fable と" not in err)
        cheap = {"initiation": "own_initiative", "title": "[local推奨] [model: opus xhigh] 検品", "prompt": "This window should run on Opus at xhigh effort."}
        check("premium: Opus xhigh → pass", start(cheap)[0] == 0)
        for t in ("[Request interrupted by user for tool use]", "<command-name>/model</command-name> fable"):
            owner_said(t)
            if start(card)[0] != 2:
                check(f"premium: a generated user line is not a naming ({t[:20]})", False)

        def setter(tool: str, ti: dict, sid: str = "launcher-5") -> int:
            inp = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "session_id": sid, "transcript_path": tr}
            with contextlib.redirect_stderr(io.StringIO()):
                return run(inp)

        owner_said("締めて")
        lid2 = "local_aaaaaaaa-0000-4000-8000-000000000003"
        check("premium: raising a worker to Fable with no reason → blocked",
              setter("mcp__ccd_session_mgmt__set_session_model", {"session_id": lid2, "model": "claude-fable-5-1"}) == 2)
        check("premium: raising effort to max with no reason → blocked",
              setter("mcp__ccd_session_mgmt__set_session_effort", {"session_id": lid2, "effort": "max"}) == 2)
        check("premium: lowering is never stopped",
              setter("mcp__ccd_session_mgmt__set_session_model", {"session_id": lid2, "model": "claude-opus-5-5"}) == 0)
        upsert("launcher-5", lid2, reason="新しい極限の式を worker が導出し直す")
        check("premium: a noted reason lets the raise through",
              setter("mcp__ccd_session_mgmt__set_session_model", {"session_id": lid2, "model": "claude-fable-5-1"}) == 0)
        rc, _, _ = call("PostToolUse", "mcp__ccd_session__start_session", reasons,
                        'Proposed "[local推奨] [model: fable max] 共著者の英文の直しの検品" (task_id: task_000000bb).', sid="launcher-6")
        with open(os.path.join(app, lid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"sessionId": lid, "model": "claude-opus-5-5", "effort": "xhigh", "title": reasons["title"]}, fh)
        check("premium: a clicked card's worker is found by its title and its card's reason",
              setter("mcp__ccd_session_mgmt__set_session_model", {"session_id": lid, "model": "claude-fable-5-1"}, sid="launcher-6") == 0)
        os.environ.pop("SESSION_LAUNCH_PREMIUM_GATE", None)

        # ---- a hand-off naming a request with no launch record here (BOARD_FIRST)
        os.environ["SESSION_LAUNCH_BOARD_FIRST"] = "1"
        rc, err = start(dict(card, title="共著者の英文の直しの検品"))
        check("board-first: a card for a request with no launch record here → blocked, board.py launch", rc == 2 and "board.py launch" in err)
        rc, _ = start(dict(card, title="検品 [no-board] 相手側の依頼を手で", prompt=card["prompt"]))
        check("board-first: [no-board] still passes", rc == 0)
        os.environ.pop("SESSION_LAUNCH_BOARD_FIRST", None)

        # ---- a board inside a project repo keeps its records under the git common dir
        import subprocess
        repo = os.path.join(td, "proj")
        os.makedirs(os.path.join(repo, "board"))
        subprocess.run(["git", "init", "-q", repo], check=True)
        common = os.path.join(repo, ".git", "board-outbox", "board")
        os.makedirs(common)
        with open(os.path.join(common, rid + ".launch.json"), "w", encoding="utf-8") as fh:
            json.dump({"model": "opus", "effort": "xhigh", "surface": "desktop"}, fh)
        got = board_launch_record(f"request `{rid}` (`--root {os.path.join(repo, 'board')}`)")
        check("outbox: a project board's record under .git/board-outbox is found (backticks stripped)",
              bool(got) and got.get("model") == "opus")
        for k in ("SESSION_LAUNCH_PREMIUM_GATE_MARKER",):
            os.environ.pop(k, None)
        check("route ignores other tools", route({"hook_event_name": "PreToolUse", "tool_name": "Bash"}) == "")
        for k in ("SESSION_LAUNCH_STATE_DIR", "CLAUDE_DESKTOP_SESSIONS_DIR", "SESSION_LAUNCH_WAIT", "SESSION_LAUNCH_BOARD_FIRST_MARKER"):
            os.environ.pop(k, None)
    print("selftest:", "PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


def note_reason(argv: list[str]) -> int:
    """`--note-reason <local_…> '<reason>'`: keep a reason for raising a session that was started without one (the
    launcher's session = CLAUDE_CODE_SESSION_ID). The reason is the launcher's own claim, visible in its transcript."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    if len(argv) != 2 or not argv[0].startswith("local_") or len(argv[1].strip()) < 12 or not sid:
        print("usage: session-launch-check.py --note-reason <local_…> '<worker が何を導出・判断するか (12 字以上)>'"
              " (CLAUDE_CODE_SESSION_ID が要る)", file=sys.stderr)
        return 2
    upsert(sid, argv[0], reason=argv[1].strip())
    print(f"noted: {argv[0]} の理由 = {argv[1].strip()}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "--note-reason":
        sys.exit(note_reason(sys.argv[2:]))
    sys.exit(main())
