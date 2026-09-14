#!/usr/bin/env python3
"""check-ledger-merge-loss.py — merge / rebase で台帳の entry が黙って消えていないかを id で照合する。

## なぜ要るのか

filter (git-crypt 等) で暗号化された file は object store 上 **binary** なので、 git は 3-way merge を
試みられない。 症状は 2 つあり、 後者が危険:

- `merge` は `CONFLICT (content)` を出すが **conflict marker が入らない** — 開いても `<<<<<<<` が
  無いので「解決済み」 に見える。
- `rebase` では**片側が採用されて成功したように見える**ことがある。 2 session が append-only 台帳
  (TODO / inbox の yaml) の末尾に追記していると、 **後から rebase した側の追記だけが消えたまま
  push される**。

しかも **件数では気づけない**: 両側が 1 件ずつ足していれば、 片方が消えても総数は同じになる。
∴ 照合は **id の集合**で行う必要がある。

## どうやって復号するか (= 実装の鍵)

`git cat-file --filters <rev>:<path>` は **smudge filter を通した内容**を返す (= git-crypt の repo で
復号済みの YAML が得られる)。 `git show <rev>:<path>` は暗号文のままなので使えない。

## 使い方

    # merge/rebase を解決した後、 commit する前に:
    python3 check-ledger-merge-loss.py TODO.yaml --revs HEAD origin/main

    # 解決済み file の代わりに任意の rev を検査対象にする
    python3 check-ledger-merge-loss.py TODO.yaml --revs HEAD@{1} origin/main --target HEAD

exit 1 = いずれかの rev に在った id が対象から消えている (= 復旧が要る)。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def read_rev(path: str, rev: str, cwd: Path) -> str | None:
    """rev の版を **smudge filter 込み**で読む (= git-crypt の repo でも平文)。"""
    return _git(["cat-file", "--filters", f"{rev}:{path}"], cwd)


def ids_of(text: str | None) -> set[str] | None:
    """YAML の list-of-dict から id を集める。 parse できなければ None (= 検査不能)。"""
    if text is None:
        return None
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    return {str(e["id"]) for e in data if isinstance(e, dict) and e.get("id") is not None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="repo 相対の台帳 path (例: TODO.yaml)")
    ap.add_argument("--revs", nargs="+", default=["HEAD", "ORIG_HEAD"],
                    help="この rev 群に在った id が対象に残っているかを見る")
    ap.add_argument("--target", default=None,
                    help="検査対象の rev (既定 = working tree の file)")
    ap.add_argument("--repo", default=".", help="repo root (既定 = cwd)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    cwd = Path(args.repo).resolve()
    if args.target:
        target_txt = read_rev(args.path, args.target, cwd)
        target_name = args.target
    else:
        try:
            target_txt = (cwd / args.path).read_text(encoding="utf-8")
        except Exception:
            target_txt = None
        target_name = "working tree"
    target = ids_of(target_txt)
    if target is None:
        print(f"⚠️  {args.path} ({target_name}) を list-of-dict の YAML として読めない = 検査不能")
        return 1

    missing_any = False
    for rev in args.revs:
        side = ids_of(read_rev(args.path, rev, cwd))
        if side is None:
            print(f"   · {rev}: 読めない / 対象外 (skip)")
            continue
        lost = sorted(side - target)
        if lost:
            missing_any = True
            print(f"🚨 {rev} に在った id が {target_name} に無い ({len(lost)} 件):")
            for i in lost:
                print(f"     - {i}")
        else:
            print(f"   ✅ {rev}: {len(side)} 件すべて残っている")

    if missing_any:
        print("\n復旧: 上流版を取り (git checkout <upstream> -- <path>)、 自分の変更を再適用して")
        print("      merge commit にする。 rebase で押し通さない。 再検査は本 script をもう一度。")
        return 1
    print(f"\n{target_name}: {len(target)} 件、 消えた id なし")
    return 0


def _selftest() -> int:
    npass = nfail = 0

    def check(cond, name):
        nonlocal npass, nfail
        if cond:
            npass += 1
            print(f"  PASS: {name}")
        else:
            nfail += 1
            print(f"  FAIL: {name}")

    y = "- id: a\n  x: 1\n- id: b\n  x: 2\n"
    check(ids_of(y) == {"a", "b"}, "list-of-dict から id を集める")
    check(ids_of("- id: a\n- {}\n- id: c\n") == {"a", "c"}, "id を持たない要素は無視")
    check(ids_of("not: a list\n") is None, "list でない YAML は検査不能 (None)")
    check(ids_of("{{ broken") is None, "壊れた YAML は検査不能 (None)")
    check(ids_of(None) is None, "読めなかった rev は None")
    # 件数が同じでも id が違えば損失を検出できる (= 本 script の存在理由)
    mine = ids_of("- id: a\n- id: mine\n")
    theirs = ids_of("- id: a\n- id: theirs\n")
    merged = ids_of("- id: a\n- id: theirs\n")
    check(len(mine) == len(merged) and bool(mine - merged),
          "件数が同じでも失われた id を検出する (= 件数では気づけない、 の核)")
    check(not (theirs - merged), "残った側は損失ゼロと判定される")

    print(f"\n==== RESULT: PASS={npass} FAIL={nfail} ====")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
