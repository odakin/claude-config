#!/usr/bin/env python3
"""check-session-shape.py — SESSION.md の形 (案件ごとの現在地 + 正本への link) を commit と書き込みの瞬間に守る gate + fleet 走査

なぜ (実測): 「SESSION に正本を置かない」 の規約 (CONVENTIONS.md#session-no-durable-record) は在り、 messageId の密度・byte の
検出器 (check-session-sot.py) も在ったが、 違反は形を変えて続いた = 決定の経緯・commit hash・検証結果・承認の記録を
「日付 + 何をした」 の節として SESSION に足す形。 共通の機構は 2 つ: ① SESSION の entry を **session / 日付で key** にすると
file は追記しかできず (置き換える slot が無い)、 日付つきの節 = 変更履歴 = 恒久の記録になる。 ② 「重要な判断で SESSION を
更新」 と書いた手順書 (層1 §3 の旧文言・各 repo の CLAUDE.md) が、 判断の**内容**を SESSION に書く生成器になっていた。
密度・byte の proxy はこの形を素通しし (実測: 違反の行は 429 byte、 hash 2 つ、 messageId 0)、 行数の目安は recall 依存で
守られなかった (実測: 45 repo 中 29 が目安 80 行超、 archive は数百 KB)。 ∴ 検出は「形」 を直接見る (一般則 = 層1
docs/convention-design-principles.md#time-keyed-file-appends-only)。

SESSION.md の形の契約 (規約の正本 = CONVENTIONS.md#session-no-durable-record):
  - entry は**案件 (状態が進む単位) ごとに 1 つ**、 進んだら**置き換える** (足さない)。 中身 = 現在地・次の一手・正本への link
  - **日付を見出しにした節を作らない** (`## 2026-09-28 — …` = 変更履歴の形。 日付は `最終更新:` の 1 行だけ)
  - **commit hash・messageId を書かない** (hash は git log が、 messageId は inbox / 台帳が持つ。 `最終更新: … (sweep 済: <hash>)` の
    1 行だけは push-workflow の marker として通す)
  - 1 行に経緯を詰めない (1000 byte 超の行は「案件の記録」 の形)
  - 全体は目安 80 行、 120 行で warn、 200 行を超えて**育つ** commit は止める (縮める commit は通す = 予算 gate と同じ形)

README.md / CLAUDE.md / AGENTS.md にも同じ gate が「生成器」 を見る:
  - README が自分を正本と宣言する行 (`本 README が正本` 等) = 非公開 repo (.claude/public-repo.marker 無し) では止める、
    公開 repo では warn (build / quickstart / deploy の手順の置き場は CONVENTIONS.md#readme-style)
  - README に日付の節・commit hash = warn (変更履歴は git log)
  - README に値の出典の表 (見出し行のどれかの列が「出典」 で始まり、 次の行が区切り) か `<!-- formcase:history -->` 区間を
    足す行 (kind readme-source-table / readme-history-region) = 非公開 repo では止める、 公開 repo と不明は warn。 README は
    説明と正本への参照だけで、 値の出典の正本はその値を書く script の行 (`# 出典:`)、 経緯の正本は README でない file
    (form-case-pipeline.md#case-readme)。 backtick の中・code fence の中・生成 view (formcase:view) の中は見ない。 足す行だけを
    見るので、 表や区間を外す commit は通る。 --fleet は repo の奥の README (git ls-files) まで数える
    (実測: 案件 dir の README に出典の表と経緯の区間が溜まり、 README が正本になっていた)
  - CLAUDE.md / AGENTS.md が「README / SESSION に (決定・成果物・状態を) 書け」 と指示する行 = warn (規約の役割表と衝突する
    手順書 = 違反の生成器。 実測: 案件の README に締切・状態を書けと命じた repo の CLAUDE.md、 「重要な判断時 → SESSION.md に
    決定事項を記録」 の雛形が 5 repo に残っていた)

暗号化の一致 (kind archive-plaintext / session-decrypted、 --staged は BLOCK・--fleet は 🔴):
  SESSION.md を暗号化している repo (filter 属性が付いている、 または blob が git-crypt の暗号文 `\\0GITCRYPT` で始まる) で、
  archive (`SESSION-archive*.md` / `SESSION-archive/**`) に同じ filter が付いていない、 または archive の blob が平文なら止める。
  HEAD で暗号文だった SESSION.md を平文の blob で入れる commit も止める (filter の driver が無い clone で書いた場合など)。
  比べる SESSION.md は archive と同じ階層のもの (`x/SESSION-archive/**` → `x/SESSION.md`)。 属性は commit に入る側
  (`git check-attr --cached`、 fleet は作業木) で、 blob は filter を通さない生の bytes (`git cat-file blob`) で見る = 属性だけ・
  blob だけでは片方の経路 (属性を付け忘れた / driver が無く平文のまま入った) を見逃す。
  実測: 一括移設の道具 (migrate-session-shape.py、 書く前に止まるよう修正済) と、 人や agent が手で作った archive の両方の経路で、
  暗号化された SESSION.md の中身が平文の archive として push された。 手の経路は道具の側では止められないので commit で止める。
  escape hatch は別の env = CLAUDE_SESSION_CRYPT_GUARD=0 (形の escape hatch で漏洩の gate が一緒に外れないようにする)。

README / SESSION を正本と書く行 (kind sot-claim、 README / SESSION 以外の file も対象。 「正本」 の言い換え
  〔SoT / SSoT / source of truth、 英文の is / are も〕 は「正本」 に直してから同じ述語で読む = _sot_norm):
  「手順は README.md §X が正本」「経緯の正本 = SESSION.md の entry」「Y は web/README.md が正本」 の形 = 同じ文 (。 と表の | で区切る)
  の中で、 README / SESSION の直後 40 字以内に「が / は (〜の) 正本」 か「を正本と / に」、 または「正本 = / は / :」 の直後 40 字以内の
  最初の file が README / SESSION。 間に主語の助詞 (は / が / 、)・別の file (`*.md` 等)・「でない / から / 以外」 を挟むもの、 正本の後が
  「への / に / を / の」 (= 正本は目的語)、 README / SESSION の後が「から / でなく / 参照」 のものは除く。 ただし別の file が並列
  (「notes/README.md と X.md が正本」「正本は … の CLAUDE.md / SESSION.md だけ」) のときは README / SESSION も正本の一部として拾う
  (「正本は X.md / README は入口」 のように並列の後で文が続くものは拾わない)。
  除く行: 否定 (置かない / しない 等が一致の近くにある)・規則の記述 (禁止 / 違反 / 宣言 / 検出 / 例外 / 公開リポでは)・過去の記述
  (旧 / だった / ていた / 撤回 / 廃止)・引用 (「」『』“” "" `` の中に「正本」 がある span は伏せる。 無い span は中身を残す = path の backtick)・
  code fence・markdown link は表示文字に畳む・「現在地」 を指す SESSION (契約どおりの役割)。
  除く file: 記録 (plans/ と archive/ の中、 SESSION-archive*、 *-archive.md)・自動生成 (先頭 5 行に AUTO-GENERATED 等)・locked (暗号文)。
  重さ: 非公開 repo の --staged = BLOCK、 公開 repo と不明 = WARN (README の自称正本と同じ扱い。 公開 repo の build / quickstart /
  deploy の手順の置き場は CONVENTIONS.md#readme-style)。 README の自称正本 (readme-self-sot) と同じ行は二重に
  出さない。 CLAUDE.md の home-redirect とも二重に出さない。 --text (書く瞬間の hook) は従来の 4 種の file 名だけ (hook の射程の宣言
  と揃える)、 それ以外の md は --staged と --fleet が見る。
  実測: 語が近いだけの行 (「README に正本を置かない」「正本は X で、 README は入口」「正本への link」 など) は fleet の追跡 md に多く、
  述語はそれを全部落とした。 述語を通った行は全部読んで判定した = 誤検出 0 (残るのは README / SESSION を正本にしている本物の行と、
  公開 repo の build の手順を README に置く行)。 直前に直された違反の行 (上の 3 形と「義務は SESSION.md が正本」) は全部拾う。

使い方:
  check-session-shape.py --staged [--repo DIR]     commit gate (pre-commit から)。 staged の追加行と、 SESSION.md の行数と、 暗号化の一致を見る
  check-session-shape.py --text PATH < 本文        書き込み hook から (Edit の new_string / Write の content を stdin で)。 行数は見ない
  check-session-shape.py --fleet [--root DIR]      走査 (dashboard / 手で)。 形に反する file を 🔴 / 🟡 で列挙、 0 件なら無出力
  check-session-shape.py --crypt-audit [--root DIR]  暗号化の一致だけを走査 (run-all-checks から)。 exit 0 = 無し / 1 = 平文の archive あり
  check-session-shape.py --selftest

exit: 0 = 通す (WARN は出しても 0) / 1 = 止める (--staged / --text で BLOCK が 1 つ以上) / 3 = 検査が走っていない
  (git repo でない・git が読めない等。 故障の合図を違反の合図と同じ値にしない =
  docs/convention-design-principles.md#failure-exit-equals-violation-exit)。 呼び元は「exit 1 かつ本 script の見出し
  (`check-session-shape:`)」 のときだけ止める。
escape hatch: CLAUDE_SESSION_SHAPE_GUARD=0 (BLOCK を WARN に落として通す。 使うのは owner が明示したときだけ。 archive への
  verbatim MOVE のような**縮める** commit は escape hatch なしで通る = 追加行に日付の節が無く行数が減る)。
  暗号化の一致だけは CLAUDE_SESSION_CRYPT_GUARD=0 (上)。

射程の限界 (§8.8 proxy 盲点): 見るのは形 (日付の節・hash・messageId・行の長さ・行数・宣言の言い回し) だけ。 日付も hash も
持たない散文の決定ログは通る。 その部分は形の契約 (案件ごとに置き換える) と 4 軸 sweep が持つ。 hook は Edit/Write の
tool 入力しか見ないので、 Bash の heredoc で書いた変更は commit の gate で捕まえる (二重の面 = 書く瞬間と commit)。

stdlib only。 lib/staged_diff.py (binary を含む commit で落ちない) と lib/git_blob.py (git-crypt の path も平文で) を使う。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

HEADING = "check-session-shape:"
ENV_ESCAPE = "CLAUDE_SESSION_SHAPE_GUARD"
RULE_DOC = "claude-config/CONVENTIONS.md#session-no-durable-record"
HOWTO_DOC = "claude-config/conventions/memory-file-slimming.md#session-shape-gate"

LINE_WARN = 120
LINE_BLOCK = 200
LONG_LINE_BYTES = 1000

README_RE = re.compile(r"^README(?:\.[A-Za-z-]+)?\.md$")
ENTRY_DOCS = {"CLAUDE.md", "AGENTS.md", "AGENTS.override.md"}
AUTO_GENERATED_RE = re.compile(r"AUTO-GENERATED|自動生成|generated by", re.I)

DATED_HEADING_RE = re.compile(r"^#{2,6}\s.*(?<!\d)20\d{2}-\d{2}(?:-\d{2})?(?!\d)")
HASH_RE = re.compile(r"`[0-9a-f]{6,12}`|(?<![A-Za-z0-9_/.-])commit\s+[0-9a-f]{7,40}(?![0-9a-f])")
HASH_ALLOW_RE = re.compile(r"最終更新|sweep\s*(?:済|未済)")
MSGID_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{16}(?![0-9a-fA-F])")
README_SELF_SOT_RE = re.compile(
    r"(?:(?:本|この)\s*(?:README|ファイル|file)[^。\n]{0,24}(?:が|は)\s*正本)|(?:README(?:\.md)?\s*(?:が|は)\s*正本)"
)
HOME_REDIRECT_RE = re.compile(
    r"(?:README|SESSION)(?:\.md)?[^。\n|]{0,24}(?:に|へ)\s*[^。\n|]{0,16}(?:書く|書いて|書け|記録|追記|残す|残して)"
    r"|(?:README|SESSION)(?:\.md)?\s*(?:が|は)\s*正本"
    r"|SESSION(?:\.md)?[^。\n|]{0,30}(?:成果物|決定事項|判断根拠|経緯を)"
)
NEGATION_RE = re.compile(
    r"置かない|書かない|しない|ではない|でない|複製しない|正本を置|pointer|ポインタ|参照だけ|参照のみ|リンクだけ|揮発|現在地|禁止|止め|gate|検査|警告|warn"
    r"|索引|index|一覧|目次"  # README の索引・一覧への追記は入口の役割そのもの
    r"|廃止|持たない|旧 step"  # 過去の手順を廃止したと述べる行は生成器でない
)
# README に正本を置かない (出典・経緯): 値の出典の表 (見出し行に「出典」 で始まる列 + 次の行が区切り) と
# formcase:history 区間 (経緯の除外区間)。 backtick の中・code fence の中・生成 view (formcase:view) の中は見ない。
HIST_OPEN_RE = re.compile(r"(?<!`)<!-- formcase:history -->(?!`)")
VIEW_OPEN_RE = re.compile(r"(?<!`)<!-- formcase:view [^>]*-->(?!`)")
VIEW_CLOSE_RE = re.compile(r"(?<!`)<!-- /formcase:view -->(?!`)")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
README_BODY_HINT = ("README は説明と正本への参照だけ: 値の出典 = その値を書く script の行の後ろの `# 出典:`、"
                    " 経緯 = README でない file (案件 dir の `経緯.md` 等)")


def readme_skip_lines(lines: list[str]) -> set[int]:
    """code fence の中と生成 view (formcase:view) の中の行番号 (1 始まり)。 README の出典表・history 区間の検査が見ない行。"""
    skip: set[int] = set()
    in_fence = in_view = False
    for i, l in enumerate(lines, 1):
        if l.lstrip().startswith("```"):
            skip.add(i)
            in_fence = not in_fence
            continue
        if in_fence:
            skip.add(i)
            continue
        if in_view:
            skip.add(i)
            if VIEW_CLOSE_RE.search(l):
                in_view = False
            continue
        if VIEW_OPEN_RE.search(l):
            skip.add(i)
            in_view = not VIEW_CLOSE_RE.search(l)
    return skip


def is_source_table_header(line: str) -> bool:
    """表の行で、 どれかの列が「出典」 で始まる (= 値の出典の表の見出し行の候補。 次の行が区切りかは呼び元が見る)。"""
    s = line.strip()
    if not s.startswith("|") or s.count("|") < 3:
        return False
    cells = [c.strip().strip("*`").strip() for c in s.strip("|").split("|")]
    return any(c.startswith("出典") for c in cells)


def readme_body_counts(text: str) -> tuple[int, int]:
    """(出典の表の数, formcase:history 区間の数)。 fleet 用。"""
    lines = text.splitlines()
    skip = readme_skip_lines(lines)
    src = hist = 0
    for i, l in enumerate(lines, 1):
        if i in skip:
            continue
        if HIST_OPEN_RE.search(l):
            hist += 1
        if is_source_table_header(l) and i < len(lines) and TABLE_SEP_RE.match(lines[i]):
            src += 1
    return src, hist


FIX_HINT = (
    "  → SESSION.md は案件ごとの現在地 1〜2 行 + 正本への link (置き換える、 足さない)。 何をした・commit・結果・承認は"
    " 正本 (DESIGN.md / plan / 台帳) へ。 契約 = " + RULE_DOC + " / 直し方 = " + HOWTO_DOC
)
CRYPT_FIX_HINT = (
    "  → .gitattributes で archive にも SESSION.md と同じ filter を付け (`SESSION-archive.md` と `SESSION-archive/**`)、 同じ commit に入れる。"
    " 平文で push 済みのものは履歴に残る (直すのは別の作業)。 直し方 = " + HOWTO_DOC
)

# ---------------------------------------------------------------- 暗号化の一致 (SESSION.md と archive)
CRYPT_ENV_ESCAPE = "CLAUDE_SESSION_CRYPT_GUARD"
CRYPT_KINDS = {"archive-plaintext", "session-decrypted"}
GITCRYPT_MAGIC = b"\x00GITCRYPT"
ARCHIVE_DIR_NAME = "SESSION-archive"
ARCHIVE_FILE_RE = re.compile(r"^SESSION-archive.*\.md$")
NO_FILTER = {"", "unspecified", "unset"}


def archive_session_rel(rel: str) -> str | None:
    """archive の path (`SESSION-archive*.md` / `SESSION-archive/**`) なら、 比べる SESSION.md (同じ階層) の path。 違えば None。"""
    parts = rel.split("/")
    for i, p in enumerate(parts[:-1]):
        if p == ARCHIVE_DIR_NAME:
            return "/".join(parts[:i] + ["SESSION.md"])
    if ARCHIVE_FILE_RE.match(parts[-1]):
        return "/".join(parts[:-1] + ["SESSION.md"])
    return None


def git_filter(repo: Path, rel: str, *, cached: bool) -> str:
    """`git check-attr filter` の値 (unspecified / unset / 名前)。 git が読めなければ例外 (= 検査が走っていない)。"""
    args = ["check-attr"] + (["--cached"] if cached else []) + ["filter", "--", rel]
    rc, out = _git(args, repo)
    if rc != 0:
        raise RuntimeError(f"git check-attr が失敗 ({rel})")
    line = out.strip().splitlines()[-1] if out.strip() else ""
    return line.rsplit(": ", 1)[-1] if ": " in line else "unspecified"


def raw_blob(repo: Path, spec: str) -> bytes | None:
    """filter を通さない blob の bytes (= commit に入る / 入った中身)。 無ければ None。"""
    try:
        r = subprocess.run(["git", "cat-file", "blob", spec], cwd=str(repo), capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def is_encrypted(blob: bytes | None) -> bool:
    return bool(blob) and blob.startswith(GITCRYPT_MAGIC)


def archive_crypt_gap(repo: Path, arch_rel: str, arch_spec: str, session_specs: list[str], *, cached: bool,
                      memo: dict | None = None) -> str | None:
    """archive が、 暗号化している SESSION.md と同じ守りを持たなければ理由を返す (持っていれば / SESSION.md を暗号化していなければ None)。
    session_specs = 比べる SESSION.md の blob を探す順 (staged なら index → HEAD、 fleet なら HEAD)。
    memo = SESSION.md ごとの (filter, 暗号文か) を覚える dict (同じ repo の archive を続けて見るとき git を呼び直さない)。"""
    s_rel = archive_session_rel(arch_rel) or "SESSION.md"
    key = (str(repo), s_rel)
    if memo is not None and key in memo:
        f_s, s_enc = memo[key]
    else:
        f_s = git_filter(repo, s_rel, cached=cached)
        s_blob = next((b for b in (raw_blob(repo, sp.format(rel=s_rel)) for sp in session_specs) if b is not None), None)
        s_enc = is_encrypted(s_blob)
        if memo is not None:
            memo[key] = (f_s, s_enc)
    if f_s in NO_FILTER and not s_enc:
        return None
    f_a = git_filter(repo, arch_rel, cached=cached)
    if f_s not in NO_FILTER and f_a != f_s:
        return f"{s_rel} は filter={f_s} (暗号化) なのに {arch_rel} は filter={f_a} = 暗号化されずに commit される"
    a_blob = raw_blob(repo, arch_spec.format(rel=arch_rel))
    if a_blob is not None and (s_enc or f_s.startswith("git-crypt")) and not is_encrypted(a_blob):
        return (f"{s_rel} は暗号化されているのに {arch_rel} の blob が平文 (先頭が \\0GITCRYPT でない = filter の driver が"
                " 無い clone で書いた等)")
    return None


def crypt_staged_findings(repo: Path, names: list[str]) -> list["Finding"]:
    out: list[Finding] = []
    for rel in names:
        if archive_session_rel(rel):
            gap = archive_crypt_gap(repo, rel, ":{rel}", [":{rel}", "HEAD:{rel}"], cached=True)
            if gap:
                out.append(Finding("BLOCK", rel, 0, "archive-plaintext", gap))
        elif Path(rel).name == "SESSION.md":
            head = raw_blob(repo, f"HEAD:{rel}")
            new = raw_blob(repo, f":{rel}")
            if is_encrypted(head) and new is not None and not is_encrypted(new):
                out.append(Finding("BLOCK", rel, 0, "session-decrypted",
                                   "HEAD では暗号文だった SESSION.md が平文の blob で入る (filter の driver が無い clone で書いた等)"))
    return out


def iter_repos(root: Path):
    """root 直下の git repo (隠し dir を除く)。"""
    try:
        return sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists())
    except OSError:
        return []


def crypt_fleet_rows(root: Path) -> list[str]:
    """HEAD にある archive のうち、 暗号化している SESSION.md の隣で守りが無いもの (🔴 の行)。 git が読めない repo は飛ばす。"""
    rows: list[str] = []
    memo: dict = {}
    for d in iter_repos(root):
        rc, out = _git(["ls-files", "-z", "--", "*SESSION-archive*"], d)  # pathspec の * は / も跨ぐ = 深さを問わない
        if rc != 0:
            continue
        for rel in out.split("\0"):
            if not rel or not archive_session_rel(rel):
                continue
            try:
                gap = archive_crypt_gap(d, rel, "HEAD:{rel}", ["HEAD:{rel}"], cached=False, memo=memo)
            except RuntimeError:
                continue
            if gap:
                rows.append(f"🔴 {d.name}/{rel}: {gap} (push 済みなら履歴にも平文が残る)")
    return rows


# ---------------------------------------------------------------- README / SESSION を正本と書く行
SOT_R_RE = re.compile(r"(?<![A-Za-z0-9_-])(?:README(?:\.[A-Za-z]{2}(?:[-_][A-Za-z]+)?)?(?:\.md)?|SESSION(?:\.md)?)(?![A-Za-z0-9_-])")
# README / SESSION の直後から: 40 字以内に「が / は (〜の) 正本」 か「を正本と / に」
SOT_FWD_RE = re.compile(
    r"(?P<mid>[^。|]{0,40}?)(?:(?<![にでとへも])(?:が|は)\s*(?P<qual>[^\s。|、]{0,10}?の)?\s*正本"
    r"(?!\s*(?:への|へ|に|を|から|の|ではな|でな|じゃな))"
    r"|を\s*正本\s*(?:と|に)(?!\S{0,4}(?:しな|せず|ならな))"
    r"|正本\s*(?:も|は)\s*ここ)")  # 構造の tree の注釈「README.md  # … の正本もここ」
# 「正本 = / は / : 」 の直後 40 字以内 (の末尾に README / SESSION)
SOT_BWD_RE = re.compile(r"正本\s*(?:は|=|＝|:|：|が)\s*(?P<mid>[^。|]{0,40}?)$")
SOT_R_AFTER_BAD_RE = re.compile(r"^\S{0,2}\s*(?:から|でなく|ではなく|ではない|でない|以外|じゃな|に正本|に置|へ|を?参照|を見)")
SOT_MID_BAD_RE = re.compile(r"[はが、，,]|でなく|ではなく|でない|ではない|じゃな|から|より|以外|[\w-]+\.(?:md|py|ya?ml|json|txt|sh|tex|toml)\b")
# 並列 (「notes/README.md と X.md が正本」「正本は … の CLAUDE.md / SESSION.md だけ」) = 別の file を挟んでも README / SESSION は正本の一部
_SOT_FILE = r"[\w./-]+\.(?:md|py|ya?ml|json|txt|sh|tex|toml)\b"
SOT_CONJ_FWD_RE = re.compile(r"^\s*(?:と|・)\s*" + _SOT_FILE + r"\s*$")
SOT_CONJ_BWD_RE = re.compile(r"^(?:[^\s、,は]{0,12}の\s*)?" + _SOT_FILE + r"\s*(?:と|・|/|／)\s*$")
SOT_CONJ_BWD_END_RE = re.compile(r"^(?:\.md)?\s*(?:だけ|のみ|$|[)）]|の\s)")  # 並列の最後の R で文が閉じる (「/ README は入口」 は別の文)
SOT_CLAUSE_BAD_RE = re.compile(r"禁止|違反|誤り|訂正|宣言|検出|例外|公開リポでは|公開 repo では|旧|だった|でした|ていた|以前|かつて|撤回|廃止")
SOT_LOCAL_NEG_RE = re.compile(r"置かない|書かない|持たない|置くな|書くな|しない|させない|ならない|いけない|てはな")
SOT_QUOTE_RE = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"\n]*\"|`[^`]*`")
SOT_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")
RECORD_DIR_NAMES = {"plans", "archive", "archives", ARCHIVE_DIR_NAME}
RECORD_FILE_RE = re.compile(r"^SESSION-archive.*\.md$|-archive(?:[-.][\w-]+)?\.md$")


def is_record_path(rel: str) -> bool:
    """記録 (plans / archive の中、 SESSION-archive、 *-archive.md) = 過去の文の引用は正本の宣言でない。"""
    parts = rel.replace("\\", "/").split("/")
    return any(p in RECORD_DIR_NAMES for p in parts[:-1]) or bool(RECORD_FILE_RE.search(parts[-1]))


def _sot_mask(line: str) -> str:
    def rep(m: re.Match) -> str:
        inner = m.group(0)[1:-1]
        return "〔引用〕" if "正本" in inner else inner
    return SOT_MD_LINK_RE.sub(r"\1", SOT_QUOTE_RE.sub(rep, line))


# 「正本」 の言い換え (SoT / SSoT / source of truth) も同じ述語で見る。 実測: 「詳細・SoT は README.md の節」 が
# 「正本」 の語だけを見る述語を素通りし、 公開 repo の CLAUDE.md で README が正本のまま残っていた。 SoT は大文字小文字を
# 区別する (file 名の sot-registry・check-sot-drift を拾わない)
SOT_SYNONYM_RE = re.compile(r"(?<![A-Za-z0-9_-])S?SoT(?![A-Za-z0-9_-])|(?i:(?<![A-Za-z])(?:single\s+)?source[\s-]+of[\s-]+truth(?![A-Za-z]))")
SOT_EN_TAIL_RE = re.compile(r"\s+(?:is|are)\s+(?:the\s+)?正本", re.I)  # 「README.md is the source of truth」
SOT_EN_HEAD_RE = re.compile(r"正本\s+(?:is|are|lives\s+in|=)\s+", re.I)  # 「The source of truth is README.md」


def _sot_norm(line: str) -> str:
    line = SOT_SYNONYM_RE.sub("正本", line)
    return SOT_EN_HEAD_RE.sub("正本は ", SOT_EN_TAIL_RE.sub("が正本", line))


def sot_claim(line: str) -> str | None:
    """README / SESSION を正本と書いた文 (見つからなければ None)。 述語の説明 = module docstring。"""
    line = _sot_norm(line)
    if "正本" not in line or ("README" not in line and "SESSION" not in line):
        return None
    for clause in re.split(r"[。|]", _sot_mask(line)):
        if "正本" not in clause or SOT_CLAUSE_BAD_RE.search(clause):
            continue
        for rm in SOT_R_RE.finditer(clause):
            m = SOT_FWD_RE.match(clause, rm.end())
            if m and (not SOT_MID_BAD_RE.search(m.group("mid")) or SOT_CONJ_FWD_RE.match(m.group("mid"))):
                if ("現在地" not in (m.group("qual") or "") + m.group("mid")
                        and not SOT_LOCAL_NEG_RE.search(clause[rm.start(): m.end() + 14])):
                    return clause.strip()
            head = clause[: rm.start()][-60:]
            hm = SOT_BWD_RE.search(head)
            after = clause[rm.end():]
            if hm and not SOT_R_AFTER_BAD_RE.match(after) and (
                    not SOT_MID_BAD_RE.search(hm.group("mid"))
                    or (SOT_CONJ_BWD_RE.match(hm.group("mid")) and SOT_CONJ_BWD_END_RE.match(after))):
                if "現在地" not in head[: hm.start()][-12:] and not SOT_LOCAL_NEG_RE.search(clause[rm.start(): rm.end() + 14]):
                    return clause.strip()
    return None


def fence_lines(lines: list[str]) -> set[int]:
    """code fence の中 (と fence の行) の行番号 (1 始まり)。"""
    skip: set[int] = set()
    inside = False
    for i, l in enumerate(lines, 1):
        if l.lstrip().startswith("```"):
            skip.add(i)
            inside = not inside
        elif inside:
            skip.add(i)
    return skip


class Finding:
    __slots__ = ("severity", "path", "lineno", "kind", "message", "sample")

    def __init__(self, severity: str, path: str, lineno: int, kind: str, message: str, sample: str = "") -> None:
        self.severity = severity  # BLOCK / WARN
        self.path = path
        self.lineno = lineno
        self.kind = kind
        self.message = message
        self.sample = sample

    def render(self) -> str:
        loc = f"{self.path}:{self.lineno}" if self.lineno else self.path
        s = self.sample.strip()
        if len(s) > 72:
            s = s[:69] + "…"
        tail = f"  「{s}」" if s else ""
        return f"{HEADING} {self.severity} {loc} [{self.kind}] {self.message}{tail}"


def classify(basename: str) -> str | None:
    if basename == "SESSION.md":
        return "session"
    if README_RE.match(basename):
        return "readme"
    if basename in ENTRY_DOCS:
        return "entry"
    return None


def scan_lines(kind: str, path: str, lines: list[tuple[int, str]], *, public: bool | None,
               context: list[str] | None = None) -> list[Finding]:
    """追加行 (行番号, 本文) の列に形の述語を当てる。 public = repo が公開 (marker あり) / None = 不明。
    context = その file の (書いた後の) 全行 = README の出典表の区切り行・code fence・生成 view の判定に使う (無ければ追加行だけで見る)。"""
    out: list[Finding] = []
    ctx = context if context is not None else [t for _n, t in lines]   # 断片 (hook) は 1 始まりの連番 = 行番号と一致
    skip = readme_skip_lines(ctx) if kind == "readme" else set()
    sot_skip = skip if kind == "readme" else fence_lines(ctx)
    check_sot = not is_record_path(path)
    for lineno, text in lines:
        claim = sot_claim(text) if check_sot and lineno not in sot_skip else None
        if claim and kind == "readme" and README_SELF_SOT_RE.search(_sot_norm(text)):
            claim = None  # README の自称正本は readme-self-sot が出す (二重に出さない)
        if claim:
            sev = "BLOCK" if public is False else "WARN"
            msg = ("README / SESSION を正本と書いた行 = 非公開 repo の正本は CLAUDE.md / DESIGN.md / conventions / 台帳"
                   " (README は入口、 SESSION は現在地と正本への link)"
                   if public is False else
                   "README / SESSION を正本と書いた行 = 公開 repo は warn (build / quickstart / deploy の手順の置き場は"
                   " CONVENTIONS.md#readme-style)、 SESSION は正本にならない")
            out.append(Finding(sev, path, lineno, "sot-claim", msg, claim))
        if kind == "doc":
            continue
        if kind == "session":
            if DATED_HEADING_RE.match(text):
                out.append(Finding("BLOCK", path, lineno, "dated-heading",
                                   "日付を見出しにした節 = 変更履歴の形 (日付は `最終更新:` の 1 行だけ)", text))
            if HASH_RE.search(text) and not HASH_ALLOW_RE.search(text):
                out.append(Finding("BLOCK", path, lineno, "commit-hash",
                                   "commit hash は git log が持つ (SESSION には書かない)", text))
            if MSGID_RE.search(text):
                out.append(Finding("BLOCK", path, lineno, "message-id",
                                   "messageId は受信記録 / 台帳が持つ (SESSION には書かない)", text))
            if len(text.encode("utf-8")) > LONG_LINE_BYTES:
                out.append(Finding("BLOCK", path, lineno, "long-line",
                                   f"1 行 {len(text.encode('utf-8'))} byte = 経緯を 1 行に詰めた形 ({LONG_LINE_BYTES} byte 超)", text))
        elif kind == "readme":
            if README_SELF_SOT_RE.search(_sot_norm(text)):
                sev = "WARN" if public else "BLOCK"
                msg = ("README が自分を正本と宣言 = 非公開 repo では正本は CLAUDE.md / DESIGN.md / 台帳 (README は入口)"
                       if not public else
                       "README が自分を正本と宣言 = 公開 repo は warn (build / quickstart / deploy の手順の置き場は CONVENTIONS.md#readme-style)")
                if public is None:
                    sev = "WARN"
                out.append(Finding(sev, path, lineno, "readme-self-sot", msg, text))
            if DATED_HEADING_RE.match(text):
                out.append(Finding("WARN", path, lineno, "dated-heading", "README の日付つき節 = 変更履歴は git log か CHANGELOG へ", text))
            if HASH_RE.search(text):
                out.append(Finding("WARN", path, lineno, "commit-hash", "README に commit hash (履歴は git log)", text))
            if lineno not in skip:
                sev = "BLOCK" if public is False else "WARN"
                if HIST_OPEN_RE.search(text):
                    out.append(Finding(sev, path, lineno, "readme-history-region",
                                       "README に formcase:history 区間 = 経緯を README に置く形。 " + README_BODY_HINT, text))
                nxt = ctx[lineno] if 0 < lineno < len(ctx) else ""
                if is_source_table_header(text) and TABLE_SEP_RE.match(nxt):
                    out.append(Finding(sev, path, lineno, "readme-source-table",
                                       "README に値の出典の表 (見出しに「出典」 の列) = 出典を README に置く形。 " + README_BODY_HINT, text))
        elif kind == "entry":
            if not claim and HOME_REDIRECT_RE.search(text) and not NEGATION_RE.search(text):
                out.append(Finding("WARN", path, lineno, "home-redirect",
                                   "README / SESSION に決定・成果物・状態を書けと指示する行 = 違反の生成器 (役割表 CONVENTIONS.md §2 と衝突。 決定は DESIGN / 正本へ、 SESSION は現在地の行を置き換える)", text))
    return out


# ---------------------------------------------------------------- git helpers

def _git(args: list[str], cwd: Path, timeout: int = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 99, str(exc)
    return r.returncode, r.stdout


def repo_root(start: Path) -> Path | None:
    rc, out = _git(["rev-parse", "--show-toplevel"], start if start.is_dir() else start.parent)
    if rc != 0 or not out.strip():
        return None
    return Path(out.strip())


def is_public_repo(root: Path | None) -> bool | None:
    if root is None:
        return None
    return (root / ".claude" / "public-repo.marker").is_file()


def blob_text(spec: str, cwd: Path) -> str | None:
    try:
        from git_blob import read_blob_text  # type: ignore
        return read_blob_text(spec, cwd=str(cwd))
    except Exception:
        rc, out = _git(["show", spec], cwd)
        return out if rc == 0 else None


def line_count(text: str | None) -> int:
    if not text:
        return 0
    return len(text.splitlines())


# ---------------------------------------------------------------- modes

def staged_kind(rel: str) -> str | None:
    """staged の path の検査の種類。 classify の 3 種 + それ以外の md (= README / SESSION を正本と書く行だけを見る)。"""
    kind = classify(Path(rel).name)
    if kind is None and rel.endswith(".md") and not is_record_path(rel):
        kind = "doc"
    return kind


def staged_findings(repo: Path) -> tuple[list[Finding], list[str]]:
    """暗号化の一致 + staged の追加行 + SESSION.md の行数。 返り = (findings, 検査した path)。"""
    from staged_diff import staged_added_lines  # type: ignore

    rc, out = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"], repo)
    if rc != 0:
        raise RuntimeError("git diff --cached が失敗")
    names = [p for p in out.splitlines() if p]
    findings: list[Finding] = crypt_staged_findings(repo, names)
    kinds = {p: k for p in names if (k := staged_kind(p))}
    if not kinds:
        return findings, []
    public = is_public_repo(repo)
    added: dict[str, list[tuple[int, str]]] = {p: [] for p in kinds}
    for path, lineno, text in staged_added_lines(cwd=str(repo), skip=lambda p: p not in kinds):
        if path in added:
            added[path].append((lineno, text))
    for path in sorted(kinds):
        kind = kinds[path]
        has_sot_word = any("正本" in _sot_norm(t) for _n, t in added[path])
        if kind == "doc" and not has_sot_word:
            continue  # 足した行に「正本」 が無い md = 見るものが無い (blob を読まない = 大きい commit を遅くしない)
        context = None  # 「正本」 が無ければ sot-claim は鳴らないので、 file 全体 (code fence の判定用) は要らない
        if kind == "readme" or has_sot_word:
            head = blob_text(f":{path}", repo) or ""
            if kind in ("readme", "doc") and AUTO_GENERATED_RE.search("\n".join(head.splitlines()[:5])):
                continue  # 生成物 (別の drift 検査が持つ)
            context = head.splitlines()
        findings.extend(scan_lines(kind, path, added[path], public=public, context=context))
        if kind == "session":
            new_n = line_count(blob_text(f":{path}", repo))
            old_n = line_count(blob_text(f"HEAD:{path}", repo))
            if new_n > LINE_BLOCK and new_n > old_n:
                findings.append(Finding("BLOCK", path, 0, "line-budget",
                                        f"{new_n} 行 (HEAD {old_n}) = {LINE_BLOCK} 行を超えて育つ commit。 同じ commit で案件ごとの現在地に置き換えるか、 経緯を正本 / SESSION-archive へ verbatim MOVE して縮める"))
            elif new_n > LINE_WARN and new_n > old_n:
                findings.append(Finding("WARN", path, 0, "line-budget",
                                        f"{new_n} 行 (HEAD {old_n}) = 目安 80 行の 1.5 倍を超えて育っている ({LINE_BLOCK} 行で止まる)"))
    return findings, sorted(kinds)


def report(findings: list[Finding], *, escape: bool, crypt_escape: bool = False) -> int:
    """escape = 形の BLOCK を WARN に落とす / crypt_escape = 暗号化の一致の BLOCK を WARN に落とす (別の env = 形の escape hatch で
    漏洩の gate が一緒に外れない)。"""
    if not findings:
        return 0
    for f in findings:
        print(f.render())
    shape = [f for f in findings if f.severity == "BLOCK" and f.kind not in CRYPT_KINDS]
    crypt = [f for f in findings if f.severity == "BLOCK" and f.kind in CRYPT_KINDS]
    if shape:
        print(FIX_HINT)
        if escape:
            print(f"{HEADING} ({ENV_ESCAPE}=0 で形の BLOCK を WARN に落として通す)")
    if crypt:
        print(CRYPT_FIX_HINT)
        if crypt_escape:
            print(f"{HEADING} ({CRYPT_ENV_ESCAPE}=0 で暗号化の BLOCK を WARN に落として通す)")
    live = ([] if escape else shape) + ([] if crypt_escape else crypt)
    if not live:
        return 0
    hatches = ([f"形は {ENV_ESCAPE}=0"] if any(f.kind not in CRYPT_KINDS for f in live) else []) + \
              ([f"暗号化は {CRYPT_ENV_ESCAPE}=0"] if any(f.kind in CRYPT_KINDS for f in live) else [])
    print(f"{HEADING} 止めた (BLOCK {len(live)} 件。 意図した縮退や例示なら {' / '.join(hatches)} で通す)")
    return 1


def mode_staged(repo_arg: str | None) -> int:
    start = Path(repo_arg).resolve() if repo_arg else Path.cwd()
    repo = repo_root(start)
    if repo is None:
        print(f"{HEADING} 検査が走っていない: git repo でない ({start})")
        return 3
    try:
        findings, _ = staged_findings(repo)
    except Exception as exc:  # 故障は 3 (違反の 1 と分ける)
        print(f"{HEADING} 検査が走っていない: {exc}")
        return 3
    return report(findings, escape=os.environ.get(ENV_ESCAPE) == "0",
                  crypt_escape=os.environ.get(CRYPT_ENV_ESCAPE) == "0")


def mode_text(path_arg: str, text: str) -> int:
    p = Path(path_arg)
    kind = classify(p.name)
    if kind is None:
        return 0
    start = p.parent  # まだ無い dir に書く場合は、 在る祖先まで上がってから repo を探す (cwd に fallback すると別の repo の公開/非公開を読む)
    while not start.exists() and start != start.parent:
        start = start.parent
    root = repo_root(start) if start.exists() else None
    public = is_public_repo(root)
    lines = [(i, t) for i, t in enumerate(text.splitlines(), 1)]
    findings = scan_lines(kind, str(p), lines, public=public)
    return report(findings, escape=os.environ.get(ENV_ESCAPE) == "0")


def iter_files(root: Path, name_pred, depth: int = 2):
    seen: set[Path] = set()
    for pattern in ("*", "*/*")[:depth]:
        for d in root.glob(pattern):
            if not d.is_dir() or d.name.startswith(".") or d.name in {"node_modules", ".git"}:
                continue
            for f in d.iterdir():
                if f.is_file() and not f.is_symlink() and name_pred(f.name):
                    r = f.resolve()
                    if r not in seen:
                        seen.add(r)
                        yield f


def iter_repo_readmes(root: Path):
    """root 直下の各 git repo の追跡された README*.md (深さを問わない)。 出典の表・history 区間は案件 dir の奥の README に出るので、
    深さ 2 までの iter_files では届かない。 git が読めない repo は飛ばす。"""
    try:
        subs = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists())
    except OSError:
        return
    for d in subs:
        rc, out = _git(["ls-files", "-z", "--", "*README*.md"], d)
        if rc != 0:
            continue
        for rel in out.split("\0"):
            if rel and README_RE.match(Path(rel).name):
                p = d / rel
                if p.is_file() and not p.is_symlink():
                    yield p


def sot_fleet_rows(root: Path) -> list[str]:
    """各 repo の追跡 md (記録・生成物・locked を除く) で README / SESSION を正本と書いた行を file ごとに 1 行 (🟡)。
    README の自称正本 (readme-self-sot) は上の README の走査が出すので、 同じ行は数えない。"""
    rows: list[str] = []
    for d in iter_repos(root):
        rc, out = _git(["ls-files", "-z", "--", "*.md"], d)
        if rc != 0:
            continue
        public = is_public_repo(d)
        for rel in out.split("\0"):
            if not rel or is_record_path(rel):
                continue
            p = d / rel
            if p.is_symlink() or not p.is_file():
                continue
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            if raw.startswith(GITCRYPT_MAGIC) or (b"README" not in raw and b"SESSION" not in raw):
                continue  # locked (読めない) / 対象の語が無い
            lines = raw.decode("utf-8", errors="ignore").splitlines()
            if AUTO_GENERATED_RE.search("\n".join(lines[:5])):
                continue
            is_readme = bool(README_RE.match(p.name))
            skip = readme_skip_lines(lines) if is_readme else fence_lines(lines)
            hits = [(i, c) for i, l in enumerate(lines, 1) if i not in skip and (c := sot_claim(l))
                    and not (is_readme and README_SELF_SOT_RE.search(_sot_norm(l)))]
            if not hits:
                continue
            i, c = hits[0]
            note = ("公開 repo = warn、 手順の置き場は CONVENTIONS.md#readme-style" if public else
                    "非公開 repo = 正本は CLAUDE / DESIGN / conventions / 台帳")
            rows.append(f"🟡 {d.name}/{rel}:{i}: README / SESSION を正本と書いた行 {len(hits)} 件 ({note})  「{c[:60]}」")
    return rows


def mode_crypt_audit(root: Path) -> int:
    """暗号化の一致だけの走査 (run-all-checks 用)。 0 = 無し / 1 = 守りの無い archive あり / 3 = 走っていない。"""
    if not root.is_dir():
        print(f"{HEADING} 検査が走っていない: root が無い ({root})")
        return 3
    rows = crypt_fleet_rows(root)
    for r in rows:
        print(r)
    if rows:
        print(CRYPT_FIX_HINT)
    return 1 if rows else 0


def mode_fleet(root: Path, limit: int = 15) -> int:
    rows: list[tuple[int, str]] = []  # (severity 2/1, line)
    if not root.is_dir():
        return 0
    for f in iter_files(root, lambda n: n == "SESSION.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lines = text.splitlines()
        dated = sum(1 for l in lines if DATED_HEADING_RE.match(l))
        hashes = sum(1 for l in lines if HASH_RE.search(l) and not HASH_ALLOW_RE.search(l))
        msgids = sum(1 for l in lines if MSGID_RE.search(l))
        long_ = sum(1 for l in lines if len(l.encode("utf-8")) > LONG_LINE_BYTES)
        n = len(lines)
        if not (dated or hashes or msgids or long_ or n > LINE_WARN):
            continue
        sev = 2 if (n > LINE_BLOCK or dated >= 5) else 1
        rel = str(f.relative_to(root))
        parts = [f"{n} 行"]
        if dated:
            parts.append(f"日付の節 {dated}")
        if hashes:
            parts.append(f"hash 行 {hashes}")
        if msgids:
            parts.append(f"messageId 行 {msgids}")
        if long_:
            parts.append(f"{LONG_LINE_BYTES}B 超の行 {long_}")
        rows.append((sev, f"{'🔴' if sev == 2 else '🟡'} {rel}: " + " / ".join(parts)))
    for f in iter_files(root, lambda n: bool(README_RE.match(n))):
        try:
            head = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if AUTO_GENERATED_RE.search("\n".join(head.splitlines()[:5])):
            continue
        rr = repo_root(f.parent)
        public = is_public_repo(rr)
        for i, l in enumerate(head.splitlines(), 1):
            if README_SELF_SOT_RE.search(_sot_norm(l)):
                rows.append((1, f"🟡 {f.relative_to(root)}:{i}: README が自分を正本と宣言 ({'公開 repo = warn、 手順の置き場は CONVENTIONS.md#readme-style' if public else '非公開 repo = 正本は CLAUDE/DESIGN/台帳'})"))
                break
    for f in iter_repo_readmes(root):
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if raw.startswith(b"\x00GITCRYPT"):
            continue  # locked = 読めない (見ていないことは他の検査が出す)
        text = raw.decode("utf-8", errors="ignore")
        if AUTO_GENERATED_RE.search("\n".join(text.splitlines()[:5])):
            continue
        src, hist = readme_body_counts(text)
        if src or hist:
            parts = ([f"出典の表 {src}"] if src else []) + ([f"formcase:history 区間 {hist}"] if hist else [])
            rows.append((1, f"🟡 {f.relative_to(root)}: README に " + " / ".join(parts)
                         + " (= 出典は値を書く script の行、 経緯は README でない file へ)"))
    for f in iter_files(root, lambda n: n in ENTRY_DOCS, depth=1):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits = [(i, l) for i, l in enumerate(text.splitlines(), 1)
                if HOME_REDIRECT_RE.search(l) and not NEGATION_RE.search(l) and not sot_claim(l)]
        if hits:
            i, l = hits[0]
            s = l.strip()
            rows.append((1, f"🟡 {f.relative_to(root)}:{i}: README / SESSION に書けと指示する行 {len(hits)} 件 (生成器)  「{s[:60]}」"))
    rows += [(2, r) for r in crypt_fleet_rows(root)]
    rows += [(1, r) for r in sot_fleet_rows(root)]
    if not rows:
        return 0
    rows.sort(key=lambda r: (-r[0], r[1]))
    print(f"# 📐 SESSION / README の形 (= 案件ごとの現在地 + 正本への link。 契約 = {RULE_DOC}、 直し方 = {HOWTO_DOC})")
    for _, line in rows[:limit]:
        print(line)
    if len(rows) > limit:
        print(f"  … ほか {len(rows) - limit} 件 (python3 {Path(__file__).name} --fleet --root {root} --limit 0 で全部)")
    return 0


# ---------------------------------------------------------------- selftest

def run_selftest() -> int:
    ok = True

    def check(cond: bool, label: str) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    here = Path(__file__).resolve()
    env = dict(os.environ)
    env.pop(ENV_ESCAPE, None)

    def run(args: list[str], cwd: Path, stdin: str | None = None, extra_env: dict | None = None):
        e = dict(env)
        if extra_env:
            e.update(extra_env)
        return subprocess.run([sys.executable, str(here), *args], cwd=str(cwd), input=stdin,
                              capture_output=True, text=True, env=e, timeout=120)

    with tempfile.TemporaryDirectory(prefix="check-session-shape-") as tmp:
        root = Path(tmp)
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        (repo / "SESSION.md").write_text("# SESSION\n\n最終更新: 2026-01-01 (sweep 済: abc1234)\n\n## 現在地\n\n- 案件 A — 次 = X → [正本](DESIGN.md)\n", encoding="utf-8")
        subprocess.run(["git", "add", "SESSION.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
        # A run with no mode (e.g. only --repo) checks nothing; exiting 0 there reads as a pass.
        r = run(["--repo", str(repo)], repo)
        check(r.returncode == 2, f"no mode (only --repo) exits 2, not a silent 0 (got {r.returncode})")

        def stage(rel: str, text: str) -> None:
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            subprocess.run(["git", "add", rel], cwd=repo, check=True)

        def unstage_all() -> None:
            subprocess.run(["git", "reset", "-q", "--hard", "HEAD"], cwd=repo, check=True)
            subprocess.run(["git", "clean", "-qfd"], cwd=repo, check=True)

        base = (repo / "SESSION.md").read_text(encoding="utf-8")

        # 1. 何も stage していない → 0
        r = run(["--staged"], repo)
        check(r.returncode == 0 and r.stdout == "", "staged: 対象 file 無しは沈黙 0")

        # 2. 日付の見出し → BLOCK
        stage("SESSION.md", base + "\n## 2026-09-28 — 何をした (session x)\n\n- やった\n")
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "dated-heading" in r.stdout and HEADING in r.stdout, "staged: 日付の節で止まる (exit 1 + 見出し)")
        unstage_all()

        # 3. commit hash → BLOCK / 最終更新 の hash は通る
        stage("SESSION.md", base + "\n- 案件 B — 適用済 (`79fecfa` / `8a94202`) → [記録](plans/x.md)\n")
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "commit-hash" in r.stdout, "staged: backtick の hash で止まる")
        unstage_all()
        stage("SESSION.md", base.replace("abc1234", "def5678"))
        r = run(["--staged"], repo)
        check(r.returncode == 0, "staged: 最終更新 (sweep 済: hash) の行は通る")
        unstage_all()

        # 4. messageId → BLOCK
        stage("SESSION.md", base + "\n- 送信済 19ab0000deadbeef\n")
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "message-id" in r.stdout, "staged: 16-hex messageId で止まる")
        unstage_all()

        # 5. 1000 byte 超の行 → BLOCK / 案件の 1 行 pointer は通る
        stage("SESSION.md", base + "\n- " + "経緯" * 520 + "\n")
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "long-line" in r.stdout, "staged: 1000 byte 超の行で止まる")
        unstage_all()
        stage("SESSION.md", base + "\n- 案件 C — 次 = 承認待ち → [台帳](todo/c.yaml)\n")
        r = run(["--staged"], repo)
        check(r.returncode == 0 and r.stdout == "", "staged: 案件の pointer 行は沈黙 0")
        unstage_all()

        # 6. 行数の予算: 210 行へ育つ → BLOCK / 210 → 150 に縮める → 通る (縮める commit は日付の節が残っていても通る)
        grown = base + "".join(f"- 案件 {i} — 次 = x → [p](DESIGN.md)\n" for i in range(210))
        stage("SESSION.md", grown)
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "line-budget" in r.stdout, "staged: 200 行を超えて育つ commit は止まる")
        subprocess.run(["git", "commit", "-q", "-m", "grown"], cwd=repo, env={**env, ENV_ESCAPE: "0"}, check=True)
        shrunk = base + "".join(f"- 案件 {i} — 次 = x → [p](DESIGN.md)\n" for i in range(150))
        stage("SESSION.md", shrunk)
        r = run(["--staged"], repo)
        check(r.returncode == 0, "staged: 予算超のまま縮める commit は通る")
        subprocess.run(["git", "commit", "-q", "-m", "shrunk"], cwd=repo, check=True)
        stage("SESSION.md", shrunk + "- 案件 z — 次 = y → [p](DESIGN.md)\n")
        r = run(["--staged"], repo)
        check(r.returncode == 0 and "line-budget" in r.stdout and "WARN" in r.stdout, "staged: 120 行超で育つのは WARN (0)")
        subprocess.run(["git", "reset", "-q", "--hard", "HEAD~2"], cwd=repo, check=True)

        # 7. escape hatch
        stage("SESSION.md", base + "\n## 2026-09-28 — x\n")
        r = run(["--staged"], repo, extra_env={ENV_ESCAPE: "0"})
        check(r.returncode == 0 and "WARN に落として" in r.stdout, "staged: escape hatch で通る (何が止めたかを出す)")
        unstage_all()

        # 8. README: 非公開 repo で自分を正本と宣言 → BLOCK / 公開 marker で WARN / 生成物は見ない
        stage("docs/README.md", "# docs\n\n本 README が正本。 詳細はここに書く。\n")
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "readme-self-sot" in r.stdout, "staged: 非公開 repo の README 自称正本で止まる")
        unstage_all()
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / ".claude" / "public-repo.marker").write_text("x\n", encoding="utf-8")
        stage("docs/README.md", "# docs\n\n本 README が正本。\n")
        r = run(["--staged"], repo)
        check(r.returncode == 0 and "WARN" in r.stdout and "readme-self-sot" in r.stdout, "staged: 公開 repo では WARN (0)")
        unstage_all()
        (repo / ".claude" / "public-repo.marker").unlink(missing_ok=True)  # git clean が消していることがある
        stage("gen/README.md", "<!-- AUTO-GENERATED by x — 手編集禁止 -->\n# gen\n本 README が正本。\n")
        r = run(["--staged"], repo)
        check(r.returncode == 0 and r.stdout == "", "staged: AUTO-GENERATED の README は見ない")
        unstage_all()

        # 9. CLAUDE.md の生成器 → WARN (0) / 否定形は通る
        stage("CLAUDE.md", "# X\n\n- 重要な判断時 → SESSION.md に決定事項を記録\n- README.md に締切・状態・提出先を書く\n")
        r = run(["--staged"], repo)
        check(r.returncode == 0 and r.stdout.count("home-redirect") == 2, "staged: CLAUDE.md の『SESSION/README に書け』 は WARN 2 件")
        unstage_all()
        stage("CLAUDE.md", "# X\n\n- SESSION.md には現在地の行だけを置く (決定は書かない)\n- README は入口、 正本を置かない\n")
        r = run(["--staged"], repo)
        check(r.returncode == 0 and r.stdout == "", "staged: 否定形・現在地の指示は沈黙")
        unstage_all()

        # 10. text mode (hook)
        r = run(["--text", str(repo / "SESSION.md")], repo, stdin="## 2026-09-28 — 何をした\n- x\n")
        check(r.returncode == 1 and "dated-heading" in r.stdout, "text: 日付の節で止まる")
        r = run(["--text", str(repo / "SESSION.md")], repo, stdin="- 案件 A — 次 = X → [正本](DESIGN.md)\n")
        check(r.returncode == 0 and r.stdout == "", "text: pointer 行は沈黙")
        r = run(["--text", str(repo / "notes.md")], repo, stdin="## 2026-09-28 — x\n")
        check(r.returncode == 0 and r.stdout == "", "text: 対象外の file は見ない")
        r = run(["--text", str(repo / "CLAUDE.md")], repo, stdin="- タスク完了時 → SESSION.md に成果物記録\n")
        check(r.returncode == 0 and "home-redirect" in r.stdout, "text: CLAUDE.md の生成器は WARN")

        # 11. git repo でない → 3
        outside = root / "plain"
        outside.mkdir()
        r = run(["--staged", "--repo", str(outside)], outside)
        check(r.returncode == 3 and "走っていない" in r.stdout, "staged: git repo でないは exit 3")

        # 12. fleet
        fleet = root / "fleet"
        (fleet / "a").mkdir(parents=True)
        (fleet / "b").mkdir()
        (fleet / "a" / "SESSION.md").write_text("# a\n" + "".join(f"## 2026-09-{i:02d} — x\n- y\n" for i in range(1, 8)), encoding="utf-8")
        (fleet / "b" / "SESSION.md").write_text("# b\n\n- 案件 — 次 → [p](x.md)\n", encoding="utf-8")
        (fleet / "b" / "CLAUDE.md").write_text("- 重要な判断時 → SESSION.md に決定事項を記録\n", encoding="utf-8")
        r = run(["--fleet", "--root", str(fleet)], root)
        check(r.returncode == 0 and "🔴 a/SESSION.md" in r.stdout and "b/SESSION.md" not in r.stdout
              and "b/CLAUDE.md" in r.stdout, "fleet: 日付の節の file を 🔴、 健全な file は出さず、 生成器の CLAUDE.md を 🟡")
        r = run(["--fleet", "--root", str(root / "none")], root)
        check(r.returncode == 0 and r.stdout == "", "fleet: 無い root は沈黙 0")

        # 13. README の値の出典表と formcase:history 区間 (= README に正本を置かない。 出典は値を書く script の行、 経緯は README でない file)
        src_tbl = "# 案件\n\n| 欄 | 値 | 出典 |\n|---|---|---|\n| 申請日 | 2026-01-01 | 提出予定日 |\n"
        stage("docs/case-a/README.md", src_tbl)
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "readme-source-table" in r.stdout, "staged: 非公開 repo の README に出典の表を足すと止まる")
        unstage_all()
        stage("docs/case-a/README.md", "# 案件\n\n<!-- formcase:history -->\n- 1/1 に提出\n<!-- /formcase:history -->\n")
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "readme-history-region" in r.stdout, "staged: 非公開 repo の README に formcase:history 区間を足すと止まる")
        unstage_all()
        ok_readme = ("# 案件\n\n経緯 = [`経緯.md`](経緯.md)。 書き方の例: `<!-- formcase:history -->` は README に置かない。\n\n"
                     "```\n<!-- formcase:history -->\n| 欄 | 値 | 出典 |\n|---|---|---|\n```\n\n"
                     "<!-- formcase:view kind=cells form=x refs=A1 -->\n| セル | 欄 | 値 | 規則 |\n|---|---|---|---|\n<!-- /formcase:view -->\n\n"
                     "| file | 何か |\n|---|---|\n| `fill_a.py` | 記入 (値の出典は各行の `# 出典:`) |\n")
        stage("docs/case-a/README.md", ok_readme)
        r = run(["--staged"], repo)
        check(r.returncode == 0 and "readme-source-table" not in r.stdout and "readme-history-region" not in r.stdout,
              "staged: backtick・code fence・生成 view の中と、 出典の列の無い表は見ない")
        unstage_all()
        stage("docs/case-a/README.md", src_tbl)
        subprocess.run(["git", "commit", "-q", "-m", "legacy table"], cwd=repo, env={**env, ENV_ESCAPE: "0"}, check=True)
        stage("docs/case-a/README.md", "# 案件\n\n値の出典 = `fill_a.py` の各行の `# 出典:`。\n")
        r = run(["--staged"], repo)
        check(r.returncode == 0 and "readme-source-table" not in r.stdout, "staged: 出典の表を README から外す commit は通る")
        subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=repo, check=True)
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / ".claude" / "public-repo.marker").write_text("x\n", encoding="utf-8")
        stage("docs/case-a/README.md", src_tbl)
        r = run(["--staged"], repo)
        check(r.returncode == 0 and "WARN" in r.stdout and "readme-source-table" in r.stdout, "staged: 公開 repo では出典の表は WARN (0)")
        unstage_all()
        (repo / ".claude" / "public-repo.marker").unlink(missing_ok=True)
        r = run(["--text", str(repo / "docs" / "case-b" / "README.md")], repo, stdin="| 項目 | 値 | 出典 |\n|---|---|---|\n")
        check(r.returncode == 1 and "readme-source-table" in r.stdout, "text: README の断片に出典の表 (見出し + 区切り) で止まる")
        r = run(["--text", str(repo / "docs" / "case-b" / "経緯.md")], repo, stdin="<!-- formcase:history -->\n| 欄 | 値 | 出典 |\n|---|---|---|\n")
        check(r.returncode == 0 and r.stdout == "", "text: README でない file (経緯.md) は見ない")
        deep = fleet / "c"
        (deep / "docs" / "case").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=deep, check=True)
        (deep / "docs" / "case" / "README.md").write_text(src_tbl + "\n<!-- formcase:history -->\n- x\n<!-- /formcase:history -->\n", encoding="utf-8")
        (deep / "docs" / "ok").mkdir(parents=True)
        (deep / "docs" / "ok" / "README.md").write_text(ok_readme, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=deep, check=True)
        r = run(["--fleet", "--root", str(fleet), "--limit", "0"], root)
        check("c/docs/case/README.md" in r.stdout and "出典の表 1" in r.stdout and "formcase:history 区間 1" in r.stdout
              and "c/docs/ok/README.md" not in r.stdout, "fleet: repo の奥の README の出典の表と history 区間を数える (健全な README は出さない)")

        # 14. 暗号化の一致 (A): SESSION.md に filter が付いているのに archive に同じ filter が無い / 暗号化されていた中身が
        #     平文の blob で入る commit を止める。 filter の driver は設定しない (= git は中身をそのまま入れる) ので、
        #     属性の食い違いと、 blob の先頭 (\0GITCRYPT) の両方を独立に確かめられる。
        def mkrepo(name: str) -> Path:
            d = root / name
            d.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            return d

        def put(d: Path, rel: str, data, add: bool = True) -> None:
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                p.write_bytes(data)
            else:
                p.write_text(data, encoding="utf-8")
            if add:
                subprocess.run(["git", "add", rel], cwd=d, check=True)

        def reset(d: Path) -> None:
            subprocess.run(["git", "reset", "-q", "--hard", "HEAD"], cwd=d, check=True)
            subprocess.run(["git", "clean", "-qfd"], cwd=d, check=True)

        arch_text = "# SESSION-archive\n\n## 2026-01-01 — 移した節\n- x\n"
        crepo = mkrepo("crypt-attr")
        put(crepo, ".gitattributes", "SESSION.md filter=selftestcrypt\n")
        put(crepo, "SESSION.md", "# S\n\n- 案件 — 次 → [p](DESIGN.md)\n")
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=crepo, check=True)
        put(crepo, "SESSION-archive.md", arch_text)
        r = run(["--staged"], crepo)
        check(r.returncode == 1 and "archive-plaintext" in r.stdout and HEADING in r.stdout,
              "staged (A): SESSION.md は filter 付きなのに archive に filter が無い → 止まる")
        r = run(["--staged"], crepo, extra_env={ENV_ESCAPE: "0"})
        check(r.returncode == 1 and "archive-plaintext" in r.stdout,
              "staged (A): 形の escape hatch では暗号化の検査は外れない")
        r = run(["--staged"], crepo, extra_env={"CLAUDE_SESSION_CRYPT_GUARD": "0"})
        check(r.returncode == 0 and "archive-plaintext" in r.stdout, "staged (A): 暗号化の escape hatch だけで通る (何が止めたかは出す)")
        reset(crepo)
        put(crepo, "SESSION-archive/2026-01.md", arch_text)
        r = run(["--staged"], crepo)
        check(r.returncode == 1 and "archive-plaintext" in r.stdout, "staged (A): dir 型の archive (SESSION-archive/**) も止まる")
        reset(crepo)
        put(crepo, ".gitattributes", "SESSION.md filter=selftestcrypt\nSESSION-archive.md filter=selftestcrypt\n"
                                     "SESSION-archive/** filter=selftestcrypt\n")
        put(crepo, "SESSION-archive.md", arch_text)
        put(crepo, "SESSION-archive/2026-01.md", arch_text)
        r = run(["--staged"], crepo)
        check(r.returncode == 0 and "archive-plaintext" not in r.stdout, "staged (A): 同じ filter を付ければ通る")
        reset(crepo)
        put(repo, "SESSION-archive.md", arch_text)
        r = run(["--staged"], repo)
        check(r.returncode == 0 and r.stdout == "", "staged (A): SESSION.md が暗号化されていない repo の archive は見ない")
        unstage_all()
        brepo = mkrepo("crypt-blob")
        put(brepo, "SESSION.md", b"\x00GITCRYPT\x00" + bytes(range(1, 64)))
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=brepo, check=True)
        put(brepo, "SESSION-archive.md", arch_text)
        r = run(["--staged"], brepo)
        check(r.returncode == 1 and "archive-plaintext" in r.stdout,
              "staged (A): 属性が無くても、 SESSION.md の blob が暗号文で archive の blob が平文なら止まる")
        reset(brepo)
        put(brepo, "SESSION-archive.md", b"\x00GITCRYPT\x00" + bytes(range(2, 64)))
        r = run(["--staged"], brepo)
        check(r.returncode == 0 and "archive-plaintext" not in r.stdout, "staged (A): archive の blob も暗号文なら通る")
        reset(brepo)
        put(brepo, "SESSION.md", "# S\n\n- 平文に戻した\n")
        r = run(["--staged"], brepo)
        check(r.returncode == 1 and "session-decrypted" in r.stdout, "staged (A): HEAD で暗号文だった SESSION.md を平文の blob で入れると止まる")
        reset(brepo)
        # fleet: HEAD にある平文の archive を 🔴 で出す (暗号化していない repo の archive は出さない)
        frepo = fleet / "e"
        frepo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=frepo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=frepo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=frepo, check=True)
        put(frepo, ".gitattributes", "SESSION.md filter=selftestcrypt\n")
        put(frepo, "SESSION.md", "# S\n")
        put(frepo, "SESSION-archive.md", arch_text)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=frepo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=fleet / "c", check=True)
        subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "c"],
                       cwd=fleet / "c", check=True)
        put(fleet / "c", "SESSION.md", "# c\n")
        put(fleet / "c", "SESSION-archive.md", arch_text)
        subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "c2"],
                       cwd=fleet / "c", check=True)
        r = run(["--fleet", "--root", str(fleet), "--limit", "0"], root)
        check("🔴 e/SESSION-archive.md" in r.stdout and "平文" in r.stdout and "c/SESSION-archive.md" not in r.stdout,
              "fleet (A): 暗号化された SESSION.md の隣の平文 archive を 🔴 (暗号化していない repo の archive は出さない)")
        r = run(["--crypt-audit", "--root", str(fleet)], root)
        check(r.returncode == 1 and "e/SESSION-archive.md" in r.stdout, "crypt-audit (A): 平文の archive があれば exit 1")
        r = run(["--crypt-audit", "--root", str(fleet / "c")], root)
        check(r.returncode == 0, "crypt-audit (A): 無ければ exit 0")

        # 15. README / SESSION を正本と書いた行 (C): 非公開 repo は止める・公開 repo は warn。 否定・引用・code fence・
        #     記録 (plans / SESSION-archive) は見ない。 README の自称正本とは二重に出さない
        claims = [
            ("DESIGN.md", "- 手順は README.md §How to build が正本。\n"),
            ("notes/x.md", "経緯の正本 = SESSION.md 08-08 entry、 送信記録は台帳\n"),
            ("docs/web.md", "verify / public release は [`web/README.md`](web/README.md) が正本。\n"),
            ("CLAUDE.md", "- 未決着の義務は **`SESSION.md` が正本**\n"),
            ("DESIGN.md", "- note と検算の対応は [`notes/README.md`](notes/README.md) と `CALC.md` が正本。\n"),
            ("DESIGN.md", "- (正本は作業場の `CLAUDE.md` / `SESSION.md` だけ)\n"),
            ("CLAUDE.md", "詳細・SoT は [`README.md`](README.md) `## For Claude` section (英)。\n"),
            ("DESIGN.md", "The source of truth is README.md.\n"),
            ("DESIGN.md", "- Build steps: README.md is the single source of truth.\n"),
        ]
        for rel, body in claims:
            stage(rel, "# x\n\n" + body)
            r = run(["--staged"], repo)
            check(r.returncode == 1 and "sot-claim" in r.stdout and "home-redirect" not in r.stdout,
                  f"staged (C): 非公開 repo の {rel} に「{body.strip()[:24]}…」 → 止まる")
            unstage_all()
        not_claims = [
            ("DESIGN.md", "README に正本を置かない。 正本は DESIGN.md。\n"),
            ("DESIGN.md", "leak gate は本節が正本で、 [`web/README.md`](web/README.md) はこの節への入口。\n"),
            ("DESIGN.md", "「README が正本」 と書いた行は commit で止まる\n"),
            ("DESIGN.md", "```\nREADME が正本\n```\n"),
            ("DESIGN.md", "識別子は正本 (plan / 台帳) に置き、 SESSION には正本への link だけ\n"),
            ("DESIGN.md", "経緯は README でない file (経緯.md) が正本\n"),
            ("DESIGN.md", "正本は DESIGN.md / README は入口\n"),
            ("DESIGN.md", "現在地の正本 = SESSION.md §現在地\n"),
            ("plans/2026-01-01-x.md", "経緯の正本 = SESSION.md 08-08 entry\n"),
            ("SESSION-archive.md", "経緯の正本 = SESSION.md 08-08 entry\n"),
            ("SESSION-archive/2026-01.md", "経緯の正本 = SESSION.md 08-08 entry\n"),
            ("DESIGN.md", "登録は scripts/sot-registry.yaml、 README は入口\n"),
            ("DESIGN.md", "The source of truth is CLAUDE.md; README.md is the entry point.\n"),
        ]
        for rel, body in not_claims:
            stage(rel, "# x\n\n" + body)
            r = run(["--staged"], repo)
            check(r.returncode == 0 and "sot-claim" not in r.stdout,
                  f"staged (C): {rel} の「{body.strip()[:24]}…」 は見ない (否定・引用・code fence・記録)")
            unstage_all()
        stage("docs/README.md", "# docs\n\n本 README が正本。\n")
        r = run(["--staged"], repo)
        check(r.returncode == 1 and "readme-self-sot" in r.stdout and "sot-claim" not in r.stdout,
              "staged (C): README の自称正本は readme-self-sot だけ (二重に出さない)")
        unstage_all()
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / ".claude" / "public-repo.marker").write_text("x\n", encoding="utf-8")
        stage("DESIGN.md", "# x\n\n- 手順は README.md §How to build が正本。\n")
        r = run(["--staged"], repo)
        check(r.returncode == 0 and "WARN" in r.stdout and "sot-claim" in r.stdout, "staged (C): 公開 repo では WARN (0)")
        unstage_all()
        (repo / ".claude" / "public-repo.marker").unlink(missing_ok=True)
        r = run(["--text", str(repo / "CLAUDE.md")], repo, stdin="- 経緯の正本 = SESSION.md 08-08 entry\n")
        check(r.returncode == 1 and "sot-claim" in r.stdout, "text (C): CLAUDE.md の断片は止める")
        r = run(["--text", str(repo / "DESIGN.md")], repo, stdin="- 経緯の正本 = SESSION.md 08-08 entry\n")
        check(r.returncode == 0 and r.stdout == "", "text (C): 書く瞬間の hook の射程 (SESSION / README / CLAUDE / AGENTS) は広げない")
        put(fleet / "c", "docs/rule.md", "# r\n\n- 順位の正本 = [../README.md](../README.md)\n")
        put(fleet / "c", "plans/2026-01-01-x.md", "# p\n\n- 順位の正本 = README.md\n")
        r = run(["--fleet", "--root", str(fleet), "--limit", "0"], root)
        check("c/docs/rule.md:3" in r.stdout and "正本" in r.stdout and "c/plans/" not in r.stdout,
              "fleet (C): repo の追跡 md の「README / SESSION が正本」 を 🟡 (記録の plans は出さない)")

    print("check-session-shape selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--repo")
    ap.add_argument("--text", metavar="PATH", help="stdin の本文を PATH に書く前提で検査")
    ap.add_argument("--fleet", action="store_true")
    ap.add_argument("--crypt-audit", action="store_true", help="暗号化の一致だけを走査 (exit 1 = 守りの無い archive あり)")
    ap.add_argument("--root", default=str(Path.home() / "Claude"))
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return run_selftest()
    if a.staged:
        return mode_staged(a.repo)
    if a.text:
        return mode_text(a.text, sys.stdin.read())
    if a.crypt_audit:
        return mode_crypt_audit(Path(a.root).expanduser())
    if a.fleet:
        return mode_fleet(Path(a.root).expanduser(), limit=(a.limit if a.limit > 0 else 10**9))
    # No mode = nothing was checked (--repo alone only names the repo for --staged).
    # A 0 here would read as a pass to the caller.
    ap.print_help(sys.stderr)
    print("check-session-shape: give a mode (--staged / --text / --fleet / --crypt-audit / --selftest)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(3)
