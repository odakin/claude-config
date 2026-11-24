#!/usr/bin/env python3
"""audio-apply-cuts.py — 録音から、 時刻の表で決めた区間を抜き、 残りを 0.1 秒の crossfade でつないで FLAC に書く。

なぜ: 配信の前に「ここからここまで切る」 を何か所も決めた (人が聞いて決めた時刻の表) 録音を、 決めた表どおりに作り直したい。
同じ録音から版を 2 つ (全部切った版 / 一部だけ切った版) 作るときも、 表を 2 つ持てば取り違えない。 手で filter を組むと
継ぎ目の数と crossfade の分だけ長さがずれ、 出来上がりの時刻で決めた次の切る所を元の時刻に直すのも手で間違える (実測)。
規則の正本 = conventions/podcast-audio-finishing.md#apply-cut-list (表の持ち方・版の分け方・確かめ方)。

やること:
    1. 切る区間 (入力の秒、 h:mm:ss.ss でも秒でも) を並べ替え、 重なりを止め、 残す区間を作る
    2. 残す区間を ffmpeg の atrim + acrossfade (既定 0.1 秒) でつなぎ、 FLAC に書く (再符号化は FLAC への 1 回だけ)
    3. 書いた file の長さが「残す区間の和 − crossfade × (継ぎ目の数)」 と 0.02 秒以内で合うかを確かめる
    4. --json に残す区間と時刻の写像を書く。 --to-in / --to-out で出来上がりの秒 ⇄ 元の秒を直す
       (出来上がりを聞いて決めた次の切る所を元の時刻の表に足すとき = 元の時刻で表を持てば、 作り直しても表は変わらない)

使い方:
    python3 audio-apply-cuts.py <in> --cuts '0:00:00-0:00:15, 0:21:10.5-0:23:40' --out <out.flac> [--json <map.json>]
    python3 audio-apply-cuts.py <in> --cuts-file <cuts.txt> --out <out.flac>     # 1 行 1 区間 (a-b)、 # から行末は注記
    python3 audio-apply-cuts.py <in> --cuts '…' --dry-run                        # 残す区間と出来上がりの長さだけ
    python3 audio-apply-cuts.py <in> --cuts '…' --to-in 1200.5 1500           # 出来上がりの秒 → 元の秒
    python3 audio-apply-cuts.py <in> --cuts '…' --to-out 1800                  # 元の秒 → 出来上がりの秒
    python3 audio-apply-cuts.py --selftest

限界: 抜いた所の前後の声は crossfade で 0.1 秒重なる = 切る所は音の谷 (語と語の間の静かな所) に置く
(谷の見つけ方 = 同じ dir の audio-phrase-map.py と audio-window-check.py envelope)。 入力の長さは ffprobe で読む。
OS: macOS / Linux / Windows (ffmpeg・ffprobe が PATH にあること、 標準 library だけ)。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

XFADE = 0.1


def parse_time(s: str) -> float:
    s = s.strip()
    if ":" not in s:
        return float(s)
    parts = [float(p) for p in s.split(":")]
    v = 0.0
    for p in parts:
        v = v * 60 + p
    return v


def parse_cuts(text: str) -> list[tuple[float, float]]:
    """'a-b, c-d' か 1 行 1 区間。 # から行末は注記。 a < b でない・重なる区間は止める。"""
    items = []
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        for piece in line.split(","):
            piece = piece.strip()
            if not piece:
                continue
            m = re.fullmatch(r"([0-9:.]+)\s*-\s*([0-9:.]+)", piece)
            if not m:
                raise ValueError(f"区間の形が読めない: {piece!r} (a-b の形、 h:mm:ss.ss か秒)")
            a, b = parse_time(m.group(1)), parse_time(m.group(2))
            if not a < b:
                raise ValueError(f"区間の始まりが終わりより前でない: {piece!r}")
            items.append((a, b))
    items.sort()
    for (a1, b1), (a2, b2) in zip(items, items[1:]):
        if a2 < b1:
            raise ValueError(f"区間が重なる: {hms(a1)}-{hms(b1)} と {hms(a2)}-{hms(b2)}")
    return items


def keeps_from_cuts(cuts: list[tuple[float, float]], dur: float) -> list[tuple[float, float]]:
    keeps, t = [], 0.0
    for a, b in cuts:
        a, b = max(0.0, a), min(dur, b)
        if a > t:
            keeps.append((t, a))
        t = max(t, b)
    if dur > t:
        keeps.append((t, dur))
    return keeps


def out_length(keeps: list[tuple[float, float]], xfade: float = XFADE) -> float:
    return sum(b - a for a, b in keeps) - xfade * max(0, len(keeps) - 1)


def to_out(t: float, keeps: list[tuple[float, float]], xfade: float = XFADE) -> float:
    """元の秒 → 出来上がりの秒。 抜いた区間の中の t は、 その継ぎ目に寄せる。"""
    acc = 0.0
    for i, (a, b) in enumerate(keeps):
        if i > 0:
            acc -= xfade
        if t < a:
            return round(acc, 3)
        if t <= b:
            return round(acc + (t - a), 3)
        acc += b - a
    return round(acc, 3)


