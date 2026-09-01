#!/usr/bin/env python3
r"""inspire-bib-audit.py — refs.bib の entry を INSPIRE-HEP と照合する gate（texkey ごとに title / 第一著者 / 誌名 / 巻 / 初頁 / DOI / eprint を突合し、捏造 DOI・DOI typo・content swap・非正規 texkey を検出。TeX 記法 ↔ Unicode・誌名の略記ゆれ・巻の系列文字・再録は正規化して偽陽性にしない、INSPIRE 未収録は SKIP、network 失敗は exit 2、--selftest 内蔵、conventions/paper-audit.md）

Audit a BibTeX file against INSPIRE-HEP.

WHY THIS EXISTS
---------------
Per-project ``refs.bib`` files are written by hand or pasted from mixed sources,
and generated entries are fluent enough to pass a human read while being wrong.
A single audit of one such file (2026-07-15) turned up four distinct error
classes at once:

    fabricated DOI      a DOI that resolves to nothing, or to another paper
    DOI typo            one character off, so it silently resolves elsewhere
    content swap        right texkey, wrong title/journal/volume attached
    non-canonical key   a key INSPIRE does not use, so cross-file cites drift

This script turns that manual recipe into a gate.  For every entry carrying a
texkey that INSPIRE recognizes, it fetches the INSPIRE record and compares the
fields that identify the work: title, first author surname, journal, volume,
first page, DOI, and arXiv eprint.

WHAT IT DOES NOT DO
-------------------
It checks *identity*, not *relevance* -- whether the cited work actually
supports the sentence citing it is a human judgment (and the failure mode that
motivated this file's sibling discipline: a correctly-cited paper can still be
mischaracterized in prose).  Entries with no INSPIRE record (books, theses,
private notes) are reported as SKIP, not as findings; INSPIRE is not a complete
index of the literature.  Page ranges are compared on the first page only,
since giving just the start page is standard practice.

Run:
    python3 inspire-bib-audit.py path/to/refs.bib
    python3 inspire-bib-audit.py path/to/refs.bib --key Elitzur:1975im
    python3 inspire-bib-audit.py --selftest        # offline, no network

Exit status is 1 if any MISMATCH was found, else 0 (SKIP alone is not a
failure).  Network errors are reported and exit 2, so a silent network outage
cannot be mistaken for a clean audit.
"""
import argparse
import json
import re
import unicodedata
import urllib.parse
import urllib.request

INSPIRE = "https://inspirehep.net/api/literature"
FIELDS = "texkeys,titles,authors,publication_info,dois,arxiv_eprints"
TIMEOUT = 30

# Fields compared, in report order.  Each is (label, bib keys, extractor).
_NORM_WS = re.compile(r"\s+")
# Commands become a space (they separated words); braces and stray escapes are
# deleted outright, since a group boundary is not a word boundary -- replacing
# the brace of ``Poincar{e`` with a space would split the word in two.
_STRIP_TEX_CMD = re.compile(r"\\[a-zA-Z]+")
_STRIP_TEX_CHR = re.compile(r"[{}\\$]")
# TeX accents, so that \'e and e-acute compare equal: the symbolic forms
# (\'e, \"o, \~n) and the named ones (\c{c}, \v{s}, \H{o}) both reduce to
# their base letter before the generic brace/escape strip runs.
_TEX_ACCENT_SYM = re.compile(r"\\[`'^\"~=.]\s*\{?([A-Za-z])\}?")
_TEX_ACCENT_CMD = re.compile(r"\\[cvuHkrdbt]\{([A-Za-z])\}")
# TeX text commands that stand for a character, not for markup.
_TEX_TEXT = {
    r"\\textendash": "-", r"\\textemdash": "-", r"\\textquoteright": "'",
    r"\\textquoteleft": "'", r"\\textquotedblleft": '"', r"\\textquotedblright": '"',
    r"\\&": "&", r"\\ss": "ss",
}
_ALNUM = re.compile(r"[^a-z0-9]")
_LEADING_ALPHA = re.compile(r"^([a-z]+)")


def norm(text):
    """Loose comparison form.

    TeX braces and escapes out, diacritics folded, quotes and dashes unified,
    whitespace and case flat.  The diacritic fold is what keeps a TeX-encoded
    ``Poincar{\'e}`` from being reported against INSPIRE's ``Poincare``-with-
    accent; both are the same name, differently encoded.
    """
    if text is None:
        return ""
    text = str(text)
    for cmd, ch in _TEX_TEXT.items():
        text = re.sub(cmd + r"\s*\{?\}?", ch, text)
    text = _TEX_ACCENT_SYM.sub(r"\1", text)
    text = _TEX_ACCENT_CMD.sub(r"\1", text)
    text = _STRIP_TEX_CMD.sub(" ", text)
    text = _STRIP_TEX_CHR.sub("", text)
    text = text.replace("--", "-").replace("–", "-").replace("’", "'")
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    return _NORM_WS.sub(" ", text).strip().lower()


