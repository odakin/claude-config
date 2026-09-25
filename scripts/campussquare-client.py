#!/usr/bin/env python3
"""campussquare-client.py — 大学の教務システム CampusSquare for WEB を **browser session cookie で script から読む** (画面 drive 不要)。

背景: 学内 SSO (Shibboleth SP + 外部 IdP) の奥にあり、 user が発行できる API credential が無い。 残る機械経路 =
user が browser でログイン済みの session cookie を再利用する (= `chromium-cookies.py`)。 形は `garoon-client.py`
と同じ (切れ判定 → 起動中の browser に裏で入り直させる → 1 回だけ撃ち直す)。 入り直しの部品 = scripts/lib/sso_cookie_session.py
(入り直せた = 読み直した cookie を server が受け入れた時だけ)、 一般則 = conventions/machine-route-first.md#sso-session-recovery。
script はパスワードも OTP も扱わない。

subcommand:
  syllabus-search [--year Y] [--code C] [--name 科目名] [--teacher 教員名] [--word 語]   シラバス検索 (一覧)
  syllabus <時間割番号> [--year Y] [--html]                                           シラバス 1 件の本文 (text)
  roster-csv --out-dir DIR [--year Y] [--exam 1]                                      全担当科目の履修者名簿 CSV を DIR に保存 (成績登録画面の CSV 一括ダウンロード)
  get <path>                                                                         任意 path を GET (debug 用)
  status                                                                             いま読めるか (GET 1 本、 切れていれば復帰を試す)
  doctor                                                                             配線だけ (cookie を復号できて値が壊れていないか。 network なし、 健全なら無言)
  probe [path ...]                                                                   切れ方の採取 (cookie なし・偽の session id で撃ち、 302 の行き先・Set-Cookie の名前・切れ判定を並べる)

共通 option: --base https://<host> (env CAMPUSSQUARE_BASE)  --browser brave|chrome  --profile Default
             --browser-refresh off|keep|close (env CAMPUSSQUARE_BROWSER_REFRESH)  --wait-login 秒  --trace

画面の仕組み (Spring Web Flow・シラバス検索の form・教員ログイン時の担当者欄の罠・CSV の形式) = conventions/campussquare.md。
切れの判定 = 3xx で別 host (IdP) / `Shibboleth.sso` / `login` か `ssologin` の path へ、 または 200 でログイン画面か「認証エラー」 の title。
  未ログインの portal は ssologin.do への 302 と一緒に未認証の JSESSIONID を配る (実測、 `probe` で見える)。
  ⚠️ CampusSquare 本体の timeout 画面の形は未実測 (出たら expired() に足して selftest に回帰を足す)。

⚠️ 出力に cookie / flow key を出さない。 取得した学生情報 (名簿・成績) は private 層にしか置かない。 書き込み (成績登録等) は射程外。
"""
import argparse
import html as htmllib
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.browser_tab import BROWSER_APPS, selftest_cases as _tab_selftest_cases  # noqa: E402
from lib.sso_cookie_session import (  # noqa: E402
    EX_LOGIN, CookieSession, LoginRequired, doctor as _doctor, print_probe, probe_anonymous,
    selftest_cases as _session_selftest_cases, site_selftest_cases)

CTX = "/campusweb"
PORTAL = CTX + "/campusportal.do?page=main"
FLOW = CTX + "/campussquare.do"
SYLLABUS_FLOW = "SYW0001000-flow"
GRADE_FLOW = "SIW0001000-flow"  # 成績登録 / 履修者名簿ダウンロード
PROBE_PATHS = [PORTAL, f"{FLOW}?_flowId={SYLLABUS_FLOW}"]


def _say(msg):
    print(f"CampusSquare: {msg}", file=sys.stderr, flush=True)


def expired(code, location, text, base_host):
    """HTTP 応答が「ログイン切れ」 なら理由、 そうでなければ None。"""
    if code in (301, 302, 303, 307):
        u = urlparse(location)
        if u.hostname and u.hostname != base_host:
            return "SSO redirect"
        # 未ログインの portal は同じ host の ssologin.do へ 302 (実測) = /login だけを見ると「読める」 と誤る
        if "Shibboleth.sso" in u.path or re.search(r"/(sso)?login\b", u.path, re.I):
            return "login redirect"
    if code == 200 and re.search(r"<title>[^<]*(ログイン|Login)", (text or "")[:3000], re.I):
        return "login page"
    # session 切れの flow は 200 で「認証エラー」 画面 (form authorizationError) を返す (2026-09-19 実測)
    if code == 200 and re.search(r'<title>\s*認証エラー|<form[^>]*name="authorizationError"', (text or "")[:3000]):
        return "auth error page"
    if code in (401, 403):
        return str(code)
    return None


