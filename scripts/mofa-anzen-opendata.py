#!/usr/bin/env python3
"""外務省の海外安全情報を、 公開データ (国ごとの XML) から読む = 危険レベル・最終変更・領事メールと広域情報の一覧と本文。--selftest 内蔵。

なぜ層1 にあるか
----------------
海外安全ホームページ (anzen.mofa.go.jp) の頁は JavaScript で組まれ、 WebFetch は 403 を返す (実測)。
同じ外務省が出している公開データの XML (ezairyu.mofa.go.jp/opendata/country/<国番号>.xml) は認証なしで
1 回の取得に全部が入る (実測): 危険レベルのある地域の印・最終変更の日・見出しと要旨・頁の URL と、
その国に出た領事メール (一般・緊急)・広域情報・危険情報の題・日付・送り主の公館・本文。 browser を開かずに済む。

読み方の罠:
  1. **riskLevel1〜4 は「その段の地域がある」 の印 (0/1) で、 件数ではない** — 国の中で地域ごとに段が違う。
     どの地域がどの段かは危険情報の本文 (`--show 危険情報`) の「地域別情勢」 を読む。
  2. **段の値が変わらないまま、 手間のかかる手順だけが先に動くことがある** — 在留邦人への在留状況の調査
     (「万が一の事態に備え」) は退避の段取りの前段。 段の値だけを見ると見落とす (実測)。 一覧では ❗ を付ける。
  3. **国番号 = 電話の国番号を 0 で 4 桁にした数** (実測)。 違う番号は 404 になる。
  4. 取得した XML は取得した時点の写し。 判断の根拠に使うなら `--save-dir` で保存し、 記録から指す。

使い方
------
  mofa-anzen-opendata.py CODE [CODE ...] [--mails 10] [--since YYYY-MM-DD]
        国ごとに 危険レベルの要約 + 新しい順の通知の一覧 (❗ = 緊急・退避の段取りの語を含む)
  mofa-anzen-opendata.py CODE --show 語 [--max-chars 3000]
        題に「語」 を含む通知の本文 (要旨 + 本文)。 危険情報の本文は --show 危険情報
  mofa-anzen-opendata.py CODE --save-dir DIR       取得した XML を DIR/<国番号>-<取得日>.xml に保存
  mofa-anzen-opendata.py --file X.xml [...]        保存した XML を読む (network に出ない)
  mofa-anzen-opendata.py --selftest                network に出ない検査
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

URL = "https://www.ezairyu.mofa.go.jp/opendata/country/{code}.xml"
UA = "mofa-anzen-opendata/1.0"
ALERT_WORDS = ("在留状況調査", "退避", "出国", "航空便の確保", "国外へ", "渡航中止")  # 題で見る語
ALERT_BODY_WORDS = ("在留状況調査", "退避")  # 本文の冒頭で見る語 (出国は査証の通知にも出る = 誤検出、 実測)


def _tag(e: ET.Element) -> str:
    return e.tag.split("}")[-1]


def _text(e: ET.Element | None) -> str:
    return (e.text or "").strip() if e is not None else ""


def _plain(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", html.unescape(s or ""))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def fetch(code: str, timeout: int = 60) -> bytes:
    if not re.fullmatch(r"\d{4}", code):
        raise SystemExit(f"国番号は 4 桁の数字 (電話の国番号を 0 で 4 桁に): {code!r}")
    req = urllib.request.Request(URL.format(code=code), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse(data: bytes) -> dict:
    root = ET.fromstring(data)
    top = {_tag(c): c for c in root}
    country = top.get("country")
    name = ""
    if country is not None:
        for c in country:
            if _tag(c) == "name":
                name = _text(c)
    levels = [n for n in (1, 2, 3, 4) if _text(top.get(f"riskLevel{n}")) == "1"]
    mails = []
    for e in root:
        if _tag(e) != "mail":
            continue
        d = {_tag(c): c for c in e}
        mails.append({
            "date": _text(d.get("leaveDate")),
            "type": _text(d.get("infoType")),
            "kind": _text(d.get("infoName")),
            "sender": _text(d.get("koukanName")),
            "title": _text(d.get("title")),
            "body": _plain(_text(d.get("lead")) + "\n" + _text(d.get("mainText"))),
        })
    seen, uniq = set(), []
    for m in mails:  # 同じ通知が 2 回入っていることがある (実測) = 日付と題で 1 件に
        k = (m["date"], m["title"])
        if k not in seen:
            seen.add(k)
            uniq.append(m)
    mails = sorted(uniq, key=lambda m: m["date"], reverse=True)
    return {
        "name": name,
        "modified": root.attrib.get("lastModified", ""),
        "levels": levels,
        "risk_date": _text(top.get("riskLeaveDate")),
        "risk_title": _text(top.get("riskTitle")),
        "risk_lead": _plain(_text(top.get("riskLead"))),
        "risk_url": _text(top.get("riskUrl")),
        "mails": mails,
    }


def _alert(m: dict) -> bool:
    return (m["type"] == "R20" or any(w in m["title"] for w in ALERT_WORDS)
            or any(w in m["body"][:600] for w in ALERT_BODY_WORDS))


def summary(code: str, info: dict, n_mails: int, since: str | None) -> str:
    out = [f"== {code} {info['name']}  (データの最終更新 {info['modified']})"]
    lv = "・".join(str(n) for n in info["levels"]) or "なし"
    top = max(info["levels"]) if info["levels"] else 0
    out.append(f"危険レベルのある地域の段: {lv} (最も高い段 = {top}。 地域ごとの段は --show 危険情報)")
    out.append(f"危険情報の最終変更: {info['risk_date']}  {info['risk_title']}")
    if info["risk_lead"]:
        out.append("  " + info["risk_lead"][:400].replace("\n", "\n  "))
    if info["risk_url"]:
        out.append(f"  {info['risk_url']}")
    ms = [m for m in info["mails"] if not since or m["date"][:10].replace("/", "-") >= since]
    out.append(f"通知 (新しい順、 {min(n_mails, len(ms))}/{len(ms)} 件。 ❗ = 緊急か退避の段取りの語):")
    for m in ms[:n_mails]:
        mark = "❗" if _alert(m) else "  "
        out.append(f" {mark} {m['date'][:16]}  {m['kind']}  {m['sender']}  {m['title']}")
    return "\n".join(out)


def show(info: dict, word: str, max_chars: int) -> str:
    out = []
    for m in info["mails"]:
        if word in m["title"]:
            out.append(f"##### {m['date']}  {m['kind']}  {m['sender']}\n{m['title']}\n{m['body'][:max_chars]}\n")
    return "\n".join(out) or f"(題に {word!r} を含む通知は無い)"


SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<opendata lastModified="2099/01/02 03:04:05">
  <country><cd>0999</cd><name>架空国</name></country>
  <riskLevel1>1</riskLevel1><riskLevel2>1</riskLevel2><riskLevel3>0</riskLevel3><riskLevel4>0</riskLevel4>
  <riskLeaveDate>2099/01/01 00:00:00</riskLeaveDate>
  <riskTitle>架空国の危険情報【一部地域の引上げ】</riskTitle>
  <riskLead>●架空の州をレベル２に引き上げます。</riskLead>
  <riskUrl>https://example.invalid/risk</riskUrl>
  <mail><infoType>R10</infoType><infoName>領事メール(一般)</infoName><leaveDate>2099/01/02 10:00:00</leaveDate>
    <title>【要回答】情勢を踏まえた在留状況調査へのご協力のお願い</title><lead>万が一の事態に備え</lead><mainText>&lt;p&gt;回答期限&lt;/p&gt;</mainText>
    <koukanName>在架空国大使館</koukanName></mail>
  <mail><infoType>R10</infoType><infoName>領事メール(一般)</infoName><leaveDate>2098/12/01 10:00:00</leaveDate>
    <title>閉館日のお知らせ</title><lead>閉館します</lead><mainText></mainText><koukanName>在架空国大使館</koukanName></mail>
  <mail><infoType>T40</infoType><infoName>危険</infoName><leaveDate>2099/01/01 00:00:00</leaveDate>
    <title>架空国の危険情報【一部地域の引上げ】</title><lead>地域別情勢</lead><mainText>架空の州 レベル２</mainText><koukanName></koukanName></mail>
</opendata>
""".encode("utf-8")


