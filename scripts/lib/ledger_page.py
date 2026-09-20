#!/usr/bin/env python3
"""ledger_page.py — 行で書かれた台帳を、 一目で読める 1 枚の HTML にする。

どこで使うか: 通知を押した先の頁、 定期実行の結果を人に見せる頁、 CLI の surface を
  そのまま人に渡す頁。 元データが「1 行 1 項目」 のテキスト (marker / 残り日数 / 本文 /
  出所) なら、 そのまま `<pre>` で流さずにこの module に渡す。

設計 (= 情報設計の判断。 なぜそうしたかは conventions/macos-clickable-notifications.md
  #click-target-page-design が正本):
  - **一番大事な量を 1 カラムに固定する**。 期限の頁なら残り日数。 等幅 + tabular-nums で
    縦に揃えると、 符号と桁が読む前に目に入る。
  - **全部を card にしない**。 重大度は行の左端の帯 (3px) で出す。 border + radius + shadow を
    全ブロックに配ると階層が潰れて、 どれが急ぐのか分からなくなる。
  - **解析できなかった行は生のまま出す**。 台帳の書式は変わるので、 解析器が読めない行を
    落とす設計にすると、 黙って情報が消える。
  - **意味色は accent と別系統**。 超過 = 赤、 接近 = 琥珀、 それ以外は中立。 accent は
    操作できるもの (chip・link) に使う。
  - 色は bare `:root` に全部定義してから `prefers-color-scheme` と `[data-theme]` で
    差し替える (= どちらのテーマ指定も無い既定の状態で壊れないため)。

API:
    parse_item(line) -> dict
        1 行を {mark, delta, days, date, title, src, ident, acct, self_act, raw} に分解。
        days は int (超過が負)、 取れなければ None。
    render_page(title, stamp=..., stats=[...], sections=[...], footer_html="") -> str
        完結した HTML 文字列 (外部 file を一切参照しない = offline / file:// で開ける)。

    section = {"kind": "rows", "heading": str, "note": str, "rows": [...], "empty": str}
            | {"kind": "raw",  "heading": str, "blocks": [{label,badge,when,header,text,open}]}
    row     = parse_item() の戻り + 任意の "tone" ("crit"|"warn"|"soon"|"calm") と "from"
            | {"kind": "head", "title": str}   # 行グループの見出し

usage: python3 ledger_page.py --selftest   (= 合成データで書式と壊れ方を検査)
"""

from __future__ import annotations

import html
import re
import sys

# 行頭に立ちうる marker。 長いものから試す (= "⚠️" は "⚠" + VS16 で、 短い方が先にあると
# 異体字選択子が本文側に残る)
DEFAULT_MARKS = ("⚠️", "🚨", "🔴", "❗", "🔥", "📌", "⏰", "🎫", "📥", "📎", "📬", "📨",
                 "📮", "📣", "🎯", "🔕", "🟠", "🟡", "🔒", "✅", "↩", "·")

_DELTA_PATTERNS = (
    re.compile(r"^([+-]\d+)d(?=\s|$)"),           # -11d / +2d
    re.compile(r"^あと\s*(\d+)\s*日(?=\s|$)"),     # あと 6 日
    re.compile(r"^(\d+)日前(?=\s|$)"),             # 3日前
    re.compile(r"^(今日|明日|昨日)(?=\s|$)"),
)
_DATE_RE = re.compile(r"^(\d{1,2}/\d{1,2})(?=\s|$)")
_REF_RE = re.compile(r"\[([^\[\]]+?):([^\[\]]+?)\]\s*$")
_ACCT_RE = re.compile(r"\(([a-z][a-z0-9-]*)\)\s*$")
_SELF_MARK = "🙋"


