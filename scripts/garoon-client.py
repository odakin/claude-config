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
       - cookie DB が変わったら読み直し、 **server が受け入れた時だけ** 入り直せたとする (GET 1 本で確かめる)。
         ⚠️ cookie が変わった ≠ 入り直せた: ログイン画面 (/login) は開かれるたびに未認証の JSESSIONID を配る (実測)
         = IdP が切れていても browser がログイン画面を通るだけで cookie DB は変わる。 受け入れられなければ見続ける。
       - tab が Garoon の中に着いたのに cookie DB が変わらない時は、 読み直して server に確かめる (同じ cookie のまま認証が済む場合)。
         入り直せたら 1 回だけ撃ち直す。
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
from lib.browser_tab import BROWSER_APPS, POLL_S, BrowserTab, watch, selftest_cases as _tab_selftest_cases  # noqa: E402

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
        self._clock, self._sleep = time.time, time.sleep  # selftest が偽の時計に差し替える
        self._probe_gap, self._next_probe = 0, 0.0  # 未認証の cookie を掴んだ後の確かめ直しの間隔 (_renewed)
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

    def _alive(self):
        """手元の cookie を server が受け入れるか (GET 1 本。 生きていれば同じ host の中への 302 で本文なし = 軽い)。"""
        r = self.s.get(self.base + "/g/portal/index.csp", headers=self.h, timeout=30, allow_redirects=False)
        return not expired(r.status_code, r.headers.get("Location", ""), r.text, self.host)

    def _renewed(self):
        """watch に渡す「入り直せたか」。 cookie DB が変わったら読み直し、 **server が受け入れた時だけ** True。

        cookie が変わった ≠ 入り直せた: Garoon のログイン画面 (/login) は開かれるたびに未認証の JSESSIONID を配る
        (実測) = browser がログイン画面を通っただけで cookie DB は変わる。 それを「入り直せた」 と読むと、
        IdP が切れている時に未認証の cookie で撃ち直して失敗し、 本人のログインが要ることも言えない。 受け入れられなければ
        読み直した時刻を新しい基準にして見続ける (= ログイン画面で止まるのを見届ける / SAML の完了を待つ)。
        未認証の cookie を掴んだ後は、 cookie DB が変わらなくても間隔を空けて確かめ直す (SAML の完了で同じ cookie が
        認証済みになる場合、 DB はもう変わらない。 間隔は 5 → 10 → 15 秒で頭打ち = 待つ間の GET は軽い 302 だけ)。
        """
        if self._stamp_changed():
            self._sleep(2)  # 同じ書き出しで他の cookie も揃うのを待つ
            self._load()
        elif not self._probe_gap or self._clock() < self._next_probe:
            return False
        if self._alive():
            return True
        if not self._probe_gap:
            _say("cookie は変わったがまだ受け入れられない (ログイン画面が配った未認証の cookie) → tab の行き先を見続ける")
        self._probe_gap = min(15, self._probe_gap + 5)
        self._next_probe = self._clock() + self._probe_gap
        return False

    def _open_tab(self, why):
        """起動中の browser に裏で tab を開かせる。 開かなければ None。"""
        app = BROWSER_APPS.get(self.browser)
        if self.refresh == "off" or not app or platform.system() != "Darwin" or not BrowserTab.running(app):
            return None
        _say(f"session 切れ ({why}) → 起動中の {app} に裏で開かせて入り直す")
        tab = BrowserTab(app)
        tab.open(f"{self.base}/g/")
        return tab

    def _recover(self, why):
        """login 切れからの復帰 (process ごとに 1 回)。 入り直せた = 読み直した cookie を server が受け入れた時だけ True。"""
        if self._recovered:
            return False
        self._recovered = True
        if self._stamp_changed():  # browser はもう入り直していて、 手元が古いだけ
            self._load()
            if self._alive():
                self.recovered_by = "reload"
                return True
        tab = self._open_tab(why)
        if not tab and not self.wait_login:
            return False
        t0 = self._clock()
        self._probe_gap, self._next_probe = 0, 0.0
        end, saw_login, at = watch(tab.where if tab else (lambda: None), self._renewed, lambda u: inside(u, self.host),
                                   self.wait_login, clock=self._clock, sleep=self._sleep, say=_say)
        if end == "login":
            if self.refresh == "close":
                tab.close(at)  # 待たないなら入口も残さない (= 失敗のたびにログイン画面の tab が溜まらない)
            raise LoginRequired(why, observed=True)
        if end == "timeout":
            return False  # wait-login の時間切れも含む。 本人が入力の途中かもしれないので tab は閉じない
        if end == "stale":  # tab は中に着いたが cookie DB は変わらなかった (= 手元の cookie のまま認証が済んだ場合を含む)
            self._load()
            if not self._alive():
                return False
        if tab and self.refresh == "close" and not saw_login:
            tab.close(self.base + "/")  # 本人がログインに使った tab は本人のものなので閉じない
        _say(f"入り直した ({self._clock() - t0:.0f} 秒)")
        self.recovered_by = "refresh"
        return True

    def _request(self, method, path, allow_redirects=False, **kw):
        headers, timeout = kw.pop("headers", self.h), kw.pop("timeout", 60)

        def send():
            r = self.s.request(method, self.base + path, headers=headers, timeout=timeout,
                               allow_redirects=allow_redirects, **kw)
            return r, expired(r.status_code, r.headers.get("Location", ""), r.text, self.host)

        r, why = send()
        if not why:
            return r
        if self._recover(why):
            r, again = send()
            if not again:
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


