#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subagent-reports.py — ある session が使った agent (subagent) の最終報告を、 会話記録から読み出す。--selftest 内蔵。

用途: agent の最終報告は呼び出した側の context にだけ渡り、 user には見えない。 文脈圧縮のあとや
session の締めの整理 (知見を正本へ移す) で、 委ねた先で分かったことを取りこぼさないために、
記録から報告を引き直す。

読む記録:
  <projects-dir>/<project>/<session id>/subagents/agent-*.jsonl  (Claude Code)
  <projects-dir>/<project>/<session id>/subagents/workflows/<run id>/agent-*.jsonl  (Workflow tool が起こした agent)
  同じ名前の agent-*.meta.json があれば description / agentType を添える。
  報告 = agent が受け渡しの呼び出し (SubagentHandback) で返した本文を**全部、 順に** (再開した agent は再開のたびに
  1 本返す)。 呼び出しが 1 つも無い記録 (古い形) だけ、 最後の assistant 発言の text を報告にする。
  ⚠️ 実測: 受け渡しの呼び出しで返す agent では「最後の text」 は作業途中の一言で、 報告が 2 本とも落ちていた。
  あわせて agent が書いた file (Write / Edit / MultiEdit / NotebookEdit の path) を並べる = 締めの整理で
  「その agent が上げた所」 と照合し、 二重に上げない・上げ漏れを見つけるため。
  ⚠️ agent の「考え中」 は記録に中身が残らない (実測: 40 か所すべて空) = 捨てた案・途中の発見・未検証は、
  委ねる側が spec で「報告か成果物に書け」 と頼んだ分しか後から引けない。

projects-dir の既定 = この機械の全部の設定 dir の projects/ (lib/claude_config_dirs.py):
  - ~/.claude/projects (desktop app の session)
  - 環境変数 CLAUDE_CONFIG_DIR が指す dir の projects/
  - ~/.claude-<名>/projects (アカウント固定の設定 dir = スマホから始めた session・無人 routine)
  --projects-dir を渡すとその dir だけ。 同じ session の写しが 2 つの設定 dir にあれば 1 回 (新しい方)。
  ⚠️ 0 件 = 「その session は agent を使っていない」 か「別のマシンの記録」。 見た dir を出すので読み分ける。

使い方:
  subagent-reports.py <session id か先頭の数文字>       # 既定は環境変数 CLAUDE_CODE_SESSION_ID
  subagent-reports.py abcd1234 --max-chars 2000
  subagent-reports.py abcd1234 --json

OS: macOS / Linux / Windows (Git Bash・PowerShell) で同じに動く (標準 library だけ、 Python 3.8+、 path は pathlib、
出力は UTF-8 に固定 = Windows の cp932 console で絵文字が UnicodeEncodeError にならない)。
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import claude_config_dirs as _ccd
except Exception:  # pragma: no cover - 古い配置
    _ccd = None


def _utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def candidate_projects_dirs(explicit=None):
    if explicit:
        return [Path(explicit).expanduser()]
    if _ccd is not None:
        return [Path(d) for d in _ccd.projects_dirs()]
    dirs = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        dirs.append(Path(env).expanduser() / "projects")
    dirs.append(Path.home() / ".claude" / "projects")
    seen, out = set(), []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


# Workflow tool が起こした agent は subagents/workflows/<run id>/ の下に入る (実測: 直下だけを見て 0 件と出していた)
AGENT_GLOBS = ("subagents/agent-*.jsonl", "subagents/workflows/*/agent-*.jsonl")