def parse_item(raw: str, marks: tuple[str, ...] = DEFAULT_MARKS) -> dict:
    """1 行を表の cell に分解する。 読めない部分は title に残す (= 落とさない)。"""
    s = raw.strip()
    mark = ""
    for m in marks:
        if s.startswith(m):
            mark = m
            s = s[len(m):].lstrip()
            break

    delta, days = "", None
    for pat in _DELTA_PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        tok, val = m.group(0), m.group(1)
        if pat.pattern.startswith(r"^([+-]"):
            days = int(val)
            delta = f"{days:+d}d"
        elif pat.pattern.startswith("^あと"):
            days = int(val)
            delta = f"+{days}d"
        elif pat.pattern.startswith(r"^(\d+)日前"):
            days = -int(val)
            delta = f"-{val}d"
        else:
            days = {"今日": 0, "明日": 1, "昨日": -1}[val]
            delta = val
        s = s[len(tok):].lstrip()
        break

    date = ""
    m = _DATE_RE.match(s)
    if m:
        date = m.group(1)
        s = s[m.end():].lstrip()

    src, ident = "", ""
    m = _REF_RE.search(s)
    if m:
        src, ident = m.group(1), m.group(2)
        s = s[:m.start()].rstrip()

    acct = ""
    m = _ACCT_RE.search(s)
    if m:
        acct = m.group(1)
        s = s[:m.start()].rstrip()

    self_act = _SELF_MARK in s
    return {"mark": mark, "delta": delta, "days": days, "date": date,
            "title": s.replace(_SELF_MARK, "").strip(), "src": src, "ident": ident,
            "acct": acct, "self_act": self_act, "raw": raw.strip()}


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def _row_html(it: dict) -> str:
    esc = html.escape
    if it.get("kind") == "head":
        return f'<li class="grouphead">{esc(it.get("title", ""))}</li>'

    days = it.get("days")
    dcls = ("d-over" if isinstance(days, int) and days < 0
            else "d-today" if days == 0 else "d-ahead")
    meta = []
    if it.get("date"):
        meta.append(f'<span class="date">{esc(it["date"])}</span>')
    if it.get("src"):
        meta.append(f'<span class="chip">{esc(it["src"])}</span>')
    if it.get("ident"):
        meta.append(f'<span class="ident">{esc(it["ident"])}</span>')
    if it.get("acct"):
        meta.append(f'<span class="chip chip-q">{esc(it["acct"])}</span>')
    if it.get("from"):
        meta.append(f'<span class="from">{esc(it["from"])}</span>')
    meta_html = f'<span class="meta">{"".join(meta)}</span>' if meta else ""
    flag = f'<span class="flag" title="自分が動く">{_SELF_MARK}</span>' if it.get("self_act") else ""
    cls = " ".join(x for x in [it.get("tone", ""), "is-self" if it.get("self_act") else ""] if x)
    return (
        f'<li class="row {cls}" data-days="{days if isinstance(days, int) else ""}">'
        f'<span class="mark">{esc(it.get("mark") or "")}</span>'
        f'<span class="delta {dcls}">{esc(it.get("delta") or "")}</span>'
        f'<span class="main"><span class="title">'
        f'{esc(it.get("title") or it.get("raw", ""))}</span>{meta_html}</span>'
        f'{flag}</li>'
    )


def _section_html(sec: dict) -> str:
    esc = html.escape
    heading = esc(sec.get("heading", ""))
    note = f' <em>{esc(sec["note"])}</em>' if sec.get("note") else ""
    head = f"<h2>{heading}{note}</h2>" if heading else ""

    if sec.get("kind") == "raw":
        blocks = []
        for b in sec.get("blocks", []):
            badge = f'<span class="n">{esc(str(b["badge"]))}</span>' if b.get("badge") else ""
            when = f'<span class="when">{esc(b.get("when", ""))}</span>' if b.get("when") else ""
            hdr = f'<p class="hdr">{esc(b["header"])}</p>' if b.get("header") else ""
            blocks.append(
                f'<details{" open" if b.get("open") else ""}>'
                f'<summary><span class="sname">{esc(b.get("label", ""))}</span>{badge}{when}</summary>'
                f'{hdr}<pre>{esc(b.get("text", ""))}</pre></details>'
            )
        body = "\n".join(blocks) or f'<p class="hdr">{esc(sec.get("empty", ""))}</p>'
        return head + body

    rows = [_row_html(r) for r in sec.get("rows", [])]
    if not rows:
        rows = ['<li class="row empty"><span class="mark"></span><span class="delta"></span>'
                f'<span class="main"><span class="title">{esc(sec.get("empty", "なし"))}'
                '</span></span></li>']
    return head + f'<ul class="rows">{"".join(rows)}</ul>'


