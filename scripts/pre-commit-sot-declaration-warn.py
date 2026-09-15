#!/usr/bin/env python3
"""Warn when staged additions introduce a source-of-truth declaration.

The detector is deliberately semantic-light: it does not decide whether the
declaration is correct or duplicated. It moves the reminder from human recall
to commit time, scans additions only, skips its own fixture and the registry,
and always exits zero. The semantic sources are
docs/convention-design-principles.md#no-duplicate-rules and
#sot-declaration-collision-sweep.
"""

from __future__ import annotations

import os
import subprocess
import sys


SKIP_BASENAMES = {
    "pre-commit-sot-declaration-warn.py",
    "sot-registry.yaml",
}
PHRASES = [
    "正本は",
    "を正本と",
    "が正本",
    "は正本",
    "= 正本",
    "📍SoT",
    "が SoT",
    "は SoT",
    "を SoT",
    "単一 SoT",
    "単一の SoT",
    "SoT =",
    "SoT 序列",
    "single source of truth",
    "source of record",
    "system of record",
]


def scan_added_lines(added: list[str]) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for line in added:
        for phrase in PHRASES:
            if phrase not in line or phrase in seen:
                continue
            seen.add(phrase)
            sample = line.strip()
            if len(sample) > 60:
                sample = sample[:57] + "…"
            warnings.append(f"{phrase!r}: {sample}")
            break
    return warnings


def skip_path(path: str) -> bool:
    return os.path.basename(path.strip()) in SKIP_BASENAMES


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
            target = line[4:]
            if target.startswith(("a/", "b/")):
                target = target[2:]
            skip = skip_path(target)
        elif line.startswith("+") and not skip:
            added.append(line[1:])
    return added


def run_selftest() -> int:
    cases = [
        (["この規則の正本は docs/reference.md"], True),
        (["| facts | 正本 (SoT) | derived |  ← SoT 序列表"], True),
        (["records.yaml が SoT として扱われる"], True),
        (["X を正本とし、他は pointer にする"], True),
        (["the single source of truth is refs.yaml"], True),
        (["key: value", "ordinary prose"], False),
        (["SoT 重複について議論する"], False),
        (["this is a single source discussion"], False),
        (["二重 SoT は存在しない"], False),
    ]
    checks: list[tuple[str, bool]] = []
    for index, (added, expected) in enumerate(cases, 1):
        checks.append(
            (f"phrase case {index}", bool(scan_added_lines(added)) == expected)
        )
    checks.extend(
        [
            ("registry is skipped", skip_path("scripts/sot-registry.yaml")),
            ("self is skipped", skip_path("scripts/pre-commit-sot-declaration-warn.py")),
            ("ordinary source is scanned", not skip_path("docs/design.md")),
        ]
    )
    ok = True
    for label, condition in checks:
        print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
        ok = ok and condition
    print("pre-commit-sot-declaration-warn selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return run_selftest()
    warnings = scan_added_lines(git_added_lines())
    if warnings:
        print("Warning: staged additions contain a source-of-truth declaration:", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)
        print(
            "  Before committing: (1) register a distinctive home anchor when a registry "
            "is in use, (2) search for conflicting declarations, and (3) make other "
            "use-sites concise pointers. See docs/convention-design-principles.md "
            "#no-duplicate-rules and #sot-declaration-collision-sweep. "
            "This warning does not block the commit.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
