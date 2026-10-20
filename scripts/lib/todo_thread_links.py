#!/usr/bin/env python3
"""todo_thread_links.py — 台帳の項目 (TODO) と mail thread を結ぶ link の読み方 (単一 home)。

なぜ存在するか (一般形、 実測は下の層の記録):
  「この TODO の thread に相手の返事が来ているか」 を見る検出器と、 その thread に記録を足す道具は、
  同じ link を同じ読み方で辿らないと片方だけが取りこぼす。 link の経路は 3 本ある:
    (1) TODO の `cross_ref` が inbox entry を指す (`<repo>/inbox:<id>` / `inbox/<file>.yaml:<id>`) → その entry の threadId
    (2) TODO の `email_ref` に threadId / messageId が書いてある (返信の messageId でも可 = 呼び手が thread に引き直す)
    (3) 逆引き: inbox entry の側が `cross_ref` の `TODO:<id>` か `related_todo` (裸 id / `<repo>/TODO:<id>`) で
        この TODO を指している (= 親 TODO が forward link を持たない新 thread の救援経路)
  片方の経路だけ読む / 読むが正規化しない、 が過去の取りこぼしの型 (一般則 = data-pipeline-automation.md
  #multipath-key-normalization)。 本 module に 3 経路と正規化を置き、 検出器と道具の両方が import する。

引き継ぎ (handover): 子の項目を閉じるとき、 続きを「続きは親の項目 <id> へ」 と現在地 (`status_context`) の文で
  渡すことがある。 その文は link にならない = 子に結ばれていた thread に閉じた後で返事が来ると、 どの開いた項目にも
  結ばれず、 続報として親に届かない (実測。 閉じた後の返事が親に結ばれない新しい項目として起票され、 親の現在地に
  入らなかった)。 → `handover_map` が「閉じた項目の現在地が名指す開いた項目」 を引き、
  `resolve_threads(..., handed_over=...)` がその閉じた子の thread も親の thread として返す (1 段だけ。 名指しは
  開いた項目の id の完全一致 = 前後が id の文字でない所。 閉じた項目の notes は読まない = 経緯の文の id を拾わない)。

欄の注記への耐性: threadId / account の欄には人の注記が混ざる (「<id> (誰々) / <id>」 / 「lab (= Cc で受信)」)。
  そのまま Gmail に渡すと 400 / 認証なしで黙って失敗するので、 読む側で id と account だけを取り出す
  (書く側の欄は直さない = 注記は人のための記録)。

使い方:
    from todo_thread_links import harvest_todo_refs, resolve_threads, thread_ids, norm_account, owner_from
    inverse = {}; for eid, e in entries: for t in harvest_todo_refs(e): inverse.setdefault(t, []).append(eid)
    pairs = resolve_threads(todo, inbox_by_id, inverse, known_accounts=("a", "b"), default_account="a")
    python3 todo_thread_links.py            # selftest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recorded_ids import harvest_text  # noqa: E402

# cross_ref / related_todo の TODO pointer: "TODO:<id>" と "<repo>/TODO:<id>" の両方
TODO_REF_RE = re.compile(r"(?:^|/)TODO:([^\s\"]+)")
# cross_ref の inbox entry pointer: "<repo>/inbox:<id>" と "inbox/<file>.yaml:<id>" の両方
INBOX_REF_RE = re.compile(r"inbox(?:/[^:\s]*\.yaml)?:([^\s\"]+)")
GMAIL_ID_RE = re.compile(r"\b[0-9a-f]{16}\b")


def harvest_todo_refs(entry: dict) -> list[str]:
    """inbox entry → この entry が link する TODO id の list (順序保持・重複なし。 cross_ref の TODO: と related_todo の両方)。"""
    out: list[str] = []
    for cr in entry.get("cross_ref") or []:
        if isinstance(cr, str):
            m = TODO_REF_RE.search(cr)
            if m:
                out.append(m.group(1).strip())
    for rt in entry.get("related_todo") or []:
        if isinstance(rt, str) and rt.strip():
            m = TODO_REF_RE.search(rt)
            out.append(m.group(1).strip() if m else rt.strip())
    seen: set[str] = set()
    uniq: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def thread_ids(v) -> list[str]:
    """threadId 欄 → id の list (注記の無い 1 語はそのまま、 注記つきは 16 進の完全一致だけ)。"""
    if not isinstance(v, str) or not v.strip():
        return []
    s = v.strip()
    if not re.search(r"[\s(（/]", s):
        return [s]
    return GMAIL_ID_RE.findall(s)


def norm_account(v, known_accounts=()) -> str | None:
    """account 欄 → alias (注記の無い 1 語はそのまま、 注記つきは先頭の英字語が known_accounts にあればそれ)。"""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", s):
        return s
    m = re.match(r"([A-Za-z0-9_-]+)", s)
    return m.group(1) if m and m.group(1) in known_accounts else None


def email_ref_accounts(er: str, known_accounts=()) -> dict[str, str]:
    """email_ref の文 → {id: alias}。 各 id の直後から次の id までの注記に known_accounts の alias が
    単語として出ていれば、 それをその id の account にする (「<id> (AJO acct-a) + <id> (本人acct-b)」 型)。"""
    out: dict[str, str] = {}
    if not isinstance(er, str) or not known_accounts:
        return out
    ms = list(GMAIL_ID_RE.finditer(er))
    for i, m in enumerate(ms):
        tail = er[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(er)]
        for alias in known_accounts:
            if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(alias)}(?![A-Za-z0-9_-])", tail):
                out[m.group(0)] = alias
                break
    return out


def owner_from(from_header: str, owner_tokens=()) -> bool:
    """From ヘッダが自分 (owner) か (= owner_tokens のどれかを lower 化した From に含む)。"""
    f = (from_header or "").lower()
    return any(tok.lower() in f for tok in owner_tokens)


_ID_CHAR = r"A-Za-z0-9_-"


def handover_targets(todo: dict, open_ids) -> list[str]:
    """閉じた項目 todo の現在地 (status_context) が名指す、 開いた項目の id (open_ids の中だけ。 文の中の出現順・重複なし・
    自分を除く)。 呼び手は閉じた項目にだけ呼ぶ (開いた項目の現在地が他の項目を名指すのは引き継ぎではない)。"""
    sc = todo.get("status_context")
    if not isinstance(sc, str) or not sc:
        return []
    me = todo.get("id")
    hits: list[tuple[int, str]] = []
    for oid in open_ids:
        if not isinstance(oid, str) or not oid or oid == me:
            continue
        m = re.search(rf"(?<![{_ID_CHAR}]){re.escape(oid)}(?![{_ID_CHAR}])", sc)
        if m:
            hits.append((m.start(), oid))
    return [oid for _pos, oid in sorted(hits)]


def handover_map(todos, is_open) -> dict[str, list[dict]]:
    """項目の list → {開いた項目の id: [その id へ続きを渡した閉じた項目]} (純関数)。 is_open(todo) -> bool は呼び手の
    status の語彙で判定する (本 module は status の語を持たない)。 1 段だけ (閉じた → 閉じた の連鎖は辿らない)。"""
    rows = [t for t in todos if isinstance(t, dict)]
    open_ids = {t.get("id") for t in rows if is_open(t) and isinstance(t.get("id"), str)}
    out: dict[str, list[dict]] = {}
    for t in rows:
        if is_open(t):
            continue
        for oid in handover_targets(t, open_ids):
            out.setdefault(oid, []).append(t)
    return out


def resolve_threads(todo: dict, inbox_by_id: dict, inverse_by_todo: dict | None = None,
                    known_accounts=(), default_account: str | None = None,
                    handed_over=()) -> list[tuple[str, str]]:
    """TODO → [(threadId, account)]。 経路 (1) cross_ref の inbox 参照 → (2) email_ref → (3) 逆引き
    → (4) 引き継ぎ = handed_over (この TODO へ続きを渡した閉じた項目、 handover_map の値) の (1)〜(3) の thread。

    inbox_by_id: entry id → {"threadId": str|None, "account": str|None}。
    account は entry の欄から (注記は norm_account で剥がす)、 無ければ default_account
    (= それも無ければ known_accounts の先頭、 それも無ければ "" = 呼び手が決める)。
    email_ref の id の account は、 その id の直後の注記に書いた alias (「<id> (… personal)」) →
    その id を threadId に持つ inbox entry の account → default の順 (= 注記を読まずに default を当てると、
    別 account の thread を違う account で引いて 404 になる。 実測 = 2 つの account の id を並べた email_ref)。
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    default = default_account or (known_accounts[0] if known_accounts else "")
    thread_account: dict[str, str] = {}
    for meta in inbox_by_id.values():
        a = norm_account((meta or {}).get("account"), known_accounts)
        if a:
            for tid in thread_ids((meta or {}).get("threadId")):
                thread_account.setdefault(tid, a)

    for cr in todo.get("cross_ref") or []:
        if not isinstance(cr, str):
            continue
        m = INBOX_REF_RE.search(cr)
        if not m:
            continue
        meta = inbox_by_id.get(m.group(1).strip())
        if not meta:
            continue
        acct = norm_account(meta.get("account"), known_accounts)
        if acct:
            default = acct
        for tid in thread_ids(meta.get("threadId")):
            if tid not in seen:
                seen.add(tid)
                out.append((tid, acct or default))

    er = todo.get("email_ref")
    if isinstance(er, str):
        annotated = email_ref_accounts(er, known_accounts)
        for tid in sorted(harvest_text(er)):
            if tid not in seen:
                seen.add(tid)
                out.append((tid, annotated.get(tid) or thread_account.get(tid) or default))

    todo_id = todo.get("id")
    if inverse_by_todo and isinstance(todo_id, str):
        for eid in inverse_by_todo.get(todo_id, ()):
            meta = inbox_by_id.get(eid)
            if not meta:
                continue
            for tid in thread_ids(meta.get("threadId")):
                if tid not in seen:
                    seen.add(tid)
                    out.append((tid, norm_account(meta.get("account"), known_accounts) or default))

    for child in handed_over or ():
        if not isinstance(child, dict) or child.get("id") == todo_id:
            continue
        for tid, acct in resolve_threads(child, inbox_by_id, inverse_by_todo,
                                         known_accounts=known_accounts, default_account=default_account):
            if tid not in seen:
                seen.add(tid)
                out.append((tid, acct))
    return out


