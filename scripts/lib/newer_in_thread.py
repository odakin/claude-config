#!/usr/bin/env python3
"""newer_in_thread.py — 返信先より新しい message (相手の続報・自分がもう送った返事) を送信前に数える engine (thread の読みは呼び手が持つ)。

なぜ存在するか:
  threading が正しくても、 返信先を決めた後に相手が同じ thread で返事をしていれば、 それを読まない続報
  (答え済みの質問の聞き直し) になる (実測)。 送信 CLI の dry-run には threadId しか出ず、 新着は見えない。
  返信する CLI はどれも「thread を読み直し、 返信先より新しい相手の message を先頭に出し、 最新の相手 message
  の id で ack されるまで送らない」 を要る。 CLI ごとに判定を持つと、 自分の判定 (list の配り直しの写し等) が
  片方にだけ入る。 判定と表示を 1 か所に置く。 規約 = conventions/gmail-sending.md#reply-newer-in-thread。

入力 (= 呼び手の gateway が用意する row、 Gmail API の threads.get(format=metadata) なら rows_from_gmail_thread):
  {"id", "internal_date" (epoch ms の整数), "labels", "from", "message_id", 任意で "subject", "date", "snippet"}

判定:
  newer_counterpart(rows, parent_id, self_addrs) = 返信先より internal_date が新しく、 送信アカウントが書いて
  いないもの (古い順)。 自分 = SENT/DRAFT label (send-as の別名も拾う) / From が self_addrs / 自分の label つき
  message と同じ Message-ID (list が自分の投稿を From を書き換えて配り直した写し)。 同じ人の別アカウントは相手に
  数える (= 警告が出る側)。 返信先が listing に無く internal_date も渡されない、 日付の無い row = ValueError
  (fail closed)。
  newer_own_sent(rows, parent_id, parent_internal_date) = 返信先より新しく、 送信アカウントがもう送った row
  (SENT label、 古い順)。 下書き (DRAFT) と list が配り直した自分の写し (SENT 無し) は数えない = 1 通の返事は 1 行。
  newer_in_thread(rows, parent_id, self_addrs, parent_internal_date) = 上の 2 つを合わせて古い順、 自分の送信の
  row には "own": True (写し、 入力の row は変えない)。 使う呼び手は二重返信も止める (自分の返事の後に同じ
  用件をもう一度送る = 相手の続報が無いと newer_counterpart では止まらない、 実測)。 自分の続報を意図して
  送るときも最新の id で ack する。 newer_counterpart だけを使う呼び手は従来どおり。
  decide(newer, ack) = (送ってよいか, 最新の id)。 通すのは新着が無いか ack が最新の id のときだけ
  (= 後から届けば id が変わり再び止まる)。
  notice(newer, ack, templates, when, **extra) = decide + 表示の行。 文言は templates (既定 EN) で差し替える
  (呼び手の言語・flag 名・exit code は extra で渡す)。 own の row には own_mark、 own があれば own_note、
  最新が own なら switch の代わりに own_latest。

使い方:
    sys.path.insert(0, "<claude-config>/scripts/lib"); import newer_in_thread as nit
    rows = nit.rows_from_gmail_thread(thread_json["messages"])
    newer = nit.newer_counterpart(rows, parent_id, {sender})   # 二重返信も止めるなら nit.newer_in_thread
    allowed, lines = nit.notice(newer, ack)
    python3 newer_in_thread.py --selftest      # 合成 row だけ (API に触らない)
"""
from __future__ import annotations

import html
import sys
from datetime import datetime, timezone
from email.utils import parseaddr

SELF_LABELS = frozenset({"SENT", "DRAFT"})
THREAD_HEADERS = ("From", "Subject", "Date", "Message-ID")

