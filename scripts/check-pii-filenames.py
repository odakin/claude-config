#!/usr/bin/env python3
"""check-pii-filenames.py — 個人情報が file 名に出ている追跡 file を検出する。

## なぜ要るか

git-crypt のような「中身を暗号化する」 仕組みは **file 名を暗号化しない**。
file 名は remote のツリーに平文で残るので、 識別子を名前に持つ file
(例 `answers/A00X0001-1.jpg`) は、 それ自体が「誰が居たか」 の一覧になる。

畳んだ dir を `.gitignore` に入れても、 **新しい期・新しい科目の dir は自動では
守られない**。 取り込み script が新しい path に同じ形の file を置いた瞬間にまた
露出するので、 それを毎回見る。

## 設定 (= 検出する識別子の形は repo 側が宣言する)

  `~/.claude/pii-filename-patterns.txt` に 1 行 1 正規表現。 `#` 行と空行は無視。
  **この file が無ければ何もしない (対象外)** — 識別子の形は組織ごとに違い、
  それ自体が漏らしたくない情報になりうるので、 この script には書かない。

  例 (= 自分の環境の形に置き換えて書く):
      # 学籍番号のような固定長 ID
      [A-Z][0-9]{2}[A-Z][0-9]{4}

## 判定

  作業ルート配下の全 repo の **追跡 file 名** を見て、 いずれかの pattern に
  一致するものがあれば FAIL。 16 進の長い連なり (= build 成果物の hash) の中に
  埋もれた一致は除く。

  ⚠️ 形だけで判定する。 誤検知が出たら pattern を闇雲に絞るのではなく、 その file 名が
     本当に個人情報でないかを人が確かめること。

使い方: check-pii-filenames.py [--selftest]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PATTERN_FILE = Path.home() / ".claude" / "pii-filename-patterns.txt"
# 16 進の長い連なり (= build 成果物の hash) は識別子ではない。
# 例: `Foo.dll_A55E1029D67B7172.mvfrm` は `A55E1029` が固定長 ID の形に一致してしまう
# (2026-09-12 に 20 件の誤検知を出した)。
HEX_RUN = re.compile(r"[0-9A-F]{12,}")


def load_patterns(path: Path = None):
    path = Path(path or os.environ.get("CLAUDE_PII_FILENAME_PATTERNS") or PATTERN_FILE)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            out.append(re.compile(line))
        except re.error:
            continue
    return out


def _real_hits(name, pats):
    """file 名から識別子らしき token を返す (16 進 hash の中のものは除く)。"""
    spans = [m.span() for m in HEX_RUN.finditer(name)]
    out = []
    for rx in pats:
        for m in rx.finditer(name):
            if any(s <= m.start() and m.end() <= e for s, e in spans):
                continue
            out.append(m.group())
    return out


def tracked_names(repo: Path):
    """追跡 file の path。 -z で引用・8 進エスケープを避ける。"""
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    return [n.decode("utf-8", "surrogateescape") for n in r.stdout.split(b"\x00") if n]


def scan(base: Path = None, pats=None):
    base = base or (Path.home() / "Claude")
    pats = load_patterns() if pats is None else pats
    hits = []
    for repo in sorted(base.iterdir()):
        if not (repo / ".git").exists():
            continue
        for name in tracked_names(repo):
            if _real_hits(name, pats):
                hits.append((repo.name, name))
    return hits


def check(base: Path = None, pats=None):
    pats = load_patterns() if pats is None else pats
    print("── 追跡 file 名に個人識別子が出ていないか")
    if not pats:
        print(f"   対象外: pattern 未設定 ({PATTERN_FILE})")
        return 0
    hits = scan(base, pats)
    if not hits:
        print("   OK: 該当なし")
        return 0
    ids = {m for _r, n in hits for m in _real_hits(n, pats)}
    print(f"   🚫 {len(hits)} file / 識別子 {len(ids)} 個が file 名に出ている")
    by_repo = {}
    for r, n in hits:
        by_repo.setdefault(r, []).append(n)
    for r, ns in by_repo.items():
        print(f"        [{r}] {len(ns)} file  例: {Path(ns[0]).parent}/…")
    print("   ※ git-crypt は中身しか暗号化しない = この名前は remote のツリーに平文で見える。")
    print("      対処: その dir を暗号化 tar に畳む (pack-pii-dirs.sh pack)")
    return 1


def selftest():
    import tempfile

    fails = []
    P = [re.compile(r"[A-Z][0-9]{2}[A-Z][0-9]{4}")]
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        repo = base / "r"; repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], capture_output=True)

        (repo / "ok.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        if check(base, pats=P) != 0:
            fails.append("無関係な file 名で誤検知した")

        (repo / "A00X0001-1.jpg").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        if check(base, pats=P) != 1:
            fails.append("識別子入りの file 名を検出できない")

        (repo / "Foo.dll_A55E1029D67B7172.mvfrm").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        if len(scan(base, P)) != 1:
            fails.append("16 進 hash を識別子と誤検知した")

        # 日本語 file 名でも落ちない (= ls-files の引用に壊されない)
        (repo / "日本語の名前.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        try:
            check(base, pats=P)
        except Exception as e:
            fails.append(f"日本語 file 名で落ちる: {e}")

        # 追跡されていなければ対象外 (= .gitignore で畳んだ後の状態)
        subprocess.run(["git", "-C", str(repo), "rm", "-q", "--cached", "A00X0001-1.jpg"],
                       capture_output=True)
        if check(base, pats=P) != 0:
            fails.append("追跡から外した file をまだ数えている")

    if fails:
        print("SELFTEST FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 1
    print("SELFTEST PASS (5 checks)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else check())
