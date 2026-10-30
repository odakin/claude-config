#!/usr/bin/env python3
"""owner-window-notice.py — 別の session へ message・掲示板の投稿を送る前に、 宛先が user の直接話している session なら 1 行知らせる (止めない。 PreToolUse hook の engine)

正本 (規律) = conventions/multi-session-coordination.md#owner-driven-window-no-funnel: user が直接話して仕事を進めている
session に、 調整役は依頼書に無い仕事 (別の議題の分析・他の session との調整の役・役の変更) を足さない。
Why (実測): 調整役が user の対話の窓に別の議題の分析と調整の役を掲示板の note で足し、 user の 1 件ずつの往復が待たされた。
止めないのは、 hook には「送る中身が依頼書に無い仕事か、 user の指示の写し・同じ file を書く予定の知らせか」 が分からないから
(どちらも同じ形の message = 止めると正当な知らせまで止まる)。 見分けられるのは宛先が user の対話の窓かどうかだけ。

述語:
  対象の呼び出し: `SendMessage` (to) / `mcp__ccd_session_mgmt__send_message` (session_id) /
    Bash の `board.py note|request|handover` (掲示板の投稿。 request・handover = `--to-session`、 note = `--request` の依頼の担当)。
  宛先の解決 (4 種): `uds:<socket>` = 生きている session の registry (`<config>/sessions/<pid>.json`) の socket /
    `local_…` = registry の hostSessionId、 無ければ desktop の記録の cliSessionId / session id (8 桁以上の 16 進) と名前 =
    lib/session_model.py の resolve (名前は完全一致だけ、 末尾の ` [ref]` は外す) / 掲示板の役割 id (`role-…` など) =
    その役割で最後に claim した session (claim の `--session-name` の先頭 8 桁)。 解けない・曖昧 (2 件以上) = 黙る。
  user の最後の発言: 宛先の会話記録を末尾から読み、 `origin.kind == "human"` の user 行と、 turn の途中に打った発言
    (`attachment.type == "queued_command"` で origin が human) を探す (conventions/hook-authoring.md#transcript-human-vs-peer-message)。
    origin の無い行は数えない (別 session の message・hook の差し戻し・task の通知・圧縮の要約は origin を持たない = 実測)。
    ⚠️ CLI・SDK で起こした session の最初の prompt は origin が human で入る (実測: 掲示板の worker の hand-off 文・盲検の
    起動文) = entrypoint が `claude-desktop` でない session の最初の user 行は数えない。 本文が `<cross-session-message` で
    始まる行も数えない (実測: 古い版は desktop の send_message で届いた message を origin が human で記録した)。
  知らせる条件: 最後の発言が RECENT_S (既定 3 時間) 以内。 同じ (送り手, 宛先) には INTERVAL_S (既定 1 時間) に 1 回。
  外すもの: 宛先 = 送り手自身 / 宛先 = 送り手を起こした session (desktop の記録の spawnedFrom = 結果を上に返す向き) /
    note で送り手がその依頼の担当 (= 報告) / 宛先の会話記録がこの機械に無い。
出力: hookSpecificOutput.additionalContext だけ (permissionDecision を出さない = 止めない・許可の流れを変えない)。
  個人層 (`.claude-personal-layer` の印のある隣の dir、 env CLAUDE_PERSONAL_LAYER) に `owner-window-notice-rule.txt` が
  あれば、 その 1 行目 (個人の規則への pointer) を文の末尾に足す。
故障は黙る (読めない入力・記録・例外 = 何も出さず exit 0)。 subagent の送信は親 session の宛名で出る = 送り手は payload の session_id。

校正 (conventions/hook-authoring.md#command-guard-calibration と同じ考え方、 時刻と会話記録に依る述語なので専用の mode):
  --calibrate [--days N] [--list | --all]
    1. 受け手の側: 全 config dir の会話記録で、 別 session の message (`<cross-session-message`) を受けた時点の
       user の最後の発言の古さを数える (宛先の解決が要らない = uds の宛先も過去の分が数えられる)。
    2. 送り手の側: `mcp__ccd_session_mgmt__send_message` と `board.py note|request|handover` の呼び出しを、 その時刻の
       宛先 (desktop の記録・掲示板の claim) に解いて同じ古さを数える。
    出力 = 古さの分布・知らせが出る回数 (1 時間に 1 回の間引きの後)、 --list = 出る回の 1 件ずつ (時刻・送り手・宛先・本文の頭)、
    --all = 全部の送信を判定 (NOTICE / throttled / report to parent / no recent human) つきで。
env: OWNER_WINDOW_NOTICE_DISABLE=1 / OWNER_WINDOW_RECENT_S / OWNER_WINDOW_INTERVAL_S / OWNER_WINDOW_NOTICE_STATE_DIR (test) /
  AGENT_BOARD_ROOT (`--root`・`--board` の無い投稿の掲示板) / CLAUDE_SESSIONS_DIR・CLAUDE_PROJECTS_DIR・CLAUDE_DESKTOP_SESSIONS_DIR (test)。
self-test: python3 scripts/owner-window-notice.py --selftest
"""
from __future__ import annotations

