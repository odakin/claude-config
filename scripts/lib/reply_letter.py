"""reply_letter.py — LaTeX で書いた返答書 (referee への point-by-point の返信) を、 答えの単位・文・原稿への参照・記号に分ける engine (CLI = scripts/reply-new-material-check.py と scripts/reply-position-refs.py)。

返答書の形の前提 (どれも引数で変えられる):
  - referee の文を引く macro (既定 `\\Q{…}`) の後から、 次の引用・次の項目 (`\\R1`・`\\A1` の類)・`\\end{itemize}`・節の見出し・文献表までを
    「1 つの答え」 とする。 答えの名前 = 直前の答えの項目の番号 + その項目の中の何番目の引用か (例 = `A2-1`)。
  - 原稿への参照は `Sec.~II\\,B` / `Secs.~II\\,A and III\\,C` / `Sec. 4.3` / `Fig.~2` / `Eq.~(12)` / `Eqs.~(3)--(5)` / `Appendix B` の形。
  - 原稿の節・図・式の番号は、 原稿を組んだ `.aux` の目次の行 (toc・lof) と `\\newlabel` から読む。

規約 = conventions/rebuttal-letter.md#unrelated-changes (答えが使う、 投稿の後に足した節・図・式は、 その答えの中で新しいと言う) と
#answer-fit-critic-instructions (返答書の中の記号は、 返答書の中の初出で定義する)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- text basics


def strip_comments(text: str) -> str:
    """`%` から行末までを空白に替える (`\\%` は残す)。 位置を保つため、 消した字は同じ数の空白にする。"""
    out = []
    for line in text.split("\n"):
        i, cut = 0, None
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut] + " " * (len(line) - cut))
    return "\n".join(out)


def brace_end(text: str, i: int) -> int:
    """text[i] == '{' に対応する '}' の次の位置。 対応が無ければ len(text)。"""
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(text)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def body_span(text: str) -> tuple[int, int]:
    """`\\begin{document}` の後から `\\end{document}` まで (無ければ全体)。"""
    b = text.find("\\begin{document}")
    e = text.find("\\end{document}")
    start = b + len("\\begin{document}") if b >= 0 else 0
    return start, (e if e >= 0 else len(text))


# ---------------------------------------------------------------- answers

DEFAULT_STOP = (r"\\(?:R|A)\d+\b|\\end\{itemize\}|\\(?:sub)*section\*?\{|\\begin\{thebibliography\}"
                r"|\\bibliography\{|\\clearpage")


@dataclass
class Answer:
    label: str          # 例 = "A2-1"
    item: str           # 例 = "A2"
    quote: str          # 引いた referee の文 (改行を寄せたもの)
    quote_span: tuple[int, int]
    start: int          # 答えの本文の始め (引用の閉じの直後)
    end: int            # 答えの本文の終わり
    body: str


def quote_spans(text: str, macro: str) -> list[tuple[int, int, int, int]]:
    """`\\<macro>{…}` の (macro の始め, 中身の始め, 中身の終わり, 閉じの次) の一覧。"""
    out = []
    for m in re.finditer(r"\\" + re.escape(macro) + r"\s*\{", text):
        open_brace = m.end() - 1
        close = brace_end(text, open_brace)
        out.append((m.start(), open_brace + 1, close - 1, close))
    return out


def segment_answers(text: str, quote_macro: str = "Q", item_macro: str = "A",
                    stop: str = DEFAULT_STOP) -> list[Answer]:
    """引用の macro の後ろを答えに切る。 text は comment を剥がしたもの (位置を保つ形) を渡す。"""
    stop_re = re.compile(stop)
    items = [(m.start(), m.group(1)) for m in re.finditer(r"\\" + re.escape(item_macro) + r"(\d+)\b", text)]
    quotes = quote_spans(text, quote_macro)
    answers: list[Answer] = []
    counts: dict[str, int] = {}
    for idx, (qs, cs, ce, qe) in enumerate(quotes):
        nxt = quotes[idx + 1][0] if idx + 1 < len(quotes) else len(text)
        m = stop_re.search(text, qe, nxt)
        end = m.start() if m else nxt
        item_no = None
        for pos, no in items:
            if pos < qs:
                item_no = no
        item = f"{item_macro}{item_no}" if item_no else "(項目の外)"
        counts[item] = counts.get(item, 0) + 1
        answers.append(Answer(label=f"{item}-{counts[item]}", item=item,
                              quote=" ".join(text[cs:ce].split()), quote_span=(qs, qe),
                              start=qe, end=end, body=text[qe:end]))
    return answers


def answer_at(answers: list[Answer], pos: int) -> Answer | None:
    for a in answers:
        if a.start <= pos < a.end:
            return a
    return None


def in_quotes(answers: list[Answer], pos: int) -> bool:
    return any(a.quote_span[0] <= pos < a.quote_span[1] for a in answers)


def letter_spans(text: str, answers: list[Answer], referee_macro: str, item_macro: str) -> list[tuple[int, int]]:
    """記号を拾う範囲 = 本文から referee の段落 (`\\R1` から次の `\\A1` まで)・引用・文献表を除いたもの。"""
    b0, b1 = body_span(text)
    holes = []
    for m in re.finditer(r"\\" + re.escape(referee_macro) + r"(\d+)\b", text):
        nxt = re.compile(r"\\" + re.escape(item_macro) + r"\d+\b").search(text, m.end())
        holes.append((m.start(), nxt.start() if nxt else m.end()))
    for a in answers:
        holes.append(a.quote_span)
    bs = text.find("\\begin{thebibliography}")
    if bs >= 0:
        be = text.find("\\end{thebibliography}", bs)
        holes.append((bs, be + len("\\end{thebibliography}") if be >= 0 else b1))
    holes.sort()
    spans, cur = [], b0
    for s, e in holes:
        if s > cur:
            spans.append((cur, min(s, b1)))
        cur = max(cur, e)
    if cur < b1:
        spans.append((cur, b1))
    return [(s, e) for s, e in spans if e > s]


# ---------------------------------------------------------------- sentences

_ABBREV = ["Secs.", "Sec.", "Eqs.", "Eq.", "Figs.", "Fig.", "Refs.", "Ref.", "e.g.", "i.e.", "et al.",
           "cf.", "vs.", "Tab.", "App.", "No.", "Nos.", "approx."]


def sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """text[start:end] を文に切った (始め, 終わり) の一覧。 `\\item` も文の切れ目にする。 略語の後の点では切らない。"""
    seg = text[start:end]
    masked = seg
    for ab in _ABBREV:
        masked = masked.replace(ab, ab.replace(".", "\x00"))
    cuts = [0]
    for m in re.finditer(r"(?<=[.?!])(?:\}|\$|\))?\s+(?=[A-Z\\$(])|\\item\b|\n\s*\n", masked):
        cuts.append(m.start() if m.group(0).startswith("\\item") else m.end())
    cuts.append(len(seg))
    spans = []
    for a, b in zip(cuts, cuts[1:]):
        if seg[a:b].strip():
            spans.append((start + a, start + b))
    return spans


# ---------------------------------------------------------------- references to the manuscript

def norm_num(s: str) -> str:
    return re.sub(r"\\,|\\ |~|\s|\(|\)|\.$", "", s)


@dataclass
class Ref:
    kind: str           # section / figure / equation / table
    number: str         # 寄せた番号 (例 = "IIB"、 "2"、 "12")
    raw: str
    pos: int
    foreign: bool = False   # 所有の語 (its / their / 文献の番号) が前にある = 引いた論文の節・図・式 (自分の原稿の番号でない)


# 参照の語の直前が所有の語か文献の番号 (`its Sec. 3.2` / `\cite{x}, Sec. 2` / `[12], Fig. 4` / `Ref. 12, Eq. (3)`)。
# 間に置けるのは空白・`~`・`\,`・comma・開き括弧だけ (`\cite{x}. Sec. II …` のように文が切れれば外さない)
FOREIGN_BEFORE = re.compile(
    r"(?:\b(?:its|their|his|her)|\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{[^}]*\}|\[\d+(?:\s*[,–-]\s*\d+)*\]"
    r"|\bRefs?\.(?:~|\\,|\\ |\s)*\d+)(?:'s)?(?:~|\\,|\\ |\s|,|\()*$", re.I)


def find_refs(text: str, start: int = 0, end: int | None = None) -> list[Ref]:
    end = len(text) if end is None else end
    out: list[Ref] = []
    pat = re.compile(
        r"(?P<kind>Secs?\.|Sections?|Appendix|Appendices|Figs?\.|Figures?|Eqs?\.|Equations?|Tables?|Tabs?\.)"
        r"(?:~|\\,|\\ |\s)*")
    for m in pat.finditer(text, start, end):
        k = m.group("kind").lower()
        kind = ("section" if k.startswith(("sec", "app")) else "figure" if k.startswith("fig")
                else "equation" if k.startswith("eq") else "table")
        j = m.end()
        nums: list[tuple[str, int]] = []
        if kind == "equation":
            while True:
                mm = re.match(r"\s*\((\w+)\)", text[j:end])
                if not mm:
                    break
                first = mm.group(1)
                nums.append((first, j))
                j += mm.end()
                rng = re.match(r"\s*(?:--|–|-)\s*\((\w+)\)", text[j:end])
                if rng:
                    a, b = first, rng.group(1)
                    if a.isdigit() and b.isdigit():
                        for x in range(int(a) + 1, int(b) + 1):
                            nums.append((str(x), j))
                    else:
                        nums.append((b, j))
                    j += rng.end()
                sep = re.match(r"\s*(?:,|and)\s*", text[j:end])
                if sep and re.match(r"\s*\(", text[j + sep.end():end]):
                    j += sep.end()
                    continue
                break
        else:
            num_re = re.compile(r"(?:[IVXLC]+(?:\\,|\\ |~)?[A-Z]?(?![a-z])|\d+(?:\.\d+)*|[A-Z](?![a-z]))")
            while True:
                mm = num_re.match(text, j, end)
                if not mm:
                    break
                nums.append((norm_num(mm.group(0)), j))
                j = mm.end()
                sep = re.match(r"(?:,\s*|\s+and\s+|\s*(?:--|–)\s*)", text[j:end])
                if sep and num_re.match(text, j + sep.end(), end):
                    j += sep.end()
                    continue
                break
        foreign = bool(FOREIGN_BEFORE.search(text[max(0, m.start() - 80):m.start()]))
        for n, p in nums:
            out.append(Ref(kind=kind, number=norm_num(n), raw=text[m.start():j].strip(), pos=m.start(), foreign=foreign))
    return out


# ---------------------------------------------------------------- .aux of the manuscript

@dataclass
class Item:
    kind: str           # section / figure / equation / table
    number: str         # 寄せた番号
    shown: str          # 組んだ番号の見え方 (例 = "II\\,B")
    title: str          # 節の題・図の caption (式は label)
    label: str = ""


@dataclass
class ManuscriptIndex:
    items: dict[tuple[str, str], Item] = field(default_factory=dict)
    titles: dict[str, set[str]] = field(default_factory=dict)   # kind -> 寄せた題・caption・label の集合
    labels: set[str] = field(default_factory=set)


def _title_key(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    s = re.sub(r"[^0-9a-z]", "", s.lower())
    return s[:80]


def _numberline(entry: str) -> tuple[str, str]:
    m = re.search(r"\\numberline\s*\{", entry)
    if not m:
        return "", entry
    e = brace_end(entry, m.end() - 1)
    num = entry[m.end():e - 1]
    rest = entry[e:]
    return num, rest


def parse_aux(aux_text: str) -> ManuscriptIndex:
    """`.aux` の toc・lof・lot の行と `\\newlabel` から、 節・図・表・式の番号と題を読む。"""
    idx = ManuscriptIndex()
    cur_sec = ""
    for m in re.finditer(r"\\@writefile\{(toc|lof|lot)\}\{\\contentsline\s*\{(\w+)\}\{", aux_text):
        which, level = m.group(1), m.group(2)
        e = brace_end(aux_text, m.end() - 1)
        entry = aux_text[m.end():e - 1]
        num, title = _numberline(entry)
        title = re.sub(r"\\ignorespaces\s*", "", title).strip()
        if which == "toc":
            num = num.strip()
            if level == "section":
                cur_sec = num
                composite, shown = num, num
            elif level in ("subsection", "subsubsection"):
                composite, shown = cur_sec + num, (cur_sec + "\\," + num if cur_sec else num)
            else:
                continue
            kind = "section"
        else:
            kind = "figure" if which == "lof" else "table"
            composite = shown = num.strip()
        if not composite:
            continue
        key = norm_num(composite)
        idx.items.setdefault((kind, key), Item(kind, key, shown, title))
        idx.titles.setdefault(kind, set()).add(_title_key(title))
    for m in re.finditer(r"\\newlabel\{([^}]*)\}\{\{([^}]*)\}\{[^}]*\}\{", aux_text):
        label, num = m.group(1), m.group(2)
        idx.labels.add(label)
        tail = aux_text[m.end():m.end() + 400]
        anchor = re.search(r"\}\{([a-z*]+)\.[^}]*\}", tail)
        a = anchor.group(1) if anchor else ""
        if a.startswith("equation") or a.startswith("AMS"):
            key = norm_num(num)
            idx.items.setdefault(("equation", key), Item("equation", key, num, label, label))
            idx.titles.setdefault("equation", set()).add(label)
        elif a.startswith("figure"):
            it = idx.items.get(("figure", norm_num(num)))
            if it:
                it.label = label
    return idx


def is_new(item: Item, submitted: ManuscriptIndex) -> bool:
    """投稿版に無いか: 節・図・表 = 題・caption が投稿版に無い / 式 = label が投稿版に無い。"""
    if item.kind == "equation":
        return item.label not in submitted.labels
    if item.label and item.label in submitted.labels:
        return False
    return _title_key(item.title) not in submitted.titles.get(item.kind, set())


# ---------------------------------------------------------------- symbols

FONT_MACROS = {"mathrm", "text", "textrm", "rm", "mathit", "mathsf", "mathbf", "mathtt", "operatorname",
               "textit", "textbf", "emph", "mbox"}
WRAPPERS = {"hat", "tilde", "bar", "vec", "dot", "ddot", "mathcal", "mathbb", "mathfrak", "bm",
            "boldsymbol", "widehat", "widetilde", "overline"}
DELTA_PREFIX = {"Delta", "delta"}
SKIP = {"frac", "dfrac", "tfrac", "sqrt", "exp", "log", "ln", "sin", "cos", "tan", "sinh", "cosh", "tanh",
        "left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "quad", "qquad",
        "simeq", "approx", "sim", "ll", "gg", "lesssim", "gtrsim", "le", "leq", "ge", "geq", "propto",
        "times", "cdot", "cdots", "ldots", "dots", "infty", "to", "rightarrow", "Rightarrow", "leftarrow",
        "pm", "mp", "int", "sum", "prod", "lim", "max", "min", "Re", "Im", "equiv", "neq", "ne", "in",
        "notin", "subset", "cap", "cup", "langle", "rangle", "vert", "mid", "nonumber", "label", "tag",
        "displaystyle", "textstyle", "scriptstyle", "partial", "nabla", "det", "tr", "mathrm", "limits",
        "colon", "ell", "hbar", "prime", "circ", "degree", "%", "begin", "end", "phantom", "hspace",
        "quad", "cr", "lvert", "rvert", "lVert", "rVert", "over", "choose", "not", "cancel", "boxed"}
RELATIONS = r"(?:=|\\simeq|\\equiv|:=|\\approx|\\coloneqq|\\doteq)"


def math_segments(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int, str, bool]]:
    """(中身の始め, 中身の終わり, 中身, display か) の一覧。 `$…$`・`$$…$$`・`\\(…\\)`・`\\[…\\]`・式の環境。"""
    end = len(text) if end is None else end
    out = []
    i = start
    env_re = re.compile(r"\\begin\{(equation|align|gather|multline|eqnarray|displaymath)\*?\}")
    while i < end:
        c = text[i]
        if c == "\\" and i + 1 < end:
            nx = text[i + 1]
            if nx == "[":
                j = text.find("\\]", i + 2, end)
                j = end if j < 0 else j
                out.append((i + 2, j, text[i + 2:j], True))
                i = j + 2
                continue
            if nx == "(":
                j = text.find("\\)", i + 2, end)
                j = end if j < 0 else j
                out.append((i + 2, j, text[i + 2:j], False))
                i = j + 2
                continue
            m = env_re.match(text, i)
            if m:
                name = m.group(0)[len("\\begin{"):-1]
                close = "\\end{" + name + "}"
                j = text.find(close, m.end(), end)
                j = end if j < 0 else j
                out.append((m.end(), j, text[m.end():j], True))
                i = j + len(close)
                continue
            i += 2
            continue
        if c == "$":
            display = text.startswith("$$", i)
            k = 2 if display else 1
            j = i + k
            while j < end:
                if text[j] == "\\":
                    j += 2
                    continue
                if text.startswith("$$" if display else "$", j):
                    break
                j += 1
            out.append((i + k, j, text[i + k:j], display))
            i = j + k
            continue
        i += 1
    return out


def _norm_script(s: str, fonts: set[str] | None = None) -> str:
    names = FONT_MACROS | (fonts or set())
    s = re.sub(r"\\(" + "|".join(sorted(names, key=len, reverse=True)) + r")\b\s*", "", s)
    s = s.replace("\\,", "").replace("\\ ", "").replace("~", "")
    s = re.sub(r"[{}\s]", "", s)
    s = re.sub(r"\\([a-zA-Z]+)", r"\1", s)
    return s


def _read_group(s: str, i: int) -> tuple[str, int]:
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return "", i
    if s[i] == "{":
        e = brace_end(s, i)
        return s[i + 1:e - 1], e
    if s[i] == "\\":
        m = re.match(r"\\[a-zA-Z]+", s[i:])
        if m:
            return m.group(0), i + m.end()
        return s[i:i + 2], i + 2
    return s[i], i + 1


@dataclass
class SymbolUse:
    key: str
    shown: str
    pos: int            # 文書の中の位置
    lhs: bool           # 式の中で関係 (=、 ≃ …) の左辺に 1 つだけ置かれているか
    seg_start: int
    seg_end: int
    seg_text: str
    display: bool


def _is_power(sup: str) -> bool:
    return not re.search(r"[A-Za-z]", re.sub(r"\\(frac|tfrac|dfrac)", "", sup))


def symbols_in(seg: str, font_macros: set[str] | None = None) -> list[tuple[str, str, int, int]]:
    """式の中身から記号を拾う: (key, 見え方, 中身の中の始め, 終わり)。"""
    fonts = FONT_MACROS | (font_macros or set())
    out = []
    i = 0
    while i < len(seg):
        c = seg[i]
        st = i
        base = None
        if c == "\\":
            m = re.match(r"\\([a-zA-Z]+)", seg[i:])
            if not m:
                i += 2
                continue
            name = m.group(1)
            i += m.end()
            if name in fonts:
                _, i = _read_group(seg, i)
                continue
            if name in WRAPPERS:
                g, i = _read_group(seg, i)
                base = name + "{" + _norm_script(g, fonts) + "}"
            elif name in DELTA_PREFIX:
                mm = re.match(r"\s*([A-Za-z])(?![A-Za-z])", seg[i:])
                if mm:
                    base = name + mm.group(1)
                    i += mm.end()
                else:
                    base = name
            elif name in SKIP:
                continue
            else:
                base = name
        elif c.isalpha():
            base = c
            i += 1
        else:
            i += 1
            continue
        sub = sup = ""
        while i < len(seg) and seg[i] in "_^ ":
            if seg[i] == " ":
                if i + 1 < len(seg) and seg[i + 1] in "_^":
                    i += 1
                    continue
                break
            mark = seg[i]
            g, i = _read_group(seg, i + 1)
            if mark == "_":
                sub = g
            else:
                sup = g
        if base == "e" and sup and not sub:
            # e^{…} は指数関数 = 肩の中の記号を拾う
            off = seg.find(sup, st)
            for k2, sh2, a2, b2 in symbols_in(sup, font_macros):
                out.append((k2, sh2, off + a2, off + b2))
            continue
        key = base
        if sub:
            key += "_" + _norm_script(sub, fonts)
        if sup and not _is_power(sup) and sup.strip() not in ("\\prime", "'", "*"):
            key += "^" + _norm_script(sup, fonts)
        out.append((key, seg[st:i].strip(), st, i))
    return out


def _top_level_cuts(seg: str) -> list[int]:
    """括弧の外にある区切り (`,` `;` `&` `\\quad` `\\\\`) の位置。"""
    cuts, depth, i = [], 0, 0
    while i < len(seg):
        c = seg[i]
        if c == "\\":
            if seg.startswith("\\quad", i) or seg.startswith("\\qquad", i) or seg.startswith("\\\\", i):
                if depth == 0:
                    cuts.append(i)
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c in ",;&" and depth == 0:
            cuts.append(i)
        i += 1
    return cuts


def _lhs_keys(seg: str, syms: list[tuple[str, str, int, int]]) -> set[int]:
    """関係 (=、 ≃ …) の左辺が記号 1 つだけで、 右辺に記号がある (= 値を入れるだけでない) ときの、 その記号の位置の集合。"""
    found = set()
    cuts = _top_level_cuts(seg)
    for m in re.finditer(RELATIONS, seg):
        before = [c for c in cuts if c < m.start()]
        left_start = before[-1] + 1 if before else 0
        after = [c for c in cuts if c > m.end()]
        right_end = after[0] if after else len(seg)
        inside = [s for s in syms if s[2] >= left_start and s[3] <= m.start()]
        rest = seg[left_start:m.start()]
        right_syms = [s for s in syms if s[2] >= m.end() and s[3] <= right_end]
        if len(inside) == 1 and right_syms:
            k, shown, a, b = inside[0]
            stripped = (rest[:a - left_start] + rest[b - left_start:]).strip()
            if not re.sub(r"\\[,!;: ]|[{}\s]", "", stripped):
                found.add(a)
    return found


def collect_symbol_uses(text: str, spans: list[tuple[int, int]], font_macros: set[str] | None = None) -> list[SymbolUse]:
    uses = []
    for s, e in spans:
        for a, b, seg, display in math_segments(text, s, e):
            syms = symbols_in(seg, font_macros)
            lhs = _lhs_keys(seg, syms)
            for key, shown, sa, sb in syms:
                uses.append(SymbolUse(key, shown, a + sa, sa in lhs, a, b, seg, display))
    uses.sort(key=lambda u: u.pos)
    return uses


_PREP = r"(?:of|for|in|on|at|by|with|from|to|into|than|as|and|or|is|are|was|be)"
_APPOSITIVE = re.compile(r"\b(?:the|a|an|its|our|this|their)\s+(?:(?!" + _PREP + r"\b)[A-Za-z-]+\s+){0,4}"
                         r"(?:\(|\$|\\\(|\\\[)?\s*$", re.I)
_DEF_AFTER = re.compile(r"^\s*(?:\$|\\\)|\\\])?\s*(?:,\s*)?(?:denotes|stands for|is defined|is the|are the|represents|being)\b", re.I)


def is_definition(text: str, use: SymbolUse) -> bool:
    if use.lhs:
        return True
    seg_first = symbols_in(use.seg_text)
    only = len(seg_first) == 1 or (seg_first and seg_first[0][2] == use.pos - use.seg_start and use.lhs)
    before = text[max(0, use.seg_start - 70):use.seg_start - (2 if use.display else 1)]
    before = re.sub(r"\s+", " ", before)
    if only and _APPOSITIVE.search(before):
        return True
    after = text[use.seg_end:use.seg_end + 40]
    if only and _DEF_AFTER.match(after):
        return True
    return False
