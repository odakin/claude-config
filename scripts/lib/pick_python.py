#!/usr/bin/env python3
"""pick_python.py — Python の入口 (shim) が engine を起こす interpreter を、 PATH の順でなく「必要な module を import できるか」 で選ぶ。

なぜ (正本 = conventions/shell-env.md#job-python-by-capability):
  素の `python3` は発火面ごとに別の interpreter になる (agent の Bash・対話 shell・launchd で PATH の先頭が違う)。
  shell の wrapper には lib/pick-python.sh があるが、 Python の shim が `os.execv(sys.executable, ...)` で engine を起こすと、
  呼ばれた python (= PATH の先頭) に依存が無いとき engine は依存なしで走り、 fail-open の読み手は
  「Gmail から引けなかった (auth / 404 / 一時失敗)」 としか言わない (実測: 2 回。 1 回目は launchd、 2 回目は agent の Bash)。

使い方 (shim の中で):
    sys.path.insert(0, "<claude-config>/scripts/lib")
    from pick_python import pick_python
    py, env = pick_python(["googleapiclient", "google.oauth2.credentials"])
    os.execve(py, [py, ENGINE] + args, env)        # 見つからなければ py = sys.executable (= 止めない、 engine 側が警告する)

候補の順 (= 最初に全 module を import できたもの。 同じ実体は 1 回だけ試す。 lib/pick-python.sh と同じ):
  0. 今の interpreter (sys.executable) が全部 import できればそれ (subprocess を起こさない)
  1. $PICK_PYTHON (明示指定。 import できなければ見つからない扱い = 指定を黙って別のものに替えない)
  2. /Library/Developer/CommandLineTools/usr/bin/python3  3. /usr/bin/python3 (CommandLineTools があれば DEVELOPER_DIR をそこへ)
  4. PATH 上の python3 を順に
  test 用: $PICK_PYTHON_CANDIDATES (":" 区切り) で 2-4 を差し替える。 selftest = `python3 pick_python.py --selftest`
返り値: (interpreter の path, 起こすときの env)。 env は DEVELOPER_DIR を足した os.environ の写し。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

CLT_DIR = "/Library/Developer/CommandLineTools"


def _env() -> dict:
    env = dict(os.environ)
    if os.path.isdir(CLT_DIR) and not env.get("DEVELOPER_DIR"):
        env["DEVELOPER_DIR"] = CLT_DIR   # /usr/bin/python3 が Xcode のライセンスで止まる (exit 69) のを避ける
    return env


def _here_has(modules) -> bool:
    try:
        return all(importlib.util.find_spec(m) is not None for m in modules)
    except (ImportError, ValueError):   # 親 package が無い ("google.oauth2" の "google") も「無い」
        return False


def _candidates() -> list[str]:
    raw = os.environ.get("PICK_PYTHON_CANDIDATES")
    if raw is not None:
        return [c for c in raw.split(":") if c]
    out = [f"{CLT_DIR}/usr/bin/python3", "/usr/bin/python3"]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, "python3")
        if os.path.isfile(p) and os.access(p, os.X_OK):
            out.append(p)
    return out


def _imports(py: str, modules, env) -> bool:
    code = "import sys" + "".join(f"; import {m}" for m in modules)
    try:
        return subprocess.run([py, "-c", code], env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pick_python(modules) -> tuple[str, dict]:
    env = _env()
    if os.environ.get("PICK_PYTHON"):
        py = os.environ["PICK_PYTHON"]
        return (py if _imports(py, modules, env) else sys.executable), env
    if _here_has(modules):
        return sys.executable, env
    seen = {os.path.realpath(sys.executable)}
    for c in _candidates():
        if not (os.path.isfile(c) and os.access(c, os.X_OK)):
            continue
        real = os.path.realpath(c)
        if real in seen:
            continue
        seen.add(real)
        if _imports(c, modules, env):
            return c, env
    return sys.executable, env


def _selftest() -> int:
    import tempfile
    fails = 0

    def check(name, ok):
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")

    saved = {k: os.environ.get(k) for k in ("PICK_PYTHON", "PICK_PYTHON_CANDIDATES")}
    try:
        os.environ.pop("PICK_PYTHON", None)
        check("今の interpreter が持つ module (sys) なら今の interpreter", pick_python(["sys"])[0] == sys.executable)
        with tempfile.TemporaryDirectory() as d:
            mod = "pick_python_selftest_mod"
            with open(os.path.join(d, f"{mod}.py"), "w") as f:
                f.write("X = 1\n")
            fake = os.path.join(d, "py-with-mod")   # 候補の 1 つだけが module を持つ = PYTHONPATH を足して起こす wrapper
            with open(fake, "w") as f:
                f.write(f"#!/bin/sh\nPYTHONPATH={d} exec {sys.executable} \"$@\"\n")
            os.chmod(fake, 0o755)
            os.environ["PICK_PYTHON_CANDIDATES"] = f"/nonexistent/python3:{sys.executable}:{fake}"
            check("今の interpreter に無い module は、 持つ候補を選ぶ", pick_python([mod])[0] == fake)
            os.environ["PICK_PYTHON_CANDIDATES"] = f"/nonexistent/python3:{sys.executable}"
            check("どの候補にも無ければ今の interpreter (止めない)", pick_python([mod])[0] == sys.executable)
            os.environ["PICK_PYTHON"] = "/nonexistent/python3"
            check("PICK_PYTHON が import できなければ別の候補に替えない", pick_python([mod])[0] == sys.executable)
            os.environ["PICK_PYTHON"] = fake
            check("PICK_PYTHON が import できればそれ", pick_python([mod])[0] == fake)
        os.environ.pop("PICK_PYTHON", None)
        check("親 package の無い dotted name も「無い」 (例外にしない)", _here_has(["no_such_pkg_xyz.sub"]) is False)
        if os.path.isdir(CLT_DIR):
            check("CommandLineTools があれば env に DEVELOPER_DIR", _env().get("DEVELOPER_DIR") in (CLT_DIR, os.environ.get("DEVELOPER_DIR")))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print(f"selftest: {'ALL PASS' if not fails else f'{fails} FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    mods = [a for a in sys.argv[1:] if not a.startswith("-")]
    print(pick_python(mods)[0])
