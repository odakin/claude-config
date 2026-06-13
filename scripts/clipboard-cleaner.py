#!/usr/bin/env python3
"""クリップボード一発整形 CLI — PDF からコピーしたテキストの後始末。

PDF からコピーしたテキストをそのまま貼ると、(a) 段落内の見た目改行が
そのまま入る、(b) RTF 書式（イタリック等）が付いてくる、の 2 つが起きる。
本スクリプトは「明示的に呼ばれた時だけ」クリップボードを 1 回整形する:

  - 見た目だけの折り返し改行を除去し、**意図的な改行は保持する**:
      保持 (1) 次の行が字下げ・箇条書き・条文番号（第○条 / ２ / 一）で始まる
      保持 (2) 行がブロック最大幅より全角 2 文字以上短い
              （折り返し行は右端まで詰まっている性質を利用 = 短い行は段落末・見出し）
      除去: それ以外（右端まで詰まった行）= ただの折り返し
  - 空行（= 元から段落区切り）はそのまま保持
  - 結合時、行境界が日本語ならそのまま、英語ならスペースを挟む
  - 英語のハイフネーション（行末 "beauti-" + "ful"）を復元
  - pbcopy で書き戻すことで RTF 書式も除去される（改行が無くても効く）

常駐監視はしない（conventions/clipboard-cleaner.md、secret-handoff.md の
クリップボード単一資源原則と衝突させないため）。

使い方:
  clipboard-cleaner.py            # クリップボードを整形して上書き
  clipboard-cleaner.py --stdin    # stdin → stdout のフィルタ（テスト用）
  clipboard-cleaner.py --selftest # 内蔵テスト

整形ロジックは scripts/pdf-cleaner.html (ブラウザ版 fallback) と仕様を
揃えてある。変更時は両方を更新すること。
"""

import os
import re
import subprocess
import sys

# 日本語判定: 全角スペース・記号・かな (U+3000-30FF)、CJK 統合漢字
# (U+4E00-9FFF)、全角英数 (U+FF00-FFEF)。pdf-cleaner.html と同一範囲。
JA_RE = re.compile(r'[　-ヿ一-鿿＀-￯]')


def _pb_env():
    """pbcopy/pbpaste 用の環境変数。

    C ロケール（LANG 未設定）だと pbcopy は「日本語 + 改行」入力で
    **silent に空クリップボードを作る**（日本語のみ・ASCII のみなら通る）。
    Hammerspoon の hs.execute や launchd 配下は LANG 未設定なので、
    呼び出し元の環境に頼らず常に UTF-8 を明示する。
    """
    env = dict(os.environ)
    env.pop('LC_ALL', None)  # LC_ALL は LC_CTYPE より優先されるため除去
    env['LC_CTYPE'] = 'UTF-8'
    return env


# 「意図的な改行」判定 (1): 次の行が新しい構造の頭で始まる
# 字下げ（全角スペース / タブ / 半角スペース 2+）
INDENT_RE = re.compile(r'^(　|\t| {2,})')
# 箇条書き・条文マーカー（・● / （１）(1) / １． １、 １　/ 一、 一　/
# 第二条 ２項 等 / 丸数字）
MARKER_RE = re.compile(
    r'^(・|[●○◆◇■□▶▸]'
    r'|[（(][0-9０-９一二三四五六七八九十]+[）)]'
    r'|[0-9０-９]+[．.、)）　]'
    r'|[一二三四五六七八九十百]+[、　]'
    r'|第[0-9０-９一二三四五六七八九十百千]+[条章節項編款目]'
    r'|[①-⑳])')


def _width(s):
    """表示幅の近似（全角 = 1.0、半角 = 0.5）。"""
    import unicodedata
    return sum(1.0 if unicodedata.east_asian_width(c) in 'WF' else 0.5
               for c in s)


def _keep_break(prev_line, next_line, max_w):
    """意図的な改行 (2): 折り返し行は右端近くまで詰まっている性質を利用。

    前の行がブロック内の最大幅より全角 2 文字分以上短ければ、
    そこで意図的に行が終わっている（段落末・見出し・箇条書き項目末）。
    """
    if INDENT_RE.match(next_line) or MARKER_RE.match(next_line):
        return True
    return max_w - _width(prev_line) >= 2.0


def clean(text):
    """見た目だけの折り返し改行を除去し、意図的な改行は保持する。

    返り値: (整形後テキスト, 結合した行境界の数)
    """
    joins = 0
    paragraphs = re.split(r'\n{2,}', text)

    cleaned = []
    for para in paragraphs:
        lines = [l.rstrip() for l in para.split('\n') if l.strip()]
        if not lines:
            continue
        max_w = max(_width(l) for l in lines)
        out_lines = []
        joined = lines[0]
        for i in range(1, len(lines)):
            prev, line = lines[i - 1], lines[i]
            if re.search(r'[A-Za-z]-$', prev):
                # 英語のハイフネーション: 折り返し確定、ハイフンを除いて直結
                joined = joined[:-1] + line
                joins += 1
            elif _keep_break(prev, line, max_w):
                # 意図的な改行: そのまま残す
                out_lines.append(joined)
                joined = line
            elif JA_RE.search(joined[-1:]) or JA_RE.search(line[:1]):
                # 折り返し・行境界のどちらかが日本語: スペース無しで直結
                joined += line
                joins += 1
            else:
                # 折り返し・英語同士: スペースを挟む
                joined += ' ' + line
                joins += 1
        out_lines.append(joined)
        cleaned.append('\n'.join(out_lines))

    return '\n\n'.join(cleaned), joins