def _fake_recover(tab_script, stamp_changes, alive_from, wait_login=0, local_stale=False):
    """selftest 用: 偽の tab (行き先の台本、 1 poll に 1 つ) ・時計・cookie DB (JSESSIONID が変わる時刻の list) ・
    server (その時刻から cookie を受け入れる。 None = 受け入れない) で _recover を回す。
    → (結末, tab を開いたか, 自分の tab を閉じたか, 経過秒)。 結末 = "reload" / "refresh" / "failed" / "login" / "login-observed"。"""
    global _say
    t, opened, closed, said = [0.0], [], [], []

    class Tab:
        def where(self):
            return tab_script[min(int(t[0] / POLL_S), len(tab_script) - 1)]

        def close(self, prefix):
            closed.append(prefix)
            return True

    g = Garoon.__new__(Garoon)  # network と browser に触る __init__ を通さない
    g.base, g.host, g.browser, g.profile = "https://x.cybozu.com", "x.cybozu.com", "brave", "Default"
    g.refresh, g.wait_login, g._recovered, g.recovered_by, g._csrf = "close", wait_login, False, None, None
    g._clock, g._sleep = (lambda: t[0]), (lambda s: t.__setitem__(0, t[0] + s))
    g._probe_gap, g._next_probe = 0, 0.0
    g._stamp = lambda: sum(1 for c in stamp_changes if t[0] >= c)
    g._load = lambda: setattr(g, "_loaded_stamp", g._stamp())
    g._alive = lambda: alive_from is not None and t[0] >= alive_from
    g._open_tab = lambda why: opened.append(why) or Tab()
    g._loaded_stamp = -1 if local_stale else g._stamp()
    saved, _say = _say, said.append
    try:
        end = g.recovered_by if g._recover("login redirect") else "failed"
    except LoginRequired as e:
        end = "login-observed" if e.observed else "login"
    finally:
        _say = saved
    return end, bool(opened), bool(closed), t[0]


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
    def _parsed(argv):
        return build_parser().parse_args(argv)
    gl, lg = ("https://x.cybozu.com/g/", True), ("https://x.cybozu.com/login", False)
    idp, asr = ("https://x.ex-tic.com/auth/session", False), ("https://x.ex-tic.com/auth/saml2/x/assertions", False)
    portal = ("https://x.cybozu.com/g/portal/index.csp", False)
    checks = _tab_selftest_cases() + [
        # 実測: ログイン画面 (/login) が配る未認証の JSESSIONID で cookie DB が変わる → 旧版は「入り直した」 と言って
        # 撃ち直し、 失敗して「復帰できなかった」 (本人のログインが要ることを言えない) で止まっていた
        ("IdP が切れている: ログイン画面が配った cookie を入り直しと読まず、 本人のログインが要ると言う",
         _fake_recover([gl, lg, idp], [3], None)[0] == "login-observed"),
        ("IdP が生きていて、 cookie DB がログイン画面の cookie を先に書いた → 確かめ直しで入り直し、 自分の tab を閉じる",
         (lambda r: r[0] == "refresh" and r[2] and r[3] <= 15)(_fake_recover([gl, lg, asr, portal], [3], 6))),
        ("普通の入り直し (cookie DB が SAML の後に変わる) → すぐ入り直す",
         (lambda r: r[0] == "refresh" and r[2] and r[3] <= 8)(_fake_recover([gl, asr, portal], [4], 3))),
        ("wait-login: 本人がログインし終えたら入り直す (ログインに使った tab は閉じない)",
         (lambda r: r[0] == "refresh" and not r[2] and r[3] <= 80)(
             _fake_recover([gl, lg] + [idp] * 40 + [portal], [3], 63, wait_login=300))),
        ("tab が中に着いても server が cookie を受け入れない → 入り直したと言わない",
         _fake_recover([gl, portal], [], None)[0] == "failed"),
        ("手元の cookie が古いだけ (browser は入り直し済み) → tab を開かずに読み直す",
         _fake_recover([portal], [], 0, local_stale=True)[:2] == ("reload", False)),

        ("--wait-login は subcommand の後ろでも効く", _parsed(["search", "k", "--wait-login", "5"]).wait_login == 5),
        ("--wait-login は subcommand の前でも効く", _parsed(["--wait-login", "7", "search", "k"]).wait_login == 7),
        ("後ろで指定しなければ前の値が残る", _parsed(["--wait-login", "7", "--json", "search", "k"]).json is True
         and _parsed(["--wait-login", "7", "search", "k"]).wait_login == 7),
        ("何も付けなければ既定値", _parsed(["status"]).wait_login == 0 and _parsed(["status"]).json is False),
        ("Garoon の中の判定: /login と別 host と http は外", inside("https://x.cybozu.com/g/", host)
         and not inside("https://x.cybozu.com/login", host) and not inside("https://y.cybozu.com/g/", host)
         and not inside("http://x.cybozu.com/g/", host) and not inside("chrome-error://chromewebdata/", host)),
    ]
    for name, good in checks:
        ok &= bool(good)
        print("PASS" if good else "FAIL", name)
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def build_parser():
    """引数の組み立て。 --wait-login / --browser-refresh / --json は subcommand の前でも後でも効く
    (= 後ろに付けると argparse の unrecognized arguments で落ちていた、 実測)。"""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--org", default=os.environ.get("GAROON_ORG"), help="cybozu.com subdomain (env GAROON_ORG)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--profile", default="Default")
    refresh_help = ("切れた時に起動中の browser に裏で tab を開かせて入り直すか (env GAROON_BROWSER_REFRESH)。 "
                    "keep = 開いた tab を残す / close = 入り直せたら自分が開いた tab を閉じる")
    wait_help = "本人のログインが要る時、 ログインし終えるのをこの秒数まで待って続きから進む"
    ap.add_argument("--browser-refresh", choices=("off", "keep", "close"),
                    default=os.environ.get("GAROON_BROWSER_REFRESH", "off"), help=refresh_help)
    ap.add_argument("--wait-login", type=int, default=0, metavar="秒", help=wait_help)
    ap.add_argument("--selftest", action="store_true", help="切れ判定と入り直しの結末判定の自己テスト (network・browser なし)")
    ap.add_argument("--json", action="store_true", help="raw JSON を出す")
    # subcommand の後ろにも同じ option を置けるようにする。 default=SUPPRESS = 後ろで指定しなかった時に前の値を消さない
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--browser-refresh", choices=("off", "keep", "close"), default=argparse.SUPPRESS, help=refresh_help)
    common.add_argument("--wait-login", type=int, default=argparse.SUPPRESS, metavar="秒", help=wait_help)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="raw JSON を出す")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("search", parents=[common]); p.add_argument("keyword"); p.add_argument("--app", default="bulletin"); p.add_argument("--start", type=int, default=0)
    sub.add_parser("bulletin-categories", parents=[common])
    p = sub.add_parser("bulletin-topics", parents=[common]); p.add_argument("category_id")
    p = sub.add_parser("bulletin-topic", parents=[common]); p.add_argument("topic_id")
    p = sub.add_parser("download", parents=[common]); p.add_argument("fid"); p.add_argument("--app", default="bulletin"); p.add_argument("--out", required=True)
    p = sub.add_parser("get", parents=[common]); p.add_argument("path")
    sub.add_parser("status", parents=[common])
    sub.add_parser("doctor", parents=[common])
    return ap


def main():
    ap = build_parser()
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
