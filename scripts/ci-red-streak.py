#!/usr/bin/env python3
"""GitHub Actions の red streak を起点まで遡る (現状・最後の green・最初の red run・失敗行・原因 commit)。

Usage:
  ci-red-streak.py [--repo OWNER/REPO] [--workflow NAME] [--branch BRANCH]
                   [--event EVENT] [--limit N] [--git-dir DIR]
                   [--failed-lines [REGEX]] [--pickaxe STRING [--path PATH]] [--brief]
  ci-red-streak.py --selftest

Answers, in the order conventions/debugging-discipline.md#ci-red-streak-forensics
uses them:
  1. Is the latest completed run red? Re-query this before acting on a handed-off
     premise such as "CI has failed for 100 runs": the fix may already be in.
  2. The current red streak, or when green the most recent streak that ended:
     last green run -> first red run, its length, and the run that ended it.
  3. --failed-lines: lines of `gh run view <first red> --log-failed` that match
     REGEX (default below). Job/step/timestamp prefixes are stripped.
  4. --pickaxe STRING: `git log -S STRING` lists the commits that changed the
     number of occurrences of STRING; for each, the first run (oldest first)
     whose head contains it (`git merge-base --is-ancestor`) and the run before.
     Runs are per push (head SHA), not per commit, so a red run can carry
     several commits; pickaxe names the one that introduced the failing line.
     Run heads must exist in --git-dir (fetch first); missing ones are counted.

Streak arithmetic counts only completed runs: success = green; failure,
timed_out, startup_failure = red; every other conclusion is ignored.
Defaults: --branch main --event push (pull_request runs of other heads would
interleave; pass an empty string to drop a filter), --limit 400, and the repo
from `gh repo view` in --git-dir.

--brief prints one line only when the latest run is red (silent when green),
for a session-start surface.

Exit: 0 latest completed run green or no runs / 1 latest red / 2 gh, git or
usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

GREEN = {"success"}
RED = {"failure", "timed_out", "startup_failure"}
# Failure markers, not every line that mentions FAIL/Error: passing summaries such as
# "PASS=74 FAIL=0", "FAIL 0 件" or "→ LookupError" must not match.
DEFAULT_FAIL_RE = r"✗|FAIL at line|\bFAILED\b|##\[error\]|cannot |No such file|Traceback|\berror:"
FIELDS = "databaseId,headSha,status,conclusion,createdAt,event,url"
LOG_PREFIX = re.compile(r"^[^\t]*\t[^\t]*\t(?:\d{4}-\d\d-\d\dT[\d:.]+Z ?)?")


class ToolError(RuntimeError):
    pass


def sh(cmd: list[str], cwd: str | None = None) -> str:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise ToolError(f"{cmd[0]}: not found") from e
    if p.returncode != 0:
        raise ToolError(f"{' '.join(cmd)}: {p.stderr.strip() or 'exit ' + str(p.returncode)}")
    return p.stdout


def classified(runs: list[dict]) -> list[dict]:
    """Completed green/red runs, in the given (gh = newest first) order."""
    out = []
    for r in runs:
        if r.get("status") not in (None, "completed"):
            continue
        if r.get("conclusion") in GREEN or r.get("conclusion") in RED:
            out.append(r)
    return out


def analyze(runs: list[dict]) -> dict:
    """runs newest first -> latest state and the newest red streak in the window."""
    seq = classified(runs)
    res = {
        "scanned": len(seq),
        "latest": seq[0] if seq else None,
        "latest_red": bool(seq) and seq[0]["conclusion"] in RED,
        "streak": None,
    }
    j = 0
    while j < len(seq) and seq[j]["conclusion"] not in RED:
        j += 1
    if j == len(seq):
        return res
    k = j
    while k < len(seq) and seq[k]["conclusion"] in RED:
        k += 1
    res["streak"] = {
        "length": k - j,
        "newest_red": seq[j],
        "first_red": seq[k - 1],
        "last_green": seq[k] if k < len(seq) else None,
        "ended_by": seq[j - 1] if j > 0 else None,
        "window_exhausted": k == len(seq),
    }
    return res


def log_message(line: str) -> str:
    """Strip the `job<TAB>step<TAB>timestamp ` prefix of a `gh run view --log*` line."""
    return LOG_PREFIX.sub("", line, count=1)


def is_ancestor(git_dir: str, anc: str, desc: str) -> bool | None:
    p = subprocess.run(["git", "-C", git_dir, "merge-base", "--is-ancestor", anc, desc],
                       capture_output=True)
    if p.returncode in (0, 1):
        return p.returncode == 0
    return None  # an object is not in the local repository


def first_containing(git_dir: str, commit: str, asc: list[dict]):
    """First run (oldest first) whose head contains commit, the run before it, unknown heads."""
    prev, unknown = None, 0
    for r in asc:
        ok = is_ancestor(git_dir, commit, r["headSha"])
        if ok is None:
            unknown += 1
            continue
        if ok:
            return r, prev, unknown
        prev = r
    return None, prev, unknown


def fmt(r: dict | None) -> str:
    if not r:
        return "-"
    return f"{r['databaseId']} {r['headSha'][:7]} {r['conclusion']} {r['createdAt']}"


def pickaxe_report(a, runs: list[dict]) -> None:
    cmd = ["git", "-C", a.git_dir, "log", "--reverse", "--format=%H %h %cs %s", "-S", a.pickaxe]
    if a.path:
        cmd += ["--", a.path]
    lines = [ln for ln in sh(cmd).splitlines() if ln.strip()]
    where = f" in {a.path}" if a.path else ""
    print(f"pickaxe {a.pickaxe!r}{where}: {len(lines)} commit(s), oldest first")
    asc = list(reversed(classified(runs)))
    for ln in lines:
        full, rest = ln.split(" ", 1)
        first, prev, unknown = first_containing(a.git_dir, full, asc)
        print(f"  {rest}")
        print(f"    first run containing it: {fmt(first)}")
        print(f"    run before it:           {fmt(prev)}")
        if unknown:
            print(f"    ({unknown} run head(s) not in {a.git_dir}: fetch and rerun)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo", help="OWNER/REPO (default: gh repo view in --git-dir)")
    ap.add_argument("--workflow", help="workflow name or file (default: all)")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--event", default="push")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--git-dir", default=".")
    ap.add_argument("--failed-lines", nargs="?", const=DEFAULT_FAIL_RE, default=None,
                    metavar="REGEX")
    ap.add_argument("--pickaxe", metavar="STRING")
    ap.add_argument("--path", help="limit --pickaxe to this path")
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.path and not a.pickaxe:
        ap.error("--path needs --pickaxe")
    try:
        repo = a.repo or sh(["gh", "repo", "view", "--json", "nameWithOwner",
                             "-q", ".nameWithOwner"], cwd=a.git_dir).strip()
        cmd = ["gh", "run", "list", "--repo", repo, "--limit", str(a.limit), "--json", FIELDS]
        if a.workflow:
            cmd += ["--workflow", a.workflow]
        if a.branch:
            cmd += ["--branch", a.branch]
        if a.event:
            cmd += ["--event", a.event]
        runs = json.loads(sh(cmd) or "[]")
        res = analyze(runs)
        st = res["streak"]
        scope = (f"{repo} workflow={a.workflow or '(all)'} branch={a.branch or '(all)'} "
                 f"event={a.event or '(all)'}")
        if a.brief:
            if res["latest_red"]:
                more = "+" if st["window_exhausted"] else ""
                fr = st["first_red"]
                print(f"🔴 CI red: {scope} — {st['length']}{more} runs since {fr['createdAt']} "
                      f"(first red {fr['headSha'][:7]}, run {fr['databaseId']})")
            return 1 if res["latest_red"] else 0
        print(f"scope: {scope} ({res['scanned']} completed green/red runs of {len(runs)} listed)")
        if not res["latest"]:
            print("no completed green/red runs")
            return 0
        print(f"latest: {fmt(res['latest'])}")
        if st is None:
            print("state: GREEN, no red run in the window")
        else:
            more = "+" if st["window_exhausted"] else ""
            if res["latest_red"]:
                print(f"state: RED — streak of {st['length']}{more} runs is ongoing")
            else:
                print(f"state: GREEN — most recent red streak ({st['length']}{more} runs) "
                      f"ended by {fmt(st['ended_by'])}")
            tail = "  (window exhausted: raise --limit)" if st["window_exhausted"] else ""
            print(f"  last green before: {fmt(st['last_green'])}{tail}")
            print(f"  first red:         {fmt(st['first_red'])}  {st['first_red'].get('url', '')}")
            print(f"  newest red:        {fmt(st['newest_red'])}")
            if a.failed_lines is not None:
                rx = re.compile(a.failed_lines)
                rid = str(st["first_red"]["databaseId"])
                log = sh(["gh", "run", "view", rid, "--repo", repo, "--log-failed"])
                hits = [log_message(ln) for ln in log.splitlines() if rx.search(ln)]
                print(f"failed lines of run {rid} (/{a.failed_lines}/, {len(hits)} hit(s)):")
                for h in hits[:40]:
                    print(f"  {h}")
        if a.pickaxe:
            pickaxe_report(a, runs)
        return 1 if res["latest_red"] else 0
    except (ToolError, json.JSONDecodeError, re.error) as e:
        print(f"ci-red-streak: {e}", file=sys.stderr)
        return 2


def selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def ok(name: str, cond) -> None:
        checks.append((name, bool(cond)))

    def run(i: int, concl, status: str = "completed", sha: str | None = None) -> dict:
        return {"databaseId": i, "headSha": sha or f"{i:07d}deadbeef", "status": status,
                "conclusion": concl, "createdAt": f"2026-01-01T00:00:{i:02d}Z"}

    a = analyze([run(5, "failure"), run(4, "failure"), run(3, "success"),
                 run(2, "failure"), run(1, "success")])
    ok("ongoing streak: latest red", a["latest_red"])
    ok("ongoing streak: length 2", a["streak"]["length"] == 2)
    ok("ongoing streak: first red 4, last green 3",
       a["streak"]["first_red"]["databaseId"] == 4 and a["streak"]["last_green"]["databaseId"] == 3)
    ok("ongoing streak: nothing ended it", a["streak"]["ended_by"] is None)

    b = analyze([run(6, "success"), run(5, "success"), run(4, "failure"), run(3, "timed_out"),
                 run(2, "failure"), run(1, "success")])
    ok("ended streak: latest green", not b["latest_red"])
    ok("ended streak: length 3 incl. timed_out", b["streak"]["length"] == 3)
    ok("ended streak: first red 2, last green 1, ended by 5",
       b["streak"]["first_red"]["databaseId"] == 2 and b["streak"]["last_green"]["databaseId"] == 1
       and b["streak"]["ended_by"]["databaseId"] == 5)

    c = analyze([run(3, "success"), run(2, "success"), run(1, "success")])
    ok("all green: no streak", c["streak"] is None and not c["latest_red"])

    d = analyze([run(6, "cancelled"), run(5, None, "in_progress"), run(4, "failure"),
                 run(3, "skipped"), run(2, "failure"), run(1, "success")])
    ok("ignored conclusions: latest is 4", d["latest"]["databaseId"] == 4)
    ok("ignored conclusions: streak 2 across a skipped run",
       d["streak"]["length"] == 2 and d["streak"]["first_red"]["databaseId"] == 2)

    e = analyze([run(2, "failure"), run(1, "startup_failure")])
    ok("window exhausted", e["streak"]["window_exhausted"] and e["streak"]["last_green"] is None
       and e["streak"]["length"] == 2)

    f = analyze([])
    ok("empty", f["latest"] is None and f["streak"] is None and not f["latest_red"])

    ok("log prefix stripped",
       log_message("checks\tRun all checks\t2026-09-11T06:21:43.2691686Z stat: cannot read")
       == "stat: cannot read")
    ok("log line without timestamp", log_message("job\tstep\tplain") == "plain")
    ok("default regex hits the run-all-checks summary",
       re.search(DEFAULT_FAIL_RE, "  ✗ test: setup-codex.test.sh") is not None)
    for passing in ("  === Result: PASS=7 FAIL=0 ===", " run-all-checks: PASS=74 FAIL=0",
                    "✅ xlsx clean (記入済): FAIL 0 件 (期待 0)", "✓ A label not found → LookupError"):
        ok(f"default regex skips passing line {passing.strip()[:28]!r}",
           re.search(DEFAULT_FAIL_RE, passing) is None)
    for failing in ("codex-hooks.test.sh: FAIL at line 136: git -C x branch",
                    "##[error]Process completed with exit code 1.",
                    "stat: cannot read file system information for '%Lp': No such file or directory"):
        ok(f"default regex hits failing line {failing[:28]!r}",
           re.search(DEFAULT_FAIL_RE, failing) is not None)

    env = dict(os.environ, GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="noreply@github.com",
               GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="noreply@github.com")
    with tempfile.TemporaryDirectory() as td:
        def g(*args: str) -> str:
            return subprocess.run(["git", "-C", td, "-c", "commit.gpgsign=false", *args],
                                  capture_output=True, text=True, env=env, check=True).stdout.strip()
        try:
            g("init", "-q", "--template=")
            shas = []
            for i, body in enumerate(["a\n", "a\nNEEDLE\n", "a\nNEEDLE\nb\n"]):
                with open(os.path.join(td, "f.txt"), "w", encoding="utf-8") as fh:
                    fh.write(body)
                g("add", "f.txt")
                g("commit", "-q", "-m", f"c{i}")
                shas.append(g("rev-parse", "HEAD"))
            asc = [run(i + 1, cl, sha=s) for i, (s, cl) in
                   enumerate(zip(shas, ["success", "failure", "failure"]))]
            intro = g("log", "--reverse", "--format=%H", "-S", "NEEDLE").splitlines()[0]
            ok("pickaxe: introducing commit is c1", intro == shas[1])
            first, prev, unknown = first_containing(td, intro, asc)
            ok("pickaxe: first run containing it 2, run before 1",
               first["databaseId"] == 2 and prev["databaseId"] == 1 and unknown == 0)
            first, prev, unknown = first_containing(td, intro, [run(9, "success", sha="0" * 40)] + asc)
            ok("pickaxe: unfetched run head counted, not fatal",
               unknown == 1 and first["databaseId"] == 2)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            ok(f"git fixture ({exc})", False)

    bad = [n for n, c in checks if not c]
    for n in bad:
        print(f"FAIL: {n}")
    print(f"ci-red-streak selftest: {len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
