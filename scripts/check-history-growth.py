#!/usr/bin/env python3
"""check-history-growth.py — 差分が効かない file (暗号化・PDF・画像) を頻繁に commit して、 版ごとに全体が git の履歴に積まれるのを早めに見つける。

## なぜ要るのか

git は text の版どうしを差分で詰めるが、 **暗号化された blob (git-crypt) と binary (PDF・画像・zip) は詰められない**。
だから「大きめの file を 1 日に何度も commit する」 と、 1 commit ごとに file の大きさがそのまま履歴に足される。
台帳 1 file (1 MB) × 1 日 60 commit なら 1 日 60 MB、 数か月で repo が GB 単位になる (実測)。
repo の大きさは clone・fetch・gc・backup の全部に効き、 縮めるには履歴の書き換え (不可逆・全 machine の追従) しかない。
= **置き方で決まる**ので、 大きくなる前 (増え方の段階) に見つけて置き方を変える。
対策の正本 = [`conventions/repo-history-growth.md`](../conventions/repo-history-growth.md)
(生成物は作り直すたびに commit しない / 暗号化して書き足す台帳は 1 entry 1 file / 既に積まれた分を落とすなら
[`git-drop-path-history.py`](git-drop-path-history.py))。

## 何を見るか

直近 `--days` 日 (既定 30) の commit で、 path ごとに「新しい版の数」 と「版の大きさの合計」 を数える。
対象は**保存された blob が binary の path だけ** (先頭 8000 byte に NUL = git 自身の判定と同じ。 git-crypt の暗号文もここに入る)。
text の path は差分で詰まるので数えない。

finding (閾値は本 file の定数だけが持つ):
- 🟠 **path の増え方**: 期間内の版の合計が `PATH_TOTAL_MIB` 以上、 または 版数 `FREQ_VERSIONS` 以上 ∧ 最新の版が `FREQ_MIN_KIB` 以上
  (= 大きくなる前の兆候。 後者が 1 entry 1 file 化の典型的な対象)
- 🟠 **repo の増え方**: 期間内の binary の版の合計が `REPO_TOTAL_MIB` 以上 (1 本ずつは閾値未満でも、 束で積んでいる)

各 finding に「暗号化 (git-crypt) か binary か」 と対策の分岐を書く:
暗号化された台帳 = 1 entry 1 file / 生成物 (PDF 等) = git に置かない・更新のたびに commit しない / 素材 = 変えない前提で置く。

## 使い方

    python3 check-history-growth.py --repo ~/src/repo            # 1 repo
    python3 check-history-growth.py --root ~/src                  # 直下の全 repo
    python3 check-history-growth.py --root ~/src --top 5 --json   # 機械向け
    python3 check-history-growth.py --staged                      # pre-commit: 何版目か・大きさを警告 (100 MiB 超だけ止める)
    python3 check-history-growth.py --selftest

finding が無い repo は何も出さない (= 健全なら沈黙)。 exit は finding があっても 0 (検出器。 `--strict` で 1)。
`--staged` は知らせるだけで commit を止めない (exit 0) — 例外は 1 つ、 **GitHub の上限 (1 file 100 MiB) を超える file** は
push が拒否され、 commit すると履歴から消すまで同期が止まるので、 `check-history-growth: BLOCK` の見出しつきで exit 1。
50 MiB 超は残りの余白つきで警告 (暗号化や作り直しで少し増えただけで上限を越える)。 検査が走らなければ ⚪ を 1 行出して exit 3
(= 故障を違反と同じ値にしない、 呼び元は 1 ∧ 見出しのときだけ止める)。

## 限界

- 数えるのは HEAD から辿れる commit だけ (他の branch・stash は見ない)。
- 版の大きさは blob の大きさ (圧縮前)。 binary は zlib でもほぼ縮まないので、 履歴の増え方の良い近似。
- 過去に積まれた分 (期間外) は見ない = 「今の増え方」 の検出器。 既に大きい repo の内訳は `--days` を伸ばして見る。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PATH_TOTAL_MIB = 50       # 期間内の 1 path の版の合計
FREQ_VERSIONS = 20        # 期間内の版数 …
FREQ_MIN_KIB = 256        # … ∧ 最新の版の大きさ
REPO_TOTAL_MIB = 150      # 期間内の repo 全体の binary の版の合計
SNIFF = 8000              # git の binary 判定と同じ窓
# GitHub の 1 file の制限 (公式 docs "About large files on GitHub": 50 MiB で警告・100 MiB を超えると push を拒否)
WARN_FILE_MIB = 50
HARD_FILE_MIB = 100
BLOCK_MARK = "check-history-growth: BLOCK"   # pre-commit はこの見出し ∧ exit 1 のときだけ止める

GIT_ENV_DROP = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY")


def _env() -> dict:
    """hook から呼ばれても別 repo の index を読まない (hook-authoring.md#hook-git-env-cross-repo)。"""
    return {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}


def git(repo, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=_env())
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {r.stderr.strip()[:200]}")
    return r.stdout


def versions_in_window(repo, days: int) -> dict[str, list[str]]:
    """path → 期間内に作られた版の blob id (新しい順)。 削除・submodule は除く。"""
    out = git(repo, "log", f"--since={days}.days", "--format=", "--raw", "--no-abbrev", "--no-renames", "HEAD")
    by_path: dict[str, list[str]] = {}
    for line in out.splitlines():
        if not line.startswith(":"):
            continue
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 5:
            continue
        new_mode, new_sha = parts[1], parts[3]
        if set(new_sha) == {"0"} or new_mode == "160000":
            continue
        by_path.setdefault(path, []).append(new_sha)
    return by_path


def blob_sizes(repo, shas) -> dict[str, int]:
    shas = list(dict.fromkeys(shas))
    if not shas:
        return {}
    r = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch-check=%(objectname) %(objectsize)"],
                       input="\n".join(shas) + "\n", capture_output=True, text=True, env=_env())
    sizes = {}
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) == 2 and p[1].isdigit():
            sizes[p[0]] = int(p[1])
    return sizes


