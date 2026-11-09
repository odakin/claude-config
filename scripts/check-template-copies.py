#!/usr/bin/env python3
"""check-template-copies.py — 共有 repo に置いた雛形の写し (collaborator-check・tools/py・pdf-publish) が正本と違わないかを base の全 repo で見て、 古いだけか repo の側で手直しされたかを分けて出す。

## なぜ

共有 repo には templates/shared-project/ の写しを置く (共同編集者は claude-config を持たないので repo 単体で動く写し)。
正本を直しても、 写しは配り直すまで古いまま残る。 写しが古いことを言うのは installer の `check <repo>` だけで、
repo ごとに手で打たない限り出ない (実測: 複数の repo の写しが正本の過去の版のまま残り、 正本の直しが相手の手元に
届いていなかった)。 古さが生まれるのは正本を変えた commit なので、 その commit の時点で古くなった写しを出し、
取りこぼし (別の機械で直して pull で届いた・警告の見落とし) は一覧の段で拾う。 規約 = conventions/shared-repo.md#template-copy-staleness

## 何を見るか (写しを持つ repo は登録せず、 repo の中身から導く)

- `.collaborator-check.conf` がある repo = `tools/collaborator-check/collaborator-check.sh`
  (正本 = templates/shared-project/collaborator-check/collaborator-check.sh)
- conf に `python` の行がある repo = その行の入口 (既定 `tools/py`、 正本 = templates/shared-project/python-env/py)。
  conf に `python` の行が無い repo の `tools/py` は見ない (repo が自分で書いた入口を古い写しと言わない)
- `tools/pdf-publish/` がある repo = その中の pdf-publish.sh・install-hook.sh (正本 = templates/shared-project/pdf-publish/)

置き場と file 名は 2 つの installer (install-collaborator-check.py・install-pdf-publish.py) の定数を読む (二重に書かない)。

## 分け方

写しの中身を正本の各版 (git の履歴の blob) と比べる:
- 今の正本と同じ = 黙る
- 正本の過去のどれかの版と同じ = 「古いだけ」 (repo の側の手直しは無い = そのまま配り直してよい)
- どの版とも違う = 「repo の側で手直しされた」 (配り直す前に中身を見る。 黙って上書きしない)
- 写しが無い = 「写しが無い」

今の正本は作業木の file を読む (= 正本を直した commit の pre-commit では、 直す前の版と同じ写しが「古いだけ」 に出る)。

## 使い方

    check-template-copies.py [--base <dir>] [--footer <text>]
    check-template-copies.py --selftest

base の既定 = 環境変数 TEMPLATE_COPIES_BASE、 無ければこの claude-config の checkout の親 dir
(worktree から呼んでも本体の checkout の親)。 `--footer` = 古い写しがあるときだけ最後に出す 1 行 (呼ぶ側の段取りを書く)。
終了値: 0 = 全部同じ (写しを持つ repo が無いときも) / 1 = 古い・手直し・欠けた写しがある / 3 = 検査が走れない
(base が dir でない・正本の履歴を git で読めない)。 出力は揃っていれば無し。

配線: claude-config の commit で templates/shared-project/ の 3 つの雛形が staged に入ったら `.claude/pre-commit-extra.sh`
が警告だけで呼ぶ (commit は止めない)。 個人層の一覧の段がもう 1 つの呼び元。

## 限界

- 見るのは base の直下の repo だけ (入れ子の repo・別の場所の clone は見ない)
- 比べるのはバイト単位 (改行の変換 = Windows の autocrlf がかかった clone は「手直し」 に見える。 installer の check と同じ)
- 正本の file の名前が履歴の途中で変わっていたら、 変わる前の版は比べない (rename を追わない)
- 配り直しも commit もしない (共同研究者の repo への push は外に出る変更 = 人か依頼を受けた worker がする)
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


def _load(modname: str, fname: str):
    spec = importlib.util.spec_from_file_location(modname, HERE / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


CC = _load("install_collaborator_check", "install-collaborator-check.py")
PP = _load("install_pdf_publish", "install-pdf-publish.py")

CC_REL = PurePosixPath(CC.TEMPLATE.resolve().relative_to(REPO_ROOT).as_posix())
PY_REL = PurePosixPath(CC.PY_TEMPLATE.resolve().relative_to(REPO_ROOT).as_posix())
PP_REL = PurePosixPath(PP.TEMPLATE.resolve().relative_to(REPO_ROOT).as_posix())

# 正本を変えた commit で pre-commit が見る dir (= .claude/pre-commit-extra.sh の検査 6 と同じ 3 つ)
WATCHED_TEMPLATE_DIRS = (str(CC_REL), str(PY_REL.parent), str(PP_REL))


def blob_sha(data: bytes) -> str:
    """git の blob の hash (= git hash-object と同じ)。 git を呼ばない = 写しの repo の filter (git-crypt) を通さない。"""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def targets(repo: Path) -> list[tuple[str, Path, PurePosixPath]]:
    """repo が持つ写しを (種類, 写しの path, 正本の repo 内 path) で返す。 置き場は installer の定数から。"""
    out: list[tuple[str, Path, PurePosixPath]] = []
    conf = repo / CC.CONF
    if conf.is_file():
        out.append(("collaborator-check", repo / CC.TOOLS / CC.SCRIPT, CC_REL / CC.SCRIPT))
        lines = [ln.strip() for ln in conf.read_text(errors="replace").splitlines()]
        for w in sorted(set(CC._python_wrappers(lines))):
            out.append(("tools/py", repo / w, PY_REL))
    if (repo / PP.TOOLS).is_dir():
        for f in PP.VENDORED:
            out.append(("pdf-publish", repo / PP.TOOLS / f, PP_REL / f))
    return out


class History:
    """正本の各 file の過去の版 (blob の hash → 短い commit と日付)。 file ごとに git log を 1 回。"""

    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[str, dict[str, tuple[str, str]]] = {}

    def versions(self, rel: PurePosixPath) -> dict[str, tuple[str, str]]:
        key = str(rel)
        if key in self._cache:
            return self._cache[key]
        r = subprocess.run(
            ["git", "-C", str(self.root), "log", "--no-renames", "--no-abbrev", "--raw",
             "--format=C %H %cs", "--", key],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"正本の履歴を読めない ({self.root}: {r.stderr.strip()[:200]})")
        found: dict[str, tuple[str, str]] = {}
        cur = ("", "")
        for line in r.stdout.splitlines():
            if line.startswith("C "):
                parts = line.split()
                cur = (parts[1][:8], parts[2] if len(parts) > 2 else "")
            elif line.startswith(":"):
                fields = line.split("\t", 1)[0].split()
                if len(fields) >= 4:
                    dst = fields[3]
                    if set(dst) != {"0"} and dst not in found:  # 新しい順に読む = 同じ中身の版が複数あれば新しい方を残す
                        found[dst] = cur
        self._cache[key] = found
        return found


def classify(copy: Path, template: Path, hist: History, rel: PurePosixPath) -> str | None:
    """None = 今の正本と同じ。 それ以外は 1 行の判定。"""
    if not copy.is_file():
        return "写しが無い"
    data = copy.read_bytes()
    if template.is_file() and data == template.read_bytes():
        return None
    ver = hist.versions(rel).get(blob_sha(data))
    if ver:
        return f"古いだけ = 正本の {ver[0]} ({ver[1]}) の版と同じ"
    return "どの版とも違う = repo の側で手直しされた (配り直す前に中身を見る)"


def redeploy_hint(kind: str, repo: Path, copy: Path, template: Path, root: Path, verdict: str) -> str:
    if verdict.startswith("どの版"):
        return f"diff {template} {copy}"
    if kind == "collaborator-check":
        return f"python3 {root / 'scripts' / 'install-collaborator-check.py'} install {repo}"
    if kind == "tools/py":
        return f"python3 {root / 'scripts' / 'install-collaborator-check.py'} install {repo} --replace-python-wrapper"
    return f"cp {template} {copy}"


def default_base(root: Path) -> Path:
    env = os.environ.get("TEMPLATE_COPIES_BASE")
    if env:
        return Path(env).expanduser()
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        common = Path(r.stdout.strip())
        if common.name == ".git":
            return common.parent.parent  # 本体の checkout の親 (worktree から呼んでも同じ)
    return root.parent


def scan(base: Path, root: Path) -> list[str]:
    """古い・手直し・欠けた写しを 1 行ずつ。 揃っていれば空。 履歴を読めなければ RuntimeError。"""
    hist = History(root)
    rows: list[str] = []
    root_r = root.resolve()
    for repo in sorted(p for p in base.iterdir() if p.is_dir() and (p / ".git").exists()):
        if repo.resolve() == root_r:
            continue
        for kind, copy, rel in targets(repo):
            template = root / Path(*rel.parts)
            verdict = classify(copy, template, hist, rel)
            if verdict is None:
                continue
            shown = copy.relative_to(repo).as_posix()
            hint = redeploy_hint(kind, repo, copy, template, root, verdict)
            rows.append(f"  🟠 {repo.name} · {shown} — {verdict} → {hint}")
    return rows


def run(base: Path, root: Path, footer: str | None) -> int:
    if not base.is_dir():
        print(f"⏸ check-template-copies: base が dir でない ({base}) = 検査が走っていない")
        return 3
    try:
        rows = scan(base, root)
    except RuntimeError as e:
        print(f"⏸ check-template-copies: {e} = 検査が走っていない")
        return 3
    if not rows:
        return 0
    print(f"🧩 共有 repo に置いた雛形の写しが正本と違う {len(rows)} 件 (正本 = {root / 'templates' / 'shared-project'}):")
    for r in rows:
        print(r)
    print("  配り直したら、 その repo で写しの file だけを path 指定で commit + push する (作業中の他人の変更に触らない)")
    if footer:
        print(f"  {footer}")
    return 1


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------
def selftest() -> int:
    import io
    from contextlib import redirect_stdout

    fails: list[str] = []

    def check(ok: bool, msg: str) -> None:
        if not ok:
            fails.append(msg)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td).resolve()  # macOS の /var → /private/var を先に解く (出力の path と比べるため)
        base = td / "base"
        base.mkdir()
        env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")

        def git(*a, cwd: Path, date: str | None = None):
            e = dict(env)
            if date:
                e.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
            subprocess.run(["git", *a], cwd=cwd, env=e, check=True, capture_output=True)

        # 正本の repo (base の中に置く = 既定の base の求め方と、 自分を飛ばすことも試す)
        root = base / "tmpl-root"
        root.mkdir()
        git("init", "-q", cwd=root)
        cc_t = root / Path(*CC_REL.parts) / CC.SCRIPT
        py_t = root / Path(*PY_REL.parts)
        pp_t = {f: root / Path(*PP_REL.parts) / f for f in PP.VENDORED}
        v1 = {"cc": b"#!/bin/bash\n# cc v1\n", "py": b"#!/bin/bash\n# py v1\n"}
        v2 = {"cc": b"#!/bin/bash\n# cc v2\n", "py": b"#!/bin/bash\n# py v2\n"}
        for p in (cc_t, py_t, *pp_t.values()):
            p.parent.mkdir(parents=True, exist_ok=True)
        cc_t.write_bytes(v1["cc"])
        py_t.write_bytes(v1["py"])
        for f, p in pp_t.items():
            p.write_bytes(f"# {f} v1\n".encode())
        git("add", "-A", cwd=root)
        git("commit", "-q", "-m", "v1", cwd=root, date="2026-01-01T00:00:00")
        cc_t.write_bytes(v2["cc"])
        py_t.write_bytes(v2["py"])
        git("commit", "-q", "-am", "v2", cwd=root, date="2026-01-02T00:00:00")
        v1_short = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD~1"],
                                  capture_output=True, text=True, env=env).stdout.strip()[:8]

        def mkrepo(name: str, conf: str | None = None, files: dict[str, bytes] | None = None) -> Path:
            r = base / name
            r.mkdir()
            git("init", "-q", cwd=r)
            if conf is not None:
                (r / CC.CONF).write_text(conf)
            for rel, data in (files or {}).items():
                p = r / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            return r

        cc_copy = (CC.TOOLS / CC.SCRIPT).as_posix()
        pp_dir = PP.TOOLS.as_posix()
        mkrepo("r-ok", "# conf\nread README.md -- x\n", {cc_copy: v2["cc"]})
        mkrepo("r-stale", "# conf\n", {cc_copy: v1["cc"]})
        mkrepo("r-edited", "# conf\n", {cc_copy: v2["cc"] + "# repo の独自\n".encode()})
        mkrepo("r-missing", "# conf\n")
        mkrepo("r-own-py", "# conf\n", {cc_copy: v2["cc"], "tools/py": b"#!/bin/sh\nexec python3 \"$@\"\n"})
        mkrepo("r-py", "# conf\npython tools/py -- 計算\n", {cc_copy: v2["cc"], "tools/py": v1["py"]})
        mkrepo("r-pdf", None, {f"{pp_dir}/pdf-publish.sh": b"# pdf-publish.sh v1\n",
                               f"{pp_dir}/install-hook.sh": b"# local hook\n"})
        (base / "not-a-repo").mkdir()
        (base / "not-a-repo" / CC.CONF).write_text("# conf\n")

        def call(*argv: str) -> tuple[int, str]:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(list(argv))
            return rc, buf.getvalue()

        rc, out = call("--base", str(base), "--template-root", str(root), "--footer", "FOOTER-LINE")
        check(rc == 1, f"古い写しがあるのに exit {rc}")
        check(f"r-stale · {cc_copy} — 古いだけ = 正本の {v1_short} (2026-01-01) の版と同じ" in out,
              f"古いだけの写しを、 一致した版の commit と日付つきで出していない:\n{out}")
        check("install-collaborator-check.py install" in out and "r-stale" in out,
              f"古いだけの collaborator-check に installer の配り直しの 1 行が無い:\n{out}")
        check(f"r-edited · {cc_copy} — どの版とも違う" in out and f"diff {cc_t}" in out,
              f"手直しされた写しを「どの版とも違う」 と diff の 1 行で出していない:\n{out}")
        check(f"r-missing · {cc_copy} — 写しが無い" in out, f"欠けた写しを出していない:\n{out}")
        check("r-py · tools/py — 古いだけ" in out and "--replace-python-wrapper" in out,
              f"conf に python 行がある repo の古い tools/py を出していない:\n{out}")
        check("r-own-py" not in out, f"conf に python 行の無い repo の tools/py を古い写しと言った:\n{out}")
        check(f"r-pdf · {pp_dir}/install-hook.sh — どの版とも違う" in out and f"r-pdf · {pp_dir}/pdf-publish.sh" not in out,
              f"pdf-publish の写しの判定が違う (同じ方は黙り、 手直しは出す):\n{out}")
        check(" r-ok ·" not in out and " not-a-repo ·" not in out and " tmpl-root ·" not in out,
              f"揃った repo・git でない dir・正本の repo 自身を出した:\n{out}")
        check(out.rstrip().endswith("FOOTER-LINE"), f"--footer を最後に出していない:\n{out}")
        check(out.count("🟠") == 5, f"件数が 5 でない:\n{out}")

        # 揃えば黙る (footer も出さない)
        base2 = td / "base2"
        base2.mkdir()
        (base / "r-ok").rename(base2 / "r-ok")
        rc, out = call("--base", str(base2), "--template-root", str(root), "--footer", "FOOTER-LINE")
        check(rc == 0 and out == "", f"揃っているのに出した / exit {rc}:\n{out}")

        # 正本を作業木で直した (commit 前 = pre-commit の時点) → 直す前の版と同じ写しは「古いだけ」
        cc_t.write_bytes(b"#!/bin/bash\n# cc v3 (uncommitted)\n")
        v2_short = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, env=env).stdout.strip()[:8]
        rc, out = call("--base", str(base2), "--template-root", str(root))
        check(rc == 1 and f"古いだけ = 正本の {v2_short} (2026-01-02) の版と同じ" in out,
              f"正本を作業木で直した後、 直す前の版の写しを古いだけと言わない:\n{out}")

        # 検査が走れない = exit 3 と 1 行
        rc, out = call("--base", str(td / "nope"), "--template-root", str(root))
        check(rc == 3 and "走っていない" in out, f"base が無いのに exit {rc}:\n{out}")
        notgit = td / "notgit"
        notgit.mkdir()
        rc, out = call("--base", str(base2), "--template-root", str(notgit))
        check(rc == 3 and "走っていない" in out, f"正本の履歴を読めないのに exit {rc}:\n{out}")

        # 既定の base = 環境変数、 無ければ正本の checkout の親
        old = os.environ.pop("TEMPLATE_COPIES_BASE", None)
        try:
            check(default_base(root).resolve() == base.resolve(), f"既定の base が正本の親でない: {default_base(root)}")
            os.environ["TEMPLATE_COPIES_BASE"] = str(base2)
            check(default_base(root).resolve() == base2.resolve(), "環境変数 TEMPLATE_COPIES_BASE が効かない")
        finally:
            os.environ.pop("TEMPLATE_COPIES_BASE", None)
            if old is not None:
                os.environ["TEMPLATE_COPIES_BASE"] = old

    # pre-commit の検査 6 が見る dir の一覧と、 ここが導く正本の dir が食い違わない (shell 側に同じ一覧が書いてある = 二重の一覧の網)
    hook = REPO_ROOT / ".claude" / "pre-commit-extra.sh"
    if hook.is_file():
        text = hook.read_text(errors="replace")
        for d in WATCHED_TEMPLATE_DIRS:
            check(d in text, f".claude/pre-commit-extra.sh の検査 6 が正本の dir {d} を見ていない (installer の定数と食い違う)")

    for f in fails:
        print(f"FAIL: {f}")
    print("selftest:", "OK" if not fails else f"{len(fails)} 件失敗")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--base", type=Path, help="写しを持つ repo を探す dir (既定 = TEMPLATE_COPIES_BASE、 無ければ claude-config の親)")
    ap.add_argument("--footer", help="古い写しがあるときだけ最後に出す 1 行")
    ap.add_argument("--template-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)  # selftest 用
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    root = a.template_root.resolve()
    base = a.base.expanduser() if a.base else default_base(root)
    return run(base, root, a.footer)


if __name__ == "__main__":
    sys.exit(main())