def parse_bib(path):
    """Minimal BibTeX reader: entry type, key, and brace/quote-delimited fields.

    Deliberately not a full parser -- it only needs the identifying fields, and
    a hand-rolled reader keeps this script dependency-free.
    """
    raw = open(path, encoding="utf-8", errors="replace").read()
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", raw):
        etype, key = m.group(1).lower(), m.group(2)
        i, depth = m.end(), 1
        while i < len(raw) and depth:
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
            i += 1
        body = raw[m.end():i - 1]
        fields = {}
        for fm in re.finditer(r'(\w+)\s*=\s*(\{|")', body):
            name = fm.group(1).lower()
            opener = fm.group(2)
            j = fm.end()
            if opener == "{":
                d = 1
                start = j
                while j < len(body) and d:
                    if body[j] == "{":
                        d += 1
                    elif body[j] == "}":
                        d -= 1
                    j += 1
                fields[name] = body[start:j - 1]
            else:
                start = j
                j = body.find('"', start)
                fields[name] = body[start:j if j > 0 else len(body)]
        entries.append({"type": etype, "key": key, "fields": fields})
    return entries


def fetch(key):
    """Return the INSPIRE metadata dict for a texkey, or None if unknown."""
    q = urllib.parse.quote(f'texkeys:"{key}"')
    url = f"{INSPIRE}?q={q}&fields={FIELDS}&size=1"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as fh:
        data = json.load(fh)
    hits = data.get("hits", {}).get("hits", [])
    return hits[0]["metadata"] if hits else None


def first_page(pages):
    if not pages:
        return ""
    return re.split(r"-{1,3}", str(pages).strip())[0].strip()


def compare(entry, meta):
    """Yield (field, bib value, inspire value) for each disagreement."""
    f = entry["fields"]

    bib_title = f.get("title", "")
    ins_titles = [t.get("title", "") for t in (meta.get("titles") or [{}])]
    ins_title = ins_titles[0] if ins_titles else ""
    if bib_title and ins_title:
        # Punctuation carries no identity here: "One loop" vs "One-loop" and
        # an en dash written as {\textendash} are the same title.  A record
        # that stores the subtitle separately shows up as a prefix, not a
        # disagreement.
        b = _ALNUM.sub("", norm(bib_title))
        cands = [_ALNUM.sub("", norm(t)) for t in ins_titles if t]
        if not any(b == c or b.startswith(c) or c.startswith(b) for c in cands):
            yield "title", bib_title, ins_title

    bib_author = f.get("author", "")
    if bib_author:
        surname = norm(re.split(r",| and ", bib_author)[0]).split()[-1:] or [""]
        ins_authors = [norm(a.get("full_name", "")) for a in meta.get("authors", [])]
        if surname[0] and not any(surname[0] in a for a in ins_authors):
            yield "author", bib_author, "; ".join(ins_authors[:3])

    pubs = meta.get("publication_info") or [{}]
    pub = next((p for p in pubs if p.get("journal_title")), pubs[0])
    # Journal abbreviations vary wildly between sources ("Front. Phys." vs
    # "Front.in Phys.", "Nucl. Phys." + volume "B417" vs "Nucl.Phys.B" + "417"),
    # so the journal is checked only on its first word -- enough to catch a
    # gross swap, loose enough not to cry wolf on house style.  The series
    # letter is moved out of the volume before the volumes are compared.
    # Records with reprints carry several publication_info entries; agreement
    # with any one of them is agreement (the bib may cite either printing).
    def first_word(v):
        toks = [t for t in re.split(r"[^a-z0-9]+", norm(v)) if t]
        return toks[0] if toks else ""

    def volume_number(vol):
        v = _ALNUM.sub("", norm(vol))
        m = _LEADING_ALPHA.match(v)
        return (v[m.end():] if m else v).lstrip("0")

    checks = (
        ("journal", "journal", "journal_title", first_word),
        ("volume", "volume", "journal_volume", volume_number),
        ("pages", "pages", "page_start", lambda v: norm(first_page(v)).lstrip("0")),
    )

    def diffs_against(p):
        out = []
        for label, bibkey, inskey, getter in checks:
            bv, iv = f.get(bibkey), p.get(inskey)
            if bv and iv and getter(bv) != getter(iv):
                out.append((label, bv, iv))
        return out

    # Report against the printing that agrees best, and only on the fields that
    # actually disagree there -- listing fields that match would bury the signal.
    best = min((diffs_against(p) for p in pubs), key=len, default=[])
    for item in best:
        yield item

    bib_doi = norm(f.get("doi", ""))
    ins_dois = [norm(d.get("value", "")) for d in meta.get("dois", [])]
    if bib_doi and ins_dois and bib_doi not in ins_dois:
        yield "doi", f.get("doi"), ", ".join(dict.fromkeys(ins_dois))

    bib_eprint = norm(f.get("eprint", "")).replace("arxiv:", "")
    ins_eprints = [norm(e.get("value", "")) for e in meta.get("arxiv_eprints", [])]
    if bib_eprint and ins_eprints and bib_eprint not in ins_eprints:
        yield "eprint", f.get("eprint"), ", ".join(ins_eprints)