_CSS = """
:root {
  color-scheme: light dark;
  --bg:#f6f7f9; --surface:#ffffff; --surface-2:#eef1f5; --line:#dde2ea;
  --ink:#171a1f; --ink-2:#5a6472; --ink-3:#8b94a2;
  --accent:#2f4b8f;
  --crit:#b3261e; --crit-soft:#f7e2df; --warn:#8a5a00; --warn-soft:#f6eddb;
  --soon:#2f4b8f;
  --sans:-apple-system,BlinkMacSystemFont,"Hiragino Kaku Gothic ProN","Hiragino Sans",
    "Noto Sans JP","Yu Gothic Medium",Segoe UI,sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,"Courier New",monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#101216; --surface:#171a1f; --surface-2:#1e222a; --line:#272c35;
  --ink:#e7eaef; --ink-2:#9aa3b1; --ink-3:#6d7683;
  --accent:#97acea;
  --crit:#ff8d7e; --crit-soft:#2f1b19; --warn:#e8b45a; --warn-soft:#2a2214;
  --soon:#97acea;
} }
:root[data-theme="dark"] {
  --bg:#101216; --surface:#171a1f; --surface-2:#1e222a; --line:#272c35;
  --ink:#e7eaef; --ink-2:#9aa3b1; --ink-3:#6d7683;
  --accent:#97acea;
  --crit:#ff8d7e; --crit-soft:#2f1b19; --warn:#e8b45a; --warn-soft:#2a2214;
  --soon:#97acea;
}
* { box-sizing:border-box; }
html, body { margin:0; }
body { background:var(--bg); color:var(--ink); font:15px/1.6 var(--sans);
  -webkit-font-smoothing:antialiased; }
.wrap { max-width:960px; margin:0 auto; padding:0 16px 72px; }

header { position:sticky; top:0; z-index:5;
  background:color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter:saturate(1.4) blur(12px);
  border-bottom:1px solid var(--line); margin-bottom:24px; padding:18px 16px 12px; }
.hgrid { max-width:960px; margin:0 auto; display:flex; flex-wrap:wrap;
  align-items:baseline; gap:12px 20px; }
h1 { font-size:17px; font-weight:650; letter-spacing:.01em; margin:0; }
.stamp { color:var(--ink-3); font:12px/1 var(--mono); }
.stats { margin-left:auto; display:flex; gap:18px; }
.stat { display:flex; align-items:baseline; gap:5px; }
.stat b { font:600 19px/1 var(--mono); font-variant-numeric:tabular-nums; }
.stat span { font-size:11px; color:var(--ink-2); letter-spacing:.06em; }
.stat.over b { color:var(--crit); }
.stat.today b { color:var(--warn); }
.filters { max-width:960px; margin:12px auto 0; display:flex; flex-wrap:wrap; gap:6px; }
.filters button { font:12px/1 var(--sans); color:var(--ink-2); background:var(--surface);
  border:1px solid var(--line); border-radius:999px; padding:6px 12px; cursor:pointer;
  transition:border-color .12s, color .12s; }
.filters button:hover { border-color:var(--ink-3); color:var(--ink); }
.filters button[aria-pressed="true"] { background:var(--ink); color:var(--bg);
  border-color:var(--ink); }
.filters button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }

h2 { font-size:13px; font-weight:600; letter-spacing:.08em; color:var(--ink-2);
  margin:34px 0 10px; }
h2 em { font-style:normal; color:var(--ink-3); font-weight:400; letter-spacing:0; }

ul.rows { list-style:none; margin:0; padding:0; background:var(--surface);
  border:1px solid var(--line); border-radius:10px; overflow:hidden; }
.row { display:grid; grid-template-columns:20px 62px minmax(0,1fr) auto;
  align-items:baseline; gap:0 10px; padding:9px 14px 9px 11px;
  border-left:3px solid transparent; border-top:1px solid var(--line); }
.row:first-child { border-top:0; }
.row.crit { border-left-color:var(--crit); background:var(--crit-soft); }
.row.warn { border-left-color:var(--warn); }
.row.soon { border-left-color:var(--soon); }
.row.calm { border-left-color:var(--line); }
.grouphead { padding:12px 14px 7px; border-top:1px solid var(--line);
  font-size:12px; color:var(--ink-2); background:var(--surface-2); }
.grouphead:first-child { border-top:0; }
.mark { font-size:13px; line-height:1.5; }
.delta { font:600 13px/1.5 var(--mono); font-variant-numeric:tabular-nums;
  text-align:right; color:var(--ink-3); white-space:nowrap; }
.d-over { color:var(--crit); }
.d-today { color:var(--warn); }
.d-ahead { color:var(--ink-2); }
.main { min-width:0; }
.title { display:block; word-break:break-word; }
.row.crit .title { font-weight:600; }
.meta { display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-top:3px; }
.date { font:12px/1 var(--mono); color:var(--ink-3); }
.chip { font:11px/1 var(--sans); color:var(--ink-2); background:var(--surface-2);
  border-radius:4px; padding:3px 6px; }
.chip-q { color:var(--accent); }
.ident { font:11px/1.4 var(--mono); color:var(--ink-3); word-break:break-all; }
.from { font:11px/1 var(--sans); color:var(--ink-3); white-space:nowrap;
  border-left:1px solid var(--line); padding-left:7px; }
.flag { font-size:12px; }
.row.empty { color:var(--ink-3); }

details { background:var(--surface); border:1px solid var(--line); border-radius:10px;
  padding:0 14px; margin-bottom:8px; }
summary { cursor:pointer; padding:11px 0; display:flex; align-items:center; gap:9px;
  font-size:13px; }
summary::-webkit-details-marker { display:none; }
summary::before { content:"\\25B8"; color:var(--ink-3); font-size:10px;
  transition:transform .12s; }
details[open] summary::before { transform:rotate(90deg); }
summary:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.sname { font-weight:600; }
summary .n { font:600 11px/1 var(--mono); color:var(--crit); background:var(--crit-soft);
  border-radius:999px; padding:4px 7px; }
summary .when { margin-left:auto; font:11px/1 var(--mono); color:var(--ink-3); }
.hdr { color:var(--ink-3); font-size:12px; margin:0 0 8px; }
pre { background:var(--surface-2); border-radius:8px; padding:12px; overflow-x:auto;
  margin:0 0 14px; font:12.5px/1.65 var(--mono); white-space:pre-wrap;
  word-break:break-word; }
footer { margin-top:36px; color:var(--ink-3); font-size:12px; }
footer code { font:11.5px/1.5 var(--mono); background:var(--surface-2); padding:2px 5px;
  border-radius:4px; }
@media (max-width:520px) {
  .row { grid-template-columns:18px 54px minmax(0,1fr); }
  .flag { grid-column:3; justify-self:end; }
  .stats { margin-left:0; width:100%; gap:16px; }
}
@media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
"""

