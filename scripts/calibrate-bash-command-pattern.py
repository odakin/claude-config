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
--with-cwd = 述語が作業 dir に依るとき (find_issues(command, cwd) の形)。 各呼び出しの時点の作業 dir を、 session の始めの
  dir から前の `cd` / `pushd` (呼び出しが成功したとき) と結果の「Shell cwd was reset to X」 を順に当てて作り直して渡す。
  ⚠️ 会話記録の各行の `cwd` 欄は使わない = 直前の単独の cd の分だけ遅れて書かれる (実測)。 hook に届く入力の cwd は単独の
  cd の直後の呼び出しから新しい (実測) ので、 遅れた欄で校正すると「単独の cd → 次の呼び出しで git」 を誤検出に数える。
  再開・文脈圧縮をまたぐと作り直しも外れる = hit ごとに呼び出しの結果 (成功か・出力の頭) を出すので、 作業 dir と矛盾する
  結果 (例 = 作業ルートのはずの `git add` が commit まで通った) は作り直しの外れとして数えない。 同じ command は作業 dir ごとに数える。
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


def _last_cd(cmd: str, cur: str | None, home: str) -> str | None:
    """command の中の最後の cd / pushd の行き先 (無ければ cur)。 読めない行き先は None。 quote の中・heredoc の本文の
    `cd` も拾いうる近似 (校正の作業 dir の作り直し用)。"""
    out = cur
    for m in re.finditer(r"(?:^|[;&|(\n]\s*)(?:cd|pushd)(?:\s+([^\s;&|)]+))?", cmd):
        t = m.group(1)
        if t is None:
            out = home
            continue
        t = t.strip("\"'")
        if t in ("~", "$HOME", "${HOME}"):
            out = home
            continue
        for pre in ("~/", "$HOME/", "${HOME}/"):
            if t.startswith(pre):
                t = os.path.join(home, t[len(pre):])
                break
        if "$" in t or "`" in t or t == "-" or (not os.path.isabs(t) and out is None):
            out = None
            continue
        out = os.path.normpath(t if os.path.isabs(t) else os.path.join(out, t))
    return out


