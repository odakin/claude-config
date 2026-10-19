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
  3. 出力の数値 — その場で流した code と、 file の script の実行 (`python3 x.py` など) の出力から、 計算の結果らしい数値
     (小数 2 桁以上・指数表記。 時刻・版番号・file 名・arXiv 番号は拾わない) を拾い、 探した repo の記録 (md・tex・txt・out・py・yaml
     など、 json・csv の data は除く) に語の単位で書かれているかを数える (末尾の 0 を落とした形と有効数字 4 桁の丸めも探す)。
     記録に無い数値が残る行は最後に 🔢 で並べる = 会話の返事にしか無い計算結果の候補 (実測: code は保存したと数えたのに、
     その code が出した数値を note に書かず、 締めでも拾えなかった)。 書いた記録が別の言い方・別の丸めなら一致しないので、
     🔢 は「記録が無い」 の証明ではなく、 1 件ずつ確かめる候補。

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
# 計算の結果らしい数値 = 小数 2 桁以上 か 指数表記。 前後が語の文字・点・コロン・slash なら拾わない (時刻・版番号・file 名・id)
NUMBER_RE = re.compile(r"(?<![\w.:/-])[-+]?\d+\.\d{2,}(?:[eE][-+]?\d+)?(?![\w.:/])"
                       r"|(?<![\w.:/-])[-+]?\d+(?:\.\d+)?[eE][-+]?\d+(?![\w.:/])")
ARXIV_ID_RE = re.compile(r"\d{4}\.\d{4,5}")
# 数値を探す記録 = 人が書く記録と検算の code・出力。 数字の羅列の data (json・csv) は無関係な数字に一致するので探さない (実測)
RECORD_PATHSPECS = ["*.md", "*.tex", "*.txt", "*.out", "*.py", "*.yaml", "*.yml", "*.sh", "*.jl", "*.R", "*.wls", "*.log"]
# file の script の実行 (python3 x.py / tools/py x.py / bash x.sh)
RUN_SCRIPT_RE = re.compile(r"(?:^|[\s;&|(])(" + INTERP + r")\s+(?:-\w+\s+)*([^\s;&|<>'\"]+\.(?:py|sh|jl|R|rb|pl|js|wls))(?=\s|$)")
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
    """道具の呼び出しを時刻順に (name, input, ts, is_error, cwd, output)。"""
    calls, errors, outputs, order = {}, {}, {}, []
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
                    outputs[c.get("tool_use_id")] = _result_text(c.get("content"))
    return [(calls[i][0], calls[i][1], calls[i][2], errors.get(i, False), calls[i][3], outputs.get(i, ""))
            for i in order if i in calls]


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


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
    for _name, inp, _ts, _err, cwd, _out in calls:
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
    files, inline, runs = {}, [], []
    for name, inp, ts, err, cwd, out in calls:
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
                    inline.append((ts, m.group(1), body, err, out))
            for m in DASH_C_RE.finditer(cmd):
                body = m.group(3)
                if len(body.splitlines()) >= MIN_LINES:
                    inline.append((ts, m.group(1) + " -c", body, err, out))
            m = RUN_SCRIPT_RE.search(cmd)
            if m and not HEREDOC_RE.search(cmd):
                runs.append((ts, m.group(2), out))
    return files, inline, runs


def result_numbers(out, k=8):
    """道具の出力にある計算の結果らしい数値 (小数 2 桁以上・指数表記)。 時刻・版番号・file 名の数字は拾わない。"""
    seen = []
    for m in NUMBER_RE.finditer(out or ""):
        v = m.group(0).lstrip("+")
        if ARXIV_ID_RE.fullmatch(v):
            continue
        if v not in seen:
            seen.append(v)
    return seen[:k]


