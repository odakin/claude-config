#!/usr/bin/env python3
"""garoon-client.py — Cybozu Garoon (cloud) を **browser session cookie で script から読む** (画面 drive 不要)。

背景: SAML-only の組織では REST の password auth が admin 限定・OAuth client も admin 登録要 = user 側で
発行できる credential が無い。 唯一残る機械経路 = user が browser で login 済みの session cookie を
再利用する (= `chromium-cookies.py`)。 本 script はその上に Garoon の主要 read 操作を載せた薄い client。
一般則 = conventions/machine-route-first.md #wiring-gap-is-a-task、 Garoon 機構 = conventions/garoon.md。

subcommand:
  search   <keyword> [--app bulletin|cabinet|...] [--start N]   全文検索 (= UI の検索 box と同じ engine)
  bulletin-categories                                           掲示板 category 一覧 (REST)
  bulletin-topics <category_id>                                 category 内の掲示一覧 (REST)
  bulletin-topic <topic_id>                                     掲示 1 件の本文 (REST)
  download <fid> --app bulletin|cabinet --out <path>            添付 file の download (file_download.csp / download.csp)
  get <path> [--json]                                           任意 path を GET (= /g/... の HTML/JSON、 debug 用)

共通 option: --org <subdomain> (env GAROON_ORG)  --browser brave|chrome  --profile Default

機構 fact (2026-09-07 実測、 Garoon 6.31 cloud):
  - 全文検索 = `POST /g/fts/api/search?csrf_ticket=<ticket>` + JSON body
      {"keyword": kw, "apps": ["bulletin"|"cabinet"|...], "start": 0,
       cabinet の時は "cabinetFolderId": "1"(= root) と "fileOnly": true が必須 (無いと GRN_FTS_00001 520)}
    header `X-Requested-With: XMLHttpRequest`。 応答 = {"result": {"docs": [...], "continuable": bool}, "succes": true}
    doc = {title, url (/g/bulletin/view.csp?aid=N | /g/cabinet/view.csp?hid=H&fid=F), snippet (HTML), modifiedTime,
           modifier{displayName}, file{title, downloadUrl(= .../file_download.csp/-/<name>?fid=F), size}}
    ⚠️ search.csp の HTML は結果を含まない (JS が上の API を叩いて描画) — HTML を grep して「0 件」 と言わない。
  - csrf ticket = /g/cabinet/search.csp 等の **redirect しない** /g/ ページの inline script (portal/index.csp は
    302 → index.csp?pid=N なので allow_redirects なしだと取れない) `grn.__PRELOADED_DATA__ = {"csrfTicket": "..."}` から取る。
  - REST = `GET /g/api/v1/bulletin/...` (session auth = cookie + X-Requested-With で通る)。
  - file = `GET /g/bulletin/file_download.csp/-/<name>?fid=F` / `GET /g/cabinet/download.csp/-/<name>?fid=F`
    (cabinet 側は UI では time= 署名 token が付くが、 session 内 GET で通るかは要実測 = 本 script の download が
    login page を返したら token 要 → 検索結果の downloadUrl をそのまま使う)。
  - login 切れの判定 = 302 → SSO (別 host) / 302 → `<org>.cybozu.com/login` / 200 + `<title>ログイン` /
    REST の 401 → 下の「browser に入り直させる」 を 1 回試し、 だめなら「browser で再 login」 と言う (script は代行しない)。

browser に入り直させる (既定 ON、 `--no-reauth-browser` / env GAROON_REAUTH_BROWSER=0 で切る):
  Garoon 本体のセッションだけが切れていて SSO (IdP) のログインが生きている間は、 browser で Garoon を開けば
  パスワードも OTP もなしで入り直せる。 script はそれを自分でやらず (= IdP の cookie で SAML を辿ると script が
  認証応答を扱うことになる)、 **起動中の** browser に `open -g` で portal を開かせ、 cookie DB の JSESSIONID が
  更新されるのを最大 45 秒待って読み直し、 1 回だけ再試行する。 browser が起動していなければ何もしない
  (= 勝手に起動しない)。 IdP も切れていれば開いたタブがログイン画面になる = そこで本人がログインしてから再実行。
  ⚠️ 開いたタブは閉じない (= user の browser のタブを script が閉じない)。 Chromium の cookie DB 書き出しは
  十数秒遅れる。 IdP の有効期間 (組織の方針) は延ばさない = 入り直せるのは IdP が生きている間だけ。

⚠️ 出力に cookie / ticket を出さない。 取得した掲示本文・file は組織の内部情報 = private 層にしか置かない。
"""
import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

HERE = Path(__file__).resolve().parent
BROWSER_APPS = {"brave": "Brave Browser", "chrome": "Google Chrome", "chromium": "Chromium"}
REAUTH_WAIT_S = 45


def _cc():
    spec = importlib.util.spec_from_file_location("cc", HERE / "chromium-cookies.py")
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    return cc


def _cookies(browser, profile, org):
    return _cc().load_cookies(browser, ["cybozu.com"], profile)  # IdP の cookie は読まない (= script は IdP に触れない)