def is_binary_blob(repo, sha: str) -> bool:
    """保存された blob の先頭に NUL があるか (git の判定と同じ。 filter を通さない = git-crypt の暗号文は binary)。"""
    p = subprocess.Popen(["git", "-C", str(repo), "cat-file", "blob", sha], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=_env())
    head = p.stdout.read(SNIFF) if p.stdout else b""
    p.kill()
    p.wait()
    return b"\0" in head


def crypt_paths(repo, paths) -> set[str]:
    if not paths:
        return set()
    r = subprocess.run(["git", "-C", str(repo), "check-attr", "--stdin", "-z", "filter"],
                       input="\0".join(paths) + "\0", capture_output=True, text=True, env=_env())
    f = r.stdout.split("\0")
    return {f[i] for i in range(0, len(f) - 2, 3) if f[i + 2] == "git-crypt"}


def scan(repo, days: int) -> dict:
    repo = Path(repo).expanduser()
    by_path = versions_in_window(repo, days)
    sizes = blob_sizes(repo, [s for v in by_path.values() for s in v])
    rows = []
    for path, shas in by_path.items():
        total = sum(sizes.get(s, 0) for s in shas)
        latest = sizes.get(shas[0], 0)
        if total < FREQ_MIN_KIB * 1024:  # 小さいものは binary 判定を省く
            continue
        if not is_binary_blob(repo, shas[0]):
            continue
        rows.append({"path": path, "versions": len(shas), "latest": latest, "total": total})
    crypt = crypt_paths(repo, [r["path"] for r in rows])
    for r in rows:
        r["crypt"] = r["path"] in crypt
        r["flag"] = (r["total"] >= PATH_TOTAL_MIB * 2**20
                     or (r["versions"] >= FREQ_VERSIONS and r["latest"] >= FREQ_MIN_KIB * 1024))
    rows.sort(key=lambda r: -r["total"])
    repo_total = sum(r["total"] for r in rows)
    return {"repo": repo.name, "path": str(repo), "days": days, "binary_total": repo_total,
            "repo_flag": repo_total >= REPO_TOTAL_MIB * 2**20, "rows": rows}


def _mib(n: int) -> str:
    return f"{n / 2**20:.0f} MiB" if n >= 2**20 else f"{n / 1024:.0f} KiB"


GENERATED_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".docx", ".xlsx", ".pptx", ".dvi", ".ps")
DOC = "conventions/repo-history-growth.md"


