#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""python が非 ASCII を含む長い 1 行を coding cookie 無しで読めなくなる境界 (file 実行と stdin = heredoc 実行の両方) を二分探索で測り、 cookie を置けば通るかも確かめる。 python を更新したら再測定する道具。--selftest 内蔵。

正本 = [`conventions/shell-env.md#python-file-long-nonascii-line`](../conventions/shell-env.md#python-file-long-nonascii-line)。
そこに書いた閾値 (system python 3.9.6 で 1 行 ~1 KB) は**その版での実測**であって python 一般の性質ではない。
版が変わったら本 script で測り直し、 消えていれば規約を緩め、 変わっていれば数字を直す。

使い方:

    python3 probe-python-nonascii-line.py                          # 既定 = /usr/bin/python3
    python3 probe-python-nonascii-line.py --python /opt/homebrew/bin/python3
    python3 probe-python-nonascii-line.py --selftest

出力の "no failure up to N bytes" はその長さまで罠が無いという意味 (境界が無いのではなく、 探した範囲に無い)。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

LO, HI = 100, 20000


def program(nbytes: int) -> bytes:
    """one line `s = "あ…"` of about nbytes UTF-8 bytes (あ = 3 bytes), then a print."""
    body = "あ" * max(1, (nbytes - 6) // 3)
    return f's = "{body}"\nprint(len(s))\n'.encode("utf-8")


def line_len(nbytes: int) -> int:
    return len(program(nbytes).splitlines()[0])


def runs_stdin(py: str, src: bytes) -> bool:
    return subprocess.run([py, "-"], input=src, capture_output=True).returncode == 0


def runs_file(py: str, src: bytes) -> bool:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "probe.py"
        f.write_bytes(src)
        return subprocess.run([py, str(f)], capture_output=True).returncode == 0


def boundary(ok, lo: int = LO, hi: int = HI) -> tuple[int, int] | None:
    """(last passing n, first failing n) for a monotone predicate; None if nothing fails up to hi.
    Raises if even lo fails (then the probe program itself is broken, not the line length)."""
    if not ok(lo):
        raise RuntimeError(f"fails already at {lo} bytes: the probe itself is broken")
    if ok(hi):
        return None
    while hi - lo > 3:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo, hi


def measure(py: str) -> dict:
    out = {"python": subprocess.run([py, "--version"], capture_output=True, text=True).stdout.strip()}
    for name, runner in (("stdin", runs_stdin), ("file", runs_file)):
        b = boundary(lambda n: runner(py, program(n)))
        out[name] = None if b is None else (line_len(b[0]), line_len(b[1]))
    cookie = b"# -*- coding: utf-8 -*-\n" + program(8000)
    out["cookie_stdin_8000"] = runs_stdin(py, cookie)
    out["cookie_file_8000"] = runs_file(py, cookie)
    return out


def selftest() -> int:
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    check("boundary finds the edge of a synthetic predicate within 3", (lambda b: b[0] < 1024 <= b[1] and b[1] - b[0] <= 3)(
        boundary(lambda n: n < 1024)))
    check("boundary reports no failure in range as None (not a fake edge)", boundary(lambda n: True) is None)
    try:
        boundary(lambda n: False)
        check("a probe that fails at the lower end raises  [foil: broken probe read as an edge]", False)
    except RuntimeError:
        check("a probe that fails at the lower end raises  [foil: broken probe read as an edge]", True)
    src = program(500)
    check("the probe program is one line of the requested size plus a print",
          abs(line_len(500) - 500) <= 3 and src.count(b"\n") == 2 and "あ".encode() in src)
    check("a short non-ASCII program runs through stdin and file with this interpreter",
          runs_stdin(sys.executable, program(200)) and runs_file(sys.executable, program(200)))
    check("a cookie-first long program runs with this interpreter",
          runs_stdin(sys.executable, b"# -*- coding: utf-8 -*-\n" + program(6000)))
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--python", default="/usr/bin/python3")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    m = measure(a.python)
    print(f"python: {m['python']} ({a.python})")
    for name, label in (("stdin", "stdin (python3 - <<'PY')"), ("file", "file  (python3 x.py)    ")):
        b = m[name]
        print(f"{label}: " + (f"no failure up to {line_len(HI)} bytes" if b is None
                              else f"last OK ~{b[0]} bytes / first FAIL ~{b[1]} bytes (one line, no cookie)"))
    print(f"coding cookie, 8000-byte line: stdin {'OK' if m['cookie_stdin_8000'] else 'FAIL'} / "
          f"file {'OK' if m['cookie_file_8000'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
