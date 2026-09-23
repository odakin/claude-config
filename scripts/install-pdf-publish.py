#!/usr/bin/env python3
"""install-pdf-publish.py — 共同編集の repo に「PDF は git に入れず、 push のたびに共有フォルダ (Dropbox) へ写す」 仕組みを配る。

## なぜ

build した PDF を commit すると、 差分が効かず版ごとにまるごと履歴に積まれる (conventions/repo-history-growth.md)。
やめるだけだと、 共同編集者どうしが相手の最新の PDF を見る手段が消える。 そこで repo に hook を仕込み、
**各自の git push で発火**して、 push された文書の PDF を (古ければ組み直して) 共有フォルダへ写す。
発火は各自の手元の push なので、 無人の定期実行 (launchd は同期フォルダに書けない) も新しい API 権限も要らない。

## 何を置くか (repo の中に。 共同編集者は claude-config を持たないので repo 単体で動く写しを置く)

- `tools/pdf-publish/pdf-publish.sh` / `install-hook.sh` = 正本 templates/shared-project/pdf-publish/ の写し
- `.pdf-publish.conf` = 共有フォルダの名前 (DEST) と文書 (DOC) と組むコマンド (BUILD)
- `.gitignore` = 生成 PDF の pattern と `.pdf-publish.local` (機械ごとの上書き)
- この clone の pre-push hook (install-hook.sh を走らせる。 他の clone は各自 1 回 = repo の CLAUDE.md に書く)

## 使い方

    install-pdf-publish.py install <repo> --dest <共有フォルダ名> --doc 'report/*.tex' --build './build.sh {stem}' [--doc ... --build ...] [--untrack] [--dry-run]
    install-pdf-publish.py check <repo>        # 写しが正本と同じか・hook が置かれているか
    install-pdf-publish.py --selftest          # 合成の repo と bare remote で、 push で発火して写ることまで確かめる

`--untrack` = 追跡中の生成 PDF (同じ dir に \\documentclass を持つ同名の .tex がある PDF) を `git rm --cached` する
(file は手元に残る。 ⚠️ 他の clone では pull すると手元の PDF が消える = 次の build で戻る。 図の PDF は触らない)。
commit と push はしない (共同編集者の了解を取ってから人が行う)。 CLAUDE.md に足す文面は最後に出す (保護 file なので書かない)。

## 限界

- 共有フォルダの作成と共有 (招待) は Dropbox 側の操作 (この道具はしない)。 無い機械では hook は黙って skip し、 記録に 1 行残す
- 文書の path に空白があると扱えない (pdf-publish.sh の限界)
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "shared-project" / "pdf-publish"
VENDORED = ("pdf-publish.sh", "install-hook.sh")
TOOLS = Path("tools") / "pdf-publish"


def git(repo, *args, check=True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r.stdout


def ignore_patterns(docs) -> list[str]:
    """DOC の glob → 生成 PDF の .gitignore pattern (repo root 起点)。"""
    out = []
    for d in docs:
        p = d[:-4] + ".pdf" if d.endswith(".tex") else d
        out.append("/" + p.lstrip("/"))
    return out


def built_tracked_pdfs(repo: Path, docs) -> list[str]:
    """追跡中の PDF のうち、 DOC に当たり \\documentclass を持つ同名の .tex があるもの (図の PDF は含めない)。"""
    out = []
    for d in docs:
        for tex in sorted(repo.glob(d)):
            pdf = tex.with_suffix(".pdf")
            rel = str(pdf.relative_to(repo))
            try:
                head = tex.read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                continue
            if "\\documentclass" in head and git(repo, "ls-files", "--", rel).strip():
                out.append(rel)
    return out


def install(repo: Path, dest: str, docs, builds, untrack: bool, dry: bool) -> int:
    repo = repo.expanduser().resolve()
    if not (repo / ".git").exists():
        print(f"git repo でない: {repo}", file=sys.stderr)
        return 2
    acts = []
    tools = repo / TOOLS
    for f in VENDORED:
        src, dst = TEMPLATE / f, tools / f
        if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
            acts.append(f"写す {dst.relative_to(repo)}")
            if not dry:
                tools.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                dst.chmod(0o755)
    conf = repo / ".pdf-publish.conf"
    lines = ["# .pdf-publish.conf — build した PDF を push のたびに共有フォルダへ写す (正本 = claude-config/templates/shared-project/pdf-publish/)",
             "# 機械ごとに違う値 (Dropbox の場所・共有フォルダの path) は .pdf-publish.local に書く (git に入れない)", "",
             f"DEST={dest}", ""]
    for i, d in enumerate(docs):
        lines.append(f"DOC={d}")
        if i < len(builds) and builds[i]:
            lines.append(f"BUILD={builds[i]}")
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    if not conf.exists() or conf.read_text(encoding="utf-8") != text:
        acts.append("書く .pdf-publish.conf")
        if not dry:
            conf.write_text(text, encoding="utf-8")
    gi = repo / ".gitignore"
    have = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    want = [p for p in ["/.pdf-publish.local", *ignore_patterns(docs)] if p not in have]
    if want:
        acts.append(".gitignore に足す: " + " ".join(want))
        if not dry:
            body = gi.read_text(encoding="utf-8") if gi.exists() else ""
            if body and not body.endswith("\n"):
                body += "\n"
            body += "\n# build した PDF は git に入れない (push のたびに tools/pdf-publish/ が共有フォルダへ写す)\n" + "\n".join(want) + "\n"
            gi.write_text(body, encoding="utf-8")
    if untrack:
        tracked = built_tracked_pdfs(repo, docs)
        if tracked:
            acts.append("git rm --cached: " + " ".join(tracked))
            if not dry:
                git(repo, "rm", "-q", "--cached", "--", *tracked)
    if not dry:
        r = subprocess.run(["sh", str(tools / "install-hook.sh")], cwd=repo, capture_output=True, text=True)
        acts.append("hook: " + (r.stdout.strip() or r.stderr.strip()))
    for a in acts:
        print(("(dry-run) " if dry else "") + a)
    print("\nrepo の CLAUDE.md に足す文面 (保護 file なので手で / 承認を取って):\n"
          "- **PDF は git に入れない** (.gitignore 済)。 push すると tools/pdf-publish/ の pre-push hook が、 push した文書の PDF を"
          " (古ければ組み直して) 共有フォルダへ背景で写す。 clone ごとに 1 回 `sh tools/pdf-publish/install-hook.sh`"
          " (確認 = `--check`)。 共有フォルダの場所が違う機械は `.pdf-publish.local` に DROPBOX_ROOT= / DEST=。"
          " 提出版など残す版は tag で指す。 背景 = claude-config/conventions/repo-history-growth.md")
    return 0


def check(repo: Path) -> int:
    repo = repo.expanduser().resolve()
    bad = []
    for f in VENDORED:
        dst = repo / TOOLS / f
        if not dst.exists():
            bad.append(f"写しが無い: {dst.relative_to(repo)}")
        elif not filecmp.cmp(TEMPLATE / f, dst, shallow=False):
            bad.append(f"写しが正本と違う: {dst.relative_to(repo)} (install で配り直す)")
    if not (repo / ".pdf-publish.conf").exists():
        bad.append(".pdf-publish.conf が無い")
    r = subprocess.run(["sh", str(repo / TOOLS / "install-hook.sh"), "--check"], cwd=repo, capture_output=True, text=True) \
        if (repo / TOOLS / "install-hook.sh").exists() else None
    if r is None or r.returncode != 0:
        bad.append("この clone に pre-push hook が無い (sh tools/pdf-publish/install-hook.sh)")
    for b in bad:
        print(f"🟠 {repo.name}: {b}")
    if not bad:
        print(f"ok: {repo.name}")
    return 1 if bad else 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    fails = []

    def ok(label, cond):
        print(("  ok: " if cond else "  NG: ") + label)
        if not cond:
            fails.append(label)

    env_keys = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                "PDF_PUBLISH_FOREGROUND": "1"}
    saved = {k: os.environ.get(k) for k in env_keys}
    os.environ.update(env_keys)
    os.environ.pop("GIT_INDEX_FILE", None)
    try:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            remote, repo, drop = t / "remote.git", t / "repo", t / "Dropbox"
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
            subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
            (repo / "report").mkdir()
            (repo / "fig").mkdir()
            (repo / "report" / "a.tex").write_text("\\documentclass{article}\nA\n")
            (repo / "report" / "b.tex").write_text("\\documentclass{article}\nB\n")
            (repo / "report" / "frag.tex").write_text("\\section{frag}\n")
            (repo / "report" / "a.pdf").write_bytes(b"%PDF old a")
            (repo / "fig" / "plot.pdf").write_bytes(b"%PDF figure")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "init")
            git(repo, "push", "-q", "origin", "main")
            (drop / "proj-pdf").mkdir(parents=True)
            (repo / ".pdf-publish.local").write_text(f"DROPBOX_ROOT={drop}\n")
            rc = install(repo, "proj-pdf", ["report/*.tex"], ["cp {stem}.tex {stem}.pdf"], True, False)
            ok("install が走る", rc == 0)
            ok("追跡中の生成 PDF を index から外す (file は残る)",
               not git(repo, "ls-files", "report/a.pdf").strip() and (repo / "report" / "a.pdf").exists())
            ok("図の PDF は外さない", bool(git(repo, "ls-files", "fig/plot.pdf").strip()))
            ok(".gitignore に生成 PDF と .local", "/report/*.pdf" in (repo / ".gitignore").read_text()
               and "/.pdf-publish.local" in (repo / ".gitignore").read_text())
            ok("check が通る", check(repo) == 0)
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "pdf-publish")
            # b だけ変えて push → b は組まれて写る、 a (変わっていない) は写らない、 断片は組まない
            (repo / "report" / "b.tex").write_text("\\documentclass{article}\nB2\n")
            git(repo, "commit", "-qam", "edit b")
            git(repo, "push", "-q", "origin", "main")
            ok("push で発火: 変わった文書を組んで写す", (drop / "proj-pdf" / "b.pdf").read_text().endswith("B2\n"))
            ok("変わっていない文書は写さない", not (drop / "proj-pdf" / "a.pdf").exists())
            ok("断片は組まない", not (repo / "report" / "frag.pdf").exists())
            ok("生成 PDF は git に入らない (ignore)", not git(repo, "ls-files", "report/b.pdf").strip())
            # 手で全部写す。 main.pdf は src のような dir を飛ばして repo 名に
            (repo / "src").mkdir()
            (repo / "src" / "main.tex").write_text("\\documentclass{article}\nM\n")
            (repo / "src" / "main.pdf").write_bytes(b"%PDF main")
            conf = repo / ".pdf-publish.conf"
            conf.write_text(conf.read_text() + "DOC=src/main.tex\n")
            subprocess.run(["sh", str(repo / TOOLS / "pdf-publish.sh"), "--all"], cwd=repo, check=True)
            ok("--all で残りも写す", (drop / "proj-pdf" / "a.pdf").exists())
            ok("src/main.pdf は repo 名で写る", (drop / "proj-pdf" / "repo.pdf").exists())
            # 共有フォルダが無い機械では黙って skip (push は通る)
            shutil.rmtree(drop / "proj-pdf")
            (repo / "report" / "b.tex").write_text("\\documentclass{article}\nB3\n")
            git(repo, "commit", "-qam", "edit b again")
            r = subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "main"], capture_output=True)
            log = (repo / ".git" / "pdf-publish.log").read_text()
            ok("共有フォルダが無くても push は通り、 記録に skip", r.returncode == 0 and "skip" in log)
            # 既存の pre-push は鎖でつながり、 その結果で push が止まる
            hook = repo / ".git" / "hooks" / "pre-push"
            hook.write_text("#!/bin/sh\nexit 1\n")
            hook.chmod(0o755)
            subprocess.run(["sh", str(repo / TOOLS / "install-hook.sh")], cwd=repo, check=True, capture_output=True)
            (repo / "report" / "b.tex").write_text("\\documentclass{article}\nB4\n")
            git(repo, "commit", "-qam", "edit b 4")
            r = subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "main"], capture_output=True)
            ok("既存の pre-push を鎖でつなぎ、 その失敗で push が止まる",
               r.returncode != 0 and (hook.parent / "pre-push.before-pdf-publish").exists())
            # 写しが正本と違えば check が言う
            (repo / TOOLS / "pdf-publish.sh").write_text("#!/bin/sh\nexit 0\n")
            ok("写しの drift を check が言う", check(repo) == 1)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print(f"selftest: {'FAILED ' + str(len(fails)) if fails else 'ALL PASS'}")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    i = sub.add_parser("install")
    i.add_argument("repo")
    i.add_argument("--dest", required=True)
    i.add_argument("--doc", action="append", default=[], required=True)
    i.add_argument("--build", action="append", default=[])
    i.add_argument("--untrack", action="store_true")
    i.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("repo")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "install":
        return install(Path(a.repo), a.dest, a.doc, a.build, a.untrack, a.dry_run)
    if a.cmd == "check":
        return check(Path(a.repo))
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
