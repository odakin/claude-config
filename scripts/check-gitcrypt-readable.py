#!/usr/bin/env python3
"""check-gitcrypt-readable.py — 暗号化 file が「このマシンで実際に読めるか」を必ず可視に報告する。

## なぜ要るか

git-crypt でロックされたマシンでは、暗号化 file を開くと **暗号文がそのまま読める**。
JSON/YAML として parse すれば当然失敗するが、 呼び出し側が fail-open で書かれていると
**黙って 0 件を返す**。 「予定が 1 件も無い」 と「読めていない」 が区別できなくなる —
守られていないのに守られているつもりになる、 という最悪の壊れ方をする。

なので、 暗号化を入れるなら必ずこの検査とセットにする。 沈黙という状態を作らず、
READABLE / LOCKED / SKIP の 3 状態のどれかを毎回 1 行出す。

## 判定

  .gitattributes の `filter=git-crypt` が付いた path を対象に、 working tree の
  先頭 9 byte が git-crypt の magic (\\x00GITCRYPT) かどうかを見る。

    鍵が無い (= CI 等)                       → SKIP (= 検査していないと申告して exit 0)
    鍵はあるのに暗号文のまま                 → LOCKED (exit 1。 unlock が要る)
    平文で読める                             → READABLE (exit 0)

  「鍵が無い」 を FAIL にしない理由: CI の runner は clone するだけで鍵を持たない。
  このリポの既存契約 (= 各 test が自分で SKIP を宣言して exit 0) に合わせる。

使い方: check-gitcrypt-readable.py [--selftest]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MAGIC = b"\x00GITCRYPT"
PERSONAL_KEY = Path.home() / ".secrets" / "git-crypt.key"


def encrypted_patterns(root: Path):
    """`.gitattributes` で git-crypt 対象に指定された pattern を返す。"""
    ga = root / ".gitattributes"
    if not ga.is_file():
        return []
    out = []
    for line in ga.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "filter=git-crypt" not in line:
            continue
        out.append(line.split()[0])
    return out


def targets(root: Path, patterns):
    """pattern に当たる追跡 file を返す (= git 自身に解決させる)。"""
    if not patterns:
        return []
    # -z は必須: 既定の ls-files は **非 ASCII の path を引用符 + 8 進エスケープで返す**
    # ("docs/\346\227\245..." の形)。 そのまま Path にすると存在しない path になり、
    # 「読めない = LOCKED」 と誤検知する。 2026-09-12 に日本語 file 名を持つ 6 repo が
    # 一斉に LOCKED と報告され、 実際は全て健全だった。
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", *patterns],
                       capture_output=True)
    names = r.stdout.split(b"\x00")
    return [root / n.decode("utf-8", "surrogateescape") for n in names if n]


def locked(path: Path):
    """working tree の中身が暗号文のままか。 読めなければ None。"""
    try:
        with path.open("rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return None


def check(root: Path, key: Path = PERSONAL_KEY):
    pats = encrypted_patterns(root)
    print("── git-crypt で暗号化した file がこのマシンで読めるか")
    if not pats:
        print("   対象外: このリポに git-crypt 対象の宣言が無い")
        return 0
    files = targets(root, pats)
    if not files:
        print(f"   対象外: 宣言はあるが該当する追跡 file が無い ({', '.join(pats)})")
        return 0
    if not key.is_file():
        print(f"   SKIP: 鍵が無いマシン ({key}) — {len(files)} file は検査していない")
        print("         (= CI の runner 等。 検査しなかったと申告するだけで、 緑ではない)")
        return 0
    bad = [f for f in files if locked(f) is not False]
    if bad:
        print(f"   🔒 LOCKED: {len(bad)}/{len(files)} file が暗号文のまま読めない")
        for f in bad[:5]:
            print(f"        {f.relative_to(root)}")
        print("   ※ この状態で private/ を読む script は fail-open で **黙って 0 件**を返す。")
        print("      復旧: cd " + str(root) + " && git-crypt unlock " + str(key))
        return 1
    print(f"   READABLE: {len(files)} file すべて平文で読める ({', '.join(pats)})")
    return 0


def selftest():
    import tempfile

    fails = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)

        # (1) 宣言が無ければ対象外
        if check(root, key=root / "nokey") != 0:
            fails.append("宣言が無いのに 0 を返さない")

        (root / ".gitattributes").write_text("secret.json filter=git-crypt diff=git-crypt\n",
                                             encoding="utf-8")
        (root / "secret.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)

        # (2) 鍵が無ければ SKIP (= FAIL にしない)
        if check(root, key=root / "nokey") != 0:
            fails.append("鍵が無いマシンで FAIL にしてしまう (= CI が落ちる)")

        # (3) 鍵はあるのに暗号文 → LOCKED
        key = root / "key"; key.write_bytes(b"x")
        (root / "secret.json").write_bytes(MAGIC + b"\x00rest")
        if check(root, key=key) != 1:
            fails.append("暗号文のままなのに LOCKED を報告しない")

        # (4) 平文なら READABLE
        (root / "secret.json").write_text("{}\n", encoding="utf-8")
        if check(root, key=key) != 0:
            fails.append("平文なのに READABLE を報告しない")

        # (5) 日本語 file 名を LOCKED と誤判定しない (= ls-files の引用に壊されない。
        #     2026-09-12 に 6 repo が一斉に誤 LOCKED になった回帰 test)
        (root / ".gitattributes").write_text("*.json filter=git-crypt diff=git-crypt\n",
                                             encoding="utf-8")
        (root / "日本語の名前.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
        if check(root, key=key) != 0:
            fails.append("日本語 file 名を LOCKED と誤検知する")

    if fails:
        print("SELFTEST FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 1
    print("SELFTEST PASS (5 checks)")
    return 0


def check_fleet(base: Path = None, key: Path = PERSONAL_KEY):
    """~/Claude 配下の **git-crypt 宣言がある全 repo** を見る。

    1 repo だけ見ると、 暗号化の本体が別 repo にある場合に取りこぼす
    (2026-09-12: 1 つの repo だけ見て、 実際に読まれている別 repo 側の cache を見落としかけた)。 宣言のある repo を git 自身に数えさせる。
    """
    base = base or (Path.home() / "Claude")
    repos = [d for d in sorted(base.iterdir())
             if (d / ".git").exists() and encrypted_patterns(d)]
    if not repos:
        print("── git-crypt で暗号化した file がこのマシンで読めるか")
        print("   対象外: git-crypt 宣言のある repo が無い")
        return 0
    rc = 0
    for d in repos:
        print(f"  [{d.name}]", end=" ")
        rc |= check(d, key)
    return rc


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--fleet" in sys.argv:
        sys.exit(check_fleet())
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, encoding="utf-8", errors="replace")
    sys.exit(check(Path(r.stdout.strip() or ".")))
