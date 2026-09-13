#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest の foil に歯があるかを、 修正の一部だけを外した mutant で確かめる (mutant ごとに、 落ちるはずの check が FAIL し、 残るはずの check は PASS のまま = foil が互いに独立) — mutant は対象 script の隣の `<name>.mutants.json` に宣言する。--selftest 内蔵。

一般則 = [`physics-verification-cycle.md#foil-teeth-per-fix-part`](../../ai-collaboration/conventions/physics-verification-cycle.md#foil-teeth-per-fix-part)
(ai-collaboration)。 修正を外した版を scratch の `sed` で作って selftest を回した結果は、 次に回す人が再現できない
(= 同じ doc の `#scratch-foil-not-bundled`)。 本 script は mutant を spec として repo に置き、 run-all-checks から毎回回す。

使い方:

    python3 check-foil-teeth.py scripts/apply-text-pairs.mutants.json
    python3 check-foil-teeth.py --all scripts          # DIR 直下の *.mutants.json を全部
    python3 check-foil-teeth.py --selftest

spec (JSON):

    {"_comment": "説明の 1 文目 (generate-tree.py が scripts/README.md に使う)",
     "target": "apply-text-pairs.py",               # spec の dir からの相対 path
     "run": "python3 {} --selftest",                 # {} = 写しの target、 cwd = 写しの dir
     "fail_marker": "[FAIL] ", "pass_marker": "[PASS] ",   # 省略時はこの 2 つ (行頭一致)
     "mutants": [
       {"name": "修正の何を外したか",
        "pairs": [["old", "new"]],                   # 各 old は target に正確に 1 回
        "expect_fail": ["FAIL するはずの check の label の部分文字列"],
        "expect_pass": ["PASS のまま残るはずの check の label の部分文字列"]}]}   # 省略可

検査 (外れたら exit 1、 spec の誤りは exit 2):

| 何を | なぜ |
|---|---|
| mutant なしの写しが exit 0 かつ FAIL 行 0 | 基準が赤いと、 mutant の FAIL は何の証拠にもならない |
| expect_fail / expect_pass の各語が基準の PASS 行に在る | label の書き損じで「期待が何にも当たらない」 まま通るのを止める (exit 2) |
| 各 pair の old が target に正確に 1 回 | 修正の行が書き換わって mutant が当たらなくなったのを、 歯の問題と取り違えない (exit 2) |
| mutant で expect_fail の各語を含む FAIL 行が在る | foil に歯がある |
| mutant で expect_pass の各語が PASS 行に在り、 FAIL 行に無い | その check が前の foil の失敗に引きずられて落ちていない (= 独立) |
| mutant で exit 0 かつ FAIL 行 0 は `[NO-TEETH]` | どの foil も見ていない修正部分が在る |

写しは target の親 dir を丸ごと一時 dir に置く (同じ dir の module を import する selftest のため。 `.git` などは除く)。
target は最初に実体の path に解決する。 repo root を前提にする selftest は写しの上では回らない
(同じ制約 = [`apply-text-pairs.py`](apply-text-pairs.py) の docstring)。
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_FAIL = "[FAIL] "
DEFAULT_PASS = "[PASS] "
TIMEOUT = 300


class SpecError(Exception):
    pass


def load_spec(path: Path) -> dict:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SpecError(f"{path}: cannot read JSON ({e})")
    if not isinstance(spec, dict):
        raise SpecError(f"{path}: top level must be an object")
    for key in ("target", "run", "mutants"):
        if key not in spec:
            raise SpecError(f"{path}: missing key {key!r}")
    if not isinstance(spec["mutants"], list) or not spec["mutants"]:
        raise SpecError(f"{path}: mutants must be a non-empty list")
    for i, m in enumerate(spec["mutants"], 1):
        if not isinstance(m, dict) or not all(k in m for k in ("name", "pairs", "expect_fail")):
            raise SpecError(f"{path}: mutant {i} needs name / pairs / expect_fail")
        pairs = m["pairs"]
        if not isinstance(pairs, list) or not pairs or not all(
                isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) for s in p) for p in pairs):
            raise SpecError(f"{path}: mutant {m['name']!r}: pairs must be a non-empty list of [old, new]")
        for key in ("expect_fail", "expect_pass"):
            v = m.get(key, [])
            if not isinstance(v, list) or not all(isinstance(s, str) and s for s in v):
                raise SpecError(f"{path}: mutant {m['name']!r}: {key} must be a list of non-empty strings")
        if not m["expect_fail"]:
            raise SpecError(f"{path}: mutant {m['name']!r}: expect_fail is empty (name what the mutant must kill)")
    return spec


