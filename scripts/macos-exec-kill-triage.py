#!/usr/bin/env python3
"""macos-exec-kill-triage.py — script の exec が macOS に SIGKILL される (exit 137 / "Killed: 9" / git の "died of signal 9") 原因を、 syspolicyd の状態・unified log・file ごとの検査で揃える (読むだけ)。

用途: 同じ中身の script が場所によって kill されたりされなかったりするとき、 原因を推測で言う前に証拠を
1 コマンドで揃える。 仕組みと直し方の正本 = conventions/macos-exec-policy-kill.md、 git hook の場合の
規則 = conventions/hook-authoring.md#killed-hook-stub (直すのは scripts/heal-hook-stubs.sh)。

見るもの:
  - syspolicyd の pid・起動時刻・RSS (詰まると数 GB に膨らんでいた = 実測)
  - unified log (/usr/bin/log。 zsh では素の `log` が組み込みに取られる) の、 指定した時間帯の
    syspolicyd と kernel (AppleSystemPolicy) の署名 5 種を分ごとに数える:
      yara     = "Error performing Yara scan"                (exec 時の malware scan の失敗)
      reject   = "Terminating process due to Malware rejection"
      emfile   = "error: 100024" / "UNIX error exception: 24" (Security framework の 100000 + errno 24 = EMFILE)
      driver   = "failed to call driver"                     (判定を kernel に返せなかった)
      deny     = "Security policy would not allow process"   (kernel が exec を拒否した。 path を集計する)
      stale    = "Could not find reference"                  (待っていた process が既に居ない = 返答の遅れ)
    ⚠️ unified log は大量出力の後に行が落ちる = 件数は下限。 0 件でも「起きていない」 の証明にならない。
  - 引数の file ごと: exec の検査 (bash の script だけ。 $BASH_ENV に exit 0 だけの file を渡すので本体は
    1 行も走らない)、 inode、 xattr の名前。 kill の判定は inode に付く (同じ inode の hard link も kill、
    新しい inode の複製は通る = 実測)

使い方:
  macos-exec-kill-triage.py [--minutes 60 | --start "YYYY-MM-DD HH:MM:SS" [--end ...]] [--no-log] [FILE ...]
  macos-exec-kill-triage.py --selftest

exit: 0 = 読めた / 1 = 引数の file に kill されるものがある / 2 = 引数・環境の誤り
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE_ENV = os.path.join(HERE, "lib", "hook-exec-probe.bash")

SIGNATURES = [  # (key, 部分文字列のどれか)
    ("yara", ("Error performing Yara scan",)),
    ("reject", ("Terminating process due to Malware rejection",)),
    ("emfile", ("error: 100024", "UNIX error exception: 24")),
    ("driver", ("failed to call driver",)),
    ("deny", ("Security policy would not allow process",)),
    ("stale", ("Could not find reference",)),
]
KEYS = [k for k, _ in SIGNATURES]
PREDICATE = (
    '(process == "syspolicyd" AND (eventMessage CONTAINS "Yara scan" OR eventMessage CONTAINS "Malware rejection"'
    ' OR eventMessage CONTAINS "100024" OR eventMessage CONTAINS "exception: 24"'
    ' OR eventMessage CONTAINS "failed to call driver"))'
    ' OR (process == "kernel" AND (eventMessage CONTAINS "would not allow process"'
    ' OR eventMessage CONTAINS "Could not find reference"))'
)
LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}):\d{2}\.\d+\s")
DENY_PATH_RE = re.compile(r"would not allow process: \d+, (.*)$")


def classify(message: str) -> str | None:
    for key, needles in SIGNATURES:
        if any(n in message for n in needles):
            return key
    return None


def path_class(path: str) -> str:
    """拒否された exec の path を、 嵐の源が読める粒度にまとめる (最初の .app の名前 + 目印)。"""
    parts = path.strip().split("/")
    app = next((p for p in parts if p.endswith(".app") or p.endswith(".app.bundle")), None)
    label = app if app else "/".join(parts[-2:]) if len(parts) >= 2 else path.strip()
    if "code_sign_clone" in path:
        label += " (code_sign_clone)"
    return label


def parse_log(lines) -> tuple[dict, Counter]:
    """compact 形式の log 行 → (分ごとの署名の件数, 拒否された path の class の件数)。"""
    per_minute: dict = defaultdict(Counter)
    denied: Counter = Counter()
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        key = classify(line)
        if not key:
            continue
        per_minute[m.group(1)][key] += 1
        if key == "deny":
            d = DENY_PATH_RE.search(line)
            if d:
                denied[path_class(d.group(1))] += 1
    return per_minute, denied


def read_log(start: str | None, end: str | None, minutes: int) -> list[str]:
    cmd = ["/usr/bin/log", "show", "--style", "compact", "--predicate", PREDICATE]
    if start:
        cmd += ["--start", start]
        if end:
            cmd += ["--end", end]
    else:
        cmd += ["--last", f"{minutes}m"]
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return res.stdout.splitlines()


def syspolicyd_state() -> str:
    try:
        pid = subprocess.run(["pgrep", "-x", "syspolicyd"], capture_output=True, text=True).stdout.split()
        if not pid:
            return "syspolicyd: 見つからない"
        out = subprocess.run(["ps", "-o", "lstart=,rss=", "-p", pid[0]], capture_output=True, text=True).stdout.strip()
        *start, rss = out.split()
        return f"syspolicyd: pid {pid[0]}, 起動 {' '.join(start)}, RSS {int(rss) / 1024 / 1024:.2f} GB"
    except (OSError, ValueError):
        return "syspolicyd: 読めない"


def probe(path: str, probe_env: str = PROBE_ENV, os_name: str | None = None) -> str:
    """'killed' / 'ok' / 'unprobed:<理由>'。 bash の script だけを、 本体を走らせずに exec する。"""
    if (os_name or platform.system()) != "Darwin":
        return "unprobed:not-macos"
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        return "unprobed:not-executable"
    try:
        with open(path, "rb") as fh:
            first = fh.readline().decode("utf-8", "replace")
    except OSError:
        return "unprobed:unreadable"
    if not (first.startswith("#!") and "bash" in first):
        return "unprobed:not-bash"
    env = dict(os.environ, BASH_ENV=probe_env)
    res = subprocess.run([os.path.abspath(path)], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "killed" if res.returncode == -9 else "ok"


def xattr_names(path: str) -> str:
    try:
        out = subprocess.run(["xattr", path], capture_output=True, text=True).stdout.split()
        return ",".join(out) or "-"
    except OSError:
        return "?"


def report(per_minute: dict, denied: Counter) -> list[str]:
    out = []
    if not per_minute:
        out.append("  (署名の行なし。 ⚠️ log は落ちるので「起きていない」 の証明ではない)")
        return out
    out.append("  分                " + "".join(f"{k:>8}" for k in KEYS))
    for minute in sorted(per_minute):
        c = per_minute[minute]
        out.append(f"  {minute}  " + "".join(f"{c[k]:>8}" for k in KEYS))
    if denied:
        out.append("  exec を拒否された path (上位 5):")
        for label, n in denied.most_common(5):
            out.append(f"    {n:>8}  {label}")
    total = Counter()
    for c in per_minute.values():
        total.update(c)
    if total["yara"] or total["emfile"]:
        out.append("  → syspolicyd が scan に失敗している (Yara / EMFILE)。 この時間帯に初めて exec された file に"
                   " kill の判定が残りうる")
    if denied and denied.most_common(1)[0][1] >= 1000:
        out.append(f"  → 拒否の嵐の源の候補 = {denied.most_common(1)[0][0]}")
    return out


def selftest() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    fixture = [
        "Timestamp               Ty Process[PID:TID]",
        '2026-01-01 07:17:32.677 E  syspolicyd[527:85cf08] [com.apple.syspolicy.exec:default] Error performing Yara scan: Error Domain=com.apple.security.syspolicy.yara Code=3',
        "2026-01-01 07:17:32.677 E  syspolicyd[527:85cf08] [com.apple.syspolicy.exec:default] Terminating process due to Malware rejection: 123, <private>",
        "2026-01-01 07:17:32.678 E  syspolicyd[527:85cf08] [com.apple.syspolicy:default] Failed to generate SecStaticCode for <private> error: 100024",
        "2026-01-01 07:17:32.678 Df syspolicyd[527:85cf08] [com.apple.securityd:security_exception] UNIX error exception: 24",
        "2026-01-01 07:17:33.001 E  syspolicyd[527:85cd22] [com.apple.syspolicy.exec:default] failed to call driver: 0x3",
        "2026-01-01 07:18:01.000 Df kernel[0:1] (AppleSystemPolicy) ASP: Security policy would not allow process: 4242, /private/var/folders/x/X/com.example.Browser.code_sign_clone/code_sign_clone.a/Example Browser.app.bundle/Contents/MacOS/Helper",
        "2026-01-01 07:18:01.100 Df kernel[0:1] (AppleSystemPolicy) ASP: Security policy would not allow process: 4243, /Applications/Other.app/Contents/MacOS/Other",
        "2026-01-01 07:18:02.000 Df kernel[0:2] (AppleSystemPolicy) ASP: Could not find reference 341313, process must have died",
        "2026-01-01 07:18:02.500 Df kernel[0:2] unrelated line",
        "garbage",
    ]
    per_minute, denied = parse_log(fixture)
    check(per_minute["2026-01-01 07:17"]["yara"] == 1, "yara count")
    check(per_minute["2026-01-01 07:17"]["reject"] == 1, "reject count")
    check(per_minute["2026-01-01 07:17"]["emfile"] == 2, "emfile = both forms")
    check(per_minute["2026-01-01 07:17"]["driver"] == 1, "driver count")
    check(per_minute["2026-01-01 07:18"]["deny"] == 2, "deny count")
    check(per_minute["2026-01-01 07:18"]["stale"] == 1, "stale count")
    check(sum(sum(c.values()) for c in per_minute.values()) == 8, "unrelated / garbage lines ignored")
    check(denied["Example Browser.app.bundle (code_sign_clone)"] == 1, f"path class with marker: {dict(denied)}")
    check(denied["Other.app"] == 1, "plain .app class")
    rep = "\n".join(report(per_minute, denied))
    check("scan に失敗" in rep, "scan-failure verdict shown")
    check("落ちる" in "\n".join(report({}, Counter())), "empty report warns that the log is lossy")

    with tempfile.TemporaryDirectory() as tmp:
        body_marker = os.path.join(tmp, "ran")
        bash_hook = os.path.join(tmp, "hook")
        with open(bash_hook, "w") as fh:
            fh.write(f'#!/bin/bash\ntouch "{body_marker}"\n')
        os.chmod(bash_hook, 0o755)
        sh_hook = os.path.join(tmp, "sh-hook")
        with open(sh_hook, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(sh_hook, 0o755)
        fake_env = os.path.join(tmp, "fake.bash")
        with open(fake_env, "w") as fh:
            fh.write("kill -9 $$\n")   # 偽の検査 = 必ず SIGKILL
        check(probe(bash_hook, os_name="Darwin") == "ok", "real probe file: ok")
        check(not os.path.exists(body_marker), "probe ran no line of the hook")
        check(probe(bash_hook, probe_env=fake_env, os_name="Darwin") == "killed", "SIGKILL → killed")
        check(probe(sh_hook, os_name="Darwin") == "unprobed:not-bash", "non-bash not probed")
        check(probe(bash_hook, os_name="Linux") == "unprobed:not-macos", "non-macOS not probed")

    if fails:
        for f in fails:
            print(f"  NG: {f}")
        print(f"selftest: {len(fails)} failed")
        return 1
    print("selftest: ok")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if platform.system() != "Darwin":
        print("macOS 専用 (syspolicyd と unified log を読む)", file=sys.stderr)
        return 2
    print(syspolicyd_state())
    if not a.no_log:
        span = f"{a.start} 〜 {a.end or '今'}" if a.start else f"過去 {a.minutes} 分"
        print(f"unified log ({span}、 ⚠️ 大量出力の後は行が落ちる = 件数は下限):")
        per_minute, denied = parse_log(read_log(a.start, a.end, a.minutes))
        print("\n".join(report(per_minute, denied)))
    killed = 0
    if a.files:
        print("file ごとの exec 検査 (本体は走らせない):")
        for f in a.files:
            try:
                ino = os.stat(f).st_ino
            except OSError:
                print(f"  ?        {f} (無い)")
                continue
            verdict = probe(f)
            killed += verdict == "killed"
            print(f"  {verdict:<22} inode {ino}  xattr {xattr_names(f)}  {f}")
        if killed:
            print("  → kill の判定は inode に付く。 同じ中身・同じ mode の新しい file に置き換えると scan し直される"
                  " (git hook なら scripts/heal-hook-stubs.sh)")
    return 1 if killed else 0


if __name__ == "__main__":
    sys.exit(main())
