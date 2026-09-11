#!/usr/bin/env python3
"""substack-fetch.py — Substack の公開一覧・記事本文・有料全文 (browser session 再利用)・購読メール整形を CLI で取る。

購読している publication の記事を研究用に原文保存するための部品。 罠と判断の正本 =
conventions/substack.md の「購読記事の取り込み」 節 (#archive-pagination / #fulltext-check /
#paid-full-text / #subscription-mail)。 有料全文の経路 = conventions/machine-route-first.md
#session-cookie-reuse (cookie 復号 = scripts/chromium-cookies.py)。

使い方:
  # 公開一覧を全件 (offset は返却件数で進める = 初回ページは limit 未満で切れることがある)
  substack-fetch.py archive <host> --out archive.json

  # 本文 JSON (body_html 入り) を slug ごとに保存。 全文判定を通ったものだけ保存する
  substack-fetch.py posts <host> <slug>... --outdir DIR [--cookie brave|chrome]

  # 保存した post JSON の body_html を markdown に (画像・購読 widget・Share ボタン除去)
  substack-fetch.py markdown post.json

  # 購読メールの text/plain から Web 誘導行・配信停止行以降・購読勧誘定型を除く
  substack-fetch.py clean-mail body.txt

  <host> = `<name>.substack.com` か独自ドメイン (旧 host が 301 で移るなら移転先を渡す)。

Python から (hyphen 名なので importlib で読む):
  list_archive(host) / fetch_post(host, slug, cookie) / browser_cookie(browser, host) /
  fulltext_ratio(post) / post_markdown(body_html) / clean_mail(text)

⚠️ cookie 値は secret (= session hijack 可能)。 表示・log・保存しない (名前だけ stderr に出す)。
⚠️ markdown 変換は bs4 + html2text が要る (pip install beautifulsoup4 html2text)。
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0"
FULL_THRESHOLD = 0.9
LATIN_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
CJK_CHAR = re.compile(r"[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ]")
HERE = os.path.dirname(os.path.abspath(__file__))


def http_json(url, cookie=None):
    headers = {"User-Agent": UA}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return json.load(r)


def list_archive(host, pause=0.8):
    """公開一覧の全件。 offset は返却件数で進める (limit 固定で進めると取りこぼす)。"""
    posts, off = {}, 0
    while True:
        page = http_json(f"https://{host}/api/v1/archive?sort=new&offset={off}&limit=50")
        if not page:
            break
        for p in page:
            posts[p["slug"]] = p
        off += len(page)
        time.sleep(pause)
    return sorted(posts.values(), key=lambda p: p["post_date"], reverse=True)


def fetch_post(host, slug, cookie=None):
    return http_json(f"https://{host}/api/v1/posts/{slug}", cookie)


def count_words(html_or_text):
    """Substack の wordcount と比べる語数。 英数字は単語、 CJK は 1 字 = 1 語。
    空白区切りだと日本語がほぼ 0 になり、 全文を抜粋と誤判定する。"""
    text = re.sub(r"<[^>]+>", " ", html_or_text or "")
    return len(LATIN_WORD.findall(text)) + len(CJK_CHAR.findall(text))


def fulltext_ratio(post):
    """body_html の語数 / API wordcount。 英語の全文 ≈ 1.0、 日本語の全文 ≈ 1.7、 抜粋 ≈ 0.05。"""
    wc = post.get("wordcount") or 0
    return count_words(post.get("body_html")) / wc if wc else 0.0


def browser_cookie(browser, host):
    """ログイン済み browser の Substack cookie を Cookie header 文字列で返す (値は表示しない)。"""
    spec = importlib.util.spec_from_file_location("chromium_cookies", os.path.join(HERE, "chromium-cookies.py"))
    ck = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ck)
    domains = ["substack.com"] + ([] if host.endswith("substack.com") else [host])
    jar = ck.load_cookies(browser, domains)
    print("cookie names:", sorted(jar), file=sys.stderr)
    if not jar:
        sys.exit(f"{browser} に Substack の cookie が無い → browser で 1 回ログインして再実行")
    return "; ".join(f"{k}={v}" for k, v in jar.items())


BOILER_LINK = re.compile(
    r"(?m)^[ \t]*\[(Share|Subscribe|Subscribe now|Leave a comment|Share [^\]]*|"
    r"Give a gift subscription|Get \d+% off[^\]]*)\]\([^)]*\)[ \t]*\n?")
DROP_SELECTORS = [
    "div.subscription-widget-wrap", "div.subscription-widget-wrap-editor", "div.subscribe-widget",
    "form", "button", "div.captioned-button-wrap", "p.button-wrapper", "div.button-wrapper",
    "figure", "picture", "img", "div.image-link-expand", "div.native-video-embed", "div.youtube-wrap",
]


def post_markdown(body_html):
    try:
        import html2text
        from bs4 import BeautifulSoup
    except ImportError:
        sys.exit("markdown 変換には beautifulsoup4 と html2text が要る (pip install beautifulsoup4 html2text)")
    soup = BeautifulSoup(body_html or "", "html.parser")
    for sel in DROP_SELECTORS:
        for x in soup.select(sel):
            x.decompose()
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_images = True
    h.unicode_snob = True
    md = BOILER_LINK.sub("", h.handle(str(soup)))
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def clean_mail(text):
    """購読メール text/plain の整形。 本文の要約・言い換えはしない。"""
    t = text.replace("\r\n", "\n")
    lines = t.split("\n")
    if lines and lines[0].startswith("View this post on the web at"):
        lines = lines[1:]
    t = "\n".join(lines)
    t = re.split(r"\n\s*Unsubscribe https://", t)[0]
    t = re.sub(r"(?m)^Thanks for reading!.*\n?", "", t)
    t = re.sub(r"(?m)^\S+ is a reader-supported publication\. .*(?:\n\n?|\Z)", "", t)
    return t.strip("\n") + "\n"


def cmd_archive(a):
    out = list_archive(a.host)
    with open(a.out, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    aud = {}
    for p in out:
        aud[p.get("audience")] = aud.get(p.get("audience"), 0) + 1
    print(f"{len(out)} posts -> {a.out}  {aud}")


def cmd_posts(a):
    os.makedirs(a.outdir, exist_ok=True)
    cookie = browser_cookie(a.cookie, a.host) if a.cookie else None
    ok = bad = 0
    for i, slug in enumerate(a.slugs):
        path = os.path.join(a.outdir, f"{slug}.json")
        cached = os.path.exists(path)
        if cached:
            with open(path) as f:
                d = json.load(f)
        else:
            d = fetch_post(a.host, slug, cookie)
        ratio = fulltext_ratio(d)
        full = ratio >= FULL_THRESHOLD
        if full:
            with open(path, "w") as f:
                json.dump(d, f, ensure_ascii=False)
            ok += 1
        else:
            bad += 1
            if cached:
                os.remove(path)
        print(f"{'FULL ' if full else 'TRUNC'} {ratio:4.2f} {d.get('post_date', '')[:10]} {d.get('audience')} {slug}")
        if i == 0 and not full and cookie:
            sys.exit("最初の記事が抜粋のまま → 未ログイン / 有料購読でない session")
        if not cached:
            time.sleep(1.0)
    print(f"full {ok} / trunc {bad} / total {len(a.slugs)}")


def cmd_markdown(a):
    with open(a.post) as f:
        sys.stdout.write(post_markdown(json.load(f).get("body_html")))


def cmd_clean_mail(a):
    with open(a.file) as f:
        sys.stdout.write(clean_mail(f.read()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("archive")
    p.add_argument("host")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_archive)
    p = sub.add_parser("posts")
    p.add_argument("host")
    p.add_argument("slugs", nargs="+")
    p.add_argument("--outdir", required=True)
    p.add_argument("--cookie", choices=["brave", "chrome", "chromium"])
    p.set_defaults(func=cmd_posts)
    p = sub.add_parser("markdown")
    p.add_argument("post")
    p.set_defaults(func=cmd_markdown)
    p = sub.add_parser("clean-mail")
    p.add_argument("file")
    p.set_defaults(func=cmd_clean_mail)
    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 2
    a.func(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
