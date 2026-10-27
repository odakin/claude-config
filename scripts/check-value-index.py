#!/usr/bin/env python3
"""check-value-index.py — 本人が暗号化して持つ値 (電話・口座・生年月日・住所) が、 平文の追加行や commit message に写るのを止める。--selftest 内蔵。

源 = 値の索引: 暗号化された file の 1 節に `- <kind>: \\`<値>\\` (説明)` の行を並べたもの。 kind ごとに比べ方を変える:
  digits = 数字だけを比べる (空白・ハイフン・括弧・ピリオドの区切りを 2 字まで許す。 0 で始まる 10〜11 桁は +81 の形も)
  date   = 年月日 (YYYY-MM-DD で書く)。 書式の揺れを広げる = 区切り (- / . 年月日)・0 の有無・月日年 / 日月年・英語の月名・
           和暦 (昭和 / 平成 / 令和、 S / H / R)・YYYYMMDD
  text   = 空白を除いて比べる (英字は大文字小文字を無視)。 8 字未満の英数字は前後に英数字・ハイフンが続かない時だけ
索引に入れないもの (誤検出になる) = 短すぎる値 (支店番号・口座の下 4 桁) と、 他の平文に公開済みの値。

止める範囲: git-crypt で暗号化されない path の追加行 (暗号化される path = 値の置き場なので見ない) と commit message。
出力 = 当たった file と行番号だけ。 値も kind も説明も出さない (検査の出力が漏洩経路にならない)。
索引が読めない (鍵の無い機械 = 先頭が \\0GITCRYPT / file が無い) ときは、 検査が走っていないと 1 行出して通す (exit 0)。

設定 (--config) = 1 行に 1 つ `<設定 file からの相対 path>#<節の anchor id>` (anchor を省くと file 全体)。 `#` で始まる行は注釈。
  例 (個人層の value-index.txt):  private/personal-values.md#leak-index

使い方:
  check-value-index.py --config <value-index.txt>                     # pre-commit: staged の追加行 (当たれば exit 1)
  check-value-index.py --config <value-index.txt> --message-file <f>  # commit-msg: message の行
  check-value-index.py --config <value-index.txt> --scan-tree <repo>  # 棚卸し: 追跡する平文の file の全行 (file:行 だけ)
  check-value-index.py --config <value-index.txt> --scan-root ~/Claude [--explain]
                       # 直下の git repo を全部。 --explain = 当たった索引の行の説明 (例「— 本人の電話」) も出す。 値は出さない
                       # = 当たった行が何の値かを行を開かずに見分ける (公開データとの偶然の一致の見分けに使った = 実測)
  check-value-index.py --selftest

配線 = 公開 repo の public-precommit-runner.sh / commit-msg-leak-guard-runner.sh の Tier F (個人層に value-index.txt があるとき)
+ 個人層が非公開 repo の pre-commit の連鎖から呼ぶ (どちらも個人層の value-index.txt を渡す)。
呼ぶ側は「exit 1 かつ見出し `[value-index] ` 」 のときだけ止める (engine の故障で commit を巻き添えにしない)。 一時的に外す = CLAUDE_VALUE_INDEX_GUARD=0。
規律 = conventions/confidential-repo-boundary.md (暗号化した値の置き場と平文の境界)。 OS: macOS / Linux / Windows (標準 library だけ)。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from git_crypt_paths import encrypted_paths  # noqa: E402

HEADER = "[value-index] "
_LINE = re.compile(r"^\s*-\s*(digits|date|text)\s*:\s*`([^`]+)`\s*(.*)$")
_SEP = r"[\s\-‐－−ー.()（）]{0,2}"
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]
_ERAS = [("令和", "R", 2019), ("平成", "H", 1989), ("昭和", "S", 1926)]


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# ---- 索引を読む ------------------------------------------------------------------------------------
def read_index(config: Path):
    """[(kind, value)] と、 読めなかった源の説明の list。"""
    entries, unreadable = [], []
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], [f"設定 {config} が読めない"]
    for raw in lines:
        spec = raw.strip()
        if not spec or spec.startswith("#"):
            continue
        rel, _, anchor = spec.partition("#")
        path = (config.parent / rel).resolve()
        try:
            data = path.read_bytes()
        except OSError:
            unreadable.append(f"{rel} が無い")
            continue
        if data.startswith(b"\x00GITCRYPT"):
            unreadable.append(f"{rel} が暗号化されたまま (この機械に鍵が無い)")
            continue
        text = data.decode("utf-8", "replace").splitlines()
        if anchor:
            start = next((i for i, l in enumerate(text) if f'id="{anchor}"' in l), None)
            if start is None:
                unreadable.append(f"{rel} に節 {anchor} が無い")
                continue
            level = len(text[start]) - len(text[start].lstrip("#"))
            end = next((j for j in range(start + 1, len(text))
                        if text[j].startswith("#") and 0 < len(text[j]) - len(text[j].lstrip("#")) <= level), len(text))
            text = text[start:end]
        found = [(m.group(1), m.group(2).strip(), m.group(3).strip()) for m in map(_LINE.match, text) if m]
        if not found:
            unreadable.append(f"{rel} の索引に行が無い")
        entries += found
    return entries, unreadable


# ---- 値ごとの照合 ------------------------------------------------------------------------------------
def _digits_pattern(value: str):
    d = re.sub(r"\D", "", unicodedata.normalize("NFKC", value))
    if len(d) < 4:
        return None
    alts = [_SEP.join(d)]
    if d.startswith("0") and len(d) in (10, 11):
        alts.append(r"\+?81" + _SEP + _SEP.join(d[1:]))
    return re.compile(r"(?<![0-9])(?:" + "|".join(alts) + r")(?![0-9])")


def _date_pattern(value: str):
    m = re.fullmatch(r"(\d{4})\D(\d{1,2})\D(\d{1,2})", unicodedata.normalize("NFKC", value).strip())
    if not m:
        return None
    y, mo, da = m.group(1), int(m.group(2)), int(m.group(3))
    M, D = f"0?{mo}", f"0?{da}"
    S = r"\s*[-/.年月]\s*"
    month = _MONTHS[mo - 1]
    mname = f"(?:{month}|{month[:3]}\\.?)"
    dsuf = f"{D}(?:st|nd|rd|th)?"
    alts = [
        f"{y}{S}{M}{S}{D}",
        f"{M}\\s*/\\s*{D}\\s*/\\s*{y}",
        f"{D}\\s*[./]\\s*{M}\\s*[./]\\s*{y}",
        f"{mname}\\s+{dsuf},?\\s+{y}",
        f"{dsuf}\\s+{mname},?\\s+{y}",
        f"{y}{mo:02d}{da:02d}",
    ]
    yi = int(y)
    for kanji, letter, start in _ERAS:
        if yi >= start:
            ey = yi - start + 1
            eyp = f"(?:0?{ey}|元)" if ey == 1 else f"0?{ey}"
            alts.append(f"(?:{kanji}|{letter}\\.?)\\s*{eyp}\\s*[年./\\-]\\s*{M}\\s*[月./\\-]\\s*{D}")
            break
    return re.compile(r"(?<![0-9])(?:" + "|".join(alts) + r")(?![0-9])", re.I)


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s)).casefold()


class Matcher:
    def __init__(self, entries):
        """entries = (kind, 値) か (kind, 値, 説明)。 説明 (索引の行の値の後ろ) は --explain で出す (値は出さない)。"""
        self.patterns, self.texts = [], []   # [(正規表現, 説明)] / [(空白を除いた値, 説明)]
        for kind, value, *rest in entries:
            label = f"{kind} {rest[0]}".strip() if rest else kind
            if kind == "digits":
                p = _digits_pattern(value)
                if p:
                    self.patterns.append((p, label))
            elif kind == "date":
                p = _date_pattern(value)
                if p:
                    self.patterns.append((p, label))
            elif kind == "text":
                sq = _squash(value)
                if re.fullmatch(r"[0-9a-z\-./]+", sq) and len(sq) < 8:
                    self.patterns.append((re.compile(r"(?<![0-9A-Za-z\-])" + re.escape(unicodedata.normalize("NFKC", value))
                                                     + r"(?![0-9A-Za-z\-])", re.I), label))
                elif len(sq) >= 4:
                    self.texts.append((sq, label))

    def labels(self, line: str) -> list:
        """当たった索引の行の説明 (値は含まない)。 空 = 当たらない。"""
        norm = unicodedata.normalize("NFKC", line)
        out = [label for p, label in self.patterns if p.search(norm)]
        sq = _squash(line)
        return out + [label for t, label in self.texts if t in sq]

    def hit(self, line: str) -> bool:
        return bool(self.labels(line))


# ---- 走査 ---------------------------------------------------------------------------------------------
def staged_added(cwd=None):
    """[(path, 新しい行番号, 行)]。 BLOCK gate なので binary も errors=replace で読む (conventions/hook-authoring.md#staged-diff-binary)。"""
    out = subprocess.run(["git", "-c", "core.quotepath=off", "diff", "--cached", "-U0", "--no-color", "--no-ext-diff",
                          "--diff-filter=ACM", "--text"], cwd=cwd, capture_output=True)
    res, path, ln = [], None, 0
    for raw in out.stdout.decode("utf-8", "replace").split("\n"):
        if raw.startswith("+++ "):
            name = raw[4:]
            if len(name) >= 2 and name[0] == name[-1] == '"':
                name = name[1:-1]
            path = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
        elif raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
            ln = int(m.group(1)) if m else 0
        elif path and raw.startswith("+"):
            res.append((path, ln, raw[1:]))
            ln += 1
    return res


def check_staged(matcher, cwd=None):
    added = staged_added(cwd)
    enc = encrypted_paths([p for p, _, _ in added], cwd=cwd)
    return [(p, ln) for p, ln, text in added if p not in enc and matcher.hit(text)]


def check_message(matcher, path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [("(commit message)", i) for i, l in enumerate(lines, 1) if not l.startswith("#") and matcher.hit(l)]


def check_tree(matcher, repo: Path, explain=False):
    ls = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True)
    files = [f for f in ls.stdout.decode("utf-8", "replace").split("\0") if f]
    enc = encrypted_paths(files, cwd=str(repo))
    hits = []
    for f in files:
        p = repo / f
        if f in enc or not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:8192]:
            continue
        for i, l in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            labels = matcher.labels(l)
            if labels:
                hits.append((f, i, labels) if explain else (f, i))
    return hits


