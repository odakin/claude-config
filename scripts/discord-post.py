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
  python3 discord-post.py --selftest

On success prints:  sent message_id=<id> channel_id=<id>
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/odakin/claude-config discord-post, 1.0)"

HINTS = {
    "1010": "Cloudflare rejected the User-Agent (should not happen via this script).",
    "401": "Unauthorized: token invalid. If the token file looks like binary noise, "
           "the repo may be git-crypt locked; run setup.sh / git-crypt unlock.",
    "50007": "Cannot send messages to this user (DMs closed or no mutual guild).",
    "50001": "Missing Access: the bot is not in that channel/guild.",
    "50013": "Missing Permissions: bot lacks Send Messages in that channel.",
    "429": "Rate limited: honor retry_after from the response body.",
}


def _request(url, token, payload=None, method=None):
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
    p.add_argument("--send", action="store_true",
                   help="actually send; without it this is a dry run")
    p.add_argument("--check", action="store_true",
                   help="read-only probe: GET the channel to validate token/UA/access")
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
        return 0

    if bool(a.content) == bool(a.content_file):
        p.error("exactly one of --content / --content-file is required")
    body = a.content if a.content else open(a.content_file, encoding="utf-8").read()
    body = body.strip()
    if not body:
        print("empty message", file=sys.stderr); return 2
    if len(body) > 2000:
        print(f"message too long for Discord ({len(body)} > 2000 chars)", file=sys.stderr)
        return 2

    if not a.send:
        target = a.channel or f"DM(user {a.dm_user})"
        print(f"[dry run] would post {len(body)} chars to {target}; "
              f"re-run with --send after the draft is approved")
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

    resp, err = _request(f"{API}/channels/{channel}/messages", token,
                         {"content": body})
    if err:
        print(_explain(*err), file=sys.stderr); return 1
    print(f"sent message_id={resp['id']} channel_id={resp['channel_id']}")
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
    check("401 hint", "git-crypt" in _explain(401, "Unauthorized"))
    # arg validation: dry-run is the default (no --send flag -> no network use)
    import inspect
    src = inspect.getsource(main)
    check("send gated behind --send", "if not a.send:" in src)
    print("selftest:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
