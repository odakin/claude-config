#!/usr/bin/env python3
"""図書館に本があるかを OPAC で確かめた結果を、 証拠つきの台帳 (YAML) を正本として持ち、 引き直し・点検する。--selftest 内蔵。

なぜ道具にしたか
----------------
購入を頼む候補の本ごとに「その館に無いか」 を確かめると、 結果が候補リストの 1 欄と散文に散らばり、
外した本の根拠・引いた語・日付が残らない (実測)。 さらに:

  1. OPAC の一覧は 1 ページ目だけを見ると、 6 件目以降にある本を見落とす → ページをたどる。
  2. 書名だけ・著者名だけの検索は当たりが多すぎる → 「書名 著者」 の AND 検索と ISBN の両方で引く。
  3. 当たりの行は同名の別の本のことがある → 機械は「当たりあり (要目視)」 までにとどめ、 結論は人が決める。
  4. 候補を作ってから申し込むまでに、 館が同じ本を買うことがある → 申し込む直前に引き直す。

台帳の 1 件 = 1 冊 (版)。 候補に入れた本も、 所蔵ありで外した本も置く。
結論 (result) と扱い (decision) は人が決める欄。 refresh が書くのは証拠 (opac) と機械の読み (auto) だけで、
結論と食い違えば警告する。 check は「候補の全冊が台帳にあり、 申し込める結論か」 を見る (申込文の生成の前に呼ぶ)。

使い方
------
  library-holdings-ledger.py --config C.json refresh [--only 語 ...]
  library-holdings-ledger.py --config C.json check --require R.json     (R.json = [{"no": 1, "title": "...", "isbn": "978..."}], "-" で stdin)
  library-holdings-ledger.py --config C.json show [語 ...]
  library-holdings-ledger.py --selftest                                  network に出ない検査

設定 (C.json) — 館ごとの値はここだけに置く (使う側の非公開の記録):
  ledger          台帳 YAML の path (設定 file からの相対でも可)
  header          台帳の冒頭に書く説明の行 (list、 館名・関連 file など。 省略可)
  search_url      検索 URL。 {q} を語に置き換える
  hit_re          件数を取る正規表現 (group 1 = 件数)
  item_re         1 件ごとの行を取る正規表現 (最後の group = 行の本文)
  page            任意。 ページ送り = {"key_re": 検索結果から次ページ用の鍵を取る正規表現, "url": {start} と {key} を含む URL,
                  "size": 1 ページの件数, "max_pages": 何ページまで見るか}
  ebook_markers   行の末尾がこれなら電子ブック (例 = 館の表示語)。 それ以外の当たりは紙の図書とみなす
  pause           照会の間の秒数 (既定 0.6)

台帳の欄:
  title / author / isbn   書誌 (isbn は版ごとに複数可)
  list                    候補リストの番号 (候補でなければ null)
  result                  結論 = 所蔵なし / 図書 / 電子ブック / 旧版のみ / 訳書のみ
  decision / note         扱いと根拠の補足 (自由記述)
  paper_request           電子ブックだけある本を紙で頼む理由。 あれば result: 電子ブック でも候補にできる
  terms                   OPAC で引く「書名 著者」 の語 (ISBN と別に 1 つ以上)
  checked / auto / opac   refresh が書く (日付 / 機械の読み / 引いた語・件数・当たった行)

手順と判断の一般則 = conventions/book-purchase-lookup.md#holdings-ledger。 依存 = 標準ライブラリ + PyYAML。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

def _yaml_safe_load(stream):  # yaml.safe_load と同じ結果を C 版 (libyaml) で返す = 約 10 倍速 (2026-09-23)
    import yaml
    return yaml.load(stream, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
OK_RESULTS = {"所蔵なし", "旧版のみ", "訳書のみ"}  # 申し込んでよい結論
RESULTS = OK_RESULTS | {"図書", "電子ブック"}
AUTO_TITLE_HIT = "書名で当たりあり (要目視)"

FIELD_DOC = """\
# 欄 (道具 = claude-config/scripts/library-holdings-ledger.py、 保存のたびにこの冒頭は道具が書き出す):
#   title / author / isbn   書誌 (isbn は版ごとに複数可。 無い本は空)
#   list                    候補リストの番号。 候補にしていなければ null
#   result                  結論 (人が決める) = 所蔵なし / 図書 / 電子ブック / 旧版のみ / 訳書のみ
#   decision / note         扱い (人が決める) と結論の根拠の補足
#   paper_request           電子ブックだけある本を紙で頼む理由。 あれば result: 電子ブック でも候補にできる
#   terms                   OPAC で引く「書名 著者」 の語 (AND 検索)。 ISBN と別に 1 つ以上
#   checked / auto / opac   refresh が書く = 引いた日 / 機械の読み (所蔵なし・図書・電子ブック・書名で当たりあり) / 証拠 (語・件数・行 最大 5)
"""


# ---------------------------------------------------------------- config / ledger

def load_config(path: str) -> dict:
    p = Path(path).expanduser()
    c = json.loads(p.read_text())
    led = Path(c["ledger"]).expanduser()
    c["ledger"] = str(led if led.is_absolute() else (p.parent / led).resolve())
    return c


def load_ledger(cfg: dict) -> list[dict]:
    import yaml
    p = Path(cfg["ledger"])
    return (_yaml_safe_load(p.read_text()) or []) if p.exists() else []


def save_ledger(cfg: dict, entries: list[dict]) -> None:
    import yaml
    head = "".join(f"# {x}\n" for x in cfg.get("header", []))
    body = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=200)
    Path(cfg["ledger"]).write_text(head + "#\n" + FIELD_DOC + "\n" + body)


# ---------------------------------------------------------------- OPAC

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=40) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return r.read().decode("utf-8", "ignore")


def page_text(h: str) -> str:
    h = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)))


def parse_items(text: str, item_re: str) -> list[str]:
    out = []
    for m in re.finditer(item_re, text):
        out.append(m.group(m.lastindex or 0).strip())
    return out


def parse_hits(text: str, hit_re: str) -> int:
    m = re.search(hit_re, text)
    return int(m.group(1)) if m else 0


def opac_search(cfg: dict, q: str, get=fetch) -> tuple[int, list[str]]:
    """件数と全行 (設定があればページをたどる)。"""
    h = get(cfg["search_url"].replace("{q}", urllib.parse.quote(q)))
    t = page_text(h)
    n = parse_hits(t, cfg["hit_re"])
    items = parse_items(t, cfg["item_re"])
    pg = cfg.get("page")
    if pg and n > len(items):
        key = re.search(pg["key_re"], h)
        if key:
            size, maxp = int(pg.get("size", 50)), int(pg.get("max_pages", 6))
            for start in range(size + 1, min(n, size * maxp) + 1, size):
                time.sleep(cfg.get("pause", 0.6))
                items += parse_items(page_text(get(pg["url"].replace("{start}", str(start)).replace("{key}", key.group(1)))), cfg["item_re"])
    return n, items[:n] if n else []


def kind(cfg: dict, line: str) -> str:
    return "電子ブック" if any(line.rstrip().endswith(m) for m in cfg.get("ebook_markers", [])) else "図書"


# ---------------------------------------------------------------- judgement

def classify(cfg: dict, isbn_hits: list[tuple[int, list[str]]], term_hits: list[int]) -> str:
    for n, lines in isbn_hits:
        if n:
            return kind(cfg, lines[0]) if lines else "図書"
    return AUTO_TITLE_HIT if any(term_hits) else "所蔵なし"


def warnings_for(auto: str, result: str | None) -> list[str]:
    w = []
    if auto in ("図書", "電子ブック") and result in OK_RESULTS:
        w.append(f"ISBN で {auto} が当たったのに結論が {result}")
    if auto == AUTO_TITLE_HIT and result == "所蔵なし":
        w.append("書名 + 著者で当たりがあるのに結論が 所蔵なし (行を目で見て result か terms を直す)")
    if auto == "所蔵なし" and result in ("図書", "電子ブック"):
        w.append(f"OPAC で 0 件なのに結論が {result} (terms が合っているか)")
    return w


def refresh_entry(cfg: dict, e: dict, get=fetch) -> list[str]:
    ev, isbn_hits, term_hits = [], [], []
    for isbn in e.get("isbn") or []:
        n, lines = opac_search(cfg, str(isbn), get)
        ev.append({"q": str(isbn), "hits": n, "lines": [x[:200] for x in lines[:5]]})
        isbn_hits.append((n, lines))
        time.sleep(cfg.get("pause", 0.6))
    for term in e.get("terms") or []:
        n, lines = opac_search(cfg, term, get)
        ev.append({"q": term, "hits": n, "lines": [x[:200] for x in lines[:5]]})
        term_hits.append(n)
        time.sleep(cfg.get("pause", 0.6))
    auto = classify(cfg, isbn_hits, term_hits)
    e["opac"], e["auto"], e["checked"] = ev, auto, dt.date.today().isoformat()
    return warnings_for(auto, e.get("result"))


def check_required(entries: list[dict], required: list[dict]) -> list[str]:
    by_no = {e["list"]: e for e in entries if e.get("list")}
    want = {int(r["no"]): r for r in required}
    probs = []
    for n, r in sorted(want.items()):
        e, t = by_no.get(n), str(r.get("title", ""))[:30]
        if not e:
            probs.append(f"{n} {t}: 台帳に無い")
            continue
        if e.get("result") not in OK_RESULTS and not (e.get("result") == "電子ブック" and e.get("paper_request")):
            probs.append(f"{n} {t}: 結論が {e.get('result')} (申し込めない。 電子ブックを紙で頼むなら paper_request に理由)")
        if not e.get("opac") or not e.get("checked"):
            probs.append(f"{n} {t}: OPAC を引いた記録が無い")
        isbn = str(r.get("isbn") or "")
        if isbn not in ("", "—") and isbn not in [str(x) for x in e.get("isbn") or []]:
            probs.append(f"{n} {t}: 候補の ISBN {isbn} が台帳に無い")
    for n, e in by_no.items():
        if n not in want:
            probs.append(f"{n} {e['title'][:30]}: 台帳は候補 (list: {n}) だが候補リストに無い")
    return probs


# ---------------------------------------------------------------- commands

def label(e: dict) -> str:
    return f"{e.get('list') or '-':>3} {e['title'][:40]} / {str(e.get('author', ''))[:20]}"


def select(entries: list[dict], words: list[str]) -> list[dict]:
    if not words:
        return entries
    return [e for e in entries
            if any(w in f"{e['title']} {e.get('author', '')} {e.get('list')} {' '.join(map(str, e.get('isbn') or []))}" for w in words)]


def cmd_refresh(cfg: dict, a) -> int:
    entries, bad = load_ledger(cfg), 0
    for e in select(entries, a.only):
        for w in refresh_entry(cfg, e):
            print(f"⚠️ {label(e)}: {w}")
            bad += 1
        print(f"{e['auto']:<18} 結論={e.get('result')}  {label(e)}", flush=True)
        save_ledger(cfg, entries)  # 途中で止まっても引いた分は残す
    return 1 if bad else 0


def cmd_check(cfg: dict, a) -> int:
    raw = sys.stdin.read() if a.require == "-" else Path(a.require).read_text()
    required = json.loads(raw)
    probs = check_required(load_ledger(cfg), required)
    for p in probs:
        print("❌ " + p)
    print(f"check: 候補 {len(required)} 冊、 問題 {len(probs)} 件")
    return 1 if probs else 0


def cmd_show(cfg: dict, a) -> int:
    for e in select(load_ledger(cfg), a.words):
        print(f"{e.get('result', '?'):<6} {e.get('checked', '')} {label(e)}  [{e.get('decision', '')}]")
    return 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    ok = True

    def check(cond, name):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    # 合成の OPAC (架空の書名・著者)。 1 ページ 2 件、 全 3 件でページ送りが要る
    cfg = {"search_url": "https://opac.example/s?q={q}", "hit_re": r"該当件数:(\d+)件",
           "item_re": r" (\d+)\. (.*?)(?= \d+\. | 以上|$)", "ebook_markers": ["電子ブック"], "pause": 0,
           "page": {"key_re": r"key=([A-Z0-9]+)", "url": "https://opac.example/p?start={start}&key={key}", "size": 2, "max_pages": 5}}
    pages = {
        "https://opac.example/s?q=%E6%9E%B6%E7%A9%BA": "<p>該当件数:3件</p> 1. 架空の本 / 甲野太郎 図書 2. 架空の続き / 甲野太郎 電子ブック 以上 <a href='p?key=K1'>次</a>",
        "https://opac.example/p?start=3&key=K1": "<p>該当件数:3件</p> 3. 架空の別巻 / 乙山花子 図書 以上",
        "https://opac.example/s?q=0000": "<p>該当する資料はありません</p>",
    }
    n, items = opac_search(cfg, "架空", get=lambda u: pages[u])
    check(n == 3 and len(items) == 3 and items[2].startswith("架空の別巻"), "OPAC: 2 ページ目までたどって 3 行")
    check(opac_search(cfg, "0000", get=lambda u: pages[u]) == (0, []), "OPAC: 件数が無ければ 0")
    check(kind(cfg, "架空の続き / 甲野太郎 電子ブック") == "電子ブック" and kind(cfg, "架空の本 図書") == "図書", "電子ブックの見分け")
    check(classify(cfg, [(1, ["x 電子ブック"])], [0]) == "電子ブック", "ISBN の当たりは区分で読む")
    check(classify(cfg, [(0, [])], [2]) == AUTO_TITLE_HIT, "書名だけの当たりは要目視")
    check(classify(cfg, [(0, [])], [0]) == "所蔵なし", "どれも 0 件なら所蔵なし")
    check(warnings_for("図書", "所蔵なし") and not warnings_for(AUTO_TITLE_HIT, "旧版のみ"), "結論との食い違いだけ警告")
    ents = [{"title": "架空の本", "list": 1, "isbn": ["9780000000002"], "result": "所蔵なし", "opac": [{"q": "x"}], "checked": "2000-01-01"},
            {"title": "架空の続き", "list": 2, "isbn": [], "result": "電子ブック", "paper_request": "式が多い", "opac": [{"q": "x"}], "checked": "2000-01-01"},
            {"title": "架空の別巻", "list": 3, "isbn": [], "result": "図書", "opac": [{"q": "x"}], "checked": "2000-01-01"}]
    req = [{"no": 1, "title": "架空の本", "isbn": "9780000000002"}, {"no": 2, "title": "架空の続き", "isbn": ""}]
    probs = check_required(ents, req)
    check(len(probs) == 1 and "3 " in probs[0], "check: 電子ブック + paper_request は通し、 候補外の list 番号を指摘")
    probs2 = check_required(ents, req + [{"no": 3, "title": "架空の別巻", "isbn": ""}])
    check(len(probs2) == 1 and "結論が 図書" in probs2[0], "check: 所蔵ありは申し込めない")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv == ["--selftest"]:
        return selftest()
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--config", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--only", nargs="*", default=[])
    c = sub.add_parser("check")
    c.add_argument("--require", required=True)
    s = sub.add_parser("show")
    s.add_argument("words", nargs="*")
    a = p.parse_args(argv)
    cfg = load_config(a.config)
    for e in load_ledger(cfg):
        if e.get("result") and e["result"] not in RESULTS:
            print(f"❌ 結論の語が決まりの外: {e['result']} ({e['title']})")
            return 2
    return {"refresh": cmd_refresh, "check": cmd_check, "show": cmd_show}[a.cmd](cfg, a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
