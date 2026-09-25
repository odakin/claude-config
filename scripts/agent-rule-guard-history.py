#!/usr/bin/env python3
"""agent-rule-guard-history.py — replay the rule-document exemption (change_exemption) over a repo's git history: how many committed versions of the rule documents would pass without a ruling, what stops the rest, and which listed terms fire (for tuning the position rules) — read-only.

The guard's line for prose rule documents (CLAUDE.md / AGENTS.md / CONVENTIONS.md / conventions/*.md) is a set of
proxies (relaxing vocabulary in a relaxing position, hiding, historicising headings). Whether a proxy over-fires is
an empirical question, so this tool judges every committed version of every rule document since a date with the
engine next to it (or any engine file you point at) and reports:

  pass rate            versions that pass without a ruling, and the reasons the rest stop
  what passed          sentence counts: added / edited / removed / moved
  slowest judgement    the worst-case time (a hook that outlives its timeout lets the tool run unchecked)
  --terms              per listed term: how many added sentences it fires on, with examples (which everyday uses a
                       position rule should exempt, which relaxing forms it must keep)
  --compare ENGINE     the same versions under a second engine (e.g. the committed one) side by side

Usage:
  agent-rule-guard-history.py <repo> [--since YYYY-MM-DD] [--engine PATH] [--compare PATH] [--terms [TERM ...]] [--examples N]
  agent-rule-guard-history.py --selftest

Free zones are masked first (as the guard does). The counts are per file version (one commit × one document), so a
commit touching three rule documents counts three. Nothing is written; the repo is read with `git show`.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import os
import subprocess
import sys
import time

PROSE_DIRS = ("conventions", "CLAUDE.md", "CONVENTIONS.md", "AGENTS.md")


def load_engine(path: str):
    spec = importlib.util.spec_from_file_location("agent_rule_guard_" + str(abs(hash(path))), path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout


def show(repo: str, rev: str, path: str) -> str:
    r = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def versions(repo: str, since: str, engine):
    """(commit, path, old, new) for every changed rule-document version since the date (newest first, as git log)."""
    for c in git(repo, "log", f"--since={since}", "--format=%H", "--", *PROSE_DIRS).split():
        for p in git(repo, "show", "--format=", "--name-only", c).split("\n"):
            if not p or not engine.prose_policy_doc(p, ("",)):
                continue
            old, new = show(repo, c + "^", p), show(repo, c, p)
            if not old or not new or old == new:
                continue
            yield c, p, old, new


def judge(engine, path: str, old: str, new: str) -> tuple[bool, str, dict, float]:
    t0 = time.monotonic()
    r = engine.change_exemption(path, old, new) if hasattr(engine, "change_exemption") else engine.insertion_exemption(path, old, new)
    dt = time.monotonic() - t0
    if r is None:
        return True, "(not a prose policy document)", {}, dt
    return bool(r["ok"]), str(r.get("reason", "")), dict(r.get("what") or {}), dt


def reason_key(reason: str) -> str:
    return reason.split(":")[0].split("「")[0].strip()[:30] or "(pass)"


def run(repo: str, since: str, engine, compare=None, examples: int = 4) -> int:
    n = 0
    stats = {"main": collections.Counter(), "cmp": collections.Counter()}
    what_tot: collections.Counter = collections.Counter()
    slowest = (0.0, "")
    cross: collections.Counter = collections.Counter()
    ex: dict[str, list] = collections.defaultdict(list)
    for c, p, old, new in versions(repo, since, engine):
        n += 1
        ok, reason, what, dt = judge(engine, p, old, new)
        if dt > slowest[0]:
            slowest = (dt, f"{c[:7]} {p}")
        if ok:
            stats["main"]["pass"] += 1
            for k, v in what.items():
                what_tot[k] += len(v)
        else:
            key = reason_key(reason)
            stats["main"][key] += 1
            if len(ex[key]) < examples:
                ex[key].append(f"{c[:7]} {p}: {reason[:120]}")
        if compare is not None:
            ok2, reason2, _w, _dt = judge(compare, p, old, new)
            stats["cmp"]["pass" if ok2 else reason_key(reason2)] += 1
            cross[(ok2, ok)] += 1
    if not n:
        print("no rule-document versions found (check --since and the repo)")
        return 2
    print(f"repo={repo} since={since} versions={n}")
    print(f"pass without a ruling: {stats['main']['pass']} ({100 * stats['main']['pass'] / n:.0f}%)")
    print("stopped by:", dict((k, v) for k, v in stats["main"].most_common() if k != "pass"))
    print("what passed (sentence counts):", dict(what_tot), f"| slowest judgement {slowest[0]:.2f}s ({slowest[1]})")
    if compare is not None:
        print(f"compare engine: pass {stats['cmp']['pass']} ({100 * stats['cmp']['pass'] / n:.0f}%)",
              {f"compare={a} this={b}": v for (a, b), v in sorted(cross.items())})
    for k, rows in ex.items():
        print("==", k)
        for e in rows:
            print("   ", e)
    return 0


def run_terms(repo: str, since: str, engine, want: set[str] | None, examples: int = 8) -> int:
    """Per listed term: sentences a change adds or edits that it fires on, with examples."""
    cnt: collections.Counter = collections.Counter()
    ex: dict[str, list] = collections.defaultdict(list)
    n = 0
    for c, p, old, new in versions(repo, since, engine):
        o, nn = engine.mask_free_zones(old), engine.mask_free_zones(new)
        _ok, _reason, what, _dt = judge(engine, p, o, nn)
        n += 1
        added = list(what.get("added") or []) + [a for _r, a in (what.get("edited") or [])]
        if not added and hasattr(engine, "_units"):
            before = collections.Counter(u for u, _ in engine._units(o) if u != "\n")
            added = [u for u, _ in engine._units(nn) if u != "\n" and before.get(u, 0) == 0]
        for u in added:
            terms = engine.relax_terms(u) if hasattr(engine, "relax_terms") else ([engine.relax_hit(u)] if engine.relax_hit(u) else [])
            for t in terms:
                if want is not None and t not in want:
                    continue
                cnt[t] += 1
                if len(ex[t]) < examples:
                    i = u.find(t) if t in u else u.lower().find(t.lower())
                    ex[t].append(u[max(0, i - 45):i + len(t) + 30].replace("\n", " "))
    print(f"repo={repo} since={since} versions={n}")
    for t, k in cnt.most_common():
        print(f"== {t}: {k} sentences")
        for e in ex[t]:
            print("   ", e)
    return 0


def selftest() -> int:
    import contextlib
    import io
    import tempfile

    fails: list[str] = []

    def check(label: str, ok: bool) -> None:
        print(("ok: " if ok else "NG: ") + label)
        if not ok:
            fails.append(label)

    engine = load_engine(os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-rule-guard.py"))
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
                   GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")

        def g(*a: str) -> None:
            subprocess.run(["git", "-C", td, *a], env=env, capture_output=True, check=False)

        os.makedirs(os.path.join(td, "conventions"))
        doc = os.path.join(td, "conventions", "deploy.md")
        g("init", "-q")
        for text, msg in (("# D\n\n## Deploy\n\nレビューを経てから deploy する。\n", "init"),
                          ("# D\n\n## Deploy\n\nレビューを経てから deploy する。 手順は runbook。\n", "append"),
                          ("# D\n\n## Deploy\n\nレビューを経てから deploy する。 手順は runbook。 ただし急ぐ時は後でよい。\n", "relax"),
                          ("# D\n\n## Deploy\n\n手順は runbook。 ただし急ぐ時は後でよい。\n", "delete")):
            with open(doc, "w", encoding="utf-8") as fh:
                fh.write(text)
            g("add", "-A")
            g("commit", "-q", "-m", msg)
        rows = list(versions(td, "2000-01-01", engine))
        check("every changed version of a rule document is replayed (3 changes after the initial commit)", len(rows) == 3)
        verdicts = {c[:7]: judge(engine, p, o, n)[0] for c, p, o, n in rows}
        check("the append and the deletion pass, the relaxing sentence stops", sorted(verdicts.values()) == [False, True, True])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = run(td, "2000-01-01", engine, compare=engine)
        check("the report prints the pass rate, the stop reasons and the slowest judgement",
              rc == 0 and "pass without a ruling: 2 (67%)" in out.getvalue() and "緩和の語" in out.getvalue()
              and "slowest judgement" in out.getvalue() and "compare engine: pass 2" in out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_terms(td, "2000-01-01", engine, None)
        check("--terms lists the firing term with an example", "== ただし: 1 sentences" in out.getvalue())
    print("agent-rule-guard-history selftest: " + ("ALL PASS" if not fails else f"FAILED {len(fails)}"))
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--since", default="2000-01-01")
    ap.add_argument("--engine", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-rule-guard.py"))
    ap.add_argument("--compare", help="a second engine file to judge the same versions with")
    ap.add_argument("--terms", nargs="*", help="per-term report (optionally only these terms)")
    ap.add_argument("--examples", type=int, default=4)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.repo:
        ap.print_help()
        return 2
    engine = load_engine(a.engine)
    if a.terms is not None:
        return run_terms(a.repo, a.since, engine, set(a.terms) or None, max(a.examples, 8))
    return run(a.repo, a.since, engine, load_engine(a.compare) if a.compare else None, a.examples)


if __name__ == "__main__":
    raise SystemExit(main())
