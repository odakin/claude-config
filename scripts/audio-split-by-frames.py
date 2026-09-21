#!/usr/bin/env python3
"""長い録音 (AAC の .m4a) を、指定したフレームの境目で無劣化 (再符号化なし) に分け、元と一致するかを確かめる。

判断の理由と壊れ方の正本 = conventions/audio-transcription.md#splitting-long-recordings (この script はその機械化)。
どこで切るか (音の切れ目と話の切れ目の両方) は呼び出し側が決める。この script は「決めた境目で正確に切れたか」 だけを受け持つ。

なぜフレーム数で切るか:
    `ffmpeg -c copy` に `-to` / `-t` を秒で渡すと、境目が AAC のフレーム (1024 サンプル) に丸められて、
    隣の part と 1 フレーム重なる・合計が長くなることがある。ここでは各 part を「開始パケットの実際の時刻」 で `-ss` し、
    `-frames:a <フレーム数>` で写して、境目をフレームにそろえる。

フレーム番号と時刻: フレーム (= パケット) k の時刻はパケットの pts を読んで使う。先頭に符号化の遅れ (priming) がある音声は
    最初のパケットの時刻が負で、k × 1024 / サンプリング周波数 とは 1 フレームほどずれる (ffmpeg の AAC で実測。Zoom の録音は
    遅れ 0 で k × 1024 / 48000 と一致 = 実測)。遅れがあれば表示する。

確かめること (1 つでも外れたら exit 1、出力は残す):
    - 各 part のフレーム数が指定どおり / 合計が元のフレーム数と一致
    - 各 part の AAC のパケットが、元の同じ位置のパケットとバイト単位で同じ (パケットごとの MD5 で照合 = 無劣化で切れた証拠)
      ⚠️ デコードした音どうしの比較にしない: 雑音に近い帯域を「雑音で埋めよ」 と書く符号化 (PNS) では、デコーダが乱数で
      埋めるので、part だけをデコードすると同じパケットでも音が変わる (合成音で実測。Zoom の録音ではたまたま一致した)

使い方:
    python3 audio-split-by-frames.py SRC.m4a --cuts 23413,64704,98361 --out DIR --prefix 2026-08-31-part
        # → DIR/2026-08-31-part1.m4a 〜 part4.m4a (境目 = 指定したフレーム番号。0 と末尾は自動)
    python3 audio-split-by-frames.py SRC.m4a --cut-times 499.477,1380.352 --out DIR --prefix ep
        # 秒で渡すと一番近いパケットの境目に丸める (丸めた値を表示する)
    python3 audio-split-by-frames.py SRC.m4a --frames-of 1276.544     # 秒 → フレーム番号を表示するだけ
    python3 audio-split-by-frames.py --selftest                        # 合成音で、切れることと食い違いを見つけることを確かめる

既存の出力は --force なしでは上書きしない。part は edit list なしで書く (元の「先頭の遅れ」 の設定が引き継がれて、
再生時に各 part の頭が捨てられるのを防ぐ)。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FRAME = 1024          # AAC-LC の 1 フレームのサンプル数 (HE-AAC は対象外 = 検出して止める)


def probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-count_packets",
                        "-show_entries", "stream=codec_name,profile,sample_rate,channels,nb_read_packets",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    if s.get("codec_name") != "aac" or "HE" in (s.get("profile") or ""):
        raise SystemExit(f"❌ {path.name}: AAC-LC だけを扱う (codec {s.get('codec_name')} / {s.get('profile')})")
    return {"sr": int(s["sample_rate"]), "ch": int(s["channels"]), "frames": int(s["nb_read_packets"])}


def packets(path: Path) -> list[dict]:
    """音声パケットごとの時刻 (秒) と中身の MD5。先頭に符号化の遅れがあると最初のパケットの時刻が負になる。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts_time,data_hash",
                        "-show_data_hash", "MD5", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return [{"t": float(x["pts_time"]), "md5": x["data_hash"]} for x in json.loads(r.stdout)["packets"]]


def packet_hashes(path: Path) -> list[str]:
    return [x["md5"] for x in packets(path)]


def cut(src: Path, start: int, n: int, start_time: float, dst: Path) -> None:
    """start 番目のパケットから n 個を無劣化で写す。-ss には、そのパケットの実際の時刻を渡す (k × 1024 / sr ではない)。"""
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if start:
        cmd += ["-ss", f"{start_time:.6f}"]
    cmd += ["-i", str(src), "-frames:a", str(n), "-c", "copy", "-use_editlist", "0", str(dst)]
    subprocess.run(cmd, check=True)


