#!/usr/bin/env python3
"""Detect duplicated cross-layer script engines and unreviewed lower-layer additions."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_SUFFIXES = {".py", ".sh", ".js", ".jl", ".wl", ".wls", ".ipynb"}
LAYER3_DECLARATION = "layer-placement: layer3"
SHIM_MARKERS = ("os.execv", "importlib.util", "exec ")


def scripts_under(directory: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not directory.is_dir():
        return out
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix not in SCRIPT_SUFFIXES:
            continue
        if any(part in {"__pycache__", ".git", "node_modules"} for part in path.parts):
            continue
        out[path.relative_to(directory).as_posix()] = path
    return out


def is_upper_shim(lower: Path, relative: str) -> bool:
    try:
        text = lower.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    names_upper = "claude-config" in text and Path(relative).name in text
    delegates = any(marker in text for marker in SHIM_MARKERS)
    return names_upper and delegates


def duplicate_findings(
    upper_dir: Path,
    lower_dir: Path,
    allow_different: set[str] | None = None,
) -> list[tuple[str, str]]:
    allowed = allow_different or set()
    upper = scripts_under(upper_dir)
    lower = scripts_under(lower_dir)
    findings: list[tuple[str, str]] = []
    for relative in sorted(set(upper) & set(lower)):
        if relative in allowed or is_upper_shim(lower[relative], relative):
            continue
        if upper[relative].read_bytes() == lower[relative].read_bytes():
            kind = "DUPLICATE_COPY"
        else:
            kind = "DUPLICATE_ENGINE"
        findings.append((kind, relative))
    return findings


def staged_added_scripts(repo: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "diff", "--cached", "--name-only", "-z", "--diff-filter=A"],
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item]


def staged_blob(repo: Path, relative: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f":{relative}"],
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else ""


def new_lower_findings(repo: Path, lower_dir: Path, upper_dir: Path) -> list[tuple[str, str]]:
    try:
        lower_prefix = lower_dir.resolve().relative_to(repo.resolve()).as_posix().rstrip("/") + "/"
    except ValueError:
        return []
    upper = scripts_under(upper_dir)
    findings: list[tuple[str, str]] = []
    for repo_relative in staged_added_scripts(repo):
        if not repo_relative.startswith(lower_prefix):
            continue
        relative = repo_relative[len(lower_prefix) :]
        if Path(relative).suffix not in SCRIPT_SUFFIXES or relative in upper:
            continue
        head = "\n".join(staged_blob(repo, repo_relative).splitlines()[:40])
        if LAYER3_DECLARATION not in head:
            findings.append(("NEW_LOWER_ONLY", relative))
    return findings


def report(findings: list[tuple[str, str]]) -> None:
    if not findings:
        return
    print("Script layer-placement findings:")
    for kind, relative in findings:
        if kind == "NEW_LOWER_ONLY":
            print(
                f"  {kind}: {relative} — add a public/shared engine, or declare "
                f"`{LAYER3_DECLARATION} <reason>` near the top"
            )
        else:
            print(f"  {kind}: {relative} — keep one upper engine and a lower config/shim")


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="script-layering-") as temporary:
        root = Path(temporary)
        upper = root / "upper/scripts"
        lower = root / "lower/scripts"
        upper.mkdir(parents=True)
        lower.mkdir(parents=True)
        (upper / "shim.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        (lower / "shim.py").write_text(
            "# claude-config/scripts/shim.py\nimport os\nos.execv('python3', ['python3'])\n",
            encoding="utf-8",
        )
        (upper / "copy.py").write_text("print('same')\n", encoding="utf-8")
        (lower / "copy.py").write_text("print('same')\n", encoding="utf-8")
        (upper / "fork.py").write_text("print('upper')\n", encoding="utf-8")
        (lower / "fork.py").write_text("print('lower')\n", encoding="utf-8")
        (lower / "private.py").write_text("print('private')\n", encoding="utf-8")
        got = duplicate_findings(upper, lower)
        checks.extend(
            [
                ("delegating shim is accepted", ("DUPLICATE_ENGINE", "shim.py") not in got),
                ("identical copy is rejected", ("DUPLICATE_COPY", "copy.py") in got),
                ("forked engine is rejected", ("DUPLICATE_ENGINE", "fork.py") in got),
                ("explicit mirror exception works", not duplicate_findings(upper, lower, {"copy.py", "fork.py"})),
                ("lower-only inventory is complete", sorted(set(scripts_under(lower)) - set(scripts_under(upper))) == ["private.py"]),
            ]
        )

        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        lower_git = repo / "scripts"
        lower_git.mkdir()
        no_reason = lower_git / "new.py"
        no_reason.write_text("#!/usr/bin/env python3\nprint('x')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "scripts/new.py"], check=True)
        findings = new_lower_findings(repo, lower_git, upper)
        checks.append(("new lower-only script needs a decision", ("NEW_LOWER_ONLY", "new.py") in findings))
        no_reason.write_text(
            "#!/usr/bin/env python3\n# layer-placement: layer3 owner-only workflow\nprint('x')\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(repo), "add", "scripts/new.py"], check=True)
        checks.append(("layer-3 reason satisfies the gate", not new_lower_findings(repo, lower_git, upper)))

    ok = True
    for label, condition in checks:
        print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
        ok = ok and condition
    print("check-script-layering selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--upper-dir", type=Path)
    parser.add_argument("--lower-dir", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--allow-different", action="append", default=[])
    parser.add_argument("--staged-new", action="store_true")
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return run_selftest()
    if args.upper_dir is None or args.lower_dir is None:
        parser.error("--upper-dir and --lower-dir are required")
    findings = duplicate_findings(
        args.upper_dir,
        args.lower_dir,
        set(args.allow_different),
    )
    if args.staged_new:
        findings.extend(
            new_lower_findings(args.repo or Path.cwd(), args.lower_dir, args.upper_dir)
        )
    if args.inventory:
        upper = scripts_under(args.upper_dir)
        lower = scripts_under(args.lower_dir)
        lower_only = sorted(set(lower) - set(upper))
        print(f"upper={len(upper)} lower={len(lower)} lower_only={len(lower_only)}")
        for relative in lower_only:
            print(relative)
    report(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