EN = {
    "header": "WARNING: {n} newer message(s) in this thread after the parent (oldest first):",
    "omitted": "  … {k} older omitted",
    "item": "  - {when}  {sender}  \"{subject}\"  {snippet}  (id {id})",
    "own_mark": "  [already sent by this account]",
    "own_note": "{k} of them already sent by this account: check this is not the same reply twice.",
    "own_latest": "The newest one ({latest}) was sent by this account: if it answers the same point, "
                  "do not send this; for a deliberate follow-up, acknowledge it.",
    "switch": "Usually: prepare a new bundle whose parent is the newest one ({latest}).",
    "acked": "Acknowledged {latest}: read, keeping this parent; send may proceed.",
    "wrong_ack": "Acknowledgement {ack} is not the newest message "
                 "(newest = {latest}); read it, then pass its id.",
    "how_to_ack": "To keep this parent after reading them: send --ack-newer {latest}.",
    "refused": "Send is refused until then.",
    "no_newer_ack": "",
}


def rows_from_gmail_thread(messages):
    """Gmail API の thread message (format=metadata) を row に。 internalDate が無い row は None のまま
    (= 判定で ValueError、 黙って古い扱いにしない)。"""
    rows = []
    for m in messages or []:
        h = {v.get("name", "").lower(): v.get("value", "")
             for v in (m.get("payload") or {}).get("headers", []) or []}
        rows.append({"id": m.get("id"), "labels": list(m.get("labelIds") or []),
                     "internal_date": int(m["internalDate"]) if m.get("internalDate") else None,
                     "from": h.get("from", ""), "subject": h.get("subject", ""),
                     "date": h.get("date", ""), "message_id": h.get("message-id", ""),
                     "snippet": m.get("snippet", "")})
    return rows


