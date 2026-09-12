#!/usr/bin/env python3
""".tex から LaTeX タグを除いたテキストを生成する (数式は Unicode で線形化、図キャプションは末尾へ)。

投稿先が「タグを除いたテキストファイル」 を PDF と併せて要求するときに使う。
動機となった venue = 日本気象学会「天気」の投稿案内 §5.3「原稿を TEX で書いた場合は，
pdf 形式のタイプセット結果およびタグを除いたテキストファイルを添える」
(機構は conventions/tenki-submission.md#tex-submission-set)。要求の形は venue 共通なので
他誌にも流用できる。

⚠️ MATH_SUBS / DROP_MACROS は原稿ごとに足りない記号が出る **拡張前提の表** —
出力を 1 度通読し、`\` `{` `}` `$` `%` `&` `~` の残留を grep で検査してから提出する。

方針:
  - 図は本文ファイルに入れない（同 §5.3）。キャプションのみ末尾に「図の説明」として列挙
  - 表は本文ファイルに含める（図と異なり文書の一部）。末尾に「表」として配置
  - 数式は Unicode に展開して 1 行に線形化し、通し番号を付す
  - 1 段落 = 1 行（原稿の改行位置を持ち込まない。編集部側で自由に流し込める）

使い方: python3 tex2plain.py <input.tex> [-o output.txt]
"""
import argparse
import re
import sys
import unicodedata

# 適用順に意味があるので list で保持する
MATH_SUBS = [
    (r"\\mathrm\{([^{}]*)\}", r"\1"),
    (r"\\mathit\{([^{}]*)\}", r"\1"),
    (r"\\text\{([^{}]*)\}", r"\1"),
    (r"\\log_\{10\}", "log10"),
    (r"\\log", "log"),
    (r"\\ln", "ln"),
    (r"\\tau", "\u03c4"),
    (r"\\alpha", "\u03b1"),
    (r"\\beta", "\u03b2"),
    (r"\\Delta", "\u0394"),
    (r"\\sigma", "\u03c3"),
    (r"\\simeq", "\u2248"),
    (r"\\approx", "\u2248"),
    (r"\\ge(?![a-zA-Z])", "\u2265"),
    (r"\\le(?![a-zA-Z])", "\u2264"),
    (r"\\times", "\u00d7"),
    (r"\\pm", "\u00b1"),
    (r"\\propto", "\u221d"),
    (r"\\cdot", "\u00b7"),
    (r"\\dots", "\u2026"),
    (r"\\ldots", "\u2026"),
    (r"\\quad", " "),
    (r"\\qquad", "  "),
    (r"\\!", ""),
    (r"\\,", " "),  # 細空き: 0.5\,mm → 0.5 mm
    (r"\\;", " "),
    (r"\\ ", " "),
    (r"\\left", ""),
    (r"\\right", ""),
]

# 下付きは数字・単一英字のみベタ書きに落とす (alpha_1 -> alpha1)
SUB_PATTERNS = [
    (r"_\{([0-9A-Za-z]+)\}", r"\1"),
    (r"_([0-9A-Za-z])", r"\1"),
]

ATOM = r"[0-9A-Za-z\u0370-\u03ff.]+"


def _frac(m):
    num, den = m.group(1), m.group(2)
    if not re.fullmatch(ATOM, den):
        den = "(" + den + ")"
    if not re.fullmatch(ATOM, num):
        num = "(" + num + ")"
    return num + "/" + den


def convert_math(s):
    """数式モードの中身を Unicode 平文へ落とす。"""
    for pat, rep in MATH_SUBS:
        s = re.sub(pat, rep, s)
    for _ in range(2):  # \frac は入れ子でない前提で 2 段まで畳む
        s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", _frac, s)
    s = re.sub(r"\^\{\\ast\}|\^\*|\^\{\*\}", "*", s)
    s = re.sub(r"\^\{([0-9A-Za-z+-]+)\}", r"^\1", s)
    for pat, rep in SUB_PATTERNS:
        s = re.sub(pat, rep, s)
    s = s.replace("{", "").replace("}", "")
    s = s.replace("-", "\u2212")  # 数式内のハイフンは負号
    return re.sub(r"\s+", " ", s).strip()


def inline_math(s):
    return re.sub(r"\$([^$]*)\$", lambda m: convert_math(m.group(1)), s)


def strip_comments(s):
    s = re.sub(r"(?m)^[ \t]*%.*$", "", s)
    return re.sub(r"(?<!\\)%.*", "", s)


# 出力に現れてはいけない、引数ごと捨てるマクロ（名前, 必須引数の数）
DROP_MACROS = [
    ("documentclass", 1), ("usepackage", 1), ("thispagestyle", 1),
    ("pagestyle", 1), ("includegraphics", 1), ("setlength", 2),
    ("addtolength", 2), ("hspace", 1), ("vspace", 1), ("date", 1),
]


def drop_macros(s):
    for name, nargs in DROP_MACROS:
        pat = re.compile(r"\\" + name + r"\*?\s*(\[[^\]]*\])?\s*\{")
        while True:
            m = pat.search(s)
            if not m:
                break
            end = m.end() - 1
            for _ in range(nargs):
                try:
                    _, end = brace_arg(s, end)
                except (ValueError, IndexError):
                    break
                while end < len(s) and s[end] in " \t":
                    end += 1
            s = s[:m.start()] + s[end:]
    return s


