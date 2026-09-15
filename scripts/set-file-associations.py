#!/usr/bin/env python3
"""set-file-associations.py — Apply or verify declared macOS filename-extension handlers with duti; fail loud on unverifiable state. --selftest included."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from lib.macos_apps import AppBundleInfo, bundle_install_status


EXTENSION_RE = re.compile(r"^\.[A-Za-z0-9][A-Za-z0-9+_-]*$")


@dataclass(frozen=True)
class Mapping:
    bundle_id: str
    extension: str
    conditional: bool = False


Runner = Callable[..., subprocess.CompletedProcess[str]]


def normalize_mapping(bundle_id: str, extension: str, *, conditional: bool = False) -> Mapping:
    bundle = bundle_id.strip()
    ext = extension.strip()
    if not ext.startswith("."):
        ext = "." + ext
    if not bundle or not EXTENSION_RE.fullmatch(ext):
        raise ValueError(f"invalid mapping: bundle={bundle_id!r} extension={extension!r}")
    return Mapping(bundle, ext.lower(), conditional)


def query_handler(duti: str, extension: str, runner: Runner = subprocess.run) -> tuple[str | None, str]:
    result = runner(
        [duti, "-x", extension],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"duti exit {result.returncode}"
        return None, detail
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None, "duti returned no handler lines"
    return lines[-1], ""


def apply_mappings(
    mappings: Sequence[Mapping],
    *,
    check_only: bool,
    duti: str,
    runner: Runner = subprocess.run,
    installed: Callable[[str], tuple[list[AppBundleInfo], list[str]]] = bundle_install_status,
) -> int:
    outcome = 0
    for mapping in mappings:
        if mapping.conditional:
            installed_apps, discovery_errors = installed(mapping.bundle_id)
            if not installed_apps and discovery_errors:
                print(
                    f"UNKNOWN {mapping.extension}: could not determine whether "
                    f"{mapping.bundle_id} is installed: {discovery_errors[0]}",
                    file=sys.stderr,
                )
                outcome = max(outcome, 2)
                continue
            if not installed_apps:
                print(f"SKIP {mapping.extension}: {mapping.bundle_id} is not installed")
                continue
        if not check_only:
            result = runner(
                [duti, "-s", mapping.bundle_id, mapping.extension, "all"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip() or f"duti exit {result.returncode}"
                print(f"ERROR {mapping.extension}: could not set {mapping.bundle_id}: {detail}", file=sys.stderr)
                outcome = max(outcome, 2)
                continue
        current, detail = query_handler(duti, mapping.extension, runner)
        if current is None:
            print(
                f"UNKNOWN {mapping.extension}: handler could not be read back: {detail}",
                file=sys.stderr,
            )
            outcome = max(outcome, 2)
        elif current != mapping.bundle_id:
            print(f"MISMATCH {mapping.extension}: expected={mapping.bundle_id} actual={current}")
            outcome = max(outcome, 1)
        else:
            print(f"OK {mapping.extension}: {current}")
    return outcome


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--set", action="append", nargs=2, metavar=("BUNDLE_ID", "EXT"), default=[])
    result.add_argument(
        "--set-if-installed",
        action="append",
        nargs=2,
        metavar=("BUNDLE_ID", "EXT"),
        default=[],
    )
    result.add_argument("--check", action="store_true", help="read and compare without changing handlers")
    result.add_argument("--duti", help="path to duti (default: PATH lookup)")
    result.add_argument("--selftest", action="store_true")
    return result


def run_selftest() -> int:
    state: dict[str, str] = {".old": "example.other"}
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(argv))
        if argv[1] == "-s":
            if argv[3] == ".broken":
                return subprocess.CompletedProcess(argv, 9, "", "set failed")
            state[argv[3]] = argv[2]
            return subprocess.CompletedProcess(argv, 0, "", "")
        extension = argv[2]
        if extension == ".unknown":
            return subprocess.CompletedProcess(argv, 1, "", "no handler")
        bundle = state.get(extension, "example.other")
        return subprocess.CompletedProcess(argv, 0, f"Demo.app\n/Applications/Demo.app\n{bundle}\n", "")

    checks: list[tuple[str, bool]] = []
    mapping = normalize_mapping("example.current", "demo")
    rc = apply_mappings([mapping], check_only=False, duti="duti", runner=fake_runner)
    checks.append(("apply sets and reads back", rc == 0 and state[".demo"] == "example.current"))
    checks.append(("duti argv is structured", calls[:2] == [
        ("duti", "-s", "example.current", ".demo", "all"),
        ("duti", "-x", ".demo"),
    ]))
    mismatch = apply_mappings(
        [normalize_mapping("example.current", ".old")],
        check_only=True,
        duti="duti",
        runner=fake_runner,
    )
    checks.append(("check-only mismatch is exit 1", mismatch == 1))
    unknown = apply_mappings(
        [normalize_mapping("example.current", ".unknown")],
        check_only=True,
        duti="duti",
        runner=fake_runner,
    )
    checks.append(("unreadable handler is exit 2", unknown == 2))
    broken = apply_mappings(
        [normalize_mapping("example.current", ".broken")],
        check_only=False,
        duti="duti",
        runner=fake_runner,
    )
    checks.append(("failed write is exit 2", broken == 2))
    conditional = apply_mappings(
        [normalize_mapping("example.missing", ".optional", conditional=True)],
        check_only=False,
        duti="duti",
        runner=fake_runner,
        installed=lambda _bundle: ([], []),
    )
    checks.append(("conditional mapping skips absent app", conditional == 0 and ".optional" not in state))
    conditional_unknown = apply_mappings(
        [normalize_mapping("example.unknown", ".conditional", conditional=True)],
        check_only=False,
        duti="duti",
        runner=fake_runner,
        installed=lambda _bundle: ([], ["permission denied"]),
    )
    checks.append(("conditional discovery error is exit 2", conditional_unknown == 2))
    try:
        normalize_mapping("example.current", "../bad")
    except ValueError:
        checks.append(("invalid extension is rejected before a write", True))
    else:
        checks.append(("invalid extension is rejected before a write", False))

    failures = [name for name, passed in checks if not passed]
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    print(f"selftest: {len(checks) - len(failures)} passed, {len(failures)} failed")
    return 1 if failures else 0


def main() -> int:
    args = parser().parse_args()
    if args.selftest:
        return run_selftest()
    if sys.platform != "darwin":
        print("ERROR: file associations are supported only on macOS", file=sys.stderr)
        return 2
    try:
        mappings = [normalize_mapping(*item) for item in args.set]
        mappings.extend(normalize_mapping(*item, conditional=True) for item in args.set_if_installed)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not mappings:
        print("ERROR: pass at least one --set or --set-if-installed mapping", file=sys.stderr)
        return 2
    duti = args.duti or shutil.which("duti")
    if not duti:
        print("ERROR: duti is required (for Homebrew: brew install duti)", file=sys.stderr)
        return 2
    return apply_mappings(mappings, check_only=args.check, duti=duti)


if __name__ == "__main__":
    raise SystemExit(main())
