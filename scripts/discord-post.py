#!/usr/bin/env python3
"""discord-post.py — canonical Discord Bot API poster (stdlib only).

Why this exists (recurrence prevention, 2026-07-10): sessions arriving at the
operational doc by grep extract token/channel IDs but structurally skip the
general rules (User-Agent requirement, error semantics, send gating) that live
in a different document. This script carries those rules in code, so the
correct path is also the easiest path. Rules embedded here:

- User-Agent header is mandatory for the Discord API; default urllib/curl UAs
  are rejected by Cloudflare with error 1010 (conventions/discord-bot.md
  "Discord API call の User-Agent header 必須").
- Posting is an external broadcast: default is a DRY RUN that prints the
  resolved target and content; nothing is sent without the explicit --send
  flag (conventions/claude-code-permissions.md #ask-pattern-action-anchor).

Usage:
  python3 discord-post.py --token-file ~/.secrets/<bot-token> \
      --channel <CHANNEL_ID> (--content "text" | --content-file msg.txt) [--send]
  python3 discord-post.py --token-file ... --dm-user <USER_ID> ...   # open DM first
  python3 discord-post.py --token-file ... --channel <ID> --check    # read-only probe
  python3 discord-post.py --token-file ... --channel <ID> --recent 10  # read-only: last N messages
  python3 discord-post.py ... --attach path/to/file [--attach ...]   # attach file(s)
  python3 discord-post.py --selftest

On success prints:  sent message_id=<id> channel_id=<id>

Mass mentions (@everyone / @here) need the bot's "Mention Everyone" permission in
that channel. Without it Discord still accepts the post (HTTP 200) and just drops the
ping, so a post can look successful while nobody is notified. After sending, this
script reads `mention_everyone` from the API response and exits 3 with a warning if a
mass mention in the text did not take effect (conventions/discord-bot.md
#mass-mention-silently-dropped).

Before sending, the same permission is computed from the API (read-only GETs: the
channel, its parent for threads, the guild roles and the bot's own member) and shown
by --check and by a dry run whose text has @everyone/@here — so "can this bot ping
everyone here?" is answered before the post, without an ad-hoc API script
(conventions/discord-bot.md #mass-mention-precheck).
"""
import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/odakin/claude-config discord-post, 1.0)"
ATTACH_WARN_MB = 25  # Discord default file size cap (unboosted). API returns 40005 if exceeded.

HINTS = {
    "1010": "Cloudflare rejected the User-Agent (should not happen via this script).",
    "401": "Unauthorized: token invalid. If the token file looks like binary noise, "
           "the repo may be git-crypt locked; run setup.sh / git-crypt unlock.",
    "50007": "Cannot send messages to this user (DMs closed or no mutual guild).",
    "50001": "Missing Access: the bot is not in that channel/guild.",
    "50013": "Missing Permissions: bot lacks Send Messages in that channel.",
    "40005": "Request entity too large: attachment exceeds channel file size cap "
             "(default 25 MB unboosted; higher on boosted server).",
    "429": "Rate limited: honor retry_after from the response body.",
}


def _request(url, token, payload=None, method=None, multipart=None):
    """Standard JSON POST/GET, or multipart POST when `multipart=(body_bytes, content_type)`.

    Multipart carries the same Authorization / User-Agent headers as JSON — the UA rule
    (= conventions/discord-bot.md #discord-api-user-agent) applies uniformly across content
    types; only the Content-Type header switches to `multipart/form-data; boundary=...`.
    """
    if multipart is not None:
        body_bytes, ctype = multipart
        req = urllib.request.Request(
            url, data=body_bytes, method="POST",
            headers={"Authorization": f"Bot {token}",
                     "Content-Type": ctype,
                     "User-Agent": UA})
    else:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url, data=data, method=method or ("POST" if data else "GET"),
            headers={"Authorization": f"Bot {token}",
                     "Content-Type": "application/json",
                     "User-Agent": UA})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return None, (e.code, body)


