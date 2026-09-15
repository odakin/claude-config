#!/usr/bin/env python3
"""Warn when staged additions contain unstable account-bound Google URLs.

This Git-native fallback covers clients where an editor lifecycle hook is not
visible. It scans only added lines and always exits zero: `/u/N/` account-slot
URLs and account-sensitive Google URLs without `authuser=` are recoverable,
low-stakes findings. The semantic source is conventions/google-url.md.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from staged_diff import staged_added_lines  # noqa: E402


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


def git_added_lines(cwd: str | None = None) -> list[str]:
    # binary (PDF 等) を含む commit でも落ちず、 同じ commit の text file は読む (lib/staged_diff.py)
    return [
        text
        for _path, _lineno, text in staged_added_lines(
            cwd=cwd, skip=lambda path: path.endswith("pre-commit-google-url-warn.py")
        )
    ]


def binary_commit_case() -> bool | None:
    """一時 repo に binary + trigger を含む text を stage し、 warning が出るか (git 無し = None)。"""
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        git = lambda *a: subprocess.run(["git", *a], cwd=td, env=env, capture_output=True, check=False)
        if git("init", "-q").returncode != 0:
            return None
        Path(td, "scan.pdf").write_bytes(b"%PDF-1.4\n%\xc5\xd0\xe2\xe3\nstream \xff\xfe\n")
        Path(td, "note.md").write_text("https://drive.google.com/file/d/example/view\n", encoding="utf-8")
        git("add", "-A")
        return bool(scan_added_lines(git_added_lines(cwd=td)))


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
    fired = binary_commit_case()
    if fired is None:
        print("  [SKIP] staged binary + text: git not available")
    else:
        print(f"  [{'PASS' if fired else 'FAIL'}] staged binary + text: warning still fires for the text file")
        ok = ok and fired
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
