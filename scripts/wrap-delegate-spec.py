#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wrap-delegate-spec.py — ある session の締めを別の worker に渡す依頼書の骨を作る (closing-sweep.md#delegated-sweep の 3 つを埋める)。 受け取りの直後の照合の部品も持つ。--selftest 内蔵。

なぜ (実測): 締めを worker に渡す依頼書を、 渡す側 (指揮役) が自分の記憶と語で書くと、 #delegated-sweep の形 (対象の session の
  完全な id・既に済んだもの・触らせない file) が抜ける。 渡す形は closing-sweep.md の中からしか辿れず、 締めの頼みが wrap の語で
  来なかったとき (wrap の語を含まない普通の語の頼み) は skill が起動せず、 その文書に届かなかった。 記憶から挙げた
  「移すもの」 の一覧で渡した worker は会話記録を読まず、 引き継ぎの「見ていない: 会話記録」 を依頼元はすぐに受け取った。
  文脈圧縮の後は、 要約が道具の名と答えを一般の語・「済み」 の札に畳むので、 記憶から書く依頼書はさらに崩れる。
  この道具は依頼書の骨を記録から作る = 渡す側は語を選ばない。

使い方:
  wrap-delegate-spec.py <締める session の id か先頭 8 字> [--quote '<本人の頼み (逐語)>'] [--out <file>]
      骨を出す (--out が無ければ stdout)。 埋めるもの = 対象の session の完全な id・記録の path・大きさ・文脈圧縮の回数、
      0.3・0.5 の道具をその id で回す行、 その session の commit と、 その session が起こした子 session の wrap の記録と commit
      (= 既に上がったもの、 二重に上げない)、 依頼元が自分の窓で回す `session-reply-knowledge-report.py <id8> --delegated --check
      <file>` の 1 行、 触らせない file の欄、 提出に書くこと。 本人の頼みは --quote で逐語を入れる (無ければ空欄 = 依頼元が貼る)。
      骨の 1 行目の印 (`<!-- wrap-delegate-spec target=<id> -->`) で、 受け取りの照合がこの依頼を締めの委任と読む。
  wrap-delegate-spec.py --selftest

受け取りの照合の部品 (child-wrap-check.py --hook-accept が `board.py accept` の直後に呼ぶ):
  accept_lines(request_id, events, read_paths) = 出す行の list:
    - 受け取った依頼の依頼書 (request の references)・提出の file (submit の deliverables)・この turn に読んだ file
      (read_paths = 中身の見えない依頼は references を持たないので、 worker が引き継ぎに写した印を読む) のどれかに上の印が
      あれば、 「この turn に依頼元の `--check` を回す」 の 1 行 (行頭の印 `🧾 wrap-delegate: target=<id8>` を締めの Stop hook =
      session-reply-knowledge-report.py が読み、 その turn で対象の id の --check が通るまで 1 回差し戻す)
    - 同じ受け取りで、 提出・読んだ file の「見ていない・確かめていない」 の行と、 依頼書の本人の逐語の範囲と照らす 1 行。
      印の無い依頼には出さない (どの受け取りにも出すと、 過去の受け取りの多くで出た = 壁紙になる、 実測)
限界: 依頼書の path は project の repo から読み、 無ければ作業ルート (~/Claude) から読む。 path の書き方がどちらでもない依頼書は
  読めない (印も「見ていない」 の行も出ない)。 「見ていない」 の語は語の list で拾う = 言い換えは拾わない。
env (test): WRAP_DELEGATE_BASE (作業ルート、 既定 ~/Claude)
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "<!-- wrap-delegate-spec target="
MARK_RE = re.compile(r"<!-- wrap-delegate-spec target=([0-9a-f]{8}(?:-[0-9a-f-]{27})?)")
ACCEPT_MARK = "🧾 wrap-delegate: target="  # session-reply-knowledge-report.py の Stop が読む印 (変えるときは両方)
NOT_SEEN = re.compile(r"見ていない|見なかった|読んでいない|確かめていない|確認していない|照らしていない|未確認|未検証|未照合"
                      r"|not\s+(?:yet\s+)?(?:verified|checked|seen|read|swept)|NOT\s+sweep", re.I)
# the person's words in a spec: the skeleton's section (its first quoted line), else a 「…」 right after 本人 / owner
QUOTE_SECTION = re.compile(r"^##\s*本人の頼み[^\n]*\n(?:\s*\n)*>\s*(?!〔)([^\n]{4,200})", re.M)
QUOTE_LINE = re.compile(r"(?:本人|owner)[^\n「」]{0,20}「([^「」\n]{4,200})」")
MAX_NOT_SEEN = 8
REPLY_CHECK = "python3 ~/Claude/claude-config/scripts/session-reply-knowledge-report.py {id8} --delegated --check <worker の処分の file>"