def to_in(x: float, keeps: list[tuple[float, float]], xfade: float = XFADE) -> float:
    """出来上がりの秒 → 元の秒 (継ぎ目の crossfade の中は後ろの区間の側として読む)。"""
    acc = 0.0
    for i, (a, b) in enumerate(keeps):
        if i > 0:
            acc -= xfade
        if x <= acc + (b - a) or i == len(keeps) - 1:
            return round(a + max(0.0, x - acc), 3)
        acc += b - a
    return round(keeps[-1][1], 3) if keeps else x


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def render(src: Path, keeps: list[tuple[float, float]], out: Path, xfade: float = XFADE) -> None:
    parts = [f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[s{k}]" for k, (a, b) in enumerate(keeps)]
    chain, prev = [], "s0"
    for k in range(1, len(keeps)):
        nxt = f"x{k}"
        chain.append(f"[{prev}][s{k}]acrossfade=d={xfade}:c1=tri:c2=tri[{nxt}]")
        prev = nxt
    graph = ";".join(parts + chain)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(graph)
        script = f.name
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                        "-filter_complex_script", script, "-map", f"[{prev}]", "-c:a", "flac", str(out)], check=True)
    finally:
        Path(script).unlink(missing_ok=True)


def hms(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def selftest() -> int:
    cuts = parse_cuts("0:00:10-0:00:20, 30-35  # 注記\n0:00:50-0:00:60")
    assert cuts == [(10.0, 20.0), (30.0, 35.0), (50.0, 60.0)], cuts
    keeps = keeps_from_cuts(cuts, 100.0)
    assert keeps == [(0.0, 10.0), (20.0, 30.0), (35.0, 50.0), (60.0, 100.0)], keeps
    assert abs(out_length(keeps) - (10 + 10 + 15 + 40 - 0.3)) < 1e-9
    assert to_out(5.0, keeps) == 5.0 and to_out(15.0, keeps) == 9.9   # 抜いた区間の中は継ぎ目へ
    assert to_out(25.0, keeps) == 14.9 and to_out(61.0, keeps) == 35.7
    for t in (5.0, 25.0, 40.0, 61.0, 99.0):                            # 残す区間の中は往復で戻る
        assert abs(to_in(to_out(t, keeps), keeps) - t) < 1e-3, t
    assert keeps_from_cuts([(0.0, 5.0)], 10.0) == [(5.0, 10.0)]        # 頭を切る
    for bad in ("5-3", "1-4, 3-6", "abc"):
        try:
            parse_cuts(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    msg = "✅ selftest: 区間の読み・残す区間・長さ・時刻の写像 (往復)"
    try:                                                               # ffmpeg があれば実際に作って長さを確かめる
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "tone.flac", Path(d) / "cut.flac"
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=6",
                            "-c:a", "flac", str(src)], check=True)
            k = keeps_from_cuts(parse_cuts("1-2, 3.5-4"), probe_duration(src))
            render(src, k, out)
            assert abs(probe_duration(out) - out_length(k)) < 0.02, (probe_duration(out), out_length(k))
        msg += " + ffmpeg で作った長さ"
    except FileNotFoundError:
        msg += " (ffmpeg が無いので作る試験は飛ばした)"
    print(msg)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?")
    ap.add_argument("--cuts")
    ap.add_argument("--cuts-file")
    ap.add_argument("--out")
    ap.add_argument("--json")
    ap.add_argument("--xfade", type=float, default=XFADE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--to-in", nargs="+", type=float, metavar="出来上がりの秒")
    ap.add_argument("--to-out", nargs="+", type=float, metavar="元の秒")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.src or not (a.cuts or a.cuts_file):
        ap.error("入力と --cuts (か --cuts-file) が要る")
    text = a.cuts if a.cuts else Path(a.cuts_file).read_text(encoding="utf-8")
    try:
        cuts = parse_cuts(text)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    src = Path(a.src)
    dur = probe_duration(src)
    keeps = keeps_from_cuts(cuts, dur)
    want = out_length(keeps, a.xfade)
    if a.to_in or a.to_out:
        for x in a.to_in or []:
            print(f"出来上がり {hms(x)} → 元 {hms(to_in(x, keeps, a.xfade))}")
        for t in a.to_out or []:
            print(f"元 {hms(t)} → 出来上がり {hms(to_out(t, keeps, a.xfade))}")
        return 0
    cut_total = sum(min(dur, b) - max(0.0, a_) for a_, b in cuts)
    print(f"{src.name}: {hms(dur)} / 切る {len(cuts)} か所 計 {cut_total:.2f} 秒 → 残す {len(keeps)} 区間、 出来上がり {hms(want)}")
    if a.json:
        Path(a.json).write_text(json.dumps({"src": str(src), "in_duration_s": round(dur, 3), "xfade_s": a.xfade,
                                            "cuts_in": [[round(x, 3), round(y, 3)] for x, y in cuts],
                                            "keeps_in": [[round(x, 3), round(y, 3)] for x, y in keeps],
                                            "out_duration_s": round(want, 3)}, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.dry_run:
        return 0
    if not a.out:
        ap.error("--out が要る (--dry-run でなければ)")
    out = Path(a.out)
    render(src, keeps, out, a.xfade)
    got = probe_duration(out)
    ok = abs(got - want) < 0.02
    print(f"{'✅' if ok else '❌'} {out}: {hms(got)} (期待 {hms(want)}、 差 {got - want:+.3f} 秒)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
