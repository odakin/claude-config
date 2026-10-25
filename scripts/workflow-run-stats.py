#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workflow-run-stats.py — 走った (走っている) Workflow の記録から、 本数・同時に走った数・時間・token・読み直した file を数え、 済んだ結果を file に書き出す (読むだけ)。

用途: workflow の割り方を数で振り返る (規約 = conventions/multi-session-coordination.md#workflow-fan-out)。 起動の前の見積もりは
scripts/workflow-estimate.py、 こちらは起動の後の実測。

読む記録 (Claude Code の Workflow の 1 run = 1 dir):
  <config>/projects/<cwd>/<session>/subagents/workflows/<runId>/
    journal.jsonl          {"type":"launched"} / {"type":"started","key","agentId","label","phase"} /
                           {"type":"result","key","agentId","result"} の行。 resume は同じ file に追記する
                           (2 回目の launched 行は無いことがある = 実測)
    agent-<agentId>.jsonl  その agent の会話記録 (assistant の行の message.usage と tool_use、 timestamp)
    agent-<agentId>.meta.json  {"description": <label>, "workflowPhase": …}
  ⚠️ 走っている run も読める (書かない)。 結果の無い agent は「途中」 か「止めたときに捨てた」 のどちらか。

数えるもの:
  - 本数: started の数、 結果のある数、 結果の無い数 (止めたら捨てる分)、 同じ key がもう一度 started した数
    (= resume で cache が効かずに走り直した。 key は (prompt, opts) から決まる)
  - 同時に走った数の最大 (agent の記録の最初と最後の時刻の重なり) と、 run の始めから終わりまでの分
  - token (phase ごと): input / cache 書き込み / cache 読み / output と、 入力換算
    (= input + 1.25 × cache 書き込み + 0.1 × cache 読み + 5 × output。 Claude の定価の比。 `--weights` で変える)
  - 起動時の文脈 (agent の 1 回目の呼び出しの入力の合計) の中央値と、 その文脈を呼び出しのたびに読み直した分の割合
    (= Σ 呼び出し回数 × 起動時の文脈 / Σ 入力。 CLAUDE.md・道具の定義・skill の一覧が載る)
  - 読み直し: 3 本以上の agent が Read した file と、 3 本以上が同じ形で打った Bash の command (`--min-agents`)

usage:
  workflow-run-stats.py <run dir>                 # 1 run の集計
  workflow-run-stats.py <run dir> --json
  workflow-run-stats.py <run dir> --export-results <out.json>
                                                  # 結果のある agent の label・phase・key・結果を 1 file に (script を
                                                  # 直した後に resume でなく新しい run へ渡す用 = 規約 #workflow-resume-prefix)
  workflow-run-stats.py --session <id の先頭>      # その session の run の一覧と 1 行の集計
  workflow-run-stats.py --latest                  # この機械で最後に書かれた run
  workflow-run-stats.py --selftest
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import statistics
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
try:
    import claude_config_dirs as ccd  # noqa: E402
except Exception:  # pragma: no cover
    ccd = None

WEIGHTS = {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0}
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def _ts(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_jsonl(path: str) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def norm_command(cmd: str) -> str:
    """Bash の command を比べる形に: 空白を詰め、 先頭の `cd <dir> &&` を外す。"""
    c = re.sub(r"\s+", " ", cmd or "").strip()
    c = re.sub(r"^cd \S+ && ", "", c)
    return c[:200]


def load_agent(path: str) -> dict:
    rows = read_jsonl(path)
    times = [t for t in (_ts(r.get("timestamp")) for r in rows) if t]
    usage = collections.Counter()
    first_ctx = None
    turns = 0
    seen = set()
    reads, bash = [], []
    for r in rows:
        if r.get("type") != "assistant":
            continue
        m = r.get("message") or {}
        mid = m.get("id")
        u = m.get("usage") or {}
        if u and not (mid and mid in seen):
            if mid:
                seen.add(mid)
            turns += 1
            for k in USAGE_KEYS:
                usage[k] += int(u.get(k) or 0)
            if first_ctx is None:
                first_ctx = sum(int(u.get(k) or 0) for k in USAGE_KEYS[:3])
        for b in m.get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            inp = b.get("input") or {}
            if b.get("name") == "Read" and inp.get("file_path"):
                reads.append(os.path.normpath(os.path.expanduser(str(inp["file_path"]))))
            elif b.get("name") == "Bash" and inp.get("command"):
                bash.append(norm_command(str(inp["command"])))
    return {
        "start": min(times) if times else None,
        "end": max(times) if times else None,
        "usage": dict(usage),
        "first_ctx": first_ctx or 0,
        "turns": turns,
        "reads": reads,
        "bash": bash,
    }


def equiv(u: dict, w: dict = WEIGHTS) -> float:
    return (u.get("input_tokens", 0) * w["input"] + u.get("cache_creation_input_tokens", 0) * w["cache_write"]
            + u.get("cache_read_input_tokens", 0) * w["cache_read"] + u.get("output_tokens", 0) * w["output"])


def load_run(run_dir: str) -> dict:
    journal = read_jsonl(os.path.join(run_dir, "journal.jsonl"))
    started, results, key_starts = [], {}, collections.defaultdict(list)
    launched = 0
    for i, r in enumerate(journal):
        t = r.get("type")
        if t == "launched":
            launched += 1
        elif t == "started":
            started.append({"i": i, "key": r.get("key"), "agentId": r.get("agentId"), "label": r.get("label"),
                            "phase": r.get("phase")})
            key_starts[r.get("key")].append(r.get("agentId"))
        elif t == "result":
            results[r.get("agentId")] = {"key": r.get("key"), "result": r.get("result")}
    agents = {}
    for p in glob.glob(os.path.join(run_dir, "agent-*.jsonl")):
        aid = os.path.basename(p)[len("agent-"):-len(".jsonl")]
        a = load_agent(p)
        meta = {}
        mp = os.path.join(run_dir, f"agent-{aid}.meta.json")
        if os.path.exists(mp):
            try:
                meta = json.load(open(mp, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        a["label"] = meta.get("description")
        a["phase"] = meta.get("workflowPhase")
        agents[aid] = a
    for s in started:
        a = agents.setdefault(s["agentId"], {"start": None, "end": None, "usage": {}, "first_ctx": 0, "turns": 0,
                                             "reads": [], "bash": []})
        a["label"] = s["label"] or a.get("label")
        a["phase"] = s["phase"] or a.get("phase")
        a["key"] = s["key"]
    for aid, a in agents.items():
        if not a.get("phase"):
            lab = a.get("label") or ""
            a["phase"] = lab.split(":", 1)[0] if ":" in lab else (lab or "?")
        a["has_result"] = aid in results
    restarted = {k: v for k, v in key_starts.items() if k and len(v) > 1}
    return {"dir": run_dir, "launched": launched, "started": started, "results": results, "agents": agents,
            "restarted": restarted}


def max_concurrency(agents: dict) -> int:
    ev = []
    for a in agents.values():
        if a.get("start") and a.get("end"):
            ev.append((a["start"], 1))
            ev.append((a["end"], -1))
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = best = 0
    for _, d in ev:
        cur += d
        best = max(best, cur)
    return best


def summarize(run: dict, weights: dict = WEIGHTS, min_agents: int = 3) -> dict:
    agents = run["agents"]
    starts = [a["start"] for a in agents.values() if a.get("start")]
    ends = [a["end"] for a in agents.values() if a.get("end")]
    span_min = ((max(ends) - min(starts)).total_seconds() / 60) if starts and ends else 0.0
    phases = collections.OrderedDict()
    for aid, a in sorted(agents.items(), key=lambda kv: kv[1]["start"].timestamp() if kv[1].get("start") else 0):
        ph = a.get("phase") or "?"
        p = phases.setdefault(ph, {"agents": 0, "with_result": 0, "turns": 0, "usage": collections.Counter(),
                                   "minutes": []})
        p["agents"] += 1
        p["with_result"] += 1 if a.get("has_result") else 0
        p["turns"] += a.get("turns", 0)
        p["usage"].update(a.get("usage") or {})
        if a.get("start") and a.get("end"):
            p["minutes"].append((a["end"] - a["start"]).total_seconds() / 60)
    tot = collections.Counter()
    for a in agents.values():
        tot.update(a.get("usage") or {})
    ctxs = [a["first_ctx"] for a in agents.values() if a.get("first_ctx")]
    base = sum(a.get("turns", 0) * a.get("first_ctx", 0) for a in agents.values())
    inp = sum(tot.get(k, 0) for k in USAGE_KEYS[:3])
    read_by = collections.defaultdict(set)
    cmd_by = collections.defaultdict(set)
    for aid, a in agents.items():
        for f in set(a.get("reads") or []):
            read_by[f].add(aid)
        for c in set(a.get("bash") or []):
            cmd_by[c].add(aid)
    dup_reads = sorted(((f, len(v)) for f, v in read_by.items() if len(v) >= min_agents), key=lambda x: -x[1])
    dup_cmds = sorted(((c, len(v)) for c, v in cmd_by.items() if len(v) >= min_agents), key=lambda x: -x[1])
    cut = [a.get("label") or aid for aid, a in agents.items() if not a.get("has_result")]
    return {
        "dir": run["dir"],
        "agents": len(agents),
        "started": len(run["started"]),
        "with_result": sum(1 for a in agents.values() if a.get("has_result")),
        "without_result": cut,
        "restarted": {k: len(v) for k, v in run["restarted"].items()},
        "restarted_labels": sorted({(agents.get(v[0]) or {}).get("label") or "?" for v in run["restarted"].values()}),
        "max_concurrency": max_concurrency(agents),
        "span_minutes": round(span_min, 1),
        "phases": {ph: {"agents": p["agents"], "with_result": p["with_result"], "turns": p["turns"],
                        "usage": dict(p["usage"]), "equiv": round(equiv(p["usage"], weights)),
                        "median_minutes": round(statistics.median(p["minutes"]), 1) if p["minutes"] else None}
                   for ph, p in phases.items()},
        "usage": dict(tot),
        "equiv": round(equiv(tot, weights)),
        "first_ctx_median": int(statistics.median(ctxs)) if ctxs else 0,
        "base_share": round(base / inp, 2) if inp else 0.0,
        "dup_reads": dup_reads,
        "dup_commands": dup_cmds,
    }


def fmt_tok(n: float) -> str:
    n = float(n)
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}k"
    return f"{n:.0f}"


def _short(path: str) -> str:
    """末尾 2 段 (dir/file) = 同じ名前の file を repo で見分ける。"""
    parts = path.rstrip("/").split("/")
    return "/".join(parts[-2:])


def render(s: dict, top: int = 10) -> str:
    out = [f"📊 workflow の実測: {s['dir']}"]
    out.append(f"  agent {s['agents']} 本 (結果あり {s['with_result']} / 結果なし {len(s['without_result'])})、"
               f" 同時に走った最大 {s['max_concurrency']} 本、 始めから終わりまで {s['span_minutes']} 分")
    if s["restarted"]:
        n = sum(v - 1 for v in s["restarted"].values())
        out.append(f"  ♻️ 同じ key がもう一度始まった = 再開で cache が効かずに走り直した {n} 本: "
                   + ", ".join(s["restarted_labels"][:top]))
    if s["without_result"]:
        out.append(f"  ✂️ 結果の無い agent {len(s['without_result'])} 本 (走っている途中か、 止めたときに捨てた分): "
                   + ", ".join(str(x) for x in s["without_result"][:top]) + (" …" if len(s["without_result"]) > top else ""))
    out.append(f"  token の入力換算 {fmt_tok(s['equiv'])} (input + 1.25×cache 書き込み + 0.1×cache 読み + 5×output)")
    out.append(f"  起動時の文脈の中央値 {fmt_tok(s['first_ctx_median'])} token、 入力のうちそれを呼び出しのたびに読み直した分 "
               f"{int(s['base_share'] * 100)}%")
    out.append("  phase ごと: 本数 (結果あり) / 呼び出し / cache 読み / output / 入力換算 / 1 本の所要 (中央値、分)")
    for ph, p in s["phases"].items():
        u = p["usage"]
        out.append(f"    {ph}: {p['agents']} ({p['with_result']}) / {p['turns']} / {fmt_tok(u.get('cache_read_input_tokens', 0))}"
                   f" / {fmt_tok(u.get('output_tokens', 0))} / {fmt_tok(p['equiv'])} / {p['median_minutes']}")
    if s["dup_reads"]:
        out.append(f"  3 本以上が Read した file {len(s['dup_reads'])} 個 (上位): "
                   + ", ".join(f"{_short(f)}×{n}" for f, n in s["dup_reads"][:top]))
    if s["dup_commands"]:
        out.append(f"  3 本以上が同じ形で打った command {len(s['dup_commands'])} 個 (上位): "
                   + " | ".join(f"{c[:60]}×{n}" for c, n in s["dup_commands"][:min(top, 5)]))
    return "\n".join(out)


def export_results(run: dict, out_path: str) -> int:
    rows = []
    seen = set()
    for s in run["started"]:
        r = run["results"].get(s["agentId"])
        if r is None or s["key"] in seen:
            continue
        seen.add(s["key"])
        rows.append({"label": s["label"], "phase": s["phase"], "key": s["key"], "agentId": s["agentId"],
                     "result": r["result"]})
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"run": run["dir"], "results": rows}, f, ensure_ascii=False, indent=1)
    return len(rows)


def run_dirs_for_session(prefix: str) -> list[str]:
    roots = ccd.projects_dirs() if ccd else [os.path.expanduser("~/.claude/projects")]
    out = []
    for root in roots:
        out += glob.glob(os.path.join(root, "*", prefix + "*", "subagents", "workflows", "*"))
    return sorted(d for d in out if os.path.isfile(os.path.join(d, "journal.jsonl")))


def latest_run_dir() -> str | None:
    roots = ccd.projects_dirs() if ccd else [os.path.expanduser("~/.claude/projects")]
    cands = []
    for root in roots:
        cands += glob.glob(os.path.join(root, "*", "*", "subagents", "workflows", "*", "journal.jsonl"))
    if not cands:
        return None
    return os.path.dirname(max(cands, key=os.path.getmtime))


# ---------------------------------------------------------------- selftest
def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _fake_agent(path, t0, minutes, turns, ctx, reads=(), cmds=()):
    rows = [{"type": "user", "timestamp": f"2026-01-01T00:{t0:02d}:00.000Z", "message": {"content": "task"}}]
    for i in range(turns):
        content = []
        if i == 0:
            content = [{"type": "tool_use", "name": "Read", "input": {"file_path": p}} for p in reads]
            content += [{"type": "tool_use", "name": "Bash", "input": {"command": c}} for c in cmds]
        rows.append({"type": "assistant", "timestamp": f"2026-01-01T00:{t0 + (minutes if i == turns - 1 else 0):02d}:00.000Z",
                     "message": {"id": f"m{i}", "content": content,
                                 "usage": {"input_tokens": 1, "cache_creation_input_tokens": ctx if i == 0 else 10,
                                           "cache_read_input_tokens": 0 if i == 0 else ctx, "output_tokens": 100}}})
        # the same message id split over two records must count once
        if i == 0:
            rows.append(dict(rows[-1]))
    _write_jsonl(path, rows)


def selftest() -> int:
    fails = 0

    def check(name, cond, detail=""):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
        fails += 0 if cond else 1

    with tempfile.TemporaryDirectory() as d:
        run = os.path.join(d, "wf_test-000")
        os.makedirs(run)
        _write_jsonl(os.path.join(run, "journal.jsonl"), [
            {"type": "launched"},
            {"type": "started", "key": "v2:aaa", "agentId": "a1", "label": "read:x", "phase": "Read"},
            {"type": "started", "key": "v2:bbb", "agentId": "a2", "label": "read:y", "phase": "Read"},
            {"type": "result", "key": "v2:aaa", "agentId": "a1", "result": {"n": 1}},
            {"type": "started", "key": "v2:ccc", "agentId": "a3", "label": "verify:x", "phase": "Verify"},
            {"type": "result", "key": "v2:bbb", "agentId": "a2", "result": {"n": 2}},
            # resume: the same key starts again under a new agent
            {"type": "started", "key": "v2:aaa", "agentId": "a4", "label": "read:x", "phase": "Read"},
        ])
        _fake_agent(os.path.join(run, "agent-a1.jsonl"), 0, 5, 3, 1000, reads=["/r/SESSION.md", "/r/CLAUDE.md"],
                    cmds=["cd /r && git log -5", "board-view.py"])
        _fake_agent(os.path.join(run, "agent-a2.jsonl"), 0, 4, 2, 1000, reads=["/r/SESSION.md"], cmds=["git log -5"])
        _fake_agent(os.path.join(run, "agent-a3.jsonl"), 6, 3, 2, 1200, reads=["/r/SESSION.md"], cmds=["git  log -5"])
        _fake_agent(os.path.join(run, "agent-a4.jsonl"), 20, 1, 1, 1000)
        r = load_run(run)
        s = summarize(r)
        check("agents counted from journal and files", s["agents"] == 4, s["agents"])
        check("with result = 2", s["with_result"] == 2, s["with_result"])
        check("without result lists the cut and the re-run", sorted(s["without_result"]) == ["read:x", "verify:x"], s["without_result"])
        check("restarted key found once", s["restarted"] == {"v2:aaa": 2}, s["restarted"])
        check("max concurrency = 2 (a1 and a2 overlap, a3 starts after a2 ends)", s["max_concurrency"] == 2, s["max_concurrency"])
        check("turns dedupe split records of one message", s["phases"]["Read"]["turns"] == 3 + 2 + 1, s["phases"]["Read"]["turns"])
        check("first context median (input + cache write + cache read of turn 1)", s["first_ctx_median"] == 1001, s["first_ctx_median"])
        u = s["usage"]
        exp_cr = 1000 * 2 + 1000 * 1 + 1200 * 1
        check("cache read sum", u["cache_read_input_tokens"] == exp_cr, u)
        check("base share in (0, 1]", 0 < s["base_share"] <= 1, s["base_share"])
        check("SESSION.md read by 3 agents is a re-read", ("/r/SESSION.md", 3) in s["dup_reads"], s["dup_reads"])
        check("git log normalized across cd prefix and spaces", ("git log -5", 3) in s["dup_commands"], s["dup_commands"])
        out = os.path.join(d, "out.json")
        n = export_results(r, out)
        data = json.load(open(out, encoding="utf-8"))
        check("export writes one row per key with a result", n == 2 and [x["label"] for x in data["results"]] == ["read:x", "read:y"], data)
        txt = render(s)
        check("render mentions re-run and cut", "走り直した 1 本" in txt and "結果の無い agent 2 本" in txt, txt)
        # a run dir without agent files (journal only) still summarizes
        run2 = os.path.join(d, "wf_test-001")
        os.makedirs(run2)
        _write_jsonl(os.path.join(run2, "journal.jsonl"), [{"type": "started", "key": "k", "agentId": "z", "label": "a"}])
        s2 = summarize(load_run(run2))
        check("journal-only run", s2["agents"] == 1 and s2["max_concurrency"] == 0, s2)
    print("selftest:", "OK" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--session")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--export-results")
    ap.add_argument("--min-agents", type=int, default=3)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--weights", help="input,cache_write,cache_read,output (既定 1,1.25,0.1,5)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    weights = dict(WEIGHTS)
    if a.weights:
        vals = [float(x) for x in a.weights.split(",")]
        weights = dict(zip(("input", "cache_write", "cache_read", "output"), vals))
    if a.session:
        dirs = run_dirs_for_session(a.session)
        if not dirs:
            print(f"run が見つからない (session {a.session})", file=sys.stderr)
            return 1
        for d in dirs:
            s = summarize(load_run(d), weights, a.min_agents)
            print(f"{os.path.basename(d)}: agent {s['agents']} (結果あり {s['with_result']}), 同時最大 {s['max_concurrency']},"
                  f" {s['span_minutes']} 分, 入力換算 {fmt_tok(s['equiv'])}, 走り直し {sum(v - 1 for v in s['restarted'].values())}")
        return 0
    run_dir = a.run_dir or (latest_run_dir() if a.latest else None)
    if not run_dir or not os.path.isfile(os.path.join(run_dir, "journal.jsonl")):
        ap.error("run の dir (journal.jsonl のある dir) か --session / --latest を渡す")
    run = load_run(run_dir)
    if a.export_results:
        n = export_results(run, a.export_results)
        print(f"結果 {n} 件を {a.export_results} に書いた")
        return 0
    s = summarize(run, weights, a.min_agents)
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=1, default=str))
    else:
        print(render(s, a.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
