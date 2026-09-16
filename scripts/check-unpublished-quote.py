#!/usr/bin/env python3
r"""check-unpublished-quote.py — Stop verbatim text of unpublished documents (your private manuscripts) from being committed to a public repo: matches quoted spans and long prose runs in the staged added lines or a commit message against hashed word shingles of the declared sources; --selftest.

Why (2026-09-13): examples in public convention docs quoted unpublished manuscripts, three times in one week,
although a written rule forbade it (claude-config CLAUDE.md#non-identifier-content-leak). Every existing gate
looks for identifiers (names, e-mail, repo names, paths) or for Japanese text of local-only repos, so English
manuscript sentences passed all of them. This gate covers the verbatim part only: a paraphrase of an
unpublished result still passes, and the written rule still applies to it.

Two detectors, calibrated by replaying the public repos' history (--replay):
  quoted span  = text inside `backticks`, "double quotes" or “curly quotes” with >= QUOTE_MIN_WORDS words and
                 >= QUOTE_MIN_CONTENT content words, every QUOTE_K-word window of which occurs in a source.
                 The leaked examples were short quotations of this kind.
  prose run    = PROSE_K consecutive content words (>= 3 letters, not a function word) that occur in a source,
                 outside fenced code blocks. Catches a copied sentence or paragraph without quote marks.
Text is normalised first: LaTeX comments, math, preamble, citation/label keys and control sequences are removed,
Japanese text breaks a run. Shingles present in REPO_DF_MAX or more top-level dirs are boilerplate and ignored.

Where it runs: public-precommit-runner.sh (staged) and commit-msg-leak-guard-runner.sh (message), and only in
repos with .claude/public-repo.marker. Private repos are never checked (they quote their own manuscripts).

Sources = a config file (the runners pass the personal layer's unpublished-sources.txt; or --config, or
$CLAUDE_UNPUBLISHED_SOURCES, or ~/.claude/unpublished-sources.txt). One directive per line, `#` = comment:
    discover: ~/Claude .tex      files with this suffix under the non-public top-level dirs of ~/Claude
    include: ~/Dropbox/drafts/**/*.tex    extra sources (glob, ** allowed)
    exclude: */published-articles/*       fnmatch on the absolute path (published or third-party text)
No config, or no readable source = not armed = exit 0 (fail-open). `--check-wiring` says which, via canaries.
The index is cached per source file under ~/.cache/claude-unpublished-index (hashes only, never text).

Exit: 0 = nothing matched or not armed / 1 = verbatim unpublished text in a public commit / 3 = internal error
(the runners do not block on 3). The matched text is never printed, only file, line, source and kind.
Bypass once: CLAUDE_UNPUBLISHED_GUARD=0 git commit ... (e.g. a quote of an already published version).

Usage:
  check-unpublished-quote.py [--config PATH]                   staged added lines of the current repo
  check-unpublished-quote.py --message-file PATH [--config PATH]
  check-unpublished-quote.py --check-wiring [--through-hooks] [--config PATH]
                                        armed? + canaries through the real index; --through-hooks also commits the
                                        canaries through the installed pre-commit and commit-msg hooks of a temp
                                        public repo (the hooks use the personal layer the runners resolve)
  check-unpublished-quote.py --scan-tree REPO [--config PATH]   audit every tracked text file of a repo as it is now
                                        (the gate itself only sees added lines; this is the inventory of older text)
  check-unpublished-quote.py --replay REPO [--max-commits N] [--prose-k K] [--quote-min N] [--config PATH]
  check-unpublished-quote.py --selftest
"""
from __future__ import annotations

import argparse
import array
import bisect
import fnmatch
import glob
import hashlib
import heapq
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:  # 公刊済みの書誌の行は対象外 (lib/published_metadata.py)。 無ければ外さない = 鳴る側
    from published_metadata import metadata_line_numbers as _published_lines, applies_to as _published_applies
except ImportError:  # pragma: no cover
    _published_lines = lambda path, text: set()  # noqa: E731
    _published_applies = lambda path: False  # noqa: E731
try:  # blob は worktree に出したときの中身で読む = git-crypt の暗号化 path も平文 (lib/git_blob.py)
    from git_blob import read_blob_text as _read_blob_text