def expired(code, location, text, base_host):
    """HTTP 応答が「Garoon のログイン切れ」 なら理由、 そうでなければ None。"""
    if code in (301, 302, 303):
        u = urlparse(location)
        if u.hostname and u.hostname != base_host:
            return "SSO redirect"
        if u.path.rstrip("/").endswith("/login"):
            return "login redirect"
    if code == 200 and "<title>ログイン" in (text or "")[:3000]:
        return "login page"
    if code == 401:
        return "401"
    return None


class Garoon:
    def __init__(self, org, browser="brave", profile="Default", reauth=True):
        self.base = f"https://{org}.cybozu.com"
        self.org, self.browser, self.profile, self.reauth = org, browser, profile, reauth
        self.s = requests.Session()
        self.s.cookies.update(_cookies(browser, profile, org))
        self.h = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
        self._csrf = None
        self._reauth_tried = False

    def _session_stamp(self):
        """browser の cookie DB にある JSESSIONID の (作成, 更新) 時刻 (値は読まない)。 読めなければ None。"""
        db = Path(_cc().BROWSERS[self.browser][0]).expanduser() / self.profile / "Cookies"
        try:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "c.db"
                shutil.copy(db, p)
                con = sqlite3.connect(p)
                try:
                    return con.execute("select creation_utc, last_update_utc from cookies where host_key = ? "
                                       "and name = 'JSESSIONID'", (f"{self.org}.cybozu.com",)).fetchone()
                finally:
                    con.close()
        except Exception:  # noqa: BLE001
            return None

    def _browser_reauth(self, why):
        """起動中の browser に Garoon を開かせ、 JSESSIONID が更新されたら cookie を読み直す。 True = 読み直した。"""
        self._reauth_tried = True
        app = BROWSER_APPS.get(self.browser)
        if not (self.reauth and app and platform.system() == "Darwin"):
            return False
        if subprocess.run(["pgrep", "-xq", app]).returncode != 0:
            return False
        before = self._session_stamp()
        url = f"{self.base}/g/portal/index.csp"
        print(f"Garoon session 切れ ({why}) → 起動中の {app} で {url} を裏で開き、 入り直しを最大 {REAUTH_WAIT_S} 秒待つ",
              file=sys.stderr)
        subprocess.run(["open", "-g", "-a", app, url], check=False)
        deadline = time.time() + REAUTH_WAIT_S
        while time.time() < deadline:
            time.sleep(3)
            now = self._session_stamp()
            if now and now != before:
                time.sleep(2)  # 同じ書き出しで他の cookie も揃うのを待つ
                self.s.cookies.clear()
                self.s.cookies.update(_cookies(self.browser, self.profile, self.org))
                self._csrf = None
                return True
        return False

    def _request(self, method, path, allow_redirects=False, **kw):
        headers, timeout = kw.pop("headers", self.h), kw.pop("timeout", 60)
        while True:
            r = self.s.request(method, self.base + path, headers=headers, timeout=timeout,
                               allow_redirects=allow_redirects, **kw)
            why = expired(r.status_code, r.headers.get("Location", ""), r.text, urlparse(self.base).hostname)
            if not why:
                return r
            if self._reauth_tried or not self._browser_reauth(why):
                app = BROWSER_APPS.get(self.browser, self.browser)
                raise SystemExit(f"Garoon session 切れ ({why}) → {app} で {self.base}/g/ を開いて再 login してから再実行"
                                 " (SSO も切れていれば OTP が要る。 script が開いたタブがあればそこで)")

    def get(self, path, **kw):
        return self._request("GET", path, **kw)

    @property
    def csrf(self):
        if not self._csrf:
            # redirect を辿らない (= 切れた時に SSO host へ cookie を持って行かず、 302 を切れとして捕まえる)
            t = self._request("GET", "/g/cabinet/search.csp", params={"text": "x"}).text
            m = re.search(r'"csrfTicket":"([0-9a-f]+)"', t)
            if not m:
                raise SystemExit("csrfTicket が取れない (= 未 login か page 構造変化)")
            self._csrf = m.group(1)
        return self._csrf

    def search(self, keyword, app="bulletin", start=0, **extra):
        body = {"keyword": keyword, "apps": [app], "start": start}
        if app == "cabinet":
            body.setdefault("cabinetFolderId", "1")
            body.setdefault("fileOnly", True)
        body.update(extra)
        ticket = self.csrf  # 切れていればここで入り直す (= POST に古い ticket を載せない)
        r = self._request("POST", "/g/fts/api/search", params={"csrf_ticket": ticket}, data=json.dumps(body),
                          headers={**self.h, "Content-Type": "application/json"}, timeout=90)
        if r.status_code != 200:
            raise SystemExit(f"fts/api/search {r.status_code}: {r.text[:300]}")
        return r.json().get("result", {})

    def rest(self, path, **params):
        r = self.get("/g/api/v1" + path, params=params)
        if r.status_code != 200:
            raise SystemExit(f"REST {path} {r.status_code}: {r.text[:300]}")
        return r.json()

    def download(self, fid, app, out):
        path = "/g/bulletin/file_download.csp/-/f" if app == "bulletin" else "/g/cabinet/download.csp/-/f"
        r = self.get(path, params={"fid": fid})
        if r.status_code != 200 or r.headers.get("content-type", "").startswith("text/html"):
            raise SystemExit(f"download fid={fid} 失敗 {r.status_code} {r.headers.get('content-type')} (cabinet は time= token 要かも)")
        Path(out).write_bytes(r.content)
        return len(r.content), r.headers.get("content-type")


