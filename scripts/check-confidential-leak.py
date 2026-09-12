#!/usr/bin/env python3
"""check-confidential-leak.py — 機密 pattern が remote 付き repo に commit されるのを止める。

= 「local-only repo にしか書いてはいけない実体」 が、 remote を持つ repo (= push される)
  に紛れ込んだ commit を pre-commit で BLOCK する gate。

## 設計 (= 層3 pre-commit chain の preamble-alias BLOCK と同じ形)

**この file には機密文字列を一切書かない。** pattern の実体は repo の外に置き、 ここは
機構だけを持つ。 理由: 本 script は remote 付きの repo に入るので、
pattern 一覧をここに書いたら pattern 一覧そのものが漏れる。

  検出は 2 本立て (役割分担):
    A. **指紋照合** … 作業リポの本文そのものを索引にし、 同じ日本語が remote 付き repo の
       追加行に現れたら BLOCK。 **人が何も登録しなくて良い** のが要点。 範囲は作業リポ側の
       `# index:` / `# index-exclude:` glob が決める。 ASCII だけ・日本語が薄い断片は
       索引に入れない (= LaTeX 定型と共有 path の誤検知を実測で 0 にした閾値)。
    B. **pattern 照合** … ASCII の識別子 (作業 file 名など。 指紋では拾えない) を正規表現で。
       こちらは人が 1 行ずつ足す。

  ⚠️ どちらも **逐語の写し** しか捕まえない。 機密を自分の言葉で言い換えた文章
     (例: 別 session への返送 marker に書いた要約) は原理的に検出できない —
     その経路は content 検査ではなく、 書き込み先の構造で縛ること。

  設定の探し方 (すべて任意 = 無ければ silent skip):
    1. 環境変数 CLAUDE_LEAK_PATTERNS  … `:` 区切りの pattern file path
    2. ~/.claude/leak-pattern-sources.txt … 1 行 1 dir。 各 dir の `.leak-patterns` を読む
       (= machine-local の pointer。 どの repo にも入らない)

  pattern file の書式 (1 行 1 件):
    <label><TAB><正規表現>     … label は違反時の表示名 (機密語を避けた呼び名にする)
    <正規表現>                 … label 省略時は「(無名)」 と表示
    # で始まる行と空行は無視

## 発火条件

  BLOCK するのは  (repo が remote を持つ) ∧ (staged の追加行 or 追加 path が pattern に一致)
  のときだけ。 remote を持たない repo (= local-only の作業リポ) では**必ず素通り**する
  ので、 実体を置くべき場所での作業は妨げない。

## 出力

  一致した **file と行番号と label** だけを出す。 **一致した本文は出さない**
  (= 端末・transcript・CI log に機密が再露出しないため)。

## escape hatch

  CLAUDE_LEAK_GUARD=0  で無効化 (= 誤検知で作業が止まったときの緊急脱出)。

## 使い方

  check-confidential-leak.py                … staged を検査 (pre-commit から呼ばれる)
  check-confidential-leak.py --install      … このマシンの作業リポを pointer に登録 (冪等)
  check-confidential-leak.py --check-wiring … 配線が生きているかを必ず可視に報告 (run-all-checks)
  check-confidential-leak.py --selftest     … 自己テスト

## ⚠️ fail-open であることの取り扱い

  pattern 未設定 / source 不達 / 正規表現破損は **すべて素通り** (= gate 全体を殺さない)。
  裏返すと「効いていないことに気づけない」 ので、 それ専用に `--check-wiring` を置き、
  run-all-checks.sh から毎回叩く。 そこでは pattern file が宣言したカナリアを本番 config
  のまま実際に BLOCK できるかまで確かめ、 できなければ FAIL にする。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SOURCES_POINTER = Path.home() / ".claude" / "leak-pattern-sources.txt"

# このマシンに作業リポが在るかの判定に使う候補 dir。
# **この script には書かない** — 作業リポの場所は個人の配置であり、 それ自体が
# 漏らしたくない情報になりうる。 環境変数か machine-local の一覧 file から読む。
#   $CLAUDE_LEAK_CANDIDATE_DIRS  … `:` 区切り
#   ~/.claude/leak-candidate-dirs.txt … 1 行 1 dir、 `#` はコメント
CANDIDATE_FILE = Path.home() / ".claude" / "leak-candidate-dirs.txt"


def candidate_dirs(env=None):
    env = os.environ if env is None else env
    out = []
    for d in (env.get("CLAUDE_LEAK_CANDIDATE_DIRS") or "").split(":"):
        if d.strip():
            out.append(Path(os.path.expanduser(d.strip())))
    f = Path(env.get("CLAUDE_LEAK_CANDIDATE_FILE") or CANDIDATE_FILE)
    if f.is_file():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(Path(os.path.expanduser(line)))
    return out


# カナリア: pattern file 側が `# canary: <値>` 行で宣言する合言葉。 --check-wiring が
# 本番の config をそのまま使って「実際に BLOCK できるか」 を毎回確かめる live probe に使う
# (= 配線が死んでいることに気づけない silent fail-open を潰すため)。
# ⚠️ **値をこの file に literal で書かない** — 書くと pattern に一致してしまい、 この
#    engine 自身の commit を自分の gate が弾く。 値の home は pattern file だけ。
CANARY_DIRECTIVE = "# canary:"
INDEX_DIRECTIVE = "# index:"
INDEX_EXCLUDE_DIRECTIVE = "# index-exclude:"

# 指紋照合 (= 作業リポの本文そのものを索引にする。 人が pattern を足す必要が無い)。
# 閾値は実測で決めた (2026-09-12、 ~/Claude 全 repo の追跡 file 830,786 行に対して):
#   日本語 0 文字以上 (= 制限なし) … 誤検知 6,800 行   ← LaTeX 定型と共有 path が原因
#   日本語 1 文字以上             … 誤検知    24 行   ← `\newtheorem{theorem}{定理}` 等
#   **日本語 4 文字以上           … 誤検知     0 行**  ← 採用。 問題文 1 文を 24 断片で捕捉
SHINGLE_N = 24          # 空白を除いた連続 24 文字を 1 単位にする
MIN_JA = 4              # 24 文字中の日本語 (かな + 漢字) がこれ未満の断片は索引に入れない
INDEX_SUFFIXES = (".tex", ".md", ".txt", ".yaml", ".yml", ".bib")


def _ja_count(s):
    return sum(1 for c in s if "\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff")


def _git(args, cwd=None):
    # errors="replace" は必須: staged に binary (画像 / tar) があると git diff の出力が
    # UTF-8 として不正になり、 text=True だと UnicodeDecodeError で hook ごと落ちて
    # **その repo の commit が全部できなくなる** (2026-09-12 に実際に起こした)。
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def _pattern_files(env=None):
    """読むべき pattern file の path リスト。"""
    env = os.environ if env is None else env
    files = []
    for p in (env.get("CLAUDE_LEAK_PATTERNS") or "").split(":"):
        if p.strip():
            files.append(Path(p.strip()))
    pointer = Path(env.get("CLAUDE_LEAK_SOURCES") or SOURCES_POINTER)
    if pointer.is_file():
        for line in pointer.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            d = Path(os.path.expanduser(line))
            if (d / ".leak-patterns").is_file():
                files.append(d / ".leak-patterns")
    return files


def read_canary(env=None):
    """pattern file の `# canary: <値>` 宣言を読む。 無ければ None。"""
    for f in _pattern_files(env):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            s = line.strip()
            if s.lower().startswith(CANARY_DIRECTIVE):
                v = s[len(CANARY_DIRECTIVE):].strip()
                if v:
                    return v
    return None


def load_patterns(env=None):
    """(label, compiled_regex) のリストを返す。 見つからなければ []（= fail-open）。"""
    out = []
    for f in _pattern_files(env):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue          # 読めない source は黙って飛ばす (= fail-open)
        for raw in text.splitlines():
            raw = raw.rstrip()
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            label, _, rx = raw.partition("\t")
            if not rx:
                label, rx = "(無名)", label
            try:
                out.append((label.strip(), re.compile(rx.strip(), re.IGNORECASE)))
            except re.error:
                continue      # 壊れた正規表現も fail-open (= gate 全体を殺さない)
    return out


def staged_added(cwd=None):
    """[(path, lineno, text)] = staged の追加行。 -U0 の hunk header から行番号を復元。"""
    rc, diff = _git(["diff", "--cached", "-U0", "--diff-filter=ACM"], cwd=cwd)
    if rc != 0:
        return []
    out, path, lineno = [], None, 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            out.append((path, lineno, line[1:]))
            lineno += 1
    return out


def staged_paths(cwd=None):
    rc, names = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"], cwd=cwd)
    return names.splitlines() if rc == 0 else []


def has_remote(cwd=None):
    rc, out = _git(["remote"], cwd=cwd)
    return rc == 0 and bool(out.strip())


def scan(cwd=None, env=None):
    """違反 [(kind, path, lineno, label)] を返す。 検査しない場合も [] を返す。"""
    env = os.environ if env is None else env
    if env.get("CLAUDE_LEAK_GUARD") == "0":
        return []
    if not has_remote(cwd):
        return []                       # local-only repo は対象外 (= 実体の置き場所)
    pats = load_patterns(env)
    fps = secret_index(env)
    if not pats and not fps:
        return []                       # 何も設定されていない環境では何もしない
    hits = []
    for p in staged_paths(cwd):
        for label, rx in pats:
            if rx.search(p):
                hits.append(("path", p, 0, label))
                break
    for path, lineno, text in staged_added(cwd):
        matched = None
        for label, rx in pats:
            if rx.search(text):
                matched = ("line", path, lineno, label)
                break
        if matched is None and fps and _shingles(text) & fps:
            # 指紋一致 = 作業リポの本文がそのまま (or ほぼそのまま) 写っている
            matched = ("copy", path, lineno, "作業リポ本文との一致")
        if matched:
            hits.append(matched)
    return hits


def main():
    hits = scan()
    if not hits:
        return 0
    rc, root = _git(["rev-parse", "--show-toplevel"])
    print("", file=sys.stderr)
    print("🚫 [confidential-leak] local-only にしか書けない内容が、 remote 付きの repo に",
          file=sys.stderr)
    print(f"   commit されようとしています ({root.strip() or '?'})。", file=sys.stderr)
    print("", file=sys.stderr)
    for kind, path, lineno, label in hits:
        where = f"{path}  (ファイル名)" if kind == "path" else f"{path}:{lineno}"
        print(f"   - [{label}] {where}", file=sys.stderr)
    print("", file=sys.stderr)
    print("   ※ 一致した本文は意図的に表示していません (= ここで再露出させないため)。",
          file=sys.stderr)
    print("   対処: 実体は local-only の作業リポにだけ置き、 この repo には", file=sys.stderr)
    print("         「存在と扱い方」 だけの pointer を残す。", file=sys.stderr)
    print("   誤検知で急ぎ通すなら: CLAUDE_LEAK_GUARD=0 git commit ...", file=sys.stderr)
    print("", file=sys.stderr)
    return 1


def _directives(env=None, name=None):
    """pattern file の `# <name>:` 行の値を、 file ごとにまとめて返す [(file, [値...])]。"""
    out = []
    for f in _pattern_files(env):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        vals = []
        for line in text.splitlines():
            s = line.strip()
            if s.lower().startswith(name):
                v = s[len(name):].strip()
                if v:
                    vals.append(v)
        out.append((f, vals))
    return out


def _shingles(text):
    """空白を除いた連続 SHINGLE_N 文字のうち、 日本語が MIN_JA 文字以上のものだけ。

    日本語比率で絞るのは、 誤検知の実体が **LaTeX の定型** (`\documentclass[...]`、
    `\begin{tikzpicture}`、 `\newtheorem{theorem}{定理}`) と **共有された path 文字列**
    だったため (2026-09-12 実測)。 ASCII だけの識別子 (作業 file 名など) は指紋では
    なく pattern 側で受け持つ = 役割分担。
    """
    s = "".join(text.split())
    return {g for g in (s[i:i + SHINGLE_N] for i in range(max(0, len(s) - SHINGLE_N + 1)))
            if _ja_count(g) >= MIN_JA}


def secret_index(env=None):
    """作業リポの本文から指紋索引を作る。

    どの範囲を索引に入れるかは **作業リポ側の `.leak-patterns`** が
    `# index: <glob>` / `# index-exclude: <glob>` で宣言する (= repo 固有の知識を
    この機構側に持たない)。 `# index:` が 1 つも無い source は指紋照合をしない。
    canary も索引に混ぜる (= --check-wiring が指紋経路を端から端まで試せるように)。
    """
    from fnmatch import fnmatch

    idx = set()
    for f, incs in _directives(env, INDEX_DIRECTIVE):
        if not incs:
            continue
        excs = dict(_directives(env, INDEX_EXCLUDE_DIRECTIVE)).get(f, [])
        root = f.parent
        for p in root.rglob("*"):
            if ".git" in p.parts or not p.is_file():
                continue
            if p.suffix.lower() not in INDEX_SUFFIXES:
                continue
            rel = p.relative_to(root).as_posix()
            if not any(fnmatch(rel, g) for g in incs):
                continue
            if any(fnmatch(rel, g) for g in excs):
                continue
            try:
                idx |= _shingles(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    canary = read_canary(env)
    if canary:
        idx |= _shingles(canary)
    return idx


def match_paths(targets, env=None):
    """複数 target を **索引 1 回** で判定し、 一致したものだけ返す。

    1 件ずつ match_path を呼ぶと索引構築 (0.3 秒) が件数分かかる (実測 60 件で 156 秒)。
    棚卸しのような一括呼び出しはこちらを使う。
    """
    idx = secret_index(env)
    pats = load_patterns(env)
    hit = []
    if not idx and not pats:
        return hit
    for target in targets:
        if _match_one(target, idx, pats):
            hit.append(target)
    return hit


def _match_one(target, idx, pats):
    p = Path(os.path.expanduser(str(target or "")))
    files = []
    if p.is_dir():
        files = [q for q in p.rglob("*") if q.is_file()]
    elif p.is_file():
        files = [p]
    for q in files[:400]:
        if q.suffix.lower() not in INDEX_SUFFIXES:
            continue
        try:
            text = q.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if idx and (_shingles(text) & idx):
            return True
        for _label, rx in pats:
            if rx.search(text):
                return True
    return False


def match_path(target, env=None):
    """target (file or dir) の本文が機密索引に一致するかを返す。

    marker などの「成果物そのものを見て機密かどうかを判定したい」 呼び出し元のための
    入口。 一致した本文は返さない (= 呼び出し元に機密を渡さない)。
    """
    return bool(match_paths([target], env))


# ------------------------------------------------------- install / wiring 監査
def install_sources(candidates=None, pointer=None, quiet=False):
    """このマシンに在る作業リポを pointer に登録 (冪等)。 登録した dir のリストを返す。"""
    pointer = Path(pointer or SOURCES_POINTER)
    done = []
    for d in (candidates if candidates is not None else candidate_dirs()):
        d = Path(d)
        if not (d / ".leak-patterns").is_file():
            continue
        pointer.parent.mkdir(parents=True, exist_ok=True)
        lines = pointer.read_text(encoding="utf-8").splitlines() if pointer.is_file() else []
        if str(d) not in lines:
            with pointer.open("a", encoding="utf-8") as fh:
                fh.write(str(d) + "\n")
            if not quiet:
                print(f"  ✅ 登録しました ({d})")
        elif not quiet:
            print(f"  OK: 登録済 ({d})")
        done.append(d)
        break          # 同一 dir の別名を二重登録しない
    if not done and not quiet:
        print("  skip: 対象の作業リポがこのマシンに無い")
    return done


def canary_blocks(env=None):
    """本番の pattern 設定のまま、 実際に commit を止められるかを確かめる live probe。

    戻り値: True=止められた / False=止められなかった / None=カナリア未宣言 (probe 不能)。
    """
    import tempfile

    canary = read_canary(env)
    if not canary:
        return None
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        _git(["init", "-q", "-b", "main"], cwd=r)
        _git(["config", "user.email", "t@t"], cwd=r)
        _git(["config", "user.name", "t"], cwd=r)
        _git(["remote", "add", "origin", "git@example.com:x/y.git"], cwd=r)
        (r / "canary.md").write_text(canary + "\n", encoding="utf-8")
        _git(["add", "canary.md"], cwd=r)
        return bool(scan(cwd=r, env=env))


def check_wiring(candidates=None, pointer=None, env=None):
    """配線が生きているかを **必ず可視に** 報告する。 死んでいれば exit 1。

    silent fail-open (= pattern 未設定でも何も言わずに素通り) は「効いていないことに
    気づけない」 ので、 この監査だけは黙らない。 3 状態を必ず 1 行出す:
      ARMED / NOT ARMED (理由つき、 FAIL) / 対象外 (このマシンに作業リポ無し)
    """
    env = os.environ if env is None else env
    pointer = Path(pointer or env.get("CLAUDE_LEAK_SOURCES") or SOURCES_POINTER)
    cands = [Path(c) for c in (candidates if candidates is not None else candidate_dirs())]
    present = [d for d in cands if (d / ".leak-patterns").is_file()]

    print("── 機密 leak guard の配線 (check-confidential-leak)")
    if not present:
        print("   対象外: このマシンに作業リポが無い (= 守るべき実体がローカルに無い)")
        return 0

    problems = []
    registered = pointer.is_file() and any(
        str(d) in pointer.read_text(encoding="utf-8").splitlines() for d in present
    )
    if not registered:
        problems.append(f"pointer に未登録 ({pointer}) — `bash hooks/install.sh` で自動登録される")

    pats = load_patterns(env)
    fps = secret_index(env)
    declared_index = any(v for _f, v in _directives(env, INDEX_DIRECTIVE))
    if not pats and not fps:
        problems.append("pattern も指紋索引も空 (file 破損 / 全行が壊れた正規表現?)")
    elif declared_index and len(fps) < 100:
        problems.append(f"`# index:` を宣言しているのに指紋索引が {len(fps)} 断片しかない"
                        " (= 範囲 glob が何にも当たっていない疑い)")

    # pre-commit から実際に呼ばれているか。 hook 本体と、 そこから chain される script を
    # 1 段だけ辿って engine 名を探す (= 個人の配置を決め打ちしない)。
    # cwd が git repo でなければこの leg は判定不能 (= 検査しない)。 repo なのに
    # hook が engine を呼んでいなければ問題として数える。
    me = Path(__file__).name
    wired = None
    hooks = Path.cwd() / ".git" / "hooks"
    for h in (hooks / "pre-commit",):
        if not h.is_file():
            continue
        wired = False
        body = h.read_text(encoding="utf-8", errors="replace")
        if me in body:
            wired = True
            break
        for tok in re.findall(r"[\w./$~{}-]+\.(?:sh|py)", body):
            q = Path(os.path.expandvars(tok.replace("$HOME", str(Path.home()))))
            if q.is_file() and me in q.read_text(encoding="utf-8", errors="replace"):
                wired = True
                break
    if wired is False:
        problems.append("pre-commit から呼ばれていない (= commit 時に発火しない)")

    if not problems:
        cb = canary_blocks(env)
        if cb is None:
            problems.append("カナリアが宣言されていない (pattern file に `# canary: <値>` 行が要る)"
                            " = 実際に BLOCK できるかを毎回確かめられない")
        elif not cb:
            problems.append("カナリアを止められなかった = 本番設定のまま実際には BLOCK できない")

    if problems:
        print("   🚫 NOT ARMED — 機密 leak guard は今このマシンで効いていません:")
        for p in problems:
            print(f"      - {p}")
        print("   ※ この gate は fail-open (壊れても commit は通る) なので、")
        print("      ここが赤いあいだは「守られている」 と思わないこと。")
        return 1

    print(f"   ARMED: 指紋 {len(fps):,} 断片 / pattern {len(pats)} 件 / カナリア OK"
          f" / pre-commit chain 済 ({present[0]})")
    return 0


# ---------------------------------------------------------------- selftest
def selftest():
    import tempfile

    fails = []

    def mkrepo(d, with_remote):
        _git(["init", "-q", "-b", "main"], cwd=d)
        _git(["config", "user.email", "t@t"], cwd=d)
        _git(["config", "user.name", "t"], cwd=d)
        if with_remote:
            _git(["remote", "add", "origin", "git@example.com:x/y.git"], cwd=d)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pat = td / "pats.txt"
        pat.write_text("# c\n作題ファイル\tzz9999sug\n秘匿語\tsecret-?word\n", encoding="utf-8")
        env = {"CLAUDE_LEAK_PATTERNS": str(pat), "CLAUDE_LEAK_SOURCES": str(td / "none")}

        if len(load_patterns(env)) != 2:
            fails.append("pattern の読み込み数が 2 でない")

        # (1) remote あり × 追加行が一致 → BLOCK
        r1 = td / "r1"; r1.mkdir(); mkrepo(r1, True)
        (r1 / "a.md").write_text("これは zz9999sug の話\n", encoding="utf-8")
        _git(["add", "a.md"], cwd=r1)
        h = scan(cwd=r1, env=env)
        if not any(k == "line" for k, *_ in h):
            fails.append("remote あり・追加行一致を block できていない")

        # (2) remote なし → 素通り
        r2 = td / "r2"; r2.mkdir(); mkrepo(r2, False)
        (r2 / "a.md").write_text("これは zz9999sug の話\n", encoding="utf-8")
        _git(["add", "a.md"], cwd=r2)
        if scan(cwd=r2, env=env):
            fails.append("remote なし repo で発火した (= 作業リポを止めてしまう)")

        # (3) file 名だけの一致も拾う
        r3 = td / "r3"; r3.mkdir(); mkrepo(r3, True)
        (r3 / "zz9999sug.tex").write_text("無害\n", encoding="utf-8")
        _git(["add", "zz9999sug.tex"], cwd=r3)
        if not any(k == "path" for k, *_ in scan(cwd=r3, env=env)):
            fails.append("file 名の一致を拾えていない")

        # (4) 無関係な内容は通す
        r4 = td / "r4"; r4.mkdir(); mkrepo(r4, True)
        (r4 / "a.md").write_text("ふつうの変更\n", encoding="utf-8")
        _git(["add", "a.md"], cwd=r4)
        if scan(cwd=r4, env=env):
            fails.append("無関係な内容で誤検知した")

        # (5) escape hatch
        env_off = dict(env, CLAUDE_LEAK_GUARD="0")
        if scan(cwd=r1, env=env_off):
            fails.append("CLAUDE_LEAK_GUARD=0 で無効化されない")

        # (6) pattern 未設定なら fail-open
        env_none = {"CLAUDE_LEAK_PATTERNS": "", "CLAUDE_LEAK_SOURCES": str(td / "none")}
        if scan(cwd=r1, env=env_none):
            fails.append("pattern 未設定で発火した (= fail-open でない)")

        # (7) 大文字小文字を無視
        r7 = td / "r7"; r7.mkdir(); mkrepo(r7, True)
        (r7 / "a.md").write_text("ZZ9999SUG\n", encoding="utf-8")
        _git(["add", "a.md"], cwd=r7)
        if not scan(cwd=r7, env=env):
            fails.append("大文字小文字の違いを取りこぼした")

        # (8) 壊れた正規表現があっても他の pattern は生きる
        bad = td / "bad.txt"
        bad.write_text("壊れ\t[unclosed\nよい\tzz9999sug\n", encoding="utf-8")
        env_bad = dict(env, CLAUDE_LEAK_PATTERNS=str(bad))
        if not scan(cwd=r1, env=env_bad):
            fails.append("壊れた正規表現が gate 全体を殺している")

        # (9) 行番号が付く
        h = scan(cwd=r1, env=env)
        if not any(k == "line" and n == 1 for k, _p, n, _l in h):
            fails.append("行番号が復元できていない")

        # (10) 本文を出力に含めない
        import io, contextlib
        buf = io.StringIO()
        os.chdir(r1)
        with contextlib.redirect_stderr(buf):
            main()
        if "zz9999sug" in buf.getvalue().lower():
            fails.append("一致した本文を出力してしまっている")
        os.chdir(td)

        # ---- 指紋照合 (= 人が pattern を足さなくても本文の写しを捕まえる) ----
        wk = td / "secret"; (wk / "2027年実施").mkdir(parents=True)
        prose = "この装置では導体棒が磁場の中を一定の速さで滑り落ちるものとして考える。" * 2
        (wk / "2027年実施" / "q.tex").write_text(prose, encoding="utf-8")
        (wk / ".leak-patterns").write_text("# index: *年実施/**\n", encoding="utf-8")
        ptr = td / "p2"; ptr.write_text(str(wk) + "\n", encoding="utf-8")
        env_f = {"CLAUDE_LEAK_PATTERNS": "", "CLAUDE_LEAK_SOURCES": str(ptr)}
        if len(secret_index(env_f)) < 10:
            fails.append("指紋索引が作られていない")
        rf = td / "rf"; rf.mkdir(); mkrepo(rf, True)
        (rf / "a.md").write_text("メモ: " + prose[:60] + "\n", encoding="utf-8")
        _git(["add", "a.md"], cwd=rf)
        if not any(k == "copy" for k, *_ in scan(cwd=rf, env=env_f)):
            fails.append("本文をそのまま貼っても指紋で捕まえられない")
        # ASCII だけの定型は索引に入らない (= LaTeX 定型による誤検知を防ぐ)
        rg = td / "rg"; rg.mkdir(); mkrepo(rg, True)
        (rg / "a.tex").write_text("\\newtheorem{theorem}{定理}\n\\documentclass[a4paper]{jsarticle}\n",
                                  encoding="utf-8")
        _git(["add", "a.tex"], cwd=rg)
        if scan(cwd=rg, env=env_f):
            fails.append("LaTeX 定型で誤検知した (= 日本語比率の下限が効いていない)")
        # 指紋は remote 無し repo では発火しない
        rh = td / "rh"; rh.mkdir(); mkrepo(rh, False)
        (rh / "a.md").write_text(prose[:60] + "\n", encoding="utf-8")
        _git(["add", "a.md"], cwd=rh)
        if scan(cwd=rh, env=env_f):
            fails.append("remote 無し repo で指紋が発火した")

        # (20) binary が staged にあっても落ちない (= 2026-09-12 の実害。 text=True で
        #      UnicodeDecodeError を出し、 その repo の commit が全部できなくなった)
        rb = td / "rb"; rb.mkdir(); mkrepo(rb, True)
        (rb / "x.bin").write_bytes(bytes(range(256)) * 8)
        (rb / "y.md").write_text("ふつうの行\n", encoding="utf-8")
        _git(["add", "x.bin", "y.md"], cwd=rb)
        try:
            scan(cwd=rb, env=env)
        except UnicodeDecodeError:
            fails.append("binary が staged にあると落ちる (= commit を全部止めてしまう)")

        # ---- 配線監査 (= 「効いていないことに気づけない」 を潰す部分) ----
        def _quiet_wiring(**kw):
            """selftest では監査の 3 状態メッセージを出さない (= run-all-checks の log で
            本物の 1 行と紛れないように)。"""
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                return check_wiring(**kw)

        # (11) このマシンに作業リポが無いときは「対象外」 で PASS
        if _quiet_wiring(candidates=[td / "nowhere"], pointer=td / "p0", env=env) != 0:
            fails.append("作業リポ不在で対象外 PASS にならない")

        # (12) 作業リポは在るのに pointer 未登録 → NOT ARMED (exit 1)
        w = td / "work"; w.mkdir()
        (w / ".leak-patterns").write_text("# canary: CANARY-TEST-0001\nc\tCANARY-TEST-0001\n",
                                          encoding="utf-8")
        env_w = {"CLAUDE_LEAK_PATTERNS": "", "CLAUDE_LEAK_SOURCES": str(td / "p1")}
        if _quiet_wiring(candidates=[w], pointer=td / "p1", env=env_w) == 0:
            fails.append("pointer 未登録なのに ARMED と報告した")

        # (13) 登録すれば ARMED (= カナリアが実際に BLOCK される)
        (td / "p1").write_text(str(w) + "\n", encoding="utf-8")
        if _quiet_wiring(candidates=[w], pointer=td / "p1", env=env_w) != 0:
            fails.append("正しく配線されているのに ARMED と報告しない")

        # (14) カナリア宣言が無ければ NOT ARMED (= 実効性を確かめられない状態を見逃さない)
        (w / ".leak-patterns").write_text("c\tCANARY-TEST-0001\n", encoding="utf-8")
        if _quiet_wiring(candidates=[w], pointer=td / "p1", env=env_w) == 0:
            fails.append("カナリア未宣言なのに ARMED と報告した")

        # (15) pattern が一致しなくなっていたら NOT ARMED (= 死んだ設定を検出)
        (w / ".leak-patterns").write_text("# canary: CANARY-TEST-0001\nc\tSOMETHING-ELSE\n",
                                          encoding="utf-8")
        if _quiet_wiring(candidates=[w], pointer=td / "p1", env=env_w) == 0:
            fails.append("カナリアを止められないのに ARMED と報告した")
        os.chdir("/")

    if fails:
        print("SELFTEST FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 1
    print("SELFTEST PASS (20 checks)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--install" in sys.argv:
        print("機密 leak guard の pattern source:")
        install_sources()
        sys.exit(0)
    if "--check-wiring" in sys.argv:
        sys.exit(check_wiring())
    if "--match-paths" in sys.argv:
        tgts = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
        for h in match_paths(tgts):
            print(h)
        sys.exit(0)
    if "--match-path" in sys.argv:
        i = sys.argv.index("--match-path")
        tgt = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        sys.exit(1 if match_path(tgt) else 0)
    sys.exit(main())
