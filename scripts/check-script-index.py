#!/usr/bin/env python3
"""Check that a Git repository's script inventory has direct Markdown links.

Usage:
  python3 check-script-index.py REPO --index analyses/README.md \
      --index analyses/checks/README.md --scan analyses --scan side-projects
  python3 check-script-index.py --selftest

The inventory is git ls-files (tracked plus nonignored untracked files),
restricted to --scan paths and --suffix extensions. Defaults: scan the whole
repository; .py,.sh,.wls,.wl,.jl,.ipynb,.nb. All indexes are explicit; a link
to another index does not recursively load it. Script links are resolved
relative to their index, never relative to the working directory.

Only inline Markdown links, including angle-bracket/percent-encoded targets,
are supported. Fenced code and HTML comments are ignored. Reference-style
links and prose filenames do not establish coverage. Remote URLs and anchors
are not fetched. Missing local link targets and repository escapes are errors.
The checker neither runs scripts nor certifies their claims, documentation,
link anchors, or reproducibility. Classification remains the index author's
job. A zero-file inventory is an error, not a vacuous completeness claim.

Exit 0: covered inventory, 1: missing coverage/targets, 2: input or Git error.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit


SUFFIXES = ".py,.sh,.wls,.wl,.jl,.ipynb,.nb"
LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s()]+)(?:\s+\"[^\"\n]*\")?\s*\)")


def within(root, path):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes repository: {path}")
    return resolved


def visible_markdown(source):
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    lines, fence = [], None
    for line in source.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return "\n".join(lines)


def inspect(root, indexes, scans, suffixes):
    root = root.resolve()
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True).stdout.strip()
    if Path(top).resolve() != root:
        raise ValueError("REPO must be the Git worktree root")
    for path in [*indexes, *scans]:
        target = within(root, root / path)
        if not target.exists():
            raise ValueError(f"missing input: {path}")
    raw = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard", "--", *scans], capture_output=True, check=True).stdout
    expected = set()
    for name in raw.decode("utf-8").split("\0"):
        if name and Path(name).suffix in suffixes:
            target = within(root, root / name)
            if not target.is_file():
                raise ValueError(f"listed script is absent or not a file: {name}")
            expected.add(target.relative_to(root).as_posix())
    if not expected:
        raise ValueError("no scripts in declared inventory; check scan paths and suffixes")
    linked, missing_targets = set(), set()
    for index in indexes:
        path = root / index
        for match in LINK.finditer(visible_markdown(path.read_text(encoding="utf-8"))):
            url = urlsplit(match.group(1).strip("<>"))
            if url.scheme or url.netloc or not url.path:
                continue
            target = within(root, path.parent / unquote(url.path))
            relative = target.relative_to(root).as_posix()
            if not target.exists():
                missing_targets.add(f"{index}: {relative}")
            else:
                linked.add(relative)
    return {"scan": scans, "suffixes": sorted(suffixes), "indexes": indexes,
            "inventory_count": len(expected), "covered_count": len(expected & linked),
            "unindexed": sorted(expected - linked),
            "missing_targets": sorted(missing_targets)}


def selftest():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp).resolve()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "checks").mkdir()
        (root / "docs").mkdir()
        (root / "checks/a.py").write_text("pass\n")
        (root / "checks/a space.jl").write_text("# fixture\n")
        (root / "ignored.py").write_text("pass\n")
        (root / ".gitignore").write_text("ignored.py\n")
        index = root / "docs/README.md"
        index.write_text("[a](../checks/a.py#entry)\n[b](<../checks/a%20space.jl>)\n")
        kwargs = (root, ["docs/README.md"], ["checks"], {".py", ".jl"})
        report = inspect(*kwargs)
        assert report["inventory_count"] == report["covered_count"] == 2
        index.write_text("```md\n[a](../checks/a.py)\n```\n<!-- [b](../checks/a%20space.jl) -->")
        assert len(inspect(*kwargs)["unindexed"]) == 2
        index.write_text("[a](../checks/a.py)\n[b](../checks/missing.py)\n[x](https://example.org/x)")
        assert inspect(*kwargs)["missing_targets"] == ["docs/README.md: checks/missing.py"]
        index.write_text("[a](../../outside.py)")
        try:
            inspect(*kwargs)
            raise AssertionError("escape accepted")
        except ValueError:
            pass
        index.write_text("[a](../checks/a.py)\n[b](../checks/a%20space.jl)")
        subprocess.run(["git", "-C", str(root), "add", "checks/a.py"], check=True)
        assert inspect(root, ["docs/README.md"], ["."], {".py", ".jl"})["inventory_count"] == 2
        (root / "checks/a.py").unlink()
        try:
            inspect(*kwargs)
            raise AssertionError("deleted tracked script accepted")
        except ValueError:
            pass
        try:
            inspect(root, ["docs/README.md"], ["docs"], {".py"})
            raise AssertionError("empty inventory accepted")
        except ValueError:
            pass
    print("selftest: coverage, nested/encoded links, ignored/untracked/tracked files, masks, missing targets, escape, deletion and empty inventory checked")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo", nargs="?", type=Path)
    parser.add_argument("--index", action="append", default=[])
    parser.add_argument("--scan", action="append")
    parser.add_argument("--suffix", default=SUFFIXES, help="comma-separated, case-sensitive suffixes")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if args.repo is None or not args.index:
        parser.error("REPO and at least one --index are required")
    try:
        report = inspect(args.repo, args.index, args.scan or ["."], set(args.suffix.split(",")))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return int(bool(report["unindexed"] or report["missing_targets"]))


if __name__ == "__main__":
    raise SystemExit(main())
