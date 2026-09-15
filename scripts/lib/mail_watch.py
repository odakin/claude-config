#!/usr/bin/env python3
"""mail_watch.py — 既知スレッドを辿るだけでは拾えない mail を拾う helper（待ち項目の検索条件 / 決着済み案件への自動督促の判定 / 本文 text の取り出し。 Gmail API の service を受け取る、 python3 mail_watch.py で selftest）

見落としの形は 2 つ (規約 = conventions/email-surface-pattern.md#new-thread-expected-inbound /
#settled-matter-key):

1. **待っている結果が別スレッドで来る**: 審査結果・受付通知・サポートの返事は no-reply の自動送信で、
   毎回 新しいスレッドになる。 「送った mail のスレッドに相手の新着があるか」 を見る返信待ちの網では
   原理的に拾えない。 → 待ち項目に Gmail の検索条件を持たせ、 当たった未記録 mail を出す
   (`watch_queries` / `unrecorded_threads`)。
2. **決着済みの案件に自動督促が来続ける**: 同じく毎回 別スレッドなので messageId / threadId の既知判定が
   効かず、 「未認識の義務 mail」 として再浮上する。 効く鍵は本文の案件 ID (招待 URL の UUID・原稿 ID・
   受付番号)。 → 決着済み項目の案件 ID が本文に入った **自動送信** の mail だけを畳む (`split_settled`)。
   人間発は畳まない (決着済み案件への人の新しい連絡は見たい)、 項目を open に戻せば畳まれなくなる。

呼び出し側が持つもの: 項目の読み込み (台帳の場所・形式)、 どの status を決着済みとするか、 表示。
本 module は判定と Gmail 呼び出しだけを持つ (API 失敗は全部 fail-open = 空を返す)。

    sys.path.insert(0, str(<claude-config>/"scripts"/"lib"))
    from mail_watch import watch_queries, unrecorded_threads, settled_matter_keys, split_settled
"""
from __future__ import annotations

import base64
import re
from typing import Callable, Iterable

SETTLED_STATUS_RE = re.compile(r"^\s*(完了|対応済|見送り|取り下げ|辞退|done|closed|declined|skipped)", re.I)
AUTOMATED_SENDER_RE = re.compile(
    r"no-?reply|do-?not-?reply|donotreply|notifications?@|mailer-daemon|automated|bounces?@", re.I)
MIN_KEY_LEN = 8


def watch_queries(item: dict, field: str = "watch_query") -> list[tuple[str, str]]:
    """項目の検索条件 → [(account, q)]。 形 = {account, q} か その list。 欠けた / 形の違う要素は捨てる。"""
    raw = item.get(field)
    out: list[tuple[str, str]] = []
    for it in raw if isinstance(raw, list) else [raw]:
        if isinstance(it, dict):
            acct, q = str(it.get("account") or "").strip(), str(it.get("q") or "").strip()
            if acct and q:
                out.append((acct, q))
    return out


def unrecorded_threads(service, q: str, known: set, limit: int = 20) -> list[str]:
    """検索に当たった message のうち、 messageId も threadId も known に無いものの threadId (重複除去)。"""
    try:
        res = service.users().messages().list(userId="me", q=q, maxResults=limit).execute()
    except Exception:
        return []
    out: list[str] = []
    for m in res.get("messages", []) or []:
        mid, tid = m.get("id"), m.get("threadId")
        if not tid or mid in known or tid in known or tid in out:
            continue
        out.append(tid)
    return out


def settled_matter_keys(items: Iterable[dict], status_field: str = "status", key_field: str = "matter_key",
                        id_field: str = "id", settled_re: re.Pattern = SETTLED_STATUS_RE) -> dict:
    """決着済み項目の案件 ID → 項目 id。 key は str か list、 MIN_KEY_LEN 未満は誤爆するので捨てる。"""
    out: dict = {}
    for e in items:
        if not isinstance(e, dict) or not settled_re.match(str(e.get(status_field, ""))):
            continue
        keys = e.get(key_field)
        for k in keys if isinstance(keys, list) else [keys]:
            if isinstance(k, str) and len(k.strip()) >= MIN_KEY_LEN:
                out[k.strip()] = str(e.get(id_field, "?"))
    return out


def is_automated_sender(from_header: str) -> bool:
    return bool(AUTOMATED_SENDER_RE.search(from_header or ""))


def matter_hit(item: dict, keys: dict, body: str = "") -> str | None:
    """自動送信 ∧ 案件 ID が件名 / snippet / 本文に入っていれば、 その項目 id。"""
    if not keys or not is_automated_sender(item.get("from", "")):
        return None
    hay = " ".join((item.get("subject", ""), item.get("snippet", ""), body or ""))
    for k, tid in keys.items():
        if k in hay:
            return tid
    return None


