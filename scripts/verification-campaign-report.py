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

Foil exit contract (2026-09-06, after four campaigns used three different conventions and a
requester-side `$?` bug produced a false "foils have no teeth"): a foil is a *test of the
check*.  It must print a line starting with `FOIL-TEETH` when the check correctly rejects
the broken input (and exit 0), or `FOIL-BROKEN` when the check let it through (exit 1).
Legacy foils without the marker are classified by phrase (`expected for a foil` /
`FAIL as expected` / `EXPECTED FAIL` ⇒ teeth) and reported as `legacy`.  `--run` executes
check_*.py (expect exit 0) and foil_*.py under this contract with a per-script timeout and
records the result in the AUTO block, so the receiver never hand-rolls the loop again.

State machine (derived, never recorded — conventions/verification-cycle-ops.md):
  spec      spec.md only, no ledger items           → worker not started
  running   ledger has items, no results.md
  done      results.md exists but receipt incomplete (refuted without novel_to_requester,
            or no AUTO block)                        → 未受領 (requester action)
  received  receipt complete, but no retro lists it   → retro 未記入
  retro'd   listed in campaigns/retros/*.md front matter `campaigns:`
`improvements.yaml` (repo root) is the fate ledger of retro proposals: status deferred items
with review_by ≤ today (or none) are surfaced; implemented items are inert.

Usage
  verification-campaign-report.py <campaign-dir> [--write] [--run [--timeout SEC]]   stats (+ run checks/foils, + write AUTO block)
  verification-campaign-report.py --index [--write] [--root R]    derived state + efficacy dataset → campaigns/INDEX.md
  verification-campaign-report.py --surface [--root R]            findings only (dashboard / SessionStart), silent when none
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


FOIL_LEGACY_TEETH = ("expected for a foil", "FAIL as expected", "EXPECTED FAIL")


