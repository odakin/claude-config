#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ある session の commit を載せた push が、 他 session の (または trailer の無い) commit も一緒に公開していないかを、 各 repo の remote-tracking ref の reflog (`update by push`) と commit の `Agent-Session` trailer から事後に監査する。--selftest 内蔵。

背景: 並列 session が同じ clone を共有していると、 live checkout で `git push` した session は、 local branch に
居る**相手の未 push commit**も一緒に公開する。 予防は
[`conventions/multi-session-coordination.md#foreign-wip-scratch-worktree`](../conventions/multi-session-coordination.md#foreign-wip-scratch-worktree)
(機械化 = [`commit-from-origin-worktree.py`](commit-from-origin-worktree.py))、 本 script は**起きたかどうか**を読む側。
trailer は [`#session-provenance-trailer`](../conventions/multi-session-coordination.md#session-provenance-trailer) が付ける。

使い方:

    python3 audit-push-provenance.py --session <id-prefix>            # ~/Claude 配下の全 repo、 既定 = 直近 7 日
    python3 audit-push-provenance.py --session <id> --since '2026-09-12 00:00' --base ~/Claude

判定: push 1 回 = reflog の隣り合う 2 値の範囲 `prev..new`。 その範囲に `--session` の commit が 1 つでもあり、
かつ他の session の commit か trailer の無い commit が混ざっていれば MIXED として列挙し exit 1。
限界: reflog は clone ごと・期限つき (既定 90 日) で、 別 machine や別 clone からの push は見えない。 誰が
push したかは記録されないので、 MIXED は「その push を**した**のが誰であれ、 混ざった範囲が公開された」 の意味。
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import tempfile
from pathlib import Path


def git(repo: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout


def push_ranges(repo: Path, since: str):
    """yield (when, prev, new) for every `update by push` of the default remote-tracking ref."""
    br = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
    refs = ["refs/remotes/" + br] if br else [f"refs/remotes/origin/{b}" for b in ("main", "master")]
    for ref in refs:
        lines = git(repo, "reflog", "show", "--date=iso", "--format=%H\t%gd\t%gs", ref).splitlines()
        entries = [l.split("\t") for l in lines if l.count("\t") == 2]
        for i, (new, gd, subj) in enumerate(entries):
            if "update by push" not in subj:
                continue
            when = gd.split("{", 1)[1].rstrip("}") if "{" in gd else ""
            if when >= since:                  # the push that created the ref has no predecessor: root range
                yield when, (entries[i + 1][0] if i + 1 < len(entries) else None), new


def audit(base: Path, session: str, since: str) -> tuple[int, list[str]]:
    carrying, report = 0, []
    repos = [base] if (base / ".git").exists() else sorted(p for p in base.iterdir() if (p / ".git").exists())
    for repo in repos:
        for when, prev, new in push_ranges(repo, since):
            rows = [r.split("\t", 2) for r in git(
                repo, "log", "--format=%h\t%(trailers:key=Agent-Session,valueonly,separator=%x2C)\t%s",
                f"{prev}..{new}" if prev else new).splitlines() if r.count("\t") >= 2]
            if not any(session in s for _h, s, _t in rows):
                continue
            carrying += 1
            others = [(h, s, t) for h, s, t in rows if session not in s]
            if others:
                report.append(f"MIXED  {repo.name}  {when}  {(prev or 'root')[:7]}..{new[:7]}")
                report += [f"   {h}  {s.strip() or '(no trailer)'}  {t[:90]}" for h, s, t in rows]
    return carrying, report


def selftest() -> int:
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        T = Path(td)
        sh = lambda repo, *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(T / "remote.git")], check=True)
        base = T / "claude"
        base.mkdir()
        live = base / "repo"
        subprocess.run(["git", "clone", "-q", str(T / "remote.git"), str(live)], capture_output=True, check=True)
        sh(live, "config", "user.email", "t@t"); sh(live, "config", "user.name", "t")

        def commit(name, session):
            (live / name).write_text(name, encoding="utf-8")
            sh(live, "add", name)
            msg = f"add {name}" + (f"\n\nAgent-Session: claude:{session}" if session else "")
            sh(live, "commit", "-q", "-m", msg)

        commit("base.md", "aaaa1111")
        sh(live, "push", "-q", "-u", "origin", "main")
        commit("mine1.md", "aaaa1111")
        sh(live, "push", "-q")                                    # a pure push of mine
        commit("theirs.md", "bbbb2222")                           # another session's unpushed commit
        commit("mine2.md", "aaaa1111")
        sh(live, "push", "-q")                                    # publishes theirs along with mine
        commit("theirs-alone.md", "bbbb2222")
        sh(live, "push", "-q")                                    # their own push: not about aaaa1111
        commit("untrailered.md", "")
        commit("mine3.md", "aaaa1111")
        sh(live, "push", "-q")
        carrying, report = audit(base, "aaaa1111", "2000-01-01")
        text = "\n".join(report)
        check("every push that carried the session is counted (base, pure, mixed, untrailered)", carrying == 4)
        check("a push that published another session's commit with mine is MIXED  [foil: live push]",
              "bbbb2222" in text and text.count("MIXED") == 2)
        check("a commit with no trailer in the range is flagged too", "(no trailer)" in text)
        check("another session's own push is not attributed to this session", "theirs-alone" not in text)
        c2, r2 = audit(base, "aaaa1111", "2999-01-01")
        check("--since excludes older pushes", c2 == 0 and r2 == [])
        c3, r3 = audit(live, "aaaa1111", "2000-01-01")
        check("--base may be a single repo", c3 == 4 and len([l for l in r3 if l.startswith("MIXED")]) == 2)
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", help="a session id or a unique prefix of one")
    ap.add_argument("--since", default=(dt.datetime.now() - dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M"))
    ap.add_argument("--base", type=Path, default=Path.home() / "Claude")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.session:
        ap.error("--session is required")
    carrying, report = audit(a.base, a.session, a.since)
    if report:
        print("\n".join(report))
    print(f"[audit-push-provenance] pushes carrying {a.session} since {a.since}: {carrying}   "
          f"mixed with other or untrailered commits: {sum(1 for l in report if l.startswith('MIXED'))}")
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main())
