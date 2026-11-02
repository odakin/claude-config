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
                              直し方 (下の見張りを Bash の run_in_background で出して turn を終える → 見張りが出す 1 行どおり:
                              記録が違う = set_session_model / set_session_effort の後にもう一度見張る / 合う = go) を出し、
                              起こした session ごとの台帳 (~/.claude/state/session-launch/<session>.json) に残す。
                              見張りが要る理由 (実測): 起こした側のほかの子が動いていると、 app は子の turn の終わりで起こした側を
                              起こさない (worker が go 待ちで止まった知らせが本人の次の発言まで届かない)。 背景の Bash の終わりは
                              ほかの子が動いていても起こした側の新しい turn を始める (child-wrap-check.py `--wait` と同じ仕組み)。
  (start_session の後と go の SendMessage が通る時) 掲示板の launch 記録が detach を求めるとき (request の --detach) だけ、
                              detach_session を出すよう additionalContext で知らせる。 掲示板の既定は worker を依頼元の子のまま
                              置く (一覧で依頼元の下に並ぶ) ので、 記録に detach が無ければ何も言わない。
  PostToolUse(set_session_model / set_session_effort)  台帳の「頼んだ値」 を起こした側の最新の指定に揃える。 起こした時の記録が
                              頼んだ値と違った worker (= go 待ちで止まる) で、 その見張りが走っていなければ、 見張りの 1 行を出す。
  `--wait-first-turn <local_…> [--model M] [--effort E] [--since <epoch|ISO>] [--max-minutes N]` (見張り = 起こした側が
                              Bash の run_in_background で出す): 子の最初の turn が終わる (子の会話記録に --since 〔既定 = app の
                              記録の作成時刻〕 より後の応答があり = turn が始まり、 registry の status が busy・waiting でない) か、 子が掲示板の依頼を
                              claim する (go を待たずに仕事に入った) まで待ち、 app の記録の model・effort を頼んだ値 (--model /
                              --effort、 無ければ台帳) と比べて次の一手を 1 行で出して終わる: 合う = go を送る / 違う =
                              set_session_* の後にもう一度この見張り (turn が終わっていればすぐ返る) / claim 済み = go は要らない。
                              子の動きの読み方は child-wrap-check.py の locate / scan_child を使う (同じ道具の turn_done_after は
                              app の記録の lastTurnEdgeAt を turn の終わりに数えるが、 作ったばかりの session はその値を最初の prompt
                              より前に持つ = 始まる前に「終わった」 と読む、 実測)。 時間切れ = exit 3、 子が見つからない = exit 2。
  `--hook-stop [--stop-mode off|observe|block]` (Stop の hook 用、 既定 = env SESSION_LAUNCH_STOP か observe): 起こした時の
                              記録が違った worker に、 見張りも go も出さずに turn を終えるとき、 worker ごとに 1 回だけ記録する
                              (observe = <state>/stop-observe.jsonl) か止める (block)。
  PreToolUse(Agent / Task)    BOARD_FIRST の機械の desktop の session で、 掲示板の worker (prompt に role と request id) か
                              Fable の Agent tool の呼び出しを止める (subagent は一覧に出ない)。 `[subagent-ok: 理由]` で通す。
  PreToolUse(SendMessage)     宛先が台帳で未解決の session なら app の記録を読み直す。 合っていれば通し、 違えば止める。
                              本人がその model でよいと言ったなら message に `[model-ok]` を入れれば通る (= 本人が app で
                              model を変えた場合を止め続けない)。
  PreToolUse(set_session_model / set_session_effort)  PREMIUM_GATE の機械で、 Fable (上位 tier) か max への引き上げは、
                              起こした時の理由 (台帳) か本人の直近の名指しが無いと止める。
  `--workflow-gate` (hooks/workflow-launch-check.sh = PreToolUse の全 tool、 PREMIUM_GATE の機械):
    PreToolUse(Workflow)      Fable の session からの Workflow は、 script の agent() が全部 opts に model を書くまで止める
                              (書かない agent は親の model を継ぐ)。 本人の直近の発言が週の切替 (リセット) に触れていれば、
                              script に `[stop-at: <ISO 時刻>]` を求め、 その時刻を session ごとの記録
                              (<state>/<session>.stop-at.json) に残す。
    PreToolUse(ほかの全 tool)   記録した時刻を過ぎたら、 subagent (hook の入力に agent_id) の tool 呼び出しを止め (結果を返す
                              StructuredOutput と SubagentHandback は通す = 止めると手持ちの結果も親に届かない、 実測)、
                              本体には workflow を TaskStop で止めて本人に聞くよう 1 回だけ知らせる。
                              記録は時刻の 6 時間後に消える。 外す = `--clear-stop-at` (CLAUDE_CODE_SESSION_ID の session)。

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
     SESSION_LAUNCH_WAIT (記録を待つ秒、 既定 3) / SESSION_LAUNCH_STOP (`--hook-stop` の mode) /
     SESSION_LAUNCH_PS_FILE (test: 見張りが走っているかを読む ps の出力の代わり) /
     SESSION_LAUNCH_WATCH_GRACE (test: 見張りが、 app の記録にも一覧にも無い子を起動の途中とみなす秒、 既定 90)。
