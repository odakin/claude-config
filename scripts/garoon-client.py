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
  status                                                        いま読めるか (GET 1 本。 切れていれば上の復帰を試す)
  doctor                                                        配線だけを見る (browser の cookie を読めるか。 network なし、 健全なら無言)

共通 option: --org <subdomain> (env GAROON_ORG)  --browser brave|chrome  --profile Default
             --browser-refresh off|keep|close (env GAROON_BROWSER_REFRESH)  --wait-login 秒

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
    REST の 401。 切れていたら下の「login 切れからの復帰」。 script はパスワードも OTP も扱わない。

login 切れからの復帰 (手順 = conventions/garoon.md#garoon-session-recovery、 設計の要点 = conventions/machine-route-first.md#sso-session-recovery):
  切れは 2 層ある = Garoon 本体のセッション (JSESSIONID) と SSO (IdP) のログイン。 本体だけが切れていて IdP が
  生きていれば、 browser が Garoon を開くだけで入り直せる。 IdP も切れていれば本人のログインが要る。
  どちらなのかを**見積もらず、 browser に開かせた tab の行き先で見る**:
    1. 手元の cookie が古いだけ (= browser はもう入り直していて、 cookie DB への書き出しが遅れていた) なら読み直して終わり。
    2. `--browser-refresh keep|close` (env GAROON_BROWSER_REFRESH、 **既定 off** = 人の browser に触る副作用は opt-in) なら、
       **起動中の** browser に tab を 1 枚、 裏で開かせる (前面の tab は元に戻す。 browser が起動していなければ何もしない)。
       - tab が Garoon の中に着いた = 入り直せた → cookie DB の更新を待って読み直し、 1 回だけ撃ち直す。
         `close` なら自分が開いたその tab を閉じる (tab が Garoon の外に居る・本人がログインに使った時は閉じない)。
       - tab が Garoon の外 (ログイン画面) で止まった = 本人のログインが要る → exit 75 で止まる (`close` なら、 その
         ログイン画面の tab も閉じる = 失敗のたびに tab が溜まらない)。 `--wait-login 秒` を付けると、 tab をログインの
         入口として残し、 本人がログインし終えるのを待って続きから進む。
    3. tab の駆動と結末の判定は scripts/lib/browser_tab.py (他の SSO 保護サイトの client でも使える部品)。
       見るのは tab の「query を落とした URL」 と「読み込み中か」 だけ (ページの中身・認証応答は読まない)。 IdP の cookie も読まない。
       AppleScript が使えない環境では `open -g` で開くだけに落ち、 cookie DB の更新だけを待つ。
  ⚠️ IdP の有効期間 (組織の方針) は延ばさない = 定期的に開かせる仕組みにしない。 開かせるのは読む用事がある時だけ。
  ⚠️ Chromium の cookie DB 書き出しは最大 30 秒ほど遅れる。

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
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # importlib 経由で読まれた時も lib を引けるように
from lib.browser_tab import BROWSER_APPS, BrowserTab, watch, selftest_cases as _tab_selftest_cases  # noqa: E402

EX_LOGIN = 75  # exit code (EX_TEMPFAIL): 本人のログインが要る


class LoginRequired(Exception):
    """login 切れから復帰できなかった。 observed=True なら、 ログイン画面で止まるのを見た (= 本人の操作が要る)。"""

    def __init__(self, why, observed=False):
        super().__init__(why)
        self.why, self.observed = why, observed


def _say(msg):
    print(f"Garoon: {msg}", file=sys.stderr, flush=True)


def _cc():
    spec = importlib.util.spec_from_file_location("cc", HERE / "chromium-cookies.py")
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    return cc


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


def inside(url, base_host):
    """tab の行き先 (query なしの URL) が Garoon の中か (= ログイン画面でも別 host でもない)。"""
    u = urlparse(url)
    return u.scheme == "https" and u.hostname == base_host and not u.path.rstrip("/").endswith("/login")


class Garoon:
    def __init__(self, org, browser="brave", profile="Default", refresh="off", wait_login=0):
        self.base = f"https://{org}.cybozu.com"
        self.host = urlparse(self.base).hostname
        self.org, self.browser, self.profile = org, browser, profile
        self.refresh, self.wait_login = refresh, wait_login
        import requests  # doctor / selftest は network を使わないので、 ここまで読み込まない
        self.s = requests.Session()
        self.h = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
        self._csrf = None
        self._recovered = False
        self.recovered_by = None  # None / "reload" / "refresh" (status の表示用)
        self._load()

    def _stamp(self):
        """browser の cookie DB にある JSESSIONID の (作成, 更新) 時刻 (値は読まない)。 読めなければ None。"""
        db = Path(_cc().BROWSERS[self.browser][0]).expanduser() / self.profile / "Cookies"
        try:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "c.db"
                shutil.copy(db, p)
                con = sqlite3.connect(p)
                try:
                    return con.execute("select max(creation_utc), max(last_update_utc) from cookies where host_key = ? "
                                       "and name = 'JSESSIONID'", (self.host,)).fetchone()
                finally:
                    con.close()
        except Exception:  # noqa: BLE001
            return None

    def _stamp_changed(self):
        """cookie DB の JSESSIONID が、 手元に読んだ時から変わったか (一時的に読めないのは「変わった」 に数えない)。"""
        now = self._stamp()
        return now is not None and now != self._loaded_stamp

    def _load(self):
        """cookie を browser から読み直す。 時刻を先に読む (= 逆順だと、 間に挟まった更新を見落とす)。"""
        self._loaded_stamp = self._stamp()
        self.s.cookies.clear()
        self.s.cookies.update(_cc().load_cookies(self.browser, ["cybozu.com"], self.profile))  # IdP の cookie は読まない
        self._csrf = None

    def _recover(self, why):
        """login 切れからの復帰 (process ごとに 1 回)。 cookie を読み直すたびに yield = 呼び元が 1 回ずつ撃ち直す。"""
        if self._recovered:
            return
        self._recovered = True
        if self._stamp_changed():  # browser はもう入り直していて、 手元が古いだけ
            self._load()
            yield "reload"
        app = BROWSER_APPS.get(self.browser)
        tab = None
        if self.refresh != "off" and app and platform.system() == "Darwin" and BrowserTab.running(app):
            _say(f"session 切れ ({why}) → 起動中の {app} に裏で開かせて入り直す")
            tab = BrowserTab(app)
            tab.open(f"{self.base}/g/")
        elif not self.wait_login:
            return
        t0 = time.time()
        end, saw_login, at = watch(tab.where if tab else (lambda: None), self._stamp_changed, lambda u: inside(u, self.host),
                                   self.wait_login, say=_say)
        if end == "login":
            if self.refresh == "close":
                tab.close(at)  # 待たないなら入口も残さない (= 失敗のたびにログイン画面の tab が溜まらない)
            raise LoginRequired(why, observed=True)
        if end == "timeout":
            return  # wait-login の時間切れも含む。 本人が入力の途中かもしれないので tab は閉じない
        if end == "fresh":
            time.sleep(2)  # 同じ書き出しで他の cookie も揃うのを待つ
        if tab and self.refresh == "close" and not saw_login:
            tab.close(self.base + "/")  # 本人がログインに使った tab は本人のものなので閉じない
        self._load()
        _say(f"入り直した ({time.time() - t0:.0f} 秒)")
        yield "refresh"

    def _request(self, method, path, allow_redirects=False, **kw):
        headers, timeout = kw.pop("headers", self.h), kw.pop("timeout", 60)

        def send():
            r = self.s.request(method, self.base + path, headers=headers, timeout=timeout,
                               allow_redirects=allow_redirects, **kw)
            return r, expired(r.status_code, r.headers.get("Location", ""), r.text, self.host)

        r, why = send()
        if not why:
            return r
        for how in self._recover(why):
            r, again = send()
            if not again:
                self.recovered_by = how
                return r
        raise LoginRequired(why)

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


def doctor(browser, profile):
    """script 経路の配線だけを見る (= browser の cookie を読めるか)。 network なし。 健全・対象外なら []。

    ログインが切れているかは見ない: 切れは配線の故障ではなく通常の周期で、 読む用事がある時に復帰を試せば足りる
    (= 切れを常時の警告にすると、 大半の時間出続けて誰も読まなくなる)。
    """
    if platform.system() != "Darwin":
        return []
    try:
        cc = _cc()
        if not (Path(cc.BROWSERS[browser][0]).expanduser() / profile / "Cookies").exists():
            return []  # この機械はこの経路の対象外
        cc.load_cookies(browser, ["cybozu.com"], profile)
    except SystemExit as e:
        first = (str(e).splitlines() or [""])[0][:80]
        return [f"🟠 Garoon script 経路: browser の cookie を復号できない ({first}) = 対話 session で 1 回実行して Keychain を許可"]
    except Exception as e:  # noqa: BLE001
        return [f"🟠 Garoon script 経路: browser の cookie を読めない ({type(e).__name__})"]
    return []


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

    # 入り直しの結末判定 (偽の tab と時計) は lib 側の台本を回す
    checks = _tab_selftest_cases() + [
        ("Garoon の中の判定: /login と別 host と http は外", inside("https://x.cybozu.com/g/", host)
         and not inside("https://x.cybozu.com/login", host) and not inside("https://y.cybozu.com/g/", host)
         and not inside("http://x.cybozu.com/g/", host) and not inside("chrome-error://chromewebdata/", host)),
    ]
    for name, good in checks:
        ok &= bool(good)
        print("PASS" if good else "FAIL", name)
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--org", default=os.environ.get("GAROON_ORG"), help="cybozu.com subdomain (env GAROON_ORG)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--profile", default="Default")
    ap.add_argument("--browser-refresh", choices=("off", "keep", "close"),
                    default=os.environ.get("GAROON_BROWSER_REFRESH", "off"),
                    help="切れた時に起動中の browser に裏で tab を開かせて入り直すか (env GAROON_BROWSER_REFRESH)。 "
                         "keep = 開いた tab を残す / close = 入り直せたら自分が開いた tab を閉じる")
    ap.add_argument("--wait-login", type=int, default=0, metavar="秒",
                    help="本人のログインが要る時、 ログインし終えるのをこの秒数まで待って続きから進む")
    ap.add_argument("--selftest", action="store_true", help="切れ判定と入り直しの結末判定の自己テスト (network・browser なし)")
    sub = ap.add_subparsers(dest="cmd")
    ap.add_argument("--json", action="store_true", help="raw JSON を出す (subcommand の前に置く)")
    p = sub.add_parser("search"); p.add_argument("keyword"); p.add_argument("--app", default="bulletin"); p.add_argument("--start", type=int, default=0)
    sub.add_parser("bulletin-categories")
    p = sub.add_parser("bulletin-topics"); p.add_argument("category_id")
    p = sub.add_parser("bulletin-topic"); p.add_argument("topic_id")
    p = sub.add_parser("download"); p.add_argument("fid"); p.add_argument("--app", default="bulletin"); p.add_argument("--out", required=True)
    p = sub.add_parser("get"); p.add_argument("path")
    sub.add_parser("status")
    sub.add_parser("doctor")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.cmd:
        ap.error("subcommand が要る")
    if a.cmd == "doctor":
        for line in doctor(a.browser, a.profile):
            print(line)
        return
    if not a.org:
        raise SystemExit("--org か env GAROON_ORG が要る (= 組織 subdomain、 private 層の環境 doc 参照)")
    try:
        run(a, Garoon(a.org, a.browser, a.profile, refresh=a.browser_refresh, wait_login=a.wait_login))
    except LoginRequired as e:
        app = BROWSER_APPS.get(a.browser, a.browser)
        if e.observed:
            _say("SSO のログインが切れている = 本人のログインが要る (ログイン画面で止まるのを見た)。 `--wait-login 600` を付けて"
                 f"実行し直すと、 {app} にログイン画面を開いたまま、 本人がログインし終えるのを待って続きから進む"
                 + ("" if a.browser_refresh == "close" else f"。 いま {app} に開いたログイン画面の tab は残してある"))
        else:
            _say(f"session 切れ ({e.why}) から復帰できなかった → {app} で https://{a.org}.cybozu.com/g/ を開いてログインしてから再実行"
                 + ("" if a.browser_refresh != "off" else " (`--browser-refresh keep|close` で browser に入り直させられる)"))
        sys.exit(EX_LOGIN)


def run(a, g):
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
    elif a.cmd == "status":
        g.get("/g/portal/index.csp")  # 生きていれば同じ host の中への 302 (本文なし = 軽い)
        print("読める" + {None: "", "reload": " (cookie を読み直した)", "refresh": " (browser に入り直させた)"}[g.recovered_by])


if __name__ == "__main__":
    main()
