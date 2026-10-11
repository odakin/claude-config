#!/usr/bin/env python3
"""chat-math-render-guard.py — Stop: 最終発話の数式 (`\\(…\\)` / `$…$` / `$$…$$` / `\\[…\\]`) のうち desktop の Code タブが生 TeX のまま出す形を、 本体の判定式を写して見つけ、 直し方を添えて出し直させる

何を塞ぐか (正本 = conventions/chat-math-rendering.md#code-tab-katex):
  desktop の Code タブは Markdown の中の数式を KaTeX に渡す前に「数式らしいか」 の guard を通す。
  guard に落ちた式は `\\(` `\\)` のバックスラッシュだけが Markdown のエスケープとして消え、 `_` は強調に取られ、
  `(x_{2},\\dots,x_{N})` が `(x{2},\\dots,x{N})` のような生の文字列になる (赤字にならないので書いた側は気づけない)。
  規則を CLAUDE.md と memory に書いても、 1 つの返事に数十個の式を書く turn では守れなかった (2026-10-09〜11 に 4 回、
  最大 63 箇所) ので、 返事を機械で見る網を置く。

述語 = 本体 2.31226.1 の描画 chunk の判定式をそのまま写す (conventions/hook-authoring.md#imitate-target-predicate):
  - 走査 (`c19e90103-*.js` の `Z`): backtick の code span の中は見ない。 `\\(` は同じ行の `\\)` で閉じる (`Yd`)。
    `$` は同じ行の、 直前が空白でなく直後が数字でない `$` で閉じる (`Jd`)。 guard に落ちた `$` は文字として
    1 つ進むので、 閉じの `$` が次の式の開きになる。 guard に落ちた `\\(` は `(` の文字になる。
  - `\\(…\\)` の guard (`cd535dee8-*.js` の `Kt`): (1) `\\(` の直前 (`*` `_` `~` は飛ばす) が 空白・タブ・改行・`(`・`[` か
    文頭。 (2) 中身 200 文字以内。 (3) 中身に `$`・backtick・`\\(`・`\\` + `| . + * ? 数字` が無い。
    (4) 中身が `-x` / `--x` (空白か文頭の直後) で始まる語を持つなら `\\英字` か `^` も要る (CLI の flag と区別)。
    (5) 中身に `\\ ^ { } = < > | ! +` のどれか、 または `x_1` 形 (英字 `_` 数字、 前後が英数字でない) の添字が要る。
  - `$…$` の guard (同 chunk の `cn`): 中身 60 文字以内・前後に空白なし・(3)(4) と同じ・末尾が演算子や開き括弧でない・
    code らしい並び (`=~` `&&` `@` `#` `"` `\\\\` 空白の後の `'` 末尾の `!`) でない・`**` `__` `~~` `](` HTML tag でない・
    括弧と `{}` が釣り合う・`|` が偶数個か末尾でない。 その上で「英字 1 文字」 か「数と四則の式 (先頭が数字でない)」 か
    「`\\ ^ { } = < > | ! +` か `a_b` / `x_{` 形の添字を含み、 `{}` の外に英字 4 連続・CJK 2 連続・`%` が無い」。
    `{` で始まる中身は不可、 `(` で始まる中身は数式か `\\英字`/`^` 持ちに限る。
  - 数字で始まる `$…$` は閉じの探索 (`Jd` → `Wd`) で別に絞る: 「数と四則の式 (120 文字以内、 × − · ÷ ≤ ≥ ≠ ≈ とギリシャ
    文字も可)」 か「`\\ { } ^ _ = < >` を含み `{}` の外に英字 4 連続・CJK 2 連続・`%` が無い」。 `5 dollars` 形 (数の後に
    空白と文字) と末尾が演算子の形は不可。 その上で `cn` を通る (= `$1/q$` は閉じは見つかるが `cn` の記号条件で落ちる)。
  - `\\[…\\]` は本体が数式にしない (常に生表示)。 表の行 (`|` で始まる行) の数式の中の `|` はセルの区切りに取られる。
  - 返事全体の gate (`ri`): `\\(`+`\\)` が無く、 `$…$` も `ti` の形 (記号を含む等) で 1 つも無い返事では KaTeX 自体を
    読まないので、 その返事の `$…$` は全部生表示。
  写していないもの: 1 行の `$$…$$` と複数行の `$$` block は見ない (block 側の判定 `an`/`Yt`/`Zt` は読み切れておらず、
  2026-10-11 の実測では `\\\\0` を含む 1 行の pmatrix も描かれた = 止めると誤検出になる)。 数式を含む行の Markdown の
  構造 (見出し・箇条書き・引用) は本体も inline parser に同じ文字列を渡すので区別しない。 guard に落ちた `$` の閉じが
  次の式の開きになって落ちる連鎖は、 本体と同じに走査するが報告はしない (直すのは元の 1 箇所)。 app の式は版で変わる
  = 読んだ版は上に書いた。

fire = session の entrypoint が claude-desktop / claude-desktop-3p (右パネルの Code タブ = KaTeX で描く画面)
     ∧ 今の turn の最終発話 (fenced code block の外) に上の guard に落ちる式が 1 つ以上ある。
挙動: fire 時 decision=block + reason (式ごとに 行番号・落ちた理由・直し方)。 stop_hook_active=true は即 exit 0。
  fail-open: transcript の不在・JSON の壊れ・例外は沈黙。 部品は持たない (単一 file。 Windows の copy 配線でも動く)。
校正: `--check FILE` (Markdown file を検査して列挙) / `--calibrate DAYS` (desktop の transcript の全 turn の最終発話に
  当てて発火数と内訳を出す。 2026-10-11 実測 = 失敗した返事 1 通の 63 箇所を全件検出、 誤検出 0)。
test = hooks/chat-math-render-guard.test.sh
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import time

DESKTOP_ENTRYPOINTS = {"claude-desktop", "claude-desktop-3p"}

# ---- 本体の定数 (cd535dee8-*.js、 2.31226.1) ---------------------------------------------------
MT = re.compile(r"[\\^{}=<>|!+]")
FT = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]_\d(?![A-Za-z0-9_])")
NT = re.compile(r"(?<![A-Za-z0-9_])(?:[a-z]_[A-Za-z0-9]|[A-Z]_[a-z0-9])(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])[A-Za-z]_\{")
L_DISPLAY = re.compile(r"[\\^{}=<>+*/()|!]")
UT_FLAG = re.compile(r"(^|\s)-{1,2}[A-Za-z]")
WT_TEX = re.compile(r"\\[a-zA-Z]|\^")
LN_BAD_ESC = re.compile(r"\\[|.+*?0-9]")
QT_TAIL = re.compile(r"(?:(?<![_^])[-+*]|[=<>/^_({\[,:;\\])$")
DOLLAR_T_CODE = re.compile(r"""[=!]~|&&|[@#"]|\\\\|(?:^|[\s(=,])'|[\s'"(/\[=,;]\^(?!\{)|(?:^|[\s({|&])!$""")
EN_MD = re.compile(r"\*\*|__|~~|\]\(|</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>|<[!?]")
_V = r"-?(?:\d+(?:[.,]\d+)*[a-z]{0,2}|[a-z])[!']*"
_TN = r"(?: ?[-+*/:] ?|, )"
_NN = rf"(?:{_V}|\({_V}(?:{_TN}{_V})*\))"
RN_ARITH = re.compile(rf"^{_NN}(?:(?:{_TN}|(?=\()){_NN})*$", re.I)
HT_BEFORE_BS = {" ", "\t", "\n", "(", "["}
ZT_MARKERS = {"*", "_", "~"}
IT_DOLLAR_MAX = 60
R_MAX = 1024
VT_LOOKBACK = 64
TI_MSG = re.compile(r"\$(?:[A-Za-z]|(?=[^$\n]*[\\^{}=<>|!+_()*/:,'-])[^\s$][^$\n]*[^\s$])\$(?![A-Za-z0-9$({/=])")
DD_SHEET = re.compile(r"^(\$\w{1,255}!?)?\$?[A-Z]{1,3}\$?[0-9]{1,7}(:(\$\w{1,255}!?)?\$?[A-Z]{1,3}\$?[0-9]{1,7})?")
OD_WORD = 555
# 数字で始まる `$…$` の閉じ (c19e90103-*.js の Wd / Fd / Id / Nd / Bd)
FD_PRICE = re.compile(r"^\d[\d.,]*(?:[a-z]{1,2}|/[a-z]+)?[*_~)\]:;]*\s+[^\W\d_]", re.I)
ID_TAIL = re.compile(r"(?:(?<![_^])[-+*]|[=<>/^_({\[,:\\×−·÷])\s*$")
ND_SYM = re.compile(r"[\\{}^_=<>]")
_LD = r"-?(?:\d+(?:[.,]\d+)*[a-zα-ω]{0,2}|[a-zα-ω])[!°]*"
_RD = r"(?: ?[-+*/:×−·÷≤≥≠≈] ?|, )"
_ZD = rf"(?:{_LD}|\({_LD}(?:{_RD}{_LD})*\))"
BD_ARITH = re.compile(rf"^{_ZD}(?:(?:{_RD}|(?=\()){_ZD})*$", re.I)


def _strip_braces(body: str) -> str:
    """本体 `Ud`: `{}` の中を空白にする。"""
    if "{" not in body:
        return body
    depth, out = 0, []
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
        elif depth == 0:
            out.append(ch)
            continue
        out.append(" ")
    return "".join(out)


def digit_body_ok(body: str) -> bool:
    """本体 `Wd`: 数字で始まる `$…$` の中身が数式として閉じてよいか。"""
    if FD_PRICE.search(body) or ID_TAIL.search(body):
        return False
    if len(body) <= 120 and BD_ARITH.match(body):
        return True
    return bool(ND_SYM.search(body)) and not prose_like(_strip_braces(body))


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
            or 0xF900 <= o <= 0xFAFF or 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F)


