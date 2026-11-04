#!/usr/bin/env python3
"""prose-pass-compare.py — 共通の土台から独立に直した 2 本の写しを、 変わった所ごとに並べる (語の差 + 選択の注記つきの HTML)。--selftest 内蔵。

使う場面 = 同じ原稿 (や文書) の文面を 2 人の worker (別 vendor でも) に独立に直させ、 検収で両方を見比べて採る所を決めるとき
(規約 = conventions/multi-session-coordination.md#parallel-full-text-candidates)。 2 本を順に当てると後の方が先の直しを消すので、
共通の土台 (2 人が見た版) に対する差分で見比べる。

  python3 prose-pass-compare.py BASE A B                       # 変わった所の一覧 (土台の行・どちらが直したか・語の差)
  python3 prose-pass-compare.py BASE A B --html out.html       # 2 列の HTML (赤 = 消した語、 緑 = 足した語)
  python3 prose-pass-compare.py BASE A B --html out.html --picks picks.json   # 所ごとの選択の注記を足す
  python3 prose-pass-compare.py BASE A B --json regions.json   # 所の一覧を JSON で (選択を書く台に使う)

- 「所」 = 土台の行の範囲のうち、 どちらか (か両方) が変えた所。 両方の変えた範囲が重なれば 1 つの所にまとめる。
  行の単位で揃えるので、 段落を 1 行に書く原稿 (行 = 段落) では所 = 段落になる。
- --picks の JSON = {"<所の番号>": "<その所の選択と理由>"} (番号は一覧の #N)。 HTML の各所の見出しの下に出る。
- --names で 2 本の名前を付ける (既定 A / B)。
- 当てるのはこの道具でなく 3-way の merge: `git merge-file -p --diff3 <A の写し> <BASE> <B の写し>` で、 片方だけの直しは自動で重なり、
  両方が同じ行を変えた所だけが衝突として残る。 衝突を 1 つずつ選んで解き、 不変量 (数式・引用・参照・数値) を
  tex-prose-pass-invariants.py で土台と比べてから当てる (TeX の原稿なら保護領域の guard を通す)。
"""
import argparse
import difflib
import html
import json
import re
import sys


def _opcodes(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [op for op in sm.get_opcodes() if op[0] != "equal"]


def _side_text(base, side, b0, b1):
    """土台の行の範囲 [b0, b1) に当たる side の行を返す (変えたか、 も)。"""
    out, touched = [], False
    for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, side, autojunk=False).get_opcodes():
        if i2 < b0 and not (i1 == i2 == b0):
            continue
        if i1 > b1 or (i1 == b1 and i1 != i2):
            continue
        if t == "equal":
            lo, hi = max(i1, b0), min(i2, b1)
            out.extend(side[j1 + (lo - i1): j1 + (hi - i1)])
        else:
            touched = True
            out.extend(side[j1:j2])
    return "\n".join(out), touched


def regions(base_text, a_text, b_text):
    """変わった所の一覧: [{line, base, a, b, a_changed, b_changed}] (line は土台の 1 始まりの行)。"""
    base, a, b = (t.split("\n") for t in (base_text, a_text, b_text))
    spans = sorted([i1, max(i2, i1)] for side in (a, b) for _, i1, i2, _, _ in _opcodes(base, side))
    merged = []
    for s in spans:
        if merged and s[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], s[1])
        else:
            merged.append(list(s))
    out = []
    for b0, b1 in merged:
        at, ac = _side_text(base, a, b0, b1)
        bt, bc = _side_text(base, b, b0, b1)
        out.append(dict(line=b0 + 1, base="\n".join(base[b0:b1]), a=at, b=bt, a_changed=ac, b_changed=bc))
    return out


def _toks(s):
    return re.findall(r"\s+|[^\s]+", s)


def word_diff(old, new, fmt="text"):
    ta, tb = _toks(old), _toks(new)
    out = []
    for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        x, y = "".join(ta[i1:i2]), "".join(tb[j1:j2])
        if t == "equal":
            out.append(html.escape(x) if fmt == "html" else x)
            continue
        if fmt == "html":
            out += ([f"<del>{html.escape(x)}</del>"] if x else []) + ([f"<ins>{html.escape(y)}</ins>"] if y else [])
        else:
            out += ([f"[-{x}-]"] if x else []) + ([f"{{+{y}+}}"] if y else [])
    return "".join(out)


def _tag(r, na, nb):
    if r["a_changed"] and r["b_changed"]:
        return "both"
    return na if r["a_changed"] else nb


def render_text(rs, na, nb):
    lines = []
    for k, r in enumerate(rs, 1):
        lines.append(f"===== #{k} line {r['line']} {_tag(r, na, nb)}")
        if r["a_changed"]:
            lines.append(f"--- {na}: " + word_diff(r["base"], r["a"]))
        if r["b_changed"]:
            lines.append(f"--- {nb}: " + word_diff(r["base"], r["b"]))
    return "\n".join(lines)


