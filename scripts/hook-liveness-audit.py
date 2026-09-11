#!/usr/bin/env python3
"""hook-liveness-audit.py — user hook が「そもそも走っていない」 root を検出 (disableAllHooks kill switch の settings 全 tier 走査 + transcript 上の SessionStart 発火証拠)

なぜ要るか
----------
`disableAllHooks: true` は **その settings file が効く範囲の command hook を全部止める**。
project-local (`<root>/.claude/settings.local.json`) に入っていると、 その root を開いた
session だけで hook が 1 本も走らず、 別 root で開いた session では普通に走る。 結果として
「ある frontend では hook が効かない」 と誤診されやすい (= root の差を frontend の差と取り違える)。
しかも kill switch 下の session は SessionStart hook も止まるので **自分の hook で自分を検出
できない** — 検出は外側 (dashboard / 別 root の hook / 定期実行) から回す必要がある。
一般則: conventions/hook-authoring.md#disableallhooks-kill-switch

何を見るか
----------
1. settings tier: user (`~/.claude/settings.json`) / managed (macOS
   `/Library/Application Support/ClaudeCode/managed-settings.json`、 Linux
   `/etc/claude-code/managed-settings.json`) / 各 root の `.claude/settings.json` と
   `.claude/settings.local.json`。 `disableAllHooks: true` → 🔴、
   `allowManagedHooksOnly: true` → 🟠 (= user / project hook が走らない)。
   検査する root = transcript (`~/.claude/projects/*/*.jsonl`、 mtime が `--days` 以内) の最初の
   `cwd` の集合 + `--root`。 `--settings-only` でも root の発見には transcript 冒頭だけを読む
   (= 最近開いた root の project-local kill switch を、 別 root の session からでも拾うため)。
2. transcript 証拠 (`--settings-only` で skip): 同じ transcript を session の root ごとに集計。
   - SessionStart 発火 = `attachment.hookEvent == "SessionStart"` かつ `attachment.command`
     が在り `callback` でない record (= user の command hook が走った証拠。 host の SDK
     callback hook は kill switch 下でも走り続けるので数えない。 `hook_additional_context`
     は command を持たないので自然に除外される)
   - stop summary = `system/stop_hook_summary` の `hookInfos[].command` に `callback` 以外が
     在る件数 (table 表示時のみ全文走査。 `--findings-only` は head だけ読む = 高速)
   - SessionStart hook が設定されているのに、 **直近の session から遡って連続
     `--min-sessions` 本以上** 発火証拠が無い root → 🟠 (原因候補: kill switch / workspace
     trust 未承認 / allowManagedHooksOnly / 配線)。 「連続」 で見るので、 除去後に 1 本でも
     発火した root は自動で消える (= 過去 30 日の古い 0 件で鳴り続けない)。

出力
----
既定 = 表。 `--findings-only` = finding 行だけ (clean なら無出力 = dashboard / audit-hooks.sh
向け)。 `--strict` = finding があれば exit 1。 `--selftest` = temp dir の偽 settings + 偽
transcript で回帰検査。

使い方
------
  hook-liveness-audit.py                       # 表 (過去 30 日)
  hook-liveness-audit.py --findings-only       # finding だけ (clean なら無出力)
  hook-liveness-audit.py --settings-only       # settings tier だけ (root の発見に transcript 冒頭だけ読む)
  hook-liveness-audit.py --root <dir> ...      # transcript に無い root も settings を検査
  hook-liveness-audit.py --selftest
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

MANAGED_DEFAULT = {
    "darwin": "/Library/Application Support/ClaudeCode/managed-settings.json",
    "linux": "/etc/claude-code/managed-settings.json",
}
HEAD_LINES = 400  # SessionStart の hook record は transcript 冒頭に並ぶ


def _tilde(path, home):
    s = str(path)
    h = str(home)
    return "~" + s[len(h):] if s == h or s.startswith(h + os.sep) else s


def load_json(path):
    """dict を返す。 不在 = None、 読めない = {"__error__": msg}。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"__error__": "top-level is not an object"}
    except FileNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001 — 読めない settings は finding として報告する
        return {"__error__": f"{type(e).__name__}: {e}"}


