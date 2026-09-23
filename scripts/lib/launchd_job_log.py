"""launchd の無人ジョブについて「直近の run が既知の形で失敗したか」 を log 末尾から読む共有判定。

使い手 = scripts/check-cron-health.py (そのマシンの horizon) と scripts/fleet-heartbeat.py (他マシンへの beat)
→ scripts/check-fleet-status.py (reader)。 判定をここ 1 か所に置き、 3 者が同じ述語で話す。

なぜ終了コードだけでは足りないか (正本 = conventions/scheduled-tasks.md#reload-resets-exit-status):
  - launchd は plist を読み込み直した job の `launchctl list` の終了コードを 0 にする (次に走るまで)。
    失敗した run の後に plist が書き直されると、 失敗は exit 0 の顔になり、 終了コードだけ見る検出器から消える (実測)。
  - 終了コードは「失敗した」 しか言わず、 なぜかを言わない。 headless `claude -p` の routine は、 config dir の
    認証が切れると全部が起動直後に同じ文言で終わる (conventions/scheduled-tasks.md#headless-auth-expiry)。

述語 (= code-as-SoT):
  - log 末尾 LOG_TAIL_LINES 行 ≈ 直近 run の出力の終わり。 log は plist の StandardErrorPath → StandardOutPath →
    <log_dir>/<label>.log の順で探す
  - failure_kind: 末尾に AUTH_MARKERS のどれか = "auth" / "Prompt is too long" = "ptl" / それ以外 = ""
  - hidden_failure: 終了コードが 0 ∧ failure_kind ≠ "" ∧ log の更新が HIDDEN_FAIL_DAYS 日以内
    (= 古い log の末尾は「直近の run」 とは限らないので拾わない)
  - config_dir_of: plist の起動行の `CLAUDE_CONFIG_DIR=` (EnvironmentVariables も見る)
  - logged_in_email: その config dir が今 claude.ai でログイン済みなら email (= `claude auth status` を読むだけ)
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import time
from pathlib import Path

LOG_TAIL_LINES = 6
# Claude CLI が認証切れで起動直後に終わるときの文言 (どれか 1 つが log 末尾にあれば認証切れ)
AUTH_MARKERS = ("Failed to authenticate", "OAuth session expired", "Not logged in",
                "Please run /login", "Invalid API key")
PTL_MARKER = "Prompt is too long"
HIDDEN_FAIL_DAYS = 3

_CONFIG_DIR_RE = re.compile(r'CLAUDE_CONFIG_DIR="?([^";\s]+)')


def load_plist(path) -> dict | None:
    try:
        with open(path, "rb") as fh:
            d = plistlib.load(fh)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def job_log_path(label: str, plist: dict | None, log_dir) -> Path:
    """job の log の path。 plist が stderr / stdout の行き先を持てばそれ、 無ければ <log_dir>/<label>.log。"""
    for k in ("StandardErrorPath", "StandardOutPath"):
        v = (plist or {}).get(k)
        if isinstance(v, str) and v:
            return Path(os.path.expanduser(v))
    return Path(log_dir) / f"{label}.log"


def log_tail(path, n: int = LOG_TAIL_LINES) -> list[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def failure_kind(path) -> str:
    """log 末尾の既知の失敗: 'auth' / 'ptl' / ''。"""
    tail = log_tail(path)
    if any(m in line for line in tail for m in AUTH_MARKERS):
        return "auth"
    if any(PTL_MARKER in line for line in tail):
        return "ptl"
    return ""


def log_age_days(path, now: float | None = None) -> float | None:
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return None
    return ((now if now is not None else time.time()) - mtime) / 86400.0


def hidden_failure(last_exit, path, now: float | None = None) -> bool:
    """終了コードは 0 なのに、 直近の run の log 末尾が既知の失敗 (= 読み込み直しで 0 に戻った)。"""
    if last_exit != 0 or not failure_kind(path):
        return False
    age = log_age_days(path, now)
    return age is not None and 0 <= age < HIDDEN_FAIL_DAYS


def config_dir_of(plist: dict | None) -> str:
    """plist の起動行 (または EnvironmentVariables) の CLAUDE_CONFIG_DIR。 無ければ空文字。"""
    if not isinstance(plist, dict):
        return ""
    env = plist.get("EnvironmentVariables") or {}
    if isinstance(env, dict) and env.get("CLAUDE_CONFIG_DIR"):
        return str(env["CLAUDE_CONFIG_DIR"])
    m = _CONFIG_DIR_RE.search(" ".join(str(a) for a in (plist.get("ProgramArguments") or [])))
    return m.group(1) if m else ""


def logged_in_email(config_dir: str, claude: str = "claude", timeout: int = 8) -> str:
    """config dir が今 claude.ai でログイン済みなら email (未ログイン・判定不能なら空文字)。 読むだけ。

    実在する絶対 path だけ問う (= 架空の dir で CLI を起動しない)。 env の API key は外して問う
    (混入すると auth status が別の答えを返す、 conventions/remote-control-server.md#local-auth-triage)。"""
    if not config_dir.startswith("/") or not os.path.isdir(config_dir):
        return ""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
    env["CLAUDE_CONFIG_DIR"] = config_dir
    try:
        cp = subprocess.run([claude, "auth", "status"], capture_output=True, text=True, timeout=timeout, env=env)
        st = json.loads(cp.stdout)
    except Exception:
        return ""
    if st.get("loggedIn") and st.get("authMethod") == "claude.ai":
        return st.get("email") or "(email 不明)"
    return ""


def selftest() -> int:
    import tempfile
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        pl = {"ProgramArguments": ["/bin/sh", "-c", 'export CLAUDE_CONFIG_DIR="/x/.claude-a"; exec claude -p x'],
              "StandardErrorPath": str(d / "custom.log")}
        (d / "custom.log").write_text("warn\nFailed to authenticate: OAuth session expired\n")
        ck("plist の StandardErrorPath を使う", job_log_path("j", pl, d) == d / "custom.log")
        ck("plist 無しは <log_dir>/<label>.log", job_log_path("j", None, d) == d / "j.log")
        ck("auth を拾う", failure_kind(d / "custom.log") == "auth")
        (d / "p.log").write_text("x\nPrompt is too long\n")
        ck("ptl を拾う", failure_kind(d / "p.log") == "ptl")
        (d / "ok.log").write_text("Not logged in (昔の run)\n" + "ok\n" * 8)
        ck("末尾の外の昔の失敗は拾わない", failure_kind(d / "ok.log") == "")
        ck("log 不在は空", failure_kind(d / "none.log") == "" and log_age_days(d / "none.log") is None)
        t0 = (d / "custom.log").stat().st_mtime
        ck("exit 0 + 直近 log が失敗 = hidden", hidden_failure(0, d / "custom.log", now=t0 + 3600))
        ck("exit 1 は hidden でない (= 普通の失敗)", not hidden_failure(1, d / "custom.log", now=t0 + 3600))
        ck("古い log は hidden にしない", not hidden_failure(0, d / "custom.log", now=t0 + 86400 * 10))
        ck("起動行の CLAUDE_CONFIG_DIR", config_dir_of(pl) == "/x/.claude-a")
        ck("EnvironmentVariables の CLAUDE_CONFIG_DIR",
           config_dir_of({"EnvironmentVariables": {"CLAUDE_CONFIG_DIR": "/y"}}) == "/y")
        ck("plist 無しは空", config_dir_of(None) == "")
        ck("架空 / 相対の dir は auth status を叩かない",
           logged_in_email("/nonexistent/.claude-z") == "" and logged_in_email("rel") == "")
        with open(d / "j.plist", "wb") as fh:
            plistlib.dump(pl, fh)
        ck("load_plist", (load_plist(d / "j.plist") or {}).get("StandardErrorPath") == str(d / "custom.log"))
        ck("load_plist 不在は None", load_plist(d / "no.plist") is None)
    for name, c in ok:
        print(f"  {'PASS' if c else 'FAIL'}  {name}")
    n = sum(1 for _, c in ok if c)
    print(f"launchd_job_log selftest: {n}/{len(ok)} passed")
    return 0 if n == len(ok) else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest() if "--selftest" in sys.argv else 0)
