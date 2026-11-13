#!/usr/bin/env python3
"""audio-shorten-gaps.py — 録音の中の長い「話の間」 (だれも話していない間) を、 決めた秒数に縮める。

なぜ: 収録の中で作業や探し物で黙った長い間 (数十秒) を縮めたいとき、 素の無音検出 (ffmpeg silencedetect) は
キーボードや物音の一瞬で間が途切れるので、 会話の間をほとんど拾えない (実測)。 ここでは 0.1 秒ごとの音量 (RMS) を見て、
閾値より小さい窓の並びを間とし、 間の中の短い物音 (--blip 秒まで) は間の一部として扱う。
規則と罠の正本 = conventions/podcast-audio-finishing.md#shorten-long-gaps (閾値の決め方・物音の長さ・縮め始める長さ)。

やること:
    1. 0.1 秒ごとの RMS (同じ dir の audio-window-check.py の series = ffmpeg astats) を測る
    2. RMS < --thr の窓の並びを間とする。 間と間に挟まれた --blip 秒以下の大きい窓は間に含める
    3. --trigger 秒 (既定 = --max-gap) を超える間を --max-gap 秒に縮める = 頭の max-gap/2 秒と尾の max-gap/2 秒を残して真ん中を抜く
       (間の入りと抜けの空気を残す。 声の頭と尾から離れた所で切るので、 語を切らない)
    4. 残した区間を 0.1 秒の crossfade でつないで FLAC に書く
    5. --json に抜いた区間と、 入力の時刻 → 出力の時刻の写像を書く (仕上げの --bgm-mute などの時刻を --map で写す)

既定の値: --thr -60 dBFS・--blip 0.2 秒 = 会議の録音 (床の音 約 -70 dBFS) で、 抜く区間に話者つきの文字起こしの発話の頭が
1 件も入らなかった組 (実測。 -45 dBFS・0.5 秒では、 遠い話者のつぶやきと短い相づちが間に入った)。 録音ごとに床と声の大きさは違う =
--dry-run --json の抜く区間を、 話者つきの文字起こし (Zoom の VTT など) の発話の頭と照らしてから当てる。

限界: 音量だけで見る = 閾値より小さい声は間に数える (照らすのは上の手順)。 抜いた所で音楽が鳴っていれば途切れる
(収録の中で鳴った音楽は閾値より大きいので、 ふつうは間にならない)。

使い方:
    python3 audio-shorten-gaps.py <in> --dry-run [--json <plan.json>]              # 縮める間の一覧だけ
    python3 audio-shorten-gaps.py <in> --out <out.flac> --json <map.json> [--max-gap 8 --trigger 8 --thr -60 --blip 0.2]
    python3 audio-shorten-gaps.py --map <map.json> 1745.3 1762.3                   # 入力の秒 → 出力の秒
    python3 audio-shorten-gaps.py --selftest
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

AWC = Path(__file__).resolve().parent / "audio-window-check.py"
STEP = 0.1
XFADE = 0.1


def _awc():
    spec = importlib.util.spec_from_file_location("audio_window_check", AWC)
    if spec is None or spec.loader is None:
        sys.exit(f"❌ {AWC} が読めない")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def find_gaps(levels: list[tuple[float, float]], thr: float, blip: float, step: float = STEP) -> list[tuple[float, float]]:
    """(時刻, dBFS) の並びから間 (start, end) を返す。 間に挟まれた blip 秒以下の大きい窓は間に含める。"""
    quiet = [v < thr for _, v in levels]
    n = len(quiet)
    maxb = int(round(blip / step))
    i = 0
    while i < n:  # 短い大きい並びを埋める (両側が quiet のときだけ)
        if not quiet[i]:
            j = i
            while j < n and not quiet[j]:
                j += 1
            if i > 0 and j < n and (j - i) <= maxb:
                for k in range(i, j):
                    quiet[k] = True
            i = j
        else:
            i += 1
    gaps, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            gaps.append((levels[i][0], levels[j - 1][0] + step))
            i = j
        else:
            i += 1
    return gaps


def plan(gaps: list[tuple[float, float]], max_gap: float, trigger: float | None = None) -> list[tuple[float, float]]:
    """抜く区間 (入力の秒) = trigger (既定 = max_gap) を超える間を max_gap に縮める = 頭と尾 max_gap/2 を残した真ん中。
    trigger > max_gap にすると、 少しだけ長い間 (会話の自然な間) には触らず、 長く黙った所だけが縮む。"""
    h = max_gap / 2
    t = max_gap if trigger is None else max(trigger, max_gap)
    return [(round(a + h, 3), round(b - h, 3)) for a, b in gaps if b - a > t]


def kept_segments(removed: list[tuple[float, float]], dur: float) -> list[tuple[float, float]]:
    segs, t = [], 0.0
    for a, b in removed:
        segs.append((t, a))
        t = b
    segs.append((t, dur))
    return segs


def to_output_time(t: float, removed: list[tuple[float, float]], xfade: float = XFADE) -> float:
    """入力の秒 t → 出力の秒。 抜いた区間の中の t は、 その区間の頭 (= 継ぎ目) に寄せる。"""
    out = t
    for a, b in removed:
        if t >= b:
            out -= (b - a) + xfade
        elif t > a:
            out -= (t - a)
            break
        else:
            break
    return round(out, 3)


def render(src: Path, segs: list[tuple[float, float]], out: Path) -> None:
    if len(segs) == 1:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-c:a", "flac", str(out)], check=True)
        return
    parts = [f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[s{k}]" for k, (a, b) in enumerate(segs)]
    chain, prev = [], "s0"
    for k in range(1, len(segs)):
        nxt = f"x{k}" if k < len(segs) - 1 else "o"
        chain.append(f"[{prev}][s{k}]acrossfade=d={XFADE}[{nxt}]")
        prev = nxt
    graph = ";".join(parts + chain)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(graph)
        script = f.name
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-filter_complex_script", script,
                    "-map", "[o]", "-c:a", "flac", str(out)], check=True)
    Path(script).unlink(missing_ok=True)


def hms(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def selftest() -> None:
    lv = [(k * STEP, -70.0) for k in range(200)]          # 20 秒の静けさ
    for k in list(range(0, 20)) + list(range(150, 160)):  # 声: 0〜2 秒、 15〜16 秒
        lv[k] = (lv[k][0], -20.0)
    for k in (80, 81):                                     # 8.0〜8.2 秒の物音 (blip)
        lv[k] = (lv[k][0], -30.0)
    g = find_gaps(lv, -45, 0.5)
    assert len(g) == 2 and abs(g[0][0] - 2.0) < 1e-6 and abs(g[0][1] - 15.0) < 1e-6, g  # 物音は間に含む
    r = plan(g, 5.0)
    assert r == [(4.5, 12.5)], r                           # 13 秒の間 → 頭 2.5・尾 2.5 を残す (16〜20 秒の 4 秒は縮めない)
    assert to_output_time(1.0, r) == 1.0 and to_output_time(15.0, r) == round(15.0 - 8.0 - XFADE, 3)
    assert to_output_time(8.0, r) == 4.5                   # 抜いた区間の中は継ぎ目へ
    assert kept_segments(r, 20.0) == [(0.0, 4.5), (12.5, 20.0)]
    assert plan(g, 5.0, trigger=14.0) == [] and plan(g, 5.0, trigger=12.0) == [(4.5, 12.5)]  # 縮め始める長さ
    g2 = find_gaps(lv, -45, 0.1)                           # blip を許さないと物音で間が割れる
    assert len(g2) == 3, g2
    print("✅ selftest: 物音を挟んだ間の検出・縮める区間・時刻の写像")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", nargs="?", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--max-gap", type=float, default=5.0, help="縮めた後の間の長さ")
    ap.add_argument("--trigger", type=float, default=None,
                    help="この秒数を超える間だけを縮める (既定 = --max-gap)。 --max-gap より長くすると、 少しだけ長い会話の間に触らない。"
                         " ⚠️ --max-gap より長くすると、 trigger を少し超えた間が max-gap まで縮み、 trigger 以下の間はそのまま残る"
                         " = 長い間ほど短くなる逆転が起きる。 順を保つなら同じ値に (podcast-audio-finishing.md#shorten-long-gaps)")
    ap.add_argument("--thr", type=float, default=-60.0, help="これより小さい RMS (dBFS) を間とみなす")
    ap.add_argument("--blip", type=float, default=0.2, help="間に挟まれたこの秒数以下の物音は間に含める")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--map", type=Path, help="--json で書いた写像を読み、 残りの引数 (入力の秒) を出力の秒に直す")
    ap.add_argument("times", nargs="*", type=float)
    ap.add_argument("--selftest", action="store_true")
    a, rest = ap.parse_known_args()
    if a.selftest:
        selftest()
        return 0
    if a.map:
        m = json.loads(a.map.read_text(encoding="utf-8"))
        removed = [tuple(x) for x in m["removed_in"]]
        ts = [float(x) for x in ([str(a.src)] if a.src else []) + [str(t) for t in a.times] + rest]
        for t in ts:
            print(f"{t:.3f} → {to_output_time(t, removed):.3f}")
        return 0
    if not a.src:
        ap.error("入力の音声が要る")
    awc = _awc()
    dur = awc.duration(a.src)
    levels = awc.series(a.src, 0.0, dur, STEP, "RMS_level")
    gaps = find_gaps(levels, a.thr, a.blip)
    trig = a.max_gap if a.trigger is None else max(a.trigger, a.max_gap)
    removed = plan(gaps, a.max_gap, trig)
    long_gaps = [g for g in gaps if g[1] - g[0] > trig]
    total = sum(b - x for x, b in removed)
    print(f"{a.src.name}: 長さ {hms(dur)} / {trig:g} 秒を超える間 {len(long_gaps)} 個 → {a.max_gap:g} 秒に縮めて抜く {total:.1f} 秒"
          f" (閾値 {a.thr:g} dBFS、 物音 {a.blip:g} 秒まで許す)")
    for (ga, gb), (ra, rb) in zip(long_gaps, removed):
        print(f"  間 {hms(ga)}〜{hms(gb)} ({gb - ga:5.1f} 秒) → {hms(ra)}〜{hms(rb)} を抜く")
    record = {"src": a.src.name, "out": a.out.name if a.out else None, "max_gap_s": a.max_gap, "trigger_s": trig, "thr_dbfs": a.thr,
              "blip_s": a.blip, "xfade_s": XFADE, "in_duration_s": round(dur, 3), "removed_s": round(total, 3),
              "gaps_in": [[round(x, 3), round(y, 3)] for x, y in long_gaps], "removed_in": [[x, y] for x, y in removed]}
    if a.dry_run:
        if a.json:  # 一覧だけでも、 抜く区間を他の記録 (話者つき文字起こし) と照らせるように書く
            a.json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0
    if not a.out:
        ap.error("--out が要る (一覧だけなら --dry-run)")
    render(a.src, kept_segments(removed, dur), a.out)
    out_dur = awc.duration(a.out)
    want = dur - total - XFADE * len(removed)
    ok = abs(out_dur - want) < 0.05
    print(f"{'✅' if ok else '❌'} {a.out.name}: {hms(out_dur)} (入力 − 抜いた分 − 継ぎ目 = {hms(want)})")
    if a.json:
        record["out_duration_s"] = round(out_dur, 3)
        a.json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
