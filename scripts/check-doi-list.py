#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""check-doi-list.py — 文書 (text / html / docx) から DOI を拾い、 DOI ごとに Crossref の書誌 (題・誌名・巻・頁・年・著者) を並べる。 bib でない業績リストを記載と突き合わせるための入力

WHY THIS EXISTS
---------------
業績リスト (応募書類や CV の論文欄) は手で書かれ、 bib ではないので
inspire-bib-audit.py (refs.bib を INSPIRE と照合) の外にある。 手で書いた行には
共著者名の綴り・年・巻の取り違えが残り、 読む人の目では通る (実測: 正しい DOI の行で
共著者の綴りが 1 字違っていたのを、 この照合で見つけた)。

WHAT IT DOES
------------
- 入力の file (複数可、 `-` は stdin) から DOI (`10.<登録者>/<suffix>`) を順に拾う。
  docx は zip の中の word/document.xml の字だけを読む (Word も python-docx も使わない)。
  末尾の句読点と、 対になっていない閉じ括弧は DOI から外す (`(2026)207` の括弧は残す)
- DOI ごとに Crossref の REST API を引き、 1 件 1 段で 題 / 誌名 巻 頁 年 / 著者 (8 人まで) を出す
- Crossref に無い DOI (JaLC・DataCite など別の登録機関の DOI) は doi.org で解決するかだけを見て、
  行き先を出す (書誌は出さない)。 どこにも無いものは NOT FOUND
- `--json` で同じ内容を JSON の list に

