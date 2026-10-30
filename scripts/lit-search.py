#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""lit-search.py — 先行研究の探索を API で回す (OpenAlex の全文検索・題名と要旨の論理式・被引用・要旨、 Crossref の書誌検索、 arXiv の検索と要旨、 INSPIRE の検索)。 1 件 1 行、 --json も

WHY THIS EXISTS
---------------
文献調査で「この問いを扱った先行研究は (調べた範囲で) 無い」 と書くには、 どの DB をどのクエリで
引き、 何件当たったかを残す必要がある (不在の主張は範囲つきでしか書けない)。 Google Scholar は
機械の読み取りを断る (CAPTCHA を回避して叩かない) ので、 被引用の追跡も含めて公開 API で回す。
その場で書いた lookup の code は、 誤り応答を cache に残す・検索語と論理式を併用して件数を小さく
出す、 の 2 つで黙って結果を歪めた (実測) = 道具にして同じ罠を踏まないようにする。

WHAT IT DOES
------------
- `oa <query>`         OpenAlex の全文検索 (`search=`、 関連度順)。 ゆるい語の検索はここ
- `oa <expr> --boolean` 題名と要旨の論理式 (`filter=title_and_abstract.search:<expr>`、 引用符・AND/OR)。
                       ⚠️ 検索語 (`search=`) を併用しない = 併用すると両方に当たる件だけが残り、 件数が小さく出る
- `cites <doi|W…>`     その文献を引いている文献 (`filter=cites:`)。 Scholar の「被引用」 の代わり
- `abstract <doi>…`    OpenAlex の要旨 (`abstract_inverted_index` を語順に戻す) と OA 版の所在
- `crossref <query>`   Crossref の書誌検索 (`query.bibliographic`)。 総数は関連度の母集団なので「ヒット数」 にしない
- `arxiv <query>`      arXiv API (`search_query`、 例 `ti:"geoscience revisited"`、 `au:Deluca AND au:Corral`)。
                       `--newest` = 提出日の新しい順 (既定は関連度順 = 最近の測定を探すときは付ける)
- `arxiv-abstract <id>…` arXiv の要旨 (id は vN なしで可、 応答の id に版が付く)
- `inspire <query>`    INSPIRE の検索 (`t …`、 `abstracts.value:"…"`、 `date > 2026-01-01` など)、 新しい順
- 各行 = 年 | DOI か id | 題 | 誌名 | 被引用数。 先頭行に API の総数 (OpenAlex の `meta.count` 等)
- `--log <file>` に 1 リクエスト 1 行 (時刻・HTTP status・URL) を追記 = 検索ログの再現の根拠
- `--cache-dir <dir>` で応答を保存 (同じ URL は引き直さない)。 **誤り応答 (4xx/5xx) は保存しない**

WHAT IT DOES NOT DO
-------------------
- DOI ごとの書誌の照合 → `check-doi-list.py` (Crossref の題・誌・巻・頁・著者を並べる)
- Semantic Scholar: 鍵なしの利用はすぐ HTTP 429 になる (実測) ので入れていない。 鍵を持つなら別に
- 出版社の PDF の取得 (Wiley・AMS・MDPI などはボット検出で 403 / 空応答。 迂回しない = arXiv・機関
  リポジトリの OA 版を `abstract` の所在から辿る)
- 429 / 5xx の自動リトライ (叩き続けない。 その source を止めて、 検索ログに「使えなかった」 と書く)

