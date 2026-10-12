#!/usr/bin/env python3
"""install-collaborator-check.py — 共有リポに「各 clone の session 開始時に、 その人の手元に要る設定 (個人の token・道具) と初回に読む節を確かめて出し、 隣に要る repo は自動で clone・更新する」 仕組みを配る。

## なぜ

共有リポに人を招待すると、 相手の手元でしか済ませられない手順が残る (自分の token を発行して置く・道具を入れる・
隣に要る repo を clone する・最初に読む節)。 招待の連絡に書いて伝えると、 相手が読み落とすか忘れた時点で止まり、 しかも誰も気付かない
(人の記憶は carrier でない = docs/convention-design-principles.md#human-memory-not-a-carrier)。 そこで
repo 自身に project の SessionStart hook を持たせ、 **相手が repo で session を開いた瞬間に、 欠けている物だけ**を
直し方つきで agent に渡す。 揃えば黙る。 規約 = conventions/shared-repo.md#collaborator-check

## 何を置くか (repo の中に。 共同編集者は claude-config を持たないので repo 単体で動く写しを置く)

- `tools/collaborator-check/collaborator-check.sh` = 正本 templates/shared-project/collaborator-check/ の写し
- `.collaborator-check.conf` = この repo が要る物 (書式 = collaborator-check.sh の冒頭)
- `.claude/settings.json` = SessionStart hook の 1 entry (既存の設定は残して足す)
- `.gitignore` = `!.claude/settings.json` (global の ignore が `.claude/*` を落としていても追跡されるように)

## 使い方

    install-collaborator-check.py install <repo> [--item '<conf の 1 行>' ...] [--dry-run]
    install-collaborator-check.py check <repo>      # 写しが正本と同じか・hook と conf があるか・settings.json が追跡できるか
    install-collaborator-check.py --selftest        # 合成の repo で、 欠けた物だけ出る・初回だけ読む節が出る・冪等 まで確かめる

`--item` の例: `--item 'file ~/.secrets/svc-token SVC_TOKEN_FILE -- 自分の token を発行して置く'`
(その service を使わない人は SVC_TOKEN_FILE=none で黙らせられる = 満たせない ❌ を毎回出し続けない)
`--item 'repo tool-repo https://github.com/<owner>/tool-repo TOOL_REPO_DIR -- 道具'` = この repo の隣に無ければ
session 開始時に clone し、 あれば 20 時間に 1 回 fast-forward で最新にする (人に clone を頼まない。 URL は https:// か file://)
(既に同じ行が conf にあれば足さない)。 commit と push はしない。 CLAUDE.md に足す文面は最後に出す (保護 file なので書かない)。
`--item 'board board AI_COLLABORATION_DIR -- 掲示板の自分宛て'` = この repo の中の掲示板 (`board/`) で要注意の thread
(引受待ち・検収待ち・質問) を、 相手の session の冒頭に出す (engine = 隣の ai-collaboration、 手元の写しを読む。
実測: 共同研究者側の session は engine を持つだけで掲示板を見ず、 依頼が止まったままだった)。

## 限界

- 走るのは hook を読む agent (Claude Code の project 設定) だけ。 hook を持たない agent (Codex ほか) のために、
  repo の CLAUDE.md に「session 開始時に 1 回 `bash tools/collaborator-check/collaborator-check.sh`」 を書く (出す文面に含めてある)
- Claude Code は repo の project 設定の hook を、 その repo を信頼した後に走らせる (初回の確認は相手の画面に出る)
- 確かめるのは「file がある (空でない)」 「command がある」 まで。 token が有効かは見ない (各 service の検査に任せる)
- repo の clone と更新は network が無いと失敗する (❌ / ⚠️ で直し方を出す)。 Codex の sandbox のように network の無い
  agent では、 user の terminal で 1 回 `bash tools/collaborator-check/collaborator-check.sh` を打つ
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "shared-project" / "collaborator-check"
SCRIPT = "collaborator-check.sh"
TOOLS = Path("tools") / "collaborator-check"
CONF = ".collaborator-check.conf"
HOOK_CMD = 'bash "$CLAUDE_PROJECT_DIR/tools/collaborator-check/collaborator-check.sh"'
GITIGNORE_LINE = "!.claude/settings.json"
KINDS = ("file", "command", "read", "repo", "board")

CONF_HEADER = """# .collaborator-check.conf — この共有リポを各自の手元で使うのに要るもの
# 書式と挙動の正本 = tools/collaborator-check/collaborator-check.sh の冒頭
# (仕組みの正本 = claude-config の conventions/shared-repo.md#collaborator-check)
"""

CLAUDE_MD_TEXT = """- **手元の準備は session 開始時に自動で点検される** = `tools/collaborator-check/collaborator-check.sh`
  (Claude Code の project hook = `.claude/settings.json`。 要る物の一覧 = `.collaborator-check.conf`)。
  欠けた物があれば直し方つきで出るので、 agent はそれを user に伝える。 隣に要る repo (conf の `repo` 行) は
  無ければその場で clone され、 あれば最新に保たれる。 hook を持たない agent (Codex ほか) は
  session 開始時に 1 回 `bash tools/collaborator-check/collaborator-check.sh` を実行する。
  仕組みの正本 = [claude-config/conventions/shared-repo.md#collaborator-check](https://github.com/<owner>/claude-config/blob/main/conventions/shared-repo.md#collaborator-check)"""


def _validate_item(item: str) -> str:
    item = item.strip()
    kind = item.split(None, 1)[0] if item else ""
    if kind not in KINDS:
        sys.exit(f"--item の種類が不明: {item!r} (使えるのは {', '.join(KINDS)})")
    if kind in ("file", "command") and " -- " not in item:
        sys.exit(f"--item に直し方 ( -- の後) が無い: {item!r}")
    if kind == "repo":
        parts = item.split(" -- ", 1)[0].split()
        if len(parts) < 3 or "/" in parts[1] or parts[1] in (".", "..") or parts[1].startswith("-"):
            sys.exit(f"--item repo は 'repo <dir 名> <clone URL> [<環境変数>] -- <何に使うか>': {item!r}")
        if not parts[2].startswith(("https://", "file://")):
            sys.exit(f"--item repo の URL は https:// か file:// だけ: {item!r}")
    return item


def _load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"{path} が JSON として読めない ({e})。 手で直してから再実行")


