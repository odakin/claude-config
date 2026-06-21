#!/usr/bin/env python3
"""check-inbound-refs.py -- safety net for restructuring claude-config (layer 1).

Scans repos under a base dir (default ~/Claude) for references INTO a target repo
(default claude-config) and verifies they still resolve. Purpose: the most-referenced
layer-1 docs can be slug-ified / reorganized WITHOUT silently breaking the ~1000
downstream pointers (CONVENTIONS.md, convention-design-principles.md, etc.). Run it
BEFORE a restructure to get a baseline, and AFTER each edit to confirm it stays green.

Reference forms (see convention-design-principles.md section 14.2):
  HARD checks (exit 1 on any dangling -- mechanically verifiable):
    * anchor ref  `X.md#slug`            -> X.md (a target doc) must define that anchor
                                            (explicit id="slug" OR a heading whose slug matches)
    * path ref    `claude-config/.../X.md` -> the file must exist
  INFO (no exit -- the FRAGILE population):
    * positional `section N.M` naming a target doc. This form SILENTLY mis-resolves on
      renumber; the semantic drift is NOT mechanically checkable (the documented blind
      spot, convention-design-principles.md 14.2 / 8.8). The fix is migrating these to
      anchors. This script reports their COUNT only, with that caveat.

De-noising (per convention-design-principles.md 8.9 -- a detector that cries wolf gets
ignored): generic per-repo scaffold filenames (README/DESIGN/SESSION/...) are NOT treated
as target docs (they collide cross-repo); GitHub `blob|tree/<branch>/` URL infixes are
stripped; obvious `X.md` placeholders in prose are skipped.

Generic + public-safe: no private repo names are hardcoded (takes base/target as args),
so this lives in layer 1 and is invoked over the whole ~/Claude tree.

Usage:
  check-inbound-refs.py [--base DIR] [--target REPO] [--list] [--quiet]
  check-inbound-refs.py --selftest
Exit code: 1 if any HARD dangling ref found, else 0.
"""
import os
import re
import sys
import glob
import shutil
import tempfile
import argparse


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


# Generic per-repo scaffold filenames: present in many repos, so an anchor ref like
# `README.md#foo` almost always points at the referencing repo's OWN file, not the
# target's. Excluded from the anchor-checkable target index (path-existence still uses them).
GENERIC_NAMES = {
    'README.md', 'README.ja.md', 'README.en.md', 'DESIGN.md', 'SESSION.md',
    'SESSION-archive.md', 'CHANGELOG.md', 'SETUP.md', 'AUDIT.md', 'EXPLORING.md',
    'CLAUDE.md', 'MEMORY.md', 'NOTES.md', 'TODO.md', 'LICENSE.md',
}
SKIP_DIRS = {'.git', 'node_modules', '_site', 'build', 'dist', '.venv', 'venv',
             '.next', 'out', '__pycache__', '.cache'}
EXT = ('.md', '.yaml', '.yml', '.py', '.sh', '.txt')


def gh_slug(text):
    """Approximate GitHub-style heading anchor slug (keeps unicode word chars)."""
    s = text.strip().lower().replace('`', '')
    s = re.sub(r'[^\w\s\-]', '', s, flags=re.UNICODE)
    s = re.sub(r'\s+', '-', s)
    return s.strip('-')


