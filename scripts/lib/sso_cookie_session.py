"""sso_cookie_session.py — browser の session cookie を借りて SSO 保護サイトを script から読む client の共通部品 (ログイン切れからの入り直し・撃ち直し・配線の診断・切れ方の採取、 macOS + Chromium 系)

使いどころ: SAML / Shibboleth の奥にあって、 user が発行できる API credential が無いサイトを、 user が browser で
ログイン済みの session cookie を借りて読む client (garoon-client.py / campussquare-client.py)。 部品の分担 =
cookie の復号 ../chromium-cookies.py / tab の駆動と結末の判定 browser_tab.py / 本 module = その 2 つを使った session。
手順と設計の理由の正本 = conventions/machine-route-first.md#sso-session-recovery。

    class Site(CookieSession):
        label = "Site"                      # 出力の接頭辞
        stamp_cookie = "JSESSIONID"         # 入り直しの合図として時刻を見る cookie (host_key = self.host)
        entry_path = "/app/"                # 入り直させる時に tab で開く所
        alive_path = "/app/portal"          # 受け入れを確かめる GET の先 (redirect は辿らない、 軽い所)
        close_path = "/app"                 # 自分の tab を閉じてよい場所の prefix
        def cookie_domains(self): ...       # 読む cookie の domain (既定 = host だけ。 IdP のものは読まない)
        def expired(self, code, location, text): ...   # HTTP 応答が切れなら理由、 でなければ None
        def inside(self, url): ...          # tab の行き先 (query なしの URL) がサイトの中か

約束:
  - **入り直せた = 読み直した cookie を server が受け入れた時だけ**。 cookie DB の時刻の変化は合図に過ぎない:
    ログイン画面や未ログインの入口そのものが未認証の session cookie を配るサイトがある (実測 2 サイト) = 時刻だけで
    決めると、 IdP が切れていても「入り直せた」 になって撃ち直しが失敗し、 本人のログインが要ることも言えない
    (conventions/garoon.md#login-page-mints-session-cookie)。
  - 未認証の cookie を掴んだ後は、 DB が変わらなくても 5 → 10 → 15 秒の間隔で確かめ直す (SAML の完了で同じ cookie が
    認証済みになるサイトでは、 DB はもう変わらない)。
  - 復帰は process ごとに 1 回。 browser に触る (tab を開く・閉じる) のは refresh が keep|close の時だけ。
  - cookie・ticket の値は出力しない (trace も時刻と query を落とした URL だけ)。

診断 (手で追った切り分けを道具にしたもの):
  - trace=True (client の --trace) = 復帰の途中の tab の行き先・cookie DB の変化・受け入れの確認を秒つきで出す
  - probe_anonymous() (client の probe) = cookie なし・偽の session id で撃ち、 302 の行き先・Set-Cookie の名前・
    expired() の判定を並べる = **切れ方を採取してから expired() を書く / 判定の穴を探す**
  - doctor() = cookie を復号できるか + 復号した値が壊れていないか (network なし。 復号「できた」 だけでは鍵や
    暗号形式の変化で値が化けていても通ってしまう)

分けた理由: 同じ入り直しの処理が client ごとに写されていて、 同じ誤り (cookie の時刻の変化を入り直しと読む) が
2 か所にあった。 ここ 1 か所に置けば、 次の SSO サイトの client も直した形で始まる。

`python3 sso_cookie_session.py` (直接実行) = selftest (偽の tab・時計・cookie DB・server。 browser・network なし)。
"""
from __future__ import annotations

import importlib.util
import platform
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    from .browser_tab import BROWSER_APPS, POLL_S, BrowserTab, watch
except ImportError:  # 直接実行 (selftest)
    from browser_tab import BROWSER_APPS, POLL_S, BrowserTab, watch

EX_LOGIN = 75  # exit code (EX_TEMPFAIL): 本人のログインが要る
_COOKIES_PY = Path(__file__).resolve().parent.parent / "chromium-cookies.py"


class LoginRequired(Exception):
    """login 切れから復帰できなかった。 observed=True なら、 ログイン画面で止まるのを見た (= 本人の操作が要る)。"""

    def __init__(self, why, observed=False):
        super().__init__(why)
        self.why, self.observed = why, observed


