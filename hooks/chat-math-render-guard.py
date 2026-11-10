#!/usr/bin/env python3
"""chat-math-render-guard.py — Stop: 最終発話の数式 (`\\(…\\)` / `$…$` / `$$…$$` / `\\[…\\]`) のうち desktop の Code タブが生 TeX のまま出す形を、 本体の判定式を写して見つけ、 直した形を添えて追記させる

何を塞ぐか (正本 = conventions/chat-math-rendering.md#code-tab-katex):
  desktop の Code タブは Markdown の中の数式を KaTeX に渡す前に「数式らしいか」 の guard を通す。
  guard に落ちた式は `\\(` `\\)` のバックスラッシュだけが Markdown のエスケープとして消え、 `_` は強調に取られ、
  `(x_{2},\\dots,x_{N})` が `(x{2},\\dots,x{N})` のような生の文字列になる (赤字にならないので書いた側は気づけない)。
  規則を CLAUDE.md と memory に書いても、 1 つの返事に数十個の式を書く turn では守れなかった (実測) ので、 返事を機械で見る網を置く。

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
  実測では `\\\\0` を含む 1 行の pmatrix も描かれた = 止めると誤検出になる)。 数式を含む行の Markdown の
  構造 (見出し・箇条書き・引用) は本体も inline parser に同じ文字列を渡すので区別しない。 guard に落ちた `$` の閉じが
  次の式の開きになって落ちる連鎖は、 本体と同じに走査するが報告はしない (直すのは元の 1 箇所)。 app の式は版で変わる
  = 読んだ版は上に書いた。

fire = session の entrypoint が claude-desktop / claude-desktop-3p (右パネルの Code タブ = KaTeX で描く画面)
     ∧ 今の turn の最終発話 (fenced code block の外) に上の guard に落ちる式が 1 つ以上ある。
数式でない `$` は報告しない (`_non_math_dollar`): 金額 (`$4/$20` `$30 と`)・shell の変数 (`$CACHE/x` `"$file"`)・
  地の文の `$$`・中身が省略記号だけの `$…$`。 生の `$` のまま出るのが書き手の意図 (直すものが無い)。
挙動: fire 時 decision=block + reason (式ごとに 行番号・落ちた理由・直した形・直し方)。 返事の全文は出し直させず、
  崩れた式だけを直した形で並べる追記を書かせる (conventions/hook-authoring.md#stop-hook-addendum-not-reemission)。
  直した形は `fix_text` (意味を変えない書き換え = 区切り・1 文字の添字の `{}`・`\(` の前の空白) を同じ判定式に通したものだけ出す。
  stop_hook_active=true でも返事を判定する (#stop-hook-active-other-hooks): 今の続きの差し戻しの中にこの hook の差し戻しが
  あれば止めず数だけ記録、 他の hook の差し戻しだけなら 1 回止める、 続きの形が分からなければ黙る。
  表示の hook (hooks/chat-math-display-fix.py = MessageDisplay) がこの session で走った印 ($TMPDIR) があれば、 画面に出た
  直した文で判定する (= 表示で直った式では止めない)。 計器 = ~/.claude/state/chat-math-events.jsonl (差し戻し・差し戻しの
  後に残った式・表示で直した式の数。 2 MB で書くのをやめる。 test は CHAT_MATH_STATE_DIR で置き場を替える)。
  fail-open: transcript の不在・JSON の壊れ・例外は沈黙。 部品は持たない (単一 file。 Windows の copy 配線でも動く。
  表示の hook はこの file を部品として読む)。
校正: `--check FILE` (Markdown file を検査して列挙) / `--calibrate DAYS` (desktop の会話記録 〔全ての設定フォルダ
  ~/.claude*/projects〕 の、 画面に出た全ての版 = 各 turn の最後の文と差し戻された版に当てて、 発火数と内訳を出す)。
test = hooks/chat-math-render-guard.test.sh / 直す部品・追記・差し戻しの後の判定・数式でない `$` = hooks/chat-math-display-fix.test.sh
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import tempfile
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
    "BS_NOSYM": "中身に記号が無い: 添字は `{}` を付ける (`\\(E_{I}\\)`)、 1 文字は `$x$`、 `K(t)` 形・数は地の文の文字",
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
    "DL_NOSYM": "記号が無い (`$P_D$` `$E_I$` `$[0,1]$` `$xy$`): 添字は `{}` を付ける (`$E_{I}$`)、 数・区間は地の文 (`\\(…\\)` にしても記号が無ければ同じく落ちる)",
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
                shell_var = _shell_var_like(text, u, hi)
                if _non_math_dollar(text, u, hi):
                    u += 1
                    continue
                if open_space or (not chained and not digit_open and not shell_var
                                  and (r[1] in ("DL_SPACE", "DL_NEXT")
                                       or (r[1] == "DL_NOCLOSE" and _looks_like_math_open(text, u, hi)))) \
                        or (not chained and r[1] == "DL_DIGIT"):
                    findings.append({"line": lineno, "at": u, "code": r[1], "span": text[u:min(hi, u + 40)]})
                u += 1
                continue
            code = dollar_guard(text, u, r)
            span = text[u:r + 1]
            if code:
                if not chained and not _non_math_dollar(text, u, hi, r):
                    findings.append({"line": lineno, "at": u, "code": code, "span": span})
                rejected_closes.add(r)
                u += 1
                continue
            if table and "|" in span:
                findings.append({"line": lineno, "at": u, "code": "TABLE_PIPE", "span": span})
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
                    findings.append({"line": lineno, "at": u, "code": "BS_NOCLOSE", "span": text[u:min(hi, u + 40)]})
                    u += 2
                    continue
                if r == "EMPTY":
                    findings.append({"line": lineno, "at": u, "code": "BS_EMPTY", "span": text[u:u + 4]})
                    u += 2
                    continue
                body = text[u + 2:r]
                code = backslash_guard(text, u, body)
                span = text[u:r + 2]
                if code:
                    extra = {"prev": char_before(text, u)} if code == "BS_PREV" else {}
                    findings.append({"line": lineno, "at": u, "code": code, "span": span, **extra})
                    remembered_close = r
                    u += 2
                    continue
                if table and "|" in body:
                    findings.append({"line": lineno, "at": u, "code": "TABLE_PIPE", "span": span})
                u = r + 2
                continue
            if nxt == "[":
                close = text.find("\\]", u + 2, hi)
                findings.append({"line": lineno, "at": u, "code": "BRACKET", "span": text[u:(close + 2 if close != -1 else min(hi, u + 40))]})
                u = close + 2 if close != -1 else u + 2
                continue
            u += 2
            continue
        u += 1


SHELL_VAR = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def _shell_var_like(text: str, u: int, hi: int) -> bool:
    """`$` の直後が 2 文字以上の識別子で、 その後が数式の続き (`^` `{` `(` `\\` `_`) でない = shell の変数の形 (`$HOME/x` `$CODE_DIR`)。
    この形の `$` の対・閉じの事情は報告しない (本体の guard に落ちて地の文の文字のまま出る = 直すものが無い)。 1 文字の `$x` は数式として扱う。"""
    m = SHELL_VAR.match(text, u + 1, hi)
    if not m:
        return False
    nxt = text[m.end()] if m.end() < hi else ""
    return nxt not in ("^", "{", "(", "\\")


def _looks_like_math_open(text: str, u: int, hi: int) -> bool:
    """閉じの無い `$` を報告するのは、 数式を書き始めた形のときだけ = 直後が `\\`、 または直後の語 (空白・引用符・`/` まで) に
    `\\` `^` `{` がある (`$\\alpha` `$x^2`)。 通貨の `$5` と、 識別子だけの語 (shell の変数 `$s"` `$HOME/x` `$CODE_DIR`) は拾わない =
    閉じの無い 1 個の `$` は地の文の文字として出るので、 数式の形でなければ直すものが無い (実測: 引用した command の `$s` で誤検出)。"""
    nxt = text[u + 1] if u + 1 < hi else ""
    if not nxt or not (nxt == "\\" or nxt.isalpha()):
        return False
    if nxt == "\\":
        return True
    j = u + 1
    while j < hi and not text[j].isspace() and text[j] not in "\"'`/,;:)]}":
        if text[j] in "\\^{":
            return True
        j += 1
    return False


# ---- 数式でない `$` (金額・shell の変数・地の文の `$$`・書き方の言及) --------------------------------
# 本体の guard に落ちて生の `$` のまま出るのが書き手の意図なので、 報告もせず (Stop)、 書き換えもしない (表示)。

CURRENCY_HEAD = re.compile(r"\$\d[\d.,]*(?:[kKmMbB]n?)?(?=/\$|/\s|\s+(?:[^\W\d_]{2}|[^\x00-\x7f])|[^\x00-\x7f]|[、。,;:)）]|\s*$)")
SHELL_UPPER = re.compile(r"[A-Z_][A-Z0-9_]+")
ELLIPSIS_BODY = {"…", "...", "⋯", "……"}


def _non_math_dollar(text: str, u: int, hi: int, close=None) -> bool:
    """位置 u の `$` が数式として書かれていないか。
    - 金額: `$4/$20` `$10/$50 で` `$5 dollars` `$30 と` (数の後が `/$`・`/`+空白・空白+語・日本語・句読点・行末)。
      `$46.0$` `$30$` (閉じの `$` が続く) は数式として書いた数 = 金額にしない
    - shell の変数: `$CACHE/x` `$CODE_DIR` (大文字の名前で、 最初の `_` までが 3 文字以上) と、 後ろが引用符・`}` の識別子
      (`"$file"`)。 直後が `$` `^` `{` `(` `\\` `_` なら数式 (`$AB$` `$E_I(\\boldsymbol P)…$` `$P_{\\mathrm D}$`)。
      小文字の `$dE/dx$` は数式 (`/` だけでは shell と見なさない)
    - 地の文の `$$`: 隣が `$` で、 その組の後が空白か行末 (`Close $$ and`)。 行の途中の `$$x^2$$` は除く
    - 中身が省略記号だけ: `$…$` (書き方の言及)"""
    if CURRENCY_HEAD.match(text, u, hi):
        return True
    m = SHELL_VAR.match(text, u + 1, hi)
    if m:
        ident = m.group(0)
        nxt = text[m.end()] if m.end() < hi else ""
        if nxt not in ("$", "^", "{", "(", "\\", "_"):
            if SHELL_UPPER.fullmatch(ident) and len(ident.split("_")[0]) >= 3:
                return True
            if nxt in ('"', "'", "}"):
                return True
    if (u > 0 and text[u - 1] == "$") or (u + 1 < hi and text[u + 1] == "$"):
        j = u + 2 if (u + 1 < hi and text[u + 1] == "$") else u + 1
        if j >= hi or text[j].isspace():
            return True
    if close is not None and text[u + 1:close].strip() in ELLIPSIS_BODY:
        return True
    return False


# ---- 表示で直す書き換え (MessageDisplay の chat-math-display-fix.py と、 Stop の「直した形」 の案内が使う) ------
# 意味を変えない書き換えだけ: 区切りの付け替え (`$…$` → 直前に空白の `\(…\)`)・1 文字の添字と上付きに `{}`・
# `\(` の前の空白・表のセルの `|` を `\vert`・`\[…\]` を `$$…$$`・数だけの式を地の文へ。 直した行を同じ判定式に通し、
# 落ちる式の数が減るときだけ採る。 直せない式と数式でない `$` は触らない。

NUMBER_ONLY = re.compile(r"-?\d+(?:[.,]\d+)*")
SCRIPT_ONE = re.compile(r"(?<!\\)([_^])([A-Za-z0-9])")
FIXABLE = {"DL_LONG", "DL_NOSYM", "DL_SPACE", "DL_OPEN", "DL_NEXT", "DL_PROSE", "DL_PAREN", "DL_BRACE", "DL_TAIL",
           "DL_UNBAL", "BS_PREV", "BS_NOSYM", "BS_FLAG", "BRACKET", "TABLE_PIPE"}
MATHY = re.compile(r"[\\^_]")


def brace_scripts(body: str) -> str:
    """`E_I` `m^2` `x_1` の 1 文字の添字・上付きを `{}` で包む (`E_{I}`)。 描かれ方は同じで、 記号の条件を満たす。
    `_\\cmd` は包まない (`_\\mathrm{D}` を `_{\\mathrm}{D}` に壊さない)。"""
    return SCRIPT_ONE.sub(r"\1{\2}", body)


def _line_findings(line: str) -> list[dict]:
    return [f for f in scan(line) if f.get("line") != 0]


def _fix_candidates(line: str, f: dict):
    """(開始, 終了, [置き換えの候補]) か None。"""
    code, at, span = f["code"], f.get("at", -1), f["span"]
    if at < 0 or line[at:at + 1] not in ("$", "\\"):
        return None

    def space_before(pos: int) -> str:
        return "" if pos == 0 or line[pos - 1] in HT_BEFORE_BS else " "

    if code.startswith("BS_"):
        if not (span.startswith("\\(") and span.endswith("\\)")):
            return None
        body = span[2:-2]
        core = body.strip()
        sp = space_before(at)
        b2 = brace_scripts(body)
        if code == "BS_FLAG":
            b2 = re.sub(r"(^|\s)-", r"\1{-}", b2)
        cands = []
        if NUMBER_ONLY.fullmatch(core):
            cands.append(core)
        cands += [sp + "\\(" + b2 + "\\)", sp + "\\(" + body + "\\)", "$" + brace_scripts(core) + "$"]
        return at, at + len(span), cands
    if code == "BRACKET":
        if not span.endswith("\\]"):
            return None
        body = span[2:-2].strip()
        if line.strip() == span.strip():
            return at, at + len(span), ["$$" + body + "$$"]
        return at, at + len(span), [space_before(at) + "\\(" + body + "\\)"]
    if code == "TABLE_PIPE":
        if span.startswith("$"):
            inner = span[1:-1]
            return at, at + len(span), ["$" + inner.replace("\\|", "\\Vert ").replace("|", "\\vert ") + "$"]
        inner = span[2:-2]
        return at, at + len(span), ["\\(" + inner.replace("\\|", "\\Vert ").replace("|", "\\vert ") + "\\)"]
    if not code.startswith("DL_"):
        return None
    closed = len(span) >= 2 and span.startswith("$") and span.endswith("$") and code not in ("DL_OPEN", "DL_NEXT")
    if closed:
        start, end, body = at, at + len(span), span[1:-1]
    else:
        close = line.find("$", at + 1)
        if close == -1:
            return None
        if code == "DL_NEXT":
            return close + 1, close + 1, [" "]
        start, end, body = at, close + 1, line[at + 1:close]
    if code in ("DL_TAIL", "DL_UNBAL") and not MATHY.search(body):
        return None
    core = body.strip()
    b2 = brace_scripts(core)
    cands = []
    if NUMBER_ONLY.fullmatch(core):
        cands.append(core)
    cands += ["$" + b2 + "$", space_before(start) + "\\(" + b2 + "\\)"]
    return start, end, cands


def fix_line(line: str):
    """1 行の落ちる式を直す。 返り値 = (直した行, 直したもの [{code, old, new, span}], 直せなかった finding)。"""
    fixes, unfixed, tried = [], [], set()
    for _ in range(64):
        cur = _line_findings(line)
        todo = [f for f in cur if (f["code"], f.get("at"), f["span"]) not in tried]
        if not todo:
            break
        f = todo[0]
        cand = _fix_candidates(line, f) if f["code"] in FIXABLE else None
        if cand:
            s, e, options = cand
            for new_piece in options:
                new_line = line[:s] + new_piece + line[e:]
                if len(_line_findings(new_line)) < len(cur):
                    fixes.append({"code": f["code"], "old": line[s:e], "new": new_piece, "span": f["span"]})
                    line = new_line
                    break
            else:
                cand = None
        if not cand:
            tried.add((f["code"], f.get("at"), f["span"]))
            unfixed.append(f)
    return line, fixes, unfixed


def fix_text(text: str, state: dict | None = None):
    """返事の Markdown を行ごとに直す (code block・`$$` block の中は触らない)。
    state = {"fence": 開いている code block の印 or None, "display": `$$` block の中か, "bracket": `\\[` を `$$` にした block の中か}
    (行のまとまりごとに呼ぶ対話の端末で、 前のまとまりから引き継ぐ)。 返り値 = (直した文, 直したもの, 直せなかった finding, state)。"""
    st = dict(state or {})
    fence, display, bracket = st.get("fence"), bool(st.get("display")), bool(st.get("bracket"))
    out, fixes, unfixed = [], [], []
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and line.strip() == m.group(1):
                fence = None
            out.append(line)
            continue
        if m:
            fence = m.group(1)
            out.append(line)
            continue
        stripped = line.strip()
        if bracket and stripped == "\\]":
            out.append(line.replace("\\]", "$$", 1))
            bracket = display = False
            fixes.append({"code": "BRACKET", "old": "\\]", "new": "$$", "span": "\\]"})
            continue
        if DISPLAY_FENCE.match(line):
            display = not display
            out.append(line)
            continue
        if display:
            out.append(line)
            continue
        if DISPLAY_ONE_LINE.match(line):
            out.append(line)
            continue
        if stripped == "\\[" and len(line) - len(line.lstrip(" ")) <= 3:
            out.append(line.replace("\\[", "$$", 1))
            bracket = display = True
            fixes.append({"code": "BRACKET", "old": "\\[", "new": "$$", "span": "\\["})
            continue
        new_line, fx, ux = fix_line(line)
        out.append(new_line)
        fixes += fx
        unfixed += ux
    return "\n".join(out), fixes, unfixed, {"fence": fence, "display": display, "bracket": bracket}


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


OWN_MARK = "chat-math-render-guard:"
FEEDBACK_PREFIX = "Stop hook feedback:"
SESSION_ID_OK = re.compile(r"[A-Za-z0-9_-]{1,80}")
EVENTS_MAX_BYTES = 2 * 1024 * 1024


def _user_text(e: dict) -> str:
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _last_user_index(entries: list[dict]):
    for i in range(len(entries) - 1, -1, -1):
        if _is_real_user(entries[i]):
            return i
    return None


def own_block_in_chain(entries: list[dict]):
    """stop_hook_active の Stop で、 今の続きの差し戻しの中に自分の差し戻し (OWN_MARK) があるか
    (conventions/hook-authoring.md#stop-hook-active-other-hooks)。 今の turn が差し戻しの行で始まっていなければ None (= 黙る)。"""
    idx = _last_user_index(entries)
    if idx is None or not _user_text(entries[idx]).lstrip().startswith(FEEDBACK_PREFIX):
        return None
    for i in range(idx, -1, -1):
        e = entries[i]
        if not _is_real_user(e):
            continue
        t = _user_text(e)
        if not t.lstrip().startswith(FEEDBACK_PREFIX):
            return False
        if OWN_MARK in t:
            return True
    return False


def display_marker_path(session_id: str):
    """表示の hook (chat-math-display-fix.py) がこの session で走った印。 同じ engine の下の hook は同じ TMPDIR を見る。"""
    if not isinstance(session_id, str) or not SESSION_ID_OK.fullmatch(session_id):
        return None
    return os.path.join(tempfile.gettempdir(), "chat-math-display-fix", session_id)


def display_hook_ran(session_id: str) -> bool:
    p = display_marker_path(session_id)
    return bool(p) and os.path.exists(p)


def record_event(session_id: str, kind: str, n: int) -> None:
    """計器: 差し戻し・差し戻しの後に残った式・表示で直した式の数を足す (効いたかの前後比較に使う)。 失敗は黙る。"""
    try:
        d = os.environ.get("CHAT_MATH_STATE_DIR") or os.path.expanduser("~/.claude/state")
        if not os.path.isdir(d):
            return
        p = os.path.join(d, "chat-math-events.jsonl")
        if os.path.exists(p) and os.path.getsize(p) > EVENTS_MAX_BYTES:
            return
        sid = session_id[:8] if isinstance(session_id, str) else ""
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "session": sid, "kind": kind, "n": n}) + "\n")
    except Exception:
        pass


