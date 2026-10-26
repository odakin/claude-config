"""intersect_sync.py — 遅れているだけの clone で、 未 commit の変更が upstream の変更と同じ file に当たって最新化できない形を、
相手の変更を保ったまま解く (平文の 3-way + 両側の行の照合 → 交差した file だけ HEAD に戻して ff → 合わせた版を書き戻す)。

正本の手順 = conventions/multi-session-coordination.md#owner-gone-intersect-sync (①〜⑤)。 本 module はその機械化:
  trial(repo)  = 読むだけ。 交差した file ごとに、 作業 tree・HEAD・upstream の 3 版を平文で取り (git-crypt は
                 `git cat-file --filters` = smudge を通す)、 `git merge-file -p` で合わせ、 両側が足した行が合わせた版に
                 残るかを数える。 repo の file・index・ref には触らない (git の optional lock も取らない)。
  apply(repo)  = trial と同じ判定が全部 clean のときだけ、 同期の sweep と同じ lock の内側で ③ 控え → ④ 交差した file を
                 HEAD に戻して `merge --ff-only @{u}` → ⑤ 合わせた版を書き戻す。 ff が通らなければ控えから戻す。
                 作業 tree の file が最近書かれた (持ち主が作業中かもしれない) ときは触らない (min_age_min)。
  record / report = 試走の結果を machine-local の記録 (JSONL) に書き、 期間で集計する。 記録には path を書かない
                 (path の hash と拡張子・数だけ = file 名に人や案件が出る repo がある)。

扱わない形 (verdict): conflict (同じ所を両側が変えた) / staged (交差した file を誰かが stage している = 戻すと相手の
  stage を消す) / binary / deleted (どちらかが file を消した) / error (平文を読めない = git-crypt の鍵が無い等) /
  ahead (手元にだけ在る commit がある = 通常の分岐、 #ordinary-divergence-replay) / busy (merge・rebase の途中) /
  none (遅れていない・交差が無い = 普通の ff で済む)。
なぜ (実測): 遅れた clone の未 commit が upstream の同じ file に当たると同期の sweep は「持ち主の commit 待ち」 で止まり、
  持ち主の session には届かないまま何時間も止まった。 同じ変更が両側に在る形 (記録を 2 つの機械が書いた・origin の worktree で
  push した後の live copy) は平文の 3-way で衝突なく 1 つになる。
同期に自動で繋ぐかは試走の記録を見てから決める (それまで sweep と fleet heartbeat は trial だけを呼ぶ)。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

LOCK_NAME = "claude-sync-sweep.lock"   # scripts/repo-sync-sweep.sh と同じ lock (= sweep と apply が同時に HEAD を動かさない)
LOCK_STALE_S = int(os.environ.get("CLAUDE_SYNC_SWEEP_LOCK_STALE", "300") or 300)
MIN_AGE_MIN = 30                       # apply: 交差した file がこれより最近書かれていたら触らない (持ち主が作業中かもしれない)
DEFAULT_LOG = Path.home() / ".claude" / "state" / "intersect-sync-trial.jsonl"
GIT_TIMEOUT = 30


def log_path() -> Path:
    v = os.environ.get("CLAUDE_INTERSECT_SYNC_LOG")
    return Path(os.path.expanduser(v)) if v else DEFAULT_LOG


def _env() -> dict:
    e = dict(os.environ)
    e["GIT_OPTIONAL_LOCKS"] = "0"      # 読むだけの git (status 等) が index の lock を取らない = 並列の session の git add を邪魔しない
    e["GIT_TERMINAL_PROMPT"] = "0"
    e.pop("GIT_DIR", None)
    e.pop("GIT_WORK_TREE", None)
    e.pop("GIT_INDEX_FILE", None)
    return e


def git(repo, *args, check=False, binary=False, stdin=None):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=_env(), timeout=GIT_TIMEOUT, input=stdin)
    out = p.stdout if binary else p.stdout.decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return p.returncode, out


def _z(out: str) -> list[str]:
    return [x for x in out.split("\0") if x]


def repo_root(path) -> Path | None:
    rc, out = git(path, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if rc == 0 and out.strip() else None


def path_hash(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]


def _git_dir(repo, common=False) -> Path | None:
    rc, out = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir" if common else "--git-dir")
    return Path(out.strip()) if rc == 0 and out.strip() else None


def _busy(repo) -> bool:
    gd = _git_dir(repo)
    return bool(gd) and any((gd / n).exists() for n in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"))


def repo_state(repo) -> dict:
    """遅れ・手元にだけ在る commit・交差した file (未 commit の変更 ∩ upstream が変えた file)・stage 済みの file。"""
    st = {"behind": 0, "ahead": 0, "overlap": [], "staged": [], "busy": False, "upstream": None}
    rc, up = git(repo, "rev-parse", "--verify", "-q", "@{u}")
    if rc != 0:
        return st
    st["upstream"] = up.strip()
    _, b = git(repo, "rev-list", "--count", "HEAD..@{u}")
    _, a = git(repo, "rev-list", "--count", "@{u}..HEAD")
    st["behind"], st["ahead"] = int(b.strip() or 0), int(a.strip() or 0)
    st["busy"] = _busy(repo)
    if st["behind"] == 0:
        return st
    _, chg = git(repo, "diff", "--name-only", "-z", "HEAD", "@{u}")
    _, wt = git(repo, "diff", "--name-only", "-z")
    _, ix = git(repo, "diff", "--cached", "--name-only", "-z")
    changed, staged = set(_z(chg)), set(_z(ix))
    st["overlap"] = sorted(changed & (set(_z(wt)) | staged))
    st["staged"] = sorted(changed & staged)
    return st


def _blob(repo, rev: str, rel: str) -> bytes | None:
    """rev の rel を平文で (smudge filter を通す = git-crypt の file も鍵があれば平文)。 無ければ None。"""
    rc, out = git(repo, "cat-file", "--filters", f"{rev}:{rel}", binary=True)
    return out if rc == 0 else None


def _encrypted(repo, rel: str) -> bool:
    _, out = git(repo, "check-attr", "filter", "--", rel)
    return out.strip().endswith(": git-crypt")


def _lines(b: bytes) -> list[bytes]:
    return b.splitlines(keepends=False)


def _is_binary(*blobs) -> bool:
    return any(b is not None and b"\0" in b[:8192] for b in blobs)


def _merge(tree: bytes, base: bytes, up: bytes) -> tuple[int, bytes]:
    """git merge-file -p <tree> <base> <upstream> → (衝突の数, 合わせた版)。 一時 file は 0700 の dir に置いて消す。"""
    with tempfile.TemporaryDirectory(prefix="intersect-sync-") as td:
        os.chmod(td, 0o700)
        paths = []
        for name, data in (("tree", tree), ("base", base), ("upstream", up)):
            p = os.path.join(td, name)
            with open(p, "wb") as fh:
                fh.write(data)
            paths.append(p)
        p = subprocess.run(["git", "merge-file", "-p", "-L", "tree", "-L", "HEAD", "-L", "upstream", *paths],
                           capture_output=True, timeout=GIT_TIMEOUT, env=_env())
        if p.returncode < 0:
            raise RuntimeError("git merge-file が失敗した")
        return p.returncode, p.stdout


def lost_lines(base: bytes, tree: bytes, up: bytes, merged: bytes) -> int:
    """② 両側が足した行が合わせた版に残っているかを数える。 欠けた行の数 (0 = 欠けなし)。

    行 L の数の変化 n_tree = tree − base、 n_up = upstream − base。 どちらかが L を足していれば、 合わせた版の L の数は
    下限 = base + max(n_tree, n_up) (両側が足しただけ = 同じ変更なら 1 つに、 別の変更なら両方) / base + n_tree + n_up
    (片側が足し、 もう片側が減らした) 以上のはず。 下限を割った分を数える (保守的 = 別の所に同じ行を足した形は欠けに見える
    ことがあるが、 欠けを見逃す側には倒れない)。"""
    cb, ct, cu, cm = (Counter(_lines(x)) for x in (base, tree, up, merged))
    lost = 0
    for ln in set(ct) | set(cu):
        nt, nu = ct[ln] - cb[ln], cu[ln] - cb[ln]
        if nt <= 0 and nu <= 0:
            continue
        lb = cb[ln] + (max(nt, nu) if nt >= 0 and nu >= 0 else nt + nu)
        lost += max(0, lb - cm[ln])
    return lost


def file_result(repo, rel: str, staged: set, now: float | None = None) -> dict:
    """交差した 1 file の判定 (merged の bytes は '_merged' に入れる = 記録には書かない)。"""
    now = now if now is not None else time.time()
    r = {"h": path_hash(rel), "ext": os.path.splitext(rel)[1].lower()[:8], "verdict": "error"}
    p = Path(repo) / rel
    try:
        r["enc"] = _encrypted(repo, rel)
        if rel in staged:
            r["verdict"] = "staged"
            return r
        base, up = _blob(repo, "HEAD", rel), _blob(repo, "@{u}", rel)
        if not p.exists() or base is None or up is None:
            r["verdict"] = "deleted"
            return r
        if p.is_symlink() or not p.is_file():
            r["verdict"] = "binary"
            return r
        tree = p.read_bytes()
        r["tree_age_min"] = int(max(0, now - p.stat().st_mtime) // 60)
        if _is_binary(base, tree, up):
            r["verdict"] = "binary"
            return r
        conflicts, merged = _merge(tree, base, up)
        r["conflicts"] = conflicts
        nt = Counter(_lines(tree)) - Counter(_lines(base))
        nu = Counter(_lines(up)) - Counter(_lines(base))
        r["tree_added"], r["up_added"] = sum(nt.values()), sum(nu.values())
        r["tree_unique"] = sum((Counter(_lines(tree)) - Counter(_lines(up))).values())
        if conflicts:
            r["verdict"] = "conflict"
            return r
        r["lost"] = lost_lines(base, tree, up, merged)
        r["subsumed"] = merged == up          # 手元の変更を upstream が全部含む (#upstream-subsumes-local)
        r["verdict"] = "clean" if r["lost"] == 0 else "lost"
        r["_merged"], r["_tree"] = merged, tree
    except Exception as exc:  # 1 file の故障を判定として返す (= 他の file と repo の判定を止めない)
        r["verdict"] = "error"
        r["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return r


_RANK = ["error", "lost", "conflict", "staged", "deleted", "binary", "clean"]


def trial(repo, now: float | None = None) -> dict:
    """読むだけの判定。 verdict = clean (全部の交差した file が衝突も欠けも無く合わさる) / 最も悪い file の verdict /
    ahead / busy / none。 files は記録に書ける形 (path は hash)。 '_files' に merged 等を含む内部の結果。"""
    root = repo_root(repo)
    res = {"repo": Path(repo).name, "verdict": "none", "files": [], "at": int(now if now is not None else time.time())}
    if root is None:
        res["verdict"] = "error"
        return res
    res["repo"] = root.name
    st = repo_state(root)
    res.update(behind=st["behind"], ahead=st["ahead"], overlap=len(st["overlap"]))
    if st["behind"] == 0 or not st["overlap"]:
        return res
    if st["ahead"]:
        res["verdict"] = "ahead"
        return res
    if st["busy"]:
        res["verdict"] = "busy"
        return res
    staged = set(st["staged"])
    full = [file_result(root, rel, staged, now) for rel in st["overlap"]]
    res["_files"] = list(zip(st["overlap"], full))
    res["files"] = [{k: v for k, v in f.items() if not k.startswith("_")} for f in full]
    verdicts = [f["verdict"] for f in full]
    res["verdict"] = min(verdicts, key=_RANK.index) if verdicts else "none"
    res["state"] = hashlib.sha1(json.dumps([st["upstream"], git(root, "rev-parse", "HEAD")[1].strip(),
                                            [hashlib.sha1(f.get("_tree", b"")).hexdigest() for f in full]]).encode()
                                ).hexdigest()[:12]
    return res


def public(res: dict) -> dict:
    """記録・表示に出してよい形 (内部の bytes を落とす)。"""
    return {k: v for k, v in res.items() if not k.startswith("_")}


def record(res: dict, mode: str = "trial", source: str = "", path: Path | None = None) -> None:
    """machine-local の記録に 1 行足す (path・中身は書かない)。 失敗しても黙る。"""
    if res.get("verdict") == "none":
        return
    path = path or log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = dict(public(res), mode=mode, source=source, host=os.uname().nodename.split(".")[0])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass


def one_line(res: dict) -> str:
    """sweep の A 行・fleet の行に添える短い日本語 (試走の結果)。"""
    v = res.get("verdict")
    files = res.get("files") or []
    n = len(files)
    if v == "clean":
        sub = sum(1 for f in files if f.get("subsumed"))
        extra = f"、 うち {sub} file は upstream が手元の変更を全部含む" if sub else ""
        return f"試走: 道具なら衝突も欠けも無く解ける見込み ({n} file{extra}。 記録だけ、 書き換えはしない)"
    names = {"conflict": "同じ所を両側が変えている", "staged": "stage 済みの file がある", "binary": "binary の file",
             "deleted": "どちらかが file を消した", "lost": "合わせると行が欠ける", "error": "平文を読めない file がある",
             "ahead": "手元にだけ在る commit がある", "busy": "merge / rebase の途中"}
    if v in names:
        return f"試走: 道具では解けない ({names[v]}) = 人が解く"
    return ""


# ---------------- apply (手で呼ぶ。 同期にはまだ繋いでいない) ----------------

def _lock(gcd: Path):
    lk = gcd / LOCK_NAME
    owner = f"{os.getpid()} {int(time.time())} {os.urandom(2).hex()}"
    for _ in range(2):
        try:
            lk.mkdir()
            (lk / "owner").write_text(owner + "\n")
            return lk, owner
        except FileExistsError:
            try:
                o = (lk / "owner").read_text().strip()
            except OSError:
                o = ""
            parts = o.split()
            stale = False
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                try:
                    os.kill(int(parts[0]), 0)
                    stale = time.time() - int(parts[1]) > LOCK_STALE_S
                except ProcessLookupError:
                    stale = True
                except PermissionError:
                    stale = False
            if not stale:
                return None, o
            tmp = lk.with_name(f"{LOCK_NAME}.stale.{os.getpid()}")
            try:
                lk.rename(tmp)
                if (tmp / "owner").read_text().strip() == o:
                    for f in tmp.iterdir():
                        f.unlink()
                    tmp.rmdir()
                else:
                    tmp.rename(lk)
                    return None, o
            except OSError:
                return None, o
    return None, ""


def _unlock(lk: Path, owner: str) -> None:
    try:
        if (lk / "owner").read_text().strip() == owner:
            (lk / "owner").unlink()
            lk.rmdir()
    except OSError:
        pass


def apply(repo, min_age_min: int = MIN_AGE_MIN) -> dict:
    """①〜⑤ を行う。 戻り値 = public な結果 + applied (True/False) + reason。 書くのは交差した file と HEAD (ff) だけ。"""
    root = repo_root(repo)
    if root is None:
        return {"verdict": "error", "applied": False, "reason": "git の repo でない"}
    gcd = _git_dir(root, common=True)
    if gcd is None:
        return {"verdict": "error", "applied": False, "reason": "git dir を解決できない"}
    lk, owner = _lock(gcd)
    if lk is None:
        return {"repo": root.name, "verdict": "error", "applied": False,
                "reason": f"同期の sweep か別の apply がこの repo を処理中 (lock: {owner or '?'})"}
    try:
        res = trial(root)
        out = dict(public(res), applied=False)
        if res["verdict"] != "clean":
            out["reason"] = one_line(res) or f"交差が無い・遅れていない ({res['verdict']})"
            return out
        young = [f for _, f in res["_files"] if f.get("tree_age_min", 0) < min_age_min]
        if young:
            out["reason"] = (f"交差した file のうち {len(young)} つが {min_age_min} 分以内に書かれた = 持ち主が作業中かもしれない"
                             f" (待つか、 持ち主に commit させる)")
            return out
        files = res["_files"]
        # ③ 控え (= 作業 tree の版。 書き戻しを確かめたら消す)、 merge に使った版から変わっていないことも確かめる
        backup = {}
        for rel, f in files:
            p = root / rel
            cur = p.read_bytes()
            if cur != f["_tree"]:
                out["reason"] = "判定の後に作業 tree の file が書き換わった = 持ち主が作業中 (触らない)"
                return out
            backup[rel] = (cur, stat.S_IMODE(p.stat().st_mode))
        rels = [rel for rel, _ in files]
        # ④ 交差した file だけ HEAD (= index) に戻して ff
        rc, _ = git(root, "checkout", "--", *rels)
        ok = rc == 0 and git(root, "merge", "--ff-only", "-q", "@{u}")[0] == 0
        if not ok:
            for rel, (data, mode) in backup.items():
                (root / rel).write_bytes(data)
                os.chmod(root / rel, mode)
            out["reason"] = "ff が通らなかった = 控えから作業 tree の版を戻した (何も変わっていない)"
            return out
        # ⑤ 合わせた版を書き戻す = 相手の未 commit は新しい HEAD の上の差分として残る
        bad = []
        for rel, f in files:
            p = root / rel
            p.write_bytes(f["_merged"])
            os.chmod(p, backup[rel][1])
            if p.read_bytes() != f["_merged"]:
                bad.append(rel)
        out["applied"] = not bad
        out["reason"] = ("最新化した: 交差した file は upstream の版 + 手元の未 commit の差分になった" if not bad
                         else f"書き戻しを確かめられない file がある ({len(bad)} つ) = 手で確かめる")
        return out
    finally:
        _unlock(lk, owner)


# ---------------- report ----------------

def report(days: int = 7, path: Path | None = None, now: float | None = None) -> str:
    path = path or log_path()
    now = now if now is not None else time.time()
    since = now - days * 86400
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and int(r.get("at", 0)) >= since:
                    rows.append(r)
    except OSError:
        return f"記録が無い ({path})"
    if not rows:
        return f"直近 {days} 日の記録は 0 行 ({path})"
    sit: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("host", "?"), r.get("repo", "?"), r.get("state") or r.get("verdict"))
        s = sit.setdefault(key, {"first": r["at"], "last": r["at"], "n": 0, "verdict": r.get("verdict"),
                                 "files": len(r.get("files") or []), "sub": 0, "applied": 0, "sources": set()})
        s["first"], s["last"], s["n"] = min(s["first"], r["at"]), max(s["last"], r["at"]), s["n"] + 1
        s["sub"] = max(s["sub"], sum(1 for f in r.get("files") or [] if f.get("subsumed")))
        s["applied"] += 1 if r.get("applied") else 0
        s["sources"].add(r.get("source") or r.get("mode") or "?")
    by = Counter(s["verdict"] for s in sit.values())
    lines = [f"intersect-sync の試走の記録 (直近 {days} 日、 {path}): 詰まり (機械 × repo × 状態) {len(sit)} 件を {len(rows)} 回観測",
             "  verdict ごと: " + " / ".join(f"{k} {v}" for k, v in by.most_common())]
    for (host, repo, _), s in sorted(sit.items(), key=lambda kv: kv[1]["first"]):
        dur = (s["last"] - s["first"]) / 3600
        lines.append(f"  - {time.strftime('%m/%d %H:%M', time.localtime(s['first']))} {host} {repo}: {s['verdict']}"
                     f" ({s['files']} file、 upstream が全部含む {s['sub']}、 {s['n']} 回・{dur:.1f} 時間見えた、"
                     f" 出どころ {'/'.join(sorted(s['sources']))}{'、 apply 済み' if s['applied'] else ''})")
    return "\n".join(lines)
