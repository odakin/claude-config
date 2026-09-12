#!/usr/bin/env python3
"""markdown の相対 link のうち着地先 file が無いものを分類し、答えが一意に決まる 2 型 (../ の段数ずれ・git が記録した改名) だけ直す。解決は renderer と同じ (symlink は実体 path、%XX decode、`:行番号` 無視、code span・fence・$数式$ の中は link でない)、書換えは link target の終端まで一致した時だけ・保護領域の外だけ、書換え後に「差は link target の中だけ・新しい着地先は全て実在・対象 file ごとに差が在る」 を自己検証する。--selftest 内蔵。

分類 (`--list` で全件):

| class        | 意味 | --fix |
|--------------|------|-------|
| depth        | `../` を 0..6 段試して着地先が **1 つだけ** 存在する (sub-dir・SESSION-archive/ へ移したのに link を張り直していない) | 直す |
| renamed      | git が改名を記録しており (`git log --diff-filter=R -M -z`)、その先が実在する | 直す |
| ambiguous    | 複数の段数で存在する | 触らない |
| verbatim     | 直せるが、生の記録 (`/raw/`・dialogue・transcript) の中 = 他者の出力の写し | 触らない |
| gone         | 同じ名前の file がどこにも無い / 改名先も消えた | 触らない (報告のみ) |
| not-a-path   | 拡張子が無い・空白や `\\` を含む (数式・散文・件名の一覧を link と誤認したもの) | 触らない |

使い方:

    python3 fix-md-links.py --base ~/Claude                   # 分類の件数
    python3 fix-md-links.py --base ~/Claude --list            # 全件
    python3 fix-md-links.py --base . --strict                 # depth / renamed が 1 件でもあれば exit 1 (suite 用)
    python3 fix-md-links.py --base ~/Claude --fix --exclude 'repo/path/example-doc.md'
    python3 fix-md-links.py --base ~/Claude --list --suggest  # gone の行に移動先の候補 (同名の追跡 file が repo に 1 つだけの時)
    cd <repo> && python3 fix-md-links.py --verify-diff        # 未 commit の差が link target の中だけか (commit 前の gate)
    cd <repo> && python3 fix-md-links.py --verify-diff origin/main..HEAD   # push 前に commit 群を検証し直す

`--verify-diff [REV]` は、 link を直した変更 (本 script の `--fix` でも手作業でも) が **link target の中だけの差**
かを git の差分そのものから確かめる gate。 REV 省略 = 作業ツリー (staged を含む) と HEAD の差、 `A..B` = 範囲、
commit 1 つ = その commit の差。 見るもの: path は `-z` で取る / hunk ごとに削除行数と追加行数が等しい / 対の行は
target の外が同一 / 新しい target は**変更後の状態** (作業ツリー、 または B やその commit の tree = disk にだけ在る
file では通さない) で実在し、 `.md` の `#anchor` も定義されている / 変更一覧に在るのに差の行が読めない file は
空振りとして FAIL / markdown 以外の file が混ざれば FAIL (`--files` で絞る)。 種類別の件数 (depth /
rename-or-move / fragment / permalink) を出す。 gate なので内部 error は exit 1 に倒す (= commit を止める側。
全 repo の pre-commit に繋ぐ `--staged` が内部 error を exit 3 で素通しにするのとは逆)。

`--fix` は書き換えた file を `CHANGED<TAB>path` で出すだけで commit はしない。 commit する側は
**`git diff -z --name-only` で path を取る** (非 ASCII の file 名は `-z` 無しだと 8 進 escape 付きで
quote され、 下流の検証に渡すと「差分 0 行」 で**空振りして PASS する** = 2026-09-13 実測、
claude-config `debugging-discipline.md#tooling-that-lies-on-binary-and-non-ascii`)。

起源 (2026-09-13): 素朴に数えた着地先の無い相対 link 898 本のうち 457 本は symlink の複製を symlink の
場所から解決した測定側の誤りで、 renderer と同じ解決では 8,718 本中 505 本。 直したのは 255 箇所 (段数ずれ
219 + 改名・移動 31 + 削除済み file への permalink 5、 13 repo・47 file)、 残りは数式・件名一覧の誤認と後継の無い削除。 途中で踏んだ罠 = 前方一致の置換が長い link を
書き換えた / 非 ASCII path の quote で検証が空振りした — どちらも selftest の foil。
正本 = `docs/convention-design-principles.md#link-target-rot`。
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("_cma", Path(__file__).with_name("check-md-anchors.py"))
_cma = _ilu.module_from_spec(_spec)                     # type: ignore
_spec.loader.exec_module(_cma)                          # type: ignore
LINK, protected_mask, split_target = _cma.LINK, _cma.protected_mask, _cma.split_target
iter_markdown_sources, rel_to = _cma.iter_markdown_sources, _cma.rel_to

VERBATIM = re.compile(r"/raw/|dialogue|transcript", re.I)
FIXABLE = ("depth", "renamed")
MAX_DEPTH = 6


def _exists(p: Path) -> bool:
    try:
        return p.exists()
    except OSError:              # e.g. name too long
        return False


class Git:
    """Per-repo rename maps from `git log -z` (NUL-separated: no path quoting)."""

    def __init__(self, enabled: bool = True):
        # disabled = no `git log` walk: the pre-commit path must be fast, and a rename of the
        # TARGET is not what a commit of the REFERRING file introduces (moves are; see --staged)
        self.enabled = enabled
        self.roots: dict[Path, Path | None] = {}
        self.maps: dict[Path, dict[str, str]] = {}
        self.names: dict[Path, dict[str, list[str]]] = {}

    def root(self, d: Path) -> Path | None:
        if d not in self.roots:
            r = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True)
            self.roots[d] = Path(r.stdout.strip()).resolve() if r.returncode == 0 else None
        return self.roots[d]

    def renames(self, root: Path) -> dict[str, str]:
        if not self.enabled:
            return {}
        if root not in self.maps:
            out = subprocess.run(["git", "-C", str(root), "log", "--all", "--diff-filter=R", "-M",
                                  "--name-status", "-z", "--format="], capture_output=True).stdout
            fields = [f for f in out.decode("utf-8", "surrogateescape").split("\0")]
            mp: dict[str, str] = {}
            i = 0
            while i + 2 < len(fields):
                st = fields[i].strip()
                if st.startswith("R"):
                    mp.setdefault(fields[i + 1], fields[i + 2])     # newest rename wins (log order)
                    i += 3
                else:
                    i += 1
            self.maps[root] = mp
        return self.maps[root]


    def by_name(self, root: Path) -> dict[str, list[str]]:
        """file name -> tracked paths (`git ls-files -z`), for the moved-file candidate of a gone link."""
        if root not in self.names:
            out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True).stdout
            idx: dict[str, list[str]] = {}
            for rel in out.decode("utf-8", "surrogateescape").split("\0"):
                if rel:
                    idx.setdefault(os.path.basename(rel), []).append(rel)
            self.names[root] = idx
        return self.names[root]


def moved_candidate(src: Path, path_part: str, git: Git) -> str | None:
    """For a gone link: the ONE tracked file in the same repo with that file name, as a path from the
    source. Same name is not proof of a move (two READMEs are different files), so this is printed as
    a candidate and never applied by --fix."""
    real_dir = src.resolve().parent
    name = os.path.basename(unquote(path_part).rstrip("/"))
    root = git.root(real_dir)
    if root is None or not name:
        return None
    hits = git.by_name(root).get(name, [])
    return os.path.relpath(root / hits[0], real_dir).replace(" ", "%20") if len(hits) == 1 else None


def classify(src: Path, path_part: str, git: Git) -> tuple[str, str | None]:
    """(class, new_path_part or None). path_part is the raw (still %XX-encoded) path."""
    real_dir = src.resolve().parent
    dec = unquote(path_part)
    if _exists(real_dir / dec):
        return "ok", None
    if dec.startswith("~/"):                                      # `~/x` never resolves in a renderer
        home = Path.home() / dec[2:]
        return ("renamed", os.path.relpath(home, real_dir)) if _exists(home) else ("gone", None)
    # "Is this a path at all?" is decided on the RAW target: a real file name with a space arrives
    # as %20 (the link regex never captures a literal space), and a formula carries `\`.
    if "\\" in path_part or dec.startswith("/"):
        return "not-a-path", None
    core_dec = re.sub(r"^(?:\.\./|\./)+", "", dec)
    core_raw = re.sub(r"^(?:\.\./|\./)+", "", path_part)
    hits = [k for k in range(MAX_DEPTH + 1) if core_dec and _exists(real_dir / ("../" * k + core_dec))]
    # A target with no extension is a path only if it resolves at some depth or is an explicit
    # directory (`dir/`). Otherwise it is prose: `(2)`, `(通知)`, and mail subjects that carry a
    # date slash like `(通知:7/18締切)` all look like `a/b` but are not paths (2026-09-13: 16 such
    # subjects were misfiled as "gone" when a bare `/` was taken as proof of a path).
    if not Path(dec).suffix and not dec.endswith("/") and not hits:
        return "not-a-path", None
    if len(hits) == 1:
        return "depth", "../" * hits[0] + core_raw
    if len(hits) > 1:
        return "ambiguous", None
    root = git.root(real_dir)
    if root is not None:
        meant = os.path.relpath(os.path.normpath(real_dir / dec), root)
        chain, hops = meant, set()
        ren = git.renames(root)
        while chain in ren and chain not in hops:
            hops.add(chain)
            chain = ren[chain]
        if chain != meant and _exists(root / chain):
            return "renamed", os.path.relpath(root / chain, real_dir)
    return "gone", None


IGNORE_MARK = "<!-- md-links:ignore -->"   # on a line: its links are examples written for another base


def ignored_line_mask(text: str) -> list[bool]:
    """True for every char on a line that carries IGNORE_MARK. The intent travels with the file
    (an example of a chat link rooted elsewhere, say), so no gate needs a separate exclude list."""
    out = [False] * len(text)
    pos = 0
    for line in text.split("\n"):
        if IGNORE_MARK in line:
            for i in range(pos, pos + len(line)):
                out[i] = True
        pos += len(line) + 1
    return out


def scan_text(src: Path, text: str, rel: str, git: "Git", excludes: list[str],
              include_verbatim: bool, rows: list) -> None:
    mask = protected_mask(text)
    ign = ignored_line_mask(text)
    for m in LINK.finditer(text):
        if mask[m.start()] or ign[m.start()]:
            continue
        path_part, _suffix, _frag = split_target(m.group(1))
        if not path_part or "<" in path_part or "{" in path_part:
            continue
        cls, new = classify(src, path_part, git)
        if cls == "ok":
            continue
        if cls in FIXABLE and not include_verbatim and VERBATIM.search("/" + rel):
            cls, new = "verbatim", None
        if cls in FIXABLE and any(fnmatch.fnmatch(rel, g) for g in excludes):
            cls, new = "excluded", None
        rows.append((src, rel, m.group(1), cls, new))


def scan(base: Path, repos: list[str], excludes: list[str], include_verbatim: bool,
         git: "Git | None" = None):
    git = git or Git()
    rows = []            # (src, rel, raw_target, class, new_path_part)
    for src in iter_markdown_sources(base, repos):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        scan_text(src, text, rel_to(base, src), git, excludes, include_verbatim, rows)
    return rows


def scan_files(files: list[Path], excludes: list[str], include_verbatim: bool, git: "Git"):
    rows = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        scan_text(f, text, os.path.relpath(f.resolve(), Path.cwd()), git, excludes, include_verbatim, rows)
    return rows


def scan_staged(repo: Path, excludes: list[str], include_verbatim: bool, git: "Git"):
    """Check what is about to be COMMITTED: the index blob of every added/copied/modified/renamed
    .md, resolved against the working tree. Paths come from `-z` (no octal quoting)."""
    out = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "-z", "--name-only",
                          "--diff-filter=ACMR"], capture_output=True).stdout
    rows = []
    for name in out.decode("utf-8", "surrogateescape").split("\0"):
        if not name.endswith(".md"):
            continue
        blob = subprocess.run(["git", "-C", str(repo), "show", f":{name}"], capture_output=True).stdout
        scan_text(repo / name, blob.decode("utf-8", "replace"), name, git, excludes, include_verbatim, rows)
    return rows


def rewrite(text: str, fixes: dict[str, str]) -> tuple[str, int]:
    """Rewrite link targets whose path part EXACTLY equals a key, outside protected regions.
    Matching is per parsed link, never a substring replace: fixing `notes/a` must not touch
    `](notes/a-b.md)` (the prefix-collision bug of a `str.replace("](" + key)` fixer)."""
    mask = protected_mask(text)
    ign = ignored_line_mask(text)
    out, last, n = [], 0, 0
    for m in LINK.finditer(text):
        if mask[m.start()] or ign[m.start()]:
            continue
        path_part, suffix, frag = split_target(m.group(1))
        if path_part not in fixes:
            continue
        new_target = fixes[path_part] + suffix + (("#" + frag) if frag else "")
        g0, g1 = m.span(1)
        out.append(text[last:g0])
        out.append(new_target)
        last = g1
        n += 1
    out.append(text[last:])
    return "".join(out), n


TGT = re.compile(r"\]\(([^)\s]+)\)")


def verify(path: Path, old: str, new: str) -> list[str]:
    """Self-check of a rewrite: same line count, differences only inside link targets, every
    new target resolves, and there IS a difference (a no-op 'fix' is a failure, not a pass)."""
    errs = []
    a, b = old.split("\n"), new.split("\n")
    if old == new:
        return [f"{path}: no change (vacuous fix)"]
    if len(a) != len(b):
        return [f"{path}: line count changed {len(a)} -> {len(b)}"]
    for la, lb in zip(a, b):
        if la == lb:
            continue
        if TGT.sub("](T)", la) != TGT.sub("](T)", lb):
            errs.append(f"{path}: change outside a link target: {lb[:100]}")
        for t in set(TGT.findall(lb)) - set(TGT.findall(la)):
            pp, _s, _f = split_target(t)
            if pp and not pp.startswith(("http:", "https:", "mailto:")) \
                    and not _exists(path.resolve().parent / unquote(pp)):
                errs.append(f"{path}: new target does not resolve: {t}")
    return errs


def diff_pairs(diff_text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """(removed, added) line pairs of a `-U0` diff of ONE file, read hunk by hunk. The file header is
    skipped by position (before the first `@@`), not by prefix: a removed content line that itself
    starts with `--` arrives as `---...` and is a content line."""
    pairs: list[tuple[str, str]] = []
    problems: list[str] = []
    minus: list[str] = []
    plus: list[str] = []
    in_hunk = False
    for line in diff_text.split("\n") + ["@@ end"]:
        if line.startswith("@@"):
            if in_hunk:
                if len(minus) != len(plus):
                    problems.append(f"a hunk replaces {len(minus)} line(s) by {len(plus)} (not line-for-line)")
                else:
                    pairs.extend(zip(minus, plus))
            minus, plus, in_hunk = [], [], True
        elif in_hunk and line.startswith("-"):
            minus.append(line[1:])
        elif in_hunk and line.startswith("+"):
            plus.append(line[1:])
    return pairs, problems


def link_change_kind(old: str, new: str) -> str:
    if new.startswith(("http:", "https:")):
        return "permalink"
    op, np_ = split_target(old)[0], split_target(new)[0]
    core = lambda s: re.sub(r"^(?:\.\./|\./)+", "", s)
    if op == np_:
        return "fragment"
    return "depth" if core(op) == core(np_) else "rename-or-move"


def _git(repo: Path, *args: str) -> bytes:
    r = subprocess.run(["git", "--literal-pathspecs", "-C", str(repo), *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout


def target_problem(repo: Path, f: str, target: str, after: str | None) -> str:
    """'' if `target` (written in repo file `f`) lands in the AFTER state: the working tree when after
    is None, else that commit's tree. A path that leaves the repo is checked on disk."""
    if target.startswith(("http:", "https:", "mailto:")):
        return ""
    pp, _suffix, frag = split_target(target)
    dest_rel = os.path.normpath(os.path.join(os.path.dirname(f), unquote(pp))) if pp else f
    inside = not (dest_rel == ".." or dest_rel.startswith("../") or os.path.isabs(dest_rel))
    checkable = bool(frag) and _cma.is_checkable_fragment(frag) and dest_rel.endswith(".md")
    if after is None or not inside:
        dest = ((repo / f).resolve().parent / unquote(pp)) if pp else (repo / f)
        if not _exists(dest):
            return "does not resolve"
        if checkable and frag not in _cma.anchors_of(dest.resolve()):
            return f"lands on {dest.name} but #{frag} is not defined there"
        return ""
    if dest_rel == ".":
        return ""
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{after}:{dest_rel}"],
                      capture_output=True).returncode != 0:
        return f"does not exist in {after}"
    if checkable:
        body = _git(repo, "show", f"{after}:{dest_rel}").decode("utf-8", "replace")
        if frag not in _cma.anchors_in_text(body):
            return f"lands on {dest_rel} but #{frag} is not defined there in {after}"
    return ""


