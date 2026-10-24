#!/usr/bin/env python3
"""Report .tex root documents that LuaLaTeX cannot typeset (pTeX classes, DVI-driver options, pTeX-only packages, a TeXShop program line naming pLaTeX); --staged for pre-commit, --fleet to inventory, --selftest.

Why (measured): an owner who typesets everything with LuaLaTeX (TeXShop's default path set to lualatex) opened an
agent-written `\\documentclass[11pt,dvipdfmx]{jsarticle}` file and pressed typeset.  lualatex stopped at the class and
waited for console input: the log was 0 bytes, `<name>.synctex(busy)` stayed, the process stayed, and the owner saw
no PDF.  The agent had built the file with platex + dvipdfmx on the command line, where it compiled cleanly, so
nothing in the agent's own build said anything.  The engine a source needs is written in the source (class, class
options, packages, the TeXShop program line), so the gate reads the source.

What is reported (a root document = a file with a non-comment `\\documentclass`):
  - a pTeX / upTeX class: jsarticle / jsbook / jsreport, jarticle / jbook / jreport, tarticle / tbook / treport,
    ujarticle / ujbook / ujreport, utarticle / utbook / utreport (use ltjsarticle / ltjsbook / ltjsreport)
  - a class option naming a DVI driver or the pTeX engine: dvipdfmx / dvips / dviout / platex / uplatex
  - a pTeX-only package: otf, pxjahyper, okumacro, plext, pxcjkcat (LuaTeX-ja: luatexja-otf, nothing, luatexja-ruby)
  - a package loaded with a DVI driver option: \\usepackage[dvipdfmx]{graphicx} and the like
  - a TeXShop program line naming a pTeX route: `% !TEX TS-program = platex / uplatex / ptex2pdf / ...`
Not reported: files without `\\documentclass` (they are \\input into a root), files that name who decides their engine
(`% tex-engine-decided-by: <who>`), and files matched by the repo's `.claude/tex-engine-decided-by.txt` (one glob per
line, `# who` after it, for files that should not be edited at all). Both are for documents whose engine is not
the owner's to choose: a template issued by someone else, a snapshot kept as a diff baseline, a document whose
engine a co-author or a student decides.
How to move a document: claude-config conventions/latex.md#lualatex-compat (class → ltjs*, drop the options and
packages above, add `% !TEX TS-program = lualatex`).

Usage
  check-tex-engine.py FILE.tex [FILE.tex ...]   exit 1 if any root document is reported
  check-tex-engine.py --staged [--repo DIR]     staged .tex: an added file that is reported blocks (exit 1);
                                                a modified file that is reported only warns (exit 0); 3 = could not run
  check-tex-engine.py --fleet ROOT              every git repo directly under ROOT: tracked .tex that are reported;
                                                exit 1 if any (files decided by others are counted, not reported)
  check-tex-engine.py --selftest
"""
from __future__ import annotations

import contextlib
import fnmatch
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DOCCLASS = re.compile(r'^[ \t]*\\documentclass\s*(?:\[(?P<opts>[^\]]*)\])?\s*\{(?P<cls>[^}]+)\}', re.M)
PTEX_CLASSES = re.compile(r'^(?:js|j|t|uj|ut)(?:article|book|report)$')
DRIVER_OPT = re.compile(r'^(?:dvipdfmx|dvips|dviout|platex|uplatex)$')
PTEX_PACKAGES = {'otf', 'pxjahyper', 'okumacro', 'plext', 'pxcjkcat'}
USEPACKAGE = re.compile(r'^[^%\n]*\\(?:usepackage|RequirePackage)\s*(?:\[(?P<opts>[^\]]*)\])?\s*\{(?P<pkgs>[^}]+)\}', re.M)
TS_PROGRAM = re.compile(r'^\s*%\s*!TEX\s+(?:TS-)?program\s*=\s*(?P<prog>\S+)', re.M | re.I)
PTEX_PROGRAM = re.compile(r'(?i)(?:^|[-_])u?platex|ptex2pdf')
DECIDED_BY = re.compile(r'^[ \t]*%[ \t]*tex-engine-decided-by[ \t]*:[ \t]*\S', re.M)
DECIDED_BY_LIST = Path('.claude/tex-engine-decided-by.txt')


def others_globs(repo: Path) -> list[str]:
    try:
        lines = (repo / DECIDED_BY_LIST).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    return [ln.split('#', 1)[0].strip() for ln in lines if ln.split('#', 1)[0].strip()]