self-test: python3 scripts/session-launch-check.py --selftest
理由を後から残す: python3 scripts/session-launch-check.py --note-reason <local_…> '<理由>'
切替時刻の止めを外す: python3 scripts/session-launch-check.py --clear-stop-at
"""
from __future__ import annotations

import calendar
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
WATCH_FLAG = "--wait-first-turn"
WATCH_MAX_MIN = 30.0     # a worker that stops for `go` ends its first turn within a minute or two (measured)
WATCH_INTERVAL = 10.0
WATCH_GRACE_S = 90.0     # a session just started may be in neither the app records nor the live registry yet
CLAIM_CALL = re.compile(r"board\.py['\"]?\s+claim\b")
STOP_STATES = ("mismatch", "pending")
STOP_RECENT_S = 6 * 3600
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
                f" 「起きた」 と言う前に python3 ~/Claude/claude-config/scripts/session-model.py {local_id} で読む。"
                f" 違っていれば worker は go 待ちで止まる = Bash の run_in_background で `{watch_cmd(local_id, want_m, want_e)}` を出す"
                " (worker の最初の turn の終わりでこの session を起こし、 次の一手を 1 行で出す)。")
    diffs = mismatch(want_m, want_e, rec)
    detach = bool((board_launch_record(ti.get("prompt") or "") or {}).get("detach"))
    upsert(sid, local_id, want_model=want_m, want_effort=want_e, state="mismatch" if diffs else "ok", detach=detach,
           got_model=rec.get("model", ""), got_effort=rec.get("effort", ""), title=ti.get("title") or rec.get("title", ""))
    if not diffs:
        return detach_note(local_id) if detach else ""
    return ("⚠️ session-launch-check: start_session で起こした session は、 app の記録で "
            + " / ".join(diffs) + " で起きた。 start_session は呼び元より高い model と受けない effort を黙って捨てる (実測)。"
            " worker は hand-off 文の model の確かめで最初の turn を止め、 go を待つ。\n"
            f"  直し方: (1) この turn のうちに Bash の run_in_background で `{watch_cmd(local_id, want_m, want_e)}` を出して"
            " turn を終える。 ほかの子が動いていると、 app は子の turn の終わりでこの session を起こさない (実測) = 背景の見張りの"
            " 終わりが起こす。 直すのは worker の最初の turn が終わってから (turn の最中の切り替えは効かなかった例がある)。\n"
            f"  (2) 見張りが終わったら出た 1 行どおり: 記録が違う = {fix_steps(local_id, want_m, want_e, rec)} を出し、 同じ見張りを"
            " もう一度 (turn が終わっていればすぐ返る) / 合う = go を送る / worker が掲示板の依頼を claim 済み = go は要らない。\n"
            f"  記録が合うまで、 この session への SendMessage はこの検査が止める (本人がこの model でよいと言ったなら message に"
            f" {OK_TOKEN})。 本人に「起きた」 と言うのは記録が合ってから。"
            + (" go の後に detach_session (掲示板の request の --detach)。" if detach else "") + f" 規約 = {RULE}")


def fix_steps(local_id: str, want_m: str, want_e: str, rec: dict) -> str:
    """The setter calls that bring the app's record to the asked model and effort ('' when nothing differs)."""
    steps = []
    model_off = bool(want_m) and not model_matches(want_m, rec.get("model", ""))
    if model_off:
        steps.append(f"set_session_model(session_id={local_id}, model={want_m})")
    if want_e and (model_off or want_e != (rec.get("effort") or "").lower()):
        # after a model switch the effort moved to another value (measured), so it is set again even when it matched
        steps.append(f"その後に set_session_effort(session_id={local_id}, effort={want_e})")
    return " と ".join(steps)


def watch_cmd(local_id: str, want_m: str = "", want_e: str = "") -> str:
    """The background watch on a worker's first turn, as the literal command for Bash run_in_background."""
    return (f"python3 ~/Claude/claude-config/scripts/session-launch-check.py {WATCH_FLAG} {local_id}"
            + (f" --model {want_m}" if want_m else "") + (f" --effort {want_e}" if want_e else ""))


def watch_running(local_id: str) -> bool:
    """A `--wait-first-turn` watch on this worker is running on this machine (ps; a test reads SESSION_LAUNCH_PS_FILE)."""
    try:
        f = os.environ.get("SESSION_LAUNCH_PS_FILE")
        if f:
            with open(f, encoding="utf-8") as fh:
                ps = fh.read()
        else:
            import subprocess
            ps = subprocess.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    return any("session-launch-check.py" in ln and WATCH_FLAG in ln and local_id in ln for ln in ps.splitlines())


def detach_note(local_id: str) -> str:
    return (f"[session-launch-check] {local_id} は頼んだ model・effort で動いている。 掲示板の request の指定 (--detach) どおり、 いま"
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
    was = hit.get("state")
    if ti.get("model"):
        hit = upsert(sid, local_id, want_model=ti["model"], state="pending")
    if ti.get("effort"):
        hit = upsert(sid, local_id, want_effort=str(ti["effort"]).lower(), state="pending")
    if was == "ok" or watch_running(local_id) or time.time() - float(hit.get("set_told") or 0) < 120:
        # a worker started as asked is already at work; a running watch reads the new record when it ends; the model
        # and the effort setters come in a row, so the line is said once for the pair
        return ""
    hit = upsert(sid, local_id, set_told=time.time())
    return (f"[session-launch-check] {local_id} は起こした時の記録が頼んだ値と違った = worker は go 待ちで止まる。"
            f" この turn のうちに Bash の run_in_background で `{watch_cmd(local_id, hit.get('want_model', ''), hit.get('want_effort', ''))}`"
            " を出す (worker の最初の turn が終わる = もう終わっていればすぐ、 この session を起こし、 記録を読み直して次の一手を"
            f" 1 行で出す: 合う = go / 違う = 直してもう一度)。 go は見張りの 1 行の後に送る。 規約 = {RULE}")


# ---- the watch on a worker's first turn (`--wait-first-turn`) and the Stop check (`--hook-stop`) ----

def _child_wrap():
    """child-wrap-check.py as a module: its locate / scan_child read the child's movement (one implementation)."""
    import importlib.machinery
    import types
    path = os.path.join(HERE, "child-wrap-check.py")
    mod = types.ModuleType("child_wrap_check")
    mod.__file__ = path
    importlib.machinery.SourceFileLoader("child_wrap_check", path).exec_module(mod)
    return mod


def _transcript_entries(path: str):
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return
    with fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict):
                yield e