def verify_diff(repo: Path, rev: str, only: list[str]) -> tuple[list[str], dict]:
    """Gate for a change set that claims to touch link targets only. Returns (problems, stats)."""
    if "..." in rev:
        raise RuntimeError("use A..B (two dots): the gate verifies the diff between two trees")
    if rev == "WORKTREE":
        diff_args, after = ["diff", "HEAD"], None
    elif ".." in rev:
        a_, b_ = rev.split("..", 1)
        diff_args, after = ["diff", a_ or "HEAD", b_ or "HEAD"], (b_ or "HEAD")
    else:
        ids = _git(repo, "rev-list", "--parents", "-n", "1", rev).decode().split()
        if len(ids) != 2:
            raise RuntimeError(f"{rev} is a root or merge commit: pass a range A..B")
        diff_args, after = ["diff", ids[1], ids[0]], ids[0]
    spec = ["--", *only] if only else []
    names = [n for n in _git(repo, *diff_args, "--no-renames", "-z", "--name-only", *spec)
             .decode("utf-8", "surrogateescape").split("\0") if n]
    stats: dict = {"files": 0, "pairs": 0, "kinds": Counter()}
    if not names:
        return ["nothing changed in that diff (vacuous: there is nothing to verify)"], stats
    problems: list[str] = []
    for f in names:
        if not f.endswith(".md"):
            problems.append(f"{f}: not markdown (this gate verifies link edits; narrow with --files)")
            continue
        stats["files"] += 1
        pairs, probs = diff_pairs(_git(repo, *diff_args, "--no-renames", "-U0", "--", f)
                                  .decode("utf-8", "replace"))
        problems += [f"{f}: {p}" for p in probs]
        if not pairs and not probs:
            problems.append(f"{f}: listed as changed but no changed line was read (vacuous: mode or binary?)")
        for la, lb in pairs:
            stats["pairs"] += 1
            if la == lb:
                problems.append(f"{f}: a changed line with identical text (end-of-file newline?)")
                continue
            if TGT.sub("](T)", la) != TGT.sub("](T)", lb):
                problems.append(f"{f}: change outside a link target: {lb[:100]}")
                continue
            olds, news = TGT.findall(la), TGT.findall(lb)
            for o, n in zip(olds, news):
                if o != n:
                    stats["kinds"][link_change_kind(o, n)] += 1
            for tgt in sorted(set(news) - set(olds)):
                why = target_problem(repo, f, tgt, after)
                if why:
                    problems.append(f"{f}: new target ({tgt}) {why}")
    return problems, stats


