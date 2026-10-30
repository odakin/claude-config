#!/usr/bin/env python3
"""check-student-identifiers.py — 学生の識別子 (学籍番号の形・氏名・path の中の姓) を平文で新しく commit させない: commit gate (--staged = stage した path と平文 file の足した行、 --commit-msg = commit message、 違反で exit 1) + fleet の棚卸し (--tree、 報告だけ)。

由来 (実測): agent は手元の既存の例 (姓入りの TODO id・学籍番号入りの file 名・氏名と点数を並べた commit message) を
真似る。 既存の例を消している最中にも、 別の session から同じ形の新しい例が入った = 「気をつける」 では止まらない。
例が何であれ commit の時点で機械が止める。

## 何を見るか

  (a) 学籍番号の形 (大文字小文字を区別しない)。 形の正規表現 = ~/.claude/pii-filename-patterns.txt
      (check-pii-filenames.py と同じ file、 env CLAUDE_PII_FILENAME_PATTERNS で差し替え) + 一覧の `id_patterns`。
      git の hash に見えるもの (16 進 12 文字以上の連なりの中 / 全部が小文字の 16 進の token) は外す。
      ただし一覧の `ids` にある既知の学籍番号は、 16 進に見えても当てる。
  (b) 学生の氏名 (漢字は姓と名の間の空白を許す、 ローマ字は姓名・名姓の両順と区切り 空白 , _ . - を許す)。
  (c) 学生の姓の token — **path だけ** (ローマ字 4 文字以上 = 英字以外か camelCase の境で区切った token と完全一致、
      漢字 2 文字以上 = 前に漢字・かなが無く後ろに漢字が無い位置 〔「_姓_」「姓さん」 は当て、 基金名の「姓名奨学」 の
      ような漢字の続きは当てない〕)。 教員・同僚と同じ姓は一覧の `surname_allow` で外す。
      一覧の `surname_conditional` の姓 (例: 同僚として動く研究室のメンバー) は、 同じ path (新しく入る部分だけでなく
      path 全体) に `path_role_patterns` のどれかが在るときだけ当てる (= 学生としての用件 〔推薦・成績・奨学金・TA の
      勤務など〕 と並んだ path は止め、 出張・共同研究の path は通す)。
      本文と commit message には姓を当てない (教員の姓と衝突して、 止める理由の無い commit を止めるため)。
      ただし一覧の `surname_message_repos` に名がある repo では、 commit message にも (c) を当て、 条件つきの姓も
      役割の語によらず当てる (= その repo の規則が commit message に学生の姓を書かないと決めている。 教員・同僚の姓は
      surname_allow で外れたまま)。 由来 (実測): 事務の repo の commit message に学生の姓 + 「さん」 が繰り返し入り、
      姓だけの形はどの検査も見ていなかった。

  値の一覧は machine-local の JSON (既定 ~/.claude/student-identity.json、 env CLAUDE_STUDENT_IDENTITY で差し替え)。
  この repo には値も、 値を集める元 (名簿の置き場所) も置かない。 一覧を作るのは各自の個人層の builder。
  形式 (どの key も省略可):

      {"schema": 1,
       "id_patterns": ["<正規表現>", ...],          # (a) の形。 pattern file に足される
       "ids": ["<学籍番号>", ...],                   # 既知の学籍番号
       "id_allow": ["<正規表現>", ...],             # (a) から外す token (全体一致、 大文字小文字を問わない = 例示・試験用の架空番号)
       "full_names_cjk": ["山田 花子", ...],         # 空白 = 姓と名の境 (無ければ どの字の間の空白も許す)
       "full_names_latin": [["yamada", "hanako"], ...],  # [姓, 名]
       "surnames_cjk": [...], "surnames_latin": [...],   # (c) path だけ
       "surname_allow": [...],                       # (c) から外す語 (教員・同僚の姓、 path に普通に出る語)
       "surname_allow_by_repo": {"<repo の dir 名>": [...]},  # (c) をその repo の path でだけ外す語
       "surname_skip_repos": ["<repo の dir 名>", ...],     # (c) をしない repo (論文の著者名で file を名付ける repo)
       "surname_conditional": [...],                 # (c) 役割の語と同じ path でだけ当てる姓 (surname_allow が優先)
       "surname_message_repos": ["<repo の dir 名>", ...],  # (c) を commit message にも当てる repo (条件つきの姓も)
       "path_role_patterns": ["<正規表現>", ...],    # 役割の語 (大文字小文字を問わず path 全体を search)
       "full_name_allow": [...]}                     # (b) から外す氏名 (例示用の架空の名前など)

  一覧が無く pattern file も無い = 対象外 (何もせず exit 0)。 pattern file だけが在る機械では (a) だけを検査し、
  「氏名は検査していない」 を 1 行出す (= fail-open を黙らせない)。

## 面

  --staged [--repo DIR]   commit gate。 ① この commit で新しく入る path (追加・rename・copy) の、 HEAD に無かった
                          部分 (既存の dir の下に足した file なら file 名から先) に (a)(b)(c)、 ② 平文の file の
                          足した行 (`git diff --cached --no-textconv`) に (a)(b)。 git-crypt で暗号化される file は
                          index の blob が暗号文 (先頭 `\\0GITCRYPT`) なので差分に行が出ず、 検査しない (= 暗号化して
                          置くのは正しい置き方)。 暗号化の設定があっても平文のまま stage された file は検査する。
                          binary (NUL を含む・既知の拡張子・UTF-8 でも cp932 でもない) は見ない。
  --commit-msg FILE       commit message に (a)(b)、 一覧の surname_message_repos の repo では (c) も。 `#` で始まる行と scissors 行から後は git が捨てるので見ない。
  --tree DIR [--max N] [--strict]
                          fleet の棚卸し。 DIR が git repo ならその repo、 そうでなければ直下の各 git repo の HEAD の
                          track 済み path (全部) に (a)(b)(c)、 平文の blob (2 MB 以下) の全行に (a)(b)。 報告だけ
                          (exit 0)、 --strict なら当たりで exit 1。

  出力は値を伏せる: 当たりは「先頭の 1 文字 + …(長さ)」 に置き換え、 path もその部分を伏せて出す
  (hook の出力は transcript と terminal に残るので、 検出器が値を書き写す経路にしない)。

## 呼び元との契約

  exit: 0 = 当たり無し / 1 = 当たりあり (見出し `check-student-identifiers: BLOCK`、 --tree は --strict のときだけ) /
        3 = 検査が走っていない (git repo でない・git が失敗・一覧が壊れている・内部の例外。 見出しつきで 1 行)。
  呼び元 = scripts/pre-commit-bib と scripts/public-precommit-runner.sh (--staged) + scripts/commit-msg-leak-guard-runner.sh
  の Stage 0 (--commit-msg、 marker の無い repo にも install-public-commit-msg.sh --any-repo が stub を置く)。
  呼び元は「exit 1 かつ BLOCK 見出し」 のときだけ止め、 見出しの無い非 0 は 1 行出して通す
  (= docs/convention-design-principles.md#failure-exit-equals-violation-exit)。
  escape hatch: CLAUDE_STUDENT_ID_GUARD=0 (--staged / --commit-msg。 一覧の誤検出を 1 回通すとき。 誤検出が続くなら
  一覧の `surname_allow` / `full_name_allow` を builder 側で直す) / git 標準の --no-verify。

selftest: python3 check-student-identifiers.py --selftest (架空の名前・番号だけを使う。 述語の陽性・陰性対照、
  一時 repo での --staged の赤 → 緑、 暗号化 filter つき file を見ないこと、 既存 dir の下に足した file の扱い、
  --commit-msg、 --tree、 出力に値が出ないこと)
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    from staged_diff import parse_added_lines, BINARY_SUFFIXES  # 差分を bytes で読み、 binary を file ごとに外す
except Exception:  # pragma: no cover
    parse_added_lines = None  # type: ignore[assignment]
    BINARY_SUFFIXES = ()  # type: ignore[assignment]

HEADING = "check-student-identifiers:"
BLOCK_HEADING = HEADING + " BLOCK"
NOT_RUN = HEADING + " 検査が走っていない"
ENV_SKIP = "CLAUDE_STUDENT_ID_GUARD"
ENV_LIST = "CLAUDE_STUDENT_IDENTITY"
ENV_PATTERNS = "CLAUDE_PII_FILENAME_PATTERNS"
DEFAULT_LIST = Path.home() / ".claude" / "student-identity.json"
DEFAULT_PATTERNS = Path.home() / ".claude" / "pii-filename-patterns.txt"

GITCRYPT_MAGIC = b"\x00GITCRYPT"
HEX_RUN = re.compile(r"[0-9A-Fa-f]{12,}")
LOWER_HEX = re.compile(r"[0-9a-f]+")
CJK_GAP = r"[ \t　]{1,2}"          # 漢字の姓と名の間の空白 (半角・全角)
CJK_BEFORE = r"(?<![一-鿿々〆ヶぁ-んァ-ヶー])"   # path の漢字の姓: 前に漢字・かなが無い
CJK_AFTER = r"(?![一-鿿々〆ヶ])"                 # 後ろに漢字が無い (かな = 「さん」 等は続いてよい)
LATIN_GAP = r"[\s,_.\-]{0,3}"          # ローマ字の姓と名の間 (無しも許す = camelCase の path)
LATIN_TOKEN = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+")
SCISSORS = re.compile(r"^# -+ >8 -+$")
TREE_MAX_BLOB = 2 * 1024 * 1024
EXTRA_BINARY = (".bin", ".dll", ".so", ".dylib", ".class", ".jar", ".o", ".a", ".exe", ".wasm", ".psd", ".ai",
                 ".eps", ".tif", ".tiff", ".bmp", ".mvfrm", ".asset", ".unity", ".prefab", ".npz", ".npy",
                 ".pkl", ".h5", ".parquet", ".doc", ".xls", ".ppt", ".odt", ".ods", ".epub", ".dmg")

KIND_LABEL = {
    "id": "学籍番号の形",
    "id-known": "既知の学籍番号",
    "name-cjk": "氏名 (漢字)",
    "name-latin": "氏名 (ローマ字)",
    "surname-cjk": "姓 (漢字)",
    "surname-latin": "姓 (ローマ字)",
}

Span = Tuple[int, int, str]  # (start, end, kind)


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------- 一覧と正規表現

_END = ""
_GAP = "\x00"


def _trie_regex(words: Iterable[str], gap: str) -> Optional[str]:
    """語の集合 → trie に畳んだ正規表現 (大きい alternation を速く回すため)。 語の中の \\x00 は gap に置き換える。"""
    trie: Dict[str, dict] = {}
    n = 0
    for w in words:
        if not w:
            continue
        node = trie
        for ch in w:
            node = node.setdefault(ch, {})
        node[_END] = {}
        n += 1
    if not n:
        return None

    def render(node: dict) -> str:
        alts = []
        for ch in sorted(k for k in node if k != _END):
            piece = gap if ch == _GAP else re.escape(ch)
            child = node[ch]
            sub = render(child) if any(k != _END for k in child) else ""
            if sub:
                sub = "(?:%s)%s" % (sub, "?" if _END in child else "")
            alts.append(piece + sub)
        return alts[0] if len(alts) == 1 else "(?:" + "|".join(alts) + ")"

    return render(trie)


def _norm_cjk(s: str) -> str:
    return re.sub(r"[ \t　]+", " ", str(s or "")).strip()


class Detector:
    def __init__(self, cfg: dict, patterns: Sequence[str]):
        self.id_res: List[re.Pattern] = []
        for p in list(patterns) + list(cfg.get("id_patterns") or []):
            try:
                self.id_res.append(re.compile(p))
            except re.error as e:
                raise ConfigError("学籍番号の形の正規表現が壊れている: %s" % e)
        self.known_ids: Set[str] = {str(i).upper() for i in (cfg.get("ids") or []) if str(i).strip()}
        try:
            self.id_allow = [re.compile(str(a), re.I) for a in (cfg.get("id_allow") or [])]
        except re.error as e:
            raise ConfigError("id_allow の正規表現が壊れている: %s" % e)
        lit = _trie_regex(sorted(i.lower() for i in self.known_ids), "")
        self.known_re = re.compile(r"(?<![0-9A-Za-z])" + lit + r"(?![0-9A-Za-z])", re.I) if lit else None

        allow_full = {re.sub(r"[\s　,_.\-]", "", str(a)).lower() for a in (cfg.get("full_name_allow") or [])}
        cjk_words: Set[str] = set()
        self.n_names = 0
        for raw in cfg.get("full_names_cjk") or []:
            name = _norm_cjk(raw)
            flat = name.replace(" ", "")
            if len(flat) < 3 or flat.lower() in allow_full:
                continue
            self.n_names += 1
            cjk_words.add(flat)
            if " " in name:
                sn, _, gv = name.partition(" ")
                cjk_words.add(sn + _GAP + gv.replace(" ", ""))
            else:
                for i in range(1, len(flat)):
                    cjk_words.add(flat[:i] + _GAP + flat[i:])
        rx = _trie_regex(cjk_words, CJK_GAP)
        self.cjk_full_re = re.compile(rx) if rx else None

        latin_words: Set[str] = set()
        for pair in cfg.get("full_names_latin") or []:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ConfigError("full_names_latin の要素は [姓, 名] の 2 要素にする")
            sn, gv = (re.sub(r"\s+", " ", str(x)).strip().lower() for x in pair)
            if len(sn) < 2 or len(gv) < 2 or {(sn + gv).replace(" ", ""), (gv + sn).replace(" ", "")} & allow_full:
                continue
            self.n_names += 1
            latin_words.add(sn + _GAP + gv)
            latin_words.add(gv + _GAP + sn)
        rx = _trie_regex(latin_words, LATIN_GAP)
        self.latin_full_re = re.compile(r"(?<![A-Za-z])" + rx + r"(?![A-Za-z])", re.I) if rx else None

        allow_sn = {str(a).strip().lower() for a in (cfg.get("surname_allow") or []) if str(a).strip()}
        cjk_sn = {_norm_cjk(s).replace(" ", "") for s in (cfg.get("surnames_cjk") or [])}
        cjk_sn = {s for s in cjk_sn if len(s) >= 2 and s.lower() not in allow_sn}
        rx = _trie_regex(cjk_sn, "")
        self.cjk_sn_re = re.compile(CJK_BEFORE + rx + CJK_AFTER) if rx else None
        self.latin_sn: Set[str] = {str(s).strip().lower() for s in (cfg.get("surnames_latin") or [])}
        self.latin_sn = {s for s in self.latin_sn if len(s) >= 4 and s.isascii() and s.isalpha() and s not in allow_sn}
        by_repo = cfg.get("surname_allow_by_repo") or {}
        if not isinstance(by_repo, dict):
            raise ConfigError("surname_allow_by_repo は {repo の dir 名: [姓, ...]} にする")
        self.allow_by_repo: Dict[str, Set[str]] = {
            str(k): {str(a).strip().lower() for a in (v or []) if str(a).strip()} for k, v in by_repo.items()}
        self.surname_skip_repos: Set[str] = {str(r) for r in (cfg.get("surname_skip_repos") or [])}
        self.message_repos: Set[str] = {str(r) for r in (cfg.get("surname_message_repos") or [])}
        # 条件つきの姓: 当てる姓の集合に足し (一覧の surnames_* に無くても)、 当たったら役割の語を見て決める
        cond = {_norm_cjk(c).replace(" ", "").lower() for c in (cfg.get("surname_conditional") or []) if str(c).strip()}
        self.conditional: Set[str] = {c for c in cond if c not in allow_sn}
        try:
            self.role_res = [re.compile(str(r), re.I) for r in (cfg.get("path_role_patterns") or [])]
        except re.error as e:
            raise ConfigError("path_role_patterns の正規表現が壊れている: %s" % e)
        self.latin_sn |= {c for c in self.conditional if len(c) >= 4 and c.isascii() and c.isalpha()}
        cjk_cond = {c for c in self.conditional if not c.isascii() and len(c) >= 2}
        if cjk_cond - cjk_sn:
            rx = _trie_regex(cjk_sn | cjk_cond, "")
            self.cjk_sn_re = re.compile(CJK_BEFORE + rx + CJK_AFTER) if rx else None
        self.has_names = bool(self.cjk_full_re or self.latin_full_re or self.cjk_sn_re or self.latin_sn)

    # --- 当たり
    def ids(self, text: str) -> List[Span]:
        out: List[Span] = []
        hexruns: Optional[List[Tuple[int, int]]] = None
        for rx in self.id_res + ([self.known_re] if self.known_re else []):
            for m in rx.finditer(text):
                tok = m.group(0)
                if not tok:
                    continue
                known = tok.upper() in self.known_ids
                if not known and any(a.fullmatch(tok) for a in self.id_allow):
                    continue
                if not known:
                    if LOWER_HEX.fullmatch(tok):
                        continue
                    if hexruns is None:
                        hexruns = [h.span() for h in HEX_RUN.finditer(text)]
                    if any(s <= m.start() and m.end() <= e for s, e in hexruns):
                        continue
                out.append((m.start(), m.end(), "id-known" if known else "id"))
        return _dedupe(out)

    def names(self, text: str) -> List[Span]:
        out: List[Span] = []
        if self.cjk_full_re is not None and not text.isascii():
            out.extend((m.start(), m.end(), "name-cjk") for m in self.cjk_full_re.finditer(text))
        if self.latin_full_re is not None:
            out.extend((m.start(), m.end(), "name-latin") for m in self.latin_full_re.finditer(text))
        return out

    def surnames(self, text: str, repo: Optional[str] = None, context: Optional[str] = None,
                 always_conditional: bool = False) -> List[Span]:
        """path の姓。 context = 役割の語を探す範囲 (既定 = text。 --staged は新しく入る部分を text、 path 全体を context に渡す)。
        always_conditional = 条件つきの姓も役割の語によらず当てる (surname_message_repos の commit message)。"""
        out: List[Span] = []
        if repo and repo in self.surname_skip_repos:
            return out
        skip = self.allow_by_repo.get(repo or "", set())
        role: List[Optional[bool]] = [None]

        def keep(tok: str) -> bool:
            if always_conditional or tok not in self.conditional:
                return True
            if role[0] is None:
                role[0] = any(r.search(context if context is not None else text) for r in self.role_res)
            return bool(role[0])

        if self.latin_sn:
            for m in LATIN_TOKEN.finditer(text):
                tok = m.group(0).lower()
                if tok in self.latin_sn and tok not in skip and keep(tok):
                    out.append((m.start(), m.end(), "surname-latin"))
        if self.cjk_sn_re is not None and not text.isascii():
            out.extend((m.start(), m.end(), "surname-cjk") for m in self.cjk_sn_re.finditer(text)
                       if m.group(0) not in skip and keep(m.group(0)))
        return out

    def text_hits(self, text: str) -> List[Span]:
        return _dedupe(self.ids(text) + self.names(text))

    def path_hits(self, text: str, repo: Optional[str] = None, context: Optional[str] = None) -> List[Span]:
        return _dedupe(self.ids(text) + self.names(text) + self.surnames(text, repo, context))


def _dedupe(spans: List[Span]) -> List[Span]:
    """重なる当たりは長い方 (同じ長さなら先に来た方) だけ残す。"""
    spans = sorted(spans, key=lambda s: (s[0], -(s[1] - s[0])))
    out: List[Span] = []
    for s in spans:
        if out and s[0] < out[-1][1]:
            continue
        out.append(s)
    return out


def mask(token: str) -> str:
    return "%s…(%d)" % (token[:1], len(token))


def mask_text(text: str, spans: List[Span]) -> str:
    out, last = [], 0
    for s, e, _k in sorted(spans):
        if s < last:
            continue
        out.append(text[last:s])
        out.append(mask(text[s:e]))
        last = e
    out.append(text[last:])
    return "".join(out)


def load_patterns() -> Tuple[List[str], Optional[Path]]:
    path = Path(os.environ.get(ENV_PATTERNS) or DEFAULT_PATTERNS).expanduser()
    if not path.is_file():
        return [], None
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = re.sub(r"\s+#.*$", "", line).strip()   # 行末の comment (空白 + #) を外す
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out, path


def load_config() -> Tuple[Optional[Detector], List[str]]:
    """(Detector か None = 対象外, 注記の行)。 一覧が壊れていれば ConfigError。"""
    notes: List[str] = []
    patterns, pat_path = load_patterns()
    list_path = Path(os.environ.get(ENV_LIST) or DEFAULT_LIST).expanduser()
    cfg: dict = {}
    if list_path.is_file():
        try:
            cfg = json.loads(list_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ConfigError("一覧を読めない (%s): %s" % (list_path, e))
        if not isinstance(cfg, dict):
            raise ConfigError("一覧の形が違う (object でない): %s" % list_path)
    elif not patterns:
        return None, notes
    else:
        notes.append("⚠️ %s 氏名の一覧が無い (%s) = 学籍番号の形だけを検査した" % (HEADING, list_path))
    det = Detector(cfg, patterns)
    if not det.id_res and not det.known_re and not det.has_names:
        return None, notes
    return det, notes


# ---------------------------------------------------------------- git

def _git(args: List[str], cwd: Optional[str], inp: Optional[bytes] = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=cwd, input=inp,
                          capture_output=True, check=False)


def _head_dirs(root: str) -> Optional[Set[str]]:
    """HEAD の tree に在る dir の集合。 HEAD が無い (最初の commit) なら空集合、 git の失敗は None。"""
    if _git(["rev-parse", "--verify", "-q", "HEAD"], root).returncode != 0:
        return set()
    r = _git(["ls-tree", "-r", "-d", "-z", "--name-only", "HEAD"], root)
    if r.returncode != 0:
        return None
    return {x.decode("utf-8", "surrogateescape") for x in r.stdout.split(b"\0") if x}


def _new_part_start(path: str, head_dirs: Set[str]) -> int:
    """path のうち HEAD に無かった部分の開始位置 (既存の dir の下に足した file なら file 名の先頭)。"""
    parts = path.split("/")
    start = 0
    for i in range(len(parts) - 1):
        prefix = "/".join(parts[:i + 1])
        if prefix in head_dirs:
            start = len(prefix) + 1
        else:
            break
    return start


def _staged_new_paths(root: str) -> Optional[List[str]]:
    """この commit で新しく入る path (追加・rename 先・copy 先)。 git の失敗は None。"""
    r = _git(["diff", "--cached", "--name-status", "-z", "-M", "--diff-filter=ACR"], root)
    if r.returncode != 0:
        return None
    items = r.stdout.split(b"\0")
    out: List[str] = []
    i = 0
    while i < len(items):
        st = items[i].decode("ascii", "replace")
        if not st:
            i += 1
            continue
        width = 3 if st[0] in "RC" else 2   # R / C は「旧 path、 新 path」 の 2 つが続く
        if i + width - 1 < len(items):
            out.append(items[i + width - 1].decode("utf-8", "surrogateescape"))
        i += width
    return out


def _format(where: str, kind: str, token: str) -> str:
    return "  %s: %s %s" % (where, KIND_LABEL.get(kind, kind), mask(token))


def _block(findings: List[str], det_note: str) -> None:
    print("%s 学生の識別子が平文で新しく入る — %d 件 (値は伏せて表示)" % (BLOCK_HEADING, len(findings)), file=sys.stderr)
    for f in findings[:50]:
        print(f, file=sys.stderr)
    if len(findings) > 50:
        print("  … ほか %d 件" % (len(findings) - 50), file=sys.stderr)
    print("  直し方: path は識別子を含まない名前にする (例 = 用件の語だけの TODO id) / 本文の識別子は git-crypt で"
          "暗号化される file に移すか「学生 A」 等に置き換える / commit message からは消す", file=sys.stderr)
    print("  %s 誤検出を 1 回だけ通す: %s=0 (続くなら一覧の surname_allow / full_name_allow を直す)"
          % (det_note, ENV_SKIP), file=sys.stderr)


def _list_note() -> str:
    return "一覧 = %s /" % (os.environ.get(ENV_LIST) or DEFAULT_LIST)


def run_staged(repo: Optional[str]) -> int:
    if os.environ.get(ENV_SKIP) == "0":
        print("%s %s=0 — この commit では検査しない" % (HEADING, ENV_SKIP), file=sys.stderr)
        return 0
    try:
        det, notes = load_config()
    except ConfigError as e:
        print("%s (%s)" % (NOT_RUN, e), file=sys.stderr)
        return 3
    for n in notes:
        print(n, file=sys.stderr)
    if det is None:
        return 0
    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top.returncode != 0:
        print("%s (git repo でない: %s)" % (NOT_RUN, repo or os.getcwd()), file=sys.stderr)
        return 3
    root = top.stdout.decode("utf-8", "replace").strip()
    if parse_added_lines is None:
        print("%s (lib/staged_diff.py を読めない)" % NOT_RUN, file=sys.stderr)
        return 3
    repo_name = _repo_name(root)
    paths = _staged_new_paths(root)
    head_dirs = _head_dirs(root)
    if paths is None or head_dirs is None:
        print("%s (git diff --cached / ls-tree が失敗)" % NOT_RUN, file=sys.stderr)
        return 3
    findings: List[str] = []
    for p in paths:
        start = _new_part_start(p, head_dirs)
        spans = [(s + start, e + start, k) for s, e, k in det.path_hits(p[start:], repo_name, p)]
        if spans:
            kinds = sorted({KIND_LABEL.get(k, k) for _s, _e, k in spans})
            findings.append("  path %s: %s" % (mask_text(p, spans), " / ".join(kinds)))
    diff = _git(["diff", "--cached", "--no-textconv", "--no-ext-diff", "-U0", "--no-color", "-M",
                 "--diff-filter=ACMR"], root)
    if diff.returncode != 0:
        print("%s (git diff --cached が失敗: rc=%d)" % (NOT_RUN, diff.returncode), file=sys.stderr)
        return 3
    added, _binary = parse_added_lines(diff.stdout)
    for path, lineno, text in added:
        for s, e, k in det.text_hits(text):
            findings.append(_format("%s:%d" % (_masked_path(det, path, repo_name), lineno), k, text[s:e]))
    if findings:
        _block(findings, _list_note())
        return 1
    return 0


def _repo_name(root: str) -> str:
    """repo の dir 名 (worktree でも元の repo の名前 = surname_allow_by_repo の key)。"""
    r = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], root)
    common = r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""
    return Path(common).parent.name if common.endswith("/.git") else Path(root).name


def _masked_path(det: Detector, path: str, repo: Optional[str] = None) -> str:
    spans = det.path_hits(path, repo)
    return mask_text(path, spans) if spans else path


def message_lines(raw: str) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for i, line in enumerate(raw.splitlines(), 1):
        if SCISSORS.match(line):
            break
        if line.startswith("#"):
            continue
        out.append((i, line))
    return out


def run_commit_msg(msg_file: str) -> int:
    if os.environ.get(ENV_SKIP) == "0":
        print("%s %s=0 — この commit message は検査しない" % (HEADING, ENV_SKIP), file=sys.stderr)
        return 0
    try:
        det, notes = load_config()
    except ConfigError as e:
        print("%s (%s)" % (NOT_RUN, e), file=sys.stderr)
        return 3
    for n in notes:
        print(n, file=sys.stderr)
    if det is None:
        return 0
    try:
        raw = Path(msg_file).read_bytes().decode("utf-8", "replace")
    except OSError as e:
        print("%s (commit message を読めない: %s)" % (NOT_RUN, e), file=sys.stderr)
        return 3
    # 一覧が commit message にも姓を当てると宣言した repo (hook は repo の top で走る = cwd の repo)
    repo = _repo_name(os.getcwd()) if det.message_repos else None
    findings: List[str] = []
    for lineno, line in message_lines(raw):
        spans = det.text_hits(line)
        if repo in det.message_repos:
            spans = _dedupe(spans + det.surnames(line, repo, always_conditional=True))
        for s, e, k in spans:
            findings.append(_format("commit message:%d" % lineno, k, line[s:e]))
    if findings:
        _block(findings, _list_note())
        return 1
    return 0


# ---------------------------------------------------------------- --tree

def repos_under(root: Path) -> List[Path]:
    if (root / ".git").exists():
        return [root]
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").exists())


def _decode(data: bytes) -> Optional[str]:
    for enc in ("utf-8", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _cat_blobs(repo: Path, shas: List[str]) -> Iterable[Tuple[str, bytes]]:
    """git cat-file --batch で blob を順に返す (入力は別 thread で書く = pipe の詰まりを避ける)。"""
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=str(repo), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def feed() -> None:
        try:
            for s in shas:
                proc.stdin.write((s + "\n").encode())
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    t = threading.Thread(target=feed, daemon=True)
    t.start()
    out = proc.stdout
    for s in shas:
        header = out.readline()
        if not header:
            break
        parts = header.split()
        if len(parts) < 3 or parts[1] != b"blob":
            continue
        size = int(parts[2])
        data = out.read(size)
        out.read(1)
        yield s, data
    t.join(timeout=5)
    proc.wait()


def scan_repo(det: Detector, repo: Path) -> Optional[dict]:
    r = _git(["ls-tree", "-r", "-l", "-z", "HEAD"], str(repo))
    if r.returncode != 0:
        return None if _git(["rev-parse", "--verify", "-q", "HEAD"], str(repo)).returncode == 0 else {
            "paths": [], "lines": [], "files": 0, "encrypted": 0, "skipped": 0}
    res = {"paths": [], "lines": [], "files": 0, "encrypted": 0, "skipped": 0}
    want: List[Tuple[str, str]] = []
    for row in r.stdout.split(b"\0"):
        if not row:
            continue
        meta, _, path_b = row.partition(b"\t")
        path = path_b.decode("utf-8", "surrogateescape")
        mode, typ, sha, size = (meta.split() + [b"", b"", b"", b""])[:4]
        spans = det.path_hits(path, repo.name)
        if spans:
            res["paths"].append((path, spans))
        if typ != b"blob" or mode == b"120000":
            continue
        low = path.lower()
        if low.endswith(tuple(BINARY_SUFFIXES) + EXTRA_BINARY) or (size.isdigit() and int(size) > TREE_MAX_BLOB):
            res["skipped"] += 1
            continue
        want.append((sha.decode(), path))
    by_sha: Dict[str, List[str]] = {}
    for sha, path in want:
        by_sha.setdefault(sha, []).append(path)
    for sha, data in _cat_blobs(repo, list(by_sha)):
        if data.startswith(GITCRYPT_MAGIC):
            res["encrypted"] += len(by_sha[sha])
            continue
        if b"\0" in data[:8000]:
            res["skipped"] += len(by_sha[sha])
            continue
        text = _decode(data)
        if text is None:
            res["skipped"] += len(by_sha[sha])
            continue
        res["files"] += len(by_sha[sha])
        spans = det.text_hits(text)
        if not spans:
            continue
        starts = [0] + [m.end() for m in re.finditer("\n", text)]
        for path in by_sha[sha]:
            for s, e, k in spans:
                lineno = bisect.bisect_right(starts, s)
                res["lines"].append((path, lineno, k, text[s:e]))
    return res


def run_tree(roots: List[str], max_examples: int, strict: bool) -> int:
    try:
        det, notes = load_config()
    except ConfigError as e:
        print("%s (%s)" % (NOT_RUN, e), file=sys.stderr)
        return 3
    for n in notes:
        print(n)
    if det is None:
        print("%s 対象外 (一覧も学籍番号の形の設定も無い)" % HEADING)
        return 0
    failed: List[str] = []
    total_p = total_l = 0
    for root_s in roots:
        root = Path(root_s).expanduser()
        if not root.is_dir():
            failed.append(root_s)
            continue
        for repo in repos_under(root):
            res = scan_repo(det, repo)
            if res is None:
                failed.append(repo.name)
                continue
            np_, nl = len(res["paths"]), len(res["lines"])
            total_p += np_
            total_l += nl
            if not (np_ or nl):
                continue
            pk: Dict[str, int] = {}
            for _p, spans in res["paths"]:
                for k in {k for _s, _e, k in spans}:
                    pk[k] = pk.get(k, 0) + 1
            lk: Dict[str, int] = {}
            for _p, _n, k, _t in res["lines"]:
                lk[k] = lk.get(k, 0) + 1
            fmt = lambda d: ", ".join("%s %d" % (KIND_LABEL.get(k, k), v) for k, v in sorted(d.items()))
            print("%s: path %d 件 [%s] / 本文 %d 箇所 [%s] (平文 %d file を走査、 暗号化 %d・binary 等 %d は見ていない)"
                  % (repo.name, np_, fmt(pk), nl, fmt(lk), res["files"], res["encrypted"], res["skipped"]))
            for path, spans in res["paths"][:max_examples]:
                print("  path %s" % mask_text(path, spans))
            if np_ > max_examples:
                print("  … path ほか %d 件" % (np_ - max_examples))
            for path, lineno, k, tok in res["lines"][:max_examples]:
                print(_format("%s:%d" % (_masked_path(det, path, repo.name), lineno), k, tok))
            if nl > max_examples:
                print("  … 本文 ほか %d 箇所" % (nl - max_examples))
    print("%s fleet 合計 path %d 件 / 本文 %d 箇所 (値は伏せて表示、 報告だけ)" % (HEADING, total_p, total_l))
    if failed:
        print("%s (走査できない: %s)" % (NOT_RUN, ", ".join(failed[:5])), file=sys.stderr)
        return 3
    return 1 if (strict and (total_p or total_l)) else 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    import shutil
    import tempfile

    fails: List[str] = []

    def expect(label: str, ok: bool, detail: str = "") -> None:
        print("  %s %s%s" % ("PASS" if ok else "FAIL", label, "" if ok else "  " + detail[:400]))
        if not ok:
            fails.append(label)

    # 架空の値だけ (実在の名簿と関係しない)。 学籍番号の形の値は実行時に組み立てる (この file 自体が gate に当たらないように)
    shape = r"(?i)(?<![0-9a-z])[a-z][0-9]{2}[a-z][0-9]{3,4}(?![0-9a-z])"
    sid = lambda a, y, b, n: "%s%02d%s%s" % (a, y, b, n)  # noqa: E731
    ID1 = sid("A", 12, "X", "3456")       # 形に当たる架空の番号
    ID3 = sid("B", 12, "Y", "345")        # 数字 3 桁の形
    HEXLIKE = sid("a", 12, "b", "3456")   # 全部が 16 進 = git の短い hash に見える
    HEX16 = sid("A", 55, "E", "1029")     # 16 進の build 成果物の名前の一部
    KNOWN = sid("D", 0, "E", "0001")      # 既知の番号 (16 進に見える)
    FAKE = sid("x", 99, "m", "001")       # id_allow で外す試験用の架空番号
    cfg = {"schema": 1, "ids": [sid("A", 0, "X", "0001"), KNOWN],
           "full_names_cjk": ["仮野 名子", "架空田子"],
           "full_names_latin": [["karino", "nako"], ["kakuuda", "ko"]],
           "surnames_cjk": ["仮野", "教員野"], "surnames_latin": ["karino", "kakuuda", "tester", "abe"],
           "surname_allow": ["tester", "教員野"], "full_name_allow": ["見本 花子"]}
    det = Detector(dict(cfg, full_names_cjk=cfg["full_names_cjk"] + ["見本 花子"]), [shape])
    kinds = lambda spans: [k for _s, _e, k in spans]
    # (a) 学籍番号
    expect("(a) 学籍番号の形は当たる", kinds(det.ids("to %s now" % ID1.lower())) == ["id"])
    expect("(a) 3 桁の形も当たる", kinds(det.ids(ID3)) == ["id"])
    expect("(a) 大文字小文字を問わない", kinds(det.ids("mail %s@example.invalid" % ID1)) == ["id"])
    expect("(a) 全部が小文字の 16 進 (git の短い hash) は外す", det.ids("commit %s fixed" % HEXLIKE) == [])
    loose = Detector({}, [r"[A-Z][0-9]{2}[A-Z][0-9]{4}"])  # 前後の境を持たない形 (16 進の除外だけが効く)
    expect("(a) 16 進の長い連なりの中は外す", loose.ids("Foo.dll_%s%s.mvfrm" % (HEX16, "D67B" + "7172")) == []
           and kinds(loose.ids("x %s y" % HEX16)) == ["id"])
    expect("(a) 既知の学籍番号は 16 進に見えても当てる", kinds(det.ids("see %s" % KNOWN.lower())) == ["id-known"])
    expect("(a) 英数字に挟まれた形は当てない", det.ids("x%sy" % ID1.lower()) == [])
    det_a = Detector(dict(cfg, id_allow=[r"x\d{2}[a-z]\d{3,4}"]), [shape])
    expect("(a) id_allow の架空番号は外す (全体一致)", det_a.ids("t " + FAKE) == [] and det.ids("t " + FAKE) != [])
    # (b) 氏名
    expect("(b) 漢字の氏名 (空白なし)", kinds(det.names("連絡: 仮野名子 さん")) == ["name-cjk"])
    expect("(b) 漢字の氏名 (全角空白)", kinds(det.names("仮野　名子")) == ["name-cjk"])
    expect("(b) 境の分からない漢字の氏名はどこの空白も許す", kinds(det.names("架空 田子")) == ["name-cjk"])
    expect("(b) ローマ字 名姓", kinds(det.names("Dear Nako Karino,")) == ["name-latin"])
    expect("(b) ローマ字 姓名 (大文字の姓、 カンマ)", kinds(det.names("KARINO, Nako")) == ["name-latin"])
    expect("(b) ローマ字 path 形 (下線・camelCase)", kinds(det.names("karino_nako.pdf")) == ["name-latin"]
           and kinds(det.names("KarinoNako")) == ["name-latin"])
    expect("(b) 姓だけは本文で当てない", det.text_hits("仮野さん / Karino-san") == [])
    expect("(b) 長い語の一部は当てない", det.names("Karinonakoya") == [])
    expect("(b) full_name_allow の氏名は当てない", det.names("見本花子") == [])
    # (c) path の姓
    expect("(c) path のローマ字の姓 token", kinds(det.path_hits("todo/2026-01-01-karino-renraku.yaml"))
           == ["surname-latin"])
    expect("(c) path の漢字の姓 (後ろがかな・区切り)", kinds(det.path_hits("notes/仮野の件.md")) == ["surname-cjk"]
           and kinds(det.path_hits("宿泊_仮野_2026.pdf")) == ["surname-cjk"])
    expect("(c) 漢字の姓の後ろに漢字が続く (基金名など) は当てない", det.path_hits("規程/仮野記念奨学金.pdf") == [])
    expect("(c) camelCase の境も token の境", kinds(det.path_hits("KarinoMemo.md")) == ["surname-latin"])
    expect("(c) 長い語の一部は当てない", det.path_hits("karinos/x.md") == [])
    expect("(c) surname_allow の姓は当てない", det.path_hits("todo/x-tester-y.yaml") == []
           and det.path_hits("教員野/a.md") == [])
    expect("(c) 4 文字未満のローマ字の姓は当てない", det.path_hits("docs/abe-notes.md") == [])
    det_s = Detector(dict(cfg, surname_skip_repos=["papers"]), [shape])
    expect("(c) surname_skip_repos の repo では姓を当てない (氏名と学籍番号は当てる)",
           det_s.path_hits("x/karino-2020.pdf", "papers") == []
           and kinds(det_s.path_hits("x/karino-nako.pdf", "papers")) == ["name-latin"]
           and kinds(det_s.path_hits("x/karino-2020.pdf", "other")) == ["surname-latin"])
    det_m = Detector(dict(cfg, surname_conditional=["kakuuda", "共野", "tester"],
                          path_role_patterns=[r"(?<![a-z])suisen", "推薦", r"(?<![a-z])ta(?![a-z])"]), [shape])
    expect("(c) 条件つきの姓は役割の語の無い path では当てない (出張・共同研究)",
           det_m.path_hits("todo/2026-01-01-kakuuda-shucchou.yaml") == [] and det_m.path_hits("notes/共野_出張.md") == [])
    expect("(c) 条件つきの姓も役割の語と同じ path なら当てる",
           kinds(det_m.path_hits("todo/2026-01-01-kakuuda-suisensho.yaml")) == ["surname-latin"]
           and kinds(det_m.path_hits("推薦/共野.pdf")) == ["surname-cjk"]
           and kinds(det_m.path_hits("docs/ta-2026/kakuuda.yaml")) == ["surname-latin"])
    expect("(c) 役割の語は context (path 全体) にあれば効く = 既存の dir の下に足した file も止める",
           kinds(det_m.path_hits("kakuuda.pdf", None, "docs/suisen-2026/kakuuda.pdf")) == ["surname-latin"])
    expect("(c) 条件つきでない学生の姓は役割の語が無くても当てる (授業の学生は今までどおり)",
           kinds(det_m.path_hits("todo/2026-01-01-karino-shucchou.yaml")) == ["surname-latin"])
    expect("(c) 役割の語は token の一部では当たらない (data の ta は役割の語でない)",
           det_m.path_hits("data/kakuuda-2026.csv") == [])
    expect("(c) surname_allow は条件つきより優先 (教員と同じ姓は役割の語があっても当てない)",
           det_m.path_hits("todo/x-tester-suisen.yaml") == [])
    det_r = Detector(dict(cfg, surname_allow_by_repo={"talks": ["kakuuda"]}), [shape])
    expect("(c) surname_allow_by_repo はその repo の path でだけ外す",
           det_r.path_hits("docs/kakuuda/a.md", "talks") == []
           and kinds(det_r.path_hits("docs/kakuuda/a.md", "other")) == ["surname-latin"])
    # 伏せ方
    expect("伏せ字 = 先頭 1 文字 + 長さ", mask("karino") == "k…(6)")
    p = "todo/2026-01-01-karino-renraku.yaml"
    expect("path の伏せ字は当たりの部分だけ", mask_text(p, det.path_hits(p)) == "todo/2026-01-01-k…(6)-renraku.yaml")

    if shutil.which("git") is None:
        print("  SKIP e2e (git 不在)")
    else:
        me = os.path.abspath(__file__)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            lst = base / "identity.json"
            lst.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            pat = base / "patterns.txt"
            pat.write_text("# 形\n" + shape + "  # 行末の comment\n", encoding="utf-8")
            repo = base / "r"
            repo.mkdir()
            env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                       **{ENV_LIST: str(lst), ENV_PATTERNS: str(pat)})
            env.pop(ENV_SKIP, None)

            def git(*a: str) -> subprocess.CompletedProcess:
                return subprocess.run(["git", *a], cwd=str(repo), env=env, capture_output=True, check=False)

            def run(args: List[str], extra: Optional[Dict[str, str]] = None, cwd: Optional[Path] = None):
                r = subprocess.run([sys.executable, me, *args], cwd=str(cwd or repo), capture_output=True,
                                   check=False, env=dict(env, **(extra or {})))
                return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")

            def clean(out: str) -> bool:  # 値が素のまま出ていない
                return not any(v in out.lower() for v in ("karino", "仮野", "名子", ID1.lower(), KNOWN.lower()))

            git("init", "-q")
            git("config", "user.email", "t@example.invalid")
            git("config", "user.name", "t")
            (repo / "todo").mkdir()
            (repo / "todo" / "ok.yaml").write_text("id: ok\n", encoding="utf-8")
            (repo / "docs" / "karino-archive").mkdir(parents=True)
            (repo / "docs" / "karino-archive" / "old.md").write_text("old\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", "init", "--no-verify")
            rc, out = run(["--staged"])
            expect("--staged: 何も stage していなければ exit 0", rc == 0, out)
            (repo / "todo" / "2026-01-01-karino-renraku.yaml").write_text("id: x\n", encoding="utf-8")
            git("add", "-A")
            rc, out = run(["--staged"])
            expect("--staged: 学生の姓を含む新しい path で exit 1 + BLOCK 見出し", rc == 1 and BLOCK_HEADING in out, out)
            expect("--staged: 出力に値が素のまま出ない (path も伏せる)", clean(out) and "k…(6)" in out, out)
            rc, out = run(["--staged"], {ENV_SKIP: "0"})
            expect("--staged: escape hatch で exit 0", rc == 0, out)
            git("mv", "todo/2026-01-01-karino-renraku.yaml", "todo/2026-01-01-renraku.yaml")
            rc, out = run(["--staged"])
            expect("--staged: 姓を外した名前に直すと exit 0 (赤 → 緑)", rc == 0, out)
            git("commit", "-q", "-m", "t", "--no-verify")
            (repo / "docs" / "karino-archive" / "new.md").write_text("x\n", encoding="utf-8")
            git("add", "-A")
            rc, out = run(["--staged"])
            expect("--staged: HEAD に在った dir の下に足した file は、 dir 名を当てない", rc == 0, out)
            git("reset", "-q", "--hard")
            git("clean", "-qfd")
            git("mv", "todo/ok.yaml", "todo/%s.yaml" % ID1.lower())
            rc, out = run(["--staged"])
            expect("--staged: rename で学籍番号を名前に入れると exit 1", rc == 1 and "学籍番号の形" in out and clean(out), out)
            git("reset", "-q", "--hard")
            (repo / "notes.md").write_text("連絡先\n仮野 名子 (%s)\n" % ID1, encoding="utf-8")
            git("add", "notes.md")
            rc, out = run(["--staged"])
            expect("--staged: 平文 file の足した行の氏名と学籍番号で exit 1",
                   rc == 1 and "notes.md:2" in out and "氏名 (漢字)" in out and "学籍番号の形" in out and clean(out), out)
            (repo / "notes.md").write_text("連絡先\n学生 A\n", encoding="utf-8")
            git("add", "notes.md")
            rc, out = run(["--staged"])
            expect("--staged: 置き換えると exit 0", rc == 0, out)
            git("commit", "-q", "-m", "t", "--no-verify")
            (repo / "notes.md").write_text("連絡先\n学生 A\nKarino さんへ\n", encoding="utf-8")
            git("add", "notes.md")
            rc, out = run(["--staged"])
            expect("--staged: 本文の姓だけは当てない", rc == 0, out)
            git("reset", "-q", "--hard")
            # 暗号化 filter の代わり: clean が git-crypt と同じ先頭の magic + 可逆な変換を書く
            (repo / ".gitattributes").write_text("secret/** filter=fakecrypt\n", encoding="utf-8")
            (base / "enc.py").write_text("import sys, base64\nd = sys.stdin.buffer.read()\n"
                                         "sys.stdout.buffer.write(b'\\x00GITCRYPT\\x00' + base64.b64encode(d))\n")
            (base / "dec.py").write_text("import sys, base64\nd = sys.stdin.buffer.read()\n"
                                         "sys.stdout.buffer.write(base64.b64decode(d[10:]))\n")
            git("config", "filter.fakecrypt.clean", '"%s" "%s"' % (sys.executable, base / "enc.py"))
            git("config", "filter.fakecrypt.smudge", '"%s" "%s"' % (sys.executable, base / "dec.py"))
            (repo / "secret").mkdir()
            (repo / "secret" / "roster.csv").write_text("%s,仮野 名子\n" % ID1, encoding="utf-8")
            git("add", ".gitattributes", "secret/roster.csv")
            blob = subprocess.run(["git", "cat-file", "blob", ":secret/roster.csv"], cwd=str(repo), env=env,
                                  capture_output=True).stdout
            rc, out = run(["--staged"])
            expect("--staged: 暗号化される file (index が暗号文) の中身は見ない",
                   blob.startswith(GITCRYPT_MAGIC) and rc == 0, out + repr(blob[:12]))
            git("commit", "-q", "-m", "t", "--no-verify")
            # commit message
            msg = base / "msg"
            msg.write_text("fix: 仮野名子 の件\n\n# 仮野 名子 (comment 行)\n", encoding="utf-8")
            rc, out = run(["--commit-msg", str(msg)])
            expect("--commit-msg: 氏名で exit 1 (1 行目だけ)", rc == 1 and "commit message:1" in out
                   and "commit message:3" not in out and clean(out), out)
            msg.write_text("fix: see %s\n" % ID1, encoding="utf-8")
            rc, out = run(["--commit-msg", str(msg)])
            expect("--commit-msg: 学籍番号の形で exit 1", rc == 1 and "学籍番号の形" in out, out)
            msg.write_text("fix: karino さんの件 (姓だけ)\n\n# ------------------------ >8 ------------------------\n"
                           "+仮野 名子\n", encoding="utf-8")
            rc, out = run(["--commit-msg", str(msg)])
            expect("--commit-msg: 姓だけと scissors 行から後は当てない", rc == 0, out)
            lst_m = base / "identity-msg.json"
            lst_m.write_text(json.dumps(dict(cfg, surname_message_repos=["r"], surname_conditional=["共野"]),
                                        ensure_ascii=False), encoding="utf-8")
            msg.write_text("fix: 仮野さんの件\n", encoding="utf-8")
            rc, out = run(["--commit-msg", str(msg)], {ENV_LIST: str(lst_m)})
            expect("--commit-msg: surname_message_repos の repo では姓だけでも exit 1 (値は伏せる)",
                   rc == 1 and "commit message:1" in out and "姓 (漢字)" in out and clean(out), out)
            msg.write_text("fix: 共野さんの立替の件\n", encoding="utf-8")
            rc, out = run(["--commit-msg", str(msg)], {ENV_LIST: str(lst_m)})
            expect("--commit-msg: その repo では条件つきの姓も役割の語によらず exit 1", rc == 1, out)
            msg.write_text("fix: 教員野さんの件\n", encoding="utf-8")
            rc, out = run(["--commit-msg", str(msg)], {ENV_LIST: str(lst_m)})
            expect("--commit-msg: surname_allow の姓 (教員) はその repo でも当てない", rc == 0, out)
            lst_o = base / "identity-other.json"
            lst_o.write_text(json.dumps(dict(cfg, surname_message_repos=["other-repo"]), ensure_ascii=False),
                             encoding="utf-8")
            msg.write_text("fix: 仮野さんの件\n", encoding="utf-8")
            rc, out = run(["--commit-msg", str(msg)], {ENV_LIST: str(lst_o)})
            expect("--commit-msg: 一覧に無い repo では姓だけを当てない", rc == 0, out)
            # --tree
            (repo / "plain.md").write_text("x\nKarino Nako\n", encoding="utf-8")
            (repo / "docs" / ("%s.txt" % ID1.lower())).write_text("y\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", "t", "--no-verify")
            rc, out = run(["--tree", str(base)])
            expect("--tree: 報告して exit 0 (path の学籍番号・姓の dir、 本文の氏名、 暗号化 file は数えるだけ)",
                   rc == 0 and "r: path 2 件" in out and "plain.md:2" in out and "暗号化 1" in out and clean(out), out)
            rc, out = run(["--tree", str(repo), "--strict"])
            expect("--tree --strict: 当たりで exit 1", rc == 1, out)
            # 条件つきの姓 (e2e): 役割の語の dir が HEAD に在っても、 その下に足した file は path 全体で判定する
            lst_m = base / "identity-middle.json"
            lst_m.write_text(json.dumps(dict(cfg, surname_conditional=["kakuuda"],
                                             path_role_patterns=[r"(?<![a-z])suisen"]), ensure_ascii=False),
                             encoding="utf-8")
            (repo / "docs" / "suisen-2026").mkdir(parents=True)
            (repo / "docs" / "suisen-2026" / "README.md").write_text("x\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", "t", "--no-verify")
            (repo / "docs" / "suisen-2026" / "kakuuda.pdf").write_bytes(b"%PDF-1.4\n")
            git("add", "-A")
            rc, out = run(["--staged"], {ENV_LIST: str(lst_m)})
            expect("--staged: 条件つきの姓も、 HEAD に在る役割の語の dir の下に足した file は止める",
                   rc == 1 and BLOCK_HEADING in out and "kakuuda" not in out, out)
            git("reset", "-q", "--hard")
            git("clean", "-qfd")
            (repo / "todo" / "2026-01-02-kakuuda-shucchou.yaml").write_text("id: z\n", encoding="utf-8")
            git("add", "-A")
            rc, out = run(["--staged"], {ENV_LIST: str(lst_m)})
            expect("--staged: 条件つきの姓は役割の語の無い path なら通る", rc == 0, out)
            git("reset", "-q", "--hard")
            git("clean", "-qfd")
            # 設定の欠け・壊れ
            rc, out = run(["--staged"], {ENV_LIST: str(base / "none.json"), ENV_PATTERNS: str(base / "none.txt")})
            expect("--staged: 一覧も形も無い機械では何もせず exit 0", rc == 0 and out.strip() == "", out)
            (repo / "todo" / "2026-01-02-karino.yaml").write_text("id: y\n", encoding="utf-8")
            git("add", "-A")
            rc, out = run(["--staged"], {ENV_LIST: str(base / "none.json")})
            expect("--staged: 一覧が無く形だけの機械では 1 行出して形だけ検査 (姓は当てない)",
                   rc == 0 and "氏名の一覧が無い" in out, out)
            git("reset", "-q", "--hard")
            git("clean", "-qfd")
            bad = base / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            rc, out = run(["--staged"], {ENV_LIST: str(bad)})
            expect("--staged: 壊れた一覧は exit 3 + 1 行 (違反の 1 と区別)", rc == 3 and NOT_RUN in out, out)
            nogit = base / "nogit"
            nogit.mkdir()
            rc, out = run(["--staged"], {"GIT_CEILING_DIRECTORIES": str(base)}, cwd=nogit)
            expect("--staged: git repo でなければ exit 3 + 1 行", rc == 3 and NOT_RUN in out, out)
            rc, out = run(["--staged"], {"PATH": str(base / "no-bin")})
            expect("--staged: 内部の例外 (git が PATH に無い) は exit 3 + 1 行 (traceback の rc 1 にしない)",
                   rc == 3 and NOT_RUN in out and "Traceback" not in out, out)

    print("check-student-identifiers selftest:", "ALL PASS" if not fails else "FAIL %s" % fails)
    return 0 if not fails else 1


# ---------------------------------------------------------------- main

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="commit gate (新しい path + 平文 file の足した行)")
    mode.add_argument("--commit-msg", metavar="FILE", help="commit message (commit-msg hook の $1)")
    mode.add_argument("--tree", nargs="+", metavar="DIR", help="DIR (か直下の各 git repo) の HEAD の棚卸し")
    mode.add_argument("--selftest", action="store_true")
    ap.add_argument("--repo", help="--staged の repo (既定 = cwd)")
    ap.add_argument("--max", type=int, default=10, help="--tree で repo ごとに出す例の数 (既定 10)")
    ap.add_argument("--strict", action="store_true", help="--tree で当たりがあれば exit 1")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.staged:
        return run_staged(args.repo)
    if args.commit_msg:
        return run_commit_msg(args.commit_msg)
    return run_tree(args.tree, args.max, args.strict)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # 故障を違反 (1) と同じ値にしない
        msg = str(exc).splitlines()[0][:200] if str(exc) else ""
        print("%s (内部の例外 %s: %s)" % (NOT_RUN, type(exc).__name__, msg), file=sys.stderr)
        sys.exit(3)
