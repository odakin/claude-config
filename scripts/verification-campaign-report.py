#!/usr/bin/env python3
"""verify-to-learn campaign の集計: ledger.yaml (3 状態 / tier / readings) + git 由来の所要・entries per commit + efficacy proxy (受領側記入 novel_to_requester) を results.md の AUTO block に焼き、👁 未了 item を carryover.yaml に集約 (--selftest 内蔵、conventions/physics-verification-cycle.md#campaign-tooling)

Layer-1 hoist (2026-09-05) of the campaign reporter first written in a private verification
repo.  Layout assumed (schema = conventions/physics-verification-cycle.md#campaign-tooling):

    <root>/campaigns/<name>/ledger.yaml   list of items: id, status (verified|refuted|unverified),
                                           tier (🔧|👁|📄), readings [], novel_to_requester (bool,
                                           filled by the *requester* at receipt), second_eye (str)
    <root>/campaigns/<name>/results.md    human summary; this script owns one AUTO block in it
    <root>/campaigns/<name>/checks/       check_*.py / foil_*.py
    <root>/campaigns/<name>/hygiene.txt   escape-hatch log written by ledger-commit-cadence-gate.py
    <root>/carryover.yaml                 generated: 👁 ∧ not refuted ∧ no second_eye, across campaigns

Why the numbers come from git and not from the worker: a session self-reported "≈ 6 h" for a
campaign whose commits span 64 min.  Duration = first commit touching the campaign dir → the
commit that first *added* results.md (worker completion).  Efficacy proxy = number of findings
the requester did not know beforehand; the worker must not fill it (integrity ≠ efficacy).
The displayed campaign-work commit count excludes commits that only refresh this AUTO block and,
when substantive campaign changes are dirty, projects their next commit.  Otherwise `--write`
would make its own count stale by one as soon as the generated results.md was committed.
The AUTO heading deliberately has no wall-clock generation date: rerunning an unchanged campaign
on a later day must be byte-stable rather than manufacture a report-only commit.

Usage
  verification-campaign-report.py <campaign-dir> [--write]      stats (+ write AUTO block)
  verification-campaign-report.py --carryover [--write] [--root R]
  verification-campaign-report.py --selftest
"""
from __future__ import annotations

import collections
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

import yaml

AUTO_BEGIN = "<!-- AUTO-CAMPAIGN-STATS (verification-campaign-report.py --write; 手編集しない) -->"
AUTO_END = "<!-- /AUTO-CAMPAIGN-STATS -->"
LEGACY_BEGIN = "<!-- AUTO-CAMPAIGN-STATS (campaign-report.py --write; 手編集しない) -->"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True).stdout.strip()


def repo_root(start: Path) -> Path:
    top = _git(start, "rev-parse", "--show-toplevel")
    return Path(top) if top else start


def load_ledger(camp: Path) -> list[dict]:
    data = yaml.safe_load((camp / "ledger.yaml").read_text(encoding="utf-8")) or []
    return [x for x in data if isinstance(x, dict) and "id" in x]


