#!/usr/bin/env python3
"""count-malformed-tool-call-events.py — local transcript から malformed-tool-call bug の genuine event を集計（synthetic 文言の user entry のみ = doc/議論 echo を除外〔naive substring は 19x overcount〕、 month×model×client-version 内訳 + model 別 rate、 upstream issue への occurrence 報告用 data point 生成、 read-only、 --selftest 内蔵、 conventions/tool-call-robustness.md#root-cause）
Count genuine malformed-tool-call events in local Claude Code transcripts.

Companion to conventions/tool-call-robustness.md (the Opus 4.8 "malformed and
could not be parsed" model-serialization bug). Produces the statistics needed
for an occurrence report on the canonical upstream issue
(anthropics/claude-code#64774): month x model x client-version breakdown plus
per-model failure rates.

Methodology (mirrors the #64774 OP):

- A *genuine event* is a transcript entry of type "user" whose message content
  is (a short string containing) exactly the synthetic marker the harness
  injects on a parse failure:

      Your tool call was malformed and could not be parsed. Please retry.

  Counting naive substring hits massively overcounts: the same string appears
  as *echoes* inside doc attachments, file-read tool results, and discussions
  about the bug that end up in transcripts (measured 2026-07-10: 590 raw hits
  vs 30 genuine events = 19x overcount in an environment whose conventions
  quote the string).

- Model attribution = model of the immediately preceding assistant message in
  the same session file.

- Rate denominator = assistant message count per model (approximated by
  scanning for assistant entries' "model" field).

Usage:
    python3 count-malformed-tool-call-events.py [--projects-dir DIR]
    python3 count-malformed-tool-call-events.py --selftest

Read-only; scans ~/.claude/projects/*/*.jsonl by default.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

SYNTH = "Your tool call was malformed and could not be parsed. Please retry."

MODEL_RE = re.compile(r'"model":"([^"]+)"')
MONTH_RE = re.compile(r'"timestamp":"(\d{4}-\d{2})')
DATE_RE = re.compile(r'"timestamp":"(\d{4}-\d{2}-\d{2})')
VER_RE = re.compile(r'"version":"([^"]+)"')


def scan(projects_dir):
    turns = Counter()   # (month, model) -> assistant message count
    events = []         # dicts: date, month, model, version, file
    files_scanned = 0
    for f in sorted(glob.glob(os.path.join(projects_dir, "*", "*.jsonl"))):
        last_model = "?"
        last_ver = "?"
        try:
            fh = open(f, "r", errors="replace")
        except OSError:
            continue
        files_scanned += 1
        with fh:
            for line in fh:
                vm = VER_RE.search(line[:2000])
                if vm:
                    last_ver = vm.group(1)
                if '"type":"assistant"' in line:
                    mm = MODEL_RE.search(line)
                    if mm:
                        last_model = mm.group(1)
                        mo = MONTH_RE.search(line[:2000])
                        if mo:
                            turns[(mo.group(1), last_model)] += 1
                if SYNTH in line and '"type":"user"' in line:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    c = (obj.get("message") or {}).get("content")
                    # Genuine signature: short plain-string content. Echoes
                    # (doc attachments / tool_result file reads / discussion
                    # text) live in long strings or structured content lists.
                    if isinstance(c, str) and SYNTH in c and len(c) < 300:
                        dm = DATE_RE.search(line[:2000])
                        events.append({
                            "date": dm.group(1) if dm else "?",
                            "month": dm.group(1)[:7] if dm else "?",
                            "model": last_model,
                            "version": last_ver,
                            "file": os.path.basename(f),
                        })
    return files_scanned, turns, events


def report(files_scanned, turns, events, out=sys.stdout):
    p = lambda *a: print(*a, file=out)
    p(f"files scanned: {files_scanned}")
    p(f"\n=== genuine synthetic error events: {len(events)} ===")
    for k in sorted(Counter(e["month"] for e in events)):
        p(f"  {k}: {Counter(e['month'] for e in events)[k]}")
    p("\nby model:")
    for k, v in Counter(e["model"] for e in events).most_common():
        p(f"  {k}: {v}")
    p("\nby client version:")
    for k, v in sorted(Counter(e["version"] for e in events).items()):
        p(f"  {k}: {v}")
    p("\nevent dates (unique):")
    p(" ", sorted(set(e["date"] for e in events)))
    p("distinct sessions with events:", len(set(e["file"] for e in events)))
    p("\n=== per-model totals (assistant msgs, events, rate) ===")
    agg = Counter()
    for (_mo, mdl), v in turns.items():
        agg[mdl] += v
    for mdl, v in agg.most_common():
        ev = sum(1 for e in events if e["model"] == mdl)
        rate = f"{100 * ev / v:.2f}%" if v else "-"
        p(f"  {mdl}: turns={v} events={ev} rate={rate}")


def selftest():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, "proj")
        os.makedirs(d)
        # Real transcripts are compact JSON (no space after ':'); the scanner's
        # raw-substring fast paths depend on that, so the fixture must match.
        j = lambda o: json.dumps(o, separators=(",", ":"))
        lines = [
            # assistant turn (opus-4-8) -> sets attribution
            j({"type": "assistant", "timestamp": "2026-06-15T01:00:00Z",
               "version": "2.1.170",
               "message": {"model": "claude-opus-4-8", "content": []}}),
            # genuine event (short plain-string user content)
            j({"type": "user", "timestamp": "2026-06-15T01:00:05Z",
               "version": "2.1.170", "message": {"content": SYNTH}}),
            # echo 1: tool_result carrying doc content that quotes the string
            j({"type": "user", "timestamp": "2026-06-15T01:01:00Z",
               "message": {"content": [{"type": "tool_result",
                                        "content": "docs say: " + SYNTH + " " + "x" * 400}]}}),
            # echo 2: long plain-string user content quoting the string
            j({"type": "user", "timestamp": "2026-06-15T01:02:00Z",
               "message": {"content": "discussion... " + SYNTH + " " + "y" * 400}}),
            # assistant turn on another model
            j({"type": "assistant", "timestamp": "2026-06-15T01:03:00Z",
               "message": {"model": "claude-sonnet-4-6", "content": []}}),
        ]
        with open(os.path.join(d, "s.jsonl"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        files, turns, events = scan(td)

        def check(name, cond):
            nonlocal ok
            print(("PASS" if cond else "FAIL"), name)
            ok = ok and cond

        check("1 file scanned", files == 1)
        check("exactly 1 genuine event (echoes excluded)", len(events) == 1)
        check("event attributed to opus-4-8",
              events and events[0]["model"] == "claude-opus-4-8")
        check("event version captured", events and events[0]["version"] == "2.1.170")
        check("turn counts per model",
              turns[("2026-06", "claude-opus-4-8")] == 1
              and turns[("2026-06", "claude-sonnet-4-6")] == 1)
    print("selftest:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--projects-dir",
                    default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    report(*scan(args.projects_dir))


if __name__ == "__main__":
    main()
