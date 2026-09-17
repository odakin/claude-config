#!/usr/bin/env python3
"""transcript-images.py — Claude Code の会話記録 (jsonl) から、 user が貼った画像 (画面写真) を file に取り出す

用途: 「開けない」「表示が変」 と画面写真つきで報告された件を後から調べるとき、 写真は transcript に
base64 で入っているだけで、 そのままでは見られない。 取り出して Read tool や Preview で見る。
写真の直前の assistant 発話と並べると、 何を表示した結果の画面かが分かる (--list)。
手順 = conventions/debugging-discipline.md#transcript-screenshots

使い方:
  transcript-images.py <transcript.jsonl | session id の先頭> --list
  transcript-images.py <…> --out DIR [--match 語] [--png]
    --match   写真と同じ message の文字列に語を含むものだけ
    --png     webp 等を png に変換 (macOS の sips があるとき。 Read tool は webp を読めないことがある)
  transcript-images.py --selftest
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


def find_transcript(arg: str) -> str | None:
    if os.path.isfile(arg):
        return arg
    hits = sorted(glob.glob(os.path.expanduser(f"~/.claude/projects/*/{arg}*.jsonl")))
    return hits[0] if len(hits) == 1 else None


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def collect(path: str) -> list[dict]:
    """user message の画像を順に。 [{index, timestamp, k, media_type, data, text, prev_assistant}]"""
    out, prev = [], ""
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue  # 数値や配列だけの行 (JSON としては正しい) も、 壊れた行と同じに飛ばす
            content = (e.get("message") or {}).get("content")
            if e.get("type") == "assistant":
                t = _text_of(content)
                if t.strip():
                    prev = t
                continue
            if e.get("type") != "user" or not isinstance(content, list):
                continue
            k = 0
            for b in content:
                if isinstance(b, dict) and b.get("type") == "image" and isinstance(b.get("source"), dict):
                    src = b["source"]
                    if src.get("type") != "base64" or not src.get("data"):
                        continue
                    out.append({"index": i, "timestamp": e.get("timestamp", ""), "k": k,
                                "media_type": src.get("media_type", "image/png"), "data": src["data"],
                                "text": _text_of(content), "prev_assistant": prev})
                    k += 1
    return out


def write_images(items: list[dict], out_dir: str, png: bool) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for it in items:
        ext = EXT.get(it["media_type"], "bin")
        fp = os.path.join(out_dir, f"{it['index']:05d}-{it['k']}.{ext}")
        try:
            raw = base64.b64decode(it["data"], validate=True)
        except ValueError:
            print(f"skip: 行 {it['index']} の画像 {it['k']} は base64 として読めない", file=sys.stderr)
            continue
        with open(fp, "wb") as f:
            f.write(raw)
        if png and ext != "png" and shutil.which("sips"):
            pp = fp.rsplit(".", 1)[0] + ".png"
            r = subprocess.run(["sips", "-s", "format", "png", fp, "--out", pp], capture_output=True)
            if r.returncode == 0 and os.path.exists(pp):
                fp = pp
        written.append(fp)
    return written


def selftest() -> int:
    fails = []

    def check(label, cond):
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)

    png1 = base64.b64encode(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()
    with tempfile.TemporaryDirectory() as t:
        tr = os.path.join(t, "s.jsonl")
        rows = [
            {"type": "user", "message": {"content": "試稿を開いて"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "こちらです: [a](drafts/a.md)"}]}},
            {"type": "user", "timestamp": "T1", "message": {"content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png1}},
                {"type": "text", "text": "ひらけない"}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            "not json",
            "123",
            '["valid json", "but not an object"]',
        ]
        with open(tr, "w") as f:
            for r in rows:
                f.write((json.dumps(r, ensure_ascii=False) if isinstance(r, dict) else r) + "\n")
        items = collect(tr)
        check("user message の画像を 1 枚拾う (壊れた行・object でない行は飛ばす)", len(items) == 1)
        check("直前の assistant 発話を添える", items and "drafts/a.md" in items[0]["prev_assistant"])
        check("同じ message の文字列を添える", items and items[0]["text"] == "ひらけない")
        out = write_images(items, os.path.join(t, "out"), png=False)
        check("file に書き出す (中身は元の bytes)", len(out) == 1 and open(out[0], "rb").read()[:4] == b"\x89PNG")
        check("id の先頭では見つからない path は None", find_transcript("no-such-session-id-xyz") is None)
        bad = [dict(items[0], data="!!!not-base64", k=1)] + items
        out2 = write_images(bad, os.path.join(t, "out2"), png=False)
        check("base64 として読めない画像は飛ばして残りを書く", len(out2) == 1 and out2[0].endswith("-0.png"))
    print("ALL PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--match", default="")
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args(argv)
    path = find_transcript(a.transcript)
    if not path:
        print(f"transcript が 1 本に定まらない: {a.transcript}", file=sys.stderr)
        return 2
    items = [it for it in collect(path) if a.match in it["text"]]
    if a.list or not a.out:
        for it in items:
            print(f"{it['index']}\t{it['timestamp'][:19]}\t{it['media_type']}\t{it['text'][:60]!r}\t直前: {it['prev_assistant'][:80]!r}")
        return 0 if items else 1
    for fp in write_images(items, a.out, a.png):
        print(fp)
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())
