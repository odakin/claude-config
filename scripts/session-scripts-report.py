#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会話記録からスクリプトを拾い、保存先を照合する。--selftest 内蔵。

用途: 締めの sweep (conventions/closing-sweep.md#collect-from-transcript) で、 その場で書いた script を取りこぼさないため。
context から思い出すと、 file に残らない形 (heredoc で interpreter に流した code・`-c` / `-e` の code) を数え落とす
(実測: 締めで file の script だけを数え、 結果を記録の根拠に使った heredoc の Python を落とした)。 agent が書いた
script は subagent-reports.py、 headless の worker の script は headless-worker-reports.py が出す = 本 script は session 本体の分。

拾うもの (session 本体の記録 <projects-dir>/<project>/<session id>.jsonl の道具の呼び出し):
  1. file に書いた script — Write / Edit / MultiEdit / NotebookEdit の path と、 Bash の `cat > path <<EOF` / `tee path <<EOF`
     のうち、 拡張子が script のもの (SCRIPT_EXT) か本文が shebang で始まるもの。 相対 path は、 同じ command の中の
     `cd <dir> &&` / `cd <dir>;` を順に当てた位置から解決する (記録の cwd は command を打つ前の位置 = その cd を含まない。
     実測: `cd <下の dir> && cat > x.py` を 1 つ上の dir で探し、 commit 済みの file を「もう無い」 と出した)。
     書き先の path と cd 先の変数は、 同じ command の中で先に代入したもの (`D=<dir>; cat > $D/x.py` / `D=<dir>; cd "$D/sub"; cat > x.py`)
     を展開する。 展開できない変数が残る path は「もう無い」 でなく「path に展開できない変数」 と出す (実測: `SP=<dir>; cat > $SP/x.py` の
     file を cwd の下の `$SP/x.py` と読み、 変数の cd 先を辿らず相対の書き先を cd の前の位置で探し、 どちらも一時 dir に在る file を「もう無い」 と出した)
  2. その場で流した code — Bash の `<interpreter> [opts] [-] <<EOF` (stdin に流す heredoc) と `<interpreter> -c '…'` / `-e '…'`
     (interpreter = python/python3/py/tools/py 型の wrapper・node・ruby・perl・Rscript・julia・wolframscript・bash/sh/zsh)。
     MIN_LINES 行未満の短いもの (1 行の確かめ) は数えない。 拾った code が失敗した実行なら印を付ける。

判定:
  1 の file → ✅ commit 済み (作業ツリーとの差なし) / 🟡 repo の中だが未 commit・未追跡 / ⚠️ repo の外 (一時 dir・scratchpad) / ❌ もう無い /
     🔀 元の path に無いが同じ名前の追跡済み file がある (実測: session の途中で folder を改名し、 commit 済みの file を「もう無い」 と出した。 別の file の同名かもしれないので読んで確かめる)
  2 の code → 特徴的な行 (長い行から最大 4 本) を、 session が触った repo (記録の path から導く。 --all-repos で作業ルートの全部) の
     追跡済み file から `git grep -F` で探す。 半分以上が同じ file にあれば ✅ (その file)、 1 本だけなら 🔸 一部一致 (書き直した版か)、
     無ければ ⚠️ 未保存。
  ⚠️ のものは 1 本ずつ決める (closing-sweep.md#placement の script の行): 出力を記録・note・規約の根拠に使ったなら、 その記録の
  隣に file として残す (1 回きりでも)。 根拠に使っていないなら置かず、 報告に「置かない」 と理由を書く。
  3. 出力の数値 — lib/output_numbers.py の共通規則で記録と照合し、 🔢 の候補を出す。
     拾う数値・探す記録・丸め・解釈の限界の正本は同 module の冒頭。

使い方:
  session-scripts-report.py <session id か先頭の数文字>     # 既定は環境変数 CLAUDE_CODE_SESSION_ID
  session-scripts-report.py abcd1234 --all-repos            # 作業ルート (--root、 既定 ~/Claude) の全 repo で探す
  session-scripts-report.py abcd1234 --json
  session-scripts-report.py abcd1234 --strict               # ⚠️ / ❌ / 🟡 が 1 件でもあれば exit 1
  session-scripts-report.py --inventory codex-inventory.json --json
  session-scripts-report.py --inventory codex-inventory.json --check-dispositions dispositions.json
  session-scripts-report.py --selftest

Codex は `codex-wrap-inventory.py <full-id> --json` の出力を入力にする。
一覧には一行の inline code も出す。本文と出力は載せず、thread・tool call ID で辿る。
`--check-dispositions` は同じ inventory に対し、各 ID の保存先（--root からの追跡済み
パス）か、除外理由が揃っていることを確かめる。JSON の形式は
`{"<ID>": {"saved": "project/checks/example.py"}, "<ID>": {"excluded": "理由"}}`。
検査は照合表の充足と保存先の状態まで。結論の裏付けや未対応の道具でのコード生成は目視する。

projects-dir の既定 = この機械の全部の設定 dir の projects/ (lib/claude_config_dirs.py)。 0 件なら見た dir を出す。

OS: macOS / Linux / Windows (Git Bash・PowerShell) で同じに動く (標準 library + git、 Python 3.8+、 出力は UTF-8)。
"""
import argparse
from collections import Counter
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

from output_numbers import _number_fields

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
# file の script の実行 (python3 x.py / tools/py x.py / bash x.sh)。 path は引用符で囲んだ形 (空白を含んでよい) と、
# 空白をバックスラッシュで逃がした形も取る (実測: 空白を含む path の script の起動を 1 件も数えなかった)。 値は unquote_path で戻す
_RUN_EXT = r"\.(?:py|sh|jl|R|rb|pl|js|wls)"
RUN_SCRIPT_RE = re.compile(r"(?:^|[\s;&|(])(" + INTERP + r")\s+(?:-\w+\s+)*(\"[^\"\n]+?" + _RUN_EXT + r"\"|'[^'\n]+?" + _RUN_EXT
                           + r"'|(?:\\.|[^\s;&|<>'\"\\])+?" + _RUN_EXT + r")(?=\s|$)")


def unquote_path(s):
    """command の中の path の字面を値に戻す: 囲む引用符を外し、 バックスラッシュで逃がした文字を戻す。"""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return re.sub(r"\\(.)", r"\1", s)


def path_args(cmd, ext):
    """cmd の中の、 拡張子 ext (正規表現の選択肢、 例 'pdf') で終わる path を (位置, 値) で順に返す。

    引用符で囲んだ文字列は空白・括弧を含めて 1 つの path (python の open('…') や p="…" の中も)、 空白などを
    バックスラッシュで逃がした語は戻した値、 残りは裸の語 (頭が ~ / / / $VAR/ か相対、 URL は除く)。 裸の語は、
    先に取った引用符の範囲の中では拾わない。 実測: 空白を含む PDF の path を最後の空白で切り、 後ろの断片 (`mechanics.pdf`
    や `.pdf`) を相対 path と読んで「もう無い」 と出した。 位置は変数と cd の展開 (_vars_at / _cwd_at) に渡す。"""
    quoted = re.compile(r"(?:^|(?<=[\s=(,\[{:]))(?:\"([^\"\n]*?\.(?:%s))\"|'([^'\n]*?\.(?:%s))')" % (ext, ext), re.I)
    bare = re.compile(r"(?:^|(?<=[\s'\"=(,]))((?:~|/|\$\{?\w+\}?/|(?![a-z][a-z0-9+.-]*://)(?=[\w.\\]))"
                      r"(?:\\.|[^\s'\";|&<>()\\])*?\.(?:%s))(?=[\s'\";|&<>),]|$)" % ext, re.I)
    out, spans = [], []
    for m in quoted.finditer(cmd):
        g = 1 if m.group(1) is not None else 2
        out.append((m.start(g), m.group(g)))
        spans.append((m.start(), m.end()))
    for m in bare.finditer(cmd):
        if not any(a <= m.start(1) < b for a, b in spans):
            out.append((m.start(1), unquote_path(m.group(1))))
    return sorted(out)
CAT_TO_FILE_RE = re.compile(
    r"(?:cat|tee)\s+(?:-a\s+)?>?\s*(['\"]?)([^\s'\";&|<>]+)\1\s*<<-?\s*(['\"]?)(\w+)\3[^\n]*\n(.*?)\n\s*\4\s*(?:\n|$)", re.S)
# 同じ command の中の `cd <dir> &&` / `cd <dir>;` (記録の cwd は command を打つ前の位置 = この cd を含まない)
CD_RE = re.compile(r"(?:^|&&|;|\n)\s*cd\s+(['\"]?)([^\s'\";&|<>`(]+)\1\s*(?=&&|;|\n)")
# 同じ command の中の `NAME=<value>` / `export NAME=<value>` (cat > の書き先の $NAME を展開するため)
ASSIGN_RE = re.compile(r"(?:^|&&|;|\n)\s*(?:export\s+)?([A-Za-z_]\w*)=(['\"]?)([^\s'\";&|<>`]*)\2(?=\s|;|&&|\n|$)")
VAR_RE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")


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


def _subst(p, env):
    """p の $NAME / ${NAME} のうち env にあるものを置き換える (無いものは残す)。"""
    return VAR_RE.sub(lambda m: env.get(m.group(1) or m.group(2), m.group(0)), p)


def _vars_at(cmd, pos):
    """cmd の pos より前で代入した変数 (順に当てる、 値の中の既知の変数も展開する)。"""
    env = {}
    for m in ASSIGN_RE.finditer(cmd[:pos]):
        env[m.group(1)] = _subst(m.group(3), env)
    return env


def _cwd_at(cmd, pos, cwd):
    """cmd の pos より前にある `cd <dir>` を順に当てた cwd。 cd 先の変数は同じ command で先に代入したものを展開し、
    展開できない変数は path に残す (file_status が「もう無い」 でなく ⚠️ と出す)。 `cd $(…)` は辿らない。"""
    for m in CD_RE.finditer(cmd[:pos]):
        cwd = _expand(_subst(m.group(2), _vars_at(cmd, m.start())), cwd)
    return cwd


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


def renamed_candidates(path):
    """無い file と同じ名前の追跡済み file を、 親の dir が残っている repo から探す (session の途中で folder を改名したとき用)。"""
    repo = repo_of(path)
    if not repo:
        return []
    name = os.path.basename(path)
    rc, out = _git(["ls-files", "--", name, "*/" + name], repo)
    if rc != 0:
        return []
    return [line for line in out.splitlines() if line.strip()]


def file_status(path):
    if not os.path.exists(path):
        if VAR_RE.search(path):
            return "⚠️", "path に展開できない変数 (記録の command を見る)"
        moved = renamed_candidates(path)
        if moved:
            return "🔀", "元の path には無い。 同じ名前の追跡済み file = " + ", ".join(moved[:2]) + " (改名か確かめる)"
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
    if rc != 0:
        return "⚠️", "作業ツリーを確認できない (" + os.path.basename(repo) + ")"
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


def collect(calls, min_lines=MIN_LINES):
    files, inline, runs = {}, [], []
    for name, inp, ts, err, cwd, out in calls:
        if name in FILE_TOOLS:
            p = inp.get("file_path") or inp.get("notebook_path") or ""
            if p and is_script_path(p, inp.get("content", "")):
                files.setdefault(_expand(p, cwd), ts)
        elif name == "Bash":
            cmd = inp.get("command", "")
            for m in CAT_TO_FILE_RE.finditer(cmd):
                p, body = _subst(m.group(2), _vars_at(cmd, m.start())), m.group(5)
                if is_script_path(p, body):
                    files.setdefault(_expand(p, _cwd_at(cmd, m.start(), cwd)), ts)
            for m in HEREDOC_RE.finditer(cmd):
                if re.search(r"(?:cat|tee)\s+(?:-a\s+)?>", cmd[max(0, m.start() - 80):m.start() + 1]):
                    continue
                body = m.group(5)
                if len(body.splitlines()) >= min_lines:
                    inline.append((ts, m.group(1), body, err, out))
            for m in DASH_C_RE.finditer(cmd):
                body = m.group(3)
                if len(body.splitlines()) >= min_lines:
                    inline.append((ts, m.group(1) + " -c", body, err, out))
            m = RUN_SCRIPT_RE.search(cmd)
            if m and not HEREDOC_RE.search(cmd):
                runs.append((ts, unquote_path(m.group(2)), out))
    return files, inline, runs


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
    bad = sum(1 for r in rows if r["mark"] in ("⚠️", "❌", "🟡", "🔀"))
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


def _number_note(r):
    if not r.get("numbers"):
        return ""
    return (" — 🔢 出力の数値 " + str(len(r["numbers"])) + " 個のうち記録にあるのは " + str(len(r["recorded"])) +
            " 個 (" + ", ".join(r["numbers"][:4]) + ")")


def inventory_rows(inventory):
    from codex_thread_reader import shell_payload

    if not inventory['threads'] or inventory['threads'][0]['id'] != inventory['root']:
        raise ValueError('inventory の親 thread が一致しない')
    rows, seen_files = [], set()
    for thread in inventory['threads']:
        thread_id = thread['id']
        calls = [
            ('Bash', {'command': shell_payload(tool['input'])}, tool['id'],
             bool(tool.get('exit_code')), tool.get('cwd') or thread.get('cwd'), '')
            for tool in thread['tools'] if tool['tool'] == 'Bash'
        ]
        files, inline, _ = collect(calls, min_lines=1)
        for change in thread['files']:
            if is_script_path(change['path']):
                files.setdefault(_expand(change['path'], thread.get('cwd')), change['call'])
        for path, call in sorted(files.items()):
            if path in seen_files:
                continue
            seen_files.add(path)
            if os.path.isabs(path):
                mark, note = file_status(path)
            else:
                mark, note = '⚠️', '記録に作業ディレクトリが無く保存先を解決できない'
            rows.append(dict(id='file:' + path, thread=thread_id, call=call,
                             kind='file', what=path, mark=mark, note=note))
        ordinal = Counter()
        for call, interpreter, body, failed, _ in inline:
            ordinal[call] += 1
            rows.append(dict(id=f'inline:{thread_id}:{call}:{ordinal[call]}',
                             thread=thread_id, call=call, kind='inline',
                             what=f'{interpreter} ({len(body.splitlines())} 行)', failed=failed))
    return rows


def disposition_errors(rows, dispositions, root):
    if not isinstance(dispositions, dict):
        raise ValueError('照合表は ID をキーにした JSON object にする')
    ids = {row['id'] for row in rows}
    errors = ['未照合: ' + key for key in sorted(ids - dispositions.keys())]
    errors.extend('一覧にない ID: ' + key for key in sorted(dispositions.keys() - ids))
    root = Path(root).expanduser().resolve()
    for key in sorted(ids & dispositions.keys()):
        entry = dispositions[key]
        if not isinstance(entry, dict) or set(entry) not in ({'saved'}, {'excluded'}):
            errors.append(f'{key}: saved か excluded を一つ記録する')
            continue
        status, value = next(iter(entry.items()))
        if not isinstance(value, str) or not value.strip():
            errors.append(f'{key}: 保存先か除外理由が空')
        elif status == 'saved':
            path = (root / value).resolve()
            if (Path(value).is_absolute() or root not in path.parents or not path.is_file()
                    or file_status(str(path))[0] != '✅'):
                errors.append(f'{key}: 保存先を追跡済みファイルとして確認できない: {value}')
    return errors


def report_inventory(args):
    inventory = json.loads(Path(args.inventory).read_text(encoding='utf-8'))
    rows = inventory_rows(inventory)
    warnings = [warning for thread in inventory['threads'] for warning in thread['warnings']]
    unavailable = inventory['unavailable']
    errors = []
    if args.check_dispositions:
        dispositions = json.loads(Path(args.check_dispositions).read_text(encoding='utf-8'))
        errors = disposition_errors(rows, dispositions, args.root)
    if args.json:
        print(json.dumps(dict(session=inventory['root'], rows=rows, warnings=warnings,
                              unavailable=unavailable, errors=errors), ensure_ascii=False, indent=1))
    else:
        for row in rows:
            print(f"{row['id']}  {row['what']}  call={row['call']}")
        print(f"スクリプト候補 {len(rows)} 件")
        if args.check_dispositions:
            print(f"照合表の指摘 {len(errors)} 件")
        for error in errors:
            print(error)
        for warning in warnings:
            print('WARNING:', warning)
        for item in unavailable:
            print('UNAVAILABLE:', item)
    if warnings or unavailable:
        return 2
    return 1 if errors or (args.strict and not args.check_dispositions
                           and any(row.get('mark') != '✅' for row in rows)) else 0


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="session がその場で書いた script を並べ、 保存の有無を出す")
    ap.add_argument("session", nargs="?")
    ap.add_argument("--projects-dir")
    ap.add_argument("--root", default="~/Claude", help="作業ルート (repo を探す範囲)")
    ap.add_argument("--all-repos", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--inventory", help="Codex の棚卸し JSON")
    ap.add_argument("--check-dispositions", help="同じ棚卸しに対する保存先・除外理由の JSON")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.inventory:
        if a.session:
            ap.error('session と --inventory は同時に指定しない')
        try:
            return report_inventory(a)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            print(f'Codex の棚卸しを読めない: {exc}', file=sys.stderr)
            return 2
    if a.check_dispositions:
        ap.error('--check-dispositions には --inventory が必要')
    session = a.session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        ap.error("session id を渡す (または CLAUDE_CODE_SESSION_ID)")
    rc, bad = report(session, projects_dirs(a.projects_dir), a.root, a.all_repos, a.json)
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
        os.makedirs(os.path.join(repo, "sub"))
        Path(repo, "sub", "gen2.sh").write_text("#!/bin/sh\necho two\n", encoding="utf-8")
        _git(["add", "kept.py", "sub/gen2.sh"], repo)
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
        # 記録の cwd = repo のまま、 同じ command の中で sub へ cd してから相対 path に書く
        call(12, "Bash", {"command": "cd " + os.path.join(repo, "sub") + " && cat > gen2.sh <<'EOF'\n#!/bin/sh\necho two\nEOF"})
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
        import output_numbers
        check(_number_fields is output_numbers._number_fields and
              _number_fields(inline[-1][4], [repo]) == {
                  "numbers": ["0.23940", "0.5615", "7.6e-10"], "recorded": ["0.23940"]},
              "共通 module を import して同じ出力を照合する")
        check([r[1] for r in runs] == [os.path.join(repo, "kept.py")] and "19.635" in runs[0][2], "file の script の実行と出力も拾う")
        # 空白を含む path の script の起動 (実測: 1 件も数えなかった)。 引用符・逃がした空白を読み、 値に戻す
        sp = [(c, RUN_SCRIPT_RE.search(c)) for c in ('python3 "/tmp/a dir/check.py" --x', "bash '/tmp/a dir/run.sh'",
                                                      "python3 /tmp/a\\ dir/check.py", 'python3 -c "print(1)"')]
        check([unquote_path(m.group(2)) if m else None for _, m in sp] == ["/tmp/a dir/check.py", "/tmp/a dir/run.sh",
                                                                          "/tmp/a dir/check.py", None],
              "空白を含む path の script の起動も拾う (-c の本文は拾わない)")
        pa_cmd = "d=fitz.open('a b/x y.pdf'); p=\"c (d) .pdf\"; cat e\\ f.pdf https://h.org/u.pdf g.pdf"
        pa = path_args(pa_cmd, "pdf")
        check([v for _, v in pa] == ["a b/x y.pdf", "c (d) .pdf", "e f.pdf", "g.pdf"] and
              [pos for pos, _ in pa] == [pa_cmd.index("a b/"), pa_cmd.index("c (d)"), pa_cmd.index("e\\ f"), pa_cmd.index(" g.pdf") + 1],
              "path_args = 引用符の中は空白・括弧ごと 1 つ、 逃がした空白は戻す、 URL は除く、 裸の語も拾う")
        inline = inline[:-1]
        check(set(files) == {os.path.join(repo, "kept.py"), os.path.join(repo, "dirty.py"), tmpscript,
                             os.path.join(repo, "gen.sh"), os.path.join(repo, "sub", "gen2.sh")},
              "file に書いた script = 5 本 (md は数えない、 cat > も拾う、 同じ command の cd 先で解決する)")
        check(file_status(os.path.join(repo, "sub", "gen2.sh"))[0] == "✅", "cd 先に書いて commit 済みの file は ✅ (cd の前の位置で探して ❌ にしない)")
        check(_cwd_at("cd /a/b && cd c && cat > f", 22, "/x") == "/a/b/c" and
              _cwd_at('cd "$D" && cat > f', 12, "/x") == "/x/$D", "cd を順に当てる / 展開できない変数の cd 先は path に残す")
        cd_cmd = 'D=/a; cd "$D/b"; cat > f'
        check(_cwd_at(cd_cmd, cd_cmd.index("cat >"), "/x") == "/a/b", "cd 先の変数も同じ command の代入で展開する")
        check(_cwd_at("cd $(mktemp -d); cat > f", 18, "/x") == "/x", "cd $(…) は辿らない")
        check(file_status(_expand("f", _cwd_at('cd "$NOPE" && cat > f', 15, repo)))[0] == "⚠️",
              "展開できない変数の cd 先に書いた相対 path も ❌ (もう無い) でなく ⚠️")
        sp_cmd ='R=/a; SP="$R/b"; mkdir -p $SP/t; cat > $SP/t/x.py <<\'EOF\'\nprint(1)\nEOF'
        check(_subst("$SP/t/x.py", _vars_at(sp_cmd, sp_cmd.index("cat >"))) == "/a/b/t/x.py" and
              _subst("${R}/y", {"R": "/a"}) == "/a/y" and _subst("$NOPE/z", {}) == "$NOPE/z",
              "cat > の書き先は同じ command で先に代入した変数を展開する (値の中の既知の変数も、 未知の変数は残す)")
        check(file_status(os.path.join(repo, "$NOPE", "x.py"))[0] == "⚠️",
              "展開できない変数が残る path は ❌ (もう無い) でなく ⚠️")
        check(len(inline) == 3, "その場で流した code = 3 本 (1 行の -c は数えない、 tools/py の wrapper も拾う)")
        check(file_status(os.path.join(repo, "kept.py"))[0] == "✅", "commit 済みは ✅")
        check(file_status(os.path.join(repo, "dirty.py"))[0] == "🟡", "未追跡は 🟡")
        check(file_status(tmpscript)[0] == "⚠️", "repo の外は ⚠️")
        check(file_status(os.path.join(repo, "gen.sh"))[0] == "❌", "書いたはずで無い file は ❌")
        moved_dir = os.path.join(repo, "moved")
        os.makedirs(moved_dir)
        with open(os.path.join(moved_dir, "renamed.py"), "w") as f:
            f.write("print(1)\n")
        _git(["add", "moved/renamed.py"], repo)
        mark, why = file_status(os.path.join(repo, "old-name", "renamed.py"))
        check(mark == "🔀" and "moved/renamed.py" in why, "folder を改名した file は ❌ でなく 🔀 + 新しい path")
        check(search_saved(unsaved_body, [repo])[0] == "⚠️", "どこにも無い code は ⚠️")
        check(search_saved(saved_body, [repo])[0] == "✅", "commit 済みの file と同じ code は ✅")
        check(inline[1][3] is True, "失敗した実行の印")
        check(touched_repos(calls, root) == [repo], "記録の path から repo を集める")
        rc, bad = report(sid[:8], [Path(t, "projects")], root, False, True)
        check(rc == 0 and bad == 6, "未保存・未 commit の数 = 6 (dirty・scratch・gen.sh・code 3 本)")
        rows = json.loads(_capture(lambda: report(sid[:8], [Path(t, "projects")], root, False, True)))
        check(rows["numbers_not_recorded"] == 2, "記録に無い数値を出した行 = 2 (一部だけ記録にある code・記録に無い script の実行)")
        import shlex

        command = "python3 - <<'PY'\nprint(1)\nPY\npython3 -c 'print(2)'"
        inventory = dict(root='parent', unavailable=[], threads=[
            dict(id='parent', cwd=repo, warnings=[], tools=[],
                 files=[dict(path='kept.py', call='write-one')]),
            dict(id='child', cwd=repo, warnings=[], files=[], tools=[
                dict(tool='Bash', id='exec-one', input=shlex.join(['/bin/zsh', '-lc', command]),
                     exit_code=0)
            ]),
        ])
        inventory_path = Path(t, 'inventory.json')
        inventory_path.write_text(json.dumps(inventory), encoding='utf-8')
        args = ['--inventory', str(inventory_path), '--root', root, '--json']
        candidates = json.loads(_capture(lambda: main(args)))['rows']
        check(len(candidates) == 3 and [r['id'] for r in candidates if r['kind'] == 'inline'] == [
            'inline:child:exec-one:1', 'inline:child:exec-one:2'
        ], 'Codex の子の一行コードも同一呼び出し内で別々に拾う')
        check(all('print(' not in r['what'] for r in candidates), '一覧には会話中のコード本文を出さない')
        dispositions = {r['id']: {'saved': 'proj/kept.py'} for r in candidates}
        missing = candidates[-1]['id']
        del dispositions[missing]
        table = Path(t, 'dispositions.json')
        table.write_text(json.dumps(dispositions), encoding='utf-8')
        result = []
        _capture(lambda: result.append(main(args + ['--check-dispositions', str(table)])))
        check(result == [1], '一件でも未照合なら CLI は失敗する')
        dispositions[missing] = {'excluded': '一度きりの表示確認'}
        table.write_text(json.dumps(dispositions), encoding='utf-8')
        _capture(lambda: result.append(main(args + ['--check-dispositions', str(table)])))
        check(result[-1] == 0, '保存先か除外理由が全件揃えば CLI は成功する')
    print("selftest: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
