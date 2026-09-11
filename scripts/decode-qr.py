#!/usr/bin/env python3
"""decode-qr.py — Decode QR payloads from screenshots without opening them."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_cv() -> tuple[Any, Any]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV and NumPy are required (Python packages: opencv-python, numpy)"
        ) from exc
    return cv2, np


def read_image(path: Path, cv2: Any, np: Any) -> Any:
    try:
        raw = np.fromfile(str(path), dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"cannot read image: {exc}") from exc
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("not a readable image")
    return image


def decode_image(image: Any, cv2: Any) -> list[str]:
    detector = cv2.QRCodeDetector()
    values: list[str] = []

    try:
        ok, decoded, _points, _straight = detector.detectAndDecodeMulti(image)
    except (AttributeError, cv2.error):
        ok, decoded = False, ()
    if ok:
        values.extend(value for value in decoded if value)

    if not values:
        value, _points, _straight = detector.detectAndDecode(image)
        if value:
            values.append(value)

    return list(dict.fromkeys(values))


def decode_paths(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    cv2, np = load_cv()
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            image = read_image(path, cv2, np)
            values = decode_image(image, cv2)
            if not values:
                raise ValueError("no decodable QR code found")
            results.append({"source": str(path), "payloads": values})
        except (OSError, ValueError, cv2.error) as exc:
            errors.append(f"{path}: {exc}")
    return results, errors


def selftest() -> int:
    try:
        cv2, _np = load_cv()
    except RuntimeError as exc:
        print(f"SKIP decode-qr.py selftest: {exc}")
        return 0

    payload = "https://example.invalid/prototype-feedback"
    encoder = cv2.QRCodeEncoder_create()
    qr = encoder.encode(payload)
    image = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    image = cv2.resize(image, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    assert decode_image(image, cv2) == [payload]
    print("decode-qr.py selftest: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode QR payloads from local images. Payloads are printed, never opened."
    )
    parser.add_argument("images", nargs="*", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.images:
        parser.error("at least one image is required")

    try:
        results, errors = decode_paths(args.images)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            for payload in result["payloads"]:
                print(payload)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
