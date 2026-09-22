#!/usr/bin/env python3
"""todo-ledger-split.py — 1 file の list (`TODO.yaml`) の TODO 台帳を 1 entry 1 file (`todo/<id>.yaml`) に分割する (既定 dry-run)。

やること (= scripts/lib/todo_ledger.py の契約に合わせる):
  1. `<repo>/TODO.yaml` を text で entry に切る (境界 = col 0 の `- id:`) → 2 space dedent → `todo/<id>.yaml` に書く。
     YAML を dump し直さない (block scalar・引用符・key 順・注釈を保つ)。 節の見出し注釈は次の entry の file の頭に残る。
  2. 読み直し照合 = 各 file を parse した mapping が元の list の該当 entry と == (全 entry)、 かつ分割後の
     `load_todos(repo)` が元の list と同じ集合 (id で照合)。 1 つでも違えば書いた file を消して exit 1。
  3. 元の `TODO.yaml` を消す (git の repo なら `git rm`、 それ以外は unlink)。 `todo/` は `git add` する。
  4. 冒頭の注釈行は `todo/README.md` に写す (置き場・書式・1 entry の例・手で足すときの手順)。

止まる条件 (書かずに exit 1): id の重複 / file 名にできない id / 照合の不一致 / `todo/<id>.yaml` が既に在って中身が違う /
  `TODO.yaml` に未 commit の変更がある / **暗号化の不一致** = `TODO.yaml` に filter (git-crypt) が付いているのに
  `todo/**` に付いていない (= 個人情報が平文で push される。 先に `.gitattributes` へ `todo/** filter=git-crypt diff=git-crypt`)。

使い方:
  python3 todo-ledger-split.py <repo>            # dry-run (何を書くか・止まる理由を出す)
  python3 todo-ledger-split.py <repo> --apply    # 書く → 照合 → TODO.yaml を消す → todo/ を git add
  python3 todo-ledger-split.py <repo> --apply --no-readme   # README を書かない
  python3 todo-ledger-split.py <repo> --apply --no-git      # git を触らない (unlink だけ)
  python3 todo-ledger-split.py --selftest

apply の後に呼び手がやること: `git-crypt status todo/` で全部 encrypted を確認 → 検出器の出力を分割前と diff →
  `git add todo/ .gitattributes && git commit -- todo/ .gitattributes TODO.yaml` (並列 session の規律 = 自分の path だけ)。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from todo_ledger import (DIR_NAME, LEGACY_NAME, TodoLedgerError, entry_text, load_todos, resolve_repo,  # noqa: E402
                         split_legacy, todo_path, write_todo)

README_NAME = "README.md"
README_TMPL = """# todo/ — TODO 台帳 (1 entry 1 file)

- 置き場 = `todo/<id>.yaml`。 **1 file = 1 entry の mapping** (list ではない)。 file 名 = entry の `id` + `.yaml`
  (id は一意・日付始まり・`[A-Za-z0-9._-]` だけ)。
- open / closed で dir を分けない (閉じるときに mv しない)。 読み手は `status` で選ぶ。 順序 = file 名順 (= id の日付順)。
- 書式 = 旧 `TODO.yaml` の entry を 2 space dedent したもの (`- id:` → `id:`)。 YAML を dump し直さない
  (block scalar・引用符・key 順・注釈を保つ)。 schema (field) は旧 file と同じ。
- **手で足すときは file を 1 つ作る** (下の例)。 道具で書くときも entry の file だけを書き、 commit は `git commit -- todo/<id>.yaml`。
- 暗号化: `.gitattributes` の `todo/** filter=git-crypt diff=git-crypt` (= 旧 `TODO.yaml` と同じ扱い。 消さない)。
- 読み書きの共通部品 = 層1 `claude-config/scripts/lib/todo_ledger.py` (`load_todos(repo)` / `write_todo(path, text)`)、
  分割の道具 = 同 `todo-ledger-split.py`。

## 1 entry の例 (`todo/2026-01-15-example-reply.yaml`)

```yaml
id: "2026-01-15-example-reply"
task: "例: 相手に返事を書く"
source: manual
status: 未対応
priority: 中
created: "2026-01-15"
deadline: "2026-01-31"
notes: |
  決定・事実・根拠だけを書く (進捗は status_context に)。
```

## 旧 `TODO.yaml` の冒頭にあった注釈 ({date} の分割で写した)

