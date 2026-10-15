#!/usr/bin/env python3
"""inspire-author-records.py — 1 人の業績が INSPIRE の複数の著者 record に割れていないか・record に別人の論文が混じっていないかを数え、 本人の業績だけを出す検索式 (API と画面の URL) を作る。

INSPIRE の著者 record は自動の名寄せで作られるので、 1 人の業績が 2 つ以上の record に割れていたり
(所属が変わった前後など)、 record に同姓同頭文字の別人の論文が付いていたりする (実測)。
著者ページ `authors/<recid>` にリンクすると業績の一部しか出ず、 名前検索 (`a <姓>, <頭文字>`) にリンクすると
別人が大量に混じる。 この道具で record ごとに数え、 本人の record を合算して本人の表記で絞った式を作る。

  python3 scripts/inspire-author-records.py survey '<姓>, <頭文字>'
      名前検索の hit を、 その姓の著者 entry が付いている record ごとに数える (件数・BAI・表記・所属の上位)。
      本人と思われる行が 2 つ以上あれば割れている。 姓の一致する著者がいない hit (別の頭文字の人) の件数も出す
  python3 scripts/inspire-author-records.py check <recid> [<recid> ...] --name '<表記>' [--name '<表記>' ...]
      その record の論文のうち、 record に付いた著者の表記が --name のどれでもないもの (= 別人の候補) を並べ、
      record の合算を本人の表記で絞った検索式の件数・残った別人の候補の数・画面の URL を出す
      (--name は survey の「表記」 列から本人のものを選ぶ。 引用符つきの完全一致で引かれる)
  python3 scripts/inspire-author-records.py --selftest   # network なし

exit: 0 = 完了 / 1 = 絞った式にも別人の候補が残る (check) / 2 = 引数・network の失敗
使い方と罠 (引用符なしの `a` は record で引くので絞りにならない、 `not a` は効かない) =
conventions/identity-in-config.md#split-and-polluted-author-records
"""
import collections
import json
import sys
import urllib.parse
import urllib.request

API = 'https://inspirehep.net/api/literature'
UI = 'https://inspirehep.net/literature'
FIELDS = 'control_number,earliest_date,titles.title,authors.full_name,authors.record,authors.ids,authors.affiliations'