def has_sessionstart_hooks(settings):
    if not isinstance(settings, dict):
        return False
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    groups = hooks.get("SessionStart")
    if not isinstance(groups, list):
        return False
    for g in groups:
        if isinstance(g, dict) and any(
            isinstance(h, dict) and h.get("command") for h in (g.get("hooks") or [])
        ):
            return True
    return False


def settings_tiers(home, roots, managed_path):
    """(tier, path, scope) を返す。 同じ実体 file は 1 回だけ。"""
    tiers = []
    seen = set()

    def add(tier, path, scope):
        p = Path(path)
        key = os.path.realpath(p)
        if key in seen:
            return
        seen.add(key)
        tiers.append((tier, p, scope))

    add("user", home / ".claude" / "settings.json", "all sessions (this user)")
    if managed_path:
        add("managed", Path(managed_path), "all sessions (this machine)")
    for root in sorted(roots):
        r = Path(root)
        add("project", r / ".claude" / "settings.json", f"sessions rooted at {_tilde(r, home)}")
        add("project-local", r / ".claude" / "settings.local.json", f"sessions rooted at {_tilde(r, home)}")
    return tiers


def audit_settings(home, roots, managed_path):
    findings = []
    for tier, path, scope in settings_tiers(home, roots, managed_path):
        data = load_json(path)
        if data is None:
            continue
        shown = _tilde(path, home)
        if "__error__" in data:
            findings.append(f"🟠 settings を読めない: {shown} [{tier}] ({data['__error__']}) — hook 設定の有無を判定できない")
            continue
        if data.get("disableAllHooks") is True:
            findings.append(
                f"🔴 disableAllHooks: true — {shown} [{tier}] → {scope} で command hook が 1 本も走らない "
                f"(= 除去は同 session の次の tool call から有効。 理由があって入れた可能性があるので削除は owner 判断)"
            )
        if data.get("allowManagedHooksOnly") is True:
            findings.append(f"🟠 allowManagedHooksOnly: true — {shown} [{tier}] → {scope} で user / project hook が走らない")
    return findings


def scan_transcript(path, deep):
    """1 transcript を読んで (root, has_sessionstart, stop_cmd_count, stop_total) を返す。"""
    root = None
    ss = False
    stop_cmd = 0
    stop_total = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if not deep and i >= HEAD_LINES and root is not None:
                    break
                if deep and ss and root is not None and '"stop_hook_summary"' not in line:
                    continue
                if root is None and '"cwd"' in line:
                    try:
                        rec = json.loads(line)
                        if isinstance(rec, dict) and rec.get("cwd"):
                            root = rec["cwd"]
                    except ValueError:
                        pass
                if not ss and '"SessionStart"' in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        rec = None
                    att = rec.get("attachment") if isinstance(rec, dict) else None
                    if isinstance(att, dict) and att.get("hookEvent") == "SessionStart":
                        cmd = att.get("command")
                        if cmd and cmd != "callback":
                            ss = True
                if deep and '"stop_hook_summary"' in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and rec.get("subtype") == "stop_hook_summary":
                        stop_total += 1
                        infos = rec.get("hookInfos") or []
                        if any(isinstance(h, dict) and h.get("command") not in (None, "", "callback") for h in infos):
                            stop_cmd += 1
    except OSError:
        return None
    return root, ss, stop_cmd, stop_total


def discover_roots(projects_dir, days):
    """transcript 冒頭の最初の cwd だけを読んで root 集合を返す (--settings-only 用、 高速)。"""
    cutoff = time.time() - days * 86400
    roots = set()
    if not projects_dir.is_dir():
        return roots
    for pdir in projects_dir.iterdir():
        if not pdir.is_dir():
            continue
        for t in pdir.glob("*.jsonl"):
            try:
                if t.stat().st_mtime < cutoff:
                    continue
                with open(t, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f):
                        if i >= 50:
                            break
                        if '"cwd"' not in line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(rec, dict) and rec.get("cwd"):
                            roots.add(rec["cwd"])
                            break
            except OSError:
                continue
    return roots