def _has_hook(settings: dict) -> bool:
    for group in settings.get("hooks", {}).get("SessionStart", []) or []:
        for h in group.get("hooks", []) or []:
            if h.get("command") == HOOK_CMD:
                return True
    return False


def install(repo: Path, items: list[str], dry: bool) -> int:
    repo = repo.resolve()
    if not (repo / ".git").exists():
        sys.exit(f"git repo ではない: {repo}")
    items = [_validate_item(i) for i in items]
    actions: list[str] = []

    # 1. 写し
    dst = repo / TOOLS / SCRIPT
    src = TEMPLATE / SCRIPT
    if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
        actions.append(f"写す: {TOOLS / SCRIPT}")
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            dst.chmod(0o755)

    # 2. conf
    conf = repo / CONF
    existing = conf.read_text().splitlines() if conf.exists() else []
    new_lines = [i for i in items if i not in [l.strip() for l in existing]]
    if not conf.exists():
        actions.append(f"作る: {CONF} (項目 {len(new_lines)})")
        if not dry:
            conf.write_text(CONF_HEADER + "".join(l + "\n" for l in new_lines))
    elif new_lines:
        actions.append(f"足す: {CONF} に {len(new_lines)} 行")
        if not dry:
            text = conf.read_text()
            if text and not text.endswith("\n"):
                text += "\n"
            conf.write_text(text + "".join(l + "\n" for l in new_lines))

    # 3. settings.json の hook
    sp = repo / ".claude" / "settings.json"
    settings = _load_settings(sp)
    if not _has_hook(settings):
        actions.append("足す: .claude/settings.json の SessionStart hook")
        if not dry:
            settings.setdefault("hooks", {}).setdefault("SessionStart", []).append(
                {"hooks": [{"type": "command", "command": HOOK_CMD}]})
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")

    # 4. .gitignore
    gi = repo / ".gitignore"
    gi_text = gi.read_text() if gi.exists() else ""
    if GITIGNORE_LINE not in gi_text.splitlines():
        actions.append(f"足す: .gitignore に {GITIGNORE_LINE}")
        if not dry:
            if gi_text and not gi_text.endswith("\n"):
                gi_text += "\n"
            gi.write_text(gi_text + "\n# collaborator-check の project hook は共有する (global の .claude/* ignore を打ち消す)\n"
                          + GITIGNORE_LINE + "\n")

    head = "[dry-run] " if dry else ""
    if actions:
        for a in actions:
            print(f"{head}{a}")
    else:
        print("変更なし (既に入っている)")
    print("\nrepo の CLAUDE.md (共同編集者向けの節) に足す文面 (<owner> を埋める):\n" + CLAUDE_MD_TEXT)
    return 0


