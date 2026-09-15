"""macos_apps.py — Discover macOS app bundles and read their declared identity without launching them."""

from __future__ import annotations

import os
import plistlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AppBundleInfo:
    path: str
    display_name: str
    version: str
    build: str
    bundle_id: str
    executable: str
    extensions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def default_app_roots(home: Path | None = None) -> tuple[Path, ...]:
    user_home = home if home is not None else Path.home()
    return (
        Path("/Applications"),
        Path("/System/Applications"),
        user_home / "Applications",
    )


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _declared_extensions(info: dict[str, object]) -> tuple[str, ...]:
    extensions: set[str] = set()
    declaration_keys = ("UTExportedTypeDeclarations", "UTImportedTypeDeclarations")
    for key in declaration_keys:
        declarations = info.get(key, [])
        if not isinstance(declarations, list):
            continue
        for declaration in declarations:
            if not isinstance(declaration, dict):
                continue
            tags = declaration.get("UTTypeTagSpecification", {})
            if not isinstance(tags, dict):
                continue
            values = tags.get("public.filename-extension", [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                extensions.update(
                    value.lower().lstrip(".")
                    for value in values
                    if isinstance(value, str) and value.strip(".")
                )
    return tuple(sorted(extensions))


def read_app_bundle(path: Path) -> AppBundleInfo:
    plist_path = path / "Contents" / "Info.plist"
    with plist_path.open("rb") as handle:
        info = plistlib.load(handle)
    if not isinstance(info, dict):
        raise ValueError(f"Info.plist is not a dictionary: {plist_path}")
    display_name = (
        _string(info.get("CFBundleDisplayName"))
        or _string(info.get("CFBundleName"))
        or path.stem
    )
    return AppBundleInfo(
        path=str(path),
        display_name=display_name,
        version=_string(info.get("CFBundleShortVersionString")),
        build=_string(info.get("CFBundleVersion")),
        bundle_id=_string(info.get("CFBundleIdentifier")),
        executable=_string(info.get("CFBundleExecutable")),
        extensions=_declared_extensions(info),
    )


def candidate_app_paths(roots: Iterable[Path], max_depth: int = 4) -> tuple[list[Path], list[str]]:
    candidates: list[Path] = []
    errors: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        root_parts = len(root.parts)

        def record_error(error: OSError) -> None:
            errors.append(f"{error.filename or root}: {error.strerror or error}")

        for current, directories, _files in os.walk(root, onerror=record_error):
            current_path = Path(current)
            depth = len(current_path.parts) - root_parts
            app_directories = [name for name in directories if name.lower().endswith(".app")]
            candidates.extend(current_path / name for name in app_directories)
            directories[:] = [
                name for name in directories if not name.lower().endswith(".app")
            ]
            if depth >= max_depth:
                directories.clear()
    return sorted(set(candidates), key=lambda item: str(item).casefold()), errors


def discover_app_bundles(
    *,
    roots: Iterable[Path] | None = None,
    name_contains: str | None = None,
    bundle_id: str | None = None,
    max_depth: int = 4,
) -> tuple[list[AppBundleInfo], list[str]]:
    selected_roots = tuple(roots) if roots is not None else default_app_roots()
    needle = name_contains.casefold() if name_contains else None
    matches: list[AppBundleInfo] = []
    candidates, errors = candidate_app_paths(selected_roots, max_depth=max_depth)
    for path in candidates:
        if needle is not None and needle not in path.name.casefold():
            continue
        try:
            info = read_app_bundle(path)
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        if bundle_id is not None and info.bundle_id != bundle_id:
            continue
        matches.append(info)
    return matches, errors


def bundle_is_installed(bundle_id: str, roots: Iterable[Path] | None = None) -> bool:
    matches, _errors = bundle_install_status(bundle_id, roots=roots)
    return bool(matches)


def bundle_install_status(
    bundle_id: str, roots: Iterable[Path] | None = None
) -> tuple[list[AppBundleInfo], list[str]]:
    return discover_app_bundles(roots=roots, bundle_id=bundle_id)
