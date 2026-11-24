#!/usr/bin/env python3
"""audio-phrase-map.py — 録音の区間を無音で区切り、 区切りごとに whisper で起こして、 時刻つきの言葉の並びにする。

なぜ: 切る所を決めるとき、 「どの言葉がどの秒に在るか」 を 0.1 秒の単位で知りたい。 whisper の時刻は話の止まった所まで
つながり (実測: 語ごとに起こしても時間の 99% を覆った)、 語と語の間の静かな所を指さない。 ここでは先に音量で区切り
(50 ms ごとの RMS、 --gap 秒以上の静けさで区切る)、 区切りごとに文脈を持ち越さない設定 (-mc 0) で起こす = 区切りの端が
そのまま切る所の候補になる。
規則と罠の正本 = conventions/podcast-audio-finishing.md#apply-cut-list (切る所の選び方) /
conventions/audio-transcription.md#short-clip-hallucination (短い区切りの作り話)。

出力: 1 行 1 区切り = `h:mm:ss.ss-h:mm:ss.ss (長さ) 起こした文`。 語にならない音 (笑い・叫び・物音) に whisper が作る決まり文句
(「ご視聴ありがとうございました」 など) は `〔語にならない音?〕` の印を付ける = 声でないことの手がかりで、 中身ではない。

使い方:
    python3 audio-phrase-map.py <録音> <始まりの秒> <終わりの秒> [--gap 0.3] [--thr -50] [--lang ja] [--model <ggml.bin>]
    python3 audio-phrase-map.py <録音> 600 640 --gap 0.12      # 細かく区切る (語の間の短い谷まで)
    python3 audio-phrase-map.py <録音> 600 640 --no-asr         # 区切りの時刻だけ (whisper を使わない)
    python3 audio-phrase-map.py --selftest

限界: 音量で区切る = 声が切れ目なく続く所 (速い言い合い) は 1 つの区切りになる (--gap を小さくする)。 区切りが 1 秒より短いと
whisper はよく作り話をする (上の印)。 区切りの中の語の順は whisper の読みで、 聞いて確かめるまでは推定。
話者は分けない (マイク 1 本の録音では分けられない)。
OS: macOS / Linux / Windows (ffmpeg と whisper.cpp の whisper-cli が PATH にあること、 標準 library だけ)。
"""
from __future__ import annotations

import argparse
import array
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOP_S = 0.05
SR = 16000
HALLUCINATIONS = ("ご視聴ありがとうございました", "お疲れ様でした", "ありがとうございました", "チャンネル登録",
                  "Thank you for watching", "Thanks for watching")
DEFAULT_MODEL = Path.home() / ".cache" / "whisper-cpp" / "ggml-large-v3-turbo.bin"


def read_pcm(src: Path, a: float, b: float) -> array.array:
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src),
                          "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return array.array("h", raw)


def levels(x: array.array, hop: int = int(SR * HOP_S)) -> list[float]:
    out = []
    for i in range(0, max(0, len(x) - hop + 1), hop):
        s = sum(v * v for v in x[i:i + hop]) / hop
        out.append(10 * math.log10(s / 32768 ** 2 + 1e-12))
    return out


def phrases(db: list[float], start: float, thr: float, gap: float, hop_s: float = HOP_S) -> list[tuple[float, float]]:
    """閾値より大きい窓の並びを区切りにし、 gap 秒未満の静けさは同じ区切りの中とみなす。"""
    segs: list[list[float]] = []
    cur = None
    quiet = 0.0
    for k, d in enumerate(db):
        t = start + k * hop_s
        if d > thr:
            if cur is None:
                cur = [t, t + hop_s]
            else:
                cur[1] = t + hop_s
            quiet = 0.0
        elif cur is not None:
            quiet += hop_s
            if quiet >= gap - 1e-9:
                segs.append(cur)
                cur, quiet = None, 0.0
    if cur is not None:
        segs.append(cur)
    return [(round(a, 3), round(b, 3)) for a, b in segs]


def transcribe(src: Path, a: float, b: float, model: Path, lang: str, work: Path) -> str:
    wav = work / "piece.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{max(0.0, a - 0.05):.3f}", "-to", f"{b + 0.05:.3f}",
                    "-i", str(src), "-ar", str(SR), "-ac", "1", "-af", "apad=pad_dur=0.6", "-c:a", "pcm_s16le", str(wav)], check=True)
    out = subprocess.run(["whisper-cli", "-m", str(model), "-l", lang, "-mc", "0", "-np", "-nt", str(wav)],
                         capture_output=True, text=True).stdout
    return " ".join(out.split())


def mark(text: str) -> str:
    if not text:
        return "〔起こせず〕"
    if any(h in text for h in HALLUCINATIONS):
        return f"〔語にならない音?〕 {text}"
    return text


def hms(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def selftest() -> int:
    db = [-80.0] * 100                       # 5 秒
    for k in list(range(10, 30)) + list(range(33, 40)) + list(range(60, 70)):
        db[k] = -20.0                        # 0.5〜1.5 秒、 1.65〜2.0 秒 (0.15 秒の谷)、 3.0〜3.5 秒
    p = phrases(db, 100.0, -50, 0.3)
    assert p == [(100.5, 102.0), (103.0, 103.5)], p          # 0.15 秒の谷は同じ区切り
    p2 = phrases(db, 100.0, -50, 0.12)
    assert p2 == [(100.5, 101.5), (101.65, 102.0), (103.0, 103.5)], p2   # 細かく区切れば谷で分かれる
    assert mark("ご視聴ありがとうございました").startswith("〔語にならない音?〕")
    assert mark("こんにちは") == "こんにちは" and mark("") == "〔起こせず〕"
    print("✅ selftest: 無音での区切り (谷の幅と --gap)・作り話の印")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?")
    ap.add_argument("start", nargs="?", type=float)
    ap.add_argument("end", nargs="?", type=float)
    ap.add_argument("--gap", type=float, default=0.3, help="これ以上の静けさで区切る (秒)")
    ap.add_argument("--thr", type=float, default=-50.0, help="これより大きい 50 ms の窓を音とみなす (dBFS)")
    ap.add_argument("--lang", default="ja")
    ap.add_argument("--model", default=os.environ.get("WHISPER_MODEL", str(DEFAULT_MODEL)))
    ap.add_argument("--no-asr", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.src is None or a.start is None or a.end is None or not a.end > a.start:
        ap.error("録音・始まりの秒・終わりの秒 (始まり < 終わり) が要る")
    src = Path(a.src)
    segs = phrases(levels(read_pcm(src, a.start, a.end)), a.start, a.thr, a.gap)
    use_asr = not a.no_asr
    if use_asr and (shutil.which("whisper-cli") is None or not Path(a.model).exists()):
        print("⚠️ whisper-cli か model が無いので、 区切りの時刻だけを出す (--no-asr と同じ)", file=sys.stderr)
        use_asr = False
    with tempfile.TemporaryDirectory() as d:
        for s, e in segs:
            text = mark(transcribe(src, s, e, Path(a.model), a.lang, Path(d))) if use_asr else ""
            print(f"{hms(s)}-{hms(e)} ({e - s:.1f}s) {text}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
