#!/usr/bin/env python3
"""permission-dialog-audit.py — Claude desktop の承認 dialog を app log から集計し、 transcript と突合して main / sub-agent に振り分け、 1 件ごとに原因 (hook / 長さ / rule) を切り分ける

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
  --diagnose          dialog 1 件ごとに**なぜ出たか**を切り分けて消し方を出す。 transcript から
                      当時の tool 入力を復元し、 settings の PreToolUse hook (matcher が当たる
                      ものだけ) に流し直す。 種別 = hook (今も ask を返す) / fixed (今は exit 2 で
                      block = dialog は出ない) / length (hook 無反応 + Bash が --long-limit 超) /
                      rule (hook 無反応 = allow・cwd scope・protected path 側) / unmatched。
                      `--latest N` と併用で直近 N 件だけ。 ⚠️ hook を**実際に実行する**ので、
                      副作用のある PreToolUse hook を書いているなら `--no-run-hooks`。
                      ⚠️ 判定は「今の設定に当時の入力を流した結果」 であって、 当時の原因の
                      再生ではない (= hook を直した後は「もう出ない」 と読む)
  --since YYYY-MM-DD  対象期間の開始日 (log / transcript 共通)
  --selftest

使い方
------
  permission-dialog-audit.py --since 2026-07-25
  permission-dialog-audit.py --attribute --since 2026-09-01
  permission-dialog-audit.py --diagnose --latest 10     # 「また聞かれた」 → まずこれ
  permission-dialog-audit.py --latest 20
  permission-dialog-audit.py --from-transcripts --since 2026-09-01
"""
import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
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

# ---------- --diagnose: dialog 1 件ごとに「なぜ出たか」 を切り分ける ----------
# 手順は毎回同じ (dialog → transcript から tool 入力を復元 → PreToolUse hook に流し直す →
# 無反応なら長さ / rule) なので、 手でやらずここに置く。 正本 =
# conventions/claude-code-permissions.md#desktop-permission-dialog-log の「mode を疑う前に hook を疑う」

HOOK_TIMEOUT = 10.0
DEFAULT_SETTINGS = "~/.claude/settings.json,~/Claude/.claude/settings.json"
FIXES = {
    "hook": "その hook を直す (除外を足す / 判定を緩める)。 hook が意図どおりなら残す",
    "fixed": "今は hook が先に block する = この形で dialog はもう出ない (対処済み)",
    "length": "分割 / scratchpad の file 経由 / Edit tool (= hooks/long-bash-command-guard.sh が誘導)",
    "rule": "permissions.allow に足す。 ⚠️ 先に path を見る — cwd / additionalDirectories の外なら"
            " allow ではなく scope の問題 (worktree session は本体 repo が cwd 外)。"
            " protected path (.claude/ 等) と always-prompt class は allow で消せない",
    "rule_unique": "⚠️ command に per-call 一意な部分 (乱数 file 名 / session UUID) がある ="
                   " 「常に許可」 は literal 保存なので**二度と一致しない**。 押しても減らない。"
                   " → Bash でなく Read tool で読み、 glob の path rule を 1 本置く"
                   " (claude-code-permissions.md#always-allow-never-matches-again)",
    "unmatched": "transcript に該当 tool 呼び出しが無い (別 session / 窓の外)。 --before/--after を広げる",
}


