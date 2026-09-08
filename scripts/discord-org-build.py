#!/usr/bin/env python3
"""discord-org-build.py — 組織図 YAML (部 → 課 → 係 + persona 名) から Discord server の器を冪等に作る (stdlib + PyYAML)。

何を作るか (conventions/discord-bot.md#webhook-personas + multi-session-coordination.md#chat-board-bridge):
  部 (department) → category (name 一致で再利用)
  部長室          → text channel `<部名>長室` (`head_channel: false` の部は作らない)
  課 (section)    → text channel (`channel_name` / `channel_id` 指定があればその既存 channel を再利用、 無ければ課名で作る)
  persona         → channel ごとに webhook 1 本 (execute 時に username を切り替えて 部長 / 課長 / 係長 を演じる)
  human           → 人間用 category + channel (既存 id を尊重、 bridge 圏外)

書き戻し (両方 required):
  --ids       = {departments: {key: {category_id, head_channel_id, sections: {key: channel_id}}}, human: {...}} (repo に commit する generated file)
  --webhooks  = {channel_id: {id, token, name}} (= 投稿権そのもの、 secret 扱い、 0600、 git-crypt 経路で保管)

組織図 YAML の形 (owner の private layer に置く instance の例):
  company: <名>
  guild_id: "<guild id>"
  departments:
    - key: somu            # ascii slug (ids の key、 rename しても id が追える)
      name: 総務部
      project: <source project>   # bridge が request を起票する先、 課に無ければ継ぐ
      boss: 万事 おまかせ           # 部長 persona (head_channel: false なら null)
      head_channel: true
      sections:
        - key: shomu
          name: 庶務課
          boss: 庶務 こなす           # 課長 persona (ack / 受領の名義)
          units:
            - {name: 雑務係, boss: 細川 こまご, keywords: [雑務, 雑用]}   # 係長 persona (進捗の名義)、 keywords で係を選ぶ
  human:
    category: 人間
    channels:
      - {key: kyukei, name: 休憩室, channel_id: "<id>"}

やらないこと: 削除 (組織図から消えた channel は手で消す)、 avatar 画像、 権限 overwrite。
前提: bot が invite 時に Manage Channels + **Manage Webhooks** を持つ (標準 posting セットには Manage Webhooks が無い → 再認証)。
--dry = 作る予定を print するだけ。 --selftest = yaml 解析 + 展開の fixture (network 無し)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/odakin/claude-config discord-org-build, 0.2)"  # conventions/discord-bot.md#discord-api-user-agent


def load_org(path: Path) -> dict:
    import yaml
    org = yaml.safe_load(path.read_text(encoding="utf-8"))
    for d in org["departments"]:
        d.setdefault("head_channel", True)
        for s in d["sections"]:
            s.setdefault("project", d["project"])
            s.setdefault("channel_name", s["name"])
            for u in s["units"]:
                u.setdefault("keywords", [])
    org.setdefault("human", {"category": None, "channels": []})
    return org


def plan(org: dict) -> list[dict]:
    """組織図 → 作るべき Discord object の列 (selftest 対象、 network 無し)。"""
    out = []
    for d in org["departments"]:
        out.append({"kind": "category", "dept": d["key"], "name": d["name"]})
        if d["head_channel"]:
            out.append({"kind": "channel", "dept": d["key"], "section": None, "name": f"{d['name']}長室",
                        "topic": f"{d['name']}長 {d['boss']} の部屋。 部全体の依頼はここ (project = {d['project']})。 1 行目 = 題、 2 行目以降 = 完了条件。"})
        for s in d["sections"]:
            units = "・".join(f"{u['name']}({u['boss']})" for u in s["units"])
            out.append({"kind": "channel", "dept": d["key"], "section": s["key"], "name": s["channel_name"],
                        "topic": f"{d['name']} {s['name']} (課長 {s['boss']}、 project = {s['project']})。 係 = {units}。 依頼はここに書けば課長が受けて係長が返します。"[:1024]})
    if org["human"].get("category"):
        out.append({"kind": "category", "dept": "_human", "name": org["human"]["category"]})
        for c in org["human"].get("channels", []):
            out.append({"kind": "channel", "dept": "_human", "section": c["key"], "name": c["name"], "channel_id": c.get("channel_id")})
    return out


class Discord:
    def __init__(self, token: str):
        self.token = token

    def req(self, path: str, payload=None, method=None):
        for _ in range(5):
            data = json.dumps(payload).encode() if payload is not None else None
            r = urllib.request.Request(API + path, data=data, method=method or ("POST" if data else "GET"),
                                       headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json", "User-Agent": UA})
            try:
                with urllib.request.urlopen(r, timeout=30) as x:
                    return json.load(x) if x.status != 204 else {}
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                if e.code == 429:
                    try:
                        wait = float(json.loads(body).get("retry_after", 1.0))
                    except Exception:
                        wait = 1.0
                    time.sleep(wait + 0.2); continue
                raise RuntimeError(f"{method or 'GET'} {path} → {e.code}: {body[:300]}")
        raise RuntimeError(f"rate limited too long: {path}")


def build(args) -> int:
    org = load_org(args.org)
    gid = str(org["guild_id"])
    steps = plan(org)
    if args.dry:
        for s in steps:
            print(f"{s['kind']:<9} {s['name']}" + (f"  [{s['dept']}/{s['section']}]" if s.get("section") else f"  [{s['dept']}]"))
        print(f"{len(steps)} objects"); return 0
    dc = Discord(args.token.read_text(encoding="utf-8").strip())
    existing = dc.req(f"/guilds/{gid}/channels")
    by_id = {c["id"]: c for c in existing}
    cats = {c["name"]: c for c in existing if c["type"] == 4}
    ids = json.loads(args.ids.read_text(encoding="utf-8")) if args.ids.exists() else {"departments": {}, "human": {}}
    try:
        whs = json.loads(args.webhooks.read_text(encoding="utf-8"))
    except Exception:
        whs = {}
    me = dc.req("/users/@me")["id"]
    guild_whs = {w["channel_id"]: w for w in dc.req(f"/guilds/{gid}/webhooks") if str(w.get("application_id")) == me and w.get("token")}  # 自分 (bot) が作った webhook だけ再利用

    def ensure_category(name: str) -> str:
        if name in cats:
            return cats[name]["id"]
        c = dc.req(f"/guilds/{gid}/channels", {"name": name, "type": 4})
        cats[name] = c; print(f"+ category {name}")
        return c["id"]

    def ensure_channel(name: str, parent: str, topic: str | None, known_id: str | None) -> str:
        if known_id and known_id in by_id:
            c = by_id[known_id]
            patch = {}
            if c.get("parent_id") != parent: patch["parent_id"] = parent
            if topic and c.get("topic") != topic: patch["topic"] = topic
            if c["name"] != name: patch["name"] = name
            if patch:
                dc.req(f"/channels/{known_id}", patch, method="PATCH"); print(f"~ channel {name}")
            return known_id
        same = [c for c in existing if c["type"] == 0 and c["name"] == name and c.get("parent_id") == parent]
        if same:
            return same[0]["id"]
        c = dc.req(f"/guilds/{gid}/channels", {"name": name, "type": 0, "parent_id": parent, **({"topic": topic} if topic else {})})
        existing.append(c); by_id[c["id"]] = c; print(f"+ channel {name}")
        return c["id"]

    def ensure_webhook(cid: str, name: str) -> None:
        if cid in whs:
            return
        w = guild_whs.get(cid)
        if not w:
            w = dc.req(f"/channels/{cid}/webhooks", {"name": name}); print(f"+ webhook {name}")
        whs[cid] = {"id": w["id"], "token": w["token"], "name": name}

    for d in org["departments"]:
        rec = ids["departments"].setdefault(d["key"], {"sections": {}})
        rec["category_id"] = ensure_category(d["name"])
        if d["head_channel"]:
            st = next(s for s in steps if s["kind"] == "channel" and s["dept"] == d["key"] and s["section"] is None)
            rec["head_channel_id"] = ensure_channel(st["name"], rec["category_id"], st["topic"], rec.get("head_channel_id"))
            ensure_webhook(rec["head_channel_id"], st["name"])
        for s in d["sections"]:
            st = next(x for x in steps if x["kind"] == "channel" and x["dept"] == d["key"] and x["section"] == s["key"])
            known = rec["sections"].get(s["key"]) or s.get("channel_id")
            cid = ensure_channel(st["name"], rec["category_id"], st["topic"], known)
            rec["sections"][s["key"]] = cid
            ensure_webhook(cid, s["channel_name"])
    if org["human"].get("category"):
        hcat = ensure_category(org["human"]["category"])
        ids["human"] = {"category_id": hcat, "channels": {}}
        for c in org["human"].get("channels", []):
            ids["human"]["channels"][c["key"]] = ensure_channel(c["name"], hcat, None, c.get("channel_id"))
    args.ids.write_text(json.dumps(ids, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    args.webhooks.parent.mkdir(parents=True, exist_ok=True)
    args.webhooks.write_text(json.dumps(whs, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(args.webhooks, 0o600)
    except OSError:
        pass
    print(f"ids → {args.ids} / webhooks {len(whs)} → {args.webhooks}")
    return 0


def selftest() -> int:
    import tempfile
    y = """company: t
