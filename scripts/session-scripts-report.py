#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session-scripts-report.py — ある session がその場で書いた script を会話記録から全部並べ、 file として残っているか (commit 済みか) を出す。--selftest 内蔵。

用途: 締めの sweep (conventions/closing-sweep.md#collect-from-transcript) で、 その場で書いた script を取りこぼさないため。
context から思い出すと、 file に残らない形 (heredoc で interpreter に流した code・`-c` / `-e` の code) を数え落とす
(実測: 締めで file の script だけを数え、 結果を記録の根拠に使った heredoc の Python を落とした)。 agent が書いた
script は subagent-reports.py、 headless の worker の script は headless-worker-reports.py が出す = 本 script は session 本体の分。

拾うもの (session 本体の記録 <projects-dir>/<project>/<session id>.jsonl の道具の呼び出し):
  1. file に書いた script — Write / Edit / MultiEdit / NotebookEdit の path と、 Bash の `cat > path <<EOF` / `tee path <<EOF`
     のうち、 拡張子が script のもの (SCRIPT_EXT) か本文が shebang で始まるもの
  2. その場で流した code — Bash の `<interpreter> [opts] [-] <<EOF` (stdin に流す heredoc) と `<interpreter> -c '…'` / `-e '…'`
     (interpreter = python/python3/py/tools/py 型の wrapper・node・ruby・perl・Rscript・julia・wolframscript・bash/sh/zsh)。
     MIN_LINES 行未満の短いもの (1 行の確かめ) は数えない。 拾った code が失敗した実行なら印を付ける。

判定:
  1 の file → ✅ commit 済み (作業ツリーとの差なし) / 🟡 repo の中だが未 commit・未追跡 / ⚠️ repo の外 (一時 dir・scratchpad) / ❌ もう無い
  2 の code → 特徴的な行 (長い行から最大 4 本) を、 session が触った repo (記録の path から導く。 --all-repos で作業ルートの全部) の
     追跡済み file から `git grep -F` で探す。 半分以上が同じ file にあれば ✅ (その file)、 1 本だけなら 🔸 一部一致 (書き直した版か)、
     無ければ ⚠️ 未保存。
  ⚠️ のものは 1 本ずつ決める (closing-sweep.md#placement の script の行): 出力を記録・note・規約の根拠に使ったなら、 その記録の
  隣に file として残す (1 回きりでも)。 根拠に使っていないなら置かず、 報告に「置かない」 と理由を書く。

使い方:
  session-scripts-report.py <session id か先頭の数文字>     # 既定は環境変数 CLAUDE_CODE_SESSION_ID
  session-scripts-report.py abcd1234 --all-repos            # 作業ルート (--root、 既定 ~/Claude) の全 repo で探す
  session-scripts-report.py abcd1234 --json
  session-scripts-report.py abcd1234 --strict               # ⚠️ / ❌ / 🟡 が 1 件でもあれば exit 1
  session-scripts-report.py --selftest

projects-dir の既定 = この機械の全部の設定 dir の projects/ (lib/claude_config_dirs.py)。 0 件なら見た dir を出す。

OS: macOS / Linux / Windows (Git Bash・PowerShell) で同じに動く (標準 library + git、 Python 3.8+、 出力は UTF-8)。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import claude_config_dirs as _ccd
except Exception:  # pragma: no cover - 古い配置
    _ccd = None

SCRIPT_EXT = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ".rb", ".pl", ".r", ".jl",
              ".wl", ".wls", ".m", ".nb", ".ipynb", ".lua", ".tcl", ".awk", ".sed", ".applescript", ".scpt"}
FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
MIN_LINES = 5
INTERP = r"(?:[\w./~-]*/)?(?:python(?:3(?:\.\d+)?)?|py|node|ruby|perl|Rscript|julia|wolframscript|bash|sh|zsh)"
# <interp> [opts] [-] <<'EOF'\n body \nEOF
HEREDOC_RE = re.compile(
    r"(?:^|[\s;&|(])(" + INTERP + r")(\s[^\n;&|<>]*?)?<<-?\s*(['\"]?)(\w+)\3[^\n]*\n(.*?)\n\s*\4\s*(?:\n|$)",
    re.S)
DASH_C_RE = re.compile(r"(?:^|[\s;&|(])(" + INTERP + r")\s+(?:-\w+\s+)*-[ce]\s+(['\"])(.*?)(?<!\\)\2", re.S)
WRITES_FILE_RE = re.compile(r"open\([^)]*['\"][wa]['\"]|\.write_text\(|\.write_bytes\(|sed\s+-i")
CAT_TO_FILE_RE = re.compile(
    r"(?:cat|tee)\s+(?:-a\s+)?>?\s*(['\"]?)([^\s'\";&|<>]+)\1\s*<<-?\s*(['\"]?)(\w+)\3[^\n]*\n(.*?)\n\s*\4\s*(?:\n|$)", re.S)


def _utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def projects_dirs(explicit=None):
    if explicit:
        return [Path(explicit).expanduser()]
    if _ccd is not None:
        return [Path(d) for d in _ccd.projects_dirs()]
    return [Path.home() / ".claude" / "projects"]


def find_main_transcripts(pdirs, session):
    pat = "*/" + glob.escape(session) + "*.jsonl"
    if _ccd is not None:
        return [Path(f) for _lab, f in _ccd.transcript_files(pat, roots=[str(d) for d in pdirs])]
    out = []
    for d in pdirs:
        out.extend(sorted(d.glob(pat)))
    return out


def read_calls(path):
    """道具の呼び出しを時刻順に (name, input, ts, is_error, cwd)。"""
    calls, errors, order = {}, {}, []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        msg = o.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        if o.get("type") == "assistant":
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    calls[c.get("id")] = (c.get("name"), c.get("input") or {}, o.get("timestamp", ""), o.get("cwd", ""))
                    order.append(c.get("id"))
        elif o.get("type") == "user":
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    errors[c.get("tool_use_id")] = bool(c.get("is_error"))
    return [(calls[i][0], calls[i][1], calls[i][2], errors.get(i, False), calls[i][3]) for i in order if i in calls]


def _expand(p, cwd):
    p = os.path.expanduser(p)
    if not os.path.isabs(p) and cwd:
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def _git(args, cwd):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def repo_of(path):
    d = path if os.path.isdir(path) else os.path.dirname(path)
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    if not d:
        return None
    rc, out = _git(["rev-parse", "--show-toplevel"], d)
    return out.strip() if rc == 0 and out.strip() else None


def file_status(path):
    if not os.path.exists(path):
        return "❌", "もう無い"
    path = os.path.realpath(path)
    repo = repo_of(path)
    if not repo:
        return "⚠️", "repo の外 (一時 dir・scratchpad など)"
    repo = os.path.realpath(repo)
    rel = os.path.relpath(path, repo)
    rc, _ = _git(["ls-files", "--error-unmatch", "--", rel], repo)
    if rc != 0:
        return "🟡", "repo の中だが未追跡 (" + os.path.basename(repo) + ")"
    rc, out = _git(["status", "--porcelain", "--", rel], repo)
    if out.strip():
        return "🟡", "commit していない変更あり (" + os.path.basename(repo) + ")"
    return "✅", "commit 済み (" + os.path.basename(repo) + ":" + rel + ")"


def is_script_path(path, body=""):
    return Path(path).suffix.lower() in SCRIPT_EXT or body.lstrip().startswith("#!")


def distinctive_lines(body, k=4):
    lines = [ln.strip() for ln in body.splitlines()]
    cand = [ln for ln in lines if len(ln) >= 20 and not ln.startswith(("#", "//", "print(", "echo "))]
    cand = sorted(set(cand), key=len, reverse=True)
    return cand[:k]


def search_saved(body, repos):
    lines = distinctive_lines(body)
    if not lines:
        return "⚠️", "未保存 (特徴的な行が無く探せない)"
    hits = {}
    for repo in repos:
        for ln in lines:
            rc, out = _git(["grep", "-F", "-l", "-e", ln], repo)
            if rc == 0:
                for f in out.split():
                    key = os.path.basename(repo) + ":" + f
                    hits.setdefault(key, set()).add(ln)
    if not hits:
        return "⚠️", "未保存 (探した repo: " + (", ".join(sorted(os.path.basename(r) for r in repos)) or "なし") + ")"
    best, got = max(hits.items(), key=lambda kv: len(kv[1]))
    if len(got) * 2 >= len(lines):
        return "✅", "保存先 = " + best + " (特徴的な行 " + str(len(got)) + "/" + str(len(lines)) + ")"
    return "🔸", "一部一致 = " + best + " (" + str(len(got)) + "/" + str(len(lines)) + "、 書き直した版か確かめる)"


def touched_repos(calls, root):
    """記録の path と cd 先から、 作業ルートの下の repo を集める。"""
    raw = os.path.normpath(os.path.expanduser(root))
    real = os.path.realpath(raw)
    names = set()
    alts = "|".join(sorted({re.escape(raw), re.escape(real), re.escape("~/" + os.path.basename(raw))}, key=len, reverse=True))
    pat = re.compile(r"(?:" + alts + r")/([^/\s'\"`;:)]+)")
    for _name, inp, _ts, _err, cwd in calls:
        blob = json.dumps(inp, ensure_ascii=False) + " " + (cwd or "")
        for m in pat.finditer(blob):
            names.add(m.group(1))
    repos = []
    for n in sorted(names):
        p = os.path.join(raw, n)
        if os.path.isdir(os.path.join(p, ".git")):
            repos.append(p)
    return repos


def all_repos(root):
    root = os.path.expanduser(root)
    return sorted(str(p.parent) for p in Path(root).glob("*/.git"))


def collect(calls):
    files, inline = {}, []
    for name, inp, ts, err, cwd in calls:
        if name in FILE_TOOLS:
            p = inp.get("file_path") or inp.get("notebook_path") or ""
            if p and is_script_path(p, inp.get("content", "")):
                files.setdefault(_expand(p, cwd), ts)
        elif name == "Bash":
            cmd = inp.get("command", "")
            for m in CAT_TO_FILE_RE.finditer(cmd):
                p, body = m.group(2), m.group(5)
                if is_script_path(p, body):
                    files.setdefault(_expand(p, cwd), ts)
            for m in HEREDOC_RE.finditer(cmd):
                if re.search(r"(?:cat|tee)\s+(?:-a\s+)?>", cmd[max(0, m.start() - 80):m.start() + 1]):
                    continue
                body = m.group(5)
                if len(body.splitlines()) >= MIN_LINES:
                    inline.append((ts, m.group(1), body, err))
            for m in DASH_C_RE.finditer(cmd):
                body = m.group(3)
                if len(body.splitlines()) >= MIN_LINES:
                    inline.append((ts, m.group(1) + " -c", body, err))
    return files, inline


def report(session, pdirs, root, use_all, as_json):
    paths = find_main_transcripts(pdirs, session)
    if not paths:
        print("記録が見つからない (session " + session + ")。 見た dir: " + ", ".join(str(d) for d in pdirs))
        return 2, 0
    calls = []
    for p in paths:
        calls.extend(read_calls(p))
    files, inline = collect(calls)
    repos = all_repos(root) if use_all else touched_repos(calls, root)
    rows = []
    for p, ts in sorted(files.items(), key=lambda kv: kv[1]):
        mark, note = file_status(p)
        rows.append({"kind": "file", "time": ts[:19], "what": p, "mark": mark, "note": note})
    for ts, interp, body, err in inline:
        mark, note = search_saved(body, repos)
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")[:90]
        if mark != "✅" and WRITES_FILE_RE.search(body):
            note += " — file を書き換える code (一度きりの置換なら、 結果は書き換えた file に入っている)"
        rows.append({"kind": "inline", "time": ts[:19], "what": interp + " (" + str(len(body.splitlines())) + " 行): " + first,
                     "mark": mark, "note": note + (" — 失敗した実行" if err else "")})
    bad = sum(1 for r in rows if r["mark"] in ("⚠️", "❌", "🟡"))
    if as_json:
        print(json.dumps({"session": session, "transcripts": [str(p) for p in paths], "rows": rows,
                          "unsaved": bad}, ensure_ascii=False, indent=1))
        return 0, bad
    print("記録: " + ", ".join(str(p) for p in paths))
    print("探した repo (その場で流した code の保存先): " + (", ".join(os.path.basename(r) for r in repos) or "なし"))
    print("file に書いた script: " + str(sum(1 for r in rows if r["kind"] == "file")) +
          " / その場で流した code (" + str(MIN_LINES) + " 行以上): " + str(sum(1 for r in rows if r["kind"] == "inline")))
    for r in rows:
        print(r["mark"] + " " + r["time"] + "  " + r["what"])
        print("      " + r["note"])
    print("未保存・未 commit: " + str(bad) + " 件" + ("" if not bad else
          " → 1 本ずつ決める: 出力を記録・note・規約の根拠に使ったなら記録の隣に file で残す。 使っていないなら置かず、 報告に理由 (closing-sweep.md#placement)"))
    return 0, bad


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="session がその場で書いた script を並べ、 保存の有無を出す")
    ap.add_argument("session", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    ap.add_argument("--projects-dir")
    ap.add_argument("--root", default="~/Claude", help="作業ルート (repo を探す範囲)")
    ap.add_argument("--all-repos", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.session:
        ap.error("session id を渡す (または CLAUDE_CODE_SESSION_ID)")
    rc, bad = report(a.session, projects_dirs(a.projects_dir), a.root, a.all_repos, a.json)
    if rc:
        return rc
    return 1 if (a.strict and bad) else 0


def selftest():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + msg)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as t:
        root = os.path.join(t, "work")
        repo = os.path.join(root, "proj")
        os.makedirs(repo)
        _git(["init", "-q"], repo)
        _git(["config", "user.email", "t@example.invalid"], repo)
        _git(["config", "user.name", "t"], repo)
        saved_body = "\n".join(["import math", "def area_of_circle(radius_value):",
                                "    return math.pi * radius_value * radius_value", "value = area_of_circle(2.5)",
                                "print(value)"])
        Path(repo, "kept.py").write_text(saved_body + "\n", encoding="utf-8")
        _git(["add", "kept.py"], repo)
        _git(["commit", "-q", "-m", "x"], repo)
        Path(repo, "dirty.py").write_text("print('dirty')\n", encoding="utf-8")
        tmpscript = os.path.join(t, "scratch", "one.py")
        os.makedirs(os.path.dirname(tmpscript))
        Path(tmpscript).write_text("print(1)\n", encoding="utf-8")
        unsaved_body = "\n".join(["import statistics", "samples_of_the_measurement = [1.0, 2.0, 4.0]",
                                  "mean_of_the_measurement = statistics.mean(samples_of_the_measurement)",
                                  "spread_of_the_measurement = statistics.pstdev(samples_of_the_measurement)",
                                  "print(mean_of_the_measurement, spread_of_the_measurement)"])
        proj = os.path.join(t, "projects", "-x")
        os.makedirs(proj)
        sid = "feedc0de-0000-0000-0000-000000000000"
        recs = []

        def call(i, name, inp, err=False):
            recs.append({"type": "assistant", "timestamp": "2026-01-01T00:00:%02d" % i, "cwd": repo,
                         "message": {"content": [{"type": "tool_use", "id": "t%d" % i, "name": name, "input": inp}]}})
            recs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t%d" % i,
                                                                  "is_error": err, "content": "x"}]}})
        call(1, "Write", {"file_path": os.path.join(repo, "kept.py"), "content": saved_body})
        call(2, "Write", {"file_path": os.path.join(repo, "dirty.py"), "content": "print('dirty')"})
        call(3, "Write", {"file_path": tmpscript, "content": "print(1)"})
        call(4, "Write", {"file_path": os.path.join(repo, "note.md"), "content": "# not a script"})
        call(5, "Bash", {"command": "cd " + repo + " && python3 - <<'EOF'\n" + unsaved_body + "\nEOF"})
        call(6, "Bash", {"command": "python3 - <<'EOF'\n" + saved_body + "\nEOF"}, err=True)
        call(7, "Bash", {"command": "cat > " + os.path.join(repo, "gen.sh") + " <<'EOF'\n#!/bin/sh\necho hi\nEOF"})
        call(8, "Bash", {"command": "python3 -c 'print(1)'"})
        call(9, "Bash", {"command": "tools/py - \"$f\" <<'EOF'\n" + unsaved_body.replace("statistics", "stats") + "\nEOF"})
        Path(proj, sid + ".jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

        calls = read_calls(Path(proj, sid + ".jsonl"))
        files, inline = collect(calls)
        check(set(files) == {os.path.join(repo, "kept.py"), os.path.join(repo, "dirty.py"), tmpscript,
                             os.path.join(repo, "gen.sh")}, "file に書いた script = 4 本 (md は数えない、 cat > も拾う)")
        check(len(inline) == 3, "その場で流した code = 3 本 (1 行の -c は数えない、 tools/py の wrapper も拾う)")
        check(file_status(os.path.join(repo, "kept.py"))[0] == "✅", "commit 済みは ✅")
        check(file_status(os.path.join(repo, "dirty.py"))[0] == "🟡", "未追跡は 🟡")
        check(file_status(tmpscript)[0] == "⚠️", "repo の外は ⚠️")
        check(file_status(os.path.join(repo, "gen.sh"))[0] == "❌", "書いたはずで無い file は ❌")
        check(search_saved(unsaved_body, [repo])[0] == "⚠️", "どこにも無い code は ⚠️")
        check(search_saved(saved_body, [repo])[0] == "✅", "commit 済みの file と同じ code は ✅")
        check(inline[1][3] is True, "失敗した実行の印")
        check(touched_repos(calls, root) == [repo], "記録の path から repo を集める")
        rc, bad = report(sid[:8], [Path(t, "projects")], root, False, True)
        check(rc == 0 and bad == 5, "未保存・未 commit の数 = 5 (dirty・scratch・gen.sh・code 2 本)")
    print("selftest: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
