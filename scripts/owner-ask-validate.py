#!/usr/bin/env python3
"""owner-ask-validate.py — 本人への問いを立てる前の関門: その変更に本人の裁定が要るかを、 書く時の守りの道具と同じ述語で判定する

用途: 掲示板の問いの台帳 (ai-collaboration/board/board_asks.py) が、 変更の在りか (`--evidence`) つきの問いを立てる前に
呼ぶ判定の道具 (board_asks.py の `BOARD_ASKS_VALIDATOR`、 既定の場所 = この file)。 裁定の要らない変更を本人に問うと、
本人の時間を使って「わざわざ聞くことか」 と返される (実測: 緩める語の無い言い直しの追認を問い、 そう返された)。

判定: manuscript-claim-guard.py の protected_changes(path, 前, 後, repo, cfg, authority=True, session, refusal_live) =
  編集の hook と同じ述語 (規則の文書の緩和・既存の文の書き換え・正本の参照の行・権限の lock = 守りの道具の配線と設定・
  原稿の保護された箇所・その会話で断った件の網)。 列挙が空 = 裁定が要らない (問わずに当てて、 返事に何を変えたかを書く)、
  空でない = 要る (どの箇所かを添える)。 判定の記録の副作用 (承認なしで通った追記の記録) は書かない。
  --session <id> = 問いを立てる session (断った件の網の会話記録と止めた印を引く)。 無ければ網は確かめていないと添える。
  --applied = もう入っている変更の追認。 裁定の要らない形 → 問わない。 要る形 → 問いは立てるが、 裁定なしに当てた事故として
  同じ返事で記録し、 戻すかも問うと添える。
変更の在りか (--evidence): `<repo の dir>@<commit>:<path>` (前 = commit~1、 後 = commit) か `<repo の dir>@worktree:<path>`
  (前 = HEAD、 後 = 作業ツリーの file) か `<repo の dir>@candidate=<候補の全文の絶対 path>:<path>` (前 = HEAD、 後 = 当てる前の
  候補 = 守りの道具に止められて当てられない worker が、 問いの根拠に候補の写しを指す形。 2026-11-09 実測: 在りかが作業ツリーの
  差分しか読めず、 承認の問いが台帳を通らずに普通の文で出た)。 前と後が同じ (その commit がその file を変えていない) は誤り。

出力: stdout に JSON 1 行。 {"ok": true|false, "message": "…"} (ok = 問いを立ててよい) で exit 0。 在りかが読めない・変更が
  無い = {"error": "…"} で exit 1 (問いは立たない)。 守りの道具の中の失敗 = {"ok": true, "message": "⚠️ …"} で exit 0
  (判定できなかったので問いは立て、 確かめていないと添える)。

使い方:
  python3 owner-ask-validate.py --evidence ~/work/repo@HEAD:CLAUDE.md [--session <id>] [--applied]
  python3 owner-ask-validate.py --selftest
`--ground rule|protected` は受け取るが判定は変えない (同じ述語で両方を見る)。
OS: macOS / Linux / Windows (Git Bash) で同じ (標準 library、 Python 3.8+、 git が要る)。
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Unreadable(Exception):
    """在りかの中身を平文で読めない (git-crypt の lock 中・UTF-8 でない) = 判定できない。 問いは立て、 確かめていないと添える。"""


def _plain(data, what):
    if data.startswith(b'\x00GITCRYPT'):
        raise Unreadable(f'{what} は git-crypt の暗号文のまま (その repo の lock を外すと読める)')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        raise Unreadable(f'{what} を UTF-8 として読めない')


def _git_text(repo, rev, rel):
    """rev:rel の中身 (その rev に file が無ければ '')。 smudge filter を通して読む (`git cat-file --filters`) = git-crypt で
    暗号化される path も平文になる (2026-11-09 実測: `git show` を text で読み、 暗号化した blob の bytes で
    「'utf-8' codec can't decode byte」 と止まった。 同じ読み方の前例 = lib/git_blob.py)。 filter が失敗すれば `git show` に戻す。"""
    spec = f'{rev}:{rel}'
    p = subprocess.run(['git', '-C', str(repo), 'cat-file', '--filters', spec], capture_output=True, timeout=30)
    if p.returncode != 0:
        p = subprocess.run(['git', '-C', str(repo), 'show', spec], capture_output=True, timeout=30)
        if p.returncode != 0:
            # 無いのか読めないのかを分ける (読めないのを無いと読むと、 在る file を新しい file として判定する = 盲検の指摘)
            t = subprocess.run(['git', '-C', str(repo), 'ls-tree', rev, '--', rel], capture_output=True, text=True,
                               timeout=30)
            if t.returncode != 0 or t.stdout.strip():
                raise Unreadable(f'{rel} ({rev}) を git で読めない')
            return ''
    return _plain(p.stdout, f'{rel} ({rev})')


def read_change(evidence):
    m = re.fullmatch(r'(.+?)@([^:@]+):(.+)', evidence or '')
    if not m:
        raise ValueError(f'変更の在りかの形が違う (<repo>@<commit>:<path> か <repo>@worktree:<path>): {evidence!r}')
    repo, rev, rel = Path(os.path.expanduser(m.group(1))).resolve(), m.group(2), m.group(3)
    if rev.startswith('candidate='):
        cand = Path(os.path.expanduser(rev[len('candidate='):]))
        if not cand.is_absolute() or not cand.is_file():
            raise ValueError(f'候補の写しは絶対 path の file で指す (candidate=<絶対 path>): {rev!r}')
        old = _git_text(repo, 'HEAD', rel)
        try:
            new = _plain(cand.read_bytes(), f'候補の写し {cand}')
        except OSError:
            raise ValueError(f'候補の写し {cand} を読めない')
    elif rev == 'worktree':
        old = _git_text(repo, 'HEAD', rel)
        try:
            new = _plain((repo / rel).read_bytes(), f'{rel} (作業ツリー)')
        except OSError:
            new = ''
    else:
        old, new = _git_text(repo, f'{rev}~1', rel), _git_text(repo, rev, rel)
    if not old and not new:
        raise ValueError(f'{repo} の {rev}:{rel} を読めない')
    if old == new:
        raise ValueError(f'{repo} の {rev} は {rel} を変えていない (在りかの commit か path が違う)')
    return repo, rel, old, new


def judge(evidence, applied=False, session=None, guard=None):
    repo, rel, old, new = read_change(evidence)
    g = guard or _load('manuscript_claim_guard', HERE / 'manuscript-claim-guard.py')
    g.note_exemption = lambda *a, **k: None   # 判定だけ: 承認なしで通った追記の記録は、 実際に当てた時の hook が書く
    sess = ('claude', session) if session else None
    changes = g.protected_changes(rel, old, new, repo, g.load_config(repo), authority=True, session=sess,
                                  refusal_live=bool(session))
    what = '追認' if applied else '変更'
    # 判定した候補を名指す (候補の写しは後で変えられる = 問いの台帳に、 どの中身を判定したかを残す。 盲検の指摘)。
    # 裁定の要る・要らないのどちらの答えにも添える
    import hashlib
    # hash は守りの道具が当てる時と同じ読み方 (改行を揃えた text) で取る
    norm = new.replace('\r\n', '\n').replace('\r', '\n')
    rcpt = (f' [判定した候補 sha256 = {hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]}、 前 = HEAD]'
            if '@candidate=' in (evidence or '') else '')
    net = '' if session else ' (この会話で断った件の網は、 session が渡されていないので確かめていない)'
    if not changes:
        return {'ok': False, 'message': (f'{rel} の{what}は本人の裁定の要らない形 = 問わずに当てて、 返事に何を変えたかを書く'
                                         + net + rcpt)}
    regions = sorted({c.get('region', '?') for c in changes})
    reason = next((c.get('detail') for c in changes if c.get('detail')), '')
    msg = '裁定が要る: ' + ', '.join(regions) + (f' ({reason[:160]})' if reason else '') + rcpt
    if applied:
        msg = ('⚠️ 裁定の要る変更がもう入っている = 裁定なしに当てた事故。 問いと同じ返事で、 当てた commit を事故として記録し、'
               ' 戻すかも問う。 ' + msg)
    return {'ok': True, 'message': msg}


def selftest():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL', msg)
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@example.invalid')

    def git(repo, *args):
        subprocess.run(['git', '-C', str(repo), *args], check=True, env=env, capture_output=True)
    with tempfile.TemporaryDirectory() as td:
        os.environ.setdefault('MANUSCRIPT_CLAIM_GUARD_STATE_DIR', str(Path(td) / 'state'))
        repo = Path(td) / 'repo'
        repo.mkdir()
        git(repo, 'init', '-q')
        (repo / 'CLAUDE.md').write_text('# 規則\n\n- 送る前に確かめる。\n', encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'a', '--no-verify')
        (repo / 'CLAUDE.md').write_text('# 規則\n\n- 送る前に確かめる。\n- 宛先も読み上げる。\n', encoding='utf-8')
        git(repo, 'commit', '-qam', 'b', '--no-verify')
        r = judge(f'{repo}@HEAD:CLAUDE.md', applied=True)
        check(r['ok'] is False and '要らない' in r['message'], f'緩める語の無い追記の追認は問わない {r}')
        (repo / 'CLAUDE.md').write_text('# 規則\n\n- 送る前に確かめる。\n- 宛先も読み上げる。\n- ただし急ぎなら確かめなくてよい。\n',
                                        encoding='utf-8')
        r = judge(f'{repo}@worktree:CLAUDE.md')
        check(r['ok'] is True and '裁定が要る' in r['message'], f'緩める語を足す変更は問う {r}')
        cand = Path(td) / 'cand.md'
        cand.write_text((repo / 'CLAUDE.md').read_text(encoding='utf-8'), encoding='utf-8')
        git(repo, 'checkout', '-q', '--', 'CLAUDE.md')
        r = judge(f'{repo}@candidate={cand}:CLAUDE.md')
        check(r['ok'] is True and '裁定が要る' in r['message'] and '判定した候補 sha256' in r['message'],
              f'当てる前の候補の写しを指す在りかも同じ述語で問い、 判定した候補の hash を添える {r}')
        for bad in (f'{repo}@candidate=cand.md:CLAUDE.md', f'{repo}@candidate={Path(td) / "none.md"}:CLAUDE.md'):
            try:
                read_change(bad)
                check(False, f'相対 path・無い file の候補の写しは断る {bad}')
            except ValueError:
                pass
        (repo / 'CLAUDE.md').write_text(cand.read_text(encoding='utf-8'), encoding='utf-8')
        git(repo, 'commit', '-qam', 'c', '--no-verify')
        r = judge(f'{repo}@HEAD:CLAUDE.md', applied=True)
        check(r['ok'] is True and '事故' in r['message'], f'裁定の要る変更の追認は問い、 事故として記録するよう言う {r}')
        (repo / 'tool.py').write_text('print(1)\n', encoding='utf-8')
        git(repo, 'add', 'tool.py')
        git(repo, 'commit', '-qm', 'd', '--no-verify')
        (repo / 'tool.py').write_text('print(2)\n', encoding='utf-8')
        r = judge(f'{repo}@worktree:tool.py')
        check(r['ok'] is False, f'守りの網の外の code の変更は問わない (書く時の hook も止めない) {r}')
        tex = ('\\documentclass{article}\n\\title{A title}\n\\begin{document}\n\\maketitle\n'
               '\\begin{abstract}\nWe show X.\n\\end{abstract}\n\\section{Introduction}\nIntro text.\n'
               '\\section{Body}\nBody text.\n\\end{document}\n')
        (repo / 'paper.tex').write_text(tex, encoding='utf-8')
        git(repo, 'add', 'paper.tex')
        git(repo, 'commit', '-qm', 'e', '--no-verify')
        (repo / 'paper.tex').write_text(tex.replace('Body text.', 'Body text, rephrased.'), encoding='utf-8')
        r = judge(f'{repo}@worktree:paper.tex')
        check(r['ok'] is False, f'本文の言い直しは保護された箇所の外 {r}')
        (repo / 'paper.tex').write_text(tex.replace('We show X.', 'We show Y.'), encoding='utf-8')
        r = judge(f'{repo}@worktree:paper.tex')
        check(r['ok'] is True, f'要旨の変更は問う {r}')
        for bad, why in (('bad', '形の違う在りか'), (f'{repo}@HEAD:tool.py', '変更の無い commit')):
            try:
                read_change(bad)
                check(False, f'{why}を断る')
            except ValueError:
                pass
        p = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--evidence', f'{repo}@HEAD:tool.py'],
                           capture_output=True, text=True)
        check(p.returncode == 1 and 'error' in json.loads(p.stdout.strip().splitlines()[-1]), f'在りかの誤りは error {p.stdout}')

        # git-crypt の repo の在りか (2026-11-09 実測 = 暗号化した blob を text で読んで止まった)。 直した読み方で判定でき、
        # 直す前の読み方 (git show を text で) では同じ在りかで止まる (foil)。 lock 中は止まらず確かめていないと添える
        import shutil
        if shutil.which('git-crypt'):
            cr = Path(td) / 'crypt'
            cr.mkdir()
            git(cr, 'init', '-q')
            subprocess.run(['git-crypt', 'init'], cwd=cr, check=True, capture_output=True, env=env)
            (cr / '.gitattributes').write_text('*.md filter=git-crypt diff=git-crypt\n', encoding='utf-8')
            (cr / 'CLAUDE.md').write_text('# 規則\n\n- 送る前に確かめる。\n', encoding='utf-8')
            git(cr, 'add', '-A')
            git(cr, 'commit', '-qm', 'a', '--no-verify')
            enc = subprocess.run(['git', '-C', str(cr), 'show', 'HEAD:CLAUDE.md'], capture_output=True).stdout
            check(enc.startswith(b'\x00GITCRYPT'), 'fixture: HEAD の blob は暗号文')
            (cr / 'CLAUDE.md').write_text('# 規則\n\n- 送る前に確かめる。\n- ただし急ぎなら確かめなくてよい。\n', encoding='utf-8')
            r = run(f'{cr}@worktree:CLAUDE.md')
            check(r.get('ok') is True and '裁定が要る' in r.get('message', ''),
                  f'git-crypt の repo の在りかも復号して判定する {r}')
            orig = globals()['_git_text']
            globals()['_git_text'] = lambda repo, rev, rel: subprocess.run(
                ['git', '-C', str(repo), 'show', f'{rev}:{rel}'], capture_output=True, text=True).stdout
            try:
                rf = run(f'{cr}@worktree:CLAUDE.md')
            finally:
                globals()['_git_text'] = orig
            check("codec can't decode" in rf.get('error', ''),
                  f'foil: 直す前の読み方では同じ在りかが報告と同じ error で止まる {rf}')
            git(cr, 'checkout', '-q', '--', 'CLAUDE.md')
            subprocess.run(['git-crypt', 'lock'], cwd=cr, check=True, capture_output=True, env=env)
            r = run(f'{cr}@worktree:CLAUDE.md')
            check(r.get('ok') is True and r['message'].startswith('⚠️') and '確かめていない' in r['message'],
                  f'lock 中の在りかは止まらず、 確かめていないと添える {r}')
        else:
            print('skip: git-crypt が無い = 暗号化の在りかの試験を回していない')

        class Broken:
            def note_exemption(self, *a):
                pass

            def load_config(self, repo):
                raise RuntimeError('broken')
        out = run(f'{repo}@worktree:paper.tex', guard=Broken())
        check(out.get('ok') is True and out['message'].startswith('⚠️'), f'守りの道具の中の失敗は、 立てて確かめていないと言う {out}')
    print('selftest:', 'OK' if ok else 'FAIL')
    return 0 if ok else 1


