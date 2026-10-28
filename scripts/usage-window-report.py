#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""usage-window-report.py — この機械の Claude Code の会話記録から、 ある時間帯に何がどれだけ token を使ったかを、 設定フォルダ × model・session・時間ごとに数える (読むだけ)。

用途: 「週の使用枠を半日で使い切った、 何が食ったか」 を数で答える。 1 つの Workflow の run の中の内訳は
scripts/workflow-run-stats.py、 起動の前の見積もりは scripts/workflow-estimate.py。 規約 = conventions/multi-session-coordination.md#workflow-agent-model。

読む記録: <設定フォルダ>/projects/**/*.jsonl (既定の設定フォルダ = ~/.claude と ~/.claude-* のうち projects/ を持つもの。
  `--config-dir` で替える)。 assistant の行の message.usage と message.model を、 message.id ごとに 1 回だけ、 その id の最も早い時刻で数える
  (1 つの応答が content の塊ごとに複数の行になり、 どの行も同じ usage を持つ = 足すと二重になる。 1 つの応答の塊が
  数分にわたって書かれ、 時間帯の境をまたぐことがある = 実測。 どちらの時刻で使用枠に数えられるかは公開されていない
  ので、 最初の時刻に揃える = 境の差はその 1 応答分)。 model が `<synthetic>` の行は数えない。
  subagent の記録 (path に subagents/ を含む) は、 親の session id で数え、 本体 (main) か subagent (sub) かを印にする。

重み (入力換算): input × 1 + cache 書き込み × 1.25 + cache 読み × 0.1 + output × 5 (Claude の定価の比。 workflow-run-stats.py と
  同じ。 `--weights` で替える)。 ⚠️ Anthropic が使用枠をどう数えるかは公開されていない = 割合は目安。

出すもの:
  既定 (時間帯)   設定フォルダ × model の合計、 `--model` に当たる model の session ごとの順位 (割合・最初と最後の時刻・main/sub)、
                  同じ model の 1 時間ごとの量 (UTC)
  `--session <id の先頭>`   その session 1 本の内訳 = 本体の model ごと、 subagent を Workflow の run ごと (名前・計画の体数・
                  状態・分は <session>/workflows/wf_*.json から) と素の Agent にまとめて、 重みの順に

usage:
  usage-window-report.py --since 2026-01-02T09:00:00Z [--until …] [--model fable] [--top 40]
  usage-window-report.py --session 0123abcd
  usage-window-report.py --selftest
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
import tempfile

WEIGHTS = (1.0, 1.25, 0.1, 5.0)   # input, cache write, cache read, output


def default_config_dirs() -> list[str]:
    home = os.path.expanduser("~")
    cands = [os.path.join(home, ".claude")] + sorted(glob.glob(os.path.join(home, ".claude-*")))
    return [d for d in cands if os.path.isdir(os.path.join(d, "projects"))]


def usage_rows(path: str):
    """{message id: (model, timestamp, session id, (in, cache write, cache read, out))} for one transcript file."""
    seen = {}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return seen
    with fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message")
            if not isinstance(m, dict):
                continue
            u, model = m.get("usage"), m.get("model")
            if not isinstance(u, dict) or not model or model == "<synthetic>":
                continue
            key = m.get("id") or d.get("requestId") or d.get("uuid")
            ts = str(d.get("timestamp") or "")
            if key in seen and seen[key][1] <= ts:
                continue
            seen[key] = (model, ts, str(d.get("sessionId") or ""),
                         tuple(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                             "cache_read_input_tokens", "output_tokens")))
    return seen


def weight(v, weights=WEIGHTS) -> float:
    return sum(v[i] * weights[i] for i in range(4)) / 1e6


def _add(acc: list, v) -> None:
    for i in range(4):
        acc[i] += v[i]
    acc[4] += 1


def window_report(dirs, since, until, model_sub, weights=WEIGHTS):
    by_model = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    by_sess = collections.defaultdict(lambda: [0, 0, 0, 0, 0, "", "", "", set()])
    by_hour = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    for root in dirs:
        rows = {}
        for f in glob.glob(os.path.join(root, "projects", "**", "*.jsonl"), recursive=True):
            rel = os.path.relpath(f, os.path.join(root, "projects"))
            sub = "subagents" in rel.split(os.sep)
            for key, r in usage_rows(f).items():
                if key not in rows or r[1] < rows[key][0][1]:
                    rows[key] = (r, rel, sub)
        for (model, ts, sid, v), rel, sub in rows.values():
            if ts < since or (until and ts >= until):
                continue
            _add(by_model[(os.path.basename(root), model)], v)
            if model_sub and model_sub not in model:
                continue
            s = by_sess[(os.path.basename(root), sid)]
            _add(s, v)
            s[5] = rel.split(os.sep)[0]
            s[6] = min(s[6] or ts, ts)
            s[7] = max(s[7] or ts, ts)
            s[8].add("sub" if sub else "main")
            _add(by_hour[ts[:13]], v)
    return by_model, by_sess, by_hour