def chromium_cookies():
    """../chromium-cookies.py を module として読む (file 名に hyphen があるので importlib)。"""
    spec = importlib.util.spec_from_file_location("chromium_cookies", _COOKIES_PY)
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    return cc


class CookieSession:
    label = "site"
    stamp_cookie = "JSESSIONID"
    entry_path = "/"
    alive_path = "/"
    close_path = "/"
    default_headers = {"User-Agent": "Mozilla/5.0"}

    def __init__(self, base, browser="brave", profile="Default", refresh="off", wait_login=0, trace=False):
        self.base = base.rstrip("/")
        self.host = urlparse(self.base).hostname
        self.browser, self.profile = browser, profile
        self.refresh, self.wait_login, self.trace = refresh, wait_login, trace
        import requests  # doctor / selftest は network を使わないので、 ここまで読み込まない
        self.s = requests.Session()
        self.h = dict(self.default_headers)
        self._recovered = False
        self.recovered_by = None  # None / "reload" / "refresh" (status の表示用)
        self._clock, self._sleep = time.time, time.sleep  # selftest が偽の時計に差し替える
        self._probe_gap, self._next_probe = 0, 0.0  # 未認証の cookie を掴んだ後の確かめ直しの間隔 (_renewed)
        self._t0 = None
        self._load()

    # ── subclass が与えるもの ──
    def cookie_domains(self):
        return [self.host]

    def expired(self, code, location, text):
        raise NotImplementedError

    def inside(self, url):
        raise NotImplementedError

    def on_load(self):
        """cookie を読み直した後に捨てるもの (csrf ticket 等) があれば subclass で。"""

    # ── 出力 ──
    def say(self, msg):
        print(f"{self.label}: {msg}", file=sys.stderr, flush=True)

    def _trace(self, msg):
        if self.trace:
            t = self._clock() - self._t0 if self._t0 is not None else 0.0
            self.say(f"[trace {t:5.1f}s] {msg}")

    # ── cookie ──
    def _stamp(self):
        """browser の cookie DB にある stamp_cookie の (作成, 更新) 時刻 (値は読まない)。 読めなければ None。"""
        db = Path(chromium_cookies().BROWSERS[self.browser][0]).expanduser() / self.profile / "Cookies"
        try:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "c.db"
                shutil.copy(db, p)
                con = sqlite3.connect(p)
                try:
                    return con.execute("select max(creation_utc), max(last_update_utc) from cookies "
                                       "where host_key = ? and name = ?", (self.host, self.stamp_cookie)).fetchone()
                finally:
                    con.close()
        except Exception:  # noqa: BLE001
            return None

    def _stamp_changed(self):
        """cookie DB の stamp_cookie が、 手元に読んだ時から変わったか (一時的に読めないのは「変わった」 に数えない)。"""
        now = self._stamp()
        return now is not None and now != self._loaded_stamp

    def _load(self):
        """cookie を browser から読み直す。 時刻を先に読む (= 逆順だと、 間に挟まった更新を見落とす)。"""
        self._loaded_stamp = self._stamp()
        self.s.cookies.clear()
        self.s.cookies.update(chromium_cookies().load_cookies(self.browser, self.cookie_domains(), self.profile))
        self.on_load()

    # ── 受け入れの確認と入り直し ──
    def _verdict(self, r):
        return self.expired(r.status_code, r.headers.get("Location", ""), r.text)

    def _alive(self):
        """手元の cookie を server が受け入れるか (alive_path を GET 1 本、 redirect は辿らない)。"""
        r = self.s.get(self.base + self.alive_path, headers=self.h, timeout=30, allow_redirects=False)
        why = self._verdict(r)
        self._trace(f"受け入れの確認 GET {urlparse(self.alive_path).path} → {r.status_code} ({why or '受け入れた'})")
        return not why

    def _renewed(self):
        """watch に渡す「入り直せたか」。 cookie DB が変わったら読み直し、 **server が受け入れた時だけ** True。
        受け入れられなければ、 読み直した時刻を新しい基準にして見続ける (ログイン画面で止まるのを見届ける /
        SAML の完了を待つ)。 未認証の cookie を掴んだ後は DB が変わらなくても間隔を空けて確かめ直す (module の約束)。"""
        if self._stamp_changed():
            self._trace(f"cookie DB の {self.stamp_cookie} が変わった → 読み直して確かめる")
            self._sleep(2)  # 同じ書き出しで他の cookie も揃うのを待つ
            self._load()
        elif not self._probe_gap or self._clock() < self._next_probe:
            return False
        if self._alive():
            return True
        if not self._probe_gap:
            self.say("cookie は変わったがまだ受け入れられない (ログインの途中の未認証の cookie) → tab の行き先を見続ける")
        self._probe_gap = min(15, self._probe_gap + 5)
        self._next_probe = self._clock() + self._probe_gap
        return False

    def _open_tab(self, why):
        """起動中の browser に裏で tab を開かせる。 開かなければ None。"""
        app = BROWSER_APPS.get(self.browser)
        if self.refresh == "off" or not app or platform.system() != "Darwin" or not BrowserTab.running(app):
            return None
        self.say(f"session 切れ ({why}) → 起動中の {app} に裏で開かせて入り直す")
        tab = BrowserTab(app)
        tab.open(self.base + self.entry_path)
        return tab

    def _where_traced(self, where):
        last = [object()]

        def w():
            at = where()
            if at != last[0]:
                self._trace(f"tab: {at}")
                last[0] = at
            return at
        return w

    def _recover(self, why):
        """login 切れからの復帰 (process ごとに 1 回)。 入り直せた = 読み直した cookie を server が受け入れた時だけ True。"""
        if self._recovered:
            return False
        self._recovered = True
        self._t0 = self._clock()
        self._trace(f"切れ ({why}) を見た")
        if self._stamp_changed():  # browser はもう入り直していて、 手元が古いだけ
            self._load()
            if self._alive():
                self.recovered_by = "reload"
                return True
        tab = self._open_tab(why)
        if not tab and not self.wait_login:
            return False
        self._probe_gap, self._next_probe = 0, 0.0
        where = tab.where if tab else (lambda: None)
        end, saw_login, at = watch(self._where_traced(where) if self.trace else where, self._renewed, self.inside,
                                   self.wait_login, clock=self._clock, sleep=self._sleep, say=self.say)
        self._trace(f"結末 = {end} (ログイン画面を見た = {saw_login})")
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
            tab.close(self.base + self.close_path)  # 本人がログインに使った tab は本人のものなので閉じない
        self.say(f"入り直した ({self._clock() - self._t0:.0f} 秒)")
        self.recovered_by = "refresh"
        return True

    def _request(self, method, path, allow_redirects=False, **kw):
        headers, timeout = kw.pop("headers", self.h), kw.pop("timeout", 60)

        def send():
            r = self.s.request(method, self.base + path, headers=headers, timeout=timeout,
                               allow_redirects=allow_redirects, **kw)
            return r, self._verdict(r)

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