def _base() -> str:
    return os.path.expanduser(os.environ.get("WRAP_DELEGATE_BASE") or "~/Claude")


def _cw():
    spec = _ilu.spec_from_file_location("child_wrap_check", os.path.join(HERE, "child-wrap-check.py"))
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def transcript_facts(path: str) -> dict:
    """記録の大きさ (MB)・文脈圧縮の回数と最後の時刻・最初と最後の時刻。"""
    out = {"mb": 0.0, "compactions": 0, "last_compaction": "", "first": "", "last": ""}
    try:
        out["mb"] = round(os.path.getsize(path) / 1e6, 1)
        fh = open(path, encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return out
    with fh:
        for line in fh:
            if '"compact_boundary"' not in line and '"timestamp"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            ts = str(e.get("timestamp") or "") if isinstance(e, dict) else ""
            if ts:
                out["first"] = out["first"] or ts
                out["last"] = ts
            if isinstance(e, dict) and e.get("type") == "system" and e.get("subtype") == "compact_boundary":
                out["compactions"] += 1
                out["last_compaction"] = ts
    return out


def skeleton(target: str, quote: str = "") -> str:
    cw = _cw()
    c = cw.locate(target)
    if not c:
        raise SystemExit(f"wrap-delegate-spec: session {target!r} が見つからない (app の記録にも live の registry にも無い)")
    cli, id8 = c["cli"], c["cli"][:8]
    f = transcript_facts(c["path"])
    commits = cw.child_commits(cli, "")
    kids = []
    for k in cw.children_of(c["local"]) if c["local"] else []:
        kc = cw.locate(k["local"]) or {}
        ev = cw.scan_child(kc.get("path", ""))
        kids.append((k, max(ev["wraps"], default=""), cw.child_commits(k["cli"], "") if k["cli"] else []))
    hm = cw._local_hm
    L = [f"{MARK}{cli} made={time.strftime('%Y-%m-%dT%H:%M:%S')} -->",
         f"# 締めの依頼書: session {id8} の締め ({c['title'] or '題なし'})",
         "",
         "形 = claude-config/conventions/closing-sweep.md#delegated-sweep (この骨は `scripts/wrap-delegate-spec.py` が記録から作った。"
         " 空欄 〔依頼元が書く〕 だけを埋める)。",
         "",
         "## 本人の頼み (逐語)",
         "",
         f"> {quote}" if quote else "> 〔依頼元が本人の頼みを逐語で貼る〕",
         "",
         "worker はこの範囲を全部回す。 回せなかった範囲は提出の「見ていない」 に書く (依頼元は受け取るとき、 この逐語と照らす)。",
         "",
         "## (1) 対象の session",
         "",
         f"- id = `{cli}` (Claude Code の session)。 local = `{c['local'] or 'なし'}`",
         f"- 記録 = `{c['path']}` ({f['mb']} MB、 {hm(f['first']) if f['first'] else '?'} 〜 {hm(f['last']) if f['last'] else '?'}、"
         f" 文脈圧縮 {f['compactions']} 回" + (f"、 最後 = {hm(f['last_compaction'])}" if f["last_compaction"] else "") + ")",
         "- worker にとって closing-sweep.md の「この session」 はこの session = 0.3・0.5 の道具をこの id で回す"
         " (圧縮の前の分も記録から読む = 依頼元の記憶や要約から拾わない):",
         ]
    for cmd in (f"search-agent-transcripts.py --session {id8} --role user --regex .",
                f"session-scripts-report.py {id8}", f"session-claims-report.py {id8}",
                f"session-open-questions-report.py {id8}", f"session-fetched-docs-report.py {id8}",
                f"session-reply-knowledge-report.py {id8} --delegated",
                f"subagent-reports.py {id8} --max-chars 0", f"headless-worker-reports.py {id8} --max-chars 0"):
        L.append(f"  - `python3 ~/Claude/claude-config/scripts/{cmd}`"
                 + ("  (処分の file 〔.txt〕 を書いて `--check <file>` を通す)" if "--delegated" in cmd else ""))
    L += ["- 掲示板に出した依頼 = 掲示板の `inbox --sync` と `show --request <id>` (closing-sweep.md#collect-from-delegates の 2 行目)",
          "",
          "## (2) 既に済んだもの (拾い直さない・二重に上げない)",
          ""]
    if commits:
        L.append("- この session の commit (`Agent-Session` の trailer): " + ", ".join(
            f"{os.path.basename(x['repo'])} {x['sha']}{'' if x['pushed'] else ' (未 push)'}" for x in commits[:12])
            + (" ほか" if len(commits) > 12 else ""))
    else:
        L.append("- この session の commit: 無し (trailer で引いた範囲)")
    if kids:
        L.append("- この session が起こした子 session (子が上げたものは子の commit を先に見る):")
        for k, w, kc in kids:
            L.append(f"  - {k['title'] or k['local']} (`{k['local']}`) wrap={hm(w) if w else 'なし'}"
                     + (" commit: " + ", ".join(f"{os.path.basename(x['repo'])} {x['sha']}" for x in kc[:6]) if kc else "")
                     + (" (archive 済み)" if k["archived"] else ""))
    else:
        L.append("- この session が起こした子 session: 無し (app の記録の範囲)")
    L += ["- 既に済んだ拾い出しの結果の file: 〔依頼元が書く。 無ければ「無し」〕",
          "",
          "## (3) 触らせない file",
          "",
          "- 〔依頼元が書く。 提出前の原稿など〕",
          "- 保護された file のうち、 緩和の語の無い追記・言い直しで guard が通すもの以外の変更は本人に聞く"
          " (closing-sweep.md#protected-files-need-ruling)",
          "",
          "## 依頼元が受け取りの turn に自分の窓で回す 1 行",
          "",
          f"`{REPLY_CHECK.format(id8=id8)}`",
          "",
          "締めの Stop hook は依頼元の会話記録の中の --check しか見ない (closing-sweep.md#delegated-reply-knowledge-check)。"
          " この依頼書で渡した依頼を受け取ると、 受け取りの直後の hook がこの 1 行を出し、 その turn で通るまで締めの Stop hook が"
          " 1 回差し戻す。",
          "",
          "## 提出に書くこと",
          "",
          "- 移したもの (どの層の正本へ) と、 repo ごとの commit",
          "- 処分の file の path (.txt) と、 上の 1 行をそのまま",
          "- 見た範囲 / 見ていない範囲 (「見ていない」 は依頼元が上の本人の頼みと照らす)",
          "- 引き継ぎ・結果の file の頭に、 この依頼書の 1 行目 (`<!-- wrap-delegate-spec target=… -->`) と「## 本人の頼み (逐語)」"
          " の節をそのまま写す (受け取りの照合がこの依頼を締めの委任と読む印と、 照らす逐語。 中身の見えない依頼でも、 依頼元が提出の後に"
          " その file を読めば効く)",
          ""]
    return "\n".join(L)


# ---------------------------------------------------------------- 受け取りの照合 (child-wrap-check.py --hook-accept が呼ぶ)

def submit_time(rid: str, events: list[dict]) -> str:
    """その依頼の最初の提出 (submit・handover) の時刻 ('' = 無い)。 受け取りの照合は、 これより後に読んだ file を見る。"""
    ts = [str(e.get("created_at") or "") for e in events if e.get("request_id") == rid and e.get("kind") in ("submit", "handover")]
    return min((t for t in ts if t), default="")


def _resolve(ref: str, project: str) -> str:
    ref = str(ref or "").strip()
    if not ref:
        return ""
    cands = [os.path.expanduser(ref)] if ref.startswith(("/", "~")) else \
        ([os.path.join(_base(), project, ref)] if project else []) + [os.path.join(_base(), ref)]
    return next((p for p in cands if os.path.isfile(p)), "")


def _read(path: str, limit: int = 400_000) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def accept_lines(rid: str, events: list[dict], read_paths: list[str] | None = None) -> list[str]:
    req = next((e for e in events if e.get("event_id") == rid and e.get("kind") == "request"), None)
    if not req:
        return []
    project = str((req.get("project") or {}).get("key") or "")
    lines = []
    specs = [p for p in (_resolve(r, project) for r in req.get("references") or []) if p]
    files = []
    for e in events:
        if e.get("request_id") == rid and e.get("kind") in ("submit", "handover"):
            files += [p for p in (_resolve(d, project) for d in (e.get("deliverables") or []) + (e.get("references") or [])) if p]
    files += [q for q in (_resolve(p, project) for p in (read_paths or [])) if q]
    target, quotes = "", []
    for p in specs + files:  # the spec carries the mark; the worker copies it into its handover (a restricted request has no references)
        t = _read(p)
        m = MARK_RE.search(t)
        if m and not target:
            target = m.group(1)
        if m or p in specs:
            quotes += QUOTE_SECTION.findall(t)[:1] + (QUOTE_LINE.findall(t)[:2] if p in specs else [])
    if not target:
        # only a delegated closing: replayed on past accepts, the "not seen" lines came with most of them (measured)
        return []
    lines.append(f"{ACCEPT_MARK}{target[:8]} — 締めを渡した依頼 (対象 = session {target[:8]}) を受け取った。 この turn のうちに"
                 f" 依頼元の照合を自分の窓で回す = `{REPLY_CHECK.format(id8=target[:8])}` (処分の file は worker の提出に書いてある。"
                 " 締めの Stop hook がこの turn で確かめる = closing-sweep.md#delegated-reply-knowledge-check)")
    seen, hits = set(), []
    for p in files:
        if p in seen or not p.endswith((".md", ".txt")):
            continue
        seen.add(p)
        for ln in _read(p).splitlines():
            if NOT_SEEN.search(ln) and len(hits) < MAX_NOT_SEEN:
                hits.append(f"  - {os.path.basename(p)}: {' '.join(ln.split())[:200]}")
    if hits:
        q = ("「" + quotes[0][:120] + "」") if quotes else "(依頼書の冒頭の本人の逐語)"
        lines.append("📋 受け取った提出・引き継ぎの「見ていない・確かめていない」 の行:\n" + "\n".join(hits)
                     + f"\n→ 依頼書の本人の頼み {q} の範囲に、 上の見ていない範囲が入っていないかを照らす。 入っていれば accept で"
                     " 終えず、 revise で残りを頼む (closing-sweep.md#collect-from-delegates の「報告は検証前の主張」)。")
    return lines


READ_CMD = re.compile(r"(?:^|[;&|(]\s*|\s)(?:cat|sed|head|tail|less|more|bat|nl|grep|rg)\b")
TEXT_TOKEN = re.compile(r"""(?:^|\s)['"]?((?:~|/|\.{0,2}/)?[^\s'"|;&<>]+\.(?:md|txt))['"]?""")


def read_paths_since(transcript: str, since: str = "", tail_bytes: int = 4_000_000) -> list[str]:
    """会話記録で読んだ file の path (Read tool の file_path と、 Bash の読み取り 〔cat・sed・head など〕 に渡した .md・.txt の
    path)。 since (ISO の時刻) があればそれより後の全部 (= 提出の後に読んだ file、 前の turn の分も)、 無ければ今の turn
    (最後の、 tool_result でない user の発言から後) だけ。 実測: 中身の見えない依頼の受け取りの照合が、 引き継ぎを Bash で
    読んだ回・前の turn に読んだ回を拾わなかった。"""
    try:
        with open(transcript, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - tail_bytes))
            raw = fh.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return []
    out: list[str] = []
    for line in raw:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        ts = str(e.get("timestamp") or "")
        if since and ts and ts[:19] < since[:19]:
            continue
        c = (e.get("message") or {}).get("content")
        if not since and e.get("type") == "user" and not e.get("isMeta") and not (
                isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)):
            out = []
            continue
        if e.get("type") == "assistant" and isinstance(c, list):
            for b in c:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                inp = b.get("input") or {}
                got = []
                if b.get("name") == "Read":
                    got = [str(inp.get("file_path") or "")]
                elif b.get("name") == "Bash" and READ_CMD.search(str(inp.get("command") or "")):
                    got = TEXT_TOKEN.findall(str(inp.get("command") or ""))
                for fp in got:
                    if fp and fp not in out:
                        out.append(fp)
    return out


