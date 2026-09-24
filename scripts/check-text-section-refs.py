#!/usr/bin/env python3
"""check-text-section-refs.py — 文中の「<file> §「<節名>」」 型の参照が、 実在する file の実在しない節を指していないかを検査する。

由来 (実測): 雛形の文中参照「詳細は `<dir>/README.md` §「<節名>」」 の節は、 実際には同じ dir の別 file にあった。
その雛形で文面を起草した session は README を節名で grep して hit 0 になり、 手元の前例と古い記述に倒れて
誤った手順の文面を作った。 markdown link の anchor (`[..](path#anchor)`) を見る検査はあったが、 **文中の
「path §節名」 は誰も見ていなかった**。 読み手 (人も agent も) にとって「指された file に節が無い」 は null であり、
null の後は手元の別の情報に倒れる。 規律側 = docs/convention-design-principles.md#text-section-refs。

見る参照の形 (source = track 済みの text。 同じ行に複数あってよい):
  F1 §「名」  `path §「節名」` / `path §『節名』` / `path §共通「節名」` / 続きの `… / §「節名2」` (同じ path)
  F2 §名     `path §節名` (鉤括弧なし。 節名の終わりは区切り文字で推定する = F1 より確度が低い)
  F3 #anchor 文中の `path.md#anchor` (markdown link の href でないもの。 F1/F2 と同じ参照に付いていれば両方を見る)
  F4 link    `[..](path.md#anchor)` (markdown link の href)
  (§ の直後が数字の `path §2.3` は番号参照 = 節の名前を持たないので数だけ数える。 path の無い §「名」 は見ない)

判定 (**不在と未判定を同じ値にしない** = docs/convention-design-principles.md#catch-all-branch-absorbs-covered-class):
  🔴 MISSING   file は 1 つに解決できた (実在・読める) のに、 節がその file に無い:
               F1 = 節名 (と ' — ' 等で切った前半) が見出し・anchor・太字の段落の頭・表の 1 列目のどこにも無く、 本文にも無い
               F2 = 節名の先頭の語さえ本文に無い (境界が推定なので本文 hit で通す = 確度を守る)
               F3/F4 = anchor が target の (<a id> ∪ GFM 見出し slug) に無い (.md の target だけ)
  🟡 BODY-ONLY F1 の節名が見出し等には無く本文にだけある (節の形になっていない = 数だけ。 --list で一覧)
  📜 RECORD    🔴 のうち source が履歴の記録 (archive・inbox・threads・incidents) か、 冒頭 20 行に
               `<!-- text-section-refs: record -->` を宣言した file (壊れた参照を報告・引用する RCA / 結果の doc)
  ⚪ UNRESOLVED file が 1 つに決まらない: 見つからない / 候補が複数 / 読めない (git-crypt lock・binary) / 見本の path
               (`X.md` `<file>` 等) / 節名が見本 (`<節名>` 等)。 **報告対象ではない** (数と --list だけ)。
               ただし候補が複数で、 どの候補にも節が無いものは 🟠 AMBIGUOUS-MISSING として別に数える (--list)
  🔴 には「その節名を見出しに持つ file」 の候補を付ける (= 直し方の手がかり。 同じ repo → 全 repo の順)。

file の解決 (上から順に、 最初に 1 つに決まったもの):
  `~/…` / 絶対 path → そのまま。 拡張子なしの README / CLAUDE / DESIGN / SESSION / AGENTS は `.md` を補う
  参照元の dir → 参照元 repo の root → base 直下 (= `<base>/<path>`、 先頭が repo 名の repo 跨ぎ path もここ)
  → 参照元 repo の track 済み file で path が後方一致するもの → base 直下の全 repo で後方一致するもの
  (README.md / SESSION.md 等の各 repo に必ずある名前は、 dir の付かない裸の名前なら参照元 repo の中だけで探す)

面 (同じ述語):
  [--root DIR]... [--base DIR]   fleet scan (既定)。 root 直下の各 git repo の track 済み text を worktree で読む。
                                 🔴 が 0 件なら何も出さない。 --surface = 枠なし / --strict = 🔴 で exit 1 /
                                 --list = ⚪ 🟠 🟡 の内訳も出す / --json
  --staged [--repo DIR]          commit 時。 stage した text の、 HEAD に無い行にある参照だけを見る (= 書いた本人に出す)。
                                 さらに stage した .md で消えた見出し・anchor を、 base 下の他の file が指していたら知らせる
                                 (= 節の名前を変えた本人に出す)。 呼び元は pre-commit の chain (**警告だけ、 commit は
                                 止めない**。 exit 1 / 3 のどちらでも commit を通す)
  --ack FILE                     承知済みの 🔴 (記録の中で壊れた参照を引用しているもの等) を 1 行 1 件で除く。
                                 行 = `<source の repo 相対 path>\t<path の字面>\t<節名 or #anchor>` (# で始まる行は注釈)
exit: 0 = 🔴 なし (--staged / --strict 以外は 🔴 があっても 0) / 1 = 🔴 あり (--staged / --strict) /
      3 = 検査が走っていない (git repo でない等。 1 行出す = docs/convention-design-principles.md#failure-exit-equals-violation-exit)
escape hatch: CLAUDE_TEXT_SECTION_REFS=0 (--staged を黙らせる)
selftest: python3 check-text-section-refs.py --selftest (一時 dir の fleet で陽性対照 = 「README §「節」 の節が同じ dir の
          別 file にある」 形、 陰性対照 = 見出し・anchor・太字・表・後方一致・repo 跨ぎ、 未判定の各 class、 --staged の
          追加行だけ・見出しを消した commit の inbound 警告、 pre-commit-bib に配線されていればそれを hook に据えた e2e =
          警告が出て commit は通る。 配線されていなければ skip と出す)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    from git_blob import read_blob  # git-crypt の path も平文で読む
except Exception:  # pragma: no cover
    read_blob = None  # type: ignore[assignment]

HEADING = "check-text-section-refs:"
ENV_SKIP = "CLAUDE_TEXT_SECTION_REFS"
DOC_ANCHOR = "claude-config/docs/convention-design-principles.md#text-section-refs"
GITCRYPT_MAGIC = b"\x00GITCRYPT"

# source として読む text (= 参照が書かれうるもの)。 target はどの拡張子でも読む (節の判定は拡張子で変える)
SCAN_EXTS = {".md", ".markdown", ".txt", ".yaml", ".yml", ".py", ".sh", ".tex"}
MAX_BYTES = 2_000_000
# 各 repo に必ずある名前 = 裸で書かれたら参照元 repo の中だけで探す (repo 跨ぎの後方一致で他 repo の同名に当てない)
SCAFFOLD_NAMES = {"readme.md", "claude.md", "design.md", "session.md", "agents.md", "setup.md", "todo.md",
                  "index.md", "notes.md", "conventions.md", "changelog.md", "license.md", "contributing.md"}
BARE_SCAFFOLD = {"README": "README.md", "CLAUDE": "CLAUDE.md", "DESIGN": "DESIGN.md",
                 "SESSION": "SESSION.md", "AGENTS": "AGENTS.md"}
# 見本 (placeholder) の path / 節名 = 判定しない
PLACEHOLDER_BASENAMES = {"x.md", "y.md", "foo.md", "bar.md", "file.md", "path.md", "doc.md", "xxx.md",
                         "example.md", "name.md", "some.md", "other.md", "a.md", "b.md", "target.md", "source.md"}
PLACEHOLDER_NAME_RE = re.compile(r"<[^>]*>|…|\.\.\.|^(?:節名|名前|name|title|x+|n+)$|\$\{|\{\{|%s", re.I)
# 節の名前でなく位置を言う語 (`README.md §冒頭` = 冒頭の部分) = 判定しない
POSITION_WORDS = {"冒頭", "末尾", "先頭", "最後", "全体", "本文", "上記", "下記", "前述", "後述", "同", "該当", "各", "表",
                  "全文", "目次", "本節", "同節", "当該", "上", "下", "前半", "後半", "頭", "尾", "top", "end"}
# 履歴の記録 (書いた時点の事実。 節が後で移っても参照は書き換えない) = 🔴 にせず 📜 で数える (--list)
RECORD_RE = re.compile(r"(^|/)(?:SESSION-archive|archive|inbox|threads)/|-archive(?:[./-]|$)|(^|/)(?:[\w-]+-)?incidents\.md$")
# file の冒頭 20 行にこの宣言があれば、 その file の 🔴 は 📜 (壊れた参照を報告・引用する RCA / 結果の doc 用)
RECORD_MARKER = "<!-- text-section-refs: record -->"


def is_record(rel_path: str, text: str) -> bool:
    return bool(RECORD_RE.search(rel_path)) or RECORD_MARKER in "\n".join(text.splitlines()[:20])


PLACEHOLDER_ANCHORS = re.compile(r"^(?:foo|bar|baz|x+|y|whatever|anchor|slug|some-?anchor|section|name|id|%s|L)$", re.I)
# 行番号の anchor (GitHub の `#L29` `#L10-L20`、 数字だけ) = 節ではない
LINE_ANCHOR_RE = re.compile(r"^(?:L?\d+(?:-L?\d+)?|L\d+C\d+)$")

# ---------------------------------------------------------------- 抽出
_PATH_BODY = (r"(?:~/|/)?(?:[\w.\-]+/)*[A-Za-z0-9_][A-Za-z0-9_.\-]*"
              r"\.(?:md|markdown|txt|ya?ml|py|sh|tex|toml|json|js|ts|html|css)")
PATH_TOK = r"(?P<path>" + _PATH_BODY + r"|README|CLAUDE|DESIGN|SESSION|AGENTS)"
LB = r"(?<![A-Za-z0-9_./\-~])"  # token の途中・URL の途中から始めない (日本語の直後からは始めてよい)
ANCHOR_TOK = r"(?:#(?P<anchor>[A-Za-z0-9_\-%.]*[A-Za-z0-9_]))?"  # 文中の anchor は ASCII (後ろの日本語を食わない)
SECT_OPEN = r"`?\)?[ \t\u3000]?§[ \t\u3000]?"
QUOTE_OPEN = "「『"
QUOTE_CLOSE = "」』"
RE_Q = re.compile(LB + PATH_TOK + ANCHOR_TOK + SECT_OPEN +
                  r"(?P<pre>[^\s「『§\d`|][^\s「『§`|]{0,11})?[「『](?P<name>[^」』\n]{1,160})[」』]")
RE_CONT = re.compile(r"\A[ \t\u3000]*(?:/|／|、|,|・|と|および|及び|\+)[ \t\u3000]*§[ \t\u3000]?"
                     r"(?:[^\s「『§\d`|]{1,12})?[「『](?P<name>[^」』\n]{1,160})[」』]")
RE_B = re.compile(LB + PATH_TOK + ANCHOR_TOK + SECT_OPEN + r"(?=[^\s「『\d§<>'\"`|(（)\]）〔〕【】])")  # 節名は line から切り出す (次の参照を食わない)
RE_N = re.compile(LB + PATH_TOK + ANCHOR_TOK + SECT_OPEN + r"\d")
RE_A = re.compile(LB + r"(?P<path>" + _PATH_BODY.replace(r"\.(?:md|markdown|txt|ya?ml|py|sh|tex|toml|json|js|ts|html|css)",
                                                        r"\.(?:md|markdown)") + r")#(?P<anchor>[A-Za-z0-9_\-%.]*[A-Za-z0-9_])")
RE_LINK = re.compile(r"\[(?:[^\[\]\n]|\[[^\]\n]*\])*\]\((?P<href>[^)\s]+?)(?:\s+\"[^\"]*\")?\)")
# F2 の節名の終わり
BARE_STOP = re.compile(r"[)\]）】〔〕【|\\、。，,;；`\"'<>「」『』]|\s[=→←/+]\s|\s[(（]|[(（]| {2,}|\s—\s|\s-\s|\s(?=[ぁ-ん])|$")
BARE_TAIL = re.compile(r"(?:\s*(?:を参照|参照|の通り|のとおり|を見よ|を読む|に記載|にある|で定義|が正本|を正本|の手順|に従う|に書く|"
                       r"に移設|へ移設|に移した|準拠|参考|相当|同様|など|等|を|に|が|は|で|と|へ|も|の|や|から|まで|より))+$")


@dataclass
class Ref:
    line: int
    form: str          # F1 F2 F3 F4
    path_tok: str
    key: str           # 節名 (F1/F2) or anchor (F3/F4)
    raw: str
    anchor: str = ""   # F1/F2 に付いた #anchor


def _strip_md(s: str) -> str:
    return s.replace("**", "").replace("`", "").strip()


def _in_string_literal(line: str, pos: int) -> bool:
    """code の 1 行で pos が引用符の内側か (= selftest の fixture 文字列。 注釈行 `#` の中は内側と見ない)。"""
    head = line[:pos]
    if head.lstrip().startswith("#"):
        return False
    return head.count('"') % 2 == 1 or head.count("'") % 2 == 1


def extract_refs(text: str, code: bool = False) -> Tuple[List[Ref], int]:
    """(refs, 番号参照の数)。 code = .py / .sh の source (1 行の文字列 literal の中は拾わない)。"""
    refs: List[Ref] = []
    numbered = 0
    for ln, line in enumerate(text.splitlines(), 1):
        if "§" not in line and "#" not in line:
            continue
        spans: List[Tuple[int, int]] = []
        # markdown link: href の anchor は F4 で見る。 link 文字列の中の §「…」 は label (anchor 側が正本) = F1/F2 にしない
        link_text_spans: List[Tuple[int, int]] = []
        link_href_spans: List[Tuple[int, int]] = []
        f4: List[Ref] = []
        if "](" in line:
            for m in RE_LINK.finditer(line):
                href = m.group("href")
                link_href_spans.append((m.start("href"), m.end("href")))
                if "://" in href or href.startswith(("mailto:", "#")) or "#" not in href:
                    continue
                p, _, a = href.partition("#")
                if not re.search(r"\.(?:md|markdown)$", p) or not a:
                    continue
                link_text_spans.append((m.start(), m.start("href")))
                f4.append(Ref(ln, "F4", p, a, m.group(0)[:160]))

        def skip(pos: int) -> bool:  # `[x](path) §「名」` の href から始まる参照は見る (link に anchor が無ければ節名が唯一の手がかり)
            return (any(a <= pos < b for a, b in spans + link_text_spans)
                    or (code and _in_string_literal(line, pos)))

        if "§" in line:
            for m in RE_Q.finditer(line):
                if skip(m.start()):
                    continue
                spans.append((m.start(), m.end()))
                refs.append(Ref(ln, "F1", m.group("path"), _strip_md(m.group("name")), m.group(0),
                                m.group("anchor") or ""))
                rest, off = line[m.end():], m.end()
                while True:  # 続きの `/ §「名2」` は同じ path
                    c = RE_CONT.match(rest)
                    if not c:
                        break
                    refs.append(Ref(ln, "F1", m.group("path"), _strip_md(c.group("name")),
                                    c.group(0).strip(), m.group("anchor") or ""))
                    spans.append((off, off + c.end()))
                    off += c.end()
                    rest = rest[c.end():]
            for m in RE_N.finditer(line):
                numbered += 1
                spans.append((m.start(), m.end()))
            for m in RE_B.finditer(line):
                if skip(m.start()):
                    continue
                name = bare_name(line[m.end(): m.end() + 80])
                if (not name or not re.match(r"\w", name) or re.match(r"[ぁ-ん]", name)
                        or m.group("path") in BARE_SCAFFOLD):
                    continue  # 記号・助詞で始まる = 節名でない / 拡張子なしの README 等は鉤括弧つき (F1) だけ見る
                spans.append((m.start(), m.end()))
                refs.append(Ref(ln, "F2", m.group("path"), name, (m.group(0) + name)[:120], m.group("anchor") or ""))
        if "#" in line:
            refs.extend(r for r in f4 if not code)
            for m in RE_A.finditer(line):
                if any(a <= m.start() < b for a, b in link_href_spans) or (code and _in_string_literal(line, m.start())):
                    continue
                refs.append(Ref(ln, "F3", m.group("path"), m.group("anchor"), m.group(0)))
    # F1/F2 に付いた #anchor も F3 として見る (重複は除く)
    seen = {(r.line, r.path_tok, r.key) for r in refs if r.form == "F3"}
    for r in list(refs):
        if r.form in ("F1", "F2") and r.anchor and re.search(r"\.(?:md|markdown)$", r.path_tok):
            k = (r.line, r.path_tok, r.anchor)
            if k not in seen:
                seen.add(k)
                refs.append(Ref(r.line, "F3", r.path_tok, r.anchor, f"{r.path_tok}#{r.anchor}"))
    return refs, numbered


def bare_name(s: str) -> str:
    m = BARE_STOP.search(s)
    name = s[: m.start()] if m else s
    name = _strip_md(name)
    prev = None
    while prev != name:
        prev = name
        name = BARE_TAIL.sub("", name).strip().rstrip(".:：")
    return name


# ---------------------------------------------------------------- 正規化・節の索引
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―ー−"), "-")
_DROP = dict.fromkeys(map(ord, "「」『』\"'“”‘’*`[]\\\u200b"), None)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_DROP).lower()
    s = s.translate({ord("—"): "-", ord("–"): "-", ord("―"): "-", ord("−"): "-"})
    return re.sub(r"\s+", "", s)


def gfm_slug(text: str) -> str:
    s = re.sub(r"<[^>]+>", "", text).strip().lower()
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # link は text だけ残す
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    return re.sub(r"\s", "-", s)


RE_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
RE_AID = re.compile(r"<a\s+(?:id|name)\s*=\s*[\"']([^\"']+)[\"']", re.I)
RE_CURLY_ID = re.compile(r"\{#([\w\-]+)\}")
RE_BOLD_HEAD = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)*(?:[^\w\s]{1,3}\s*)?\*\*(.+?)\*\*")
RE_TABLE_CELL = re.compile(r"^\s*\|\s*([^|]+?)\s*\|")
RE_TEX = re.compile(r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*(?:\[[^\]]*\])?\{([^}]*)\}"
                    r"|\\label\{([^}]*)\}")
RE_YAML_KEY = re.compile(r"^\s*(?:-\s+)?([\w\-. ]+?)\s*:(?:\s|$)")
RE_COMMENT = re.compile(r"^\s*(?:#|//|%)+\s*(.+)$")


@dataclass
class SectionIndex:
    anchors: Set[str] = field(default_factory=set)
    struct: List[str] = field(default_factory=list)   # 正規化済みの節の名前
    raw_heads: List[str] = field(default_factory=list)  # 見出し (表示用)
    body: str = ""


def build_index(text: str, ext: str) -> SectionIndex:
    ix = SectionIndex(body=norm(text))
    slug_count: Dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        if ext in (".md", ".markdown", ".txt", ""):
            if re.match(r"^\s{0,3}(```|~~~)", line):
                in_fence = not in_fence
                continue
            for a in RE_AID.findall(line):
                ix.anchors.add(a)
            for a in RE_CURLY_ID.findall(line):
                ix.anchors.add(a)
            if in_fence:
                continue
            m = RE_HEAD.match(line)
            if m:
                h = RE_CURLY_ID.sub("", re.sub(r"<a\s[^>]*>\s*</a>", "", m.group(2))).strip()
                slug = gfm_slug(h)
                n = slug_count.get(slug, 0)
                slug_count[slug] = n + 1
                ix.anchors.add(slug if n == 0 else f"{slug}-{n}")
                ix.struct.append(norm(h))
                ix.raw_heads.append(h)
                continue
            b = RE_BOLD_HEAD.match(line)
            if b:
                ix.struct.append(norm(b.group(1)))
            t = RE_TABLE_CELL.match(line)
            if t and not re.match(r"^[\s:\-]+$", t.group(1)):
                ix.struct.append(norm(t.group(1)))
        elif ext == ".tex":
            for sec, lab in RE_TEX.findall(line):
                if sec:
                    ix.struct.append(norm(sec))
                    ix.raw_heads.append(sec)
                if lab:
                    ix.anchors.add(lab)
                    ix.struct.append(norm(lab))
        else:  # yaml / py / sh / その他: key と注釈行を節の名前とみなす
            if ext in (".yaml", ".yml"):
                k = RE_YAML_KEY.match(line)
                if k:
                    ix.struct.append(norm(k.group(1)))
            c = RE_COMMENT.match(line)
            if c:
                ix.struct.append(norm(c.group(1)))
            for a in RE_AID.findall(line):
                ix.anchors.add(a)
    ix.struct = [s for s in ix.struct if s]
    return ix


_PARTICLE_SPLIT = re.compile(r"(?<=[^\sぁ-ん])(?:が|を|に|は|で|と|へ|も|の|や|から|まで|より)")
_SPLITS = re.compile(r"\s+[—–-]{1,2}\s+|—|\s*[:：]\s*|\s*[（(]|\s+/\s+|、")


def name_variants(name: str) -> List[str]:
    """節名の引き方: 全体 / 先頭の `#`・`§` を落とした形 / ' — ' 等の前半 / 入れ子の「 の前 / `A §B` の A と B。"""
    out = []
    base = re.sub(r"^[#§\s]+", "", name)
    cands = [name, base] + _SPLITS.split(base)[:1] + [re.split(r"[「『]", base)[0]]
    if "§" in base:
        parts = [x.strip() for x in base.split("§") if x.strip()]
        cands += [parts[-1], parts[0]]
    for v in cands:
        n = norm(v)
        if n and n not in out:
            out.append(n)
    return out


def match_name(ix: SectionIndex, name: str, bare: bool) -> str:
    """'struct' / 'body' / 'none'。"""
    if bare:
        toks = name.split()
        variants = []
        for i in range(len(toks), 0, -1):
            variants.append(norm(" ".join(toks[:i])))
        first = variants[-1] if variants else ""
        for v in variants:
            if len(v) >= 2 and any(v in h for h in ix.struct):
                return "struct"
        if len(first) < 2:  # `§A` `§5a` 等 = 見出しの頭で引く
            for h in ix.struct:
                if h.lstrip("§").startswith(first) or re.match(r"^[\d.]*" + re.escape(first) + r"[.)\s:：]", h):
                    return "struct"
            return "none"
        # 境界が推定なので、 先頭の語の「最初の助詞の前」 まで縮めて本文で引く (`§規律が警告していた…` → `規律`)
        chunk = norm(_PARTICLE_SPLIT.split(toks[0])[0]) if toks else ""
        probes = [first] + ([chunk] if len(chunk) >= 2 else [])
        return "body" if any(p in ix.body for p in probes) else "none"
    vs = name_variants(name)
    for v in vs:
        if any(v in h for h in ix.struct):
            return "struct"
    full = vs[0] if vs else ""
    for h in ix.struct:  # 節名の方が長い (見出し + 補足) = 見出しが節名の頭にある
        if len(h) >= 4 and full.startswith(h):
            return "struct"
    for v in vs:
        if v in ix.body:
            return "body"
    return "none"


def match_anchor(ix: SectionIndex, anchor: str, prose: bool = False) -> bool:
    """link (F4) は anchor の完全一致。 文中 (F3) は読み手が file の中で探す手がかりなので、 anchor の頭一致
    (`#print-blocker` → `print-blocker-rule`) と、 見出し等に語として在ること (`#M01` → `## M01. …`、 `#2026-08-24`) も通す。"""
    try:
        from urllib.parse import unquote
        a = unquote(anchor)
    except Exception:  # pragma: no cover
        a = anchor
    low = {x.lower() for x in ix.anchors}
    if a in ix.anchors or a.lower() in low:
        return True
    if not prose:
        return False
    al = a.lower()
    if len(al) >= 3 and any(x.startswith(al) for x in low):
        return True
    na = norm(a)
    return len(na) >= 2 and any(na in h or norm(a.replace("-", " ")) in h for h in ix.struct)


# ---------------------------------------------------------------- file の解決
# commit 中の hook は GIT_INDEX_FILE (一時 index の絶対 path) 等を持つ。 他の repo の file 一覧を取るときに引き継ぐと
# その repo の index の代わりに commit 中の repo の一時 index を読む (= 一覧が化ける)。 他 repo を読むときは外す
_GIT_REPO_ENV = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")


def git_ls(repo: Path) -> List[str]:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_ENV}
    try:
        r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, timeout=60, env=env)
    except Exception:
        return []
    if r.returncode != 0:
        return []
    return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]


def repo_toplevel(p: Path) -> Optional[Path]:
    try:
        r = subprocess.run(["git", "-C", str(p), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                           timeout=30)
    except Exception:
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def read_text_file(p: Path) -> Optional[str]:
    try:
        if p.stat().st_size > MAX_BYTES:
            return None
        b = p.read_bytes()
    except Exception:
        return None
    if b.startswith(GITCRYPT_MAGIC) or b"\x00" in b[:4096]:
        return None
    return b.decode("utf-8", "replace")


class Fleet:
    """base 直下の repo 群の file 一覧 (後方一致の解決用) と、 target の節の索引の cache。"""

    def __init__(self, base: Path, overrides: Optional[Dict[Path, str]] = None):
        self.base = base
        self._repo_files: Dict[Path, List[str]] = {}
        self._repos: Optional[List[Path]] = None
        self._by_base: Optional[Dict[str, List[Path]]] = None
        self._ix: Dict[Path, Optional[SectionIndex]] = {}
        self._heads_cache: Dict[Path, List[Tuple[Path, List[str]]]] = {}
        self.hint_all_repos = True
        self.overrides = overrides or {}  # 絶対 path → 本文 (--staged の index 版)

    def repos(self) -> List[Path]:
        if self._repos is None:
            out = []
            try:
                for d in sorted(self.base.iterdir()):
                    if d.is_dir() and not d.is_symlink() and (d / ".git").exists():
                        out.append(d)
            except Exception:
                pass
            self._repos = out
        return self._repos

    def files(self, repo: Path) -> List[str]:
        if repo not in self._repo_files:
            self._repo_files[repo] = git_ls(repo)
        return self._repo_files[repo]

    def by_basename(self) -> Dict[str, List[Path]]:
        if self._by_base is None:
            d: Dict[str, List[Path]] = {}
            for repo in self.repos():
                for f in self.files(repo):
                    d.setdefault(os.path.basename(f).lower(), []).append(repo / f)
            self._by_base = d
        return self._by_base

    def index(self, p: Path) -> Optional[SectionIndex]:
        key = p.resolve() if p.exists() else p
        if key not in self._ix:
            text = self.overrides.get(key)
            if text is None:
                text = read_text_file(p)
            self._ix[key] = None if text is None else build_index(text, p.suffix.lower())
        return self._ix[key]

    def resolve(self, tok: str, src: Path, repo: Optional[Path]) -> Tuple[str, List[Path]]:
        """('ok', [p]) / ('ambiguous', [p...]) / ('notfound', []) / ('placeholder', [])。"""
        tok = tok.strip("`")
        tok = BARE_SCAFFOLD.get(tok, tok)
        bn = os.path.basename(tok).lower()
        if bn in PLACEHOLDER_BASENAMES or "<" in tok:
            return "placeholder", []
        if tok.startswith("~/") or tok.startswith("/"):
            p = Path(os.path.expanduser(tok))
            return ("ok", [p]) if p.is_file() else ("notfound", [])
        cands = [src.parent / tok]
        if repo is not None:  # 参照元の dir から repo root まで祖先を近い順に (sub-project の DESIGN.md 等)
            d = src.parent
            while d != repo and repo in d.parents:
                d = d.parent
                cands.append(d / tok)
            cands.append(repo / tok)
        cands.append(self.base / tok)
        for c in cands:
            if c.is_file():
                return "ok", [c]
        if tok.startswith("Claude/"):
            c = self.base / tok[len("Claude/"):]
            if c.is_file():
                return "ok", [c]
        first = tok.split("/", 1)[0]
        if "/" in tok and (self.base / first / ".git").exists():
            return "notfound", []  # repo 名で始まる明示の path なのに無い
        suffix = "/" + tok  # 後方一致は大小文字を区別する (`results.md` を `RESULTS.md` に当てない)
        if repo is not None:
            hits = [repo / f for f in self.files(repo) if ("/" + f).endswith(suffix)]
            if len(hits) == 1:
                return "ok", hits
            if len(hits) > 1:
                return "ambiguous", hits
        if "/" not in tok and bn in SCAFFOLD_NAMES:
            return "notfound", []
        hits = [p for p in self.by_basename().get(bn, []) if ("/" + str(p)).endswith(suffix)]
        if len(hits) == 1:
            return "ok", hits
        if len(hits) > 1:
            return "ambiguous", hits
        return "notfound", []

    def _heads(self, repo: Path) -> List[Tuple[Path, List[str]]]:
        if repo not in self._heads_cache:
            out = []
            for f in self.files(repo):
                if not f.endswith((".md", ".markdown")):
                    continue
                ix = self.index(repo / f)
                if ix is not None and ix.struct:
                    out.append((repo / f, ix.struct))
            self._heads_cache[repo] = out
        return self._heads_cache[repo]

    def heading_homes(self, name: str, prefer: Optional[Path], all_repos: bool = True, limit: int = 3) -> List[Path]:
        """節名を見出し (等) に持つ .md。 参照元の repo → (all_repos なら) 全 repo の順。"""
        vs = [v for v in name_variants(name) if len(v) >= 2]
        if not vs:
            return []
        out: List[Path] = []
        repos = ([prefer] if prefer else []) + ([r for r in self.repos() if r != prefer] if all_repos else [])
        for repo in repos:
            for p, struct in self._heads(repo):
                if any(any(v in h for h in struct) for v in vs):
                    out.append(p)
                    if len(out) >= limit:
                        return out
            if out and repo == prefer:
                return out
        return out


# ---------------------------------------------------------------- 判定
@dataclass
class Finding:
    status: str        # MISSING / BODY / UNRESOLVED / AMBIG_MISSING
    src: str           # 表示用 (base 相対)
    line: int
    form: str
    path_tok: str
    key: str
    target: str = ""
    why: str = ""
    homes: List[str] = field(default_factory=list)

    def ack_key(self) -> str:
        return f"{self.src}\t{self.path_tok}\t{self.key if self.form in ('F1', 'F2') else '#' + self.key}"


def rel(p: Path, base: Path) -> str:
    try:
        return str(p.resolve().relative_to(base.resolve()))
    except Exception:
        try:
            return str(p.relative_to(base))
        except Exception:
            return str(p)


def _check(fleet: Fleet, p: Path, ref: Ref) -> str:
    """'struct' / 'body' / 'none' / 'unreadable'。"""
    ix = fleet.index(p)
    if ix is None:
        return "unreadable"
    if ref.form in ("F3", "F4"):
        if p.suffix.lower() not in (".md", ".markdown"):
            return "unreadable"
        return "struct" if match_anchor(ix, ref.key, prose=(ref.form == "F3")) else "none"
    return match_name(ix, ref.key, bare=(ref.form == "F2"))


RE_STUB_MARK = re.compile(r"移設|移動した|moved to|superseded|正本は|正本 =")


def _stub_targets(fleet: Fleet, p: Path) -> List[Path]:
    """移設済みの stub (短い file が「移設」 と同じ basename の別 path を指す) なら、 その移設先。"""
    text = read_text_file(p)
    if text is None or len(text) > 20000 or not RE_STUB_MARK.search(text[:3000]):
        return []
    out = []
    for m in re.finditer(r"(?:~/|\.\./|/)?(?:[\w.\-]+/)+" + re.escape(p.name), text[:3000]):
        tok = m.group(0)
        st, paths = fleet.resolve(tok, p, repo_of(fleet, p))
        if st == "ok" and paths[0].resolve() != p.resolve():
            out.append(paths[0])
    return out


def repo_of(fleet: Fleet, p: Path) -> Optional[Path]:
    rp = p.resolve()
    for r in fleet.repos():
        rr = r.resolve()
        if rr == rp or rr in rp.parents:
            return r
    return None


def judge(fleet: Fleet, ref: Ref, src: Path, repo: Optional[Path], hints: bool = True) -> Optional[Finding]:
    """None = 通る。"""
    base = fleet.base
    srel = rel(src, base)
    key_is_anchor = ref.form in ("F3", "F4")

    def unres(why: str, target: str = "") -> Finding:
        return Finding("UNRESOLVED", srel, ref.line, ref.form, ref.path_tok, ref.key, target=target, why=why)

    if key_is_anchor and LINE_ANCHOR_RE.match(ref.key):
        return unres("行番号の anchor")
    if key_is_anchor and PLACEHOLDER_ANCHORS.match(ref.key):
        return unres("見本の anchor")
    if not key_is_anchor:
        if PLACEHOLDER_NAME_RE.search(ref.key):
            return unres("節名が見本")
        if norm(ref.key) in POSITION_WORDS or (ref.form == "F2" and norm(ref.key.split()[0]) in POSITION_WORDS):
            return unres("位置の語 (節の名前でない)")
    st, paths = fleet.resolve(ref.path_tok, src, repo)
    if st in ("placeholder", "notfound"):
        return unres("見本の path" if st == "placeholder" else "file が見つからない")
    results = [(p, _check(fleet, p, ref)) for p in paths]
    kinds = {k for _, k in results}
    if st == "ambiguous":
        if kinds & {"struct", "body"}:
            return None
        if kinds == {"none"}:
            return Finding("AMBIG_MISSING", srel, ref.line, ref.form, ref.path_tok, ref.key,
                           target=", ".join(rel(p, base) for p, _ in results[:4]), why=f"候補 {len(paths)} file のどれにも無い")
        return unres(f"候補 {len(paths)} file")
    p, k = results[0]
    if k == "unreadable":
        return unres("読めない (git-crypt lock / binary / 節を持たない種類)", rel(p, base))
    if k == "struct":
        return None
    if k == "body":
        if ref.form == "F2":
            return None
        return Finding("BODY", srel, ref.line, ref.form, ref.path_tok, ref.key, target=rel(p, base),
                       why="本文にはあるが見出し等の節の形でない")
    # 移設済みの stub なら移設先で引く (旧 anchor だけを残した stub に、 移設後に増えた節を指す参照)
    for q in _stub_targets(fleet, p):
        if _check(fleet, q, ref) in ("struct", "body"):
            return None
    # 同じ名前の別 file (各 repo の CLAUDE.md、 層ごとの同名 doc) にあるなら、 文脈で別 file を指している可能性 = 🟠
    bn = os.path.basename(BARE_SCAFFOLD.get(ref.path_tok, ref.path_tok))
    if "/" not in ref.path_tok.strip("`").lstrip("~/").rstrip("/") or bn.lower() in SCAFFOLD_NAMES:
        others = [q for q in fleet.by_basename().get(bn.lower(), []) if q.name == bn and q.resolve() != p.resolve()]
        hit = [q for q in others if _check(fleet, q, ref) in ("struct", "body")]
        if hit:
            return Finding("SAME_NAME", srel, ref.line, ref.form, ref.path_tok, ref.key, target=rel(p, base),
                           why="同じ名前の別 file にある (文脈で別の file を指している可能性)",
                           homes=[rel(q, base) for q in hit[:3]])
    f = Finding("MISSING", srel, ref.line, ref.form, ref.path_tok, ref.key, target=rel(p, base),
                why="anchor が無い" if key_is_anchor else "節名が file のどこにも無い")
    if hints and not key_is_anchor:
        homes = fleet.heading_homes(ref.key, repo, all_repos=fleet.hint_all_repos)
        f.homes = [rel(h, base) for h in homes if h.resolve() != p.resolve()]
    return f


def scan_repo(fleet: Fleet, repo: Path, hints: bool = True) -> Tuple[List[Finding], Dict[str, int]]:
    out: List[Finding] = []
    stats = {"refs": 0, "numbered": 0}
    for f in fleet.files(repo):
        if os.path.splitext(f)[1].lower() not in SCAN_EXTS:
            continue
        p = repo / f
        text = read_text_file(p)
        if text is None or ("§" not in text and "#" not in text):
            continue
        refs, n = extract_refs(text, code=f.endswith((".py", ".sh")))
        stats["numbered"] += n
        record = is_record(f, text)
        for r in refs:
            stats["refs"] += 1
            fd = judge(fleet, r, p, repo, hints=hints and not record)
            if fd:
                if fd.status == "MISSING" and record:
                    fd.status = "RECORD"
                out.append(fd)
    return out, stats


ACK_BASENAME = ".text-section-refs-ack"


def load_ack(path: Optional[str], repos: Iterable[Path] = ()) -> Set[str]:
    """--ack FILE と、 各 repo の root の .text-section-refs-ack (どちらも行 = `<repo>/<path>\t<path の字面>\t<節名 or #anchor>`)。"""
    out: Set[str] = set()
    for f in ([Path(path)] if path else []) + [r / ACK_BASENAME for r in repos]:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        out |= {ln.split("  #", 1)[0].rstrip() for ln in lines if ln.strip() and not ln.startswith("#")}
    return out


def fmt(f: Finding) -> str:
    key = f"§「{f.key}」" if f.form in ("F1", "F2") else f"#{f.key}"
    s = f"{f.src}:{f.line} → {f.path_tok} {key}"
    if f.target and f.target != f.path_tok:
        s += f" (= {f.target})"
    s += f" — {f.why}"
    if f.homes:
        s += f"。 見出しがあるのは: {', '.join(f.homes)}"
    return s


ICON = {"MISSING": "🔴", "AMBIG_MISSING": "🟠", "SAME_NAME": "🟠", "RECORD": "📜", "BODY": "🟡", "UNRESOLVED": "⚪"}


# ---------------------------------------------------------------- staged
def git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def blob_text(spec: str, repo: Path) -> Optional[str]:
    if read_blob is not None:
        rc, data = read_blob(spec, cwd=str(repo))
    else:  # pragma: no cover
        r = subprocess.run(["git", "show", spec], cwd=str(repo), capture_output=True)
        rc, data = r.returncode, r.stdout
    if rc != 0 or data.startswith(GITCRYPT_MAGIC):
        return None
    return data.decode("utf-8", "replace")


def run_staged(repo_arg: Optional[str], base_arg: Optional[str], ack: Set[str]) -> int:
    if os.environ.get(ENV_SKIP) == "0":
        return 0
    repo = repo_toplevel(Path(repo_arg or "."))
    if repo is None:
        print(f"{HEADING} 検査が走っていない (git repo でない)")
        return 3
    base = Path(base_arg) if base_arg else repo.parent
    ack = ack | load_ack(None, [repo])
    r = git(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], repo)
    if r.returncode != 0:
        print(f"{HEADING} 検査が走っていない (git diff 失敗)")
        return 3
    staged = [p for p in r.stdout.split("\0") if p]
    texts: Dict[Path, str] = {}
    heads: Dict[Path, Optional[str]] = {}
    for f in staged:
        if os.path.splitext(f)[1].lower() not in SCAN_EXTS:
            continue
        t = blob_text(f":{f}", repo)
        if t is None:
            continue
        texts[repo / f] = t
        heads[repo / f] = blob_text(f"HEAD:{f}", repo)
    if not texts:
        return 0
    fleet = Fleet(base, overrides={p.resolve(): t for p, t in texts.items()})
    fleet.hint_all_repos = False  # commit 時は参照元 repo の中だけで候補を探す (速さ)
    findings: List[Finding] = []
    for p, t in texts.items():
        if is_record(str(p.relative_to(repo)), t):
            continue  # 履歴の記録・宣言した記録の doc への追記には出さない
        old_lines = set((heads[p] or "").splitlines())
        refs, _ = extract_refs(t, code=p.suffix in (".py", ".sh"))
        lines = t.splitlines()
        for ref in refs:
            if lines[ref.line - 1] in old_lines:
                continue
            fd = judge(fleet, ref, p, repo)
            if fd and fd.status == "MISSING" and fd.ack_key() not in ack:
                findings.append(fd)
    # 節を消した / 名前を変えた本人に: 消えた見出し・anchor を他の file が指していないか
    inbound: List[Finding] = []
    for p, t in texts.items():
        if p.suffix.lower() not in (".md", ".markdown") or heads.get(p) is None:
            continue
        old_ix, new_ix = build_index(heads[p] or "", ".md"), build_index(t, ".md")
        lost_heads = [h for h in old_ix.struct if h not in set(new_ix.struct)]
        lost_anchors = old_ix.anchors - new_ix.anchors
        if not lost_heads and not lost_anchors:
            continue
        inbound += find_inbound(fleet, p, repo, lost_heads, lost_anchors, ack)
    if not findings and not inbound:
        return 0
    print(f"{HEADING} 文中の節参照が、 実在しない節を指している ({len(findings) + len(inbound)} 件、 commit は止めない)")
    for f in findings:
        print(f"  🔴 {fmt(f)}")
    for f in inbound:
        print(f"  🔴 (この commit で消えた節を指している) {fmt(f)}")
    print(f"  直し方: 節のある file を指す (できれば `path#anchor` にする)。 承知済みなら ack に 1 行。 正本 = {DOC_ANCHOR}")
    return 1


def find_inbound(fleet: Fleet, target: Path, repo: Path, lost_heads: List[str], lost_anchors: Set[str],
                 ack: Set[str]) -> List[Finding]:
    out: List[Finding] = []
    tres = target.resolve()
    bn = target.name
    stem = target.stem
    for r in fleet.repos():
        for f in fleet.files(r):
            if os.path.splitext(f)[1].lower() not in SCAN_EXTS:
                continue
            p = r / f
            if p.resolve() == tres:
                continue
            text = fleet.overrides.get(p.resolve()) or read_text_file(p)
            if text is None or (bn not in text and stem not in text):
                continue
            refs, _ = extract_refs(text, code=f.endswith((".py", ".sh")))
            for ref in refs:
                if os.path.basename(BARE_SCAFFOLD.get(ref.path_tok, ref.path_tok)) != bn:
                    continue
                st, paths = fleet.resolve(ref.path_tok, p, r)
                if st != "ok" or paths[0].resolve() != tres:
                    continue
                was = (ref.key in lost_anchors) if ref.form in ("F3", "F4") else \
                    any(any(v in h for h in lost_heads) for v in name_variants(ref.key))
                if not was:
                    continue
                fd = judge(fleet, ref, p, r, hints=False)
                if fd and fd.status == "MISSING" and fd.ack_key() not in ack:
                    out.append(fd)
    return out


# ---------------------------------------------------------------- fleet
def repos_under(root: Path) -> List[Path]:
    if (root / ".git").exists():
        return [root]
    out = []
    try:
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.is_symlink() and (d / ".git").exists():
                out.append(d)
    except Exception:
        pass
    return out


def run_fleet(roots: List[str], base_arg: Optional[str], ack: Set[str], surface: bool, strict: bool,
              list_all: bool, as_json: bool) -> int:
    all_f: List[Finding] = []
    stats = {"refs": 0, "numbered": 0, "repos": 0}
    for root in roots:
        rp = Path(os.path.expanduser(root))
        if not rp.is_dir():
            print(f"{HEADING} 検査が走っていない (root {rp} が無い)")
            return 3
        base = Path(base_arg) if base_arg else (rp.parent if (rp / ".git").exists() else rp)
        fleet = Fleet(base)
        for repo in repos_under(rp):
            ack = ack | load_ack(None, [repo])
            fs, st = scan_repo(fleet, repo)
            stats["repos"] += 1
            stats["refs"] += st["refs"]
            stats["numbered"] += st["numbered"]
            all_f += fs
    missing = [f for f in all_f if f.status == "MISSING" and f.ack_key() not in ack]
    acked = [f for f in all_f if f.status == "MISSING" and f.ack_key() in ack]
    stale_ack = sorted(ack - {f.ack_key() for f in acked})  # 直った / 行が動いた = 一覧から消す行
    by = {k: [f for f in all_f if f.status == k] for k in ("AMBIG_MISSING", "SAME_NAME", "RECORD", "BODY", "UNRESOLVED")}
    if as_json:
        print(json.dumps({"stats": stats, "missing": [f.__dict__ for f in missing],
                          "acked": len(acked), "stale_ack": stale_ack, **{k.lower(): [f.__dict__ for f in v] for k, v in by.items()}},
                         ensure_ascii=False, indent=1))
        return 1 if (strict and missing) else 0
    if missing or list_all:
        if not surface:
            print(f"{HEADING} 文中の節参照 {stats['refs']} 件 ({stats['repos']} repo) — 実在する file の実在しない節を指すもの "
                  f"🔴 {len(missing)} 件 (承知済み {len(acked)} 件は除いた)")
        for f in missing:
            print(f"🔴 {fmt(f)}")
        if missing and not surface:
            print(f"  直し方: 節のある file を指す (できれば `path#anchor` にする)。 正本 = {DOC_ANCHOR}")
    if stale_ack and (list_all or strict):
        print(f"⚪ 承知済み一覧の古い行 {len(stale_ack)} 件 (該当する 🔴 が無い = 直ったか字面が変わった。 一覧から消す)")
        for k in stale_ack[:20]:
            print(f"   {k}")
    if list_all:
        print(f"-- 内訳: 🟠 候補が複数でどれにも無い {len(by['AMBIG_MISSING'])} / 🟠 同名の別 file にある {len(by['SAME_NAME'])} / 📜 履歴の記録の中 {len(by['RECORD'])} / 🟡 本文にだけある {len(by['BODY'])} / "
              f"⚪ 未判定 {len(by['UNRESOLVED'])} / 番号参照 (§数字) {stats['numbered']}")
        for k in ("AMBIG_MISSING", "SAME_NAME", "RECORD", "BODY", "UNRESOLVED"):
            for f in by[k]:
                print(f"{ICON[k]} {fmt(f)}")
    return 1 if (strict and missing) else 0


# ---------------------------------------------------------------- selftest
def selftest() -> int:
    import shutil
    import tempfile
    fails: List[str] = []

    def expect(label: str, ok: bool) -> None:
        print(("  ok: " if ok else "  NG: ") + label)
        if not ok:
            fails.append(label)

    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")

    def sh(args, cwd):
        return subprocess.run(args, cwd=str(cwd), env=env, capture_output=True, text=True)

    def write(p: Path, s: str) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s, encoding="utf-8")

    # 抽出の単体
    refs, n = extract_refs("詳細は `docs/guide/README.md` §「記入の手順」 参照 / x.md §2.3 / "
                           "[a](g.md#h) と `g.md#k` と a.md §「甲」 / §「乙」 と b.md §丙の節 を見る")
    forms = sorted((r.form, r.path_tok, r.key) for r in refs)
    expect("抽出: F1 (backtick の path)", ("F1", "docs/guide/README.md", "記入の手順") in forms)
    expect("抽出: 番号参照は数だけ", n == 1 and not any(r.key.startswith("2") for r in refs))
    expect("抽出: F4 link / F3 文中 anchor", ("F4", "g.md", "h") in forms and ("F3", "g.md", "k") in forms)
    expect("抽出: F1 の続き (/ §「乙」) は同じ path", ("F1", "a.md", "乙") in forms)
    expect("抽出: F2 の末尾の助詞を落とす", ("F2", "b.md", "丙の節") in forms)
    refs, _ = extract_refs("see https://example.com/a/b.md#x and [t](https://e.com/c.md#y)")
    expect("抽出: URL の中は拾わない", refs == [])
    refs, _ = extract_refs("`guide.md#fill-v2` §「記入の手順」")
    expect("抽出: path#anchor §「名」 は名と anchor の両方", {r.form for r in refs} == {"F1", "F3"})

    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "fleet"
        a = base / "alpha"
        b = base / "beta"
        for r in (a, b):
            r.mkdir(parents=True)
            sh(["git", "init", "-q"], r)
        # --- target 側
        write(a / "docs/guide/README.md", "# guide\n\n## 目次\n\n本文。\n")
        write(a / "docs/guide/guideline.md",
              "# 運用\n\n<a id=\"fill-v2\"></a>\n## 記入の手順 — 第 2 版\n\n手順。\n\n"
              "- **太字の段落の頭**: 説明\n\n| 行の名前 | 値 |\n|---|---|\n| 印刷物 | x |\n\n"
              "本文にだけある語句 ここ。\n")
        write(a / "DESIGN.md", "# design\n\n## cross_ref によるリポ横断参照\n")
        write(a / "notes/paper.tex", "\\section{Induced action}\\label{sec:hk}\n")
        write(a / "conf.yaml", "# ── 見出しの注釈 ──\nyearly_recurring:\n  - x\n")
        write(b / "conventions/mcp.md", "# mcp\n\n## 機械 enforcement\n")
        write(b / "README.md", "# beta\n")
        # --- source 側 (alpha)
        write(a / "docs/rca.md", "# RCA\n<!-- text-section-refs: record -->\n\n旧 `guide/README.md` §「記入の手順」 を指していた\n")
        write(a / "docs/manuals/template.md",
              "詳細は `../guide/README.md` §「記入の手順」 参照\n")  # 陽性対照 (節は guideline.md にある)
        write(a / "docs/guide/src.md",
              "\n".join([
                  "L1 `README.md` §「記入の手順」",                       # 陽性 (同じ dir の README)
                  "L2 `guideline.md` §「記入の手順」",                     # 見出し (— の前半)
                  "L3 `guideline.md#fill-v2` §「記入の手順 — 第 2 版」",       # anchor + 見出し全体
                  "L4 guideline.md §「太字の段落の頭」 / §「印刷物」",           # 太字 + 表 (続き)
                  "L5 guideline.md §「本文にだけある語句」",                    # 🟡
                  "L6 [x](guideline.md#fill-v2) と [y](guideline.md#no-such)",   # F4 陰性 / 陽性
                  "L7 `guideline.md#nope`",                                    # F3 陽性
                  "L8 DESIGN.md §「cross_ref によるリポ横断参照」",              # repo root
                  "L9 beta/conventions/mcp.md §「機械 enforcement」",          # repo 跨ぎ (先頭が repo 名)
                  "L10 mcp.md §「機械 enforcement」 と mcp.md §「存在しない節」",  # 後方一致 (全 repo で 1 つ)
                  "L11 X.md §「何か」 と missing.md §「何か」 と guideline.md §「<節名>」",  # ⚪ 見本 / 無い / 見本
                  "L12 notes/paper.tex §hk と conf.yaml §yearly_recurring と conf.yaml §見出しの注釈",
                  "L13 guideline.md §記入の手順 と guideline.md §全然無い語",   # F2 陰性 / 陽性
                  "L14 beta/nothere.md §「x」",                                 # ⚪ repo 名つきで無い
                  "L15 README.md §「guide」",                                   # README (同じ dir) の見出し
                  "L16 [`guideline.md`](guideline.md) §「無い手順」 と [g](guideline.md) §「記入の手順」",  # link の後ろの節名
              ]) + "\n")
        for r in (a, b):
            sh(["git", "add", "-A"], r)  # 走査は track 済みの file だけ
        fleet = Fleet(base)
        fs, st = scan_repo(fleet, a)
        miss = {(f.src.split("/")[-1], f.line, f.key) for f in fs if f.status == "MISSING"}
        unres = {(f.line, f.path_tok) for f in fs if f.status == "UNRESOLVED"}
        body = {(f.line, f.key) for f in fs if f.status == "BODY"}
        expect("陽性対照: 雛形の README §「節」 (節は同じ dir の guideline.md) = 🔴", ("template.md", 1, "記入の手順") in miss)
        expect("陽性: 同じ dir の README.md §「節」 = 🔴", ("src.md", 1, "記入の手順") in miss)
        hint = [f for f in fs if f.status == "MISSING" and f.src.endswith("template.md")]
        expect("🔴 に節のある file の候補が付く", bool(hint) and any("guideline.md" in h for h in hint[0].homes))
        for ln in (2, 3, 4, 8, 9, 12, 15):
            expect(f"陰性: L{ln} は通る", not any(f.line == ln and f.src.endswith("src.md") and f.status != "UNRESOLVED"
                                                 for f in fs))
        expect("陽性: F4 link の無い anchor", ("src.md", 6, "no-such") in miss)
        expect("陰性: F4 link の在る anchor", ("src.md", 6, "fill-v2") not in miss)
        expect("陽性: F3 文中の無い anchor", ("src.md", 7, "nope") in miss)
        expect("後方一致で解決 → 陽性 (存在しない節)", ("src.md", 10, "存在しない節") in miss)
        expect("陰性: 後方一致で解決 (在る節)", ("src.md", 10, "機械 enforcement") not in miss)
        expect("🟡 本文にだけある", (5, "本文にだけある語句") in body)
        expect("記録の宣言 (<!-- text-section-refs: record -->) のある file の 🔴 は 📜",
               [f.status for f in fs if f.src.endswith("docs/rca.md")] == ["RECORD"])
        expect("⚪ 見本の path / 無い file / 見本の節名は未判定", {(11, "X.md"), (11, "missing.md"), (11, "guideline.md")} <= unres)
        expect("⚪ repo 名つきの無い path は未判定 (🔴 にしない)", (14, "beta/nothere.md") in unres)
        expect("F2 陽性 (先頭の語さえ無い)", ("src.md", 13, "全然無い語") in miss)
        expect("F2 陰性", ("src.md", 13, "記入の手順") not in miss)
        expect("link の後ろの §「名」 も見る (陽性)", ("src.md", 16, "無い手順") in miss)
        expect("link の後ろの §「名」 も見る (陰性)", ("src.md", 16, "記入の手順") not in miss)
        # 候補が複数 (後方一致が 2 repo) → 🟠 (どれにも無い) / 通る (どれかに在る)
        write(b / "docs/guide/guideline.md", "# other\n\n## 別の節\n")
        d = base / "delta"
        d.mkdir()
        sh(["git", "init", "-q"], d)
        write(d / "amb.md", "guide/guideline.md §「別の節」 と guide/guideline.md §「どこにも無い」\n")
        for r in (a, b, d):
            sh(["git", "add", "-A"], r)
        fleet = Fleet(base)
        fs_d, _ = scan_repo(fleet, d)
        expect("曖昧: どれかの候補に在れば通る", not any(f.key == "別の節" for f in fs_d))
        expect("曖昧: どの候補にも無い = 🟠 (🔴 にしない)",
               [f.status for f in fs_d if f.key == "どこにも無い"] == ["AMBIG_MISSING"])
        fs, _ = scan_repo(fleet, a)
        # ack
        ackf = Path(td) / "ack.txt"
        tmpl = [f for f in fs if f.status == "MISSING" and f.src.endswith("template.md")][0]
        ackf.write_text("# 注釈\n" + tmpl.ack_key() + "  # 理由\nalpha/gone.md\tx.md\t消えた節\n", encoding="utf-8")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run_fleet([str(base)], None, load_ack(str(ackf)), surface=True, strict=True, list_all=False,
                           as_json=False)
        expect("ack した 🔴 は出ない / 残りで --strict = 1", rc == 1 and "template.md" not in buf.getvalue())
        expect("該当の無い ack 行は「古い行」 として出る", "古い行 1 件" in buf.getvalue() and "gone.md" in buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run_fleet([str(Path(td) / "nope")], None, set(), True, True, False, False)
        expect("root が無い = exit 3 (故障を違反と同じ値にしない)", rc == 3)

        # --- staged: 追加行だけ / 消えた見出しの inbound / pre-commit-bib e2e
        s = base / "gamma"
        s.mkdir()
        sh(["git", "init", "-q"], s)
        write(s / "docs/t.md", "# t\n\n## 旧い節\n\n古い参照 `README.md` §「無い節」\n")
        write(s / "README.md", "# r\n")
        write(s / "user.md", "`docs/t.md` §「旧い節」 を見よ\n")
        sh(["git", "add", "-A"], s)
        sh(["git", "commit", "-qm", "init"], s)
        write(s / "note.md", "新しい参照 `docs/t.md` §「旧い節」 と `docs/t.md` §「無い節2」\n")
        sh(["git", "add", "note.md"], s)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run_staged(str(s), str(base), set())
        out = buf.getvalue()
        expect("staged: 追加した行の不在参照 = 1 + 見出し", rc == 1 and "無い節2" in out and HEADING in out)
        expect("staged: HEAD にあった行の不在参照は出さない", "「無い節」" not in out.replace("無い節2", ""))
        sh(["git", "reset", "-q"], s)
        (s / "note.md").unlink()
        write(s / "docs/t.md", "# t\n\n## 新しい節\n\n古い参照 `README.md` §「無い節」\n")
        sh(["git", "add", "docs/t.md"], s)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run_staged(str(s), str(base), set())
        out = buf.getvalue()
        expect("staged: 見出しを消した commit に、 それを指す他 file (user.md) を知らせる",
               rc == 1 and "消えた節" in out and "user.md" in out)
        os.environ[ENV_SKIP] = "0"
        try:
            expect("staged: escape hatch", run_staged(str(s), str(base), set()) == 0)
        finally:
            os.environ.pop(ENV_SKIP, None)
        notrepo = Path(td) / "plain"
        notrepo.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            expect("staged: git repo でない = exit 3", run_staged(str(notrepo), None, set()) == 3)
        # e2e: pre-commit-bib を hook に据えて、 警告が出て commit は通る (= その検査が出したことまで見る)
        hook_src = Path(__file__).resolve().parent / "pre-commit-bib"
        wired = hook_src.is_file() and "check-text-section-refs" in hook_src.read_text(encoding="utf-8", errors="replace")
        if wired and shutil.which("bash"):
            hooks = s / ".git" / "hooks"
            hooks.mkdir(parents=True, exist_ok=True)
            (hooks / "pre-commit").unlink(missing_ok=True)
            os.symlink(hook_src, hooks / "pre-commit")
            write(s / "e2e.md", "e2e `docs/t.md` §「e2eで無い節」\n")
            sh(["git", "add", "e2e.md"], s)
            env_hook = {k: v for k, v in env.items() if k not in (
                "CLAUDE_CONFIG_AGENT_SESSION", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "CODEX_THREAD_ID")}
            env_hook["HOME"] = str(Path(td) / "home")  # 層3 の chain hook を呼ばない
            r = subprocess.run(["git", "commit", "-m", "e2e"], cwd=str(s), env=env_hook, capture_output=True, text=True)
            both = r.stdout + r.stderr
            expect("e2e: pre-commit-bib の警告に本検査の見出しと節名が出る", HEADING in both and "e2eで無い節" in both)
            expect("e2e: 警告だけで commit は通る", r.returncode == 0)
        else:
            print("  skip: e2e — 層1 pre-commit-bib に本検査が配線されていない (個人層の chain から呼ぶ構成なら、 その層の selftest が e2e を持つ)")
    if fails:
        print(f"selftest FAIL ({len(fails)})")
        return 1
    print("selftest ok")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", action="append", help="fleet scan の root (repo か、 repo を直下に持つ dir)")
    ap.add_argument("--base", help="repo 跨ぎの解決の基準 dir (既定 = root / repo の親)")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--repo")
    ap.add_argument("--ack")
    ap.add_argument("--surface", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    ack = load_ack(a.ack)
    if a.staged:
        return run_staged(a.repo, a.base, ack)
    roots = a.root or [str(Path.home() / "Claude")]
    return run_fleet(roots, a.base, ack, a.surface, a.strict, a.list, a.json)


if __name__ == "__main__":
    sys.exit(main())
