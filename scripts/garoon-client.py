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
  - login 切れの判定 = 302 → ex-tic / 200 + `<title>ログイン` → 「browser で再 login」 と言う (script は代行しない)。

⚠️ 出力に cookie / ticket を出さない。 取得した掲示本文・file は組織の内部情報 = private 層にしか置かない。
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent


def _cookies(browser, profile, org):
    spec = importlib.util.spec_from_file_location("cc", HERE / "chromium-cookies.py")
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    return cc.load_cookies(browser, ["cybozu.com", "ex-tic.com"], profile)


class Garoon:
    def __init__(self, org, browser="brave", profile="Default"):
        self.base = f"https://{org}.cybozu.com"
        self.s = requests.Session()
        self.s.cookies.update(_cookies(browser, profile, org))
        self.h = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
        self._csrf = None

    def _check(self, r):
        if r.status_code in (301, 302) and "ex-tic" in r.headers.get("Location", ""):
            raise SystemExit("Garoon session 切れ (SSO redirect) → browser で Garoon を開いて再 login してから再実行")
        if r.status_code == 200 and "<title>ログイン" in r.text[:2000]:
            raise SystemExit("Garoon session 切れ (login page) → browser で再 login")
        return r

    def get(self, path, **kw):
        return self._check(self.s.get(self.base + path, headers=self.h, timeout=60, allow_redirects=False, **kw))

    @property
    def csrf(self):
        if not self._csrf:
            t = self._check(self.s.get(self.base + "/g/cabinet/search.csp", params={"text": "x"},
                                       headers=self.h, timeout=60, allow_redirects=True)).text
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
        r = self.s.post(self.base + "/g/fts/api/search", params={"csrf_ticket": self.csrf},
                        data=json.dumps(body), headers={**self.h, "Content-Type": "application/json"}, timeout=90)
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--org", default=os.environ.get("GAROON_ORG"), help="cybozu.com subdomain (env GAROON_ORG)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--profile", default="Default")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap.add_argument("--json", action="store_true", help="raw JSON を出す (subcommand の前に置く)")
    p = sub.add_parser("search"); p.add_argument("keyword"); p.add_argument("--app", default="bulletin"); p.add_argument("--start", type=int, default=0)
    sub.add_parser("bulletin-categories")
    p = sub.add_parser("bulletin-topics"); p.add_argument("category_id")
    p = sub.add_parser("bulletin-topic"); p.add_argument("topic_id")
    p = sub.add_parser("download"); p.add_argument("fid"); p.add_argument("--app", default="bulletin"); p.add_argument("--out", required=True)
    p = sub.add_parser("get"); p.add_argument("path")
    a = ap.parse_args()
    if not a.org:
        raise SystemExit("--org か env GAROON_ORG が要る (= 組織 subdomain、 private 層の環境 doc 参照)")
    g = Garoon(a.org, a.browser, a.profile)
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
