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
    4. MP3 128 kbps CBR / stereo / 48 kHz で 1 回だけ符号化。入力のメタデータは持ち越さず、タグを付け直す
    5. 書き出したものを測り直して検査する。リミッターで本編が下がった分・MP3 化で山が上限を越えた分を
       直して作り直す (最大 5 回)

検査 (1 つでも外れたら exit 1、出力は .FAILED を付けて残す):
    全体 loudness が目標 ± 1 LU / true peak ≤ -1.0 dBTP / 本編区間が目標 ± 0.5 LU /
    冒頭ジングル区間が目標 + offset ± 1 LU / 長さ = 冒頭ジングル + 本編 + 締めジングル (± 0.15 秒) /
    タグが付け直した分だけ

使い方:
    python3 audio-finish-episode.py <part> --jingle <jingle> [--artist 名前 --album 名前 --title 題]
    python3 audio-finish-episode.py <part> --jingle <j> --trim-head 1.98 --intro-jingle 10.4
    python3 audio-finish-episode.py <part> --jingle <j> --intro <冒頭用の音> --intro-jingle 9.86
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(part: Path, jingle: Path, out: Path, g_speech: float, g_jingle: float,
           ceiling: float, tags: dict[str, str], head: float = 0.0, speech_len: float | None = None,
           intro_len: float | None = None, intro: Path | None = None, g_intro: float | None = None) -> None:
    fmt = f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
    limit = 10 ** (ceiling / 20)
    graph = (
        f"[0:a]{fmt},"
        + (f"atrim=duration={intro_len:.3f},afade=t=out:st={intro_len - INTRO_FADE_S:.3f}:d={INTRO_FADE_S}," if intro_len else "")
        + f"volume={g_jingle if g_intro is None else g_intro:.3f}dB[j1];"
        f"[1:a]{fmt},atrim=start={head:.3f}:duration={speech_len:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d={FADE_IN_S},afade=t=out:st={speech_len - FADE_OUT_S:.3f}:d={FADE_OUT_S},"
        f"volume={g_speech:.3f}dB[s];"
        f"[2:a]{fmt},volume={g_jingle:.3f}dB[j2];"
        f"[j1][s][j2]concat=n=3:v=0:a=1,"
        # level=0: alimiter は既定で出力を上限まで自動で持ち上げる (= 音量が勝手に変わる) ので切る
        # latency=1: 先読みの遅延を補正する (切らないと頭が attack 分ずれて尾が欠ける)
        f"aresample=192000,alimiter=limit={limit:.6f}:attack=1:release=50:level=0:latency=1,"
        f"aresample={SAMPLE_RATE}[out]"
    )
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y",
           "-i", str(intro or jingle), "-i", str(part), "-i", str(jingle),
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
           intro_jingle: float = INTRO_JINGLE_S, intro: Path | None = None) -> bool:
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))
    src_intro = intro or jingle        # 冒頭に置く音 (既定 = 締めと同じジングル)
    jd, raw, idur = duration(jingle), duration(part), duration(src_intro)
    ji = intro_jingle if 0 < intro_jingle < idur else idur   # 冒頭の音の長さ (切らないなら全長)
    sd = raw - trim_head - trim_tail   # 実際に使う本編の長さ
    if sd <= FADE_IN_S + FADE_OUT_S:
        sys.exit(f"⚠️ 削りすぎ: 本編が残らない ({part})")
    mj, ms = measure(jingle), measure(part, trim_head, trim_head + sd)
    mi = measure(src_intro) if intro else mj
    say(f"入力  本編 {part.name}: I={ms['I']:.1f} LUFS  TP={ms['TP']:.1f} dBTP  長さ {sd:.2f} 秒"
        + (f" (元 {raw:.2f} 秒から頭 {trim_head} 秒・尾 {trim_tail} 秒を削った)" if trim_head or trim_tail else ""))
    say(f"入力  ジングル {jingle.name}: I={mj['I']:.1f} LUFS  TP={mj['TP']:.1f} dBTP  長さ {jd:.2f} 秒")
    if intro:
        say(f"入力  冒頭 {intro.name}: I={mi['I']:.1f} LUFS  TP={mi['TP']:.1f} dBTP  長さ {idur:.2f} 秒")

    g_speech = target - ms["I"]
    g_jingle = target + offset - mj["I"]
    g_intro = target + offset - mi["I"]   # 冒頭と締めは別の音でありうるので別々に揃える
    ceiling = CEILING_DBFS
    history = []
    for attempt in range(1, MAX_RENDERS + 1):
        render(part, jingle, out, g_speech, g_jingle, ceiling, tags, head=trim_head, speech_len=sd,
               intro_len=ji if ji < idur else None, intro=intro, g_intro=g_intro)
        whole = measure(out)
        speech = measure(out, ji, ji + sd)
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
    want_d = ji + sd + jd
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
         f"{got_d:.2f} 秒 (冒頭ジングル {ji:.2f} + 本編 + 締めジングル = {want_d:.2f} ± {DURATION_TOL_S})"),
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
           "trim_head_s": trim_head, "trim_tail_s": trim_tail, "intro_jingle_s": ji, "fade_in_s": FADE_IN_S, "fade_out_s": FADE_OUT_S,
           "target_LUFS": target, "jingle_offset_LU": offset, "bitrate": BITRATE, "tags": tags,
           "in_speech": ms, "in_jingle": mj, "renders": history,
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
        assert not ok_bad and (d / "bad.mp3.FAILED").exists(), "selftest: 無理な目標でも検査が通ってしまった"
    print("✅ selftest PASS (合成音で検査が通る / 無理な目標では落ちて .FAILED になる / 元のタグが消える / 削り・切りの勘定が合う"
          " / 冒頭だけ別の音でも合う)")


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
                    trim_head=a.trim_head, trim_tail=a.trim_tail, intro_jingle=a.intro_jingle, intro=a.intro)
        all_ok &= ok
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
