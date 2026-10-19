#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""python-pin-floor.py — requirements.txt の固定した依存 (name==version) が要る Python の版の下限と、 wheel が揃う版の上限を PyPI から出し、 宣言 (.python-version) と照合する

## なぜ

repo の文書に「Python ≥ 3.X」 と人が書くと、 固定した依存の実際の下限とずれる (実測: 文書の版が、 固定した依存の
requires_python の下限より 1 つ古かった = 文書の版の機械でも pip install -r は通らない)。 版の宣言を
書く・依存を上げるときに、 下限を人の記憶でなく PyPI の metadata から機械で出す。 新しすぎる版も同じで、 固定した版に
その Python 向けの wheel が無いと pip は source から build しようとする (compiler が要る・長い・失敗しうる)。

同じ metadata から、 platform ごと (macOS の arm64・x86_64、 Linux の glibc・musl × x86_64・aarch64、 Windows の x64・ARM64) に、
宣言の版で使える wheel が無い依存も出す = その環境では source から build になる (環境ごとの入口の挙動 =
conventions/python-env.md#python-env-environments)。

規約 = conventions/python-env.md#python-env-declare (宣言の書き方) / conventions/github-security-automation.md#requirement-floor-vs-python
(依存の下限を上げる PR が Python の下限も上げる話)。

## 使い方

    python3 scripts/python-pin-floor.py [requirements.txt] [--declared 3.13]
        --declared を省くと requirements.txt と同じ dir の .python-version を読む (無ければ照合しない)
    python3 scripts/python-pin-floor.py --selftest      # network を使わない合成の metadata で確かめる

出力: package ごとの requires_python と wheel の版、 下限 (= requires_python の下限の最大) と、 wheel が揃う上限
(= 版ごとの wheel しか無い package の、 一番新しい wheel の版の最小)。 abi3 / py3 の wheel や sdist しか無い package は上限に数えない。
宣言があれば、 platform ごとに宣言の版で使える wheel が無い依存 (cpXY の wheel・abi3 で XY 以下・py3 の pure を数える。
free-threaded の cpXYt と PyPy は数えない)。 platform の行は情報だけで、 終了値に効かない。
終了値: 0 = 宣言が下限以上 (上限を超えていれば ⚠️ を出すだけ) / 1 = 宣言が下限より古い / 2 = 読めない・network の失敗。
固定していない行 (>= など) は飛ばして 1 行で言う。 標準 library だけで動く。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([A-Za-z0-9._+!-]+)\s*(;.*)?$")
WHEEL_PY = re.compile(r"-(cp|pp)(\d)(\d+)-([A-Za-z0-9_]+)-")


def parse_requirements(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    pins, skipped = [], []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = PIN.match(line)
        if m:
            pins.append((m.group(1), m.group(3)))
        else:
            skipped.append(line)
    return pins, skipped


def mm(v: str) -> tuple[int, int]:
    p = re.findall(r"\d+", v)
    return (int(p[0]), int(p[1]) if len(p) > 1 else 0)


def floor_of(spec: str | None) -> tuple[int, int] | None:
    """requires_python の下限 (major, minor)。 無ければ None。"""
    if not spec:
        return None
    best = None
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"(>=|~=|==|>)\s*([0-9][0-9.*]*)", part)
        if not m:
            continue
        op, ver = m.groups()
        f = mm(ver)
        if op == ">":
            nums = re.findall(r"\d+", ver)
            if len(nums) <= 2:   # >3.11 = 3.12 から (>3.11.2 は 3.11 の途中 = 3.11 と数える)
                f = (f[0], f[1] + 1)
        if best is None or f > best:
            best = f
    return best


def wheel_ceiling(files: list[dict]) -> tuple[int, int] | None:
    """版ごとの wheel しか無いとき、 一番新しい wheel の版。 abi3 / py3 の wheel があれば None (上限なし)。"""
    newest = None
    for f in files:
        if f.get("packagetype") != "bdist_wheel":
            continue
        name = f.get("filename", "")
        if "-py3-" in name or "-py2.py3-" in name or "-abi3-" in name:
            return None
        m = WHEEL_PY.search(name)
        if not m:
            continue
        v = (int(m.group(2)), int(m.group(3)))
        if newest is None or v > newest:
            newest = v
    return newest


# platform の行: (表示名, plat tag の判定)。 plat tag は wheel の file 名の最後の欄 (. で複数を並べる)
PLATFORMS = (
    ("macOS arm64", lambda t: t.startswith("macosx_") and t.endswith(("_arm64", "_universal2"))),
    ("macOS x86_64", lambda t: t.startswith("macosx_") and t.endswith(("_x86_64", "_universal2", "_intel"))),
    ("Linux x86_64 glibc", lambda t: t.startswith("manylinux") and t.endswith("_x86_64")),
    ("Linux aarch64 glibc", lambda t: t.startswith("manylinux") and t.endswith("_aarch64")),
    ("Linux x86_64 musl", lambda t: t.startswith("musllinux") and t.endswith("_x86_64")),
    ("Linux aarch64 musl", lambda t: t.startswith("musllinux") and t.endswith("_aarch64")),
    ("Windows x64", lambda t: t == "win_amd64"),
    ("Windows ARM64", lambda t: t == "win_arm64"),
)


def wheel_tags(filename: str) -> tuple[set[str], set[str], set[str]] | None:
    """wheel の file 名 → (python tag, abi tag, platform tag) の集合 (PEP 425 の . で並べた形を開く)。"""
    if not filename.endswith(".whl"):
        return None
    parts = filename[:-4].split("-")
    if len(parts) < 5:
        return None
    return set(parts[-3].split(".")), set(parts[-2].split(".")), set(parts[-1].split("."))


def wheel_fits(py: set[str], abi: set[str], declared: tuple[int, int]) -> bool:
    """その wheel が宣言の版の CPython (free-threaded でない) に入るか。"""
    cp = f"cp{declared[0]}{declared[1]}"
    if cp in py and (cp in abi or "abi3" in abi or "none" in abi):
        return True
    for t in py:
        m = re.fullmatch(r"cp(\d)(\d+)", t)
        if m and "abi3" in abi and (int(m.group(1)), int(m.group(2))) <= declared:
            return True
        if "none" in abi and t in ("py3", f"py{declared[0]}{declared[1]}"):
            return True
    return False


def platform_gaps(files_by_pkg: list[tuple[str, list[dict]]], declared: tuple[int, int]) -> list[tuple[str, list[str]]]:
    """platform ごとに、 宣言の版で使える wheel が無い package の名前 (= そこでは source から build)。"""
    out = []
    for label, pred in PLATFORMS:
        missing = []
        for name, files in files_by_pkg:
            ok = False
            for f in files:
                if f.get("packagetype") != "bdist_wheel":
                    continue
                tags = wheel_tags(f.get("filename", ""))
                if not tags or not wheel_fits(tags[0], tags[1], declared):
                    continue
                if "any" in tags[2] or any(pred(t) for t in tags[2]):
                    ok = True
                    break
            if not ok:
                missing.append(name)
        out.append((label, missing))
    return out


def fetch(name: str, version: str) -> dict:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def fmt(v: tuple[int, int] | None) -> str:
    return "-" if v is None else f"{v[0]}.{v[1]}"


def analyse(pins: list[tuple[str, str]], getter) -> tuple[list[tuple], tuple[int, int] | None, list[str],
                                                          tuple[int, int] | None, list[str], list[tuple[str, list[dict]]]]:
    rows, floor, floor_by, ceil, ceil_by, files_by_pkg = [], None, [], None, [], []
    for name, ver in pins:
        d = getter(name, ver)
        files_by_pkg.append((name, d.get("urls") or []))
        rp = (d.get("info") or {}).get("requires_python")
        f = floor_of(rp)
        c = wheel_ceiling(d.get("urls") or [])
        rows.append((name, ver, rp or "(なし)", fmt(c) if c else "上限なし"))
        if f is not None:
            if floor is None or f > floor:
                floor, floor_by = f, [name]
            elif f == floor:
                floor_by.append(name)
        if c is not None:
            if ceil is None or c < ceil:
                ceil, ceil_by = c, [name]
            elif c == ceil:
                ceil_by.append(name)
    return rows, floor, floor_by, ceil, ceil_by, files_by_pkg


def read_declared(req: Path, declared: str | None) -> str | None:
    if declared:
        return declared
    pv = req.parent / ".python-version"
    if pv.exists():
        for line in pv.read_text().splitlines():
            line = re.sub(r"#.*", "", line).strip()
            line = re.sub(r"^[A-Za-z]*@", "", line)
            if re.match(r"\d+\.\d+", line):
                return line
    return None


def report(req_text: str, declared: str | None, getter, out=print) -> int:
    pins, skipped = parse_requirements(req_text)
    if not pins:
        out("固定した依存 (name==version) が無い")
        return 0
    try:
        rows, floor, floor_by, ceil, ceil_by, files_by_pkg = analyse(pins, getter)
    except Exception as e:  # network / 名前の誤り
        out(f"PyPI から読めない: {e}")
        return 2
    w = max(len(r[0]) for r in rows)
    out(f"{'package':<{w}}  {'version':<10} {'requires_python':<16} wheel の上限")
    for r in rows:
        out(f"{r[0]:<{w}}  {r[1]:<10} {r[2]:<16} {r[3]}")
    for s in skipped:
        out(f"(固定していないので飛ばした: {s})")
    out(f"→ 下限 = {fmt(floor)}" + (f" ({', '.join(floor_by)})" if floor_by else "")
        + f" / wheel が揃う上限 = {fmt(ceil)}" + (f" ({', '.join(ceil_by)})" if ceil_by else ""))
    if not declared:
        out("宣言 (.python-version) が無いので照合していない")
        return 0
    d = mm(declared)
    gaps = platform_gaps(files_by_pkg, d)
    if all(not miss for _, miss in gaps):
        out(f"platform ごとの wheel (Python {declared}): {len(gaps)} 種の platform 全部に揃う")
    else:
        out(f"platform ごとの wheel (Python {declared}。 無い依存は、 その platform では pip が source から build する = compiler と header が要る):")
        lw = max(len(label) for label, _ in gaps)
        for label, miss in gaps:
            out(f"  {label:<{lw}}  " + ("✅" if not miss else "⚠️ wheel 無し: " + ", ".join(miss)))
    if floor is not None and d < floor:
        out(f"❌ 宣言 {declared} は下限 {fmt(floor)} より古い = この版の Python では pip install -r が通らない")
        return 1
    if ceil is not None and d > ceil:
        out(f"⚠️ 宣言 {declared} は wheel が揃う上限 {fmt(ceil)} より新しい = {', '.join(ceil_by)} を source から build しようとする")
        return 0
    out(f"✅ 宣言 {declared} は下限以上・wheel の揃う範囲")
    return 0


def selftest() -> int:
    fails = []

    def wheel(tag: str, abi: str | None = None) -> dict:
        abi = abi or tag
        return {"packagetype": "bdist_wheel", "filename": f"x-1-{tag}-{abi}-macosx_11_0_arm64.whl"}

    meta = {
        ("alpha", "2.0"): {"info": {"requires_python": ">=3.12"}, "urls": [wheel("cp312"), wheel("cp313"), wheel("cp315")]},
        ("beta", "1.1"): {"info": {"requires_python": ">=3.11"}, "urls": [wheel("cp311"), wheel("cp314")]},
        ("gamma", "0.3"): {"info": {"requires_python": ">=3.9"}, "urls": [wheel("cp39", "abi3")]},
        ("delta", "5"): {"info": {"requires_python": None},
                         "urls": [{"packagetype": "bdist_wheel", "filename": "delta-5-py3-none-any.whl"}]},
    }

    def getter(n, v):
        return meta[(n, v)]

    req = "# 合成\nalpha==2.0\nbeta[extra]==1.1 ; python_version >= '3'\ngamma==0.3\ndelta==5\nepsilon>=1\n"
    lines: list[str] = []
    rc = report(req, "3.11", getter, out=lines.append)
    text = "\n".join(lines)
    if rc != 1 or "下限 = 3.12 (alpha)" not in text or "上限 = 3.14 (beta)" not in text:
        fails.append(f"3.11 の宣言は下限 3.12 で ❌ のはず:\n{text}")
    if "epsilon>=1" not in text:
        fails.append("固定していない行を言っていない")
    lines.clear()
    rc = report(req, "3.13", getter, out=lines.append)
    if rc != 0 or "✅" not in "\n".join(lines):
        fails.append(f"3.13 は通るはず:\n{lines}")
    lines.clear()
    rc = report(req, "3.15", getter, out=lines.append)
    if rc != 0 or "⚠️" not in "\n".join(lines) or "beta" not in "\n".join(lines):
        fails.append(f"3.15 は上限を超える ⚠️ のはず:\n{lines}")
    for spec, want in ((">=3.12", (3, 12)), (">3.11", (3, 12)), ("~=3.10", (3, 10)), ("!=3.10.*,>=3.9,<4", (3, 9)),
                       ("==3.11.*", (3, 11)), (None, None), (">=3.8, >=3.10", (3, 10))):
        if floor_of(spec) != want:
            fails.append(f"floor_of({spec!r}) = {floor_of(spec)} (期待 {want})")
    pins, skipped = parse_requirements("a==1  # c\n-r other.txt\nb @ https://x\n\n")
    if pins != [("a", "1")] or skipped != ["b @ https://x"]:
        fails.append(f"parse_requirements: {pins} {skipped}")

    # platform ごとの wheel: 版ごとの wheel・free-threaded だけの wheel・abi3・pure・sdist だけ
    def whl(name: str) -> dict:
        return {"packagetype": "bdist_wheel", "filename": name}
    pmeta = {
        ("np", "2.0"): {"info": {"requires_python": ">=3.10"}, "urls": [
            whl("np-2.0-cp313-cp313-macosx_14_0_arm64.whl"),
            whl("np-2.0-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"),
            whl("np-2.0-cp313-cp313t-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"),
            whl("np-2.0-cp313-cp313-musllinux_1_2_x86_64.whl"), whl("np-2.0-cp313-cp313-win_amd64.whl")]},
        ("pure", "1.0"): {"info": {"requires_python": None}, "urls": [whl("pure-1.0-py3-none-any.whl")]},
        ("abi", "1.0"): {"info": {"requires_python": ">=3.9"}, "urls": [
            whl("abi-1.0-cp39-abi3-manylinux_2_28_aarch64.whl"), whl("abi-1.0-cp39-abi3-macosx_10_9_universal2.whl")]},
        ("src", "1.0"): {"info": {"requires_python": None}, "urls": [{"packagetype": "sdist", "filename": "src-1.0.tar.gz"}]},
    }
    files = [(n, pmeta[(n, v)]["urls"]) for n, v in pmeta]
    got = dict(platform_gaps(files, (3, 13)))
    want = {"macOS arm64": ["src"], "macOS x86_64": ["np", "src"], "Linux x86_64 glibc": ["abi", "src"],
            "Linux aarch64 glibc": ["np", "src"], "Linux x86_64 musl": ["abi", "src"],
            "Linux aarch64 musl": ["np", "abi", "src"], "Windows x64": ["abi", "src"], "Windows ARM64": ["np", "abi", "src"]}
    if got != want:
        fails.append(f"platform_gaps 3.13: {got}")
    got14 = dict(platform_gaps(files, (3, 14)))
    if got14["Linux x86_64 glibc"] != ["np", "abi", "src"] or got14["macOS arm64"] != ["np", "src"]:
        fails.append(f"platform_gaps 3.14 (cp313 の wheel は 3.14 に入らない、 abi3 cp39 は入る): {got14}")
    lines.clear()
    rc = report("np==2.0\npure==1.0\nabi==1.0\nsrc==1.0\n", "3.13", lambda n, v: pmeta[(n, v)], out=lines.append)
    text = "\n".join(lines)
    if rc != 0 or "Linux aarch64 musl" not in text or "⚠️ wheel 無し: np, abi, src" not in text:
        fails.append(f"report に platform の行が無い:\n{text}")
    lines.clear()
    report("pure==1.0\n", "3.13", lambda n, v: pmeta[(n, v)], out=lines.append)
    if "8 種の platform 全部に揃う" not in "\n".join(lines):
        fails.append(f"pure だけなら全部に揃うと 1 行: {lines}")

    def bad(n, v):
        raise OSError("no network")
    if report("a==1\n", "3.13", bad, out=lambda *_: None) != 2:
        fails.append("network の失敗で 2 を返さない")
    for f in fails:
        print(f"FAIL: {f}")
    print("selftest:", "OK" if not fails else f"{len(fails)} 件失敗")
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("requirements", nargs="?", default="requirements.txt", type=Path)
    ap.add_argument("--declared", help="照合する Python の版 (例 3.13)。 省くと同じ dir の .python-version")
    a = ap.parse_args()
    if not a.requirements.exists():
        print(f"{a.requirements} が無い")
        return 2
    return report(a.requirements.read_text(), read_declared(a.requirements, a.declared), fetch)


if __name__ == "__main__":
    sys.exit(main())
