#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""(old, new) の置換 pair 列を 1 file に当てる前に、 契約 (各 old は正確に 1 回 / 全検査が通るまで書かない) に加えて「再実行で二重に入る」「old が長い別物の先頭」 を拒否し、 必要なら patch 後の写しで test を回してから、 原子的に書く。--selftest 内蔵。

契約の正本 = [`conventions/batch-text-edits.md`](../conventions/batch-text-edits.md#batch-text-contract)。
本 script はその機械化で、 手書きの patch script が毎回書き直していた部分を 1 つにする。

使い方:

    python3 apply-text-pairs.py TARGET PAIRS.py                  # 検査 + 書込み
    python3 apply-text-pairs.py TARGET PAIRS.py --dry-run        # 検査 + unified diff の表示だけ
    python3 apply-text-pairs.py TARGET PAIRS.py --test 'python3 {} --selftest'
    python3 apply-text-pairs.py --selftest

- `PAIRS.py` は `PAIRS = [(old, new), ...]` を定義する python file (三重引用符で長い日本語も読める形のまま書ける)。
  pair は前から順に、 **前の pair を当てた後の text** に当たる (後の pair が前の pair の出力を掴んでよい)。
- `TARGET` は必須 (既定の path を持たない)。 既定値が live な file を指す patch script は、 引数を付け忘れた
  1 回で本物を書き換える (2026-09-13 実測: 写しに当てるつもりの再実行が engine 本体に二重に入った)。

拒否するもの (1 つでもあれば何も書かない):

| 検査 | 何を防ぐか |
|---|---|
| `old` の出現が 1 回でない | 0 回 = typo / 別 file、 2 回以上 = 誤爆 |
| `new` が `old` を含み、 `new` が既に在る | 挿入型 pair の再実行。 `old` は `new` の中に残るので「正確に 1 回」 を**通ってしまう** |
| `old` の端が識別子・path の途中で切れている | `](DESIGN.md` が `](DESIGN.md.local)` の先頭に当たる型 (`--allow-prefix` で明示的に許す) |
| `--test` の command が patch 後の写しで失敗 | 壊れた版を保存しない (git hook の engine は保存した瞬間に全 repo へ配布される) |

`--test` は TARGET の親 dir を丸ごと一時 dir に写し (同じ dir の module を path で import する script のため)、
写しの TARGET に patch 後の text を置いて command を走らせる。 `{}` は写しの TARGET の path、 cwd は写しの dir。
書込みは同じ dir の一時 file → `os.replace` (途中まで書かれた file を hook が読む瞬間を作らない)、 file mode は保つ。
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOKEN = re.compile(r"[A-Za-z0-9_.\-/]")


def load_pairs(path: Path) -> list[tuple[str, str]]:
    ns: dict = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    pairs = ns.get("PAIRS")
    if not isinstance(pairs, (list, tuple)) or not all(
            isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(s, str) for s in p) for p in pairs):
        raise SystemExit(f"{path}: PAIRS must be a list of (old, new) string pairs")
    return [(o, n) for o, n in pairs]


def plan(text: str, pairs: list[tuple[str, str]], allow_prefix: bool = False) -> tuple[str, list[str]]:
    """(patched text, problems). Problems are collected for every pair; text is only meaningful when
    there are none."""
    problems = []
    for i, (old, new) in enumerate(pairs, 1):
        label = f"pair {i} ({old[:50]!r})"
        if not old:
            problems.append(f"{label}: empty old")
            continue
        if old == new:
            problems.append(f"{label}: old == new (a no-op pair)")
            continue
        if old in new and new in text:
            problems.append(f"{label}: new already present and contains old = this pair looks applied already "
                            f"(an insertion pair passes the exactly-once check on every re-run)")
            continue
        n = text.count(old)
        if n != 1:
            problems.append(f"{label}: matches {n} times (must be exactly 1)")
            continue
        at = text.index(old)
        before = text[at - 1] if at > 0 else ""
        after = text[at + len(old)] if at + len(old) < len(text) else ""
        if not allow_prefix and (
                (after and TOKEN.match(old[-1]) and TOKEN.match(after)) or
                (before and TOKEN.match(old[0]) and TOKEN.match(before))):
            ctx = text[max(0, at - 10): at + len(old) + 10].replace("\n", "\\n")
            problems.append(f"{label}: old starts or ends inside a longer token ({ctx!r}); include the delimiter, "
                            f"or pass --allow-prefix if that is intended")
            continue
        text = text.replace(old, new, 1)
    return text, problems


def run_test(target: Path, patched: str, cmd: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        dst_dir = Path(td) / target.parent.name
        shutil.copytree(target.parent, dst_dir, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules"))
        copy = dst_dir / target.name
        copy.write_text(patched, encoding="utf-8")
        argv = [a.replace("{}", str(copy)) for a in shlex.split(cmd)]
        r = subprocess.run(argv, cwd=dst_dir, capture_output=True, text=True)
        return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def write_atomic(target: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".apply-tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def apply(target: Path, pairs: list[tuple[str, str]], dry_run: bool = False, test: str | None = None,
          allow_prefix: bool = False, quiet: bool = False) -> int:
    old_text = target.read_text(encoding="utf-8")
    new_text, problems = plan(old_text, pairs, allow_prefix)
    for p in problems:
        print(f"[REFUSED] {p}")
    if problems:
        print(f"nothing written to {target}")
        return 1
    diff = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=0))
    plus = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    minus = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    if dry_run:
        print("\n".join(diff[:200]))
        print(f"[dry-run] {len(pairs)} pair(s) apply cleanly: +{plus} -{minus} line(s)")
        return 0
    if test:
        ok, out = run_test(target, new_text, test)
        if not ok:
            if not quiet:
                print(out)
            print(f"[REFUSED] --test failed on the patched copy; nothing written to {target}")
            return 1
    write_atomic(target, new_text)
    if not quiet:
        print(f"[applied] {len(pairs)} pair(s) to {target}: +{plus} -{minus} line(s)"
              + (" (test passed on the patched copy)" if test else ""))
    return 0