except ImportError:  # pragma: no cover
    def _read_blob_text(spec, cwd=None):
        r = subprocess.run(["git", "show", spec], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else None

PROSE_K = 6
QUOTE_K = 5
QUOTE_MIN_WORDS = 5
QUOTE_MIN_CONTENT = 3
REPO_DF_MAX = 3
INDEX_VERSION = 4
MARKER = Path(".claude") / "public-repo.marker"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "claude-unpublished-index"
POINTER = Path.home() / ".claude" / "unpublished-sources.txt"

STOP = frozenset("""
the and for with that this from are was were which its into than then have has had not but can may one two
all any each only also such both more most same other where when what who how why our their these those there
here will would should could been being over under between through per via upon about above below after before
while whose them they his her him she you your out off own very just even much many some well does did done
""".split())
CJK = "\u3000-\u303f\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef"
TOKEN_RE = re.compile(rf"(?P<cjk>[{CJK}]{{2,}})|(?P<w>[A-Za-z]+)")
MATH_ENVS = "equation|align|gather|multline|eqnarray|displaymath|alignat|flalign|figure|table|tabular|thebibliography|tikzpicture"
MATH_BLOCK_RE = re.compile(rf"\\begin\{{({MATH_ENVS})\*?\}}.*?\\end\{{\1\*?\}}", re.S)
DISPLAY_RE = re.compile(r"\\\[.*?\\\]|\\\(.*?\\\)|\$\$.*?\$\$", re.S)
INLINE_MATH_RE = re.compile(r"(?<!\\)\$[^$\n]*(?<!\\)\$")
KEY_CMD_RE = re.compile(r"\\(?:cite[a-z]*|[cC]ref|labelcref|eqref|ref|autoref|pageref|label|input|include|"
                        r"includegraphics|url|href|bibliography|bibliographystyle|usepackage|documentclass)"
                        r"\*?(?:\[[^\]]*\])*\{[^}]*\}")
CS_RE = re.compile(r"\\[A-Za-z@]+\*?")
COMMENT_RE = re.compile(r"(?<!\\)%.*")
ACK_RE = re.compile(r"\\(?:(?:sub)*section\*?\{Acknowledge?ments?\}|begin\{acknowledge?ments?\}|acknowledge?ments?\b)"
                    r".*?(?=\\(?:sub)*section|\\appendix|\\bibliography|\\begin\{thebibliography\}|\\end\{document\}|$)", re.S | re.I)
QUOTE_RE = re.compile(r"`([^`\n]{8,400})`|\"([^\"\n]{8,400})\"|\u201c([^\u201d\n]{8,400})\u201d")
BREAK = None
FAMILIES = ("prose", "quote")


# ----------------------------------------------------------------------------- text -> word stream
def normalize(text: str, latex: bool) -> str:
    if latex:
        m = re.search(r"\\begin\{document\}", text)
        if m:
            text = text[m.end():]
        text = COMMENT_RE.sub("", text)
        text = ACK_RE.sub(" ", text)
        text = MATH_BLOCK_RE.sub(" ", text)
    text = DISPLAY_RE.sub(" ", text)
    text = INLINE_MATH_RE.sub(" ", text)
    text = KEY_CMD_RE.sub(" ", text)
    return CS_RE.sub(" ", text)


def is_content(w: str) -> bool:
    return len(w) >= 3 and w not in STOP


def tokens(text: str, latex: bool = False, family: str = "prose") -> list:
    out = []
    for m in TOKEN_RE.finditer(normalize(text, latex)):
        if m.group("cjk"):
            if out and out[-1] is not BREAK:
                out.append(BREAK)
            continue
        w = m.group("w").lower()
        if family == "quote" or is_content(w):
            out.append(w)
    return out


def shingle_hash(words, family: str = "prose") -> int:
    return int.from_bytes(hashlib.blake2b((family + ":" + " ".join(words)).encode(), digest_size=8).digest(), "big")


def shingles(stream, k: int, family: str = "prose"):
    """Yield (start index, hash) for every k-window without a BREAK."""
    run = []
    for i, t in enumerate(stream):
        if t is BREAK:
            run = []
            continue
        run.append(i)
        if len(run) >= k:
            s = run[-k]
            yield s, shingle_hash(stream[s:i + 1], family)


# ----------------------------------------------------------------------------- config and sources
def read_config(path):
    if not path:
        return None
    p = Path(os.path.expanduser(str(path)))
    if not p.is_file():
        return None
    cfg = {"discover": [], "include": [], "exclude": []}
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        if key in cfg and val:
            cfg[key].append(val)
    return cfg


def resolve_config(arg=None, env=None):
    env = os.environ if env is None else env
    for cand in (arg, env.get("CLAUDE_UNPUBLISHED_SOURCES"), str(POINTER)):
        cfg = read_config(cand)
        if cfg is not None:
            return cfg, cand
    return None, None


def source_files(cfg) -> list:
    found = set()
    for d in cfg["discover"]:
        parts = d.split()
        root = Path(os.path.expanduser(parts[0]))
        suffixes = tuple(parts[1:]) or (".tex",)
        if not root.is_dir():
            continue
        for top in sorted(root.iterdir()):
            if not top.is_dir() or top.name.startswith(".") or (top / MARKER).exists():
                continue
            for dp, dns, fns in os.walk(top):
                dns[:] = [x for x in dns if x not in (".git", "node_modules", "__pycache__", ".venv", "worktrees")]
                for fn in fns:
                    if fn.endswith(suffixes):
                        found.add(str(Path(dp) / fn))
    for g in cfg["include"]:
        for f in glob.glob(os.path.expanduser(g), recursive=True):
            if os.path.isfile(f):
                found.add(os.path.abspath(f))
    excl = [os.path.expanduser(x) for x in cfg["exclude"]]
    return sorted(f for f in found if not any(fnmatch.fnmatch(f, x) for x in excl))


def repo_label(path: str, cfg) -> str:
    for d in cfg["discover"]:
        root = Path(os.path.expanduser(d.split()[0]))
        try:
            return str(Path(path).relative_to(root))
        except ValueError:
            pass
    return path.replace(str(Path.home()), "~", 1)


def top_dir(path: str, cfg) -> str:
    return repo_label(path, cfg).split(os.sep, 1)[0]


# ----------------------------------------------------------------------------- index (cached hashes)
class Index:
    def __init__(self, cfg, prose_k=PROSE_K, cache_dir=CACHE_DIR, df_max=REPO_DF_MAX):
        self.cfg, self.cache, self.df_max = cfg, Path(cache_dir), df_max
        self.k = {"prose": prose_k, "quote": QUOTE_K}
        self.files = source_files(cfg)
        self.per_file = {f: {} for f in FAMILIES}
        self.union = {f: array.array("Q") for f in FAMILIES}

    def _file_hashes(self, path: str, family: str) -> array.array:
        st = os.stat(path)
        key = hashlib.sha1(f"{INDEX_VERSION}:{family}:{self.k[family]}:{path}".encode()).hexdigest()
        meta_p, bin_p = self.cache / f"{key}.json", self.cache / f"{key}.bin"
        stamp = [st.st_size, st.st_mtime_ns]
        if meta_p.is_file() and bin_p.is_file():
            try:
                if json.loads(meta_p.read_text())["stamp"] == stamp:
                    a = array.array("Q")
                    a.frombytes(bin_p.read_bytes())
                    return a
            except (ValueError, KeyError, OSError):
                pass
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        stream = tokens(text, latex=path.endswith(".tex"), family=family)
        a = array.array("Q", sorted({h for _, h in shingles(stream, self.k[family], family)}))
        self.cache.mkdir(parents=True, exist_ok=True)
        bin_p.write_bytes(a.tobytes())
        meta_p.write_text(json.dumps({"stamp": stamp}))
        return a

    def _manifest(self) -> str:
        stamps = []
        for f in self.files:
            try:
                st = os.stat(f)
            except OSError:
                continue
            stamps.append([f, st.st_size, st.st_mtime_ns])
        blob = json.dumps([INDEX_VERSION, self.k, self.df_max, stamps]).encode()
        return hashlib.sha1(blob).hexdigest()

    def build(self):
        manifest = self._manifest()
        cached = {fam: self.cache / f"union-{fam}-{manifest}.bin" for fam in FAMILIES}
        if all(p.is_file() for p in cached.values()):
            for fam, p in cached.items():
                a = array.array("Q")
                a.frombytes(p.read_bytes())
                self.union[fam] = a
            return self          # per-file arrays are loaded only when a hit needs its source (sources_of)
        for family in FAMILIES:
            by_top = {}
            for f in self.files:
                try:
                    a = self._file_hashes(f, family)
                except OSError:
                    continue
                self.per_file[family][f] = a
                by_top.setdefault(top_dir(f, self.cfg), set()).update(a)
            out, prev, count = array.array("Q"), None, 0
            for h in heapq.merge(*[sorted(s) for s in by_top.values()]):
                if h == prev:
                    count += 1
                    continue
                if prev is not None and count < self.df_max:
                    out.append(prev)
                prev, count = h, 1
            if prev is not None and count < self.df_max:
                out.append(prev)
            self.union[family] = out
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            for old in self.cache.glob("union-*.bin"):
                old.unlink()
            for fam, p in cached.items():
                p.write_bytes(self.union[fam].tobytes())
        except OSError:
            pass
        return self

    def armed(self) -> bool:
        return bool(self.union["prose"]) or bool(self.union["quote"])

    def contains(self, family: str, h: int) -> bool:
        u = self.union[family]
        i = bisect.bisect_left(u, h)
        return i < len(u) and u[i] == h

    def sources_of(self, family: str, h: int, limit=2) -> list:
        if not self.per_file[family]:
            for f in self.files:
                try:
                    self.per_file[family][f] = self._file_hashes(f, family)
                except OSError:
                    continue
        hits = []
        for f, a in self.per_file[family].items():
            i = bisect.bisect_left(a, h)
            if i < len(a) and a[i] == h:
                hits.append(repo_label(f, self.cfg))
                if len(hits) >= limit:
                    break
        return hits


# ----------------------------------------------------------------------------- targets
def _git(args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def added_lines_from_diff(diff: str) -> dict:
    """{path: [(new line number, text), ...]} from a unified diff with -U0."""
    out, path, ln = {}, None, 0
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            ln = int(m.group(1)) if m else 0
            continue
        if path and line.startswith("+"):
            out.setdefault(path, []).append((ln, line[1:]))
            ln += 1
    return out


def fenced_lines(full_text: str) -> set:
    """Line numbers (1-based) inside ``` / ~~~ fences, marker lines included."""
    inside, out = False, set()
    for i, line in enumerate(full_text.split("\n"), 1):
        if re.match(r"\s*(```|~~~)", line):
            out.add(i)
            inside = not inside
            continue
        if inside:
            out.add(i)
    return out


def prose_runs(lines, index: Index, skip=frozenset()):
    """lines = [(line number, text)]. Returns [(first line, last line, content words in a row, hash)]."""
    stream, where, prev_ln = [], [], None
    for ln, text in lines:
        if ln in skip:
            if stream and stream[-1] is not BREAK:
                stream.append(BREAK); where.append(ln)
            prev_ln = None
            continue
        if prev_ln is not None and ln != prev_ln + 1 and stream and stream[-1] is not BREAK:
            stream.append(BREAK); where.append(ln)
        for t in tokens(text, family="prose"):
            stream.append(t); where.append(ln)
        prev_ln = ln
    k = index.k["prose"]
    starts = [(s, h) for s, h in shingles(stream, k, "prose") if index.contains("prose", h)]
    runs, cur = [], None
    for s, h in starts:
        if cur and s <= cur[1] + 1:
            cur[1] = s
        else:
            if cur:
                runs.append(cur)
            cur = [s, s, h]
    if cur:
        runs.append(cur)
    return [(where[a], where[b + k - 1], b - a + k, h) for a, b, h in runs]


def quoted_hits(lines, index: Index, skip=frozenset(), min_words=QUOTE_MIN_WORDS):
    """Returns [(line, words in the span, hash of its first window)] for quoted spans found verbatim in a source."""
    out = []
    for ln, text in lines:
        if ln in skip:
            continue
        for m in QUOTE_RE.finditer(text):
            span = next(g for g in m.groups() if g is not None)
            if len(span.split()) < min_words:   # paths and identifiers (a/b-c.md) are one space-separated token
                continue
            words = tokens(span, family="quote")
            if BREAK in words or len(words) < min_words or sum(is_content(w) for w in words) < QUOTE_MIN_CONTENT:
                continue
            hs = [h for _, h in shingles(words, QUOTE_K, "quote")]
            if hs and all(index.contains("quote", h) for h in hs):
                out.append((ln, len(words), hs[0]))
    return out


def scan_lines(path, lines, index, full_text=None, min_words=QUOTE_MIN_WORDS):
    skip = fenced_lines(full_text) if (full_text is not None and path.endswith((".md", ".markdown"))) else frozenset()
    if full_text is not None:
        # 公刊済みの著作の書誌 (arXiv の要旨・題名、 公開先 link だけの行) は定義上公開済み
        skip = set(skip) | _published_lines(path, full_text)
    found = []
    for a, b, n, h in prose_runs(lines, index, skip):
        found.append((path, a, b, f"prose run of {n} content words", "prose", h))
    for ln, n, h in quoted_hits(lines, index, skip, min_words):
        found.append((path, ln, ln, f"quoted span of {n} words", "quote", h))
    return found


def is_public_repo(cwd=None) -> bool:
    rc, top = _git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return rc == 0 and (Path(top.strip()) / MARKER).is_file()


def report(findings, index: Index, what: str) -> None:
    print(f"🚫 [unpublished-quote] {what} contains verbatim text of an unpublished document", file=sys.stderr)
    for path, a, b, kind, family, h in findings:
        src = ", ".join(index.sources_of(family, h)) or "?"
        span = f"{a}" if a == b else f"{a}-{b}"
        print(f"  {path}:{span}  {kind}  <- {src}", file=sys.stderr)
    print("  The matched text is not printed. Rewrite the example in general form: keep the lesson, drop the\n"
          "  instance (claude-config CLAUDE.md#non-identifier-content-leak). If the source is already published,\n"
          "  bypass this commit once with CLAUDE_UNPUBLISHED_GUARD=0, or exclude that source in the config.",
          file=sys.stderr)


def scan_staged(cfg, cwd=None, index=None) -> int:
    if not is_public_repo(cwd):
        return 0
    rc, diff = _git(["diff", "--cached", "--no-color", "-U0", "--no-ext-diff", "--diff-filter=AMR"], cwd=cwd)
    if rc != 0 or not diff.strip():
        return 0
    index = index or Index(cfg).build()
    if not index.armed():
        return 0
    findings = []
    for path, lines in added_lines_from_diff(diff).items():
        full = (_read_blob_text(f":{path}", cwd=cwd) or "") if (path.endswith((".md", ".markdown")) or _published_applies(path)) else None
        findings += scan_lines(path, lines, index, full)
    if findings:
        report(findings, index, "the staged change")
        return 1
    return 0


def scan_message(cfg, path, cwd=None, index=None) -> int:
    if not is_public_repo(cwd):
        return 0
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    body = [l for l in text.split("\n") if not l.startswith("#")]
    index = index or Index(cfg).build()
    if not index.armed():
        return 0
    findings = scan_lines("commit message", list(enumerate(body, 1)), index)
    if findings:
        report(findings, index, "the commit message")
        return 1
    return 0


# ----------------------------------------------------------------------------- wiring check with canaries
def _canaries(index: Index):
    prose = quote = None
    for f in index.files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        latex = f.endswith(".tex")
        if prose is None:
            st = tokens(text, latex, "prose")
            prose = next((" ".join(st[s:s + index.k["prose"]]) for s, h in shingles(st, index.k["prose"], "prose")
                          if index.contains("prose", h)), None)
        if quote is None:
            st = tokens(text, latex, "quote")
            for s, h in shingles(st, QUOTE_MIN_WORDS, "quote"):
                win = st[s:s + QUOTE_MIN_WORDS]
                if sum(is_content(w) for w in win) >= QUOTE_MIN_CONTENT and all(
                        index.contains("quote", x) for _, x in shingles(win, QUOTE_K, "quote")):
                    quote = " ".join(win)
                    break
        if prose and quote:
            break
    return prose, quote


def check_wiring(cfg, cfg_path, through_hooks=False) -> int:
    if cfg is None:
        print("NOT ARMED [unpublished-quote]: no sources config (personal layer unpublished-sources.txt, --config, "
              "$CLAUDE_UNPUBLISHED_SOURCES or ~/.claude/unpublished-sources.txt)")
        return 1
    index = Index(cfg).build()
    if not index.files:
        print(f"NOT APPLICABLE [unpublished-quote]: config {cfg_path} finds no source file on this machine")
        return 0
    if not index.armed():
        print(f"NOT ARMED [unpublished-quote]: config {cfg_path} lists source files but they yield no text")
        return 1
    prose, quote = _canaries(index)
    results = {}
    for name, text in (("prose", prose and f"An example: {prose}."), ("quote", quote and f"Example: `{quote}`.")):
        if not text:
            results[name] = False
            continue
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _git(["init", "-q"], cwd=repo)
            (repo / MARKER).parent.mkdir(parents=True)
            (repo / MARKER).write_text("")
            (repo / "doc.md").write_text(text + "\n")
            _git(["add", "."], cwd=repo)
            with open(os.devnull, "w") as devnull:
                old, sys.stderr = sys.stderr, devnull
                try:
                    results[name] = scan_staged(cfg, cwd=repo, index=index) == 1
                finally:
                    sys.stderr = old
    ok = all(results.values())
    print(f"{'ARMED' if ok else 'BROKEN'} [unpublished-quote]: {len(index.files)} source file(s), "
          f"{len(index.union['prose'])} prose + {len(index.union['quote'])} quote shingles; canaries: "
          + ", ".join(f"{k} {'blocked' if v else 'NOT blocked'}" for k, v in results.items()))
    if ok and through_hooks:
        hooks = check_through_hooks(quote)
        hooks_ok = all(hooks.values())
        print(f"{'HOOKS OK' if hooks_ok else 'HOOKS BROKEN'} [unpublished-quote]: real commits in a temp public repo: "
              + ", ".join(f"{k} {'ok' if v else 'FAILED'}" for k, v in hooks.items()))
        ok = hooks_ok
    return 0 if ok else 1


def check_through_hooks(quote: str, env=None) -> dict:
    """Commit through the installed public hooks of a temp repo: a staged quote and a quoted message must be
    rejected by Tier D, a plain commit must pass. Catches a runner that is not wired or not resolving its config."""
    env = dict(os.environ if env is None else env)
    env.pop("CLAUDE_UNPUBLISHED_GUARD", None)
    scripts = Path(__file__).resolve().parent
    results = {}
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)

        def git(*args):
            return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env)

        git("init", "-q")
        git("config", "user.name", "canary")
        git("config", "user.email", "canary@example.org")
        (repo / MARKER).parent.mkdir(parents=True)
        (repo / MARKER).write_text("# canary repo for check-unpublished-quote.py --through-hooks\n")
        for inst in ("install-public-precommit.sh", "install-public-commit-msg.sh"):
            subprocess.run(["bash", str(scripts / inst), str(repo)], capture_output=True, text=True, env=env)
        (repo / "doc.md").write_text(f"Example: `{quote}`.\n")
        git("add", "doc.md", str(MARKER))
        r = git("commit", "-q", "-m", "add a doc")
        results["staged quote rejected"] = r.returncode != 0 and "[unpublished-quote] the staged change contains" in r.stderr + r.stdout
        git("rm", "--cached", "-q", "doc.md")
        (repo / "note.txt").write_text("harmless\n")
        git("add", "note.txt", str(MARKER))
        r = git("commit", "-q", "-m", f"Explain: `{quote}`")
        results["quoted message rejected"] = r.returncode != 0 and "[unpublished-quote] the commit message contains" in r.stderr + r.stdout
        r = git("commit", "-q", "-m", "A plain message about a harmless note")
        results["plain commit passes"] = r.returncode == 0
    return results


