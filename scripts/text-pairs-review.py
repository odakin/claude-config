#!/usr/bin/env python3
"""提案の note の「今の文 → 案の文」 の組を、 語の差を色で示した 1 枚の HTML にする (本人が組をまとめて読んで決めるための頁)。

なぜ (実測): 原稿の要旨・序論・まとめのように本人の裁定が要る区画の書き直しは、 組が 10 を越えると chat に並べきれず、
長い LaTeX の段落を 2 つ並べても何が変わったかが読み取れない。 消える語を赤・入る語を緑で 1 枚にすると、
本人は「全部案で」「A と C は今のまま」 と組の名前で答えられ、 答えの後は同じ note を
[`apply-text-pairs.py`](apply-text-pairs.py) の `--note` にそのまま渡して当てられる (見せた文と当てる文が食い違わない)。
読み手が共同研究者の AI でも同じ頁を判断の記録として残せる。

note の形 (`apply-text-pairs.py --note` と同じ):

    #### <組の題>
    <説明の行 (任意、 何がなぜ変わるか)>
    <!-- now ID -->
    ```latex
    今の文
    ```
    <!-- new ID -->
    ```latex
    案の文
    ```

使い方:

    python3 text-pairs-review.py NOTE.md OUT.html [--title '題'] [--intro '頁の頭の 1 文'] [--elide ID,ID] [--stop-at '## 3.']
    python3 text-pairs-review.py --selftest

- `--elide ID,ID` = 今の文が長い組 (節をまるごと外す組など) は、 頭の 3 行と行数だけを示し、 案の文を全部示す。
- `--stop-at` = この文字列で始まる行から後は読まない (note の後半に組の説明でない節があるとき)。
- 頁は外部の資源を読まない 1 file (色は light / dark の両方)。 原稿の文を含むので、 置き場所は原稿と同じ公開範囲の repo か一時 dir にする。
"""
import argparse
import difflib
import html
import re
import sys
import tempfile
from pathlib import Path

CSS = """:root{--bg:#fff;--fg:#1d1d1f;--mut:#666;--del:#ffd7d5;--delfg:#8a1c14;--ins:#d4f7dc;--insfg:#0f5a26;--card:#f6f6f8;--bd:#ddd}
@media (prefers-color-scheme: dark){:root{--bg:#18181b;--fg:#e8e8ea;--mut:#a0a0a8;--del:#5a2320;--delfg:#ffc9c4;--ins:#1e4a2c;--insfg:#c8f5d2;--card:#232328;--bd:#3a3a40}}
body{background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,'Hiragino Sans',sans-serif;max-width:980px;margin:0 auto;padding:16px}
h1{font-size:20px} h2{font-size:17px;margin-top:28px;border-top:1px solid var(--bd);padding-top:16px} .id{font-family:monospace;color:var(--mut)}
.expl{color:var(--mut);font-size:14px;white-space:pre-wrap}
.tex{background:var(--card);border:1px solid var(--bd);border-radius:6px;padding:10px;font-family:Menlo,monospace;font-size:13px;white-space:pre-wrap;word-break:break-word}
del{background:var(--del);color:var(--delfg);text-decoration:line-through} ins{background:var(--ins);color:var(--insfg);text-decoration:none}"""


def parse(lines, stop_at=None):
    items, cur, in_expl, i = [], None, False, 0
    while i < len(lines):
        line = lines[i]
        if stop_at and line.startswith(stop_at):
            break
        m = re.match(r'^#### (.*)', line)
        if m:
            cur = {'title': m.group(1), 'expl': [], 'now': None, 'new': None, 'id': ''}
            items.append(cur)
            in_expl = True
            i += 1
            continue
        m = re.match(r'^<!-- (now|new) (\S+) -->', line)
        if m and cur is not None:
            kind, pid = m.group(1), m.group(2)
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                i += 1
            i += 1
            block = []
            while i < len(lines) and not lines[i].startswith('```'):
                block.append(lines[i])
                i += 1
            cur[kind] = '\n'.join(block)
            cur['id'] = pid
            in_expl = False
            i += 1
            continue
        if cur is not None and in_expl and not line.startswith('#'):
            cur['expl'].append(line)
        i += 1
    bad = [it['title'] for it in items if (it['now'] is None) != (it['new'] is None)]
    if bad:
        raise SystemExit('now と new の片方しか無い組: ' + ', '.join(bad))
    return [it for it in items if it['now'] is not None]