def selftest() -> int:
    fails = []

    def expect(label, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        if not cond:
            fails.append(label)

    e = {"cross_ref": ["ledger-a/TODO:t-1", "other/inbox:x"], "related_todo": ["t-2", "ledger-b/TODO:t-3", "t-1"]}
    expect("harvest_todo_refs = cross_ref の TODO: + related_todo (裸 / prefix)、 順序保持・重複なし",
           harvest_todo_refs(e) == ["t-1", "t-2", "t-3"])
    expect("thread_ids: 注記なしはそのまま", thread_ids("aaaa000000000001") == ["aaaa000000000001"])
    expect("thread_ids: 注記つきは 16 進だけ", thread_ids("aaaa000000000001 (誰々) / aaaa000000000002") == ["aaaa000000000001", "aaaa000000000002"])
    expect("norm_account: 注記つきは known の先頭語", norm_account("acct-a (= Cc で受信)", ("acct-a",)) == "acct-a"
           and norm_account("zzz (x)", ("acct-a",)) is None and norm_account("acct-b", ()) == "acct-b")
    expect("owner_from: token の lower 部分一致", owner_from("Owner <owner@example.org>", ("owner@",)) and not owner_from("x@y", ("owner@",)))
    by_id = {"e1": {"threadId": "aaaa000000000001", "account": "acct-b"},
             "e2": {"threadId": "aaaa000000000002 (注記)", "account": None},
             "e3": {"threadId": "aaaa000000000003", "account": "acct-a"}}
    inverse = {"t-1": ["e3"]}
    todo = {"id": "t-1", "cross_ref": ["ledger-a/inbox:e1", "inbox/2026-01.yaml:e2"],
            "email_ref": "threadId:aaaa000000000004 / messageId:aaaa000000000005"}
    got = resolve_threads(todo, by_id, inverse, known_accounts=("acct-a", "acct-b"), default_account="acct-a")
    expect("resolve_threads: (1) cross_ref の 2 形式 → entry の threadId と account (注記は剥がす、 account 無しは直前の account)",
           got[:2] == [("aaaa000000000001", "acct-b"), ("aaaa000000000002", "acct-b")])
    expect("resolve_threads: (2) email_ref の threadId / messageId", set(got[2:4]) == {("aaaa000000000004", "acct-b"), ("aaaa000000000005", "acct-b")})
    expect("resolve_threads: (3) 逆引き (related_todo / cross_ref TODO: で指す entry)", got[4] == ("aaaa000000000003", "acct-a") and len(got) == 5)
    got2 = resolve_threads({"email_ref": "messageId:aaaa000000000007 (note acct-b) + messageId:aaaa000000000008 (本人acct-c)"},
                           {}, None, known_accounts=("acct-a", "acct-b", "acct-c"), default_account="acct-a")
    expect("resolve_threads: email_ref の id ごとの注記の alias を account にする (default に倒さない)",
           sorted(got2) == [("aaaa000000000007", "acct-b"), ("aaaa000000000008", "acct-c")])
    got3 = resolve_threads({"email_ref": "messageId:aaaa000000000009"}, {"e9": {"threadId": "aaaa000000000009", "account": "acct-c"}},
                           None, known_accounts=("acct-a", "acct-c"), default_account="acct-a")
    expect("resolve_threads: 注記が無ければ、 その id を threadId に持つ inbox entry の account", got3 == [("aaaa000000000009", "acct-c")])
    expect("email_ref_accounts: alias は単語としてだけ (他の語の一部は拾わない)",
           email_ref_accounts("aaaa00000000000a (grant) / aaaa00000000000b (gr)", ("gr",)) == {"aaaa00000000000b": "gr"})
    expect("resolve_threads: 何も無ければ空、 default は known の先頭",
           resolve_threads({"id": "t-9"}, by_id, None, known_accounts=("acct-a",)) == []
           and resolve_threads({"email_ref": "threadId:aaaa000000000006"}, {}, None, known_accounts=("acct-a",)) == [("aaaa000000000006", "acct-a")])

    # 引き継ぎ: 閉じた子の現在地が開いた親の id を名指す → 親の thread に子の thread を足す
    is_open = lambda t: t.get("status") != "done"  # noqa: E731
    parent = {"id": "2030-01-01-parent", "status": "open", "email_ref": "threadId:aaaa0000000000a1"}
    child = {"id": "2030-02-01-child", "status": "done", "email_ref": "threadId:aaaa0000000000b1",
             "status_context": "済。 続きは親 2030-01-01-parent へ (2030-01-01-parent-old は別件)"}
    other = {"id": "2030-02-02-other", "status": "done", "status_context": "2030-01-01-parentx と 2030-01-01-paren は別の id"}
    child_of_inbox = {"id": "2030-02-03-viainbox", "status": "done", "status_context": "→ 2030-01-01-parent"}
    hm = handover_map([parent, child, other, child_of_inbox], is_open)
    expect("handover_map: 閉じた子が名指す開いた id だけ (前後が id の文字の部分一致は拾わない、 開いた項目からは引かない)",
           sorted(t["id"] for t in hm.get("2030-01-01-parent", [])) == ["2030-02-01-child", "2030-02-03-viainbox"]
           and set(hm) == {"2030-01-01-parent"})
    expect("handover_targets: 開いた id の集合の外は拾わない・自分は拾わない",
           handover_targets(child, {"2030-01-01-parent-old"}) == ["2030-01-01-parent-old"]
           and handover_targets({"id": "x", "status_context": "x へ"}, {"x"}) == [])
    by_id_h = {"eh": {"threadId": "aaaa0000000000c1", "account": "acct-b"}}
    inv_h = {"2030-02-03-viainbox": ["eh"]}
    got_h = resolve_threads(parent, by_id_h, inv_h, known_accounts=("acct-a", "acct-b"), default_account="acct-a",
                            handed_over=hm["2030-01-01-parent"])
    expect("resolve_threads: (4) 引き継ぎ = 子の email_ref と、 子を指す inbox entry (逆引き) の thread も親の thread",
           [t for t, _a in got_h] == ["aaaa0000000000a1", "aaaa0000000000b1", "aaaa0000000000c1"]
           and dict(got_h)["aaaa0000000000c1"] == "acct-b")
    expect("resolve_threads: handed_over を渡さなければ従来どおり (親の thread だけ)",
           resolve_threads(parent, by_id_h, inv_h, known_accounts=("acct-a",)) == [("aaaa0000000000a1", "acct-a")])
    print(f"selftest: {'ALL PASS' if not fails else 'FAIL ' + str(len(fails))}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
