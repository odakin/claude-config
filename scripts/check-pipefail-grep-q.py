#!/usr/bin/env python3
"""check-pipefail-grep-q.py — pipefail の下の shell script で、 変数や file を `grep -q` に pipe で流す形 (`printf '%s' "$x" | grep -q …`) を見つける: commit gate の段 (--staged、 足した行の違反で exit 1) + fleet の棚卸し (--tree) (`grep -q` が最初の一致で読み終えると、 書き終わっていない書き手が閉じた pipe に書いて死に、 pipefail の下では一致したのに偽になる。 入力が pipe の容量 〔macOS で約 64 KB〕 を越えたときだけ起きる)。

規約 (症状・再現・直し方) = conventions/shell-env.md#pipefail-grep-q-sigpipe。
由来 (実測): 公開 repo の漏洩検査の照合器がこの形で、 commit 1 本の差分 (小さい入力) では効き、 tree 全体を 1 回で渡す
棚卸し (大きい入力) では一致を黙って落として「0 件」 と記録した。 小さい入力の試験では通るので、 commit で機械が止める。

対象の file (shell script = 拡張子 .sh .bash .zsh、 または拡張子の無い file で sh / bash / zsh の shebang) のうち:
  - その file が pipefail を立てる (`set -o pipefail` / `set -euo pipefail` のような旗の組 / zsh の `setopt pipefail`
    `setopt pipe_fail`)。 単一引用符の中 (`bash -c '...'` の文字列) と comment は数えない
  - または、 他の script から読み込まれる部品 (path の dir に `lib` を含むか、 名前が `lib` で始まる。 名前に `.test.`
    を含む file は除く) = 呼び元の pipefail の下で動く (上の由来の照合器はこの形で、 自分では pipefail を立てていなかった)
  pipefail の無い script では、 この形は正しく動くので見ない (--assume-pipefail で全部を対象にできる)。

述語 (comment・単一引用符と `$'...'` の中・二重引用符の文字・heredoc の本文は伏せてから見る。 `\\` の続き行と、 行末の
`|` の後の改行は 1 つの pipeline として読む):
  pipe (`|` か `|&`。 `||` は除く) の直後の段が `grep` (`egrep` `fgrep` `command grep` `/usr/bin/grep` も) で、 その旗に
  `-q` を含む組 (`-q` `-qE` `-Eq` `-Fqx` …。 引数を取る旗 `-e` `-f` `-m` `-A` `-B` `-C` `-d` `-D` の後ろの文字は引数として
  読む = `-eq` は pattern "q")・`--quiet`・`--silent` があるとき、 pipe の直前の段 (= 書き手) で分ける:
    BLOCK (止める) = 書き手が `printf` / `echo` / zsh の `print` で `$` を含む (変数・コマンドの置換) /
                     `cat` / `+` で始める位置か追従の `tail` (`tail -n +N` `tail -c +N` `tail -f`)
    警告 (止めない) = それ以外のコマンド (`git diff …` `sed -n …` `jq …` `ls …` など)。 出力の大きさがコマンド次第で、
                     小さい出力の行まで直させないため (2026-11-09 の方針で依頼元が決めた)
    見ない = `head …` と `+` の無い `tail` (出力に上限がある) / `$` を含まない `printf 'abc'` `echo abc` (文字だけ)
  書き手の段の始まりは、 pipe と同じ入れ子の深さの区切り (`|` `&` `;` `(` `)` `{` `}` 改行 `` ` `` `! `) か、 入れ子の
  外に出た所。 `printf "$(cmd)" | grep -q` の `$(...)` の中の括弧は区切りにしない。
  ⚠️ 取り逃し (受け入れる): `bash <<'EOF'` のように shell に食わせる heredoc の本文と `bash -c '...'` の文字列の中 /
  変数に入れた command 文字列 / 2 段以上前の書き手 (`printf "$x" | tr a b | grep -q` は直前の `tr` で分ける = 警告)。
  `case` の中の `)` を含む `$(...)` は入れ子を誤って読むことがある (報告の側にも見逃しの側にも倒れうる)。

直し方 (知らせに出す): 変数 = `grep -q … <<< "$x"` (here-string) / file = `grep -q … FILE` か `grep -q … < <(tail …)` /
  コマンド = `-q` を外して `>/dev/null` に送る (最後まで読む = 前段の失敗も今どおり拾う) か `grep -q … < <(cmd)`。
  どの形も書き手が pipeline に入らないか、 grep が最後まで読む。

面:
  --staged [--repo DIR]   commit gate。 stage した shell script を index の blob で読み (git-crypt も平文)、 全文を解析
                          したうえで、 この commit で足した行 (`git diff --cached -U0` の hunk) を含む当たりだけを出す。
                          呼び元との契約 = 「exit 1 かつ見出し `check-pipefail-grep-q: BLOCK`」 のときだけ止め、 見出しの
                          無い非 0 は 1 行出して通す。 警告だけのときは見出し `check-pipefail-grep-q: 警告` を出して exit 0。
                          呼び元 = scripts/pre-commit-bib と scripts/public-precommit-runner.sh
  --paths FILE... [--assume-pipefail]  与えた file の全文を解析して当たりを全部出す
  --tree DIR [--strict] [--assume-pipefail]  fleet の棚卸し。 DIR が git repo ならその repo、 そうでなければ直下の各 git repo の、
                          track 済みの shell script を worktree で読む。 報告だけ (exit 0)、 --strict なら BLOCK の当たりで exit 1

exit: 0 = BLOCK の当たり無し (警告はあってよい) / 1 = BLOCK の当たりあり / 3 = 検査が走っていない (git repo でない・git が
      失敗・読めない file が残った・共通部品を読めない・内部の例外。 見出しつきで 1 行出す = 呼び元は 1 + 見出し以外で止めない、
      docs/convention-design-principles.md#failure-exit-equals-violation-exit)
escape hatch: CLAUDE_PIPEFAIL_GREP_Q_GUARD=0 (--staged だけ) / git 標準の --no-verify
共通部品: shell の file の見分け・heredoc の宣言の読み方・足した行の番号・repo の列挙は check-unbraced-multibyte-var.py の
      関数 (is_shell_path / _heredoc_at / _terminates / added_line_numbers / repos_under / tracked_shell_files / _git) を
      同じ dir の file から読み込んで使う (その file を変えたら、 この file の --selftest も回す。 run-all-checks の
      check-foil-teeth が両方の mutants を回す)
selftest: python3 check-pipefail-grep-q.py --selftest (述語の陽性・陰性・警告の対照、 一時 repo での --staged の赤→緑と
      足した行だけを見ること、 実物の bash で「止める形は大きな入力で一致を落とし、 here-string と -q を外した形は当たる」)
mutants: check-pipefail-grep-q.mutants.json (check-foil-teeth.py が読む)
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

HEADING = "check-pipefail-grep-q:"
BLOCK_HEADING = HEADING + " BLOCK"
WARN_HEADING = HEADING + " 警告"
NOT_RUN = HEADING + " 検査が走っていない"
ENV_SKIP = "CLAUDE_PIPEFAIL_GREP_Q_GUARD"
DOC_ANCHOR = "conventions/shell-env.md#pipefail-grep-q-sigpipe"

_UMV = None


def umv():
    """check-unbraced-multibyte-var.py (同じ dir) を module として読む (共通部品)。"""
    global _UMV
    if _UMV is None:
        path = Path(__file__).resolve().parent / "check-unbraced-multibyte-var.py"
        spec = importlib.util.spec_from_file_location("check_unbraced_multibyte_var", str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError("共通部品を読めない: %s" % path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _UMV = mod
    return _UMV


class Hit(NamedTuple):
    line: int          # 書き手の段が始まる行 (1 起点)
    span: Tuple[int, int]  # 書き手の始まりから grep の段の終わりまでの行 (両端を含む)
    kind: str          # "var" / "file" / "cmd"
    text: str          # 元の文の該当部分 (空白を詰めた 1 行)


# ---------------------------------------------------------------- 伏せる (lexer)

WORD_BREAK = frozenset(b" \t\n;&|()<>")


def mask(data: bytes) -> Tuple[bytes, List[int]]:
    """shell の全文 → (同じ長さの伏せた byte 列, 各 byte の入れ子の深さ)。
    伏せる = comment・単一引用符と $'...' の中・二重引用符の文字 ($ だけ残す)・${...} の中・heredoc の本文を 'x' に、
    `\\` の続き行を空白に。 $(...) `...` の中は code として残す。"""
    n = len(data)
    out = bytearray(data)
    depth = [0] * n
    lines = data.split(b"\n")
    line_starts = [0]
    for ln in lines[:-1]:
        line_starts.append(line_starts[-1] + len(ln) + 1)
    stack: List[List] = []  # ["D"] / ["C", 括弧の深さ] / ["B"] / ["A", 括弧の深さ] / ["P", 波括弧の深さ]
    pending: List[Tuple[bytes, bool]] = []
    U = umv()

    def top() -> Optional[str]:
        return stack[-1][0] if stack else None

    def line_index(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def hide(a: int, b: int, ch: int = 0x78) -> None:  # 'x'
        for k in range(max(a, 0), min(b, n)):
            out[k] = ch

    i = 0
    while i < n:
        c = data[i]
        d = len(stack)
        t = top()
        depth[i] = d
        if t == "D":
            if c == 0x5C:  # \
                hide(i, i + 2)
                if i + 1 < n:
                    depth[i + 1] = d
                i += 2
                continue
            if c == 0x22:  # "
                stack.pop()
                depth[i] = len(stack)
                i += 1
                continue
            if c == 0x24 and data[i + 1:i + 3] == b"((":
                stack.append(["A", 2])
                depth[i + 1] = depth[i + 2] = d
                i += 3
                continue
            if c == 0x24 and data[i + 1:i + 2] == b"(":
                stack.append(["C", 1])
                depth[i + 1] = d
                i += 2
                continue
            if c == 0x60:  # `
                stack.append(["B"])
                i += 1
                continue
            if c != 0x24:
                out[i] = 0x78
            i += 1
            continue
        if t == "A":
            if c == 0x28:
                stack[-1][1] += 1
            elif c == 0x29:
                stack[-1][1] -= 1
                if stack[-1][1] <= 0:
                    stack.pop()
                    depth[i] = len(stack)
            i += 1
            continue
        if t == "P":
            if c == 0x7B:
                stack[-1][1] += 1
            elif c == 0x7D:
                stack[-1][1] -= 1
                if stack[-1][1] <= 0:
                    stack.pop()
                    depth[i] = len(stack)
            if c != 0x0A:
                out[i] = 0x78
            i += 1
            continue
        # code (最上位 / $(...) / `...`)
        if c == 0x5C:  # \
            if i + 1 < n and data[i + 1] == 0x0A:
                hide(i, i + 2, 0x20)
            else:
                hide(i, i + 2)
            if i + 1 < n:
                depth[i + 1] = d
            i += 2
            continue
        if c == 0x24 and data[i + 1:i + 2] == b"'":  # $'...'
            j = i + 2
            while j < n and data[j] != 0x27:
                j += 2 if data[j] == 0x5C else 1
            hide(i, j)
            for k in range(i, min(j + 1, n)):
                depth[k] = d
            i = j + 1
            continue
        if c == 0x27:  # '...'
            j = data.find(b"'", i + 1)
            if j < 0:
                j = n
            hide(i + 1, j)
            for k in range(i, min(j + 1, n)):
                depth[k] = d
            i = j + 1
            continue
        if c == 0x22:  # "
            stack.append(["D"])
            i += 1
            continue
        if c == 0x24 and data[i + 1:i + 3] == b"((":
            stack.append(["A", 2])
            depth[i + 1] = depth[i + 2] = d
            i += 3
            continue
        if c == 0x24 and data[i + 1:i + 2] == b"(":
            stack.append(["C", 1])
            depth[i + 1] = d
            i += 2
            continue
        if c == 0x24 and data[i + 1:i + 2] == b"{":
            stack.append(["P", 1])
            out[i + 1] = 0x78
            depth[i + 1] = d
            i += 2
            continue
        if data[i:i + 2] == b"((" and (i == 0 or data[i - 1] in WORD_BREAK):
            stack.append(["A", 2])
            depth[i + 1] = d
            i += 2
            continue
        if c == 0x60:  # `
            if t == "B":
                stack.pop()
                depth[i] = len(stack)
            else:
                stack.append(["B"])
            i += 1
            continue
        if t == "C" and c == 0x28:
            stack[-1][1] += 1
        elif t == "C" and c == 0x29:
            stack[-1][1] -= 1
            if stack[-1][1] <= 0:
                stack.pop()
                depth[i] = len(stack)
            i += 1
            continue
        if c == 0x23 and (i == 0 or data[i - 1] in WORD_BREAK):  # 語頭の # から行末は comment
            j = data.find(b"\n", i)
            if j < 0:
                j = n
            hide(i, j)
            for k in range(i, j):
                depth[k] = d
            i = j
            continue
        if data[i:i + 3] == b"<<<":
            depth[i + 1] = depth[i + 2] = d
            i += 3
            continue
        if data[i:i + 2] == b"<<":
            li = line_index(i)
            ls = line_starts[li]
            le = data.find(b"\n", i)
            if le < 0:
                le = n
            decl = U._heredoc_at(data[ls:le], i - ls)
            if decl is not None:
                delim, strip = decl[0], decl[1]
                if U._terminates(lines, li + 1, delim, strip):
                    pending.append((delim, strip))
                    for k in range(i, ls + decl[3]):
                        depth[k] = d
                    i = ls + decl[3]
                    continue
            depth[i + 1] = d
            i += 2
            continue
        if c == 0x0A and pending:  # 改行の後ろに heredoc の本文が続く
            li = line_index(i) + 1
            for delim, strip in pending:
                while li < len(lines):
                    body = lines[li]
                    s = line_starts[li]
                    hide(s, s + len(body))
                    for k in range(s, min(s + len(body) + 1, n)):
                        depth[k] = d
                    li += 1
                    if (body.lstrip(b"\t") if strip else body) == delim:
                        break
            pending = []
            i = line_starts[li] - 1 if li < len(lines) else n
            if i < n:
                depth[i] = d
            i += 1
            continue
        i += 1
    return bytes(out), depth


# ---------------------------------------------------------------- 述語

PF_SET_RE = re.compile(r"(?:^|[\s;&|(){}!])set(?:[ \t][^\n;&|]*?)?[ \t]-[A-Za-z]*o[ \t]+pipefail\b", re.M)
PF_SETOPT_RE = re.compile(r"(?:^|[\s;&|(){}!])setopt[ \t][^\n;&|]*?(?<![A-Za-z_])(?i:pipe_?fail)\b", re.M)
GREP_STAGE_RE = re.compile(
    r"(?<!\|)\|(?!\|)&?[ \t\n]*(?:(?:command|builtin|exec|nice|time)[ \t]+)*(?:[^\s|;&()<>`]*/)?[ef]?grep(?=[ \t\n;&|)`]|$)")
STAGE_END_RE = re.compile(r"[^|;&)\n`]*")
ARG_TAKING = frozenset("efmABCdD")
SEPARATORS = frozenset("|&;(){}\n`")
LEAD_WORDS = frozenset(("if", "then", "elif", "else", "do", "while", "until", "time", "!", "{", "exec", "command",
                        "builtin", "nice"))
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
TAIL_UNBOUNDED_RE = re.compile(r"(?:^|\s)(?:-[nc][ \t]*\+|\+\d|--(?:lines|bytes)=\+|-[A-Za-z]*[fF][A-Za-z]*(?=\s|$)|--follow)")


def sets_pipefail(masked: str) -> bool:
    return bool(PF_SET_RE.search(masked) or PF_SETOPT_RE.search(masked))


def is_library(path: str) -> bool:
    parts = Path(path).parts
    if not parts:
        return False
    name = parts[-1]
    if ".test." in name:
        return False
    return "lib" in parts[:-1] or name.startswith("lib")


def has_quiet(args: str) -> bool:
    for tok in args.split():
        if tok == "--":
            break
        if tok in ("--quiet", "--silent"):
            return True
        if tok.startswith("--") or not tok.startswith("-") or len(tok) < 2:
            continue
        for ch in tok[1:]:
            if ch == "q":
                return True
            if ch in ARG_TAKING:
                break
    return False


def stage_start(masked: str, depth: List[int], pipe: int) -> int:
    """pipe の直前の段の始まり (= pipe と同じ深さの区切りの次、 または入れ子の外に出た所の次)。"""
    pd = depth[pipe]
    j = pipe - 1
    while j >= 0:
        if depth[j] < pd:
            return j + 1
        if depth[j] == pd:
            ch = masked[j]
            if ch == "&" and ((j > 0 and masked[j - 1] in "<>") or masked[j + 1:j + 2] == ">"):
                j -= 1  # redirection の & (2>&1 / >&2 / &>) は区切りでない
                continue
            if ch in SEPARATORS:
                return j + 1
            if ch == "!" and j + 1 < len(masked) and masked[j + 1] in " \t":
                return j + 1
        j -= 1
    return 0


def classify(writer: str) -> Optional[str]:
    """書き手の段 (伏せた文) → "var" / "file" / "cmd" / None (見ない)。"""
    toks = writer.split()
    while toks and (toks[0] in LEAD_WORDS or ASSIGN_RE.match(toks[0])):
        toks.pop(0)
    if not toks:
        return None
    w = toks[0].rsplit("/", 1)[-1]
    rest = " ".join(toks[1:])
    if w in ("printf", "echo", "print"):
        return "var" if ("$" in rest or "`" in rest) else None
    if w == "cat":
        return "file"
    if w == "tail":
        return "file" if TAIL_UNBOUNDED_RE.search(" " + rest) else None
    if w == "head":
        return None
    return "cmd"


def scan_bytes(data: bytes, assume_pipefail: bool = False, path: str = "") -> List[Hit]:
    masked_b, depth = mask(data)
    masked = masked_b.decode("latin-1")
    if not (assume_pipefail or sets_pipefail(masked) or is_library(path)):
        return []
    hits: List[Hit] = []
    for m in GREP_STAGE_RE.finditer(masked):
        pipe = m.start()
        end_m = STAGE_END_RE.match(masked, m.end())
        args_end = end_m.end() if end_m else m.end()
        if not has_quiet(masked[m.end():args_end]):
            continue
        start = stage_start(masked, depth, pipe)
        writer = masked[start:pipe]
        kind = classify(writer)
        if kind is None:
            continue
        lead = len(writer) - len(writer.lstrip())
        wstart = start + lead
        first = data.count(b"\n", 0, wstart) + 1
        last = data.count(b"\n", 0, max(args_end - 1, wstart)) + 1
        text = re.sub(r"\s+", " ", data[wstart:args_end].decode("utf-8", "replace")).strip()
        hits.append(Hit(first, (first, last), kind, text[:160]))
    return hits


FIX = {
    "var": "here-string に: grep -q … <<< \"$x\"  (か -q を外して >/dev/null)",
    "file": "file を grep に渡す: grep -q … FILE / grep -q … < <(tail …)",
    "cmd": "-q を外して >/dev/null に送る (前段の失敗も今どおり拾う) か grep -q … < <(cmd)",
}
KIND_LABEL = {"var": "変数を流す書き手", "file": "file を全部流す書き手", "cmd": "コマンドの出力"}


def format_hit(path: str, hit: Hit) -> str:
    return "  %s:%d: [%s] %s\n      → %s" % (path, hit.line, KIND_LABEL[hit.kind], hit.text, FIX[hit.kind])


# ---------------------------------------------------------------- 面

def _print_block(findings: List[str], warns: List[str], stream) -> None:
    if findings:
        print("%s pipefail の下で変数・file を `grep -q` に pipe で流す形 (入力が約 64 KB を越えると、 一致したのに偽になる)"
              " — %d 件" % (BLOCK_HEADING, len(findings)), file=stream)
        for f in findings:
            print(f, file=stream)
        print("  規約 = %s / 直すと意味が変わる当たりだけ %s=0 で commit" % (DOC_ANCHOR, ENV_SKIP), file=stream)
    if warns:
        print("%s (commit は止めない) コマンドの出力を `grep -q` に pipe で流す形 — 出力が約 64 KB を越えうるなら直す"
              " — %d 件" % (WARN_HEADING, len(warns)), file=stream)
        for w in warns:
            print(w, file=stream)
        if not findings:
            print("  規約 = %s" % DOC_ANCHOR, file=stream)


def run_staged(repo: Optional[str]) -> int:
    if os.environ.get(ENV_SKIP) == "0":
        print("%s %s=0 — この commit では検査しない" % (HEADING, ENV_SKIP), file=sys.stderr)
        return 0
    U = umv()
    top = U._git(["rev-parse", "--show-toplevel"], repo)
    if top.returncode != 0:
        print("%s (git repo でない: %s)" % (NOT_RUN, repo or os.getcwd()), file=sys.stderr)
        return 3
    root = top.stdout.decode("utf-8", "replace").strip()
    names = U._git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"], root)
    if names.returncode != 0:
        print("%s (git diff --cached が失敗: rc=%d)" % (NOT_RUN, names.returncode), file=sys.stderr)
        return 3
    if U.read_blob is None:
        print("%s (lib/git_blob.py を読めない)" % NOT_RUN, file=sys.stderr)
        return 3
    stage = U._git(["ls-files", "--stage", "-z"], root)
    if stage.returncode != 0:
        print("%s (git ls-files --stage が失敗: rc=%d)" % (NOT_RUN, stage.returncode), file=sys.stderr)
        return 3
    gitlinks = {row.partition(b"\t")[2] for row in stage.stdout.split(b"\0") if row.startswith(b"160000 ")}
    findings: List[str] = []
    warns: List[str] = []
    unread: List[str] = []
    for raw in names.stdout.split(b"\0"):
        if not raw or raw in gitlinks:
            continue
        path = raw.decode("utf-8", "surrogateescape")
        suffix = Path(path).suffix.lower()
        if suffix not in U.SHELL_SUFFIXES and suffix != "":
            continue
        rc, data = U.read_blob(":" + path, cwd=root)
        if rc != 0 or data.startswith(U.GITCRYPT_MAGIC):
            unread.append(path)
            continue
        if not U.is_shell_path(path, data[:256]):
            continue
        hits = scan_bytes(data, path=path)
        if not hits:
            continue
        added = U.added_line_numbers(root, path)
        if added is None:
            unread.append(path)
            continue
        for h in hits:
            if any(ln in added for ln in range(h.span[0], h.span[1] + 1)):
                (findings if h.kind != "cmd" else warns).append(format_hit(path, h))
    if findings or warns:
        _print_block(findings, warns, sys.stderr)
    if findings:
        return 1
    if unread:
        print("%s (%d file を読めない: %s)" % (NOT_RUN, len(unread), ", ".join(unread[:3])), file=sys.stderr)
        return 3
    return 0


def run_paths(paths: Iterable[str], assume_pipefail: bool) -> int:
    findings: List[str] = []
    warns: List[str] = []
    unread: List[str] = []
    for p in paths:
        try:
            data = Path(p).read_bytes()
        except OSError:
            unread.append(p)
            continue
        for h in scan_bytes(data, assume_pipefail=assume_pipefail, path=p):
            (findings if h.kind != "cmd" else warns).append(format_hit(p, h))
    _print_block(findings, warns, sys.stdout)
    if findings:
        return 1
    if unread:
        print("%s (%d file を読めない: %s)" % (NOT_RUN, len(unread), ", ".join(unread[:3])), file=sys.stderr)
        return 3
    return 0


def run_tree(roots: List[str], strict: bool, assume_pipefail: bool) -> int:
    U = umv()
    total = {"var": 0, "file": 0, "cmd": 0}
    failed: List[str] = []
    for root_s in roots:
        root = Path(root_s).expanduser()
        if not root.is_dir():
            failed.append(root_s)
            continue
        for repo in U.repos_under(root):
            files, ok = U.tracked_shell_files(repo)
            if not ok:
                failed.append(str(repo))
                continue
            lines: List[str] = []
            for rel in files:
                full = repo / rel
                try:
                    if full.is_symlink() or not full.is_file():
                        continue
                    data = full.read_bytes()
                except OSError:
                    continue
                if data.startswith(U.GITCRYPT_MAGIC):
                    continue
                for h in scan_bytes(data, assume_pipefail=assume_pipefail, path=rel):
                    total[h.kind] += 1
                    lines.append(format_hit(rel, h))
            if lines:
                print("%s %d 件 (shell script %d 本を走査)" % (repo.name, len(lines), len(files)))
                for ln in lines:
                    print(ln)
    print("%s fleet 合計 = 止める形 %d 件 (変数 %d・file %d) / 警告の形 (コマンド) %d 件 (規約 = %s)"
          % (HEADING, total["var"] + total["file"], total["var"], total["file"], total["cmd"], DOC_ANCHOR))
    if failed:
        print("%s (走査できない: %s)" % (NOT_RUN, ", ".join(failed[:5])), file=sys.stderr)
        return 3
    return 1 if (strict and (total["var"] + total["file"])) else 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    import shutil
    import tempfile

    fails: List[str] = []

    def expect(label: str, ok: bool, detail: str = "") -> None:
        print("  %s %s%s" % ("PASS" if ok else "FAIL", label, "" if ok else "  " + detail))
        if not ok:
            fails.append(label)

    PF = b"#!/usr/bin/env bash\nset -euo pipefail\n"

    def kinds(src: bytes, path: str = "x.sh", assume: bool = False) -> List[Tuple[int, str]]:
        return [(h.line, h.kind) for h in scan_bytes(src, assume_pipefail=assume, path=path)]

    # 陽性対照 (止める)
    expect("止める: printf '%s' \"$x\" | grep -q", kinds(PF + b"printf '%s' \"$x\" | grep -q y\n") == [(3, "var")])
    expect("止める: echo \"$x\" | grep -qE", kinds(PF + b"echo \"$x\" | grep -qE 'a|b'\n") == [(3, "var")])
    expect("止める: zsh の setopt pipe_fail + print -r --",
           kinds(b"#!/bin/zsh\nsetopt pipe_fail\nprint -r -- \"$x\" | grep -Fq y\n", "z.zsh") == [(3, "var")])
    expect("止める: --quiet と --silent",
           kinds(PF + b"echo \"$x\" | grep --quiet y\necho \"$x\" | grep --silent y\n") == [(3, "var"), (4, "var")])
    expect("止める: if ! printf … | grep -q", kinds(PF + b"if ! printf '%s' \"$x\" | grep -q y; then :; fi\n")
           == [(3, "var")])
    expect("止める: \\ の続き行は 1 つの pipeline (書き手の行で出す)",
           kinds(PF + b"printf '%s' \"$x\" \\\n  | grep -q y\n") == [(3, "var")])
    expect("止める: 行末の | の後の改行も 1 つの pipeline", kinds(PF + b"printf '%s' \"$x\" |\n  grep -q y\n")
           == [(3, "var")])
    expect("止める: $(...) の中の形", kinds(PF + b"r=$(printf '%s' \"$x\" | grep -q y && echo 1)\n") == [(3, "var")])
    expect("止める: cat F | grep -q / tail -n +2 / tail -f",
           kinds(PF + b"cat \"$f\" | grep -q y\ntail -n +2 \"$f\" | grep -q y\ntail -f log | grep -q y\n")
           == [(3, "file"), (4, "file"), (5, "file")])
    expect("止める: printf \"$(cmd)\" はコマンドの置換を書き手に含む (中の括弧で段を切らない)",
           kinds(PF + b"printf '%s' \"$(cmd a)\" | grep -q y\n") == [(3, "var")])
    expect("止める: echo ${x} (引用符の外の ${...}) も変数", kinds(PF + b"echo ${x} | grep -q y\n") == [(3, "var")])
    expect("止める: |& も pipe", kinds(PF + b"echo \"$x\" |& grep -q y\n") == [(3, "var")])
    expect("止める: -Fqx と -qm1 (q が引数の前)", kinds(PF + b"echo \"$x\" | grep -Fqx y\necho \"$x\" | grep -qm1 y\n")
           == [(3, "var"), (4, "var")])
    expect("止める: command grep と /usr/bin/grep と egrep",
           kinds(PF + b"echo \"$x\" | command grep -q y\necho \"$x\" | /usr/bin/grep -q y\necho \"$x\" | egrep -q y\n")
           == [(3, "var"), (4, "var"), (5, "var")])
    expect("止める: 部品 (lib/ の下) は pipefail を立てていなくても見る",
           kinds(b"#!/usr/bin/env bash\nm() { printf '%s' \"$1\" | grep -q y; }\n", "scripts/lib/m.sh") == [(2, "var")])
    expect("止める: 名前が lib で始まる部品も見る",
           kinds(b"m() { echo \"$1\" | grep -q y; }\n", "hooks/lib-surface.sh") == [(1, "var")])
    expect("止める: 書き手の 2>&1 と &> の & で段を切らない",
           kinds(PF + b"echo \"$x\" 2>&1 | grep -q y\nprintf '%s' \"$x\" &>/dev/null | grep -q y\n")
           == [(3, "var"), (4, "var")])
    expect("止める: set -o errexit -o pipefail も pipefail",
           kinds(b"set -o errexit -o pipefail\necho \"$x\" | grep -q y\n") == [(2, "var")])
    # 警告 (止めない)
    expect("警告だけ: コマンドの出力 (git diff --name-only | grep -q)",
           kinds(PF + b"git diff --cached --name-only | grep -qE 'a'\n") == [(3, "cmd")])
    expect("警告だけ: 2 段前の書き手 (直前の段 = tr) はコマンドとして扱う",
           kinds(PF + b"printf '%s' \"$x\" | tr a b | grep -q y\n") == [(3, "cmd")])
    # 陰性対照 (見ない)
    expect("見ない: here-string", kinds(PF + b"grep -q y <<< \"$x\"\n") == [])
    expect("見ない: -q の無い grep … >/dev/null", kinds(PF + b"printf '%s' \"$x\" | grep y >/dev/null\n") == [])
    expect("見ない: 上限のある書き手 (head -c 9 / tail -n 1 / tail -5)",
           kinds(PF + b"head -c 9 \"$f\" | grep -q G\ntail -n 1 \"$f\" | grep -q y\ntail -5 f | grep -q y\n") == [])
    expect("見ない: 文字だけの printf / echo", kinds(PF + b"printf 'abc' | grep -q a\necho abc | grep -q a\n") == [])
    expect("見ない: comment 行と行末の comment",
           kinds(PF + b"# printf \"$x\" | grep -q y\n: ok  # echo \"$x\" | grep -q y\n") == [])
    expect("見ない: 単一引用符の中 (bash -c '...' の文字列)",
           kinds(PF + b"bash -c 'printf \"$x\" | grep -q y'\n") == [])
    expect("見ない: heredoc の本文 (引用符つき・引用符なし)",
           kinds(PF + b"cat <<'EOF'\necho \"$x\" | grep -q y\nEOF\ncat <<EOF\necho \"$x\" | grep -q y\nEOF\n") == [])
    expect("見ない: heredoc の後ろの行は見る",
           kinds(PF + b"cat <<'EOF'\nbody\nEOF\necho \"$x\" | grep -q y\n") == [(6, "var")])
    expect("見ない: pipefail の無い file は見ない", kinds(b"#!/usr/bin/env bash\necho \"$x\" | grep -q y\n") == [])
    expect("見ない: set +o pipefail と setopt no_pipe_fail は pipefail でない",
           kinds(b"set +o pipefail\necho \"$x\" | grep -q y\n") == []
           and kinds(b"setopt no_pipe_fail\necho \"$x\" | grep -q y\n", "z.zsh") == [])
    expect("見ない: lib/ の下でも .test. の file は部品でない",
           kinds(b"echo \"$x\" | grep -q y\n", "scripts/lib/m.test.sh") == [])
    expect("見ない: || は pipe でない", kinds(PF + b"printf '%s' \"$x\" || grep -q y f\n") == [])
    expect("見ない: -eq は pattern が q (quiet でない)", kinds(PF + b"echo \"$x\" | grep -eq\n") == [])
    expect("見ない: 単一引用符の中の set -o pipefail は file の pipefail に数えない",
           kinds(b"bash -c 'set -o pipefail; true'\necho \"$x\" | grep -q y\n") == [])
    expect("--assume-pipefail なら pipefail の無い file も見る",
           kinds(b"echo \"$x\" | grep -q y\n", assume=True) == [(1, "var")])
    expect("算術の << は heredoc と読まない (後ろの行を飲み込まない)",
           kinds(PF + b"y=$((1 << 2))\necho \"$x\" | grep -q y\n") == [(4, "var")])
    hs = scan_bytes(PF + b"printf '%s' \"$x\" | grep -q y\n", path="x.sh")
    expect("当たりの文は元の文 (伏せる前) で出す", bool(hs) and hs[0].text == "printf '%s' \"$x\" | grep -q y",
           repr(hs))

    # 一時 repo: --staged の赤 → 緑、 足した行だけ、 警告だけは exit 0、 git repo でない
    if shutil.which("git") is None:
        print("  SKIP --staged の e2e (git 不在)")
    else:
        me = os.path.abspath(__file__)
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            env.pop(ENV_SKIP, None)

            def git(*a: str) -> subprocess.CompletedProcess:
                return subprocess.run(["git", *a], cwd=td, env=env, capture_output=True, check=False)

            def staged(extra_env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
                r = subprocess.run([sys.executable, me, "--staged"], cwd=td, capture_output=True, check=False,
                                   env=dict(env, **(extra_env or {})))
                return r.returncode, r.stderr.decode("utf-8", "replace")

            git("init", "-q")
            git("config", "user.email", "t@example.invalid")
            git("config", "user.name", "t")
            base = PF + b"echo \"$old\" | grep -q y\n"
            (Path(td) / "a.sh").write_bytes(base)
            git("add", "a.sh")
            git("commit", "-q", "-m", "init", "--no-verify")
            rc, out = staged()
            expect("--staged: 何も stage していなければ exit 0", rc == 0, out)
            (Path(td) / "a.sh").write_bytes(base + b"printf '%s' \"$x\" | grep -q z\n")
            git("add", "a.sh")
            rc, out = staged()
            expect("--staged: 足した違反の行で exit 1 + BLOCK 見出し", rc == 1 and BLOCK_HEADING in out, out)
            expect("--staged: 足した行だけを出す (既存の行 3 は出さない)", "a.sh:4:" in out and "a.sh:3:" not in out, out)
            expect("--staged: 直し方 (here-string) と規約の節を出す", "<<<" in out and DOC_ANCHOR in out, out)
            rc, out = staged({ENV_SKIP: "0"})
            expect("--staged: escape hatch で exit 0", rc == 0, out)
            (Path(td) / "a.sh").write_bytes(base + b"grep -q z <<< \"$x\"\n")
            git("add", "a.sh")
            rc, out = staged()
            expect("--staged: here-string に直すと exit 0 (赤 → 緑)", rc == 0 and BLOCK_HEADING not in out, out)
            (Path(td) / "a.sh").write_bytes(base + b"git diff --name-only | grep -q z\n")
            git("add", "a.sh")
            rc, out = staged()
            expect("--staged: コマンドの出力の形は警告だけで exit 0", rc == 0 and WARN_HEADING in out
                   and BLOCK_HEADING not in out, out)
            git("reset", "-q", "--hard")
            (Path(td) / "hook").write_bytes(PF + b"echo \"$x\" | grep -q y\n")
            (Path(td) / "tool.py").write_bytes(b"#!/usr/bin/env python3\n# echo \"$x\" | grep -q y\n")
            (Path(td) / "plain.sh").write_bytes(b"#!/usr/bin/env bash\necho \"$x\" | grep -q y\n")
            git("add", "hook", "tool.py", "plain.sh")
            rc, out = staged()
            expect("--staged: 拡張子の無い shebang の file は検査、 .py と pipefail の無い file は対象外",
                   rc == 1 and "hook:3:" in out and "tool.py" not in out and "plain.sh" not in out, out)
            git("reset", "-q", "--hard")
            git("clean", "-qfd")
            (Path(td) / "vendor" / "sub").mkdir(parents=True)
            git("update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",vendor/sub")
            rc, out = staged()
            expect("--staged: submodule (gitlink) は読まない", rc == 0 and NOT_RUN not in out, out)
        with tempfile.TemporaryDirectory() as td2:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--staged"], cwd=td2, capture_output=True,
                               check=False, env=dict(os.environ, GIT_CEILING_DIRECTORIES=td2))
            err = r.stderr.decode("utf-8", "replace")
            expect("--staged: git repo でなければ exit 3 + 1 行 (違反の 1 と区別)", r.returncode == 3 and NOT_RUN in err,
                   err)
            p = Path(td2) / "x.sh"
            p.write_bytes(PF + b"echo \"$v\" | grep -q y\n")
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--paths", str(p)], capture_output=True,
                               check=False)
            expect("--paths: 当たりで exit 1", r.returncode == 1 and b"x.sh:3:" in r.stdout, repr(r.stdout))
            p.write_bytes(PF + b"grep -q y <<< \"$v\"\n")
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--paths", str(p)], capture_output=True,
                               check=False)
            expect("--paths: 直すと exit 0", r.returncode == 0, repr(r.stdout))

    # 実物の bash: 止める形は大きな入力で一致を落とし、 here-string と -q を外した形は当たる (述語が実害と対応すること)
    bash = "/bin/bash" if os.path.exists("/bin/bash") else shutil.which("bash")
    if not bash:
        print("  SKIP 実物の bash での確認 (bash が無い)")
    else:
        with tempfile.TemporaryDirectory() as td3:
            # 改行の多い大きな入力 (1 行だけの入力は grep が行の終わりまで読むので落ちない = 規約の節の最後の文)
            (Path(td3) / "data.txt").write_bytes(b"HEAD\n" + (b"x" * 49 + b"\n") * 20000)
            big = b"set -o pipefail\nout=\"$(cat \"$(dirname \"$0\")/data.txt\")\"\n"
            bad = Path(td3) / "bad.sh"
            good = Path(td3) / "good.sh"
            noq = Path(td3) / "noq.sh"
            bad.write_bytes(big + b"if printf '%s' \"$out\" | grep -q HEAD; then echo hit; else echo miss; fi\n")
            good.write_bytes(big + b"if grep -q HEAD <<< \"$out\"; then echo hit; else echo miss; fi\n")
            noq.write_bytes(big + b"if printf '%s' \"$out\" | grep HEAD >/dev/null; then echo hit; else echo miss; fi\n")
            env_b = dict(os.environ)
            rb = subprocess.run([bash, str(bad)], capture_output=True, check=False, env=env_b)
            rg = subprocess.run([bash, str(good)], capture_output=True, check=False, env=env_b)
            rn = subprocess.run([bash, str(noq)], capture_output=True, check=False, env=env_b)
            expect("実物の bash: 止める形は 1 MB の入力で一致を落とす (miss)", rb.stdout.strip() == b"miss",
                   repr(rb.stdout + rb.stderr))
            expect("実物の bash: here-string は当たる (hit)", rg.stdout.strip() == b"hit", repr(rg.stdout + rg.stderr))
            expect("実物の bash: -q を外して >/dev/null は当たる (hit)", rn.stdout.strip() == b"hit",
                   repr(rn.stdout + rn.stderr))
            expect("検出器: bad.sh は止め、 good.sh と noq.sh は止めない",
                   [h.kind for h in scan_bytes(bad.read_bytes(), path="bad.sh")] == ["var"]
                   and scan_bytes(good.read_bytes(), path="good.sh") == []
                   and scan_bytes(noq.read_bytes(), path="noq.sh") == [])

    print("check-pipefail-grep-q selftest:", "ALL PASS" if not fails else "FAIL %s" % fails)
    return 0 if not fails else 1


# ---------------------------------------------------------------- main

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="commit gate (stage した shell script の足した行)")
    mode.add_argument("--paths", nargs="+", metavar="FILE", help="与えた file の全文")
    mode.add_argument("--tree", nargs="+", metavar="DIR", help="DIR (か直下の各 git repo) の track 済み shell script")
    mode.add_argument("--selftest", action="store_true")
    ap.add_argument("--repo", help="--staged の repo (既定 = cwd)")
    ap.add_argument("--strict", action="store_true", help="--tree で止める形の当たりがあれば exit 1")
    ap.add_argument("--assume-pipefail", action="store_true", help="--paths / --tree で pipefail の無い file も見る")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.staged:
        return run_staged(args.repo)
    if args.paths:
        return run_paths(args.paths, args.assume_pipefail)
    return run_tree(args.tree, args.strict, args.assume_pipefail)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # 故障を違反 (1) と同じ値にしない
        msg = str(exc).splitlines()[0][:200] if str(exc) else ""
        print("%s (内部の例外 %s: %s)" % (NOT_RUN, type(exc).__name__, msg), file=sys.stderr)
        sys.exit(3)
