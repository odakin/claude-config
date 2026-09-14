#!/usr/bin/env python3
"""calendar-events.py — Google Calendar の event を機械で読む / 足す / 消す。

MCP の create_event が使えない session (= server 未接続 / bulk) と、
学会の聴講計画のように **数十 event を一度に組み立てる** 用途のための CLI。

設計動機 (= 実測。 この種の操作は使い捨て script で書き散らされやすい):
  - OAuth の load → build → insert が毎回同じ 20 行の写経になる
  - **削除に dry-run が無い** ものをその場で書くと、 保護対象 (他の予定・終日 event)
    を巻き込む事故と紙一重になる
  - 「空き時間」 の計算を ad hoc に書くと、 block event が窓を占有する問題
    (= 下記 gaps の docstring) に気づけない

⚠️ **layer 1 なので calendar id も token path も持たない**。 呼び出し側 (= 個人層) が
   env で渡す。 個人の calendar id は layer 3 の SoT に置く (= 公開 repo に焼かない)。

env:
  CLAUDE_CALENDAR_ID         書き先 calendar の id                      (必須)
  CLAUDE_CALENDAR_TOKEN_DIR  credentials.json + gcp-oauth.keys.json の dir (必須)
  CLAUDE_CALENDAR_CRED_NAME  credential file 名 (default credentials.json)
  CLAUDE_CALENDAR_TZ         timeZone (default Asia/Tokyo)

使い方:
  calendar-events.py list   --from 2030-01-10 --to 2030-01-14
  calendar-events.py gaps   --from 2030-01-10 --to 2030-01-14 \
                            --windows 09:00-12:30,13:30-17:30
  calendar-events.py dups   --from 2030-01-10 --to 2030-01-14
  calendar-events.py add    --spec talks.yaml [--apply]
  calendar-events.py delete --from 2030-01-10T14:45 --to 2030-01-11 \
                            --match '学会' --protect '打合せ|会期' [--apply]
  calendar-events.py --selftest

add / delete は **既定 dry-run**。 実行は --apply。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

JST = datetime.timezone(datetime.timedelta(hours=9))
DEFAULT_REMINDERS = [0, 5, 15]


# ---------------------------------------------------------------- 純関数群
# (= API を叩かない。 selftest の契約はここ)

def parse_window(s: str) -> tuple[int, int]:
    """'09:00-12:30' → (540, 750) 分単位。"""
    a, b = s.split("-")
    return hhmm_to_min(a), hhmm_to_min(b)


def hhmm_to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def min_to_hhmm(x: int) -> str:
    return f"{x // 60:02d}:{x % 60:02d}"


def compute_gaps(busy: list[tuple[int, int]], window: tuple[int, int]) -> list[tuple[int, int]]:
    """window 内で busy 区間に覆われていない帯を返す (分単位)。

    ⚠️ **これは「予定が入っていない時間」 であって「やることが無い時間」 ではない**。
    session 丸ごとを 1 event にした block が置いてあると、 その窓は busy 扱いになり
    **窓の中の個別トークが候補検討の射程から丸ごと落ちる** (= 実測で、
    複数の窓が sweep 射程外だった)。 学会の聴講計画のように「重なってもよいから内容で
    選びたい」 用途では gaps を入口にせず、 **プログラム全体を走査**すること。
    正本 = conventions/jps-talk-submission.md#candidate-calendar-discipline
    """
    w0, w1 = window
    clipped = sorted((max(b0, w0), min(b1, w1)) for b0, b1 in busy if b1 > w0 and b0 < w1)
    merged: list[list[int]] = []
    for b0, b1 in clipped:
        if merged and b0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b1)
        else:
            merged.append([b0, b1])
    out, cur = [], w0
    for b0, b1 in merged:
        if b0 > cur:
            out.append((cur, b0))
        cur = max(cur, b1)
    if cur < w1:
        out.append((cur, w1))
    return out


def find_duplicates(items: list[dict]) -> list[tuple[str, list[str]]]:
    """(開始時刻, 会場, 要約) が同一の event を重複として返す。

    「同じ時刻に別の候補」 は重複ではない (= 選択肢)。 **完全に同じ講演が 2 件**だけを
    重複とみなす (= block を split する際、 元が単一トークの event を二重に作りやすい)。
    """
    seen: dict[tuple, list[str]] = {}
    for e in items:
        key = (e.get("start", ""), e.get("location") or "", (e.get("summary") or "").strip())
        seen.setdefault(key, []).append(e.get("id", ""))
    return [(f"{k[0]} {k[2][:40]}", v) for k, v in sorted(seen.items()) if len(v) > 1]


def select_for_delete(items: list[dict], match: str | None, protect: str | None,
                      cutoff: str | None) -> tuple[list[dict], list[tuple[dict, str]]]:
    """削除対象と保護対象に仕分ける。 **保護側の理由も返す** (= 消さない根拠を出す)。

    - 終日 event (start に 'T' が無い) は常に保護 (= 会期・記念日を巻き込まない)
    - protect 正規表現に当たる summary は保護 (= 同じ窓の別種の予定)
    - match 正規表現が指定されていれば、 当たらない summary は保護
    - cutoff ('YYYY-MM-DDTHH:MM') より前に始まる event は保護
    """
    kill, keep = [], []
    for e in items:
        s = e.get("start", "")
        sm = e.get("summary", "") or ""
        if "T" not in s:
            keep.append((e, "終日 event"))
        elif protect and re.search(protect, sm):
            keep.append((e, "protect に一致"))
        elif match and not re.search(match, sm):
            keep.append((e, "match に不一致"))
        elif cutoff and s[:16] < cutoff:
            keep.append((e, "cutoff より前"))
        else:
            kill.append(e)
    return kill, keep


def build_event_body(spec: dict, tz: str, default_reminders=None) -> dict:
    """spec (dict) → Calendar API の event body。 必須欄が無ければ ValueError。

    spec: summary / start / end (ISO 'YYYY-MM-DDTHH:MM') は必須。
          location / description / reminders (分の list) は任意。
    """
    for k in ("summary", "start", "end"):
        if not spec.get(k):
            raise ValueError(f"spec に {k} が無い: {spec!r}")
    if spec["end"] <= spec["start"]:
        raise ValueError(f"end <= start: {spec['start']} .. {spec['end']}")
    mins = spec.get("reminders", default_reminders if default_reminders is not None else DEFAULT_REMINDERS)
    body = {
        "summary": spec["summary"],
        "start": {"dateTime": f"{spec['start']}:00+09:00", "timeZone": tz},
        "end": {"dateTime": f"{spec['end']}:00+09:00", "timeZone": tz},
        "reminders": {"useDefault": False,
                      "overrides": [{"method": "popup", "minutes": m} for m in mins]},
    }
    if spec.get("location"):
        body["location"] = spec["location"]
    if spec.get("description"):
        body["description"] = spec["description"]
    return body


# ---------------------------------------------------------------- API 層

def _cfg(name: str, required: bool = True) -> str:
    v = os.environ.get(name, "")
    if required and not v:
        sys.exit(f"環境変数 {name} が未設定 (= layer 1 script なので個人の値は持たない)。\n"
                 f"  個人層の SoT から export すること。")
    return v


def get_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    d = Path(_cfg("CLAUDE_CALENDAR_TOKEN_DIR")).expanduser()
    cred_name = os.environ.get("CLAUDE_CALENDAR_CRED_NAME", "credentials.json")
    cd = json.loads((d / cred_name).read_text())
    keys = json.loads((d / "gcp-oauth.keys.json").read_text())["installed"]
    c = Credentials(
        token=cd.get("access_token"), refresh_token=cd.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=keys["client_id"], client_secret=keys["client_secret"],
        scopes=cd.get("scope", "").split(),
    )
    if c.expired and c.refresh_token:
        # refresh は in-memory のみ (= file に書き戻すと git churn / cross-machine conflict)
        c.refresh(Request())
    return build("calendar", "v3", credentials=c, cache_discovery=False)


def fetch(svc, cal: str, frm: str, to: str) -> list[dict]:
    def iso(x, end=False):
        if "T" in x:
            return f"{x}:00+09:00" if len(x) == 16 else x
        return f"{x}T{'00:00' if not end else '00:00'}:00+09:00"

    out, token = [], None
    while True:
        r = svc.events().list(calendarId=cal, timeMin=iso(frm), timeMax=iso(to, True),
                              singleEvents=True, orderBy="startTime",
                              pageToken=token, maxResults=2500).execute()
        for e in r.get("items", []):
            out.append({
                "id": e["id"],
                "start": e["start"].get("dateTime", e["start"].get("date", "")),
                "end": e["end"].get("dateTime", e["end"].get("date", "")),
                "summary": e.get("summary", ""),
                "location": e.get("location") or "",
            })
        token = r.get("nextPageToken")
        if not token:
            return out


# ---------------------------------------------------------------- コマンド

def cmd_list(a) -> int:
    svc = get_service()
    for e in fetch(svc, _cfg("CLAUDE_CALENDAR_ID"), a.frm, a.to):
        s, en = e["start"], e["end"]
        when = f"{s[:10]} {s[11:16]}-{en[11:16]}" if "T" in s else f"{s[:10]}    終日     "
        print(f"{when}  {e['location'][:22]:<22} {e['summary'][:62]}")
        if a.ids:
            print(f"{'':>17}  id={e['id']}")
    return 0


def cmd_gaps(a) -> int:
    svc = get_service()
    items = fetch(svc, _cfg("CLAUDE_CALENDAR_ID"), a.frm, a.to)
    windows = [parse_window(w) for w in a.windows.split(",")]
    by_day: dict[str, list] = {}
    for e in items:
        if "T" in e["start"]:
            by_day.setdefault(e["start"][:10], []).append(
                (hhmm_to_min(e["start"][11:16]), hhmm_to_min(e["end"][11:16])))
    for d in sorted(by_day):
        print(f"\n== {d} ==")
        for w in windows:
            for g0, g1 in compute_gaps(by_day[d], w):
                print(f"   空き {min_to_hhmm(g0)}-{min_to_hhmm(g1)}")
    print("\n⚠️ 「空き」 = 予定が入っていない時間。 block event が窓を占有していると"
          "\n   その中の個別候補は検討されない (docstring 参照)。")
    return 0


def cmd_dups(a) -> int:
    svc = get_service()
    d = find_duplicates(fetch(svc, _cfg("CLAUDE_CALENDAR_ID"), a.frm, a.to))
    for label, ids in d:
        print(f"  {label}")
        for i in ids:
            print(f"       id={i}")
    print(f"\n重複 {len(d)} 組" if d else "重複なし")
    return 0


def cmd_add(a) -> int:
    import yaml
    specs = yaml.safe_load(Path(a.spec).read_text())
    if isinstance(specs, dict):
        specs = specs.get("events", [])
    tz = os.environ.get("CLAUDE_CALENDAR_TZ", "Asia/Tokyo")
    bodies = [build_event_body(s, tz) for s in specs]      # 先に全件 validate
    if not a.apply:
        for b in bodies:
            print(f"  + {b['start']['dateTime'][:16]} {b['summary'][:66]}")
        print(f"\n(dry-run: {len(bodies)} 件。 --apply で実行)")
        return 0
    svc = get_service()
    cal = _cfg("CLAUDE_CALENDAR_ID")
    for b in bodies:
        ev = svc.events().insert(calendarId=cal, body=b).execute()
        print(f"  + {b['start']['dateTime'][:16]} {ev['id']}  {b['summary'][:52]}")
    return 0


def cmd_delete(a) -> int:
    svc = get_service()
    cal = _cfg("CLAUDE_CALENDAR_ID")
    items = fetch(svc, cal, a.frm[:10], a.to)
    kill, keep = select_for_delete(items, a.match, a.protect, a.frm if "T" in a.frm else None)
    print("=== 残すもの ===")
    for e, why in keep:
        print(f"  {e['start'][11:16] or '終日':>5}  {e['summary'][:56]}   [{why}]")
    print("\n=== 消すもの ===")
    for e in kill:
        print(f"  {e['start'][11:16]:>5}  {e['summary'][:56]}")
    if not a.apply:
        print(f"\n(dry-run: {len(kill)} 件が対象。 --apply で実行)")
        return 0
    print()
    for e in kill:
        svc.events().delete(calendarId=cal, eventId=e["id"]).execute()
        print(f"  ✅ deleted {e['start'][11:16]} {e['id']}")
    print(f"\n{len(kill)} 件削除")
    return 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    ok = fail = 0

    def check(cond, label):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS: {label}")
        else:
            fail += 1
            print(f"  FAIL: {label}")

    w = parse_window("09:00-12:30")
    check(w == (540, 750), "T1: parse_window")
    check(compute_gaps([], w) == [(540, 750)], "T2: 予定ゼロなら窓全体が空き")
    check(compute_gaps([(540, 600)], w) == [(600, 750)], "T3: 頭が埋まる")
    check(compute_gaps([(700, 750)], w) == [(540, 700)], "T4: 尻が埋まる")
    check(compute_gaps([(600, 630), (660, 690)], w) == [(540, 600), (630, 660), (690, 750)],
          "T5: 中抜け 2 つ")
    check(compute_gaps([(600, 660), (630, 700)], w) == [(540, 600), (700, 750)],
          "T6: 重なる busy は merge される")
    check(compute_gaps([(500, 800)], w) == [], "T7: 窓を覆う block は空きゼロ (= 汚染の再現)")
    check(compute_gaps([(300, 400)], w) == [(540, 750)], "T8: 窓外の予定は無視")

    items = [
        {"id": "a", "start": "2030-01-12T16:30", "location": "A101", "summary": "X"},
        {"id": "b", "start": "2030-01-12T16:30", "location": "A101", "summary": "X"},
        {"id": "c", "start": "2030-01-12T16:30", "location": "A102", "summary": "Y"},
    ]
    d = find_duplicates(items)
    check(len(d) == 1 and sorted(d[0][1]) == ["a", "b"], "T9: 完全同一のみ重複")
    check(all("c" not in ids for _, ids in d), "T10: 同時刻の別候補は重複でない")

    ev = [
        {"id": "1", "start": "2030-01-10", "summary": "学会 会期"},
        {"id": "2", "start": "2030-01-10T14:30", "summary": "🎧 学会 甲講演"},
        {"id": "3", "start": "2030-01-10T15:15", "summary": "🎧 学会 乙講演"},
        {"id": "4", "start": "2030-01-10T21:00", "summary": "夜の打合せ"},
    ]
    kill, keep = select_for_delete(ev, match="学会", protect=None, cutoff="2030-01-10T14:45")
    kids = [e["id"] for e in kill]
    check(kids == ["3"], "T11: cutoff 後の一致分のみ削除対象")
    check("1" in [e["id"] for e, _ in keep], "T12: 終日 event は常に保護")
    check("4" in [e["id"] for e, _ in keep], "T13: match 外の別予定は保護")
    check("2" in [e["id"] for e, _ in keep], "T14: cutoff 前は保護")
    kill2, _ = select_for_delete(ev, match=None, protect="打合せ", cutoff=None)
    check("4" not in [e["id"] for e in kill2], "T15: protect 正規表現が効く")

    b = build_event_body({"summary": "s", "start": "2030-01-10T10:00",
                          "end": "2030-01-10T10:15"}, "Asia/Tokyo")
    check(b["reminders"]["overrides"][0]["minutes"] == 0, "T16: 既定 reminder が入る")
    check("location" not in b, "T17: 任意欄は無ければ入れない")
    try:
        build_event_body({"summary": "s", "start": "2030-01-10T10:00",
                          "end": "2030-01-10T09:00"}, "Asia/Tokyo")
        check(False, "T18: end<=start は ValueError")
    except ValueError:
        check(True, "T18: end<=start は ValueError")
    try:
        build_event_body({"start": "2030-01-10T10:00", "end": "2030-01-10T10:15"}, "Asia/Tokyo")
        check(False, "T19: summary 欠落は ValueError")
    except ValueError:
        check(True, "T19: summary 欠落は ValueError")

    print(f"\n==== RESULT: PASS={ok} FAIL={fail} ====")
    return 1 if fail else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    def common(q):
        q.add_argument("--from", dest="frm", required=True)
        q.add_argument("--to", required=True)

    q = sub.add_parser("list"); common(q); q.add_argument("--ids", action="store_true")
    q = sub.add_parser("gaps"); common(q)
    q.add_argument("--windows", default="09:00-12:30,13:30-17:30")
    q = sub.add_parser("dups"); common(q)
    q = sub.add_parser("add")
    q.add_argument("--spec", required=True); q.add_argument("--apply", action="store_true")
    q = sub.add_parser("delete"); common(q)
    q.add_argument("--match"); q.add_argument("--protect")
    q.add_argument("--apply", action="store_true")

    a = p.parse_args()
    if a.selftest:
        return selftest()
    if not a.cmd:
        p.print_help()
        return 1
    return {"list": cmd_list, "gaps": cmd_gaps, "dups": cmd_dups,
            "add": cmd_add, "delete": cmd_delete}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
