#!/usr/bin/env python3
"""Claude for Mac の通知が鳴らない・来ない原因を層ごとに read-only 診断する (conventions/macos-claude-app-notifications.md)。

見る順 = 同 doc #notification-layers:
  1. Claude アプリの仕様 (完了通知は常に無音 / 見ている session は通知なし) … 定数として表示
  2. Claude アプリの設定 (preferences.notificationSound / notificationLevels)
  3. macOS の通知許可 (com.apple.ncprefs の flags + swift.log の Authorization)
  4. 音量 (alert volume / mute)
  5. 集中モード (unified log の状態変化 + Claude の通知ごとの扱い)

何も書き換えない (file read / defaults export / osascript get / log show のみ)。

Usage:
  python3 scripts/claude-app-notify-diagnose.py              # 直近 6 時間の log を見る
  python3 scripts/claude-app-notify-diagnose.py --hours 48   # 窓を広げる (log show は数十秒かかる)
  python3 scripts/claude-app-notify-diagnose.py --selftest
"""
from __future__ import annotations

import argparse
import json
import plistlib
import re
import subprocess
import sys
from pathlib import Path

BUNDLE = "com.anthropic.claudefordesktop"
APP_CONFIG = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
SWIFT_LOG = Path.home() / "Library/Logs/Claude/swift.log"
# zsh では `log` が builtin に食われる (doc #focus-dnd-unified-log) ので絶対 path で呼ぶ
LOG_BIN = "/usr/bin/log"

# com.apple.ncprefs の app flags。 bit 位置は公開仕様でなく観測からの推定 (doc #macos-notification-prefs)
FLAG_BITS = {"allow": 25, "badge": 1, "sound": 2, "banner": 3, "alert": 4}

APP_DESIGN_NOTES = [
    "タスク完了の通知 (Claude finished a task) はアプリの仕様で常に無音 — 設定では変えられない",
    "アプリが前面でその session を表示中なら、 許可要求の通知自体が出ない (viewing_session)",
    "鳴るのは 許可要求 / 質問 (AskUserQuestion) / 入力待ち。 1.5 秒以内の連続は 1 回だけ鳴る",
]


def decode_flags(flags: int) -> dict:
    return {k: bool(flags >> b & 1) for k, b in FLAG_BITS.items()}


def _field(pat: str, s: str):
    m = re.search(pat, s)
    return m.group(1).strip() if m else None


VOL_RE = re.compile(r"(output volume|alert volume|output muted):\s*([^,]+)")


def parse_volume(text: str) -> dict:
    return {k: v.strip() for k, v in VOL_RE.findall(text)}


def parse_state_update(line: str) -> dict:
    """donotdisturbd の 'Did receive state update' 1 行 → 新しい state の要点 (previousState は捨てる)。"""
    body = line[line.find("stateUpdate="):]
    state = body[body.find("state:"):]
    cut = state.find("previousState")
    if cut >= 0:
        state = state[:cut]
    return {
        "time": line[:19],
        "reason": _field(r"reason: ?([^;]+)", body),
        "suppression": _field(r"suppressionState: ?([^;]+)", state),
        "active_mode": _field(r"activeModeIdentifier: ?([^;>]+)", state),
        "mode_name": _field(r"<DNDMode:[^;]*; name: ([^;]+)", state),
        "start": _field(r"startDate: ?([^;]+)", state),
        "end": _field(r"userVisibleTransitionDate: ?([^;]+)", state),
    }


def is_active(state: dict) -> bool:
    mode = state.get("active_mode")
    return bool(mode) and mode != "(null)" and state.get("suppression") != "inactive"


def parse_claude_events(lines: list[str]) -> list[dict]:
    """Claude 宛て通知の集中モード判定 log を 1 通知 (= 同じ秒) ごとにまとめる。

    interruptionSuppression = none → 素通り / delay delivery → 音もバナーも出さず通知センター行き。
    """
    groups: dict[str, dict] = {}
    for line in lines:
        ev = groups.setdefault(line[:19], {"time": line[:19], "suppression": None, "app_allowed": False})
        sup = _field(r"interruptionSuppression: ?([a-z ]+?)[;>]", line)
        if sup:
            ev["suppression"] = sup
        if re.search(r"Breakthrough is allowed with reason: mode configuration for application", line):
            ev["app_allowed"] = True
    return [g for g in groups.values() if g["suppression"]]


def run(cmd: list[str], timeout: int = 60):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def log_show(hours: int, predicate: str) -> list[str]:
    r = run([LOG_BIN, "show", "--last", f"{hours}h", "--style", "compact", "--predicate", predicate], timeout=600)
    return [l for l in r.stdout.decode(errors="replace").splitlines() if l[:2] == "20"]


def read_app_prefs(path: Path = APP_CONFIG) -> dict:
    try:
        prefs = json.loads(path.read_text()).get("preferences", {})
    except (OSError, ValueError) as e:
        return {"error": str(e)}
    return {
        "notificationSound": prefs.get("notificationSound", "system"),
        "explicit": "notificationSound" in prefs,
        "notificationLevels": prefs.get("notificationLevels", {}),
        "dockBounceEnabled": prefs.get("dockBounceEnabled"),
    }


