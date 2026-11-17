#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ja_question_direction.py — 日本語の問いと答えの語の向きの食い違い (問いの中で打ち消した動詞を、 答えが肯定形で持つ) を見つける部品

なぜ在るか (conventions/concise-output.md#question-button-same-words): 本人は問いとボタンを突き合わせて何を聞かれているかを
決める。 問いを打ち消しで書き (「例外を表題に当てないようにしますか」)、 ボタンにその動詞の肯定形を置くと (「当てる」)、
押した答えがどちらの向きか決まらない (実測)。 表面の形で見分けられたのは、 この 1 形だけ (問いとボタンの語のほかの食い違い =
本文と箱の別の問い・層の違い・説明の語は、 通じた問いと見分けられなかった = 実測)。 語の形が日本語に依るので、 言語に依らない
engine (decision-question-jargon.py・問いの台帳の判定の道具 owner-ask-validate.py) から、 この部品を呼ぶ。

述語: 答えの語 (ボタンの label・推す答えの先頭の語) の末尾の動詞について、 その動詞の打ち消しの形 (〜ない・〜なく・〜ずに・
  〜ません) が問いの文に出ていて、 どの答えの語もその打ち消しの形を持っていないとき、 その答えを返す。
  - 動詞の形 = 辞書形 (当てる・送る・残す・適用する) と て形 (当てて・送って)。 一段の語幹 (当て-ない)、 五段の未然形
    (送ら-ない) と連用形 (送り-ません)、 する動詞 (適用し-ない・適用せ-ずに) の打ち消しを作る。 「る」 で終わる動詞は一段と
    五段の両方を作る (帰る / 止める は形だけでは分けられない)。 動詞の頭は漢字か片仮名 (仮名だけの答え = 「そうする」「はい」
    は見ない)。
  - 答えが打ち消し・据え置き (〜ない・〜ず・なし・無し・残す・まま で終わる) なら、 その答えは見ない。
  - 打ち消しは問いの終わりの述語にあるものだけ = 打ち消しの形の後ろが問いの終わりまで仮名 (と 形・方・様) だけで、 読点を
    挟まない (「当てないようにしますか」「当てない形でよいですか」 は当てる)。 途中の節の打ち消し (「受領を待たずに今から
    書き始めますか」 × [書き始める / 受領を待つ]、 「依頼は送らずに、 別々に買いますか」) は、 ボタンがその逆を別の選択肢に
    置いた通じる形なので当てない (実測: 範囲を問いの全体にすると、 鳴った箱の大半がこの形の誤検出だった)。
  - 除く: どれかの答えが、 同じ動詞の打ち消しを持つ (問い「引かないようにしますか」 × [引かない / 引く]、 「足さずに」 ×
    [足さない / それでも足す]) = ボタンが問いの述語の向きを繰り返していて、 向きは読める (実測: その形は通じた)。 素の「ず」 は
    打ち消しに数えない (「一回ずつ」「まず」 に当たる = 実測の誤検出)。 括弧の中 (問いの補足) は見ない。 「〜しませんか」 (勧め)
    で終わる問いも見ない。

API (純関数、 例外を出さない):
  verb_forms(answer)          -> (動詞の語, [打ち消しの形…]) か None
  flipped(question, answers)  -> [{"answer", "verb", "negated"}] (向きが逆の答え。 空 = 食い違いなし)
  leading_answer(text)        -> 推す答えの文の先頭の語 (括弧・句読点・空白の前まで)
  notice(question, hits)      -> 書き直しを求める 1 段の文 (本人の画面でなく agent に返す文)
CLI: ja_question_direction.py --selftest / ja_question_direction.py '<問い>' '<答え>' ['<答え>' …] (JSON 1 行)
"""
from __future__ import annotations

import json
import re
import sys

RULE = "claude-config/conventions/concise-output.md#question-button-same-words"

# 仮名だけの答え・中身の無い答えは動詞として見ない
GENERIC = re.compile(r"^(?:はい|いいえ|うん|OK|ok|そうする|そうして|そうしない|今のまま|このまま|そのまま|まだ|待つ|やめる|しない|する"
                     r"|おすすめ.*|推す.*|両方|どちらも|後で|あとで|保留|任せる|進める|進めて|いい|よい|良い)$")
# 打ち消し・据え置きの答え (その答えは、 問いの打ち消しと同じ向き)
NEG_ANSWER = re.compile(r"(?:ない|ず|なし|無し|残す|まま)$")
_PAREN = re.compile(r"[（(][^）)]*[）)]")
_TAIL = re.compile(r"([一-龥々ァ-ヶー]+)([ぁ-ん]*)$")
_INVITE = re.compile(r"ませんか[？?。]?\s*$")
_NEG_TAILS = ("ない", "なく", "ずに")
_PRED_TAIL = re.compile(r"[ぁ-んー形方様]{0,14}")   # 打ち消しの後ろ、 問いの終わりまで (述語の打ち消しの形)
_Q_END = re.compile(r"[？?。!！\s]+$")
# 五段の辞書形の末尾 → (未然形の段, 連用形の段)
_GODAN = {"う": ("わ", "い"), "く": ("か", "き"), "ぐ": ("が", "ぎ"), "す": ("さ", "し"), "つ": ("た", "ち"),
          "ぬ": ("な", "に"), "ぶ": ("ば", "び"), "む": ("ま", "み"), "る": ("ら", "り")}
# て形 → 辞書形の末尾の候補
_TE = {"って": ("う", "つ", "る"), "んで": ("ぬ", "ぶ", "む"), "いて": ("く",), "いで": ("ぐ",), "して": ("す",)}


def _clean(text: str) -> str:
    return _PAREN.sub("", text or "").strip(" 　。、.,")


def _negations(head: str, kana: str) -> list[str]:
    """動詞の頭 (漢字・片仮名) と後ろの仮名から、 打ち消しの形の一覧。"""
    out: list[str] = []
    if kana == "する":                      # 適用する → 適用しない / 適用せずに / 適用しません
        return [head + "し" + t for t in ("ない", "なく")] + [head + "せずに", head + "しません"]
    if kana == "して":                      # 適用して (する動詞の て形) と 残して (五段 す) は同じ形
        out += [head + "し" + t for t in ("ない", "なく")] + [head + "せずに", head + "しません"]
    endings: list[tuple[str, str]] = []     # (語幹の仮名, 辞書形の末尾)
    if kana and kana[-1] in _GODAN:
        endings.append((kana[:-1], kana[-1]))
    for te, ends in _TE.items():
        if kana.endswith(te):
            endings += [(kana[:-len(te)], e) for e in ends]
    if kana.endswith("て") and not any(kana.endswith(te) for te in _TE):
        out += [head + kana[:-1] + t for t in _NEG_TAILS] + [head + kana[:-1] + "ません"]   # 一段の て形 (当てて → 当て)
    for stem_kana, last in endings:
        base = head + stem_kana
        if last == "る" and stem_kana:      # 一段 (当てる → 当て)。 語幹に仮名が無い「送る」 は五段だけ
            out += [base + t for t in _NEG_TAILS] + [base + "ません"]
        a, i = _GODAN[last]
        out += [base + a + t for t in _NEG_TAILS] + [base + i + "ません"]
    seen: list[str] = []
    for f in out:
        if f not in seen:
            seen.append(f)
    return seen


def verb_forms(answer: str):
    """答えの語の末尾の動詞 (語, 打ち消しの形の一覧)。 動詞が無い・仮名だけ・打ち消しの答えは None。"""
    a = _clean(answer)
    if not a or GENERIC.match(a) or NEG_ANSWER.search(a):
        return None
    m = _TAIL.search(a)
    if not m or not m.group(2):
        return None
    head, kana = m.group(1), m.group(2)
    forms = _negations(head, kana)
    return (head + kana, forms) if forms else None


def _predicate_negation(q: str, forms):
    """打ち消しの形のうち、 問いの終わりの述語にあるもの (後ろが問いの終わりまで仮名と 形・方・様 だけ)。"""
    body = _Q_END.sub("", q)
    for f in forms:
        i = body.rfind(f)
        if i >= 0 and _PRED_TAIL.fullmatch(body[i + len(f):]):
            return f
    return None


def flipped(question: str, answers) -> list[dict]:
    """問いの終わりの述語で打ち消した動詞を肯定形で持つ答え (向きが逆の答え) の一覧。 答えのどれかが同じ動詞の打ち消しを
    持てば空。"""
    q = _clean(question)
    if not q or _INVITE.search(q):
        return []
    raws = [a for a in (answers or []) if isinstance(a, str) and a.strip()]
    labels = [_clean(a) for a in raws]
    hits = []
    for raw, lab in zip(raws, labels):
        vf = verb_forms(lab)
        if not vf:
            continue
        verb, forms = vf
        neg = _predicate_negation(q, forms)
        if not neg:
            continue
        if any(f in other for other in labels for f in forms):   # ボタンが同じ動詞の打ち消しを持つ = 向きは読める
            continue
        hits.append({"answer": raw.strip(), "verb": verb, "negated": neg})
    return hits


def leading_answer(text: str) -> str:
    """推す答えの文の先頭の語 (「当てる (題は…)」 → 「当てる」)。"""
    t = (text or "").strip()
    m = re.match(r"[^\s　(（。、,，:：=＝/／]+", t)
    return m.group(0) if m else ""


def notice(question: str, hits) -> str:
    h = hits[0]
    return (f"答え「{h['answer']}」 は、 問いの中で打ち消した「{h['negated']}」 の逆向き (問い「{_clean(question)[:60]}」) ="
            " 本人が押した答えがどちらの向きか決まらない。 問いを、 決めた後に本人の側で何が変わるかの肯定で書き直し"
            " (例: 「例外を〜に当てないようにしますか」 → 「〜にも本人の OK が要るようにしますか」)、 答えの語は問いの述語から取る"
            f" (「そうする / 今のまま」)。 打ち消しで聞くのが正しいなら、 答えの語にもその打ち消しをそのまま使う (「{h['negated']} / {h['verb']}」)。"
            f" 正本 = {RULE}")


def selftest() -> int:
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and bool(cond)

    # 止まる形 (実測と同じ形の合成 = 問いが例外を打ち消し、 ボタンが作業の動詞の肯定形)
    q0 = "校正の例外を見出しにだけ当てないようにしますか？"
    check(flipped(q0, ["当てる", "例外は残す"]) and flipped(q0, ["当てる", "例外は残す"])[0]["negated"] == "当てない",
          "実測の形: 問い「当てない」 × ボタン「当てる」 は止まる")
    check(flipped("この変更を適用しないようにしますか", ["適用する", "今のまま"]), "する動詞: 「適用しない」 × 「適用する」")
    check(flipped("下書きは送らないでおきますか", ["送る", "待つ"]), "五段の未然形: 「送らない」 × 「送る」")
    check(flipped("見出しには当てませんよね？", ["当てる", "やめる"]), "一段の連用形: 「当てません」 × 「当てる」")
    check(flipped("表題には当てない形でよいですか", ["当てる", "今のまま"]), "「〜ない形でよいですか」 も述語の打ち消し")
    check(flipped("表題に当てないようにしますか", ["当てて", "今のまま"]), "て形の答え: 「当てて」")
    check(flipped("今回は送らないことにしますか", ["送って", "待って"]), "五段の て形の答え: 「送って」")
    # 止まらない形
    check(not flipped("表題に当てないようにしますか", ["当てないようにする", "当てる"]),
          "ボタンが問いの打ち消しを繰り返す (一段) は止めない")
    check(not flipped("この検査で引かないようにしますか", ["引かない", "引く"]), "ボタンが問いの打ち消しを繰り返す (五段) は止めない")
    check(not flipped("この語は足さないようにしますか", ["足さない", "別の手を考えて"]), "打ち消しの答えと別の動詞は止めない")
    check(not flipped("この検出は足さずに、 規約の文で持つ形でよいですか", ["足さない", "それでも足す"]),
          "別の打ち消しの形 (足さずに × 足さない) でもボタンが向きを繰り返せば止めない")
    check(not flipped("参照の受領を待たずに今から書き始めますか", ["書き始める", "受領を待つ"]),
          "途中の節の打ち消し (待たずに書き始めますか) は止めない")
    check(not flipped("見積もりの依頼は送らずに、 別々に買いますか", ["別々に買う", "依頼も送る"]),
          "読点の前の節の打ち消しは止めない")
    check(not flipped("指摘は一回ずつ回しますか", ["回す", "まとめて回す"]), "「一回ずつ」 の類 (素の「ず」) は止めない")
    check(not flipped("まず送りますか", ["送る", "まだ送らない"]), "「まず」 は打ち消しでない")
    check(not flipped("見出しだけは、 校正の直しでも本人の OK が要るようにしますか", ["そうする", "今のまま"]),
          "言い直した問い (肯定 × 仮名の答え) は止めない")
    check(not flipped("この 3 file を当てますか", ["当てる", "当てない"]), "肯定の問いは止めない")
    check(not flipped("一緒に送りませんか", ["送る", "やめる"]), "勧めの「〜ませんか」 は見ない")
    check(not flipped("見出しの例外を残しますか (当てない案もある)", ["当てる", "残す"]), "括弧の中の打ち消しは見ない")
    check(not flipped("どちらにしますか", ["はい", "いいえ"]), "仮名だけの答えは見ない")
    check(not flipped("", ["当てる"]) and not flipped("当てないか", []), "空の問い・空の答え")
    # 部品
    check(leading_answer("当てる (見出しは語が少なく…)") == "当てる" and leading_answer("そうする。 理由") == "そうする"
          and leading_answer("  進める、 今日中に") == "進める", "推す答えの先頭の語")
    check(verb_forms("例外は残す") is None and verb_forms("まだ送らない") is None and verb_forms("そうする") is None,
          "打ち消し・据え置き・仮名だけの答えは動詞にしない")
    check("送らない" in (verb_forms("送る") or ("", []))[1] and "当てない" in (verb_forms("当てる") or ("", []))[1]
          and "帰らない" in (verb_forms("帰る") or ("", []))[1], "辞書形の打ち消し (五段・一段・る の両方)")
    n = notice(q0, flipped(q0, ["当てる", "例外は残す"]))
    check("当てない" in n and RULE in n, "書き直しの文に打ち消しの形と正本")
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv) -> int:
    if "--selftest" in argv:
        return selftest()
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[0])
        return 2
    print(json.dumps(flipped(argv[0], argv[1:]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
