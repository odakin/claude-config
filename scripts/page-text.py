#!/usr/bin/env python3
"""page-text.py — 公式の頁・PDF の原文を、 要約を通さずに見える文だけの text にして出す (HTML の comment を除く・frameset の中身の頁まで読む・PDF は PyMuPDF で頁ごと。 標準ライブラリだけで動き、 PDF のときだけ PyMuPDF が要る)

用途: 締切・金額・応募資格・推薦の要否のような事実値を、 公式の頁から確かめて記録に写すとき。
WebFetch の答えは小さなモデルの生成物で、 原文の写しではない (= conventions/web-tools.md#webfetch-answer-is-generated)。
curl で取った HTML を手で text にすると落としやすい 3 点を、 この道具が持つ:
  1. HTML の comment (<!-- … -->) の中の古い文 = 画面には出ない (例: 何年も前の募集期間)。 タグだけを消すと、
     表示されている文と区別なく出てくる。 この道具は comment を落とし、 落とした comment の数を最後に言う
     (--comments で comment の中身も別に出す = 「画面にあるか」 を確かめる材料)
  2. frameset / iframe の頁 = 外側の頁には中身が無い。 <frame src> / <iframe src> を 1 段だけ辿って読む
  3. 古い頁の文字コード (EUC-JP / Shift_JIS) = header か <meta charset> で decode する
     (decode と text 化の実装は web-page-watch.py と共通 = その 2 関数を読み込んで使う)

使い方:
  page-text.py URL [URL ...]               見える文を 1 行ずつ出す (URL ごとに見出し)
  page-text.py FILE.html|FILE.pdf          手元の file も同じ (取得した写しを読み直すとき)
  page-text.py URL --grep '締切|募集期間'    正規表現に当たる行だけ (前後 --context 行、 既定 1)
  page-text.py URL --comments              落とした HTML の comment の中身も別の節で出す
  page-text.py URL --save DIR              取った原物 (HTML / PDF) を DIR に保存し、 sha256 を出す
  page-text.py --selftest                  合成データだけで検査する (network に出ない)

PDF: 頁ごとに block を上から順に並べて出す。 表・多段組は block の順が視覚の順と合わないことがある =
数字の表を写すときは conventions/office-automation.md#pdf-table-layout-aware-reading の手順で読み直す。
ネットから取った file を repo に入れる前は scripts/downloaded-file-scan.py を通す (conventions/downloaded-file-scan.md)。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (compatible; page-text)"
FRAME_RE = re.compile(r"<i?frame\b[^>]*?\bsrc\s*=\s*[\"']?([^\"'\s>]+)", re.I)
COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)


def _watch_module():
    spec = importlib.util.spec_from_file_location("web_page_watch_shared", HERE / "web-page-watch.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_W = _watch_module()


def fetch(src: str) -> tuple[bytes, str | None, str]:
    """(原物の bytes, header の charset, content-type) を返す。 手元の file も読む。"""
    p = Path(src)
    if not re.match(r"^[a-z][a-z0-9+.-]*://", src, re.I) and p.exists():
        raw = p.read_bytes()
        return raw, None, "application/pdf" if raw[:5] == b"%PDF-" else "text/html"
    req = urllib.request.Request(src, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (人が渡した URL だけを読む)
        raw = r.read()
        return raw, r.headers.get_content_charset(), r.headers.get_content_type() or ""


def is_pdf(raw: bytes, ctype: str) -> bool:
    return raw[:5] == b"%PDF-" or "pdf" in ctype.lower()


def pdf_lines(raw: bytes) -> list[str]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ["⚠️ PDF の text には PyMuPDF (fitz) が要る。 `python3 -I` で起こすと user site の fitz が見えない = conventions/python-env.md#isolated-mode-drops-user-site"]
    out: list[str] = []
    with fitz.open(stream=raw, filetype="pdf") as doc:
        for i, page in enumerate(doc, 1):
            out.append(f"--- p{i}")
            blocks = sorted(page.get_text("blocks"), key=lambda b: (round(b[1]), b[0]))
            for b in blocks:
                for ln in str(b[4]).splitlines():
                    ln = re.sub(r"\s+", " ", ln).strip()
                    if ln:
                        out.append(ln)
    return out


def comments_of(src_html: str) -> list[str]:
    out = []
    for m in COMMENT_RE.finditer(src_html):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
        if len(t) >= 10:
            out.append(t)
    return out


def frame_urls(src_html: str, base: str) -> list[str]:
    body = COMMENT_RE.sub("", src_html)
    seen, out = set(), []
    for m in FRAME_RE.finditer(body):
        u = urllib.parse.urljoin(base, m.group(1))
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def read_one(src: str, fetcher=fetch, follow_frames: bool = True, depth: int = 0) -> dict:
    raw, charset, ctype = fetcher(src)
    res = {"src": src, "raw": raw, "kind": "pdf" if is_pdf(raw, ctype) else "html",
           "lines": [], "comments": [], "frames": []}
    if res["kind"] == "pdf":
        res["lines"] = pdf_lines(raw)
        return res
    text = _W.decode_html(raw, charset)
    res["lines"] = _W.html_to_lines(text)
    res["comments"] = comments_of(text)
    if follow_frames and depth == 0:
        base = src if re.match(r"^[a-z][a-z0-9+.-]*://", src, re.I) else Path(src).resolve().as_uri()
        for u in frame_urls(text, base):
            try:
                res["frames"].append(read_one(u, fetcher, follow_frames, depth + 1))
            except Exception as e:  # noqa: BLE001 (frame 1 つの失敗で全体を止めない)
                res["frames"].append({"src": u, "raw": b"", "kind": "error", "lines": [f"⚠️ 読めない: {e}"],
                                      "comments": [], "frames": []})
    return res


def grep_lines(lines: list[str], pattern: str | None, context: int) -> list[str]:
    if not pattern:
        return lines
    rx = re.compile(pattern)
    keep = set()
    for i, ln in enumerate(lines):
        if rx.search(ln):
            keep.update(range(max(0, i - context), min(len(lines), i + context + 1)))
    return [lines[i] for i in sorted(keep)]


def render(res: dict, args, out: list[str], label: str = "") -> None:
    out.append(f"##### {label}{res['src']} ({res['kind']}, {len(res['raw'])} bytes)")
    out.extend(grep_lines(res["lines"], args.grep, args.context))
    if res["comments"]:
        out.append(f"(HTML の comment {len(res['comments'])} 個は画面に出ないので除いた"
                   + (")" if args.comments else "。 中身 = --comments)"))
        if args.comments:
            out.extend(f"  <!-- {c[:400]} -->" for c in res["comments"])
    for f in res["frames"]:
        render(f, args, out, label="frame: ")


def save(res: dict, outdir: Path, out: list[str]) -> None:
    if not res["raw"]:
        return
    outdir.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.parse.urlparse(res["src"]).path).name or "index.html"
    host = urllib.parse.urlparse(res["src"]).netloc.replace(":", "_")
    dest = outdir / (f"{host}_{name}" if host else name)
    dest.write_bytes(res["raw"])
    out.append(f"saved {dest} sha256={hashlib.sha256(res['raw']).hexdigest()}")
    for f in res["frames"]:
        save(f, outdir, out)


def selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name)
        fails += 0 if cond else 1

    top = b"<html><head><meta charset=EUC-JP></head><frameset><frame src='menu.html'><frame src=\"main.html\"></frameset></html>"
    main = ("<html><head><meta http-equiv=Content-Type content='text/html; charset=EUC-JP'></head>"
            "<body><h1>募集要項</h1><p>募集期間 2030年1月1日から</p>"
            "<!-- <p>募集期間 1999年12月1日から</p> --><script>x=1</script></body></html>").encode("euc_jp")
    menu = b"<html><body><a href='a'>MENU</a></body></html>"
    pages = {"https://example.test/": (top, None, "text/html"),
             "https://example.test/main.html": (main, None, "text/html"),
             "https://example.test/menu.html": (menu, None, "text/html")}
    res = read_one("https://example.test/", fetcher=lambda u: pages[u])
    check("frames followed", [f["src"] for f in res["frames"]] == ["https://example.test/menu.html", "https://example.test/main.html"])
    mlines = res["frames"][1]["lines"]
    check("EUC-JP decoded via meta", "募集要項" in mlines)
    check("visible text kept", any("2030年" in ln for ln in mlines))
    check("comment text dropped from lines", not any("1999年" in ln for ln in mlines))
    check("comment reported separately", any("1999年" in c for c in res["frames"][1]["comments"]))
    check("script dropped", not any("x=1" in ln for ln in mlines))
    check("grep with context", grep_lines(["a", "募集期間 X", "b", "c"], "募集期間", 1) == ["a", "募集期間 X", "b"])
    check("pdf magic detected", is_pdf(b"%PDF-1.7 ...", "application/octet-stream"))
    print(f"\nOK: {fails} failure(s)" if fails == 0 else f"\nNG: {fails} failure(s)")
    return 0 if fails == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="*", help="URL か手元の HTML / PDF")
    ap.add_argument("--grep", help="この正規表現に当たる行だけを出す")
    ap.add_argument("--context", type=int, default=1, help="--grep の前後の行数 (既定 1)")
    ap.add_argument("--comments", action="store_true", help="落とした HTML の comment の中身も出す")
    ap.add_argument("--no-frames", action="store_true", help="frameset / iframe の中身の頁を辿らない")
    ap.add_argument("--save", metavar="DIR", help="取った原物を DIR に保存して sha256 を出す")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.src:
        ap.error("URL か file を 1 つ以上")
    rc = 0
    for src in args.src:
        out: list[str] = []
        try:
            res = read_one(src, follow_frames=not args.no_frames)
        except Exception as e:  # noqa: BLE001
            print(f"##### {src}\n⚠️ 読めない: {e}")
            rc = 1
            continue
        render(res, args, out)
        if args.save:
            save(res, Path(args.save), out)
        print("\n".join(out))
    return rc


if __name__ == "__main__":
    sys.exit(main())