import fcntl
import glob
import importlib.util as _ilu
import json
import os
import re
import shlex
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
import session_model as sm  # noqa: E402
import desktop_sessions as ds  # noqa: E402

RULE = "claude-config/conventions/multi-session-coordination.md#owner-driven-window-no-funnel"
SEND_TOOLS = {"SendMessage": "to", "mcp__ccd_session_mgmt__send_message": "session_id"}
BOARD_KINDS = {"note", "request", "handover"}
BOARD_BOOL_FLAGS = {"sync", "preview", "json", "launch", "no-launch", "detach", "nested", "worktree", "model-ok", "subagent-ok",
                    "not-blind", "include-closed", "all-boards", "wait"}
RECENT_S = 3 * 3600
INTERVAL_S = 3600
CHUNK = 1 << 20
TS_RE = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"')
REF_SUFFIX = re.compile(r"\s*\[[^\]]+\]\s*$")
TASK_ID = re.compile(r"([0-9a-f]{8})(?![0-9a-z])")
NATIVE_ID = re.compile(r"^[0-9a-f]{8}(?:[0-9a-f-]{0,28})$")
XSESSION = re.compile(r"<cross-session-message\b([^>]*)>")
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


# ---------------------------------------------------------------- transcript reading

def _blocks(e: dict) -> list:
    c = (e.get("message") or {}).get("content")
    return c if isinstance(c, list) else []


def is_prompt_line(e: dict) -> bool:
    """A user line that is a prompt (any origin), not a tool result and not a hook's meta line."""
    if e.get("type") != "user" or e.get("isMeta"):
        return False
    return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in _blocks(e))


def is_human(e: dict) -> bool:
    """A person typed this: a user prompt line with origin.kind == human, or a prompt queued mid-turn by a person.
    A line whose text starts with a peer-message tag is not, whatever its origin (measured: older builds recorded a
    message delivered by the desktop's send_message with a human origin)."""
    a = e.get("attachment")
    if e.get("type") == "attachment" and isinstance(a, dict):
        ok = a.get("type") == "queued_command" and (a.get("origin") or {}).get("kind") == "human"
    elif not is_prompt_line(e):
        return False
    else:
        o = e.get("origin")
        ok = isinstance(o, dict) and o.get("kind") == "human"
    return ok and not prompt_text(e).startswith("<cross-session-message")


def prompt_text(e: dict) -> str:
    a = e.get("attachment")
    if isinstance(a, dict):
        p = a.get("prompt")
    else:
        p = (e.get("message") or {}).get("content")
    if isinstance(p, list):
        p = " ".join(b.get("text", "") for b in p if isinstance(b, dict) and b.get("type") == "text")
    return REMINDER.sub("", str(p or "")).strip()


