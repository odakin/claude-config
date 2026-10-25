#!/usr/bin/env python3
"""calendar_conflicts.py — 予定の重なりを先に警告する engine (カレンダーの予定 + 枠表から作った占有の突き合わせ・「間に合うか」・承知済みの台帳・通知の段と記録・表示)。

一般則 = conventions/calendar-conflict-detection.md。 本 file は判定・台帳の読み方・通知の段・表示の正本で、
owner の枠表 (授業の時間割など) と学期の暦の読み方・予定の読み込み・台帳の置き場所・配線は持たない
(= 呼び元の adapter が provider と引数で渡す。 seam = conventions/script-layer-placement.md#engine-instance-seam)。

## adapter が渡すもの

- events: カレンダーの予定の list。 1 件 = {date: "YYYY-MM-DD", end_date: "YYYY-MM-DD", start: "HH:MM", end: "HH:MM",
  all_day, title, calendar, location}。 date = 開始日、 end_date = 最後の日 (その日を含む。 省略・読めない・date 以前なら
  date の 1 日)、 end = end_date の日の終了時刻。 終わりがちょうど 0:00 の予定は前の日を end_date にして渡す
- provider(d) -> (占有の list, 未チェックの理由の list): カレンダーに入っていない占有 (授業の時間割・当番表・定例の枠表) を
  その日について作る関数。 占有 = {kind: "slot", start: 分, end: 分, title, name, calendar, location}。
  name = 枠の実体の名前 (科目名など)。 予定の題名に name の頭の語が入っていれば同じもの (自己一致) として重ねない。
  暦の型 (学期・休暇・補講の時限・時刻のずれる週) の解釈は provider の側。 枠表や暦が読めない日は占有を返さず
  理由を返す (= 黙って「枠なし」 にしない、 一般則 #occupancy-outside-calendar)
- ledger: load_ledger(path) で読んだ台帳 (形は下)
- oncampus_re: 「間に合うか」 で学内・オンラインとみなす場所の正規表現。 既定 = 先頭が番号の「N 号館」・研究室・
  オンライン会議の語・URL。 所属機関の名前は adapter が足した正規表現を渡す
- text: 表示の語 {scope: 見出しの括弧の中, ack_where: 台帳の場所の案内, slot_word: 枠の呼び名}

## 判定 (detect、 既定 7 日先まで = 今日を含む days + 1 日)

- 占有 = provider の枠 + 時刻のある予定。 予定のうち数えないもの = 終日 / 1 日の予定で開始と終了が同じ (目印) /
  台帳の ignore_titles に当たる題名。 同じ日時・題名の予定が複数のカレンダーにあれば 1 つに数える。 「〜へ移動」 (乗換案内から
  入る移動の予定) も占有 (kind = travel)。 複数日の予定 (end_date が date より後) は期間に入る日すべての占有 = 開始日は
  開始時刻から 24:00、 間の日は 1 日中、 最後の日は 0:00 から終了時刻 (開始と終了が同じ時刻でも目印にしない)。 表示は期間
  (`span`)。 end_date の無い予定で終了が開始より前のもの (古い写し) はその日の 24:00 まで
- ⚠️ 重なり = 2 つの占有が 1 分でも重なる (終わり = 次の始まりは重ならない)。 枠どうしは見ない。 枠と自己一致の予定は見ない
- ⏱ 間に合うか = 場所が学外 (location があり oncampus_re に当たらない) の予定と、 直前・直後の枠の間が tight_min (既定 30) 分
  未満で、 その間に移動の予定が無いもの。 重なりとは別の段 (通知しない)
- now を渡すと、 今日の組のうち両方とも終わったもの (遅い方の終了 ≤ 今) は出さない

## 台帳 (YAML、 置き場所は adapter が決める)

    ignore_titles: ["^🔔"]           # 時間を取らない予定の題名 (正規表現)。 足すのは時間を取らないと確かめたものだけ
    ack:
      - date: "YYYY-MM-DD"
        until: "YYYY-MM-DD"          # 省略可 = その日だけ。 毎週の組を意図して重ねるなら期間の終わりを必ず書く
        a: "組の片方の題名の一部"
        b: "もう片方の題名の一部"
        reason: "YYYY-MM-DD 理由"     # 日付つきの理由の無い行は効かない (invalid に出す = 見て決めた記録だけ)

承知済みの組は通知せず一覧からも外す。 ただし当日の一覧には「(承知済み: 理由)」 付きで出す。

## 通知 (post_notifications)

- 段 = d3 (残り 2-3 日) / d1 (残り 0-1 日)。 記録の鍵 = 段 + 日付 + 組 = 同じ段は 1 回、 段が変われば 1 回ずつ。 承知済みは出さない
- 投稿は notifier (通知の唯一の入口、 層1 claude-notify.sh 等) に `--title --body --sound` で渡す。 題名のタブ・改行は入口が潰す
- 記録 = state_path の JSON (鍵 → 日付)。 14 日より古い鍵は消す。 投稿に失敗したら記録しない (= 次の run で再試行)
- 夜の時間帯 (in_quiet) に呼ばない・記録しないのは呼び元の責務 (受け手ごとの間隔 daemon から呼ぶ、 一般則 #notification-timing)

usage:
    python3 calendar_conflicts.py --selftest
    python3 calendar_conflicts.py --list --events EVENTS.json [--ack ACK.yaml] [--days 7] [--today YYYY-MM-DD]
        (枠表なし = 予定どうしの重なりだけ。 枠表を足すのは adapter)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

WINDOW_D = 7
TIGHT_MIN = 30
WEEKDAY_JA = "月火水木金土日"
TRAVEL_RE = re.compile(r"へ移動\s*$")
# 学内・オンラインの場所 (= 「間に合うか」 の対象外)。 他大学の「〜キャンパス 理学部1号館」 は学外 = 号館は先頭が番号のとき
# (= 学内の「6号館 6111 教室」 の形) だけ学内に数える。 所属機関の名前は adapter が足す
ONCAMPUS_RE = re.compile(r"^\s*[0-9０-９]+\s*号館|研究室|zoom|オンライン|online|teams|meet\.google|webex|https?://",
                         re.IGNORECASE)
REASON_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\S")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEXT = {"scope": "枠表 + 全カレンダー", "ack_where": "台帳", "slot_word": "枠"}

Provider = Callable[[date], "tuple[list[dict], list[str]]"]


def empty_ledger() -> dict:
    return {"ack": [], "ignore": [], "invalid": []}


# ---------------------------------------------------------------------------
# 時刻 / 台帳
# ---------------------------------------------------------------------------
def mins(s) -> int | None:
    try:
        h, m = str(s).strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return None


def hhmm(m: int) -> str:
    return f"{m // 60}:{m % 60:02d}"


def _yaml_load(path: Path):
    import yaml  # 遅延 import = yaml の無い python でも module の import は通す (呼び元は fail-open)
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def load_ledger(path: Path) -> dict:
    """台帳 = {"ack": [...有効な entry], "ignore": [compiled re], "invalid": [効かない entry の説明]}。 無ければ空。"""
    out = empty_ledger()
    p = Path(path)
    try:
        data = _yaml_load(p) if p.exists() else None
    except Exception as ex:
        out["invalid"].append(f"台帳を読めない ({type(ex).__name__})")
        return out
    if not isinstance(data, dict):
        return out
    for pat in data.get("ignore_titles") or []:
        try:
            out["ignore"].append(re.compile(str(pat)))
        except re.error:
            out["invalid"].append(f"ignore_titles の正規表現が壊れている: {pat}")
    for e in data.get("ack") or []:
        if not isinstance(e, dict):
            continue
        try:
            d0 = date.fromisoformat(str(e.get("date", "")))
            d1 = date.fromisoformat(str(e["until"])) if e.get("until") else d0
        except Exception:
            out["invalid"].append(f"ack の日付が読めない: {e}")
            continue
        a, b, reason = str(e.get("a") or "").strip(), str(e.get("b") or "").strip(), str(e.get("reason") or "").strip()
        if not (a and b and REASON_RE.match(reason)):
            out["invalid"].append(f"ack に a・b・「YYYY-MM-DD 理由」 が揃っていない: {d0} {a} × {b}")
            continue
        out["ack"].append({"from": d0, "until": d1, "a": a, "b": b, "reason": reason})
    return out


# ---------------------------------------------------------------------------
# カレンダーの占有
# ---------------------------------------------------------------------------
def event_last_day(e: dict) -> str:
    """予定が掛かる最後の日 ('YYYY-MM-DD')。 end_date が無い・読めない・date 以前なら date (= 1 日の予定)。"""
    d0 = str(e.get("date", ""))[:10]
    d1 = str(e.get("end_date") or "")[:10]
    return d1 if DATE_RE.match(d1) and d1 > d0 else d0


def _md_label(iso: str) -> str:
    return f"{int(iso[5:7])}/{int(iso[8:10])}"


def event_occupancies(events: list[dict], d: date, ignore: list | None = None, travel_re=TRAVEL_RE) -> list[dict]:
    iso = d.isoformat()
    seen: set = set()
    out: list[dict] = []
    for e in events:
        d0, d1 = str(e.get("date", ""))[:10], event_last_day(e)
        if not (d0 <= iso <= d1) or e.get("all_day"):
            continue
        s, en = mins(e.get("start")), mins(e.get("end"))
        if s is None or en is None:
            continue  # 終日相当
        span = ""
        if d1 == d0:
            if s == en:
                continue  # 目印 (1 日の予定で開始 = 終了)
            if en < s:
                en = 24 * 60  # end_date の無い古い写しの日をまたぐ予定はその日の終わりまで
        else:
            # 複数日の予定 = 開始日は開始時刻から、 最後の日は終了時刻まで、 間の日は 1 日中
            span = f"{_md_label(d0)} {hhmm(s)}〜{_md_label(d1)} {hhmm(en)}"
            s, en = (s if iso == d0 else 0), (en if iso == d1 else 24 * 60)
            if en <= s:
                continue  # その日に掛かる時間が無い (最後の日の 0:00 ちょうどに終わる、 整えていない写し)
        title = str(e.get("title") or "").strip()
        if any(r.search(title) for r in (ignore or [])):
            continue
        key = (s, en, title)
        if key in seen:
            continue  # 同じ予定が複数のカレンダーにある
        seen.add(key)
        occ = {"kind": "travel" if travel_re.search(title) else "event", "start": s, "end": en,
               "title": title, "calendar": str(e.get("calendar") or ""), "location": str(e.get("location") or "")}
        if span:
            occ["span"] = span
        out.append(occ)
    return out


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def name_core(name: str) -> str:
    """枠の名前の頭の語 (空白・括弧の前まで) = 予定の題名に入っていれば同じもの。"""
    return re.split(r"[\s(（]", str(name).strip(), maxsplit=1)[0]


def same_thing(a: dict, b: dict) -> bool:
    """枠と、 その枠自身のカレンダーの予定 (= 枠の名前が題名に入っている) は重なりにしない。"""
    for c, e in ((a, b), (b, a)):
        if c["kind"] == "slot" and e["kind"] != "slot":
            core = name_core(c.get("name") or "")
            if core and core in e["title"]:
                return True
    return False


def pair_key(iso: str, a: dict, b: dict) -> str:
    sig = sorted(f"{hhmm(x['start'])}-{hhmm(x['end'])} {x['title']}" for x in (a, b))
    return f"{iso}|{sig[0]}|{sig[1]}"


def ack_for(acks: list[dict], d: date, a: dict, b: dict) -> str | None:
    for k in acks:
        if not (k["from"] <= d <= k["until"]):
            continue
        ta, tb = a["title"], b["title"]
        if (k["a"] in ta and k["b"] in tb) or (k["a"] in tb and k["b"] in ta):
            return k["reason"]
    return None


def detect(events: list[dict], today: date, days: int | None = None, provider: Provider | None = None,
           ledger: dict | None = None, now: datetime | None = None, oncampus_re=None,
           tight_min: int | None = None, travel_re=None) -> dict:
    """今日から days 日先まで (今日を含む) の重なりと「間に合うか」。 純粋 (入力は引数と provider だけ)。"""
    days = WINDOW_D if days is None else days
    tight_min = TIGHT_MIN if tight_min is None else tight_min
    oncampus_re = oncampus_re or ONCAMPUS_RE
    ledger = ledger if ledger is not None else empty_ledger()
    acks = ledger.get("ack") or []
    res: dict = {"conflicts": [], "tight": [], "notes": [], "days": days, "tight_min": tight_min}
    now_min = now.hour * 60 + now.minute if now is not None else None
    now_d = now.date() if now is not None else None
    seen_notes: set = set()
    for i in range(days + 1):
        d = today + timedelta(days=i)
        iso = d.isoformat()
        slots, notes = provider(d) if provider else ([], [])
        for n in notes:
            if n not in seen_notes:
                seen_notes.add(n)
                res["notes"].append(n)
        evs = event_occupancies(events, d, ledger.get("ignore"), travel_re or TRAVEL_RE)
        occ = sorted(list(slots) + evs, key=lambda x: (x["start"], x["end"]))
        for x in range(len(occ)):
            for y in range(x + 1, len(occ)):
                a, b = occ[x], occ[y]
                if not (a["start"] < b["end"] and b["start"] < a["end"]):
                    continue
                if a["kind"] == "slot" and b["kind"] == "slot":
                    continue
                if same_thing(a, b):
                    continue
                if now_min is not None and d == now_d and max(a["end"], b["end"]) <= now_min:
                    continue
                res["conflicts"].append({"date": iso, "a": a, "b": b, "key": pair_key(iso, a, b),
                                         "ack": ack_for(acks, d, a, b)})
        travels = [o for o in evs if o["kind"] == "travel"]
        offsite = [o for o in evs if o["kind"] == "event" and o["location"] and not oncampus_re.search(o["location"])]
        for c in slots:
            for e in offsite:
                if e["start"] >= c["end"]:
                    gap = e["start"] - c["end"]
                    moved = any(c["start"] <= t["start"] <= e["start"] for t in travels)
                    order = (c, e)
                elif e["end"] <= c["start"]:
                    gap = c["start"] - e["end"]
                    moved = any(e["end"] - tight_min <= t["start"] <= c["start"] for t in travels)
                    order = (e, c)
                else:
                    continue  # 重なりは上の段
                if now_min is not None and d == now_d and order[1]["end"] <= now_min:
                    continue
                if gap < tight_min and not moved:
                    res["tight"].append({"date": iso, "first": order[0], "second": order[1], "gap": gap,
                                         "key": pair_key(iso, order[0], order[1]) + "|tight",
                                         "ack": ack_for(acks, d, order[0], order[1])})
    return res


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------
def day_label(iso: str, today: date) -> str:
    d = date.fromisoformat(iso)
    wd = WEEKDAY_JA[d.weekday()]
    if d == today:
        return f"今日 {d.month}/{d.day}({wd})"
    if d == today + timedelta(days=1):
        return f"明日 {d.month}/{d.day}({wd})"
    return f"{d.month}/{d.day}({wd})"


def occ_label(o: dict, cal: bool = True, limit: int = 32) -> str:
    """占有の 1 行。 複数日の予定はその日の部分でなく期間を出す (= 「0:00-24:00 会期」 では何の予定か読めない)。"""
    t = o["title"] if len(o["title"]) <= limit else o["title"][:limit] + "…"
    tail = f" [{o['calendar']}]" if cal and o["kind"] != "slot" and o.get("calendar") else ""
    return f"{o.get('span') or hhmm(o['start']) + '-' + hhmm(o['end'])} {t}{tail}"


def visible(item: dict, today: date) -> bool:
    """承知済みは当日だけ出す。"""
    return not item.get("ack") or item["date"] == today.isoformat()


def render_section(res: dict, today: date, text: dict | None = None) -> list[str]:
    """予定の一覧 (session 開始・dashboard) に足す段。 出すものが無ければ []。"""
    tx = dict(TEXT, **(text or {}))
    conf = [c for c in res.get("conflicts", []) if visible(c, today)]
    tight = [t for t in res.get("tight", []) if visible(t, today)]
    lines: list[str] = []
    if conf:
        lines.append(f"⚠️ 予定の重なり {len(conf)} 組 ({tx['scope']}、 {res.get('days', WINDOW_D)} 日先まで):")
        for c in conf:
            ack = f"  (承知済み: {c['ack']})" if c.get("ack") else ""
            lines.append(f"   {day_label(c['date'], today)} {occ_label(c['a'])} × {occ_label(c['b'])}{ack}")
        lines.append(f"   → どちらかを動かす / 連絡する。 承知の上なら {tx['ack_where']} に"
                     " 日付・予定の組・「YYYY-MM-DD 理由」 (通知が止まる。 当日の一覧には出る)")
    if tight:
        lines.append(f"⏱ 間に合うか {len(tight)} 件 (学外の予定と{tx['slot_word']}の間が {res.get('tight_min', TIGHT_MIN)}"
                     " 分未満・移動の予定なし):")
        for t in tight:
            ack = f"  (承知済み: {t['ack']})" if t.get("ack") else ""
            loc = f" (場所: {t['first']['location'] or t['second']['location']})"[:40]
            lines.append(f"   {day_label(t['date'], today)} {occ_label(t['first'])} → {occ_label(t['second'])}"
                         f" = 間 {t['gap']} 分{loc}{ack}")
    for n in res.get("notes", []):
        lines.append(f"⚠️ 予定の重なり: {n}")
    return lines


def digest_rows(res: dict, today: date) -> list[str]:
    """session 開始の 1 ブロック (畳んだ注入) 用の行 (1 組 1 行、 見出しだけ、 字下げ 2)。

    未承知で 2 日以内の組は 🚨 (= 最初の返答で伝える印)、 それ以外は ⚠️。
    """
    rows = []
    for c in res.get("conflicts", []):
        if not visible(c, today):
            continue
        ack = " (承知済み)" if c.get("ack") else ""
        icon = "🚨" if not c.get("ack") and (date.fromisoformat(c["date"]) - today).days <= 2 else "⚠️"
        rows.append(f"  {icon} {day_label(c['date'], today)} 予定の重なり: {occ_label(c['a'], cal=False, limit=24)}"
                    f" × {occ_label(c['b'], cal=False, limit=24)}{ack}")
    for t in res.get("tight", []):
        if not visible(t, today):
            continue
        rows.append(f"  ⏱ {day_label(t['date'], today)} 間に合うか: {occ_label(t['first'], cal=False, limit=24)}"
                    f" → {occ_label(t['second'], cal=False, limit=24)} (間 {t['gap']} 分・移動の予定なし)")
    for n in res.get("notes", []):
        rows.append(f"  ⚠️ 予定の重なりは未チェック: {n}")
    return rows


def list_lines(res: dict, today: date, source: str, invalid: list[str] | None = None) -> list[str]:
    """--list の出力 (承知済みも、 今日の終わった組も含む全部)。"""
    out = [f"予定の重なり: {today} から {res.get('days', WINDOW_D)} 日先まで ({source}。 今日の終わった組も含む)",
           f"  重なり {len(res['conflicts'])} 組 (うち承知済み {sum(1 for c in res['conflicts'] if c.get('ack'))})"
           f" / 間に合うか {len(res['tight'])} 件"]
    for c in res["conflicts"]:
        ack = f"  (承知済み: {c['ack']})" if c.get("ack") else ""
        out.append(f"  ⚠️ {day_label(c['date'], today)} {occ_label(c['a'])} × {occ_label(c['b'])}{ack}")
    for t in res["tight"]:
        out.append(f"  ⏱ {day_label(t['date'], today)} {occ_label(t['first'])} → {occ_label(t['second'])} = 間 {t['gap']} 分")
    for n in list(res["notes"]) + list(invalid or []):
        out.append(f"  ⚠️ {n}")
    return out


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------
def notify_stage(iso: str, today: date) -> str | None:
    """3 日前 (残り 2-3 日) = d3 / 前日 (残り 0-1 日) = d1。 それ以外は通知しない。"""
    delta = (date.fromisoformat(iso) - today).days
    if 2 <= delta <= 3:
        return "d3"
    if 0 <= delta <= 1:
        return "d1"
    return None


def notify_targets(res: dict, today: date, state: dict) -> list[tuple[str, dict]]:
    """純関数: 通知する (記録の鍵, 重なり)。 承知済みは出さない。 同じ (段, 組) は 1 回。"""
    out = []
    for c in res.get("conflicts", []):
        if c.get("ack"):
            continue
        st = notify_stage(c["date"], today)
        if st is None:
            continue
        k = f"{st}|{c['key']}"
        if k in state:
            continue
        out.append((k, c))
    return out


def in_quiet(now: datetime, start: int = 22, end: int = 7) -> bool:
    """夜の時間帯 (start 時〜end 時、 日をまたいでよい) か。"""
    h = now.hour
    return (start <= h < end) if start < end else (h >= start or h < end)


def post_notifications(res: dict, today: date, state_path: Path, notifier: Path | str, dry: bool = False,
                       sound: str = "Basso") -> int:
    """まだ出していない段の重なりを 1 通にまとめて notifier に渡し、 記録する。 出した組の数を返す (dry は記録しない)。"""
    sp = Path(state_path)
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
        state = state if isinstance(state, dict) else {}
    except Exception:
        state = {}
    fresh = notify_targets(res, today, state)
    if not fresh:
        return 0
    head = fresh[0][1]
    dates = sorted({c["date"] for _, c in fresh})
    title = f"⚠️ 予定の重なり {len(fresh)} 組 ({' / '.join(day_label(x, today) for x in dates)})"
    body = (f"{day_label(head['date'], today)} {occ_label(head['a'], cal=False, limit=20)}"
            f" × {occ_label(head['b'], cal=False, limit=20)}")
    if len(fresh) > 1:
        body += f" 他 {len(fresh) - 1} 組"
    if dry:
        print(f"[dry-run] {title}\n[dry-run] {body}")
        return 0
    try:
        subprocess.run(["sh", str(notifier), "--title", title, "--body", body, "--sound", sound],
                       timeout=30, check=False, capture_output=True)
    except Exception:
        return 0  # 記録しない = 次の run で再試行
    for k, c in fresh:
        state[k] = c["date"]
    cutoff = (today - timedelta(days=14)).isoformat()
    state = {k: v for k, v in state.items() if str(v) >= cutoff}
    try:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    print(f"calendar-conflicts: {len(fresh)} 組を通知")
    return len(fresh)


# ---------------------------------------------------------------------------
# CLI (枠表なし = 予定どうしの重なりだけ。 枠表を足すのは adapter)
# ---------------------------------------------------------------------------
def _arg(argv: list[str], name: str) -> str | None:
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    if "--list" not in argv or not _arg(argv, "--events"):
        print(__doc__.split("usage:")[1].rstrip(), file=sys.stderr)
        return 2
    ev_path = Path(_arg(argv, "--events") or "")
    events = json.loads(ev_path.read_text(encoding="utf-8"))
    ledger = load_ledger(Path(_arg(argv, "--ack"))) if _arg(argv, "--ack") else empty_ledger()
    today = date.fromisoformat(_arg(argv, "--today")) if _arg(argv, "--today") else date.today()
    days = int(_arg(argv, "--days") or WINDOW_D)
    res = detect(events, today, days=days, ledger=ledger)
    print("\n".join(list_lines(res, today, str(ev_path.name), ledger["invalid"])))
    return 0


# ---------------------------------------------------------------------------
# selftest (合成の予定と枠表。 実在の時間割・暦・カレンダーは読まない)
# ---------------------------------------------------------------------------
def _selftest() -> int:
    import tempfile
    npass = nfail = 0

    def check(cond: bool, label: str) -> None:
        nonlocal npass, nfail
        if cond:
            npass += 1
            print(f"[PASS] {label}")
        else:
            nfail += 1
            print(f"[FAIL] {label}")

    # 枠表 = 曜日 → (開始, 終了, 名前)。 休業日は枠なし、 枠表の無い日は理由を返す (provider の契約)
    table = {"水": [("09:00", "10:30", "科目甲 (演習)")],
             "金": [("09:00", "10:30", "科目乙"), ("10:55", "12:25", "科目丙"), ("10:00", "11:00", "科目丁")]}
    holidays = {date(2030, 10, 4)}   # 金曜の休業日
    no_table = {date(2030, 9, 30), date(2030, 10, 1)}   # 枠表の無い日 (窓の中に 2 日 = 理由は 1 回だけ持つ)

    def provider(d: date):
        if d in no_table:
            return [], ["枠表が無い日 = その日の枠との重なりは未チェック"]
        if d in holidays:
            return [], []
        wd = WEEKDAY_JA[d.weekday()]
        return [{"kind": "slot", "start": mins(s), "end": mins(e), "title": f"枠「{n}」{wd}", "name": n,
                 "calendar": "枠表", "location": ""} for s, e, n in table.get(wd, [])], []

    E = lambda d, s, e, t, cal="カレンダー甲", **k: dict(date=d, start=s, end=e, title=t, calendar=cal, all_day=False, **k)  # noqa: E731
    today = date(2030, 9, 24)   # 火曜
    events = [
        E("2030-09-25", "09:00", "10:30", "定例の会", "カレンダー乙"),
        E("2030-09-25", "10:03", "10:59", "病院 へ移動", location="バス停"),
        E("2030-09-25", "10:30", "12:00", "外の用事"),
        dict(date="2030-09-25", all_day=True, title="終日の予定", calendar="カレンダー丙"),
        dict(date="2030-09-25", all_day=True, start="00:00", end="23:59", title="時刻つきの終日の予定", calendar="カレンダー丙"),
        E("2030-09-25", "18:00", "22:00", "同じ予定", "カレンダー甲"),
        E("2030-09-25", "18:00", "22:00", "同じ予定", "カレンダー乙"),
        E("2030-09-26", "09:00", "09:30", "🔔 確認のリマインダー"),
        E("2030-09-26", "09:00", "09:30", "🔔 別のリマインダー"),
        E("2030-09-26", "16:00", "16:00", "目印 (開始=終了)"),
        E("2030-09-26", "15:00", "17:00", "午後の会議"),   # 目印を内側に含む予定 (= 目印を数えると重なる)
        E("2030-09-27", "09:30", "10:15", "科目乙 (配信)", "授業のカレンダー"),
    ]
    ledger = {"ack": [], "ignore": [re.compile(r"^🔔")], "invalid": []}
    res = detect(events, today, days=7, provider=provider, ledger=ledger)
    blob = lambda c: c["a"]["title"] + " / " + c["b"]["title"]  # noqa: E731
    check(any(c["date"] == "2030-09-25" and "枠「科目甲" in blob(c) and "定例の会" in blob(c) for c in res["conflicts"]),
          "T1 枠 × 毎週の予定を拾う")
    check(any(c["date"] == "2030-09-25" and "へ移動" in blob(c) and "枠「" in blob(c) for c in res["conflicts"]),
          "T2 移動の予定も占有 (枠 × 移動)")
    check(any("外の用事" in blob(c) and "へ移動" in blob(c) for c in res["conflicts"]), "T3 予定 × 予定 (移動 × 外の用事)")
    check(not any("外の用事" in blob(c) and "枠「" in blob(c) for c in res["conflicts"]),
          "T4 終わり 10:30 × 始まり 10:30 は重ならない")
    check(not any("終日" in blob(c) for c in res["conflicts"]), "T5 終日の予定は数えない")
    check(not any(c["a"]["title"] == c["b"]["title"] == "同じ予定" for c in res["conflicts"]),
          "T6 同じ日時・題名の予定は複数のカレンダーにあっても 1 つ")
    check(not any("リマインダー" in blob(c) for c in res["conflicts"]), "T7 台帳の ignore_titles に当たる予定は数えない")
    check(not any("目印" in blob(c) for c in res["conflicts"]), "T8 開始 = 終了の目印は数えない")
    check(not any("科目乙 (配信)" in blob(c) and "枠「科目乙" in blob(c) for c in res["conflicts"]),
          "T9 枠と、 その枠の名前が題名に入った予定は重ねない (自己一致)")
    check(any("科目乙 (配信)" in blob(c) and "枠「科目丁" in blob(c) for c in res["conflicts"]),
          "T9 自己一致は自分の枠とだけ (別の枠とは重なる)")
    check(not any(c["a"]["kind"] == "slot" and c["b"]["kind"] == "slot" for c in res["conflicts"]),
          "T10 枠どうしは見ない")
    fri = [E("2030-10-04", "09:00", "10:00", "金曜の会議"), E("2030-10-11", "09:00", "10:00", "金曜の会議")]
    res_h = detect(fri, date(2030, 10, 3), days=8, provider=provider, ledger=ledger)
    check(not any(c["date"] == "2030-10-04" for c in res_h["conflicts"])
          and any(c["date"] == "2030-10-11" for c in res_h["conflicts"]),
          "T10 provider が枠を返さない日 (休業日) は枠の占有なし、 次の週の同じ曜日は重なる")
    check(res["notes"] == ["枠表が無い日 = その日の枠との重なりは未チェック"], "T11 provider の未チェックの理由を 1 回だけ持つ")
    check(any("未チェック" in ln for ln in render_section(res, today)) and any("未チェック" in r for r in digest_rows(res, today)),
          "T11 未チェックの理由は段にも digest にも出る (黙らない)")

    # 間に合うか
    t_events = [E("2030-09-25", "10:35", "11:30", "他大学の会議", location="〜キャンパス 理学部1号館"),
                E("2030-09-25", "10:40", "11:00", "学内の打合せ", location="6号館 6111 教室"),
                E("2030-09-27", "12:40", "13:30", "学外の昼食", location="駅前の店"),
                E("2030-09-27", "08:00", "08:50", "朝の用事", location="隣町"),
                E("2030-09-27", "08:50", "08:58", "職場 へ移動")]
    tr = detect(t_events, today, days=7, provider=provider, ledger=ledger)
    check(any(t["date"] == "2030-09-27" and "学外の昼食" in t["second"]["title"] and t["gap"] == 15 for t in tr["tight"]),
          "T12 学外の予定と直前の枠の間 15 分・移動なし = 間に合うか")
    check(any("理学部1号館" in t["second"]["location"] and t["gap"] == 5 for t in tr["tight"]),
          "T12 他大学の「〜キャンパス N 号館」 (号館が先頭でない) は学外")
    check(not any("6号館" in (t["first"]["location"] + t["second"]["location"]) for t in tr["tight"]),
          "T12 先頭が「N 号館」 の場所は学内 = 対象外")
    check(not any("朝の用事" in t["first"]["title"] for t in tr["tight"]), "T12 間に移動の予定があれば出さない")
    tr2 = detect(t_events, today, days=7, provider=provider, ledger=ledger,
                 oncampus_re=re.compile(ONCAMPUS_RE.pattern + "|駅前", re.IGNORECASE))
    check(not any("学外の昼食" in t["second"]["title"] for t in tr2["tight"]),
          "T13 adapter が渡す oncampus_re の語は学内として扱う")

    # 承知済み
    ack_led = dict(ledger, ack=[{"from": date(2030, 9, 25), "until": date(2030, 9, 25), "a": "科目甲",
                                 "b": "へ移動", "reason": "2030-09-24 早退の連絡済み"}])
    res_a = detect(events, today, days=7, provider=provider, ledger=ack_led)
    acked = [c for c in res_a["conflicts"] if c.get("ack")]
    check(len(acked) == 1 and "へ移動" in blob(acked[0]), "T14 台帳の ack が組に当たる (題名の一部 × 一部、 順不同)")
    check(any("承知済み" in ln for ln in render_section(res_a, date(2030, 9, 25))), "T14 承知済みでも当日の段には出す")
    check(not any("承知済み" in ln for ln in render_section(res_a, today)), "T14 承知済みは当日以外の段から外す")
    check(bool(acked) and all(k[1]["key"] != acked[0]["key"] for k in notify_targets(res_a, today, {})),
          "T14 承知済みは通知しない")

    # 通知の段と記録
    check(notify_stage("2030-09-27", today) == "d3" and notify_stage("2030-09-26", today) == "d3"
          and notify_stage("2030-09-25", today) == "d1" and notify_stage("2030-09-28", today) is None,
          "T15 残り 2-3 日 = d3 / 0-1 日 = d1 / 4 日以上は通知しない")
    tg = notify_targets(res, today, {})
    check(bool(tg) and all(k.startswith("d1|2030-09-25") or k.startswith("d3|2030-09-27") for k, _ in tg),
          "T15 段の鍵 = 段 + 日付 + 組")
    st = {k: c["date"] for k, c in tg}
    check(notify_targets(res, today, st) == [], "T16 同じ (段, 組) は 2 回通知しない")
    res_d3 = detect(events, date(2030, 9, 22), days=7, provider=provider, ledger=ledger)
    st3 = {k: c["date"] for k, c in notify_targets(res_d3, date(2030, 9, 22), {})}
    check(bool(st3) and all(k.startswith("d3|") for k in st3), "T16 3 日前の run は d3 の段")
    check(notify_targets(res_d3, date(2030, 9, 23), st3) == [], "T16 残り 2 日の run は d3 を出し済みなので出ない")
    res_d1 = detect(events, today, days=7, provider=provider, ledger=ledger)
    check(len([k for k, c in notify_targets(res_d1, today, st3) if c["date"] == "2030-09-25"])
          == len([k for k in st3 if "2030-09-25" in k]), "T16 前日の run は d1 の段でもう 1 回ずつ")
    check(in_quiet(datetime(2030, 9, 24, 23, 0)) and in_quiet(datetime(2030, 9, 25, 6, 59))
          and not in_quiet(datetime(2030, 9, 25, 7, 0)) and not in_quiet(datetime(2030, 9, 24, 21, 59)),
          "T17 既定の夜 22:00-07:00 (日をまたぐ)")
    check(in_quiet(datetime(2030, 9, 24, 1, 0), 0, 6) and not in_quiet(datetime(2030, 9, 24, 6, 0), 0, 6),
          "T17 日をまたがない夜の時間帯も読む")

    # 今日の終わった組
    res_now = detect(events, date(2030, 9, 25), days=0, provider=provider, ledger=ledger, now=datetime(2030, 9, 25, 11, 0))
    check(bool(res_now["conflicts"]) and all("外の用事" in blob(c) for c in res_now["conflicts"]),
          "T18 now を渡すと両方とも終わった組は出さず、 まだ続く組は出す")

    # 表示
    sec = render_section(res, today)
    check(sec and sec[0].startswith("⚠️ 予定の重なり") and "枠表 + 全カレンダー" in sec[0], "T19 段の見出しと既定の語")
    check(render_section({"conflicts": [], "tight": [], "notes": []}, today) == [], "T19 無ければ無音")
    sec_t = render_section(res, today, {"scope": "時間割 + 全カレンダー", "ack_where": "某/台帳.yaml"})
    check(sec_t[0].endswith("(時間割 + 全カレンダー、 7 日先まで):") and any("承知の上なら 某/台帳.yaml に" in ln for ln in sec_t),
          "T19 表示の語は adapter が差し替えられる")
    sec_tight = render_section(tr, today, {"slot_word": "授業"})
    check(any(ln.startswith("⏱ 間に合うか") and "学外の予定と授業の間が 30 分未満" in ln for ln in sec_tight),
          "T19 間に合うかの段に枠の呼び名と分数")
    check(not any("[枠表]" in ln for ln in sec) and any("[カレンダー乙]" in ln for ln in sec),
          "T19 枠の占有にはカレンダー名を付けない (予定には付ける)")
    rows = digest_rows(res, today)
    near = [r for r in rows if "予定の重なり:" in r and "9/25" in r]
    far = [r for r in rows if "予定の重なり:" in r and "9/27" in r]
    check(bool(near) and all(r.startswith("  🚨 ") for r in near), "T20 digest: 未承知で 2 日以内の組は 🚨")
    check(bool(far) and all(r.startswith("  ⚠️ ") for r in far), "T20 digest: 3 日以上先 (9/27) の組は ⚠️")
    rows_2 = digest_rows(detect(events, date(2030, 9, 23), days=7, provider=provider, ledger=ledger), date(2030, 9, 23))
    check(any(r.startswith("  🚨 ") and "9/25" in r for r in rows_2), "T20 digest: 残り 2 日の組も 🚨")
    rows_ack = digest_rows(res_a, date(2030, 9, 25))
    check(any(r.startswith("  ⚠️ ") and "(承知済み)" in r for r in rows_ack), "T20 digest: 当日の承知済みは ⚠️ + (承知済み)")
    ll = list_lines(res_a, today, "fixture", ["台帳の行が効かない"])
    check(ll[0].startswith("予定の重なり: 2030-09-24 から 7 日先まで (fixture。") and "(うち承知済み 1)" in ll[1]
          and ll[-1] == "  ⚠️ 台帳の行が効かない", "T23 --list の行 (承知済みも・台帳の無効行も)")

    # 複数日の予定 (end_date = 最後の日、 その日を含む)
    m_events = [
        E("2030-09-25", "18:00", "09:30", "学外の会期", end_date="2030-09-27"),
        E("2030-09-26", "15:00", "17:00", "木曜の会議"),
        E("2030-10-01", "10:00", "10:00", "同じ時刻の 2 日", end_date="2030-10-02"),
        E("2030-09-25", "22:00", "02:00", "日をまたぐ古い写し"),   # end_date なし = その日の 24:00 まで (従来どおり)
        dict(date="2030-09-25", end_date="2030-09-27", all_day=True, title="終日の会期", calendar="カレンダー丙"),
    ]
    res_m = detect(m_events, today, days=8, provider=provider, ledger=ledger)
    on = lambda iso, *words: any(c["date"] == iso and all(w in blob(c) for w in words) for c in res_m["conflicts"])  # noqa: E731
    check(on("2030-09-27", "学外の会期", "枠「科目乙"), "T24 複数日の予定の最後の日 (0:00-9:30) が枠と重なる")
    check(on("2030-09-26", "学外の会期", "木曜の会議"), "T24 複数日の予定の間の日は 1 日中の占有")
    check(on("2030-10-02", "同じ時刻の 2 日", "枠「科目甲"), "T24 開始と終了が同じ時刻の複数日の予定は目印にしない")
    check(on("2030-09-25", "学外の会期", "日をまたぐ古い写し")
          and not any("日をまたぐ古い写し" in blob(c) for c in res_m["conflicts"] if c["date"] != "2030-09-25"),
          "T24 end_date の無い日をまたぐ予定は従来どおりその日の 24:00 まで")
    check(not any("終日の会期" in blob(c) for c in res_m["conflicts"]), "T24 複数日でも終日の予定は数えない")
    sec_m = render_section(res_m, today)
    check(any("9/25 18:00〜9/27 9:30 学外の会期" in ln for ln in sec_m), "T24 複数日の予定は期間で表示する")
    res_mn = detect(m_events, date(2030, 9, 27), days=0, provider=provider, ledger=ledger, now=datetime(2030, 9, 27, 10, 0))
    res_mn2 = detect(m_events, date(2030, 9, 27), days=0, provider=provider, ledger=ledger, now=datetime(2030, 9, 27, 11, 0))
    check(any("学外の会期" in blob(c) for c in res_mn["conflicts"]) and not any("学外の会期" in blob(c) for c in res_mn2["conflicts"]),
          "T24 今日の終わった組は、 複数日の予定もその日の終了時刻で外す")
    same = detect([dict(e, end_date=e["date"]) for e in events], today, days=7, provider=provider, ledger=ledger)
    bad_end = detect([dict(e, end_date="2030-09-01") for e in events] + [dict(events[0], end_date="きのう")], today, days=7,
                     provider=provider, ledger=ledger)
    keys = lambda r: sorted(c["key"] for c in r["conflicts"])  # noqa: E731
    check(keys(same) == keys(res) and keys(bad_end) == keys(res), "T25 1 日の予定の結果は end_date の有無・読めない値で変わらない")

    # 台帳の読み方
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ack.yaml"
        p.write_text('ignore_titles:\n  - "^🔔"\n  - "(壊れた"\nack:\n'
                     '  - date: "2030-09-25"\n    a: "科目甲"\n    b: "移動"\n    reason: "2030-09-24 早退の連絡済み"\n'
                     '  - date: "2030-10-02"\n    a: "会議"\n    b: "打合せ"\n    reason: "理由に日付が無い"\n'
                     '  - date: "2030-10-01"\n    until: "2030-12-24"\n    a: "A"\n    b: "B"\n    reason: "2030-09-24 毎週の件"\n',
                     encoding="utf-8")
        led = load_ledger(p)
        check(len(led["ack"]) == 2 and sum("揃っていない" in x for x in led["invalid"]) == 1,
              "T21 「YYYY-MM-DD 理由」 の無い ack は効かせず invalid に出す")
        check([k["until"] for k in led["ack"] if k["a"] == "A"] == [date(2030, 12, 24)], "T21 until で期間の ack")
        check(len(led["ignore"]) == 1 and led["ignore"][0].search("🔔 x") and any("壊れている" in x for x in led["invalid"]),
              "T21 ignore_titles を正規表現で読み、 壊れた正規表現は invalid")
        check(load_ledger(Path(td) / "none.yaml") == empty_ledger(), "T21 台帳が無ければ空")

        # 通知の投稿と記録 (偽の notifier = 引数を file に書く sh)
        log = Path(td) / "posted.txt"
        fake = Path(td) / "notify.sh"
        fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{log}"\n', encoding="utf-8")
        sp = Path(td) / "state" / "notified.json"
        n1 = post_notifications(res, today, sp, fake)
        posted = log.read_text(encoding="utf-8") if log.exists() else ""
        check(n1 == len(tg) and "--title" in posted and "⚠️ 予定の重なり" in posted and "--sound" in posted,
              "T22 notifier に題名・本文・音を渡す")
        saved = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        check(set(saved) == {k for k, _ in tg}, "T22 出した (段, 組) を記録する")
        check(post_notifications(res, today, sp, fake) == 0 and posted == log.read_text(encoding="utf-8"),
              "T22 記録済みの組は次の run で出さない")
        sp2 = Path(td) / "dry.json"
        post_notifications(res, today, sp2, fake, dry=True)
        check(not sp2.exists(), "T22 dry-run は記録しない")
        sp.write_text(json.dumps({"d1|2030-09-01|x|y": "2030-09-01"}), encoding="utf-8")
        post_notifications(res, today, sp, fake)
        check("d1|2030-09-01|x|y" not in json.loads(sp.read_text(encoding="utf-8")), "T22 14 日より古い記録は消す")

    print(f"\ncalendar_conflicts (engine) selftest: {npass} passed, {nfail} failed")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
