#!/usr/bin/env python3
"""check-session-carryover.py — 公開 repo の commit に、 同じ session で非公開の source から読んだ値 (金額・数・コードの並び) を持ち込ませない: commit gate (--staged、 違反で exit 1) + 過去の公開 commit の replay (--replay) + --selftest

## なぜ在るか

検出器を較正する・例を本物らしくする turn では、 非公開の記録 (暗号化した repo の commit message、 非公開 repo の file) を
tool で読み、 その値を **同じ session の中で** 公開 repo の selftest・コメント・docstring の例に写す (実測)。 写した値は
識別子でも語の一覧の語でもなく (額の組・本数・通貨コードの並び)、 逐語の網 (5 語以上の引用) にも活動の事実の網 (語 × 日付)
にも値の索引 (電話・口座・生年月日) にも掛からない。 「commit の前に、 較正で目にした値で追加行を grep する」 は散文の手順で、
commit と push を 1 本の command で打つと、 気づくのは push の後になる。

この検査は、 その手順を機械にする: 会話記録は「この session で何を読んだか」 を持っている。

## 何を見るか

  source  この session の会話記録 (env CLAUDE_CODE_SESSION_ID → ~/.claude*/projects/*/<id>.jsonl、 または --transcript) の
          tool の出力のうち、 **非公開の source を読んだもの**。 公開とみなすのは、 tool の入力に出る場所 (Read の file_path・
          Bash の command の path・その時の cwd) がすべて公開の印 (.claude/public-repo.marker) のある repo の中のときと、
          WebFetch / WebSearch だけ。 場所が分からない出力 (MCP・subagent の返事・cwd が repo の外) は非公開に数える。
          Edit / Write などの確認の出力は見ない。
  自作    値が最初に現れたのが agent 自身の入力 (返事の文・tool の入力) なら数えない = 自分で作った合成の値。
  sink    staged の追加行 (公開 repo の pre-commit) / replay では各 commit の追加行。
  除く    合成の例の形の数 (連番 1,234,567・同じ数字の並び 1,111) と、 主要通貨・よく使う形式名だけの並び (COMMON_CODES)。
  規則    (1 つでも当たれば BLOCK。 どれも「額の形」 に絞ってある = 一般の定数・ID・寸法・件数の誤検出を避ける)
    pair    同じ行に、 非公開の出力から来た 3 桁区切りの数 (1,234 の形) が 2 つ以上 (例: 額の組)
    long    非公開の出力から来た 7 桁以上の 3 桁区切りの数が 1 つ (長い額)
    money   数 (2 桁以上) と大文字 3 字のコードの組 (「59 XYZ」「XYZ 1,234」) が、 非公開の出力にそのまま在る (例: 通貨ごとの額・本数)
    codes   区切り (| , / 、) でつないだ大文字 3 字のコード 4 つの並びが、 非公開の出力に同じ順で在る (例: 通貨コードの一覧)
    pair と long は、 数の直後に件数の単位 (行・件・字・file・commit・byte …) が続くものを数えない。

当たった値は出さない (file:行 と規則の名前だけ)。 公開 repo の追加行そのものは公開に出る文なので、 replay の --show は見せる。

## 呼び方

  check-session-carryover.py --staged [--repo DIR] [--transcript JSONL]   (env CLAUDE_CARRYOVER_TRANSCRIPT でも渡せる)
      exit 0 = 当たり無し / 1 = BLOCK / 3 = 走らなかった (session も会話記録も無い = Claude の外の commit、 または検査の中の
      故障。 1 行出す。 呼び元は通す = 故障を違反と同じ値にしない)
  check-session-carryover.py --replay [--root DIR] [--since YYYY-MM-DD] [--show]
      公開の印の repo の commit のうち、 message の `Agent-Session: claude:<id>` から会話記録を引けるものを、 commit の時刻までの
      記録で判定し直す (誤検出の較正)。 repo ごとの commit 数・当たり数・規則ごとの数
  check-session-carryover.py --selftest

1 回だけ通す: env CLAUDE_CARRYOVER_GUARD=0 (形が CLAUDE_*_GUARD なので、 層1 の escape-hatch-guard が本人の明示の指示なしの
使用を止める)。 拒否の文面には書かない。

## 限界

- 読んだ値を言い換えた・計算し直した形 (額を足した・丸めた・桁を変えた) は拾わない。 1 つだけの短い数 (5,000 など) も拾わない
  (pair / long の形にしてある = 件数・行番号の誤検出を避ける)。
- Codex の commit は会話記録の場所が違うので走らない (0 + 1 行)。 subagent の中の commit は subagent の記録を見ない。
- 一般の知識でも非公開の出力に同じ並びで在れば当たる (例: 主要通貨の並び)。 その時は合成の並びに変えるか、 本人の判断で 1 回だけ通す。

設計と校正の記録 = conventions/confidential-repo-boundary.md#session-carryover-gate。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

MARKER = os.path.join(".claude", "public-repo.marker")
IGNORE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "TodoWrite", "ToolSearch", "AskUserQuestion", "SendMessage",
                "ScheduleWakeup", "Skill", "mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up"}
PUBLIC_TOOLS = {"WebFetch", "WebSearch"}
SYSTEM_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/dev/", "/System/", "/Library/", "/opt/homebrew/", "/Applications/", "/etc/")

NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{4,})(?![\w])")
COMMA = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
COUNT_UNIT = re.compile(r"\s*(?:行|字|文字|件|回|個|本|人|名|頁|ページ|枚|秒|分|時間|日|週|月|年|倍|%|％|B\b|KB|MB|GB|bytes?|"
                        r"lines?|files?|commits?|records?|entries|tokens?|chars?|rows?|ms\b|s\b|px|pt)")
MONEY = re.compile(r"(?<![\w.,\-/:])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{2,}(?:\.\d+)?)\s+([A-Z]{3})(?![A-Za-z])"
                   r"|(?<![A-Za-z])([A-Z]{3})\s+(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{2,}(?:\.\d+)?)(?![\w.,]\d)")
CODES = re.compile(r"(?<![A-Za-z])[A-Z]{3}(?:\s*[|,/、]\s*[A-Z]{3}){3,}(?![A-Za-z])")


def _digits(tok):
    return sum(c.isdigit() for c in tok)


def _is_year(tok):
    return re.fullmatch(r"(19|20)\d\d", tok) is not None


def _is_placeholder(tok):
    """合成の例の形 (連番 1,234,567 / 654321、 同じ数字の並び 1,111 / 99999) = 本物の値ではない。 区切りと小数点は外して見る。"""
    d = [int(c) for c in tok if c.isdigit()]
    if len(set(d)) == 1:
        return True
    steps = {b - a for a, b in zip(d, d[1:])}
    return steps in ({1}, {-1})


def num_tokens(text):
    out = set()
    for m in NUM.finditer(text):
        t = m.group(1)
        if _digits(t) < 4 or _is_year(t) or _is_placeholder(t):
            continue
        out.add(t)
    return out


def money_tokens(text):
    """数と大文字 3 字のコードの組 (順を問わない形に揃える) = 「59 XYZ」「XYZ 1,234」。"""
    out = set()
    for m in MONEY.finditer(text):
        n, c = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        if _is_year(n) or _is_placeholder(n) or c in NON_MONEY_CODES:
            continue
        out.add(f"{n}|{c}")
    return out


def _unit_follows(line, end):
    return COUNT_UNIT.match(line, end) is not None


def comma_amounts(line):
    """行の中の 3 桁区切りの数のうち、 件数の単位が続かず合成の形でもないもの。"""
    out = []
    for m in COMMA.finditer(line):
        if m.start() and (line[m.start() - 1].isalnum() or line[m.start() - 1] in ".,-/:"):
            continue
        if re.search(r"rgba?\(\s*$|hsla?\(\s*$", line[:m.start()]):
            continue  # CSS の色 (rgba(255,255,255,…)) は 3 桁区切りの数ではない
        if m.end() < len(line) and (line[m.end()].isalnum() or (line[m.end()] in ".," and line[m.end() + 1:m.end() + 2].isdigit())):
            continue
        t = m.group(0)
        if _is_placeholder(t) or _unit_follows(line, m.end()):
            continue
        out.append(t)
    return out


# 額の組に数えない大文字 3 字 (HTTP の動詞・形式名など。 数と並んでも額ではない)
NON_MONEY_CODES = {"GET", "PUT", "DEL", "AND", "NOT", "THE", "FOR", "PDF", "PNG", "JPG", "SVG", "GIF", "CSV", "TSV", "XML",
                   "TXT", "ZIP", "TEX", "BIB", "FPS", "DPI", "RGB", "CPU", "GPU", "RAM", "SSD", "API", "URL", "UTC", "JST",
                   "EOF", "TOC", "LOC", "ASM", "BPM", "RFC", "ISO", "JIS", "PEP", "CVE", "UTF", "SHA", "RCA", "FAQ",
                   "TBD", "WIP", "TCP", "UDP", "SSH", "DNS", "MCP", "CLI", "SDK", "LTS", "PID", "UID", "DOI"}


# 誰でも同じ並びで書く一般のコード (主要通貨・よく使う形式名)。 4 つの並びがこれだけなら数えない (一般の知識の誤検出)。
COMMON_CODES = {"USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD", "SEK", "NOK",
                "PDF", "PNG", "JPG", "SVG", "GIF", "CSV", "TSV", "XML", "TXT", "DOC", "XLS", "PPT", "ZIP", "TEX", "BIB",
                "GET", "PUT", "DEL", "AND", "NOT", "THE", "FOR"}


def code_tokens(text):
    out = set()
    for m in CODES.finditer(text):
        cs = re.findall(r"[A-Z]{3}", m.group(0))
        for i in range(len(cs) - 3):
            g = cs[i:i + 4]
            if all(c in COMMON_CODES for c in g):
                continue
            out.add("|".join(g))
    return out


def all_tokens(text):
    return ({"N:" + t for t in num_tokens(text)} | {"M:" + t for t in money_tokens(text)}
            | {"C:" + t for t in code_tokens(text)})


def line_hits(line, tainted):
    """1 行の当たり = 規則の名前の list。"""
    hits = []
    nums = {t for t in comma_amounts(line) if "N:" + t in tainted}
    if len(nums) >= 2:
        hits.append("pair")
    if any(_digits(t) >= 7 for t in nums):
        hits.append("long")
    if any("M:" + t in tainted for t in money_tokens(line)):
        hits.append("money")
    if any("C:" + c in tainted for c in code_tokens(line)):
        hits.append("codes")
    return hits


# ---------------------------------------------------------------- 公開か非公開か

_REPO_CACHE = {}


def repo_root(path):
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(p):
        p = os.path.dirname(p)
    cur = p
    while cur and cur != os.path.dirname(cur):
        if cur in _REPO_CACHE:
            return _REPO_CACHE[cur]
        if os.path.exists(os.path.join(cur, ".git")):
            _REPO_CACHE[p] = cur
            return cur
        cur = os.path.dirname(cur)
    _REPO_CACHE[p] = None
    return None


def is_public_path(path):
    """True = 公開の印のある repo の中 / False = それ以外 (repo の外も含む) / None = 見ない path (system)。"""
    ap = os.path.abspath(os.path.expanduser(path))
    if ap.startswith(SYSTEM_PREFIXES):
        return None
    root = repo_root(ap)
    return bool(root and os.path.isfile(os.path.join(root, MARKER)))


PATH_TOKEN = re.compile(r"(?:(?<=[\s'\"=:(])|^)((?:~|/)[^\s'\"|;&<>()`$]+)")


def bash_paths(command, cwd):
    paths = [m.group(1) for m in PATH_TOKEN.finditer(command)]
    if cwd:
        for tok in re.findall(r"[\w.\-][\w.\-/]*", command):
            if "/" in tok or os.path.isdir(os.path.join(cwd, tok)):
                cand = os.path.join(cwd, tok)
                if os.path.exists(cand):
                    paths.append(cand)
    return paths


def source_is_private(name, inp, cwd):
    """tool の出力が非公開の source を読んだものか。 None = 見ない tool。"""
    if name in IGNORE_TOOLS:
        return None
    if name in PUBLIC_TOOLS:
        return False
    paths = []
    if isinstance(inp, dict):
        if name == "Bash":
            paths = bash_paths(str(inp.get("command", "")), cwd)
        else:
            for k in ("file_path", "path", "notebook_path"):
                if inp.get(k):
                    paths.append(str(inp[k]))
    if not paths and cwd and name in ("Bash", "Grep", "Glob"):
        paths = [cwd]
    if not paths:
        return True  # 場所が分からない (MCP・subagent など) = 非公開に数える
    verdicts = [is_public_path(p) for p in paths]
    verdicts = [v for v in verdicts if v is not None]
    if not verdicts:
        return not (cwd and is_public_path(cwd))
    return not all(verdicts)


# ---------------------------------------------------------------- 会話記録

def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(str(b.get("text", "")))
                elif b.get("type") == "tool_result":
                    parts.append(_text(b.get("content")))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    return ""


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def events(path):
    """会話記録 → (時刻, 種類, 中身) の列。 種類 = authored (agent 自身の文・tool の入力) / private / public (tool の出力)。"""
    uses = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = o.get("type")
            msg = o.get("message") if isinstance(o.get("message"), dict) else {}
            content = msg.get("content")
            ts = _ts(o.get("timestamp"))
            cwd = o.get("cwd")
            if t == "assistant" and isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        yield ts, "authored", str(b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        uses[b.get("id")] = (b.get("name"), b.get("input"), cwd)
                        yield ts, "authored", json.dumps(b.get("input"), ensure_ascii=False)
            elif t == "user" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        name, inp, ucwd = uses.get(b.get("tool_use_id"), (None, None, cwd))
                        priv = source_is_private(name, inp, ucwd or cwd)
                        if priv is None:
                            continue
                        yield ts, "private" if priv else "public", _text(b.get("content"))


class Taint:
    """会話記録を順に読み、 非公開の出力から来た token の集合を育てる。"""

    def __init__(self):
        self.authored, self.tainted = set(), set()

    def feed(self, kind, text):
        toks = all_tokens(text)
        if kind == "authored":
            self.authored |= toks - self.tainted
        elif kind == "private":
            self.tainted |= toks - self.authored


def taint_of(path, until=None):
    tt = Taint()
    for ts, kind, text in events(path):
        if until is not None and ts is not None and ts > until:
            break
        tt.feed(kind, text)
    return tt.tainted


def find_transcript(session_id):
    pats = [os.path.expanduser(f"~/.claude*/projects/*/{session_id}.jsonl")]
    for p in pats:
        hits = sorted(glob.glob(p), key=os.path.getmtime, reverse=True)
        if hits:
            return hits[0]
    return None


# ---------------------------------------------------------------- 追加行

def added_lines(diff_text):
    """unified diff (-U0) → [(path, 行番号, 本文)]。"""
    out, path, n = [], None, 0
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            n = int(m.group(1)) if m else 0
        elif line.startswith("+") and path:
            out.append((path, n, line[1:]))
            n += 1
    return out


def check_lines(lines, tainted, already=None):
    """already(path) = the values the file already carries in its committed version (HEAD for --staged, the parent
    for --replay). Those are on the public surface already, so rewording or moving a line that holds them is not a new
    carryover (measured: a reworded line of an existing pair of numbers was stopped, and the values were moved to
    another line to get past). A value the committed file does not carry still counts."""
    res, cache = [], {}
    for path, n, body in lines:
        t = tainted
        if already is not None:
            if path not in cache:
                cache[path] = tainted - already(path)
            t = cache[path]
        h = line_hits(body, t)
        if h:
            res.append((path, n, h))
    return res


def committed_tokens(repo, rev):
    """path -> the tokens of the file at rev ('' when the file is new or rev is missing = nothing already public)."""
    return lambda path: all_tokens(git(repo, "show", f"{rev}:{path}"))


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, errors="replace").stdout


def cmd_staged(repo, transcript):
    if os.environ.get("CLAUDE_CARRYOVER_GUARD") == "0":
        print("check-session-carryover: CLAUDE_CARRYOVER_GUARD=0 = 今回は見ない", file=sys.stderr)
        return 0
    transcript = transcript or os.environ.get("CLAUDE_CARRYOVER_TRANSCRIPT")  # test と手で確かめる用
    if not transcript:
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        transcript = find_transcript(sid) if sid else None
    if not transcript or not os.path.isfile(transcript):
        print("check-session-carryover: 会話記録が無い (Claude の session の外の commit) = 走らなかった", file=sys.stderr)
        return 3
    tainted = taint_of(transcript)
    hits = check_lines(added_lines(git(repo, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff")), tainted,
                       committed_tokens(repo, "HEAD"))
    if not hits:
        return 0
    print("check-session-carryover: BLOCK — この session で非公開の source (暗号化した repo・非公開 repo の file・MCP など) から"
          " 読んだ値が、 公開 repo の追加行に在る (値は出さない):", file=sys.stderr)
    for path, n, h in hits[:30]:
        print(f"  {path}:{n} [{', '.join(h)}]", file=sys.stderr)
    if len(hits) > 30:
        print(f"  … ほか {len(hits) - 30} 行", file=sys.stderr)
    print("  直し方: 例・selftest・較正の文の値は合成の値で書く (読んだ本物を写さない)。 一般の知識 (公開の料金など) が"
          " たまたま同じなら、 本人に判断を聞く。 正本 = claude-config/conventions/confidential-repo-boundary.md#session-carryover-gate",
          file=sys.stderr)
    return 1


# ---------------------------------------------------------------- replay

def public_repos(root):
    out = []
    for g in sorted(glob.glob(os.path.join(root, "*", ".git"))):
        r = os.path.dirname(g)
        if os.path.isfile(os.path.join(r, MARKER)):
            out.append(r)
    return out


SESSION_TRAILER = re.compile(r"^(?:Agent|Claude)-Session:\s*(?:claude:)?([0-9a-f]{8}-[0-9a-f-]{27,})\s*$", re.M)


def cmd_replay(root, since, show):
    per_repo = Counter()
    per_rule = Counter()
    hit_commits = Counter()
    lines_shown = []
    no_tx = 0
    for repo in public_repos(root):
        log = git(repo, "log", "--all", "--no-merges", f"--since={since}" if since else "--since=2000-01-01",
                  "--format=%H%x00%ct%x00%B%x1e")
        by_session = defaultdict(list)
        for rec in log.split("\x1e"):
            rec = rec.strip("\n")
            if not rec:
                continue
            sha, ct, body = rec.split("\x00", 2)
            m = SESSION_TRAILER.search(body)
            if m:
                by_session[m.group(1)].append((int(ct), sha))
        name = os.path.basename(repo)
        for sid, commits in by_session.items():
            tx = find_transcript(sid)
            if not tx:
                no_tx += len(commits)
                continue
            evs = list(events(tx))
            for ct, sha in sorted(commits):
                tt = Taint()
                for ts, kind, text in evs:
                    if ts is not None and ts > ct:
                        break
                    tt.feed(kind, text)
                per_repo[name] += 1
                hits = check_lines(added_lines(git(repo, "show", "--format=", "-U0", "--no-color", "--no-ext-diff", sha)),
                                   tt.tainted, committed_tokens(repo, sha + "^"))
                if hits:
                    hit_commits[name] += 1
                    for _p, _n, h in hits:
                        per_rule.update(h)
                    if show:
                        for p, n, h in hits[:5]:
                            body = git(repo, "show", f"{sha}:{p}").splitlines()
                            txt = body[n - 1][:160] if 0 < n <= len(body) else ""
                            lines_shown.append(f"  {name} {sha[:8]} {p}:{n} [{', '.join(h)}] {txt}")
    total = sum(per_repo.values())
    print(f"replay: 公開 repo の commit で会話記録を引けたもの {total} (引けないもの {no_tx})、 当たった commit {sum(hit_commits.values())}")
    for name in sorted(per_repo):
        print(f"  {name}: {per_repo[name]} commit / 当たり {hit_commits[name]}")
    print("  規則ごとの当たり行: " + (", ".join(f"{k} {v}" for k, v in sorted(per_rule.items())) or "なし"))
    for s in lines_shown:
        print(s)
    return 0


# ---------------------------------------------------------------- selftest

def selftest():
    fails = []

    def check(label, ok, extra=""):
        print(("  ok: " if ok else "  NG: ") + label + (f" ({extra})" if extra and not ok else ""))
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        td = os.path.realpath(td)
        pub, prv = os.path.join(td, "pubrepo"), os.path.join(td, "privrepo")
        for r in (pub, prv):
            subprocess.run(["git", "init", "-q", r], check=True)
        os.makedirs(os.path.join(pub, ".claude"))
        open(os.path.join(pub, MARKER), "w").close()
        check("場所: 公開の印のある repo の中 = 公開", is_public_path(os.path.join(pub, "a.py")) is True)
        check("場所: 印の無い repo = 非公開", is_public_path(os.path.join(prv, "a.md")) is False)
        check("場所: repo の外 = 非公開", is_public_path(td) is False)
        check("場所: system の path は見ない", is_public_path("/usr/bin/python3") is None)
        check("tool: 公開 repo だけを読む Bash = 公開", source_is_private("Bash", {"command": f"grep -n x {pub}/a.py"}, td) is False)
        check("tool: 非公開 repo を混ぜた Bash = 非公開",
              source_is_private("Bash", {"command": f"grep x {pub}/a.py {prv}/b.md"}, td) is True)
        check("tool: 場所の分からない MCP = 非公開", source_is_private("mcp__gmail__read", {"id": "x"}, td) is True)
        check("tool: Edit の確認は見ない", source_is_private("Edit", {"file_path": f"{pub}/a.py"}, td) is None)
        check("tool: Web は公開", source_is_private("WebFetch", {"url": "https://example.org"}, td) is False)
        # 会話記録の模型
        tx = os.path.join(td, "s.jsonl")
        T0 = "2026-01-01T00:00:0{}Z"
        recs = [
            {"type": "assistant", "timestamp": T0.format(1), "cwd": td, "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash", "input": {"command": f"git -C {prv} log"}}]}},
            {"type": "user", "timestamp": T0.format(2), "cwd": td, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u1", "content":
                    "記録: 謝礼 7,350 と 2,950 / 47 XYZ widgets / QQA|QQB|QQC|QQD|QQE / 見通し 3,141,592 / 812,903 行"}]}},
            {"type": "assistant", "timestamp": T0.format(3), "cwd": td, "message": {"content": [
                {"type": "text", "text": "合成の例 6,789 / 4,321 を使う"}]}},
            {"type": "assistant", "timestamp": T0.format(4), "cwd": td, "message": {"content": [
                {"type": "tool_use", "id": "u2", "name": "Bash", "input": {"command": f"cat {pub}/a.py"}}]}},
            {"type": "user", "timestamp": T0.format(5), "cwd": td, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u2", "content": "公開の値 1,111 と 2,222"}]}},
            {"type": "assistant", "timestamp": T0.format(6), "cwd": td, "message": {"content": [
                {"type": "tool_use", "id": "u3", "name": "Bash", "input": {"command": f"grep 6,789 {prv}/b.md"}}]}},
            {"type": "user", "timestamp": T0.format(7), "cwd": td, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u3", "content": "6,789 / 4,321 (後から非公開の file に出た)"}]}},
        ]
        with open(tx, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tainted = taint_of(tx)
        H = lambda s: line_hits(s, tainted)  # noqa: E731
        check("pair: 非公開の出力から来た数 2 つの行は止める", "pair" in H('"謝礼額: 7,350 / 2,950"'))
        check("pair: 1 つだけなら止めない (短い数の誤検出を避ける)", not H("謝礼 7,350 の例"))
        check("long: 7 桁以上の 3 桁区切りの数 1 つで止める", "long" in H("見通し 3,141,592 の例"))
        check("pair / long: 件数の単位が続く数は数えない", not H("走査した 812,903 行と 7,350 件"))
        check("money: 数とコードの組で止める", "money" in H("# 「47 XYZ widgets」 = 件数"))
        check("money: 数を変えた組は止めない", not H("# 「42 XYZ widgets」 = 件数"))
        check("money: 日付の断片 + 大文字の語 (2026-06-06 RCA) は組にしない", not money_tokens("2026-06-06 RCA と RFC 5322"))
        check("pair: CSS の色の数の並び (rgba(255,255,255,.5)) は 3 桁区切りに数えない",
              not comma_amounts("--x: rgba(255,255,255,.05); --y: rgb(84,114,228)"))
        check("codes: コード 4 つの並びで止める", "codes" in H('C = r"AAA|QQB|QQC|QQD|QQE"'))
        check("codes: 3 つまでは止めない", not H('C = r"QQA|QQB|QQC|ZZZ"'))
        check("自作: agent が先に書いた合成の値は、 後で非公開の出力に出ても止めない", not H('"謝礼額: 6,789 / 4,321"'))
        check("公開の出力だけから来た値は止めない", not H("1,111 と 2,222"))
        check("年 (1900–2099) は数に数えない", not num_tokens("2026 年と 1999 年"))
        check("合成の例の形 (連番・同じ数字) は数に数えない", not num_tokens("1,234,567 と 7654321 と 1,111 と 99999"))
        check("codes: 主要通貨だけの並びは数えない", not code_tokens("USD|EUR|JPY|GBP|AUD"))
        tainted_early = taint_of(tx, until=_ts(T0.format(1)))
        check("replay: commit の時刻より後の記録は数えない", not line_hits('"7,350 / 2,950"', tainted_early))
        # staged の gate
        a = os.path.join(pub, "a.py")
        open(a, "w").write('X = ["謝礼額: 7,350 / 2,950"]\nY = "6,789 / 4,321"\n')
        subprocess.run(["git", "-C", pub, "add", "a.py"], check=True)
        env0 = dict(os.environ)
        try:
            os.environ.pop("CLAUDE_CARRYOVER_GUARD", None)
            rc = cmd_staged(pub, tx)
            check("staged: 写した値の行で BLOCK (exit 1)", rc == 1)
            os.environ["CLAUDE_CARRYOVER_GUARD"] = "0"
            check("staged: CLAUDE_CARRYOVER_GUARD=0 で 1 回だけ通す", cmd_staged(pub, tx) == 0)
            os.environ.pop("CLAUDE_CARRYOVER_GUARD", None)
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            check("staged: 会話記録が無ければ走らなかった印 (3)", cmd_staged(pub, None) == 3)
            # 既に commit した file にある値 (2026-11-09): 同じ値の行の言い直し・別の行への移しは止めない、 無い値は止める
            subprocess.run(["git", "-C", pub, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "commit", "-q", "-m", "a"], check=True, env=dict(os.environ, CLAUDE_CARRYOVER_GUARD="0"))
            open(a, "w").write('Y = "6,789 / 4,321"\nZ = "謝礼の額は 7,350 と 2,950 (言い直した)"\n')
            subprocess.run(["git", "-C", pub, "add", "a.py"], check=True)
            check("staged: commit 済みの file にある値の行を言い直し・移しても止めない", cmd_staged(pub, tx) == 0)
            b = os.path.join(pub, "b.py")
            open(b, "w").write('W = "7,350 / 2,950"\n')
            subprocess.run(["git", "-C", pub, "add", "b.py"], check=True)
            check("staged: 別の file に写した値は止める (その file の commit 済みの版に無い)", cmd_staged(pub, tx) == 1)
        finally:
            os.environ.clear()
            os.environ.update(env0)
        check("diff の追加行: 行番号を数える",
              added_lines("+++ b/x.py\n@@ -0,0 +3,2 @@\n+a\n+b\n") == [("x.py", 3, "a"), ("x.py", 4, "b")])
    print(f"selftest: {'FAILED ' + str(len(fails)) if fails else 'ALL PASS'}")
    return 1 if fails else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--transcript")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--root", default=os.path.expanduser("~/Claude"))
    ap.add_argument("--since")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.replay:
        return cmd_replay(a.root, a.since, a.show)
    if a.staged:
        return cmd_staged(os.path.abspath(a.repo), a.transcript)
    ap.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001  故障は 3 (違反の 1 と分ける)
        print(f"check-session-carryover: 検査の中の故障 = 走らなかった ({type(e).__name__}: {e})", file=sys.stderr)
        sys.exit(3)
