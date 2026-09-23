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

組み直し (設定の "build"): build した PDF を git から外すと (conventions/repo-history-growth.md#generated-binaries)、
共同編集者が source だけ push したとき手元の PDF が古いまま / 無いままになる。 写す前に、 規則に従って
「追跡されていない ∧ 同名の .tex より古い (か無い) ∧ .tex が recent_days の内に変わった」 PDF だけを組み直す。
  {"repo": "r", "dir": "report", "cmd": "./build.sh {stem}"}      # dir 直下の \\documentclass を持つ .tex ごとに 1 回
  {"repo": "r", "docs": ["a.tex", "b/main.tex"], "cmd": "..."}   # 複数の文書を 1 回のコマンドで組む
⚠️ 追跡中の PDF は組み直さない (変更として誰かの commit に紛れ込み、 履歴を太らせる) = repo が PDF を
git から外すまで、 その repo には何もしない。 失敗は source が変わるまで再試行しない。 記録 =
~/.claude/state/sync-built-pdfs-build.{json,log}。 組み直しだけ止める: CLAUDE_PDF_BUILD=0。
"""
import argparse
import filecmp
import fnmatch
import json
import os
import re
import shlex
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
    """repo の中の「同名の .tex がある PDF」 で、 git-crypt でないもの (repo からの相対 path)。

    追跡中・未追跡に加えて **ignore されている PDF も見る** — build した PDF を git から外す
    (conventions/repo-history-growth.md#generated-binaries) と ignore 側に移るので、 見ないと写らなくなる。"""
    out = git(repo, "ls-files", "-z", "-co", "--exclude-standard", "--", "*.pdf")
    out += b"\0" + git(repo, "ls-files", "-z", "-oi", "--exclude-standard", "--", "*.pdf")
    paths = list(dict.fromkeys(p for p in out.decode("utf-8", "replace").split("\0") if p))
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


def take_lock(lock: Path) -> bool:
    """同時に 1 本だけ走らせる。 取れなければ False (別の run の lock は消さない = 消すと 2 本が並走する)。"""
    try:
        if time.time() - lock.stat().st_mtime < 300:
            return False
        lock.unlink()  # 300 秒より古い = 落ちた run の残り
    except FileNotFoundError:
        pass
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False  # 同時に起動した別の run が先に取った
    with os.fdopen(fd, "w") as fh:
        fh.write(str(os.getpid()))
    return True


# ---------------------------------------------------------------- 組み直し (build)
# git から外した PDF は、 相手が source だけ push すると手元で古いままになる。 設定の build 規則に従って
# 「追跡されていない ∧ .tex より古い (か無い) ∧ .tex が最近変わった」 PDF だけを組み直してから写す。
# ⚠️ 追跡中の PDF は組み直さない = 組み直すと変更として誰かの commit に紛れ込み、 履歴を太らせる
# (= repo が PDF を git から外すまでは、 その repo に何もしない)。
BUILD_LOCK_STALE = 3600
TEX_BINS = ("/Library/TeX/texbin", "/usr/local/bin", "/opt/homebrew/bin")


def is_root_doc(tex: Path) -> bool:
    try:
        with tex.open(encoding="utf-8", errors="replace") as fh:
            return any("\\documentclass" in line for _, line in zip(range(200), fh))
    except OSError:
        return False


def build_targets(base: Path, rules, recent_days: int):
    """build 規則 → [(実行 dir, command, [(tex, pdf), ...])]。 command 1 回で組む単位ごとにまとめる。"""
    out = []
    for r in rules:
        repo = base / r["repo"]
        if not (repo / ".git").exists():
            continue
        touched = recently_touched(repo, recent_days) if recent_days else None
        if "docs" in r:
            docs = [repo / d for d in r["docs"]]
            groups = [(repo, r["cmd"], docs)]
        else:
            d = repo / r.get("dir", "")
            docs = sorted(t for t in d.glob("*.tex") if is_root_doc(t))
            groups = [(d, r["cmd"].replace("{stem}", shlex.quote(t.stem)), [t]) for t in docs]
        for cwd, cmd, texs in groups:
            stale = []
            for tex in texs:
                pdf = tex.with_suffix(".pdf")
                rel_tex, rel_pdf = str(tex.relative_to(repo)), str(pdf.relative_to(repo))
                if not tex.is_file() or git(repo, "ls-files", "--", rel_pdf).strip():
                    continue  # 追跡中の PDF は触らない
                if pdf.exists() and pdf.stat().st_mtime + 1 >= tex.stat().st_mtime:
                    continue
                if touched is not None and rel_tex not in touched:
                    continue  # 最近変わっていない文書は、 PDF が無くても一斉には組まない
                stale.append((tex, pdf))
            if stale:
                out.append((cwd, cmd, stale, int(r.get("timeout", 600))))
    return out


def run_builds(base: Path, rules, recent_days: int, state_dir: Path, dry: bool, quiet: bool) -> None:
    if not rules or os.environ.get("CLAUDE_PDF_BUILD") == "0":
        return
    lock = Path(tempfile.gettempdir()) / f"sync-built-pdfs-build-{os.getuid()}.lock"
    try:
        if time.time() - lock.stat().st_mtime > BUILD_LOCK_STALE:
            lock.unlink()
    except FileNotFoundError:
        pass
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return  # 別の run が組んでいる
    os.close(fd)
    memo_path = state_dir / "sync-built-pdfs-build.json"
    try:
        memo = json.loads(memo_path.read_text()) if memo_path.exists() else {}
    except (OSError, ValueError):
        memo = {}
    env = dict(os.environ, PATH=":".join([b for b in TEX_BINS if Path(b).is_dir()] + [os.environ.get("PATH", "")]))
    log = []
    try:
        for cwd, cmd, stale, timeout in build_targets(base, rules, recent_days):
            key = str(stale[0][0])
            fp = max(t.stat().st_mtime for t, _ in stale)
            if memo.get(key) == fp:
                continue  # 同じ source で前回失敗した = source が変わるまで試さない
            if dry:
                if not quiet:
                    print(f"would build ({cwd}): {cmd}")
                continue
            try:
                r = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, timeout=timeout)
                ok = r.returncode == 0 and all(p.exists() and p.stat().st_mtime + 1 >= fp for _, p in stale)
            except subprocess.TimeoutExpired:
                ok = False
            if ok:
                memo.pop(key, None)
            else:
                memo[key] = fp
            log.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {'ok ' if ok else 'NG '} {cwd}: {cmd}")
            if not quiet:
                print(log[-1])
    finally:
        lock.unlink(missing_ok=True)
        if not dry:
            try:
                state_dir.mkdir(parents=True, exist_ok=True)
                memo_path.write_text(json.dumps(memo, ensure_ascii=False, indent=1))
                if log:
                    with (state_dir / "sync-built-pdfs-build.log").open("a", encoding="utf-8") as fh:
                        fh.write("\n".join(log) + "\n")
            except OSError:
                pass


def run(base: Path, dest: Path, exclude, dry: bool, quiet: bool, recent_days: int = 0,
        build_rules=None, state_dir: Path = Path("~/.claude/state").expanduser()) -> int:
    run_builds(base, build_rules or [], recent_days, state_dir, dry, quiet)
    lock = Path(tempfile.gettempdir()) / f"sync-built-pdfs-{os.getuid()}.lock"
    if not take_lock(lock):
        return 0
    try:
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
    saved = tempfile.tempdir
    try:
        with tempfile.TemporaryDirectory() as t:
            # lock を本番の run (Stop hook が毎 turn 裏で起動する) と共有しない = 並走で黙って写さない flake を避ける
            tempfile.tempdir = t
            _selftest(Path(t))
    finally:
        tempfile.tempdir = saved
    print("selftest OK")
    return 0


def _selftest(t: Path) -> None:
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
    # 別の run が lock を持つ間は写さずに退き、 その lock を消さない (消すと次の起動と 2 本が並走する)
    lk = Path(tempfile.gettempdir()) / f"sync-built-pdfs-{os.getuid()}.lock"
    lk.write_text("99999")
    run(base, dest, [], False, True)
    assert not dest.exists() and lk.exists(), "lock を持つ別の run の最中に写した / その lock を消した"
    # 300 秒より古い lock は落ちた run の残り = 取り直して写す
    stale = time.time() - 600
    os.utime(lk, (stale, stale))
    run(base, dest, [], False, True)
    assert not lk.exists(), "終わった run が lock を残した"
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
    _selftest_build(base, dest, Path(t) / "state")


def _selftest_build(base: Path, dest: Path, state: Path) -> None:
    """git から外した PDF の組み直し: 追跡していない PDF だけ・断片は組まない・失敗は source が変わるまで試さない。"""
    r2 = base / "r2"
    (r2 / "x").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r2)], check=True)
    (r2 / ".gitignore").write_text("*.pdf\n")
    (r2 / "a.tex").write_text("\\documentclass{article}\n")
    (r2 / "frag.tex").write_text("\\section{only a fragment}\n")
    (r2 / "bad.tex").write_text("\\documentclass{article}\n")
    (r2 / "x" / "y.tex").write_text("\\documentclass{article}\n")
    (r2 / "tracked.tex").write_text("\\documentclass{article}\n")
    (r2 / "tracked.pdf").write_bytes(b"%PDF tracked")
    subprocess.run(["git", "-C", str(r2), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r2), "add", "-f", "tracked.pdf"], check=True)
    subprocess.run(["git", "-C", str(r2), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", "src"], check=True)
    later = time.time() + 5
    os.utime(r2 / "tracked.tex", (later, later))   # 追跡中の PDF より .tex が新しい
    rules = [{"repo": "r2", "dir": "", "cmd": "if [ {stem} = bad ]; then exit 1; fi; cp {stem}.tex {stem}.pdf"},
             {"repo": "r2", "docs": ["x/y.tex"], "cmd": "cp x/y.tex x/y.pdf"}]
    run(base, dest, [], False, True, 30, rules, state)
    assert (r2 / "a.pdf").exists(), "ignore した PDF を組み直していない"
    assert not (r2 / "frag.pdf").exists(), "\\documentclass の無い断片を組んだ"
    assert (r2 / "x" / "y.pdf").exists(), "docs の規則 (1 コマンドで組む) が走っていない"
    assert (r2 / "tracked.pdf").read_bytes() == b"%PDF tracked", "追跡中の PDF を組み直した (commit に紛れ込む)"
    assert (dest / "r2" / "a.pdf").exists(), "ignore した PDF が写し先に写っていない"
    memo = json.loads((state / "sync-built-pdfs-build.json").read_text())
    assert str(r2 / "bad.tex") in memo, "失敗を記録していない"
    log_n = len((state / "sync-built-pdfs-build.log").read_text().splitlines())
    run(base, dest, [], False, True, 30, rules, state)
    assert len((state / "sync-built-pdfs-build.log").read_text().splitlines()) == log_n, "同じ source で失敗を繰り返した"
    newer = time.time() + 20
    os.utime(r2 / "bad.tex", (newer, newer))
    run(base, dest, [], False, True, 30, rules, state)
    assert len((state / "sync-built-pdfs-build.log").read_text().splitlines()) == log_n + 1, "source が変わっても再試行しない"


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
    return run(base, dest, exclude, a.dry_run, a.quiet, recent, cfg.get("build", []))


if __name__ == "__main__":
    sys.exit(main())
