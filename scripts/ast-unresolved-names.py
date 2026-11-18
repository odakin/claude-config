#!/usr/bin/env python3
"""python の候補を import も実行もせずに AST だけで読み、 関数の中で定義の無い名前が基準の版より増えていないかを比べる (当てる前に写しを回せない道具の候補の確かめ、 静的検査の道具の無い機でも動く)。 --selftest 内蔵。

使い方:
  python3 ast-unresolved-names.py <基準の版.py> <候補.py>
    exit 0 = 増えていない / 1 = 増えた (増えた (関数, 名前) を NEW: の行で出す) / 2 = どちらかが構文として読めない
  python3 ast-unresolved-names.py --selftest

なぜ:
  守りの道具 (guard) の候補のように、 当てる前に写しを動かすことを規則が止めているものは、 当てる前に確かめられるのが
  file を読むだけの形に限られる (tool-call-robustness.md#classifier-blocks-guard-approval-cli)。 構文の解析 (ast.parse) は
  書き換えで消した関数・綴りを誤った名前・足し忘れた import を拾わない。 pyflakes などの静的検査の道具が入っていない機もある
  (実測)。 この道具は、 書き換えで生まれた「どこにも定義の無い名前」 だけを、 基準の版との差で出す。

数え方:
  module の上段の関数 (async を含む) ごとに、 中で読む名前 (Name の Load) のうち、 次のどれにも無いものを (関数名, 名前) で数える:
  その関数とその中の関数・lambda の引数、 その関数の中で代入・for・with・except・import・global・nonlocal・def・class で
  束ねた名前、 module の上段で束ねた名前 (関数・class・代入・import、 上段の if / try の中も)、 builtins。
  基準の版と候補で同じ数え方をして、 候補で増えた分だけを出す (数え方の粗さで出る名前は両方に出て打ち消し合う)。

数えないもの (限界):
  - class の本体と、 上段の関数の外 (module の上段の式) で読む名前
  - 属性 (obj.name) の綴りの誤り、 引数の数・型の誤り、 import 先の module に名前が在るか
  - `from x import *` で入る名前 (どちらの版にも同じく在れば打ち消し合う)
  - 内側の関数の名前を外側の関数より先に読む順序の誤り (名前が束ねられていれば数えない)
  ∴ 0 件は「定義の無い名前が増えていない」 だけを言い、 候補が動くことの代わりにはならない (当てた後に正本の path で試験を回す)。
"""
from __future__ import annotations

import ast
import builtins
import sys
import tempfile
from collections import Counter
from pathlib import Path


def _bound_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        elif hasattr(ast, "MatchAs") and isinstance(n, getattr(ast, "MatchAs")) and n.name:
            out.add(n.name)
        elif hasattr(ast, "MatchStar") and isinstance(n, getattr(ast, "MatchStar")) and n.name:
            out.add(n.name)
    return out


def unresolved(source: str, filename: str = "<source>") -> Counter:
    """(上段の関数名, 名前) → その関数の中で読んだ回数。 SyntaxError はそのまま上げる。"""
    tree = ast.parse(source, filename)
    module = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__loader__", "__package__"}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module.add(n.name)
        else:
            module |= _bound_names(n)
    found: Counter = Counter()
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local = _bound_names(fn)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in local and n.id not in module:
                found[(fn.name, n.id)] += 1
    return found


def compare(base_path: str, cand_path: str) -> int:
    try:
        base = unresolved(Path(base_path).read_text(encoding="utf-8"), base_path)
        cand = unresolved(Path(cand_path).read_text(encoding="utf-8"), cand_path)
    except SyntaxError as exc:
        print(f"構文として読めない: {exc.filename}:{exc.lineno}: {exc.msg}")
        return 2
    new = cand - base
    print(f"定義の無い名前 (関数, 名前): 基準 {sum(base.values())} / 候補 {sum(cand.values())} / 増えた {sum(new.values())}")
    for (fn, name), count in sorted(new.items()):
        print(f"  NEW: {fn} の中の {name} ({count} 回)")
    return 1 if new else 0


def selftest() -> int:
    ok = 0
    ng: list[str] = []

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        if cond:
            ok += 1
        else:
            ng.append(label)

    base = (
        "import os\n"
        "from pathlib import Path as P\n"
        "LIMIT = 3\n"
        "def helper(x):\n"
        "    return x\n"
        "def f(a, *rest, k=1, **kw):\n"
        "    total = 0\n"
        "    for i in range(LIMIT):\n"
        "        total += i\n"
        "    try:\n"
        "        os.path.join(a)\n"
        "    except ValueError as exc:\n"
        "        print(exc)\n"
        "    def inner(y):\n"
        "        return y + total + a\n"
        "    sq = [v * v for v in rest]\n"
        "    g = lambda z: z + k\n"
        "    with open(a) as fh:\n"
        "        fh.read()\n"
        "    return helper(inner(1)) + sum(sq) + g(2) + len(kw) + len(str(P('.')))\n"
        "if LIMIT:\n"
        "    FLAG = True\n"
        "def uses_flag():\n"
        "    global COUNTER\n"
        "    COUNTER = 1\n"
        "    return FLAG, COUNTER\n"
    )
    check("基準の書き方 (引数・for・except as・内側の関数・内包・lambda・with・上段の if の中の代入・global) は 0 件",
          sum(unresolved(base).values()) == 0)
    renamed = base.replace("return helper(inner(1))", "return helperz(inner(1))")
    check("呼び出しの綴りの誤りを拾う", unresolved(renamed) - unresolved(base) == Counter({("f", "helperz"): 1}))
    removed = base.replace("def helper(x):\n    return x\n", "")
    check("書き換えで消した関数の呼び出しを拾う", unresolved(removed) - unresolved(base) == Counter({("f", "helper"): 1}))
    no_import = base.replace("import os\n", "")
    check("足し忘れた import を拾う", unresolved(no_import) - unresolved(base) == Counter({("f", "os"): 1}))
    added = base + "def g2(cfg):\n    return make_roots(cfg)\n"
    check("新しい関数が定義の無い名前を読むと拾う", unresolved(added) - unresolved(base) == Counter({("g2", "make_roots"): 1}))
    defined = added + "def make_roots(cfg):\n    return tuple(cfg)\n"
    check("その名前の関数を足せば 0 件", unresolved(defined) - unresolved(base) == Counter())
    with tempfile.TemporaryDirectory() as td:
        pb, pc, pe = Path(td) / "base.py", Path(td) / "cand.py", Path(td) / "broken.py"
        pb.write_text(base, encoding="utf-8")
        pc.write_text(renamed, encoding="utf-8")
        pe.write_text("def f(:\n", encoding="utf-8")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r_same, r_new, r_broken = compare(str(pb), str(pb)), compare(str(pb), str(pc)), compare(str(pb), str(pe))
        out = buf.getvalue()
        check("同じ file どうしは exit 0", r_same == 0)
        check("増えたら exit 1 で NEW の行に関数と名前", r_new == 1 and "NEW: f の中の helperz (1 回)" in out)
        check("構文として読めなければ exit 2", r_broken == 2 and "構文として読めない" in out)
    if ng:
        for label in ng:
            print(f"NG: {label}")
        print(f"FAILED: ok {ok} / ng {len(ng)}")
        return 1
    print(f"ALL PASS: ok {ok}")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["--selftest"]:
        return selftest()
    if len(argv) != 2 or argv[0].startswith("-"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    return compare(argv[0], argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
