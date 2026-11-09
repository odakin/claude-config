#!/usr/bin/env python3
"""Copy named top-level functions of one Python file into another (foil: run the new tests against the version before a fix).

Usage:
    transplant-functions.py --from NEW.py --into OLD.py --func NAME [--func NAME ...] --out OUT.py
    transplant-functions.py --selftest

Each named function (a `def` at the top level, with its decorators) is cut from --from and replaces the function of the
same name in --into. A name that either file lacks is refused: the old version must already have the entry point, so
that its own selftest runner calls the swapped tests. The result is written to --out, never in place.

Typical use: put the new test functions into the version a review saw, run that copy's selftest, and check that exactly
the new tests fail while every old test still passes (the new tests catch what the fix closed; the old tests still run
against the old code). Record the command and the failing lines next to the receipt, not only the conclusion.
Function spans come from the ast module (first decorator line to the end of the body), so the files must parse.
"""
from __future__ import annotations

import argparse
import ast
import sys
import tempfile
from pathlib import Path


def spans(src: str) -> dict[str, tuple[int, int]]:
    """Top-level function name -> (first line, last line), 1-based and inclusive, decorators included."""
    out: dict[str, tuple[int, int]] = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            out[node.name] = (first, node.end_lineno or node.lineno)
    return out


def transplant(new_src: str, old_src: str, names: list[str]) -> str:
    """old_src with each named function replaced by the one in new_src. ValueError names what is missing."""
    new_spans, old_spans = spans(new_src), spans(old_src)
    missing = [n for n in names if n not in new_spans] + [n for n in names if n not in old_spans]
    if missing:
        where = ["--from" if n not in new_spans else "--into" for n in missing]
        raise ValueError("no top-level function " + ", ".join(f"{n} in {w}" for n, w in zip(missing, where)))
    new_lines, old_lines = new_src.splitlines(keepends=True), old_src.splitlines(keepends=True)
    for name in sorted(names, key=lambda n: old_spans[n][0], reverse=True):  # bottom first: earlier spans stay valid
        a, b = new_spans[name]
        c, d = old_spans[name]
        body = new_lines[a - 1:b]
        if body and not body[-1].endswith("\n"):
            body[-1] += "\n"
        old_lines[c - 1:d] = body
    return "".join(old_lines)


def selftest() -> int:
    fails = 0

    def check(label: str, ok: bool) -> None:
        nonlocal fails
        print(("  ok: " if ok else "  NG: ") + label)
        fails += 0 if ok else 1

    old = ("import os\n\n\ndef keep():\n    return 1\n\n\n@staticmethod\ndef tests(check):\n    check('old', True)\n\n\n"
           "def tail():\n    return 2\n")
    new = ("def tests(check):\n    check('old', True)\n    check('new', fix())\n\n\ndef keep():\n    return 99\n")
    got = transplant(new, old, ["tests"])
    check("the named function is replaced, its decorator with it", "check('new', fix())" in got and "@staticmethod" not in got)
    check("the other functions of --into stay as they were", "return 1" in got and "return 2" in got and "return 99" not in got)
    check("the result still parses", bool(ast.parse(got)))
    for args, label in ((["absent"], "a name that --from lacks is refused"),
                        (["tail"], "a name that --into has but --from lacks is refused")):
        try:
            transplant(new, old, args)
            check(label, False)
        except ValueError:
            check(label, True)
    two = transplant(new + "\n\ndef tail():\n    return 3\n", old, ["tests", "tail"])
    check("two functions in one call (the later one first, so line numbers stay right)",
          "return 3" in two and "check('new', fix())" in two and "return 1" in two)
    with tempfile.TemporaryDirectory() as td:
        n, o, r = Path(td, "n.py"), Path(td, "o.py"), Path(td, "r.py")
        n.write_text(new, encoding="utf-8")
        o.write_text(old, encoding="utf-8")
        rc = main(["--from", str(n), "--into", str(o), "--func", "tests", "--out", str(r)])
        check("the CLI writes --out and leaves --into alone", rc == 0 and r.read_text(encoding="utf-8") == got
              and o.read_text(encoding="utf-8") == old)
        check("the CLI refuses to write over --into", main(["--from", str(n), "--into", str(o), "--func", "tests",
                                                            "--out", str(o)]) == 2)
    print("selftest: " + ("ALL PASS" if not fails else f"FAILED {fails}"))
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--from", dest="src", help="the file that has the new functions")
    ap.add_argument("--into", help="the file to put them into (read only)")
    ap.add_argument("--func", action="append", default=[], help="a top-level function name (repeat)")
    ap.add_argument("--out", help="where to write the result (not --into)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.src and a.into and a.func and a.out):
        ap.error("--from, --into, --func and --out are required")
    if Path(a.out).resolve() == Path(a.into).resolve():
        print("transplant-functions: --out must not be --into (the old version stays as it was)", file=sys.stderr)
        return 2
    try:
        res = transplant(Path(a.src).read_text(encoding="utf-8"), Path(a.into).read_text(encoding="utf-8"), a.func)
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"transplant-functions: {exc}", file=sys.stderr)
        return 2
    Path(a.out).write_text(res, encoding="utf-8")
    print(f"wrote {a.out} ({', '.join(a.func)} from {a.src} into {a.into})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
