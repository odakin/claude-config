#!/usr/bin/env python3
"""arXiv 投稿用の source package を作って検査する (コメント除去 / .bbl + .bib + .bst 同梱 / 包装物だけで組版 / 元原稿と PDF テキスト一致 / bibtex 再実行で .bbl 再現)。 metadata (題・abstract の平文化と照合) と arXiv の組版 PDF との頁ごと照合も。 --selftest 内蔵。 conventions/paper-submission.md#arxiv-package-tool

arXiv は upload された source をそのまま公開する (= 著者間の赤入れ・内部メモのコメントも公開される)。
本 script は「公開してよい source」 を作り、 それが元原稿と同じ PDF になることを機械で確かめる。

Subcommands:
  build SRC_DIR --main NAME --out OUT_DIR [--drop-graphicx-driver] [--expect-pages N]
        [--forbid PATTERN ...] [--extra FILE ...] [--engine pdflatex]
      1. NAME.tex (と \\input / \\include した .tex) からコメントを除く。
         コメントだけの行は行ごと消す (空行を残すと段落が切れる)、 行末コメントは `%` を残す
         (行末の空白を殺す働きを保つ)、 `\\%` はコメントでない、 \\url{..} / \\href{..} の第 1 引数・
         \\verb・verbatim 系環境の中の `%` は触らない。 comment 環境 (package comment) の中身も消す。
         \\iffalse ブロックは自動では消さず、 行番号を報告する (隠し本文の公開に気づくため)。
      2. --drop-graphicx-driver: \\usepackage[...]{graphicx} の driver option (dvips / dvipdfmx / pdftex 等)
         だけを外す (arXiv help: driver は自動判定させ、 明示しない)。
      3. 依存を集める: \\includegraphics (\\graphicspath も見る)、 \\bibliography の .bib、
         \\bibliographystyle の .bst (SRC_DIR にあるもの)、 SRC_DIR にある \\documentclass の .cls と
         \\usepackage の .sty、 --extra。
      4. scratch で bibtex 込みで組版して NAME.bbl を作る → package (= 包装物だけ、 bibtex を回さない)
         を組版 = arXiv の AutoTeX が見るもの。 .bib と .bst も同梱する (source を落とした人が参考文献を
         組み直せるように)。
      5. gate: package の組版で error 0 / 未定義参照 0 / rerun 警告なし / (--expect-pages) 頁数一致 /
         除去後に全行コメントが残っていない / --forbid の文字列が無い / **package の PDF テキストが
         元原稿 (コメント付きのまま) の PDF テキストと一致** / **package で bibtex を回すと同梱の .bbl を
         byte 一致で再現**。 全部通れば ALL PASS (exit 0)。
      6. OUT_DIR/NAME-arxiv-source.tar.gz と OUT_DIR/NAME-arxiv-preview.pdf を書く。

  metadata SRC_DIR --main NAME [--compare-abstract FILE]
      コメント除去後の source から \\title と abstract を取り、 arXiv の metadata 欄に貼る平文にする
      (空白の正規化、 語と語の間の `--` を `-` に)。 abstract の字数 (上限 1920) と、 残った TeX 命令・`$` を
      警告。 --compare-abstract: arXiv の Preview 画面から写した abstract と照合。

  compare-pdf ARXIV_PDF LOCAL_PDF
      arXiv が組版した PDF と手元の package の PDF を頁ごとのテキストで比べ、 違う頁と行を出す
      (1 頁目の日付 = arXiv 側は UTC の組版日 / arXiv:submit/NNNNNNN の stamp は想定内の差)。
      未解決引用 `[?]` / `??` の数と Type3 font も数える。

Usage:
  python3 arxiv-package.py build paper-dir --main paper --out arxiv/v1 --drop-graphicx-driver --expect-pages 45
  python3 arxiv-package.py metadata paper-dir --main paper --compare-abstract abstract-from-arxiv.txt
  python3 arxiv-package.py compare-pdf ~/Downloads/view.pdf arxiv/v1/paper-arxiv-preview.pdf
  python3 arxiv-package.py --selftest
"""
from __future__ import annotations

