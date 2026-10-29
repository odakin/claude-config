#!/usr/bin/env python3
"""child-wrap-check.py — 起こした子の session を畳んで (archive して) よいかを照合する。 `--wait` は子の turn が終わるまで待ってから照合する。 `--finished` は掲示板の依頼が全部受け取られたのに畳まれていない子を数える (desktop app の親 session 用、 読むだけ)。

Why (実測、 正本 = conventions/multi-session-coordination.md#tidy-after-child-turn-ends):
  - 止めて待つ向き: desktop app は、 子の turn の終わりの知らせで親を起こすのを「親が起こした子が 1 つも動いていない時」 に
    限る。 ほかの子 (長い仕事の worker) が動いていると、 知らせは親の次の turn まで待たされる = 多くは本人の次の発言に
    同梱されて届き、 親は子が終わったのを知らないまま止まっている。 一方、 親が自分の Bash を run_in_background で回すと、
    その終わりは (ほかの子が動いていても) 親の新しい turn を始める。 `--wait` はその見張り。
  - 早すぎる向き: 子が本人に頼んだ・問うたまま止まったのに、 親が代わりに答えて (別 session の message で上書きして) 子を
    閉じる。 子の最後の報告は「残りは無い」 に変わるので、 最後の知らせだけを見ると「終えた」 に見える。
  - 畳み忘れの向き (`--finished` と 2 つの hook mode): 親が子の提出を受け取った (accept) turn で畳む手順に入らず、 子が
    何時間も残る。 実測の型 = 親の文脈に畳む規則が無い (読んだ範囲が規則の 1 行下から) / 後の直しに使うつもりで残す
    (次の依頼は出していない) / 畳む前に本人に「片づけますか」 と聞いて答えを待つ。 受け取った turn の直後に 1 行を出し
    (`--hook-accept`)、 畳むべき子を残したまま turn を終えると 1 回だけ止める (`--hook-stop`)。

照合 (子ごと):
  - 動き: live の registry の status (busy = まだ動いている)
  - wrap: 子の記録の wrap skill の起動 (Skill tool の skill=wrap か、 skill の本文の差し込み)
  - commit: 子の commit (全 repo の commit に入る `Agent-Session: claude:<子の transcript id>` の trailer で引く) が、
    その repo の remote-tracking branch に入っているか (push 済みか)
  - 本人待ちの問い: 子の turn が本人待ちで終わった最後の時点 (子の wrap_up の ask / blocked、 親の記録の
    「… finished a turn and then reported that it was waiting on the user」 の知らせより前の子の最後の応答) より後に、
    子の窓に本人の発言 (人の入力。 別 session の message・hook の差し戻し・task の通知・API の誤りの後の「Try again」 は
    数えない) があるか
  - 本人と話している途中: 親が子へ最後に送った message (wrap の依頼など) より後に、 本人が子の窓で発言しているか
    (実測: 親が「片付けは不要、 wrap して終えて」 と送った直後に、 本人が同じ子に「どうやって消すの？」 と打ち、
    子が答えた 2 分後に親が畳んだ)。 子がその発言に答えて問いを残さず turn を終えていれば、 その時刻を添えて出す
    (子が止まってから ANSWERED_GRACE_MIN 分 〔既定 30、 env CHILD_WRAP_ANSWERED_GRACE_MIN、 `none` = 数え続ける〕、
    本人がその窓で話さなければ、 話している途中ではない)
  - 「Try again」: app が API の誤り (接続が切れた等) の後に入れる再試行の 1 行。 本人の新しい発言ではないので、
    上の 2 つのどちらにも数えない (実測: 子が答え終えて止まっているのに、 これ 1 行で「話している途中」 と出ていた)
判定: 動いていない・wrap の記録がある・push されていない commit が無い・本人待ちの問いも話の途中も無い = 畳んでよい。
見ないもの: 掲示板の依頼が受理されたか (受理は親自身の操作。 `--finished` は掲示板を読む)、 子が commit しなかった変更
  (同じ作業木を共有すると帰属できない)、 trailer の hook が入っていない repo の commit。

`--finished` (掲示板の root は --board-root か env CHILD_WRAP_BOARD_ROOTS = os.pathsep 区切り。 層1 に既定は無い):
  子 = app の記録で spawnedFrom が親で、 独立させていない (lineageDetached でない) もの。 子の依頼 = この機械の instance
  (`claude@<host>`) で子が claim / submit した request (actor.task の頭の transcript id 8 字か actor.session_id で引く)。
  開いている依頼 = 子が claim して受け取られていないもの + 子が claim に使った役 (role id) か子の id 宛ての、
  まだ誰も受け取っていない request (次の依頼 = 使い回し)。 状態:
    open (開いている依頼がある) / busy / owner (本人待ち) / answered (本人が子の窓で話した後に子が答え終えている = 裁定待ち) /
    due (全部受け取られ、 wrap を頼んでいない = 規則の番) / wrapping (wrap を頼んで子がまだ終えていない) /
    wrapped (wrap が終わっている = 照合して畳む) / no-board (掲示板に子の依頼が無い = 判定しない)

Usage:
  child-wrap-check.py <local_…|transcript id> [...]     照合して出す (exit 0 = 全部畳んでよい / 1 = 残すものがある / 2 = 子が見つからない)
  child-wrap-check.py --wait <local_…> [...] [--since <epoch 秒>] [--max-minutes N]
        子のどれか 1 つの turn が --since (既定 = 今の 60 秒前) より後に終わって動いていない状態になるまで待ち、 終わった子の
        照合と、 残りの子を続けて見張る 1 行を出す (親が Bash の run_in_background で回す = 終わると親が起こされる。
        全部を待つと先に終えた子が残る = 実測。 時間切れ = exit 3)
  child-wrap-check.py <id> --as-of 2026-01-01T00:00:00 照合をその時点までの記録で (RCA の再現。 動きと commit は今の状態)
  child-wrap-check.py --finished [--parent <local_…|transcript id>] --board-root <dir> [...] [--as-of …]
        掲示板の依頼が受け取られたのに畳まれていない子を数える (--parent 無し = この機械の全部の親。 exit 1 = due / wrapped がある)
  child-wrap-check.py --wait-due <local_…> [...] --board-root … [--max-minutes N]
        子のどれかが親の番 (due / wrapped。 ANSWERED_GRACE_MIN が none なら答え終えて ASK_AFTER_MIN 分も) になるまで待って
        状態と、 残りの子を続けて見張る 1 行を出す (既定 720 分、 時間切れ = exit 3)。
        本人を待っている子に親が run_in_background で出す = 本人が子の窓で答えて子が終えたとき、 ほかの子が動いていても親が起こされる
  child-wrap-check.py --hook-sendmessage [--rule <参照>]  PostToolUse(SendMessage) の hook 用: 自分の子に wrap を頼んだ
        message なら、 同じ turn に --wait の見張りを出す 1 行を additionalContext で返す (それ以外は何も出さない)
  child-wrap-check.py --hook-accept --board-root … [--rule …]   PostToolUse(Bash) の hook 用: `board.py accept` で自分の子の
        依頼を受け取った直後に、 子の状態に合わせた 1 行を返す
  child-wrap-check.py --hook-stop --board-root … [--rule …] [--stop-mode off|observe|block]   Stop の hook 用: due / wrapped の
        子を残したまま turn を終えると、 子ごとに 1 回だけ止める (observe = 記録だけ。 既定 = env CHILD_FINISHED_STOP か observe)
  --no-wrap-needed (wrap の記録を判定に入れない) / --json / --selftest
env (test): CLAUDE_SESSIONS_DIR / CLAUDE_PROJECTS_DIR / CLAUDE_DESKTOP_SESSIONS_DIR / CHILD_WRAP_REPOS_GLOB /
  CHILD_WRAP_BOARD_ROOTS / CHILD_WRAP_INSTANCE / CHILD_FINISHED_STATE_DIR
"""
from __future__ import annotations

import argparse
import calendar
import collections
import glob
import importlib.util as _ilu
import json
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import desktop_sessions as ds  # noqa: E402
import session_model as sm  # noqa: E402

_spec = _ilu.spec_from_file_location("busy_worker_stop_check", os.path.join(HERE, "busy-worker-stop-check.py"))
_bw = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_bw)

WAIT_NOTE = "finished a turn and then reported that it was waiting on the user"
PEER_FROM = re.compile(r'<cross-session-message from=\\?"(local_[0-9a-f-]+)')
MAX_COMMITS = 30
RETRY_TEXTS = {"Try again"}  # the app's retry after an API error (measured on the desktop app)
# Latin-letter boundaries, not \b: Python counts kana as word characters, so \bwrap\b misses 「wrapして」.
WRAP_WORD = re.compile(r"(?<![A-Za-z])wrap(?![A-Za-z])", re.I)
ID8 = re.compile(r"^([0-9a-f]{8})\b")
def _grace_from_env() -> float | None:
    v = (os.environ.get("CHILD_WRAP_ANSWERED_GRACE_MIN") or "").strip().lower()
    if v in ("none", "off"):
        return None
    try:
        return float(v) if v else 30.0
    except ValueError:
        return 30.0


