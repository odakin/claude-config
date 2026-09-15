#!/usr/bin/env python3
"""staged 追加行を読む helper (= pre-commit の warn 検査が binary を含む commit で落ちないように)。

由来 (2026-09-15): `git diff --cached` を `text=True` で読む warn 検査が、 staged に binary
(PDF など) を含む commit で UnicodeDecodeError を出して落ちた。 hook は warn-only で commit は
通るので、 **同じ commit の text file の検査も黙って走らなくなる** (= fail-open が沈黙になる)。
git の binary 判定は「先頭 8KB に NUL があるか」 なので、 NUL を含まない binary と、 textconv
(git-crypt 等) で平文に戻した binary は、 どちらも text として diff に出る。 --numstat の
`-\t-` だけでは見分けられない。

∴ 出力は bytes で受け取り、 file ごとの section を UTF-8 として厳密に decode する。 decode
できない section (または NUL を含む section) は binary として飛ばし、 他の file は読む。
textconv は切らない (git-crypt で暗号化された text file を平文で検査するため)。

使い方:

    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from staged_diff import staged_added_lines
    for path, lineno, text in staged_added_lines(skip=lambda p: p.endswith("self.py")):
        ...

python3 staged_diff.py で selftest (一時 repo に binary + text を stage して確かめる)。
"""
from __future__ import annotations

import re
import subprocess
from typing import Callable, List, Optional, Tuple

DIFF_ARGS = ["diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACM"]
_HUNK = re.compile(rb"^@@ -\d+(?:,\d+)? \+(\d+)")

Added = Tuple[str, int, str]


def _target_path(line: bytes) -> Optional[str]:
    """`+++ b/path` (core.quotepath=false でも特殊文字は "..." で囲まれる) から path を取り出す。"""
    name = line[4:].rstrip(b"\r\n").decode("utf-8", "replace")
    if len(name) >= 2 and name[0] == name[-1] == '"':
        name = name[1:-1]
    if name == "/dev/null":
        return None
    return name[2:] if name.startswith(("a/", "b/")) else name


def parse_added_lines(raw: bytes, skip: Optional[Callable[[str], bool]] = None) -> Tuple[List[Added], List[str]]:
    """unified diff (bytes) → ([(path, new-lineno, text)], [binary として飛ばした path])。"""
    added: List[Added] = []
    binary: List[str] = []
    sections: List[List[bytes]] = []
    for line in raw.split(b"\n"):
        if line.startswith(b"diff --git ") or not sections:
            sections.append([])
        sections[-1].append(line)
    for section in sections:
        path: Optional[str] = None
        body: List[Tuple[int, bytes]] = []
        lineno = 0
        in_hunk = False
        for line in section:
            if line.startswith(b"+++ ") and not in_hunk:
                # 追加行 "++ x" も diff では "+++ x" になるので、 header は最初の @@ より前だけ
                path = _target_path(line)
            elif line.startswith(b"@@"):
                in_hunk = True
                m = _HUNK.match(line)
                lineno = int(m.group(1)) if m else 0
            elif in_hunk and path is not None and line.startswith(b"+"):
                body.append((lineno, line[1:]))
                lineno += 1
        if path is None or not body or (skip and skip(path)):
            continue
        try:
            if any(b"\0" in chunk for _, chunk in body):
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "NUL byte")
            decoded = [(n, chunk.decode("utf-8").rstrip("\r")) for n, chunk in body]
        except UnicodeDecodeError:
            binary.append(path)
            continue
        added.extend((path, n, text) for n, text in decoded)
    return added, binary


def staged_added_lines(cwd=None, skip: Optional[Callable[[str], bool]] = None, timeout: int = 20) -> List[Added]:
    """staged 追加行 (text file だけ)。 git が走らない / timeout = 空 (warn 検査は fail-open)。"""
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", *DIFF_ARGS],
            cwd=cwd, capture_output=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_added_lines(result.stdout, skip)[0]


def selftest() -> int:
    import os
    import tempfile

    fails = []

    def expect(label, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        if not cond:
            fails.append(label)

    raw = (b"diff --git a/x.bin b/x.bin\n+++ b/x.bin\n@@ -0,0 +1 @@\n+%PDF \xc5\xd0\n"
           b"diff --git a/y.md b/y.md\n+++ b/y.md\n@@ -0,0 +1,2 @@\n+one\n+\xe4\xba\x8c\n")
    added, binary = parse_added_lines(raw)
    expect("invalid UTF-8 section is skipped, the text section is kept",
           added == [("y.md", 1, "one"), ("y.md", 2, "二")] and binary == ["x.bin"])
    added, _ = parse_added_lines(raw, skip=lambda p: p == "y.md")
    expect("skip callback drops a path", added == [])
    added, binary = parse_added_lines(b"diff --git a/z b/z\n+++ b/z\n@@ -0,0 +1 @@\n+a\0b\n")
    expect("NUL byte marks a section as binary", added == [] and binary == ["z"])
    added, _ = parse_added_lines(b"diff --git a/w b/w\n--- /dev/null\n+++ b/w\n@@ -0,0 +1,2 @@\n+++ kept\n+x\n")
    expect("an added line that starts with '++' is content, not a header",
           added == [("w", 1, "++ kept"), ("w", 2, "x")])
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        run = lambda *a: subprocess.run(["git", *a], cwd=td, env=env, capture_output=True, check=False)
        if run("init", "-q").returncode != 0:
            print("SKIP: git not available")
            return 0
        with open(os.path.join(td, "doc.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4\n%\xc5\xd0\xe2\xe3\nstream \xff\xfe\n")
        os.makedirs(os.path.join(td, "サブ"))
        with open(os.path.join(td, "サブ", "note.md"), "w", encoding="utf-8") as fh:
            fh.write("first\n日本語\n")
        run("add", "-A")
        got = staged_added_lines(cwd=td)
        expect("real git: a binary file does not hide the text file in the same commit",
               ("サブ/note.md", 2, "日本語") in got and all(p != "doc.pdf" for p, _, _ in got))
    print("staged_diff selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
