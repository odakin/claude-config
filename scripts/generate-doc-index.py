#!/usr/bin/env python3
"""generate-doc-index.py -- regenerate a slug index FROM its markdown, so Claude writes
ONLY markdown and the index keeps itself in sync (write-ease is the priority).

For a slug-anchored convention doc (each `##`/`###` heading carries `<a id="slug"></a>`),
this scans the md and (re)writes `<doc>.index.yaml`:
  DERIVED from the md   : id (the anchor slug), level (## / ###), title (verbatim heading).
  PRESERVED across regen : legacy  (a section's ORIGINAL §-number = a permanent forwarding
                                   address for old `§N.M` refs; FROZEN once set --
                                   convention-design-principles.md §14.7),
                          related (the hand-authored relation graph),
                          and ANY other hand field (e.g. origin) -- preserved verbatim, so
                          the generator never silently drops data it does not understand.
A NEW section (slug not yet in the index) freezes its legacy from its current heading
§-number, if it has one. Sections ALREADY in the index keep their legacy EXACTLY (a leading
digit in a doc that dropped its numbers is not a §-number, so it is never re-derived).

Workflow:  edit markdown (prose + the `<a id>` anchor)  ->  run this  ->  index syncs.
Pair with check-office-automation-index.py to verify (dangling/orphan 0).

⚠️ The title is taken VERBATIM from the heading. A doc whose existing index uses a DIFFERENT
title convention (e.g. office-automation.md hand-strips leading ⚠️ / backticks) will not
round-trip identically -- such a doc is hand-maintained, do not auto-regenerate it. Docs
built to this convention (verbatim title) round-trip with zero content diff.

Surfaces (does NOT auto-fix) two review-worthy conditions:
  * a `##`/`###` heading with NO `<a id>` anchor (un-referenceable -- add one),
  * a slug in the OLD index but GONE from the md (rename/delete that would orphan a legacy
    forwarding entry -- §14.7 'legacy is append-only': confirm before committing).

Generic + public-safe. Usage:
  generate-doc-index.py <doc.md> <doc.index.yaml>            # write the index
  generate-doc-index.py <doc.md> <doc.index.yaml> --check    # don't write; exit 1 if out of sync
"""
import re
import sys
import argparse
from pathlib import Path

# slug-ification anchors only level-2/3 headings (level-4 #### are intentionally skipped).
SLUG_RE = re.compile(r'^(#{2,3})\s+<a id="([a-z0-9][a-z0-9-]*)"></a>\s*(.*)$')
PLAIN_RE = re.compile(r'^(#{2,3})\s+(?!<a id=)(\S.*)$')
SEC_NUM_RE = re.compile(r'^(\d+(?:[.\-]\d+)*[a-z]?)\b')
DERIVED = {"id", "level", "title"}  # always rebuilt from the md, never preserved


def parse_existing(index_text):
    """slug -> {'legacy': str|None, 'related': [..], 'extras': [(key, rawval), ..]}.
    Any field that is not derived and not legacy/related is preserved verbatim (extras)."""
    out, cur = {}, None
    for raw in index_text.split("\n"):
        m = re.match(r"\s*-\s+id:\s*(.+)$", raw)
        if m:
            cur = m.group(1).strip()
            out[cur] = {"legacy": None, "related": [], "extras": []}
            continue
        if cur is None:
            continue
        m = re.match(r"\s+(\w+):\s*(.*)$", raw)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if k in DERIVED:
            continue
        if k == "legacy":
            out[cur]["legacy"] = v.strip('"')
        elif k == "related":
            out[cur]["related"] = [x.strip() for x in v.strip("[]").split(",") if x.strip()]
        else:
            out[cur]["extras"].append((k, v))  # e.g. origin -- preserve verbatim
    return out


def scan_md(md_text):
    """document-order [(slug, level, title, cur_num)], plus [(lineno, heading)] missing an anchor."""
    sections, missing = [], []
    in_fence = False
    for ln, line in enumerate(md_text.split("\n"), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = SLUG_RE.match(line)
        if m:
            title = m.group(3).strip()
            nm = SEC_NUM_RE.match(title)
            sections.append((m.group(2), len(m.group(1)), title, nm.group(1) if nm else None))
            continue
        m = PLAIN_RE.match(line)
        if m:
            missing.append((ln, m.group(2).strip()))
    return sections, missing


def build_index(sections, existing):
    out = [
        "# Stable slug index -- AUTO-GENERATED from the doc by scripts/generate-doc-index.py.",
        "# id/level/title are DERIVED from the markdown (edit the md + re-run, do NOT hand-edit",
        "# them here). legacy (a section's original §-number = a permanent forwarding address),",
        "# related, and any other hand field are PRESERVED. See convention-design-principles §14.7.",
        "# Validated by scripts/check-office-automation-index.py (dangling=0 / orphan=0).",
        "sections:",
    ]
    seen = set()
    for slug, level, title, cur_num in sections:
        prev = existing.get(slug)
        if prev is not None:
            legacy, related, extras = prev["legacy"], prev["related"], prev["extras"]
        else:
            legacy, related, extras = cur_num, [], []   # new section freezes its current §-number
        seen.add(slug)
        out.append("  - id: %s" % slug)
        if legacy:
            out.append('    legacy: "%s"' % legacy)
        out.append("    level: %d" % level)
        out.append('    title: "%s"' % title.replace("\\", "\\\\").replace('"', '\\"'))
        if related:
            out.append("    related: [%s]" % ", ".join(related))
        for k, v in extras:
            out.append("    %s: %s" % (k, v))
    vanished = [s for s in existing if s not in seen]
    return "\n".join(out) + "\n", vanished


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("index")
    ap.add_argument("--check", action="store_true", help="don't write; exit 1 if out of sync")
    a = ap.parse_args()
    doc_p, idx_p = Path(a.doc), Path(a.index)

    md = doc_p.read_text(encoding="utf-8")
    existing = parse_existing(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else {}
    sections, missing = scan_md(md)
    new_index, vanished = build_index(sections, existing)

    for ln, h in missing:
        print("  WARN  %s:%d heading has no <a id> anchor: %s" % (doc_p.name, ln, h[:60]))
    for slug in vanished:
        leg = existing[slug].get("legacy", "")
        print("  WARN  slug '%s' (legacy %s) is in the index but GONE from the md "
              "(rename/delete? a vanished legacy orphans old §-refs -- §14.7 append-only)."
              % (slug, leg or "-"))

    cur = idx_p.read_text(encoding="utf-8") if idx_p.exists() else ""
    if a.check:
        if cur.rstrip("\n") != new_index.rstrip("\n"):
            print("❌ %s OUT OF SYNC with %s -- run generate-doc-index.py" % (idx_p.name, doc_p.name))
            return 1
        print("✅ %s in sync (%d sections)" % (idx_p.name, len(sections)))
        return 0
    idx_p.write_text(new_index, encoding="utf-8")
    print("✅ wrote %s: %d sections (%d missing-anchor / %d vanished-slug warnings)"
          % (idx_p.name, len(sections), len(missing), len(vanished)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
