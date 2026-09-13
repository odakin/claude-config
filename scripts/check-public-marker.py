#!/usr/bin/env python3
"""check-public-marker.py — Are the public-repo leak gates switched on? Lists local clones whose GitHub repo is public but lack .claude/public-repo.marker (no public pre-commit gate runs), clones marked public whose repo is private, and marked clones whose gate hooks are not installed on this machine; --fix-hooks installs them; --selftest.

Why (2026-09-13): seven public repos cloned under the same base had no marker, so none of the public
pre-commit tiers (e-mail and paths, private repo names, verbatim unpublished text) ran on their commits;
one of them had a commit twelve days earlier. The marker is the only switch for those gates. The new-repo
setup path writes it, but clones of repos created elsewhere never got one. A gate nobody switched on looks
exactly like a gate that finds nothing (conventions/confidential-repo-boundary.md#unpublished-text-public-gate).

Checks (one line per finding, then a summary line that is always printed):
  public-no-marker   GitHub says PUBLIC, the clone has no marker            -> add and commit the marker
  marker-on-private  the clone has a marker, GitHub says PRIVATE/INTERNAL  -> remove it (public gates, and the
                     repo is skipped as a source of unpublished text)
  hooks-missing      marker present, but .git/hooks/pre-commit or commit-msg is not the public stub on this
                     machine (e.g. right after pulling a new marker)       -> --fix-hooks runs the installers
Visibility comes from one `gh api graphql` call per 40 repos. If gh is unavailable, the visibility checks are
reported as not run (one line) and only the local hook check counts.

Usage:
  check-public-marker.py [--root DIR] [--fix-hooks]      full check (default root = the base dir holding claude-config)
  check-public-marker.py --hooks-only [--fix-hooks]      local only, no network (for the per-session install step)
  check-public-marker.py --selftest
Exit: 0 = nothing to fix (or CI, where clones and hooks are not the owner's machine) / 1 = findings remain.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_ROOT = SCRIPTS.parents[1]
MARKER = Path(".claude") / "public-repo.marker"
STUBS = {"pre-commit": "public-precommit-runner.sh", "commit-msg": "commit-msg-leak-guard-runner.sh"}
INSTALLERS = {"pre-commit": "install-public-precommit.sh", "commit-msg": "install-public-commit-msg.sh"}
GITHUB_RE = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def clones(root: Path) -> list:
    out = []
    for d in sorted(root.iterdir()):
        if d.name.startswith(".") or not d.is_dir() or not (d / ".git").exists():
            continue
        m = GITHUB_RE.search(_git(d, "remote", "get-url", "origin"))
        out.append({"dir": d, "slug": f"{m.group(1)}/{m.group(2)}" if m else None,
                    "marker": (d / MARKER).is_file()})
    return out


def hooks_dir(repo: Path) -> Path:
    p = _git(repo, "config", "--get", "core.hooksPath") or _git(repo, "rev-parse", "--git-path", "hooks") or ".git/hooks"
    p = Path(p)
    return p if p.is_absolute() else repo / p


def missing_stubs(repo: Path) -> list:
    hd = hooks_dir(repo)
    missing = []
    for hook, needle in STUBS.items():
        f = hd / hook
        try:
            ok = needle in f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ok = False
        if not ok:
            missing.append(hook)
    return missing


def gh_visibility(slugs: list) -> tuple:
    """Return ({slug: visibility or None}, error or None) via batched GraphQL."""
    vis, err = {}, None
    for i in range(0, len(slugs), 40):
        chunk = slugs[i:i + 40]
        fields = []
        for j, s in enumerate(chunk):
            owner, name = s.split("/", 1)
            fields.append(f'r{j}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ visibility }}')
        query = "query { " + " ".join(fields) + " }"
        try:
            r = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return vis, f"gh not usable ({exc.__class__.__name__})"
        try:
            data = json.loads(r.stdout or "{}").get("data") or {}
        except ValueError:
            data = {}
        if not data and r.returncode != 0:
            return vis, (r.stderr.strip().splitlines() or ["gh api graphql failed"])[-1]
        for j, s in enumerate(chunk):
            node = data.get(f"r{j}")
            vis[s] = node.get("visibility") if node else None
    return vis, err


def run(root: Path, hooks_only: bool, fix_hooks: bool, visibility=gh_visibility, out=print) -> int:
    items = clones(root)
    findings = 0
    vis, err = ({}, None)
    if not hooks_only:
        vis, err = visibility([c["slug"] for c in items if c["slug"]])
    public = 0
    for c in items:
        v = vis.get(c["slug"]) if c["slug"] else None
        if v == "PUBLIC":
            public += 1
            if not c["marker"]:
                findings += 1
                out(f"✗ public-no-marker: {c['dir'].name} ({c['slug']}) is public on GitHub but has no {MARKER}; "
                    f"no public pre-commit gate runs on its commits")
        if c["marker"] and v in ("PRIVATE", "INTERNAL"):
            findings += 1
            out(f"✗ marker-on-private: {c['dir'].name} ({c['slug']}) is {v.lower()} on GitHub but carries {MARKER}")
        if c["marker"]:
            miss = missing_stubs(c["dir"])
            if miss and fix_hooks:
                for hook in miss:
                    subprocess.run(["bash", str(SCRIPTS / INSTALLERS[hook]), str(c["dir"])], capture_output=True, text=True)
                still = missing_stubs(c["dir"])
                if still:
                    findings += 1
                    out(f"✗ hooks-missing: {c['dir'].name}: installer did not place {', '.join(still)}")
                else:
                    out(f"✓ installed public gate hooks in {c['dir'].name}: {', '.join(miss)}")
            elif miss:
                findings += 1
                out(f"✗ hooks-missing: {c['dir'].name} is marked public but {', '.join(miss)} is not the public stub "
                    f"here (run with --fix-hooks)")
    marked = sum(c["marker"] for c in items)
    if hooks_only:
        scope = "visibility not checked (--hooks-only)"
    elif err:
        scope = f"visibility NOT checked: {err}"
    else:
        scope = f"{public} public on GitHub"
    out(f"public-repo markers: {len(items)} clone(s) under {root}, {marked} marked, {scope}; "
        f"{findings} finding(s)")
    return 1 if findings else 0


def selftest() -> int:
    failed = []

    def expect(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failed.append(name)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        spec = {"pub-unmarked": ("mock-org/pub-unmarked", False), "pub-marked": ("mock-org/pub-marked", True),
                "priv-marked": ("mock-org/priv-marked", True), "priv-plain": ("mock-org/priv-plain", False)}
        for name, (slug, marked) in spec.items():
            d = root / name
            d.mkdir()
            _git(d, "init", "-q")
            _git(d, "remote", "add", "origin", f"git@github.com:{slug}.git")
            if marked:
                (d / ".claude").mkdir()
                (d / MARKER).write_text("# mock marker\n")
        (root / "not-a-repo").mkdir()
        fake = {"mock-org/pub-unmarked": "PUBLIC", "mock-org/pub-marked": "PUBLIC",
                "mock-org/priv-marked": "PRIVATE", "mock-org/priv-plain": "PRIVATE"}
        lines = []
        rc = run(root, False, False, visibility=lambda s: ({k: fake.get(k) for k in s}, None), out=lines.append)
        text = "\n".join(lines)
        expect("public repo without marker is reported", "public-no-marker: pub-unmarked" in text)
        expect("marker on a private repo is reported", "marker-on-private: priv-marked" in text)
        expect("marked repos without stubs are reported as hooks-missing",
               "hooks-missing: pub-marked" in text and "hooks-missing: priv-marked" in text)
        expect("a private repo without marker is fine, and a non-repo dir is ignored",
               "priv-plain" not in text and "not-a-repo" not in text)
        expect("findings give exit 1 and a summary line", rc == 1 and lines[-1].startswith("public-repo markers: 4 clone(s)"))
        lines = []
        rc = run(root, True, True, out=lines.append)
        text = "\n".join(lines)
        expect("--fix-hooks installs both stubs in marked repos (no network with --hooks-only)",
               "installed public gate hooks in pub-marked" in text and missing_stubs(root / "pub-marked") == [])
        expect("... and leaves unmarked repos alone", missing_stubs(root / "pub-unmarked") == ["pre-commit", "commit-msg"])
        lines = []
        rc = run(root, False, False, visibility=lambda s: ({}, "gh: not logged in"), out=lines.append)
        expect("gh failure is stated in the summary, hooks are still checked",
               "visibility NOT checked: gh: not logged in" in lines[-1] and rc == 0)
        (root / "pub-unmarked" / ".claude").mkdir()
        (root / "pub-unmarked" / MARKER).write_text("# mock marker\n")
        _ = run(root, True, True, out=lambda s: None)
        (root / "priv-marked" / MARKER).unlink()
        lines = []
        rc = run(root, False, False, visibility=lambda s: ({k: fake.get(k) for k in s}, None), out=lines.append)
        expect("after the fixes nothing is left (exit 0)", rc == 0 and "0 finding(s)" in lines[-1])
    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--hooks-only", action="store_true")
    ap.add_argument("--fix-hooks", action="store_true")
    a = ap.parse_args()
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
        print("public-repo markers: SKIP (CI: the clones and hooks here are not the owner's machine)")
        return 0
    return run(a.root.resolve(), a.hooks_only, a.fix_hooks)


if __name__ == "__main__":
    sys.exit(main())