_JS = """
(function () {
  var btns = [].slice.call(document.querySelectorAll('.filters button'));
  var rows = [].slice.call(document.querySelectorAll('.row'));
  var heads = [].slice.call(document.querySelectorAll('.grouphead'));
  function apply(mode) {
    rows.forEach(function (r) {
      var d = r.getAttribute('data-days');
      var over = d !== '' && d !== null && Number(d) < 0;
      var self = r.classList.contains('is-self');
      r.hidden = (mode === 'over' && !over) || (mode === 'self' && !self);
    });
    heads.forEach(function (h) { h.hidden = mode !== 'all'; });
    btns.forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.filter === mode));
    });
  }
  btns.forEach(function (b) {
    b.addEventListener('click', function () { apply(b.dataset.filter); });
  });
})();
"""


def render_page(title: str, *, stamp: str = "", stats: list[tuple] | None = None,
                sections: list[dict] | None = None, filters: bool = True,
                footer_html: str = "") -> str:
    """完結した 1 枚の HTML を返す (外部 file を参照しない = file:// でも開ける)。

    stats = [(値, ラベル, tone)] で tone は "over" / "today" / ""。
    """
    esc = html.escape
    stat_html = "".join(
        f'<span class="stat {esc(tone)}"><b>{esc(str(val))}</b>'
        f'<span>{esc(lab)}</span></span>'
        for val, lab, tone in (stats or [])
    )
    filt = ('<div class="filters">'
            '<button type="button" id="f-all" data-filter="all" aria-pressed="true">すべて</button>'
            '<button type="button" id="f-over" data-filter="over" aria-pressed="false">超過だけ</button>'
            '<button type="button" id="f-self" data-filter="self" aria-pressed="false">自分が動く</button>'
            '</div>') if filters else ""
    body = "\n".join(_section_html(s) for s in (sections or []))
    foot = f"<footer>{footer_html}</footer>" if footer_html else ""
    return (
        '<!DOCTYPE html>\n<html lang="ja"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n<style>{_CSS}</style></head>\n<body>\n"
        f'<header><div class="hgrid"><h1>{esc(title)}</h1>'
        f'<span class="stamp">{esc(stamp)}</span>'
        f'<div class="stats">{stat_html}</div></div>{filt}</header>\n'
        f'<div class="wrap">\n{body}\n{foot}\n</div>\n'
        f"<script>{_JS}</script>\n</body></html>\n"
    )