def run(evidence, applied=False, session=None, guard=None):
    """judge + 失敗の扱い: 在りかの誤り (ValueError) は {"error"}、 守りの道具の中の失敗は立てて確かめていないと言う。"""
    try:
        return judge(evidence, applied, session, guard)
    except ValueError as e:
        return {'error': str(e)}
    except Unreadable as e:
        return {'ok': True, 'message': f'⚠️ 変更の在りかを平文で読めない ({e}) = 裁定の要否を確かめていない (問いは立てた)'}
    except Exception as e:   # noqa: BLE001 (判定できない = 問いは立て、 その旨を添える)
        return {'ok': True, 'message': f'⚠️ 判定の道具の中で失敗 ({e.__class__.__name__}: {str(e)[:120]}) = 裁定の要否を確かめずに立てた'}


def main(argv=None):
    ap = argparse.ArgumentParser(description='本人への問いを立てる前の関門 (規則・原稿の変更に裁定が要るか)')
    ap.add_argument('--ground', choices=['rule', 'protected'], help='受け取るが判定は変えない')
    ap.add_argument('--evidence')
    ap.add_argument('--session')
    ap.add_argument('--applied', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.evidence:
        ap.error('--evidence が要る')
    out = run(a.evidence, a.applied, a.session)
    print(json.dumps(out, ensure_ascii=False))
    return 1 if 'error' in out else 0


if __name__ == '__main__':
    sys.exit(main())
