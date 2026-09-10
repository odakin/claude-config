#!/usr/bin/env python3
"""Audit a LaTeX log and PDF, and optionally render numbered pages for visual review.

Usage:
  python3 latex-pdf-audit.py paper.pdf --log paper.log --source paper.tex --json
  python3 latex-pdf-audit.py paper.pdf --log paper.log --report review.json
  python3 latex-pdf-audit.py paper.pdf --log paper.log --render-dir review --pages 2,4-6
  python3 latex-pdf-audit.py --selftest

Requires PyMuPDF for PDF inspection/rendering. This tool does not compile or
modify the input files. It scans the entire supplied log and every PDF font
resource. Missing inputs, unreadable PDFs or unavailable dependencies fail
explicitly. --source is repeatable and checks mtime only, not build provenance.
Record hashes identify the inspected bytes; they do not prove correspondence.

Exit 0: no blocking finding in the inspected scope; visual_review is still
"required". Exit 1: TeX error, undefined reference/citation, missing glyph,
incomplete log, pending rerun, stale PDF, unexpected page count or Type 3 font.
Overfull boxes are reported but block only with --strict-overfull.
Exit 2: invalid arguments or unavailable/unreadable input.

Rendering writes new PNGs only; existing targets are rejected. --pages uses
one-based inclusive ranges. No claim of visual correctness is made by a scan.
The operating procedure is conventions/latex.md#latex-pdf-audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_log(text):
    findings = {key: [] for key in ("tex_errors", "undefined", "missing_glyphs", "overfull")}
    for number, line in enumerate(text.splitlines(), 1):
        item = {"log_line": number, "text": line}
        file_line = re.match(r"^.+\.(?:tex|sty|cls|bib|bbl|aux|def|clo):\d+:\s*(.*)", line)
        if line.startswith("!") or (file_line and "Warning" not in file_line.group(1)):
            findings["tex_errors"].append(item)
        if "undefined" in line.lower() and ("Warning" in line or "undefined on input" in line):
            findings["undefined"].append(item)
        if line.startswith("Missing character:"):
            findings["missing_glyphs"].append(item)
        if re.search(r"Overfull \\[hv]box", line):
            findings["overfull"].append(item)
    findings["completed_pdf_run"] = bool(re.search(r"Output written on .+\.pdf\b", text))
    findings["rerun_required"] = bool(re.search(
        r"Label\(s\) may have changed|Rerun to get|Rerun to get outlines", text
    ))
    return findings


def selected_pages(value, count):
    if value is None:
        return list(range(1, count + 1))
    pages = set()
    for group in value.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", group)
        if not match:
            raise ValueError("Pages must be comma-separated numbers or ranges, for example 2,4-6.")
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= count:
            raise ValueError(f"Page range outside 1..{count}: {group}")
        pages.update(range(first, last + 1))
    return sorted(pages)


def inspect_pdf(pdf, log, sources=(), expected_pages=None, strict_overfull=False):
    import fitz

    log_text = log.read_text(encoding="utf-8", errors="replace")
    findings = scan_log(log_text)
    fonts = {}
    with fitz.open(pdf) as document:
        if document.needs_pass:
            raise ValueError("Encrypted PDF requires an unlocked input.")
        page_count = document.page_count
        for number, page in enumerate(document, 1):
            for font in page.get_fonts(full=True):
                xref, _, kind, name = font[:4]
                entry = fonts.setdefault((xref, kind, name), {
                    "xref": xref, "type": kind, "name": name, "pages": [],
                })
                if number not in entry["pages"]:
                    entry["pages"].append(number)
    stale = [str(source) for source in sources if source.stat().st_mtime > pdf.stat().st_mtime]
    failures = [key for key in ("tex_errors", "undefined", "missing_glyphs") if findings[key]]
    if not findings["completed_pdf_run"]:
        failures.append("incomplete_log")
    if findings["rerun_required"]:
        failures.append("rerun_required")
    if any(font["type"] == "Type3" for font in fonts.values()):
        failures.append("type3_fonts")
    if stale:
        failures.append("sources_newer_than_pdf")
    if expected_pages is not None and page_count != expected_pages:
        failures.append("unexpected_page_count")
    if strict_overfull and findings["overfull"]:
        failures.append("overfull")
    return {
        "schema_version": 1,
        "inputs": {
            "pdf": {"name": pdf.name, "sha256": digest(pdf)},
            "log": {"name": log.name, "sha256": digest(log)},
            "sources": [{"name": s.name, "sha256": digest(s)} for s in sources],
        },
        "page_count": page_count,
        "fonts": list(fonts.values()),
        "log_findings": findings,
        "sources_newer_than_pdf": stale,
        "blocking_findings": failures,
        "visual_review": "required",
        "limits": (
            "Log diagnostics and all PDF font resources only. A successful scan "
            "does not verify clipping, overlaps, scientific correctness or build provenance. "
            "Source freshness uses only explicitly supplied files and mtimes."
        ),
    }


def render(pdf, directory, pages, dpi):
    import fitz

    if dpi <= 0:
        raise ValueError("DPI must be positive.")
    with fitz.open(pdf) as document:
        selected = selected_pages(pages, document.page_count)
        outputs = [directory / f"page-{number:03d}.png" for number in selected]
        if any(path.exists() for path in outputs):
            raise ValueError("Render targets already exist; use a fresh directory.")
        directory.mkdir(parents=True, exist_ok=True)
        for number, path in zip(selected, outputs):
            document[number - 1].get_pixmap(dpi=dpi, alpha=False).save(path)
    return [str(path) for path in outputs]


def selftest():
    # Diagnostics use deliberately synthetic text, never a project's real log.
    sample = (
        "! Missing $ inserted.\n"
        "./paper.tex:8: Undefined control sequence.\n"
        "./paper.tex:9: LaTeX Warning: Citation 'sample' undefined on input line 9.\n"
        "Missing character: There is no X in font nullfont!\n"
        "Overfull \\hbox (4.0pt too wide) in paragraph at lines 8--9\n"
        "Output written on paper.pdf (1 page, 100 bytes).\n"
    )
    result = scan_log(sample)
    assert len(result["tex_errors"]) == 2
    assert len(result["undefined"]) == len(result["missing_glyphs"]) == len(result["overfull"]) == 1
    assert result["completed_pdf_run"]
    assert not scan_log("")["completed_pdf_run"]
    assert scan_log("LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.")["rerun_required"]
    assert selected_pages("3,1-2,2", 3) == [1, 2, 3]
    for bad in ("0", "4", "3-1", "all", ""):
        try:
            selected_pages(bad, 3)
            raise AssertionError(f"Accepted invalid page range {bad!r}")
        except ValueError:
            pass
    import fitz
    with tempfile.TemporaryDirectory(prefix="latex-pdf-audit-") as folder:
        root = Path(folder)
        pdf, log = root / "paper.pdf", root / "paper.log"
        with fitz.open() as document:
            document.new_page().insert_text((60, 60), "Synthetic audit fixture")
            document.save(pdf)
        log.write_text("Output written on paper.pdf (1 page, 100 bytes).\n", encoding="utf-8")
        report = inspect_pdf(pdf, log, expected_pages=1)
        assert not report["blocking_findings"] and report["visual_review"] == "required"
        assert inspect_pdf(pdf, log, expected_pages=2)["blocking_findings"] == ["unexpected_page_count"]
        source = root / "paper.tex"
        source.write_text("Synthetic source", encoding="utf-8")
        stamp = pdf.stat().st_mtime + 10
        os.utime(source, (stamp, stamp))
        assert "sources_newer_than_pdf" in inspect_pdf(pdf, log, [source])["blocking_findings"]
        # A minimal synthetic Type 3 resource exercises the font-class gate.
        type3 = root / "type3.pdf"
        with fitz.open(pdf) as document:
            font_xref = document[0].get_fonts()[0][0]
            document.xref_set_key(font_xref, "Subtype", "/Type3")
            document.save(type3)
        assert "type3_fonts" in inspect_pdf(type3, log)["blocking_findings"]
        log.write_text(sample, encoding="utf-8")
        report = inspect_pdf(pdf, log, strict_overfull=True)
        assert {"tex_errors", "undefined", "missing_glyphs", "overfull"} <= set(report["blocking_findings"])
        outputs = render(pdf, root / "pages", "1", 60)
        assert Path(outputs[0]).stat().st_size > 0
        try:
            render(pdf, root / "pages", "1", 60)
            raise AssertionError("Existing output was overwritten")
        except ValueError:
            pass
    print("Selftest: diagnostic rejection, incomplete runs, page selection, PDF scan and rendering checked.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, nargs="?")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--source", action="append", type=Path, default=[])
    parser.add_argument("--expect-pages", type=int)
    parser.add_argument("--strict-overfull", action="store_true")
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--pages")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", type=Path, help="Write the generated audit JSON.")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    try:
        if args.selftest:
            selftest()
            return 0
        if args.pdf is None or args.log is None:
            parser.error("pdf and --log are required unless --selftest is used")
        if args.pages is not None and args.render_dir is None:
            parser.error("--pages requires --render-dir")
        report = inspect_pdf(args.pdf, args.log, args.source, args.expect_pages, args.strict_overfull)
        if args.report and args.report.resolve() in {
            path.resolve() for path in [args.pdf, args.log, *args.source]
        }:
            raise ValueError("The report path must not overwrite an input.")
        if args.render_dir:
            report["rendered_pages"] = render(args.pdf, args.render_dir, args.pages, args.dpi)
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Pages: {report['page_count']}; unique font resources: {len(report['fonts'])}")
            for key in ("tex_errors", "undefined", "missing_glyphs", "overfull"):
                print(f"{key}: {len(report['log_findings'][key])}")
            print("Blocking findings: " + (", ".join(report["blocking_findings"]) or "none in inspected scope"))
            print("Visual review: required")
            for path in report.get("rendered_pages", []):
                print(path)
        return int(bool(report["blocking_findings"]))
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"latex-pdf-audit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
