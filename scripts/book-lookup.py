#!/usr/bin/env python3
"""本の書誌・図書館の所蔵・価格と入手できるかを、 ISBN や書名からまとめて引く (CiNii Books / 図書館 OPAC / openBD / 紀伊國屋 / 楽天)。--selftest 内蔵。

なぜ層1 にあるか
----------------
図書館に本の購入を頼む前の下調べ (書誌を揃える → 所蔵が無いか → 新刊で買えるか・いくらか) は、
1 冊ごとに同じ web 照会を手書きの inline python で繰り返すことになる (実測)。 壊れ方も毎回同じなので道具にした:

  1. **CiNii の参加組織フィルタは所蔵なしの証明にならない** — CiNii に載らない紙の本、 電子書籍、
     ISBN の無い古い登録がある。 `held` はヒントで、 結論は `opac` (その館の OPAC) で ISBN と書名の両方を引く。
  2. **openBD の価格は登録時の値** — 値上げが反映されないことがある。 今の定価は書店の商品ページで見る (`price`)。
  3. **書店に価格が出ない = 注文できない見込み** — 紀伊國屋の商品ページに価格が無い本は、 品切れ・絶版のことが多い。
     楽天の「ご注文できない商品」 は楽天で扱えないだけのこともあるので弱い信号。 版元のサイトで在庫ありに
     絞る検索があれば、 それが一番強い (版元ごとに違うので道具には入れていない)。
  4. **ISBN が無い本がある** — 雑誌扱いの叢書や 1980 年代より前の本。 書名で引く。
     **OPAC の頁が読めないのを 0 件と読まない** — 件数の語の無い頁を 0 件と出した (実測)。 件数の語も該当なしの語
     (`--none`) も無い頁 (ログインの頁・読み込み中の頁・形の変わった頁など) は「読めない」 と出す = 所蔵なしの結論にしない。
  5. **書店の商品ページが丸 1 日応答しないことがある** (nginx のエラー、 script でもブラウザでも同じ = 実測)。 その日は
     `amazon` (通販の商品ページ、 商品 id = ISBN-10) で価格と入手を取る。 値付けは出品者込みで定価より高いことがあり、
     「残り N 点」 は出品在庫。 空の応答が時々返るので間を置いて取り直す。 楽天の検索結果は洋書では海外取り寄せの上乗せで
     定価と離れ「注文できない」 ばかりになる = 洋書の価格には使わない (実測)。
  6. **1 か所が応答しないと、 その列だけが「応答なし」 になる** — 書店の 1 ページの read timeout で command ごと落ち、
     先に取れていた openBD の価格も残りの本も出ないことがあった (実測)。 今はその本のその列だけ「応答なし = 未確認」
     と出して先へ進む。 「応答なし」 は「価格なし」 (= 注文できない見込み) と違う。 時間をおいて取り直す。

手順と判断の一般則 = conventions/book-purchase-lookup.md。

使い方
------
  book-lookup.py bib   ISBN|NCID|書名 [...] [--count 5]       CiNii の書誌 (NCID・版・ページ・ISBN・叢書・所蔵館数)
  book-lookup.py held  --fano CODE ISBN|NCID|書名 [...]      CiNii で参加組織 CODE が持っているか (ヒント)
  book-lookup.py opac  --url 'https://.../search?kw={q}' [--hit REGEX] [--item REGEX] ISBN|書名 [...]
                                                          その館の OPAC の検索件数と先頭の行 (結論はこちら)
  book-lookup.py price ISBN [...] [--rakuten]               openBD の登録価格 + 紀伊國屋の今の価格・在庫 (+ 楽天の表示)
  book-lookup.py amazon ISBN [...]                          Amazon.co.jp の商品ページの価格 (出品者込み)・在庫・形態 (書店の商品ページが落ちている日の代替)
  book-lookup.py isbn13 ISBN10 [...]                        ISBN-10 → ISBN-13
  book-lookup.py --selftest                                 network に出ない検査

出力はタブ区切り 1 行 1 件。 照会の間は 0.6 秒あける。 依存 = 標準ライブラリだけ。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
PAUSE = 0.6
NCID_RE = re.compile(r"^[A-Z]{2}\d{7}[\dX]$")


# ---------------------------------------------------------------- ISBN

def isbn13_check(first12: str) -> str:
    return str((10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(first12)) % 10) % 10)


def to_isbn13(s: str) -> str | None:
    """ISBN-10 / ISBN-13 (ハイフン可) を ISBN-13 にする。 形が合わない・検査数字が合わなければ None。"""
    d = re.sub(r"[-\s]", "", s).upper()
    if re.fullmatch(r"\d{9}[\dX]", d):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d))
        if total % 11:
            return None
        return "978" + d[:9] + isbn13_check("978" + d[:9])
    if re.fullmatch(r"97[89]\d{10}", d):
        return d if isbn13_check(d[:12]) == d[12] else None
    return None


def to_isbn10(s: str) -> str | None:
    """978 で始まる ISBN-13 を ISBN-10 に (979 は ISBN-10 を持たない)。 通販サイトの商品 id は ISBN-10 のことが多い。"""
    d = to_isbn13(s)
    if not d or not d.startswith("978"):
        return None
    core = d[3:12]
    chk = (11 - sum((10 - i) * int(c) for i, c in enumerate(core)) % 11) % 11
    return core + ("X" if chk == 10 else str(chk))


# ---------------------------------------------------------------- HTTP / text

def fetch(url: str, timeout: int = 30, encoding: str = "utf-8") -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return r.read().decode(encoding, "ignore")


def page_text(s: str) -> str:
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)))


# ---------------------------------------------------------------- CiNii

def _plain(v) -> str:
    """CiNii JSON-LD の値 (文字列 / {@value} / その list) から、 読み仮名以外を ' / ' でつなぐ。"""
    if isinstance(v, list):
        return " / ".join(x for x in (_plain(i) for i in v if not (isinstance(i, dict) and i.get("@language"))) if x)
    if isinstance(v, dict):
        return str(v.get("@value") or v.get("dc:title") or "")
    return "" if v is None else str(v)


def cinii_search(q: str, count: int = 5, fano: str | None = None) -> tuple[int, list[str]]:
    params = {"format": "json", "count": count, "q": q}
    if fano:
        params["fano"] = fano
    d = json.loads(fetch("https://ci.nii.ac.jp/books/opensearch/search?" + urllib.parse.urlencode(params)))
    g = d.get("@graph", [{}])[0]
    ncids = [it.get("@id", "").rstrip("/").split("/")[-1] for it in g.get("items", [])]
    return int(g.get("opensearch:totalResults") or 0), [n for n in ncids if NCID_RE.match(n)]


def parse_cinii_detail(d: dict, fano: str | None = None) -> dict:
    e = d["@graph"][0]
    parts = e.get("dcterms:hasPart") or []
    isbns = []
    for p in parts if isinstance(parts, list) else [parts]:
        pid = p.get("@id", "")
        if pid.startswith("urn:isbn:"):
            vol = _plain(p.get("dc:title"))
            isbns.append(pid[9:] + (f"({vol})" if vol else ""))
    series = e.get("dcterms:isPartOf") or []
    owners = [o.get("@id", "") for o in e.get("bibo:owner") or []]
    return {
        "ncid": e.get("cinii:ncid", ""),
        "title": _plain(e.get("dc:title")),
        "creator": _plain(e.get("dc:creator")),
        "publisher": _plain(e.get("dc:publisher")),
        "date": e.get("dc:date", ""),
        "edition": e.get("prism:edition", ""),
        "extent": e.get("dcterms:extent", ""),
        "isbn": ",".join(isbns),
        "series": _plain(series if isinstance(series, list) else [series]),
        "owners": e.get("cinii:ownerCount", ""),
        "held": (any(o.rstrip("/").endswith("/" + fano) for o in owners) if fano else None),
    }


def cinii_detail(ncid: str, fano: str | None = None) -> dict:
    return parse_cinii_detail(json.loads(fetch(f"https://ci.nii.ac.jp/ncid/{ncid}.json")), fano)


def resolve_ncids(q: str, count: int) -> list[str]:
    if NCID_RE.match(q):
        return [q]
    isbn = to_isbn13(q)
    return cinii_search(isbn or q, count)[1]


# ---------------------------------------------------------------- OPAC

OPAC_NONE_DEFAULT = (r"該当する(?:資料|データ|もの|図書)(?:は|が)(?:ありません|見つかりません)|見つかりませんでした|"
                     r"検索結果はありません|[Nn]o (?:records|results|items|matches)(?: were)? found")


def parse_opac(text: str, hit: str, item: str | None, none: str = OPAC_NONE_DEFAULT) -> tuple[int | None, list[str]]:
    """(件数, 先頭の行)。 件数の語が無く該当なしの語 (none) があれば 0、 どちらも無ければ None = 読めない頁 (0 件と分ける)。"""
    m = re.search(hit, text)
    if not m:
        return (0, []) if re.search(none, text) else (None, [])
    n = int(m.group(1))
    if not item:
        return n, [text[m.end():m.end() + 300].strip()]
    return n, [_clip(x.strip()) for x in re.findall(item, text[m.end():])][:5]


def _clip(s: str, head: int = 130, tail: int = 20) -> str:
    """長い行は頭と末尾を残して縮める (OPAC の区分「図書」「電子ブック」 は行末に付くので、 末尾を落とすと形態が読めなくなる)。"""
    return s if len(s) <= head + tail + 1 else s[:head] + "…" + s[-tail:]


# ---------------------------------------------------------------- price

def parse_openbd(records: list) -> dict:
    out = {}
    for d in records:
        if not d:
            continue
        isbn = d.get("summary", {}).get("isbn", "")
        prices = (d.get("onix", {}).get("ProductSupply", {}).get("SupplyDetail", {}).get("Price") or [])
        out[isbn] = "; ".join(f"{p.get('PriceAmount')}" for p in prices if p.get("PriceAmount")) or "価格の登録なし"
    return out


def parse_kinokuniya(text: str) -> tuple[str | None, str | None, str]:
    """(税込, 本体, 在庫の句)。 価格が無ければ (None, None, ...) = 注文できない見込み。"""
    p = re.search(r"(?<!電子版)価格 ¥([0-9,]+) （本体¥([0-9,]+)）", text)
    st = re.search(r"(ウェブストアに\d+冊在庫がございます|お取り寄せ[^。）)]{0,30}|在庫がございません|予約受付中)", text)
    return (p.group(1) if p else None, p.group(2) if p else None, st.group(1) if st else "")


def parse_rakuten(text: str, isbn: str) -> tuple[str | None, str]:
    m = re.search(r"ISBN：" + isbn + r"(.{0,160}?)([0-9,]+)円 \(税込\)(.{0,80}?)※", text)
    if not m:
        return None, ""
    return m.group(2), re.sub(r"\s*送料無料\s*", " ", m.group(3)).strip()[:40]


def _block(page: str, id_: str, n: int = 6000) -> str:
    """id="..." を持つ要素の中身 (開始 tag の直後から n 字)。 無ければ空。"""
    i = page.find(f'id="{id_}"')
    if i < 0:
        return ""
    j = page.find(">", i)
    return page[j + 1:j + 1 + n]


def parse_amazon(page: str) -> dict:
    """Amazon.co.jp の商品ページから 書名 / 価格 (税込表示) / 在庫の句 / 形態 を読む。 書名が取れなければ空の応答 (取り直す)。
    価格は出品者の値付けを含む (定価とは限らない)。 「残り N 点」 は出品在庫の表示。"""
    title = page_text(_block(page, "productTitle", 800).split("</", 1)[0]).strip()  # 要素の閉じで切る (後続の要素を拾わない)
    if not title:
        return {}
    core = _block(page, "corePrice_feature_div")
    m = re.search(r'a-offscreen">\s*(￥[\d,]+)', core) or re.search(r'a-offscreen">\s*(￥[\d,]+)', page)
    avail = re.sub(r"在庫状況.*$", "", page_text(_block(page, "availability", 1500))).strip()
    binding = page_text(_block(page, "productSubtitle", 300).split("</", 1)[0]) or page_text(_block(page, "productBinding", 300).split("</", 1)[0])
    if not binding:
        mb = re.search(r"(ペーパーバック|ハードカバー|単行本[^ ]*|文庫|新書)\s*[–-]\s*\d{4}/\d{1,2}/\d{1,2}", page_text(page[:200000]))
        binding = mb.group(0) if mb else ""
    return {"title": title[:80], "price": m.group(1) if m else "価格なし", "availability": avail[:40], "binding": binding[:40]}


def cmd_amazon(a) -> None:
    """大手書店の商品ページが落ちている日や自費出版の本の代替。 空の応答が時々返るので間を置いて 3 回まで取り直す。"""
    for x in a.isbn:
        i10 = to_isbn10(x)
        if not i10:
            print(f"{x}\t(ISBN-10 にできない = 商品 id が分からない)")
            continue
        row = None
        for _ in range(3):
            try:
                r = parse_amazon(fetch(f"https://www.amazon.co.jp/dp/{i10}", timeout=40))
            except urllib.error.HTTPError as e:
                row = [x, i10, f"HTTP {e.code}", "", "", ""]
                break
            if r:
                row = [x, i10, r["price"], r["availability"], r["binding"], r["title"]]
                break
            time.sleep(4)
        print("\t".join(row or [x, i10, "取得失敗 (空の応答 3 回)", "", "", ""]))
        time.sleep(2.5)


# ---------------------------------------------------------------- commands

def cmd_bib(a) -> None:
    for q in a.query:
        for ncid in resolve_ncids(q, a.count):
            r = cinii_detail(ncid)
            print("\t".join([q, r["ncid"], r["title"], r["creator"], r["publisher"], str(r["date"]),
                             r["edition"], r["extent"], r["isbn"], r["series"], f"所蔵館 {r['owners']}"]))
            time.sleep(PAUSE)


def cmd_held(a) -> None:
    for q in a.query:
        ncids = resolve_ncids(q, a.count)
        if not ncids:
            print(f"{q}\t(CiNii に書誌なし)")
        for ncid in ncids:
            r = cinii_detail(ncid, a.fano)
            print("\t".join([q, ncid, r["title"][:50], str(r["date"]), r["edition"],
                             "CiNii では所蔵あり" if r["held"] else "CiNii では所蔵なし (OPAC で確かめる)"]))
            time.sleep(PAUSE)


def cmd_opac(a) -> None:
    for q in a.query:
        text = page_text(fetch(a.url.replace("{q}", urllib.parse.quote(q))))
        n, items = parse_opac(text, a.hit, a.item, a.none)
        if n is None:   # 件数の語も該当なしの語も無い頁 (ログインの頁・読み込み中の頁・形の変わった頁) を 0 件にしない
            print("\t".join([q, "読めない (件数の語も該当なしの語も無い頁。 0 件ではない = 画面で確かめるか --hit / --none を直す)"]))
            time.sleep(PAUSE)
            continue
        # 行は先頭 5 件まで (1 ページ目だけ)。 当たりが多いと 6 件目以降の本を見落とすので、 切れたことを出す
        more = [f"…ほか {n - len(items)} 件は表示していない (書名と著者を空白でつないだ AND 検索で絞る)"] if a.item and n > len(items) else []
        print("\t".join([q, f"{n} 件"] + items + more))
        time.sleep(PAUSE)


def fetch_or_none(url: str) -> str | None:
    """照会先が応答しない (read timeout・接続できない) ときは None を返す。 呼び元はその列だけ「応答なし」 にして先へ進む
    (= 1 か所の timeout で command ごと落ち、 取れていた分まで失わないため)。 HTTP の status (404 など) は呼び元が扱う。"""
    try:
        return fetch(url)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError):  # socket.timeout は OSError の子 (3.9)
        return None


def cmd_price(a) -> None:
    isbns = [to_isbn13(x) or x for x in a.isbn]
    bad = [x for x in isbns if not to_isbn13(x)]
    if bad:
        print("⚠️ ISBN として読めない: " + ", ".join(bad), file=sys.stderr)
    good = [x for x in isbns if to_isbn13(x)]
    ob_page = fetch_or_none("https://api.openbd.jp/v1/get?isbn=" + ",".join(good)) if good else None
    ob = parse_openbd(json.loads(ob_page)) if ob_page else {}
    if good and ob_page is None:
        print("⚠️ openBD が応答しない = 登録価格は未確認", file=sys.stderr)
    for isbn in good:
        kind = "01" if isbn.startswith("9784") else "02"
        try:
            page = fetch_or_none(f"https://www.kinokuniya.co.jp/f/dsg-{kind}-{isbn}")
            if page is None:
                kino = "紀伊國屋 応答なし = 未確認 (時間をおいて取り直す)"
            else:
                tax, base, stock = parse_kinokuniya(page_text(page))
                kino = f"紀伊國屋 税込 {tax} (本体 {base}) {stock}" if tax else "紀伊國屋 価格なし = 注文できない見込み"
        except urllib.error.HTTPError as e:  # 商品ページの無い ISBN は 404 で返る (自費出版の洋書など)
            if e.code != 404:
                raise
            kino = "紀伊國屋 商品ページなし (404) = 取り扱いなし"
        row = [isbn, f"openBD {ob.get(isbn, '登録なし') if ob_page else '応答なし'}", kino]
        time.sleep(PAUSE)
        if a.rakuten:
            page = fetch_or_none(f"https://books.rakuten.co.jp/search?sitem={isbn}&g=001")
            if page is None:
                row.append("楽天 応答なし = 未確認")
            else:
                rp, rs = parse_rakuten(page_text(page), isbn)
                row.append(f"楽天 税込 {rp} {rs}" if rp else "楽天 該当なし")
            time.sleep(PAUSE)
        print("\t".join(row))


def cmd_isbn13(a) -> None:
    for x in a.isbn:
        print(f"{x}\t{to_isbn13(x) or '(ISBN として読めない)'}")


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    ok = True

    def check(cond, name):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    # 合成の ISBN (検査数字だけ正しく作った架空の番号)
    body = "400000001"
    s10 = sum((10 - i) * int(c) for i, c in enumerate(body))
    c10 = (11 - s10 % 11) % 11
    isbn10 = body + ("X" if c10 == 10 else str(c10))
    isbn13 = "978" + body + isbn13_check("978" + body)
    check(to_isbn13(isbn10) == isbn13, "ISBN-10 → ISBN-13 (検査数字を付け直す)")
    check(to_isbn13(isbn13[:3] + "-" + isbn13[3:]) == isbn13, "ハイフン入りの ISBN-13 をそのまま通す")
    check(to_isbn13(isbn13[:12] + str((int(isbn13[12]) + 1) % 10)) is None, "検査数字が合わない ISBN-13 は None")
    check(to_isbn13("abc") is None and to_isbn13("4910000000000") is None, "ISBN でない番号 (雑誌コード等) は None")

    detail = {"@graph": [{
        "cinii:ncid": "BX00000001", "dc:title": [{"@value": "合成の本"}, {"@value": "ゴウセイ ノ ホン", "@language": "ja-hrkt"}],
        "dc:creator": "著者A著", "dc:publisher": [{"@value": "合成出版"}], "dc:date": "2020",
        "prism:edition": "第2版", "dcterms:extent": "2冊",
        "dcterms:hasPart": [{"@id": "urn:isbn:" + isbn13, "dc:title": "1"}, {"@id": "urn:isbn:9780000000002", "dc:title": "2"}],
        "dcterms:isPartOf": [{"@id": "x", "dc:title": "合成叢書, 3"}],
        "cinii:ownerCount": "12",
        "bibo:owner": [{"@id": "https://ci.nii.ac.jp/library/FA000001"}, {"@id": "https://ci.nii.ac.jp/library/FA000002"}],
    }]}
    r = parse_cinii_detail(detail, "FA000002")
    check(r["title"] == "合成の本" and r["publisher"] == "合成出版" and r["edition"] == "第2版",
          "CiNii 詳細: 読み仮名を落として書名・出版社・版を取る")
    check(r["isbn"] == f"{isbn13}(1),9780000000002(2)" and r["series"] == "合成叢書, 3", "CiNii 詳細: 巻ごとの ISBN と叢書")
    check(r["held"] is True and parse_cinii_detail(detail, "FA000003")["held"] is False
          and parse_cinii_detail(detail)["held"] is None, "CiNii 詳細: 参加組織コードの完全一致で所蔵を判定")

    opac_text = "検索結果 2件 並び順 1. 合成の本 / 著者A 図書 2. 合成の本 / 著者A : electronic bk 電子ブック メール送信"
    n, items = parse_opac(opac_text, r"(\d+)\s*件", r"\d+\. (.*?)(?= \d+\. | メール送信)")
    check(n == 2 and items == ["合成の本 / 著者A 図書", "合成の本 / 著者A : electronic bk 電子ブック"],
          "OPAC: 件数と行 (区分の語が行に残る)")
    check(parse_opac("該当する資料はありません", r"(\d+)\s*件", None) == (0, []), "OPAC: 該当なしの語があれば 0")
    check(parse_opac("検索結果 0件", r"(\d+)\s*件", None)[0] == 0, "OPAC: 件数の語の 0 件は 0")
    check(parse_opac("ログインしてください 読み込み中…", r"(\d+)\s*件", None) == (None, []),
          "OPAC: 件数の語も該当なしの語も無い頁は None = 読めない (0 件にしない)")

    ob = parse_openbd([None, {"summary": {"isbn": isbn13}, "onix": {"ProductSupply": {"SupplyDetail": {
        "Price": [{"PriceType": "01", "PriceAmount": "2000"}]}}}}])
    check(ob == {isbn13: "2000"}, "openBD: 登録価格を取り、 null の record は飛ばす")
    k = parse_kinokuniya("電子版価格 ¥900 合成の本 価格 ¥2,200 （本体¥2,000） 合成出版 ウェブストアに3冊在庫がございます。")
    check(k == ("2,200", "2,000", "ウェブストアに3冊在庫がございます"), "紀伊國屋: 電子版価格を避けて紙の価格と在庫")
    check(parse_kinokuniya("内容説明 目次")[0] is None, "紀伊國屋: 価格が無いページは None")
    check(to_isbn10(isbn13) == isbn10 and to_isbn10("9790000000000") is None, "ISBN-13 → ISBN-10 (979 は無し)")
    check(_clip("a" * 200 + " 電子ブック").endswith("…" + ("a" * 200 + " 電子ブック")[-20:]) and _clip("短い行 図書") == "短い行 図書",
          "OPAC の長い行は末尾の区分を残して縮める")
    amz = ('<span id="productTitle" class="x"> 合成の本 </span><div id="corePrice_feature_div"><span class="a-offscreen">￥1,234</span></div>'
           '<div id="availability" class="y"> 残り2点 ご注文はお早めに 在庫状況 について .css{} </div><span id="productSubtitle">ペーパーバック – 2020/1/1</span>')
    ra = parse_amazon(amz)
    check(ra == {"title": "合成の本", "price": "￥1,234", "availability": "残り2点 ご注文はお早めに", "binding": "ペーパーバック – 2020/1/1"},
          "Amazon: 書名・価格・在庫の句 (在庫状況の後ろの css を捨てる)・形態")
    check(parse_amazon("<html>empty</html>") == {}, "Amazon: 書名が無い応答は空 = 取り直す")
    rk = parse_rakuten(f"本 合成の本 ISBN：{isbn13} 2020年発売 ／ 合成出版 2,200円 (税込) 送料無料 ご注文できない商品 ※ページの更新", isbn13)
    check(rk == ("2,200", "ご注文できない商品"), "楽天: 検索結果のその本の行から価格と注文可否")

    # 照会先が応答しなくても command は落ちず、 その列だけ「応答なし」 (network に出ない = fetch を差し替える)
    import contextlib
    import io
    import socket
    import types
    g = globals()
    real_fetch, real_pause = g["fetch"], g["PAUSE"]
    ob_json = json.dumps([{"summary": {"isbn": isbn13}, "onix": {"ProductSupply": {"SupplyDetail": {
        "Price": [{"PriceType": "01", "PriceAmount": "2000"}]}}}}])

    def price_out(openbd_up: bool) -> str:
        def fake_fetch(url, timeout=30, encoding="utf-8"):
            if "openbd" in url and openbd_up:
                return ob_json
            raise socket.timeout("The read operation timed out")
        g["fetch"], g["PAUSE"] = fake_fetch, 0
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                cmd_price(types.SimpleNamespace(isbn=[isbn13], rakuten=True))
            return buf.getvalue()
        finally:
            g["fetch"], g["PAUSE"] = real_fetch, real_pause

    out = price_out(True)
    check("openBD 2000" in out and "紀伊國屋 応答なし" in out and "楽天 応答なし" in out,
          "price: 書店が応答しなくても openBD の価格は出て、 書店の列だけ「応答なし」")
    check("openBD 応答なし" in price_out(False), "price: openBD も応答しなければ「登録なし」 でなく「応答なし」")

    def opac_out(page: str) -> str:
        g["fetch"], g["PAUSE"] = (lambda url, timeout=30, encoding="utf-8": page), 0
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_opac(types.SimpleNamespace(url="https://opac.example.invalid/?q={q}", hit=r"(\d+)\s*件",
                                               item=r"\d+\. (.*?)(?= \d+\. |$)", none=OPAC_NONE_DEFAULT, query=["合成の本"]))
            return buf.getvalue()
        finally:
            g["fetch"], g["PAUSE"] = real_fetch, real_pause

    check("\t読めない" in opac_out("<html><body>ログインしてください</body></html>")
          and "\t0 件" in opac_out("<p>該当する資料はありません</p>"),
          "opac: 読めない頁は「読めない」、 該当なしの頁は 0 件 (2 つを分けて出す)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("bib"); p.add_argument("query", nargs="+"); p.add_argument("--count", type=int, default=5)
    p.set_defaults(fn=cmd_bib)
    p = sub.add_parser("held"); p.add_argument("--fano", required=True); p.add_argument("query", nargs="+")
    p.add_argument("--count", type=int, default=5); p.set_defaults(fn=cmd_held)
    p = sub.add_parser("opac"); p.add_argument("--url", required=True, help="検索 URL。 {q} を語に置き換える")
    p.add_argument("--hit", default=r"(\d+)\s*件", help="件数を取る正規表現 (group 1 = 件数)")
    p.add_argument("--item", help="1 件ごとの行を取る正規表現 (group 1)。 省くと件数の後ろ 300 字")
    p.add_argument("--none", default=OPAC_NONE_DEFAULT,
                   help="該当なしの頁の語の正規表現。 件数の語もこれも無い頁は「読めない」 と出す (0 件と分ける)")
    p.add_argument("query", nargs="+"); p.set_defaults(fn=cmd_opac)
    p = sub.add_parser("price"); p.add_argument("isbn", nargs="+"); p.add_argument("--rakuten", action="store_true")
    p.set_defaults(fn=cmd_price)
    p = sub.add_parser("amazon", help="Amazon.co.jp の商品ページの価格・在庫・形態 (書店の商品ページが落ちている日の代替、 値付けは出品者込み)")
    p.add_argument("isbn", nargs="+"); p.set_defaults(fn=cmd_amazon)
    p = sub.add_parser("isbn13"); p.add_argument("isbn", nargs="+"); p.set_defaults(fn=cmd_isbn13)
    a = ap.parse_args(argv)
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
