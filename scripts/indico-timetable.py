#!/usr/bin/env python3
"""indico-timetable.py — Indico の会議の時間割を JSON export で読み、 題か発表者の名で講演を探して、 会議の時刻と手元の時刻を並べる。

用途: 自分の講演・座長の枠・聴きたい講演の日時を、 時間割の画面を開かずに確かめる (予定表に入れる前の照合)。
規約 = conventions/indico-abstract-submission.md#timetable-json-export

使い方:
  indico-timetable.py https://indico.example.org/event/12345/        # 全講演を時刻順に
  indico-timetable.py https://indico.example.org/event/12345/ --match 'Example|題の語'   # 題・発表者・session 名を正規表現で
  indico-timetable.py --json saved.json --match '...'                 # 取得済みの JSON を読む (再取得しない)
  indico-timetable.py <URL> --save timetable.json                     # 取得した JSON を根拠として残す (sha256 を出す)
  indico-timetable.py <URL> --tz America/New_York                     # 手元の時刻の tz (既定 = この機械の tz)
  indico-timetable.py --selftest

機構 (実測):
  - export の URL = https://<host>/export/timetable/<event id>.json (公開の会議ならログイン不要)。 時間割の画面が
    ボット確認の頁で止まった回でも、 この JSON は User-Agent を付けた素の GET で取れた。
  - JSON の形 = results[<event id>][<YYYYMMDD>][<entry id>]。 session の枠 (entryType = Session) は中に entries を持ち、
    講演 (Contribution) は presenters (と speakers) に名前を持つ。 時刻は startDate / endDate の {date, time, tz} で、
    tz は会議の tz (例 Europe/Geneva)。 手元の時刻は tz を変換して出す = 夏時間の有無は tz の表 (zoneinfo) に任せ、
    固定の時差を手で足さない。
  - 時間割は会期の前でも動く (講演の追加・時間の変更)。 予定表に入れた後も、 出発前に読み直す。
標準 library だけ (urllib / json / zoneinfo)。 zoneinfo の表が無い機 (Windows の素の Python) では手元の時刻を出さずに 1 行言う。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

UA = "Mozilla/5.0 (compatible; indico-timetable/1.0)"


def parse_event_url(url: str) -> tuple[str, str]:
    """'https://<host>/event/<id>/...' → (base 'https://<host>', id)。 読めなければ ValueError。"""
    m = re.match(r"^(https?://[^/]+)(?:/.*)?/event/(\d+)", url.strip())
    if not m:
        raise ValueError(f"Indico の event の URL として読めない: {url}")
    return m.group(1), m.group(2)


def fetch(base: str, event_id: str) -> bytes:
    req = urllib.request.Request(f"{base}/export/timetable/{event_id}.json", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _names(entry: dict) -> list[str]:
    out = []
    for key in ("presenters", "speakers"):
        for p in entry.get(key) or []:
            n = (p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("familyName")) if x)).strip()
            if n and n not in out:
                out.append(n)
    return out


def talks(data: dict) -> list[dict]:
    """時間割の JSON → 講演の list (session の中も平らに)。 時刻順。"""
    out: list[dict] = []

    def walk(e: dict, session: str) -> None:
        kids = e.get("entries") or {}
        if kids:
            for c in kids.values():
                walk(c, e.get("title") or session)
            return
        if e.get("entryType") == "Break":
            return
        s, en = e.get("startDate") or {}, e.get("endDate") or {}
        out.append({"title": e.get("title") or "", "session": session, "names": _names(e),
                    "start": f"{s.get('date')}T{(s.get('time') or '')[:5]}", "end": f"{en.get('date')}T{(en.get('time') or '')[:5]}",
                    "tz": s.get("tz") or "UTC"})

    for ev in (data.get("results") or {}).values():
        for day in ev.values():
            for e in day.values():
                walk(e, "")
    return sorted(out, key=lambda t: (t["start"], t["title"]))


def local_times(t: dict, tz: str | None) -> str:
    try:
        from zoneinfo import ZoneInfo
        src = ZoneInfo(t["tz"])
        dst = ZoneInfo(tz) if tz else None
    except Exception:
        return "(手元の時刻は出せない: tz の表が無い)"
    a = datetime.fromisoformat(t["start"]).replace(tzinfo=src)
    b = datetime.fromisoformat(t["end"]).replace(tzinfo=src)
    a, b = (a.astimezone(dst), b.astimezone(dst)) if dst else (a.astimezone(), b.astimezone())
    return f"{a:%m-%d %H:%M}-{b:%H:%M} {a.tzname()}"


def show(rows: list[dict], tz: str | None) -> None:
    for t in rows:
        print(f"{t['start'][5:].replace('T', ' ')}-{t['end'][11:]} {t['tz']} | {local_times(t, tz)} | "
              f"{t['session'] or '-'} | {t['title']} | {', '.join(t['names']) or '-'}")


def selftest() -> int:
    data = {"results": {"1": {"20300114": {
        "s1": {"entryType": "Session", "title": "Session 1: Theory", "entries": {
            "c1": {"entryType": "Contribution", "title": "A synthetic talk on wave packets",
                   "presenters": [{"name": "A. Example"}],
                   "startDate": {"date": "2030-01-14", "time": "00:00:00", "tz": "UTC"},
                   "endDate": {"date": "2030-01-14", "time": "00:25:00", "tz": "UTC"}},
            "b1": {"entryType": "Break", "title": "Coffee",
                   "startDate": {"date": "2030-01-14", "time": "00:25:00", "tz": "UTC"},
                   "endDate": {"date": "2030-01-14", "time": "00:40:00", "tz": "UTC"}}}},
        "c2": {"entryType": "Contribution", "title": "Another talk",
               "speakers": [{"firstName": "B.", "familyName": "Sample"}],
               "startDate": {"date": "2030-01-14", "time": "01:00:00", "tz": "UTC"},
               "endDate": {"date": "2030-01-14", "time": "01:17:00", "tz": "UTC"}}}}}}
    ok = True
    rows = talks(data)
    ok &= [r["title"] for r in rows] == ["A synthetic talk on wave packets", "Another talk"]   # Break は出さない・時刻順
    ok &= rows[0]["session"] == "Session 1: Theory" and rows[1]["names"] == ["B. Sample"]
    ok &= local_times(rows[0], "Asia/Tokyo").startswith("01-14 09:00-09:25")                # UTC 00:00 → JST 09:00
    ok &= parse_event_url("https://indico.example.org/event/12345/timetable/#all") == ("https://indico.example.org", "12345")
    try:
        parse_event_url("https://example.org/no-event")
        ok = False
    except ValueError:
        pass
    print("selftest:", "ok" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", nargs="?")
    ap.add_argument("--json", help="取得済みの JSON を読む")
    ap.add_argument("--match", help="題・発表者・session 名に当てる正規表現 (大文字小文字を区別しない)")
    ap.add_argument("--tz", help="手元の時刻の tz (既定 = この機械の tz)")
    ap.add_argument("--save", help="取得した JSON を書く path")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.json:
        raw = Path(a.json).read_bytes()
    elif a.url:
        raw = fetch(*parse_event_url(a.url))
    else:
        ap.error("URL か --json が要る")
    if a.save:
        Path(a.save).write_bytes(raw)
        print(f"保存: {a.save} (sha256 {hashlib.sha256(raw).hexdigest()})")
    rows = talks(json.loads(raw))
    if a.match:
        rx = re.compile(a.match, re.I)
        rows = [t for t in rows if rx.search(" ".join([t["title"], t["session"], *t["names"]]))]
    show(rows, a.tz)
    print(f"({len(rows)} 件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
