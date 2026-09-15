#!/usr/bin/env python3
"""Warn when staged additions contain unstable account-bound Google URLs.

This Git-native fallback covers clients where an editor lifecycle hook is not
visible. It scans only added lines and always exits zero: `/u/N/` account-slot
URLs and account-sensitive Google URLs without `authuser=` are recoverable,
low-stakes findings. The semantic source is conventions/google-url.md.
"""

from __future__ import annotations

import re
import subprocess
import sys


SLOT = re.compile(r"https?://[^\s\"'<>]*google(?:usercontent)?\.com[^\s\"'<>]*/u/\d+/")
SENSITIVE = re.compile(
    r"https?://(?:docs|drive|classroom|calendar|script|sites|mail|meet|forms|keep)"
    r"\.google\.com[^\s\"'<>]*|https?://console\.cloud\.google\.com[^\s\"'<>]*"
)
PUBLIC_SITE = re.compile(r"https?://sites\.google\.com/view/")


def scan_added_lines(added: list[str]) -> list[str]:
    warnings: list[str] = []
    blob = "\n".join(added)
    if SLOT.search(blob):
        urls = sorted({match.group(0) for match in SLOT.finditer(blob)})
        warnings.append("/u/N/ account-slot URL: " + ", ".join(urls[:3]))
    missing: set[str] = set()
    for match in SENSITIVE.finditer(blob):
        url = match.group(0)
        if PUBLIC_SITE.match(url) or "authuser=" in url:
            continue
        missing.add(url)
    if missing:
        warnings.append(
            "account-sensitive Google URL without authuser=: "
            + ", ".join(sorted(missing)[:3])
        )
    return warnings


def git_added_lines() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "-U0", "--no-color", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    added: list[str] = []
    skip = False
    for line in result.stdout.splitlines():
        if line.startswith("+++ "):
            skip = line.rstrip().endswith("pre-commit-google-url-warn.py")
        elif line.startswith("+") and not skip:
            added.append(line[1:])
    return added


def run_selftest() -> int:
    cases = [
        (["https://docs.google.com/document/d/example/u/3/edit"], True),
        (["https://drive.google.com/file/d/example/view"], True),
        (["https://docs.google.com/document/d/example/edit?authuser=user@example.com"], False),
        (["plain text"], False),
        (["https://maps.google.com/example"], False),
        (["https://sites.google.com/view/example-lab/"], False),
        (["https://sites.google.com/d/example/edit"], True),
    ]
    ok = True
    for index, (added, expected) in enumerate(cases, 1):
        got = bool(scan_added_lines(added))
        passed = got == expected
        print(f"  [{'PASS' if passed else 'FAIL'}] case {index}: got={got} expected={expected}")
        ok = ok and passed
    print("pre-commit-google-url-warn selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return run_selftest()
    warnings = scan_added_lines(git_added_lines())
    if warnings:
        print("Warning: staged additions contain unstable Google URLs:", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)
        print(
            "  Use a stable resource ID plus ?authuser=<account>; remove /u/N/. "
            "See conventions/google-url.md. This warning does not block the commit.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
