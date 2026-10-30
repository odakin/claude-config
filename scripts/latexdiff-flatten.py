#!/usr/bin/env python3
"""Flatten one side of a multi-file LaTeX manuscript for latexdiff (\\input / \\include replaced by the text).

Why: latexdiff compares the two files it is given.  A sub-file pulled in by ``\\input`` is
then one unchanged command on both sides, so a change inside it gets no markup, and at
compile time both sides read the working-tree sub-file.  The PDF looks finished and says
nothing changed.  ``latexdiff --flatten`` needs the old tree on disk and runs inside
latexdiff, after the steps that must see the text (the wrapper expansion and the
safe-command list), so the two sides are flattened here first, the same way:
the old side reads sub-files with ``git show REV:PATH``, the new side from the working tree.
``scripts/latexdiff-review-snapshot.sh`` calls this; repo-specific diff scripts can too.

What it does (conventions/latex.md#latexdiff-multi-file):
- ``\\input{x}``, ``\\input x`` and ``\\include{x}`` are replaced by the file, recursively.  As in
  TeX the path is relative to the main file's directory, also inside a sub-file, and
  ``x.tex`` is tried before ``x``.  ``\\include`` keeps its ``\\clearpage`` on both sides.
- Comments go: a comment-only line is dropped, a trailing comment is cut to the bare ``%``
  (which still swallows the line end).  So a commented-out ``\\input`` is not expanded and old
  comments do not show up as changes.  ``\\%`` is not a comment, ``\\\\%`` is.
- ``\\endinput`` ends that file.  verbatim / comment / lstlisting / minted blocks are left as they are.
- A file that is not there is left as a command with a warning (it can be generated, such
  as a table written at build time).  Stops: an \\input cycle (exit 2); ``\\subfile`` and
  ``\\import`` (exit 3), which are not expanded here and would stay unmarked.
- Not handled: ``\\includeonly`` (everything is included) and a path built from a macro
  (reported as missing).

Usage
    latexdiff-flatten.py IN.tex OUT.tex --main REL [--repo DIR] [--rev REV] [--search DIR]... [--list FILE]
        IN     the main file's text (OUT may be the same file)
        --main the main file's path from the repo root (sets the directory that \\input is relative to)
        --rev  read sub-files with git show REV:PATH instead of the working tree
        --search  look here first, relative to the main file's directory (a processed copy)
        --list write the repo-relative files that were read, one per line
    latexdiff-flatten.py --has-inputs IN.tex      exit 0 if IN has \\input or \\include outside comments
    latexdiff-flatten.py --selftest
"""
from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

ENC = {"encoding": "utf-8", "errors": "surrogateescape"}
# an even number of backslashes may precede: \\input is a line break followed by the word input
INPUT_RE = re.compile(r"(?<!\\)((?:\\\\)*)\\(input|include)(?![A-Za-z@])\s*(?:\{([^{}]+)\}|([^\s{}\\%]+))")
UNSUPPORTED_RE = re.compile(
    r"(?<!\\)(?:\\\\)*\\(subfile|subfileinclude|import|subimport|includefrom|subincludefrom|inputfrom|subinputfrom)"
    r"(?![A-Za-z@])\s*\{")
ENDINPUT_RE = re.compile(r"(?<!\\)(?:\\\\)*\\endinput(?![A-Za-z@])")
VERBATIM_RE = re.compile(r"\\begin\{(verbatim\*?|comment|lstlisting|minted)\}")