def claimed_after(path: str, since: float) -> bool:
    """The worker ran the board's `claim` after `since` = it went to work without waiting for `go`."""
    for e in _transcript_entries(path):
        if e.get("type") != "assistant":
            continue
        ts = parse_when(str(e.get("timestamp") or "")) or 0
        if ts < since:
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash"
                    and CLAIM_CALL.search(str((b.get("input") or {}).get("command") or ""))):
                return True
    return False


def last_reply(path: str, width: int = 200) -> str:
    """The worker's last reply text, on one line (for the launcher to see whether it waits for `go`)."""
    last = ""
    for e in _transcript_entries(path):
        if e.get("type") != "assistant":
            continue
        texts = [b.get("text", "") for b in (e.get("message") or {}).get("content") or []
                 if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()]
        if texts:
            last = " ".join(" ".join(texts).split())
    return last[:width] + ("…" if len(last) > width else "")


def first_turn_ended(cw, c: dict, since: float) -> tuple[bool, str]:
    """The worker's first turn has ended: its transcript has a reply after the launch (the turn started) and the live
    registry does not show it busy or waiting. The app record's lastTurnEdgeAt is not read here: a session just
    created carries an edge later than its creation before its first prompt arrives (measured: the watch read
    'ended' 35 s before the worker's first prompt), which child-wrap-check's turn_done_after would count."""
    if c["status"] == "busy":
        return False, "動いている"
    if c["status"] == "waiting":
        return False, cw.WAITING_TEXT
    ev = cw.scan_child(c.get("path") or "")
    if not any(r and cw._epoch(r) > since for r in ev["replies"]):
        return False, "最初の turn がまだ始まっていない"
    return True, "終わった" if c["status"] != "(not live)" else "終わった (process は無い)"


def wait_first_turn(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="session-launch-check.py " + WATCH_FLAG)
    ap.add_argument("local_id")
    ap.add_argument("--model", default="")
    ap.add_argument("--effort", default="")
    ap.add_argument("--since", default="", help="epoch seconds or ISO time (default: the app record's creation time)")
    ap.add_argument("--max-minutes", type=float, default=WATCH_MAX_MIN)
    ap.add_argument("--interval", type=float, default=WATCH_INTERVAL)
    a = ap.parse_args(argv)
    local = a.local_id
    cw = _child_wrap()
    launcher = os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    hit = next((e for e in load(launcher) if e.get("local_id") == local), {}) if launcher else {}
    want_m = a.model or hit.get("want_model", "")
    want_e = (a.effort or hit.get("want_effort", "")).lower()
    since = None
    if a.since:
        try:
            since = float(a.since)
        except ValueError:
            since = parse_when(a.since)
    if since is None:
        created = cw._raw_record(ds.find(local)).get("createdAt")
        since = created / 1000 - 1 if isinstance(created, (int, float)) else time.time() - 120
    grace = float(os.environ.get("SESSION_LAUNCH_WATCH_GRACE", WATCH_GRACE_S))
    start = time.time()
    deadline = start + a.max_minutes * 60
    claimed, why, c = False, "", None
    while True:
        c = cw.locate(local)
        if not c:
            if time.time() - start >= grace and not ds.find(local):
                break   # nowhere: reported below
            done, why = False, "app の一覧にまだ出ていない"
        elif c.get("path") and claimed_after(c["path"], since):
            claimed = True
            break
        else:
            done, why = first_turn_ended(cw, c, since)
        if done:
            break
        if time.time() > deadline:
            print(f"⌛ session-launch-check: {local} の最初の turn が {a.max_minutes:g} 分たっても終わらない ({why})。"
                  " worker の窓で許可・入力の確認が出ていないかを本人に見てもらうか、 同じ見張りをもう一度"
                  f" Bash の run_in_background で: {watch_cmd(local, want_m, want_e)}")
            return 3
        time.sleep(a.interval)
    rec = ds.find(local)
    if not rec and not c:
        print(f"⚠️ session-launch-check: {local} が app の記録にも生きている session の一覧にも無い = 起きていない。"
              " 本人に一覧を見てもらう (start_session の返りの id を確かめる)。")
        return 2
    rec = rec or {}
    title = rec.get("title") or (c or {}).get("title") or local
    asked = f" (頼んだのは {want_m or '指定なし'} / {want_e or '指定なし'})" if (want_m or want_e) else ""
    head = (f"🚦 session-launch-check: {title} ({local}) — "
            + ("掲示板の依頼を claim した = go を待たずに仕事に入った" if claimed else f"最初の turn が終わった ({why})")
            + f"。 app の記録 = model {rec.get('model') or '?'} / effort {rec.get('effort') or '?'}{asked}")
    lines = [head]
    reply = last_reply((c or {}).get("path") or "")
    if reply:
        lines.append(f"  worker の最後の 1 行: 「{reply}」")
    diffs = mismatch(want_m, want_e, rec) if rec else ["app の記録が読めない"]
    if (c or {}).get("status") == "(not live)" and not claimed:
        lines.append("  (worker の process がこの機械に無い = 窓が閉じられたか archive された。 go が届かなければ本人に一覧で開いてもらう)")
    if claimed:
        if launcher:
            upsert(launcher, local, state="ok", proceeded=True)
        lines.append("  次の一手: go は要らない (提出は掲示板の watch で届く)。"
                     + (f" ただし記録が頼んだ値と違う ({' / '.join(diffs)}) = 本人に 1 行で伝える。" if diffs else "")
                     + (f" 掲示板の request の指定 (--detach) どおり detach_session(session_id={local}) を出す。"
                        if hit.get("detach") and not diffs else ""))
    elif diffs and rec:
        lines.append(f"  次の一手: 記録が違う ({' / '.join(diffs)}) = {fix_steps(local, want_m, want_e, rec)} を出し、"
                     f" 同じ見張りをもう一度 Bash の run_in_background で: {watch_cmd(local, want_m, want_e)}"
                     " (turn が終わっていればすぐ返る)。 go はまだ送らない。")
    elif diffs:
        lines.append(f"  次の一手: app の記録が読めない = python3 ~/Claude/claude-config/scripts/session-model.py {local} で読む。")
    else:
        lines.append(f"  次の一手: 記録が頼んだ値と合う = いま SendMessage(to={local}) で go を送る"
                     " (worker の最後の 1 行が go 待ちでなく問いや報告なら、 go ではなくそれに答える)。")
    print("\n".join(lines))
    return 0