USAGE
-----
    python3 lit-search.py oa "waiting time distribution power law exponential cutoff" -n 12
    python3 lit-search.py oa '("waiting time" OR "inter-event time") AND ("power law" OR "power-law")' --boolean -n 80
    python3 lit-search.py cites 10.1137/070710111 -n 50
    python3 lit-search.py abstract 10.1137/070710111
    python3 lit-search.py crossref "Clauset Shalizi Newman 2009 Power-law distributions in empirical data" -n 3
    python3 lit-search.py arxiv 'ti:"power-law distributions"'
    python3 lit-search.py arxiv 'cat:hep-ex AND abs:"cross section"' --newest -n 25
    python3 lit-search.py arxiv-abstract 1810.07868
    python3 lit-search.py inspire 'abstracts.value:"cross section" and date > 2026-01-01' -n 25
    python3 lit-search.py --json inspire 'refersto:recid:<recid>' --all --abstract > citers.json   # 全件を手元で絞る
    python3 lit-search.py --selftest            # network を使わない
    (礼儀として連絡先を名乗るなら環境変数 OPENALEX_MAILTO / CROSSREF_MAILTO = <address>。 既定は名乗らない)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "lit-search/1.0 (academic literature survey; low volume)"
OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"
ARXIV = "https://export.arxiv.org/api/query"
INSPIRE = "https://inspirehep.net/api/literature"


class HttpError(RuntimeError):
    def __init__(self, status, url):
        super().__init__(f"HTTP {status}: {url}")
        self.status = status


class Client:
    def __init__(self, cache_dir=None, log=None, sleep=1.0):
        self.cache_dir, self.log, self.sleep, self._last = cache_dir, log, sleep, 0.0
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def get(self, url, as_json=True):
        path = None
        if self.cache_dir:
            path = os.path.join(self.cache_dir, hashlib.sha1(url.encode()).hexdigest()[:16]
                                + (".json" if as_json else ".xml"))
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    return json.load(f) if as_json else f.read()
        wait = self._last + self.sleep - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body, status = r.read().decode("utf-8", "replace"), r.status
        except urllib.error.HTTPError as e:
            body, status = None, e.code
        if self.log:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{status}\t{url}\n")
        if status != 200:
            raise HttpError(status, url)  # 誤り応答は cache に残さない
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        return json.loads(body) if as_json else body


def _mailto(var):
    m = os.environ.get(var, "").strip()
    return f"&mailto={urllib.parse.quote(m)}" if m else ""


def openalex_url(query, n=25, boolean=False, sort=None, extra_filter=None):
    """検索語か論理式の URL。 論理式のときは search= を付けない (付けると両方に当たる件だけになる)。"""
    parts = [f"per-page={n}"]
    filters = []
    if boolean:
        filters.append("title_and_abstract.search:" + urllib.parse.quote(query))
    elif query:
        parts.append("search=" + urllib.parse.quote(query))
    if extra_filter:
        filters.append(extra_filter)
    if filters:
        parts.append("filter=" + ",".join(filters))
    if sort:
        parts.append("sort=" + sort)
    return OPENALEX + "?" + "&".join(parts) + _mailto("OPENALEX_MAILTO")


def rebuild_abstract(inverted):
    """OpenAlex の abstract_inverted_index ({語: [位置…]}) を語順の文に戻す。"""
    pos = sorted((p, w) for w, ps in (inverted or {}).items() for p in ps)
    return " ".join(w for _, w in pos)


def norm_doi(s):
    s = s.strip()
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", s, flags=re.I)
    return s


def oa_row(w):
    loc = (w.get("primary_location") or {}).get("source") or {}
    return {"year": w.get("publication_year"), "id": (w.get("doi") or w.get("id") or "").replace("https://doi.org/", ""),
            "title": w.get("display_name"), "venue": loc.get("display_name"), "cited": w.get("cited_by_count"),
            "openalex": (w.get("id") or "").rsplit("/", 1)[-1]}


def crossref_row(m):
    return {"year": ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0], "id": m.get("DOI"),
            "title": (m.get("title") or [""])[0], "venue": (m.get("container-title") or [""])[0],
            "cited": m.get("is-referenced-by-count"),
            "first_author": ((m.get("author") or [{}])[0]).get("family")}


def arxiv_rows(xml):
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", e, re.S) or [None, ""])[1]
        out.append({"year": g("published")[:4], "id": g("id").rsplit("/abs/", 1)[-1],
                    "title": re.sub(r"\s+", " ", g("title")).strip(), "venue": g("arxiv:journal_ref"),
                    "cited": None})
    total = re.search(r"<opensearch:totalResults[^>]*>(\d+)<", xml)
    return (int(total.group(1)) if total else None), out


