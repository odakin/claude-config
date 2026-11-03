#!/usr/bin/env python3
"""diff-form-docx.py — 様式 docx の記入ミスを blank diff で検出（ラベル欄上書き/見出し消失/段落の増加/足した欧文の font/Word で描いた頁数と様式の字のずれ=HARD・空の箇条書き/全空 labeled 列=surface、描けなければ exit 3 = 見た目は未確認、--selftest 内蔵、office-automation.md#diff-form-docx-detection）
Compare a filled-in 様式 docx against its blank template; flag fill mistakes.

Usage:
    diff-form-docx.py <filled.docx> <blank.docx> [--strict] [--no-render]
                      [--filled-pdf F.pdf --blank-pdf B.pdf] [--keep-pdf DIR]
                      [--allow-added-paragraphs]
    diff-form-docx.py --receipt-status <filled.docx> [--json]
    diff-form-docx.py --not-a-form <file.docx> --reason '<本人の言葉 / 雛形が無い理由>'
    diff-form-docx.py --selftest

The docx analog of `diff-form-xlsx.py`. Word 様式 (cover sheets, 申請書) have no
mechanical fill-check, so a whole class of mistakes slips through even after a
human renders the PDF and "looks at it" — because the human looks at *what they
filled*, not at *what a reviewer would see as blank / overwritten / mis-placed*.

Findings
--------
HARD (exit 1):
  ❌ LABEL_OVERWRITE  : a table cell that held pre-printed label text in the blank
                        form now holds *different* text (no containment either way;
                        a choice mark ○ ■ ☑ … put into the label does not count).
                        = the cover-sheet bug: writing a value into a LABEL cell
                          (e.g. birth date typed into the 「年令」/age label cell).
  ❌ LABEL_DELETED    : a blank label cell is empty in the filled form.
  ❌ HEADING_VANISHED : a structural heading paragraph ( （N） / N． ) present in the
                        blank form is absent from the filled form (= overwritten /
                        deleted, e.g. a heading clobbered by an off-by-one fill).
  ❌ PARA_ADDED       : the body (or a textbox) has MORE paragraphs than in the blank,
                        counting self-closing empty paragraphs `<w:p .../>` (= 記入行).
                        The fill wrote a new paragraph instead of the template's line;
                        on a fixed-pitch form (docGrid type="lines") each one pushes
                        the page by a line. --allow-added-paragraphs turns this into
                        PARA_GREW (for documents meant to grow); the render check
                        still runs. A table cell that grows is PARA_GREW (a cell
                        takes several lines by design; the render check sees the row
                        push the page).
  ❌ FONT_MISMATCH    : a run the fill added or changed carries Latin letters/digits
                        whose effective Latin font (run → style → docDefaults → theme)
                        is not the font the blank uses for Latin text in that
                        paragraph (or anywhere, if the paragraph has none). = a run
                        written without `w:rFonts` falls back to the theme's Latin
                        font (e.g. Century) and prints visibly different.
  Render-based (Word via docx-to-pdf.sh, both files; or the PDFs you pass):
  ❌ PAGE_ADDED       : the filled PDF has more pages than the blank PDF.
  ❌ LAYOUT_SHIFT     : template text lines (= lines identical in both PDFs) moved
                        down = a fill wrapped onto an extra line or added one.
  ❌ PDF_FONT_NEW     : a font renders letters/digits in the filled PDF but renders
                        none in the blank PDF, or renders any visible character in
                        the filled PDF while the blank uses it for none (a font that
                        only draws spaces in the blank counts as absent).

SURFACE (printed; exit 0 unless --strict):
  ⚠ BULLET_EMPTY     : a bullet placeholder ( 「・」 alone ) is still empty
                        = a whole 「・・・」 section left unfilled.
  ⚠ EMPTY_LABELED_COL: a table column with a non-empty header has *all* data cells
                        empty = a labeled column (e.g. 「年月」) left blank.
  ⚠ PARA_GREW        : a table cell has more paragraphs than in the blank (or the body,
                        with --allow-added-paragraphs). At a fixed row height the text
                        can clip without moving anything = look at the rendered PDF.
  ⚠ PARA_REMOVED     : a container has fewer paragraphs than in the blank.
  ⚠ LAYOUT_SHIFT_UP  : template text lines moved up (= a template line was removed).
  ℹ LABEL_PARTIAL    : filled text is a substring of the blank label (label split /
                        restructured, e.g. one 「学歴・職歴」 cell broken into rows).
  ℹ INPUT_FILLED     : blank cell, filled has text (= normal applicant input).

Exit: 0 = no HARD (render done, or --no-render) / 1 = HARD (or --strict + surface) /
      2 = usage / 3 = the render could not be done = 見た目 (頁数・行の折れ・紙の font) は未確認.
      Exit 3 is not a pass: do not show or send the form until one of the other routes
      (office-automation.md#docx-layout-unverified) has confirmed the layout.
Every run records one line (sha256 of the filled file, path, result = pass / hard /
unverified / no-render) in ${XDG_STATE_HOME:-~/.local/state}/claude-form-layout/receipts.tsv;
--receipt-status answers whether the file as it is now passed with the render (exit 0)
or not (exit 1, saying whether that path was checked before = a gate can tell a form
that went through this check from a document that never did; --json = one object
{passed, seen_path, status, when, pages, reason} for a gate to read). --not-a-form
records, for the file's current content only, that a docx has no blank template
(not a form) with a reason (the owner's words); a gate treats it as passed, and any
change to the file voids it.

The check is structural, not semantic: it can tell that a box / column / bullet is
EMPTY or that a label was REPLACED, but it cannot judge whether prose content is
*thin* — that remains a human "reviewer's-eye" pass (see
office-automation-principles.md#reviewer-eye-completion). The render check finds
growth and new fonts, not a value that fits but reads wrong (= look at the PDF).

Why this script exists
----------------------
2026-06-27 ある研究費 docx 申請様式を 1 session で記入した際、同じ様式に対し
4 つの記入ミスを連続で出し、そのつど人間 (申請者) が見つけて指摘した:
  (1) 生年月日を「年令」ラベルセルに上書き  → LABEL_OVERWRITE
  (2) 「（１）研究者氏名・所属先」の「・・・」を空欄のまま  → BULLET_EMPTY
  (3) 略歴の「年月」列を空のまま (内容列に畳んだ)  → EMPTY_LABELED_COL
  (4) ≪研究内容概要≫ の箱が下半分・薄い  → (箱の空きは検出可、薄さは判断)
さらに自分で catch した off-by-one 見出し上書き (= 「（５）...」見出しの clobber) も
HEADING_VANISHED として機械化する。xlsx には diff-form-xlsx.py があるが docx には
無かった = この session の記入が機械の網ゼロだった。これを埋める。
追記 (実測): 1 頁の様式を XML 直編集で記入し、 2 頁にはみ出した・行が折れた・
足した run の欧文だけ別の font で出た、 のまま本人に見せた。 記入の script は段落を
`<w:p[ >].*?</w:p>` で切っており自己終了の記入行が見えず段落を足した。 PDF 化が止まった時点で
目視の経路ごと落とし「見た目は未確認」 と台帳に書いて先へ進んだ。 → PARA_ADDED / FONT_MISMATCH /
描画の 3 検査 / exit 3 / 段落の切り方の共有部品 scripts/lib/docx_paragraphs.py を足した。
"""

