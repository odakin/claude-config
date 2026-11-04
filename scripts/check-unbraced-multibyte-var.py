#!/usr/bin/env python3
"""check-unbraced-multibyte-var.py — shell script で波括弧の無い変数の直後に全角文字が続く形 (`"$name、"`) を見つける: commit gate の段 (--staged、 違反で exit 1) + fleet の棚卸し (--tree) (UTF-8 の locale では macOS の bash が全角文字の先頭 byte を変数名に取り込み、 set -u なら落ち、 無ければ値が黙って消える)。

規約 (症状・locale 依存・書き方) = conventions/shell-multibyte-truncation.md#unbraced-var-before-multibyte。
由来 (実測): 同じ class の不具合が 2 件、 どちらも C locale の手元と test では通り、 UTF-8 の locale を渡す呼び元
(session 開始 hook の実行環境) でだけ落ちた = 手で回して通ることは反証にならないので、 commit で機械が止める。

bash 3.2 (macOS 同梱) の実測 (LC_ALL=en_US.UTF-8 と ja_JP.UTF-8 で同じ、 C locale では全部正しく展開):
  取り込む先頭 byte = 0xC2 0xC3 (Latin-1 の文字) / 0xE3 (かな・漢字・句読点) / 0xEF (全角括弧) / 0xF0 (絵文字)
  取り込まない = 0xD7 (Latin-1 の × に当たる byte)。 Homebrew の bash 5.3 (macOS) も 0xE3 を取り込んで set -u で落ちる
  (= `#!/usr/bin/env bash` が新しい bash を選んでも避けられない)。 述語は規約の正規表現どおり 0xC0-0xFF の全部を数える
  (報告の側に倒す = 直し方 `${var}` はどの byte の前でも無害)。 zsh 5.9 は かな・漢字 を取り込み、 句読点は取り込まない
  (規約の記述) — .zsh と zsh の shebang も同じ述語で数える (句読点の当たりは zsh では実害が無いが、 直し方は無害)。

述語 (byte 列で見る):
  当たり = `$` + `[A-Za-z_][A-Za-z0-9_]*` の直後の byte が 0xC0-0xFF (= 規約の正規表現 `(?<![\\\\'$])\\$[A-Za-z_][A-Za-z0-9_]*[\\xc0-\\xff]`)。
  `$1` `$$` `$?` `$@` 等の特殊変数と `${var}` は当たらない (1 文字で終わる / 波括弧で閉じる)。
  数えない所 (= 明らかな誤検出だけを外す。 迷う所は報告する):
    - 先頭の非空白が `#` の行 (comment と shebang)、 引用符の外で語頭に来た `#` から行末 (行末の comment)
    - `\\$var` (逆斜線で escape した `$`)、 `$$var` の 2 つ目の `$`
    - 1 行の中で開いて閉じた単一引用符 `'...'` と `$'...'` の中。 ただしその行の引用符の対が行末で閉じていない
      (= 複数行にまたがる文字列の途中の行かもしれない) ときは、 行の解析を信用せず、 規約の正規表現そのもの
      (`'` 直後の `$` だけを外す) で行全体を数える。 複数行の二重引用符の途中の行で、 引用符を 1 つも含まない行に
      `'$var、'` がある形は取り逃す (実害のある形としては稀と判断した)
    - 引用符つきの heredoc (`<<'EOF'` `<<"EOF"` `<<\\EOF`) の本文 (展開されない)。 引用符の無い heredoc の本文は
      展開されるので、 引用符も `#` も literal として全部数える。 heredoc の終わりの行が見つからない `<<` (算術の
      左 shift など) は heredoc として扱わない
  数える所の限界: shell 以外の言語を複数行の単一引用符で埋め込んだ本文 (awk / perl の `$name`) は、 引用符を
  含まない行が「閉じている」 と見えるので報告する。 その行は `${name}` にすると awk / perl の意味が変わる = 直さずに
  escape hatch で commit し、 fleet の一覧に残ることを受け入れる (実測の件数は --tree の出力で見る)。

面:
  --staged [--repo DIR]   commit gate。 stage した shell script (拡張子 .sh .bash .zsh、 または拡張子の無い file で
                          sh / bash / zsh の shebang) を index の blob で読み (lib/git_blob = git-crypt も平文)、 全文を
                          解析したうえで、 この commit で足した行 (`git diff --cached -U0` の hunk) の当たりだけを出す。
                          呼び元との契約 = 「exit 1 かつ見出し `check-unbraced-multibyte-var: BLOCK`」 のときだけ止め、
                          見出しの無い非 0 は 1 行出して通す。 呼び元 = scripts/pre-commit-bib と
                          scripts/public-precommit-runner.sh (2026-09-29 に本人の裁定で配線 = 足した行の
                          違反は全 repo の commit で止まる)
  --paths FILE...         与えた file の全文を解析して当たりを全部出す (shell かどうかは問わない = 呼び手が選ぶ)
  --tree DIR [--strict]   fleet の棚卸し。 DIR が git repo ならその repo、 そうでなければ直下の各 git repo の、
                          track 済みの shell script を worktree で読む。 報告だけ (exit 0)、 --strict なら当たりで exit 1

exit: 0 = 当たり無し (--tree は --strict でなければ常に 0) / 1 = 当たりあり (--staged は BLOCK) /
      3 = 検査が走っていない (git repo でない・git が失敗・読めない file が残った・内部の例外。 見出しつきで 1 行出す。
      呼び元は 1 + 見出し以外で止めない = docs/convention-design-principles.md#failure-exit-equals-violation-exit)
escape hatch: CLAUDE_UNBRACED_MB_VAR_GUARD=0 (--staged だけ。 上の awk / perl の埋め込みなど、 直すと壊れる当たり) /
      git 標準の --no-verify
selftest: python3 check-unbraced-multibyte-var.py --selftest (述語の陽性・陰性対照、 一時 repo での --staged の赤→緑、
      足した行だけを見ること、 clean / smudge filter つき path を平文で読むこと、 /bin/bash 3.2 と UTF-8 の locale が
      ある機械では実物の bash で「当たりの形は set -u で落ち、 `${var}` の形は通る」 ことまで確かめる)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    from git_blob import read_blob  # git-crypt の path も平文で読む
except Exception:  # pragma: no cover
    read_blob = None  # type: ignore[assignment]

HEADING = "check-unbraced-multibyte-var:"
BLOCK_HEADING = HEADING + " BLOCK"
NOT_RUN = HEADING + " 検査が走っていない"
ENV_SKIP = "CLAUDE_UNBRACED_MB_VAR_GUARD"
DOC_ANCHOR = "conventions/shell-multibyte-truncation.md#unbraced-var-before-multibyte"

SHELL_SUFFIXES = {".sh", ".bash", ".zsh"}
SHEBANG_RE = re.compile(rb"^#![ \t]*\S*/(?:env[ \t]+(?:-\S+[ \t]+)*)?(?:ba|z)?sh(?:[ \t]|$)")
GITCRYPT_MAGIC = b"\x00GITCRYPT"
# 規約の正規表現 (行の解析を信用しないときに行全体へ当てる)
RAW_RE = re.compile(rb"(?<![\\'$])\$([A-Za-z_][A-Za-z0-9_]*)(?=[\xc0-\xff])")
HUNK_RE = re.compile(rb"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

IDENT_START = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
IDENT_CHARS = IDENT_START | frozenset(b"0123456789")
WORD_BREAK = frozenset(b" \t;&|()<>")
HEREDOC_WORD_END = frozenset(b" \t;&|()<>")

Hit = Tuple[int, str]  # (1-based line number, token 例 "$name、")


# ---------------------------------------------------------------- 述語

def _token(line: bytes, dollar: int, end: int) -> str:
    """`$name` + 直後の 1 文字 (UTF-8 として読めなければ hex)。"""
    name = line[dollar:end].decode("ascii")
    lead = line[end]
    width = 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4
    try:
        return name + line[end:end + width].decode("utf-8")
    except UnicodeDecodeError:
        return name + "\\x%02x" % lead


def _expanding_hits(line: bytes, lineno: int) -> List[Hit]:
    """引用符の無い heredoc の本文: 引用符も `#` も literal、 `\\` だけが escape。"""
    hits: List[Hit] = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == 0x5C:  # backslash
            i += 2
            continue
        if c == 0x24 and i + 1 < n:  # $
            if line[i + 1] == 0x24:
                i += 2
                continue
            if line[i + 1] in IDENT_START:
                j = i + 1
                while j < n and line[j] in IDENT_CHARS:
                    j += 1
                if j < n and line[j] >= 0xC0:
                    hits.append((lineno, _token(line, i, j)))
                i = j
                continue
        i += 1
    return hits


def _heredoc_at(line: bytes, i: int) -> Optional[Tuple[bytes, bool, bool, int]]:
    """line[i:i+2] == b'<<' の位置から heredoc の宣言を読む → (delimiter, strip_tabs, literal, 次の位置) / None。"""
    j = i + 2
    n = len(line)
    strip = False
    if j < n and line[j] == 0x2D:  # <<-
        strip = True
        j += 1
    while j < n and line[j] in b" \t":
        j += 1
    if j >= n:
        return None
    if line[j] in b"'\"":
        q = line[j]
        k = line.find(bytes([q]), j + 1)
        if k < 0 or k == j + 1:
            return None
        return line[j + 1:k], strip, True, k + 1
    literal = False
    if line[j] == 0x5C:  # <<\EOF
        literal = True
        j += 1
    k = j
    word = bytearray()
    while k < n and line[k] not in HEREDOC_WORD_END:
        if line[k] in b"'\"":
            literal = True
        else:
            word.append(line[k])
        k += 1
    if not word or not (word[0] in IDENT_START or word[0] in b"-.!@%+:="):
        return None  # `<< 2` (算術) や空の語は heredoc として扱わない
    return bytes(word), strip, literal, k


def _code_line(line: bytes, lineno: int) -> Tuple[List[Hit], List[Tuple[bytes, bool, bool]]]:
    """shell の 1 行を解析 → (当たり, この行で始まる heredoc の宣言)。 行末で引用符が閉じていなければ規約の正規表現で数える。"""
    n = len(line)
    state = 0  # 0 = 外 / 1 = '...' / 2 = "..." / 3 = $'...'
    hits: List[Hit] = []
    heredocs: List[Tuple[bytes, bool, bool]] = []
    i = 0
    arith = 0  # (( の深さ (算術の中の << を heredoc と読まない)
    while i < n:
        c = line[i]
        if state == 1:
            if c == 0x27:
                state = 0
            i += 1
            continue
        if state == 3:
            if c == 0x5C:
                i += 2
                continue
            if c == 0x27:
                state = 0
            i += 1
            continue
        if c == 0x5C:
            i += 2
            continue
        if state == 2 and c == 0x22:
            state = 0
            i += 1
            continue
        if c == 0x24 and i + 1 < n:  # $
            nxt = line[i + 1]
            if nxt == 0x24:
                i += 2
                continue
            if state == 0 and nxt == 0x27:  # $'...'
                state = 3
                i += 2
                continue
            if nxt in IDENT_START:
                j = i + 1
                while j < n and line[j] in IDENT_CHARS:
                    j += 1
                if j < n and line[j] >= 0xC0:
                    hits.append((lineno, _token(line, i, j)))
                i = j
                continue
            if state == 0 and line[i + 1:i + 3] == b"((":
                arith += 1
                i += 3
                continue
        if state == 0:
            if c == 0x27:
                state = 1
            elif c == 0x22:
                state = 2
            elif c == 0x23 and (i == 0 or line[i - 1] in WORD_BREAK):  # 語頭の # から行末は comment
                break
            elif line[i:i + 2] == b"((":
                arith += 1
                i += 2
                continue
            elif line[i:i + 2] == b"))" and arith > 0:
                arith -= 1
                i += 2
                continue
            elif line[i:i + 3] == b"<<<":  # here-string
                i += 3
                continue
            elif line[i:i + 2] == b"<<" and arith == 0:
                decl = _heredoc_at(line, i)
                if decl is not None:
                    heredocs.append(decl[:3])
                    i = decl[3]
                    continue
                i += 2
                continue
        i += 1
    if state != 0 or _unbalanced_ignoring_comment(line):
        # 行末で引用符が閉じていない = 複数行の文字列の途中かもしれない → 規約の正規表現で行全体を数える
        return [(lineno, _token(line, m.start(), m.end())) for m in RAW_RE.finditer(line)], heredocs
    return hits, heredocs


def _unbalanced_ignoring_comment(line: bytes) -> bool:
    """`#` を comment と読まずに引用符の対を数え、 行末で開いたままなら True
    (複数行の文字列の途中の行を「語頭の # 以降は comment」 と誤って読んで取り逃さないため)。"""
    state = 0
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if state == 1:
            if c == 0x27:
                state = 0
        elif state == 3:
            if c == 0x5C:
                i += 1
            elif c == 0x27:
                state = 0
        elif c == 0x5C:
            i += 1
        elif state == 2:
            if c == 0x22:
                state = 0
        elif c == 0x24 and line[i + 1:i + 2] == b"'":
            state = 3
            i += 1
        elif c == 0x27:
            state = 1
        elif c == 0x22:
            state = 2
        i += 1
    return state != 0


def scan_bytes(data: bytes) -> List[Hit]:
    """shell script の全文 → 当たり (行番号は 1 起点)。"""
    lines = data.split(b"\n")
    lines = [ln[:-1] if ln.endswith(b"\r") else ln for ln in lines]
    hits: List[Hit] = []
    pending: List[Tuple[bytes, bool, bool]] = []
    current: Optional[Tuple[bytes, bool, bool]] = None
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        lineno = idx + 1
        if current is not None:
            delim, strip, literal = current
            if (line.lstrip(b"\t") if strip else line) == delim:
                current = pending.pop(0) if pending else None
            elif not literal:
                hits.extend(_expanding_hits(line, lineno))
            idx += 1
            continue
        if line.lstrip(b" \t").startswith(b"#"):
            idx += 1
            continue
        line_hits, decls = _code_line(line, lineno)
        hits.extend(line_hits)
        for delim, strip, literal in decls:
            if _terminates(lines, idx + 1, delim, strip):
                pending.append((delim, strip, literal))
        if pending:
            current = pending.pop(0)
        idx += 1
    return hits


def _terminates(lines: List[bytes], start: int, delim: bytes, strip: bool) -> bool:
    for line in lines[start:]:
        if (line.lstrip(b"\t") if strip else line) == delim:
            return True
    return False


def is_shell_path(path: str, head: Optional[bytes]) -> bool:
    """拡張子 .sh .bash .zsh、 または拡張子の無い file で sh / bash / zsh の shebang。"""
    p = Path(path)
    if p.suffix.lower() in SHELL_SUFFIXES:
        return True
    if p.suffix == "" and head is not None:
        first = head.split(b"\n", 1)[0].rstrip(b"\r")
        return bool(SHEBANG_RE.match(first))
    return False


def format_hit(path: str, hit: Hit) -> str:
    lineno, token = hit
    name = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)", token)
    fix = "${%s}%s" % (name.group(1), token[len(name.group(0)):]) if name else token
    return "  %s:%d: %s → %s" % (path, lineno, token, fix)