def _variants(num):
    """記録には丸めて書くことが多いので、 末尾の 0 を落とした形と、 有効数字 4 桁に丸めた形も探す
    (3 桁まで丸めると無関係な数字に一致する = 実測)。"""
    out = {num}
    if "." in num and "e" not in num.lower():
        out.add(num.rstrip("0").rstrip("."))
    try:
        x = float(num)
    except ValueError:
        return out
    digits = len(re.sub(r"[^0-9]", "", num.lower().split("e")[0]).lstrip("0"))
    for sig in (4,):
        if digits > sig and x != 0:
            out.add(("%." + str(sig) + "g") % x)
    return {v for v in out if v}


def numbers_recorded(nums, repos):
    """nums のうち、 repos の追跡済み file のどこかに (丸めた形を含めて) 書かれているもの。"""
    if not nums or not repos:
        return []
    want = {n: _variants(n) for n in nums}
    pats = sorted({v for vs in want.values() for v in vs})
    found = set()
    for repo in repos:
        args = ["grep", "-F", "-w", "-o", "-h", "--no-color"]   # -w = 0.5536 が 0.553612 の一部に一致しない
        for v in pats:
            args += ["-e", v]
        args += ["--"] + RECORD_PATHSPECS
        rc, out = _git(args, repo)
        if rc == 0:
            found.update(out.split())
    return [n for n, vs in want.items() if any(v in found for v in vs)]


def report(session, pdirs, root, use_all, as_json):
    paths = find_main_transcripts(pdirs, session)
    if not paths:
        print("記録が見つからない (session " + session + ")。 見た dir: " + ", ".join(str(d) for d in pdirs))
        return 2, 0
    calls = []
    for p in paths:
        calls.extend(read_calls(p))
    files, inline, runs = collect(calls)
    repos = all_repos(root) if use_all else touched_repos(calls, root)
    rows = []
    for p, ts in sorted(files.items(), key=lambda kv: kv[1]):
        mark, note = file_status(p)
        rows.append({"kind": "file", "time": ts[:19], "what": p, "mark": mark, "note": note})
    for ts, interp, body, err, out in inline:
        mark, note = search_saved(body, repos)
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")[:90]
        if mark != "✅" and WRITES_FILE_RE.search(body):
            note += " — file を書き換える code (一度きりの置換なら、 結果は書き換えた file に入っている)"
        rows.append({"kind": "inline", "time": ts[:19], "what": interp + " (" + str(len(body.splitlines())) + " 行): " + first,
                     "mark": mark, "note": note + (" — 失敗した実行" if err else ""), **_number_fields(out, repos)})
    for ts, script, out in runs:
        f = _number_fields(out, repos)
        if f.get("numbers"):
            rows.append({"kind": "run", "time": ts[:19], "what": "実行: " + script, "mark": "·", "note": "script の実行の出力", **f})
    bad = sum(1 for r in rows if r["mark"] in ("⚠️", "❌", "🟡"))
    lost = [r for r in rows if r.get("numbers") and len(r.get("recorded", [])) < len(r["numbers"])]
    if as_json:
        print(json.dumps({"session": session, "transcripts": [str(p) for p in paths], "rows": rows,
                          "unsaved": bad, "numbers_not_recorded": len(lost)}, ensure_ascii=False, indent=1))
        return 0, bad
    print("記録: " + ", ".join(str(p) for p in paths))
    print("探した repo (その場で流した code の保存先): " + (", ".join(os.path.basename(r) for r in repos) or "なし"))
    print("file に書いた script: " + str(sum(1 for r in rows if r["kind"] == "file")) +
          " / その場で流した code (" + str(MIN_LINES) + " 行以上): " + str(sum(1 for r in rows if r["kind"] == "inline")))
    for r in rows:
        if r["kind"] == "run":
            continue
        print(r["mark"] + " " + r["time"] + "  " + r["what"])
        print("      " + r["note"] + _number_note(r))
    print("未保存・未 commit: " + str(bad) + " 件" + ("" if not bad else
          " → 1 本ずつ決める: 出力を記録・note・規約の根拠に使ったなら記録の隣に file で残す。 使っていないなら置かず、 報告に理由 (closing-sweep.md#placement)"))
    if lost:
        print("🔢 数値を出したのに、 その数値が探した repo のどの記録にも無い: " + str(len(lost)) + " 件"
              " = 研究の中身・根拠の取りこぼしの候補 (closing-sweep.md#collect-from-transcript)。"
              " 1 件ずつ note に書くか、 書かない理由を報告に:")
        for r in lost:
            miss = [n for n in r["numbers"] if n not in r["recorded"]]
            print("   " + r["time"] + "  " + r["what"][:100] + "  → 記録に無い: " + ", ".join(miss[:5]))
    return 0, bad


