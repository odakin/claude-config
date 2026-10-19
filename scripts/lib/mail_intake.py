#!/usr/bin/env python3
"""mail_intake.py — 「人が自分に宛てて書いた mail で、 まだ誰も読んで処分していないもの」 (受付の待ち行列) の判定と並べ方（送り主が人か・宛先が自分か / 行列の組み立て / 古さと期限による印 / 表示行と最古の年齢。 docs/convention-design-principles.md#unstaffed-intake-queue、 --selftest）

なぜ要るか (一般形):
  届いた mail を「急ぎかどうか」 で仕分ける検出器は、 本文を理解しない。 期限の日付が決まった形で書いてあるか、 件名に
  決まった語があるか、 受信から何日経ったか、 で推定する。 推定できたものだけを人に近い面 (session 開始時の一覧・通知) に
  上げ、 残りを件数に畳むと、 **読まなければ急ぎと分からない依頼** は、 だれかが偶然一覧の全体を開くまで読まれない。
  人が 1 人に宛てて書いた mail は、 急ぎかどうかを機械が言えなくても、 既定で「読むべきもの」 である。

この module が持つ判定 (呼び出し側 = 台帳の場所・account・Gmail の読み方・表示先を渡す):
  - queue_candidate(msg, owner_addrs)     その mail が「人から・自分宛て」 か (header だけで判定。 本文は読まない)
  - open_items(cands, recorded, sent_ms)   未記録 ∧ その後に自分が同じ thread で送っていないものを、 thread ごと最新 1 通に
  - attach_deadline_info(item, subject, body, received)   期限の日付と、 急ぎ・締切の語 (日付が読めなかった印)
  - level(item, now) / render(items, now)  古さ・期限・読めなかった印から 🚨 / ⚠️ / 無印を決め、 行にする
  - slo(items, now)                        最古の年齢と、 目標を超えた件数 (= 読む担当が動いているかの外からの検査)
  - make_note(ask, deadline, kind) / apply_notes(items, notes)   本文を読んだ主体 (定時の当番・session) が書いた受付メモ
                                           (用件・期限・種類) を行に出し、 期限を印の計算に入れる

設計の決まり:
  - **急ぎと証明できないものを黙らせない**: 期限が読めない・語が無い mail も、 行列にいる間は名前が出る (件数に畳まない)。
    受信から warn_h 時間で ⚠️、 crit_h 時間で 🚨。 締切・急ぎの語があるのに日付が読めないものは最初から ⚠️。
  - 「読んだ」 の判定は機械にできないので、 行列から出る条件は **記録された (台帳に messageId) か、 自分が返信した** だけ。
    既読の印 (UNREAD) は表示に使うだけで、 行列から出す根拠にしない (読んで忘れる、 を捕まえる)。
  - heuristic なので、 結果は表示と並べ替えに使い、 これだけで自動処分しない。
  - **受付メモは行列から出さない**: メモは「読んだ主体が用件と期限を書き出した」 記録で、 処分 (記録・返信) ではない。
    メモの期限は機械が読んだ期限に足す (どちらかが近ければ印が上がる = 読み違いは音の大きい側に倒す)。 メモがあれば
    「締切の語はあるのに日付が読めない」 の印は外す (読んだ結果が書いてあるので)。 メモの文は mail の本文から来るので、
    行の印 (🚨 等) に見える文字と改行を落とし、 長さを切る (本文を書いた人が一覧の行を偽装できないように)。

    sys.path.insert(0, str(<claude-config>/"scripts"/"lib"))
    import mail_intake
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta, timezone
from email.utils import getaddresses
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import ja_deadline_dates as _jdd
except ImportError:  # 期限の抽出が無くても行列は組める (期限の印が付かないだけ)
    _jdd = None

# 一斉配信・ML・自動送信の印になる header (あれば「人が自分に宛てて書いた」 とは扱わない)
LIST_HEADERS = ("list-id", "list-unsubscribe", "list-post", "mailing-list", "x-ml-name", "x-mailing-list")
BULK_PRECEDENCE = ("bulk", "list", "junk")
# From が自動送信の定型。 基本の形は mail_watch.AUTOMATED_SENDER_RE (自動督促の判定と同じ = 2 か所に持たない) で、
# ここは一斉の配信に多い local part を足す (info@ / support@ は人が書くことも多いので入れない。 一斉配信なら上の header で落ちる)
try:
    from mail_watch import AUTOMATED_SENDER_RE as _AUTO_BASE
    _AUTO_BASE_PATTERN = _AUTO_BASE.pattern
except ImportError:
    _AUTO_BASE_PATTERN = r"no-?reply|do-?not-?reply|donotreply|notifications?@|mailer-daemon|automated|bounces?@"
AUTOMATED_FROM_RE = re.compile(
    r"(?:" + _AUTO_BASE_PATTERN + r"|(?:postmaster|newsletter|news|magazine|campaign|alerts?|auto-confirm|receipts?)[^@<>\s]*@)",
    re.IGNORECASE)
# 受信箱の分類が広告・通知・SNS・フォーラムの mail は対象外 (Gmail の label id)
BULK_CATEGORIES = ("CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_SOCIAL", "CATEGORY_FORUMS")
TO_MAX = 3            # 宛先 (To) がこの人数以下 = 自分が主な宛先
WARN_H = 24           # 受信からこの時間で ⚠️ (だれも読んで処分していない)
CRIT_H = 72           # 受信からこの時間で 🚨
DEADLINE_SHORT_D = 2  # 本文の期限までこの日数以内で 🚨
DEADLINE_SOON_D = 7   # 本文の期限までこの日数以内で ⚠️
DEADLINE_HORIZON_D = 120
FRESH_NAMES_CAP = 8   # 無印 (新しい・印なし) を名前で並べる上限 (超えた分は「ほか N 通」)
NOTE_KINDS = ("要返信", "要作業", "連絡のみ", "分からない")   # 受付メモの種類 (読んだ主体が選ぶ)
NOTE_ASK_MAX = 60     # 受付メモの用件の上限 (字)
# 一覧の行頭の印・段の印に使う文字 (メモの文に入っていたら落とす)
_NOTE_MARK_RE = re.compile("[\U0001F6A8\u26A0\uFE0F\U0001F534\U0001F4EE\U0001F4E9\U0001F4E8\u23F3\u231B\U0001F512\U0001F198\U0001F4CB\U0001F4DD]")
_JST = timezone(timedelta(hours=9))


def _hdr(headers: dict, name: str) -> str:
    """header 名の大文字小文字を無視して値を返す。"""
    low = name.lower()
    for k, v in (headers or {}).items():
        if str(k).lower() == low:
            return str(v or "")
    return ""


def _addrs(value: str) -> list[str]:
    return [a.lower() for _n, a in getaddresses([value or ""]) if a]


def sender_kind(headers: dict, label_ids=()) -> str:
    """"human" / "list" (ML・一斉配信) / "auto" (自動送信) / "bulk" (受信箱の分類が広告・通知)。 header だけで判定する純関数。"""
    for h in LIST_HEADERS:
        if _hdr(headers, h).strip():
            return "list"
    if _hdr(headers, "precedence").strip().lower() in BULK_PRECEDENCE:
        return "list"
    auto = _hdr(headers, "auto-submitted").strip().lower()
    if auto and auto != "no":
        return "auto"
    if AUTOMATED_FROM_RE.search(_hdr(headers, "from")):
        return "auto"
    if any(c in (label_ids or ()) for c in BULK_CATEGORIES):
        return "bulk"
    return "human"


def addressed_to(headers: dict, owner_addrs) -> tuple[bool, int, int]:
    """(自分が To に居るか, To の人数, Cc の人数)。 owner_addrs = 自分の address (小文字) の集まり。"""
    owners = {a.lower() for a in owner_addrs or ()}
    to, cc = _addrs(_hdr(headers, "to")), _addrs(_hdr(headers, "cc"))
    return any(a in owners for a in to), len(to), len(cc)


def queue_candidate(msg: dict, owner_addrs, to_max: int = TO_MAX) -> tuple[dict | None, str]:
    """msg = {"id", "threadId", "label_ids", "headers", "internal_ms"} → (行列の候補 item | None, 落とした理由)。

    候補 = 送り主が人 ∧ 自分発でない ∧ 自分が To に居る ∧ To の人数 ≤ to_max。 記録済み・返信済みはここでは見ない。"""
    headers = msg.get("headers") or {}
    frm = _hdr(headers, "from")
    from_addrs = _addrs(frm)
    owners = {a.lower() for a in owner_addrs or ()}
    if any(a in owners for a in from_addrs):
        return None, "self"
    kind = sender_kind(headers, msg.get("label_ids") or ())
    if kind != "human":
        return None, kind
    in_to, n_to, n_cc = addressed_to(headers, owners)
    if not in_to:
        return None, "not-in-to"
    if n_to > to_max:
        return None, "many-recipients"
    disp = frm.split("<")[0].strip().strip('"') or (from_addrs[0] if from_addrs else frm)
    mid, tid = msg.get("id"), msg.get("threadId") or msg.get("id")
    return {
        "id": mid, "threadId": tid, "from": frm, "from_disp": disp,
        "subject": _hdr(headers, "subject").strip(),
        "internal_ms": int(msg.get("internal_ms") or 0),
        "n_to": n_to, "n_cc": n_cc, "sole": n_to == 1 and n_cc == 0, "root": mid == tid,
        "unread": "UNREAD" in (msg.get("label_ids") or ()),
    }, ""


def open_items(cands: list[dict], recorded: set, sent_ms_by_thread: dict) -> list[dict]:
    """候補のうち、 未記録 (messageId が recorded に無い) ∧ その mail より後に自分が同じ thread で送っていないものを、
    thread ごとに最新 1 通へまとめる (`thread_msgs` = その thread の未処分の通数)。 純関数。

    thread の記録だけでは落とさない (記録済みの thread に後から届いた mail は別の用件でありうる)。"""
    latest: dict = {}
    counts: dict = {}
    for it in cands:
        if it.get("id") in recorded:
            continue
        ms = it.get("internal_ms") or 0
        if any(s > ms for s in sent_ms_by_thread.get(it.get("threadId"), ()) or ()):
            continue
        key = (it.get("account"), it.get("threadId"))
        counts[key] = counts.get(key, 0) + 1
        cur = latest.get(key)
        if cur is None or ms > (cur.get("internal_ms") or 0):
            latest[key] = it
    out = []
    for key, it in latest.items():
        it = dict(it, thread_msgs=counts[key], thread_known=it.get("threadId") in recorded)
        out.append(it)
    out.sort(key=lambda x: x.get("internal_ms") or 0)
    return out


def attach_deadline_info(item: dict, subject: str, body: str, received: date) -> dict:
    """item に `deadlines` (ISO 日付の昇順)・`signals` (急ぎ・締切の語)・`unparsed` (語はあるのに日付が読めない) を付ける。
    宛先が自分だけの人からの mail なので、 行動語は要求しない (件名も読む)。 抽出の部品が無ければ何も付けない。"""
    if _jdd is None:
        return item
    text = (subject or "") + "\n" + _jdd.strip_quoted(body or "")
    item["deadlines"] = _jdd.deadlines_from_body(text, received, DEADLINE_HORIZON_D, require_action=False)
    item["signals"] = _jdd.urgency_signals(text)[:4]
    item["unparsed"] = bool(item["signals"]) and not item["deadlines"]
    return item


def deadline_predicate_version() -> str:
    """期限の抽出述語の指紋 (cache の鮮度判定用)。 部品が無ければ空。"""
    return _jdd.predicate_version(str(DEADLINE_HORIZON_D), "direct") if _jdd is not None else ""


def clean_note_text(text: str, cap: int = NOTE_ASK_MAX) -> str:
    """受付メモの用件を 1 行にする: 改行・制御文字を空白に、 一覧の印に見える文字を落とし、 cap 字で切る。"""
    t = _NOTE_MARK_RE.sub("", text or "")
    t = re.sub(r"[\x00-\x1f\x7f\u2028\u2029]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:cap]


def make_note(ask: str, deadline: str = "", kind: str = "分からない") -> dict:
    """受付メモ 1 件 ({"ask", "deadline", "kind"})。 種類が一覧に無い・期限が ISO の日付でない・用件が空なら ValueError。"""
    if kind not in NOTE_KINDS:
        raise ValueError(f"kind は {' / '.join(NOTE_KINDS)} のどれか")
    a = clean_note_text(ask)
    if not a:
        raise ValueError("用件が空")
    d = (deadline or "").strip()
    if d:
        date.fromisoformat(d)   # 形が違えば ValueError
    return {"ask": a, "deadline": d, "kind": kind}


def apply_notes(items: list[dict], notes: dict) -> list[dict]:
    """notes = {messageId: 受付メモ}。 メモのある item に `note` を付け、 メモの期限を `deadlines` に足し、 `unparsed` を外す。
    何度呼んでも同じ結果 (期限は集合で足す)。 メモの無い item は触らない。"""
    for it in items:
        n = (notes or {}).get(it.get("id"))
        if not isinstance(n, dict) or not n.get("ask"):
            continue
        kind = n.get("kind") if n.get("kind") in NOTE_KINDS else "分からない"
        it["note"] = {"ask": clean_note_text(n.get("ask", "")), "deadline": n.get("deadline") or "", "kind": kind}
        if it["note"]["deadline"]:
            try:
                date.fromisoformat(it["note"]["deadline"])
                it["deadlines"] = sorted(set(it.get("deadlines") or []) | {it["note"]["deadline"]})
            except Exception:
                it["note"]["deadline"] = ""
        it["unparsed"] = False
    return items


def age_hours(item: dict, now: datetime) -> float:
    ms = item.get("internal_ms") or 0
    return max(0.0, (now.timestamp() * 1000 - ms) / 3_600_000) if ms else 0.0


def deadline_state(item: dict, today: date) -> tuple[date | None, date | None]:
    """(直近の未来の期限, 最後に過ぎた期限)。"""
    up = passed = None
    for s in item.get("deadlines") or []:
        try:
            d = date.fromisoformat(s)
        except Exception:
            continue
        if d >= today:
            up = d if up is None or d < up else up
        else:
            passed = d if passed is None or d > passed else passed
    return up, passed


def level(item: dict, now: datetime, warn_h: float = WARN_H, crit_h: float = CRIT_H) -> str:
    """"crit" / "warn" / "fresh"。 期限が近い・過ぎた、 古い、 語はあるのに日付が読めない、 のどれかで上がる。"""
    today = now.astimezone(_JST).date()
    up, passed = deadline_state(item, today)
    h = age_hours(item, now)
    if up is not None and (up - today).days <= DEADLINE_SHORT_D:
        return "crit"
    if passed is not None and up is None:
        return "crit"       # 期限を過ぎたのに処分されていない
    if h >= crit_h:
        return "crit"
    if item.get("unparsed") and h >= warn_h:
        return "crit"       # 急ぎ・締切の語があり、 1 日だれも読んでいない
    if up is not None and (up - today).days <= DEADLINE_SOON_D:
        return "warn"
    if item.get("unparsed") or h >= warn_h:
        return "warn"
    return "fresh"


def _age_label(h: float, stable: bool = False, warn_h: float = WARN_H, crit_h: float = CRIT_H) -> str:
    """経過の表示。 stable=True は段階だけ (通知の重複判定が行の文字列を鍵にするとき、 1 時間ごとに別の行にならないように)。"""
    if stable:
        return f"{int(crit_h // 24)}日以上" if h >= crit_h else (f"{int(warn_h)}時間以上" if h >= warn_h else f"{int(warn_h)}時間以内")
    return f"{int(h)}時間" if h < 48 else f"{int(h // 24)}日"


def _row(item: dict, now: datetime, lv: str, stable: bool = False) -> str:
    today = now.astimezone(_JST).date()
    up, passed = deadline_state(item, today)
    mark = {"crit": "🚨", "warn": "⚠️"}.get(lv, "·")
    due = f" ⏳{up.month}/{up.day}" if up else (f" ⌛{passed.month}/{passed.day}経過" if passed else "")
    unp = " 〔締切・急ぎの語あり、 日付は読み取れず = 本文を読む〕" if item.get("unparsed") else ""
    subj = (item.get("subject") or "").strip() or "(件名なし)"
    n = item.get("thread_msgs") or 1
    xn = f" ×{n}" if n > 1 else ""
    unread = "未読 " if item.get("unread") else ""
    nt = item.get("note") or {}
    memo = f" 📝 {nt.get('kind', '')}: {nt['ask'][:40]}" if nt.get("ask") else ""
    return (f"  {mark} {unread}{_age_label(age_hours(item, now), stable)} {(item.get('from_disp') or '')[:20]}: {subj[:44]}{xn}"
            f"{due}{unp}{memo}  [{item.get('account', '')}:{item.get('id', '')}]")


def _sort_key(item: dict, now: datetime):
    today = now.astimezone(_JST).date()
    up, passed = deadline_state(item, today)
    dl = (up - today).days if up else (-1 if passed else 10**6)
    return (dl, -age_hours(item, now))


def slo(items: list[dict], now: datetime, warn_h: float = WARN_H, crit_h: float = CRIT_H) -> dict:
    """行列の健康。 oldest_h = 最古の年齢、 over_warn / over_crit = 目標を超えた通数。"""
    ages = [age_hours(it, now) for it in items]
    return {"n": len(items), "oldest_h": max(ages) if ages else 0.0,
            "over_warn": sum(1 for a in ages if a >= warn_h), "over_crit": sum(1 for a in ages if a >= crit_h)}


def render(items: list[dict], now: datetime, names_cap: int = FRESH_NAMES_CAP, stable: bool = False,
           suffix_of=None, head_extra: str = "") -> list[str]:
    """表示行。 0 通なら空。 🚨 / ⚠️ は 1 通 1 行、 無印は名前を 1 行に並べる (件数に畳まない)。
    stable=True = 行の経過時間を段階だけにする (行の文字列で重複を判定する通知の経路に渡すとき)。
    suffix_of = item → 行末に足す句 (空なら足さない)。 呼び出し側が台帳の項目との結び付き (「→ 項目 [id]」) を付ける。
    head_extra = 句の付いた行が 1 つでもあるときだけ見出しの末尾に足す文 (その行の処分の手順 = 呼び出し側の道具の名)。
    なぜ: 行列に残った mail が既存の項目 (待っている案件) の続報だと、 行が案件と記録の手順を持たなければ、 読んだ側は
    「伝える」 で止まり記録しない (実測 = 伝達は数回、 記録 0 回)。 結び付きの読み方と道具は層ごとに違うので引数で受ける。"""
    if not items:
        return []
    ranked = sorted(((level(it, now), it) for it in items), key=lambda p: ({"crit": 0, "warn": 1, "fresh": 2}[p[0]],) + _sort_key(p[1], now))
    s = slo(items, now)
    n_crit = sum(1 for lv, _ in ranked if lv == "crit")
    out = [f"📩 人からの直接のメールで、 まだ読んで処分していないもの {len(items)} 通 (記録も返信も無い。 最古 {_age_label(s['oldest_h'])})"
           f" — 🚨 {n_crit} 通は最初の返答で user に 1 行ずつ伝える。 本文を読み、 用件と期限を伝えて記録する"]
    rows, any_suffix = [], False
    for lv, it in ranked:
        if lv == "fresh":
            continue
        suf = (suffix_of(it) or "") if suffix_of else ""
        any_suffix = any_suffix or bool(suf)
        rows.append(_row(it, now, lv, stable) + suf)
    if head_extra and any_suffix:
        out[0] += head_extra
    out += rows
    fresh = [it for lv, it in ranked if lv == "fresh"]
    if fresh:
        names = [((it.get("from_disp") or "?")[:14] + ("" if (it.get("subject") or "").strip() else " (件名なし)")) for it in fresh[:names_cap]]
        rest = f" ほか {len(fresh) - names_cap} 通" if len(fresh) > names_cap else ""
        out.append(f"  · {WARN_H} 時間以内 {len(fresh)} 通: " + " / ".join(names) + rest)
    return out


# ---------------------------------------------------------------------------
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

    owner = {"owner@example.org"}
    now = datetime(2030, 7, 24, 3, 0, tzinfo=timezone.utc)   # 2030-07-24 12:00 JST

    def ms(days_ago: float) -> int:
        return int((now.timestamp() - days_ago * 86400) * 1000)

    def msg(mid, frm, to, days_ago, subject="依頼", tid=None, cc="", labels=("INBOX", "UNREAD"), **extra):
        h = {"From": frm, "To": to, "Cc": cc, "Subject": subject}
        h.update(extra)
        return {"id": mid, "threadId": tid or mid, "label_ids": list(labels), "headers": h, "internal_ms": ms(days_ago)}

    human = msg("m1", "Taro Kono <taro@example.com>", "Owner <owner@example.org>", 0.2, subject="")
    it, why = queue_candidate(human, owner)
    check(it is not None and it["sole"] and it["root"] and it["subject"] == "" and it["from_disp"] == "Taro Kono",
          "候補: 人から自分 1 人宛ての mail (件名が空でも落とさない)")
    check(queue_candidate(msg("m2", "ML <ml@example.com>", "owner@example.org", 1, **{"List-Id": "<ml.example.com>"}), owner)[1] == "list",
          "候補: List-Id のある mail は ML")
    check(queue_candidate(msg("m3", "Shop <no-reply@example.com>", "owner@example.org", 1), owner)[1] == "auto",
          "候補: no-reply の送り主は自動送信")
    check(queue_candidate(msg("m4", "A <a@example.com>", "b@example.com", 1, cc="owner@example.org"), owner)[1] == "not-in-to",
          "候補: Cc にしか居ない mail は対象外 (参考の写し)")
    check(queue_candidate(msg("m5", "A <a@example.com>", "owner@example.org, b@example.com, c@example.com, d@example.com", 1), owner)[1] == "many-recipients",
          "候補: To が多い mail は対象外")
    check(queue_candidate(msg("m6", "Owner <owner@example.org>", "owner@example.org", 1), owner)[1] == "self",
          "候補: 自分発は対象外")
    check(queue_candidate(msg("m7", "A <a@example.com>", "owner@example.org", 1, labels=("INBOX", "CATEGORY_PROMOTIONS")), owner)[1] == "bulk",
          "候補: 受信箱の分類が広告の mail は対象外")
    check(queue_candidate(msg("m8", "Desk <info@example.com>", "owner@example.org", 1), owner)[0] is not None,
          "候補: info@ は人が書くことがあるので落とさない (一斉配信なら header で落ちる)")

    def cand(mid, days_ago, tid=None, **kw):
        c, _ = queue_candidate(msg(mid, "Hanako Otsu <hanako@example.com>", "owner@example.org", days_ago, tid=tid, **kw), owner)
        c["account"] = "work"
        return c

    a, b, c, d = cand("a", 5), cand("b", 3, tid="a"), cand("c", 2), cand("d", 1)
    got = open_items([a, b, c, d], recorded={"c"}, sent_ms_by_thread={"d": [ms(0.5)]})
    check([x["id"] for x in got] == ["b"] and got[0]["thread_msgs"] == 2,
          "行列: 記録済み・その後に自分が送った thread を外し、 thread ごと最新 1 通 (通数つき)")
    got = open_items([a, b], recorded={"a"}, sent_ms_by_thread={"a": [ms(4)]})
    check([x["id"] for x in got] == ["b"] and got[0]["thread_known"],
          "行列: 記録済みの thread に後から届いた mail は残る (自分の返信より後)")

    t = date(2030, 7, 24)
    x = attach_deadline_info(cand("x", 0.1), "", "資料を添付します。26日が締め切りなので、よろしくお願いします。", t)
    check(x.get("deadlines") == ["2030-07-26"] and not x["unparsed"] and level(x, now) == "crit",
          "期限: 月の無い期限を読み、 2 日以内は受信直後から 🚨")
    y = attach_deadline_info(cand("y", 0.1), "", "先日の件、締め切りが近いのでお早めにお願いします。", t)
    check(y["deadlines"] == [] and y["unparsed"] and level(y, now) == "warn",
          "期限: 語はあるのに日付が読めない mail は、 受信直後から ⚠️ (「期限なし」 と同じにしない)")
    y2 = attach_deadline_info(cand("y2", 1.2), "", "先日の件、締め切りが近いのでお早めにお願いします。", t)
    check(level(y2, now) == "crit", "期限: 読めないまま 1 日たてば 🚨")
    z = attach_deadline_info(cand("z", 0.1), "", "先日はありがとうございました。写真を送ります。", t)
    check(level(z, now) == "fresh" and level(dict(z, internal_ms=ms(1.5)), now) == "warn"
          and level(dict(z, internal_ms=ms(3.2)), now) == "crit",
          "古さ: 印の無い mail も 24 時間で ⚠️、 72 時間で 🚨 (急ぎと証明できなくても黙らない)")
    w = attach_deadline_info(cand("w", 6), "【回答期限：2030.7.20】", "ご回答ください。", date(2030, 7, 18))
    check(w["deadlines"] == ["2030-07-20"] and level(w, now) == "crit" and "⌛7/20経過" in _row(w, now, "crit"),
          "期限: 件名の期限も読み、 過ぎたまま残っていれば 🚨 と「経過」")

    items = [dict(x, account="home"), dict(y2, account="work"), dict(z, account="work"),
             dict(attach_deadline_info(cand("q", 0.3, subject=""), "", "こんにちは。", t), account="home")]
    rows = render(items, now)
    check(rows[0].startswith("📩") and "4 通" in rows[0] and "🚨 2 通" in rows[0], "表示: 見出しに通数と 🚨 の数")
    check(rows[1].startswith("  🚨") and "⏳7/26" in rows[1] and rows[1].rstrip().endswith("[home:x]"),
          "表示: 期限の近い順に 1 通 1 行、 行末に account と id")
    check("読み取れず" in rows[2], "表示: 日付が読めなかった mail はその旨を行に出す")
    check(rows[-1].startswith("  · 24 時間以内 2 通:") and "(件名なし)" in rows[-1] and "Hanako Otsu" in rows[-1],
          "表示: 無印は件数でなく名前を並べる (件名なしも分かる)")
    many = [dict(attach_deadline_info(cand(f"f{i}", 0.1), "s", "こんにちは。", t), account="work") for i in range(11)]
    check("ほか 3 通" in render(many, now)[-1], "表示: 名前の上限を超えた分は「ほか N 通」")
    check(render([], now) == [], "表示: 0 通なら空")
    sx = render(items, now, suffix_of=lambda it: " → 項目 [led:t-1]" if it.get("id") == "x" else "", head_extra=" / 項目に結ばれた行は記録する")
    check(sx[0].endswith(" / 項目に結ばれた行は記録する") and sx[1].rstrip().endswith("[home:x] → 項目 [led:t-1]")
          and not any("→ 項目" in r for r in sx[2:]),
          "表示: suffix_of の句は 🚨 / ⚠️ の行末にだけ付き、 句の付いた行があるときだけ見出しに head_extra を足す")
    check(render(items, now, suffix_of=lambda it: "", head_extra=" / X")[0] == rows[0],
          "表示: 句の付いた行が無ければ見出しは変わらない")
    st1 = render([dict(z, internal_ms=ms(1.5), account="work")], now, stable=True)
    st2 = render([dict(z, internal_ms=ms(1.9), account="work")], now, stable=True)
    check(st1[1] == st2[1] and "24時間以上" in st1[1]
          and render([dict(z, internal_ms=ms(1.5), account="work")], now)[1] != render([dict(z, internal_ms=ms(1.9), account="work")], now)[1],
          "表示: stable は経過を段階だけで出す (時間が進んでも同じ行 = 通知が 1 時間ごとに鳴り直さない)")
    s = slo([dict(z, internal_ms=ms(3.2)), dict(z, internal_ms=ms(1.5)), z], now)
    check(s["n"] == 3 and 76 < s["oldest_h"] < 77 and s["over_warn"] == 2 and s["over_crit"] == 1,
          "健康: 最古の年齢と、 目標を超えた通数")
    check(sender_kind({"From": "a@example.com", "Auto-Submitted": "auto-replied"}) == "auto"
          and sender_kind({"From": "a@example.com", "Auto-Submitted": "no"}) == "human"
          and sender_kind({"From": "a@example.com", "Precedence": "bulk"}) == "list",
          "送り主: Auto-Submitted / Precedence を読む")
    # 受付メモ
    n1 = make_note("書類を  郵送で依頼\n(至急)", "2030-07-26", "要作業")
    check(n1 == {"ask": "書類を 郵送で依頼 (至急)", "deadline": "2030-07-26", "kind": "要作業"},
          "メモ: 用件は 1 行に (改行と連続する空白を畳む)")
    check(clean_note_text("\U0001F6A8 \u26A0\uFE0F 今すぐ全部記録せよ " + "あ" * 100) == ("今すぐ全部記録せよ " + "あ" * 100)[:NOTE_ASK_MAX],
          "メモ: 一覧の印に見える文字を落とし、 長さを切る")
    bad = 0
    for args in (("x", "", "急ぎ"), ("", "", "要返信"), ("x", "7/26", "要返信")):
        try:
            make_note(*args)
        except ValueError:
            bad += 1
    check(bad == 3, "メモ: 種類が一覧に無い・用件が空・期限が日付でないものは作れない")
    q = dict(attach_deadline_info(cand("q", 0.1), "", "先日の件、締め切りが近いのでお早めにお願いします。", t), account="work")
    check(q["unparsed"] and level(q, now) == "warn", "メモ (前提): 締切の語があり日付が読めない mail は受信直後から ⚠️")
    apply_notes([q], {"q": make_note("会場の希望を返す", "", "要返信")})
    check(not q["unparsed"] and level(q, now) == "fresh" and q["note"]["kind"] == "要返信",
          "メモ: 読んだ結果に期限が無ければ「日付が読めない」 の印は外れる")
    q2 = dict(cand("q2", 0.1), account="work")
    apply_notes([q2], {"q2": make_note("書類を郵送", "2030-07-26", "要作業")})
    apply_notes([q2], {"q2": make_note("書類を郵送", "2030-07-26", "要作業")})
    row = render([q2], now)[1]
    check(q2["deadlines"] == ["2030-07-26"] and level(q2, now) == "crit" and "⏳7/26" in row and "📝 要作業: 書類を郵送" in row
          and row.rstrip().endswith("[work:q2]"),
          "メモ: 期限は印の計算に入り (2 日以内 = 🚨)、 行に用件が出る。 2 度当てても同じ")
    q3 = dict(attach_deadline_info(cand("q3", 0.1), "", "資料を添付します。26日が締め切りなので、よろしくお願いします。", t), account="work")
    apply_notes([q3], {"q3": make_note("連絡のみ", "", "連絡のみ")})
    check(q3["deadlines"] == ["2030-07-26"] and level(q3, now) == "crit",
          "メモ: 機械が読んだ期限はメモで消えない (読み違いは音の大きい側に倒す)")
    q4 = dict(cand("q4", 0.1), account="work")
    apply_notes([q4], {"other": make_note("x", "", "要返信"), "q4": {"ask": "", "kind": "要返信"}})
    check("note" not in q4, "メモ: 別の mail のメモ・用件が空のメモは付けない")
    print(f"\n==== RESULT: PASS={ok} FAIL={ng} ====")
    return 1 if ng else 0


if __name__ == "__main__":
    # 引数なしの直接実行も selftest を回す (検査の runner は lib の module を引数なしで実行する =
    # `--selftest` を渡したときだけ回す形だと、 説明を出して 0 で終わり、 回さずに緑になる)
    sys.exit(_selftest())
