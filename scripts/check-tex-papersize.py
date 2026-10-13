#!/usr/bin/env python3
"""Warn when a .tex \\documentclass names no paper size (standard classes default to letterpaper); --staged-warn for pre-commit, --pdf to measure a built PDF, --selftest.

Why (measured): two documents of one project were typeset on Letter for weeks because `\\documentclass[11pt]{article}`
carries no paper option and the standard classes default to letterpaper.  Nothing in the build reports it: no error,
no warning, the page count is plausible, the margins look fine on screen.  It surfaced only when the print preflight
compared the PDF with the printer's A4 tray.  The paper size belongs in the source, where every machine that builds
the file gets the same page, so the gate reads the source: a `\\documentclass[...]{...}` whose options name no paper
(a4paper / a5paper / b5paper / letterpaper / legalpaper / executivepaper, or a `paper=` key), and no geometry call
that names one (`\\usepackage[a4paper,...]{geometry}` / `\\geometry{a4paper,...}`; margins alone do not set the paper),
is reported.  jsclasses
and ltjs* default to A4 and are not reported.  The `--pdf` mode measures the MediaBox of a built file (A4 / Letter /
other) for the cases where the class option does not reach the PDF (dvipdfmx without a papersize special =
claude-config conventions/latex.md#dvipdfmx-papersize).

Usage
  check-tex-papersize.py FILE.tex [FILE.tex ...]     exit 1 if any file lacks a paper option
  check-tex-papersize.py --staged-warn [--repo DIR]  staged .tex files: warn only, exit 0 (3 = could not run)
  check-tex-papersize.py --pdf FILE.pdf              print the paper size of page 1 (exit 0 always)
  check-tex-papersize.py --selftest
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

DOCCLASS = re.compile(r'^\s*\\documentclass\s*(?:\[(?P<opts>[^\]]*)\])?\s*\{(?P<cls>[^}]+)\}', re.M)
PAPER_OPT = re.compile(r'(?i)\b(?:a[0-6]|b[0-6]|letter|legal|executive)paper\b|\bpaper\s*=|\bpapersize\b')
# geometry also sets the paper when given a size: \usepackage[a4paper,...]{geometry} / \geometry{a4paper,...}
GEOMETRY_PAPER = re.compile(r'^[^%\n]*\\(?:usepackage\s*\[(?P<uo>[^\]]*)\]\s*\{geometry\}|geometry\s*\{(?P<go>[^}]*)\})', re.M)
A4_DEFAULT_CLASSES = re.compile(r'^(?:lt)?js(?:article|book|report)$|^ltj[st]?(?:article|book|report)$|^(?:u)?jsarticle$')
# ISO/ANSI sizes in points (72 pt = 1 in), with a tolerance of 3 pt
PAPER_SIZES = {'A4': (595.28, 841.89), 'Letter': (612.0, 792.0), 'A5': (419.53, 595.28), 'B5': (498.9, 708.66), 'Legal': (612.0, 1008.0)}


def geometry_paper(text: str) -> str | None:
    for m in GEOMETRY_PAPER.finditer(text):
        opts = m.group('uo') if m.group('uo') is not None else m.group('go')
        pm = PAPER_OPT.search(opts or '')
        if pm:
            return 'geometry:' + pm.group(0)
    return None


def scan_text(text: str) -> list[dict]:
    """One record per \\documentclass found: {'line', 'cls', 'opts', 'paper': str|None, 'reported': bool}."""
    out = []
    geo = geometry_paper(text)
    for m in DOCCLASS.finditer(text):
        # ignore commented-out lines
        line_start = text.rfind('\n', 0, m.start()) + 1
        if text[line_start:m.start()].lstrip().startswith('%'):
            continue
        opts = m.group('opts') or ''
        cls = m.group('cls').strip()
        pm = PAPER_OPT.search(opts)
        paper = pm.group(0) if pm else geo
        reported = paper is None and not A4_DEFAULT_CLASSES.match(cls)
        out.append({'line': text.count('\n', 0, m.start()) + 1, 'cls': cls, 'opts': opts, 'paper': paper, 'reported': reported})
    return out


def report_file(path: Path, text: str | None = None) -> list[str]:
    if text is None:
        text = path.read_text(encoding='utf-8', errors='replace')
    lines = []
    for r in scan_text(text):
        if r['reported']:
            lines.append(f"{path}:{r['line']}: \\documentclass[{r['opts']}]{{{r['cls']}}} names no paper size "
                         f"(standard classes default to letterpaper) → add a4paper (or the size you print on)")
    return lines


def staged_tex(repo: Path) -> list[Path]:
    p = subprocess.run(['git', '-C', str(repo), 'diff', '--cached', '--name-only', '--diff-filter=AM'],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip())
    return [repo / f for f in p.stdout.split('\n') if f.endswith('.tex')]


def staged_warn(repo: Path) -> int:
    try:
        files = staged_tex(repo)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ check-tex-papersize --staged-warn: could not read the staged files ({e}); not checked", file=sys.stderr)
        return 3
    findings = []
    for f in files:
        # cat-file --filters applies the smudge filter: in a git-crypt repo the index holds the encrypted blob, which
        # `git show :path` prints as raw bytes (and text=True then dies on the first non-UTF-8 byte)
        p = subprocess.run(['git', '-C', str(repo), 'cat-file', '--filters', f':{f.relative_to(repo)}'], capture_output=True)
        if p.returncode != 0:
            continue
        findings += report_file(f.relative_to(repo), p.stdout.decode('utf-8', errors='replace'))
    if findings:
        print("⚠️ paper size not declared in \\documentclass (commit is not blocked): the standard classes typeset on Letter "
              "when no paper option is given; the print preflight then rejects the PDF against an A4 tray. Add a4paper "
              "(claude-config conventions/latex.md#declare-paper-size).", file=sys.stderr)
        for line in findings:
            print(f"    {line}", file=sys.stderr)
    return 0


def pdf_size(path: Path) -> str:
    try:
        import fitz  # type: ignore
    except ImportError:
        return 'unknown (PyMuPDF not installed)'
    r = fitz.open(str(path))[0].rect
    w, h = r.width, r.height
    for name, (pw, ph) in PAPER_SIZES.items():
        if abs(w - pw) <= 3 and abs(h - ph) <= 3:
            return f"{name} ({w:.0f} x {h:.0f} pt)"
        if abs(w - ph) <= 3 and abs(h - pw) <= 3:
            return f"{name} landscape ({w:.0f} x {h:.0f} pt)"
    return f"other ({w:.1f} x {h:.1f} pt = {w*25.4/72:.0f} x {h*25.4/72:.0f} mm)"


def _selftest() -> int:
    plain = '\\documentclass[11pt]{article}\n\\usepackage{a4wide}\n'
    r = scan_text(plain)
    assert len(r) == 1 and r[0]['reported'] and r[0]['paper'] is None, r
    assert report_file(Path('n.tex'), plain) and 'letterpaper' in report_file(Path('n.tex'), plain)[0]
    ok = '\\documentclass[11pt,a4paper]{article}\n'
    assert scan_text(ok)[0]['paper'] == 'a4paper' and not scan_text(ok)[0]['reported']
    assert not scan_text('\\documentclass[letterpaper]{report}')[0]['reported'], 'an explicit Letter is a choice, not an omission'
    assert not scan_text('\\documentclass[paper=a4]{scrartcl}')[0]['reported']
    assert not scan_text('\\documentclass[10pt]{ltjsarticle}')[0]['reported'], 'ltjs classes default to A4'
    assert not scan_text('\\documentclass[uplatex,papersize]{jsarticle}')[0]['reported']
    assert scan_text('% \\documentclass[11pt]{article}\n\\documentclass[a4paper]{article}\n') == \
        [dict(line=2, cls='article', opts='a4paper', paper='a4paper', reported=False)]
    assert scan_text('\\documentclass{revtex4-2}')[0]['reported'], 'no options at all = default paper'
    geo = '\\documentclass[12pt]{article}\n\\usepackage[a4paper, top=2cm]{geometry}\n'
    assert scan_text(geo)[0]['paper'] == 'geometry:a4paper' and not scan_text(geo)[0]['reported'], 'geometry with a size sets the paper'
    assert scan_text('\\documentclass{article}\n\\usepackage[margin=1in]{geometry}\n')[0]['reported'], 'margins alone do not'
    assert not scan_text('\\documentclass{article}\n\\usepackage{geometry}\n\\geometry{a4paper,margin=2cm}\n')[0]['reported']
    assert scan_text('\\documentclass{article}\n% \\usepackage[a4paper]{geometry}\n')[0]['reported'], 'commented-out geometry'
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        (repo / 'a.tex').write_text(plain, encoding='utf-8')
        (repo / 'b.tex').write_text(ok, encoding='utf-8')
        subprocess.run(['git', '-C', str(repo), 'add', 'a.tex', 'b.tex'], check=True)
        assert staged_warn(repo) == 0, 'warn only'
        assert staged_warn(repo / 'nope') == 3
        assert main(['x', str(repo / 'a.tex')]) == 1 and main(['x', str(repo / 'b.tex')]) == 0
    print('selftest OK (16 checks)')
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args == ['--selftest']:
        return _selftest()
    if args[:1] == ['--staged-warn']:
        repo = Path(args[args.index('--repo') + 1]) if '--repo' in args else Path.cwd()
        return staged_warn(repo)
    if args[:1] == ['--pdf'] and len(args) == 2:
        print(f"{args[1]}: {pdf_size(Path(args[1]).expanduser())}")
        return 0
    files = [a for a in args if not a.startswith('--')]
    if not files or len(files) != len(args):
        print(__doc__)
        return 2
    findings = []
    for f in files:
        findings += report_file(Path(f).expanduser())
    for line in findings:
        print(line)
    if not findings:
        print(f"paper size declared in {len(files)} file(s)")
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
