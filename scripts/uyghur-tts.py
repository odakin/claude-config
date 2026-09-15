#!/usr/bin/env python3
"""uyghur-tts.py — Generate Uyghur speech through the public Idirak/MMS-TTS endpoint.

The pronunciation and evidence workflow is owned by
conventions/pronunciation-verification.md#uyghur-tts-route.  This script is the
reusable API route: it accepts Uyghur text, prints the returned audio URL, and
optionally saves the WAV without overwriting an existing file by default.

Usage:
  python3 scripts/uyghur-tts.py "ياخشىمۇسىز"
  printf '%s\n' 'ياخشىمۇسىز' | python3 scripts/uyghur-tts.py
  python3 scripts/uyghur-tts.py "ياخشىمۇسىز" --output /tmp/uyghur.wav
  python3 scripts/uyghur-tts.py "ياخشىمۇسىز" --dry-run --json
  python3 scripts/uyghur-tts.py --selftest

The text is sent to a third-party service.  Do not send secrets, unpublished
material, or personal data that the user has not explicitly placed in scope.
Generated URLs are ephemeral delivery artifacts, not durable records.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_BASE = "https://uyghurai-uyghurai-tts.hf.space"
API_HOST = urllib.parse.urlparse(API_BASE).hostname
SPEAK_PATH = "/tts/speak"
USER_AGENT = "claude-config-uyghur-tts/1.0"
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class TtsError(RuntimeError):
    """A bounded, user-facing failure from the remote TTS route."""


def ranged_float(name: str, minimum: float, maximum: float):
    def parse(value: str) -> float:
        try:
            number = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{name} must be a number") from exc
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
        return number

    return parse


def build_payload(text: str, voice: str, speed: float, noise_scale: float) -> dict[str, Any]:
    clean = text.strip()
    if not clean:
        raise TtsError("input text is empty")
    return {"text": clean, "voice": voice, "speed": speed, "noiseScale": noise_scale}


def _bounded_detail(raw: bytes) -> str:
    text = raw[:2048].decode("utf-8", "replace").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text[:300]
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error")
        if isinstance(detail, list):
            detail = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in detail)
        if detail:
            return str(detail)[:300]
    return text[:300]


def post_json(path: str, payload: dict[str, Any], timeout: float) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        API_BASE + path,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = _bounded_detail(exc.read())
        raise TtsError(f"TTS API returned HTTP {exc.code}" + (f": {detail}" if detail else "")) from exc
    except urllib.error.URLError as exc:
        raise TtsError(f"TTS API connection failed: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TtsError("TTS API returned invalid JSON") from exc


def checked_audio_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TtsError("TTS API response has no audio URL")
    url = urllib.parse.urljoin(API_BASE + "/", value.strip())
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != API_HOST:
        raise TtsError("TTS API returned an audio URL outside the trusted host")
    return url


def normalize_result(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("success") is not True:
        raise TtsError("TTS API did not report success")
    result = {
        "audio_url": checked_audio_url(raw.get("audioUrl")),
        "normalized_text": raw.get("normalizedText", ""),
        "voice": raw.get("voice", "default"),
        "speed": raw.get("speed", 1.0),
        "format": raw.get("format", "wav"),
    }
    if not isinstance(result["normalized_text"], str):
        raise TtsError("TTS API returned an invalid normalized text field")
    return result


def synthesize(text: str, voice: str, speed: float, noise_scale: float, timeout: float) -> dict[str, Any]:
    payload = build_payload(text, voice, speed, noise_scale)
    return normalize_result(post_json(SPEAK_PATH, payload, timeout))


def read_audio(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            checked_audio_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in {"audio/wav", "audio/x-wav", "application/octet-stream"}:
                raise TtsError(f"audio download returned unexpected content type: {content_type}")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_AUDIO_BYTES:
                raise TtsError(f"audio download exceeds {MAX_AUDIO_BYTES} bytes")
            data = response.read(MAX_AUDIO_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise TtsError(f"audio download returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TtsError(f"audio download failed: {exc.reason}") from exc
    if len(data) > MAX_AUDIO_BYTES:
        raise TtsError(f"audio download exceeds {MAX_AUDIO_BYTES} bytes")
    if not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        raise TtsError("downloaded data is not a WAV file")
    return data


def write_audio(path: Path, data: bytes, force: bool = False) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not force:
        try:
            with path.open("xb") as handle:
                handle.write(data)
        except FileExistsError as exc:
            raise TtsError(f"refusing to overwrite existing file: {path} (use --force)") from exc
        return

    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def selftest() -> int:
    failures: list[str] = []

    def expect(name: str, condition: bool) -> None:
        print(("  [PASS] " if condition else "  [FAIL] ") + name)
        if not condition:
            failures.append(name)

    payload = build_payload("  ياخشىمۇسىز  ", "default", 1.0, 0.667)
    expect("payload strips outer whitespace and preserves Uyghur text", payload["text"] == "ياخشىمۇسىز")
    expect("payload uses the public client field names", set(payload) == {"text", "voice", "speed", "noiseScale"})

    result = normalize_result(
        {
            "success": True,
            "audioUrl": "/outputs/example.wav",
            "normalizedText": "ياخشىمۇسىز",
            "voice": "default",
            "speed": 1.0,
            "format": "wav",
        }
    )
    expect("relative audio URL is pinned to the trusted HTTPS host", result["audio_url"] == API_BASE + "/outputs/example.wav")

    for name, raw in [
        ("unsuccessful response", {"success": False, "audioUrl": "/outputs/x.wav"}),
        ("foreign audio host", {"success": True, "audioUrl": "https://example.com/x.wav"}),
        ("missing audio URL", {"success": True}),
        ("invalid normalized text", {"success": True, "audioUrl": "/outputs/x.wav", "normalizedText": []}),
    ]:
        try:
            normalize_result(raw)
        except TtsError:
            rejected = True
        else:
            rejected = False
        expect(f"rejects {name}", rejected)

    wav = b"RIFF" + (8).to_bytes(4, "little") + b"WAVEfmt "
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "sample.wav"
        write_audio(target, wav)
        expect("writes a new output file", target.read_bytes() == wav)
        try:
            write_audio(target, b"new")
        except TtsError:
            refused = True
        else:
            refused = False
        expect("refuses overwrite without --force", refused and target.read_bytes() == wav)
        write_audio(target, b"new", force=True)
        expect("--force replaces through a temporary file", target.read_bytes() == b"new")

    print("selftest:", "ALL PASS" if not failures else f"FAILED ({len(failures)})")
    return 0 if not failures else 1


def input_text(argument: str | None) -> str:
    if argument is not None:
        return argument
    if sys.stdin.isatty():
        raise TtsError("pass text as an argument or pipe it on stdin")
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("text", nargs="?", help="Uyghur text; when omitted, read stdin")
    parser.add_argument("--voice", default="default")
    parser.add_argument("--speed", type=ranged_float("speed", 0.5, 2.0), default=1.0)
    parser.add_argument("--noise-scale", type=ranged_float("noise-scale", 0.1, 1.5), default=0.667)
    parser.add_argument("--timeout", type=ranged_float("timeout", 1.0, 120.0), default=30.0)
    parser.add_argument("--output", type=Path, help="save the returned WAV")
    parser.add_argument("--force", action="store_true", help="allow --output to replace an existing file")
    parser.add_argument("--json", action="store_true", help="print the structured result")
    parser.add_argument("--dry-run", action="store_true", help="print request details without transmitting text")
    parser.add_argument("--selftest", action="store_true", help="run network-free tests")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if args.force and not args.output:
        parser.error("--force requires --output")

    try:
        text = input_text(args.text)
        payload = build_payload(text, args.voice, args.speed, args.noise_scale)
        if args.dry_run:
            result: dict[str, Any] = {"endpoint": API_BASE + SPEAK_PATH, "payload": payload, "sent": False}
        else:
            result = synthesize(text, args.voice, args.speed, args.noise_scale, args.timeout)
            if args.output:
                audio = read_audio(result["audio_url"], args.timeout)
                write_audio(args.output, audio, args.force)
                result["output"] = str(args.output.expanduser().resolve())
                result["bytes"] = len(audio)
    except TtsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json or args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.output:
        print(result["output"])
    else:
        print(result["audio_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
