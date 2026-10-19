#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live-engine-paths.py — hook と git の hook が作業 tree から直接読む file (= 書きかけを別の session が走らせる file) の一覧を作る。--selftest 内蔵。

なぜ: settings の hook と、 各 repo の git hook (pre-commit・commit-msg ほか) は、 呼ぶ script を作業 tree の file のまま読む。
その file を Edit で何回にも分けて直すと、 途中の形を同じ機械の別の session が走らせる (実測: 検査の engine を分けて直す途中に、
別の session の commit で検査が異常終了し、 fail-open で素通りした)。 規則 = conventions/hook-authoring.md#live-hook-edit-runs-elsewhere。
この一覧を hook (hooks/live-engine-edit-guard.py) が Edit の前に引く。

何を「読まれている」 とするか (呼び元から辿る、 深さ 4 まで):
  起点 = 各設定 dir の settings.json の hooks の command (lib/claude_config_dirs.py の全設定 dir) と、
         作業ルート (本 repo の親) の直下の各 repo の .git/hooks/{pre-commit, commit-msg, prepare-commit-msg, post-merge, pre-push, post-checkout}
  辿り方 = 呼び元の本文の `*.py` / `*.sh` の語と、 python の `import X` / `from X import` を、 呼び元の dir・その lib/・symlink の先の dir で
           実在する file に解決する (~ と $HOME は展開)。 symlink は実体の path にそろえる。
一覧は ~/.claude/state/live-engine-paths.json に 30 分 cache する (環境変数 LIVE_ENGINE_PATHS_CACHE で場所を変える)。

使い方:
  live-engine-paths.py --list            # 一覧 (path と、 それを呼ぶ file の 1 つ)
  live-engine-paths.py --check <file>    # 読まれていれば呼び元を出して exit 0、 読まれていなければ exit 1
  live-engine-paths.py --selftest
OS: macOS / Linux / Windows (標準 library だけ)。
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
try:
    import claude_config_dirs as _ccd  # noqa: E402
except Exception:  # noqa: BLE001
    _ccd = None

GIT_HOOKS = ("pre-commit", "commit-msg", "prepare-commit-msg", "post-merge", "pre-push", "post-checkout")
CACHE = Path(os.environ.get("LIVE_ENGINE_PATHS_CACHE") or Path.home() / ".claude/state/live-engine-paths.json")
TTL = 1800  # 作り直しは 2 秒弱 (実測 735 file) = Edit の前に毎回は払わない
MAX_DEPTH = 4
MAX_FILES = 3000
_TOKEN = re.compile(r"[A-Za-z0-9_~$./{}-]*?[A-Za-z0-9_-]+\.(?:py|sh)\b")
_IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_]\w*)[\w.]*\s+import|import\s+([A-Za-z_]\w*))", re.M)


def _expand(tok: str) -> str:
    tok = tok.replace("${HOME}", str(Path.home())).replace("$HOME", str(Path.home()))
    return os.path.expanduser(tok)


def _resolve(tok: str, caller: Path) -> list:
    """呼び元の本文の語を、 実在する file の実体の path に。"""
    tok = _expand(tok.strip("'\"`()"))
    cands = []
    p = Path(tok)
    name = tok.split("/")[-1]
    if p.is_absolute():
        cands.append(p)
    for d in {caller.parent, caller.resolve().parent}:
        # `$(dirname "$0")/x.py` は語が `/x.py` で切れる = 呼び元の dir で名前を引く
        cands += [d / name, d / "lib" / name] + ([] if p.is_absolute() else [d / tok])
    out = []
    for c in cands:
        try:
            if c.is_file():
                out.append(c.resolve())
        except OSError:
            pass
    return out


def _refs(path: Path) -> set:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found = set()
    for tok in _TOKEN.findall(text):
        found.update(_resolve(tok, path))
    if path.suffix == ".py":
        for a, b in _IMPORT.findall(text):
            mod = a or b
            for d in {path.parent, path.resolve().parent}:
                for c in (d / f"{mod}.py", d / "lib" / f"{mod}.py"):
                    if c.is_file():
                        found.add(c.resolve())
    return found


def _settings_files() -> list:
    dirs = _ccd.config_dirs() if _ccd else [str(Path.home() / ".claude")]
    return [Path(d) / "settings.json" for d in dirs if (Path(d) / "settings.json").is_file()]