def read_ncprefs() -> dict:
    r = run(["defaults", "export", "com.apple.ncprefs", "-"])
    if r.returncode != 0:
        return {"error": r.stderr.decode(errors="replace").strip()}
    d = plistlib.loads(r.stdout)
    apps = d.get("apps", [])
    out: dict = {}
    for a in apps:
        if a.get("bundle-id") == BUNDLE:
            out["flags"] = a.get("flags", 0)
            out["decoded"] = decode_flags(out["flags"])
    allowed = [a.get("flags", 0) for a in apps if a.get("flags", 0) >> FLAG_BITS["allow"] & 1]
    out["allowed_apps"] = len(allowed)
    out["allowed_with_sound"] = sum(1 for f in allowed if f >> FLAG_BITS["sound"] & 1)
    dp = d.get("dnd_prefs")
    if isinstance(dp, bytes):
        try:
            dp = plistlib.loads(dp)
        except Exception:
            dp = None
    if isinstance(dp, dict):
        out["dndMirrored"] = dp.get("dndMirrored")
    return out


def read_swift_auth(path: Path = SWIFT_LOG):
    try:
        hits = [l for l in path.read_text(errors="replace").splitlines() if "Authorization granted" in l]
    except OSError:
        return None
    return hits[-1].strip() if hits else None


def read_volume() -> dict:
    r = run(["osascript", "-e", "get volume settings"])
    return parse_volume(r.stdout.decode()) if r.returncode == 0 else {"error": r.stderr.decode().strip()}


def diagnose(hours: int) -> int:
    stops: list[str] = []
    print("## 1. Claude アプリの仕様 (設定では変わらない)")
    for n in APP_DESIGN_NOTES:
        print(f"   ・ {n}")

    print("\n## 2. Claude アプリの設定")
    p = read_app_prefs()
    if "error" in p:
        print(f"   ⚠️ 設定 file を読めない: {p['error']}")
    else:
        src = "明示" if p["explicit"] else "未設定 = 既定"
        mark = "❌" if p["notificationSound"] == "none" else "✅"
        print(f"   {mark} notificationSound = {p['notificationSound']} ({src})")
        if p["notificationSound"] == "none":
            stops.append("Claude アプリの設定で通知音が none")
        if p["notificationLevels"]:
            print(f"   ・ notificationLevels = {p['notificationLevels']} (banner も badge も off の種別は通知自体が出ない)")

    print("\n## 3. macOS の通知許可")
    nc = read_ncprefs()
    if "error" in nc:
        print(f"   ⚠️ ncprefs を読めない: {nc['error']}")
    elif "decoded" not in nc:
        print(f"   ⚠️ {BUNDLE} の通知設定が無い (アプリが一度も通知許可を求めていない可能性)")
        stops.append("macOS に Claude の通知設定が無い")
    else:
        dec = nc["decoded"]
        for key, label in (("allow", "通知を許可"), ("sound", "サウンド"), ("banner", "バナー"), ("alert", "通知パネル")):
            print(f"   {'✅' if dec[key] else '・'} {label}: {'on' if dec[key] else 'off'}")
        print(f"   ・ 比較: 通知を許可している {nc['allowed_apps']} app 中 {nc['allowed_with_sound']} app でサウンド bit が立つ"
              " (bit 位置は推定 = 同じ値なら同じ設定と読む)")
        if not dec["allow"]:
            stops.append("macOS で Claude の通知が許可されていない")
        elif not dec["sound"]:
            stops.append("macOS の Claude の通知設定でサウンドが off (推定)")
    auth = read_swift_auth()
    if auth:
        print(f"   {'✅' if 'true' in auth else '❌'} swift.log: {auth}")
        if "false" in auth:
            stops.append("Claude アプリの通知許可が false")

    print("\n## 4. 音量")
    v = read_volume()
    if "error" in v:
        print(f"   ⚠️ 音量を読めない: {v['error']}")
    else:
        muted = v.get("output muted") == "true"
        alert0 = v.get("alert volume") in ("0", "missing value")
        print(f"   {'❌' if muted or alert0 else '✅'} alert volume = {v.get('alert volume')} / muted = {v.get('output muted')}")
        if muted or alert0:
            stops.append("音量 (mute か通知音量 0)")

    print(f"\n## 5. 集中モード (unified log 直近 {hours} 時間)")
    if nc.get("dndMirrored"):
        print("   ・ 「デバイス間で共有」 = on (他の端末で入れた集中モードがこの Mac にも来る)")
    states = [parse_state_update(l) for l in log_show(
        hours, 'subsystem == "com.apple.donotdisturb" AND eventMessage CONTAINS "Did receive state update"')]
    if states:
        s = states[-1]
        if is_active(s):
            end = "終了時刻なし" if (s["end"] or "").startswith("4001") else s["end"]
            print(f"   ⚠️ 最後の状態変化 {s['time']} ({s['reason']}) = 「{s['mode_name']}」 オン (start {s['start']}, 終了 {end})")
        else:
            print(f"   ✅ 最後の状態変化 {s['time']} ({s['reason']}) = オフ")
    else:
        print("   ・ 窓内に状態変化なし (--hours を伸ばすと、 いつからの状態か分かる)")
    events = parse_claude_events(log_show(
        hours, f'subsystem == "com.apple.donotdisturb" AND eventMessage CONTAINS "{BUNDLE.split(".")[-1]}"'))
    if events:
        held = [e for e in events if e["suppression"] != "none"]
        last = events[-1]
        how = "素通り" if last["suppression"] == "none" else f"{last['suppression']} (音もバナーも出ない)"
        allowed = " / 「通知されるアプリ」 で許可" if last["app_allowed"] else ""
        print(f"   {'❌' if last['suppression'] != 'none' else '✅'} Claude の通知 {len(events)} 件中 {len(held)} 件が保留。"
              f" 最新 {last['time']} = {how}{allowed}")
        if last["suppression"] != "none":
            stops.append("集中モードが Claude の通知を保留している")
    else:
        print("   ・ 窓内に Claude の通知なし (= 集中モードの判定を受けた通知が無い)")

    print("\n## 判定")
    if stops:
        for s in stops:
            print(f"   ❌ {s}")
    else:
        print("   ✅ 設定・許可・音量・集中モードのどこでも止まっていない。 鳴らないなら 1 の仕様 (完了通知 / 表示中の session) を疑う")
    return 1 if stops else 0