def first_line(s, limit=160):
    for ln in (s or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln[:limit]
    return ""


def load_pretooluse_hooks(paths):
    """settings*.json の hooks.PreToolUse → [(matcher, command)] (登録順、 重複は除く)。"""
    out = []
    seen = set()
    for p in paths:
        try:
            d = json.loads(Path(p).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        for entry in (d.get("hooks") or {}).get("PreToolUse") or []:
            if not isinstance(entry, dict):
                continue
            m = entry.get("matcher") or ".*"
            for h in entry.get("hooks") or []:
                c = (h or {}).get("command") if isinstance(h, dict) else None
                if c and (m, c) not in seen:
                    seen.add((m, c))
                    out.append((m, c))
    return out


def matcher_hits(matcher, tool):
    """PreToolUse の matcher (正規表現・完全一致) が tool 名に当たるか。"""
    try:
        return bool(re.fullmatch(matcher, tool))
    except re.error:
        return matcher == tool


def run_hook(cmd, payload, timeout=HOOK_TIMEOUT):
    """hook を実行 → (verdict, 説明)。 verdict = 'ask'|'deny'|'block'|'error'|None。"""
    try:
        pr = subprocess.run(os.path.expanduser(cmd), shell=True, input=json.dumps(payload),
                            capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        return ("error", f"hook を実行できない: {e}")
    if pr.returncode == 2:
        return ("block", first_line(pr.stderr))
    try:
        obj = json.loads((pr.stdout or "").strip() or "{}")
        dec = (obj.get("hookSpecificOutput") or {}).get("permissionDecision")
    except (ValueError, AttributeError):
        dec = None
    if dec in ("ask", "deny"):
        return (dec, first_line(pr.stderr) or first_line(pr.stdout))
    return (None, "")


def brief_input(tool, inp):
    if tool == "Bash":
        cmd = str(inp.get("command", "")).strip()
        return first_line(cmd, 110)
    for k in ("file_path", "notebook_path", "url", "path", "pattern"):
        if inp.get(k):
            return str(inp[k])[:120]
    return ""


def diagnose(reqs_list, uses, before, after, hooks, long_limit, run_hooks=True, cwd=None):
    """dialog ごとに (req, 種別, 理由, 詳細) を返す。 種別 = hook / length / rule / unmatched。"""
    rows = []
    for r in reqs_list:
        lo, hi = r["emit"] - before, r["emit"] + after
        cands = [u for u in uses if lo <= u["t"] <= hi and names_match(r["tool"], u["name"])]
        if not cands:
            rows.append((r, "unmatched", "対応する tool 呼び出しを transcript で見つけられない", ""))
            continue
        u = min(cands, key=lambda x: abs(x["t"] - r["emit"]))
        tool = u["name"]
        inp = u["input"] if isinstance(u["input"], dict) else {}
        detail = brief_input(tool, inp)
        hit = None
        if run_hooks:
            payload = {"session_id": "permission-dialog-audit", "transcript_path": "/dev/null",
                       "cwd": str(cwd or Path.home()), "hook_event_name": "PreToolUse",
                       "tool_name": tool, "tool_input": inp}
            for matcher, cmd in hooks:
                if not matcher_hits(matcher, tool):
                    continue
                v, msg = run_hook(cmd, payload)
                if v:
                    hit = (os.path.basename(cmd.split()[0]), v, msg)
                    break
        if hit:
            # block (exit 2) は Claude にしか返らない = dialog は出ない。 ∴ 当時 dialog が出た
            # この形も、 今は hook が先に止める (= 対処済み) と読める。 ask/deny は今も出る。
            rows.append((r, "fixed" if hit[1] == "block" else "hook",
                         f"{hit[0]} が {hit[1]}", hit[2] or detail))
            continue
        if tool == "Bash" and len(str(inp.get("command", ""))) > long_limit:
            n = len(str(inp.get("command", "")))
            rows.append((r, "length", f"command が {n:,} 文字 (閾値 {long_limit:,} 超)", detail))
            continue
        uniq = per_call_unique_reason(inp)
        if uniq:
            rows.append((r, "rule_unique", f"hook は無反応 + {uniq}", detail))
            continue
        rows.append((r, "rule", "hook は無反応 = permission rule 側", detail))
    return rows


# 呼び出しごとに変わる token = 「常に許可」 の literal 保存が二度と一致しない印
# (claude-code-permissions.md#always-allow-never-matches-again)
_UNIQ_PATTERNS = (
    (re.compile(r"/tool-results/"), "tool 出力の spill file (乱数 file 名)"),
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
     "path に session UUID"),
)


def per_call_unique_reason(inp):
    """tool 入力に per-call 一意な token があれば理由を返す (無ければ None)。"""
    text = " ".join(
        str(inp.get(k, "")) for k in ("command", "file_path", "path", "pattern")
    )
    hits = [why for pat, why in _UNIQ_PATTERNS if pat.search(text)]
    return " + ".join(hits) if hits else None


def print_diagnosis(rows, run_hooks, hooks_n):
    if not rows:
        print("対象の dialog なし")
        return
    by = {}
    for _r, kind, _why, _d in rows:
        by[kind] = by.get(kind, 0) + 1
    print(f"permission dialog {len(rows)} 件 — 原因: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
    print(f"  (PreToolUse hook {hooks_n} 本を実際に流し直して判定)" if run_hooks
          else "  (--no-run-hooks: hook を実行していないので hook 由来も rule に混ざる)")
    print("  ⚠️ 判定は「**今の**設定に当時の入力を流した結果」。 その後 hook を直していれば、"
          " 当時 hook 由来だった dialog も今は rule / fixed と出る (= もう出ない、 と読む)")
    print("")
    for r, kind, why, detail in rows:
        print(f"{fmt_t(r['emit'])}  {r['tool']}  [{kind}] {why}")
        if detail:
            print(f"      {detail}")
        print(f"      → {FIXES.get(kind, '')}")


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

        # --- --diagnose ---
        check(matcher_hits("Edit|Write|Bash", "Edit") and not matcher_hits("Edit|Write|Bash", "Read"),
              "matcher は完全一致 (Edit|Write|Bash に Read は当たらない)")
        check(matcher_hits("mcp__.*__(search_emails|list_events)", "mcp__gmail-lab__search_emails"),
              "matcher の正規表現 (mcp__.*__…) が当たる")
        check(not matcher_hits("Bash", "BashOutput"), "前方一致で誤爆しない (Bash は BashOutput に当たらない)")

        hd = tmp / "hooks"
        hd.mkdir()
        (hd / "ask.sh").write_text(
            '#!/bin/sh\necho "理由の 1 行目" >&2\n'
            'printf \'{"hookSpecificOutput":{"permissionDecision":"ask"}}\'\n', encoding="utf-8")
        (hd / "block.sh").write_text('#!/bin/sh\necho "長すぎる" >&2\nexit 2\n', encoding="utf-8")
        (hd / "quiet.sh").write_text('#!/bin/sh\nexit 0\n', encoding="utf-8")
        for f in ("ask.sh", "block.sh", "quiet.sh"):
            os.chmod(hd / f, 0o755)
        check(run_hook(f"sh {hd}/ask.sh", {})[0] == "ask", "hook の permissionDecision:ask を読む")
        check(run_hook(f"sh {hd}/ask.sh", {})[1] == "理由の 1 行目", "hook の stderr 先頭行を理由に使う")
        check(run_hook(f"sh {hd}/block.sh", {})[0] == "block", "hook の exit 2 を block と判定")
        check(run_hook(f"sh {hd}/quiet.sh", {})[0] is None, "無反応の hook は verdict なし")
        check(run_hook(f"{hd}/does-not-exist.sh", {})[0] in (None, "error"), "存在しない hook で落ちない")

        st = tmp / "settings.json"
        st.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": f"sh {hd}/quiet.sh"}]},
            {"matcher": "Write", "hooks": [{"type": "command", "command": f"sh {hd}/ask.sh"}]},
        ]}}), encoding="utf-8")
        hooks = load_pretooluse_hooks([str(st), str(tmp / "missing.json")])
        check(len(hooks) == 2, "settings から PreToolUse hook を読む (無い file は無視)")

        def req(tool, t):
            return {"emit": t, "resp": None, "tool": tool, "decision": "once", "session": "s"}

        du = [{"t": 1000.0, "name": "Bash", "input": {"command": "x" * 5000}, "id": "1", "sub": False, "path": tmp},
              {"t": 2000.0, "name": "Bash", "input": {"command": "ls"}, "id": "2", "sub": False, "path": tmp},
              {"t": 3000.0, "name": "Write", "input": {"file_path": "/x/y.md"}, "id": "3", "sub": False, "path": tmp}]
        rows = diagnose([req("Bash", 1000.0), req("Bash", 2000.0), req("Write", 3000.0), req("Edit", 9000.0)],
                        du, 8.0, 2.0, hooks, 3000, run_hooks=True, cwd=tmp)
        kinds = [k for _r, k, _w, _d in rows]
        check(kinds == ["length", "rule", "hook", "unmatched"],
              f"分類: 長い Bash=length / 短い Bash=rule / ask 返す hook=hook / 突合不能=unmatched (got {kinds})")
        check("5,000 文字" in rows[0][2], "length の理由に実際の文字数が出る")
        check(rows[2][3] == "理由の 1 行目", "hook の理由を詳細に載せる")
        rows_nb = diagnose([req("Write", 3000.0)], du, 8.0, 2.0, hooks, 3000, run_hooks=False, cwd=tmp)
        check(rows_nb[0][1] == "rule", "--no-run-hooks では hook 由来も rule に落ちる (= 表示で断る)")

        # per-call 一意な path は rule でなく rule_unique (= 「常に許可」 が効かない class)
        check(per_call_unique_reason({"command": "ls"}) is None,
              "普通の command は per-call 一意でない")
        spill = ("sed -n '/x/p' ~/.claude/projects/-p/"
                 "0a76b26b-4d95-42a6-a37d-7472326951ee/tool-results/b7cz1bf2n.txt")
        why = per_call_unique_reason({"command": spill})
        check(why and "spill" in why and "UUID" in why,
              f"spill file path は乱数 file 名と session UUID の両方を挙げる (got {why})")
        du_u = [{"t": 4000.0, "name": "Bash", "input": {"command": spill},
                 "id": "9", "sub": False, "path": tmp}]
        rows_u = diagnose([req("Bash", 4000.0)], du_u, 8.0, 2.0, [], 3000,
                          run_hooks=False, cwd=tmp)
        check(rows_u[0][1] == "rule_unique",
              f"spill file を読む Bash は rule_unique に分類 (got {rows_u[0][1]})")
        check("rule_unique" in FIXES, "rule_unique に消し方の文言がある")

        st2 = tmp / "settings2.json"
        st2.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": f"sh {hd}/block.sh"}]}]}}), encoding="utf-8")
        rows_b = diagnose([req("Bash", 2000.0)], du, 8.0, 2.0,
                          load_pretooluse_hooks([str(st2)]), 3000, run_hooks=True, cwd=tmp)
        check(rows_b[0][1] == "fixed", "block を返す hook は fixed (= 今はもう dialog が出ない) と分類")
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
    ap.add_argument("--diagnose", action="store_true",
                    help="dialog 1 件ごとに原因 (hook / 長さ / rule) を切り分けて消し方を出す")
    ap.add_argument("--no-run-hooks", action="store_true",
                    help="--diagnose で hook を実際に実行しない (= 副作用のある PreToolUse hook を書いている場合)")
    ap.add_argument("--long-limit", type=int, default=3000,
                    help="--diagnose で「長すぎる Bash」 とみなす文字数 (既定 3000)")
    ap.add_argument("--settings", default=DEFAULT_SETTINGS,
                    help="hook 定義を読む settings (カンマ区切り)")
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
    if a.diagnose:
        sel = sorted(reqs.values(), key=lambda x: x["emit"])
        if a.latest:
            sel = sel[-a.latest:]
        uses, _ = load_tool_events(projects, a.since)
        hooks = load_pretooluse_hooks([s.strip() for s in a.settings.split(",") if s.strip()])
        rows = diagnose(sel, uses, a.before, a.after, hooks, a.long_limit,
                        run_hooks=not a.no_run_hooks, cwd=home / "Claude")
        print_diagnosis(rows, not a.no_run_hooks, len(hooks))
        return 0
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
