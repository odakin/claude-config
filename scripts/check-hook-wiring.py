#!/usr/bin/env python3
"""check-hook-wiring.py — hook の dir の hook のうち、 配線の台帳にも Claude Code の設定にも載っていないもの (= 一度も走らない hook) を数えて出す

なぜ: hook は file を作っただけでは走らない。 台帳 (層1 = hooks/settings-entries.json を setup.sh が設定に写す / 個人層 =
  その層の台帳を個人層の installer が写す) に 1 行足すまでが配線で、 その 1 行を落とすと hook は黙って一度も走らない。
  実測: 作られたまま台帳に載らず、 一度も走らなかった Stop hook があった。 設定に手で書いただけの hook も、 新しい
  機械や設定の作り直しで黙って消える (同じ棚卸しで見つかった)。 作った側は「在る」 と
  思っているので、 人の目では見つからない = 定期の点検で数える。

数え方:
  - hook = 各 --pair の dir の直下の `*.sh` / `*.py` のうち git に登録された file (git の外の dir なら全部)。
    `*.test.sh` / `*.test.py`・`lib-*` / `lib_*`・`install.sh`・`_` か `test-` で始まる file は hook でない。
  - 載っている = その file の名前が、 どれかの台帳 (各 --pair の json) か設定 (--settings) の `command` に出てくる。
  - 台帳に無く設定にだけ載っている hook は別に出す (今は走るが、 新しい機械では配線されない)。
  - 載っていなくてよい hook は、 冒頭 40 行に次の印を 1 行書く (印の形の正本 = この docstring):
      hook-wiring: deferred — <配線しない理由>          (わざと配線しない。 個人層の installer の旧い印
                                                         「DEFERRED」 + 「配線しない」/「do not wire」 も同じに読む)
      hook-wiring: part — 呼び手 = <呼ぶ hook・道具・launchd の label>   (同じ組の dir の別の hook・その repo の道具・
                                                         launchd から呼ばれる部品)
      hook-wiring: engine — 呼び手 = <利用者の層の shim>   (利用者の層の shim が config を渡して呼ぶ engine。 呼び手は
                                                         この repo の外に在るので確かめない)
    part の印は、 その file の名前 (拡張子を除いた名前でもよい) がどれかの --pair の dir か、 その dir の親の repo の
    scripts/ の別の file に出てくることも確かめる (呼び手の居ない部品 = 印だけ残った死んだ hook を見逃さない)。
既存の hook の点検 (scripts/audit-hooks.sh) との分担: あちらはこの機械の ~/.claude/hooks と settings.json の食い違い
  (台帳にはあるが設定に写っていない hook など) を見る。 こちらは台帳 (setup が設定に写す元) を見るので、 どの機械でも
  走らない hook と、 設定にだけ手で書かれた hook (新しい機械で消える) を拾う。
使い方:
  check-hook-wiring.py                                 この repo の hooks/ と hooks/settings-entries.json、 設定 = ~/.claude/settings.json と ~/.claude-*/settings.json
  check-hook-wiring.py --pair <dir>=<json> ...         台帳の組を足す (最初の --pair で既定の組を置き換える。 既定の組も残すなら明示する)
  check-hook-wiring.py --settings <file> ...           設定を明示する (既定を置き換える)。 --no-settings = 設定を見ない (台帳だけで数える)
  --json / --quiet (載っていない hook が無ければ何も出さない) / --selftest
終了値: 0 = 印の無い載っていない hook も呼び手の居ない部品も無い / 1 = ある / 2 = 引数の誤り。
置き場 = 層1: 層1 の hook の配線の正本は層1 の台帳で、 台帳に載らない hook は層1 だけでも起きる (利用者の層は自分の組を
  --pair で渡す。 例 = 個人層の定期点検が層1 と個人層の 2 組を渡す)。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
HEAD_LINES = 40
MARK = re.compile(r"hook-wiring:\s*(deferred|part|engine)\b(.*)", re.I)
NAME = re.compile(r"[\w.\-]+\.(?:sh|py)")


def is_hook_name(b: str) -> bool:
    if not re.search(r"\.(sh|py)$", b):
        return False
    if re.search(r"\.test\.(sh|py)$", b) or b == "install.sh":
        return False
    return not (b.startswith(("lib-", "lib_", "_", "test-")))


def hook_files(d: str) -> list[str]:
    """dir の直下の hook (git に登録された file。 git の外なら全部)。"""
    try:
        r = subprocess.run(["git", "-C", d, "ls-files", "--", "."], capture_output=True, text=True, timeout=20)
        names = [n for n in r.stdout.splitlines() if "/" not in n] if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        names = None
    if names is None:
        names = [os.path.basename(p) for p in glob.glob(os.path.join(d, "*")) if os.path.isfile(p)]
    return sorted(os.path.join(d, n) for n in names if is_hook_name(n) and os.path.isfile(os.path.join(d, n)))


def commands(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return set()
    out: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            c = x.get("command")
            if isinstance(c, str):
                out.add(c)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(d)
    return out


def names_in(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for p in paths:
        for c in commands(p):
            out |= {os.path.basename(t) for t in NAME.findall(c)}
    return out


def marker(path: str) -> tuple[str, str] | None:
    """冒頭の印 → (kind, 残りの文)。 個人層の installer の旧い印 (DEFERRED + 配線しない) は deferred。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = [next(fh, "") for _ in range(HEAD_LINES)]
    except OSError:
        return None
    for line in head:
        m = MARK.search(line)
        if m:
            return m.group(1).lower(), m.group(2).strip(" —-:")
    text = "".join(head[:20])
    if "DEFERRED" in text and ("配線しない" in text or "do not wire" in text):
        return "deferred", "DEFERRED (旧い印)"
    return None


