#!/usr/bin/env python3
"""verify-prototype-feedback.py — Verify a prototype-feedback record and its local packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


STATUSES = {
    "received",
    "reviewing",
    "feedback_ready",
    "sent_reported",
    "sent_verified",
    "closed",
}
IDENTITY_AUTHORITIES = {
    "display_name_only",
    "self_identified",
    "official_record",
    "not_provided",
}
MARKDOWN_PATTERNS = (
    (re.compile(r"(?m)^\s{0,3}#{1,6}\s+"), "markdown heading"),
    (re.compile(r"\*\*|__"), "markdown emphasis"),
    (re.compile(r"`"), "markdown code marker"),
    (re.compile(r"\[[^\]\n]+\]\([^\)\n]+\)"), "markdown link"),
    (re.compile(r"(?m)^\s*[-*+]\s+"), "markdown bullet"),
)


def load_record(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is required for YAML records; JSON records use the standard library"
            ) from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("record root must be a mapping/object")
    return data


def resolve_local(root: Path, raw: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(raw, str) or not raw:
        errors.append(f"{label}: expected a non-empty relative path")
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        errors.append(f"{label}: absolute paths are not allowed: {raw}")
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        errors.append(f"{label}: path escapes the packet directory: {raw}")
        return None
    if not resolved.is_file():
        errors.append(f"{label}: file not found: {raw}")
        return None
    return resolved


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_mapping(data: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key}: expected a mapping/object")
        return {}
    return value


def verify_plain_text(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for pattern, name in MARKDOWN_PATTERNS:
        match = pattern.search(text)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"review.feedback_sot:{line}: contains {name}")


def verify_record(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = load_record(path)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        return [f"record: {exc}"]

    if data.get("schema") != "prototype-feedback/v1":
        errors.append("schema: expected prototype-feedback/v1")
    for key in ("id", "title", "received_at", "channel"):
        if not isinstance(data.get(key), str) or not data[key]:
            errors.append(f"{key}: expected a non-empty string")

    status = data.get("status")
    if status not in STATUSES:
        errors.append(f"status: expected one of {sorted(STATUSES)}, got {status!r}")
    if "sent" in data:
        errors.append("sent: duplicate boolean is forbidden; status is the state carrier")

    identity = require_mapping(data, "requester_identity", errors)
    authority = identity.get("authority")
    if authority not in IDENTITY_AUTHORITIES:
        errors.append(
            "requester_identity.authority: expected one of "
            f"{sorted(IDENTITY_AUTHORITIES)}, got {authority!r}"
        )
    observed_label = identity.get("observed_label")
    if authority == "not_provided":
        if observed_label is not None:
            errors.append(
                "requester_identity.observed_label: must be null when authority is not_provided"
            )
    elif not isinstance(observed_label, str) or not observed_label:
        errors.append("requester_identity.observed_label: expected a non-empty observed string")

    root = path.parent
    source = require_mapping(data, "source", errors)
    artifacts = source.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("source.artifacts: expected a non-empty list")
    else:
        artifact_paths: set[str] = set()
        for index, artifact in enumerate(artifacts):
            label = f"source.artifacts[{index}]"
            if not isinstance(artifact, dict):
                errors.append(f"{label}: expected a mapping/object")
                continue
            artifact_path = resolve_local(root, artifact.get("path"), f"{label}.path", errors)
            if isinstance(artifact.get("path"), str):
                artifact_paths.add(artifact["path"])
            expected = artifact.get("sha256")
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                errors.append(f"{label}.sha256: expected 64 lowercase hexadecimal characters")
            elif artifact_path is not None:
                actual = file_sha256(artifact_path)
                if actual != expected:
                    errors.append(f"{label}.sha256: mismatch (actual {actual})")

        preview = source.get("preview")
        if preview is not None:
            if not isinstance(preview, dict):
                errors.append("source.preview: expected a mapping/object")
            else:
                for key in ("decoded_value", "decoded_from", "observed_at"):
                    if not isinstance(preview.get(key), str) or not preview[key]:
                        errors.append(f"source.preview.{key}: expected a non-empty string")
                decoded_from = preview.get("decoded_from")
                if isinstance(decoded_from, str) and decoded_from not in artifact_paths:
                    errors.append("source.preview.decoded_from: must name a source.artifacts path")

    review = require_mapping(data, "review", errors)
    feedback_path = resolve_local(root, review.get("feedback_sot"), "review.feedback_sot", errors)
    for key in ("observed_scope", "not_tested"):
        if not isinstance(review.get(key), list):
            errors.append(f"review.{key}: expected a list")
    for key in ("observed_at", "method"):
        if not isinstance(review.get(key), str) or not review[key]:
            errors.append(f"review.{key}: expected a non-empty string")

    delivery = require_mapping(data, "delivery", errors)
    if "sent" in delivery:
        errors.append("delivery.sent: duplicate boolean is forbidden; status is the state carrier")
    if "clipboard_loaded" in delivery:
        errors.append(
            "delivery.clipboard_loaded: current-state boolean is forbidden; use clipboard_prepared_at"
        )
    sent_at = delivery.get("sent_at")
    verification = delivery.get("verification")
    sent_states = {"sent_reported", "sent_verified"}
    if status in sent_states and not isinstance(sent_at, str):
        errors.append(f"delivery.sent_at: required when status is {status!r}")
    if status not in sent_states and sent_at is not None:
        errors.append(f"delivery.sent_at: must be null while status is {status!r}")
    if status == "sent_verified":
        if not isinstance(verification, dict) or not isinstance(verification.get("method"), str):
            errors.append("delivery.verification.method: required for sent_verified")
    elif verification is not None and status != "closed":
        errors.append("delivery.verification: only sent_verified/closed may carry verification")

    if delivery.get("format") == "plain_text" and feedback_path is not None:
        verify_plain_text(feedback_path, errors)
    return errors


def selftest() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence.png"
        feedback = root / "feedback.md"
        evidence.write_bytes(b"original evidence")
        feedback.write_text("A useful observation.\nA concrete suggestion.\n", encoding="utf-8")
        record = {
            "schema": "prototype-feedback/v1",
            "id": "2099-01-01-example",
            "title": "Example",
            "received_at": "2099-01-01 12:00 UTC",
            "channel": "chat",
            "status": "feedback_ready",
            "requester_identity": {
                "observed_label": "Example",
                "authority": "display_name_only",
            },
            "source": {
                "artifacts": [
                    {
                        "path": evidence.name,
                        "role": "original_screenshot",
                        "sha256": file_sha256(evidence),
                    }
                ]
            },
            "review": {
                "observed_at": "2099-01-01",
                "method": "browser inspection",
                "observed_scope": ["main flow"],
                "not_tested": ["persistence"],
                "feedback_sot": feedback.name,
            },
            "delivery": {
                "target": "chat",
                "format": "plain_text",
                "clipboard_prepared_at": None,
                "sent_at": None,
                "verification": None,
            },
        }
        record_path = root / "record.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        assert verify_record(record_path) == []

        record["source"]["artifacts"][0]["sha256"] = "0" * 64
        record_path.write_text(json.dumps(record), encoding="utf-8")
        assert any("mismatch" in error for error in verify_record(record_path))

        record["source"]["artifacts"][0]["sha256"] = file_sha256(evidence)
        feedback.write_text("**not plain text**\n", encoding="utf-8")
        assert any("markdown emphasis" in error for error in verify_record(record_path))

    print("verify-prototype-feedback.py selftest: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a prototype-feedback record, referenced files, hashes, and delivery state."
    )
    parser.add_argument("record", nargs="?", type=Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if args.record is None:
        parser.error("a record.yaml or record.json path is required")

    errors = verify_record(args.record)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {args.record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
