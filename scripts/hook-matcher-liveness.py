#!/usr/bin/env python3
"""hook-matcher-liveness.py — hook の matcher が今の tool 名に当たっているかを、 会話記録に出た tool 名で確かめる (読むだけ)

なぜ要るか
----------
PreToolUse / PostToolUse の hook は matcher が tool 名に当たったときだけ走る。 tool が改名されると
matcher は黙って何にも当たらなくなり、 hook は配線も script も健全なまま 1 度も発火しない。 実測
(2026-10-20): desktop の tool `mcp__ccd_session__spawn_task` が `mcp__ccd_session__start_session` に改名された後、
改名前の名だけを matcher に持つ hook は 1 度も発火していなかった。 配線の健全性 (audit-hooks.sh の (a)(b)(c)) と
kill switch (hook-liveness-audit.py) はこれを見ない = 別の軸。

何を見るか
----------
1. matcher の出どころ (= 直す場所):
   - 各設定フォルダの `settings.json` / `settings.local.json` (= 実際に効いているもの。 symlink で同じ file は 1 回。
     列挙 = lib/claude_config_dirs.py)
   - この repo の `hooks/settings-entries.json` (層1 の配線の正本)
   - 個人層の `hooks/manifest.json` (個人層の検出は lib/find-personal-layer.sh と同じ規則)
   - 会話記録に出た作業 dir の `.claude/settings.json` / `.claude/settings.local.json`
   - `--source <file>` で足す。 `--settings <file>` を 1 つでも渡すと既定の出どころを全部置き換える
   同じ (event, matcher, command) は 1 行にまとめ、 出どころを並べる。
2. tool 名の集合 (直近 `--days` 日、 この機械の全部の設定フォルダの会話記録。 sub-agent の記録も読む):
   - 呼ばれた名 = assistant の `tool_use` の name と、 hook の発火記録 (`hookName` = `PreToolUse:<tool>`) の tool 名
   - 出ていた名 = `deferred_tools_delta` の addedNames / readdedNames と `prompt_snapshot` の tools[].name
     (= その session で使えた tool。 呼ばれていなくても在る)
   - 出ていた MCP server = 上の名の `mcp__<server>__` と、 `deferred_tools_delta` の needsAuth / pending / failed の server
3. matcher の当たり方は Claude Code の規則に合わせる (2.1.299 の本体の mQ / jSn / GHn を読んで写した):
   英数字・`_`・`|`・`,`・空白・`-` だけなら名の列挙 (`|` か `,` で区切り、 旧名は今の名に直す = `Task` は `Agent`)
   で完全一致、 それ以外は `new RegExp(matcher).test(名)` = 正規表現の部分一致 (先頭・末尾に固定しない) で、
   今の名と旧名の両方に当てる。 旧名の表 (LEGACY_ALIASES) と族の名 (FAMILY_NAMES = Artifact の action) は本体の
   写し = 版が変わったら本体を読み直す。 空・`*`・無しは全 tool に当たる (= 検査しない)。
   tool 名で選ばない event (SessionStart など) の matcher は検査しない。

判定 (matcher 1 本ごと。 matcher を `|` の選択肢に分け、 量化子の付かない `( | )` も展開して選択肢ごとにも見る)
----
  ✅ 生きている   = 呼ばれた名に当たる
  💤 眠っている   = 出ていた名には当たるが、 期間中に呼ばれていない (在る tool。 finding にしない)
  🔴 死んでいる   = どの名にも当たらない (組み込みの tool 名、 期間中に出ていた server の tool、 server を問わない
                    `mcp__.*__x` の形)。 改名の疑い
  🔴 途中で消えた = 当たる名が期間の途中から出ていない: その名を最後に見た後に始まった session のうち、 同じ出どころ
                    (server か組み込み) のほかの名を最後の session の 8 割以上持つものが `--gone-sessions` 本 (既定 5)
                    以上ある (= 改名・削除。 2026-10-20 の spawn_task → start_session は期間の途中で起きた)。 推定なので、
                    面ごとに出る tool が違うと生きた名を消えたと読むことがある (表の「途中で消えた名」 は参考)
  🟡 冗長       = 死んだ行だが、 同じ command が同じ event の生きた行にも配線されている (hook 自体は走る)
  ⚪ 確かめられない = MCP の tool で、 その server が期間中どの session にも出ていない (未接続か server の改名)。
                    確かめ方 = その server を繋いだ session の tool 一覧
  🟡 一部が死んでいる = matcher は生きているが、 選択肢のどれかが何にも当たらない (改名前の名の残り・消えた tool)
  🔵 広く当たる  = 正規表現の部分一致で、 識別子だけの選択肢 (`Agent`) が別の名 (`ListAgents`) にも当たる (表だけ)
  ❗ 正規表現として壊れている = どの tool にも当たらない

この機械の会話記録しか読まない。 期間中の session が `--min-sessions` 本に満たないときは判定を出さない
(= 証拠が薄い)。 plugin の hook (plugins/*/hooks/hooks.json) は読まない。

出力
----
既定 = 表。 `--findings-only` = 🔴 ⚪ ❗ と 🟡 の要約だけ (無ければ無出力 = dashboard / audit-hooks.sh 向け)。
`--json` = 機械向け。 `--strict` = 🔴 か ❗ があれば exit 1。 `--selftest` = temp dir の偽 settings + 偽会話記録で回帰検査。

使い方
------
  hook-matcher-liveness.py                     # 表 (直近 14 日)
  hook-matcher-liveness.py --findings-only     # finding だけ
  hook-matcher-liveness.py --days 30 --json
  hook-matcher-liveness.py --source path/to/manifest.json
  hook-matcher-liveness.py --selftest
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
try:
    import claude_config_dirs as _ccd
except Exception:  # pragma: no cover
    _ccd = None

REPO = Path(__file__).resolve().parent.parent
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}
SIMPLE_MATCHER = re.compile(r"^[A-Za-z0-9_|, -]+$")  # tool の event の単純形 (Claude Code 2.1.299 の jSn)
# 旧名 → 今の名 (2.1.299 の Xl の表)。 単純形の名はこの表で今の名に直してから比べ、 正規表現は今の名と旧名の両方に当てる。
LEGACY_ALIASES = {"Task": "Agent", "KillShell": "TaskStop", "KillBash": "TaskStop", "ListPeers": "ListAgents",
                  "Brief": "SendUserMessage", "ListMcpResources": "ListMcpResourcesTool",
                  "ReadMcpResource": "ReadMcpResourceTool", "ReadMcpResourceDir": "ReadMcpResourceDirTool"}
# 1 つの tool が別の名でも matcher に当たる族 (2.1.299 の cLt: Artifact の action ごと)
FAMILY_NAMES = {"Artifact": ("ArtifactComments", "ArtifactData", "ArtifactCheck")}
IDENT = re.compile(r"^[A-Za-z0-9_]+$")
SERVER_LITERAL = re.compile(r"^[A-Za-z0-9_.-]+$")
MCP_NAME = re.compile(r"^mcp__(.+?)__(.+)$")
EXPAND_CAP = 128


# ---------------------------------------------------------------- matcher の出どころ

def find_personal_layer(base=None):
    """lib/find-personal-layer.sh と同じ規則。 見つからなければ None。"""
    env = os.environ.get("CLAUDE_PERSONAL_LAYER", "")
    if env == "none":
        return None
    if env:
        p = Path(os.path.expanduser(env))
        ok = (p / ".claude-personal-layer").is_file() and (p / "CLAUDE.md").is_file()
        return p if ok else None
    base = Path(base) if base else REPO.parent
    hits = [Path(m).parent for m in glob.glob(str(base / "*" / ".claude-personal-layer"))]
    return hits[0] if len(hits) == 1 else None


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def hook_events(doc):
    """settings.json (`hooks` の下) と settings-entries.json / manifest.json (event が top) の両方を読む。"""
    if not isinstance(doc, dict):
        return {}
    h = doc.get("hooks") if isinstance(doc.get("hooks"), dict) else doc
    return {k: v for k, v in h.items() if not k.startswith("_") and isinstance(v, list)}


def _tilde(p):
    home = os.path.expanduser("~")
    p = str(p)
    return "~" + p[len(home):] if p.startswith(home) else p


def default_sources(project_roots):
    out = []
    seen = set()

    def add(path, label):
        try:
            real = os.path.realpath(path)
        except Exception:
            return
        if real in seen or not os.path.isfile(path):
            return
        seen.add(real)
        out.append((label, str(path)))

    dirs = _ccd.config_dirs() if _ccd else [os.path.expanduser("~/.claude")]
    for d in dirs:
        lab = _ccd.label(d) if _ccd else os.path.basename(d)
        for name in ("settings.json", "settings.local.json"):
            add(os.path.join(d, name), f"user:{lab}/{name}")
    add(REPO / "hooks" / "settings-entries.json", "layer1:hooks/settings-entries.json")
    layer = find_personal_layer()
    if layer:
        add(layer / "hooks" / "manifest.json", f"personal:{layer.name}/hooks/manifest.json")
    for root in sorted(project_roots):
        for name in ("settings.json", "settings.local.json"):
            add(os.path.join(root, ".claude", name), f"project:{_tilde(root)}/.claude/{name}")
    return out


def collect_entries(sources):
    """[(label, path)] → {(event, matcher, commands): set(labels)}。 読めない file は errors に。"""
    entries, errors = {}, []
    for label, path in sources:
        doc = load_json(path)
        if doc is None:
            errors.append(f"読めない: {label} ({path})")
            continue
        for ev, arr in hook_events(doc).items():
            for e in arr:
                if not isinstance(e, dict):
                    continue
                cmds = tuple(sorted(str(h.get("command", "")) for h in e.get("hooks", []) if isinstance(h, dict)))
                key = (ev, e.get("matcher"), cmds)
                entries.setdefault(key, set()).add(label)
    return entries, errors


# ---------------------------------------------------------------- tool 名の集合 (会話記録)

def transcript_list(projects_dirs, days, now=None):
    now = now or time.time()
    cutoff = now - days * 86400
    pats = ("*/*.jsonl", "*/*/subagents/*.jsonl")
    if projects_dirs:
        files = []
        for root in projects_dirs:
            for p in pats:
                files.extend(glob.glob(os.path.join(glob.escape(os.path.expanduser(root)), p)))
        files = sorted(set(files))
    elif _ccd:
        files = [f for _lab, f in _ccd.transcript_files(pats)]
    else:
        files = []
    out = []
    for f in files:
        try:
            if os.path.getmtime(f) >= cutoff:
                out.append(f)
        except OSError:
            continue
    return out


def _server_key(name):
    """表示名 (`plugin:cloudflare:cloudflare`、 `claude.ai Gmail`) を tool 名の server 部の形に寄せる。"""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _key_of(name):
    """名の「出どころ」: MCP なら server、 組み込みなら ""。 消えたかの判定で、 同じ出どころを持つ後の session を数える。"""
    m = MCP_NAME.match(name)
    return m.group(1) if m else ""


def scan_transcripts(files, days, now=None):
    """used / offered / servers / fired / roots / sessions / last_seen / last_where / session_keys を返す。
    行ごとの timestamp でも期間を切る。 last_seen = 名が最後に呼ばれたか出ていた時刻、 last_where = その session の番号、
    session_keys = session ごとの [開始時刻, {出どころ: その session に出ていた名の集合}]。"""
    now = now or time.time()
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - days * 86400))
    used, offered, servers, roots = {}, set(), set(), set()
    fired = {}  # (event, command) -> set(tool)
    last_seen, last_where = {}, {}
    session_keys = []
    sessions = 0

    def seen(name, ts, idx):
        if isinstance(ts, str) and ts > last_seen.get(name, ""):
            last_seen[name] = ts
            if idx is not None:
                last_where[name] = idx

    for f in files:
        main = "/subagents/" not in f
        if main:
            sessions += 1
        start, idx = None, None
        if main:
            session_keys.append([None, {}])
            idx = len(session_keys) - 1
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        got_cwd = not main
        with fh:
            for line in fh:
                if start is None and main and '"timestamp":"' in line:
                    m = re.search(r'"timestamp":"([^"]+)"', line)
                    if m:
                        start = m.group(1)
                if not got_cwd and '"cwd":"' in line:
                    m = re.search(r'"cwd":"((?:[^"\\]|\\.)*)"', line)
                    if m:
                        try:
                            roots.add(json.loads('"' + m.group(1) + '"'))
                            got_cwd = True
                        except Exception:
                            pass
                if not ('"tool_use"' in line or '"deferred_tools_delta"' in line
                        or '"prompt_snapshot"' in line or '"hookName"' in line):
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ts = d.get("timestamp")
                if isinstance(ts, str) and ts[:19] < cutoff_iso:
                    continue
                t = d.get("type")
                names = []
                if t == "assistant":
                    content = (d.get("message") or {}).get("content")
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "tool_use" and isinstance(c.get("name"), str):
                                used[c["name"]] = used.get(c["name"], 0) + 1
                                names.append(c["name"])
                elif t == "attachment":
                    a = d.get("attachment") or {}
                    at = a.get("type")
                    if at == "deferred_tools_delta":
                        for k in ("addedNames", "readdedNames"):
                            got = [n for n in a.get(k) or [] if isinstance(n, str)]
                            offered.update(got)
                            names.extend(got)
                        for k in ("needsAuthMcpServers", "pendingMcpServers", "failedMcpServers"):
                            for s in a.get(k) or []:
                                name = s.get("name") if isinstance(s, dict) else s
                                if isinstance(name, str):
                                    servers.add(_server_key(name))
                    elif at == "prompt_snapshot":
                        for tool in a.get("tools") or []:
                            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                                offered.add(tool["name"])
                                names.append(tool["name"])
                    hn = a.get("hookName")
                    if isinstance(hn, str) and ":" in hn:
                        ev, tool = hn.split(":", 1)
                        if ev in TOOL_EVENTS and tool:
                            used.setdefault(tool, 0)
                            names.append(tool)
                            cmd = a.get("command")
                            if isinstance(cmd, str) and cmd:
                                fired.setdefault((ev, cmd), set()).add(tool)
                for n in names:
                    seen(n, ts, idx)
                    if idx is not None:
                        session_keys[idx][1].setdefault(_key_of(n), set()).add(n)
        if idx is not None:
            session_keys[idx][0] = start
    for parent, fam in FAMILY_NAMES.items():
        if parent in used or parent in offered:
            offered.update(fam)
            for n in fam:
                if parent in last_seen:
                    seen(n, last_seen[parent], last_where.get(parent))
    for n in list(used) + list(offered):
        m = MCP_NAME.match(n)
        if m:
            servers.add(m.group(1))
    return {"used": used, "offered": offered, "servers": servers, "fired": fired,
            "roots": roots, "sessions": sessions, "last_seen": last_seen, "last_where": last_where,
            "session_keys": session_keys}


GONE_COVER = 0.8


def gone_names(scan, gone_sessions):
    """期間の途中で消えた名 → {名: (最後に見えた時刻, 証拠になった後の session の数)}。
    その名を最後に見た後に始まった session のうち、 同じ出どころ (MCP なら server、 組み込みなら組み込みの tool) の
    ほかの名を、 最後に見た session の GONE_COVER 以上持っている session を数え、 gone_sessions 本以上なら消えたと
    みなす (= 改名・削除)。 2026-10-20 の spawn_task → start_session は期間の途中で起きたので、 期間全体の集合だけ
    では生きて見えた。 ほかの名の重なりを求めるのは、 面によって出る組み込みの tool が違うから (CLI にだけ在る
    TaskCreate を、 後の desktop の session に無いだけで消えたとしない)。"""
    sess = [(st, by) for st, by in scan["session_keys"] if st]
    out = {}
    for name, ls in scan["last_seen"].items():
        key = _key_of(name)
        w = scan["last_where"].get(name)
        base = (set(scan["session_keys"][w][1].get(key, ())) - {name}) if w is not None else set()
        n = 0
        for st, by in sess:
            if st <= ls or key not in by or name in by[key]:
                continue
            if base and len(base & by[key]) < GONE_COVER * len(base):
                continue
            n += 1
        if n >= gone_sessions:
            out[name] = (ls, n)
    return out


# ---------------------------------------------------------------- matcher の展開と判定

def _split_top(s):
    """括弧・文字クラスの外の `|` で分ける。"""
    parts, depth, buf, i, in_cls = [], 0, "", 0, False
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            buf += s[i:i + 2]
            i += 2
            continue
        if in_cls:
            in_cls = ch != "]"
        elif ch == "[":
            in_cls = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            parts.append(buf)
            buf = ""
            i += 1
            continue
        buf += ch
        i += 1
    parts.append(buf)
    return parts


def _expand_seq(s):
    """1 つの選択肢 → [(regex, 表示)]。 量化子の付かない `(…|…)` / `(?:…|…)` を展開する (上限 EXPAND_CAP)。"""
    results = [("", "")]
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            tok = s[i:i + 2]
            results = [(r + tok, d + tok) for r, d in results]
            i += 2
            continue
        if ch == "[":
            j = i + 1
            if j < len(s) and s[j] == "]":
                j += 1
            while j < len(s) and s[j] != "]":
                j += 2 if s[j] == "\\" else 1
            tok = s[i:j + 1]
            results = [(r + tok, d + tok) for r, d in results]
            i = j + 1
            continue
        if ch == "(":
            depth, j, in_cls = 1, i + 1, False
            while j < len(s) and depth:
                c = s[j]
                if c == "\\":
                    j += 2
                    continue
                if in_cls:
                    in_cls = c != "]"
                elif c == "[":
                    in_cls = True
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                j += 1
            group = s[i:j]
            inner = group[1:-1]
            quantified = j < len(s) and s[j] in "*+?{"
            plain = not inner.startswith("?") or inner.startswith("?:")
            if inner.startswith("?:"):
                inner = inner[2:]
            if quantified or not plain:
                results = [(r + group, d + group) for r, d in results]
            else:
                alts = []
                for part in _split_top(inner):
                    alts.extend(_expand_seq(part))
                results = [(r + "(?:" + ar + ")", d + ad) for r, d in results for ar, ad in alts]
            if len(results) > EXPAND_CAP:
                return [(s, s)]
            i = j
            continue
        results = [(r + ch, d + ch) for r, d in results]
        i += 1
    return results


def alternatives(matcher):
    """matcher → (kind, [(表示, 当たり判定の関数)])。 kind = all / exact / regex / invalid。"""
    if matcher is None or matcher == "" or matcher == "*":
        return "all", []
    if SIMPLE_MATCHER.match(matcher):
        names = [n.strip() for n in re.split(r"[|,]", matcher) if n.strip()]
        return "exact", [(n, (lambda name, c=LEGACY_ALIASES.get(n, n): name == c)) for n in names]
    try:
        re.compile(matcher)
    except re.error:
        return "invalid", []
    out = []
    for part in _split_top(matcher):
        for rx, disp in _expand_seq(part):
            try:
                c = re.compile(rx)
            except re.error:
                c = re.compile(re.escape(rx))
            out.append((disp, (lambda name, c=c: any(c.search(f) for f in _forms(name)))))
    return "regex", out


def _forms(name):
    """正規表現を当てる名: 今の名と、 それに直る旧名 (2.1.299 の mQ は eae(e) の旧名にも当てる)。"""
    return [name] + [old for old, new in LEGACY_ALIASES.items() if new == name]


def matches_whole(kind, matcher, name):
    if kind == "all":
        return True
    if kind == "exact":
        return name in {LEGACY_ALIASES.get(n.strip(), n.strip()) for n in re.split(r"[|,]", matcher)}
    if kind == "regex":
        return any(re.search(matcher, f) for f in _forms(name))
    return False


def _no_hit_class(disp, servers):
    """当たりの無い選択肢の印: 'dead' か 'absent' (MCP で、 その server が期間中に出ていない)。"""
    body = disp.lstrip("^").rstrip("$")
    if not body.startswith("mcp__"):
        return "dead"
    rest = body[len("mcp__"):]
    k = rest.rfind("__")
    if k <= 0:
        return "dead"
    seg = rest[:k]
    if SERVER_LITERAL.match(seg):
        return "dead" if seg in servers else "absent"
    if seg.startswith(".") or ".*" in seg or ".+" in seg:
        return "dead"  # server を問わない形 = 出ていたどの server にも無い
    return "absent"  # 文字クラスなどで server を絞る形 = どの server の tool か決められない


def _day(ts):
    return ts[:10] if isinstance(ts, str) else "?"


def judge(entries, scan, gone_sessions=5):
    gone = gone_names(scan, gone_sessions)
    used = {n: c for n, c in scan["used"].items() if n not in gone}
    offered = scan["offered"] - set(gone)
    servers = scan["servers"]
    every = set(used) | offered
    rows = []
    for (ev, matcher, cmds), labels in entries.items():
        if ev not in TOOL_EVENTS:
            continue
        kind, alts = alternatives(matcher)
        row = {"event": ev, "matcher": matcher, "commands": list(cmds), "sources": sorted(labels),
               "kind": kind, "status": None, "used_hits": [], "offered_hits": [], "gone_hits": [],
               "dead_alts": [], "absent_alts": [], "broad": [], "fired": []}
        for c in cmds:
            for (fev, fcmd), tools in scan["fired"].items():
                if fev == ev and fcmd == c:
                    row["fired"].extend(sorted(tools))
        if kind in ("all", "invalid"):
            row["status"] = kind
            rows.append(row)
            continue
        row["used_hits"] = sorted(n for n in used if matches_whole(kind, matcher, n))
        row["offered_hits"] = sorted(n for n in offered - set(used) if matches_whole(kind, matcher, n))
        row["gone_hits"] = sorted(f"{n} (最後 {_day(gone[n][0])}、 以後 {gone[n][1]} session に無い)"
                                  for n in gone if matches_whole(kind, matcher, n))
        for disp, hit in alts:
            hits = [n for n in every if hit(n)]
            if not hits:
                old = sorted(n for n in gone if hit(n))
                if old:
                    row["dead_alts"].append(f"{disp} (最後 {max(_day(gone[n][0]) for n in old)})")
                elif _no_hit_class(disp, servers) == "dead":
                    row["dead_alts"].append(disp)
                else:
                    row["absent_alts"].append(disp)
            elif kind == "regex" and IDENT.match(disp):
                extra = sorted(n for n in hits if disp not in _forms(n))  # 旧名で当たる今の名 (Task → Agent) は意図どおり
                if extra:
                    row["broad"].append({"alt": disp, "also": extra[:8], "n": len(extra)})
        if row["used_hits"]:
            row["status"] = "live"
        elif row["offered_hits"]:
            row["status"] = "dormant"
        elif row["gone_hits"]:
            row["status"] = "gone"
        elif row["dead_alts"]:
            row["status"] = "dead"
        else:
            row["status"] = "absent"
        rows.append(row)
    # 死んだ行でも、 同じ command が同じ event の生きた行にも配線されていれば hook 自体は走る = 冗長な行
    alive = {(r["event"], c) for r in rows if r["status"] in ("live", "dormant", "all") for c in r["commands"]}
    for r in rows:
        if r["status"] in ("dead", "gone") and r["commands"] and all((r["event"], c) in alive for c in r["commands"]):
            r["status"] = "redundant"
            if not r["dead_alts"]:
                r["dead_alts"] = [str(r["matcher"])]
    order = {"invalid": 0, "dead": 1, "gone": 1, "absent": 2, "redundant": 3, "live": 4, "dormant": 5, "all": 6}
    rows.sort(key=lambda r: (order[r["status"]], r["event"], str(r["matcher"]), r["commands"]))
    return rows


# ---------------------------------------------------------------- 出力

MARK = {"invalid": "❗", "dead": "🔴", "gone": "🔴", "absent": "⚪", "redundant": "🟡", "live": "✅", "dormant": "💤",
        "all": "··"}


def _cmd_names(cmds):
    names = []
    for c in cmds:
        if not c:
            continue
        parts = c.split()
        names.append(" ".join([os.path.basename(parts[0])] + parts[1:]))
    return ", ".join(names) or "(command なし)"


def finding_lines(rows):
    out = []
    for r in rows:
        where = f"{_cmd_names(r['commands'])}; {', '.join(r['sources'])}"
        if r["status"] == "invalid":
            out.append(f"❗ {r['event']} matcher {r['matcher']!r} は正規表現として壊れている = どの tool にも当たらない ({where})")
        elif r["status"] == "dead":
            out.append(f"🔴 {r['event']} matcher {r['matcher']!r} がどの tool 名にも当たらない = 発火しない (改名の疑い) ({where})")
        elif r["status"] == "gone":
            out.append(f"🔴 {r['event']} matcher {r['matcher']!r} が当たる名は期間の途中で消えた = もう発火しない"
                       f" (改名か削除: {'; '.join(r['gone_hits'])}) ({where})")
        elif r["status"] == "absent":
            out.append(f"⚪ {r['event']} matcher {r['matcher']!r}: 当たる MCP server が期間中どの session にも出ていない"
                       f" (未接続か server の改名) ({where})")
    partial = {}
    for r in rows:
        if r["status"] in ("live", "dormant", "redundant"):
            for a in r["dead_alts"]:
                partial.setdefault(a, []).append(r)
    if partial:
        items = ", ".join(f"{a} ×{len(rs)}" for a, rs in sorted(partial.items(), key=lambda kv: (-len(kv[1]), kv[0])))
        out.append(f"🟡 何にも当たらない選択肢 (生きている matcher の中か、 同じ hook が別の行で生きている行): {items}"
                   f" (消えた tool か改名前の名。 行は表で)")
    return out


def _few(names, n=6):
    return ", ".join(names[:n]) + (" …" if len(names) > n else "")


def print_table(rows, scan, days, errors, sources):
    print(f"hook matcher liveness — 直近 {days} 日、 session {scan['sessions']} 本、 呼ばれた tool 名 {len(scan['used'])}、"
          f" 出ていた tool 名 {len(scan['offered'])}、 MCP server {len(scan['servers'])}")
    print("出どころ: " + "; ".join(lab for lab, _ in sources))
    for e in errors:
        print("  ⚠️ " + e)
    print()
    for r in rows:
        if r["status"] == "all":
            continue
        print(f"{MARK[r['status']]} {r['event']:<18} {str(r['matcher'])[:100]}  ← {_cmd_names(r['commands'])[:70]}")
        if r["status"] == "live":
            print(f"      呼ばれた: {_few(r['used_hits'])}")
        elif r["status"] == "dormant":
            print(f"      出ていた (呼ばれていない): {_few(r['offered_hits'])}")
        elif r["status"] == "redundant":
            print("      この行は死んでいるが、 同じ hook は同じ event の別の行で走る (行を消せる)")
        if r["gone_hits"]:
            print(f"      途中で消えた名: {_few(r['gone_hits'], 3)}")
        if r["dead_alts"]:
            print(f"      🟡 何にも当たらない選択肢: {', '.join(r['dead_alts'])}")
        if r["absent_alts"] and r["status"] != "absent":
            print(f"      ⚪ server が出ていない選択肢: {_few(r['absent_alts'], 4)}")
        for b in r["broad"]:
            print(f"      🔵 '{b['alt']}' が部分一致で別の名 {b['n']} 個にも当たる: {', '.join(b['also'])}")
        if r["fired"]:
            print(f"      発火の記録 (出力を出した回だけ残る): {_few(sorted(set(r['fired'])))}")
        print(f"      出どころ: {', '.join(r['sources'])}")
    print()
    fl = finding_lines(rows)
    print("finding: " + ("なし" if not fl else ""))
    for x in fl:
        print("  " + x)


def run(sources, projects_dirs, days, min_sessions, now=None, extra_sources=(), gone_sessions=5):
    files = transcript_list(projects_dirs, days, now)
    scan = scan_transcripts(files, days, now)
    if sources is None:
        sources = default_sources(scan["roots"])
    sources = list(sources) + list(extra_sources)
    entries, errors = collect_entries(sources)
    rows = judge(entries, scan, gone_sessions)
    thin = scan["sessions"] < min_sessions
    return rows, scan, errors, sources, thin


# ---------------------------------------------------------------- selftest

def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")


def selftest():
    fails = []

    def check(cond, label):
        print(f"  {'PASS' if cond else 'FAIL'}: {label}")
        if not cond:
            fails.append(label)

    k, alts = alternatives("Edit|Write|MultiEdit")
    check(k == "exact" and [a for a, _ in alts] == ["Edit", "Write", "MultiEdit"], "完全一致の形は | で列挙")
    check(not alts[0][1]("NotebookEdit"), "完全一致の形は部分一致しない (Edit ≠ NotebookEdit)")
    k, alts = alternatives("mcp__.*__(spawn_task|start_session)")
    check(k == "regex" and [a for a, _ in alts] == ["mcp__.*__spawn_task", "mcp__.*__start_session"], "1 段の ( | ) を展開")
    k, alts = alternatives("^(Artifact|mcp__x__(a|b))$")
    check([a for a, _ in alts] == ["^Artifact$", "^mcp__x__a$", "^mcp__x__b$"], "入れ子の ( | ) と錨を展開")
    k, alts = alternatives("mcp__[0-9a-f]{8}__(x|y)")
    check([a for a, _ in alts] == ["mcp__[0-9a-f]{8}__x", "mcp__[0-9a-f]{8}__y"], "{n} と文字クラスは素通し")
    k, alts = alternatives("(ab)+c|d")
    check([a for a, _ in alts] == ["(ab)+c", "d"], "量化子付きの group は展開しない")
    k, alts = alternatives("Agent|Task")
    check(k == "exact" and alts[1][1]("Agent"), "単純形の旧名は今の名に直す (Task = Agent)")
    k, alts = alternatives("^Task$")
    check(k == "regex" and alts[0][1]("Agent") and not alts[0][1]("TaskStop"), "正規表現は旧名にも当てる (^Task$ は Agent に当たる)")
    k, alts = alternatives("mcp__gmail-lab__send_email, Bash")
    check(k == "exact" and [a for a, _ in alts] == ["mcp__gmail-lab__send_email", "Bash"], "単純形は , と - と空白も許す")
    check(alternatives("Bash(")[0] == "invalid", "壊れた正規表現は invalid")
    check(alternatives(None)[0] == "all" and alternatives("*")[0] == "all", "空・* は全 tool")

    tmp = Path(tempfile.mkdtemp())
    try:
        proj = tmp / "projects"
        now = time.time()
        iso = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - 3600))
        old = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - 40 * 86400))

        def tu(name, ts=iso):
            return {"type": "assistant", "timestamp": ts, "cwd": str(tmp / "work"),
                    "message": {"content": [{"type": "tool_use", "id": "t", "name": name, "input": {}}]}}

        recs = [
            {"type": "attachment", "timestamp": iso, "attachment": {
                "type": "deferred_tools_delta",
                "addedNames": ["mcp__ccd_session__start_session", "mcp__gmail-lab__send_email", "TaskStop"],
                "needsAuthMcpServers": [{"name": "cloud"}]}},
            {"type": "attachment", "timestamp": iso, "attachment": {
                "type": "prompt_snapshot", "tools": [{"name": "Bash"}, {"name": "Edit"}, {"name": "Agent"}]}},
            tu("Bash"), tu("Edit"), tu("Agent"), tu("ListAgents"),
            tu("OldTool", ts=old),
            {"type": "attachment", "timestamp": iso, "attachment": {
                "type": "hook_success", "hookName": "PreToolUse:Bash", "command": "~/.claude/hooks/a.sh"}},
        ]
        _write(proj / "-w" / "s1.jsonl", recs)
        for i in range(2, 4):
            _write(proj / "-w" / f"s{i}.jsonl", [tu("Bash")])
        _write(proj / "-w" / "s1" / "subagents" / "agent-x.jsonl", [tu("Read")])
        (tmp / "work" / ".claude").mkdir(parents=True)
        (tmp / "work" / ".claude" / "settings.local.json").write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Gone", "hooks": [{"type": "command", "command": "p.sh"}]}]}}), encoding="utf-8")
        st = tmp / "settings.json"
        st.write_text(json.dumps({"hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/a.sh"}]},
                {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "~/.claude/hooks/b.sh"}]},
                {"matcher": "mcp__ccd_session__spawn_task", "hooks": [{"type": "command", "command": "~/.claude/hooks/c.sh"}]},
                {"matcher": "mcp__.*__spawn_task", "hooks": [{"type": "command", "command": "~/.claude/hooks/c2.sh"}]},
                {"matcher": "mcp__.*__(spawn_task|start_session)", "hooks": [{"type": "command", "command": "~/.claude/hooks/d.sh"}]},
                {"matcher": "mcp__gmail-lab__send_email", "hooks": [{"type": "command", "command": "~/.claude/hooks/e.sh"}]},
                {"matcher": "mcp__slack-x__post", "hooks": [{"type": "command", "command": "~/.claude/hooks/f.sh"}]},
                {"matcher": "mcp__.*__start_session|Agent|Task", "hooks": [{"type": "command", "command": "~/.claude/hooks/g.sh"}]},
                {"matcher": "OldTool", "hooks": [{"type": "command", "command": "~/.claude/hooks/h.sh"}]},
                {"matcher": "Agent|Task", "hooks": [{"type": "command", "command": "~/.claude/hooks/j.sh"}]},
                {"matcher": "ArtifactData", "hooks": [{"type": "command", "command": "~/.claude/hooks/k.sh"}]},
                {"matcher": "Bash(", "hooks": [{"type": "command", "command": "~/.claude/hooks/i.sh"}]},
            ],
            "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "~/.claude/hooks/s.sh"}]}],
        }}), encoding="utf-8")
        st2 = tmp / "settings-entries.json"
        st2.write_text(json.dumps({"_comment": "x", "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/a.sh"}]}]}), encoding="utf-8")

        rows, scan, errors, _src, thin = run([("user", str(st)), ("layer1", str(st2))], [str(proj)], 14, 3, now)
        by = {(r["matcher"], tuple(r["commands"])): r for r in rows}

        def status(m, c):
            return by[(m, (c,))]["status"]

        check(scan["sessions"] == 3 and not thin, "session は本体の記録だけを数える (sub-agent は数えない)")
        check("Read" in scan["used"], "sub-agent の記録の tool_use も読む")
        check("OldTool" not in scan["used"], "期間の外の行は数えない")
        check(scan["roots"] == {str(tmp / "work")}, "作業 dir を会話記録から拾う")
        check(status("Bash", "~/.claude/hooks/a.sh") == "live", "✅ 呼ばれた名に当たる")
        check(by[("Bash", ("~/.claude/hooks/a.sh",))]["sources"] == ["layer1", "user"], "同じ配線は 1 行で出どころを並べる")
        check(by[("Bash", ("~/.claude/hooks/a.sh",))]["fired"] == ["Bash"], "hook の発火記録を拾う")
        r = by[("Edit|Write|MultiEdit", ("~/.claude/hooks/b.sh",))]
        check(r["status"] == "live" and r["dead_alts"] == ["Write", "MultiEdit"], "🟡 生きている matcher の死んだ選択肢")
        check(status("mcp__ccd_session__spawn_task", "~/.claude/hooks/c.sh") == "dead", "🔴 出ていた server の消えた tool")
        check(status("mcp__.*__spawn_task", "~/.claude/hooks/c2.sh") == "dead", "🔴 server を問わない形 (2026-10-20 の実例)")
        r = by[("mcp__.*__(spawn_task|start_session)", ("~/.claude/hooks/d.sh",))]
        check(r["status"] == "dormant" and r["dead_alts"] == ["mcp__.*__spawn_task"], "💤 + 🟡 改名後の名を足した形")
        check(status("mcp__gmail-lab__send_email", "~/.claude/hooks/e.sh") == "dormant", "💤 出ていたが呼ばれていない")
        check(status("mcp__slack-x__post", "~/.claude/hooks/f.sh") == "absent", "⚪ server が出ていない MCP")
        r = by[("mcp__.*__start_session|Agent|Task", ("~/.claude/hooks/g.sh",))]
        check(r["status"] == "live" and any(b["alt"] == "Agent" and "ListAgents" in b["also"] for b in r["broad"])
              and any(b["alt"] == "Task" and "TaskStop" in b["also"] and "Agent" not in b["also"] for b in r["broad"]),
              "🔵 部分一致で別の名にも当たる (旧名で当たる今の名は除く)")
        check(status("OldTool", "~/.claude/hooks/h.sh") == "dead", "🔴 期間の外でしか呼ばれていない名")
        check(status("Bash(", "~/.claude/hooks/i.sh") == "invalid", "❗ 壊れた正規表現")
        r = by[("Agent|Task", ("~/.claude/hooks/j.sh",))]
        check(r["status"] == "live" and r["dead_alts"] == [], "旧名 Task は死んだ選択肢にしない")
        check(status("ArtifactData", "~/.claude/hooks/k.sh") == "dead", "族の親 (Artifact) が出ていなければ族の名は無い")
        check(not any(r["event"] == "SessionStart" for r in rows), "tool 名で選ばない event は検査しない")
        fl = finding_lines(rows)
        check(any(x.startswith("🔴") and "spawn_task" in x for x in fl), "finding に 🔴 が出る")
        check(any(x.startswith("🟡") and "MultiEdit ×1" in x for x in fl), "finding の 🟡 は選択肢ごとに数える")
        check(not any(x.startswith("💤") or x.startswith("✅") for x in fl), "finding に 💤 ✅ は出ない")

        # 期間の途中の改名: 古い session だけが spawn_task を持ち、 後の session は start_session だけを持つ
        proj2 = tmp / "projects2"

        def at(h):
            return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - h * 3600))

        def offer(names, ts):
            return {"type": "attachment", "timestamp": ts,
                    "attachment": {"type": "deferred_tools_delta", "addedNames": names}}

        _write(proj2 / "-w" / "old.jsonl", [offer(["mcp__ccd_session__spawn_task", "Bash"], at(100)),
                                           tu("mcp__ccd_session__spawn_task", at(99)), tu("Edit", at(99))])
        for i in range(6):
            _write(proj2 / "-w" / f"new{i}.jsonl", [offer(["mcp__ccd_session__start_session", "Bash"], at(50 - i)),
                                                   tu("Edit", at(49 - i))])
        st3 = tmp / "settings3.json"
        st3.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "mcp__ccd_session__spawn_task", "hooks": [{"type": "command", "command": "n.sh"}]},
            {"matcher": "mcp__.*__(spawn_task|start_session)", "hooks": [{"type": "command", "command": "d.sh"}]},
            {"matcher": "Edit", "hooks": [{"type": "command", "command": "b.sh"}]},
            {"matcher": "MultiEdit", "hooks": [{"type": "command", "command": "b.sh"}]},
        ]}}), encoding="utf-8")
        r5, _s5, _e5, _src5, _t5 = run([("u", str(st3))], [str(proj2)], 14, 3, now, gone_sessions=5)
        by5 = {(r["matcher"], tuple(r["commands"])): r for r in r5}
        g = by5[("mcp__ccd_session__spawn_task", ("n.sh",))]
        check(g["status"] == "gone" and "最後" in g["gone_hits"][0], "🔴 期間の途中で消えた名 (後の同じ server の session に無い)")
        d5 = by5[("mcp__.*__(spawn_task|start_session)", ("d.sh",))]
        check(d5["status"] == "dormant" and d5["dead_alts"] and d5["dead_alts"][0].startswith("mcp__.*__spawn_task (最後"),
              "🟡 改名前の選択肢に最後の日付を付ける")
        check(by5[("MultiEdit", ("b.sh",))]["status"] == "redundant", "🟡 死んだ行でも同じ hook が別の行で生きていれば冗長")
        r6, _s6, _e6, _src6, _t6 = run([("u", str(st3))], [str(proj2)], 14, 3, now, gone_sessions=10)
        by6 = {(r["matcher"], tuple(r["commands"])): r for r in r6}
        check(by6[("mcp__ccd_session__spawn_task", ("n.sh",))]["status"] == "live", "後の session が閾値に満たなければ消えたとしない")
        # 面の違い: CLI にだけ在る組み込み (TaskCreate) は、 後の desktop の session に無くても消えたとしない。
        # 組み込みの改名 (OldName → NewName、 ほかの tool は同じ) は消えたとする
        proj3, proj4 = tmp / "projects3", tmp / "projects4"
        _write(proj3 / "-w" / "cli.jsonl", [offer(["Bash", "Edit", "Read", "TaskCreate", "TaskGet"], at(100))])
        _write(proj4 / "-w" / "old.jsonl", [offer(["Bash", "Edit", "Read", "OldName"], at(100))])
        for i in range(6):
            _write(proj3 / "-w" / f"desk{i}.jsonl", [offer(["Bash"], at(50 - i))])
            _write(proj4 / "-w" / f"new{i}.jsonl", [offer(["Bash", "Edit", "Read", "NewName"], at(50 - i))])
        g3 = gone_names(scan_transcripts(transcript_list([str(proj3)], 14, now), 14, now), 5)
        check("TaskCreate" not in g3 and "TaskGet" not in g3, "面の違い (後の desktop に無い CLI の tool) は消えたとしない")
        g4 = gone_names(scan_transcripts(transcript_list([str(proj4)], 14, now), 14, now), 5)
        check("OldName" in g4 and "NewName" not in g4, "組み込みの改名 (ほかの tool は同じ) は消えたとする")

        fl5 = finding_lines(r5)
        check(any(x.startswith("🔴") and "途中で消えた" in x for x in fl5), "finding に途中で消えた 🔴 が出る")
        check(not any(x.startswith("🔴") and "'MultiEdit'" in x for x in fl5), "冗長な行は 🔴 にしない")

        srcs = default_sources(scan["roots"])
        check(any(lab.startswith("project:") and lab.endswith("settings.local.json") for lab, _ in srcs),
              "既定の出どころに作業 dir の .claude/settings.local.json が入る")
        _r2, _s2, _e2, _src2, thin2 = run([("user", str(st))], [str(proj)], 14, 5, now)
        check(thin2, "session が min に満たなければ証拠が薄い")
        _r3, _s3, e3, _src3, _t3 = run([("broken", str(tmp / "nope.json"))], [str(proj)], 14, 3, now)
        check(e3 and "読めない" in e3[0], "読めない出どころは errors に")
        r4, _s4, _e4, src4, _t4 = run([("user", str(st))], [str(proj)], 14, 3, now, [("extra", str(st2))])
        check([lab for lab, _ in src4] == ["user", "extra"], "--source は既定・置き換えの出どころに足す")

        base = tmp / "base"
        (base / "prefs").mkdir(parents=True)
        (base / "prefs" / ".claude-personal-layer").write_text("")
        (base / "prefs" / "CLAUDE.md").write_text("")
        saved = os.environ.pop("CLAUDE_PERSONAL_LAYER", None)
        try:
            check(find_personal_layer(base) == base / "prefs", "個人層を marker で見つける")
            (base / "other").mkdir()
            (base / "other" / ".claude-personal-layer").write_text("")
            check(find_personal_layer(base) is None, "marker が 2 つなら個人層なし")
            os.environ["CLAUDE_PERSONAL_LAYER"] = "none"
            check(find_personal_layer(base) is None, "CLAUDE_PERSONAL_LAYER=none で無効")
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_PERSONAL_LAYER", None)
            else:
                os.environ["CLAUDE_PERSONAL_LAYER"] = saved
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"selftest: {'OK' if not fails else 'FAIL ' + str(len(fails))}")
    return 0 if not fails else 1


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=14, help="会話記録の期間 (日、 既定 14)")
    ap.add_argument("--min-sessions", type=int, default=5, help="判定を出す最小の session 数 (既定 5)")
    ap.add_argument("--gone-sessions", type=int, default=5,
                    help="名を最後に見た後、 同じ server を持つ session がこの数だけ始まって出ていなければ消えたとみなす (既定 5)")
    ap.add_argument("--source", action="append", default=[], help="matcher の出どころを足す (settings 形式か event が top の json)")
    ap.add_argument("--settings", action="append", default=[], help="既定の出どころを置き換える (複数可)")
    ap.add_argument("--projects-dir", action="append", default=[], help="会話記録の dir (既定 = 全部の設定フォルダ)")
    ap.add_argument("--findings-only", action="store_true", help="🔴 ⚪ ❗ 🟡 だけ (無ければ無出力)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="🔴 か ❗ があれば exit 1")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    sources = [(f"arg:{_tilde(p)}", os.path.expanduser(p)) for p in a.settings] or None
    extra = [(f"arg:{_tilde(p)}", os.path.expanduser(p)) for p in a.source]
    rows, scan, errors, used_sources, thin = run(sources, a.projects_dir, a.days, a.min_sessions, extra_sources=extra,
                                                 gone_sessions=a.gone_sessions)
    if a.json:
        print(json.dumps({"days": a.days, "sessions": scan["sessions"], "thin": thin, "errors": errors,
                          "sources": used_sources, "rows": rows,
                          "findings": [] if thin else finding_lines(rows)}, ensure_ascii=False, indent=1))
    elif a.findings_only:
        if thin:
            return 0
        for x in finding_lines(rows):
            print(x)
        for e in errors:
            print("⚠️ hook-matcher-liveness: " + e)
    else:
        if thin:
            print(f"(期間中の session が {scan['sessions']} 本 < {a.min_sessions} = 証拠が薄いので判定は参考)")
        print_table(rows, scan, a.days, errors, used_sources)
    bad = (not thin) and any(r["status"] in ("dead", "gone", "invalid") for r in rows)
    return 1 if (a.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