def arxiv_url(query, n, newest=False):
    order = "&sortBy=submittedDate&sortOrder=descending" if newest else ""
    return f"{ARXIV}?search_query={urllib.parse.quote(query, safe=':')}&max_results={n}{order}"


def arxiv_abstracts(xml):
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", e, re.S) or [None, ""])[1]
        out.append({"id": g("id").rsplit("/abs/", 1)[-1], "date": g("published")[:10],
                    "title": re.sub(r"\s+", " ", g("title")).strip(),
                    "abstract": re.sub(r"\s+", " ", g("summary")).strip()})
    return out


def inspire_url(query, n, page=1, abstract=False):
    fields = "titles,arxiv_eprints,earliest_date,publication_info,citation_count"
    if abstract:
        fields += ",abstracts"
    return f"{INSPIRE}?sort=mostrecent&size={n}&page={page}&fields={fields}&q={urllib.parse.quote(query)}"


def inspire_row(hit, abstract=False):
    m = hit["metadata"]
    pub = (m.get("publication_info") or [{}])[0]
    row = {"year": (m.get("earliest_date") or "")[:10], "id": (m.get("arxiv_eprints") or [{}])[0].get("value"),
           "title": (m.get("titles") or [{}])[0].get("title"),
           "venue": " ".join(str(pub[k]) for k in ("journal_title", "journal_volume") if pub.get(k)),
           "cited": m.get("citation_count")}
    if abstract:
        row["abstract"] = " ".join(x.get("value", "") for x in m.get("abstracts") or [])
    return row


def inspire_all(get, query, abstract=False, size=100):
    """全件を頁送りで集める。 get(url) -> 応答の dict。 総数と集めた行を返す (件数が合わなければ呼び手が気づける)。"""
    rows, page = [], 1
    while True:
        d = get(inspire_url(query, size, page, abstract))
        hits, total = d["hits"]["hits"], d["hits"]["total"]
        rows += [inspire_row(h, abstract) for h in hits]
        if not hits or len(rows) >= total:
            return total, rows
        page += 1


def show(total, rows, as_json, label):
    if as_json:
        print(json.dumps({"source": label, "total": total, "results": rows}, ensure_ascii=False, indent=1))
        return
    print(f"# {label}: total {total}")
    for r in rows:
        print(f"  {r.get('year')} | {r.get('id')} | {r.get('title')} | {r.get('venue') or ''} | cited {r.get('cited')}")


