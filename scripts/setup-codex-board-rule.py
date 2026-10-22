#!/usr/bin/env python3
"""Install or audit the Codex rule that lets a board worker run the agent board's engine outside the sandbox.

Why (measured, Codex app 26.1002 / CLI 0.162): a Codex worker that the Codex app runs (the app holds the thread, so the
owner sees its progress and can talk to it; ai-collaboration board/CONTRACT.md#codex-worker-launch) gets the app's
sandbox, whose network is the machine's default (off). The board's `inbox --sync`, `claim`, `note` and `submit` fetch
and push the board checkout, so they fail there. A Codex `prefix_rule` with `decision = "allow"` runs the matching
command outside the sandbox without asking, also on a turn whose approval policy is `never` (measured with the
normal-push rule of setup-codex-git-push.py: a lone `git push origin main` reached a remote outside the writable roots,
the same push chained after another command with `;` did not match and stayed sandboxed). The rule names only the
worker's subcommands of this machine's engine (absolute path); starting workers (`request`, `launch`) and the
requester's verdicts (`accept`, `revise`) stay sandboxed. The owner chose this narrow rule over turning the sandbox's
network on for every Codex thread (2026-10-21).

usage: setup-codex-board-rule.py [--install | --check | --print] [--engine PATH] [--codex-home DIR] | --selftest
  --check (default): exit 0 when the managed rule file is current, 1 when it is missing or stale (repair = --install).
  The rule file is <CODEX_HOME>/rules/claude-config-agent-board.rules (0600). A file there without the managed marker is
left unchanged. A newly installed rule applies from the next thread the app or the daemon opens.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = "# Managed by claude-config/scripts/setup-codex-board-rule.py\n"
RULE_NAME = "claude-config-agent-board.rules"
WORKER_SUBCOMMANDS = ("inbox", "show", "watch", "boards", "sessions", "claim", "note", "blocker", "finding", "submit",
                      "release", "handover", "touch", "untouch", "touching")


def default_engine() -> Path:
    return (HERE.parent.parent / "ai-collaboration" / "board" / "board.py").resolve()


def desired(engine: Path) -> str:
    e = str(engine)
    if any(c.isspace() or c in "\"'\\" for c in e):
        raise ValueError(f"engine path must not contain spaces or quotes (the rule matches argv tokens): {e}")
    subs = ", ".join(f'"{s}"' for s in WORKER_SUBCOMMANDS)
    match = ",\n".join(f'        "python3 {e} {s} --root /x"' for s in ("inbox", "claim", "note", "submit"))
    not_match = ",\n".join([f'        "python3 {e} {s} --root /x"' for s in ("request", "launch", "accept")]
                           + ['        "python3 /tmp/elsewhere/board.py inbox --root /x"'])
    return MARKER + f"""prefix_rule(
    pattern = ["python3", "{e}", [{subs}]],
    decision = "allow",
    justification = "A board worker reads and posts on the agent board (it fetches and pushes the board checkout) outside the sandbox; starting workers and the requester's verdicts stay sandboxed",
    match = [
{match},
    ],
    not_match = [
{not_match},
    ],
)
"""


def target_of(codex_home: Path) -> Path:
    return codex_home.expanduser() / "rules" / RULE_NAME


def unmanaged(t: Path) -> bool:
    return t.is_symlink() or (t.exists() and not t.read_text(encoding="utf-8").startswith(MARKER))


def check(codex_home: Path, engine: Path) -> tuple[bool, str]:
    t = target_of(codex_home)
    if unmanaged(t):
        return False, f"unmanaged file at {t}: left unchanged (remove or rename it, then --install)"
    if not t.is_file():
        return False, f"missing: {t} (repair = {Path(__file__).name} --install)"
    if t.read_text(encoding="utf-8") != desired(engine):
        return False, f"stale: {t} (repair = {Path(__file__).name} --install)"
    if t.stat().st_mode & 0o077:
        return False, f"not private (0600): {t}"
    return True, f"Codex board rule current: {t}"


def install(codex_home: Path, engine: Path) -> tuple[bool, str]:
    t = target_of(codex_home)
    if unmanaged(t):
        return False, f"unmanaged file at {t}: left unchanged"
    want = desired(engine)
    if t.is_file() and t.read_text(encoding="utf-8") == want and not t.stat().st_mode & 0o077:
        return True, f"Codex board rule current: {t}"
    t.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(t, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as s:
        os.fchmod(s.fileno(), 0o600)
        s.write(want)
    return True, f"installed: {t} (applies from the next thread the app or the daemon opens)"


def codex_cli() -> str | None:
    sys.path.insert(0, str(HERE / "lib"))
    try:
        import codex_threads as ct
        return ct.codex_binary()
    except Exception:
        return None


def execpolicy(rule: Path, command: list[str]) -> str | None:
    cli = codex_cli()
    if not cli:
        return None
    p = subprocess.run([cli, "execpolicy", "check", "--rules", str(rule), "--", *command], capture_output=True, text=True,
                       timeout=60)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[-400:])
    rules = (json.loads(p.stdout) or {}).get("matchedRules") or []   # measured shape: [{"prefixRuleMatch": {"decision": …}}]
    got = [r.get("prefixRuleMatch", {}).get("decision") for r in rules]
    return "allow" if got and all(d == "allow" for d in got) else (got[0] if got else "unmatched")


def selftest() -> int:
    checks = []
    with tempfile.TemporaryDirectory(prefix="codex-board-rule-") as td:
        home, eng = Path(td) / "codex", Path(td) / "ai-collaboration" / "board" / "board.py"
        checks.append(("missing rule is reported", check(home, eng)[0] is False))
        ok, _ = install(home, eng)
        checks.append(("install writes the managed file 0600", ok and target_of(home).stat().st_mode & 0o777 == 0o600))
        checks.append(("check passes after install", check(home, eng)[0]))
        checks.append(("a moved engine makes it stale", check(home, Path(td) / "elsewhere" / "board.py")[0] is False))
        target_of(home).write_text('prefix_rule(pattern=["x"], decision="allow")\n')
        checks.append(("an unmanaged file is left unchanged", install(home, eng)[0] is False
                       and '"x"' in target_of(home).read_text()))
        try:
            desired(Path("/a b/board.py"))
            checks.append(("a path with a space is refused", False))
        except ValueError:
            checks.append(("a path with a space is refused", True))
        rule = Path(td) / "probe.rules"
        rule.write_text(desired(eng), encoding="utf-8")
        try:
            got = {s: execpolicy(rule, ["python3", str(eng), s, "--sync"]) for s in ("inbox", "submit", "request", "launch")}
        except RuntimeError as e:
            print(f"FAIL codex execpolicy rejected the rule: {e}")
            return 1
        if None in got.values():
            print("SKIP codex execpolicy (no Codex CLI on this machine)")
        else:
            checks.append(("execpolicy: worker subcommands allowed", got["inbox"] == "allow" and got["submit"] == "allow"))
            checks.append(("execpolicy: request / launch not allowed", got["request"] != "allow" and got["launch"] != "allow"))
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    return 0 if all(ok for _, ok in checks) else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--print", action="store_true", help="print the rule this machine would get")
    ap.add_argument("--engine", type=Path, default=None, help="the board engine (default: ai-collaboration next to claude-config)")
    ap.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    a = ap.parse_args(argv)
    engine = (a.engine or default_engine()).expanduser().resolve()
    if a.print:
        print(desired(engine), end="")
        return 0
    ok, msg = install(a.codex_home, engine) if a.install else check(a.codex_home, engine)
    print(msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