def hook_stop(inp: dict, mode: str) -> str:
    """Stop: a worker whose start record differed (it stops for `go`) and has neither a running watch nor a delivered
    `go` (the ledger is not ok) when the launcher ends its turn. Once per worker and asked values; observe = record."""
    if mode == "off":
        return ""
    sid = inp.get("session_id") or ""
    now = time.time()
    entries = [e for e in load(sid) if e.get("state") in STOP_STATES and str(e.get("local_id", "")).startswith("local_")]
    fresh = []
    for e in entries:
        try:
            age = now - calendar.timegm(time.strptime(str(e.get("updated") or ""), "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            continue
        key = f"{e.get('want_model', '')}|{e.get('want_effort', '')}"
        if age < STOP_RECENT_S and e.get("stop_noted") != key and not watch_running(e["local_id"]):
            fresh.append((e, key))
    if not fresh:
        return ""
    for e, key in fresh:
        upsert(sid, e["local_id"], stop_noted=key)
    if mode == "observe":
        try:
            os.makedirs(state_dir(), exist_ok=True)
            with open(os.path.join(state_dir(), "stop-observe.jsonl"), "a", encoding="utf-8") as fh:
                for e, _ in fresh:
                    fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "launcher": sid,
                                         "worker": e["local_id"], "title": e.get("title", ""), "state": e.get("state"),
                                         "want": [e.get("want_model", ""), e.get("want_effort", "")],
                                         "got": [e.get("got_model", ""), e.get("got_effort", "")]}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return ""
    lines = ["🚦 起こした worker が go 待ちで止まるのに、 見張りも go も出さずに turn を終えようとしている"
             " (ほかの子が動いていると、 worker が止まった知らせではこの session は起こされない):"]
    for e, _ in fresh:
        lines.append(f"- {e.get('title') or e['local_id']} ({e['local_id']}) → Bash の run_in_background で"
                     f" `{watch_cmd(e['local_id'], e.get('want_model', ''), e.get('want_effort', ''))}`")
    lines.append(f"この知らせは worker ごとに 1 回だけ。 規約 = {RULE}")
    return json.dumps({"decision": "block", "reason": "\n".join(lines)}, ensure_ascii=False)


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


# ---- Workflow (hooks/workflow-launch-check.sh = every PreToolUse, `--workflow-gate`): the agents' model, and the stop
# time of a burst that spends the rest of a weekly limit before its reset ----

WORKFLOW_RULE = "claude-config/conventions/multi-session-coordination.md#workflow-agent-model"
AGENT_CALL = re.compile(r"(?<![\w$.])agent\s*\(")
MODEL_OPT = re.compile(r"\bmodel\s*:|[{,]\s*model\s*[,}]")
STOP_AT = re.compile(r"\[stop-at:\s*([^\]]+)\]")
NAMES_RESET = re.compile(r"リセット|\breset\b", re.I)
STOP_AT_GRACE = 6 * 3600         # the state is dropped this long after the stop time
STOP_AT_PASS = ("StructuredOutput", "SubagentHandback")   # a stopped agent still has to hand back its result
# (measured: with only StructuredOutput passed, a stopped plain Agent's SubagentHandback was refused 3 times and the
#  parent got "ended without delivering a report")


def workflow_source(ti: dict, cwd: str) -> str:
    """The script a Workflow call runs: inline `script`, the `scriptPath` file, or a saved workflow by `name`."""
    if isinstance(ti.get("script"), str) and ti["script"].strip():
        return ti["script"]
    paths = []
    if ti.get("scriptPath"):
        p = os.path.expanduser(str(ti["scriptPath"]))
        paths.append(p if os.path.isabs(p) else os.path.join(cwd or ".", p))
    elif ti.get("name"):
        for d in (os.path.join(cwd or ".", ".claude", "workflows"), os.path.expanduser("~/.claude/workflows")):
            paths += [os.path.join(d, str(ti["name"]) + ext) for ext in (".js", ".mjs")]
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            continue
    return ""


def code_mask(src: str) -> str:
    """The script with comments and the text of string literals blanked (newlines kept), so that a parenthesis or the
    word `model:` inside an agent's prompt is not read as code. Template literals keep their `${…}` code."""
    out, n, i = list(src), len(src), 0
    stack: list[list] = []   # ["tpl"] inside a template literal's text, ["expr", depth] inside its ${…}

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if stack and stack[-1][0] == "tpl":
            if c == "\\":
                blank(i, i + 2); i += 2; continue
            if c == "`":
                stack.pop(); i += 1; continue
            if src.startswith("${", i):
                stack.append(["expr", 0]); i += 2; continue
            blank(i, i + 1); i += 1; continue
        if src.startswith("//", i):
            j = src.find("\n", i); j = n if j < 0 else j
            blank(i, j); i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            blank(i, j); i = j; continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] not in (c, "\n"):
                j += 2 if src[j] == "\\" else 1
            blank(i + 1, j); i = j + 1; continue
        if c == "`":
            stack.append(["tpl"])
        elif stack and c == "{":
            stack[-1][1] += 1
        elif stack and c == "}":
            if stack[-1][1] == 0:
                stack.pop()
            else:
                stack[-1][1] -= 1
        i += 1
    return "".join(out)


