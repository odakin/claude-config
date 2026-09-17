#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-agent-transcripts.py — Claude Code と Codex の会話記録を横断して、発言を文字列で探す

用途: 「前に決めたはず」「前にこう言ったはず」 と言われたとき、 決定の記録が
repo に無くても、 会話そのものから発言者と時刻を確かめる。 正本 (DESIGN / 台帳) に無い決定を
推測で書き足す前に、 一次記録を引く道具 (規律 = conventions/actor-attribution.md#load-bearing-verify)。

読む記録:
  Claude Code : <claude-dir>/*/*.jsonl  (既定 ~/.claude/projects)
                record の type が user / assistant、 message.content は文字列か
                {type: text, text} の list
  Codex       : <codex-dir>/**/*.jsonl (既定 ~/.codex/sessions と ~/.codex/archived_sessions)
                record の type が response_item、 payload.type が message、
                payload.role が user / assistant / developer、 content は {text} の list
                ⚠️ Codex はアーカイブした session を sessions/YYYY/MM/DD から archived_sessions/ (平置き) へ
                移す。 sessions だけを読むと、 元の発言は見つからず、 別 session に貼られた写しだけが当たる (実測)

既定の挙動:
  - 役割は user だけ (--role any で全部)。 harness が差し込んだ user 側の文
    (system-reminder・command 表示・AGENTS.md 指示・文脈圧縮の要約。 INJECTED_PREFIXES) は除く (--include-injected で含める)
  - 同じ agent・役割・本文の重複は 1 回だけ出す (Codex の記録は同じ発言を複数回持つことがある)
  - 行を JSON として読む前に、 素の行に対して文字列の有無を先に見る (大きな記録でも速い)
  - 一致が別 session に貼られた会話の抜粋 (`[12] user: …` の形) の中なら、 役割の欄に「(写し)」 を付ける。
    その行の時刻と session は写した側のもので、 発言した側ではない (元の発言は --role any で探し直すか、
    写しの無い行を見る)

--tool-runs (道具の実行を拾う):
  pattern を**道具の呼び出しの入力** (Claude = tool_use の input、 Codex = function_call の arguments) に当て、
  その呼び出しの**結果の冒頭** (tool_result / function_call_output) と対にして出す。 用途 = 「その script を
  前にいつ走らせて、 どう終わったか」 (認証切れ・失敗が初めて出た時刻、 成功していた最後の時刻) を RCA で拾う。
  本文の検索と違い、 役割・注入文の絞り込みは使わない。 結果が記録に無い呼び出しは「(結果なし)」。
  ⚠️ 入力の文字列に当てるので、 script の名前を grep / cat / 編集しただけの呼び出しも当たる (--context で読み分ける)。

使い方:
  search-agent-transcripts.py 混ぜる
  search-agent-transcripts.py '重ね(る|て)' --regex --role any --since <YYYY-MM-DD>
  search-agent-transcripts.py 決めた --agent claude --session <session id の先頭> --context 200
  search-agent-transcripts.py --tool-runs 'some-client\\.py (search|get)' --regex --since <YYYY-MM-DD>
  search-agent-transcripts.py --selftest

出力: 1 件ごとに `時刻  agent  session先頭8文字  役割  本文の前後`。 --tool-runs は役割の欄が `run` / `run(error)` で、
本文の後に ` → 結果の冒頭`。 exit 0 (見つからなくても 0)。
⚠️ 射程: 手元のマシンにある記録だけ。 別のマシンで開いた session・消えた記録・claude.ai の会話は見えない
   (0 件は「このマシンの記録に無い」 であって「言っていない」 ではない)。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


# harness が user 役で差し込む文の書き出し (system-reminder・command 表示・AGENTS.md 指示・文脈圧縮の要約)
INJECTED_PREFIXES = ("<", "# AGENTS.md", "This session is being continued from a previous conversation")
# 別 session に貼られた会話の抜粋で、 一致の直前に来る話者ラベル (`[12] user: `)
QUOTED_SPEAKER_RE = re.compile(r"\[\d+\]\s*(?:user|assistant)\s*:\s*$")
DEFAULT_CODEX_DIRS = ("~/.codex/sessions", "~/.codex/archived_sessions")


def _texts_claude(rec: dict) -> tuple[str | None, list[str]]:
    t = rec.get("type")
    if t not in ("user", "assistant"):
        return None, []
    c = (rec.get("message") or {}).get("content")
    if isinstance(c, str):
        return t, [c]
    out = []
    if isinstance(c, list):
        for x in c:
            if isinstance(x, dict) and x.get("type") == "text" and isinstance(x.get("text"), str):
                out.append(x["text"])
    return t, out


def _texts_codex(rec: dict) -> tuple[str | None, list[str]]:
    if rec.get("type") != "response_item":
        return None, []
    p = rec.get("payload")
    if not isinstance(p, dict) or p.get("type") != "message":
        return None, []
    out = []
    for x in p.get("content") or []:
        if isinstance(x, dict) and isinstance(x.get("text"), str):
            out.append(x["text"])
    return p.get("role"), out


def _session_of(path: Path, agent: str) -> str:
    name = path.stem
    if agent == "codex":
        m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", name)
        return m.group(1) if m else name
    return name


def iter_files(agent: str, claude_dir: Path, codex_dirs):
    if agent in ("claude", "both") and claude_dir.is_dir():
        for f in sorted(claude_dir.glob("*/*.jsonl")):
            yield "claude", f
    if agent in ("codex", "both"):
        if isinstance(codex_dirs, (str, Path)):
            codex_dirs = [codex_dirs]
        seen: set = set()
        for d in codex_dirs:
            d = Path(d)
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("*.jsonl")):
                if f.resolve() not in seen:
                    seen.add(f.resolve())
                    yield "codex", f


