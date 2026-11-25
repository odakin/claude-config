#!/usr/bin/env python3
"""model_versions.py — a Claude model id's tier and version, and the newest version of a tier this machine's Claude CLIs list.

Why: a worker is started with the tier word (`opus` / `fable`), which the CLI and the desktop app resolve to the newest
version (measured: a desktop worker whose start arguments said "opus" ran claude-opus-5-5). Its step 0 then needs a
floor to tell "the newest" from an older start (the app starts a child on the requester's model when the asked one is
higher = conventions/multi-session-coordination.md#desktop-start-model-cap): the board writes the id `best_model` returns
into the hand-off, and session-model.py's check passes the same tier at that version or a newer one. The same rule as
codex-app-launch.py best-model / check-self for Codex (the newest version of the chosen family; a newer one goes on).

Where the list is (measured on a desktop install): each Claude CLI config keeps `.claude.json` (the default config's in
the home directory, another config dir's inside it) with `additionalModelCostsCache` (keys = model ids) and
`additionalModelOptionsCache` (`value` = a model id, maybe with a context suffix such as `[1m]`). Read-only; never
raises on a broken file. Tier words and their mapping come from session_model.py (one table).

Env (tests): CLAUDE_MODEL_LIST_FILES = the list files to read instead (os.pathsep-separated; set and empty = none), so
a test's expected id does not move when this machine's list gains a newer version; CLAUDE_CONFIG_DIRS_HOME /
CLAUDE_CONFIG_DIR (through claude_config_dirs.py).
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import os
import re


def _sibling(name: str):
    spec = _ilu.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sm = _sibling("session_model")
try:
    _ccd = _sibling("claude_config_dirs")
except Exception:  # pragma: no cover - an old checkout: the default config only
    _ccd = None

_CLAUDE_ID = re.compile(r"^claude-([a-z]+)((?:-\d+)+)$")
_SUFFIX = re.compile(r"\[[^\]]*\]$")


def tier(model: str) -> str:
    return _sm.tier(model)


def bare(model: str) -> str:
    """'claude-opus-5-5[1m]' → 'claude-opus-5-5' (the context-size suffix is not another model)."""
    return _SUFFIX.sub("", (model or "").strip().lower())


def version_of(model: str):
    """'claude-opus-5-5[1m]' → ('opus', (5, 5)); 'claude-opus-4-5-20251101' → ('opus', (4, 5)) (a date part is no
    version); 'claude-mythos-5-1' → ('fable', (5, 1)) (the same tier). None for a tier word ('opus') or another shape."""
    m = _CLAUDE_ID.match(bare(model))
    if not m:
        return None
    t = tier(m.group(1))
    parts = [int(x) for x in m.group(2).strip("-").split("-") if len(x) < 8]
    return (t, tuple(parts)) if t not in ("", "unknown") and parts else None


def model_list_files() -> list[str]:
    """Every `.claude.json` of this machine's Claude CLI configs (default first); CLAUDE_MODEL_LIST_FILES replaces them."""
    override = os.environ.get("CLAUDE_MODEL_LIST_FILES")
    if override is not None:
        return [p for p in override.split(os.pathsep) if p]
    home = _ccd._home() if _ccd is not None else os.path.expanduser("~")
    out = [os.path.join(home, ".claude.json")]
    dirs = _ccd.config_dirs() if _ccd is not None else []
    out += [os.path.join(d, ".claude.json") for d in dirs[1:]]
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        out.append(os.path.join(os.path.expanduser(env), ".claude.json"))
    seen, uniq = set(), []
    for p in out:
        k = os.path.realpath(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def best_model(family: str, files: list[str] | None = None) -> tuple[str, str]:
    """(id, '') = the model of this tier ('opus' / 'fable') with the highest version among the ids the lists hold;
    ('', why) when no list can be read, none has the tier, or `family` is not a tier word (no guess: an old id as the
    floor would let an older start pass, a guessed newer one would stop every worker)."""
    fam = tier(family or "")
    if fam in ("", "unknown"):
        return "", f"系統の語でない ({family!r}: opus / fable / sonnet / haiku)"
    read_any, best = False, None
    for p in files if files is not None else model_list_files():
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        read_any = True
        costs = d.get("additionalModelCostsCache")
        ids = list(costs.keys()) if isinstance(costs, dict) else []
        ids += [str(o.get("value") or "") for o in (d.get("additionalModelOptionsCache") or []) if isinstance(o, dict)]
        for i in ids:
            v = version_of(i)
            if v and v[0] == fam and (best is None or v[1] > best[1]):
                best = (bare(i), v[1])
    if not read_any:
        return "", "この機械の Claude CLI の model の一覧 (.claude.json) が読めない"
    if not best:
        return "", f"この機械の Claude CLI の model の一覧に {fam} の版つきの id が無い"
    return best[0], ""


def _selftest() -> int:
    import tempfile
    fails = []

    def check(label, ok):
        print(("ok: " if ok else "NG: ") + label)
        if not ok:
            fails.append(label)

    check("version_of: suffix dropped, date part dropped, mythos = fable, tier word / other shape = None",
          version_of("claude-opus-5-5[1m]") == ("opus", (5, 5)) and version_of("claude-opus-4-5-20251101") == ("opus", (4, 5))
          and version_of("claude-mythos-5-1") == ("fable", (5, 1)) and version_of("opus") is None
          and version_of("gpt-6.2-astra") is None and version_of("claude-opus-5") == ("opus", (5,)))
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, "a.json"), os.path.join(td, "b.json")
        with open(a, "w", encoding="utf-8") as fh:
            json.dump({"additionalModelCostsCache": {"claude-opus-5": {}, "claude-opus-5-5": {}, "claude-opus-4-5-20251101": {},
                                                     "claude-fable-5-1": {}}}, fh)
        with open(b, "w", encoding="utf-8") as fh:
            json.dump({"additionalModelOptionsCache": [{"value": "claude-fable-5-2[1m]"}], "additionalModelCostsCache": None}, fh)
        check("best_model: the highest version of the tier over every list (cost keys and options, suffix dropped)",
              best_model("opus", [a, b]) == ("claude-opus-5-5", "") and best_model("fable", [a, b]) == ("claude-fable-5-2", "")
              and best_model("mythos", [a, b])[0] == "claude-fable-5-2")
        check("best_model: versions compare as numbers (5-10 > 5-9)",
              best_model("opus", [a]) == ("claude-opus-5-5", "")
              and _with({"claude-opus-5-9": {}, "claude-opus-5-10": {}}, td) == ("claude-opus-5-10", ""))
        check("best_model: no model of the tier / no readable list / not a tier word → '' with the reason",
              best_model("haiku", [a])[0] == "" and "haiku" in best_model("haiku", [a])[1]
              and best_model("opus", [os.path.join(td, "none.json")])[1].endswith("読めない")
              and best_model("gpt", [a])[0] == "")
        home = os.path.join(td, "home")
        os.makedirs(os.path.join(home, ".claude"))
        os.makedirs(os.path.join(home, ".claude-alt", "projects"))
        saved = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIRS_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_MODEL_LIST_FILES")}
        os.environ["CLAUDE_CONFIG_DIRS_HOME"] = home
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        os.environ.pop("CLAUDE_MODEL_LIST_FILES", None)
        try:
            files = model_list_files()
            check("model_list_files: the home's .claude.json first, then each other config dir's",
                  files[0] == os.path.join(home, ".claude.json") and os.path.join(home, ".claude-alt", ".claude.json") in files)
            os.environ["CLAUDE_MODEL_LIST_FILES"] = a + os.pathsep + b
            check("CLAUDE_MODEL_LIST_FILES replaces the files (a test's floor does not move with this machine's list)",
                  model_list_files() == [a, b] and best_model("fable") == ("claude-fable-5-2", ""))
            os.environ["CLAUDE_MODEL_LIST_FILES"] = ""
            check("CLAUDE_MODEL_LIST_FILES set and empty = no list (unknown)", best_model("opus")[0] == "")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    print("model_versions selftest: " + ("ALL PASS" if not fails else f"FAILED {len(fails)}"))
    return 1 if fails else 0


def _with(costs: dict, td: str):
    p = os.path.join(td, "c.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"additionalModelCostsCache": costs}, fh)
    return best_model("opus", [p])


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--selftest"]:
        raise SystemExit(_selftest())
    print(__doc__.splitlines()[0])
