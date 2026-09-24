#!/usr/bin/env python3
"""desktop app でアカウントを切り替えた後、 同じ account の無人 job / RC の設定フォルダが切れていないかを自動で確かめる (切れたら 🔴)。

背景 (実測、 macOS の Claude desktop app + Claude Code CLI): desktop app で account X をログアウトした後、 同じ機械で
X として無人の `claude -p` / Remote Control が使う設定フォルダ (`CLAUDE_CONFIG_DIR`) が、 次にトークンの更新が要る時点で
`OAuth session expired and could not be refreshed` になった例がある。 ただし対照実験 (desktop で両 account のログアウトと
新しいログインを往復) では、 両方のフォルダが約 8 時間後の更新に成功した = ログアウトや新しいログインだけでは切れない。
原因は未確定なので、 切り替えのたびに問い合わせで確かめ、 **失敗したときだけ** 🔴 を出す (切り替えるだけで 🔴 は出さない)。
ログアウトの直後はアクセストークンが残っていて問い合わせが通るので、 更新が要る時刻の後にもう 1 回確かめる。
規約の正本 = conventions/scheduled-tasks.md#headless-auth-expiry。

  check-desktop-logout-auth.py                     # 表示だけ (dashboard / SessionStart 用。 切れたものだけ、 無ければ silent)
  check-desktop-logout-auth.py --verbose           # 確かめ中のものも出す
  check-desktop-logout-auth.py --schedule-probes   # 表示 + 未予約のログアウトに問い合わせを予約 + 長く更新の無いフォルダを今確かめる
  check-desktop-logout-auth.py --probe DIR [--tag T]   # DIR に最小の claude -p を 1 回、 結果を ledger に追記
  check-desktop-logout-auth.py --ensure-watch      # 見張りが無い・違う時だけ置く (config-bootstrap が毎 session 呼ぶ、 冪等)
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
  - 確かめ中 = そのフォルダの account の最新のログアウトが、 keychain の更新時刻より後 (= ログアウト以降、 更新も
    ログインも成功していない)。 更新が要る目安 = keychain の更新時刻 + AT_LIFETIME_H (desktop の Code タブのトークンが
    約 7h55m ごとに更新され、 実験でも更新から約 8 時間後の問い合わせで更新が走った)。 更新が成功すれば keychain の
    更新時刻がログアウトより後になり、 対象から外れる
  - 🔴 = 最後の問い合わせ (ledger = ~/.claude/state/desktop-logout-probe.log) が失敗し、 その後にログインし直して
    いないフォルダ (判定 = scripts/lib/config_dir_auth.py の is_dead、 heartbeat と共有)。 きっかけ (ログアウト / 毎日の
    確認) を問わない
  - 毎日の確認 (stale-check) = keychain が STALE_H 時間以上更新されず、 その間に問い合わせもしていないフォルダを、
    見張りが今確かめる (= ログアウトと無関係に切れた場合も 1 日以内に分かる。 RC しか使わないフォルダはここでしか確かめない)
  - 確かめ中で失敗の無いものは既定では出さない (--verbose で「確かめ中」 と出す)
  - 予約 = 直後に 1 回 (アクセストークンがその場で失効するか) + 目安 + 15 分に 1 回 (更新トークンが生きているか)。
    同じ (フォルダ, ログアウト時刻) には 1 度だけ (state = ~/.claude/state/desktop-logout-probe-state.json)。
    予約は一回だけ走って自分の plist を消す
  - desktop app の log が無い (desktop 未使用の機械 / 非 macOS) なら silent (fail-open、 exit 0)

⚠️ 限界: desktop app の log の文言が変わると検知が黙って止まる (selftest は固定の文言で見ている)。 他の機械での
ログアウトは見えない。 アクセストークンの寿命は推定。
"""
from __future__ import annotations

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
import config_dir_auth as cda  # noqa: E402  (keychain の更新時刻・問い合わせの記録・切れたかの判定 = heartbeat と共有)
from config_dir_auth import KEYCHAIN_PREFIX, keychain_mdat, keychain_service, _MDAT_RE  # noqa: E402,F401

HOME = Path.home()
DESKTOP_LOG_DIR = Path(os.environ.get("CLAUDE_DESKTOP_LOG_DIR", str(HOME / "Library" / "Logs" / "Claude")))
LAUNCH_AGENTS = Path(os.environ.get("CLAUDE_LOGOUT_AGENTS", str(HOME / "Library" / "LaunchAgents")))
STATE_DIR = Path(os.environ.get("CLAUDE_LOGOUT_STATE_DIR", str(HOME / ".claude" / "state")))
LEDGER = STATE_DIR / cda.LEDGER.name
STATE = STATE_DIR / "desktop-logout-probe-state.json"
AT_LIFETIME_H = 8
VERDICT_MARGIN_MIN = 15
STALE_H = 24  # これより長く keychain が更新されていないフォルダは、 見張りが 1 日 1 回問い合わせる
PROBE_MODEL = "claude-haiku-4-5-20251001"
PROBE_LABEL_PREFIX = "com.claude-config.logout-probe"
WATCH_LABEL = "com.claude-config.desktop-logout-watch"