def build_target_index(target_dir):
    """Map each DISTINCTIVE target *.md basename -> set of anchor slugs, plus the set of
    all relpaths (for path-ref existence checks, generic names included)."""
    docs = {}
    relpaths = set()
    for path in glob.glob(os.path.join(target_dir, '**', '*.md'), recursive=True):
        if os.sep + '.git' + os.sep in path:
            continue
        rel = os.path.relpath(path, target_dir)
        relpaths.add(rel)
        base = os.path.basename(path)
        if base in GENERIC_NAMES:
            continue  # collides cross-repo: don't anchor-index (path-existence still covers it)
        anchors = set()
        try:
            txt = open(path, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        for m in re.finditer(r'id=["\']([^"\']+)["\']', txt):
            anchors.add(m.group(1))
        for line in txt.splitlines():
            hm = re.match(r'#{1,6}\s+(.*)', line)
            if hm:
                anchors.add(gh_slug(hm.group(1)))
        d = docs.setdefault(base, set())
        d |= anchors
    return docs, relpaths


def scan(base, target_name, docs, relpaths):
    target_dir = os.path.join(base, target_name)
    anchor_re = re.compile(r'([A-Za-z0-9_.\-]+\.md)#([A-Za-z0-9_\-]+)')
    path_re = re.compile(r'(?:\.\./)*' + re.escape(target_name) + r'/([\w./\-]+\.md)')
    blob_re = re.compile(r'^(?:blob|tree)/[^/]+/')
    placeholder_re = re.compile(r'^[A-Z]\.md$')
    sec_re = re.compile(r'§\s*\d+(?:[.\-]\d+)*[a-z]?')
    hard = []          # (relfile, lineno, kind, ref)
    fragile = 0
    fragile_samples = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if root == target_dir or root.startswith(target_dir + os.sep):
            continue  # the target repo's internal refs are its own concern
        for f in files:
            if not f.endswith(EXT):
                continue
            fp = os.path.join(root, f)
            try:
                txt = open(fp, encoding='utf-8', errors='ignore').read()
            except Exception:
                continue
            relfp = os.path.relpath(fp, base)
            for ln, line in enumerate(txt.splitlines(), 1):
                for m in anchor_re.finditer(line):
                    bn, slug = m.group(1), m.group(2)
                    if bn in docs and slug not in docs[bn]:
                        hard.append((relfp, ln, 'anchor', bn + '#' + slug))
                for m in path_re.finditer(line):
                    rel = blob_re.sub('', m.group(1))  # strip github blob/<branch>/
                    if placeholder_re.match(os.path.basename(rel)):
                        continue  # obvious placeholder in illustrative prose
                    if rel not in relpaths and not os.path.exists(os.path.join(target_dir, rel)):
                        hard.append((relfp, ln, 'path', target_name + '/' + rel))
                if sec_re.search(line):
                    for bn in docs:
                        if bn in line:
                            fragile += 1
                            if len(fragile_samples) < 10:
                                fragile_samples.append((relfp, ln, bn))
                            break
    return hard, fragile, fragile_samples


def selftest():
    """Hermetic fixture: a temp base dir with a tiny target repo + a downstream repo,
    exercising every HARD/INFO/de-noise rule. Touches no real ~/Claude file."""
    ok = True
    tmp = tempfile.mkdtemp(prefix='check-inbound-refs-selftest-')
    try:
        # --- target repo: one distinctive doc with a known anchor, one generic README ---
        tgt = os.path.join(tmp, 'tgt')
        os.makedirs(os.path.join(tgt, 'conventions'))
        with open(os.path.join(tgt, 'conventions', 'real.md'), 'w', encoding='utf-8') as f:
            f.write('## <a id="present-slug"></a>Present heading\n\nbody\n')
        with open(os.path.join(tgt, 'README.md'), 'w', encoding='utf-8') as f:
            f.write('## A README heading\n')  # generic name; must not anchor-index

        # --- downstream repo with one of every reference kind ---
        ds = os.path.join(tmp, 'downstream')
        os.makedirs(ds)
        with open(os.path.join(ds, 'doc.md'), 'w', encoding='utf-8') as f:
            f.write(
                # HARD anchor: present (NOT flagged) vs missing (FLAGGED)
                'See real.md#present-slug for details.\n'                # line 1: OK
                'But real.md#missing-slug is wrong.\n'                   # line 2: HARD anchor
                # HARD path: existing (NOT flagged) vs missing (FLAGGED)
                'Path tgt/conventions/real.md exists.\n'                 # line 3: OK
                'Path tgt/conventions/gone.md is missing.\n'             # line 4: HARD path
                # DE-NOISE: README.md#x in this repo must NOT be flagged (generic name)
                'Our own README.md#whatever is local.\n'                 # line 5: de-noised
                # DE-NOISE: github blob/<branch>/ infix must strip to docs/x.md and exist
                'GH link tgt/blob/main/conventions/real.md works.\n'     # line 6: de-noised path
                # DE-NOISE: single-letter placeholder X.md must be skipped
                'In prose we sometimes write tgt/X.md as an example.\n'  # line 7: placeholder
                # FRAGILE positional: §N.M naming a target doc -> INFO (counted, not HARD)
                'See real.md §1.2 for the rationale.\n'                  # line 8: fragile
            )

        docs, relpaths = build_target_index(tgt)
        # README.md must NOT be in the anchor-indexed docs (generic)
        if 'README.md' in docs:
            print("  selftest MISS: generic README.md leaked into target anchor index"); ok = False
        if 'real.md' not in docs or 'present-slug' not in docs.get('real.md', set()):
            print("  selftest MISS: distinctive real.md / present-slug not indexed"); ok = False

        hard, fragile, _ = scan(tmp, 'tgt', docs, relpaths)
        hard_kinds = sorted((kind, ref) for _, _, kind, ref in hard)
        expected = sorted([
            ('anchor', 'real.md#missing-slug'),
            ('path',   'tgt/conventions/gone.md'),
        ])
        if hard_kinds != expected:
            print("  selftest MISS: HARD set mismatch")
            print("    got:      %s" % hard_kinds)
            print("    expected: %s" % expected)
            ok = False
        if fragile < 1:
            print("  selftest MISS: fragile §1.2 positional ref not counted"); ok = False

        print("✅ selftest passed" if ok else "❌ selftest FAILED")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    _force_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=os.path.expanduser('~/Claude'))
    ap.add_argument('--target', default='claude-config')
    ap.add_argument('--list', action='store_true', help='list every hard dangling ref')
    ap.add_argument('--quiet', action='store_true', help='print nothing when green')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    target_dir = os.path.join(args.base, args.target)
    if not os.path.isdir(target_dir):
        print('[check-inbound-refs] target not found: %s' % target_dir, file=sys.stderr)
        return 0  # fail-open: do not block on a missing target

    docs, relpaths = build_target_index(target_dir)
    hard, fragile, fragile_samples = scan(args.base, args.target, docs, relpaths)

    if hard:
        print('[check-inbound-refs] HARD DANGLING into %s: %d ref(s)' % (args.target, len(hard)))
        show = hard if args.list else hard[:20]
        for relfp, ln, kind, ref in show:
            print('  %-7s %s:%d  ->  %s' % (kind, relfp, ln, ref))
        if not args.list and len(hard) > 20:
            print('  ... (%d more; rerun with --list)' % (len(hard) - 20))
        print('  fragile positional refs (informational): %d' % fragile)
        return 1

    if not args.quiet:
        print('[check-inbound-refs] OK: 0 hard dangling into %s '
              '(%d distinctive target docs indexed).' % (args.target, len(docs)))
        print('  fragile positional refs (informational): %d '
              '-- these RESOLVE today but silently mis-resolve on renumber;' % fragile)
        print('  migrate to anchors (convention-design-principles.md 14.2). '
              'Positional-ref SEMANTICS are not checkable here (blind spot).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
