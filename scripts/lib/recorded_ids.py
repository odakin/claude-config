#!/usr/bin/env python3
"""recorded_ids.py — mail ledger の「記録済み message / thread id」 の書式の契約と harvest (単一 home)。

なぜ存在するか (一般形、 実測は下の層の記録):
  台帳 (YAML の entry 列) に message id を書く書式は、 生きた記録の可読性のために 1 つに固定できない
  (top-level の素値 / `email_ref: "messageId:x"` / log 行の短縮形 `mid:x` / 散文の `threadId:x`)。
  読み手 (未記録 mail の検出器) がそれぞれ独自の regex で「記録済み集合」 を作ると、 ある読み手だけが
  短縮形を読まず、 記録済みの mail を「未認識」 に出し続ける。 書式の読み取りを本 module 1 つに寄せ、
  house style の全書式の fixture を selftest で固定する (規約 = conventions/email-surface-pattern.md
  #recorded-id-notation、 一般則 = data-pipeline-automation.md#multipath-key-normalization)。

契約 (= harvest_entry の認識述語。 変更時は下の FIXTURES も同 commit で更新):
  1. top-level `messageId` / `threadId` / `thread_id` field の**素値** (= prefix 無し bare hex)
  2. entry の全 string 値 (入れ子の dict / list の中も) に対する prefix regex:
     - message id: `messageId:` / `mid:` (log 行の短縮形)
     - thread id:  `threadId:`
     `[:=]` 両対応、 直前は word boundary (= "pyramid:" 等の偶発 substring を弾く)。
  ⚠️ 認識**しない**もの (= 書き手側の禁止事項):
     - YAML コメント内の id (parser が捨てるため構造的に不可視。 記録は必ず値として書く)
     - prefix 無しの bare hex が散文中に単独出現 (偶発 hex 一致の偽 suppress を避ける)
  書き手の道具 (scripts/record-reply.py) が書く印 `recorded_upto: "messageId:<hex> (<日時>)"` と索引
  `messages: ["mid:<hex> <日時> ← <差出人>" / "… → <宛先>", …]` は契約 2 の中 (fixture で固定 = 道具の出力と読み手の述語が
  別々に動かない)。

harvest_message_ids = messageId だけの変種 (threadId を含めない)。 「message は未認識 ∧ thread は認識済」 を分けて
  出す読み手用。 threadId を混ぜると thread の root message (= 多くは threadId と同値) だけが「記録済み」 に見えて
  続報の未認識が隠れる。

使い方:
    from recorded_ids import MSGID_RE, THREADID_RE, harvest_entry, harvest_message_ids, harvest_text
    known |= harvest_entry(entry_dict)      # 台帳 entry 1 つ
    known |= harvest_text(free_text)        # yaml 外の散文
    python3 recorded_ids.py                 # selftest (= round-trip contract)。 消費者の delegation 検査は下の層の shim が持つ
"""
from __future__ import annotations

import re
import sys

# canonical 述語 (= 書き手 house style との round-trip は本 file の selftest が固定)
MSGID_RE = re.compile(r"\b(?:messageId|mid)[:=]\s*([a-fA-F0-9]+)")
THREADID_RE = re.compile(r"\bthreadId[:=]\s*([a-fA-F0-9]+)")
BARE_FIELDS = ("messageId", "threadId", "thread_id")   # 契約 1


def harvest_text(text: str) -> set[str]:
    """散文 blob から prefix 付き id を harvest。"""
    if not isinstance(text, str):
        return set()
    out: set[str] = set()
    out.update(MSGID_RE.findall(text))
    out.update(THREADID_RE.findall(text))
    return out


def iter_strings(v):
    """入れ子の dict / list をたどって string 値を全部返す (= key は返さない)。"""
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from iter_strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from iter_strings(x)


def harvest_entry(e: dict) -> set[str]:
    """YAML entry (dict) 1 つから既記録 id を harvest (= 素値 field ∪ blob prefix regex の union)。

    union の理由: blob prefix regex 単独では email_ref を持たない素値 field のみの entry が漏れ、
    素値 field 単独では log 行の mid: 併記 (= thread 続報の最安記録経路) が漏れる。 片方に「置換」 した
    fix が両方向とも FP を生んだ実測があるため、 必ず union で読む。
    """
    out: set[str] = set()
    if not isinstance(e, dict):
        return out
    for k in BARE_FIELDS:
        v = e.get(k)
        if isinstance(v, str) and v.strip():
            out.add(v.strip())
    out |= harvest_text("\n".join(iter_strings(e)))
    return out


def harvest_message_ids(e: dict) -> set[str]:
    """messageId だけの変種 (= threadId を含めない。 契約 1 の `messageId` 素値 ∪ 契約 2 の MSGID_RE)。"""
    out: set[str] = set()
    if not isinstance(e, dict):
        return out
    v = e.get("messageId")
    if isinstance(v, str) and v.strip():
        out.add(v.strip())
    for s in iter_strings(e):
        out.update(MSGID_RE.findall(s))
    return out


def harvest_yaml_list(entries: list) -> set[str]:
    """load 済み YAML list (台帳 file 1 本分) をまとめて harvest。"""
    out: set[str] = set()
    for e in entries or []:
        if isinstance(e, dict):
            out |= harvest_entry(e)
    return out


