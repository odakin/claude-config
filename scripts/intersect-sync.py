#!/usr/bin/env python3
"""intersect-sync.py — 遅れているだけの clone で、 未 commit の変更が upstream の変更と同じ file に当たって最新化できない形を、 相手の変更を保ったまま解く道具 (--trial = 読むだけ・結果を machine-local の記録に / --apply = 手で / --report = 記録の集計、 --selftest)

使い方:
  intersect-sync.py --trial <repo> [<repo> ...] [--log] [--line] [--source NAME]
      読むだけ (repo の file・index・ref に触らない)。 既定の出力 = 1 repo 1 行の JSON (path は hash)。
      --line = sweep の A 行に添える日本語 1 行だけ / --log = machine-local の記録に足す (CLAUDE_INTERSECT_SYNC_LOG、
      既定 ~/.claude/state/intersect-sync-trial.jsonl) / --source = 記録に残す呼び元の名前 (sweep / heartbeat / manual)
  intersect-sync.py --apply <repo> [--min-age-min N]
      ①〜⑤ を同期の sweep と同じ lock の内側で行う。 判定が clean でなければ何もしない。 終了値 0 = 最新化した /
      3 = しなかった (理由を 1 行) / 2 = 使い方の誤り。 持ち主の居る未 commit (N 分以内に書かれた file) には触らない (既定 30)
  intersect-sync.py --report [--days N]   試走の記録を集計 (既定 7 日)
  intersect-sync.py --selftest
手順と考え方の正本 = conventions/multi-session-coordination.md#owner-gone-intersect-sync、 実装 = lib/intersect_sync.py。
⚠️ 同期 (scripts/repo-sync-sweep.sh / scripts/fleet-heartbeat.py) は trial だけを呼ぶ (= 試走)。 apply を同期に繋ぐかは
   試走の記録を見てから決める。 --apply を手で使うのは、 持ち主が居ない (閉じた session・無人の job の取り残し) と分かったときだけ。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import intersect_sync as isync  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--trial", nargs="+", metavar="REPO")
    g.add_argument("--apply", metavar="REPO")
    g.add_argument("--report", action="store_true")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--log", action="store_true")
    ap.add_argument("--line", action="store_true")
    ap.add_argument("--source", default="manual")
    ap.add_argument("--min-age-min", type=int, default=isync.MIN_AGE_MIN)
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.report:
        print(isync.report(a.days))
        return 0
    if a.apply:
        res = isync.apply(a.apply, min_age_min=a.min_age_min)
        isync.record(res, mode="apply", source=a.source)
        print(("✓ " if res.get("applied") else "✗ ") + f"{res.get('repo', a.apply)}: {res.get('reason', '')}")
        return 0 if res.get("applied") else 3
    for repo in a.trial:
        try:
            res = isync.trial(repo)
        except Exception as exc:  # 試走は呼び元 (sweep・heartbeat) を止めない
            res = {"repo": Path(repo).name, "verdict": "error", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        if a.log:
            isync.record(res, mode="trial", source=a.source)
        if a.line:
            line = isync.one_line(res)
            if line:
                print(line)
        else:
            print(json.dumps(isync.public(res), ensure_ascii=False, sort_keys=True))
    return 0


# ---------------- selftest ----------------

def selftest() -> int:
    ok = fail = 0

    def check(cond, label):
        nonlocal ok, fail
        print(("  PASS: " if cond else "  FAIL: ") + label)
        ok, fail = ok + bool(cond), fail + (not cond)

    td = Path(tempfile.mkdtemp(prefix="intersect-sync-test-"))
    saved = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                                            "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "CLAUDE_INTERSECT_SYNC_LOG", "HOME")}
    try:
        (td / "home").mkdir()
        os.environ.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
                          GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
                          GIT_COMMITTER_EMAIL="t@example.invalid", CLAUDE_INTERSECT_SYNC_LOG=str(td / "trial.jsonl"),
                          HOME=str(td / "home"))

        def g(repo, *args, ok_rc=(0,)):
            p = subprocess.run(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "-c", "init.defaultBranch=main",
                                *args], capture_output=True, text=True)
            if p.returncode not in ok_rc:
                raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
            return p.stdout

        base_ledger = "".join(f"- id: e{i}\n  status: open\n" for i in range(1, 11))

        # S0 欠けの照合 (②): 両側が足した行が合わせた版から消えたら数える / 同じ行を両側が足しただけなら欠けではない
        bb, tt, uu = b"a\nb\n", b"a\nb\nX\n", b"Y\na\nb\n"
        check(isync.lost_lines(bb, tt, uu, b"Y\na\nb\nX\n") == 0, "S0 両側の足した行が残る = 欠け 0")
        check(isync.lost_lines(bb, tt, uu, b"Y\na\nb\n") == 1 and isync.lost_lines(bb, tt, uu, b"a\nb\nX\n") == 1,
              "S0 手元の行・upstream の行のどちらが消えても欠け 1")
        check(isync.lost_lines(bb, tt, tt, tt) == 0, "S0 同じ行を両側が足した (1 つに合わさる) = 欠けではない")

        def world(name, setup_extra=None):
            """remote (bare) + clone a (遅れる側) + clone b (push する側)。"""
            w = td / name
            w.mkdir()
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(w / "remote.git")], check=True)
            for c in ("a", "b"):
                pass
            g(w, "clone", "-q", str(w / "remote.git"), "a")
            a = w / "a"
            (a / "ledger.yaml").write_text(base_ledger)
            (a / "notes.md").write_text("# notes\nline 1\n")
            (a / "bin.dat").write_bytes(b"\x00\x01\x02 data\n")
            (a / "gone.txt").write_text("to be removed\n")
            if setup_extra:
                setup_extra(a)
            g(a, "add", "-A")
            g(a, "commit", "-q", "-m", "init")
            g(a, "push", "-q", "origin", "HEAD:main")
            g(w, "clone", "-q", str(w / "remote.git"), "b")
            return w, a, w / "b"

        def push_b(b, mutate, msg="upstream change"):
            mutate(b)
            g(b, "add", "-A")
            g(b, "commit", "-q", "-m", msg)
            g(b, "push", "-q", "origin", "HEAD:main")

        def age(p, minutes):
            t = time.time() - minutes * 60
            os.utime(p, (t, t))

        def edit(p, old, new):
            s = p.read_text()
            assert old in s, old
            p.write_text(s.replace(old, new, 1))

        # S1 同じ変更が両側に在る (live copy・二重の記録) → clean・subsumed、 apply で手元は upstream と同じになる
        w, a, b = world("s1")
        (a / "ledger.yaml").write_text(base_ledger + "- id: e11\n  status: open\n")
        push_b(b, lambda r: (r / "ledger.yaml").write_text(base_ledger + "- id: e11\n  status: open\n"))
        g(a, "fetch", "-q")
        r = isync.trial(a)
        check(r["verdict"] == "clean" and r["files"] and r["files"][0].get("subsumed") is True,
              f"S1 同じ変更が両側 = clean・upstream が全部含む (got {r['verdict']})")
        age(a / "ledger.yaml", 60)
        x = isync.apply(a, min_age_min=30)
        st = g(a, "status", "--porcelain")
        check(x.get("applied") and g(a, "rev-parse", "HEAD") == g(a, "rev-parse", "@{u}") and "ledger.yaml" not in st,
              f"S1 apply: HEAD = upstream、 ledger は差分なし ({x.get('reason')})")

        # S2 別の行を変えた → clean、 apply で両方の変更が残り、 diff は手元の変更だけ
        w, a, b = world("s2")
        edit(a / "ledger.yaml", "- id: e2\n  status: open", "- id: e2\n  status: done")
        push_b(b, lambda r: edit(r / "ledger.yaml", "- id: e9\n  status: open", "- id: e9\n  status: waiting"))
        g(a, "fetch", "-q")
        r = isync.trial(a)
        check(r["verdict"] == "clean" and r["files"][0].get("lost") == 0 and r["files"][0].get("subsumed") is False,
              f"S2 別の行 = clean・欠けなし (got {r['verdict']})")
        idx = a / ".git" / "index"
        before = (idx.stat().st_mtime_ns, idx.read_bytes())
        r2 = isync.trial(a)
        after = (idx.stat().st_mtime_ns, idx.read_bytes())  # (下の git status は optional lock を取って index を書きうる = 先に比べる)
        check(after == before and g(a, "status", "--porcelain").strip() == "M ledger.yaml" and r2["state"] == r["state"],
              "S2 trial は repo に触らない (index の中身と時刻が同じ・status 同じ・2 回目も同じ状態の鍵)")
        age(a / "ledger.yaml", 60)
        x = isync.apply(a)
        txt = (a / "ledger.yaml").read_text()
        d = g(a, "diff", "--", "ledger.yaml")
        check(x.get("applied") and "e2\n  status: done" in txt and "e9\n  status: waiting" in txt
              and "+  status: done" in d and "waiting" not in d.replace("e9\n  status: waiting", ""),
              f"S2 apply: 両方の変更が残り、 diff は手元の変更だけ ({x.get('reason')})")

        # S3 同じ行を別々に変えた → conflict、 apply は何もしない
        w, a, b = world("s3")
        edit(a / "ledger.yaml", "- id: e5\n  status: open", "- id: e5\n  status: done")
        push_b(b, lambda r: edit(r / "ledger.yaml", "- id: e5\n  status: open", "- id: e5\n  status: dropped"))
        g(a, "fetch", "-q")
        head0, file0 = g(a, "rev-parse", "HEAD"), (a / "ledger.yaml").read_text()
        r = isync.trial(a)
        age(a / "ledger.yaml", 60)
        x = isync.apply(a)
        check(r["verdict"] == "conflict" and not x.get("applied") and g(a, "rev-parse", "HEAD") == head0
              and (a / "ledger.yaml").read_text() == file0, "S3 衝突 = conflict、 apply は HEAD も file も変えない")
        check("人が解く" in isync.one_line(r), "S3 sweep に添える 1 行 = 道具では解けない")

        # S4 stage 済み → staged
        w, a, b = world("s4")
        edit(a / "notes.md", "line 1", "line 1 (local)")
        g(a, "add", "notes.md")
        push_b(b, lambda r: (r / "notes.md").write_text("# notes\nline 1\nline 2\n"))
        g(a, "fetch", "-q")
        check(isync.trial(a)["verdict"] == "staged", "S4 交差した file が stage 済み = staged (戻すと相手の stage を消す)")

        # S5 binary / S6 削除
        w, a, b = world("s5")
        (a / "bin.dat").write_bytes(b"\x00\x01\x03 local\n")
        push_b(b, lambda r: (r / "bin.dat").write_bytes(b"\x00\x09 upstream\n"))
        g(a, "fetch", "-q")
        check(isync.trial(a)["verdict"] == "binary", "S5 binary = 扱わない")
        w, a, b = world("s6")
        (a / "gone.txt").write_text("to be removed\nlocal note\n")
        push_b(b, lambda r: (r / "gone.txt").unlink())
        g(a, "fetch", "-q")
        check(isync.trial(a)["verdict"] == "deleted", "S6 upstream が消した file = deleted")

        # S7 最近書かれた file には apply が触らない (持ち主が作業中かもしれない)
        w, a, b = world("s7")
        edit(a / "ledger.yaml", "- id: e2\n  status: open", "- id: e2\n  status: done")
        push_b(b, lambda r: edit(r / "ledger.yaml", "- id: e9\n  status: open", "- id: e9\n  status: waiting"))
        g(a, "fetch", "-q")
        head0 = g(a, "rev-parse", "HEAD")
        x = isync.apply(a, min_age_min=30)
        check(not x.get("applied") and "作業中" in x.get("reason", "") and g(a, "rev-parse", "HEAD") == head0,
              f"S7 30 分以内に書かれた file = apply しない ({x.get('reason')})")

        # S8 手元にだけ在る commit = ahead (通常の分岐は別の手順)
        w, a, b = world("s8")
        (a / "notes.md").write_text("# notes\nline 1\nlocal commit\n")
        g(a, "commit", "-q", "-am", "local")
        edit(a / "ledger.yaml", "- id: e2\n  status: open", "- id: e2\n  status: done")
        push_b(b, lambda r: edit(r / "ledger.yaml", "- id: e9\n  status: open", "- id: e9\n  status: waiting"))
        g(a, "fetch", "-q")
        check(isync.trial(a)["verdict"] == "ahead", "S8 手元にだけ在る commit = ahead")

        # S9 ff が通らない (upstream が足した file と同じ名の未追跡 file) → 控えから戻す
        w, a, b = world("s9")
        edit(a / "ledger.yaml", "- id: e2\n  status: open", "- id: e2\n  status: done")
        (a / "new.txt").write_text("untracked local\n")

        def m9(r):
            edit(r / "ledger.yaml", "- id: e9\n  status: open", "- id: e9\n  status: waiting")
            (r / "new.txt").write_text("tracked upstream\n")
        push_b(b, m9)
        g(a, "fetch", "-q")
        age(a / "ledger.yaml", 60)
        head0, file0 = g(a, "rev-parse", "HEAD"), (a / "ledger.yaml").read_text()
        x = isync.apply(a)
        check(not x.get("applied") and "控えから" in x.get("reason", "") and g(a, "rev-parse", "HEAD") == head0
              and (a / "ledger.yaml").read_text() == file0, f"S9 ff が通らない = 控えから戻す ({x.get('reason')})")

        # S10 lock を別の生きている process が持っている → apply しない
        w, a, b = world("s10")
        edit(a / "ledger.yaml", "- id: e2\n  status: open", "- id: e2\n  status: done")
        push_b(b, lambda r: edit(r / "ledger.yaml", "- id: e9\n  status: open", "- id: e9\n  status: waiting"))
        g(a, "fetch", "-q")
        age(a / "ledger.yaml", 60)
        lk = Path(g(a, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()) / isync.LOCK_NAME
        lk.mkdir()
        (lk / "owner").write_text(f"{os.getppid()} {int(time.time())} test\n")
        x = isync.apply(a)
        check(not x.get("applied") and "処理中" in x.get("reason", ""), "S10 sweep の lock が生きている = apply しない")
        (lk / "owner").write_text(f"999999 {int(time.time()) - 10} test\n")
        x = isync.apply(a)
        check(x.get("applied") and not lk.exists(), f"S10 持ち主の死んだ古い lock は除いて進む ({x.get('reason')})")

        # S11 記録と集計: path も中身も書かない
        w, a, b = world("s11")
        edit(a / "ledger.yaml", "- id: e2\n  status: open", "- id: e2\n  status: SECRET-VALUE")
        push_b(b, lambda r: edit(r / "ledger.yaml", "- id: e9\n  status: open", "- id: e9\n  status: waiting"))
        g(a, "fetch", "-q")
        rc = main(["--trial", str(a), "--log", "--source", "selftest", "--line"])
        logtxt = Path(os.environ["CLAUDE_INTERSECT_SYNC_LOG"]).read_text()
        check(rc == 0 and '"verdict": "clean"' in logtxt and "ledger" not in logtxt and "SECRET-VALUE" not in logtxt,
              "S11 記録に path と中身を書かない (hash と数だけ)")
        rep = isync.report(7)
        check("詰まり" in rep and "clean" in rep and "s11" not in rep.split("\n")[0], "S11 集計が出る")

        # S12 git-crypt の file (鍵のある clone) = 平文で 3-way し、 index には暗号文のまま入る
        if shutil.which("git-crypt"):
            w = td / "s12"
            w.mkdir()
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(w / "remote.git")], check=True)
            g(w, "clone", "-q", str(w / "remote.git"), "a")
            a = w / "a"
            subprocess.run(["git-crypt", "init"], cwd=a, capture_output=True, check=True)
            (a / ".gitattributes").write_text("secret.yaml filter=git-crypt diff=git-crypt\n")
            (a / "secret.yaml").write_text(base_ledger)
            g(a, "add", "-A")
            g(a, "commit", "-q", "-m", "init")
            g(a, "push", "-q", "origin", "HEAD:main")
            key = w / "key"
            subprocess.run(["git-crypt", "export-key", str(key)], cwd=a, capture_output=True, check=True)
            g(w, "clone", "-q", str(w / "remote.git"), "b")
            b = w / "b"
            subprocess.run(["git-crypt", "unlock", str(key)], cwd=b, capture_output=True, check=True)
            edit(a / "secret.yaml", "- id: e2\n  status: open", "- id: e2\n  status: done")
            push_b(b, lambda r: edit(r / "secret.yaml", "- id: e9\n  status: open", "- id: e9\n  status: waiting"))
            g(a, "fetch", "-q")
            r = isync.trial(a)
            check(r["verdict"] == "clean" and r["files"][0].get("enc") is True, f"S12 git-crypt の file も平文で clean (got {r['verdict']})")
            age(a / "secret.yaml", 60)
            x = isync.apply(a)
            raw = subprocess.run(["git", "-C", str(a), "show", "HEAD:secret.yaml"], capture_output=True).stdout
            txt = (a / "secret.yaml").read_text()
            check(x.get("applied") and raw.startswith(b"\x00GITCRYPT") and "e2\n  status: done" in txt
                  and "e9\n  status: waiting" in txt, f"S12 apply: 作業 tree は平文で両方の変更、 HEAD は暗号文 ({x.get('reason')})")
        else:
            print("  SKIP: S12 (git-crypt が無い)")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(td, ignore_errors=True)
    print(f"\n==== RESULT: PASS={ok} FAIL={fail} ====")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
