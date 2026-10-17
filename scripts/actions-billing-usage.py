#!/usr/bin/env python3
"""actions-billing-usage.py — GitHub Actions の月の使用分数を課金 API の正式な値で読み、 private repo の無料枠と比べる (今月なら月末までの見込みも)。

課金 API (`/users/<u>/settings/billing/usage`) の `usageItems` のうち `unitType` が `Minutes` の行を、
private repo について SKU の倍率 (Linux 1 / Windows 2 / macOS 10) を掛けて合計し、 プラン (`gh api user` の `plan.name`)
の月の枠 (free 2,000 / pro 3,000) に対する割合を出す。 public repo の分は無料・無制限なので枠に数えず、 別に合計だけ出す。
請求の net 合計 (0 なら枠の内) と、 repo ごとの上位も出す。

前提: gh の token に `user` の scope (`gh auth refresh -h github.com -s user` → ブラウザで device code を承認。 token は
機械ごと)。 無ければ exit 2 で直し方を出す。 scope が無い機械での見積もり = 姉妹の `actions-usage-estimate.py`
(run の履歴から数える。 請求額そのものではない)。 正本 = conventions/github-security-automation.md#private-actions-minutes

使い方:
  actions-billing-usage.py                  # 今月
  actions-billing-usage.py --month 2026-09  # 指定の月
  actions-billing-usage.py --selftest
"""

from __future__ import annotations

import argparse
import calendar
import json
import subprocess
import sys
from collections import Counter
from datetime import date

PLAN_MINUTES = {"free": 2000, "pro": 3000}
SKU_MULTIPLIER = (("windows", 2), ("macos", 10))  # SKU 名に含まれる語 → 倍率。 無ければ 1 (Linux)


def _gh(args: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def multiplier(sku: str) -> int:
    s = sku.lower()
    for word, m in SKU_MULTIPLIER:
        if word in s:
            return m
    return 1


def aggregate(items: list[dict], private: set[str]) -> dict:
    """usageItems を private / public の分数・repo ごとの分数・net 合計にまとめる (倍率は private の枠の計算にだけ掛ける)。"""
    priv = 0.0
    pub = 0.0
    per_repo: Counter = Counter()
    net = 0.0
    for i in items:
        net += float(i.get("netAmount") or 0)
        if i.get("unitType") != "Minutes":
            continue
        q = float(i.get("quantity") or 0)
        repo = i.get("repositoryName") or ""
        if repo in private:
            w = q * multiplier(i.get("sku") or "")
            priv += w
            per_repo[repo] += w
        else:
            pub += q
    return {"private": priv, "public": pub, "per_repo": per_repo, "net": net}


def projection(used: float, year: int, month: int, today: date) -> float | None:
    """今月なら経過日数で月末まで按分した見込み。 過去の月は None (= 確定値)。"""
    if (today.year, today.month) != (year, month):
        return None
    days = calendar.monthrange(year, month)[1]
    return used / max(today.day, 1) * days


def selftest() -> None:
    items = [
        {"unitType": "Minutes", "sku": "Actions Linux", "quantity": 100, "repositoryName": "a", "netAmount": 0},
        {"unitType": "Minutes", "sku": "Actions macOS 3-core", "quantity": 3, "repositoryName": "a", "netAmount": 0},
        {"unitType": "Minutes", "sku": "Actions Linux", "quantity": 50, "repositoryName": "pub", "netAmount": 0},
        {"unitType": "GigabyteHours", "sku": "Actions storage", "quantity": 9, "repositoryName": "a", "netAmount": 0.5},
    ]
    a = aggregate(items, {"a"})
    assert a["private"] == 130, a          # 100 + 3 × 10
    assert a["public"] == 50, a
    assert a["per_repo"]["a"] == 130, a
    assert abs(a["net"] - 0.5) < 1e-9, a
    assert multiplier("Actions Windows") == 2 and multiplier("Actions Linux") == 1
    assert projection(100, 2026, 10, date(2026, 10, 10)) == 310
    assert projection(100, 2026, 9, date(2026, 10, 10)) is None
    print("selftest: PASS")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--month", help="YYYY-MM (既定 = 今月)")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    today = date.today()
    year, month = (int(x) for x in a.month.split("-")) if a.month else (today.year, today.month)

    rc, login, err = _gh(["api", "user", "-q", ".login"])
    if rc != 0:
        sys.exit(f"gh で認証 user を読めない: {err.strip()}")
    login = login.strip()
    rc, out, err = _gh(["api", f"/users/{login}/settings/billing/usage?year={year}&month={month}"])
    if rc != 0:
        print("課金 API を読めない (gh の token に user の scope が無いと 404)。 直し方: "
              "gh auth refresh -h github.com -s user (ブラウザで device code を承認)。 "
              "scope が無いままの見積もり = actions-usage-estimate.py", file=sys.stderr)
        sys.exit(2)
    items = json.loads(out).get("usageItems", [])
    rc, plan, _ = _gh(["api", "user", "-q", ".plan.name"])
    plan = plan.strip() if rc == 0 else ""
    rc, repos, _ = _gh(["repo", "list", login, "--visibility", "private", "-L", "1000", "--json", "name"])
    private = {r["name"] for r in json.loads(repos)} if rc == 0 and repos.strip() else set()

    s = aggregate(items, private)
    quota = PLAN_MINUTES.get(plan)
    days = sorted({i["date"][:10] for i in items if i.get("date")})
    span = f"{days[0]}〜{days[-1]}" if days else "記録なし"
    print(f"{year}-{month:02d} ({span}) / plan = {plan or '不明'}")
    line = f"private repo の Actions: {s['private']:.0f} 分"
    if quota:
        line += f" / 枠 {quota} 分 ({s['private'] / quota:.0%})"
    print(line)
    p = projection(s["private"], year, month, today)
    if p is not None:
        tail = f" (枠の {p / quota:.0%})" if quota else ""
        print(f"月末までの見込み: {p:.0f} 分{tail}")
    print(f"public repo (枠に数えない): {s['public']:.0f} 分")
    note = ""
    if s["net"] == 0:
        over = quota is not None and s["private"] > quota
        # 請求 0 でも枠を超えた月は、 超えた後の run が spending limit で起動されなかった (= 数秒で failure) ことがある
        note = " (枠を超えたが請求は無い = 超えた後の run は spending limit で止まった可能性)" if over else " = 枠の内"
    print(f"請求 (net 合計): ${s['net']:.2f}{note}")
    for repo, m in s["per_repo"].most_common(a.top):
        print(f"  {repo}: {m:.0f} 分")


if __name__ == "__main__":
    main()