def _multipart_body(payload_json, attach_paths):
    """Build a Discord-style multipart/form-data body: payload_json + files[N] parts.

    Returns (body_bytes, content_type). Reference:
    https://discord.com/developers/docs/reference#uploading-files
    """
    boundary = "----ClaudeConfig" + uuid.uuid4().hex
    parts = []
    # payload_json part (JSON body for the message)
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="payload_json"\r\n')
    parts.append(b"Content-Type: application/json\r\n\r\n")
    parts.append(payload_json.encode("utf-8"))
    parts.append(b"\r\n")
    # each attachment as files[i]
    for i, path in enumerate(attach_paths):
        # filename: strip embedded quotes to avoid header injection; UTF-8 is fine in
        # modern Content-Disposition (Discord accepts it).
        filename = os.path.basename(path).replace('"', "")
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            data = fh.read()
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="files[{i}]"; filename="{filename}"\r\n'.encode("utf-8")
        )
        parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _format_messages(msgs):
    """GET /channels/{id}/messages の結果 (新しい順) を古い順の 1 行ずつにする。
    改行は ' / ' に畳み、 添付は file 名だけ出す (= 読む用。 本文の全文は API の JSON にある)。"""
    lines = []
    for m in reversed(msgs or []):
        ts = (m.get("timestamp") or "")[:19].replace("T", " ")
        author = (m.get("author") or {}).get("username", "?")
        text = (m.get("content") or "").replace("\n", " / ")
        atts = [a.get("filename", "") for a in m.get("attachments") or []]
        tail = f" [attachments: {', '.join(atts)}]" if atts else ""
        lines.append(f"{ts} | {m.get('id', '')} | {author} | {text}{tail}")
    return lines


def _wants_mass_mention(body):
    return "@everyone" in body or "@here" in body


def _mass_mention_dropped(body, resp):
    """本文に @everyone / @here があるのに、 送信結果の mention_everyone が立っていない。"""
    return _wants_mass_mention(body) and not (resp or {}).get("mention_everyone")


MENTION_EVERYONE = 1 << 17
ADMINISTRATOR = 1 << 3
THREAD_TYPES = (10, 11, 12)  # thread は親 channel の overwrite を継ぐ


def _can_mention_everyone(guild_id, member_id, member_role_ids, role_perms, overwrites):
    """Discord の権限算出 (base → channel overwrite) を Mention Everyone の 1 bit だけで行う。

    role_perms = {role_id: int}。 @everyone role の id は guild_id と同じ。
    順序 = role の合算 → Administrator なら全許可 → @everyone の overwrite →
    role の overwrite (deny を全部当ててから allow を全部) → member 個別の overwrite。
    """
    perms = role_perms.get(guild_id, 0)
    for rid in member_role_ids:
        perms |= role_perms.get(rid, 0)
    if perms & ADMINISTRATOR:
        return True
    ow = {o.get("id"): o for o in overwrites or []}
    ev = ow.get(guild_id)
    if ev:
        perms = (perms & ~int(ev.get("deny", 0))) | int(ev.get("allow", 0))
    allow = deny = 0
    for rid in member_role_ids:
        o = ow.get(rid)
        if o:
            allow |= int(o.get("allow", 0))
            deny |= int(o.get("deny", 0))
    perms = (perms & ~deny) | allow
    mo = ow.get(member_id)
    if mo:
        perms = (perms & ~int(mo.get("deny", 0))) | int(mo.get("allow", 0))
    return bool(perms & MENTION_EVERYONE)


def _probe_mass_mention(token, channel_id):
    """この bot がこの channel で @everyone / @here を効かせられるかを API から計算する。

    読むだけ (GET 4-5 回)。 返り値 = (True / False / None, 説明)。 None = 判定できなかった。
    """
    ch, err = _request(f"{API}/channels/{channel_id}", token)
    if err:
        return None, _explain(*err)
    gid = ch.get("guild_id")
    if not gid:
        return None, "not a server channel (DM): @everyone / @here do not apply"
    src = ch
    if ch.get("type") in THREAD_TYPES and ch.get("parent_id"):
        src, err = _request(f"{API}/channels/{ch['parent_id']}", token)
        if err:
            return None, "parent channel: " + _explain(*err)
    me, err = _request(f"{API}/users/@me", token)
    if err:
        return None, _explain(*err)
    roles, err = _request(f"{API}/guilds/{gid}/roles", token)
    if err:
        return None, "guild roles: " + _explain(*err)
    member, err = _request(f"{API}/guilds/{gid}/members/{me['id']}", token)
    if err:
        return None, "bot member: " + _explain(*err)
    role_perms = {r["id"]: int(r.get("permissions", 0)) for r in roles}
    overwrites = src.get("permission_overwrites") or []
    ok = _can_mention_everyone(gid, me["id"], member.get("roles") or [], role_perms, overwrites)
    return ok, f"bot roles + {len(overwrites)} channel overwrite(s)"


def _mass_mention_line(allowed, detail):
    if allowed is True:
        return f"mass mention: ALLOWED here ({detail}) = @everyone/@here will ping"
    if allowed is False:
        return (f"mass mention: DENIED here ({detail}) = the post would go up but nobody "
                f"is pinged. Grant the bot Mention Everyone in this channel first")
    return f"mass mention: could not determine ({detail}); it is checked again after --send"