WHAT IT DOES NOT DO
-------------------
記載との突き合わせは人がする (この道具は記載の行を解釈しない = 誌名の略し方・頁の書き方は
文書ごとに違う)。 出力と記載を 1 件ずつ並べて読み、 違いだけを拾う。 Crossref の書誌も
紙面と食い違うことがある (researchmap.md#doi-import) ので、 疑わしい 1 件は出版社の頁で確かめる。

USAGE
-----
    python3 check-doi-list.py list.txt
    python3 check-doi-list.py draft.docx --json > dois.json
    python3 check-doi-list.py --selftest      # network を使わない
    (Crossref への礼儀として連絡先を名乗るなら環境変数 CROSSREF_MAILTO=<address>)
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

DOI_RE = re.compile(r'10\.\d{4,9}/[^\s"<>\]\[,;]+')
TRAIL = '.,;:'


def clean_doi(raw):
    """末尾の句読点と、 対の無い閉じ括弧を外す。"""
    d = raw
    while True:
        prev = d
        d = d.rstrip(TRAIL)
        if d.endswith(')') and d.count(')') > d.count('('):
            d = d[:-1]
        if d == prev:
            return d


def text_of(path):
    """file の字。 docx は word/document.xml の w:t の字を段落ごとに改行して返す。"""
    if path == '-':
        return sys.stdin.read()
    if path.lower().endswith('.docx'):
        with zipfile.ZipFile(path) as z:
            x = z.read('word/document.xml').decode('utf-8')
        x = re.sub(r'</w:p>', '\n', x)
        return re.sub(r'<[^>]+>', '', x).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def find_dois(text):
    out = []
    for m in DOI_RE.finditer(text):
        d = clean_doi(m.group(0))
        if d not in out:
            out.append(d)
    return out


def summarize(doi, msg):
    """Crossref の message から 1 件分の dict を作る。"""
    when = msg.get('published-print') or msg.get('published-online') or msg.get('issued') or {}
    parts = (when.get('date-parts') or [[None]])[0]
    authors = []
    for a in msg.get('author') or []:
        name = ' '.join(x for x in ((a.get('given') or '')[:1] + '.' if a.get('given') else '', a.get('family') or a.get('name') or '') if x)
        authors.append(name)
    return {
        'doi': doi, 'source': 'crossref',
        'title': (msg.get('title') or [''])[0],
        'container': (msg.get('container-title') or [''])[0],
        'volume': msg.get('volume'), 'page': msg.get('page') or msg.get('article-number'),
        'year': parts[0] if parts else None,
        'authors': authors, 'n_authors': len(authors),
    }


def ua():
    mail = os.environ.get('CROSSREF_MAILTO', '').strip()
    return 'check-doi-list/1.0' + (f' (mailto:{mail})' if mail else '')


def look_up(doi, timeout=20):
    url = 'https://api.crossref.org/works/' + urllib.parse.quote(doi, safe='/()')
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': ua()}), timeout=timeout) as r:
            return summarize(doi, json.load(r)['message'])
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return {'doi': doi, 'source': 'error', 'error': f'Crossref HTTP {e.code}'}
    except Exception as e:  # network
        return {'doi': doi, 'source': 'error', 'error': str(e)}
    # Crossref に無い: doi.org が解決するかだけを見る (別の登録機関の DOI)
    req = urllib.request.Request('https://doi.org/' + urllib.parse.quote(doi, safe='/()'), method='HEAD',
                                 headers={'User-Agent': ua()})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        urllib.request.build_opener(NoRedirect).open(req, timeout=timeout)
        return {'doi': doi, 'source': 'doi.org', 'resolves_to': None}
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return {'doi': doi, 'source': 'doi.org', 'resolves_to': e.headers.get('Location')}
        return {'doi': doi, 'source': 'not-found', 'error': f'doi.org HTTP {e.code}'}
    except Exception as e:
        return {'doi': doi, 'source': 'error', 'error': str(e)}


def render(rec):
    d = rec['doi']
    if rec['source'] == 'crossref':
        more = '' if rec['n_authors'] <= 8 else f' ほか (計 {rec["n_authors"]} 人)'
        return (f"{d}\n  題:   {rec['title']}\n  誌:   {rec['container']} 巻={rec['volume']} 頁={rec['page']} 年={rec['year']}\n"
                f"  著者: {', '.join(rec['authors'][:8])}{more}")
    if rec['source'] == 'doi.org':
        return f"{d}\n  Crossref に無い。 doi.org は解決する → {rec.get('resolves_to') or '(行き先なし)'}"
    if rec['source'] == 'not-found':
        return f"{d}\n  NOT FOUND ({rec['error']})"
    return f"{d}\n  ERROR ({rec['error']})"


def selftest():
    assert clean_doi('10.1007/JHEP08(2026)207') == '10.1007/JHEP08(2026)207'
    assert clean_doi('10.1007/JHEP08(2026)207).') == '10.1007/JHEP08(2026)207'
    assert clean_doi('10.1016/j.physletb.2025.139425.') == '10.1016/j.physletb.2025.139425'
    t = ('[1] A. Author, "T," J 1 (2020) [DOI: https://doi.org/10.1007/JHEP08(2026)207]\n'
         '(see doi:10.1088/1475-7516/2025/09/074), and 10.11316/butsuri.79.5_242. again 10.1088/1475-7516/2025/09/074')
    assert find_dois(t) == ['10.1007/JHEP08(2026)207', '10.1088/1475-7516/2025/09/074', '10.11316/butsuri.79.5_242'], find_dois(t)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('word/document.xml', '<w:document><w:body><w:p><w:r><w:t>X [DOI: 10.1103/PhysRevD.1.1</w:t></w:r>'
                   '<w:r><w:t>]</w:t></w:r></w:p><w:p><w:r><w:t>Y &amp; 10.1000/xyz</w:t></w:r></w:p></w:body></w:document>')
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'fixture.docx')
        open(p, 'wb').write(buf.getvalue())
        assert find_dois(text_of(p)) == ['10.1103/PhysRevD.1.1', '10.1000/xyz'], find_dois(text_of(p))
    msg = {'title': ['A fixture title'], 'container-title': ['Fixture Journal'], 'volume': '12', 'article-number': '345',
           'issued': {'date-parts': [[2024, 1]]},
           'author': [{'given': 'Alice', 'family': 'Abe'}, {'given': 'Bob', 'family': 'Baker'}, {'name': 'Fixture Collaboration'}]}
    r = summarize('10.0000/fixture', msg)
    assert (r['volume'], r['page'], r['year']) == ('12', '345', 2024)
    assert r['authors'] == ['A. Abe', 'B. Baker', 'Fixture Collaboration'], r['authors']
    out = render(r)
    assert '題:   A fixture title' in out and '年=2024' in out
    assert 'NOT FOUND' in render({'doi': 'x', 'source': 'not-found', 'error': 'doi.org HTTP 404'})
    print('selftest OK')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--pause', type=float, default=0.2, help='Crossref に引く間隔 (秒)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.files:
        ap.error('file を 1 つ以上 (stdin は -)')
    dois = []
    for f in a.files:
        for d in find_dois(text_of(f)):
            if d not in dois:
                dois.append(d)
    recs = []
    for i, d in enumerate(dois):
        if i:
            time.sleep(a.pause)
        recs.append(look_up(d))
    if a.json:
        print(json.dumps(recs, ensure_ascii=False, indent=1))
    else:
        for r in recs:
            print(render(r))
        bad = sum(r['source'] in ('not-found', 'error') for r in recs)
        print(f'DOI {len(recs)} 件 (Crossref {sum(r["source"] == "crossref" for r in recs)} / 他の登録機関 '
              f'{sum(r["source"] == "doi.org" for r in recs)} / 見つからない・失敗 {bad})')
        return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
