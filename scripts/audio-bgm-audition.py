#!/usr/bin/env python3
"""本編の下に敷く BGM の音量を声の下で聞き比べて決める道具 (聞き比べの切り出し・間の多い箇所探し・曲の波の大きさ・仕上がりの静かな所)。

BGM の integrated loudness を揃えて揃うのは平均だけ。 曲の波 (盛り上がり) の大きさや旋律の音色で、 同じ値でも静かな話の声に
近づく曲がある (実測: 同じ値で、 ある曲は静かな話の声の約 13 dB 下まで来ていた)。 だから音量は曲ごとに、 実際の本編の
間の多い箇所に敷いて聞き比べて決める (考え方の正本 = conventions/podcast-audio-finishing.md#bgm-level-per-track)。

    quiet    Part (生の本編) の中で間 (声が止まっている所) が多い区間を探す = 聞き比べに使う箇所 (BGM が一番聞こえる所)
    clips    Part の一部に BGM を何段かの音量で敷いた聞き比べ用の切り出しを作る。 声の利得・頭の削り・リミッターの上限は
             仕上げの記録 (.json) から取り、 リミッターは仕上げの engine と同じ形 (192 kHz で掛ける) なので、 記録の音量の段は
             仕上がった配信音声のその箇所と同じ聞こえ方になる (--reference で照合する)
    profile  BGM を目標の loudness に揃えたときの 3 秒窓の大きさの分布 (中央値 / 90 % / 最大)・LRA・帯域の割合 = 曲同士の比較
    gaps     仕上がった音声の 0.4 秒窓の大きさの下側の分位 (2 / 5 / 10 / 25 / 50 %) = 話の間に BGM がどれだけ聞こえるか

使い方:
    python3 audio-bgm-audition.py quiet parts/x-part1.m4a [--window 60 --top 5]
    python3 audio-bgm-audition.py clips parts/x-part1.m4a loop.flac --finish-json finished/x-part1.json --at 650 \\
        [--dur 60 --levels -40,-44,-48 --out-dir unclear-clips --prefix 聞き比べ --reference finished/x-part1.mp3 --force]
    python3 audio-bgm-audition.py profile a-loop.flac b-loop.flac [--target -40]
    python3 audio-bgm-audition.py gaps finished/x-part1.mp3 finished/y-part1.mp3 [--skip 20]
    python3 audio-bgm-audition.py --selftest      # 合成音で 4 つを確かめる (数十秒)

--finish-json = audio-finish-episode.py の記録 (renders[-1] の gain_speech_dB / ceiling_dBFS、 trim_head_s、 intro_jingle_s、 bgm_lufs)。
--speech-gain / --ceiling / --trim-head で個別に上書きできる (記録が無いときは 3 つとも渡す)。
BGM は本編の頭 (= 冒頭ジングルの終わり) で頭から鳴る = Part の時刻 t の所の BGM の位置は t - trim_head_s (ループの長さで折り返す)。
--reference = 仕上がった配信音声。 同じ箇所 (t - trim_head_s + intro_jingle_s) を切り出し、 記録の bgm_lufs の段の切り出しと gaps を
並べて出す (下側の分位が 0.5 dB 以内なら再現できている)。 出力は上書きしない (--force)。
⚠️ 切り出しは配信音声を作り直さない = 聞き比べ専用。 値が決まったら仕上げ script で生の本編から作り直す。
依存 = ffmpeg / ffprobe (ebur128・libmp3lame)。 標準 library だけ。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SAMPLE_RATE = 48000
BANDS = [("0-250", "lowpass=f=250,lowpass=f=250"),
         ("250-1000", "highpass=f=250,highpass=f=250,lowpass=f=1000,lowpass=f=1000"),
         ("1000-4000", "highpass=f=1000,highpass=f=1000,lowpass=f=4000,lowpass=f=4000"),
         ("4000-", "highpass=f=4000,highpass=f=4000")]
FRAME = re.compile(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+|-?inf|nan)\s+S:\s*(-?[\d.]+|-?inf|nan)")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def duration(path: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(r.stdout.strip())


def ebur128(path: Path, gain_db: float = 0.0, start: float | None = None, dur: float | None = None) -> dict:
    """integrated / LRA と 0.1 秒ごとの momentary (0.4 秒窓)・short-term (3 秒窓)。 gain_db を掛けてから測る。"""
    cmd = ["ffmpeg", "-nostats", "-hide_banner"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(path), "-af", f"volume={gain_db:.3f}dB,ebur128", "-f", "null", "-"]
    text = run(cmd).stderr
    frames = []
    for m in FRAME.finditer(text):
        t, mo, st = (float(m.group(i)) if m.group(i) not in ("nan",) else -math.inf for i in (1, 2, 3))
        frames.append((t, mo, st))
    summary = text.rsplit("Summary", 1)[-1]
    m_i = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", summary)
    m_lra = re.search(r"LRA:\s*(-?[\d.]+)\s*LU", summary)
    if not m_i or not frames:
        raise SystemExit(f"ebur128 の結果が読めない: {path}\n{text[-600:]}")
    return {"I": float(m_i.group(1)), "LRA": float(m_lra.group(1)) if m_lra else None, "frames": frames}


def pct(values: list[float], q: float) -> float:
    v = sorted(values)
    if not v:
        return -math.inf
    k = (len(v) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def gap_quantiles(path: Path, skip: float, start: float | None = None, dur: float | None = None) -> tuple[float, list[float]]:
    r = ebur128(path, start=start, dur=dur)
    end = r["frames"][-1][0]
    mom = [mo for t, mo, _ in r["frames"] if skip <= t <= end - skip]
    return r["I"], [pct(mom, q) for q in (2, 5, 10, 25, 50)]


def fmt_q(qs: list[float]) -> str:
    return "/".join(f"{q:.1f}" for q in qs)


def cmd_gaps(a) -> int:
    for p in a.files:
        i, qs = gap_quantiles(Path(p), a.skip)
        print(f"{Path(p).name}: I={i:.1f} LUFS  0.4 秒窓の下側の分位 2/5/10/25/50 % = {fmt_q(qs)}")
    return 0


def band_shares(path: Path) -> dict[str, float]:
    def mean_db(af: str | None) -> float:
        cmd = ["ffmpeg", "-nostats", "-hide_banner", "-i", str(path)] + (["-af", f"{af},volumedetect"] if af else ["-af", "volumedetect"])
        m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", run(cmd + ["-f", "null", "-"]).stderr)
        return float(m.group(1)) if m else -math.inf
    total = mean_db(None)
    return {name: mean_db(af) - total for name, af in BANDS}


def cmd_profile(a) -> int:
    for p in a.files:
        path = Path(p)
        base = ebur128(path)
        off = a.target - base["I"]
        st = [s + off for t, _, s in base["frames"] if t >= 3.0]
        mo = [m + off for _, m, _ in base["frames"]]
        print(f"{path.name}: 単体 I={base['I']:.1f} LUFS → {a.target:g} に揃える利得 {off:+.1f} dB  LRA={base['LRA']} LU")
        print(f"  3 秒窓 中央値/90 %/最大 = {pct(st, 50):.1f}/{pct(st, 90):.1f}/{max(st):.1f}   0.4 秒窓 90 %/最大 = {pct(mo, 90):.1f}/{max(mo):.1f}")
        if not a.no_bands:
            print("  帯域の割合 (dB、 おおよそ = 4 次の filter): " + "  ".join(f"{k} Hz {v:+.1f}" for k, v in band_shares(path).items()))
    return 0


def cmd_quiet(a) -> int:
    r = ebur128(Path(a.part))
    frames = [(t, m) for t, m, _ in r["frames"]]
    voiced = [m for _, m in frames if m > -70]
    med = pct(voiced, 50)
    quiet = [1 if m < med - a.below else 0 for _, m in frames]
    per_s = 10                                    # ebur128 は 0.1 秒ごと
    w = int(a.window * per_s)
    csum = [0]
    for q in quiet:
        csum.append(csum[-1] + q)
    cands = sorted(((csum[i + w] - csum[i], frames[i][0]) for i in range(0, len(quiet) - w, per_s * 10)), reverse=True)
    picked: list[tuple[int, float]] = []
    for n, t in cands:
        if all(abs(t - u) >= a.window for _, u in picked):
            picked.append((n, t))
        if len(picked) >= a.top:
            break
    print(f"{Path(a.part).name}: 声の 0.4 秒窓の中央値 {med:.1f} LUFS、 それより {a.below:g} dB 以上静かな所を間と数える ({a.window:g} 秒窓)")
    for n, t in picked:
        print(f"  Part の {t:7.1f} 秒 ({int(t // 60)}:{t % 60:04.1f}) から: 間 {n / per_s:.1f} 秒")
    return 0


def render_clip(part: Path, bgm: Path, out: Path, at: float, dur: float, g_speech: float, g_bgm: float,
                bgm_pos: float, ceiling: float, bitrate: str) -> None:
    limit = 10 ** (ceiling / 20)
    fc = (f"[0:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,volume={g_speech:.3f}dB[s];"
          f"[1:a]atrim=start={bgm_pos:.4f}:duration={dur:.3f},asetpts=PTS-STARTPTS,"
          f"aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,volume={g_bgm:.3f}dB[b];"
          f"[s][b]amix=inputs=2:normalize=0:duration=first,"
          f"aresample=192000,alimiter=limit={limit:.6f}:attack=1:release=50:level=0:latency=1,aresample={SAMPLE_RATE},"
          f"afade=t=in:d=0.3,afade=t=out:st={max(dur - 1, 0):.3f}:d=1")
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-t", f"{dur:.3f}", "-i", str(part),
           # ⚠️ ループする入力に -ss を付けると、 折り返しのたびに -ss の位置へ戻る (実測) = 位置は filter の atrim で切る
           "-stream_loop", "-1", "-i", str(bgm), "-filter_complex", fc, "-t", f"{dur:.3f}"]
    cmd += ["-c:a", "libmp3lame", "-b:a", bitrate] if out.suffix == ".mp3" else []
    r = run(cmd + [str(out)])
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg が失敗: {r.stderr[-600:]}")


def cmd_clips(a) -> int:
    part, bgm = Path(a.part), Path(a.bgm)
    rec = json.loads(Path(a.finish_json).read_text()) if a.finish_json else {}
    last = (rec.get("renders") or [{}])[-1]
    g_speech = a.speech_gain if a.speech_gain is not None else last.get("gain_speech_dB")
    ceiling = a.ceiling if a.ceiling is not None else last.get("ceiling_dBFS")
    trim = a.trim_head if a.trim_head is not None else rec.get("trim_head_s")
    if None in (g_speech, ceiling, trim):
        raise SystemExit("声の利得・リミッターの上限・頭の削りが要る (--finish-json か --speech-gain / --ceiling / --trim-head)")
    bgm_i = ebur128(bgm)["I"]
    bgm_pos = (a.at - trim) % duration(bgm)
    levels = [float(x) for x in a.levels.split(",")]
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    body = a.at - trim
    label = f"本編{int(body // 60):02d}m{int(body % 60):02d}s"
    made: dict[float, Path] = {}
    for lv in levels:
        out = out_dir / f"{a.prefix}_{lv:g}LUFS_{label}.mp3"
        if out.exists() and not a.force:
            print(f"既にある (作り直すなら --force): {out}")
            made[lv] = out
            continue
        render_clip(part, bgm, out, a.at, a.dur, g_speech, lv - bgm_i, bgm_pos, ceiling, a.bitrate)
        made[lv] = out
        print(f"{out}  (BGM の利得 {lv - bgm_i:+.1f} dB、 声 {g_speech:+.1f} dB、 上限 {ceiling} dBFS)")
    if a.reference:
        rec_lv = rec.get("bgm_lufs")
        if rec_lv is None:
            raise SystemExit("--reference には記録の bgm_lufs が要る (--finish-json)")
        with tempfile.TemporaryDirectory() as td:
            clip = made.get(float(rec_lv))
            if clip is None:
                clip = Path(td) / "rec-level.mp3"
                render_clip(part, bgm, clip, a.at, a.dur, g_speech, float(rec_lv) - bgm_i, bgm_pos, ceiling, a.bitrate)
            start = body + rec.get("intro_jingle_s", 0.0)
            _, q_ref = gap_quantiles(Path(a.reference), a.skip, start=start, dur=a.dur)
            _, q_clip = gap_quantiles(clip, a.skip)
        worst = max(abs(x - y) for x, y in zip(q_ref, q_clip))
        print(f"照合 ({rec_lv:g} LUFS の段 対 配信音声の同じ箇所、 下側の分位 2/5/10/25/50 %):")
        print(f"  配信音声 {fmt_q(q_ref)}\n  切り出し {fmt_q(q_clip)}  → 差の最大 {worst:.1f} dB {'(再現できている)' if worst <= 0.5 else '⚠️ 合わない = 利得・位置・上限を確かめる'}")
    return 0


def selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        speech, bgm, rec_json = d / "speech.wav", d / "bgm.wav", d / "rec.json"
        # BGM は 13 秒で大きさが 0.15 → 1 に上がる = 位置がずれると間の大きさが変わる (ループの折り返しの検査になる)
        for out, expr, dur in ((speech, "0.3*sin(2*PI*300*t)*lt(mod(t\\,2)\\,1)", 30),
                               (bgm, "0.5*sin(2*PI*220*t)*(0.15+0.85*t/13)", 13)):
            r = run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc={expr}:s={SAMPLE_RATE}:d={dur}", str(out)])
            assert r.returncode == 0, r.stderr
        rec_json.write_text(json.dumps({"renders": [{"gain_speech_dB": 0.0, "ceiling_dBFS": -1.5}],
                                        "trim_head_s": 0.0, "intro_jingle_s": 0.0, "bgm_lufs": -40}))
        ns = argparse.Namespace
        # 全長の「配信音声」 の代わり = 頭から全部を -40 で
        full = d / "full.mp3"
        render_clip(speech, bgm, full, 0.0, 30.0, 0.0, -40 - ebur128(bgm)["I"], 0.0, -1.5, "128k")
        cmd_clips(ns(part=str(speech), bgm=str(bgm), finish_json=str(rec_json), speech_gain=None, ceiling=None, trim_head=None,
                     at=8.0, dur=16.0, levels="-30,-40", out_dir=str(d / "clips"), prefix="t", force=False, bitrate="128k",
                     reference=str(full), skip=2.0))
        q30 = gap_quantiles(d / "clips" / "t_-30LUFS_本編00m08s.mp3", 2.0)[1]
        q40 = gap_quantiles(d / "clips" / "t_-40LUFS_本編00m08s.mp3", 2.0)[1]
        assert 9.0 <= q30[0] - q40[0] <= 11.0, (q30, q40)            # 段の差 10 dB が一番静かな所 (BGM だけ) に出る
        # (5 % より上の分位は声の縁にかかる窓が混ざるので 10 dB ずつは動かない = 比べるときは同じ分位どうしで)
        _, q_ref = gap_quantiles(full, 2.0, start=8.0, dur=16.0)
        assert max(abs(x - y) for x, y in zip(q_ref, q40)) <= 0.5, (q_ref, q40)   # ループの折り返し込みで位置が合う
        prof = ebur128(bgm, gain_db=-40 - ebur128(bgm)["I"])
        assert abs(prof["I"] + 40) <= 0.3, prof["I"]
        cmd_quiet(ns(part=str(speech), window=6.0, top=2, below=20.0))
    print("selftest OK")
    return 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quiet")
    q.add_argument("part")
    q.add_argument("--window", type=float, default=60.0)
    q.add_argument("--top", type=int, default=5)
    q.add_argument("--below", type=float, default=20.0, help="声の中央値より何 dB 静かなら間と数えるか")
    c = sub.add_parser("clips")
    c.add_argument("part")
    c.add_argument("bgm")
    c.add_argument("--at", type=float, required=True, help="切り出しの頭 (Part の秒)")
    c.add_argument("--dur", type=float, default=60.0)
    c.add_argument("--levels", default="-40,-44,-48")
    c.add_argument("--finish-json")
    c.add_argument("--speech-gain", type=float)
    c.add_argument("--ceiling", type=float)
    c.add_argument("--trim-head", type=float)
    c.add_argument("--out-dir", default=".")
    c.add_argument("--prefix", default="BGM聞き比べ")
    c.add_argument("--bitrate", default="128k")
    c.add_argument("--reference")
    c.add_argument("--skip", type=float, default=5.0, help="照合で頭と尾から除く秒")
    c.add_argument("--force", action="store_true")
    p = sub.add_parser("profile")
    p.add_argument("files", nargs="+")
    p.add_argument("--target", type=float, default=-40.0)
    p.add_argument("--no-bands", action="store_true")
    g = sub.add_parser("gaps")
    g.add_argument("files", nargs="+")
    g.add_argument("--skip", type=float, default=20.0, help="頭と尾から除く秒 (ジングル・フェード)")
    a = ap.parse_args()
    return {"quiet": cmd_quiet, "clips": cmd_clips, "profile": cmd_profile, "gaps": cmd_gaps}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
