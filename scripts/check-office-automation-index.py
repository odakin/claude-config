#!/usr/bin/env python3
"""Validate office-automation.md against its slug index (office-automation.index.yaml).

Checks (exit 1 if any FAIL):
  orphan   : heading slugs <-> index ids must be a bijection
  dangling : every index `related` id and every in-doc [`slug`](#slug) ref must exist
  malformed: a ref's link label must equal its anchor target
  legacy   : non-empty `legacy` values must be unique

Informational (never fails the build):
  dedup    : sections whose titles share >=2 distinctive tokens (overlap candidates)
  external : bare §N refs whose N is not an index legacy (= cross-doc, e.g. CLAUDE.md inline)

Dependency-free (minimal index parser) so it runs anywhere office-automation.md ships.
`--selftest` runs embedded fixtures. Default target: the file next to this script's repo.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "conventions" / "office-automation.md"
INDEX = REPO / "conventions" / "office-automation.index.yaml"

SLUG_RE = re.compile(r'<a id="([a-z0-9][a-z0-9-]*)"></a>')
REF_RE = re.compile(r'\[`([a-z0-9][a-z0-9-]*)`\]\(#([a-z0-9][a-z0-9-]*)\)')
BARE_SECTION_RE = re.compile(r'§([0-9]+(?:\.[0-9]+)?(?:-[0-9]+[a-z]?)?)')
STOP = {"の", "は", "が", "を", "に", "で", "と", "vs", "=", "+", "/", "の落とし穴",
        "form", "cell", "xlsx", "docx", "pdf", "excel", "設定", "確認", "義務"}
# Illustrative placeholders for the ref SYNTAX itself. convention-design-principles §14.2
# shows `[`slug`](#slug)` as an EXAMPLE of how to write a slug ref, not a real cross-ref.
# The meta-doc that documents the convention legitimately contains such placeholders; real
# section slugs are always descriptive, never these bare words, so skipping them in the
# dangling check is safe (§8.9 = filter legitimate non-violations).
PLACEHOLDER_TARGETS = {"slug", "name", "id", "anchor", "their-name"}


def parse_index(text):
    """Minimal parser for the controlled index.yaml shape -> list of dicts."""
    entries, cur = [], None
    for raw in text.split("\n"):
        if raw.startswith("#") or not raw.strip() or raw.strip() == "sections:":
            continue
        m = re.match(r"\s*-\s+id:\s*(.+)$", raw)
        if m:
            if cur:
                entries.append(cur)
            cur = {"id": m.group(1).strip(), "related": []}
            continue
        if cur is None:
            continue
        m = re.match(r"\s+(\w+):\s*(.*)$", raw)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "related":
            cur["related"] = [x.strip() for x in val.strip("[]").split(",") if x.strip()]
        else:
            cur[key] = val.strip('"')
    if cur:
        entries.append(cur)
    return entries


def heading_slugs(doc):
    out, in_fence = [], False
    for ln in doc.split("\n"):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ln.startswith("#"):
            m = SLUG_RE.search(ln)
            if m:
                out.append(m.group(1))
    return out


def doc_refs(doc):
    """list of (label, target) markdown refs outside code fences."""
    out, in_fence = [], False
    for ln in doc.split("\n"):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.extend(REF_RE.findall(ln))
    return out


def bare_sections(doc):
    out, in_fence = set(), False
    for ln in doc.split("\n"):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        out.update(BARE_SECTION_RE.findall(ln))
    return out


def tokens(title):
    t = re.sub(r"[`*\"()=+/、。:：!?\[\]]", " ", title)
    return {w for w in t.split() if len(w) >= 2 and w.lower() not in STOP}


def validate(doc, index_entries):
    """-> (fails, infos). fails is a list of FAIL strings (exit 1 if non-empty)."""
    fails, infos = [], []
    ids = [e["id"] for e in index_entries]
    idset = set(ids)
    hslugs = heading_slugs(doc)
    hset = set(hslugs)

    # orphan: bijection heading <-> index
    for s in hset - idset:
        fails.append(f"orphan: heading slug '{s}' has no index entry")
    for s in idset - hset:
        fails.append(f"orphan: index id '{s}' has no heading in the doc")
    if len(ids) != len(idset):
        dup = {i for i in ids if ids.count(i) > 1}
        fails.append(f"duplicate index id(s): {sorted(dup)}")

    # dangling: related + doc refs must resolve
    for e in index_entries:
        for r in e["related"]:
            if r not in idset:
                fails.append(f"dangling: index '{e['id']}' related -> unknown '{r}'")
    for label, target in doc_refs(doc):
        if target in PLACEHOLDER_TARGETS:
            continue  # illustrative syntax example (e.g. §14.2's `[`slug`](#slug)`), not a real ref
        if target not in idset:
            fails.append(f"dangling: doc ref [#{target}] resolves to nothing")
        if label != target:
            fails.append(f"malformed ref: label '{label}' != target '{target}'")

    # legacy uniqueness (non-empty)
    legacies = [e.get("legacy", "") for e in index_entries if e.get("legacy", "")]
    if len(legacies) != len(set(legacies)):
        dup = {l for l in legacies if legacies.count(l) > 1}
        fails.append(f"duplicate legacy number(s): {sorted(dup)}")

    # external bare §N refs (informational): N not an index legacy
    legacyset = set(legacies)
    ext = {n for n in bare_sections(doc) if n not in legacyset}
    if ext:
        infos.append(f"external §-refs (verify cross-doc target manually): "
                     f"{', '.join('§'+n for n in sorted(ext))}")

    # dedup candidates (informational): title token overlap >= 2
    toks = {e["id"]: tokens(e.get("title", "")) for e in index_entries}
    seen = set()
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = toks[a] & toks[b]
            if len(shared) >= 2 and (a, b) not in seen:
                seen.add((a, b))
                infos.append(f"dedup? {a} ~ {b}  (shared: {', '.join(sorted(shared))})")
    return fails, infos


def run(doc, index_text, label="", silent_if_clean=False):
    entries = parse_index(index_text)
    fails, infos = validate(doc, entries)
    pre = f"[{label}] " if label else ""
    if silent_if_clean:
        # dashboard mode: only surface real drift (FAILs); infos are not actionable daily noise
        if fails:
            print("\n🗂️  office-automation index drift (slug<->doc out of sync):")
            for f in fails:
                print(f"  ❌ {f}")
        return len(fails)
    for i in infos:
        print(f"{pre}info  {i}")
    for f in fails:
        print(f"{pre}FAIL  {f}")
    n = len(entries)
    if fails:
        print(f"{pre}❌ {len(fails)} failure(s) over {n} sections")
    else:
        print(f"{pre}✅ {n} sections: dangling 0 / orphan 0")
    return len(fails)


def selftest():
    good_doc = (
        '## <a id="alpha"></a>Alpha section\n'
        'See [`beta`](#beta) for details.\n'
        'Syntax example [`slug`](#slug) is a placeholder, must NOT count as a real ref.\n'
        '## <a id="beta"></a>Beta section\n'
        'Refs [`alpha`](#alpha). External §14 should be ignored.\n'
    )
    good_idx = (
        "sections:\n"
        '  - id: alpha\n    legacy: "1"\n    title: "Alpha section"\n    related: [beta]\n'
        '  - id: beta\n    legacy: "2"\n    title: "Beta section"\n    related: [alpha]\n'
    )
    bad_doc = (
        '## <a id="alpha"></a>Alpha\n'
        'Broken [`ghost`](#ghost) ref.\n'
        '## <a id="orphan-heading"></a>No index entry\n'
    )
    bad_idx = (
        "sections:\n"
        '  - id: alpha\n    legacy: "1"\n    title: "Alpha"\n    related: [missing]\n'
        '  - id: lonely\n    legacy: "1"\n    title: "Lonely"\n'  # dup legacy + orphan id
    )
    ok = True
    print("-- good fixture (expect 0 fails) --")
    if run(good_doc, good_idx, "good") != 0:
        ok = False
    print("-- bad fixture (expect >=4 fails) --")
    entries = parse_index(bad_idx)
    fails, _ = validate(bad_doc, entries)
    expect = {"dangling", "orphan", "duplicate legacy"}
    got = " ".join(fails)
    for kw in expect:
        if kw not in got:
            print(f"  selftest MISS: expected a '{kw}' failure"); ok = False
    print(f"  detected {len(fails)} fail(s): {got[:120]}...")
    print("✅ selftest passed" if ok else "❌ selftest FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse
    # Generalized 2026-06-16: defaults validate office-automation (dashboard caller
    # unchanged), but --doc/--index let this validate ANY slug-indexed convention
    # (convention-design-principles, hook-authoring, ...). See convention-design-principles
    # §14 / §14.7. Name kept for caller compatibility; it is now a generic validator.
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=str(DOC))
    ap.add_argument("--index", default=str(INDEX))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--silent-if-clean", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    doc_path, index_path = Path(a.doc), Path(a.index)
    label = doc_path.name if doc_path.resolve() != DOC.resolve() else ""
    sys.exit(1 if run(doc_path.read_text(encoding="utf-8"),
                      index_path.read_text(encoding="utf-8"),
                      label=label, silent_if_clean=a.silent_if_clean) else 0)
