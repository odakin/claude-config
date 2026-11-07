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
                                         # (each line has the author's user id)
  python3 discord-post.py --token-file ... --guilds          # read-only: servers this bot is in
  python3 discord-post.py --token-file ... --channels <GUILD_ID>
                                         # read-only: that server's channels + active threads
  python3 discord-post.py ... --attach path/to/file [--attach ...]   # attach file(s)
  python3 discord-post.py --token-file ... --member-probe <USER_ID> [--member-probe ...]
                                         # read-only: is that user/bot in each guild of this bot?
  python3 discord-post.py --token-file ... --channel <ID> --message <MSG_ID> [--content-file f]
                                         # read-only: who wrote it (id, username, server nickname),
                                         # its mentions; with --content-file, whether the text matches
  python3 discord-post.py --token-file ... --channel <ID> --message <MSG_ID> --full \
      [--save-attachments <new or empty dir>]
                                         # read-only: also the whole text and attachments; saves them
                                         # into the dir (scan before importing)
  python3 discord-post.py --selftest

On success prints:  sent message_id=<id> channel_id=<id> [mentions=<user ids>]

Missing Access (403 / code 50001) does not say why. On that error this script looks the
channel id up in every guild the bot is in (the guild channel list includes private
channels the bot cannot open) and says which case it is: the bot is in that server but the
channel is private (a server admin adds the bot or its role to the channel's permissions),
or the bot is not in that server (invite it with the OAuth2 authorize URL; discord.gg
invite links cannot add a bot) (conventions/discord-bot.md #missing-access-triage).

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

--member-probe answers "is this (third-party) bot or user in any server my bot is in?"
- the first check when a third-party bot is reported compromised. The member list
endpoint needs the privileged Server Members intent (403 / code 50001 without it), but
fetching one member by id does not. Only 404 / code 10007 (Unknown Member) counts as
absent; the bot itself is probed in every guild as a control, and a guild where the
control is not "present" makes the run exit 4 (its "absent" cannot be trusted)
(conventions/discord-bot.md #third-party-bot-breach-triage).

--quote-source FILE (repeatable) checks, before the dry run and before --send, that every
quotation the text attributes to someone else (a referee, a coauthor; the text inside
「…」 / “…” / "…" or a "> " block, attributed by a word such as "referee" in the same
sentence) is a substring of the original FILE, with whitespace, line breaks and quote
characters normalised. A quotation that is not in the original is listed; --send then
refuses with exit 5 until the text quotes the original's words, or until
--allow-unmatched-quote '<reason>' is given (engine = scripts/lib/attributed_quotes.py,
CLI = scripts/check-attributed-quotes.py). Without --quote-source the script only notes how
many attributed quotations the text has (one line, never blocks). Why: a paraphrase put
inside quotation marks reaches a coauthor as the referee's words (実測), and the writer
reads it back with the original's meaning (conventions/rebuttal-letter.md
#pre-send-verification-sheet).
"""
import argparse
import json
import mimetypes
import os
import sys
import time
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
    "50001": "Missing Access: the bot cannot see that channel = either it is not in the "
             "server, or the channel is private and the bot (or its role) is not in the "
             "channel's permissions. See the 'located:' line for which.",
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


MESSAGE_TYPE_LABELS = {7: "member joined"}  # 0 (default) / 19 (reply) には印を付けない


def _ts(iso, tz=None):
    """Discord の timestamp (ISO 8601、 UTC = +00:00) を手元の時刻と時差つきで返す ("2026-01-01 09:00:00 +0900")。
    API の値は UTC で、 素のまま 19 文字に切ると時差の印が落ち、 手元の時刻と読み違える
    (実測: UTC の時刻を日本時間として記録と返事に書いた)。 tz = 変換先 (既定 = この機械の時刻)。
    読めない値はそのまま 19 文字に切って返す。 純関数 (tz を渡せば)。"""
    from datetime import datetime
    raw = iso or ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:19].replace("T", " ")
    if dt.tzinfo is None:
        return raw[:19].replace("T", " ")
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %z")


def _format_messages(msgs):
    """GET /channels/{id}/messages の結果 (新しい順) を古い順の 1 行ずつにする。
    改行は ' / ' に畳み、 添付は file 名だけ出す (= 読む用。 本文の全文は API の JSON にある)。
    書き手は username と user id。 通常の投稿と返信以外の message には type の印を付ける
    (type 7 = 参加の通知の書き手は参加した本人 = Server Members Intent を切った bot でも
    その人の id がここで引ける)。"""
    lines = []
    for m in reversed(msgs or []):
        ts = _ts(m.get("timestamp"))
        a = m.get("author") or {}
        author = f"{a.get('username', '?')} ({a.get('id', '?')})"
        text = (m.get("content") or "").replace("\n", " / ")
        mtype = m.get("type", 0)
        if mtype not in (0, 19):
            label = MESSAGE_TYPE_LABELS.get(mtype)
            mark = f"[type {mtype}" + (f" = {label}" if label else "") + "]"
            text = f"{mark} {text}" if text else mark
        atts = [a.get("filename", "") for a in m.get("attachments") or []]
        tail = f" [attachments: {', '.join(atts)}]" if atts else ""
        lines.append(f"{ts} | {m.get('id', '')} | {author} | {text}{tail}")
    return lines


def _format_guilds(guilds):
    """GET /users/@me/guilds の結果を 1 server 1 行 (id | 名前) にする。 純関数。"""
    lines = [f"{g.get('id')} | {g.get('name', '?')}" for g in guilds or []]
    lines.append(f"guilds={len(guilds or [])} (the bot sees only the servers it is in)")
    return lines


CHANNEL_TYPE_NAMES = {0: "text", 2: "voice", 4: "category", 5: "announcement",
                      10: "announcement-thread", 11: "thread", 12: "private-thread",
                      13: "stage", 15: "forum", 16: "media"}


def _format_channels(chans, threads=None):
    """GET /guilds/{g}/channels (+ /threads/active の threads) を 1 channel 1 行にする。

    行 = id | type 番号 = 名前 | #名前 | parent=<id> (#親の名前)。 並びは画面に近い順
    (親の無いもの → その下の子、 それぞれ position 順。 thread は親 channel の直後)。
    この一覧は bot が開けない非公開 channel も名前つきで返す (実測) = 読めるかは別に --check で。
    純関数 (selftest 用に API と分ける)。"""
    items = list(chans or []) + list(threads or [])
    by_id = {c.get("id"): c for c in items}

    def pos(c):
        p = c.get("position")
        return (p if isinstance(p, int) else 0, c.get("id") or "")

    def key(c):
        chain = [c]  # c, 親, 親の親 (category → channel → thread の 3 段まで)
        while len(chain) < 3 and by_id.get(chain[-1].get("parent_id")):
            chain.append(by_id[chain[-1]["parent_id"]])
        path = [pos(x) for x in reversed(chain)]  # 上から順の position
        return path + [(-1, "")] * (3 - len(path))  # 親は子より先に並ぶ

    lines = []
    for c in sorted(items, key=key):
        t = c.get("type")
        line = f"{c.get('id')} | type {t} = {CHANNEL_TYPE_NAMES.get(t, '?')} | #{c.get('name', '?')}"
        pid = c.get("parent_id")
        if pid:
            pname = (by_id.get(pid) or {}).get("name")
            line += f" | parent={pid}" + (f" (#{pname})" if pname else "")
        lines.append(line)
    lines.append(f"channels={len(chans or [])} active_threads={len(threads or [])}")
    return lines


def _get_retry(url, token, tries=4):
    """GET with rate-limit retry (429 -> sleep retry_after). Used by loops over many guilds."""
    resp, err = None, None
    for _ in range(tries):
        resp, err = _request(url, token)
        if not err or err[0] != 429:
            return resp, err
        try:
            wait = float(json.loads(err[1]).get("retry_after", 1))
        except ValueError:
            wait = 1.0
        time.sleep(min(wait, 10) + 0.2)
    return resp, err


def _find_channel(channel_id, guild_listings):
    """guild_listings = [(guild, [channel or thread dict, ...]), ...] から channel_id を探す。
    見つかれば (guild, channel)、 無ければ None (= 純関数、 selftest 用に API と分ける)。"""
    for guild, chans in guild_listings:
        for c in chans:
            if c.get("id") == channel_id:
                return guild, c
    return None


def _locate_line(channel_id, found, n_guilds):
    """403 / 50001 の後に出す 1 行。 どちらの場合かと、 次に人がする操作を書く。"""
    if found:
        guild, c = found
        return (f"located: #{c.get('name')} (type {c.get('type')}) in server "
                f"'{guild.get('name')}' ({guild.get('id')}) = the bot is in this server but "
                f"cannot see this channel (private). A server admin adds the bot or its role "
                f"in the channel's Edit Channel > Permissions. An invite link does not help.")
    return (f"located: channel {channel_id} is not in any of this bot's {n_guilds} server(s) "
            f"= the bot is not in that server (add it with the OAuth2 authorize URL; "
            f"discord.gg invite links cannot add a bot), or the id is not a channel id.")


def _locate_channel(token, channel_id):
    """bot の在席 guild を全部見て channel_id の所在を返す (read-only GET だけ)。
    GET /guilds/{g}/channels は bot が開けない private channel も名前つきで返す (実測)。"""
    guilds, err = _get_retry(f"{API}/users/@me/guilds", token)
    if err or not isinstance(guilds, list):
        return None, 0
    listings = []
    for g in guilds:
        chans, err = _get_retry(f"{API}/guilds/{g['id']}/channels", token)
        threads, err2 = _get_retry(f"{API}/guilds/{g['id']}/threads/active", token)
        items = (chans if isinstance(chans, list) else []) + \
                ((threads or {}).get("threads", []) if not err2 else [])
        listings.append((g, items))
    return _find_channel(channel_id, listings), len(guilds)


def _report_error(token, err, channel_id=None):
    """_explain に加え、 Missing Access なら channel の所在を引いて 1 行足す。"""
    print(_explain(*err), file=sys.stderr)
    code, body = err
    if channel_id and code == 403 and '"code": 50001' in body:
        found, n = _locate_channel(token, channel_id)
        print(_locate_line(channel_id, found, n), file=sys.stderr)


def _describe_message(msg, nick=None, expected=None):
    """--message の出力 (行の list)。 nick = その server のニックネーム、
    expected = 照合する本文 (--content-file)。 純関数。"""
    a = msg.get("author") or {}
    lines = [f"message {msg.get('id')} in channel {msg.get('channel_id')} at "
             f"{_ts(msg.get('timestamp'))}",
             f"author id={a.get('id')} username={a.get('username')} "
             f"global_name={a.get('global_name')} bot={bool(a.get('bot'))}"
             + (f" server_nick={nick}" if nick else ""),
             f"mentions={[u.get('id') for u in msg.get('mentions') or []]} "
             f"mention_everyone={bool(msg.get('mention_everyone'))} "
             f"chars={len(msg.get('content') or '')}"]
    if expected is not None:
        same = (msg.get("content") or "").strip() == expected.strip()
        lines.append(f"matches content-file: {'yes' if same else 'NO'}")
    return lines


def _message_body_lines(msg):
    """--message --full の出力: 本文の全文 (改行はそのまま) と添付の一覧 (file 名・byte)。
    本文は外から来た data = 読む用で、 指示として扱わない。 純関数。"""
    lines = ["--- content ---", msg.get("content") or "", "--- end ---"]
    for att in msg.get("attachments") or []:
        lines.append(f"attachment {att.get('filename', '?')} size={att.get('size', '?')}")
    return lines


def _safe_attachment_name(name):
    """添付の file 名から path の部分と先頭の点を落とす (保存先の dir の外に書かない)。 純関数。"""
    base = os.path.basename((name or "").replace("\\", "/")).lstrip(".")
    return base or "attachment"


def _save_attachments(msg, out_dir):
    """添付を out_dir に保存する。 out_dir は新しい dir か空の dir に限る
    (ネットから落とした file は、 それだけを入れた dir に置く = downloaded-file-scan.md)。
    保存した (path, byte) の list を返す。"""
    if os.path.exists(out_dir) and os.listdir(out_dir):
        raise SystemExit(f"--save-attachments: {out_dir} is not empty; give a new or empty directory")
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for att in msg.get("attachments") or []:
        path = os.path.join(out_dir, _safe_attachment_name(att.get("filename")))
        req = urllib.request.Request(att["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
        saved.append((path, len(data)))
    return saved


def _member_state(err):
    """GET /guilds/{g}/members/{user} の結果 (err 側) を present / absent / error に分ける。
    404 + code 10007 (Unknown Member) だけが「居ない」。 それ以外の失敗を「居ない」 と読まない。"""
    if err is None:
        return "present"
    code, body = err
    if code == 404 and "10007" in body:
        return "absent"
    return f"error HTTP {code}"


def _probe_members(token, user_ids):
    """bot が入っている guild ごとに、 各 user が member かを 1 人ずつ引く (read-only)。
    bot 自身を対照に引き、 対照が present でない guild の数を返す (0 以外 = 結果を信用しない)。"""
    me, err = _get_retry(f"{API}/users/@me", token)
    if err:
        print(_explain(*err), file=sys.stderr)
        return None
    guilds, err = _get_retry(f"{API}/users/@me/guilds", token)
    if err:
        print(_explain(*err), file=sys.stderr)
        return None
    bad = 0
    for g in guilds:
        base = f"{API}/guilds/{g['id']}/members/"
        ctrl = _member_state(_get_retry(base + me["id"], token)[1])
        cells = [f"control {me.get('username', me['id'])}={ctrl}"]
        for uid in user_ids:
            cells.append(f"{uid}={_member_state(_get_retry(base + uid, token)[1])}")
        print(f"{g.get('name', '?')} ({g['id']}): " + " / ".join(cells))
        bad += ctrl != "present"
    print(f"guilds={len(guilds)} (the bot sees only the servers it is in)")
    return bad


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


def _quote_gate(body, sources, allow_reason):
    """(lines to print, block --send?) for the attributed-quotation check (--quote-source)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    try:
        import attributed_quotes as aq
    except ImportError as e:
        if sources:  # the check was asked for and cannot run = do not send
            return [f"quote check: cannot load scripts/lib/attributed_quotes.py ({e})"], True
        return [], False
    if not sources:
        n = len(aq.attributed(body))
        if not n:
            return [], False
        return [f"note: {n} quotation(s) attributed to someone else; to check them against the "
                f"original add --quote-source <file> (conventions/rebuttal-letter.md"
                f"#pre-send-verification-sheet)"], False
    texts = [open(p, encoding="utf-8", errors="replace").read() for p in sources]
    quotes = aq.check_text(body, texts)
    lines = ["quote check (--quote-source):"] + ["  " + s for s in aq.format_report(quotes, "message")]
    if aq.failures(quotes) and allow_reason:
        lines.append(f"  sending anyway: --allow-unmatched-quote {allow_reason!r}")
        return lines, False
    return lines, bool(aq.failures(quotes))


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
    p.add_argument("--guilds", action="store_true",
                   help="read-only: list the servers this bot is in (id and name)")
    p.add_argument("--channels", metavar="GUILD_ID",
                   help="read-only: list that server's channels and active threads "
                        "(id, type, name, parent); private channels are listed too")
    p.add_argument("--member-probe", action="append", default=[], metavar="USER_ID",
                   help="read-only: for every guild this bot is in, is USER_ID a member? "
                        "(repeat for several; the bot itself is probed as a control)")
    p.add_argument("--message", metavar="MSG_ID",
                   help="read-only (with --channel): print who wrote that message (id, "
                        "username, server nickname) and its mentions; with --content-file, "
                        "also whether its text matches the file")
    p.add_argument("--full", action="store_true",
                   help="with --message: also print the whole text (newlines kept) and the "
                        "attachment names and sizes (--recent folds each message into one line)")
    p.add_argument("--save-attachments", metavar="DIR",
                   help="with --message: download its attachments into DIR (a new or empty "
                        "directory; scan them before importing)")
    p.add_argument("--quote-source", action="append", default=[], metavar="FILE",
                   help="original text (e.g. the referee report as txt); quotations the message "
                        "attributes to someone else must be substrings of it, or --send refuses "
                        "(exit 5). Repeat for several originals")
    p.add_argument("--allow-unmatched-quote", metavar="REASON",
                   help="send although an attributed quotation is not in --quote-source (say why)")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args(argv)

    if a.selftest:
        return selftest()
    if not a.token_file:
        p.error("--token-file is required")
    if not (a.channel or a.dm_user or a.member_probe or a.guilds or a.channels):
        p.error("--channel, --dm-user, --member-probe, --guilds or --channels is required")
    token = open(a.token_file, encoding="utf-8", errors="replace").read().strip()
    if not token or "\x00" in token:
        print("token file looks empty/binary (git-crypt locked?)", file=sys.stderr)
        return 2

    if a.guilds:
        guilds, err = _get_retry(f"{API}/users/@me/guilds", token)
        if err:
            print(_explain(*err), file=sys.stderr); return 1
        print("\n".join(_format_guilds(guilds)))
        return 0

    if a.channels:
        chans, err = _get_retry(f"{API}/guilds/{a.channels}/channels", token)
        if err:
            print(_explain(*err), file=sys.stderr); return 1
        resp, err = _get_retry(f"{API}/guilds/{a.channels}/threads/active", token)
        if err:
            print("note: active threads not listed: " + _explain(*err), file=sys.stderr)
        threads = [] if err else (resp or {}).get("threads", [])
        print("\n".join(_format_channels(chans, threads)))
        return 0

    if a.member_probe:
        bad = _probe_members(token, a.member_probe)
        if bad is None:
            return 1
        if bad:
            print(f"warning: the control (this bot) was not found in {bad} guild(s); "
                  "'absent' there proves nothing", file=sys.stderr)
            return 4
        return 0

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
            _report_error(token, err, None if a.dm_user else target); return 1
        name = f" name=#{resp['name']}" if resp.get("name") else ""
        guild = f" guild_id={resp['guild_id']}" if resp.get("guild_id") else ""
        print(f"ok channel_id={resp['id']} type={resp.get('type')}{name}{guild}")
        if resp.get("guild_id"):
            print(_mass_mention_line(*_probe_mass_mention(token, target)))
        return 0

    if a.message:
        if not a.channel:
            p.error("--message needs --channel")
        msg, err = _request(f"{API}/channels/{a.channel}/messages/{a.message}", token)
        if err:
            _report_error(token, err, a.channel); return 1
        nick = None
        chan, err = _request(f"{API}/channels/{a.channel}", token)
        uid = (msg.get("author") or {}).get("id")
        if not err and chan.get("guild_id") and uid:
            mem, err = _request(f"{API}/guilds/{chan['guild_id']}/members/{uid}", token)
            nick = (mem or {}).get("nick") if not err else None
        expected = (open(a.content_file, encoding="utf-8").read()
                    if a.content_file else None)
        print("\n".join(_describe_message(msg, nick, expected)))
        if a.full:
            print("\n".join(_message_body_lines(msg)))
        if a.save_attachments:
            for path, n in _save_attachments(msg, a.save_attachments):
                print(f"saved {path} ({n} bytes)")
            print("next: scan before importing = python3 scripts/downloaded-file-scan.py <files> "
                  "(conventions/downloaded-file-scan.md)")
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
            _report_error(token, err, None if a.dm_user else target); return 1
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
    for path in a.quote_source:
        if not os.path.isfile(path):
            print(f"quote source not found: {path}", file=sys.stderr); return 2
    quote_lines, quote_block = _quote_gate(body, a.quote_source, a.allow_unmatched_quote)
    for line in quote_lines:
        print(line, file=sys.stderr if quote_block else sys.stdout)
    if quote_block and a.send:
        print("not sent: a quotation attributed to someone else is not in --quote-source "
              "(quote the original's words, or --allow-unmatched-quote '<reason>')", file=sys.stderr)
        return 5
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
        if quote_block:
            print("note: --send will refuse (exit 5) until the quotations above match "
                  "--quote-source or --allow-unmatched-quote '<reason>' is given")
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
        _report_error(token, err, None if a.dm_user else channel); return 1
    n_att = len(resp.get("attachments", []))
    tail = f" attachments={n_att}" if n_att else ""
    mentioned = [u.get("id") for u in resp.get("mentions") or []]
    if mentioned:
        tail += f" mentions={','.join(mentioned)}"
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
    check("50001 hint names the private-channel case",
          "private" in _explain(403, '{"message": "Missing Access", "code": 50001}'))
    # Missing Access triage: find the channel in the bot's guild listings (synthetic ids)
    lst = [({"id": "g1", "name": "A"}, [{"id": "c1", "name": "open", "type": 0}]),
           ({"id": "g2", "name": "B"}, [{"id": "c2", "name": "seminar", "type": 0}])]
    found = _find_channel("c2", lst)
    check("locate: found in the second guild",
          found is not None and found[0]["id"] == "g2" and found[1]["name"] == "seminar")
    check("locate: found -> says private + permissions, invite does not help",
          "private" in _locate_line("c2", found, 2)
          and "Permissions" in _locate_line("c2", found, 2)
          and "invite link does not help" in _locate_line("c2", found, 2))
    check("locate: absent -> not in any server + authorize URL",
          _find_channel("c9", lst) is None
          and "not in any of this bot's 2" in _locate_line("c9", None, 2)
          and "authorize URL" in _locate_line("c9", None, 2))
    # --message: author, server nickname, mentions, content comparison
    msg = {"id": "m1", "channel_id": "c2", "timestamp": "2026-01-01T00:00:00.000+00:00",
           "author": {"id": "u1", "username": "x1", "global_name": "X"},
           "mentions": [{"id": "u2"}], "mention_everyone": False, "content": "hello"}
    d = _describe_message(msg, nick="Nick", expected="hello\n")
    check("message: author id + server nick", "id=u1" in d[1] and "server_nick=Nick" in d[1])
    check("message: mentions listed", "mentions=['u2']" in d[2] and "chars=5" in d[2])
    check("message: content compare ignores trailing newline", d[3].endswith("yes"))
    check("message: mismatch says NO",
          _describe_message(msg, expected="other")[-1].endswith("NO"))
    check("message: no expected -> no compare line", len(_describe_message(msg)) == 3)
    # --message --full: whole text with newlines, attachment names and sizes
    msg2 = dict(msg, content="line1\nline2",
                attachments=[{"filename": "a.pdf", "size": 12, "url": "u"}])
    body = _message_body_lines(msg2)
    check("full: text kept with its newline", "line1\nline2" in body)
    check("full: attachment listed with size", "attachment a.pdf size=12" in body)
    check("full: no attachments -> just the text block", len(_message_body_lines(msg)) == 3)
    # --save-attachments: names cannot leave the target directory
    check("attachment name: path parts dropped", _safe_attachment_name("../../x/evil.sh") == "evil.sh")
    check("attachment name: leading dots dropped", _safe_attachment_name(".bashrc") == "bashrc")
    check("attachment name: empty -> placeholder", _safe_attachment_name("") == "attachment")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "x"), "w").close()
        try:
            _save_attachments({"attachments": []}, td); refused = False
        except SystemExit:
            refused = True
        check("save: a non-empty directory is refused", refused)
    # timestamps: Discord gives UTC; print local time with the offset (not the bare UTC wall clock)
    from datetime import timezone, timedelta
    check("ts: UTC converted to the given zone with offset",
          _ts("2026-01-01T00:00:00.000+00:00", tz=timezone(timedelta(hours=9))) == "2026-01-01 09:00:00 +0900")
    check("ts: unparsable value falls back to the raw text", _ts("garbage") == "garbage")
    # --recent formatter: API returns newest first; print oldest first, fold newlines, list attachments
    fmt = _format_messages([
        {"id": "2", "timestamp": "2026-01-02T03:04:05.000+00:00", "author": {"username": "b"},
         "content": "line1\nline2", "attachments": [{"filename": "x.pdf"}]},
        {"id": "1", "timestamp": "2026-01-01T00:00:00.000+00:00", "author": {"username": "a"},
         "content": "first", "attachments": []},
    ])
    check("recent: oldest first", len(fmt) == 2 and fmt[0].endswith("| a (?) | first"))
    check("recent: newline folded + attachments", fmt[1].endswith("line1 / line2 [attachments: x.pdf]"))
    # --recent: author id on every line; a member-join notice (type 7) is marked and its
    # author is the person who joined (= how a bot without the Members intent gets the id)
    fmt = _format_messages([
        {"id": "4", "type": 19, "timestamp": "2026-01-01T00:00:02.000+00:00",
         "author": {"id": "u9", "username": "z"}, "content": "re"},
        {"id": "3", "type": 7, "timestamp": "2026-01-01T00:00:01.000+00:00",
         "author": {"id": "u7", "username": "newcomer"}, "content": ""},
    ])
    check("recent: author id shown", "| newcomer (u7) |" in fmt[0])
    check("recent: join notice marked", fmt[0].endswith("| [type 7 = member joined]"))
    check("recent: reply (type 19) not marked", fmt[1].endswith("| z (u9) | re"))
    # --guilds: one server per line + a count
    g = _format_guilds([{"id": "g1", "name": "Lab"}, {"id": "g2", "name": "Show"}])
    check("guilds: id | name per line", g[:2] == ["g1 | Lab", "g2 | Show"])
    check("guilds: count line", g[-1].startswith("guilds=2"))
    # --channels: parent by id and name; children follow their category in position order;
    # a thread follows its parent channel; unknown type is '?'
    ch = _format_channels(
        [{"id": "c9", "type": 0, "name": "loose", "position": 0},
         {"id": "k1", "type": 4, "name": "Talks", "position": 1},
         {"id": "c2", "type": 0, "name": "seminar", "position": 1, "parent_id": "k1"},
         {"id": "c1", "type": 2, "name": "room", "position": 0, "parent_id": "k1"},
         {"id": "c5", "type": 99, "name": "odd", "position": 2}],
        [{"id": "t1", "type": 11, "name": "q-and-a", "parent_id": "c2"}])
    order = [line.split(" | ")[0] for line in ch[:-1]]
    check("channels: category, its children in order, thread after its parent",
          order == ["c9", "k1", "c1", "c2", "t1", "c5"])
    check("channels: parent id and name", "| parent=k1 (#Talks)" in ch[order.index("c2")])
    check("channels: type number and name", "| type 4 = category | #Talks" in ch[1])
    check("channels: unknown type", "| type 99 = ? | #odd" in ch[order.index("c5")])
    check("channels: count line", ch[-1] == "channels=5 active_threads=1")
    # arg validation: dry-run is the default (no --send flag -> no POST; the dry run
    # only GETs when it pre-checks a mass mention)
    import inspect
    src = inspect.getsource(main)
    check("send gated behind --send", "if not a.send:" in src)
    # --quote-source: an attributed quotation not in the original blocks --send, before the POST
    check("quote gate runs before the dry run / send branch",
          src.index("_quote_gate(body") < src.index("if not a.send:"))
    with tempfile.TemporaryDirectory() as td:
        orig = os.path.join(td, "orig.txt")
        with open(orig, "w", encoding="utf-8") as fh:
            fh.write("The bias appears when the sample is restricted to the northern stations.\n")
        lines, block = _quote_gate('The referee says "the bias is small everywhere".', [orig], None)
        check("quote gate: invented attributed quotation blocks", block and any("✗" in s for s in lines))
        lines, block = _quote_gate('The referee writes "restricted to the northern stations".', [orig], None)
        check("quote gate: verbatim quotation passes", not block)
        lines, block = _quote_gate('The referee says "the bias is small everywhere".', [orig], "checked by hand")
        check("quote gate: --allow-unmatched-quote passes with the reason shown",
              not block and any("checked by hand" in s for s in lines))
        lines, block = _quote_gate('The referee says "the bias is small everywhere".', [], None)
        check("quote gate: no source -> one note, never blocks", not block and len(lines) == 1)
        lines, block = _quote_gate("hello all", [], None)
        check("quote gate: no quotation -> silent", not block and not lines)
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
    check("precheck: bot-role overwrite deny beats an @everyone-role grant",
          not _can_mention_everyone(G, BOT, [R], {G: ME, R: 0},
                                    [{"id": R, "allow": "0", "deny": str(ME)}]))
    check("precheck: @everyone-role grant reaches the bot without overwrites",
          _can_mention_everyone(G, BOT, [R], {G: ME, R: 0}, []))
    # --member-probe: only 404 + Unknown Member (10007) means absent
    check("member probe: success -> present", _member_state(None) == "present")
    check("member probe: 404/10007 -> absent",
          _member_state((404, '{"message": "Unknown Member", "code": 10007}')) == "absent")
    check("member probe: 404 other code -> error, not absent",
          _member_state((404, '{"message": "Unknown Guild", "code": 10004}')).startswith("error"))
    check("member probe: 403 -> error, not absent",
          _member_state((403, '{"code": 50001}')).startswith("error"))
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