def doctor(label, browser, profile, domains):
    """script 経路の配線だけを見る (= browser の cookie を復号できて、 値が壊れていないか)。 network なし。 健全・対象外なら []。

    ログインが切れているかは見ない: 切れは配線の故障ではなく通常の周期で、 読む用事がある時に復帰を試せば足りる
    (= 切れを常時の警告にすると、 大半の時間出続けて誰も読まなくなる)。
    """
    if platform.system() != "Darwin":
        return []
    try:
        cc = chromium_cookies()
        if not (Path(cc.BROWSERS[browser][0]).expanduser() / profile / "Cookies").exists():
            return []  # この機械はこの経路の対象外
        bad = sorted({name for name, _host, _n, ok in cc.cookie_health(browser, domains, profile) if not ok})
    except SystemExit as e:
        first = (str(e).splitlines() or [""])[0][:80]
        return [f"🟠 {label} script 経路: browser の cookie を復号できない ({first}) = 対話 session で 1 回実行して Keychain を許可"]
    except Exception as e:  # noqa: BLE001
        return [f"🟠 {label} script 経路: browser の cookie を読めない ({type(e).__name__})"]
    if bad:
        return [f"🟠 {label} script 経路: cookie は復号できたが値が壊れている ({', '.join(bad)}) = 鍵か暗号の形式が変わった疑い "
                f"(確かめる = python3 chromium-cookies.py --check --domain <domain>)"]
    return []


