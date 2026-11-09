#!/usr/bin/env python3
"""permission-dialog-audit.py — Claude desktop の承認 dialog を app log から集計し、 transcript と突合して main / sub-agent に振り分け、 1 件ごとに原因を切り分ける

なぜ要るか
----------
「いちいち聞かれる」 「背景作業を立ち上げるたびに聞かれる」 は体感で語られやすく、 どの tool の
dialog が何件か・誰 (main session か sub-agent か) の tool call かを数えないと、 allow の足し先
も「そもそも仕様で消せない dialog か」 も決まらない。 desktop app は dialog ごとに log へ 2 行
残すので、 それを数えれば推測が要らない。 一般則: conventions/claude-code-permissions.md#desktop-permission-dialog-log

入力
----
desktop app の log (既定 `~/Library/Logs/Claude/main*.log`) の 3 形式の行:
  <YYYY-MM-DD HH:MM:SS> [info] Emitted tool permission request <id> for <tool> in session <local_id>
  <YYYY-MM-DD HH:MM:SS> [info] Received permission response for <id>: <decision> (tool: <tool>)
  <YYYY-MM-DD HH:MM:SS> [info] Mapping internal session <local_id> to CLI session <session_id>
同じ行が 2 回ずつ書かれることがあるので request id で dedupe する。 log の時刻は local time。
3 行目が desktop 側の session id (local_…) と transcript 側の session id (= `<設定フォルダ>/projects/` の
file 名・各 record の `sessionId`) を結ぶ唯一の鍵。 同じ local_id の Mapping 行は繰り返し書かれ、
再開で別の CLI session に付け替わることがあるので、 時刻つきで持ち dialog の時刻で引く。

dialog と tool 呼び出しの突合 (--attribute / --diagnose 共通、 match_dialogs)
--------------------------------------------------------------------------
時刻が近いだけで選ぶと、 並列に動く別 session の同名 tool (Bash が大半) に付く (実測: 送信 guard の
dialog が別 session の無関係な command に付き、 guard 別の件数が狂った)。 3 つの制約で絞る:
  1. 同じ session — Mapping 行で dialog の local_id を CLI session に解き、 その session の transcript
     (sub-agent の transcript も同じ session id を持つ) の tool_use だけを候補にする。 Mapping 行が無い
     dialog は旧来どおり時刻の窓だけで選び、 その旨を出す (別 session への fallback はしない)
  2. 応答より後に終わった呼び出し — dialog を出した tool は user が答えるまで走らないので、 その
     tool_result は応答の時刻より後にある。 応答より前に tool_result が出ている呼び出しは別物として除く
     (tool_result が transcript に無い呼び出しは除かない)
  3. 待ち行列の順 — 1 つの assistant message が複数の tool を並べて呼ぶと、 dialog は 1 つずつ順に出て
     2 つ目以降は tool_use の時刻から大きく遅れる。 窓の中に候補が無いときは、 同じ session で既に
     dialog を割り当てた message の兄弟 (= 同じ record の tool_use) を tool_use の順に割り当て、 それも
     無ければ --queue-window 秒まで遡って最も古い未割り当ての候補を取る。 1 つの tool_use に 2 つの dialog
     は付けない (割り当て済みは候補から外す)

mode
----
  (既定)              tool 別件数 / decision 内訳 / 応答待ち秒 (中央値・最大)
  --latest N          直近 N 件を 1 行ずつ
  --attribute         transcript (`<設定フォルダ>/projects/**.jsonl`、 sub-agent の transcript を含む) の
                      tool_use と突合 (上の 3 制約。 窓 = dialog 発行の --before 秒前 〜 --after 秒後、
                      既定 8 / 2)。 main / sub-agent / unmatched に振り分け、 Edit/Read/Write は path の
                      上位 2 階層、 Bash は先頭語で bucket する。 direct / queue / unmapped の内訳も出す
  --from-transcripts  desktop log が無い環境 (CLI 等) 向け。 通常すぐ返る tool (Read/Edit/Write/Glob/
                      Grep/Monitor 等) の tool_use → tool_result が --wait 秒 (既定 15) 超かかった
                      ものを「dialog 候補」 として列挙 (= 承認待ちで止まった可能性。 断定はしない)
  --diagnose          dialog 1 件ごとに**なぜ出たか**を切り分けて消し方を出す。 transcript から
                      当時の tool 入力を復元し、 settings の PreToolUse hook (matcher が当たる
                      ものだけ) に流し直す。 種別 = hook (今も ask を返す) / fixed (今は exit 2 で
                      block = dialog は出ない) / length (hook 無反応 + Bash が --long-limit 超) /
                      rule (hook 無反応 = allow・cwd scope・protected path 側) /
                      rule_unique (command に per-call 一意な token = 「常に許可」 が永久に効かない) /
                      unmatched。
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
  permission-dialog-audit.py --judgeable --since-days 7 --surface \
      --send-hooks mail-send-guard --judgeable-hooks protected-dir --judgeable-tools run_in_terminal
      # 本人が dialog の文字だけで決められない確認の件数 (0 件なら沈黙 = dashboard の段)。 決められる = アプリ自身の
      # 確認 (APP_GATES)・宣言した hook・送信の hook の本送信の形・宣言した tool (claude-code-permissions.md#ask-only-owner-judgeable)
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
MAP_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:[.,]\d+)?\s+\[\w+\]\s+Mapping internal session (\S+) to CLI session (\S+)"
)
# 待ち行列の候補を遡る上限 (秒)。 並列の dialog は前の dialog が答えられるまで出ないので、 tool_use から
# dialog までの遅れは user が前の dialog を放置した時間に等しく、 数十分になりうる
QUEUE_WINDOW = 3600.0
FAST_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Glob", "Grep", "Monitor",
              "Skill", "TodoWrite", "ToolSearch")
PATH_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit")
# アプリ自身が出す確認 (permission の設定でも hook でもない = allow で消えない)。 hook を流し直す前に分ける =
# 流し直すと、 その道具に掛かる今の hook の block (理由の無い高い段を止める類) が「fixed」 と出て、 hook で直った
# ように見える (実測)。 key = log の tool 名 (mcp__<server>__ を除いた名でも引く)
APP_GATES = {
    "set_session_effort": "自分が起こした session を自分の段より上げる・他の session を変えるとアプリが聞く (道具の説明)",
    "set_session_model": "自分が起こした session を自分の model より上げる・他の session を変えるとアプリが聞く (道具の説明)",
    "set_session_permission_mode": "permission mode を上げるとアプリが聞く (道具の説明)",
    "search_session_transcripts": "道具が毎回の承認を求める (always-prompt、 allow に入れても出る)",
    "browser:open_site": "内蔵ブラウザで初めて開くサイト",
    "computer:request_access": "画面操作で app を使う許可",
}


def local_epoch(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


def iso_epoch(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def since_epoch(since):
    return local_epoch(since + " 00:00:00") if since else 0.0


def scan_logs(log_dir, since):
    """log を 1 回読んで (dialog の dict, session の対応表) を返す。

    dialog = request id → {emit, tool, session, resp, decision} (dedupe 済、 --since で切る)。
    対応表 = local_id → [(時刻, CLI session id), ...] (時刻順。 --since で切らない = session は
    期間の前に始まっていることが多い)。
    """
    lo = since_epoch(since)
    reqs = {}
    resps = {}
    smap = {}
    for p in sorted(Path(log_dir).glob("main*.log")):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "Mapping internal session" in line:
                        m = MAP_RE.match(line)
                        if m:
                            pair = (local_epoch(m.group(1)), m.group(3))
                            lst = smap.setdefault(m.group(2), [])
                            if not lst or lst[-1][1] != pair[1]:
                                lst.append(pair)
                        continue
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
    for lst in smap.values():
        lst.sort()
    return out, smap


def parse_logs(log_dir, since):
    """request id → {emit, tool, session, resp, decision}。 dedupe 済。"""
    return scan_logs(log_dir, since)[0]


def parse_session_map(log_dir):
    """local_id → [(時刻, CLI session id), ...]。"""
    return scan_logs(log_dir, None)[1]


def cli_session_for(session_map, local_id, at):
    """dialog の時刻 at で有効な CLI session id (無ければ None)。 at より前の最後の Mapping、 それも無ければ最初。"""
    lst = (session_map or {}).get(local_id) or []
    if not lst:
        return None
    cur = None
    for t, cli in lst:
        if t <= at + 1.0:
            cur = cli
        else:
            break
    return cur if cur is not None else lst[0][1]


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
# 読む transcript = 既定でこの機械の全部の設定フォルダの projects/ (~/.claude と、 アカウント固定の ~/.claude-<名> =
# スマホから始めた session・無人 routine、 と $CLAUDE_CONFIG_DIR)。 desktop の session は ~/.claude にしか無いので
# desktop log との突合 (--attribute / --diagnose) は ~/.claude の分で決まるが、 --from-transcripts は CLI・スマホの
# session の承認待ちも拾う。 列挙と重複の扱い = lib/claude_config_dirs.py の transcript_files。

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import claude_config_dirs as _ccd
except Exception:  # pragma: no cover - 古い配置
    _ccd = None


def _transcript_paths(projects_dir):
    """projects_dir = None なら全部の設定フォルダ、 path (1 つか list) ならその dir だけ。"""
    if projects_dir is None:
        if _ccd is not None:
            return [Path(f) for _lab, f in _ccd.transcript_files("**/*.jsonl")]
        projects_dir = Path("~/.claude/projects").expanduser()
    roots = projects_dir if isinstance(projects_dir, (list, tuple)) else [projects_dir]
    out = []
    for r in roots:
        for root, _dirs, files in os.walk(r):
            out += [Path(root) / fn for fn in files if fn.endswith(".jsonl")]
    return out


def config_label(p) -> str:
    """transcript の設定フォルダの名。 ~/.claude と不明は空 (表示しない)。"""
    if _ccd is None:
        return ""
    lab = _ccd.label_of(str(p))
    return "" if lab in ("default", "?") else lab


def iter_transcripts(projects_dir, since):
    lo = since_epoch(since) - 86400  # mtime は最終書込み時刻なので 1 日余裕
    for p in _transcript_paths(projects_dir):
        try:
            if p.stat().st_mtime < lo:
                continue
        except OSError:
            continue
        yield p


def transcript_session_id(p):
    """transcript の path から CLI session id を導く (record に sessionId が無いときの fallback)。
    `<dir>/<session>.jsonl` → session、 `<dir>/<session>/subagents/<agent>.jsonl` → session。"""
    parts = str(p).replace(os.sep, "/").split("/")
    if len(parts) >= 3 and parts[-2] == "subagents":
        return parts[-3]
    return Path(p).stem


def load_tool_events(projects_dir, since, want_results=False):
    """tool_use の list と (want_results なら) tool_use_id → result 時刻。

    各 tool_use に突合用の鍵を持たせる: cli = CLI session id (record の sessionId、 無ければ path から)、
    msg = それを含む assistant record の uuid (= 同じ message の兄弟 tool_use は同じ msg)、
    seq = 時刻順の通し番号 (同時刻は transcript の並び順)。
    """
    uses = []
    results = {}
    lo = since_epoch(since)
    for p in iter_transcripts(projects_dir, since):
        sub_path = "/subagents/" in str(p).replace(os.sep, "/")
        path_sid = transcript_session_id(p)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f):
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
                    cli = rec.get("sessionId") or path_sid
                    msg = rec.get("uuid") or f"{p}:{lineno}"
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "tool_use":
                            uses.append({"t": ts, "name": c.get("name", ""), "input": c.get("input") or {},
                                         "id": c.get("id"), "sub": side, "path": p, "cli": cli, "msg": msg})
                        elif want_results and c.get("type") == "tool_result" and c.get("tool_use_id"):
                            results.setdefault(c["tool_use_id"], ts)
        except OSError:
            continue
    uses.sort(key=lambda u: u["t"])
    for i, u in enumerate(uses):
        u["seq"] = i
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


def _rid(r):
    """request の鍵 (log 由来は request id。 無ければ object identity)。"""
    return r["id"] if r.get("id") is not None else id(r)


def match_dialogs(reqs, uses, results, before, after, session_map=None, queue_window=QUEUE_WINDOW):
    """dialog → tool_use の 1 対 1 突合。 _rid(request) → (use | None, how, cli)。

    how = "direct" (同じ session、 窓の中) / "queue" (同じ session、 窓の外から待ち行列の順で) /
    "unmapped" (Mapping 行が無く session を解けない → 窓だけで選んだ) / None (突合できず)。
    制約 (docstring 冒頭): 同じ session / tool_result が応答より後 / 1 tool_use に 1 dialog。
    """
    out = {}
    used = set()
    matched_msgs = {}  # cli → set(msg) = dialog を割り当て済みの message (並列の兄弟を引くため)
    results = results or {}
    for r in sorted(reqs, key=lambda x: x["emit"]):
        emit = r["emit"]
        cli = cli_session_for(session_map, r.get("session"), emit)
        floor = (r["resp"] if r["resp"] is not None else emit) - 1.0  # 1 秒 = log の秒切り捨て分

        def result_after_response(u):
            rt = results.get(u["id"])
            return rt is None or rt >= floor

        pool = [u for u in uses
                if u["id"] not in used
                and names_match(r["tool"], u["name"])
                and (cli is None or u.get("cli") == cli)
                and u["t"] <= emit + after
                and result_after_response(u)]
        pick, how = None, None
        window = [u for u in pool if u["t"] >= emit - before]
        if window:
            pick = min(window, key=lambda u: (abs(u["t"] - emit), u.get("seq", 0)))
            how = "direct" if cli is not None else "unmapped"
        elif cli is not None:
            siblings = [u for u in pool if u.get("msg") in matched_msgs.get(cli, set())]
            if not siblings:
                siblings = [u for u in pool if u["t"] >= emit - queue_window]
            if siblings:
                pick = min(siblings, key=lambda u: u.get("seq", 0))
                how = "queue"
        if pick is not None:
            used.add(pick["id"])
            if cli is not None:
                matched_msgs.setdefault(cli, set()).add(pick.get("msg"))
        out[_rid(r)] = (pick, how, cli)
    return out


def attribute(reqs, uses, before, after, home, results=None, session_map=None, queue_window=QUEUE_WINDOW):
    """[(req, who, bucket, how)]。 who = main / sub-agent / unmatched。"""
    matched = match_dialogs(list(reqs.values()), uses, results, before, after, session_map, queue_window)
    rows = []
    for r in sorted(reqs.values(), key=lambda x: x["emit"]):
        u, how, _cli = matched[_rid(r)]
        if u is None:
            rows.append((r, "unmatched", r["tool"], None))
            continue
        rows.append((r, "sub-agent" if u["sub"] else "main", bucket(u, home), how))
    return rows


def print_attribution(rows):
    total = len(rows)
    by_who = {}
    by_how = {}
    for _r, who, _b, how in rows:
        by_who[who] = by_who.get(who, 0) + 1
        if how:
            by_how[how] = by_how.get(how, 0) + 1
    print(f"attribution: {total} dialogs → " + ", ".join(f"{k} {v}" for k, v in sorted(by_who.items())))
    print("  突合の内訳: " + (", ".join(f"{k} {v}" for k, v in sorted(by_how.items())) or "-")
          + "  (direct = 同じ session・窓内 / queue = 同じ session・待ち行列 / unmapped = Mapping 行なし・窓だけ)")
    print("")
    agg = {}
    for _r, who, b, _how in rows:
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
        cfg = config_label(u.get("path", ""))
        who += f"[{cfg}]" if cfg else ""
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
    "unmatched": "同じ session の transcript に該当 tool 呼び出しが無い (transcript 欠落 / --since の外 /"
                 " 応答より前に終わった呼び出ししか無い)。 --since を広げる。 別 session の呼び出しには付けない",
    "app": "アプリ自身の確認 = 設定・hook では消えない。 減らすなら呼ぶ形を変える (例 = 上げたい段の session から起こす)"
           " (claude-code-permissions.md#always-approve-tools)",
}


def app_gate(tool):
    """アプリ自身の確認の道具なら理由 (違えば None)。"""
    return APP_GATES.get(tool) or APP_GATES.get(str(tool).split("__")[-1])


_SEG_SPLIT = re.compile(r"\n|&&|\|\||;|\||&")
_SEND_FLAG = re.compile(r"(?:^|\s)--send(?:[\s=]|$)")


def has_send_segment(command):
    """単純 command (改行・&& || ; | & で割った 1 片) のどれかに `--send` がある = 送信の道具の本送信の形
    (claude-code-permissions.md#ask-pattern-action-anchor = 不可逆の action の flag に anchor)。"""
    return any(_SEND_FLAG.search(seg) for seg in _SEG_SPLIT.split(str(command or "")))


def judge(row, judgeable_hooks=(), send_hooks=(), judgeable_tools=()):
    """dialog 1 件を、 本人が dialog の文字だけで決められるか (judgeable) / 決められない (not) / 今はもう出ない (gone) に分ける。
    決められる = アプリ自身の確認 (どの session を何に・どのサイト)、 宣言した hook (judgeable_hooks)、 送信の hook
    (send_hooks) の本送信の形 (`--send` のある片)、 宣言した tool (judgeable_tools、 例 = 本人の端末の tab に出す道具)。
    それ以外 (宣言していない hook・hook 無反応の rule・長さ・一意な path・突合できないもの) は決められない側
    (claude-code-permissions.md#ask-only-owner-judgeable)。"""
    r, kind, _why, _detail = row
    if kind == "fixed":
        return "gone"
    if kind == "app":
        return "judgeable"
    tool = str(r.get("tool", ""))
    if kind == "hook":
        h = r.get("_hook", "")
        if any(s and s in h for s in send_hooks):
            if tool != "Bash":  # 送信の tool そのもの (MCP の send_email など) = dialog に宛先・件名・本文が出る
                return "judgeable"
            inp = r.get("_input") or {}
            return "judgeable" if has_send_segment(inp.get("command", "")) else "not"
        if any(s and s in h for s in judgeable_hooks):
            return "judgeable"
        return "not"
    if any(t and (t == tool or tool.endswith("__" + t)) for t in judgeable_tools):
        return "judgeable"
    return "not"


def print_judgeable(rows, surface=False, **kw):
    """--judgeable の出力。 surface = 決められない確認が 0 件なら何も出さない (dashboard の段)。"""
    groups = {}
    counts = {"judgeable": 0, "not": 0, "gone": 0}
    for row in rows:
        v = judge(row, **kw)
        counts[v] += 1
        if v != "not":
            continue
        r, kind, why, _d = row
        key = (kind, r.get("_hook") or "", r.get("tool", ""))
        g = groups.setdefault(key, {"n": 0, "last": 0.0})
        g["n"] += 1
        g["last"] = max(g["last"], r["emit"])
    if surface and not counts["not"]:
        return
    print(f"🔐 承認の確認のうち、 本人が dialog の文字だけで決められないもの {counts['not']} 件"
          f" (決められる {counts['judgeable']} / 今はもう出ない {counts['gone']})"
          " → 確認を出す側 (hook の述語・書き方) を直す = claude-code-permissions.md#ask-only-owner-judgeable")
    for (kind, hook, tool), g in sorted(groups.items(), key=lambda x: -x[1]["n"]):
        src = f"{hook} が ask" if hook else f"[{kind}]"
        print(f"  {g['n']:3d}  {tool}  {src}  (最後 {fmt_t(g['last'])})")
    if counts["not"]:
        print("  1 件ずつの切り分け = permission-dialog-audit.py --diagnose --since <日付> --show-command")


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


def filter_hooks(hooks, only):
    """--only-hooks: hook の command に部分文字列 (カンマ区切り) のどれかを含むものだけ残す。 空なら全部。"""
    keys = [s.strip() for s in str(only or "").split(",") if s.strip()]
    return [(m, c) for m, c in hooks if not keys or any(k in c for k in keys)]


def diagnose(reqs_list, uses, before, after, hooks, long_limit, run_hooks=True, cwd=None,
             results=None, session_map=None, queue_window=QUEUE_WINDOW, show_command=False):
    """dialog ごとに (req, 種別, 理由, 詳細) を返す。 種別 = hook / fixed / length / rule / rule_unique / unmatched。
    突合は match_dialogs (同じ session / 応答より後の tool_result / 待ち行列の順)。
    show_command = hook 由来の行の詳細に、 hook の理由に加えて当時の呼び出しの全文 (Bash は command を 1 行に) を足す
    (= 外部発信の guard の dialog が実際の送信かを 1 件ずつ読むとき。 既定は理由だけ)。"""
    rows = []
    matched = match_dialogs(reqs_list, uses, results, before, after, session_map, queue_window)
    for r in reqs_list:
        u, how, cli = matched[_rid(r)]
        gate = app_gate(r.get("tool", ""))
        if gate:
            if u is not None:
                r["_input"] = u["input"] if isinstance(u["input"], dict) else {}
            rows.append((r, "app", gate, brief_input(u["name"], r.get("_input") or {}) if u is not None else ""))
            continue
        if u is None:
            why = ("同じ session に対応する tool 呼び出しが無い (transcript 欠落 / 期間の外)" if cli
                   else "session の対応づけ (Mapping 行) が log に無く、 窓の中にも候補が無い")
            rows.append((r, "unmatched", why, ""))
            continue
        tool = u["name"]
        inp = u["input"] if isinstance(u["input"], dict) else {}
        r["_input"] = inp
        detail = brief_input(tool, inp)
        if how == "queue":
            detail = (detail + "  " if detail else "") + "(待ち行列: tool_use は dialog より前)"
        elif how == "unmapped":
            detail = (detail + "  " if detail else "") + "(session 不明: 時刻の窓だけで突合)"
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
                    r["_hook"] = hit[0]
                    break
        if hit:
            # block (exit 2) は Claude にしか返らない = dialog は出ない。 ∴ 当時 dialog が出た
            # この形も、 今は hook が先に止める (= 対処済み) と読める。 ask/deny は今も出る。
            shown = hit[2] or detail
            if show_command:
                full = (str(inp.get("command", "")).replace("\n", " ⏎ ") if tool == "Bash"
                        else brief_input(tool, inp))
                if full and full != shown:
                    shown = f"{shown}\n      ⮑ {full}" if shown else full
            rows.append((r, "fixed" if hit[1] == "block" else "hook",
                         f"{hit[0]} が {hit[1]}", shown))
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


def print_diagnosis(rows, run_hooks, hooks_n, only_hooks=""):
    if not rows:
        print("対象の dialog なし")
        return
    by = {}
    for _r, kind, _why, _d in rows:
        by[kind] = by.get(kind, 0) + 1
    print(f"permission dialog {len(rows)} 件 — 原因: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
    print(f"  (PreToolUse hook {hooks_n} 本を実際に流し直して判定)" if run_hooks
          else "  (--no-run-hooks: hook を実行していないので hook 由来も rule に混ざる)")
    if run_hooks and only_hooks:
        print(f"  ⚠️ --only-hooks {only_hooks} で絞った = 絞りの外の hook の確認は rule (hook 無反応) に入る"
              " (件数の比べには絞らない run を使う)")
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
        who = {row[0]["id"]: (row[1], row[2]) for row in rows}
        check(who["bbb"] == ("main", "Bash python3"), f"main の Bash を先頭語 bucket (got {who['bbb']})")
        check(who["ccc"] == ("sub-agent", "Edit ~/work/repo"), f"sub-agent の Edit を path 上位 2 階層 (got {who['ccc']})")
        check(who["aaa"][0] == "unmatched", "突合できない dialog は unmatched")

        # --- 突合の 3 制約: 同じ session / 応答より後の tool_result / 待ち行列の順 ---
        # (旧版 = 時刻が最も近い同名 tool を session を問わず選ぶ、 はこの block 全体が赤になる)
        try:
            T = local_epoch("2026-09-11 16:00:00")
            smap = {"local_1": [(T - 600, "S1")], "local_2": [(T - 600, "S2")]}

            def use(i, t, cli, msg, name="Bash"):
                return {"t": t, "name": name, "input": {"command": f"cmd{i}"}, "id": f"id{i}", "sub": False,
                        "path": tmp, "cli": cli, "msg": msg, "seq": i}

            def rq(rid, local, emit, resp=None, tool="Bash"):
                return {"id": rid, "emit": emit, "resp": resp, "tool": tool, "decision": "once", "session": local}

            us = [use(1, T - 1, "S1", "m1"), use(2, T - 5, "S2", "m2")]
            m = match_dialogs([rq("d1", "local_2", T, T + 3)], us, {}, 8, 2, smap)
            check(m["d1"][0]["id"] == "id2" and m["d1"][1] == "direct",
                  "同じ session の呼び出しを選ぶ (時刻がより近い別 session の同名 tool には付けない)")
            m = match_dialogs([rq("d1", "local_2", T, T + 3)], [use(1, T - 1, "S1", "m1")], {}, 8, 2, smap)
            check(m["d1"][0] is None and m["d1"][2] == "S2", "同じ session に候補が無ければ unmatched (別 session へ fallback しない)")
            m = match_dialogs([rq("d1", "local_9", T, T + 3)], [use(1, T - 1, "S1", "m1")], {}, 8, 2, smap)
            check(m["d1"][0] is not None and m["d1"][1] == "unmapped", "Mapping 行が無い dialog は窓だけで選び unmapped と出す")
            us = [use(1, T - 2, "S1", "m1"), use(2, T - 6, "S1", "m2")]
            m = match_dialogs([rq("d1", "local_1", T, T + 3)], us, {"id1": T - 1, "id2": T + 4}, 8, 2, smap)
            check(m["d1"][0]["id"] == "id2", "応答より前に tool_result が出た呼び出しは候補から外す")
            us = [use(1, T, "S1", "mm"), use(2, T, "S1", "mm"), use(3, T, "S1", "mm")]
            res = {"id1": T + 4.5, "id2": T + 8.5, "id3": T + 33.5}
            rs = [rq("d1", "local_1", T + 0.1, T + 4), rq("d2", "local_1", T + 4.1, T + 8),
                  rq("d3", "local_1", T + 30, T + 33)]
            m = match_dialogs(rs, us, res, 8, 2, smap)
            got = [(m[k][0]["id"] if m[k][0] else None, m[k][1]) for k in ("d1", "d2", "d3")]
            check(got == [("id1", "direct"), ("id2", "direct"), ("id3", "queue")],
                  f"並列の 3 呼び出しに順に出る 3 dialog を待ち行列の順で 1 対 1 (窓の外の 3 つ目は queue) (got {got})")
            m = match_dialogs([rq("d1", "local_1", T + 0.1, T + 4), rq("d2", "local_1", T + 1, T + 6)],
                              [use(1, T, "S1", "mm")], {}, 8, 2, smap)
            check(m["d1"][0] is not None and m["d2"][0] is None, "割り当て済みの tool_use は 2 つ目の dialog の候補にしない")
            m = match_dialogs([rq("d1", "local_1", T + 600, T + 603)], [use(1, T, "S1", "m1")], {}, 8, 2, smap,
                              queue_window=300)
            check(m["d1"][0] is None, "--queue-window より古い候補は待ち行列でも拾わない")

            (logs / "main5.log").write_text(
                "2026-09-11 15:50:00 [info] Mapping internal session local_7 to CLI session S7a\n"
                "2026-09-11 15:50:00 [info] Mapping internal session local_7 to CLI session S7a\n"
                "2026-09-11 16:10:00 [info] Mapping internal session local_7 to CLI session S7b\n"
                "2026-09-11 11:00:00 [info] Mapping internal session local_1 to CLI session sess\n"
                "2026-09-11 11:00:00 [info] Mapping internal session local_2 to CLI session sess\n"
                "2026-09-11 11:00:00 [info] Mapping internal session local_3 to CLI session other\n"
                "2026-09-11 12:59:59 [info] Emitted tool permission request eee for Bash in session local_3\n",
                encoding="utf-8")
            sm = parse_session_map(logs)
            check([c for _t, c in sm.get("local_7", [])] == ["S7a", "S7b"],
                  f"Mapping 行を dedupe して時刻順に持つ (got {sm.get('local_7')})")
            check(cli_session_for(sm, "local_7", T) == "S7a" and cli_session_for(sm, "local_7", T + 1200) == "S7b",
                  "再開で付け替わった session は dialog の時刻で引く")
            check(cli_session_for(sm, "local_7", T - 7200) == "S7a", "最初の Mapping より前の dialog は最初の session に寄せる")
            check(transcript_session_id(Path("/p/-x/abc.jsonl")) == "abc"
                  and transcript_session_id(Path("/p/-x/abc/subagents/agent-1.jsonl")) == "abc",
                  "transcript の path から session id (sub-agent は親 dir の名前)")
            check(all("cli" in u and "msg" in u and "seq" in u for u in uses) and {u["cli"] for u in uses} == {"sess"},
                  "load_tool_events が cli / msg / seq を付ける (sessionId が無ければ path から)")
            rows2 = attribute(parse_logs(logs, "2026-09-11"), uses, 8, 2, home, results=results, session_map=sm)
            who2 = {r["id"]: (w, h) for r, w, _b, h in rows2}
            check(who2["bbb"] == ("main", "direct") and who2["eee"] == ("unmatched", None),
                  f"attribute: 1 秒前に出た別 session の dialog は同じ Bash を横取りせず unmatched (got {who2['bbb']}, {who2['eee']})")
            rows3 = diagnose([parse_logs(logs, "2026-09-11")["eee"]], uses, 8, 2, [], 3000,
                             run_hooks=False, cwd=tmp, results=results, session_map=sm)
            check(rows3[0][1] == "unmatched" and "同じ session" in rows3[0][2],
                  f"diagnose: 別 session の dialog は unmatched と理由を出す (got {rows3[0][1]}: {rows3[0][2]})")
        except Exception as e:  # 突合が session を見ない版ではここに落ちる
            check(False, f"session / tool_result / 待ち行列の突合: {type(e).__name__}: {e}")

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
        rows_sc = diagnose([req("Write", 3000.0)], du, 8.0, 2.0, hooks, 3000, run_hooks=True, cwd=tmp,
                           show_command=True)
        check("理由の 1 行目" in rows_sc[0][3] and "/x/y.md" in rows_sc[0][3],
              "--show-command は hook 由来の行に理由と呼び出しの中身の両方を出す")
        check(filter_hooks([("Bash", "/h/a-guard.sh"), ("Bash", "/h/b.sh")], "a-guard") == [("Bash", "/h/a-guard.sh")]
              and len(filter_hooks([("Bash", "/h/a.sh"), ("Bash", "/h/b.sh")], "")) == 2,
              "--only-hooks は command の部分文字列で hook を絞る (空なら全部)")
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

        # アプリ自身の確認は hook を流し直す前に分ける (流し直すと今の hook の block で fixed に見える = 実測)
        st3 = tmp / "settings3.json"
        st3.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": ".*", "hooks": [{"type": "command", "command": f"sh {hd}/block.sh"}]}]}}), encoding="utf-8")
        du_app = [{"t": 5000.0, "name": "mcp__ccd_session_mgmt__set_session_effort",
                   "input": {"session_id": "local_x", "effort": "max"}, "id": "a1", "sub": False, "path": tmp}]
        rows_app = diagnose([req("mcp__ccd_session_mgmt__set_session_effort", 5000.0), req("browser:open_site", 6000.0)],
                            du_app, 8.0, 2.0, load_pretooluse_hooks([str(st3)]), 3000, run_hooks=True, cwd=tmp)
        check([k for _r, k, _w, _d in rows_app] == ["app", "app"],
              f"set_session_effort と内蔵ブラウザのサイトは app (block する hook があっても fixed にしない) (got {[k for _r, k, _w, _d in rows_app]})")
        check("app" in FIXES, "app に消し方の文言がある")

        # 本人が dialog の文字だけで決められるか (--judgeable)
        check(has_send_segment("cd x && python3 send_mail.py --to a --send") and not has_send_segment("send_mail.py --to a")
              and not has_send_segment("python3 x.py --send-later") and not has_send_segment("echo '--send' >> notes.md"),
              "本送信の形 = 単純 command に `--send` (dry-run・別の flag・引用符の中の見本は数えない)")

        def jr(kind, tool="Bash", hook="", cmd=""):
            rr = {"emit": 1.0, "tool": tool, "_hook": hook, "_input": {"command": cmd}}
            return (rr, kind, "", "")
        kw = dict(judgeable_hooks=("protected-dir",), send_hooks=("mail-send-guard",), judgeable_tools=("run_in_terminal",))
        got = [judge(jr("hook", hook="mail-send-guard.sh", tool="mcp__gmail-x__send_email"), **kw),
               judge(jr("hook", hook="mail-send-guard.sh", cmd="send_mail.py --send"), **kw),
               judge(jr("hook", hook="mail-send-guard.sh", cmd="python3 presend_replay.py"), **kw),
               judge(jr("hook", hook="protected-dir-access-guard.py"), **kw),
               judge(jr("hook", hook="ask-user-question-guard.sh", tool="AskUserQuestion"), **kw),
               judge(jr("rule"), **kw),
               judge(jr("rule", tool="mcp__terminal__run_in_terminal"), **kw),
               judge(jr("app", tool="browser:open_site"), **kw),
               judge(jr("fixed"), **kw)]
        check(got == ["judgeable", "judgeable", "not", "judgeable", "not", "not", "judgeable", "judgeable", "gone"],
              f"judge: 送信の tool / 本送信 / 送信でない / 宣言した hook / 宣言していない hook / rule / 宣言した tool / app / fixed (got {got})")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_judgeable([jr("app", tool="browser:open_site"), jr("fixed")], surface=True, **kw)
        check(buf.getvalue() == "", "--surface は決められない確認が 0 件なら何も出さない")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_judgeable([jr("rule"), jr("rule"), jr("app", tool="browser:open_site")], surface=True, **kw)
        check("決められないもの 2 件" in buf.getvalue() and "決められる 1" in buf.getvalue(),
              f"--surface は決められない確認の件数と内訳を出す (got {buf.getvalue()[:80]!r})")

        # 既定 (projects_dir=None) = この機械の全部の設定フォルダ。 偽の HOME に既定とアカウント固定の 2 つ
        if _ccd is not None:
            fh_home = tmp / "cfg-home"
            for cfg, tid in ((".claude", "c1"), (".claude-alt", "c2")):
                d = fh_home / cfg / "projects" / "-w"
                d.mkdir(parents=True)
                (d / f"s-{tid}.jsonl").write_text(json.dumps(
                    {"type": "assistant", "timestamp": iso("2026-09-11 12:00:00"),
                     "message": {"content": [{"type": "tool_use", "id": tid, "name": "Read", "input": {}}]}}) + "\n",
                    encoding="utf-8")
            # アカウント固定の設定フォルダの memory は既定の memory への symlink (二重に読まない)
            (fh_home / ".claude" / "projects" / "-w" / "memory").mkdir()
            (fh_home / ".claude" / "projects" / "-w" / "memory" / "m.jsonl").write_text("{}\n", encoding="utf-8")
            os.symlink(fh_home / ".claude" / "projects" / "-w" / "memory", fh_home / ".claude-alt" / "projects" / "-w" / "memory")
            saved = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIRS_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECTS_DIR")}
            try:
                for k in saved:
                    os.environ.pop(k, None)
                os.environ["CLAUDE_CONFIG_DIRS_HOME"] = str(fh_home)
                au, _ar = load_tool_events(None, "2026-09-11", want_results=True)
                paths = list(_transcript_paths(None))
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            check(sorted(u["id"] for u in au) == ["c1", "c2"], "既定 = 全部の設定フォルダの transcript を読む")
            check(sorted(config_label(u["path"]) for u in au) == ["", "alt"], "~/.claude 以外の設定フォルダの名を出す")
            check(sum(p.name == "m.jsonl" for p in paths) == 1, "symlink の memory は 1 回だけ")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    print(f"selftest: {'PASS' if not fails else 'FAIL'} ({len(fails)} failed)")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log-dir", default="~/Library/Logs/Claude", help="desktop app の log dir")
    ap.add_argument("--projects-dir", default=None,
                    help="transcript の親 dir (既定 = この機械の全部の設定フォルダの projects/)")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (local)")
    ap.add_argument("--latest", type=int, default=0, help="直近 N 件を 1 行ずつ")
    ap.add_argument("--attribute", action="store_true", help="transcript と時刻突合して main / sub-agent に振り分け")
    ap.add_argument("--before", type=float, default=8.0, help="突合窓: dialog 発行の何秒前まで (既定 8)")
    ap.add_argument("--after", type=float, default=2.0, help="突合窓: dialog 発行の何秒後まで (既定 2)")
    ap.add_argument("--queue-window", type=float, default=QUEUE_WINDOW,
                    help="並列の待ち行列で tool_use を遡る上限秒 (既定 3600。 同じ session の中だけ)")
    ap.add_argument("--from-transcripts", action="store_true", help="desktop log 無しで待ち時間から dialog 候補を推定")
    ap.add_argument("--wait", type=float, default=15.0, help="--from-transcripts の閾値秒 (既定 15)")
    ap.add_argument("--tools", default=",".join(FAST_TOOLS), help="--from-transcripts の対象 tool (カンマ区切り)")
    ap.add_argument("--diagnose", action="store_true",
                    help="dialog 1 件ごとに原因を切り分けて消し方を出す")
    ap.add_argument("--no-run-hooks", action="store_true",
                    help="--diagnose で hook を実際に実行しない (= 副作用のある PreToolUse hook を書いている場合)")
    ap.add_argument("--long-limit", type=int, default=3000,
                    help="--diagnose で「長すぎる Bash」 とみなす文字数 (既定 3000)")
    ap.add_argument("--settings", default=DEFAULT_SETTINGS,
                    help="hook 定義を読む settings (カンマ区切り)")
    ap.add_argument("--only-hooks", default="",
                    help="--diagnose で流し直す hook を、 command の部分文字列 (カンマ区切り) で絞る "
                         "(例 mail-send-guard,discord-post-guard)")
    ap.add_argument("--show-command", action="store_true",
                    help="--diagnose の hook 由来の行に、 当時の呼び出しの全文 (Bash は command を 1 行に) も出す")
    ap.add_argument("--judgeable", action="store_true",
                    help="--diagnose の結果を、 本人が dialog の文字だけで決められるか / 決められないか / もう出ないかで数える")
    ap.add_argument("--judgeable-hooks", default="",
                    help="--judgeable で「決められる」 に数える hook (command の部分文字列、 カンマ区切り。 例 = 保護 dir の名指しに確認を出す hook)")
    ap.add_argument("--send-hooks", default="",
                    help="--judgeable で、 本送信の形 (`--send` のある片) のときだけ「決められる」 に数える外部発信の hook (カンマ区切り)")
    ap.add_argument("--judgeable-tools", default="",
                    help="--judgeable で「決められる」 に数える tool (hook 無反応のもの。 例 = run_in_terminal)")
    ap.add_argument("--surface", action="store_true",
                    help="--judgeable で、 決められない確認が 0 件なら何も出さない (dashboard の段)")
    ap.add_argument("--since-days", type=int, default=0,
                    help="--since の代わりに「今日から N 日前」 (dashboard の段の直近 7 日など)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.since_days and not a.since:
        a.since = datetime.fromtimestamp(time.time() - a.since_days * 86400).strftime("%Y-%m-%d")
    if a.judgeable:
        a.diagnose = True
    home = Path.home()
    projects = Path(a.projects_dir).expanduser() if a.projects_dir else None
    if a.from_transcripts:
        uses, results = load_tool_events(projects, a.since, want_results=True)
        tools = tuple(t.strip() for t in a.tools.split(",") if t.strip())
        print_from_transcripts(from_transcripts(uses, results, a.wait, tools), home, a.wait)
        return 0
    log_dir = Path(a.log_dir).expanduser()
    if not log_dir.is_dir() and a.surface:
        return 0  # dashboard の段: dialog の log を持たない機械 (CLI だけ) では数えるものが無い = 沈黙
    if not log_dir.is_dir():
        print(f"desktop log dir が無い: {log_dir} — CLI 等なら --from-transcripts を使う", file=sys.stderr)
        return 2
    reqs, session_map = scan_logs(log_dir, a.since)
    if a.diagnose:
        sel = sorted(reqs.values(), key=lambda x: x["emit"])
        if a.latest:
            sel = sel[-a.latest:]
        uses, results = load_tool_events(projects, a.since, want_results=True)
        hooks = filter_hooks(load_pretooluse_hooks([s.strip() for s in a.settings.split(",") if s.strip()]),
                             a.only_hooks)
        rows = diagnose(sel, uses, a.before, a.after, hooks, a.long_limit,
                        run_hooks=not a.no_run_hooks, cwd=home / "Claude",
                        results=results, session_map=session_map, queue_window=a.queue_window,
                        show_command=a.show_command)
        if a.judgeable:
            def _csv(s):
                return tuple(x.strip() for x in s.split(",") if x.strip())
            print_judgeable(rows, surface=a.surface, judgeable_hooks=_csv(a.judgeable_hooks),
                            send_hooks=_csv(a.send_hooks), judgeable_tools=_csv(a.judgeable_tools))
            return 0
        print_diagnosis(rows, not a.no_run_hooks, len(hooks), a.only_hooks)
        return 0
    if a.latest:
        print_latest(reqs, a.latest)
        return 0
    print_summary(reqs, log_dir, a.since)
    if a.attribute:
        print("")
        uses, results = load_tool_events(projects, a.since, want_results=True)
        print_attribution(attribute(reqs, uses, a.before, a.after, home,
                                    results=results, session_map=session_map, queue_window=a.queue_window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