def roots(work_root: Path | None = None, settings=None) -> dict:
    """起点の file → それを呼ぶもの (settings / git hook の名前)。"""
    out = {}
    for s in (settings if settings is not None else _settings_files()):
        try:
            data = json.loads(Path(s).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for groups in (data.get("hooks") or {}).values():
            for g in groups if isinstance(groups, list) else []:
                for h in (g or {}).get("hooks", []):
                    for tok in _TOKEN.findall(str(h.get("command", ""))):
                        for p in _resolve(tok, Path(s)):
                            out.setdefault(p, f"{s} の hook")
    base = work_root or HERE.parent.parent
    for repo in sorted(base.iterdir()) if base.is_dir() else []:
        hooks_dir = repo / ".git" / "hooks"
        for name in GIT_HOOKS:
            h = hooks_dir / name
            if h.is_file():
                out.setdefault(h.resolve(), f"{repo.name} の git hook {name}")
    return out


def build(work_root: Path | None = None, settings=None) -> dict:
    """読まれている file の実体の path → 呼び元 (1 つ)。"""
    live = {str(p): why for p, why in roots(work_root, settings).items()}
    frontier = [Path(p) for p in live]
    for _ in range(MAX_DEPTH):
        nxt = []
        for f in frontier:
            for r in _refs(f):
                if str(r) not in live and len(live) < MAX_FILES:
                    live[str(r)] = str(f)
                    nxt.append(r)
        frontier = nxt
    return live


def load(max_age: int = TTL) -> dict:
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        if time.time() - data.get("built", 0) < max_age:
            return data["live"]
    except (OSError, ValueError, KeyError):
        pass
    live = build()
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_name(CACHE.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"built": time.time(), "live": live}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, CACHE)
    except OSError:
        pass
    return live


def caller_of(path, live=None):
    live = load() if live is None else live
    try:
        real = str(Path(path).expanduser().resolve())
    except OSError:
        return None
    return live.get(real)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if "--selftest" in argv:
        return selftest()
    if "--check" in argv:
        i = argv.index("--check")
        who = caller_of(argv[i + 1]) if i + 1 < len(argv) else None
        if who:
            print(f"読まれている: 呼び元 = {who}")
            return 0
        return 1
    if "--list" in argv:
        live = load(max_age=0)
        for p, why in sorted(live.items()):
            print(f"{p}\t← {why}")
        print(f"live-engine-paths: {len(live)} file", file=sys.stderr)
        return 0
    print(__doc__.splitlines()[0])
    return 2


def selftest() -> int:
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and bool(cond)

    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "work"
        tools = base / "tools" / "scripts"
        (tools / "lib").mkdir(parents=True)
        (tools / "runner.sh").write_text('#!/bin/sh\npython3 "$(dirname "$0")/engine.py" "$@"\n', encoding="utf-8")
        (tools / "engine.py").write_text("import helper\nfrom other import x\n", encoding="utf-8")
        (tools / "lib" / "helper.py").write_text("X = 1\n", encoding="utf-8")
        (tools / "unused.py").write_text("print(1)\n", encoding="utf-8")
        repo = base / "proj"
        (repo / ".git" / "hooks").mkdir(parents=True)
        (repo / ".git" / "hooks" / "pre-commit").write_text(f'#!/bin/sh\nexec "{tools}/runner.sh"\n', encoding="utf-8")
        hookdir = Path(d) / "cfg" / "hooks"
        hookdir.mkdir(parents=True)
        (hookdir / "nudge.py").write_text("print(1)\n", encoding="utf-8")
        settings = Path(d) / "cfg" / "settings.json"
        settings.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": f"{hookdir}/nudge.py"}]}]}}), encoding="utf-8")
        live = build(work_root=base, settings=[settings])
        res = lambda p: str(Path(p).resolve())  # noqa: E731
        expect("git hook → runner → engine → lib の import まで辿る",
               all(res(p) in live for p in (tools / "runner.sh", tools / "engine.py", tools / "lib" / "helper.py")))
        expect("settings の hook の command の file を起点にする", res(hookdir / "nudge.py") in live)
        expect("どこからも呼ばれない file は入れない", res(tools / "unused.py") not in live)
        expect("呼び元を 1 つ返す", "runner.sh" in live[res(tools / "engine.py")])
    print("live-engine-paths selftest:", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
