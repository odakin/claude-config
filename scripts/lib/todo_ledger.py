#!/usr/bin/env python3
"""todo_ledger.py — 1 entry 1 file の TODO 台帳 (`<repo>/todo/<id>.yaml`) の読み書き (単一 home)。

なぜ存在するか (一般形、 実測は下の層の記録):
  TODO 台帳を 1 file の list (`TODO.yaml`) で持つと、 暗号化 (git-crypt) の下では版ごとに全文の blob が
  積まれ (差分圧縮が効かない = 1 commit の増分 ≈ file の大きさ)、 並列 session が同じ file に追記して
  衝突する。 1 entry 1 file にすると増分は触った entry の大きさになり、 別 entry の commit は別 file で衝突しない。
  読み手 (検出器 ~40 本) がそれぞれ `yaml.safe_load(TODO.yaml)` を持つと移行のたびに全部を触るので、
  読み方を本 module 1 つに寄せる。

契約:
  1. 置き場 = `<repo>/todo/<id>.yaml`。 1 file = 1 entry の **mapping** (list ではない)。 file 名 = entry の `id` + `.yaml`
     (id は一意・path safe = `[A-Za-z0-9._-]`、 先頭は英数字)。 open / closed で dir を分けない (閉じるときに mv しない、
     読み手は `status` で選ぶ)。
  2. 書式 = 旧 list 形の entry の text を 2 space dedent したもの (先頭行 `- id:` → `id:`、 以下の行は先頭 2 space を落とす)。
     YAML を dump し直さない (block scalar・引用符・key 順・注釈を保つ = 散文の書式に依存する読み手を壊さない)。
  3. 読み = `todo/*.yaml` を file 名順 (= id 順 = 日付順)。 旧 `TODO.yaml` が残っていればそれも読み、 同じ id は
     `todo/` 側が勝つ (= 移行中も動く。 旧 file の entry は todo/ に無いものだけ、 旧 file の順で後ろに続く)。
  4. file の `id` ≠ file 名 / mapping でない / parse できない / 暗号文のまま (git-crypt locked) = `TodoLedgerError`
     (黙って読み飛ばさない。 fail-open にしたい読み手は自分で捕まえる)。
  5. 書き手は **entry の file だけ**を書く (`write_todo` = text をそのまま書く。 書く前に parse して id と file 名を照合)。

使い方:
    sys.path.insert(0, str(Path.home() / "Claude" / "claude-config" / "scripts" / "lib"))
    from todo_ledger import load_todos, load_todos_with_paths, todo_path, write_todo, TodoLedgerError
    for e in load_todos(repo_dir): ...                 # repo dir / todo dir / 旧 TODO.yaml の path のどれでも可
    for path, e in load_todos_with_paths(repo_dir): ... # 書き手向け (旧 file の entry は path = TODO.yaml)
    globs = todo_globs(repo_dir)                       # 生 text を grep する読み手向け
    python3 todo_ledger.py                             # selftest (引数なし)

移行 (旧 TODO.yaml → todo/*.yaml) = scripts/todo-ledger-split.py (本 module の split_legacy を使う)。
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML が必要: pip install pyyaml")

LEGACY_NAME = "TODO.yaml"
DIR_NAME = "todo"
GIT_CRYPT_MAGIC = b"\x00GITCRYPT"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class TodoLedgerError(ValueError):
    """台帳の file が契約を満たさない (id と file 名の不一致 / mapping でない / 読めない / 暗号文)。"""


# ------------------------------------------------------------
# path
# ------------------------------------------------------------
def resolve_repo(p) -> Path:
    """repo dir / `<repo>/todo` / `<repo>/TODO.yaml` のどれを渡されても repo dir を返す。"""
    p = Path(p).expanduser()
    if p.name == LEGACY_NAME:
        return p.parent
    if p.name == DIR_NAME and p.is_dir() and not (p / DIR_NAME).is_dir() and not (p / LEGACY_NAME).exists():
        return p.parent
    return p


def todo_dir(repo) -> Path:
    return resolve_repo(repo) / DIR_NAME


def legacy_path(repo) -> Path:
    return resolve_repo(repo) / LEGACY_NAME


def legacy_present(repo) -> bool:
    return legacy_path(repo).is_file()


def is_safe_id(eid) -> bool:
    return isinstance(eid, str) and bool(SAFE_ID_RE.match(eid)) and eid not in (".", "..")


def todo_path(repo, eid: str) -> Path:
    if not is_safe_id(eid):
        raise TodoLedgerError(f"file 名にできない id: {eid!r}")
    return todo_dir(repo) / f"{eid}.yaml"


def todo_files(repo) -> List[Path]:
    """`todo/*.yaml` を file 名順 (README.md 等は含めない)。"""
    d = todo_dir(repo)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.yaml") if p.is_file())


def todo_globs(repo) -> List[str]:
    """生 text を grep する読み手向けの glob (todo/*.yaml + 移行中の旧 TODO.yaml)。"""
    r = resolve_repo(repo)
    return [str(r / DIR_NAME / "*.yaml"), str(r / LEGACY_NAME)]


# ------------------------------------------------------------
# 1 file
# ------------------------------------------------------------
def _read_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise TodoLedgerError(f"{path}: 読めない ({e.__class__.__name__})") from e
    if raw.startswith(GIT_CRYPT_MAGIC):
        raise TodoLedgerError(f"{path}: 暗号文のまま (git-crypt locked)")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise TodoLedgerError(f"{path}: UTF-8 として読めない") from e


def entry_text(path) -> str:
    return _read_text(Path(path))


def parse_entry_text(text: str, path: Optional[Path] = None) -> dict:
    """1 entry の text (mapping) を parse して検査する。 path を渡せば id と file 名も照合する。"""
    where = str(path) if path else "<text>"
    try:
        data = yaml.load(text, Loader=_LOADER)
    except yaml.YAMLError as e:
        raise TodoLedgerError(f"{where}: YAML として読めない ({str(e).splitlines()[0] if str(e) else e})") from e
    if not isinstance(data, dict):
        raise TodoLedgerError(f"{where}: 1 entry の mapping でない ({type(data).__name__})")
    eid = data.get("id")
    if not isinstance(eid, str) or not eid.strip():
        raise TodoLedgerError(f"{where}: id が無い")
    if path is not None and Path(path).stem != eid:
        raise TodoLedgerError(f"{path}: id {eid!r} が file 名と違う")
    return data


def read_todo(path) -> dict:
    p = Path(path)
    return parse_entry_text(_read_text(p), p)


def write_todo(path, text: str) -> Path:
    """text をそのまま書く (書く前に parse し、 id と file 名を照合。 末尾は改行 1 つ)。"""
    p = Path(path)
    text = text.rstrip("\n") + "\n"
    parse_entry_text(text, p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------
# 台帳全体
# ------------------------------------------------------------
def _load_legacy_list(path: Path) -> List[dict]:
    text = _read_text(path)
    try:
        data = yaml.load(text, Loader=_LOADER)
    except yaml.YAMLError as e:
        raise TodoLedgerError(f"{path}: YAML として読めない ({str(e).splitlines()[0] if str(e) else e})") from e
    if data is None:
        return []
    if not isinstance(data, list):
        raise TodoLedgerError(f"{path}: entry の list でない ({type(data).__name__})")
    return [x for x in data if isinstance(x, dict)]


def load_todos_with_paths(repo) -> List[Tuple[Path, dict]]:
    """[(file, entry)]。 todo/*.yaml (file 名順) + 旧 TODO.yaml の残り (旧 file の順、 path = TODO.yaml)。"""
    r = resolve_repo(repo)
    out: List[Tuple[Path, dict]] = []
    seen = set()
    for p in todo_files(r):
        e = read_todo(p)
        out.append((p, e))
        seen.add(e["id"])
    lp = r / LEGACY_NAME
    if lp.is_file():
        for e in _load_legacy_list(lp):
            eid = e.get("id")
            if isinstance(eid, str) and eid in seen:
                continue
            out.append((lp, e))
    return out


def load_todos(repo) -> List[dict]:
    """entry の list (todo/*.yaml を file 名順 + 旧 TODO.yaml の残り)。 読めない file は TodoLedgerError。"""
    return [e for _, e in load_todos_with_paths(repo)]


def find_todo(repo, eid: str) -> Optional[Tuple[Path, dict]]:
    for p, e in load_todos_with_paths(repo):
        if e.get("id") == eid:
            return p, e
    return None


# ------------------------------------------------------------
# 旧 list 形 ⇄ 1 entry の text (移行 script と書き手が共用)
# ------------------------------------------------------------
def dedent_entry(text: str) -> str:
    """旧 list 形の 1 entry (`- id: …` で始まる text) → mapping の text (2 space dedent)。 注釈行 (col 0 の #) は保つ。"""
    lines = text.rstrip("\n").split("\n")
    out: List[str] = []
    seen_start = False
    for ln in lines:
        if not seen_start:
            if ln.startswith("- id:"):
                out.append(ln[2:])
                seen_start = True
                continue
            if ln.strip() == "" or ln.startswith("#"):
                out.append("" if ln.strip() == "" else ln)
                continue
            raise TodoLedgerError(f"entry の先頭が `- id:` でない: {ln[:60]!r}")
        if ln.startswith("  "):
            out.append(ln[2:])
        elif ln.strip() == "":
            out.append("")
        elif ln.startswith("#"):
            out.append(ln)
        else:
            raise TodoLedgerError(f"2 space dedent できない行: {ln[:60]!r}")
    if not seen_start:
        raise TodoLedgerError("`- id:` 行が無い")
    return "\n".join(out).rstrip("\n") + "\n"


def indent_entry(text: str) -> str:
    """mapping の text → 旧 list 形 (dedent_entry の逆)。 旧 file にまだ書く読み手の互換用。"""
    lines = text.rstrip("\n").split("\n")
    out: List[str] = []
    seen_start = False
    for ln in lines:
        if not seen_start and ln.startswith("id:"):
            out.append("- " + ln)
            seen_start = True
        elif ln.strip() == "":
            out.append("")
        elif ln.startswith("#"):
            out.append(ln)
        else:
            out.append("  " + ln)
    if not seen_start:
        raise TodoLedgerError("`id:` 行が無い")
    return "\n".join(out).rstrip("\n") + "\n"


def split_legacy(text: str, verify: bool = True) -> Tuple[List[str], List[Tuple[str, str]]]:
    """旧 TODO.yaml の text → (冒頭の注釈行, [(id, 1 entry の text)])。

    境界 = col 0 の `- id:`。 entry の末尾の空行・col 0 の注釈行は**次の entry の頭**に送る (= 節の見出し注釈は
    その次の entry の file に残る。 最後の entry の後ろの注釈はその file の末尾に残る)。
    verify=True なら各 entry の text を parse し直し、 元の list の要素と == であることを確かめる (違えば TodoLedgerError)。
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    starts = [i for i, ln in enumerate(lines) if ln.startswith("- id:")]
    for i, ln in enumerate(lines):
        if ln.startswith("- ") and not ln.startswith("- id:"):
            raise TodoLedgerError(f"L{i + 1}: `- id:` 以外で始まる top-level の要素: {ln[:60]!r}")
    if not starts:
        raise TodoLedgerError("`- id:` 行が 1 つも無い")
    header = lines[:starts[0]]
    for ln in header:
        if ln.strip() and not ln.startswith("#"):
            raise TodoLedgerError(f"冒頭に注釈でない行: {ln[:60]!r}")
    chunks: List[List[str]] = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        chunks.append(lines[s:e])
    # 末尾の空行・注釈行を次の entry の頭へ
    for k in range(len(chunks) - 1):
        tail: List[str] = []
        while chunks[k] and (chunks[k][-1].strip() == "" or chunks[k][-1].startswith("#")):
            tail.insert(0, chunks[k].pop())
        comments = [ln for ln in tail if ln.startswith("#")]
        if comments:
            chunks[k + 1] = comments + chunks[k + 1]
    orig = None
    if verify:
        try:
            orig = yaml.load(text, Loader=_LOADER)
        except yaml.YAMLError as e:
            raise TodoLedgerError(f"元の text が YAML として読めない ({str(e).splitlines()[0] if str(e) else e})") from e
        if not isinstance(orig, list) or len(orig) != len(chunks):
            raise TodoLedgerError(f"元の list の要素数 {len(orig) if isinstance(orig, list) else '?'} ≠ `- id:` 行 {len(chunks)}")
    out: List[Tuple[str, str]] = []
    for k, ch in enumerate(chunks):
        t = dedent_entry("\n".join(ch))
        d = parse_entry_text(t)
        eid = d["id"]
        if not is_safe_id(eid):
            raise TodoLedgerError(f"file 名にできない id: {eid!r}")
        if orig is not None and d != orig[k]:
            raise TodoLedgerError(f"entry {eid}: dedent した text の parse が元と違う")
        out.append((eid, t))
    ids = [i for i, _ in out]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise TodoLedgerError(f"id の重複: {dup[:5]}")
    return header, out


# ------------------------------------------------------------
# selftest
# ------------------------------------------------------------
LEGACY_FIXTURE = '''# ledger header
# source: a | b

- id: "2026-01-02-second"
  task: "second"
  status: open
  notes: |
    two lines
    with "quotes" and: colons

    and a blank line inside
  cross_ref:
    - "x/inbox:2026-01-02-mail"   # inline comment

# ── section note for the next entry ──
- id: 2026-01-01-first
  task: 'first'
  status: done
  tags: [a, b]
- id: "2026-01-03-third"
  task: "third"
  status: open
# trailing note
'''


def _selftest() -> int:
    fails = 0

    def check(cond, name):
        nonlocal fails
        print(("  PASS: " if cond else "  FAIL: ") + name)
        if not cond:
            fails += 1

    header, parts = split_legacy(LEGACY_FIXTURE)
    orig = yaml.safe_load(LEGACY_FIXTURE)
    check(header == ["# ledger header", "# source: a | b", ""], "split: 冒頭の注釈行を返す")
    check([i for i, _ in parts] == ["2026-01-02-second", "2026-01-01-first", "2026-01-03-third"], "split: 旧 file の順で entry を切る")
    check([yaml.safe_load(t) for _, t in parts] == orig, "split: dedent した text の parse が元の list と ==")
    check(parts[1][1].startswith("# ── section note"), "split: 節の注釈行は次の entry の頭に送る")
    check(parts[2][1].endswith("status: open\n# trailing note\n"), "split: 最後の entry の後ろの注釈はその file の末尾")
    check('notes: |\n  two lines\n  with "quotes" and: colons\n\n  and a blank line inside\n' in parts[0][1],
          "dedent: block scalar と引用符と空行を保つ")
    check(indent_entry(parts[0][1]) == "\n".join(LEGACY_FIXTURE.split("\n")[3:13]) + "\n", "indent_entry は dedent の逆")
    for bad, why in (("- id: a\n  x: 1\n- k: 2\n", "`- id:` 以外の top-level 要素"),
                     ("x: 1\n- id: a\n", "冒頭に注釈でない行"),
                     ("- id: a\n  x: 1\n- id: a\n  x: 2\n", "id の重複"),
                     ("- id: a/b\n  x: 1\n", "file 名にできない id"),
                     ("- id: a\n x: 1\n", "2 space dedent できない行")):
        try:
            split_legacy(bad)
            check(False, f"split: {why} で TodoLedgerError")
        except TodoLedgerError:
            check(True, f"split: {why} で TodoLedgerError")

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "ledger"
        (repo / DIR_NAME).mkdir(parents=True)
        for eid, t in parts:
            write_todo(todo_path(repo, eid), t)
        check(sorted(p.name for p in todo_files(repo)) == ["2026-01-01-first.yaml", "2026-01-02-second.yaml", "2026-01-03-third.yaml"],
              "write_todo / todo_files: file 名 = id + .yaml")
        got = load_todos(repo)
        check([e["id"] for e in got] == ["2026-01-01-first", "2026-01-02-second", "2026-01-03-third"], "load_todos: file 名順 (= id 順)")
        check({e["id"]: e for e in got} == {e["id"]: e for e in orig}, "round-trip: 旧 list → file → load == 元の entry")
        # 旧 TODO.yaml が残っている: 同じ id は todo/ が勝ち、 無い id は後ろに続く
        (repo / LEGACY_NAME).write_text('- id: "2026-01-02-second"\n  task: "OLD"\n- id: "2026-01-00-legacy-only"\n  task: "legacy"\n',
                                        encoding="utf-8")
        got = load_todos(repo)
        check([e["id"] for e in got] == ["2026-01-01-first", "2026-01-02-second", "2026-01-03-third", "2026-01-00-legacy-only"]
              and got[1]["task"] == "second", "移行中: 旧 file も読み、 同じ id は todo/ が勝つ")
        wp = load_todos_with_paths(repo)
        check(wp[-1][0] == repo / LEGACY_NAME and wp[0][0] == repo / DIR_NAME / "2026-01-01-first.yaml",
              "load_todos_with_paths: 旧 file の entry は path = TODO.yaml")
        check(find_todo(repo, "2026-01-00-legacy-only")[0].name == LEGACY_NAME and find_todo(repo, "nope") is None, "find_todo")
        check(resolve_repo(repo / LEGACY_NAME) == repo and resolve_repo(repo / DIR_NAME) == repo and resolve_repo(repo) == repo,
              "resolve_repo: repo / todo / TODO.yaml のどれでも repo")
        check(load_todos(repo / LEGACY_NAME) == got and load_todos(repo / DIR_NAME) == got, "load_todos: path の形に依らない")
        check(todo_globs(repo) == [str(repo / DIR_NAME / "*.yaml"), str(repo / LEGACY_NAME)], "todo_globs")
        (repo / LEGACY_NAME).unlink()
        # 契約 4: id ≠ file 名 / mapping でない / 暗号文 / 読めない YAML は例外 (黙って飛ばさない)
        (repo / DIR_NAME / "2026-01-09-wrong.yaml").write_text('id: "2026-01-09-other"\ntask: x\n', encoding="utf-8")
        try:
            load_todos(repo)
            check(False, "id ≠ file 名 で TodoLedgerError")
        except TodoLedgerError as e:
            check("file 名と違う" in str(e), "id ≠ file 名 で TodoLedgerError")
        (repo / DIR_NAME / "2026-01-09-wrong.yaml").unlink()
        (repo / DIR_NAME / "2026-01-09-list.yaml").write_text('- id: "2026-01-09-list"\n  task: x\n', encoding="utf-8")
        try:
            load_todos(repo)
            check(False, "list 形の file で TodoLedgerError")
        except TodoLedgerError as e:
            check("mapping でない" in str(e), "list 形の file で TodoLedgerError")
        (repo / DIR_NAME / "2026-01-09-list.yaml").unlink()
        (repo / DIR_NAME / "2026-01-09-locked.yaml").write_bytes(GIT_CRYPT_MAGIC + b"\x00\x01garbage")
        try:
            load_todos(repo)
            check(False, "暗号文のままの file で TodoLedgerError")
        except TodoLedgerError as e:
            check("locked" in str(e), "暗号文のままの file で TodoLedgerError")
        (repo / DIR_NAME / "2026-01-09-locked.yaml").unlink()
        (repo / DIR_NAME / "2026-01-09-broken.yaml").write_text('id: "2026-01-09-broken"\ntask: [unclosed\n', encoding="utf-8")
        try:
            load_todos(repo)
            check(False, "壊れた YAML で TodoLedgerError")
        except TodoLedgerError:
            check(True, "壊れた YAML で TodoLedgerError")
        (repo / DIR_NAME / "2026-01-09-broken.yaml").unlink()
        (repo / DIR_NAME / "README.md").write_text("# not an entry\n", encoding="utf-8")
        check(len(load_todos(repo)) == 3, "todo/README.md は entry として読まない")
        try:
            write_todo(todo_path(repo, "2026-01-05-x"), 'id: "2026-01-05-y"\ntask: x\n')
            check(False, "write_todo: id ≠ file 名 なら書かない")
        except TodoLedgerError:
            check(not (repo / DIR_NAME / "2026-01-05-x.yaml").exists(), "write_todo: id ≠ file 名 なら書かない")
        try:
            todo_path(repo, "../escape")
            check(False, "todo_path: path safe でない id を拒む")
        except TodoLedgerError:
            check(True, "todo_path: path safe でない id を拒む")
        # 旧 file が暗号文 = 例外 (fail-open にしたい読み手が捕まえる)
        (repo / LEGACY_NAME).write_bytes(GIT_CRYPT_MAGIC + b"\x00")
        try:
            load_todos(repo)
            check(False, "旧 TODO.yaml が暗号文なら TodoLedgerError")
        except TodoLedgerError:
            check(True, "旧 TODO.yaml が暗号文なら TodoLedgerError")
        (repo / LEGACY_NAME).unlink()
        empty = Path(td) / "empty"
        empty.mkdir()
        check(load_todos(empty) == [] and todo_files(empty) == [], "todo/ も TODO.yaml も無い repo は空 list")
    print(f"selftest: {'ALL PASS' if not fails else f'FAIL {fails}'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest())  # 引数なしでも --selftest でも selftest