def run_checks(camp: Path, timeout: int = 600) -> dict:
    """Run check_*.py (expect exit 0) and foil_*.py (foil exit contract). Exit codes captured directly."""
    checks_dir = camp / "checks"
    out = {"checks": [], "foils": []}
    if not checks_dir.exists():
        return out
    for f in sorted(checks_dir.glob("check_*.py")):
        try:
            pr = subprocess.run([sys.executable, str(f)], cwd=str(checks_dir), capture_output=True, text=True, timeout=timeout)
            out["checks"].append((f.name, "PASS" if pr.returncode == 0 else f"FAIL(exit {pr.returncode})"))
        except subprocess.TimeoutExpired:
            out["checks"].append((f.name, f"TIMEOUT({timeout}s)"))
    for f in sorted(checks_dir.glob("foil_*.py")):
        try:
            pr = subprocess.run([sys.executable, str(f)], cwd=str(checks_dir), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            out["foils"].append((f.name, f"TIMEOUT({timeout}s)", "-")); continue
        text = (pr.stdout or "") + (pr.stderr or "")
        if "FOIL-TEETH" in text:
            verdict, conv = ("teeth" if pr.returncode == 0 else "teeth(marker, but exit≠0)"), "standard"
        elif "FOIL-BROKEN" in text:
            verdict, conv = "BROKEN", "standard"
        elif any(k in text for k in FOIL_LEGACY_TEETH):
            verdict, conv = "teeth", "legacy"
        else:
            verdict, conv = ("teeth?" if pr.returncode != 0 else "BROKEN?"), "legacy-exit-only"
        out["foils"].append((f.name, verdict, conv))
    return out


def render_run(r: dict) -> str:
    if not r["checks"] and not r["foils"]:
        return ""
    c_pass = sum(1 for _, v in r["checks"] if v == "PASS")
    f_teeth = sum(1 for _, v, _ in r["foils"] if v.startswith("teeth"))
    convs = sorted({c for _, _, c in r["foils"]})
    bad = [f"{n}:{v}" for n, v in r["checks"] if v != "PASS"] + [f"{n}:{v}" for n, v, _ in r["foils"] if not v.startswith("teeth")]
    return (f"| **実走 (--run)** | checks {c_pass}/{len(r['checks'])} PASS, foils {f_teeth}/{len(r['foils'])} teeth "
            f"(contract: {', '.join(convs) or '—'})" + (f" ⚠️ {'; '.join(bad)}" if bad else "") + " |")


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
    if s.get('run'):
        row = render_run(s['run'])
        if row:
            lines.append(row)
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


def _front_matter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
    return fm if isinstance(fm, dict) else {}


def load_retros(root: Path) -> list[dict]:
    out = []
    for f in sorted((root / "campaigns" / "retros").glob("*.md")):
        fm = _front_matter(f.read_text(encoding="utf-8"))
        fm["_file"] = f.name
        out.append(fm)
    return out


def load_improvements(root: Path) -> list[dict]:
    f = root / "improvements.yaml"
    if not f.exists():
        return []
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or []
    return [x for x in data if isinstance(x, dict) and "id" in x]


def campaign_state(camp: Path, repo: Path, retros: list[dict]) -> dict:
    ledger = load_ledger(camp) if (camp / "ledger.yaml").exists() else []
    results = camp / "results.md"
    has_results = results.exists()
    text = results.read_text(encoding="utf-8") if has_results else ""
    has_auto = AUTO_BEGIN in text or LEGACY_BEGIN in text
    unrated = [x["id"] for x in ledger if x.get("status") == "refuted" and "novel_to_requester" not in x]
    in_retro = [r["_file"] for r in retros if camp.name in (r.get("campaigns") or [])]
    if not ledger and not has_results:
        state = "spec"
    elif not has_results:
        state = "running"
    elif unrated or not has_auto:
        state = "done"
    elif not in_retro:
        state = "received"
    else:
        state = "retro'd"
    st = stats(camp, repo) if ledger else {"items": 0, "status": {}, "tier": {}, "novel_to_requester": [], "second_eye_open": [], "checks": 0, "foils": 0, "git": git_timeline(camp, repo)}
    contamination = 0
    for r in retros:
        c = r.get("contamination") or {}
        if isinstance(c, dict):
            contamination += int(c.get(camp.name, 0) or 0)
    return {"campaign": camp.name, "state": state, "unrated": unrated, "retro": in_retro, "contamination": contamination, **{k: st[k] for k in ("items", "status", "tier", "novel_to_requester", "second_eye_open", "checks", "foils", "git")}}


def index(root: Path) -> dict:
    retros = load_retros(root)
    camps = [c for c in sorted((root / "campaigns").glob("*/")) if (c / "spec.md").exists() and c.name != "retros"]
    rows = [campaign_state(c, root, retros) for c in camps]
    return {"campaigns": rows, "retros": retros, "improvements": load_improvements(root),
            "carryover": len(yaml.safe_load((root / "carryover.yaml").read_text(encoding="utf-8")) or []) if (root / "carryover.yaml").exists() else None}


def render_index(ix: dict) -> str:
    L = ["# campaigns/INDEX.md — 導出 state と efficacy dataset (verification-campaign-report.py --index --write が再生成、手編集しない)", "",
         f"生成 {_dt.date.today()}。state は file から導出 (spec / running / done=未受領 / received=retro 未記入 / retro'd)。数字は ledger + git 由来。", "",
         "| campaign | state | items | verified / refuted / unverified | 👁 | novel (受領側) | checks / foils | 所要 (分) | items/commit max | 汚染 hit | retro |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    tot = {"items": 0, "novel": 0, "refuted": 0}
    for r in ix["campaigns"]:
        stt = r["status"]; g = r["git"]
        L.append(f"| `{r['campaign']}` | **{r['state']}** | {r['items']} | {stt.get('verified',0)} / {stt.get('refuted',0)} / {stt.get('unverified',0)} | {r['tier'].get('👁',0)} | {len(r['novel_to_requester'])} | {r['checks']} / {r['foils']} | {g.get('duration_min','—')} | {g.get('max_items_per_commit','—')} | {r['contamination']} | {', '.join(r['retro']) or '—'} |")
        tot["items"] += r["items"]; tot["novel"] += len(r["novel_to_requester"]); tot["refuted"] += stt.get("refuted", 0)
    L += ["", f"**累計**: campaigns {len(ix['campaigns'])} / items {tot['items']} / refuted {tot['refuted']} / novel_to_requester {tot['novel']} / carryover open {ix['carryover'] if ix['carryover'] is not None else '—'}", ""]
    imps = ix["improvements"]
    if imps:
        L += ["## improvements.yaml (retro 提案の fate 台帳)", "", "| id | origin | status | mechanism / where | trigger / review_by |", "|---|---|---|---|---|"]
        for i in imps:
            L.append(f"| {i['id']} | {i.get('origin','')} | **{i.get('status','')}** | {i.get('where') or i.get('mechanism','')} | {i.get('trigger') or ''} {('(review_by ' + str(i['review_by']) + ')') if i.get('review_by') else ''} |")
    return "\n".join(L) + "\n"


def surface(ix: dict, today: "_dt.date | None" = None) -> list[str]:
    today = today or _dt.date.today()
    out = []
    for r in ix["campaigns"]:
        if r["state"] == "done":
            out.append(f"📥 未受領: `{r['campaign']}` に results.md あり、受領未完 (refuted の novel_to_requester 未記入: {', '.join(r['unrated']) or '—'} / AUTO block) → 汚染 grep → 独立再実装 → ledger 記入 → --run --write → marker consume")
        elif r["state"] == "received":
            out.append(f"📝 retro 未記入: `{r['campaign']}` は受領済だが campaigns/retros/*.md の front matter `campaigns:` に無い → TEMPLATE-retro.md から書く (提案は gate / rule+trigger / rejected の 3 択 + improvements.yaml)")
        elif r["state"] == "spec":
            fi = r["git"].get("first")
            if fi:
                age = (today - _dt.datetime.fromisoformat(fi).date()).days
                if age >= 3:
                    out.append(f"⏳ 起票のみ {age} 日: `{r['campaign']}` に ledger item も results も無い → worker が走っていない (chip 未クリック / 死亡) → spawn し直すか abandon を DESIGN に")
    for i in ix["improvements"]:
        if i.get("status") == "deferred":
            rb = i.get("review_by")
            if rb is None:
                out.append(f"🕰 deferred に時計なし: improvements `{i['id']}` — review_by を入れる (時計の無い deferred は拾われない)")
            else:
                try:
                    d = rb if isinstance(rb, _dt.date) else _dt.date.fromisoformat(str(rb))
                except Exception:
                    d = None
                if d and d <= today:
                    out.append(f"🕰 deferred の見直し期日: improvements `{i['id']}` (review_by {d}) — trigger『{i.get('trigger','')}』は立ったか判断 → implemented / rejected / review_by 延長")
    co = ix.get("carryover")
    if co is not None and co >= 12:
        out.append(f"🧾 carryover {co} item — 次 campaign の C 群へ (教科書に効く item を優先、閾値 12)")
    return out


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
    with tempfile.TemporaryDirectory() as td:
        camp = Path(td) / "campaigns" / "r"
        (camp / "checks").mkdir(parents=True)
        (camp / "checks" / "check_ok.py").write_text("import sys; print('PASS'); sys.exit(0)\n", encoding="utf-8")
        (camp / "checks" / "check_bad.py").write_text("import sys; sys.exit(3)\n", encoding="utf-8")
        (camp / "checks" / "foil_std.py").write_text("print('FOIL-TEETH: rejected')\n", encoding="utf-8")
        (camp / "checks" / "foil_broken.py").write_text("import sys; print('FOIL-BROKEN'); sys.exit(1)\n", encoding="utf-8")
        (camp / "checks" / "foil_legacy.py").write_text("import sys; print('OVERALL: FAIL (expected for a foil)'); sys.exit(1)\n", encoding="utf-8")
        r = run_checks(camp, timeout=30)
        assert dict(r["checks"]) == {"check_ok.py": "PASS", "check_bad.py": "FAIL(exit 3)"}, r["checks"]
        f = {n: (v, c) for n, v, c in r["foils"]}
        assert f["foil_std.py"] == ("teeth", "standard") and f["foil_broken.py"] == ("BROKEN", "standard") and f["foil_legacy.py"] == ("teeth", "legacy"), f
        row = render_run(r)
        assert "checks 1/2 PASS" in row and "foils 2/3 teeth" in row and "foil_broken.py:BROKEN" in row, row
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); (root / "campaigns" / "retros").mkdir(parents=True)
        def mk(name, ledger=None, results=None):
            c = root / "campaigns" / name; c.mkdir(); (c / "spec.md").write_text("spec\n", encoding="utf-8")
            if ledger is not None:
                (c / "ledger.yaml").write_text(yaml.safe_dump(ledger, allow_unicode=True), encoding="utf-8")
            if results is not None:
                (c / "results.md").write_text(results, encoding="utf-8")
            return c
        mk("a-spec")
        mk("b-running", [{"id": "X", "status": "verified", "tier": "🔧"}])
        mk("c-done", [{"id": "X", "status": "refuted", "tier": "🔧"}], "# r\n" + AUTO_BEGIN + "\nx\n" + AUTO_END + "\n")
        mk("d-received", [{"id": "X", "status": "refuted", "tier": "🔧", "novel_to_requester": True}], "# r\n" + AUTO_BEGIN + "\nx\n" + AUTO_END + "\n")
        mk("e-retrod", [{"id": "X", "status": "verified", "tier": "👁"}], "# r\n" + AUTO_BEGIN + "\nx\n" + AUTO_END + "\n")
        (root / "campaigns" / "retros" / "r1.md").write_text("---\nround: 1\ncampaigns: [e-retrod]\ncontamination: {e-retrod: 2}\n---\n# retro\n", encoding="utf-8")
        (root / "improvements.yaml").write_text(yaml.safe_dump([
            {"id": "I-1", "status": "implemented", "origin": "r1"},
            {"id": "I-2", "status": "deferred", "origin": "r1", "trigger": "n>=2", "review_by": "2020-01-01"},
            {"id": "I-3", "status": "deferred", "origin": "r1", "trigger": "x"},
        ]), encoding="utf-8")
        ix = index(root)
        states = {r["campaign"]: r["state"] for r in ix["campaigns"]}
        assert states == {"a-spec": "spec", "b-running": "running", "c-done": "done", "d-received": "received", "e-retrod": "retro'd"}, states
        assert [r for r in ix["campaigns"] if r["campaign"] == "e-retrod"][0]["contamination"] == 2
        lines = surface(ix, today=_dt.date(2026, 9, 6))
        joined = "\n".join(lines)
        assert "未受領: `c-done`" in joined and "retro 未記入: `d-received`" in joined, joined
        assert "I-2" in joined and "見直し期日" in joined and "I-3" in joined and "時計なし" in joined and "I-1" not in joined, joined
        assert "a-spec" not in joined  # no git history in tempdir → no age → silent
        txt = render_index(ix); assert "| `c-done` | **done** |" in txt and "I-2" in txt
    print("selftest OK (19 checks)")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    write = "--write" in argv
    root_arg = argv[argv.index("--root") + 1] if "--root" in argv else None
    if "--index" in argv or "--surface" in argv:
        root = Path(root_arg).resolve() if root_arg else repo_root(Path.cwd())
        ix = index(root)
        if "--surface" in argv:
            for line in surface(ix):
                print(line)
            return 0
        text = render_index(ix)
        print(text)
        if write:
            (root / "campaigns" / "INDEX.md").write_text(text, encoding="utf-8")
            print(f"→ {root / 'campaigns' / 'INDEX.md'} written")
        return 0
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
    timeout_arg = int(argv[argv.index("--timeout") + 1]) if "--timeout" in argv else 600
    args = [a for a in args if a != (argv[argv.index("--timeout") + 1] if "--timeout" in argv else None)]
    camp = Path(args[0]).resolve()
    repo = Path(root_arg).resolve() if root_arg else repo_root(camp)
    st = stats(camp, repo)
    if "--run" in argv:
        st["run"] = run_checks(camp, timeout_arg)
        for n, v in st["run"]["checks"]:
            print(f"  check {n}: {v}")
        for n, v, c in st["run"]["foils"]:
            print(f"  foil  {n}: {v} [{c}]")
    block = render(st)
    print(block)
    if write:
        write_block(camp, block)
        print(f"→ {camp / 'results.md'} updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
