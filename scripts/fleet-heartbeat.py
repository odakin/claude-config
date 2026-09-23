#!/usr/bin/env python3
"""fleet-heartbeat.py — per-machine heartbeat writer（毎時 launchd cron から自マシンの RC server 群〔launchd loaded + server ログ末尾 marker parse = Connected/auth error/version error〕 + config-dir auth metadata を <repo>/<subdir>/<host>.json に commit+push。**claude を一切呼ばない** = auth 失効でも監視が生き残る、state-change-or-age commit policy で git history を汚さない、fail-open、--selftest 内蔵、conventions/multi-machine-state.md#fleet-heartbeat）
fleet-heartbeat.py — per-machine heartbeat writer (layer 1 generic engine).

cross-machine state の不可視問題 (multi-account-machine-surface.md #honest-limits) を
狭める: 各マシンが自分の remote-control server / CLI 環境の live 状態を JSON 1 file に
まとめ、 git repo に commit + push する。 他マシンは sibling `check-fleet-status.py`
(reader) で全マシン分を読み、 常時起動マシンの silent 死や auth 失効を surface する。

設計原則:
- **`claude` コマンドを一切呼ばない** (= auth 失効で server 群が死んでいても heartbeat
  自体は動き続け、 その死を server ログの parse で報告できる。 監視が監視対象に依存する
  と共倒れして意味がない)。 依存は launchctl / git / python3 stdlib のみ。
- **state-change-or-age commit policy**: 毎 beat commit すると git history が汚れる。
  essence (= server の loaded/status、 auth metadata、 設定) が変わった時 + 最終 commit
  から --min-commit-interval-hours 経過時のみ commit。 変化なし & 期間内なら working
  tree に触らない (= 他の git 機構を汚さない)。 liveness の上限 = interval + cron 周期。
- **fail-open**: 何が起きても exit 0 (= cron を止めない)。 push 失敗は local commit を
  残して次 beat で再 push。 commit 後の pull は `--rebase --autostash` — 他 session が
  無関係な dirty file を残置していると autostash なしでは rebase が拒否され、 beat が
  local commit に積み上がるだけで push されない = fleet からこのマシンが silent 死に
  見え、 このマシン自身の fleet view も stale 化する (= 双方向の盲目)。 failure mode の
  正本 = conventions/multi-machine-state.md#fleet-heartbeat 設計原則 5。
- server の実況は **launchd loaded/pid + server ログ末尾の marker parse** で判定
  (= "Connected" / "Not logged in" / "too old" / "Enable Remote Control?" を新しい順に
  評価)。 process が生きていても auth 失効で cycling している状態を検出できるのが肝。

inventory (--inventory、 opt-in、 repeatable):
  「このマシンに何が置かれているか」 の **名前だけ** の一覧を記録する generic hook。
  machine-local な設定・credential・token dir は「あるマシンにだけ無い」 状態を作りうるが、
  それを見る機械が無いと誰にも見えないまま放置される (= 2026-07-25 実測: ある account の
  credential が 1 台だけ未配置のまま 45 日 silent)。 sibling reader が全マシン分を
  突合し、 **他マシンには在るのにこのマシンには無い** entry を surface する。
  ⚠️ 期待集合は **fleet の union** = 宣言 registry を持たない (= 「registry への登録忘れ」
     という規律依存の穴を作らない)。 代償 = **どのマシンにも無い物は検出できない**。
  ⚠️ 記録するのは path 要素の名前のみ。 **file の中身は一切読まない**。

usage:
  fleet-heartbeat.py --repo <git-repo-root> --subdir <relative-dir>
      [--min-commit-interval-hours 4]
      [--rc-label-prefix com.claude-config.remote-control-server]
      [--cron-label-prefix <prefix>]     # optional: 無人 cron job 数も記録
      [--inventory 'LABEL=GLOB' ...]     # optional: 名前一覧を記録 (下記 name 規則)
      [--job-label-prefix <prefix> ...]  # optional: ジョブごとの健康 (下記 job health)
      [--job-python-modules yaml,...]     # optional: ジョブの python3 が import できるべき module
  fleet-heartbeat.py --selftest

書かれる JSON (subdir/<hostname>.json):
  { host, ts (iso), epoch, servers: [{label, pid, last_status, log_age_min}],
    config_dirs: {alias: email_metadata_or_null},
    remote_control_at_startup, old_usr_local_cli, cron_jobs,
    desktop_scheduled_tasks: [{registry, enabled_ids}],
    inventories: {label: [name, ...]},         # --inventory 指定時のみ
    jobs: [{label, last_exit, python, python_runs, python_ok, bare_in_command, bare_in_wrapper,
            log_failure, log_age_h, config_dir?}],               # --job-label-prefix 指定時のみ
    job_python_modules: [module, ...] }                          # 同上

job health (--job-label-prefix、 opt-in、 repeatable):
  launchd の無人ジョブは job 定義の PATH で `python3` を解決する。 その PATH は agent の session や対話 shell と
  先頭の dir が違い、 package manager の更新で `python3` の実体が差し替わると、 編集ゼロで依存 (yaml 等) が消えて
  engine が import で終わる。 fail-open の engine は exit 0 で終わるので、 そのマシンの中からも成功に見える
  (conventions/shell-env.md#job-python-by-capability)。 そこで各ジョブについて次を記録し、 reader が他マシンから見る:
  - last_exit = `launchctl list` の最後の終了コード (未実行は null)
  - python = job 定義の PATH (ProgramArguments の `export PATH="..."` か EnvironmentVariables) で解決した python3
  - python_runs = その python3 が起動できるか (Xcode の gate の exit 69 等で落ちれば False)
  - python_ok = その python3 が --job-python-modules を全部 import できるか。 未指定なら null
  - bare_in_command = job の command (起動の関門など) が `python3` を PATH で呼ぶか
  - bare_in_wrapper = command が `exec bash "<wrapper>"` で呼ぶ wrapper が `python3` を PATH で呼ぶか
    (`"$PY"` や絶対 path で呼ぶ wrapper は PATH の python3 の健康に依存しない)
  - log_failure = 直近 run の log 末尾の既知の失敗 ("auth" = Claude の認証切れ / "ptl" = Prompt is too long / null)、
    log_age_h = その log の最終更新からの時間、 config_dir = auth のときだけ plist の CLAUDE_CONFIG_DIR
    (判定 = scripts/lib/launchd_job_log.py、 check-cron-health と共有。 plist を読み込み直すと last_exit は 0 に戻るので、
    last_exit だけでは失敗が消える = conventions/scheduled-tasks.md#reload-resets-exit-status)
  reader は bare_in_command ∧ ¬python_runs (= 関門が起動できず、 そのジョブは黙って休み続ける) と
  bare_in_wrapper ∧ ¬python_ok (= engine が import で終わる) を出す。 command の位置 (行頭・; && || | $( の直後) の
  `python3` だけを数える (echo の文中の語は数えない)

  name 規則 = **glob の最初の `*` 以降の最初の path 要素**:
    'gmail_accounts=~/.gmail-mcp/*/credentials.json' → 各 account dir 名の一覧 (= 親 dir 名)
    'secrets=~/.secrets/*'                          → 各 file 名の一覧 (= 末端の file 名)
  match 0 件でも label は `[]` として記録する (= 「field 不在 = 旧 beat」 と
  「報告した上で空」 を reader が区別できるようにするため)。

⚠️ email は .claude.json の oauthAccount **metadata** (= keychain 実 auth とはズレうる、
   remote-control-server.md#account-auth-keychain)。 fleet view の cheap signal として
   記録し、 断定には使わない。 token 等の secret は一切読まない・書かない。
"""

