#!/usr/bin/env python3
"""check-memory-file-bloat.py — memory file (CLAUDE.md / SESSION.md) の肥大 surface。

層1 engine (2026-09-12 に個人層から hoist)。 auto-load される memory file の肥大は
Claude Code を使う誰にでも起きるので判定は公開層に置き、 **発火面の配線 (どの surfacer /
dashboard / CI から呼ぶか) は各利用者の層に残す** (= kernel-up / instance-down)。
⚠️ 検査を作っただけでは発火しない — 入口 script だけに配線すると「人が見に来た turn」 に
しか出ない (= 層1 docs/convention-design-principles.md#firing-surface-hierarchy)。

CLAUDE.md 連鎖は毎 session + 毎 headless routine が払う税で、 肥大の failure mode は
2 つ: ① headless `claude -p` の "Prompt is too long" silent 全滅 (2026-07-29 実害 =
個人層 CLAUDE.md 276 KB で日次 cron 5 本が 4-5 日全滅、 RCA =
個人層の RCA plan) ② そもそも**誰も見ておらず気づかず育つ**
(2026-09-01 実害 = user の手動質問で初めて fleet 実測し 或る原稿 repo が 456 KB 等と判明、
6 repo 一斉縮退 1.37 → 0.49 MB)。 本 script は ② を塞ぐ常設 backstop:
~/Claude/ 直下 repo の CLAUDE.md / SESSION.md サイズを実測し、 閾値超過だけを surface する。

閾値 (本 docstring = SoT。 根拠 = 2026-09-01 縮退 campaign の実測):
  per-file:  🟡 150 KB (= 縮退推奨窓。 縮退直後の fleet max ~140 KB 〔= 健康 floor〕 では
             点かず、 再肥大が一段進んだら点く位置 — 慢性点灯は「healthy = silent」 に反する) /
             🔴 200 KB (= 276 KB cron 全滅ラインへの接近、 即縮退)
  per-repo:  CLAUDE.md + SESSION.md 合計で 🟡 200 KB / 🔴 300 KB (= その repo で開く
             session の実効 auto-load 税。 per-file が両方 subthreshold でも合計で焼ける
             「個別は subthreshold・合計で焼ける」 型 (254+202) を catch)
  行数 (登録制): LINE_LIMITS に載せた file だけ 🟡 / 🔴 を行数で出す。 byte は auto-load されない SESSION.md の
             再肥大を拾わない (2026-09-11 の claude-config/SESSION.md は 506 行でも 91 KB)。 縮退した file を縮退と
             同じ turn で登録する (= 層1 claude-config/conventions/memory-file-slimming.md#regrowth-backstop)。
             claude-config/SESSION.md = 🟡 100 / 🔴 200 行 (目安 ~80 + slack。 縮退直後の 47 行 = 健康 floor では点かない)。
             同じ閾値で、 claude-config の .claude/pre-commit-extra.sh 検査 5 が `--staged` で commit 時に本人へ warn する
             (値は LINE_LIMITS だけが持つ)。

運用:
  - finding 0 件 = silent / fail-open (= 予期せぬ例外は exit 0 + 1 行 note、 dashboard を殺さない)
  - finding 時は縮退の手順正本 = 層1 claude-config/conventions/memory-file-slimming.md を案内
    (fleet 並列縮退 #fleet-parallel-slimming で delegate に投げられる)
  - SESSION-archive.md / projects-archive.md 等の archive は**意図的に肥大する**ので対象外
    (= exact 名 CLAUDE.md / SESSION.md のみ。 archive を閾値に入れると縮退が「移せば移すほど
    焼ける」 self-defeating になる)
  - 射程 = ~/Claude/ 直下の repo のみ (Dropbox 側 local-only repo は ask-gate 圏のため対象外)。
    symlink は realpath で dedupe (root ~/Claude/CLAUDE.md は glob 圏外だが防御的に)
  - trend (growth-rate) 分析はしない = 絶対閾値のみの宣言的圏外。 「閾値未満のまま慢性成長」 が
    実害を出したら un-defer (git 高水位方式 = check-career-db-truncation.py の型を流用)

selftest: --selftest (tempdir fixture、 実 fleet 非依存)。 root 差し替え = 第 1 引数 --root DIR。

commit 時 warn (= 書いた本人に、 書いた commit で届ける): `--staged [--repo DIR] [--file CLAUDE.md]
[--entry-section '### 見出し'] [--entry-bytes 1200] [--file-kb 150]` = stage した file の ① 全体 KB ② LINE_LIMITS の行数
③ 見出しの節で新規・書き換えた entry の byte (#per-entry-commit-warn)。 止めない (exit 0)、 検査不能は exit 3 (呼び元が
「この commit では走っていない」 を出す = hook-authoring.md#warn-check-crash-visible)。 file を stage していなければ何もしない。
"""
import os
import sys
from pathlib import Path

