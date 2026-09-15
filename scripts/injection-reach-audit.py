#!/usr/bin/env python3
"""injection-reach-audit.py — hook の注入 (SessionStart 等) に指定の語が何 session 出たか、 その session の assistant と user がそれに触れたかを transcript から数える（配達と伝達を別々に数える RCA 用。 docs/convention-design-principles.md#surface-reader-is-not-the-owner、 --selftest）

「毎 session 表示されていたのに誰も触れなかった」 型の調査で、 手で transcript を grep すると
配達 (注入に出た) と伝達 (返答に書いた) を混ぜて数えやすい。 本 script は session ごとに次を出す:

- 注入に出た行 (最初の 1 行。 行頭の印 = 🔴 / ⚠️ などで、 どの段に居たかが分かる)
- assistant が文中でその語に最初に触れた時刻と、 それが **session の最初の返答**だったか
- user が文中でその語に触れた時刻 (= 人が気付いた時点の目安)

使い方:
    python3 injection-reach-audit.py --pattern '<注入の行に出る語>' [--mention '<返答で探す語>']
        [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--events SessionStart,UserPromptSubmit]
        [--projects-dir ~/.claude/projects] [--json]
    python3 injection-reach-audit.py --selftest

限界:
- 数えるのは transcript に残った注入で、 model が読んだことの証明ではない。 transcript はこのマシンの分だけ
- `--mention` の既定は `--pattern` と同じ。 識別子 (id) で注入を探し、 返答は人が読む語 (件名の一部) で探す、 のように分けると伝達を数え落とさない
- 時刻の範囲は transcript file の更新時刻で粗く絞ったあと、 各行の timestamp で判定する
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from transcript_turns import load_entries  # noqa: E402


def _text_blocks(e: dict) -> list[str]:
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return [c]
    if not isinstance(c, list):
        return []
    return [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]


def _injection_text(e: dict, events: set[str]) -> str | None:
    if e.get("type") != "attachment":
        return None
    a = e.get("attachment")
    if not isinstance(a, dict) or a.get("hookEvent") not in events:
        return None
    for key in ("content", "stdout"):
        v = a.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def audit_session(entries: list[dict], pattern: re.Pattern, mention: re.Pattern, events: set[str]) -> dict | None:
    """1 transcript の結果 (注入に出ていなければ None)。 純関数。"""
    injected = None
    first_ts = None
    first_reply_seen = False
    first_reply_mentions = False
    assistant_ts = user_ts = None
    for e in entries:
        ts = e.get("timestamp")
        if first_ts is None and ts:
            first_ts = ts
        inj = _injection_text(e, events)
        if inj is not None and injected is None:
            for line in inj.splitlines():
                if pattern.search(line):
                    injected = line.strip()
                    break
        if e.get("type") == "assistant":
            texts = [t for t in _text_blocks(e) if t.strip()]
            if texts and not first_reply_seen:
                first_reply_seen = True
                first_reply_mentions = any(mention.search(t) for t in texts)
            if assistant_ts is None and any(mention.search(t) for t in texts):
                assistant_ts = ts
        elif e.get("type") == "user" and user_ts is None:
            if any(mention.search(t) for t in _text_blocks(e) if "<system-reminder>" not in t):
                user_ts = ts
    if injected is None:
        return None
    return {"start": first_ts, "injected": injected, "assistant_first_mention": assistant_ts,
            "mentioned_in_first_reply": first_reply_mentions, "user_first_mention": user_ts}


def _in_range(ts: str | None, since: str | None, until: str | None) -> bool:
    if not ts:
        return False
    day = ts[:10]
    return (since is None or day >= since) and (until is None or day <= until)


def run(projects_dir: Path, pattern: str, mention: str | None, since: str | None, until: str | None,
        events: set[str]) -> list[dict]:
    pat = re.compile(pattern)
    men = re.compile(mention) if mention else pat
    floor = datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp() if since else 0
    rows = []
    for f in sorted(projects_dir.glob("*/*.jsonl")):
        try:
            if os.path.getmtime(f) < floor:
                continue
        except OSError:
            continue
        r = audit_session(load_entries(f), pat, men, events)
        if r is None or not _in_range(r["start"], since, until):
            continue
        r["session"] = f.stem[:8]
        r["project"] = f.parent.name
        rows.append(r)
    rows.sort(key=lambda r: r["start"] or "")
    return rows


def render(rows: list[dict]) -> str:
    out = []
    for r in rows:
        mark = (r["injected"].split() or ["?"])[0]
        am = r["assistant_first_mention"] or "-"
        out.append(f"{(r['start'] or '')[:16]}  {r['session']}  段={mark:<4} "
                   f"assistant={am[:16]:<16} 最初の返答={'yes' if r['mentioned_in_first_reply'] else 'no ':<3} "
                   f"user={(r['user_first_mention'] or '-')[:16]}  | {r['injected'][:90]}")
    marks = collections.Counter((r["injected"].split() or ["?"])[0] for r in rows)
    out.append("")
    out.append(f"配達 (注入に出た session) = {len(rows)}  段の内訳 = {dict(marks)}")
    out.append(f"伝達 (assistant が触れた) = {sum(1 for r in rows if r['assistant_first_mention'])}"
               f"  うち最初の返答 = {sum(1 for r in rows if r['mentioned_in_first_reply'])}"
               f"  / user が触れた = {sum(1 for r in rows if r['user_first_mention'])}")
    return "\n".join(out)


def _selftest() -> int:
    ok = ng = 0

    def check(cond, name):
        nonlocal ok, ng
        if cond:
            ok += 1
            print(f"  PASS: {name}")
        else:
            ng += 1
            print(f"  FAIL: {name}")

    def att(ts, event, content):
        return {"type": "attachment", "timestamp": ts,
                "attachment": {"type": "hook_success", "hookEvent": event, "content": content}}

    def asst(ts, text):
        return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}}

    def user(ts, text):
        return {"type": "user", "timestamp": ts, "message": {"content": text}}

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "proj"
        d.mkdir()
        sessions = {
            "aaaaaaaa-1": [att("2030-01-02T01:00:00Z", "SessionStart", "⏰ horizon\n   🔴◆ -3d  todo-x [対応中]"),
                           user("2030-01-02T01:00:05Z", "作業して"), asst("2030-01-02T01:01:00Z", "作業します"),
                           asst("2030-01-02T01:05:00Z", "ついでに todo-x の件ですが"),
                           user("2030-01-02T01:06:00Z", "todo-x どうなってる？")],
            "bbbbbbbb-2": [att("2030-01-03T01:00:00Z", "SessionStart", "   ⚠️ todo-x [対応中]"),
                           asst("2030-01-03T01:01:00Z", "todo-x を先に伝えます")],
            "cccccccc-3": [att("2030-01-04T01:00:00Z", "SessionStart", "何も無し"), asst("2030-01-04T01:01:00Z", "todo-x")],
            "dddddddd-4": [att("2030-01-05T01:00:00Z", "UserPromptSubmit", "🔴 todo-x"), asst("2030-01-05T01:01:00Z", "x")],
            "eeeeeeee-5": [att("2029-12-01T01:00:00Z", "SessionStart", "🔴 todo-x")],
        }
        for sid, es in sessions.items():
            p = d / f"{sid}.jsonl"
            p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in es) + "\n{broken", encoding="utf-8")
            t = datetime.fromisoformat(es[-1]["timestamp"].replace("Z", "+00:00")).timestamp()
            os.utime(p, (t, t))  # 更新時刻での粗い絞り込みを実データと同じ条件にする
        rows = run(Path(td), r"todo-x", None, "2030-01-01", None, {"SessionStart"})
        by = {r["session"]: r for r in rows}
        check(set(by) == {"aaaaaaaa", "bbbbbbbb"}, "SessionStart に出た session だけ・範囲外と別 event と未出現は数えない")
        check(by["aaaaaaaa"]["injected"].startswith("🔴◆") and by["aaaaaaaa"]["assistant_first_mention"] == "2030-01-02T01:05:00Z",
              "注入の行 (段の印つき) と assistant の最初の言及時刻")
        check(by["aaaaaaaa"]["mentioned_in_first_reply"] is False and by["bbbbbbbb"]["mentioned_in_first_reply"] is True,
              "最初の返答で触れたかを分けて数える")
        check(by["aaaaaaaa"]["user_first_mention"] == "2030-01-02T01:06:00Z", "user が触れた時刻")
        rows2 = run(Path(td), r"todo-x", None, None, None, {"SessionStart", "UserPromptSubmit"})
        check(len(rows2) == 4, "--events で UserPromptSubmit の注入も数え、 --since 無しは全期間")
        rows3 = run(Path(td), r"todo-x", r"どうなって", "2030-01-01", None, {"SessionStart"})
        check({r["session"]: r["assistant_first_mention"] for r in rows3} == {"aaaaaaaa": None, "bbbbbbbb": None},
              "--mention を分けると返答はその語で探す")
        check("配達 (注入に出た session) = 2" in render(rows), "要約行に配達と伝達を分けて出す")
    print(f"\n==== RESULT: PASS={ok} FAIL={ng} ====")
    return 1 if ng else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pattern")
    ap.add_argument("--mention")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--events", default="SessionStart")
    ap.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not a.pattern:
        ap.error("--pattern が要る")
    rows = run(Path(a.projects_dir).expanduser(), a.pattern, a.mention, a.since, a.until,
               {x.strip() for x in a.events.split(",") if x.strip()})
    print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
