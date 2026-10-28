#!/usr/bin/env python3
"""child-wrap-check.py — 起こした子の session を畳んで (archive して) よいかを照合する。 `--wait` は子の turn が終わるまで待ってから照合する (desktop app の親 session 用、 読むだけ)。

Why (実測、 正本 = conventions/multi-session-coordination.md#tidy-after-child-turn-ends):
  - 止めて待つ向き: desktop app は、 子の turn の終わりの知らせで親を起こすのを「親が起こした子が 1 つも動いていない時」 に
    限る。 ほかの子 (長い仕事の worker) が動いていると、 知らせは親の次の turn まで待たされる = 多くは本人の次の発言に
    同梱されて届き、 親は子が終わったのを知らないまま止まっている。 一方、 親が自分の Bash を run_in_background で回すと、
    その終わりは (ほかの子が動いていても) 親の新しい turn を始める。 `--wait` はその見張り。
  - 早すぎる向き: 子が本人に頼んだ・問うたまま止まったのに、 親が代わりに答えて (別 session の message で上書きして) 子を
    閉じる。 子の最後の報告は「残りは無い」 に変わるので、 最後の知らせだけを見ると「終えた」 に見える。

照合 (子ごと):
  - 動き: live の registry の status (busy = まだ動いている)
  - wrap: 子の記録の wrap skill の起動 (Skill tool の skill=wrap か、 skill の本文の差し込み)
  - commit: 子の commit (全 repo の commit に入る `Agent-Session: claude:<子の transcript id>` の trailer で引く) が、
    その repo の remote-tracking branch に入っているか (push 済みか)
  - 本人待ちの問い: 子の turn が本人待ちで終わった最後の時点 (子の wrap_up の ask / blocked、 親の記録の
    「… finished a turn and then reported that it was waiting on the user」 の知らせより前の子の最後の応答) より後に、
    子の窓に本人の発言 (人の入力。 別 session の message・hook の差し戻し・task の通知は数えない) があるか
  - 本人と話している途中: 親が子へ最後に送った message (wrap の依頼など) より後に、 本人が子の窓で発言しているか
    (実測: 親が「片付けは不要、 wrap して終えて」 と送った直後に、 本人が同じ子に「どうやって消すの？」 と打ち、
    子が答えた 2 分後に親が畳んだ)
判定: 動いていない・wrap の記録がある・push されていない commit が無い・本人待ちの問いも話の途中も無い = 畳んでよい。
見ないもの: 掲示板の依頼が受理されたか (受理は親自身の操作)、 子が commit しなかった変更 (同じ作業木を共有すると帰属できない)、
  trailer の hook が入っていない repo の commit。

Usage:
  child-wrap-check.py <local_…|transcript id> [...]     照合して出す (exit 0 = 全部畳んでよい / 1 = 残すものがある / 2 = 子が見つからない)
  child-wrap-check.py --wait <local_…> [...] [--since <epoch 秒>] [--max-minutes N]
        子の turn が --since (既定 = 今の 60 秒前) より後に終わって動いていない状態になるまで待ち、 照合を出す
        (親が Bash の run_in_background で回す = 終わると親が起こされる。 時間切れ = exit 3)
  child-wrap-check.py <id> --as-of 2026-01-01T00:00:00 照合をその時点までの記録で (RCA の再現。 動きと commit は今の状態)
  child-wrap-check.py --hook-sendmessage [--rule <参照>]  PostToolUse(SendMessage) の hook 用: 自分の子に wrap を頼んだ
        message なら、 同じ turn に --wait の見張りを出す 1 行を additionalContext で返す (それ以外は何も出さない)
  --no-wrap-needed (wrap の記録を判定に入れない) / --json / --selftest
env (test): CLAUDE_SESSIONS_DIR / CLAUDE_PROJECTS_DIR / CLAUDE_DESKTOP_SESSIONS_DIR / CHILD_WRAP_REPOS_GLOB
"""
from __future__ import annotations

import argparse
import calendar
import glob
import importlib.util as _ilu
import json
import os
import re
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


