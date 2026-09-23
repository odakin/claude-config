#!/usr/bin/env python3
"""desktop app でのログアウトの後、 同じ account の無人 job / RC の設定フォルダの認証が更新されていなければ 🔴 (切れる前に言う)。

背景 (実測、 macOS の Claude desktop app + Claude Code CLI): desktop app で account X をログアウトした後、 同じ機械で
X として無人の `claude -p` / Remote Control が使う設定フォルダ (`CLAUDE_CONFIG_DIR`) が、 次にトークンの更新が要る時点で
`OAuth session expired and could not be refreshed` になった例がある。 ログアウトの直後はアクセストークンが残っていて
問い合わせが通るので、 翌朝の job の失敗まで誰も気づかない。 因果は未確定 (同じ account の新しいログインが原因という
仮説と分けられていない) = 本 script は「疑い」 として出し、 確かめる問い合わせを予約できる。 規約の正本 =
conventions/scheduled-tasks.md#headless-auth-expiry。

  check-desktop-logout-auth.py                     # 表示だけ (dashboard / SessionStart 用。 該当 0 件なら silent)
  check-desktop-logout-auth.py --schedule-probes   # 表示 + 未予約のログアウトに問い合わせを launchd で予約 (冪等)
  check-desktop-logout-auth.py --probe DIR [--tag T]   # DIR に最小の claude -p を 1 回、 結果を ledger に追記
  check-desktop-logout-auth.py --install-watch / --uninstall-watch   # 15 分ごとの --schedule-probes を launchd に
  check-desktop-logout-auth.py --selftest

述語 (= code-as-SoT):
  - 対象 = ~/Library/LaunchAgents/*.plist の起動行にある CLAUDE_CONFIG_DIR (= 無人 job と RC サーバーが使うフォルダ)。
    判定は scripts/lib/launchd_job_log.py の config_dir_of。 実在する絶対 path だけ
  - フォルダの account = <dir>/.claude.json の oauthAccount.accountUuid
  - keychain の項目 = "Claude Code-credentials-" + sha256(フォルダの path) の先頭 8 桁 (実測で一致)。 更新時刻
    (mdat) は `security find-generic-password -s <項目>` の属性だけを読む (値は読まない)
  - ログアウト = desktop app の log (main.log / main1.log) の
    `Login-state transition (loggedOut: false → true, uuid: <X> → <none>)`。 時刻は log の local time
  - 🔴 = そのフォルダの account の最新のログアウトが、 keychain の更新時刻より後 (= ログアウト以降、 更新もログインも
    成功していない)。 更新が要る目安 = keychain の更新時刻 + AT_LIFETIME_H (desktop の Code タブのトークンが約 7h55m
    ごとに更新されることからの推定)
  - 問い合わせの ledger (~/.claude/state/desktop-logout-probe.log) に、 ログアウト後の失敗があれば「切れた」、
    目安の時刻を過ぎた成功があれば「目安では切れていない」 を添える
  - 予約 = 直後に 1 回 (アクセストークンがその場で失効するか) + 目安 + 15 分に 1 回 (更新トークンが生きているか)。
    同じ (フォルダ, ログアウト時刻) には 1 度だけ (state = ~/.claude/state/desktop-logout-probe-state.json)。
    予約は一回だけ走って自分の plist を消す
  - desktop app の log が無い (desktop 未使用の機械 / 非 macOS) なら silent (fail-open、 exit 0)

⚠️ 限界: desktop app の log の文言が変わると検知が黙って止まる (selftest は固定の文言で見ている)。 他の機械での
ログアウトは見えない。 アクセストークンの寿命は推定。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import launchd_job_log as jl  # noqa: E402

HOME = Path.home()
DESKTOP_LOG_DIR = Path(os.environ.get("CLAUDE_DESKTOP_LOG_DIR", str(HOME / "Library" / "Logs" / "Claude")))
LAUNCH_AGENTS = Path(os.environ.get("CLAUDE_LOGOUT_AGENTS", str(HOME / "Library" / "LaunchAgents")))
STATE_DIR = Path(os.environ.get("CLAUDE_LOGOUT_STATE_DIR", str(HOME / ".claude" / "state")))
LEDGER = STATE_DIR / "desktop-logout-probe.log"
STATE = STATE_DIR / "desktop-logout-probe-state.json"
AT_LIFETIME_H = 8
VERDICT_MARGIN_MIN = 15
PROBE_MODEL = "claude-haiku-4-5-20251001"
PROBE_LABEL_PREFIX = "com.claude-config.logout-probe"
WATCH_LABEL = "com.claude-config.desktop-logout-watch"
KEYCHAIN_PREFIX = "Claude Code-credentials-"

_LOGOUT_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) .*Login-state transition \(loggedOut: false → true, uuid: ([0-9a-f-]+) → <none>\)")
_MDAT_RE = re.compile(r'"mdat"<timedate>=0x[0-9A-F]*\s+"(\d{14})Z')


def keychain_service(config_dir: str) -> str:
    return KEYCHAIN_PREFIX + hashlib.sha256(config_dir.encode()).hexdigest()[:8]


def keychain_mdat(service: str) -> float | None:
    """keychain 項目の更新時刻 (epoch)。 属性だけ読む。 無い・読めないなら None。"""
    try:
        cp = subprocess.run(["security", "find-generic-password", "-s", service],
                            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    m = _MDAT_RE.search(cp.stdout + cp.stderr)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()


def watched_dirs(agents_dir: Path) -> dict[str, list[str]]:
    """CLAUDE_CONFIG_DIR → それを使う launchd label の一覧。"""
    out: dict[str, list[str]] = {}
    for p in sorted(agents_dir.glob("*.plist")):
        d = jl.config_dir_of(jl.load_plist(p))
        if d.startswith("/") and os.path.isdir(d):
            out.setdefault(d, []).append(p.stem)
    return out


def dir_account(config_dir: str) -> tuple[str, str]:
    """(accountUuid, email)。 読めなければ ("", "")。"""
    try:
        o = json.loads(Path(config_dir, ".claude.json").read_text(encoding="utf-8")).get("oauthAccount") or {}
    except Exception:
        return "", ""
    return str(o.get("accountUuid") or ""), str(o.get("emailAddress") or "")


def logouts(log_dir: Path) -> dict[str, float]:
    """accountUuid → 最新のログアウト時刻 (epoch)。 main1.log (前の世代) と main.log を読む。"""
    last: dict[str, float] = {}
    for name in ("main1.log", "main.log"):
        p = log_dir / name
        try:
            fh = p.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if "Login-state transition (loggedOut: false" not in line:
                    continue
                m = _LOGOUT_RE.match(line)
                if not m:
                    continue
                t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                if t > last.get(m.group(2), 0):
                    last[m.group(2)] = t
    return last


def read_ledger(ledger: Path) -> list[dict]:
    rows = []
    try:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 4:
                try:
                    t = time.mktime(time.strptime(parts[0], "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    continue
                rows.append({"t": t, "tag": parts[1], "dir": parts[2], "ok": parts[3] == "ok"})
    except OSError:
        pass
    return rows


def _hm(t: float) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(t))


def assess(dirs: dict[str, list[str]], last_logout: dict[str, float], mdat_of, ledger_rows: list[dict],
           now: float | None = None) -> list[dict]:
    """at-risk なフォルダごとに 1 件。 mdat_of = config_dir → keychain 更新時刻 (epoch|None)。"""
    now = time.time() if now is None else now
    out = []
    for d, labels in sorted(dirs.items()):
        uuid, email = dir_account(d)
        t_out = last_logout.get(uuid) if uuid else None
        if not t_out:
            continue
        m = mdat_of(d)
        if m is None or m >= t_out:
            continue  # ログアウト以降に更新 or ログインが成功している = 生きている
        verdict_at = m + AT_LIFETIME_H * 3600
        after = [r for r in ledger_rows if r["dir"] == d and r["t"] > t_out]
        state = "未確認"
        if any(not r["ok"] for r in after):
            state = "切れた"
        elif any(r["ok"] and r["t"] > verdict_at for r in after):
            state = "目安を過ぎても通った"
        out.append({"dir": d, "email": email or uuid[:8], "labels": labels, "logout": t_out, "mdat": m,
                    "verdict_at": verdict_at, "state": state, "now": now})
    return out


def render(items: list[dict], script: str) -> list[str]:
    lines = []
    for it in items:
        who = f"{it['dir']} ({len(it['labels'])} 本の launchd job が使う)"
        fix = f"CLAUDE_CONFIG_DIR={it['dir']} claude auth login"
        if it["state"] == "切れた":
            lines.append(f"🔴 {who} は切れた (desktop で {it['email']} を {_hm(it['logout'])} にログアウトした後の問い合わせが失敗)。"
                         f" 直す = そのマシンで {fix}")
        elif it["state"] == "目安を過ぎても通った":
            lines.append(f"🟡 desktop で {it['email']} を {_hm(it['logout'])} にログアウトしたが、 {who} は更新の目安"
                         f" ({_hm(it['verdict_at'])}) を過ぎても通った = トークンの寿命が目安より長い可能性。 翌日の run で確かめる")
        else:
            lines.append(f"🔴 desktop で {it['email']} を {_hm(it['logout'])} にログアウトした後、 {who} の認証は一度も更新されていない"
                         f" → 次の更新 ({_hm(it['verdict_at'])} 頃) で切れる疑い。 確かめる = python3 {script} --probe {it['dir']}"
                         f" / 直す = {fix}")
    return lines


# ── 問い合わせ ─────────────────────────────────────────────

def probe(config_dir: str, tag: str, claude: str = "claude", ledger: Path = LEDGER) -> bool:
    svc = keychain_service(config_dir)
    before = keychain_mdat(svc)
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
    env["CLAUDE_CONFIG_DIR"] = config_dir
    env["PATH"] = f"{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
    cmd = [claude, "-p", "--no-session-persistence", "--strict-mcp-config",
           "--settings", json.dumps({"disableAllHooks": True, "remoteControlAtStartup": False}),
           "--model", PROBE_MODEL, "Reply with the single word OK."]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=240, env=env,
                            cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL)
        rc, raw = cp.returncode, (cp.stdout + cp.stderr)
    except Exception as e:  # CLI が無い・timeout
        rc, raw = 99, f"probe error: {e}"
    # 成否は終了コード + 認証エラーの文言 (返答の語では決めない: 設定で日本語になる)
    ok = rc == 0 and not any(mk in raw for mk in jl.AUTH_MARKERS) and not re.search(r"\b401\b", raw)
    after = keychain_mdat(svc)
    fmt = lambda t: time.strftime("%m-%d %H:%M:%S", time.localtime(t)) if t else "-"  # noqa: E731
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write("\t".join([time.strftime("%Y-%m-%d %H:%M:%S"), tag, config_dir, "ok" if ok else f"FAIL(rc={rc})",
                            f"keychain {fmt(before)} -> {fmt(after)}", " ".join(raw.split())[:160]]) + "\n")
    if not ok:
        notify = Path(__file__).resolve().parent / "claude-notify.sh"
        if notify.exists():
            subprocess.run(["sh", str(notify), "--title", f"認証切れ: {Path(config_dir).name}",
                            "--body", f"desktop ログアウト後の問い合わせが失敗 ({tag})。 直す = CLAUDE_CONFIG_DIR={config_dir} claude auth login"],
                           capture_output=True, timeout=30)
    print(f"{'ok' if ok else 'FAIL'}\t{config_dir}\t{' '.join(raw.split())[:120]}")
    return ok


# ── 予約 ─────────────────────────────────────────────────

def _one_shot_plist(label: str, when: float, args: list[str]) -> dict:
    lt = time.localtime(when)
    plist_path = LAUNCH_AGENTS / f"{label}.plist"
    q = " ".join("'" + a.replace("'", "'\\''") + "'" for a in args)
    # 片付けは file を先に消し、 bootout を最後に (bootout は自分の process を止めるので、 後ろの rm は走らない = 実測)
    cmd = f"{q}; rm -f '{plist_path}'; /bin/launchctl bootout gui/$(id -u)/{label}"
    return {"Label": label, "ProgramArguments": ["/bin/sh", "-c", cmd], "RunAtLoad": False,
            "StartCalendarInterval": {"Month": lt.tm_mon, "Day": lt.tm_mday, "Hour": lt.tm_hour, "Minute": lt.tm_min},
            "StandardOutPath": str(HOME / "Library" / "Logs" / f"{PROBE_LABEL_PREFIX}.log"),
            "StandardErrorPath": str(HOME / "Library" / "Logs" / f"{PROBE_LABEL_PREFIX}.log")}


def plan_probes(items: list[dict], state: dict, now: float) -> list[tuple[str, str, float, str]]:
    """未予約の (key, dir, 時刻, tag)。 状態が「未確認」 のものだけ。"""
    todo = []
    for it in items:
        if it["state"] != "未確認":
            continue
        key = f"{it['dir']}|{int(it['logout'])}"
        if key in state:
            continue
        todo.append((key, it["dir"], now + 120, "after-logout"))
        if it["verdict_at"] + VERDICT_MARGIN_MIN * 60 > now + 300:
            todo.append((key, it["dir"], it["verdict_at"] + VERDICT_MARGIN_MIN * 60, "verdict"))
    return todo


def schedule(items: list[dict], now: float | None = None, dry: bool = False) -> list[str]:
    now = time.time() if now is None else now
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    done = []
    for key, d, when, tag in plan_probes(items, state, now):
        h = hashlib.sha256(d.encode()).hexdigest()[:8]
        label = f"{PROBE_LABEL_PREFIX}.{h}.{time.strftime('%m%d%H%M', time.localtime(when))}"
        args = [sys.executable, str(Path(__file__).resolve()), "--probe", d, "--tag", tag]
        if not dry:
            p = LAUNCH_AGENTS / f"{label}.plist"
            with p.open("wb") as fh:
                plistlib.dump(_one_shot_plist(label, when, args), fh)
            subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], capture_output=True, timeout=20)
            state.setdefault(key, []).append({"label": label, "at": when, "tag": tag})
        done.append(f"⏰ 予約 {tag}: {d} を {_hm(when)} に問い合わせ ({label})")
    if done and not dry:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return done


def install_watch(uninstall: bool = False) -> int:
    p = LAUNCH_AGENTS / f"{WATCH_LABEL}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{WATCH_LABEL}"], capture_output=True)
    if uninstall:
        p.unlink(missing_ok=True)
        print(f"removed {WATCH_LABEL}")
        return 0
    log = str(HOME / "Library" / "Logs" / f"{WATCH_LABEL}.log")
    d = {"Label": WATCH_LABEL, "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), "--schedule-probes"],
         "StartInterval": 900, "RunAtLoad": True, "StandardOutPath": log, "StandardErrorPath": log}
    with p.open("wb") as fh:
        plistlib.dump(d, fh)
    rc = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], capture_output=True).returncode
    print(f"installed {WATCH_LABEL} (15 分ごと、 rc={rc})")
    return rc


# ── selftest ─────────────────────────────────────────────

def selftest() -> int:
    ok = fail = 0

    def ck(name, cond):
        nonlocal ok, fail
        print(("  PASS  " if cond else "  FAIL  ") + name)
        ok, fail = ok + bool(cond), fail + (not cond)

    ODA = "11111111-2222-4333-8444-555555555555"
    OKA = "66666666-7777-4888-9999-aaaaaaaaaaaa"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        logs = td / "logs"; logs.mkdir()
        # 実測の文言 (desktop app の main.log の形そのまま、 account は架空)
        (logs / "main.log").write_text(
            "2026-09-18 08:50:14 [info] [account] Navigated to /logout, synthesizing logged-out\n"
            f"2026-09-18 08:50:14 [info] [account] Login-state transition (loggedOut: false → true, uuid: {ODA} → <none>), clearing oauth cache\n"
            f"2026-09-18 08:50:57 [info] [account] Login-state transition (loggedOut: true → false, uuid: {ODA} → {OKA}), clearing oauth cache\n",
            encoding="utf-8")
        cron = td / ".claude-acct"; cron.mkdir()
        (cron / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": ODA, "emailAddress": "a@example.com"}}))
        other = td / ".claude-other"; other.mkdir()
        (other / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": OKA, "emailAddress": "b@example.com"}}))
        agents = td / "agents"; agents.mkdir()
        for name, d in (("job.a", cron), ("job.b", other)):
            with (agents / f"{name}.plist").open("wb") as fh:
                plistlib.dump({"Label": name, "ProgramArguments": ["/bin/sh", "-c", f'export CLAUDE_CONFIG_DIR="{d}"; exec claude -p x']}, fh)

        lo = logouts(logs)
        t_out = time.mktime(time.strptime("2026-09-18 08:50:14", "%Y-%m-%d %H:%M:%S"))
        ck("実例の文言からログアウトを拾う (account と時刻)", lo.get(ODA) == t_out)
        ck("ログインの行はログアウトと数えない", OKA not in lo)
        dirs = watched_dirs(agents)
        ck("plist の CLAUDE_CONFIG_DIR から対象フォルダを集める", set(dirs) == {str(cron), str(other)})

        before = t_out - 5 * 3600  # 9/18 03:50 の更新 (ログアウトより前)
        items = assess(dirs, lo, lambda d: before, [], now=t_out + 600)
        ck("実測の文言の例で 🔴 (更新がログアウトより前)", len(items) == 1 and items[0]["dir"] == str(cron))
        lines = render(items, "check-desktop-logout-auth.py")
        ck("🔴 の行に login の command と目安の時刻", lines and lines[0].startswith("🔴") and "claude auth login" in lines[0]
           and _hm(before + AT_LIFETIME_H * 3600) in lines[0])
        ck("別の account のフォルダは出さない", all(it["dir"] != str(other) for it in items))
        ck("ログアウト後に更新されていれば silent", assess(dirs, lo, lambda d: t_out + 60, [], now=t_out + 600) == [])
        ck("keychain が読めなければ silent (fail-open)", assess(dirs, lo, lambda d: None, []) == [])
        ck("desktop の log が無ければ silent", logouts(td / "nolog") == {})

        fail_row = [{"t": t_out + 7200, "tag": "verdict", "dir": str(cron), "ok": False}]
        it2 = assess(dirs, lo, lambda d: before, fail_row, now=t_out + 8000)
        ck("ログアウト後の問い合わせが失敗 = 「切れた」", it2 and it2[0]["state"] == "切れた" and "切れた" in render(it2, "x")[0])
        pass_row = [{"t": before + AT_LIFETIME_H * 3600 + 60, "tag": "verdict", "dir": str(cron), "ok": True}]
        it3 = assess(dirs, lo, lambda d: before, pass_row)
        ck("目安を過ぎた成功 = 🟡", it3 and it3[0]["state"] == "目安を過ぎても通った" and render(it3, "x")[0].startswith("🟡"))

        plan = plan_probes(items, {}, now=t_out + 600)
        ck("予約 = 直後 + 目安の 15 分後の 2 回", [p[3] for p in plan] == ["after-logout", "verdict"]
           and abs(plan[1][2] - (before + AT_LIFETIME_H * 3600 + VERDICT_MARGIN_MIN * 60)) < 1)
        ck("同じログアウトは 2 度予約しない", plan_probes(items, {plan[0][0]: [{}]}, now=t_out + 600) == [])
        late = plan_probes(items, {}, now=before + AT_LIFETIME_H * 3600 + 3600)
        ck("目安を過ぎてから見つけたら直後の 1 回だけ (それが判定になる)", [p[3] for p in late] == ["after-logout"])
        pl = _one_shot_plist("com.x.y", t_out, ["python3", "s.py", "--probe", "/d"])
        c = pl["ProgramArguments"][2]
        ck("予約は一回きり (plist を消してから最後に bootout = 順序が逆だと file が残る)",
           "rm -f" in c and "bootout" in c and c.index("rm -f") < c.index("bootout") and pl["StartCalendarInterval"]["Hour"] == 8)
        ck("keychain 項目名 = sha256(path) の先頭 8 桁", keychain_service("~/.claude-acct") == KEYCHAIN_PREFIX + "b50c49a0")
        ck("mdat の属性を UTC として読む", _MDAT_RE.search('"mdat"<timedate>=0x32303236  "20260923034324Z\\000"') is not None)
    print(f"selftest: {ok}/{ok + fail} passed")
    return 1 if fail else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--install-watch" in argv or "--uninstall-watch" in argv:
        return install_watch(uninstall="--uninstall-watch" in argv)
    if "--probe" in argv:
        i = argv.index("--probe")
        tag = argv[argv.index("--tag") + 1] if "--tag" in argv else "manual"
        return 0 if probe(argv[i + 1], tag) else 1
    if not (DESKTOP_LOG_DIR / "main.log").exists():
        return 0
    items = assess(watched_dirs(LAUNCH_AGENTS), logouts(DESKTOP_LOG_DIR),
                   lambda d: keychain_mdat(keychain_service(d)), read_ledger(LEDGER))
    for line in render(items, str(Path(__file__).resolve())):
        print(line)
    if "--schedule-probes" in argv:
        for line in schedule(items):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
