#!/usr/bin/env python3
"""discord-private-channel.py — bot に、 指定した人と bot 自身だけが見える非公開の text channel を server に作らせる。 --selftest 内蔵。

用途: bot と人の 1:1 DM は bot の持ち主から見えない。 持ち主・相手・bot の 3 人の場を作るのは server の非公開 channel だけ
(bot はフレンドにもグループ DM にもなれない)。 規約 = conventions/discord-bot.md#owner-visible-bot-conversation。

作り方: @everyone の View Channel を deny し、 --member で渡した user と bot 自身に user overwrite で
View / Send / Read History / Embed / Attach / Add Reactions を allow した text channel を、 作成の request 1 本で作る。
bot に要るのは guild の `Manage Channels` だけ (作成時の overwrite は `Manage Roles` 無しで付く。 allow できるのは
bot が guild で持っている権限だけ = conventions/discord-bot.md の「Bot 自身が UI 操作の代行をできない理由」)。

Usage:
  discord-private-channel.py --token-file ~/.secrets/<bot>-token --guild <GUILD_ID> --name <名前> \\
      --member <USER_ID> [--member <USER_ID> ...] [--parent <CATEGORY_ID>]          # 既定 = 送らずに中身を出す
  ... --create                                                                     # 作って、 GET で読み戻して確かめる
  discord-private-channel.py --selftest
相手と bot が同じ server に居るか = discord-post.py --member-probe <USER_ID>。 分類の id = discord-post.py --channels <GUILD_ID>。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/odakin/claude-config discord-private-channel, 1.0)"  # UA 必須 (無いと 1010)

VIEW, SEND, EMBED, ATTACH, HISTORY, REACT = 1 << 10, 1 << 11, 1 << 14, 1 << 15, 1 << 16, 1 << 6
ALLOW = VIEW | SEND | EMBED | ATTACH | HISTORY | REACT


def build_payload(guild: str, name: str, members: list[str], bot_id: str, parent: str | None) -> dict:
    """作成の request の本体。 @everyone (= guild id の role) は View を deny、 members と bot は allow。"""
    ids = []
    for m in [*members, bot_id]:
        if m not in ids:
            ids.append(m)
    body = {
        "name": name,
        "type": 0,
        "permission_overwrites": [{"id": guild, "type": 0, "allow": "0", "deny": str(VIEW)}]
        + [{"id": i, "type": 1, "allow": str(ALLOW), "deny": "0"} for i in ids],
    }
    if parent:
        body["parent_id"] = parent
    return body


def check_overwrites(channel: dict, guild: str, want: list[str]) -> list[str]:
    """読み戻した channel の overwrite が意図どおりか。 食い違いの説明の list (空 = 一致)。"""
    got = {o["id"]: o for o in channel.get("permission_overwrites", [])}
    bad = []
    ev = got.get(guild)
    if not ev or not int(ev.get("deny", "0")) & VIEW:
        bad.append("@everyone の View が deny されていない (= 公開 channel になっている)")
    for i in want:
        o = got.get(i)
        if not o or int(o.get("allow", "0")) & ALLOW != ALLOW:
            bad.append(f"{i} に View / Send / History などの allow が無い")
    extra = set(got) - {guild, *want}
    if extra:
        bad.append(f"想定外の overwrite: {sorted(extra)}")
    return bad


def req(token: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{API}{path}", data=data, method="POST" if body is not None else "GET",
                               headers={"Authorization": f"Bot {token}", "User-Agent": UA,
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:400]
        hint = " (403 = bot に Manage Channels が無いか、 allow しようとした権限を bot が guild で持っていない)" if e.code == 403 else ""
        sys.exit(f"HTTP {e.code} {path}: {msg}{hint}")


def selftest() -> int:
    fails = []
    p = build_payload("G", "x", ["U1", "B"], "B", "C")
    ow = p["permission_overwrites"]
    if [o["id"] for o in ow] != ["G", "U1", "B"]:
        fails.append("bot が重複して入るか順番が違う")
    if ow[0]["deny"] != str(VIEW) or ow[1]["allow"] != str(ALLOW):
        fails.append("deny / allow の値")
    if p.get("parent_id") != "C" or "parent_id" in build_payload("G", "x", [], "B", None):
        fails.append("parent_id")
    good = {"permission_overwrites": ow}
    if check_overwrites(good, "G", ["U1", "B"]):
        fails.append("一致する読み戻しを食い違いと判定した")
    leaky = {"permission_overwrites": [{"id": "U1", "type": 1, "allow": str(ALLOW), "deny": "0"}]}
    if not any("公開" in b for b in check_overwrites(leaky, "G", ["U1"])):
        fails.append("@everyone の deny 無しを見逃した")
    print("discord-private-channel selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--token-file")
    ap.add_argument("--guild")
    ap.add_argument("--name")
    ap.add_argument("--member", action="append", default=[], help="見せる人の user id (繰り返し可)")
    ap.add_argument("--parent", help="置く分類 (category) の id")
    ap.add_argument("--create", action="store_true", help="実際に作る (無ければ送らずに中身を出す)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.token_file and a.guild and a.name and a.member):
        ap.error("--token-file / --guild / --name / --member (1 つ以上) が要る")
    token = Path(a.token_file).expanduser().read_text().strip()
    me = req(token, "/users/@me")
    body = build_payload(a.guild, a.name, a.member, me["id"], a.parent)
    print(f"bot = {me.get('username')} ({me['id']})")
    print(json.dumps(body, ensure_ascii=False, indent=1))
    if not a.create:
        print("(送っていない。 作るなら --create)")
        return 0
    c = req(token, f"/guilds/{a.guild}/channels", body)
    back = req(token, f"/channels/{c['id']}")
    bad = check_overwrites(back, a.guild, [*a.member, me["id"]])
    print(f"created channel_id={c['id']} name=#{c.get('name')} parent={c.get('parent_id')}")
    if bad:
        print("⚠️ 読み戻しの食い違い: " + " / ".join(bad))
        return 1
    print("読み戻し: @everyone deny + 指定した人と bot の allow を確認")
    return 0


if __name__ == "__main__":
    sys.exit(main())