def find_session_dir(dirs, prefix):
    hits = []
    for root in dirs:
        hits += [f[:-6] for f in glob.glob(os.path.join(root, "projects", "*", prefix + "*.jsonl"))]
    return hits


def session_report(d: str, weights=WEIGHTS):
    """Main transcript by model; subagents grouped by workflow run (or plain Agent)."""
    main = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    for model, _ts, _sid, v in usage_rows(d + ".jsonl").values():
        _add(main[model], v)
    groups = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0, collections.Counter(), "", ""])
    base = os.path.join(d, "subagents")
    for f in glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True):
        parts = os.path.relpath(f, base).split(os.sep)
        if not parts[-1].startswith("agent-"):   # the run's journal.jsonl is not an agent
            continue
        g = parts[1] if parts[0] == "workflows" and len(parts) > 2 else ("(plain Agent)" if len(parts) == 1 else parts[0])
        G = groups[g]
        G[5] += 1
        for model, ts, _sid, v in usage_rows(f).values():
            _add(G, v)
            G[6][model] += 1
            G[7] = min(G[7] or ts, ts)
            G[8] = max(G[8] or ts, ts)
    meta = {}
    for f in glob.glob(os.path.join(d, "workflows", "wf_*.json")):
        try:
            w = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        m = re.search(r"name:\s*['\"]([^'\"]+)", w.get("script") or "")
        meta[os.path.basename(f)[:-5]] = (w.get("workflowName") or (m.group(1) if m else "?"), w.get("agentCount"),
                                         w.get("status"), round((w.get("durationMs") or 0) / 60000))
    return main, groups, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", help="ISO 時刻 (UTC、 記録の timestamp と文字列で比べる。 例 2026-01-02T09:00:00Z)")
    ap.add_argument("--until", default="", help="ISO 時刻 (含まない)。 既定 = 終わりなし")
    ap.add_argument("--model", default="", help="session ごと・時間ごとに数える model の部分一致 (例 fable)。 既定 = 全部")
    ap.add_argument("--session", help="session id の先頭 = その session の内訳")
    ap.add_argument("--config-dir", action="append", help="読む設定フォルダ (繰り返し可)")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--weights", help="input,cache_write,cache_read,output (既定 1,1.25,0.1,5)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    weights = tuple(float(x) for x in a.weights.split(",")) if a.weights else WEIGHTS
    dirs = [os.path.expanduser(x) for x in a.config_dir] if a.config_dir else default_config_dirs()
    if a.session:
        hits = find_session_dir(dirs, a.session)
        if len(hits) != 1:
            print(f"session {a.session!r}: {len(hits)} 件 ({', '.join(hits[:5])})", file=sys.stderr)
            return 1
        main_, groups, meta = session_report(hits[0], weights)
        print(f"== {hits[0]}\n== 本体")
        for k, v in main_.items():
            print(f"  {k:24s} msgs={v[4]:5d} cw={v[1]/1e6:6.2f}M cr={v[2]/1e6:7.2f}M out={v[3]/1e6:5.2f}M w={weight(v, weights):6.2f}")
        tot = sum(weight(v, weights) for v in groups.values()) or 1
        print("== subagent (Workflow の run ごと、 重みの順)")
        for g, v in sorted(groups.items(), key=lambda kv: -weight(kv[1], weights)):
            name, n, st, mins = meta.get(g, ("", "", "", ""))
            models = ",".join(f"{k.replace('claude-', '')}:{c}" for k, c in v[6].most_common())
            print(f"{weight(v, weights):7.2f} ({100*weight(v, weights)/tot:4.1f}%) {g:18s} {str(name)[:38]:38s} agents={v[5]:3d}/{n} "
                  f"{st} {mins}min msgs={v[4]:4d} out={v[3]/1e6:4.2f}M cw={v[1]/1e6:5.2f}M {v[7][5:16]}->{v[8][5:16]} [{models}]")
        print("total subagent w =", round(tot, 2))
        return 0
    if not a.since:
        ap.error("--since か --session が要る")
    by_model, by_sess, by_hour = window_report(dirs, a.since, a.until, a.model, weights)
    print(f"== 設定フォルダ × model  since {a.since} until {a.until or '(now)'}  (読んだ設定フォルダ: {', '.join(dirs)})")
    for k, v in sorted(by_model.items(), key=lambda kv: -weight(kv[1], weights)):
        print(f"{k[0]:16s} {k[1]:26s} msgs={v[4]:6d} in={v[0]/1e6:6.2f}M cw={v[1]/1e6:6.2f}M cr={v[2]/1e6:8.2f}M "
              f"out={v[3]/1e6:5.2f}M  w={weight(v, weights):7.2f}")
    tot = sum(weight(v, weights) for v in by_sess.values()) or 1
    print(f"\n== session ごと (model ~ {a.model or '*'}、 重みの順)、 合計 w = {round(tot, 2)}")
    for k, v in sorted(by_sess.items(), key=lambda kv: -weight(kv[1], weights))[:a.top]:
        print(f"{weight(v, weights):7.2f} ({100*weight(v, weights)/tot:5.1f}%) {k[0]:15s} {k[1][:8]} {v[5][:42]:42s} msgs={v[4]:5d} "
              f"out={v[3]/1e6:5.2f}M cr={v[2]/1e6:7.2f}M cw={v[1]/1e6:5.2f}M {v[6][5:16]}->{v[7][5:16]} {','.join(sorted(v[8]))}")
    print(f"\n== 1 時間ごと (UTC、 model ~ {a.model or '*'})")
    for k in sorted(by_hour):
        v = by_hour[k]
        print(f"{k}  w={weight(v, weights):6.2f} msgs={v[4]:5d} out={v[3]/1e6:5.2f}M")
    return 0


