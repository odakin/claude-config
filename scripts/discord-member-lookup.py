#!/usr/bin/env python3
"""discord-member-lookup.py — 取得済みの Discord message log (JSON) から、名前でメンバーの user ID を根拠つきで引く（本人の自己紹介 / 他人の mention / ユーザー名一致の 3 段）。 --selftest 内蔵。 conventions/discord-bot.md#group-call-mentions

Why: 呼びかけの投稿で個別 mention を付けるとき、表示名は変わるし、ユーザー名が
名前と無関係なメンバーも多い。 ID を推測で入れると ping が届かない (= 失敗が
黙って起きる)。 取得済みの log には本人の自己紹介や、他のメンバーが名前と一緒に
その ID を mention した投稿が残っているので、そこから根拠の強い順に引く。

入力 = Discord API の message object の JSON (次のどれでもよい):
  - message の list
  - {"messages": [...]} の dict
  - {id: message} の dict
message は author{id, username, global_name} / content / timestamp を使う。

Usage:
  discord-member-lookup.py authors FILE...
      投稿者一覧 (id / username / global_name / 初出 / 件数)
  discord-member-lookup.py find NAME [--alias A ...] FILE...
      NAME (と alias) で候補 ID を根拠の強い順に出す。 alias にはローマ字や
      別表記 (例: 異体字の姓) を渡す。 ユーザー名・表示名との照合にも alias を使う。
  discord-member-lookup.py --selftest

根拠の段:
  self_intro   本人の投稿で「NAME です / と申します / といいます」
  self_label   本人の投稿が NAME で始まる (写真の名札・キャプション)
  mentioned    他人の投稿で <@ID> のすぐ隣 (前後 15 字) に NAME がある
  name_match   ユーザー名・表示名に NAME / alias が含まれる (弱い)
判定:
  確定 = 本人の投稿 (self_intro/self_label) と他人の mention が同じ ID を指す
  有力 = どちらか一方
  弱   = name_match だけ (本人確認前として扱い、記録にもそう書く)
NAME の直後が敬称 (さん / 様 / 先生 / くん / ちゃん / 氏) の本人投稿は、
他人への呼びかけなので根拠にしない。
"""
import argparse
import glob
import json
import re
import sys
import unicodedata
from collections import OrderedDict, defaultdict

HONORIFICS = ("さん", "様", "さま", "先生", "くん", "君", "ちゃん", "氏")
SELF_INTRO_TAIL = re.compile(r"^\s*(です|でーす|と申します|といいます|と言います)")
MENTION_TOKEN = re.compile(r"<@!?(\d+)>")
WINDOW = 15
RANK = {"確定": 0, "有力": 1, "弱": 2}


def norm(s):
    return unicodedata.normalize("NFKC", s or "")


def name_regex(name):
    chars = [c for c in norm(name) if not c.isspace()]
    return re.compile(r"\s*".join(re.escape(c) for c in chars), re.IGNORECASE)


def load_messages(paths):
    out = []
    for pattern in paths:
        files = sorted(glob.glob(pattern)) or [pattern]
        for f in files:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("messages"), list):
                msgs = data["messages"]
            elif isinstance(data, dict):
                msgs = list(data.values())
            else:
                msgs = data
            for m in msgs:
                if isinstance(m, dict) and isinstance(m.get("author"), dict):
                    out.append((f.rsplit("/", 1)[-1], m))
    out.sort(key=lambda fm: fm[1].get("timestamp") or "")
    return out


def authors(messages):
    table = OrderedDict()
    for _f, m in messages:
        a = m["author"]
        aid = str(a.get("id"))
        if aid not in table:
            table[aid] = {"username": a.get("username"), "global_name": a.get("global_name"),
                          "first": (m.get("timestamp") or "")[:10], "count": 0}
        table[aid]["count"] += 1
    return table


def snippet(text, limit=80):
    t = norm(text).replace("\n", " / ")
    return t if len(t) <= limit else t[:limit] + "…"


def find(messages, name, aliases=()):
    regs = [name_regex(n) for n in (name, *aliases) if n and n.strip()]
    ev = defaultdict(list)  # id -> [(kind, file, ts, snippet)]
    meta = {}
    for f, m in messages:
        a = m["author"]
        aid = str(a.get("id"))
        meta.setdefault(aid, (a.get("username"), a.get("global_name")))
        content = norm(m.get("content"))
        ts = (m.get("timestamp") or "")[:10]
        tokens = list(MENTION_TOKEN.finditer(content))
        lead = len(content) - len(content.lstrip())
        for rg in regs:
            for hit in rg.finditer(content):
                tail = content[hit.end():]
                if tail.startswith(HONORIFICS):
                    kind_self = None  # 他人への呼びかけ
                elif SELF_INTRO_TAIL.match(tail):
                    kind_self = "self_intro"
                elif hit.start() == lead:
                    kind_self = "self_label"
                else:
                    kind_self = None
                if kind_self == "self_intro":
                    # 「<@相手> …の NAME です」 = 相手への挨拶に続く本人の自己紹介。 隣に mention があっても
                    # 相手の ID に名前を付けない (= 付けると自己紹介した本人の名前が挨拶の相手に誤帰属する)
                    ev[aid].append((kind_self, f, ts, snippet(content)))
                    continue
                in_mention_window = False
                for tok in tokens:
                    near_after = 0 <= hit.start() - tok.end() <= WINDOW
                    near_before = 0 <= tok.start() - hit.end() <= WINDOW
                    if not (near_after or near_before):
                        continue
                    lo, hi = sorted((tok.end(), hit.start())) if near_after else sorted((hit.end(), tok.start()))
                    if MENTION_TOKEN.search(content[lo:hi]):
                        continue  # 間に別の mention = どちらの名前か曖昧
                    in_mention_window = True
                    uid = tok.group(1)
                    if uid != aid:
                        ev[uid].append(("mentioned", f, ts, snippet(content)))
                if kind_self and not in_mention_window:
                    ev[aid].append((kind_self, f, ts, snippet(content)))
    for aid, (username, global_name) in meta.items():
        label = norm(f"{username or ''} {global_name or ''}")
        if any(rg.search(label) for rg in regs):
            ev[aid].append(("name_match", "-", "", f"username={username} global_name={global_name}"))
    results = []
    for uid, items in ev.items():
        kinds = {k for k, *_ in items}
        own = bool(kinds & {"self_intro", "self_label"})
        other = "mentioned" in kinds
        verdict = "確定" if own and other else "有力" if own or other else "弱"
        seen, uniq = set(), []
        for it in items:
            if it not in seen:
                seen.add(it)
                uniq.append(it)
        results.append({"id": uid, "verdict": verdict, "evidence": uniq,
                        "username": meta.get(uid, (None, None))[0],
                        "global_name": meta.get(uid, (None, None))[1]})
    results.sort(key=lambda r: (RANK[r["verdict"]], -len(r["evidence"])))
    return results


