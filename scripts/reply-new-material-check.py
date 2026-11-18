#!/usr/bin/env python3
"""reply-new-material-check.py — LaTeX の返答書を答えごとに読み、 referee が読んだ投稿版に無い節・図・式を使う答えの中に「新しい」 と言う句があるか、 返答書の記号が返答書の中の初出で定義されているかを数える (engine = scripts/lib/reply_letter.py、 --selftest)。

なぜ存在するか: 投稿の後に足した節を答えの根拠に使ったのに、 その答えでは新しい節だと言わなかった (別の答えでは言っていた)。
返答書の中で定義していない記号を使った (原稿の新しい節で定義した記号)。 referee が読んだのは投稿版なので、 どちらも
referee には読めない (実測)。 批判役は返答書と referee の報告しか持たないので、 どの節が投稿版に無いかは見えない
= 機械で投稿版と照らす。 規約 = conventions/rebuttal-letter.md#unrelated-changes の 1 (答えが使う変更は、 それを使う答えの
中で変更として言及する) と #answer-fit-critic-instructions (返答書の中の記号は返答書の中の初出で定義する)。
この一覧は批判役には渡さない (#critic-sandbox-copy の「2 file だけ」 を保つ)。

何を見るか:
  1. 答え (既定 = `\\Q{…}` で引いた referee の文の後、 次の引用か項目まで) ごとに、 原稿への参照 (Sec. / Fig. / Eq. / Table /
     Appendix) を今の原稿の .aux で番号から引き、 投稿版の .aux に無い節・図・表 (題・caption で照らす) と式 (label で照らす)
     を「投稿版に無い」 とする。 その参照を含む文 (列挙の 1 項目も 1 文) に新しいと言う句 (既定 = new / added / after our
     submission / not in the submitted … / updated arXiv version …、 --new-phrase で足す) が無い答えを出す。 同じ答えの中で
     別の文が言っていれば、 その答えは通す (言った文を示す)。 今の原稿に無い番号も出す。
  2. 返答書の中の記号 (式の中の記号。 referee の引用・文献表は除く) の初出を探し、 初出の近く (同じ答えの 160 字以内) に
     定義 (`X = …` の左辺に X だけ / 「the rate $X$」 のような同格 / 「$X$ denotes」) があるかを見る。 慣習の記号は
     --conventional '<正規表現>' (記号の key に当てる。 key の形 = `Gamma_X`・`DeltaT_max,j`) で外す。
     --submitted-tex を渡すと、 その記号が投稿版の tex に在るかも書く。

使い方:
  python3 reply-new-material-check.py --reply reply.tex --current-aux current.aux --submitted-aux submitted.aux
          [--submitted-tex submitted.tex] [--quote-macro Q] [--item-macro A] [--referee-macro R]
          [--font-macro mr ...] [--conventional '^m_' ...] [--new-phrase '<正規表現>' ...] [--json]
  python3 reply-new-material-check.py --selftest
終了値: 0 = 出すものなし / 1 = 新しいと言っていない答えか、 初出で定義していない記号がある / 2 = 使い方の誤り。
見ないもの: 言い換えた主張の新しさ (節・図・式の番号に出ないもの)、 番号を書かずに節の題で引く参照、 原稿の番号が
返答書の想定と違うとき (今の原稿に無い番号として出るだけ)、 定義の文の中身が正しいか。 式は label で照らすので、
投稿の後に label だけを足した式は新しいと出る (--current-tex を渡すと、 その式の行が投稿版の tex に字面で在るかも見て
外し、 relabeled_equations に名を出す。 実測 = 投稿版にある式に後で label を足し、 新しい式と出た)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import reply_letter as rl  # noqa: E402

DEFAULT_NEW = [r"\bnew(?:ly)?\b", r"\badded\b", r"\badd(?:ing)?\b", r"\bintroduced?\b",
               r"after (?:our|the) (?:original )?submission", r"not (?:in|included in|present in) the (?:submitted|original)",
               r"(?:updated|revised|new) arXiv version", r"arXiv\s*v\d", r"\bsince (?:our|the) submission"]
WINDOW = 160


def _eq_body(tex: str, label: str) -> str | None:
    """今の原稿の tex で `\\label{label}` の付いた式の行 (その label の前の行の切れ目まで) を寄せた形で返す。"""
    i = tex.find("\\label{" + label + "}")
    if i < 0:
        return None
    start = max(tex.rfind("\\\\", 0, i), tex.rfind("\\begin{", 0, i), 0)
    return _norm_tex(tex[start:i])


def _norm_tex(s: str) -> str:
    s = re.sub(r"\\label\{[^}]*\}|\\nonumber|\\notag|\\begin\{[a-z*]+\}|\\\\|&|[\s{}]", "", s)
    return s


def analyse(reply: str, current: rl.ManuscriptIndex, submitted: rl.ManuscriptIndex, *, submitted_tex: str | None,
            quote_macro: str, item_macro: str, referee_macro: str, font_macros: set[str],
            conventional: list[str], new_phrases: list[str], current_tex: str | None = None) -> dict:
    text = rl.strip_comments(reply)
    sub_norm = _norm_tex(rl.strip_comments(submitted_tex)) if (submitted_tex and current_tex) else None
    cur_clean = rl.strip_comments(current_tex) if current_tex else None
    relabeled: list[str] = []

    def new_item(it) -> bool:
        if not rl.is_new(it, submitted):
            return False
        if it.kind == "equation" and sub_norm is not None:
            body = _eq_body(cur_clean, it.label)
            if body and len(body) >= 12 and body in sub_norm:
                if it.label not in relabeled:
                    relabeled.append(it.label)
                return False
        return True
    answers = rl.segment_answers(text, quote_macro, item_macro)
    new_re = re.compile("|".join(new_phrases), re.I)
    out = {"answers": [], "unresolved": [], "outside_answers": [], "symbols": []}
    for a in answers:
        sents = rl.sentence_spans(text, a.start, a.end)
        uses = []
        for r in rl.find_refs(text, a.start, a.end):
            it = current.items.get((r.kind, r.number))
            if not it:
                out["unresolved"].append({"answer": a.label, "ref": r.raw, "kind": r.kind, "number": r.number,
                                          "line": rl.line_of(text, r.pos)})
                continue
            if new_item(it):
                uses.append((r, it))
        if not uses:
            continue
        by_item: dict[tuple[str, str], list] = {}
        for r, it in uses:
            by_item.setdefault((it.kind, it.number), []).append((r, it))
        for (kind, num), lst in by_item.items():
            it = lst[0][1]
            said_in = []
            for r, _ in lst:
                for s, e in sents:
                    if s <= r.pos < e and new_re.search(text[s:e]):
                        said_in.append(" ".join(text[s:e].split())[:160])
            out["answers"].append({
                "answer": a.label, "quote": a.quote[:90], "kind": kind, "number": it.shown,
                "title": " ".join(it.title.split())[:80], "refs": [r.raw for r, _ in lst],
                "lines": [rl.line_of(text, r.pos) for r, _ in lst],
                "new_said": bool(said_in), "said_in": said_in[:1]})
    # 答えの外 (前置き・結び・案の節) の参照
    covered = [(a.start, a.end) for a in answers] + [a.quote_span for a in answers]
    b0, b1 = rl.body_span(text)
    for r in rl.find_refs(text, b0, b1):
        if any(s <= r.pos < e for s, e in covered):
            continue
        it = current.items.get((r.kind, r.number))
        out["outside_answers"].append({"ref": r.raw, "line": rl.line_of(text, r.pos),
                                       "resolved": bool(it), "new": bool(it and new_item(it))})
    # 記号
    conv = [re.compile(c) for c in conventional]
    sub_keys: set[str] = set()
    if submitted_tex is not None:
        st = rl.strip_comments(submitted_tex)
        for _, _, seg, _ in rl.math_segments(st):
            for k, *_ in rl.symbols_in(seg, font_macros):
                sub_keys.add(k)
    uses = rl.collect_symbol_uses(text, rl.letter_spans(text, answers, referee_macro, item_macro), font_macros)
    first: dict[str, rl.SymbolUse] = {}
    defs: dict[str, list[rl.SymbolUse]] = {}
    for u in uses:
        first.setdefault(u.key, u)
        if rl.is_definition(text, u):
            defs.setdefault(u.key, []).append(u)
    for key, u in first.items():
        if any(c.search(key) for c in conv):
            continue
        a0 = rl.answer_at(answers, u.pos)
        status, def_line = "定義なし", None
        for d in defs.get(key, []):
            same = rl.answer_at(answers, d.pos) is a0
            if same and 0 <= d.pos - u.pos <= WINDOW:
                status = "初出で定義"
                break
        else:
            later = defs.get(key)
            if later:
                status, def_line = "初出より後で定義", rl.line_of(text, later[0].pos)
        if status == "初出で定義":
            continue
        out["symbols"].append({"key": key, "shown": u.shown, "line": rl.line_of(text, u.pos),
                               "answer": a0.label if a0 else "(答えの外)", "status": status, "defined_line": def_line,
                               "in_submitted": (key in sub_keys) if submitted_tex is not None else None})
    out["relabeled_equations"] = relabeled
    out["counts"] = {
        "answers_using_new": len({x["answer"] for x in out["answers"]}),
        "new_not_said": sum(1 for x in out["answers"] if not x["new_said"]),
        "unresolved": len(out["unresolved"]),
        "symbols_not_defined_at_first_use": len(out["symbols"]),
    }
    return out


def render(res: dict) -> str:
    lines = []
    c = res["counts"]
    lines.append(f"投稿版に無い節・図・式を使う答え {c['answers_using_new']} / そのうち新しいと言っていない組 "
                 f"{c['new_not_said']} / 今の原稿に無い番号 {c['unresolved']} / 初出で定義していない記号 "
                 f"{c['symbols_not_defined_at_first_use']}")
    for x in res["answers"]:
        mark = "✓" if x["new_said"] else "✗"
        where = f" (言った文: {x['said_in'][0]})" if x["said_in"] else ""
        lines.append(f"  {mark} {x['answer']} 行 {','.join(map(str, x['lines']))}: {x['kind']} {x['number']} "
                     f"「{x['title']}」 は投稿版に無い。 参照 = {', '.join(x['refs'])}{where}")
    for x in res["unresolved"]:
        why = ("label の付いた式に無い番号 (label の無い式かもしれない)" if x["kind"] == "equation"
               else "今の原稿の .aux に無い番号")
        lines.append(f"  ? {x['answer']} 行 {x['line']}: {x['ref']} は{why}")
    for x in res["outside_answers"]:
        if x["new"] or not x["resolved"]:
            tag = "投稿版に無い" if x["new"] else ("label の付いた式に無い番号" if "Eq" in x["ref"] else "今の原稿に無い番号")
            lines.append(f"  · 答えの外 行 {x['line']}: {x['ref']} ({tag})")
    for s in res["symbols"]:
        extra = f" (定義 = 行 {s['defined_line']})" if s["defined_line"] else ""
        sub = "" if s["in_submitted"] is None else (" / 投稿版の tex に在る" if s["in_submitted"] else " / 投稿版の tex に無い")
        lines.append(f"  ✗ 記号 {s['shown']} (key {s['key']}): 初出 = 行 {s['line']} ({s['answer']}) / {s['status']}{extra}{sub}")
    return "\n".join(lines)


SELF_SUB_AUX = r"""
\@writefile{toc}{\contentsline {section}{\numberline {I}Introduction}{1}{section*.1}}
\@writefile{toc}{\contentsline {section}{\numberline {II}Method}{2}{section*.2}}
\@writefile{toc}{\contentsline {subsection}{\numberline {A}Old part}{2}{section*.3}}
\@writefile{lof}{\contentsline {figure}{\numberline {1}{\ignorespaces A sketch of the device}}{2}{figure.1}}
\newlabel{eq:old}{{1}{2}{}{equation.1}{}}
"""
SELF_CUR_AUX = r"""
\@writefile{toc}{\contentsline {section}{\numberline {I}Introduction}{1}{section*.1}}
\@writefile{toc}{\contentsline {section}{\numberline {II}Method}{2}{section*.2}}
\@writefile{toc}{\contentsline {subsection}{\numberline {A}Added part}{2}{section*.3}}
\@writefile{toc}{\contentsline {subsection}{\numberline {B}Old part}{3}{section*.4}}
\@writefile{lof}{\contentsline {figure}{\numberline {1}{\ignorespaces A sketch of the device}}{2}{figure.1}}
\@writefile{lof}{\contentsline {figure}{\numberline {2}{\ignorespaces A new plot of the rate}}{3}{figure.2}}
\newlabel{eq:old}{{1}{2}{}{equation.1}{}}
\newlabel{eq:added}{{2}{3}{}{equation.2}{}}
"""
SELF_REPLY = r"""\documentclass{article}
\newcommand\Q[1]{\begin{quote}#1\end{quote}}
\begin{document}
\begin{itemize}
\R1 Does the method work for large inputs? Is there another example?
\A1
\Q{Does the method work for large inputs?}
Yes; this is shown in Sec.~II\,A, where the rate $\kappa_j$ is used.
The old part (Sec.~II\,B) is unchanged.
\Q{Is there another example?}
Yes, see the new Fig.~2 and Eq.~(2), where $\lambda = \kappa_j t$.
\R2 Please say what is new.
\A2
\Q{Please say what is new.}
Our results are:
\begin{enumerate}
\item The rate (Sec.~II\,A, added after our submission).
\item The plot (Fig.~3).
\end{enumerate}
\end{itemize}
\end{document}
"""
SELF_SUB_TEX = r"\begin{document} $\lambda$ is a constant. \end{document}"


def selftest() -> int:
    sub, cur = rl.parse_aux(SELF_SUB_AUX), rl.parse_aux(SELF_CUR_AUX)
    res = analyse(SELF_REPLY, cur, sub, submitted_tex=SELF_SUB_TEX, quote_macro="Q", item_macro="A",
                  referee_macro="R", font_macros=set(), conventional=[], new_phrases=DEFAULT_NEW)
    got = {(x["answer"], x["number"]): x["new_said"] for x in res["answers"]}
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + msg)
        ok = ok and cond
    check(got.get(("A1-1", "II\\,A")) is False, "新しい節を新しいと言わない答えを出す")
    check(("A1-1", "II\\,B") not in got, "投稿版にあった節 (番号が変わっただけ) は出さない")
    check(got.get(("A1-2", "2")) is True, "「the new Fig.~2」 は通す")
    check(got.get(("A1-2", "2")) is True and any(x["kind"] == "equation" and x["answer"] == "A1-2" and x["new_said"]
                                                  for x in res["answers"]), "同じ文の new が式の参照にも効く")
    check(got.get(("A2-1", "II\\,A")) is True, "列挙の項目の中の added を通す")
    check(any(x["ref"] == "Fig.~3" for x in res["unresolved"]), "今の原稿に無い番号を出す")
    sym = {s["key"]: s for s in res["symbols"]}
    check("kappa_j" not in sym, "「the rate $\\kappa_j$」 は初出で定義")
    check("t" in sym and sym["t"]["status"] == "定義なし", "定義の無い記号 t を出す")
    check("lambda" not in sym, "`\\lambda = …` の左辺は初出で定義")
    res2 = analyse(SELF_REPLY, cur, sub, submitted_tex=None, quote_macro="Q", item_macro="A", referee_macro="R",
                   font_macros=set(), conventional=[r"^t$"], new_phrases=DEFAULT_NEW)
    check(not any(s["key"] == "t" for s in res2["symbols"]), "--conventional で外す")
    cur_tex = r"\begin{equation} \lambda = \kappa_j t \label{eq:added} \end{equation}"
    sub_tex = r"\begin{equation} \lambda = \kappa_j t \end{equation}"
    res3 = analyse(SELF_REPLY.replace("the new Fig.~2 and Eq.~(2)", "Eq.~(2)"), cur, sub, submitted_tex=sub_tex,
                   current_tex=cur_tex, quote_macro="Q", item_macro="A", referee_macro="R", font_macros=set(),
                   conventional=[], new_phrases=DEFAULT_NEW)
    check(not any(x["kind"] == "equation" for x in res3["answers"]) and res3["relabeled_equations"] == ["eq:added"],
          "投稿の後に label だけを足した式は新しいと出さない")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--reply", type=Path)
    ap.add_argument("--current-aux", type=Path)
    ap.add_argument("--submitted-aux", type=Path)
    ap.add_argument("--submitted-tex", type=Path)
    ap.add_argument("--current-tex", type=Path, help="今の原稿の tex (式の label が投稿版に無いとき、 式の中身が投稿版にあるかを見る)")
    ap.add_argument("--quote-macro", default="Q")
    ap.add_argument("--item-macro", default="A")
    ap.add_argument("--referee-macro", default="R")
    ap.add_argument("--font-macro", action="append", default=[])
    ap.add_argument("--conventional", action="append", default=[])
    ap.add_argument("--new-phrase", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.reply and a.current_aux and a.submitted_aux):
        ap.print_usage(sys.stderr)
        return 2
    res = analyse(a.reply.read_text(encoding="utf-8"),
                  rl.parse_aux(a.current_aux.read_text(encoding="utf-8", errors="replace")),
                  rl.parse_aux(a.submitted_aux.read_text(encoding="utf-8", errors="replace")),
                  submitted_tex=a.submitted_tex.read_text(encoding="utf-8") if a.submitted_tex else None,
                  current_tex=a.current_tex.read_text(encoding="utf-8") if a.current_tex else None,
                  quote_macro=a.quote_macro, item_macro=a.item_macro, referee_macro=a.referee_macro,
                  font_macros=set(a.font_macro), conventional=a.conventional,
                  new_phrases=DEFAULT_NEW + a.new_phrase)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))
    c = res["counts"]
    return 1 if (c["new_not_said"] or c["symbols_not_defined_at_first_use"]) else 0


if __name__ == "__main__":
    sys.exit(main())