def _strip(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("\n", " ")


def selftest():
    host = "x.cybozu.com"
    cases = [
        ((302, "https://x.ex-tic.com/auth/saml2/a/assertions?SAMLRequest=z", ""), "SSO redirect"),
        ((302, "https://x.cybozu.com/login?redirect=https%3A%2F%2Fx.cybozu.com%2Fg%2F", ""), "login redirect"),
        ((302, "/login?redirect=%2Fg%2F", ""), "login redirect"),
        ((200, "", "<html><head><title>ログイン</title>"), "login page"),
        ((401, "", '{"error":{"errorCode":"GRN_REST_API_00003"}}'), "401"),
        ((302, "https://x.cybozu.com/g/portal/index.csp?pid=44", ""), None),
        ((302, "/g/index.csp?pid=44", ""), None),
        ((200, "", "<title>ポータル</title>"), None),
    ]
    ok = True
    for (code, loc, text), want in cases:
        got = expired(code, loc, text, host)
        ok &= got == want
        print("PASS" if got == want else "FAIL", code, loc[:40], "->", got)
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--org", default=os.environ.get("GAROON_ORG"), help="cybozu.com subdomain (env GAROON_ORG)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--profile", default="Default")
    ap.add_argument("--no-reauth-browser", action="store_true",
                    help="切れた時に起動中の browser で Garoon を開いて入り直させない (env GAROON_REAUTH_BROWSER=0 と同じ)")
    ap.add_argument("--selftest", action="store_true", help="login 切れ判定の自己テスト (network なし)")
    sub = ap.add_subparsers(dest="cmd")
    ap.add_argument("--json", action="store_true", help="raw JSON を出す (subcommand の前に置く)")
    p = sub.add_parser("search"); p.add_argument("keyword"); p.add_argument("--app", default="bulletin"); p.add_argument("--start", type=int, default=0)
    sub.add_parser("bulletin-categories")
    p = sub.add_parser("bulletin-topics"); p.add_argument("category_id")
    p = sub.add_parser("bulletin-topic"); p.add_argument("topic_id")
    p = sub.add_parser("download"); p.add_argument("fid"); p.add_argument("--app", default="bulletin"); p.add_argument("--out", required=True)
    p = sub.add_parser("get"); p.add_argument("path")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.cmd:
        ap.error("subcommand が要る")
    if not a.org:
        raise SystemExit("--org か env GAROON_ORG が要る (= 組織 subdomain、 private 層の環境 doc 参照)")
    reauth = not (a.no_reauth_browser or os.environ.get("GAROON_REAUTH_BROWSER") == "0")
    g = Garoon(a.org, a.browser, a.profile, reauth=reauth)
    if a.cmd == "search":
        res = g.search(a.keyword, a.app, a.start)
        if a.json:
            print(json.dumps(res, ensure_ascii=False)); return
        docs = res.get("docs", [])
        print(f"# {a.app} '{a.keyword}': {len(docs)} docs (continuable={res.get('continuable')})")
        for d in docs:
            f = d.get("file") or {}
            fid = re.search(r"fid=(\d+)", f.get("downloadUrl", "") or "")
            print(f"- {d.get('title','')} | {d.get('url')} | {d.get('modifiedTime')} | {(d.get('modifier') or {}).get('displayName','')}"
                  + (f" | file={f.get('title')} fid={fid.group(1) if fid else '-'}" if f else ""))
            print(f"    {_strip(d.get('snippet'))[:300]}")
    elif a.cmd == "bulletin-categories":
        print(json.dumps(g.rest("/bulletin/categories"), ensure_ascii=False, indent=None if a.json else 1))
    elif a.cmd == "bulletin-topics":
        print(json.dumps(g.rest(f"/bulletin/categories/{a.category_id}/topics"), ensure_ascii=False, indent=None if a.json else 1))
    elif a.cmd == "bulletin-topic":
        print(json.dumps(g.rest(f"/bulletin/topics/{a.topic_id}"), ensure_ascii=False, indent=None if a.json else 1))
    elif a.cmd == "download":
        n, ct = g.download(a.fid, a.app, a.out); print(f"saved {a.out} ({n} bytes, {ct})")
    elif a.cmd == "get":
        r = g.get(a.path)
        print(r.text if not a.json else json.dumps(r.json(), ensure_ascii=False))


if __name__ == "__main__":
    main()
