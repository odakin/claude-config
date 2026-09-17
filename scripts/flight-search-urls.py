#!/usr/bin/env python3
"""flight-search-urls.py — 航空券の往復検索 URL を比較サイト別に作る (Kayak / Expedia)。 --selftest 内蔵。

Why: 航空会社の公式サイトは検索の前に bot 判定を置いていることが多く、 Google フライトは URL の自然文
パラメータを受け付けず入力欄を 1 つずつ操作することになる (実測)。 Kayak と Expedia は URL だけで
検索結果まで開ける (実測) ので、 内蔵 Browser pane の `navigate` に渡す URL をここで作る。
手順・結果の読み方・止まる所 = conventions/flight-search.md。

usage:
  flight-search-urls.py <出発> <到着> <往路 YYYY-MM-DD> <復路 YYYY-MM-DD> [--site kayak|expedia|all]
                        [--kayak-filter FS]
  flight-search-urls.py --selftest

  出発・到着 = IATA の空港 code (例: NRT) か都市 code (例: TYO = 東京の全空港)。
  --kayak-filter = Kayak の `fs=` にそのまま入れる値。 実測で効いたもの:
      alliance=STAR_ALLIANCE   (スターアライアンスだけ)
      airlines=<2 字 code>     (1 社だけ、 例 airlines=LH)
    複数条件の組み合わせ書式は未実測なので、 1 回に 1 条件で使う。
  Expedia は URL で絞り込みを指定せず、 結果画面左の「航空会社」 欄で絞る (実測)。
  Expedia に都市 code (TYO 等) を渡した動作は未実測 = 空港 code を推奨。

出力: サイトごとに 1 行 `<site>\t<URL>`。 検索の実行はしない (ネットワークに出ない)。

制約 (実測):
  - 往復・大人 1 名・エコノミーだけ。 片道・周遊・人数・座席クラスの URL 書式は検証していないので作らない。
  - Kayak は数回検索すると reCAPTCHA が出る。 出たら押さずに別サイトへ (conventions/flight-search.md#bot-checks)。
  - 価格は時間で変わる。 URL を開いた時刻 (現地時刻) を価格と一緒に記録する。
"""
import argparse
import re
import sys
from urllib.parse import quote

CODE_RE = re.compile(r"^[A-Z]{3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def kayak_url(orig, dest, d1, d2, fs=None):
    path = f"https://www.kayak.co.jp/flights/{orig}-{dest}/{d1}/{d2}"
    q = "?sort=price_a"
    if fs:
        q += "&fs=" + quote(fs, safe="=_;")
    return path + q


def expedia_url(orig, dest, d1, d2):
    def leg(a, b, d):
        return f"from:{a},to:{b},departure:{d.replace('-', '/')}TANYT"
    return (
        "https://www.expedia.co.jp/Flights-Search?trip=roundtrip"
        f"&leg1={leg(orig, dest, d1)}&leg2={leg(dest, orig, d2)}"
        "&passengers=adults:1&options=cabinclass:economy&mode=search"
    )


def validate(orig, dest, d1, d2):
    errs = []
    for name, v in (("出発", orig), ("到着", dest)):
        if not CODE_RE.match(v):
            errs.append(f"{name} は 3 文字の大文字 code: {v!r}")
    for name, v in (("往路", d1), ("復路", d2)):
        if not DATE_RE.match(v):
            errs.append(f"{name} は YYYY-MM-DD: {v!r}")
    if not errs and d2 < d1:
        errs.append(f"復路 {d2} が往路 {d1} より前")
    return errs


def selftest():
    fails = 0

    def check(cond, label):
        nonlocal fails
        print(("ok   " if cond else "FAIL ") + label)
        fails += 0 if cond else 1

    # 合成例 (実在の予定ではない)。 期待値は実測で結果画面まで開いた URL と同じ書式。
    check(kayak_url("NRT", "CDG", "2027-03-01", "2027-03-08")
          == "https://www.kayak.co.jp/flights/NRT-CDG/2027-03-01/2027-03-08?sort=price_a", "kayak 基本")
    check(kayak_url("TYO", "CDG", "2027-03-01", "2027-03-08", fs="alliance=STAR_ALLIANCE")
          == "https://www.kayak.co.jp/flights/TYO-CDG/2027-03-01/2027-03-08?sort=price_a&fs=alliance=STAR_ALLIANCE",
          "kayak alliance filter")
    check(kayak_url("NRT", "CDG", "2027-03-01", "2027-03-08", fs="airlines=LH").endswith("&fs=airlines=LH"),
          "kayak airline filter")
    check(expedia_url("NRT", "CDG", "2027-03-01", "2027-03-08")
          == "https://www.expedia.co.jp/Flights-Search?trip=roundtrip&leg1=from:NRT,to:CDG,departure:2027/03/01TANYT"
             "&leg2=from:CDG,to:NRT,departure:2027/03/08TANYT&passengers=adults:1&options=cabinclass:economy&mode=search",
          "expedia 基本 (復路は出発・到着を入れ替える)")
    check(validate("nrt", "CDG", "2027-03-01", "2027-03-08") != [], "小文字 code を弾く")
    check(validate("NRT", "CDG", "2027-03-08", "2027-03-01") != [], "復路が往路より前を弾く")
    check(validate("NRT", "CDG", "2027/03/01", "2027-03-08") != [], "日付の区切りを弾く")
    check(validate("NRT", "CDG", "2027-03-01", "2027-03-08") == [], "正しい入力は通す")
    print(f"{'PASS' if fails == 0 else 'FAIL'} ({fails} failed)")
    return 0 if fails == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="航空券の往復検索 URL を作る (Kayak / Expedia)")
    ap.add_argument("orig", nargs="?")
    ap.add_argument("dest", nargs="?")
    ap.add_argument("depart", nargs="?")
    ap.add_argument("ret", nargs="?")
    ap.add_argument("--site", choices=["kayak", "expedia", "all"], default="all")
    ap.add_argument("--kayak-filter")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not all((a.orig, a.dest, a.depart, a.ret)):
        ap.error("出発 到着 往路 復路 の 4 つが要る")
    errs = validate(a.orig, a.dest, a.depart, a.ret)
    if errs:
        for e in errs:
            print(f"error: {e}", file=sys.stderr)
        return 2
    if a.site in ("kayak", "all"):
        print("kayak\t" + kayak_url(a.orig, a.dest, a.depart, a.ret, a.kayak_filter))
    if a.site in ("expedia", "all"):
        if a.kayak_filter and a.site == "expedia":
            print("note: --kayak-filter は Expedia には効かない (結果画面で絞る)", file=sys.stderr)
        print("expedia\t" + expedia_url(a.orig, a.dest, a.depart, a.ret))
    return 0


if __name__ == "__main__":
    sys.exit(main())
