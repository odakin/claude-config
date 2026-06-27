#!/usr/bin/env python3
"""check-legacy-append-only.py -- the `legacy` forwarding map in a slug index must be
APPEND-ONLY.

WHY: once a §-number is published, downstream repos / other users / old notes can reference
it forever and we can NEVER recall those refs. So each `legacy:` entry is a PERMANENT
forwarding address (convention-design-principles.md §14.7 = #inbound-ref-robustness -- the 'mail-forwarding-order you
keep forever' guarantee). It must never be SILENTLY dropped (by a slug rename, a section
delete, or an index regeneration). This gate compares every slug index's CURRENT legacy set
against its committed (HEAD) version and FAILS if any legacy value disappeared.

Deliberate retirement (a section genuinely removed on purpose) is ALLOWED but must be
EXPLICIT, never a silent side-effect: set env LEGACY_RETIRE_OK=1 to downgrade the failure to
a warning for that one commit. The point is that a forwarding entry can only leave the live
set by a DELIBERATE, acknowledged act -- never by accident.

Uses git history as the source of truth (no separate ledger to maintain). Generic + public-safe.

Usage:
  check-legacy-append-only.py [index.yaml ...]    # default: working tree vs HEAD
  check-legacy-append-only.py --staged [...]       # staged (:path) vs HEAD  (pre-commit gate)
  check-legacy-append-only.py --selftest
  (no index args -> auto-discover tracked *.index.yaml)
Exit 1 if a legacy dropped (unless LEGACY_RETIRE_OK=1).
"""
import os
import re
import sys
import argparse
import subprocess


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


LEGACY_RE = re.compile(r'^\s*legacy:\s*"?([^"\n]+?)"?\s*$', re.M)


def legacy_set(text):
    return set(m.group(1).strip() for m in LEGACY_RE.finditer(text or ""))


def git_show(ref_path):
    try:
        r = subprocess.run(["git", "show", ref_path], capture_output=True,
                            text=True, encoding="utf-8")
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def discover():
    """Index files to check = HEAD's committed set UNION the current tracked set.

    Iterating HEAD's set is what closes the whole-file-deletion hole: a deleted index.yaml
    vanishes from the working/staged set, so iterating ONLY the current set would miss it and
    let its ENTIRE legacy map drop silently (= deleting a whole convention's index would erase
    all its §-ref forwarding undetected). With HEAD's set included, a deleted/renamed-away index
    is still compared -- its current legacy set is empty, so ALL of HEAD's legacies count as
    dropped -> BLOCK (a deliberate whole-doc removal uses LEGACY_RETIRE_OK=1)."""
    paths = set()
    for args in (["git", "ls-tree", "-r", "--name-only", "HEAD"], ["git", "ls-files"]):
        try:
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
            if r.returncode == 0:
                paths |= {p for p in r.stdout.split("\n") if p.endswith(".index.yaml")}
        except Exception:
            pass
    return sorted(paths)


def selftest():
    ok = True
    before = ('sections:\n  - id: a\n    legacy: "1"\n  - id: b\n    legacy: "2"\n'
              '  - id: c\n    legacy: "2-5b"\n')
    after_ok = before + '  - id: d\n    legacy: "9"\n'            # added one, dropped none
    after_bad = 'sections:\n  - id: a\n    legacy: "1"\n  - id: c\n    legacy: "2-5b"\n'  # dropped "2"
    if legacy_set(before) != {"1", "2", "2-5b"}:
        print("  selftest MISS: parse"); ok = False
    if legacy_set(before) - legacy_set(after_ok):
        print("  selftest MISS: append must not report a drop"); ok = False
    if (legacy_set(before) - legacy_set(after_bad)) != {"2"}:
        print("  selftest MISS: expected dropped {'2'}"); ok = False
    print("✅ selftest passed" if ok else "❌ selftest FAILED")
    return 0 if ok else 1


def main():
    _force_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("indexes", nargs="*")
    ap.add_argument("--staged", action="store_true", help="compare staged content vs HEAD (pre-commit)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    paths = a.indexes or discover()
    violations = []
    for p in paths:
        head = git_show("HEAD:" + p)
        if not head:
            continue  # not in HEAD (new file) -> nothing could have been dropped
        cur = git_show(":" + p) if a.staged else _read(p)
        for d in sorted(legacy_set(head) - legacy_set(cur)):
            violations.append((p, d))

    if not violations:
        return 0
    if os.environ.get("LEGACY_RETIRE_OK") == "1":
        print("[legacy-append-only] %d legacy forwarding entry(ies) dropped -- "
              "LEGACY_RETIRE_OK=1, treated as deliberate retirement:" % len(violations))
        for p, d in violations:
            print("  %s : §%s retired" % (p, d))
        return 0
    print("[legacy-append-only] ❌ BLOCK: %d legacy forwarding entry(ies) DROPPED -- "
          "old §-refs would break:" % len(violations))
    for p, d in violations:
        print("  %s : legacy §%s is gone vs HEAD" % (p, d))
    print("  A published §-number is a PERMANENT forwarding address (convention-design-principles")
    print("  §14.7). If you removed these sections ON PURPOSE, re-commit with LEGACY_RETIRE_OK=1.")
    return 1


def _read(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""


if __name__ == "__main__":
    sys.exit(main())
