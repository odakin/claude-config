#!/usr/bin/env python3
"""whisper-transcribe.py — 録音を whisper.cpp で文字起こしし、 同じ語の繰り返し (ループ) が出た区間を自動で転写し直す。

長い録音 (講義・会議) を whisper で一括転写すると、 **話している区間でも** 同じ 1 文が数分〜数十分続く
出力 (ループ) になることがある。 原因は前の出力を次の区間の文脈に持ち越すこと。 無音区間の
ハルシネーションと違って音はあるので、 その区間だけ **文脈を持ち越さない設定 (`-mc 0`) で転写し直す**と
中身が戻る (実測)。 本 script はこれを 1 コマンドにする:

  1. 音声を 16 kHz mono wav にする (ffmpeg)
  2. whisper-cli で全体を転写 (SRT)
  3. 同じ文が --min-run 回以上続く区間を探す
  4. その区間 (前後 --pad 秒を足す) を `-mc 0` で転写し直し、 元の区間の行と差し替える
  5. 差し替えた後もループが残る区間は「未解決」 として見出しに書く (= 無音・非音声の可能性。 引用しない)
  6. `[h:mm:ss] 本文` の行で書き出す。 見出しに源・model・差し替えた区間・未解決の区間を書く

一般則 (ループ・無音のハルシネーションの扱い、 聞き取れない語を推測で埋めない) =
conventions/audio-transcription.md (#hallucination-runs / #loop-runs-in-speech)。

使い方:
  whisper-transcribe.py <音声 (m4a/mp3/wav…)> -o <out.txt> [--lang ja] [--model <ggml.bin>]
                        [--title "見出しの 1 行目"] [--srt <out.srt>] [--work <dir>]
  whisper-transcribe.py selftest     # 通信も whisper も使わない部品の自己検査

必要なもの: ffmpeg / whisper-cli (whisper.cpp) / model file
  (既定 = ~/.cache/whisper-cpp/ggml-large-v3-turbo.bin、 --model か env WHISPER_MODEL で変える)。
所要時間: whisper の速さ次第 (Apple Silicon で 80 分の音声がおよそ 10〜15 分)。 長いので background で回す。
⚠️ 機械転写 = 固有名詞・数字は別の源 (板書・資料) と突き合わせて使う。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", str(Path.home() / ".cache/whisper-cpp/ggml-large-v3-turbo.bin"))


# ---- 通信・外部 process を使わない部品 (selftest の対象) ----

def ms(t: str) -> int:
    h, m, rest = t.strip().split(":")
    s, frac = rest.split(",")
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac)


def parse_srt(text: str) -> list[tuple[int, int, str]]:
    out = []
    for b in text.strip().split("\n\n"):
        p = b.strip().split("\n")
        if len(p) < 3 or " --> " not in p[1]:
            continue
        a, z = p[1].split(" --> ")
        out.append((ms(a), ms(z), " ".join(p[2:]).strip()))
    return out


def find_loop_runs(blocks, min_run: int) -> list[tuple[int, int, str, int]]:
    """同じ本文が min_run 回以上続く区間 → (開始 ms, 終了 ms, 本文, 回数)。 空行は数えない。"""
    runs, i = [], 0
    while i < len(blocks):
        j = i
        while j + 1 < len(blocks) and blocks[j + 1][2] == blocks[i][2]:
            j += 1
        if blocks[i][2] and j - i + 1 >= min_run:
            runs.append((blocks[i][0], blocks[j][1], blocks[i][2], j - i + 1))
        i = j + 1
    return runs


def windows(runs, pad_ms: int, total_ms: int) -> list[tuple[int, int]]:
    """ループ区間に前後 pad を足し、 重なる窓はまとめる。"""
    ws = sorted((max(0, a - pad_ms), min(total_ms, z + pad_ms)) for a, z, _, _ in runs)
    merged: list[list[int]] = []
    for a, z in ws:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], z)
        else:
            merged.append([a, z])
    return [(a, z) for a, z in merged]


def splice(base, redo_by_window: dict) -> list[tuple[int, int, str]]:
    """base の行のうち窓の中で始まるものを捨て、 窓ごとの転写し直しを入れる (時刻順)。"""
    kept = [b for b in base if not any(a <= b[0] < z for a, z in redo_by_window)]
    for (a, z), blocks in redo_by_window.items():
        kept += [b for b in blocks if a <= b[0] < z]
    return sorted(kept)


def hms(t_ms: int) -> str:
    s = t_ms // 1000
    return f"{s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}"


def to_srt(blocks) -> str:
    def f(t):
        return f"{t // 3600000:02d}:{t // 60000 % 60:02d}:{t // 1000 % 60:02d},{t % 1000:03d}"
    return "\n\n".join(f"{i}\n{f(a)} --> {f(z)}\n{t}" for i, (a, z, t) in enumerate(blocks, 1)) + "\n"


# ---- 外部 process ----

def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def whisper(model: str, lang: str, wav: Path, stem: Path, extra: list[str]) -> list[tuple[int, int, str]]:
    run(["whisper-cli", "-m", model, "-l", lang, "-osrt", "-of", str(stem), "-np", *extra, str(wav)])
    return parse_srt(Path(f"{stem}.srt").read_text())


def transcribe(args) -> int:
    src = Path(args.audio).expanduser()
    work_ctx = tempfile.TemporaryDirectory() if not args.work else None
    work = Path(args.work or work_ctx.name)
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "audio16k.wav"
    print(f"[1/4] 16 kHz に変換: {src.name}", flush=True)
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
    print("[2/4] 全体を転写 (長い)", flush=True)
    base = whisper(args.model, args.lang, wav, work / "full", [])
    total = base[-1][1] if base else 0
    runs = find_loop_runs(base, args.min_run)
    ws = windows(runs, args.pad * 1000, total)
    print(f"[3/4] ループ {len(runs)} 区間 → 転写し直す窓 {len(ws)} 個", flush=True)
    redo = {}
    for k, (a, z) in enumerate(ws):
        print(f"      {hms(a)}–{hms(z)} を -mc 0 で", flush=True)
        redo[(a, z)] = whisper(args.model, args.lang, wav, work / f"redo{k}", ["-mc", "0", "-ot", str(a), "-d", str(z - a)])
    merged = splice(base, redo)
    left = find_loop_runs(merged, args.min_run)
    head = [f"# {args.title or src.stem}",
            f"# 源 = {src.name} を whisper.cpp ({Path(args.model).name}, -l {args.lang}) で機械転写 (whisper-transcribe.py)"]
    if ws:
        head.append("# ループが出た区間を文脈を持ち越さない設定 (-mc 0) で転写し直して差し替えた: "
                    + " / ".join(f"{hms(a)}–{hms(z)}" for a, z in ws))
    if left:
        head.append("# ⚠️ 差し替えても繰り返しが残った区間 (無音・非音声の可能性、 引用しない): "
                    + " / ".join(f"{hms(a)}–{hms(z)} 「{t[:20]}」×{n}" for a, z, t, n in left))
    head.append("# ⚠️ 機械転写 = 固有名詞・数字は別の源と突き合わせて使う")
    out = Path(args.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head) + "\n" + "\n".join(f"[{hms(a)}] {t}" for a, _, t in merged) + "\n")
    if args.srt:
        Path(args.srt).expanduser().write_text(to_srt(merged))
    print(f"[4/4] {out} ({len(merged)} 行、 未解決のループ {len(left)} 区間)", flush=True)
    if work_ctx:
        work_ctx.cleanup()
    return 0


def selftest() -> int:
    fails = []

    def check(cond, name):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    srt = "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n\n2\n00:01:00,500 --> 00:01:02,000\n二行\n目\n"
    b = parse_srt(srt)
    check(b == [(1000, 2000, "こんにちは"), (60500, 62000, "二行 目")], "SRT を (開始, 終了, 本文) にする (複数行は空白でつなぐ)")
    blocks = [(i * 1000, i * 1000 + 900, t) for i, t in enumerate(["a", "b", "x", "x", "x", "x", "c", "y", "y"])]
    runs = find_loop_runs(blocks, 3)
    check(runs == [(2000, 5900, "x", 4)], "min_run 回以上続く同じ本文だけをループとする")
    check(windows([(10000, 20000, "x", 5), (25000, 30000, "y", 5)], 5000, 100000) == [(5000, 35000)], "重なる窓はまとめる")
    check(windows([(1000, 2000, "x", 5)], 5000, 3000) == [(0, 3000)], "窓は 0 と全長で切る")
    base = [(0, 900, "a"), (2000, 2900, "x"), (3000, 3900, "x"), (6000, 6900, "c")]
    got = splice(base, {(1500, 5000): [(1800, 2500, "b1"), (2600, 3400, "b2"), (5500, 5900, "外")]})
    check(got == [(0, 900, "a"), (1800, 2500, "b1"), (2600, 3400, "b2"), (6000, 6900, "c")], "窓の中の行を転写し直しで差し替え、 窓の外の出力は捨てる")
    check(hms(3723000) == "1:02:03", "時刻を h:mm:ss に")
    check(parse_srt(to_srt(base)) == base, "SRT の書き出しと読み込みが往復する")
    print("whisper-transcribe selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description="whisper.cpp で文字起こしし、 ループ区間を -mc 0 で転写し直す")
    ap.add_argument("audio")
    ap.add_argument("-o", "--output", required=True, help="書き出す txt")
    ap.add_argument("--lang", default="ja")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--title", help="見出しの 1 行目")
    ap.add_argument("--srt", help="差し替え後の SRT も書く path")
    ap.add_argument("--work", help="中間 file を残す dir (既定 = 一時 dir、 終わったら消す)")
    ap.add_argument("--min-run", type=int, default=8, help="同じ本文が何回続いたらループとみなすか (既定 8)")
    ap.add_argument("--pad", type=int, default=10, help="転写し直す窓の前後に足す秒 (既定 10)")
    return transcribe(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
