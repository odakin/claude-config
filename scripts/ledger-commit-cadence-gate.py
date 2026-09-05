#!/usr/bin/env python3
"""YAML ledger の commit cadence gate (pre-commit): 1 commit で追加される list entry (`- id:`) が N 個を超えたら refuse、escape env は hygiene log に記録 + worker scope gate (= env CAMPAIGN_WORKER_DIR が立っていれば、その dir 外の staged path を refuse = worker が層1・他 dir へ書く事故の機械化)。--selftest 内蔵、conventions/physics-verification-cycle.md#campaign-tooling

Why (layer-1 hoist, 2026-09-05; scope gate 2026-09-06): a verify-to-learn worker was told
"commit per item" and committed 41 ledger items in 2 commits.  Prose discipline does not
survive a cold worker session, and desktop clients drop hook *output* — only git's exit code is
honored on every surface.  The next day, three parallel sessions each hoisted into the same
layer-1 files from one shared checkout; the requester's own file-level `git add` swept in the
workers' uncommitted hunks.  The scope gate turns "workers write only in their campaign dir"
into an exit code too.

Usage (from a repo's hooks/pre-commit):

    python3 ~/Claude/claude-config/scripts/ledger-commit-cadence-gate.py --pre-commit \\
        --glob 'campaigns/*/ledger.yaml' --max 3 --escape-env CAMPAIGN_BATCH_OK --log-name hygiene.txt \\
        --worker-scope-env CAMPAIGN_WORKER_DIR

    --pre-commit          read the staged diff of every file matching --glob, count added
                          `- id:` lines, exit 1 if any file exceeds --max.
    --escape-env          if that env var is "1", let the commit through but append a line to
                          <ledger dir>/<--log-name> and stage it (visible in history and in the
                          stats script).  Avoid `.log` for the name (global gitignores often
                          ignore `*.log`).
    --worker-scope-env    if that env var is set (repo-relative dir, e.g.
                          campaigns/2026-09-05-x), every staged path must be under it or the
                          commit is refused.  Unset = gate inert (requester session).  A worker
                          spec sets it once: `export CAMPAIGN_WORKER_DIR=campaigns/<dir>`.
    --selftest            exercise the diff parser and the scope predicate on synthetic input.

Deliberately blind to wall-clock and token counts (not observable from git); "entries per
commit" is the cheapest proxy for "did the worker commit incrementally".  Only `- id:` list
items are counted, so edits to existing entries never trip the cadence gate.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ADDED_ID = re.compile(r"^\+\s*-\s*id:\s*\S")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True).stdout


def count_added_ids(diff_text: str) -> int:
    """Count `- id:` list entries added in a unified diff (context / removed lines ignored)."""
    return sum(1 for line in diff_text.splitlines() if ADDED_ID.match(line))


def staged_paths(repo: Path) -> list[str]:
    return _git(repo, "diff", "--cached", "--name-only").split()


def staged_matching(repo: Path, pattern: str) -> list[str]:
    return [n for n in staged_paths(repo) if fnmatch.fnmatch(n, pattern)]


def out_of_scope(paths: list[str], scope_dir: str) -> list[str]:
    """Staged paths not under scope_dir (repo-relative, posix)."""
    scope = PurePosixPath(scope_dir.strip("/"))
    bad = []
    for p in paths:
        pp = PurePosixPath(p)
        if pp == scope or scope in pp.parents:
            continue
        bad.append(p)
    return bad


def pre_commit(repo: Path, pattern: str, max_new: int, escape_env: str, log_name: str, scope_env: str | None) -> int:
    rc = 0
    # --- worker scope gate ---
    if scope_env:
        scope_dir = os.environ.get(scope_env, "").strip()
        if scope_dir:
            bad = out_of_scope(staged_paths(repo), scope_dir)
            if bad:
                print(
                    f"✗ [worker-scope] {scope_env}={scope_dir} but this commit stages paths outside it:\n   "
                    + "\n   ".join(bad)
                    + "\n   Workers write only in their campaign dir; hoisting to layer 1 / other repos is the requester's job at receipt.\n"
                    f"   Unstage them (`git reset -q -- <path>`) or, if you are the requester, `unset {scope_env}`.",
                    file=sys.stderr,
                )
                rc = 1
    # --- cadence gate ---
    offenders = [(rel, n) for rel in staged_matching(repo, pattern)
                 if (n := count_added_ids(_git(repo, "diff", "--cached", "--", rel))) > max_new]
    if offenders:
        escape = os.environ.get(escape_env) == "1"
        for rel, n in offenders:
            ledger = repo / rel
            if escape:
                log = ledger.parent / log_name
                stamp = _dt.datetime.now().astimezone().isoformat(timespec="minutes")
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(f"{stamp} batch-commit {n} entries (> {max_new}) with {escape_env}=1\n")
                subprocess.run(["git", "-C", str(repo), "add", "-f", str(log.relative_to(repo))], check=False)
                print(f"⚠️ [ledger-cadence] {rel}: {n} entries in one commit (limit {max_new}); allowed by "
                      f"{escape_env}=1, logged to {log.relative_to(repo)}", file=sys.stderr)
            else:
                print(
                    f"✗ [ledger-cadence] {rel}: this commit adds {n} ledger entries (limit {max_new}).\n"
                    f"   Commit incrementally (a few entries per commit). To split now: `git reset -q {rel}`\n"
                    f"   then re-add a few entries at a time (git add -p), or set {escape_env}=1 to force\n"
                    f"   (logged to {log_name} next to the ledger).",
                    file=sys.stderr,
                )
                rc = 1
    return rc


def selftest() -> int:
    diff_ok = "\n".join(["--- a/x", "+++ b/x", "+- id: A-01", "+  status: verified", "+- id: A-02", " - id: OLD", "-- id: GONE"])
    assert count_added_ids(diff_ok) == 2, count_added_ids(diff_ok)
    assert count_added_ids("\n".join(f"+- id: A-{i:02d}" for i in range(5))) == 5
    assert count_added_ids("+  id: not-a-list-item\n+ - id:\n") == 0
    assert fnmatch.fnmatch("campaigns/2026-09-05-x/ledger.yaml", "campaigns/*/ledger.yaml")
    assert not fnmatch.fnmatch("campaigns/TEMPLATE-spec.md", "campaigns/*/ledger.yaml")
    paths = ["campaigns/c1/ledger.yaml", "campaigns/c1/checks/x.py", "campaigns/c2/results.md", "SESSION.md"]
    assert out_of_scope(paths, "campaigns/c1") == ["campaigns/c2/results.md", "SESSION.md"]
    assert out_of_scope(paths, "campaigns/c1/") == ["campaigns/c2/results.md", "SESSION.md"]
    assert out_of_scope(["campaigns/c10/ledger.yaml"], "campaigns/c1") == ["campaigns/c10/ledger.yaml"]  # prefix ≠ parent
    print("selftest OK (8 checks)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pre-commit", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--repo", default=None, help="git repo (default: toplevel of cwd)")
    ap.add_argument("--glob", default="campaigns/*/ledger.yaml")
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--escape-env", default="LEDGER_BATCH_OK")
    ap.add_argument("--log-name", default="hygiene.txt")
    ap.add_argument("--worker-scope-env", default=None, help="env var naming the worker's repo-relative dir; unset var = inert")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.pre_commit:
        repo = Path(a.repo) if a.repo else Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or ".")
        return pre_commit(repo.resolve(), a.glob, a.max, a.escape_env, a.log_name, a.worker_scope_env)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
