#!/usr/bin/env python3
"""Move one pTeX .tex to LuaLaTeX and compare the two builds (pages, paper size, rendered ink, text per page); --apply writes the moved text back, --selftest.

Why (measured): moving a document from platex / uplatex to LuaLaTeX by hand edits the class line, the class options,
the package options and the TeXShop program line, and the result can still differ from the old PDF in ways that no
error shows: a jsarticle at 11pt / 12pt is typeset with \\mag and came out on paper larger than A4 (or on Letter),
an `article` whose body has Japanese lost every Japanese glyph under LuaLaTeX without luatexja (the log only says
`Missing character`), and luatexja loaded at the top of the preamble shrank \\textheight (with a4wide after it) and
pushed a one-page table to two pages.  So the move is mechanical and the check is a comparison of the two builds.

What it does
  1. converts the text (= the rules of conventions/latex.md#lualatex-compat):
     - class jsarticle / jsbook / jsreport → ltjs*, jarticle / jbook / jreport → ltj*
     - drops the class options dvipdfmx / dvips / dviout / platex / uplatex / papersize / nomag / nomag*
     - drops DVI driver options from \\usepackage[...] and the package pxjahyper
     - an `article`-type class with Japanese in the text gets \\usepackage{luatexja} just before \\begin{document}
     - replaces the TeXShop lines with `% !TEX TS-program = lualatex` and `% !TEX encoding = UTF-8 Unicode`
  2. builds the original with ptex2pdf (-u when the source names uplatex) and the converted text with lualatex, both
     twice, each in its own copy under WORKDIR; TEXINPUTS points at the source's directory so \\input files, figures
     and .sty beside the source are found (BibTeX is not run: a document with a bibliography is compared without it)
  3. prints: both exit codes, pages old / new, page sizes, the share of ink pixels that changed per page (0 = same),
     how much of the text matches per page and over the whole document, overfull boxes in the new log, and the
     LuaLaTeX marks that are still in the converted text (from check-tex-engine.py beside this file: otf / okumacro /
     plext / pxcjkcat need a hand replacement = luatexja-otf / luatexja-ruby)
  4. --apply writes the converted text to the source (only when the new build succeeded)
Read the numbers before --apply: a page-count change, a size change, or a whole-text match well below 1 is a reason
to look at both PDFs.  A low match on pages whose text moved between pages, with the same whole-text match, is
usually a reflow, not a loss.

Usage
  migrate-tex-to-lualatex.py SRC.tex WORKDIR [--apply]
  migrate-tex-to-lualatex.py --selftest
Requires: lualatex and ptex2pdf on PATH (TeX Live), PyMuPDF (fitz) for the comparison.  WORKDIR is wiped and
re-created; put it in a scratch directory.
"""
from __future__ import annotations

import difflib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CLASS_MAP = {'jsarticle': 'ltjsarticle', 'jsbook': 'ltjsbook', 'jsreport': 'ltjsreport',
             'jarticle': 'ltjarticle', 'jbook': 'ltjbook', 'jreport': 'ltjreport'}
DROP_CLASS_OPTS = {'dvipdfmx', 'dvips', 'dviout', 'uplatex', 'platex', 'papersize', 'nomag', 'nomag*'}
DVI_DRIVERS = {'dvipdfmx', 'dvips', 'dviout'}
DROP_PACKAGES = {'pxjahyper'}
DOCCLASS = re.compile(r'^([ \t]*\\documentclass\s*)(?:\[([^\]]*)\])?(\s*\{)([^}]+)(\})', re.M)
USEPKG = re.compile(r'^([^%\n]*\\usepackage\s*)\[([^\]]*)\](\s*\{[^}]+\})', re.M)
TSPROG = re.compile(r'^[ \t]*%[ \t]*!TEX\s+(?:TS-)?program\s*=.*\n', re.M | re.I)
TSENC = re.compile(r'^[ \t]*%[ \t]*!TEX\s+encoding\s*=.*\n', re.M | re.I)
JAPANESE = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef]')
HEADER = '% !TEX TS-program = lualatex\n% !TEX encoding = UTF-8 Unicode\n'


