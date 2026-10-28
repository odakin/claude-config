#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workflow-estimate.py — Workflow の script を起動の前に空回しして、 起こす agent の本数・波数 (同時実行の上限で割った数)・観点ごとの分け方・再開で cache が効く本数を出す (読むだけ)。

用途: 起動の前に「何本・何波か」 を起票者に見せる (規約 = conventions/multi-session-coordination.md#workflow-estimate-before-launch)。
起動の後の実測は scripts/workflow-run-stats.py。

しくみ: script を node の vm で、 agent() を差し替えて最後まで走らせる (agent は起こさない、 token を使わない)。
  - agent(prompt, opts) は呼び出しを記録し、 schema があれば schema どおりの見本の値を返す。 見本の配列の長さを k と
    置き (既定 k = 1, 3, 10)、 boolean は true、 文字列は毎回ちがう値 (= 前段の出力で後段の本数が決まる形は、 k に応じて
    本数がふえる = 「前段 1 件ごとに約 S 本」 と出る)。 boolean を true にするので、 filter で絞る形は多めに数える (上の見積もり)
  - parallel / pipeline は本物と同じく、 thunk・stage の呼び出しを後回しにする (= その後ろで同期に呼んだ agent() が先に
    始まる。 実測 = parallel の後ろの単発の agent が 5 秒先に始まった)
  - phase / log / args / budget (total = null) / workflow (入れ子は数えずに null) を用意する。 Date.now / Math.random は
    本物と同じく投げる
  - node は `--disallow-code-generation-from-strings` と permission model (file は runner だけ読める) で起こす = script から
    file・別 process・Node の API に届かない (vm だけでは Function の constructor から process に届く = 実測)。 flag を
    持たない node (19 以下) では走らせずに見積もりの失敗を返す
  - 呼び出しが 5000 本を越えたら止めて「前段の出力次第で止まらない形」 と出す
静的にも見る (source の正規表現): 観点の配列 (`['a','b'].map(… agent(`) と同じ問いの票 (`Array.from({length: N}` … agent(`)。
  正規表現なので、 `Array.from({length: N}, …)` で番号ごとに違う prompt を並べる形と、 短い文字列の配列を直に `.map` で
  並べる形 (入力の一覧) も観点・票と読む (誤検出、 実測)。 本当に分割でないなら、 一覧を変数に入れてから `.map` するか、
  `// workflow-lenses: independent — <理由>` を書く。
宣言 (script の注釈の行):
  // workflow-size: <本数> — <理由>          (k=3 の見積もりが max(10, 上限) 本を越える・本数が前段の出力で決まるときに書く。
                                              10 = harness の既定の目安 〔medium = 10 本未満〕)
  // workflow-lenses: independent — <理由>  (観点・票を別の agent に分けるのは独立が要るときだけ = 盲検・独立の票)
  // workflow-resume: rerun-ok — <理由>     (再開で済んだ結果を走り直してよいとき)
同時実行の上限 = min(16, CPU 数 − 2) (Workflow の仕様)。 `--cap` で変える。

再開の見込み (`--resume-dir <前の run の dir>` か hook の resumeFromRunId):
  前の run の journal で結果のある agent の prompt (agent の記録の「computed task」 の本文) と label を読み、 空回しの
  呼び出しの順に、 前の run に同じ (label, prompt) の結果があるかを見る。 Workflow の再開は「前から順に変わっていない
  呼び出しだけ cache を返し、 最初に変わった・新しい呼び出しから後ろは全部走る」 (仕様の文言) ので、 最初に前の run に
  無い呼び出しが来た所で cache は終わる、 として数える。 schema・model の変更は記録に無いので見ない (= 多めに見積もる)。
  cache の key は (prompt, opts) だけでなく parallel / pipeline の中の位置でも決まる (実測 = 項目の並びだけを入れ替えた
  再開は 1 本も cache から返らず、 元の並びに戻すと全部返った。 args は key に入らない)。 前の run の最初の波 (journal で
  最初の結果より前に始まった呼び出し) は項目の並びどおりに始まるので、 空回しの同じ番目の呼び出しと (label, prompt) が
  違えば並びが変わったとみなし、 そこから後ろを走り直しに数える。 最初の波より後ろの並びの入れ替えは見えない。
  同じ run を別の並びで再開した後は、 その並びの結果も cache にあるが、 見積もりは最初の並びだけを基準にする (少なめに出す)
  (規約 = conventions/multi-session-coordination.md#workflow-resume-prefix)。

hook (`--hook`、 PreToolUse の Workflow): stdin の hook 入力から script (inline の script / scriptPath / name) と args と
resumeFromRunId を読み、 見積もりを additionalContext で出す。 enforce (= `~/.claude/workflow-fanout-enforce.on` が在るか
env WORKFLOW_FANOUT_ENFORCE=1) のときだけ次をする:
  - 本人に聞く (permissionDecision = ask、 宣言があっても): その機械で一度に走れる本数 (上限) を k = 1, 3, 10 のどれかで
    越える、 または本数が前段の出力で決まる (2026-10-28 本人の裁定 = 「一度に走れる本数までは聞かずに走らせ、 越える
    並べ方だけ起動の前に本数・波数・待ちを見せて本人の OK を取る」。 宣言の 1 行で通すと agent が自分で許可できるため)
  - 止める (exit 2): 宣言の無い (c) 観点・票の分割 (d) 再開で cache が 0 本なのに前の run の結果を走り直す。
  無人の run (claude -p) では聞く相手がいない = 上限を越える Workflow は起こさない形にする。
故障 (node が無い・script が読めない・空回しが途中で止まる) は通す (exit 0、 理由だけ出す)。
env: WORKFLOW_FANOUT_DISABLE=1 / WORKFLOW_ESTIMATE_NODE (node の path) / WORKFLOW_FANOUT_ENFORCE_MARKER (test) /
     WORKFLOW_ESTIMATE_CAP (上限の上書き = test)

usage:
  workflow-estimate.py <script.js> [--args '<json>' | --args @file.json] [--cap N] [--ks 1,3,10] [--json]
  workflow-estimate.py <script.js> --resume-dir <前の run の dir>
  workflow-estimate.py --hook < hook-input.json
  workflow-estimate.py --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

RULE = "claude-config/conventions/multi-session-coordination.md#workflow-fan-out"
CALL_CAP = 5000
SIZE_GUIDE = 10  # harness の既定の目安 (medium = 10 本未満)。 宣言が要るのは max(SIZE_GUIDE, 上限) を越えるとき
DEFAULT_KS = (1, 3, 10)

RUNNER_JS = r"""
'use strict';
const vm = require('vm');
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => main(JSON.parse(raw)));
function main(input) {
const K = input.k;
const calls = [];
const logs = [];
let curPhase = '';
let n = 0;
let nested = 0;
const cache = new Map(input.cache || []);
let live = false;
class CallCap extends Error {}
function mock(s, d) {
  if (!s || typeof s !== 'object' || d > 14) return 's' + (n++);
  if (Array.isArray(s.enum) && s.enum.length) return s.enum[0];
  if ('const' in s) return s.const;
  let t = s.type; if (Array.isArray(t)) t = t.find(x => x !== 'null') || t[0];
  if (!t && s.properties) t = 'object';
  if (!t && s.items) t = 'array';
  if (!t && Array.isArray(s.anyOf || s.oneOf)) return mock((s.anyOf || s.oneOf)[0], d + 1);
  switch (t) {
    case 'object': { const o = {}; for (const [k, v] of Object.entries(s.properties || {})) o[k] = mock(v, d + 1); return o; }
    case 'array': return Array.from({ length: d <= 2 ? K : 1 }, () => mock(s.items || {}, d + 1));  // 深い入れ子は 1 = k の累乗で膨らませない
    case 'boolean': return true;
    case 'number': case 'integer': return 1;
    case 'null': return null;
    default: return 's' + (n++);
  }
}
async function agent(prompt, opts) {
  opts = opts || {};
  if (calls.length >= input.cap_calls) throw new CallCap('call cap');
  const p = String(prompt);
  const label = opts.label ? String(opts.label) : '';
  const key = label + '\u0000' + p;
  const c = { label, phase: opts.phase ? String(opts.phase) : curPhase, model: opts.model || '', effort: opts.effort || '',
              agentType: opts.agentType || '', isolation: opts.isolation || '', plen: p.length };
  if (input.keep_prompts) c.prompt = p;
  const wave = input.first_wave || [];
  const moved = calls.length < wave.length && wave[calls.length] !== key;
  if (cache.has(key) && !moved) { c.prev = true; c.hit = !live; }
  else if (cache.has(key)) { c.prev = true; c.hit = false; c.moved = true; live = true; }
  else { c.prev = false; c.hit = false; live = true; }
  calls.push(c);
  if (cache.has(key)) return cache.get(key);
  return opts.schema ? mock(opts.schema, 0) : ('s' + (n++));
}
async function parallel(thunks) {
  await null;
  return Promise.all(Array.from(thunks || [], async (t) => {
    try { return await t(); } catch (e) { if (e instanceof CallCap) throw e; return null; }
  }));
}
async function pipeline(items, ...stages) {
  await null;
  return Promise.all(Array.from(items || [], async (item, idx) => {
    let v = item;
    for (const st of stages) {
      try { v = await st(v, item, idx); } catch (e) { if (e instanceof CallCap) throw e; return null; }
    }
    return v;
  }));
}
async function workflow() { nested++; return null; }
const SafeMath = Object.create(Math); SafeMath.random = () => { throw new Error('Math.random is unavailable'); };
const RealDate = Date;
function SafeDate(...a) { if (!a.length) throw new Error('new Date() is unavailable'); return new RealDate(...a); }
SafeDate.now = () => { throw new Error('Date.now() is unavailable'); };
SafeDate.parse = RealDate.parse; SafeDate.UTC = RealDate.UTC;
const ctx = { agent, parallel, pipeline, workflow, phase: (t) => { curPhase = String(t); }, log: (m) => { logs.push(String(m)); },
              args: input.args, budget: { total: null, spent: () => 0, remaining: () => Infinity },
              JSON, Math: SafeMath, Date: SafeDate, Array, Object, String, Number, Boolean, Set, Map, Promise, RegExp,
              Error, TypeError, Symbol, parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent,
              console: { log() {}, error() {}, warn() {} } };
vm.createContext(ctx);
let src = input.src.replace(/^\s*export\s+const\s+meta\s*=/m, 'const meta =').replace(/^\s*export\s+default\s+/m, '');
const wrapped = '(async () => {\n' + src + '\n})()';
let out = { ok: true, error: '' };
(async () => {
  try {
    const p = vm.runInContext(wrapped, ctx, { timeout: 5000 });
    await p;
  } catch (e) {
    out.ok = false;
    out.error = (e instanceof CallCap) ? 'CALL_CAP' : String(e && e.message || e).slice(0, 300);
  }
  out.calls = calls; out.logs = logs; out.nested = nested;
  process.stdout.write(JSON.stringify(out));
})();
}
"""


def machine_cap() -> int:
    env = os.environ.get("WORKFLOW_ESTIMATE_CAP", "")
    if env.isdigit() and int(env) > 0:
        return int(env)
    cpus = os.cpu_count() or 4
    return max(1, min(16, cpus - 2))


def node_path() -> str | None:
    p = os.environ.get("WORKFLOW_ESTIMATE_NODE")
    if p:
        return p if os.path.exists(p) else None
    return shutil.which("node")


def dry_run(src: str, args, k: int, cache: list | None = None, keep_prompts: bool = False,
            first_wave: list | None = None) -> dict:
    node = node_path()
    if not node:
        return {"ok": False, "error": "NO_NODE", "calls": []}
    payload = json.dumps({"src": src, "args": args, "k": k, "cache": cache or [], "keep_prompts": keep_prompts,
                          "first_wave": first_wave or [], "cap_calls": CALL_CAP})
    with tempfile.TemporaryDirectory() as d:
        # 実体の path を渡す (macOS の temp は /var → /private/var の symlink で、 node は path の解決で /var を読む)
        runner = os.path.join(os.path.realpath(d), "runner.js")
        with open(runner, "w", encoding="utf-8") as f:
            f.write(RUNNER_JS)
        p = None
        # 本物の engine は script に file も Node の API も触らせない。 vm は隔離ではない (Function の constructor から
        # process に届く = 実測) ので、 文字列から code を作るのを禁じ、 permission model で file は runner だけ読める
        # ようにする (child_process・worker も止まる)。 node 20 は --experimental-permission。 どちらも知らない node では
        # 隔離なしに走らせず、 見積もりの失敗として返す (hook は失敗を止めずに通す)
        for flags in (["--permission", f"--allow-fs-read={runner}"],
                      ["--experimental-permission", f"--allow-fs-read={runner}"]):
            try:
                p = subprocess.run([node, "--disallow-code-generation-from-strings", *flags, runner], input=payload,
                                   capture_output=True, text=True, timeout=30)
            except (subprocess.TimeoutExpired, OSError) as e:
                return {"ok": False, "error": f"RUNNER_FAILED: {e}", "calls": []}
            if "bad option" not in (p.stderr or ""):
                break
        else:
            return {"ok": False, "error": "RUNNER_FAILED: この node は隔離の flag を持たない (node 20 以上が要る)", "calls": []}
    try:
        return json.loads(p.stdout)
    except (json.JSONDecodeError, AttributeError):
        return {"ok": False, "error": "RUNNER_FAILED: " + ((p.stderr if p else "") or "")[-300:], "calls": []}


LENS_RE = re.compile(r"\[\s*(?:(['\"`])[^'\"`\n]{1,40}\1\s*,\s*)+(['\"`])[^'\"`\n]{1,40}\2\s*,?\s*\]\s*\.\s*(?:flatMap|map|forEach)\s*\(")
VOTES_RE = re.compile(r"Array\.from\(\s*\{\s*length\s*:\s*([A-Za-z0-9_.]+)\s*\}")
DECL_SIZE_RE = re.compile(r"//\s*workflow-size:\s*(\d+)\s*(.*)")
DECL_LENS_RE = re.compile(r"//\s*workflow-lenses:\s*independent\b\s*(.*)")
DECL_RESUME_RE = re.compile(r"//\s*workflow-resume:\s*rerun-ok\b\s*(.*)")


def static_scan(src: str) -> dict:
    lenses, votes = [], []
    for m in LENS_RE.finditer(src):
        window = src[m.end(): m.end() + 800]
        if "agent(" in window:
            line = src.count("\n", 0, m.start()) + 1
            lenses.append({"line": line, "text": src[m.start(): m.end()].strip()[:80]})
    for m in VOTES_RE.finditer(src):
        window = src[m.end(): m.end() + 400]
        if "agent(" in window:
            line = src.count("\n", 0, m.start()) + 1
            votes.append({"line": line, "length": m.group(1)})
    size = DECL_SIZE_RE.search(src)
    return {
        "lenses": lenses,
        "votes": votes,
        "decl_size": int(size.group(1)) if size else None,
        "decl_size_reason": (size.group(2).strip(" —-:") if size else ""),
        "decl_lenses": bool(DECL_LENS_RE.search(src)),
        "decl_resume": bool(DECL_RESUME_RE.search(src)),
    }


def by_prefix(calls: list) -> dict:
    out: dict = {}
    for c in calls:
        key = c.get("phase") or (c.get("label") or "").split(":", 1)[0] or "?"
        out[key] = out.get(key, 0) + 1
    return out


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def unindent_task(text: str) -> str | None:
    marker = "The computed task text follows:\n"
    i = text.find(marker)
    if i < 0:
        return None
    body = text[i + len(marker):]
    return "\n".join(line[2:] if line.startswith("  ") else line for line in body.split("\n"))


def load_prev_run(run_dir: str) -> dict:
    """前の run の (label, prompt) → 結果。 prompt は agent の記録の computed task の本文。"""
    jpath = os.path.join(run_dir, "journal.jsonl")
    started, results, first_wave_ids, wave_open = [], {}, [], True
    with open(jpath, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("type") == "started":
                started.append(r)
                if wave_open:
                    first_wave_ids.append(r.get("agentId"))
            elif r.get("type") == "result":
                results[r.get("agentId")] = r.get("result")
                wave_open = False
    cache, seen, key_of = [], set(), {}
    for s in started:
        aid = s.get("agentId")
        if aid not in results:
            continue
        prompt = None
        try:
            with open(os.path.join(run_dir, f"agent-{aid}.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("type") != "user":
                        continue
                    c = (r.get("message") or {}).get("content")
                    if isinstance(c, str) and c.startswith("[Workflow harness — computed task]"):
                        prompt = unindent_task(c)
                        break
        except OSError:
            continue
        if prompt is None:
            continue
        key = (s.get("label") or "") + "\u0000" + prompt
        key_of[aid] = key
        if key in seen:
            continue
        seen.add(key)
        cache.append([key, results[aid]])
    # 最初の波 = 最初の結果より前に始まった呼び出し = 項目の並びどおりの順。 prompt を読めない呼び出しで打ち切る
    first_wave = []
    for aid in first_wave_ids:
        if aid not in key_of:
            break
        first_wave.append(key_of[aid])
    return {"cache": cache, "started": len(started), "with_result": len(results), "first_wave": first_wave}


def estimate(src: str, args=None, cap: int | None = None, ks=DEFAULT_KS, resume_dir: str | None = None) -> dict:
    cap = cap or machine_cap()
    runs = {}
    for k in ks:
        r = dry_run(src, args, k)
        runs[k] = {"ok": r.get("ok"), "error": r.get("error", ""), "agents": len(r.get("calls", [])),
                   "by_phase": by_prefix(r.get("calls", [])), "logs": r.get("logs", [])[:5],
                   "nested": r.get("nested", 0)}
    k_lo, k_mid, k_hi = ks[0], ks[min(1, len(ks) - 1)], ks[-1]
    n_lo, n_mid, n_hi = runs[k_lo]["agents"], runs[k_mid]["agents"], runs[k_hi]["agents"]
    grows = n_hi > n_lo
    slope = round((n_hi - n_mid) / (k_hi - k_mid), 1) if k_hi != k_mid else 0
    res = {"cap": cap, "runs": runs, "grows": grows, "slope": slope, "k_mid": k_mid, "agents_mid": n_mid,
           "waves_mid": ceil_div(n_mid, cap) if n_mid else 0, "static": static_scan(src)}
    if resume_dir:
        prev = load_prev_run(resume_dir)
        r = dry_run(src, args, k_mid, cache=prev["cache"], first_wave=prev["first_wave"])
        calls = r.get("calls", [])
        hits = sum(1 for c in calls if c.get("hit"))
        rerun = [c.get("label") or "?" for c in calls if c.get("prev") and not c.get("hit")]
        first_live = next((c for c in calls if not c.get("hit")), None)
        res["resume"] = {"dir": resume_dir, "prev_started": prev["started"], "prev_with_result": prev["with_result"],
                         "prev_matched_prompts": len(prev["cache"]), "hits": hits, "rerun": rerun,
                         "first_live": (first_live or {}).get("label") or ("(なし)" if not first_live else "?"),
                         "first_live_prev": bool(first_live and first_live.get("prev")),
                         "first_live_moved": bool(first_live and first_live.get("moved")), "ok": r.get("ok"),
                         "error": r.get("error", "")}
    return res


def judge(res: dict) -> list[dict]:
    """宣言の無い問題の一覧 (enforce のとき止める理由)。"""
    st = res["static"]
    out = []
    n, cap = res["agents_mid"], res["cap"]
    limit = max(SIZE_GUIDE, cap)
    if (n > limit or res["grows"]) and st["decl_size"] is None:
        why = []
        if n > limit:
            why.append(f"k={res['k_mid']} で {n} 本 = {res['waves_mid']} 波 (上限 {cap}、 目安 {limit} 本まで)")
        if res["grows"]:
            why.append(f"本数が前段の出力で決まる (前段 1 件ごとに約 {res['slope']} 本)")
        out.append({"kind": "size", "text": "、 ".join(why)})
    elif st["decl_size"] is not None and res["grows"]:
        hi_k = max(res["runs"])
        if res["runs"][hi_k]["agents"] > st["decl_size"]:
            out.append({"kind": "size-soft", "text": f"k={hi_k} で {res['runs'][hi_k]['agents']} 本 = 宣言 {st['decl_size']} 本を越える"
                        " (前段の件数に上限を置き、 削った分を log() で言う)"})
    if (st["lenses"] or st["votes"]) and not st["decl_lenses"]:
        where = [f"行 {x['line']} `{x['text']}`" for x in st["lenses"]] + [f"行 {x['line']} Array.from(length: {x['length']})" for x in st["votes"]]
        out.append({"kind": "lenses", "text": "観点・票を別の agent に分けている (" + " / ".join(where[:3]) + ")"})
    rs = res.get("resume")
    if rs and rs.get("ok") and rs["hits"] == 0 and rs["rerun"] and not st["decl_resume"]:
        out.append({"kind": "resume", "text": f"再開しても cache は 0 本 (1 本目 = {rs['first_live']})、 前の run で結果の出た {len(rs['rerun'])} 本を走り直す"})
    return out


def render(res: dict, problems: list[dict] | None = None) -> str:
    cap = res["cap"]
    lines = [f"🧮 workflow の見積もり (起動の前の空回し、 agent は起こしていない): この機械の同時実行の上限 = {cap}"
             f" (min(16, CPU {os.cpu_count()} − 2))"]
    parts = []
    for k, r in res["runs"].items():
        parts.append(f"k={k} → {r['agents']} 本" + ("" if r["ok"] else f" (途中で止まった: {r['error'][:80]})"))
    lines.append("  前段が返す配列の長さを k と置いた本数: " + " / ".join(parts)
                 + (f" (前段 1 件ごとに約 {res['slope']} 本ふえる)" if res["grows"] else " (本数は script で決まる)"))
    mid = res["runs"][res["k_mid"]]
    if mid["by_phase"]:
        lines.append(f"  k={res['k_mid']} の内訳: " + " / ".join(f"{p} {c}" for p, c in mid["by_phase"].items())
                     + f" = {res['waves_mid']} 波 (1 波 = 上限 {cap} 本が並んで走る。 時間はおよそ 1 本の所要 × 波)")
    if any(r["error"] == "CALL_CAP" for r in res["runs"].values()):
        lines.append(f"  ⚠️ 空回しが {CALL_CAP} 本で止まった = 前段の出力次第で止まらない形 (loop の終わりを本数か budget で決める)")
    if any(r["error"] == "NO_NODE" for r in res["runs"].values()):
        lines.append("  (node が無いので空回しできない。 本数は数えていない)")
    st = res["static"]
    for x in st["lenses"]:
        lines.append(f"  ⚠️ 観点ごとに agent を分けている (行 {x['line']}: `{x['text']}`) = 同じ入力を観点の数だけ読み直す。"
                     " 独立が要る (盲検・互いの結論を見せない票) のでなければ、 1 本の prompt に観点を並べる")
    for x in st["votes"]:
        lines.append(f"  ⚠️ 同じ問いに {x['length']} 票の agent (行 {x['line']}) = 項目数 × 票の数だけ起きる。 項目が上限を越えるなら票は"
                     " 入力 (repo・file) ごとにまとめる")
    if st["decl_size"] is not None:
        lines.append(f"  宣言: workflow-size {st['decl_size']} 本 — {st['decl_size_reason'] or '(理由なし)'}")
    rs = res.get("resume")
    if rs:
        if not rs.get("ok") and rs.get("error"):
            lines.append(f"  ♻️ 再開の見込み: 空回しが途中で止まった ({rs['error'][:80]})")
        else:
            lines.append(f"  ♻️ 再開の見込み (前の run: 始まった {rs['prev_started']} 本 / 結果 {rs['prev_with_result']} 本 / prompt を照合できた {rs['prev_matched_prompts']} 本):"
                         f" cache が返るのは前から {rs['hits']} 本。 最初に走る呼び出し = {rs['first_live']}"
                         + (" (前の run に同じ prompt の結果があるが、 項目の並びの位置が違う = cache の key は位置でも決まる)"
                            if rs.get("first_live_moved")
                            else " (前の run に結果があるのに、 その前で順が崩れた)" if rs["first_live_prev"]
                            else " (前の run に無い呼び出し)"))
            if rs["rerun"]:
                lines.append(f"     前の run で結果の出た {len(rs['rerun'])} 本を走り直す: " + ", ".join(rs["rerun"][:6])
                             + (" …" if len(rs["rerun"]) > 6 else "")
                             + "。 → 再開でなく、 workflow-run-stats.py <前の run の dir> --export-results <file> で済んだ結果を file にし、"
                             " それを読む新しい run にする")
    if problems:
        lines.append("  🛑 宣言の無い点: " + " / ".join(p["text"] for p in problems))
        lines.append("     直し方 = 割り方を直すか、 script の注釈に宣言を書く: `// workflow-size: <本数> — <理由>` /"
                     " `// workflow-lenses: independent — <理由>` / `// workflow-resume: rerun-ok — <理由>`")
    lines.append(f"  規約 = {RULE}")
    return "\n".join(lines)


# ---------------------------------------------------------------- hook
def _enforced() -> bool:
    if os.environ.get("WORKFLOW_FANOUT_ENFORCE") == "1":
        return True
    marker = os.environ.get("WORKFLOW_FANOUT_ENFORCE_MARKER") or os.path.expanduser("~/.claude/workflow-fanout-enforce.on")
    return os.path.exists(marker)


def workflow_source(ti: dict, cwd: str) -> str | None:
    if isinstance(ti.get("script"), str) and ti["script"].strip():
        return ti["script"]
    sp = ti.get("scriptPath")
    if isinstance(sp, str) and sp:
        p = sp if os.path.isabs(sp) else os.path.join(cwd or ".", sp)
        try:
            return open(os.path.expanduser(p), encoding="utf-8").read()
        except OSError:
            return None
    name = ti.get("name")
    if isinstance(name, str) and name:
        for d in (os.path.join(cwd or ".", ".claude", "workflows"), os.path.expanduser("~/.claude/workflows")):
            for cand in (name, name + ".js"):
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    try:
                        return open(p, encoding="utf-8").read()
                    except OSError:
                        return None
    return None


def resume_dir_for(ev: dict, run_id: str) -> str | None:
    tp = ev.get("transcript_path") or ""
    if not tp.endswith(".jsonl"):
        return None
    d = os.path.join(tp[:-len(".jsonl")], "subagents", "workflows", run_id)
    return d if os.path.isfile(os.path.join(d, "journal.jsonl")) else None


def hook(stdin_text: str) -> int:
    if os.environ.get("WORKFLOW_FANOUT_DISABLE") == "1":
        return 0
    try:
        ev = json.loads(stdin_text or "{}")
    except json.JSONDecodeError:
        return 0
    if ev.get("hook_event_name", "PreToolUse") != "PreToolUse" or ev.get("tool_name") != "Workflow":
        return 0
    ti = ev.get("tool_input") or {}
    src = workflow_source(ti, ev.get("cwd") or "")
    if not src:
        return 0
    args = ti.get("args")
    rid = ti.get("resumeFromRunId")
    rdir = resume_dir_for(ev, rid) if isinstance(rid, str) and rid else None
    try:
        res = estimate(src, args, resume_dir=rdir)
    except Exception as e:  # fail-open
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": f"[workflow-estimate] 見積もりに失敗した ({e})"}}, ensure_ascii=False))
        return 0
    broken = all(not r["ok"] for r in res["runs"].values())
    # 本数は止めずに本人に聞く (宣言の 1 行では通さない)。 止めるのは観点の分割・cache 0 本の再開の宣言の無い形だけ
    problems = [] if broken else [p for p in judge(res) if p["kind"] not in ("size", "size-soft")]
    text = render(res, problems)
    enforced = _enforced()
    if problems and enforced:
        print(text, file=sys.stderr)
        return 2
    over = None if broken else over_one_wave(res)
    out = {"hookEventName": "PreToolUse", "additionalContext": text}
    if over and enforced:
        out.update({"permissionDecision": "ask", "permissionDecisionReason": over})
    print(json.dumps({"hookSpecificOutput": out}, ensure_ascii=False))
    return 0


def over_one_wave(res: dict) -> str | None:
    """その機械で一度に走れる本数 (上限) を越えうるなら、 本人に聞く理由の文。 越えないなら None。"""
    cap = res["cap"]
    oks = [r["agents"] for r in res["runs"].values() if r["ok"]]
    most = max(oks) if oks else 0
    if most <= cap and not res["grows"]:
        return None
    st = res["static"]
    parts = []
    if res["grows"]:
        parts.append(f"本数が前段の出力で決まる (前段 1 件ごとに約 {res['slope']} 本、 前段 10 件なら {res['runs'][max(res['runs'])]['agents']} 本)")
    else:
        parts.append(f"{most} 本 = {ceil_div(most, cap)} 波")
    parts.append(f"この機械で一度に走るのは {cap} 本まで、 残りは待ち行列")
    if st["decl_size"] is not None:
        parts.append(f"script の宣言 = {st['decl_size']} 本 ({st['decl_size_reason'] or '理由なし'})")
    return "Workflow が一度に走れる本数を越える: " + "、 ".join(parts) + "。 走らせてよければ許可"


# ---------------------------------------------------------------- selftest
SELFTEST_SCRIPTS = {
    "constant": """export const meta = { name: 't', description: 't' }
const a = await agent('one', { label: 'a' })
const b = await agent('two', { label: 'b' })
return { a, b }""",
    "per_finding_two_lenses": """export const meta = { name: 't', description: 't' }
const ITEMS = ['p', 'q', 'r', 's']
const S = { type: 'object', properties: { tasks: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, doable: { type: 'boolean' } } } } } }
const out = await pipeline(ITEMS, (it) => agent('read ' + it, { label: 'read:' + it, phase: 'Read', schema: S }),
  async (r, it) => {
    const d = r.tasks.filter(t => t.doable)
    return parallel(d.map(t => () => parallel(['state', 'rules'].map(lens => () => agent(`verify ${it} ${t.title} ${lens}`, { label: `verify:${it}:${lens}`, phase: 'Verify' })))))
  })
await agent('critic', { label: 'critic', phase: 'Critic' })
return out""",
    "batched_with_decl": """export const meta = { name: 't', description: 't' }
// workflow-size: 9 — 4 repo を 1 本ずつ読み、 2 本で照合、 1 本で批評
// workflow-lenses: independent — 規則の観点は状態の結論を見ずに判定させる
const ITEMS = ['p', 'q', 'r', 's']
const reads = await parallel(ITEMS.map(it => () => agent('read ' + it, { label: 'read:' + it })))
const v = await parallel(['state', 'rules'].map(lens => () => agent('verify all ' + lens, { label: 'verify:' + lens })))
await agent('critic', { label: 'critic' })
return v""",
    "order": """export const meta = { name: 't', description: 't' }
const p = parallel(['x', 'y'].map(v => () => agent('par ' + v, { label: 'par:' + v })))
const s = await agent('single', { label: 'single' })
await p
return s""",
    "votes": """export const meta = { name: 't', description: 't' }
const F = ['f1', 'f2']
await parallel(F.map(f => () => parallel(Array.from({length: 3}, (_, i) => () => agent('refute ' + f + i, { label: 'vote' })))))""",
    "runaway": """export const meta = { name: 't', description: 't' }
const seen = []
while (true) { seen.push(await agent('again ' + seen.length)) }""",
    "escape": """export const meta = { name: 't', description: 't' }
let r = 'none'
try { const p = agent.constructor.constructor('return process')(); r = 'ESCAPED' + typeof p } catch (e) { r = 'blocked' }
await agent(r, { label: r })""",
    "uses_args": """export const meta = { name: 't', description: 't' }
await parallel(args.repos.flatMap(r => ['a', 'b'].map(l => () => agent(r + l, { label: r + ':' + l }))))
await agent('sweep', { label: 'sweep' })""",
    "big_declared": """export const meta = { name: 't', description: 't' }
// workflow-size: 20 — test of a declared script over one wave
const PARTS = []
for (let i = 0; i < 20; i++) PARTS.push(i)
await parallel(PARTS.map(i => () => agent('read part ' + i, { label: 'read:' + i })))""",
    "grows_declared": """export const meta = { name: 't', description: 't' }
// workflow-size: 30 — test of a declared script whose count follows the first stage
const f = await agent('find', { label: 'find', schema: { type: 'object', properties: { items: { type: 'array', items: { type: 'string' } } } } })
await parallel(f.items.map(x => () => agent('check ' + x, { label: 'check' })))""",
    "reorder": """export const meta = { name: 't', description: 't' }
const ORDER = (args && args.order) || ['a', 'b', 'c']
await pipeline(ORDER, (it) => agent('read ' + it, { label: 'read:' + it }), (r, it) => agent('check ' + it, { label: 'check:' + it }))""",
}


def _fake_prev_run(d: str, calls: list[tuple[str, str]], with_result: int, starts_first: int = 0,
                   name: str = "wf_prev-000") -> str:
    """starts_first = 最初の結果より前に始まる呼び出しの数 (本物の run の最初の波。 0 なら 1 本ずつ始まって終わる)。"""
    run = os.path.join(d, name)
    os.makedirs(run, exist_ok=True)
    rows = [{"type": "launched"}]
    for i in range(min(starts_first, len(calls))):
        rows.append({"type": "started", "key": f"v2:{i}", "agentId": f"a{i:03d}", "label": calls[i][0]})
    for i, (label, prompt) in enumerate(calls):
        aid = f"a{i:03d}"
        if i >= starts_first:
            rows.append({"type": "started", "key": f"v2:{i}", "agentId": aid, "label": label})
        task = ("[Workflow harness — computed task] The task text below was computed at runtime by a workflow script. "
                "The computed task text follows:\n" + "\n".join("  " + ln for ln in prompt.split("\n")))
        with open(os.path.join(run, f"agent-{aid}.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "[Workflow harness — user request] x"}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"content": task}}, ensure_ascii=False) + "\n")
        if i < with_result:
            rows.append({"type": "result", "key": f"v2:{i}", "agentId": aid, "result": "s0"})
    with open(os.path.join(run, "journal.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return run


def selftest() -> int:
    fails = 0

    def check(name, cond, detail=""):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
        fails += 0 if cond else 1

    if not node_path():
        print("SKIP node が無い (空回しの試験は node が要る)")
        return 0
    S = SELFTEST_SCRIPTS
    os.environ["WORKFLOW_ESTIMATE_CAP"] = "8"  # 上限を機械に依らず 8 に (hook の試験は machine_cap を通る)
    r = estimate(S["constant"], cap=8)
    check("constant: 2 本、 k で変わらない", [x["agents"] for x in r["runs"].values()] == [2, 2, 2] and not r["grows"], r["runs"])
    r = estimate(S["per_finding_two_lenses"], cap=8)
    got = [x["agents"] for x in r["runs"].values()]
    check("per finding × 2 lenses: 4 + 8k + 1", got == [4 + 8 * k + 1 for k in DEFAULT_KS], got)
    check("per finding grows with slope 8", r["grows"] and r["slope"] == 8.0, r["slope"])
    check("lens split detected", len(r["static"]["lenses"]) == 1, r["static"])
    pk = [p["kind"] for p in judge(r)]
    check("undeclared size and lenses are problems", "size" in pk and "lenses" in pk, pk)
    r = estimate(S["batched_with_decl"], cap=8)
    check("batched: 7 本で一定", [x["agents"] for x in r["runs"].values()] == [7, 7, 7], r["runs"])
    check("declarations parsed", r["static"]["decl_size"] == 9 and r["static"]["decl_lenses"], r["static"])
    check("declared script has no problems", judge(r) == [], judge(r))
    one = dry_run(S["order"], None, 1)
    check("parallel defers thunks: the single call after it starts first",
          [c["label"] for c in one["calls"]] == ["single", "par:x", "par:y"], one)
    r = estimate(S["votes"], cap=8)
    check("votes: 2 × 3 = 6 本、 票を見つける", r["agents_mid"] == 6 and len(r["static"]["votes"]) == 1, (r["agents_mid"], r["static"]))
    r = estimate(S["runaway"], cap=8, ks=(1,))
    check("runaway loop stops at the call cap", r["runs"][1]["error"] == "CALL_CAP" and r["runs"][1]["agents"] == CALL_CAP, r["runs"][1])
    one = dry_run(S["escape"], None, 1)
    check("sandbox: reaching process through the Function constructor is blocked",
          [c["label"] for c in one.get("calls", [])] == ["blocked"], one)
    r = estimate(S["uses_args"], {"repos": ["r1", "r2", "r3"]}, cap=4)
    check("args are passed: 3 × 2 + 1 = 7 本 = 2 波 (上限 4)", r["agents_mid"] == 7 and r["waves_mid"] == 2, r)
    r = estimate(S["uses_args"], None, cap=4)
    check("missing args: the dry run reports the error", not r["runs"][3]["ok"] and r["runs"][3]["error"], r["runs"][3])
    # resume: same script with an unchanged prefix → hits; a new first call → 0 hits and re-runs
    with tempfile.TemporaryDirectory() as d:
        prev_src = S["batched_with_decl"]
        prev_calls = dry_run(prev_src, None, 3, keep_prompts=True)["calls"]
        run = _fake_prev_run(d, [(c["label"], c["prompt"]) for c in prev_calls], with_result=4)
        r = estimate(prev_src, resume_dir=run, cap=8)
        check("resume same script: the 4 finished readers come back from the cache", r["resume"]["hits"] == 4 and r["resume"]["rerun"] == [], r["resume"])
        edited = prev_src.replace("const ITEMS", "const pre = agent('new first call', { label: 'new' })\nconst ITEMS")
        r = estimate(edited, resume_dir=run, cap=8)
        check("resume after putting a new call first: 0 hits, 4 re-runs", r["resume"]["hits"] == 0 and len(r["resume"]["rerun"]) == 4
              and r["resume"]["first_live"] == "new", r["resume"])
        check("zero-hit resume is a problem", "resume" in [p["kind"] for p in judge(r)], judge(r))
        # resume: the cache key also depends on the position in pipeline / parallel (measured). The first wave of the
        # previous run starts in item order, so items put in another order are not cache hits.
        ro = S["reorder"]
        ro_calls = dry_run(ro, None, 3, keep_prompts=True)["calls"]
        ro_run = _fake_prev_run(d, [(c["label"], c["prompt"]) for c in ro_calls], with_result=6, starts_first=3,
                                name="wf_prev-reorder")
        r = estimate(ro, resume_dir=ro_run, cap=8)
        check("resume in the same item order: all 6 come back", r["resume"]["hits"] == 6 and r["resume"]["rerun"] == [], r["resume"])
        r = estimate(ro, {"order": ["c", "b", "a"]}, resume_dir=ro_run, cap=8)
        check("resume with the items reordered: 0 hits, 6 re-runs, the first call is flagged as moved",
              r["resume"]["hits"] == 0 and len(r["resume"]["rerun"]) == 6 and r["resume"]["first_live"] == "read:c"
              and r["resume"]["first_live_moved"], r["resume"])
        r = estimate(ro, {"order": ["a", "c", "b"]}, resume_dir=ro_run, cap=8)
        check("resume with only the tail moved: the unmoved first item still comes back",
              r["resume"]["hits"] == 1 and r["resume"]["first_live"] == "read:c", r["resume"])
        # hook: inline script, enforce off → context only; enforce on → exit 2
        ev = {"hook_event_name": "PreToolUse", "tool_name": "Workflow", "tool_input": {"script": S["per_finding_two_lenses"]}}
        marker = os.path.join(d, "enforce.on")
        os.environ["WORKFLOW_FANOUT_ENFORCE_MARKER"] = marker
        os.environ.pop("WORKFLOW_FANOUT_ENFORCE", None)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = hook(json.dumps(ev))
        check("hook without enforce: exit 0 + additionalContext", rc == 0 and "additionalContext" in buf.getvalue(), (rc, buf.getvalue()[:200]))
        open(marker, "w").close()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = hook(json.dumps(ev))
        check("hook with enforce: exit 2 + reason on stderr", rc == 2 and "宣言の無い点" in err.getvalue(), (rc, err.getvalue()[:200]))
        ev2 = dict(ev, tool_input={"script": S["batched_with_decl"]})
        with contextlib.redirect_stdout(io.StringIO()):
            rc = hook(json.dumps(ev2))
        check("hook with enforce: a declared script within one wave runs without asking", rc == 0, rc)
        for name, label in (("big_declared", "a declared script over one wave"),
                            ("grows_declared", "a declared script whose count follows the first stage")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = hook(json.dumps(dict(ev, tool_input={"script": S[name]})))
            out = json.loads(buf.getvalue() or "{}").get("hookSpecificOutput", {})
            check(f"hook with enforce: {label} asks the owner (the declaration does not pass it)",
                  rc == 0 and out.get("permissionDecision") == "ask" and "一度に走れる" in out.get("permissionDecisionReason", ""),
                  (rc, out))
        os.environ["WORKFLOW_FANOUT_ENFORCE_MARKER"] = os.path.join(d, "no-marker")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = hook(json.dumps(dict(ev, tool_input={"script": S["big_declared"]})))
        check("hook without enforce: over one wave only shows the numbers (no ask)",
              rc == 0 and "permissionDecision" not in buf.getvalue(), buf.getvalue()[:200])
        os.environ["WORKFLOW_FANOUT_ENFORCE_MARKER"] = marker
        ev3 = dict(ev, tool_name="Bash")
        check("hook ignores other tools", hook(json.dumps(ev3)) == 0)
        os.environ["WORKFLOW_ESTIMATE_NODE"] = os.path.join(d, "no-node")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = hook(json.dumps(ev))
        check("hook fails open without node", rc == 0, rc)
        old = os.path.join(d, "old-node")  # 隔離の flag を知らない node = 走らせずに失敗を返す (隔離なしで回さない)
        with open(old, "w") as f:
            f.write('#!/bin/sh\necho "node: bad option: $2" >&2\nexit 9\n')
        os.chmod(old, 0o755)
        os.environ["WORKFLOW_ESTIMATE_NODE"] = old
        one = dry_run(S["escape"], None, 1)
        check("node without the isolation flags: refused, not run unisolated",
              not one["ok"] and "隔離の flag" in one["error"], one)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = hook(json.dumps(ev))
        check("hook fails open with an old node", rc == 0, rc)
        os.environ.pop("WORKFLOW_ESTIMATE_NODE", None)
        os.environ.pop("WORKFLOW_FANOUT_ENFORCE_MARKER", None)
    print("selftest:", "OK" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?")
    ap.add_argument("--args")
    ap.add_argument("--cap", type=int)
    ap.add_argument("--ks", default=",".join(str(k) for k in DEFAULT_KS))
    ap.add_argument("--resume-dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hook", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.hook:
        return hook(sys.stdin.read())
    if not a.script:
        ap.error("script の path を渡す (または --hook / --selftest)")
    src = open(a.script, encoding="utf-8").read()
    args = None
    if a.args:
        args = json.load(open(a.args[1:], encoding="utf-8")) if a.args.startswith("@") else json.loads(a.args)
    ks = tuple(int(x) for x in a.ks.split(",") if x.strip())
    res = estimate(src, args, a.cap, ks, a.resume_dir)
    problems = judge(res)
    if a.json:
        print(json.dumps({"estimate": res, "problems": problems}, ensure_ascii=False, indent=1))
    else:
        print(render(res, problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