_LOGOUT_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) .*Login-state transition \(loggedOut: false → true, uuid: ([0-9a-f-]+) → <none>\)")


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
    return cda.read_ledger(ledger)


def dead_dirs(dirs: dict[str, list[str]], mdat_of, rows: list[dict]) -> list[dict]:
    """最後の問い合わせが失敗し、 その後にログインし直していないフォルダ (きっかけを問わない)。"""
    out = []
    for d, labels in sorted(dirs.items()):
        r = cda.is_dead(rows, d, mdat_of(d))
        if r:
            out.append({"dir": d, "labels": labels, "t": r["t"], "tag": r["tag"]})
    return out


def plan_stale(dirs: dict[str, list[str]], mdat_of, rows: list[dict], now: float) -> list[str]:
    """keychain が STALE_H 時間以上更新されず、 その間に問い合わせもしていないフォルダ (= 使う人がいない or 切れている)。"""
    out = []
    for d in sorted(dirs):
        m = mdat_of(d)
        if m is None or now - m < STALE_H * 3600:
            continue
        last = cda.last_probe(rows, d)
        if last and now - last["t"] < STALE_H * 3600:
            continue
        out.append(d)
    return out


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


def render(items: list[dict], script: str, verbose: bool = False, dead: list[dict] | None = None) -> list[str]:
    """🔴 = 切れたフォルダ (dead_dirs、 きっかけを問わない)。 ⚪ = ログアウト後に確かめ中 (--verbose のときだけ)。"""
    lines = []
    for x in dead or []:
        lines.append(f"🔴 {x['dir']} ({len(x['labels'])} 本の launchd job が使う) は切れた ({_hm(x['t'])} の問い合わせ〔{x['tag']}〕が失敗し、"
                     f" その後ログインし直していない)。 直す = そのマシンで CLAUDE_CONFIG_DIR={x['dir']} claude auth login")
    dead_set = {x["dir"] for x in dead or []}
    for it in items:
        if verbose and it["dir"] not in dead_set:
            who = f"{it['dir']} ({len(it['labels'])} 本の launchd job が使う)"
            lines.append(f"⚪ 確かめ中: desktop で {it['email']} を {_hm(it['logout'])} にログアウトした後、 {who} の認証はまだ更新されていない"
                         f" (更新の目安 {_hm(it['verdict_at'])}、 状態 = {it['state']})。 今すぐ確かめる = python3 {script} --probe {it['dir']}")
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
                            "--body", f"認証の問い合わせが失敗 ({tag})。 直す = CLAUDE_CONFIG_DIR={config_dir} claude auth login"],
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


def _watch_plist() -> dict:
    log = str(HOME / "Library" / "Logs" / f"{WATCH_LABEL}.log")
    return {"Label": WATCH_LABEL, "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), "--schedule-probes"],
            "StartInterval": 900, "RunAtLoad": True, "StandardOutPath": log, "StandardErrorPath": log}


def ensure_watch() -> int:
    """見張りが無い・中身が違う・launchd に載っていない時だけ入れ直す (冪等、 何もしなければ無出力)。
    見張るフォルダ (launchd の job が使う CLAUDE_CONFIG_DIR) が 1 つも無い機械では何もしない。"""
    if not watched_dirs(LAUNCH_AGENTS):
        return 0
    p = LAUNCH_AGENTS / f"{WATCH_LABEL}.plist"
    want = _watch_plist()
    try:
        have = plistlib.load(p.open("rb"))
    except Exception:
        have = None
    loaded = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{WATCH_LABEL}"],
                            capture_output=True).returncode == 0
    if have == want and loaded:
        return 0
    return install_watch()