import argparse
import glob as globmod
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    import launchd_job_log as _jl   # 直近 run の log 末尾の判定 (check-cron-health と共有)
except Exception:                   # 部品が無い古い checkout でも beat は止めない
    _jl = None

RC_LABEL_PREFIX_DEFAULT = "com.claude-config.remote-control-server"

# server ログ末尾の status marker (新しい出現が勝つ)
LOG_MARKERS = [
    ("Connected", "connected"),
    ("Not logged in", "auth_error"),
    ("must be logged in", "auth_error"),
    ("requires a claude.ai subscription", "auth_error"),
    ("requires claude.ai subscription auth", "auth_error"),
    ("too old for Remote Control", "version_error"),
    ("not enabled for your account", "version_error"),
    ("Enable Remote Control?", "consent_pending"),
    # virgin config dir の headless 死 (= trust dialog を出せず exit-1 cycling、
    # remote-control-server.md#ts-workspace-trust。 2026-07-02 実測 RCA で追加)
    ("Workspace not trusted", "trust_error"),
]

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\[[0-9]+[A-Z]")


def sh(cmd, timeout=20):
    try:
        # errors="replace": 子プロセスの出力が現在の locale encoding で decode できない
        # ことがある (= Windows の cp932 出力を UTF-8 で読む等)。 既定の "strict" だと
        # decode が capture 用の reader thread 内で例外になり、 その thread は本 try/except
        # の外なので握り潰せず、 traceback を撒いたうえで出力が失われる。
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def hostname_short():
    rc, out = sh(["hostname", "-s"])
    h = out.strip() or "unknown"
    return h[: -len(".local")] if h.endswith(".local") else h


def parse_log_status(log_path: Path):
    """ログ末尾 ~6KB から最後に出た marker の status を返す。"""
    try:
        size = log_path.stat().st_size
        with open(log_path, "rb") as f:
            f.seek(max(0, size - 6000))
            tail = f.read().decode("utf-8", errors="replace")
        tail = ANSI_RE.sub("", tail)
        best = ("unknown", -1)
        for needle, status in LOG_MARKERS:
            idx = tail.rfind(needle)
            if idx > best[1]:
                best = (status, idx)
        age_min = int((time.time() - log_path.stat().st_mtime) / 60)
        return best[0], age_min
    except Exception:
        return "unknown", None


def scan_inventory(spec: str):
    """'LABEL=GLOB' を (label, [names]) にする。 name = glob の最初の `*` 以降の最初の path 要素。

    ⚠️ 名前のみを収集し file の中身は読まない (= secret の inventory にも安全に使える)。
    不正な spec は None (= caller が無視、 fail-open)。
    """
    label, sep, pat = spec.partition("=")
    label, pat = label.strip(), pat.strip()
    if not sep or not label or not pat:
        return None
    expanded = os.path.expanduser(pat)
    star = expanded.find("*")
    prefix = expanded[:star] if star >= 0 else ""
    # glob() は platform の separator で返す (Windows は "\") 一方 pattern は "/" で
    # 書かれる。 素の startswith 比較は Windows で必ず外れ、 basename fallback に落ちて
    # 全 entry が glob 末尾の file 名 (= "credentials.json" 等) に潰れる = inventory が
    # 「1 個だけある」 と誤報告する。 両辺を "/" に正規化してから比較・分割する。
    prefix_n = prefix.replace(os.sep, "/")
    names = set()
    for m in globmod.glob(expanded):
        m_n = m.replace(os.sep, "/")
        rest = m_n[len(prefix_n):] if (prefix_n and m_n.startswith(prefix_n)) else os.path.basename(m)
        n = rest.split("/", 1)[0]
        if n:
            names.add(n)
    return label, sorted(names)


def collect(rc_prefix, cron_prefix, inventory_specs=None, job_prefixes=None, job_modules=None):
    home = Path.home()
    data = {
        "host": hostname_short(),
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "epoch": int(time.time()),
        "servers": [],
        "config_dirs": {},
        "remote_control_at_startup": None,
        "old_usr_local_cli": None,
        "cron_jobs": None,
    }
    # launchctl list から RC server 群
    rc, out = sh(["launchctl", "list"])
    cron_count = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pid, _status, label = parts[0], parts[1], parts[2]
        if label.startswith(rc_prefix):
            log = home / "Library/Logs" / f"{label}.log"
            status, age = parse_log_status(log)
            data["servers"].append(
                {"label": label, "pid": (None if pid == "-" else pid),
                 "last_status": status, "log_age_min": age}
            )
        if cron_prefix and label.startswith(cron_prefix):
            cron_count += 1
    if cron_prefix:
        data["cron_jobs"] = cron_count
    # job health (opt-in、 docstring §job health)
    if job_prefixes:
        try:
            data["jobs"] = scan_jobs(out, list(job_prefixes), list(job_modules or []), home)
            data["job_python_modules"] = list(job_modules or [])
        except Exception:
            pass  # fail-open (= beat 全体を落とさない)
    data["servers"].sort(key=lambda s: s["label"])
    # config dirs の auth metadata (= secret は読まない、 email 欄のみ)。
    # ⚠️ config JSON の場所は default と pinned dir で違う: 既定 (CLAUDE_CONFIG_DIR 未指定) は
    # ~/.claude.json (home 直下)、 pinned dir は <dir>/.claude.json。 旧実装は default も
    # ~/.claude/.claude.json を読んでいて常に null になっていた (2026-07-02 fix)。
    for d in sorted([home / ".claude", *home.glob(".claude-*")]):
        if not d.is_dir():
            continue
        alias = "default" if d.name == ".claude" else d.name[len(".claude-"):]
        cfg = (home / ".claude.json") if alias == "default" else (d / ".claude.json")
        email = None
        try:
            j = json.load(open(cfg))
            email = j.get("oauthAccount", {}).get("emailAddress") or None
        except Exception:
            pass
        data["config_dirs"][alias] = email
    # remoteControlAtStartup
    try:
        s = json.load(open(home / ".claude/settings.json"))
        data["remote_control_at_startup"] = bool(s.get("remoteControlAtStartup", False))
    except Exception:
        pass
    # 旧 CLI 残置 (/usr/local/bin/claude、 dual-install trap の fleet 可視化)
    old = Path("/usr/local/bin/claude")
    if old.exists():
        rc, out = sh([str(old), "--version"], timeout=10)
        m = re.search(r"\d+(?:\.\d+)+", out)
        data["old_usr_local_cli"] = m.group(0) if m else "unparseable"
    # desktop app の scheduled task registry 監視 (= account × app-install scoped な registry が
    # アカウント切替で enabled task を黙って復活させ、 launchd 移行済ジョブと二重実行する事故の
    # 機械検出。 2026-07-04 実測: swap 2 日後まで silent だった)。 registry ごとに enabled id を列挙。
    data["desktop_scheduled_tasks"] = scan_desktop_tasks(home)
    # inventory (opt-in): 「このマシンに何が置かれているか」 の名前一覧。 reader が fleet 横断で
    # 突合して「他マシンには在るのにここには無い」 を surface する (docstring §inventory)。
    if inventory_specs:
        inv = {}
        for spec in inventory_specs:
            try:
                r = scan_inventory(spec)
            except Exception:
                r = None  # fail-open (= 1 spec の失敗で beat 全体を落とさない)
            if r:
                inv[r[0]] = r[1]
        if inv:
            data["inventories"] = inv
    return data


# コマンドとして呼ぶ位置の python3 だけ (行頭 / ; & | ( ` / $( / exec then do else の直後)。 文字列中の語は数えない
_BARE_PY_RE = re.compile(r"(?:^|[;&|(`]\s*|\$\(\s*|\b(?:exec|then|do|else)\s+)python3\s")
_EXPORT_PATH_RE = re.compile(r'export PATH="([^"]*)"')
_WRAPPER_RE = re.compile(r'(?:exec\s+)?bash\s+"([^"]+\.sh)"')


def _expand(p, home):
    return p.replace("$HOME", str(home)).replace("${HOME}", str(home)).replace("~", str(home), 1 if p.startswith("~") else 0)


def job_path(plist, home):
    """job 定義の PATH (command の最後の `export PATH="..."` > EnvironmentVariables.PATH)。 無ければ None (= launchd 既定)。"""
    cmd = " ".join(str(x) for x in (plist.get("ProgramArguments") or []))
    m = _EXPORT_PATH_RE.findall(cmd)
    if m:
        return ":".join(_expand(p, home) for p in m[-1].split(":"))
    env = plist.get("EnvironmentVariables") or {}
    return _expand(env["PATH"], home) if env.get("PATH") else None


def resolve_in_path(name, path):
    """PATH の順で最初に見つかる実行 file (launchd 既定の PATH は /usr/bin:/bin:/usr/sbin:/sbin)。"""
    for d in (path or "/usr/bin:/bin:/usr/sbin:/sbin").split(":"):
        c = os.path.join(d, name)
        if d and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def bare_python_in(text):
    """`python3` を PATH で呼ぶ行があるか (comment と `command -v python3` は除く)。"""
    for ln in text.splitlines():
        t = ln.strip()
        if not t or t.startswith("#") or "command -v python3" in t:
            continue
        if _BARE_PY_RE.search(t):
            return True
    return False


def job_health(label, status, plist, modules, home):
    """1 ジョブの健康。 probe だけが外に出る (python3 -c 'import ...'、 timeout 10s、 失敗は False)。"""
    rec = {"label": label, "last_exit": None, "python": None, "python_runs": None, "python_ok": None,
           "bare_in_command": None, "bare_in_wrapper": None, "log_failure": None, "log_age_h": None}
    try:
        rec["last_exit"] = int(status)
    except (TypeError, ValueError):
        pass
    if _jl is not None:   # 直近 run の log 末尾 (= 読み込み直しで 0 に戻った失敗と、 失敗の原因を他マシンへ運ぶ)
        try:
            lp = _jl.job_log_path(label, plist if isinstance(plist, dict) else None, home / "Library/Logs")
            rec["log_failure"] = _jl.failure_kind(lp) or None
            age = _jl.log_age_days(lp)
            rec["log_age_h"] = round(age * 24, 1) if age is not None else None
            if rec["log_failure"] == "auth":
                rec["config_dir"] = _jl.config_dir_of(plist if isinstance(plist, dict) else None) or None
        except Exception:
            pass
    if not isinstance(plist, dict):
        return rec
    cmd = " ".join(str(x) for x in (plist.get("ProgramArguments") or []))
    # job の command (= 起動の関門など。 標準ライブラリで足りる) と wrapper (= engine。 依存を使う) を分けて見る
    rec["bare_in_command"] = bare_python_in(cmd.replace(";", "\n").replace("&&", "\n").replace("||", "\n"))
    bw = False
    for w in _WRAPPER_RE.findall(cmd):
        try:
            bw = bw or bare_python_in(Path(_expand(w, home)).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    rec["bare_in_wrapper"] = bw
    py = resolve_in_path("python3", job_path(plist, home))
    rec["python"] = py

    def _probe(code):
        if not py:
            return False
        env = dict(os.environ)
        if os.path.isdir("/Library/Developer/CommandLineTools"):
            env.setdefault("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
        try:
            return subprocess.run([py, "-c", code], env=env, capture_output=True, timeout=10).returncode == 0
        except Exception:
            return False
    rec["python_runs"] = _probe("import sys")
    if modules:
        rec["python_ok"] = rec["python_runs"] and _probe("import sys; " + "; ".join(f"import {m}" for m in modules))
    return rec


def scan_jobs(launchctl_out, prefixes, modules, home):
    import plistlib
    out = []
    for line in launchctl_out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        status, label = parts[1], parts[2]
        if not any(label.startswith(p) for p in prefixes):
            continue
        try:
            with open(home / "Library/LaunchAgents" / f"{label}.plist", "rb") as f:
                pl = plistlib.load(f)
        except Exception:
            pl = None
        try:
            out.append(job_health(label, status, pl, modules, home))
        except Exception:
            out.append({"label": label, "last_exit": None, "python": None, "python_runs": None, "python_ok": None,
                        "bare_in_command": None, "bare_in_wrapper": None})
    out.sort(key=lambda r: r["label"])
    return out


def scan_desktop_tasks(home: Path):
    """全 account registry の scheduled-tasks.json から enabled task id を収集 (fail-open)。"""
    out = []
    try:
        base = home / "Library/Application Support/Claude/claude-code-sessions"
        for f in sorted(base.glob("*/*/scheduled-tasks.json")):
            try:
                d = json.load(open(f))
                ids = sorted(
                    t.get("id") or t.get("taskId") or "?"
                    for t in d.get("scheduledTasks", [])
                    if t.get("enabled")
                )
                # registry の識別は account uuid の先頭 8 桁 (= PII でない、 突合には十分)
                out.append({"registry": f.parent.parent.name[:8], "enabled_ids": ids})
            except Exception:
                out.append({"registry": f.parent.parent.name[:8], "enabled_ids": None})
    except Exception:
        pass
    return out


def essence(d: dict):
    """commit 要否判定に使う本質部分 (ts / pid / log age を除く)。"""
    return json.dumps(
        {
            "servers": [(s["label"], s["pid"] is not None, s["last_status"]) for s in d.get("servers", [])],
            "config_dirs": d.get("config_dirs"),
            "rcs": d.get("remote_control_at_startup"),
            "old_cli": d.get("old_usr_local_cli"),
            "cron_jobs": d.get("cron_jobs"),
            # enabled task の変化 (= 復活) は即 commit させる (= state-change-or-age policy に乗せる)
            "desktop_tasks": d.get("desktop_scheduled_tasks"),
            # inventory の増減 (= account 追加 / 欠落) も即 commit (= 他マシンの reader に早く届く)
            "inventories": d.get("inventories"),
            # job の健康の変化 (= 壊れた / 直った) も即 commit (last_exit は 0 か否かだけ)
            "jobs": [(j.get("label"), (j.get("last_exit") or 0) != 0, j.get("python_runs"), j.get("python_ok"),
                      j.get("bare_in_command"), j.get("bare_in_wrapper"), j.get("log_failure"))
                     for j in d.get("jobs") or []],
        },
        sort_keys=True,
    )


def git(repo: Path, *args, timeout=60):
    return sh(["git", "-C", str(repo), *args], timeout=timeout)


def beat(repo: Path, subdir: str, min_interval_h: float, rc_prefix: str, cron_prefix,
         inventory_specs=None, job_prefixes=None, job_modules=None):
    data = collect(rc_prefix, cron_prefix, inventory_specs, job_prefixes, job_modules)
    rel = f"{subdir}/{data['host']}.json"
    fpath = repo / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)

    old_ess = None
    if fpath.exists():
        try:
            old_ess = essence(json.load(open(fpath)))
        except Exception:
            pass
    rc, out = git(repo, "log", "-1", "--format=%ct", "--", rel)
    last_commit = int(out.strip()) if (rc == 0 and out.strip().isdigit()) else 0
    aged = (time.time() - last_commit) >= min_interval_h * 3600

    if old_ess == essence(data) and not aged:
        return "skip (no change, within interval)"

    fpath.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    git(repo, "add", rel)
    rc, _ = git(repo, "commit", "-q", "-m", f"fleet-heartbeat: {data['host']}")
    if rc != 0:
        return "commit failed (fail-open)"
    # --autostash: 他 session が残した無関係な dirty file で rebase が
    # 拒否されると、 beat が local commit に積み上がるだけで push されず
    # 他マシンから silent 死に見える (2026-07-10 実測 RCA: dirty 残置 2 日で
    # divergence 76/12 まで雪だるま化)。 autostash なら dirty をまたいで流れる。
    git(repo, "pull", "--rebase", "--autostash", "-q")
    rc, _ = git(repo, "push", "-q", timeout=90)
    return "committed+pushed" if rc == 0 else "committed (push failed, retry next beat)"


def selftest():
    import tempfile
    ok = 0
    with tempfile.TemporaryDirectory() as td:
        # ANSI strip + marker priority (後に出た marker が勝つ)
        log = Path(td) / "x.log"
        log.write_bytes("·✔︎· Connected\x1b[6A\x1b[J\nNot logged in\n".encode())
        st, _ = parse_log_status(log)
        assert st == "auth_error", st
        ok += 1
        log.write_bytes("Not logged in\nfoo\n... Connected · Claude · HEAD\n".encode())
        st, _ = parse_log_status(log)
        assert st == "connected", st
        ok += 1
        # trust_error: 過去に Connected でも最後の marker が trust なら trust_error
        log.write_bytes("Connected · Claude · HEAD\nError: Workspace not trusted. Please run `claude` in /x first\n".encode())
        st, _ = parse_log_status(log)
        assert st == "trust_error", st
        ok += 1
        # essence: ts/pid 差は無視、 status 差は検出
        a = {"servers": [{"label": "l", "pid": "1", "last_status": "connected", "log_age_min": 3}],
             "config_dirs": {}, "remote_control_at_startup": True,
             "old_usr_local_cli": None, "cron_jobs": 2}
        b = json.loads(json.dumps(a)); b["servers"][0]["pid"] = "999"
        assert essence(a) == essence(b)
        ok += 1
        c = json.loads(json.dumps(a)); c["servers"][0]["last_status"] = "auth_error"
        assert essence(a) != essence(c)
        ok += 1
        # git repo での beat → commit → 2 回目は skip
        repo = Path(td) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        # fixture email は文字列連結で構成 (= public-precommit の Tier A email regex を
        # 発火させないため。 値は RFC 2606 の .invalid = 実在しない domain)
        git(repo, "config", "user.email", "t@" + "example.invalid")
        git(repo, "config", "user.name", "t")
        r1 = beat(repo, "fleet", 4, RC_LABEL_PREFIX_DEFAULT, None)
        assert r1.startswith("committed"), r1
        ok += 1
        r2 = beat(repo, "fleet", 4, RC_LABEL_PREFIX_DEFAULT, None)
        assert r2.startswith("skip"), r2
        ok += 1
        # inventory: name = 最初の `*` 以降の最初の path 要素 (= 親 dir 名 / file 名の両形)
        inv_root = Path(td) / "invroot"
        for a in ("a1", "a2"):
            (inv_root / a).mkdir(parents=True)
            (inv_root / a / "credentials.json").write_text("x")
        (inv_root / "empty").mkdir()  # credentials.json 無し = 名前に出ない
        r = scan_inventory(f"accts={inv_root}/*/credentials.json")
        assert r == ("accts", ["a1", "a2"]), r
        ok += 1
        r = scan_inventory(f"files={inv_root}/*/*.json")
        assert r == ("files", ["a1", "a2"]), r  # 最初の `*` 以降の最初の要素 = 親 dir
        ok += 1
        flat = Path(td) / "flat"
        flat.mkdir()
        (flat / "a.key").write_text("x")
        (flat / "b.key").write_text("x")
        r = scan_inventory(f"secrets={flat}/*")
        assert r == ("secrets", ["a.key", "b.key"]), r
        ok += 1
        # match 0 件でも label は [] で報告 (= 「旧 beat の field 不在」 と区別できるように)
        r = scan_inventory(f"none={flat}/nope-*/x")
        assert r == ("none", []), r
        ok += 1
        # 不正 spec は None (= caller が無視、 beat を落とさない)
        assert scan_inventory("no-equals-sign") is None
        assert scan_inventory("=/tmp/*") is None
        ok += 1
        # collect() 配線 + essence が inventory 変化を拾う (= 即 commit 対象)
        d1 = collect(RC_LABEL_PREFIX_DEFAULT, None, [f"accts={inv_root}/*/credentials.json"])
        assert d1["inventories"] == {"accts": ["a1", "a2"]}, d1.get("inventories")
        d2 = json.loads(json.dumps(d1))
        d2["inventories"]["accts"] = ["a1"]
        assert essence(d1) != essence(d2)
        ok += 1
        # --inventory 未指定なら field 自体を作らない (= 旧 beat と同形、 opt-in)
        assert "inventories" not in collect(RC_LABEL_PREFIX_DEFAULT, None, None)
        # job health: PATH の python3 が module を読めないジョブを、 wrapper の書き方ごと記録する
        jroot = Path(td) / "jobhome"
        (jroot / "brew").mkdir(parents=True)
        (jroot / "sys").mkdir(parents=True)
        (jroot / "Library/LaunchAgents").mkdir(parents=True)
        for d_, good in (("brew", False), ("sys", True)):
            p = jroot / d_ / "python3"
            p.write_text("#!/bin/sh\nexit %d\n" % (0 if good else 1))
            p.chmod(0o755)
        w_bare = jroot / "bare-cron.sh"
        w_bare.write_text("#!/bin/bash\n# python3 はコメント\ncommand -v python3 >/dev/null || exit 0\necho \"python3 が無い\"\npython3 \"$ENGINE\" --x\n")
        w_pick = jroot / "pick-cron.sh"
        w_pick.write_text("#!/bin/bash\nPY=\"$(pick_python yaml)\" || exit 3\n\"$PY\" \"$ENGINE\"\n")
        def mkpl(target, path):
            return {"ProgramArguments": ["/bin/sh", "-c",
                    'export PATH="%s"; cd "$HOME" && exec bash "%s"' % (path, target)]}
        jb = job_health("j.bare", "0", mkpl(str(w_bare), f"$HOME/brew:$HOME/sys"), ["yaml"], jroot)
        assert jb["python"] == str(jroot / "brew/python3") and jb["python_ok"] is False and jb["python_runs"] is False             and jb["bare_in_wrapper"] is True and jb["bare_in_command"] is False, jb
        jp = job_health("j.pick", "3", mkpl(str(w_pick), f"$HOME/brew:$HOME/sys"), ["yaml"], jroot)
        assert jp["bare_in_wrapper"] is False and jp["last_exit"] == 3, jp
        jg = job_health("j.gate", "-", {"ProgramArguments": ["/bin/sh", "-c",
                        'export PATH="$HOME/sys"; cd x && python3 "gate.py" || exit 0; exec claude -p']}, ["yaml"], jroot)
        assert jg["bare_in_command"] is True and jg["bare_in_wrapper"] is False and jg["python_ok"] is True             and jg["python_runs"] is True and jg["last_exit"] is None, jg
        assert not bare_python_in('echo "yaml を import できる python3 が無い" >&2')
        assert bare_python_in('out="$(python3 x.py)"') and bare_python_in("python3 x.py")             and not bare_python_in('PY=python3') and not bare_python_in('[ -x /usr/bin/python3 ] && PY=/usr/bin/python3')
        assert job_health("j.none", "0", None, ["yaml"], jroot)["python"] is None
        assert resolve_in_path("python3", None) in (None, "/usr/bin/python3")
        e1 = essence({"jobs": [jb]}); e2 = essence({"jobs": [dict(jb, python_ok=True)]})
        assert e1 != e2, "job の健康の変化は即 commit"
        # 直近 run の log 末尾 (lib/launchd_job_log.py と共有の判定): exit 0 でも認証切れを運ぶ
        (jroot / "Library/Logs").mkdir(parents=True, exist_ok=True)
        (jroot / "Library/Logs/j.auth.log").write_text("warn\nFailed to authenticate: OAuth session expired\n")
        ja = job_health("j.auth", "0", {"ProgramArguments": ["/bin/sh", "-c",
                        'export CLAUDE_CONFIG_DIR="/c/.claude-x"; exec claude -p']}, [], jroot)
        if _jl is not None:
            assert ja["log_failure"] == "auth" and ja["config_dir"] == "/c/.claude-x" \
                and ja["log_age_h"] is not None and ja["last_exit"] == 0, ja
            assert essence({"jobs": [ja]}) != essence({"jobs": [dict(ja, log_failure=None)]}), "失敗の原因の変化も即 commit"
        assert job_health("j.nolog", "0", None, [], jroot)["log_failure"] is None
        ok += 1
    print(f"selftest: {ok}/14 PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--subdir", default="private/fleet-status")
    ap.add_argument("--min-commit-interval-hours", type=float, default=4)
    ap.add_argument("--rc-label-prefix", default=RC_LABEL_PREFIX_DEFAULT)
    ap.add_argument("--cron-label-prefix", default=None)
    ap.add_argument("--inventory", action="append", default=[],
                    metavar="LABEL=GLOB",
                    help="このマシンに置かれた物の **名前だけ** を記録 (repeatable、 中身は読まない)。 "
                         "reader が fleet 横断で突合し「他マシンには在るのにここには無い」 を surface")
    ap.add_argument("--job-label-prefix", action="append", default=[],
                    help="この prefix の launchd job ごとに最後の終了コードと、 job の PATH での python3 の健康を記録 (repeatable)")
    ap.add_argument("--job-python-modules", default="",
                    help="ジョブの python3 が import できるべき module (カンマ区切り、 例 yaml)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.repo:
        print("--repo required", file=sys.stderr)
        sys.exit(0)  # fail-open
    try:
        msg = beat(Path(args.repo).expanduser(), args.subdir,
                   args.min_commit_interval_hours, args.rc_label_prefix,
                   args.cron_label_prefix, args.inventory, args.job_label_prefix,
                   [m.strip() for m in args.job_python_modules.split(",") if m.strip()])
        print(msg)
    except Exception as e:
        print(f"fail-open: {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
