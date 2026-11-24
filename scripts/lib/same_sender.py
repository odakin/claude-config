#!/usr/bin/env python3
"""same_sender.py — 扱っている便の相手 (差出人・宛先) から届いて、 まだ記録していない受信を並べる (相手の照合の述語と Gmail の検索。 --selftest)

なぜ要るか (一般形):
  ある相手の 1 通を記録する・返す turn は、 同じ相手の隣の便を読む最も安い機会である。 記録・返信の道具が「この相手を
  見張っている開いた項目」 だけを出し、 同じ相手から届いて未記録の便を出さないと、 相手を扱った turn の後も、 同じ相手の
  一斉の依頼・催促 (宛名に名前が無く、 件名に決まった語も無い便) は受信箱に残ったまま読まれない (実測 = 相手の 1 通を記録して
  返事を送った turn の時点で、 同じ差出人の未記録の便が何通も残っていた)。 規約 = docs/convention-design-principles.md
  #broadcast-obligation-blind-spot。

相手の照合 (keys_for / from_hits):
  address は小文字で比べる。 domain で引くのは、 無料のメール・本人の所属 (own_domains と subdomain)・大学と公の機関
  (`ac` / `edu` / `go` / `lg` / `gov` の段を持つ domain) でない domain だけ (= 組織の窓口が人ごとに address を変える相手)。
  それ以外は address の完全一致だけ (同じ大学の別の人の便を同じ相手にしない)。 自動送信の address (no-reply など) は鍵にしない
  (通知の便を全部並べない)。 本人の所属の domain は呼び出し側 (個人の層) が渡す。

記録済みの判定 (pick):
  message の id が known (台帳から集めた記録済みの id = messageId ∪ threadId、 recorded_ids.harvest_entry と同じ集合) に
  あれば記録済み。 thread の id の一致では落とさない (記録済みの thread に後から届いた催促は未記録 = recorded_ids の読み手の述語)。
  今記録している thread (exclude_threads) と、 今扱っている message (exclude_ids) は並べない。

使い手 (呼び出し側が known・account・Gmail の service・本人の所属を渡す):
  - 記録の道具 (scripts/record-reply.py、 --same-sender-days / --same-sender-own-domain)
  - 送る前の照会・受付の記録の道具 (個人の層の配線)

    sys.path.insert(0, str(<claude-config>/"scripts"/"lib"))
    import same_sender as ss
    addrs, doms, _ = ss.keys_for(ss.addresses(from_header), own_domains=("example.ac.jp",))
    items, err = ss.scan(service, addrs, doms, known, days=30, exclude_threads={tid})
    for line in ss.lines(items, days=30): print(line)
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from mail_watch import AUTOMATED_SENDER_RE as _AUTO_RE
except ImportError:  # 自動送信の判定が無くても照合はできる (鍵から外さないだけ)
    _AUTO_RE = re.compile(r"no-?reply|do-?not-?reply|donotreply|notifications?@|mailer-daemon|bounces?@", re.IGNORECASE)

FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.co.jp", "yahoo.com", "ymail.com", "outlook.com", "outlook.jp",
             "hotmail.com", "hotmail.co.jp", "live.com", "live.jp", "msn.com", "icloud.com", "me.com", "mac.com",
             "aol.com", "proton.me", "protonmail.com", "gmx.com", "gmx.de", "qq.com", "163.com", "126.com",
             "naver.com", "docomo.ne.jp", "ezweb.ne.jp", "au.com", "softbank.ne.jp", "i.softbank.jp", "nifty.com"}
INSTITUTION_LABELS = {"ac", "edu", "go", "lg", "gov"}
ADDR_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DEFAULT_DAYS = 30
LIST_LIMIT = 50        # 検索に当てる message の上限 (新しい順)
META_LIMIT = 20        # metadata を引く未記録の message の上限
SHOW_CAP = 5           # 件名を並べる上限 (超えた分は「ほか N 通」)
MARK = "🔎"            # 行の頭の印 (通知の見張りが拾う印 🚨 / 🔴 / ⚠️ / ❗ / 🔥 は使わない = 知らせるだけの行)


def addresses(*fields) -> list[str]:
    """欄 (From / To / Cc の header の文字列など) から address を小文字で、 出た順に重複なしで。"""
    out: list[str] = []
    for f in fields:
        for a in ADDR_RE.findall(str(f or "")):
            a = a.lower()
            if a not in out:
                out.append(a)
    return out


def domain_matchable(domain: str, own_domains=()) -> bool:
    """domain で引いてよい domain か (無料のメール・本人の所属・大学と公の機関でない)。"""
    d = (domain or "").lower()
    if d in FREE_MAIL or any(d == o or d.endswith("." + o) for o in own_domains or ()):
        return False
    return not (set(d.split(".")) & INSTITUTION_LABELS)   # 最後の段も見る (`.edu` / `.gov` は最後の段)


def keys_for(addrs, own_domains=(), own_addrs=(), drop_automated: bool = False) -> tuple[list[str], list[str], list[str]]:
    """(address の list, domain で引く domain の list, domain で引かない domain の list)。
    own_addrs = 鍵から外す本人の address。 drop_automated = 自動送信の address (no-reply など) を鍵から外す。"""
    own = {a.lower() for a in own_addrs or ()}
    keep = [a.lower() for a in addrs if a and a.lower() not in own
            and not (drop_automated and _AUTO_RE.search(a))]
    doms, skipped = [], []
    for a in keep:
        d = a.rsplit("@", 1)[1]
        (doms if domain_matchable(d, own_domains) else skipped).append(d)
    return keep, sorted(set(doms)), sorted(set(skipped))


def _addr_domain_hit(addr: str, doms) -> bool:
    d = addr.rsplit("@", 1)[-1]
    return any(d == x or d.endswith("." + x) for x in doms)


def from_hits(from_header: str, addrs, doms) -> bool:
    """From の address が相手 (address の完全一致か、 domain で引く domain とその subdomain) に当たるか。"""
    fa = addresses(from_header)
    return any(a in set(addrs) or _addr_domain_hit(a, doms) for a in fa)


def gmail_query(addrs, doms, days: int = DEFAULT_DAYS) -> str:
    """相手から届いた受信の Gmail の検索。 鍵が無ければ空。 domain で引く相手の address は domain に含まれるので並べない。"""
    terms = list(doms) + [a for a in addrs if not _addr_domain_hit(a, doms)]
    if not terms:
        return ""
    return f"in:inbox newer_than:{int(days)}d (" + " OR ".join(f"from:{t}" for t in terms) + ")"


def keys_label(addrs, doms) -> str:
    """表示用の相手の鍵 (domain で引く domain と、 それに含まれない address)。"""
    return ", ".join(list(doms) + [a for a in addrs if not _addr_domain_hit(a, doms)])


def pick(metas, known, addrs, doms, exclude_threads=(), exclude_ids=(), own_addrs=()) -> list[dict]:
    """metas = [{"id", "threadId", "from", "subject", "internal_ms"}] → 相手から届いた未記録の受信 (新しい順、 id の重複なし)。純関数。
    own_addrs = From が本人の address の受信は並べない (相手と本人が同じ組織の domain のとき)。"""
    known, ex_t, ex_i = set(known or ()), set(exclude_threads or ()), set(exclude_ids or ())
    own = {a.lower() for a in own_addrs or ()}
    out, seen = [], set()
    for m in metas or []:
        mid, tid = m.get("id"), m.get("threadId") or m.get("id")
        if not mid or mid in seen or mid in known or mid in ex_i or tid in ex_t:
            continue
        if not from_hits(m.get("from") or "", addrs, doms) or set(addresses(m.get("from"))) & own:
            continue
        seen.add(mid)
        out.append({k: m.get(k) for k in ("id", "threadId", "from", "subject", "internal_ms")})
    return sorted(out, key=lambda x: -(int(x.get("internal_ms") or 0)))


def _hdr(raw: dict, name: str) -> str:
    for h in (raw.get("payload") or {}).get("headers", []) or []:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value") or "")
    return ""


def scan(service, addrs, doms, known, days: int = DEFAULT_DAYS, exclude_threads=(), exclude_ids=(),
         list_limit: int = LIST_LIMIT, meta_limit: int = META_LIMIT, own_addrs=()) -> tuple[list[dict], str]:
    """Gmail を検索して pick する。 -> (未記録の受信, 失敗の理由 〔空 = 引けた〕)。 読むだけ (既読・label を変えない)。
    記録済み・除外の id は metadata を引かない (検索の 1 回 + 未記録の通数ぶんの get)。"""
    q = gmail_query(addrs, doms, days)
    if not q or service is None:
        return [], ("" if not q else "Gmail の service が無い")
    try:
        res = service.users().messages().list(userId="me", q=q, maxResults=list_limit).execute()
    except Exception as e:  # noqa: BLE001 — 知らせるだけの段 = 失敗は理由を返して呼び出し側が 1 行出す
        return [], f"検索に失敗 ({type(e).__name__})"
    known_s, ex_t, ex_i = set(known or ()), set(exclude_threads or ()), set(exclude_ids or ())
    todo = [m for m in res.get("messages", []) or []
            if m.get("id") not in known_s and m.get("id") not in ex_i and (m.get("threadId") or m.get("id")) not in ex_t]
    metas, err = [], ""
    for m in todo[:meta_limit]:
        try:
            raw = service.users().messages().get(userId="me", id=m["id"], format="metadata",
                                                 metadataHeaders=["From", "Subject"]).execute()
        except Exception as e:  # noqa: BLE001
            err = f"一部の metadata を引けなかった ({type(e).__name__})"
            continue
        metas.append({"id": raw.get("id"), "threadId": raw.get("threadId"), "from": _hdr(raw, "From"),
                      "subject": _hdr(raw, "Subject"), "internal_ms": int(raw.get("internalDate") or 0)})
    if len(todo) > meta_limit:
        err = (err + " / " if err else "") + f"未記録の候補 {len(todo)} 通のうち新しい {meta_limit} 通だけ見た"
    return pick(metas, known_s, addrs, doms, ex_t, ex_i, own_addrs), err


def _md(ms) -> str:
    try:
        d = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).astimezone()
        return f"{d.month}/{d.day}"
    except Exception:
        return "?"


def lines(items, days: int = DEFAULT_DAYS, cap: int = SHOW_CAP, err: str = "", who: str = "同じ差出人",
          scope: str = "") -> list[str]:
    """表示行。 未記録が 0 で失敗も無ければ空。 件名は 1 行に並べ、 その下に読み方の 1 行。 scope = 括弧の頭に足す句 (相手・account)。"""
    out = []
    if items:
        shown = " / ".join(f"{_md(x.get('internal_ms'))} {(x.get('subject') or '(件名なし)').strip()[:50]}" for x in items[:cap])
        more = f" ほか {len(items) - cap} 通" if len(items) > cap else ""
        out.append(f"{MARK} {who}の未記録 {len(items)} 通 ({scope + '、 ' if scope else ''}受信箱 {days} 日、 台帳に messageId が無い):"
                   f" {shown}{more}")
        out.append("   = 扱っている相手の隣の便。 読んで、 要るものは記録・TODO にする (この行は記録しない。"
                   f" id = {', '.join(str(x.get('id')) for x in items[:cap])})")
    if err:
        out.append(f"{MARK} {who}の未記録の照会: {err}")
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

    check(addresses("A <X\x40Example.COM>", "x@example.com, y@example.net") == ["x@example.com", "y@example.net"],
          "address: 小文字で、 出た順に重複なし")
    a, d, s = keys_for(["office@example.com", "a\x40gmail.com", "b\x40phys.uni.ac.jp", "c\x40agency.go.jp", "e\x40cs.uni-x.edu",
                        "me\x40own.example.jp", "x\x40dept.own.example.jp"], own_domains=("own.example.jp",), own_addrs=("me\x40own.example.jp",))
    check(d == ["example.com"] and "me\x40own.example.jp" not in a and "x\x40dept.own.example.jp" in a,
          "鍵: 組織の domain だけ domain で引く。 無料のメール・大学・公の機関・本人の所属 (subdomain も) は address だけ。 本人は鍵にしない")
    check(keys_for(["noreply@example.net", "desk@example.net"], drop_automated=True)[0] == ["desk@example.net"],
          "鍵: 自動送信の address は外せる")
    check(from_hits("Office <office@example.com>", ["x@example.com"], ["example.com"])
          and from_hits("Desk <desk\x40mail.example.com>", [], ["example.com"])
          and not from_hits("Other <o\x40myexample.com>", [], ["example.com"])
          and from_hits("B <b\x40phys.uni.ac.jp>", ["b\x40phys.uni.ac.jp"], [])
          and not from_hits("C <c\x40phys.uni.ac.jp>", ["b\x40phys.uni.ac.jp"], []),
          "照合: domain は一致と subdomain だけ (部分の一致は当てない)、 大学は address の完全一致だけ")
    q = gmail_query(["x@example.com", "b\x40phys.uni.ac.jp"], ["example.com"], 30)
    check(q == "in:inbox newer_than:30d (from:example.com OR from:b\x40phys.uni.ac.jp)" and gmail_query([], [], 30) == "",
          "検索: domain で引く相手は domain だけ、 それ以外は address、 鍵が無ければ空")
    metas = [
        {"id": "m1", "threadId": "t1", "from": "Office <office@example.com>", "subject": "Urgent: form", "internal_ms": 1000},
        {"id": "m2", "threadId": "t1", "from": "Office <office@example.com>", "subject": "Re: Urgent: form", "internal_ms": 3000},
        {"id": "m3", "threadId": "t3", "from": "Office <office@example.com>", "subject": "Schedule", "internal_ms": 2000},
        {"id": "m4", "threadId": "t4", "from": "Office <office@example.com>", "subject": "記録済み", "internal_ms": 4000},
        {"id": "m5", "threadId": "t5", "from": "Other <o@example.net>", "subject": "別の相手", "internal_ms": 5000},
        {"id": "m6", "threadId": "t6", "from": "Office <office@example.com>", "subject": "今扱っている thread", "internal_ms": 6000},
    ]
    got = pick(metas, {"m4", "t1"}, ["office@example.com"], ["example.com"], exclude_threads={"t6"})
    check([x["id"] for x in got] == ["m2", "m3", "m1"],
          "未記録: messageId が known に無い相手の受信を新しい順に。 thread の id の一致では落とさない (記録済みの thread の催促も出す)。"
          " 今記録している thread・別の相手は出さない")
    check(pick(metas + [{"id": "m7", "threadId": "t7", "from": "Me <me@example.com>", "subject": "自分", "internal_ms": 9000}],
               set(), [], ["example.com"], own_addrs={"me@example.com"})[0]["id"] == "m6"
          and keys_label(["x@example.com", "b\x40phys.uni.ac.jp"], ["example.com"]) == "example.com, b\x40phys.uni.ac.jp",
          "未記録: From が本人の受信は並べない・表示の鍵は domain と、 それに含まれない address")
    ln = lines(got, 30)
    check(ln[0].startswith(f"{MARK} 同じ差出人の未記録 3 通 (受信箱 30 日") and "Re: Urgent: form" in ln[0] and "m2, m3, m1" in ln[1],
          "表示: 件名を新しい順に並べ、 次の行に id")
    check(lines(got, 30, scope="相手 = example.com、 home")[0].startswith(f"{MARK} 同じ差出人の未記録 3 通 (相手 = example.com、 home、 受信箱 30 日"),
          "表示: scope は括弧の頭に入る")
    many = [dict(metas[0], id=f"x{i}", internal_ms=i) for i in range(8)]
    check("ほか 3 通" in lines(many, 30)[0] and lines([], 30) == [] and lines([], 30, err="検索に失敗 (X)")[0].endswith("検索に失敗 (X)"),
          "表示: 上限を超えた分は「ほか N 通」、 0 通で失敗も無ければ空、 失敗は 1 行で言う")

    class _Svc:   # Gmail の service の代わり (list と get だけ)
        def __init__(self, msgs):
            self.msgs, self.gets = msgs, []

        def users(self):
            return self

        def messages(self):
            return self

        def list(self, **kw):
            self.q = kw.get("q")
            return _Exec({"messages": [{"id": m["id"], "threadId": m["threadId"]} for m in self.msgs]})

        def get(self, **kw):
            self.gets.append(kw["id"])
            m = next(x for x in self.msgs if x["id"] == kw["id"])
            return _Exec({"id": m["id"], "threadId": m["threadId"], "internalDate": str(m["internal_ms"]),
                          "payload": {"headers": [{"name": "From", "value": m["from"]}, {"name": "Subject", "value": m["subject"]}]}})

    class _Exec:
        def __init__(self, v):
            self.v = v

        def execute(self):
            return self.v

    svc = _Svc(metas)
    items, err = scan(svc, ["office@example.com"], ["example.com"], {"m4"}, 30, exclude_threads={"t6"})
    check([x["id"] for x in items] == ["m2", "m3", "m1"] and err == "" and "m4" not in svc.gets and "m6" not in svc.gets
          and svc.q.startswith("in:inbox newer_than:30d"),
          "scan: 記録済み・除外の id は metadata を引かず、 pick と同じ結果")
    check(scan(None, ["a@example.net"], ["example.net"], set())[1] == "Gmail の service が無い" and scan(svc, [], [], set()) == ([], ""),
          "scan: service が無ければ理由を返し、 鍵が無ければ何もしない")
    print(f"\n==== RESULT: PASS={ok} FAIL={ng} ====")
    return 1 if ng else 0


if __name__ == "__main__":
    # 引数なしの直接実行も selftest を回す (検査の runner は lib の module を引数なしで実行する)
    sys.exit(_selftest())