def check(repo: Path) -> int:
    repo = repo.resolve()
    probs: list[str] = []
    dst = repo / TOOLS / SCRIPT
    if not dst.exists():
        probs.append(f"{TOOLS / SCRIPT} が無い")
    elif not filecmp.cmp(TEMPLATE / SCRIPT, dst, shallow=False):
        probs.append(f"{TOOLS / SCRIPT} が正本と違う (= install で配り直す)")
    if not (repo / CONF).exists():
        probs.append(f"{CONF} が無い")
    sp = repo / ".claude" / "settings.json"
    if not _has_hook(_load_settings(sp)):
        probs.append(".claude/settings.json に SessionStart hook が無い")
    r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", ".claude/settings.json"])
    if r.returncode == 0:
        probs.append(".claude/settings.json が ignore されている (= 共同編集者に届かない)")
    for p in probs:
        print(f"❌ {p}")
    if not probs:
        print("✅ collaborator-check は入っていて正本と同じ")
    return 1 if probs else 0


def selftest() -> int:
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        repo = td / "repo"
        repo.mkdir()
        env = dict(os.environ, HOME=str(td / "home"), GIT_CONFIG_GLOBAL="/dev/null")
        (td / "home").mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
        # global の ignore を模す
        (repo / ".git" / "info" / "exclude").write_text(".claude/*\n")
        items = ["read README.md §はじめに -- 最初に読む",
                 "file ~/.secrets/selftest-token SELFTEST_TOKEN_FILE -- token を置く",
                 "command definitely-not-a-command-xyz -- 入れる"]
        argv = [sys.executable, __file__, "install", str(repo)]
        for i in items:
            argv += ["--item", i]
        subprocess.run(argv, check=True, env=env, capture_output=True)
        subprocess.run(argv, check=True, env=env, capture_output=True)  # 冪等
        settings = json.loads((repo / ".claude" / "settings.json").read_text())
        n = sum(1 for g in settings["hooks"]["SessionStart"] for h in g["hooks"] if h["command"] == HOOK_CMD)
        if n != 1:
            fails.append(f"hook entry が {n} 個 (1 個のはず)")
        conf_lines = [l for l in (repo / CONF).read_text().splitlines() if l and not l.startswith("#")]
        if conf_lines != items:
            fails.append(f"conf の項目が違う: {conf_lines}")
        if subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", ".claude/settings.json"], env=env).returncode == 0:
            fails.append("settings.json が ignore されたまま")

        sh = repo / TOOLS / SCRIPT

        def run(*a, extra=None):
            e = dict(env, **(extra or {}))
            return subprocess.run(["bash", str(sh), *a], capture_output=True, text=True, env=e).stdout

        out1 = run()
        if "📖 README.md §はじめに" not in out1 or "❌ ~/.secrets/selftest-token" not in out1 \
                or "❌ definitely-not-a-command-xyz" not in out1:
            fails.append(f"初回の出力が違う:\n{out1}")
        out2 = run()
        if "📖" in out2 or "❌ definitely-not-a-command-xyz" not in out2:
            fails.append(f"2 回目は読む節が消え、 欠けた物は残るはず:\n{out2}")
        tok = td / "tok"
        tok.write_text("x")
        out3 = run(extra={"SELFTEST_TOKEN_FILE": str(tok)})
        if "selftest-token" in out3 or "SELFTEST_TOKEN_FILE" in out3:
            fails.append(f"環境変数で置いた token が見えていない:\n{out3}")
        out3b = run(extra={"SELFTEST_TOKEN_FILE": "none"})
        if "selftest-token" in out3b:
            fails.append(f"環境変数 = none なのに token の ❌ が出た:\n{out3b}")
        (td / "home" / ".secrets").mkdir()
        (td / "home" / ".secrets" / "selftest-token").write_text("x")
        out4 = run(extra={"PATH": f"{td}:{env['PATH']}"})
        fake = td / "definitely-not-a-command-xyz"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        out5 = run(extra={"PATH": f"{td}:{env['PATH']}"})
        if out5.strip():
            fails.append(f"全部揃ったら黙るはず:\n{out5}")
        out6 = run("--all", extra={"PATH": f"{td}:{env['PATH']}"})
        if "✅" not in out6 or "📖" not in out6:
            fails.append(f"--all は ✅ と読む節を出すはず:\n{out6}")
        if "❌ ~/.secrets/selftest-token" in out4:
            fails.append(f"~ の展開が効いていない:\n{out4}")
        # repo: 隣に無ければ clone、 あれば 20 時間に 1 回 fast-forward、 作業中の変更があれば触らない
        pathenv = {"PATH": f"{td}:{env['PATH']}"}
        remote, seed = td / "remote.git", td / "seed"
        genv = dict(env, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
                    GIT_AUTHOR_DATE="2026-01-01T00:00:00", GIT_COMMITTER_DATE="2026-01-01T00:00:00")
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=env)
        subprocess.run(["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"], check=True, env=env)
        subprocess.run(["git", "init", "-q", str(seed)], check=True, env=env)

        def publish(text: str) -> None:
            (seed / "f.txt").write_text(text)
            subprocess.run(["git", "-C", str(seed), "add", "f.txt"], check=True, env=genv)
            subprocess.run(["git", "-C", str(seed), "commit", "-q", "-m", text], check=True, env=genv)
            subprocess.run(["git", "-C", str(seed), "push", "-q", str(remote), "HEAD:refs/heads/main"],
                           check=True, env=genv, capture_output=True)

        publish("v1")
        subprocess.run([sys.executable, __file__, "install", str(repo), "--item",
                        f"repo toolrepo file://{remote} TOOLREPO_DIR -- 道具"], check=True, env=env, capture_output=True)
        sib = td / "toolrepo"
        out7 = run(extra=pathenv)
        if "📥 toolrepo" not in out7 or not (sib / "f.txt").exists():
            fails.append(f"隣に無い repo を clone して 📥 を出すはず:\n{out7}")
        if run(extra=pathenv).strip():
            fails.append("clone の直後の session は黙るはず")
        publish("v2")
        run(extra=pathenv)
        if (sib / "f.txt").read_text() != "v1":
            fails.append("20 時間以内なのに pull した")
        stamp = sib / ".git" / "collaborator-check.pulled"
        os.utime(stamp, (0, 0))
        out8 = run(extra=pathenv)
        if (sib / "f.txt").read_text() != "v2" or out8.strip():
            fails.append(f"20 時間を過ぎたら黙って fast-forward するはず:\n{out8}")
        publish("v3")
        os.utime(stamp, (0, 0))
        (sib / "wip.txt").write_text("作業中")
        run(extra=pathenv)
        if (sib / "f.txt").read_text() != "v2":
            fails.append("作業中の変更があるのに pull した")
        (sib / "wip.txt").unlink()
        if run(extra=dict(pathenv, TOOLREPO_DIR="none")).strip():
            fails.append("環境変数 = none なのに repo の行を出した")
        bad = subprocess.run([sys.executable, __file__, "install", str(repo), "--item",
                              "repo x http://example.invalid/x -- y"], env=env, capture_output=True)
        if bad.returncode == 0:
            fails.append("http:// の repo を受け付けた")
        r = subprocess.run([sys.executable, __file__, "check", str(repo)], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            fails.append(f"check が通らない:\n{r.stdout}")
        sh.write_text(sh.read_text() + "\n# drift\n")
        r = subprocess.run([sys.executable, __file__, "check", str(repo)], capture_output=True, text=True, env=env)
        if r.returncode == 0:
            fails.append("写しを変えたのに check が通った")
        # conf が無い repo では何も出さない
        (repo / CONF).unlink()
        if run().strip():
            fails.append("conf が無いのに出力した")
    for f in fails:
        print(f"FAIL: {f}")
    print("selftest:", "OK" if not fails else f"{len(fails)} 件失敗")
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("install")
    pi.add_argument("repo", type=Path)
    pi.add_argument("--item", action="append", default=[])
    pi.add_argument("--dry-run", action="store_true")
    pc = sub.add_parser("check")
    pc.add_argument("repo", type=Path)
    a = ap.parse_args()
    if a.cmd == "install":
        return install(a.repo, a.item, a.dry_run)
    return check(a.repo)


if __name__ == "__main__":
    sys.exit(main())
