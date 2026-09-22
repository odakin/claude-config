#!/usr/bin/env python3
"""check-degenerate-text.py — script 置換の暴走で壊れた text file (1 行の異常な繰り返し / HEAD 比の爆発的な増加) を commit で止める + fleet を走査して surface する。

由来 (実測): 一括置換 script が `old = s[s.index(A):s.index(B)]` で節を切り出したところ、 B が file 内でもっと前にも
在って slice が start > end = 空文字列になり、 `s.replace('', new)` (= Python は「先頭・各文字の間・末尾」 に挿入する)
が全文字の間に new を差し込んだ。 数百行の設計 doc が十数万行 (数 MB) になって push され、 しばらくどの検出器も
鳴らなかった (肥大検出器は CLAUDE/SESSION.md 限定、 切り詰め検出器は縮小しか見ない、 pre-commit にサイズの門が無い、
書いた session は `commit -q | tail` で stat を捨てていた)。 規律側 = conventions/batch-text-edits.md#computed-old-empty。

2 つの面 (同じ述語):
  --staged [--repo DIR]   commit gate。 stage した hand-edited text (GATE_EXTS) を index の blob で読み (git-crypt は
                          lib/git_blob で平文)、 HEAD の同じ file と比べる。 呼び元 = scripts/pre-commit-bib と
                          scripts/public-precommit-runner.sh (「exit 1 かつ見出し `check-degenerate-text:`」 のときだけ止める)
  [--root DIR]... [PATH]... fleet scan (既定)。 root 直下の各 git repo (root 自身が repo ならそれ) の track 済み prose
                          (SCAN_EXTS) を worktree で読み、 繰り返しの異常だけを 🔴 で出す。 発火面 = dashboard + SessionStart
                          (--surface = 枠なし) + CI (--strict = finding で exit 1)

述語 (閾値は本 file だけが持つ。 値の根拠 = 数千の text file を持つ fleet の実測):
  content line = strip 後 40 字以上 かつ 異なる文字 8 種以上 (= `$$` / ``` / `* * *` / `%+++++` / `# ═══` の装飾行を除く。
                 装飾行は正常な .md で最大 140 回、 .tex で 458 回並ぶ)
  G2 繰り返し   = content line が REPEAT_MIN (200) 回以上 かつ HEAD での同じ行の回数の REPEAT_RATIO (10) 倍以上 → 止める
                 (fleet の正常最大 = .txt の log 73 回 / .md 46 回未満 / YAML の定型行 472 回 〔HEAD 比で守る〕。 事故 = 2 万回超)。
                 HEAD に無い新規 file の絶対値は prose (SCAN_EXTS) だけ = 生成 data の YAML / code は新規でも同じ長い行が
                 数百回並ぶ (実測: 公開 repo の履歴に 208 回の report)
  G1 増加       = HEAD の GROWTH_RATIO (10) 倍以上 かつ GROWTH_MIN_ADDED (1,000) 行以上の追加 → 止める
                 (5 行の骨組みを 300 行に育てる・40 行の SESSION を 600 行にするのは止めない。 事故 = 300 倍超)
  W1 縮小       = SHRINK_MIN_REMOVED (200) 行以上減り、 HEAD の SHRINK_FRACTION (1/2) 以下 → ⚠️ を出すだけ (縮退は正当な操作)
  fleet scan は G2 の絶対値だけ (HEAD が無いので比は取れない。 YAML は定型行が正常に数百回並ぶので対象外 = 別の検出器)

exit: 0 = 通す (W1 は出しても 0) / 1 = 止める (--staged) or finding (--strict) / 3 = 検査が走っていない (git repo でない等。
      1 行出す。 呼び元は 1 以外で止めない = docs/convention-design-principles.md#failure-exit-equals-violation-exit)
escape hatch: CLAUDE_DEGENERATE_TEXT_GUARD=0 (意図した大量追加・JSON の整形など) / git 標準の --no-verify
selftest: python3 check-degenerate-text.py --selftest (一時 repo で陽性対照 = replace('') の壊れ、 陰性対照 = 骨組みの成長・
          定型行の多い YAML・装飾行・縮退、 pre-commit-bib を hook に据えた e2e = その検査が止めたことまで見る)
"""
from __future__ import annotations

import argparse
import collections
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    from git_blob import read_blob  # git-crypt の path も平文で読む
except Exception:  # pragma: no cover
    read_blob = None  # type: ignore[assignment]

HEADING = "check-degenerate-text:"
ENV_SKIP = "CLAUDE_DEGENERATE_TEXT_GUARD"
DOC_ANCHOR = "conventions/batch-text-edits.md#computed-old-empty"

