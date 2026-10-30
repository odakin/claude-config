#!/usr/bin/env python3
"""git-commit-own-hunk.py — 同じ file に別の session の未 commit の変更が居る時に、 自分の変更だけを commit する (一時 index。 作業 tree の相手の変更は触らない)。

## なぜ要るのか

並列の session が同じ file を触っていると、 `git commit -- <path>` は相手の未 commit の変更ごと commit する
(守れるのは file の単位まで)。 自分の分だけを commit する手順 (HEAD の版に自分の変更だけを当てた版を作り、
一時 index から commit する) は [`conventions/multi-session-coordination.md#temp-index-commit`](../conventions/multi-session-coordination.md#temp-index-commit)
に在るが、 手で踏むと次の穴に落ちる。 本 script はその穴を塞いだ形で 1 command にする。

1. **HEAD が動いた後の commit は、 相手の commit の中身を黙って戻す**。 版を作った時の HEAD (P) から一時 index を作り、
   その間に相手が commit して HEAD が X に進んでいると、 `git commit` は親 = X・tree = 「P + 自分の変更」 の commit を作る
   = X の変更が消える。 error は出ない (git が止めるのは commit の最中に HEAD が動いた時だけ)。
   → 親を最初に 1 回だけ決め、 commit の直前に HEAD がその親のままかを見て、 commit の直後に親を照合する。
   違えば ref を元に戻して (旧値つき) 版を作り直す。 git が commit の最中に HEAD が動いたのを見つけて
   `cannot lock ref` で止めた時も、 commit は入っていないので同じく親を取り直してやり直す (関門の拒否と取り違えない)。
2. **temp file を `git hash-object -w` に渡すと、 その path の clean filter が掛からない**。 暗号化 (git-crypt 等) の path なら
   平文の blob が commit に入る。 → `--path <path>` を付けて blob を作る。 親の版も filter を通して読む
   (`git cat-file --filters`)。
3. **実行 file の mode を 100644 と決め打ちすると実行権限が落ちる**。 → 親の tree の mode を引き継ぐ。
4. **commit の後に実 index を揃えないと、 自分の commit を取り消す変更が stage 済みになる**。 → commit の後に
   `git reset -q -- <path>` (作業 tree は不変)。
5. **commit 時の関門に止められた時に、 作業 tree に当てた自分の変更が残る**。 → 作業 tree への書き込みは commit が
   通った後にだけ行う (止められたら作業 tree は 1 byte も変わらない)。
6. **commit の直後に HEAD を読み直して 「自分の commit」 とすると、 その間に相手が上に重ねた commit を取り違える**。
   その親は自分の commit なので 「親が違う」 と読み、 1 の巻き戻しが**相手の commit を HEAD から外す** (selftest で再現)。
   → 一時 index の tree と同じ tree の commit を HEAD から first-parent で探して自分の commit とする (同じ tree が
   複数なら件名も照合)。 巻き戻しは旧値つきなので、 誤った commit の上に相手が重ねていれば外さずに止まる (終了値 5)。
7. **4 の `git reset` が実 index の lock (`index.lock`) に当たると、 commit だけが入って実 index と作業 tree が古いまま残る**
   (一時 index の commit は実 index の lock を取らないので通る)。 実 index には自分の commit を取り消す変更が stage 済みで、
   相手が素の `git commit` を打つと自分の変更が黙って巻き戻る (実測)。 → commit の前に lock が消えるのを待ち
   (消えなければ commit しない)、 commit の後の reset も lock が消えるまで待って打ち直す。 それでも揃わなければ
   commit を HEAD から外して (旧値つき) 止まる (終了値 6)。 上に相手の commit が重なっていて外せなければ終了値 5。
   lock を持ったまま走る commit (`git commit -a` / `-- <path>`、 実測) の終わりを待った後は、 それが古い実 index・作業 tree から
   自分の変更を戻していることがある → reset の後に、 自分の commit より後の commit の版に自分の変更が無ければ終了値 5
   (自分の変更を 3-way で HEAD の版に当てて変わるかで見る = 相手が同じ file に足しただけなら止めない)。
   commit の前の待ちと後の待ちは、 それぞれ合わせて LOCK_WAIT 秒まで (待ちの合計が呼び出し側の timeout を越えない)。

commit は `git commit` で作る (pre-commit / prepare-commit-msg / commit-msg / post-commit がそのまま走る)。

## 似た道具との使い分け

- **本 script** = 手元の HEAD の上に commit する。 worktree を作らないので速く、 暗号化の repo でも checkout が要らない。
  hook は手元の作業 tree で走る。 push は別に行う。
- [`commit-from-origin-worktree.py`](commit-from-origin-worktree.py) = `origin/<branch>` から切った使い捨ての worktree で commit して push まで行う。
  手元の index・作業 tree・未 push の commit に一切触れない。 手元に他の session の未 push の commit が居て、 それを巻き込んで
  push したくない時はこちら (同じ file に相手の変更が混ざる時は、 その `--apply` に (old, new) の pair を渡す)。

## 使い方

    # 置換で指定 (親の版と作業 tree の両方に、 同じ置換を当てる)。 OLD / NEW は file で渡す (shell の引用の事故を避ける)
    git-commit-own-hunk.py -F msg.txt --replace <path> old.txt new.txt [--replace …]
    git-commit-own-hunk.py -F msg.txt --replace-str <path> 'old' 'new'

    # 版で指定 (「親の版 + 自分の変更」 の全文を自分で作った時)。 作った時の HEAD を --base に書く
    git-commit-own-hunk.py -F msg.txt --base <sha> --version <path> mine.txt
    #   その後に並列の session の commit で HEAD が進んでいても、 --base から今の HEAD までの commit が対象の path を
    #   1 つも触っていなければ (保存された blob と mode で比べる)、 渡した版は今の HEAD の上でもそのまま正しい
    #   (版 = 親の版 + 自分の変更 で、 親の版が変わっていない) ので今の HEAD を親にして進む。 触っていれば終了値 4
    #   (= 今の HEAD から版を作り直す)。 commit の最中に HEAD が動いた時 (git の `cannot lock ref`) も、 親の取り直しと
    #   この確認からやり直す (やり直しは 3 回まで)。 --replace に --base を付けた時も同じ確認をする
    #   (--base の無い --replace は、 やり直しのたびに新しい親の版に置換を当て直す)
    #   ⚠️ --version は作業 tree に書かない (全文は相手の変更の混ざった作業 tree に当てられない)。 commit の後、
    #   作業 tree が親の版のままだと自分の commit を取り消す差分に見える = 作業 tree が親の版と一致するなら
    #   `git checkout HEAD -- <path>`、 相手の変更が在るなら自分の変更を作業 tree にも当てる (= --replace を使う方が楽)

    --dry-run   commit せずに、 何が commit されるかを出す
    --no-worktree  置換を作業 tree に当てない (もう自分で当ててある時)
    --repo DIR  (既定 = cwd の repo)

置換は親の版の中で**ちょうど 1 回**一致しなければ止まる (0 回 = もう入っているか文面が違う / 2 回以上 = どれか決まらない)。
commit の後は push と、 相手の session への 1 行 (相手の `git diff` から自分の分が消えて見える) を忘れない。

## 終了値

    0 = commit した (dry-run なら何もしていない)
    1 = commit 時の関門 (hook) が止めた。 HEAD も作業 tree も変わっていない
    2 = 使い方・前提の誤り (置換が 1 回一致でない、 変更が無い、 対象が通常の file でない)
    3 = commit は入ったが、 作業 tree に同じ置換を当てられなかった (相手の変更が同じ場所に在る)。 作業 tree を手で直す
    4 = --base から今の HEAD までの commit が対象の path を変えている (渡した版が古い) / HEAD が動き続けた。
        何も commit していない
    5 = commit の直前に HEAD が動いて誤った commit が入り、 その上に別の commit が重なっていて HEAD から外せなかった
        (相手の commit を外さないために止めた) / commit の後に HEAD の近くに自分の commit が見つからない /
        commit の後に実 index を揃えられず、 上に別の commit が重なっていて自分の commit を外せない /
        commit の後、 実 index を揃える前に入った別の commit の版に自分の変更が無い (戻された恐れ。
        作業 tree には自分の変更を当ててある)。 push せずに git log と git reflog を見て手で直す
    6 = 実 index の lock (index.lock) が 30 秒 (LOCK_WAIT) 消えなかった。 何も commit していない (commit の後に当たった時は、
        入れた commit を HEAD から外して戻した)。 少し待って呼び直す (git の process が 1 つも動いていないのに残るなら、
        落ちた git が残した lock = 消してから)

## 限界

- HEAD を見てから `git commit` が HEAD を読むまでの間 (process の起動 1 回ぶん) に相手の commit が入ると、 誤った commit が
  一瞬 HEAD になる。 直後の照合で ref を戻して作り直すが、 その間に push する post-commit hook が在る repo では、
  誤った commit が外へ出うる (そういう hook を持つ repo では使わない)。
- 素の `git commit` は親を pre-commit の前に読み、 tree は pre-commit の後に読み直した実 index から作る (selftest の
  「git の前提」 で確かめている)。 親を読むのが自分の commit より前なら相手の commit が `cannot lock ref` で止まり、 読み直しが
  reset より後なら実 index は新しい。 残る窓 = 相手の開始から読み直しまでの全部が、 自分の commit と reset の間 (git の起動の
  数回ぶん) に収まる時だけで、 pre-commit が無いか、 ごく短い repo に限られる。 その時は相手の commit が自分の変更を戻す。
  reset より先に入れば終了値 5 で分かるが、 後に入ると分からない。
- hook は作業 tree を読むことがある。 hook が見る作業 tree には相手の変更も在る (index は自分の分だけ)。
- commit の後に自分の commit を tree と件名で探す。 hook が件名を書き換え、 かつ同じ tree の commit (空の commit など) が
  直後に上に重なった時だけ取り違えうる。
- pre-commit が一時 index に別の path を足すと (直して `git add` する hook など)、 自分の path 以外を含む commit として
  HEAD から外し、 やり直しを繰り返して終了値 4 で止まる。 足された path は作業 tree の中身 = 相手の未 commit の変更を
  含みうるので止まるのは安全側だが、 表示は「HEAD が動いた」 になる (区別していない)。
- rename と symlink は扱わない。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RC_OK, RC_GATE, RC_USAGE, RC_WORKTREE, RC_MOVED, RC_STUCK, RC_LOCKED = 0, 1, 2, 3, 4, 5, 6
TEST_HOOK_ENV = "GIT_COMMIT_OWN_HUNK_TEST_HOOK"   # selftest 専用: 最初の commit の直前に 1 回だけ shell で実行する (窓を決定的に開ける)
RETRIES = 4                                        # 最初の 1 回 + やり直し 3 回
BACKOFF = 0.2                                      # やり直しの前に待つ秒 × 何回目のやり直しか
LOCK_REF_RE = re.compile(r"cannot lock ref '|HEAD\.lock")   # git が ref を更新できなかった (commit は入っていない)
OWN_SEARCH = 50                                    # commit の後、 自分の commit を HEAD から何個さかのぼって探すか
LOCK_WAIT = 30.0                                   # 実 index の lock (index.lock) が消えるのを待つ秒 (commit の前と後でそれぞれ)
LOCK_POLL = 0.05                                   # lock が消えたかを見る間隔の秒
LOCK_INDEX_RE = re.compile(r"index\.lock")         # git が実 index の lock を取れなかった


class Stop(Exception):
    def __init__(self, rc: int, msg: str):
        super().__init__(msg)
        self.rc = rc


def run(top, *args, inp: bytes | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(top), *args], input=inp, capture_output=True, env=env)


def out(top, *args, inp: bytes | None = None, env: dict | None = None) -> bytes:
    r = run(top, *args, inp=inp, env=env)
    if r.returncode != 0:
        raise Stop(RC_USAGE, f"git {' '.join(args[:3])} が失敗: {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return r.stdout


def repo_top(start: Path) -> Path:
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True)
    if r.returncode != 0:
        raise Stop(RC_USAGE, f"git の repo ではない: {start}")
    return Path(r.stdout.decode().strip())


def rel_path(top: Path, p: str, cwd: Path) -> str:
    q = Path(p)
    q = q if q.is_absolute() else cwd / q
    try:
        return q.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        raise Stop(RC_USAGE, f"repo の外の path: {p}")


def parent_version(top: Path, parent: str, path: str) -> bytes | None:
    """親の版 (smudge filter を通した中身)。 親に無ければ None。"""
    r = run(top, "cat-file", "--filters", f"{parent}:{path}")
    return r.stdout if r.returncode == 0 else None


def tree_mode(top: Path, parent: str, path: str) -> str:
    line = out(top, "ls-tree", parent, "--", path).decode().strip()
    if not line:
        return "100644"
    mode = line.split()[0]
    if mode not in ("100644", "100755"):
        raise Stop(RC_USAGE, f"通常の file でない (mode {mode}): {path}")
    return mode


def paths_changed(top: Path, a: str, b: str, paths: list) -> bool:
    """a と b の間で paths のどれかの中身か mode が変わったか。 保存された blob で比べる (filter・textconv に依らない)。
    pathspec は字面どおり (glob に読まない)。"""
    r = run(top, "diff-tree", "--quiet", "-r", a, b, "--", *paths, env=dict(os.environ, GIT_LITERAL_PATHSPECS="1"))
    if r.returncode not in (0, 1):
        raise Stop(RC_USAGE, f"git diff-tree が失敗: {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return r.returncode == 1


def apply_replaces(data: bytes, reps: list, where: str) -> bytes:
    for old, new in reps:
        n = data.count(old)
        if n != 1:
            hint = "もう入っているか、 文面が違う" if n == 0 else "どれを置き換えるか決まらない"
            raise Stop(RC_USAGE, f"{where}: 置換の old が {n} 回一致 (ちょうど 1 回でなければ止める = {hint}): "
                                 f"{old[:60].decode('utf-8', 'replace')!r}")
        data = data.replace(old, new)
    return data


def build_versions(top: Path, parent: str, specs: dict) -> dict:
    """{path: (mode, mine bytes)}。 specs[path] = {"reps": [(old, new)…]} か {"version": bytes}。"""
    built = {}
    for path, sp in specs.items():
        old = parent_version(top, parent, path)
        if "version" in sp:
            mine = sp["version"]
        else:
            if old is None:
                raise Stop(RC_USAGE, f"{path}: 親の版に無い file は置換で指定できない (--version で全文を渡す)")
            mine = apply_replaces(old, sp["reps"], f"{path} (親の版)")
        if old is not None and mine == old:
            raise Stop(RC_USAGE, f"{path}: 親の版と同じ = commit する変更が無い (もう入っている)")
        built[path] = (tree_mode(top, parent, path), mine)
    return built


def own_commit(top: Path, env: dict, subject: str) -> str | None:
    """今 commit した commit。 commit の後に HEAD を読み直すと、 その間に相手が上に重ねた commit を自分のと取り違え、
    「親が違う」 と読んで ref を戻すと相手の commit が HEAD から消える。 → 一時 index の tree と同じ tree の commit を
    HEAD から first-parent で探す。 同じ tree が複数なら件名も合うものを選ぶ (上に重なった空の commit と取り違えない。
    件名を hook が書き換えていれば tree だけで選ぶ)。 見つからなければ None。"""
    tree = out(top, "write-tree", env=env).decode().strip()
    cur = first = None
    for ln in out(top, "rev-list", "--first-parent", "-n", str(OWN_SEARCH), "--format=%T %s", "HEAD").decode("utf-8", "replace").splitlines():
        if ln.startswith("commit "):          # 出力 = 「commit <sha>」 と 「<tree> <件名>」 の繰り返し
            cur = ln.split()[1]
            continue
        t, _, s = ln.partition(" ")
        if cur and t == tree:
            if s == subject:
                return cur
            first = first or cur
    return first


def msg_subject(msg_file: Path) -> str:
    """git の件名 (%s) と同じ形 = 最初の段落の行を空白 1 つで繋いだもの。"""
    try:
        lines = msg_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return ""
    para = []
    for ln in lines:
        if not ln.strip():
            break
        para.append(ln.strip())
    return " ".join(para)


def commit_once(top: Path, parent: str, built: dict, msg_file: Path, first: bool) -> tuple:
    """(状態, 値)。 状態 = ok (値 = commit) / gate (値 = git の出力) / moved (値 = 説明。 何も入っていない = やり直せる)
    / stuck (値 = 説明。 誤った commit を HEAD から外せなかった = やり直さない)。"""
    tmp = Path(tempfile.mkdtemp(prefix="own-hunk-"))
    try:
        env = dict(os.environ, GIT_INDEX_FILE=str(tmp / "index"))
        out(top, "read-tree", parent, env=env)
        for path, (mode, mine) in built.items():
            blob = out(top, "hash-object", "-w", "--path", path, "--stdin", inp=mine).decode().strip()
            out(top, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", env=env)
        if out(top, "rev-parse", "HEAD").decode().strip() != parent:
            return "moved", "版を作っている間に HEAD が動いた"
        hook = os.environ.get(TEST_HOOK_ENV)
        if hook and first:
            subprocess.run(hook, shell=True, cwd=str(top), capture_output=True)
        r = run(top, "commit", "-q", "-F", str(msg_file), env=env)
        if r.returncode != 0:
            text = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
            # commit の最中に HEAD が動くと git は ref を更新せずに止める (= 関門の拒否ではない)。 git の文言が翻訳されていても
            # HEAD が親から動いていれば同じ扱い。 関門の拒否と重なっても、 やり直しで hook がもう一度判定する
            if LOCK_REF_RE.search(text) or out(top, "rev-parse", "HEAD").decode().strip() != parent:
                return "moved", "commit の最中に HEAD が動いた (git が ref を更新せずに止めた = commit は入っていない)"
            return "gate", text
        new = own_commit(top, env, msg_subject(msg_file))
        if new is None:
            return "stuck", (f"commit したが、 HEAD から {OWN_SEARCH} 個以内に自分の commit が見つからない (HEAD が大きく動いた) "
                             "= push せずに git log と git reflog を見て手で直す")
        parents = out(top, "rev-list", "--parents", "-n", "1", new).decode().split()[1:]
        touched = set(out(top, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", new).decode().split("\0")) - {""}
        if parents[:1] != [parent] or not touched <= set(built):
            # 親が違う = 相手の commit の上に、 古い tree の commit を作った (相手の変更を戻している)。 ref を元に戻す。
            # 旧値つき = HEAD が自分の commit のままの時だけ戻る (上に相手が重ねていれば失敗する = 相手の commit を外さない)
            back = parents[0] if parents else parent
            rb = run(top, "update-ref", "HEAD", back, new)
            if rb.returncode != 0:
                return "stuck", (f"commit の直前に HEAD が動き、 誤った commit {new[:9]} (親 {back[:9]} の変更を戻している) が入った。 "
                                 "その上に別の commit が重なっていて HEAD から外せない = push せずに git log を見て手で直す")
            return "moved", f"commit の直前に HEAD が動いた。 誤った commit {new[:9]} を HEAD から外して戻した"
        return "ok", new
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def dry_run(top: Path, parent: str, built: dict) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="own-hunk-"))
    try:
        env = dict(os.environ, GIT_INDEX_FILE=str(tmp / "index"))
        out(top, "read-tree", parent, env=env)
        for path, (mode, mine) in built.items():
            blob = out(top, "hash-object", "-w", "--path", path, "--stdin", inp=mine).decode().strip()
            out(top, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", env=env)
        sys.stdout.write(out(top, "diff", "--cached", "--stat", parent, env=env).decode("utf-8", "replace"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def index_lock(top: Path) -> Path:
    """実 index の lock file。 別の git が実 index を書いている間だけ在る (落ちた git が残していくこともある)。"""
    p = Path(out(top, "rev-parse", "--git-path", "index").decode().strip())
    return Path(f"{p if p.is_absolute() else top / p}.lock")


def wait_unlocked(lock: Path, wait: float) -> bool:
    """lock が消えるのを wait 秒まで待つ。 消えていれば True。"""
    deadline = time.monotonic() + wait
    while lock.exists():
        if time.monotonic() >= deadline:
            return False
        time.sleep(LOCK_POLL)
    return True


def reset_real_index(top: Path, paths: list, lock: Path) -> str | None:
    """commit の後に実 index の paths を新しい HEAD に揃える (作業 tree は不変)。 別の git が実 index の lock を持っていて
    失敗した時は、 lock が消えるのを待ってやり直す (合わせて LOCK_WAIT 秒まで)。 揃ったら None、 揃わなければ git の出力。"""
    deadline = time.monotonic() + LOCK_WAIT
    warned = False
    while True:
        r = run(top, "reset", "-q", "--", *paths)
        if r.returncode == 0:
            return None
        text = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
        if not (LOCK_INDEX_RE.search(text) or lock.exists()):
            return text                       # lock 以外の理由 = 待っても揃わない
        if not warned:
            warned = True
            print(f"⚠️ commit の後、 実 index の lock に当たった。 消えるのを {LOCK_WAIT:g} 秒まで待って打ち直す", file=sys.stderr)
        if not wait_unlocked(lock, deadline - time.monotonic()) or time.monotonic() >= deadline:
            return text
        time.sleep(LOCK_POLL)                 # lock が消えた直後に別の git が取り直すこともある = 少し置いて打ち直す


def change_survives(top: Path, parent: str, mine: str, head: str, path: str) -> bool:
    """parent → mine の path の変更が head の版にも入っているか (= その変更を 3-way で head の版に当てても変わらない)。"""
    cur = parent_version(top, head, path)
    if cur is None:
        return False
    tmp = Path(tempfile.mkdtemp(prefix="own-hunk-"))
    try:
        (tmp / "head").write_bytes(cur)
        (tmp / "base").write_bytes(parent_version(top, parent, path) or b"")
        (tmp / "mine").write_bytes(parent_version(top, mine, path) or b"")
        r = run(top, "merge-file", "-p", str(tmp / "head"), str(tmp / "base"), str(tmp / "mine"))
        return r.returncode == 0 and r.stdout == cur
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def apply_worktree(top: Path, specs: dict) -> list:
    """置換を作業 tree に当てる。 当てられなかった path の説明の list を返す (空 = 全部当たった / もう当たっていた)。"""
    problems = []
    for path, sp in specs.items():
        if "reps" not in sp:
            continue
        f = top / path
        try:
            data = f.read_bytes()
        except OSError as e:
            problems.append(f"{path}: 作業 tree の file を読めない ({e})")
            continue
        new_data, bad = data, None
        for old, new in sp["reps"]:
            n = new_data.count(old)
            if n == 1:
                new_data = new_data.replace(old, new)
            elif n == 0 and new and new in new_data:
                continue                      # もう当ててある
            else:
                bad = f"{path}: 作業 tree で old が {n} 回一致 = 相手の変更が同じ場所に在る。 手で直す"
                break
        if bad:
            problems.append(bad)
        elif new_data != data:
            f.write_bytes(new_data)
    return problems


def do_commit(top: Path, specs: dict, msg_file: Path, base: str | None, dry: bool, worktree: bool) -> int:
    paths = list(specs)
    anchor = out(top, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip() if base is not None else None
    lock = index_lock(top)                    # commit の後に git を 1 回でも減らす (そこで失敗すると commit だけが残る)
    # やり直しの全部で合わせて LOCK_WAIT 秒 (回ごとに待つと、 呼び出し側の timeout に commit の後で殺されうる)
    lock_deadline = time.monotonic() + LOCK_WAIT
    for attempt in range(1, RETRIES + 1):
        if attempt > 1:
            time.sleep(BACKOFF * (attempt - 1))
        # commit の後の実 index の reset は lock が要る。 lock を別の git が持っている間は commit しない
        if not dry and not wait_unlocked(lock, lock_deadline - time.monotonic()):
            raise Stop(RC_LOCKED, f"実 index の lock ({lock}) が {LOCK_WAIT:g} 秒消えない = 別の git が実 index を使っている。 "
                                  "何も commit していない。 少し待って呼び直す (git の process が 1 つも動いていないのに残るなら、 "
                                  "落ちた git が残した lock = 消してから呼び直す)")
        # 毎回: 親を取り直し、 版を作った親 (--base) から今の HEAD までに対象の path が変わっていないかを見る。
        # 変わっていなければ 「親の版 + 自分の変更」 は今の HEAD の上でもそのまま正しい
        parent = out(top, "rev-parse", "HEAD").decode().strip()
        if anchor is not None and anchor != parent:
            if paths_changed(top, anchor, parent, paths):
                raise Stop(RC_MOVED, f"--base {anchor[:9]} から今の HEAD ({parent[:9]}) までの commit が対象の path を変えている "
                                     "= 渡された版は古い親から作ってある。 今の HEAD から版を作り直す")
            print(f"ℹ️ --base {anchor[:9]} から今の HEAD ({parent[:9]}) までの commit は対象の path を触っていない = 今の HEAD を親にする")
        built = build_versions(top, parent, specs)
        if dry:
            print(f"dry-run: 親 = {parent[:9]}。 commit されるのは次だけ (相手の未 commit の変更は入らない):")
            dry_run(top, parent, built)
            return RC_OK
        state, val = commit_once(top, parent, built, msg_file, first=(attempt == 1))
        if state == "gate":
            print("🛑 commit 時の関門が止めた。 HEAD も作業 tree も変わっていない。 git の出力:", file=sys.stderr)
            print(val, file=sys.stderr)
            return RC_GATE
        if state == "stuck":
            raise Stop(RC_STUCK, val)
        if state == "moved":
            print(f"⚠️ {val} (試行 {attempt}/{RETRIES})", file=sys.stderr)
            continue
        err = reset_real_index(top, list(built), lock)
        if err is not None:
            # 実 index が古い版のまま = 自分の commit を取り消す変更が stage 済みで、 作業 tree にも当てていない。
            # この状態で相手が素の git commit を打つと自分の変更が巻き戻る → commit を HEAD から外して (旧値つき) 元に戻す
            first_line = err.splitlines()[0] if err else "(出力なし)"
            rb = run(top, "update-ref", "HEAD", parent, val)
            if rb.returncode != 0:
                raise Stop(RC_STUCK, f"commit {val[:9]} は入ったが、 実 index を新しい HEAD に揃えられず ({first_line})、 "
                                     "その上に別の commit が重なっていて HEAD から外せない。 push せずに、 lock が消えてから "
                                     f"`git reset -q -- {' '.join(built)}` を打ち、 自分の変更を作業 tree にも当て、 "
                                     "上の commit が自分の変更を戻していないかを git log -p で見る")
            raise Stop(RC_LOCKED, f"commit {val[:9]} は入ったが、 実 index を新しい HEAD に揃えられなかった ({first_line})。 "
                                  "commit を HEAD から外して戻した = 何も commit していない (実 index も作業 tree も触っていない)。 "
                                  "少し待って呼び直す")
        problems = apply_worktree(top, specs) if worktree else []
        stat = out(top, "show", "--stat", "--format=%h %s", val).decode("utf-8", "replace").strip()
        print(f"✅ commit した (自分の分だけ。 親 = {parent[:9]}、 試行 {attempt} 回目):")
        print(stat)
        print("次: push する。 相手の session に 1 行知らせる (相手の git diff から自分の分が消えて見える)。")
        if problems:
            print("🟠 commit は入ったが、 作業 tree に同じ置換を当てられなかった:", file=sys.stderr)
            for x in problems:
                print("  " + x, file=sys.stderr)
        # 実 index を揃える前に相手が commit した (git commit -a など、 実 index の lock を持ったまま走る形は reset が
        # その終わりを待つ) = 古い実 index・作業 tree から作った commit が自分の変更を戻している恐れ。 相手が同じ file に
        # 自分の変更を残したまま足しただけなら止めない
        head = out(top, "rev-parse", "HEAD").decode().strip()
        lost = [] if head == val else [p for p in built
                                        if paths_changed(top, val, head, [p]) and not change_survives(top, parent, val, head, p)]
        if lost:
            print(f"🟠 自分の commit {val[:9]} の後に入った commit (HEAD = {head[:9]}) の版に、 自分の変更が無い: {', '.join(lost)} "
                  "= 実 index を揃える前に相手が古い実 index・作業 tree から commit した恐れ。 push せずに git log -p で見る",
                  file=sys.stderr)
            return RC_STUCK
        return RC_WORKTREE if problems else RC_OK
    raise Stop(RC_MOVED, f"HEAD が {RETRIES} 回続けて動いた。 何も commit していない (少し待って呼び直す)")


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------
def selftest() -> int:
    global LOCK_WAIT                          # lock の待ちを test ごとに短くする (finally で戻す)
    saved_wait = LOCK_WAIT
    fails = 0
    base_env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    base_env.pop(TEST_HOOK_ENV, None)
    saved = dict(os.environ)

    def g(top, *args, inp=None):
        return subprocess.run(["git", "-C", str(top), *args], input=inp, capture_output=True, env=dict(os.environ))

    def new_repo(root: Path, name: str) -> Path:
        top = root / name
        top.mkdir()
        g(top, "init", "-q", "-b", "main")
        (top / "f.txt").write_text("a\nb\nc\nd\ne\n")
        (top / "g.txt").write_text("g0\n")
        g(top, "add", "f.txt", "g.txt")
        g(top, "commit", "-q", "-m", "P")
        return top

    def call(top: Path, argv: list) -> int:
        try:
            return main(["--repo", str(top), *argv])
        except SystemExit as e:
            return int(e.code or 0)

    def ok(label: str, cond: bool, extra: str = "") -> None:
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'} {label}{(': ' + extra) if extra and not cond else ''}")

    def head_file(top, path):
        return g(top, "cat-file", "-p", f"HEAD:{path}").stdout.decode()

    root = Path(tempfile.mkdtemp(prefix="own-hunk-selftest-"))
    try:
        os.environ.clear()
        os.environ.update(base_env)
        msg = root / "msg.txt"
        msg.write_text("mine\n")

        # 1. 相手の未 commit の変更が同じ file に居る → 自分の分だけ commit、 作業 tree は両方、 index は揃う
        top = new_repo(root, "r1")
        (top / "f.txt").write_text("a-other\nb\nc\nd\ne\n")          # 相手の未 commit の変更
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        ok("自分の分だけが commit に入る (相手の未 commit の変更は入らない)",
           rc == 0 and head_file(top, "f.txt") == "a\nb\nc\nd\ne-mine\n", f"rc={rc} head={head_file(top, 'f.txt')!r}")
        ok("作業 tree は相手の変更 + 自分の変更", (top / "f.txt").read_text() == "a-other\nb\nc\nd\ne-mine\n")
        ok("実 index は新しい HEAD に揃う (status が ' M' = 自分の commit を取り消す変更が stage されていない)",
           g(top, "status", "--porcelain", "--", "f.txt").stdout.decode().startswith(" M"))

        # 2. commit 時の関門が止める → HEAD も作業 tree も変わらない
        top = new_repo(root, "r2")
        hook = top / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho blocked >&2\nexit 1\n")
        hook.chmod(0o755)
        (top / "f.txt").write_text("a-other\nb\nc\nd\ne\n")
        before_head = g(top, "rev-parse", "HEAD").stdout
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        ok("関門が止めたら終了値 1、 HEAD は動かない", rc == RC_GATE and g(top, "rev-parse", "HEAD").stdout == before_head, f"rc={rc}")
        ok("関門が止めたら作業 tree は 1 byte も変わらない (自分の変更は当たっていない)",
           (top / "f.txt").read_text() == "a-other\nb\nc\nd\ne\n")

        # 3. commit の直前に相手が commit して HEAD が動く → 相手の commit の中身を戻さず、 作り直して commit
        top = new_repo(root, "r3")
        os.environ[TEST_HOOK_ENV] = "printf 'g1\\n' >> g.txt && git add g.txt && git commit -q -m other"
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        os.environ.pop(TEST_HOOK_ENV, None)
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("HEAD が動いても相手の commit の中身が残る (g.txt が戻されていない)",
           rc == 0 and head_file(top, "g.txt") == "g0\ng1\n", f"rc={rc} g={head_file(top, 'g.txt')!r}")
        ok("履歴は 相手の commit → 自分の commit (誤った commit は HEAD に残らない)", log[:3] == ["mine", "other", "P"], str(log))
        ok("自分の変更も入っている", head_file(top, "f.txt").endswith("e-mine\n"))

        # 4. 実行 file の mode を引き継ぐ
        top = new_repo(root, "r4")
        (top / "x.sh").write_text("#!/bin/sh\necho 1\n")
        (top / "x.sh").chmod(0o755)
        g(top, "add", "x.sh")
        g(top, "commit", "-q", "-m", "x")
        rc = call(top, ["-F", str(msg), "--replace-str", "x.sh", "echo 1\n", "echo 2\n"])
        ok("実行 file の mode (100755) が落ちない", rc == 0 and g(top, "ls-tree", "HEAD", "--", "x.sh").stdout.decode().startswith("100755"))

        # 5. clean filter が掛かる (暗号化の path に平文の blob を入れない)
        top = new_repo(root, "r5")
        g(top, "config", "filter.up.clean", "tr a-z A-Z")
        g(top, "config", "filter.up.smudge", "tr A-Z a-z")
        (top / ".gitattributes").write_text("s.txt filter=up\n")
        (top / "s.txt").write_text("secret one\n")
        g(top, "add", ".gitattributes", "s.txt")
        g(top, "commit", "-q", "-m", "s")
        rc = call(top, ["-F", str(msg), "--replace-str", "s.txt", "secret one\n", "secret two\n"])
        ok("blob は path の clean filter を通る (保存された中身は filter の後の形)",
           rc == 0 and head_file(top, "s.txt") == "SECRET TWO\n", f"rc={rc} raw={head_file(top, 's.txt')!r}")

        # 6. 置換が 1 回一致でない → 止まる
        top = new_repo(root, "r6")
        (top / "f.txt").write_text("a\nb\nc\nd\ne\n")
        before_head = g(top, "rev-parse", "HEAD").stdout
        rc0 = call(top, ["-F", str(msg), "--replace-str", "f.txt", "zzz\n", "y\n"])
        (top / "h.txt").write_text("k\nk\n")
        g(top, "add", "h.txt")
        g(top, "commit", "-q", "-m", "h")
        before_head = g(top, "rev-parse", "HEAD").stdout
        rc2 = call(top, ["-F", str(msg), "--replace-str", "h.txt", "k\n", "y\n"])
        ok("old が 0 回・2 回なら終了値 2、 何も commit しない",
           rc0 == RC_USAGE and rc2 == RC_USAGE and g(top, "rev-parse", "HEAD").stdout == before_head, f"rc0={rc0} rc2={rc2}")

        # 7. --version: 新しい file / 古い --base は止まる
        top = new_repo(root, "r7")
        mine = root / "n.mine"
        mine.write_text("new file\n")
        base = g(top, "rev-parse", "HEAD").stdout.decode().strip()
        rc = call(top, ["-F", str(msg), "--base", base, "--version", "n.txt", str(mine)])
        ok("--version で新しい file を足せる (mode 100644)",
           rc == 0 and g(top, "ls-tree", "HEAD", "--", "n.txt").stdout.decode().startswith("100644") and head_file(top, "n.txt") == "new file\n")
        mine.write_text("new file v2\n")
        rc = call(top, ["-F", str(msg), "--base", base, "--version", "n.txt", str(mine)])
        ok("--base の後に同じ新しい file を足した commit が在れば終了値 4、 何も commit しない",
           rc == RC_MOVED and head_file(top, "n.txt") == "new file\n", f"rc={rc}")

        # 8. dry-run は commit しない / 相手が実 index に stage した file は自分の commit に入らない
        top = new_repo(root, "r8")
        (top / "o.txt").write_text("other staged\n")
        g(top, "add", "o.txt")                                        # 相手が実 index に stage
        before_head = g(top, "rev-parse", "HEAD").stdout
        rc = call(top, ["-F", str(msg), "--dry-run", "--replace-str", "f.txt", "e\n", "e-mine\n"])
        ok("dry-run は commit しない", rc == 0 and g(top, "rev-parse", "HEAD").stdout == before_head)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        names = g(top, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.decode().split()
        ok("相手が実 index に stage した file は自分の commit に入らず、 stage されたまま残る",
           rc == 0 and names == ["f.txt"] and g(top, "status", "--porcelain", "--", "o.txt").stdout.decode().startswith("A "), str(names))

        # 9. 作業 tree の同じ場所に相手の変更が在る → commit は入り、 終了値 3 で知らせる
        top = new_repo(root, "r9")
        (top / "f.txt").write_text("a\nb\nc\nd\ne-other\n")
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        ok("作業 tree に当てられない時は終了値 3 (commit は入り、 作業 tree の相手の変更はそのまま)",
           rc == RC_WORKTREE and head_file(top, "f.txt").endswith("e-mine\n") and (top / "f.txt").read_text().endswith("e-other\n"), f"rc={rc}")

        def other_commit(top: Path, path: str, text: str) -> None:
            (top / path).write_text(text)
            g(top, "add", path)
            g(top, "commit", "-q", "-m", "other")

        def move_head_in_hook(top: Path, path: str, line: str) -> None:
            """pre-commit の中で 1 回だけ相手の commit を入れる (git commit が HEAD を読んだ後に HEAD が動く = cannot lock ref)。"""
            h = top / ".git" / "hooks" / "pre-commit"
            h.write_text("#!/bin/sh\n[ -e .git/moved-once ] && exit 0\n: > .git/moved-once\n"
                         f"printf '{line}\\n' >> {path}\n"
                         f"(unset GIT_INDEX_FILE; git add {path} && git commit -q --no-verify -m other)\n")
            h.chmod(0o755)

        mine = root / "f.mine"
        mine.write_text("a\nb\nc\nd\ne-mine\n")                      # 版 = P の f.txt + 自分の変更

        # 10. --version: --base の後に対象の path を触らない commit が入った → 今の HEAD を親にして進める
        top = new_repo(root, "r10")
        base = g(top, "rev-parse", "HEAD").stdout.decode().strip()
        other_commit(top, "g.txt", "g0\ng1\n")
        rc = call(top, ["-F", str(msg), "--base", base, "--version", "f.txt", str(mine)])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("--base の後の commit が対象の path を触っていなければ、 今の HEAD を親にして進める",
           rc == 0 and log[:3] == ["mine", "other", "P"] and head_file(top, "f.txt") == "a\nb\nc\nd\ne-mine\n"
           and head_file(top, "g.txt") == "g0\ng1\n", f"rc={rc} log={log}")

        # 11. --version: --base の後に対象の path を触る commit が入った → 止める (版は古い親から作ってある)
        top = new_repo(root, "r11")
        base = g(top, "rev-parse", "HEAD").stdout.decode().strip()
        other_commit(top, "f.txt", "a-other\nb\nc\nd\ne\n")
        before_head = g(top, "rev-parse", "HEAD").stdout
        rc = call(top, ["-F", str(msg), "--base", base, "--version", "f.txt", str(mine)])
        ok("--base の後の commit が対象の path を触っていれば終了値 4、 何も commit しない (相手の変更が残る)",
           rc == RC_MOVED and g(top, "rev-parse", "HEAD").stdout == before_head
           and head_file(top, "f.txt") == "a-other\nb\nc\nd\ne\n", f"rc={rc}")

        # 12. commit の最中に HEAD が動く (cannot lock ref)。 対象の path を触らない commit → 親を取り直してやり直す
        top = new_repo(root, "r12")
        base = g(top, "rev-parse", "HEAD").stdout.decode().strip()
        move_head_in_hook(top, "g.txt", "g1")
        rc = call(top, ["-F", str(msg), "--base", base, "--version", "f.txt", str(mine)])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("cannot lock ref で止まっても、 対象の path が変わっていなければ親を取り直してやり直す",
           rc == 0 and log[:3] == ["mine", "other", "P"] and head_file(top, "g.txt") == "g0\ng1\n"
           and head_file(top, "f.txt") == "a\nb\nc\nd\ne-mine\n", f"rc={rc} log={log}")

        # 13. commit の最中に HEAD が動き、 その commit が対象の path を触る → --version は止める
        top = new_repo(root, "r13")
        base = g(top, "rev-parse", "HEAD").stdout.decode().strip()
        move_head_in_hook(top, "f.txt", "f-other")
        rc = call(top, ["-F", str(msg), "--base", base, "--version", "f.txt", str(mine)])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("cannot lock ref の後に対象の path が変わっていれば終了値 4、 相手の commit が HEAD に残る",
           rc == RC_MOVED and log[:2] == ["other", "P"] and head_file(top, "f.txt").endswith("f-other\n"), f"rc={rc} log={log}")

        # 14. --replace は cannot lock ref の後、 新しい親の版に置換を当て直す (相手が同じ file の別の場所を変えていても進む)
        top = new_repo(root, "r14")
        move_head_in_hook(top, "f.txt", "f-other")
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "a\n", "a-mine\n"])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("--replace は cannot lock ref の後に新しい親へ当て直す (相手の行も自分の行も HEAD に在る)",
           rc == 0 and log[:3] == ["mine", "other", "P"] and head_file(top, "f.txt") == "a-mine\nb\nc\nd\ne\nf-other\n",
           f"rc={rc} log={log} head={head_file(top, 'f.txt')!r}")

        def late_commit_on_top(top: Path) -> None:
            """自分の commit の直後 (post-commit) に 1 回だけ、 相手がその上に commit を重ねる。"""
            h = top / ".git" / "hooks" / "post-commit"
            h.write_text("#!/bin/sh\n[ \"$(git log -1 --format=%s)\" = mine ] || exit 0\n[ -e .git/late-once ] && exit 0\n"
                         ": > .git/late-once\n"
                         "(unset GIT_INDEX_FILE; git reset -q && printf 'h\\n' > h.txt && git add h.txt && git commit -q --no-verify -m late)\n")
            h.chmod(0o755)

        # 15. 自分の commit (親は正しい) の直後に相手が上に重ねる → 相手の commit を外さず、 自分の commit も 1 回だけ
        top = new_repo(root, "r15")
        late_commit_on_top(top)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "c\n", "c-mine\n"])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("相手が自分の commit の上に重ねた commit を外さない (自分の commit を HEAD から探す)",
           rc == 0 and log[:3] == ["late", "mine", "P"] and head_file(top, "f.txt") == "a\nb\nc-mine\nd\ne\n"
           and head_file(top, "h.txt") == "h\n", f"rc={rc} log={log} f={head_file(top, 'f.txt')!r}")

        # 16. 誤った親の commit の上に相手が重ねた → 外せないので終了値 5、 やり直して commit を重ねない
        top = new_repo(root, "r16")
        late_commit_on_top(top)
        os.environ[TEST_HOOK_ENV] = "printf 'g1\\n' >> g.txt && git add g.txt && git commit -q -m other"
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "c\n", "c-mine\n"])
        os.environ.pop(TEST_HOOK_ENV, None)
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("誤った commit を HEAD から外せない時は終了値 5 で止まり、 相手の commit を外さず上に重ねもしない",
           rc == RC_STUCK and log[:4] == ["late", "mine", "other", "P"], f"rc={rc} log={log}")

        # 17. 自分の commit の直後に、 相手が同じ tree の commit (空の commit) を上に重ねる → 件名で見分けて外さない
        top = new_repo(root, "r17")
        h = top / ".git" / "hooks" / "post-commit"
        h.write_text("#!/bin/sh\n[ \"$(git log -1 --format=%s)\" = mine ] || exit 0\n[ -e .git/late-once ] && exit 0\n"
                     ": > .git/late-once\n(unset GIT_INDEX_FILE; git reset -q && git commit -q --no-verify --allow-empty -m late)\n")
        h.chmod(0o755)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "c\n", "c-mine\n"])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("上に重なった同じ tree の commit (空の commit) を自分のと取り違えて外さない",
           rc == 0 and log[:3] == ["late", "mine", "P"] and head_file(top, "f.txt") == "a\nb\nc-mine\nd\ne\n", f"rc={rc} log={log}")

        def lock_after_commit(top: Path, release_after: float | None, stack: bool = False) -> None:
            """自分の commit の直後 (post-commit) に 1 回だけ、 別の git が実 index の lock を取る。 release_after 秒で放す
            (None = 放さない = 落ちた git が残した lock)。 stack = 相手が index を使わずに上へ commit を重ねる。"""
            release = f"(sleep {release_after}; rm -f .git/index.lock) >/dev/null 2>&1 &\n" if release_after is not None else ""
            late = "c=$(git commit-tree 'HEAD^{tree}' -p HEAD -m late) && git update-ref HEAD \"$c\"\n" if stack else ""
            h = top / ".git" / "hooks" / "post-commit"
            h.write_text("#!/bin/sh\n[ \"$(git log -1 --format=%s)\" = mine ] || exit 0\n[ -e .git/lock-once ] && exit 0\n"
                         ": > .git/lock-once\n: > .git/index.lock\n" + release + late)
            h.chmod(0o755)

        def index_entry(top: Path, path: str) -> str:
            return g(top, "ls-files", "-s", "--", path).stdout.decode()

        def reflog_len(top: Path) -> int:
            return len(g(top, "reflog", "--format=%H", "HEAD").stdout.decode().split())

        # 18. 実 index の lock が commit の前から在る (別の git が使っている / 落ちた git が残した) → commit しない
        LOCK_WAIT = 0.3
        top = new_repo(root, "r18")
        (top / "f.txt").write_text("a-other\nb\nc\nd\ne\n")
        before = (g(top, "rev-parse", "HEAD").stdout, index_entry(top, "f.txt"), reflog_len(top))
        (top / ".git" / "index.lock").write_text("")
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        ok("実 index の lock が消えなければ commit せずに終了値 6 (HEAD・reflog・実 index・作業 tree が変わらない)",
           rc == RC_LOCKED and (g(top, "rev-parse", "HEAD").stdout, index_entry(top, "f.txt"), reflog_len(top)) == before
           and (top / "f.txt").read_text() == "a-other\nb\nc\nd\ne\n", f"rc={rc}")

        # 19. commit の後に別の git が実 index の lock を取り、 少しして放す → 待って揃え、 作業 tree にも当てる
        LOCK_WAIT = 5.0
        top = new_repo(root, "r19")
        (top / "f.txt").write_text("a-other\nb\nc\nd\ne\n")
        lock_after_commit(top, release_after=0.2)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        ok("commit の後に lock に当たっても、 lock が消えたら実 index を揃えて作業 tree にも当てる",
           rc == 0 and head_file(top, "f.txt") == "a\nb\nc\nd\ne-mine\n"
           and (top / "f.txt").read_text() == "a-other\nb\nc\nd\ne-mine\n"
           and g(top, "status", "--porcelain", "--", "f.txt").stdout.decode().startswith(" M"),
           f"rc={rc} work={(top / 'f.txt').read_text()!r} status={g(top, 'status', '--porcelain', '--', 'f.txt').stdout!r}")

        # 20. commit の後に取られた lock が消えない → commit を HEAD から外して終了値 6 (何もしなかった状態に戻る)
        LOCK_WAIT = 0.3
        top = new_repo(root, "r20")
        (top / "f.txt").write_text("a-other\nb\nc\nd\ne\n")
        lock_after_commit(top, release_after=None)
        before = (g(top, "rev-parse", "HEAD").stdout, index_entry(top, "f.txt"))
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        ok("commit の後の lock が消えなければ commit を HEAD から外して終了値 6 (実 index・作業 tree も元のまま)",
           rc == RC_LOCKED and (g(top, "rev-parse", "HEAD").stdout, index_entry(top, "f.txt")) == before
           and (top / "f.txt").read_text() == "a-other\nb\nc\nd\ne\n", f"rc={rc} log={g(top, 'log', '--format=%s').stdout!r}")

        # 21. 20 の上に、 相手が index を使わずに commit を重ねた → 相手の commit を外さずに終了値 5
        top = new_repo(root, "r21")
        lock_after_commit(top, release_after=None, stack=True)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("lock で揃えられず、 上に相手の commit が重なっていれば外さずに終了値 5",
           rc == RC_STUCK and log[:3] == ["late", "mine", "P"], f"rc={rc} log={log}")

        # 22. 自分の commit の後、 実 index を揃える前に相手が作業 tree から commit した (git commit -a) → 自分の変更が戻る
        top = new_repo(root, "r22")
        (top / "f.txt").write_text("a-other\nb\nc\nd\ne\n")
        h = top / ".git" / "hooks" / "post-commit"
        h.write_text("#!/bin/sh\n[ \"$(git log -1 --format=%s)\" = mine ] || exit 0\n[ -e .git/late-once ] && exit 0\n"
                     ": > .git/late-once\n(unset GIT_INDEX_FILE; git commit -q -a --no-verify -m late)\n")
        h.chmod(0o755)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("実 index を揃える前に入った相手の commit が自分の変更を戻したら終了値 5 で知らせる (作業 tree には自分の変更を当てる)",
           rc == RC_STUCK and log[:3] == ["late", "mine", "P"] and head_file(top, "f.txt") == "a-other\nb\nc\nd\ne\n"
           and (top / "f.txt").read_text() == "a-other\nb\nc\nd\ne-mine\n", f"rc={rc} log={log}")

        # 23. 自分の commit の後、 相手が同じ file に自分の変更を残したまま足した commit → 止めない (22 の誤検出の foil)
        top = new_repo(root, "r23")
        h = top / ".git" / "hooks" / "post-commit"
        h.write_text("#!/bin/sh\n[ \"$(git log -1 --format=%s)\" = mine ] || exit 0\n[ -e .git/late-once ] && exit 0\n"
                     ": > .git/late-once\n(unset GIT_INDEX_FILE; git cat-file -p HEAD:f.txt > f.txt && printf 'late\\n' >> f.txt "
                     "&& git add f.txt && git commit -q --no-verify -m late)\n")
        h.chmod(0o755)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "c\n", "c-mine\n"])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("相手が同じ file に自分の変更を残したまま足した commit では止めない (終了値 0)",
           rc == 0 and log[:3] == ["late", "mine", "P"] and head_file(top, "f.txt") == "a\nb\nc-mine\nd\ne\nlate\n", f"rc={rc} log={log}")

        # 24〜26. git の前提 (docstring の「限界」 と規約の文の根拠。 ここが落ちたら、 git の版で振る舞いが変わった = 両方を見直す)
        def hook_saw_lock(name: str, argv: list) -> bool:
            top = new_repo(root, name)
            h = top / ".git" / "hooks" / "pre-commit"
            h.write_text("#!/bin/sh\nif [ -e .git/index.lock ]; then : > .git/saw-lock; fi\n")
            h.chmod(0o755)
            (top / "f.txt").write_text("changed\n")
            g(top, "add", "f.txt")
            (top / "f.txt").write_text("changed again\n")
            g(top, "commit", "-q", "-m", "x", *argv)
            return (top / ".git" / "saw-lock").exists()

        ok("git の前提: hook の走る間に実 index の lock を持つのは -a と -- <path> で、 素の commit は持たない",
           (hook_saw_lock("r24a", ["-a"]), hook_saw_lock("r24b", ["--", "f.txt"]), hook_saw_lock("r24c", [])) == (True, True, False))

        top = new_repo(root, "r25")
        (top / "f.txt").write_text("changed\n")
        g(top, "add", "f.txt")
        (top / ".git" / "index.lock").write_text("")
        before_head = g(top, "rev-parse", "HEAD").stdout
        r = g(top, "commit", "-q", "-m", "x")
        ok("git の前提: lock が在ると素の commit は始まらない", r.returncode != 0 and g(top, "rev-parse", "HEAD").stdout == before_head)
        (top / ".git" / "index.lock").unlink()

        top = new_repo(root, "r26")
        (top / "f.txt").write_text("changed\n")
        (top / "g.txt").write_text("g-hook\n")
        g(top, "add", "f.txt")
        h = top / ".git" / "hooks" / "pre-commit"
        h.write_text("#!/bin/sh\ngit add g.txt\n")
        h.chmod(0o755)
        g(top, "commit", "-q", "-m", "x")
        ok("git の前提: 素の commit は pre-commit の後に実 index を読み直して tree を作る", head_file(top, "g.txt") == "g-hook\n")

        def slow_other(top: Path) -> None:
            """相手の commit の pre-commit だけを遅くする。 環境変数で見分ける = 一時 dir の名前に入る語を条件にしない。"""
            h = top / ".git" / "hooks" / "pre-commit"
            h.write_text("#!/bin/sh\n[ -z \"$SLOW_OTHER\" ] || sleep 0.4\n")
            h.chmod(0o755)

        # 27. 本物の git commit -a が lock を持っている間に呼ぶ → 待って、 相手の commit の上に commit する
        LOCK_WAIT = 5.0
        top = new_repo(root, "r27")
        slow_other(top)
        (top / "f.txt").write_text("a-other\nb\nc\nd\ne\n")
        p = subprocess.Popen(["git", "-C", str(top), "commit", "-q", "-a", "-m", "other"], env=dict(os.environ, SLOW_OTHER="1"),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        lock_file, limit = top / ".git" / "index.lock", time.monotonic() + 5
        while not lock_file.exists() and time.monotonic() < limit:
            time.sleep(0.005)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        p.wait()
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("本物の git commit -a が lock を持つ間は待ち、 相手の commit の上に commit する",
           rc == 0 and log[:3] == ["mine", "other", "P"] and head_file(top, "f.txt") == "a-other\nb\nc\nd\ne-mine\n"
           and (top / "f.txt").read_text() == "a-other\nb\nc\nd\ne-mine\n", f"rc={rc} log={log}")

        # 28. 自分の commit の直後に本物の git commit -a が lock を取る → reset が待ち、 相手が古い作業 tree から戻したのを終了値 5 で知らせる
        top = new_repo(root, "r28")
        slow_other(top)
        (top / "f.txt").write_text("a-other\nb\nc\nd\ne\n")
        h = top / ".git" / "hooks" / "post-commit"
        h.write_text("#!/bin/sh\n[ \"$(git log -1 --format=%s)\" = mine ] || exit 0\n[ -e .git/late-once ] && exit 0\n"
                     ": > .git/late-once\n(unset GIT_INDEX_FILE; SLOW_OTHER=1 git commit -q -a -m late) >/dev/null 2>&1 &\n"
                     "i=0; while [ ! -e .git/index.lock ] && [ $i -lt 300 ]; do sleep 0.01; i=$((i+1)); done\n")
        h.chmod(0o755)
        rc = call(top, ["-F", str(msg), "--replace-str", "f.txt", "e\n", "e-mine\n"])
        log = g(top, "log", "--format=%s").stdout.decode().split()
        ok("本物の git commit -a が commit の直後に lock を取っても待ち、 戻されたら終了値 5 (作業 tree には自分の変更)",
           rc == RC_STUCK and log[:3] == ["late", "mine", "P"] and head_file(top, "f.txt") == "a-other\nb\nc\nd\ne\n"
           and (top / "f.txt").read_text() == "a-other\nb\nc\nd\ne-mine\n", f"rc={rc} log={log}")
    finally:
        LOCK_WAIT = saved_wait
        os.environ.clear()
        os.environ.update(saved)
        shutil.rmtree(root, ignore_errors=True)
    print("ALL PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", help="repo の中の dir (既定 = cwd)")
    ap.add_argument("-F", "--message-file", help="commit message の file")
    ap.add_argument("--replace", nargs=3, action="append", metavar=("PATH", "OLDFILE", "NEWFILE"), default=[],
                    help="親の版と作業 tree の PATH で、 OLDFILE の中身を NEWFILE の中身に置き換える (ちょうど 1 回一致)")
    ap.add_argument("--replace-str", nargs=3, action="append", metavar=("PATH", "OLD", "NEW"), default=[],
                    help="同上、 文字列で渡す")
    ap.add_argument("--version", nargs=2, action="append", metavar=("PATH", "FILE"), default=[],
                    help="PATH の全文 (親の版 + 自分の変更) を FILE で渡す。 --base が要る")
    ap.add_argument("--base", help="--version の版を作った時の HEAD")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-worktree", action="store_true", help="置換を作業 tree に当てない")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    try:
        cwd = Path(args.repo).resolve() if args.repo else Path.cwd()
        top = repo_top(cwd)
        if not args.message_file and not args.dry_run:
            raise Stop(RC_USAGE, "-F <commit message の file> が要る")
        if args.version and not args.base:
            raise Stop(RC_USAGE, "--version には --base <版を作った時の HEAD> が要る")
        specs: dict = {}
        for p, of, nf in args.replace:
            specs.setdefault(rel_path(top, p, cwd), {}).setdefault("reps", []).append((Path(of).read_bytes(), Path(nf).read_bytes()))
        for p, o, n in args.replace_str:
            specs.setdefault(rel_path(top, p, cwd), {}).setdefault("reps", []).append((o.encode(), n.encode()))
        for p, f in args.version:
            rp = rel_path(top, p, cwd)
            if rp in specs:
                raise Stop(RC_USAGE, f"{rp}: --replace と --version を同じ path に混ぜない")
            specs[rp] = {"version": Path(f).read_bytes()}
        if not specs:
            raise Stop(RC_USAGE, "--replace / --replace-str / --version のどれかが要る")
        msg = Path(args.message_file).resolve() if args.message_file else Path(os.devnull)
        return do_commit(top, specs, msg, args.base, args.dry_run, not args.no_worktree)
    except Stop as e:
        print(f"git-commit-own-hunk: {e}", file=sys.stderr)
        return e.rc


if __name__ == "__main__":
    sys.exit(main())
