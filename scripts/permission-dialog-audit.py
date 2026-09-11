#!/usr/bin/env python3
"""permission-dialog-audit.py — Claude desktop の承認 dialog を app log から tool 別に集計し、 transcript と時刻突合して main / sub-agent / 不明に振り分ける

なぜ要るか
----------
「いちいち聞かれる」 「背景作業を立ち上げるたびに聞かれる」 は体感で語られやすく、 どの tool の
dialog が何件か・誰 (main session か sub-agent か) の tool call かを数えないと、 allow の足し先
も「そもそも仕様で消せない dialog か」 も決まらない。 desktop app は dialog ごとに log へ 2 行
残すので、 それを数えれば推測が要らない。 一般則: conventions/claude-code-permissions.md#desktop-permission-dialog-log

入力
----
desktop app の log (既定 `~/Library/Logs/Claude/main*.log`) の 2 形式の行:
  <YYYY-MM-DD HH:MM:SS> [info] Emitted tool permission request <id> for <tool> in session <local_id>
  <YYYY-MM-DD HH:MM:SS> [info] Received permission response for <id>: <decision> (tool: <tool>)
同じ行が 2 回ずつ書かれることがあるので request id で dedupe する。 log の時刻は local time。

mode
----
  (既定)              tool 別件数 / decision 内訳 / 応答待ち秒 (中央値・最大)
  --latest N          直近 N 件を 1 行ずつ
  --attribute         transcript (`~/.claude/projects/**.jsonl`、 sub-agent の transcript を含む) の
                      tool_use と時刻突合 (dialog 発行の --before 秒前 〜 --after 秒後、 既定 8 / 2)。
                      main / sub-agent / unmatched に振り分け、 Edit/Read/Write は path の上位 2 階層、
                      Bash は先頭語で bucket する
  --from-transcripts  desktop log が無い環境 (CLI 等) 向け。 通常すぐ返る tool (Read/Edit/Write/Glob/
                      Grep/Monitor 等) の tool_use → tool_result が --wait 秒 (既定 15) 超かかった
                      ものを「dialog 候補」 として列挙 (= 承認待ちで止まった可能性。 断定はしない)
  --since YYYY-MM-DD  対象期間の開始日 (log / transcript 共通)
  --selftest

使い方
------
  permission-dialog-audit.py --since 2026-07-25
  permission-dialog-audit.py --attribute --since 2026-09-01
  permission-dialog-audit.py --latest 20
  permission-dialog-audit.py --from-transcripts --since 2026-09-01
"""
import argparse
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

EMIT_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:[.,]\d+)?\s+\[\w+\]\s+Emitted tool permission request (\S+) for (\S+) in session (\S+)"
)
RESP_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:[.,]\d+)?\s+\[\w+\]\s+Received permission response for (\S+): (\S+) \(tool: ([^)]*)\)"
)
FAST_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Glob", "Grep", "Monitor",
              "Skill", "TodoWrite", "ToolSearch")
PATH_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit")