def listed(rel: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, g) for g in globs)


def _split(opts: str | None) -> list[str]:
    return [o.strip() for o in (opts or '').split(',') if o.strip()]


def scan_text(text: str) -> dict:
    """{'root': bool, 'others': bool, 'reasons': [str]} for one file's text."""
    root = None
    for m in DOCCLASS.finditer(text):
        root = m
        break
    if root is None:
        return {'root': False, 'others': False, 'reasons': []}
    reasons = []
    cls = root.group('cls').strip()
    if PTEX_CLASSES.match(cls):
        reasons.append(f'class {cls} (pTeX)')
    for o in _split(root.group('opts')):
        if DRIVER_OPT.match(o):
            reasons.append(f'class option {o}')
    for m in USEPACKAGE.finditer(text):
        for p in _split(m.group('pkgs')):
            if p in PTEX_PACKAGES:
                reasons.append(f'package {p}')
        for o in _split(m.group('opts')):
            if o in ('dvipdfmx', 'dvips', 'dviout'):
                reasons.append(f'package option {o} ({m.group("pkgs").strip()})')
    for m in TS_PROGRAM.finditer(text):
        if PTEX_PROGRAM.search(m.group('prog')):
            reasons.append(f'TeXShop program {m.group("prog")}')
    return {'root': True, 'others': bool(DECIDED_BY.search(text)), 'reasons': reasons}


def reported(text: str) -> list[str]:
    r = scan_text(text)
    return r['reasons'] if r['root'] and not r['others'] else []


def _git(repo: Path, *args: str, binary: bool = False):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=not binary)


def staged(repo: Path) -> int:
    p = _git(repo, 'diff', '--cached', '--name-status', '--diff-filter=ACMR')
    if p.returncode != 0:
        print(f"⚠️ check-tex-engine --staged: could not read the staged files ({p.stderr.strip()}); not checked", file=sys.stderr)
        return 3
    blocked, warned = [], []
    globs = others_globs(repo)
    for line in p.stdout.splitlines():
        parts = line.split('\t')
        status, path = parts[0], parts[-1]
        if not path.endswith('.tex') or listed(path, globs):
            continue
        # cat-file --filters applies the smudge filter (a git-crypt index holds the encrypted blob)
        c = _git(repo, 'cat-file', '--filters', f':{path}', binary=True)
        if c.returncode != 0:
            continue
        why = reported(c.stdout.decode('utf-8', errors='replace'))
        if why:
            (blocked if status[0] in 'AC' else warned).append(f"{path}: {'; '.join(why)}")
    hint = ("move it with claude-config conventions/latex.md#lualatex-compat (class → ltjsarticle / ltjsbook, drop the "
            "DVI options and pTeX packages, add `% !TEX TS-program = lualatex`), or mark a document whose engine "
            "someone else decides with `% tex-engine-decided-by: <who>` (or list it in .claude/tex-engine-decided-by.txt)")
    if warned:
        print("⚠️ LuaLaTeX cannot typeset these edited documents (commit is not blocked): " + hint, file=sys.stderr)
        for w in warned:
            print(f"    {w}", file=sys.stderr)
    if blocked:
        print("pre-commit: a new .tex that LuaLaTeX cannot typeset; commit stopped. " + hint, file=sys.stderr)
        for b in blocked:
            print(f"    {b}", file=sys.stderr)
        return 1
    return 0


def fleet(root: Path) -> int:
    total = 0
    for repo in sorted(p for p in root.iterdir() if (p / '.git').exists()):
        ls = _git(repo, 'ls-files', '-z', '--', '*.tex')
        if ls.returncode != 0:
            continue
        rows, others = [], 0
        globs = others_globs(repo)
        for rel in ls.stdout.split('\0'):
            if not rel:
                continue
            try:
                text = (repo / rel).read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            if text.startswith('\x00GITCRYPT'):
                continue
            r = scan_text(text)
            if r['root'] and r['reasons']:
                if r['others'] or listed(rel, globs):
                    others += 1
                else:
                    rows.append(f"    {rel}: {'; '.join(r['reasons'])}")
        if rows or others:
            print(f"{repo.name}: {len(rows)} reported" + (f", {others} decided by others" if others else ''))
            print('\n'.join(rows)) if rows else None
            total += len(rows)
    print(f"total reported: {total}")
    return 1 if total else 0


