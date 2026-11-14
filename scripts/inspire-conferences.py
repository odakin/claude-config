#!/usr/bin/env python3
"""inspire-conferences.py — INSPIRE の conferences DB から、 開始日が窓に入る会議を全部引いて一覧にする (会議の候補の洗い出し用)。

「次はどの会議で話すか」 の sweep の口の 1 つ (手順 = conventions/conference-candidate-search.md)。
開始日の窓で引き、 1 行 = 会期・題・都市と国・INSPIRE の分野・頁の URL を出す。 生の hit を JSON に残せば、
後で候補を選び直すときに取り直さずに済む (sweep の記録の隣に置く)。

  python3 scripts/inspire-conferences.py --from 2027-01-25 --to 2027-03-31
      1 行ずつ: 会期 | 題 | 都市, 国 | 分野
  python3 scripts/inspire-conferences.py --from <日> --to <日> --markdown
      markdown の表の行 (| 会期 | 題 | 都市, 国 | 分野 | URL |) = sweep の記録に貼る形
  python3 scripts/inspire-conferences.py --from <日> --to <日> --json <file>
      上に加えて、 生の hit (metadata) を <file> に書く
  python3 scripts/inspire-conferences.py --selftest   # network なし

⚠️ INSPIRE に載るのは主催が登録した会議だけ。 告知が遅いシリーズ (春の回を秋〜初冬に告知する会議) は窓に出ない =
  出なかったことは「その会議が無い」 ではない (過去の回の日程から見込みを立てる手順も上の doc)。
exit: 0 = 完了 / 2 = 引数・network の失敗
"""
import json
import re
import sys
import urllib.parse
import urllib.request

API = 'https://inspirehep.net/api/conferences'
FIELDS = 'titles,opening_date,closing_date,addresses,inspire_categories,urls,series,cnum,acronyms,control_number'
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'inspire-conferences/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch_window(date_from, date_to, fetch=fetch_json, page_size=250, limit=2000):
    """開始日が [date_from, date_to] の会議を全部 (limit まで) → (hits, total)。 開始日の昇順。"""
    q = f'opening_date:[{date_from} TO {date_to}]'
    hits, page, total = [], 1, 0
    while len(hits) < limit:
        url = API + '?' + urllib.parse.urlencode(
            {'q': q, 'size': page_size, 'page': page, 'sort': 'dateasc', 'fields': FIELDS})
        data = fetch(url)
        total = data['hits']['total']
        got = data['hits']['hits']
        hits.extend(got)
        if not got or len(hits) >= total:
            break
        page += 1
    return hits, total


def row(hit):
    """1 件 → dict (会期・題・場所・分野・URL)。 欠けた欄は空文字。"""
    m = hit.get('metadata', {})
    titles = m.get('titles') or [{}]
    addr = (m.get('addresses') or [{}])[0]
    city = (addr.get('cities') or [''])[0]
    country = addr.get('country', '')
    urls = m.get('urls') or []
    url = urls[0].get('value', '') if urls else ''
    if not url and m.get('control_number'):
        url = f"https://inspirehep.net/conferences/{m['control_number']}"
    return {
        'start': m.get('opening_date', ''),
        'end': m.get('closing_date', ''),
        'title': titles[0].get('title', ''),
        'place': ', '.join(x for x in (city, country) if x),
        'cats': ', '.join(c.get('term', '') for c in m.get('inspire_categories') or []),
        'url': url,
    }


def line(r):
    return f"{r['start']}〜{r['end']} | {r['title']} | {r['place']} | {r['cats']}"


def md_row(r):
    cells = [f"{r['start']}〜{r['end']}", r['title'], r['place'], r['cats'], r['url']]
    return '| ' + ' | '.join(c.replace('|', '/') for c in cells) + ' |'


def _selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))

    # 合成の hit (実在の会議ではない)
    h1 = {'metadata': {'titles': [{'title': 'Example Workshop A'}], 'opening_date': '2030-02-01',
                       'closing_date': '2030-02-05', 'addresses': [{'cities': ['Sampletown'], 'country': 'Nowhere'}],
                       'inspire_categories': [{'term': 'Phenomenology-HEP'}, {'term': 'Theory-HEP'}],
                       'urls': [{'value': 'https://example.org/a'}], 'control_number': 1}}
    h2 = {'metadata': {'titles': [{'title': 'Pipe | Title'}], 'opening_date': '2030-03-01', 'control_number': 2}}
    r1, r2 = row(h1), row(h2)
    ck('場所 = 都市, 国', r1['place'] == 'Sampletown, Nowhere')
    ck('分野を , で並べる', r1['cats'] == 'Phenomenology-HEP, Theory-HEP')
    ck('欠けた欄は空', r2['end'] == '' and r2['place'] == '' and r2['cats'] == '')
    ck('URL が無ければ INSPIRE の頁', r2['url'] == 'https://inspirehep.net/conferences/2')
    ck('1 行の形', line(r1) == '2030-02-01〜2030-02-05 | Example Workshop A | Sampletown, Nowhere | Phenomenology-HEP, Theory-HEP')
    ck('markdown の | を逃がす', '| Pipe / Title |' in md_row(r2))

    # 頁送り: total 3、 page_size 2 → 2 回引いて 3 件
    pages = {1: [h1, h2], 2: [h1]}
    calls = []

    def fake(url):
        p = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['page'][0])
        calls.append(url)
        return {'hits': {'total': 3, 'hits': pages.get(p, [])}}

    hits, total = fetch_window('2030-01-01', '2030-12-31', fetch=fake, page_size=2)
    ck('頁送りで全部', len(hits) == 3 and total == 3 and len(calls) == 2)
    ck('窓の式', 'opening_date%3A%5B2030-01-01+TO+2030-12-31%5D' in calls[0])
    bad = [n for n, c in ok if not c]
    for n in bad:
        print('FAIL:', n)
    print('selftest:', 'ok' if not bad else f'{len(bad)} 件失敗')
    return 0 if not bad else 1


def main(argv):
    if argv[:1] == ['--selftest']:
        return _selftest()
    args = {'--from': None, '--to': None, '--json': None}
    md = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in args and i + 1 < len(argv):
            args[a] = argv[i + 1]
            i += 2
        elif a == '--markdown':
            md = True
            i += 1
        else:
            print(f'inspire-conferences: 分からない引数 {a!r} (使い方 = この file の冒頭)', file=sys.stderr)
            return 2
    f, t = args['--from'], args['--to']
    if not (f and t and DATE.match(f) and DATE.match(t)):
        print('inspire-conferences: --from と --to に YYYY-MM-DD が要る', file=sys.stderr)
        return 2
    try:
        hits, total = fetch_window(f, t)
    except Exception as e:  # network・API の失敗
        print(f'inspire-conferences: 取得に失敗 ({e})', file=sys.stderr)
        return 2
    if args['--json']:
        with open(args['--json'], 'w', encoding='utf-8') as fh:
            json.dump(hits, fh, ensure_ascii=False, indent=1)
    print(f'# INSPIRE conferences: 開始日 {f}〜{t} = {total} 件 (取得 {len(hits)} 件)')
    for h in hits:
        r = row(h)
        print(md_row(r) if md else line(r))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
