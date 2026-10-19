#!/usr/bin/env python3
"""ポッドキャストの 1 回分を仕上げる: 本編にジングルを頭と尾に付け、音量を揃えて配信用 MP3 に書き出し、測り直して検査する。

判断の理由と壊れ方の正本 = conventions/podcast-audio-finishing.md (この script はその機械化)。
番組ごとの値 (ジングル・タグ・冒頭ジングルを切る位置・Part ごとの頭の削り) は呼び出し側が渡す。

やること:
    1. 本編とジングルの音量を測る (ITU-R BS.1770 の integrated loudness と true peak)
    2. 両方を目標 (既定 -16 LUFS) に合わせる利得を決める
    3. [冒頭ジングル][本編][締めジングル] を連結 → 192 kHz に上げてリミッター (上限 -1.5 dBFS) → 48 kHz へ戻す
       本編は頭 0.03 秒・尾 0.05 秒を必ずフェードする。--trim-head/--trim-tail で頭尾を削れる。
       --intro-jingle で冒頭のジングルだけ指定秒で切る (締めは全長)
       --intro で冒頭だけ別の音 (かけ声を重ねたジングル等) にできる。音量は冒頭・締めを別々に測って揃える
       --outro-overlap で締めのジングルを本編の終わりの指定秒前から重ねる (盛り上がりを最後の言葉の下に敷き、
       アタックを語尾の直後に置く。本編の尾の無言は --trim-tail で削って揃える)
       --bgm で本編の下に BGM を敷く (BGM の integrated loudness を --bgm-lufs に合わせ、冒頭ジングルの終わりから
       フェードイン、締めのジングルが重なり始める所で消え終わるようフェードアウト。足りなければ頭から繰り返す。
       ジングルの上には乗せない。リミッターと符号化は本編と同じ 1 回だけ)
       --bgm-mute A-B で本編のその区間だけ BGM を消す (収録の中で曲を流した所など、音楽が二重になる区間。
       A・B は Part の元の時刻 = 頭を削る前の秒か h:mm:ss、前後 2 秒でなだらかに消して戻す。何度でも渡せる)
    4. MP3 128 kbps CBR / stereo / 48 kHz で 1 回だけ符号化。入力のメタデータは持ち越さず、タグを付け直す
    5. 書き出したものを測り直して検査する。リミッターで本編が下がった分・MP3 化で山が上限を越えた分を
       直して作り直す (最大 5 回)

検査 (1 つでも外れたら exit 1、出力は .FAILED を付けて残す):
    全体 loudness が目標 ± 1 LU / true peak ≤ -1.0 dBTP / 本編区間が目標 ± 0.5 LU /
    冒頭ジングル区間が目標 + offset ± 1 LU / 長さ = 冒頭ジングル + 本編 + 締めジングル − 重ね (± 0.15 秒) /
    タグが付け直した分だけ

使い方:
    python3 audio-finish-episode.py <part> --jingle <jingle> [--artist 名前 --album 名前 --title 題]
    python3 audio-finish-episode.py <part> --jingle <j> --trim-head 1.98 --intro-jingle 10.4
    python3 audio-finish-episode.py <part> --jingle <j> --intro <冒頭用の音> --intro-jingle 9.86
    python3 audio-finish-episode.py <part> --jingle <j> --trim-tail 0.3 --outro-overlap 2.5
    python3 audio-finish-episode.py <part> --jingle <j> --outro-overlap 2.5 --bgm <loop.flac> --bgm-lufs -40
    python3 audio-finish-episode.py --measure <file>...      # 測るだけ
    python3 audio-finish-episode.py --selftest               # 合成音で検査が効くか確かめる

出力の既定 = 入力が <dir>/parts/ にあれば <dir>/finished/<名前>.mp3、それ以外は --out 必須
(+ 同名 .json に測定値・利得・削り量の記録)。既存の出力は --force なしでは上書きしない。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TARGET_LUFS = -16.0        # Apple Podcasts: -16 LKFS ± 1
TOLERANCE_LU = 1.0
TP_MAX_DBTP = -1.0         # Apple Podcasts: true peak ≤ -1 dBFS
CEILING_DBFS = -1.5        # リミッターの上限。MP3 化で山が少し伸びる分の余裕を取る
SPEECH_TOL_LU = 0.5
JINGLE_TOL_LU = 1.0
DURATION_TOL_S = 0.15
MAX_RENDERS = 5
BITRATE = "128k"
SAMPLE_RATE = 48000
FADE_IN_S = 0.03    # 本編の頭。無音から声がいきなり立ち上がるとプツッと聞こえる (実測)
FADE_OUT_S = 0.05   # 本編の尾。話の途中で切れている Part でもジングルへ滑らかにつなぐ
# 冒頭のジングルを切る位置 (秒)。既定 0 = 切らない。ジングルが音の後に長い無音を持っていると、話し始めまでが
# 空きすぎる (実測) ので、音が -60 dB を切った少し後で切る値を呼び出し側が渡す。締めのジングルは切らない
INTRO_JINGLE_S = 0.0
INTRO_FADE_S = 0.2
# 本編の下に敷く BGM (--bgm)。声 -16 LUFS の 24 dB 下が既定 (16 dB 下は「うるさい」 の実測、
# conventions/podcast-audio-finishing.md#bgm-under-speech)。番組で決めた値は呼び出し側が渡す
BGM_LUFS = -40.0
BGM_FADE_IN_S = 4.0    # 冒頭ジングルが終わってから
BGM_FADE_OUT_S = 6.0   # 締めのジングルが重なり始める所で消え終わる
BGM_MUTE_FADE_S = 2.0  # --bgm-mute の区間の前後で BGM を消す・戻すのにかける秒


def bgm_mute_expr(ranges: list[tuple[float, float]], head: float, fade: float = BGM_MUTE_FADE_S) -> str | None:
    """BGM の利得の式 (ffmpeg の volume の eval=frame 用、t = 本編の頭を削った後の秒)。
    区間の中は 0、区間の前後 fade 秒で 0 と 1 の間を直線で動き、外は 1。区間ごとの式の積。"""
    if not ranges:
        return None
    terms = [f"clip(max(({a - head:.3f}-t)/{fade},(t-{b - head:.3f})/{fade}),0,1)" for a, b in ranges]
    return "*".join(terms)


def parse_range(text: str) -> tuple[float, float]:
    """'A-B' (秒か h:mm:ss / m:ss) を (A, B) に。"""
    def sec(s: str) -> float:
        parts = [float(p) for p in s.strip().split(":")]
        v = 0.0
        for p in parts:
            v = v * 60 + p
        return v
    try:
        a, b = text.split("-", 1)
        lo, hi = sec(a), sec(b)
    except ValueError:
        raise argparse.ArgumentTypeError(f"区間は A-B の形 (秒か h:mm:ss): {text}") from None
    if not hi > lo >= 0:
        raise argparse.ArgumentTypeError(f"区間の終わりが始まりより後でない: {text}")
    return lo, hi


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"⚠️ command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr[-2000:]}")
    return p.stderr + p.stdout


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip())


def measure(path: Path, start: float | None = None, end: float | None = None) -> dict:
    """ebur128 (true peak は 4 倍オーバーサンプル) で integrated loudness と true peak を測る。"""
    af = "ebur128=peak=true:framelog=quiet"
    if start is not None:
        trim = f"atrim=start={start:.3f}" + (f":end={end:.3f}" if end is not None else "")
        af = f"{trim},asetpts=PTS-STARTPTS,{af}"
    text = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", af, "-f", "null", "-"])
    summary = text[text.rindex("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary)
    tp = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    lra = re.search(r"LRA:\s+(-?[\d.]+) LU", summary)
    if not (i and tp):
        sys.exit(f"⚠️ ebur128 の出力を読めない: {path}")
    to_f = lambda s: -math.inf if s == "-inf" else float(s)
    return {"I": to_f(i.group(1)), "TP": to_f(tp.group(1)), "LRA": float(lra.group(1)) if lra else None}


def band_level(path: Path, start: float, end: float, freq: float) -> float:
    """区間の、ある周波数の近くだけの平均レベル (dB)。selftest で「その音が鳴っているか」 を見る。"""
    text = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                f"atrim=start={start:.3f}:end={end:.3f},bandpass=f={freq}:width_type=q:w=30,volumedetect",
                "-f", "null", "-"])
    return float(re.findall(r"mean_volume:\s+(-?[\d.]+) dB", text)[-1])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(part: Path, jingle: Path, out: Path, g_speech: float, g_jingle: float,
           ceiling: float, tags: dict[str, str], head: float = 0.0, speech_len: float | None = None,
           intro_len: float | None = None, intro: Path | None = None, g_intro: float | None = None,
           outro_at: float | None = None, bgm: Path | None = None, g_bgm: float = 0.0, bgm_len: float = 0.0,
           bgm_fade_in: float = BGM_FADE_IN_S, bgm_fade_out: float = BGM_FADE_OUT_S,
           bgm_mute: str | None = None) -> None:
    """outro_at を渡すと、締めのジングルを連結せずに出力のその秒から重ねる (本編はその下で最後まで鳴る)。
    bgm を渡すと、本編の頭から bgm_len 秒だけ BGM を本編に足してから連結する (= ジングルの上には乗らない)。
    bgm_mute = BGM の利得の式 (bgm_mute_expr)。その区間だけ BGM を消す。"""
    fmt = f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
    limit = 10 ** (ceiling / 20)
    graph = (
        f"[0:a]{fmt},"
        + (f"atrim=duration={intro_len:.3f},afade=t=out:st={intro_len - INTRO_FADE_S:.3f}:d={INTRO_FADE_S}," if intro_len else "")
        + f"volume={g_jingle if g_intro is None else g_intro:.3f}dB[j1];"
        f"[1:a]{fmt},atrim=start={head:.3f}:duration={speech_len:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d={FADE_IN_S},afade=t=out:st={speech_len - FADE_OUT_S:.3f}:d={FADE_OUT_S},"
        f"volume={g_speech:.3f}dB" + ("[s0];" if bgm else "[s];")
        # BGM は -stream_loop -1 で無限に繰り返して入るので、使う長さで切ってからフェードする。
        # duration=first = 本編の長さで終わる (BGM が先に消えても本編は最後まで鳴る)
        + (f"[3:a]{fmt},atrim=duration={bgm_len:.3f},asetpts=PTS-STARTPTS,"
           + (f"volume=volume='{bgm_mute}':eval=frame," if bgm_mute else "")
           + f"afade=t=in:st=0:d={bgm_fade_in},afade=t=out:st={bgm_len - bgm_fade_out:.3f}:d={bgm_fade_out},"
           f"volume={g_bgm:.3f}dB[b];[s0][b]amix=inputs=2:duration=first:normalize=0[s];" if bgm else "")
        + f"[2:a]{fmt},volume={g_jingle:.3f}dB"
        # 重ねるときは足し算だけ (normalize=0: amix は既定で入力数で割って音量を下げる)。遅延はサンプル数で渡す
        + (f",adelay=delays={round(outro_at * SAMPLE_RATE)}S:all=1[j2];"
           f"[j1][s]concat=n=2:v=0:a=1[body];[body][j2]amix=inputs=2:duration=longest:normalize=0,"
           if outro_at is not None else "[j2];[j1][s][j2]concat=n=3:v=0:a=1,")
        +
        # level=0: alimiter は既定で出力を上限まで自動で持ち上げる (= 音量が勝手に変わる) ので切る
        # latency=1: 先読みの遅延を補正する (切らないと頭が attack 分ずれて尾が欠ける)
        f"aresample=192000,alimiter=limit={limit:.6f}:attack=1:release=50:level=0:latency=1,"
        f"aresample={SAMPLE_RATE}[out]"
    )
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y",
           "-i", str(intro or jingle), "-i", str(part), "-i", str(jingle),
           *(["-stream_loop", "-1", "-i", str(bgm)] if bgm else []),
           "-filter_complex", graph, "-map", "[out]",
           "-map_metadata", "-1", "-id3v2_version", "3", "-write_id3v1", "0",
           "-c:a", "libmp3lame", "-b:a", BITRATE, "-ar", str(SAMPLE_RATE), "-ac", "2"]
    for k, v in tags.items():
        cmd += ["-metadata", f"{k}={v}"]
    run(cmd + [str(out)])


def format_tags(path: Path) -> dict[str, str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return {k.lower(): v for k, v in json.loads(out).get("format", {}).get("tags", {}).items()}


def finish(part: Path, jingle: Path, out: Path, *, target: float, offset: float,
           tags: dict[str, str], quiet: bool = False, trim_head: float = 0.0, trim_tail: float = 0.0,
           intro_jingle: float = INTRO_JINGLE_S, intro: Path | None = None, outro_overlap: float = 0.0,
           bgm: Path | None = None, bgm_lufs: float = BGM_LUFS, bgm_fade_in: float = BGM_FADE_IN_S,
           bgm_fade_out: float = BGM_FADE_OUT_S, bgm_mute: list[tuple[float, float]] | None = None) -> bool:
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))
    bgm_mute = sorted(bgm_mute or [])
    src_intro = intro or jingle        # 冒頭に置く音 (既定 = 締めと同じジングル)
    jd, raw, idur = duration(jingle), duration(part), duration(src_intro)
    ji = intro_jingle if 0 < intro_jingle < idur else idur   # 冒頭の音の長さ (切らないなら全長)
    sd = raw - trim_head - trim_tail   # 実際に使う本編の長さ
    if sd <= FADE_IN_S + FADE_OUT_S:
        sys.exit(f"⚠️ 削りすぎ: 本編が残らない ({part})")
    if not 0 <= outro_overlap < min(jd, sd):
        sys.exit(f"⚠️ --outro-overlap {outro_overlap} は 0 以上で、締めのジングル ({jd:.2f} 秒) と本編より短くする")
    bgm_len = sd - outro_overlap       # BGM を敷く長さ = 本編のうち締めのジングルが重なる前まで
    if bgm and bgm_len <= bgm_fade_in + bgm_fade_out:
        sys.exit(f"⚠️ 本編 ({bgm_len:.2f} 秒) が BGM のフェード ({bgm_fade_in} + {bgm_fade_out} 秒) より短い")
    if bgm_mute and not bgm:
        sys.exit("⚠️ --bgm-mute は --bgm と一緒に渡す")
    for a, b in bgm_mute:   # Part の元の時刻で、使う本編 (頭と尾を削った残り) の中に入っているか
        if not trim_head <= a < b <= trim_head + sd:
            sys.exit(f"⚠️ --bgm-mute {a:.2f}-{b:.2f} が本編 ({trim_head:.2f}〜{trim_head + sd:.2f} 秒、Part の元の時刻) の外")
    mute_expr = bgm_mute_expr(bgm_mute, trim_head)
    mj, ms = measure(jingle), measure(part, trim_head, trim_head + sd)
    mb = measure(bgm) if bgm else None
    mi = measure(src_intro) if intro else mj
    say(f"入力  本編 {part.name}: I={ms['I']:.1f} LUFS  TP={ms['TP']:.1f} dBTP  長さ {sd:.2f} 秒"
        + (f" (元 {raw:.2f} 秒から頭 {trim_head} 秒・尾 {trim_tail} 秒を削った)" if trim_head or trim_tail else ""))
    say(f"入力  ジングル {jingle.name}: I={mj['I']:.1f} LUFS  TP={mj['TP']:.1f} dBTP  長さ {jd:.2f} 秒")
    if intro:
        say(f"入力  冒頭 {intro.name}: I={mi['I']:.1f} LUFS  TP={mi['TP']:.1f} dBTP  長さ {idur:.2f} 秒")
    g_bgm = bgm_lufs - mb["I"] if bgm else 0.0   # BGM 全体の loudness で合わせる (区間ごとには追わない)
    if bgm:
        say(f"入力  BGM {bgm.name}: I={mb['I']:.1f} LUFS  TP={mb['TP']:.1f} dBTP  長さ {duration(bgm):.2f} 秒"
            f" → 利得 {g_bgm:+.2f} dB で {bgm_lufs} LUFS、出力の {ji:.2f}〜{ji + bgm_len:.2f} 秒に敷く"
            f" (フェード {bgm_fade_in} / {bgm_fade_out} 秒)")
        for a, b in bgm_mute:
            say(f"      BGM を消す区間: Part の {a:.2f}〜{b:.2f} 秒 = 出力の {ji + a - trim_head:.2f}〜{ji + b - trim_head:.2f} 秒"
                f" (前後 {BGM_MUTE_FADE_S} 秒でなだらかに)")

    g_speech = target - ms["I"]
    g_jingle = target + offset - mj["I"]
    g_intro = target + offset - mi["I"]   # 冒頭と締めは別の音でありうるので別々に揃える
    ceiling = CEILING_DBFS
    history = []
    for attempt in range(1, MAX_RENDERS + 1):
        render(part, jingle, out, g_speech, g_jingle, ceiling, tags, head=trim_head, speech_len=sd,
               intro_len=ji if ji < idur else None, intro=intro, g_intro=g_intro,
               outro_at=ji + sd - outro_overlap if outro_overlap else None,
               bgm=bgm, g_bgm=g_bgm, bgm_len=bgm_len, bgm_fade_in=bgm_fade_in, bgm_fade_out=bgm_fade_out,
               bgm_mute=mute_expr)
        whole = measure(out)
        speech = measure(out, ji, ji + sd - outro_overlap)   # 締めを重ねた所は本編区間に入れない
        head = measure(out, 0, ji)
        rec = {"attempt": attempt, "gain_speech_dB": round(g_speech, 2), "gain_jingle_dB": round(g_jingle, 2),
               "gain_intro_dB": round(g_intro, 2),
               "ceiling_dBFS": ceiling, "pre_limiter_peak_dBTP": round(ms["TP"] + g_speech, 2),
               "out_whole": whole, "out_speech": speech, "out_head_jingle": head}
        history.append(rec)
        say(f"書出 {attempt} 回目: 本編利得 {g_speech:+.2f} dB / ジングル利得 {g_jingle:+.2f} dB"
            + (f" / 冒頭利得 {g_intro:+.2f} dB" if intro else "") + f" / 上限 {ceiling} dBFS"
            f" → 全体 I={whole['I']:.1f} TP={whole['TP']:.1f}、本編区間 I={speech['I']:.1f}、ジングル区間 I={head['I']:.1f}")
        short = target - speech["I"]
        over = whole["TP"] - TP_MAX_DBTP
        if over <= 0 and abs(short) <= SPEECH_TOL_LU / 2:
            break
        if over > 0:
            ceiling -= over + 0.2   # MP3 化で上限を越えた分 + 余裕だけ上限を下げる
        g_speech += short           # リミッターで本編が下がった (or 上がった) 分を足す

    got_d = duration(out)
    want_d = ji + sd + jd - outro_overlap
    got_tags = format_tags(out)
    extra = sorted(set(got_tags) - {k.lower() for k in tags} - {"encoder"})
    last = history[-1]
    checks = [
        ("全体の loudness", abs(last["out_whole"]["I"] - target) <= TOLERANCE_LU,
         f"{last['out_whole']['I']:.1f} LUFS (目標 {target} ± {TOLERANCE_LU})"),
        ("true peak", last["out_whole"]["TP"] <= TP_MAX_DBTP,
         f"{last['out_whole']['TP']:.1f} dBTP (≤ {TP_MAX_DBTP})"),
        ("本編区間の loudness", abs(last["out_speech"]["I"] - target) <= SPEECH_TOL_LU,
         f"{last['out_speech']['I']:.1f} LUFS (目標 {target} ± {SPEECH_TOL_LU})"),
        ("ジングル区間の loudness", abs(last["out_head_jingle"]["I"] - (target + offset)) <= JINGLE_TOL_LU,
         f"{last['out_head_jingle']['I']:.1f} LUFS (目標 {target + offset} ± {JINGLE_TOL_LU})"),
        ("長さ", abs(got_d - want_d) <= DURATION_TOL_S,
         f"{got_d:.2f} 秒 (冒頭ジングル {ji:.2f} + 本編 + 締めジングル"
         + (f" − 重ね {outro_overlap:.2f}" if outro_overlap else "") + f" = {want_d:.2f} ± {DURATION_TOL_S})"),
        ("元ファイルのタグが残っていない", not extra, f"余分なタグ = {extra or 'なし'}"),
    ]
    ok = all(c[1] for c in checks)
    for name, passed, detail in checks:
        say(f"  {'✅' if passed else '❌'} {name}: {detail}")
    limited = last["pre_limiter_peak_dBTP"] - last["ceiling_dBFS"]
    say(f"  ℹ️ リミッターが削った最大量 ≈ {max(limited, 0):.1f} dB"
        + ("  ← 6 dB を超えたので、その箇所を聞いて歪みを確かめる" if limited > 6 else ""))

    log = {"part": str(part), "part_sha256": sha256(part), "jingle": str(jingle), "jingle_sha256": sha256(jingle),
           "intro": str(intro) if intro else None, "intro_sha256": sha256(intro) if intro else None,
           "in_intro": mi if intro else None,
           "trim_head_s": trim_head, "trim_tail_s": trim_tail, "intro_jingle_s": ji, "outro_overlap_s": outro_overlap, "fade_in_s": FADE_IN_S, "fade_out_s": FADE_OUT_S,
           "target_LUFS": target, "jingle_offset_LU": offset, "bitrate": BITRATE, "tags": tags,
           "in_speech": ms, "in_jingle": mj, "renders": history,
           "bgm": str(bgm) if bgm else None, "bgm_sha256": sha256(bgm) if bgm else None, "in_bgm": mb,
           "bgm_lufs": bgm_lufs if bgm else None, "gain_bgm_dB": round(g_bgm, 2) if bgm else None,
           "bgm_start_s": round(ji, 3) if bgm else None, "bgm_end_s": round(ji + bgm_len, 3) if bgm else None,
           "bgm_fade_in_s": bgm_fade_in if bgm else None, "bgm_fade_out_s": bgm_fade_out if bgm else None,
           "bgm_mute_part_s": [[a, b] for a, b in bgm_mute] or None,
           "bgm_mute_out_s": [[round(ji + a - trim_head, 3), round(ji + b - trim_head, 3)] for a, b in bgm_mute] or None,
           "bgm_mute_fade_s": BGM_MUTE_FADE_S if bgm_mute else None,
           "checks": [{"name": n, "pass": p, "detail": d} for n, p, d in checks], "ok": ok}
    out.with_suffix(".json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n")
    if not ok:
        failed = out.with_name(out.name + ".FAILED")
        out.replace(failed)
        say(f"❌ 検査に通らなかった → {failed} (conventions/podcast-audio-finishing.md §検査に落ちたとき)")
    return ok


def selftest() -> None:
    """合成音 (声の代わりにピークの鋭い変調ノイズ、ジングルの代わりに大きめのサイン波) で一連を回す。"""
    import shutil
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:  # run-all-checks の契約: 依存が無い環境では理由を出して SKIP (exit 0)
        print(f"SKIP: {' / '.join(missing)} が無い (audio-finish-episode selftest)")
        return
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        part, jingle, out = d / "part.m4a", d / "jingle.mp3", d / "out.mp3"
        # 本編役: -20 LUFS 前後で、ときどき 0 dBFS 近い山が立つ (= リミッターが効く状況を作る)
        run(["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i",
             "anoisesrc=d=20:c=pink:a=0.05:r=48000,volume='if(lt(mod(t,4),0.05),4,1)':eval=frame",
             "-ac", "2", "-metadata", "artist=SHOULD-NOT-SURVIVE", "-c:a", "aac", "-b:a", "96k", str(part)])
        # ジングル役: 無音 0.5 秒 + 大きいサイン波 3 秒 + 無音 1 秒
        run(["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i",
             "sine=f=440:d=3:r=48000,volume=0.9,adelay=500|500,apad=pad_dur=1",
             "-ac", "2", "-metadata", "artist=SHOULD-NOT-SURVIVE", "-c:a", "libmp3lame", "-b:a", "192k", str(jingle)])
        ok = finish(part, jingle, out, target=TARGET_LUFS, offset=0.0,
                    tags={"title": "selftest", "artist": "selftest"}, quiet=False)
        log = json.loads(out.with_suffix(".json").read_text())
        assert ok, "selftest: 検査に落ちた"
        assert "SHOULD-NOT-SURVIVE" not in json.dumps(format_tags(out)), "selftest: 元のタグが残った"
        assert log["renders"][-1]["out_whole"]["TP"] <= TP_MAX_DBTP
        # 検査が本当に落ちるかも確かめる (= 検査が常に通るだけの飾りになっていないか)
        ok_bad = finish(part, jingle, d / "bad.mp3", target=-6.0, offset=0.0,
                        tags={"title": "selftest-bad"}, quiet=True)
        # 頭を削り、冒頭ジングルを切っても長さの検査が合う (= 削り・切りの勘定が正しい)
        ok_cut = finish(part, jingle, d / "cut.mp3", target=TARGET_LUFS, offset=0.0,
                        tags={"title": "selftest-cut"}, quiet=True, trim_head=1.0, intro_jingle=3.6)
        assert ok_cut, "selftest: 頭の削り・冒頭ジングルの切りで検査に落ちた"
        # 冒頭だけ別の音 (大きさも長さも締めと違う) にしても、音量と長さの検査が合う。
        # 冒頭の音 (2.5 秒) はジングル (4.5 秒) と長さが違うので、冒頭の音が無視されると長さで分かる
        intro = d / "intro.wav"
        run(["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "sine=f=220:d=2:r=48000,volume=0.2,apad=pad_dur=0.5",
             "-ac", "2", str(intro)])
        ok_intro = finish(part, jingle, d / "intro.mp3", target=TARGET_LUFS, offset=0.0,
                          tags={"title": "selftest-intro"}, quiet=True, intro=intro, intro_jingle=0.0)
        assert ok_intro, "selftest: 冒頭だけ別の音にすると検査に落ちた"
        want = duration(intro) + duration(part) + duration(jingle)
        assert abs(duration(d / "intro.mp3") - want) <= DURATION_TOL_S, "selftest: 冒頭の音が使われていない (長さが合わない)"
        # 締めを重ねると、その分だけ短くなり、重ねた所で本編とジングルが同時に鳴る (= 連結でなく足し算になっている)
        ok_ov = finish(part, jingle, d / "overlap.mp3", target=TARGET_LUFS, offset=0.0,
                       tags={"title": "selftest-overlap"}, quiet=True, trim_tail=1.0, outro_overlap=1.5)
        assert ok_ov, "selftest: 締めを重ねると検査に落ちた"
        end = duration(jingle) + duration(part) - 1.0   # 出力の中で本編が終わる時刻
        assert abs(duration(d / "overlap.mp3") - (end + duration(jingle) - 1.5)) <= DURATION_TOL_S, \
            "selftest: 締めの重ねの長さが合わない"
        # ジングル役は 0.5 秒の無音の後にサイン波が鳴る = 本編の終わりの 1.0 秒前から鳴り始める。
        # 本編の終わり直前 (重なっている所) と、ジングルが始まる前を 440 Hz の近くで比べる
        on = band_level(d / "overlap.mp3", end - 0.9, end - 0.1, 440)
        off = band_level(d / "overlap.mp3", end - 2.4, end - 1.6, 440)
        assert on - off > 10, f"selftest: 重ねた所でジングルが鳴っていない ({on:.1f} vs {off:.1f} dB)"
        # BGM (3 kHz のサイン波 7 秒 = 本編より短いので繰り返される) を敷くと、本編の中では鳴り、ジングルの上では鳴らない。
        # 締めを重ねた版 (overlap.mp3) と同じ条件で作り、3 kHz の近くを区間ごとに比べる。BGM は声の 6 dB 下
        # (= 本編役のピンクノイズの 3 kHz 帯より約 13 dB 上。10 dB 下だと差が 9 dB で判定が際どかった、実測)
        bgm = d / "bgm.wav"
        run(["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "sine=f=3000:d=7:r=48000", "-ac", "2", str(bgm)])
        ok_bgm = finish(part, jingle, d / "bgm.mp3", target=TARGET_LUFS, offset=0.0,
                        tags={"title": "selftest-bgm"}, quiet=True, trim_tail=1.0, outro_overlap=1.5,
                        bgm=bgm, bgm_lufs=TARGET_LUFS - 6)
        assert ok_bgm, "selftest: BGM を敷くと検査に落ちた"
        ji = duration(jingle)
        lv = lambda f, a, b: band_level(d / f, a, b, 3000)
        # フェードイン (4 秒) の後・BGM の 1 周目 (7 秒) の切れ目を越えた所・フェードアウトの前
        body_on, body_off = lv("bgm.mp3", ji + 8, ji + 11), lv("overlap.mp3", ji + 8, ji + 11)
        assert body_on - body_off > 6, f"selftest: 本編の中で BGM が鳴っていない ({body_on:.1f} vs {body_off:.1f} dB)"
        for name, a, b in (("冒頭ジングル", 0.6, ji - 0.2), ("締めのジングル", end + 0.2, end + 1.8)):
            on, off = lv("bgm.mp3", a, b), lv("overlap.mp3", a, b)
            assert on - off < 3, f"selftest: {name}の上で BGM が鳴っている ({on:.1f} vs {off:.1f} dB)"
        blog = json.loads((d / "bgm.json").read_text())
        assert abs(blog["bgm_end_s"] - (end - 1.5)) < 0.01, "selftest: BGM の終わりが締めの重なり始めと合わない"
        # --bgm-mute: Part の 9〜10 秒 (頭を 1 秒削るので本編の 8〜9 秒) だけ BGM を消す。
        # 本編の時刻で: フェードイン 0〜4 / 消す 6〜8 で下げ、8〜9 は無し、9〜11 で戻す / フェードアウト 10.5〜16.5。
        # 消した所は BGM なしの版と同じ、手前と後ろは鳴っている
        ok_mute = finish(part, jingle, d / "mute.mp3", target=TARGET_LUFS, offset=0.0,
                         tags={"title": "selftest-mute"}, quiet=True, trim_head=1.0, trim_tail=1.0, outro_overlap=1.5,
                         bgm=bgm, bgm_lufs=TARGET_LUFS - 6, bgm_mute=[(9.0, 10.0)])
        assert ok_mute, "selftest: BGM を一部だけ消すと検査に落ちた"
        ok_nob = finish(part, jingle, d / "nobgm.mp3", target=TARGET_LUFS, offset=0.0,
                        tags={"title": "selftest-nobgm"}, quiet=True, trim_head=1.0, trim_tail=1.0, outro_overlap=1.5)
        assert ok_nob
        for name, a, b, muted in (("消す区間の手前", 4.5, 5.5, False), ("消した区間", 8.1, 8.9, True),
                                  ("戻した後", 11.2, 11.8, False)):
            on, off = lv("mute.mp3", ji + a, ji + b), lv("nobgm.mp3", ji + a, ji + b)
            assert (on - off < 3) if muted else (on - off > 6), \
                f"selftest: {name}で BGM が{'鳴っている' if muted else '鳴っていない'} ({on:.1f} vs {off:.1f} dB)"
        assert json.loads((d / "mute.json").read_text())["bgm_mute_out_s"] == [[round(ji + 8.0, 3), round(ji + 9.0, 3)]]
        try:
            parse_range("5-3")
            raise AssertionError("selftest: 逆向きの区間を受け付けた")
        except argparse.ArgumentTypeError:
            pass
        assert parse_range("1:02-1:03:04") == (62.0, 3784.0)
        assert not ok_bad and (d / "bad.mp3.FAILED").exists(), "selftest: 無理な目標でも検査が通ってしまった"
    print("✅ selftest PASS (合成音で検査が通る / 無理な目標では落ちて .FAILED になる / 元のタグが消える / 削り・切りの勘定が合う"
          " / 冒頭だけ別の音でも合う / 締めを重ねると長さが合い、重ねた所でジングルが鳴る"
          " / BGM を敷くと本編の中で繰り返し鳴り、ジングルの上では鳴らない / --bgm-mute の区間だけ BGM が消えて戻る)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", nargs="*", type=Path)
    ap.add_argument("--jingle", type=Path, help="頭と尾に付けるジングル (仕上げるときは必須)")
    ap.add_argument("--artist", help="ID3 artist (番組名など)")
    ap.add_argument("--album", help="ID3 album (既定 = artist と同じ)")
    ap.add_argument("--genre", default="Podcast")
    ap.add_argument("--target", type=float, default=TARGET_LUFS)
    ap.add_argument("--jingle-offset", type=float, default=0.0,
                    help="ジングルを本編より何 LU 大きく (負なら小さく) するか。既定 0 = 同じ")
    ap.add_argument("--title", help="エピソード名 (ID3 title)。省略時は Part のファイル名")
    ap.add_argument("--trim-head", type=float, default=0.0,
                    help="本編の頭を何秒削るか (録画開始で切れた語の断片などを落とす。削る前に聞いて決める)")
    ap.add_argument("--trim-tail", type=float, default=0.0, help="本編の尾を何秒削るか")
    ap.add_argument("--intro-jingle", type=float, default=INTRO_JINGLE_S,
                    help=f"冒頭のジングル (--intro を渡したらその音) を何秒で切るか (既定 {INTRO_JINGLE_S}。0 で切らない)")
    ap.add_argument("--intro", type=Path,
                    help="冒頭だけ別の音にする (例: かけ声を重ねたジングル)。締めは常に --jingle。既定 = --jingle と同じ")
    ap.add_argument("--outro-overlap", type=float, default=0.0,
                    help="締めのジングルを本編の終わりの何秒前から重ねるか (既定 0 = 本編の後に続ける)。"
                         "ジングルのアタックの時刻を渡すと、本編の終わりにアタックが来る")
    ap.add_argument("--bgm", type=Path,
                    help="本編の下に敷く BGM (ループ素材は WAV / FLAC = AAC は頭の無音でつなぎ目が切れる)。既定 = 敷かない")
    ap.add_argument("--bgm-lufs", type=float, default=BGM_LUFS,
                    help=f"BGM の integrated loudness をいくつに合わせるか (既定 {BGM_LUFS} = 声 -16 の 24 dB 下)")
    ap.add_argument("--bgm-fade-in", type=float, default=BGM_FADE_IN_S,
                    help=f"BGM のフェードイン (秒、冒頭ジングルの終わりから。既定 {BGM_FADE_IN_S})")
    ap.add_argument("--bgm-fade-out", type=float, default=BGM_FADE_OUT_S,
                    help=f"BGM のフェードアウト (秒、締めのジングルが重なり始める所で消え終わる。既定 {BGM_FADE_OUT_S})")
    ap.add_argument("--bgm-mute", type=parse_range, action="append", default=[], metavar="A-B",
                    help="この区間だけ BGM を消す (Part の元の時刻 = 頭を削る前、秒か h:mm:ss。何度でも)。"
                         f"収録の中で曲を流した所など。前後 {BGM_MUTE_FADE_S} 秒でなだらかに")
    ap.add_argument("--out", type=Path, help="出力先 (Part を 1 本だけ渡すとき)")
    ap.add_argument("--force", action="store_true", help="既存の出力を上書きする")
    ap.add_argument("--measure", action="store_true", help="測るだけ")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.part:
        ap.error("Part のファイルを渡す")
    if a.measure:
        for p in a.part:
            m = measure(p)
            print(f"{p}: I={m['I']:.1f} LUFS  TP={m['TP']:.1f} dBTP  LRA={m['LRA']} LU  長さ {duration(p):.2f} 秒")
        return
    if a.out and len(a.part) != 1:
        ap.error("--out は Part 1 本のときだけ")
    if not a.jingle:
        ap.error("--jingle を渡す")

    all_ok = True
    for part in a.part:
        if a.out:
            out = a.out
        elif part.parent.name == "parts":
            out = part.parent.parent / "finished" / f"{part.stem}.mp3"
        else:
            sys.exit(f"⚠️ parts/ の外のファイルは --out で出力先を指定する: {part}")
        if out.exists() and not a.force:
            sys.exit(f"⚠️ 出力が既にある (上書きは --force): {out}")
        out.parent.mkdir(parents=True, exist_ok=True)
        tags = {"title": a.title or part.stem, "genre": a.genre}
        if a.artist:
            tags["artist"] = a.artist
        if a.album or a.artist:
            tags["album"] = a.album or a.artist
        print(f"== {part} → {out}", flush=True)
        ok = finish(part, a.jingle, out, target=a.target, offset=a.jingle_offset, tags=tags,
                    trim_head=a.trim_head, trim_tail=a.trim_tail, intro_jingle=a.intro_jingle, intro=a.intro,
                    outro_overlap=a.outro_overlap, bgm=a.bgm, bgm_lufs=a.bgm_lufs,
                    bgm_fade_in=a.bgm_fade_in, bgm_fade_out=a.bgm_fade_out, bgm_mute=a.bgm_mute)
        all_ok &= ok
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