def _selftest() -> int:
    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, msg
        n += 1
    ok(reported('\\documentclass[11pt,dvipdfmx]{jsarticle}\n') == ['class jsarticle (pTeX)', 'class option dvipdfmx'], 'pTeX class + driver')
    ok(reported('\\documentclass[11pt,a4paper]{ltjsarticle}\n') == [], 'ltjs is fine')
    ok(reported('\\documentclass[11pt,a4paper]{article}\n\\usepackage{amsmath}\n') == [], 'plain article is fine')
    ok(reported('\\documentclass{article}\n\\usepackage[dvipdfmx]{graphicx}\n') == ['package option dvipdfmx (graphicx)'], 'driver on graphicx')
    ok(reported('\\documentclass{ltjsarticle}\n\\usepackage{otf,amsmath}\n') == ['package otf'], 'otf')
    ok(reported('% !TEX TS-program = uplatex\n\\documentclass[uplatex]{jsbook}\n')
       == ['class jsbook (pTeX)', 'class option uplatex', 'TeXShop program uplatex'], 'uplatex route')
    ok(reported('% !TEX TS-program = latexmk-lualatex\n\\documentclass{ltjsbook}\n') == [], 'lualatex engine names are fine')
    ok(reported('% \\documentclass{jsarticle}\n\\documentclass{ltjsarticle}\n') == [], 'commented-out class is skipped')
    ok(reported('\\section{x}\n\\usepackage{otf}\n') == [], 'no \\documentclass = not a root')
    ok(reported('% tex-engine-decided-by: the issuer of the form\n\\documentclass[dvipdfmx]{jarticle}\n') == [], 'decided by others')
    ok(reported('% tex-engine-decided-by:\n\\documentclass{jarticle}\n') == ['class jarticle (pTeX)'], 'the line must name who')
    ok(reported('\\documentclass[12pt]{ujarticle}\n% \\usepackage{otf}\n') == ['class ujarticle (pTeX)'], 'commented package skipped')
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')
        (repo / 'old.tex').write_text('\\documentclass{article}\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(repo), 'add', 'old.tex'], check=True)
        subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'x'], check=True, env=env)
        (repo / 'old.tex').write_text('\\documentclass[dvipdfmx]{jsarticle}\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(repo), 'add', 'old.tex'], check=True)
        quiet_err = lambda: contextlib.redirect_stderr(io.StringIO())  # noqa: E731
        with quiet_err():
            ok(staged(repo) == 0, 'a modified file only warns')
        (repo / 'new.tex').write_text('\\documentclass[dvipdfmx]{jsarticle}\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(repo), 'add', 'new.tex'], check=True)
        with quiet_err():
            ok(staged(repo) == 1, 'an added file blocks')
        (repo / '.claude').mkdir()
        (repo / '.claude/tex-engine-decided-by.txt').write_text('# issued templates\nnew.tex  # the issuer\n', encoding='utf-8')
        with quiet_err():
            ok(staged(repo) == 0, 'a listed added file passes')
        (repo / '.claude/tex-engine-decided-by.txt').unlink()
        (repo / 'new.tex').write_text('% tex-engine-decided-by: test\n\\documentclass[dvipdfmx]{jsarticle}\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(repo), 'add', 'new.tex'], check=True)
        with quiet_err():
            ok(staged(repo) == 0, 'an added file whose engine others decide passes')
            ok(staged(repo / 'nope') == 3, 'not a repo = could not run')
        with contextlib.redirect_stdout(io.StringIO()):
            ok(main(['x', str(repo / 'old.tex')]) == 1 and main(['x', str(repo / 'new.tex')]) == 0, 'file mode')
    print(f'selftest OK ({n} checks)')
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args == ['--selftest']:
        return _selftest()
    if args[:1] == ['--staged']:
        repo = Path(args[args.index('--repo') + 1]) if '--repo' in args else Path.cwd()
        return staged(repo)
    if args[:1] == ['--fleet'] and len(args) == 2:
        return fleet(Path(args[1]).expanduser())
    files = [a for a in args if not a.startswith('--')]
    if not files or len(files) != len(args):
        print(__doc__)
        return 2
    findings = []
    for f in files:
        why = reported(Path(f).expanduser().read_text(encoding='utf-8', errors='replace'))
        if why:
            findings.append(f"{f}: {'; '.join(why)}")
    for line in findings:
        print(line)
    if not findings:
        print(f"LuaLaTeX can typeset the root documents among {len(files)} file(s) (by the source markers)")
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
