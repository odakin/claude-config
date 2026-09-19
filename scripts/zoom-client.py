#!/usr/bin/env python3
"""zoom-client.py — Zoom を **Server-to-Server OAuth で script から** 読む / 部屋を作る (画面 drive 不要)。

背景: Zoom は user 名義の常設 credential を出さないが、 account owner/admin は Marketplace で
**Server-to-Server OAuth app** を 1 つ作れる (= client_id / client_secret / account_id の 3 値)。
これだけで token を自己発行でき、 以後は部屋の作成も設定の読み取りも機械経路で回る。
一般則 = conventions/machine-route-first.md #route-ladder (= 画面 drive は最終手段)。

subcommand:
  whoami                                    自分 (account / user / PMI) を表示 = 配線の死活確認
  show <meeting_id>                         ミーティング 1 件の設定を表示 (PMI 番号も可)
  list [--type scheduled|upcoming|previous_meetings]   自分のミーティング一覧
  create --topic T [--like <meeting_id>] [--apply]     部屋を作る (既定 dry-run)
  delete <meeting_id> [--apply]             部屋を消す (既定 dry-run)

create の既定 = **type 3 (定期ミーティング・固定時刻なし)** = 「いつでも入れる常設の部屋」。
  --like <id> を付けると、 その ミーティング (= PMI を渡すのが普通) の設定を写して作る。
  写すのは下の COPY_SETTINGS だけ (= 開催者側の運用設定)。 招待・録画先・代替ホストは写さない。

⚠️ 部屋の作成・削除は外部 service の account 変更 = **既定 dry-run**、 実行は `--apply`。
⚠️ 「固定時刻なし」 の定期ミーティングは **最終使用から 365 日で失効**する (PMI と違う点)。
⚠️ Zoom は「パスコード」 と「待機室」 の**どちらかを必須**にする。 waiting_room=false で作ると
   パスコードが付く (join_url に埋め込まれる) — これは Zoom 側の強制で、 本 script は外さない。

credential: JSON {"account_id": ..., "client_id": ..., "client_secret": ...}
  path = --cred <path> / env ZOOM_CRED / ~/.secrets/zoom-s2s-oauth.json の順。

Server-to-Server OAuth app の作り方 (= 本人が 1 回だけ、 5 分):
  1. https://marketplace.zoom.us/ にログイン → Develop → Build App → "Server-to-Server OAuth" → Create
  2. Information タブの必須欄 (Company Name / Developer Name / Developer Email) を埋める
  3. Scopes タブで付ける: meeting:read / meeting:write / user:read / user:read:settings の admin 版
     (新しい UI の粒度なら meeting:read:meeting:admin, meeting:write:meeting:admin,
      meeting:delete:meeting:admin, user:read:user:admin, user:read:settings:admin)
  4. Activation タブ → Activate
  5. App Credentials タブの Account ID / Client ID / Client Secret を credential JSON に書く
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://zoom.us/oauth/token"
API = "https://api.zoom.us/v2"

# --like で写す設定 (= 開催者側の運用。 招待・録画先・代替ホスト等の「その部屋固有」 は写さない)
COPY_SETTINGS = (
    "host_video",
    "participant_video",
    "join_before_host",
    "jbh_time",
    "mute_upon_entry",
    "waiting_room",
    "audio",
    "auto_recording",
    "approval_type",
    "meeting_authentication",
    "allow_multiple_devices",
    "encryption_type",
    "show_share_button",
    "private_meeting",
)

TYPE_RECURRING_NO_FIXED = 3


class ZoomError(RuntimeError):
    pass


def load_cred(path: str | None) -> dict:
    cand = path or os.environ.get("ZOOM_CRED") or os.path.expanduser("~/.secrets/zoom-s2s-oauth.json")
    if not os.path.exists(cand):
        raise ZoomError(
            f"credential がありません: {cand}\n"
            "Server-to-Server OAuth app を 1 回作って 3 値を書いてください (作り方 = この script の冒頭)。"
        )
    with open(cand, encoding="utf-8") as fh:
        cred = json.load(fh)
    missing = [k for k in ("account_id", "client_id", "client_secret") if not cred.get(k)]
    if missing:
        raise ZoomError(f"{cand} に {', '.join(missing)} がありません")
    return cred


def get_token(cred: dict) -> str:
    body = urllib.parse.urlencode(
        {"grant_type": "account_credentials", "account_id": cred["account_id"]}
    ).encode()
    basic = base64.b64encode(f"{cred['client_id']}:{cred['client_secret']}".encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)["access_token"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ZoomError(f"token 取得に失敗 ({exc.code}): {detail}") from exc


def api(token: str, method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ZoomError(f"{method} {path} が失敗 ({exc.code}): {detail}") from exc


def cmd_whoami(token: str, args) -> int:
    me = api(token, "GET", "/users/me")
    print(f"user      : {me.get('first_name','')} {me.get('last_name','')} <{me.get('email')}>")
    print(f"account_id: {me.get('account_id')}")
    print(f"type      : {me.get('type')}  (1=Basic 2=Licensed 3=On-prem)")
    print(f"PMI       : {me.get('pmi')}")
    print(f"個人部屋   : {me.get('personal_meeting_url')}")
    return 0


def _print_meeting(m: dict) -> None:
    print(f"topic    : {m.get('topic')}")
    print(f"id       : {m.get('id')}")
    print(f"type     : {m.get('type')}  (2=単発 3=定期/固定時刻なし 4=PMI 8=定期/固定時刻あり)")
    print(f"join_url : {m.get('join_url')}")
    s = m.get("settings") or {}
    print("settings :")
    for k in COPY_SETTINGS:
        if k in s:
            print(f"  {k:24s} = {s[k]}")


def cmd_show(token: str, args) -> int:
    _print_meeting(api(token, "GET", f"/meetings/{args.meeting_id}"))
    return 0


def cmd_list(token: str, args) -> int:
    res = api(token, "GET", f"/users/me/meetings?type={args.type}&page_size=100")
    for m in res.get("meetings", []):
        print(f"{m.get('id')}  type={m.get('type')}  {m.get('topic')}")
    return 0


def cmd_create(token: str, args) -> int:
    settings: dict = {}
    if args.like:
        src = api(token, "GET", f"/meetings/{args.like}")
        src_settings = src.get("settings") or {}
        settings = {k: src_settings[k] for k in COPY_SETTINGS if k in src_settings}
        print(f"■ 設定の写し元: {src.get('topic')} (id={src.get('id')}, type={src.get('type')})")
    payload = {
        "topic": args.topic,
        "type": TYPE_RECURRING_NO_FIXED,
        "timezone": args.timezone,
        "settings": settings,
    }
    if args.agenda:
        payload["agenda"] = args.agenda
    print("■ 作る部屋:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not args.apply:
        print("\n(dry-run — 実行するには --apply)")
        return 0
    created = api(token, "POST", "/users/me/meetings", payload)
    print("\n■ 作成しました:")
    _print_meeting(created)
    return 0


def cmd_delete(token: str, args) -> int:
    m = api(token, "GET", f"/meetings/{args.meeting_id}")
    print(f"■ 消す対象: {m.get('topic')} (id={m.get('id')}, type={m.get('type')})")
    if not args.apply:
        print("(dry-run — 実行するには --apply)")
        return 0
    api(token, "DELETE", f"/meetings/{args.meeting_id}")
    print("削除しました。")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Zoom を Server-to-Server OAuth で読む / 部屋を作る")
    ap.add_argument("--cred", help="credential JSON の path (既定 env ZOOM_CRED → ~/.secrets/zoom-s2s-oauth.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="自分と PMI を表示 (= 配線の死活確認)")

    p_show = sub.add_parser("show", help="ミーティング 1 件の設定を表示 (PMI 番号も可)")
    p_show.add_argument("meeting_id")

    p_list = sub.add_parser("list", help="自分のミーティング一覧")
    p_list.add_argument("--type", default="scheduled")

    p_create = sub.add_parser("create", help="常設の部屋を作る (既定 dry-run)")
    p_create.add_argument("--topic", required=True)
    p_create.add_argument("--like", help="設定を写す元のミーティング id (PMI を渡すのが普通)")
    p_create.add_argument("--agenda")
    p_create.add_argument("--timezone", default="Asia/Tokyo")
    p_create.add_argument("--apply", action="store_true", help="実際に作る")

    p_del = sub.add_parser("delete", help="部屋を消す (既定 dry-run)")
    p_del.add_argument("meeting_id")
    p_del.add_argument("--apply", action="store_true")

    args = ap.parse_args(argv)
    try:
        token = get_token(load_cred(args.cred))
        return {
            "whoami": cmd_whoami,
            "show": cmd_show,
            "list": cmd_list,
            "create": cmd_create,
            "delete": cmd_delete,
        }[args.cmd](token, args)
    except ZoomError as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
