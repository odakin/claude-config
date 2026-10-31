#!/usr/bin/env python3
"""memory-budget-pay.py — 予算 gate に止められた memory file (CLAUDE.md) の「払い」 を 1 コマンドにする (余裕の表示 / 候補の順位 / 1 行の退避 / entry の graduate)

層1 engine (2026-10-04)。 commit 時の予算 gate (check-memory-file-bloat.py --staged --block) は
「予算以上 ∧ HEAD より育つ commit」 を止め、 止まった側に「足す分を同じ commit で MOVE + pointer 化して払う」
を求める。 実測 (2026-09-23〜10-04、 1 台の記録) では止められた 12 回のうち払ったのは 1 回で、 残りは追記を
取り下げる・短く削って通す、 だった。 払う操作 (どの行を・どこへ・verbatim で・link を直して・検算して) に
道具が無く、 止めた画面は 28 KB の手順 doc を指していたのが直接の原因 (RCA = 個人層の plan)。
本 script はその「払い」 の帳簿作業を 1 コマンドにする。 **何を残すか (live な行動制約と routing) を決めるのは
呼び手 (agent) で、 道具は決めない** — 道具が持つのは、 一意 prefix の 1 行置換・旧全文の archive への verbatim
退避・link の深さの付け替え・検算・余裕の表示だけ。

subcommand:
  status      --file F [--budget-kb N] [--target-kb T]
              今の byte / HEAD の byte / 予算 (block 線) までの余裕 / 余裕の目安 (予算 − T KB) まで、 を 1 画面で。
              止められた直後に打つ (予算の値は check-memory-file-bloat.py の BLOCK_FILE_KB を読む、 --budget-kb で上書き)。
  candidates  --file F [--top N] [--section '### 見出し'] [--min-bytes B]
              unit (markdown table の row / bullet / 番号付き項目 = 1 行) を「経緯 payload」 (日付・RCA・実測・旧全文・
              経緯・起源・本人の発言の引用を含む括弧) の byte の多い順に並べる。 payload は「落としても規則が
              変わらない可能性が高い部分」 の候補であって判定ではない = 行を読んで決める。 床 (~800 B) 超えの行は印。
  retreat     --file F --prefix P --new-file NEW --archive A [--heading H] [--reason R] [--dry-run]
              P で始まる行がちょうど 1 行であることを assert し、 NEW (file、 1 行) に置換。 旧行は A の H 節
              (無ければ末尾に作る。 既定 = 「## <F の名> pointer 化退避 (<今日> — <R>)」) に
              「### <unit の頭>  (<今日> まで、 verbatim)」 + 旧行、 で verbatim 追記。 F と A の dir が違えば
              link の深さを fix-md-links.py で付け替える。 書いた後に旧行が A に在ることを検算し、 byte の差と
              予算までの余裕を出す。 NEW が旧行より長ければ警告 (払いになっていない)。
  graduate    --file F --prefix P --archive A [--heading H] [--carrier TEXT] [--dry-run]
              bullet の 1 行を丸ごと A へ MOVE (完了 / 受領済の entry 用)。 義務語彙 (残 / 未 / 待ち / 次 / 保留 /
              TODO …) の hit を列挙し、 --carrier (その義務を運ぶ TODO / plan / 機械 surface の名) が無ければ
              dry-run に留める (= 義務を運ぶ entry は graduate しない、 memory-file-slimming.md#obligation-carrier-graduation)。
  --selftest  tempdir fixture (実 repo 非依存)。

設計:
  - 置換・移動の単位は 1 行だけ (= CLAUDE.md の table row / bullet は 1 行に書かれている)。 複数行の block は
    fold-dated-bullets.py / migrate-session-shape.py の領分。
  - prefix は literal startswith、 一致 0 / 2+ は書かずに exit 1 (replace-line.py と同じ契約)。
  - 道具は中身を要約しない (= 要約は LLM の判断で、 間違えると規則が消える)。 NEW は呼び手が書く。
  - archive への追記は append-only。 archive 側の既存行は触らない。
  - fail-closed: 検算に落ちたら両 file を書く前の内容に戻す (同一 process 内で連続 write、 途中状態を残さない)。
  - 予算の値はここに持たない (check-memory-file-bloat.py が唯一の持ち主、 正規表現で読む。 import しない =
    stale .pyc を掴まない)。

退避先の形 (= 個人層の archive の既存の形に合わせる):
  ## <F の名> pointer 化退避 (<YYYY-MM-DD> — <reason>)

  ### <unit の頭 40 字> (<YYYY-MM-DD> まで、 verbatim)

  <旧行>

public-safe / stdlib only。 個人の path・repo 名は持たない (呼び手の shim が既定値を渡す)。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLOAT_ENGINE = HERE / "check-memory-file-bloat.py"
FIX_LINKS = HERE / "fix-md-links.py"
DEFAULT_TARGET_KB = 8  # 余裕の目安 = 予算 − 8 KB (実測 1 日 ~1.5-2.3 KB 育つ → 4-5 日分。 値の根拠は個人層の RCA)
FLOOR_BYTES = 800  # pointer 化の床 (memory-file-slimming.md 実測 ~700-800 B)
PAREN_RE = re.compile(r"[（(〔][^()（）〔〕]*[)）〕]")
PAYLOAD_KEY_RE = re.compile(
    r"20\d\d-\d\d(?:-\d\d)?|RCA|実測|旧全文|経緯|起源|本人「|user ?「|第[一二三四五六七八九十]+弾|までは|以前"
)
OBLIGATION_RE = re.compile(
    r"残|未実装|未着手|未確認|未決|判断待ち|green-light|次 ?session|保留|待ち|次 =|次の一手|TODO|carrier"
)
UNIT_RE = re.compile(r"^(\| |- |\d+\. |   \| |  - )")  # table row / bullet / 番号付き (inline の表はインデント 3)


def read_budget_kb() -> int | None:
    try:
        m = re.search(r"^BLOCK_FILE_KB\s*=\s*(\d+)", BLOAT_ENGINE.read_text(encoding="utf-8"), re.M)
        return int(m.group(1)) if m else None
    except OSError:
        return None


def head_bytes(path: Path) -> int | None:
    try:
        top = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        rel = os.path.relpath(path.resolve(), Path(top).resolve())
        r = subprocess.run(["git", "-C", top, "show", f"HEAD:{rel}"], capture_output=True)
        return len(r.stdout) if r.returncode == 0 else None
    except (subprocess.CalledProcessError, OSError, ValueError):
        return None


def nbytes(s: str) -> int:
    return len(s.encode("utf-8"))


def fmt_kb(b: int) -> str:
    return f"{b / 1024:.1f} KB"


def payload_of(line: str) -> tuple[int, list[str]]:
    hits = [m.group(0) for m in PAREN_RE.finditer(line) if PAYLOAD_KEY_RE.search(m.group(0))]
    return sum(nbytes(h) for h in hits), hits


def unit_head(line: str, n: int = 40) -> str:
    """unit の頭 (archive の小見出し用): 行頭の記号 (| - > 番号) と装飾 (** ` link の括弧) を外した先頭 n 字。"""
    s = line.strip().lstrip("|").lstrip("-").lstrip(">").strip()
    s = re.sub(r"^\d+\.\s*", "", s)
    s = s.split(" | ")[0] if line.lstrip().startswith("|") else s
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = s.replace("**", "").replace("`", "")
    return s[:n]


# ---------------------------------------------------------------- status
def cmd_status(a) -> int:
    f = Path(a.file)
    text = f.read_text(encoding="utf-8")
    size = nbytes(text)
    budget_kb = a.budget_kb or read_budget_kb()
    head = head_bytes(f)
    print(f"{f}: {size} B ({fmt_kb(size)})" + (f"、 HEAD = {head} B ({size - head:+d} B)" if head is not None else ""))
    if budget_kb is None:
        print("予算の値が読めない (check-memory-file-bloat.py の BLOCK_FILE_KB) — --budget-kb で渡す")
        return 3
    block_b = budget_kb * 1024
    target_b = block_b - a.target_kb * 1024
    room = block_b - size
    if room > 0:
        print(f"予算 {budget_kb} KB (= {block_b} B) まで余裕 {room} B — 育つ commit は {room} B 未満なら通る")
    else:
        print(f"予算 {budget_kb} KB (= {block_b} B) を {-room} B 超過 — HEAD より育つ commit は止まる (縮める commit は通る)")
    if size > target_b:
        print(f"余裕の目安 (予算 − {a.target_kb} KB = {target_b} B) まで {size - target_b} B 払うと、 当分は止まらない")
    else:
        print(f"余裕の目安 (予算 − {a.target_kb} KB) の内側 ({target_b - size} B の余裕)")
    print("候補 = `candidates --file ...`、 払う = `retreat --file ... --prefix '<行頭>' --new-file <新しい行> --archive <archive>`")
    return 0


# ---------------------------------------------------------------- candidates
def iter_units(lines: list[str]):
    section = ""
    for i, l in enumerate(lines, 1):
        if l.startswith("#"):
            section = l.strip()
            continue
        if UNIT_RE.match(l) and not re.match(r"^\s*\|[-\s|]+\|?\s*$", l):
            yield i, section, l


def cmd_candidates(a) -> int:
    lines = Path(a.file).read_text(encoding="utf-8").split("\n")
    rows = []
    for i, section, l in iter_units(lines):
        if a.section and not section.startswith(a.section):
            continue
        b = nbytes(l)
        if b < a.min_bytes:
            continue
        pb, hits = payload_of(l)
        rows.append((pb, b, i, section, l, hits))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    print(f"{len(rows)} unit (section filter = {a.section or 'なし'})、 経緯 payload の多い順に {a.top} 件:")
    print("  行    byte  payload  床  見出し / unit の頭 … payload の例")
    for pb, b, i, section, l, hits in rows[: a.top]:
        floor = "超" if b > FLOOR_BYTES else "  "
        ex = " / ".join(h[:38] for h in hits[:2])
        print(f"  {i:4d} {b:6d} {pb:7d}  {floor}  [{section[:18]}] {unit_head(l)} … {ex}")
    tot = sum(r[0] for r in rows)
    print(f"payload 合計 = {tot} B (= 落として規則が変わらない可能性の高い部分の上限。 候補であって判定ではない)")
    return 0


# ---------------------------------------------------------------- retreat / graduate (shared)
def _unique_line(lines: list[str], prefix: str) -> int:
    idx = [i for i, l in enumerate(lines) if l.startswith(prefix)]
    if len(idx) != 1:
        raise SystemExit(f"prefix に一致する行が {len(idx)} 行 (ちょうど 1 行が要る) — prefix を長く: {prefix[:60]!r}")
    return idx[0]


def _archive_block(file_name: str, old: str, today: str, reason: str, heading: str | None, note: str | None) -> tuple[str, str]:
    h = heading or f"## {file_name} pointer 化退避 ({today} — {reason})"
    sub = f"### {unit_head(old)} ({today} まで、 verbatim)"
    body = (f"\n{sub}\n\n" + (f"判定: {note}\n\n" if note else "") + old + "\n")
    return h, body


def _append_under_heading(archive_text: str, heading: str, body: str) -> str:
    lines = archive_text.split("\n")
    idx = next((i for i, l in enumerate(lines) if l.strip() == heading.strip()), None)
    if idx is None:
        base = archive_text.rstrip("\n") + "\n" if archive_text else ""
        return base + f"\n{heading}\n" + body
    level = len(heading) - len(heading.lstrip("#"))
    end = len(lines)
    for j in range(idx + 1, len(lines)):
        h = len(lines[j]) - len(lines[j].lstrip("#"))
        if h and lines[j][h:h + 1] == " " and h <= level:
            end = j
            break
    while end > idx + 1 and lines[end - 1].strip() == "":
        end -= 1
    # body は改行で終わり、 lines[end:] は節の後ろの空行 (と次の節) = そのまま繋ぐ。 間に "\n" を足すと足すたびに空行が 1 行増える
    return "\n".join(lines[:end]) + "\n" + body + "\n".join(lines[end:])


def _fix_links_if_needed(src: Path, archive: Path, dry: bool) -> str:
    if src.resolve().parent == archive.resolve().parent:
        return "同じ dir = link の深さはそのまま"
    if not FIX_LINKS.is_file():
        return f"⚠️ dir が違うが {FIX_LINKS.name} が無い — 相対 link を手で確かめる"
    if dry:
        return f"dir が違う → 書いた後に {FIX_LINKS.name} --files {archive} --fix を回す"
    r = subprocess.run([sys.executable, str(FIX_LINKS), "--files", str(archive), "--fix"],
                       capture_output=True, text=True, cwd=str(archive.parent))
    return f"{FIX_LINKS.name} --fix: rc={r.returncode} " + (r.stdout or r.stderr).strip()[-200:]


def _normalize_links(s: str) -> str:
    return re.sub(r"\]\((?:\.\./)+", "](", s)


def _write_pair(src: Path, new_src: str, archive: Path, new_arc: str, old_line: str):
    old_src = src.read_text(encoding="utf-8")
    old_arc = archive.read_text(encoding="utf-8") if archive.exists() else None
    archive.write_text(new_arc, encoding="utf-8")
    src.write_text(new_src, encoding="utf-8")
    ok = old_line in archive.read_text(encoding="utf-8") or _normalize_links(old_line) in _normalize_links(
        archive.read_text(encoding="utf-8"))
    if not ok:  # fail-closed: 戻す
        src.write_text(old_src, encoding="utf-8")
        if old_arc is None:
            archive.unlink()
        else:
            archive.write_text(old_arc, encoding="utf-8")
        raise SystemExit("検算に失敗 (旧行が archive に見つからない) — 両 file を書く前に戻した")


def _report_size(src: Path, before: int, a) -> None:
    after = nbytes(src.read_text(encoding="utf-8"))
    budget_kb = getattr(a, "budget_kb", None) or read_budget_kb()
    line = f"{src.name}: {before} → {after} B ({after - before:+d} B)"
    if budget_kb:
        room = budget_kb * 1024 - after
        line += f"、 予算 {budget_kb} KB まで余裕 {room} B" if room > 0 else f"、 予算 {budget_kb} KB を {-room} B 超過 (縮める commit は通る)"
    print(line)


def cmd_retreat(a) -> int:
    src, archive = Path(a.file), Path(a.archive)
    text = src.read_text(encoding="utf-8")
    lines = text.split("\n")
    i = _unique_line(lines, a.prefix)
    old = lines[i]
    new = Path(a.new_file).read_text(encoding="utf-8").rstrip("\n") if a.new_file != "-" else sys.stdin.read().rstrip("\n")
    if "\n" in new:
        raise SystemExit("--new-file は 1 行 (複数行の置換はこの道具の領分でない)")
    if not new.strip():
        raise SystemExit("--new-file が空 — 行を消すなら graduate")
    today = _dt.date.today().isoformat()
    heading, body = _archive_block(src.name, old, today, a.reason, a.heading, None)
    arc_text = archive.read_text(encoding="utf-8") if archive.exists() else ""
    new_arc = _append_under_heading(arc_text, heading, body)
    lines[i] = new
    new_src = "\n".join(lines)
    before = nbytes(text)
    delta = nbytes(new) - nbytes(old)
    print(f"行 {i + 1}: {nbytes(old)} → {nbytes(new)} B ({delta:+d} B)" + ("  ⚠️ 長くなっている = 払いになっていない" if delta >= 0 else ""))
    print(f"退避先: {archive} の「{heading}」 の下に「{body.strip().splitlines()[0]}」 + 旧行 verbatim")
    print(_fix_links_if_needed(src, archive, a.dry_run))
    if a.dry_run:
        print("(dry-run: 書いていない)")
        return 0
    _write_pair(src, new_src, archive, new_arc, old)
    if src.resolve().parent != archive.resolve().parent:
        print(_fix_links_if_needed(src, archive, False))
    _report_size(src, before, a)
    print(f"次: git add {archive} && git commit -- {src} {archive}  (旧全文の在処 = {archive.name}「{heading[3:]}」)")
    return 0


def cmd_graduate(a) -> int:
    src, archive = Path(a.file), Path(a.archive)
    text = src.read_text(encoding="utf-8")
    lines = text.split("\n")
    i = _unique_line(lines, a.prefix)
    old = lines[i]
    hits = sorted(set(OBLIGATION_RE.findall(old)))
    if hits:
        print(f"義務語彙の hit: {', '.join(hits)} — 本文の末尾まで読み、 その義務を運ぶ carrier (TODO / plan の trigger / 機械 surface) を --carrier に書く")
    if hits and not a.carrier:
        print("(carrier 未指定 = dry-run。 義務を運ぶ entry は graduate しない)")
        a.dry_run = True
    today = _dt.date.today().isoformat()
    heading = a.heading or f"## graduate 済 entry ({today} — {a.reason})"
    note = a.carrier or ("義務語彙 hit なし" if not hits else None)
    _, body = _archive_block(src.name, old, today, a.reason, heading, note)
    arc_text = archive.read_text(encoding="utf-8") if archive.exists() else ""
    new_arc = _append_under_heading(arc_text, heading, body)
    del lines[i]
    new_src = "\n".join(lines)
    before = nbytes(text)
    print(f"行 {i + 1} ({nbytes(old)} B) を {archive} の「{heading}」 へ MOVE")
    print(_fix_links_if_needed(src, archive, a.dry_run))
    if a.dry_run:
        print("(dry-run: 書いていない)")
        return 0
    _write_pair(src, new_src, archive, new_arc, old)
    if src.resolve().parent != archive.resolve().parent:
        print(_fix_links_if_needed(src, archive, False))
    _report_size(src, before, a)
    print(f"次: git add {archive} && git commit -- {src} {archive}")
    return 0


# ---------------------------------------------------------------- selftest
def selftest() -> int:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="membudget-selftest-"))
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and cond

    def run(*args, stdin=None):
        return subprocess.run([sys.executable, __file__, *args], capture_output=True, text=True, input=stdin)

    try:
        f = tmp / "CLAUDE.md"
        arc = tmp / "archive.md"
        row_a = "| tool-a | **触る前に A** (2026-09-01 RCA = plan、 実測 3 回) ⚠️ 消すな (経緯 = 第三弾) |"
        row_b = "| tool-b | **触る前に B** |"
        bul_done = "- **proj-x** — 完了 (受領済)"
        bul_live = "- **proj-y** — 残 = 本人の判断待ち、 次 = TODO 起票"
        f.write_text("# t\n\n### 制約表\n\n| 対象 | 制約 |\n|---|---|\n" + row_a + "\n" + row_b +
                     "\n\n### 現在の作業プロジェクト\n\n" + bul_done + "\n" + bul_live + "\n", encoding="utf-8")
        arc.write_text("# archive\n\n## old\n\nx\n", encoding="utf-8")
        # status
        r = run("status", "--file", str(f), "--budget-kb", "1", "--target-kb", "0")
        check(r.returncode == 0 and "余裕" in r.stdout and "1 KB" in r.stdout, "status: 予算と余裕を出す")
        # candidates
        r = run("candidates", "--file", str(f), "--top", "5")
        check(r.returncode == 0 and r.stdout.find("tool-a") < r.stdout.find("tool-b"), "candidates: payload の多い row が先")
        check("payload 合計" in r.stdout, "candidates: 合計を出す")
        r = run("candidates", "--file", str(f), "--section", "### 現在")
        check("tool-a" not in r.stdout and "proj-x" in r.stdout, "candidates: --section で絞る")
        # retreat: prefix 0 件 / 2 件
        new = tmp / "new.txt"
        new.write_text("| tool-a | **触る前に A** ⚠️ 消すな (旧全文 = archive.md) |\n", encoding="utf-8")
        r = run("retreat", "--file", str(f), "--prefix", "| tool-z", "--new-file", str(new), "--archive", str(arc))
        check(r.returncode != 0 and "0 行" in (r.stdout + r.stderr), "retreat: prefix 0 件は書かない")
        r = run("retreat", "--file", str(f), "--prefix", "| tool-", "--new-file", str(new), "--archive", str(arc))
        check(r.returncode != 0 and "2 行" in (r.stdout + r.stderr), "retreat: prefix 2 件は書かない")
        before = f.read_text(encoding="utf-8")
        r = run("retreat", "--file", str(f), "--prefix", "| tool-a", "--new-file", str(new), "--archive", str(arc),
                "--dry-run", "--reason", "試験")
        check(r.returncode == 0 and f.read_text(encoding="utf-8") == before and "dry-run" in r.stdout, "retreat: --dry-run は書かない")
        r = run("retreat", "--file", str(f), "--prefix", "| tool-a", "--new-file", str(new), "--archive", str(arc),
                "--reason", "試験", "--budget-kb", "1")
        t2, a2 = f.read_text(encoding="utf-8"), arc.read_text(encoding="utf-8")
        check(r.returncode == 0 and new.read_text(encoding="utf-8").strip() in t2 and row_a not in t2, "retreat: 1 行を置換")
        check(row_a in a2 and "pointer 化退避" in a2 and "試験" in a2 and "まで、 verbatim" in a2, "retreat: 旧行を archive の節に verbatim 追記")
        check(a2.startswith("# archive\n\n## old\n\nx\n"), "retreat: archive の既存部分は不変 (append-only)")
        check("B (-" in r.stdout and "予算" in r.stdout, "retreat: byte の差と予算までの余裕を出す")
        # 2 本目は同じ heading の下に入る (節の末尾へ)
        new.write_text("| tool-b | **B** |\n", encoding="utf-8")
        r = run("retreat", "--file", str(f), "--prefix", "| tool-b", "--new-file", str(new), "--archive", str(arc), "--reason", "試験")
        a3 = arc.read_text(encoding="utf-8")
        check(a3.count("pointer 化退避") == 1 and a3.find(row_a) < a3.find(row_b), "retreat: 同じ日の 2 本目は同じ節の末尾")
        check(not a3.endswith("\n\n"), "retreat: 同じ節に足しても末尾の空行が増えない")
        check(_append_under_heading("# a\n\n## s\n\nx\n\n## t\n\ny\n", "## s", "\n### u\n\nz\n")
              == "# a\n\n## s\n\nx\n\n### u\n\nz\n\n## t\n\ny\n", "retreat: 途中の節に足しても次の節との空行は 1 行のまま")
        # 長くなる置換は警告
        new.write_text("| tool-b | **B** " + "x" * 50 + " |\n", encoding="utf-8")
        r = run("retreat", "--file", str(f), "--prefix", "| tool-b", "--new-file", str(new), "--archive", str(arc), "--dry-run")
        check("払いになっていない" in r.stdout, "retreat: 長くなる置換は警告")
        # graduate: 義務語彙 hit → carrier 無しは dry-run
        before = f.read_text(encoding="utf-8")
        r = run("graduate", "--file", str(f), "--prefix", "- **proj-y", "--archive", str(arc), "--reason", "試験")
        check(r.returncode == 0 and f.read_text(encoding="utf-8") == before and "義務語彙" in r.stdout, "graduate: 義務語彙 hit + carrier 無しは書かない")
        r = run("graduate", "--file", str(f), "--prefix", "- **proj-y", "--archive", str(arc), "--reason", "試験",
                "--carrier", "TODO 2026-10-xx が運ぶ")
        check(r.returncode == 0 and bul_live not in f.read_text(encoding="utf-8") and bul_live in arc.read_text(encoding="utf-8")
              and "判定: TODO 2026-10-xx" in arc.read_text(encoding="utf-8"), "graduate: carrier を書けば MOVE + 判定を archive に残す")
        r = run("graduate", "--file", str(f), "--prefix", "- **proj-x", "--archive", str(arc), "--reason", "試験")
        check(r.returncode == 0 and bul_done not in f.read_text(encoding="utf-8") and bul_done in arc.read_text(encoding="utf-8"),
              "graduate: 義務語彙 hit なしはそのまま MOVE")
        check("\n\n\n" not in arc.read_text(encoding="utf-8"), "retreat・graduate を重ねても節の間の空行が増えない")
        # 別 dir の archive: 書いた後も旧行が (link 正規化で) 見つかる
        sub = tmp / "deep"
        sub.mkdir()
        arc2 = sub / "arc.md"
        f.write_text("# t\n\n- **link-row** — see [x](plans/x.md) (2026-01-01)\n", encoding="utf-8")
        new.write_text("- **link-row** — [x](plans/x.md)\n", encoding="utf-8")
        r = run("retreat", "--file", str(f), "--prefix", "- **link-row", "--new-file", str(new), "--archive", str(arc2), "--reason", "試験")
        check(r.returncode == 0 and arc2.exists() and "link-row" in arc2.read_text(encoding="utf-8"), "retreat: 別 dir の archive を新規に作れる")
        check(read_budget_kb() is not None, "予算の値を check-memory-file-bloat.py から読める")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    if sys.argv[1:] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(prog="memory-budget-pay.py", description=__doc__.split("\n", 1)[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("status")
    p.add_argument("--file", required=True)
    p.add_argument("--budget-kb", type=int)
    p.add_argument("--target-kb", type=int, default=DEFAULT_TARGET_KB)
    p.set_defaults(fn=cmd_status)
    p = sp.add_parser("candidates")
    p.add_argument("--file", required=True)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--section")
    p.add_argument("--min-bytes", type=int, default=0)
    p.set_defaults(fn=cmd_candidates)
    for name, fn in (("retreat", cmd_retreat), ("graduate", cmd_graduate)):
        p = sp.add_parser(name)
        p.add_argument("--file", required=True)
        p.add_argument("--prefix", required=True)
        p.add_argument("--archive", required=True)
        p.add_argument("--heading")
        p.add_argument("--reason", default="予算の支払い")
        p.add_argument("--budget-kb", type=int)
        p.add_argument("--dry-run", action="store_true")
        if name == "retreat":
            p.add_argument("--new-file", required=True, help="新しい 1 行の file ('-' = stdin)")
        else:
            p.add_argument("--carrier", help="義務を運ぶ carrier の名 (無ければ義務語彙 hit 時は dry-run)")
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