def bash_calls_with_cwd(entries, home: str | None = None):
    """→ [(command, 呼び出しの時点の作業 dir, 結果の印 'ok' / 'error' / '', 出力の頭)]。 作り直し方 = 上の docstring の --with-cwd。"""
    home = home or os.path.expanduser("~")
    cur, started, calls, pending = None, False, [], {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        a = e.get("attachment") or {}
        if not started and isinstance(a, dict) and a.get("type") == "environment":
            cur = (a.get("snapshot") or {}).get("workingDirectory") or cur
            started = cur is not None
        if not started and e.get("cwd"):
            cur, started = e.get("cwd"), True  # 最初の 1 回だけ = session の始めの dir (以後の欄は遅れるので使わない)
        m = e.get("message")
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmd = (b.get("input") or {}).get("command")
                if isinstance(cmd, str) and cmd:
                    pending[b.get("id")] = len(calls)
                    calls.append([cmd, cur, "", ""])
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                i = pending.pop(b.get("tool_use_id"))
                c = b.get("content")
                txt = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                calls[i][2] = "error" if b.get("is_error") else "ok"
                calls[i][3] = txt[:80].replace("\n", " ")
                if "Shell cwd was reset to " in txt:
                    cur = txt.split("Shell cwd was reset to ", 1)[1].split('"', 1)[0].split("\\n", 1)[0].split("\n", 1)[0].strip()
                elif not b.get("is_error"):
                    cur = _last_cd(calls[i][0], calls[i][1], home)
    return [tuple(c) for c in calls]


def load_detector(hook: str | None = None, pattern: str | None = None, func: str = "find_issues",
                  with_cwd: bool = False):
    """command → 検出の list (空 = 問題なし) を返す関数。 hook は module level の func を呼ぶ。"""
    if hook:
        src = Path(hook).read_text(encoding="utf-8")
        ns: dict = {"__name__": "guard_under_test", "__file__": hook}
        exec(compile(src, hook, "exec"), ns)
        fn = ns.get(func)
        if not callable(fn):
            raise SystemExit(f"{hook}: module level に {func}(command) が無い")
        if with_cwd:
            return lambda c, cwd: list(fn(c, cwd or "") or [])
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


def scan_with_cwd(files, detect, home: str | None = None):
    """→ (Bash command 数, (command, 作業 dir) の重複を除いた数, [(session8, 検出, command, 作業 dir, 結果, 出力の頭)])"""
    seen: set = set()
    n_cmd = 0
    hits = []
    for fp in files:
        try:
            entries = load_entries(fp)
        except OSError:
            continue
        sid = Path(fp).stem[:8]
        for cmd, cwd, res, head in bash_calls_with_cwd(entries, home):
            n_cmd += 1
            if (cmd, cwd) in seen:
                continue
            seen.add((cmd, cwd))
            found = detect(cmd, cwd)
            if found:
                hits.append((sid, found, cmd, cwd, res, head))
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
        # --with-cwd: 作業 dir を前の cd と「Shell cwd was reset」 から作り直す (行の cwd 欄は最初の 1 回だけ使う)
        def tuid(cmd, i):
            return {"type": "assistant", "cwd": "/w", "message": {"content": [
                {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": cmd}}]}}

        def tr(i, text, err=False):
            return {"type": "user", "cwd": "/w", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": text, "is_error": err}]}}
        rows2 = [{"type": "attachment", "attachment": {"type": "environment", "snapshot": {"workingDirectory": "/w"}}},
                 tuid("cd sub", 1), tr(1, ""), tuid("git add x", 2), tr(2, ""),
                 tuid("cd /tmp/x", 3), tr(3, "Shell cwd was reset to /w"), tuid("git add y", 4), tr(4, "fatal: x", True),
                 tuid("cd \"$X\"", 5), tr(5, ""), tuid("git add z", 6), tr(6, "")]
        tp2 = Path(d) / "cwd12345678.jsonl"
        tp2.write_text("\n".join(json.dumps(r) for r in rows2) + "\n", encoding="utf-8")
        seen_cwd = {c[0]: c[1] for c in bash_calls_with_cwd(load_entries(str(tp2)), home="/h")}
        check(seen_cwd.get("git add x") == "/w/sub", f"単独の cd の後の呼び出しは cd の行き先 ({seen_cwd.get('git add x')})")
        check(seen_cwd.get("git add y") == "/w", "「Shell cwd was reset to X」 の後は X (行の cwd 欄の遅れに依らない)")
        check(seen_cwd.get("git add z") is None, "行き先が読めない cd の後は作業 dir 不明 (None)")
        cg = Path(d) / "cg.py"
        cg.write_text("def find_issues(c, cwd):\n    return ['root'] if c.startswith('git add') and cwd == '/w' else []\n",
                      encoding="utf-8")
        n2, u2, hits2 = scan_with_cwd([str(tp2)], load_detector(hook=str(cg), with_cwd=True), home="/h")
        check(n2 == 6 and len(hits2) == 1 and hits2[0][2] == "git add y" and hits2[0][4] == "error",
              f"--with-cwd: 述語に作業 dir を渡し、 hit に結果の印を付ける (hits={[(h[2], h[3], h[4]) for h in hits2]})")
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
    ap.add_argument("--with-cwd", action="store_true",
                    help="述語を find_issues(command, cwd) で呼ぶ。 作業 dir は前の cd と「Shell cwd was reset」 から作り直す")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.hook or a.pattern):
        ap.error("--hook か --pattern が要る")
    files = sorted(transcript_paths(a.glob), key=os.path.getmtime, reverse=True)
    if a.files:
        files = files[:a.files]
    if a.with_cwd:
        if not a.hook:
            ap.error("--with-cwd は --hook と一緒に使う")
        n, u, hits = scan_with_cwd(files, load_detector(a.hook, None, a.func, with_cwd=True))
        ok = sum(1 for h in hits if h[4] == "ok")
        print(f"files {len(files)} / Bash command {n} (command と作業 dir の組で重複を除く {u}) / hit {len(hits)}"
              f" (うち呼び出しが成功 {ok} = 作業 dir と矛盾する結果なら作り直しの外れ。 1 件ずつ読む)")
        print(PUBLIC_SHAPE_NOTE)
        for sid, found, cmd, cwd, res, head in hits[:a.samples]:
            print(f"--- {sid} {found}  cwd={cwd}  結果={res or '?'}: {head}")
            print(f"    {_snippet(cmd, found)}")
        if len(hits) > a.samples:
            print(f"... 他 {len(hits) - a.samples} 件 (--samples で増やす)")
        return 0
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