def install_watch(uninstall: bool = False) -> int:
    p = LAUNCH_AGENTS / f"{WATCH_LABEL}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{WATCH_LABEL}"], capture_output=True)
    if uninstall:
        p.unlink(missing_ok=True)
        print(f"removed {WATCH_LABEL}")
        return 0
    with p.open("wb") as fh:
        plistlib.dump(_watch_plist(), fh)
    rc = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], capture_output=True).returncode
    print(f"認証の見張りを置いた ({WATCH_LABEL}、 15 分ごと、 rc={rc})")
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

        before = t_out - 5 * 3600  # ログアウトの 5 時間前の更新
        items = assess(dirs, lo, lambda d: before, [], now=t_out + 600)
        ck("実測の文言の例で確かめ中に入る (更新がログアウトより前)", len(items) == 1 and items[0]["dir"] == str(cron))
        ck("確かめ中で失敗が無ければ既定では何も出さない (切り替えるだけで 🔴 にしない)",
           render(items, "check-desktop-logout-auth.py") == [])
        lines = render(items, "check-desktop-logout-auth.py", verbose=True)
        ck("--verbose では確かめ中を目安の時刻と問い合わせの command つきで出す",
           lines and lines[0].startswith("⚪") and "--probe" in lines[0] and _hm(before + AT_LIFETIME_H * 3600) in lines[0])
        ck("別の account のフォルダは出さない", all(it["dir"] != str(other) for it in items))
        ck("ログアウト後に更新されていれば silent", assess(dirs, lo, lambda d: t_out + 60, [], now=t_out + 600) == [])
        ck("keychain が読めなければ silent (fail-open)", assess(dirs, lo, lambda d: None, []) == [])
        ck("desktop の log が無ければ silent", logouts(td / "nolog") == {})

        fail_row = [{"t": t_out + 7200, "tag": "verdict", "dir": str(cron), "ok": False}]
        it2 = assess(dirs, lo, lambda d: before, fail_row, now=t_out + 8000)
        dd = dead_dirs(dirs, lambda d: before, fail_row)
        r2 = render(it2, "x", dead=dd)
        ck("ログアウト後の問い合わせが失敗 = 🔴 「切れた」 と login の command (1 行だけ)", it2 and it2[0]["state"] == "切れた"
           and len(r2) == 1 and r2[0].startswith("🔴") and "切れた" in r2[0] and "claude auth login" in r2[0])
        ck("--verbose でも切れたフォルダを確かめ中と二重に出さない", len(render(it2, "x", verbose=True, dead=dd)) == 1)
        ck("失敗の後にログインし直せば 🔴 は消える", dead_dirs(dirs, lambda d: t_out + 9000, fail_row) == [])
        # きっかけの無い切れ: ログアウトが無くても、 長く更新されていないフォルダを確かめて失敗したら 🔴
        now = t_out + 3 * 86400
        ck("keychain が 24 時間以上更新されず問い合わせも無いフォルダを確かめる",
           plan_stale(dirs, lambda d: now - 30 * 3600, [], now) == sorted(dirs))
        ck("最近更新されたフォルダは確かめない", plan_stale(dirs, lambda d: now - 3600, [], now) == [])
        recent = [{"t": now - 3600, "tag": "stale-check", "dir": d, "ok": True} for d in dirs]
        ck("24 時間以内に確かめたフォルダは確かめない", plan_stale(dirs, lambda d: now - 30 * 3600, recent, now) == [])
        ck("keychain が読めないフォルダは確かめない (fail-open)", plan_stale(dirs, lambda d: None, [], now) == [])
        stale_fail = [{"t": now, "tag": "stale-check", "dir": str(other), "ok": False}]
        r3 = render([], "x", dead=dead_dirs(dirs, lambda d: now - 30 * 3600, stale_fail))
        ck("毎日の確認の失敗も 🔴 (ログアウトと無関係に)", len(r3) == 1 and str(other) in r3[0] and "stale-check" in r3[0])
        global LAUNCH_AGENTS
        saved, LAUNCH_AGENTS = LAUNCH_AGENTS, td / "empty-agents"
        (td / "empty-agents").mkdir()
        try:
            ck("見張るフォルダが無い機械では見張りを置かない", ensure_watch() == 0
               and not (td / "empty-agents" / f"{WATCH_LABEL}.plist").exists())
        finally:
            LAUNCH_AGENTS = saved
        pass_row = [{"t": before + AT_LIFETIME_H * 3600 + 60, "tag": "verdict", "dir": str(cron), "ok": True}]
        it3 = assess(dirs, lo, lambda d: before, pass_row)
        ck("目安を過ぎた成功は既定では出さない", it3 and it3[0]["state"] == "目安を過ぎても通った" and render(it3, "x") == [])

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
    if "--ensure-watch" in argv:
        return ensure_watch()
    if "--install-watch" in argv or "--uninstall-watch" in argv:
        return install_watch(uninstall="--uninstall-watch" in argv)
    if "--probe" in argv:
        i = argv.index("--probe")
        tag = argv[argv.index("--tag") + 1] if "--tag" in argv else "manual"
        return 0 if probe(argv[i + 1], tag) else 1
    dirs = watched_dirs(LAUNCH_AGENTS)
    mdat_of = lambda d: keychain_mdat(keychain_service(d))  # noqa: E731
    rows = read_ledger(LEDGER)
    # ログアウトのきっかけは desktop app の log がある機械だけ (無ければ ログアウト由来の確かめ中は 0 件)
    last_out = logouts(DESKTOP_LOG_DIR) if (DESKTOP_LOG_DIR / "main.log").exists() else {}
    items = assess(dirs, last_out, mdat_of, rows)
    if "--schedule-probes" in argv:
        for line in schedule(items):
            print(line)
        # きっかけの無い切れ (原因不明の失効) も 1 日以内に見つける: 長く更新されていないフォルダを今確かめる
        for d in plan_stale(dirs, mdat_of, rows, time.time()):
            probe(d, "stale-check")
        rows = read_ledger(LEDGER)
    for line in render(items, str(Path(__file__).resolve()), verbose="--verbose" in argv,
                       dead=dead_dirs(dirs, mdat_of, rows)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
