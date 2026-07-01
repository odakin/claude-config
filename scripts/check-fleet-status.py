#!/usr/bin/env python3
"""check-fleet-status.py — fleet heartbeat の reader (layer 1 generic)。

sibling `fleet-heartbeat.py` (writer) が各マシンから git repo に commit する
`<dir>/<hostname>.json` を全部読み、 マシン役割 (role) に応じて異常を surface する。
finding 0 件なら silent (= dashboard / SessionStart hook 統合前提)。

役割 semantics:
- always-on   : 常時起動マシン。 heartbeat が --stale-hours を超えて停止 = 🔴
                (マシン / ネットワーク / launchd / git のどれかが死んでいる)。
                beat file 自体が無い = ℹ️ (install 待ち)。
- best-effort : スリープする可搬マシン。 staleness は仕様なので silent。
                beat が新鮮なとき (= 起きている) の server 異常のみ報告。

server 異常 (どの役割でも beat が新鮮なら報告):
- last_status auth_error      → 🔴 auth 失効で cycling (claude auth login が要る)
- last_status version_error   → 🔴 CLI が古い (remote-control-server.md#ts-version-mismatch)
- last_status consent_pending → 🟠 初回同意プロンプト待ちで進めない
- pid 無し (loaded but dead)  → 🟠

usage:
  check-fleet-status.py --dir <fleet-status-dir> [--role HOST=always-on ...]
      [--stale-hours 6]
  check-fleet-status.py --selftest

⚠️ 読むのは git working tree = 「最後に pull した時点の他マシン状態」。 呼び出し側の
   dashboard / sync-sweep が fetch/pull を担う前提 (= 本 script は fetch しない)。
"""

import argparse
import json
import sys
import time
from pathlib import Path

BAD = {
    "auth_error": ("🔴", "auth 失効で cycling 中 (= そのマシンで `claude auth login`。 remote-control-server.md#ts-api-key-conflict / #account-auth-keychain)"),
    "version_error": ("🔴", "CLI が古くて RC 不能 (remote-control-server.md#ts-version-mismatch)"),
    "consent_pending": ("🟠", "初回同意プロンプト待ちで進めない (そのマシンで `claude remote-control` に y)"),
}


def scan(dir_, roles, stale_hours, now=None):
    now = now or time.time()
    findings = []
    seen = set()
    for f in sorted(dir_.glob("*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            findings.append(f"🟠 {f.name}: parse 不能 (壊れた heartbeat file)")
            continue
        host = d.get("host", f.stem)
        seen.add(host)
        role = roles.get(host, "best-effort")
        age_h = (now - d.get("epoch", 0)) / 3600
        fresh = age_h <= stale_hours
        if role == "always-on" and not fresh:
            findings.append(
                f"🔴 {host} (always-on): heartbeat が {age_h:.1f}h 停止 (threshold {stale_hours:g}h) "
                f"= マシン / ネットワーク / launchd / git push のどれかが死んでいる可能性。 "
                f"スマホの environment 一覧でも server 生存を cross-check"
            )
            continue
        if not fresh:
            continue  # best-effort の staleness は仕様 (スリープ)
        for s in d.get("servers", []):
            st = s.get("last_status")
            if st in BAD:
                mark, desc = BAD[st]
                findings.append(f"{mark} {host}: server {s.get('label')} = {st} — {desc}")
            elif s.get("pid") is None:
                findings.append(f"🟠 {host}: server {s.get('label')} が loaded だが process 無し")
        if role == "always-on" and not d.get("servers"):
            findings.append(f"🟠 {host} (always-on): RC server が 1 本も loaded されていない")
    for host, role in roles.items():
        if role == "always-on" and host not in seen:
            findings.append(f"ℹ️ {host} (always-on): heartbeat 未開始 (= そのマシンで fleet-heartbeat の install 待ち)")
    return findings


def selftest():
    import tempfile
    ok = 0
    now = 1_800_000_000
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        def write(host, epoch, servers):
            json.dump({"host": host, "epoch": epoch, "servers": servers},
                      open(d / f"{host}.json", "w"))

        # 1: always-on stale → 🔴
        write("srv", now - 10 * 3600, [])
        f = scan(d, {"srv": "always-on"}, 6, now)
        assert any("🔴 srv" in x and "停止" in x for x in f), f
        ok += 1
        # 2: best-effort stale → silent
        write("lap", now - 48 * 3600, [{"label": "x", "pid": "1", "last_status": "auth_error"}])
        f = scan(d, {"srv": "always-on"}, 6, now)
        assert not any("lap" in x for x in f), f
        ok += 1
        # 3: fresh + auth_error → 🔴 (best-effort でも)
        write("lap", now - 600, [{"label": "x", "pid": "1", "last_status": "auth_error"}])
        f = scan(d, {}, 6, now)
        assert any("lap" in x and "auth_error" in x for x in f), f
        ok += 1
        # 4: fresh + connected → silent
        write("lap", now - 600, [{"label": "x", "pid": "1", "last_status": "connected"}])
        write("srv", now - 600, [{"label": "y", "pid": "2", "last_status": "connected"}])
        f = scan(d, {"srv": "always-on"}, 6, now)
        assert f == [], f
        ok += 1
        # 5: always-on で beat file 不在 → ℹ️
        f = scan(d, {"ghost": "always-on"}, 6, now)
        assert any("ghost" in x and "未開始" in x for x in f), f
        ok += 1
        # 6: loaded but pid 無し → 🟠
        write("lap", now - 600, [{"label": "x", "pid": None, "last_status": "connected"}])
        f = scan(d, {}, 6, now)
        assert any("process 無し" in x for x in f), f
        ok += 1
    print(f"selftest: {ok}/6 PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    ap.add_argument("--role", action="append", default=[])
    ap.add_argument("--stale-hours", type=float, default=6)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.dir:
        sys.exit(0)
    roles = {}
    for r in args.role:
        if "=" in r:
            h, v = r.split("=", 1)
            roles[h] = v
    dir_ = Path(args.dir).expanduser()
    if not dir_.is_dir():
        sys.exit(0)  # fleet 未開始 = silent (fail-open)
    try:
        findings = scan(dir_, roles, args.stale_hours)
    except Exception:
        sys.exit(0)
    if findings:
        print("🛰 fleet heartbeat findings (= cross-machine 状態、 multi-machine-state.md#fleet-heartbeat):")
        for x in findings:
            print(f"  {x}")
    sys.exit(0)


if __name__ == "__main__":
    main()
