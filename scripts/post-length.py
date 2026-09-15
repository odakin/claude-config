#!/usr/bin/env python3
"""post-length.py — SNS 投稿文の長さを X / Bluesky / Mastodon の数え方で並べて数え、上限を超えるものを示す (X は日本語・絵文字が 2、URL は 23)。--selftest 内蔵。

Why: 同じ告知文を複数の SNS に出すとき、 数え方が違うので「Bluesky と Mastodon には入るのに X では超える」
が起きる (実測: 同じ文面が Bluesky 292/300 で X は 345/280)。 手で数えると日本語の重みと URL の置き換えを
間違える。

数え方 (本 script の実装):
  X         weighted length ≤ 280。 code point ごとに重み 1 (U+0000–U+10FF, U+2000–U+200D, U+2010–U+201F,
            U+2032–U+2037) か 2 (それ以外 = 日本語・全角記号)。 絵文字は 1 つ (ZWJ 連結や肌色込み) で 2。
            URL は長さによらず 23。 (twitter-text v3 の既定設定)
  Bluesky   grapheme ≤ 300。 URL は書いたとおりの長さで数える (公式アプリは投稿画面で長い URL を短く表示するが、
            本 script は上側に倒して全長)。 grapheme の切れ目は近似 (結合文字・異体字セレクタ・ZWJ 連結・
            肌色・国旗の対・keycap を 1 つにまとめる)。
  Mastodon  ≤ 500 (サーバ設定で変わる)。 URL は 23。 本 script は code point で数える (grapheme より多いか同じ
            = 上側に倒す)。 @user@domain の domain 部分は数えない実装のサーバがあるが、 本 script は数える。

使い方:
  post-length.py post.txt                 # 3 つを表で。 超えたものがあれば exit 1
  pbpaste | post-length.py -              # 標準入力
  post-length.py post.txt --only x        # X だけ判定 (exit code も X だけで決まる)
  post-length.py post.txt --mastodon-limit 1000
  post-length.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata

URL = re.compile(r"https?://\S+")
X_LIGHT = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))
ZWJ = 0x200D


def _extends(cp: int) -> bool:
    """この code point は直前の grapheme に付くか (近似)。"""
    ch = chr(cp)
    return (
        unicodedata.combining(ch) > 0
        or unicodedata.category(ch) in ("Mn", "Me", "Mc")
        or 0xFE00 <= cp <= 0xFE0F          # variation selectors
        or 0x1F3FB <= cp <= 0x1F3FF        # skin tone modifiers
        or 0xE0020 <= cp <= 0xE007F        # tag characters (subdivision flags)
        or cp == 0x20E3                    # combining enclosing keycap
        or cp == ZWJ
    )


def graphemes(text: str) -> list[str]:
    out: list[str] = []
    after_zwj = False
    ri_open = False  # 直前の cluster が対になっていない regional indicator か
    for ch in text:
        cp = ord(ch)
        is_ri = 0x1F1E6 <= cp <= 0x1F1FF
        if out and (after_zwj or _extends(cp) or (is_ri and ri_open)):
            out[-1] += ch
            if is_ri:
                ri_open = False
        else:
            out.append(ch)
            ri_open = is_ri
        after_zwj = cp == ZWJ
    return out


def _is_emoji_cluster(cluster: str) -> bool:
    cp = ord(cluster[0])
    if len(cluster) > 1 and any(ord(c) in (0xFE0F, ZWJ, 0x20E3) or 0x1F3FB <= ord(c) <= 0x1F3FF for c in cluster):
        return True
    return 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF


def x_length(text: str) -> int:
    text = unicodedata.normalize("NFC", text)
    n = 0
    pos = 0
    for m in URL.finditer(text):
        n += _x_plain(text[pos:m.start()]) + 23
        pos = m.end()
    return n + _x_plain(text[pos:])


def _x_plain(text: str) -> int:
    n = 0
    for cluster in graphemes(text):
        if _is_emoji_cluster(cluster):
            n += 2
            continue
        for ch in cluster:
            cp = ord(ch)
            n += 1 if any(lo <= cp <= hi for lo, hi in X_LIGHT) else 2
    return n


def bluesky_length(text: str) -> int:
    return len(graphemes(text))


def mastodon_length(text: str) -> int:
    return len(URL.sub("x" * 23, text))


def measure(text: str, mastodon_limit: int = 500) -> list[tuple[str, int, int]]:
    text = text.strip("\n")
    return [
        ("x", x_length(text), 280),
        ("bluesky", bluesky_length(text), 300),
        ("mastodon", mastodon_length(text), mastodon_limit),
    ]


def selftest() -> int:
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got}, want {want}")

    check("x ascii", x_length("a" * 280), 280)
    check("x cjk is 2", x_length("あ" * 141), 282)
    check("x url is 23", x_length("see https://example.com/a/very/long/path/that/is/long"), 4 + 23)
    check("x emoji is 2", x_length("📄✨"), 4)
    check("x zwj family is 2", x_length("👨‍👩‍👧"), 2)
    check("x flag pair is 2", x_length("🇯🇵"), 2)
    check("x en dash is 1", x_length("16:15–16:30"), 11)
    check("x fullwidth colon is 2", x_length("："), 2)
    check("bsky zwj family is 1", bluesky_length("👨‍👩‍👧"), 1)
    check("bsky flags", bluesky_length("🇯🇵🇺🇸"), 2)
    check("bsky skin tone", bluesky_length("👍🏽"), 1)
    check("bsky combining", bluesky_length("é"), 1)
    check("bsky url full length", bluesky_length("https://a.b/c"), 13)
    check("mastodon url 23", mastodon_length("x https://example.com/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), 2 + 23)
    # 同じ文面が Bluesky には入り X では超える型 (合成例)
    sample = "📄✨ 新しい論文が出ました！\nhttps://example.org/abs/0000.00000\n" + "あ" * 120 + "\n#example"
    rows = {k: (n, lim) for k, n, lim in measure(sample)}
    check("sample fits bluesky", rows["bluesky"][0] <= 300, True)
    check("sample over x", rows["x"][0] > 280, True)
    if fails:
        print("FAIL\n  " + "\n  ".join(fails))
        return 1
    print("selftest PASS (16 checks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", nargs="?", help="投稿文の file (- = stdin)")
    ap.add_argument("--only", choices=["x", "bluesky", "mastodon"], action="append")
    ap.add_argument("--mastodon-limit", type=int, default=500)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.file:
        ap.error("file か --selftest を指定")
    text = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
    over = False
    for name, n, lim in measure(text, a.mastodon_limit):
        if a.only and name not in a.only:
            continue
        ok = n <= lim
        over |= not ok
        print(f"{name:9s} {n:4d} / {lim:<4d} {'ok' if ok else 'OVER by ' + str(n - lim)}")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