def print_find(results):
    if not results:
        print("候補なし (= この log の範囲に根拠が無い。 別表記を --alias で足すか、本人に聞く)")
        return
    for r in results:
        who = r["username"] or "(log に投稿なし)"
        print(f"[{r['verdict']}] {r['id']}  username={who} global_name={r['global_name']}")
        for kind, f, ts, snip in r["evidence"][:4]:
            print(f"    {kind:<10} {f} {ts} | {snip}")


def selftest():
    A, B, C, D = "1001", "1002", "1003", "1004"
    msgs = [
        ("t.json", {"author": {"id": A, "username": "x_river", "global_name": "かわ"},
                    "content": "M1の霧ヶ丘です！よろしくお願いします", "timestamp": "2025-01-01T00:00:00"}),
        ("t.json", {"author": {"id": B, "username": "b_user", "global_name": "B"},
                    "content": "霧ヶ丘さん、明日の件お願いします", "timestamp": "2025-01-02T00:00:00"}),
        ("t.json", {"author": {"id": C, "username": "c_user", "global_name": "C"},
                    "content": f"<@{A}> （霧ヶ丘様）本日受け取りに来てください", "timestamp": "2025-01-03T00:00:00"}),
        ("t.json", {"author": {"id": D, "username": "kirigaoka_77", "global_name": "k"},
                    "content": "こんにちは", "timestamp": "2025-01-04T00:00:00"}),
        ("t.json", {"author": {"id": C, "username": "c_user", "global_name": "C"},
                    "content": f"<@{B}> <@{D}> 今日の議題はたくさんあります。 あとで霧ヶ丘の件も", "timestamp": "2025-01-05T00:00:00"}),
        ("t.json", {"author": {"id": B, "username": "b_user", "global_name": "B"},
                    "content": "鳩ノ森 花 / Hana Hatonomori", "timestamp": "2025-01-06T00:00:00"}),
        ("t.json", {"author": {"id": C, "username": "c_user", "global_name": "C"},
                    "content": f"<@{D}> <@{B}>鳩ノ森さん", "timestamp": "2025-01-07T00:00:00"}),
        ("t.json", {"author": {"id": D, "username": "kirigaoka_77", "global_name": "k"},
                    "content": f"<@{A}>\nM2の潮見台です！", "timestamp": "2025-01-08T00:00:00"}),
    ]
    fails = []

    def check(label, cond):
        print(("PASS " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)

    res = {r["id"]: r for r in find(msgs, "霧ヶ丘", aliases=["kirigaoka"])}
    check("自己紹介 + 他人の mention が一致すれば 確定", res.get(A, {}).get("verdict") == "確定")
    check("敬称つきの本人投稿は根拠にしない (B は候補にならない)", B not in res)
    check("ユーザー名一致だけなら 弱", res.get(D, {}).get("verdict") == "弱")
    check("mention と名前が離れていれば数えない (D に mentioned が付かない)",
          all(k != "mentioned" for k, *_ in res.get(D, {}).get("evidence", [])))
    res2 = {r["id"]: r for r in find(msgs, "鳩ノ森花")}
    check("名札キャプション (空白の揺れ込み) は self_label", any(k == "self_label" for k, *_ in res2.get(B, {}).get("evidence", [])))
    res3 = {r["id"]: r for r in find(msgs, "鳩ノ森")}
    check("間に別の mention がある組は採らず、隣の mention だけ採る",
          res3.get(B, {}).get("verdict") == "確定" and D not in res3)
    res4 = {r["id"]: r for r in find(msgs, "潮見台")}
    check("挨拶の mention に続く自己紹介は本人に付け、挨拶の相手には付けない",
          res4.get(D, {}).get("verdict") == "有力" and A not in res4)
    tab = authors(msgs)
    check("authors は投稿者ごとに件数を数える", tab[C]["count"] == 3 and tab[A]["first"] == "2025-01-01")
    check("候補なしは空", find(msgs, "存在しない名前") == [])
    print(f"\n{len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p_auth = sub.add_parser("authors")
    p_auth.add_argument("files", nargs="+")
    p_find = sub.add_parser("find")
    p_find.add_argument("name")
    p_find.add_argument("--alias", action="append", default=[])
    p_find.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.cmd == "authors":
        for aid, row in authors(load_messages(args.files)).items():
            print(f"{aid}\t{row['username']}\t{row['global_name']}\t{row['first']}\t{row['count']}")
        return 0
    if args.cmd == "find":
        print_find(find(load_messages(args.files), args.name, args.alias))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