def mutate(text: str, pairs: list, name: str) -> str:
    for old, new in pairs:
        n = text.count(old)
        if n != 1:
            raise SpecError(f"mutant {name!r}: old matches {n} times in the target (must be exactly 1): {old[:60]!r}")
        text = text.replace(old, new, 1)
    return text


def run_copy(target: Path, text: str, cmd: str, timeout: int) -> tuple[int, list[str]]:
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / (target.parent.name or "root")
        shutil.copytree(target.parent, dst, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules"))
        copy = dst / target.name
        copy.write_text(text, encoding="utf-8")
        argv = [a.replace("{}", str(copy)) for a in shlex.split(cmd)]
        try:
            r = subprocess.run(argv, cwd=dst, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, [f"(timeout after {timeout}s)"]
        return r.returncode, (r.stdout + r.stderr).splitlines()


def check_spec(spec_path: Path, timeout: int = TIMEOUT, out=print) -> int:
    try:
        spec = load_spec(spec_path)
        target = Path(os.path.realpath(spec_path.parent / spec["target"]))
        if not target.is_file():
            raise SpecError(f"{spec_path}: target not found: {target}")
        base_text = target.read_text(encoding="utf-8")
        mutants = [(m, mutate(base_text, m["pairs"], m["name"])) for m in spec["mutants"]]
    except SpecError as e:
        out(f"[SPEC] {e}")
        return 2
    fail_marker = spec.get("fail_marker", DEFAULT_FAIL)
    pass_marker = spec.get("pass_marker", DEFAULT_PASS)

    rc, lines = run_copy(target, base_text, spec["run"], timeout)
    base_fails = [ln for ln in lines if ln.startswith(fail_marker)]
    if rc != 0 or base_fails:
        out(f"[BASE-RED] {target.name}: the unmutated copy exits {rc} with {len(base_fails)} FAIL line(s)")
        for ln in (base_fails or lines[-5:])[:8]:
            out("    " + ln)
        return 1
    base_passes = [ln for ln in lines if ln.startswith(pass_marker)]
    unknown = sorted({s for m, _ in mutants for s in m["expect_fail"] + m.get("expect_pass", [])
                      if not any(s in ln for ln in base_passes)})
    if unknown:
        for s in unknown:
            out(f"[SPEC] {spec_path.name}: label not found among the unmutated PASS lines: {s!r}")
        return 2
    out(f"[BASE] {target.name}: exit 0, {len(base_passes)} PASS / 0 FAIL")

    problems = 0
    for m, text in mutants:
        rc, lines = run_copy(target, text, spec["run"], timeout)
        fails = [ln for ln in lines if ln.startswith(fail_marker)]
        passes = [ln for ln in lines if ln.startswith(pass_marker)]
        missing_fail = [s for s in m["expect_fail"] if not any(s in ln for ln in fails)]
        broken_pass = [s for s in m.get("expect_pass", [])
                       if not any(s in ln for ln in passes) or any(s in ln for ln in fails)]
        survived = rc == 0 and not fails
        if survived or missing_fail or broken_pass:
            problems += 1
            out(f"[{'NO-TEETH' if survived else 'UNEXPECTED'}] {m['name']}")
            for s in missing_fail:
                out(f"    expected FAIL not seen: {s!r}")
            for s in broken_pass:
                out(f"    expected to stay PASS but did not (a foil depends on another, or the check was not reached): {s!r}")
            for ln in fails[:8]:
                out("      " + ln)
        else:
            kept = len(m.get("expect_pass", []))
            out(f"[KILLED] {m['name']}: {len(fails)} FAIL line(s), all {len(m['expect_fail'])} expected"
                + (f", {kept} kept PASS" if kept else ""))
    return 1 if problems else 0


TOOL = '''import sys
from helper import LOW


def clamp(x):
    if x < LOW:
        return LOW
    return x


def selftest():
    ok = True

    def check(label, cond):
        nonlocal ok
        print(("[PASS] " if cond else "[FAIL] ") + label)
        ok = ok and cond

    check("negative input is clamped to the floor  [foil]", clamp(-3) == LOW)
    check("positive input passes through", clamp(5) == 5)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest())
'''


def selftest() -> int:
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "pkg"
        pkg.mkdir()
        (pkg / "tool.py").write_text(TOOL, encoding="utf-8")
        (pkg / "helper.py").write_text("LOW = 0\n", encoding="utf-8")
        kill = {"name": "floor removed", "pairs": [["    if x < LOW:\n        return LOW\n", ""]],
                "expect_fail": ["clamped to the floor"], "expect_pass": ["passes through"]}

        def spec_file(name, mutants, **extra):
            p = pkg / f"{name}.mutants.json"
            p.write_text(json.dumps(dict({"_comment": "fixture.", "target": "tool.py",
                                          "run": "python3 {}", "mutants": mutants}, **extra)), encoding="utf-8")
            return p

        log: list[str] = []
        rc = check_spec(spec_file("good", [kill]), out=log.append)
        expect("a mutant that removes the fix is killed, the sibling check stays PASS (and the copy can import a "
               "sibling module)", rc == 0 and any(ln.startswith("[KILLED]") for ln in log))

        log.clear()
        cosmetic = {"name": "comment only", "pairs": [["    return x\n", "    return x  # note\n"]],
                    "expect_fail": ["clamped to the floor"]}
        rc = check_spec(spec_file("cosmetic", [cosmetic]), out=log.append)
        expect("a mutant that no check notices is reported as NO-TEETH (exit 1)",
               rc == 1 and any(ln.startswith("[NO-TEETH]") for ln in log))

        log.clear()
        both = {"name": "returns garbage", "pairs": [["def clamp(x):\n", "def clamp(x):\n    return -1\n"]],
                "expect_fail": ["clamped to the floor"], "expect_pass": ["passes through"]}
        rc = check_spec(spec_file("both", [both]), out=log.append)
        expect("a check expected to stay PASS but failing is reported (the independence half; exit 1)",
               rc == 1 and any("expected to stay PASS" in ln for ln in log))

        log.clear()
        rc = check_spec(spec_file("absent", [dict(kill, pairs=[["no such line\n", ""]])]), out=log.append)
        expect("a pair that no longer matches the target is a spec error (exit 2), not a teeth verdict",
               rc == 2 and any("matches 0 times" in ln for ln in log))

        log.clear()
        rc = check_spec(spec_file("typo", [dict(kill, expect_fail=["clamped to teh floor"])]), out=log.append)
        expect("a label that matches no PASS line of the unmutated run is a spec error (exit 2)",
               rc == 2 and any("label not found" in ln for ln in log))

        log.clear()
        (pkg / "helper.py").write_text("LOW = 10\n", encoding="utf-8")
        rc = check_spec(spec_file("red", [kill]), out=log.append)
        expect("a red baseline stops before any mutant runs (exit 1)",
               rc == 1 and any(ln.startswith("[BASE-RED]") for ln in log)
               and not any(ln.startswith("[KILLED]") for ln in log))
        (pkg / "helper.py").write_text("LOW = 0\n", encoding="utf-8")

        other = Path(td) / "elsewhere"
        other.mkdir()
        for p in pkg.glob("*.mutants.json"):
            if p.name != "good.mutants.json":
                p.unlink()
        me = os.path.abspath(__file__)
        r = subprocess.run([sys.executable, me, "--all", os.path.relpath(pkg, other)], cwd=other,
                           capture_output=True, text=True)
        expect("CLI --all with a DIR relative to another cwd finds the spec and exits 0",
               r.returncode == 0 and "[KILLED] floor removed" in r.stdout)
        r = subprocess.run([sys.executable, me], capture_output=True, text=True)
        expect("CLI with no spec is an error", r.returncode != 0)
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("specs", nargs="*", type=Path)
    ap.add_argument("--all", metavar="DIR", type=Path, help="run every *.mutants.json directly under DIR")
    ap.add_argument("--timeout", type=int, default=TIMEOUT, help="seconds per run (default %(default)s)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    specs = list(a.specs)
    if a.all:
        found = sorted(a.all.glob("*.mutants.json"))
        if not found:
            print(f"no *.mutants.json directly under {a.all}")
        specs += found
    if not specs and not a.all:
        ap.error("give spec path(s) or --all DIR")
    worst = 0
    for s in specs:
        print(f"== {s}")
        worst = max(worst, check_spec(s, a.timeout))
    return worst


if __name__ == "__main__":
    sys.exit(main())