def fetch_json(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch_all(q, fetch=fetch_json, page_size=250, limit=3000):
    """q の hit を全部 (limit まで) → (hits, total)"""
    hits, page = [], 1
    while True:
        url = f'{API}?' + urllib.parse.urlencode({'q': q, 'size': page_size, 'page': page, 'fields': FIELDS})
        d = fetch(url)
        batch = d['hits']['hits']
        hits += batch
        total = d['hits']['total']
        if not batch or len(hits) >= total or len(hits) >= limit:
            return hits, total
        page += 1


def recid_of(author):
    ref = (author.get('record') or {}).get('$ref', '')
    return ref.rsplit('/', 1)[-1] if ref else None


def bai_of(author):
    return next((i.get('value') for i in author.get('ids', []) if i.get('schema') == 'INSPIRE BAI'), None)


def surname_matches(full_name, surname):
    return full_name.lower().startswith(surname.lower() + ',')


def survey_table(hits, surname):
    """→ ({recid or None: {'papers', 'names', 'bai', 'affs'}}, その姓の著者がいない hit の数)"""
    rows = collections.defaultdict(lambda: {'papers': 0, 'names': collections.Counter(), 'bai': set(), 'affs': collections.Counter()})
    unmatched = 0
    for h in hits:
        authors = [a for a in h['metadata'].get('authors', []) if surname_matches(a.get('full_name', ''), surname)]
        if not authors:
            unmatched += 1
            continue
        seen = set()
        for a in authors:
            rec = recid_of(a)
            row = rows[rec]
            row['names'][a['full_name']] += 1
            if bai_of(a):
                row['bai'].add(bai_of(a))
            for x in a.get('affiliations', []):
                row['affs'][x.get('value')] += 1
            if rec not in seen:
                row['papers'] += 1
                seen.add(rec)
    return dict(rows), unmatched


def foreign_hits(hits, recids, names):
    """record に付いた著者の表記が names のどれでもない hit (= 別人の候補) → [(hit, 表記, 所属)]"""
    recids, names = {str(r) for r in recids}, set(names)
    out = []
    for h in hits:
        mine = [a for a in h['metadata'].get('authors', []) if recid_of(a) in recids]
        if mine and not any(a.get('full_name') in names for a in mine):
            a = mine[0]
            out.append((h, a.get('full_name'), [x.get('value') for x in a.get('affiliations', [])]))
    return out


def record_names(hits, recids):
    recids = {str(r) for r in recids}
    c = collections.Counter()
    for h in hits:
        for a in h['metadata'].get('authors', []):
            if recid_of(a) in recids:
                c[(recid_of(a), a.get('full_name'))] += 1
    return c


def union_query(recids):
    return ' or '.join(f'authors.recid:{r}' for r in recids)


def filtered_query(recids, names):
    return f'({union_query(recids)}) and (' + ' or '.join(f'a "{n}"' for n in names) + ')'


def ui_url(q):
    return f'{UI}?' + urllib.parse.urlencode({'sort': 'mostrecent', 'size': 25, 'page': 1, 'q': q, 'ui-citation-summary': 'true'}, quote_via=urllib.parse.quote)


def cmd_survey(name, fetch=fetch_json):
    surname = name.split(',')[0].strip()
    hits, total = fetch_all(f'a {name}', fetch)
    rows, unmatched = survey_table(hits, surname)
    print(f'名前検索 `a {name}`: {total} 件 (読んだ {len(hits)} 件)。 姓「{surname}」 の著者が付いていない hit = {unmatched} 件')
    print('record ごと (件数の多い順。 本人の行が 2 つ以上あれば割れている):')
    for rec, row in sorted(rows.items(), key=lambda kv: -kv[1]['papers']):
        names = ', '.join(f'{n} ×{k}' for n, k in row['names'].most_common())
        affs = ', '.join(f'{a} ×{k}' for a, k in row['affs'].most_common(4))
        print(f"  {rec or '(record なし)'}  {row['papers']} 件  BAI={','.join(sorted(row['bai'])) or '-'}")
        print(f'      表記: {names}')
        print(f'      所属: {affs or "-"}')
    return 0


def cmd_check(recids, names, fetch=fetch_json):
    hits, total = fetch_all(union_query(recids), fetch)
    print(f'record {" + ".join(recids)} の合算: {total} 件')
    print('record に付いた表記 (✓ = --name に含む):')
    for (rec, n), k in record_names(hits, recids).most_common():
        print(f"  {'✓' if n in names else '✗'} {rec}  {n} ×{k}")
    foreign = foreign_hits(hits, recids, names)
    print(f'別人の候補 (record の著者の表記が --name に無い): {len(foreign)} 件')
    for h, n, affs in foreign:
        m = h['metadata']
        title = (m.get('titles') or [{}])[0].get('title', '')[:70]
        print(f"  {m.get('control_number')}  {m.get('earliest_date')}  {n} {affs}  {title}")
    if not names:
        return 0
    q = filtered_query(recids, names)
    fhits, ftotal = fetch_all(q, fetch)
    left = foreign_hits(fhits, recids, names)
    print(f'\n本人の表記で絞った式: {ftotal} 件、 別人の候補の残り {len(left)} 件')
    print(f'  式: {q}')
    print(f'  画面: {ui_url(q)}')
    print('  → 画面でも件数・先頭 (最新順)・左の Author / Collaboration の絞り込み欄を見る')
    return 1 if left else 0


def _selftest():
    def au(name, rec=None, bai=None, aff=None):
        a = {'full_name': name}
        if rec:
            a['record'] = {'$ref': f'https://inspirehep.net/api/authors/{rec}'}
        if bai:
            a['ids'] = [{'schema': 'INSPIRE BAI', 'value': bai}]
        if aff:
            a['affiliations'] = [{'value': aff}]
        return a

    def hit(cn, *authors):
        return {'metadata': {'control_number': cn, 'earliest_date': '2000', 'titles': [{'title': f'T{cn}'}], 'authors': list(authors)}}

    # 架空の人物 2 人 (同姓同頭文字) と、 別の頭文字の人
    hits = [
        hit(1, au('Doe, J.A.', 111, 'J.A.Doe.1', 'Univ X')),
        hit(2, au('Doe, J.A.', 222, 'J.A.Doe.2', 'Univ Y')),
        hit(3, au('Doe, John Adam', 222, 'J.A.Doe.2', 'Lab Z'), au('Roe, R.', 333)),
        hit(4, au('Doe, Jane', 222, 'J.A.Doe.2', 'Inst W')),
        hit(5, au('Doe, J.')),
        hit(6, au('Doering, K.', 444)),
    ]
    rows, unmatched = survey_table(hits, 'Doe')
    assert unmatched == 1, unmatched
    assert rows['111']['papers'] == 1 and rows['222']['papers'] == 3 and rows[None]['papers'] == 1, rows
    assert rows['222']['names']['Doe, John Adam'] == 1 and rows['222']['bai'] == {'J.A.Doe.2'}
    names = ['Doe, J.A.', 'Doe, John Adam']
    foreign = foreign_hits(hits, ['111', '222'], names)
    assert [h['metadata']['control_number'] for h, _, _ in foreign] == [4], foreign
    assert foreign_hits(hits, [111, 222], names)[0][1] == 'Doe, Jane'
    q = filtered_query(['111', '222'], names)
    assert q == '(authors.recid:111 or authors.recid:222) and (a "Doe, J.A." or a "Doe, John Adam")', q
    url = ui_url(q)
    assert url.startswith(UI + '?sort=mostrecent') and '%28authors.recid%3A111%20or%20' in url and '%22Doe%2C%20J.A.%22' in url, url

    # cmd_check の流れ (fetch を差し替え): 合算 = 4 件、 絞った式 = 本人の 3 件
    def fake_fetch(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['q'][0]
        sel = hits[:4] if q.startswith('authors.recid') else [h for h in hits[:4] if h['metadata']['control_number'] != 4]
        return {'hits': {'hits': sel, 'total': len(sel)}}
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = cmd_check(['111', '222'], names, fake_fetch)
    assert rc == 0 and '別人の候補 (record の著者の表記が --name に無い): 1 件' in out.getvalue(), out.getvalue()
    print('selftest: ok')
    return 0


def main(argv):
    if argv[:1] == ['--selftest']:
        return _selftest()
    if len(argv) >= 2 and argv[0] == 'survey':
        return cmd_survey(' '.join(argv[1:]))
    if len(argv) >= 2 and argv[0] == 'check':
        recids, names, rest = [], [], argv[1:]
        while rest:
            x = rest.pop(0)
            if x == '--name' and rest:
                names.append(rest.pop(0))
            elif x.isdigit():
                recids.append(x)
            else:
                print(f'分からない引数: {x}', file=sys.stderr)
                return 2
        if not recids:
            print('recid を 1 つ以上', file=sys.stderr)
            return 2
        return cmd_check(recids, names)
    print(__doc__.split('\n\n')[2], file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError) as e:
        print(f'失敗: {e}', file=sys.stderr)
        sys.exit(2)