# ---------------------------------------------------------------- git

def _git(args: List[str], cwd: Optional[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=cwd,
                          capture_output=True, check=False)


def added_line_numbers(repo: Optional[str], path: str) -> Optional[Set[int]]:
    """staged の差分で足した行の番号 (新しい版の側)。 git が失敗したら None。"""
    r = _git(["diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "--", path], repo)
    if r.returncode != 0:
        return None
    out: Set[int] = set()
    for line in r.stdout.split(b"\n"):
        m = HUNK_RE.match(line)
        if m:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            out.update(range(start, start + count))
    return out


def run_staged(repo: Optional[str]) -> int:
    if os.environ.get(ENV_SKIP) == "0":
        print("%s %s=0 — この commit では検査しない" % (HEADING, ENV_SKIP), file=sys.stderr)
        return 0
    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top.returncode != 0:
        print("%s (git repo でない: %s)" % (NOT_RUN, repo or os.getcwd()), file=sys.stderr)
        return 3
    root = top.stdout.decode("utf-8", "replace").strip()
    names = _git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"], root)
    if names.returncode != 0:
        print("%s (git diff --cached が失敗: rc=%d)" % (NOT_RUN, names.returncode), file=sys.stderr)
        return 3
    if read_blob is None:
        print("%s (lib/git_blob.py を読めない)" % NOT_RUN, file=sys.stderr)
        return 3
    # submodule (gitlink = mode 160000) は text の版を持たない (中身は submodule の repo の commit で検査される)。
    # 読みに行くと「読めない」 で exit 3 になり、 pin を上げる commit のたびに「検査が走っていない」 が出る (実測)。
    stage = _git(["ls-files", "--stage", "-z"], root)
    if stage.returncode != 0:
        print("%s (git ls-files --stage が失敗: rc=%d)" % (NOT_RUN, stage.returncode), file=sys.stderr)
        return 3
    gitlinks = {row.partition(b"\t")[2] for row in stage.stdout.split(b"\0") if row.startswith(b"160000 ")}
    findings: List[str] = []
    unread: List[str] = []
    for raw in names.stdout.split(b"\0"):
        if not raw or raw in gitlinks:
            continue
        path = raw.decode("utf-8", "surrogateescape")
        suffix = Path(path).suffix.lower()
        if suffix not in SHELL_SUFFIXES and suffix != "":
            continue
        rc, data = read_blob(":" + path, cwd=root)
        if rc != 0:
            unread.append(path)
            continue
        if data.startswith(GITCRYPT_MAGIC):
            unread.append(path)
            continue
        if not is_shell_path(path, data[:256]):
            continue
        hits = scan_bytes(data)
        if not hits:
            continue
        added = added_line_numbers(root, path)
        if added is None:
            unread.append(path)
            continue
        findings.extend(format_hit(path, h) for h in hits if h[0] in added)
    if findings:
        print("%s 変数の直後に全角文字 (UTF-8 の locale では macOS の bash が先頭 byte を変数名に取り込み、 set -u なら落ち、"
              " 無ければ値が黙って消える) — %d 件" % (BLOCK_HEADING, len(findings)), file=sys.stderr)
        for f in findings:
            print(f, file=sys.stderr)
        print("  直し方: 変数を `${var}` と書く。 規約 = %s / 直すと壊れる当たり (awk・perl の埋め込み) だけ %s=0 で commit"
              % (DOC_ANCHOR, ENV_SKIP), file=sys.stderr)
        return 1
    if unread:
        print("%s (%d file を読めない: %s)" % (NOT_RUN, len(unread), ", ".join(unread[:3])), file=sys.stderr)
        return 3
    return 0


def run_paths(paths: Iterable[str]) -> int:
    findings: List[str] = []
    unread: List[str] = []
    for p in paths:
        try:
            data = Path(p).read_bytes()
        except OSError:
            unread.append(p)
            continue
        findings.extend(format_hit(p, h) for h in scan_bytes(data))
    for f in findings:
        print(f)
    if findings:
        print("%s %d 件 (直し方 = `${var}`、 規約 = %s)" % (HEADING, len(findings), DOC_ANCHOR))
        return 1
    if unread:
        print("%s (%d file を読めない: %s)" % (NOT_RUN, len(unread), ", ".join(unread[:3])), file=sys.stderr)
        return 3
    return 0


def repos_under(root: Path) -> List[Path]:
    from repo_roots import root_is_repo  # 空の repo の root なら子を数える (lib/ は冒頭で sys.path に入れてある)
    if root_is_repo(root):
        return [root]
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").exists())


def tracked_shell_files(repo: Path) -> Tuple[List[str], bool]:
    r = _git(["ls-files", "-z"], str(repo))
    if r.returncode != 0:
        return [], False
    out: List[str] = []
    for raw in r.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "surrogateescape")
        suffix = Path(rel).suffix.lower()
        if suffix in SHELL_SUFFIXES:
            out.append(rel)
        elif suffix == "":
            full = repo / rel
            try:
                if full.is_file() and not full.is_symlink():
                    with open(full, "rb") as fh:
                        if is_shell_path(rel, fh.read(256)):
                            out.append(rel)
            except OSError:
                continue
    return out, True


def run_tree(roots: List[str], strict: bool) -> int:
    total = 0
    failed: List[str] = []
    for root_s in roots:
        root = Path(root_s).expanduser()
        if not root.is_dir():
            failed.append(root_s)
            continue
        for repo in repos_under(root):
            files, ok = tracked_shell_files(repo)
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
                if data.startswith(GITCRYPT_MAGIC):
                    continue
                lines.extend(format_hit(rel, h) for h in scan_bytes(data))
            if lines:
                total += len(lines)
                print("%s %d 件 (shell script %d 本を走査)" % (repo.name, len(lines), len(files)))
                for ln in lines:
                    print(ln)
    print("%s fleet 合計 %d 件 (直し方 = `${var}`、 規約 = %s)" % (HEADING, total, DOC_ANCHOR))
    if failed:
        print("%s (走査できない: %s)" % (NOT_RUN, ", ".join(failed[:5])), file=sys.stderr)
        return 3
    return 1 if (strict and total) else 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    import shutil
    import tempfile

    fails: List[str] = []

    def expect(label: str, ok: bool, detail: str = "") -> None:
        print("  %s %s%s" % ("PASS" if ok else "FAIL", label, "" if ok else "  " + detail))
        if not ok:
            fails.append(label)

    ten = "、".encode("utf-8")  # 、
    wo = "を".encode("utf-8")   # を
    paren = "）".encode("utf-8")  # ）

    def hits(src: bytes) -> List[Hit]:
        return scan_bytes(src)

    # 陽性対照
    expect("違反: \"$name、\" は当たる", [h[0] for h in hits(b'echo "$name' + ten + b'"\n')] == [1])
    expect("違反: 引用符の外の $name を も当たる", len(hits(b"echo $name" + wo + b"\n")) == 1)
    expect("違反: 全角括弧の直前も当たる", len(hits(b'echo "($rpath' + paren + b'"\n')) == 1)
    expect("違反: 二重引用符の中の '...' は literal でないので当たる", len(hits(b'echo "\'$name' + ten + b'\'"\n')) == 1)
    expect("違反: 当たりの token は `$name、`", hits(b'echo "$name' + ten + b'"\n') == [(1, "$name、")])
    expect("違反: ${x:-$y、} の中の $y も当たる", len(hits(b'echo "${x:-$y' + ten + b'}"\n')) == 1)
    # 陰性対照
    expect("波括弧 ${name}、 は当たらない", hits(b'echo "${name}' + ten + b'"\n') == [])
    expect("空白を挟む $name 、 は当たらない", hits(b'echo "$name ' + ten + b'"\n') == [])
    expect("comment 行は当たらない", hits(b"  # $name" + ten + b"\n") == [])
    expect("行末の comment は当たらない", hits(b"echo ok  # $name" + ten + b"\n") == [])
    expect("\\$name、 (escape) は当たらない", hits(b'echo "\\$name' + ten + b'"\n') == [])
    expect("1 行で閉じた '...' の中は当たらない", hits(b"echo '$name" + ten + b"'\n") == [])
    expect("$'...' の中は当たらない", hits(b"echo $'a $name" + ten + b"'\n") == [])
    expect("特殊変数 $1 $$ $? は当たらない", hits(b'echo "$1' + ten + b"$$" + ten + b"$?" + ten + b'"\n') == [])
    expect("$$name の 2 つ目の $ は当たらない", hits(b'echo "$$name' + ten + b'"\n') == [])
    # 行の解析を信用しない側 (報告に倒す)
    expect("行末で引用符が開いたままの行は規約の正規表現で数える",
           len(hits(b"  it's $name" + ten + b' done"\n')) == 1)
    expect("複数行の文字列の途中の行の ` #` を comment と読まない",
           len(hits(b"msg=\"first\n  text #1 $name" + ten + b' end"\n')) == 1)
    # heredoc
    expect("引用符つき heredoc の本文は当たらない",
           hits(b"cat <<'EOF'\n$name" + ten + b"\nEOF\necho \"$b" + ten + b"\"\n") == [(4, "$b、")])
    expect("<<\\EOF と <<\"EOF\" の本文も当たらない",
           hits(b"cat <<\\EOF\n$a" + ten + b"\nEOF\ncat <<\"X\"\n$b" + ten + b"\nX\n") == [])
    expect("引用符の無い heredoc の本文は当たる (# 行も '...' も literal)",
           [h[0] for h in hits(b"cat <<EOF\n# $a" + ten + b"\n'$b" + ten + b"'\nEOF\n")] == [2, 3])
    expect("<<- は tab を外した終わりの行で閉じる",
           [h[0] for h in hits(b"cat <<-'EOF'\n\t$a" + ten + b"\n\tEOF\necho \"$b" + ten + b"\"\n")] == [4])
    expect("算術の << は heredoc と読まない (後ろの行を飲み込まない)",
           [h[0] for h in hits(b"x=$((1 << 2))\ny=$(( a << b ))\necho \"$c" + ten + b"\"\n")] == [3])
    expect("終わりの行が無い <<'X' は heredoc と読まない (後ろの行を literal として飲み込まず報告に倒す)",
           [h[0] for h in hits(b"echo x <<'NOPE'\necho \"$c" + ten + b"\"\n")] == [2])
    # 対象の file
    expect("拡張子 .sh / .bash / .zsh は対象", all(is_shell_path("a" + s, None) for s in (".sh", ".bash", ".zsh")))
    expect("拡張子の無い bash / sh / zsh の shebang は対象",
           all(is_shell_path("hook", h) for h in (b"#!/usr/bin/env bash\n", b"#!/bin/sh\n", b"#!/bin/zsh -f\n",
                                                   b"#!/usr/bin/env -S bash -e\n")))
    expect("python の shebang・拡張子つきの他言語は対象外",
           not is_shell_path("tool", b"#!/usr/bin/env python3\n") and not is_shell_path("a.py", b"#!/bin/sh\n"))

    # 一時 repo: --staged の赤 → 緑、 足した行だけ、 filter つき path、 git repo でない
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
            (Path(td) / "a.sh").write_bytes(b"#!/usr/bin/env bash\nset -u\nold=\"$legacy" + ten + b"\"\n")
            git("add", "a.sh")
            git("commit", "-q", "-m", "init", "--no-verify")
            rc, out = staged()
            expect("--staged: 何も stage していなければ exit 0", rc == 0, out)
            (Path(td) / "a.sh").write_bytes(b"#!/usr/bin/env bash\nset -u\nold=\"$legacy" + ten + b"\"\n"
                                            b"echo \"$name" + ten + b"\"\n")
            git("add", "a.sh")
            rc, out = staged()
            expect("--staged: 足した違反の行で exit 1 + BLOCK 見出し", rc == 1 and BLOCK_HEADING in out, out)
            expect("--staged: 足した行だけを出す (既存の行 3 は出さない)", "a.sh:4:" in out and "a.sh:3:" not in out, out)
            expect("--staged: 直し方 ${name} を出す", "${name}" in out, out)
            rc, out = staged({ENV_SKIP: "0"})
            expect("--staged: escape hatch で exit 0", rc == 0, out)
            (Path(td) / "a.sh").write_bytes(b"#!/usr/bin/env bash\nset -u\nold=\"$legacy" + ten + b"\"\n"
                                            b"echo \"${name}" + ten + b"\"\n")
            git("add", "a.sh")
            rc, out = staged()
            expect("--staged: ${name} に直すと exit 0 (赤 → 緑)", rc == 0, out)
            git("reset", "-q", "--hard")
            (Path(td) / "hook").write_bytes(b"#!/bin/sh\necho \"$x" + ten + b"\"\n")
            (Path(td) / "tool.py").write_bytes(b"#!/usr/bin/env python3\nprint(\"$x" + ten + b"\")\n")
            git("add", "hook", "tool.py")
            rc, out = staged()
            expect("--staged: 拡張子の無い shebang の file は検査、 .py は対象外",
                   rc == 1 and "hook:2:" in out and "tool.py" not in out, out)
            git("reset", "-q", "--hard")
            git("clean", "-qfd")
            (Path(td) / "vendor" / "sub").mkdir(parents=True)
            git("update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",vendor/sub")
            rc, out = staged()
            expect("--staged: submodule (gitlink) は読まない (「検査が走っていない」 にしない)",
                   rc == 0 and NOT_RUN not in out, out)
            git("rm", "-q", "--cached", "vendor/sub")
            shutil.rmtree(Path(td) / "vendor")
            # clean / smudge = rot13 (index の blob は別物になる = git show で読むと token が変わる)
            (Path(td) / ".gitattributes").write_text("*.rot.sh filter=rot\n")
            git("config", "filter.rot.clean", "tr 'A-Za-z' 'N-ZA-Mn-za-m'")
            git("config", "filter.rot.smudge", "tr 'A-Za-z' 'N-ZA-Mn-za-m'")
            (Path(td) / "c.rot.sh").write_bytes(b"echo \"$name" + ten + b"\"\n")
            git("add", ".gitattributes", "c.rot.sh")
            rc, out = staged()
            expect("--staged: filter つき path は平文で読む (token が $name のまま)",
                   rc == 1 and "$name、" in out and "$anzr" not in out, out)
        with tempfile.TemporaryDirectory() as td2:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--staged"], cwd=td2, capture_output=True,
                               check=False, env=dict(os.environ, GIT_CEILING_DIRECTORIES=td2))
            err = r.stderr.decode("utf-8", "replace")
            expect("--staged: git repo でなければ exit 3 + 1 行 (違反の 1 と区別)", r.returncode == 3 and NOT_RUN in err,
                   err)
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--staged"], cwd=td2, capture_output=True,
                               check=False, env=dict(os.environ, PATH=os.path.join(td2, "no-bin")))
            err = r.stderr.decode("utf-8", "replace")
            expect("--staged: 内部の例外 (git が PATH に無い) は exit 3 + 1 行 (traceback の rc 1 にしない)",
                   r.returncode == 3 and NOT_RUN in err and "Traceback" not in err, err)
            p = Path(td2) / "x.sh"
            p.write_bytes(b"echo \"$v" + ten + b"\"\n")
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--paths", str(p)], capture_output=True,
                               check=False)
            expect("--paths: 当たりで exit 1", r.returncode == 1 and b"x.sh:1:" in r.stdout, repr(r.stdout))
            p.write_bytes(b"echo \"${v}" + ten + b"\"\n")
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--paths", str(p)], capture_output=True,
                               check=False)
            expect("--paths: 直すと exit 0", r.returncode == 0, repr(r.stdout))

    # 実物の bash: 当たりの形は UTF-8 の locale で set -u なら落ち、 ${var} の形は通る (述語が実害と対応すること)
    bash = "/bin/bash"
    probe = subprocess.run([bash, "-c", 'echo "$BASH_VERSION"'], capture_output=True, check=False) \
        if os.path.exists(bash) else None
    locales = subprocess.run(["locale", "-a"], capture_output=True, check=False).stdout.decode("utf-8", "replace") \
        if shutil.which("locale") else ""
    loc = next((x for x in ("en_US.UTF-8", "ja_JP.UTF-8") if x in locales.split()), None)
    if probe is None or not probe.stdout.startswith(b"3.2") or loc is None:
        print("  SKIP 実物の bash 3.2 の確認 (/bin/bash が 3.2 でない、 または UTF-8 の locale が無い)")
    else:
        with tempfile.TemporaryDirectory() as td3:
            bad = Path(td3) / "bad.sh"
            good = Path(td3) / "good.sh"
            bad.write_bytes(b"set -u\nname=VAL\necho \"$name" + ten + b"\"\n")
            good.write_bytes(b"set -u\nname=VAL\necho \"${name}" + ten + b"\"\n")
            env_u = dict(os.environ, LC_ALL=loc)
            rb = subprocess.run([bash, str(bad)], capture_output=True, check=False, env=env_u)
            rg = subprocess.run([bash, str(good)], capture_output=True, check=False, env=env_u)
            rc_ = subprocess.run([bash, str(bad)], capture_output=True, check=False, env=dict(os.environ, LC_ALL="C"))
            expect("bash 3.2 + %s: 当たりの形は set -u で落ちる" % loc,
                   rb.returncode != 0 and b"unbound variable" in rb.stderr, repr(rb.stderr))
            expect("bash 3.2 + %s: ${var} の形は値を出す" % loc,
                   rg.returncode == 0 and rg.stdout == b"VAL" + ten + b"\n", repr(rg.stdout))
            expect("bash 3.2 + C locale: 当たりの形も通る (= 手元で通ることは反証にならない)",
                   rc_.returncode == 0, repr(rc_.stderr))
            expect("検出器: bad.sh は当たり、 good.sh は当たらない",
                   len(scan_bytes(bad.read_bytes())) == 1 and scan_bytes(good.read_bytes()) == [])

    print("check-unbraced-multibyte-var selftest:", "ALL PASS" if not fails else "FAIL %s" % fails)
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
    ap.add_argument("--strict", action="store_true", help="--tree で当たりがあれば exit 1")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.staged:
        return run_staged(args.repo)
    if args.paths:
        return run_paths(args.paths)
    return run_tree(args.tree, args.strict)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # 故障を違反 (1) と同じ値にしない
        msg = str(exc).splitlines()[0][:200] if str(exc) else ""
        print("%s (内部の例外 %s: %s)" % (NOT_RUN, type(exc).__name__, msg), file=sys.stderr)
        sys.exit(3)