def scan_root(matcher, root: Path, explain=False):
    """root の直下の git repo を全部 (= 全 repo の棚卸し)。 [(repo/file, 行[, 説明])]。"""
    out = []
    for repo in sorted(d for d in root.iterdir() if (d / ".git").exists()):
        out += [(f"{repo.name}/{h[0]}",) + tuple(h[1:]) for h in check_tree(matcher, repo, explain)]
    return out


def report(hits, where: str) -> None:
    print(f"{HEADER}the {where} contains a value from the encrypted value index (値は出さない、 file と行番号だけ):",
          file=sys.stderr)
    for p, ln in hits:
        print(f"  {p}:{ln}", file=sys.stderr)
    print("  → その行の値を消し、 値の在り処 (暗号化された file の節) への pointer に書き換える。"
          " 値でないと確かめた一度だけの通過 = CLAUDE_VALUE_INDEX_GUARD=0", file=sys.stderr)


def main(argv=None) -> int:
    _utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    if os.environ.get("CLAUDE_VALUE_INDEX_GUARD", "1") == "0":
        return 0

    def opt(name):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None

    config = opt("--config")
    if not config:
        print("usage: check-value-index.py --config <value-index.txt> [--message-file <f> | --scan-tree <repo>"
              " | --scan-root <dir>] [--explain]",
              file=sys.stderr)
        return 2
    entries, unreadable = read_index(Path(config).expanduser())
    for why in unreadable:
        print(f"⚠️ value-index: 値の索引が読めない ({why}) — この検査は走っていない", file=sys.stderr)
    if not entries:
        return 0
    matcher = Matcher(entries)
    if opt("--message-file"):
        hits, where = check_message(matcher, Path(opt("--message-file"))), "commit message"
    elif opt("--scan-tree") or opt("--scan-root"):
        explain = "--explain" in argv
        hits = (check_tree(matcher, Path(opt("--scan-tree")).expanduser(), explain) if opt("--scan-tree")
                else scan_root(matcher, Path(opt("--scan-root")).expanduser(), explain))
        for h in hits:
            print(f"{h[0]}:{h[1]}" + (f"\t{' / '.join(h[2])}" if explain else ""))
        print(f"value-index: {len(hits)} 行", file=sys.stderr)
        return 1 if hits else 0
    else:
        hits, where = check_staged(matcher), "staged change"
    if hits:
        report(hits, where)
        return 1
    return 0