import argparse
import difflib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

VERBATIM_ENVS = ("verbatim", "verbatim*", "lstlisting", "minted", "Verbatim", "alltt")
GRAPHICS_EXTS = ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".mps")
DRIVER_OPTIONS = {"dvips", "dvipdfm", "dvipdfmx", "pdftex", "luatex", "xetex", "dvisvgm", "vtex", "dvipsone", "dviwindo"}
ABSTRACT_LIMIT = 1920


# ── comment stripping ────────────────────────────────────────────────────────

def _skip_braced(line: str, i: int) -> int:
    """line[i] == '{' → index just past the matching '}' on this line (or len(line))."""
    depth = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(line)


def _comment_start(line: str) -> int | None:
    """Index of the `%` that starts a TeX comment, honouring \\%, \\url{..}, \\href{..}, \\verb."""
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            m = re.match(r"\\(url|href)\s*(?=\{)", line[i:])
            if m:
                i = _skip_braced(line, i + m.end())
                continue
            m = re.match(r"\\verb\*?(.)", line[i:])
            if m:
                end = line.find(m.group(1), i + m.end())
                i = n if end < 0 else end + 1
                continue
            i += 2
            continue
        if ch == "%":
            return i
        i += 1
    return None


def strip_comments(text: str) -> tuple[str, dict]:
    """Return (stripped text, report). Comment-only lines are removed, trailing comments keep '%'."""
    out: list[str] = []
    report = {"comment_lines": 0, "trailing": 0, "comment_env_lines": 0, "iffalse_lines": []}
    in_verbatim: str | None = None
    in_comment_env = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if in_verbatim:
            out.append(line)
            if re.search(r"\\end\{" + re.escape(in_verbatim) + r"\}", line):
                in_verbatim = None
            continue
        if in_comment_env:
            report["comment_env_lines"] += 1
            if re.match(r"\s*\\end\{comment\}", line):
                in_comment_env = False
            continue
        cut = _comment_start(line)
        code = line if cut is None else line[:cut]
        if re.match(r"\s*\\begin\{comment\}", code):
            in_comment_env = True
            report["comment_env_lines"] += 1
            continue
        m = re.search(r"\\begin\{(" + "|".join(re.escape(e) for e in VERBATIM_ENVS) + r")\}", code)
        if m and not re.search(r"\\end\{" + re.escape(m.group(1)) + r"\}", code):
            in_verbatim = m.group(1)
        if re.search(r"\\iffalse\b", code):
            report["iffalse_lines"].append(lineno)
        if cut is None:
            out.append(line)
        elif code.strip() == "":
            report["comment_lines"] += 1
        else:
            report["trailing"] += 1
            out.append(line[:cut + 1])
    return "\n".join(out) + "\n", report


def residual_comment_lines(text: str) -> list[int]:
    return [i for i, l in enumerate(text.splitlines(), 1) if _comment_start(l) is not None and l[:_comment_start(l)].strip() == ""]


def drop_graphicx_driver(text: str) -> tuple[str, int]:
    def repl(m: re.Match) -> str:
        opts = [o.strip() for o in m.group(1).split(",") if o.strip()]
        kept = [o for o in opts if o not in DRIVER_OPTIONS]
        return r"\usepackage" + (f"[{','.join(kept)}]" if kept else "") + "{graphicx}"
    pat = re.compile(r"\\usepackage\[([^\]]*)\]\{graphicx\}")
    count = sum(1 for m in pat.finditer(text) if any(o.strip() in DRIVER_OPTIONS for o in m.group(1).split(",")))
    return pat.sub(lambda m: repl(m) if any(o.strip() in DRIVER_OPTIONS for o in m.group(1).split(",")) else m.group(0), text), count


# ── dependency discovery ─────────────────────────────────────────────────────

