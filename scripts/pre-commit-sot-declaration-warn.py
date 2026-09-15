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
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from staged_diff import staged_added_lines  # noqa: E402


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


def git_added_lines(cwd: str | None = None) -> list[str]:
    # binary (PDF 等) を含む commit でも落ちず、 同じ commit の text file は読む (lib/staged_diff.py)
    return [text for _path, _lineno, text in staged_added_lines(cwd=cwd, skip=skip_path)]


def binary_commit_case() -> bool | None:
    """一時 repo に binary + trigger を含む text を stage し、 warning が出るか (git 無し = None)。"""
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        git = lambda *a: subprocess.run(["git", *a], cwd=td, env=env, capture_output=True, check=False)
        if git("init", "-q").returncode != 0:
            return None
        Path(td, "scan.pdf").write_bytes(b"%PDF-1.4\n%\xc5\xd0\xe2\xe3\nstream \xff\xfe\n")
        Path(td, "note.md").write_text("この規則の正本は docs/reference.md\n", encoding="utf-8")
        git("add", "-A")
        return bool(scan_added_lines(git_added_lines(cwd=td)))


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
    fired = binary_commit_case()
    if fired is None:
        print("  [SKIP] staged binary + text: git not available")
    else:
        checks.append(("staged binary + text: warning still fires for the text file", fired))
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
