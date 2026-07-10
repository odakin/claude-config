#!/usr/bin/env python3
"""routine-host-gate.py — 汎用 active-routine-host gate（無人ルーチンを複数マシンに install しつつ「今の本番ホスト」を台帳1ファイルで決める。台帳の host が自分でなければ defer〔exit 1〕、台帳不在/破損は fail-open〔exit 0〕、最新 committed 台帳を fetch して読む、--selftest 内蔵。install-launchd-cron.sh --gate から呼ぶ、conventions/multi-machine-state.md#account-host-failover）
routine-host-gate.py — "am I the active routine host?" gate for unmanned launchd/cron jobs.

== What this is for ==
When unmanned routines (launchd cron + `claude -p`, see conventions/scheduled-tasks.md) run on
a fleet of >1 machine, you want EXACTLY ONE machine actually executing them at a time — otherwise
you get double publishes / double notifications. The classic rule "register the jobs on only one
always-on host" (conventions/multi-machine-state.md) breaks the moment that host's account is
rate-limited or you want to move the workload to another machine/account.

This gate lets you install the (gated) jobs on EVERY candidate machine and decide which one is
live with a single git-committed ledger file. Each routine, before doing real work, calls this
gate. The gate reads the ledger's `host` field and compares it to the machine it runs on:

    exit 0  -> PROCEED  (I am the active host, OR the ledger is absent/unreadable/has no host
                         = FAIL-OPEN: behave as if there were no gate, so a broken ledger can
                         never silently stop all routines)
    exit 1  -> DEFER    (the ledger names a DIFFERENT host -> this machine is standby; the
                         caller should exit cleanly without running the routine)

Failover then = edit the ledger's `host` and push. No install/uninstall needed; the next run on
each machine re-reads the ledger and self-selects.

== Wiring ==
The generic launchd-cron engine (scripts/install-launchd-cron.sh) accepts `--gate "<snippet>"`
and inserts it into each job's wrapper as:  cd WORKDIR && <snippet> || exit 0 ; exec <routine>
So a caller passes, e.g.:
    --gate 'python3 "$HOME/path/routine-host-gate.py" "$HOME/path/<ledger-repo>" private/active-routine-host.json'
(`$HOME` stays literal so it expands per-machine at launchd runtime.)

== Ledger format ==
A small JSON file committed in a git repo. Only `host` is load-bearing for the gate; the rest is
for humans / health surfaces:
    {"host": "<hostname-short>", "account": "<cli-email>", "since": "<iso8601>", "reason": "..."}
The `host` is matched case-insensitively against this machine's `hostname -s` / `socket.gethostname()`
(with a trailing ".local" stripped), so either short or mDNS form works.

== Freshness ==
The gate best-effort `git fetch`es and reads the LATEST COMMITTED ledger (origin/<default-branch>),
falling back to the working-tree copy if the network is down. This means a standby machine sees a
failover as soon as the new ledger is pushed, without needing a manual pull. Fetch is bounded by a
timeout; any failure falls through to the working tree (fail-open preserved).

This script is generic (no per-user paths). The concrete ledger path + job wiring live in the
caller's personal layer.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys


def _strip_local(name: str) -> str:
    return name[:-6] if name.endswith(".local") else name


def my_hostnames() -> set[str]:
    """All plausible names for THIS machine, normalized (lowercase, no .local)."""
    names: set[str] = set()
    try:
        out = subprocess.run(
            ["hostname", "-s"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if out:
            names.add(out)
    except Exception:
        pass
    try:
        h = socket.gethostname()
        if h:
            names.add(h)
            names.add(h.split(".")[0])
    except Exception:
        pass
    return {_strip_local(n).lower() for n in names if n}


def _default_ref(repo: str) -> str:
    """Best guess at the remote default branch ref (origin/HEAD -> main -> master)."""
    for ref in ("origin/HEAD", "origin/main", "origin/master"):
        r = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--verify", "-q", ref + ":"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return ref
    return "origin/main"


def read_ledger(repo: str, relpath: str) -> dict | None:
    """Latest committed ledger (best-effort fetch) -> working tree fallback -> None."""
    txt: str | None = None
    try:
        subprocess.run(
            ["git", "-C", repo, "fetch", "-q", "origin"],
            timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ref = _default_ref(repo)
        r = subprocess.run(
            ["git", "-C", repo, "show", f"{ref}:{relpath}"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            txt = r.stdout
    except Exception:
        pass
    if txt is None:
        try:
            with open(os.path.join(repo, relpath)) as f:
                txt = f.read()
        except Exception:
            return None
    try:
        d = json.loads(txt)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def decide(repo: str, relpath: str, host_override: str | None = None) -> int:
    led = read_ledger(repo, relpath)
    if not led or not led.get("host"):
        return 0  # fail-open: no usable ledger -> behave as ungated
    active = _strip_local(str(led["host"])).lower()
    mine = {_strip_local(host_override).lower()} if host_override else my_hostnames()
    if active in mine:
        return 0  # I am the active host
    sys.stderr.write(
        f"[routine-host-gate] defer: active host={led.get('host')} != me {sorted(mine)}\n"
    )
    return 1  # standby -> defer


def _selftest() -> int:
    import tempfile

    fails = 0

    def check(name, got, want):
        nonlocal fails
        ok = got == want
        if not ok:
            fails += 1
        print(f"  {'OK' if ok else 'FAIL'} {name}: got={got} want={want}")

    with tempfile.TemporaryDirectory() as d:
        rel = "ledger.json"
        p = os.path.join(d, rel)

        # absent ledger -> fail-open (proceed)
        check("absent->proceed", decide(d, rel, host_override="machineA"), 0)

        # ledger naming me -> proceed
        with open(p, "w") as f:
            json.dump({"host": "machineA", "account": "x@y"}, f)
        check("self->proceed", decide(d, rel, host_override="machineA"), 0)
        check("self.local->proceed", decide(d, rel, host_override="machineA.local"), 0)
        check("case-insensitive->proceed", decide(d, rel, host_override="MACHINEA"), 0)

        # ledger naming a different host -> defer
        check("other->defer", decide(d, rel, host_override="machineB"), 1)

        # ledger present with .local in stored host, matched by short override
        with open(p, "w") as f:
            json.dump({"host": "machineA.local"}, f)
        check("stored.local vs short->proceed", decide(d, rel, host_override="machineA"), 0)

        # garbled ledger -> fail-open (proceed)
        with open(p, "w") as f:
            f.write("{not json")
        check("garbled->proceed", decide(d, rel, host_override="machineB"), 0)

        # ledger with no host field -> fail-open
        with open(p, "w") as f:
            json.dump({"account": "x@y"}, f)
        check("no-host-field->proceed", decide(d, rel, host_override="machineB"), 0)

    print("SELFTEST:", "ALL PASS" if fails == 0 else f"{fails} FAIL")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    host_override = None
    if "--host" in argv:
        i = argv.index("--host")
        host_override = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2 :]
    pos = [a for a in argv if not a.startswith("--")]
    if len(pos) < 2:
        sys.stderr.write(
            "usage: routine-host-gate.py <repo-dir> <ledger-relpath> [--host NAME] | --selftest\n"
        )
        return 0  # fail-open on misuse
    return decide(pos[0], pos[1], host_override)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