def find_agent_files(projects_dirs, session):
    if _ccd is not None:  # 同じ file・同じ session の写しは 1 回
        found = []
        for tail in AGENT_GLOBS:
            pat = "*/" + glob.escape(session) + "*/" + tail
            found.extend(Path(f) for _lab, f in _ccd.transcript_files(pat, roots=[str(d) for d in projects_dirs]))
        return found
    found = []
    for pdir in projects_dirs:
        if not pdir.is_dir():
            continue
        for proj in sorted(pdir.iterdir()):
            if not proj.is_dir():
                continue
            for sdir in sorted(proj.glob(session + "*")):
                sub = sdir / "subagents"
                if sub.is_dir():
                    for tail in AGENT_GLOBS:
                        found.extend(sorted(sub.glob(tail[len("subagents/"):])))
    return found


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def read_report(path):
    """(meta, reports, last timestamp, files written)。 reports = 受け渡しの本文の list (無ければ最後の text 1 本)。
    壊れた行は飛ばす。"""
    meta = {}
    mpath = path.with_name(path.name[:-len(".jsonl")] + ".meta.json")
    if mpath.is_file():
        try:
            meta = json.loads(mpath.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            meta = {}
    last_text, last_ts = "", ""
    handbacks, files = [], []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or '"assistant"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") != "assistant":
                continue
            content = (rec.get("message") or {}).get("content")
            for x in content if isinstance(content, list) else []:
                if not isinstance(x, dict) or x.get("type") != "tool_use":
                    continue
                inp = x.get("input") or {}
                if x.get("name") == "SubagentHandback" and isinstance(inp.get("message"), str):
                    handbacks.append((inp["message"], rec.get("timestamp", "")))
                elif x.get("name") in FILE_TOOLS:
                    p = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(p, str) and p not in files:
                        files.append(p)
            text = _text_of(content)
            if text.strip():
                last_text, last_ts = text, rec.get("timestamp", "")
    if handbacks:
        return meta, [h for h, _ in handbacks], handbacks[-1][1], files
    return meta, ([last_text] if last_text else []), last_ts, files


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="session が使った agent の最終報告を読み出す")
    ap.add_argument("session", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
                    help="session id か先頭の数文字 (既定 = $CLAUDE_CODE_SESSION_ID)")
    ap.add_argument("--projects-dir", default="")
    ap.add_argument("--max-chars", type=int, default=4000, help="1 報告の表示上限 (0 = 全文)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.session:
        ap.error("session id を渡す (または CLAUDE_CODE_SESSION_ID を設定)")
    pdirs = candidate_projects_dirs(args.projects_dir or None)
    files = find_agent_files(pdirs, args.session)
    rows = []
    for f in files:
        meta, reports, ts, written = read_report(f)
        rows.append({"file": str(f), "agentType": meta.get("agentType", ""),
                     "description": meta.get("description", ""), "timestamp": ts,
                     "reports": reports, "report": "\n\n".join(reports), "files_written": written})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    print("見た dir: " + ", ".join(str(d) for d in pdirs))
    print("agent の記録: {} 件 (session {})".format(len(rows), args.session))
    for i, r in enumerate(rows, 1):
        print("\n--- [{}] {} {} {}".format(i, r["agentType"], r["description"], r["timestamp"]).rstrip())
        print("    " + r["file"])
        if not r["reports"]:
            print("(報告なし)")
        for k, body in enumerate(r["reports"], 1):
            if args.max_chars and len(body) > args.max_chars:
                body = body[:args.max_chars] + "\n… (以下略、 --max-chars 0 で全文)"
            if len(r["reports"]) > 1:
                print("  ── 報告 {}/{}".format(k, len(r["reports"])))
            print(body)
        if r["files_written"]:
            print("  書いた file ({}): {}".format(len(r["files_written"]), " / ".join(r["files_written"])))
    return 0


def selftest():
    import io
    import tempfile
    from contextlib import redirect_stdout
    failures = []

    def check(name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)
            if detail:
                print("     " + detail[:800])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "projects"
        sub = root / "-proj" / "abcd1234-0000" / "subagents"
        sub.mkdir(parents=True)
        recs = [
            {"type": "user", "message": {"content": "do it"}},
            {"type": "assistant", "timestamp": "t1", "message": {"content": [{"type": "text", "text": "途中経過"}]}},
            {"type": "assistant", "timestamp": "t2", "message": {"content": [{"type": "text", "text": "最終報告 ✅"}]}},
            {"type": "assistant", "timestamp": "t3", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        ]
        (sub / "agent-x1.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n{broken\n", encoding="utf-8")
        (sub / "agent-x1.meta.json").write_text(json.dumps({"agentType": "opus55", "description": "調べる"}),
                                                encoding="utf-8")
        hb = [
            {"type": "user", "message": {"content": "調べて直して"}},
            {"type": "assistant", "timestamp": "h1", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/r/a.md"}}]}},
            {"type": "assistant", "timestamp": "h2", "message": {"content": [
                {"type": "tool_use", "name": "SubagentHandback", "input": {"message": "報告その 1"}}]}},
            {"type": "user", "message": {"content": "続けて"}},
            {"type": "assistant", "timestamp": "h3", "message": {"content": [{"type": "text", "text": "途中の一言"}]}},
            {"type": "assistant", "timestamp": "h4", "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/r/b.py"}},
                {"type": "tool_use", "name": "SubagentHandback", "input": {"message": "報告その 2"}}]}},
        ]
        (sub / "agent-x2.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in hb) + "\n",
                                            encoding="utf-8")
        other = root / "-proj" / "ffff0000" / "subagents"
        other.mkdir(parents=True)
        (other / "agent-y.jsonl").write_text(json.dumps(recs[2]) + "\n", encoding="utf-8")
        wf = sub / "workflows" / "wf_0001"
        wf.mkdir(parents=True)
        (wf / "agent-w1.jsonl").write_text(json.dumps(recs[2], ensure_ascii=False) + "\n", encoding="utf-8")

        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["abcd", "--projects-dir", str(root), "--json"])
        rows = json.loads(out.getvalue())
        check("prefix で該当 session だけを拾う", rc == 0 and len(rows) == 3, out.getvalue())
        check("Workflow tool の agent (subagents/workflows/<run>/) も拾う",
              any(Path(r["file"]).name == "agent-w1.jsonl" for r in rows), out.getvalue())
        rows_by = {Path(r["file"]).name: r for r in rows}
        r1 = rows_by.get("agent-x1.jsonl", {})
        check("受け渡しの呼び出しが無い記録は、 最後の text 発言を報告にする (tool だけの発言・壊れた行は飛ばす)",
              r1.get("report") == "最終報告 ✅" and r1.get("timestamp") == "t2", out.getvalue())
        r2 = rows_by.get("agent-x2.jsonl", {})
        check("受け渡しの本文を全部、 順に報告にする (途中の一言は報告にしない)",
              r2.get("reports") == ["報告その 1", "報告その 2"] and r2.get("timestamp") == "h4", out.getvalue())
        check("agent が書いた file を並べる", r2.get("files_written") == ["/r/a.md", "/r/b.py"], out.getvalue())
        check("meta の description を添える", r1.get("description") == "調べる", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            main(["zzzz", "--projects-dir", str(root)])
        check("0 件は 0 件と見た dir を出す", "0 件" in out.getvalue() and str(root) in out.getvalue(),
              out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            main(["abcd", "--projects-dir", str(root), "--max-chars", "3"])
        check("--max-chars で切る", "最終報\n… (以下略" in out.getvalue(), out.getvalue())
        if _ccd is not None:  # 既定 = 全部の設定 dir (偽の HOME に既定とアカウント固定の 2 つ)
            home = Path(td) / "home"
            for cfg, sid in ((".claude", "abcd1234-0000"), (".claude-alt", "abcd5678-0000")):
                s = home / cfg / "projects" / "-proj" / sid / "subagents"
                s.mkdir(parents=True)
                (s / "agent-z.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                                                 encoding="utf-8")
            saved = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIRS_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECTS_DIR")}
            try:
                for k in saved:
                    os.environ.pop(k, None)
                os.environ["CLAUDE_CONFIG_DIRS_HOME"] = str(home)
                out = io.StringIO()
                with redirect_stdout(out):
                    main(["abcd", "--json"])
                rows_all = json.loads(out.getvalue())
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            check("既定 = 全部の設定 dir (アカウント固定の dir の session の agent も拾う)",
                  sorted(Path(r["file"]).parts[-6] for r in rows_all) == [".claude", ".claude-alt"], out.getvalue())
    print("\n{}: {} failure(s)".format("FAIL" if failures else "OK", len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
