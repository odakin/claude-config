#!/usr/bin/env python3
"""macos-notification-db.py — macOS 通知センターの DB から、ある app が出した通知 (題・副題・本文・時刻) を読む。

何のためか
    API を持たないアプリ (メッセンジャー・業務アプリ) でも、 macOS の通知として届いた内容は
    通知センターの SQLite DB (`~/Library/Group Containers/group.com.apple.usernoted/db2/db`) に残る。
    本 script はその DB を**写しを取ってから**読み、 指定 app の通知を時刻順に並べる。 読むだけ。
    「読む側の機械経路が無いアプリ」 を段 4 (自作経路) に降ろすための engine
    (一般則 = conventions/machine-route-first.md#route-ladder、 手順と限界 = conventions/macos-notification-db.md)。

機構と限界 (= 出力の読み方に効く)
    - その app が**起動していた間**に表示された通知しか無い。 通知センターで消した通知は DB からも消える。
    - 本文は通知に載った長さで切れる。 app 側の「内容を表示しない」 設定だと本文が定型文になる。
    - DB は TCC (フルディスクアクセス) の下。 読めないときは **exit 3** + 1 行 (= 検査が走っていない合図、
      違反 / 該当ありの 1 と同じ値にしない = docs/convention-design-principles.md#failure-exit-equals-violation-exit)。
      付与の対象 = この script を起動した側の app (Terminal / Claude desktop / launchd なら applet =
      conventions/launchd-cloudstorage-tcc.md の A' pattern)。
    - schema (公開されている解析記事の形。 **本 script の作者はまだ実機の DB で確かめていない** = 初回は
      `--list-apps` で表と件数が出るかを見る): 表 `app` (app_id, identifier) と `record` (app_id, uuid,
      data = binary plist, delivered_date / request_date = 2001-01-01 起算の秒)。 `data['req']` に titl / subt / body。
      macOS の版で変わりうる。 形が違う record は 1 件だけ落として続ける (全体を落とさない)。

使い方
    python3 macos-notification-db.py --list-apps                 # DB に居る app と件数 (最初にこれ)
    python3 macos-notification-db.py --app <bundle id>           # その app の通知、 新しい順
    python3 macos-notification-db.py --app <bundle id> --since 48h --json
    python3 macos-notification-db.py --selftest                  # 合成 DB で parse / filter / 不在→3 を検査 (TCC 不要)

import 面 (層3 の shim が使う): snapshot_db(src) / load_records(db, bundle) / cocoa_to_dt / parse_since /
    probe_db(src) -> (present, reason) / DB_PATH / COCOA_EPOCH。 CLI の exit: 0 = 読めた / 3 = 読めない / 2 = 引数。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

DB_PATH = Path.home() / "Library/Group Containers/group.com.apple.usernoted/db2/db"
COCOA_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
FDA_HINT = ("システム設定 › プライバシーとセキュリティ › フルディスクアクセス に、 この script を起動した app "
            "(Terminal / Claude desktop / launchd の applet) を追加")


def cocoa_to_dt(sec: float | None) -> dt.datetime | None:
    if sec is None:
        return None
    try:
        return (COCOA_EPOCH + dt.timedelta(seconds=float(sec))).astimezone()
    except (OverflowError, ValueError):
        return None


def parse_since(s: str) -> dt.timedelta:
    m = re.fullmatch(r"(\d+)([hd])", s.strip())
    if not m:
        raise argparse.ArgumentTypeError("--since は 48h / 7d の形")
    n, unit = int(m.group(1)), m.group(2)
    return dt.timedelta(hours=n) if unit == "h" else dt.timedelta(days=n)


def probe_db(src: Path) -> tuple[bool, str]:
    """(present, reason)。 Path.exists() は EPERM を False に畳むので、 listdir の例外で
    「無い」 と「読めない (TCC)」 を区別する。 reason は present=False のときの 1 行。"""
    try:
        present = src.name in os.listdir(src.parent)
    except PermissionError:
        return False, f"通知 DB の dir が読めない (フルディスクアクセス未付与) — {FDA_HINT}"
    except FileNotFoundError:
        return False, f"通知 DB が無い ({src}) — macOS の版で場所が違う可能性"
    if not present:
        return False, f"通知 DB が無い ({src}) — macOS の版で場所が違う可能性"
    return True, ""


def snapshot_db(src: Path) -> Path:
    """DB + WAL + SHM を一時 dir に写す (= 本物を lock しない・WAL の未 checkpoint 分も読む)。
    TCC で読めない → PermissionError (呼び元が exit 3)。 呼び元は使い終わったら親 dir を消す。"""
    tmp = Path(tempfile.mkdtemp(prefix="notif-db-"))
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(src) + suffix)
        if p.exists():
            shutil.copy2(p, tmp / ("db" + suffix))
    return tmp / "db"


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None


def load_records(db: Path, bundle: str | None):
    """(records 新しい順, {app_id: identifier})。 bundle=None で全 app。"""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    apps = {r["app_id"]: r["identifier"] for r in con.execute("SELECT app_id, identifier FROM app")}
    rows = con.execute(
        "SELECT rec_id, app_id, uuid, data, delivered_date, request_date, presented FROM record"
    ).fetchall()
    out = []
    for r in rows:
        ident = apps.get(r["app_id"], "?")
        if bundle and ident != bundle:
            continue
        title = subtitle = body = None
        when = cocoa_to_dt(r["delivered_date"] or r["request_date"])
        try:
            pl = plistlib.loads(r["data"]) if r["data"] else {}
            req = pl.get("req", pl) if isinstance(pl, dict) else {}
            title = _first(req, "titl", "title")
            subtitle = _first(req, "subt", "subtitle")
            body = _first(req, "body")
            if when is None and isinstance(pl, dict):
                when = cocoa_to_dt(pl.get("date"))
        except Exception:  # noqa: BLE001 — plist の形が違っても 1 件で全体を落とさない
            pass
        uuid = r["uuid"]
        if isinstance(uuid, (bytes, bytearray)):
            uuid = uuid.hex()
        out.append(dict(uuid=str(uuid), app=ident, when=when, title=title, subtitle=subtitle,
                        body=body, presented=bool(r["presented"])))
    con.close()
    out.sort(key=lambda x: x["when"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return out, apps


def read(src: Path, bundle: str | None):
    """probe → snapshot → load を 1 つに。 戻り = (rc, records, apps, reason)。 rc 3 = 読めない。"""
    present, reason = probe_db(src)
    if not present:
        return 3, [], {}, reason
    try:
        db = snapshot_db(src)
    except PermissionError:
        return 3, [], {}, f"通知 DB が読めない (フルディスクアクセス未付与) — {FDA_HINT}"
    try:
        recs, apps = load_records(db, bundle)
    except sqlite3.DatabaseError as e:
        return 3, [], {}, f"DB を開けない ({e})"
    finally:
        shutil.rmtree(db.parent, ignore_errors=True)
    return 0, recs, apps, ""


def fmt(rec: dict, marker: str = "🔔") -> str:
    t = rec["when"].strftime("%m/%d %H:%M") if rec["when"] else "??/?? ??:??"
    who = rec["title"] or "(題なし)"
    if rec["subtitle"]:
        who += f" › {rec['subtitle']}"
    body = (rec["body"] or "(本文なし)").replace("\n", " ⏎ ")
    return f"{marker} {t} {who}: {body}"


def to_jsonable(recs):
    return [{**r, "when": r["when"].isoformat() if r["when"] else None} for r in recs]


def make_fake_db(dir_: Path, entries) -> Path:
    """selftest と層3 shim の test 用: entries = [(bundle, title, body, age_sec), ...] から合成 DB を作る。"""
    db = dir_ / "db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE app (app_id INTEGER PRIMARY KEY, identifier VARCHAR);"
        "CREATE TABLE record (rec_id INTEGER PRIMARY KEY, app_id INTEGER, uuid BLOB, data BLOB,"
        " request_date REAL, request_last_date REAL, delivered_date REAL, presented INTEGER, style INTEGER);"
    )
    app_ids: dict[str, int] = {}
    now = (dt.datetime.now(dt.timezone.utc) - COCOA_EPOCH).total_seconds()
    for i, (bundle, title, body, age) in enumerate(entries, 1):
        if bundle not in app_ids:
            app_ids[bundle] = len(app_ids) + 1
            con.execute("INSERT INTO app VALUES (?, ?)", (app_ids[bundle], bundle))
        blob = plistlib.dumps({"app": bundle, "req": {"titl": title, "body": body, "iden": f"i{i}"}})
        con.execute("INSERT INTO record VALUES (?, ?, ?, ?, ?, NULL, ?, 1, 0)",
                    (i, app_ids[bundle], bytes([i]), blob, now - age, now - age))
    con.commit()
    con.close()
    return db


def selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="notif-db-selftest-"))
    try:
        db = make_fake_db(tmp, [("com.example.chat", "Alice", "hello", 10),
                                ("com.apple.mail", "Mail", "x", 20),
                                ("com.example.chat", "Bob", "older", 3600 * 50)])
        rc, recs, apps, _ = read(db, "com.example.chat")
        assert rc == 0 and len(recs) == 2 and recs[0]["title"] == "Alice", (rc, recs)
        assert len(apps) == 2
        rc, recs, _, _ = read(db, None)
        assert rc == 0 and len(recs) == 3
        recent = [r for r in recs if dt.datetime.now(dt.timezone.utc) - r["when"] <= parse_since("48h")]
        assert len(recent) == 2, recent
        rc, _, _, reason = read(tmp / "nope" / "db", None)
        assert rc == 3 and "無い" in reason, (rc, reason)
        assert fmt(recs[0]).startswith("🔔 ")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest OK (parse / filter / since / 不在→3)")
    return 0


def main(argv=None) -> int:
    if argv is None and "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--app", default=None, help="bundle id (省略 = 全 app)")
    ap.add_argument("--since", type=parse_since, default=None, help="直近 N h / N d だけ")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-apps", action="store_true", help="DB に居る app と件数")
    ap.add_argument("--db", default=str(DB_PATH), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    rc, recs, apps, reason = read(Path(a.db), None if a.list_apps else a.app)
    if rc:
        print(f"⚠️ 通知 DB: {reason}", file=sys.stderr)
        return rc
    if a.list_apps:
        counts: dict[str, int] = {}
        for r in recs:
            counts[r["app"]] = counts.get(r["app"], 0) + 1
        for ident, n in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"{n:5d}  {ident}")
        if not counts:
            print("(通知 0 件)")
        return 0
    if a.since:
        now = dt.datetime.now(dt.timezone.utc)
        recs = [r for r in recs if r["when"] and now - r["when"] <= a.since]
    if a.json:
        print(json.dumps(to_jsonable(recs), ensure_ascii=False, indent=1))
    else:
        for r in recs:
            print(fmt(r))
        if not recs:
            print("通知 0 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