TREE_SUFFIXES = (".md", ".markdown", ".py", ".sh", ".txt", ".yaml", ".yml", ".json", ".toml", ".tex", ".html", ".js", ".ts")


def scan_tree(cfg, repo, index=None, out=print) -> int:
    """Audit the current tracked text files of a repo (the inventory the go-forward gate cannot give)."""
    repo = Path(repo).resolve()
    rc, listing = _git(["ls-files", "-z"], cwd=repo)
    if rc != 0:
        out(f"✗ [unpublished-quote] not a git repo: {repo}")
        return 3
    index = index or Index(cfg).build()
    if not index.armed():
        out("NOT ARMED [unpublished-quote]: no source text")
        return 0
    findings, n = [], 0
    for rel in listing.split("\0"):
        if not rel.endswith(TREE_SUFFIXES):
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n += 1
        full = text if (rel.endswith((".md", ".markdown")) or _published_applies(rel)) else None
        findings += scan_lines(rel, list(enumerate(text.split("\n"), 1)), index, full)
    for path, a, b, kind, family, h in findings:
        span = f"{a}" if a == b else f"{a}-{b}"
        out(f"{path}:{span}  {kind}  <- {', '.join(index.sources_of(family, h)) or '?'}")
    note = "" if (repo / MARKER).is_file() else " (not marked public: its own sources may match)"
    out(f"scan-tree [unpublished-quote]: {n} text file(s) in {repo.name}{note}; {len(findings)} finding(s)")
    return 1 if findings else 0