def search(pattern: str, *, regex: bool, role: str, agent: str, since: str | None,
           until: str | None, session: str | None, context: int, include_injected: bool,
           claude_dir: Path, codex_dir, limit: int) -> list[tuple]:
    rx = re.compile(pattern) if regex else None
    raw_probe = None if regex else pattern
    seen: set = set()
    hits: list[tuple] = []
    for ag, f in iter_files(agent, claude_dir, codex_dir):
        sid = _session_of(f, ag)
        if session and not sid.startswith(session):
            continue
        try:
            fh = open(f, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if raw_probe is not None and raw_probe not in line:
                    continue
                if rx is not None and not rx.search(line):
                    # 本文の改行は JSON では \n なので、 行単位の先読みで落ちる match はない
                    # (改行をまたぐ regex は対象外)
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ts = rec.get("timestamp") or ""
                if since and ts[:10] < since:
                    continue
                if until and ts[:10] > until:
                    continue
                r, texts = (_texts_claude if ag == "claude" else _texts_codex)(rec)
                if r is None or (role != "any" and r != role):
                    continue
                for tx in texts:
                    if r in ("user", "developer") and not include_injected and tx.lstrip().startswith(INJECTED_PREFIXES):
                        continue
                    m = rx.search(tx) if rx is not None else None
                    i = m.start() if m is not None else tx.find(pattern)
                    if i < 0:
                        continue
                    key = (ag, r, tx)
                    if key in seen:
                        continue
                    seen.add(key)
                    j = m.end() if m is not None else i + len(pattern)
                    snip = tx[max(0, i - context): j + context].replace("\n", " ")
                    shown = r + "(写し)" if QUOTED_SPEAKER_RE.search(tx[max(0, i - 40): i]) else r
                    hits.append((ts, ag, sid[:8], shown, snip))
    hits.sort()
    return hits[:limit] if limit else hits


def _tool_items(agent: str, rec: dict):
    """1 record から (種別 call|result, id, 文字列, error か) を取り出す。 会話の本文は対象外。"""
    out = []
    if agent == "claude":
        c = (rec.get("message") or {}).get("content")
        if not isinstance(c, list):
            return out
        for x in c:
            if not isinstance(x, dict):
                continue
            if x.get("type") == "tool_use" and x.get("id"):
                out.append(("call", x["id"], json.dumps(x.get("input"), ensure_ascii=False), False))
            elif x.get("type") == "tool_result" and x.get("tool_use_id"):
                body = x.get("content")
                if isinstance(body, list):
                    body = " ".join(y.get("text", "") for y in body if isinstance(y, dict))
                out.append(("result", x["tool_use_id"], body if isinstance(body, str) else "", bool(x.get("is_error"))))
    elif rec.get("type") == "response_item":
        p = rec.get("payload")
        if isinstance(p, dict) and p.get("call_id"):
            if p.get("type") == "function_call":
                out.append(("call", p["call_id"], str(p.get("arguments") or ""), False))
            elif p.get("type") == "function_call_output":
                body = p.get("output")
                if isinstance(body, dict):
                    body = body.get("output") or json.dumps(body, ensure_ascii=False)
                out.append(("result", p["call_id"], str(body or ""), False))
    return out


def tool_runs(pattern: str, *, regex: bool, agent: str, since: str | None, until: str | None,
              session: str | None, context: int, claude_dir: Path, codex_dir, limit: int) -> list[tuple]:
    """道具の呼び出しの入力に pattern が当たるものを、 結果の冒頭と対にして返す。"""
    rx = re.compile(pattern) if regex else None
    runs: list[tuple] = []
    for ag, f in iter_files(agent, claude_dir, codex_dir):
        sid = _session_of(f, ag)
        if session and not sid.startswith(session):
            continue
        pending: dict = {}
        try:
            fh = open(f, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                hit = rx.search(line) if rx is not None else pattern in line
                if not hit and not (pending and any(k in line for k in pending)):
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ts = rec.get("timestamp") or ""
                for kind, cid, text, is_err in _tool_items(ag, rec):
                    if kind == "call":
                        if (since and ts[:10] < since) or (until and ts[:10] > until):
                            continue
                        m = rx.search(text) if rx is not None else None
                        i = m.start() if m is not None else text.find(pattern)
                        if i < 0:
                            continue
                        j = m.end() if m is not None else i + len(pattern)
                        pending[cid] = (ts, text[max(0, i - context): j + context].replace("\n", " "))
                    elif cid in pending:
                        t0, snip = pending.pop(cid)
                        head = re.sub(r"\s+", " ", text).strip()[: max(context, 60)]
                        runs.append((t0, ag, sid[:8], "run(error)" if is_err else "run", f"{snip} → {head}"))
        for t0, snip in pending.values():
            runs.append((t0, ag, sid[:8], "run", f"{snip} → (結果なし)"))
    runs.sort()
    return runs[:limit] if limit else runs


def selftest() -> int:
    ok = 0
    with tempfile.TemporaryDirectory() as td:
        cl = Path(td) / "claude" / "proj"
        cx = Path(td) / "codex" / "2099" / "01" / "02"
        cl.mkdir(parents=True)
        cx.mkdir(parents=True)
        (cl / "aaaaaaaa-1111.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
            {"type": "user", "timestamp": "2099-01-01T00:00:00Z", "message": {"content": "りんごは赤にしよう"}},
            {"type": "user", "timestamp": "2099-01-01T00:00:01Z", "message": {"content": "<system-reminder>りんご</system-reminder>"}},
            {"type": "assistant", "timestamp": "2099-01-01T00:00:02Z", "message": {"content": [{"type": "text", "text": "りんごは赤で記録します"}]}},
            {"type": "user", "timestamp": "2099-01-03T00:00:00Z", "message": {"content": "みかんの話"}},
        ]) + "\n", encoding="utf-8")
        codex_msg = {"type": "response_item", "timestamp": "2099-01-02T00:00:00Z",
                     "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "りんごは青では"}]}}
        (cx / "rollout-2099-01-02T00-00-00-00000000-0000-4000-8000-00000000c0de.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in [codex_msg, codex_msg,
                      {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "りんご"}}]) + "\n",
            encoding="utf-8")
        base = dict(regex=False, role="user", agent="both", since=None, until=None, session=None,
                    context=10, include_injected=False, claude_dir=Path(td) / "claude",
                    codex_dir=Path(td) / "codex", limit=0)

        def check(name, cond):
            nonlocal ok
            print(("PASS " if cond else "FAIL ") + name)
            ok += bool(cond)
            return cond

        h = search("りんご", **base)
        results = [
            check("user だけ・注入文は除く・Codex の重複は 1 回", [x[1] for x in h] == ["claude", "codex"]),
            check("Codex の session id を file 名から取る", h[1][2] == "00000000"),
            check("--role any で assistant も出る", len(search("りんご", **{**base, "role": "any"})) == 3),
            check("--include-injected で注入文も出る", len(search("りんご", **{**base, "include_injected": True})) == 3),
            check("--since で日付を絞る", [x[1] for x in search("りんご", **{**base, "since": "2099-01-02"})] == ["codex"]),
            check("--agent claude", [x[1] for x in search("りんご", **{**base, "agent": "claude"})] == ["claude"]),
            check("--regex", len(search("りんごは(赤|青)", **{**base, "regex": True})) == 2),
            check("--session で session を絞る", [x[2] for x in search("りんご", **{**base, "session": "aaaa"})] == ["aaaaaaaa"]),
            check("event_msg など会話でない record は読まない", all("task" not in x[4] for x in search("りんご", **{**base, "role": "any"}))),
        ]
        # アーカイブされた Codex session (平置き) と、 別 session に貼られた会話の抜粋
        arch = Path(td) / "codex-archived"
        arch.mkdir()
        (arch / "rollout-2099-01-04T00-00-00-00000000-0000-4000-8000-0000000a4c4d.jsonl").write_text(json.dumps(
            {"type": "response_item", "timestamp": "2099-01-04T00:00:00Z",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "ぶどうは紫"}]}},
            ensure_ascii=False) + "\n", encoding="utf-8")
        (cx / "rollout-2099-01-05T00-00-00-00000000-0000-4000-8000-00000000c0b1.jsonl").write_text(json.dumps(
            {"type": "response_item", "timestamp": "2099-01-05T00:00:00Z",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "前の会話:\n[3] user: ぶどうは紫\n[4] assistant: はい"}]}},
            ensure_ascii=False) + "\n", encoding="utf-8")
        two = {**base, "codex_dir": [Path(td) / "codex", arch]}
        hb = search("ぶどうは紫", **{**base, "agent": "codex"})
        hb2 = search("ぶどうは紫", **{**two, "agent": "codex"})
        results += [
            check("sessions だけだと元の発言は無く写しだけが当たる", [x[3] for x in hb] == ["user(写し)"]),
            check("archived も読むと元の発言 (写しの印なし) が出る", [x[3] for x in hb2] == ["user", "user(写し)"]),
            check("写しでない一致には印が付かない", all("写し" not in x[3] for x in search("りんご", **base))),
        ]
        # --tool-runs: 呼び出しと結果の対 (Claude の tool_use / tool_result、 Codex の function_call / output)
        tl = Path(td) / "claude-tools" / "proj"
        tl.mkdir(parents=True)
        (tl / "bbbbbbbb-2222.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
            {"type": "assistant", "timestamp": "2099-02-01T00:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "python3 fruit-client.py search 梨"}}]}},
            {"type": "user", "timestamp": "2099-02-01T00:00:01Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "session 切れ\n再 login", "is_error": True}]}},
            {"type": "assistant", "timestamp": "2099-02-02T00:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "python3 fruit-client.py search 桃"}}]}},
            {"type": "user", "timestamp": "2099-02-02T00:00:01Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "# 3 docs"}]}]}},
            {"type": "assistant", "timestamp": "2099-02-03T00:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "python3 fruit-client.py get /x"}}]}},
        ]) + "\n", encoding="utf-8")
        cxt = Path(td) / "codex-tools"
        cxt.mkdir()
        (cxt / "rollout-2099-02-04T00-00-00-00000000-0000-4000-8000-0000000c0de2.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
            {"type": "response_item", "timestamp": "2099-02-04T00:00:00Z",
             "payload": {"type": "function_call", "name": "shell", "call_id": "c1", "arguments": "{\"cmd\": \"python3 fruit-client.py search 柿\"}"}},
            {"type": "response_item", "timestamp": "2099-02-04T00:00:02Z",
             "payload": {"type": "function_call_output", "call_id": "c1", "output": "# 1 docs"}},
        ]) + "\n", encoding="utf-8")
        tb = dict(regex=False, agent="both", since=None, until=None, session=None, context=20,
                  claude_dir=Path(td) / "claude-tools", codex_dir=[cxt], limit=0)
        tr = tool_runs("fruit-client.py", **tb)
        results += [
            check("--tool-runs: 呼び出しと結果を対にする (Claude 3 件 + Codex 1 件)", len(tr) == 4),
            check("--tool-runs: error の結果に印", tr[0][3] == "run(error)" and "session 切れ 再 login" in tr[0][4]),
            check("--tool-runs: list 形の結果も読む", "# 3 docs" in tr[1][4]),
            check("--tool-runs: 結果の無い呼び出しは (結果なし)", "(結果なし)" in tr[2][4]),
            check("--tool-runs: Codex の function_call も拾う", tr[3][1] == "codex" and "# 1 docs" in tr[3][4]),
            check("--tool-runs: --regex と --since", len(tool_runs(r"fruit-client\.py search", **{**tb, "regex": True, "since": "2099-02-02"})) == 2),
            check("--tool-runs: 本文の検索は道具の入力を拾わない", search("fruit-client", **{**base, "role": "any", "claude_dir": Path(td) / "claude-tools", "agent": "claude"}) == []),
        ]
    print(f"{ok}/{len(results)} PASS")
    return 0 if all(results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Claude Code と Codex の会話記録を横断して発言を探す")
    ap.add_argument("pattern", nargs="?")
    ap.add_argument("--regex", action="store_true", help="pattern を正規表現として扱う")
    ap.add_argument("--role", default="user", choices=["user", "assistant", "developer", "any"])
    ap.add_argument("--agent", default="both", choices=["claude", "codex", "both"])
    ap.add_argument("--since", help="YYYY-MM-DD (この日を含む)")
    ap.add_argument("--until", help="YYYY-MM-DD (この日を含む)")
    ap.add_argument("--session", help="session id の先頭 (Claude は file 名、 Codex は末尾の uuid)")
    ap.add_argument("--context", type=int, default=120, help="一致の前後に出す文字数")
    ap.add_argument("--include-injected", action="store_true", help="harness が差し込んだ user 側の文も含める")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--claude-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--codex-dir", action="append",
                    help="Codex の記録の dir (繰り返し可。 既定 = ~/.codex/sessions と ~/.codex/archived_sessions)")
    ap.add_argument("--tool-runs", action="store_true",
                    help="pattern を道具の呼び出しの入力に当て、 結果の冒頭と対にして出す (RCA で実行時刻と成否を拾う)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.pattern:
        ap.error("pattern が要る")
    codex_dirs = [Path(os.path.expanduser(d)) for d in (a.codex_dir or DEFAULT_CODEX_DIRS)]
    if a.tool_runs:
        hits = tool_runs(a.pattern, regex=a.regex, agent=a.agent, since=a.since, until=a.until,
                         session=a.session, context=a.context, claude_dir=Path(a.claude_dir),
                         codex_dir=codex_dirs, limit=a.limit)
    else:
        hits = search(a.pattern, regex=a.regex, role=a.role, agent=a.agent, since=a.since, until=a.until,
                      session=a.session, context=a.context, include_injected=a.include_injected,
                      claude_dir=Path(a.claude_dir), codex_dir=codex_dirs, limit=a.limit)
    for ts, ag, sid, r, snip in hits:
        print(f"{ts[:19]}  {ag:6}  {sid}  {r:9}  {snip}")
    if not hits:
        print("(このマシンの記録には見つからない)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
