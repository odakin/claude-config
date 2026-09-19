#!/usr/bin/env python3
"""sync-protected-dirs.py — 「触る前に確認を出す dir」 の宣言を machine-local の一覧 file に配る (冪等)

hooks/protected-dir-access-guard.py が読む一覧 (~/.claude/protected-dirs.txt など) は machine-local
(git 非同期) なので、 あるマシンで足した dir は他マシンに届かない。 一方で settings の path rule を
deny から ask へ緩めるマシンでは、 file を名指ししない読み方 (grep -r / find / script の中の走査) を
止めるのはこの一覧だけになる = 一覧が空のマシンだけ Bash 側が無防備になる。

そこで「保護する dir」 を git に載せた宣言 file に書き、 session 開始の auto-apply 層から毎回
このスクリプトを呼ぶ。 **足すだけ**で、 宣言に無い行は消さない (= 各マシンが独自に足した dir と、
別経路の一覧 〔leak-pattern-sources.txt 等〕 を壊さない)。

⚠️ 順序: gate の kind を入れ替えるときは、 **先にこの一覧を配り、 後から deny を外す**。 一覧は即時に
効き、 settings の rule は次 session からなので、 逆にすると確認なしで読める窓が開く。
規約 = conventions/confidential-repo-boundary.md#protected-dir-access-guard

宣言 file の形 (= 配布先と同じ形式): 1 行 1 dir、 `#` 以降は comment、 空行は無視、 `~` と ${HOME} 可。
重複判定は `~` / `${HOME}` を展開し末尾の `/` を落とした path で行う (= 同じ dir を綴り違いで二重に
足さない)。 書き込みは symlink の実体に対して行う。

usage:
  sync-protected-dirs.py --decl DECL.txt [--dest PATH]            # 監査: 足りない dir を列挙して exit 1
  sync-protected-dirs.py --decl DECL.txt [--dest PATH] --apply    # 適用: 足した時だけ出力、 exit 0
  sync-protected-dirs.py --selftest

  DECL = 宣言 file (git に載せる側)
  PATH = 配布先。 既定 ~/.claude/protected-dirs.txt (dir が無ければ何もしない = fail-open)
  失敗 (宣言 file が読めない等) = stderr に理由、 exit 2、 何も書かない
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _expand(line: str, home: str) -> str:
    """重複判定用に `~` / ${HOME} を展開し、 末尾の `/` を落とす。"""
    for pre in ("${HOME}", "$HOME", "~"):
        if line == pre:
            return home
        if line.startswith(pre + "/"):
            line = home + line[len(pre):]
            break
    return line.rstrip("/") or "/"


def read_decl(path: Path) -> list[str]:
    """宣言 file の dir を宣言どおりの綴りで返す (comment / 空行を落とす)。"""
    out = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def missing(decl: list[str], dest: Path, home: str) -> list[str]:
    """dest にまだ無い dir を宣言どおりの綴りで返す。 dest が無ければ全件。"""
    have = set()
    try:
        for raw in Path(dest).read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                have.add(_expand(line, home))
    except FileNotFoundError:
        pass
    out, seen = [], set()
    for d in decl:
        key = _expand(d, home)
        if key not in have and key not in seen:
            seen.add(key)
            out.append(d)
    return out


def apply(decl: list[str], dest: Path, home: str) -> list[str]:
    """足りない dir を末尾に足して、 足した dir を返す (空 = 変更なし、 冪等)。"""
    add = missing(decl, dest, home)
    if not add:
        return []
    p = Path(os.path.realpath(dest))
    body = ""
    if p.exists():
        body = p.read_text(encoding="utf-8")
        if body and not body.endswith("\n"):
            body += "\n"
    p.write_text(body + "".join(d + "\n" for d in add), encoding="utf-8")
    return add


def selftest() -> int:
    import tempfile
    fails = []

    def ck(name, cond):
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        home = str(td / "home")
        os.makedirs(home)
        decl = td / "decl.txt"
        decl.write_text("# 注釈\n\n~/work/alpha   # 行内の注釈\n${HOME}/work/beta\n", encoding="utf-8")
        ck("read_decl: comment と空行を落とす", read_decl(decl) == ["~/work/alpha", "${HOME}/work/beta"])

        dest = td / ".claude" / "protected-dirs.txt"
        dest.parent.mkdir()
        ck("audit: dest 不在なら全件", missing(read_decl(decl), dest, home) == ["~/work/alpha", "${HOME}/work/beta"])
        add = apply(read_decl(decl), dest, home)
        ck("apply: 宣言どおりの綴りで足す", add == ["~/work/alpha", "${HOME}/work/beta"])
        ck("apply: 中身", dest.read_text(encoding="utf-8") == "~/work/alpha\n${HOME}/work/beta\n")
        ck("apply: 2 回目は空 (冪等)", apply(read_decl(decl), dest, home) == [])

        # 綴り違い (絶対 path) で既に在る dir は足さない / 宣言に無い行は消さない
        dest2 = td / "d2.txt"
        dest2.write_text("# 手で足した分\n%s/work/alpha/\n~/local/only\n" % home, encoding="utf-8")
        ck("audit: 綴り違いの同じ dir は足りない扱いにしない",
           missing(read_decl(decl), dest2, home) == ["${HOME}/work/beta"])
        apply(read_decl(decl), dest2, home)
        body = dest2.read_text(encoding="utf-8")
        ck("apply: 宣言に無い行と comment を残す", "~/local/only\n" in body and "# 手で足した分" in body)
        ck("apply: 足りない 1 件だけ足す", body.count("work/beta") == 1 and body.count("work/alpha") == 1)

        # 改行で終わっていない dest でも行が潰れない
        dest3 = td / "d3.txt"
        dest3.write_text("~/x/y", encoding="utf-8")
        apply(["~/work/alpha"], dest3, home)
        ck("apply: 改行無しの末尾に足しても潰れない",
           dest3.read_text(encoding="utf-8") == "~/x/y\n~/work/alpha\n")

        # symlink は実体を書く
        real, link = td / "real.txt", td / "link.txt"
        real.write_text("", encoding="utf-8")
        link.symlink_to(real)
        apply(["~/work/alpha"], link, home)
        ck("apply: symlink を保ち実体を更新",
           link.is_symlink() and real.read_text(encoding="utf-8") == "~/work/alpha\n")
    if fails:
        print("sync-protected-dirs selftest FAIL:", fails)
        return 1
    print("sync-protected-dirs selftest: ALL PASS (10 checks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--decl", type=Path)
    ap.add_argument("--dest", type=Path, default=Path.home() / ".claude" / "protected-dirs.txt")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.decl:
        ap.error("--decl が必要")
    home = str(Path.home()).rstrip("/")
    try:
        decl = read_decl(a.decl)
        if not a.dest.parent.is_dir():
            return 0  # 配布先の dir が無いマシンでは何もしない (fail-open)
        if a.apply:
            for d in apply(decl, a.dest, home):
                print(f"保護 dir を追加 (= Bash / Grep / Glob で触る前に確認): {d}")
            return 0
        gaps = missing(decl, a.dest, home)
    except Exception as e:
        print(f"sync-protected-dirs: {e}", file=sys.stderr)
        return 2
    for d in gaps:
        print(f"一覧に無い: {d}")
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
