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
  status                                                        いま読めるか (GET 1 本。 切れていれば下の復帰を試す)
  doctor                                                        配線だけを見る (cookie を復号できて値が壊れていないか。 network なし、 健全なら無言)
  probe [path ...]                                              切れ方の採取 (cookie なし・偽の session id で撃ち、 302 の行き先・Set-Cookie の名前・切れ判定を並べる)

共通 option: --org <subdomain> (env GAROON_ORG)  --browser brave|chrome  --profile Default
             --browser-refresh off|keep|close (env GAROON_BROWSER_REFRESH)  --wait-login 秒  --trace

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
    (cabinet 側は UI では time= 署名 token が付くが、 session 内 GET なら token なしの fid だけで 200 application/pdf
    が返る = 実測。 返らなくなったら検索結果の downloadUrl をそのまま使う)。
  - login 切れの判定 = 302 → SSO (別 host) / 302 → `<org>.cybozu.com/login` / 200 + `<title>ログイン` /
    REST の 401。 script はパスワードも OTP も扱わない。
  - ログイン画面 (/login) は開かれるたびに未認証の JSESSIONID を配る (実測、 `probe` で見える) = cookie DB の変化は
    入り直しの証拠にならない (conventions/garoon.md#login-page-mints-session-cookie)。

login 切れからの復帰 = 共通部品 scripts/lib/sso_cookie_session.py (入り直せた = 読み直した cookie を server が受け入れた
時だけ / tab の行き先で「本体だけの切れ」 と「本人のログインが要る」 を見分ける / `--wait-login` / `--trace`)。
手順 = conventions/garoon.md#garoon-session-recovery、 設計の要点 = conventions/machine-route-first.md#sso-session-recovery。
`--browser-refresh` の既定は off (= 人の browser に触る副作用は opt-in、 利用者の入口 wrapper が決める)。
⚠️ IdP の有効期間 (組織の方針) は延ばさない = 定期的に開かせる仕組みにしない。 開かせるのは読む用事がある時だけ。

⚠️ 出力に cookie / ticket を出さない。 取得した掲示本文・file は組織の内部情報 = private 層にしか置かない。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # importlib 経由で読まれた時も lib を引けるように
from lib.browser_tab import BROWSER_APPS, selftest_cases as _tab_selftest_cases  # noqa: E402
from lib.sso_cookie_session import (  # noqa: E402
    EX_LOGIN, CookieSession, LoginRequired, doctor as _doctor, print_probe, probe_anonymous,
    selftest_cases as _session_selftest_cases, site_selftest_cases)

PROBE_PATHS = ["/g/", "/g/portal/index.csp", "/g/cabinet/search.csp"]


def _say(msg):
    print(f"Garoon: {msg}", file=sys.stderr, flush=True)


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


class Garoon(CookieSession):
    label = "Garoon"
    entry_path = "/g/"
    alive_path = "/g/portal/index.csp"  # 生きていれば同じ host の中への 302 で本文なし = 軽い
    close_path = "/"
    default_headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}

    def __init__(self, org, browser="brave", profile="Default", refresh="off", wait_login=0, trace=False):
        self.org = org
        self._csrf = None
        super().__init__(f"https://{org}.cybozu.com", browser, profile, refresh, wait_login, trace)

    def cookie_domains(self):
        return ["cybozu.com"]  # org の host と .cybozu.com (IdP の cookie は読まない)

    def expired(self, code, location, text):
        return expired(code, location, text, self.host)

    def inside(self, url):
        return inside(url, self.host)

    def on_load(self):
        self._csrf = None  # cookie を読み直したら ticket も取り直す

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
            raise SystemExit(f"download fid={fid} 失敗 {r.status_code} {r.headers.get('content-type')} (cabinet は fid だけで通る実測だが、 変わったら検索結果の downloadUrl を get で)")
        Path(out).write_bytes(r.content)
        return len(r.content), r.headers.get("content-type")