def audit(path, only=None):
    entries = parse_bib(path)
    if only:
        entries = [e for e in entries if e["key"] in only]
    findings = skipped = 0
    for entry in entries:
        key = entry["key"]
        try:
            meta = fetch(key)
        except Exception as exc:                      # network / API failure
            print(f"[ERROR] {key}: {exc}")
            return 2
        if meta is None:
            print(f"[SKIP ] {key}: no INSPIRE record for this texkey")
            skipped += 1
            continue
        diffs = list(compare(entry, meta))
        if not diffs:
            print(f"[OK   ] {key}")
            continue
        findings += 1
        print(f"[MISMATCH] {key}")
        for field, bib_value, ins_value in diffs:
            print(f"           {field}: bib={bib_value!r}")
            print(f"           {' ' * len(field)}  inspire={ins_value!r}")
    print(f"\n{len(entries)} entries -- {findings} mismatch, {skipped} skipped")
    return 1 if findings else 0


def selftest():
    """Offline: exercise the parser and the comparator on synthetic records."""
    import tempfile
    import os

    bib = """
@article{Good:1975im,
  author = "Elitzur, S.",
  title = "{Impossibility of Spontaneously Breaking Local Symmetries}",
  journal = "Phys. Rev. D", volume = "12", pages = "3978", year = "1975",
  doi = "10.1103/PhysRevD.12.3978"
}
@article{BadDoi:1975im,
  author = "Elitzur, S.", title = "{Impossibility of Spontaneously Breaking Local Symmetries}",
  journal = "Phys. Rev. D", volume = "12", pages = "3978", doi = "10.1103/PhysRevD.12.3979"
}
@inbook{Swap:2018xdo,
  author = "Chaichian, Masud", title = "{A different paper entirely}",
  pages = "271--299", doi = "10.1142/9789811203961_0021"
}
"""
    meta = {
        "titles": [{"title": "Impossibility of Spontaneously Breaking Local Symmetries"}],
        "authors": [{"full_name": "Elitzur, S."}],
        "publication_info": [{"journal_title": "Phys.Rev.D", "journal_volume": "12",
                              "page_start": "3978", "page_end": "3982"}],
        "dois": [{"value": "10.1103/PhysRevD.12.3978"}],
        "arxiv_eprints": [],
    }
    fd, path = tempfile.mkstemp(suffix=".bib")
    os.write(fd, bib.encode())
    os.close(fd)
    entries = {e["key"]: e for e in parse_bib(path)}
    os.unlink(path)

    ok = True

    def chk(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")

    chk("parser reads all three entries", len(entries) == 3)
    chk("parser keeps the entry type", entries["Swap:2018xdo"]["type"] == "inbook")
    chk("clean entry has no diff", not list(compare(entries["Good:1975im"], meta)))
    chk("journal abbreviation difference is not a finding",   # 'Phys. Rev. D' vs 'Phys.Rev.D'
        not any(d[0] == "journal" for d in compare(entries["Good:1975im"], meta)))
    chk("page range vs first page is not a finding",
        not any(d[0] == "pages" for d in compare(entries["Good:1975im"], meta)))
    doi_diffs = [d for d in compare(entries["BadDoi:1975im"], meta) if d[0] == "doi"]
    chk("foil: one-character DOI typo is caught", len(doi_diffs) == 1)
    swap_diffs = [d[0] for d in compare(entries["Swap:2018xdo"], meta)]
    chk("foil: content swap is caught on the title", "title" in swap_diffs)
    chk("foil: swapped entry also flags its DOI against the wrong record",
        "doi" in swap_diffs)
    accent_meta = dict(meta, titles=[{"title": "Sakharov’s Induced Gravity and the Poincaré Gauge Theory"}])
    accent_entry = {"fields": {"title": "{Sakharov's Induced Gravity and the Poincar{\\'e} Gauge Theory}"}}
    chk("TeX accent vs Unicode accent is not a finding",
        not any(d[0] == "title" for d in compare(accent_entry, accent_meta)))
    print("\nALL PASS" if ok else "\nFAILURES PRESENT")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bib", nargs="?", help="path to a .bib file")
    ap.add_argument("--key", action="append", help="audit only this texkey (repeatable)")
    ap.add_argument("--selftest", action="store_true", help="offline parser/comparator test")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.bib:
        ap.error("give a .bib path, or --selftest")
    return audit(args.bib, only=set(args.key) if args.key else None)


if __name__ == "__main__":
    raise SystemExit(main())