def run(a):
    c = Client(a.cache_dir, a.log, a.sleep)
    try:
        if a.cmd == "oa":
            d = c.get(openalex_url(a.query, a.n, a.boolean, "cited_by_count:desc" if a.sort == "cited" else None))
            show(d.get("meta", {}).get("count"), [oa_row(w) for w in d.get("results", [])], a.json, "OpenAlex")
        elif a.cmd == "cites":
            wid = a.work
            if wid.lower().startswith("10.") or "doi.org" in wid:
                wid = c.get(OPENALEX + "/doi:" + norm_doi(wid))["id"].rsplit("/", 1)[-1]
            d = c.get(openalex_url("", a.n, sort="cited_by_count:desc", extra_filter="cites:" + wid))
            show(d.get("meta", {}).get("count"), [oa_row(w) for w in d.get("results", [])], a.json, f"cites {wid}")
        elif a.cmd == "abstract":
            out = []
            for doi in a.dois:
                w = c.get(OPENALEX + "/doi:" + norm_doi(doi) + _mailto("OPENALEX_MAILTO").replace("&", "?", 1))
                loc = w.get("best_oa_location") or {}
                out.append({"doi": norm_doi(doi), "title": w.get("display_name"), "year": w.get("publication_year"),
                            "oa_status": (w.get("open_access") or {}).get("oa_status"),
                            "oa_url": loc.get("pdf_url") or loc.get("landing_page_url"),
                            "abstract": rebuild_abstract(w.get("abstract_inverted_index"))})
            if a.json:
                print(json.dumps(out, ensure_ascii=False, indent=1))
            else:
                for r in out:
                    print(f"### {r['doi']} | {r['year']} | {r['title']} | OA={r['oa_status']} {r['oa_url']}")
                    print(r["abstract"] or "(要旨なし = OpenAlex が持っていない)")
                    print()
        elif a.cmd == "crossref":
            d = c.get(f"{CROSSREF}?rows={a.n}&query.bibliographic={urllib.parse.quote(a.query)}"
                      + _mailto("CROSSREF_MAILTO"))
            show(d["message"].get("total-results"), [crossref_row(m) for m in d["message"].get("items", [])],
                 a.json, "Crossref (total = 関連度の母集団、 ヒット数ではない)")
        elif a.cmd == "arxiv":
            total, rows = arxiv_rows(c.get(arxiv_url(a.query, a.n, a.newest), as_json=False))
            show(total, rows, a.json, "arXiv")
        elif a.cmd == "arxiv-abstract":
            rows = arxiv_abstracts(c.get(f"{ARXIV}?max_results={len(a.ids)}&id_list={','.join(a.ids)}", as_json=False))
            if a.json:
                print(json.dumps(rows, ensure_ascii=False, indent=1))
            else:
                for r in rows:
                    print(f"### {r['id']} | {r['date']} | {r['title']}\n{r['abstract']}\n")
        elif a.cmd == "inspire":
            if a.all:
                total, rows = inspire_all(c.get, a.query, a.abstract)
            else:
                d = c.get(inspire_url(a.query, a.n, abstract=a.abstract))
                total, rows = d["hits"]["total"], [inspire_row(h, a.abstract) for h in d["hits"]["hits"]]
            show(total, rows, a.json, "INSPIRE (新しい順)")
    except HttpError as e:
        sys.exit(f"{e} — リトライしない。 429 なら鍵なしの利用の制限 (その source を止めて検索ログに書く)")


