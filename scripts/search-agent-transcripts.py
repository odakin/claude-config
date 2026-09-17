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

使い方:
  search-agent-transcripts.py 混ぜる
  search-agent-transcripts.py '重ね(る|て)' --regex --role any --since <YYYY-MM-DD>
  search-agent-transcripts.py 決めた --agent claude --session <session id の先頭> --context 200
  search-agent-transcripts.py --selftest

出力: 1 件ごとに `時刻  agent  session先頭8文字  役割  本文の前後`。 exit 0 (見つからなくても 0)。
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
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.pattern:
        ap.error("pattern が要る")
    hits = search(a.pattern, regex=a.regex, role=a.role, agent=a.agent, since=a.since, until=a.until,
                  session=a.session, context=a.context, include_injected=a.include_injected,
                  claude_dir=Path(a.claude_dir),
                  codex_dir=[Path(os.path.expanduser(d)) for d in (a.codex_dir or DEFAULT_CODEX_DIRS)],
                  limit=a.limit)
    for ts, ag, sid, r, snip in hits:
        print(f"{ts[:19]}  {ag:6}  {sid}  {r:9}  {snip}")
    if not hits:
        print("(このマシンの記録には見つからない)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