WARN_FILE_KB = 150
CRIT_FILE_KB = 200
WARN_REPO_KB = 200
CRIT_REPO_KB = 300
LINE_LIMITS = {  # root 相対の file → (🟡 行, 🔴 行)。 縮退した file を登録する
    "claude-config/SESSION.md": (100, 200),
}
TARGETS = ("CLAUDE.md", "SESSION.md")
SLIM_DOC = "claude-config/conventions/memory-file-slimming.md"


def scan(root: Path, line_limits=None):
    """[(severity, line)] を返す。 severity = 2 (🔴) / 1 (🟡)。"""
    findings = []
    seen = set()
    for repo in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        sizes = {}
        for name in TARGETS:
            f = repo / name
            if not f.is_file():
                continue
            real = f.resolve()
            if real in seen:
                continue
            seen.add(real)
            sizes[name] = f.stat().st_size // 1024
        for name, kb in sizes.items():
            if kb >= CRIT_FILE_KB:
                findings.append((2, f"🔴 {repo.name}/{name} = {kb} KB (≥ {CRIT_FILE_KB} KB、 即縮退)"))
            elif kb >= WARN_FILE_KB:
                findings.append((1, f"🟡 {repo.name}/{name} = {kb} KB (≥ {WARN_FILE_KB} KB、 縮退推奨窓)"))
        total = sum(sizes.values())
        if len(sizes) >= 2:
            if total >= CRIT_REPO_KB:
                findings.append((2, f"🔴 {repo.name} 合計 (CLAUDE+SESSION) = {total} KB (≥ {CRIT_REPO_KB} KB)"))
            elif total >= WARN_REPO_KB:
                findings.append((1, f"🟡 {repo.name} 合計 (CLAUDE+SESSION) = {total} KB (≥ {WARN_REPO_KB} KB)"))
    for rel, (warn, crit) in (LINE_LIMITS if line_limits is None else line_limits).items():
        f = root / rel
        if not f.is_file():
            continue
        with f.open(encoding="utf-8", errors="replace") as fh:
            n = sum(1 for _ in fh)
        if n >= crit:
            findings.append((2, f"🔴 {rel} = {n} 行 (≥ {crit} 行、 縮退後の再肥大)"))
        elif n >= warn:
            findings.append((1, f"🟡 {rel} = {n} 行 (≥ {warn} 行、 縮退後の再肥大。 新 entry は 1-3 行 + 正本 pointer)"))
    return findings


def _section_entries(text: str, heading: str) -> list:
    """heading (例 `### 現在の作業プロジェクト`) で始まる行の節にある `- ` bullet 行。 節は同じか上の level の見出しで終わる。"""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith(heading)), None)
    if start is None:
        return []
    level = len(heading) - len(heading.lstrip("#"))
    out = []
    for l in lines[start + 1:]:
        h = len(l) - len(l.lstrip("#"))
        if h and l[h:h + 1] == " " and h <= level:
            break
        if l.startswith("- "):
            out.append(l)
    return out