def iter_lines_reverse(path: str, chunk: int = CHUNK):
    """Lines of a file from the end (bytes, without the newline). A line longer than the chunk is joined first."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        pos, carry = f.tell(), b""
        while pos > 0:
            n = min(chunk, pos)
            pos -= n
            f.seek(pos)
            data = f.read(n) + carry
            lines = data.split(b"\n")
            carry = lines[0]
            for ln in reversed(lines[1:]):
                if ln.strip():
                    yield ln
        if carry.strip():
            yield carry


def _parse_ts(s: str) -> float | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def last_human(path: str, now: float, recent_s: float, before: float | None = None) -> dict | None:
    """The person's latest utterance in a transcript within recent_s before `before` (default now): {"at", "text"}.

    Reads from the end and stops at the first line older than the window. A CLI/SDK session's first prompt carries a
    human origin although a launcher passed it (measured) = it counts only when the session runs in the desktop app.
    None when there is none in the window or the file cannot be read.
    """
    ref = before if before is not None else now
    cutoff = ref - recent_s
    found = None
    try:
        for raw in iter_lines_reverse(path):
            m = TS_RE.search(raw)
            ts = _parse_ts(m.group(1).decode("ascii", "replace")) if m else None
            if found is None:
                if ts is not None and ts > ref:
                    continue
                if ts is not None and ts < cutoff:
                    return None
                if b'"human"' not in raw:
                    continue
                try:
                    e = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(e, dict) and is_human(e):
                    found = {"at": ts if ts is not None else ref, "text": prompt_text(e),
                             "entrypoint": str(e.get("entrypoint") or "")}
                continue
            # A human line was found: is there any earlier prompt? (only matters for a non-desktop session)
            if found["entrypoint"] == "claude-desktop":
                return found
            if b'"user"' not in raw:
                continue
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if isinstance(e, dict) and is_prompt_line(e):
                return found
        if found is not None and found["entrypoint"] == "claude-desktop":
            return found
        return None  # the human line was the session's first prompt in a CLI/SDK session (or nothing was found)
    except OSError:
        return None


# ---------------------------------------------------------------- destinations

def _live() -> list[dict]:
    try:
        return sm.live_sessions()
    except Exception:
        return []


def _row_from_record(rec: dict | None) -> dict | None:
    if not rec or not rec.get("cli_id"):
        return None
    return {"sessionId": rec["cli_id"], "host": rec.get("local_id", ""), "name": rec.get("title", ""), "cwd": ""}


def resolve_target(target: str, live: list[dict] | None = None) -> dict | None:
    """One session for a SendMessage `to` / send_message session_id / board session id; None when unknown or ambiguous."""
    t = REF_SUFFIX.sub("", (target or "").strip())
    if not t or t in {"main", "parent"}:
        return None
    live = _live() if live is None else live
    if t.startswith("uds:"):
        hits = [s for s in live if s.get("address") == t]
    elif t.startswith("local_"):
        hits = [s for s in live if s.get("host") == t]
        if not hits:
            row = _row_from_record(ds.find(t))
            return row
    elif NATIVE_ID.match(t):
        hits = [s for s in live if s["sessionId"].startswith(t)]
        if not hits:
            try:
                hits = sm.resolve(t)
            except Exception:
                hits = []
    else:
        hits = [s for s in live if s.get("name") == t]
    return hits[0] if len(hits) == 1 else None


def transcript_of(row: dict) -> str | None:
    p = row.get("path")
    if p and os.path.isfile(p):
        return p
    try:
        return sm.transcript_path(row["sessionId"], row.get("cwd") or None)
    except Exception:
        return None


# ---------------------------------------------------------------- board posts

def board_args(command: str) -> list[dict]:
    """Each `board.py note|request|handover` invocation in a command: {kind, to_session, request, session, root, board}."""
    if "board.py" not in command:
        return []
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return []
    out = []
    for i, tok in enumerate(toks):
        if not tok.endswith("board.py") or i + 1 >= len(toks) or toks[i + 1] not in BOARD_KINDS:
            continue
        d = {"kind": toks[i + 1], "script": tok}
        j = i + 2
        while j < len(toks) and toks[j] not in {"&&", "||", ";", "|", "&", "(", ")"}:
            k = toks[j]
            if k.startswith("--") and "=" in k:
                key, val = k[2:].split("=", 1)
                d[key.replace("-", "_")] = val
            elif k.startswith("--") and k[2:] not in BOARD_BOOL_FLAGS and j + 1 < len(toks):
                d[k[2:].replace("-", "_")] = toks[j + 1]
                j += 1
            j += 1
        out.append(d)
    return out


def board_root(args: dict) -> str | None:
    """--root > --board > a board's own forwarder (`<board>/scripts/board.py` next to `<board>/board.json`) >
    AGENT_BOARD_ROOT (the forwarder sets it for the engine, so a post without --root is bound to that board)."""
    if args.get("root"):
        return os.path.abspath(os.path.expanduser(args["root"]))
    if args.get("board"):
        try:
            spec = _ilu.spec_from_file_location("board_config", os.path.join(
                os.environ.get("AI_COLLABORATION_DIR") or os.path.join(os.path.dirname(REPO), "ai-collaboration"),
                "board", "board_config.py"))
            bc = _ilu.module_from_spec(spec)
            spec.loader.exec_module(bc)
            return str(bc.find(args["board"]))
        except Exception:
            return None
    script = os.path.abspath(os.path.expanduser(str(args.get("script") or "")))
    if os.path.basename(os.path.dirname(script)) == "scripts":
        cand = os.path.dirname(os.path.dirname(script))
        if os.path.isfile(os.path.join(cand, "board.json")):
            return cand
    env = os.environ.get("AGENT_BOARD_ROOT")
    return os.path.abspath(os.path.expanduser(env)) if env else None


def load_board_events(root: str, needles: tuple[str, ...] = ()) -> list[dict]:
    """Board events (JSON files below <root>/events). With needles, only files containing one of them are parsed."""
    out = []
    for p in glob.glob(os.path.join(root, "events", "**", "*.json"), recursive=True):
        try:
            with open(p, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            continue
        if needles and not any(n in raw for n in needles):
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def role_claimant(role: str, events: list[dict], before: str | None = None) -> str | None:
    """The 8-hex native id of the session that last claimed as `role` (from the claim's session name)."""
    best = None
    for e in events:
        if e.get("kind") != "claim" or (e.get("actor") or {}).get("session_id") != role:
            continue
        at = str(e.get("created_at") or e.get("event_id") or "")
        if before and at > before:
            continue
        m = TASK_ID.match(str((e.get("actor") or {}).get("task") or "").strip())
        if m and (best is None or at > best[0]):
            best = (at, m.group(1))
    return best[1] if best else None


def board_destinations(args: dict, sender_board_session: str, events: list[dict], before: str | None = None) -> list[str]:
    """Session ids (native, role or local) a board post is addressed to; [] when it reports upward or names no one."""
    kind = args.get("kind")
    if kind in {"request", "handover"}:
        return [args["to_session"]] if args.get("to_session") else []
    if kind == "note" and args.get("request"):
        req = next((e for e in events if e.get("kind") == "request" and e.get("event_id") == args["request"]), None)
        if not req:
            return []
        assignee = str((req.get("assignee") or {}).get("session_id") or "")
        if not assignee or assignee == sender_board_session:
            return []  # the assignee's note reports to the requester: not a funnel into a window
        return [assignee]
    return []


def native_of(dest: str, events: list[dict], before: str | None = None) -> str | None:
    if NATIVE_ID.match(dest) or dest.startswith("local_") or dest.startswith("uds:"):
        return dest
    return role_claimant(dest, events, before)


# ---------------------------------------------------------------- state (once per hour per sender/destination)

def state_dir() -> str:
    return os.environ.get("OWNER_WINDOW_NOTICE_STATE_DIR") or os.path.expanduser("~/.claude/state/owner-window-notice")


def claim_slot(sender: str, dest: str, now: float, interval: float) -> bool:
    """True (and record now) when this (sender, destination) had no notice within interval. Never raises."""
    try:
        d = state_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, re.sub(r"[^A-Za-z0-9_.-]", "_", sender or "unknown") + ".json")
        with open(path + ".lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                with open(path, encoding="utf-8") as fh:
                    st = json.load(fh)
                st = st if isinstance(st, dict) else {}
            except (OSError, ValueError):
                st = {}
            last = st.get(dest)
            if isinstance(last, (int, float)) and now - last < interval:
                return False
            st = {k: v for k, v in st.items() if isinstance(v, (int, float)) and now - v < 86400}
            st[dest] = now
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(st, fh)
            os.replace(tmp, path)
        return True
    except Exception:
        return True


# ---------------------------------------------------------------- decision

def personal_rule_line() -> str:
    env = os.environ.get("CLAUDE_PERSONAL_LAYER")
    if env == "none":
        return ""
    try:
        base = os.path.dirname(REPO)
        cands = [env] if env else [os.path.join(base, d) for d in sorted(os.listdir(base))]
        found = [d for d in cands if d and os.path.isfile(os.path.join(d, ".claude-personal-layer"))]
        if len(found) != 1:
            return ""
        with open(os.path.join(found[0], "owner-window-notice-rule.txt"), encoding="utf-8") as fh:
            return fh.readline().strip()
    except Exception:
        return ""


def label_of(row: dict) -> str:
    name = row.get("name") or ""
    sid = (row.get("sessionId") or "")[:8]
    return f"{name} ({sid})" if name else sid


def notice_text(row: dict, human: dict, now: float) -> str:
    mins = max(0, int((now - human["at"]) // 60))
    at = datetime.fromtimestamp(human["at"]).strftime("%H:%M")
    extra = personal_rule_line()
    return (f"🪟 宛先 {label_of(row)} は user が直接話している session (user の最後の発言 = {at}、 {mins} 分前)。"
            " 送る中身がその session の依頼書に無い仕事 (別の議題の分析・他の session との調整の役・役の変更) なら、"
            " 別の子か user と話していない worker に回すか自分でやる (送った後なら、 その仕事を引き取る 1 行を送る)。"
            " user の指示の写し・同じ file を他が書く予定の知らせなど、 その session が今の仕事に要る事実ならそのままでよい"
            f" ({RULE}{'。 ' + extra if extra else ''})。 この宛先への知らせは 1 時間に 1 回。")


def destinations_for(tool: str, tin: dict, sender: str) -> list[str]:
    if tool in SEND_TOOLS:
        t = str(tin.get(SEND_TOOLS[tool]) or "")
        return [t] if t else []
    if tool == "Bash":
        out = []
        for args in board_args(str(tin.get("command") or "")):
            root = board_root(args)
            if not root:
                continue
            needles = tuple(x for x in (args.get("request"), args.get("to_session")) if x)
            events = load_board_events(root, needles + ('"claim"',)) if needles else []
            for dest in board_destinations(args, str(args.get("session") or ""), events):
                n = native_of(dest, events)
                if n:
                    out.append(n)
        return out
    return []


def decide(payload: dict, now: float | None = None) -> str | None:
    if os.environ.get("OWNER_WINDOW_NOTICE_DISABLE") == "1":
        return None
    now = time.time() if now is None else now
    recent = float(os.environ.get("OWNER_WINDOW_RECENT_S") or RECENT_S)
    interval = float(os.environ.get("OWNER_WINDOW_INTERVAL_S") or INTERVAL_S)
    tool = str(payload.get("tool_name") or "")
    tin = payload.get("tool_input") or {}
    sender = str(payload.get("session_id") or "")
    if not isinstance(tin, dict) or not sender:
        return None
    if tool == "Bash" and "board.py" not in str(tin.get("command") or ""):
        return None
    if tool not in SEND_TOOLS and tool != "Bash":
        return None
    dests = destinations_for(tool, tin, sender)
    if not dests:
        return None
    live = _live()
    me = ds.find(sender) or {}
    lines = []
    for d in dests:
        row = resolve_target(d, live)
        if not row or row["sessionId"] == sender:
            continue
        host = row.get("host") or (ds.find(row["sessionId"]) or {}).get("local_id", "")
        if me.get("parent") and host and host == me["parent"]:
            continue  # reporting back to the session that started this one
        path = transcript_of(row)
        if not path:
            continue
        human = last_human(path, now, recent)
        if not human or not claim_slot(sender, row["sessionId"], now, interval):
            continue
        lines.append(notice_text(row, human, now))
    return "\n".join(lines) or None


def hook_main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        msg = decide(payload)
    except Exception:
        return 0
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg}},
                         ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- calibration

def _all_transcripts(days: float) -> list[str]:
    cutoff = time.time() - days * 86400
    out = []
    for root in sm.projects_dirs():
        for p in glob.glob(os.path.join(root, "*", "*.jsonl")):
            try:
                if os.path.getmtime(p) >= cutoff:
                    out.append(p)
            except OSError:
                pass
    return sorted(set(out))


def _records() -> tuple[dict, dict]:
    by_local, by_cli = {}, {}
    for p in glob.glob(os.path.join(ds.root(), "*", "*", "local_*.json")):
        rec = ds._load(p)  # noqa: SLF001 (same package)
        if rec:
            by_local[rec["local_id"]] = rec
            if rec["cli_id"]:
                by_cli[rec["cli_id"]] = rec
    return by_local, by_cli


class _Human:
    """Walks one transcript forward and answers "the latest counted human utterance before t"."""

    def __init__(self, entries: list[dict]):
        self.points = []
        seen_prompt = False
        for e in entries:
            first = is_prompt_line(e) and not seen_prompt
            if is_prompt_line(e):
                seen_prompt = True
            if is_human(e):
                if first and str(e.get("entrypoint") or "") != "claude-desktop":
                    continue
                ts = _parse_ts(str(e.get("timestamp") or ""))
                if ts is not None:
                    self.points.append(ts)
        self.points.sort()

    def before(self, t: float) -> float | None:
        best = None
        for p in self.points:
            if p > t:
                break
            best = p
        return best


def _load(path: str) -> list[dict]:
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
        pass
    return out


def calibrate(days: float, show: bool, recent: float = RECENT_S, interval: float = INTERVAL_S, show_all: bool = False) -> int:
    by_local, by_cli = _records()
    paths = [p for p in _all_transcripts(days) if "/subagents/" not in p]
    sid_of = {os.path.basename(p)[:-6]: p for p in paths}
    humans: dict[str, _Human] = {}
    entries_of: dict[str, list[dict]] = {}

    def human_for(path: str) -> _Human:
        if path not in humans:
            entries_of[path] = entries_of.get(path) or _load(path)
            humans[path] = _Human(entries_of[path])
        return humans[path]

    events_cache: dict[str, list[dict]] = {}
    rows = []  # (t, channel, sender_key, sender_label, dest_sid, dest_label, age_s or None, upward, text)
    for p in paths:
        ents = entries_of.get(p) or _load(p)
        entries_of[p] = ents
        h = human_for(p)
        me = os.path.basename(p)[:-6]
        rec_me = by_cli.get(me) or {}
        seen_bodies: set[tuple[str, str]] = set()
        for e in ents:
            t = _parse_ts(str(e.get("timestamp") or ""))
            if t is None:
                continue
            # 1. receiver side: a peer message landed in this transcript. It arrives as a user line (isMeta when the
            # receiver was idle) or, while the receiver is busy, as a queued_command attachment with origin "peer"
            # (measured); the same message can be written in both forms = deduplicated on (sender, body).
            a = e.get("attachment") if e.get("type") == "attachment" else None
            peer_line = ((e.get("type") == "user" and not any(isinstance(b, dict) and b.get("type") == "tool_result"
                                                               for b in _blocks(e)))
                         or (isinstance(a, dict) and a.get("type") == "queued_command")) and not is_human(e)
            if peer_line:
                txt = prompt_text(e)
                m = XSESSION.search(txt[:3000])
                body_key = (me, txt[m.end():m.end() + 160]) if m else None
                if m and body_key in seen_bodies:
                    m = None
                if m:
                    seen_bodies.add(body_key)
                    attrs = dict(ATTR.findall(m.group(1)))
                    snd = attrs.get("from-session") or attrs.get("from") or ""
                    srec = by_local.get(snd) or {}
                    upward = bool(srec.get("parent")) and srec.get("parent") == rec_me.get("local_id")
                    hb = h.before(t)
                    body = txt[m.end():m.end() + 220].replace("\n", " ").strip()
                    rows.append((t, "message", snd, srec.get("title") or snd[:14], me, rec_me.get("title") or me[:8],
                                 (t - hb) if hb is not None else None, upward, body))
            # 2. sender side: send_message calls and board posts from this transcript
            if e.get("type") != "assistant":
                continue
            for b in _blocks(e):
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                tin = b.get("input") or {}
                dests: list[tuple[str, str]] = []
                if b.get("name") == "mcp__ccd_session_mgmt__send_message":
                    dests = [("send_message", str(tin.get("session_id") or ""))]
                    body = str(tin.get("message") or "")[:220].replace("\n", " ")
                elif b.get("name") == "Bash" and "board.py" in str(tin.get("command") or ""):
                    body = ""
                    for args in board_args(str(tin.get("command") or "")):
                        root = board_root(args)
                        if not root:
                            continue
                        if root not in events_cache:
                            events_cache[root] = load_board_events(root)
                        ev = events_cache[root]
                        iso = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        for d in board_destinations(args, str(args.get("session") or ""), ev, iso):
                            n = native_of(d, ev, iso)
                            if n:
                                dests.append(("board-" + args["kind"], n))
                        body = str(args.get("summary") or "")[:220]
                for channel, d in dests:
                    if d.startswith("local_"):
                        drec = by_local.get(d) or {}
                        dsid = drec.get("cli_id", "")
                    else:
                        dsid = next((s for s in sid_of if s.startswith(d)), "") if NATIVE_ID.match(d) else ""
                        drec = by_cli.get(dsid) or {}
                    dpath = sid_of.get(dsid)
                    if not dsid or not dpath or dsid == me:
                        continue
                    upward = bool(rec_me.get("parent")) and rec_me.get("parent") == drec.get("local_id")
                    hb = human_for(dpath).before(t)
                    rows.append((t, channel, rec_me.get("local_id") or me, rec_me.get("title") or me[:8], dsid,
                                 drec.get("title") or dsid[:8], (t - hb) if hb is not None else None, upward, body))
    rows.sort()
    buckets = {"<10m": 0, "<30m": 0, "<1h": 0, "<3h": 0, "<6h": 0, ">=6h": 0, "no human": 0}
    for r in rows:
        a = r[6]
        k = ("no human" if a is None else "<10m" if a < 600 else "<30m" if a < 1800 else "<1h" if a < 3600
             else "<3h" if a < 10800 else "<6h" if a < 21600 else ">=6h")
        buckets[k] += 1
    last: dict[tuple[str, str], float] = {}
    fired, status = [], {}
    for r in rows:
        if r[6] is None or r[6] > recent:
            status[id(r)] = "no recent human"
            continue
        if r[7]:
            status[id(r)] = "report to parent"
            continue
        key = (r[2], r[4])
        if key in last and r[0] - last[key] < interval:
            status[id(r)] = "throttled"
            continue
        last[key] = r[0]
        fired.append(r)
        status[id(r)] = "NOTICE"
    by_channel: dict[str, int] = {}
    for r in rows:
        by_channel[r[1]] = by_channel.get(r[1], 0) + 1
    upward = sum(1 for r in rows if r[7] and r[6] is not None and r[6] <= recent)
    print(f"transcripts read: {len(paths)} (last {days:g} days, every config dir, subagents excluded)")
    print(f"sends found: {len(rows)} by channel {by_channel}")
    print("age of the destination's last human utterance at send time: " + ", ".join(f"{k} {v}" for k, v in buckets.items()))
    print(f"within {recent / 3600:g} h but reporting back to the sender's parent (not noticed): {upward}")
    print(f"notices (within {recent / 3600:g} h, once per {interval / 60:g} min per sender/destination): {len(fired)}")
    if show_all:
        for r in rows:
            at = datetime.fromtimestamp(r[0]).strftime("%m-%d %H:%M")
            age = "-" if r[6] is None else f"{int(r[6] // 60)} min"
            print(f"- {at} [{r[1]}] {status[id(r)]}: {r[3][:40]} → {r[5][:40]} (human {age}): {r[8][:160]}")
    elif show:
        for r in fired:
            at = datetime.fromtimestamp(r[0]).strftime("%m-%d %H:%M")
            print(f"- {at} [{r[1]}] {r[3][:40]} → {r[5][:40]} (human {int(r[6] // 60)} min before): {r[8][:200]}")
    return 0


# ---------------------------------------------------------------- self-test

def selftest() -> int:
    fails = []

    def check(label: str, ok: bool) -> None:
        print(("ok   " if ok else "FAIL ") + label)
        if not ok:
            fails.append(label)

    tmp = tempfile.mkdtemp(prefix="owner-window-")
    proj = os.path.join(tmp, "projects", "-w")
    sess = os.path.join(tmp, "sessions")
    desk = os.path.join(tmp, "desktop", "acct", "env")
    board = os.path.join(tmp, "board")
    for d in (proj, sess, desk, os.path.join(board, "events", "p", "t")):
        os.makedirs(d, exist_ok=True)
    os.environ.update(CLAUDE_PROJECTS_DIR=os.path.join(tmp, "projects"), CLAUDE_SESSIONS_DIR=sess,
                      CLAUDE_DESKTOP_SESSIONS_DIR=os.path.join(tmp, "desktop"),
                      OWNER_WINDOW_NOTICE_STATE_DIR=os.path.join(tmp, "state"), CLAUDE_PERSONAL_LAYER="none")
    now = time.time()

    def iso(t: float) -> str:
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def write_transcript(sid: str, lines: list[dict]) -> None:
        with open(os.path.join(proj, sid + ".jsonl"), "w", encoding="utf-8") as fh:
            for ln in lines:
                fh.write(json.dumps(ln) + "\n")

    def human(t: float, text: str = "please fix it", ep: str = "claude-desktop") -> dict:
        return {"type": "user", "timestamp": iso(t), "entrypoint": ep, "origin": {"kind": "human"},
                "message": {"role": "user", "content": text}}

    def peer(t: float) -> dict:
        return {"type": "user", "timestamp": iso(t), "entrypoint": "claude-desktop",
                "message": {"role": "user", "content": "<system-reminder>x</system-reminder>\n<cross-session-message from=\"local_x\">hi"}}

    def asst(t: float) -> dict:
        return {"type": "assistant", "timestamp": iso(t), "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}

    W, P, C, S = ("aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002",
                  "cccccccc-0000-4000-8000-000000000003", "dddddddd-0000-4000-8000-000000000004")
    write_transcript(W, [human(now - 7200, "start"), asst(now - 7000), human(now - 1200), asst(now - 600)])  # owner window
    write_transcript(P, [peer(now - 7200), asst(now - 100), peer(now - 50)])                                   # peer-only
    write_transcript(C, [human(now - 1000, "You are the board worker", ep="cli"), asst(now - 900)])            # CLI launch
    write_transcript(S, [asst(now - 10)])                                                                       # the sender
    for i, (sid, name) in enumerate(((W, "reader"), (P, "helper"), (C, "bgworker"), (S, "conductor"))):
        with open(os.path.join(sess, f"{1000 + i}.json"), "w") as fh:
            json.dump({"sessionId": sid, "name": name, "pid": os.getpid(), "hostSessionId": f"local_{sid}",
                       "cwd": "/w", "messagingSocketPath": f"/tmp/x/{1000 + i}.sock"}, fh)
    with open(os.path.join(desk, f"local_{S}.json"), "w") as fh:
        json.dump({"sessionId": f"local_{S}", "cliSessionId": S, "title": "conductor",
                   "spawnedFrom": {"sessionId": f"local_{P}"}}, fh)

    def pay(tool: str, tin: dict, sender: str = S) -> dict:
        return {"tool_name": tool, "tool_input": tin, "session_id": sender}

    lw = os.path.join(proj, W + ".jsonl")
    h = last_human(lw, now, RECENT_S)
    check("last human = the latest origin-human line", bool(h) and abs(h["at"] - (now - 1200)) < 2)
    check("no human within a 10-minute window", last_human(lw, now, 600) is None)
    check("peer messages are not human", last_human(os.path.join(proj, P + ".jsonl"), now, RECENT_S) is None)
    tagged = human(now - 60, "<system-reminder>r</system-reminder>\n<cross-session-message from=\"local_y\">done")
    check("a peer message recorded with a human origin is not human", not is_human(tagged))
    check("a CLI session's first prompt is not human", last_human(os.path.join(proj, C + ".jsonl"), now, RECENT_S) is None)

    msg = decide(pay("SendMessage", {"to": "reader", "message": "x"}), now)
    check("SendMessage by name to the owner window: notice", bool(msg) and "reader" in msg and RULE in msg)
    check("same pair within the hour: quiet", decide(pay("SendMessage", {"to": "reader", "message": "x"}), now + 60) is None)
    check("same pair after the hour: notice again",
          bool(decide(pay("SendMessage", {"to": "uds:/tmp/x/1000.sock", "message": "x"}), now + INTERVAL_S + 5)))
    check("uds address resolves", resolve_target("uds:/tmp/x/1000.sock", sm.live_sessions())["sessionId"] == W)
    check("local_ id resolves", resolve_target(f"local_{W}", sm.live_sessions())["sessionId"] == W)
    check("name with [ref] resolves", resolve_target("reader [3fa9c1]", sm.live_sessions())["sessionId"] == W)
    check("unknown name: None", resolve_target("nobody", sm.live_sessions()) is None)
    check("peer-only destination: quiet", decide(pay("SendMessage", {"to": "helper", "message": "x"}), now) is None)
    check("CLI worker destination: quiet", decide(pay("SendMessage", {"to": "bgworker", "message": "x"}), now) is None)
    check("non-send tool: quiet", decide(pay("Read", {"file_path": "/x"}), now) is None)

    # report back to the parent: the parent is an owner window too, but the sender reports upward
    write_transcript(P, [human(now - 300), asst(now - 100)])
    check("reporting to the sender's parent: quiet",
          decide(pay("mcp__ccd_session_mgmt__send_message", {"session_id": f"local_{P}", "message": "x"}), now) is None)

    # board: request to a live session id, note on a thread whose assignee role was claimed by the owner window
    def ev(name: str, d: dict) -> None:
        with open(os.path.join(board, "events", "p", "t", name + ".json"), "w") as fh:
            json.dump(d, fh)

    ev("r1", {"kind": "request", "event_id": "20260101T000000Z-claude-aaaaaa", "created_at": "2026-01-01T00:00:00Z",
              "actor": {"session_id": S}, "assignee": {"session_id": "role-p-reader"}})
    ev("c1", {"kind": "claim", "event_id": "20260101T000100Z-claude-bbbbbb", "created_at": "2026-01-01T00:01:00Z",
              "request_id": "20260101T000000Z-claude-aaaaaa", "actor": {"session_id": "role-p-reader", "task": "aaaaaaaa (opus)"}})
    os.environ["OWNER_WINDOW_NOTICE_STATE_DIR"] = os.path.join(tmp, "state2")
    cmd = (f"python3 /x/board.py note --root {board} --agent claude --session {S} --request 20260101T000000Z-claude-aaaaaa"
           " --project p --policy ordinary --summary 'another agenda'")
    check("board args parsed", board_args(cmd)[0].get("request") == "20260101T000000Z-claude-aaaaaa")
    check("board note to the window's role: notice", bool(decide(pay("Bash", {"command": cmd}), now)))
    cmd2 = cmd.replace(f"--session {S}", "--session role-p-reader")
    check("note by the assignee (report): quiet", decide(pay("Bash", {"command": cmd2}, sender=W), now) is None)
    cmd3 = f"python3 /x/board.py request --root {board} --agent claude --session {S} --to claude --to-session {W[:8]} --summary s"
    os.environ["OWNER_WINDOW_NOTICE_STATE_DIR"] = os.path.join(tmp, "state3")
    check("board request to a session id: notice", bool(decide(pay("Bash", {"command": cmd3}), now)))
    os.makedirs(os.path.join(board, "scripts"), exist_ok=True)
    open(os.path.join(board, "board.json"), "w").write("{}")
    check("a board's forwarder binds the root", board_root({"script": os.path.join(board, "scripts", "board.py")}) == board)
    check("board inbox: quiet", decide(pay("Bash", {"command": f"python3 /x/board.py inbox --root {board}"}), now) is None)
    check("echo of board.py words: quiet", decide(pay("Bash", {"command": "echo 'board.py note --request x'"}), now) is None)
    os.environ["OWNER_WINDOW_NOTICE_DISABLE"] = "1"
    check("disable env: quiet", decide(pay("SendMessage", {"to": "reader", "message": "x"}), now + 99999) is None)
    os.environ.pop("OWNER_WINDOW_NOTICE_DISABLE")
    print("selftest:", "FAIL " + str(len(fails)) if fails else "PASS")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--calibrate" in argv:
        days = float(argv[argv.index("--days") + 1]) if "--days" in argv else 30.0
        recent = float(os.environ.get("OWNER_WINDOW_RECENT_S") or RECENT_S)
        return calibrate(days, "--list" in argv, recent=recent, show_all="--all" in argv)
    return hook_main()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