# Minutes after the child answered the person's last prompt in its window (and left no question) from which that prompt
# no longer counts as "talking" = the child is the parent's to fold. Default 30 (the owner's ruling where this was built);
# env CHILD_WRAP_ANSWERED_GRACE_MIN=none keeps counting it (then an answered child is raised as "ask the person").
ANSWERED_GRACE_MIN: float | None = _grace_from_env()
ASK_AFTER_MIN = 10  # an "answered" child idle this long is raised once as "ask the person whether to fold" (--hook-stop / --wait-due)
RAW_ROOTS: list[str] = []  # the --board-root values as given (patterns), repeated in the commands the hooks suggest
CHILD_DAYS = 14  # children are looked for among app records touched this recently
STATE_DIR_DEFAULT = os.path.expanduser("~/.claude/state/child-finished-stop")


def _ts(e: dict) -> str:
    return str(e.get("timestamp") or "")


def _epoch(ts: str) -> float:
    return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch))


def _local_hm(ts: str) -> str:
    """'2026-10-28T09:26:52.608Z' → '10/28 18:26' in local time ('?' when unparsable)."""
    try:
        return time.strftime("%m/%d %H:%M", time.localtime(_epoch(ts)))
    except (ValueError, OverflowError):
        return "?"


def _raw_record(rec: dict | None) -> dict:
    try:
        with open(rec["path"], encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def locate(target: str) -> dict | None:
    """The child: local id, transcript id and path, title, live status, parent's transcript path, last turn edge (epoch s)."""
    t = (target or "").strip()
    if not t:
        return None
    rec = ds.find(t)
    cli = rec["cli_id"] if rec else ""
    local = rec["local_id"] if rec else (t if t.startswith("local_") else "")
    status = "(not live)"
    for s in sm.live_sessions():
        if (cli and s["sessionId"] == cli) or (local and s["host"] == local) or (not cli and not local and s["sessionId"].startswith(t)):
            status, cli, local = s["status"] or "?", s["sessionId"], local or s["host"]
            break
    if not cli and not t.startswith("local_"):
        rows = sm.resolve(t)
        cli = rows[0]["sessionId"] if rows else ""
    if not cli:
        return None
    parent_path = ""
    if rec and rec.get("parent"):
        prec = ds.find(rec["parent"])
        if prec and prec.get("cli_id"):
            parent_path = sm.transcript_path(prec["cli_id"]) or ""
    edge = _raw_record(rec).get("lastTurnEdgeAt")
    return {"local": local, "cli": cli, "title": (rec or {}).get("title", ""), "status": status,
            "archived": bool((rec or {}).get("archived")), "path": sm.transcript_path(cli) or "",
            "parent": (rec or {}).get("parent", ""), "parent_path": parent_path,
            "edge": edge / 1000 if isinstance(edge, (int, float)) else None}


def scan_child(path: str, as_of: str = "") -> dict:
    """Events from the child's transcript (timestamps): first entry, replies, turn ends, prompts of the person, asks, wrap runs.
    The app's retry line after an API error ("Try again") goes to `retries`, not to the person's prompts."""
    out = {"first": "", "replies": [], "stops": [], "human": [], "said": [], "peers": [], "asks": [], "wraps": [],
           "retries": []}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return out
    api_error = False
    with fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            ts = _ts(e)
            if as_of and ts and ts[:19] > as_of[:19]:
                continue
            kind = e.get("type")
            if ts and not out["first"]:
                out["first"] = ts
            if kind == "assistant" and ts:
                out["replies"].append(ts)
                api_error = bool(e.get("isApiErrorMessage"))
            if kind == "system" and e.get("subtype") == "stop_hook_summary":
                out["stops"].append(ts)
                continue
            said = _bw._human_text(e)
            if said:
                if api_error and said.strip() in RETRY_TEXTS:
                    out["retries"].append(ts)
                    continue
                out["human"].append(ts)
                out["said"].append((ts, said))
            elif kind in ("user", "attachment"):
                for frm in PEER_FROM.findall(json.dumps((e.get("message") or {}).get("content") or e.get("attachment") or "",
                                                        ensure_ascii=False)):
                    out["peers"].append((ts, frm))
            content = (e.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if kind == "assistant" and b.get("type") == "tool_use":
                    name, inp = str(b.get("name") or ""), b.get("input") or {}
                    if name.endswith("wrap_up") and (inp.get("ask") or inp.get("blocked") is True):
                        out["asks"].append((ts, str(inp.get("ask") or "(blocked)")))
                    elif name == "Skill" and str(inp.get("skill") or "").split(":")[-1] == "wrap":
                        out["wraps"].append(ts)
                elif kind == "user" and e.get("isMeta") and b.get("type") == "text":
                    t = b.get("text", "")
                    if t.startswith("Base directory for this skill:") and re.search(r"/skills/wrap\s", t[:300]):
                        out["wraps"].append(ts)
    return out


def parent_wait_notes(parent_path: str, local: str, as_of: str = "") -> list[str]:
    """Times the parent was told the child ended a turn waiting on the person."""
    if not parent_path or not local:
        return []
    needle, out = f"({local}) {WAIT_NOTE}", []
    try:
        with open(parent_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if needle not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("type") == "user" and _ts(e) and not (as_of and _ts(e)[:19] > as_of[:19]):
                    out.append(_ts(e))
    except OSError:
        pass
    return out


def open_ask(ev: dict, notes: list[str]) -> dict | None:
    """The child's last turn that ended waiting on the person, if no prompt of the person came in the child's window after it."""
    points = list(ev["asks"])
    for n in notes:  # a note arrives after the child's turn end; date it at the child's last reply before it
        points.append((max((s for s in ev["replies"] if s <= n), default=n), ""))
    if not points:
        return None
    at, text = max(points, key=lambda p: p[0])
    if any(h > at for h in ev["human"]):
        return None
    if not text:
        text = next((a for t, a in sorted(ev["asks"], reverse=True) if t <= at), "")
    return {"at": at, "ask": text}


def owner_after_parent(ev: dict, parent: str, now: float | None = None) -> dict | None:
    """The person's latest prompt in the child's window, if it came after the parent's latest message to the child.
    `answered_at` = the child's first turn end after that prompt when it left no question (None otherwise)."""
    sent = [ts for ts, frm in ev["peers"] if frm == parent]
    if not parent or not sent or not ev["said"]:
        return None
    at, said = max(ev["said"], key=lambda p: p[0])
    if at <= max(sent):
        return None
    ends = sorted(s for s in ev["stops"] if s > at)
    answered = ends[0] if ends and not any(t > at for t, _ in ev["asks"]) else None
    if answered and ANSWERED_GRACE_MIN is not None:
        ref = now if now is not None else time.time()
        if ref - _epoch(answered) >= ANSWERED_GRACE_MIN * 60:
            return None
    return {"at": at, "said": said, "parent_at": max(sent), "answered_at": answered}


def _talking_text(talking: dict) -> str:
    s = (f"本人がこの子と話している途中 (親の最後の指示 {_local_hm(talking['parent_at'])} の後、"
         f" {_local_hm(talking['at'])} に本人がこの子の窓で発言): {talking['said'][:120]}")
    if talking.get("answered_at"):
        s += f" (子は {_local_hm(talking['answered_at'])} に答えて turn を終え、 問いを残していない)"
    return s


def _git(repo: str, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=20)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def child_commits(cli: str, since: str) -> list[dict]:
    """The child's commits in every repo (by the Agent-Session trailer), newest first, with whether each is pushed."""
    pattern = os.environ.get("CHILD_WRAP_REPOS_GLOB") or os.path.expanduser("~/Claude/*/.git")
    out = []
    for g in sorted(glob.glob(pattern)):
        repo = os.path.dirname(g)
        args = ["log", "--all", "-F", f"--grep=Agent-Session: claude:{cli}", "--format=%h %cI"] + ([f"--since={since}"] if since else [])
        for line in _git(repo, *args)[1].splitlines():
            sha, _, at = line.partition(" ")
            if sha:
                pushed = bool(_git(repo, "branch", "-r", "--contains", sha)[1].strip())
                out.append({"at": at, "sha": sha, "repo": repo, "pushed": pushed})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:MAX_COMMITS]


def _ask_text(ask: dict) -> str:
    return (f"本人待ちの問いが残っている ({_local_hm(ask['at'])} に本人待ちで止まり、 その後この子の窓に本人の発言が無い)"
            + (f": {ask['ask'][:160]}" if ask["ask"] else ""))


def owner_reasons(target: str) -> list[str]:
    """Only the person-side reasons to keep a child (an ask left open / the person talking with it): the cheap part
    of check_child, for the archive guard (scripts/busy-worker-stop-check.py). [] when the child is not found."""
    c = locate(target)
    if not c:
        return []
    ev = scan_child(c["path"])
    out = []
    ask = open_ask(ev, parent_wait_notes(c["parent_path"], c["local"]))
    if ask:
        out.append(_ask_text(ask))
    talking = owner_after_parent(ev, c["parent"])
    if talking:
        out.append(_talking_text(talking))
    return out


def check_child(target: str, as_of: str = "", need_wrap: bool = True, wrap_since: str = "") -> dict:
    c = locate(target)
    if not c:
        return {"target": target, "found": False, "ok": False, "reasons": ["子が見つからない (app の記録にも live の registry にも無い)"]}
    ev = scan_child(c["path"], as_of)
    earlier_wraps = []
    if wrap_since:  # after --wait: only a wrap run for this request counts, not one from an earlier request
        earlier_wraps = [w for w in ev["wraps"] if w[:19] < wrap_since[:19]]
        ev["wraps"] = [w for w in ev["wraps"] if w[:19] >= wrap_since[:19]]
    ask = open_ask(ev, parent_wait_notes(c["parent_path"], c["local"], as_of))
    commits = child_commits(c["cli"], ev["first"][:19])
    reasons = []
    if not as_of and c["status"] == "busy":
        reasons.append("まだ動いている (turn の途中)")
    if ask:
        reasons.append(_ask_text(ask))
    talking = owner_after_parent(ev, c["parent"], _epoch(as_of) if as_of else None)
    if talking:
        reasons.append(_talking_text(talking))
    if need_wrap and not ev["wraps"]:
        # measured: a parent passed --since 10 minutes after its wrap request, and the wrap run fell outside the window
        reasons.append("wrap の記録が無い" + (f" (--since より前の {_local_hm(max(earlier_wraps))} に wrap の記録がある = --since が"
                                              " wrap の依頼より後になっている。 依頼の時刻 〔hook が出す --since の値〕 か、 それより前を渡す)"
                                              if earlier_wraps else ""))
    bad = [x for x in commits if not x["pushed"]]
    if bad:
        reasons.append("push されていない commit: " + ", ".join(f"{os.path.basename(x['repo'])} {x['sha']}" for x in bad))
    return {"target": target, "found": True, "ok": not reasons, "reasons": reasons, "local": c["local"], "title": c["title"],
            "status": c["status"], "archived": c["archived"], "last_wrap": max(ev["wraps"], default=""),
            "last_turn_end": max(ev["stops"], default=""), "commits": commits, "open_ask": ask}


def render(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        lines.append(f"{'✅ 畳んでよい' if r['ok'] else '⏸ 残す'}  {r.get('title') or r['target']} ({r.get('local') or r['target']})")
        if not r["found"]:
            lines.append("    " + r["reasons"][0])
            continue
        lines.append(f"    動き={r['status']}  最後の turn の終わり={_local_hm(r['last_turn_end']) if r['last_turn_end'] else 'なし'}"
                     f"  wrap={_local_hm(r['last_wrap']) if r['last_wrap'] else 'なし'}"
                     + ("  (archive 済み)" if r["archived"] else ""))
        if r["commits"]:
            lines.append("    commit: " + ", ".join(f"{os.path.basename(x['repo'])} {x['sha']}{'' if x['pushed'] else ' (未 push)'}"
                                                 for x in r["commits"][:8]) + (" ほか" if len(r["commits"]) > 8 else ""))
        for why in r["reasons"]:
            lines.append("    → " + why)
    return "\n".join(lines)


def turn_done_after(target: str, since: float) -> tuple[bool, str]:
    c = locate(target)
    if not c:
        return True, "見つからない"
    if c["status"] == "busy":
        return False, "動いている"
    ends = [_epoch(s) for s in scan_child(c["path"])["stops"][-3:] if s]
    if (c["edge"] and c["edge"] > since) or any(e > since for e in ends):
        return True, "終わった"
    if c["status"] == "(not live)":
        return True, "process が無い (turn は始まっていない)"
    return False, "まだ始まっていない"


def wait(targets: list[str], since: float, max_minutes: float, interval: float = 20.0) -> tuple[int, list[str]]:
    """Wait until at least one child's turn has ended after `since`; (0, the children done) or (3, []) on time-out.
    Measured: waiting for all of them left the child that finished first idle until the person noticed."""
    deadline = time.time() + max_minutes * 60
    while True:
        states = {t: turn_done_after(t, since) for t in targets}
        done = [t for t, (d, _) in states.items() if d]
        if done:
            return 0, done
        if time.time() > deadline:
            print("⌛ 待ち切れなかった: " + ", ".join(f"{t} ({why})" for t, (d, why) in states.items() if not d))
            return 3, []
        time.sleep(interval)


def _watch_running(local: str) -> bool:
    """A `--wait` / `--wait-due` watch on this child is running (on this machine)."""
    try:
        ps = subprocess.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        ps = ""
    return any("child-wrap-check.py" in ln and "--wait" in ln and local in ln for ln in ps.splitlines())


def _roots_args() -> str:
    return " ".join("--board-root '" + r.replace(os.path.expanduser("~"), "~", 1) + "'" for r in RAW_ROOTS)


def _wait_due_cmd(locals_: list[str]) -> str:
    return (f"python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait-due {' '.join(locals_)} {_roots_args()}"
            .strip())


def hook_sendmessage(inp: dict, rule: str) -> str:
    """additionalContext for a SendMessage that asks one's own child to wrap; '' otherwise."""
    if inp.get("tool_name") != "SendMessage":
        return ""
    ti = inp.get("tool_input") or {}
    to, msg = str(ti.get("to") or ""), str(ti.get("message") or "")
    if not to.startswith("local_") or not WRAP_WORD.search(msg):
        return ""
    me, child = ds.find(str(inp.get("session_id") or "")), ds.find(to)
    if not me or not child or child.get("parent") != me.get("local_id"):
        return ""
    if _watch_running(to):
        return ""
    since = int(time.time()) - 30
    return ("🧺 child-wrap-check: 子 (" + (child.get("title") or to) + ") に wrap を頼んだ。 ほかの子が動いている間は、 子の turn の終わりで"
            " app はこの session を起こさない (知らせは本人の次の発言まで待たされる、 実測)。 この turn のうちに Bash を"
            f" run_in_background で `python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait {to} --since {since}`"
            " を出す (同じ turn で複数の子に頼んだら id を並べた 1 本。 どれか 1 つが終わると見張りは終わり、 残りを続けて見張る 1 行が出る)。 子の turn が終わるとこの session が起こされ、 畳んでよいかの照合が出る。"
            + (f" 規則 = {rule}" if rule else ""))


# ---------------------------------------------------------------- board side (--finished / --hook-accept / --hook-stop)

def instance_name() -> str:
    """The board's instance for this machine (board.py writes agent@<short hostname>)."""
    return os.environ.get("CHILD_WRAP_INSTANCE") or "claude@" + socket.gethostname().split(".")[0]


def board_roots(extra: list[str] | None = None) -> list[str]:
    raw = list(extra or []) + [x for x in (os.environ.get("CHILD_WRAP_BOARD_ROOTS") or "").split(os.pathsep) if x]
    out = []
    for r in raw:
        for p in sorted(glob.glob(os.path.expanduser(r))) or [os.path.expanduser(r)]:
            if os.path.isdir(os.path.join(p, "events")) and p not in out:
                out.append(p)
    return out


def _compact(iso: str) -> str:
    """'2026-01-02T03:04:05' → '20260102T030405Z' (the board's event file names start with this)."""
    s = re.sub(r"[^0-9T]", "", iso[:19])
    return s + "Z" if len(s) == 15 else ""


def load_board(roots: list[str], since: str = "") -> list[dict]:
    prefix, out = _compact(since) if since else "", []
    for root in roots:
        for p in glob.glob(os.path.join(root, "events", "*", "*", "*.json")):
            if prefix and os.path.basename(p)[:16] < prefix:
                continue
            try:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(d, dict):
                out.append(d)
    return out


def _actor(e: dict) -> dict:
    a = e.get("actor")
    return a if isinstance(a, dict) else {}


def board_state(cli: str, events: list[dict], instance: str, as_of: str = "") -> dict:
    """The child's requests on the board: claimed (this machine), open ones, and when the last of them was accepted."""
    evs = [e for e in events if not (as_of and str(e.get("created_at") or "")[:19] > as_of[:19])]
    by_req: dict[str, list[dict]] = collections.defaultdict(list)
    for e in evs:
        if e.get("request_id"):
            by_req[e["request_id"]].append(e)
    mine, roles = set(), set()
    for e in evs:
        a = _actor(e)
        if a.get("instance") != instance or e.get("kind") not in ("claim", "submit") or not e.get("request_id"):
            continue
        sid, m = str(a.get("session_id") or ""), ID8.match(str(a.get("task") or ""))
        if (m and m.group(1) == cli[:8]) or (cli and sid == cli):
            mine.add(e["request_id"])
            if sid and sid != cli:
                roles.add(sid)
    accepted = {rid: max(str(e.get("created_at") or "") for e in es if e.get("kind") == "accept")
                for rid, es in by_req.items() if any(e.get("kind") == "accept" for e in es)}
    open_ = sorted(r for r in mine if r not in accepted)
    for rid, es in by_req.items():
        if rid in mine or rid in accepted:
            continue
        req = next((e for e in es if e.get("kind") == "request"), None)
        tgt = str(((req or {}).get("assignee") or {}).get("session_id") or "")
        if tgt and (tgt in roles or tgt == cli):
            open_.append(rid)
    threads = {rid: str(by_req[rid][0].get("thread_id") or rid) for rid in set(mine) | set(open_) if by_req.get(rid)}
    return {"claimed": sorted(mine), "open": open_, "threads": threads,
            "accepted_at": max(accepted[r] for r in mine) if mine and not open_ else ""}


def children_of(parent_local: str) -> list[dict]:
    """App records whose spawnedFrom is the parent (touched in the last CHILD_DAYS days)."""
    out, cutoff = [], time.time() - CHILD_DAYS * 86400
    for p in glob.glob(os.path.join(ds.root(), "*", "*", "local_*.json")):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
            with open(p, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            continue
        if parent_local not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        sf = d.get("spawnedFrom") if isinstance(d.get("spawnedFrom"), dict) else {}
        if sf.get("sessionId") != parent_local:
            continue
        out.append({"local": str(d.get("sessionId") or ""), "cli": str(d.get("cliSessionId") or ""),
                    "title": str(d.get("title") or ""), "archived": bool(d.get("isArchived")),
                    "detached": bool(d.get("lineageDetached")), "created_ms": d.get("createdAt") or 0})
    return out


def parent_actions(parent_path: str, child_local: str, as_of: str = "") -> dict:
    """The parent's wrap requests (SendMessage with the word) and archive calls for this child (timestamps)."""
    out = {"wraps": [], "archives": []}
    if not parent_path or not child_local:
        return out
    try:
        fh = open(parent_path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            if child_local not in line or '"assistant"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            ts = _ts(e)
            if not isinstance(e, dict) or e.get("type") != "assistant" or (as_of and ts[:19] > as_of[:19]):
                continue
            for b in (e.get("message") or {}).get("content") or []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                name, inp = str(b.get("name") or ""), b.get("input") or {}
                if name == "SendMessage" and str(inp.get("to") or "") == child_local and WRAP_WORD.search(str(inp.get("message") or "")):
                    out["wraps"].append(ts)
                elif name.endswith("archive_session") and str(inp.get("session_id") or "") == child_local:
                    out["archives"].append(ts)
    return out


def finished_state(child: dict, parent_local: str, parent_path: str, events: list[dict], instance: str,
                   as_of: str = "") -> dict:
    row = dict(child, parent=parent_local, state="", accepted_at="", reasons=[], hours=None, threads={})
    b = board_state(child["cli"], events, instance, as_of)
    row["threads"], row["accepted_at"] = b["threads"], b["accepted_at"]
    if not b["claimed"]:
        row["state"] = "no-board"
        return row
    if b["open"]:
        row["state"] = "open"
        row["open"] = [b["threads"].get(r, r) for r in b["open"]]
        return row
    acts = parent_actions(parent_path, child["local"], as_of)
    if as_of and any(t[:19] <= as_of[:19] for t in acts["archives"]):
        row["state"] = "archived"
        return row
    ev = scan_child(sm.transcript_path(child["cli"]) or "", as_of)
    now = _epoch(as_of) if as_of else time.time()
    row["hours"] = round((now - _epoch(b["accepted_at"])) / 3600, 1)
    if as_of:
        busy = bool(ev["replies"]) and max(ev["replies"]) > max(ev["stops"], default="")
    else:
        busy = any((s["sessionId"] == child["cli"] or s["host"] == child["local"]) and s["status"] == "busy"
                   for s in sm.live_sessions())
    if busy:
        row["state"] = "busy"
        return row
    ask = open_ask(ev, parent_wait_notes(parent_path, child["local"], as_of))
    talking = owner_after_parent(ev, parent_local, now)
    if ask:
        row["reasons"].append(_ask_text(ask))
    if talking:
        row["reasons"].append(_talking_text(talking))
    if row["reasons"]:
        if talking and talking.get("answered_at") and not ask:
            row["state"], row["answered_at"] = "answered", talking["answered_at"]
            row["answered_min"] = round((now - _epoch(talking["answered_at"])) / 60)
        else:
            row["state"] = "owner"
            row["wait_since"] = (ask or talking or {}).get("at", "")
        return row
    wraps = sorted(t for t in acts["wraps"] + ev["wraps"] if t[:19] >= b["accepted_at"][:19])
    # a turn end counts only when the child started replying after the request (measured: the child's previous turn
    # ended 3 s after the parent's SendMessage, before the message was delivered)
    last = wraps[-1] if wraps else ""
    if last in ev["wraps"]:
        started = last
    else:  # from the delivery of the parent's message in the child's window
        got = min((ts for ts, frm in ev["peers"] if frm == parent_local and last and ts >= last), default=last)
        started = min((r for r in ev["replies"] if got and r > got), default="")
    if not wraps:
        row["state"] = "due"
    elif started and any(s > started for s in ev["stops"]):
        row["state"] = "wrapped"
    else:
        row["state"] = "wrapping"
    return row


def finished(parent: str, roots: list[str], as_of: str = "", instance: str | None = None) -> list[dict]:
    """--finished for one parent (local_… or transcript id)."""
    prec = ds.find(parent)
    if not prec:
        return []
    kids = [c for c in children_of(prec["local_id"]) if not c["detached"] and (as_of or not c["archived"]) and c["cli"]]
    if as_of:
        kids = [c for c in kids if c["created_ms"] and _iso(c["created_ms"] / 1000) <= as_of[:19]]
    if not kids:
        return []
    since = _iso(min(c["created_ms"] for c in kids) / 1000 - 86400) if all(c["created_ms"] for c in kids) else ""
    events = load_board(roots, since)
    ppath = sm.transcript_path(prec["cli_id"]) or ""
    return [finished_state(c, prec["local_id"], ppath, events, instance or instance_name(), as_of) for c in kids]


DONE_STATES = ("due", "wrapped", "archived", "no-board")


def _settled(r: dict) -> bool:
    """--wait-due ends here: the child is the parent's turn again (or gone)."""
    return r["state"] in DONE_STATES or (r["state"] == "answered" and ANSWERED_GRACE_MIN is None
                                         and r.get("answered_min", 0) >= ASK_AFTER_MIN)


def child_row(local: str) -> tuple[dict | None, dict | None]:
    """(child dict as children_of gives, parent's app record) for one child id."""
    rec = ds.find(local)
    if not rec or not rec.get("parent"):
        return None, None
    raw = _raw_record(rec)
    child = {"local": rec["local_id"], "cli": rec["cli_id"], "title": rec["title"], "archived": rec["archived"],
             "detached": bool(raw.get("lineageDetached")), "created_ms": rec.get("created_ms") or 0}
    return child, ds.find(rec["parent"])


def wait_due(targets: list[str], roots: list[str], max_minutes: float, interval: float = 60.0) -> int:
    """Wait until every child is settled (the parent's turn: fold it, or ask the person), then print the states.
    For a child that waits on the person: the person may answer in the child's window hours later, while another child
    of the parent is running, so the app's own turn-end note would not wake the parent (see the docstring)."""
    deadline = time.time() + max_minutes * 60
    while True:
        rows = []
        for t in targets:
            child, prec = child_row(t)
            if not child or not prec:
                rows.append({"local": t, "title": "", "parent": "", "state": "archived", "reasons": [], "hours": None,
                             "accepted_at": ""})
                continue
            if child["archived"]:
                rows.append(dict(child, parent=prec["local_id"], state="archived", reasons=[], hours=None, accepted_at=""))
                continue
            events = load_board(roots, _iso(child["created_ms"] / 1000 - 86400) if child["created_ms"] else "")
            rows.append(finished_state(child, prec["local_id"], sm.transcript_path(prec["cli_id"]) or "", events, instance_name()))
        settled = [r for r in rows if _settled(r)]
        if settled:  # the first child that is the parent's turn ends the watch (the rest are re-watched)
            print(f"🧺 子 {len(settled)} 件が親の番になった ({time.strftime('%H:%M')}):")
            print(render_finished(settled))
            rest = [r["local"] for r in rows if not _settled(r)]
            if rest:
                print(f"⏳ まだ親の番でない子 {len(rest)} 件 → 畳み終えたら、 続けて見張る (run_in_background): `{_wait_due_cmd(rest)}`")
            return 0
        if time.time() > deadline:
            print("⌛ 待ち切れなかった:\n" + render_finished([r for r in rows if not _settled(r)]))
            return 3
        time.sleep(interval)


def all_parents() -> list[str]:
    out, cutoff = set(), time.time() - CHILD_DAYS * 86400
    for p in glob.glob(os.path.join(ds.root(), "*", "*", "local_*.json")):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        sf = d.get("spawnedFrom") if isinstance(d, dict) and isinstance(d.get("spawnedFrom"), dict) else {}
        if sf.get("sessionId") and not d.get("lineageDetached") and not d.get("isArchived"):
            out.add(sf["sessionId"])
    return sorted(out)


STATE_WORDS = {"due": "規則 10 の番 (wrap を頼んでいない)", "wrapped": "wrap は終わっている = 照合して畳む",
               "wrapping": "wrap の途中", "owner": "本人待ち = 残す", "answered": "本人の発言に子が答え終えている (裁定待ち = 今は残す)",
               "open": "開いている依頼がある", "busy": "動いている", "no-board": "掲示板に依頼が無い", "archived": "archive 済み"}


def render_finished(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        mark = "🧺" if r["state"] in ("due", "wrapped") else "  "
        h = f"  受け取り {_local_hm(r['accepted_at'])} から {r['hours']} 時間" if r.get("hours") is not None else ""
        lines.append(f"{mark} [{r['state']}] {r['title'] or r['local']} ({r['local']})  親={r['parent']}{h}  — {STATE_WORDS.get(r['state'], '')}")
        for why in r["reasons"]:
            lines.append("      → " + why)
        if r.get("open"):
            lines.append("      → 開いている依頼: " + ", ".join(r["open"]))
    return "\n".join(lines)


def _accept_line(r: dict, rule: str, extra: str = "") -> str:
    who = f"子 {r['title'] or r['local']} ({r['local']})"
    tail = f" 規則 = {rule}" if rule else ""
    if r["state"] == "due":
        return (f"🧺 規則 10 の番: {who} の依頼を受け取った (accept)。 この子に開いている依頼は無く、 本人も待っていない。"
                " この turn のうちに規則 10 の順で畳む = model を確かめる → wrap を頼む → 同じ turn に見張り"
                f" (`python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait {r['local']}`) → 起こされたら照合して archive。"
                " 次の仕事に使うなら、 この turn に次の依頼を掲示板に出す (宛先 = その子の役。 道具は開いている依頼と数える)。"
                + (f" {extra}" if extra else "") + tail)
    if r["state"] == "owner":
        return (f"🧺 {who} の依頼を受け取った。 子は本人を待っている ({'; '.join(r['reasons'])[:300]})"
                " = 規則 10 では残し、 本人に 1 行で伝える。 本人が子の窓で答えて子が終えたときに起こされるよう、 同じ turn に"
                f" Bash の run_in_background で `{_wait_due_cmd([r['local']])}` を出す (ほかの子が動いていると、 app は子の"
                " turn の終わりでこの session を起こさない)。" + tail)
    if r["state"] == "answered" and ANSWERED_GRACE_MIN is not None:
        return (f"🧺 {who} の依頼を受け取った。 本人がこの子の窓で話した後、 子は答え終えて問いを残していない"
                f" ({'; '.join(r['reasons'])[:300]})。 本人がその窓で {ANSWERED_GRACE_MIN:g} 分話さなければ畳む番になる ="
                f" 起こされるよう Bash の run_in_background で `{_wait_due_cmd([r['local']])}` を出す。" + tail)
    if r["state"] == "answered":
        return (f"🧺 {who} の依頼を受け取った。 本人がこの子の窓で話した後、 子は答え終えて問いを残していない"
                f" ({'; '.join(r['reasons'])[:300]})。 道具は残す側 = 畳むかを本人に 1 行で聞く。" + tail)
    return ""


def hook_accept(inp: dict, roots: list[str], rule: str, extra: str = "") -> str:
    """additionalContext after `board.py accept` of a request one's own child worked on; '' otherwise."""
    if inp.get("tool_name") != "Bash":
        return ""
    cmd = str((inp.get("tool_input") or {}).get("command") or "")
    if not re.search(r"board\.py['\"]?\s+accept\b", cmd):
        return ""
    m = re.search(r"--request[= ]+['\"]?(\d{8}T\d{6}Z-[a-z]+-[0-9a-f]+)", cmd)
    me = ds.find(str(inp.get("session_id") or ""))
    if not m or not me or not roots:
        return ""
    rid, instance = m.group(1), instance_name()
    events = load_board(roots)
    workers = set()
    for e in events:
        a = _actor(e)
        if e.get("request_id") == rid and e.get("kind") in ("claim", "submit") and a.get("instance") == instance:
            mm = ID8.match(str(a.get("task") or ""))
            workers.add(mm.group(1) if mm else str(a.get("session_id") or "")[:8])
    if not workers:
        return ""
    ppath = sm.transcript_path(me["cli_id"]) or ""
    lines = []
    for c in children_of(me["local_id"]):
        if c["cli"][:8] in workers and not c["detached"] and not c["archived"]:
            line = _accept_line(finished_state(c, me["local_id"], ppath, events, instance), rule, extra)
            if line:
                lines.append(line)
    return "\n".join(lines)


def _state_file(parent_local: str) -> str:
    d = os.environ.get("CHILD_FINISHED_STATE_DIR") or STATE_DIR_DEFAULT
    return os.path.join(d, re.sub(r"[^A-Za-z0-9_.-]", "_", parent_local) + ".json")


def hook_stop(inp: dict, roots: list[str], rule: str, mode: str, extra: str = "") -> str:
    """A Stop decision (JSON) when the session ends a turn leaving a child due to be wrapped/archived; '' otherwise.
    Once per child and accept time: the second Stop for the same child is silent."""
    if mode == "off" or not roots:
        return ""
    me = ds.find(str(inp.get("session_id") or ""))
    if not me:
        return ""
    rows = finished(me["local_id"], roots)
    due = [r for r in rows if r["state"] in ("due", "wrapped", "answered", "owner") and not _watch_running(r["local"])]
    if not due:
        return ""
    path = _state_file(me["local_id"])
    try:
        with open(path, encoding="utf-8") as fh:
            seen = json.load(fh)
    except (OSError, ValueError):
        seen = {}
    def key(r: dict) -> str:
        late = (r["state"] == "answered" and ANSWERED_GRACE_MIN is None
                and r.get("answered_min", 0) >= ASK_AFTER_MIN)  # recent → watch, later → ask
        return f"{r['accepted_at']}|{r['state']}{'+' if late else ''}|{r.get('answered_at') or r.get('wait_since') or ''}"

    new = [r for r in due if seen.get(r["local"]) != key(r)]
    if not new:
        return ""
    for r in new:
        seen[r["local"]] = key(r)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(seen, fh, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError:
        pass
    if mode == "observe":
        try:
            with open(os.path.join(os.path.dirname(path), "observe.jsonl"), "a", encoding="utf-8") as fh:
                for r in new:
                    fh.write(json.dumps({"at": _iso(time.time()), "parent": me["local_id"], "child": r["local"],
                                         "state": r["state"], "accepted_at": r["accepted_at"]}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return ""
    fold = [r for r in new if r["state"] in ("due", "wrapped")]
    ask = [r for r in new if r["state"] == "answered" and ANSWERED_GRACE_MIN is None
           and r.get("answered_min", 0) >= ASK_AFTER_MIN]
    watch = [r for r in new if r not in fold and r not in ask]
    lines = []
    if fold:
        lines.append(f"🧺 規則 10 の番の子が {len(fold)} つ、 畳まれないまま残っている (掲示板の依頼は全部受け取り済みで、 子は動いておらず本人も待っていない):")
        for r in fold:
            lines.append(f"- {r['title'] or r['local']} ({r['local']}) — 受け取り {_local_hm(r['accepted_at'])} から {r['hours']} 時間"
                         + ("、 wrap は終わっている = 照合して archive" if r["state"] == "wrapped" else ""))
        lines.append("この turn のうちに規則 10 の順で畳む (wrap を頼む → 見張り → 照合 → archive)。 本人がこの子について別の指示を"
                     "しているなら (例 = 使用量の上限が戻るまで待つ)、 それを本人に 1 行で書いて turn を終える。"
                     + (f" {extra}" if extra else ""))
    if ask:
        lines.append(f"🧺 依頼は全部受け取り済みで、 本人がその窓で話した後に子が答え終え、 {ASK_AFTER_MIN} 分以上止まっている子が {len(ask)} つ"
                     " (規則 10 の「話している間」 に入るかは本人の裁定待ち = 道具は残す側):")
        for r in ask:
            lines.append(f"- {r['title'] or r['local']} ({r['local']}) — 子は {_local_hm(r['answered_at'])} に答え終えた")
        lines.append("畳んでよいかを本人に 1 行で聞く (子の窓で続けるなら残す)。")
    if watch:
        lines.append(f"🧺 依頼は全部受け取り済みで、 本人を待っている子"
                     + (f" か本人の発言に答え終えて {ANSWERED_GRACE_MIN:g} 分たたない子" if ANSWERED_GRACE_MIN is not None else "")
                     + f"が {len(watch)} つ (残す): "
                     + "、 ".join(f"{r['title'] or r['local']} ({r['local']})" for r in watch))
        lines.append("本人に 1 行で伝え (まだなら)、 本人が子の窓で答えて子が終えたときに起こされるよう、 Bash の run_in_background で"
                     f" `{_wait_due_cmd([r['local'] for r in watch])}` を出す (ほかの子が動いていると、 app は子の turn の終わりで"
                     " この session を起こさない)。")
    lines.append("この知らせは子ごとに 1 回だけ。")
    if rule:
        lines.append(f"規則 = {rule}")
    return json.dumps({"decision": "block", "reason": "\n".join(lines)}, ensure_ascii=False)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="起こした子の session を畳んでよいかを照合する")
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--wait-due", action="store_true")
    # epoch seconds or ISO time (measured: a parent passed `date -u +%Y-%m-%dT%H:%M:%SZ` and the watch failed to start)
    ap.add_argument("--since", type=lambda s: float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else float(_epoch(s.rstrip("Z"))))
    ap.add_argument("--max-minutes", type=float, default=180)
    ap.add_argument("--as-of", default="")
    ap.add_argument("--no-wrap-needed", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hook-sendmessage", action="store_true")
    ap.add_argument("--hook-accept", action="store_true")
    ap.add_argument("--hook-stop", action="store_true")
    ap.add_argument("--stop-mode", choices=("off", "observe", "block"))
    ap.add_argument("--finished", action="store_true")
    ap.add_argument("--parent", default="")
    ap.add_argument("--board-root", action="append", default=[])
    ap.add_argument("--rule", default="")
    ap.add_argument("--extra", default="", help="hook の文に足す 1 文 (個人層の規則の要点)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    RAW_ROOTS[:] = list(a.board_root) + [x for x in (os.environ.get("CHILD_WRAP_BOARD_ROOTS") or "").split(os.pathsep) if x]
    if a.wait_due:
        roots = board_roots(a.board_root)
        if not a.targets or not roots:
            ap.error("--wait-due には子の local_… と --board-root (か env CHILD_WRAP_BOARD_ROOTS) が要る")
        return wait_due(a.targets, roots, a.max_minutes if a.max_minutes != 180 else 720)
    if a.hook_sendmessage or a.hook_accept or a.hook_stop:
        try:
            inp = json.loads(sys.stdin.read() or "{}")
            if a.hook_stop:
                out = hook_stop(inp, board_roots(a.board_root), a.rule,
                                a.stop_mode or os.environ.get("CHILD_FINISHED_STOP") or "observe", a.extra)
                if out:
                    print(out)
                return 0
            ctx = (hook_accept(inp, board_roots(a.board_root), a.rule, a.extra) if a.hook_accept
                   else hook_sendmessage(inp, a.rule))
        except Exception:
            return 0  # fail-open
        if ctx:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}, ensure_ascii=False))
        return 0
    if a.finished:
        roots = board_roots(a.board_root)
        if not roots:
            ap.error("--finished には --board-root (か env CHILD_WRAP_BOARD_ROOTS) が要る")
        rows = [r for p in ([a.parent] if a.parent else all_parents()) for r in finished(p, roots, a.as_of)]
        print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else (render_finished(rows) or "(該当する子なし)"))
        return 1 if any(r["state"] in ("due", "wrapped") for r in rows) else 0
    if not a.targets:
        ap.error("子の local_… か transcript id を 1 つ以上")
    wrap_since, targets, rest = "", a.targets, []
    if a.wait:
        since = a.since if a.since is not None else time.time() - 60
        rc, done = wait(a.targets, since, a.max_minutes)
        if rc:
            return rc
        wrap_since = _iso(since)
        targets, rest = done, [t for t in a.targets if t not in done]
        print(f"🧺 子 {len(done)} 件の turn が終わった ({time.strftime('%H:%M')})。 照合:")
    rows = [check_child(t, a.as_of, not a.no_wrap_needed, wrap_since) for t in targets]
    print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else render(rows))
    if rest:
        print(f"⏳ まだ終わっていない子 {len(rest)} 件 → 畳み終えたら、 続けて見張る (run_in_background):"
              f" `python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait {' '.join(rest)} --since {int(since)}`")
    if any(not r["found"] for r in rows):
        return 2
    return 0 if all(r["ok"] for r in rows) else 1


def selftest() -> int:
    import tempfile

    global ANSWERED_GRACE_MIN
    saved_grace, ANSWERED_GRACE_MIN = ANSWERED_GRACE_MIN, None  # the cases below were written for "keep counting"
    fails: list[str] = []

    def ok(label: str, cond: bool) -> None:
        print(("ok: " if cond else "NG: ") + label)
        if not cond:
            fails.append(label)

    def u(ts: str, text: str, **kw) -> dict:
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **kw}

    def peer(ts: str, text: str, frm: str = "local_55555555-0000-4000-8000-000000000000") -> dict:
        # a peer session's message as the desktop app writes it: a long reminder first
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content":
                "<system-reminder>\n" + "Linked sessions now ... " * 20 + f"\n</system-reminder>\n<cross-session-message from=\"{frm}\">"
                + text + "</cross-session-message>"}}

    def reply(ts: str, ask: str | None = None) -> dict:
        inp = {"recap": "r"} | ({"ask": ask} if ask else {})
        return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "id": "w", "name": "mcp__ccd_turn__wrap_up", "input": inp}]}}

    def api_err(ts: str) -> dict:
        return {"type": "assistant", "timestamp": ts, "isApiErrorMessage": True,
                "message": {"content": [{"type": "text", "text": "API Error: Can't reach the API server"}]}}

    def stop(ts: str) -> dict:
        return {"type": "system", "subtype": "stop_hook_summary", "timestamp": ts}

    with tempfile.TemporaryDirectory() as td:
        sdir, pdir, ddir = (os.path.join(td, x) for x in ("sessions", "projects", "desktop"))
        for d in (sdir, os.path.join(pdir, "-w"), os.path.join(ddir, "acct", "env")):
            os.makedirs(d)
        os.environ.update(CLAUDE_SESSIONS_DIR=sdir, CLAUDE_PROJECTS_DIR=pdir, CLAUDE_DESKTOP_SESSIONS_DIR=ddir,
                          CHILD_WRAP_REPOS_GLOB=os.path.join(td, "none", "*", ".git"))
        parent_l, parent_c = "local_00000000-0000-4000-8000-000000000000", "00000000-aaaa-4000-8000-000000000000"
        kids = {"answered": "11111111", "overridden": "22222222", "busy": "33333333", "nowrap": "44444444"}

        def ids(k: str) -> tuple[str, str]:
            n = kids[k]
            return f"local_{n}-0000-4000-8000-000000000000", f"{n}-cccc-4000-8000-000000000000"

        def record(local: str, cli: str, parent: str = "", **extra) -> None:
            with open(os.path.join(ddir, "acct", "env", local + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"sessionId": local, "cliSessionId": cli, "title": local[:14], "isArchived": False,
                           "spawnedFrom": {"sessionId": parent} if parent else {}, "lastTurnEdgeAt": 1000,
                           "createdAt": 1767225600000} | extra, fh)  # createdAt = 2026-01-01T00:00:00Z

        def transcript(cli: str, rows: list[dict]) -> None:
            with open(os.path.join(pdir, "-w", cli + ".jsonl"), "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

        def live(n: int, cli: str, local: str, status: str) -> None:
            with open(os.path.join(sdir, f"{n}.json"), "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "sessionId": cli, "hostSessionId": local, "cwd": "/w", "status": status}, fh)

        record(parent_l, parent_c)
        notes = []
        for n, k in enumerate(kids):
            local, cli = ids(k)
            record(local, cli, parent_l)
            live(n, cli, local, "busy" if k == "busy" else "idle")
            wrap = [{"type": "assistant", "timestamp": "2026-01-01T01:05:00Z",
                     "message": {"content": [{"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}}]
            rows = [u("2026-01-01T00:00:00Z", "依頼", origin={"kind": "human"}), reply("2026-01-01T00:10:00Z"),
                    stop("2026-01-01T00:10:01Z")]
            if k in ("answered", "overridden"):
                rows += [u("2026-01-01T00:20:00Z", "要らんもの消して", origin={"kind": "human"}), reply("2026-01-01T00:29:00Z")]
                notes.append(u("2026-01-01T00:30:05Z", f"<system-reminder>\nThe session \"x\" you started ({local}) {WAIT_NOTE}. It reported\n</system-reminder>"))
                if k == "answered":
                    rows.append(u("2026-01-01T00:40:00Z", "はい、消した", origin={"kind": "human"}))
                else:
                    rows.append(peer("2026-01-01T00:40:00Z", "消さなくてよい"))
            if k != "nowrap":
                rows += wrap
            rows.append(stop("2026-01-01T01:10:00Z"))
            transcript(cli, rows)
        transcript(parent_c, notes)

        r = check_child(ids("answered")[0])
        ok("waited on the person, the person answered in the child's window, wrapped → ok", r["ok"])
        r = check_child(ids("overridden")[0])
        ok("waited on the person, only another session answered (reminder first) → kept with the ask", (not r["ok"])
           and r["open_ask"] and any("本人待ち" in x for x in r["reasons"]))
        ok("the ask is dated at the child's last reply before the note", r["open_ask"]["at"] == "2026-01-01T00:29:00Z")
        r = check_child(ids("busy")[0])
        ok("busy child → kept", (not r["ok"]) and any("動いている" in x for x in r["reasons"]))
        r = check_child(ids("nowrap")[0])
        ok("no wrap run → kept", (not r["ok"]) and r["reasons"] == ["wrap の記録が無い"])
        ok("--no-wrap-needed drops that reason", check_child(ids("nowrap")[0], need_wrap=False)["ok"])
        ok("--since after the wrap run → the reason says --since is too late",
           any("--since が wrap の依頼より後" in x for x in check_child(ids("answered")[0], wrap_since="2026-01-01T02:00:00")["reasons"]))
        ok("after --wait, a wrap from an earlier request does not count",
           not check_child(ids("busy")[0], wrap_since="2026-01-01T02:00:00")["ok"]
           and any(x.startswith("wrap の記録が無い") for x in check_child(ids("busy")[0], wrap_since="2026-01-01T02:00:00")["reasons"]))
        talk = [u("2026-01-01T00:00:00Z", "依頼", origin={"kind": "human"}), peer("2026-01-01T01:00:00Z", "wrap して終えて", parent_l),
                {"type": "attachment", "timestamp": "2026-01-01T01:02:00Z", "attachment": {
                    "type": "queued_command", "origin": {"kind": "human"}, "prompt": "どうやって消すの？"}},
                {"type": "assistant", "timestamp": "2026-01-01T01:05:00Z",
                 "message": {"content": [{"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}},
                stop("2026-01-01T01:10:00Z")]
        transcript(ids("nowrap")[1], talk)
        r = check_child(ids("nowrap")[0])
        ok("the person spoke in the child's window after the parent's wrap request → kept", (not r["ok"])
           and any("話している途中" in x and "どうやって" in x for x in r["reasons"]))
        ok("... and the child's answer (turn end, no question) is shown", any("答えて turn を終え" in x for x in r["reasons"]))
        ANSWERED_GRACE_MIN = 30
        ok("with a grace (the owner's call), an answered prompt long ago no longer keeps the child", check_child(ids("nowrap")[0])["ok"])
        ANSWERED_GRACE_MIN = None
        transcript(ids("nowrap")[1], talk[:2] + talk[3:])
        ok("no word of the person after the parent's request → ok", check_child(ids("nowrap")[0])["ok"])
        retry = talk[:2] + [api_err("2026-01-01T01:01:00Z"),
                            u("2026-01-01T01:02:00Z", "<system-reminder>\nLinked sessions now ...\n</system-reminder>\n\nTry again"),
                            reply("2026-01-01T01:04:00Z")] + talk[3:]
        transcript(ids("nowrap")[1], retry)
        ok("the app's 'Try again' after an API error is not the person talking", check_child(ids("nowrap")[0])["ok"])
        transcript(ids("nowrap")[1], talk[:2] + [u("2026-01-01T01:02:00Z", "Try again", origin={"kind": "human"})] + talk[3:])
        ok("'Try again' typed with no API error before it still counts", not check_child(ids("nowrap")[0])["ok"])
        transcript(ids("nowrap")[1], [u("2026-01-01T00:00:00Z", "依頼", origin={"kind": "human"}), stop("2026-01-01T01:10:00Z")])
        r = check_child(ids("overridden")[0], as_of="2026-01-01T00:25:00")
        ok("--as-of before the wait → no open ask yet", r["open_ask"] is None)
        transcript(ids("answered")[1], [reply("2026-01-01T00:10:00Z", ask="デスクトップはこのまま?"), stop("2026-01-01T00:10:01Z")])
        r = check_child(ids("answered")[0], need_wrap=False)
        ok("a wrap_up ask with no later prompt of the person → open ask with its text", r["open_ask"] and "デスクトップ" in r["open_ask"]["ask"])
        repo = os.path.join(td, "repos", "r")
        os.makedirs(repo)
        os.environ["CHILD_WRAP_REPOS_GLOB"] = os.path.join(td, "repos", "*", ".git")
        for cmd in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
                    "--allow-empty", "-m", f"x\n\nAgent-Session: claude:{ids('nowrap')[1]}"]):
            subprocess.run(["git", "-C", repo, *cmd], check=True, capture_output=True)
        r = check_child(ids("nowrap")[0], need_wrap=False)
        ok("the child's commit found by its trailer, not pushed → kept", len(r["commits"]) == 1
           and any("push されていない" in x for x in r["reasons"]))
        os.environ["CHILD_WRAP_REPOS_GLOB"] = os.path.join(td, "none", "*", ".git")
        ok("missing child → not found", not check_child("local_99999999-0000-4000-8000-000000000000")["found"])
        hook = {"tool_name": "SendMessage", "session_id": parent_c,
                "tool_input": {"to": ids("answered")[0], "message": "wrap skill で仕上げて"}}
        ok("hook: wrap request to own child → nudge with --wait and the id", ids("answered")[0] in hook_sendmessage(hook, "R")
           and "--wait" in hook_sendmessage(hook, "R"))
        hook["tool_input"] = {"to": ids("answered")[0], "message": "終わったので wrapして"}
        ok("hook: 'wrap' followed by kana still counts", "--wait" in hook_sendmessage(hook, ""))
        hook["tool_input"] = {"to": ids("answered")[0], "message": "進み具合は? unwrapped な値も見て"}
        ok("hook: other message (and 'unwrapped') → silent", hook_sendmessage(hook, "") == "")
        record(ids("nowrap")[0], ids("nowrap")[1], "local_77777777-0000-4000-8000-000000000000")
        hook["tool_input"] = {"to": ids("nowrap")[0], "message": "wrap して"}
        ok("hook: someone else's child → silent", hook_sendmessage(hook, "") == "")
        done, _ = turn_done_after(ids("overridden")[0], since=_epoch("2026-01-01T01:00:00"))
        ok("--wait: idle with a turn end after since → done", done)
        done, why = turn_done_after(ids("overridden")[0], since=_epoch("2026-01-01T02:00:00"))
        ok("--wait: idle, last turn end before since → not started yet", not done and why == "まだ始まっていない")
        done, why = turn_done_after(ids("busy")[0], since=0)
        ok("--wait: busy → not done", not done and why == "動いている")
        rc_w, first = wait([ids("busy")[0], ids("overridden")[0]], _epoch("2026-01-01T01:00:00"), 0.001, 0)
        ok("--wait: one child done, another still busy → ends with the done one", rc_w == 0 and first == [ids("overridden")[0]])

        # ---- board side: a fresh parent with its own children (B-cases) ----
        board = os.path.join(td, "board")
        os.environ.update(CHILD_WRAP_INSTANCE="claude@testhost", CHILD_FINISHED_STATE_DIR=os.path.join(td, "state"))
        bp_l, bp_c = "local_b0000000-0000-4000-8000-000000000000", "b0000000-aaaa-4000-8000-000000000000"
        record(bp_l, bp_c)
        seq = [0]

        def event(kind: str, rid: str, at: str, task: str = "", sid: str = "", inst: str = "claude@testhost", **kw) -> None:
            seq[0] += 1
            d = os.path.join(board, "events", "proj", "t-" + rid)
            os.makedirs(d, exist_ok=True)
            eid = f"{_compact(at)}-claude-{seq[0]:06x}"
            with open(os.path.join(d, f"{_compact(at)}--{eid}.json"), "w", encoding="utf-8") as fh:
                json.dump({"event_id": eid, "thread_id": "t-" + rid, "kind": kind, "created_at": at + "Z", "request_id": rid,
                           "actor": {"agent": "claude", "task": task, "instance": inst, "session_id": sid}} | kw, fh)

        def kid(n: str, rows_: list[dict], status: str = "idle", **extra) -> tuple[str, str]:
            local, cli = f"local_{n}-0000-4000-8000-000000000000", f"{n}-cccc-4000-8000-000000000000"
            record(local, cli, bp_l, **extra)
            live(int(n[:6], 16) % 100000 + 100, cli, local, status)
            transcript(cli, rows_)
            return local, cli

        base = [u("2026-01-02T00:00:00Z", "依頼", origin={"kind": "human"}), reply("2026-01-02T01:00:00Z"), stop("2026-01-02T01:00:01Z")]
        R = {k: f"20260102T000000Z-claude-{i:06x}" for i, k in enumerate(["due", "open", "reuse", "owner", "retry", "said", "far", "wrapd"])}
        cases = {}
        for k, n in [("due", "c1000001"), ("open", "c1000002"), ("reuse", "c1000003"), ("owner", "c1000004"),
                     ("retry", "c1000005"), ("said", "c1000006"), ("far", "c1000007"), ("wrapd", "c1000008")]:
            role = f"role-proj-{k}"
            event("request", R[k], "2026-01-02T00:00:00", task="parent", sid=bp_c, assignee={"agent": "claude", "session_id": role})
            event("claim", R[k], "2026-01-02T00:01:00", task=f"{n} (opus)", sid=role,
                  inst="claude@otherhost" if k == "far" else "claude@testhost")
            event("submit", R[k], "2026-01-02T00:50:00", task=f"{n} (opus)", sid=role,
                  inst="claude@otherhost" if k == "far" else "claude@testhost")
            if k != "open":
                event("accept", R[k], "2026-01-02T01:10:00", task="b0000000 (opus)", sid="role-proj-owner-review")
            rows_ = list(base)
            if k == "owner":
                rows_ = base[:1] + [reply("2026-01-02T01:00:00Z", ask="送ってよいですか?"), stop("2026-01-02T01:00:01Z")]
            if k in ("retry", "said"):
                rows_ = base[:1] + [peer("2026-01-02T00:30:00Z", "続けて", bp_l)]
                if k == "retry":
                    rows_ += [api_err("2026-01-02T00:40:00Z"), u("2026-01-02T00:41:00Z", "Try again")]
                else:
                    rows_ += [u("2026-01-02T00:41:00Z", "全部当てて", origin={"kind": "human"})]
                rows_ += [reply("2026-01-02T01:00:00Z"), stop("2026-01-02T01:00:01Z")]
            if k == "wrapd":
                rows_ = base + [{"type": "assistant", "timestamp": "2026-01-02T01:20:00Z", "message": {"content": [
                    {"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}}, stop("2026-01-02T01:30:00Z")]
            cases[k] = kid(n, rows_)
        event("request", "20260102T020000Z-claude-0000ff", "2026-01-02T02:00:00", task="parent", sid=bp_c,
              assignee={"agent": "claude", "session_id": "role-proj-reuse"})  # the next request to the same role = reuse
        rl, rc_ = kid("c100000a", base + [reply("2026-01-02T01:20:01Z"), stop("2026-01-02T01:20:03Z"),
                                          peer("2026-01-02T01:20:04Z", "wrap して", bp_l)])
        event("claim", "20260102T000000Z-claude-0000dd", "2026-01-02T00:01:00", task="c100000a (opus)", sid="role-proj-race")
        event("accept", "20260102T000000Z-claude-0000dd", "2026-01-02T01:10:00", task="x", sid="x")
        transcript(bp_c, [{"type": "assistant", "timestamp": "2026-01-02T01:20:00Z", "message": {"content": [
            {"type": "tool_use", "id": "m", "name": "SendMessage", "input": {"to": rl, "message": "wrap して"}}]}}])
        dl, dc = kid("c1000009", list(base), lineageDetached=True)
        event("claim", "20260102T000000Z-claude-0000ee", "2026-01-02T00:01:00", task="c1000009 (opus)", sid="role-proj-chore")
        event("accept", "20260102T000000Z-claude-0000ee", "2026-01-02T01:10:00", task="x", sid="x")
        rows = {r["local"]: r for r in finished(bp_l, [board])}
        st = {k: rows.get(v[0], {}).get("state") for k, v in cases.items()}
        ok("finished: all accepted, idle, no wrap asked → due", st["due"] == "due")
        ok("finished: a claimed request not accepted → open", st["open"] == "open")
        ok("finished: a new request posted to the child's role (reuse) → open", st["reuse"] == "open")
        ok("finished: the child asked the person and no answer → owner", st["owner"] == "owner")
        ok("finished: only the app's 'Try again' after the parent's message → due", st["retry"] == "due")
        ok("finished: the person spoke and the child answered → answered (kept, owner's call)", st["said"] == "answered")
        ok("finished: claimed on another machine → no-board", st["far"] == "no-board")
        ok("finished: wrap ran after the accept and the child stopped → wrapped", st["wrapd"] == "wrapped")
        ok("finished: a detached child (chore conductor) is not counted", dl not in rows)
        ok("finished: the child's previous turn ended just after the parent's wrap request → wrapping, not wrapped",
           rows.get(rl, {}).get("state") == "wrapping")
        ok("finished --as-of before the accept → open", {r["local"]: r["state"] for r in finished(
            bp_l, [board], as_of="2026-01-02T01:05:00")}.get(cases["due"][0]) == "open")
        stop_in = {"hook_event_name": "Stop", "session_id": bp_c}
        out = hook_stop(stop_in, [board], "R", "block")
        d = json.loads(out) if out else {}
        why = d.get("reason", "")
        fold_part = why.split("話している間")[0]
        ok("hook-stop: due + wrapped children → block naming them in the 'fold' part, not the owner-waiting one",
           d.get("decision") == "block" and cases["due"][0] in fold_part and cases["wrapd"][0] in fold_part
           and cases["retry"][0] in fold_part and cases["owner"][0] not in fold_part)
        ok("hook-stop: the owner-waiting child → 'keep, tell the person, start --wait-due'",
           why.index(cases["owner"][0]) > why.index("本人を待っている子") and "--wait-due " + cases["owner"][0] in why)
        ok("hook-stop: open / other-machine children are not named",
           all(cases[k][0] not in why for k in ("open", "reuse", "far")))
        ok("hook-stop: the answered child (idle > 30 min) is raised as 'ask the person', not as 'fold'",
           cases["said"][0] in d.get("reason", "") and "本人に 1 行で聞く" in d.get("reason", "")
           and d["reason"].index(cases["said"][0]) > d["reason"].index("話している間"))
        ok("hook-stop: a child still wrapping is not named", rl not in d.get("reason", ""))
        ok("hook-stop: the second Stop for the same children → silent", hook_stop(stop_in, [board], "R", "block") == "")
        os.remove(_state_file(bp_l))
        ok("hook-stop: observe mode → silent (and logged)", hook_stop(stop_in, [board], "R", "observe") == ""
           and os.path.exists(os.path.join(td, "state", "observe.jsonl")))
        ok("hook-stop: off → silent", hook_stop(stop_in, [board], "R", "off") == "")
        acc = {"tool_name": "Bash", "session_id": bp_c, "tool_input": {"command":
               f"python3 ~/Claude/ai-collaboration/board/board.py accept --root /x --request {R['due']} --reply-to y"}}
        ok("hook-accept: accepting own child's request → the rule-10 line with --wait", "--wait " + cases["due"][0] in hook_accept(acc, [board], "R"))
        acc["tool_input"]["command"] = f"python3 board.py accept --request {R['owner']}"
        RAW_ROOTS[:] = [board]
        line = hook_accept(acc, [board], "")
        ok("hook-accept: the child waits on the person → 'keep, tell the person' + the --wait-due watch with the board root",
           "残し" in line and "--wait-due " + cases["owner"][0] in line and f"--board-root '{board}'" in line)
        ok("wait-due: a child due now → returns at once", wait_due([cases["due"][0]], [board], 0.001, 0) == 0)
        ok("wait-due: a child still waiting on the person → times out", wait_due([cases["owner"][0]], [board], 0.0001, 0) == 3)
        ok("wait-due: one child due, one waiting → ends at once (the rest re-watched)",
           wait_due([cases["owner"][0], cases["due"][0]], [board], 0.0001, 0) == 0)
        acc["tool_input"]["command"] = f"python3 board.py accept --request {R['open']}"
        ok("hook-accept: a request still open (accept failed) → silent", hook_accept(acc, [board], "") == "")
        acc["tool_input"]["command"] = f"python3 board.py note --request {R['due']}"
        ok("hook-accept: not an accept → silent", hook_accept(acc, [board], "") == "")
        acc["session_id"] = parent_c
        acc["tool_input"]["command"] = f"python3 board.py accept --request {R['due']}"
        ok("hook-accept: someone else's child → silent", hook_accept(acc, [board], "") == "")
        acc["session_id"] = bp_c
        ok("hook-accept: --extra text rides on the 'fold' line", "聞かない" in hook_accept(acc, [board], "", "畳む前に聞かない"))
        ANSWERED_GRACE_MIN = 30
        st30 = {r["local"]: r for r in finished(bp_l, [board])}
        ok("grace 30: the person spoke, the child answered long ago → due", st30[cases["said"][0]]["state"] == "due")
        early = {r["local"]: r for r in finished(bp_l, [board], as_of="2026-01-02T01:10:30")}[cases["said"][0]]
        ok("grace 30: answered 10 minutes ago → still answered", early["state"] == "answered")
        ok("grace 30: the accept line for a recent answer → --wait-due, not 'ask'",
           "--wait-due" in _accept_line(early, "") and "本人に 1 行で聞く" not in _accept_line(early, ""))
        ok("grace 30: wait-due does not settle on a recent answer", not _settled(early))
        os.remove(_state_file(bp_l))
        why30 = json.loads(hook_stop(stop_in, [board], "R", "block") or "{}").get("reason", "")
        ok("grace 30: the long-answered child is in the 'fold' part, no 'ask' part",
           cases["said"][0] in why30.split("本人を待っている子")[0] and "本人に 1 行で聞く" not in why30)
        ANSWERED_GRACE_MIN = None
        for v, want in (("none", None), ("", 30.0), ("45", 45.0), ("x", 30.0)):
            os.environ["CHILD_WRAP_ANSWERED_GRACE_MIN"] = v
            ok(f"env grace {v!r} → {want}", _grace_from_env() == want)
        os.environ.pop("CHILD_WRAP_ANSWERED_GRACE_MIN", None)
        for k in ("CLAUDE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR", "CLAUDE_DESKTOP_SESSIONS_DIR", "CHILD_WRAP_REPOS_GLOB",
                  "CHILD_WRAP_INSTANCE", "CHILD_FINISHED_STATE_DIR"):
            os.environ.pop(k, None)
    ANSWERED_GRACE_MIN = saved_grace
    print("selftest:", "PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