def agent_calls(src: str) -> list[str]:
    """The argument text of each agent(…) call (strings blanked). Helpers that wrap agent() are read where they call it."""
    m, calls = code_mask(src), []
    for hit in AGENT_CALL.finditer(m):
        depth, j = 0, hit.end() - 1
        while j < len(m):
            if m[j] == "(":
                depth += 1
            elif m[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        calls.append(m[hit.end():j])
    return calls


def parse_when(text: str) -> float | None:
    """Epoch seconds of an ISO-8601 time (`2026-01-02T18:00+09:00`, `…Z`); a time without an offset is local time."""
    from datetime import datetime
    t = text.strip().replace(" ", "T", 1)
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.astimezone()).timestamp()


def _stop_at_path(sid: str) -> str:
    return os.path.join(state_dir(), re.sub(r"[^A-Za-z0-9_.-]", "_", sid or "unknown") + ".stop-at.json")


def load_stop_at(sid: str) -> dict | None:
    try:
        with open(_stop_at_path(sid), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) and isinstance(d.get("stop_at"), (int, float)) else None
    except (OSError, ValueError):
        return None


def save_stop_at(sid: str, d: dict) -> None:
    os.makedirs(state_dir(), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state_dir(), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, _stop_at_path(sid))


def clear_stop_at(sid: str) -> bool:
    try:
        os.remove(_stop_at_path(sid))
        return True
    except OSError:
        return False