def clean_clipboard():
    env = _pb_env()
    text = subprocess.run(['pbpaste'], capture_output=True,
                          encoding='utf-8', env=env).stdout
    if not text.strip():
        print('クリップボードにテキストがありません')
        return 1
    result, joins = clean(text)
    # 改行除去が無くても書き戻す = pbcopy 経由で RTF 書式が落ちる
    subprocess.run(['pbcopy'], input=result, encoding='utf-8',
                   env=env, check=True)
    if joins:
        print(f'整形しました（改行 {joins} 箇所を結合・書式除去）')
    else:
        print('書式のみ除去（改行の変更なし）')
    return 0


def selftest():
    cases = [
        # (入力, 期待出力, 説明)
        # ※ fixture は現実の PDF コピーを模した行幅（折り返し行は
        #    ほぼ同じ幅）で書くこと。短い行 = 意図的な改行と判定される。
        ('本契約の当事者は、本契約に定める各条項を誠実に履行\n'
         'するものとし、疑義が生じた場合には両当事者が協議の\n'
         '上これを解決する。',
         '本契約の当事者は、本契約に定める各条項を誠実に履行する'
         'ものとし、疑義が生じた場合には両当事者が協議の上これを解決する。',
         '日本語: 折り返しをスペース無しで結合'),
        ('第一条　この法律は、国民の権利の保護を目的とする\n'
         'ものとし、その施行に必要な事項は政令で定めるもの\n'
         'とする。\n'
         '２　前項の政令は、関係行政機関の長に協議して定め\n'
         'るものとする。',
         '第一条　この法律は、国民の権利の保護を目的とするものとし、'
         'その施行に必要な事項は政令で定めるものとする。\n'
         '２　前項の政令は、関係行政機関の長に協議して定めるものとする。',
         '条文: 項の構造（短い行末 + 番号マーカー）を保持'),
        ('次の各号のいずれかに該当する者は、これを拒否する\n'
         'ことができる。\n'
         '一　未成年者\n'
         '二　破産者で復権を得ない者',
         '次の各号のいずれかに該当する者は、これを拒否することができる。\n'
         '一　未成年者\n'
         '二　破産者で復権を得ない者',
         '号 list: 漢数字マーカーの改行を保持'),
        ('当事者の一方が前項の規定に違反したときは、相手方\n'
         'は契約を解除することができる。\n'
         '　ただし、相手方に過失があるときは、この限りでな\n'
         'い。',
         '当事者の一方が前項の規定に違反したときは、相手方は'
         '契約を解除することができる。\n'
         '　ただし、相手方に過失があるときは、この限りでない。',
         '字下げ: 全角スペース開始行の前の改行を保持'),
        ('The committee discussed the proposal at length and con-\n'
         'cluded that further review would be necessary before the\n'
         'final decision.',
         'The committee discussed the proposal at length and concluded '
         'that further review would be necessary before the final decision.',
         '英語: スペース結合 + ハイフネーション復元'),
        ('量子力学の基礎理論は二十世紀初頭に確立されたもので\n'
         'あり、現代物理学の根幹をなしている。\n'
         '\n'
         '相対性理論もまた同時期に提唱された理論である。',
         '量子力学の基礎理論は二十世紀初頭に確立されたものであり、'
         '現代物理学の根幹をなしている。\n'
         '\n'
         '相対性理論もまた同時期に提唱された理論である。',
         '空行 = 段落区切りは保持'),
        ('実験結果は仮説と一致しており、detailed analysis に\n'
         'よりその妥当性が確認された。',
         '実験結果は仮説と一致しており、detailed analysis に'
         'よりその妥当性が確認された。',
         '混在: 行境界が日本語なら直結'),
        ('変更なしの一行', '変更なしの一行', '単一行は不変'),
    ]
    failed = 0
    for src, expect, desc in cases:
        got, _ = clean(src)
        if got != expect:
            print(f'FAIL: {desc}\n  expect: {expect!r}\n  got:    {got!r}')
            failed += 1
    total = len(cases)
    print(f'{total - failed}/{total} passed')
    return 1 if failed else 0


def main():
    if '--selftest' in sys.argv:
        return selftest()
    if '--stdin' in sys.argv:
        result, _ = clean(sys.stdin.read())
        sys.stdout.write(result)
        return 0
    return clean_clipboard()


if __name__ == '__main__':
    sys.exit(main())