def caller_found(path: str, dirs: list[str]) -> bool:
    """part の file の名前が、 hook の dir か、 その親の repo の scripts/ の別の file に出てくるか。"""
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    pat = re.compile(r"(?<![\w.\-])" + re.escape(stem) + r"(?:\.(?:sh|py))?(?![\w\-])")
    seen: set[str] = set()
    pools = []
    for d in dirs:
        pools.append(glob.glob(os.path.join(d, "*")))
        pools.append(glob.glob(os.path.join(os.path.dirname(d), "scripts", "**", "*"), recursive=True))
    for pool in pools:
        for p in pool:
            rp = os.path.realpath(p)
            if rp in seen or rp == os.path.realpath(path) or not os.path.isfile(p):
                continue
            seen.add(rp)
            b = os.path.basename(p)
            if re.search(r"\.test\.(sh|py)$", b) or b.endswith((".md", ".json", ".txt")):
                continue
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    if pat.search(fh.read()):
                        return True
            except OSError:
                continue
    return False


def audit(pairs: list[tuple[str, str]], settings: list[str]) -> dict:
    ledger_names = names_in([j for _, j in pairs])
    setting_names = names_in(settings)
    dirs = [d for d, _ in pairs]
    res = {"hooks": 0, "unwired": [], "settings_only": [], "deferred": [], "part": [], "orphan_part": [], "engine": []}
    for d in dirs:
        for f in hook_files(d):
            res["hooks"] += 1
            b = os.path.basename(f)
            if b in ledger_names:
                continue
            if b in setting_names:
                res["settings_only"].append(f)
                continue
            mk = marker(f)
            if mk and mk[0] == "deferred":
                res["deferred"].append((f, mk[1]))
            elif mk and mk[0] == "engine":
                res["engine"].append((f, mk[1]))
            elif mk and mk[0] == "part":
                (res["part"] if caller_found(f, dirs) else res["orphan_part"]).append((f, mk[1]))
            else:
                res["unwired"].append(f)
    return res


def default_settings() -> list[str]:
    home = os.path.expanduser("~")
    cands = [os.path.join(home, ".claude", "settings.json")] + sorted(glob.glob(os.path.join(home, ".claude-*", "settings.json")))
    return [p for p in cands if os.path.isfile(p)]


def _rel(p: str) -> str:
    base = os.path.dirname(REPO)
    return os.path.relpath(p, base) if p.startswith(base + os.sep) else p