def clean_text(s, collapse_newlines=False):
    """本文用: 残った LaTeX マークアップを落とす。"""
    s = drop_macros(s)
    if collapse_newlines:
        s = re.sub(r"\s*\n\s*", " ", s)
    s = inline_math(s)
    s = re.sub(r"\\textbf\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\emph\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\textit\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\label\{[^{}]*\}", "", s)
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = s.replace("\\%", "%").replace("\\&", "&")
    s = re.sub(r"\\\\(\[[^\]]*\])?", "\n", s)
    s = re.sub(r"\\[a-zA-Z@]+\*?", "", s)  # 取りこぼしのコマンド
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def brace_arg(s, start):
    """s[start] が '{' のとき、対応する閉じ括弧までの中身と終端位置を返す。"""
    depth = 0
    i = start
    while i < len(s):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start + 1:i], i + 1
        i += 1
    raise ValueError("unbalanced brace at %d" % start)


def macro_arg(s, name):
    m = re.search(r"\\" + name + r"\s*\{", s)
    if not m:
        return None
    return brace_arg(s, m.end() - 1)[0]


def pop_environments(s, env):
    """begin/end env を抜き出し、本文からは取り除く。"""
    kept, found = [], []
    pat = re.compile(r"\\begin\{" + env + r"\}(\[[^\]]*\])?")
    closer = "\\end{" + env + "}"
    pos = 0
    while True:
        m = pat.search(s, pos)
        if not m:
            kept.append(s[pos:])
            break
        end = s.find(closer, m.end())
        if end == -1:
            kept.append(s[pos:])
            break
        found.append(s[m.end():end])
        kept.append(s[pos:m.start()])
        pos = end + len(closer)
    return "".join(kept), found


def render_table(body, number):
    cap = macro_arg(body, "caption") or ""
    lines = ["\u7b2c%d\u8868\u3000%s" % (number, clean_text(cap)), ""]
    inner = re.search(r"\\begin\{tabular\}\{[^{}]*\}(.*?)\\end\{tabular\}", body, re.S)
    if inner:
        for raw in inner.group(1).split("\\\\"):
            raw = raw.replace("\\hline", "").strip()
            if not raw:
                continue
            cells = [clean_text(c).strip() or "\u2014" for c in raw.split("&")]
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def render_equation(body, number):
    body = re.sub(r"\\label\{[^{}]*\}", "", body)
    cases = re.search(r"\\begin\{cases\}(.*?)\\end\{cases\}", body, re.S)
    tag = "\uff08%d\uff09" % number
    if cases:
        head = convert_math(body[:cases.start()]).rstrip("= ").strip()
        rows = []
        for raw in cases.group(1).split("\\\\"):
            if not raw.strip():
                continue
            parts = raw.split("&")
            expr = convert_math(parts[0])
            cond = convert_math(parts[1]) if len(parts) > 1 else ""
            rows.append(("%s = %s\u3000%s" % (head, expr, cond)).strip())
        return tag + "\u3001".join(rows)
    return tag + convert_math(body).rstrip(",").strip()


def convert(src):
    src = strip_comments(src)
    title = macro_arg(src, "title") or ""
    author = macro_arg(src, "author") or ""

    body = src.split("\\begin{document}", 1)[1].split("\\end{document}", 1)[0]
    body, centers = pop_environments(body, "center")
    body, tables = pop_environments(body, "table")
    body, figures = pop_environments(body, "figure")

    refs = []
    if "\\subsection*{\u53c2\u8003\u6587\u732e}" in body:
        body, refblock = body.split("\\subsection*{\u53c2\u8003\u6587\u732e}", 1)
        _, descs = pop_environments(refblock, "description")
        for d in descs:
            # \itemsep 等に誤って割り込まないよう、後続が英字でない \item のみで分割
            for item in re.split(r"\\item(?![a-zA-Z])", d)[1:]:
                t = clean_text(item)
                if t:
                    refs.append(t)

    body, equations = pop_environments(body, "equation")

    out = [clean_text(title, collapse_newlines=True).replace("\n", ""), ""]
    out += [clean_text(author, collapse_newlines=True), ""]
    for c in centers:
        out += [clean_text(c, collapse_newlines=True), ""]

    sec_no = sub_no = 0
    chunks = re.split(r"(\\section\*?\{[^{}]*\}|\\subsection\*?\{[^{}]*\})", body)
    for chunk in chunks:
        m = re.fullmatch(r"\\(section|subsection)(\*?)\{([^{}]*)\}", chunk.strip())
        if m:
            kind, star, name = m.groups()
            name = clean_text(name)
            if star:
                out += [name, ""]
            elif kind == "section":
                sec_no += 1
                sub_no = 0
                out += ["%d. %s" % (sec_no, name), ""]
            else:
                sub_no += 1
                out += ["%d.%d %s" % (sec_no, sub_no, name), ""]
            continue
        for para in re.split(r"\n\s*\n", chunk):
            cleaned = clean_text(para)
            if cleaned:
                out += [cleaned, ""]

    if equations:
        out += ["\u672c\u6587\u4e2d\u306e\u5f0f", ""]
        for i, e in enumerate(equations, 1):
            out += [render_equation(e, i), ""]

    if refs:
        out += ["\u53c2\u8003\u6587\u732e", ""]
        out += refs + [""]

    if tables:
        out += ["\u8868", ""]
        for i, t in enumerate(tables, 1):
            out += [render_table(t, i), ""]

    if figures:
        out += ["\u56f3\u306e\u8aac\u660e", ""]
        for i, f in enumerate(figures, 1):
            cap = macro_arg(f, "caption") or ""
            out += ["\u7b2c%d\u56f3\u3000%s" % (i, clean_text(cap)), ""]

    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return unicodedata.normalize("NFC", text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()
    text = convert(open(a.input, encoding="utf-8").read())
    if a.output:
        open(a.output, "w", encoding="utf-8", newline="\n").write(text)
        sys.stderr.write("wrote %s (%d chars)\n" % (a.output, len(text)))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
