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


def owner_from(from_header: str, owner_tokens=()) -> bool:
    """From ヘッダが自分 (owner) か (= owner_tokens のどれかを lower 化した From に含む)。"""
    f = (from_header or "").lower()
    return any(tok.lower() in f for tok in owner_tokens)


def resolve_threads(todo: dict, inbox_by_id: dict, inverse_by_todo: dict | None = None,
                    known_accounts=(), default_account: str | None = None) -> list[tuple[str, str]]:
    """TODO → [(threadId, account)]。 経路 (1) cross_ref の inbox 参照 → (2) email_ref → (3) 逆引き。

    inbox_by_id: entry id → {"threadId": str|None, "account": str|None}。
    account は entry の欄から (注記は norm_account で剥がす)、 無ければ default_account
    (= それも無ければ known_accounts の先頭、 それも無ければ "" = 呼び手が決める)。
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    default = default_account or (known_accounts[0] if known_accounts else "")

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
        for tid in sorted(harvest_text(er)):
            if tid not in seen:
                seen.add(tid)
                out.append((tid, default))

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
    expect("resolve_threads: 何も無ければ空、 default は known の先頭",
           resolve_threads({"id": "t-9"}, by_id, None, known_accounts=("acct-a",)) == []
           and resolve_threads({"email_ref": "threadId:aaaa000000000006"}, {}, None, known_accounts=("acct-a",)) == [("aaaa000000000006", "acct-a")])
    print(f"selftest: {'ALL PASS' if not fails else 'FAIL ' + str(len(fails))}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