def selftest():
    u = openalex_url('"waiting time" AND "power law"', 40, boolean=True)
    assert "filter=title_and_abstract.search:" in u and "search=%22" not in u.split("filter=")[0], u
    assert "&search=" not in u, "論理式に search= を併用している"
    u2 = openalex_url("waiting time", 12)
    assert "search=waiting%20time" in u2 and "filter=" not in u2, u2
    u3 = openalex_url("", 50, sort="cited_by_count:desc", extra_filter="cites:W1")
    assert "filter=cites:W1" in u3 and "search=" not in u3, u3
    assert rebuild_abstract({"law": [2], "Power": [0], "-": [1]}) == "Power - law"
    assert rebuild_abstract(None) == ""
    assert norm_doi("https://doi.org/10.1/x") == "10.1/x" and norm_doi("doi:10.2/Y") == "10.2/Y"
    total, rows = arxiv_rows("<feed><opensearch:totalResults>1</opensearch:totalResults><entry><id>http://arxiv.org/abs/1810.07868v2</id>"
                             "<published>2018-10-18T00:00:00Z</published><title>Power-law size\n distributions</title></entry></feed>")
    assert total == 1 and rows[0]["id"] == "1810.07868v2" and rows[0]["title"] == "Power-law size distributions", rows
    assert "sortBy=submittedDate" in arxiv_url('abs:"x y"', 5, newest=True), "新しい順が URL に入っていない"
    assert "sortBy" not in arxiv_url('abs:"x y"', 5) and "abs:%22x%20y%22" in arxiv_url('abs:"x y"', 5)
    abs_rows = arxiv_abstracts("<feed><entry><id>http://arxiv.org/abs/1810.07868v2</id><published>2018-10-18T00:00:00Z"
                               "</published><title>A title</title><summary>Two\n lines</summary></entry></feed>")
    assert abs_rows == [{"id": "1810.07868v2", "date": "2018-10-18", "title": "A title", "abstract": "Two lines"}], abs_rows
    assert "sort=mostrecent" in inspire_url('t "x" and date > 2026-01-01', 3)
    r = inspire_row({"metadata": {"earliest_date": "2026-01-02T00", "arxiv_eprints": [{"value": "2601.00001"}],
                                  "titles": [{"title": "A title"}], "citation_count": 4,
                                  "publication_info": [{"journal_title": "J.Test", "journal_volume": "9"}]}})
    assert r == {"year": "2026-01-02", "id": "2601.00001", "title": "A title", "venue": "J.Test 9", "cited": 4}, r
    assert inspire_row({"metadata": {}})["id"] is None, "欠けた欄で落ちる"
    assert "abstracts" in inspire_url("x", 3, abstract=True) and "abstracts" not in inspire_url("x", 3)
    assert inspire_row({"metadata": {"abstracts": [{"value": "a"}, {"value": "b"}]}}, True)["abstract"] == "a b"
    pages = {1: [{"metadata": {}}, {"metadata": {}}], 2: [{"metadata": {}}]}
    fake = lambda url: {"hits": {"total": 3, "hits": pages[int(re.search(r"page=(\d+)", url).group(1))]}}
    assert inspire_all(fake, "x", size=2)[0] == 3 and len(inspire_all(fake, "x", size=2)[1]) == 3, "頁送り"
    # 誤り応答を cache に残さないこと (network を使わず、 応答を差し替えて確かめる)
    import tempfile

    class Fake(Client):
        def __init__(self, d):
            super().__init__(d, None, 0)
            self.calls = 0

    with tempfile.TemporaryDirectory() as d:
        f = Fake(d)
        orig = urllib.request.urlopen

        def boom(*_a, **_k):
            f.calls += 1
            raise urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        urllib.request.urlopen = boom
        try:
            for _ in range(2):
                try:
                    f.get("https://example.invalid/x")
                except HttpError:
                    pass
        finally:
            urllib.request.urlopen = orig
        assert f.calls == 2 and not os.listdir(d), "誤り応答が cache に残った"
    print("selftest ok")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cache-dir")
    ap.add_argument("--log", help="1 リクエスト 1 行 (時刻・status・URL) を追記する file")
    ap.add_argument("--sleep", type=float, default=1.0, help="リクエストの間隔の下限 (秒)")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("oa")
    p.add_argument("query")
    p.add_argument("-n", type=int, default=25)
    p.add_argument("--boolean", action="store_true", help="題名と要旨の論理式 (title_and_abstract.search)")
    p.add_argument("--sort", choices=("relevance", "cited"), default=None,
                   help="既定 = 全文検索は関連度順、 論理式は被引用順")
    p = sub.add_parser("cites")
    p.add_argument("work", help="DOI か OpenAlex の W id")
    p.add_argument("-n", type=int, default=50)
    p = sub.add_parser("abstract")
    p.add_argument("dois", nargs="+")
    p = sub.add_parser("crossref")
    p.add_argument("query")
    p.add_argument("-n", type=int, default=5)
    p = sub.add_parser("arxiv")
    p.add_argument("query")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--newest", action="store_true", help="提出日の新しい順 (既定 = 関連度順)")
    p = sub.add_parser("arxiv-abstract")
    p.add_argument("ids", nargs="+")
    p = sub.add_parser("inspire")
    p.add_argument("query")
    p.add_argument("-n", type=int, default=25)
    p.add_argument("--all", action="store_true", help="全件を頁送りで取る (-n を無視)。 被引用の全件を手元で絞るとき")
    p.add_argument("--abstract", action="store_true", help="要旨も取る (--json の abstract 欄)")
    a = ap.parse_args(argv)
    if a.selftest:
        selftest()
        return
    if not a.cmd:
        ap.error("subcommand が要る (oa / cites / abstract / crossref / arxiv / arxiv-abstract / inspire)")
    if a.cmd == "oa" and a.sort is None:
        a.sort = "cited" if a.boolean else "relevance"
    run(a)


if __name__ == "__main__":
    main()
