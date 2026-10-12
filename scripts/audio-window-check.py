#!/usr/bin/env python3
"""音声の短い区間を確かめる: 切れ目の両側の再転写・ある時刻の前後の音量の並び・大きな山の一覧。

長い録音を分けて仕上げるとき、 機械で確かめる所はいつも同じ 3 つ (判断の理由と壊れ方の正本 =
conventions/audio-transcription.md#splitting-long-recordings / conventions/podcast-audio-finishing.md#listen-checklist):
    edges     分けた part の頭と尾を whisper で起こし直す (= 切れ目の両側の確認。 前の part の尾と次の part の頭を並べて出す)
    window    ある時刻の前後を whisper で起こす (= 切れ目の候補・聞き取れない語・削る断片の確認。 時刻は元の音声の秒で出す)
    envelope  ある時刻の前後の音量 (RMS dBFS) を細かい刻みで並べる (= 声と声の間の静けさの幅を見て、 切る位置を決める)
    peaks     山 (Peak dBFS) が閾値を超える区間を大きい順に並べる (= リミッターが強く効く所 = 歪みを聞く所を探す)

使い方:
    python3 audio-window-check.py edges parts/x-part1.m4a parts/x-part2.m4a parts/x-part3.m4a [--head 10 --tail 8]
    python3 audio-window-check.py window SRC.m4a --at 1850.4 [--before 6 --after 10]
    python3 audio-window-check.py envelope SRC.m4a --at 1850.4 [--span 2 --step 0.05]
    python3 audio-window-check.py peaks SRC.m4a [--above -1 --window 0.5 --top 15]
    python3 audio-window-check.py --selftest     # 合成音で envelope と peaks を確かめる (whisper は使わない)

whisper: whisper-cli (whisper.cpp) と model (既定 ~/.cache/whisper-cpp/ggml-large-v3-turbo.bin、 --model か env WHISPER_MODEL)、
    言語 = --lang (既定 ja)。 起こした語は「生成」 = 語の確認でなく、 切れ目が発話の途中でないか・何の話かの確認に使う。
⚠️ 音量の刻みは ffmpeg の asetnsamples (標本の数) で切る = 48 kHz なら 0.05 秒 = 2400 標本。 mono に混ぜてから測る。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", str(Path.home() / ".cache/whisper-cpp/ggml-large-v3-turbo.bin"))


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def sample_rate(path: Path) -> int:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return int(r.stdout.strip())


def series(path: Path, start: float, length: float, step: float, key: str) -> list[tuple[float, float]]:
    """start から length 秒を step 秒ごとに区切り、 各区間の astats の key (RMS_level / Peak_level) を (時刻, dBFS) で返す。"""
    n = max(1, round(step * sample_rate(path)))
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path), "-af",
           f"aformat=channel_layouts=mono,asetnsamples={n},astats=metadata=1:reset=1,"
           f"ametadata=print:key=lavfi.astats.Overall.{key}", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    out, t = [], None
    for line in err.splitlines():
        m = re.search(r"pts_time:([-\d.]+)", line)
        if m:
            t = float(m.group(1)) + start
        m = re.search(rf"{key}=(-?[\d.]+|-inf|inf)", line)
        if m and t is not None:
            v = float(m.group(1)) if "inf" not in m.group(1) else (-200.0 if m.group(1).startswith("-") else 0.0)
            out.append((round(t, 3), v))
    return out


def whisper(path: Path, start: float, length: float, lang: str, model: str) -> list[tuple[float, str]]:
    """start から length 秒を 16 kHz mono に切り出して whisper-cli で起こす。 (元の音声の秒, 文) を返す。"""
    if not shutil.which("whisper-cli"):
        raise SystemExit("❌ whisper-cli が無い (whisper.cpp)")
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "w.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, start):.3f}", "-t", f"{length:.3f}",
                        "-i", str(path), "-ar", "16000", "-ac", "1", str(wav)], check=True)
        r = subprocess.run(["whisper-cli", "-m", model, "-l", lang, "-np", str(wav)], capture_output=True, text=True)
    rows = []
    for line in r.stdout.splitlines():
        m = re.match(r"\[(\d+):(\d+):([\d.]+) --> [^\]]+\]\s*(.*)", line)
        if m:
            rows.append((max(0.0, start) + int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)),
                         m.group(4).strip()))
    return rows


def hms(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"


def cmd_edges(a) -> int:
    parts = [Path(p) for p in a.parts]
    for k, p in enumerate(parts):
        d = duration(p)
        if k:
            print(f"== {p.name} の頭 ({a.head} 秒)")
            for t, s in whisper(p, 0, a.head, a.lang, a.model):
                print(f"  [{hms(t)}] {s}")
        if k < len(parts) - 1:
            print(f"== {p.name} の尾 ({a.tail} 秒、 長さ {hms(d)})")
            for t, s in whisper(p, d - a.tail, a.tail, a.lang, a.model):
                print(f"  [{hms(t)}] {s}")
    return 0


def cmd_window(a) -> int:
    for t, s in whisper(Path(a.src), a.at - a.before, a.before + a.after, a.lang, a.model):
        print(f"[{hms(t)}] {s}")
    return 0


def cmd_envelope(a) -> int:
    rows = series(Path(a.src), a.at - a.span, 2 * a.span, a.step, "RMS_level")
    for i in range(0, len(rows), 8):
        print("  ".join(f"{t:.2f}:{v:6.1f}" for t, v in rows[i:i + 8]))
    return 0


def cmd_peaks(a) -> int:
    src = Path(a.src)
    rows = [r for r in series(src, 0, duration(src), a.window, "Peak_level") if r[1] > a.above]
    rows.sort(key=lambda r: -r[1])
    print(f"{src.name}: 山が {a.above} dBFS を超える {a.window} 秒の区間 = {len(rows)} 個 (大きい順に {a.top} 個)")
    for t, v in rows[:a.top]:
        print(f"  {hms(t)}  ({t:.1f} 秒)  {v:+.1f} dBFS")
    return 0


def selftest() -> int:
    missing = [x for x in ("ffmpeg", "ffprobe") if not shutil.which(x)]
    if missing:  # run-all-checks の契約: 依存が無い環境では理由を出して SKIP (exit 0)
        print(f"SKIP: {' / '.join(missing)} が無い (audio-window-check selftest)")
        return 0
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "t.wav"
        # 0〜1 秒 = 小さい音 (-30 dB)、 1〜1.5 秒 = 無音、 1.5〜2 秒 = 大きい音 (-1 dB 付近)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "aevalsrc=if(lt(t\\,1)\\,0.0316*sin(2*PI*440*t)\\,if(lt(t\\,1.5)\\,0\\,0.89*sin(2*PI*440*t))):s=48000:d=2",
                        str(src)], check=True)
        env = series(src, 0, 2, 0.05, "RMS_level")
        quiet = [v for t, v in env if 1.05 <= t < 1.45]
        loud = [v for t, v in env if 1.55 <= t < 1.95]
        soft = [v for t, v in env if 0.05 <= t < 0.95]
        assert len(env) == 40, len(env)
        assert all(v < -100 for v in quiet), quiet
        assert all(-34 < v < -30 for v in soft), soft[:3]
        assert all(-5 < v < -2 for v in loud), loud[:3]
        pk = [r for r in series(src, 0, 2, 0.5, "Peak_level") if r[1] > -3]
        assert [round(t, 1) for t, _ in pk] == [1.5], pk
    print("audio-window-check selftest: ALL PASS (無音の区間・小さい音・大きい音の RMS、 山の区間の検出)")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("edges", "window"):
        p = sub.add_parser(name)
        p.add_argument("--lang", default="ja")
        p.add_argument("--model", default=DEFAULT_MODEL)
    sub.choices["edges"].add_argument("parts", nargs="+", help="分けた part を順に")
    sub.choices["edges"].add_argument("--head", type=float, default=10.0)
    sub.choices["edges"].add_argument("--tail", type=float, default=8.0)
    w = sub.choices["window"]
    w.add_argument("src")
    w.add_argument("--at", type=float, required=True, help="元の音声の秒")
    w.add_argument("--before", type=float, default=6.0)
    w.add_argument("--after", type=float, default=10.0)
    e = sub.add_parser("envelope")
    e.add_argument("src")
    e.add_argument("--at", type=float, required=True)
    e.add_argument("--span", type=float, default=2.0, help="前後それぞれの秒")
    e.add_argument("--step", type=float, default=0.05)
    p = sub.add_parser("peaks")
    p.add_argument("src")
    p.add_argument("--above", type=float, default=-1.0, help="この dBFS を超える区間だけ")
    p.add_argument("--window", type=float, default=0.5)
    p.add_argument("--top", type=int, default=15)
    a = ap.parse_args(argv)
    return {"edges": cmd_edges, "window": cmd_window, "envelope": cmd_envelope, "peaks": cmd_peaks}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