# 閾値 (SoT = ここだけ。 根拠は docstring の fleet 実測)
MIN_LINE_CHARS = 40
MIN_DISTINCT_CHARS = 8
REPEAT_MIN = 200
REPEAT_RATIO = 10
GROWTH_RATIO = 10
GROWTH_MIN_ADDED = 1000
SHRINK_MIN_REMOVED = 200
SHRINK_FRACTION = 0.5

# commit gate の対象 = 手で編集する text。 data / 生成物 (.json .csv .svg .xml .ipynb .lock .log) は 10 倍の増減が正当に起きるので圏外
GATE_EXTS = {
    ".md", ".markdown", ".rst", ".txt", ".tex", ".bib", ".sty", ".cls",
    ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".html", ".css",
}
# fleet scan の対象 = prose (YAML の定型行は正常に数百回並ぶので入れない)
SCAN_EXTS = {".md", ".markdown", ".rst", ".txt", ".tex"}
GITCRYPT_MAGIC = b"\x00GITCRYPT"


# ---------------------------------------------------------------- 述語
def is_content_line(line: str) -> bool:
    s = line.strip()
    return len(s) >= MIN_LINE_CHARS and len(set(s)) >= MIN_DISTINCT_CHARS


def line_count(text: str) -> int:
    return len(text.splitlines())


def max_repeat(text: str) -> Tuple[int, str]:
    """content line の最頻行とその回数。 無ければ (0, '')。"""
    c = collections.Counter(ln.strip() for ln in text.splitlines() if is_content_line(ln))
    if not c:
        return 0, ""
    line, n = c.most_common(1)[0]
    return n, line


def count_line(text: Optional[str], line: str) -> int:
    if not text or not line:
        return 0
    return sum(1 for ln in text.splitlines() if ln.strip() == line)


def looks_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def _short(line: str, n: int = 60) -> str:
    return line if len(line) <= n else line[: n - 1] + "…"


def judge(staged: str, head: Optional[str], prose: bool = True) -> Tuple[List[str], List[str]]:
    """(止める理由の list, 警告の list)。 文言は path を含まない (呼び元が付ける)。
    prose=False (YAML / code) の新規 file は G2 の絶対値で止めない = 生成 data (report / cache) は新規でも同じ長い行が
    数百回並ぶ (実測: 公開 repo の履歴に 208 回の YAML report)。 既存 file なら HEAD 比で守る。"""
    blocks: List[str] = []
    warns: List[str] = []
    sl = line_count(staged)
    hl = line_count(head) if head is not None else None
    n, line = max_repeat(staged)
    if n >= REPEAT_MIN and (head is not None or prose):
        base = count_line(head, line)
        if n >= REPEAT_RATIO * base:
            blocks.append(f"1 行が {n:,} 回 (HEAD では {base:,} 回) — script 置換の暴走の疑い\n      「{_short(line)}」")
    if hl is not None and hl >= 1 and sl >= GROWTH_RATIO * hl and sl - hl >= GROWTH_MIN_ADDED:
        blocks.append(f"{hl:,} → {sl:,} 行 ({sl / hl:,.0f} 倍、 +{sl - hl:,}) — 爆発的な増加")
    if hl is not None and hl - sl >= SHRINK_MIN_REMOVED and sl <= hl * SHRINK_FRACTION:
        warns.append(f"{hl:,} → {sl:,} 行 (-{hl - sl:,}) — 意図した縮退でなければ確認 (止めない)")
    return blocks, warns


# ---------------------------------------------------------------- git helpers
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=False)


