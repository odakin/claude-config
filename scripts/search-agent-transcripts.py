#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-agent-transcripts.py — Claude Code と Codex の会話記録を横断して、発言を文字列で探す

用途: 「前に決めたはず」「前にこう言ったはず」 と言われたとき、 決定の記録が
repo に無くても、 会話そのものから発言者と時刻を確かめる。 正本 (DESIGN / 台帳) に無い決定を
推測で書き足す前に、 一次記録を引く道具 (規律 = conventions/actor-attribution.md#load-bearing-verify)。

読む記録:
  Claude Code : <claude-dir>/*/*.jsonl  (既定 = この機械の全部の設定フォルダの projects/ = ~/.claude と、
                アカウント固定の ~/.claude-<名> 〔スマホから始めた session・無人 routine〕 と $CLAUDE_CONFIG_DIR。
                列挙と重複の扱い = lib/claude_config_dirs.py の transcript_files。 ~/.claude 以外の session は
                agent の欄が `claude[<名>]`。 --claude-dir を渡すとその dir だけ)
                + その session が使った agent (subagent) の記録 <claude-dir>/*/<session>/subagents/agent-*.jsonl
                  (session id = 親の session。 agent の発言は「assistant(agent)」、 親が agent に渡した指示は role「parent」
                  = `--role user` には入らない。 agent が報告を受け渡しの呼び出し 〔SubagentHandback〕 で返した分も本文として読む。
                  ⚠️ agent の「考え中」 は記録に中身が残らない = 考えたことは報告と成果物に書かれた分しか引けない)
                record の type が user / assistant、 message.content は文字列か
                {type: text, text} の list
                ⚠️ agent が作業している途中に打たれた発話は user の行にならず、 type が attachment で
                attachment.type が queued_command の record (本文は prompt) にだけ残る。 これも user の発話として読む
                (user の行だけを読むと、 途中で足された指示や事実の申告が「言っていない」 に見える = 実測)
  Codex       : <codex-dir>/**/*.jsonl (既定 ~/.codex/sessions と ~/.codex/archived_sessions)
                record の type が response_item、 payload.type が message、
                payload.role が user / assistant / developer、 content は {text} の list
                ⚠️ Codex はアーカイブした session を sessions/YYYY/MM/DD から archived_sessions/ (平置き) へ
                移す。 sessions だけを読むと、 元の発言は見つからず、 別 session に貼られた写しだけが当たる (実測)

既定の挙動:
  - 役割は user だけ (--role any で全部)。 harness が差し込んだ user 側の文
    (system-reminder・command 表示・AGENTS.md 指示・文脈圧縮の要約。 INJECTED_PREFIXES) は除く (--include-injected で含める)
  - 同じ agent・役割・時刻・本文の重複は 1 回だけ出す (Codex の記録は同じ発言を複数回持つことがある)。
    時刻が違えば同じ文面でも別の発言として全部出す (「送って」 を 2 回打てば 2 行)
  - 行を JSON として読む前に、 素の行に対して文字列の有無を先に見る (大きな記録でも速い)。
    行頭・行末に錨を置いた regex (^…$) はこの先読みをせず、 本文だけで照合する
  - 一致が別 session に貼られた会話の抜粋 (`[12] user: …` の形) の中なら、 役割の欄に「(写し)」 を付ける。
    その行の時刻と session は写した側のもので、 発言した側ではない (元の発言は --role any で探し直すか、
    写しの無い行を見る)

--tool-runs (道具の実行を拾う):
  pattern を**道具の呼び出しの入力** (Claude = tool_use の input、 Codex = function_call の arguments / custom_tool_call の input) に当て、
  その呼び出しの**結果の冒頭** (tool_result / function_call_output / custom_tool_call_output) と対にして出す。 用途 = 「その script を
  前にいつ走らせて、 どう終わったか」 (認証切れ・失敗が初めて出た時刻、 成功していた最後の時刻) を RCA で拾う。
  本文の検索と違い、 役割・注入文の絞り込みは使わない。 結果が記録に無い呼び出しは「(結果なし)」。
  code-mode の JavaScript 入力も検索する。内側の tool 実行の成否は外側の完了だけでは決めず、結果を確認する。
  ⚠️ 入力の文字列に当てるので、 script の名前を grep / cat / 編集しただけの呼び出しも当たる (--context で読み分ける)。
  pattern は出力に見える形 (`"command": "…`) で書ける。

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

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import claude_config_dirs as _ccd
except Exception:  # pragma: no cover - 古い配置
    _ccd = None


# harness が user 役で差し込む文の書き出し (system-reminder・command 表示・AGENTS.md 指示・文脈圧縮の要約)
INJECTED_PREFIXES = ("<", "# AGENTS.md", "This session is being continued from a previous conversation")
# 別 session に貼られた会話の抜粋で、 一致の直前に来る話者ラベル (`[12] user: `)
QUOTED_SPEAKER_RE = re.compile(r"\[\d+\]\s*(?:user|assistant)\s*:\s*$")
# 行頭・行末の錨 (^ / $ / \A / \Z / \z)。 [^…] の ^ にも当たるが、 その時は先読みを止めるだけ (結果は同じ)
_ANCHOR_RE = re.compile(r"(?<!\\)[\^$]|\\[AZz]")
DEFAULT_CODEX_DIRS = ("~/.codex/sessions", "~/.codex/archived_sessions")


def _texts_claude(rec: dict) -> tuple[str | None, list[str]]:
    t = rec.get("type")
    if t == "attachment":
        # 作業の途中で打たれた発話。 user の行としては残らず、 この形でしか記録されない
        a = rec.get("attachment")
        if (isinstance(a, dict) and a.get("type") == "queued_command" and isinstance(a.get("prompt"), str)
                and (a.get("origin") or {}).get("kind", "human") == "human"):
            return "user", [a["prompt"]]
        return None, []
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
            elif (isinstance(x, dict) and x.get("type") == "tool_use" and x.get("name") == "SubagentHandback"
                  and isinstance((x.get("input") or {}).get("message"), str)):
                out.append(x["input"]["message"])  # agent が報告を受け渡しの呼び出しで返した分
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
    if path.parent.name == "subagents":
        return path.parent.parent.name  # agent の記録は親 session の id で引く
    return name


def _is_subagent(path: Path) -> bool:
    return path.parent.name == "subagents"


CLAUDE_PATTERNS = ("*/*.jsonl", "*/*/subagents/agent-*.jsonl")


def _claude_files(claude_dir):
    """(path, 設定フォルダの名) の list。 claude_dir = None なら全部の設定フォルダ (名は ~/.claude 以外だけ)、
    dir (1 つか list) を渡されたらその dir だけ (名は付けない)。"""
    if claude_dir is None:
        if _ccd is not None:
            return [(Path(f), "" if lab == "default" else lab) for lab, f in _ccd.transcript_files(CLAUDE_PATTERNS)]
        claude_dir = Path(os.path.expanduser("~/.claude/projects"))
    roots = [Path(d) for d in claude_dir] if isinstance(claude_dir, (list, tuple)) else [Path(claude_dir)]
    out = []
    for root in roots:
        if root.is_dir():
            out += [(f, "") for f in sorted(root.glob(CLAUDE_PATTERNS[0]))]
            out += [(f, "") for f in sorted(root.glob(CLAUDE_PATTERNS[1]))]
    return out


def _agent_shown(ag: str, label: str) -> str:
    return f"{ag}[{label}]" if label else ag


def iter_files(agent: str, claude_dir, codex_dirs):
    """(agent, path, 設定フォルダの名) を出す。 名は ~/.claude 以外の設定フォルダの Claude の記録だけ。"""
    if agent in ("claude", "both"):
        for f, label in _claude_files(claude_dir):
            yield "claude", f, label
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
                    yield "codex", f, ""


def search(pattern: str, *, regex: bool, role: str, agent: str, since: str | None,
           until: str | None, session: str | None, context: int, include_injected: bool,
           claude_dir, codex_dir, limit: int) -> list[tuple]:
    rx = re.compile(pattern) if regex else None
    raw_probe = None if regex else pattern
    # 生の JSON 行での先読みは、 行頭・行末に錨を置いた regex (^…$ / \A / \Z) では本文に当たっても行で外れる
    # (行は {"type": … で始まる) = 錨のある regex は先読みせず、 本文だけで照合する (遅いが落とさない)
    line_rx = rx if rx is not None and not _ANCHOR_RE.search(pattern) else None
    seen: set = set()
    hits: list[tuple] = []
    for ag, f, label in iter_files(agent, claude_dir, codex_dir):
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
                if line_rx is not None and not line_rx.search(line):
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
                sub_agent = ag == "claude" and _is_subagent(f)
                if sub_agent and r == "user":
                    r = "parent"  # 親が agent に渡した指示 (user 本人の発言ではない)
                if r is None or (role != "any" and r != role):
                    continue
                for tx in texts:
                    if r in ("user", "developer") and not include_injected and tx.lstrip().startswith(INJECTED_PREFIXES):
                        continue
                    m = rx.search(tx) if rx is not None else None
                    i = m.start() if m is not None else tx.find(pattern)
                    if i < 0:
                        continue
                    # 同じ record の写し (同じ file の重複行・複数の記録の dir) だけをまとめる。 時刻を鍵に入れないと、
                    # 同じ文面を別の時刻に打った発言 (「送って」「はい」) が最初の 1 回に潰れ、 2 回目の承認が記録に無いように見える (実測)
                    key = (ag, r, ts, tx)
                    if key in seen:
                        continue
                    seen.add(key)
                    j = m.end() if m is not None else i + len(pattern)
                    snip = tx[max(0, i - context): j + context].replace("\n", " ")
                    shown = r + "(写し)" if QUOTED_SPEAKER_RE.search(tx[max(0, i - 40): i]) else r
                    if sub_agent and r == "assistant":
                        shown += "(agent)"
                    hits.append((ts, _agent_shown(ag, label), sid[:8], shown, snip))
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
            if p.get("type") in {"function_call", "custom_tool_call"}:
                field = "input" if p["type"] == "custom_tool_call" else "arguments"
                out.append(("call", p["call_id"], str(p.get(field) or ""), False))
            elif p.get("type") in {"function_call_output", "custom_tool_call_output"}:
                body = p.get("output")
                if isinstance(body, dict):
                    body = body.get("output") or json.dumps(body, ensure_ascii=False)
                if isinstance(body, list):
                    body = " ".join(x["text"] for x in body if isinstance(x, dict) and isinstance(x.get("text"), str))
                out.append(("result", p["call_id"], str(body or ""), False))
    return out


def _spaced(line: str) -> str:
    """生の記録の行を、 本番の照合と表示の形 (json.dumps の `"key": "value", "k2"`) に寄せる。 下読み専用 = 当たりすぎても parse が増えるだけ。"""
    return line.replace('":', '": ').replace(',"', ', "')


def tool_runs(pattern: str, *, regex: bool, agent: str, since: str | None, until: str | None,
              session: str | None, context: int, claude_dir, codex_dir, limit: int) -> list[tuple]:
    """道具の呼び出しの入力に pattern が当たるものを、 結果の冒頭と対にして返す。"""
    rx = re.compile(pattern) if regex else None
    # 下読みは生の行に当てる。 生の行は区切りの空白なしの JSON、 本番の照合と表示は空白ありの形。 pattern がその空白を含むなら
    # 下読みも同じ形で当てる (実測: 出力のまま `"command": "…` と書いた pattern が下読みで全部落ち、 黙って 0 件を返した)
    spaced = '": ' in pattern or ', "' in pattern
    runs: list[tuple] = []
    for ag, f, label in iter_files(agent, claude_dir, codex_dir):
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
                if not hit and spaced:
                    wide = _spaced(line)
                    hit = rx.search(wide) if rx is not None else pattern in wide
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
                        runs.append((t0, _agent_shown(ag, label), sid[:8], "run(error)" if is_err else "run", f"{snip} → {head}"))
        for t0, snip in pending.values():
            runs.append((t0, _agent_shown(ag, label), sid[:8], "run", f"{snip} → (結果なし)"))
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
            {"type": "user", "timestamp": "2099-01-03T00:05:00Z", "message": {"content": "みかんの話"}},
        ]) + "\n", encoding="utf-8")
        sa = cl / "aaaaaaaa-1111" / "subagents"
        sa.mkdir(parents=True)
        (sa / "agent-zz.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
            {"type": "user", "timestamp": "2099-01-06T00:00:00Z", "message": {"content": "メロンを調べて"}},
            {"type": "assistant", "timestamp": "2099-01-06T00:00:01Z", "message": {"content": [
                {"type": "tool_use", "name": "SubagentHandback", "input": {"message": "メロンは緑だった (報告)"}}]}},
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
            check("agent の記録も読む: 受け渡しの報告が assistant(agent) で、 親の session id で出る",
                  [(x[2], x[3]) for x in search("メロン", **{**base, "role": "assistant", "session": "aaaa"})] == [("aaaaaaaa", "assistant(agent)")]),
            check("親が agent に渡した指示は --role user に入らない (role = parent)",
                  search("メロン", **base) == [] and [x[3] for x in search("メロン", **{**base, "role": "parent"})] == ["parent"]),
            check("同じ文面を別の時刻に打った発言は 2 件とも出る (最初の 1 回に潰さない)",
                  [x[0] for x in search("みかんの話", **{**base, "agent": "claude"})]
                  == ["2099-01-03T00:00:00Z", "2099-01-03T00:05:00Z"]),
            check("行頭・行末に錨を置いた --regex も本文に当たる",
                  len(search("^みかんの話$", **{**base, "agent": "claude", "regex": True})) == 2),
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
        # 作業の途中で打たれた発話 (queued_command) は user の行にならない
        mid = Path(td) / "claude-mid" / "proj"
        mid.mkdir(parents=True)
        (mid / "cccccccc-3333.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
            {"type": "user", "timestamp": "2099-03-01T00:00:00Z", "message": {"content": "資料を作って"}},
            {"type": "queue-operation", "operation": "enqueue", "timestamp": "2099-03-01T00:01:00Z", "content": "柿は渋いと聞いた"},
            {"type": "attachment", "timestamp": "2099-03-01T00:01:00Z",
             "attachment": {"type": "queued_command", "prompt": "柿は渋いと聞いた", "origin": {"kind": "human"}}},
            {"type": "attachment", "timestamp": "2099-03-01T00:02:00Z",
             "attachment": {"type": "queued_command", "prompt": "柿の通知", "origin": {"kind": "task-notification"}}},
            {"type": "attachment", "timestamp": "2099-03-01T00:03:00Z", "attachment": {"type": "skill_listing", "content": "柿"}},
        ]) + "\n", encoding="utf-8")
        hm = search("柿", **{**base, "agent": "claude", "claude_dir": Path(td) / "claude-mid"})
        results += [
            check("作業の途中で打たれた発話 (queued_command) を user の発話として拾う",
                  [(x[3], x[4]) for x in hm] == [("user", "柿は渋いと聞いた")]),
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
        # 本物の記録の形 = 区切りの空白なしの JSON (上の fixture は json.dumps の既定の形なので、 この形の下読みを通らない)
        compact = Path(td) / "claude-compact" / "proj"
        compact.mkdir(parents=True)
        (compact / "dddddddd-4444.jsonl").write_text(json.dumps(
            {"type": "assistant", "timestamp": "2099-03-01T00:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "t9", "name": "Bash", "input": {"command": "python3 fruit-client.py pick", "description": "x"}}]}},
            ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        ctb = {**tb, "agent": "claude", "claude_dir": Path(td) / "claude-compact"}
        results += [
            check("--tool-runs: 空白なしの記録に、 出力の形の regex が当たる", len(tool_runs(r'"command": "[^"]*fruit-client', **{**ctb, "regex": True})) == 1),
            check("--tool-runs: 空白なしの記録に、 出力の形の literal が当たる", len(tool_runs('"command": "python3 fruit', **ctb)) == 1),
            check("--tool-runs: 項目をまたぐ出力の形も当たる", len(tool_runs(r'pick", "description"', **{**ctb, "regex": True})) == 1),
            check("--tool-runs: 空白なしの記録で、 当たらない pattern は 0 件のまま", tool_runs(r'"command": "[^"]*no-such-tool', **{**ctb, "regex": True}) == []),
        ]
        # Code-mode tools use custom_tool_call/input, not function_call/arguments.
        custom = cxt / "rollout-2099-02-05T00-00-00-00000000-0000-4000-8000-0000000c0de3.jsonl"
        custom.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
            {"type":"response_item", "timestamp":"2099-02-05T00:00:00Z", "payload":
             {"type":"custom_tool_call", "name":"exec", "call_id":"custom-one",
              "input":"text(await tools.exec_command({cmd: 'python3 fruit-probe.py'}));"}},
            {"type":"response_item", "timestamp":"2099-02-05T00:00:01Z", "payload":
             {"type":"custom_tool_call_output", "call_id":"custom-one",
              "output":[{"type":"input_text","text":"probe received"}]}},
            {"type":"response_item", "timestamp":"2099-02-05T00:00:02Z", "payload":
             {"type":"custom_tool_call", "name":"exec", "call_id":"custom-pending",
              "input":"text(await tools.exec_command({cmd: 'python3 fruit-probe.py --pending'}));"}},
        ])+"\n", encoding="utf-8")
        cr = tool_runs("fruit-probe.py", **{**tb, "agent":"codex", "session":"00000000-0000-4000-8000-0000000c0de3"})
        results += [
            check("--tool-runs: code-mode custom call と text list の結果を結ぶ",
                  len(cr) == 2 and "probe received" in cr[0][4]),
            check("--tool-runs: code-mode の結果未着も消さない",
                  len(cr) == 2 and "(結果なし)" in cr[1][4]),
            check("--tool-runs: code-mode も session で絞る",
                  tool_runs("fruit-probe.py", **{**tb,"session":"unrelated"}) == []),
        ]
        # 既定 (claude_dir=None) = この機械の全部の設定フォルダ。 偽の HOME に既定とアカウント固定の 2 つを置く
        if _ccd is not None:
            home = Path(td) / "home"
            for cfg, sid, text in ((".claude", "dddddddd-0001", "梨は既定の設定フォルダ"),
                                   (".claude-alt", "eeeeeeee-0002", "梨はスマホから始めた session"),
                                   (".claude-alt", "dddddddd-0001", "梨は既定の設定フォルダ")):  # 同じ session の写し
                d = home / cfg / "projects" / "-w"
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{sid}.jsonl").write_text(json.dumps(
                    {"type": "user", "timestamp": "2099-02-01T00:00:00Z", "message": {"content": text}}, ensure_ascii=False) + "\n",
                    encoding="utf-8")
            os.utime(home / ".claude-alt" / "projects" / "-w" / "dddddddd-0001.jsonl", (1000, 1000))  # 止まった写し = 古い
            saved = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIRS_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECTS_DIR")}
            try:
                for k in saved:
                    os.environ.pop(k, None)
                os.environ["CLAUDE_CONFIG_DIRS_HOME"] = str(home)
                hd = search("梨は", **{**base, "agent": "claude", "claude_dir": None})
                td_runs = tool_runs("梨", **{**tb, "agent": "claude", "claude_dir": None})
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            results += [
                check("既定 = 全部の設定フォルダ。 ~/.claude 以外は agent の欄に名", sorted(x[1] for x in hd) == ["claude", "claude[alt]"]),
                check("既定: 同じ session が 2 つの設定フォルダにあっても 1 回", sorted(x[2] for x in hd) == ["dddddddd", "eeeeeeee"]),
                check("既定: --tool-runs も同じ列挙を通る (呼び出しが無ければ空)", td_runs == []),
            ]
    print(f"{ok}/{len(results)} PASS")
    return 0 if all(results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Claude Code と Codex の会話記録を横断して発言を探す")
    ap.add_argument("pattern", nargs="?")
    ap.add_argument("--regex", action="store_true", help="pattern を正規表現として扱う")
    ap.add_argument("--role", default="user", choices=["user", "assistant", "developer", "parent", "any"])
    ap.add_argument("--agent", default="both", choices=["claude", "codex", "both"])
    ap.add_argument("--since", help="YYYY-MM-DD (この日を含む)")
    ap.add_argument("--until", help="YYYY-MM-DD (この日を含む)")
    ap.add_argument("--session", help="session id の先頭 (Claude は file 名、 Codex は末尾の uuid)")
    ap.add_argument("--context", type=int, default=120, help="一致の前後に出す文字数")
    ap.add_argument("--include-injected", action="store_true", help="harness が差し込んだ user 側の文も含める")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--claude-dir", action="append",
                    help="Claude Code の記録の dir (繰り返し可。 既定 = この機械の全部の設定フォルダの projects/)")
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
    claude_dirs = [Path(os.path.expanduser(d)) for d in a.claude_dir] if a.claude_dir else None
    if a.tool_runs:
        hits = tool_runs(a.pattern, regex=a.regex, agent=a.agent, since=a.since, until=a.until,
                         session=a.session, context=a.context, claude_dir=claude_dirs,
                         codex_dir=codex_dirs, limit=a.limit)
    else:
        hits = search(a.pattern, regex=a.regex, role=a.role, agent=a.agent, since=a.since, until=a.until,
                      session=a.session, context=a.context, include_injected=a.include_injected,
                      claude_dir=claude_dirs, codex_dir=codex_dirs, limit=a.limit)
    for ts, ag, sid, r, snip in hits:
        print(f"{ts[:19]}  {ag:6}  {sid}  {r:9}  {snip}")
    if not hits:
        print("(このマシンの記録には見つからない)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