# ============================================================
# selftest (= round-trip contract)。 house style に書式を足したら**ここに fixture を足してから**書き始める。
# ============================================================
FIXTURES: list[tuple[str, dict, set[str]]] = [
    ("top-level messageId 素値", {"messageId": "aaaa000000000001"}, {"aaaa000000000001"}),
    ("top-level threadId 素値", {"threadId": "aaaa000000000002"}, {"aaaa000000000002"}),
    ("email_ref prefix + 説明括弧",
     {"email_ref": "messageId:aaaa000000000003 (受信) / messageId:aaaa000000000004 (返信)"},
     {"aaaa000000000003", "aaaa000000000004"}),
    ("log 行 mid: 短縮形 (list)", {"log": ["ack 受信 (mid:aaaa000000000005)、 対応不要"]}, {"aaaa000000000005"}),
    ("log 行 messageId: (list)", {"log": ["送信 (messageId:aaaa000000000006)"]}, {"aaaa000000000006"}),
    ("notes 散文 threadId:", {"notes": "同 thread (threadId:aaaa000000000007) に続報あり"}, {"aaaa000000000007"}),
    ("summary 内 mid=", {"summary": "決着 (mid=aaaa000000000008)"}, {"aaaa000000000008"}),
    ("任意 field の mid:", {"status_context": "追加連絡 (mid:aaaa000000000009) を反映"}, {"aaaa000000000009"}),
    ("素値 + log 併記の union",
     {"messageId": "aaaa00000000000a", "log": ["続報 (mid:aaaa00000000000b)"]},
     {"aaaa00000000000a", "aaaa00000000000b"}),
    ("全角括弧隣接 （messageId:…） (約物は非 \\w ゆえ \\b 成立)",
     {"log": ["照会（messageId:aaaa00000000000e）"]}, {"aaaa00000000000e"}),
    ("入れ子 dict (refs:) の prefix つき値",
     {"refs": {"gmail_msg_ids": "messageId:aaaa000000000010 (受信)"}}, {"aaaa000000000010"}),
    ("list の中の dict の prefix つき値",
     {"log": [{"date": "2026-01-01", "note": "続報 (mid:aaaa000000000011)"}]}, {"aaaa000000000011"}),
    ("top-level thread_id 素値", {"thread_id": "aaaa000000000013"}, {"aaaa000000000013"}),
    ("道具が書く印 recorded_upto",
     {"recorded_upto": "messageId:aaaa000000000014 (2026-01-01 16:56)"}, {"aaaa000000000014"}),
    ("道具が書く索引 messages[] (← / → の方向つき)",
     {"messages": ["mid:aaaa000000000015 2026-01-01 21:25 ← Example Admin",
                   "mid:aaaa000000000016 2026-01-02 09:00 → Example Admin"]},
     {"aaaa000000000015", "aaaa000000000016"}),
    # negatives
    ("入れ子でも prefix 無しの bare hex は非認識", {"refs": {"gmail_msg_id": "aaaa000000000012"}}, set()),
    ("偶発 substring (pyramid:) は非認識", {"notes": "pyramid:aaaa00000000000c"}, set()),
    ("散文中の bare hex は非認識", {"notes": "対応済 aaaa00000000000d です"}, set()),
    ("非 string field (int/None) は無害", {"messageId": None, "count": 3}, set()),
    ("漢字直付き (受信messageId:) は \\b 不成立で非認識 (空白か約物を挟むのが house style)",
     {"notes": "受信messageId:aaaa00000000000f"}, set()),
]

MSG_FIXTURES: list[tuple[str, dict, set[str]]] = [
    ("messageId 素値 + log の mid: は入る、 threadId 素値と threadId: は入らない",
     {"messageId": "aaaa000000000021", "threadId": "aaaa000000000022",
      "log": ["続報 (mid:aaaa000000000023)、 同 thread (threadId:aaaa000000000024)"]},
     {"aaaa000000000021", "aaaa000000000023"}),
    ("入れ子の messages[] / recorded_upto も message id として入る",
     {"recorded_upto": "messageId:aaaa000000000025 (2026-01-01 09:00)",
      "messages": ["mid:aaaa000000000025 2026-01-01 09:00 ← X"]},
     {"aaaa000000000025"}),
]


def run_selftest() -> bool:
    ok = True
    for name, entry, want in FIXTURES:
        got = harvest_entry(entry)
        print(f"  {'PASS' if got == want else 'FAIL'}: {name}" + ("" if got == want else f": want={sorted(want)} got={sorted(got)}"))
        ok &= got == want
    for name, entry, want in MSG_FIXTURES:
        got = harvest_message_ids(entry)
        print(f"  {'PASS' if got == want else 'FAIL'}: message-only: {name}" + ("" if got == want else f": want={sorted(want)} got={sorted(got)}"))
        ok &= got == want
    return ok


if __name__ == "__main__":
    ok = run_selftest()
    print(f"selftest: {'ALL PASS' if ok else 'FAIL あり'}")
    raise SystemExit(0 if ok else 1)