```
{header}
```
"""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def _in_git(repo: Path) -> bool:
    r = _git(repo, "rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and r.stdout.strip() == "true"


def _filter_of(repo: Path, rel: str) -> str:
    """`git check-attr filter -- <rel>` の値 (unspecified / unset / <name>)。"""
    r = _git(repo, "check-attr", "filter", "--", rel)
    if r.returncode != 0 or not r.stdout.strip():
        return "unspecified"
    return r.stdout.strip().rsplit(": ", 1)[-1]


def run(repo_arg, apply: bool = False, readme: bool = True, use_git: bool = True, out: Callable[[str], None] = print,
        today: Optional[str] = None) -> int:
    repo = resolve_repo(repo_arg)
    legacy = repo / LEGACY_NAME
    tdir = repo / DIR_NAME
    if not legacy.is_file():
        n = len(list(tdir.glob("*.yaml"))) if tdir.is_dir() else 0
        out(f"{legacy} が無い = 分割済み (todo/*.yaml {n} file)。 何もしない")
        return 0
    try:
        text = entry_text(legacy)
        header, parts = split_legacy(text)
    except TodoLedgerError as e:
        out(f"✗ {e}")
        return 1
    orig = yaml.safe_load(text)
    problems: List[str] = []
    same, to_write = [], []
    for eid, t in parts:
        p = todo_path(repo, eid)
        if p.exists():
            if p.read_text(encoding="utf-8") == t:
                same.append(eid)
            else:
                problems.append(f"{p.relative_to(repo)} が既に在って中身が違う (手で消すか、 先に照合する)")
        else:
            to_write.append((eid, t, p))
    git = use_git and _in_git(repo)
    if git:
        st = _git(repo, "status", "--porcelain", "--", LEGACY_NAME).stdout.strip()
        if st:
            problems.append(f"{LEGACY_NAME} に未 commit の変更がある ({st.split()[0]}) = 先に commit してから (別 session の分を巻き込まない)")
        lf = _filter_of(repo, LEGACY_NAME)
        tf = _filter_of(repo, f"{DIR_NAME}/{parts[0][0]}.yaml")
        if lf not in ("unspecified", "unset") and tf != lf:
            problems.append(f"暗号化の不一致: {LEGACY_NAME} は filter={lf} だが {DIR_NAME}/*.yaml は filter={tf} "
                            f"= 個人情報が平文で push される。 先に .gitattributes へ `{DIR_NAME}/** filter={lf} diff={lf}` を足す")
        else:
            out(f"  暗号化: {LEGACY_NAME} filter={lf} / {DIR_NAME}/*.yaml filter={tf} (一致)")
    carried = sum(1 for _, t in parts if t.startswith("#"))
    out(f"  {legacy.name}: entry {len(parts)} 件 (bytes {len(text.encode('utf-8')):,}) → {DIR_NAME}/<id>.yaml "
        f"{len(to_write)} 件を書く / {len(same)} 件は同じ中身で既に在る")
    out(f"  冒頭の注釈 {sum(1 for h in header if h.strip())} 行 → {DIR_NAME}/{README_NAME}" + ("" if readme else " (--no-readme = 書かない)"))
    if carried:
        out(f"  節の見出し注釈を頭に持つ file: {carried} 件 (= 元の file で直前にあった注釈)")
    if problems:
        for pr in problems:
            out(f"✗ {pr}")
        return 1
    if not apply:
        out("(dry-run。 書くには --apply)")
        return 0

    written: List[Path] = []
    try:
        for eid, t, p in to_write:
            write_todo(p, t)
            written.append(p)
        if readme and not (tdir / README_NAME).exists():
            body = "\n".join(h for h in header if h.strip()) or "(無し)"
            (tdir / README_NAME).write_text(README_TMPL.format(header=body, date=today or _today()), encoding="utf-8")
            written.append(tdir / README_NAME)
        # 読み直し照合 (旧 file がまだ在る = todo/ が勝つ順で読み、 集合を id で照合)
        got = load_todos(repo)
        by_id = {e["id"]: e for e in got}
        want = {e["id"]: e for e in orig if isinstance(e, dict)}
        if by_id != want:
            bad = sorted(k for k in set(by_id) | set(want) if by_id.get(k) != want.get(k))
            raise TodoLedgerError(f"読み直し照合に落ちた: {bad[:5]}")
    except (TodoLedgerError, OSError) as e:
        for p in written:
            try:
                p.unlink()
            except OSError:
                pass
        out(f"✗ {e} — 書いた {len(written)} file を消して戻した")
        return 1
    out(f"✓ {len(to_write)} file を書いた、 読み直し照合 OK ({len(got)} entry)")
    if git:
        r = _git(repo, "rm", "-q", "--", LEGACY_NAME)
        if r.returncode != 0:
            out(f"✗ git rm {LEGACY_NAME}: {r.stderr.strip()} (todo/ は書いてある。 手で消して commit)")
            return 1
        _git(repo, "add", "--", DIR_NAME)
        out(f"✓ git rm {LEGACY_NAME} / git add {DIR_NAME}/ (commit は呼び手: git commit -- {DIR_NAME}/ .gitattributes {LEGACY_NAME})")
    else:
        legacy.unlink()
        out(f"✓ {LEGACY_NAME} を消した")
    n = len(load_todos(repo))
    if n != len(parts):
        out(f"✗ 分割後の load_todos が {n} 件 (期待 {len(parts)})")
        return 1
    out(f"✓ 分割後: load_todos = {n} 件、 {LEGACY_NAME} 無し")
    return 0


def _today() -> str:
    import datetime
    return datetime.date.today().isoformat()


# ------------------------------------------------------------
# selftest
# ------------------------------------------------------------
FIXTURE = '''# TODO — fixture ledger
# source: a | b

- id: "2026-01-02-second"
  task: "second"
  status: open
  notes: |
    line one
    line two: with colon

# ── section ──
- id: 2026-01-01-first
  task: 'first'
  status: done
- id: "2026-01-03-third"
  task: "third"
  status: open
'''


def _selftest() -> int:
    fails = 0
    log: List[str] = []

    def check(cond, name):
        nonlocal fails
        print(("  PASS: " if cond else "  FAIL: ") + name)
        if not cond:
            fails += 1

    def pr(s):
        log.append(s)

    def joined():
        return "\n".join(log)

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "ledger"
        repo.mkdir()
        g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=False)
        g("init", "-q")
        g("config", "user.email", "t@example.org")
        g("config", "user.name", "t")
        (repo / LEGACY_NAME).write_text(FIXTURE, encoding="utf-8")
        (repo / ".gitattributes").write_text(f"{LEGACY_NAME} filter=git-crypt diff=git-crypt\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "-m", "init")
        orig = yaml.safe_load(FIXTURE)

        # T1 dry-run: 何も書かない
        log.clear()
        rc = run(repo, apply=False, out=pr, today="2026-01-10")
        check(rc == 1 and "暗号化の不一致" in joined() and not (repo / DIR_NAME).exists(),
              "T1 暗号化の不一致 (TODO.yaml は filter 付き、 todo/** は無し) は dry-run でも止まり、 何も書かない")
        (repo / ".gitattributes").write_text(f"{LEGACY_NAME} filter=git-crypt diff=git-crypt\n{DIR_NAME}/** filter=git-crypt diff=git-crypt\n",
                                             encoding="utf-8")
        g("add", ".gitattributes")
        g("commit", "-q", "-m", "attr")
        log.clear()
        rc = run(repo, apply=False, out=pr, today="2026-01-10")
        check(rc == 0 and "dry-run" in joined() and "entry 3 件" in joined() and not (repo / DIR_NAME).exists(),
              "T2 dry-run: 件数を出し、 何も書かない")
        # T3 未 commit の変更があれば止まる
        (repo / LEGACY_NAME).write_text(FIXTURE + "- id: x\n  task: dirty\n", encoding="utf-8")
        log.clear()
        rc = run(repo, apply=True, out=pr, today="2026-01-10")
        check(rc == 1 and "未 commit" in joined() and not (repo / DIR_NAME).exists(), "T3 TODO.yaml に未 commit の変更 = 書かない")
        (repo / LEGACY_NAME).write_text(FIXTURE, encoding="utf-8")
        # T4 apply
        log.clear()
        rc = run(repo, apply=True, out=pr, today="2026-01-10")
        files = sorted(p.name for p in (repo / DIR_NAME).glob("*.yaml"))
        check(rc == 0 and files == ["2026-01-01-first.yaml", "2026-01-02-second.yaml", "2026-01-03-third.yaml"],
              "T4 apply: todo/<id>.yaml を書く")
        check(not (repo / LEGACY_NAME).exists() and LEGACY_NAME not in g("ls-files").stdout
              and f"{DIR_NAME}/2026-01-01-first.yaml" in g("ls-files").stdout,
              "T4 apply: TODO.yaml を git rm、 todo/ を git add")
        check({e["id"]: e for e in load_todos(repo)} == {e["id"]: e for e in orig}, "T4 apply: load_todos == 元の list (id で照合)")
        check((repo / DIR_NAME / "2026-01-01-first.yaml").read_text(encoding="utf-8").startswith("# ── section ──\nid: 2026-01-01-first\n"),
              "T4 apply: 節の注釈は次の entry の file の頭に残る")
        rd = (repo / DIR_NAME / README_NAME).read_text(encoding="utf-8")
        check("# TODO — fixture ledger" in rd and "2026-01-10" in rd and "todo/** filter=git-crypt" in rd,
              "T4 apply: README に冒頭の注釈と暗号化の行")
        check(g("check-attr", "filter", "--", f"{DIR_NAME}/2026-01-01-first.yaml").stdout.strip().endswith("git-crypt"),
              "T4 apply: todo/*.yaml に filter が付いている")
        # T5 冪等 (TODO.yaml が無い)
        log.clear()
        rc = run(repo, apply=True, out=pr, today="2026-01-10")
        check(rc == 0 and "分割済み" in joined(), "T5 TODO.yaml が無ければ何もしない (exit 0)")
        # T6 既存 file と中身が違う → 止まる (旧 file を戻して再実行)
        (repo / LEGACY_NAME).write_text(FIXTURE, encoding="utf-8")
        g("add", LEGACY_NAME)
        g("commit", "-q", "-m", "legacy back")
        (repo / DIR_NAME / "2026-01-03-third.yaml").write_text('id: "2026-01-03-third"\ntask: "CHANGED"\n', encoding="utf-8")
        log.clear()
        rc = run(repo, apply=True, out=pr, today="2026-01-10")
        check(rc == 1 and "中身が違う" in joined() and (repo / LEGACY_NAME).exists(), "T6 todo/<id>.yaml が在って中身が違えば止まる")
        (repo / DIR_NAME / "2026-01-03-third.yaml").write_text(
            next(t for i, t in split_legacy(FIXTURE)[1] if i == "2026-01-03-third"), encoding="utf-8")
        log.clear()
        rc = run(repo, apply=True, out=pr, today="2026-01-10")
        check(rc == 0 and "0 件を書く / 3 件は同じ中身で既に在る" in joined() and not (repo / LEGACY_NAME).exists(),
              "T6' 同じ中身なら通る (書かずに TODO.yaml だけ消す)")
        # T7 --no-git (plain dir): unlink
        plain = Path(td) / "plain"
        plain.mkdir()
        (plain / LEGACY_NAME).write_text(FIXTURE, encoding="utf-8")
        log.clear()
        rc = run(plain, apply=True, use_git=False, readme=False, out=pr, today="2026-01-10")
        check(rc == 0 and not (plain / LEGACY_NAME).exists() and not (plain / DIR_NAME / README_NAME).exists()
              and len(load_todos(plain)) == 3, "T7 --no-git --no-readme: unlink だけ、 README 無し")
        # T8 id の重複 / 壊れた YAML は書かない
        bad = Path(td) / "bad"
        bad.mkdir()
        (bad / LEGACY_NAME).write_text('- id: a\n  x: 1\n- id: a\n  x: 2\n', encoding="utf-8")
        log.clear()
        rc = run(bad, apply=True, use_git=False, out=pr, today="2026-01-10")
        check(rc == 1 and "重複" in joined() and not (bad / DIR_NAME).exists(), "T8 id の重複は書かずに止まる")
        # 直す前に赤くなる対照: 旧来の読み手 (yaml.safe_load(TODO.yaml)) は分割後の repo を読めない
        try:
            yaml.safe_load((repo / LEGACY_NAME).read_text(encoding="utf-8"))
            old_reader_ok = True
        except FileNotFoundError:
            old_reader_ok = False
        check(not old_reader_ok and len(load_todos(repo)) == 3,
              "対照: 旧来の読み手 (TODO.yaml を直に開く) は分割後に読めず、 loader は 3 件読む")
    print(f"selftest: {'ALL PASS' if not fails else f'FAIL {fails}'}")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TODO.yaml (list) → todo/<id>.yaml (1 entry 1 file) の分割 (既定 dry-run)")
    ap.add_argument("repo", nargs="?", help="repo dir (または TODO.yaml の path)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-readme", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.repo:
        ap.error("repo を渡す (または --selftest)")
    return run(args.repo, apply=args.apply, readme=not args.no_readme, use_git=not args.no_git)


if __name__ == "__main__":
    sys.exit(main())
