#!/usr/bin/env python3
"""check-message-amounts.py — git-crypt で中身を暗号化する repo の commit message に、 金額・為替レートを平文で入れさせない: commit gate (--commit-msg / --text-file、 違反で exit 1) + 過去の message の replay (--replay、 報告だけ)。

## なぜ要るか

git-crypt は file の中身しか暗号化しない。 file 名・commit message は平文のまま remote に載る
(一般則 = conventions/confidential-repo-boundary.md §1)。 金額を暗号化される台帳・TODO に書いても、
同じ turn の commit message の 1 行目に額やレートを要約として書けば、 そこで平文になる。
agent は暗号化した台帳を更新した commit の要約に、 額やレートをそのまま書く (実測)。
人名・学生の識別子の網だけでは、 金額は止まらない。

## 何を見るか (1 つでも当たれば BLOCK)

  円         数 + 円 (万円・億円・千円を含む)。 「円盤」「円周」「円ターゲット」 のような形の語と、
             言い回しの「1 円も (変わらない)」 は外す
  通貨記号   ¥ ￥ € £ + 数、 $ + 2 桁以上か小数か桁の語 (k / M / B / 万 …)。 TeX の数式 ($3.1$ / $0.5^\\circ$) と
             shell の位置引数 ($1) は外す
  通貨コード USD・EUR・JPY ほか + 3 桁以上か小数か桁区切り (前後どちらでも)。 件数の単位が続く形 (「AUD 3 件」
             「42 USD bonds」) と 2 桁以下の整数 (通貨ごとの件数の並び「GBP 12, CHF 11」) は外す
  通貨の語   数 + ドル・ユーロ・ポンド・フラン・ウォン・人民元 … (後ろにカタカナが続く形 = 「フランス」 は外す)
  レート     「1 ドル = …」「USD/JPY …」「ドル円 …」「レート 123.45」「123.45 で両替」 の形 (レートの語の後は
             小数 = 「frame rate: 60」「RATE = 1/9」 は当てない)
  万・億     数 + 万 / 億 で、 円も件数の単位 (行・字・件・回・人・倍・B …) も続かない形 (例: 予算の「50 万」)
  3 桁区切り 1,234 / 12,345,678 の形で、 件数の単位が続かず、 **同じ行に金額の語 (費・額・予算・謝礼・精算 …) が
             あるか、 同じ message の別の行で上の規則が当たった** とき。 3 桁区切りの数は件数・byte 数・行数にも
             使うので、 単独では止めない (実測: 単独で止めると、 件数・byte 数で鳴る分が、 拾える額より多い。
             引き換えに、 金額の語の無い行の額は取りこぼす)

trailer の行 (Co-Authored-By: / Agent-Session: …) と # で始まる行は見ない。 当たった値は出さない (行番号と規則の名前だけ)。

## どの repo で止めるか (--scope、 既定 auto)

  auto = repo の .gitattributes (入れ子を含む、 git が追跡している file) に `filter=git-crypt` があるときだけ見る。
         暗号化していない repo では中身の file も平文なので、 message だけ止めても守るものが無い
  all  = repo を問わず見る (--text-file で repo の外の文を見るときも)

## 呼び方

  check-message-amounts.py --commit-msg <COMMIT_EDITMSG> [--repo DIR]   # git の commit-msg (cwd = repo の root)
  check-message-amounts.py --text-file <file> [--repo DIR] [--scope …]   # agent の hook が抽出した message を見る
  check-message-amounts.py --replay <repo>... [--replay-root DIR] [--show]  # 過去の message に当て、 repo ごとの件数
  check-message-amounts.py --selftest

  終了値: 0 = 通す / 1 = 止める (stderr の見出し `message-amounts: BLOCK`) / 3 = 読めない (呼び手は止めない =
  見出しの無い非 0 は 1 行出して通す、 runner の Stage 0 と同じ扱い)。
  1 回だけ通す: env CLAUDE_MESSAGE_AMOUNT_GUARD=0 (agent が使うのは本人の明示の指示があるときだけ =
  conventions/agent-rule-ownership.md#guard-escape-hatch。 止めた時の文面には書かない)。
  --show は当たった行を値ごと出す (手元の診断用。 出力を公開の場所に貼らない)。

python3 の標準 library だけで動く。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

HEADING = "message-amounts: BLOCK"
ENV_SKIP = "CLAUDE_MESSAGE_AMOUNT_GUARD"

TRAILER = re.compile(r"^(?:Co-Authored-By|Co-authored-by|Agent-Session|Agent-Model|Agent-Effort|Claude-Session|"
                     r"Codex-Session|Signed-off-by|Reviewed-by|Generated-by):", re.I)

# 数の後ろに来ると「金額ではない」 単位 (件数・大きさ・時間・物の数)
_UNITS = (r"B\b|KB|KiB|MB|MiB|GB|GiB|bytes?|行|字|文字|件|回|分|秒|時間|日|週|か月|ヶ月|カ月|年|枚|通|本|冊|個|人|名|語|点|"
          r"頁|ページ|箇所|か所|倍|対|種|通り|状態|光年|ターン|サンプル|杯|泊|コマ|社|台|局|曲|部|画素|ピクセル|"
          r"commits?|files?|lines?|turns?|tokens?|words?|chars?|characters?|rows?|entries|entry|items?|runs?|records?|"
          r"LOC|ms|px|pt|km|kg|ly|ls\b|bonds?|pharmacies|patterns?|messages?|calls?|steps?|points?|×|x\b")
COUNT_UNIT = re.compile(r"\s*(?:" + _UNITS + r")")

_CUR_CODES = r"USD|EUR|JPY|GBP|AUD|CAD|CHF|NZD|CNY|HKD|SGD|KRW|INR|TWD|THB|IDR|MYR|SEK|NOK|DKK|PLN|CZK|HUF|TRY|ZAR|MXN|BRL"
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"

R_YEN = re.compile(r"(?<![\d.,])(?!1\s*円も)\d[\d,.]*\s*(?:万|億|千|百)?\s*円(?![盤周形柱錐筒弧環板滑熟陣卓座心ァ-ヺー])")
R_SYM_FIXED = re.compile(r"[¥￥€£]\s?\d")
R_DOLLAR = re.compile(r"(?<![\\\w$])\$\s?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*([kKMB](?![A-Za-z])|千|万|億)?")
R_CODE = re.compile(r"\b(?:" + _CUR_CODES + r")\s?(" + _NUM + r")|(" + _NUM + r")\s?(?:" + _CUR_CODES + r")\b")
R_FOREIGN = re.compile(r"\d[\d,.]*\s*(?:万|千|百)?\s*(?:米ドル|豪ドル|加ドル|NZドル|ドル|ユーロ|ポンド|スイスフラン|フラン|"
                       r"ペソ|ランド|リラ|ウォン|人民元|ルピー)(?![ァ-ヺー])")
R_RATE = re.compile(r"1\s*(?:米ドル|ドル|USD|\$|ユーロ|EUR|ポンド|GBP)\s*[=＝]\s*\d"
                    r"|(?:USD|EUR|GBP|AUD|CAD|CHF|NZD)\s*/\s*JPY\s*[=＝:：@]?\s*\d"
                    r"|(?:ドル円|ユーロ円|ポンド円|豪ドル円)\s*[=＝:：@]?\s*\d"
                    r"|(?:レート|為替)\s*[=＝:：@]?\s*\d{2,3}\.\d{1,4}"
                    r"|\d{2,3}\.\d{1,4}\s*(?:円)?\s*で\s*(?:両替|換金|交換)")
R_MAN = re.compile(r"\d[\d.,]*\s*(?:万|億)(?!\s*円)")
R_COMMA3 = re.compile(r"(?<![A-Za-z0-9.:/_-])\d{1,3}(?:,\d{3})+(?![\d,]*\d)(?:\.\d+)?(?![A-Za-z0-9])")
MONEY_WORD = re.compile(r"円|¥|￥|\$|€|£|ドル|ユーロ|(?<!消)費|額|価格|値段|予算|執行|残高|残額|見積|決済|精算|立替|"
                        r"謝金|謝礼|料金|手数料|送料|使用料|掲載料|参加料|利用料|取消料|キャンセル料|税|支払|入金|出金|"
                        r"振込|振り込|両替|レート|為替|年俸|月額|日当|給与|俸給|手当|補助金|交付|購入|発注|領収|会費|"
                        r"財源|price|cost|fee|paid|USD|JPY|EUR")

RULE_NAMES = {"yen": "円", "symbol": "通貨記号", "code": "通貨コード", "foreign": "通貨の語", "rate": "レート",
              "man": "万・億", "comma3": "3 桁区切り"}


def _after(line: str, end: int) -> str:
    return line[end:end + 16]


def _count_unit_follows(line: str, end: int) -> bool:
    return bool(COUNT_UNIT.match(line, end))


def line_hits(line: str) -> List[str]:
    """Rules (keys of RULE_NAMES) that fire on one line, comma3 excluded (it needs context)."""
    hits: List[str] = []
    if R_YEN.search(line):
        hits.append("yen")
    sym = bool(R_SYM_FIXED.search(line))
    if not sym:
        for m in R_DOLLAR.finditer(line):
            num, suffix = m.group(1), m.group(2)
            nxt = line[m.end(1):m.end(1) + 1]
            if not suffix and nxt in ("\\", "$", "^", "_", "{"):
                continue  # TeX の数式
            if suffix or "." in num or "," in num or len(num) >= 2:
                sym = True
                break
    if sym:
        hits.append("symbol")
    for m in R_CODE.finditer(line):
        num = m.group(1) or m.group(2)
        if _count_unit_follows(line, m.end()):
            continue  # 「AUD 3 件」「42 USD bonds」 = 通貨ごとの件数
        if "." in num or "," in num or len(num) >= 3:
            hits.append("code")
            break
    if R_FOREIGN.search(line):
        hits.append("foreign")
    if R_RATE.search(line):
        hits.append("rate")
    for m in R_MAN.finditer(line):
        if not _count_unit_follows(line, m.end()):
            hits.append("man")
            break
    return hits


def comma3_hit(line: str) -> bool:
    for m in R_COMMA3.finditer(line):
        if not _count_unit_follows(line, m.end()):
            return True
    return False


def message_lines(raw: str) -> List[Tuple[int, str]]:
    out = []
    for n, line in enumerate(raw.splitlines(), 1):
        if not line.strip() or line.startswith("#") or TRAILER.match(line):
            continue
        out.append((n, line))
    return out


def check_message(raw: str) -> List[Tuple[int, List[str]]]:
    """[(line number, [rule, ...]), ...] for the lines that would block."""
    lines = message_lines(raw)
    per = [(n, line, line_hits(line)) for n, line in lines]
    other_rule_in_message = any(h for _, _, h in per)
    findings = []
    for n, line, hits in per:
        hits = list(hits)
        if comma3_hit(line) and (MONEY_WORD.search(line) or other_rule_in_message):
            hits.append("comma3")
        if hits:
            findings.append((n, hits))
    return findings


# ---------------------------------------------------------------- scope

def _git(args: List[str], cwd: Optional[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True)


def repo_root(start: Optional[str]) -> Optional[str]:
    r = _git(["rev-parse", "--show-toplevel"], start)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace").strip() or None


def uses_git_crypt(root: str) -> bool:
    """True when a tracked .gitattributes (any depth) or the working-tree root one declares filter=git-crypt."""
    paths = {".gitattributes"}
    r = _git(["ls-files", "-z", "--", ".gitattributes", ":(glob)**/.gitattributes"], root)
    if r.returncode == 0:
        paths.update(p for p in r.stdout.decode("utf-8", "replace").split("\0") if p)
    for p in paths:
        try:
            if "filter=git-crypt" in (Path(root) / p).read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def in_scope(scope: str, repo: Optional[str]) -> bool:
    if scope == "all":
        return True
    root = repo_root(repo or os.getcwd())
    return bool(root) and uses_git_crypt(root)


# ---------------------------------------------------------------- commit gate

def report_block(findings: List[Tuple[int, List[str]]], where: str) -> None:
    print(f"{HEADING} — {where}の {len(findings)} 行に金額か為替レートの形がある (値は出さない):", file=sys.stderr)
    for n, hits in findings:
        print(f"  - {n} 行目: " + "・".join(RULE_NAMES[h] for h in hits), file=sys.stderr)
    print("  この repo は git-crypt で中身を暗号化するが、 commit message は暗号化されない平文で remote に載る。\n"
          "  直し方: 額・レートは暗号化される中身 (台帳・TODO の本文) に書き、 message は操作の種類と案件の語\n"
          "          (台帳の id など) だけにして打ち直す。\n"
          "  金額でない数 (件数・byte 数・行数・版) に当たったと思ったら、 打ち直さずに持ち主に聞く。", file=sys.stderr)


def run_gate(path: str, repo: Optional[str], scope: str, where: str) -> int:
    if os.environ.get(ENV_SKIP) == "0":
        return 0
    if not in_scope(scope, repo):
        return 0
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"message-amounts: 読めない ({e.__class__.__name__}) — この commit では金額の検査が走っていない", file=sys.stderr)
        return 3
    findings = check_message(raw)
    if findings:
        report_block(findings, where)
        return 1
    return 0


# ---------------------------------------------------------------- replay

def repos_under(root: Path) -> List[Path]:
    return sorted(d for d in root.iterdir() if d.is_dir() and (d / ".git").exists())


def replay(repos: Iterable[Path], scope: str, show: bool) -> int:
    total = {"repos": 0, "commits": 0, "blocked": 0}
    for repo in repos:
        gc = uses_git_crypt(str(repo))
        if scope == "auto" and not gc:
            continue
        r = subprocess.run(["git", "-C", str(repo), "log", "--all", "--no-merges", "--format=%h%x00%B%x1e"],
                           capture_output=True, text=True, errors="replace")
        commits = blocked = 0
        rule_counts = {k: 0 for k in RULE_NAMES}
        for rec in r.stdout.split("\x1e"):
            rec = rec.strip("\n")
            if not rec:
                continue
            h, _, body = rec.partition("\x00")
            commits += 1
            findings = check_message(body)
            if findings:
                blocked += 1
                for k in {k for _, hs in findings for k in hs}:
                    rule_counts[k] += 1
                if show:
                    lines = body.splitlines()
                    for n, hs in findings:
                        print(f"    {repo.name} {h.strip()} {n}: [{','.join(hs)}] {lines[n - 1][:160]}")
        total["repos"] += 1
        total["commits"] += commits
        total["blocked"] += blocked
        rules = " ".join(f"{RULE_NAMES[k]}={v}" for k, v in rule_counts.items() if v)
        print(f"{repo.name}\tgit-crypt={'yes' if gc else 'no'}\tcommits={commits}\tblocked={blocked}\t{rules}")
    print(json.dumps(total, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    bad = 0

    def ok(cond: bool, label: str) -> None:
        nonlocal bad
        print(("ok   " if cond else "FAIL ") + label)
        bad += 0 if cond else 1

    def blocks(msg: str) -> bool:
        return bool(check_message(msg))

    # 止めるべき形 (値はすべて合成)
    for msg in ["todo: 参加費 1,234 円を記録", "記録: 着手金 12 万円", "記録: 約 3.5 億円の枠",
                "精算 ¥12,345 を記録", "€90 の登録費", "$1,250 の返金", "$12.5k の見積", "USD 1,234 を両替", "min 500 USD",
                "2,345.67 USD を送金", "300 ドルを両替", "5 万ドル", "1 ドル = 123.4 円で両替", "USD/JPY 123.45",
                "ドル円 123.4", "レート: 123.45", "123.45 で両替した記録", "予算を 50 万に縮める",
                "謝礼額: 6,789 / 4,321", "財源台帳: 見通し 2,345,678 → 1,234,567"]:
        ok(blocks(msg), f"止める: {msg}")
    ok(blocks("記録: 直接 1,234,000 / 総計 1,604,200\n参加費 2,000 円"), "止める: 3 桁区切りは別の行の金額で文脈を得る")
    # 通す形
    for msg in ["fix: 1,234 行を削った", "docs: 123,456 → 98,765 B", "data: 12,345 → 13,579 records",
                "tex: $3.1$--$3.2\\sigma$ を足す", "tex: $0.5^\\circ$ の範囲", "sh: $1 と $2 を quote", "f32 の円盤の判定",
                "円ターゲット較正", "額は 1 円も変わらない", "results: フランス 1-0 ドイツ", "1 万行の log", "2 万 entry の cache", "5 万倍の差",
                "AUD 3 件 / NZD 5 件", "EUR 6 bonds", "GBP 12, CHF 11, NZD 10", "42 USD bonds by YTM", "v1.2.3 を release", "2026-11-05 の記録", "PR #1234 を merge",
                "コーヒー 1,234 + 茶 400 = 最大 1,634 杯", "(101,102) (107,108)", "git log -L 100,120:draft.tex",
                "予算 (8,000 字) を超えたら畳む", "見通し 2,345,678 → 1,234,567", "Co-Authored-By: X <x@example.com>\n\nfix: typo"]:
        ok(not blocks(msg), f"通す: {msg.splitlines()[0]}")
    ok(not blocks("fix: 1,234 件を整理"), "通す: 3 桁区切り + 件数の単位")
    ok(not blocks("# 参加費 1,234 円\nfix: typo"), "通す: # の行は見ない")
    ok(check_message("a\n参加費 1,234 円\nb") == [(2, ["yen", "comma3"])], "行番号と規則の名前")
    # scope: git-crypt の宣言の有無
    with tempfile.TemporaryDirectory() as td:
        plain = Path(td) / "plain"
        enc = Path(td) / "enc"
        nested = Path(td) / "nested"
        for d in (plain, enc, nested):
            d.mkdir()
            subprocess.run(["git", "init", "-q", str(d)], check=True)
        (enc / ".gitattributes").write_text("secret/** filter=git-crypt diff=git-crypt\n")
        (nested / "sub").mkdir()
        (nested / "sub" / ".gitattributes").write_text("* filter=git-crypt diff=git-crypt\n")
        subprocess.run(["git", "-C", str(nested), "add", "sub/.gitattributes"], check=True)
        ok(not in_scope("auto", str(plain)), "scope auto: 暗号化の宣言の無い repo は見ない")
        ok(in_scope("auto", str(enc)), "scope auto: root の .gitattributes の宣言")
        ok(in_scope("auto", str(nested)), "scope auto: 入れ子の .gitattributes の宣言 (追跡済み)")
        ok(in_scope("all", str(plain)), "scope all: repo を問わない")
        msg = Path(td) / "MSG"
        msg.write_text("記録: 参加費 1,234 円\n")
        ok(run_gate(str(msg), str(enc), "auto", "commit message ") == 1, "gate: 暗号化 repo で止める")
        ok(run_gate(str(msg), str(plain), "auto", "commit message ") == 0, "gate: 平文の repo では通す")
        os.environ[ENV_SKIP] = "0"
        try:
            ok(run_gate(str(msg), str(enc), "auto", "commit message ") == 0, "gate: env で 1 回だけ通す")
        finally:
            del os.environ[ENV_SKIP]
        ok(run_gate(str(Path(td) / "missing"), str(enc), "auto", "commit message ") == 3, "gate: 読めない = 3")
    print("selftest:", "PASS" if not bad else f"FAIL ({bad})")
    return 0 if not bad else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--commit-msg", metavar="FILE", help="git の commit-msg hook (scope の既定 = auto)")
    mode.add_argument("--text-file", metavar="FILE", help="抽出した message の file を見る (agent の hook)")
    mode.add_argument("--replay", nargs="*", metavar="REPO", help="過去の commit message に当てて repo ごとに数える")
    mode.add_argument("--selftest", action="store_true")
    ap.add_argument("--repo", help="scope を決める repo (既定 = cwd)")
    ap.add_argument("--scope", choices=("auto", "all"), default="auto")
    ap.add_argument("--replay-root", help="--replay: この dir の直下の repo をすべて")
    ap.add_argument("--show", action="store_true", help="--replay: 当たった行を値ごと出す (手元の診断だけ)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.commit_msg:
        return run_gate(a.commit_msg, a.repo, a.scope, "commit message ")
    if a.text_file:
        return run_gate(a.text_file, a.repo, a.scope, "commit message ")
    repos = [Path(p) for p in (a.replay or [])]
    if a.replay_root:
        repos += repos_under(Path(a.replay_root).expanduser())
    if not repos:
        ap.error("--replay: repo を渡すか --replay-root を付ける")
    return replay(repos, a.scope, a.show)


if __name__ == "__main__":
    sys.exit(main())
