#!/usr/bin/env python3
"""compaction-report.py — 会話記録 (Claude Code の transcript) から自動圧縮の記録を並べ、 圧縮が会話の動いている途中で起きたか、
しばらく止まった後に起きたかを見分ける (「圧縮がやたら多い」「窓の設定が 1M から変わったのでは」 の切り分け)。

使い方:
  python3 scripts/compaction-report.py [--days 4] [--session <id の先頭>] [--projects <dir> ...]
  python3 scripts/compaction-report.py --selftest

出力 = 1 行 1 圧縮: 時刻 (UTC)・session の id 8 字・trigger・圧縮前の token 数・precomputed・直前の応答からの空き (分)・区分。
区分:
  止まった後 = 直前の応答から 60 分以上空いている。 Claude Code は長い会話がしばらく止まると、 戻る前に会話を要約へ差し替える
               (設定 `idleCompaction`、 既定 on、 settings.json に false を書くと切れる。 true を書いても on にはならない)。
               このときの圧縮前の token は窓の上限よりずっと小さくてよい
  動いている途中 = 空きが 60 分未満。 窓の上限に近づいて起きた圧縮なら、 圧縮前の token は窓の上限の近く (1M なら 90 万台)
読み方の注意:
  - 区分は空きの長さで付けるだけで、 圧縮の理由を記録から読んだものではない (記録に理由の欄は無い)。 窓の大きさは記録から分からないので、
    圧縮前の token と自分の窓 (1M か 200K か) を並べて読む
  - 止まった後の圧縮を切ると、 休憩の後に長い会話を再開するたびに保存された途中の読み込みが切れていて会話を全部読み直す = 使用量が増える
  - 圧縮した会話記録 (`.jsonl.zst` など) は読まない (数えた file と飛ばした file の数を最後に出す)
既定の探し場所 = ~/.claude/projects と、 実体のある ~/.claude-*/projects (symlink は実体で 1 つに)。 標準 library だけ。
正本の説明 = docs/usage-tips.ja.md#idle-compaction (英語 = docs/usage-tips.md#idle-compaction)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
import tempfile
import time

IDLE_MINUTES = 60


def _parse(ts: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def default_projects() -> list[str]:
    home = os.path.expanduser("~")
    out, seen = [], set()
    for d in [os.path.join(home, ".claude", "projects")] + sorted(glob.glob(os.path.join(home, ".claude-*", "projects"))):
        if os.path.isdir(d):
            rp = os.path.realpath(d)
            if rp not in seen:
                seen.add(rp)
                out.append(d)
    return out


def scan_file(path: str) -> list[dict]:
    rows, last_reply = [], None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"compact_boundary"' not in line and '"assistant"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            ts = _parse(e.get("timestamp") or "")
            if e.get("type") == "assistant" and ts:
                last_reply = ts
            elif e.get("type") == "system" and e.get("subtype") == "compact_boundary":
                md = e.get("compactMetadata") or {}
                gap = (ts - last_reply).total_seconds() / 60 if ts and last_reply else None
                rows.append({"at": ts, "session": os.path.basename(path)[:8], "trigger": md.get("trigger"),
                             "pre": md.get("preTokens"), "precomputed": md.get("precomputed"), "gap": gap})
    return rows


def collect(projects: list[str], days: float, session: str = "") -> tuple[list[dict], int, int]:
    rows, read, skipped = [], 0, 0
    cutoff = time.time() - days * 86400
    for d in projects:
        for p in glob.glob(os.path.join(d, "*", "*")):
            if os.path.getmtime(p) < cutoff:
                continue
            name = os.path.basename(p)
            if session and not name.startswith(session):
                continue
            if name.endswith(".jsonl"):
                read += 1
                rows.extend(scan_file(p))
            elif ".jsonl." in name:
                skipped += 1
    rows.sort(key=lambda r: r["at"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
    return rows, read, skipped


def render(rows: list[dict], read: int, skipped: int) -> str:
    out = []
    for r in rows:
        gap = "?" if r["gap"] is None else f"{r['gap']:.0f}"
        kind = "?" if r["gap"] is None else ("止まった後" if r["gap"] >= IDLE_MINUTES else "動いている途中")
        at = r["at"].strftime("%Y-%m-%d %H:%M") if r["at"] else "?"
        out.append(f"{at}Z  {r['session']}  {r['trigger'] or '?':6}  圧縮前 {r['pre'] if r['pre'] is not None else '?':>9}  "
                   f"precomputed={r['precomputed']}  空き {gap:>5} 分  {kind}")
    idle = sum(1 for r in rows if r["gap"] is not None and r["gap"] >= IDLE_MINUTES)
    out.append(f"圧縮 {len(rows)} 件 (止まった後 {idle} 件)、 読んだ記録 {read} file、 圧縮した記録で読まなかったもの {skipped} file")
    return "\n".join(out)


def selftest() -> int:
    fails = []

    def ok(label: str, cond: bool) -> None:
        print(("ok: " if cond else "NG: ") + label)
        if not cond:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        proj = os.path.join(td, "projects", "-w")
        os.makedirs(proj)
        rows = [
            {"type": "assistant", "timestamp": "2099-01-01T00:00:00Z", "message": {"content": []}},
            {"type": "system", "subtype": "compact_boundary", "timestamp": "2099-01-01T01:30:00Z",
             "compactMetadata": {"trigger": "auto", "preTokens": 300000, "precomputed": True}},
            {"type": "assistant", "timestamp": "2099-01-01T02:00:00Z", "message": {"content": []}},
            {"type": "system", "subtype": "compact_boundary", "timestamp": "2099-01-01T02:01:00Z",
             "compactMetadata": {"trigger": "auto", "preTokens": 950000}},
        ]
        with open(os.path.join(proj, "aaaabbbb-0000.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
        with open(os.path.join(proj, "ccccdddd-0000.jsonl.zst"), "wb") as fh:
            fh.write(b"\x28\xb5\x2f\xfd")
        got, read, skipped = collect([os.path.join(td, "projects")], days=1)
        ok("2 compactions found", len(got) == 2)
        ok("the first comes after a 90-minute gap", got and round(got[0]["gap"]) == 90)
        text = render(got, read, skipped)
        ok("the idle one is labelled 止まった後", "空き    90 分  止まった後" in text)
        ok("the busy one is labelled 動いている途中", "空き     1 分  動いている途中" in text)
        ok("a compressed record is counted as skipped", read == 1 and skipped == 1)
        ok("--session narrows to one record", len(collect([os.path.join(td, "projects")], 1, "cccc")[0]) == 0)
    print("selftest:", "PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--days", type=float, default=4)
    ap.add_argument("--session", default="")
    ap.add_argument("--projects", nargs="*")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    rows, read, skipped = collect(a.projects or default_projects(), a.days, a.session)
    print(render(rows, read, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
