#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""散文に書いた期間 (N ヶ月 / N 週 / N 日 / N months …) が、 同じ段落に並べた日付の範囲 (YYYY-MM-DD → YYYY-MM-DD) の実際の差と桁で食い違う箇所を候補として出す (書いた時点の計算違いと、 その写しを拾う on-demand の走査)。--selftest 内蔵。

一般則 = [`docs/convention-design-principles.md#derived-value-beside-inputs`](../docs/convention-design-principles.md#derived-value-beside-inputs)。

使い方:

    python3 check-duration-beside-dates.py ~/repo-a ~/repo-b        # 各 git repo の追跡 file
    python3 check-duration-beside-dates.py --files notes.md DESIGN.md
    python3 check-duration-beside-dates.py --selftest

- 対象 = 追跡 file のうち .md / .py / .yaml / .yml / .txt。 段落 (空行区切り) の中で、 日付の範囲から
  120 文字以内にある期間語を範囲の日数と比べ、 比が 0.5〜2 の外なら出す (桁の食い違いだけを見る)。
- **拾うのは「期間語と日付の範囲が同じ段落に在る」 形だけ**。 日付 1 つに「N ヶ月後」 を付けた形は、
  差を計算する入力が無いので圏外。
- 相対の offset (「N 日前」「今日 −N 日」) も期間語として拾うので誤検出がある。 候補を文脈で判断する
  sweep の道具で、 CI の gate にはしない。
- 陽性対照 (2026-09-14): 「13 ヶ月」 と 35 日の範囲を並べていた 2 file の、 直す前の版で 2 組とも拾う。

exit: 0 = 候補なし / 1 = 候補あり / 2 = 入力の誤り。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

EXTS = (".md", ".py", ".yaml", ".yml", ".txt")
DATE = r"(20\d\d)-(\d\d)-(\d\d)"
RANGE = re.compile(DATE + r"\s*(?:→|->|〜|~|–|から|to)\s*" + DATE)
DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(ヶ月|か月|カ月|箇月|months?|週間|週|weeks?|日間|日|days?)")
DAYS_PER = {"ヶ月": 30.44, "か月": 30.44, "カ月": 30.44, "箇月": 30.44, "month": 30.44, "months": 30.44,
            "週": 7, "週間": 7, "week": 7, "weeks": 7, "日": 1, "日間": 1, "day": 1, "days": 1}
WINDOW = 120
PARA_BREAK = re.compile(r"\n[ \t]*\n")


def paragraph_bounds(text: str, pos: int) -> tuple[int, int]:
    start = 0
    for m in PARA_BREAK.finditer(text, 0, pos):
        start = m.end()
    m = PARA_BREAK.search(text, pos)
    return start, (m.start() if m else len(text))


def scan_text(text: str) -> list[dict]:
    hits = []
    for r in RANGE.finditer(text):
        y1, m1, d1, y2, m2, d2 = map(int, r.groups())
        try:
            days = (date(y2, m2, d2) - date(y1, m1, d1)).days
        except ValueError:
            continue
        if days <= 0:
            continue
        lo, hi = paragraph_bounds(text, r.start())
        for d in DURATION.finditer(text, lo, hi):
            if abs(d.start() - r.start()) > WINDOW:
                continue
            claimed = float(d.group(1)) * DAYS_PER[d.group(2)]
            if 0.5 <= claimed / days <= 2.0:
                continue
            a, b = min(r.start(), d.start()), max(r.end(), d.end())
            hits.append({"line": text.count("\n", 0, r.start()) + 1, "range": r.group(0), "days": days,
                         "duration": d.group(0), "claimed_days": round(claimed),
                         "context": text[max(lo, a - 30): min(hi, b + 30)].replace("\n", " ")})
    return hits


def tracked_files(repo: Path) -> list[Path]:
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    if r.returncode != 0:
        raise ValueError(f"{repo}: not a git repository")
    names = [n for n in r.stdout.decode("utf-8", "surrogateescape").split("\0") if n.endswith(EXTS)]
    return [repo / n for n in names]


def scan_paths(paths: list[Path], label_root: Path | None = None, out=print) -> int:
    count = 0
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for h in scan_text(text):
            count += 1
            name = p.relative_to(label_root) if label_root else p
            out(f"{name}:{h['line']}: {h['range']} = {h['days']} days, but '{h['duration']}' ≈ {h['claimed_days']} days"
                f"  | {h['context'][:200]}")
    return count


def selftest() -> int:
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    wrong = "実例 (2026-04-20 → 2026-05-25 の 13 ヶ月遅延発見): 前の修正から見つかるまで。"
    expect("a duration off by an order of magnitude from its own range is reported  [positive control]",
           len(scan_text(wrong)) == 1 and scan_text(wrong)[0]["days"] == 35)
    expect("a consistent approximate duration is not reported", scan_text("約 5 週 (2026-04-20 → 2026-05-25)。") == [])
    expect("English words and 'to' work both ways",
           scan_text("from 2025-01-01 to 2025-03-01, i.e. 2 months.") == []
           and len(scan_text("from 2025-01-01 to 2025-03-01, i.e. 2 weeks.")) == 1)
    expect("a duration in another paragraph is not paired with the range",
           scan_text("2026-04-20 → 2026-05-25 の間。\n\n別の話で 13 ヶ月。") == [])
    expect("a duration farther than the window in the same paragraph is not paired",
           scan_text("2026-04-20 → 2026-05-25。" + "あ" * (WINDOW + 5) + " 13 ヶ月。") == [])
    expect("an impossible date is skipped without crashing", scan_text("2026-02-30 → 2026-05-25 の 13 ヶ月") == [])
    expect("a window whose offsets are swapped against its example dates is reported",
           len(scan_text("窓 = 起点の 7 日前 〜 30 日後。 例: 2026-04-30 〜 2026-06-06 の間だけ出る。")) >= 1)
    expect("the line number points at the range", scan_text("a\nb\n2026-04-20 → 2026-05-25 の 13 ヶ月")[0]["line"] == 3)

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        (repo / "tracked.md").write_text(wrong + "\n", encoding="utf-8")
        (repo / "untracked.md").write_text(wrong + "\n", encoding="utf-8")
        (repo / "clean.md").write_text("約 5 週 (2026-04-20 → 2026-05-25)。\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "tracked.md", "clean.md"], check=True)
        log: list[str] = []
        n = scan_paths(tracked_files(repo), repo, out=log.append)
        expect("repo mode reads tracked files only", n == 1 and log[0].startswith("tracked.md:1:"))
        me = str(Path(__file__).resolve())
        r = subprocess.run([sys.executable, me, str(repo)], capture_output=True, text=True)
        expect("CLI exits 1 when there is a candidate", r.returncode == 1 and "13 ヶ月" in r.stdout)
        r = subprocess.run([sys.executable, me, "--files", str(repo / "clean.md")], capture_output=True, text=True)
        expect("CLI exits 0 when there is none", r.returncode == 0)
        r = subprocess.run([sys.executable, me, str(Path(td) / "not-a-repo")], capture_output=True, text=True)
        expect("a path that is not a git repository is an input error (exit 2)", r.returncode == 2)
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repos", nargs="*", type=Path, help="git repositories (tracked files are scanned)")
    ap.add_argument("--files", nargs="+", type=Path, default=[], help="scan these files instead")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.repos and not a.files:
        ap.error("give git repositories or --files")
    total = 0
    try:
        for repo in a.repos:
            total += scan_paths(tracked_files(repo), repo)
    except ValueError as e:
        print(f"[input] {e}")
        return 2
    total += scan_paths(a.files)
    print(f"{total} candidate(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