def _ts(e: dict) -> str:
    return str(e.get("timestamp") or "")


def _epoch(ts: str) -> float:
    return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))


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
    """Events from the child's transcript (timestamps): first entry, replies, turn ends, prompts of the person, asks, wrap runs."""
    out = {"first": "", "replies": [], "stops": [], "human": [], "said": [], "peers": [], "asks": [], "wraps": []}
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
            if kind == "system" and e.get("subtype") == "stop_hook_summary":
                out["stops"].append(ts)
                continue
            said = _bw._human_text(e)
            if said:
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


def owner_after_parent(ev: dict, parent: str) -> dict | None:
    """The person's latest prompt in the child's window, if it came after the parent's latest message to the child."""
    sent = [ts for ts, frm in ev["peers"] if frm == parent]
    if not parent or not sent or not ev["said"]:
        return None
    at, said = max(ev["said"], key=lambda p: p[0])
    return {"at": at, "said": said, "parent_at": max(sent)} if at > max(sent) else None


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
        out.append(f"本人待ちの問いが残っている ({_local_hm(ask['at'])} に本人待ちで止まり、 その後この子の窓に本人の発言が無い)"
                   + (f": {ask['ask'][:160]}" if ask["ask"] else ""))
    talking = owner_after_parent(ev, c["parent"])
    if talking:
        out.append(f"本人がこの子と話している途中 (親の最後の指示 {_local_hm(talking['parent_at'])} の後、"
                   f" {_local_hm(talking['at'])} に本人がこの子の窓で発言): {talking['said'][:120]}")
    return out


def check_child(target: str, as_of: str = "", need_wrap: bool = True) -> dict:
    c = locate(target)
    if not c:
        return {"target": target, "found": False, "ok": False, "reasons": ["子が見つからない (app の記録にも live の registry にも無い)"]}
    ev = scan_child(c["path"], as_of)
    ask = open_ask(ev, parent_wait_notes(c["parent_path"], c["local"], as_of))
    commits = child_commits(c["cli"], ev["first"][:19])
    reasons = []
    if not as_of and c["status"] == "busy":
        reasons.append("まだ動いている (turn の途中)")
    if ask:
        reasons.append(f"本人待ちの問いが残っている ({_local_hm(ask['at'])} に本人待ちで止まり、 その後この子の窓に本人の発言が無い)"
                       + (f": {ask['ask'][:160]}" if ask["ask"] else ""))
    talking = owner_after_parent(ev, c["parent"])
    if talking:
        reasons.append(f"本人がこの子と話している途中 (親の最後の指示 {_local_hm(talking['parent_at'])} の後、"
                       f" {_local_hm(talking['at'])} に本人がこの子の窓で発言): {talking['said'][:120]}")
    if need_wrap and not ev["wraps"]:
        reasons.append("wrap の記録が無い")
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


def wait(targets: list[str], since: float, max_minutes: float, interval: float = 20.0) -> int:
    deadline = time.time() + max_minutes * 60
    while True:
        states = {t: turn_done_after(t, since) for t in targets}
        if all(done for done, _ in states.values()):
            return 0
        if time.time() > deadline:
            print("⌛ 待ち切れなかった: " + ", ".join(f"{t} ({why})" for t, (done, why) in states.items() if not done))
            return 3
        time.sleep(interval)


