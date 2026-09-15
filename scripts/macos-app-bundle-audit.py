#!/usr/bin/env python3
"""macos-app-bundle-audit.py — Inventory side-by-side macOS app bundles by name or bundle identifier. --selftest included."""

from __future__ import annotations

import argparse
import json
import plistlib
import sys
import tempfile
from pathlib import Path

from lib.macos_apps import discover_app_bundles


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--match", help="case-insensitive substring of the .app directory name")
    result.add_argument("--bundle-id", help="exact CFBundleIdentifier")
    result.add_argument("--root", action="append", type=Path, help="search root (repeatable)")
    result.add_argument("--max-depth", type=int, default=4)
    result.add_argument("--json", action="store_true", help="emit JSON")
    result.add_argument("--selftest", action="store_true")
    return result


def render_human(records: list[dict[str, object]]) -> None:
    for record in records:
        print(record["path"])
        print(f"  display={record['display_name']}")
        print(f"  version={record['version']} build={record['build']}")
        print(f"  bundle={record['bundle_id']} executable={record['executable']}")
        extensions = ",".join(record["extensions"]) or "-"
        print(f"  extensions={extensions}")


def write_fixture(path: Path, *, version: str, bundle_id: str, extension: str) -> None:
    contents = path / "Contents"
    contents.mkdir(parents=True)
    info = {
        "CFBundleDisplayName": path.stem,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version + ".1",
        "CFBundleIdentifier": bundle_id,
        "CFBundleExecutable": path.stem,
        "UTExportedTypeDeclarations": [
            {
                "UTTypeIdentifier": bundle_id + ".document",
                "UTTypeTagSpecification": {"public.filename-extension": [extension]},
            }
        ],
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle)


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="macos-app-audit-") as temporary:
        root = Path(temporary)
        write_fixture(
            root / "Orbit.app", version="1.0", bundle_id="example.orbit.legacy", extension="orb"
        )
        write_fixture(
            root / "Orbit Creator Studio.app",
            version="2.0",
            bundle_id="example.orbit",
            extension="orb",
        )
        matches, errors = discover_app_bundles(roots=[root], name_contains="orbit")
        checks.append(("substring finds differently named old and new bundles", len(matches) == 2))
        checks.append(("valid fixtures have no parse errors", not errors))
        checks.append(("versions remain attached to their bundle ids", {
            item.bundle_id: item.version for item in matches
        } == {"example.orbit.legacy": "1.0", "example.orbit": "2.0"}))
        checks.append(("declared extension is extracted", all(item.extensions == ("orb",) for item in matches)))
        current, _ = discover_app_bundles(roots=[root], bundle_id="example.orbit")
        checks.append(("exact bundle-id filter selects current app", len(current) == 1 and current[0].version == "2.0"))
        missing, _ = discover_app_bundles(roots=[root], name_contains="absent")
        checks.append(("absent name stays empty", not missing))

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
        print("ERROR: this audit is for macOS", file=sys.stderr)
        return 2
    if not args.match and not args.bundle_id:
        print("ERROR: pass --match or --bundle-id", file=sys.stderr)
        return 2
    if args.max_depth < 0:
        print("ERROR: --max-depth must be non-negative", file=sys.stderr)
        return 2

    records, errors = discover_app_bundles(
        roots=args.root,
        name_contains=args.match,
        bundle_id=args.bundle_id,
        max_depth=args.max_depth,
    )
    payload = [record.to_dict() for record in records]
    if args.json:
        print(json.dumps({"apps": payload, "errors": errors}, ensure_ascii=False, indent=2))
    else:
        render_human(payload)
        for error in errors:
            print(f"UNKNOWN: {error}", file=sys.stderr)
    if errors:
        return 2
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
