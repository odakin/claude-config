#!/usr/bin/env python3
"""TeX から組んだ PDF (原稿・ノート) の最新版を、 同期フォルダ (Dropbox 等) の 1 か所へ写す — 携帯で常に読めるようにする。

対象は自動で見つける (一覧を人が育てない): BASE 直下の各 git repo で、 追跡中または
未追跡 (ignore されていない) の PDF のうち、 同じ場所に同じ名前の .tex があるもの。
git-crypt で暗号化している PDF は写さない (復号した写しを repo の外に置かないため)。
置き場所の dir 名が保管庫を表すもの (archive / old / submissions など = SKIP_DIRS) も写さない。
recent_days を指定すると、 その日数の内に PDF か .tex が commit されたもの・作業中のもの
(未 commit の変更)・すでに写し先に在るものだけにする (携帯の一覧を今の仕事に絞る)。

repo の中に clone してある別の repo (親が ignore している Overleaf の clone 等、 3 階層まで) も見る。

写し先: DEST/<repo>/<名前>.pdf。 main.pdf のような一般的な名前は、 意味のある一番近い dir 名
(src / v3 のような dir は飛ばす。 無ければ repo 名) に付け替える。 同じ名前がぶつかったら path を `--` でつないだ名前にする。

写す条件: 写し先に無い、 または「中身が違う ∧ 元のほうが新しい (mtime)」。 後ろの条件は、
複数のマシンが同じ DEST に書くときに、 pull の遅れたマシンが古い PDF で上書きしないため。
消すことはしない (別のマシンにまだ無い PDF を消さないため)。 整理は `--prune-report` の一覧を見て人が決める。

使い方:
  sync-built-pdfs.py --config CONFIG.json   # {"base": "~/work", "dest": "~/Dropbox/...", "exclude": ["*/x/*"], "recent_days": 30}
  sync-built-pdfs.py --base DIR --dest DIR [--exclude GLOB ...] [--recent-days N] [--dry-run] [--quiet]
  sync-built-pdfs.py --config CONFIG.json --prune-report   # DEST に在るが元が見つからない PDF の一覧
  sync-built-pdfs.py --selftest
exclude の GLOB は `<repo>/<repo 内の path>` に対して当てる (fnmatch)。
止める: 環境変数 CLAUDE_PDF_SYNC=0。
"""
import argparse
import filecmp
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SKIP_DIRS = {"archive", "archives", "old", "attic", "backup", "backups", "submissions", "submitted", "vendor", "doc"}
GENERIC_DIRS = {"src", "tex", "latex", "manuscript", "paper", "draft", "text", "overleaf", "external"}
GENERIC = {"main", "paper", "draft", "manuscript", "note", "notes", "slides", "report", "ms"}


def git(repo: Path, *args: str, stdin: bytes = b"") -> bytes:
    r = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True)
    return r.stdout if r.returncode == 0 else b""


def built_pdfs(repo: Path):
    """repo の中の「同名の .tex がある PDF」 で、 git-crypt でないもの (repo からの相対 path)。"""
    out = git(repo, "ls-files", "-z", "-co", "--exclude-standard", "--", "*.pdf")
    paths = [p for p in out.decode("utf-8", "replace").split("\0") if p]
    paths = [p for p in paths if (repo / p).with_suffix(".tex").is_file() and (repo / p).stat().st_size > 0]
    paths = [p for p in paths if not any(d.lower() in SKIP_DIRS or d.lower().endswith(("_old", "-old", "revisions"))
                                         for d in Path(p).parts[:-1])]
    if not paths:
        return []
    attr = git(repo, "check-attr", "-z", "--stdin", "filter", stdin="\0".join(paths).encode() + b"\0")
    f = attr.decode("utf-8", "replace").split("\0")
    crypt = {f[i] for i in range(0, len(f) - 2, 3) if f[i + 2] == "git-crypt"}
    return [p for p in paths if p not in crypt]


def target_names(repo_name: str, paths):
    """repo 内の path → 写し先の file 名。 一般的な名前は dir 名に、 ぶつかったら path 全体に。"""
    def short(p: str) -> str:
        q = Path(p)
        if q.stem.lower() not in GENERIC:
            return q.name
        # 一般的な名前 (main.pdf 等) は、 意味のある一番近い dir 名に。 src / v3 のような dir は飛ばす
        for d in reversed(q.parts[:-1]):
            if d.lower() not in GENERIC_DIRS and not re.fullmatch(r"v\d+", d.lower()):
                return d + ".pdf"
        return repo_name + ".pdf"
    names = {p: short(p) for p in paths}
    seen = {}
    for p, n in names.items():
        seen.setdefault(n, []).append(p)
    for n, ps in seen.items():
        if len(ps) > 1:
            for p in ps:
                names[p] = "--".join(Path(p).with_suffix("").parts) + ".pdf"
    return names