def convert(text: str) -> str:
    m = DOCCLASS.search(text)
    if not m:
        raise ValueError('no \\documentclass (only a root document can be moved)')
    opts = [o.strip() for o in (m.group(2) or '').split(',') if o.strip() and o.strip() not in DROP_CLASS_OPTS]
    cls = CLASS_MAP.get(m.group(4).strip(), m.group(4).strip())
    new = m.group(1) + (f"[{','.join(opts)}]" if opts else '') + m.group(3) + cls + m.group(5)
    # pTeX typesets Japanese in any class; under LuaLaTeX an article-type class needs luatexja
    add_ja = (not cls.startswith('ltj') and JAPANESE.search(text)
              and not re.search(r'\\usepackage(\[[^\]]*\])?\{luatexja\}', text))
    text = text[:m.start()] + new + text[m.end():]
    if add_ja:
        # last in the preamble: loaded before a4wide it shrank \textheight (measured 621pt -> 432pt)
        text = re.sub(r'^([ \t]*\\begin\{document\})', r'\\usepackage{luatexja}\n\1', text, count=1, flags=re.M)

    def pkg(mm):
        o = [x.strip() for x in mm.group(2).split(',') if x.strip() and x.strip() not in DVI_DRIVERS]
        return mm.group(1) + (f"[{','.join(o)}]" if o else '') + mm.group(3)
    text = USEPKG.sub(pkg, text)
    for p in DROP_PACKAGES:
        text = re.sub(r'^([ \t]*)\\usepackage(\[[^\]]*\])?\{' + p + r'\}[ \t]*\n', '', text, flags=re.M)
    text = TSENC.sub('', TSPROG.sub('', text))
    return HEADER + text


def remaining_marks(text: str) -> list[str]:
    """LuaLaTeX marks still in the text, from check-tex-engine.py beside this file ([] if it is not there)."""
    path = Path(__file__).with_name('check-tex-engine.py')
    if not path.exists():
        return []
    spec = importlib.util.spec_from_file_location('check_tex_engine', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scan_text(text)['reasons']


def _run(cmd, cwd: Path, srcdir: Path):
    # the build's own directory first: the source's directory also holds the unconverted file of the same name
    env = dict(os.environ, TEXINPUTS=f'.:{srcdir}//:' + os.environ.get('TEXINPUTS', ''))
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors='replace', timeout=600, env=env)
    return p.returncode, p.stdout[-1500:] + p.stderr[-500:]


def build_ptex(tex: Path, uplatex: bool, srcdir: Path):
    flags = ['-l'] + (['-u'] if uplatex else [])
    for _ in range(2):
        rc, out = _run(['ptex2pdf', *flags, '-ot', '-interaction=nonstopmode -halt-on-error', tex.name], tex.parent, srcdir)
    return rc, out


def build_lua(tex: Path, srcdir: Path):
    for _ in range(2):
        rc, out = _run(['lualatex', '-interaction=nonstopmode', '-halt-on-error', tex.name], tex.parent, srcdir)
    return rc, out


def compare(a: Path, b: Path):
    import fitz  # PyMuPDF
    da, db = fitz.open(a), fitz.open(b)
    sizes = ([(round(p.rect.width), round(p.rect.height)) for p in da],
             [(round(p.rect.width), round(p.rect.height)) for p in db])
    diffs = []
    for i in range(min(da.page_count, db.page_count)):
        pa = da[i].get_pixmap(matrix=fitz.Matrix(0.5, 0.5), colorspace=fitz.csGRAY)
        pb = db[i].get_pixmap(matrix=fitz.Matrix(0.5, 0.5), colorspace=fitz.csGRAY)
        if (pa.width, pa.height) != (pb.width, pb.height):
            diffs.append(None)  # different page size: no pixel comparison
            continue
        sa, sb = pa.samples, pb.samples
        ink = sum(1 for x in sa if x < 128) + sum(1 for x in sb if x < 128)
        changed = sum(1 for x, y in zip(sa, sb) if (x < 128) != (y < 128))
        diffs.append(round(changed / max(1, ink), 3))
    ta = [re.sub(r'\s+', '', p.get_text()) for p in da]
    tb = [re.sub(r'\s+', '', p.get_text()) for p in db]
    per_page = [round(difflib.SequenceMatcher(None, x, y).ratio(), 3) for x, y in zip(ta, tb)]
    whole = round(difflib.SequenceMatcher(None, ''.join(ta), ''.join(tb)).ratio(), 4)
    return da.page_count, db.page_count, sizes, diffs, per_page, whole