def selftest() -> int:
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "pkg"
        d.mkdir()
        tgt = d / "tool.py"
        base = 'import helper\n\ndef main():\n    return helper.VALUE\n\nprint(main())\n'
        tgt.write_text(base, encoding="utf-8")
        os.chmod(tgt, 0o755)
        (d / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
        q = dict(quiet=True)

        ins = [("def main():\n", "def extra():\n    return 2\n\n\ndef main():\n")]
        check("an insertion pair applies once", apply(tgt, ins, **q) == 0 and tgt.read_text().count("def extra") == 1)
        check("the naive exactly-once contract would apply it AGAIN (the foil has teeth)",
              tgt.read_text().count("def main():\n") == 1)
        check("re-running the insertion pair is refused  [foil: 2026-09-13 duplicate argparse option]",
              apply(tgt, ins, **q) == 1 and tgt.read_text().count("def extra") == 1)

        tgt.write_text(base, encoding="utf-8")
        check("zero matches is refused, nothing written", apply(tgt, [("nope", "x")], **q) == 1 and tgt.read_text() == base)
        tgt.write_text(base + "helper\n", encoding="utf-8")
        check("two matches is refused", apply(tgt, [("import helper\n", "import os\n"), ("helper.", "h.")], **q) == 1
              and tgt.read_text() == base + "helper\n")

        link = "see [k](DESIGN.md.local) and more\n"
        (d / "doc.md").write_text(link, encoding="utf-8")
        check("an old that stops inside a longer token is refused  [foil: prefix-shaped key]",
              apply(d / "doc.md", [("](DESIGN.md", "](../DESIGN.md")], **q) == 1)
        check("--allow-prefix lets it through when intended",
              apply(d / "doc.md", [("](DESIGN.md", "](../DESIGN.md")], allow_prefix=True, **q) == 0)
        check("a delimiter-terminated old is not a prefix case",
              plan("a [x](DESIGN.md) b", [("](DESIGN.md)", "](../DESIGN.md)")])[1] == [])
        check("CJK text next to the match is not a token boundary",
              plan("前置き本文の続き", [("本文", "本体")])[1] == [])

        tgt.write_text(base, encoding="utf-8")
        chain = [("return helper.VALUE", "return helper.VALUE + 1"), ("+ 1\n", "+ 41\n")]
        check("a later pair may match the output of an earlier pair", plan(base, chain)[0].count("VALUE + 41") == 1)
        check("an old that starts mid-token (after `.`) is refused too",
              plan(base, [("VALUE", "V")])[1] != [])
        check("one bad pair in a batch writes nothing", apply(tgt, chain + [("absent", "x")], **q) == 1
              and tgt.read_text() == base)

        broken = [("def main():\n", "def main(:\n")]
        check("--test on the patched copy blocks a broken version",
              apply(tgt, broken, test="python3 {}", **q) == 1 and tgt.read_text() == base)
        good = [("return helper.VALUE", "return helper.VALUE * 5")]
        check("--test can import a sibling module from the copied dir, then the file is written",
              apply(tgt, good, test="python3 {}", **q) == 0 and "* 5" in tgt.read_text())
        check("file mode survives the atomic write", os.stat(tgt).st_mode & 0o777 == 0o755)
        check("no temp file is left next to the target", not list(d.glob("*.apply-tmp")))
        before = tgt.read_text()
        check("--dry-run writes nothing", apply(tgt, [("* 5", "* 6")], dry_run=True, **q) == 0
              and tgt.read_text() == before)
        pf = Path(td) / "pairs.py"
        pf.write_text('PAIRS = [("* 5", """* 7""")]\n', encoding="utf-8")
        r = subprocess.run([sys.executable, __file__, str(tgt), str(pf)], capture_output=True, text=True)
        check("CLI: TARGET + PAIRS.py applies", r.returncode == 0 and "* 7" in tgt.read_text())
        r = subprocess.run([sys.executable, __file__, str(pf)], capture_output=True, text=True)
        check("CLI: there is no default target (one path alone is an error)", r.returncode != 0)
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", nargs="?", type=Path)
    ap.add_argument("pairs", nargs="?", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", metavar="CMD", help="run CMD on a patched copy first; {} = the copy's path")
    ap.add_argument("--allow-prefix", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.target and a.pairs):
        ap.error("TARGET and PAIRS.py are both required (there is no default target)")
    return apply(a.target, load_pairs(a.pairs), a.dry_run, a.test, a.allow_prefix, a.quiet)


if __name__ == "__main__":
    sys.exit(main())
