#!/usr/bin/env python3
"""first_reply_stamp.py — 最初の返信の自己同定 stamp (I7) を hook で支える共通 logic (Claude / Codex)

規約 = conventions/multi-account-machine-surface.md の I7 (「最初の返信の冒頭 = 自己同定 stamp 1 行」)。
設計と実測 = 同 doc #first-reply-stamp-mechanism。 事後 audit = scripts/check-first-reply-stamp.py。

3 つの段がここを呼ぶ (Claude と Codex で同じ判定を使う):
  session-start … SessionStart で stamp と「最初の text の 1 行目に置け」 を注入 (Claude のみ。
                  Codex では codex/hooks/resume_context.py が同じ役を持つ)
  prompt        … UserPromptSubmit: session の最初の prompt に限り、 完全な stamp を再注入
                  (= 最初の text を書く直前の位置。 SessionStart の注入は他の reminder に埋もれる)
  stop          … Stop: 最初の turn の終わりに、 その turn のどの返信の 1 行目にも stamp が無ければ
                  observe = 記録だけ / block = 1 回だけ差し戻して stamp 1 行を出させる

なぜ 3 段か (2026-09-11 実測、 1 マシン 60 日分の transcript):
  - 規約があっても最初の text の 1 行目に stamp が出たのは 13/31。 主因は
    (a) SessionStart の時点で desktop の account が引けず注入 stamp が不完全
        (→ claude-session-whoami.py --wait で registry の出現を待つ)
    (b) 「数語で状況を」 という harness の促しや「stamp を確認します」 という予告が最初の text になる
  - (a)(b) には、 最初の text の直前に完全な stamp を置く prompt 段が根元に近い。 stop 段は位置を
    直せない (turn の終わりにしか効かない) ので床 (floor) にとどまる。
  - desktop app でも UserPromptSubmit の additionalContext と Stop の decision:block は届く
    (2026-09-11 実測)。 systemMessage は desktop の会話に表示されなかった (同日 owner の目視) ので使わない。

範囲 (どれかに当たれば何もしない):
  - env FIRST_REPLY_STAMP=off (全段)
  - session の cwd が workspace base (= 本 repo の親 dir) の外 (全段)。 盲検 sandbox は base の外に
    作る規約 (cold-eyes-isolation) なので、 注入が汚染源にならない
  - Claude の headless (CLAUDE_CODE_ENTRYPOINT が sdk-*) — prompt / stop 段のみ
  - Codex の sub-agent rollout (session_meta に parent_thread_id) — stop 段のみ
stop 段の mode = env FIRST_REPLY_STAMP_STOP (off | observe | block)、 未設定なら DEFAULT_STOP_MODE。

fail-open: 読めない stdin / transcript / 例外は無出力で exit 0 (session を止めない)。

usage:
  first_reply_stamp.py hook <claude|codex> <session-start|prompt|stop>   # hook から (stdin = event JSON)
  first_reply_stamp.py --selftest
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 2026-09-12 導入時は observe。 観測 (stop-log.jsonl + check-first-reply-stamp.py) で誤発火が
# 無いのを確かめてから block に上げる (= 値を変えて commit。 全マシンに pull で行き渡る)。
DEFAULT_STOP_MODE = "observe"
STOP_MODES = ("off", "observe", "block")

STAMP_MARK = "🖥"
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
WHOAMI = SCRIPT_DIR / "claude-session-whoami.py"
MARKER_MAX_AGE = 30 * 24 * 3600

# 実 user prompt ではない user 行 (slash command の出力・harness の通知・継続 summary)
NON_PROMPT_PREFIXES = (
    "<command-name>", "<local-command", "Caveat:", "This session is being continued",
    "<system-reminder>", "<task-notification", "<cross-session",
)


# ---------- 範囲・設定 ----------

def workspace_base() -> Path:
    value = os.environ.get("FIRST_REPLY_STAMP_BASE")
    return Path(value).resolve() if value else REPO_ROOT.parent


def in_scope(cwd: object) -> bool:
    try:
        here = Path(str(cwd) if cwd else os.getcwd()).resolve()
    except (OSError, ValueError):
        return False
    base = workspace_base()
    return here == base or base in here.parents


def disabled() -> bool:
    return os.environ.get("FIRST_REPLY_STAMP", "").strip().lower() in {"off", "0", "false", "no"}


def stop_mode() -> str:
    value = os.environ.get("FIRST_REPLY_STAMP_STOP", "").strip().lower()
    return value if value in STOP_MODES else DEFAULT_STOP_MODE


def claude_headless() -> bool:
    return os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk-")


# ---------- machine-local state (session ごとの 1 回印 + stop 段の記録) ----------

def state_dir(flavor: str) -> Path:
    value = os.environ.get("FIRST_REPLY_STAMP_STATE_DIR")
    if value:
        return Path(value)
    if flavor == "codex":
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        return home / "state" / "claude-config-first-reply-stamp"
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return home / "state" / "first-reply-stamp"


def _marker(flavor: str, session_id: str, kind: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return state_dir(flavor) / f"{kind}-{digest}"


def is_marked(flavor: str, session_id: str, kind: str) -> bool:
    return _marker(flavor, session_id, kind).exists()


def mark_once(flavor: str, session_id: str, kind: str) -> bool:
    """初回だけ True (O_EXCL で原子的に作る = 並行 hook でも 1 回)。"""
    path = _marker(flavor, session_id, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        return True
    except FileExistsError:
        return False


def prune_markers(flavor: str) -> None:
    now = time.time()
    try:
        for path in state_dir(flavor).iterdir():
            if path.name.startswith(("prompt-", "stop-")) and now - path.stat().st_mtime > MARKER_MAX_AGE:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def stop_log_path(flavor: str) -> Path:
    return state_dir(flavor) / "stop-log.jsonl"


def log_stop(flavor: str, record: dict) -> None:
    path = stop_log_path(flavor)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------- stamp 判定 ----------

def top_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def has_top_stamp(text: str) -> bool:
    return STAMP_MARK in top_line(text)


# ---------- transcript ----------

def _iter_jsonl(path: Path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                yield value


def _claude_user_text(entry: dict) -> str | None:
    """実 user prompt の本文。 tool_result / meta (Stop hook feedback 等) / sidechain は None。"""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    if not text or text.lstrip().startswith(NON_PROMPT_PREFIXES):
        return None
    return text


def claude_first_turn(path: Path) -> tuple[int, list[str]]:
    """(実 prompt 数 〔2 で打ち切り〕, 最初の turn の assistant text 群)。"""
    prompts, texts = 0, []
    for entry in _iter_jsonl(path):
        if entry.get("isSidechain"):
            continue
        if _claude_user_text(entry) is not None:
            prompts += 1
            if prompts >= 2:
                break
            continue
        if prompts == 1 and entry.get("type") == "assistant":
            for block in (entry.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and str(block.get("text", "")).strip():
                    texts.append(block["text"])
    return prompts, texts


def codex_first_turn(path: Path) -> tuple[int, list[str]]:
    """Codex rollout 版。 sub-agent rollout (parent_thread_id あり) は (-1, [])。"""
    prompts, texts = 0, []
    for entry in _iter_jsonl(path):
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        kind = entry.get("type")
        if kind == "session_meta" and payload.get("parent_thread_id"):
            return -1, []
        if kind == "event_msg" and payload.get("type") == "user_message":
            prompts += 1
            if prompts >= 2:
                break
        elif (prompts == 1 and kind == "response_item" and payload.get("type") == "message"
              and payload.get("role") == "assistant"):
            for block in payload.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "output_text" and str(block.get("text", "")).strip():
                    texts.append(block["text"])
    return prompts, texts


def find_codex_rollout(session_id: str) -> Path | None:
    if not SAFE_ID.fullmatch(session_id or ""):
        return None
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    try:
        hits = sorted(root.glob(f"**/rollout-*{session_id}.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return hits[-1] if hits else None


def _transcript(flavor: str, event: dict) -> Path | None:
    value = event.get("transcript_path")
    if isinstance(value, str) and value:
        path = Path(value).expanduser()
        if path.is_file():
            return path
    if flavor == "codex":
        return find_codex_rollout(str(event.get("session_id") or ""))
    return None


def first_turn(flavor: str, path: Path) -> tuple[int, list[str]]:
    return claude_first_turn(path) if flavor == "claude" else codex_first_turn(path)


# ---------- stamp の組み立て ----------

def _host() -> str:
    try:
        return socket.gethostname().split(".")[0] or "unknown-host"
    except OSError:
        return "unknown-host"


def claude_stamp(event: dict, wait: float) -> str:
    session_id = str(event.get("session_id") or "")
    sid8 = session_id[:8] if session_id else "unknown"
    who = os.environ.get("FIRST_REPLY_STAMP_WHO", "")
    if not who:
        try:
            out = subprocess.run(
                [sys.executable, str(WHOAMI), "--who", "--wait", str(wait)],
                capture_output=True, text=True, timeout=wait + 8,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""
        first = out.splitlines()[0] if out else ""
        who = "" if first.startswith(STAMP_MARK) else first  # whoami の失敗行は 🖥 で始まる
    return f"{STAMP_MARK} {_host()} · {who or 'account 未同定'} · session {sid8}"


def codex_stamp(event: dict) -> str:
    try:
        sys.path.insert(0, str(REPO_ROOT / "codex" / "hooks"))
        from session_stamp import build_stamp  # noqa: WPS433 (lazy: Codex 側 module)
        return build_stamp(event)
    except Exception:
        session_id = str(event.get("session_id") or "")
        sid8 = session_id[:8] if SAFE_ID.fullmatch(session_id) else "unknown"
        return (f"{STAMP_MARK} {_host()} · Codex surface unknown · account unknown "
                f"· session {sid8} · model unknown · effort unknown")


def build_stamp(flavor: str, event: dict, wait: float = 1.0) -> str:
    return claude_stamp(event, wait) if flavor == "claude" else codex_stamp(event)


# ---------- 文面 ----------

def _unresolved_note(stamp: str) -> str:
    if "未同定" not in stamp:
        return ""
    return ("account が「未同定」 なら、 最初の text を書く前に "
            "`claude-session-whoami.py --stamp` を実行し、 その出力行を使う。\n")


def session_start_text(stamp: str) -> str:
    return ("<system-reminder>\n"
            "worker 自己同定 stamp (= multi-account-machine-surface.md I7): この session で最初に書く text "
            "(途中経過の 1 行・「数語で状況を」 への返答を含む) の 1 行目に、 次の 1 行をそのまま置く "
            "(以後のターンでは繰り返さない):\n"
            f"{stamp}\n"
            f"{_unresolved_note(stamp)}"
            "</system-reminder>\n")


def prompt_context(flavor: str, stamp: str) -> str:
    if flavor == "codex":
        return ("Identity stamp (first prompt of this session): the first line of the first text "
                "you write in reply — a one-line progress note included — must be exactly this line:\n"
                f"{stamp}\n"
                "Saying that you will print the stamp does not count as printing it.")
    return ("🖥 自己同定 stamp (I7、 この session の最初の prompt): これから書く最初の text — "
            "途中経過の 1 行や状況報告を含む — の 1 行目に、 次の行をそのまま置く:\n"
            f"{stamp}\n"
            "「stamp を確認します」 のような予告は stamp の代わりにならない。\n"
            f"{_unresolved_note(stamp)}").rstrip("\n")


def stop_reason(flavor: str, stamp: str) -> str:
    if flavor == "codex":
        return ("The identity stamp did not lead any reply in this session's first turn. "
                "End with a short message consisting only of this line (do not repeat the body):\n"
                f"{stamp}")
    return ("🖥 自己同定 stamp が、 この session の最初の turn のどの返信の 1 行目にもありません (I7)。 "
            "次の 1 行だけの短い message を出して終わってください (本文の再掲は不要):\n"
            f"{stamp}")


# ---------- 段ごとの判定 ----------

def handle_session_start(flavor: str, event: dict) -> str | None:
    if flavor != "claude" or event.get("hook_event_name") != "SessionStart":
        return None
    if disabled() or not in_scope(event.get("cwd")):
        return None
    return session_start_text(claude_stamp(event, wait=3.0))


def handle_prompt(flavor: str, event: dict) -> str | None:
    if event.get("hook_event_name") != "UserPromptSubmit" or disabled():
        return None
    if flavor == "claude" and claude_headless():
        return None
    if not in_scope(event.get("cwd")):
        return None
    session_id = str(event.get("session_id") or "")
    if not SAFE_ID.fullmatch(session_id) or is_marked(flavor, session_id, "prompt"):
        return None
    path = _transcript(flavor, event)
    if path is not None:
        prompts, _ = first_turn(flavor, path)
        if prompts < 0 or prompts >= 2:  # sub-agent / 最初の turn を過ぎた再開 session
            mark_once(flavor, session_id, "prompt")
            return None
    if not mark_once(flavor, session_id, "prompt"):
        return None
    prune_markers(flavor)
    context = prompt_context(flavor, build_stamp(flavor, event, wait=1.0))
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                              "additionalContext": context}}, ensure_ascii=False)


def handle_stop(flavor: str, event: dict) -> str | None:
    if event.get("stop_hook_active") is True:
        return None
    mode = stop_mode()
    if mode == "off" or disabled():
        return None
    if flavor == "claude" and claude_headless():
        return None
    if not in_scope(event.get("cwd")):
        return None
    session_id = str(event.get("session_id") or "")
    if not SAFE_ID.fullmatch(session_id):
        return None
    # 1 session につき評価は最初の Stop の 1 回だけ (= 以後の turn は transcript を読まない)
    if not mark_once(flavor, session_id, "stop"):
        return None
    path = _transcript(flavor, event)
    if path is not None:
        prompts, texts = first_turn(flavor, path)
    elif flavor == "codex":
        prompts, texts = 1, []  # transcript 不明: 最初の Stop = 最初の turn とみなす
    else:
        return None
    last = event.get("last_assistant_message")
    if isinstance(last, str) and last.strip() and last not in texts:
        texts.append(last)
    if prompts != 1 or any(has_top_stamp(t) for t in texts):
        return None
    log_stop(flavor, {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "flavor": flavor, "session": session_id[:8], "mode": mode,
        "cwd": str(event.get("cwd") or ""), "n_texts": len(texts),
        "first_text_head": top_line(texts[0])[:60] if texts else "",
    })
    if mode != "block":
        return None
    return json.dumps({"decision": "block",
                       "reason": stop_reason(flavor, build_stamp(flavor, event, wait=1.0))},
                      ensure_ascii=False)


HANDLERS = {"session-start": handle_session_start, "prompt": handle_prompt, "stop": handle_stop}


def hook_main(flavor: str, kind: str) -> int:
    if flavor not in {"claude", "codex"} or kind not in HANDLERS:
        return 0
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0
    try:
        out = HANDLERS[kind](flavor, event)
    except Exception:  # fail-open
        return 0
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return 0


# ---------- selftest ----------

def selftest() -> int:
    import tempfile
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + name)
        ok = ok and bool(cond)

    def jl(path: Path, rows: list[dict]) -> Path:
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return path

    def user(text: str, **extra) -> dict:
        return {"type": "user", "message": {"content": text}, **extra}

    def asst(*blocks: dict) -> dict:
        return {"type": "assistant", "message": {"content": list(blocks)}}

    def text(t: str) -> dict:
        return {"type": "text", "text": t}

    tool_use = {"type": "tool_use", "name": "Bash", "input": {"command": "true"}}
    tool_result = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}

    saved = {k: os.environ.get(k) for k in (
        "FIRST_REPLY_STAMP_BASE", "FIRST_REPLY_STAMP_STATE_DIR", "FIRST_REPLY_STAMP_WHO",
        "FIRST_REPLY_STAMP_STOP", "FIRST_REPLY_STAMP", "CLAUDE_CODE_ENTRYPOINT", "CODEX_HOME")}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = root / "base"
        (base / "repo").mkdir(parents=True)
        outside = root / "sandbox"
        outside.mkdir()
        os.environ.update({
            "FIRST_REPLY_STAMP_BASE": str(base),
            "FIRST_REPLY_STAMP_STATE_DIR": str(root / "state"),
            "FIRST_REPLY_STAMP_WHO": "desktop = someone@example.invalid",
            "CODEX_HOME": str(root / "codex-home"),
        })
        for key in ("FIRST_REPLY_STAMP_STOP", "FIRST_REPLY_STAMP", "CLAUDE_CODE_ENTRYPOINT"):
            os.environ.pop(key, None)
        cwd = str(base / "repo")

        check("top-line 判定: 空行の後の 1 行目", has_top_stamp("\n\n🖥 host · x"))
        check("top-line 判定: 2 行目の stamp は数えない", not has_top_stamp("状況報告\n🖥 host"))
        check("範囲: base 配下は内", in_scope(cwd) and in_scope(str(base)))
        check("範囲: sandbox は外", not in_scope(str(outside)))

        # 2026-09-11 の失敗の形: 状況報告が最初の text → tool → 最終 message、 stamp 無し
        miss = jl(root / "miss.jsonl", [
            user("<system-reminder>hook 注入</system-reminder>"),
            user("spec を読んで実行して"),
            asst(text("Status: spec read; now reading…"), tool_use), tool_result,
            user("Stop hook feedback: x", isMeta=True),
            asst(text("結果です")),
        ])
        prompts, texts = claude_first_turn(miss)
        check("claude: harness 行と meta 行は prompt に数えない", prompts == 1 and len(texts) == 2)

        ev = {"hook_event_name": "Stop", "session_id": "s-miss-1", "cwd": cwd,
              "transcript_path": str(miss), "stop_hook_active": False}
        check("stop observe: 無出力", handle_stop("claude", ev) is None)
        log = stop_log_path("claude")
        check("stop observe: 記録が 1 行", log.is_file() and len(log.read_text().splitlines()) == 1)
        check("stop: 同 session の 2 回目は評価しない", handle_stop("claude", ev) is None
              and len(log.read_text().splitlines()) == 1)

        os.environ["FIRST_REPLY_STAMP_STOP"] = "block"
        out = handle_stop("claude", dict(ev, session_id="s-miss-2"))
        payload = json.loads(out) if out else {}
        check("stop block: decision=block + stamp 行", payload.get("decision") == "block"
              and "🖥 " in payload.get("reason", "") and "session s-miss-2" in payload.get("reason", ""))
        check("stop block: stop_hook_active では黙る",
              handle_stop("claude", dict(ev, session_id="s-miss-3", stop_hook_active=True)) is None)
        check("stop block: sandbox cwd では黙る",
              handle_stop("claude", dict(ev, session_id="s-miss-4", cwd=str(outside))) is None)
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "sdk-cli"
        check("stop block: headless では黙る", handle_stop("claude", dict(ev, session_id="s-miss-5")) is None)
        os.environ.pop("CLAUDE_CODE_ENTRYPOINT")

        late = jl(root / "late.jsonl", [
            user("やって"), asst(text("了解、 まず読みます"), tool_use), tool_result,
            asst(text("\n🖥 host · desktop = x · session abc\n\n本文")),
        ])
        check("stop block: 後の text の 1 行目にあれば黙る",
              handle_stop("claude", dict(ev, session_id="s-late", transcript_path=str(late))) is None)
        two = jl(root / "two.jsonl", [user("1 つ目"), asst(text("a")), user("2 つ目"), asst(text("b"))])
        check("stop block: 2 turn 目以降は黙る",
              handle_stop("claude", dict(ev, session_id="s-two", transcript_path=str(two))) is None)
        os.environ.pop("FIRST_REPLY_STAMP_STOP")

        up = {"hook_event_name": "UserPromptSubmit", "session_id": "s-up-1", "cwd": cwd,
              "transcript_path": str(root / "absent.jsonl"), "prompt": "やって"}
        out = handle_prompt("claude", up)
        ctx = (json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else "")
        check("prompt: 最初の prompt で stamp を注入", "🖥 " in ctx and "session s-up-1" in ctx and "途中経過" in ctx)
        check("prompt: 同 session の 2 回目は黙る", handle_prompt("claude", up) is None)
        check("prompt: 再開 session (2 prompt 済) は黙る",
              handle_prompt("claude", dict(up, session_id="s-up-2", transcript_path=str(two))) is None)
        check("prompt: sandbox cwd は黙る", handle_prompt("claude", dict(up, session_id="s-up-3", cwd=str(outside))) is None)
        os.environ["FIRST_REPLY_STAMP"] = "off"
        check("prompt: FIRST_REPLY_STAMP=off で黙る", handle_prompt("claude", dict(up, session_id="s-up-4")) is None)
        os.environ.pop("FIRST_REPLY_STAMP")

        ss = handle_session_start("claude", {"hook_event_name": "SessionStart", "session_id": "abcdef12-z", "cwd": cwd}) or ""
        check("session-start: stamp + 指示 + system-reminder", "🖥 " in ss and "abcdef12" in ss
              and "<system-reminder>" in ss and "未同定" not in ss)
        os.environ["FIRST_REPLY_STAMP_WHO"] = "desktop = account 未同定"
        ss = handle_session_start("claude", {"hook_event_name": "SessionStart", "session_id": "x", "cwd": cwd}) or ""
        check("session-start: 未同定なら whoami を先に打てと添える", "claude-session-whoami.py --stamp" in ss)
        os.environ["FIRST_REPLY_STAMP_WHO"] = "desktop = someone@example.invalid"
        check("session-start: sandbox では黙る",
              handle_session_start("claude", {"hook_event_name": "SessionStart", "cwd": str(outside)}) is None)

        # Codex rollout
        sid = "01aaaaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee"
        day = root / "codex-home" / "sessions" / "2026" / "09" / "12"
        day.mkdir(parents=True)
        rollout = jl(day / f"rollout-2026-09-12T00-00-00-{sid}.jsonl", [
            {"type": "session_meta", "payload": {"id": sid}},
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                  "content": [{"type": "input_text", "text": "# AGENTS.md"}]}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "やって"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                  "content": [{"type": "output_text", "text": "Working on it"}]}},
        ])
        check("codex: rollout を session id で見つける", find_codex_rollout(sid) == rollout)
        prompts, texts = codex_first_turn(rollout)
        check("codex: 注入 user 行は数えず user_message だけ数える", prompts == 1 and texts == ["Working on it"])
        os.environ["FIRST_REPLY_STAMP_STOP"] = "block"
        out = handle_stop("codex", {"hook_event_name": "Stop", "session_id": sid, "cwd": cwd,
                                    "last_assistant_message": "Done."})
        payload = json.loads(out) if out else {}
        check("codex stop block: decision=block + Codex stamp", payload.get("decision") == "block"
              and "Codex" in payload.get("reason", "") and sid[:8] in payload.get("reason", ""))
        sub = jl(root / "sub.jsonl", [{"type": "session_meta", "payload": {"parent_thread_id": "p"}},
                                      {"type": "event_msg", "payload": {"type": "user_message"}}])
        check("codex stop: sub-agent rollout は黙る",
              handle_stop("codex", {"session_id": "s-sub", "cwd": cwd, "transcript_path": str(sub)}) is None)
        check("codex stop: last_assistant_message の stamp で黙る",
              handle_stop("codex", {"session_id": "s-last", "cwd": cwd,
                                    "last_assistant_message": "🖥 host · Codex desktop · x"}) is None)
        os.environ.pop("FIRST_REPLY_STAMP_STOP")
        out = handle_prompt("codex", {"hook_event_name": "UserPromptSubmit", "session_id": "s-cx-up", "cwd": cwd})
        ctx = (json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else "")
        check("codex prompt: 英語の指示 + Codex stamp", "Identity stamp" in ctx and "Codex" in ctx)

    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selftest"]:
        return selftest()
    if len(argv) == 3 and argv[0] == "hook":
        return hook_main(argv[1], argv[2])
    print(__doc__.strip().splitlines()[-2:][0] if __doc__ else "usage: see docstring", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