def _is_latin_greek_num(ch: str) -> bool:
    if ch in "$\\" or ch.isdigit():
        return True
    if not ch.isalpha():
        return False
    o = ord(ch)
    return o < 0x250 or 0x370 <= o <= 0x3FF or 0x1E00 <= o <= 0x1FFF


def prose_like(body: str) -> bool:
    """本体 `on`: `{}` の外 (と `\\x` の後) に英字 4 連続・CJK 2 連続・生の `%` があれば散文扱い。"""
    depth, out, i = 0, [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            out.append(body[i:i + 2] if depth == 0 else "  ")
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
        elif depth == 0:
            out.append(ch)
            i += 1
            continue
        out.append(" ")
        i += 1
    s = "".join(out)
    run = 0
    for j, ch in enumerate(s):
        if ch.isalpha():
            run += 1
            if run == 4 and (j - 4 < 0 or s[j - 4] != "\\"):
                return True
        else:
            run = 0
        if ch == "%" and (j == 0 or s[j - 1] != "\\"):
            return True
        if j > 0 and _is_cjk(ch) and _is_cjk(s[j - 1]):
            return True
    return False


def unbalanced(body: str) -> bool:
    """本体 `sn`: 括弧・`{}` の釣り合い、 `|` の奇数個で末尾 `|`。"""
    paren = brace = pipes = 0
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            i += 2
            continue
        if ch in "([":
            paren += 1
        elif ch in ")]":
            paren -= 1
            if paren < 0:
                return True
        elif ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
            if brace < 0:
                return True
        elif ch == "|":
            pipes += 1
        i += 1
    return paren != 0 or brace != 0 or (pipes % 2 == 1 and body.endswith("|"))


def has_bad_escape(body: str) -> bool:
    """本体 `un`: `$`・backtick・`\\(`・`\\` + `| . + * ? 数字`。"""
    return "$" in body or "`" in body or "\\(" in body or bool(LN_BAD_ESC.search(body))


def flag_like(body: str) -> bool:
    """本体 `dn` の後半: `-x` の語があって `\\英字` も `^` も無い (CLI の flag と見なす)。"""
    return bool(UT_FLAG.search(body)) and not WT_TEX.search(body)


def char_before(text: str, pos: int):
    """本体 `Gt`: pos の前を `*` `_` `~` を飛ばして見る (64 文字まで)。 文頭なら None。"""
    n, floor = pos - 1, pos - 1 - VT_LOOKBACK
    while n >= 0 and text[n] in ZT_MARKERS:
        if n <= floor:
            return text[n]
        n -= 1
    return text[n] if n >= 0 else None


# ---- `\(…\)` ----------------------------------------------------------------------------------

def backslash_guard(text: str, open_at: int, body: str) -> str | None:
    """本体 `Kt`。 通れば None、 落ちれば理由コード。"""
    if len(body) > R_MAX or len(body) > 200:
        return "BS_LONG"
    prev = char_before(text, open_at)
    if prev is not None and prev not in HT_BEFORE_BS:
        return "BS_PREV"
    if has_bad_escape(body):
        return "BS_BAD_ESC"
    if flag_like(body):
        return "BS_FLAG"
    if not (MT.search(body) or FT.search(body)):
        return "BS_NOSYM"
    return None


def find_backslash_close(text: str, open_at: int):
    """本体 `Yd`: 同じ行の `\\)` (奇数個の `\\`)。 返り値 = `\\)` の `\\` の位置、 空なら 'EMPTY'、 無ければ 'NONE'。"""
    n = open_at + 2
    while n < len(text):
        ch = text[n]
        if ch == "\n":
            return "NONE"
        if ch == ")":
            k, i = 0, n - 1
            while i > open_at + 1 and text[i] == "\\":
                k += 1
                i -= 1
            if k % 2 == 1:
                return "EMPTY" if n - 1 == open_at + 2 else n - 1
        n += 1
    return "NONE"


# ---- `$…$` ------------------------------------------------------------------------------------

def dollar_guard(text: str, open_at: int, close_at: int) -> str | None:
    """本体 `cn`。 通れば None、 落ちれば理由コード。"""
    body = text[open_at + 1:close_at]
    if len(body) > R_MAX:
        return "DL_LONG"
    if len(body) > IT_DOLLAR_MAX:
        return "DL_LONG"
    if body == "" or body[0].isspace() or body[-1].isspace():
        return "DL_SPACE"
    if has_bad_escape(body):
        return "DL_BAD_ESC"
    if QT_TAIL.search(body):
        return "DL_TAIL"
    if DOLLAR_T_CODE.search(body):
        return "DL_CODE"
    if EN_MD.search(body):
        return "DL_MD"
    if unbalanced(body):
        return "DL_UNBAL"
    if len(body) == 1:
        arith = bool(re.match(r"[A-Za-z]", body))
    else:
        arith = not body[0].isdigit() and bool(RN_ARITH.match(body))
    if body[0] == "{":
        return "DL_BRACE"
    if body[0] == "(" and not arith and not WT_TEX.search(body):
        return "DL_PAREN"
    if arith:
        return None
    if not (MT.search(body) or NT.search(body)):
        return "DL_NOSYM"
    if not re.search(r"[A-Za-z0-9\\]", body):
        return "DL_NOSYM"
    if prose_like(body):
        return "DL_PROSE"
    return None


def _sheet_ref_blocks(text: str, pos: int) -> bool:
    """本体 `qd`+`Jd`: `$` を含む語が `$A$1` 形の sheet 参照なら数式にしない。"""
    start = pos
    while start > 0 and text[start - 1] not in " \n":
        start -= 1
    if pos - start > OD_WORD:
        return False
    m = DD_SHEET.match(text[start:start + OD_WORD])
    if not m:
        return False
    end = start + len(m.group(0))
    return end > pos and (end >= len(text) or text[end] != "$")


def find_dollar_close(text: str, open_at: int):
    """本体 `Jd`。 返り値 = 閉じ `$` の位置、 無ければ ('NONE', 理由)。"""
    a = text[open_at + 1] if open_at + 1 < len(text) else None
    if a is None or a in " \n$" or (open_at > 0 and text[open_at - 1] == "$"):
        return ("NONE", "DL_OPEN")
    digit = a.isdigit()
    if digit and open_at > 0 and (text[open_at - 1].isalnum()):
        return ("NONE", "DL_OPEN")
    if not digit and _sheet_ref_blocks(text, open_at):
        return ("NONE", "DL_SHEET")
    n = open_at + 1
    while n < len(text):
        ch = text[n]
        if ch == "\n":
            return ("NONE", "DL_NOCLOSE")
        if ch == "$":
            k, i = 0, n - 1
            while i > open_at and text[i] == "\\":
                k += 1
                i -= 1
            if k % 2 == 1:
                n += 1
                continue
            if text[n - 1] == " ":
                return ("NONE", "DL_SPACE")
            body = text[open_at + 1:n]
            if digit and not digit_body_ok(body):
                return ("NONE", "DL_DIGIT")
            nxt = text[n + 1] if n + 1 < len(text) else None
            if nxt is not None and nxt.isdigit():
                return ("NONE", "DL_NEXT")
            if digit and nxt is not None and _is_latin_greek_num(nxt):
                return ("NONE", "DL_NEXT")
            return n
        n += 1
    return ("NONE", "DL_NOCLOSE")


# ---- 走査 ---------------------------------------------------------------------------------------

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
DISPLAY_ONE_LINE = re.compile(r"^ {0,3}\$\$(.+?)\$\$\s*$")
DISPLAY_FENCE = re.compile(r"^ {0,3}\$\$\s*$")

HINT = {
    "BS_PREV": "`\\(` の直前に半角空白を 1 つ入れる (読点・句点・括弧・日本語の直後は不可)",
    "BS_NOSYM": "中身に記号が無い: 1 文字は `$x$`、 `K(t)` 形は地の文の文字、 添字は `x_{i}` と `{}` 付き",
    "BS_FLAG": "空白の後の `-x` は CLI の flag と見なされる: `{-}x` と書くか `\\英字` を中に入れる",
    "BS_BAD_ESC": "中身に `$`・backtick・`\\(`・`\\|` `\\.` `\\+` `\\*` `\\?` `\\数字` を入れない (ノルムは `\\lVert v\\rVert`)",
    "BS_LONG": "中身が 200 文字超: 分けるか `$$…$$` に出す",
    "BS_NOCLOSE": "同じ行に `\\)` が無い: 1 行に収める",
    "BS_EMPTY": "中身が空",
    "BRACKET": "`\\[…\\]` は描かれない: `$$…$$` にする",
    "DL_OPEN": "開き `$` の直後が空白・`$`・行末 (`$ x $` は不可)",
    "DL_SPACE": "`$` の内側に空白を置かない",
    "DL_NOCLOSE": "同じ行に閉じ `$` が無い",
    "DL_NEXT": "閉じ `$` の直後に数字 (数字始まりなら英字も) を置かない",
    "DL_DIGIT": "数字で始まる `$…$` は「数と四則の式」 か「`\\ { } ^ _ = < >` を含む式」 だけ (`$5 dollars$` 形・末尾演算子は不可): `\\(…\\)` に",
    "DL_SHEET": "`$A$1` 形は表の参照と見なされる",
    "DL_LONG": "中身が 60 文字超: `\\(…\\)` にする",
    "DL_BAD_ESC": "中身に `$`・backtick・`\\(`・`\\|` `\\.` `\\+` `\\*` `\\?` `\\数字` を入れない",
    "DL_TAIL": "末尾が演算子・`,`・`:`・開き括弧・`\\`: `\\(…\\)` にするか式を閉じる",
    "DL_CODE": "code らしい並び (`&&` `@` `#` `\"` `=~` 空白後の `'` 末尾 `!`): `\\(…\\)` にする",
    "DL_MD": "`**` `__` `~~` `](` や HTML tag を含む: `\\(…\\)` にする",
    "DL_UNBAL": "括弧・`{}`・`|` が釣り合わない: `\\(…\\)` にするか閉じる",
    "DL_BRACE": "`{` で始まる中身は不可: `\\(…\\)` にする",
    "DL_PAREN": "`(` で始まる中身は数式か `\\英字`/`^` 持ちに限る: `\\(…\\)` にする",
    "DL_NOSYM": "記号が無い (`$P_D$` `$[0,1]$` `$xy$` `$dx$`): `\\(…\\)` にするか `$P_{D}$` と `{}` を付ける",
    "DL_PROSE": "`{}` の外に英字 4 連続・CJK・`%` がある: `\\(…\\)` にするか `\\mathrm{…}` で包む",
    "TABLE_PIPE": "表のセルの中の数式に `|` がある (セルの区切りに取られる): `\\mid` / `\\vert` にするか表の外へ",
    "MSG_NO_KATEX": "返事に `\\(…\\)` が無く、 `$…$` も記号を含む形が 1 つも無い: この返事の `$…$` は全部生表示になる",
}


def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def scan(text: str) -> list[dict]:
    """返事の Markdown を本体の順で走査し、 生表示になる式を列挙する。"""
    findings: list[dict] = []
    lines = text.split("\n")
    in_fence: str | None = None
    in_display = False
    offset = 0
    for lineno, line in enumerate(lines, 1):
        start = offset
        offset += len(line) + 1
        m = FENCE.match(line)
        if in_fence is not None:
            if m and m.group(1)[0] == in_fence[0] and len(m.group(1)) >= len(in_fence) and line.strip() == m.group(1):
                in_fence = None
            continue
        if m:
            in_fence = m.group(1)
            continue
        if DISPLAY_FENCE.match(line):
            in_display = not in_display
            continue
        if in_display:
            continue
        if DISPLAY_ONE_LINE.match(line):
            continue
        _scan_inline(text, start, start + len(line), lineno, _is_table_row(line), findings)
    # 本体 `ri`: `\(`+`\)` も display (`$$` の対・1 行の `$$…$$`・```math) も `ti` 形の `$…$` も無い返事は KaTeX を読まない
    if (not ("\\(" in text and "\\)" in text) and not _has_display(text) and not TI_MSG.search(text)
            and any(f["code"].startswith("DL_") for f in findings)):
        findings.append({"line": 0, "code": "MSG_NO_KATEX", "span": ""})
    return findings


def _has_display(text: str) -> bool:
    if re.search(r"(?:`{3}|~{3})math\b", text):
        return True
    for m in re.finditer(r"^ {0,3}\$\$(.*)\$\$\s*$", text, re.M):
        if L_DISPLAY.search(m.group(1)):
            return True
    return len(re.findall(r"^ {0,3}\$\$+\s*$", text, re.M)) >= 2


def _scan_inline(text: str, lo: int, hi: int, lineno: int, table: bool, findings: list[dict]) -> None:
    u = lo
    skip_bs_until = -1          # 本体 `p`: この行で閉じの無い `\(` を見た後は `\(` を見ない
    remembered_close = -1       # 本体 `v`: guard に落ちた `\(` の閉じを次の `\(` が再利用する
    rejected_closes: set[int] = set()   # guard に落ちた `$…$` の閉じ = 次の開きになるが、 その連鎖は報告しない
    while u < hi:
        ch = text[u]
        if ch == "`":
            k = u
            while k < hi and text[k] == "`":
                k += 1
            run = text[u:k]
            close = text.find(run, k, hi)
            while close != -1 and (close + len(run) < hi and text[close + len(run)] == "`"):
                j = close
                while j < hi and text[j] == "`":
                    j += 1
                close = text.find(run, j, hi)
            u = close + len(run) if close != -1 else k
            continue
        if ch == "$":
            chained = u in rejected_closes
            r = find_dollar_close(text, u)
            if isinstance(r, tuple):
                # 本体は `$` を文字として 1 つ進む。 閉じが無い等の理由は、 $ の対が意図された形の時だけ報告する
                # (`$ x $` = 開きの直後が空白で、 同じ行に閉じの `$` がある / 閉じの無い `$` の直後が英字か `\`)
                # 数字で始まる `$5` は通貨の形なので、 閉じの事情 (空白の後の `$3` 等) は報告しない
                digit_open = u + 1 < hi and text[u + 1].isdigit()
                open_space = (r[1] == "DL_OPEN" and u + 1 < hi and text[u + 1] == " "
                              and text.find("$", u + 2, hi) != -1 and not chained)
                if open_space or (not chained and not digit_open
                                  and (r[1] in ("DL_SPACE", "DL_NEXT")
                                       or (r[1] == "DL_NOCLOSE" and _looks_like_math_open(text, u, hi)))) \
                        or (not chained and r[1] == "DL_DIGIT"):
                    findings.append({"line": lineno, "code": r[1], "span": text[u:min(hi, u + 40)]})
                u += 1
                continue
            code = dollar_guard(text, u, r)
            span = text[u:r + 1]
            if code:
                if not chained:
                    findings.append({"line": lineno, "code": code, "span": span})
                rejected_closes.add(r)
                u += 1
                continue
            if table and "|" in span:
                findings.append({"line": lineno, "code": "TABLE_PIPE", "span": span})
            u = r + 1
            continue
        if ch == "\\":
            if u + 1 >= hi:
                u += 1
                continue
            nxt = text[u + 1]
            if nxt == "(" and u >= skip_bs_until:
                r = remembered_close if remembered_close > u + 2 else find_backslash_close(text, u)
                if r == "NONE":
                    skip_bs_until = hi
                    findings.append({"line": lineno, "code": "BS_NOCLOSE", "span": text[u:min(hi, u + 40)]})
                    u += 2
                    continue
                if r == "EMPTY":
                    findings.append({"line": lineno, "code": "BS_EMPTY", "span": text[u:u + 4]})
                    u += 2
                    continue
                body = text[u + 2:r]
                code = backslash_guard(text, u, body)
                span = text[u:r + 2]
                if code:
                    extra = {"prev": char_before(text, u)} if code == "BS_PREV" else {}
                    findings.append({"line": lineno, "code": code, "span": span, **extra})
                    remembered_close = r
                    u += 2
                    continue
                if table and "|" in body:
                    findings.append({"line": lineno, "code": "TABLE_PIPE", "span": span})
                u = r + 2
                continue
            if nxt == "[":
                close = text.find("\\]", u + 2, hi)
                findings.append({"line": lineno, "code": "BRACKET", "span": text[u:(close + 2 if close != -1 else min(hi, u + 40))]})
                u = close + 2 if close != -1 else u + 2
                continue
            u += 2
            continue
        u += 1


def _looks_like_math_open(text: str, u: int, hi: int) -> bool:
    """閉じの無い `$` を報告するのは、 直後が英字か `\\` で始まる (数式を書き始めた形) ときだけ (通貨の `$5` は拾わない)。"""
    nxt = text[u + 1] if u + 1 < hi else ""
    return bool(nxt) and (nxt == "\\" or nxt.isalpha())


# ---- transcript ----------------------------------------------------------------------------------

def _blocks(e: dict) -> list:
    c = (e.get("message") or {}).get("content")
    return c if isinstance(c, list) else []


def _is_real_user(e: dict) -> bool:
    if e.get("type") != "user":
        return False
    return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in _blocks(e))