def build_reason(findings: list[dict], suggestions: dict | None = None) -> str:
    suggestions = suggestions or {}
    lines = ["%s この返事の数式のうち次の %d 箇所は Code タブで生の TeX のまま表示された (本体 2.31226.1 の判定式で検査)。 "
             "返事の全文は出し直さない。 崩れた式だけを、 どの文の式かを添えて直した形で並べる短い追記を書く:" % (OWN_MARK, len(findings))]
    by_code: dict[str, int] = {}
    for f in findings[:40]:
        span = f["span"].replace("\n", " ")
        if len(span) > 60:
            span = span[:57] + "…"
        prev = ""
        if f["code"] == "BS_PREV":
            p = f.get("prev")
            prev = " (直前の文字 = %s)" % ("文頭" if p is None else repr(p))
        fixed = suggestions.get(f["span"])
        tail = " → 直した形 `%s`" % fixed.strip() if fixed else ""
        lines.append("  - L%d %s: %s%s%s" % (f["line"], f["code"], span, prev, tail))
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
    if not isinstance(payload, dict):
        return 0
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not os.path.isfile(path):
        return 0
    sid = payload.get("session_id") if isinstance(payload.get("session_id"), str) else ""
    active = bool(payload.get("stop_hook_active"))
    try:
        entries = load_entries(path)
        if entrypoint_of(entries) not in DESKTOP_ENTRYPOINTS:
            return 0
        own = None
        if active:
            own = own_block_in_chain(entries)
            if own is None:
                return 0
        text = current_turn_text(entries)
        if not text:
            return 0
        shown, fixes, _, _ = fix_text(text)
        # 表示の hook がこの session で走っていれば、 画面に出たのは直した文 = 直した文で判定する
        findings = scan(shown if display_hook_ran(sid) else text)
    except Exception:
        return 0
    if not findings:
        return 0
    if active and own:
        record_event(sid, "after_own_block", len(findings))
        return 0
    record_event(sid, "block", len(findings))
    suggestions = {fx["span"]: fx["new"] for fx in fixes}
    print(json.dumps({"decision": "block", "reason": build_reason(findings, suggestions)}, ensure_ascii=False))
    return 0