def inside(url, base_host):
    u = urlparse(url)
    return u.scheme == "https" and u.hostname == base_host and u.path.startswith(CTX) and "Shibboleth.sso" not in u.path


def html_to_text(page):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(tr|p|div|h\d|li)>", "\n", t, flags=re.I)
    t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "", t))
    return "\n".join(line.strip() for line in t.splitlines() if line.strip() and line.strip() != "|")


def form_fields(page, form_name):
    """name=form_name の form の hidden/text input を {name: value} で返す (select は value="" 扱い)。"""
    m = re.search(r'<form[^>]*name="%s"[^>]*>(.*?)</form>' % re.escape(form_name), page, re.S)
    if not m:
        raise SystemExit(f"form {form_name} が見つからない (= 画面構造の変化か未ログイン)")
    out = {}
    for tag in re.findall(r"<input[^>]*>", m.group(1)):
        n = re.search(r'name="([^"]+)"', tag)
        if n and not re.search(r'type="(button|reset|submit)"', tag):
            v = re.search(r'value="([^"]*)"', tag)
            out[n.group(1)] = htmllib.unescape(v.group(1)) if v else ""
    return out


def result_rows(page):
    """検索結果の表 → [{cells:[...], refer:(年度, 所属, 番号, locale) | None}]。"""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [htmllib.unescape(re.sub(r"<[^>]+>|\s+", " ", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        ref = re.search(r"refer\('(\d+)','([^']*)','([^']+)','([^']+)'\)", tr)
        if cells and ref:
            rows.append({"cells": cells, "refer": ref.groups()})
    return rows


class CampusSquare(CookieSession):
    label = "CampusSquare"
    entry_path = PORTAL
    alive_path = PORTAL  # 生きていれば 200 の portal、 切れていれば ssologin.do への 302
    close_path = CTX

    def expired(self, code, location, text):
        return expired(code, location, text, self.host)

    def inside(self, url):
        return inside(url, self.host)

    def _follow(self, r):
        """flow 内の 302 (同じ host。 別 host なら _request が切れとして先に捕まえている) を追って画面 HTML にする。"""
        for _ in range(4):
            if r.status_code not in (301, 302, 303):
                break
            r = self._request("GET", urlparse(r.headers["Location"])._replace(scheme="", netloc="").geturl())
        if r.status_code != 200:
            raise SystemExit(f"{r.request.method} {urlparse(r.url).path} {r.status_code}")
        return r.text

    def open_flow(self, flow_id):
        """flow を開始して最初の画面 HTML を返す。"""
        return self._follow(self._request("GET", f"{FLOW}?_flowId={flow_id}"))

    def post_flow(self, data):
        """form を POST して次の画面 HTML を返す (Web Flow は POST → 302 → GET で画面を返す)。"""
        return self._follow(self._request("POST", FLOW, data=data))

    def syllabus_search(self, year, code="", name="", teacher="", word=""):
        page = self.open_flow(SYLLABUS_FLOW)
        f = form_fields(page, "SearchForm")
        f.update({"_eventId": "search", "nendo": str(year), "kaikoKubunCode": "", "kyokannm": teacher,
                  "kaikoKamokunm": name, "jikanwaricd": code, "yobi": "", "jigen": "", "freeWord": word,
                  "_displayCount": "200"})
        page = self.post_flow(f)
        return page, result_rows(page)

    def syllabus(self, year, code):
        page, rows = self.syllabus_search(year, code=code)
        hits = [r for r in rows if r["refer"][2] == code]
        if not hits:
            raise SystemExit(f"{year} 年度の時間割番号 {code} が検索で見つからない")
        y, shozoku, jcd, locale = hits[0]["refer"]
        f = form_fields(page, "ReferForm")
        f.update({"_eventId": "input", "nendo": y, "jikanwariShozokuCode": shozoku, "jikanwaricd": jcd, "locale": locale})
        return self.post_flow(f)

    def roster_csv(self, year, exam="1"):
        """成績登録画面の「CSV一括ダウンロード」 = 全担当科目の履修者名簿 (bytes は CP932 のまま)。 読むだけ。
        画面の downloadAllCsv(年度, 試験区分) と同じ POST。 年度・学期は画面が開いた時点の学期で決まる。"""
        page = self.open_flow(GRADE_FLOW)
        f = form_fields(page, "downloadForm")
        f.update({"_eventId": "outputCsvAll", "nendo": str(year), "shikenKbnCd": exam})
        r = self._request("POST", FLOW, data=f)
        for _ in range(4):
            if r.status_code not in (301, 302, 303):
                break
            r = self._request("GET", urlparse(r.headers["Location"])._replace(scheme="", netloc="").geturl())
        disp = r.headers.get("Content-Disposition", "")
        if r.status_code != 200 or "csv" not in (r.headers.get("Content-Type", "") + disp).lower():
            title = re.search(r"<title>(.*?)</title>", r.text, re.S)
            raise SystemExit(f"名簿 CSV が返らなかった ({r.status_code} {title.group(1).strip() if title else ''})")
        name = re.search(r'filename="?([^";]+)', disp)
        return r.content, (name.group(1) if name else f"regis{time.strftime('%Y%m%d')}.csv")


def doctor(browser, profile, base):
    """script 経路の配線だけを見る (cookie を復号できて値が壊れていないか)。 network なし。 健全・対象外なら []。"""
    if not base:
        return []
    return _doctor("CampusSquare", browser, profile, [urlparse(base).hostname])


def selftest():
    host = "cs.example.ac.jp"
    cases = [
        ((302, "https://idp.example.com/auth/saml2/x?SAMLRequest=z", ""), "SSO redirect"),
        ((302, "https://cs.example.ac.jp/Shibboleth.sso/Login?target=x", ""), "login redirect"),
        ((302, "/campusweb/login.do", ""), "login redirect"),
        ((302, "/campusweb/ssologin.do", ""), "login redirect"),
        ((200, "", "<html><head><title>ログイン</title>"), "login page"),
        ((200, "", '<title>認証エラー</title><form name="authorizationError" method="post">'), "auth error page"),
        ((302, "/campusweb/campussquare.do?_flowExecutionKey=_cX_kY", ""), None),
        ((200, "", "<title>CampusSquare for WEB</title>"), None),
    ]
    ok = True
    for (code, loc, text), want in cases:
        got = expired(code, loc, text, host)
        ok &= got == want
        print("PASS" if got == want else "FAIL", code, loc[:40], "->", got)
    page = ('<form name="ReferForm" action="/campusweb/campussquare.do"><input type="hidden" name="_flowExecutionKey" '
            'value="_cA_kB"><input type="hidden" name="_eventId" value="input"><input type="hidden" name="secchikbncd">'
            '</form><table><tr><td>1</td><td>学科</td><td>後期</td><td>金2</td><td>123456</td><td>科目&amp;名</td><td>'
            '<a onclick="refer(\'2026\',\'99\',\'123456\',\'ja_JP\');">参照</a></td></tr></table>')
    rows = result_rows(page)
    b = "https://cs.example.ac.jp"
    checks = _tab_selftest_cases() + _session_selftest_cases() + site_selftest_cases(
        CampusSquare, b, entry=(b + "/campusweb/campusportal.do", True), login=(b + "/campusweb/ssologin.do", False),
        idp=("https://idp.example.com/auth/session", False), back=(b + "/campusweb/campusportal.do", False)) + [
        ("form_fields: hidden と値なし hidden を拾う", form_fields(page, "ReferForm") ==
         {"_flowExecutionKey": "_cA_kB", "_eventId": "input", "secchikbncd": ""}),
        ("result_rows: refer の引数と entity 解決", len(rows) == 1 and rows[0]["refer"] == ("2026", "99", "123456", "ja_JP")
         and "科目&名" in rows[0]["cells"]),
        ("inside: 別 host・Shibboleth・context 外は外", inside("https://cs.example.ac.jp/campusweb/x.do", host)
         and not inside("https://cs.example.ac.jp/Shibboleth.sso/SAML2/POST", host)
         and not inside("https://idp.example.com/campusweb/", host) and not inside("https://cs.example.ac.jp/", host)),
    ]
    for name, good in checks:
        ok &= bool(good)
        print("PASS" if good else "FAIL", name)
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default=os.environ.get("CAMPUSSQUARE_BASE"), help="https://<host> (env CAMPUSSQUARE_BASE)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--profile", default="Default")
    ap.add_argument("--browser-refresh", choices=("off", "keep", "close"),
                    default=os.environ.get("CAMPUSSQUARE_BROWSER_REFRESH", "off"))
    ap.add_argument("--wait-login", type=int, default=0, metavar="秒")
    ap.add_argument("--trace", action="store_true",
                    help="入り直しの途中の tab の行き先・cookie DB の変化・受け入れの確認を秒つきで stderr に出す (値は出さない)")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("syllabus-search")
    p.add_argument("--year", default=time.strftime("%Y")); p.add_argument("--code", default="")
    p.add_argument("--name", default=""); p.add_argument("--teacher", default=""); p.add_argument("--word", default="")
    p = sub.add_parser("syllabus"); p.add_argument("code"); p.add_argument("--year", default=time.strftime("%Y"))
    p.add_argument("--html", action="store_true")
    p = sub.add_parser("roster-csv"); p.add_argument("--year", default=time.strftime("%Y"))
    p.add_argument("--exam", default="1", help="試験区分 (画面の既定 = 1)")
    p.add_argument("--out-dir", required=True, help="保存先 dir (file 名は server が付ける regisYYYYMMDD.csv)")
    p = sub.add_parser("get"); p.add_argument("path")
    sub.add_parser("status")
    sub.add_parser("doctor")
    p = sub.add_parser("probe", help="切れ方の採取 (cookie を使わない)")
    p.add_argument("paths", nargs="*", help=f"既定 = {' '.join(PROBE_PATHS)}")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.cmd:
        ap.error("subcommand が要る")
    if a.cmd == "doctor":
        for line in doctor(a.browser, a.profile, a.base):
            print(line)
        return
    if not a.base:
        raise SystemExit("--base か env CAMPUSSQUARE_BASE が要る (= 組織の host、 private 層の入口 script が与える)")
    if a.cmd == "probe":  # browser の cookie を使わない = CampusSquare() を作らない
        host = urlparse(a.base).hostname
        print_probe(probe_anonymous(a.base, a.paths or PROBE_PATHS, lambda c, l, t: expired(c, l, t, host)))
        return
    try:
        cs = CampusSquare(a.base, a.browser, a.profile, refresh=a.browser_refresh, wait_login=a.wait_login, trace=a.trace)
        run(a, cs)
    except LoginRequired as e:
        app = BROWSER_APPS.get(a.browser, a.browser)
        if e.observed:
            _say("学内ログインが切れている = 本人のログインが要る。 `--wait-login 600` を付けて実行し直すと、 "
                 f"{app} にログイン画面を開いたまま、 ログインし終えるのを待って続きから進む")
        else:
            _say(f"session 切れ ({e.why}) から復帰できなかった → {app} で {a.base}{PORTAL} を開いてログインしてから再実行"
                 + ("" if a.browser_refresh != "off" else " (`--browser-refresh keep|close` で browser に入り直させられる)")
                 + " / 途中を見るなら `--trace`")
        sys.exit(EX_LOGIN)


def run(a, cs):
    if a.cmd == "syllabus-search":
        _, rows = cs.syllabus_search(a.year, a.code, a.name, a.teacher, a.word)
        print(f"# {a.year} 年度 シラバス検索: {len(rows)} 件")
        for r in rows:
            print(" | ".join(c for c in r["cells"] if c))
    elif a.cmd == "syllabus":
        page = cs.syllabus(a.year, a.code)
        print(page if a.html else html_to_text(page))
    elif a.cmd == "roster-csv":
        body, name = cs.roster_csv(a.year, a.exam)
        out = Path(a.out_dir).expanduser() / Path(name).name
        if out.exists() and out.read_bytes() != body:
            out = out.with_name(f"{out.stem}-{time.strftime('%H%M%S')}{out.suffix}")  # 同じ日の取り直しは上書きしない
        out.write_bytes(body)
        rows = max(body.count(b"\n") - 1, 0)
        print(f"{out} ({len(body)} bytes, {rows} 行)")  # 中身 (個人情報) は出さない
    elif a.cmd == "get":
        print(cs._request("GET", a.path).text)
    elif a.cmd == "status":
        r = cs._request("GET", PORTAL)
        title = re.search(r"<title>(.*?)</title>", r.text, re.S)
        print(f"読める ({r.status_code} {title.group(1).strip() if title else ''})"
              + {None: "", "reload": " (cookie を読み直した)", "refresh": " (browser に入り直させた)"}[cs.recovered_by])


if __name__ == "__main__":
    main()