# ----------------------------------------------------------------------------- calibration replay
def replay(cfg, repo, max_commits, prose_k, quote_min) -> int:
    index = Index(cfg, prose_k=prose_k).build()
    rc, revs = _git(["rev-list", f"--max-count={max_commits}", "HEAD"], cwd=repo)
    counts = {"prose": 0, "quote": 0}
    for sha in revs.split():
        rc, diff = _git(["show", "--no-color", "-U0", "--format=", "--no-ext-diff", sha], cwd=repo)
        hits = []
        for path, lines in added_lines_from_diff(diff).items():
            full = _git(["show", f"{sha}:{path}"], cwd=repo)[1] if (path.endswith((".md", ".markdown")) or _published_applies(path)) else None
            hits += scan_lines(path, lines, index, full, quote_min)
        if hits:
            _, subj = _git(["log", "-1", "--format=%h %cs %s", sha], cwd=repo)
            print(subj.strip()[:100])
            for path, a, b, kind, family, h in hits:
                counts[family] += 1
                print(f"    {path}:{a}-{b} {kind} <- {', '.join(index.sources_of(family, h))}")
    print(f"prose_k={prose_k} quote_min={quote_min}: prose {counts['prose']}, quote {counts['quote']} in "
          f"{len(revs.split())} commit(s); index {len(index.union['prose'])} + {len(index.union['quote'])} shingles "
          f"from {len(index.files)} file(s)")
    return 0


