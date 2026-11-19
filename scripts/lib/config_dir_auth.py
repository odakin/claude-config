"""Claude Code の設定フォルダ (CLAUDE_CONFIG_DIR) の認証が切れているかを、 `claude` を呼ばずに読む共有判定。

使い手 = scripts/check-desktop-logout-auth.py (問い合わせを打ち、 そのマシンで 🔴) と
scripts/fleet-heartbeat.py (判定を beat に載せ、 他のマシンの check-fleet-status.py が 🔴)。
heartbeat は `claude` を呼ばない設計なので (監視が監視対象と共倒れしないため)、 ここも `security` と file しか読まない。

述語 (= code-as-SoT):
  - keychain の項目 = KEYCHAIN_PREFIX + sha256(設定フォルダの path) の先頭 8 桁 (実測で一致)。 更新時刻 (mdat) は
    `security find-generic-password -s <項目>` の属性だけを読む (値は読まない)。 トークンの更新やログインが
    成功すると mdat が進む。 ⚠️ 更新の失敗でも、 切れた最初の 1 回だけ進む (実測 = 失敗した問い合わせ 12 回のうち
    動いたのは最初の 1 回、 2 回目以降の失敗では動かない) = 失敗の後に進めばログインか更新の成功と読めるが、
    「ログアウトの後に進んだ」 だけでは生きていると読めない (check-desktop-logout-auth.py の assess が扱う)
  - 問い合わせの記録 (LEDGER、 1 行 = 時刻 TAB tag TAB フォルダ TAB ok|FAIL(...)|UNKNOWN(...) TAB ...) は
    check-desktop-logout-auth.py --probe が書く。 UNKNOWN = 答えが出なかった (CLI が無い・時間切れ = 許可 dialog に
    止められた等) で、 認証の成否を言わない = 読むときに飛ばす (2026-10-30 実測: dialog で時間切れになった問い合わせを
    FAIL と記録し、 切れていないフォルダを 🔴 にした)
  - 切れた (dead) = そのフォルダの最後の問い合わせが失敗 ∧ その後に keychain が更新されていない
    (= ログインし直していない、 更新も成功していない)。 問い合わせが無い・keychain が読めないなら判定しない
  - 続いている失敗 (failure_run) = 最後の問い合わせから遡って続く失敗の回数と、 その最初の行・その前に通った行。
    問い合わせは切れた瞬間を見ていない = 最初の失敗は「遅くともこの時刻には切れていた」 を言う
  - 使い手 (dir_uses) = そのフォルダを CLAUDE_CONFIG_DIR に持つ launchd job (~/Library/LaunchAgents/*.plist) の区分ごとの
    本数。 区分 (use_kind) = "rc" (起動行が `claude remote-control` = Remote Control のサーバー) / "gated" (起動行が本番
    ホストの関門 routine-host-gate.py を通る定期実行) / "other" (それ以外)。 RC の判定を関門より先に見る
  - 待機中の機械でだけ使われる (standby_only) = この機械が本番ホストでない ∧ 使い手が関門つきの定期実行だけ。 切れても
    この機械で止まるものが無いので 🔴 から外し、 本番を切り替える手順 (台帳を書き換える道具) の側で確かめる。 使い手の数が
    無い (旧 beat) か本番ホストかが分からない (台帳が読めない) なら外さない (= 今どおり出す)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import subprocess
import time
from pathlib import Path

KEYCHAIN_PREFIX = "Claude Code-credentials-"
LEDGER = Path.home() / ".claude" / "state" / "desktop-logout-probe.log"
_MDAT_RE = re.compile(r'"mdat"<timedate>=0x[0-9A-F]*\s+"(\d{14})Z')
_RC_RE = re.compile(r'\bclaude"?\s+remote-control(?=[\s"\';]|$)')
USE_KINDS = ("rc", "gated", "other")


def keychain_service(config_dir: str) -> str:
    return KEYCHAIN_PREFIX + hashlib.sha256(config_dir.encode()).hexdigest()[:8]


def keychain_mdat(service: str) -> float | None:
    """keychain 項目の更新時刻 (epoch)。 属性だけ読む。 無い・読めない・security が無いなら None。"""
    try:
        cp = subprocess.run(["security", "find-generic-password", "-s", service],
                            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    m = _MDAT_RE.search(cp.stdout + cp.stderr)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()


def read_ledger(ledger: Path = LEDGER) -> list[dict]:
    """問い合わせの記録。 読めない行は飛ばす。 各要素 = {t, tag, dir, ok}。"""
    rows = []
    try:
        text = ledger.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or parts[3].startswith("UNKNOWN"):
            continue
        try:
            t = time.mktime(time.strptime(parts[0], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        rows.append({"t": t, "tag": parts[1], "dir": parts[2], "ok": parts[3] == "ok"})
    return rows


def last_probe(rows: list[dict], config_dir: str) -> dict | None:
    mine = [r for r in rows if r["dir"] == config_dir]
    return max(mine, key=lambda r: r["t"]) if mine else None


def is_dead(rows: list[dict], config_dir: str, mdat: float | None) -> dict | None:
    """切れていれば最後の (失敗した) 問い合わせ、 そうでなければ None。"""
    r = last_probe(rows, config_dir)
    if r is None or r["ok"]:
        return None
    if mdat is not None and mdat > r["t"]:
        return None  # 失敗の後にログインし直した / 更新が成功した
    return r


def failure_run(rows: list[dict], config_dir: str) -> dict | None:
    """最後の問い合わせから遡って続いている失敗 = {first: 最初の失敗の行, n: 回数, last_ok: その前に通った行か None}。
    最後が成功・問い合わせ無し = None。"""
    run, last_ok = [], None
    for r in sorted((r for r in rows if r["dir"] == config_dir), key=lambda r: r["t"], reverse=True):
        if r["ok"]:
            last_ok = r
            break
        run.append(r)
    return {"first": run[-1], "n": len(run), "last_ok": last_ok} if run else None


def use_kind(plist: dict | None) -> str:
    """launchd job 1 本が設定フォルダをどう使うか ("rc" / "gated" / "other"、 docstring の「使い手」)。"""
    import launchd_job_log as jl  # 同じ lib/ (起動行の読み方と関門の判定は launchd_job_log が持つ)
    if _RC_RE.search(jl._command(plist)):
        return "rc"
    return "gated" if jl.is_gated(plist) else "other"


def _norm_dir(d: str, home: Path) -> str:
    for h in ("${HOME}", "$HOME"):
        if d.startswith(h):
            d = str(home) + d[len(h):]
    if d == "~" or d.startswith("~/"):
        d = str(home) + d[1:]
    return d.rstrip("/") if d.startswith("/") else ""


def dir_uses(agents_dir: Path, home: Path | None = None) -> dict[str, dict[str, int]]:
    """設定フォルダ (絶対 path) → {"rc": n, "gated": n, "other": n} (それを CLAUDE_CONFIG_DIR に持つ launchd job の本数)。
    plist が読めない・CLAUDE_CONFIG_DIR が無い job は数えない。 dir が無い・読めないなら空。"""
    import launchd_job_log as jl
    home = home or Path.home()
    out: dict[str, dict[str, int]] = {}
    try:
        plists = sorted(Path(agents_dir).glob("*.plist"))
    except OSError:
        return out
    for p in plists:
        pl = jl.load_plist(p)
        d = _norm_dir(jl.config_dir_of(pl), home)
        if not d:
            continue
        u = out.setdefault(d, {k: 0 for k in USE_KINDS})
        u[use_kind(pl)] += 1
    return out


def standby_only(uses: dict | None, active: bool | None) -> bool:
    """本番でない機械で、 関門つきの定期実行だけが使う設定フォルダか (docstring の「待機中の機械でだけ使われる」)。
    active = この機械が本番ホストか (分からなければ None)。 分からない・数が無いなら False (= 今どおり出す)。"""
    if active is not False or not isinstance(uses, dict):
        return False
    return uses.get("gated", 0) > 0 and not uses.get("rc", 0) and not uses.get("other", 0)


def selftest() -> int:
    fails = 0

    def ck(name, cond):
        nonlocal fails
        print(("  PASS  " if cond else "  FAIL  ") + name)
        fails += not cond

    d = "~/.claude-acct"
    rows = [{"t": 100.0, "tag": "a", "dir": d, "ok": True}, {"t": 200.0, "tag": "b", "dir": d, "ok": False},
            {"t": 150.0, "tag": "c", "dir": "~/.claude-other", "ok": False}]
    ck("最後の問い合わせが失敗 ∧ その後の更新なし = 切れた", is_dead(rows, d, 150.0)["tag"] == "b")
    ck("失敗の後に keychain が更新された = 切れていない (ログインし直した)", is_dead(rows, d, 250.0) is None)
    ck("keychain が読めなくても失敗は切れたと数える", is_dead(rows, d, None) is not None)
    ck("最後が成功なら切れていない", is_dead(rows + [{"t": 300.0, "tag": "d", "dir": d, "ok": True}], d, 150.0) is None)
    ck("問い合わせの無いフォルダは判定しない", is_dead(rows, "~/.claude-none", 0.0) is None)
    run = failure_run(rows + [{"t": 260.0, "tag": "e", "dir": d, "ok": False}, {"t": 230.0, "tag": "f", "dir": d, "ok": False}], d)
    ck("続いている失敗 = 最初の失敗・回数・その前に通った行 (記録の順に依らない)",
       run["first"]["tag"] == "b" and run["n"] == 3 and run["last_ok"]["tag"] == "a")
    ck("成功の後の失敗だけを数える", failure_run(rows + [{"t": 250.0, "tag": "g", "dir": d, "ok": True},
                                                          {"t": 270.0, "tag": "h", "dir": d, "ok": False}], d)["n"] == 1)
    ck("その前に通った記録が無ければ last_ok は None", failure_run([rows[2]], "~/.claude-other")["last_ok"] is None)
    ck("最後が成功・問い合わせ無しは None", failure_run(rows[:1], d) is None and failure_run(rows, "~/.claude-none") is None)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        led = Path(td) / "probe.log"
        led.write_text(f"2026-10-30 07:00:00\tverdict\t{d}\tok\tx\tOK\n"
                       f"2026-10-30 09:38:06\tafter-logout\t{d}\tUNKNOWN(rc=99)\tx\tprobe error: timeout\n", encoding="utf-8")
        got = read_ledger(led)
        ck("答えが出なかった問い合わせ (UNKNOWN) は飛ばす = 前の成功で判定する",
           len(got) == 1 and got[0]["ok"] and is_dead(got, d, None) is None)
    ck("keychain 項目名 = sha256(path) の先頭 8 桁",
       keychain_service(d) == KEYCHAIN_PREFIX + hashlib.sha256(d.encode()).hexdigest()[:8])
    ck("mdat の属性を UTC として読む", _MDAT_RE.search('"mdat"<timedate>=0x32303236  "20260923034324Z\\000"') is not None)
    # 使い手の区分と、 待機中の機械でだけ使われるフォルダ
    import plistlib
    rc_pl = {"ProgramArguments": ["/bin/sh", "-c", 'export CLAUDE_CONFIG_DIR="/h/.claude-a"; exec claude remote-control --name x']}
    gated_pl = {"ProgramArguments": ["/bin/sh", "-c", 'export CLAUDE_CONFIG_DIR="$HOME/.claude-b"; '
                                     'python3 "$HOME/Claude/claude-config/scripts/routine-host-gate.py" r l && exec claude -p x']}
    other_pl = {"ProgramArguments": ["/bin/sh", "-c", 'export CLAUDE_CONFIG_DIR="/h/.claude-b"; exec claude -p y']}
    ck("区分 = RC のサーバー / 関門つき / それ以外",
       (use_kind(rc_pl), use_kind(gated_pl), use_kind(other_pl)) == ("rc", "gated", "other"))
    ck("`remote-control` を語の中に含むだけの起動行は RC にしない",
       use_kind({"ProgramArguments": ["/bin/sh", "-c", "exec claude remote-controlled -p x"]}) == "other")
    with tempfile.TemporaryDirectory() as td2:
        la = Path(td2)
        for name, pl in (("r", rc_pl), ("g", gated_pl), ("g2", gated_pl), ("o", other_pl),
                         ("none", {"ProgramArguments": ["/bin/sh", "-c", "exec true"]})):
            with open(la / f"{name}.plist", "wb") as fh:
                plistlib.dump(pl, fh)
        (la / "broken.plist").write_text("not a plist", encoding="utf-8")
        got = dir_uses(la, home=Path("/h"))
        ck("フォルダごとの使い手の数 ($HOME を展開、 CLAUDE_CONFIG_DIR の無い job と壊れた plist は数えない)",
           got == {"/h/.claude-a": {"rc": 1, "gated": 0, "other": 0}, "/h/.claude-b": {"rc": 0, "gated": 2, "other": 1}})
        ck("読めない dir は空", dir_uses(la / "missing", home=Path("/h")) == {})
    g_only = {"rc": 0, "gated": 3, "other": 0}
    ck("本番でない機械 ∧ 関門つきだけ = 待機中だけ", standby_only(g_only, active=False))
    ck("本番ホストなら外さない", not standby_only(g_only, active=True))
    ck("本番ホストか分からない (台帳が読めない) なら外さない", not standby_only(g_only, active=None))
    ck("RC のサーバーも使うなら外さない", not standby_only({"rc": 1, "gated": 3, "other": 0}, active=False))
    ck("関門なしの job も使うなら外さない", not standby_only({"rc": 0, "gated": 3, "other": 1}, active=False))
    ck("使い手の数が無い (旧 beat) ・使い手が居ないなら外さない",
       not standby_only(None, active=False) and not standby_only({"rc": 0, "gated": 0, "other": 0}, active=False))
    print(f"config_dir_auth selftest: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