def _brace_args(text: str, command: str) -> list[str]:
    return re.findall(r"\\" + command + r"\*?(?:\[[^\]]*\])?\s*\{([^}]*)\}", text)


def find_dependencies(src: Path, stripped: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (files to ship besides the main/included .tex, missing references)."""
    ship: list[str] = []
    missing: list[str] = []
    all_text = "\n".join(stripped.values())
    gpaths = [""] + [p for grp in re.findall(r"\\graphicspath\s*\{((?:\{[^}]*\})+)\}", all_text) for p in re.findall(r"\{([^}]*)\}", grp)]
    for name in _brace_args(all_text, "includegraphics"):
        name = name.strip()
        hit = next((gp + name + ext for gp in gpaths for ext in GRAPHICS_EXTS if (src / (gp + name + ext)).is_file()), None)
        (ship.append(hit) if hit else missing.append(f"graphics:{name}"))
    for group in _brace_args(all_text, "bibliography"):
        for b in [x.strip() for x in group.split(",") if x.strip()]:
            f = b if b.endswith(".bib") else b + ".bib"
            (ship.append(f) if (src / f).is_file() else missing.append(f"bib:{f}"))
    for s in _brace_args(all_text, "bibliographystyle"):
        f = s.strip() + ".bst"
        if (src / f).is_file():
            ship.append(f)
    for c in _brace_args(all_text, "documentclass"):
        if (src / (c.strip() + ".cls")).is_file():
            ship.append(c.strip() + ".cls")
    for group in _brace_args(all_text, "usepackage"):
        for p in [x.strip() for x in group.split(",") if x.strip()]:
            if (src / (p + ".sty")).is_file():
                ship.append(p + ".sty")
    return sorted(set(ship)), missing


def collect_tex(src: Path, main: str) -> dict[str, str]:
    """main.tex plus \\input/\\include'd .tex files (recursive), keyed by relative path, raw text."""
    raw: dict[str, str] = {}
    queue = [main + ".tex"]
    while queue:
        rel = queue.pop()
        if rel in raw or not (src / rel).is_file():
            continue
        raw[rel] = (src / rel).read_text()
        stripped, _ = strip_comments(raw[rel])
        for cmd in ("input", "include", "subfile"):
            for name in _brace_args(stripped, cmd):
                name = name.strip()
                queue.append(name if name.endswith(".tex") else name + ".tex")
    return raw


# ── building and gates ───────────────────────────────────────────────────────

def run_latex(workdir: Path, main: str, engine: str, bibtex: bool) -> None:
    def tex() -> None:
        subprocess.run([engine, "-interaction=nonstopmode", "-halt-on-error", main + ".tex"],
                       cwd=workdir, capture_output=True, text=True)
    tex()
    if bibtex:
        subprocess.run(["bibtex", main], cwd=workdir, capture_output=True, text=True)
    tex()
    tex()


def log_gates(workdir: Path, main: str) -> dict:
    logf = workdir / (main + ".log")
    log = logf.read_text(errors="replace") if logf.exists() else ""
    pages = re.search(r"Output written on .*?\((\d+) pages?", log)
    return {
        "pages": int(pages.group(1)) if pages else None,
        "undefined": len(re.findall(r"undefined", log, re.I)),
        "errors": len(re.findall(r"^! ", log, re.M)),
        "rerun": "Label(s) may have changed" in log or "Rerun to get" in log,
    }


def pdf_pages_text(pdf: Path) -> list[str] | None:
    try:
        import fitz  # PyMuPDF
        with fitz.open(pdf) as d:
            return [p.get_text() for p in d]
    except ImportError:
        pass
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True)
        return r.stdout.split("\f")
    return None


