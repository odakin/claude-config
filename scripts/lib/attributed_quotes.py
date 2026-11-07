#!/usr/bin/env python3
"""attributed_quotes.py — 外に出す文の中で他人 (referee・共著者・文献) に帰して引いた文が、 原文の部分文字列かを数える engine (CLI = scripts/check-attributed-quotes.py、 送信の道具 discord-post.py と送信の CLI が import する)。

なぜ存在するか:
  共著者・編集者・referee に出す文で他人の文を鉤括弧・引用符で括ると、 読み手はそれを原文の写しとして読む。
  下請け (批判役・worker) の要約を簡潔・平易に書き直す段で言い換えが鉤括弧の中に入り、 原文の主節を落とした
  「X は … と言っているだけ」 が引用の形で外に出る (実測)。 書き手は原文の意味で読み返すので目では見落とす。
  鉤括弧の中身が原文の部分文字列かは機械で数えられる。
  規約 = conventions/rebuttal-letter.md#pre-send-verification-sheet (照合票の B と、 この検査の置き場所)。
  似た道具 = scripts/check-note-quotes.py (note が原稿の tex を行番号つきで引く形を、 寄せずに厳密に照らす)。
  こちらは送る文と他人の文 (メールの txt・報告) を、 空白・改行・引用符を寄せて照らし、 帰属の有無で分ける。

何を引用と数えるか:
  「…」 『…』 “…” "…" ``…'' と、 行頭が "> " の引用の塊 (Discord・markdown。 ">>> " は以降すべて)。
  段落 (空行) をまたがない。 ``` で囲んだ code block の中は見ない。
  引用の中の省略 (... / … / \\ldots / [...]) は片の区切り = 各片が原文に順に現れるかで照らす。
  寄せた後の文字数が min_chars 未満の片は照らさない (照らしていない印として数えて返す)。

比べ方 (送る文と原文の両方を同じに寄せる):
  NFKC、 引用符の文字を消す、 ~ を空白に、 空白・改行を 1 つの空白に、 CJK の文字どうしの間の空白は消す。
  原文の行末のハイフンでの分割 (「imagi-」 + 改行 + 「nary」) は、 つないだ形でも照らす。
  大文字小文字だけの違いは一致に数え、 印 (ok-case) を付ける。

帰属:
  引用を含む文 (。！？ / 「. 」 / 空行で区切る。 引用の前が空か「:」 で終わるなら、 その前の文も) に、
  帰属の語 (ATTRIB_EN / ATTRIB_JA と、 呼び手が渡す語 = 人名など) があれば「他人に帰した引用」。
  "> " の塊は形で帰属あり。 all_quotes=True なら全部の引用を帰属ありとして扱う。
  帰属ありで原文に無い = failure。 帰属の語の無い引用で原文に無いものは、 failure にせず別の印 (unattributed) で返す
  (照らしたが帰属は判定していない = 照合票の「照らしていないこと」 に書く分)。

限界 (= この検査が見ないこと。 照合票の「照らしていないこと」 に書く):
  - 括らずに書いた言い換え (「referee は X とだけ言う」 を鉤括弧なしで書いた文) は見ない。
  - 帰属は語の有無だけ。 自分の文を引いた引用に帰属の語が同じ文にあると failure に出る (読んで外す)。
  - 原文の訳 (英文の原文を日本語で括ったもの) は原文に無いと出る = 規約どおり (訳は括らず、 原文の語で引く)。
  - 部分文字列なら一致とする = 文脈から切り離した引用 (主節を落として従属節だけ引く) は通る。 意味の照合は人が読む。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

QUOTE_CHARS = set("「」『』“”‘’\"'`«»„‟〝〞＂＇")
PARA = r"(?:(?!\n[ \t]*\n).)"  # 空行をまたがない 1 文字
PAIRS = [
    ("「", "」"), ("『", "』"), ("“", "”"), ("``", "''"),
]
SPAN_RES = [re.compile(re.escape(o) + "(" + PARA + "+?)" + re.escape(c), re.S) for o, c in PAIRS]
ASCII_DQ = re.compile('"(' + r'(?:(?!\n[ \t]*\n)[^"])' + '+?)"', re.S)
FENCE = re.compile(r"```.*?```", re.S)
ELLIPSIS = re.compile(r"\\ldots(?:\{\})?|\[\s*(?:\.\.\.|…)\s*\]|\.\.\.|…")
CJK = "\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uff00-\uffef"
BOUNDARY = re.compile(r"[。！？!?]|\.(?=\s)|\n[ \t]*\n")

ATTRIB_EN = (
    "referee", "referees", "reviewer", "reviewers", "report", "editor", "editors",
    "coauthor", "coauthors", "co-author", "co-authors", "author", "authors",
    "says", "said", "states", "stated", "writes", "wrote", "argues", "argued",
    "claims", "claimed", "notes", "noted", "asks", "asked", "suggests", "suggested",
    "comments", "commented", "remarks", "remarked", "according to",
)
ATTRIB_JA = (
    "レフェリー", "査読者", "査読", "審査員", "審査者", "編集者", "編集部", "共著者", "著者", "筆頭",
    "原文", "報告書", "レポート", "コメント", "指摘", "さん", "氏", "先生", "くん",
    "と言", "って言", "と書", "と述", "と主張", "と問", "によれば", "によると", "曰く", "いわく", "の文",
)


@dataclass
class Quote:
    line: int                 # 送る文の中の行 (1 始まり)
    text: str                 # 引用の中身 (送る文の字面)
    form: str                 # "bracket" | "block"
    attrib: str | None        # 帰属の語 (None = 帰属の語なし)
    status: str = ""          # "ok" | "ok-case" | "missing" | "order" | "short"
    missing: list[str] = field(default_factory=list)  # 原文に無かった片 (寄せた形)

    @property
    def failure(self) -> bool:
        return bool(self.attrib) and self.status in ("missing", "order")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = "".join(ch for ch in s if ch not in QUOTE_CHARS).replace("~", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(rf"(?<=[{CJK}]) (?=[{CJK}])", "", s)


def _corpora(sources: list[str]) -> list[str]:
    out = []
    for raw in sources:
        out.append(norm(raw))
        joined = re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", raw)
        if joined != raw:
            out.append(norm(joined))
    return out


def _fragments(span: str, min_chars: int) -> tuple[list[str], int]:
    """(照らす片, 短くて外した片の数)。"""
    frags, short = [], 0
    for part in ELLIPSIS.split(span):
        p = norm(part).strip(" .,;:")
        if not p:
            continue
        if len(p) < min_chars:
            short += 1
        else:
            frags.append(p)
    return frags, short


def _find_ordered(frags: list[str], corpus: str) -> bool:
    pos = 0
    for f in frags:
        i = corpus.find(f, pos)
        if i < 0:
            return False
        pos = i + len(f)
    return True


def _attrib_word(context: str, extra: tuple[str, ...]) -> str | None:
    low = context.lower()
    for w in ATTRIB_EN:
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
            return w
    for w in ATTRIB_JA + tuple(extra):
        if w and w.lower() in low:
            return w
    return None


def _sentence_context(text: str, start: int, end: int) -> str:
    before = [m.end() for m in BOUNDARY.finditer(text, 0, start)]
    b = before[-1] if before else 0
    head = text[b:start]
    if (not head.strip() or head.rstrip().endswith((":", "："))) and len(before) >= 2:
        b = before[-2]
        head = text[b:start]
    m = BOUNDARY.search(text, end)
    tail = text[end:m.start() if m else len(text)]
    return head + " " + tail


def _blank(m: re.Match) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in m.group(0))


def find_quotes(text: str, extra_attrib: tuple[str, ...] = (), all_quotes: bool = False) -> list[Quote]:
    """送る文の引用を順に返す (status は未設定)。"""
    work = FENCE.sub(_blank, text)
    spans: list[tuple[int, int, str]] = []  # (start, end, inner)
    for rx in SPAN_RES + [ASCII_DQ]:
        for m in rx.finditer(work):
            spans.append((m.start(), m.end(), m.group(1)))
    quotes = []
    for s, e, inner in sorted(spans):
        ctx = _sentence_context(work, s, e)
        attrib = "(all)" if all_quotes else _attrib_word(ctx, extra_attrib)
        quotes.append(Quote(line=work.count("\n", 0, s) + 1, text=inner, form="bracket", attrib=attrib))
    # "> " の塊 (">>> " は以降すべて)
    lines = work.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if re.match(r"[ \t]*>>>[ \t]?", ln):
            body = [re.sub(r"^[ \t]*>>>[ \t]?", "", ln)] + lines[i + 1:]
            quotes.append(Quote(line=i + 1, text="\n".join(body), form="block", attrib="(> 引用)"))
            break
        if re.match(r"[ \t]*>[ \t]?", ln):
            j = i
            body = []
            while j < len(lines) and re.match(r"[ \t]*>[ \t]?", lines[j]) and not re.match(r"[ \t]*>>>", lines[j]):
                body.append(re.sub(r"^[ \t]*>[ \t]?", "", lines[j]))
                j += 1
            quotes.append(Quote(line=i + 1, text="\n".join(body), form="block", attrib="(> 引用)"))
            i = j
            continue
        i += 1
    return sorted(quotes, key=lambda q: q.line)


def check_text(text: str, sources: list[str], extra_attrib: tuple[str, ...] = (),
               all_quotes: bool = False, min_chars: int = 5) -> list[Quote]:
    """送る文の引用それぞれに status を付けて返す。 sources = 原文の中身 (file の文字列) の list。"""
    corpora = _corpora(sources)
    folded = [c.casefold() for c in corpora]
    out = []
    for q in find_quotes(text, extra_attrib, all_quotes):
        frags, _short = _fragments(q.text, min_chars)
        if not frags:
            q.status = "short"
        elif any(_find_ordered(frags, c) for c in corpora):
            q.status = "ok"
        elif any(_find_ordered([f.casefold() for f in frags], c) for c in folded):
            q.status = "ok-case"
        else:
            q.missing = [f for f in frags if not any(f.casefold() in c for c in folded)]
            q.status = "missing" if q.missing else "order"
        out.append(q)
    return out


def attributed(text: str, extra_attrib: tuple[str, ...] = (), min_chars: int = 5) -> list[Quote]:
    """原文を渡されていないときの数え: 帰属の語のある、 照らせる長さの引用。"""
    return [q for q in find_quotes(text, extra_attrib)
            if q.attrib and _fragments(q.text, min_chars)[0]]


def failures(quotes: list[Quote]) -> list[Quote]:
    return [q for q in quotes if q.failure]


def _clip(s: str, n: int = 80) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def format_report(quotes: list[Quote], label: str = "送る文") -> list[str]:
    lines = []
    for q in quotes:
        where = f"{label}:{q.line}"
        if q.failure:
            why = "片の順が原文と違う" if q.status == "order" else "原文に無い"
            lines.append(f"✗ {where} 「{_clip(q.text)}」 = {why} (帰属: {q.attrib})")
            for f in q.missing:
                lines.append(f"    無い片: {_clip(f)!r}")
        elif q.status in ("missing", "order"):
            lines.append(f"△ {where} 「{_clip(q.text)}」 = 原文に無い。 帰属の語なし = 他人の文として照らしていない")
        elif q.status == "ok-case":
            lines.append(f"✓ {where} 「{_clip(q.text, 50)}」 = 原文の部分文字列 (大文字小文字だけ違う)")
        elif q.status == "ok":
            lines.append(f"✓ {where} 「{_clip(q.text, 50)}」 = 原文の部分文字列")
    n = len(quotes)
    nf = len(failures(quotes))
    nu = sum(1 for q in quotes if not q.failure and q.status in ("missing", "order"))
    ns = sum(1 for q in quotes if q.status == "short")
    lines.append(f"引用 {n} 件: 他人に帰して原文に無い {nf} / 帰属の語なしで原文に無い {nu} / "
                 f"短くて照らしていない {ns} / 一致 {n - nf - nu - ns}")
    return lines


def selftest() -> int:
    """合成の文で、 一致・訳・言い換え・省略・順・改行・ハイフン・塊の引用・code block を確かめる。"""
    src = ("The bias appears when the sample is restricted to the northern stations, as\n"
           "\"noted\" in Section 2. A second line wraps here and con-\n"
           "tinues to the end.\n"
           "観測点を北に\n限ると偏りが出る。\n")
    ok = True

    def expect(label: str, cond: bool) -> None:
        nonlocal ok
        print(("  PASS " if cond else "  FAIL ") + label)
        ok = ok and cond

    def one(draft: str, **kw) -> Quote:
        qs = check_text(draft, [src], **kw)
        assert len(qs) == 1, (draft, qs)
        return qs[0]

    q = one("referee は「the sample is restricted to the northern stations」と書いています。")
    expect("verbatim quote attributed to the referee is ok", q.status == "ok" and not q.failure)
    q = one("referee は「北の観測点だけだと偏りが出る」と言っているだけです。")
    expect("a Japanese paraphrase in brackets attributed to the referee fails",
           q.failure and q.status == "missing")
    q = one('The referee writes "the bias appears when ... the northern stations".')
    expect("ellipsis fragments + sentence-initial case difference pass", q.status == "ok-case" and not q.failure)
    q = one('The referee says "the bias is small".')
    expect("an invented English quote fails", q.failure)
    q = one('The referee writes "northern stations ... The bias appears".')
    expect("fragments in the wrong order fail", q.failure and q.status == "order")
    q = one("referee の「A second line wraps here and continues」 の文。")
    expect("a line-end hyphen split in the source still matches", q.status == "ok")
    q = one('referee: "the sample is\nrestricted to"')
    expect("a quote broken across lines in the draft matches", q.status == "ok")
    q = one("referee の「観測点を北に限ると偏りが出る」。")
    expect("CJK text broken by a newline in the source matches", q.status == "ok")
    q = one("referee の「bias」。")
    expect("a fragment shorter than min_chars is not checked", q.status == "short" and not q.failure)
    q = one("この版では「段落を一つ足した」 だけだ。")
    expect("a quote without an attribution word is not a failure but is marked",
           q.attrib is None and q.status == "missing" and not q.failure)
    q = one("この版では「段落を一つ足した」 だけだ。", all_quotes=True)
    expect("all_quotes=True treats every quote as attributed", q.failure)
    q = one("Kanda: 「the bias is small everywhere」", extra_attrib=("Kanda",))
    expect("a caller-supplied attribution word (a name) counts", q.failure and q.attrib == "Kanda")
    expect("without it the same quote is unattributed",
           one("Kanda: 「the bias is small everywhere」").attrib is None)
    qs = check_text("> The bias appears when the sample\n> is restricted\n\n> The bias vanishes entirely\n", [src])
    expect("a > block quote is attributed by form; a true one passes, an invented one fails",
           len(qs) == 2 and qs[0].status == "ok" and qs[1].failure)
    qs = check_text("```\nreferee says \"the bias is small\"\n```\nreferee の「the northern stations」。", [src])
    expect("a fenced code block is skipped", len(qs) == 1 and qs[0].status == "ok")
    q = one("The referee writes ``restricted to the northern''.")
    expect("TeX ``…'' quotes are checked", q.status == "ok")
    q = one("The referee writes “restricted to the northern stations”.")
    expect("curly quotes are checked", q.status == "ok")
    q = one("referee は次のように書いています:\n「the sample is restricted」")
    expect("an attribution in the sentence before a ':' counts", q.attrib == "referee" and q.status == "ok")
    q = one('referee writes "as noted in Section 2"')
    expect("quote characters inside the source are ignored on both sides", q.status == "ok")
    expect("attributed() counts attributed quotes without a source",
           len(attributed("referee は「北の観測点だけだと偏る」と言う。 私は「段落を足した」 だけ。")) == 1)
    rep = format_report(check_text("referee は「北の観測点だけだと偏る」と言う。", [src]))
    expect("report names the failure and the summary line", rep[0].startswith("✗") and "原文に無い 1" in rep[-1])
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
