#!/usr/bin/env python3
"""discord-board-bridge.py — Discord ⇄ agent-board bridge engine (決定的 tick、 LLM 不使用、 config 駆動)。

一般則 = conventions/multi-session-coordination.md#chat-board-bridge (bridge は transport のみ、 依頼者 identity は人間、
受領は人間の ✅ reaction、 worker は resident runner)。 Discord 側の機構 fact = conventions/discord-bot.md#webhook-personas。

やること (毎 tick):
  1. config の各 channel (+ 組織図 org_file の部長室 / 課 channel) を cursor 以降だけ GET /channels/{id}/messages?after= で読む
     (cursor 不在 = 初回は最新 message id を cursor にして何も取り込まない = 履歴を request 化しない。 直近だけ拾うなら --backfill-minutes)。
  2. allowed_authors の人間の message (guild channel は mention_required、 DM / 役割 channel は不要) を 1 通 = 1 request として
     `board.py request --agent human --session discord:<author id> --to <agent> --to-session <resident>` で起票。
     project = channel の担当 (組織図の課 / 部)、 1 行目の `[project]` で上書き可 (config `projects` に列挙 = owner の source
     classification 済み ordinary source のみ)。 ack は課長 persona (webhook username)、 担当係は依頼文の keyword で選ぶ。
  3. 追跡中 request を `board.py show --request <id> --json --sync` で見て、 status が変わっていたら係長 persona で返信
     (🔧 着手 / 📤 提出 + deliverables / ⛔ blocker / ↩️ 差し戻し)。
  4. 📤 提出の返信に依頼者が ✅ reaction を付けていたら `board.py accept` を依頼者 identity で post (references = ✅ message の link)
     → 課長 persona が「✅ 受領済」。
  5. heartbeat (<state_dir>/heartbeat.txt) + state.json (cursor / request 追跡、 machine-local)。

やらないこと: worker を起こす (= resident runner の仕事、 poll/dispatch 分離)、 request 内容の要約・翻訳・判断、
allowed_authors 外の message への反応、 config に無い project への起票、 restricted source。

config (YAML、 --config で必須。 instance は owner の private layer):
  token_file / bot_user_id / allowed_authors / channels (channel_id, name, guild_id, project, dm, mention_required) /
  projects ({key: repo or null}) / default_project / to_agent / to_session ("resident-<host>-claude") / resident_host /
  resident_ledger (active-routine-host.json、 <host> の既定) / board_root (board.py のある repo) / source_root (~/Claude 等、
  <source_root>/<project> が --source) / state_dir / webhook_file / org_file / org_ids_file / reply。

安全側 default: --dry = Discord も board も書かない。 既定 = 起票 + 返信 (返信先は config 列挙 channel のみ = owner の standing OK)。
--setup-webhooks = 列挙 channel の persona webhook を作って webhook_file へ (要 Manage Webhooks)。 --selftest = network 無し fixture。

Message 書式 (依頼者向け): 1 行目 = 題 (任意で先頭に `[project]`)、 2 行目以降 = 完了条件 (無ければ題を完了条件にする)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/odakin/claude-config discord-board-bridge, 0.2)"  # 層1 discord-bot.md#discord-api-user-agent
ACCEPT_EMOJI = "✅"
STATUS_TEXT = {  # board status → Discord 返信 (status が変わった時だけ 1 回)
    "working": "🔧 着手 (claim)",
    "submitted": "📤 提出 — この message に ✅ を付けると受領 (accept) になります",
    "blocked": "⛔ blocker — 依頼者の回答待ち (board で update を返してください)",
    "accepted": "✅ 受領済 (closed)",
    "revision": "↩️ 差し戻し (revision) — worker の再提出待ち",
    "abandoned": "🗑 放棄 (abandoned)",
}


# ---------- config / state ----------

def _p(v: str) -> str:
    return os.path.expanduser(str(v))


def load_config(path: Path) -> dict:
    import yaml
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("token_file", "")
    cfg.setdefault("board_root", "")        # board.py のある repo (例 ~/Claude/agent-board)
    cfg.setdefault("source_root", "~/Claude")  # <source_root>/<project> = request の --source
    cfg.setdefault("state_dir", "~/.local/state/discord-board-bridge")
    cfg.setdefault("resident_ledger", "")   # active-routine-host.json (任意、 <host> の既定)
    cfg.setdefault("bot_user_id", "")
    cfg.setdefault("allowed_authors", [])
    cfg.setdefault("channels", [])
    cfg.setdefault("projects", {})
    cfg.setdefault("default_project", "")
    cfg.setdefault("to_agent", "claude")
    cfg.setdefault("to_session", "resident-<host>-claude")
    cfg.setdefault("resident_host", "")
    cfg.setdefault("reply", True)
    cfg.setdefault("webhook_file", "")   # 役割 persona (channel ごとの webhook) の保管 file、 空なら bot 名義で返信
    cfg.setdefault("org_file", "")       # 組織図 YAML (部 → 課 → 係 + persona 名)、 空なら channels 列挙だけ
    cfg.setdefault("org_ids_file", "")   # discord-org-build.py が書き戻す channel id
    for k in ("token_file", "board_root", "source_root", "state_dir", "resident_ledger", "webhook_file", "org_file", "org_ids_file"):
        if cfg.get(k):
            cfg[k] = _p(cfg[k])
    cfg["allowed_authors"] = [str(a) for a in cfg["allowed_authors"]]
    seen = {str(c["channel_id"]) for c in cfg["channels"]}
    for e in org_channels(cfg):
        if e["channel_id"] not in seen:
            cfg["channels"].append(e); seen.add(e["channel_id"])
    for c in cfg["channels"]:
        c.setdefault("personas", {})
    return cfg


def org_channels(cfg: dict, org: dict | None = None, ids: dict | None = None) -> list[dict]:
    """組織図 (kindo-org.yaml) + ids → bridge の channel entry。 部長室 = 部長が ack も進捗も、 課 = 課長が ack / 係長が進捗。"""
    try:
        if org is None:
            import yaml
            org = yaml.safe_load(Path(os.path.expanduser(cfg["org_file"])).read_text(encoding="utf-8"))
        if ids is None:
            ids = json.loads(Path(os.path.expanduser(cfg["org_ids_file"])).read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    gid = str(org.get("guild_id", ""))
    for d in org.get("departments", []):
        rec = (ids.get("departments") or {}).get(d["key"]) or {}
        if d.get("head_channel", True) and rec.get("head_channel_id"):
            out.append({"channel_id": str(rec["head_channel_id"]), "name": f"#{d['name']}長室", "guild_id": gid, "project": d["project"],
                        "mention_required": False, "personas": {"ack": d.get("boss"), "done": d.get("boss"), "units": []}})
        for s in d.get("sections", []):
            cid = (rec.get("sections") or {}).get(s["key"])
            if not cid:
                continue
            units = [{"name": u["name"], "boss": u["boss"], "keywords": [str(k).lower() for k in (u.get("keywords") or [])]} for u in s.get("units", [])]
            out.append({"channel_id": str(cid), "name": f"#{s.get('channel_name') or s['name']}", "guild_id": gid, "project": s.get("project") or d["project"],
                        "mention_required": False, "personas": {"ack": s.get("boss"), "done": s.get("boss"), "units": units}})
    return out


def pick_unit(text: str, units: list[dict]) -> dict | None:
    """依頼文の keyword で係を選ぶ (先勝ち)、 無ければ筆頭係、 係が無ければ None。"""
    low = (text or "").lower()
    for u in units:
        if any(k and k in low for k in u.get("keywords", [])):
            return u
    return units[0] if units else None


def active_routine_host(ledger: str | None) -> str | None:
    """runner が走る host = active-routine-host 台帳 (multi-machine-state.md#account-host-failover)。 bridge がどの機械で走っても宛先は runner の host。"""
    if not ledger:
        return None
    try:
        return (json.loads(Path(ledger).read_text(encoding="utf-8")).get("host") or None)
    except Exception:
        return None


def resident_target(cfg: dict, ledger_host: str | None = None) -> str:
    host = cfg.get("resident_host") or ledger_host or active_routine_host(cfg.get("resident_ledger")) or socket.gethostname().split(".")[0]
    return str(cfg["to_session"]).replace("<host>", host)


def load_state(state_dir: Path) -> dict:
    p = state_dir / "state.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"channels": {}, "requests": {}}


def save_state(st: dict, state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def write_heartbeat(note: str, state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "heartbeat.txt").write_text(
        f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n{note}\n", encoding="utf-8")


# ---------- Discord (stdlib) ----------

class Discord:
    def __init__(self, token: str):
        self.token = token

    def _req(self, path: str, payload=None, method=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(API + path, data=data, method=method or ("POST" if data else "GET"),
                                     headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"discord {method or 'GET'} {path} → {e.code}: {e.read().decode(errors='replace')[:300]}")

    def messages_after(self, channel_id: str, after: str | None, limit: int = 100) -> list[dict]:
        q = f"?limit={limit}" + (f"&after={after}" if after else "")
        rows = self._req(f"/channels/{channel_id}/messages{q}")
        return sorted(rows, key=lambda m: int(m["id"]))  # API は新→旧、 処理は古→新

    def latest_id(self, channel_id: str) -> str | None:
        rows = self._req(f"/channels/{channel_id}/messages?limit=1")
        return rows[0]["id"] if rows else None

    def post(self, channel_id: str, content: str, reply_to: str | None = None) -> dict:
        payload = {"content": content[:1990], "allowed_mentions": {"parse": []}}
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}
        return self._req(f"/channels/{channel_id}/messages", payload)

    def post_webhook(self, wh: dict, content: str, username: str | None = None) -> dict:
        """役割 persona で投稿 (= webhook は message ごとに username / avatar を持てる)。 webhook は message_reference 不可。"""
        payload = {"content": content[:1990], "allowed_mentions": {"parse": []}}
        if username:
            payload["username"] = username
        return self._req(f"/webhooks/{wh['id']}/{wh['token']}?wait=true", payload)

    def reactors(self, channel_id: str, message_id: str, emoji: str = ACCEPT_EMOJI) -> set[str]:
        e = urllib.parse.quote(emoji, safe="")
        try:
            rows = self._req(f"/channels/{channel_id}/messages/{message_id}/reactions/{e}?limit=100")
        except RuntimeError as ex:
            if "→ 404" in str(ex):
                return set()
            raise
        return {str(u["id"]) for u in rows}


# ---------- pure logic (selftest 対象) ----------

def parse_request(content: str, bot_id: str, projects: dict, default_project: str) -> dict | None:
    """Discord message → {project, title, acceptance}. project 不明 / 空文は None。"""
    text = re.sub(rf"<@!?{re.escape(bot_id)}>", "", content).strip() if bot_id else content.strip()
    if not text:
        return None
    lines = [ln.rstrip() for ln in text.splitlines()]
    first = lines[0].strip()
    project = default_project
    m = re.match(r"^\[([A-Za-z0-9._-]+)\]\s*(.*)$", first)
    if m:
        project, first = m.group(1), m.group(2).strip()
    if project not in projects or not first:
        return None
    body = "\n".join(lines[1:]).strip()
    return {"project": project, "title": first[:200], "acceptance": (body or first)[:2000]}


def channel_project(ch: dict, default_project: str) -> str:
    """channel が役割 (= project) を持つならそれが既定 (1 行目の [project] は上書き可)。"""
    return str(ch.get("project") or default_project)


def load_webhooks(cfg: dict) -> dict:
    f = cfg.get("webhook_file")
    if not f:
        return {}
    try:
        return json.loads(Path(os.path.expanduser(f)).read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_candidate(msg: dict, allowed: list[str], bot_id: str, mention_required: bool) -> bool:
    a = msg.get("author") or {}
    if a.get("bot") or str(a.get("id")) not in allowed:
        return False
    if not (msg.get("content") or "").strip():
        return False
    if mention_required and bot_id and f"<@{bot_id}>" not in msg["content"] and f"<@!{bot_id}>" not in msg["content"]:
        return False
    return True


DISCORD_EPOCH_MS = 1420070400000  # 2015-01-01T00:00:00Z


def snowflake_at(when: dt.datetime) -> str:
    """その時刻に対応する Discord snowflake (= `after=` に使える時刻 cursor)。"""
    ms = int(when.timestamp() * 1000) - DISCORD_EPOCH_MS
    return str(max(ms, 0) << 22)


def init_cursor(state_ch: dict, latest: str | None, floor: str | None = None) -> bool:
    """cursor 不在なら初期化して True。 既定 = 最新 id (= 履歴を取り込まない)。
    floor (時刻 snowflake、 --backfill-minutes) があれば min(latest, floor) = その時刻以降の投稿だけ次 tick で拾う
    (= 初回 tick より前に書かれた直近の依頼を落とさない、 それより古い履歴は依然として取り込まない)。"""
    if state_ch.get("cursor"):
        return False
    cur = latest or "0"
    if floor and int(floor) < int(cur):
        cur = floor
    state_ch["cursor"] = cur
    return True


def status_reply(row: dict, prev: str | None) -> str | None:
    st = row.get("status")
    if not st or st == prev or st not in STATUS_TEXT:
        return None
    lines = [f"{STATUS_TEXT[st]}  `{row.get('request_id')}`"]
    for key in ("submission", "question", "review"):
        e = row.get(key)
        if e and key == {"submitted": "submission", "blocked": "question", "revision": "review"}.get(st):
            lines.append(f"> {e.get('summary') or ''}"[:600])
            for d in (e.get("deliverables") or []) + (e.get("references") or []):
                lines.append(f"• {d}")
    return "\n".join(lines)


def thread_id(mid: str, when: dt.date) -> str:
    return f"{when.isoformat()}-discord-{mid[-6:]}"


def jump_link(channel: dict, mid: str) -> str:
    g = channel.get("guild_id") or "@me"
    return f"https://discord.com/channels/{g}/{channel['id']}/{mid}"


# ---------- board (subprocess) ----------

def board(cfg: dict, args: list[str], timeout: int = 240, stdout_only: bool = False) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(Path(cfg["board_root"]) / "scripts" / "board.py"), *args], capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout if stdout_only else p.stdout + p.stderr).strip()


def board_request(cfg: dict, req: dict, author_id: str, tid: str, link: str) -> tuple[str | None, str]:
    src = str(Path(cfg["source_root"]) / req["project"])
    rc, out = board(cfg, ["request", "--agent", "human", "--session", f"discord:{author_id}", "--session-name", "discord bridge",
                     "--source", src, "--policy", "ordinary", "--project", req["project"], "--repo", cfg["projects"][req["project"]] or "",
                     "--thread", tid, "--to", cfg["to_agent"], "--to-session", resident_target(cfg),
                     "--summary", req["title"], "--acceptance", req["acceptance"], "--reference", link])
    m = re.search(r"posted (\S+)", out)
    return (m.group(1) if rc == 0 and m else None), out


def board_show(cfg: dict, request_id: str, author_id: str) -> dict | None:
    # --session は必須 (board.py が native id を要求)、 reader = 依頼者 identity。 warnings は stderr なので stdout だけ JSON parse。
    rc, out = board(cfg, ["show", "--agent", "human", "--session", f"discord:{author_id}", "--request", request_id, "--json", "--sync"], stdout_only=True)
    if rc != 0 or not out.startswith("{"):
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def board_accept(cfg: dict, project: str, author_id: str, request_id: str, submit_event: str, reference: str) -> tuple[int, str]:
    # schema は accept にも references ≥ 1 を要求 (2026-09-08 初回 live で `$.references: too few items`) → ✅ を付けた message の jump link を証跡に
    return board(cfg, ["accept", "--agent", "human", "--session", f"discord:{author_id}", "--session-name", "discord bridge",
                  "--source", str(Path(cfg["source_root"]) / project), "--policy", "ordinary", "--request", request_id,
                  "--reply-to", submit_event, "--summary", "Discord で依頼者が ✅ reaction (bridge が転記)", "--reference", reference])


# ---------- tick ----------

def tick(args) -> int:
    cfg = load_config(args.config)
    log = lambda m: print(f"[discord-board-bridge] {m}", flush=True)
    state_dir = Path(args.state_dir or cfg["state_dir"])
    if not cfg.get("board_root") or not cfg.get("token_file"):
        log("✗ config needs board_root and token_file"); return 2
    token = Path(cfg["token_file"]).read_text(encoding="utf-8").strip()
    if not token or token.startswith("\x00GITCRYPT"):
        log("✗ token unreadable (git-crypt locked?)"); write_heartbeat("token unreadable", state_dir); return 1
    dc = Discord(token)
    st = load_state(state_dir)
    bot_id = str(cfg["bot_user_id"])
    n_new = n_status = n_accept = 0
    chmap = {str(ch["channel_id"]): ch for ch in cfg["channels"]}
    webhooks = load_webhooks(cfg)
    floor = snowflake_at(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=args.backfill_minutes)) if args.backfill_minutes else None

    def say(cid: str, content: str, reply_to: str | None = None, persona: str | None = None) -> dict:
        """channel に webhook が在れば persona (部長 / 課長 / 係長) の名義、 無ければ bot 名義。 webhook は reply 不可なので本文で足りる形にする。"""
        wh = webhooks.get(cid)
        if wh and chmap.get(cid, {}).get("persona", True):
            return dc.post_webhook(wh, content, username=persona or wh.get("name"))
        return dc.post(cid, content, reply_to=reply_to)

    # 1-2. intake
    for ch in cfg["channels"]:
        cid = str(ch["channel_id"]); sch = st["channels"].setdefault(cid, {})
        try:
            if init_cursor(sch, dc.latest_id(cid), floor):
                log(f"channel {ch.get('name', cid)}: cursor initialised at {sch['cursor']}" + (f" (backfill {args.backfill_minutes} min)" if floor else " (history not ingested)"))
                if not floor:
                    continue
            msgs = dc.messages_after(cid, sch["cursor"])
        except Exception as ex:
            log(f"✗ channel {ch.get('name', cid)}: {ex}"); continue
        for m in msgs:
            sch["cursor"] = m["id"]
            if not is_candidate(m, cfg["allowed_authors"], bot_id, bool(ch.get("mention_required", not ch.get("dm")))):
                continue
            req = parse_request(m["content"], bot_id, cfg["projects"], channel_project(ch, cfg["default_project"]))
            author = str(m["author"]["id"]); link = jump_link({"id": cid, "guild_id": ch.get("guild_id")}, m["id"])
            if req is None:
                log(f"skip {m['id']}: unparsable / unknown project → reply hint")
                if not args.dry and cfg["reply"]:
                    say(cid, "❓ 起票できません: 1 行目 = 題 (任意で `[project]` を先頭に)、 使える project = " + ", ".join(cfg["projects"]), reply_to=m["id"])
                continue
            tid = thread_id(m["id"], dt.date.today())
            log(f"→ request [{req['project']}] {req['title']!r} thread={tid}" + (" (dry)" if args.dry else ""))
            if args.dry:
                continue
            rid, out = board_request(cfg, req, author, tid, link)
            if not rid:
                log(f"✗ board request failed: {out[-300:]}")
                if cfg["reply"]:
                    say(cid, f"⚠️ board 起票に失敗: {out[-200:]}", reply_to=m["id"])
                continue
            n_new += 1
            ack = None
            pers = ch.get("personas") or {}
            unit = pick_unit(m["content"], pers.get("units") or [])
            worker_persona = (unit or {}).get("boss") or pers.get("ack")
            if cfg["reply"]:
                handoff = f"。 {unit['name']} ({unit['boss']}) に回します" if unit else ""
                ack = say(cid, f"📮 承りました: 「{req['title']}」{handoff}。 伝票 `{rid}` ({req['project']}/{tid}、 実働 `{resident_target(cfg)}`)",
                          reply_to=m["id"], persona=pers.get("ack"))
            st["requests"][rid] = {"channel": cid, "message_id": m["id"], "author": author, "project": req["project"], "thread": tid,
                                   "status": "requested", "status_message_id": (ack or {}).get("id"), "submit_event": None,
                                   "persona": worker_persona, "done_persona": pers.get("done")}
        if not args.dry:
            save_state(st, state_dir)

    # 3-4. status follow + reaction accept
    for rid, r in list(st["requests"].items()):
        if r.get("status") in {"accepted", "abandoned"}:
            continue
        row = board_show(cfg, rid, r["author"])
        if not row:
            log(f"? show failed for {rid}"); continue
        text = status_reply(row, r.get("status"))
        if text:
            log(f"status {rid}: {r.get('status')} → {row['status']}" + (" (dry)" if args.dry else ""))
            if not args.dry:
                r["status"] = row["status"]
                if row.get("submission"):
                    r["submit_event"] = row["submission"].get("event_id")
                if cfg["reply"]:
                    posted = say(r["channel"], text, reply_to=r["message_id"], persona=r.get("persona"))
                    r["status_message_id"] = posted.get("id")
                n_status += 1
        if r.get("status") == "submitted" and r.get("status_message_id") and r.get("submit_event"):
            try:
                who = dc.reactors(r["channel"], r["status_message_id"])
            except Exception as ex:
                log(f"? reactions {rid}: {ex}"); who = set()
            if r["author"] in who:
                log(f"✅ reaction by requester on {rid} → accept" + (" (dry)" if args.dry else ""))
                if not args.dry:
                    link = jump_link({"id": r["channel"], "guild_id": chmap.get(r["channel"], {}).get("guild_id")}, r["status_message_id"])
                    rc, out = board_accept(cfg, r["project"], r["author"], rid, r["submit_event"], link)
                    if rc == 0:
                        r["status"] = "accepted"; n_accept += 1
                        if cfg["reply"]:
                            say(r["channel"], f"{STATUS_TEXT['accepted']}  `{rid}`", reply_to=r["message_id"], persona=r.get("done_persona"))
                    else:
                        log(f"✗ accept failed: {out[-300:]}")
    if not args.dry:
        save_state(st, state_dir)
    open_n = sum(1 for r in st["requests"].values() if r.get("status") not in {"accepted", "abandoned"})
    write_heartbeat(f"new={n_new} status={n_status} accept={n_accept} open={open_n} dry={args.dry}", state_dir)
    log(f"done: new={n_new} status={n_status} accept={n_accept} open={open_n}")
    return 0


def setup_webhooks(args) -> int:
    """guild channel ごとに persona webhook を作って webhook_file に保存 (冪等 = 既存 entry は skip)。 要 Manage Webhooks。"""
    cfg = load_config(args.config)
    if not cfg.get("webhook_file"):
        print("✗ config needs webhook_file"); return 2
    token = Path(cfg["token_file"]).read_text(encoding="utf-8").strip()
    dc = Discord(token)
    f = Path(cfg["webhook_file"])
    cur = load_webhooks(cfg)
    for ch in cfg["channels"]:
        cid = str(ch["channel_id"])
        if ch.get("dm") or cid in cur:
            continue
        name = str(ch.get("name", cid)).lstrip("#")
        try:
            wh = dc._req(f"/channels/{cid}/webhooks", {"name": name})
        except RuntimeError as ex:
            print(f"✗ {name}: {ex}"); continue
        cur[cid] = {"id": wh["id"], "token": wh["token"], "name": name}
        print(f"✓ webhook for {name}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(f, 0o600)
    print(f"saved {len(cur)} webhook(s) → {f}")
    return 0


# ---------- selftest ----------

def selftest() -> int:
    projects = {"odakin-prefs": "odakin/odakin-prefs", "quantum-mechanics-textbook": None}
    # message parsing
    r = parse_request("<@123> [quantum-mechanics-textbook] 図 1.1 候補を 3 案\n各案 1 段落で。", "123", projects, "odakin-prefs")
    assert r == {"project": "quantum-mechanics-textbook", "title": "図 1.1 候補を 3 案", "acceptance": "各案 1 段落で。"}, r
    r = parse_request("README の誤字を直す", "123", projects, "odakin-prefs")
    assert r["project"] == "odakin-prefs" and r["acceptance"] == "README の誤字を直す", r   # body 無し → 題 = 完了条件
    assert parse_request("[nope] x", "123", projects, "odakin-prefs") is None            # 未登録 project = 起票しない
    assert parse_request("<@123>", "123", projects, "odakin-prefs") is None              # mention だけ
    # candidate filter
    me = {"author": {"id": "1", "bot": False}, "content": "<@123> hi"}
    assert is_candidate(me, ["1"], "123", True) and not is_candidate(me, ["2"], "123", True)
    assert not is_candidate({"author": {"id": "1", "bot": True}, "content": "x"}, ["1"], "123", False)      # bot 自身
    assert not is_candidate({"author": {"id": "1"}, "content": "no mention"}, ["1"], "123", True)          # guild は mention 必須
    assert is_candidate({"author": {"id": "1"}, "content": "no mention"}, ["1"], "123", False)             # DM は不要
    # cursor init
    ch = {}
    assert init_cursor(ch, "999") and ch["cursor"] == "999" and not init_cursor(ch, "1000") and ch["cursor"] == "999"
    ch = {}; assert init_cursor(ch, "999", floor="500") and ch["cursor"] == "500"      # backfill: 時刻 floor が古ければそちら
    ch = {}; assert init_cursor(ch, "400", floor="500") and ch["cursor"] == "400"      # latest の方が古ければ latest (= 何も取り込まない)
    assert snowflake_at(dt.datetime(2015, 1, 1, tzinfo=dt.timezone.utc)) == "0" and int(snowflake_at(dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc))) > 1546000000000000000
    # status replies
    row = {"status": "submitted", "request_id": "r1", "submission": {"event_id": "s1", "summary": "done", "deliverables": ["odakin-prefs/x.md"]}}
    t = status_reply(row, "working")
    assert t and "📤" in t and "done" in t and "odakin-prefs/x.md" in t and "r1" in t, t
    assert status_reply(row, "submitted") is None                                       # 変化なし = 沈黙
    assert status_reply({"status": "requested"}, None) is None                            # 起票直後は ack が担う
    assert "⛔" in status_reply({"status": "blocked", "request_id": "r", "question": {"summary": "q?"}}, "working")
    assert thread_id("1234567890", dt.date(2026, 9, 8)) == "2026-09-08-discord-567890"
    assert channel_project({"project": "lectures"}, "odakin-prefs") == "lectures" and channel_project({}, "odakin-prefs") == "odakin-prefs"
    assert parse_request("成績の集計", "123", {**projects, "lectures": None}, channel_project({"project": "lectures"}, "odakin-prefs"))["project"] == "lectures"
    org = {"guild_id": "1", "departments": [
        {"key": "a", "name": "甲部", "project": "p", "boss": "甲 長", "sections": [
            {"key": "a1", "name": "甲一課", "boss": "一 課長", "project": "pp",
             "units": [{"name": "一係", "boss": "一 係長", "keywords": ["印刷"]}, {"name": "二係", "boss": "二 係長", "keywords": ["メール"]}]}]},
        {"key": "b", "name": "乙室", "project": "q", "head_channel": False, "boss": None, "sections": [{"key": "b1", "name": "乙課", "boss": "乙 課長", "units": []}]}]}
    ids = {"departments": {"a": {"head_channel_id": "10", "sections": {"a1": "11"}}, "b": {"sections": {"b1": "20"}}}}
    ent = org_channels({}, org, ids)
    assert [(e["channel_id"], e["project"], e["personas"]["ack"]) for e in ent] == [("10", "p", "甲 長"), ("11", "pp", "一 課長"), ("20", "q", "乙 課長")], ent
    units = ent[1]["personas"]["units"]
    assert pick_unit("メールの返信を", units)["boss"] == "二 係長" and pick_unit("なんでも", units)["boss"] == "一 係長" and pick_unit("x", []) is None
    cfg = {"to_session": "resident-<host>-claude", "resident_host": ""}
    assert resident_target(cfg, ledger_host="iMac-3") == "resident-iMac-3-claude"           # 台帳の host が宛先
    assert resident_target({**cfg, "resident_host": "mini"}, "iMac-3") == "resident-mini-claude"  # config 明示が勝つ
    assert jump_link({"id": "c", "guild_id": None}, "m") == "https://discord.com/channels/@me/c/m"
    print("selftest OK (27 checks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, help="bridge config YAML (instance、 owner の private layer)")
    ap.add_argument("--state-dir", type=Path, default=None, help="override config state_dir")
    ap.add_argument("--dry", action="store_true", help="read Discord + board; write nothing anywhere (except heartbeat)")
    ap.add_argument("--backfill-minutes", type=int, default=0, help="on cursor init, also ingest posts from the last N minutes (default 0 = none)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--setup-webhooks", action="store_true", help="create persona webhooks for guild channels (needs Manage Webhooks) and save webhook_file")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.config:
        ap.error("--config is required (except --selftest)")
    if a.setup_webhooks:
        return setup_webhooks(a)
    return tick(a)


if __name__ == "__main__":
    sys.exit(main())