def hook_sendmessage(inp: dict, rule: str) -> str:
    """additionalContext for a SendMessage that asks one's own child to wrap; '' otherwise."""
    if inp.get("tool_name") != "SendMessage":
        return ""
    ti = inp.get("tool_input") or {}
    to, msg = str(ti.get("to") or ""), str(ti.get("message") or "")
    if not to.startswith("local_") or not re.search(r"\bwrap\b", msg, re.I):
        return ""
    me, child = ds.find(str(inp.get("session_id") or "")), ds.find(to)
    if not me or not child or child.get("parent") != me.get("local_id"):
        return ""
    try:
        ps = subprocess.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        ps = ""
    if any("child-wrap-check.py" in ln and "--wait" in ln and to in ln for ln in ps.splitlines()):
        return ""
    since = int(time.time()) - 30
    return ("🧺 child-wrap-check: 子 (" + (child.get("title") or to) + ") に wrap を頼んだ。 ほかの子が動いている間は、 子の turn の終わりで"
            " app はこの session を起こさない (知らせは本人の次の発言まで待たされる、 実測)。 この turn のうちに Bash を"
            f" run_in_background で `python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait {to} --since {since}`"
            " を出す (同じ turn で複数の子に頼んだら id を並べた 1 本)。 子の turn が終わるとこの session が起こされ、 畳んでよいかの照合が出る。"
            + (f" 規則 = {rule}" if rule else ""))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="起こした子の session を畳んでよいかを照合する")
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--since", type=float)
    ap.add_argument("--max-minutes", type=float, default=180)
    ap.add_argument("--as-of", default="")
    ap.add_argument("--no-wrap-needed", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hook-sendmessage", action="store_true")
    ap.add_argument("--rule", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.hook_sendmessage:
        try:
            ctx = hook_sendmessage(json.loads(sys.stdin.read() or "{}"), a.rule)
        except Exception:
            return 0  # fail-open
        if ctx:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}, ensure_ascii=False))
        return 0
    if not a.targets:
        ap.error("子の local_… か transcript id を 1 つ以上")
    if a.wait:
        rc = wait(a.targets, a.since if a.since is not None else time.time() - 60, a.max_minutes)
        if rc:
            return rc
        print(f"🧺 子 {len(a.targets)} 件の turn が終わった ({time.strftime('%H:%M')})。 照合:")
    rows = [check_child(t, a.as_of, not a.no_wrap_needed) for t in a.targets]
    print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else render(rows))
    if any(not r["found"] for r in rows):
        return 2
    return 0 if all(r["ok"] for r in rows) else 1


def selftest() -> int:
    import tempfile

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

        def record(local: str, cli: str, parent: str = "") -> None:
            with open(os.path.join(ddir, "acct", "env", local + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"sessionId": local, "cliSessionId": cli, "title": local[:14], "isArchived": False,
                           "spawnedFrom": {"sessionId": parent} if parent else {}, "lastTurnEdgeAt": 1000}, fh)

        def transcript(cli: str, rows: list[dict]) -> None:
            with open(os.path.join(pdir, "-w", cli + ".jsonl"), "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

        record(parent_l, parent_c)
        notes = []
        for n, k in enumerate(kids):
            local, cli = ids(k)
            record(local, cli, parent_l)
            with open(os.path.join(sdir, f"{n}.json"), "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "sessionId": cli, "hostSessionId": local, "cwd": "/w",
                           "status": "busy" if k == "busy" else "idle"}, fh)
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
        transcript(ids("nowrap")[1], talk[:2] + talk[3:])
        ok("no word of the person after the parent's request → ok", check_child(ids("nowrap")[0])["ok"])
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
        hook["tool_input"] = {"to": ids("answered")[0], "message": "進み具合は?"}
        ok("hook: other message → silent", hook_sendmessage(hook, "") == "")
        record(ids("nowrap")[0], ids("nowrap")[1], "local_77777777-0000-4000-8000-000000000000")
        hook["tool_input"] = {"to": ids("nowrap")[0], "message": "wrap して"}
        ok("hook: someone else's child → silent", hook_sendmessage(hook, "") == "")
        done, _ = turn_done_after(ids("overridden")[0], since=_epoch("2026-01-01T01:00:00"))
        ok("--wait: idle with a turn end after since → done", done)
        done, why = turn_done_after(ids("overridden")[0], since=_epoch("2026-01-01T02:00:00"))
        ok("--wait: idle, last turn end before since → not started yet", not done and why == "まだ始まっていない")
        done, why = turn_done_after(ids("busy")[0], since=0)
        ok("--wait: busy → not done", not done and why == "動いている")
        for k in ("CLAUDE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR", "CLAUDE_DESKTOP_SESSIONS_DIR", "CHILD_WRAP_REPOS_GLOB"):
            os.environ.pop(k, None)
    print("selftest:", "PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
