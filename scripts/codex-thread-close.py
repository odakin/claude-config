#!/usr/bin/env python3
"""codex-thread-close.py — 仕事を終えた Codex のチャット (thread) を、 wrap させてから archive する (指揮役が使う)。 判定 (list / check)・wrap の依頼・wrap の turn の待ち・archive・戻し (unarchive)。 --selftest。

Why: Claude の子 session は、 指揮役が「終えた」 と判定して wrap を頼み、 wrap の記録を確かめてから畳む
(conventions/multi-session-coordination.md#tidy-after-child-turn-ends、 照合 = child-wrap-check.py)。 Codex のチャットには
その道具が無く、 アプリの「最近の項目」 に済んだチャットが積もった (実測: 一覧に残っていたのは盲検の reviewer と試しの thread で、
起こした側はどれも受け取り済みだった)。 この道具は Claude 側の照合と同じ線を Codex の記録で引く。 規則の正本 =
conventions/multi-session-coordination.md#codex-thread-close。

照合 (thread ごと、 どれか 1 つでも当たれば残す = 理由を全部出す):
  - 動き: 最後の turn が進行中 (inProgress)・途中で止まった (interrupted / failed)、 または予約された message が残る
    (<CODEX_HOME>/queue_1.sqlite、 読めなければ「分からない」 として残す)。 書き手の lock (アプリが開いている) だけでは
    動いているとは数えない (アプリは開いた thread の lock を持ち続ける = 実測)。
  - 本人待ち: 最後の turn の最後の発言が問いの欄 (questions) を持つ・問いの形で終わる。 最初の依頼文の後に人の発言が
    ある thread (会話の窓) は、 最後の turn の終わりから GRACE 分 (既定 10、 env CODEX_THREAD_CLOSE_GRACE_MIN) 経つまで
    「本人と話している途中」 として残す (Claude 側の ANSWERED_GRACE_MIN と同じ値と同じ理由)。
  - 掲示板: thread が自分で投稿した・claim した・宛先になった・本文で名指しされた依頼 (全 id か、 機械の中で一意な先頭 8 字)
    のうち、 受け取り (accept) も取り下げ (abandoned) もされていないもの。 thread が claim に使った役 (role id) 宛ての、
    まだ誰も引き受けていない依頼 = 次の依頼 (残す)。 掲示板の root は --board-root か env CODEX_THREAD_CLOSE_BOARD_ROOTS
    (無ければ CHILD_WRAP_BOARD_ROOTS、 os.pathsep 区切り、 glob 可)。 層1 に既定は無い。
  - 作業 dir の種類:
      sealed = 封じた盲検の sandbox (cwd の AGENTS.md の頭が「# Isolated」)。 wrap は頼まない = sandbox の規則が返送の後に
        公開層へ触ることを禁じ、 知見の回収は起こした側の `make-review-sandbox.py collect` と締めの
        `codex-wrap-inventory.py` が持つ (ai-collaboration conventions/cold-eyes-isolation.md#collect-everything-written)。
        代わりに sandbox の台帳が「回収済みで回収の後に変わっていない」 か「閉じた」 ことを求める。
      gone = 作業 dir がもう無い (試しの thread を片づけた後など)。 wrap はできない (turn が走る場所が無い)。 掲示板の
        受け取り済みの依頼に結び付くか、 指揮役が --evidence で完了の根拠を渡すことを求める。
      work = それ以外。 wrap の記録 (wrap skill の型つきの入力か `$wrap` / 「wrap skill」 の依頼文で始まって終わった turn) を
        求め、 その turn の後にこの thread が file を変えた・commit / push した分は wrap されていないと数える。 掲示板の
        受け取り済みの依頼に結び付かない thread (本人が直に開いた窓など) は、 指揮役が --evidence で完了の根拠を渡す
        (題・idle・最後の一言だけでは完了と数えない)。
  - git: この thread が変えた file を含む repo と cwd の repo で、 thread の変えた file が commit されていない・upstream に
    push されていない commit がある。
見ないもの: 本人が別の機械で話している途中か (この機械の記録だけを読む)、 別の機械の Codex の thread。 依頼が受け取られた
  ことと仕事が本当に済んだことの差 (受け取りは依頼元の判断)。

subcommand:
  list [--board-root R]... [--all] [--json]   archive されていない対話の thread (アプリの一覧に出る種類) を 1 行ずつ判定
  check THREAD [--board-root R]... [--evidence TEXT] [--json]   1 つを詳しく
  wrap THREAD [--board-root R]... [--evidence TEXT] [--writer daemon|app]
      照合の残す理由が「wrap の記録が無い」 だけのときに wrap を頼む。 既定 = 共有の Codex daemon で wrap skill を型つきの
      入力で渡す turn を始める (アプリを前に出さない。 アプリがその thread を持っていれば `codex queue` で予約し、 アプリが
      次の turn として走らせる)。 --writer app = 予約してアプリに開かせる。 頼んだ時刻を台帳に書き、 待つ 1 行を出す。
  wait THREAD [--timeout SEC] [--board-root R]...   wrap の依頼の後の turn が終わるまで待ち (daemon が書き手なら手放すまで)、
      照合を出す。 Bash の run_in_background で出す (終わりが指揮役の turn を始める)。
  archive THREAD [--board-root R]... [--evidence TEXT]   照合が通ったときだけ使い捨ての app-server の thread/archive を呼び
      (model は呼ばない)、 状態 DB で archived を確かめ、 台帳に書いて戻す 1 行を出す。 通らなければ理由を出して止める (exit 1)。
      アプリか daemon がその thread を開いている (書き手の lock) ときも止める = 開いている書き手は古い rollout の場所を持った
      ままになる。 実測: archive は状態 DB の印と rollout の archived_sessions/ への移動で、 開いているアプリの「最近の項目」
      には、 アプリが一覧を引き直すまで残る (アプリの一覧は状態 DB から引く。 外の process の archive はアプリに知らせが行かない)。
      残って見える項目を開くと thread/resume が「archived なので先に unarchive」 と断る (中身は壊れない)。
  unarchive THREAD   thread/unarchive (戻す)。 Codex の CLI の `codex unarchive <id>` も同じく戻す。
台帳 = env CODEX_THREAD_CLOSE_LOG か ~/.claude/state/codex-thread-close.jsonl (wrap の依頼・archive・戻しの時刻と根拠)。
状態 DB・queue・lock の配置は Codex の未文書の手元の layout = 読めなければ「分からない」 として残す側に倒す。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
try:
    import codex_threads as ct  # noqa: E402
except Exception:  # pragma: no cover - partial checkout
    ct = None

RULE = "conventions/multi-session-coordination.md#codex-thread-close"
INTERACTIVE = {"vscode", "cli", "appServer"}
DEFAULT_GRACE_MIN = 10.0  # the same owner ruling as child-wrap-check.py DEFAULT_ANSWERED_GRACE_MIN (2026-11-04)
WRAP_TEXT = ("$wrap — wrap skill で仕上げてください (この thread で得た知見・手順・script を上の層の正本へ移し、 正本・参照・SESSION を"
             " 整え、 repo ごとに commit + push して、 移した先を報告)。 依頼元 = 指揮役 (codex-thread-close.py)。")
WRAP_RX = re.compile(r"(?:^|\s)[$/]wrap\b|wrap\s*skill|skill\s*=\s*wrap", re.I)
GIT_WRITE_RX = re.compile(r"\bgit\b[^\n|;&]*\b(?:commit|push|merge|rebase|cherry-pick|reset|revert)\b")
QUESTION_TAIL = re.compile(r"[?？]\s*$|(?:ますか|でしょうか|ませんか|どうしますか|いかがですか|よいですか|いいですか)[。．]?\s*$"
                           r"|(?:ください|下さい|お願いします)[。．]?\s*$")
URL_OR_CODE = re.compile(r"`[^`]*`|https?://\S+|\[[^\]]*\]\([^)]*\)")
SEALED_HEAD = re.compile(r"^#\s*Isolated\b")
CLOSED_BOARD = {"accepted", "abandoned"}


# ---------------------------------------------------------------- small helpers

def now_ts() -> float:
    return float(os.environ.get("CODEX_THREAD_CLOSE_NOW") or time.time())


def iso(ts) -> str:
    if not ts:
        return "?"
    return _dt.datetime.fromtimestamp(float(ts)).astimezone().strftime("%m-%d %H:%M")


def grace_min() -> float:
    try:
        return float(os.environ.get("CODEX_THREAD_CLOSE_GRACE_MIN", DEFAULT_GRACE_MIN))
    except ValueError:
        return DEFAULT_GRACE_MIN


def ledger_path() -> Path:
    return Path(os.environ.get("CODEX_THREAD_CLOSE_LOG") or Path.home() / ".claude/state/codex-thread-close.jsonl")


def ledger_append(rec: dict) -> None:
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"), **rec}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def ledger_records(tid: str) -> list[dict]:
    p = ledger_path()
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("thread") == tid:
                out.append(r)
    return out


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and isinstance(x.get("text"), str))


def is_wrap_input(item: dict) -> bool:
    """A user message that asks for the wrap skill: the typed skill input, or the request text naming it."""
    content = item.get("content")
    if isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "skill" and x.get("name") == "wrap"
                                         for x in content):
        return True
    return bool(WRAP_RX.search(text_of(content)))


def turn_running(turn: dict) -> bool:
    """Whether a turn has not ended. Measured: read through another app-server, a turn still running shows
    status=interrupted with no completedAt (the rollout has no end event yet), and becomes completed with a completedAt
    once it ends. So the end is the completedAt, not the status word."""
    if not turn:
        return False
    return turn.get("status") == "inProgress" or not turn.get("completedAt")


def asks_owner(msg: dict | None) -> str | None:
    """Why the final agent message waits on the owner, or None."""
    if not msg:
        return None
    if msg.get("questions"):
        return "最後の発言が問いの欄 (questions) を持つ"
    text = URL_OR_CODE.sub("", msg.get("text") or "").strip()
    tail = [ln.strip() for ln in text.splitlines() if ln.strip()][-2:]
    for ln in tail:
        if QUESTION_TAIL.search(ln):
            return f"最後の発言が問い・頼みの形で終わる (「{ln[-60:]}」)"
    return None


# ---------------------------------------------------------------- Codex state (read-only)

def state_rows(ids=None, unarchived_interactive=False) -> list[dict] | None:
    if ct is None:
        return None
    got = ct._connect(None)
    if got is None:
        return None
    con, cols = got
    try:
        sel = ", ".join(cols)
        if unarchived_interactive:
            rows = con.execute(f"SELECT {sel} FROM threads WHERE archived = 0 ORDER BY recency_at DESC").fetchall()
            rows = [dict(zip(cols, r)) for r in rows]
            return [r for r in rows if str(r.get("source")) in INTERACTIVE]
        ids = list(ids or [])
        if not ids:
            return []
        rows = con.execute(f"SELECT {sel} FROM threads WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except sqlite3.Error:
        return None
    finally:
        con.close()


def all_ids() -> list[str]:
    if ct is None:
        return []
    got = ct._connect(None)
    if got is None:
        return []
    con, _ = got
    try:
        return [r[0] for r in con.execute("SELECT id FROM threads")]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def queued_count(tid: str) -> int | None:
    if ct is None:
        return None
    db = ct.codex_home() / "queue_1.sqlite"
    if not db.exists():
        return 0
    try:
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)
        try:
            return int(con.execute("SELECT count(*) FROM queued_items WHERE thread_id = ?", (tid,)).fetchone()[0])
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return None


def held_ids() -> set[str] | None:
    return ct.held_lock_ids() if ct is not None else None


def _reader_cls():
    from codex_thread_reader import Reader  # noqa: E402

    class Writer(Reader):
        """thread/archive and thread/unarchive only, on a one-shot app-server (no model turn is started)."""

        def mutate(self, method, params):
            if method not in {"thread/archive", "thread/unarchive"}:
                raise ValueError("only archive / unarchive")
            return self._call(method, params)
    return Reader, Writer


_SHARED_READER = None  # list reads every thread through one app-server


def read_thread(tid: str) -> dict:
    fixture = os.environ.get("CODEX_THREAD_CLOSE_FIXTURE")
    if fixture:
        return json.loads(Path(fixture).read_text(encoding="utf-8"))["threads"][tid]
    if _SHARED_READER is not None:
        return _SHARED_READER.thread(tid)
    Reader, _ = _reader_cls()
    with Reader(timeout=90) as r:
        return r.thread(tid)


# ---------------------------------------------------------------- board

def board_roots(args_roots) -> list[Path]:
    raw = list(args_roots or [])
    if not raw:
        env = os.environ.get("CODEX_THREAD_CLOSE_BOARD_ROOTS") or os.environ.get("CHILD_WRAP_BOARD_ROOTS") or ""
        raw = [x for x in env.split(os.pathsep) if x]
    out = []
    for r in raw:
        for p in sorted(glob.glob(os.path.expanduser(r))) or [os.path.expanduser(r)]:
            if (Path(p) / "events").is_dir():
                out.append(Path(p))
    return out


def board_threads(roots) -> list[dict]:
    """[{root, dir, events}] — each board thread's events in time order."""
    out = []
    for root in roots:
        for d in sorted((root / "events").glob("*/*")):
            if not d.is_dir():
                continue
            evs = []
            for f in sorted(d.glob("*.json")):
                try:
                    evs.append(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
            if evs:
                evs.sort(key=lambda e: (e.get("created_at") or "", e.get("event_id") or ""))
                out.append({"root": root, "dir": d, "events": evs})
    return out


def request_status(evs: list[dict], request_id: str) -> str:
    """The request's state from its events (the same transitions as the board's reducer, without its validation)."""
    st = None
    for e in evs:
        if e.get("request_id") != request_id and e.get("event_id") != request_id:
            continue
        k = e.get("kind")
        if k == "request" and e.get("event_id") == request_id:
            st = "requested"
        elif st in CLOSED_BOARD:
            continue
        elif k == "claim":
            st = "working"
        elif k == "submit":
            st = "submitted"
        elif k == "revise":
            st = "revision"
        elif k == "release":
            st = "requested"
        elif k == "blocker":
            st = "blocked"
        elif k in ("accept", "abandoned"):
            st = "accepted" if k == "accept" else "abandoned"
    return st or "unknown"


def board_links(tid: str, threads: list[dict], unique8: bool) -> dict:
    """Requests this thread posted, claimed, was addressed by or is named in; roles it claimed; requests waiting on them."""
    t8 = tid[:8]
    linked, roles = {}, set()
    for bt in threads:
        for e in bt["events"]:
            a = e.get("actor") or {}
            rid = e.get("request_id") or (e.get("event_id") if e.get("kind") == "request" else None)
            if not rid:
                continue
            how = None
            if a.get("session_id") == tid:
                how = "actor"
            elif a.get("agent") == "codex" and str(a.get("task") or "").startswith(t8) and unique8:
                how = "actor"
                if str(a.get("session_id") or "").startswith("role-"):
                    roles.add(a["session_id"])
            elif ((e.get("target") or {}).get("session_id") == tid) or ((e.get("assignee") or {}).get("session_id") == tid):
                how = "target"
            else:
                body = f"{e.get('summary') or ''}\n{e.get('details') or ''}"
                if tid in body or (unique8 and re.search(rf"(?<![0-9a-f]){t8}(?![0-9a-f])", body)):
                    how = "named"
            if how:
                key = (str(bt["dir"]), rid)
                linked.setdefault(key, {"thread": bt["dir"].name, "project": bt["dir"].parent.name, "request": rid,
                                        "how": set(), "events": bt["events"]})["how"].add(how)
    out = []
    for (_, rid), v in linked.items():
        out.append({"thread": v["thread"], "project": v["project"], "request": rid, "how": sorted(v["how"]),
                    "status": request_status(v["events"], rid)})
    nxt = []
    for bt in threads:
        for e in bt["events"]:
            if e.get("kind") == "request" and (e.get("target") or {}).get("session_id") in roles:
                st = request_status(bt["events"], e["event_id"])
                if st == "requested":
                    nxt.append({"thread": bt["dir"].name, "project": bt["dir"].parent.name, "request": e["event_id"],
                                "role": e["target"]["session_id"]})
    return {"requests": out, "roles": sorted(roles), "next": nxt}


# ---------------------------------------------------------------- work dir / sandbox / git

def dir_kind(cwd: str | None) -> str:
    if not cwd or not Path(cwd).is_dir():
        return "gone"
    agents = Path(cwd) / "AGENTS.md"
    try:
        head = agents.read_text(encoding="utf-8", errors="replace").lstrip().splitlines()[0] if agents.exists() else ""
    except (OSError, IndexError):
        head = ""
    return "sealed" if SEALED_HEAD.match(head) else "work"


_SANDBOX_STATUS: dict[str, list] = {}  # one status run per sandbox root


def sandbox_state(cwd: str) -> dict | None:
    """make-review-sandbox.py status for this sandbox (ai-collaboration, a sibling layer-1 repo); None when unavailable."""
    if os.environ.get("CODEX_THREAD_CLOSE_SANDBOX_FIXTURE"):
        return json.loads(os.environ["CODEX_THREAD_CLOSE_SANDBOX_FIXTURE"]).get(Path(cwd).name)
    tool = Path(os.environ.get("AI_COLLABORATION_DIR") or HERE.parents[1] / "ai-collaboration") / "scripts/make-review-sandbox.py"
    if not tool.exists():
        return None
    p = Path(cwd)
    root = str(p.parent)
    if root not in _SANDBOX_STATUS:
        try:
            proc = subprocess.run([sys.executable, str(tool), "status", "--root", root, "--json"],
                                  capture_output=True, text=True, timeout=180)
            rows = json.loads(proc.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        _SANDBOX_STATUS[root] = rows if isinstance(rows, list) else []
    for r in _SANDBOX_STATUS[root]:
        if r.get("slug") == p.name:
            return r
    return None


def _git(d, *a):
    try:
        p = subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def active_windows(thread: dict) -> list[tuple[float, float]]:
    """(start, end + 60 s) of each turn that has ended — when this thread could have written files."""
    out = []
    for tu in thread.get("turns") or []:
        s, e = tu.get("startedAt"), tu.get("completedAt")
        if s and e:
            out.append((float(s) - 5, float(e) + 60))
    return out


def git_findings(cwd: str | None, changed: list[str], windows=()) -> list[str]:
    """Uncommitted files this thread changed and commits not pushed, in the repos it touched. A file made by a shell
    command is not in the record's file changes (measured), so a dirty path in those repos whose mtime falls inside one of
    the thread's turns also counts (another session writing in the same minutes keeps the thread too = the safe side)."""
    repos: dict[str, list[str]] = {}
    for path in [*(changed or []), *([cwd] if cwd else [])]:
        d = Path(path)
        d = d if d.is_dir() else d.parent
        if not d.is_dir():
            continue
        rc, top = _git(d, "rev-parse", "--show-toplevel")
        if rc == 0 and top:
            repos.setdefault(top, [])
            if path != cwd:
                repos[top].append(path)
    out = []
    for top, paths in sorted(repos.items()):
        if paths:
            rc, dirty = _git(top, "status", "--porcelain", "--", *paths)
            if rc == 0 and dirty:
                out.append(f"{top}: この thread が変えた file に commit されていない変更がある ({len(dirty.splitlines())} 件)")
        if windows:
            rc, dirty = _git(top, "status", "--porcelain", "-uall")
            hits = []
            for line in (dirty.splitlines() if rc == 0 else [])[:2000]:
                rel = line[3:].split(" -> ")[-1].strip('"')
                try:
                    m = (Path(top) / rel).stat().st_mtime
                except OSError:
                    continue
                if any(s <= m <= e for s, e in windows) and str(Path(top) / rel) not in paths:
                    hits.append(rel)
            if hits:
                out.append(f"{top}: この thread の turn の間に変わった、 commit されていない file がある ({len(hits)} 件、 例 {hits[0]})")
        rc, ahead = _git(top, "rev-list", "--count", "@{u}..HEAD")
        if rc == 0 and ahead.isdigit() and int(ahead) > 0:
            out.append(f"{top}: upstream に push されていない commit が {ahead} 件ある")
        elif rc != 0 and _git(top, "remote")[1]:
            out.append(f"{top}: 今の branch に upstream が無い (push 先を確かめられない)")
    return out


# ---------------------------------------------------------------- the judgment

def judge(tid: str, thread: dict, row: dict | None, links: dict, evidence: str | None = None,
          queued: int | None = 0, sandbox: dict | None = None, git: list[str] | None = None) -> dict:
    """Facts and keep-reasons for one thread. closable = no reason; wrap_only = the only reason is the missing wrap."""
    turns = thread.get("turns") or []
    reasons, notes = [], []
    last = turns[-1] if turns else {}
    status = last.get("status")
    if turn_running(last):
        reasons.append("動いている (最後の turn が終わっていない)")
    elif status in ("interrupted", "failed"):
        reasons.append(f"最後の turn が途中で止まった ({status}) = 中身を読んで判断する")
    if queued is None:
        reasons.append("予約された message の有無が読めない (queue の DB)")
    elif queued:
        reasons.append(f"予約された message が {queued} 件ある (次の turn がまだ)")
    agent_msgs = [it for it in last.get("items") or [] if it.get("type") == "agentMessage"]
    why = asks_owner(agent_msgs[-1] if agent_msgs else None)
    if why:
        reasons.append("本人待ち: " + why)
    users = [(n, it) for n, tu in enumerate(turns) for it in tu.get("items") or [] if it.get("type") == "userMessage"]
    conversational = len([u for u in users if not is_wrap_input(u[1])]) > 1
    ended = last.get("completedAt")
    if conversational and ended and (now_ts() - float(ended)) < grace_min() * 60:
        reasons.append(f"本人と話している途中かもしれない (会話の窓で、 最後の turn の終わり {iso(ended)} から {grace_min():g} 分たっていない)")
    # board
    accepted_link = False
    for r in links.get("requests", []):
        if r["status"] in CLOSED_BOARD:
            accepted_link = accepted_link or r["status"] == "accepted"
            continue
        reasons.append(f"掲示板の依頼が開いている: {r['project']}/{r['thread']} ({r['status']}、 結び付き = {'・'.join(r['how'])})")
    for r in links.get("next", []):
        reasons.append(f"次の依頼がある: {r['project']}/{r['thread']} (宛先 {r['role']}、 まだ誰も引き受けていない)")
    # work dir
    cwd = thread.get("cwd") or (row or {}).get("cwd")
    kind = dir_kind(cwd)
    wrap_state = "n/a"
    wrap_missing = False
    if kind == "sealed":
        st = (sandbox or {}).get("state")
        if st == "collected" and not (sandbox or {}).get("changed"):
            notes.append(f"封じた sandbox = wrap は頼まない (回収済み {sandbox.get('collected_at', '?')[:16]}、 回収の後の変化なし)")
        elif st == "closed":
            notes.append("封じた sandbox = wrap は頼まない (台帳で閉じた)")
        elif sandbox is None:
            reasons.append("封じた sandbox の回収の台帳が読めない (make-review-sandbox.py status)")
        else:
            reasons.append(f"封じた sandbox が回収されていない・回収の後に変わった (台帳の状態 = {st}、 変化 {sandbox.get('changed')})")
        if not accepted_link and not evidence:
            notes.append("掲示板の受け取り済みの依頼に結び付かない (sandbox の回収を完了の根拠にする)")
    elif kind == "gone":
        notes.append(f"作業 dir が無い ({cwd}) = wrap はできない")
        if not accepted_link and not evidence:
            reasons.append("完了の根拠が機械に見えない (作業 dir が無く、 掲示板の受け取り済みの依頼にも結び付かない) = 指揮役が --evidence で渡す")
    else:
        wrap_turn = None
        for n, tu in enumerate(turns):
            if any(it.get("type") == "userMessage" and is_wrap_input(it) for it in tu.get("items") or []):
                wrap_turn = n
        if wrap_turn is None:
            wrap_state, wrap_missing = "missing", True
            reasons.append("wrap の記録が無い (wrap skill を頼んで終わった turn が無い)")
        elif turns[wrap_turn].get("status") != "completed" or turn_running(turns[wrap_turn]):
            wrap_state, wrap_missing = "unfinished", True
            reasons.append(f"wrap の turn が終わっていない ({turns[wrap_turn].get('status')})")
        else:
            later = [it for tu in turns[wrap_turn + 1:] for it in tu.get("items") or []
                     if it.get("type") == "fileChange" or (it.get("type") == "commandExecution"
                                                            and GIT_WRITE_RX.search(it.get("command") or ""))]
            if later:
                wrap_state, wrap_missing = "stale", True
                reasons.append(f"wrap の後にこの thread が file を変えた・commit した ({len(later)} 件) = その分は wrap されていない")
            else:
                wrap_state = f"turn {wrap_turn + 1}"
        if not accepted_link and not evidence:
            reasons.append("完了の根拠が機械に見えない (掲示板の受け取り済みの依頼に結び付かない) = 指揮役が最後の報告を読み、 --evidence で渡す")
    for g in git or []:
        reasons.append("git: " + g)
    others = [r for r in reasons if not r.startswith(("wrap の記録が無い", "wrap の turn が終わっていない", "wrap の後に"))]
    return {"thread": tid, "title": (row or {}).get("name") or thread.get("name") or (row or {}).get("title") or "",
            "cwd": cwd, "kind": kind, "turns": len(turns), "last_status": status, "last_end": ended,
            "wrap": wrap_state, "board": links.get("requests", []), "next": links.get("next", []),
            "evidence": evidence, "reasons": reasons, "notes": notes,
            "closable": not reasons, "wrap_only": wrap_missing and not others}


def changed_paths(thread: dict) -> list[str]:
    out = []
    for tu in thread.get("turns") or []:
        for it in tu.get("items") or []:
            if it.get("type") != "fileChange":
                continue
            ch = it.get("changes")
            if isinstance(ch, str):
                out += re.findall(r"'path': '([^']+)'", ch)
            elif isinstance(ch, list):
                out += [c.get("path") for c in ch if isinstance(c, dict) and c.get("path")]
    return sorted(set(out))


def evaluate(tid: str, roots, evidence=None, row=None, threads_cache=None, ids_cache=None) -> dict:
    thread = read_thread(tid)
    if row is None:
        rows = state_rows([tid]) or []
        row = rows[0] if rows else None
    threads = threads_cache if threads_cache is not None else board_threads(roots)
    ids = ids_cache if ids_cache is not None else all_ids()
    unique8 = sum(1 for i in ids if i.startswith(tid[:8])) == 1 if ids else False
    links = board_links(tid, threads, unique8)
    cwd = thread.get("cwd") or (row or {}).get("cwd")
    kind = dir_kind(cwd)
    sandbox = sandbox_state(cwd) if kind == "sealed" else None
    git = git_findings(cwd, changed_paths(thread), active_windows(thread)) if kind == "work" else []
    ev = evidence or next((r.get("evidence") for r in reversed(ledger_records(tid)) if r.get("evidence")), None)
    res = judge(tid, thread, row, links, ev, queued_count(tid), sandbox, git)
    held = held_ids()
    res["held"] = None if held is None else tid in held
    res["archived"] = bool((row or {}).get("archived"))
    if not roots:
        res["notes"].append("掲示板の root が渡されていない = 掲示板の照合をしていない (--board-root)")
    return res


def render(res: dict, verbose=True) -> str:
    if res.get("archived"):
        mark = "📦 archive 済み"
    elif res["closable"]:
        mark = "✅ 畳める"
    elif res["wrap_only"]:
        mark = "🧹 wrap を頼む番"
    else:
        mark = "⏸ 残す"
    head = f"{mark} {res['thread'][:8]} 「{res['title'][:50]}」 [{res['kind']}] turn {res['turns']} 最後 {res['last_status']} {iso(res['last_end'])}"
    if res.get("held"):
        head += " (アプリか daemon が開いている)"
    lines = [head]
    if verbose or not res["closable"]:
        lines += ["   - " + r for r in res["reasons"]]
    if verbose:
        lines += ["   · " + n for n in res["notes"]]
        for b in res["board"]:
            lines.append(f"   · 掲示板 {b['project']}/{b['thread']} = {b['status']} ({'・'.join(b['how'])})")
        if res.get("evidence"):
            lines.append(f"   · 指揮役の根拠: {res['evidence'][:200]}")
    if res["wrap_only"]:
        lines.append(f"   → 次の一手 = python3 {__file__} wrap {res['thread']}" + (" --evidence '…'" if res.get("evidence") else ""))
    elif res["closable"] and not res.get("archived") and res.get("held"):
        lines.append("   → アプリか daemon が開いている = 外から archive しない (手放してから archive、 またはアプリの中で)")
    elif res["closable"] and not res.get("archived"):
        lines.append(f"   → 次の一手 = python3 {__file__} archive {res['thread']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- actions

def _launch_module():
    spec = importlib.util.spec_from_file_location("codex_app_launch", HERE / "codex-app-launch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wrap_skill_path(cwd: str) -> str | None:
    Reader, _ = _reader_cls()
    try:
        with Reader(timeout=60) as r:
            got = r.call("skills/list", {"cwds": [cwd]})
    except Exception:
        return None
    for entry in (got or {}).get("data", []):
        for s in entry.get("skills", []):
            if s.get("name") == "wrap" and s.get("enabled", True) and s.get("path"):
                return s["path"]
    return None


def send_wrap(tid: str, cwd: str, writer: str) -> tuple[bool, str]:
    m = _launch_module()
    cli = m.codex_cli()
    if writer == "app":
        if not cli:
            return False, "Codex の CLI が見つからない"
        ok, out = m.queue_message(cli, tid, WRAP_TEXT)
        if ok:
            m.open_in_app(m.reveal_url(tid))
        return ok, "予約してアプリに開かせた" if ok else out
    sock = m.daemon_socket(start=True)
    if not sock:
        return False, "共有の Codex daemon に繋がらない (--writer app で予約する)"
    skill = wrap_skill_path(cwd)
    w = m.WS(sock)
    try:
        w.call("initialize", {"clientInfo": m.CLIENT})
        w.send({"method": "initialized"})
        try:
            w.call("thread/resume", {"threadId": tid})
        except RuntimeError as e:
            if "active writer" in str(e) and cli:
                ok, out = m.queue_message(cli, tid, WRAP_TEXT)
                return ok, ("アプリが開いている = 予約した (アプリが次の turn として走らせる)" if ok else out)
            return False, f"daemon で開けない ({e})"
        inp = [{"type": "text", "text": WRAP_TEXT}]
        if skill:
            inp.append({"type": "skill", "name": "wrap", "path": skill})
        w.call("turn/start", {"threadId": tid, "input": inp})
    finally:
        w.close()
    return True, "daemon で wrap の turn を始めた" + ("" if skill else " (wrap skill の path が引けず、 依頼文だけ)")


def cmd_wrap(a) -> int:
    tid = resolve(a.thread)
    res = evaluate(tid, board_roots(a.board_root), a.evidence)
    if not res["wrap_only"]:
        print(render(res))
        print("⛔ wrap を頼むのは残す理由が「wrap の記録が無い」 だけのとき = 頼まない", file=sys.stderr)
        return 1
    ok, msg = send_wrap(tid, res["cwd"], a.writer)
    if not ok:
        print(f"⛔ wrap を頼めない: {msg}", file=sys.stderr)
        return 2
    ledger_append({"event": "wrap_asked", "thread": tid, "title": res["title"], "writer": a.writer, "how": msg,
                   "evidence": a.evidence, "asked_ts": now_ts()})
    print(f"→ {tid[:8]} に wrap を頼んだ ({msg})")
    print(f"→ 同じ turn に Bash の run_in_background で: python3 {__file__} wait {tid}"
          + "".join(f" --board-root '{r}'" for r in (a.board_root or [])))
    return 0


def cmd_wait(a) -> int:
    tid = resolve(a.thread)
    asked = [r for r in ledger_records(tid) if r.get("event") == "wrap_asked"]
    since = float(asked[-1]["asked_ts"]) - 5 if asked else now_ts() - 5
    deadline = time.time() + a.timeout
    seen_turn = False
    while time.time() < deadline:
        th = read_thread(tid)
        turns = th.get("turns") or []
        newer = [t for t in turns if (t.get("startedAt") or 0) >= since]
        if newer:
            seen_turn = True
            if not turn_running(newer[-1]) and not queued_count(tid):
                break
        time.sleep(a.interval)
    else:
        print(f"⏳ {a.timeout} 秒待ったが wrap の turn が{'終わらない' if seen_turn else '始まらない'} = 残す (アプリで開いて確かめる)")
        return 3
    # the daemon keeps an idle thread for 40-60 s after the turn; archive after it lets go
    for _ in range(12):
        held = held_ids()
        if not held or tid not in held:
            break
        time.sleep(10)
    res = evaluate(tid, board_roots(a.board_root))
    print(render(res))
    return 0 if res["closable"] else 1


def resolve(token: str) -> str:
    tid = ct.resolve(token) if ct is not None else None
    if not tid:
        sys.exit(f"⛔ thread が一意に決まらない: {token}")
    return tid


def cmd_archive(a) -> int:
    tid = resolve(a.thread)
    res = evaluate(tid, board_roots(a.board_root), a.evidence)
    if res.get("archived"):
        print(f"📦 {tid[:8]} は archive 済み")
        return 0
    if not res["closable"]:
        print(render(res))
        print("⛔ 残す理由がある = archive しない", file=sys.stderr)
        return 1
    if res.get("held") is not False:
        print(render(res))
        print("⛔ アプリか daemon がこの thread を開いている (書き手の lock が握られている、 または lock が読めない) = 外から archive"
              " しない: 開いている書き手は古い rollout の場所を持ったままになる。 アプリが手放してから打ち直すか、 アプリの中で"
              " archive する (Codex のチャットの set_thread_archived / 一覧の右クリック)", file=sys.stderr)
        return 1
    _, Writer = _reader_cls()
    with Writer(timeout=60) as w:
        w.mutate("thread/archive", {"threadId": tid})
    row = (state_rows([tid]) or [{}])[0]
    if not row.get("archived"):
        print(f"⛔ thread/archive は返ったが状態 DB で archived になっていない ({tid})", file=sys.stderr)
        return 2
    ledger_append({"event": "archived", "thread": tid, "title": res["title"], "kind": res["kind"], "cwd": res["cwd"],
                   "notes": res["notes"], "board": [f"{b['project']}/{b['thread']}={b['status']}" for b in res["board"]],
                   "evidence": res.get("evidence"), "held": res.get("held")})
    print(f"📦 {tid[:8]} 「{res['title'][:50]}」 を archive した。 戻す = python3 {__file__} unarchive {tid}")
    return 0


def cmd_unarchive(a) -> int:
    tid = resolve(a.thread)
    _, Writer = _reader_cls()
    with Writer(timeout=60) as w:
        w.mutate("thread/unarchive", {"threadId": tid})
    row = (state_rows([tid]) or [{}])[0]
    ok = row and not row.get("archived")
    if ok:
        ledger_append({"event": "unarchived", "thread": tid})
    print(("↩︎ 戻した: " if ok else "⛔ 戻らない: ") + tid)
    return 0 if ok else 2


def cmd_check(a) -> int:
    tid = resolve(a.thread)
    res = evaluate(tid, board_roots(a.board_root), a.evidence)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str) if a.json else render(res))
    return 0 if res["closable"] else 1


def cmd_list(a) -> int:
    rows = state_rows(unarchived_interactive=True)
    if rows is None:
        print("⛔ Codex の状態 DB が読めない", file=sys.stderr)
        return 2
    global _SHARED_READER
    roots = board_roots(a.board_root)
    threads, ids = board_threads(roots), all_ids()
    out = []
    Reader, _ = _reader_cls()
    with Reader(timeout=90) as reader:
        _SHARED_READER = reader
        try:
            for row in rows:
                try:
                    res = evaluate(row["id"], roots, row=row, threads_cache=threads, ids_cache=ids)
                except Exception as e:  # one unreadable thread does not hide the others
                    res = {"thread": row["id"], "title": row.get("name") or row.get("title") or "", "error": str(e)}
                out.append(res)
        finally:
            _SHARED_READER = None
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return 0
    for res in out:
        if "error" in res:
            print(f"❓ {res['thread'][:8]} 「{res['title'][:50]}」 読めない: {res['error']}")
        else:
            print(render(res, verbose=a.all))
    if not roots:
        print("· 掲示板の root が渡されていない = 掲示板の照合をしていない (--board-root)")
    return 0


# ---------------------------------------------------------------- selftest

def _selftest() -> int:
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("OK: " if cond else "FAIL: ") + name)
        ok = ok and bool(cond)

    T = "01a10000-0000-7000-8000-000000000001"  # synthetic
    os.environ["CODEX_THREAD_CLOSE_NOW"] = "1794300000"
    tmp = Path(tempfile.mkdtemp())
    sealed = tmp / "sb"
    sealed.mkdir()
    (sealed / "AGENTS.md").write_text("# Isolated review sandbox\n\nrules\n")
    work = tmp / "w"
    work.mkdir()

    def turn(user, agent, status="completed", end=1794200000, extra=()):
        items = [{"type": "userMessage", "content": user if isinstance(user, list) else [{"type": "text", "text": user}]}]
        items += list(extra)
        items.append({"type": "agentMessage", "text": agent, "questions": None})
        return {"status": status, "startedAt": end - 60, "completedAt": end if status != "inProgress" else None, "items": items}

    def th(cwd, *turns):
        return {"id": T, "cwd": str(cwd), "turns": list(turns)}

    done = {"requests": [{"project": "p", "thread": "t", "request": "r", "how": ["named"], "status": "accepted"}], "next": []}
    collected = {"state": "collected", "changed": 0, "collected_at": "2026-01-01T00:00"}
    r = judge(T, th(sealed, turn("Read REVIEW-SPEC.md", "Completed REVIEW-RESULTS.md and HANDOFF.md.")), None, done,
              sandbox=collected)
    check("封じた sandbox: 回収済み + 受け取り済み = 畳める (wrap は頼まない)", r["closable"] and r["kind"] == "sealed")
    r = judge(T, th(sealed, turn("spec", "done.")), None, done, sandbox={"state": "collected", "changed": 3})
    check("foil: 回収の後に変わった sandbox は残す", not r["closable"] and any("回収" in x for x in r["reasons"]))
    r = judge(T, th(sealed, turn("spec", "done.", status="inProgress")), None, done, sandbox=collected)
    check("foil: 最後の turn が進行中なら残す", not r["closable"] and any("終わっていない" in x for x in r["reasons"]))
    live = turn("spec", "working…", status="interrupted")
    live["completedAt"] = None  # measured: a running turn read through another app-server
    r = judge(T, th(sealed, live), None, done, sandbox=collected)
    check("foil: interrupted でも終了時刻が無ければ動いていると読む",
          not r["closable"] and any("終わっていない" in x for x in r["reasons"]))
    check("turn_running: 終了時刻のある interrupted は終わっている", not turn_running({"status": "interrupted", "completedAt": 5}))
    r = judge(T, th(sealed, turn("spec", "done.")), None, done, queued=2, sandbox=collected)
    check("foil: 予約された message があれば残す", not r["closable"])
    r = judge(T, th(sealed, turn("spec", "done.")), None, done, queued=None, sandbox=collected)
    check("foil: queue が読めなければ残す", not r["closable"])
    opn = {"requests": [{"project": "p", "thread": "t", "request": "r", "how": ["actor"], "status": "submitted"}], "next": []}
    r = judge(T, th(sealed, turn("spec", "done.")), None, opn, sandbox=collected)
    check("foil: 掲示板の依頼が開いていれば残す", not r["closable"] and any("開いている" in x for x in r["reasons"]))
    nxt = dict(done, next=[{"project": "p", "thread": "t2", "request": "r2", "role": "role-x"}])
    r = judge(T, th(sealed, turn("spec", "done.")), None, nxt, sandbox=collected)
    check("foil: 次の依頼があれば残す", not r["closable"] and any("次の依頼" in x for x in r["reasons"]))
    r = judge(T, th(sealed, turn("spec", "結果を書きました。 次はどうしますか？")), None, done, sandbox=collected)
    check("foil: 最後の発言が問いなら残す", not r["closable"] and any("本人待ち" in x for x in r["reasons"]))
    q = turn("spec", "done.")
    q["items"][-1]["questions"] = [{"q": "pick"}]
    r = judge(T, th(sealed, q), None, done, sandbox=collected)
    check("foil: 問いの欄があれば残す", not r["closable"])
    r = judge(T, th(sealed, turn("spec", "See [results](https://x.y/a?b) and `f?`.")), None, done, sandbox=collected)
    check("URL・code の中の ? は問いと数えない", r["closable"])
    gone = tmp / "nope"
    r = judge(T, th(gone, turn("probe", "Ran once.")), None, {"requests": [], "next": []})
    check("作業 dir が無く根拠も無ければ残す", not r["closable"] and r["kind"] == "gone")
    r = judge(T, th(gone, turn("probe", "Ran once.")), None, {"requests": [], "next": []}, evidence="plans/x.md §2.3")
    check("作業 dir が無くても指揮役の根拠があれば畳める", r["closable"])
    r = judge(T, th(work, turn("do x", "done.")), None, done)
    check("work: wrap の記録が無ければ wrap を頼む番", not r["closable"] and r["wrap_only"])
    wrap_typed = [{"type": "text", "text": "x"}, {"type": "skill", "name": "wrap", "path": "/s/wrap/SKILL.md"}]
    r = judge(T, th(work, turn("do x", "done."), turn(wrap_typed, "移した先: ...")), None, done)
    check("work: 型つきの wrap の turn の後は畳める", r["closable"] and r["wrap"] == "turn 2")
    r = judge(T, th(work, turn("do x", "done."), turn("$wrap please", "ok"),
                    turn("fix one more", "fixed", extra=[{"type": "fileChange", "changes": []}])), None, done)
    check("foil: wrap の後に file を変えたら wrap の番に戻る", not r["closable"] and r["wrap_only"])
    r = judge(T, th(work, turn("do x", "done."), turn("$wrap", "ok", status="interrupted")), None, done)
    check("foil: wrap の turn が止まったら畳まない", not r["closable"])
    r = judge(T, th(work, turn("do x", "done."), turn("$wrap", "ok")), None, {"requests": [], "next": []})
    check("foil: 掲示板に結び付かない work は根拠が要る", not r["closable"] and not r["wrap_only"])
    r = judge(T, th(work, turn("do x", "done."), turn("$wrap", "ok")), None, done, git=["repo: push されていない commit が 1 件"])
    check("foil: push されていない commit があれば残す", not r["closable"])
    os.environ["CODEX_THREAD_CLOSE_NOW"] = "1794200300"  # 5 min after the end
    r = judge(T, th(work, turn("do x", "done."), turn("one more thing", "ok"), turn("$wrap", "ok")), None, done)
    check("foil: 会話の窓は最後の turn の後 10 分は残す", not r["closable"] and any("話している途中" in x for x in r["reasons"]))
    r = judge(T, th(sealed, turn("spec", "done.")), None, done, sandbox=collected)
    check("依頼文 1 つの窓には待ちを掛けない", r["closable"])
    os.environ["CODEX_THREAD_CLOSE_NOW"] = "1794300000"
    # board links
    root = tmp / "board"
    d = root / "events" / "proj" / "2026-11-09-x"
    d.mkdir(parents=True)
    evs = [{"kind": "request", "event_id": "R1", "created_at": "2026-11-09T00:00:00Z", "actor": {"agent": "claude", "session_id": "c"},
            "summary": "盲検を起こす"},
           {"kind": "note", "event_id": "N1", "request_id": "R1", "created_at": "2026-11-09T00:01:00Z",
            "actor": {"agent": "claude", "session_id": "role-a"}, "summary": f"Codex の thread {T[:8]} を起こした"},
           {"kind": "accept", "event_id": "A1", "request_id": "R1", "created_at": "2026-11-09T00:09:00Z",
            "actor": {"agent": "claude", "session_id": "c"}, "summary": "ok"}]
    for e in evs:
        (d / f"{e['event_id']}.json").write_text(json.dumps(e, ensure_ascii=False))
    bt = board_threads([root])
    links = board_links(T, bt, unique8=True)
    check("本文の先頭 8 字で依頼に結び付き、 受け取り済みと読む",
          len(links["requests"]) == 1 and links["requests"][0]["status"] == "accepted")
    check("foil: 先頭 8 字が一意でなければ本文では結び付けない", not board_links(T, bt, unique8=False)["requests"])
    d2 = root / "events" / "proj" / "2026-11-09-y"
    d2.mkdir(parents=True)
    for e in [{"kind": "request", "event_id": "R2", "created_at": "2026-11-09T01:00:00Z", "actor": {"agent": "claude", "session_id": "c"},
               "target": {"agent": "codex", "session_id": "role-w"}, "summary": "work"},
              {"kind": "claim", "event_id": "C2", "request_id": "R2", "created_at": "2026-11-09T01:01:00Z",
               "actor": {"agent": "codex", "session_id": "role-w", "task": f"{T[:8]} (Codex)"}, "summary": "c"},
              {"kind": "accept", "event_id": "A2", "request_id": "R2", "created_at": "2026-11-09T02:00:00Z",
               "actor": {"agent": "claude", "session_id": "c"}, "summary": "ok"},
              {"kind": "request", "event_id": "R3", "created_at": "2026-11-09T03:00:00Z", "actor": {"agent": "claude", "session_id": "c"},
               "target": {"agent": "codex", "session_id": "role-w"}, "summary": "next job"}]:
        (d2 / f"{e['event_id']}.json").write_text(json.dumps(e, ensure_ascii=False))
    links = board_links(T, board_threads([root]), unique8=True)
    check("claim した役を引き、 その役宛ての未着手の依頼を次の依頼と読む",
          links["roles"] == ["role-w"] and [n["request"] for n in links["next"]] == ["R3"])
    check("request_status: release の後は引受待ちに戻る", request_status(
        [{"kind": "request", "event_id": "X"}, {"kind": "claim", "request_id": "X"}, {"kind": "release", "request_id": "X"}], "X") == "requested")
    check("asks_owner: 頼みの形 (ください) は問いと数える", asks_owner({"text": "確認してください。"}) is not None)
    check("asks_owner: 完了の報告は問いでない", asks_owner({"text": "Completed both stages.\n[Review](R.md)"}) is None)
    check("is_wrap_input: `$wrap` と型つきの入力を読む", is_wrap_input({"content": [{"type": "text", "text": "$wrap"}]})
          and is_wrap_input({"content": wrap_typed}) and not is_wrap_input({"content": [{"type": "text", "text": "wrapper"}]}))
    check("dir_kind: AGENTS.md の頭で封じた sandbox を見分ける", dir_kind(str(sealed)) == "sealed" and dir_kind(str(work)) == "work"
          and dir_kind(str(gone)) == "gone")
    check("changed_paths: 文字列の changes からも path を拾う",
          changed_paths({"turns": [{"items": [{"type": "fileChange", "changes": "[{'path': '/a/b.md', 'kind': {}}]"}]}]}) == ["/a/b.md"])
    # git: a bare remote and a clone; a file made by a shell inside a turn's window counts, one outside it does not
    bare, clone = tmp / "remote.git", tmp / "clone"
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for cmd in (["git", "init", "-q", "--bare", str(bare)], ["git", "init", "-q", "-b", "main", str(clone)]):
        subprocess.run(cmd, check=True, env=env)
    (clone / "a.txt").write_text("a\n")
    for cmd in (["add", "a.txt"], ["commit", "-qm", "a"], ["remote", "add", "origin", str(bare)], ["push", "-q", "-u", "origin", "main"]):
        subprocess.run(["git", "-C", str(clone), *cmd], check=True, env=env)
    check("git: 何も無ければ空", git_findings(str(clone), [], [(1, 2)]) == [])
    (clone / "shell-made.txt").write_text("x\n")
    m = (clone / "shell-made.txt").stat().st_mtime
    check("git: turn の間に shell で作った未 commit の file を拾う", any("turn の間" in g for g in git_findings(str(clone), [], [(m - 10, m + 10)])))
    check("foil: turn の外の時刻の未 commit の file は拾わない", git_findings(str(clone), [], [(m - 100, m - 50)]) == [])
    (clone / "shell-made.txt").unlink()
    (clone / "b.txt").write_text("b\n")
    for cmd in (["add", "b.txt"], ["commit", "-qm", "b"]):
        subprocess.run(["git", "-C", str(clone), *cmd], check=True, env=env)
    check("git: push されていない commit を拾う", any("push されていない" in g for g in git_findings(str(clone), [], [])))
    print("selftest: " + ("all passed" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("list", "check", "wrap", "wait", "archive", "unarchive"):
        p = sub.add_parser(name)
        if name != "list":
            p.add_argument("thread")
        if name != "unarchive":
            p.add_argument("--board-root", action="append")
        if name in ("check", "wrap", "archive"):
            p.add_argument("--evidence", help="指揮役の完了の判定の根拠 (file の path と節、 掲示板の id、 最後の報告の要点)")
        if name in ("list", "check"):
            p.add_argument("--json", action="store_true")
        if name == "list":
            p.add_argument("--all", action="store_true", help="畳める thread の根拠も出す")
        if name == "wrap":
            p.add_argument("--writer", choices=("daemon", "app"), default="daemon")
        if name == "wait":
            p.add_argument("--timeout", type=int, default=2400)
            p.add_argument("--interval", type=int, default=15)
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    fn = {"list": cmd_list, "check": cmd_check, "wrap": cmd_wrap, "wait": cmd_wait, "archive": cmd_archive,
          "unarchive": cmd_unarchive}.get(a.cmd)
    if not fn:
        ap.print_help()
        return 2
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
