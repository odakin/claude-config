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
  fleet-heartbeat.py --selftest

書かれる JSON (subdir/<hostname>.json):
  { host, ts (iso), epoch, servers: [{label, pid, last_status, log_age_min}],
    config_dirs: {alias: email_metadata_or_null},
    remote_control_at_startup, old_usr_local_cli, cron_jobs,
    desktop_scheduled_tasks: [{registry, enabled_ids}],
    inventories: {label: [name, ...]} }        # --inventory 指定時のみ

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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
    names = set()
    for m in globmod.glob(expanded):
        rest = m[len(prefix):] if (prefix and m.startswith(prefix)) else os.path.basename(m)
        n = rest.split(os.sep, 1)[0]
        if n:
            names.add(n)
    return label, sorted(names)


def collect(rc_prefix, cron_prefix, inventory_specs=None):
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
        },
        sort_keys=True,
    )


def git(repo: Path, *args, timeout=60):
    return sh(["git", "-C", str(repo), *args], timeout=timeout)


def beat(repo: Path, subdir: str, min_interval_h: float, rc_prefix: str, cron_prefix,
         inventory_specs=None):
    data = collect(rc_prefix, cron_prefix, inventory_specs)
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
                   args.cron_label_prefix, args.inventory)
        print(msg)
    except Exception as e:
        print(f"fail-open: {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