class Stop(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def comment_at(line: str) -> int:
    """Index of the first real % in line, or -1."""
    i = 0
    while i < len(line):
        if line[i] == "\\":
            i += 2
        elif line[i] == "%":
            return i
        else:
            i += 1
    return -1


def code_lines(text: str):
    """The code part of each line outside verbatim blocks."""
    verb = None
    for line in text.split("\n"):
        if verb:
            if f"\\end{{{verb}}}" in line:
                verb = None
            continue
        cut = comment_at(line)
        code = line if cut < 0 else line[:cut]
        m = VERBATIM_RE.search(code)
        if m and f"\\end{{{m.group(1)}}}" not in code:
            verb = m.group(1)
            continue
        yield code


def has_inputs(text: str) -> bool:
    return any(INPUT_RE.search(code) for code in code_lines(text))


class Flattener:
    def __init__(self, read: Callable[[str], Optional[str]], main_dir: str) -> None:
        self.read, self.main_dir = read, main_dir
        self.used: list[str] = []
        self.missing: list[str] = []

    def resolve(self, name: str):
        for cand in (name + ".tex", name):
            rel = posixpath.normpath(posixpath.join(self.main_dir, cand))
            text = self.read(rel)
            if text is not None:
                return rel, text
        return None, None

    def one(self, cmd: str, name: str, stack: tuple[str, ...]) -> Optional[str]:
        rel, text = self.resolve(name)
        if rel is None:
            self.missing.append(name)
            return None
        if rel in stack:
            raise Stop(2, f"\\input の循環: {' -> '.join(stack + (rel,))}")
        if rel not in self.used:
            self.used.append(rel)
        body = self.expand(text[:-1] if text.endswith("\n") else text, stack + (rel,))
        return f"\\clearpage\n{body}\n\\clearpage" if cmd == "include" else body

    def expand_code(self, code: str, stack: tuple[str, ...]) -> str:
        out, pos = [], 0
        for m in INPUT_RE.finditer(code):
            body = self.one(m.group(2), (m.group(3) or m.group(4)).strip(), stack)
            if body is None:
                continue  # left as the command
            out += [code[pos:m.start()], m.group(1), body]
            pos = m.end()
            if code[pos:].strip():
                out.append("\n")  # the sub-file's last line may end in a bare %
        return "".join(out) + code[pos:]

    def expand(self, text: str, stack: tuple[str, ...]) -> str:
        out, verb = [], None
        for line in text.split("\n"):
            if verb:
                out.append(line)
                if f"\\end{{{verb}}}" in line:
                    verb = None
                continue
            cut = comment_at(line)
            code = line if cut < 0 else line[:cut]
            if cut >= 0 and not code.strip():
                continue
            m = VERBATIM_RE.search(code)
            if m and f"\\end{{{m.group(1)}}}" not in code:
                verb = m.group(1)
                out.append(line)
                continue
            bad = UNSUPPORTED_RE.search(code)
            if bad:
                raise Stop(3, f"\\{bad.group(1)} は平らにできない (sub-file の変更に印が付かない): {code.strip()}")
            end = ENDINPUT_RE.search(code)
            if end:
                code = code[:end.start()]
            new = self.expand_code(code, stack)
            out.append(new + ("%" if cut >= 0 and not end else ""))
            if end:
                break
        return "\n".join(out)


def reader(repo: Path, rev: Optional[str], search: list[str], main_dir: str) -> Callable[[str], Optional[str]]:
    def read(rel: str) -> Optional[str]:
        for s in search:
            p = Path(s) / posixpath.relpath(rel, main_dir or ".")
            if p.is_file():
                return p.read_text(**ENC)
        if rev:
            r = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{rel}"], capture_output=True)
            return r.stdout.decode(**ENC) if r.returncode == 0 else None
        p = repo / rel
        return p.read_text(**ENC) if p.is_file() else None
    return read


def flatten(text: str, main: str, read: Callable[[str], Optional[str]]) -> Flattener:
    f = Flattener(read, posixpath.dirname(main))
    f.result = f.expand(text, (posixpath.normpath(main),))  # type: ignore[attr-defined]
    return f


def selftest() -> int:
    bad = 0

    def check(cond: bool, what: str) -> None:
        nonlocal bad
        if not cond:
            bad += 1
            print(f"FAIL: {what}")

    def run(files: dict[str, str], main: str = "main.tex") -> Flattener:
        return flatten(files[main], main, files.get)

    f = run({"main.tex": "A\n\\input{a}\nB\n", "a.tex": "x\n"})
    check(f.result == "A\nx\nB\n", f"a sub-file adds no blank line: {f.result!r}")  # type: ignore[attr-defined]
    check(f.used == ["a.tex"], "the list of files read")
    r = run({"main.tex": "\\input{sec/a}", "sec/a.tex": "\\input{sec/b}\n", "sec/b.tex": "deep\n"}).result  # type: ignore[attr-defined]
    check(r == "deep", f"a nested path is relative to the main file: {r!r}")
    r = run({"paper/main.tex": "\\input{a}", "paper/a.tex": "in dir\n"}, "paper/main.tex").result  # type: ignore[attr-defined]
    check(r == "in dir", f"a main file in a sub-directory: {r!r}")
    r = run({"main.tex": "\\input a.tex\n\\input{b.tikz}\n", "a.tex": "1\n", "b.tikz": "2\n"}).result  # type: ignore[attr-defined]
    check(r == "1\n2\n", f"the brace-less form and a file with another extension: {r!r}")
    r = run({"main.tex": "\\include{a}\n", "a.tex": "x\n"}).result  # type: ignore[attr-defined]
    check(r == "\\clearpage\nx\n\\clearpage\n", f"\\include keeps \\clearpage: {r!r}")
    f = run({"main.tex": "% \\input{ghost}\nkeep % \\input{ghost}\n100\\% sure\nline\\\\% cut\n\\inputencoding{utf8}\n"})
    check(f.used == [] and not f.missing, "a commented-out \\input is not read")
    check(f.result == "keep %\n100\\% sure\nline\\\\%\n\\inputencoding{utf8}\n",  # type: ignore[attr-defined]
          f"comments go, \\% stays, \\\\% is a comment: {f.result!r}")  # type: ignore[attr-defined]
    r = run({"main.tex": "\\input{a}\nB\n", "a.tex": "x\n\\endinput\nnever\n"}).result  # type: ignore[attr-defined]
    check(r == "x\n\nB\n", f"\\endinput ends the sub-file: {r!r}")
    r = run({"main.tex": "\\input{a} tail\n", "a.tex": "x % c\n"}).result  # type: ignore[attr-defined]
    check(r == "x %\n tail\n", f"text after \\input survives a trailing %: {r!r}")
    r = run({"main.tex": "line\\\\input{a}\n"}).result  # type: ignore[attr-defined]
    check(r == "line\\\\input{a}\n", f"\\\\ followed by the word input is not a command: {r!r}")
    r = run({"main.tex": "\\begin{verbatim}\n\\input{a} % k\n\\end{verbatim}\n", "a.tex": "x\n"}).result  # type: ignore[attr-defined]
    check("\\input{a} % k" in r, f"verbatim is left alone: {r!r}")
    f = run({"main.tex": "\\input{gen}\n"})
    check(f.result == "\\input{gen}\n" and f.missing == ["gen"], "a missing file stays as the command")  # type: ignore[attr-defined]
    check(has_inputs("x\n\\input{a}\n") and not has_inputs("% \\input{a}\nx\n"), "--has-inputs")
    for files, code, what in (
            ({"main.tex": "\\input{a}", "a.tex": "\\input{main}\n"}, 2, "a cycle stops"),
            ({"main.tex": "\\subfile{a}\n"}, 3, "\\subfile stops"),
            ({"main.tex": "\\import{d/}{a}\n"}, 3, "\\import stops")):
        try:
            run(files)
            check(False, what)
        except Stop as e:
            check(e.code == code, f"{what}: exit {e.code}")

    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "r"
        repo.mkdir()
        git = ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "-c", "user.name=t",
               "-c", "user.email=t@example.invalid"]
        (repo / "main.tex").write_text("\\input{a}\n", encoding="utf-8")
        (repo / "a.tex").write_text("old\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-qm", "base"], check=True)
        (repo / "a.tex").write_text("new\n", encoding="utf-8")
        main = (repo / "main.tex").read_text(encoding="utf-8")
        check(flatten(main, "main.tex", reader(repo, "HEAD", [], "")).result == "old\n",  # type: ignore[attr-defined]
              "the old side reads the revision")
        check(flatten(main, "main.tex", reader(repo, None, [], "")).result == "new\n",  # type: ignore[attr-defined]
              "the new side reads the working tree")
        copy = Path(d) / "copy"
        copy.mkdir()
        (copy / "a.tex").write_text("copy\n", encoding="utf-8")
        check(flatten(main, "main.tex", reader(repo, None, [str(copy)], "")).result == "copy\n",  # type: ignore[attr-defined]
              "--search comes first")
    print("selftest: FAIL" if bad else "selftest: OK")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--main")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--rev")
    ap.add_argument("--search", action="append", default=[])
    ap.add_argument("--list")
    ap.add_argument("--has-inputs", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.has_inputs:
        return 0 if has_inputs(Path(a.files[0]).read_text(**ENC)) else 1
    if len(a.files) != 2 or not a.main:
        ap.error("IN.tex OUT.tex and --main are required")
    text = Path(a.files[0]).read_text(**ENC)
    read = reader(Path(a.repo), a.rev, a.search, posixpath.dirname(a.main))
    try:
        f = flatten(text, a.main, read)
    except Stop as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return e.code
    Path(a.files[1]).write_text(f.result, **ENC)  # type: ignore[attr-defined]
    for name in f.missing:
        side = a.rev or "作業 tree"
        print(f"WARN: \\input{{{name}}} は {side} に無い = 命令のまま残す (組版は作業 tree の file を読む)", file=sys.stderr)
    if a.list:
        Path(a.list).write_text("".join(r + "\n" for r in f.used), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
