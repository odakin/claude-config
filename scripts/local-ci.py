#!/usr/bin/env python3
"""local-ci.py — CI を持たない repo の検査を手元で回す runner（config の repo × 検査を、 対象 path の最終 commit が変わったものだけ実行して結果を machine-local state に残し、 --status で red / 検査不能 / 長く未実行を 1 行ずつ出す。 並列起動は lock で 1 本、 --selftest 内蔵）

なぜ要るか: GitHub Actions の無料枠は private repo だと月の分数に上限がある。 push の多い private repo で
per-push の検査を回すと枠を使い切り、 以後は **全 workflow が「起動されない」 まま red** になる
(= コードの失敗ではない。 check-ci-red.py が「未起動」 として分けて出す)。 お金をかけない運用では
private repo の検査を手元に移すことになるが、 「手元で回す」 は放っておくと「誰も回さない」 になる。
∴ 本 runner は (1) 変わった repo だけを回し (2) 結果を state に残し (3) 呼び出し側 (session 開始
hook など、 人が毎回見る面) が --status で読む、 の 3 つを受け持つ。 規約 =
conventions/github-security-automation.md#private-actions-minutes。

config (JSON):
  {
    "base": "~/Claude",                       # repo dir の親 (既定 = この script の 2 つ上)
    "path_prepend": ["~/Library/Python/3.9/bin"],   # 検査 tool を探す PATH の追加分 (任意)。 ⚠️ 前に足すので
                                              # 別の python3 がある dir を足すと検査 script の依存が消える
    "env": {"PYTHONWARNINGS": "ignore"},     # 検査に渡す環境変数 (任意。 tool 自身の警告で末尾行が埋まるのを防ぐ等)
    "min_interval_hours": 6,                  # 同じ検査を続けて回す間隔の下限 (既定 6)
    "commands": {"semgrep": [["semgrep", "scan", "--error", "."]]},   # 名前つき command (任意)
    "checks": [
      {"repo": "my-repo", "name": "tests", "run": [["bash", "scripts/run-all-checks.sh"]],
       "paths": ["scripts", "hooks"], "timeout": 900},
      {"repo": "other", "name": "semgrep", "run": "semgrep", "paths": [".", ":(exclude)private"]}
    ]
  }
  run = argv の list の list (順に実行、 1 本でも非 0 なら red) か、 commands の名前。
  paths = git pathspec。 key = その pathspec に触れた最終 commit (既定 ".")。 key が前回と同じなら回さない。
  check ごとの任意: "env" (その検査だけの環境変数) / "rerun_hours" (key が同じでもこの時間を過ぎたら回す =
  他 repo や外部を見る検査用) / "timeout" (秒、 既定 900)。
  検査は working tree で走る (未 commit の変更も含む) が、 記録する key は commit。

使い方:
  local-ci.py --config C --run [--force] [--only REPO]   変わった検査を回す (lock が取れなければ何もしない)
  local-ci.py --config C --status [--strict]             red / 検査不能 / 24h 超未実行を出す (全部緑なら無出力)
  local-ci.py --selftest
state: 既定 ~/.claude/local-ci/state.json (--state で変更)。 machine-local = マシンごとに回して、 そのマシンの
session が読む (clone がある所で回るので、 結果を別マシンに運ぶ必要が無い)。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE = Path.home() / ".claude" / "local-ci" / "state.json"
DEFAULT_BASE = Path(__file__).resolve().parents[2]
TAIL_LINES = 40
PENDING_WARN_HOURS = 24
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def now() -> float:
    return time.time()


def fmt_age(ts: float) -> str:
    h = (now() - ts) / 3600
    return f"{h:.0f}h 前" if h < 48 else f"{h / 24:.0f} 日前"


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["base"] = Path(os.path.expanduser(cfg.get("base") or str(DEFAULT_BASE)))
    cfg["path_prepend"] = [os.path.expanduser(p) for p in cfg.get("path_prepend", [])]
    commands = cfg.get("commands", {})
    for check in cfg.get("checks", []):
        run = check.get("run")
        if isinstance(run, str):
            if run not in commands:
                raise ValueError(f"check {check.get('repo')}/{check.get('name')}: unknown command {run!r}")
            check["run"] = commands[run]
        if not check["run"] or not all(isinstance(argv, list) and argv for argv in check["run"]):
            raise ValueError(f"check {check.get('repo')}/{check.get('name')}: run must be a list of argv lists")
    return cfg


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def check_id(check: dict) -> str:
    return f"{check['repo']}::{check['name']}"


def content_key(repo_dir: Path, paths: list[str]) -> str | None:
    r = subprocess.run(["git", "-C", str(repo_dir), "log", "-1", "--format=%H", "--", *paths],
                       capture_output=True, text=True)
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def tool_env(cfg: dict, check: dict | None = None) -> dict:
    env = dict(os.environ)
    env.update({k: str(v) for k, v in cfg.get("env", {}).items()})
    env.update({k: str(v) for k, v in (check or {}).get("env", {}).items()})
    env["PATH"] = os.pathsep.join([*cfg["path_prepend"], env.get("PATH", "")])
    return env


def probe(cfg: dict, check: dict) -> tuple[Path, str | None, str | None]:
    """(repo_dir, key, 検査不能の理由)。"""
    repo_dir = cfg["base"] / check["repo"]
    if not (repo_dir / ".git").exists():
        return repo_dir, None, f"clone が無い ({repo_dir})"
    env = tool_env(cfg)
    for argv in check["run"]:
        tool = argv[0]
        if not (os.sep in tool or shutil.which(tool, path=env["PATH"])):
            return repo_dir, None, f"{tool} が無い (install するか config の path_prepend に場所を足す)"
    key = content_key(repo_dir, check.get("paths") or ["."])
    if key is None:
        return repo_dir, None, "git log が読めない"
    return repo_dir, key, None


EXCLUDE_ENCRYPTED = "@exclude-git-crypt"


def encrypted_paths(repo_dir: Path) -> list[str]:
    """git-crypt で暗号化される追跡 file (手元では平文、 remote では暗号文)。"""
    files = subprocess.run(["git", "-C", str(repo_dir), "ls-files", "-z"], capture_output=True).stdout
    names = [n for n in files.decode("utf-8", "surrogateescape").split("\0") if n]
    if not names:
        return []
    r = subprocess.run(["git", "-C", str(repo_dir), "check-attr", "-z", "filter", "--stdin"],
                       input="\0".join(names).encode("utf-8", "surrogateescape"), capture_output=True)
    parts = r.stdout.decode("utf-8", "surrogateescape").split("\0")
    return [parts[i] for i in range(0, len(parts) - 2, 3) if parts[i + 2] == "git-crypt"]


def expand_argv(argv: list[str], repo_dir: Path) -> list[str]:
    """`@exclude-git-crypt` → 暗号化 file ごとに `--exclude <path>`。 手元の scan は平文を読むので、
    意図して暗号化保存した secret が secret 検出に掛かり続ける (remote 側は暗号文なので漏洩ではない)。"""
    out = []
    for arg in argv:
        if arg == EXCLUDE_ENCRYPTED:
            for path in encrypted_paths(repo_dir):
                out += ["--exclude", path]
        else:
            out.append(arg)
    return out


def run_one(cfg: dict, check: dict, repo_dir: Path, key: str) -> dict:
    started, rc, lines, timed_out = now(), 0, [], False
    deadline = started + int(check.get("timeout", 900))
    for argv in check["run"]:
        argv = expand_argv(argv, repo_dir)
        try:
            p = subprocess.run(argv, cwd=repo_dir, env=tool_env(cfg, check), capture_output=True,
                               timeout=max(1, deadline - now()))
            out = (p.stdout + p.stderr).decode("utf-8", "replace")
            rc = p.returncode
        except subprocess.TimeoutExpired as exc:
            out = ((exc.stdout or b"") + (exc.stderr or b"")).decode("utf-8", "replace")
            rc, timed_out = 124, True
        except OSError as exc:
            out, rc = str(exc), 127
        lines += [ANSI.sub("", l) for l in out.splitlines() if l.strip()]
        if rc != 0:
            break
    return {"key": key, "rc": rc, "timed_out": timed_out, "started": started,
            "duration": round(now() - started, 1), "tail": lines[-TAIL_LINES:], "unprobed": None}


def do_run(cfg: dict, state_path: Path, force=False, only=None, out=print) -> int:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock = open(state_path.with_suffix(".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        out("local-ci: 別の run が実行中なので何もしない")
        return 0
    interval = float(cfg.get("min_interval_hours", 6)) * 3600
    for check in cfg.get("checks", []):
        if only and check["repo"] != only:
            continue
        state = load_state(state_path)
        cid, prev = check_id(check), state.get(check_id(check), {})
        repo_dir, key, why = probe(cfg, check)
        if why:
            state[cid] = dict(prev, unprobed=why, probed_at=now())
            save_state(state_path, state)
            continue
        stale_hours = check.get("rerun_hours")  # 他 repo や外部を見る検査 = commit が変わらなくても定期に回す
        aged = stale_hours is not None and prev.get("started") and now() - prev["started"] > float(stale_hours) * 3600
        if not force and prev.get("key") == key and not prev.get("unprobed") and not aged:
            continue
        if not force and prev.get("started") and now() - prev["started"] < interval and not prev.get("unprobed"):
            continue
        result = run_one(cfg, check, repo_dir, key)
        state = load_state(state_path)
        state[cid] = result
        save_state(state_path, state)
        out(f"local-ci: {cid} exit {result['rc']} ({result['duration']} s)")
    return 0


def do_status(cfg: dict, state_path: Path, strict=False, out=print) -> int:
    state = load_state(state_path)
    red, unprobed, pending = [], [], []
    for check in cfg.get("checks", []):
        cid, rec = check_id(check), state.get(check_id(check))
        label = f"{check['repo']} · {check['name']}"
        if rec and rec.get("unprobed"):
            unprobed.append((rec["unprobed"], label))
            continue
        if not rec:
            pending.append(f"{label} (一度も回っていない)")
            continue
        if rec["rc"] != 0:
            # 末尾の罫線だけの行 (═══ 等) は飛ばし、 文字を含む最後の行を見出しにする
            last = next((l.strip() for l in reversed(rec.get("tail", [])) if re.search(r"\w", l)), "")
            what = "timeout" if rec.get("timed_out") else f"exit {rec['rc']}"
            red.append(f"🔴 {label}: {what} ({fmt_age(rec['started'])}, {rec['key'][:8]}) — {last[:160]}")
        repo_dir = cfg["base"] / check["repo"]
        key = content_key(repo_dir, check.get("paths") or ["."]) if (repo_dir / ".git").exists() else None
        if key and key != rec.get("key") and now() - rec["started"] > PENDING_WARN_HOURS * 3600:
            pending.append(f"{label} (最後の run {fmt_age(rec['started'])}、 その後に commit あり)")
    for line in red:
        out(line)
    by_reason: dict[str, list[str]] = {}
    for why, label in unprobed:  # 同じ理由 (tool が無い等) は 1 行にまとめる = 14 repo で 14 行にしない
        by_reason.setdefault(why, []).append(label)
    for why, labels in by_reason.items():
        out(f"⚠️ 検査不能 {len(labels)} 件 — {why}: " + " / ".join(labels))
    if pending:
        out(f"⏳ 手元の検査が {PENDING_WARN_HOURS}h 以上回っていない: " + " / ".join(pending[:6])
            + (f" … 他 {len(pending) - 6}" if len(pending) > 6 else ""))
    if red:
        out("   詳細: local-ci.py --config <config> --status の state (tail) / 再実行: --run --force --only <repo>")
    return 1 if strict and (red or unprobed) else 0


def selftest() -> int:
    fails = []

    def expect(label, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        if not cond:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        git = lambda repo, *a: subprocess.run(["git", "-C", str(base / repo), *a], env=env, capture_output=True)
        for repo in ("good", "bad"):
            (base / repo / "src").mkdir(parents=True)
            (base / repo / "src" / "a.txt").write_text("1\n")
            (base / repo / "notes.txt").write_text("n\n")
            git(repo, "init", "-q")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "init")
        py = sys.executable
        cfg_path = base / "cfg.json"
        cfg_path.write_text(json.dumps({
            "base": str(base), "min_interval_hours": 0, "env": {"LOCAL_CI_SELFTEST_VAR": "seen"},
            "commands": {"ok": [[py, "-c", "print('fine')"]]},
            "checks": [
                {"repo": "good", "name": "ok", "run": "ok", "paths": ["src"]},
                {"repo": "bad", "name": "fails", "run": [[py, "-c", "print('first')"],
                                                         [py, "-c", "import sys; print('boom line'); sys.exit(3)"]]},
                {"repo": "good", "name": "notool", "run": [["no-such-tool-xyz", "--version"]]},
                {"repo": "bad", "name": "notool", "run": [["no-such-tool-xyz", "--version"]]},
                {"repo": "bad", "name": "env", "run": [[py, "-c", "import os; print(os.environ['LOCAL_CI_SELFTEST_VAR'])"]]},
                {"repo": "bad", "name": "boxed", "env": {"LOCAL_CI_SELFTEST_VAR": "own"}, "rerun_hours": 1,
                 "run": [[py, "-c", "import os, sys; print('real reason ' + os.environ['LOCAL_CI_SELFTEST_VAR']); print('════'); sys.exit(1)"]]},
                {"repo": "missing", "name": "ok", "run": "ok"},
            ]}))
        cfg, state = load_config(cfg_path), base / "state" / "state.json"
        log = []
        do_run(cfg, state, out=log.append)
        st = load_state(state)
        expect("passing check recorded exit 0", st.get("good::ok", {}).get("rc") == 0)
        expect("a failing step makes the check red and keeps its output",
               st.get("bad::fails", {}).get("rc") == 3 and "boom line" in st["bad::fails"]["tail"])
        expect("missing tool = unprobed, not green", "no-such-tool-xyz" in (st.get("good::notool", {}).get("unprobed") or ""))
        expect("missing clone = unprobed", "clone" in (st.get("missing::ok", {}).get("unprobed") or ""))
        expect("config env reaches the command", st.get("bad::env", {}).get("tail") == ["seen"])
        expect("a check's own env overrides the config env", "real reason own" in st.get("bad::boxed", {}).get("tail", []))
        lines = []
        do_status(cfg, state, out=lines.append)
        text = "\n".join(lines)
        expect("status shows the red check with its last output line", "🔴 bad · fails: exit 3" in text and "boom line" in text)
        expect("unprobed checks with the same reason share one line, other reasons get their own",
               text.count("検査不能") == 2 and "⚠️ 検査不能 2 件 — no-such-tool-xyz が無い" in text
               and "good · notool / bad · notool" in text)
        expect("status does not mention the green check", "good · ok" not in text)
        expect("status headline skips a trailing rule line", "🔴 bad · boxed: exit 1" in text and "— real reason own" in text)
        expect("--strict exits 1 when something is red", do_status(cfg, state, strict=True, out=lambda *_: None) == 1)
        log = []
        do_run(cfg, state, out=log.append)
        expect("unchanged key = not rerun", not any("good::ok" in l or "bad::fails" in l for l in log))
        full = load_state(state)
        full["bad::boxed"]["started"] -= 2 * 3600
        save_state(state, full)
        log = []
        do_run(cfg, state, out=log.append)
        expect("rerun_hours reruns a check whose key did not change once it is old enough",
               any("bad::boxed" in l for l in log) and not any("bad::fails" in l for l in log))
        (base / "good" / "notes.txt").write_text("changed\n")
        git("good", "commit", "-qam", "notes only")
        log = []
        do_run(cfg, state, out=log.append)
        expect("a commit outside the check's paths does not rerun it", not any("good::ok" in l for l in log))
        (base / "good" / "src" / "a.txt").write_text("2\n")
        git("good", "commit", "-qam", "src")
        log = []
        do_run(cfg, state, out=log.append)
        expect("a commit inside the check's paths reruns it", any("good::ok exit 0" in l for l in log))
        with open(state.with_suffix(".lock"), "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            log = []
            do_run(cfg, state, force=True, out=log.append)
            expect("a held lock = the second run does nothing", log == ["local-ci: 別の run が実行中なので何もしない"])
        (base / "good" / ".gitattributes").write_text("secret.json filter=git-crypt diff=git-crypt\n")
        (base / "good" / "secret.json").write_text("{}\n")
        git("good", "add", "-A")
        argv = expand_argv(["scan", EXCLUDE_ENCRYPTED, "."], base / "good")
        expect("@exclude-git-crypt expands to --exclude for each git-crypt path",
               argv == ["scan", "--exclude", "secret.json", "."])
        expect("@exclude-git-crypt expands to nothing without encrypted files",
               expand_argv(["scan", EXCLUDE_ENCRYPTED], base / "bad") == ["scan"])
        git("good", "commit", "-qm", "attrs")
        rec = load_state(state)["good::ok"]
        rec["started"] -= (PENDING_WARN_HOURS + 1) * 3600
        full = load_state(state)
        full["good::ok"] = rec
        save_state(state, full)
        (base / "good" / "src" / "a.txt").write_text("3\n")
        git("good", "commit", "-qam", "src again")
        lines = []
        do_status(cfg, state, out=lines.append)
        expect("a check not run for 24h after a new commit is reported as pending",
               any(l.startswith("⏳") and "good · ok" in l for l in lines))
    print("local-ci selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.config or not (a.run or a.status):
        ap.error("--config と --run / --status を指定 (or --selftest)")
    if not a.config.is_file():
        print(f"⚠️ 手元の検査: config が無い ({a.config}) — 検査不能 (= 緑とは限らない)")
        return 0
    cfg = load_config(a.config)
    rc = do_run(cfg, a.state, a.force, a.only) if a.run else 0
    return do_status(cfg, a.state, a.strict) if a.status else rc


if __name__ == "__main__":
    sys.exit(main())
