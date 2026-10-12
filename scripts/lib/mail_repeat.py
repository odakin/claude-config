#!/usr/bin/env python3
"""mail_repeat.py — 「同じ差出人から同じ件名の未読が、 別スレッドで日をまたいで積み上がる」 を拾う純関数
(= 語彙・差出人の列挙・宛名のどれにも依らない「何かを待たれている」 の信号。 python3 mail_repeat.py で selftest)。

なぜ (規約 = docs/convention-design-principles.md#noise-obligation-signal-sharing の反復軸):
  認証・同意・設定が済むまで送り手が毎日 (毎週) 同じ件名で送り続ける mail は、 受信箱の分類 (広告・通知) で抑制されると
  どの網にも出ないまま積む。 件名の語彙は class ごとに列挙が要り、 差出人は事故のたびに 1 つ足す形になる。
  反復は class を問わない共通の形で、 かつ newsletter (購読解除 header あり) と自動の失敗通知 (From が noreply@ 等の定型 ∧
  重要の印なし) を外せば誤検出は出ない (実測: 個人 account の受信箱 60 日分 ≈ 4 千通で 0 群、 組織 account ≈ 8 百通で 0 群)。

判定 (repeat_groups):
  (差出人 address, 正規化した件名) で束ね、 次を全部満たす群を返す:
    n >= min_msgs ∧ 届いた日 >= min_days ∧ 未読 / n >= min_unread_ratio ∧ 別スレッド / n >= min_thread_ratio
    ∧ 購読解除 header の mail を含まない ∧ 重要の印 (IMPORTANT) / n >= min_important_ratio
  重要の印を条件にする理由 = 同じ条件で印を見ないと、 注文・予約の完了通知 (本人の操作の結果) が 1 群混じる (実測)。 印は本人宛ての
  手続き (認証・督促・再登録・通知書) に付き、 CI の失敗通知・天気・完了通知には付かない。 `automated_from` は表示用に返すだけ。
  記録済み (recognized に id か threadId が在る) の mail を 1 通でも含む群は返さない (= 案件として既に知っている)。
  件名の正規化 = Re/Fwd を剥ぎ、 数字を # に、 空白を 1 つに、 小文字 80 字 (= 毎日の日付や通し番号を同じ件名と見る)。

item の形 (呼び出し側が Gmail の metadata から作る):
  {"id", "threadId", "from", "subject", "date_raw" (RFC 2822) か "internal_ms", "label_ids" (list),
   "list_unsubscribe" (bool, 任意)}

    sys.path.insert(0, str(<claude-config>/"scripts"/"lib"))
    from mail_repeat import repeat_groups, norm_subject
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime

try:
    from mail_watch import AUTOMATED_SENDER_RE as _AUTO_RE
except ImportError:  # 単体で置かれたとき (同じ正規表現、 2 か所に持たないのが本則)
    _AUTO_RE = re.compile(r"no-?reply|do-?not-?reply|donotreply|notifications?@|mailer-daemon|automated|bounces?@", re.I)

DEFAULTS = dict(min_msgs=5, min_days=4, min_unread_ratio=0.9, min_thread_ratio=0.8, min_important_ratio=0.5)
_REPLY_RE = re.compile(r"^(\s*(re|fwd?|fw|aw|sv)\s*:\s*)+", re.I)


def norm_subject(s: str) -> str:
    s = _REPLY_RE.sub("", s or "")
    s = re.sub(r"\d+", "#", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s[:80]


def sender_addr(from_header: str) -> str:
    a = [x for _n, x in getaddresses([from_header or ""]) if x]
    return a[0].lower() if a else (from_header or "").strip().lower()


def item_date(it: dict) -> datetime | None:
    try:
        if it.get("internal_ms"):
            return datetime.fromtimestamp(int(it["internal_ms"]) / 1000, tz=timezone.utc)
        d = parsedate_to_datetime(it.get("date_raw") or it.get("date") or "")
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def repeat_groups(items: list, recognized: set | None = None, *, now: datetime | None = None,
                  min_msgs: int = DEFAULTS["min_msgs"], min_days: int = DEFAULTS["min_days"],
                  min_unread_ratio: float = DEFAULTS["min_unread_ratio"],
                  min_thread_ratio: float = DEFAULTS["min_thread_ratio"],
                  min_important_ratio: float = DEFAULTS["min_important_ratio"],
                  ignore_senders: tuple = ()) -> list:
    """返り値 = [{"sender", "subject", "n", "unread", "days", "threads", "important", "automated_from",
    "first", "last" (datetime | None), "latest" (item), "ids" (list)}] を n の多い順。 純関数。"""
    recognized = recognized or set()
    groups: dict = defaultdict(list)
    for it in items or []:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        key = (sender_addr(it.get("from", "")), norm_subject(it.get("subject", "")))
        if not key[0] or any(s and s in key[0] for s in ignore_senders or ()):
            continue
        groups[key].append(it)
    out = []
    for (sender, subj), ms in groups.items():
        n = len(ms)
        if n < min_msgs:
            continue
        if any(m.get("id") in recognized or (m.get("threadId") or m.get("id")) in recognized for m in ms):
            continue
        if any(m.get("list_unsubscribe") for m in ms):
            continue
        labels = [set(m.get("label_ids") or ()) for m in ms]
        unread = sum(1 for L in labels if "UNREAD" in L)
        important = sum(1 for L in labels if "IMPORTANT" in L)
        threads = len({m.get("threadId") or m.get("id") for m in ms})
        dates = [d for d in (item_date(m) for m in ms) if d]
        days = len({d.astimezone().date() for d in dates})
        automated = bool(_AUTO_RE.search(ms[0].get("from", "") or ""))
        if days < min_days or unread / n < min_unread_ratio or threads / n < min_thread_ratio:
            continue
        if important / n < min_important_ratio:
            continue   # 重要の印 = 受信箱が「本人宛ての手続き」 と見た印。 注文・予約の完了通知と CI の失敗通知には付かない (実測)
        latest = max(ms, key=lambda m: (item_date(m) or datetime.min.replace(tzinfo=timezone.utc)))
        out.append({"sender": sender, "subject": subj, "n": n, "unread": unread, "days": days, "threads": threads,
                    "important": important, "automated_from": automated,
                    "first": min(dates) if dates else None, "last": max(dates) if dates else None,
                    "latest": latest, "ids": [m.get("id") for m in ms]})
    out.sort(key=lambda g: (-g["n"], g["sender"]))
    return out


def _selftest() -> int:
    from datetime import timedelta
    ok = [0]; bad = [0]

    def check(c, name):
        (ok if c else bad)[0] += 1
        print(("  PASS: " if c else "  FAIL: ") + name)

    base = datetime(2026, 8, 7, 3, 0, tzinfo=timezone.utc)

    def series(n, frm, subj, *, labels=("UNREAD", "IMPORTANT", "CATEGORY_UPDATES"), same_thread=False,
               unsub=False, skip_days=(), start=base, pre="s"):
        out = []
        d = 0; made = 0
        while made < n:
            if d not in skip_days:
                out.append({"id": f"{pre}{made:03d}", "threadId": ("t0" if same_thread else f"{pre}{made:03d}"),
                            "from": frm, "subject": subj, "label_ids": list(labels),
                            "date_raw": (start + timedelta(days=d)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
                            "list_unsubscribe": unsub})
                made += 1
            d += 1
        return out

    daily = series(65, '"Vendor Co" <contact-digital@example.net>', "【Vendor Co】メールアドレスの有効性の確認", skip_days=(1, 8))
    # 発火の時点: 8/7 から毎日 (8/8 は無い) → 5 通目 = 8/12
    cut = lambda items, day: [i for i in items if item_date(i) <= base + timedelta(days=day)]
    check(repeat_groups(cut(daily, 4)) == [], "4 通 (8/11 まで) ではまだ出ない")
    g = repeat_groups(cut(daily, 5))
    check(len(g) == 1 and g[0]["n"] == 5 and g[0]["days"] == 5, "5 通目 (8/12) で出る (n=5, 5 日)")
    g = repeat_groups(daily)
    check(len(g) == 1 and g[0]["n"] == 65 and g[0]["threads"] == 65 and g[0]["latest"]["id"] == "s064",
          "65 通 = 1 群、 latest は最後の 1 通")
    check(repeat_groups(daily, recognized={"s010"}) == [], "1 通でも記録済み (id) なら群ごと出さない")
    check(repeat_groups(daily, recognized={"s063"}) == [], "記録済み (threadId) でも同じ")
    gh = series(24, "ci <notifications@example.com>", "[owner/repo] Run failed: checks - main (abc123)",
                labels=("UNREAD", "CATEGORY_UPDATES"), pre="g")
    check(repeat_groups(gh) == [], "自動送信の定型 From ∧ 重要の印なし (CI の失敗通知) は出ない")
    gh_imp = series(10, "ci <notifications@example.com>", "[owner/repo] Run failed", pre="h")
    check(len(repeat_groups(gh_imp)) == 1, "定型 From でも重要の印が半数以上なら出る")
    nl = series(12, "News <news@example.org>", "今週のまとめ", unsub=True, pre="n")
    check(repeat_groups(nl) == [], "購読解除 header のある newsletter は出ない")
    th = series(12, "Alice <alice@example.org>", "Re: 打ち合わせ", same_thread=True, labels=("UNREAD",), pre="a")
    check(repeat_groups(th) == [], "同じスレッドの返信の束は出ない (別スレッドが条件)")
    rd = series(12, "Shop <shop@example.com>", "ご注文", labels=("CATEGORY_UPDATES",), pre="r")
    check(repeat_groups(rd) == [], "既読が多い群は出ない")
    done = series(6, "Coop <coop-info@example.org>", "予約変更完了のお知らせ", labels=("UNREAD", "CATEGORY_UPDATES"), pre="c")
    check(repeat_groups(done) == [], "重要の印の無い完了通知 (定型でない From でも) は出ない = 実測の誤検出 1 群")
    burst = series(12, "Shop <shop@example.com>", "ご注文", pre="b")
    for i in burst:
        i["date_raw"] = base.strftime("%a, %d %b %Y %H:%M:%S +0000")
    check(repeat_groups(burst) == [], "同じ日に 12 通 (日をまたがない) は出ない")
    numbered = series(8, "Bank <bank-info@example.com>", "【取引通知】入金 2026/08/0%d 分", pre="k")
    for i, m in enumerate(numbered):
        m["subject"] = f"【取引通知】入金 2026/08/{i+1:02d} 分"
    check(len(repeat_groups(numbered)) == 1, "件名の数字の違いは同じ件名と見る (正規化)")
    check(repeat_groups(daily, ignore_senders=("example.net",)) == [], "ignore_senders で外せる")
    check(norm_subject("Re: Fwd: [owner/x] Run failed: 12") == "[owner/x] run failed: #", "件名の正規化")
    print(f"\n==== RESULT: PASS={ok[0]} FAIL={bad[0]} ====")
    return 1 if bad[0] else 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
