#!/usr/bin/env python3
"""constraint-at-use.py — 制約表 (markdown table) の行を、 その道具・file を使う瞬間の PreToolUse hook で session に 1 回だけ出す (auto-load 面から降ろした制約の point-of-use 配達)

層1 engine (2026-10-04)。 「触る前に効く制約」 の表 (1 列目 = 対象の道具・台帳の名、 2 列目 = 制約) を毎 session
auto-load される CLAUDE.md に置くと、 道具ごとに 1 行足す構造ゆえ際限なく育ち、 memory file の予算に張り付く
(RCA = 利用者の層の plan、 実測で 33 KB / 54 行)。 本 engine は表を auto-load されない file へ降ろす代わりに、
**道具を Bash で叩く瞬間・台帳 file を開く瞬間に、 該当する行だけを additionalContext で 1 回出す**。 読む側が
100 KB 手前の preamble から思い出すのでなく、 tool 結果の直前にその行が居る。

key の導出 (= 対応表を別に持たない、 convention-design-principles.md#detector-config-must-be-derived):
  1 列目の token のうち ① backtick の中 ② 5 字以上で `-` `_` `.` `/` のどれかを含む (= script / file 名の形) を key に
  する。 ② は括弧 (半角・全角) の外だけ = 括弧の中の説明語 (台帳の置き場の repo 名など) は key にしない (実測: repo 名を
  含むだけの command に行が出た)。 括弧の中でも key にしたい名前は backtick で囲む。 `<id>` 等の placeholder は「/ と空白以外の任意」、 `{a,b}` は選択肢に展開。 key は Bash の command と
  file 系 tool (Edit / Write / MultiEdit / Read / NotebookEdit) の path に対して substring (regex) で当てる。
  英数字で始まる導いた key は、 左に語の境目を要る (直前が英数字・`_` でないか文頭 = LEFT_BOUNDARY)。 実測:
  key が別の file 名の途中で当たり、 無関係な command に行が出た (合成例 = key `log-export` が `catalog-export.md` の中)。
  `-` の後は当てる = 道具を包む・入れる file (`session-start-<key>.sh` / `install-<key>.sh`) にも出す (実測: `-` まで
  境目にすると、 本体が `hooks/session-start-<道具>.sh` の形の道具の行が、 その本体に出なくなった)。
  `.` `/` placeholder で始まる key と overlay の regex (下の :: / :=) は書いたとおりに当てる (境目が要るなら regex に書く)。
  表示 (`--check`) は導いた key のまま、 照合だけ境目つき (row の "match")。
  1 列目から key が導けない行 (「Remote Control の auth」 等) は、 表の file の HTML comment で足す:
      <!-- constraint-keys
      - <1 列目の頭 (prefix)> :: <regex>      ← 導いた key に足す
      - <1 列目の頭 (prefix)> := <regex>      ← 導いた key を置き換える (1 列目の説明の語が key になって
                                                 関係ない command に出る行を絞る。 例 = 「X / 層1 pre-commit の gate」)
      -->
  (= 同じ file の中、 描画されない、 規則の文は触らない)。 `--check` が key の無い行を列挙して exit 1 で止める
  (= 足した行が黙って「出ない行」 にならない)。

出し方: 1 回の tool call で最大 --max 行 (既定 2)、 同じ行は 1 session に 1 回 (state = <state-dir>/<session_id>、
machine-local)。 該当する行が --max を超えたら、 出さなかった行の頭を末尾に 1 行で並べ (黙って落とさない)、 それらは
出したことにしない (= 次に触る時に全文が出る)。 `--check` は複数の行が同じ key を持つものも並べる (= 1 回の command で
一緒に出る組。 同じ道具の別の面なら正しい、 説明の語なら := で絞る)。
出力は PreToolUse の additionalContext (止めない。 deny は別の guard の仕事)。 全 error path で fail-open (無言 exit 0)。
自分 (engine 名) を含む command には出さない (表の file 名は除外しない = 表を開く瞬間に行の足し方の行が出るのは望む挙動)。
Bash の command のうち、 道具を使っていない文字列は照合から外す: 掲示板 (board.py) の自由文の値 (--summary・
--acceptance・--session-name・--title・--reason ほか) と、 grep 系 (grep / rg / ugrep / ag / ack / git grep) の
検索語。 検索先の path と、 叩いている道具の名は外さない (= その file を読む瞬間には出る)。 実測: 発火の約 1/3 が
「文字列に含むだけ」 で、 その主な形がこの 2 つだった。 quote が閉じない行 (heredoc の本文など) は外さずに当てる。

usage:
  constraint-at-use.py --table T.md [--table U.md]... [--state-dir DIR] [--max N]      # hook (stdin = PreToolUse JSON)
  constraint-at-use.py --table T.md --probe '<command or path>' [--tool Bash]           # どの行が出るか (state は書かない)
  constraint-at-use.py --table T.md --check                                            # 行と key の一覧、 key 無しの行があれば exit 1
  constraint-at-use.py --selftest

public-safe / stdlib only。 表の path・state の場所は呼び手 (利用者の shim) が渡す。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

FILE_TOOLS = ("Edit", "Write", "MultiEdit", "Read", "NotebookEdit")
TOK_RE = re.compile(r"`([^`]+)`|([A-Za-z][A-Za-z0-9_.\-/<>{},]*[A-Za-z0-9>}])")
KEY_BLOCK_RE = re.compile(r"<!--\s*constraint-keys\s*\n(.*?)-->", re.S)
DEFAULT_STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "state", "constraint-at-use")
# 道具を使っていない文字列 (Bash の command の中)
FREE_TEXT_FLAGS = {"--summary", "--acceptance", "--session-name", "--title", "--reason", "--headless-reason",
                   "--effort-quote", "--model-quote"}
SEARCH_TOOLS = {"grep", "egrep", "fgrep", "rg", "ugrep", "ag", "ack"}
SEARCH_ARG_OPTS = {"-A", "-B", "-C", "-m", "-d", "-D", "-g", "-t", "-T", "-M", "-j", "--include", "--exclude",
                   "--exclude-dir", "--glob", "--type", "--max-count", "--context", "--after-context",
                   "--before-context"}
SEPARATORS = {";", "|", "||", "&", "&&", "(", ")"}
# 導いた key の左の語の境目 = 直前が英数字・`_` でない (文頭を含む)。 `-` `.` `/` 空白の後は当たる
LEFT_BOUNDARY = r"(?<![A-Za-z0-9_])"
HEADER = "⚠️ 触る前に効く制約 (この session で初めて触る道具の行。 正本 = {table})"


def _expand_braces(tok: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", tok)
    if not m:
        return [tok]
    out = []
    for alt in m.group(1).split(","):
        out.extend(_expand_braces(tok[: m.start()] + alt.strip() + tok[m.end():]))
    return out


def token_to_regex(tok: str) -> str:
    parts = re.split(r"(<[^>]*>)", tok)
    return "".join(r"[^/\s]*" if p.startswith("<") else re.escape(p) for p in parts if p)


def _paren_depths(head: str) -> list[int]:
    """各文字位置の括弧の深さ (半角 () と全角 （）)。 backtick の中の括弧は数えない。"""
    depths, depth, in_tick = [], 0, False
    for ch in head:
        if ch == "`":
            in_tick = not in_tick
        elif not in_tick and ch in "(（":
            depth += 1
        depths.append(depth)
        if not in_tick and ch in ")）" and depth > 0:
            depth -= 1
    return depths


def derive_keys(head: str) -> list[str]:
    keys = []
    depths = _paren_depths(head)
    for m in TOK_RE.finditer(head):
        tok = (m.group(1) or m.group(2) or "").strip()
        if not tok:
            continue
        if m.group(2) and not (len(tok) >= 5 and re.search(r"[-_./]", tok)):
            continue
        if m.group(2) and depths[m.start()] > 0:
            continue  # 括弧の中の bare token = 説明語。 key にしたいなら backtick で囲む
        for t in _expand_braces(tok):
            r = token_to_regex(t)
            if r and r not in keys:
                keys.append(r)
    return keys


def load_table(path: Path) -> list[dict]:
    """[{id, head, line, keys, table}] — 最初の markdown table の行 (header と区切りを除く)。 overlay の key を足す。"""
    text = path.read_text(encoding="utf-8")
    rows = []
    in_table = False
    for line in text.split("\n"):
        if line.startswith("|"):
            if re.match(r"^\|[-\s|:]+\|?\s*$", line):
                in_table = True  # 区切り行 = ここまでが header
                continue
            if not in_table:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            if len(cells) < 2:
                continue
            head = cells[0]
            keys = derive_keys(head)
            rows.append({"id": hashlib.sha1(head.encode("utf-8")).hexdigest()[:12], "head": head, "line": line,
                         "keys": keys, "derived": set(keys), "table": str(path)})
        elif in_table and rows and line.strip() == "":
            break  # 表の終わり
    for blk in KEY_BLOCK_RE.findall(text):
        for l in blk.split("\n"):
            l = l.strip()
            if not l.startswith("- ") or (" :: " not in l and " := " not in l):
                continue
            replace = " := " in l and (" :: " not in l or l.index(" := ") < l.index(" :: "))
            prefix, rx = l[2:].split(" := " if replace else " :: ", 1)
            hits = [r for r in rows if r["head"].startswith(prefix.strip())]
            if len(hits) != 1 or not rx.strip():
                continue
            if replace:
                hits[0]["keys"] = [rx.strip()]
                hits[0]["derived"] = set()
            elif rx.strip() not in hits[0]["keys"]:
                hits[0]["keys"].append(rx.strip())
    for r in rows:
        r["match"] = [match_regex(k) if k in r["derived"] else k for k in r["keys"]]
    return rows


def match_regex(key: str) -> str:
    """導いた key の照合用の regex: 英数字で始まる key は左に語の境目を要る。"""
    return LEFT_BOUNDARY + key if key[:1].isascii() and key[:1].isalnum() else key


def _command_word(tokens: list[str]) -> tuple[str, int]:
    """segment の command の語と、 その位置 (env の代入・sudo・command・git の前置きを飛ばす)。"""
    i = 0
    while i < len(tokens) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]) or tokens[i] in ("sudo", "command", "env")):
        i += 1
    if i < len(tokens) - 1 and tokens[i] == "git" and tokens[i + 1] == "grep":
        i += 1
    return (tokens[i].rsplit("/", 1)[-1] if i < len(tokens) else ""), i


def _drop_search_terms(tokens: list[str], start: int) -> list[str]:
    out, pattern_seen, skip_next, i = tokens[:start + 1], False, False, start + 1
    while i < len(tokens):
        t = tokens[i]
        if t in ("-e", "--regexp"):
            pattern_seen, i = True, i + 2
            continue
        if t.startswith("--regexp=") or (t.startswith("-e") and not t.startswith("--") and len(t) > 2):
            pattern_seen, i = True, i + 1
            continue
        if t in SEARCH_ARG_OPTS or t == "-f":
            out.extend(tokens[i:i + 2])
            i += 2
            continue
        if t.startswith("-"):
            out.append(t)
        elif not pattern_seen:
            pattern_seen = True  # 最初の位置引数 = 検索語
        else:
            out.append(t)
        i += 1
    return out


def _drop_free_text(tokens: list[str]) -> list[str]:
    out, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if t in FREE_TEXT_FLAGS:
            i += 2
            continue
        if t.split("=", 1)[0] in FREE_TEXT_FLAGS and "=" in t:
            i += 1
            continue
        out.append(t)
        i += 1
    return out


def strip_unused_text(command: str) -> str:
    """道具を使っていない文字列 (掲示板の自由文の値・grep 系の検索語) を除いた command。 行ごとに shlex で
    分け、 分けられない行 (quote が閉じない = heredoc の本文など) は元のまま残す (= 今までどおり当てる)。"""
    kept = []
    for line in command.splitlines():
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            tokens = list(lex)
        except ValueError:
            kept.append(line)
            continue
        seg: list[str] = []
        for t in tokens + [";"]:
            if t in SEPARATORS:
                if seg:
                    word, pos = _command_word(seg)
                    if word in SEARCH_TOOLS or (word == "grep" and pos > 0 and seg[pos - 1] == "git"):
                        seg = _drop_search_terms(seg, pos)
                    if any(x.endswith("board.py") for x in seg):
                        seg = _drop_free_text(seg)
                    kept.append(" ".join(seg))
                seg = []
            else:
                seg.append(t)
    return "\n".join(kept)


def haystack(tool_name: str, tool_input: dict) -> str | None:
    if tool_name == "Bash":
        return strip_unused_text(str(tool_input.get("command", "")))
    if tool_name in FILE_TOOLS:
        return str(tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or "")
    return None


def match_rows(rows: list[dict], text: str) -> list[dict]:
    out = []
    for r in rows:
        for k in r.get("match", r["keys"]):
            try:
                if re.search(k, text):
                    out.append(r)
                    break
            except re.error:
                continue
    return out


def _state_path(state_dir: str, session_id: str) -> Path:
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "nosession")[:80]
    return Path(state_dir) / sid


def _seen(state_dir: str, session_id: str) -> set[str]:
    p = _state_path(state_dir, session_id)
    try:
        return set(p.read_text(encoding="utf-8").split())
    except OSError:
        return set()


def _mark(state_dir: str, session_id: str, ids: list[str]) -> None:
    p = _state_path(state_dir, session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("".join(i + "\n" for i in ids))


def self_mention(text: str, tables: list[Path]) -> bool:
    """engine 自身を叩く command (--probe / --check / selftest) には出さない。 表の file 名は除外しない
    (= 表を開く・grep する瞬間に「行の足し方」 の行が 1 回出るのは望む挙動)。"""
    return Path(__file__).name in text


def render(rows: list[dict], table_names: str, rest: list[dict] | None = None) -> str:
    body = "\n".join(r["line"] for r in rows)
    more = ""
    if rest:
        more = ("\nほかにも該当する行: " + " / ".join(r["head"][:40] for r in rest)
                + " (次に触る時に出る。 今すぐ読むなら表を grep)")
    return (HEADER.format(table=table_names) + "\n" + body + more
            + "\n(同じ行は 1 session に 1 回だけ出る。 表の他の行は道具の名で grep)")


def hook_main(tables: list[Path], state_dir: str, max_rows: int) -> int:
    try:
        ev = json.loads(sys.stdin.read() or "{}")
        if ev.get("hook_event_name", "PreToolUse") != "PreToolUse":
            return 0
        text = haystack(ev.get("tool_name", ""), ev.get("tool_input") or {})
        if not text or self_mention(text, tables):
            return 0
        rows = []
        for t in tables:
            if t.is_file():
                rows.extend(load_table(t))
        hits = match_rows(rows, text)
        if not hits:
            return 0
        sid = str(ev.get("session_id") or "")
        seen = _seen(state_dir, sid)
        unseen = [r for r in hits if r["id"] not in seen]
        fresh, rest = unseen[:max_rows], unseen[max_rows:]
        if not fresh:
            return 0
        _mark(state_dir, sid, [r["id"] for r in fresh])
        names = " / ".join(sorted({Path(r["table"]).name for r in fresh}))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": render(fresh, names, rest)}}, ensure_ascii=False))
        return 0
    except Exception:  # noqa: BLE001  fail-open: hook の故障で tool call を止めない
        return 0


def check_main(tables: list[Path]) -> int:
    bad = 0
    for t in tables:
        rows = load_table(t)
        print(f"{t}: {len(rows)} 行")
        for r in rows:
            mark = "∅" if not r["keys"] else " "
            bad += not r["keys"]
            print(f"  {mark} {r['head'][:48]!r:52} -> {r['keys'][:4]}{' …' if len(r['keys']) > 4 else ''}")
        shared: dict[str, list[str]] = {}
        for r in rows:
            for k in r["keys"]:
                shared.setdefault(k, []).append(r["head"][:32])
        shared = {k: v for k, v in shared.items() if len(v) > 1}
        if shared:
            print("複数の行が同じ key を持つ (= 1 回の command で一緒に出る。 説明の語なら := で絞る):")
            for k, v in shared.items():
                print(f"    {k} -> {v}")
    if bad:
        print(f"key の無い行 = {bad} (出ない行 = 表の末尾の <!-- constraint-keys --> に「- <1 列目の頭> :: <regex>」 を足す)")
    return 1 if bad else 0


def selftest() -> int:
    import shutil
    import subprocess
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="cau-selftest-"))
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and cond

    try:
        tbl = tmp / "constraints.md"
        tbl.write_text("# t\n\n| 対象 | 制約 |\n|---|---|\n"
                       "| drive-xlsx-set-cells | **他人の file は OK 経由** |\n"
                       "| todo_ledger (台帳 = `todo/<id>.yaml`、 実体は `lib/{todo_ledger,recorded_ids}.py`) | **loader 経由で読む** |\n"
                       "| Remote Control の auth | **auth_error で断定しない** |\n"
                       "| calendar.sh / calendar-events.py | **add は dry-run** |\n"
                       "| foo-tool (台帳 = some-repo / other-repo の `data/<id>.yaml`、 旧名 old-name.py) | **台帳は道具で書く** |\n"
                       "| bar-tool （全角 = third-repo の中） | **全角の括弧も同じ** |\n"
                       "| baz-check / 層1 pre-hook の gate | **形を守る** |\n"
                       "| log-tool / log-export (書き出しの dir) | **左の境目** |\n"
                       "| `.collab-x.conf` | **点で始まる key** |\n"
                       "\n後文\n\n<!-- constraint-keys\n- Remote Control の auth :: claude auth status|remote-control\n- baz-check := baz-check|baz-guard\n-->\n",
                       encoding="utf-8")
        rows = load_table(tbl)
        check(len(rows) == 9, "table: header / 区切りを除く 9 行を読む")
        k = {r["head"][:12]: r["keys"] for r in rows}
        check(k["drive-xlsx-s"] == ["drive\\-xlsx\\-set\\-cells"], "key: script 名 (- を含む bare token)")
        check(any("todo/[^/\\s]*\\.yaml" == x for x in k["todo_ledger "]), "key: `<id>` placeholder → [^/\\s]*")
        check("lib/todo_ledger\\.py" in k["todo_ledger "] and "lib/recorded_ids\\.py" in k["todo_ledger "], "key: {a,b} を展開")
        check(k["Remote Contr"] == ["claude auth status|remote-control"], "key: 導けない行は overlay から")
        check(k["calendar.sh "] == ["calendar\\.sh", "calendar\\-events\\.py"], "key: `.sh` / `.py` の 2 つ")
        check(k["foo-tool (台帳"] == ["foo\\-tool", "data/[^/\\s]*\\.yaml"], "key: 括弧の中は backtick だけ (bare の repo 名・旧名は key にしない)")
        check(k["bar-tool （全角"] == ["bar\\-tool"], "key: 全角の括弧の中の bare token も key にしない")
        check(not match_rows(rows, "grep -rn foo some-repo/notes.md"), "match: 括弧の中の説明語 (repo 名) だけを含む command には出ない")
        check(k["baz-check / "] == ["baz-check|baz-guard"], "key: := は導いた key を置き換える")
        check(not match_rows(rows, "bash x/pre-hook-scan.sh") and match_rows(rows, "bash baz-guard.sh"),
              "match: := で絞った行は説明の語 (pre-hook) に出ず、 置き換えた key には出る")
        line_hit = lambda c: [r for r in match_rows(rows, haystack("Bash", {"command": c}))  # noqa: E731
                              if r["head"].startswith("log-tool")]
        check(not line_hit("sed -n '1,5p' notes/catalog-export.md"),
              "boundary: key が長い語の途中に当たっても出ない (cata|log-export)")
        check(not line_hit("cat x/count_log-tool.py") and not line_hit("cat x/blog-tool.py"),
              "boundary: 直前が英字や `_` なら別の語 (blog-tool / count_log-tool)")
        check(line_hit("python3 scripts/log-tool.py --surface") and line_hit("cat repo/log-export/a.md")
              and line_hit("log-tool --x") and line_hit("cat hooks/session-start-log-tool.sh"),
              "boundary: 空白・`/`・文頭・`-` の後なら出る (道具を包む file)")
        k9 = {r["head"][:12]: r for r in rows}
        check(k9["drive-xlsx-s"]["match"][0].startswith("(?<!") and k9["drive-xlsx-s"]["keys"] == ["drive\\-xlsx\\-set\\-cells"],
              "boundary: 境目は照合用の regex だけに付け、 表示の key は変えない")
        check(match_rows(rows, "repo/.collab-x.conf") and match_rows(rows, "cat a.collab-x.conf"),
              "boundary: 点で始まる key には境目を付けない")
        check(k9["Remote Contr"]["match"] == ["claude auth status|remote-control"]
              and k9["baz-check / "]["match"] == ["baz-check|baz-guard"],
              "boundary: overlay の regex (:: / :=) は書いたとおりに当てる")
        hits = match_rows(rows, "python3 scripts/drive-xlsx-set-cells.py --inspect x.xlsx")
        check([r["head"][:5] for r in hits] == ["drive"], "match: Bash command に script 名")
        hits = match_rows(rows, "repo/todo/2026-10-01-foo.yaml")
        check(len(hits) == 1 and hits[0]["head"].startswith("todo_ledger"), "match: Edit の path に todo/<id>.yaml")
        check(match_rows(rows, "claude auth status") and not match_rows(rows, "git status"), "match: overlay の regex、 無関係な command は 0")
        hs = lambda c: haystack("Bash", {"command": c})  # noqa: E731
        check(not match_rows(rows, hs("python3 board/board.py claim --summary 'drive-xlsx-set-cells の件を引き受けた' --session x")),
              "strip: 掲示板の --summary の自由文に道具の名があっても出ない")
        check(not match_rows(rows, hs("python3 board.py note --acceptance='calendar.sh を直す'")),
              "strip: --flag=値 の形の自由文も外す")
        check(match_rows(rows, hs("python3 board.py submit --deliverable scripts/drive-xlsx-set-cells.py")),
              "strip: 掲示板の path の引数 (--deliverable) は外さない")
        check(not match_rows(rows, hs("grep -rn drive-xlsx-set-cells notes/ | head")),
              "strip: grep の検索語に道具の名があっても出ない")
        check(not match_rows(rows, hs("cd x && command grep -n -A 3 -e calendar.sh docs")),
              "strip: -e の検索語と、 引数を取る option (-A 3) の後の検索先を見分ける")
        check(match_rows(rows, hs("grep -n foo scripts/drive-xlsx-set-cells.py")),
              "strip: grep の検索先の file は外さない (= その file を読む瞬間には出る)")
        check(not match_rows(rows, hs("git grep -n calendar.sh")) and match_rows(rows, hs("python3 x/calendar.sh add")),
              "strip: git grep の検索語も外す / 道具を叩く command には今までどおり出る")
        check(match_rows(rows, hs("cat <<EOF\nrun drive-xlsx-set-cells 'now\nEOF")),
              "strip: quote が閉じない行は外さずに当てる (fail-safe = 今までの挙動)")
        # hook: 新しい process で stdin JSON → additionalContext JSON、 2 回目は無言 (state)
        st = tmp / "state"
        ev = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Bash",
              "tool_input": {"command": "python3 scripts/drive-xlsx-set-cells.py --inspect x.xlsx"}}

        def run(e, *extra):
            return subprocess.run([sys.executable, __file__, "--table", str(tbl), "--state-dir", str(st), *extra],
                                  input=json.dumps(e), capture_output=True, text=True)

        r = run(ev)
        check(r.returncode == 0 and '"additionalContext"' in r.stdout and "他人の file は OK 経由" in r.stdout
              and "PreToolUse" in r.stdout, "hook: 初回は additionalContext に行を出す")
        r = run(ev)
        check(r.returncode == 0 and r.stdout.strip() == "", "hook: 同じ session の 2 回目は無言")
        r = run(dict(ev, session_id="s2"))
        check('"additionalContext"' in r.stdout, "hook: 別の session では再び出る")
        r = run({"hook_event_name": "PreToolUse", "session_id": "s3", "tool_name": "Edit",
                 "tool_input": {"file_path": "repo/todo/2026-10-01-foo.yaml"}})
        check("loader 経由で読む" in r.stdout, "hook: Edit の file_path でも出る")
        r = run({"hook_event_name": "PreToolUse", "session_id": "s4", "tool_name": "Bash",
                 "tool_input": {"command": "python3 constraint-at-use.py --table x.md --probe 'calendar.sh add'"}})
        check(r.stdout.strip() == "", "hook: engine 自身を叩く command (--probe 等) には出さない")
        r = run({"hook_event_name": "PreToolUse", "session_id": "s5", "tool_name": "Bash",
                 "tool_input": {"command": "python3 x/calendar.sh add && python3 drive-xlsx-set-cells.py && vi todo/a.yaml"}},
                "--max", "2")
        check(r.stdout.count("\n| ") + r.stdout.count("\\n| ") <= 2 and '"additionalContext"' in r.stdout, "hook: 1 回の call は --max 行まで")
        check("ほかにも該当する行" in r.stdout, "hook: --max を超えた行は頭を末尾に並べる (黙って落とさない)")
        r = run({"hook_event_name": "PreToolUse", "session_id": "s5", "tool_name": "Bash",
                 "tool_input": {"command": "python3 x/calendar.sh add && python3 drive-xlsx-set-cells.py && vi todo/a.yaml"}},
                "--max", "2")
        check('"additionalContext"' in r.stdout and "ほかにも該当する行" not in r.stdout,
              "hook: 頭だけ並べた行は出したことにしない (次の call で全文が出る)")
        r = run({"hook_event_name": "PostToolUse", "session_id": "s6", "tool_name": "Bash",
                 "tool_input": {"command": "calendar.sh"}})
        check(r.stdout.strip() == "", "hook: PreToolUse 以外の event は無言")
        r = subprocess.run([sys.executable, __file__, "--table", str(tbl), "--state-dir", str(st)], input="not json",
                           capture_output=True, text=True)
        check(r.returncode == 0 and r.stdout.strip() == "", "hook: 壊れた stdin は fail-open (無言 exit 0)")
        r = subprocess.run([sys.executable, __file__, "--table", str(tmp / "missing.md"), "--state-dir", str(st)],
                           input=json.dumps(ev), capture_output=True, text=True)
        check(r.returncode == 0 and r.stdout.strip() == "", "hook: 表が無ければ fail-open")
        # --probe / --check
        r = subprocess.run([sys.executable, __file__, "--table", str(tbl), "--probe", "calendar.sh add"], capture_output=True, text=True)
        check(r.returncode == 0 and "calendar.sh" in r.stdout, "--probe: 出る行を表示")
        r = subprocess.run([sys.executable, __file__, "--table", str(tbl), "--check"], capture_output=True, text=True)
        check(r.returncode == 0 and "9 行" in r.stdout, "--check: 全行に key があれば rc 0")
        t2 = tmp / "shared.md"
        t2.write_text("| 対象 | 制約 |\n|---|---|\n| foo-bar / a.py | x |\n| foo-bar / b.py | y |\n", encoding="utf-8")
        r = subprocess.run([sys.executable, __file__, "--table", str(t2), "--check"], capture_output=True, text=True)
        check(r.returncode == 0 and "同じ key を持つ" in r.stdout and "foo" in r.stdout,
              "--check: 複数の行が同じ key を持てば並べる (rc は 0 のまま)")
        tbl.write_text(tbl.read_text(encoding="utf-8").replace("| Remote Control の auth |", "| 承認の CLI |"), encoding="utf-8")
        r = subprocess.run([sys.executable, __file__, "--table", str(tbl), "--check"], capture_output=True, text=True)
        check(r.returncode == 1 and "key の無い行 = 1" in r.stdout, "--check: key の無い行があれば rc 1 + 行を列挙")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if args == ["--selftest"]:
        return selftest()
    tables, state_dir, max_rows, probe, tool, check = [], DEFAULT_STATE_DIR, 2, None, "Bash", False
    it = iter(args)
    for tok in it:
        if tok == "--table":
            tables.append(Path(next(it, "")))
        elif tok == "--state-dir":
            state_dir = next(it, state_dir)
        elif tok == "--max":
            max_rows = int(next(it, "2"))
        elif tok == "--probe":
            probe = next(it, "")
        elif tok == "--tool":
            tool = next(it, "Bash")
        elif tok == "--check":
            check = True
        else:
            print(__doc__.split("usage:", 1)[-1])
            return 64
    if not tables:
        print("--table が要る")
        return 64
    if check:
        return check_main([t for t in tables if t.is_file()])
    if probe is not None:
        rows = []
        for t in tables:
            if t.is_file():
                rows.extend(load_table(t))
        text = haystack(tool, {"command": probe, "file_path": probe}) or probe  # hook と同じ除き方で当てる
        hits = match_rows(rows, text)
        print(f"{len(hits)} 行が出る (tool = {tool}):")
        for r in hits:
            print("  " + r["head"][:70])
        return 0
    return hook_main(tables, state_dir, max_rows)


if __name__ == "__main__":
    sys.exit(main())
