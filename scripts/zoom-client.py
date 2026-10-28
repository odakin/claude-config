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
  notes <meeting_id> --date YYYY-MM-DD [--between HH:MM-HH:MM] [--out DIR] [--rec-start HH:MM:SS]
                                            その日の回の AI 要約と文字起こしを取り出す (読むだけ)
  scopes                                    token に付いている scope の一覧 (足した scope が効いたかを確かめる)
  joined --from YYYY-MM-DD --to YYYY-MM-DD [--tz]   自分の account で入った会議 (入室・退室・会議 id・主催)。
                                            直近 6 か月の月まで = 残すなら自分で写す (conventions/zoom-meetings.md#presence-from-process)
  selftest                                  通信しない部品の自己検査

文字起こし (VTT) は**参加者ごとの名前つき** = 話者を分けない録音の転写 (whisper 等) の帰属に使える。
  ⚠️ VTT の時刻は**会議の開始から** (ローカル録画の開始からではない)。 `--rec-start` に録画を始めた現地の時刻
  (Zoom の録画フォルダ名の時刻) を渡すと、 録画の時刻に直して話者ごとにまとめた `*_transcript-rec.txt`
  (`[h:mm:ss] 名前: 本文`、 録画より前は負の時刻) も書く。 Zoom の cue は実際の発話より 2〜3 秒遅れる (実測)。
  ⚠️ 話者の名前は参加者の表示名 = 実名が入る。 共有の場所に置く前に通称へ置き換える。

notes は「無い」 も根拠つきで言う: past meeting の `has_meeting_summary` (= 要約が作られたか) と
  transcript API の 3322 (= 文字起こしが存在しない)。 要約は録画と独立で、 部屋の
  `auto_start_meeting_summary` が false なら会議中に手で開始しない限り作られない。
  ⚠️ 要約の通知メールが来ていない ≠ 要約が無い、 の逆も同じ = 判断はこの 2 つの応答で行う。
  終了値: 0 = 要約か文字起こしを 1 つ以上取れた / 4 = 回はあるが両方とも無い (手元の録音を起こす合図) /
  5 = その日 (時間帯) の回が無い / 1 = API の失敗。 呼び元は 4 と 5 を「失敗」 と区別して分岐する。

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
    return token_response(cred)["access_token"]


def token_response(cred: dict) -> dict:
    """token の応答 (access_token と、 app に付いている scope の一覧 `scope`)。 scope を足した後に効いたかはこれで確かめる
    (app の Scopes の一覧に並んでいないと token に入らない、 実測 = conventions/zoom-meetings.md#presence-from-process)。"""
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
            return json.load(resp)
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


def report_time(s) -> dt.datetime | None:
    """report API の時刻 → UTC の datetime。 書式が混ざる (実測): join_time / leave_time = 'MM/DD/YYYY HH:MM' (分の精度)、
    start_time = 'YYYY-MM-DD HH:MM:SS'、 ほかの API は ISO の 'Z'。 どれも UTC。 読めなければ None。"""
    for fmt in ("%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(str(s), fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def month_chunks(d0: dt.date, d1: dt.date) -> list[tuple[dt.date, dt.date]]:
    """report API は 1 回の問い合わせが 1 か月まで = 暦の月ごとに区切る。"""
    out, a = [], d0
    while a <= d1:
        b = min(d1, (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
        out.append((a, b))
        a = b + dt.timedelta(days=1)
    return out


def joined(token: str, d0: dt.date, d1: dt.date) -> list[dict]:
    """自分の account で入った会議 (report の pastJoined) = [{join, leave (UTC の datetime), meeting_id, host: self|other, topic}]、 入室の順。
    scope `report:read:user:admin` が要る (無いと 4711)。 user に `me` は効かない (1001) = 自分の id を引いてから。
    問えるのは今月を含む直近 6 か月の月だけ (それより古い月は code 300)。 他人が主催した会議は題も開始時刻も返らないが、
    会議 id は主催者の案内の id と一致する (実測)。 同じ入室が 2 行返ることがある = 重複を除く。
    使い方と考え方の正本 = conventions/zoom-meetings.md#presence-from-process。"""
    uid = api(token, "GET", "/users/me")["id"]
    seen, out = set(), []
    for a, b in month_chunks(d0, d1):
        nxt = ""
        while True:
            q = f"/report/users/{uid}/meetings?from={a}&to={b}&type=pastJoined&page_size=300"
            r = api(token, "GET", q + (f"&next_page_token={urllib.parse.quote(nxt)}" if nxt else ""))
            for x in r.get("meetings", []):
                j, lv = report_time(x.get("join_time")), report_time(x.get("leave_time"))
                key = (x.get("id"), x.get("join_time"), x.get("leave_time"))
                if not j or not lv or key in seen:
                    continue
                seen.add(key)
                out.append({"join": j, "leave": lv, "meeting_id": str(x.get("id", "")),
                            "host": "self" if x.get("host_id") == uid else "other", "topic": x.get("topic") or ""})
            nxt = r.get("next_page_token") or ""
            if not nxt:
                break
    return sorted(out, key=lambda m: m["join"])


def cmd_joined(token: str, args) -> int:
    tz = ZoneInfo(args.tz)
    rows = joined(token, dt.date.fromisoformat(args.date_from), dt.date.fromisoformat(args.date_to))
    for m in rows:
        j, lv = m["join"].astimezone(tz), m["leave"].astimezone(tz)
        print(f"{j:%Y-%m-%d %H:%M}-{lv:%H:%M}  会議 id {m['meeting_id']}  主催 {'自分' if m['host'] == 'self' else '他人'}"
              f"  {m['topic'] or '(題なし = 他人の主催)'}")
    print(f"({len(rows)} 件、 {args.date_from}〜{args.date_to}、 時刻は {args.tz})")
    return 0


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


def in_window(start_time: str, tz: str, between: str | None) -> bool:
    """start_time (UTC) の現地の時刻が between ("HH:MM-HH:MM"、 両端を含む) に入るか。 None なら常に真。
    同じ部屋を 1 日に何度も使うとき (個人部屋で授業と打ち合わせ等)、 取り出す回を時間帯で絞る。"""
    if not between:
        return True
    lo, hi = between.split("-")
    t = dt.datetime.fromisoformat(start_time.replace("Z", "+00:00")).astimezone(ZoneInfo(tz)).strftime("%H:%M")
    return lo <= t <= hi


def _download(token: str, url: str) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def vtt_to_rec_lines(vtt: str, offset_s: float, merge_gap_s: float = 8.0) -> list[str]:
    """Zoom の VTT を `[h:mm:ss] 名前: 本文` の行にする。 時刻 = cue の開始 − offset_s (録画の開始からの秒)。
    同じ話者の cue が merge_gap_s 秒以内に続けば 1 行にまとめる。 名前の無い cue は名前を空にする。"""
    rows: list[list] = []
    for block in vtt.replace("\r\n", "\n").split("\n\n"):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        ts = next((i for i, ln in enumerate(lines) if " --> " in ln), None)
        if ts is None or ts + 1 >= len(lines):
            continue
        h, m, s = lines[ts].split(" --> ")[0].strip().split(":")
        t = int(h) * 3600 + int(m) * 60 + float(s) - offset_s
        text = " ".join(lines[ts + 1:]).strip()
        who, sep, body = text.partition(": ")
        if not sep:
            who, body = "", text
        if rows and rows[-1][1] == who and t - rows[-1][2] < merge_gap_s:
            rows[-1][3] += " " + body
            rows[-1][2] = t
        else:
            rows.append([t, who, t, body])

    def hms(t: float) -> str:
        sign, t = ("-" if t < 0 else ""), int(abs(t))
        return f"{sign}{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"
    return [f"[{hms(t)}] {who + ': ' if who else ''}{body}" for t, who, _, body in rows]


def rec_offset_s(meeting_start_utc: str, date: str, rec_start: str, tz: str) -> float:
    """会議の開始 (API の start_time、 UTC) から録画の開始 (現地の date + rec_start) までの秒。"""
    ms = dt.datetime.fromisoformat(meeting_start_utc.replace("Z", "+00:00"))
    rs = dt.datetime.fromisoformat(f"{date}T{rec_start}").replace(tzinfo=ZoneInfo(tz))
    return (rs - ms).total_seconds()


def cmd_notes(token: str, args) -> int:
    inst = api(token, "GET", f"/past_meetings/{args.meeting_id}/instances").get("meetings", [])
    hits = sorted((m for m in inst if local_date(m["start_time"], args.tz) == args.date
                   and in_window(m["start_time"], args.tz, args.between)),
                  key=lambda m: m["start_time"])
    if not hits:
        span = f" {args.between}" if args.between else ""
        print(f"{args.date}{span} に {args.meeting_id} の回は無い (過去の回 {len(inst)} 件を見た)")
        return 5
    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    found = 0
    for m in hits:
        up = uuid_path(m["uuid"])
        pm = api(token, "GET", f"/past_meetings/{up}")
        print(f"== {pm.get('topic')}  {pm.get('start_time')} 〜 {pm.get('end_time')}"
              f"  ({pm.get('duration')} 分, 参加 {pm.get('participants_count')})")
        stem = f"{args.date}_{m['start_time'][11:19].replace(':', '')}Z"
        if pm.get("has_meeting_summary"):
            summ = api(token, "GET", f"/meetings/{up}/meeting_summary")
            found += 1
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
        found += 1
        print(f"  文字起こし: あり{'' if url else ' (download_url 無し)'}")
        if url and out:
            vtt = _download(token, url)
            (out / f"{stem}_transcript.vtt").write_bytes(vtt)
            if args.rec_start:
                off = rec_offset_s(pm.get("start_time") or m["start_time"], args.date, args.rec_start, args.tz)
                (out / f"{stem}_transcript-rec.txt").write_text(
                    "\n".join(vtt_to_rec_lines(vtt.decode("utf-8"), off)) + "\n", encoding="utf-8")
                print(f"  録画の時刻に直した文字起こし: 会議の開始から {off:.0f} 秒ずらした")
    if out and found:
        print(f"保存先: {out}")
    return 0 if found else 4


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
    check(in_window("2030-01-02T05:00:00Z", "Asia/Tokyo", "13:30-15:00"), "時間帯の中 (東京 14:00)")
    check(not in_window("2030-01-02T01:00:00Z", "Asia/Tokyo", "13:30-15:00"), "時間帯の外 (東京 10:00)")
    check(in_window("2030-01-02T01:00:00Z", "Asia/Tokyo", None), "時間帯の指定なしは常に通す")
    vtt = ("WEBVTT\n\n00:09:58.000 --> 00:10:00.000\n話者 A: 始めます。\n\n"
           "00:10:05.000 --> 00:10:07.000\n話者 B: はい。\n\n00:10:08.000 --> 00:10:09.000\n話者 B: どうぞ。\n\n"
           "00:10:30.000 --> 00:10:31.000\n話者 B: 続き。\n\n00:10:40.000 --> 00:10:41.000\n名前の無い行\n")
    got = vtt_to_rec_lines(vtt, 600)
    check(got[0] == "[-0:00:02] 話者 A: 始めます。", "録画の前の cue は負の時刻")
    check(got[1] == "[0:00:05] 話者 B: はい。 どうぞ。", "同じ話者の近い cue は 1 行にまとめる")
    check(got[2] == "[0:00:30] 話者 B: 続き。", "間が空いた同じ話者は別の行")
    check(got[3] == "[0:00:40] 名前の無い行", "名前の無い cue は本文だけ")
    check(rec_offset_s("2030-01-02T11:00:00Z", "2030-01-02", "20:10:30", "Asia/Tokyo") == 630,
          "録画の開始 (東京 20:10:30) − 会議の開始 (UTC 11:00:00) = 630 秒")
    check(report_time("10/07/2030 04:16") == dt.datetime(2030, 10, 7, 4, 16, tzinfo=dt.timezone.utc), "report の join_time は UTC の MM/DD/YYYY HH:MM")
    check(report_time("2030-10-07 04:16:23") == dt.datetime(2030, 10, 7, 4, 16, 23, tzinfo=dt.timezone.utc), "report の start_time は UTC")
    check(report_time(None) is None and report_time("x") is None, "読めない時刻は None")
    check(month_chunks(dt.date(2030, 9, 29), dt.date(2030, 11, 3)) == [(dt.date(2030, 9, 29), dt.date(2030, 9, 30)),
          (dt.date(2030, 10, 1), dt.date(2030, 10, 31)), (dt.date(2030, 11, 1), dt.date(2030, 11, 3))], "問い合わせを暦の月で区切る")
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
    p_notes.add_argument("--between", help="開始時刻で絞る 'HH:MM-HH:MM' (--tz の現地時刻、 両端を含む)")
    p_notes.add_argument("--out", help="保存先 dir (無ければ要約の概要を画面に出すだけ)")
    p_notes.add_argument("--rec-start", help="録画を始めた現地の時刻 HH:MM:SS。 付けると文字起こしを録画の時刻に直した"
                         " *_transcript-rec.txt も書く (--out と一緒に)")

    sub.add_parser("scopes", help="token に付いている scope の一覧 (scope を足した後に効いたかを確かめる)")

    p_joined = sub.add_parser("joined", help="自分の account で入った会議の一覧 (report の pastJoined、 直近 6 か月の月まで)")
    p_joined.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p_joined.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p_joined.add_argument("--tz", default="Asia/Tokyo")

    sub.add_parser("selftest", help="通信しない部品の自己検査")

    args = ap.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    try:
        if args.cmd == "scopes":
            for s in sorted(token_response(load_cred(args.cred)).get("scope", "").split()):
                print(s)
            return 0
        token = get_token(load_cred(args.cred))
        return {
            "whoami": cmd_whoami,
            "show": cmd_show,
            "list": cmd_list,
            "create": cmd_create,
            "update": cmd_update,
            "delete": cmd_delete,
            "notes": cmd_notes,
            "joined": cmd_joined,
        }[args.cmd](token, args)
    except ZoomError as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