def staged_warnings(repo: Path, rel: str, entry_section=None, entry_bytes=1200, file_kb=WARN_FILE_KB,
                    line_limits=None) -> list:
    """commit 時 warn (= 書いた本人に、 書いた commit で届ける。 次の session の surface では遅い)。
    stage された `rel` について: ① file 全体が file_kb 以上 ② LINE_LIMITS に `<repo 名>/<rel>` があれば行数 ③ entry_section の
    節で HEAD に無い (新規・書き換えた) entry が entry_bytes 超。 既存の長い entry を触らない commit では鳴らない
    (= #per-entry-commit-warn)。 blob は smudge を通して読む (git-crypt の path も平文 = hook-authoring.md#blob-read-git-crypt)。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from git_blob import read_blob_text

    staged = read_blob_text(f":{rel}", cwd=str(repo))
    if staged is None:
        return []
    head = read_blob_text(f"HEAD:{rel}", cwd=str(repo)) or ""
    msgs = []
    kb = len(staged.encode("utf-8")) / 1024
    if kb >= file_kb:
        msgs.append(f"{rel} が {kb:.0f} KB (≥ {file_kb} KB) — 縮退の手順 = 層1 {SLIM_DOC}")
    limits = LINE_LIMITS if line_limits is None else line_limits
    warn_lines = limits.get(f"{repo.resolve().name}/{rel}", (None, None))[0]
    n = staged.count("\n")
    if warn_lines is not None and n >= warn_lines:
        msgs.append(f"{rel} = {n} 行 (≥ {warn_lines}) — 新 entry は「日付 + 何を + 正本への pointer」 の 1-3 行、"
                    f" 経緯・実測は正本 doc か archive へ MOVE (手順 = 層1 {SLIM_DOC})")
    if entry_section:
        old = set(_section_entries(head, entry_section))
        for l in _section_entries(staged, entry_section):
            b = len(l.encode("utf-8"))
            if l not in old and b > entry_bytes:
                msgs.append(f"「{entry_section.lstrip('# ')}」 の entry が {b} B (> {entry_bytes}): {l[:40]}… — entry は"
                            f" pointer + 次の一手だけ、 状態・経緯は各 repo の SESSION / plan"
                            f" (層1 {SLIM_DOC}#per-entry-commit-warn)")
    return msgs


def staged_main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="check-memory-file-bloat.py --staged")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--file", dest="rel", default="CLAUDE.md")
    ap.add_argument("--entry-section", help="entry が並ぶ節の見出し行の先頭 (例: '### 現在の作業プロジェクト')")
    ap.add_argument("--entry-bytes", type=int, default=1200)
    ap.add_argument("--file-kb", type=int, default=WARN_FILE_KB)
    a = ap.parse_args(argv)
    try:
        import subprocess
        names = subprocess.run(["git", "-C", a.repo, "diff", "--cached", "--name-only"], capture_output=True,
                               text=True, check=True).stdout.split("\n")
        if a.rel not in names:
            return 0
        repo = Path(subprocess.run(["git", "-C", a.repo, "rev-parse", "--show-toplevel"], capture_output=True,
                                   text=True, check=True).stdout.strip())
        msgs = staged_warnings(repo, a.rel, a.entry_section, a.entry_bytes, a.file_kb)
    except Exception as e:  # noqa: BLE001  warn 検査の故障で commit を止めない。 呼び元が rc で「走らなかった」 を出す
        print(f"check-memory-file-bloat --staged: 検査不能 = {e.__class__.__name__}: {e}", file=sys.stderr)
        return 3
    for m in msgs:
        print(f"⚠️ pre-commit (memory file 肥大 WARN): {m}", file=sys.stderr)
    return 0


def report(findings, surface: bool = False) -> None:
    """surface=True = SessionStart hook 用 (= 枠飾りを出さない。 header は
    lib-surface.sh の hook_emit_guarded が付けるので、 ここで出すと二重になる)。"""
    if not findings:
        return
    if surface:
        for _, line in sorted(findings, reverse=True):
            print(line)
        print(f"→ 縮退手順の正本 = 層1 {SLIM_DOC} (MOVE + pointer 化・DELETE 禁止)")
        return
    print("=" * 64)
    print("📏 memory file 肥大 (= 毎 session / headless routine の auto-load 税)")
    print("=" * 64)
    for _, line in sorted(findings, reverse=True):
        print("   " + line)
    print(f"   → 縮退手順の正本 = 層1 {SLIM_DOC}")
    print("     (MOVE + pointer 化・DELETE 禁止。 複数 repo なら #fleet-parallel-slimming で delegate 並列)")


def selftest() -> int:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="membloat-selftest-"))
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and cond

    def mk(repo, name, kb):
        d = tmp / repo
        d.mkdir(exist_ok=True)
        (d / name).write_bytes(b"x" * (kb * 1024))

    try:
        mk("clean-repo", "CLAUDE.md", 40)
        mk("clean-repo", "SESSION.md", 30)
        mk("warn-repo", "CLAUDE.md", 160)
        mk("crit-repo", "SESSION.md", 210)
        mk("combined-repo", "CLAUDE.md", 120)   # 個別は subthreshold だが…
        mk("combined-repo", "SESSION.md", 110)  # 合計 230 ≥ 200 で 🟡 (= 合計で焼ける型)
        mk("archive-repo", "SESSION-archive.md", 500)  # archive は対象外
        f = scan(tmp)
        lines = [l for _, l in f]
        check(not any("clean-repo" in l for l in lines), "clean repo は silent")
        check(any("warn-repo/CLAUDE.md = 160 KB" in l and l.startswith("🟡") for l in lines), "150 KB 超で 🟡")
        check(any("crit-repo/SESSION.md = 210 KB" in l and l.startswith("🔴") for l in lines), "200 KB 超で 🔴")
        check(any("combined-repo 合計" in l and l.startswith("🟡") for l in lines),
              "個別 subthreshold でも合計 200 KB 超で 🟡 (= 合計で焼ける型)")
        check(not any("combined-repo/CLAUDE.md" in l for l in lines), "合計超過でも個別 subthreshold は silent")
        check(not any("archive-repo" in l for l in lines), "SESSION-archive.md は対象外")
        # 閾値境界: ちょうど 150 KB は点灯 (>= 判定)
        mk("edge-repo", "CLAUDE.md", 150)
        f2 = scan(tmp)
        check(any("edge-repo/CLAUDE.md = 150 KB" in l for _, l in f2), "境界 150 KB ちょうどは点灯 (>=)")
        # symlink dedupe: 同一 realpath は 1 回だけ数える
        (tmp / "link-repo").mkdir()
        (tmp / "link-repo" / "CLAUDE.md").symlink_to(tmp / "crit-repo" / "SESSION.md")
        f3 = scan(tmp)
        check(not any("link-repo" in l for _, l in f3), "symlink (同一 realpath) は dedupe")
        # 行数閾値 (登録制): 登録 file だけ行数で判定、 未登録の長い SESSION.md は行数では silent
        (tmp / "slim-repo").mkdir()
        lim = {"slim-repo/SESSION.md": (100, 200)}
        (tmp / "slim-repo" / "SESSION.md").write_text("x\n" * 99, encoding="utf-8")
        check(not any("slim-repo" in l for _, l in scan(tmp, lim)), "登録 file 99 行は silent")
        (tmp / "slim-repo" / "SESSION.md").write_text("x\n" * 100, encoding="utf-8")
        check(any(l.startswith("🟡 slim-repo/SESSION.md = 100 行") for _, l in scan(tmp, lim)), "登録 file 100 行で 🟡 (>=)")
        (tmp / "slim-repo" / "SESSION.md").write_text("x\n" * 200, encoding="utf-8")
        check(any(l.startswith("🔴 slim-repo/SESSION.md = 200 行") for _, l in scan(tmp, lim)), "登録 file 200 行で 🔴")
        (tmp / "long-repo").mkdir()
        (tmp / "long-repo" / "SESSION.md").write_text("x\n" * 500, encoding="utf-8")
        check(not any("long-repo" in l for _, l in scan(tmp, lim)), "未登録の 500 行 SESSION.md は行数では silent")
        check(not any("missing" in l for _, l in scan(tmp, {"missing/SESSION.md": (1, 2)})), "登録 file が無ければ silent")
        # --staged (commit 時 warn): 一時 repo で HEAD と index を作る
        import subprocess as sp
        g = tmp / "staged-repo"
        g.mkdir()
        sp.run(["git", "-C", str(g), "init", "-q"], check=True)
        sec = "### 作業中"
        long_old = "- **old** " + "y" * 1300
        (g / "CLAUDE.md").write_text(f"# t\n{sec}\n{long_old}\n- short\n## 次\n- " + "z" * 1300 + "\n", encoding="utf-8")
        sp.run(["git", "-C", str(g), "add", "CLAUDE.md"], check=True)
        sp.run(["git", "-C", str(g), "-c", "commit.gpgsign=false", "commit", "-qm", "i"], check=True,
               env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid"))

        def stage(text):
            (g / "CLAUDE.md").write_text(text, encoding="utf-8")
            sp.run(["git", "-C", str(g), "add", "CLAUDE.md"], check=True)
            return staged_warnings(g, "CLAUDE.md", sec, 1200, WARN_FILE_KB, {})

        base = f"# t\n{sec}\n{long_old}\n- short\n## 次\n- " + "z" * 1300 + "\n"
        check(stage(base + "x\n") == [], "--staged: 既存の長い entry と節の外の長い行には鳴らない")
        w = stage(base.replace("- short", "- short " + "w" * 1300))
        check(len(w) == 1 and "作業中" in w[0] and "B (> 1200)" in w[0], "--staged: 書き換えた entry が 1200 B 超で 1 件")
        check(len(stage(base + "x" * (151 * 1024) + "\n")) == 1, "--staged: file 全体 150 KB 以上で 1 件")
        sp.run(["git", "-C", str(g), "reset", "-q"], check=True)
        (g / "SESSION.md").write_text("x\n" * 120, encoding="utf-8")
        sp.run(["git", "-C", str(g), "add", "SESSION.md"], check=True)
        w = staged_warnings(g, "SESSION.md", None, 1200, WARN_FILE_KB, {"staged-repo/SESSION.md": (100, 200)})
        check(len(w) == 1 and "120 行" in w[0], "--staged: LINE_LIMITS に登録した file は行数で鳴る")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if args == ["--selftest"]:
        return selftest()
    if "--staged" in args:
        return staged_main(args)
    surface = False
    if "--surface" in args:
        surface = True
        args = [a for a in args if a != "--surface"]
    # 既定 = この repo の親 dir (= 複数 repo を並べている dir)。 個人の layout を hardcode しない
    root = Path(__file__).resolve().parent.parent.parent
    if len(args) == 2 and args[0] == "--root":
        root = Path(args[1])
    elif args:
        print("usage: check-memory-file-bloat.py [--root DIR | --surface | --selftest | --staged ...]")
        return 64
    try:
        report(scan(root), surface=surface)
    except Exception as e:  # fail-open: dashboard を殺さない
        print(f"(check-memory-file-bloat: 検査不能 = {e.__class__.__name__}: {e} — fail-open)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