def _git_file(repo: Path, spec: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", spec],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def _without_auto_block(text: str) -> str:
    """Remove the owned stats block while preserving all human-authored text."""
    outside = text
    for begin in (AUTO_BEGIN, LEGACY_BEGIN):
        if begin in text and AUTO_END in text:
            pre, rest = text.split(begin, 1)
            _, post = rest.split(AUTO_END, 1)
            outside = pre + post
            break
    # Inserting/removing a block necessarily changes separator blank lines;
    # those are part of the generated boundary, not substantive result prose.
    return re.sub(r"\n{3,}", "\n\n", outside).strip()


def _commit_is_auto_refresh_only(repo: Path, sha: str, rel: str) -> bool:
    """True iff a commit changes only the generated AUTO block in results.md."""
    result_path = f"{rel}/results.md"
    changed = _git(
        repo,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        sha,
        "--",
        rel,
    ).splitlines()
    if changed != [result_path]:
        return False
    before = _git_file(repo, f"{sha}^:{result_path}") or ""
    after = _git_file(repo, f"{sha}:{result_path}")
    return after is not None and _without_auto_block(before) == _without_auto_block(after)


def _has_pending_campaign_work(camp: Path, repo: Path) -> bool:
    """Detect dirty campaign content other than a generated AUTO-block refresh."""
    rel = str(camp.relative_to(repo))
    result_path = f"{rel}/results.md"
    changed = set(_git(repo, "diff", "--name-only", "HEAD", "--", rel).splitlines())
    changed.update(
        _git(repo, "ls-files", "--others", "--exclude-standard", "--", rel).splitlines()
    )
    if any(path != result_path for path in changed):
        return True
    if result_path not in changed:
        return False
    before = _git_file(repo, f"HEAD:{result_path}") or ""
    after = (camp / "results.md").read_text(encoding="utf-8") if (camp / "results.md").exists() else ""
    return _without_auto_block(before) != _without_auto_block(after)


def git_timeline(camp: Path, repo: Path) -> dict:
    rel = str(camp.relative_to(repo))
    log = _git(repo, "log", "--format=%H|%aI|%s", "--", rel)
    commits = [line.split("|", 2) for line in log.splitlines() if line]
    if not commits:
        return {"commits": 0}
    first_iso = commits[-1][1]
    work_commits = [
        row for row in commits if not _commit_is_auto_refresh_only(repo, row[0], rel)
    ]
    pending_work = _has_pending_campaign_work(camp, repo)
    added = _git(repo, "log", "--diff-filter=A", "--format=%aI", "--", f"{rel}/results.md").splitlines()
    last_iso = added[-1] if added else commits[0][1]
    per_commit = []
    for sha, iso, subj in commits:
        diff = _git(repo, "show", sha, "--format=", "--", f"{rel}/ledger.yaml")
        n = sum(1 for l in diff.splitlines() if re.match(r"^\+\s*-\s*id:\s*\S", l))
        if n:
            per_commit.append((sha[:7], iso[11:16], n, subj[:60]))
    hyg = camp / "hygiene.txt"
    first = _dt.datetime.fromisoformat(first_iso)
    last = _dt.datetime.fromisoformat(last_iso)
    return {
        "commits": len(work_commits) + int(pending_work),
        "committed_work_commits": len(work_commits),
        "raw_commits": len(commits),
        "pending_work": pending_work,
        "first": first_iso, "last": last_iso,
        "duration_min": round((last - first).total_seconds() / 60),
        "ledger_commits": per_commit,
        "max_items_per_commit": max((n for _, _, n, _ in per_commit), default=0),
        "hygiene_log": hyg.read_text(encoding="utf-8").strip().splitlines() if hyg.exists() else [],
    }


def stats(camp: Path, repo: Path) -> dict:
    L = load_ledger(camp)
    by_status = collections.Counter(x.get("status") for x in L)
    by_tier = collections.Counter(x.get("tier") for x in L)
    checks_dir = camp / "checks"
    return {
        "campaign": camp.name, "items": len(L), "status": dict(by_status), "tier": dict(by_tier),
        "readings": sum(1 for x in L if x.get("readings")),
        "checks": len(list(checks_dir.glob("check_*.py"))) if checks_dir.exists() else 0,
        "foils": len(list(checks_dir.glob("foil_*.py"))) if checks_dir.exists() else 0,
        "novel_to_requester": [x["id"] for x in L if x.get("novel_to_requester") is True],
        "novel_unrated_refuted": [x["id"] for x in L if x.get("status") == "refuted" and "novel_to_requester" not in x],
        "second_eye_open": open_eye_ids(L),
        "git": git_timeline(camp, repo),
    }


def open_eye_ids(L: list[dict]) -> list[str]:
    return [x["id"] for x in L if x.get("tier") == "👁" and x.get("status") != "refuted" and not x.get("second_eye")]


def render(s: dict) -> str:
    g = s["git"]
    lines = [AUTO_BEGIN, "**campaign stats (git-derived)**", "", "| 指標 | 値 |", "|---|---|"]
    lines.append(f"| item | {s['items']} = " + " / ".join(f"{k} {v}" for k, v in sorted(s['status'].items())) + " |")
    lines.append("| tier | " + " / ".join(f"{k} {v}" for k, v in sorted(s['tier'].items())) + f" (readings 列挙 {s['readings']}) |")
    lines.append(f"| checks / foils | {s['checks']} / {s['foils']} |")
    if g.get("commits"):
        lines.append(f"| 所要 (git: 最初の commit → results.md 初出) | {g['first'][:16]} → {g['last'][:16]} = **{g['duration_min']} 分**, campaign work commits {g['commits']} (AUTO-only refresh 除外) |")
        lines.append(f"| ledger items / commit | max {g['max_items_per_commit']} (規律 = ≤ 3; " + ("違反あり" if g['max_items_per_commit'] > 3 else "OK") + ") |")
        if g["hygiene_log"]:
            lines.append(f"| hygiene.txt | {len(g['hygiene_log'])} 件の batch 許可 |")
    nov = s["novel_to_requester"]
    lines.append(f"| **efficacy proxy** = 起票者が知らなかった finding | **{len(nov)}** ({', '.join(nov) or '—'}) |")
    if s["novel_unrated_refuted"]:
        lines.append(f"| ⚠️ refuted で novel_to_requester 未記入 | {', '.join(s['novel_unrated_refuted'])} (受領側が埋める) |")
    lines.append(f"| 👁 で第二の目待ち (carryover) | {len(s['second_eye_open'])} ({', '.join(s['second_eye_open']) or '—'}) |")
    lines.append(AUTO_END)
    return "\n".join(lines)


def write_block(camp: Path, block: str) -> None:
    res = camp / "results.md"
    text = res.read_text(encoding="utf-8") if res.exists() else f"# results — {camp.name}\n"
    begin = AUTO_BEGIN if AUTO_BEGIN in text else (LEGACY_BEGIN if LEGACY_BEGIN in text else None)
    if begin and AUTO_END in text:
        pre, rest = text.split(begin, 1)
        _, post = rest.split(AUTO_END, 1)
        text = pre + block + post
    else:
        m = re.search(r"^## ", text, flags=re.M)
        text = (text[: m.start()] + block + "\n\n" + text[m.start():]) if m else text.rstrip() + "\n\n" + block + "\n"
    res.write_text(text, encoding="utf-8")


def carryover(root: Path, write: bool) -> list[dict]:
    rows = []
    for camp in sorted((root / "campaigns").glob("*/")):
        if not (camp / "ledger.yaml").exists():
            continue
        for x in load_ledger(camp):
            if x.get("tier") == "👁" and x.get("status") != "refuted" and not x.get("second_eye"):
                # `id` first: some yaml gates count physical "- id:" lines against parsed entries
                rows.append({"id": x["id"], "campaign": camp.name, "status": x.get("status"),
                             "statement": x.get("statement", ""), "why_open": (x.get("note") or "")[:160]})
    if write:
        head = ("# carryover.yaml — 👁 item (自前導出のみ・機械 anchor なし) で第二の目が未了のもの。\n"
                "# verification-campaign-report.py --carryover --write が全 ledger から再生成する (手編集しない)。\n"
                "# 消灯 = 元 ledger の item に second_eye: \"done <date> <where>\" を書く。\n"
                "# 次 campaign の spec §C 群はここから引く (= 検証サイクルが産んだ未検証主張を campaign 内で死なせない)。\n")
        (root / "carryover.yaml").write_text(head + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return rows


def selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        camp = Path(td) / "campaigns" / "c"
        (camp / "checks").mkdir(parents=True)
        (camp / "ledger.yaml").write_text(yaml.safe_dump([
            {"id": "X-1", "status": "verified", "tier": "🔧"},
            {"id": "X-2", "status": "refuted", "tier": "👁", "novel_to_requester": True},
            {"id": "X-3", "status": "unverified", "tier": "👁"},
            {"id": "X-4", "status": "verified", "tier": "👁", "second_eye": "done 2026-09-06 note"},
            {"id": "X-5", "status": "refuted", "tier": "🔧"},
        ], allow_unicode=True), encoding="utf-8")
        L = load_ledger(camp)
        assert collections.Counter(x["status"] for x in L) == {"verified": 2, "refuted": 2, "unverified": 1}
        assert open_eye_ids(L) == ["X-3"]
        assert [x["id"] for x in L if x.get("novel_to_requester") is True] == ["X-2"]
        rendered = render(stats(camp, Path(td)))
        assert "**campaign stats (git-derived)**" in rendered
        assert str(_dt.date.today()) not in rendered
        (camp / "results.md").write_text("# r\n\nintro\n\n## 1. x\n", encoding="utf-8")
        write_block(camp, AUTO_BEGIN + "\nB1\n" + AUTO_END)
        write_block(camp, AUTO_BEGIN + "\nB2\n" + AUTO_END)
        t = (camp / "results.md").read_text(encoding="utf-8")
        assert t.count(AUTO_BEGIN) == 1 and "B2" in t and "B1" not in t and t.index(AUTO_BEGIN) < t.index("## 1. x")
        (camp / "results.md").write_text("# r\n\n" + LEGACY_BEGIN + "\nOLD\n" + AUTO_END + "\n\n## 1. x\n", encoding="utf-8")
        write_block(camp, AUTO_BEGIN + "\nNEW\n" + AUTO_END)
        t = (camp / "results.md").read_text(encoding="utf-8")
        assert LEGACY_BEGIN not in t and "NEW" in t and "OLD" not in t
        rows = carryover(Path(td), write=True)
        assert [r["id"] for r in rows] == ["X-3"] and (Path(td) / "carryover.yaml").read_text(encoding="utf-8").count("\n- id:") == 1
    # Git-backed regression: an AUTO-only commit must not increment its own
    # displayed count, while dirty substantive work must be projected once.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        camp = root / "campaigns" / "c"
        (camp / "checks").mkdir(parents=True)

        def git(*args: str) -> None:
            subprocess.run(
                ["git", "-C", str(root), *args],
                check=True,
                capture_output=True,
                text=True,
            )

        git("init")
        git("config", "user.email", "selftest@example.invalid")
        git("config", "user.name", "selftest")
        (camp / "ledger.yaml").write_text(
            yaml.safe_dump([{"id": "X-1", "status": "verified", "tier": "🔧"}], allow_unicode=True),
            encoding="utf-8",
        )
        (camp / "results.md").write_text("# r\n\n## result\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-m", "campaign work")
        assert stats(camp, root)["git"]["commits"] == 1

        write_block(camp, render(stats(camp, root)))
        git("add", ".")
        git("commit", "-m", "refresh report")
        assert stats(camp, root)["git"]["commits"] == 1

        (camp / "notes.md").write_text("substantive\n", encoding="utf-8")
        projected = render(stats(camp, root))
        assert "campaign work commits 2" in projected
        write_block(camp, projected)
        git("add", ".")
        git("commit", "-m", "more campaign work")
        assert render(stats(camp, root)) == projected
    print("selftest OK (10 checks)")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    write = "--write" in argv
    root_arg = argv[argv.index("--root") + 1] if "--root" in argv else None
    if "--carryover" in argv:
        root = Path(root_arg).resolve() if root_arg else repo_root(Path.cwd())
        rows = carryover(root, write)
        print(f"carryover: {len(rows)} 👁 item(s) open" + (" → carryover.yaml written" if write else ""))
        for r in rows:
            print(f"  {r['campaign']} {r['id']} [{r['status']}] {r['statement'][:70]}")
        return 0
    args = [a for a in argv if not a.startswith("--") and a != root_arg]
    if not args:
        print(__doc__)
        return 2
    camp = Path(args[0]).resolve()
    repo = Path(root_arg).resolve() if root_arg else repo_root(camp)
    block = render(stats(camp, repo))
    print(block)
    if write:
        write_block(camp, block)
        print(f"→ {camp / 'results.md'} updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
