#!/usr/bin/env python3
"""html-print-pdf.py — 「印刷用 HTML ページ」 (window.print() 前提) を保存 HTML から A4 PDF にし、 刷れる raster 版まで作る。

用途: Web システムが PDF でなく印刷用 HTML で配る書類 (学会の参加票・名札 / 領収書 / 受講票 等) を、
画面の「印刷」 ボタンを押さずに機械で PDF 化する。 ページは login の奥にあることが多いので、 取得 (login +
保存) は本 script の外 = 本人がブラウザで保存するか、 本人が curl で取る。 本 script は保存後の HTML だけを扱う。

  python3 html-print-pdf.py page.html --base-href https://example.org/app/ -o ticket.pdf --expect-pages 1
    → ticket.pdf (ブラウザ出力) + ticket-print.pdf (RGB raster、 刷るのはこちら) + 検査結果

処理:
  1. <base href> を <head> 直後に差す (保存 HTML の CSS・画像は相対 path なので、 無いと版面が崩れる)。
     既に <base> があれば触らない。
  2. <head> 先頭に `@page{size:<paper>}` を差す。 先頭に置くので、 ページ側 CSS が @page を持っていればそちらが勝つ
     (= 用紙指定の無いページだけ A4 になる。 領収書型のページは CSS が用紙を指定しないことがある)。
  3. headless の Chromium 系ブラウザ (Brave / Chrome / Chromium / Edge を自動検出、 --browser で指定) で
     --print-to-pdf。macOS では GUI 稼働中の同じ app bundle を候補から外し、停止中の browser を選ぶ。
     さらに通常 profile と singleton/profile lock を共有しないよう、一時 user-data-dir を使う。
     ヘッダ・フッタ (URL・日付) は付けない。
  4. pdf-print-preflight.py に通し、 --rasterize で RGB raster 版を作る。 ⚠️ Chromium の print-to-pdf は文字を
     Type3 font で書くことがあり、 そのままだと preflight が FAIL する (実測) = 刷るのは raster 版。

終了コード: 0 = PDF と raster 版ができた (page 数が --expect-pages と一致) / 1 = page 数不一致 / 2 = 実行不能。
刷る前の残り: render の目視 (--png で PNG も出す) と、 プリンタ本体の用紙サイズ・トレイの紙の確認
(= lp の media 指定は本体設定を上書きしない、 conventions/office-automation.md#print-preflight 5.)。
本 script は lp を呼ばない (印刷は人が確認してから)。

  --selftest : 合成 HTML で 1-4 を通す (ブラウザが無い環境では skip を明示して exit 0)
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PREFLIGHT = os.path.join(HERE, "pdf-print-preflight.py")

BROWSER_CANDIDATES = [
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "brave-browser", "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]
MACOS_USER_DATA_DIRS = {
    "Brave Browser": ("Library", "Application Support", "BraveSoftware", "Brave-Browser"),
    "Google Chrome": ("Library", "Application Support", "Google", "Chrome"),
    "Chromium": ("Library", "Application Support", "Chromium"),
    "Microsoft Edge": ("Library", "Application Support", "Microsoft Edge"),
}


def browser_is_running(browser):
    if sys.platform != "darwin" or not os.path.isabs(browser):
        return False
    process_name = os.path.basename(browser)
    segments = MACOS_USER_DATA_DIRS.get(process_name)
    if segments:
        lock = os.path.join(os.path.expanduser("~"), *segments, "SingletonLock")
        try:
            target = os.readlink(lock)
            pid = int(target.rsplit("-", 1)[1])
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except (FileNotFoundError, OSError, ValueError, IndexError):
            pass
    r = subprocess.run(["/usr/bin/pgrep", "-x", process_name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def find_browser(explicit=None):
    for c in ([explicit] if explicit else BROWSER_CANDIDATES):
        if not c:
            continue
        if os.path.isabs(c) and os.access(c, os.X_OK):
            if not browser_is_running(c):
                return c
            continue
        w = shutil.which(c)
        if w and not browser_is_running(w):
            return w
    return None


def japanese_font_available(env=None):
    """日本語の glyph を持つ font がこの機械に在るか。 Chromium は無い glyph を描かず PDF の文字層にも残さないので、
    日本語だけの頁は白紙になり preflight が止める (2026-09-22 の CI = ubuntu runner で実測)。 macOS は Hiragino 同梱 =
    常に真、 それ以外は fontconfig (fc-list :lang=ja) に聞く (無ければ偽)。 HTML_PRINT_PDF_JA_FONT=0/1 は test 用の上書き
    (font の在る機械で selftest の SKIP 側の経路を通す。 本番の判定には使わない)。"""
    env = os.environ if env is None else env
    forced = env.get("HTML_PRINT_PDF_JA_FONT")
    if forced in ("0", "1"):
        return forced == "1"
    if sys.platform == "darwin":
        return True
    try:
        r = subprocess.run(["fc-list", ":lang=ja", "family"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(r.stdout.strip())


def prepare_html(html, base_href=None, paper="A4"):
    """<base href> と @page を差した HTML を返す。 <head> が無ければ先頭に作る。"""
    m = re.search(r"<head[^>]*>", html, flags=re.I)
    if not m:
        html = "<head></head>" + html
        m = re.search(r"<head[^>]*>", html, flags=re.I)
    inject = ""
    if paper:
        inject += f"\n<style>@page{{size:{paper}}}</style>"
    if base_href and not re.search(r"<base\s", html, flags=re.I):
        inject = f"\n<base href=\"{base_href}\">" + inject
    return html[:m.end()] + inject + html[m.end():]


def browser_command(browser, html_path, out_pdf, user_data_dir):
    return [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--user-data-dir={user_data_dir}", f"--print-to-pdf={out_pdf}",
            "file://" + os.path.abspath(html_path)]


def in_codex_seatbelt(env=None):
    return (os.environ if env is None else env).get("CODEX_SANDBOX") == "seatbelt"


WRITTEN_MARKER = "bytes written to file"


def render_pdf(browser, html_path, out_pdf, timeout=120):
    """headless で print-to-pdf し、 PDF を書き終えたら browser を止める。

    実測: macOS の Chrome は「N bytes written to file」 を出して PDF を書いた後も process が終わらないことがある
    (数秒で書けているのに timeout まで待って TimeoutExpired で落ちていた)。 ∴ 終了を待たず、 marker (または
    size が 2 回続けて同じ) を見たら process group ごと止める。
    """
    import signal
    import time

    profile_dir = os.path.join(os.path.dirname(html_path), "chromium-profile")
    cmd = browser_command(browser, html_path, out_pdf, profile_dir)
    log_path = os.path.join(os.path.dirname(html_path), "browser.log")
    with open(log_path, "wb") as log:
        p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline, last_size, stable = time.monotonic() + timeout, -1, 0
    try:
        while p.poll() is None and time.monotonic() < deadline:
            size = os.path.getsize(out_pdf) if os.path.exists(out_pdf) else 0
            with open(log_path, encoding="utf-8", errors="replace") as f:
                written = WRITTEN_MARKER in f.read()
            stable = stable + 1 if size > 0 and size == last_size else 0
            if size > 0 and (written or stable >= 4):  # marker が無い build でも 2 秒同じ size なら書き終わり
                break
            last_size = size
            time.sleep(0.5)
    finally:
        if p.poll() is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    p.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    continue
    with open(log_path, encoding="utf-8", errors="replace") as f:
        tail = f.read().strip()[-400:]
    if not os.path.exists(out_pdf) or os.path.getsize(out_pdf) == 0:
        raise RuntimeError(f"ブラウザが PDF を出さなかった (rc={p.returncode}): {tail}")


def page_report(pdf):
    try:
        import fitz
    except ImportError:
        return "(PyMuPDF が無いので寸法は未確認)"
    d = fitz.open(pdf)
    sizes = sorted({(round(p.rect.width * 25.4 / 72), round(p.rect.height * 25.4 / 72)) for p in d})
    return f"{d.page_count} page / " + ", ".join(f"{w}×{h} mm" for w, h in sizes)


def run(src, out, base_href=None, paper="A4", expect_pages=None, browser=None, dpi=300, png=False):
    if in_codex_seatbelt():
        print("html-print-pdf: Codex seatbelt 内では macOS GUI browser を起動しない; 承認済みの sandbox 外実行を使う", file=sys.stderr)
        return 2
    b = find_browser(browser)
    if not b:
        print("html-print-pdf: Chromium 系ブラウザが見つからない (--browser で path を指定)", file=sys.stderr)
        return 2
    with open(src, encoding="utf-8", errors="replace") as f:
        html = f.read()
    tmpd = tempfile.mkdtemp()
    fixed = os.path.join(tmpd, "page.html")
    with open(fixed, "w", encoding="utf-8") as f:
        f.write(prepare_html(html, base_href, paper))
    render_pdf(b, fixed, out)
    print(f"  · ブラウザ出力: {out} ({page_report(out)})")
    raster = re.sub(r"\.pdf$", "", out) + "-print.pdf"
    cmd = [sys.executable, PREFLIGHT, out, "--rasterize", raster, "--dpi", str(dpi)]
    if expect_pages is not None:
        cmd += ["--expect-pages", str(expect_pages)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout.rstrip())
    if png:
        try:
            import fitz
            p = re.sub(r"\.pdf$", "", out) + ".png"
            fitz.open(raster)[0].get_pixmap(dpi=80).save(p)
            print(f"  · 目視用 PNG (1 頁目): {p}")
        except Exception as e:  # pragma: no cover
            print(f"  · PNG 生成に失敗: {e}")
    print(f"  ⚠️ 刷るのは {raster}。 刷る前に render を目視 + プリンタ本体の用紙サイズとトレイの紙を確認")
    return r.returncode


def selftest():
    # prepare_html の単体 (ブラウザ不要)
    h = prepare_html("<html><head><title>t</title></head><body>x</body></html>", "https://example.org/a/")
    assert '<base href="https://example.org/a/">' in h and "@page{size:A4}" in h, h
    assert h.index("<base") < h.index("<title>"), "base は head 先頭"
    h2 = prepare_html('<head><base href="https://x/"></head>', "https://example.org/a/")
    assert h2.count("<base") == 1, "既存 base は触らない"
    h3 = prepare_html("<body>no head</body>", None, "A4")
    assert h3.startswith("<head>") and "@page" in h3
    print("  prepare_html: 3/3 PASS")
    cmd = browser_command("/browser", "/tmp/page.html", "/tmp/page.pdf", "/tmp/profile")
    assert "--user-data-dir=/tmp/profile" in cmd, cmd
    assert cmd[-1] == "file:///tmp/page.html", cmd
    print("  browser_command: isolated user-data-dir PASS")
    assert in_codex_seatbelt({"CODEX_SANDBOX": "seatbelt"})
    assert not in_codex_seatbelt({})
    print("  sandbox guard: 2/2 PASS")
    assert japanese_font_available({"HTML_PRINT_PDF_JA_FONT": "0"}) is False
    assert japanese_font_available({"HTML_PRINT_PDF_JA_FONT": "1"}) is True
    print("  japanese_font_available: override 2/2 PASS")
    # 終わらない browser の代役: PDF と marker を書いた後 sleep し続ける (render_pdf が待たずに止めるか)
    fake_dir = tempfile.mkdtemp()
    fake = os.path.join(fake_dir, "hang-browser")
    with open(fake, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nfor a in \"$@\"; do case \"$a\" in --print-to-pdf=*) o=\"${a#--print-to-pdf=}\";; esac; done\n"
                "printf '%%PDF-1.4\\n' > \"$o\"; echo \"9 " + WRITTEN_MARKER + " $o\" >&2; exec sleep 600\n")
    os.chmod(fake, 0o755)
    import time
    t0 = time.monotonic()
    render_pdf(fake, os.path.join(fake_dir, "page.html"), os.path.join(fake_dir, "out.pdf"), timeout=30)
    assert time.monotonic() - t0 < 15, "render_pdf waited for a browser that never exits"
    print("  render_pdf: stops a browser that keeps running after writing the PDF PASS")
    if in_codex_seatbelt():
        print("  render: SKIP (Codex seatbelt 内では macOS GUI browser を起動しない)")
        print("html-print-pdf selftest: PASS")
        return 0
    b = find_browser()
    if not b:
        print("  render: SKIP (Chromium 系ブラウザ無し)")
        return 0
    d = tempfile.mkdtemp()
    src = os.path.join(d, "t.html")
    # 日本語 font の無い機械では、 日本語だけの頁は Chromium が何も描かず preflight が「白紙」 で止める (= 環境の欠落で
    # あって道具の壊れではない)。 そこでは英字の頁で経路 (browser → PDF → preflight → raster) だけ確かめ、 SKIP を宣言する。
    ja = japanese_font_available()
    if not ja:
        print("  render: SKIP 日本語の描画 (日本語 font が無い環境 = fc-list :lang=ja が空。 英字の頁で経路だけ確かめる)")
    body = "<h1>合成 テスト 参加票</h1>" if ja else "<h1>Synthetic test form</h1>"
    with open(src, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'></head><body>" + body + "</body></html>")
    out = os.path.join(d, "t.pdf")
    rc = run(src, out, expect_pages=1, dpi=72)
    assert rc == 0, rc
    assert os.path.exists(os.path.join(d, "t-print.pdf"))
    try:
        import fitz
        p = fitz.open(os.path.join(d, "t-print.pdf"))[0]
        w, hh = round(p.rect.width * 25.4 / 72), round(p.rect.height * 25.4 / 72)
        assert (w, hh) == (210, 297), (w, hh)
        if ja:
            t = "".join(pg.get_text() for pg in fitz.open(out))
            assert "参加票" in t, "日本語 font が在るのに文字層に日本語が無い: " + repr(t[:80])
            print("  render: 日本語の文字層 PASS")
    except ImportError:
        pass
    print("html-print-pdf selftest: PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html", nargs="?", help="保存した印刷用 HTML")
    ap.add_argument("-o", "--out", help="出力 PDF (default: <html>.pdf)")
    ap.add_argument("--base-href", help="保存元ページのディレクトリ URL (CSS・画像の相対 path 解決用)")
    ap.add_argument("--paper", default="A4", help="ページ CSS に @page が無いときの用紙 (default A4、 空文字で差さない)")
    ap.add_argument("--expect-pages", type=int)
    ap.add_argument("--browser", help="Chromium 系ブラウザの実行ファイル")
    ap.add_argument("--dpi", type=int, default=300, help="raster 版の dpi (default 300)")
    ap.add_argument("--png", action="store_true", help="目視用に raster 版 1 頁目の PNG も出す")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.html:
        ap.error("html を指定 (or --selftest)")
    out = a.out or re.sub(r"\.html?$", "", a.html) + ".pdf"
    return run(a.html, out, a.base_href, a.paper, a.expect_pages, a.browser, a.dpi, a.png)


if __name__ == "__main__":
    sys.exit(main())
