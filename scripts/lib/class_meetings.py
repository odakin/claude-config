#!/usr/bin/env python3
"""class_meetings.py — 授業の「第何回か」 をクラスのカレンダーから数え、 撮影時刻を時限に振り分ける helper (python3 class_meetings.py で selftest)

授業の記録 (板書写真・動画・感想課題) に「第N回」 を振るとき、 手元のフォルダの続き番号 (最大 + 1) だけで
決めると、 記録の無い回 (写真を撮らなかった回) があった時点で以後の番号が 1 つずつずれる。 授業のある日
だけが入ったカレンダー (Google Classroom のクラスのカレンダーに毎週の予定を入れ、 休講・休暇を除いたもの
= conventions/google-classroom-api.md#class-calendar) があれば、 学期はじめからの件数が正しい回数になる。
両方を出して食い違ったら止めて人に確かめる、 が conventions/chalkboard-photo-archive.md の使い方。

- meeting_days(events, tz)       : カレンダーの予定 (Calendar API の events.list(singleEvents=True) の items)
                                   から授業のある日を並べる。 開始時刻つきで min_minutes (既定 30) 分以上の予定だけ
                                   = Classroom が自動で入れる課題の期限 (1 分の予定) や終日の予定を数えない
- lecture_number(events, day, tz): day が第何回か (その日に授業が無ければ None = 補講を入れ忘れた・日付の誤り)
- period_midpoints(periods)      : その日の授業の (開始分, 終了分) の列から、 隣の授業との境目 (前の終わりと
                                   次の始まりの中点) を返す
- assign(minute, midpoints)      : 撮影時刻 (0 時からの分) が何番目の授業か (最後より後は最後の授業)
"""
from __future__ import annotations

import datetime as dt


def _parse(s: str) -> dt.datetime:
    # python 3.9 の fromisoformat は末尾 Z を読めない
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def meeting_days(events: list[dict], tz, min_minutes: int = 30) -> list[dt.date]:
    days = set()
    for e in events:
        if e.get("status") == "cancelled":
            continue
        s, en = e.get("start", {}).get("dateTime"), e.get("end", {}).get("dateTime")
        if not s or not en:  # 終日の予定
            continue
        ts, te = _parse(s), _parse(en)
        if te - ts < dt.timedelta(minutes=min_minutes):  # 課題の期限など
            continue
        days.add(ts.astimezone(tz).date())
    return sorted(days)


def lecture_number(events: list[dict], day: dt.date, tz, min_minutes: int = 30) -> int | None:
    days = [d for d in meeting_days(events, tz, min_minutes) if d <= day]
    return len(days) if days and days[-1] == day else None


def fetch_events(service, calendar_id: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    """Calendar API (googleapiclient の service) から [start, end) の予定を繰り返しを展開して取る。"""
    items, token = [], None
    while True:
        r = service.events().list(calendarId=calendar_id, timeMin=start.isoformat(), timeMax=end.isoformat(),
                                  singleEvents=True, orderBy="startTime", maxResults=250,
                                  pageToken=token).execute()
        items += r.get("items", [])
        token = r.get("nextPageToken")
        if not token:
            return items


def period_midpoints(periods: list[tuple[int, int]]) -> list[int]:
    return [(periods[i][1] + periods[i + 1][0]) // 2 for i in range(len(periods) - 1)]


def assign(minute: int, midpoints: list[int]) -> int:
    return sum(1 for mp in midpoints if minute >= mp)


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    fails = []

    def check(cond, name):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    tz = dt.timezone(dt.timedelta(hours=9))

    def timed(day, start, minutes, status="confirmed"):
        s = dt.datetime.combine(day, start, tz)
        return {"status": status, "start": {"dateTime": s.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")},
                "end": {"dateTime": (s + dt.timedelta(minutes=minutes)).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")}}

    d0 = dt.date(2030, 4, 5)  # 合成の学期 (毎週同じ曜日、 3 週目は休講で予定なし)
    weeks = [d0 + dt.timedelta(weeks=k) for k in (0, 1, 3, 4)]
    ev = [timed(d, dt.time(10, 55), 90) for d in weeks]
    # 数えてはいけない予定は最後の授業より後の別々の日に置く (= 検査どうしが独立に落ちる)
    due_day, allday_day, cancel_day = (weeks[3] + dt.timedelta(days=k) for k in (1, 2, 3))
    ev.append(timed(due_day, dt.time(23, 59), 1))  # 課題の期限 (1 分)
    ev.append({"status": "confirmed", "start": {"date": allday_day.isoformat()}, "end": {"date": allday_day.isoformat()}})
    ev.append(timed(cancel_day, dt.time(10, 55), 90, status="cancelled"))
    check([lecture_number(ev, d, tz) for d in weeks] == [1, 2, 3, 4],
          "授業のある日を学期はじめから数える (休講の週は飛ばす)")
    check(lecture_number(ev, d0 + dt.timedelta(weeks=2), tz) is None, "授業の無い日は None")
    check(lecture_number(ev, due_day, tz) is None, "課題の期限 (短い予定) は数えない")
    check(lecture_number(ev, allday_day, tz) is None, "終日の予定は数えない")
    check(lecture_number(ev, cancel_day, tz) is None, "取り消した予定は数えない")
    late = timed(d0, dt.time(23, 30), 90)  # 日本時間では当日、 UTC では同じ日
    check(meeting_days([late], tz) == [d0], "日付は現地時刻で決める")
    mids = period_midpoints([(540, 630), (655, 745), (795, 885)])
    check(mids == [642, 770], "隣の授業との境目 = 前の終わりと次の始まりの中点")
    check([assign(m, mids) for m in (600, 641, 642, 700, 900)] == [0, 0, 1, 1, 2],
          "撮影時刻を時限に振り分け、 最後より後は最後の授業")
    print("class_meetings selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