def message_body_text(service, mid: str) -> str:
    """本文 text (text/plain、 無ければ text/html の tag を除いたもの)。 取得失敗は空。"""
    try:
        m = service.users().messages().get(userId="me", id=mid, format="full").execute()
    except Exception:
        return ""
    plain: list[str] = []
    html: list[str] = []

    def walk(p: dict) -> None:
        data = (p.get("body") or {}).get("data")
        if data:
            try:
                txt = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
            except Exception:
                txt = ""
            if p.get("mimeType") == "text/plain":
                plain.append(txt)
            elif p.get("mimeType") == "text/html":
                html.append(txt)
        for c in p.get("parts") or []:
            walk(c)

    walk(m.get("payload") or {})
    return "\n".join(plain) if plain else re.sub(r"<[^>]+>", " ", "\n".join(html))


def split_settled(items: list, service, keys: dict,
                  fetch_body: Callable[[object, str], str] = message_body_text):
    """items → (残す, 畳む [(item, 項目 id)])。 本文を引くのは自動送信の item だけ、 key が無ければ何もしない。"""
    if not keys:
        return items, []
    keep, moved = [], []
    for it in items:
        if not is_automated_sender(it.get("from", "")):
            keep.append(it)
            continue
        tid = matter_hit(it, keys) or matter_hit(it, keys, fetch_body(service, it["id"]))
        if tid:
            moved.append((it, tid))
        else:
            keep.append(it)
    return keep, moved


def selftest() -> int:
    fails = []

    def expect(label, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        if not cond:
            fails.append(label)

    expect("watch_queries: dict / list、 欠けた要素は捨てる",
           watch_queries({"watch_query": {"account": "a", "q": "from:x"}}) == [("a", "from:x")]
           and watch_queries({"watch_query": [{"account": "a", "q": "y"}, {"account": "", "q": "z"}, "junk"]}) == [("a", "y")]
           and watch_queries({}) == [])

    class Fake:
        def __init__(self, res=None, boom=False, full=None):
            self.res, self.boom, self.full = res or {}, boom, full

        def users(self):
            return self

        def messages(self):
            return self

        def list(self, **_):
            self._mode = "list"
            return self

        def get(self, **_):
            self._mode = "get"
            return self

        def execute(self):
            if self.boom:
                raise RuntimeError("api")
            return self.res if self._mode == "list" else self.full

    svc = Fake({"messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"},
                             {"id": "m3", "threadId": "t1"}, {"id": "m4", "threadId": "tk"}]})
    expect("unrecorded_threads: 記録済み message / thread を除き重複なし", unrecorded_threads(svc, "q", {"m2", "tk"}) == ["t1"])
    expect("unrecorded_threads: API 失敗は空", unrecorded_threads(Fake(boom=True), "q", set()) == [])

    items = [{"id": "done", "status": "完了", "matter_key": "00000000-aaaa-bbbb-cccc-111111111111"},
             {"id": "open", "status": "待ち", "matter_key": "22222222-dddd-eeee-ffff-333333333333"},
             {"id": "skip", "status": "declined by owner", "matter_key": ["MS-ID-4444", "abc"]}]
    keys = settled_matter_keys(items)
    expect("settled_matter_keys: 決着済みだけ、 短い key は捨てる",
           keys == {"00000000-aaaa-bbbb-cccc-111111111111": "done", "MS-ID-4444": "skip"})
    at = "@" + "journal.example"  # 合成の送り手 (address literal を source に置かない = 公開 repo の Tier A)
    auto = {"id": "a1", "from": f"J <do-not-reply{at}>", "subject": "Reminder", "snippet": ""}
    human = {"id": "h1", "from": f"Editor <editor{at}>", "subject": "Reminder", "snippet": ""}
    body = "https://review.example/invite/00000000-aaaa-bbbb-cccc-111111111111"
    expect("matter_hit: 自動送信 ∧ 本文に key", matter_hit(auto, keys, body) == "done")
    expect("matter_hit: 人間発は対象外", matter_hit(human, keys, body) is None)
    expect("matter_hit: open の項目の key では畳まない",
           matter_hit(auto, keys, "https://review.example/invite/22222222-dddd-eeee-ffff-333333333333") is None)
    calls = []
    keep, moved = split_settled([auto, human], None, keys, fetch_body=lambda _s, mid: (calls.append(mid), body)[1])
    expect("split_settled: 自動送信だけ本文を引いて畳む",
           [i["id"] for i in keep] == ["h1"] and moved == [(auto, "done")] and calls == ["a1"])
    expect("split_settled: key が無ければ何もしない", split_settled([auto], None, {}, fetch_body=lambda *_: 1 / 0) == ([auto], []))

    enc = lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    full = {"payload": {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/html", "body": {"data": enc("<p>html only</p>")}}]}}
    expect("message_body_text: plain が無ければ html の tag を除く", "html only" in message_body_text(Fake(full=full), "x"))
    full2 = {"payload": {"parts": [{"mimeType": "text/plain", "body": {"data": enc("plain wins")}},
                                   {"mimeType": "text/html", "body": {"data": enc("<b>no</b>")}}]}}
    expect("message_body_text: plain を優先", message_body_text(Fake(full=full2), "x") == "plain wins")
    expect("message_body_text: 取得失敗は空", message_body_text(Fake(boom=True), "x") == "")
    print("mail_watch selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