import difflib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import docx_paragraphs as dp  # noqa: E402

try:
    from docx import Document
except ImportError:  # pragma: no cover
    print("python-docx required: pip install python-docx", file=sys.stderr)
    sys.exit(2)

# Heading-like paragraph: （１） / (1) / １． / 1. / １、 etc. — pure structural labels
# that must survive verbatim in the filled form.
HEADING_RE = re.compile(r"^[\s　]*(?:[（(][0-9０-９]+[）)]|[0-9０-９]+[．.、])")
# A paragraph whose normalized text is exactly one of these is an empty bullet slot.
BULLET_TOKENS = {"・", "·", "•", "‧", "・", "-", "*", "／", "/"}
LATIN = re.compile(r"[A-Za-z0-9]")
SHIFT_TOL_PT = 2.0
DOCX_TO_PDF = os.path.join(HERE, "docx-to-pdf.sh")
WORD_APP = "/Applications/Microsoft Word.app"


CHOICE_MARKS = "○◯●◎■□☑☐✓✔"


def _unmarked(s):
    """norm した字から選択の印を除く (印を付けただけの label を上書きと読まない)。"""
    return "".join(c for c in s if c not in CHOICE_MARKS)


def norm(s):
    """NFKC + strip ALL whitespace (incl. full-width 　 and newlines)."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"\s+", "", s)


def all_text_blocks(doc):
    """Every text-bearing block (body paragraphs + all table cells), flattened."""
    blocks = []
    for p in doc.paragraphs:
        blocks.append(p.text)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                blocks.append(cell.text)
    return blocks


def _new_findings():
    return {k: [] for k in (
        "LABEL_OVERWRITE", "LABEL_DELETED", "HEADING_VANISHED", "PARA_ADDED", "FONT_MISMATCH",
        "PAGE_ADDED", "LAYOUT_SHIFT", "PDF_FONT_NEW",
        "BULLET_EMPTY", "EMPTY_LABELED_COL", "PARA_GREW", "PARA_REMOVED", "LAYOUT_SHIFT_UP",
        "LABEL_PARTIAL", "INPUT_FILLED")}


def diff_forms(filled_path, blank_path, allow_added=False):
    fdoc = Document(filled_path)
    bdoc = Document(blank_path)
    findings = _new_findings()

    _diff_tables(fdoc, bdoc, findings)
    _check_headings(fdoc, bdoc, findings)
    _check_bullets(fdoc, findings)
    _check_paragraph_counts(filled_path, blank_path, findings, allow_added)
    _check_fonts(filled_path, blank_path, findings)
    return findings


def _diff_tables(fdoc, bdoc, findings):
    for ti, (bt, ft) in enumerate(zip(bdoc.tables, fdoc.tables)):
        nrow = min(len(bt.rows), len(ft.rows))
        ncol = min(len(bt.columns), len(ft.columns))
        # --- per-cell label / input diff ---
        for r in range(nrow):
            for c in range(ncol):
                try:
                    bv = bt.cell(r, c).text
                    fv = ft.cell(r, c).text
                except (IndexError, ValueError):
                    continue
                bn, fn = norm(bv), norm(fv)
                if bn == fn:
                    continue
                loc = f"table{ti}!r{r}c{c}"
                if not bn:                       # blank empty -> applicant input
                    if fn:
                        findings["INPUT_FILLED"].append((loc, _short(fv)))
                elif not fn:                     # label cell now empty
                    findings["LABEL_DELETED"].append((loc, f"blank={_short(bv)} -> empty"))
                elif bn in fn:                   # label preserved + appended (e.g. ○第１課題)
                    pass                         # OK (mark / box label kept)
                elif _unmarked(bn) and _unmarked(bn) in _unmarked(fn):
                    pass                         # OK: only a choice mark moved in (連絡／○面談, □→■)
                elif fn in bn:                   # filled is a subset of the label (restructure)
                    findings["LABEL_PARTIAL"].append((loc, f"blank={_short(bv)} -> {_short(fv)}"))
                else:                            # text fully replaced = overwrite
                    findings["LABEL_OVERWRITE"].append((loc, f"blank={_short(bv)} -> {_short(fv)}"))
        # --- labeled column with all data cells empty (in the FILLED form) ---
        # Only for "header tables" = blank row 0 is a *full* header (every cell
        # non-empty). This excludes key-value cover sheets (label|value|label|…
        # where blank row 0 has gaps at the value cells), so 略歴/予算表 (uniform
        # header row) are checked but the 表紙 is not.
        blank_header_full = (
            len(bt.columns) >= 2
            and all(norm(bt.cell(0, c).text) for c in range(len(bt.columns)))
        )
        if blank_header_full and len(ft.rows) >= 2 and len(ft.columns) >= 1:
            for c in range(len(ft.columns)):
                try:
                    header = norm(ft.cell(0, c).text)
                except (IndexError, ValueError):
                    continue
                if not header:
                    continue
                data_cells = []
                seen = set()
                for r in range(1, len(ft.rows)):
                    try:
                        cell = ft.cell(r, c)
                    except (IndexError, ValueError):
                        continue
                    key = id(cell._tc)           # dedupe merged cells
                    if key in seen:
                        continue
                    seen.add(key)
                    data_cells.append(norm(cell.text))
                if data_cells and all(not d for d in data_cells):
                    findings["EMPTY_LABELED_COL"].append(
                        (f"table{ti} col{c}", f"header={_short(ft.cell(0, c).text)} / data cells all empty"))


def _is_subsequence(needle, hay):
    it = iter(hay)
    return all(c in it for c in needle)


def _check_headings(fdoc, bdoc, findings):
    filled_text = norm("".join(all_text_blocks(fdoc)))
    filled_paras = [norm(p.text) for p in fdoc.paragraphs]
    for t in fdoc.tables:
        for row in t.rows:
            for cell in row.cells:
                filled_paras += [norm(p.text) for p in cell.paragraphs]
    for p in bdoc.paragraphs:
        raw = p.text
        m = HEADING_RE.match(raw)
        if not m:
            continue
        hn = norm(raw)
        if not hn or hn in filled_text:
            continue
        # A numbered line can itself be the fill line (「３．…：　年　月　日」): the heading survives
        # when a paragraph still starts with its number and keeps every template character in order.
        num = norm(m.group(0))
        if any(fp.startswith(num) and _is_subsequence(hn, fp) for fp in filled_paras):
            continue
        findings["HEADING_VANISHED"].append(("body", _short(raw)))


def _check_bullets(fdoc, findings):
    for p in fdoc.paragraphs:
        if norm(p.text) in BULLET_TOKENS:
            findings["BULLET_EMPTY"].append(("body", f"empty bullet: {p.text!r}"))
    for t in fdoc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if norm(p.text) in BULLET_TOKENS:
                        findings["BULLET_EMPTY"].append(("table-cell", f"empty bullet: {p.text!r}"))


# --------------------------------------------------------------------------- #
# paragraph counts (self-closing included) — scripts/lib/docx_paragraphs.py
# --------------------------------------------------------------------------- #
def _check_paragraph_counts(filled_path, blank_path, findings, allow_added):
    fxml, bxml = dp.read_part(filled_path), dp.read_part(blank_path)
    fps, bps = dp.paragraphs(fxml), dp.paragraphs(bxml)
    fc, bc = dp.counts(fxml), dp.counts(bxml)
    bids = {p.para_id for p in bps if p.para_id}
    for cont in sorted(set(fc) | set(bc)):
        nf, nb = fc.get(cont, 0), bc.get(cont, 0)
        if nf == nb:
            continue
        if nf > nb:
            new = [p for p in fps if p.container == cont and p.para_id and p.para_id not in bids]
            hint = ("; new: " + ", ".join(f"#{p.index} {_short(p.text, 30)}" for p in new[:5])) if new else ""
            if "/tc" in cont:
                # a table cell grows its row (or clips at a fixed row height) = the render check decides
                findings["PARA_GREW"].append((cont, f"表の cell の段落 {nb} → {nf} (行が伸びるか、 行の高さが固定なら字が切れる = 描いた紙で見る){hint}"))
            elif allow_added:
                findings["PARA_GREW"].append((cont, f"(--allow-added-paragraphs) 段落 {nb} → {nf}{hint}"))
            else:
                findings["PARA_ADDED"].append((cont, f"段落 {nb} → {nf} (自己終了の空段落を含む){hint}"))
        else:
            findings["PARA_REMOVED"].append((cont, f"段落 {nb} → {nf} (雛形の行を消した = 下の字が上がる)"))


# --------------------------------------------------------------------------- #
# effective Latin font of the runs the fill touched
# --------------------------------------------------------------------------- #
_RPR = re.compile(r"<w:rPr>(.*?)</w:rPr>", re.S)
_RFONTS = re.compile(r"<w:rFonts\b([^>]*?)/?>")
_ATTR = re.compile(r'w:(\w+)="([^"]*)"')
_LANG_SCRIPT = {"ja-JP": "Jpan", "zh-CN": "Hans", "zh-TW": "Hant", "ko-KR": "Hang"}


def _rfonts(fragment):
    m = _RFONTS.search(fragment or "")
    return dict(_ATTR.findall(m.group(1))) if m else {}


class _FontContext:
    """styles.xml + theme1.xml of one package: resolves the font a run prints Latin text in."""

    def __init__(self, path):
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            styles = z.read("word/styles.xml").decode("utf-8") if "word/styles.xml" in names else ""
            theme_name = next((n for n in sorted(names) if re.match(r"word/theme/theme\d+\.xml$", n)), None)
            theme = z.read(theme_name).decode("utf-8") if theme_name else ""
        self.styles = {}
        self.default_para = None
        for m in re.finditer(r"<w:style\b([^>]*)>(.*?)</w:style>", styles, re.S):
            attrs = dict(_ATTR.findall(m.group(1)))
            body = m.group(2)
            sid = attrs.get("styleId")
            if not sid:
                continue
            based = re.search(r'<w:basedOn w:val="([^"]*)"', body)
            rpr = _RPR.search(body)
            self.styles[sid] = (based.group(1) if based else None, _rfonts(rpr.group(1) if rpr else ""))
            if attrs.get("type") == "paragraph" and attrs.get("default") == "1":
                self.default_para = sid
        dd = re.search(r"<w:rPrDefault>(.*?)</w:rPrDefault>", styles, re.S)
        self.defaults = _rfonts(dd.group(1)) if dd else {}
        lang = re.search(r'<w:lang\b[^>]*w:eastAsia="([^"]*)"', dd.group(1) if dd else "")
        script = _LANG_SCRIPT.get(lang.group(1) if lang else "ja-JP", "Jpan")
        self.theme = {}
        for kind in ("major", "minor"):
            blk = re.search(rf"<a:{kind}Font>(.*?)</a:{kind}Font>", theme, re.S)
            if not blk:
                continue
            b = blk.group(1)
            latin = re.search(r'<a:latin typeface="([^"]*)"', b)
            ea = re.search(r'<a:ea typeface="([^"]*)"', b)
            scr = re.search(rf'<a:font script="{script}" typeface="([^"]*)"', b)
            cs = re.search(r'<a:cs typeface="([^"]*)"', b)
            lat = latin.group(1) if latin else ""
            east = (ea.group(1) if ea and ea.group(1) else "") or (scr.group(1) if scr else "")
            for k in ("Ascii", "HAnsi"):
                self.theme[f"{kind}{k}"] = lat
            self.theme[f"{kind}EastAsia"] = east
            self.theme[f"{kind}Bidi"] = cs.group(1) if cs else ""

    def _latin(self, attrs):
        if "asciiTheme" in attrs:
            return self.theme.get(attrs["asciiTheme"]) or attrs["asciiTheme"]
        if attrs.get("ascii"):
            return attrs["ascii"]
        return None

    def _chain(self, sid):
        seen = set()
        while sid and sid not in seen and sid in self.styles:
            seen.add(sid)
            based, rf = self.styles[sid]
            f = self._latin(rf)
            if f:
                return f
            sid = based
        return None

    def latin_font(self, run_xml, para_xml):
        rpr = _RPR.search(run_xml)
        rpr = rpr.group(1) if rpr else ""
        f = self._latin(_rfonts(rpr))
        if f:
            return f
        rs = re.search(r'<w:rStyle w:val="([^"]*)"', rpr)
        if rs:
            f = self._chain(rs.group(1))
            if f:
                return f
        ps = re.search(r'<w:pStyle w:val="([^"]*)"', para_xml)
        f = self._chain(ps.group(1) if ps else self.default_para)
        if f:
            return f
        return self._latin(self.defaults) or "(既定)"


def _run_text(run_xml):
    return dp._text_of(run_xml)


def _para_runs(xml, ps):
    """index → (paragraph XML without nested textbox paragraphs, [run XML])."""
    out = {}
    for p in ps:
        if p.self_closing:
            out[p.index] = (xml[p.start:p.end], [])
            continue
        body = dp.para_xml(xml, p, ps)
        out[p.index] = (body, dp.runs(body))
    return out


def _align(bps, fps):
    """filled paragraph index → blank paragraph index (paraId first, then text order)."""
    mapping = {}
    bid = {p.para_id: p.index for p in bps if p.para_id}
    rest_f = []
    for p in fps:
        if p.para_id and p.para_id in bid:
            mapping[p.index] = bid[p.para_id]
        else:
            rest_f.append(p)
    used = set(mapping.values())
    rest_b = [p for p in bps if p.index not in used]
    sm = difflib.SequenceMatcher(None, [(p.container, p.text) for p in rest_b],
                                 [(p.container, p.text) for p in rest_f], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal", "replace") and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                mapping[rest_f[j1 + k].index] = rest_b[i1 + k].index
    return mapping


def _check_fonts(filled_path, blank_path, findings):
    fxml, bxml = dp.read_part(filled_path), dp.read_part(blank_path)
    fps, bps = dp.paragraphs(fxml), dp.paragraphs(bxml)
    bctx, fctx = _FontContext(blank_path), _FontContext(filled_path)
    bruns, fruns = _para_runs(bxml, bps), _para_runs(fxml, fps)
    local, every = {}, set()
    for i, (pxml, rs) in bruns.items():
        fonts = {bctx.latin_font(r, pxml) for r in rs if LATIN.search(_run_text(r))}
        local[i] = fonts
        every |= fonts
    if not every:
        return  # the blank prints no Latin text = nothing to compare against
    mapping = _align(bps, fps)
    for p in fps:
        pxml, rs = fruns[p.index]
        bi = mapping.get(p.index)
        before = Counter(bruns[bi][1]) if bi is not None else Counter()
        ref = local.get(bi) or every
        for r in rs:
            if before[r] > 0:
                before[r] -= 1
                continue  # the template's own run, unchanged
            text = _run_text(r)
            if not LATIN.search(text):
                continue
            f = fctx.latin_font(r, pxml)
            if f not in ref:
                findings["FONT_MISMATCH"].append(
                    (f"#{p.index}", f"「{_short(text, 24)}」 の欧文 = {f} (雛形のこの段落の欧文 = {'/'.join(sorted(ref))})"))


# --------------------------------------------------------------------------- #
# render: page count / template lines moved / new fonts on paper
# --------------------------------------------------------------------------- #
def _pdf_lines(path):
    import fitz
    doc = fitz.open(path)
    lines, fonts_alnum, fonts_all = [], set(), set()
    offset = 0.0
    for page in doc:
        h = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                txt = norm("".join(s["text"] for s in ln["spans"]))
                for s in ln["spans"]:
                    name = re.sub(r"^[A-Z]{6}\+", "", s.get("font", ""))
                    if s["text"].strip():
                        fonts_all.add(name)
                    if LATIN.search(s["text"]):
                        fonts_alnum.add(name)
                if txt:
                    lines.append((txt, offset + ln["bbox"][1], page.number))
        offset += h
    n = doc.page_count
    doc.close()
    lines.sort(key=lambda t: t[1])
    return n, lines, fonts_alnum, fonts_all


def check_pdfs(filled_pdf, blank_pdf, findings):
    nf, lf, af, allf = _pdf_lines(filled_pdf)
    nb, lb, ab, allb = _pdf_lines(blank_pdf)
    if nf > nb:
        findings["PAGE_ADDED"].append(("pdf", f"頁 {nb} → {nf}"))
    ys = sorted({round(y, 1) for _, y, p in lb if p == 0})
    gaps = sorted(b - a for a, b in zip(ys, ys[1:]) if b - a > 1)
    pitch = gaps[len(gaps) // 2] if gaps else 18.0
    sm = difflib.SequenceMatcher(None, [t for t, _, _ in lb], [t for t, _, _ in lf], autojunk=False)
    down, up = [], []
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            tb, yb, _ = lb[blk.a + k]
            _, yf, _ = lf[blk.b + k]
            d = yf - yb
            if d > SHIFT_TOL_PT:
                down.append((d, tb))
            elif d < -SHIFT_TOL_PT:
                up.append((d, tb))
    if down:
        first = down[0]
        mx = max(d for d, _ in down)
        findings["LAYOUT_SHIFT"].append(
            ("pdf", f"様式の字 {len(down)} 行が下にずれた (最大 {mx:.1f}pt ≈ {mx / pitch:.1f} 行、 "
                    f"最初 = 「{_short(first[1], 24)}」 が {first[0]:.1f}pt) = 記入が行を折り返した・増やした"))
    if up:
        mn = min(d for d, _ in up)
        findings["LAYOUT_SHIFT_UP"].append(("pdf", f"様式の字 {len(up)} 行が上にずれた (最大 {-mn:.1f}pt)"))
    ref = ab or allb
    new_alnum = sorted(f for f in af - ref if f)
    new_any = sorted(f for f in allf - allb if f and f not in new_alnum)
    if new_alnum:
        findings["PDF_FONT_NEW"].append(
            ("pdf", f"欧文・数字を描く font {', '.join(new_alnum)} が雛形の紙に無い (雛形 = {', '.join(sorted(ref)) or '-'})"))
    if new_any:
        findings["PDF_FONT_NEW"].append(
            ("pdf", f"font {', '.join(new_any)} が雛形の紙では字を描いていない (雛形 = {', '.join(sorted(allb)) or '-'})"))
    return nf, nb


def render(docx_path, outdir, tag):
    """Word で PDF にする (docx-to-pdf.sh)。 返り値 = (pdf path or None, 理由)。"""
    if sys.platform != "darwin":
        return None, "macOS でない (Word の経路が無い)"
    if not os.path.isdir(WORD_APP):
        return None, "Microsoft Word が無い (Pages / LibreOffice は組み直すので頁数の判定に使わない)"
    if not os.path.isfile(DOCX_TO_PDF):
        return None, f"{DOCX_TO_PDF} が無い"
    out = os.path.join(outdir, f"{tag}.pdf")
    src = os.path.join(outdir, f"{tag}.docx")
    shutil.copyfile(docx_path, src)
    try:
        r = subprocess.run(["bash", DOCX_TO_PDF, src, out], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None, "docx-to-pdf.sh が 300 秒で終わらなかった"
    if r.returncode != 0 or not os.path.isfile(out):
        tail = " / ".join(l for l in (r.stderr or "").strip().splitlines() if l.startswith("❌"))[:300]
        return None, f"docx-to-pdf.sh rc={r.returncode} {tail}"
    return out, ""


UNVERIFIED_LADDER = """\
   見た目 (頁数・行の折れ・紙の font) は未確認 = この様式を本人に見せる・送る段に進まない。 次を上から試す
   (office-automation.md#docx-layout-unverified):
     1. Word が止まった理由を docx-to-pdf.sh の stderr で読み、 直せるなら直してもう一度 (同じ手を 3 回は叩かない)
     2. Word の画面で見る: 写しを project 配下に置き `open -g -a "Microsoft Word" <写し>` → computer-use の
        app_screenshot で状態バーの「1/N ページ」 と各頁を見る (縮小表示で頁の数が分かる)
     3. 本人に Word で PDF に書き出してもらい --filled-pdf / --blank-pdf で渡す
   Pages・LibreOffice の PDF は組み直すので頁数の判定に使わない。"""


# --------------------------------------------------------------------------- #
# receipt (sha256 of the filled file, written only after a pass with the render)
# --------------------------------------------------------------------------- #
def _receipts_path():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "claude-form-layout", "receipts.tsv")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_receipt(filled, blank, pages, status="pass"):
    """1 回の検査を 1 行で記録する。 status = pass (描画つきで通った) / hard / unverified (描けなかった) / no-render。"""
    p = _receipts_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("\t".join([time.strftime("%Y-%m-%dT%H:%M:%S"), _sha256(filled), _sha256(blank),
                            str(pages if pages is not None else "-"), os.path.abspath(filled), status]) + "\n")
    return p


def receipt_lookup(filled):
    """今の中身の記録を引く。 返り値 = {passed, seen_path, status, when, pages, reason}。
    passed = 今の sha256 に pass (描画つきで通った) か not-a-form (様式でないと理由つきで宣言した) の行がある。"""
    p = _receipts_path()
    digest = _sha256(filled)
    path = os.path.abspath(filled)
    out = {"passed": False, "seen_path": False, "status": None, "when": None, "pages": None, "reason": None}
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                if len(f) < 5:
                    continue
                status = f[5] if len(f) >= 6 else "pass"
                if f[1] == digest and status in ("pass", "not-a-form"):
                    out.update(passed=True, status=status, when=f[0], pages=f[3],
                               reason=f[6] if len(f) >= 7 else None)
                out["seen_path"] = out["seen_path"] or (f[4] == path and status != "not-a-form")
    return out


def receipt_status(filled, as_json=False):
    """0 = 今の中身が描画つきで通った (か、 様式でないと宣言済み) / 1 = 通っていない (その path を検査したことがあるかも言う)。"""
    r = receipt_lookup(filled)
    if as_json:
        import json
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r["passed"] else 1
    if r["passed"] and r["status"] == "not-a-form":
        print(f"✓ この file (今の中身) は {r['when']} に様式でないと宣言済み (理由: {r['reason']})")
        return 0
    if r["passed"]:
        print(f"✓ この file (今の中身) は {r['when']} に描画つきで検査済み ({r['pages']} 頁)")
        return 0
    tail = " (この path は検査したことがある = その後に中身が変わったか、 通らなかった)" if r["seen_path"] else ""
    print(f"✗ この file の今の中身は、 描画つきの検査を通っていない{tail} (diff-form-docx.py <記入済み> <雛形> を回す)")
    return 1


def declare_not_a_form(filled, reason):
    """雛形の無い docx (様式でない文書) を、 今の中身に限って理由つきで記録する。 中身が変われば効かない。"""
    reason = " ".join(str(reason or "").split())
    if len(reason) < 4:
        print("--reason に理由を書く (本人が様式でないと言った言葉か、 雛形が無い理由)", file=sys.stderr)
        return 2
    p = _receipts_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("\t".join([time.strftime("%Y-%m-%dT%H:%M:%S"), _sha256(filled), "-", "-",
                            os.path.abspath(filled), "not-a-form", reason]) + "\n")
    print(f"記録: {os.path.basename(filled)} (今の中身) は様式でない — 理由: {reason} ({p})")
    return 0


def _short(v, n=50):
    s = str(v).replace("\n", "⏎")
    return f"{s[:n]}{'…' if len(s) > n else ''}"


HARD = ("LABEL_OVERWRITE", "LABEL_DELETED", "HEADING_VANISHED", "PARA_ADDED", "FONT_MISMATCH",
        "PAGE_ADDED", "LAYOUT_SHIFT", "PDF_FONT_NEW")
SOFT = ("BULLET_EMPTY", "EMPTY_LABELED_COL", "PARA_GREW", "PARA_REMOVED", "LAYOUT_SHIFT_UP", "LABEL_PARTIAL")


def report(findings, strict=False, render_state="skipped", render_note=""):
    hard = soft = 0
    for cls in HARD + SOFT + ("INPUT_FILLED",):
        items = findings[cls]
        if not items:
            continue
        if cls in HARD:
            marker = "❌"
        elif cls == "INPUT_FILLED":
            marker = "ℹ"
        else:
            marker = "⚠"
        print(f"\n{marker} {cls} ({len(items)})")
        for loc, detail in items[:40]:
            print(f"  {loc}: {detail}")
        if len(items) > 40:
            print(f"  … +{len(items) - 40} more")
        if cls in HARD:
            hard += len(items)
        elif cls in SOFT:
            soft += len(items)

    if hard:
        print(f"\n❌ {hard} HARD finding(s):")
        found = {c for c in HARD if findings[c]}
        if found & {"LABEL_OVERWRITE", "LABEL_DELETED", "HEADING_VANISHED"}:
            print("   ラベルセル・見出しは入力欄ではない — 元のラベルを復元し、値は値セル側へ。")
        if "PARA_ADDED" in found:
            print("   記入は雛形の段落・行に書く (自己終了の空段落 <w:p .../> が記入行。 段落の切り方 = scripts/lib/docx_paragraphs.py)。")
        if "FONT_MISMATCH" in found or "PDF_FONT_NEW" in found:
            print("   足した run に雛形の隣の run と同じ <w:rFonts> を付ける (無いと欧文が theme の font で出る)。")
        if found & {"PAGE_ADDED", "LAYOUT_SHIFT"}:
            print("   紙で行が増えた = 記入を縮める (様式の指示の行数に収める) か、 折り返した行を探して直す。 描いた PDF を見る。")
    if soft:
        print(f"\n⚠ {soft} 完成度 finding(s): 空の箇条書き / 全空の列 / 部分改変 / 表の cell の段落の増加 / 段落の減少。")
        print("   意図的空欄 (印・提出日・指導者欄 等) か、記入漏れかを 1 件ずつ確認。")
    if render_state == "done":
        print(f"\n🖨 描画: {render_note}")
    elif render_state == "failed":
        print(f"\n⏸ 描画できなかった: {render_note}")
        print(UNVERIFIED_LADDER)
    else:
        print("\n⚠ 描画は見ていない (--no-render) = 頁数・行の折れ・紙の font は未確認。 見せる・送る前に描画つきで回す。")
    if not hard and not soft:
        print("\n✓ 上書き・見出し消失・段落の増減・字の font・空の箇条書き/列 は検出されませんでした。")
        print("  ⚠ ただし「中身が薄い/箱が半分」 は機械では判定不可 — 審査員の目で最終確認 (描いた PDF を見る)。")

    if hard or (strict and soft):
        return 1
    if render_state == "failed":
        return 3
    return 0


# --------------------------------------------------------------------------- #
# selftest: synthetic blank/filled docx reproducing each 2026-06-27 mistake
# --------------------------------------------------------------------------- #
def _selftest():
    import tempfile as _tf
    from docx import Document as D

    def build(path, kind):
        d = D()
        # cover-like table: r0 ふりがな, r1 氏名|印|年令|歳, ...
        t = d.add_table(rows=2, cols=4)
        t.cell(0, 0).text = "申請者氏名"
        t.cell(0, 2).text = "年\n令"            # age LABEL (the trap)
        t.cell(0, 3).text = "歳"
        t.cell(1, 0).text = "応募課題"
        t.cell(1, 1).text = "第１課題　第２課題　（いずれかを○で）"
        if kind == "blank":
            pass                                 # value cells empty
        elif kind == "good":
            t.cell(0, 1).text = "甲野 太郎"      # name -> value cell (c1) OK
            t.cell(1, 1).text = "○第１課題　第２課題　（いずれかを○で）"  # mark prepended OK
        elif kind == "overwrite":
            t.cell(0, 2).text = "1900.1.1生"     # DOB typed into 年令 LABEL = bug (1)
        # 略歴-like table: header 項目/年月/内容
        t2 = d.add_table(rows=2, cols=3)
        t2.cell(0, 0).text = "項目"
        t2.cell(0, 1).text = "年月"
        t2.cell(0, 2).text = "内容"
        if kind == "good":
            t2.cell(1, 0).text = "学歴"
            t2.cell(1, 1).text = "1990. 3"       # 年月 column filled
            t2.cell(1, 2).text = "甲野大学 卒業"
        elif kind == "emptycol":
            t2.cell(1, 0).text = "学歴"
            t2.cell(1, 2).text = "甲野大学 卒業"  # 年月 (c1) left empty = bug (3)
        # heading + bullet section
        d.add_paragraph("（１）研究者氏名・所属先")
        if kind in ("blank", "emptycol", "overwrite"):
            d.add_paragraph("・")                # empty bullet = bug (2)
            d.add_paragraph("・")
        elif kind == "good":
            d.add_paragraph("・甲野 太郎　甲野大学")
        d.add_paragraph("（５）研究の開始・終了予定年月日")  # heading that must survive
        # a numbered line that is itself the fill line (values go into the blanks)
        d.add_paragraph({"good": "６．生年月日：　1900年1月1日",
                         "overwrite": "６．1900年1月1日"}.get(kind, "６．生年月日：　　　年　　月　　日"))
        d.save(path)

    tmp = _tf.mkdtemp()
    paths = {}
    for k in ("blank", "good", "overwrite", "emptycol"):
        p = os.path.join(tmp, f"{k}.docx")
        build(p, k)
        paths[k] = p
    # vanished: filled good but with (5) heading removed
    vdoc = Document(paths["good"])
    for para in list(vdoc.paragraphs):
        if para.text.startswith("（５）"):
            para._element.getparent().remove(para._element)
    vpath = os.path.join(tmp, "vanished.docx")
    vdoc.save(vpath)
    paths["vanished"] = vpath
    # cellgrow: a second paragraph in a table cell / marked: choice marks put into labels
    cdoc = Document(paths["blank"])
    cdoc.tables[1].cell(1, 2).add_paragraph("甲野大学 修了")
    paths["cellgrow"] = os.path.join(tmp, "cellgrow.docx")
    cdoc.save(paths["cellgrow"])
    mdoc = Document(paths["blank"])
    mdoc.tables[0].cell(1, 1).text = "第１課題　○第２課題　（いずれかを○で）"
    paths["marked"] = os.path.join(tmp, "marked.docx")
    mdoc.save(paths["marked"])

    # a fixed-line form whose 記入行 is a self-closing paragraph; latin text in 明朝
    def raw_form(path, body):
        doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
               'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"><w:body>' + body +
               '<w:sectPr><w:docGrid w:type="lines" w:linePitch="360"/></w:sectPr></w:body></w:document>')
        with zipfile.ZipFile(paths["blank"]) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
            for n in src.namelist():
                dst.writestr(n, doc if n == "word/document.xml" else src.read(n))

    M = '<w:rPr><w:rFonts w:asciiTheme="minorEastAsia" w:hAnsiTheme="minorEastAsia" w:hint="eastAsia"/></w:rPr>'
    head = (f'<w:p w14:paraId="00000001"><w:r>{M}<w:t>１．申請理由 (A4 1 行)</w:t></w:r></w:p>')
    tail = f'<w:p w14:paraId="00000003"><w:r>{M}<w:t>承認欄 No.</w:t></w:r></w:p>'
    line = '<w:p w14:paraId="00000002"/>'
    raw_form(os.path.join(tmp, "fblank.docx"), head + line + tail)
    raw_form(os.path.join(tmp, "fgood.docx"),
             head + f'<w:p w14:paraId="00000002"><w:r>{M}<w:t>架空の理由 ABC</w:t></w:r></w:p>' + tail)
    raw_form(os.path.join(tmp, "fadded.docx"),   # the naive split hid the line → a new paragraph was added
             head + line + f'<w:p w14:paraId="00000009"><w:r>{M}<w:t>架空の理由</w:t></w:r></w:p>' + tail)
    raw_form(os.path.join(tmp, "ffont.docx"),    # run written without w:rFonts → theme Latin font
             head + '<w:p w14:paraId="00000002"><w:r><w:t>架空の理由 ABC</w:t></w:r></w:p>' + tail)
    for k in ("fblank", "fgood", "fadded", "ffont"):
        paths[k] = os.path.join(tmp, f"{k}.docx")

    def has(f, cls, blank="blank", **kw):
        return len(diff_forms(paths[f], paths[blank], **kw)[cls]) > 0

    checks = [
        ("good: no LABEL_OVERWRITE", not has("good", "LABEL_OVERWRITE")),
        ("good: no BULLET_EMPTY", not has("good", "BULLET_EMPTY")),
        ("good: no EMPTY_LABELED_COL", not has("good", "EMPTY_LABELED_COL")),
        ("good: no HEADING_VANISHED (incl. a numbered fill line)", not has("good", "HEADING_VANISHED")),
        ("good: no PARA_ADDED", not has("good", "PARA_ADDED")),
        ("overwrite: LABEL_OVERWRITE detected (年令)", has("overwrite", "LABEL_OVERWRITE")),
        ("overwrite: numbered line lost its label = HEADING_VANISHED", has("overwrite", "HEADING_VANISHED")),
        ("blank: BULLET_EMPTY detected", has("blank", "BULLET_EMPTY")),
        ("emptycol: EMPTY_LABELED_COL detected (年月)", has("emptycol", "EMPTY_LABELED_COL")),
        ("emptycol: BULLET_EMPTY detected", has("emptycol", "BULLET_EMPTY")),
        ("vanished: HEADING_VANISHED detected ((5))", has("vanished", "HEADING_VANISHED")),
        ("vanished: PARA_REMOVED surfaced", has("vanished", "PARA_REMOVED")),
        ("good: INPUT_FILLED present (name)", has("good", "INPUT_FILLED")),
        ("fgood: 記入行に書いた = no PARA_ADDED", not has("fgood", "PARA_ADDED", "fblank")),
        ("fgood: 明朝の run = no FONT_MISMATCH", not has("fgood", "FONT_MISMATCH", "fblank")),
        ("fadded: 段落を足した = PARA_ADDED", has("fadded", "PARA_ADDED", "fblank")),
        ("fadded + --allow-added-paragraphs = surface only",
         not has("fadded", "PARA_ADDED", "fblank", allow_added=True)
         and has("fadded", "PARA_GREW", "fblank", allow_added=True)),
        ("cell: a paragraph added in a table cell = PARA_GREW (surface), not PARA_ADDED",
         has("cellgrow", "PARA_GREW") and not has("cellgrow", "PARA_ADDED")),
        ("cell: a choice mark put into a label (連絡／○面談・□→■) is not LABEL_OVERWRITE",
         not has("marked", "LABEL_OVERWRITE")),
        ("ffont: rFonts の無い欧文 = FONT_MISMATCH", has("ffont", "FONT_MISMATCH", "fblank")),
        ("naive regex hides the 記入行 (the bug this guards)",
         len(re.findall(r"<w:p[ >].*?</w:p>", dp.read_part(paths["fblank"]), re.S)) == 2
         and len(dp.paragraphs(dp.read_part(paths["fblank"]))) == 3),
    ]

    # render checks on synthetic PDFs (no Word): lines, pages, fonts
    try:
        import fitz

        def pdf(path, rows, pages=1, latin_font="helv"):
            doc = fitz.open()
            for pg in range(pages):
                page = doc.new_page(width=595, height=842)
                for i, (txt, font) in enumerate(rows if pg == 0 else [("2", "helv")]):
                    page.insert_text((72, 100 + 18 * i), txt, fontname=font if font else latin_font, fontsize=11)
            doc.save(path)

        bp = os.path.join(tmp, "b.pdf")
        pdf(bp, [("Heading 1", "helv"), ("", "helv"), ("Approval No 7", "helv")])
        same = os.path.join(tmp, "s.pdf")
        pdf(same, [("Heading 1", "helv"), ("fill 123", "helv"), ("Approval No 7", "helv")])
        shifted = os.path.join(tmp, "sh.pdf")
        pdf(shifted, [("Heading 1", "helv"), ("fill 123", "helv"), ("wrapped", "helv"), ("Approval No 7", "helv")])
        twop = os.path.join(tmp, "two.pdf")
        pdf(twop, [("Heading 1", "helv"), ("fill", "helv"), ("Approval No 7", "helv")], pages=2)
        newf = os.path.join(tmp, "nf.pdf")
        pdf(newf, [("Heading 1", "helv"), ("fill 123", "cour"), ("Approval No 7", "helv")])
        newg = os.path.join(tmp, "ng.pdf")   # a new font that draws no letters/digits (marks only)
        pdf(newg, [("Heading 1", "helv"), ("- - -", "cour"), ("Approval No 7", "helv")])

        def pf(f):
            fi = _new_findings()
            check_pdfs(f, bp, fi)
            return fi

        checks += [
            ("pdf same layout: nothing", not any(pf(same)[k] for k in ("PAGE_ADDED", "LAYOUT_SHIFT", "PDF_FONT_NEW"))),
            ("pdf wrap: LAYOUT_SHIFT", bool(pf(shifted)["LAYOUT_SHIFT"])),
            ("pdf 2 pages: PAGE_ADDED", bool(pf(twop)["PAGE_ADDED"])),
            ("pdf new latin font: PDF_FONT_NEW", bool(pf(newf)["PDF_FONT_NEW"])),
            ("pdf new font for marks only: PDF_FONT_NEW", bool(pf(newg)["PDF_FONT_NEW"])),
        ]
    except ImportError:
        print("  SKIP  render checks (PyMuPDF が無い)")

    # report(): exit 3 when the render failed and nothing HARD
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        rc_fail = report(_new_findings(), render_state="failed", render_note="test")
        rc_skip = report(_new_findings(), render_state="skipped")
        hard = _new_findings()
        hard["PARA_ADDED"].append(("body", "x"))
        rc_hard = report(hard, render_state="failed", render_note="test")
    checks += [
        ("render failed + no HARD = exit 3 (未確認)", rc_fail == 3),
        ("--no-render = exit 0", rc_skip == 0),
        ("HARD wins over render failure = exit 1", rc_hard == 1),
    ]
    old = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = tmp
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            before = receipt_status(paths["fgood"])
            write_receipt(paths["fgood"], paths["fblank"], 1)
            after = receipt_status(paths["fgood"])
            write_receipt(paths["fadded"], paths["fblank"], 2, status="hard")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                other = receipt_status(paths["fadded"])
        checks.append(("receipt: unknown → recorded → other file still unknown", (before, after, other) == (1, 0, 1)))
        checks.append(("receipt: a failed run is not a pass, and the path is known", "検査したことがある" in buf.getvalue()))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            short = declare_not_a_form(paths["ffont"], "x")
            decl = declare_not_a_form(paths["ffont"], "雛形の無い送り状 (架空の理由)")
            j = receipt_lookup(paths["ffont"])
        checks.append(("not-a-form: a reason is required, then the current content counts as passed",
                       short == 2 and decl == 0 and j["passed"] and j["status"] == "not-a-form"
                       and not j["seen_path"] and receipt_lookup(paths["fgood"])["status"] == "pass"))
        import shutil as _sh
        _sh.copyfile(paths["fadded"], paths["ffont"])          # the content changed = the declaration no longer applies
        checks.append(("not-a-form: a changed file is not covered", not receipt_lookup(paths["ffont"])["passed"]))
    finally:
        if old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = old

    ok = True
    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'ALL PASS' if ok else 'FAILURES'} ({sum(p for _, p in checks)}/{len(checks)})")
    return 0 if ok else 1


def _opt(args, name):
    if name in args:
        k = args.index(name)
        if k + 1 >= len(args):
            print(f"{name} needs a value", file=sys.stderr)
            sys.exit(2)
        v = args[k + 1]
        del args[k:k + 2]
        return v
    return None


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        sys.exit(_selftest())
    nf = _opt(args, "--not-a-form")
    if nf:
        sys.exit(declare_not_a_form(nf, _opt(args, "--reason")))
    rs = _opt(args, "--receipt-status")
    if rs:
        sys.exit(receipt_status(rs, as_json="--json" in args))
    filled_pdf = _opt(args, "--filled-pdf")
    blank_pdf = _opt(args, "--blank-pdf")
    keep = _opt(args, "--keep-pdf")
    strict = "--strict" in args
    no_render = "--no-render" in args
    allow_added = "--allow-added-paragraphs" in args
    args = [a for a in args if not a.startswith("--")]
    if len(args) != 2 or (bool(filled_pdf) != bool(blank_pdf)):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    filled, blank = args
    findings = diff_forms(filled, blank, allow_added=allow_added)

    state, note, pages = "skipped", "", None
    if filled_pdf:
        nf, nb = check_pdfs(filled_pdf, blank_pdf, findings)
        state, note, pages = "done", f"渡された PDF で照合 (雛形 {nb} 頁 / 記入済み {nf} 頁)", nf
    elif not no_render:
        work = tempfile.mkdtemp(prefix="diff-form-docx-")
        bpdf, why_b = render(blank, work, "blank")
        fpdf, why_f = render(filled, work, "filled") if bpdf else (None, "")
        if bpdf and fpdf:
            nf, nb = check_pdfs(fpdf, bpdf, findings)
            state, pages = "done", nf
            note = f"Word で両方を描いて照合 (雛形 {nb} 頁 / 記入済み {nf} 頁)"
            if keep:
                os.makedirs(keep, exist_ok=True)
                for src, name in ((bpdf, "blank.pdf"), (fpdf, "filled.pdf")):
                    shutil.copyfile(src, os.path.join(keep, name))
                note += f"。 PDF = {os.path.join(keep, 'filled.pdf')} (目で見る)"
        else:
            state, note = "failed", why_b or why_f
        shutil.rmtree(work, ignore_errors=True)
    rc = report(findings, strict=strict, render_state=state, render_note=note)
    status = {0: "pass" if state == "done" else "no-render", 3: "unverified"}.get(rc, "hard")
    try:
        p = write_receipt(filled, blank, pages, status=status)
        if status == "pass":
            print(f"  記録: {p}")
    except OSError as e:  # 記録できなくても検査の結果は変えない
        print(f"  (記録を書けなかった: {e})", file=sys.stderr)
    sys.exit(rc)


if __name__ == "__main__":
    main()