def cmd_build(args: argparse.Namespace) -> int:
    src = Path(args.src).resolve()
    out = Path(args.out).resolve()
    main = args.main
    raw = collect_tex(src, main)
    if main + ".tex" not in raw:
        sys.exit(f"not found: {src / (main + '.tex')}")
    stripped: dict[str, str] = {}
    problems: list[str] = []
    for rel, text in raw.items():
        s, rep = strip_comments(text)
        if rel == main + ".tex" and args.drop_graphicx_driver:
            s, n = drop_graphicx_driver(s)
            print(f"graphicx driver option dropped: {n} occurrence(s)")
        stripped[rel] = s
        print(f"{rel}: comment-only lines removed {rep['comment_lines']}, trailing comments cut {rep['trailing']}, comment-env lines removed {rep['comment_env_lines']}")
        if rep["iffalse_lines"]:
            print(f"  ⚠️ \\iffalse at lines {rep['iffalse_lines']} (text inside is published; review by hand)")
        left = residual_comment_lines(s)
        if left:
            problems.append(f"{rel}: comment lines survived at {left[:10]}")
        for pat in args.forbid or []:
            if pat in s:
                problems.append(f"{rel}: forbidden string present: {pat!r}")
    deps, missing = find_dependencies(src, stripped)
    deps = sorted(set(deps + (args.extra or [])))
    if missing:
        problems.append(f"unresolved references: {missing}")
    if problems:
        for p in problems:
            print("✗", p)
        print("FAILED")
        return 1

    pkg, scratch, orig, rebib = out / "source", out / "scratch", out / "scratch-original", out / "rebib"
    for d in (pkg, scratch, orig, rebib):
        if d.exists():
            shutil.rmtree(d)
    for d in (pkg, scratch, orig):
        d.mkdir(parents=True)
    for d, texts in ((pkg, stripped), (scratch, stripped), (orig, raw)):
        for rel, t in texts.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(t)
        for f in deps:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / f, d / f)
    has_bib = any(f.endswith(".bib") for f in deps)

    run_latex(scratch, main, args.engine, bibtex=has_bib)
    run_latex(orig, main, args.engine, bibtex=has_bib)
    if has_bib:
        if not (scratch / (main + ".bbl")).exists():
            print("✗ bibtex produced no .bbl\nFAILED")
            return 1
        shutil.copy2(scratch / (main + ".bbl"), pkg / (main + ".bbl"))
    shipped = sorted(str(p.relative_to(pkg)) for p in pkg.rglob("*") if p.is_file())
    run_latex(pkg, main, args.engine, bibtex=False)
    g = log_gates(pkg, main)
    o = log_gates(orig, main)

    text_same = None
    tp, to = pdf_pages_text(pkg / (main + ".pdf")), pdf_pages_text(orig / (main + ".pdf"))
    if tp is not None and to is not None:
        text_same = [" ".join(x.split()) for x in tp] == [" ".join(x.split()) for x in to]

    bbl_same = None
    if has_bib:
        shutil.copytree(pkg, rebib)
        (rebib / (main + ".bbl")).unlink()
        run_latex(rebib, main, args.engine, bibtex=True)
        new = rebib / (main + ".bbl")
        bbl_same = new.exists() and new.read_bytes() == (pkg / (main + ".bbl")).read_bytes()
        shutil.rmtree(rebib)

    shutil.copy2(pkg / (main + ".pdf"), out / (main + "-arxiv-preview.pdf"))
    for p in sorted(pkg.rglob("*"), reverse=True):
        if p.is_file() and str(p.relative_to(pkg)) not in shipped:
            p.unlink()
    tarpath = out / f"{main}-arxiv-source.tar.gz"
    with tarfile.open(tarpath, "w:gz") as tar:
        for name in shipped:
            tar.add(pkg / name, arcname=name)

    print(f"shipped files : {shipped}")
    print(f"original build: {o}")
    print(f"package build : {g}")
    print(f"package PDF text == original PDF text: {text_same}")
    print(f"bibtex on the package reproduces the shipped .bbl: {bbl_same}")
    print(f"tarball       : {tarpath} ({tarpath.stat().st_size} bytes)")
    print(f"preview PDF   : {out / (main + '-arxiv-preview.pdf')}")
    ok = g["errors"] == 0 and g["undefined"] == 0 and not g["rerun"]
    ok = ok and text_same is not False and bbl_same is not False
    if text_same is None:
        print("⚠️ PDF text comparison skipped (install PyMuPDF or pdftotext)")
    if args.expect_pages is not None:
        ok = ok and g["pages"] == args.expect_pages
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