def read_paths_in_turn(transcript: str, tail_bytes: int = 2_000_000) -> list[str]:
    """read_paths_since の今の turn だけの形 (前の呼び出し方)。"""
    return read_paths_since(transcript, "", tail_bytes)


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    fails = []

    def ok(label, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + label)
        if not cond:
            fails.append(label)

    with tempfile.TemporaryDirectory() as d:
        os.environ["WRAP_DELEGATE_BASE"] = d
        os.makedirs(os.path.join(d, "proj", "plans"))
        target = "0123abcd-1111-2222-3333-444455556666"
        spec = os.path.join(d, "proj", "plans", "close-spec.md")
        with open(spec, "w", encoding="utf-8") as fh:
            fh.write(f"{MARK}{target} made=x -->\n# 締めの依頼書\n\n## 本人の頼み (逐語)\n\n> この session で得た知見をすべて正本に整理しておいて\n")
        hand = os.path.join(d, "proj", "handover.md")
        with open(hand, "w", encoding="utf-8") as fh:
            fh.write("# 引き継ぎ\n- 見た: 台帳と TODO\n- 見ていない: 元の session の会話記録\n- 移したもの: 3 件\n")
        plain = os.path.join(d, "proj", "plans", "plain-spec.md")
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write("# 普通の依頼書\n本人「表を直して」\n")
        ev = [{"event_id": "R1", "kind": "request", "project": {"key": "proj"}, "references": ["plans/close-spec.md"]},
              {"event_id": "S1", "kind": "submit", "request_id": "R1", "deliverables": ["handover.md"]},
              {"event_id": "R2", "kind": "request", "project": {"key": "proj"}, "references": ["proj/plans/plain-spec.md"]}]
        got = accept_lines("R1", ev)
        ok("締めを渡した依頼の受け取り = 印つきの --check の行", bool(got) and got[0].startswith(ACCEPT_MARK + "0123abcd")
           and "session-reply-knowledge-report.py 0123abcd --delegated --check" in got[0])
        ok("提出の「見ていない」 の行と、 依頼書の本人の逐語の範囲の 1 行",
           any("見ていない: 元の session の会話記録" in x and "得た知見をすべて正本に整理" in x for x in got))
        got2 = accept_lines("R2", ev, read_paths=[hand])
        ok("印の無い依頼 = 何も出さない (「見ていない」 の行も = 締めを渡した依頼だけ)", got2 == [])
        hand_m = os.path.join(d, "proj", "handover-marked.md")
        with open(hand_m, "w", encoding="utf-8") as fh:
            fh.write(f"{MARK}{target} -->\n## 本人の頼み (逐語)\n\n> この session で得た知見をすべて正本に整理しておいて\n\n"
                     "# 引き継ぎ\n- 見ていない: 元の session の会話記録\n")
        got3 = accept_lines("R4", ev + [{"event_id": "R4", "kind": "request"}], read_paths=[hand_m])
        ok("中身の見えない依頼 (references 無し): 読んだ引き継ぎの印で、 印の行と「見ていない」 の行と、 引き継ぎに写した本人の逐語を出す",
           bool(got3) and got3[0].startswith(ACCEPT_MARK + "0123abcd") and any("元の session の会話記録" in x and "得た知見をすべて正本に整理" in x
                                                                                for x in got3))
        ok("提出も読んだ file も無い依頼 = 何も出さない", accept_lines("R3", ev + [{"event_id": "R3", "kind": "request"}]) == [])
        tr = os.path.join(d, "t.jsonl")
        rows = [{"type": "user", "message": {"content": "前の turn"}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/old.md"}}]}},
                {"type": "user", "message": {"content": "引き継ぎを読んで受け取って"}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": hand}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}},
                {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-01-01T00:00:00Z"}]
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
        ok("今の turn で Read した file だけ (tool_result は turn の区切りでない)", read_paths_in_turn(tr) == [hand])
        f = transcript_facts(tr)
        ok("記録の文脈圧縮の回数", f["compactions"] == 1 and f["last_compaction"].startswith("2026-01-01"))
        rows2 = [{"type": "assistant", "timestamp": "2026-01-01T00:00:00Z", "message": {"content": [
                     {"type": "tool_use", "name": "Read", "input": {"file_path": "/before.md"}}]}},
                 {"type": "assistant", "timestamp": "2026-01-01T01:00:00Z", "message": {"content": [
                     {"type": "tool_use", "name": "Bash", "input": {"command": f"sed -n 1,40p {hand_m}"}}]}},
                 {"type": "user", "timestamp": "2026-01-01T01:05:00Z", "message": {"content": "受け取って"}},
                 {"type": "assistant", "timestamp": "2026-01-01T01:06:00Z", "message": {"content": [
                     {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}}]}}]
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows2) + "\n")
        ok("提出の後に読んだ file (前の turn・Bash の読み取りも)、 提出の前は数えない",
           read_paths_since(tr, "2026-01-01T00:30:00Z") == [hand_m])
        ok("提出の時刻 = 最初の submit・handover", submit_time("R1", ev + [{"request_id": "R1", "kind": "submit", "created_at": "2025-12-31T00:00:00Z"}])
           == "2025-12-31T00:00:00Z")
        os.environ.pop("WRAP_DELEGATE_BASE", None)
    print("selftest: " + ("ALL PASS" if not fails else f"FAIL {len(fails)}"))
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="ある session の締めを別の worker に渡す依頼書の骨を作る")
    ap.add_argument("target", nargs="?")
    ap.add_argument("--quote", default="", help="本人の頼み (逐語)")
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.target:
        ap.error("締める session の id (か先頭 8 字) を 1 つ")
    text = skeleton(a.target, a.quote)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrap-delegate-spec: 骨を {a.out} に書いた (空欄 〔依頼元が書く〕 を埋めてから掲示板の request の --reference に)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