def migrate(src: Path, work: Path, apply: bool) -> int:
    original = src.read_text(encoding='utf-8')
    m = DOCCLASS.search(original)
    if not m:
        print(f'{src}: no \\documentclass (only a root document can be moved)')
        return 2
    uplatex = bool(re.search(r'\buplatex\b', m.group(2) or '')) or \
        bool(re.search(r'TS-program\s*=\s*uplatex', original, re.I))
    converted = convert(original)
    if work.exists():
        shutil.rmtree(work)
    (work / 'old').mkdir(parents=True)
    (work / 'new').mkdir(parents=True)
    old, new = work / 'old' / src.name, work / 'new' / src.name
    old.write_text(original, encoding='utf-8')
    new.write_text(converted, encoding='utf-8')
    rc_o, out_o = build_ptex(old, uplatex, src.parent)
    rc_n, out_n = build_lua(new, src.parent)
    pdf_o, pdf_n = old.with_suffix('.pdf'), new.with_suffix('.pdf')
    print(f'== {src}')
    print(f'   old route: ptex2pdf {"-u " if uplatex else ""}rc={rc_o}  pdf={pdf_o.exists()}')
    print(f'   new route: lualatex rc={rc_n}  pdf={pdf_n.exists()}')
    marks = remaining_marks(converted)
    if marks:
        print(f'   still in the converted text (replace by hand): {"; ".join(marks)}')
    if rc_n != 0 or not pdf_n.exists():
        print('   NEW BUILD FAILED (nothing applied):\n' + out_n[-1200:])
        return 2
    if pdf_o.exists():
        po, pn, sizes, diffs, per_page, whole = compare(pdf_o, pdf_n)
        print(f'   pages old={po} new={pn}  sizes old={sizes[0]} new={sizes[1]}')
        print(f'   ink changed per page (0 = same): {diffs}')
        print(f'   text match per page: {per_page}  whole document: {whole}')
    else:
        print('   old build failed (no comparison):\n' + out_o[-600:])
    log = new.with_suffix('.log').read_text(errors='replace') if new.with_suffix('.log').exists() else ''
    ov = re.findall(r'Overfull \\hbox \((\d+\.\d+)pt', log)
    print(f'   new overfull boxes: {len(ov)}' + (f' (max {max(map(float, ov)):.1f}pt)' if ov else ''))
    missing = len(re.findall(r'Missing character', log))
    if missing:
        print(f'   ⚠️ new log: {missing} "Missing character" (glyphs dropped without an error)')
    if apply:
        src.write_text(converted, encoding='utf-8')
        print('   APPLIED to source')
    return 0


def _selftest() -> int:
    n = 0

    def check(cond, label):
        nonlocal n
        n += 1
        if not cond:
            raise AssertionError(label)

    a = convert('% !TEX TS-program = platex\n\\documentclass[11pt,dvipdfmx,papersize]{jsarticle}\n'
                '\\usepackage[dvipdfmx]{graphicx}\n\\usepackage{pxjahyper}\n\\begin{document}\nあ\n\\end{document}\n')
    check(a.startswith(HEADER), 'header first')
    check('\\documentclass[11pt]{ltjsarticle}' in a, 'class and options')
    check('\\usepackage{graphicx}' in a, 'driver option dropped')
    check('pxjahyper' not in a, 'pxjahyper dropped')
    check('platex' not in a, 'old program line removed')
    check('luatexja' not in a, 'ltjs class needs no luatexja')
    b = convert('\\documentclass[12pt,a4paper]{article}\n\\usepackage{a4wide}\n\\begin{document}\n和音\n\\end{document}\n')
    check('\\usepackage{a4wide}\n\\usepackage{luatexja}\n\\begin{document}' in b, 'luatexja just before begin{document}')
    c = convert('\\documentclass{article}\n\\begin{document}\nEnglish only\n\\end{document}\n')
    check('luatexja' not in c, 'no Japanese, no luatexja')
    d = convert('\\documentclass[uplatex,nomag*]{jsbook}\n\\usepackage[dvipdfmx,hidelinks]{hyperref}\n'
                '\\begin{document}\nx\n\\end{document}\n')
    check('\\documentclass{ltjsbook}' in d, 'uplatex and nomag* dropped, jsbook -> ltjsbook')
    check('\\usepackage[hidelinks]{hyperref}' in d, 'other package options kept')
    e = convert('\\documentclass{jarticle}\n% \\usepackage[dvipdfmx]{graphicx}\n\\begin{document}\nx\n\\end{document}\n')
    check('\\documentclass{ltjarticle}' in e, 'jarticle -> ltjarticle')
    check('% \\usepackage[dvipdfmx]{graphicx}' in e, 'commented-out line left as it is')
    check(convert(a) == a, 'converting twice changes nothing')
    try:
        convert('\\section{x}\n')
        check(False, 'a file without documentclass is refused')
    except ValueError:
        check(True, 'a file without documentclass is refused')
    marks = remaining_marks(convert('\\documentclass{jsarticle}\n\\usepackage{otf}\n\\begin{document}\nあ\n\\end{document}\n'))
    check(not Path(__file__).with_name('check-tex-engine.py').exists() or any('otf' in r for r in marks),
          'otf is reported as still to replace')
    print(f'selftest OK ({n} checks)')
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ['--selftest']:
        return _selftest()
    args = [a for a in argv if a != '--apply']
    if len(args) != 2:
        print(__doc__.split('Usage')[1].split('Requires')[0].strip())
        return 2
    return migrate(Path(args[0]).expanduser().resolve(), Path(args[1]).expanduser().resolve(), '--apply' in argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