def probe_anonymous(base, paths, verdict, cookie_name="JSESSIONID"):
    """cookie なし・偽の session id で各 path を 1 本ずつ撃ち、 切れの応答の形を返す (redirect は辿らない)。

    → [{path, sent, status, to (host + path、 query なし), set_cookie (名前だけ), verdict (expired() の判定)}]。
    未ログインの応答なので verdict が None なら「公開の頁」 か「判定の穴」 (どちらかは人が読む)。 set_cookie に
    cookie_name があれば、 そのサイトは未ログインの入口で session cookie を配る = cookie DB の変化は入り直しの証拠にならない。
    """
    import requests
    host = urlparse(base).hostname
    out = []
    for path in paths:
        for sent, jar in (("cookie なし", {}), (f"偽の {cookie_name}", {cookie_name: secrets.token_hex(16).upper()})):
            s = requests.Session()
            for k, v in jar.items():
                s.cookies.set(k, v, domain=host)
            r = s.get(base.rstrip("/") + path, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, allow_redirects=False)
            loc = urlparse(r.headers.get("Location", ""))
            raw = r.raw.headers.getlist("Set-Cookie") if hasattr(r.raw.headers, "getlist") else []
            out.append({"path": urlparse(path).path, "sent": sent, "status": r.status_code,
                        "to": (loc.hostname or "") + loc.path, "set_cookie": sorted({c.split("=", 1)[0] for c in raw}),
                        "verdict": verdict(r.status_code, r.headers.get("Location", ""), r.text)})
    return out


def print_probe(rows, cookie_name="JSESSIONID"):
    for x in rows:
        print(f"{x['path']} [{x['sent']}] {x['status']}" + (f" → {x['to']}" if x["to"] else "")
              + f" | Set-Cookie: {', '.join(x['set_cookie']) or '-'} | expired() = {x['verdict']}")
    if any(cookie_name in x["set_cookie"] for x in rows):
        print(f"⚠️ 未ログインの応答が {cookie_name} を配る = cookie DB の変化は入り直しの証拠にならない (受け入れを GET で確かめる)")
    if any(x["verdict"] is None for x in rows):
        print("⚠️ expired() = None の行がある = 公開の頁か、 切れの判定の穴 (未ログインの応答なのに「読める」 と判定する)")


# ── selftest ──

def fake_recover(cls, base, tab_script, stamp_changes, alive_from, wait_login=0, local_stale=False):
    """偽の tab (行き先の台本、 1 poll に 1 つ) ・時計・cookie DB (stamp_cookie が変わる時刻の list) ・server (その時刻
    から cookie を受け入れる、 None = 受け入れない) で cls の _recover を回す。 inside() / expired() は cls の本物を使う。
    → (結末, tab を開いたか, 自分の tab を閉じたか, 経過秒)。 結末 = "reload" / "refresh" / "failed" / "login" / "login-observed"。"""
    t, opened, closed, said = [0.0], [], [], []

    class Tab:
        def where(self):
            return tab_script[min(int(t[0] / POLL_S), len(tab_script) - 1)]

        def close(self, prefix):
            closed.append(prefix)
            return True

    obj = cls.__new__(cls)  # network と browser に触る __init__ を通さない
    obj.base, obj.host = base, urlparse(base).hostname
    obj.browser, obj.profile, obj.refresh, obj.wait_login, obj.trace = "brave", "Default", "close", wait_login, False
    obj._recovered, obj.recovered_by, obj._t0 = False, None, None
    obj._clock, obj._sleep = (lambda: t[0]), (lambda s: t.__setitem__(0, t[0] + s))
    obj._probe_gap, obj._next_probe = 0, 0.0
    obj._stamp = lambda: sum(1 for c in stamp_changes if t[0] >= c)
    obj._load = lambda: setattr(obj, "_loaded_stamp", obj._stamp())
    obj._alive = lambda: alive_from is not None and t[0] >= alive_from
    obj._open_tab = lambda why: opened.append(why) or Tab()
    obj.say = said.append
    obj._loaded_stamp = -1 if local_stale else obj._stamp()
    try:
        end = obj.recovered_by if obj._recover("login redirect") else "failed"
    except LoginRequired as e:
        end = "login-observed" if e.observed else "login"
    return end, bool(opened), bool(closed), t[0]


