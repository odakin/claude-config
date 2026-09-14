#!/usr/bin/env python3
"""PDF の本文を grep できる plain text にする — 合字・行末ハイフン・柱・頁番号を直し、直した数を報告する。--selftest 内蔵 (network 不要)。

なぜ層1 にあるか
----------------
論文 PDF を「読んで引用する」ために text 化する場面は繰り返し来る (原典の照合、逐語引用、
用語の grep、訳の突き合わせ)。 素の `page.get_text()` は 3 つの壊れ方を必ずする:

  1. **合字** — `ﬁ ﬂ ﬀ ﬃ ﬄ` がそのまま残り、`fi` で grep しても当たらない。
  2. **行末ハイフン** — `broad-\nest` が 2 語に割れる。 連続行にまたがると 1 回の置換では取り切れない。
  3. **柱と頁番号** — 各頁の著者名・題・数字が本文の途中に挟まり、段落が切れる。

公開エッセイを text 化したとき、 同じ処理を inline python で 2 回書き、 1 回目は連続ハイフンを
取りこぼした (`dis- cussion` 型の残留、 実測)。 同じ形が次にも要るので層1 へ。

⚠️ **この script は組版を復元しない**。 段落は PDF に情報が無いので、既定では行を保つ。
`--reflow` は 1 本の stream にし、`--para-starts` で与えた**書き出しの語**でだけ段落を切る
(= 人が本文を見て並べる。 推測で切らない)。 表・多段組は射程外
(層3 の PDF 表読みの ladder = `office-automation.md#pdf-table-layout-aware-reading`)。

使い方
------
  pdf-to-text.py paper.pdf -o paper.txt              # 行を保ったまま修復
  pdf-to-text.py paper.pdf --reflow --para-starts starts.txt -o paper.txt
  pdf-to-text.py paper.pdf --keep-hyphen few- --keep-hyphen self-   # 結合しない行末
  pdf-to-text.py paper.pdf --json                    # 修復の内訳だけ見る
  pdf-to-text.py --selftest

報告 (stderr、`--json` なら stdout): 頁数 / 合字 N 件 / ハイフン結合 N 件 / 除いた柱の行 /
除いた頁番号 N 件 / **結合で怪しくなった語** (= 合字展開を含む長い語。 直さず報告だけする)。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
PAGE_NUMBER = re.compile(r"^[\divxlcDIVXLC]{1,5}$")
HYPHEN_BREAK = re.compile(r"(\w)-\n\s*(\w)")   # 頁境界の空行をまたぐ分割も結合する
SUSPICIOUS = re.compile(r"\b\w*(?:ff|fi|fl)\w*\b")


def expand_ligatures(text: str) -> tuple[str, int]:
    n = sum(text.count(k) for k in LIGATURES)
    for k, v in LIGATURES.items():
        text = text.replace(k, v)
    return text, n


def join_hyphenation(text: str, keep: set[str]) -> tuple[str, int, int]:
    """Join `word-\\nrest` into `wordrest`, repeatedly (consecutive breaks and page breaks).

    A fragment listed in `keep` (e.g. `few-`) is a real compound hyphen: the line break is still
    removed, but the hyphen is kept, so `few-\\nsentence` becomes `few-sentence`, not `fewsentence`.
    """
    joined = kept = 0
    while True:
        out, hit = [], False
        pos = 0
        for m in HYPHEN_BREAK.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            tail = text[line_start:m.end(1) + 1].split()   # the fragment, e.g. ["The", "few-"]
            real = bool(tail) and tail[-1] in keep
            out.append(text[pos:m.start(1) + 1])           # up to and including the letter
            out.append(("-" if real else "") + m.group(2))
            pos = m.end()
            hit = True
            joined += 0 if real else 1
            kept += 1 if real else 0
        if not hit:
            break
        out.append(text[pos:])
        text = "".join(out)
    return text, joined, kept


def strip_repeats(pages: list[str], min_pages: int) -> tuple[list[str], list[str], int]:
    """Drop running headers/footers (same short line on >= min_pages pages) and page numbers."""
    counts = Counter()
    for p in pages:
        for line in {l.strip() for l in p.split("\n") if l.strip()}:
            if len(line) <= 90:
                counts[line] += 1
    repeats = {l for l, c in counts.items() if c >= min_pages and not PAGE_NUMBER.match(l)}
    numbers = 0
    out = []
    for p in pages:
        kept = []
        for line in p.split("\n"):
            s = line.strip()
            if s in repeats:
                continue
            if PAGE_NUMBER.match(s):
                numbers += 1
                continue
            kept.append(line)
        out.append("\n".join(kept))
    return out, sorted(repeats), numbers


def reflow(text: str, para_starts: list[str]) -> str:
    stream = re.sub(r"\s+", " ", text).strip()
    if not para_starts:
        return stream
    for st in sorted(para_starts, key=len, reverse=True):
        stream = re.sub(r"(?<=[.\):”\"]) " + re.escape(st), "\n\n" + st, stream)
        if stream.startswith(st):
            continue
    return stream


def convert(pdf: Path, *, keep_hyphen=(), do_reflow=False, para_starts=(), strip=True,
            min_repeat_pages=0, replace=(), prepend=""):
    import fitz  # PyMuPDF; imported here so --selftest can report a clear error

    doc = fitz.open(pdf)
    pages = [p.get_text() for p in doc]
    report = {"pdf": str(pdf), "pages": len(pages)}
    dropped, numbers = [], 0
    if strip and len(pages) > 1:
        thr = min_repeat_pages or max(2, math.ceil(0.6 * len(pages)))
        pages, dropped, numbers = strip_repeats(pages, thr)
        report["repeat_threshold"] = thr
    text = "\n".join(pages)
    text, lig = expand_ligatures(text)
    text, joins, kept_hyphens = join_hyphenation(text, set(keep_hyphen))
    if do_reflow:
        text = reflow(text, list(para_starts))
    applied = 0
    for pair in replace:
        old, _, new = pair.partition("=")
        n = text.count(old)
        text, applied = text.replace(old, new), applied + n
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    if prepend:
        text = prepend.rstrip("\n") + "\n\n" + text
    # 合字の直後で空白が落ちた語 (`offas` = off as) は PDF 側の欠落で、script は直せない。
    # 短い語ほど疑わしい (長い語は difference / sufficiently のような実在語) ので昇順で出す。
    sus = sorted({w for w in SUSPICIOUS.findall(text) if len(w) >= 4}, key=lambda w: (len(w), w))
    report.update(ligatures=lig, hyphen_joins=joins, dropped_lines=dropped,
                  page_numbers=numbers, replacements=applied, kept_hyphens=kept_hyphens,
                  suspicious=sus)
    return text, report


def selftest() -> int:
    """合字は純関数として、それ以外は実 PDF を作って検査する。base-14 font は合字も em dash も
    符号化できず `·` に化けるので、PDF 経由では合字修復を確かめられない (実測)。"""
    import tempfile
    checks = []

    # 1. 純関数: 合字展開
    got, n = expand_ligatures("the diﬀerence is a ﬁne ﬂow, oﬃce, baﬄe")
    checks.append(("ligature expanded", got == "the difference is a fine flow, office, baffle"))
    checks.append(("ligature count", n == 5))

    # 2. 純関数: 連続ハイフン・頁境界・keep
    got, j, k = join_hyphenation("a broad-\nest and a dis-\n\ncussion of the few-\nsentence", {"few-"})
    checks.append(("hyphen joined", "broadest" in got))
    checks.append(("page-break hyphen joined", "discussion" in got))
    checks.append(("keep-hyphen keeps the hyphen, drops the break", "few-sentence" in got))
    checks.append(("counts", (j, k) == (2, 1)))
    foil, _, _ = join_hyphenation("the few-\nsentence summary", set())
    checks.append(("foil: keep なしなら結合する", "fewsentence" in foil))

    # 3. PDF: 抽出・柱・頁番号・reflow (ASCII のみ = base-14 font で化けない範囲)
    try:
        import fitz
    except ImportError:
        print("selftest: PyMuPDF (fitz) が要る", file=sys.stderr)
        return 2
    doc = fitz.open()
    head = "R. Author - Suggestions For Giving Talks"
    lines = [("the argument is of the broad-", "est kind, and a dis-"),
             ("cussion of the effect follows.", "A second paragraph starts here.")]
    for i, (x, y) in enumerate(lines, start=1):
        page = doc.new_page()
        page.insert_text((72, 60), head, fontsize=9)
        page.insert_text((72, 100), x, fontsize=11)
        page.insert_text((72, 120), y, fontsize=11)
        page.insert_text((300, 760), str(i), fontsize=9)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        doc.save(fh.name)
        path = Path(fh.name)

    text, rep = convert(path)
    checks += [
        ("running head dropped", head not in text),
        ("head reported", head in rep["dropped_lines"]),
        ("page numbers dropped", rep["page_numbers"] == 2),
        ("hyphen joined across the page break", "discussion" in text),
        ("body kept", "A second paragraph starts here." in text),
    ]
    flow, _ = convert(path, do_reflow=True, para_starts=["A second paragraph"])
    checks += [
        ("reflow makes one stream per paragraph", flow.split("\n\n")[0].count("\n") == 0),
        ("para-starts splits there", "\n\nA second paragraph" in flow),
    ]
    keep, _ = convert(path, strip=False)
    checks.append(("foil: --no-strip-repeats は柱を残す", head in keep))
    rep_t, rep_r = convert(path, replace=["effect=affect"], prepend="[note]")
    checks += [("replace applied", "affect follows" in rep_t and rep_r["replacements"] == 1),
               ("prepend applied", rep_t.startswith("[note]\n\n"))]
    path.unlink()

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print("ALL PASS" if not bad else f"FAILED: {bad}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", nargs="?", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="書き出し先 (既定 = stdout)")
    ap.add_argument("--reflow", action="store_true", help="行を 1 本の stream にする")
    ap.add_argument("--para-starts", type=Path, help="段落の書き出しの語を 1 行 1 つ書いた file")
    ap.add_argument("--keep-hyphen", action="append", default=[],
                    help="結合しない行末の断片 (例: few-)。複数可")
    ap.add_argument("--no-strip-repeats", action="store_true", help="柱・頁番号を残す")
    ap.add_argument("--replace", action="append", default=[], metavar="OLD=NEW",
                    help="最後に当てる literal 置換 (合字の後で空白が落ちた語など)。複数可")
    ap.add_argument("--prepend", type=Path, help="先頭に付ける来歴 note の file")
    ap.add_argument("--json", action="store_true", help="修復の内訳を stdout に JSON で")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.pdf:
        ap.error("pdf を指定するか --selftest")
    starts = []
    if a.para_starts:
        starts = [l.rstrip("\n") for l in a.para_starts.read_text().splitlines() if l.strip()]
    text, rep = convert(a.pdf, keep_hyphen=a.keep_hyphen, do_reflow=a.reflow,
                        para_starts=starts, strip=not a.no_strip_repeats, replace=a.replace,
                        prepend=a.prepend.read_text() if a.prepend else "")
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        (a.out.write_text(text) if a.out else sys.stdout.write(text))
        print(f"[pdf-to-text] {rep['pages']} 頁 / 合字 {rep['ligatures']} / ハイフン結合 "
              f"{rep['hyphen_joins']} / 頁番号 {rep['page_numbers']} / 柱 {len(rep['dropped_lines'])} 種",
              file=sys.stderr)
        if rep["suspicious"]:
            print(f"[pdf-to-text] 合字を含む語 {len(rep['suspicious'])} 種、短い順に: "
                  f"{', '.join(rep['suspicious'][:8])} … (空白落ちは --replace で直す)",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