# ----------------------------------------------------------------------------- selftest (synthetic text only)
def selftest() -> int:
    failed = []

    def expect(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failed.append(name)

    def quiet(fn, *a, **kw):
        with open(os.devnull, "w") as devnull:
            old, sys.stderr = sys.stderr, devnull
            try:
                return fn(*a, **kw)
            finally:
                sys.stderr = old

    manuscript = r"""\documentclass{article}
\newcommand{\qq}{q}
\begin{document}
% A comment that must not be indexed: purple elephants dancing quietly around marble fountains tonight.
We show that the lattice regulator preserves the hidden symmetry of the toy model at every order, \cite{Doe:2020ab}
and that the induced coupling $g_{\mu\nu}$ stays finite once the auxiliary field is integrated out.
\begin{equation} a = b \label{eq:toy} \end{equation}
Our second argument uses the spectral density of the heat operator on compact manifolds with boundary.
Then those numbers come from one careful toy run.
\end{document}
"""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "privproj").mkdir()
        (base / "privproj" / "paper.tex").write_text(manuscript)
        (base / "privproj" / "notes.tex").write_text("Gardening tomatoes during humid summers in coastal villages.\n")
        (base / "pubrepo" / ".claude").mkdir(parents=True)
        (base / "pubrepo" / MARKER).write_text("")
        (base / "pubrepo" / "copy.tex").write_text("We show that the lattice regulator preserves the hidden symmetry.\n")
        for n in ("b1", "b2", "b3"):
            (base / n).mkdir()
            (base / n / "ack.tex").write_text("This work was supported by the generous funding agency grant number.\n")
        conf = base / "sources.txt"
        conf.write_text(f"discover: {base} .tex\nexclude: */notes.tex\n")
        cache = base / "cache"
        cfg = read_config(conf)

        t = tokens(r"Once $x$ is removed by its defining relation \cite{key-with-words}.")
        expect("prose tokens: math, cite keys, short and function words removed",
               t == ["once", "removed", "defining", "relation"])
        expect("quote tokens keep every word", tokens("Then those numbers come", family="quote") == ["then", "those", "numbers", "come"])
        expect("a Japanese run breaks the stream", tokens("alpha 日本語の文 beta") == ["alpha", BREAK, "beta"])
        files = source_files(cfg)
        expect("discover skips public repos and honours exclude",
               any(f.endswith("paper.tex") for f in files) and not any("pubrepo" in f or f.endswith("notes.tex") for f in files))
        idx = Index(cfg, cache_dir=cache).build()
        ack = tokens("This work was supported by the generous funding agency grant number")
        expect("boilerplate in 3 top-level dirs is dropped (repo DF filter)", not idx.contains("prose", shingle_hash(ack[:PROSE_K])))
        idx4 = Index(cfg, cache_dir=base / "cache4", df_max=4).build()
        expect("... foil: with the filter relaxed the same shingle is indexed", idx4.contains("prose", shingle_hash(ack[:PROSE_K])))
        purple = tokens("purple elephants dancing quietly around marble fountains tonight")
        expect("comments and the preamble are not indexed", not idx.contains("prose", shingle_hash(purple[:PROSE_K])))
        stamp = {f: os.stat(cache / (hashlib.sha1(f"{INDEX_VERSION}:prose:{PROSE_K}:{f}".encode()).hexdigest() + ".bin")).st_mtime_ns
                 for f in idx.files}
        idx2 = Index(cfg, cache_dir=cache).build()
        stamp2 = {f: os.stat(cache / (hashlib.sha1(f"{INDEX_VERSION}:prose:{PROSE_K}:{f}".encode()).hexdigest() + ".bin")).st_mtime_ns
                  for f in idx2.files}
        expect("unchanged sources are read from the cache", stamp == stamp2 and list(idx.union["prose"]) == list(idx2.union["prose"]))
        expect("... the merged index is reused and per-file data loads only for attribution",
               not idx2.per_file["prose"] and bool(idx2.sources_of("prose", idx2.union["prose"][0])))
        (base / "privproj" / "extra.tex").write_text("Brand new sentences about crystalline violins humming beneath frozen lighthouses tonight.\n")
        idx3 = Index(cfg, cache_dir=cache).build()
        new = tokens("crystalline violins humming beneath frozen lighthouses tonight")
        expect("... and a new source file invalidates it", idx3.contains("prose", shingle_hash(new[:PROSE_K])))
        (base / "privproj" / "extra.tex").unlink()
        idx = Index(cfg, cache_dir=cache).build()

        pub = base / "pubrepo"
        _git(["init", "-q"], cwd=pub)
        doc = pub / "conventions.md"
        doc.write_text("# Rules\n\nExample: `then those numbers come from one careful toy run` (short quote).\n"
                       "A paraphrase: the coupling remains finite after removing the auxiliary field.\n"
                       "```\nthe induced coupling stays finite once the auxiliary field is integrated out\n```\n")
        _git(["add", "conventions.md"], cwd=pub)
        expect("a short verbatim quotation in a public repo blocks (exit 1)", quiet(scan_staged, cfg, cwd=pub, index=idx) == 1)
        (pub / "scan.pdf").write_bytes(b"%PDF-1.4\n%\xc5\xd0\xe2\xe3\nstream \xff\xfe\n")
        _git(["add", "scan.pdf"], cwd=pub)
        expect("... still blocks when a non-UTF-8 binary is staged in the same commit",
               quiet(scan_staged, cfg, cwd=pub, index=idx) == 1)
        _git(["rm", "-q", "--cached", "scan.pdf"], cwd=pub)
        (pub / "scan.pdf").unlink()
        lines = list(enumerate(doc.read_text().split("\n"), 1))
        found = scan_lines("conventions.md", lines, idx, doc.read_text())
        expect("... reported as a quoted span on line 3, and nothing else", [(f[1], f[4]) for f in found] == [(3, "quote")])
        expect("... foil: the same words without quote marks are too short for the prose detector",
               prose_runs([(3, "then those numbers come from one careful toy run")], idx) == [])
        expect("a paraphrase passes", scan_lines("x.md", [(4, lines[3][1])], idx) == [])
        expect("a copied sentence inside a fenced block is skipped in markdown", scan_lines("conventions.md", lines[4:7], idx, doc.read_text()) == [])
        expect("... foil: the same sentence outside a fence is a prose run",
               [f[4] for f in scan_lines("conventions.md", [(40, lines[5][1])], idx, "")] == ["prose"])
        split = [(10, "Our second argument uses the spectral"), (11, "density of the heat operator on compact manifolds")]
        expect("a sentence wrapped over consecutive added lines is caught", bool(prose_runs(split, idx)))
        expect("... but not across non-consecutive lines", prose_runs([(10, split[0][1]), (20, split[1][1])], idx) == [])
        expect("a quoted generic phrase with few content words passes", quoted_hits([(1, "`and that the of the`")], idx) == [])
        expect("a quoted path or identifier is not a sentence", quoted_hits([(1, "`outputs-of-a/single-toy-loop.md`")], idx) == [])
        ack_tex = "\\begin{document}Body text here.\n\\subsection*{Acknowledgement}We thank the generous funding agency.\n\\section{Next}Tail words.\n\\end{document}"
        expect("acknowledgments are not indexed, and indexing resumes at the next section",
               "funding" not in tokens(ack_tex, latex=True) and {"body", "tail"} <= set(tokens(ack_tex, latex=True)))
        _git(["reset", "-q"], cwd=pub)
        priv = base / "privproj"
        _git(["init", "-q"], cwd=priv)
        _git(["add", "paper.tex"], cwd=priv)
        expect("a private repo is never checked", scan_staged(cfg, cwd=priv, index=idx) == 0)
        msg = base / "MSG"
        msg.write_text("Explain: the lattice regulator preserves the hidden symmetry of the toy model at every order\n# comment\n")
        expect("a commit message with a verbatim sentence blocks", quiet(scan_message, cfg, msg, cwd=pub, index=idx) == 1)
        empty = Index({"discover": [], "include": [], "exclude": []}, cache_dir=base / "c0").build()
        expect("no source = not armed = exit 0", scan_staged(None, cwd=pub, index=empty) == 0)
        with open(os.devnull, "w") as devnull:
            old_out, sys.stdout = sys.stdout, devnull
            try:
                wrc = check_wiring(cfg, conf)
            finally:
                sys.stdout = old_out
        expect("--check-wiring arms and both canaries block through the real index", wrc == 0)

        tree = base / "treerepo"
        (tree / ".claude").mkdir(parents=True)
        (tree / MARKER).write_text("")
        (tree / "notes.md").write_text("Old rule text with `then those numbers come from one careful toy run` in it.\n"
                                       "A paraphrase about numbers from a careful run.\n")
        _git(["init", "-q"], cwd=tree)
        _git(["add", "."], cwd=tree)
        lines = []
        trc = scan_tree(cfg, tree, index=idx, out=lines.append)
        expect("--scan-tree finds the old quotation in a tracked file (exit 1), not the paraphrase",
               trc == 1 and any(l.startswith("notes.md:1 ") for l in lines) and not any(l.startswith("notes.md:2") for l in lines))

        layer = base / "mock-layer"
        layer.mkdir()
        (layer / ".claude-personal-layer").write_text("")
        (layer / "CLAUDE.md").write_text("# mock\n")
        (layer / "unpublished-sources.txt").write_text(f"discover: {base} .tex\nexclude: */notes.tex\n")
        hook_env = dict(os.environ, CLAUDE_PERSONAL_LAYER=str(layer), XDG_CACHE_HOME=str(base / "hook-cache"))
        got = check_through_hooks("then those numbers come from one careful toy run", env=hook_env)
        expect("--through-hooks: real hooks reject a staged quote and a quoted message, and pass a plain commit",
               all(got.values()) and len(got) == 3)
    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config")
    ap.add_argument("--message-file")
    ap.add_argument("--check-wiring", action="store_true")
    ap.add_argument("--through-hooks", action="store_true")
    ap.add_argument("--scan-tree")
    ap.add_argument("--replay")
    ap.add_argument("--max-commits", type=int, default=300)
    ap.add_argument("--prose-k", type=int, default=PROSE_K)
    ap.add_argument("--quote-min", type=int, default=QUOTE_MIN_WORDS)
    a = ap.parse_args()
    if os.environ.get("CLAUDE_UNPUBLISHED_GUARD") == "0" and not (a.check_wiring or a.replay):
        print("⚠️ [unpublished-quote] bypassed (CLAUDE_UNPUBLISHED_GUARD=0)", file=sys.stderr)
        return 0
    cfg, cfg_path = resolve_config(a.config)
    if a.check_wiring:
        return check_wiring(cfg, cfg_path, a.through_hooks)
    if cfg is None:
        return 0
    if a.scan_tree:
        return scan_tree(cfg, a.scan_tree)
    if a.replay:
        return replay(cfg, a.replay, a.max_commits, a.prose_k, a.quote_min)
    if a.message_file:
        return scan_message(cfg, a.message_file)
    return scan_staged(cfg)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never let an engine bug stop every public commit
        print(f"⚠️ [unpublished-quote] internal error, not blocking: {exc!r}", file=sys.stderr)
        sys.exit(3)