def scan_projects(projects_dir, days, deep):
    """root → list of session dict (mtime 降順)。"""
    cutoff = time.time() - days * 86400
    by_root = {}
    if not projects_dir.is_dir():
        return by_root
    for pdir in projects_dir.iterdir():
        if not pdir.is_dir():
            continue
        for t in pdir.glob("*.jsonl"):
            try:
                mt = t.stat().st_mtime
            except OSError:
                continue
            if mt < cutoff:
                continue
            res = scan_transcript(t, deep)
            if res is None:
                continue
            root, ss, stop_cmd, stop_total = res
            if not root:
                continue
            by_root.setdefault(root, []).append(
                {"path": t, "mtime": mt, "ss": ss, "stop_cmd": stop_cmd, "stop_total": stop_total}
            )
    for sessions in by_root.values():
        sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return by_root


def audit(home, projects_dir, managed_path, extra_roots, days, min_sessions, settings_only, deep):
    extra = {str(Path(r).expanduser()) for r in extra_roots}
    if settings_only:
        by_root = {}
        roots = discover_roots(projects_dir, days) | extra
    else:
        by_root = scan_projects(projects_dir, days, deep)
        roots = set(by_root) | extra
    findings = audit_settings(home, roots, managed_path)

    user_settings = load_json(home / ".claude" / "settings.json")
    managed_settings = load_json(Path(managed_path)) if managed_path else None
    global_ss = has_sessionstart_hooks(user_settings) or has_sessionstart_hooks(managed_settings)

    rows = []
    for root in sorted(by_root):
        sessions = by_root[root]
        r = Path(root)
        proj_ss = any(
            has_sessionstart_hooks(load_json(r / ".claude" / n)) for n in ("settings.json", "settings.local.json")
        )
        expected = global_ss or proj_ss
        streak = 0
        for s in sessions:
            if s["ss"]:
                break
            streak += 1
        with_ss = sum(1 for s in sessions if s["ss"])
        last_ss = next((s["mtime"] for s in sessions if s["ss"]), None)
        row = {
            "root": root,
            "sessions": len(sessions),
            "with_ss": with_ss,
            "streak": streak,
            "stop_cmd": sum(s["stop_cmd"] for s in sessions),
            "stop_total": sum(s["stop_total"] for s in sessions),
            "last_ss": last_ss,
            "status": "ok",
        }
        if not expected:
            row["status"] = "no SessionStart hook configured"
        elif streak >= min_sessions:
            row["status"] = "🟠"
            since = time.strftime("%Y-%m-%d", time.localtime(last_ss)) if last_ss else f"過去 {days} 日で一度も"
            findings.append(
                f"🟠 {_tilde(r, home)}: 直近 {streak} session 連続で SessionStart hook の発火記録なし "
                f"(最後の発火 = {since}) — 原因候補: disableAllHooks / workspace trust 未承認 / "
                f"allowManagedHooksOnly / 配線。 判別 = conventions/hook-authoring.md#disableallhooks-kill-switch"
            )
        elif streak:
            row["status"] = f"recent {streak} without evidence (< {min_sessions})"
        rows.append(row)
    return findings, rows


def print_table(findings, rows, home, days, deep, settings_only):
    print(f"hook liveness audit (過去 {days} 日{'、 settings のみ' if settings_only else ''})")
    print("")
    print("findings:" if findings else "findings: なし")
    for f in findings:
        print(f"  {f}")
    if settings_only:
        return
    print("")
    hdr = f"{'root':<52} {'sess':>5} {'SS>0':>5} {'streak':>6} {'stop(cmd/all)':>14}  status"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        stop = f"{r['stop_cmd']}/{r['stop_total']}" if deep else "-"
        name = _tilde(r["root"], home)
        if len(name) > 52:
            name = "…" + name[-51:]
        print(f"{name:<52} {r['sessions']:>5} {r['with_ss']:>5} {r['streak']:>6} {stop:>14}  {r['status']}")
    print("")
    print("  SS>0 = SessionStart の user command hook が走った session 数 / streak = 直近から連続で証拠なしの session 数")


# ---------------------------------------------------------------- selftest