def split(src: Path, cuts: list[int], out: Path, prefix: str, force: bool = False) -> dict:
    info = probe(src)
    total = info["frames"]
    bounds = [0] + sorted(set(cuts)) + [total]
    if bounds[1] <= 0 or bounds[-2] >= total:
        raise SystemExit(f"❌ 境目は 1〜{total - 1} フレームの間で指定する (元は {total} フレーム)")
    out.mkdir(parents=True, exist_ok=True)
    pk = packets(src)
    whole = [x["md5"] for x in pk]
    if len(whole) != total:
        raise SystemExit(f"❌ パケットの数 {len(whole)} がフレーム数 {total} と合わない")
    pad = round(-pk[0]["t"] * info["sr"]) if pk[0]["t"] < 0 else 0
    if pad:
        print(f"⚠️ {src.name}: 先頭に符号化の遅れ {pad} サンプル (最初のパケットの時刻 {pk[0]['t']} 秒) = "
              "フレーム番号と時刻がその分ずれる。切るときはパケットの実際の時刻を使う")
    parts, ok = [], True
    for k in range(len(bounds) - 1):
        start, n = bounds[k], bounds[k + 1] - bounds[k]
        dst = out / f"{prefix}{k + 1}{src.suffix}"
        if dst.exists() and not force:
            raise SystemExit(f"❌ {dst} がある (--force で上書き)")
        cut(src, start, n, pk[start]["t"], dst)
        got = probe(dst)["frames"]
        same = packet_hashes(dst) == whole[start:start + n]
        good = got == n and same
        ok &= good
        parts.append({"file": str(dst), "start_frame": start, "frames": got, "want_frames": n,
                      "start_s": round(pk[start]["t"], 6), "dur_s": round(n * FRAME / info["sr"], 3),
                      "packets_match_source": same})
        print(f"{'✅' if good else '❌'} {dst.name}: frames {got}/{n}, {pk[start]['t']:.3f}s から "
              f"{n * FRAME / info['sr']:.3f}s, パケットが元と同じ = {same}")
    s = sum(p["frames"] for p in parts)
    ok &= s == total
    print(f"{'✅' if s == total else '❌'} 合計 {s} フレーム (元 {total})")
    return {"ok": ok, "source": str(src), "total_frames": total, "sample_rate": info["sr"],
            "initial_padding": pad, "parts": parts}


def time_to_frame(t: float, pk: list[dict]) -> int:
    """秒 → 時刻が一番近いパケットの番号 (先頭の遅れも込み)。"""
    return min(range(len(pk)), key=lambda k: abs(pk[k]["t"] - t))


def selftest() -> int:
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src = d / "tone.m4a"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6:sample_rate=48000",
                        "-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:r=48000:a=0.05", "-filter_complex", "amix=inputs=2",
                        "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(src)], check=True)
        info = probe(src)
        pk = packets(src)
        cuts = [time_to_frame(1.9, pk), time_to_frame(4.2, pk)]
        r = split(src, cuts, d / "out", "p")
        assert r["ok"] and len(r["parts"]) == 3, r
        assert sum(p["frames"] for p in r["parts"]) == info["frames"]
        # ffmpeg の AAC は先頭に遅れを入れる = 知らせる (切ること自体はできる)
        assert r["initial_padding"] > 0, r
        # 食い違いを見つけるか: 1 フレームずらして切った part は元の同じ位置のパケットと一致しない
        bad = d / "shifted.m4a"
        cut(src, cuts[0] + 1, cuts[1] - cuts[0], pk[cuts[0] + 1]["t"], bad)
        assert packet_hashes(bad) != packet_hashes(src)[cuts[0]:cuts[1]], "1 フレームのずれを見逃した"
        # 範囲外の境目を止める
        try:
            split(src, [0], d / "out2", "q")
            raise AssertionError("境目 0 を通した")
        except SystemExit:
            pass
        # 遅れの無い音声 (edit list なしで書いた場合) でも切れる
        flat = d / "flat.m4a"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-c", "copy", "-use_editlist", "0", str(flat)], check=True)
        r2 = split(flat, cuts, d / "out3", "f")
        assert r2["ok"], r2
    print("✅ selftest PASS (フレーム数で切れてパケットが元と同じ / 先頭の遅れを知らせる / 1 フレームのずれを見つける / "
          "範囲外の境目を止める)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", nargs="?", type=Path)
    ap.add_argument("--cuts", help="境目のフレーム番号 (カンマ区切り)")
    ap.add_argument("--cut-times", help="境目の秒 (カンマ区切り、時刻が一番近いパケットに丸める)")
    ap.add_argument("--frames-of", type=float, help="秒 → フレーム番号を表示するだけ")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--prefix", default="part")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true", help="結果を JSON でも出す")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.src:
        ap.error("SRC が要る")
    info = probe(a.src)
    pk = packets(a.src)
    if a.frames_of is not None:
        f = time_to_frame(a.frames_of, pk)
        print(f"{a.frames_of} 秒 → frame {f} (= パケットの時刻 {pk[f]['t']:.6f} 秒)。元は {info['frames']} フレーム")
        return 0
    if a.cuts:
        cuts = [int(x) for x in a.cuts.split(",")]
    elif a.cut_times:
        cuts = [time_to_frame(float(x), pk) for x in a.cut_times.split(",")]
        print("丸めた境目:", ", ".join(f"frame {c} = {pk[c]['t']:.6f} 秒" for c in cuts))
    else:
        ap.error("--cuts か --cut-times が要る")
    if not a.out:
        ap.error("--out が要る")
    r = split(a.src, cuts, a.out, a.prefix, a.force)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