def _selftest() -> int:
    ok = fail = 0

    def check(desc: str, cond: bool) -> None:
        nonlocal ok, fail
        if cond:
            print(f"[PASS] {desc}")
            ok += 1
        else:
            print(f"[FAIL] {desc}")
            fail += 1

    # 合成データ (= 実在の台帳は使わない)
    it = parse_item("  🔴 -11d 9/9 甲野さんに都合を返す 🙋  [sample-repo:2026-09-09-reply]")
    check("marker を取る", it["mark"] == "🔴")
    check("超過は負の days", it["days"] == -11 and it["delta"] == "-11d")
    check("日付を取る", it["date"] == "9/9")
    check("出所を repo と id に分ける",
          it["src"] == "sample-repo" and it["ident"] == "2026-09-09-reply")
    check("自分が動く印を本文から外して旗にする",
          it["self_act"] and "🙋" not in it["title"] and it["title"] == "甲野さんに都合を返す")
    check("先の期限は正の days", parse_item("⏰ +4d 9/24 様式を出す")["days"] == 4)
    check("「あと N 日」 を読む", parse_item("🎫 あと 6 日 会期前の準備")["days"] == 6)
    check("「N 日前」 は負", parse_item("↩ 3日前 だれか: Re: 件名")["days"] == -3)
    check("今日 = 0", parse_item("↩ 今日 だれか: Re: 件名")["days"] == 0)
    check("account を chip に分ける",
          parse_item("↩ 今日 だれか: Re: 件名  (lab)")["acct"] == "lab")
    check("異体字つき marker を先に取る (⚠️ の VS16 が本文に残らない)",
          parse_item("⚠️ 点検の期限")["title"] == "点検の期限")
    raw = parse_item("解析できない行はそのまま")
    check("解析できなくても本文を落とさない", raw["title"] == "解析できない行はそのまま")
    check("解析できない行は days を持たない", raw["days"] is None)

    html_out = render_page(
        "見本の台帳", stamp="9/9 (Tue) 10:00",
        stats=[(2, "超過", "over"), (0, "今日", "today")],
        sections=[
            {"kind": "rows", "heading": "急ぐもの", "note": "2 件",
             "rows": [{"kind": "head", "title": "見出し"},
                      dict(parse_item("🔴 -11d 9/9 甲野さんに都合を返す 🙋"), tone="crit"),
                      dict(parse_item("⏰ +4d 9/24 様式を出す"), tone="soon")]},
            {"kind": "rows", "heading": "空の節", "rows": [], "empty": "なにもありません"},
            {"kind": "raw", "heading": "全文",
             "blocks": [{"label": "見本", "badge": 1, "when": "9/9 10:00",
                         "header": "見本の説明", "text": "生テキスト <script>", "open": True}]},
        ],
        footer_html="脚注")
    check("行が表に出る", "甲野さんに都合を返す" in html_out)
    check("超過は d-over で色が付く", 'class="delta d-over"' in html_out)
    check("空の節でも壊れない", "なにもありません" in html_out)
    check("生テキストは escape される",
          "&lt;script&gt;" in html_out and "<script>生" not in html_out)
    check("色 token は bare :root に全部ある (= テーマ未指定で壊れない)",
          html_out.index("--crit:#b3261e") < html_out.index("prefers-color-scheme"))
    check("明示 dark の上書きも持つ", ':root[data-theme="dark"]' in html_out)
    check("外部 file を参照しない",
          "http://" not in html_out and "https://" not in html_out)
    check("横スクロールする要素は自分の器に入る", "overflow-x:auto" in html_out)

    print(f"\n=== selftest: {ok} passed, {fail} failed ===")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv[1:] else 0)
