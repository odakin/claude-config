#!/usr/bin/env python3
"""generate-doc-index.py -- regenerate a slug index FROM its markdown, so Claude writes
ONLY markdown and the index keeps itself in sync (write-ease is the priority).

For a slug-anchored convention doc (each `##`/`###` heading carries `<a id="slug"></a>`),
this scans the md and (re)writes `<doc>.index.yaml`:
  DERIVED from the md   : id (the anchor slug), level (## / ###), title (verbatim heading).
  PRESERVED across regen : legacy  (a section's ORIGINAL §-number = a permanent forwarding
                                   address for old `§N.M` refs; FROZEN once set --
                                   convention-design-principles.md §14.7 〔= #inbound-ref-robustness〕),
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
  generate-doc-index.py --check-all [repo_root]               # verify EVERY auto-generated index
                                                              # (files whose head says AUTO-GENERATED;
                                                              #  hand-maintained indexes are skipped)
  generate-doc-index.py --selftest                            # in-memory regression fixtures
"""
import re
import sys
import argparse
from pathlib import Path


def _force_utf8_stdio():
    """Force UTF-8 stdout/stderr.

    Windows consoles default to a legacy code page (e.g. cp932 on Japanese
    Windows) that cannot encode the status emoji printed below, raising
    UnicodeEncodeError mid-run. macOS/Linux already default to UTF-8 so this
    is a no-op there, as it is where a stream has no reconfigure()."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


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
        "# related, and any other hand field are PRESERVED. See convention-design-principles §14.7 (= #inbound-ref-robustness).",
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


def selftest():
    """Exercise the pure helpers in-memory: round-trip preservation of legacy / related /
    extras, derivation of id/level/title, NEW-section legacy freezing, code-fence skipping,
    and the missing-anchor / vanished-slug WARN surfaces."""
    ok = True

    # --- fixture md: covers derived, preserved, new-section, code-fence, missing-anchor ---
    md = (
        '## <a id="alpha"></a>Alpha heading\n'
        'body\n'
        '### <a id="beta"></a>Beta heading\n'
        '### 8.12 No-anchor heading\n'           # PLAIN level-3: missing-anchor WARN
        '### <a id="gamma"></a>8.12 New section gamma\n'  # NEW slug, leading §-number
        '### <a id="delta"></a>Plain-titled delta\n'      # NEW slug, NO leading number
        '```\n'
        '### <a id="fenced"></a>Fenced heading should be ignored\n'  # CODE FENCE
        '```\n'
        '#### <a id="too-deep"></a>level-4 also ignored\n'           # level-4 not slug-anchored
    )
    # --- fixture existing index: alpha+beta have legacy/related/extras to preserve; epsilon
    #     is in the index but vanished from the md -> vanished-slug WARN ---
    existing_yaml = (
        "sections:\n"
        '  - id: alpha\n'
        '    legacy: "1"\n'
        '    level: 2\n'
        '    title: "Alpha heading"\n'
        '    related: [beta]\n'
        '    origin: hand-authored\n'              # EXTRA -- must survive verbatim
        '  - id: beta\n'
        '    legacy: "2-5b"\n'
        '    level: 3\n'
        '    title: "Beta heading"\n'
        '    related: [alpha, gamma]\n'
        '  - id: epsilon\n'                         # VANISHED -- not in md
        '    legacy: "9"\n'
        '    level: 3\n'
        '    title: "Gone"\n'
    )

    existing = parse_existing(existing_yaml)
    if existing.get("alpha", {}).get("legacy") != "1":
        print("  selftest MISS: legacy '1' for alpha not parsed"); ok = False
    if existing.get("beta", {}).get("related") != ["alpha", "gamma"]:
        print("  selftest MISS: related for beta not parsed"); ok = False
    if ("origin", "hand-authored") not in existing.get("alpha", {}).get("extras", []):
        print("  selftest MISS: extra 'origin' for alpha not preserved by parser"); ok = False

    sections, missing = scan_md(md)
    slugs = [s[0] for s in sections]
    if slugs != ["alpha", "beta", "gamma", "delta"]:
        print("  selftest MISS: scan_md slug order: %s" % slugs); ok = False
    # level: alpha is ##, others are ###
    levels = {s: lvl for s, lvl, _, _ in sections}
    if levels.get("alpha") != 2 or levels.get("beta") != 3:
        print("  selftest MISS: level not derived"); ok = False
    # title: verbatim, including the "8.12 " prefix on gamma
    title_gamma = [t for s, _, t, _ in sections if s == "gamma"][0]
    if title_gamma != "8.12 New section gamma":
        print("  selftest MISS: gamma title not verbatim: %r" % title_gamma); ok = False
    # NEW-section legacy: gamma freezes its leading §-number; delta gets no number
    cur_nums = {s: cn for s, _, _, cn in sections}
    if cur_nums.get("gamma") != "8.12":
        print("  selftest MISS: gamma cur_num not '8.12': %r" % cur_nums.get("gamma")); ok = False
    if cur_nums.get("delta") is not None:
        print("  selftest MISS: delta cur_num should be None: %r" % cur_nums.get("delta")); ok = False
    # CODE FENCE: the fenced heading must NOT appear
    if "fenced" in slugs:
        print("  selftest MISS: fenced heading leaked through code-fence skip"); ok = False
    # missing-anchor WARN: the plain '### 8.12 No-anchor heading' line
    if not any("No-anchor heading" in h for _, h in missing):
        print("  selftest MISS: missing-anchor heading not reported"); ok = False

    new_index, vanished = build_index(sections, existing)

    # PRESERVED: alpha's legacy/related/origin survive verbatim
    if 'legacy: "1"' not in new_index:
        print("  selftest MISS: alpha legacy '1' not preserved in regen"); ok = False
    if 'related: [beta]' not in new_index:
        print("  selftest MISS: alpha related not preserved"); ok = False
    if 'origin: hand-authored' not in new_index:
        print("  selftest MISS: extra 'origin' field dropped on regen"); ok = False
    # PRESERVED: beta's legacy "2-5b" survives (not re-derived from current §-number, which
    # beta does not have anyway). beta's related survives.
    if 'legacy: "2-5b"' not in new_index:
        print("  selftest MISS: beta legacy '2-5b' not preserved"); ok = False
    if 'related: [alpha, gamma]' not in new_index:
        print("  selftest MISS: beta related not preserved"); ok = False
    # NEW: gamma freezes "8.12" as legacy; delta has none
    if 'legacy: "8.12"' not in new_index:
        print("  selftest MISS: gamma new-section legacy '8.12' not frozen"); ok = False
    gamma_block = new_index.split("- id: gamma", 1)[-1].split("- id:", 1)[0]
    if 'legacy: "8.12"' not in gamma_block:
        print("  selftest MISS: gamma's legacy block missing"); ok = False
    delta_block = new_index.split("- id: delta", 1)[-1]
    if "legacy:" in delta_block:
        print("  selftest MISS: delta should have NO legacy (no leading §-number)"); ok = False
    # vanished-slug WARN: epsilon was in the index but absent from the md
    if "epsilon" not in vanished:
        print("  selftest MISS: vanished slug 'epsilon' not reported"); ok = False

    # IDEMPOTENCE: regenerating from the just-written index reproduces the same yaml.
    existing2 = parse_existing(new_index)
    new_index2, _ = build_index(sections, existing2)
    if new_index != new_index2:
        print("  selftest MISS: regeneration is not idempotent"); ok = False

    print("✅ selftest passed" if ok else "❌ selftest FAILED")
    return 0 if ok else 1


def check_all(root):
    """--check every AUTO-GENERATED index under root (hand-maintained ones are skipped:
    they carry no AUTO-GENERATED head marker and have their own validator).
    Pairs <name>.index.yaml with its sibling <name>.md. Exit 1 on any drift."""
    root = Path(root)
    fails = checked = 0
    for idx_p in sorted(root.rglob("*.index.yaml")):
        if ".git" in idx_p.parts:
            continue
        head = idx_p.read_text(encoding="utf-8")[:200]
        if "AUTO-GENERATED" not in head:
            continue  # hand-maintained (e.g. office-automation.index.yaml)
        doc_p = idx_p.with_name(idx_p.name.replace(".index.yaml", ".md"))
        if not doc_p.exists():
            print("❌ %s: paired doc %s not found" % (idx_p, doc_p.name))
            fails += 1
            continue
        checked += 1
        md = doc_p.read_text(encoding="utf-8")
        existing = parse_existing(idx_p.read_text(encoding="utf-8"))
        sections, _ = scan_md(md)
        new_index, _ = build_index(sections, existing)
        cur = idx_p.read_text(encoding="utf-8")
        if cur.rstrip("\n") != new_index.rstrip("\n"):
            print("❌ %s OUT OF SYNC with %s -- run generate-doc-index.py" % (idx_p, doc_p.name))
            fails += 1
        else:
            print("✅ %s in sync (%d sections)" % (idx_p.relative_to(root), len(sections)))
    if checked == 0 and fails == 0:
        print("⚠️ --check-all: no AUTO-GENERATED index found under %s" % root)
    return 1 if fails else 0


def main():
    _force_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("doc", nargs="?")
    ap.add_argument("index", nargs="?")
    ap.add_argument("--check", action="store_true", help="don't write; exit 1 if out of sync")
    ap.add_argument("--check-all", nargs="?", const=".", metavar="ROOT",
                    help="verify every AUTO-GENERATED *.index.yaml under ROOT (default .)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.check_all:
        return check_all(a.check_all)
    if not a.doc or not a.index:
        ap.error("doc and index are required (or use --selftest)")
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
