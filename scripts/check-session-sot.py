#!/usr/bin/env python3
"""Detect durable-data accretion and bloat in SESSION.md files.

SESSION.md is a volatile resume pointer, not a durable ledger. This report-only
detector scans SESSION.md files one or two directories below a root and surfaces
three high-signal proxies:

* a dense block of distinct 16-hex external message identifiers;
* an unusually large SESSION.md file;
* an unusually large single line, which catches durable payload packed into one
  Markdown bullet to evade line-count or density checks.

The defaults are calibrated as warnings, not universal correctness limits:
64 KiB per file and 2 KiB per line. A clean result does not prove that prose is
properly placed. The semantic source is
conventions/memory-file-slimming.md#regrowth-backstop.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path


MSGID_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])")
DEFAULT_WINDOW = 5
DEFAULT_MESSAGE_ID_THRESHOLD = 8
DEFAULT_TOTAL_BYTES = 64 * 1024
DEFAULT_MAX_LINE_BYTES = 2 * 1024
SKIP_DIR_PARTS = {".git", "node_modules", ".obsidian"}


def iter_session_files(root: Path):
    """Yield de-duplicated SESSION.md files at depth one or two below root."""
    seen: set[Path] = set()
    for pattern in ("*/SESSION.md", "*/*/SESSION.md"):
        for path in root.glob(pattern):
            if path.is_symlink() or not path.is_file():
                continue
            if SKIP_DIR_PARTS & set(path.parts):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def max_window_density(lines: list[str], window: int = DEFAULT_WINDOW) -> tuple[int, int]:
    """Return maximum distinct message-id density and its 1-based start line."""
    best = 0
    best_line = 0
    for start in range(len(lines)):
        identifiers: set[str] = set()
        for line in lines[start : start + window]:
            identifiers.update(MSGID_RE.findall(line))
        if len(identifiers) > best:
            best = len(identifiers)
            best_line = start + 1
    return best, best_line


def longest_line_bytes(lines: list[str]) -> tuple[int, int]:
    """Return longest UTF-8 encoded line size and its 1-based line number."""
    best = 0
    best_line = 0
    for lineno, line in enumerate(lines, 1):
        size = len(line.encode("utf-8"))
        if size > best:
            best = size
            best_line = lineno
    return best, best_line


def scan(
    root: Path,
    *,
    window: int = DEFAULT_WINDOW,
    message_id_threshold: int = DEFAULT_MESSAGE_ID_THRESHOLD,
    total_bytes_threshold: int = DEFAULT_TOTAL_BYTES,
    max_line_bytes_threshold: int = DEFAULT_MAX_LINE_BYTES,
) -> list[dict[str, object]]:
    """Return one finding per SESSION.md that crosses at least one threshold."""
    findings: list[dict[str, object]] = []
    for path in iter_session_files(root):
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="ignore")
        except OSError:
            continue
        lines = text.splitlines()
        density, density_line = max_window_density(lines, window)
        max_line_bytes, max_line_number = longest_line_bytes(lines)
        total_ids = len(MSGID_RE.findall(text))
        reasons: list[str] = []
        if message_id_threshold > 0 and density >= message_id_threshold:
            reasons.append("message_ids")
        if total_bytes_threshold > 0 and len(raw) >= total_bytes_threshold:
            reasons.append("file_bytes")
        if max_line_bytes_threshold > 0 and max_line_bytes >= max_line_bytes_threshold:
            reasons.append("max_line_bytes")
        if not reasons:
            continue
        if "message_ids" in reasons:
            lineno = density_line
        elif "max_line_bytes" in reasons:
            lineno = max_line_number
        else:
            lineno = 1
        score = max(
            density / message_id_threshold if message_id_threshold > 0 else 0,
            len(raw) / total_bytes_threshold if total_bytes_threshold > 0 else 0,
            max_line_bytes / max_line_bytes_threshold if max_line_bytes_threshold > 0 else 0,
        )
        findings.append(
            {
                "rel": str(path.relative_to(root)),
                "lineno": lineno,
                "density": density,
                "density_line": density_line,
                "total_ids": total_ids,
                "file_bytes": len(raw),
                "line_count": len(lines),
                "max_line_bytes": max_line_bytes,
                "max_line_number": max_line_number,
                "reasons": reasons,
                "score": score,
            }
        )
    findings.sort(key=lambda finding: (-float(finding["score"]), str(finding["rel"])))
    return findings


def report(
    findings: list[dict[str, object]],
    *,
    window: int,
    message_id_threshold: int,
    total_bytes_threshold: int,
    max_line_bytes_threshold: int,
) -> None:
    if not findings:
        return
    print()
    print("=" * 72)
    print("📌 SESSION-as-SoT / bloat findings")
    print("=" * 72)
    for finding in findings:
        print(f"\n🚨 {finding['rel']}:{finding['lineno']}")
        reasons = set(finding["reasons"])
        if "message_ids" in reasons:
            print(
                f"   - messageId density {finding['density']} in {window} lines "
                f"(threshold {message_id_threshold}, file total {finding['total_ids']})"
            )
        if "file_bytes" in reasons:
            print(
                f"   - file size {finding['file_bytes']} bytes across "
                f"{finding['line_count']} lines (threshold {total_bytes_threshold})"
            )
        if "max_line_bytes" in reasons:
            print(
                f"   - longest line {finding['max_line_bytes']} bytes at "
                f"L{finding['max_line_number']} (threshold {max_line_bytes_threshold})"
            )
        print(
            "   → move durable payload to its owning source/archive and keep "
            "SESSION as current state + direct pointers"
        )
    print()
    print(
        "scope: message-id density and byte-size proxies only. A clean report "
        "does not prove correct information placement."
    )
    print()


def run_selftest() -> int:
    def message_id(index: int) -> str:
        return f"19ab00000000{index:04x}"

    with tempfile.TemporaryDirectory(prefix="check-session-sot-") as temporary:
        root = Path(temporary)

        (root / "repoA").mkdir()
        dense = " ".join(message_id(index) for index in range(10))
        (root / "repoA/SESSION.md").write_text(f"# A\n{dense}\n", encoding="utf-8")

        (root / "repoB").mkdir()
        scattered = ["# B"]
        for index in range(6):
            scattered.extend(
                [f"- pointer {message_id(100 + index)}", "  short explanation"]
            )
        (root / "repoB/SESSION.md").write_text(
            "\n".join(scattered) + "\n", encoding="utf-8"
        )

        (root / "repoC").mkdir()
        (root / "repoC/SESSION.md").write_text(
            "# C\ncommit 60e80a1 / 9d9a0c7\n"
            "full SHA 1338f51aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            "sha256 4305f6bb" + "0" * 56 + "\n",
            encoding="utf-8",
        )

        (root / "repoD").mkdir()
        (root / "repoD/notes.md").write_text(
            " ".join(message_id(index) for index in range(10)) + "\n",
            encoding="utf-8",
        )

        (root / "repoE/sub").mkdir(parents=True)
        (root / "repoE/sub/SESSION.md").write_text(
            " ".join(message_id(index) for index in range(9)) + "\n",
            encoding="utf-8",
        )

        (root / "repoF").mkdir()
        (root / "repoF/SESSION.md").write_text(
            "\n".join("x" * 1000 for _ in range(70)) + "\n",
            encoding="utf-8",
        )

        (root / "repoG").mkdir()
        (root / "repoG/SESSION.md").write_text(
            "# G\n" + "y" * 2200 + "\n", encoding="utf-8"
        )

        (root / "repoH").mkdir()
        (root / "repoH/SESSION.md").write_text(
            "# H\n" + "界" * 700 + "\n", encoding="utf-8"
        )

        findings = scan(root)
        by_rel = {str(finding["rel"]): finding for finding in findings}
        checks = [
            ("dense message ids", "message_ids" in by_rel["repoA/SESSION.md"]["reasons"]),
            ("scattered ids stay quiet", "repoB/SESSION.md" not in by_rel),
            ("SHA-only stays quiet", "repoC/SESSION.md" not in by_rel),
            ("non-SESSION is ignored", "repoD/notes.md" not in by_rel),
            ("depth-two is scanned", "message_ids" in by_rel["repoE/sub/SESSION.md"]["reasons"]),
            ("total bytes are measured", by_rel["repoF/SESSION.md"]["reasons"] == ["file_bytes"]),
            ("long ASCII line is measured", by_rel["repoG/SESSION.md"]["reasons"] == ["max_line_bytes"]),
            ("line threshold uses UTF-8 bytes", by_rel["repoH/SESSION.md"]["max_line_bytes"] == 2100),
        ]
        ok = True
        for label, condition in checks:
            print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
            ok = ok and condition

        legacy_only = scan(
            root,
            total_bytes_threshold=0,
            max_line_bytes_threshold=0,
        )
        legacy_flagged = {str(finding["rel"]) for finding in legacy_only}
        legacy_ok = legacy_flagged == {"repoA/SESSION.md", "repoE/sub/SESSION.md"}
        print(f"  [{'PASS' if legacy_ok else 'FAIL'}] size axes can be disabled")
        ok = ok and legacy_ok

    print("check-session-sot selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or positive")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--window", type=positive_int, default=DEFAULT_WINDOW)
    parser.add_argument(
        "--message-id-threshold",
        type=positive_int,
        default=DEFAULT_MESSAGE_ID_THRESHOLD,
    )
    parser.add_argument(
        "--total-bytes", type=positive_int, default=DEFAULT_TOTAL_BYTES
    )
    parser.add_argument(
        "--max-line-bytes", type=positive_int, default=DEFAULT_MAX_LINE_BYTES
    )
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return run_selftest()
    if args.window == 0:
        parser.error("--window must be positive")
    if not args.root.exists():
        return 0
    findings = scan(
        args.root,
        window=args.window,
        message_id_threshold=args.message_id_threshold,
        total_bytes_threshold=args.total_bytes,
        max_line_bytes_threshold=args.max_line_bytes,
    )
    report(
        findings,
        window=args.window,
        message_id_threshold=args.message_id_threshold,
        total_bytes_threshold=args.total_bytes,
        max_line_bytes_threshold=args.max_line_bytes,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