def selftest() -> int:
    info = parse(SAMPLE)
    checks = [
        (info["name"] == "架空国", "国名"),
        (info["levels"] == [1, 2], "段の印 (0/1) を段の一覧に"),
        (info["mails"][0]["title"].startswith("【要回答】"), "新しい順"),
        (_alert(info["mails"][0]), "在留状況調査に ❗"),
        (not _alert(info["mails"][-1]), "閉館日に ❗ を付けない"),
        ("<p>" not in info["mails"][0]["body"], "本文の tag を落とす"),
        ("最も高い段 = 2" in summary("0999", info, 10, None), "要約の最も高い段"),
        ("3/3 件" in summary("0999", info, 10, None), "通知の件数"),
        ("1/1 件" in summary("0999", info, 10, "2099-01-02"), "--since で絞る"),
        ("架空の州 レベル２" in show(info, "危険情報", 500), "--show で本文"),
        ("含む通知は無い" in show(info, "存在しない語", 500), "--show の 0 件"),
    ]
    bad = [msg for ok, msg in checks if not ok]
    for msg in bad:
        print("FAIL:", msg)
    try:
        fetch("12")
        bad.append("4 桁でない国番号を止める")
    except SystemExit:
        pass
    print("selftest:", "OK" if not bad else f"{len(bad)} 件失敗")
    return 0 if not bad else 1


def main(argv: list[str]) -> int:
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("codes", nargs="*", help="国番号 (4 桁)")
    ap.add_argument("--file", action="append", default=[], help="保存した XML を読む")
    ap.add_argument("--mails", type=int, default=10)
    ap.add_argument("--since", help="YYYY-MM-DD 以降の通知だけ")
    ap.add_argument("--show", help="題にこの語を含む通知の本文を出す")
    ap.add_argument("--max-chars", type=int, default=3000)
    ap.add_argument("--save-dir", help="取得した XML の保存先")
    a = ap.parse_args(argv)
    if not a.codes and not a.file:
        ap.error("国番号か --file を 1 つ以上")
    sources = [(c, None) for c in a.codes] + [(os.path.basename(f), f) for f in a.file]
    rc = 0
    for code, path in sources:
        try:
            if path:
                with open(path, "rb") as fh:
                    data = fh.read()
            else:
                data = fetch(code)
                if a.save_dir:
                    os.makedirs(a.save_dir, exist_ok=True)
                    out = os.path.join(a.save_dir, f"{code}-{dt.date.today().isoformat()}.xml")
                    with open(out, "wb") as fh:
                        fh.write(data)
                    print(f"(保存 = {out})")
            info = parse(data)
        except Exception as e:  # 1 国の失敗で他の国を止めない
            print(f"== {code}: 取得・解析に失敗 = {e}")
            rc = 1
            continue
        print(show(info, a.show, a.max_chars) if a.show else summary(code, info, a.mails, a.since))
        print()
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
