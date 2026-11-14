#!/usr/bin/env python3
"""audio-speaker-levels.py — 話者つきの文字起こし (WebVTT の cue の本文が「名前: 本文」) と録音から、 話者ごとの声の大きさを測る。

なぜ: 片方のマイクの入力が大きすぎた・小さすぎた録音を、 仕上げる前に見つけるため (収録の後に毎回回す)。
測り方: 片方の話者の cue だけがかかる時間の 10 ms 窓のうち、 閾値 (既定 -50 dBFS) より上のものをその人の声とし、
窓の dB の中央値と power 平均 (聞こえの大きさに近い) を話者ごとに出す。 区間 (配信の 1 回分など) ごとにも出す。
cue ごとの値の中央値は使わない = 相づちの短い cue が多い人ほど小さく出た (実測)。 power 平均は、 相手の時間に混じった
相づち (cue にならない声) で小さい方が大きめに出る = 差が大きい録音では中央値の差も見る。
規則と、 差が大きいときの揃え方の正本 = conventions/podcast-audio-finishing.md#balance-speakers。

使い方:
    python3 audio-speaker-levels.py <録音> <vtt> --offset <秒> [--parts <区間の file> ...] [--threshold -50] [--json]
    python3 audio-speaker-levels.py <録音> <vtt> --rec-txt <rec.txt> ...   # offset を自動で決める
    python3 audio-speaker-levels.py --selftest

    --offset  = 録音の時刻 − VTT の時刻 (秒)。 VTT は会議の開始から数え、 録画は途中から始まることが多い
    --rec-txt = 録音の時刻に直した文字起こし (1 行目が「[h:mm:ss] 名前: 本文」、 zoom-client.py notes --rec-start の出力) =
                1 行目と、 本文の頭が同じ VTT の最初の cue との時刻の差を offset にする
    --parts   = 録音を切った区間の file を順に渡す (長さを足して区間の境を決める)。 省くと録音の全体を 1 区間
    話者の名前は VTT の cue の「:」 の前をそのまま使う (同じ人が 2 つのアカウントで入ると 2 人に分かれる)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HOP = 0.01   # 10 ms


def t2s(s: str) -> float:
    neg = s.startswith("-")
    h, m, x = s.lstrip("-").split(":")
    v = int(h) * 3600 + int(m) * 60 + float(x)
    return -v if neg else v


def parse_vtt(text: str) -> list[tuple[float, float, str, str]]:
    out = []
    for a, b, sp, tx in re.findall(r"(\d+:\d\d:\d\d\.\d+) --> (\d+:\d\d:\d\d\.\d+)\n([^:\n]+): (.*)", text):
        out.append((t2s(a), t2s(b), sp.strip(), tx))
    return out


def offset_from_rec(rec_first_line: str, cues) -> float:
    m = re.match(r"\[(-?\d+:\d\d:\d\d)\] ([^:]+): (.*)", rec_first_line)
    if not m:
        raise SystemExit("rec.txt の 1 行目が「[h:mm:ss] 名前: 本文」 でない")
    t_rec, text = t2s(m.group(1)), m.group(3)
    for a, _b, sp, tx in cues:
        if sp == m.group(2).strip() and text.startswith(tx[:6]):
            return t_rec - a
    raise SystemExit("rec.txt の 1 行目と本文の頭が同じ cue が VTT に無い")


def frames_db(path: str) -> "list[float]":
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype=np.float32)
    n = len(y) // 160
    return 10 * np.log10((y[: n * 160].reshape(n, 160).astype(np.float64) ** 2).mean(axis=1) + 1e-12)


def duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def measure(db, cues, offset: float, edges: list[float], threshold: float = -50.0) -> list[dict]:
    """db = 10 ms ごとの dB (録音の時刻)、 cues = (VTT の頭, 尾, 話者, 本文)、 edges = 区間の境 (秒、 頭 0 と尾を含む)。"""
    import numpy as np
    db = np.asarray(db)
    n = len(db)
    speakers = sorted({c[2] for c in cues})
    cover = {sp: np.zeros(n, bool) for sp in speakers}
    for a, b, sp, _ in cues:
        i, j = max(int((a + offset) / HOP), 0), min(int((b + offset) / HOP), n)
        if j > i:
            cover[sp][i:j] = True
    count = sum(c.astype(int) for c in cover.values()) if cover else np.zeros(n, int)
    act = db > threshold
    rows = []
    for k in range(len(edges) - 1):
        a, b = int(edges[k] / HOP), min(int(edges[k + 1] / HOP), n)
        seg = {"part": k + 1, "start_s": round(edges[k], 3), "end_s": round(edges[k + 1], 3), "speakers": {}}
        for sp in speakers:
            m = (cover[sp] & (count == 1) & act)[a:b]
            if m.sum() < 100:   # 1 秒に満たない
                continue
            v = db[a:b][m]
            seg["speakers"][sp] = {"median_db": round(float(np.median(v)), 1),
                                   "power_db": round(float(10 * np.log10(np.mean(10 ** (v / 10)))), 1),
                                   "minutes": round(float(m.sum() * HOP / 60), 1)}
        sv = seg["speakers"]
        if len(sv) >= 2:
            med = sorted(x["median_db"] for x in sv.values())
            pw = sorted(x["power_db"] for x in sv.values())
            seg["gap_median_db"] = round(med[-1] - med[0], 1)
            seg["gap_power_db"] = round(pw[-1] - pw[0], 1)
        rows.append(seg)
    return rows


def selftest() -> int:
    import numpy as np
    fails = []
    n = 6000   # 60 秒
    db = np.full(n, -80.0)
    cues = []
    t = 0.0
    while t < 58:   # 3 秒ずつ交互、 A は -15、 B は -30 (B の時間に A の短い相づちを 1 回混ぜる)
        sp, lvl = ("A", -15.0) if int(t / 3) % 2 == 0 else ("B", -30.0)
        db[int(t * 100): int((t + 2.5) * 100)] = lvl
        cues.append((t + 10, t + 2.5 + 10, sp, "x"))   # VTT は 10 秒先から数える
        t += 3
    db[int(4.0 * 100): int(4.2 * 100)] = -15.0   # B の時間に A の相づち (cue にならない)
    rows = measure(db, cues, -10.0, [0.0, 30.0, 60.0])
    if len(rows) != 2:
        fails.append(f"区間の数 {len(rows)}")
    s = rows[0]["speakers"]
    if not (abs(s["A"]["median_db"] + 15) < 0.1 and abs(s["B"]["median_db"] + 30) < 0.1):
        fails.append(f"中央値 {s}")
    if not abs(rows[0]["gap_median_db"] - 15) < 0.1:
        fails.append(f"中央値の差 {rows[0].get('gap_median_db')}")
    if not rows[0]["gap_power_db"] < 15:
        fails.append("相づちで power 平均の差が縮むはず")
    cues2 = parse_vtt("WEBVTT\n\n00:00:12.000 --> 00:00:14.000\nA: こんにちは。\n\n00:00:15.000 --> 00:00:16.000\nB: はい。\n")
    if len(cues2) != 2 or cues2[0][2] != "A":
        fails.append(f"VTT の読み {cues2}")
    if abs(offset_from_rec("[0:00:02] A: こんにちは。 さて。", cues2) + 10.0) > 1e-9:
        fails.append("rec.txt からの offset")
    for f in fails:
        print("FAIL:", f)
    print("audio-speaker-levels selftest:", "ALL PASS (区間ごとの中央値・相づちの混じり・VTT の読み・offset)" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("audio", nargs="?")
    ap.add_argument("vtt", nargs="?")
    ap.add_argument("--offset", type=float)
    ap.add_argument("--rec-txt")
    ap.add_argument("--parts", nargs="*", default=[])
    ap.add_argument("--threshold", type=float, default=-50.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.audio or not a.vtt:
        ap.error("録音と vtt が要る")
    cues = parse_vtt(Path(a.vtt).read_text(encoding="utf-8"))
    if a.offset is None:
        if not a.rec_txt:
            ap.error("--offset か --rec-txt が要る")
        a.offset = offset_from_rec(Path(a.rec_txt).read_text(encoding="utf-8").splitlines()[0], cues)
    db = frames_db(a.audio)
    total = len(db) * HOP
    edges = [0.0]
    for p in a.parts:
        edges.append(edges[-1] + duration(p))
    edges = edges[:-1] + [total] if a.parts else [0.0, total]
    rows = measure(db, cues, a.offset, edges, a.threshold)
    if a.json:
        print(json.dumps({"offset_s": a.offset, "parts": rows}, ensure_ascii=False, indent=1))
        return 0
    print(f"offset = {a.offset:+.0f} 秒 (録音の時刻 − VTT の時刻)")
    for r in rows:
        sp = "、 ".join(f"{k} 中央値 {v['median_db']} / 平均 {v['power_db']} dB ({v['minutes']} 分)" for k, v in r["speakers"].items())
        gap = f" → 差 = 中央値 {r['gap_median_db']} / 平均 {r['gap_power_db']} dB" if "gap_median_db" in r else ""
        print(f"  区間 {r['part']} ({r['start_s']:.0f}〜{r['end_s']:.0f} 秒): {sp}{gap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