def remedy(row) -> str:
    """対策の分岐 (正本 = conventions/repo-history-growth.md)。 拡張子を先に見る (暗号化された PDF も生成物)。"""
    if Path(row["path"]).suffix.lower() in GENERATED_EXT:
        return f"生成物なら作り直すたびに commit しない = 追跡から外すか節目だけ ({DOC}#generated-binaries)"
    if row["crypt"]:
        return f"書き足す台帳なら 1 entry 1 file ({DOC}#encrypted-ledgers)"
    return f"置き方を見直す = 生成物 / 台帳 / 素材のどれか ({DOC}#three-kinds)"


def staged_warnings(repo, days: int) -> list[str]:
    """commit しようとしている差分の効かない file が、 直近 days 日で何版目かを数えて警告 (止めない)。

    ⚠️ ここだけは GIT_INDEX_FILE を**残す**: pre-commit の中で、 `git commit -- <path>` は一時 index に staged を置く。
    捨てると main の index を読み、 commit されない file を数え・commit される file を見落とす (別 repo を触る時の逆)。"""
    def run(*args) -> str:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""

    names = run("diff", "--cached", "--name-only", "--diff-filter=AM", "-z").split("\0")
    has_head = bool(run("rev-parse", "--verify", "-q", "HEAD").strip())
    out = []
    for path in filter(None, names):
        sha = run("rev-parse", f":{path}").strip()
        if not sha:
            continue
        size = blob_sizes(repo, [sha]).get(sha, 0)
        # 1 file の大きさ (text も含む): 上限を超えた commit は push できない = ここで止める (BLOCK_MARK)
        if size > HARD_FILE_MIB * 2**20:
            out.append(f"⛔ {BLOCK_MARK} {path} は {size / 2**20:.2f} MiB — GitHub は {HARD_FILE_MIB} MiB を超える file を push で拒否する"
                       f" (commit すると履歴から消すまで push できない)。 追跡しない・分ける・解像度を下げる ({DOC}#hosting-limits)")
            continue
        if size > WARN_FILE_MIB * 2**20:
            out.append(f"⚠️ check-history-growth: {path} は {size / 2**20:.2f} MiB — GitHub の推奨 ({WARN_FILE_MIB} MiB) 超。"
                       f" 上限 {HARD_FILE_MIB} MiB まで残り {_mib(HARD_FILE_MIB * 2**20 - size)} (作り直して少し増えると push できない、"
                       f" {DOC}#hosting-limits)")
        if size < FREQ_MIN_KIB * 1024 or not is_binary_blob(repo, sha):
            continue
        prior = run("log", f"--since={days}.days", "--format=%H", "HEAD", "--", path).split() if has_head else []
        n = len(prior) + 1
        if n < FREQ_VERSIONS and size * n < PATH_TOTAL_MIB * 2**20:
            continue
        row = {"path": path, "crypt": path in crypt_paths(repo, [path])}
        out.append(f"⚠️ check-history-growth: {path} はこの commit で直近 {days} 日の {n} 版目 (1 版 {_mib(size)}、 "
                   f"差分が効かず毎回まるごと履歴に積まれる) → {remedy(row)}")
    return out


def render(res: dict, top: int) -> list[str]:
    flagged = [r for r in res["rows"] if r["flag"]]
    if not flagged and not res["repo_flag"]:
        return []
    out = []
    if res["repo_flag"]:
        out.append(f"🟠 {res['repo']}: 直近 {res['days']} 日で差分の効かない版が計 {_mib(res['binary_total'])} 履歴に積まれた")
    for r in (flagged or res["rows"])[:top]:
        kind = "暗号化" if r["crypt"] else "binary"
        out.append(f"  🟠 {res['repo']}: {r['path']} — {res['days']} 日で {r['versions']} 版 × 最新 {_mib(r['latest'])}"
                   f" = 計 {_mib(r['total'])} ({kind}) → {remedy(r)}")
    return out


