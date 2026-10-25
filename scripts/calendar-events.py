#!/usr/bin/env python3
"""calendar-events.py — Google Calendar の event を機械で読む / 足す / 直す / 消す。

MCP の create_event が使えない session (= server 未接続 / bulk) と、
学会の聴講計画のように **数十 event を一度に組み立てる** 用途のための CLI。

設計動機 (= 実測。 この種の操作は使い捨て script で書き散らされやすい):
  - OAuth の load → build → insert が毎回同じ 20 行の写経になる
  - **削除に dry-run が無い** ものをその場で書くと、 保護対象 (他の予定・終日 event)
    を巻き込む事故と紙一重になる
  - 「空き時間」 の計算を ad hoc に書くと、 block event が窓を占有する問題
    (= 下記 gaps の docstring) に気づけない
  - 既存 event の時刻や説明を 1 か所直すだけでも、 道具に無いと OAuth の写経が
    また始まる (= patch)
  - **範囲が空 (--to <= --from) の list は黙って 0 件を返し、 「予定なし」 と
    読み違える** (= 1 日分を見るつもりで --from と --to に同じ日付を渡すと、
    --to は排他なので空になる)。 空の範囲はエラーにする
  - **複数日の予定を開始日だけで出すと、 開始日だけの予定と読み、 期間の途中の日を
    空きとして人に出す** (= 実測)。 list は終わりの日も出し (例 2030-01-07〜01-11)、
    add の前の同じ日の一覧と gaps は期間に入る日すべての予定として扱う (= event_days)

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
  calendar-events.py patch  --id <event id> [--start/--end 2030-01-10T13:00] \
                            [--summary '…'] [--append-description '…'] \
                            [--reminders 0,15,60] [--apply]
  calendar-events.py delete --from 2030-01-10T14:45 --to 2030-01-11 \
                            --match '学会' --protect '打合せ|会期' [--apply]
  calendar-events.py --selftest

add / patch / delete は **既定 dry-run**。 実行は --apply。
--to は**排他** (日付だけなら その日の 0:00)。 1 日分を見るなら --to に翌日を渡す。
event id は `list --ids` で引く。 patch の説明は置き換えず末尾に足す。
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

def _yaml_safe_load(stream):  # yaml.safe_load と同じ結果を C 版 (libyaml) で返す = 約 10 倍速 (2026-09-23)
    import yaml
    return yaml.load(stream, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


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


def _next_day(d: str) -> str:
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=1)).isoformat()


def last_day(start: str, end: str) -> str:
    """予定が掛かる最後の日 ('YYYY-MM-DD')。

    終日の予定の end は排他 (= 最後の日の翌日) なのでその前日。 時刻つきは end の日、
    ただし 0:00 ちょうどに終わるならその前日 (= 22:00-24:00 は 1 日の予定)。
    end が無い・読めない・start より前なら開始日。
    """
    s0 = start[:10]
    if not end or end[:10] <= s0:
        return s0
    if "T" in end and end[11:16] != "00:00":
        return end[:10]
    try:
        prev = (datetime.date.fromisoformat(end[:10]) - datetime.timedelta(days=1)).isoformat()
    except ValueError:
        return s0
    return max(prev, s0)


def event_days(start: str, end: str) -> list[str]:
    """予定が掛かる日 ('YYYY-MM-DD') を開始日から最後の日まで並べる。"""
    if not start:
        return []
    days, d, last = [], start[:10], last_day(start, end)
    try:
        while d <= last:
            days.append(d)
            d = _next_day(d)
    except ValueError:      # 日付として読めない start = 開始日の文字列だけを返す
        return [start[:10]]
    return days


def _md(d: str, ref: str) -> str:
    """ref と同じ年なら 'MM-DD'、 年をまたぐなら 'YYYY-MM-DD'。"""
    return d[5:10] if d[:4] == ref[:4] else d[:10]


def format_when(start: str, end: str) -> str:
    """list の日時欄。 1 日の予定は '2030-01-10 09:00-10:30' / '2030-01-10    終日     '、
    複数日の予定は終わりの日も出す = '2030-01-07〜01-11 終日' / '2030-01-10 22:00〜01-11 02:00'。
    """
    last = last_day(start, end)
    if "T" in start:
        if last == start[:10]:
            return f"{start[:10]} {start[11:16]}-{end[11:16]}"
        return f"{start[:10]} {start[11:16]}〜{_md(end, start)} {end[11:16]}"
    if last == start[:10]:
        return f"{start[:10]}    終日     "
    return f"{start[:10]}〜{_md(last, start)} 終日"


def span_head(start: str, end: str) -> str:
    """日付を省いた短い日時 (= 日ごとの一覧の見出し)。 1 日の予定は 'HH:MM' / '終日'、
    複数日の予定は期間 = '12-07 09:00〜12-08 17:00' / '終日 12-07〜12-11'。
    """
    last = last_day(start, end)
    if "T" in start:
        if last == start[:10]:
            return start[11:16]
        return f"{start[5:10]} {start[11:16]}〜{_md(end, start)} {end[11:16]}"
    return "終日" if last == start[:10] else f"終日 {start[5:10]}〜{_md(last, start)}"


def day_busy(items: list[dict]) -> tuple[dict[str, list[tuple[int, int]]], dict[str, list[str]]]:
    """gaps 用に (日ごとの busy 区間 〔分〕, 日ごとの終日の予定の見出し) を返す。

    時刻つきの予定は掛かる日すべてで busy にする (開始日は開始時刻から 24:00、 間の日は 1 日中、
    最後の日は 0:00 から終了時刻)。 終日の予定は busy に入れない (= 会期・学年暦などの印で窓を
    埋めない) が、 掛かる日すべてに期間つきの見出しを返す = 「空き」 と並べて見せる。
    """
    busy: dict[str, list[tuple[int, int]]] = {}
    allday: dict[str, list[str]] = {}
    for e in items:
        st, en = e.get("start", ""), e.get("end", "")
        days = event_days(st, en)
        if "T" in st:
            for d in days:
                b0 = hhmm_to_min(st[11:16]) if d == st[:10] else 0
                b1 = hhmm_to_min(en[11:16]) if d == en[:10] else 24 * 60
                busy.setdefault(d, []).append((b0, b1))
        else:
            label = f"{span_head(st, en)} {(e.get('summary') or '').strip()}"
            for d in days:
                allday.setdefault(d, []).append(label)
    return busy, allday


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


def same_day_existing(specs: list[dict], existing: list[dict]) -> list[tuple[str, list[str]]]:
    """足す予定が掛かる日ごとに、 その日に既に在る予定 (終日・複数日を含む) を返す
    = [(足す予定の要約, [既存の 'HH:MM 要約' / '終日 要約' / '終日 12-07〜12-11 要約'])]。

    足す前に同じ日を見ないと、 学年暦などから入っている終日の予定と同じものを時刻つきで二重に足す
    (実測: 確認の list と add を 1 つの command で流し、 list の結果を読む前に add が走った)。
    複数日の既存の予定は期間に入る日すべてで期間つきで出す。 足す予定が複数日なら既存の予定に日付を付ける。
    重複かどうかの判定はしない (要約の言い回しが違う = 機械では決められない) = 並べて見せるだけ。
    """
    by_day: dict[str, list[str]] = {}
    for e in existing:
        st, en = e.get("start", ""), e.get("end", "")
        label = f"{span_head(st, en)} {(e.get('summary') or '').strip()}"
        for day in event_days(st, en):
            by_day.setdefault(day, []).append(label)
    out = []
    for s in specs:
        st, en = str(s.get("start") or ""), str(s.get("end") or "")
        days = event_days(st, en)
        if len(days) > 1:
            head = f"{days[0]}〜{_md(days[-1], days[0])}"
            found = [f"{d[5:]} {x}" for d in days for x in by_day.get(d, [])]
        else:
            head, found = st[:10], by_day.get(st[:10], [])
        if found:
            out.append((f"{head} {str(s.get('summary', ''))[:50]}", found))
    return out


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


def _norm_bound(x: str) -> str:
    """'YYYY-MM-DD' / 'YYYY-MM-DDTHH:MM' を比較できる 'YYYY-MM-DDTHH:MM' に揃える。"""
    return x[:16] if "T" in x else f"{x}T00:00"


def check_range(frm: str, to: str) -> None:
    """--to <= --from なら ValueError (= 空の範囲で「0 件」 を返して読み違えさせない)。"""
    if _norm_bound(to) <= _norm_bound(frm):
        raise ValueError(
            f"範囲が空: --from {frm} --to {to} (--to は排他。 1 日分なら --to に翌日を渡す)")


def build_patch_body(current: dict, tz: str, start: str | None = None, end: str | None = None,
                     summary: str | None = None, append_description: str | None = None,
                     reminders: list[int] | None = None) -> dict:
    """既存 event (API の dict) と変更の指定 → events.patch の body。

    指定した欄だけを入れる。 時刻は 'YYYY-MM-DDTHH:MM'。 変更後の end <= start は ValueError。
    説明は**置き換えず末尾に足す** (= 前の記録を消さない)。 指定が 1 つも無ければ ValueError。
    """
    body: dict = {}
    if start:
        body["start"] = {"dateTime": f"{start}:00+09:00", "timeZone": tz}
    if end:
        body["end"] = {"dateTime": f"{end}:00+09:00", "timeZone": tz}
    new_s = start or current.get("start", {}).get("dateTime", "")[:16]
    new_e = end or current.get("end", {}).get("dateTime", "")[:16]
    if (start or end) and new_s and new_e and new_e <= new_s:
        raise ValueError(f"変更後の end <= start: {new_s} .. {new_e}")
    if summary:
        body["summary"] = summary
    if append_description:
        cur = (current.get("description") or "").rstrip()
        body["description"] = f"{cur}\n\n{append_description}" if cur else append_description
    if reminders is not None:
        body["reminders"] = {"useDefault": False,
                             "overrides": [{"method": "popup", "minutes": m} for m in reminders]}
    if not body:
        raise ValueError("変更する欄が指定されていない")
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
        print(f"{format_when(e['start'], e['end'])}  {e['location'][:22]:<22} {e['summary'][:62]}")
        if a.ids:
            print(f"{'':>17}  id={e['id']}")
    return 0


def cmd_gaps(a) -> int:
    svc = get_service()
    items = fetch(svc, _cfg("CLAUDE_CALENDAR_ID"), a.frm, a.to)
    windows = [parse_window(w) for w in a.windows.split(",")]
    busy, allday = day_busy(items)
    lo, hi = a.frm[:10], _norm_bound(a.to)
    for d in sorted(x for x in set(busy) | set(allday) if lo <= x and f"{x}T00:00" < hi):
        print(f"\n== {d} ==")
        for label in allday.get(d, []):
            print(f"   {label[:60]}   ← 空きの計算に入れていない")
        for w in windows:
            for g0, g1 in compute_gaps(busy.get(d, []), w):
                print(f"   空き {min_to_hhmm(g0)}-{min_to_hhmm(g1)}")
    print("\n⚠️ 「空き」 = 予定が入っていない時間。 block event が窓を占有していると"
          "\n   その中の個別候補は検討されない (docstring 参照)。"
          "\n   終日の予定 (複数日を含む) は空きの計算に入れず、 掛かる日の見出しの下に出す。")
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
    specs = _yaml_safe_load(Path(a.spec).read_text())
    if isinstance(specs, dict):
        specs = specs.get("events", [])
    tz = os.environ.get("CLAUDE_CALENDAR_TZ", "Asia/Tokyo")
    bodies = [build_event_body(s, tz) for s in specs]      # 先に全件 validate
    # 同じ日の既存の予定を dry-run でも apply でも見せる (= 重複は dry-run の出力で気づく。 読めなければ 1 行で言う)
    svc = None
    try:
        svc = get_service()
        days = sorted({d for s in specs for d in event_days(str(s["start"]), str(s["end"]))})
        hits = same_day_existing(specs, fetch(svc, _cfg("CLAUDE_CALENDAR_ID"), days[0], _next_day(days[-1])))
        for label, ex in hits:
            print(f"  ⚠️ 同じ日に既に在る予定 ({label} を足す前に見る): " + " / ".join(x[:56] for x in ex))
    except Exception as e:   # 読めなくても add 自体は止めない (見られなかったことは言う)
        print(f"  ⚪ 同じ日の既存の予定を読めなかった ({type(e).__name__}) = 重複は未確認")

    def when(b):   # 1 日の予定は開始だけ、 日をまたぐ予定は終わりも
        s, e = b["start"]["dateTime"], b["end"]["dateTime"]
        return s[:16] if last_day(s, e) == s[:10] else f"{s[:16]}〜{_md(e, s)} {e[11:16]}"

    if not a.apply:
        for b in bodies:
            print(f"  + {when(b)} {b['summary'][:66]}")
        print(f"\n(dry-run: {len(bodies)} 件。 --apply で実行)")
        return 0
    svc = get_service()
    cal = _cfg("CLAUDE_CALENDAR_ID")
    for b in bodies:
        ev = svc.events().insert(calendarId=cal, body=b).execute()
        print(f"  + {when(b)} {ev['id']}  {b['summary'][:52]}")
    return 0


def cmd_patch(a) -> int:
    svc = get_service()
    cal = _cfg("CLAUDE_CALENDAR_ID")
    tz = os.environ.get("CLAUDE_CALENDAR_TZ", "Asia/Tokyo")
    cur = svc.events().get(calendarId=cal, eventId=a.id).execute()
    rem = [int(x) for x in a.reminders.split(",")] if a.reminders else None
    body = build_patch_body(cur, tz, start=a.start, end=a.end, summary=a.summary,
                            append_description=a.append_description, reminders=rem)
    s0 = cur["start"].get("dateTime", cur["start"].get("date", ""))
    e0 = cur["end"].get("dateTime", cur["end"].get("date", ""))
    rng = f"{s0[:16]}-{e0[11:16]}" if last_day(s0, e0) == s0[:10] else format_when(s0, e0)
    print(f"  対象: {cur.get('summary', '')}  {rng}")
    for k, v in body.items():
        if k in ("start", "end"):
            print(f"  {k}: {cur.get(k, {}).get('dateTime', '')[:16]} → {v['dateTime'][:16]}")
        elif k == "reminders":
            print(f"  reminders → {[o['minutes'] for o in v['overrides']]}")
        elif k == "description":
            print(f"  description の末尾に追記: {a.append_description!r}")
        else:
            print(f"  {k}: {cur.get(k, '')!r} → {v!r}")
    if not a.apply:
        print("\n(dry-run。 --apply で実行)")
        return 0
    ev = svc.events().patch(calendarId=cal, eventId=a.id, body=body).execute()
    print(f"  ✅ patched {ev['id']}")
    return 0


def cmd_delete(a) -> int:
    svc = get_service()
    cal = _cfg("CLAUDE_CALENDAR_ID")
    items = fetch(svc, cal, a.frm[:10], a.to)
    kill, keep = select_for_delete(items, a.match, a.protect, a.frm if "T" in a.frm else None)
    print("=== 残すもの ===")
    for e, why in keep:
        print(f"  {span_head(e['start'], e['end']):>5}  {e['summary'][:56]}   [{why}]")
    print("\n=== 消すもの ===")
    for e in kill:     # 日をまたぐ予定は期間も出す (= 前の日から続く予定を消すと気づける)
        print(f"  {span_head(e['start'], e['end']):>5}  {e['summary'][:56]}")
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

    try:
        check_range("2030-01-10", "2030-01-10")
        check(False, "T20: 同じ日付の --from/--to は空の範囲としてエラー")
    except ValueError:
        check(True, "T20: 同じ日付の --from/--to は空の範囲としてエラー")
    try:
        check_range("2030-01-10T14:45", "2030-01-11")
        check_range("2030-01-10", "2030-01-11")
        check(True, "T21: 正しい範囲は通る (時刻つきと日付だけの混在も)")
    except ValueError:
        check(False, "T21: 正しい範囲は通る (時刻つきと日付だけの混在も)")

    cur = {"summary": "s", "description": "前の記録",
           "start": {"dateTime": "2030-01-10T12:30:00+09:00"},
           "end": {"dateTime": "2030-01-10T13:10:00+09:00"}}
    pb = build_patch_body(cur, "Asia/Tokyo", end="2030-01-10T13:00", append_description="追記")
    check(pb["end"]["dateTime"].startswith("2030-01-10T13:00") and "start" not in pb,
          "T22: patch は指定した欄だけ入れる")
    check(pb["description"] == "前の記録\n\n追記", "T23: 説明は置き換えず末尾に足す")
    try:
        build_patch_body(cur, "Asia/Tokyo", end="2030-01-10T12:00")
        check(False, "T24: 変更後の end <= start は ValueError")
    except ValueError:
        check(True, "T24: 変更後の end <= start は ValueError")
    try:
        build_patch_body(cur, "Asia/Tokyo")
        check(False, "T25: 指定なしの patch は ValueError")
    except ValueError:
        check(True, "T25: 指定なしの patch は ValueError")

    ex = [{"start": "2030-01-20", "summary": "式典 (学年暦)"}, {"start": "2030-01-20T09:00:00+09:00", "summary": "会議"},
          {"start": "2030-01-21", "summary": "別の日"}]
    hits = same_day_existing([{"start": "2030-01-20T10:00", "summary": "式典の手伝い"},
                              {"start": "2030-01-22T10:00", "summary": "空いている日"}], ex)
    check(len(hits) == 1 and hits[0][1] == ["終日 式典 (学年暦)", "09:00 会議"],
          "T26: add の前に同じ日の既存の予定 (終日と時刻つき) を並べる、 別の日と空いている日は出さない")

    # 複数日の予定 (実測: 開始日だけを出した一覧から、 期間の途中の日を空きとして人に出した)
    check(format_when("2030-01-10T09:00:00+09:00", "2030-01-10T10:30:00+09:00") == "2030-01-10 09:00-10:30",
          "T27: 1 日の時刻つきの予定の表示は変わらない")
    check(format_when("2030-01-10", "2030-01-11") == "2030-01-10    終日     ",
          "T28: 1 日の終日の予定の表示は変わらない")
    check(format_when("2030-01-07", "2030-01-12") == "2030-01-07〜01-11 終日",
          "T29: 複数日の終日の予定は終わりの日も出す (API の end は排他 = その前日が最後の日)")
    check(format_when("2030-01-10T22:00:00+09:00", "2030-01-11T02:00:00+09:00")
          == "2030-01-10 22:00〜01-11 02:00", "T30: 複数日の時刻つきの予定は終わりの日と時刻も出す")
    check(format_when("2030-01-10T22:00:00+09:00", "2030-01-11T00:00:00+09:00") == "2030-01-10 22:00-00:00",
          "T31: 翌日 0:00 ちょうどに終わる予定は 1 日の予定のまま")
    check(format_when("2030-12-30", "2031-01-03") == "2030-12-30〜2031-01-02 終日",
          "T32: 年をまたぐ予定は終わりの日に年も出す")
    check(event_days("2030-01-07", "2030-01-12")
          == ["2030-01-07", "2030-01-08", "2030-01-09", "2030-01-10", "2030-01-11"]
          and event_days("2030-01-10T22:00:00+09:00", "2030-01-11T00:00:00+09:00") == ["2030-01-10"],
          "T33: 予定が掛かる日 = 開始日から最後の日まで")
    ex2 = [{"start": "2030-01-07", "end": "2030-01-12", "summary": "集中の行事"},
           {"start": "2030-01-20T22:00:00+09:00", "end": "2030-01-21T02:00:00+09:00", "summary": "夜通しの作業"}]
    hits2 = same_day_existing([{"start": "2030-01-09T10:00", "end": "2030-01-09T11:00", "summary": "期間の途中"},
                               {"start": "2030-01-12T10:00", "end": "2030-01-12T11:00", "summary": "期間の翌日"},
                               {"start": "2030-01-21T09:00", "end": "2030-01-21T10:00", "summary": "翌朝"}], ex2)
    check([h[1] for h in hits2] == [["終日 01-07〜01-11 集中の行事"], ["01-20 22:00〜01-21 02:00 夜通しの作業"]],
          "T34: add の前の一覧は、 複数日の既存の予定を期間に入る日すべてで期間つきで出す (翌日には出さない)")
    hits3 = same_day_existing(
        [{"start": "2030-01-08T23:00", "end": "2030-01-09T01:00", "summary": "日をまたぐ"}],
        [{"start": "2030-01-09T09:00:00+09:00", "end": "2030-01-09T10:00:00+09:00", "summary": "翌日の会議"}])
    check(hits3 == [("2030-01-08〜01-09 日をまたぐ", ["01-09 09:00 翌日の会議"])],
          "T35: 足す予定が複数日なら、 掛かる日すべての既存の予定を日付つきで出す")
    busy, allday = day_busy([
        {"start": "2030-01-10T09:00:00+09:00", "end": "2030-01-12T12:00:00+09:00", "summary": "3 日の合宿"},
        {"start": "2030-01-20T22:00:00+09:00", "end": "2030-01-21T00:00:00+09:00", "summary": "夜"},
        {"start": "2030-01-07", "end": "2030-01-12", "summary": "集中の行事"}])
    check(busy.get("2030-01-10") == [(540, 1440)] and busy.get("2030-01-11") == [(0, 1440)]
          and busy.get("2030-01-12") == [(0, 720)] and compute_gaps(busy.get("2030-01-11", []), w) == [],
          "T36: gaps は複数日の時刻つきの予定を掛かる日すべてで busy にする (間の日は 1 日中)")
    check(busy.get("2030-01-20") == [(1320, 1440)] and "2030-01-21" not in busy,
          "T37: 翌日 0:00 に終わる予定は開始日の 24:00 まで busy、 翌日には掛けない")
    check(all(allday.get(d) == ["終日 01-07〜01-11 集中の行事"] for d in event_days("2030-01-07", "2030-01-12"))
          and "2030-01-09" not in busy,
          "T38: 終日の予定は busy に入れず、 掛かる日すべてに期間つきの見出しを出す")

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
    q = sub.add_parser("patch")
    q.add_argument("--id", required=True)
    q.add_argument("--start"); q.add_argument("--end"); q.add_argument("--summary")
    q.add_argument("--append-description", dest="append_description")
    q.add_argument("--reminders", help="分の list (例 0,15,60,120,1440)")
    q.add_argument("--apply", action="store_true")
    q = sub.add_parser("delete"); common(q)
    q.add_argument("--match"); q.add_argument("--protect")
    q.add_argument("--apply", action="store_true")

    a = p.parse_args()
    if a.selftest:
        return selftest()
    if not a.cmd:
        p.print_help()
        return 1
    if a.cmd in ("list", "gaps", "dups", "delete"):
        try:
            check_range(a.frm, a.to)
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2
    return {"list": cmd_list, "gaps": cmd_gaps, "dups": cmd_dups,
            "add": cmd_add, "patch": cmd_patch, "delete": cmd_delete}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
