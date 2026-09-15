#!/usr/bin/env python3
"""fx-ttm-jpy.py — 指定日の三菱UFJ銀行 公表相場 (TTS / TTB) を取り、 TTM = (TTS+TTB)/2 で外貨額を円に換算する。 --selftest 内蔵。

Why: 大学の研究費で外貨の立替 (海外会議の参加費・海外の書籍やソフト) を精算するとき、 規程が
「購入日の TTM で円換算」 と決めていることが多い。 カード明細の円額やカード会社のレートは TTM ではないので
そのまま書くと合わない。 TTM を手で探して掛け算すると、 日付・通貨単位 (100 通貨単位の通貨)・休日の扱いを
取り違える。

源: 三菱UFJリサーチ&コンサルティング「1990年以降の為替相場」 (公表相場の日次ページ、 Shift_JIS)。
  https://www.murc-kawasesouba.jp/fx/past/index.php?id=YYMMDD
  ページ自身が「公表仲値（TTM）は（TTS＋TTB）/2 で算出」 と明記している。 TTM の列は無いので本 script が計算する。
  「*1」 印の通貨 (KRW 等) と IDR は 100 通貨単位あたりの円。 本 script は 1 通貨単位に直してから掛ける。

見出し: 当日のページは「YYYY年M月D日現在」、 過去の日のページは「YYYY年M月D日の為替相場」 (実測)。 どちらも日付として読み、
  表の日付が要求日と違うページは採らない。
休日: 公表が無い日 (土日・銀行休業日) のページは表を持たない。 既定では前日へ最大 7 日さかのぼり、
  使った日付を明示する。 **休日の扱い (前営業日か翌営業日か) は規程しだい** なので、 さかのぼった場合は
  結果に ⚠️ を付ける。 `--no-fallback` なら公表が無い日は exit 2。

丸め: 円未満の扱いも規程しだい。 本 script は換算額そのものと、 切り捨て / 四捨五入 / 切り上げの 3 つを並べる
  (どれを使うかは決めない)。

使い方:
  fx-ttm-jpy.py 2025-04-01 EUR 250          # TTS / TTB / TTM と円換算
  fx-ttm-jpy.py 2025-04-01 USD 120.50 --json
  fx-ttm-jpy.py 2025-04-05 EUR 80 --no-fallback
  fx-ttm-jpy.py --selftest

終了コード: 0 = 換算できた / 2 = 公表が無い・通貨が無い / 3 = 取得失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Callable

URL = "https://www.murc-kawasesouba.jp/fx/past/index.php?id={yymmdd}"
MAX_BACK_DAYS = 7

ROW = re.compile(
    r"<tr>\s*<td>[^<]*</td>\s*<td>[^<]*</td>\s*"
    r'<td class="t_center">\s*([A-Z]{3})\s*</td>\s*'
    r'<td class="t_right">\s*([0-9.,-]*)\s*</td>\s*'
    r'<td class="t_right">\s*([0-9.,-]*)\s*</td>\s*'
    r'<td class="t_center">\s*([^<]*?)\s*</td>',
    re.S,
)
AS_OF = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:現在|の為替相場)")   # 当日ページ = 「現在」 / 過去の日 = 「の為替相場」 (実測)


def fetch(day: dt.date) -> str:
    req = urllib.request.Request(URL.format(yymmdd=day.strftime("%y%m%d")),
                                 headers={"User-Agent": "fx-ttm-jpy/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return raw.decode("shift_jis", errors="replace")


def parse(page: str) -> tuple[dt.date | None, dict[str, dict]]:
    """ページから (公表日, {通貨: {tts, ttb, per_100}}) を返す。 表が無ければ (None, {})。"""
    m = AS_OF.search(page)
    as_of = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    rates: dict[str, dict] = {}
    for code, tts, ttb, mark in ROW.findall(page):
        if not tts or not ttb or tts.strip("-") == "" or ttb.strip("-") == "":
            continue
        mark = html.unescape(mark)
        rates[code] = {
            "tts": Decimal(tts.replace(",", "")),
            "ttb": Decimal(ttb.replace(",", "")),
            "per_100": code == "IDR" or "*1" in mark or "*3" in mark,
        }
    if as_of is None:
        return None, {}
    return as_of, rates


def lookup(day: dt.date, currency: str, fallback: bool,
           fetcher: Callable[[dt.date], str] = fetch) -> dict:
    tried = []
    for back in range(MAX_BACK_DAYS + 1 if fallback else 1):
        d = day - dt.timedelta(days=back)
        as_of, rates = parse(fetcher(d))
        tried.append(d.isoformat())
        if as_of is None or not rates:
            continue
        if as_of != d:
            continue
        if currency not in rates:
            raise LookupError(f"{d.isoformat()} の公表相場に {currency} がありません (載っている通貨: {', '.join(sorted(rates))})")
        r = rates[currency]
        return {"requested": day.isoformat(), "rate_date": d.isoformat(), "fell_back": d != day,
                "currency": currency, "tts": r["tts"], "ttb": r["ttb"], "per_100": r["per_100"]}
    raise LookupError(f"公表相場が見つかりません (試した日: {', '.join(tried)})")


def convert(res: dict, amount: Decimal) -> dict:
    ttm = (res["tts"] + res["ttb"]) / 2
    unit = Decimal(100) if res["per_100"] else Decimal(1)
    jpy = amount * ttm / unit
    return {**res, "ttm": ttm, "amount": amount, "jpy": jpy,
            "jpy_floor": jpy.to_integral_value(ROUND_FLOOR),
            "jpy_round": jpy.to_integral_value(ROUND_HALF_UP),
            "jpy_ceil": jpy.to_integral_value(ROUND_CEILING)}


def render(c: dict) -> str:
    unit = " (100 通貨単位あたり)" if c["per_100"] else ""
    lines = [
        f"公表日 {c['rate_date']}  {c['currency']}{unit}  TTS {c['tts']}  TTB {c['ttb']}  TTM {c['ttm']}",
        f"{c['amount']} {c['currency']} × TTM = {c['jpy']} 円",
        f"  切り捨て {c['jpy_floor']} / 四捨五入 {c['jpy_round']} / 切り上げ {c['jpy_ceil']}  (どれを使うかは規程で)",
        "  源 = 三菱UFJ銀行 公表相場 (三菱UFJリサーチ&コンサルティング掲載)",
    ]
    if c["fell_back"]:
        lines.insert(0, f"⚠️ {c['requested']} は公表なし → {c['rate_date']} の相場を使用。 休日の扱いは規程で確認")
    return "\n".join(lines)


def selftest() -> int:
    def page(day: dt.date, rows: str) -> str:
        return (f"<h2>{day.year}年{day.month}月{day.day}日現在　As of</h2><table class=\"data-table5\">"
                + rows + "</table>")

    def row(code: str, tts: str, ttb: str, mark: str = "") -> str:
        return (f"<tr>\n<td>Name</td>\n<td>名</td>\n<td class=\"t_center\">{code}</td>\n"
                f"<td class=\"t_right\">{tts} </td>\n<td class=\"t_right\">{ttb} </td>\n"
                f"<td class=\"t_center\">{mark}</td>\n</tr>")

    mon = dt.date(2025, 3, 3)
    pages = {
        mon: page(mon, row("GBP", "200.13", "190.00") + row("KRW", "10.00", "9.60", "*1")
                  + row("IDR", "1.08", "0.88", "*3") + row("XXX", "-", "-")),
        dt.date(2025, 3, 2): "<h2>三菱UFJ銀行公表の対顧客外国為替相場</h2>",   # 休日 = 表なし
        dt.date(2025, 3, 1): "<h2>三菱UFJ銀行公表の対顧客外国為替相場</h2>",
    }
    fetcher = lambda d: pages.get(d, "<h2>no data</h2>")
    fails = 0

    def check(name: str, cond: bool) -> None:
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name)
        fails += 0 if cond else 1

    c = convert(lookup(mon, "GBP", True, fetcher), Decimal("250"))
    check("TTM = (TTS+TTB)/2", c["ttm"] == Decimal("195.065"))
    check("GBP 250 → 48766.25 円", c["jpy"] == Decimal("48766.25"))
    check("丸め 3 種", (c["jpy_floor"], c["jpy_round"], c["jpy_ceil"]) == (48766, 48766, 48767))
    check("当日公表なら fell_back=False", c["fell_back"] is False)
    k = convert(lookup(mon, "KRW", True, fetcher), Decimal("10000"))
    check("*1 通貨は 100 単位あたり", k["per_100"] and k["jpy"] == Decimal("980"))
    i = convert(lookup(mon, "IDR", True, fetcher), Decimal("100"))
    check("IDR (*3) も 100 単位あたり", i["per_100"] and i["jpy"] == Decimal("0.98"))
    none_week = {}
    try:
        lookup(dt.date(2025, 3, 2), "GBP", True, lambda d: none_week.get(d, "<h2>休</h2>"))
        check("7 日さかのぼっても無ければ LookupError", False)
    except LookupError:
        check("7 日さかのぼっても無ければ LookupError", True)
    sun = dt.date(2025, 3, 9)
    past = lambda day, rows: (f"<h2>{day.year}年{day.month}月{day.day}日の為替相場　As of</h2>"
                              f"<table class=\"data-table7\">{rows}</table>")
    pages2 = {dt.date(2025, 3, 7): past(dt.date(2025, 3, 7), row("GBP", "210.00", "202.00"))}
    fb2 = lookup(sun, "GBP", True, lambda d: pages2.get(d, "<h2>休</h2>"))
    check("日曜 → 金曜の相場、 fell_back=True", fb2["rate_date"] == "2025-03-07" and fb2["fell_back"])
    check("過去日ページの見出し「…日の為替相場」 も日付として読む", parse(pages2[dt.date(2025, 3, 7)])[0] == dt.date(2025, 3, 7))
    try:
        lookup(sun, "GBP", False, lambda d: pages2.get(d, "<h2>休</h2>"))
        check("--no-fallback で休日は失敗", False)
    except LookupError:
        check("--no-fallback で休日は失敗", True)
    wrongday = {sun: page(dt.date(2025, 3, 7), row("GBP", "1", "1"))}
    try:
        lookup(sun, "GBP", False, lambda d: wrongday.get(d, ""))
        check("表の日付が要求日と違うページは採らない", False)
    except LookupError:
        check("表の日付が要求日と違うページは採らない", True)
    try:
        lookup(mon, "ZZZ", True, fetcher)
        check("無い通貨は LookupError", False)
    except LookupError:
        check("無い通貨は LookupError", True)
    check("'-' 行は読み飛ばす", "XXX" not in parse(pages[mon])[1])
    print(f"{'OK' if fails == 0 else 'NG'}: {fails} failure(s)")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("date", nargs="?", help="YYYY-MM-DD (購入日・支払日)")
    ap.add_argument("currency", nargs="?", help="通貨コード (GBP / USD / EUR ...)")
    ap.add_argument("amount", nargs="?", help="外貨額")
    ap.add_argument("--no-fallback", action="store_true", help="公表が無い日にさかのぼらない")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.date and a.currency and a.amount):
        ap.error("date currency amount が要ります")
    day = dt.date.fromisoformat(a.date)
    try:
        res = lookup(day, a.currency.upper(), not a.no_fallback)
    except LookupError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"❌ 取得失敗: {e}", file=sys.stderr)
        return 3
    c = convert(res, Decimal(a.amount))
    if a.json:
        print(json.dumps({k: (str(v) if isinstance(v, Decimal) else v) for k, v in c.items()}, ensure_ascii=False))
    else:
        print(render(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
