#!/usr/bin/env python3
"""git-rewrite-follow.py — 書き換えられた (force-push された) 履歴に手元の clone を中身で揃える / 古い世代の commit・blob の push を止める / 揃える機構が各マシンに届いたかを状態で答える (engine = scripts/lib/git_rewrite_follow.py、 追従の判定は書き換えられない層 = 本 repo に置く)

書き換えた repo の追従を、 書き換えられる repo の中の script に頼らないための入口 (実測 2026-09-29: 追従 script が
書き換えられる側の repo に在り、 その repo 自身を書き換えると古い履歴の Mac は script を pull できない。 毎時の
無人 job は `pull --rebase` で古い commit を積み直しうる)。 判定・不変条件・manifest の形 = lib の docstring。

usage:
  git-rewrite-follow.py follow --repo PATH [--no-fetch] [--map GLOB]... [--max N] [--dry-run] [--tsv]
      diverged な clone を、 対応表 / tree の一致 で新しい履歴に揃える (reset --keep)。 1 行で結果。
      exit 0 = 揃えた / 揃っている / 触らない (upstream 無し等)、 1 = 止まった (手元にしか無い中身、 dirty の重なり、 通信、
      書き換えの痕跡の無い通常の分岐 = 追従の対象外)。
      --tsv = repo-sync-sweep.sh 向け (F<TAB>行 = 揃えた / S<TAB>行 = 止まった / D<TAB>行 = 書き換えの痕跡の無い通常の分岐
      〔揃えない。 手元にだけ在る commit の数と古さ・解き方の節〕 / 無音 = 何もしない)
  git-rewrite-follow.py sweep --root DIR [--fetch] [--map GLOB]... [--max N] [--dry-run] [--no-prepush] [--stub-all]
      DIR/*/ の repo を順に follow (既定は fetch しない = 直前の sync が fetch した ref を読む) + manifest のある repo に
      pre-push stub を置く (--stub-all = manifest の無い repo にも) + manifest か clone の記録のある repo の remote 側を読む (audit、 戻って
      いれば止まった行)。 exit 0 (何かで止まった repo があれば 1)。
  git-rewrite-follow.py guard --repo PATH --hook [remote url]      (git pre-push の stdin を読む。 stub が呼ぶ)
  git-rewrite-follow.py guard --repo PATH --range LOCAL..REMOTE     (手で確かめる)
      push 範囲に、 対応表の旧 sha / forbidden-blobs の object / この clone の reflog が覚えている「remote から捨てられた
      履歴」 の object が在れば exit 1 + 理由 (見出し「push を止めた」)。 remote の今の先頭が手元の知識と違えば、 判定の
      前に fetch する (--no-fetch で止める)。 exit 3 = 検査が走らなかった (stub は 1 行出して通す)。
      書き換えに依らない 2 つも同じ入口で見る: git-crypt の対象の path の平文の blob (止める = CLAUDE_CRYPT_PUSH_GUARD=0) /
      commit message の識別子の検査 (commit-msg と同じ engine を push 範囲に。 止める = その engine の escape hatch)。
      中身を持たない object (空の blob など) は検査しない。 止まった object が、 消した中身でなく同じ中身の新しい file だった時は、
      持ち主の判断を受けてから GIT_REWRITE_FOLLOW_ALLOW=<止まった sha> を付けて push する (名指しした object だけが通り、 記録に残る)。
      remote の既定 branch を fast-forward でなく動かす push (履歴の書き換え) の前には、 複製の側の備えを点呼する command
      (env GIT_REWRITE_READY_HOOK か ~/.claude/rewrite-ready-check、 引数 = repo の path) を呼ぶ: exit 1 + 「NOT READY」 =
      止める / それ以外の非 0 = 1 行出して通す / command が無ければ何もしない。 持ち主の判断で進める = GIT_REWRITE_READY_OVERRIDE=1。
  git-rewrite-follow.py guard-head --repo PATH
      HEAD が、 書き換えで捨てられた履歴の commit の上にあれば exit 1 + 見出し「[rewrite-follow] BLOCK」 (pre-commit の段が
      呼ぶ = 追従前の clone で commit を始めさせない)。 fetch はしない。 exit 3 = 検査が走らなかった。
  git-rewrite-follow.py audit (--repo PATH | --root DIR) [--fetch] [--no-cache]
      manifest のある repo の remote 側を読む: upstream に対応表の旧 sha / forbidden の object が戻っていれば 🔴、 remote の
      他の branch が旧履歴を抱えていれば 🟠。 finding があれば exit 1 (3 = 走らなかった repo がある)。 hook を持たない clone
      からの push・host 上の merge で戻った分は、 ここでしか分からない。
  git-rewrite-follow.py forbidden --repo PATH [--write]
      対応表の旧 sha のうち手元に在る commit から届き、 upstream からは届かない tree / blob の sha を出す (書き換えた clone で
      回す)。 --write = worktree の `.rewrite-follow/forbidden-blobs` に書く (commit は呼び手)。 stderr に被覆 (手元に在った
      旧 commit の数)。
  git-rewrite-follow.py facts --root DIR
      DIR/*/ の repo ごとの事実 (HEAD・見ている upstream・pre-push の状態) を JSON で (点呼の材料。 判定は読む側)。
  git-rewrite-follow.py ensure-prepush (--repo PATH | --root DIR) [--force]
      manifest (`<upstream>:.rewrite-follow/`) のある repo に pre-push stub を置く。
      --force = manifest の無い repo にも置く (書き換えの前から全 clone に置く)。
      別の pre-push hook が在る clone では、 その hook を残したまま検査を先に通す (pdf-publish の hook はその鎖の口に、
      他は元の hook を pre-push.rewrite-follow-chained に写して検査の後に呼ぶ)。 包まない = GIT_REWRITE_FOLLOW_CHAIN=0 か
      その clone で git config rewritefollow.chain false。 戻す = mv pre-push.rewrite-follow-chained pre-push
  git-rewrite-follow.py status --repo PATH [--json]
      upstream / manifest の有無 / stub の有無 / forced-update の痕跡 / HEAD と upstream の関係 / HEAD が捨てられた履歴の
      上か。 heartbeat と gate が読む。
  git-rewrite-follow.py map --repo PATH [--map GLOB]... SHA...
      書き換え前の sha (7 文字以上の短縮可) を、 upstream の `.rewrite-follow/commit-map*` を最後まで辿って今の sha に引く
      (記録 〔掲示板・受信の記録・TODO〕 に残る旧 sha を読むため)。 1 行ずつ「入力 → 今の sha  状態  説明」。
      状態 = mapped / current (書き換えで変わっていない) / ambiguous / dropped / unknown。 exit 1 = unknown か ambiguous が在る。
  git-rewrite-follow.py --selftest

対応表の外部供給: --map GLOB (repeatable) / ~/.claude/rewrite-follow-maps.txt (1 行 1 glob、 env GIT_REWRITE_FOLLOW_MAPS_FILE で
場所を変える) / env GIT_REWRITE_FOLLOW_MAPS (`:` 区切り glob)。 `<map>.forbidden-blobs` が隣に在れば guard が読む。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import git_rewrite_follow as RF  # noqa: E402


def _print_result(r, tsv):
    if r.state == "followed":
        if tsv:
            print("F\t" + r.line)
            for x in r.extra:
                print("F\t" + x.strip())
        else:
            print(r.line)
            for x in r.extra:
                print(x)
    elif r.state == "stopped":
        if tsv:
            print("S\t" + r.line)
        else:
            print(r.line, file=sys.stderr)
    elif r.state == "diverged":   # 通常の分岐 = sweep には D 行 (数・古さ・解き方の節を持つ 1 行。 旧い sweep は読まずに従来の A 行を出す)
        if tsv:
            print("D\t" + r.line)
        else:
            print(r.line, file=sys.stderr)


def cmd_follow(a):
    try:
        r = RF.follow_repo(a.repo, a.map, fetch=not a.no_fetch, max_count=a.max, dry_run=a.dry_run)
    except Exception as exc:  # 判定の失敗は 1 行で止まる (呼び元は次回再試行)
        r = RF.Result("stopped", f"{Path(a.repo).name}: 追従の判定で失敗 ({type(exc).__name__}: {str(exc)[:160]})", exit_code=1)
    _print_result(r, a.tsv)
    return r.exit_code


def cmd_sweep(a):
    rc = 0
    for r, pl in RF.sweep(a.root, a.map, fetch=a.fetch, max_count=a.max, dry_run=a.dry_run, prepush=not a.no_prepush,
                          stub_all=(True if a.stub_all else None)):
        _print_result(r, a.tsv)
        if pl:
            print(("P\t" if a.tsv else "") + pl)
        rc = max(rc, r.exit_code)
    return rc


def cmd_guard(a):
    if a.range:
        local, _, remote = a.range.partition("..")
        lines = [f"refs/heads/x {RF.rev(a.repo, local)} refs/heads/x {RF.rev(a.repo, remote) if remote else RF.ZERO}"]
    else:
        lines = sys.stdin.read().splitlines()
    remote = a.rest[0] if (a.hook and a.rest) else None
    try:
        ok, msgs = RF.guard_stdin(a.repo, lines, a.map, remote=remote, fetch=not a.no_fetch)
    except Exception as exc:  # 検査の失敗は違反と同じ値で返さない (3 = 走らなかった。 stub は 1 行出して通す)
        print(f"rewrite-follow guard: 検査できなかった ({type(exc).__name__}: {str(exc)[:120]})", file=sys.stderr)
        try:
            RF.log_event("guard-error", a.repo, type(exc).__name__)   # 止めずに通す出来事を、 他の machine から読める記録に残す
        except Exception:
            pass
        return 3
    for m in msgs:
        print(m, file=sys.stderr)
    return 0 if ok else 1


def cmd_guard_head(a):
    try:
        ok, msg = RF.head_violations(a.repo, a.map)
    except Exception as exc:
        print(f"rewrite-follow guard-head: 検査できなかった ({type(exc).__name__}: {str(exc)[:120]})", file=sys.stderr)
        return 3
    if not ok:
        print(msg, file=sys.stderr)
    return 0 if ok else 1


def cmd_audit(a):
    repos = [a.repo] if a.repo else sorted(str(Path(g).parent) for g in Path(a.root).glob("*/.git"))
    rc = 0
    for r in repos:
        try:
            if a.fetch:
                up = RF.upstream_of(r)
                if up:
                    RF.git(r, "fetch", "-q", up.split("/", 1)[0], check=False, timeout=RF.FETCH_TIMEOUT)
            for line in RF.audit_repo(r, a.map, use_cache=not a.no_cache):
                print(line)
                rc = rc or 1
        except Exception as exc:
            print(f"⚠️ {Path(r).name}: remote 側の検査が走らなかった ({type(exc).__name__}: {str(exc)[:120]})")
            rc = 3
    return rc


def cmd_forbidden(a):
    objs, have, total = RF.forbidden_from_local(a.repo, a.map)
    print(f"{Path(a.repo).name}: 旧世代にしか無い tree / blob {len(objs)} 個 (対応表の旧 commit {total} 個のうち手元に在る {have} 個から)",
          file=sys.stderr)
    if have < total:
        print(f"  ⚠️ 旧 commit {total - have} 個が手元に無い = その分の object は拾えていない"
              " (書き換えた clone か、 書き換え前の bundle を fetch した clone で回す)", file=sys.stderr)
    if a.write:
        d = Path(a.repo) / RF.MANIFEST_DIR
        d.mkdir(parents=True, exist_ok=True)
        (d / "forbidden-blobs").write_text("".join(o + "\n" for o in objs), encoding="utf-8")
        print(f"  wrote {d / 'forbidden-blobs'} (commit は呼び手)", file=sys.stderr)
    else:
        for o in objs:
            print(o)
    return 0 if (objs or total == 0) else 1


def cmd_facts(a):
    print(json.dumps(RF.repo_facts(a.root), ensure_ascii=False, indent=1, sort_keys=True))
    return 0


def cmd_ensure_prepush(a):
    repos = [a.repo] if a.repo else sorted(str(Path(g).parent) for g in Path(a.root).glob("*/.git"))
    for r in repos:
        try:
            line = RF.ensure_prepush(r, only_with_manifest=not a.force)
        except Exception as exc:
            line = f"{Path(r).name}: pre-push stub を置けなかった ({type(exc).__name__}: {str(exc)[:120]})"
        if line:
            print(line)
    return 0


def cmd_status(a):
    st = RF.status(a.repo, a.map)
    if a.json:
        print(json.dumps(st, ensure_ascii=False, indent=1))
    else:
        for k, v in st.items():
            print(f"{k}: {v}")
    return 0


def cmd_map(a):
    rows = RF.lookup(a.repo, a.sha, cli_globs=a.map)
    for raw, state, new, note in rows:
        print(f"{raw[:12]:<12} → {(new[:12] or '-'):<12}  {state:<9}  {note}")
    return 1 if any(r[1] in ("unknown", "ambiguous") for r in rows) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--map", action="append", default=[], metavar="GLOB", help="対応表 (old new) の glob、 repeatable")

    p = sub.add_parser("follow")
    p.add_argument("--repo", required=True)
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--max", type=int, default=RF.DEFAULT_MAX)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tsv", action="store_true")
    common(p)
    p = sub.add_parser("sweep")
    p.add_argument("--root", default=os.path.join(os.path.expanduser("~"), "Claude"))
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--max", type=int, default=RF.DEFAULT_MAX)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-prepush", action="store_true")
    p.add_argument("--stub-all", action="store_true", help="manifest の無い repo にも pre-push stub を置く")
    p.add_argument("--tsv", action="store_true")
    common(p)
    p = sub.add_parser("guard")
    p.add_argument("--repo", required=True)
    p.add_argument("--hook", action="store_true", help="git pre-push として stdin を読む")
    p.add_argument("--range", help="LOCAL..REMOTE (手で確かめる)")
    p.add_argument("--no-fetch", action="store_true", help="remote の先頭が手元の知識と違っても fetch しない")
    p.add_argument("rest", nargs="*", help="(pre-push が渡す remote 名と URL。 remote 名を fetch 先に使う)")
    common(p)
    p = sub.add_parser("guard-head")
    p.add_argument("--repo", required=True)
    common(p)
    p = sub.add_parser("audit")
    p.add_argument("--repo")
    p.add_argument("--root")
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    common(p)
    p = sub.add_parser("forbidden")
    p.add_argument("--repo", required=True)
    p.add_argument("--write", action="store_true", help="worktree の .rewrite-follow/forbidden-blobs に書く")
    common(p)
    p = sub.add_parser("facts")
    p.add_argument("--root", default=os.path.join(os.path.expanduser("~"), "Claude"))
    p = sub.add_parser("ensure-prepush")
    p.add_argument("--repo")
    p.add_argument("--root")
    p.add_argument("--force", action="store_true", help="manifest が無くても置く")
    p = sub.add_parser("status")
    p.add_argument("--repo", required=True)
    p.add_argument("--json", action="store_true")
    common(p)
    p = sub.add_parser("map")
    p.add_argument("--repo", required=True)
    p.add_argument("sha", nargs="+", help="書き換え前の sha (7 文字以上の短縮可)")
    common(p)
    a = ap.parse_args(argv)
    if a.selftest:
        return RF._selftest()
    if a.cmd == "follow":
        return cmd_follow(a)
    if a.cmd == "sweep":
        return cmd_sweep(a)
    if a.cmd == "guard":
        return cmd_guard(a)
    if a.cmd == "guard-head":
        return cmd_guard_head(a)
    if a.cmd == "audit":
        if not (a.repo or a.root):
            ap.error("audit needs --repo or --root")
        return cmd_audit(a)
    if a.cmd == "forbidden":
        return cmd_forbidden(a)
    if a.cmd == "facts":
        return cmd_facts(a)
    if a.cmd == "ensure-prepush":
        if not (a.repo or a.root):
            ap.error("ensure-prepush needs --repo or --root")
        return cmd_ensure_prepush(a)
    if a.cmd == "status":
        return cmd_status(a)
    if a.cmd == "map":
        return cmd_map(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