def _write_transcript(path, cwd, ss_command=None, stop_commands=None, pad=0):
    recs = [{"type": "system", "cwd": cwd, "sessionId": "s"}]
    if ss_command is not None:
        recs.append({
            "type": "attachment", "cwd": cwd,
            "attachment": {"type": "hook_success", "hookEvent": "SessionStart",
                           "hookName": "SessionStart:startup", "command": ss_command},
        })
    recs.append({"type": "attachment", "cwd": cwd,
                 "attachment": {"type": "hook_additional_context", "hookEvent": "SessionStart",
                                "content": "host callback note"}})
    for _ in range(pad):
        recs.append({"type": "user", "cwd": cwd, "message": {"content": "x"}})
    if stop_commands is not None:
        recs.append({"type": "system", "subtype": "stop_hook_summary",
                     "hookInfos": [{"command": c} for c in stop_commands]})
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def selftest():
    fails = []

    def check(cond, label):
        print(f"  {'PASS' if cond else 'FAIL'}: {label}")
        if not cond:
            fails.append(label)

    tmp = Path(tempfile.mkdtemp())
    try:
        home = tmp / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "~/.claude/hooks/x.sh"}]}]}
        }), encoding="utf-8")
        projects = home / ".claude" / "projects"
        root_a = tmp / "work" / "A"   # kill switch
        root_b = tmp / "work" / "B"   # healthy
        root_c = tmp / "work" / "C"   # 古い 0 件 + 最新は発火 = streak 0
        root_d = tmp / "work" / "D"   # 証拠なし 2 本 (< min 3)
        for r in (root_a, root_b, root_c, root_d):
            (r / ".claude").mkdir(parents=True)
        (root_a / ".claude" / "settings.local.json").write_text(
            json.dumps({"disableAllHooks": True, "permissions": {"allow": ["Bash"]}}), encoding="utf-8")
        now = time.time()

        def mk(root, n, ss_list, stop=None):
            d = projects / ("-" + str(root).strip("/").replace("/", "-"))
            d.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                p = d / f"s{i}.jsonl"
                _write_transcript(p, str(root), ss_list[i], stop, pad=500 if i == 0 else 0)
                t = now - (n - i) * 60  # i が大きいほど新しい
                os.utime(p, (t, t))

        mk(root_a, 4, [None] * 4, stop=["callback"])
        mk(root_b, 3, ["~/.claude/hooks/x.sh"] * 3, stop=["~/.claude/hooks/stop.sh", "callback"])
        mk(root_c, 4, [None, None, None, "~/.claude/hooks/x.sh"])
        mk(root_d, 2, [None, None])
        # callback だけの SessionStart は証拠に数えない
        mk(tmp / "work" / "E", 3, ["callback"] * 3)
        managed = tmp / "managed-settings.json"  # 不在

        findings, rows = audit(home, projects, str(managed), [], 30, 3, False, True)
        byroot = {r["root"]: r for r in rows}
        joined = "\n".join(findings)
        check(any(f.startswith("🔴") and "settings.local.json" in f and "[project-local]" in f for f in findings),
              "kill switch in project-local → 🔴")
        check(byroot[str(root_a)]["status"] == "🟠", "kill-switch root: 4 session 連続証拠なし → 🟠")
        check(byroot[str(root_b)]["status"] == "ok" and byroot[str(root_b)]["with_ss"] == 3, "healthy root = ok")
        check(byroot[str(root_b)]["stop_cmd"] == 3 and byroot[str(root_b)]["stop_total"] == 3,
              "stop summary: command hook を含む件数を数える")
        check(byroot[str(root_a)]["stop_cmd"] == 0 and byroot[str(root_a)]["stop_total"] == 4,
              "stop summary: callback だけは command hook に数えない")
        check(byroot[str(root_c)]["streak"] == 0 and byroot[str(root_c)]["status"] == "ok",
              "最新 session が発火していれば古い 0 件では鳴らない")
        check(byroot[str(root_d)]["status"].startswith("recent 2"), "証拠なし 2 本 (< min 3) は finding にしない")
        check(byroot[str(tmp / "work" / "E")]["status"] == "🟠", "SessionStart の callback 記録は証拠に数えない")
        check(joined.count("🟠") == 2, f"🟠 は A と E の 2 件 (got {joined.count('🟠')})")

        # head-only (findings-only 相当) でも 🔴/🟠 は同じ
        f2, _ = audit(home, projects, str(managed), [], 30, 3, False, False)
        check(sorted(f2) == sorted(findings), "head-only scan でも finding は同一")

        # settings-only: transcript を読まずに --root の kill switch を拾う
        f3, rows3 = audit(home, projects, str(managed), [str(root_a)], 30, 3, True, False)
        check(len(f3) == 1 and f3[0].startswith("🔴") and rows3 == [], "--settings-only + --root で kill switch だけ")
        f3b, _ = audit(home, projects, str(managed), [], 30, 3, True, False)
        check(len(f3b) == 1 and "settings.local.json" in f3b[0],
              "--settings-only でも transcript 冒頭の cwd から root を発見して kill switch を拾う")

        # 除去 → 最新 session が発火 → clean
        (root_a / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {}}), encoding="utf-8")
        d = projects / ("-" + str(root_a).strip("/").replace("/", "-"))
        p = d / "s-new.jsonl"
        _write_transcript(p, str(root_a), "~/.claude/hooks/x.sh")
        f4, rows4 = audit(home, projects, str(managed), [], 30, 3, False, False)
        check(not any(str(root_a) in f or "settings.local.json" in f for f in f4), "除去 + 新 session 発火で A の finding が消える")

        # user tier の kill switch / managed の allowManagedHooksOnly / 壊れた JSON
        (home / ".claude" / "settings.json").write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
        managed.write_text(json.dumps({"allowManagedHooksOnly": True}), encoding="utf-8")
        (root_b / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        f5, _ = audit(home, projects, str(managed), [str(root_b)], 30, 3, True, False)
        j5 = "\n".join(f5)
        check("[user]" in j5 and "🔴" in j5, "user tier の kill switch → 🔴")
        check("allowManagedHooksOnly" in j5 and "[managed]" in j5, "managed の allowManagedHooksOnly → 🟠")
        check("読めない" in j5, "壊れた settings は 🟠 (判定不能) で報告し落ちない")

        # SessionStart hook が設定されていなければ streak は finding にしない
        (home / ".claude" / "settings.json").write_text(json.dumps({}), encoding="utf-8")
        managed.unlink()
        f6, rows6 = audit(home, projects, str(managed), [], 30, 3, False, False)
        check(not any(f.startswith("🟠 ") and "連続" in f for f in f6), "SessionStart hook 未設定なら streak finding なし")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    print(f"selftest: {'PASS' if not fails else 'FAIL'} ({len(fails)} failed)")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30, help="transcript の対象期間 (日、 既定 30)")
    ap.add_argument("--root", action="append", default=[], help="settings を検査する root を追加 (複数可)")
    ap.add_argument("--min-sessions", type=int, default=3, help="🟠 にする連続証拠なし session 数 (既定 3)")
    ap.add_argument("--settings-only", action="store_true",
                    help="発火証拠は見ず settings tier だけ検査 (root の発見には transcript 冒頭の cwd を使う)")
    ap.add_argument("--findings-only", action="store_true", help="finding 行だけ出す (clean なら無出力、 head だけ読む)")
    ap.add_argument("--strict", action="store_true", help="finding があれば exit 1")
    ap.add_argument("--home", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--projects-dir", default=None, help="transcript の親 dir (既定 ~/.claude/projects)")
    ap.add_argument("--managed-settings", default=None, help="managed settings の path (既定 = OS 標準)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    home = Path(a.home).expanduser() if a.home else Path.home()
    projects = Path(a.projects_dir).expanduser() if a.projects_dir else home / ".claude" / "projects"
    managed = a.managed_settings if a.managed_settings is not None else MANAGED_DEFAULT.get(sys.platform)
    deep = not a.findings_only
    findings, rows = audit(home, projects, managed, a.root, a.days, a.min_sessions, a.settings_only, deep)
    if a.findings_only:
        for f in findings:
            print(f)
    else:
        print_table(findings, rows, home, a.days, deep, a.settings_only)
    return 1 if (a.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