PAGE_HEAD = """<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--del:#ffe1e1;--ins:#dcf5dc;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161616;--fg:#e8e8e8;--mut:#999;--del:#5a2525;--ins:#1f4a26;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,sans-serif;margin:0 auto;max-width:1400px;padding:16px}}
h1{{font-size:20px}}h2{{font-size:16px;margin:24px 0 8px;border-top:1px solid var(--line);padding-top:12px}}h2 small{{color:var(--mut);font-weight:normal}}
h3{{font-size:13px;color:var(--mut);margin:0 0 4px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media (max-width:800px){{.grid{{grid-template-columns:1fr}}}}
p.t{{margin:0;white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,monospace;font-size:13px}}
del{{background:var(--del);text-decoration:line-through}}ins{{background:var(--ins);text-decoration:none}}.same{{color:var(--mut)}}
.pick{{font-weight:600;margin:4px 0 8px}}
</style></head><body><h1>{title}</h1><p>赤の取り消し = 消した語、 緑 = 足した語 (土台に対する語の差)。</p>
"""


def render_html(rs, na, nb, picks=None, title="2 本の直しの比較"):
    picks = picks or {}
    rows = []
    for k, r in enumerate(rs, 1):
        tag = {"both": "両方"}.get(_tag(r, na, nb), _tag(r, na, nb) + " だけ")
        cell = lambda changed, new: (word_diff(r["base"], new, "html") if changed  # noqa: E731
                                     else '<span class="same">(変更なし)</span>')
        pick = f'<p class="pick">選択: {html.escape(picks[str(k)])}</p>' if str(k) in picks else ""
        rows.append(f'<section><h2>#{k} <small>土台 l.{r["line"]} · {tag}</small></h2>{pick}'
                    f'<div class="grid"><div><h3>{html.escape(na)}</h3><p class="t">{cell(r["a_changed"], r["a"])}</p></div>'
                    f'<div><h3>{html.escape(nb)}</h3><p class="t">{cell(r["b_changed"], r["b"])}</p></div></div></section>')
    return PAGE_HEAD.format(title=html.escape(title)) + "\n".join(rows) + "</body></html>"


def summary(rs, na, nb):
    both = sum(1 for r in rs if r["a_changed"] and r["b_changed"])
    only_a = sum(1 for r in rs if r["a_changed"] and not r["b_changed"])
    only_b = sum(1 for r in rs if r["b_changed"] and not r["a_changed"])
    return f"所 {len(rs)}: 両方 {both}、 {na} だけ {only_a}、 {nb} だけ {only_b}"


def selftest():
    base = "Para one is long, and it has two clauses.\n\nPara two stays.\n\nPara three has a typo teh.\n\nPara four."
    a = "Para one is long. It has two clauses.\n\nPara two stays.\n\nPara three has a typo the.\n\nPara four."
    b = "Para one is long, and it has two parts.\n\nPara two stays.\n\nPara three has a typo teh.\n\nPara four, now longer."
    rs = regions(base, a, b)
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  [ok] " if cond else "  [FAIL] ") + name)
        ok = ok and cond

    check("3 regions (one both, one A only, one B only)", len(rs) == 3)
    check("region 1 changed by both", rs[0]["a_changed"] and rs[0]["b_changed"] and rs[0]["line"] == 1)
    check("region 2 changed by A only", rs[1]["a_changed"] and not rs[1]["b_changed"] and rs[1]["line"] == 5)
    check("region 3 changed by B only", rs[2]["b_changed"] and not rs[2]["a_changed"] and rs[2]["line"] == 7)
    check("summary counts", summary(rs, "A", "B") == "所 3: 両方 1、 A だけ 1、 B だけ 1")
    check("word diff marks removed and added words", word_diff("teh cat", "the cat") == "[-teh-]{+the+} cat")
    page = render_html(rs, "A", "B", {"1": "A を採る"})
    check("html carries del/ins and the pick note", "<del>teh.</del>" in page and "<ins>the.</ins>" in page
          and "選択: A を採る" in page)
    check("html escapes markup in the text", "&lt;b&gt;" in render_html(regions("x", "<b>", "x"), "A", "B"))
    check("unchanged copies give no region", regions(base, base, base) == [])
    print("selftest:", "ALL PASS" if ok else "FAILURES above")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("base", nargs="?")
    ap.add_argument("a", nargs="?")
    ap.add_argument("b", nargs="?")
    ap.add_argument("--names", nargs=2, default=["A", "B"], metavar=("NAME_A", "NAME_B"))
    ap.add_argument("--html")
    ap.add_argument("--picks", help='JSON {"<所の番号>": "<選択と理由>"}')
    ap.add_argument("--json")
    ap.add_argument("--title", default="2 本の直しの比較")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not (args.base and args.a and args.b):
        ap.error("BASE A B が要る (または --selftest)")
    read = lambda p: open(p, encoding="utf-8").read()  # noqa: E731
    rs = regions(read(args.base), read(args.a), read(args.b))
    na, nb = args.names
    if args.json:
        json.dump(rs, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.html:
        picks = json.load(open(args.picks, encoding="utf-8")) if args.picks else None
        open(args.html, "w", encoding="utf-8").write(render_html(rs, na, nb, picks, args.title))
    if not (args.json or args.html):
        print(render_text(rs, na, nb))
    print(summary(rs, na, nb), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