def word_diff(a, b):
    split = lambda s: re.findall(r'\S+|\s+', s)
    A, B = split(a), split(b)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, A, B, autojunk=False).get_opcodes():
        if op == 'equal':
            out.append(html.escape(''.join(A[i1:i2])))
        if op in ('delete', 'replace'):
            out.append('<del>' + html.escape(''.join(A[i1:i2])) + '</del>')
        if op in ('insert', 'replace'):
            out.append('<ins>' + html.escape(''.join(B[j1:j2])) + '</ins>')
    return ''.join(out)


def render(items, title, intro, elide):
    h = ['<!doctype html><html lang="ja"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width,initial-scale=1">'
         '<title>%s</title><style>%s</style></head><body>' % (html.escape(title), CSS),
         '<h1>%s</h1>' % html.escape(title),
         '<p>%s</p>' % html.escape(intro or '赤 = 消える語、 緑 = 入る語。 組の名前で答える (例: 「全部案で」「A と C は今のまま」)。')]
    for it in items:
        expl = '\n'.join(x for x in it['expl'] if x.strip()).strip()
        h.append('<h2><span class="id">%s</span> %s</h2>' % (html.escape(it['id']), html.escape(it['title'])))
        if expl:
            h.append('<div class="expl">%s</div>' % html.escape(expl))
        if it['id'] in elide:
            head = it['now'].split('\n')
            h.append('<div class="tex"><del>%s\n… (今の %d 行をまるごと外す)</del>\n<ins>%s</ins></div>'
                     % (html.escape('\n'.join(head[:3])), len(head), html.escape(it['new'])))
        else:
            h.append('<div class="tex">%s</div>' % word_diff(it['now'], it['new']))
    h.append('</body></html>')
    return '\n'.join(h)


def selftest():
    note = '\n'.join([
        '#### 組 A — 文を短く', '主語を前に出す。', '<!-- now A -->', '```latex', 'The cat, which was black, sat.', '```',
        '<!-- new A -->', '```latex', 'The black cat sat.', '```',
        '#### 組 B — 節を外す', '<!-- now B -->', '```latex', 'line 1', 'line 2', 'line 3', 'line 4', '```',
        '<!-- new B -->', '```latex', '', '```', '## 3. ほかの節', '#### 組 C', '<!-- now C -->', '```', 'x', '```'])
    items = parse(note.split('\n'), stop_at='## 3.')
    ok = [len(items) == 2, items[0]['id'] == 'A', items[0]['expl'] == ['主語を前に出す。']]
    page = render(items, '題', None, {'B'})
    ok += ['<del>' in page and '<ins>' in page, '今の 4 行をまるごと外す' in page, 'line 4' not in page,
           page.count('<h2>') == 2]
    try:
        parse(['#### 組 X', '<!-- now X -->', '```', 'a', '```'])
        ok.append(False)
    except SystemExit:
        ok.append(True)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 'n.md'
        p.write_text(note, encoding='utf-8')
        sys.argv = ['x', str(p), str(Path(d) / 'o.html'), '--elide', 'B', '--stop-at', '## 3.']
        main()
        ok.append((Path(d) / 'o.html').read_text(encoding='utf-8').count('<h2>') == 2)
    print('selftest:', 'ALL PASS' if all(ok) else 'FAIL %s' % ok)
    return 0 if all(ok) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('note', nargs='?')
    ap.add_argument('out', nargs='?')
    ap.add_argument('--title', default='決めること')
    ap.add_argument('--intro', default=None)
    ap.add_argument('--elide', default='')
    ap.add_argument('--stop-at', default=None)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.note and a.out):
        ap.error('NOTE と OUT が要る')
    items = parse(Path(a.note).read_text(encoding='utf-8').split('\n'), a.stop_at)
    Path(a.out).write_text(render(items, a.title, a.intro, set(filter(None, a.elide.split(',')))), encoding='utf-8')
    print('%d 組 -> %s' % (len(items), a.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