# ── metadata ─────────────────────────────────────────────────────────────────

def _balanced_arg(text: str, command: str) -> str | None:
    m = re.search(r"\\" + command + r"\s*\{", text)
    if not m:
        return None
    end = _skip_braced(text.replace("\n", " "), m.end() - 1)
    return text[m.end():end - 1]


def plain_metadata(s: str) -> str:
    s = re.sub(r"\\\\", " ", s)
    s = re.sub(r"\\noindent\b", " ", s)
    s = " ".join(s.split())
    return re.sub(r"(?<=\w)--(?=\w)", "-", s)


def metadata_warnings(s: str) -> list[str]:
    w = []
    commands = sorted(set(re.findall(r"\\[A-Za-z]+", s)))
    if commands:
        w.append("TeX commands left: " + ", ".join(commands))
    if "$" in s:
        w.append("'$' present (arXiv renders it with MathJax)")
    if "~" in s:
        w.append("'~' present (shown literally)")
    return w


def cmd_metadata(args: argparse.Namespace) -> int:
    src = Path(args.src)
    text, _ = strip_comments((src / (args.main + ".tex")).read_text())
    title = _balanced_arg(text, "title")
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.S)
    abstract = m.group(1) if m else None
    rc = 0
    for label, val in (("Title", title), ("Abstract", abstract)):
        if val is None:
            print(f"✗ {label} not found")
            rc = 1
            continue
        p = plain_metadata(val)
        print(f"── {label} ({len(p)} chars) ──\n{p}\n")
        for w in metadata_warnings(p):
            print(f"  ⚠️ {w}")
        if label == "Abstract" and len(p) > ABSTRACT_LIMIT:
            print(f"  ✗ longer than arXiv's {ABSTRACT_LIMIT}-character limit")
            rc = 1
    if args.compare_abstract and abstract is not None:
        theirs = " ".join(Path(args.compare_abstract).read_text().split())
        ours = plain_metadata(abstract)
        if theirs == ours:
            print("abstract on the arXiv page == source abstract")
        else:
            sm = difflib.SequenceMatcher(None, ours, theirs)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag != "equal":
                    print(f"  ✗ {tag}: source {ours[max(0, i1 - 30):i2 + 30]!r} vs page {theirs[max(0, j1 - 30):j2 + 30]!r}")
            rc = 1
    return rc


# ── compare-pdf ──────────────────────────────────────────────────────────────

def cmd_compare_pdf(args: argparse.Namespace) -> int:
    a, b = pdf_pages_text(Path(args.arxiv_pdf)), pdf_pages_text(Path(args.local_pdf))
    if a is None or b is None:
        sys.exit("need PyMuPDF or pdftotext")
    while a and not a[-1].strip():
        a.pop()
    while b and not b[-1].strip():
        b.pop()
    print(f"pages arXiv / local: {len(a)} / {len(b)}")
    rc = 0 if len(a) == len(b) else 1
    for i, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            d = [l for l in difflib.unified_diff(x.splitlines(), y.splitlines(), lineterm="", n=0)
                 if not l.startswith(("---", "+++", "@@"))]
            expected = i == 1 and all(re.search(r"arXiv:submit/|\b(19|20)\d\d\b", l) or not l[1:].strip() for l in d)
            print(f"page {i} differs{' (date / submit stamp only = expected)' if expected else ''}: {d[:8]}")
            rc = rc if expected else 1
    full = "".join(a)
    print(f"'[?]' {full.count('[?]')} / '??' {full.count('??')}")
    try:
        import fitz
        with fitz.open(args.arxiv_pdf) as d:
            t3 = sorted({f[3] for p in d for f in p.get_fonts() if f[2] == "Type3"})
        print(f"Type3 fonts: {t3 or 'none'}")
    except ImportError:
        pass
    return rc