def site_selftest_cases(cls, base, entry, login, idp, back):
    """subclass の inside() を本物の URL の形で通す入り直しの 4 場面。 entry = 開かせた直後 (読み込み中) /
    login = サイト自身のログイン入口 / idp = IdP のログイン画面 / back = 入り直した後のサイトの中 (読み込み完了)。"""
    return [
        # 実測: ログイン入口が配る未認証の session cookie で cookie DB が変わる → 旧版は「入り直した」 と言って撃ち直し、
        # 失敗して「復帰できなかった」 (本人のログインが要ることを言えない) で止まっていた
        (f"{cls.label}: IdP が切れている → 入口が配った cookie を入り直しと読まず、 本人のログインが要ると言う",
         fake_recover(cls, base, [entry, login, idp], [3], None)[0] == "login-observed"),
        (f"{cls.label}: IdP が生きていて cookie DB が先に変わった → 確かめ直しで入り直し、 自分の tab を閉じる",
         (lambda r: r[0] == "refresh" and r[2] and r[3] <= 15)(fake_recover(cls, base, [entry, login, back], [3], 6))),
        (f"{cls.label}: wait-login = 本人がログインし終えたら入り直す (ログインに使った tab は閉じない)",
         (lambda r: r[0] == "refresh" and not r[2] and r[3] <= 80)(
             fake_recover(cls, base, [entry, login] + [idp] * 40 + [back], [3], 63, wait_login=300))),
        (f"{cls.label}: tab が中に着いても server が cookie を受け入れない → 入り直したと言わない",
         fake_recover(cls, base, [entry, back], [], None)[0] == "failed"),
    ]


class _Demo(CookieSession):
    label = "demo"

    def expired(self, code, location, text):
        return "login redirect" if code == 302 and urlparse(location).path.endswith("/login") else None

    def inside(self, url):
        u = urlparse(url)
        return u.scheme == "https" and u.hostname == self.host and not u.path.endswith("/login")


def selftest_cases():
    """[(名前, 通ったか)]。 呼び元の --selftest に混ぜられるように list で返す。"""
    b = "https://app.example"
    entry, login = ("https://app.example/app/", True), ("https://app.example/login", False)
    idp, asr = ("https://idp.example/auth/session", False), ("https://idp.example/auth/saml2/x/assertions", False)
    back = ("https://app.example/app/portal", False)
    return site_selftest_cases(_Demo, b, entry, login, idp, back) + [
        ("普通の入り直し (cookie DB が SAML の後に変わる) → すぐ入り直す",
         (lambda r: r[0] == "refresh" and r[2] and r[3] <= 8)(fake_recover(_Demo, b, [entry, asr, back], [4], 3))),
        ("手元の cookie が古いだけ (browser は入り直し済み) → tab を開かずに読み直す",
         fake_recover(_Demo, b, [back], [], 0, local_stale=True)[:2] == ("reload", False)),
        ("復帰は process ごとに 1 回", (lambda o: (o.__setattr__("_recovered", True), o._recover("x"))[1] is False)(
            _Demo.__new__(_Demo))),
        ("print_probe は値でなく名前だけ・未認証 cookie と判定の穴を言う", _probe_output_ok()),
    ]


def _probe_output_ok():
    import contextlib
    import io
    rows = [{"path": "/app/", "sent": "cookie なし", "status": 302, "to": "app.example/login",
             "set_cookie": ["JSESSIONID"], "verdict": "login redirect"},
            {"path": "/app/portal", "sent": "偽の JSESSIONID", "status": 302, "to": "app.example/app/sso",
             "set_cookie": [], "verdict": None}]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_probe(rows)
    out = buf.getvalue()
    return "未ログインの応答が JSESSIONID を配る" in out and "判定の穴" in out and out.count("\n") == 4


if __name__ == "__main__":  # 直接実行 = selftest (scripts/lib の module の流儀。 run-all-checks が引数なしで呼ぶ)
    ok = True
    for name, good in selftest_cases():
        ok &= bool(good)
        print("PASS" if good else "FAIL", name)
    print("selftest", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