def recently_touched(repo: Path, days: int):
    """days 日の内に commit された path と、 未 commit の変更がある path。"""
    log = git(repo, "log", f"--since={days} days ago", "--name-only", "--format=", "-z", "--", "*.pdf", "*.tex")
    st = git(repo, "status", "--porcelain", "-z", "--", "*.pdf", "*.tex")
    touched = {p for p in log.decode("utf-8", "replace").split("\0") if p}
    touched |= {e[3:] for e in st.decode("utf-8", "replace").split("\0") if len(e) > 3}
    return touched


def plan(base: Path, dest: Path, exclude, recent_days: int = 0):
    jobs = []
    # BASE 直下の repo に加えて、 その中に clone してある別の repo (親が ignore している Overleaf の clone 等) も見る
    repos = {p.parent for pat in ("*/.git", "*/*/.git", "*/*/*/.git") for p in base.glob(pat)}
    for repo in sorted(repos):
        top = repo.relative_to(base).parts[0]
        inner = "/".join(repo.relative_to(base).parts[1:])
        paths = [p for p in built_pdfs(repo)
                 if not any(fnmatch.fnmatch(f"{top}/{inner + '/' if inner else ''}{p}", g) for g in exclude)]
        touched = recently_touched(repo, recent_days) if recent_days and paths else None
        prefix = (inner.replace("/", "--") + "--") if inner else ""
        for p, n in target_names(top, paths).items():
            # 入れ子の repo の PDF は、 親の repo の PDF と名前がぶつかったら置き場所を前に付ける
            d = dest / top / n
            if inner and any(j[1] == d for j in jobs):
                d = dest / top / (prefix + n)
            if touched is None or p in touched or str(Path(p).with_suffix(".tex")) in touched or d.exists():
                jobs.append((repo / p, d))
    return jobs


def needs_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    if src.stat().st_mtime <= dst.stat().st_mtime + 1:
        return False
    return not filecmp.cmp(src, dst, shallow=False)


def copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name("." + dst.name + ".tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def run(base: Path, dest: Path, exclude, dry: bool, quiet: bool, recent_days: int = 0) -> int:
    lock = Path(tempfile.gettempdir()) / f"sync-built-pdfs-{os.getuid()}.lock"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime < 300:
            return 0
        lock.write_text(str(os.getpid()))
        copied = [(s, d) for s, d in plan(base, dest, exclude, recent_days) if needs_copy(s, d)]
        for s, d in copied:
            if not dry:
                copy_atomic(s, d)
            if not quiet:
                print(("would copy " if dry else "copied ") + f"{s} -> {d}")
        if not quiet:
            print(f"{len(copied)} 件" + (" (dry-run)" if dry else ""))
        return 0
    finally:
        lock.unlink(missing_ok=True)


def prune_report(base: Path, dest: Path, exclude) -> int:
    live = {d for _, d in plan(base, dest, exclude)}
    for p in sorted(dest.rglob("*.pdf")):
        if p not in live:
            print(p)
    return 0


def selftest() -> int:
    with tempfile.TemporaryDirectory() as t:
        base, dest = Path(t) / "base", Path(t) / "dest"
        repo = base / "r1"
        (repo / "notes" / "topic").mkdir(parents=True)
        (repo / "sec").mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        for rel in ("main", "notes/topic/main", "talk", "sec/secret"):
            (repo / f"{rel}.tex").write_text("x")
            (repo / f"{rel}.pdf").write_bytes(b"%PDF " + rel.encode())
        (repo / "orphan.pdf").write_bytes(b"%PDF orphan")          # .tex が無い → 対象外
        (repo / ".gitattributes").write_text("sec/** filter=git-crypt diff=git-crypt\n")
        jobs = {str(d.relative_to(dest)) for _, d in plan(base, dest, [])}
        assert jobs == {"r1/r1.pdf", "r1/topic.pdf", "r1/talk.pdf"}, jobs
        assert {str(d.relative_to(dest)) for _, d in plan(base, dest, ["r1/notes/*"])} == {"r1/r1.pdf", "r1/talk.pdf"}
        run(base, dest, [], False, True)
        assert (dest / "r1/topic.pdf").read_bytes() == b"%PDF notes/topic/main"
        # 古いマシンの古い PDF は、 新しい写しを上書きしない
        (dest / "r1/talk.pdf").write_bytes(b"%PDF newer elsewhere")
        old = time.time() - 3600
        os.utime(repo / "talk.pdf", (old, old))
        run(base, dest, [], False, True)
        assert (dest / "r1/talk.pdf").read_bytes() == b"%PDF newer elsewhere"
        # 元が新しくなれば写す
        (repo / "talk.pdf").write_bytes(b"%PDF rebuilt")
        new = time.time() + 5
        os.utime(repo / "talk.pdf", (new, new))
        run(base, dest, [], False, True)
        assert (dest / "r1/talk.pdf").read_bytes() == b"%PDF rebuilt"
        # 同じ名前がぶつかったら path 全体の名前にする
        (repo / "a" / "x").mkdir(parents=True)
        (repo / "b" / "x").mkdir(parents=True)
        for rel in ("a/x/main", "b/x/main"):
            (repo / f"{rel}.tex").write_text("x")
            (repo / f"{rel}.pdf").write_bytes(b"%PDF")
        names = {str(d.relative_to(dest)) for _, d in plan(base, dest, [])}
        assert {"r1/a--x--main.pdf", "r1/b--x--main.pdf"} <= names, names
        # 一般的な名前 + 一般的な dir (src / v3) は repo 名に。 入れ子の repo (親が ignore) も見る
        assert target_names("r9", ["manuscript/v3/main.pdf"]) == {"manuscript/v3/main.pdf": "r9.pdf"}
        assert target_names("r9", ["paper-x/main.pdf"]) == {"paper-x/main.pdf": "paper-x.pdf"}
        inner = repo / "external" / "overleaf"
        inner.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(inner)], check=True)
        (inner / "paper.tex").write_text("x")
        (inner / "paper.pdf").write_bytes(b"%PDF inner")
        (repo / ".gitignore").write_text("external/\n")
        got = {str(d.relative_to(dest)) for s_, d in plan(base, dest, []) if "overleaf" in str(s_)}
        assert got == {"r1/external--overleaf--r1.pdf"}, got   # 親の main.pdf = r1.pdf とぶつかるので前置き
        shutil.rmtree(repo / "external")
        (repo / ".gitignore").unlink()
        # 保管庫の dir は写さない。 recent_days は、 commit も変更も無い古いものを外す
        (repo / "archive").mkdir()
        (repo / "archive" / "gone.tex").write_text("x")
        (repo / "archive" / "gone.pdf").write_bytes(b"%PDF")
        assert not any("gone" in str(d) for _, d in plan(base, dest, []))
        env = dict(os.environ, GIT_AUTHOR_DATE="2001-01-01T00:00:00", GIT_COMMITTER_DATE="2001-01-01T00:00:00")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "-c", "commit.gpgsign=false", "commit", "-qm", "old", "--no-verify"], check=True, env=env)
        shutil.rmtree(dest)
        assert plan(base, dest, [], 30) == [], "古い commit だけなら recent_days で外れる"
        (repo / "talk.pdf").write_bytes(b"%PDF rebuilt again")
        assert [d.name for _, d in plan(base, dest, [], 30)] == ["talk.pdf"]
    print("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config")
    ap.add_argument("--base")
    ap.add_argument("--dest")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--recent-days", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--prune-report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if os.environ.get("CLAUDE_PDF_SYNC") == "0":
        return 0
    cfg = json.loads(Path(a.config).expanduser().read_text(encoding="utf-8")) if a.config else {}
    base, dest = a.base or cfg.get("base"), a.dest or cfg.get("dest")
    if not base or not dest:
        ap.error("--base と --dest (または --config) が要る")
    base, dest = Path(base).expanduser(), Path(dest).expanduser()
    exclude = a.exclude + cfg.get("exclude", [])
    if a.prune_report:
        return prune_report(base, dest, exclude)
    recent = a.recent_days if a.recent_days is not None else int(cfg.get("recent_days", 0))
    return run(base, dest, exclude, a.dry_run, a.quiet, recent)


if __name__ == "__main__":
    sys.exit(main())
