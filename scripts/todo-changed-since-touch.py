#!/usr/bin/env python3
"""todo-changed-since-touch.py — TODO 台帳の項目を触る瞬間に、 その session が最後に触った後に入った別の書き手の記録と、 結ばれた thread に届いた相手の message を 1 回だけ知らせる (PreToolUse hook の engine)。

なぜ (一般形。 実測は個人層の記録):
  案件を持つ session は、 その項目の現在地を自分の文脈 (前に読んだ値・記憶) で持っている。 その間に別の session が
  相手の返事を受信の記録として書き、 項目の現在地も直す。 案件の session は同じ日に同じ項目を別件で書き換えるが、
  自分の記憶から作った現在地で丸ごと置き換え、 記録された返事を消した (同じ session で 2 回)。 一覧の印は記録した時点で
  消え、 一覧の雑用は別の session が持つので、 案件の session には返事が届く経路が無かった。 編集の道具の
  「読んだ後に file が変わった」 という注記は出ていたが、 何が変わったかは言わない。
  → 案件の session が項目に触る (読む・書く・道具に id を渡す) 瞬間に、 「最後に触った後に、 誰が何を書き、 どの相手から
    何が届いたか」 を 1 回出す。 上書きを止めるのは書く道具の読んだ印 (yaml-set-top-keys.py / record-reply.py の
    --replaces) で、 本 engine は気づく面。 止めない。

述語:
  - 触った項目: Read / Edit / Write / MultiEdit の file_path が <台帳の repo>/todo/<id>.yaml。 Bash の command に
    `todo/<id>.yaml` か、 台帳に実在する項目の id (日付で始まる id) が出てくる (record-reply.py <id> / todo-show.py <id> など)
  - 基準の時刻 = その session がその項目を最後に触った時刻 = max(その session の commit のうちその項目の file を含む最新
    〔commit の `Agent-Session:` trailer にその session の id〕, 本 engine が前に見た触った時刻 〔state〕)。
    基準が無い (= その session が初めて触る) なら知らせない (今の中身を読むところ) で、 触った時刻だけを記録する
  - 知らせる中身 (基準より後のもの): (1) その項目の file を含む別の書き手の commit (trailer が別の session / trailer なし)
    (2) 項目に結ばれた thread (経路 = lib/todo_thread_links.resolve_threads) の inbox の索引 `messages[]` の受信の行 (←)
  - 知らせたら触った時刻を今に進める = 同じ中身は 2 回出ない。 何も無ければ黙って触った時刻だけ進める
  - 全部の失敗で黙る (fail-open)。 出力 = PreToolUse の additionalContext
射程外: 基準より前に届いて基準より後に記録された message (受信の時刻で比べるため。 記録した commit が項目の file も
  書いていれば (1) が拾う) / 作業 tree の未 commit の書き換え (同じ checkout を共有するなら file を読めば見える)。

使い方:
    <PreToolUse の JSON> | python3 todo-changed-since-touch.py --repo <台帳の repo> [--repo ...] [--state-dir DIR]
    python3 todo-changed-since-touch.py --repo <repo> --replay --session <id> --todo <id> --now "YYYY-MM-DD HH:MM"
        (過去の時点で何が出たかを再生する = state を使わず、 now より後の commit と message を除く)
    python3 todo-changed-since-touch.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from todo_thread_links import harvest_todo_refs, resolve_threads, thread_ids  # noqa: E402

try:
    import yaml
    _LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
except ImportError:  # pragma: no cover
    yaml = None

ID_RE = re.compile(r"(?<![\w.-])(\d{4}-\d{2}-\d{2}-[A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.yaml)?(?![\w.-])")
MSG_RE = re.compile(r"^mid:([0-9a-f]+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s+(←|→)\s*(.*)$")
FILE_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit")
MAX_COMMITS, MAX_MSGS, HEAD_CHARS = 3, 4, 160
WINDOW_DAYS = 60   # その session の commit を探す窓 (これより前に最後に触った項目は、 state が無ければ初めて触る扱い)


def _git_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")}


def _load_yaml(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.load(f, Loader=_LOADER)


def touched_todos(ev: dict, repos: list[Path]) -> list[tuple[Path, str]]:
    """tool call → 触った (repo, 項目の id) の list (順序保持・重複なし)。"""
    tool = ev.get("tool_name") or ""
    ti = ev.get("tool_input") or {}
    out: list[tuple[Path, str]] = []
    if tool in FILE_TOOLS:
        p = Path(str(ti.get("file_path") or ti.get("notebook_path") or "")).expanduser()
        for r in repos:
            try:
                if p.suffix == ".yaml" and p.resolve().parent == (r / "todo").resolve():
                    out.append((r, p.stem))
            except OSError:
                pass
    elif tool == "Bash":
        cmd = str(ti.get("command") or "")
        for m in ID_RE.finditer(cmd):
            tid = m.group(1)
            for r in repos:
                if (r / "todo" / f"{tid}.yaml").is_file() and (r, tid) not in out:
                    out.append((r, tid))
            if len(out) >= 5:
                break
    return out


def file_commits(repo: Path, rel: str, n: int = 40, since: float | None = None) -> list[dict]:
    """その file を含む commit (新しい順): ct (commit の epoch) / sha / session (Agent-Session trailer) / subject。
    since (epoch) より後だけ歩く (履歴の長い台帳で file を含む commit が少ないと全履歴を歩く = 実測 0.3〜0.8 秒)。"""
    fmt = "%ct%x1f%h%x1f%(trailers:key=Agent-Session,valueonly,separator=%x2C)%x1f%s"
    lim = [time.strftime("--since=%Y-%m-%dT%H:%M:%S", time.localtime(since))] if since else []
    r = subprocess.run(["git", "-C", str(repo), "log", f"-n{n}", *lim, f"--format={fmt}", "--", rel],
                       capture_output=True, text=True, timeout=10, env=_git_env())
    out = []
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        parts = line.split("\x1f")
        if len(parts) == 4 and parts[0].isdigit():
            out.append({"ct": int(parts[0]), "sha": parts[1], "session": parts[2].strip(), "subject": parts[3]})
    return out


def _epoch(d: str, hm: str) -> float | None:
    try:
        return time.mktime(datetime.strptime(f"{d} {hm}", "%Y-%m-%d %H:%M").timetuple())
    except ValueError:
        return None


def linked_incoming(repo: Path, todo: dict, since: float, until: float | None = None,
                    prune_by_mtime: bool = True) -> list[dict]:
    """項目に結ばれた thread の inbox 索引から、 since より後 (until 以前) に届いた相手の message (古い順)。
    inbox の月 file のうち since より後に書かれていない file は読まない (後に届いた message はその後に記録される)。"""
    entries: dict[str, dict] = {}
    for f in sorted((repo / "inbox").glob("*.yaml")):
        try:
            if prune_by_mtime and f.stat().st_mtime < since:
                continue
            data = _load_yaml(f)
        except Exception:  # noqa: BLE001 — 読めない月 file (暗号文のまま等) は飛ばす
            continue
        for e in data if isinstance(data, list) else []:
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                entries[e["id"]] = e
    inverse: dict[str, list[str]] = {}
    for eid, e in entries.items():
        for t in harvest_todo_refs(e):
            inverse.setdefault(t, []).append(eid)
    threads = {tid for tid, _ in resolve_threads(todo, entries, inverse)}
    out, seen = [], set()
    for e in entries.values():
        if not threads.intersection(thread_ids(e.get("threadId"))):
            continue
        for line in e.get("messages") or []:
            m = MSG_RE.match(str(line).strip())
            if not m or m.group(4) != "←" or m.group(1) in seen:
                continue
            t = _epoch(m.group(2), m.group(3))
            if t is None or t <= since or (until is not None and t > until):
                continue
            seen.add(m.group(1))
            out.append({"t": t, "mid": m.group(1), "who": m.group(5).strip(), "subject": str(e.get("subject") or "")})
    return sorted(out, key=lambda x: x["t"])


def _hm(t: float) -> str:
    return time.strftime("%m/%d %H:%M", time.localtime(t))


def news(repo: Path, tid: str, session: str, touched: float | None, now: float,
         replay: bool = False) -> tuple[str | None, float | None]:
    """(知らせる文 or None, 基準の時刻 or None)。 基準が無ければ (None, None)。"""
    rel = f"todo/{tid}.yaml"
    commits = [c for c in file_commits(repo, rel, since=None if replay else now - WINDOW_DAYS * 86400) if c["ct"] <= now]
    mine = [c["ct"] for c in commits if session and session in c["session"]]
    ref = max([t for t in (max(mine) if mine else None, touched) if t is not None], default=None)
    if ref is None:
        return None, None
    foreign = [c for c in commits if c["ct"] > ref and not (session and session in c["session"])]
    try:
        todo = _load_yaml(repo / rel)
    except Exception:  # noqa: BLE001
        todo = None
    todo = todo if isinstance(todo, dict) else {"id": tid}
    msgs = linked_incoming(repo, todo, ref, until=now if replay else None, prune_by_mtime=not replay)
    if not foreign and not msgs:
        return None, ref
    lines = [f"📨 TODO {tid} ({repo.name}) は、 この session が最後に触った後 ({_hm(ref)}) に動いている。"
             f" 書く前に今の現在地を読み直す (自分の記憶の値で丸ごと置き換えない):"]
    for c in foreign[:MAX_COMMITS]:
        who = c["session"].split(",")[0].split(":")[-1][:8] if c["session"] else "trailer なし"
        lines.append(f"  ・別の書き手の commit: {_hm(c['ct'])} session {who} {c['sha']}「{c['subject']}」")
    if len(foreign) > MAX_COMMITS:
        lines.append(f"  ・ほか {len(foreign) - MAX_COMMITS} 件の commit (git log -- {rel})")
    for m in msgs[-MAX_MSGS:]:
        lines.append(f"  ・結ばれた thread に届いた相手の message: {_hm(m['t'])} {m['who']}「{m['subject']}」 (mid:{m['mid']})")
    if not replay:
        sc = str(todo.get("status_context") or "").strip().replace("\n", " ⏎ ")
        if sc:
            lines.append(f"  ・今の status_context の頭: 「{sc[:HEAD_CHARS]}{'…' if len(sc) > HEAD_CHARS else ''}」"
                         f" (status = {todo.get('status')})")
    return "\n".join(lines), ref


def quiet_since(repo: Path, tid: str, t: float) -> bool:
    """t の後に repo の HEAD (commit・pull)・項目の file・inbox の月 file のどれも書かれていない = 新しいものは無い
    (git を呼ばずに済む速い道。 HEAD の reflog が読めない repo では偽 = いつもの道)。"""
    head_log = repo / ".git" / "logs" / "HEAD"
    if not head_log.is_file():
        return False
    try:
        paths = [head_log, repo / "todo" / f"{tid}.yaml", *(repo / "inbox").glob("*.yaml")]
        return all(p.stat().st_mtime < t for p in paths if p.exists())
    except OSError:
        return False


def _state_path(state_dir: Path, session: str) -> Path:
    return state_dir / (re.sub(r"[^A-Za-z0-9_.-]", "_", session or "nosession")[:80] + ".json")


def hook_main(repos: list[Path], state_dir: Path, now: float | None = None) -> int:
    try:
        ev = json.loads(sys.stdin.read() or "{}")
        session = str(ev.get("session_id") or "")
        hits = touched_todos(ev, repos)
        if not hits or not session:
            return 0
        sp = _state_path(state_dir, session)
        try:
            state = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        now = now or time.time()
        msgs = []
        for repo, tid in hits:
            key = f"{repo}/{tid}"
            if state.get(key) and quiet_since(repo, tid, state[key]):
                state[key] = now
                continue
            text, _ = news(repo, tid, session, state.get(key), now)
            state[key] = now
            if text:
                msgs.append(text)
        state_dir.mkdir(parents=True, exist_ok=True)
        tmp = sp.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(sp)
        if msgs:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                     "additionalContext": "\n".join(msgs)}}, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — hook は止めない
        return 0
    return 0


# ---- selftest ----

def _git(repo: Path, *args: str, when: str | None = None, trailer: str | None = None) -> None:
    env = {**_git_env(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    hooks = repo / ".nohooks"
    hooks.mkdir(exist_ok=True)
    cmd = ["git", "-C", str(repo), "-c", f"core.hooksPath={hooks}", *args]
    if trailer:
        cmd += ["-m", f"Agent-Session: {trailer}"]
    subprocess.run(cmd, check=True, capture_output=True, env=env)


def selftest() -> int:
    ok = True

    def check(cond: bool, label: str) -> None:
        nonlocal ok
        print(("  ok  " if cond else "  NG  ") + label)
        ok = ok and cond

    me, other = "aaaa1111-0000-4000-8000-000000000001", "bbbb2222-0000-4000-8000-000000000002"
    tid = "2020-01-10-sample-case"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "ledger"
        (repo / "todo").mkdir(parents=True)
        (repo / "inbox").mkdir()
        st = Path(tmp) / "state"
        _git(repo, "init", "-q")
        todo_p, inbox_p = repo / "todo" / f"{tid}.yaml", repo / "inbox" / "2020-01.yaml"
        todo_p.write_text(f'id: "{tid}"\nstatus: "待ち"\nstatus_context: "2020-01-10 書類を送った → 次: 甲野さんの返事待ち"\n',
                          encoding="utf-8")
        inbox = (f'- id: "2020-01-10-sample-received"\n  subject: "書類の件"\n  threadId: "aaaaaaaaaaaaaaaa"\n'
                 f'  related_todo: ["{tid}"]\n  messages:\n    - "mid:aaaaaaaaaaaaaaaa 2020-01-10 09:00 → kono@example.invalid"\n')
        inbox_p.write_text(inbox, encoding="utf-8")
        _git(repo, "add", "-A", when="2020-01-10T10:00:00")
        _git(repo, "commit", "-q", "-m", "案件の session: 書類を送った", when="2020-01-10T10:00:00", trailer=f"claude:{me}")

        def touch(tool: str, inp: dict, at: str, sess: str = me) -> str:
            ev = {"hook_event_name": "PreToolUse", "session_id": sess, "tool_name": tool, "tool_input": inp}
            d, hm = at.split(" ")
            r = subprocess.run([sys.executable, __file__, "--repo", str(repo), "--state-dir", str(st),
                                "--now-epoch", str(_epoch(d, hm))],
                               input=json.dumps(ev), capture_output=True, text=True, timeout=30)
            return r.stdout

        check(touched_todos({"tool_name": "Bash", "tool_input": {"command": f"python3 record-reply.py {tid} --apply"}},
                            [repo]) == [(repo, tid)], "Bash の command の項目の id を拾う")
        check(touched_todos({"tool_name": "Bash", "tool_input": {"command": f"git commit -- 'todo/{tid}.yaml'"}},
                            [repo]) == [(repo, tid)], "Bash の command の todo/<id>.yaml を拾う")
        check(touched_todos({"tool_name": "Bash", "tool_input": {"command": f"ls plans/{tid}.md plans/2020-01-11-x.md"}},
                            [repo]) == [], "台帳の項目でない file 名 (同じ日付・同じ名前の .md) は拾わない")

        # 形 1: 別の session が受信の記録だけ書いた (項目の file は触らない)。 案件の session が項目を読む → 知らせる
        inbox_p.write_text(inbox + '    - "mid:bbbbbbbbbbbbbbbb 2020-01-11 09:24 ← 甲野 太郎"\n', encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "受信の記録: 甲野さんの返事", when="2020-01-11T10:25:00", trailer=f"claude:{other}")
        out = touch("Read", {"file_path": str(todo_p)}, "2020-01-11 12:00")
        check("01/11 09:24 甲野 太郎「書類の件」" in out and "別の書き手の commit" not in out and "01/10 10:00" in out,
              "形 1 (受信の記録だけ): 最後に触った時刻と、 結ばれた thread に届いた相手の message を出す")
        check(touch("Read", {"file_path": str(todo_p)}, "2020-01-11 12:05") == "", "同じ中身は 2 回出ない")

        # 形 2: 同じ日に別の session が項目の現在地も直した後、 案件の session が別件で書き換える
        todo_p.write_text(todo_p.read_text(encoding="utf-8").replace(
            "2020-01-10 書類を送った → 次: 甲野さんの返事待ち", "2020-01-12 甲野さんの返事 (必要書類 3 点) → 次: 3 点を送る"),
            encoding="utf-8")
        inbox_p.write_text(inbox_p.read_text(encoding="utf-8") + '    - "mid:cccccccccccccccc 2020-01-12 09:00 ← 甲野 太郎"\n',
                           encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "受信の記録: 甲野さんの 2 通目", when="2020-01-12T10:00:00", trailer=f"claude:{other}")
        out = touch("Bash", {"command": f"python3 yaml-set-top-keys.py todo/{tid}.yaml --set status_context=任期を反映"},
                    "2020-01-12 14:51")
        check("受信の記録: 甲野さんの 2 通目" in out and "session bbbb2222" in out and "01/12 09:00 甲野 太郎" in out
              and "必要書類 3 点" in out, "形 2 (同じ日に別件で更新): 別の書き手の commit・届いた message・今の現在地を出す")

        # 初めて触る session (commit も state も無い) には出さない
        check(touch("Read", {"file_path": str(todo_p)}, "2020-01-12 15:00", sess="cccc3333-0000-4000-8000-000000000003") == "",
              "初めて触る session には出さない (今の中身を読むところ)")
        # 自分の commit は知らせない
        todo_p.write_text(todo_p.read_text(encoding="utf-8") + 'notes: "自分の追記"\n', encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "自分", when="2020-01-13T10:00:00", trailer=f"claude:{me}")
        check(touch("Read", {"file_path": str(todo_p)}, "2020-01-13 12:00") == "", "自分の commit は知らせない")
        # 再生: 過去の時点で何が出たか (state を使わない)
        text, _ = news(repo, tid, me, None, _epoch("2020-01-12", "11:00"), replay=True)
        check(bool(text) and "甲野さんの 2 通目" in text and "01/11 09:24" in text and "「自分」" not in text,
              "再生: その時点までの commit と message を出す")
        check(hook_main_guard(), "壊れた入力でも黙って exit 0")
    print("todo-changed-since-touch selftest: " + ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


def hook_main_guard() -> bool:
    r = subprocess.run([sys.executable, __file__, "--repo", "/nonexistent"], input="not json",
                       capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and r.stdout == ""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--state-dir", default=str(Path.home() / ".claude" / "state" / "todo-changed-since-touch"))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--session")
    ap.add_argument("--todo")
    ap.add_argument("--now")
    ap.add_argument("--now-epoch", type=float, help=argparse.SUPPRESS)  # selftest が fixture の時刻で触る
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if yaml is None:
        return 0
    repos = [Path(r).expanduser() for r in a.repo]
    if a.replay:
        d, hm = (a.now or "").split(" ") if " " in (a.now or "") else (a.now, "23:59")
        now = _epoch(d, hm)
        if not (a.session and a.todo and now and repos):
            raise SystemExit("❌ --replay には --session / --todo / --now / --repo が要る")
        for repo in repos:
            if (repo / "todo" / f"{a.todo}.yaml").is_file():
                text, ref = news(repo, a.todo, a.session, None, now, replay=True)
                print(text or f"(出ない: 基準 = {_hm(ref) if ref else 'なし (その session の commit が無い)'})")
        return 0
    return hook_main(repos, Path(a.state_dir).expanduser(), a.now_epoch)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