def report(res: dict, quiet: bool) -> str:
    bad = res["unwired"] or res["orphan_part"]
    if quiet and not bad and not res["settings_only"]:
        return ""
    n = sum(len(res[k]) for k in ("unwired", "orphan_part", "settings_only", "deferred", "part", "engine"))
    lines = [f"hook {res['hooks']} 本のうち、 台帳に載っていない {n} 本 "
             f"(印の無いもの {len(res['unwired'])}・呼び手の居ない部品 {len(res['orphan_part'])}・設定にだけ在る {len(res['settings_only'])}・"
             f"部品 {len(res['part'])}・別の層の shim が呼ぶ engine {len(res['engine'])}・配線しない {len(res['deferred'])})"]
    for f in res["unwired"]:
        lines.append(f"  🔴 配線されていない: {_rel(f)} = 台帳に足す (層1 = hooks/settings-entries.json、 個人層 = その層の台帳) か、 "
                     "部品・わざと外したものなら冒頭に `hook-wiring: part — 呼び手 = …` / `hook-wiring: deferred — 理由` を書く。 "
                     "使わなくなった hook なら消して退役の一覧に名前を書く")
    for f, why in res["orphan_part"]:
        lines.append(f"  🔴 呼び手の居ない部品: {_rel(f)} ({why}) = 呼び手が名前を持っていない。 呼び手を確かめ、 居なければ配線するか退役させる")
    for f in res["settings_only"]:
        lines.append(f"  🟠 設定にだけ在る: {_rel(f)} = 台帳に無いので、 新しい機械や設定の作り直しでは配線されない。 台帳に足す")
    if not quiet:
        for f, why in res["part"]:
            lines.append(f"  ・ 部品: {_rel(f)} ({why})")
        for f, why in res["engine"]:
            lines.append(f"  ・ engine: {_rel(f)} ({why})")
        for f, why in res["deferred"]:
            lines.append(f"  ・ 配線しない: {_rel(f)} ({why})")
    return "\n".join(lines)


def parse_pairs(vals: list[str] | None) -> list[tuple[str, str]]:
    if not vals:
        return [(os.path.join(REPO, "hooks"), os.path.join(REPO, "hooks", "settings-entries.json"))]
    out = []
    for v in vals:
        if "=" not in v:
            raise ValueError(f"--pair は <dir>=<json> の形: {v}")
        d, j = v.split("=", 1)
        out.append((os.path.expanduser(d), os.path.expanduser(j)))
    return out