def displayed_texts(entries: list[dict]) -> list[tuple[str, bool]]:
    """画面に出た版 = 各 turn の最後の text と、 Stop の差し戻しの直前の text (差し戻された版も画面に出ている)。
    返り値 = [(文, この hook が差し戻した版か)]。"""
    out, cur = [], ""
    for e in entries:
        if _is_real_user(e):
            if cur.strip():
                t = _user_text(e)
                out.append((cur, t.lstrip().startswith(FEEDBACK_PREFIX) and OWN_MARK in t))
            cur = ""
        elif e.get("type") == "assistant":
            for b in _blocks(e):
                if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                    cur = b["text"]
    if cur.strip():
        out.append((cur, False))
    return out


def calibrate(days: float, show: int) -> None:
    """desktop の会話記録 (全ての設定フォルダ ~/.claude*/projects) の、 画面に出た全ての版に当てる。"""
    roots = sorted(glob.glob(os.path.join(os.path.expanduser("~"), ".claude*", "projects")))
    cutoff = time.time() - days * 86400
    versions = fired = own_blocked = 0
    codes: dict[str, int] = {}
    shown = 0
    for root in roots:
        for path in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
            try:
                if os.path.getmtime(path) < cutoff:
                    continue
                entries = load_entries(path)
            except OSError:
                continue
            if entrypoint_of(entries) not in DESKTOP_ENTRYPOINTS:
                continue
            for text, blocked in displayed_texts(entries):
                versions += 1
                own_blocked += blocked
                fs = scan(text)
                if not fs:
                    continue
                fired += 1
                for f in fs:
                    codes[f["code"]] = codes.get(f["code"], 0) + 1
                    if shown < show:
                        shown += 1
                        print("%s  L%d %s: %s" % (os.path.basename(path)[:8], f["line"], f["code"], f["span"].replace("\n", " ")[:80]))
    print("roots=%d displayed=%d fired=%d (%.1f%%) own_blocked=%d" % (
        len(roots), versions, fired, 100.0 * fired / versions if versions else 0.0, own_blocked))
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
