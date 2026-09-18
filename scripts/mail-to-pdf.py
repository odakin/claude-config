#!/usr/bin/env python3
"""mail-to-pdf.py — 受信したメールの本文 (text) を、 事務に出す添付書類の PDF にする (日本語可・秘密の値を伏せられる)。

用途: 「予約確認メール」「採択通知」「見積メール」 のように、 メールそのものが証拠書類になるとき。
メールの取得は本 script の外 (Gmail なら API で本文を text に落とす。 ヘッダ〔Date / From / To / Subject〕
を先頭に含めておくと、 出した先で出典が分かる)。

  python3 mail-to-pdf.py mail.txt -o quote.pdf --title "宿泊の見積 (旅行会社からのメール)" \\
      --redact 'PIN code: *\\S+' --redact '暗証番号 *[:：] *\\S+'

処理:
  1. text を HTML に包む (<pre> = 改行と字下げをそのまま、 長い行は折り返す、 HTML は escape)。
  2. --redact の正規表現に当たった部分を ■ に置き換える (元の値は PDF の文字層にも残らない)。
     ⚠️ 伏せたい値の書式は送り手ごとに違う = 出力を読み戻して値が消えたかを確かめる (本 script は置換の件数を出す)。
  3. 同じ dir の html-print-pdf.py で A4 PDF にする (headless の Chromium 系ブラウザ、 日本語 font はブラウザ任せ)。
     html-print-pdf.py は刷る用の raster 版 (<out>-print.pdf) も作る。 メールで出すだけならそちらは要らない。

終了コード: html-print-pdf.py と同じ (0 = できた / 1 = page 数不一致 / 2 = 実行不能)。

  --selftest : 合成メール (日本語 + 伏せる値) で 1-2 を検査し、 ブラウザがあれば 3 も通す
"""
import argparse
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "html-print-pdf.py"

CSS = (
    "body{margin:0;font-family:'Hiragino Kaku Gothic ProN','Hiragino Sans','Noto Sans CJK JP',sans-serif;}"
    "h1{font-size:11pt;margin:0 0 6pt 0;padding-bottom:4pt;border-bottom:1px solid #888;}"
    "pre{font-family:inherit;font-size:9.5pt;line-height:1.45;white-space:pre-wrap;word-break:break-all;margin:0;}"
)


def redact(text, patterns):
    """patterns に当たった部分を ■ に置き換える。 (置換後の text, 当たった件数) を返す。"""
    total = 0
    for pat in patterns:
        text, n = re.subn(pat, lambda m: "■" * max(4, min(len(m.group(0)), 12)), text)
        total += n
    return text, total


def build_html(text, title=None):
    head = f"<h1>{html.escape(title)}</h1>" if title else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head>"
            f"<body>{head}<pre>{html.escape(text)}</pre></body></html>")


def run(src, out, title=None, patterns=(), expect_pages=None):
    text = Path(src).read_text(encoding="utf-8", errors="replace")
    text, hits = redact(text, patterns)
    if patterns:
        print(f"伏せた箇所: {hits} (パターン {len(patterns)} 個)。 0 なら書式が違う = 出力を読んで確かめる")
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "mail.html"
        page.write_text(build_html(text, title), encoding="utf-8")
        cmd = [sys.executable, str(ENGINE), str(page), "-o", str(out)]
        if expect_pages:
            cmd += ["--expect-pages", str(expect_pages)]
        return subprocess.run(cmd).returncode


def selftest():
    sample = ("Date: Thu, 1 Jan 2099 10:00:00 +0900\nFrom: 架空旅行社 <x@example.invalid>\n"
              "Subject: 見積\n\n1 泊 100 ドル、 PIN code: 123456\n暗証番号：654321\n<script>alert(1)</script>\n")
    ok = True
    red, n = redact(sample, [r"PIN code: *\S+", r"暗証番号 *[:：] *\S+"])
    checks = [
        ("伏せる値が 2 件当たる", n == 2),
        ("値そのものが残らない", "123456" not in red and "654321" not in red),
        ("日本語はそのまま", "架空旅行社" in red and "1 泊 100 ドル" in red),
        ("HTML は escape される", "<script>" not in build_html(red) and "&lt;script&gt;" in build_html(red)),
        ("題は h1 に入る", "<h1>題</h1>" in build_html(red, "題")),
    ]
    for name, good in checks:
        ok &= bool(good)
        print("PASS" if good else "FAIL", name)
    # ブラウザがあれば PDF まで (無ければ html-print-pdf.py の selftest と同じく skip を明示)
    try:
        import fitz  # noqa: F401
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "m.txt"; src.write_text(sample, encoding="utf-8")
            out = Path(d) / "m.pdf"
            rc = run(src, out, "題", [r"PIN code: *\S+", r"暗証番号 *[:：] *\S+"])
            if rc == 2 or not out.exists():
                print("SKIP PDF 化 (ブラウザが無い / 実行不能)")
            else:
                import fitz
                t = "".join(p.get_text() for p in fitz.open(out))
                good = "架空旅行社" in t and "123456" not in t and "654321" not in t
                ok &= good
                print("PASS" if good else "FAIL", "PDF の文字層に日本語があり、 伏せた値が無い")
    except ImportError:
        print("SKIP PDF の読み戻し (PyMuPDF が無い)")
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("text", nargs="?", help="メールの text (ヘッダ行を含めてよい)")
    ap.add_argument("-o", "--out", help="出力 PDF (default: <text>.pdf)")
    ap.add_argument("--title", help="先頭に置く 1 行の題 (何の書類か)")
    ap.add_argument("--redact", action="append", default=[], metavar="正規表現",
                    help="伏せる部分の正規表現 (複数可)。 暗証番号・口座番号など")
    ap.add_argument("--expect-pages", type=int)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.text:
        ap.error("メールの text file が要る")
    out = a.out or str(Path(a.text).with_suffix(".pdf"))
    sys.exit(run(a.text, out, a.title, a.redact, a.expect_pages))


if __name__ == "__main__":
    main()