def _number_fields(out, repos):
    nums = result_numbers(out)
    if not nums:
        return {}
    return {"numbers": nums, "recorded": numbers_recorded(nums, repos)}


def _number_note(r):
    if not r.get("numbers"):
        return ""
    return (" — 🔢 出力の数値 " + str(len(r["numbers"])) + " 個のうち記録にあるのは " + str(len(r["recorded"])) +
            " 個 (" + ", ".join(r["numbers"][:4]) + ")")


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


def _capture(fn):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


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
        # 出力に計算の結果: 0.23940 は記録 (丸めた 0.2394) にあり、 0.5615 は無い。 時刻・版番号・file 名の数字は拾わない
        Path(repo, "note.md").write_text("weight = 0.2394\n", encoding="utf-8")
        _git(["add", "note.md"], repo)
        _git(["commit", "-q", "-m", "note"], repo)
        numeric_body = unsaved_body.replace("print(", "print('w', ")
        recs.append({"type": "assistant", "timestamp": "2026-01-01T00:00:10", "cwd": repo,
                     "message": {"content": [{"type": "tool_use", "id": "t10", "name": "Bash",
                                              "input": {"command": "python3 - <<'EOF'\n" + numeric_body + "\nEOF"}}]}})
        recs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t10", "content": [
            {"type": "text", "text": "w 0.23940 0.5615 at 07:46:54.329Z v2.1.287 file 1401.6700.pdf 7.6e-10"}]}]}})
        recs.append({"type": "assistant", "timestamp": "2026-01-01T00:00:11", "cwd": repo,
                     "message": {"content": [{"type": "tool_use", "id": "t11", "name": "Bash",
                                              "input": {"command": "python3 " + os.path.join(repo, "kept.py")}}]}})
        recs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t11",
                                                              "content": "area 19.635"}]}})
        Path(proj, sid + ".jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

        calls = read_calls(Path(proj, sid + ".jsonl"))
        files, inline, runs = collect(calls)
        check(result_numbers("ids 2102.12032 and 1809.04285, value 0.0785") == ["0.0785"], "arXiv 番号は数値として拾わない")
        check(result_numbers(inline[-1][4]) == ["0.23940", "0.5615", "7.6e-10"],
              "出力の数値 = 小数 2 桁以上と指数表記 (時刻・版番号・file 名の数字は拾わない)")
        check(numbers_recorded(["0.23940", "0.5615"], [repo]) == ["0.23940"], "丸めた形で記録にある数値は記録あり、 無いものは無し")
        check([r[1] for r in runs] == [os.path.join(repo, "kept.py")] and "19.635" in runs[0][2], "file の script の実行と出力も拾う")
        inline = inline[:-1]
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
        check(rc == 0 and bad == 6, "未保存・未 commit の数 = 6 (dirty・scratch・gen.sh・code 3 本)")
        rows = json.loads(_capture(lambda: report(sid[:8], [Path(t, "projects")], root, False, True)))
        check(rows["numbers_not_recorded"] == 2, "記録に無い数値を出した行 = 2 (一部だけ記録にある code・記録に無い script の実行)")
    print("selftest: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