def repo_root(start: Path) -> Optional[Path]:
    r = _git(start, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        return None
    return Path(r.stdout.decode("utf-8", "replace").strip())


def staged_paths(repo: Path) -> List[str]:
    r = _git(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    if r.returncode != 0:
        raise RuntimeError("git diff --cached が失敗: " + r.stderr.decode("utf-8", "replace").strip())
    return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]


def blob_text(repo: Path, spec: str) -> Optional[str]:
    """index (":path") / HEAD ("HEAD:path") の blob を平文で。 無い・binary なら None。"""
    if read_blob is not None:
        rc, data = read_blob(spec, cwd=str(repo), timeout=20)
    else:  # pragma: no cover
        r = _git(repo, "show", spec)
        rc, data = r.returncode, r.stdout
    if rc != 0 or looks_binary(data):
        return None
    return data.decode("utf-8", "replace")


def head_exists(repo: Path) -> bool:
    return _git(repo, "rev-parse", "--verify", "-q", "HEAD").returncode == 0


# ---------------------------------------------------------------- --staged
def run_staged(repo_arg: Optional[str]) -> int:
    if os.environ.get(ENV_SKIP, "1") == "0":
        print(f"{HEADING} skipped ({ENV_SKIP}=0)")
        return 0
    repo = repo_root(Path(repo_arg) if repo_arg else Path.cwd())
    if repo is None:
        print(f"⚠️ {HEADING} 検査が走っていない (git repo でない: {repo_arg or os.getcwd()})")
        return 3
    try:
        paths = staged_paths(repo)
        has_head = head_exists(repo)
        blocked: List[Tuple[str, List[str]]] = []
        warned: List[Tuple[str, List[str]]] = []
        for p in paths:
            if Path(p).suffix.lower() not in GATE_EXTS:
                continue
            staged = blob_text(repo, f":{p}")
            if staged is None:
                continue
            head = blob_text(repo, f"HEAD:{p}") if has_head else None
            blocks, warns = judge(staged, head, prose=Path(p).suffix.lower() in SCAN_EXTS)
            if blocks:
                blocked.append((p, blocks))
            if warns:
                warned.append((p, warns))
    except Exception as e:  # engine の故障は違反と別の値で
        print(f"⚠️ {HEADING} 検査が走っていない ({type(e).__name__}: {e})")
        return 3
    for p, ws in warned:
        for w in ws:
            print(f"⚠️ {HEADING} {p}: {w}")
    if not blocked:
        return 0
    for p, bs in blocked:
        for b in bs:
            print(f"{HEADING} ✗ {p}: {b}")
    print(
        f"\n{HEADING} 止めた = 一括置換の old が空 / 二重挿入 / 切り出しの取り違え の形。 直し方 = git の直前の版に\n"
        f"  意図した差分だけを当て直す ({DOC_ANCHOR})。 意図した変更 (大量の正当な追加・整形) なら\n"
        f"  {ENV_SKIP}=0 git commit … か --no-verify"
    )
    return 1


# ---------------------------------------------------------------- fleet scan
def iter_repos(root: Path) -> List[Path]:
    if (root / ".git").exists():
        return [root]
    out: List[Path] = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if d.is_dir() and (d / ".git").exists():
            out.append(d)
    return out


def scan_repo(repo: Path) -> List[str]:
    r = _git(repo, "ls-files", "-z")
    if r.returncode != 0:
        return []
    findings: List[str] = []
    for rel in r.stdout.decode("utf-8", "replace").split("\0"):
        if not rel or Path(rel).suffix.lower() not in SCAN_EXTS:
            continue
        p = repo / rel
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if not data or data.startswith(GITCRYPT_MAGIC) or looks_binary(data):
            continue
        n, line = max_repeat(data.decode("utf-8", "replace"))
        if n >= REPEAT_MIN:
            findings.append(f"🔴 {repo.name}/{rel}: 1 行が {n:,} 回 「{_short(line, 48)}」 = script 置換の暴走の疑い"
                            f" → git の直前の版 + 意図した差分で復元 ({DOC_ANCHOR})")
    return findings


def run_scan(roots: List[str], paths: List[str], surface: bool, strict: bool) -> int:
    targets: List[Path] = []
    for r in roots:
        targets.extend(iter_repos(Path(r).expanduser()))
    for p in paths:
        pp = Path(p).expanduser()
        rr = repo_root(pp if pp.is_dir() else pp.parent)
        if rr and rr not in targets:
            targets.append(rr)
    if not targets:
        print(f"⚠️ {HEADING} 走査対象の git repo が無い (roots={roots} paths={paths})")
        return 3
    findings: List[str] = []
    for repo in targets:
        findings.extend(scan_repo(repo))
    if not findings:
        return 0
    if not surface:
        print(f"{HEADING} {len(findings)} 件 (repo {len(targets)} 本を走査)")
    for f in findings:
        print(f)
    return 1 if strict else 0


# ---------------------------------------------------------------- selftest
def selftest() -> int:
    import shutil
    import tempfile

    fails: List[str] = []
    here = Path(__file__).resolve()

    def check(label: str, ok: bool) -> None:
        print(("  ok: " if ok else "  NG: ") + label)
        if not ok:
            fails.append(label)

    def env_for(home: Path) -> Dict[str, str]:
        e = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                 GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                 GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        e.pop(ENV_SKIP, None)
        return e

    def git(repo: Path, *args: str, env: Dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(repo), env=env, capture_output=True, text=True, check=False)

    def gate(repo: Path, env: Dict[str, str], **extra: str) -> Tuple[int, str]:
        r = subprocess.run([sys.executable, str(here), "--staged", "--repo", str(repo)],
                           env=dict(env, **extra), capture_output=True, text=True, check=False)
        return r.returncode, r.stdout + r.stderr

    def commit_file(repo: Path, rel: str, text: str, env: Dict[str, str], msg: str = "c") -> None:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
        assert git(repo, "add", rel, env=env).returncode == 0
        r = git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", msg, env=env)
        assert r.returncode == 0, r.stderr

    def stage(repo: Path, rel: str, text: str, env: Dict[str, str]) -> None:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
        assert git(repo, "add", rel, env=env).returncode == 0

    prose = "\n".join(f"段落 {i}: これは十分に長い本文の行で、 内容は行ごとに違う ({i * 7919 % 1000:03d})。" for i in range(30)) + "\n"
    block = "### lint\n\n`~/x/scripts/validate-something.py`:\n- 全 entry の status / category を enum に照合 (dashboard 統合済、 0 件なら無音)\n\n"
    long_line = "  url: https://example.invalid/j/0123456789?pwd=abcdefghijklmnop  # 定型行"

    with tempfile.TemporaryDirectory() as td:
        home = Path(td, "home"); home.mkdir()
        env = env_for(home)
        root = Path(td, "root"); root.mkdir()

        # --- 陽性対照: replace('') の壊れ
        r1 = root / "r1"; r1.mkdir(); git(r1, "init", "-q", env=env)
        commit_file(r1, "DESIGN.md", prose, env)
        stage(r1, "DESIGN.md", prose.replace("", block), env)
        rc, out = gate(r1, env)
        check("陽性対照: replace('') で壊れた .md を止める (rc 1 + 見出し)", rc == 1 and f"{HEADING} ✗ DESIGN.md" in out and "回" in out)
        rc, out = gate(r1, env, **{ENV_SKIP: "0"})
        check("escape hatch: env=0 なら通す (skip を 1 行出す)", rc == 0 and "skipped" in out)

        # --- 爆発的な増加 (繰り返し無し)
        r2 = root / "r2"; r2.mkdir(); git(r2, "init", "-q", env=env)
        commit_file(r2, "notes.md", "\n".join(f"line {i}" for i in range(50)) + "\n", env)
        stage(r2, "notes.md", "\n".join(f"unique content line number {i} with padding text {i * 31}" for i in range(2000)) + "\n", env)
        rc, out = gate(r2, env)
        check("G1: 50 → 2,000 行 (繰り返し無し) を止める", rc == 1 and "爆発的な増加" in out)

        # --- 正当な成長 / 定型行の多い YAML / 装飾行 / 縮退 / 圏外の拡張子 / 新規 file の絶対値
        r3 = root / "r3"; r3.mkdir(); git(r3, "init", "-q", env=env)
        commit_file(r3, "plan.md", "# plan\n\n- a\n- b\n- c\n", env)
        stage(r3, "plan.md", "# plan\n\n" + "\n".join(f"- 手順 {i}: 十分に長い説明の行 ({i * 13})。" for i in range(300)) + "\n", env)
        rc, out = gate(r3, env)
        check("陰性: 5 行の骨組みを 300 行に育てるのは通す", rc == 0 and "✗" not in out)
        commit_file(r3, "cache.yaml", "items:\n" + (long_line + "\n") * 500, env)
        stage(r3, "cache.yaml", "items:\n" + (long_line + "\n") * 520, env)
        rc, out = gate(r3, env)
        check("陰性: HEAD に 500 回ある定型行が 520 回になるのは通す (HEAD 比)", rc == 0 and "✗" not in out)
        stage(r3, "deco.tex", ("%" + "+" * 60 + "\n") * 500 + ("$$\n") * 500, env)
        rc, out = gate(r3, env)
        check("陰性: 装飾行 (%+++ / $$) の繰り返しは content line でない", rc == 0 and "✗" not in out)
        stage(r3, "data.json", ('{"k": "' + "v" * 50 + '"},\n') * 500, env)
        rc, out = gate(r3, env)
        check("陰性: .json は commit gate の圏外", rc == 0 and "✗" not in out)
        stage(r3, "new.md", (long_line + "\n") * 300, env)
        rc, out = gate(r3, env)
        check("新規 file: 同じ content line 300 回は絶対値で止める", rc == 1 and "new.md" in out)
        git(r3, "reset", "-q", env=env)
        stage(r3, "report.yaml", "items:\n" + (long_line + "\n") * 300, env)
        rc, out = gate(r3, env)
        check("陰性: 新規の YAML (生成 data) に同じ長い行 300 回は通す (絶対値は prose だけ)", rc == 0 and "✗" not in out)
        git(r3, "reset", "-q", env=env)
        big = "\n".join(f"line {i} of a long session log with enough text {i}" for i in range(600)) + "\n"
        commit_file(r3, "SESSION.md", big, env)
        stage(r3, "SESSION.md", "\n".join(big.splitlines()[:50]) + "\n", env)
        rc, out = gate(r3, env)
        check("W1: 600 → 50 行の縮退は ⚠️ を出すが止めない", rc == 0 and "⚠️" in out and "縮退" in out)

        # --- 検査が走っていない = 3
        nog = Path(td, "not-a-repo"); nog.mkdir()
        r = subprocess.run([sys.executable, str(here), "--staged", "--repo", str(nog)], env=env,
                           capture_output=True, text=True, check=False)
        check("git repo でなければ rc 3 + 1 行", r.returncode == 3 and "走っていない" in r.stdout)

        # --- fleet scan: 壊れた file を --no-verify で commit した repo を root 直下から見つける
        git(r1, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "corrupt", env=env)
        r = subprocess.run([sys.executable, str(here), "--root", str(root)], env=env, capture_output=True, text=True, check=False)
        check("fleet scan: root 直下の repo から壊れた .md を 🔴 で出す (rc 0)", r.returncode == 0 and "🔴 r1/DESIGN.md" in r.stdout
              and "r2/" not in r.stdout and "r3/" not in r.stdout)
        r = subprocess.run([sys.executable, str(here), "--root", str(root), "--strict", "--surface"], env=env,
                           capture_output=True, text=True, check=False)
        check("fleet scan --strict --surface: finding で rc 1、 枠なし", r.returncode == 1 and r.stdout.startswith("🔴 "))
        r = subprocess.run([sys.executable, str(here), "--root", str(r3)], env=env, capture_output=True, text=True, check=False)
        check("fleet scan: 正常な repo は無音", r.returncode == 0 and r.stdout.strip() == "")
        r = subprocess.run([sys.executable, str(here), "--root", str(Path(td, "nothing-here"))], env=env,
                           capture_output=True, text=True, check=False)
        check("fleet scan: 対象 repo が無ければ rc 3", r.returncode == 3)

        # --- e2e: pre-commit-bib を hook に据えて「その検査が止めた」 ことまで見る
        hook_src = here.parent / "pre-commit-bib"
        if hook_src.exists() and shutil.which("bash"):
            r4 = root / "r4"; r4.mkdir(); git(r4, "init", "-q", env=env)
            (r4 / ".git" / "hooks" / "pre-commit").symlink_to(hook_src)
            commit_file(r4, "doc.md", prose, env)
            stage(r4, "doc.md", prose.replace("", block), env)
            r = git(r4, "commit", "-q", "-m", "bad", env=env)
            check("e2e: pre-commit-bib が壊れた .md の commit を止める (見出し付き)",
                  r.returncode != 0 and HEADING in (r.stdout + r.stderr))
            stage(r4, "doc.md", prose + "追記: 正常な 1 行。\n", env)
            r = git(r4, "commit", "-q", "-m", "good", env=env)
            check("e2e: 正常な変更は pre-commit-bib を通る", r.returncode == 0)
        else:
            print("  skip: pre-commit-bib が隣に無い (e2e)")

    print(f"\nselftest: {'PASS' if not fails else 'FAIL'} ({len(fails)} NG)")
    return 0 if not fails else 1


# ---------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="script 置換の暴走で壊れた text を commit で止める / fleet を走査する")
    ap.add_argument("paths", nargs="*", help="fleet scan: file か dir (その git repo を走査)")
    ap.add_argument("--root", action="append", default=[], help="fleet scan: この dir 直下の各 git repo (dir 自身が repo ならそれ)。 繰り返し可")
    ap.add_argument("--staged", action="store_true", help="commit gate: 現 repo の index を HEAD と比べる")
    ap.add_argument("--repo", help="--staged の repo (既定 = cwd)")
    ap.add_argument("--surface", action="store_true", help="fleet scan: finding 行だけ (SessionStart 用)")
    ap.add_argument("--strict", action="store_true", help="fleet scan: finding があれば exit 1 (CI 用)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.staged:
        return run_staged(a.repo)
    roots = a.root or ([] if a.paths else ["."])
    return run_scan(roots, a.paths, a.surface, a.strict)


if __name__ == "__main__":
    sys.exit(main())
