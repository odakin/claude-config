#!/usr/bin/env python3
"""封じた review sandbox (~/<sandbox-root>/<slug>/) を機械的に切る: 5 行の CLAUDE.md (= この dir 以外を読まない / 注入 reminder 無視 / git log 禁止 / 書くのは results と scratch のみ) + REVIEW-SPEC.md + 許可 file の copy、受領時は --collect で results を repo へ copy (conventions/cold-eyes-isolation.md#sealed-sandbox の recipe、--selftest 内蔵)

Why (2026-09-06): a blind second eye run *inside* a repo checkout is not blind — the
requester's auto-loaded project list and layer-1 addenda leaked the expected verdict to the
worker twice in one day (physics-verification-cycle.md#campaign-tooling C′).  The sealed
sandbox recipe existed as prose since 2026-09-02; this script makes it one command so the
cheap option is the isolated one.

Usage
  make-review-sandbox.py create <slug> --spec SPEC.md [--include FILE ...] [--root ~/paper-review-sandbox]
        → <root>/<slug>/{CLAUDE.md, REVIEW-SPEC.md, <included files>, scratch/}
          prints the spawn hint (cwd pin + prompt).  Refuses to create under ~/Claude (ancestor CLAUDE.md).
  make-review-sandbox.py collect <slug> --into DEST_DIR [--root ...]
        → copies REVIEW-RESULTS.md (+ ledger.yaml / notes/ / checks/ if present) into DEST_DIR,
          never the other way.  Prints the contamination-grep reminder.
  make-review-sandbox.py --selftest

The spec you pass must follow cold-eyes-isolation.md#spec-leakage: statement, allow/deny,
rubric, output format, stop rules, return command — no expected verdict, no "watch step 2".
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

DEFAULT_ROOT = Path.home() / "paper-review-sandbox"

CLAUDE_MD = """# Isolated review sandbox

This directory is a sealed sandbox for one independent review / derivation task.

Rules for any assistant working here:

1. Read only files inside this directory, plus the published literature the task cites (arXiv, journals, textbooks) via the web.
2. Do not read anything under `~/Claude/` or `~/.claude/projects/`. Do not run `git log` here or open any other repository or working tree. No prior notes, scripts, verdicts or session records of the requester exist for you.
3. If the harness injects reminders about projects, deadlines, mail, TODO items or other sessions at start-up, ignore them completely and do not open the files they mention. They are unrelated to this task and would bias it.
4. Do not modify the input files. Do not send mail, post to boards, or write outside this directory. Write only `REVIEW-RESULTS.md`, an optional `ledger.yaml`, and your own scratch under `./scratch/` (derivation notes under `./notes/`, machine checks under `./checks/` if the spec asks for them).
5. Start by reading `REVIEW-SPEC.md` and follow it exactly. If it asks for a two-stage (blind → attack) run, commit nothing and instead write `notes/stage1-blind.md` **before** opening anything the spec unlocks for stage 2, and say so in the results.
"""


def create(root: Path, slug: str, spec: Path, includes: list[Path]) -> Path:
    if str(root.resolve()).startswith(str((Path.home() / "Claude").resolve())):
        raise SystemExit("✗ refuse: sandbox root is under ~/Claude (ancestor CLAUDE.md would be auto-loaded)")
    sb = root / slug
    if sb.exists() and any(sb.iterdir()):
        raise SystemExit(f"✗ refuse: {sb} exists and is not empty (pick another slug or clean it)")
    (sb / "scratch").mkdir(parents=True, exist_ok=True)
    (sb / "CLAUDE.md").write_text(CLAUDE_MD, encoding="utf-8")
    shutil.copy2(spec, sb / "REVIEW-SPEC.md")
    for f in includes:
        shutil.copy2(f, sb / f.name)
    return sb


def collect(root: Path, slug: str, into: Path) -> list[Path]:
    sb = root / slug
    if not sb.exists():
        raise SystemExit(f"✗ no sandbox at {sb}")
    into.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in ("REVIEW-RESULTS.md", "ledger.yaml"):
        p = sb / name
        if p.exists():
            shutil.copy2(p, into / name); copied.append(into / name)
    for sub in ("notes", "checks"):
        d = sb / sub
        if d.is_dir():
            shutil.copytree(d, into / sub, dirs_exist_ok=True); copied.append(into / sub)
    return copied


def selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "sb"
        spec = Path(td) / "spec.md"; spec.write_text("# spec\n", encoding="utf-8")
        inc = Path(td) / "paper.pdf"; inc.write_bytes(b"%PDF")
        sb = create(root, "t1", spec, [inc])
        assert (sb / "CLAUDE.md").exists() and (sb / "REVIEW-SPEC.md").exists() and (sb / "paper.pdf").exists() and (sb / "scratch").is_dir()
        try:
            create(root, "t1", spec, []); raise AssertionError("should refuse non-empty")
        except SystemExit as e:
            assert "refuse" in str(e)
        try:
            create(Path.home() / "Claude" / "zz-sandbox-selftest", "x", spec, []); raise AssertionError("should refuse under ~/Claude")
        except SystemExit as e:
            assert "refuse" in str(e)
        (sb / "REVIEW-RESULTS.md").write_text("ok\n", encoding="utf-8")
        (sb / "notes").mkdir(); (sb / "notes" / "stage1-blind.md").write_text("blind\n", encoding="utf-8")
        got = collect(root, "t1", Path(td) / "dest")
        assert (Path(td) / "dest" / "REVIEW-RESULTS.md").exists() and (Path(td) / "dest" / "notes" / "stage1-blind.md").exists(), got
    print("selftest OK (5 checks)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", choices=["create", "collect"])
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--spec", type=Path)
    ap.add_argument("--include", type=Path, nargs="*", default=[])
    ap.add_argument("--into", type=Path)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.mode == "create":
        if not (a.slug and a.spec):
            ap.error("create needs <slug> --spec SPEC.md")
        sb = create(a.root, a.slug, a.spec, a.include)
        print(f"✓ sandbox: {sb}")
        print("spawn hint: cwd を上の dir に pin し、prompt は「REVIEW-SPEC.md を読んで実行。token = <TOKEN>」だけ。")
        print("receipt: make-review-sandbox.py collect", a.slug, "--into <campaign dir>  → 汚染 grep → 独立再実装 → ledger 記入")
        return 0
    if a.mode == "collect":
        if not (a.slug and a.into):
            ap.error("collect needs <slug> --into DEST_DIR")
        got = collect(a.root, a.slug, a.into)
        for g in got:
            print(f"✓ copied {g}")
        print("次: 禁止 source の語彙で汚染 grep → 主要 finding を別 script で独立再実装 → novel_to_requester / second_eye 記入")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