def selftest() -> int:
    fails = 0

    def check(cond, msg):
        nonlocal fails
        print(("  ok   " if cond else "  FAIL ") + msg)
        fails += 0 if cond else 1

    d = decode_flags(310386702)  # 実機の Claude の値 (許可 + バッジ + サウンド + バナー)
    check(d == {"allow": True, "badge": True, "sound": True, "banner": True, "alert": False}, "decode_flags")
    check(parse_volume("output volume:50, input volume:100, alert volume:47, output muted:false")
          == {"output volume": "50", "alert volume": "47", "output muted": "false"}, "parse_volume")
    on = ("2026-09-12 08:00:02.000 Df donotdisturbd[1:2] [com.apple.donotdisturb:ServiceProvider] Did receive state"
          " update, will handle; stateUpdate=<DNDStateUpdate: 0x1; reason: scheduled; source: local; options: <none>;"
          " state: <DNDState: 0x2; suppressionState: while UI locked; startDate: 2026-09-11 23:00:00 +0000;"
          " userVisibleTransitionDate: 4001-01-01 00:00:00 +0000; activeModeConfiguration:"
          " <DNDMutableModeConfiguration: 0x3; mode: <DNDMode: 0x4; name: Do Not Disturb; modeIdentifier:"
          " com.apple.donotdisturb.mode.default; semanticType: 0>>; activeModeIdentifier:"
          " com.apple.donotdisturb.mode.default>; previousState: <DNDState: 0x5; suppressionState: inactive;"
          " activeModeIdentifier: (null)>>")
    s = parse_state_update(on)
    check(s["reason"] == "scheduled" and s["mode_name"] == "Do Not Disturb" and s["end"].startswith("4001")
          and is_active(s), "parse_state_update: オン (previousState を拾わない)")
    off = ("2026-09-12 08:17:42.000 Df donotdisturbd[1:2] Did receive state update; stateUpdate=<DNDStateUpdate:"
           " 0x1; reason: user action; source: local; state: <DNDState: 0x2; suppressionState: inactive;"
           " activeModeIdentifier: (null)>; previousState: <DNDState: 0x5; suppressionState: while UI locked;"
           " activeModeIdentifier: com.apple.donotdisturb.mode.default>>")
    s = parse_state_update(off)
    check(s["reason"] == "user action" and not is_active(s), "parse_state_update: オフ (previousState がオンでも)")
    ev = parse_claude_events([
        "2026-09-12 08:07:02.188 Df donotdisturbd[1] Breakthrough is NOT allowed with reason: mode configuration type claudefordesktop",
        "2026-09-12 08:07:02.189 Df NotificationCenter[2] Resolved event behavior=<DNDClientEventBehavior: 0x1;"
        " interruptionSuppression: delay delivery; x> claudefordesktop",
        "2026-09-12 08:14:50.100 Df donotdisturbd[1] Breakthrough is allowed with reason: mode configuration for"
        " application for configuration claudefordesktop",
        "2026-09-12 08:14:50.200 Df NotificationCenter[2] Resolved event behavior=<DNDClientEventBehavior: 0x1;"
        " interruptionSuppression: none; x> claudefordesktop",
    ])
    check(len(ev) == 2 and ev[0]["suppression"] == "delay delivery" and not ev[0]["app_allowed"]
          and ev[1]["suppression"] == "none" and ev[1]["app_allowed"], "parse_claude_events: 保留 → 許可後に素通り")
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=int, default=6, help="unified log を遡る時間 (既定 6)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if sys.platform != "darwin":
        print("macOS 専用")
        return 2
    return diagnose(a.hours)


if __name__ == "__main__":
    sys.exit(main())
