#!/usr/bin/env python3
"""calibrate-bash-command-pattern.py — Bash の command を見る PreToolUse guard の述語を、 過去の transcript の Bash tool 呼び出しに当てて検出数と例を出す（導入前の誤検出の見積もり用。 --hook で hook file の find_issues(command) をそのまま使う、 --selftest。 conventions/hook-authoring.md#command-guard-calibration）

使い方:
  calibrate-bash-command-pattern.py --hook hooks/zsh-word-split-guard.py [--glob '<dir>/*/*.jsonl']
      [--files N] [--samples 30]
  calibrate-bash-command-pattern.py --pattern 'REGEX' [...]
--hook の file は find_issues(command: str) -> list (空 = 問題なし) を module level に持つこと。
  1 つの hook が述語を複数持つときは --func <名前> でそれを呼ぶ (同じ型: command → list)。
  例 = calibrate-bash-command-pattern.py --hook hooks/zsh-word-split-guard.py --func log_issues (素の log show の述語)
  読み込みは source を読んで exec する (= importlib の .pyc cache を経由しない。 古い述語を掴まないため)。
--pattern は re.search で 1 件でも当たれば hit。
読む transcript の既定 = この機械の全部の設定フォルダの projects/*/*.jsonl (~/.claude と、 アカウント固定の
  ~/.claude-<名> = スマホから始めた session・無人 routine、 と $CLAUDE_CONFIG_DIR。 lib/claude_config_dirs.py)。
  hook はどの設定フォルダの session でも走るので、 誤検出の見積もりも全部で取る。 --glob を渡すとその glob だけ。
出力: 読んだ file 数 / Bash command 数 (同じ文字列を除いた数) / hit した command 数と、 hit ごとに
  session id の先頭 8 桁・検出内容・前後の文脈。 同じ command 文字列は 1 回だけ数える (= 再試行の重複を除く)。
  誤検出かどうかは人が読んで数える (= 述語の一致は意図を識別しない)。
⚠️ transcript は local の private data。 出力 (command の抜粋) を公開の場所に貼らない。 件数 (母数・hit) も
  本人の会話記録から数えた活動の量 = 公開 repo の commit message・本文には形 (誤検出の数・道具・読んだ範囲) だけを
  書く (conventions/hook-authoring.md#new-hook-protected-bundle の 2。 出力の 2 行目にも出す = 数字を写す瞬間に読む)。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from transcript_turns import load_entries  # noqa: E402

try:
    import claude_config_dirs as _ccd  # noqa: E402
except Exception:  # pragma: no cover - 古い配置
    _ccd = None

LEGACY_GLOB = "~/.claude/projects/*/*.jsonl"
PUBLIC_SHAPE_NOTE = ("⚠️ 上の件数 (母数・hit) は本人の会話記録から数えた活動の量 = 公開 repo の commit message・本文には書かない。 "
                     "書くのは誤検出の数・道具・読んだ範囲だけ (conventions/hook-authoring.md#new-hook-protected-bundle の 2)")


def transcript_paths(pattern: str | None) -> list[str]:
    """--glob があればその glob、 無ければ全部の設定フォルダ。"""
    if _ccd is not None:
        return _ccd.transcript_paths(pattern)
    return glob.glob(os.path.expanduser(pattern or LEGACY_GLOB))


def bash_commands(entries):
    """transcript の entry 列から Bash tool_use の command 文字列を順に返す。"""
    for e in entries:
        m = e.get("message") if isinstance(e, dict) else None
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmd = (b.get("input") or {}).get("command")
                if isinstance(cmd, str) and cmd:
                    yield cmd


def load_detector(hook: str | None = None, pattern: str | None = None, func: str = "find_issues"):
    """command → 検出の list (空 = 問題なし) を返す関数。 hook は module level の func を呼ぶ。"""
    if hook:
        src = Path(hook).read_text(encoding="utf-8")
        ns: dict = {"__name__": "guard_under_test", "__file__": hook}
        exec(compile(src, hook, "exec"), ns)
        fn = ns.get(func)
        if not callable(fn):
            raise SystemExit(f"{hook}: module level に {func}(command) が無い")
        return lambda c: list(fn(c) or [])
    rx = re.compile(pattern or "")
    return lambda c: [m.group(0) for m in [rx.search(c)] if m]


def _snippet(cmd: str, found) -> str:
    key = ""
    first = found[0] if found else ""
    if isinstance(first, (tuple, list)) and first:
        key = str(first[0])
    elif isinstance(first, str):
        key = first
    i = -1
    for k in (f"${key}", f"${{{key}}}", key):
        if k:
            i = cmd.find(k)
            if i >= 0:
                break
    i = max(i, 0)
    return cmd[max(0, i - 120):i + 80].replace("\n", " ⏎ ")


def scan(files, detect):
    """→ (Bash command 数, 重複を除いた数, [(session8, 検出, command)])"""
    seen: set[str] = set()
    n_cmd = 0
    hits = []
    for fp in files:
        try:
            entries = load_entries(fp)
        except OSError:
            continue
        sid = Path(fp).stem[:8]
        for cmd in bash_commands(entries):
            n_cmd += 1
            if cmd in seen:
                continue
            seen.add(cmd)
            found = detect(cmd)
            if found:
                hits.append((sid, found, cmd))
    return n_cmd, len(seen), hits


def selftest() -> int:
    fails = 0

    def check(cond, msg):
        nonlocal fails
        print(("  ok   " if cond else "  FAIL ") + msg)
        fails += 0 if cond else 1

    with tempfile.TemporaryDirectory() as d:
        def tu(cmd):
            return {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}}
        rows = [tu("for x in $v; do :; done"), tu("ls"), tu("for x in $v; do :; done"),
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}]}},
                {"type": "user", "message": {"content": "hi"}}]
        tp = Path(d) / "abcdef1234.jsonl"
        tp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        guard = Path(d) / "g.py"
        guard.write_text("def find_issues(c):\n    return [('v', 'for')] if '$v' in c else []\n", encoding="utf-8")
        n, u, hits = scan([str(tp)], load_detector(hook=str(guard)))
        check(n == 3 and u == 2, f"Bash だけを数え、 同じ文字列は 1 回 (n={n} unique={u})")
        check(len(hits) == 1 and hits[0][0] == "abcdef12", "--hook の find_issues で hit + session id 8 桁")
        check("$v" in _snippet(hits[0][2], hits[0][1]), "文脈は検出した変数の周り")
        n, u, hits = scan([str(tp)], load_detector(pattern=r"^ls$"))
        check(len(hits) == 1, "--pattern (re.search)")
        bad = Path(d) / "bad.py"
        bad.write_text("x = 1\n", encoding="utf-8")
        try:
            load_detector(hook=str(bad))
            check(False, "find_issues の無い hook は止める")
        except SystemExit:
            check(True, "find_issues の無い hook は止める")
        two = Path(d) / "two.py"
        two.write_text("def find_issues(c):\n    return []\n\ndef log_issues(c):\n    return ['ls'] if c == 'ls' else []\n",
                       encoding="utf-8")
        n, u, hits = scan([str(tp)], load_detector(hook=str(two), func="log_issues"))
        check(len(hits) == 1 and hits[0][1] == ["ls"], "--func で同じ hook の別の述語を呼ぶ")
        try:
            load_detector(hook=str(two), func="nope")
            check(False, "--func の名前が無い hook は止める")
        except SystemExit:
            check(True, "--func の名前が無い hook は止める")
        if _ccd is not None:  # 既定 = 全部の設定フォルダ (偽の HOME に既定とアカウント固定の 2 つ)
            for cfg in (".claude", ".claude-alt"):
                pd = Path(d) / "home" / cfg / "projects" / "-w"
                pd.mkdir(parents=True)
                (pd / f"{cfg.strip('.')}.jsonl").write_text(tp.read_text(encoding="utf-8"), encoding="utf-8")
            saved = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIRS_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECTS_DIR")}
            try:
                for k in saved:
                    os.environ.pop(k, None)
                os.environ["CLAUDE_CONFIG_DIRS_HOME"] = str(Path(d) / "home")
                got = sorted(Path(p).name for p in transcript_paths(None))
                one = transcript_paths(str(Path(d) / "home" / ".claude-alt" / "projects" / "*" / "*.jsonl"))
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            check(got == ["claude-alt.jsonl", "claude.jsonl"], f"既定 = 全部の設定フォルダの transcript ({got})")
            check([Path(p).name for p in one] == ["claude-alt.jsonl"], "--glob を渡すとその glob だけ")
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--hook", help="find_issues(command) を持つ hook file")
    g.add_argument("--pattern", help="re.search の正規表現")
    ap.add_argument("--func", default="find_issues", help="--hook で呼ぶ述語の名前 (既定 = find_issues)")
    ap.add_argument("--glob", default=None, help="transcript の glob (既定 = この機械の全部の設定フォルダの projects/*/*.jsonl)")
    ap.add_argument("--files", type=int, default=0, help="新しい順に N file だけ (0 = 全部)")
    ap.add_argument("--samples", type=int, default=30)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.hook or a.pattern):
        ap.error("--hook か --pattern が要る")
    files = sorted(transcript_paths(a.glob), key=os.path.getmtime, reverse=True)
    if a.files:
        files = files[:a.files]
    n, u, hits = scan(files, load_detector(a.hook, a.pattern, a.func))
    print(f"files {len(files)} / Bash command {n} (同じ文字列を除く {u}) / hit {len(hits)}")
    print(PUBLIC_SHAPE_NOTE)
    for sid, found, cmd in hits[:a.samples]:
        print(f"--- {sid} {found}")
        print(f"    {_snippet(cmd, found)}")
    if len(hits) > a.samples:
        print(f"... 他 {len(hits) - a.samples} 件 (--samples で増やす)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
