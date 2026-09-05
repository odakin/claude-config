#!/usr/bin/env python3
"""YAML ledger の commit cadence gate (pre-commit): 1 commit で追加される list entry (`- id:`) が N 個を超えたら refuse、escape env は hygiene log に記録 (= 「item ごとに commit」 の散文規律を git exit code で機械化。--selftest 内蔵、conventions/physics-verification-cycle.md#campaign-tooling)

Why (layer-1 hoist, 2026-09-05): a verify-to-learn worker was told "commit per item" and
committed 41 ledger items in 2 commits.  Prose discipline does not survive a cold worker
session, and desktop clients drop hook *output* — only git's exit code is honored on every
surface.  So the cadence is enforced as a pre-commit gate on the staged diff.

Usage (from a repo's hooks/pre-commit):

    python3 ~/Claude/claude-config/scripts/ledger-commit-cadence-gate.py --pre-commit \
        --glob 'campaigns/*/ledger.yaml' --max 3 --escape-env CAMPAIGN_BATCH_OK --log-name hygiene.txt

    --pre-commit    read the staged diff of every file matching --glob, count added
                    `- id:` lines, exit 1 if any file exceeds --max.
    --escape-env    if that env var is "1", let the commit through but append a line to
                    <ledger dir>/<--log-name> and stage it (violation stays visible in history
                    and in any stats script that reads the log).  Avoid `.log` for the name:
                    a global gitignore commonly ignores `*.log`.
    --selftest      exercise the diff parser on synthetic diffs.

Deliberately blind to wall-clock and token counts (not observable from git); "entries per
commit" is the cheapest proxy for "did the worker commit incrementally".  Only `- id:` list
items are counted, so edits to existing entries never trip the gate.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

ADDED_ID = re.compile(r"^\+\s*-\s*id:\s*\S")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True).stdout


def count_added_ids(diff_text: str) -> int:
    """Count `- id:` list entries added in a unified diff (context / removed lines ignored)."""
    return sum(1 for line in diff_text.splitlines() if ADDED_ID.match(line))


def staged_matching(repo: Path, pattern: str) -> list[str]:
    names = _git(repo, "diff", "--cached", "--name-only").split()
    return [n for n in names if fnmatch.fnmatch(n, pattern)]


def pre_commit(repo: Path, pattern: str, max_new: int, escape_env: str, log_name: str) -> int:
    offenders = [(rel, n) for rel in staged_matching(repo, pattern)
                 if (n := count_added_ids(_git(repo, "diff", "--cached", "--", rel))) > max_new]
    if not offenders:
        return 0
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
    return 0 if escape else 1


def selftest() -> int:
    diff_ok = "\n".join(["--- a/x", "+++ b/x", "+- id: A-01", "+  status: verified", "+- id: A-02", " - id: OLD", "-- id: GONE"])
    assert count_added_ids(diff_ok) == 2, count_added_ids(diff_ok)
    assert count_added_ids("\n".join(f"+- id: A-{i:02d}" for i in range(5))) == 5
    assert count_added_ids("+  id: not-a-list-item\n+ - id:\n") == 0
    assert fnmatch.fnmatch("campaigns/2026-09-05-x/ledger.yaml", "campaigns/*/ledger.yaml")
    assert not fnmatch.fnmatch("campaigns/TEMPLATE-spec.md", "campaigns/*/ledger.yaml")
    print("selftest OK (5 checks)")
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
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.pre_commit:
        repo = Path(a.repo) if a.repo else Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or ".")
        return pre_commit(repo.resolve(), a.glob, a.max, a.escape_env, a.log_name)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
