#!/usr/bin/env python3
"""calendar-app-occurrence.py — Mac の Calendar.app にある繰り返し予定の「この回だけ」 をずらす / 飛ばす、 写しの系列を丸ごと消す (EventKit、 既定 dry-run)。

なぜ要るか (実測):
  繰り返し予定の 1 回だけを変える操作は、 Android (Etar + DAVx5) から iCloud へ送ると壊れることがある
  (編集が出ず「複製」 しか選べず、 同じ繰り返しの写しが増えて重複した)。 Apple 純正の EventKit から
  `span = この予定のみ` で保存すれば、 元の系列に、 その回だけを変えた印 (RECURRENCE-ID の回) が付くだけで、 他の端末にも
  そのまま届く。 毎回 Swift や JXA を書き下ろすと span の取り違え (= 系列ごと動く・消える) と紙一重なので道具にする。
  手順と罠の正本 = conventions/macos-calendar-write.md#recurring-one-occurrence

subcommands (calendar 名は Calendar.app が出す名前そのもの。 同名が複数あるなら --source で account を絞る。
--title は題の完全一致 = 題の一部では 0 件になる (実測)。 題が分からないなら list を --title 無しで回して読む):
  list    --calendar C [--title T] [--from D] [--to D]       回ごとに 日時 / series id / 繰り返し / 個別に変えた回か を出す
  move    --calendar C --title T --date D [--time HH:MM] --to-date D2 [--to-time HH:MM] [--apply]
          その回だけを D2 へ (時刻を省くと元の時刻、 長さは保つ)
  skip    --calendar C --title T --date D [--time HH:MM] [--apply]      その回だけを消す (除外日)
  remove-series --calendar C --series-id ID [--apply]                  系列を丸ごと消す (重複の写しの掃除用)

安全側の既定:
  - --apply が無ければ何も書かない (計画だけ出す)
  - 対象の回がちょうど 1 つでなければ止まる (重複があるなら list で series id を見て remove-series が先)
  - ゲスト (参加者) のいる予定は止まる = 保存で server が招待の更新を送りうる。 承知なら --allow-attendees
  - 書いた後に読み直して、 計画どおりの形になったかを確かめる
  ⚠️ 他の端末 (例: DAVx5 の Android) は、 その端末の同期の番が来るまで古いまま。 iCloud は DAVx5 に変更を知らせない

usage:
  calendar-app-occurrence.py list --calendar Family --title "Piano" --from 2030-01-01 --to 2030-01-31
  calendar-app-occurrence.py move --calendar Family --title "Piano" --date 2030-01-07 --to-date 2030-01-08
  calendar-app-occurrence.py move ... --apply
  calendar-app-occurrence.py --selftest      (Calendar.app に触らない純関数の検査)
日付は Mac の local time で読む。 macOS 以外では何もしない。 Calendar 権限 (TCC) は osascript の起動元に付く。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys

JXA = r"""
ObjC.import('EventKit');
function iso(d) { return d.isNil() ? null : d.timeIntervalSince1970; }
function run(argv) {
  var spec = JSON.parse(argv[0]);
  var store = $.EKEventStore.alloc.init;
  var out = {auth: $.EKEventStore.authorizationStatusForEntityType(0)};
  var cals = ObjC.unwrap(store.calendarsForEntityType(0)).filter(function (c) {
    return ObjC.unwrap(c.title) === spec.calendar && (!spec.source || ObjC.unwrap(c.source.title) === spec.source);
  });
  out.calendars = cals.map(function (c) { return {title: ObjC.unwrap(c.title), source: ObjC.unwrap(c.source.title)}; });
  if (cals.length !== 1) { out.error = 'calendar_not_unique'; return JSON.stringify(out); }
  var cal = cals[0];
  var pred = store.predicateForEventsWithStartDateEndDateCalendars(
    $.NSDate.dateWithTimeIntervalSince1970(spec.from), $.NSDate.dateWithTimeIntervalSince1970(spec.until),
    $.NSArray.arrayWithObject(cal));
  var evs = ObjC.unwrap(store.eventsMatchingPredicate(pred));
  function desc(e) {
    var rules = e.hasRecurrenceRules ? ObjC.unwrap(e.recurrenceRules).map(function (r) { return ObjC.unwrap(r.description); }) : [];
    return {title: ObjC.unwrap(e.title), start: iso(e.startDate), end: iso(e.endDate), allDay: e.allDay,
            series: ObjC.unwrap(e.calendarItemExternalIdentifier), detached: e.isDetached,
            rules: rules, attendees: e.hasAttendees};
  }
  var sel = evs.filter(function (e) { return !spec.title || ObjC.unwrap(e.title) === spec.title; });
  if (spec.series) { sel = sel.filter(function (e) { return ObjC.unwrap(e.calendarItemExternalIdentifier) === spec.series; }); }
  if (spec.at !== undefined && spec.at !== null) { sel = sel.filter(function (e) { return Math.abs(e.startDate.timeIntervalSince1970 - spec.at) < 1; }); }
  out.matches = sel.map(desc);
  if (spec.op === 'remove-series') {
    // the series master (not its earliest visible occurrence: that may be after a detached exception
    // or outside the window, and futureEvents on it would only truncate the series)
    sel = ObjC.unwrap(store.calendarItemsWithExternalIdentifier(spec.series)).filter(function (i) {
      return ObjC.unwrap(i.calendar.title) === spec.calendar && (!spec.source || ObjC.unwrap(i.calendar.source.title) === spec.source);
    });
    out.masters = sel.map(desc);
  }
  if (!spec.apply || spec.op === 'list') { return JSON.stringify(out); }
  if (sel.length !== 1) { out.error = 'target_not_unique'; return JSON.stringify(out); }
  var ev = sel[0], err = $(), ok;   // NSError** out-param: $() works, Ref() segfaults osascript (macOS 26)
  if (spec.op === 'move') {
    ev.setStartDate($.NSDate.dateWithTimeIntervalSince1970(spec.newStart));
    ev.setEndDate($.NSDate.dateWithTimeIntervalSince1970(spec.newEnd));
    ok = store.saveEventSpanCommitError(ev, 0, true, err);           // 0 = EKSpanThisEvent
  } else if (spec.op === 'skip') {
    ok = store.removeEventSpanCommitError(ev, 0, true, err);         // 0 = EKSpanThisEvent
  } else if (spec.op === 'remove-series') {
    ok = store.removeEventSpanCommitError(ev, 1, true, err);         // 1 = EKSpanFutureEvents on the master = whole series
  }
  out.ok = !!ok;
  if (!ok && !err.isNil()) { out.error = ObjC.unwrap(err.localizedDescription); }
  return JSON.stringify(out);
}
"""


def local_epoch(day: str, hhmm: str | None = None) -> float:
    """local time の日付 (+時刻) を epoch 秒に。 時刻なし = その日の 0:00。"""
    d = _dt.date.fromisoformat(day)
    t = _dt.time.fromisoformat(hhmm) if hhmm else _dt.time(0, 0)
    return _dt.datetime.combine(d, t).astimezone().timestamp()


def day_window(day: str) -> tuple[float, float]:
    start = local_epoch(day)
    end = (_dt.datetime.fromtimestamp(start) + _dt.timedelta(days=1)).timestamp()
    return start, end


def shifted(start: float, end: float, to_date: str, to_time: str | None) -> tuple[float, float]:
    """元の回 (start, end) を to_date へ。 to_time が無ければ元の時刻のまま、 長さは保つ。"""
    orig = _dt.datetime.fromtimestamp(start)
    hhmm = to_time or orig.strftime("%H:%M")
    new_start = local_epoch(to_date, hhmm)
    return new_start, new_start + (end - start)


def fmt(ts: float | None) -> str:
    if ts is None:
        return "-"
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d(%a) %H:%M")


def call(spec: dict) -> dict:
    p = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA, json.dumps(spec)],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        sys.exit(f"osascript failed (rc={p.returncode}): {p.stderr.strip()}")
    return json.loads(p.stdout)


def show(matches: list[dict]) -> None:
    for m in matches:
        kind = "個別に変えた回" if m["detached"] else ("繰り返し" if m["rules"] else "単発")
        rule = "; ".join(r.split("RRULE ", 1)[-1] for r in m["rules"])
        guest = " ゲストあり" if m["attendees"] else ""
        print(f"  {fmt(m['start'])} - {fmt(m['end'])[-5:]}  {m['title']}  [{kind}{guest}] series={m['series']}  {rule}")


def base_spec(a, op: str) -> dict:
    return {"op": op, "calendar": a.calendar, "source": a.source, "title": getattr(a, "title", None)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("list", "move", "skip", "remove-series"):
        s = sub.add_parser(name)
        s.add_argument("--calendar", required=True)
        s.add_argument("--source", help="account 名 (同名の calendar が複数ある時)")
        if name != "remove-series":
            s.add_argument("--title", required=(name != "list"))
        if name == "list":
            s.add_argument("--from", dest="frm", default=_dt.date.today().isoformat())
            s.add_argument("--to", dest="to")
        if name in ("move", "skip"):
            s.add_argument("--date", required=True)
            s.add_argument("--time")
        if name == "move":
            s.add_argument("--to-date", required=True)
            s.add_argument("--to-time")
        if name == "remove-series":
            s.add_argument("--series-id", required=True)
        if name != "list":
            s.add_argument("--apply", action="store_true")
            s.add_argument("--allow-attendees", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if sys.platform != "darwin":
        print("macOS 以外では何もしない")
        return 0
    if not a.cmd:
        ap.print_help()
        return 2

    if a.cmd == "list":
        frm = local_epoch(a.frm)
        until = local_epoch(a.to) if a.to else frm + 35 * 86400
        if until <= frm:
            sys.exit("--to は --from より後に (--to は排他)")
        r = call({**base_spec(a, "list"), "from": frm, "until": until})
        if r.get("error"):
            sys.exit(f"{r['error']}: {r.get('calendars')}")
        print(f"{len(r['matches'])} 件 ({a.calendar}, {fmt(frm)[:10]} 〜 {fmt(until)[:10]} の手前)")
        show(r["matches"])
        return 0

    if a.cmd in ("move", "skip"):
        frm, until = day_window(a.date)
        spec = {**base_spec(a, a.cmd), "from": frm, "until": until,
                "at": local_epoch(a.date, a.time) if a.time else None}
    else:  # remove-series: the series' occurrences within ~2 years from 2 years back
        now = _dt.datetime.now().timestamp()
        spec = {**base_spec(a, a.cmd), "title": None, "series": a.series_id,
                "from": now - 730 * 86400, "until": now + 730 * 86400}

    r = call(spec)
    if r.get("error"):
        sys.exit(f"{r['error']}: {r.get('calendars')}")
    m = r["matches"]
    if a.cmd != "remove-series" and len(m) != 1:
        print(f"対象がちょうど 1 つでない ({len(m)} 件)。 --time で絞るか、 重複なら list で series id を見て remove-series を先に:")
        show(m)
        return 1
    if a.cmd == "remove-series":
        if len(r.get("masters", [])) != 1:
            print(f"その series id の本体がちょうど 1 つでない ({len(r.get('masters', []))} 件) = 止める")
            show(r.get("masters", []))
            return 1
    elif not m:
        print("対象の回が見つからない")
        return 1
    if any(x["attendees"] for x in m) and not a.allow_attendees:
        print("ゲストのいる予定 = 保存すると server が招待の更新を送りうる。 承知なら --allow-attendees")
        show(m[:1])
        return 1

    tgt = r["masters"][0] if a.cmd == "remove-series" else m[0]
    if a.cmd == "move":
        ns, ne = shifted(tgt["start"], tgt["end"], a.to_date, a.to_time)
        spec.update(newStart=ns, newEnd=ne, at=tgt["start"])
        print(f"PLAN この回だけ移す: {fmt(tgt['start'])} → {fmt(ns)} - {fmt(ne)[-5:]}  「{tgt['title']}」")
    elif a.cmd == "skip":
        spec.update(at=tgt["start"])
        print(f"PLAN この回だけ消す: {fmt(tgt['start'])}  「{tgt['title']}」")
    else:
        rule = "; ".join(x.split("RRULE ", 1)[-1] for x in tgt["rules"])
        print(f"PLAN 系列を丸ごと消す: series={a.series_id} 「{tgt['title']}」 始まり = {fmt(tgt['start'])}  {rule}  (前後 2 年に見えている回 {len(m)} 件)")
    if not a.apply:
        print("dry run (書くなら --apply)")
        return 0

    r = call({**spec, "apply": True})
    if not r.get("ok"):
        sys.exit(f"保存に失敗: {r.get('error')}")
    # 読み直して確かめる
    if a.cmd == "move":
        w0, w1 = day_window(a.to_date)
        chk = call({**base_spec(a, "list"), "from": w0, "until": w1, "at": spec["newStart"]})["matches"]
        old = call({**base_spec(a, "list"), "from": frm, "until": until, "at": tgt["start"]})["matches"]
        good = len(chk) == 1 and chk[0]["detached"] and (not old or abs(spec["newStart"] - tgt["start"]) < 1)
    elif a.cmd == "skip":
        good = not call({**base_spec(a, "list"), "from": frm, "until": until, "at": tgt["start"]})["matches"]
    else:
        good = not call({**spec, "apply": False})["matches"]
    print("DONE (読み直しで確認済み)" if good else "⚠️ 保存は通ったが、 読み直しの形が計画と違う = list で見る")
    print("他の端末 (DAVx5 の Android など) は、 その端末で同期が走るまで古いまま")
    return 0 if good else 1


def selftest() -> int:
    fails = 0

    def eq(got, want, label):
        nonlocal fails
        if got != want:
            fails += 1
            print(f"FAIL {label}: {got!r} != {want!r}")

    s = local_epoch("2030-01-07", "19:00")
    e = s + 90 * 60
    ns, ne = shifted(s, e, "2030-01-08", None)
    eq(ns - s, 86400.0, "move keeps time (+1 day)")
    eq(ne - ns, 90 * 60.0, "move keeps duration")
    ns2, _ = shifted(s, e, "2030-01-08", "18:30")
    eq(_dt.datetime.fromtimestamp(ns2).strftime("%Y-%m-%d %H:%M"), "2030-01-08 18:30", "move with --to-time")
    w0, w1 = day_window("2030-01-07")
    eq(w0 <= s < w1, True, "occurrence inside its day window")
    eq(w1 - w0 in (82800.0, 86400.0, 90000.0), True, "day window is one local day")
    print("selftest:", "ALL PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