def selftest() -> int:
    fails = 0

    def check(name: str, ok: bool):
        nonlocal fails
        print(("ok   " if ok else "FAIL ") + name)
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as t:
        repo = os.path.join(t, "repo")
        hd = os.path.join(repo, "hooks")
        os.makedirs(os.path.join(repo, "scripts"))
        os.makedirs(hd)

        def put(name: str, body: str, where: str = hd):
            with open(os.path.join(where, name), "w", encoding="utf-8") as fh:
                fh.write(body)
        put("wired.sh", "#!/bin/sh\n")
        put("forgot.py", "#!/usr/bin/env python3\n\"\"\"forgot.py — 作ったまま\"\"\"\n")
        put("deferred-new.sh", "#!/bin/sh\n# hook-wiring: deferred — 観察だけ\n")
        put("deferred-old.sh", "#!/bin/sh\n# DEFERRED — 配線しない (観察期)\n")
        put("part.py", "#!/usr/bin/env python3\n# hook-wiring: part — 呼び手 = hooks/wrapper.sh\n")
        put("wrapper.sh", "#!/bin/sh\nexec python3 \"$(dirname \"$0\")/part.py\"\n")
        put("ghost.py", "#!/usr/bin/env python3\n# hook-wiring: part — 呼び手 = 消えた道具\n")
        put("launchd-part.sh", "#!/bin/sh\n# hook-wiring: part — 呼び手 = launchd\n")
        put("install-launchd.sh", "#!/bin/sh\necho ~/.claude/hooks/launchd-part.sh\n", os.path.join(repo, "scripts"))
        put("manual.sh", "#!/bin/sh\n")
        put("engine.sh", "#!/bin/sh\n# hook-wiring: engine — 呼び手 = 利用者の層の shim\n")
        put("lib-x.sh", "#!/bin/sh\n")
        put("wired.test.sh", "#!/bin/sh\n")
        put("install.sh", "#!/bin/sh\n")
        put("README.md", "forgot.py ghost.py\n")
        led = os.path.join(hd, "settings-entries.json")
        with open(led, "w") as fh:
            json.dump({"Stop": [{"hooks": [{"type": "command", "command": "~/.claude/hooks/wired.sh"},
                                           {"type": "command", "command": "~/.claude/hooks/wrapper.sh --x"}]}]}, fh)
        st = os.path.join(t, "settings.json")
        with open(st, "w") as fh:
            json.dump({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/manual.sh"}]}]}}, fh)
        res = audit([(hd, led)], [st])
        names = lambda xs: sorted(os.path.basename(x if isinstance(x, str) else x[0]) for x in xs)  # noqa: E731
        check("hook を数える (test・lib・install.sh は数えない)", res["hooks"] == 10)
        check("別の層の shim が呼ぶ engine は呼び手を確かめずに外す", names(res["engine"]) == ["engine.sh"])
        check("印の無い載っていない hook を出す", names(res["unwired"]) == ["forgot.py"])
        check("新しい印と旧い印の「配線しない」 を外す", names(res["deferred"]) == ["deferred-new.sh", "deferred-old.sh"])
        check("呼び手の居る部品を外す (hook の dir の呼び手・repo の scripts/ の呼び手)", names(res["part"]) == ["launchd-part.sh", "part.py"])
        check("呼び手の居ない部品を出す (README の言及は呼び手に数えない)", names(res["orphan_part"]) == ["ghost.py"])
        check("設定にだけ在る hook を別に出す", names(res["settings_only"]) == ["manual.sh"])
        txt = report(res, quiet=False)
        check("報告に件数と直し方が出る", "印の無いもの 1" in txt and "forgot.py" in txt and "hook-wiring: deferred" in txt)
        check("--no-settings 相当 (設定を見ない) では設定にだけ在る hook も配線されていない側", "manual.sh" in names(audit([(hd, led)], [])["unwired"]))
        # git の中では登録された file だけを数える (作業中の未登録の hook は数えない)
        ok_git = subprocess.run(["git", "init", "-q", repo], capture_output=True).returncode == 0
        if ok_git:
            subprocess.run(["git", "-C", repo, "add", "hooks/wired.sh", "hooks/forgot.py", "hooks/settings-entries.json"],
                           capture_output=True)
            res2 = audit([(hd, led)], [st])
            check("git の中では登録された file だけ (未登録の作業中の hook は数えない)",
                  res2["hooks"] == 2 and names(res2["unwired"]) == ["forgot.py"])
        # 終了値
        rc = main(["--pair", f"{hd}={led}", "--settings", st, "--quiet"])
        check("印の無い hook があれば終了値 1", rc == 1)
        os.remove(os.path.join(hd, "forgot.py"))
        os.remove(os.path.join(hd, "ghost.py"))
        if ok_git:
            subprocess.run(["git", "-C", repo, "rm", "-q", "--cached", "hooks/forgot.py"], capture_output=True)
        rc = main(["--pair", f"{hd}={led}", "--settings", st, "--quiet"])
        check("無ければ終了値 0", rc == 0)
    print(f"{'PASS' if fails == 0 else 'FAIL'} ({fails} fail)")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pair", action="append")
    ap.add_argument("--settings", action="append")
    ap.add_argument("--no-settings", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    try:
        pairs = parse_pairs(a.pair)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    settings = [] if a.no_settings else ([os.path.expanduser(s) for s in a.settings] if a.settings else default_settings())
    res = audit(pairs, settings)
    if a.json:
        print(json.dumps({k: ([x if isinstance(x, str) else list(x) for x in v] if isinstance(v, list) else v)
                          for k, v in res.items()}, ensure_ascii=False, indent=1))
    else:
        txt = report(res, a.quiet)
        if txt:
            print(txt)
    return 1 if (res["unwired"] or res["orphan_part"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