def run_fix(rows) -> tuple[list[str], list[str]]:
    per_file: dict[Path, dict[str, str]] = defaultdict(dict)
    for src, _rel, target, cls, new in rows:
        if cls in FIXABLE:
            per_file[src.resolve()][split_target(target)[0]] = new
    changed, errors = [], []
    for real, fixes in per_file.items():
        old = real.read_text(encoding="utf-8")
        new, n = rewrite(old, fixes)
        errs = verify(real, old, new)
        if errs:
            errors += errs
            continue                         # never write a file that fails its own check
        real.write_text(new, encoding="utf-8")
        changed.append(str(real))
    return changed, errors


# ---------------------------------------------------------------- selftest


def selftest() -> int:
    import tempfile
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        repo = base / "repo"
        (repo / "SESSION-archive").mkdir(parents=True)
        (repo / "analyses" / "archive").mkdir(parents=True)
        (repo / "notes").mkdir()
        (repo / "notes" / "a").mkdir()
        (repo / "notes" / "a-b.md").write_text("x\n", encoding="utf-8")
        (repo / "notes" / "t a.md").write_text("x\n", encoding="utf-8")
        (repo / "DESIGN.md").write_text("x\n", encoding="utf-8")
        (repo / "tool.py").write_text("x\n", encoding="utf-8")
        # git repo with a recorded rename: notes/2026-01-01-conv.tex -> notes/conv.tex
        g = lambda *c: subprocess.run(["git", "-C", str(repo), *c], capture_output=True, check=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        (repo / "notes" / "2026-01-01-conv.tex").write_text("\\relax\n" * 20, encoding="utf-8")
        g("add", "-A"); g("commit", "-q", "-m", "a")
        g("mv", "notes/2026-01-01-conv.tex", "notes/conv.tex"); g("commit", "-q", "-m", "rename")

        arch = repo / "SESSION-archive" / "2026-01.md"
        (repo / "SESSION-archive" / "DESIGN.md.local").write_text("x\n", encoding="utf-8")
        body = (
            "correct sibling that shares the broken key as a prefix [k](DESIGN.md.local)\n"
            "moved into archive, depth off [d](DESIGN.md) and [e](notes/a-b.md#sec)\n"
            "short key must not rewrite a longer link [p](notes/a) vs [q](notes/a-b.md)\n"
            "editor line ref [l](tool.py:12)\n"
            "encoded [u](notes/t%20a.md)\n"
            "renamed [r](../notes/2026-01-01-conv.tex)\n"
            "example `[x](DESIGN.md)` stays as written\n"
            "formula $[a,b](2)$ and subject [重要](通知) are not paths\n"
            "a mail subject with a date slash [件名](通知:7/18締切) is not a path either\n"
            "an explicit dir link that is gone [z](old-examples/)\n"
            "gone [g](nowhere/deleted.md)\n"
        )
        arch.write_text(body, encoding="utf-8")
        raw_dir = repo / "raw"
        raw_dir.mkdir()
        (raw_dir / "memo.md").write_text("[v](DESIGN.md)\n", encoding="utf-8")   # would be depth

        rows = scan(base, ["repo"], [], False)
        cls = {(r[1], r[2]): r[3] for r in rows}
        a = "repo/SESSION-archive/2026-01.md"
        check("depth error after an archive move is classified", cls.get((a, "DESIGN.md")) == "depth")
        check("editor :line suffix is resolved on the path part", cls.get((a, "tool.py:12")) == "depth")
        check("%20 path is decoded before resolving", cls.get((a, "notes/t%20a.md")) == "depth")
        check("git-recorded rename is followed",
              cls.get((a, "../notes/2026-01-01-conv.tex")) == "renamed")
        check("code-span example is not a link", (a, "DESIGN.md") in cls and
              sum(1 for r in rows if r[1] == a and r[2] == "DESIGN.md") == 1)
        check("formula and mail-subject brackets are not paths",
              cls.get((a, "2")) is None and cls.get((a, "通知")) == "not-a-path")
        check("deleted target is 'gone' (reported, not fixed)", cls.get((a, "nowhere/deleted.md")) == "gone")
        check("a date slash in a mail subject does not make it a path  [foil for `/` = path]",
              cls.get((a, "通知:7/18締切")) == "not-a-path")
        check("an explicit missing dir link (`dir/`) is 'gone', not prose",
              cls.get((a, "old-examples/")) == "gone")
        check("fixable link inside a raw/ record is left as verbatim",
              cls.get(("repo/raw/memo.md", "DESIGN.md")) == "verbatim")

        # teeth of the prefix foil: the naive fixer really does break the correct sibling
        naive = body.replace("](DESIGN.md", "](../DESIGN.md")
        check("naive str.replace fixer breaks the correct sibling link (the foil has teeth)",
              "[k](../DESIGN.md.local)" in naive)
        changed, errors = run_fix(rows)
        new = arch.read_text(encoding="utf-8")
        check("exact-target rewrite leaves the correct sibling link alone  [foil: prefix replace]",
              "[k](DESIGN.md.local)" in new)
        check("fix writes the archive file and reports no self-check errors",
              str(arch.resolve()) in changed and not errors)
        check("depth fixed, fragment kept", "[e](../notes/a-b.md#sec)" in new and "[d](../DESIGN.md)" in new)
        check("line suffix kept", "[l](../tool.py:12)" in new)
        check("rename rewritten to the successor", "[r](../notes/conv.tex)" in new)
        check("short key notes/a did NOT rewrite the longer link  [foil: prefix replace]",
              "[p](../notes/a)" in new and "[q](../notes/a-b.md)" in new
              and "../../notes/a-b.md" not in new)
        check("code-span example untouched  [foil: protected region]", "`[x](DESIGN.md)`" in new)
        check("gone target untouched", "[g](nowhere/deleted.md)" in new)
        check("raw/ record untouched", (raw_dir / "memo.md").read_text() == "[v](DESIGN.md)\n")
        rows2 = scan(base, ["repo"], [], False)
        check("after fix nothing fixable remains", not [r for r in rows2 if r[3] in FIXABLE])

        # verify() gate itself
        check("verify rejects a change outside a link target  [foil]",
              verify(arch, "see [a](x.md) now\n", "SEE [a](x.md) now\n") != [])
        check("verify rejects a no-op (vacuous) fix  [foil]", verify(arch, "same\n", "same\n") != [])
        check("verify rejects an unresolvable new target  [foil]",
              verify(arch, "[a](x.md)\n", "[a](../missing.md)\n") != [])

        # ignore marker: an example written for another base is neither reported nor rewritten
        ex = repo / "SESSION-archive" / "example.md"
        ex_body = f"chat-rooted example [c](DESIGN.md) {IGNORE_MARK}\nreal one [d](DESIGN.md)\n"
        ex.write_text(ex_body, encoding="utf-8")
        exrows = [r for r in scan(base, ["repo"], [], False) if r[1].endswith("example.md")]
        check("a line with the ignore marker is not reported", len(exrows) == 1)
        new_ex, n_ex = rewrite(ex_body, {"DESIGN.md": "../DESIGN.md"})
        check("the ignore-marked line is not rewritten, the real one is",
              f"[c](DESIGN.md) {IGNORE_MARK}" in new_ex and "real one [d](../DESIGN.md)" in new_ex and n_ex == 1)
        ex.unlink()

        # --staged reads the INDEX: a working-tree fix that was not re-added must still fail
        me = str(Path(__file__).resolve())
        st = repo / "SESSION-archive" / "staged.md"
        st.write_text("[s](DESIGN.md)\n", encoding="utf-8")
        g("add", "SESSION-archive/staged.md")
        r1 = subprocess.run([sys.executable, me, "--staged"], cwd=repo, capture_output=True, text=True)
        check("--staged exits 1 on a staged depth error and prints the fix command",
              r1.returncode == 1 and "--fix" in r1.stdout)
        st.write_text("[s](../DESIGN.md)\n", encoding="utf-8")            # fixed, NOT re-added
        r2 = subprocess.run([sys.executable, me, "--staged"], cwd=repo, capture_output=True, text=True)
        check("--staged still fails while only the working tree is fixed  [foil: index vs worktree]",
              r2.returncode == 1)
        g("add", "SESSION-archive/staged.md")
        r3 = subprocess.run([sys.executable, me, "--staged"], cwd=repo, capture_output=True, text=True)
        check("--staged passes once the fix is staged", r3.returncode == 0 and r3.stdout == "")
        # --files --fix on exactly the reported file
        st.write_text("[s](DESIGN.md)\n", encoding="utf-8")
        r4 = subprocess.run([sys.executable, me, "--files", str(st), "--fix"], cwd=repo,
                            capture_output=True, text=True)
        check("--files --fix rewrites only that file", st.read_text() == "[s](../DESIGN.md)\n"
              and "CHANGED" in r4.stdout)

    selftest_verify_diff(check)
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def selftest_verify_diff(check) -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td).resolve() / "r"
        (repo / "docs" / "sub").mkdir(parents=True)
        g = lambda *c: subprocess.run(["git", "-C", str(repo), *c], capture_output=True, check=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        (repo / "DOC.md").write_text("## Real Section\n", encoding="utf-8")
        (repo / "notes.txt").write_text("x\n", encoding="utf-8")
        moved = repo / "docs" / "sub" / "moved.md"
        na = repo / "docs" / "§ 記録.md"
        before_m = "see [a](DOC.md) here\n-- dashed [b](DOC.md)\nplain line\n"
        good_m = "see [a](../../DOC.md) here\n-- dashed [b](../../DOC.md)\nplain line\n"
        moved.write_text(before_m, encoding="utf-8")
        na.write_text("[c](DOC.md#real-section)\n", encoding="utf-8")
        g("add", "-A"); g("commit", "-q", "-m", "base")
        vd = lambda rev="WORKTREE", only=(): verify_diff(repo, rev, list(only))

        check("verify-diff: an empty change set fails  [foil: vacuous pass]", vd()[0] != [])
        moved.write_text(good_m, encoding="utf-8")
        na.write_text("[c](../DOC.md#real-section)\n", encoding="utf-8")
        probs, st = vd()
        check("verify-diff: link-only depth fixes pass, a line starting with `--` included  [foil: header by prefix]",
              probs == [] and st["pairs"] == 3 and st["kinds"]["depth"] == 3)
        check("verify-diff: the file with a non-ASCII name is read  [foil: quoted path]", st["files"] == 2)
        moved.write_text(good_m.replace("see", "SEE"), encoding="utf-8")
        check("verify-diff: a word changed outside a link target fails",
              any("outside a link target" in p for p in vd()[0]))
        moved.write_text(good_m.replace("](../../DOC.md) here", "](../DOC.md) here"), encoding="utf-8")
        check("verify-diff: a new target that does not resolve fails", any("does not resolve" in p for p in vd()[0]))
        moved.write_text(good_m, encoding="utf-8")
        na.write_text("[c](../DOC.md#no-such)\n", encoding="utf-8")
        check("verify-diff: a new #anchor that the landing file does not define fails",
              any("#no-such is not defined" in p for p in vd()[0]))
        na.write_text("[c](../DOC.md#real-section)\n", encoding="utf-8")
        moved.write_text(good_m.replace("plain line\n", ""), encoding="utf-8")
        check("verify-diff: a deleted line fails (not line-for-line)", any("line-for-line" in p for p in vd()[0]))
        moved.write_text(good_m, encoding="utf-8")
        (repo / "notes.txt").write_text("y\n", encoding="utf-8")
        check("verify-diff: a non-markdown change in the set fails", any("not markdown" in p for p in vd()[0]))
        check("verify-diff: --files narrows the set to the link edits",
              vd(only=["DOC.md", "docs/sub/moved.md", "docs/§ 記録.md"])[0] == [])
        (repo / "notes.txt").write_text("x\n", encoding="utf-8")
        g("commit", "-q", "-am", "fix depth")
        probs, st = vd("HEAD")
        check("verify-diff REV: a committed link-only fix passes", probs == [] and st["kinds"]["depth"] == 3)
        check("verify-diff A..B: the same range passes", vd("HEAD~1..HEAD")[0] == [])
        (repo / "only-on-disk.md").write_text("x\n", encoding="utf-8")
        moved.write_text(good_m.replace("](../../DOC.md) here", "](../../only-on-disk.md) here"), encoding="utf-8")
        g("commit", "-q", "-am", "points at an uncommitted file")
        check("verify-diff REV: resolves in that commit's tree, not on disk  [foil: file only on disk]",
              any("does not exist in" in p for p in vd("HEAD")[0]))
        check("verify-diff: the same edit uncommitted would have passed (the foil has teeth)",
              target_problem(repo, "docs/sub/moved.md", "../../only-on-disk.md", None) == "")
        (repo / "docs" / "unique-name.md").write_text("x\n", encoding="utf-8")
        (repo / "docs" / "README.md").write_text("x\n", encoding="utf-8")
        (repo / "README.md").write_text("x\n", encoding="utf-8")
        g("add", "-A"); g("commit", "-q", "-m", "names")
        gs = repo / "docs" / "sub" / "gone.md"
        gg = Git(enabled=False)
        check("--suggest: a gone link gets the one tracked file with that name",
              moved_candidate(gs, "old/unique-name.md", gg) == "../unique-name.md")
        check("--suggest: a name tracked twice gets no candidate  [foil: README.md]",
              moved_candidate(gs, "old/README.md", gg) is None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", type=Path, default=Path.home() / "Claude")
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[], help="glob (relative to base) never fixed")
    ap.add_argument("--include-verbatim", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any depth/renamed link remains")
    ap.add_argument("--files", nargs="+", type=Path, help="only these working-tree files")
    ap.add_argument("--staged", action="store_true",
                    help="pre-commit: check the index blobs of staged .md in the current repo; "
                         "exit 1 with the fix command if a fixable link is about to be committed")
    ap.add_argument("--renames", action="store_true",
                    help="with --files/--staged: also follow git renames (slower)")
    ap.add_argument("--suggest", action="store_true",
                    help="for gone links, print the one tracked file with the same name as a candidate")
    ap.add_argument("--verify-diff", nargs="?", const="WORKTREE", metavar="REV",
                    help="gate: the change set (worktree vs HEAD, a commit, or A..B) touches link targets only")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    if a.verify_diff:
        repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
        only = [os.path.relpath(Path(f).absolute().parent.resolve() / Path(f).name, repo) for f in (a.files or [])]
        problems, st = verify_diff(repo, a.verify_diff, only)
        kinds = "  ".join(f"{k}={v}" for k, v in st["kinds"].most_common())
        for p in problems:
            print(f"[FAIL] {p}")
        print(f"[verify-diff] {a.verify_diff}: files={st['files']} line-pairs={st['pairs']} "
              f"link-changes={sum(st['kinds'].values())} ({kinds}) failures={len(problems)}")
        return 1 if problems else 0

    if a.staged:
        # exit 1 = a fixable link is about to be committed (block); exit 3 = the guard itself
        # failed (the hook must NOT block every commit in every repo because of that — it warns).
        # A plain uncaught exception would also exit 1 and be indistinguishable from a finding.
        try:
            repo = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                                       text=True).stdout.strip() or ".")
            rows = [r for r in scan_staged(repo, a.exclude, a.include_verbatim, Git(a.renames))
                    if r[3] in FIXABLE]
        except Exception as e:                                   # noqa: BLE001
            print(f"[fix-md-links] WARN: link guard failed internally, commit NOT blocked: {e!r}")
            return 3
        if not rows:
            return 0
        paths = sorted({r[1] for r in rows})
        print(f"[fix-md-links] {len(rows)} link(s) in staged markdown point nowhere at their "
              f"current depth / name (typical after moving a file into a sub-dir or archive):")
        for _src, rel, target, cls, new in rows:
            print(f"  {cls:8s} {rel}  ::  {target}  ->  {new}")
        me = Path(__file__).resolve()
        quoted = " ".join("'" + p.replace("'", "'\\''") + "'" for p in paths)
        print(f"fix (rewrites link targets only, self-verified):\n"
              f"  python3 {me} --files {quoted} --fix && git add {quoted}\n"
              f"a line that is an example written for another base: append {IGNORE_MARK}")
        return 1

    git = Git(enabled=(a.renames or not a.files))
    if a.files:
        rows = scan_files(a.files, a.exclude, a.include_verbatim, git)
    else:
        rows = scan(a.base, a.repo, a.exclude, a.include_verbatim, git)
    counts = Counter(r[3] for r in rows)
    if a.fix:
        changed, errors = run_fix(rows)
        for c in changed:
            print(f"CHANGED\t{c}")
        for e in errors:
            print(f"[SELF-CHECK FAIL, file not written] {e}")
        rows = (scan_files(a.files, a.exclude, a.include_verbatim, git) if a.files
                else scan(a.base, a.repo, a.exclude, a.include_verbatim, git))
        counts = Counter(r[3] for r in rows)
        if errors:
            return 1
    fixable = counts["depth"] + counts["renamed"]
    if not (a.quiet and fixable == 0):
        print(f"[fix-md-links] relative links with a missing target: {len(rows)}  "
              + "  ".join(f"{k}={v}" for k, v in counts.most_common()))
    if a.list:
        for _src, rel, target, cls, new in sorted(rows, key=lambda r: (r[3], r[1])):
            print(f"  {cls:10s} {rel}  ::  {target}" + (f"  ->  {new}" if new else ""))
            cand = moved_candidate(_src, split_target(target)[0], git) if a.suggest and cls == "gone" else None
            if cand:
                print(f"  {'':10s} ? moved? the one tracked file with that name: {cand}")
    elif a.suggest:
        for _src, rel, target, cls, _new in rows:
            cand = moved_candidate(_src, split_target(target)[0], git) if cls == "gone" else None
            if cand:
                print(f"  gone     {rel}  ::  {target}  ? moved? {cand}")
    if fixable and not a.quiet and not a.list:
        for _src, rel, target, cls, new in rows:
            if cls in FIXABLE:
                print(f"  {cls:8s} {rel}  ::  {target}  ->  {new}")
    return 1 if (a.strict and fixable) else 0


if __name__ == "__main__":
    sys.exit(main())
