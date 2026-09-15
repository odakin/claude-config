#!/usr/bin/env python3
"""public_tree_accept.py — 公開 repo の棚卸し受理一覧 (.claude/public-tree-accept.txt) の `generated:` 宣言を読む。

正本: claude-config/scripts/lib/public_tree_accept.py
規律: conventions/confidential-repo-boundary.md#generated-data-declaration

受理一覧の普通の行は「見た上で残す token」 (Tier A、 scan-public-tree.sh が扱う)。 この module は
もう 1 種類の行だけを扱う:

    generated: <git pathspec glob>   # <何が・どこから生成しているか>

= **owner が書いていない、 外部の公開データを機械が変換して置いた file** (例: 官公庁の公開 xlsx を
CI が毎日 JSON に直した物)。 中身は第三者の公開記録で、 人名・連絡先・日付と件数が大量に並ぶので、
実名 (Tier B)・連絡先 (Tier A)・活動の事実 (Tier E) の棚卸しが数千行単位で鳴り、 行ごとの承認も
データ更新のたびに失効する。 **棚卸しからだけ**外す (= commit gate には効かない)。

path 単位の除外は「その file に後から入った本物も黙る」 (docs/convention-design-principles.md#semantic-detector-ack-ratchet)。
その代償を型で絞る:
  - 宣言できるのは **データ形式の file だけ** (.json .jsonl .ndjson .csv .tsv .xml .geojson)。 文章・code は
    1 file でも混ざれば宣言ごと無効 (= docs/ や src/ を丸ごと外す抜け道にしない)
  - glob は tracked file に 1 つ以上当たること、 `#` の後に生成元を書くこと
  - 外した file の数と glob は走査のたびに表示する (= 黙って外さない)

使い方:
  python3 public_tree_accept.py --generated REPO     # 外す file を 1 行 1 path で stdout。 宣言の誤りは stderr + exit 1
  python3 public_tree_accept.py --selftest

  from public_tree_accept import generated_files      # (files:set, problems:list, summary:list)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ACCEPT = Path(".claude") / "public-tree-accept.txt"
DATA_SUFFIXES = (".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".xml", ".geojson")
PREFIX = "generated:"


def declarations(repo: Path) -> list:
    """[(pattern, reason, line number)]"""
    path = Path(repo) / ACCEPT
    if not path.is_file():
        return []
    out = []
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = raw.strip()
        if not s.startswith(PREFIX):
            continue
        body, _, reason = s[len(PREFIX):].partition("#")
        out.append((body.strip(), reason.strip(), i))
    return out


def _ls(repo: Path, pattern: str) -> list:
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--", f":(glob){pattern}"],
                       capture_output=True)
    if r.returncode != 0:
        return []
    return [p for p in r.stdout.decode("utf-8", errors="replace").split("\0") if p]


def generated_files(repo) -> tuple:
    repo = Path(repo)
    files, problems, summary = set(), [], []
    for pattern, reason, ln in declarations(repo):
        where = f"{ACCEPT}:{ln}"
        if not pattern or pattern in ("*", "**", "**/*", "."):
            problems.append(f"{where}: glob が空か全体 (`{pattern}`)")
            continue
        if not reason:
            problems.append(f"{where}: `# 生成元` が無い (`{pattern}`)")
            continue
        hit = _ls(repo, pattern)
        if not hit:
            problems.append(f"{where}: tracked file に当たらない (`{pattern}`)")
            continue
        bad = [p for p in hit if not p.lower().endswith(DATA_SUFFIXES)]
        if bad:
            problems.append(f"{where}: データ形式でない file を含む (`{pattern}` → {', '.join(bad[:3])}"
                            f"{' …' if len(bad) > 3 else ''})")
            continue
        files.update(hit)
        summary.append(f"{pattern} ({len(hit)} file)")
    return files, problems, summary


def _selftest() -> int:
    fails = 0

    def expect(name, cond):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name)
        fails += 0 if cond else 1

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "data").mkdir()
        (repo / "docs").mkdir()
        (repo / ".claude").mkdir()
        for rel in ("data/a.json", "data/b.json", "docs/index.md", "docs/data.json"):
            (repo / rel).write_text("x\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

        def run(lines):
            (repo / ACCEPT).write_text("\n".join(lines) + "\n")
            return generated_files(repo)

        f, p, s = run(["# comment", "token-a  # ok", "generated: data/*.json  # CI が公開 xlsx から変換"])
        expect("data glob with a producer -> its files", f == {"data/a.json", "data/b.json"} and not p and s)
        f, p, _ = run(["generated: docs/*  # 生成物"])
        expect("foil: a glob that also hits prose -> whole declaration rejected", not f and p)
        f, p, _ = run(["generated: data/*.json"])
        expect("foil: no producer after # -> rejected", not f and p)
        f, p, _ = run(["generated: **  # all"])
        expect("foil: whole-tree glob -> rejected", not f and p)
        f, p, _ = run(["generated: nothing/*.json  # x"])
        expect("foil: glob with no tracked file -> reported", not f and p)
        f, p, _ = run(["generated: docs/data.json  # x", "generated: data/a.json  # y"])
        expect("several declarations add up", f == {"docs/data.json", "data/a.json"} and not p)
    print(f"public_tree_accept selftest: {'OK' if fails == 0 else f'{fails} FAIL'}")
    return 1 if fails else 0


def main(argv: list) -> int:
    if "--selftest" in argv:
        return _selftest()
    if len(argv) == 2 and argv[0] == "--generated":
        files, problems, _ = generated_files(argv[1])
        for p in problems:
            print(p, file=sys.stderr)
        sys.stdout.write("".join(f + "\n" for f in sorted(files)))
        return 1 if problems else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