def _strip(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("\n", " ")


def doctor(browser, profile):
    """script 経路の配線だけを見る (cookie を復号できて値が壊れていないか)。 network なし。 健全・対象外なら []。"""
    return _doctor("Garoon", browser, profile, ["cybozu.com"])


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

    def _parsed(argv):
        return build_parser().parse_args(argv)
    b = "https://x.cybozu.com"
    checks = _tab_selftest_cases() + _session_selftest_cases() + site_selftest_cases(
        Garoon, b, entry=(b + "/g/", True), login=(b + "/login", False),
        idp=("https://x.ex-tic.com/auth/session", False), back=(b + "/g/portal/index.csp", False)) + [
        ("--wait-login は subcommand の後ろでも効く", _parsed(["search", "k", "--wait-login", "5"]).wait_login == 5),
        ("--wait-login は subcommand の前でも効く", _parsed(["--wait-login", "7", "search", "k"]).wait_login == 7),
        ("後ろで指定しなければ前の値が残る", _parsed(["--wait-login", "7", "--json", "search", "k"]).json is True
         and _parsed(["--wait-login", "7", "search", "k"]).wait_login == 7),
        ("何も付けなければ既定値", _parsed(["status"]).wait_login == 0 and _parsed(["status"]).json is False
         and _parsed(["status"]).trace is False),
        ("--trace は subcommand の前でも後でも効く", _parsed(["--trace", "status"]).trace and _parsed(["status", "--trace"]).trace),
        ("probe は path を省けば既定の組", _parsed(["probe"]).paths == [] and _parsed(["probe", "/g/"]).paths == ["/g/"]),
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
    """引数の組み立て。 --wait-login / --browser-refresh / --json / --trace は subcommand の前でも後でも効く
    (= 後ろに付けると argparse の unrecognized arguments で落ちていた、 実測)。"""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--org", default=os.environ.get("GAROON_ORG"), help="cybozu.com subdomain (env GAROON_ORG)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--profile", default="Default")
    refresh_help = ("切れた時に起動中の browser に裏で tab を開かせて入り直すか (env GAROON_BROWSER_REFRESH)。 "
                    "keep = 開いた tab を残す / close = 入り直せたら自分が開いた tab を閉じる")
    wait_help = "本人のログインが要る時、 ログインし終えるのをこの秒数まで待って続きから進む"
    trace_help = "入り直しの途中の tab の行き先・cookie DB の変化・受け入れの確認を秒つきで stderr に出す (値は出さない)"
    ap.add_argument("--browser-refresh", choices=("off", "keep", "close"),
                    default=os.environ.get("GAROON_BROWSER_REFRESH", "off"), help=refresh_help)
    ap.add_argument("--wait-login", type=int, default=0, metavar="秒", help=wait_help)
    ap.add_argument("--trace", action="store_true", help=trace_help)
    ap.add_argument("--selftest", action="store_true", help="切れ判定と入り直しの結末判定の自己テスト (network・browser なし)")
    ap.add_argument("--json", action="store_true", help="raw JSON を出す")
    # subcommand の後ろにも同じ option を置けるようにする。 default=SUPPRESS = 後ろで指定しなかった時に前の値を消さない
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--browser-refresh", choices=("off", "keep", "close"), default=argparse.SUPPRESS, help=refresh_help)
    common.add_argument("--wait-login", type=int, default=argparse.SUPPRESS, metavar="秒", help=wait_help)
    common.add_argument("--trace", action="store_true", default=argparse.SUPPRESS, help=trace_help)
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
    p = sub.add_parser("probe", parents=[common], help="切れ方の採取 (cookie を使わない)")
    p.add_argument("paths", nargs="*", help=f"既定 = {' '.join(PROBE_PATHS)}")
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
    if a.cmd == "probe":  # browser の cookie を使わない = Garoon() を作らない
        base = f"https://{a.org}.cybozu.com"
        print_probe(probe_anonymous(base, a.paths or PROBE_PATHS, lambda c, l, t: expired(c, l, t, urlparse(base).hostname)))
        return
    try:
        run(a, Garoon(a.org, a.browser, a.profile, refresh=a.browser_refresh, wait_login=a.wait_login, trace=a.trace))
    except LoginRequired as e:
        app = BROWSER_APPS.get(a.browser, a.browser)
        if e.observed:
            _say("SSO のログインが切れている = 本人のログインが要る (ログイン画面で止まるのを見た)。 `--wait-login 600` を付けて"
                 f"実行し直すと、 {app} にログイン画面を開いたまま、 本人がログインし終えるのを待って続きから進む"
                 + ("" if a.browser_refresh == "close" else f"。 いま {app} に開いたログイン画面の tab は残してある"))
        else:
            _say(f"session 切れ ({e.why}) から復帰できなかった → {app} で https://{a.org}.cybozu.com/g/ を開いてログインしてから再実行"
                 + ("" if a.browser_refresh != "off" else " (`--browser-refresh keep|close` で browser に入り直させられる)")
                 + " / 途中を見るなら `--trace`")
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
        g.get(Garoon.alive_path)
        print("読める" + {None: "", "reload": " (cookie を読み直した)", "refresh": " (browser に入り直させた)"}[g.recovered_by])


if __name__ == "__main__":
    main()