def pre_workflow(inp: dict) -> tuple[int, str]:
    """PREMIUM_GATE machines, main thread. (1) A Fable session's Workflow: every agent() names its model (an agent
    without one inherits the session's model; measured: a fan-out of checks a lower tier does ran wholly on the top
    tier). (2) The owner's last prompts name the reset: the script carries `[stop-at: <time>]`, recorded so that
    stop_at_check stops the agents at that time (measured: a burst meant to spend the rest of a weekly limit just
    before its reset kept running past it and spent most of its tokens from the next week's limit)."""
    if not premium_gate_on() or inp.get("agent_id"):
        return 0, ""
    ti = inp.get("tool_input") or {}
    src = workflow_source(ti, inp.get("cwd") or "")
    if not src:
        return 0, ""
    transcript = inp.get("transcript_path") or ""
    msgs = []
    session_model = ((sm.last_model(transcript) if sm is not None and transcript else None) or {}).get("model") or ""
    if tier(session_model) == "fable":
        calls = agent_calls(src)
        missing = sum(1 for a in calls if not MODEL_OPT.search(a))
        if missing:
            msgs.append(f"  - この session は {session_model}。 agent() {len(calls)} 件のうち {missing} 件が model を書いていない ="
                        " 親の model を継いで Fable で動く。 agent ごとに opts の model を書く (読む・照合する・検品する・直す agent は"
                        " claude-opus-5-5 など一段下、 Fable は agent 自身が導出し判断するものだけ)。 1 本の agent は 10 体未満"
                        " (越える形は起動の前に scripts/workflow-estimate.py で見積もって script に書く = #workflow-fan-out)。")
    stop = None
    if any(NAMES_RESET.search(t) for t in owner_prompts(transcript)):
        m = STOP_AT.search(src + " " + str(ti.get("description") or ""))
        stop = parse_when(m.group(1)) if m else None
        if stop is None:
            msgs.append("  - 本人の直近の発言が週の切替 (リセット) に触れている = 切替の前に残りを使い切る workflow なら、 切替時刻で止める。"
                        " script に `// [stop-at: 2026-01-02T18:00+09:00]` の形で切替時刻を書く (時刻は desktop なら get_usage の"
                        " resetsAt、 CLI なら /usage。 使い切りでないなら、 その workflow が終わってよい時刻)。 その時刻を過ぎると、"
                        " この session の agent の tool 呼び出しをこの検査が止める。")
        elif stop <= time.time():
            msgs.append(f"  - [stop-at: {m.group(1).strip()}] はもう過ぎている = 使い切りの時刻は終わった。 起こすなら本人に聞く。")
    if msgs:
        return 2, ("🛑 workflow-launch-check: この Workflow はまだ起こさない。\n" + "\n".join(msgs) + f"\n  規約 = {WORKFLOW_RULE}")
    if stop is not None:
        save_stop_at(inp.get("session_id") or "", {"stop_at": stop, "iso": m.group(1).strip(), "notified": False,
                                                   "set": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return 0, ""


def stop_at_check(inp: dict) -> tuple[int, str]:
    """After a recorded stop time: a subagent's tool call is refused (it returns what it has); the main thread is told
    once to stop the workflows and ask the owner. The record is dropped STOP_AT_GRACE after the stop time."""
    sid = inp.get("session_id") or ""
    st = load_stop_at(sid)
    now = time.time()
    if not st or now < st["stop_at"]:
        return 0, ""
    if now > st["stop_at"] + STOP_AT_GRACE:
        clear_stop_at(sid)
        return 0, ""
    if inp.get("agent_id"):
        if (inp.get("tool_name") or "").startswith(STOP_AT_PASS):
            return 0, ""
        return 2, (f"🛑 workflow-launch-check: 週の切替時刻 {st.get('iso')} を過ぎた。 この workflow は切替の前に残りの枠を使い切るために"
                   " 起こされたので、 ここで止める。 これ以上 tool を呼ばず、 ここまでに分かったことだけを返して終える。")
    if st.get("notified"):
        return 0, ""
    st["notified"] = True
    save_stop_at(sid, st)
    return 0, (f"[workflow-launch-check] 週の切替時刻 {st.get('iso')} を過ぎた。 この session の agent の tool 呼び出しは止めている。"
               " 走っている workflow を TaskStop で止め、 済んだ結果を本人に報告し、 続けるかは本人に聞く (上限が解けた後に自動で届く"
               "「続けて」 は本人の指示ではない)。 止めを外す = python3 ~/Claude/claude-config/scripts/session-launch-check.py"
               f" --clear-stop-at。 規約 = {WORKFLOW_RULE}")


def run_workflow_gate(inp: dict) -> int:
    if inp.get("hook_event_name") != "PreToolUse":
        return 0
    rc, txt = pre_workflow(inp) if inp.get("tool_name") == "Workflow" else stop_at_check(inp)
    if rc == 2:
        sys.stderr.write(txt + "\n")
        return 2
    if txt:
        emit_context("PreToolUse", txt)
    return 0


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


def main(workflow_gate: bool = False) -> int:
    if os.environ.get("SESSION_LAUNCH_CHECK_DISABLE") == "1":
        return 0
    try:
        inp = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    try:
        return run_workflow_gate(inp) if workflow_gate else run(inp)
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
                          SESSION_LAUNCH_WAIT="0", SESSION_LAUNCH_BOARD_FIRST_MARKER=os.path.join(td, "no-marker"),
                          # the machine's own markers must not reach the cases (measured: with the premium-gate
                          # marker on the machine, a pre-start case that expects a pass was blocked)
                          SESSION_LAUNCH_PREMIUM_GATE_MARKER=os.path.join(td, "no-premium-marker"))
        os.environ.pop("SESSION_LAUNCH_BOARD_FIRST", None)
        os.environ.pop("SESSION_LAUNCH_PREMIUM_GATE", None)
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
        app_rec("claude-fable-5-1", "high")
        rc, out, _ = call("PostToolUse", "mcp__ccd_session__start_session", st, started, sid="launcher-2n")
        check("post-start: the record does not ask detach (the board's default) → no detach_session note",
              rc == 0 and "detach_session" not in out)

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

        # ---- the watch on a worker's first turn: a launcher whose other children run is not woken by the worker's
        # stop, so the start and the setters hand it a background watch (measured: the go waited for the owner)
        saved_sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
        psf = os.path.join(td, "ps.txt")
        open(psf, "w").close()
        os.environ["SESSION_LAUNCH_PS_FILE"] = psf
        app_rec("claude-opus-5-5", "xhigh")
        rc, out, _ = call("PostToolUse", "mcp__ccd_session__start_session", st, started, sid="launcher-w")
        check("post-start: capped → the background watch line comes first",
              rc == 0 and f"{WATCH_FLAG} {lid} --model claude-fable-5-1 --effort high" in out and "run_in_background" in out
              and out.index(WATCH_FLAG) < out.index("set_session_model"))
        rc, out, _ = call("PostToolUse", "mcp__ccd_session_mgmt__set_session_model", {"session_id": lid, "model": "claude-fable-5-1"},
                          "ok", sid="launcher-w")
        check("post-set: a worker that waits for go and no watch → the watch line", rc == 0 and WATCH_FLAG in out)
        rc, out, _ = call("PostToolUse", "mcp__ccd_session_mgmt__set_session_effort", {"session_id": lid, "effort": "high"},
                          "ok", sid="launcher-w")
        check("post-set: the effort setter right after the model setter → said once", rc == 0 and out == "")
        upsert("launcher-w", lid, set_told=0)
        with open(psf, "w", encoding="utf-8") as fh:
            fh.write(f"python3 /x/session-launch-check.py {WATCH_FLAG} {lid} --model claude-fable-5-1\n")
        rc, out, _ = call("PostToolUse", "mcp__ccd_session_mgmt__set_session_effort", {"session_id": lid, "effort": "high"},
                          "ok", sid="launcher-w")
        check("post-set: the watch is already running → silent (it reads the new record when it ends)", rc == 0 and out == "")
        open(psf, "w").close()
        app_rec("claude-fable-5-1", "high")
        call("PostToolUse", "mcp__ccd_session__start_session", st, started, sid="launcher-ok")
        rc, out, _ = call("PostToolUse", "mcp__ccd_session_mgmt__set_session_effort", {"session_id": lid, "effort": "high"},
                          "ok", sid="launcher-ok")
        check("post-set: a worker started as asked → silent", rc == 0 and out == "")

        sess, projects = os.path.join(td, "sessions"), os.path.join(td, "projects")
        os.makedirs(sess)
        os.makedirs(os.path.join(projects, "-w"))
        os.environ.update(CLAUDE_SESSIONS_DIR=sess, CLAUDE_PROJECTS_DIR=projects, SESSION_LAUNCH_WATCH_GRACE="0")
        cli = "bbbbbbbb-0000-4000-8000-000000000002"

        def registry(status: str) -> None:
            with open(os.path.join(sess, "1.json"), "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "sessionId": cli, "hostSessionId": lid, "cwd": "/w", "status": status}, fh)

        def transcript(*entries: dict) -> None:
            with open(os.path.join(projects, "-w", cli + ".jsonl"), "w", encoding="utf-8") as fh:
                for e in entries:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")

        said = {"type": "assistant", "timestamp": "2026-01-02T00:00:50.123Z",
                "message": {"content": [{"type": "text", "text": "effort が頼んだ値と違うので止まります。 go を待ちます"}]}}
        turn_end = {"type": "system", "subtype": "stop_hook_summary", "timestamp": "2026-01-02T00:01:00Z"}
        claim = {"type": "assistant", "timestamp": "2026-01-02T00:00:40Z", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": f"python3 /e/board.py claim --root {board} --request {rid}"}}]}}

        def watch(*extra: str, sid: str = "launcher-w", since: str = "2026-01-02T00:00:00Z") -> tuple[int, str]:
            os.environ["CLAUDE_CODE_SESSION_ID"] = sid
            buf = io.StringIO()
            limit = [] if "--max-minutes" in extra else ["--max-minutes", "0.01"]  # a broken case ends, not hangs
            with contextlib.redirect_stdout(buf):
                rc = wait_first_turn([lid, "--since", since, "--interval", "0.01", *limit, *extra])
            return rc, buf.getvalue()

        registry("idle")
        transcript(said, turn_end)
        app_rec("claude-fable-5-1", "high")
        rc, out = watch("--model", "claude-fable-5-1", "--effort", "high")
        check("watch: the first turn ended and the record matches → send go (with the worker's last line)",
              rc == 0 and "go を送る" in out and "go を待ちます" in out)
        app_rec("claude-opus-5-5", "xhigh")
        rc, out = watch("--model", "claude-fable-5-1", "--effort", "high")
        check("watch: the record still differs → the setters, then the same watch again, no go yet",
              rc == 0 and "set_session_model" in out and WATCH_FLAG in out and "go はまだ送らない" in out)
        app_rec("claude-fable-5-1", "high")
        upsert("launcher-w", lid, want_model="claude-fable-5-1", want_effort="high")
        rc, out = watch()
        check("watch: the asked values come from the launcher's ledger when not given", rc == 0 and "go を送る" in out)
        registry("busy")
        transcript(claim)
        rc, out = watch()
        check("watch: the worker claimed (went to work without go) → no go needed, ledger ok, the record's detach asked",
              rc == 0 and "go は要らない" in out and load("launcher-w")[-1]["state"] == "ok" and "detach_session" in out)
        transcript(said)
        rc, out = watch("--max-minutes", "0.0005")
        check("watch: still busy → time-out (exit 3) with the same watch to run again", rc == 3 and WATCH_FLAG in out)
        registry("idle")
        transcript(said, turn_end)
        rc, out = watch("--max-minutes", "0.0005", since="2026-01-02T00:05:00Z")
        check("watch: a turn end before the launch does not count", rc == 3)
        # the measured start: the app record carries a turn edge later than its creation before the first prompt arrives,
        # and the worker has written nothing yet (the watch read 'ended' 35 s before the first prompt)
        with open(os.path.join(app, lid + ".json"), encoding="utf-8") as fh:
            recd = json.load(fh)
        recd.update(createdAt=parse_when("2026-01-02T00:05:00Z") * 1000, lastTurnEdgeAt=parse_when("2026-01-02T00:05:30Z") * 1000)
        with open(os.path.join(app, lid + ".json"), "w", encoding="utf-8") as fh:
            json.dump(recd, fh)
        registry("idle")
        transcript()
        rc, out = watch("--max-minutes", "0.0005", since="")
        check("watch: just created, idle in the live list, edge after creation, nothing written → not ended",
              rc == 3 and "まだ始まっていない" in out)
        os.remove(os.path.join(sess, "1.json"))
        rc, out = watch("--max-minutes", "0.0005", since="")
        check("watch: the same, not in the live list yet → not ended", rc == 3 and "まだ始まっていない" in out)
        os.environ["SESSION_LAUNCH_WATCH_GRACE"] = "60"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = wait_first_turn(["local_eeeeeeee-0000-4000-8000-00000000000e", "--interval", "0.01", "--max-minutes", "0.0005"])
        check("watch: in neither the app records nor the live list, within the grace → keeps waiting",
              rc == 3 and "一覧にまだ出ていない" in buf.getvalue())
        os.environ["SESSION_LAUNCH_WATCH_GRACE"] = "0"
        os.environ["CLAUDE_CODE_SESSION_ID"] = "launcher-w"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = wait_first_turn(["local_ffffffff-0000-4000-8000-00000000000f", "--interval", "0.01", "--max-minutes", "0.001"])
        check("watch: a session that is nowhere → exit 2", rc == 2 and "起きていない" in buf.getvalue())

        # ---- Stop: the launcher ends its turn with neither a watch nor a go for such a worker
        obs = os.path.join(td, "state", "stop-observe.jsonl")
        upsert("launcher-s", lid, state="mismatch", want_model="claude-fable-5-1", want_effort="high", title="worker A")
        check("hook-stop observe: records the worker, says nothing",
              hook_stop({"session_id": "launcher-s"}, "observe") == "" and os.path.exists(obs) and lid in open(obs, encoding="utf-8").read())
        upsert("launcher-s2", lid, state="pending", want_model="claude-opus-5-5", want_effort="max", title="worker B")
        out = hook_stop({"session_id": "launcher-s2"}, "block")
        check("hook-stop block: a decision with the watch line", '"decision": "block"' in out and WATCH_FLAG in out)
        check("hook-stop: the same worker and asked values → once", hook_stop({"session_id": "launcher-s2"}, "block") == "")
        upsert("launcher-s3", lid, state="mismatch", want_model="claude-fable-5-1", want_effort="high")
        with open(psf, "w", encoding="utf-8") as fh:
            fh.write(f"python3 /x/session-launch-check.py {WATCH_FLAG} {lid}\n")
        check("hook-stop: a watch is running → silent", hook_stop({"session_id": "launcher-s3"}, "block") == "")
        open(psf, "w").close()
        upsert("launcher-s4", lid, state="ok", want_model="claude-fable-5-1")
        check("hook-stop: the go went through (ledger ok) → silent / off → silent",
              hook_stop({"session_id": "launcher-s4"}, "block") == "" and hook_stop({"session_id": "launcher-s3"}, "off") == "")
        for k in ("SESSION_LAUNCH_PS_FILE", "CLAUDE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR", "SESSION_LAUNCH_WATCH_GRACE"):
            os.environ.pop(k, None)
        if saved_sid is None:
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        else:
            os.environ["CLAUDE_CODE_SESSION_ID"] = saved_sid

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
        # ---- Workflow: the agents' model in a Fable session, and the stop time of a burst before a reset
        wtr = os.path.join(td, "wf.jsonl")

        def wf_session(model: str, *texts: str) -> None:
            rows = [{"type": "user", "message": {"role": "user", "content": t}} for t in texts]
            rows.append({"type": "assistant", "message": {"role": "assistant", "model": model, "content": []}})
            with open(wtr, "w", encoding="utf-8") as fh:
                fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

        def wf(ti: dict, tool: str = "Workflow", agent_id: str = "", sid: str = "wf-1") -> tuple[int, str, str]:
            inp = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "session_id": sid,
                   "transcript_path": wtr, "cwd": td}
            if agent_id:
                inp["agent_id"] = agent_id
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = run_workflow_gate(inp)
            return rc, out.getvalue(), err.getvalue()

        bare = ("export const meta = {name: 'x', description: 'check (all)'}\n"
                "const r = await parallel(FILES.map(f => () => agent(`Check ${f.name} (see model: notes)`, {label: f.name})))\n"
                "await agent('Summarize: model: none', {schema: S})\n")
        pinned = bare.replace("{label: f.name}", "{label: f.name, model: 'claude-opus-5-5'}").replace(
            "{schema: S}", "{schema: S, model: 'claude-opus-5-5', effort: 'low'}")
        check("agent_calls: two calls, prompt text and its parens blanked",
              len(agent_calls(bare)) == 2 and not any(MODEL_OPT.search(a) for a in agent_calls(bare)))
        check("agent_calls: a helper that wraps agent() is read at its call",
              [bool(MODEL_OPT.search(a)) for a in agent_calls("const ask = (p, o) => agent(p, {...o, model: M})\nask('x')")] == [True])
        wf_session("claude-fable-5-1", "Fable にふさわしい物理の仕事をやろう")
        check("workflow: gate off → a Fable session's bare script passes", wf({"script": bare})[0] == 0)
        os.environ["SESSION_LAUNCH_PREMIUM_GATE"] = "1"
        rc, _, err = wf({"script": bare})
        check("workflow: Fable session, agents without model → blocked (2 of 2)", rc == 2 and "2 件が model" in err)
        check("workflow: every agent names its model → pass", wf({"script": pinned})[0] == 0)
        sp = os.path.join(td, "wf.js")
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(bare)
        check("workflow: a scriptPath is read too", wf({"scriptPath": sp})[0] == 2)
        check("workflow: inside a subagent → not this check", wf({"script": bare}, agent_id="a1")[0] == 0)
        wf_session("claude-opus-5-5", "Fable にふさわしい物理の仕事をやろう")
        check("workflow: an Opus session's bare script → pass", wf({"script": bare})[0] == 0)
        wf_session("claude-opus-5-5", "適当に分業して！あと13分でリセット！！")
        rc, _, err = wf({"script": pinned})
        check("workflow: the owner names the reset, no stop-at → blocked", rc == 2 and "stop-at" in err)
        rc, _, err = wf({"script": "// [stop-at: 2001-01-01T09:00:00Z]\n" + pinned})
        check("workflow: a stop-at already past → blocked", rc == 2 and "過ぎている" in err)
        later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 600))
        rc, _, _ = wf({"script": f"// [stop-at: {later}]\n" + pinned})
        check("workflow: a stop-at ahead → pass and recorded", rc == 0 and abs(load_stop_at("wf-1")["stop_at"] - time.time() - 600) < 5)
        check("stop-at: before the time a subagent's call passes", wf({"command": "ls"}, tool="Bash", agent_id="a1")[0] == 0)
        save_stop_at("wf-1", dict(load_stop_at("wf-1"), stop_at=time.time() - 60))
        rc, _, err = wf({"command": "ls"}, tool="Bash", agent_id="a1")
        check("stop-at: after the time a subagent's call → blocked", rc == 2 and "返して終える" in err)
        check("stop-at: the stopped agent can still hand back its result",
              wf({}, tool="StructuredOutput", agent_id="a1")[0] == 0)
        check("stop-at: ... also a plain Agent's report (SubagentHandback)",
              wf({"message": "x"}, tool="SubagentHandback", agent_id="a1")[0] == 0)
        rc, out, _ = wf({"command": "ls"}, tool="Bash")
        check("stop-at: the main thread is told once to stop the workflows", rc == 0 and "TaskStop" in out)
        check("stop-at: ... and only once", wf({"command": "ls"}, tool="Bash")[1] == "")
        check("stop-at: another session is not touched", wf({"command": "ls"}, tool="Bash", agent_id="a2", sid="wf-2")[0] == 0)
        save_stop_at("wf-1", dict(load_stop_at("wf-1"), stop_at=time.time() - STOP_AT_GRACE - 60))
        rc, _, _ = wf({"command": "ls"}, tool="Bash", agent_id="a1")
        check("stop-at: long after the time the record is dropped", rc == 0 and load_stop_at("wf-1") is None)
        check("parse_when: an offset and a local time", parse_when("2026-10-23T18:00+09:00") == parse_when("2026-10-23T09:00Z")
              and parse_when("2026-10-23 18:00") is not None and parse_when("tomorrow") is None)
        os.environ.pop("SESSION_LAUNCH_PREMIUM_GATE", None)

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
    if len(sys.argv) > 1 and sys.argv[1] == "--clear-stop-at":
        _sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or (sys.argv[2] if len(sys.argv) > 2 else "")
        print("cleared" if _sid and clear_stop_at(_sid) else "no stop time recorded for this session")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == WATCH_FLAG:
        sys.exit(wait_first_turn(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--hook-stop":
        if os.environ.get("SESSION_LAUNCH_CHECK_DISABLE") == "1":
            sys.exit(0)
        _mode = sys.argv[sys.argv.index("--stop-mode") + 1] if "--stop-mode" in sys.argv[:-1] else (
            os.environ.get("SESSION_LAUNCH_STOP") or "observe")
        try:
            _out = hook_stop(json.loads(sys.stdin.read() or "{}"), _mode)
        except Exception:
            _out = ""  # fail-open
        if _out:
            print(_out)
        sys.exit(0)
    sys.exit(main(workflow_gate="--workflow-gate" in sys.argv))
