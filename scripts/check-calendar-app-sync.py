#!/usr/bin/env python3
"""check-calendar-app-sync.py — Mac の Calendar.app が各アカウントと同期できているかを **この機械で** 見る。

なぜ要るか (= 既存の網の穴):
  API / MCP で Google Calendar に書いた予定は、 user が Mac の Calendar.app で見て、 Calendar.app が通知を鳴らす。
  Calendar.app 側のアカウントが認証切れになると、 同期は試行のたびに即失敗し、 **予定も通知も届かないまま
  どこにもエラーが出ない** (実測: 移行した機械で Google アカウントの一部だけが未認証になり、 API の書き込みは
  成功と返り続けた)。 書き込み側の成功は「user の画面に出た」 ではないので、 画面の側を機械で見る。
  切り分けの手順と読み方の正本 = conventions/macos-calendar-write.md #google-to-calendar-app-sync-check

見るもの (全部 read-only、 `mode=ro` で開く):
  1. Calendar.app の DB (macOS 26 = ~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb、 13 = ~/Library/Calendars/Calendar.sqlitedb) の Store 表
     = アカウントごとの最後の同期の試行 (last_sync_start / last_sync_end、 2001-01-01 起点の秒) と error_id
  2. インターネットアカウントの DB (~/Library/Accounts/Accounts4.sqlite)
     = Store.external_id が CalDAV の子アカウントの ZIDENTIFIER、 その ZPARENTACCOUNT (Google 等) の ZAUTHENTICATED
     (⚠️ 子の CalDAV アカウントは親が未認証でも 1 のまま = 親を見ないと切れが見えない)

判定 (= 状態を畳まない):
  unauth    親アカウントが未認証 (ZAUTHENTICATED=0)。 同期は来ない。 直す = 再サインイン (パスワード = user の操作)
  error     認証は有効だが最後の同期が error。 一時的な失敗もありうる (次の試行で消えることがある)
  offline   同期するアカウント全部が error = ネットワーク断の可能性が高いので 1 行に畳む
  unknown   DB を開けない (権限 / 無い)。 **ok に畳まない** (= 「測れなかった」 と「健全」 を分ける)
  ok        上のどれでもない

usage:
  check-calendar-app-sync.py [--surface] [--json] [--selftest]
    --surface  finding があるときだけ surface 用の見出しつきで出す (無ければ完全沈黙)
    --json     機械可読 (全アカウント)
    (flag なし) 全アカウントの表を出す
  macOS 以外では何もしない。 path の差し替え = env CALSYNC_CALENDAR_DB / CALSYNC_ACCOUNTS_DB (test 用)。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

APPLE_EPOCH = 978307200  # 2001-01-01T00:00:00Z の Unix 時刻

FIX = {
    "unauth": ("🔴", "インターネットアカウントで未認証 = Calendar.app に予定も通知も届かない",
               "システム設定 → インターネットアカウント → このアカウント → 再サインイン "
               "(パスワード = user の操作。 Calendar.app ツールバーの ⚠ からも入れる)"),
    "error": ("🟠", "認証は有効だが最後の同期が error",
              "次の同期で消えなければ Calendar.app ツールバーの ⚠ で内容を見る"),
}


def _present(p: Path) -> bool:
    """在るか。 TCC で stat 自体を拒まれたら「在るが読めない」 = True (= 読めない理由は後段が出す)。"""
    try:
        return p.exists()
    except PermissionError:
        return True


def _default_calendar_db(home: Path) -> Path:
    """Calendar.app の DB の置き場所は macOS の版で違う (実測: 26 = group container / 13 = ~/Library/Calendars)。
    在る方を返し、 どちらも無ければ新しい方 (= 不在の理由がその path で出る)。"""
    new = home / "Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb"
    old = home / "Library/Calendars/Calendar.sqlitedb"
    for p in (new, old):
        if _present(p):
            return p
    return new


def _paths() -> tuple[Path, Path]:
    home = Path.home()
    cal = os.environ.get("CALSYNC_CALENDAR_DB") or str(_default_calendar_db(home))
    acc = os.environ.get("CALSYNC_ACCOUNTS_DB") or str(home / "Library/Accounts/Accounts4.sqlite")
    return Path(cal), Path(acc)


def _ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def _clock(t) -> str:
    if t is None:
        return "—"
    return _dt.datetime.fromtimestamp(float(t) + APPLE_EPOCH).strftime("%m/%d %H:%M")


def read_stores(cal_db: Path) -> list[dict]:
    """同期の試行記録を持つ有効な Store (= Calendar.app のアカウント)。"""
    with _ro(cal_db) as con:
        rows = con.execute(
            "select ROWID, name, external_id, error_id, last_sync_start, last_sync_end "
            "from Store where last_sync_start is not null and coalesce(disabled,0)=0 "
            "and external_id is not null and external_id != ''").fetchall()
    out = []
    for rid, name, ext, err, s0, s1 in rows:
        dur = None if (s0 is None or s1 is None) else round(float(s1) - float(s0), 3)
        if dur is not None and dur < 0:
            dur = "同期中"  # 試行が始まって終わりがまだ = last_sync_end は前回の試行のもの
        out.append({"store": name, "external_id": ext, "error": int(err or 0),
                    "last_sync": _clock(s0), "duration_s": dur})
    return out


def read_parents(acc_db: Path, ext_ids: list[str]) -> dict[str, dict]:
    """external_id (CalDAV 子の ZIDENTIFIER) → 親アカウントの {username, kind, authenticated}。"""
    if not ext_ids:
        return {}
    q = ("select c.ZIDENTIFIER, coalesce(p.ZUSERNAME, c.ZUSERNAME), "
         "coalesce(pt.ZIDENTIFIER, ct.ZIDENTIFIER), coalesce(p.ZAUTHENTICATED, c.ZAUTHENTICATED) "
         "from ZACCOUNT c left join ZACCOUNTTYPE ct on c.ZACCOUNTTYPE=ct.Z_PK "
         "left join ZACCOUNT p on c.ZPARENTACCOUNT=p.Z_PK "
         "left join ZACCOUNTTYPE pt on p.ZACCOUNTTYPE=pt.Z_PK "
         f"where c.ZIDENTIFIER in ({','.join('?' * len(ext_ids))})")
    with _ro(acc_db) as con:
        rows = con.execute(q, ext_ids).fetchall()
    return {ext: {"username": user or "", "kind": (kind or "").replace("com.apple.account.", ""),
                  "authenticated": None if auth is None else int(auth)}
            for ext, user, kind, auth in rows}


def classify(stores: list[dict], parents: dict[str, dict] | None) -> list[dict]:
    rows = []
    for s in stores:
        p = (parents or {}).get(s["external_id"], {})
        r = {**s, "username": p.get("username", ""), "kind": p.get("kind", ""),
             "authenticated": p.get("authenticated")}
        if r["authenticated"] == 0:
            r["status"] = "unauth"
        elif r["error"]:
            r["status"] = "error"
        else:
            r["status"] = "ok"
        rows.append(r)
    # 同期するアカウントが全部 error で、 認証切れが 1 つも無い = ネットワーク断の顔 (1 行に畳む)
    if len(rows) >= 2 and all(r["status"] == "error" for r in rows):
        for r in rows:
            r["status"] = "offline"
    return rows


def collect() -> tuple[list[dict], str | None]:
    """(rows, unknown_reason)。 Calendar の DB が読めなければ unknown。 Accounts だけ読めなければ認証軸を欠いて続ける。"""
    cal_db, acc_db = _paths()
    try:
        stores = read_stores(cal_db)
    except Exception as e:  # noqa: BLE001 — 権限 / 無い / 形式違い を全部「測れなかった」 に寄せる
        return [], f"Calendar.app の DB を読めない ({type(e).__name__}: {e})"
    try:
        parents = read_parents(acc_db, [s["external_id"] for s in stores])
    except Exception as e:  # noqa: BLE001
        rows = classify(stores, None)
        return rows, f"インターネットアカウントの DB を読めない = 認証切れは見えていない ({type(e).__name__})"
    return classify(stores, parents), None


def _dur(r: dict) -> str:
    d = r["duration_s"]
    return d if isinstance(d, str) else f"所要 {d} 秒"


def render(rows: list[dict], unknown: str | None, surface: bool) -> str:
    bad = [r for r in rows if r["status"] in ("unauth", "error")]
    offline = [r for r in rows if r["status"] == "offline"]
    if surface and not bad and not offline and not unknown:
        return ""
    lines = []
    if surface:
        lines.append("# 📅 Calendar.app の同期 (この機械)")
    if not surface:
        for r in rows:
            auth = {1: "認証 ✓", 0: "未認証", None: "認証 ?"}[r["authenticated"]]
            lines.append(f"  {r['status']:7} {r['store']} ({r['username'] or '?'}, {r['kind'] or '?'}) "
                         f"{auth} / 最後の同期 {r['last_sync']} error={r['error']} {_dur(r)}")
    for r in bad:
        mark, what, fix = FIX[r["status"]]
        who = f"{r['store']} ({r['username']})" if r["username"] and r["username"] != r["store"] else r["store"]
        lines.append(f"  {mark} {who}: {what} — 最後の同期 {r['last_sync']}、 {_dur(r)}")
        lines.append(f"     直す = {fix}")
    if offline:
        lines.append(f"  ⚪ 同期するアカウント {len(offline)} つが全部 error = ネットワーク断の可能性 "
                     "(つながった後も続くなら flag なしで表を見る)")
    if unknown:
        lines.append(f"  ⚪ 未チェック: {unknown} (= 健全とは限らない。 呼び元 process の権限を確かめる)")
    if surface and bad:
        lines.append("     ⚠️ API / MCP の書き込みは成功と返るので、 ここ以外にエラーは出ない "
                     "(切り分けの正本 = claude-config conventions/macos-calendar-write.md #google-to-calendar-app-sync-check)")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surface", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if sys.platform != "darwin" and not os.environ.get("CALSYNC_CALENDAR_DB"):
        return 0
    rows, unknown = collect()
    if a.json:
        print(json.dumps({"accounts": rows, "unknown": unknown}, ensure_ascii=False, indent=2))
        return 0
    out = render(rows, unknown, a.surface)
    if out:
        print(out)
    return 0


# ---------------------------------------------------------------- selftest
def _mk_calendar(path: Path, stores: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.execute("create table Store (ROWID integer primary key, name text, external_id text, "
                "disabled integer, error_id integer, last_sync_start real, last_sync_end real)")
    con.executemany("insert into Store (ROWID,name,external_id,disabled,error_id,last_sync_start,last_sync_end) "
                    "values (?,?,?,?,?,?,?)", stores)
    con.commit()
    con.close()


def _mk_accounts(path: Path, accounts: list[tuple]) -> None:
    """accounts = (pk, identifier, username, type_identifier, authenticated, parent_pk)。"""
    con = sqlite3.connect(path)
    con.execute("create table ZACCOUNTTYPE (Z_PK integer primary key, ZIDENTIFIER text)")
    con.execute("create table ZACCOUNT (Z_PK integer primary key, ZIDENTIFIER text, ZUSERNAME text, "
                "ZACCOUNTTYPE integer, ZAUTHENTICATED integer, ZPARENTACCOUNT integer)")
    types = sorted({a[3] for a in accounts})
    tid = {t: i + 1 for i, t in enumerate(types)}
    con.executemany("insert into ZACCOUNTTYPE values (?,?)", [(v, k) for k, v in tid.items()])
    con.executemany("insert into ZACCOUNT values (?,?,?,?,?,?)",
                    [(pk, ident, user, tid[t], auth, parent) for pk, ident, user, t, auth, parent in accounts])
    con.commit()
    con.close()


def _selftest() -> int:
    fails = []
    G, C = "com.apple.account.Google", "com.apple.account.CalDAV"
    t0 = 811760000.0

    def run(stores, accounts, surface=True, drop_accounts=False):
        with tempfile.TemporaryDirectory() as d:
            cal, acc = Path(d, "cal.db"), Path(d, "acc.db")
            _mk_calendar(cal, stores)
            if not drop_accounts:
                _mk_accounts(acc, accounts)
            os.environ["CALSYNC_CALENDAR_DB"], os.environ["CALSYNC_ACCOUNTS_DB"] = str(cal), str(acc)
            try:
                rows, unknown = collect()
                return rows, unknown, render(rows, unknown, surface)
            finally:
                os.environ.pop("CALSYNC_CALENDAR_DB", None)
                os.environ.pop("CALSYNC_ACCOUNTS_DB", None)

    accts = [(1, "P-GMAIL", "a@example.com", G, 0, None), (2, "C-GMAIL", "", C, 1, 1),
             (3, "P-LAB", "b@example.org", G, 1, None), (4, "C-LAB", "", C, 1, 3)]
    stores = [(6, "Gmail", "C-GMAIL", 0, 7, t0, t0 + 0.007), (4, "b@example.org", "C-LAB", 0, 0, t0, t0 + 1.2),
              (17, "holidays", "X", 1, 0, None, None)]
    # 1. 親が未認証 → 🔴 (子の CalDAV が 1 でも親を見る)
    rows, unknown, out = run(stores, accts)
    st = {r["store"]: r["status"] for r in rows}
    if st != {"Gmail": "unauth", "b@example.org": "ok"}:
        fails.append(f"1 status {st}")
    if "🔴 Gmail (a@example.com)" not in out or "再サインイン" not in out:
        fails.append("1 render " + out)
    # 2. 全部健全 → --surface は完全沈黙
    ok_accts = [(1, "P-GMAIL", "a@example.com", G, 1, None)] + accts[1:]
    ok_stores = [(6, "Gmail", "C-GMAIL", 0, 0, t0, t0 + 4.6), stores[1]]
    _, _, out = run(ok_stores, ok_accts)
    if out != "":
        fails.append("2 not silent: " + out)
    # 3. 認証は有効だが error → 🟠 (1 つだけ)
    err_stores = [(6, "Gmail", "C-GMAIL", 0, 9, t0, t0 + 0.01), stores[1]]
    rows, _, out = run(err_stores, ok_accts)
    if "🟠 Gmail" not in out or any(r["status"] == "unauth" for r in rows):
        fails.append("3 " + out)
    # 4. 全アカウント error かつ認証切れ無し → offline の 1 行に畳む
    all_err = [(6, "Gmail", "C-GMAIL", 0, 9, t0, t0 + 0.01), (4, "b@example.org", "C-LAB", 0, 9, t0, t0 + 0.01)]
    rows, _, out = run(all_err, ok_accts)
    if {r["status"] for r in rows} != {"offline"} or "ネットワーク断" not in out or "🟠" in out:
        fails.append("4 " + out)
    # 5. Accounts DB が無い → 認証軸を欠いた unknown を明示 (沈黙しない)
    rows, unknown, out = run(ok_stores, ok_accts, drop_accounts=True)
    if not unknown or "未チェック" not in out:
        fails.append("5 " + out)
    # 6. Calendar DB が無い → unknown、 rows 空
    os.environ["CALSYNC_CALENDAR_DB"] = "/nonexistent/cal.db"
    try:
        rows, unknown = collect()
    finally:
        os.environ.pop("CALSYNC_CALENDAR_DB", None)
    if rows or not unknown:
        fails.append(f"6 rows={rows} unknown={unknown}")
    # 8. 試行中 (end < start) は負の秒でなく「同期中」
    rows, _, _ = run([(6, "Gmail", "C-GMAIL", 0, 0, t0, t0 - 20.0)], ok_accts)
    if rows[0]["duration_s"] != "同期中":
        fails.append(f"8 {rows[0]['duration_s']}")
    # 7. 未認証 + 別アカウント error は offline に畳まない (認証切れを隠さない)
    mixed = [(6, "Gmail", "C-GMAIL", 0, 9, t0, t0 + 0.01), (4, "b@example.org", "C-LAB", 0, 9, t0, t0 + 0.01)]
    rows, _, out = run(mixed, accts)
    if "🔴 Gmail" not in out or "ネットワーク断" in out:
        fails.append("7 " + out)

    for f in fails:
        print("FAIL", f)
    print(f"selftest: {8 - len(fails)}/8 PASS" if not fails else f"selftest: {len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