def load_entries(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if isinstance(e, dict):
                out.append(e)
    return out


def entrypoint_of(entries: list[dict]) -> str | None:
    for e in entries:
        ep = e.get("entrypoint")
        if isinstance(ep, str) and ep:
            return ep
    return None


def turn_final_texts(entries: list[dict]) -> list[str]:
    """各 turn (実 user 行で区切る) の最終 assistant text。"""
    out, cur = [], ""
    for e in entries:
        if _is_real_user(e):
            if cur.strip():
                out.append(cur)
            cur = ""
        elif e.get("type") == "assistant":
            for b in _blocks(e):
                if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                    cur = b["text"]
    if cur.strip():
        out.append(cur)
    return out


def current_turn_text(entries: list[dict]) -> str:
    texts = turn_final_texts(entries)
    for i in range(len(entries) - 1, -1, -1):
        if _is_real_user(entries[i]):
            t = turn_final_texts(entries[i:])
            return t[-1] if t else ""
    return texts[-1] if texts else ""


def build_reason(findings: list[dict]) -> str:
    lines = ["chat-math-render-guard: この返事の数式のうち次の %d 箇所は Code タブで生の TeX のまま表示される (本体 2.31226.1 の判定式で検査)。 直して返事を出し直す:" % len(findings)]
    by_code: dict[str, int] = {}
    for f in findings[:40]:
        span = f["span"].replace("\n", " ")
        if len(span) > 60:
            span = span[:57] + "…"
        prev = ""
        if f["code"] == "BS_PREV":
            p = f.get("prev")
            prev = " (直前の文字 = %s)" % ("文頭" if p is None else repr(p))
        lines.append("  - L%d %s: %s%s" % (f["line"], f["code"], span, prev))
        by_code[f["code"]] = by_code.get(f["code"], 0) + 1
    if len(findings) > 40:
        lines.append("  - … ほか %d 箇所" % (len(findings) - 40))
        for f in findings[40:]:
            by_code[f["code"]] = by_code.get(f["code"], 0) + 1
    lines.append("直し方:")
    for code in by_code:
        lines.append("  - %s (%d): %s" % (code, by_code[code], HINT.get(code, "")))
    lines.append("規則の正本 = claude-config/conventions/chat-math-rendering.md#code-tab-katex。 迷う式は Unicode の地の文で書く。")
    return "\n".join(lines)


def hook_main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return 0
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not os.path.isfile(path):
        return 0
    try:
        entries = load_entries(path)
        if entrypoint_of(entries) not in DESKTOP_ENTRYPOINTS:
            return 0
        text = current_turn_text(entries)
        if not text:
            return 0
        findings = scan(text)
    except Exception:
        return 0
    if not findings:
        return 0
    print(json.dumps({"decision": "block", "reason": build_reason(findings)}, ensure_ascii=False))
    return 0


def calibrate(days: float, show: int) -> None:
    root = os.path.expanduser("~/.claude/projects")
    cutoff = time.time() - days * 86400
    turns = fired = 0
    codes: dict[str, int] = {}
    shown = 0
    for path in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
            entries = load_entries(path)
        except OSError:
            continue
        if entrypoint_of(entries) not in DESKTOP_ENTRYPOINTS:
            continue
        for text in turn_final_texts(entries):
            turns += 1
            fs = scan(text)
            if not fs:
                continue
            fired += 1
            for f in fs:
                codes[f["code"]] = codes.get(f["code"], 0) + 1
                if shown < show:
                    shown += 1
                    print("%s  L%d %s: %s" % (os.path.basename(path)[:8], f["line"], f["code"], f["span"].replace("\n", " ")[:80]))
    print("turns=%d fired=%d (%.1f%%)" % (turns, fired, 100.0 * fired / turns if turns else 0.0))
    for c, n in sorted(codes.items(), key=lambda x: -x[1]):
        print("  %s %d" % (c, n))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv[:1] == ["--check"] and len(argv) == 2:
        with open(argv[1], encoding="utf-8") as f:
            fs = scan(f.read())
        for f in fs:
            print("L%d %s: %s" % (f["line"], f["code"], f["span"].replace("\n", " ")[:100]))
        print("findings=%d" % len(fs))
        sys.exit(1 if fs else 0)
    if argv[:1] == ["--calibrate"] and len(argv) in (2, 3):
        calibrate(float(argv[1]), int(argv[2]) if len(argv) == 3 else 40)
        sys.exit(0)
    sys.exit(hook_main())
