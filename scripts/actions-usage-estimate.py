#!/usr/bin/env python3
"""actions-usage-estimate.py — GitHub Actions の月の使用量を、 課金 API を使わずに run の履歴から workflow ごとに見積もる (private repo の無料枠の棚卸し用)。

使用量の API (`/users/<u>/settings/billing/usage`) は token に `user` scope が要り、 普段の `gh` の認証では読めない
(= conventions/github-security-automation.md#private-actions-minutes)。 代わりに各 repo の run の履歴
(`repos/<owner>/<repo>/actions/runs?created=>=<日付>`) を集め、 run ごとに (updated_at − run_started_at) を分に切り上げて
workflow ごとに足す。 出力 = 分の多い順に「分 / 回数 / repo / workflow / event の内訳」。

限界 (= 請求額そのものではない):
  - 課金は job 単位の切り上げ・OS ごとの倍率。 ここは run 単位の壁時計の切り上げなので、 並列 job の多い workflow は少なめに、
    待ち時間の長い run は多めに出る
  - job が runner に載らなかった run (枠切れ・支払いの失敗) も数十秒の run として数える (請求はされない)
  - 対象は `--visibility` の repo だけ (public repo は無料 = 既定で数えない)

使い方:
  actions-usage-estimate.py                      # 自分の private repo、 今月 1 日から
  actions-usage-estimate.py --since 2026-09-16   # ある日からだけ (止めた後に漏れが無いかを見る)
  actions-usage-estimate.py --owner <org> --visibility all --top 50
  actions-usage-estimate.py --selftest
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime


def _gh(args: list[str]):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def run_minutes(run: dict) -> int:
    st, up = run.get("run_started_at"), run.get("updated_at")
    if not st or not up:
        return 0
    sec = max(0.0, (_ts(up) - _ts(st)).total_seconds())
    return math.ceil(sec / 60) if sec > 0 else 0


def aggregate(rows: list[tuple[str, dict]]) -> list[tuple[str, str, int, int, dict]]:
    """rows = [(repo, run)] → [(repo, workflow, 分, 回数, {event: 回数})] を分の多い順に。"""
    agg: dict[tuple[str, str], list] = defaultdict(lambda: [0, 0, defaultdict(int)])
    for repo, run in rows:
        a = agg[(repo, run.get("name") or run.get("path") or "?")]
        a[0] += run_minutes(run)
        a[1] += 1
        a[2][run.get("event") or "?"] += 1
    out = [(r, w, m, n, dict(ev)) for (r, w), (m, n, ev) in agg.items()]
    return sorted(out, key=lambda x: (-x[2], -x[3], x[0], x[1]))


def collect(owner: str, visibility: str, since: str) -> tuple[list[str], list[tuple[str, dict]]]:
    args = ["repo", "list", owner, "--limit", "500", "--json", "name"]
    if visibility != "all":
        args += ["--visibility", visibility]
    repos = [r["name"] for r in (_gh(args) or [])]
    rows = []
    for name in repos:
        page = 1
        while True:
            d = _gh(["api", f"repos/{owner}/{name}/actions/runs?created=>={since}&per_page=100&page={page}"])
            runs = (d or {}).get("workflow_runs", [])
            rows += [(name, x) for x in runs]
            if len(runs) < 100:
                break
            page += 1
    return repos, rows


def selftest() -> None:
    mk = lambda name, ev, st, up: {"name": name, "event": ev, "run_started_at": st, "updated_at": up}
    rows = [
        ("r1", mk("scan", "push", "2026-01-01T00:00:00Z", "2026-01-01T00:01:30Z")),   # 90 s → 2 分
        ("r1", mk("scan", "push", "2026-01-01T01:00:00Z", "2026-01-01T01:00:10Z")),   # 10 s → 1 分
        ("r1", mk("scan", "schedule", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z")),  # 0 s → 0 分
        ("r2", mk("fetch", "schedule", "2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")),  # 5 分
        ("r2", {"name": "broken", "event": "push"}),                                   # 時刻なし → 0 分
    ]
    got = aggregate(rows)
    assert got[0][:4] == ("r2", "fetch", 5, 1), got
    assert got[1][:4] == ("r1", "scan", 3, 3) and got[1][4] == {"push": 2, "schedule": 1}, got
    assert got[2][:4] == ("r2", "broken", 0, 1), got
    print("selftest: 3/3 PASS")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--owner", help="既定 = gh の認証 user")
    ap.add_argument("--since", help="YYYY-MM-DD (既定 = 今月 1 日)")
    ap.add_argument("--visibility", default="private", choices=["private", "public", "all"])
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    owner = a.owner or ((_gh(["api", "user"]) or {}).get("login"))
    if not owner:
        sys.exit("gh の認証 user が取れない (--owner で渡す)")
    since = a.since or date.today().replace(day=1).isoformat()
    repos, rows = collect(owner, a.visibility, since)
    agg = aggregate(rows)
    total = sum(x[2] for x in agg)
    print(f"{a.visibility} repo {len(repos)} 件 / run {len(rows)} 回 / {since} から / 概算 {total} 分 (run 単位の切り上げ)")
    for repo, wf, m, n, ev in agg[: a.top]:
        evs = ",".join(f"{k}:{v}" for k, v in sorted(ev.items(), key=lambda kv: -kv[1]))
        print(f"{m:6d} 分 {n:5d} 回  {repo:28s} {wf[:40]:40s} [{evs}]")


if __name__ == "__main__":
    main()