# ---- selftest (値はすべて架空) ---------------------------------------------------------------------
def selftest() -> int:
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and bool(cond)

    index = ("# 値\n\n## <a id=\"leak-index\"></a>漏洩検査の索引\n\n"
             "- digits: `090-0000-1234` (携帯)\n- digits: `7654321` (口座番号)\n- date: `1971-02-03` (生年月日)\n"
             "- text: `架空県架空市試験町9丁目8番7号` (住所)\n- text: `9-8-7 Shiken, Kaku-shi, Kaku` (英字)\n"
             "- text: `98-7a` (番地の短い形)\n\n## 別の節\n\n- digits: `1111111`\n")
    m = Matcher(read_index_from_text(index, "leak-index"))
    expect("digits: 区切りの揺れ (空白・括弧・全角) を拾う", m.hit("携帯 090 0000 1234") and m.hit("（090）0000-1234")
           and m.hit("０９０-００００-１２３４"))
    expect("digits: +81 の形を拾う", m.hit("tel +81-90-0000-1234"))
    expect("digits: 長い数字の中の 7 桁は拾わない", not m.hit("id 1765432100") and not m.hit("x17654321"))
    expect("digits: 口座番号の 7 桁を拾う", m.hit("普通 7654321"))
    expect("date: 区切り・0・和暦・英語・YYYYMMDD の揺れを拾う",
           all(m.hit(s) for s in ["1971/2/3", "1971年02月03日", "昭和46年2月3日", "S46.2.3", "Feb. 3, 1971",
                                  "3 February 1971", "02/03/1971", "19710203"]))
    expect("date: 別の日は拾わない", not m.hit("1971-02-13") and not m.hit("2026-02-03"))
    expect("text: 空白を除いて・大文字小文字を無視して拾う", m.hit("住所 = 架空県 架空市 試験町 9丁目8番7号")
           and m.hit("9-8-7 SHIKEN,  Kaku-shi, Kaku"))
    expect("text: 短い英数字は前後が続く時は拾わない", m.hit("番地 98-7a。") and not m.hit("v198-7a") and not m.hit("98-7ab"))
    expect("節の外の行は索引にしない", not m.hit("1111111"))
    with tempfile.TemporaryDirectory() as d:
        cfg = Path(d) / "value-index.txt"
        (Path(d) / "values.md").write_text(index, encoding="utf-8")
        cfg.write_text("# 注釈\nvalues.md#leak-index\n", encoding="utf-8")
        entries, bad = read_index(cfg)
        expect("設定 file から節を読む", len(entries) == 6 and not bad)
        (Path(d) / "locked.md").write_bytes(b"\x00GITCRYPT\x00\x01\x02")
        cfg.write_text("locked.md#leak-index\n", encoding="utf-8")
        entries, bad = read_index(cfg)
        expect("暗号化されたままの索引は読めないと言う", not entries and bad and "鍵" in bad[0])
        # 一時 repo で staged を見る
        repo = Path(d) / "repo"
        repo.mkdir()
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, env=env, capture_output=True, check=False)  # noqa: E731
        if git("init", "-q").returncode != 0:
            print("  [SKIP] git が無い")
        else:
            (repo / ".gitattributes").write_text("private/** filter=git-crypt diff=git-crypt\n", encoding="utf-8")
            (repo / "private").mkdir()
            (repo / "private" / "v.md").write_text("携帯 090-0000-1234\n", encoding="utf-8")
            (repo / "note.md").write_text("一行目\n連絡先 090-0000-1234\n", encoding="utf-8")
            (repo / "scan.pdf").write_bytes(b"%PDF-1.4\n%\xc5\xd0\xe2\xe3\nstream \xff\xfe\n")
            git("add", "-A")
            hits = check_staged(m, cwd=str(repo))
            expect("staged: 平文の追加行を file:行 で返し、 暗号化の path は見ない (binary が同じ commit にあっても)",
                   hits == [("note.md", 2)])
            got = scan_root(m, Path(d), explain=True)
            expect("scan-root: 直下の repo を見て、 当たった索引の行の説明だけを出す (値は出さない)",
                   got == [("repo/note.md", 2, ["digits (携帯)"])] and "0000" not in str(got))
            msg = Path(d) / "msg"
            msg.write_text("fix: 1971/2/3 の件\n# 090-0000-1234 (注釈の行)\n", encoding="utf-8")
            expect("commit message: 値の行を拾い、 # の注釈行は見ない", check_message(m, msg) == [("(commit message)", 1)])
            old = os.getcwd()
            cfg.write_text("values.md#leak-index\n", encoding="utf-8")
            os.chdir(repo)
            try:
                import io
                import contextlib
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(["--config", str(cfg)])
                expect("main: 当たれば exit 1 + 見出し、 出力に値を出さない",
                       rc == 1 and HEADER in err.getvalue() and "0000" not in err.getvalue())
            finally:
                os.chdir(old)
    print("check-value-index selftest:", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def read_index_from_text(text: str, anchor: str):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "v.md").write_text(text, encoding="utf-8")
        (Path(d) / "c.txt").write_text(f"v.md#{anchor}\n", encoding="utf-8")
        return read_index(Path(d) / "c.txt")[0]


if __name__ == "__main__":
    sys.exit(main())
