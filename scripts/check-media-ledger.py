#!/usr/bin/env python3
"""画像 stream の読取記録 (transcript ledger) に、 読んでいない画像が残っていないかを見る detector。

一般則の正本 = conventions/media-transcription-ledger.md (4 点セットの「3. 未読 detector」 と #per-item-not-per-bucket)。
画像の来る所 (chat の channel を fetch した JSON) と、 読んだ内容を書く所 (日付の節を持つ Markdown の dir) を引数で受け取る
engine。 どの channel・どの dir かは呼び出し側 (個人層の shim) が渡す。

判定:
  - source = `--source-json` の message 配列。 各 message の `timestamp` (ISO 8601、 先頭 10 字を日付とみなす = 時差の換算はしない)
    と `attachments[].filename` (画像の拡張子だけ数える) を読む。 `--since` より前の日付は見ない
  - ledger = `--ledger-dir` の *.md。 `## YYYY-MM-DD` の見出しが「その日を読んだ」 印
  - 画像のある日 ∧ 節なし → 未読。 猶予 (`--grace`、 既定 7 日) を過ぎたら 🔴、 以内は 🟡
  - **同じ日に画像が 2 枚以上ある日は、 1 枚ずつ file 名が ledger のどこかに出ていること** (拡張子を省いた記録も一致とみなす)。
    節はあっても名前の出ない画像 = 2 枚目以降を読んでいない疑い = 同じ 🔴 / 🟡。 1 枚だけの日は節の有無で見る
  - finding 0 件なら何も出さない (exit 0)。 source が無い・読めない (未 clone / 暗号化のまま / 壊れた JSON) は fail-open で沈黙

使い方:
    check-media-ledger.py --source-json <messages.json> --ledger-dir <dir> [--since YYYY-MM-DD] [--grace 7]
                          [--title "<見出し>"] [--today YYYY-MM-DD]
    check-media-ledger.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

IMAGE_RE = re.compile(r"\.(jpe?g|png|heic|webp)$", re.I)
SECTION_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})", re.M)


def find_findings(source_json: Path, ledger_dir: Path, today: date, since: str = "0000-00-00", grace: int = 7):
    """[(sev, date, age_days, unnamed)] を返す。 unnamed = None (節なし) / [file 名] (複数枚の日で名前の出ない画像)。
    source が無い・読めない時は None (fail-open)。"""
    if not source_json.exists():
        return None
    try:
        msgs = json.loads(source_json.read_text())
    except Exception:
        return None
    if isinstance(msgs, dict):
        msgs = msgs.get("messages", [])
    photos: dict[str, set[str]] = {}
    for m in msgs:
        if not (isinstance(m, dict) and m.get("attachments") and str(m.get("timestamp", "")) >= since):
            continue
        d = str(m["timestamp"])[:10]
        names = photos.setdefault(d, set())
        for a in m["attachments"]:
            fn = a.get("filename", "") if isinstance(a, dict) else ""
            if IMAGE_RE.search(fn):
                names.add(fn)
    if not photos:
        return []
    text = ""
    if ledger_dir.is_dir():
        for md in sorted(ledger_dir.glob("*.md")):
            try:
                text += md.read_text()
            except Exception:
                continue
    sections = set(SECTION_RE.findall(text))
    out = []
    for d in sorted(photos):
        age = (today - date.fromisoformat(d)).days
        sev = "🔴" if age > grace else "🟡"
        if d not in sections:
            out.append((sev, d, age, None))
            continue
        names = photos[d]
        if len(names) > 1:
            unnamed = sorted(fn for fn in names if fn not in text and Path(fn).stem not in text)
            if unnamed:
                out.append((sev, d, age, unnamed))
    return out


def render(findings, title: str) -> list[str]:
    lines = ["", f"📋 {title}"]
    for sev, d, age, unnamed in findings:
        if unnamed is None:
            lines.append(f"  {sev} {d} の画像が未読 ({age} 日経過)。 読む → ledger に日付の節と file 名を書く → 転記先に反映")
        else:
            lines.append(f"  {sev} {d} は画像が複数枚で、 {', '.join(unnamed)} が ledger に名前で出てこない ({age} 日経過)。 "
                         f"その画像を開いて読み、 節に file 名つきで追記 (読んだ上で同じものの撮り直しなら、 そう 1 行)")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source-json")
    ap.add_argument("--ledger-dir")
    ap.add_argument("--since", default="0000-00-00")
    ap.add_argument("--grace", type=int, default=7)
    ap.add_argument("--title", default="画像の読取記録に未読がある")
    ap.add_argument("--today")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.source_json and a.ledger_dir):
        ap.error("--source-json と --ledger-dir が要る")
    today = date.fromisoformat(a.today) if a.today else date.today()
    f = find_findings(Path(a.source_json), Path(a.ledger_dir), today, a.since, a.grace)
    if f:
        print("\n".join(render(f, a.title)))
    return 0


def selftest() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "msgs.json"
        led = root / "ledger"
        led.mkdir()
        msgs = [
            {"timestamp": "2026-01-15T04:00:00+00:00", "attachments": [{"filename": "a.jpg"}]},   # --since より前 = 見ない
            {"timestamp": "2026-07-09T04:09:00+00:00", "attachments": [{"filename": "b.jpg"}]},   # 節あり
            {"timestamp": "2026-07-13T04:00:00+00:00", "attachments": [{"filename": "c.jpg"}]},   # 未読・8 日 = 🔴
            {"timestamp": "2026-07-19T04:00:00+00:00", "attachments": [{"filename": "d.jpg"}]},   # 未読・2 日 = 🟡
            {"timestamp": "2026-07-20T04:00:00+00:00", "content": "text only"},                   # 添付なし = 見ない
        ]
        src.write_text(json.dumps(msgs))
        (led / "2026.md").write_text("# t\n\n## 2026-07-09\n\n- 読了\n")
        today = date(2026, 7, 21)
        f = find_findings(src, led, today, since="2026-04-01")
        assert f is not None
        assert [(s, d) for s, d, _, _ in f] == [("🔴", "2026-07-13"), ("🟡", "2026-07-19")], f
        (led / "2026.md").write_text("# t\n\n## 2026-07-09\n\n## 2026-07-13\n\n## 2026-07-19\n")
        assert find_findings(src, led, today, since="2026-04-01") == []
        # 同じ日に 2 枚: 名前が出ていなければ出す / 拡張子なしの記録でも消える
        src.write_text(json.dumps(msgs + [{"timestamp": "2026-07-09T04:20:00+00:00", "attachments": [{"filename": "b2.jpg"}]}]))
        f2 = find_findings(src, led, today, since="2026-04-01")
        assert [(s, d, u) for s, d, _, u in f2] == [("🔴", "2026-07-09", ["b.jpg", "b2.jpg"])], f2
        (led / "2026.md").write_text("# t\n\n## 2026-07-09\n\n(b + b2)\n\n## 2026-07-13\n\n## 2026-07-19\n")
        assert find_findings(src, led, today, since="2026-04-01") == []
        # {"messages": [...]} 形の JSON も読む
        src.write_text(json.dumps({"messages": msgs}))
        assert find_findings(src, led, today, since="2026-04-01") == []
        # source が無い / 壊れている = fail-open (None)
        src.write_text("{broken")
        assert find_findings(src, led, today) is None
        src.unlink()
        assert find_findings(src, led, today) is None
    print("check-media-ledger selftest: ALL PASS (5 blocks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
