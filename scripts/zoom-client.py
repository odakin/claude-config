#!/usr/bin/env python3
"""zoom-client.py — Zoom を **Server-to-Server OAuth で script から** 読む / 部屋を作る (画面 drive 不要)。

背景: Zoom は user 名義の常設 credential を出さないが、 account owner/admin は Marketplace で
**Server-to-Server OAuth app** を 1 つ作れる (= client_id / client_secret / account_id の 3 値)。
これだけで token を自己発行でき、 以後は部屋の作成も設定の読み取りも機械経路で回る。
一般則 = conventions/machine-route-first.md #route-ladder (= 画面 drive は最終手段)。
罠と手順の正本 = conventions/zoom-meetings.md (= S2S app の作り方 / use_pmi / passcode と待機室 /
365 日失効 / 録画と議事録の違い / 部屋の記録の仕方)。

subcommand:
  whoami                                    自分 (account / user / PMI) を表示 = 配線の死活確認
  show <meeting_id>                         ミーティング 1 件の設定を表示 (PMI 番号も可)
  list [--type scheduled|upcoming|previous_meetings]   自分のミーティング一覧
  create --topic T [--like <meeting_id>] [--apply]     部屋を作る (既定 dry-run)
  update <meeting_id> --set k=v [...] [--apply]        既存の部屋の settings を変える (既定 dry-run)
  delete <meeting_id> [--apply]             部屋を消す (既定 dry-run)
  notes <meeting_id> --date YYYY-MM-DD [--out DIR]    その日の回の AI 要約と文字起こしを取り出す (読むだけ)
  selftest                                  通信しない部品の自己検査

notes は「無い」 も根拠つきで言う: past meeting の `has_meeting_summary` (= 要約が作られたか) と
  transcript API の 3322 (= 文字起こしが存在しない)。 要約は録画と独立で、 部屋の
  `auto_start_meeting_summary` が false なら会議中に手で開始しない限り作られない。
  ⚠️ 要約の通知メールが来ていない ≠ 要約が無い、 の逆も同じ = 判断はこの 2 つの応答で行う。

create の既定 = **type 3 (定期ミーティング・固定時刻なし)** = 「いつでも入れる常設の部屋」。
  --like <id> を付けると、 その ミーティング (= PMI を渡すのが普通) の設定を写して作る。
  写すのは下の COPY_SETTINGS だけ (= 開催者側の運用設定)。 招待・録画先・代替ホストは写さない。

⚠️ 部屋の作成・削除は外部 service の account 変更 = **既定 dry-run**、 実行は `--apply`。
⚠️ 「固定時刻なし」 の定期ミーティングは **最終使用から 365 日で失効**する (PMI と違う点)。
⚠️ **create は必ず `use_pmi: false` を送る** (実測): アカウント設定
   「予定されたミーティングに個人ミーティング ID を使用」 が ON だと、 新しく作った部屋の
   join_url が **個人部屋のもの** (`/j/<PMI>?pwd=…&omn=<新 id>`) になり、 別の部屋を作ったつもりが
   PMI の別名でしかない、 という状態になる。 id が新しく発番されるので気づきにくい
   (= 見分け方は join_url の番号が PMI と同じか / `settings.use_pmi`)。
⚠️ Zoom は「パスコード」 と「待機室」 の**どちらかを必須**にする (実測): passcode なしで
   作ると `waiting_room` が **要求に関わらず true に上書きされる** (= ホストが毎回入室を承認する羽目になり、
   「いつでも入れる部屋」 が壊れる)。 ∴ create は既定で passcode を自動生成し join_url に埋める。

credential: JSON {"account_id": ..., "client_id": ..., "client_secret": ...}
  path = --cred <path> / env ZOOM_CRED / ~/.secrets/zoom-s2s-oauth.json の順。

Server-to-Server OAuth app の作り方 (= 本人が 1 回だけ、 5 分):
  1. https://marketplace.zoom.us/ にログイン → Develop → Build App → "Server-to-Server OAuth" → Create
  2. Information タブの必須欄 (Company Name / Developer Name / Developer Email) を埋める
  3. Scopes タブで付ける: meeting:read / meeting:write / user:read / user:read:settings の admin 版
     (新しい UI の粒度なら meeting:read:meeting:admin, meeting:write:meeting:admin,
      meeting:delete:meeting:admin, user:read:user:admin, user:read:settings:admin)
     update を使うなら meeting:update:meeting:admin も要る (実測: 無いと 4711 で止まる。 旧い手順の
      5 つには入っていなかった)
     notes を使うなら読み取りを足す: meeting:read:list_past_instances:admin,
      meeting:read:past_meeting:admin, meeting:read:summary:admin, meeting:read:list_summaries:admin,
      cloud_recording:read:meeting_transcript:admin (実測: 有効化済みの app なら、 足した直後に
      発行した token から効く = Activate し直す操作は要らなかった)
  4. Activation タブ → Activate
  5. App Credentials タブの Account ID / Client ID / Client Secret を credential JSON に書く
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

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
    "use_pmi",
    "auto_start_meeting_summary",
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
    # ⚠️ 必ず明示的に false (docstring の use_pmi 注意)。 写し元が PMI でも、 アカウント既定が
    #    ON でも、 「新しい部屋」 を作る以上 PMI の別名になってはいけない。
    settings["use_pmi"] = False
    for kv in args.set or []:
        k, _, v = kv.partition("=")
        settings[k.strip()] = _coerce(v.strip())
    payload = {
        "topic": args.topic,
        "type": TYPE_RECURRING_NO_FIXED,
        "timezone": args.timezone,
        "settings": settings,
    }
    if args.agenda:
        payload["agenda"] = args.agenda
    # ⚠️ passcode を付けないと Zoom が待機室を強制 ON にする (= 「ぶっ通し」 が壊れる)。
    #    既定で自動生成し、 join_url に ?pwd= が埋まる形にする。 --password "" で明示的に無しにできる。
    if args.password is None:
        payload["password"] = "".join(
            secrets.choice("abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8)
        )
    elif args.password:
        payload["password"] = args.password
    print("■ 作る部屋:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not args.apply:
        print("\n(dry-run — 実行するには --apply)")
        return 0
    created = api(token, "POST", "/users/me/meetings", payload)
    print("\n■ 作成しました:")
    _print_meeting(created)
    return 0


def _coerce(v: str):
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none") and v != "none":  # "none" は auto_recording の正当な値
        return None
    try:
        return int(v)
    except ValueError:
        return v


def cmd_update(token: str, args) -> int:
    before = api(token, "GET", f"/meetings/{args.meeting_id}")
    cur = before.get("settings") or {}
    changes = {}
    for kv in args.set:
        k, _, v = kv.partition("=")
        k, new = k.strip(), _coerce(v.strip())
        changes[k] = new
        print(f"  {k:28s} {cur.get(k)!r} → {new!r}")
    print(f"■ 対象: {before.get('topic')} (id={before.get('id')})")
    if not args.apply:
        print("(dry-run — 実行するには --apply)")
        return 0
    api(token, "PATCH", f"/meetings/{args.meeting_id}", {"settings": changes})
    print("\n■ 変更後:")
    _print_meeting(api(token, "GET", f"/meetings/{args.meeting_id}"))
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


def uuid_path(uuid: str) -> str:
    """past meeting の UUID を path に入れる形にする。 "/" で始まるか "//" を含む UUID は二重に
    percent-encode しないと Zoom が 404 を返す (API 仕様)。 それ以外は 1 回。"""
    once = urllib.parse.quote(uuid, safe="")
    return urllib.parse.quote(once, safe="") if (uuid.startswith("/") or "//" in uuid) else once


def local_date(start_time: str, tz: str) -> str:
    """API の start_time (UTC の ISO 文字列、 末尾 Z) を、 その地域の日付 YYYY-MM-DD にする。"""
    t = dt.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    return t.astimezone(ZoneInfo(tz)).date().isoformat()


def _download(token: str, url: str) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def cmd_notes(token: str, args) -> int:
    inst = api(token, "GET", f"/past_meetings/{args.meeting_id}/instances").get("meetings", [])
    hits = sorted((m for m in inst if local_date(m["start_time"], args.tz) == args.date),
                  key=lambda m: m["start_time"])
    if not hits:
        print(f"{args.date} に {args.meeting_id} の回は無い (過去の回 {len(inst)} 件を見た)")
        return 1
    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    for m in hits:
        up = uuid_path(m["uuid"])
        pm = api(token, "GET", f"/past_meetings/{up}")
        print(f"== {pm.get('topic')}  {pm.get('start_time')} 〜 {pm.get('end_time')}"
              f"  ({pm.get('duration')} 分, 参加 {pm.get('participants_count')})")
        stem = f"{args.date}_{m['start_time'][11:19].replace(':', '')}Z"
        if pm.get("has_meeting_summary"):
            summ = api(token, "GET", f"/meetings/{up}/meeting_summary")
            print("  要約     : あり")
            if out:
                (out / f"{stem}_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1))
            else:
                print(summ.get("summary_overview") or summ.get("summary_content") or "")
        else:
            print("  要約     : 無い (has_meeting_summary=false = この回では AI 要約が作られていない)")
        try:
            tr = api(token, "GET", f"/meetings/{up}/transcript")
        except ZoomError as exc:
            if "3322" not in str(exc):
                raise
            print("  文字起こし: 無い (3322 = この回の文字起こしは存在しない)")
            continue
        url = tr.get("download_url")
        print(f"  文字起こし: あり{'' if url else ' (download_url 無し)'}")
        if url and out:
            (out / f"{stem}_transcript.vtt").write_bytes(_download(token, url))
    if out:
        print(f"保存先: {out}")
    return 0


def selftest() -> int:
    fails = []

    def check(cond, name):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    check(uuid_path("AbCdEfGhIjKlMnOpQrSt==") == "AbCdEfGhIjKlMnOpQrSt%3D%3D", "普通の UUID は 1 回 encode")
    check(uuid_path("/AbCdEfGhIjKlMnOpQrS==") == "%252FAbCdEfGhIjKlMnOpQrS%253D%253D", "/ で始まる UUID は二重に encode")
    check(uuid_path("Ab//Cd==") == "Ab%252F%252FCd%253D%253D", "// を含む UUID は二重に encode")
    check(local_date("2030-01-02T03:04:05Z", "Asia/Tokyo") == "2030-01-02", "UTC の朝は東京の同じ日")
    check(local_date("2030-01-02T16:30:00Z", "Asia/Tokyo") == "2030-01-03", "UTC の夕方以降は東京の翌日")
    print("zoom-client selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


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
    p_create.add_argument("--set", action="append", help="settings を上書き (k=v、 複数可)")
    p_create.add_argument("--password", help="passcode (既定 = 自動生成。 空文字で無し = 待機室が強制 ON になる)")
    p_create.add_argument("--apply", action="store_true", help="実際に作る")

    p_up = sub.add_parser("update", help="既存の部屋の settings を変える (既定 dry-run)")
    p_up.add_argument("meeting_id")
    p_up.add_argument("--set", action="append", required=True, help="k=v (複数可)")
    p_up.add_argument("--apply", action="store_true")

    p_del = sub.add_parser("delete", help="部屋を消す (既定 dry-run)")
    p_del.add_argument("meeting_id")
    p_del.add_argument("--apply", action="store_true")

    p_notes = sub.add_parser("notes", help="その日の回の AI 要約と文字起こしを取り出す (読むだけ)")
    p_notes.add_argument("meeting_id", help="ミーティング番号 (PMI も可)")
    p_notes.add_argument("--date", required=True, help="回の日付 YYYY-MM-DD (--tz の地域の日付)")
    p_notes.add_argument("--tz", default="Asia/Tokyo")
    p_notes.add_argument("--out", help="保存先 dir (無ければ要約の概要を画面に出すだけ)")

    sub.add_parser("selftest", help="通信しない部品の自己検査")

    args = ap.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    try:
        token = get_token(load_cred(args.cred))
        return {
            "whoami": cmd_whoami,
            "show": cmd_show,
            "list": cmd_list,
            "create": cmd_create,
            "update": cmd_update,
            "delete": cmd_delete,
            "notes": cmd_notes,
        }[args.cmd](token, args)
    except ZoomError as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
