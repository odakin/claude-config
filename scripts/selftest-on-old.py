#!/usr/bin/env python3
"""selftest-on-old.py — 新しい版の selftest の関数を、 直す前の版 (git の rev) の module の中で回す = 新しい検査が直す前の実装で赤くなるかを、 file を書き換えずに見る。--selftest 内蔵。

用途: 欠陥を直して検査を足した turn に「その検査は直す前の実装で落ちる」 を確かめる
(docs/convention-design-principles.md#isolation-shortens-the-path の (d))。 selftest を関数で持つ script なら、
直す前の版を作業 tree に戻したり、 修正だけを戻した写しを作ったりせずに、 新しい検査の全部を直す前の実装に当てられる。
新しい関数の code object を直す前の module の名前空間で実行する (`types.FunctionType(新.__code__, 旧.__dict__)`) ので、
検査の中で呼ぶ関数・定数はすべて直す前の版のものになる。

使い方:
  selftest-on-old.py <新しい版の file>                       # 直す前の版 = 同じ file の HEAD、 関数 = _selftest
  selftest-on-old.py <file> --rev <rev> --func selftest     # 版と関数名を選ぶ
  selftest-on-old.py <写しの file> --tracked <repo の file>  # 新しい版が別名の写し (例 `.foo.py.wip`) のとき、 直す前の版を取る file
  selftest-on-old.py <file> --old <直す前の版の file>        # git の版でなく手元の file を直す前の版にする
  selftest-on-old.py --selftest

終了値 = 関数の返り値 (int なら。 直す前の実装で赤 = 0 でない) / 2 = 使い方・版を読めない / 3 = 関数が例外で止まった。

動き:
- 直す前の版は lib/git_blob.py の `read_blob` で読む (`git cat-file --filters` = git-crypt で暗号化される path も平文。
  `git show <rev>:<path>` は暗号文を返し、 読み込みが null byte で落ちる。 実測)
- 直す前の版は新しい版と**同じ dir に隠し file** (`.<名前>.selftest-old-<pid>.py`) として置いて読み、 終わったら消す
  = 隣の module の import と `__file__` からの相対 path が本物と同じに解決する (1 file だけ別の dir に写すと import で落ちて
  「手前で落ちて緑」 になる = 上の節の罠。 実測)。 その名の file・link が既に在れば書かずに止まる
- 両方の版を `SourceFileLoader` で読む = 拡張子が `.py` でない写し (`.wip`) も読める (spec_from_file_location は
  loader を推せず None になる。 実測)。 その dir を sys.path の先頭に足す (script として起動したときと同じ)

限界:
- 両方の版の module の top level が 1 回ずつ走る = import のときに state を書く module には使わない
- 関数は module の top level の関数 (closure を持たない) に限る
- 新しい検査が直す前の版に無い名前 (新しく足した helper) を直接呼ぶと NameError でそこで止まり、 後の検査が見えない (exit 3)
  = 新しい検査は直す前の版にもある入口 (公開の関数) を通して書くと、 直す前の実装で 1 件ずつ FAIL が並ぶ (実測)
- 検査の中で `globals()` を書き換える selftest は、 直す前の module の globals を書き換える (戻す処理も同じ globals に効く)

OS: macOS / Linux / Windows で同じに動く (標準 library + git、 Python 3.8+)。
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import traceback
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from git_blob import read_blob  # noqa: E402


def _load(path: Path, name: str) -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_file_location(name, str(path), loader=loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


def _repo_root(p: Path) -> Path | None:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(p.parent), capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def old_source(tracked: Path, rev: str) -> bytes:
    """tracked (作業 tree の file) の rev の版の中身。 読めなければ ValueError。"""
    root = _repo_root(tracked)
    if root is None:
        raise ValueError(f"{tracked} は git の repo の中に無い (--old で直す前の版を渡す)")
    rel = tracked.resolve().relative_to(root.resolve()).as_posix()
    rc, data = read_blob(f"{rev}:{rel}", cwd=str(root))
    if rc != 0:
        raise ValueError(f"{rev}:{rel} を読めない")
    if data.startswith(b"\x00GITCRYPT"):
        raise ValueError(f"{rev}:{rel} が暗号文のまま (repo を unlock する)")
    return data


def run(new_file: Path, old_bytes: bytes, func: str, label: str) -> int:
    new_file = new_file.resolve()
    hidden = new_file.parent / f".{new_file.name.lstrip('.')}.selftest-old-{os.getpid()}.py"
    if hidden.exists() or hidden.is_symlink():
        print(f"❌ {hidden} が既に在る = 書かない", file=sys.stderr)
        return 2
    print(f"直す前の版 = {label} で、 {new_file.name} の {func} を回す")
    sys.path.insert(0, str(new_file.parent))
    try:
        hidden.write_bytes(old_bytes)
        old = _load(hidden, f"_selftest_on_old_old_{os.getpid()}")
        new = _load(new_file, f"_selftest_on_old_new_{os.getpid()}")
        fn = getattr(new, func, None)
        if not isinstance(fn, types.FunctionType):
            print(f"❌ {new_file.name} に関数 {func} が無い", file=sys.stderr)
            return 2
        if fn.__code__.co_freevars:
            print(f"❌ {func} は closure (top level の関数でない)", file=sys.stderr)
            return 2
        moved = types.FunctionType(fn.__code__, old.__dict__, func, fn.__defaults__)
        try:
            rv = moved()
        except NameError as ex:
            print(f"⚠️ 直す前の版に無い名前を呼んで止まった ({ex}) = 以降の検査は見ていない。"
                  " 新しい検査を直す前の版にもある入口から呼ぶ形にすると 1 件ずつ見える")
            return 3
        except Exception:  # noqa: BLE001
            print("⚠️ 関数が例外で止まった:\n" + traceback.format_exc(limit=3))
            return 3
        return rv if isinstance(rv, int) else 0
    finally:
        try:
            hidden.unlink()
        except FileNotFoundError:
            pass


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("new_file")
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--func", default="_selftest")
    ap.add_argument("--tracked", help="直す前の版を取る repo の file (既定 = new_file)")
    ap.add_argument("--old", help="直す前の版の file (git の版の代わり)")
    a = ap.parse_args(argv)
    new_file = Path(a.new_file)
    if not new_file.is_file():
        print(f"❌ {new_file} が無い", file=sys.stderr)
        return 2
    try:
        if a.old:
            data, label = Path(a.old).read_bytes(), a.old
        else:
            tracked = Path(a.tracked) if a.tracked else new_file
            data, label = old_source(tracked, a.rev), f"{a.rev}:{tracked}"
    except (OSError, ValueError) as ex:
        print(f"❌ {ex}", file=sys.stderr)
        return 2
    return run(new_file, data, a.func, label)


# ---------------------------------------------------------------------------
# selftest (一時 repo の合成の module。 暗号化 path の代わりに長さの変わる clean / smudge filter)
# ---------------------------------------------------------------------------
def _selftest() -> int:
    fails: list[str] = []

    def check(cond: bool, label: str) -> None:
        print(("PASS: " if cond else "FAIL: ") + label)
        if not cond:
            fails.append(label)

    old_mod = ("from helper_lib import base\n\ndef add(a, b):\n    return a - b + base()\n\n"
               "def _selftest():\n    return 0\n")
    new_mod = ("from helper_lib import base\n\ndef add(a, b):\n    return a + b + base()\n\n"
               "def _selftest():\n    bad = 0 if add(1, 1) == 2 else 1\n    print('add:', 'PASS' if not bad else 'FAIL')\n"
               "    return bad\n\ndef helper2():\n    return 1\n\n"
               "def calls_new_helper():\n    return 0 if helper2() == 1 else 1\n")
    me = [sys.executable, str(Path(__file__).resolve())]
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        git = lambda *a: subprocess.run(["git", *a], cwd=td, capture_output=True, text=True, check=True)  # noqa: E731
        git("init", "-q")
        git("config", "user.email", "t@example.invalid")
        git("config", "user.name", "t")
        # 暗号化 path の代わり: 先頭に印を足す clean と、 外す smudge (blob は作業 tree と違う中身になる)
        git("config", "filter.mark.clean", "sed '1s/^/#MARK /'")
        git("config", "filter.mark.smudge", "sed '1s/^#MARK //'")
        (d / ".gitattributes").write_text("mod.py filter=mark\n", encoding="utf-8")
        (d / "helper_lib.py").write_text("def base():\n    return 0\n", encoding="utf-8")
        (d / "mod.py").write_text(old_mod, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "old")
        shown = subprocess.run(["git", "show", "HEAD:mod.py"], cwd=td, capture_output=True, text=True).stdout
        check(shown.startswith("#MARK "), "前提: git show は filter の前の blob を返す (暗号文と同じ形)")
        (d / "mod.py").write_text(new_mod, encoding="utf-8")

        r = subprocess.run(me + [str(d / "mod.py")], capture_output=True, text=True)
        check(r.returncode == 1 and "add: FAIL" in r.stdout, f"新しい検査が直す前の版で赤 (exit {r.returncode})")
        check("ModuleNotFoundError" not in r.stdout + r.stderr, "直す前の版は隣の module を import できる (同じ dir に置く)")
        check(not list(d.glob(".*selftest-old*")), "隠し file は終わったら消える")

        (d / ".mod.py.wip").write_text(new_mod, encoding="utf-8")
        r = subprocess.run(me + [str(d / ".mod.py.wip"), "--tracked", str(d / "mod.py")], capture_output=True, text=True)
        check(r.returncode == 1, f"拡張子の違う写し (.wip) も読める (exit {r.returncode}: {r.stderr.strip()[:80]})")

        (d / "old_copy.py").write_text(new_mod.replace("_selftest", "_unused"), encoding="utf-8")
        r = subprocess.run(me + [str(d / "mod.py"), "--old", str(d / "old_copy.py")], capture_output=True, text=True)
        check(r.returncode == 0, f"--old に直した後と同じ実装を渡せば緑 (exit {r.returncode})")

        r = subprocess.run(me + [str(d / "mod.py"), "--func", "calls_new_helper"], capture_output=True, text=True)
        check(r.returncode == 3 and "直す前の版に無い名前" in r.stdout, f"直す前の版に無い helper を呼ぶと exit 3 (exit {r.returncode})")

        r = subprocess.run(me + [str(d / "mod.py"), "--func", "nope"], capture_output=True, text=True)
        check(r.returncode == 2, "関数が無ければ exit 2")
        r = subprocess.run(me + [str(d / "mod.py"), "--rev", "no-such-rev"], capture_output=True, text=True)
        check(r.returncode == 2, "版を読めなければ exit 2")

    print(f"\nselftest-on-old selftest: {'all PASS' if not fails else f'{len(fails)} 件 FAIL'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
