#!/usr/bin/env python3
"""transcript-line-shapes.py — 会話記録 (jsonl) で、 prompt の行がどの形で入っているかを数える (行の種類・isMeta・origin.kind・entrypoint × 本文の種類、 例つき)。 本人の発言と別 session の message を見分ける hook を書く・直す前と、 app の版が上がった後に読み直す道具

Why: 「本人が打った発言か」 を会話記録から決める hook は、 行の形 (user 行か queued_command の attachment か、 isMeta か、
origin.kind が何か) に依る。 形は app の版で変わり、 docs には無い (実測: 別 session の message は idle の受け手では isMeta の
user 行、 busy の受け手では origin.kind = "peer" の queued_command で入った。 CLI・SDK で起こした session の最初の prompt は
origin.kind = "human" で入った。 古い版は desktop の send_message で届いた message を origin.kind = "human" で記録した)。
その場の使い捨ての集計を何度も書いたので道具にした。 規約 = conventions/hook-authoring.md#transcript-human-vs-peer-message。

数えるもの: type が user で tool_result を運ばない行 (isMeta も) と、 type が attachment で attachment.type が queued_command の行。
本文の種類 = system-reminder を取り除いた先頭で決める: peer (`<cross-session-message`) / task (`<task-notification`) /
side (`<side-sessions-event`) / command (`<command-name>`・`<local-command`) / hook (`Stop hook feedback` など) /
summary (圧縮の要約) / handoff (`Background (from the session that started this one)`) / text (それ以外)。
first = その会話記録で最初の prompt の行か (CLI・SDK の起動文の判定に使う)。

使い方:
  transcript-line-shapes.py [--days N] [--examples K] [--json]   全 config dir の会話記録 (subagent を除く、 既定 30 日)
  transcript-line-shapes.py --file <jsonl> …                      指定の会話記録だけ
  transcript-line-shapes.py --selftest
読むだけ。 壊れた行は飛ばす。 env (test): CLAUDE_PROJECTS_DIR。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import session_model as sm  # noqa: E402

REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
CATEGORIES = (
    ("peer", ("<cross-session-message",)),
    ("task", ("<task-notification",)),
    ("side", ("<side-sessions-event",)),
    ("command", ("<command-name>", "<command-message>", "<local-command")),
    ("hook", ("Stop hook feedback", "PreToolUse:", "PostToolUse:", "UserPromptSubmit hook")),
    ("summary", ("This session is being continued from a previous conversation",)),
    ("handoff", ("Background (from the session that started this one)",)),
)


def _text(e: dict) -> str:
    a = e.get("attachment") if e.get("type") == "attachment" else None
    p = a.get("prompt") if isinstance(a, dict) else (e.get("message") or {}).get("content")
    if isinstance(p, list):
        p = " ".join(b.get("text", "") for b in p if isinstance(b, dict) and b.get("type") == "text")
    return REMINDER.sub("", str(p or "")).strip()


def shape(e: dict) -> tuple[str, str] | None:
    """(form, origin) of a prompt line, None for anything else. form = user / user(isMeta) / queued_command."""
    if e.get("type") == "attachment":
        a = e.get("attachment")
        if not isinstance(a, dict) or a.get("type") != "queued_command":
            return None
        return "queued_command", str((a.get("origin") or {}).get("kind") or "-")
    if e.get("type") != "user":
        return None
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return None
    o = e.get("origin")
    return ("user(isMeta)" if e.get("isMeta") else "user"), str((o or {}).get("kind") or "-") if isinstance(o, dict) else "-"


def category(text: str) -> str:
    head = text[:400]
    for name, marks in CATEGORIES:
        if any(head.startswith(m) or m in head[:200] for m in marks):
            return name
    return "text"


def scan(paths: list[str], examples: int = 2) -> tuple[Counter, dict]:
    counts: Counter = Counter()
    ex: dict = defaultdict(list)
    for p in paths:
        first = True
        try:
            fh = open(p, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"user"' not in line and "queued_command" not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(e, dict):
                    continue
                sh = shape(e)
                if sh is None:
                    continue
                t = _text(e)
                key = (sh[0], sh[1], str(e.get("entrypoint") or "-"), category(t), "first" if first else "")
                first = False
                counts[key] += 1
                if len(ex[key]) < examples:
                    ex[key].append((str(e.get("timestamp") or "")[:16], os.path.basename(p)[:8], t[:80].replace("\n", " ")))
    return counts, ex


def transcripts(days: float) -> list[str]:
    cutoff = time.time() - days * 86400
    out = []
    for root in sm.projects_dirs():
        for p in glob.glob(os.path.join(root, "*", "*.jsonl")):
            try:
                if os.path.getmtime(p) >= cutoff:
                    out.append(p)
            except OSError:
                pass
    return sorted(set(out))


def selftest() -> int:
    fails = []

    def check(label: str, ok: bool) -> None:
        print(("ok   " if ok else "FAIL ") + label)
        if not ok:
            fails.append(label)

    rows = [
        {"type": "user", "entrypoint": "cli", "origin": {"kind": "human"}, "message": {"content": "You are the worker for role x"}},
        {"type": "user", "entrypoint": "claude-desktop", "origin": {"kind": "human"}, "message": {"content": "please read"}},
        {"type": "user", "isMeta": True, "message": {"content": "<system-reminder>r</system-reminder>\n<cross-session-message from=\"local_a\">hi"}},
        {"type": "attachment", "attachment": {"type": "queued_command", "origin": {"kind": "peer"},
                                              "prompt": [{"type": "text", "text": "<cross-session-message from=\"uds:/x\">yo"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "user", "message": {"content": "Stop hook feedback: fix it"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
    ]
    d = tempfile.mkdtemp(prefix="line-shapes-")
    p = os.path.join(d, "s.jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))
    counts, ex = scan([p])
    check("CLI first prompt counted as first human text",
          counts[("user", "human", "cli", "text", "first")] == 1)
    check("desktop human prompt is not first", counts[("user", "human", "claude-desktop", "text", "")] == 1)
    check("idle peer message = isMeta user line", counts[("user(isMeta)", "-", "-", "peer", "")] == 1)
    check("busy peer message = queued_command with origin peer", counts[("queued_command", "peer", "-", "peer", "")] == 1)
    check("tool results are not prompt lines", sum(counts.values()) == 5)
    check("hook feedback categorised", counts[("user", "-", "-", "hook", "")] == 1)
    print("selftest:", "FAIL " + str(len(fails)) if fails else "PASS")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--days", type=float, default=30.0)
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--examples", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    paths = a.file or [p for p in transcripts(a.days) if "/subagents/" not in p]
    counts, ex = scan(paths, a.examples)
    if a.json:
        print(json.dumps([{"form": k[0], "origin": k[1], "entrypoint": k[2], "category": k[3], "first": bool(k[4]),
                           "count": n, "examples": ex[k]} for k, n in counts.most_common()], ensure_ascii=False, indent=1))
        return 0
    print(f"会話記録 {len(paths)} 本 / prompt の行 {sum(counts.values())}")
    print("件数  行の種類 / origin / entrypoint / 本文の種類 / 最初の prompt")
    for k, n in counts.most_common():
        print(f"{n:5d}  {k[0]} / {k[1]} / {k[2]} / {k[3]}" + (" / first" if k[4] else ""))
        for t, sid, head in ex[k]:
            print(f"         例 {t} {sid}: {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