def repos_under(root: Path) -> list[Path]:
    return sorted(p for p in root.expanduser().iterdir() if (p / ".git").exists())


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    fails = []

    def check(label, ok):
        print(("  ok: " if ok else "  NG: ") + label)
        if not ok:
            fails.append(label)

    env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    os.environ.update(env)
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "r"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=_env())
        (repo / ".gitattributes").write_text("secret/** filter=fake-crypt\n")
        subprocess.run(["git", "-C", str(repo), "config", "filter.fake-crypt.clean", "cat"], check=True, env=_env())
        (repo / "secret").mkdir()
        rnd = os.urandom
        # 1. 頻繁に commit される binary の台帳 (暗号文の代わりに乱数 + NUL) = 版数 × 大きさで flag
        # 2. 同じ頻度の text = 差分が効くので数えない
        # 3. 1 回だけの大きな binary = 閾値未満
        big_text_line = "entry: " + "x" * 400 + "\n"
        for i in range(FREQ_VERSIONS + 1):
            (repo / "ledger.bin").write_bytes(b"\0HDR\0" + rnd(FREQ_MIN_KIB * 1024 + 10))
            (repo / "ledger.txt").write_text(big_text_line * (800 + i))
            if i == 0:
                (repo / "figure.pdf").write_bytes(b"%PDF\0" + rnd(300 * 1024))
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=_env())
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", f"c{i}"], check=True, env=_env())
        res = scan(repo, 30)
        rows = {r["path"]: r for r in res["rows"]}
        check("頻繁に commit される binary は flag (版数 × 大きさ)", rows.get("ledger.bin", {}).get("flag") is True)
        check("版数を正しく数える", rows.get("ledger.bin", {}).get("versions") == FREQ_VERSIONS + 1)
        check("text は差分が効くので数えない", "ledger.txt" not in rows)
        check("1 回だけの binary は flag しない", rows.get("figure.pdf", {}).get("flag") is False)
        lines = render(res, 5)
        check("finding に対策の分岐と正本が出る", any("ledger.bin" in l and "repo-history-growth.md" in l for l in lines))
        check("PDF は暗号化でも生成物の分岐", "生成物" in remedy({"path": "a/b.pdf", "crypt": True}))
        # --staged: 次の版を stage すると警告、 text と小さい binary は黙る
        (repo / "ledger.bin").write_bytes(b"\0HDR\0" + rnd(FREQ_MIN_KIB * 1024 + 10))
        (repo / "ledger.txt").write_text(big_text_line * 900)
        (repo / "small.bin").write_bytes(b"\0" + rnd(1024))
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=_env())
        warns = staged_warnings(repo, 30)
        check("commit 時: 頻繁な binary の次の版で警告 (版数つき)",
              len(warns) == 1 and "ledger.bin" in warns[0] and f"{FREQ_VERSIONS + 2} 版目" in warns[0])
        check("commit 時: text と小さい binary は警告しない", not any("ledger.txt" in w or "small.bin" in w for w in warns))
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "next"], check=True, env=_env())
        # `git commit -- <path>` の一時 index: main の index に無い staged を、 GIT_INDEX_FILE 経由で見る
        alt = Path(td) / "alt-index"
        alt_env = dict(_env(), GIT_INDEX_FILE=str(alt))
        subprocess.run(["git", "-C", str(repo), "read-tree", "HEAD"], check=True, env=alt_env)
        (repo / "ledger.bin").write_bytes(b"\0HDR\0" + rnd(FREQ_MIN_KIB * 1024 + 10))
        subprocess.run(["git", "-C", str(repo), "add", "ledger.bin"], check=True, env=alt_env)
        saved = os.environ.get("GIT_INDEX_FILE")
        os.environ["GIT_INDEX_FILE"] = str(alt)
        try:
            via_alt = staged_warnings(repo, 30)
        finally:
            if saved is None:
                os.environ.pop("GIT_INDEX_FILE", None)
            else:
                os.environ["GIT_INDEX_FILE"] = saved
        check("commit 時: 一時 index (GIT_INDEX_FILE) の staged を読む", any("ledger.bin" in w for w in via_alt))
        check("commit 時: main の index だけなら staged は無い", staged_warnings(repo, 30) == [])
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--", "ledger.bin"], check=True, env=_env())
        # HEAD の無い repo (最初の commit) でも落ちない
        fresh = Path(td) / "fresh"
        subprocess.run(["git", "init", "-q", "-b", "main", str(fresh)], check=True, env=_env())
        (fresh / "big.bin").write_bytes(b"\0" + rnd(FREQ_MIN_KIB * 1024 * 3))
        subprocess.run(["git", "-C", str(fresh), "add", "-A"], check=True, env=_env())
        check("commit 時: 最初の commit (HEAD 無し) でも落ちず、 1 版目は黙る", staged_warnings(fresh, 30) == [])
        # 1 file の大きさ: 上限超は BLOCK、 推奨超は余白つきの警告 (text でも数える)
        (fresh / "huge.bin").write_bytes(b"\0" + rnd(HARD_FILE_MIB * 2**20 + 10))
        (fresh / "large.txt").write_text("y" * (WARN_FILE_MIB * 2**20 + 10))
        subprocess.run(["git", "-C", str(fresh), "add", "-A"], check=True, env=_env())
        sw = staged_warnings(fresh, 30)
        check("commit 時: 上限 (100 MiB) を超える file は BLOCK の見出し",
              any(BLOCK_MARK in w and "huge.bin" in w for w in sw))
        check("commit 時: 推奨 (50 MiB) 超は警告だけ (text も)",
              any("large.txt" in w and "残り" in w and BLOCK_MARK not in w for w in sw))
        cwd = os.getcwd()
        os.chdir(fresh)
        try:
            rc = main(["--staged"])
        finally:
            os.chdir(cwd)
        check("commit 時: BLOCK があれば exit 1", rc == 1)
        # 期間: 90 日前の commit は 30 日の窓に入らず、 120 日の窓には入る
        old = Path(td) / "old"
        subprocess.run(["git", "init", "-q", "-b", "main", str(old)], check=True, env=_env())
        when = f"@{int(time.time()) - 90 * 86400} +0000"
        past = dict(_env(), GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        for i in range(FREQ_VERSIONS):
            (old / "ledger.bin").write_bytes(b"\0HDR\0" + rnd(FREQ_MIN_KIB * 1024 + 10))
            subprocess.run(["git", "-C", str(old), "add", "-A"], check=True, env=past)
            subprocess.run(["git", "-C", str(old), "commit", "-q", "-m", f"o{i}"], check=True, env=past)
        check("期間外の commit は数えない", scan(old, 30)["rows"] == [])
        check("窓を伸ばせば数える", any(r["flag"] for r in scan(old, 120)["rows"]))
        # 健全なら沈黙
        quiet = Path(td) / "q"
        subprocess.run(["git", "init", "-q", "-b", "main", str(quiet)], check=True, env=_env())
        (quiet / "a.txt").write_text("hello\n")
        subprocess.run(["git", "-C", str(quiet), "add", "-A"], check=True, env=_env())
        subprocess.run(["git", "-C", str(quiet), "commit", "-q", "-m", "a"], check=True, env=_env())
        check("健全な repo は何も出さない", render(scan(quiet, 30), 5) == [])
        # git-crypt の判定は attr で (filter 名)
        (repo / ".gitattributes").write_text("ledger.bin filter=git-crypt\n")
        check("filter=git-crypt の path を暗号化と判定", crypt_paths(repo, ["ledger.bin", "figure.pdf"]) == {"ledger.bin"})
    print(f"selftest: {'FAILED ' + str(len(fails)) if fails else 'ALL PASS'}")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--root")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--staged", action="store_true", help="pre-commit 用: cwd の repo の staged 差分だけ見て警告 (常に exit 0)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.staged:
        try:
            lines = staged_warnings(Path.cwd(), a.days)
        except Exception as e:  # 壊れても commit を止めない (故障 ≠ 違反 = exit 3)。 ただし黙らない
            print(f"⚪ check-history-growth --staged: 検査が走らなかった ({type(e).__name__}: {e})", file=sys.stderr)
            return 3
        for line in lines:
            print(line, file=sys.stderr)
        return 1 if any(BLOCK_MARK in l for l in lines) else 0
    targets = [Path(p).expanduser() for p in a.repo]
    if a.root:
        targets += repos_under(Path(a.root))
    if not targets:
        ap.error("--repo か --root を 1 つ以上")
    results, found = [], False
    for t in targets:
        try:
            res = scan(t, a.days)
        except RuntimeError as e:
            print(f"⚪ {t.name}: 読めない ({e})", file=sys.stderr)
            continue
        results.append(res)
        lines = render(res, a.top)
        found = found or bool(lines)
        if not a.json:
            for line in lines:
                print(line)
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    return 1 if (a.strict and found) else 0


if __name__ == "__main__":
    sys.exit(main())
