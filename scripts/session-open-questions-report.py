#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session-open-questions-report.py — ある session が turn 終わりの箱で問うて、 本人の答えが無いままの問いを会話記録から並べる。--selftest 内蔵。

用途: 締めの sweep (conventions/closing-sweep.md#collect-from-transcript) で、 流れた問いを持ち越すため。
  箱の問いはその turn にしか無い。 次の自動の turn (別 session の message・通知) が始まると箱は入れ替わり、 本人が後で窓に来ても
  問いは画面に無い。 記録に残らないので、 どの機械の網も問い直さない (実測: 外への発信の可否を箱だけで問い、 数秒後の自動の turn で流れた。
  本人はその窓で別の件にだけ答え、 問いは session の締めでも拾われなかった)。 拾ったら TODO の ask に写す。

拾うもの: 箱 (`*__wrap_up`) の `ask` のうち、 次のどれか
  無回答     その後に本人の発言が無い
  流れた     箱の後、 本人が発言する前に自動の turn が始まった (本人の発言でない user 行) か、 箱が出し直された。
             その後の本人の発言がボタンの文と一致すれば答えたと数える
同じ問いが続くときは最後の 1 件だけを数える。 本人の発言の見分け = 行の `origin.kind == "human"` (無い記録は、 isMeta でなく、
tool_result でも system の知らせでもない user 行)。 本人の答えが別の言葉のときは「流れた」 に出ることがある = 1 件ずつ読む。

使い方:
  session-open-questions-report.py <session id か先頭の数文字>     # 既定は環境変数 CLAUDE_CODE_SESSION_ID
  session-open-questions-report.py abcd1234 --json
  session-open-questions-report.py abcd1234 --strict               # 1 件でもあれば exit 1
  session-open-questions-report.py --selftest

OS: macOS / Linux / Windows (Git Bash・PowerShell) で同じに動く (標準 library、 Python 3.8+、 出力は UTF-8)。
"""
import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ssr", HERE / "session-scripts-report.py")
ssr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ssr)

NOT_HUMAN_HEADS = ("Another Claude session", "Stop hook feedback", "<")


def _text(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def is_human(entry):
    """本人が打った user 行か。"""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    origin = entry.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") == "human"
    text = _text(entry).lstrip()
    return bool(text) and not text.startswith(NOT_HUMAN_HEADS)


def is_auto_turn(entry):
    """本人の発言でない turn の入口か (hook の差し戻しは同じ turn の続きなので数えない)。"""
    if entry.get("type") != "user" or is_human(entry):
        return False
    text = _text(entry).lstrip()
    return bool(text) and not text.startswith("Stop hook feedback")


def scan(entries):
    """[{ts, ask, why, next}] を返す。 entries は会話記録の行を時刻順に。"""
    boxes = []
    for i, e in enumerate(entries):
        if e.get("type") != "assistant":
            continue
        content = (e.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and str(b.get("name", "")).endswith("wrap_up"):
                boxes.append((i, e.get("timestamp", ""), b.get("input") or {}))
    open_qs = {}
    for n, (i, ts, box) in enumerate(boxes):
        ask = str(box.get("ask") or "").strip()
        if not ask:
            continue
        replaced = n + 1 < len(boxes)
        next_box_at = boxes[n + 1][0] if replaced else len(entries)
        moved_on, said = False, None
        for e in entries[i + 1:]:
            if is_human(e):
                said = _text(e).strip()
                break
            if is_auto_turn(e):
                moved_on = True
        replaced_first = replaced and not any(is_human(x) for x in entries[i + 1:next_box_at])
        labels = [str(a.get(k) or "").strip() for a in box.get("actions") or [] if isinstance(a, dict) for k in ("label", "message")]
        answered = said is not None and (any(x and x in said for x in labels) or not (moved_on or replaced_first))
        if answered:
            open_qs.pop(ask, None)
        else:
            open_qs[ask] = {"ts": ts, "ask": ask, "why": "無回答" if said is None else "流れた", "next": (said or "")[:80]}
    return sorted(open_qs.values(), key=lambda q: q["ts"])


def report(session, pdirs, as_json, strict):
    paths = ssr.find_main_transcripts(pdirs, session)
    if not paths:
        print("記録が見つからない: session=%s (見た dir: %s)" % (session, ", ".join(map(str, pdirs))))
        return 2
    found = []
    for p in paths:
        entries = []
        for line in open(p, encoding="utf-8", errors="replace"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict):
                entries.append(o)
        found += scan(entries)
    if as_json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
    else:
        print("記録: " + ", ".join(map(str, paths)))
        print("答えの無い箱の問い: %d (今の TODO の ask に写すか、 もう要らないと確かめて消す)" % len(found))
        for q in found:
            print("%s  %s  %s\n      次の本人の発言: %s" % (q["why"], q["ts"][:19], q["ask"][:200], q["next"] or "(無し)"))
    return 1 if (strict and found) else 0


def selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print("FAIL", name, got, want)

    def box(ask, label="はい", ts="t"):
        return {"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "tool_use", "name": "mcp__x__wrap_up", "input": {"recap": "r", "ask": ask, "actions": [{"label": label}]}}]}}

    def human(text):
        return {"type": "user", "origin": {"kind": "human"}, "message": {"content": text}}

    peer = {"type": "user", "isMeta": True, "message": {"content": "Another Claude session sent a message:"}}
    stop = {"type": "user", "isMeta": True, "message": {"content": "Stop hook feedback: 追記して"}}
    tool = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}

    expect("すぐ答えた", scan([box("Q"), human("別の言葉で答える")]), [])
    expect("無回答", [q["why"] for q in scan([box("Q")])], ["無回答"])
    expect("自動の turn で流れた", [q["why"] for q in scan([box("Q"), peer, human("別の話")])], ["流れた"])
    expect("流れてもボタンの文なら答え", scan([box("Q"), peer, human("はい")]), [])
    expect("hook の差し戻しは流れない", scan([box("Q"), stop, tool, human("別の言葉で答える")]), [])
    expect("箱の出し直しで流れた", [q["why"] for q in scan([box("Q"), {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "w__wrap_up", "input": {"recap": "r"}}]}}, human("別の話")])], ["流れた"])
    expect("同じ問いは 1 件", len(scan([box("Q", ts="a"), box("Q", ts="b")])), 1)
    expect("後で答えた問いは消える", scan([box("Q"), peer, box("Q"), human("別の言葉で答える")]), [])
    expect("問いの無い箱は見ない", scan([{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "w__wrap_up", "input": {"recap": "r"}}]}}]), [])
    expect("origin の無い本人の行", is_human({"type": "user", "message": {"content": "はい"}}), True)
    expect("origin の無い peer の行", is_human({"type": "user", "message": {"content": "Another Claude session sent"}}), False)

    with tempfile.TemporaryDirectory() as td:
        pdir = Path(td) / "proj"
        pdir.mkdir()
        (pdir / "abcd1234-0000.jsonl").write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in [box("残る問い"), peer, human("別の話")]) + "\n", encoding="utf-8")
        got = []
        real_print = print
        try:
            import builtins
            builtins.print = lambda *a, **k: got.append(" ".join(map(str, a)))
            rc = report("abcd1234", [Path(td)], False, True)
        finally:
            builtins.print = real_print
        expect("report の終了値", rc, 1)
        expect("report の行", any("残る問い" in x for x in got), True)

    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ssr._utf8_stdout()
    ap = argparse.ArgumentParser(description="session が箱で問うて答えの無いままの問いを並べる")
    ap.add_argument("session", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    ap.add_argument("--projects-dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.session:
        ap.error("session id を渡す (または CLAUDE_CODE_SESSION_ID)")
    return report(a.session, ssr.projects_dirs(a.projects_dir), a.json, a.strict)


if __name__ == "__main__":
    sys.exit(main())
