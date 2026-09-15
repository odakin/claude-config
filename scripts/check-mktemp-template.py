#!/usr/bin/env python3
"""check-mktemp-template.py — `mktemp` の template で X の後ろに拡張子を付けた書き方を見つける (BSD/macOS で固定名になる)。

正本: claude-config/scripts/check-mktemp-template.py
規律: conventions/hook-authoring.md#mktemp-template-suffix

Why: GNU の mktemp は `name-XXXXXX.md` の X を置換するが、 BSD (macOS) の mktemp は **末尾の X しか置換しない**。
X の後ろに `.md` 等があると置換されず **literal の名前**で作られる。 1 回目は成功するので気づかず、 2 回目以降は
「File exists」 で失敗して空の path が返り、 その先の書き込みが全部失敗する (= 無人の週次監査が黙って壊れていた、 実測)。
同時に走る 2 本は同じ file を奪い合う。 Linux の CI では再現しない。

直し方: 拡張子が要らなければ X を末尾に置く。 要るなら `d="$(mktemp -d)"` の中に固定名で作る。

使い方:
  check-mktemp-template.py [REPO ...]      # 各 repo の tracked file (.sh .bash .zsh .py) を走査。 既定 = cwd の repo
  check-mktemp-template.py --root DIR      # DIR 直下の git repo を全部
  check-mktemp-template.py --selftest
exit: 0 = 無し / 1 = 見つけた / 2 = usage
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

SUFFIXES = (".sh", ".bash", ".zsh", ".py")
# mktemp の引数のどこかに「X が 3 つ以上 → X 以外の文字 (拡張子など)」 が続く。 `-t prefix` 形は対象外
PATTERN = re.compile(r"\bmktemp\b[^\n;|)]*?X{3,}(?=[A-Za-z0-9_.-])(?!X)[^\sX\"')]*")


def scan_text(text: str) -> list:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.lstrip()
        if s.startswith("#"):
            continue
        m = PATTERN.search(line)
        if m and not m.group(0).rstrip().endswith("X"):
            out.append((i, line.strip()))
    return out


def tracked(repo: Path) -> list:
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    if r.returncode != 0:
        return []
    return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p.endswith(SUFFIXES)]


def scan_repo(repo: Path) -> list:
    hits = []
    for rel in tracked(repo):
        if rel.endswith("check-mktemp-template.py"):
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits += [(f"{repo.name}/{rel}", i, l) for i, l in scan_text(text)]
    return hits


def selftest() -> int:
    fails = 0

    def expect(name, cond):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name)
        fails += 0 if cond else 1

    x = "X" * 6
    expect("suffix after Xs is found", scan_text(f'R="$(mktemp /tmp/report-{x}.md)"'))
    expect("suffix after 4 Xs with .py is found", scan_text(f'T="$(mktemp /tmp/t-{"X" * 4}.py)"'))
    expect("foil: Xs at the end is fine", not scan_text(f'R="$(mktemp "${{TMPDIR:-/tmp}}/report-{x}")"'))
    expect("foil: mktemp -d is fine", not scan_text('d="$(mktemp -d)"'))
    expect("foil: comment line is ignored", not scan_text(f"# mktemp /tmp/a-{x}.md was wrong"))
    expect("foil: plain mktemp is fine", not scan_text('f="$(mktemp)"'))
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "a.sh").write_text(f'x="$(mktemp /tmp/a-{x}.md)"\n')
        (repo / "b.txt").write_text(f'x="$(mktemp /tmp/a-{x}.md)"\n')
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        got = scan_repo(repo)
        expect("repo scan: only tracked scripts", len(got) == 1 and got[0][0].endswith("a.sh"))
    print(f"check-mktemp-template selftest: {'OK' if fails == 0 else f'{fails} FAIL'}")
    return 1 if fails else 0


def main(argv: list) -> int:
    if "--selftest" in argv:
        return selftest()
    repos = []
    if argv[:1] == ["--root"]:
        if len(argv) != 2:
            print(__doc__, file=sys.stderr)
            return 2
        repos = sorted(d for d in Path(argv[1]).expanduser().iterdir() if (d / ".git").exists())
    elif argv:
        repos = [Path(a).expanduser() for a in argv]
    else:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode != 0:
            print(__doc__, file=sys.stderr)
            return 2
        repos = [Path(top.stdout.strip())]
    hits = []
    for r in repos:
        hits += scan_repo(r)
    for path, i, line in hits:
        print(f"{path}:{i}: {line[:160]}")
    if hits:
        print(f"✗ [mktemp-template] {len(hits)} 箇所で X の後ろに文字がある (BSD/macOS では固定名になる。 "
              f"X を末尾に置くか mktemp -d の中に作る = conventions/hook-authoring.md#mktemp-template-suffix)")
        return 1
    print(f"ok [mktemp-template]: {len(repos)} repo")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