guild_id: "1"
departments:
  - key: a
    name: 甲部
    project: p
    boss: 甲 長
    sections:
      - key: a1
        name: 甲一課
        boss: 一 課長
        units:
          - {name: 一係, boss: 一 係長, keywords: [x]}
  - key: b
    name: 乙室
    project: q
    head_channel: false
    boss: null
    sections:
      - key: b1
        name: 乙課
        channel_name: 既存
        boss: 乙 課長
        units:
          - {name: 乙係, boss: 乙 係長}
human:
  category: 人
  channels:
    - {key: k, name: 休, channel_id: "9"}
"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "o.yaml"; p.write_text(y, encoding="utf-8")
        org = load_org(p)
        assert org["departments"][1]["sections"][0]["project"] == "q"           # 課は部の project を継ぐ
        assert org["departments"][1]["sections"][0]["units"][0]["keywords"] == []
        steps = plan(org)
        names = [s["name"] for s in steps]
        assert names == ["甲部", "甲部長室", "甲一課", "乙室", "既存", "人", "休"], names   # 室は部長室無し、 channel_name 尊重
        assert "一係(一 係長)" in next(s for s in steps if s["name"] == "甲一課")["topic"]
        p2 = Path(td) / "o2.yaml"; p2.write_text(y.split("human:")[0], encoding="utf-8")
        assert [s["name"] for s in plan(load_org(p2))][-1] == "既存"                  # human 節は任意
    print("selftest OK (6 checks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--org", type=Path, help="組織図 YAML")
    ap.add_argument("--ids", type=Path, help="channel id の書き戻し先 JSON (repo に commit)")
    ap.add_argument("--webhooks", type=Path, help="webhook 保管 JSON (secret、 0600)")
    ap.add_argument("--token", type=Path, help="bot token file")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    missing = [k for k in ("org", "ids", "webhooks", "token") if getattr(a, k) is None]
    if missing:
        ap.error("required: " + ", ".join("--" + m for m in missing))
    return build(a)


if __name__ == "__main__":
    sys.exit(main())