def when_ms(row):
    try:
        return int(row["internal_date"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Thread listing needs an integer internal_date per message") from None


def _own(row):
    return bool(SELF_LABELS & set(row.get("labels") or []))


def _base_ms(rows, parent_id, parent_internal_date):
    """返信先の internal_date (= 新着の起点)。 返信先が listing に無く日付も渡されなければ fail closed。"""
    parents = [r for r in rows if r.get("id") == parent_id]
    if len(parents) == 1:
        base = when_ms(parents[0])
    elif not parents and parent_internal_date is not None:
        base = int(parent_internal_date)
    else:
        raise ValueError("Parent not found in its thread listing; cannot check for newer replies")
    return base


def newer_counterpart(rows, parent_id, self_addrs, parent_internal_date=None):
    """返信先より新しく、 送信アカウントが書いていない row を古い順に返す (判定は module docstring)。"""
    selves = {a.lower() for a in self_addrs if a}
    base = _base_ms(rows, parent_id, parent_internal_date)
    own_ids = {r.get("message_id") for r in rows if _own(r)} - {"", None}
    newer = [r for r in rows
             if r.get("id") != parent_id and when_ms(r) > base and not _own(r)
             and parseaddr(r.get("from") or "")[1].lower() not in selves
             and not (r.get("message_id") and r["message_id"] in own_ids)]
    return sorted(newer, key=when_ms)


def newer_own_sent(rows, parent_id, parent_internal_date=None):
    """返信先より新しく、 送信アカウントがもう送った row (SENT label) を古い順に返す (判定は module docstring)。"""
    base = _base_ms(rows, parent_id, parent_internal_date)
    sent = [r for r in rows
            if r.get("id") != parent_id and "SENT" in (r.get("labels") or []) and when_ms(r) > base]
    return sorted(sent, key=when_ms)


def newer_in_thread(rows, parent_id, self_addrs, parent_internal_date=None):
    """相手の新着と自分がもう送った返事を合わせて古い順に返す。 自分の送信は "own": True を付けた写し。"""
    own = [dict(r, own=True) for r in newer_own_sent(rows, parent_id, parent_internal_date)]
    return sorted(newer_counterpart(rows, parent_id, self_addrs, parent_internal_date) + own, key=when_ms)


def decide(newer, ack=""):
    if not newer:
        return True, None
    latest = newer[-1]["id"]
    return ack == latest, latest


def _flat(value, limit=None):
    text = " ".join(str(value or "").split())
    return text if limit is None or len(text) <= limit else text[:limit] + "…"


def default_when(row):
    return row.get("date") or datetime.fromtimestamp(
        when_ms(row) / 1000, timezone.utc).isoformat(timespec="minutes")


def describe(row, templates=EN, when=default_when):
    line = templates["item"].format(
        when=_flat(when(row)), sender=_flat(row.get("from")), subject=_flat(row.get("subject")),
        snippet=_flat(html.unescape(row.get("snippet") or ""), 70), id=row["id"])
    return line + (templates["own_mark"] if row.get("own") else "")


def notice(newer, ack="", templates=EN, when=default_when, **extra):
    """(送ってよいか, 表示する行)。 extra は templates の置換に足す値 (flag 名・exit code 等)。"""
    allowed, latest = decide(newer, ack)
    if latest is None:
        line = templates["no_newer_ack"].format(ack=ack, **extra) if ack else ""
        return True, [line] if line else []
    shown = newer[-10:]
    fmt = dict(extra, n=len(newer), latest=latest, ack=ack)
    lines = [templates["header"].format(**fmt)]
    if len(newer) > len(shown):
        lines.append(templates["omitted"].format(k=len(newer) - len(shown), **fmt))
    lines += [describe(r, templates, when) for r in shown]
    n_own = sum(1 for r in newer if r.get("own"))
    if n_own:
        lines.append(templates["own_note"].format(**dict(fmt, k=n_own)))
    lines.append(templates["own_latest" if newer[-1].get("own") else "switch"].format(**fmt))
    if allowed:
        lines.append(templates["acked"].format(**fmt))
        return True, lines
    lines.append(templates["wrong_ack" if ack else "how_to_ack"].format(**fmt))
    lines.append(templates["refused"].format(**fmt))
    return False, lines


# ---- selftest (合成 row だけ。 行頭 [PASS] / [FAIL] = check-foil-teeth.py が読む) ----

def _row(mid, t, sender, labels=("INBOX",), message_id=None, **kw):
    return dict(id=mid, internal_date=t, labels=list(labels), message_id=message_id or f"<{mid}>",
                subject="Re: topic", snippet=f"text of {mid} &amp; more", **{"from": sender}, **kw)


def selftest():
    me, peer = "me@example.invalid", "Peer <peer@example.invalid>"
    fails = []

    def check(label, cond):
        print(("[PASS] " if cond else "[FAIL] ") + label)
        if not cond:
            fails.append(label)

    parent = _row("P", 100, peer)
    newer = newer_counterpart([parent, _row("B", 200, peer)], "P", {me})
    check("newer counterpart after the parent is listed", [r["id"] for r in newer] == ["B"])
    check("older counterpart is not counted",
          newer_counterpart([_row("O", 50, peer), parent], "P", {me}) == [])
    own = [parent,
           _row("S", 200, me, ["SENT"], "<own>"),
           _row("L", 210, "list@example.invalid", message_id="<own>"),
           _row("U", 220, f"Me <{me.upper()}>"),
           _row("D", 230, me, ["DRAFT"])]
    check("own sent / list copy / own From / draft are not counterparts",
          newer_counterpart(own, "P", {me}) == [])
    alias = [parent, _row("A", 200, "alias@example.invalid")]
    check("each self address counts as own",
          newer_counterpart(alias, "P", {me, "alias@example.invalid"}) == [])
    two = [parent, _row("B2", 300, peer), _row("B", 200, peer)]
    check("oldest first", [r["id"] for r in newer_counterpart(two, "P", {me})] == ["B", "B2"])
    for label, rows, kw in [
            ("parent missing from the listing fails closed", [_row("B", 200, peer)], {}),
            ("missing internal_date fails closed", [parent, _row("B", None, peer)], {})]:
        try:
            newer_counterpart(rows, "P", {me}, **kw)
            check(label, False)
        except ValueError:
            check(label, True)
    check("parent date passed separately when the listing lacks it",
          [r["id"] for r in newer_counterpart([_row("B", 200, peer)], "P", {me}, 100)] == ["B"])
    b = newer_counterpart([parent, _row("B", 200, peer)], "P", {me})
    b2 = newer_counterpart(two, "P", {me})
    check("no newer: allowed without ack", notice([], "")[0] is True)
    check("newer without ack: refused", notice(b, "")[0] is False)
    check("ack of another id: refused", notice(b, "Z")[0] is False)
    check("ack of the newest id: allowed", notice(b, "B")[0] is True)
    check("later arrival makes the old ack stale", notice(b2, "B")[0] is False)
    lines = notice(b, "")[1]
    check("notice lists the id, unescapes the snippet, tells how to ack",
          "(id B)" in lines[1] and "text of B & more" in lines[1] and "--ack-newer B" in "\n".join(lines))
    ja = dict(EN, header="⚠️ {n} 通", refused="exit {exit}", no_newer_ack="(ack {ack}: 無し)")
    jl = notice(b, "", ja, lambda r: "JST", exit=6)[1]
    check("templates and extra values are substituted",
          jl[0] == "⚠️ 1 通" and jl[-1] == "exit 6" and "JST" in jl[1])
    check("ack with nothing newer can be noted", notice([], "X", ja)[1] == ["(ack X: 無し)"])

    # 自分がもう送った返事 (二重返信を止める呼び手が使う、 2026-11-02)
    check("own sent reply after the parent is listed",
          [r["id"] for r in newer_own_sent([parent, _row("S", 200, me, ["SENT"])], "P")] == ["S"])
    check("draft / list copy / own From without SENT are not own sent replies",
          [r["id"] for r in newer_own_sent(own, "P")] == ["S"]
          and newer_own_sent([parent, _row("D", 230, me, ["DRAFT"])], "P") == [])
    check("own sent reply older than the parent is not counted",
          newer_own_sent([_row("S0", 50, me, ["SENT"]), parent], "P") == [])
    mixed_rows = [parent, _row("S", 300, me, ["SENT"]), _row("B", 200, peer)]
    mixed = newer_in_thread(mixed_rows, "P", {me})
    check("counterpart and own sent are merged oldest first, own marked",
          [(r["id"], bool(r.get("own"))) for r in mixed] == [("B", False), ("S", True)])
    check("marking own does not change the input rows", "own" not in mixed_rows[1])
    check("counterpart-only callers still ignore own sent replies",
          newer_counterpart(mixed_rows, "P", {me})[-1]["id"] == "B")
    only_own = newer_in_thread([parent, _row("S", 200, me, ["SENT"])], "P", {me})
    ol = notice(only_own, "")[1]
    check("own sent reply alone refuses without ack", notice(only_own, "")[0] is False)
    check("ack of the own sent reply's id: allowed", notice(only_own, "S")[0] is True)
    check("notice marks the own reply and says the newest is own (no switch line)",
          EN["own_mark"] in ol[1] and any(EN["own_note"].format(k=1) == x for x in ol)
          and EN["own_latest"].format(latest="S") in ol and EN["switch"].format(latest="S") not in ol)
    ml = notice(mixed, "")[1]
    check("counterpart lines carry no own mark",
          EN["own_mark"] not in ml[1] and EN["own_mark"] in ml[2])
    raw = [{"id": "g1", "internalDate": "1700", "labelIds": ["INBOX"], "snippet": "s",
            "payload": {"headers": [{"name": "From", "value": "a"}, {"name": "Message-ID", "value": "<g1>"}]}},
           {"id": "g2", "payload": {"headers": []}}]
    rows = rows_from_gmail_thread(raw)
    check("gmail rows keep fields and leave a missing date as None",
          rows[0]["internal_date"] == 1700 and rows[0]["message_id"] == "<g1>"
          and rows[0]["labels"] == ["INBOX"] and rows[1]["internal_date"] is None)
    print(f"\n{'FAIL' if fails else 'OK'}: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(selftest() if sys.argv[1:] in ([], ["--selftest"]) else 2)