def selftest() -> int:
    fails = []

    def check(name, ok):
        print(("ok: " if ok else "FAIL: ") + name)
        if not ok:
            fails.append(name)

    def line(mid, model, ts, sid, u):
        return json.dumps({"type": "assistant", "timestamp": ts, "sessionId": sid,
                           "message": {"id": mid, "model": model, "usage": dict(zip(
                               ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"), u))}})

    with tempfile.TemporaryDirectory() as root:
        proj = os.path.join(root, "projects", "-cwd")
        os.makedirs(os.path.join(proj, "s1", "subagents", "workflows", "wf_a"))
        os.makedirs(os.path.join(proj, "s1", "workflows"))
        with open(os.path.join(proj, "s1.jsonl"), "w") as fh:
            # the same message id on two lines (two content blocks) counts once
            fh.write(line("m1", "claude-fable-5", "2026-01-01T10:00:00Z", "s1", (0, 1_000_000, 0, 0)) + "\n")
            fh.write(line("m1", "claude-fable-5", "2026-01-01T10:00:00Z", "s1", (0, 1_000_000, 0, 0)) + "\n")
            fh.write(line("m2", "<synthetic>", "2026-01-01T10:00:01Z", "s1", (9, 9, 9, 9)) + "\n")
            fh.write(line("m3", "claude-opus-5", "2026-01-01T08:00:00Z", "s1", (1_000_000, 0, 0, 0)) + "\n")
        with open(os.path.join(proj, "s1", "subagents", "workflows", "wf_a", "agent-x.jsonl"), "w") as fh:
            fh.write(line("m4", "claude-fable-5", "2026-01-01T11:00:00Z", "s1", (0, 0, 10_000_000, 200_000)) + "\n")
        with open(os.path.join(proj, "s1", "subagents", "agent-y.jsonl"), "w") as fh:
            fh.write(line("m5", "claude-opus-5", "2026-01-01T11:30:00Z", "s1", (0, 0, 0, 100_000)) + "\n")
        with open(os.path.join(proj, "s1", "subagents", "workflows", "wf_a", "journal.jsonl"), "w") as fh:
            fh.write(json.dumps({"type": "launched"}) + "\n")
        with open(os.path.join(proj, "s1", "workflows", "wf_a.json"), "w") as fh:
            json.dump({"script": "export const meta = { name: 'demo-run' }", "agentCount": 3, "status": "done",
                       "durationMs": 120000}, fh)
        bm, bs, bh = window_report([root], "2026-01-01T09:00:00Z", "", "fable")
        check("dedupe by message id + window + synthetic dropped",
              bm[(os.path.basename(root), "claude-fable-5")][4] == 2 and (os.path.basename(root), "claude-opus-5") in bm
              and bm[(os.path.basename(root), "claude-opus-5")][4] == 1)
        check("weights: cache write 1.25, cache read 0.1, output 5",
              abs(weight(bm[(os.path.basename(root), "claude-fable-5")]) - (1.25 + 1.0 + 1.0)) < 1e-9)
        s = bs[(os.path.basename(root), "s1")]
        check("session row: fable only, main and sub marked", s[4] == 2 and s[8] == {"main", "sub"})
        check("by hour (UTC)", sorted(bh) == ["2026-01-01T10", "2026-01-01T11"])
        bm2, _, _ = window_report([root], "2026-01-01T00:00:00Z", "2026-01-01T09:00:00Z", "")
        check("until is exclusive and earlier rows are in", sum(v[4] for v in bm2.values()) == 1)
        check("find the session by prefix", find_session_dir([root], "s1") == [os.path.join(proj, "s1")])
        main_, groups, meta = session_report(os.path.join(proj, "s1"))
        check("session report: main by model", main_["claude-fable-5"][4] == 1 and main_["claude-opus-5"][4] == 1)
        check("session report: subagents grouped by run and plain Agent",
              set(groups) == {"wf_a", "(plain Agent)"} and meta["wf_a"] == ("demo-run", 3, "done", 2))
        check("session report: the run's journal.jsonl is not counted as an agent", groups["wf_a"][5] == 1)
    print("selftest: " + ("PASS" if not fails else f"FAIL ({len(fails)})"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