# ── selftest ─────────────────────────────────────────────────────────────────

def selftest() -> int:
    cases = [
        ("a\n% note\nb\n", "a\nb\n"),
        ("text % note\n", "text %\n"),
        ("50\\% off\n", "50\\% off\n"),
        ("x\\\\% note\n", "x\\\\%\n"),
        ("\\url{http://a/b%20c} % note\n", "\\url{http://a/b%20c} %\n"),
        ("\\href{http://a/%7E}{link}% note\n", "\\href{http://a/%7E}{link}%\n"),
        ("\\verb|a%b| x\n", "\\verb|a%b| x\n"),
        ("\\begin{verbatim}\n% kept\n\\end{verbatim}\n", "\\begin{verbatim}\n% kept\n\\end{verbatim}\n"),
        ("a\n\\begin{comment}\nhidden\n\\end{comment}\nb\n", "a\nb\n"),
        ("   % indented\nz\n", "z\n"),
    ]
    fails = 0
    for src, want in cases:
        got, _ = strip_comments(src)
        if got != want:
            fails += 1
            print(f"✗ strip {src!r}: got {got!r}, want {want!r}")
    _, rep = strip_comments("\\iffalse\nsecret\n\\fi\n")
    if rep["iffalse_lines"] != [1]:
        fails += 1
        print(f"✗ iffalse report: {rep['iffalse_lines']}")
    for src, want, n in [
        ("\\usepackage[dvipdfmx]{graphicx}", "\\usepackage{graphicx}", 1),
        ("\\usepackage[dvips,final]{graphicx}", "\\usepackage[final]{graphicx}", 1),
        ("\\usepackage[final]{graphicx}", "\\usepackage[final]{graphicx}", 0),
    ]:
        got, cnt = drop_graphicx_driver(src)
        if got != want or cnt != n:
            fails += 1
            print(f"✗ driver {src!r}: got {got!r} ({cnt})")
    for src, want in [("Klein--Gordon and Bose--Einstein", "Klein-Gordon and Bose-Einstein"),
                      ("\\noindent\nA  line\\\\ B", "A line B"), ("1--2 pages", "1-2 pages")]:
        if plain_metadata(src) != want:
            fails += 1
            print(f"✗ metadata {src!r}: {plain_metadata(src)!r}")
    if residual_comment_lines("a\n% left\n") != [2]:
        fails += 1
        print("✗ residual_comment_lines")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "fig.png").write_bytes(b"x")
        (d / "refs.bib").write_text("@misc{a,title={t}}\n")
        (d / "sty.bst").write_text("")
        (d / "loc.sty").write_text("")
        tex = "\\usepackage{loc,amsmath}\\includegraphics[width=1cm]{fig}\\bibliographystyle{sty}\\bibliography{refs}\\includegraphics{nope}"
        deps, missing = find_dependencies(d, {"m.tex": tex})
        if deps != ["fig.png", "loc.sty", "refs.bib", "sty.bst"] or missing != ["graphics:nope"]:
            fails += 1
            print(f"✗ deps {deps} missing {missing}")
    print("selftest:", "ALL PASS" if fails == 0 else f"{fails} FAIL")
    return 0 if fails == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("src")
    b.add_argument("--main", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--drop-graphicx-driver", action="store_true")
    b.add_argument("--expect-pages", type=int)
    b.add_argument("--forbid", action="append")
    b.add_argument("--extra", action="append")
    b.add_argument("--engine", default="pdflatex")
    m = sub.add_parser("metadata")
    m.add_argument("src")
    m.add_argument("--main", required=True)
    m.add_argument("--compare-abstract")
    c = sub.add_parser("compare-pdf")
    c.add_argument("arxiv_pdf")
    c.add_argument("local_pdf")
    args = ap.parse_args()
    return {"build": cmd_build, "metadata": cmd_metadata, "compare-pdf": cmd_compare_pdf}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
