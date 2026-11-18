#!/usr/bin/env python3
"""generate-trigger-table.py — 全文の markdown table (源) から、 auto-load 面に置く「trigger + ⚠️ だけ」 の表を marker の間に生成する (--write / --check / --selftest)

層1 engine (2026-10-04)。 「いつ何を読むか」 の routing table (1 列目 = 規約の名、 2 列目 = file の link、
3 列目 = 適用タイミング + 要約 + ⚠️) は、 毎 session auto-load される CLAUDE.md に置くと 3 列目に要約と経緯が
溜まって育つ (実測 62 行 32 KB、 うち 3 列目 26 KB)。 memory-file-slimming.md の「routing table は trigger 列こそが
routing 機能、 digest は drift する複製」 を**生成契約**にする: 源の表は auto-load されない file に全文で置き、
CLAUDE.md には marker の間に **1 列目 / 2 列目 / 3 列目の 1 文目 (= trigger) + ⚠️ を含む文** だけを機械で写す。
要約・経緯の文は源にだけ在る (= 行を足す人が何を書いても auto-load 面には trigger と ⚠️ しか出ない)。

3 列目の縮め方 (決定的・機械的、 文は 1 字も変えない):
  「。」 の直後の空白で文に分け、 1 文目と ⚠️ を含む文を元の順で残す。 「。」 の無い cell はそのまま。
  ⚠️ を残すのは、 表の ⚠️ が「読む前に知っておく行動制約」 として置かれたものだから (経緯は ⚠️ を含まない)。
  括弧 (丸括弧・〔〕・「」 など) の中の「。」 + 空白でも文は切れる。 切れ目の片側だけが残ると、 生成した行に
  閉じない括弧が残る (実測)。 その切れ目は --write / --check のたびに行の名と前後の抜粋を ⚠️ で出す
  (終了値は変えない = 警告だけ。 直し方 = 源の括弧の中の「。」 を「、」 にする)。 code span (`…`) の中の括弧は数えない。

marker (target の中、 手編集禁止):
  <!-- AUTO-TABLE:<name> BEGIN ... -->
  …生成した表…
  <!-- AUTO-TABLE:<name> END -->

usage:
  generate-trigger-table.py --source SRC.md --target TARGET.md --name NAME --write   # 再生成 (in place)
  generate-trigger-table.py --source SRC.md --target TARGET.md --name NAME --check   # 比較、 drift = exit 1、 源の不備 = exit 2
  generate-trigger-table.py --selftest

源の表 = SRC の最初の markdown table (header 行 + 区切り + 行)。 3 列未満の行は exit 2 で止める。
相対 link は SRC の dir から TARGET の dir への相対に書き直す (relink)。 生成の結果を本物の TARGET に書かずに
候補として作るとき (保護された file を別の窓が当てる前の候補など) は、 SRC と TARGET を repo と同じ相対の配置で
一時 dir に写してから回す (TARGET だけを一時 dir に置くと、 link が一時 dir からの path に化けた = 実測)。
public-safe / stdlib only。 path は呼び手 (利用者の shim) が渡す。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

SENT_SPLIT = re.compile(r"(?<=。)\s+")


def read_table(src: Path) -> tuple[str, str, list[list[str]]]:
    """(header 行, 区切り行, [cells]) を返す。 行は ' | ' で分け、 3 列目以降は 1 つに戻す。"""
    header = sep = None
    rows = []
    for line in src.read_text(encoding="utf-8").split("\n"):
        if not line.startswith("|"):
            if header is not None and rows:
                break
            continue
        if re.match(r"^\|[-\s|:]+\|?\s*$", line):
            sep = line
            continue
        if header is None:
            header = line
            continue
        if sep is None:
            raise SystemExit(f"源の表に区切り行が無い: {src}")
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) < 3:
            raise SystemExit(f"源の表に 3 列未満の行: {line[:60]!r}")
        rows.append([cells[0], cells[1], " | ".join(cells[2:])])
    if header is None or sep is None:
        raise SystemExit(f"源に markdown table が無い: {src}")
    return header, sep, rows


def compact(cell: str) -> str:
    parts = SENT_SPLIT.split(cell.strip())
    keep = [p for i, p in enumerate(parts) if i == 0 or "⚠️" in p]
    return " ".join(keep)


BRACKET_PAIRS = {"(": ")", "（": "）", "〔": "〕", "「": "」", "『": "』", "【": "】"}
CLOSERS = set(BRACKET_PAIRS.values())


def broken_splits(cell: str) -> list[str]:
    """compact が括弧の中で文を切り、 切れ目の片側だけを残す所 (= 生成した行に閉じない括弧が残る所) の前後の抜粋を返す。

    切れ目の両側が残る (どちらも ⚠️ を含む) か両側が落ちるなら、 生成した行の括弧は壊れないので数えない。
    code span (`…`) の中の括弧は数えない。 閉じ括弧は stack の頭と対になるときだけ外す (対にならない閉じは無視)。"""
    text = cell.strip()
    parts = SENT_SPLIT.split(text)
    if len(parts) < 2:
        return []
    kept = [i == 0 or "⚠️" in p for i, p in enumerate(parts)]
    cuts = [m.start() for m in SENT_SPLIT.finditer(text)]
    want = set(cuts)
    depth_at = {}
    stack: list[str] = []
    in_code = False
    for i, ch in enumerate(text):
        if i in want:
            depth_at[i] = len(stack)
        if ch == "`":
            in_code = not in_code
        elif in_code:
            continue
        elif ch in BRACKET_PAIRS:
            stack.append(BRACKET_PAIRS[ch])
        elif ch in CLOSERS and stack and stack[-1] == ch:
            stack.pop()
    out = []
    for k, pos in enumerate(cuts):
        if depth_at.get(pos, 0) > 0 and kept[k] != kept[k + 1]:
            out.append(text[max(0, pos - 24):pos + 24].replace("\n", " "))
    return out


LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def relink(cell: str, src_dir: Path, dst_dir: Path) -> str:
    """源の file から見た相対 link を、 target の file から見た相対 link に付け替える (源と target の dir が違うとき)。
    http(s) / mailto / `#anchor` だけ / 絶対 path はそのまま。 `path#anchor` の anchor は残す。"""
    if src_dir.resolve() == dst_dir.resolve():
        return cell

    def fix(m):
        tgt = m.group(1)
        if re.match(r"^(?:[a-z]+:|#|/|~)", tgt):
            return m.group(0)
        path, _, anchor = tgt.partition("#")
        rel = os.path.relpath(os.path.normpath(src_dir / path), dst_dir).replace(os.sep, "/")
        return f"]({rel}{'#' + anchor if anchor else ''})"

    return LINK_RE.sub(fix, cell)


def render(header: str, sep: str, rows: list[list[str]], name: str, src: Path, target: Path) -> str:
    begin = (f"<!-- AUTO-TABLE:{name} BEGIN (generate-trigger-table.py --write が生成 — 手編集禁止、 同期検査 = --check、"
             f" 源 = {src.name} 〔全文〕。 表示 = 3 列目の 1 文目 〔trigger〕 + ⚠️ の文だけ、 要約・経緯は源) -->")
    end = f"<!-- AUTO-TABLE:{name} END -->"
    sd, dd = src.parent, target.parent
    body = "\n".join(f"| {relink(a, sd, dd)} | {relink(b, sd, dd)} | {relink(compact(c), sd, dd)} |" for a, b, c in rows)
    return f"{begin}\n{header}\n{sep}\n{body}\n{end}"


def splice(target_text: str, name: str, block: str) -> str:
    pat = re.compile(rf"<!-- AUTO-TABLE:{re.escape(name)} BEGIN.*?<!-- AUTO-TABLE:{re.escape(name)} END -->", re.S)
    if not pat.search(target_text):
        raise SystemExit(f"target に AUTO-TABLE:{name} の marker が無い")
    return pat.sub(lambda _m: block, target_text, count=1)


def run(src: Path, target: Path, name: str, write: bool) -> int:
    try:
        header, sep, rows = read_table(src)
        block = render(header, sep, rows, name, src, target)
        old = target.read_text(encoding="utf-8")
        new = splice(old, name, block)
    except SystemExit as e:
        print(f"❌ {e}")
        return 2
    for a, _b, c in rows:
        for ex in broken_splits(c):
            print(f"⚠️ 括弧の中の「。」 で文が切れ、 生成した行に閉じない括弧が残る: 行「{a}」 … {ex} …"
                  f" (直し方 = 源 {src.name} の括弧の中の「。」 を「、」 にする)")
    if new == old:
        print(f"✅ {target.name} AUTO-TABLE:{name}: in sync ({len(rows)} 行、 {len(block.encode('utf-8'))} B)")
        return 0
    if write:
        target.write_text(new, encoding="utf-8")
        print(f"📝 {target.name} AUTO-TABLE:{name}: regenerated ({len(rows)} 行、 {len(block.encode('utf-8'))} B、"
              f" file {len(old.encode('utf-8'))} → {len(new.encode('utf-8'))} B)")
        return 0
    print(f"❌ {target.name} AUTO-TABLE:{name}: OUT OF SYNC — python3 {Path(__file__).name} … --write で再生成")
    return 1


def selftest() -> int:
    import shutil
    import subprocess
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="gtt-selftest-"))
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and cond

    try:
        src = tmp / "required-reading.md"
        tgt = tmp / "CLAUDE.md"
        row1 = "| メール文体 | [`email-style.md`](email-style.md) | **メール下書き作成前に必ず読む** (= 他人名義も)。 宛名・署名の SoT。 ⚠️ 引用は cite-me 禁止。 旧全文 = archive |"
        row2 = "| 研究文献 | [`refs.md`](refs.md) | **物理研究系リポで文献引用時**。正本は refs.yaml |"
        row3 = "| 口コミ | 層1 [`c.md`](../c.md) | **評価を起草する前** | 余分な列 |"
        src.write_text(f"# 源\n\n前置き。\n\n| 規約 | ファイル | 適用タイミング |\n|---|---|---|\n{row1}\n{row2}\n{row3}\n\n後文の表ではない行\n", encoding="utf-8")
        tgt.write_text("# t\n\n### 一覧\n\n<!-- AUTO-TABLE:rr BEGIN (old) -->\nstale\n<!-- AUTO-TABLE:rr END -->\n\n後。\n", encoding="utf-8")
        check(compact("**A**。 B。 ⚠️ C。 D") == "**A**。 ⚠️ C。", "compact: 1 文目 + ⚠️ の文")
        check(compact("**A**。B。") == "**A**。B。", "compact: 「。」 の後に空白が無ければ分けない")
        check(compact("文のない cell") == "文のない cell", "compact: 「。」 が無ければそのまま")
        h, s, rows = read_table(src)
        check(h.startswith("| 規約 |") and len(rows) == 3 and rows[2][2] == "**評価を起草する前** | 余分な列", "read_table: header / 3 行 / 4 列目は 3 列目に戻す")
        r = subprocess.run([sys.executable, __file__, "--source", str(src), "--target", str(tgt), "--name", "rr", "--check"],
                           capture_output=True, text=True)
        check(r.returncode == 1 and "OUT OF SYNC" in r.stdout, "--check: stale なら rc 1")
        r = subprocess.run([sys.executable, __file__, "--source", str(src), "--target", str(tgt), "--name", "rr", "--write"],
                           capture_output=True, text=True)
        t = tgt.read_text(encoding="utf-8")
        check(r.returncode == 0 and "| メール文体 | [`email-style.md`](email-style.md) | **メール下書き作成前に必ず読む** (= 他人名義も)。 ⚠️ 引用は cite-me 禁止。 |" in t,
              "--write: 行を trigger + ⚠️ に縮めて marker の間に書く")
        check("宛名・署名の SoT" not in t and "stale" not in t and t.startswith("# t\n\n### 一覧\n\n<!-- AUTO-TABLE:rr BEGIN")
              and t.endswith("<!-- AUTO-TABLE:rr END -->\n\n後。\n"), "--write: 要約は出ない、 marker の外は不変")
        check("| 研究文献 | [`refs.md`](refs.md) | **物理研究系リポで文献引用時**。正本は refs.yaml |" in t, "--write: 空白の無い「。」 は分けない")
        r = subprocess.run([sys.executable, __file__, "--source", str(src), "--target", str(tgt), "--name", "rr", "--check"],
                           capture_output=True, text=True)
        check(r.returncode == 0 and "in sync" in r.stdout, "--check: 再生成後は rc 0")
        src.write_text(src.read_text(encoding="utf-8") + "| 壊れた行 | 2 列だけ |\n", encoding="utf-8")
        # 表の直後に追記したので表の一部として読まれる → 3 列未満 = exit 2 … ただし後文の後なので表は終わっている
        r = subprocess.run([sys.executable, __file__, "--source", str(src), "--target", str(tgt), "--name", "rr", "--check"],
                           capture_output=True, text=True)
        check(r.returncode == 0, "表の後の無関係な行は読まない (後文で表が終わる)")
        src.write_text(f"| a | b |\n|---|---|\n| x | y |\n", encoding="utf-8")
        r = subprocess.run([sys.executable, __file__, "--source", str(src), "--target", str(tgt), "--name", "rr", "--check"],
                           capture_output=True, text=True)
        check(r.returncode == 2 and "3 列未満" in r.stdout, "源に 3 列未満の行 = exit 2")
        tgt.write_text("# no marker\n", encoding="utf-8")
        src.write_text(f"| 規約 | ファイル | 適用タイミング |\n|---|---|---|\n{row2}\n", encoding="utf-8")
        r = subprocess.run([sys.executable, __file__, "--source", str(src), "--target", str(tgt), "--name", "rr", "--check"],
                           capture_output=True, text=True)
        check(r.returncode == 2 and "marker が無い" in r.stdout, "target に marker が無い = exit 2")
        # 源が sub dir のとき、 生成した表の相対 link は target の dir から見た形に付け替える (anchor は残す、 http / # だけ はそのまま)
        sub = tmp / "conventions"
        sub.mkdir()
        src2 = sub / "src.md"
        src2.write_text("| 規約 | ファイル | 適用タイミング |\n|---|---|---|\n"
                        "| A | [`a.md`](../a.md#x) | **読む** [b](../../other/b.md) [h](https://e.invalid/p) [i](#only)。 要約 |\n", encoding="utf-8")
        tgt.write_text("<!-- AUTO-TABLE:rr BEGIN -->\n<!-- AUTO-TABLE:rr END -->\n", encoding="utf-8")
        r = subprocess.run([sys.executable, __file__, "--source", str(src2), "--target", str(tgt), "--name", "rr", "--write"],
                           capture_output=True, text=True)
        t = tgt.read_text(encoding="utf-8")
        check(r.returncode == 0 and "[`a.md`](a.md#x)" in t and "[b](../other/b.md)" in t and "(https://e.invalid/p)" in t and "(#only)" in t,
              "源が sub dir: 相対 link を target の dir から見た形に (anchor 保持、 http / #only は不変)")
        check(relink("x [a](a.md)", Path("/r/c"), Path("/r/c")) == "x [a](a.md)", "relink: 同じ dir なら不変")
        # 括弧の中の「。」 で切れて片側だけ残る所を警告する (実測 = 生成した行に閉じない括弧が残った)
        check(len(broken_splits("**A** (= x。 y)。 B")) == 1, "broken_splits: 丸括弧の中で切れて後ろが落ちる = 1 件")
        check(broken_splits("**A** (= x、 y)。 B") == [], "broken_splits: 括弧の中が「、」 なら 0 件")
        check(broken_splits("**A**。 ⚠️ C (p。 ⚠️ q)。 D") == [], "broken_splits: 切れ目の両側が残るなら 0 件")
        check(broken_splits("**A**。 要約 (p。 q)。 D") == [], "broken_splits: 切れ目の両側が落ちるなら 0 件")
        check(len(broken_splits("**A**。 ⚠️ C 「p。 q」。 D")) == 1, "broken_splits: 「」 の中でも数える")
        check(len(broken_splits("**A**。 要約 (p。 ⚠️ q)。")) == 1, "broken_splits: 前が落ちて後ろが残る (閉じだけ残る) も 1 件")
        check(broken_splits("**A** `(x`。 B") == [], "broken_splits: code span の中の括弧は数えない")
        check(broken_splits("**A**") == [], "broken_splits: 切れ目が無ければ 0 件")
        src3 = tmp / "src3.md"
        src3.write_text("| 規約 | ファイル | 適用タイミング |\n|---|---|---|\n"
                        "| 壊れ | [`a.md`](a.md) | **読む** (= x。 y)。 要約 |\n", encoding="utf-8")
        tgt.write_text("<!-- AUTO-TABLE:rr BEGIN -->\n<!-- AUTO-TABLE:rr END -->\n", encoding="utf-8")
        r = subprocess.run([sys.executable, __file__, "--source", str(src3), "--target", str(tgt), "--name", "rr", "--write"],
                           capture_output=True, text=True)
        check(r.returncode == 0 and "⚠️ 括弧の中の「。」" in r.stdout and "行「壊れ」" in r.stdout,
              "--write: 括弧の中で切れる行を ⚠️ で出す (終了値は 0 のまま)")
        r = subprocess.run([sys.executable, __file__, "--source", str(src3), "--target", str(tgt), "--name", "rr", "--check"],
                           capture_output=True, text=True)
        check(r.returncode == 0 and "⚠️ 括弧の中の「。」" in r.stdout, "--check: 同期していても括弧の警告は出す")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    a = sys.argv[1:]
    if a == ["--selftest"]:
        return selftest()
    opts = {}
    it = iter(a)
    mode = None
    for tok in it:
        if tok in ("--source", "--target", "--name"):
            opts[tok[2:]] = next(it, "")
        elif tok in ("--write", "--check"):
            mode = tok
        else:
            print(__doc__.split("usage:", 1)[-1])
            return 64
    if not all(k in opts for k in ("source", "target", "name")) or mode is None:
        print(__doc__.split("usage:", 1)[-1])
        return 64
    return run(Path(opts["source"]), Path(opts["target"]), opts["name"], mode == "--write")


if __name__ == "__main__":
    sys.exit(main())
