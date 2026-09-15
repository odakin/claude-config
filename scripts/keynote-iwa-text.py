#!/usr/bin/env python3
"""Extract a text inventory from Keynote .key slide IWA archives (layout/order not reconstructed)."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path


SLIDE_IWA_RE = re.compile(r"^Index/Slide(?:-\d+)?\.iwa$")


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("truncated Snappy varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift >= 64:
            raise ValueError("Snappy varint is too long")


def decompress_snappy_block(data: bytes) -> bytes:
    expected, offset = read_varint(data, 0)
    output = bytearray()
    while offset < len(data):
        tag = data[offset]
        offset += 1
        kind = tag & 0x03
        if kind == 0:
            length_code = tag >> 2
            if length_code < 60:
                length = length_code + 1
            else:
                extra = length_code - 59
                if offset + extra > len(data):
                    raise ValueError("truncated Snappy literal length")
                length = int.from_bytes(data[offset : offset + extra], "little") + 1
                offset += extra
            if offset + length > len(data):
                raise ValueError("truncated Snappy literal")
            output.extend(data[offset : offset + length])
            offset += length
            continue

        if kind == 1:
            length = 4 + ((tag >> 2) & 0x07)
            if offset >= len(data):
                raise ValueError("truncated Snappy COPY_1")
            distance = ((tag & 0xE0) << 3) | data[offset]
            offset += 1
        else:
            width = 2 if kind == 2 else 4
            length = 1 + (tag >> 2)
            if offset + width > len(data):
                raise ValueError(f"truncated Snappy COPY_{width}")
            distance = int.from_bytes(data[offset : offset + width], "little")
            offset += width
        if not 0 < distance <= len(output):
            raise ValueError(f"invalid Snappy copy distance {distance}")
        for _ in range(length):
            output.append(output[-distance])

    if len(output) != expected:
        raise ValueError(f"Snappy size mismatch: expected {expected}, got {len(output)}")
    return bytes(output)


def decompress_iwa(data: bytes) -> bytes:
    """Decode Keynote's repeated type-0, 24-bit-length Snappy frames."""
    offset = 0
    output = bytearray()
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError("truncated IWA frame header")
        frame_type = data[offset]
        length = int.from_bytes(data[offset + 1 : offset + 4], "little")
        offset += 4
        if frame_type != 0:
            raise ValueError(f"unsupported IWA frame type {frame_type}")
        if offset + length > len(data):
            raise ValueError("truncated IWA frame payload")
        output.extend(decompress_snappy_block(data[offset : offset + length]))
        offset += length
    return bytes(output)


def text_runs(data: bytes, min_chars: int = 4, japanese_only: bool = False) -> list[str]:
    decoded = data.decode("utf-8", "replace")
    pattern = re.compile(rf"[^\x00-\x1f\x7f-\x9f\ufffd]{{{min_chars},}}")
    runs: list[str] = []
    for match in pattern.finditer(decoded):
        value = match.group(0).strip()
        if not value or not any(ch.isalpha() or ch.isdigit() for ch in value):
            continue
        if japanese_only and not re.search(r"[ぁ-んァ-ヶ一-龠々]", value):
            continue
        if value not in runs:
            runs.append(value)
    return runs


def extract(path: Path, min_chars: int = 4, japanese_only: bool = False) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(path)
    records = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist() if SLIDE_IWA_RE.fullmatch(name))
        if not names:
            raise ValueError("no Index/Slide*.iwa archives found")
        for name in names:
            strings = text_runs(decompress_iwa(archive.read(name)), min_chars, japanese_only)
            if strings:
                records.append({"archive": name, "strings": strings})
    return records


def render_markdown(records: list[dict]) -> str:
    lines = [
        "<!-- Text inventory only: IWA archive names are not presentation order. -->",
        "",
    ]
    for record in records:
        lines.append(f"## {record['archive']}")
        lines.append("")
        lines.extend(f"- {value}" for value in record["strings"])
        lines.append("")
    return "\n".join(lines)


def selftest() -> int:
    literal = bytes([5, 16]) + b"hello"
    assert decompress_snappy_block(literal) == b"hello"

    copy = bytes([8, 12]) + b"abcd" + bytes([1, 4])
    assert decompress_snappy_block(copy) == b"abcdabcd"

    payload = "題名\x00English text\x00短".encode()
    block = bytes([len(payload), (len(payload) - 1) << 2]) + payload
    framed = bytes([0]) + len(block).to_bytes(3, "little") + block
    assert decompress_iwa(framed) == payload
    assert text_runs(payload, 2, japanese_only=True) == ["題名"]

    with tempfile.TemporaryDirectory() as directory:
        deck = Path(directory) / "fixture.key"
        with zipfile.ZipFile(deck, "w") as archive:
            archive.writestr("Index/Slide-1.iwa", framed)
            archive.writestr("Index/Document.iwa", framed)
        records = extract(deck, min_chars=2, japanese_only=True)
        assert records == [{"archive": "Index/Slide-1.iwa", "strings": ["題名"]}]
        assert "presentation order" in render_markdown(records)
    print("ALL PASS (Keynote IWA text extractor)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deck", nargs="?", type=Path, help="Keynote .key package")
    parser.add_argument("--output", type=Path, help="write output instead of stdout")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    parser.add_argument("--japanese-only", action="store_true", help="keep runs containing Japanese text")
    parser.add_argument("--min-chars", type=int, default=4)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.deck is None:
        parser.error("DECK is required unless --selftest is used")
    if args.min_chars < 1:
        parser.error("--min-chars must be positive")
    records = extract(args.deck, args.min_chars, args.japanese_only)
    content = json.dumps(records, ensure_ascii=False, indent=2) + "\n" if args.json else render_markdown(records)
    if args.output:
        if args.output.exists():
            raise FileExistsError(f"output exists: {args.output}")
        args.output.write_text(content)
    else:
        sys.stdout.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