def local_epoch(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


def iso_epoch(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def since_epoch(since):
    return local_epoch(since + " 00:00:00") if since else 0.0


def parse_logs(log_dir, since):
    """request id → {emit, tool, session, resp, decision}。 dedupe 済。"""
    lo = since_epoch(since)
    reqs = {}
    resps = {}
    for p in sorted(Path(log_dir).glob("main*.log")):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "permission" not in line:
                        continue
                    m = EMIT_RE.match(line)
                    if m:
                        t = local_epoch(m.group(1))
                        rid = m.group(2)
                        cur = reqs.get(rid)
                        if cur is None or t < cur["emit"]:
                            reqs[rid] = {"id": rid, "emit": t, "tool": m.group(3), "session": m.group(4)}
                        continue
                    m = RESP_RE.match(line)
                    if m:
                        t = local_epoch(m.group(1))
                        rid = m.group(2)
                        if rid not in resps or t < resps[rid][0]:
                            resps[rid] = (t, m.group(3), m.group(4))
        except OSError:
            continue
    out = {}
    for rid, r in reqs.items():
        if r["emit"] < lo:
            continue
        rs = resps.get(rid)
        r["resp"] = rs[0] if rs else None
        r["decision"] = rs[1] if rs else "(no response)"
        out[rid] = r
    return out


def fmt_t(epoch):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def summarize(reqs):
    by_tool = {}
    for r in reqs.values():
        d = by_tool.setdefault(r["tool"], {"n": 0, "dec": {}, "waits": []})
        d["n"] += 1
        d["dec"][r["decision"]] = d["dec"].get(r["decision"], 0) + 1
        if r["resp"] is not None:
            d["waits"].append(max(0.0, r["resp"] - r["emit"]))
    return by_tool


def print_summary(reqs, log_dir, since):
    by_tool = summarize(reqs)
    total = len(reqs)
    span = ""
    if reqs:
        span = f" ({fmt_t(min(r['emit'] for r in reqs.values()))} 〜 {fmt_t(max(r['emit'] for r in reqs.values()))})"
    print(f"permission dialogs: {total} 件{span}  [log = {log_dir}{', since ' + since if since else ''}]")
    print("")
    hdr = f"{'tool':<48} {'n':>5}  {'wait med':>8} {'max':>8}  decisions"
    print(hdr)
    print("-" * len(hdr))
    for tool, d in sorted(by_tool.items(), key=lambda kv: -kv[1]["n"]):
        med = f"{statistics.median(d['waits']):.0f}s" if d["waits"] else "-"
        mx = f"{max(d['waits']):.0f}s" if d["waits"] else "-"
        dec = ", ".join(f"{k} {v}" for k, v in sorted(d["dec"].items(), key=lambda kv: -kv[1]))
        print(f"{tool[:48]:<48} {d['n']:>5}  {med:>8} {mx:>8}  {dec}")


def print_latest(reqs, n):
    rows = sorted(reqs.values(), key=lambda r: r["emit"])[-n:]
    for r in rows:
        wait = f"{r['resp'] - r['emit']:.0f}s" if r["resp"] is not None else "-"
        print(f"{fmt_t(r['emit'])}  {r['tool']:<44} {r['decision']:<14} wait {wait:>6}  {r['session']}")


# ---------------------------------------------------------------- transcripts

def iter_transcripts(projects_dir, since):
    lo = since_epoch(since) - 86400  # mtime は最終書込み時刻なので 1 日余裕
    for root, _dirs, files in os.walk(projects_dir):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            p = Path(root) / fn
            try:
                if p.stat().st_mtime < lo:
                    continue
            except OSError:
                continue
            yield p


def load_tool_events(projects_dir, since, want_results=False):
    """tool_use の list と (want_results なら) tool_use_id → result 時刻。"""
    uses = []
    results = {}
    lo = since_epoch(since)
    for p in iter_transcripts(projects_dir, since):
        sub_path = "/subagents/" in str(p).replace(os.sep, "/")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    has_use = '"tool_use"' in line
                    has_res = want_results and '"tool_result"' in line
                    if not (has_use or has_res):
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    ts = iso_epoch(rec.get("timestamp", ""))
                    if ts is None or ts < lo:
                        continue
                    content = (rec.get("message") or {}).get("content")
                    if not isinstance(content, list):
                        continue
                    side = bool(rec.get("isSidechain")) or sub_path
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "tool_use":
                            uses.append({"t": ts, "name": c.get("name", ""), "input": c.get("input") or {},
                                         "id": c.get("id"), "sub": side, "path": p})
                        elif want_results and c.get("type") == "tool_result" and c.get("tool_use_id"):
                            results.setdefault(c["tool_use_id"], ts)
        except OSError:
            continue
    uses.sort(key=lambda u: u["t"])
    return uses, results


def names_match(log_tool, use_name):
    if log_tool == use_name:
        return True
    a = log_tool.split(":")[-1].split("__")[-1]
    b = use_name.split("__")[-1]
    return bool(a) and a == b


def bucket(use, home):
    name = use["name"]
    inp = use["input"] if isinstance(use["input"], dict) else {}
    if name in PATH_TOOLS:
        fp = inp.get("file_path") or inp.get("notebook_path") or ""
        if fp:
            s = str(fp)
            h = str(home)
            if s.startswith(h + os.sep):
                parts = s[len(h) + 1:].split(os.sep)
                return f"{name} ~/" + "/".join(parts[:2])
            parts = [x for x in s.split(os.sep) if x]
            return f"{name} /" + "/".join(parts[:2])
        return name
    if name == "Bash":
        cmd = str(inp.get("command", "")).strip()
        toks = cmd.split()
        while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
            toks = toks[1:]
        return f"Bash {toks[0] if toks else '?'}"
    return name


def attribute(reqs, uses, before, after, home):
    rows = []
    for r in sorted(reqs.values(), key=lambda x: x["emit"]):
        lo = r["emit"] - before
        hi = r["emit"] + after
        cands = [u for u in uses if lo <= u["t"] <= hi and names_match(r["tool"], u["name"])]
        if not cands:
            rows.append((r, "unmatched", r["tool"]))
            continue
        u = min(cands, key=lambda u: abs(u["t"] - r["emit"]))
        rows.append((r, "sub-agent" if u["sub"] else "main", bucket(u, home)))
    return rows


def print_attribution(rows):
    total = len(rows)
    by_who = {}
    for _r, who, _b in rows:
        by_who[who] = by_who.get(who, 0) + 1
    print(f"attribution: {total} dialogs → " + ", ".join(f"{k} {v}" for k, v in sorted(by_who.items())))
    print("")
    agg = {}
    for _r, who, b in rows:
        agg[(who, b)] = agg.get((who, b), 0) + 1
    hdr = f"{'who':<10} {'n':>5}  bucket"
    print(hdr)
    print("-" * 60)
    for (who, b), n in sorted(agg.items(), key=lambda kv: (kv[0][0], -kv[1])):
        print(f"{who:<10} {n:>5}  {b}")


def from_transcripts(uses, results, wait, tools):
    cands = []
    for u in uses:
        if u["name"] not in tools or not u["id"]:
            continue
        rt = results.get(u["id"])
        if rt is None:
            continue
        gap = rt - u["t"]
        if gap > wait:
            cands.append((u, gap))
    return cands


def print_from_transcripts(cands, home, wait):
    print(f"dialog 候補 (通常すぐ返る tool の tool_use → tool_result が {wait:.0f}s 超): {len(cands)} 件")
    print("  ⚠️ 候補 = 承認待ちで止まった可能性。 遅い FS / 長い Monitor 起動等でも出るので断定しない")
    print("")
    per = {}
    for u, _g in cands:
        per[u["name"]] = per.get(u["name"], 0) + 1
    for name, n in sorted(per.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<20} {n:>5}")
    print("")
    for u, g in cands[-30:]:
        who = "sub-agent" if u["sub"] else "main"
        print(f"  {fmt_t(u['t'])}  {who:<9} wait {g:>6.0f}s  {bucket(u, home)}")


# ---------------------------------------------------------------- selftest

def selftest():
    fails = []

    def check(cond, label):
        print(f"  {'PASS' if cond else 'FAIL'}: {label}")
        if not cond:
            fails.append(label)

    tmp = Path(tempfile.mkdtemp())
    try:
        logs = tmp / "logs"
        logs.mkdir()
        home = tmp / "home"
        e1 = "2026-09-11 12:00:00 [info] Emitted tool permission request aaa for Monitor in session local_1\n"
        r1 = "2026-09-11 12:40:00 [info] Received permission response for aaa: once (tool: Monitor)\n"
        e2 = "2026-09-11 13:00:00 [info] Emitted tool permission request bbb for Bash in session local_1\n"
        r2 = "2026-09-11 13:00:05 [info] Received permission response for bbb: always (tool: Bash)\n"
        e3 = "2026-09-11 14:00:00 [info] Emitted tool permission request ccc for Edit in session local_2\n"
        e4 = "2026-09-10 09:00:00 [info] Emitted tool permission request ddd for Write in session local_3\n"
        # 同じ行が 2 回ずつ + rotate した別 file にも
        (logs / "main.log").write_text(e1 + e1 + r1 + r1 + e2 + e2 + r2 + "noise permission line\n", encoding="utf-8")
        (logs / "main1.log").write_text(e3 + e3 + e4 + e1, encoding="utf-8")
        (logs / "other.log").write_text(e2.replace("bbb", "zzz"), encoding="utf-8")  # main*.log 以外は見ない

        reqs = parse_logs(logs, None)
        check(len(reqs) == 4, f"dedupe + main*.log のみ → 4 件 (got {len(reqs)})")
        check(reqs["aaa"]["decision"] == "once" and abs(reqs["aaa"]["resp"] - reqs["aaa"]["emit"] - 2400) < 1,
              "応答待ち 40 分を計測")
        check(reqs["ccc"]["decision"] == "(no response)", "応答なしを区別")
        check(len(parse_logs(logs, "2026-09-11")) == 3, "--since で期間を切る")
        s = summarize(reqs)
        check(s["Bash"]["dec"] == {"always": 1}, "decision 内訳")

        # transcripts: main の Bash / sub-agent の Edit
        proj = tmp / "projects" / "-x"
        (proj / "sess" / "subagents").mkdir(parents=True)

        def iso(local):
            return datetime.fromtimestamp(local_epoch(local)).astimezone().isoformat()

        main_recs = [
            {"type": "assistant", "timestamp": iso("2026-09-11 12:59:58"),
             "message": {"content": [{"type": "tool_use", "id": "u1", "name": "Bash",
                                      "input": {"command": "FOO=1 python3 x.py --send"}}]}},
            {"type": "user", "timestamp": iso("2026-09-11 13:00:06"),
             "message": {"content": [{"type": "tool_result", "tool_use_id": "u1", "content": "ok"}]}},
            {"type": "assistant", "timestamp": iso("2026-09-11 15:00:00"),
             "message": {"content": [{"type": "tool_use", "id": "u3", "name": "Read",
                                      "input": {"file_path": str(home / "Dropbox" / "dir" / "f.txt")}}]}},
            {"type": "user", "timestamp": iso("2026-09-11 15:01:00"),
             "message": {"content": [{"type": "tool_result", "tool_use_id": "u3", "content": "ok"}]}},
        ]
        sub_recs = [
            {"type": "assistant", "isSidechain": True, "timestamp": iso("2026-09-11 13:59:57"),
             "message": {"content": [{"type": "tool_use", "id": "u2", "name": "Edit",
                                      "input": {"file_path": str(home / "work" / "repo" / "a" / "b.md")}}]}},
        ]
        (proj / "sess.jsonl").write_text("\n".join(json.dumps(r) for r in main_recs) + "\n", encoding="utf-8")
        (proj / "sess" / "subagents" / "agent-1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in sub_recs) + "\n", encoding="utf-8")

        uses, results = load_tool_events(tmp / "projects", "2026-09-11", want_results=True)
        rows = attribute(parse_logs(logs, "2026-09-11"), uses, 8, 2, home)
        who = {r["id"]: (w, b) for r, w, b in rows}
        check(who["bbb"] == ("main", "Bash python3"), f"main の Bash を先頭語 bucket (got {who['bbb']})")
        check(who["ccc"] == ("sub-agent", "Edit ~/work/repo"), f"sub-agent の Edit を path 上位 2 階層 (got {who['ccc']})")
        check(who["aaa"][0] == "unmatched", "突合できない dialog は unmatched")

        c = from_transcripts(uses, results, 15, FAST_TOOLS)
        check(len(c) == 1 and c[0][0]["name"] == "Read" and c[0][1] >= 59,
              "--from-transcripts: 60 秒止まった Read だけが候補 (Bash は対象外)")
        check(names_match("computer:request_access", "mcp__computer-use__request_access"), "tool 名の接頭辞差を吸収")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    print(f"selftest: {'PASS' if not fails else 'FAIL'} ({len(fails)} failed)")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log-dir", default="~/Library/Logs/Claude", help="desktop app の log dir")
    ap.add_argument("--projects-dir", default="~/.claude/projects", help="transcript の親 dir")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (local)")
    ap.add_argument("--latest", type=int, default=0, help="直近 N 件を 1 行ずつ")
    ap.add_argument("--attribute", action="store_true", help="transcript と時刻突合して main / sub-agent に振り分け")
    ap.add_argument("--before", type=float, default=8.0, help="突合窓: dialog 発行の何秒前まで (既定 8)")
    ap.add_argument("--after", type=float, default=2.0, help="突合窓: dialog 発行の何秒後まで (既定 2)")
    ap.add_argument("--from-transcripts", action="store_true", help="desktop log 無しで待ち時間から dialog 候補を推定")
    ap.add_argument("--wait", type=float, default=15.0, help="--from-transcripts の閾値秒 (既定 15)")
    ap.add_argument("--tools", default=",".join(FAST_TOOLS), help="--from-transcripts の対象 tool (カンマ区切り)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    home = Path.home()
    projects = Path(a.projects_dir).expanduser()
    if a.from_transcripts:
        uses, results = load_tool_events(projects, a.since, want_results=True)
        tools = tuple(t.strip() for t in a.tools.split(",") if t.strip())
        print_from_transcripts(from_transcripts(uses, results, a.wait, tools), home, a.wait)
        return 0
    log_dir = Path(a.log_dir).expanduser()
    if not log_dir.is_dir():
        print(f"desktop log dir が無い: {log_dir} — CLI 等なら --from-transcripts を使う", file=sys.stderr)
        return 2
    reqs = parse_logs(log_dir, a.since)
    if a.latest:
        print_latest(reqs, a.latest)
        return 0
    print_summary(reqs, log_dir, a.since)
    if a.attribute:
        print("")
        uses, _ = load_tool_events(projects, a.since)
        print_attribution(attribute(reqs, uses, a.before, a.after, home))
    return 0


if __name__ == "__main__":
    sys.exit(main())