def _explain(code, body):
    msgs = [f"HTTP {code}: {body[:300]}"]
    for key, hint in HINTS.items():
        if key == str(code) or f'"code": {key}' in body or f"error code: {key}" in body:
            msgs.append(f"hint: {hint}")
    return "\n".join(msgs)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--token-file")
    p.add_argument("--channel", help="target channel id")
    p.add_argument("--dm-user", help="user id; opens (or reuses) the 1:1 DM channel first")
    p.add_argument("--content", help="message text")
    p.add_argument("--content-file", help="file containing the message text (UTF-8)")
    p.add_argument("--attach", action="append", default=[],
                   help="file to attach (repeat for multiple); Discord caps at 25 MB "
                        "per file on unboosted servers, warns if any single file exceeds")
    p.add_argument("--send", action="store_true",
                   help="actually send; without it this is a dry run")
    p.add_argument("--check", action="store_true",
                   help="read-only probe: GET the channel to validate token/UA/access")
    p.add_argument("--recent", type=int, metavar="N",
                   help="read-only: print the last N messages of the channel, oldest first "
                        "(1-100). Use this instead of ad-hoc API reads")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args(argv)

    if a.selftest:
        return selftest()
    if not a.token_file:
        p.error("--token-file is required")
    if not a.channel and not a.dm_user:
        p.error("--channel or --dm-user is required")
    token = open(a.token_file, encoding="utf-8", errors="replace").read().strip()
    if not token or "\x00" in token:
        print("token file looks empty/binary (git-crypt locked?)", file=sys.stderr)
        return 2

    if a.check:
        target = a.channel
        if a.dm_user:
            resp, err = _request(f"{API}/users/@me/channels", token,
                                 {"recipient_id": a.dm_user})
            if err:
                print(_explain(*err), file=sys.stderr); return 1
            target = resp["id"]
        resp, err = _request(f"{API}/channels/{target}", token)
        if err:
            print(_explain(*err), file=sys.stderr); return 1
        print(f"ok channel_id={resp['id']} type={resp.get('type')}")
        if resp.get("guild_id"):
            print(_mass_mention_line(*_probe_mass_mention(token, target)))
        return 0

    if a.recent is not None:
        target = a.channel
        if a.dm_user:
            # DM channel を開く (or 既存を返す) POST。 相手には何も表示されない
            resp, err = _request(f"{API}/users/@me/channels", token,
                                 {"recipient_id": a.dm_user})
            if err:
                print(_explain(*err), file=sys.stderr); return 1
            target = resp["id"]
        limit = min(max(a.recent, 1), 100)
        resp, err = _request(f"{API}/channels/{target}/messages?limit={limit}", token)
        if err:
            print(_explain(*err), file=sys.stderr); return 1
        print("\n".join(_format_messages(resp)))
        return 0

    if bool(a.content) == bool(a.content_file):
        p.error("exactly one of --content / --content-file is required")
    body = a.content if a.content else open(a.content_file, encoding="utf-8").read()
    body = body.strip()
    if not body and not a.attach:
        print("empty message and no attachment", file=sys.stderr); return 2
    if len(body) > 2000:
        print(f"message too long for Discord ({len(body)} > 2000 chars)", file=sys.stderr)
        return 2
    # attachment existence + size soft-warn (API returns 40005 for the hard limit)
    for path in a.attach:
        if not os.path.isfile(path):
            print(f"attach not found: {path}", file=sys.stderr); return 2
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb > ATTACH_WARN_MB:
            print(f"warn: {path} is {size_mb:.1f} MB (> {ATTACH_WARN_MB} MB Discord "
                  f"cap on unboosted servers; will likely fail 40005)", file=sys.stderr)

    if not a.send:
        target = a.channel or f"DM(user {a.dm_user})"
        extra = ""
        if a.attach:
            extra = f" + {len(a.attach)} attachment(s)"
            for path in a.attach:
                extra += f"\n  attach: {path} ({os.path.getsize(path)} B)"
        print(f"[dry run] would post {len(body)} chars to {target}{extra}; "
              f"re-run with --send after the draft is approved")
        if _wants_mass_mention(body):
            if a.channel:
                # read-only GETs; nothing is posted in a dry run
                allowed, detail = _probe_mass_mention(token, a.channel)
                print(_mass_mention_line(allowed, detail),
                      file=sys.stderr if allowed is False else sys.stdout)
            else:
                print("note: @everyone/@here do not apply in a DM")
        print("-" * 40)
        print(body)
        return 0

    channel = a.channel
    if a.dm_user:
        resp, err = _request(f"{API}/users/@me/channels", token,
                             {"recipient_id": a.dm_user})
        if err:
            print(_explain(*err), file=sys.stderr); return 1
        channel = resp["id"]

    if a.attach:
        payload_json = json.dumps({"content": body})
        mp = _multipart_body(payload_json, a.attach)
        resp, err = _request(f"{API}/channels/{channel}/messages", token, multipart=mp)
    else:
        resp, err = _request(f"{API}/channels/{channel}/messages", token,
                             {"content": body})
    if err:
        print(_explain(*err), file=sys.stderr); return 1
    n_att = len(resp.get("attachments", []))
    tail = f" attachments={n_att}" if n_att else ""
    print(f"sent message_id={resp['id']} channel_id={resp['channel_id']}{tail}")
    if _mass_mention_dropped(body, resp):
        print("WARNING: the text has @everyone/@here but Discord did not apply it "
              "(mention_everyone=false) = the post is up but nobody was pinged. "
              "Grant the bot Mention Everyone in this channel, or tell people another way.",
              file=sys.stderr)
        return 3
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  PASS " if cond else "  FAIL ") + name)
        ok = ok and cond

    # UA is a proper DiscordBot UA (the whole point of this script)
    check("UA declares DiscordBot", UA.startswith("DiscordBot ("))
    # error hint mapping
    check("1010 hint", "User-Agent" in _explain(403, "error code: 1010"))
    check("50007 hint", "DMs closed" in _explain(403, '{"message": "x", "code": 50007}'))
    check("40005 hint", "attachment exceeds" in _explain(413, '{"code": 40005}'))
    check("401 hint", "git-crypt" in _explain(401, "Unauthorized"))
    # --recent formatter: API returns newest first; print oldest first, fold newlines, list attachments
    fmt = _format_messages([
        {"id": "2", "timestamp": "2026-01-02T03:04:05.000+00:00", "author": {"username": "b"},
         "content": "line1\nline2", "attachments": [{"filename": "x.pdf"}]},
        {"id": "1", "timestamp": "2026-01-01T00:00:00.000+00:00", "author": {"username": "a"},
         "content": "first", "attachments": []},
    ])
    check("recent: oldest first", len(fmt) == 2 and fmt[0].endswith("| a | first"))
    check("recent: newline folded + attachments", fmt[1].endswith("line1 / line2 [attachments: x.pdf]"))
    # arg validation: dry-run is the default (no --send flag -> no POST; the dry run
    # only GETs when it pre-checks a mass mention)
    import inspect
    src = inspect.getsource(main)
    check("send gated behind --send", "if not a.send:" in src)
    # mass-mention pre-check: Discord permission order on synthetic ids (G = @everyone role)
    G, BOT, R = "g1", "u-bot", "r-bot"
    ME, ADM = MENTION_EVERYONE, ADMINISTRATOR
    check("precheck: role grants, no overwrites -> allowed",
          _can_mention_everyone(G, BOT, [R], {G: 0, R: ME}, []))
    check("precheck: nobody grants -> denied",
          not _can_mention_everyone(G, BOT, [R], {G: 0, R: 0}, []))
    check("precheck: @everyone overwrite deny beats role grant",
          not _can_mention_everyone(G, BOT, [R], {G: 0, R: ME},
                                    [{"id": G, "allow": "0", "deny": str(ME)}]))
    check("precheck: role overwrite allow beats @everyone deny",
          _can_mention_everyone(G, BOT, [R], {G: 0, R: 0},
                                [{"id": G, "allow": "0", "deny": str(ME)},
                                 {"id": R, "allow": str(ME), "deny": "0"}]))
    check("precheck: member overwrite deny is last",
          not _can_mention_everyone(G, BOT, [R], {G: 0, R: ME},
                                    [{"id": BOT, "allow": "0", "deny": str(ME)}]))
    check("precheck: administrator ignores overwrites",
          _can_mention_everyone(G, BOT, [R], {G: 0, R: ADM},
                                [{"id": G, "allow": "0", "deny": str(ME)}]))
    check("precheck line: denied says nobody is pinged",
          "nobody" in _mass_mention_line(False, "x"))
    # mass mention: flagged when the text asks for it but the response did not apply it
    check("mass mention dropped -> flagged",
          _mass_mention_dropped("@everyone hi", {"mention_everyone": False}))
    check("mass mention applied -> ok",
          not _mass_mention_dropped("@everyone hi", {"mention_everyone": True}))
    check("@here counts as mass mention", _mass_mention_dropped("@here hi", {}))
    check("no mass mention -> never flagged",
          not _mass_mention_dropped("hi all", {"mention_everyone": False}))
    # multipart: payload_json + files[0] parts, correct Content-Type header
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
        fh.write(b"selftest attachment payload")
        tmp = fh.name
    try:
        body, ctype = _multipart_body('{"content":"hi"}', [tmp])
        check("multipart Content-Type", ctype.startswith("multipart/form-data; boundary="))
        check("multipart has payload_json", b'name="payload_json"' in body)
        check("multipart has files[0]", b'name="files[0]"' in body)
        check("multipart includes attachment bytes", b"selftest attachment payload" in body)
        check("multipart boundary properly closed", body.endswith(b"--\r\n"))
    finally:
        os.unlink(tmp)
    print("selftest:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
