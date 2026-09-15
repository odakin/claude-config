#!/usr/bin/env python3
"""Surface unresolved deployment check-runs for recent default-branch commits.

The engine queries GitHub's commits and check-runs APIs through `gh`. A named
check that succeeds closes the older failure chain; failures, long-running
checks, and checks still absent after the grace period are reported. Callers
provide one or more repositories, so owner inventory remains outside layer 1.
The detector is report-only and exits zero after a valid run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Callable, Optional, Union


JsonValue = Optional[Union[dict, list]]
Fetcher = Callable[[list[str]], JsonValue]


def gh_json(arguments: list[str]) -> JsonValue:
    try:
        result = subprocess.run(
            ["gh", "api", *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def audit_repo(
    repo: str,
    now: datetime,
    *,
    fetch: Fetcher = gh_json,
    check_name: str = "Cloudflare Pages",
    stuck_minutes: int = 30,
    lookback: int = 8,
    age_hours: int = 24,
) -> tuple[list[dict[str, object]], bool]:
    """Return findings and whether the GitHub API was readable."""
    commits = fetch([f"repos/{repo}/commits?per_page={lookback}"])
    if not isinstance(commits, list):
        return [], False
    findings: list[dict[str, object]] = []
    readable = True
    for commit in commits:
        if not isinstance(commit, dict):
            continue
        sha = str(commit.get("sha") or "")
        commit_data = commit.get("commit") or {}
        author_data = commit_data.get("author") or {} if isinstance(commit_data, dict) else {}
        commit_time = parse_iso(str(author_data.get("date") or ""))
        if not sha or commit_time is None:
            continue
        age_min = (now - commit_time).total_seconds() / 60
        if age_min > age_hours * 60:
            continue
        checks = fetch([f"repos/{repo}/commits/{sha}/check-runs"])
        if not isinstance(checks, dict):
            readable = False
            continue
        runs = checks.get("check_runs") or []
        named = next(
            (run for run in runs if isinstance(run, dict) and run.get("name") == check_name),
            None,
        )
        message = str(commit_data.get("message") or "").split("\n", 1)[0][:60]
        base = {
            "repo": repo,
            "sha": sha[:7],
            "age_min": round(age_min),
            "message": message,
        }
        if named is None:
            if age_min > stuck_minutes:
                findings.append(
                    {
                        **base,
                        "severity": "WARN",
                        "detail": f"{check_name} check-run absent after {round(age_min)} minutes",
                    }
                )
            continue
        status = str(named.get("status") or "")
        conclusion = str(named.get("conclusion") or "")
        if conclusion == "success":
            break
        if conclusion == "failure":
            findings.append(
                {
                    **base,
                    "severity": "CRITICAL",
                    "detail": f"{check_name} failed",
                    "details_url": named.get("details_url") or named.get("html_url") or "",
                }
            )
        elif status == "in_progress" and age_min > stuck_minutes:
            findings.append(
                {
                    **base,
                    "severity": "WARN",
                    "detail": f"{check_name} still in progress after {round(age_min)} minutes",
                }
            )
    return findings, readable


def format_findings(findings: list[dict[str, object]], check_name: str) -> str:
    if not findings:
        return ""
    order = {"CRITICAL": 0, "WARN": 1}
    findings.sort(
        key=lambda item: (order.get(str(item["severity"]), 9), int(item["age_min"]))
    )
    lines = ["", "=" * 64, f"Deployment status: {check_name}", "=" * 64, ""]
    for finding in findings:
        icon = "CRITICAL" if finding["severity"] == "CRITICAL" else "WARN"
        lines.append(
            f"{icon} {finding['repo']} {finding['sha']} ({finding['age_min']} minutes ago)"
        )
        lines.append(f"    {finding['detail']}")
        if finding.get("message"):
            lines.append(f"    commit: {finding['message']}")
        if finding.get("details_url"):
            lines.append(f"    details: {finding['details_url']}")
    lines.append("")
    return "\n".join(lines)


def run_selftest() -> int:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def commit(sha: str, minutes: int) -> dict[str, object]:
        stamp = datetime.fromtimestamp(now.timestamp() - minutes * 60, timezone.utc)
        return {
            "sha": sha,
            "commit": {"author": {"date": stamp.isoformat()}, "message": f"change {sha}"},
        }

    def fake_fetch(mapping: dict[str, JsonValue]) -> Fetcher:
        return lambda arguments: mapping.get(arguments[0])

    commits_path = "repos/example/site/commits?per_page=8"
    checks = lambda sha: f"repos/example/site/commits/{sha}/check-runs"
    cases: list[tuple[str, dict[str, JsonValue], list[str], bool]] = [
        (
            "success closes older failures",
            {
                commits_path: [commit("newsuccess", 5), commit("oldfailure", 20)],
                checks("newsuccess"): {"check_runs": [{"name": "Cloudflare Pages", "status": "completed", "conclusion": "success"}]},
                checks("oldfailure"): {"check_runs": [{"name": "Cloudflare Pages", "status": "completed", "conclusion": "failure"}]},
            },
            [],
            True,
        ),
        (
            "failure is reported",
            {
                commits_path: [commit("badcommit", 10)],
                checks("badcommit"): {"check_runs": [{"name": "Cloudflare Pages", "status": "completed", "conclusion": "failure"}]},
            },
            ["CRITICAL"],
            True,
        ),
        (
            "missing check after grace is reported",
            {
                commits_path: [commit("nocheckxx", 45)],
                checks("nocheckxx"): {"check_runs": []},
            },
            ["WARN"],
            True,
        ),
        (
            "unreadable API is not healthy",
            {commits_path: None},
            [],
            False,
        ),
    ]
    ok = True
    for label, mapping, severities, expected_readable in cases:
        findings, readable = audit_repo(
            "example/site", now, fetch=fake_fetch(mapping)
        )
        passed = [str(item["severity"]) for item in findings] == severities and readable == expected_readable
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    sample = [
        {"severity": "WARN", "repo": "example/site", "sha": "warn123", "age_min": 4, "message": "w", "detail": "d"},
        {"severity": "CRITICAL", "repo": "example/site", "sha": "crit123", "age_min": 8, "message": "c", "detail": "d"},
    ]
    rendered = format_findings(sample, "Cloudflare Pages")
    ordered = rendered.index("crit123") < rendered.index("warn123")
    print(f"  [{'PASS' if ordered else 'FAIL'}] critical findings sort first")
    ok = ok and ordered
    print("check-pages-deploy selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--check-name", default="Cloudflare Pages")
    parser.add_argument("--stuck-minutes", type=int, default=30)
    parser.add_argument("--lookback", type=int, default=8)
    parser.add_argument("--age-hours", type=int, default=24)
    parser.add_argument("--quiet-if-clean", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return run_selftest()
    if not args.repo:
        parser.error("at least one --repo is required")
    now = datetime.now(timezone.utc)
    all_findings: list[dict[str, object]] = []
    unreadable: list[str] = []
    for repo in dict.fromkeys(args.repo):
        findings, readable = audit_repo(
            repo,
            now,
            check_name=args.check_name,
            stuck_minutes=args.stuck_minutes,
            lookback=args.lookback,
            age_hours=args.age_hours,
        )
        all_findings.extend(findings)
        if not readable:
            unreadable.append(repo)
    output = format_findings(all_findings, args.check_name)
    if output:
        print(output)
    if unreadable:
        print(
            "Deployment status not checked (GitHub API unavailable): "
            + ", ".join(unreadable)
        )
    elif not output and not args.quiet_if_clean:
        print(f"Deployment status healthy: {args.check_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
