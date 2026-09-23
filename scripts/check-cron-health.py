#!/usr/bin/env python3
"""launchd の無人ジョブの失敗を、 そのマシンで原因つきで出す horizon (= 「黙って全滅」 の再発防止)。

fleet heartbeat (scripts/fleet-heartbeat.py) は他のマシンに「そのジョブがどうなったか」 を運び、 本 script は
そのマシン自身の session 開始・dashboard で同じことを言う。 どちらも判定は scripts/lib/launchd_job_log.py
(= 1 か所) を使う。 規約の正本 = conventions/scheduled-tasks.md の #headless-context-budget §監視 /
#reload-resets-exit-status / #headless-auth-expiry。

  check-cron-health.py --prefix <label prefix> [--prefix ...]   # 対象 = launchctl list の label がどれかで始まる job
  check-cron-health.py --selftest

  env (test 用): CLAUDE_CRON_HEALTH_PREFIX (comma 区切り、 --prefix が無いとき) /
                 CLAUDE_CRON_HEALTH_LOGDIR (既定 ~/Library/Logs) / CLAUDE_CRON_HEALTH_AGENTS (既定 ~/Library/LaunchAgents)

述語 (= code-as-SoT):
  - 🔴 = launchctl list の終了コード ≠ 0 (launchd は次の成功まで値を保持する = 「直近失敗」 と「失敗しっぱなし」 を
    区別しない。 どちらも見るべき状態)
  - 🔴 = 終了コード 0 でも、 直近の run の log 末尾が既知の失敗で、 log が新しい (lib の hidden_failure)
    = plist の読み込み直しで終了コードが 0 に戻った失敗
  - 各行に log の鮮度 (mtime) と、 既知の失敗なら原因 (認証切れ + config dir / Prompt is too long) を付ける
  - 認証切れがあれば config dir ごとに 1 行: 今ログイン済みなら「次の run で消える」、 未ログインなら login の command
  - 該当 0 件なら silent (= dashboard 契約)。 launchctl が無い (非 macOS) なら fail-open (exit 0)

⚠️ 限界: exit 0 で中身が壊れている run (= 既知の文言を出さない論理故障) は射程外 = 各 routine 固有の heartbeat が相補する。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import launchd_job_log as jl  # noqa: E402

LOG_DIR = Path(os.environ.get("CLAUDE_CRON_HEALTH_LOGDIR", str(Path.home() / "Library" / "Logs")))
LAUNCH_AGENTS = Path(os.environ.get("CLAUDE_CRON_HEALTH_AGENTS", str(Path.home() / "Library" / "LaunchAgents")))


def parse_launchctl(text: str, prefixes: list[str]) -> list[tuple[str, int]]:
    """`launchctl list` 出力 ("PID\\tStatus\\tLabel") から (label, 終了コード)。 対象 = prefix の job、 数値でない行は skip。"""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        _pid, status, label = parts
        if not any(label.startswith(p) for p in prefixes):
            continue
        try:
            out.append((label, int(status)))
        except ValueError:
            continue
    return out


def _plist(label: str):
    return jl.load_plist(LAUNCH_AGENTS / f"{label}.plist")


def _log(label: str) -> Path:
    return jl.job_log_path(label, _plist(label), LOG_DIR)


def log_age_note(label: str, now: float | None = None) -> str:
    """log の mtime から「その失敗はいつのものか」。 3 日以上前なら終了コードの残留 (sticky) の可能性を明示。"""
    age_d = jl.log_age_days(_log(label), now)
    if age_d is None or age_d < 0:
        return ""
    if age_d < 1:
        return f" (最終 log 書込 {age_d * 24:.0f}h 前)"
    note = "、 sticky 残留の可能性 = 現況は log で確認" if age_d >= 3 else ""
    return f" (最終 log 書込 {age_d:.0f}日前{note})"


def log_signature(label: str) -> str:
    path = _log(label)
    kind = jl.failure_kind(path)
    if kind == "auth":
        d = jl.config_dir_of(_plist(label))
        return f" (log 末尾 = Claude の認証切れ{' ' + d if d else ''})"
    if kind == "ptl":
        n = sum(1 for line in jl.log_tail(path) if jl.PTL_MARKER in line)
        return (f" (log 末尾に 'Prompt is too long' ×{n} = context budget 超過、"
                f" 層1 scheduled-tasks.md#headless-context-budget)")
    return ""


def findings(text: str, prefixes: list[str], now: float | None = None) -> list[str]:
    out = []
    for label, code in sorted(parse_launchctl(text, prefixes)):
        short = next((label[len(p):] for p in prefixes if label.startswith(p)), label)
        if code == 0:
            if jl.hidden_failure(0, _log(label), now):
                out.append(f"  🔴 {short}: exit 0 だが直近 run の log 末尾が失敗{log_age_note(label, now)}"
                           f"{log_signature(label)} (= plist の読み込み直しで終了コードが 0 に戻った)")
            continue
        out.append(f"  🔴 {short}: 直近 run が exit {code}{log_age_note(label, now)}{log_signature(label)}")
    return out


def auth_remedies(text: str, prefixes: list[str]) -> list[str]:
    """認証切れの job がある config dir ごとに 1 行 (ログイン済みなら「次の run で消える」、 未ログインなら command)。"""
    dirs: list[str] = []
    for label, _code in sorted(parse_launchctl(text, prefixes)):
        if jl.failure_kind(_log(label)) == "auth":
            d = jl.config_dir_of(_plist(label)) or "<plist の起動行の CLAUDE_CONFIG_DIR>"
            if d not in dirs:
                dirs.append(d)
    out = []
    for d in dirs:
        email = jl.logged_in_email(d)
        if email:
            out.append(f"  ✅ {d} は今はログイン済み ({email}) = 上の行は次の run で消える"
                       f" (急ぐなら launchctl kickstart -k gui/$(id -u)/<label>)")
        else:
            out.append(f"  🔑 そのマシンの terminal で: CLAUDE_CONFIG_DIR={d} claude auth login")
    return out


def prefixes_from(argv: list[str]) -> list[str]:
    out = []
    for i, a in enumerate(argv):
        if a == "--prefix" and i + 1 < len(argv):
            out.append(argv[i + 1])
        elif a.startswith("--prefix="):
            out.append(a.split("=", 1)[1])
    if not out:
        out = [p for p in os.environ.get("CLAUDE_CRON_HEALTH_PREFIX", "").split(",") if p]
    return out


def main(argv: list[str]) -> int:
    prefixes = prefixes_from(argv)
    if not prefixes:
        print("check-cron-health: --prefix <launchd label prefix> が要る (例: --prefix com.example.)", file=sys.stderr)
        return 2
    try:
        text = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0  # fail-open (非 macOS / launchctl 不在)
    rows = findings(text, prefixes)
    if not rows:
        return 0
    print()
    print("🚦 launchd cron の失敗 (= LastExitStatus != 0、 または exit 0 でも直近 run の log 末尾が既知の失敗。"
          " log は job の plist の出力先)")
    for r in rows:
        print(r)
    rem = auth_remedies(text, prefixes)
    for r in rem:
        print(r)
    if any("🔑" in r for r in rem):
        print("    ⚠️ 承認はブラウザで今ログインしている claude.ai のアカウントに黙って紐づく = 目的の"
              "アカウントに切り替えてから承認し、 最後に claude auth status の email を見る"
              " (層1 remote-control-server.md#oauth-grabs-browser-account)")
    print("  → 手動再現 = `launchctl kickstart -k gui/$(id -u)/<label>` → log 確認。")
    print("    'Prompt is too long' なら routine の model の context / memory file の肥大を疑う"
          " (層1 scheduled-tasks.md#headless-context-budget)")
    return 0


def selftest() -> int:
    import plistlib
    import tempfile
    global LOG_DIR, LAUNCH_AGENTS
    checks = []

    def ck(name, cond):
        checks.append((name, bool(cond)))

    P = ["com.example."]
    fx = "\n".join(["PID\tStatus\tLabel", "-\t0\tcom.example.cron.ok-job", "-\t1\tcom.example.cron.bad-job",
                    "-\t78\tcom.example.other.worse-job", "123\t0\tcom.example.running-job",
                    "-\t1\tcom.apple.unrelated", "-\tx\tcom.example.cron.weird"])
    old = (LOG_DIR, LAUNCH_AGENTS)
    with tempfile.TemporaryDirectory() as td:
        LOG_DIR = LAUNCH_AGENTS = Path(td)
        rows = findings(fx, P)
        ck("prefix の job のみ", len(parse_launchctl(fx, P)) == 4)
        ck("exit 0 (log 無し) は finding にしない", not any("ok-job" in r for r in rows))
        ck("exit 1 を flag", any("cron.bad-job: 直近 run が exit 1" in r for r in rows))
        ck("exit 78 を flag", any("worse-job" in r for r in rows))
        ck("他の prefix は無視", not any("unrelated" in r for r in rows))
        ck("非数値 status は skip", not any("weird" in r for r in rows))
        ck("prefix が複数でも拾う", len(parse_launchctl(fx, ["com.example.cron.", "com.example.other."])) == 3)
        (LOG_DIR / "com.example.x.log").write_text("ok\nPrompt is too long\nPrompt is too long\n")
        ck("Prompt is too long ×2", "×2" in log_signature("com.example.x"))
        ck("log 不在は空 signature", log_signature("com.example.nolog") == "")
        lf = LOG_DIR / "com.example.aged.log"
        lf.write_text("fail\n")
        m = lf.stat().st_mtime
        ck("age <1d は h 表示", "h 前" in log_age_note("com.example.aged", now=m + 3600 * 5))
        ck("age 1-3d は日表示・sticky 注記なし", "日前)" in log_age_note("com.example.aged", now=m + 86400 * 2))
        aged = log_age_note("com.example.aged", now=m + 86400 * 16)
        ck("age >=3d は sticky 残留注記", "16日前" in aged and "sticky 残留" in aged)
        ck("負 age (時計逆行) は空", log_age_note("com.example.aged", now=m - 10) == "")
        # 認証切れ: config dir + exit 0 に隠れた失敗 + 古い log / 末尾の外の失敗は拾わない
        for lab in ("com.example.auth-job", "com.example.hidden-job", "com.example.old-job"):
            with open(LAUNCH_AGENTS / f"{lab}.plist", "wb") as fh:
                plistlib.dump({"ProgramArguments": ["/bin/sh", "-c",
                               'export CLAUDE_CONFIG_DIR="/nonexistent/.claude-acct"; exec claude -p x']}, fh)
            (LOG_DIR / f"{lab}.log").write_text("warn ...\nFailed to authenticate: OAuth session expired\n")
        (LOG_DIR / "com.example.fine.log").write_text("Failed to authenticate (昔の run)\n" + "ok\n" * 8)
        t0 = (LOG_DIR / "com.example.auth-job.log").stat().st_mtime
        os.utime(LOG_DIR / "com.example.old-job.log", (t0 - 86400 * 10, t0 - 86400 * 10))
        fx2 = "\n".join(["-\t1\tcom.example.auth-job", "-\t0\tcom.example.hidden-job",
                         "-\t0\tcom.example.old-job", "-\t0\tcom.example.fine"])
        rows2 = findings(fx2, P, now=t0 + 3600)
        ck("認証切れを named 表示 + config dir",
           any("auth-job: 直近 run が exit 1" in r and "認証切れ /nonexistent/.claude-acct" in r for r in rows2))
        ck("exit 0 でも直近 log が認証切れなら flag", any("hidden-job: exit 0 だが" in r for r in rows2))
        ck("exit 0 で log が古いなら flag しない", not any("old-job" in r for r in rows2))
        ck("exit 0 で log 末尾が正常なら flag しない", not any("fine" in r for r in rows2))
        ck("login command を config dir ごとに 1 行 (実在しない dir = 未ログイン扱い)",
           auth_remedies(fx2, P) == ["  🔑 そのマシンの terminal で: CLAUDE_CONFIG_DIR=/nonexistent/.claude-acct"
                                     " claude auth login"])
        ck("--prefix の解釈", prefixes_from(["--prefix", "a.", "--prefix=b."]) == ["a.", "b."])
        ck("prefix 無しは usage で exit 2", main([]) == 2 if not os.environ.get("CLAUDE_CRON_HEALTH_PREFIX") else True)
    LOG_DIR, LAUNCH_AGENTS = old
    n = sum(1 for _, c in checks if c)
    for name, c in checks:
        print(f"  {'PASS' if c else 'FAIL'}  {name}")
    print(f"selftest: {n}/{len(checks)} passed")
    return 0 if n == len(checks) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main(sys.argv[1:]))
