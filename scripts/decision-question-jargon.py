#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decision-question-jargon.py — 本人への問い (最終の返事の問いの行・選択肢 UI・turn 終わりの箱) に作業側の語 (掲示板の動詞・台帳の符号・event id・内輪の略語) が入っているか、 原稿の要旨・序論・題・結論の文を変えるかを今の文と直した文を見せずに問うていたら、 1 回だけ注意する engine (hook = hooks/decision-question-jargon-nudge.sh、 語 = hooks/decision-question-jargon-terms.txt + ~/.claude/decision-question-jargon-ext.txt、 校正 = `calibrate --since`、 --selftest。 conventions/concise-output.md#decision-questions / #show-the-text-being-changed)

変える文の検査 (語の一覧に依らない。 conventions/concise-output.md#show-the-text-being-changed):
  問いの単位が区画の名 (要旨・概要・序論・結論・題・表題・副題・タイトル・abstract・introduction・title・conclusion) と
  変更を問う語 (変えますか・直してよいか・当てますか・見直しますか・残しますか・おすすめどおりで … の形) を同じ単位に持ち、
  返事の全体 (Stop = 最終発話 + 今の turn の箱と選択肢 UI の全文 / tool の面 = その tool の文) に今の文と直した文の対が無いとき。
  問いの単位 = Stop は最終発話の問いの行 (下の Q_RE) と箱の ask の欄と選択肢 UI、 tool の面は箱の ask の欄 (recap は済んだことの報告) と選択肢 UI の全文。
  対 = 行頭の「今:」 と「案:」 の組 (現 / 旧 / 変更前 / before と 新 / 直した文 / 変更後 / after も) / 「…」→「…」 /
  「…」のまま …「…」に / 行頭の > の引用 / code block。 「」 で 1 つだけ引いた文は対と見なさない (今の文だけ、 または
  直した文だけを引いた問いが本人に通じなかった = 実測)。
  除く = 刷り直し・組み直し・作り直し・やり直し (印刷・作業の問い) / 別の session の問いの取り次ぎ (#local_ の link を持つ問い) /
  「」『』 で引いた問いしか問いの形を持たない行 (別の窓に残った問いの報告 = own_question、 Stop の問いの行の見分けも同じ)。
  Stop の差し戻しの続き (stop_hook_active) でも見る = 他の hook の差し戻しの後に書いた追記が、 また文を見せずに問うことがある (実測)。
  自分が差し戻した続き (差し戻しの行に SHOW_MARK) と、 続きの形が分からないときは黙る (hook-authoring.md#stop-hook-active-other-hooks)。
  既知の限界: 区画を箇条書きに並べ、 その下の行で「おすすめどおり直してよいか」 とだけ問う形は見ない (区画の名を問いの直前の
  数行にまで広げると、 校正で鳴る数が 2 倍強になり、 増えた分に本人が「分からない」 と返した問いは無かった)。

本文の行番号の検査 (2026-11-04、 conventions/concise-output.md#locate-by-quote-not-line-number): Stop で最終の返事の本文 (問いの行に
  限らない) に行番号の形があれば、 節の名・式の番号・文の書き出しに言い直す追記を 1 回求める。 形 = 英字の原稿の形 (L540・L1071 =
  L のあとに数字 2〜5 桁 / l.119 / `.tex:540`) と、 日本語の形 (2026-11-09 に足した = 「の 238 行目」「112〜118 行」「304・306 行」、
  場所の手がかりつきの単独の「494 行」。 線引きは JA_LINE_* の注釈、 校正 = `calibrate --since` の行番号の段)。 日本語の形は原稿でも
  code の file でも当てる (本人は code の行番号でも探さない)。 code block の中・「」『』 の中・押せる link ([…](…)) は見ない。
  英字の code の場所 (`file.py:42`) は押せる形なので当てない (英字の形は `.tex` だけ当てる)。 差し戻しの続き (stop_hook_active) では見ない。
  見るのは本人に見せる chat の返事だけ = agent 同士の文 (別 session への message・掲示板・依頼書・results の file) は見ない
  (本人の裁定 2026-11-09 = 人間相手には許さず、 機械同士は `file:行` を積極的に使う = concise-output.md#line-numbers-between-agents)。

箱の承認の検査 (2026-11-04、 conventions/mid-turn-text-visibility.md#turn-closing-question-box): turn 終わりの箱 (wrap_up) の ask の
  欄が、 文面の送信・投稿の承認 (「送ってよいか」「この文面で」) か、 本文にある下書き・案・条件 (「下の案」「推す条件で」) を指す
  とき、 箱を止める (permissionDecision = deny、 TOOL_MODE に依らない)。 箱の後の本文は本人に見えないことがあり、 本文を読まない
  承認になる (実測)。 文面と問いは最終の返事の本文に書き、 箱は要約だけで閉じる。

何を見るか (3 つの面、 どれも「本人が読む問い」):
  Stop                      今の turn の最終 assistant 発話のうち**問いの行** (下の Q_RE) と、 その行に続く字下げの深い行
                            (= list item の sub-bullet。 問いの item の中身は sub-bullet に書かれることが多い)。 問いでない行は見ない。
  PreToolUse AskUserQuestion question / header / options の label と description (全部が本人に出る)
  PreToolUse <…>__wrap_up   turn 終わりの箱 (Claude desktop の `mcp__ccd_turn__wrap_up`): recap / ask / actions の label と message。
                            実測: 本人が「分からない」 と返した「現在地」 の 1 つは chat の文でなくこの箱の recap だった。

語の一覧 (1 行 1 語、 `re:` で始まる行は正規表現、 それ以外は literal、 `#` はコメント。 `pointer:` は注意文の末尾に添える正本):
  既定 = hooks/decision-question-jargon-terms.txt (層1 = どの利用者でも作業側の語である形: 掲示板の動詞・台帳の符号・event id)
  個人 = ~/.claude/decision-question-jargon-ext.txt (個人層が symlink で置く。 内輪の略語・呼び名。 env DECISION_QUESTION_JARGON_EXT で差し替え)
  両方読めなければ沈黙 (語が無い hook は鳴らない = 故障を違反と同じ値にしない)。

除外 (= 符号は「添えるだけ」 なら通す、 conventions/concise-output.md#decision-questions):
  - 語の直後に `=` / `(` / `（` / `:` が続く = 普通の語の説明が添えてある (「Q14 = 赤字の確認を外すか」)
  - 語が 「」 / 『』 の中に丸ごと収まる = 例として引いただけ (hook 自身を説明する文で鳴らない)

出力 (hook-authoring.md#text-pattern-stop-hook / #stop-hook-addendum-not-reemission):
  Stop        {"decision":"block","reason":…} を 1 回だけ (語の検査は stop_hook_active = true なら見ない。 変える文の検査は上のとおり)。
              2 つの検査が当たれば 1 つの reason にまとめる。 reason は「問いの部分 / 文の対だけを短い追記で」 を求め、
              返事の全文の出し直しは求めない。 (Stop で model に届く経路は block しか無い = 「注意」 の実装は 1 回の block)
  PreToolUse  既定 = additionalContext (止めない。 ⚠️ 選択肢 UI と箱は本人に先に出るので、 語の注意が効くのは次の問いから。
              箱の問いが文を見せていない注意は、 箱の後に書く締めの返事に間に合う)。
              env DECISION_QUESTION_JARGON_TOOL_MODE=deny なら permissionDecision=deny + reason (本人が見る前に書き直させる)。
  故障 (入力不正・transcript 不在・部品の import 失敗) は沈黙 (exit 0)。 語の一覧が無いときは語の検査だけが黙る。

校正 (導入前と、 語を変えるたび): `decision-question-jargon.py calibrate --since YYYY-MM-DD [--show] [--terms F] [--ext F]`
  = この機械の全部の設定フォルダの transcript (lib/claude_config_dirs.py) の各 turn の最終発話・AskUserQuestion・wrap_up に
  本番と同じ述語を当て、 問いの turn の数・鳴った数・語ごとの数を出す。 ⚠️ transcript は private data、 --show の抜粋を公開の場所に貼らない。
  導入前の校正 (直近 2 週、 問いを含む turn 550 + 選択肢 UI 13 + 箱 224): 採った語と落とした語の理由は hooks/decision-question-jargon-terms.txt
  のコメントに。 落とした候補 = commit hash だけの参照 (27 turn、 ほぼ全部が出所の注記)、 `§N` (35 turn、 著者本人には節の位置の語)、
  `--flag` (6 turn、 全部が手順の説明)、 file 名 (64 turn)、 数式記号の連なり (23 turn、 物理の内容そのもの)。

環境変数: DECISION_QUESTION_JARGON_DISABLE=1 (一時無効) / DECISION_QUESTION_JARGON_TERMS (既定の一覧の path) /
  DECISION_QUESTION_JARGON_EXT (個人の一覧の path) / DECISION_QUESTION_JARGON_TOOL_MODE (notice | deny) /
  CLAUDE_CONFIG_ROOT (部品 scripts/lib の置き場所を上書き。 既定 = この file の隣の lib、 無ければ ~/Claude/claude-config)
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.realpath(__file__))
for _lib in (os.path.join(_HERE, "lib"),
             os.path.join(os.environ.get("CLAUDE_CONFIG_ROOT") or os.path.expanduser("~/Claude/claude-config"), "scripts", "lib")):
    if os.path.isdir(_lib) and _lib not in sys.path:
        sys.path.insert(0, _lib)
        break

DEFAULT_TERMS = os.path.join(_HERE, "..", "hooks", "decision-question-jargon-terms.txt")
DEFAULT_EXT = os.path.expanduser("~/.claude/decision-question-jargon-ext.txt")
RULE = "claude-config/conventions/concise-output.md#decision-questions"

# 問いの行: 「〜か。」「〜か？」「〜か**:」「〜か →」 (list item の末尾に推す答えが続く形) / 「？」 / どちら・どっち・どれに /
# よいですか・でよいか / 教えて・答えて・選んで・決めてください / ご判断・判断を仰ぐ。 「どちらも」「どれも」 は問いでない。
Q_RE = re.compile(
    r"か(?:\*\*|\*|」|』|\)|）)*\s*(?:[。？?:：→]|$)"
    r"|[？?](?=\s|$|[」』)）*])"
    r"|どちら(?!も|でも)|どっち|どれ(?:に|を|が|で)(?!も)"
    r"|(?:よい|いい)ですか|でよいか|でいいか"
    r"|教えてください|答えてください|選んでください|決めてください|決めてもらう|答えてほしい|決めてほしい"
    r"|ご判断|判断を(?:お願い|仰|求)",
    re.M)
GLOSS_AFTER = re.compile(r"^\s?[=＝(（:：]")   # 語の直後に説明が続く形
# 「」 / 『』 で引いた問い = 別の窓に残っている問いや人の問いを報告しているだけで、 この返事の問いではない
# (実測: 別の窓に残った「要旨を…差し替えてよいですか？」 を取り次いだだけの行が問いの行と読まれ、 変える文の検査が差し戻した)
QUOTED = re.compile(r"「[^「」\n]*」|『[^『』\n]*』")


def own_question(line: str) -> bool:
    """行が、 引用した問いを除いても問いの形を持つか (引用の中の問いだけで問いの行にしない)。 入れ子の「「…」…か」 は
    内側から外す = 問いでない引用を □ に置いて外側の引用が次の回で 1 つの引用として読めるようにする (実測: 規則の文書の
    変更を報告する行の「「終えた」 = …、 か」→「…」 が外側の引用を外せず、 問いの行と読まれて語の検査が差し戻した)。"""
    t, prev = line, None
    while prev != t:
        prev, t = t, QUOTED.sub(lambda m: "" if Q_RE.search(m.group(0)[1:-1]) else "□", t)
    return bool(Q_RE.search(t))


def question_units(text: str) -> list:
    """問いの行 (own_question) + その行より字下げの深い続きの行 (空行か同じ以下の字下げで止まる)。"""
    lines = (text or "").split("\n")
    units, i = [], 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if s and own_question(s):
            indent = len(raw) - len(raw.lstrip())
            buf, j = [s], i + 1
            while j < len(lines):
                r2 = lines[j]
                if not r2.strip():
                    break
                if len(r2) - len(r2.lstrip()) <= indent:
                    break
                buf.append(r2.strip())
                j += 1
            units.append("\n".join(buf))
            i = j
        else:
            i += 1
    return units


def load_terms(path):
    """→ (terms, pointer)。 terms = [(label, compiled)]。 読めなければ ([], None)。"""
    terms, pointer = [], None
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("pointer:"):
                    pointer = line[len("pointer:"):].strip() or pointer
                    continue
                try:
                    if line.startswith("re:"):
                        terms.append((line[3:], re.compile(line[3:])))
                    else:
                        terms.append((line, re.compile(re.escape(line))))
                except re.error:
                    continue
    except OSError:
        return [], None
    return terms, pointer


def all_terms(terms_path=None, ext_path=None):
    base, _ = load_terms(terms_path or os.environ.get("DECISION_QUESTION_JARGON_TERMS") or DEFAULT_TERMS)
    ext, pointer = load_terms(ext_path or os.environ.get("DECISION_QUESTION_JARGON_EXT") or DEFAULT_EXT)
    return base + ext, pointer


def _inside_quote(text, i):
    try:
        from transcript_turns import inside_quote
        return inside_quote(text, i)
    except Exception:
        return False


def find_jargon(text: str, terms, as_question: bool = False) -> list:
    """text の問いの行 (as_question=True なら text 全体を 1 つの問いとして) に入っている作業側の語 (重複なし、 出現順)。"""
    units = [text] if as_question else question_units(text)
    found = []
    for unit in units:
        for _label, pat in terms:
            for m in pat.finditer(unit):
                if _inside_quote(unit, m.start()) and _inside_quote(unit, m.end()):
                    continue
                if GLOSS_AFTER.match(unit[m.end():m.end() + 2]):
                    continue
                word = m.group(0)
                if word not in found:
                    found.append(word)
    return found


def notice(words, pointer=None) -> str:
    refs = RULE + (f" / {pointer}" if pointer else "")
    return (f"🗣 本人への問いに作業側の語 ({'・'.join(words[:6])}) が入っています。 "
            f"何の話か → 変えると何が変わるか → 決めること、 の順に普通の語で書き直す ({refs})")


# ── 変える文を見せずに、 原稿の要旨・序論・題・結論の文の変更を問う ─────────────

LINE_MARK = "🧭 返事の本文に原稿の行番号"   # Stop の差し戻しの印
LINE_RULE = "claude-config/conventions/concise-output.md#locate-by-quote-not-line-number"
LINE_REF_RE = re.compile(r"(?<![A-Za-z0-9_$\\])L\d{2,5}(?![0-9])|(?<![A-Za-z0-9_])l\.\s?\d{2,5}(?![0-9])|\.tex:\d{1,5}(?![0-9])")
_FENCE_BLOCK = re.compile(r"^\s*```.*?^\s*```[^\n]*$", re.M | re.S)
_MD_LINK = re.compile(r"\[[^\]\n]*\]\([^)\n]*\)")   # 押せる link (行つきの link も) は見ない
# 日本語の形 (2026-11-09 に足した。 直近 3 週の最終の返事 4709 turn で校正 = 鳴る 78 turn、 読んだ範囲で誤検出なし):
#   N 行目・N〜M 行目・N・M 行目 (数のどれかが 2 桁以上。 「返事の 1 行目」「表の 1 行目」 は 1 桁なので外れる) /
#   N〜M 行 (範囲、 量の語が続けば外す) / N・M 行 (2 桁以上の番号の並び) /
#   単独の N 行 (2 桁以上) は場所の手がかりがある時だけ: 前が章・注・付録・式・図・file の拡張子・英大文字・外した引用の空き
#   (「第 1 章 488 行」「付録 A 1126 行」「`a.tex` の 490 行」) / 後ろが前半・後半・あたり・にある・で止ま・名詞の「の」
#   (「494 行の綴り」) / 箇条の頭の「488 行:」。 量の語が続けば外す (「240 行に漏れは」「13 行とも」「481 行のまま」「113 行から 34 行に」)。
#   見ない形 (校正で量だった) = 「表の 36 行」「節の 29 行」 (表・節の前置き)、 「止まっている 22 行:」 (箇条の頭でないコロン)。
JA_LINE_ORD = re.compile(r"(?<![0-9.,])\d{1,5}(?:\s*[〜~\-–・、]\s*\d{1,5})*\s*行目")
JA_LINE_RANGE = re.compile(r"(?<![0-9.,])(\d{1,5})\s*[〜~\-–]\s*(\d{1,5})\s*行(?!目)"
                           r"(?!\s*(?:ほど|くらい|ぐらい|程度|分|弱|強|以内|以上|未満|超|を|が|増|減|足|消|ずつ))")
JA_LINE_LIST = re.compile(r"(?<![0-9.,])\d{2,5}(?:\s*[・、]\s*\d{2,5})+\s*行(?!目)")
JA_LINE_BARE = re.compile(r"(?<![0-9.,A-Za-z])\d{2,5}\s*行(?!目)")
_JA_BEFORE_LOC = re.compile(r"(?:[章注録式図]|付録\s*[A-Z]?|\.[A-Za-z]{1,5}|[A-Z]|\s{2,})\s*(?:の)?\s*$")
_JA_AFTER_LOC = re.compile(r"^\s*(?:前半|後半|あたり|付近|辺り|の前後|にあり|にある|で止ま"
                           r"|の(?!うち|中|全|すべて|追加|差分|変更|削除|分|合計|計|行|範囲|まま|扱い|file|ファイル|script|コード|段落|文書|表))")
_JA_AFTER_QTY = re.compile(r"^\s*(?:とも|ほど|くらい|ぐらい|程度|分|弱|強|以内|以上|未満|超|を|が|増|減|足|消|ずつ|すべて|全部|のうち"
                           r"|に漏れ|で[、。す]|から\s*\d|に縮|出|あり|ある|の(?:行|範囲|まま|扱い))")
_JA_ITEM_HEAD = re.compile(r"^\s*(?:[-*]\s*)?(?:\d{1,2}[.)]\s*)?(?:\*\*)?\s*$")


def _ja_line_refs(body: str) -> list:
    """日本語の形の行番号 [(位置, 文字列)] (body は code block・引用・link を外した後)。"""
    out = []
    for m in JA_LINE_ORD.finditer(body):
        if max(int(x) for x in re.findall(r"\d+", m.group(0))) >= 10:
            out.append((m.start(), m.group(0)))
    for m in JA_LINE_RANGE.finditer(body):
        if max(int(m.group(1)), int(m.group(2))) >= 10:
            out.append((m.start(), m.group(0)))
    for m in JA_LINE_LIST.finditer(body):
        out.append((m.start(), m.group(0)))
    taken = [(s, s + len(t)) for s, t in out]
    for m in JA_LINE_BARE.finditer(body):
        if any(a <= m.start() < b for a, b in taken):
            continue
        before, after = body[max(0, m.start() - 12):m.start()], body[m.end():m.end() + 12]
        if _JA_AFTER_QTY.match(after):
            continue
        head = _JA_ITEM_HEAD.match(body[body.rfind("\n", 0, m.start()) + 1:m.start()])
        if (head and re.match(r"^\s*(?:\*\*)?\s*[:：]", after)) or _JA_BEFORE_LOC.search(before) or _JA_AFTER_LOC.match(after):
            out.append((m.start(), m.group(0)))
    return out


def line_refs(text: str) -> list:
    """返事の本文の行番号の形 (英字の形 = 原稿の L540・l.119・.tex:540 / 日本語の形 = 原稿でも code でも「の 238 行目」 の類)、
    出現順に 4 つまで。 code block・「」『』 の中・押せる link ([…](…)) は見ない。"""
    body = _MD_LINK.sub(" ", QUOTED.sub(" ", _FENCE_BLOCK.sub(" ", text or "")))
    hits = [(m.start(), m.group(0)) for m in LINE_REF_RE.finditer(body)] + _ja_line_refs(body)
    out = []
    for _s, t in sorted(hits):
        t = re.sub(r"\s+", " ", t)
        if t not in out:
            out.append(t)
    return out[:4]


def line_notice(refs) -> str:
    return (f"{LINE_MARK} ({'、 '.join(refs)}) があります: 読む人の手元に行番号は無い。 節の名・式の番号・文の書き出しで"
            f"言い直す短い追記を書く (前の返事は出し直さない。 code の場所は本文に行番号を書かず、 押せる link"
            f" [file.py:42](path:42) か `file.py:42` にする。 agent 同士の文 (別 session への message・掲示板・依頼書・results)"
            f" は `file:行` で書いてよい。 正本 = {LINE_RULE})")


BOX_MARK = "📨 箱の問いが文面の承認か本文を指しています"
BOX_RULE = "claude-config/conventions/mid-turn-text-visibility.md#turn-closing-question-box"
BOX_APPROVAL_RE = re.compile(
    r"送(?:って|っても|信して|信しても|ります|信します)[^。\n]{0,8}(?:よい|いい|か)"
    r"|投稿(?:して|しても|します)[^。\n]{0,8}(?:よい|いい|か)"
    r"|この(?:下書き|文面|文章)で"
    r"|(?:下|上|本文|返事)の(?:下書き|文面|案|文|推す|条件|答え)"
    r"|推す(?:条件|答え|案)で")


def box_approval_asks(tool_name: str, tool_input) -> list:
    """箱の ask の欄のうち、 文面の承認か本文の下書き・案・条件を指す問い (箱だけ。 選択肢 UI は見ない)。"""
    if not (tool_name or "").endswith("__wrap_up"):
        return []
    return [a for a in tool_asks(tool_name, tool_input) if BOX_APPROVAL_RE.search(a)]


SHOW_RULE = "claude-config/conventions/concise-output.md#show-the-text-being-changed"
SHOW_MARK = "🗣 変える文が返事にありません"   # Stop の差し戻しの印 (差し戻しの続きで自分の分を見分ける)
FEEDBACK_PREFIX = "Stop hook feedback"
# 区画の名。 「題」 は問題・課題・議題などの語の一部を除く。 英語の語は前後が英字でないこと (\b は日本語に隣ると効かない)
SECTION_RE = re.compile(
    r"要旨|概要|アブストラクト|序論|結論|表題|副題|タイトル|(?<![問課宿議話主例出難命演])題(?![目材])"
    r"|(?<![A-Za-z])(?:abstract|introduction|title|conclusions?)(?![A-Za-z])", re.I)
# 変更を問う語。 刷り直し・組み直し・作り直し・やり直しは印刷や作業の問いなので除く
_CHANGE_V = (r"(?<!刷り)(?<!組み)(?<!作り)(?<!やり)(?<![刷組作見])"
             r"(?:変え|直し|当て|見直し|書き換え|差し替え|置き換え|入れ替え|残し|外し|削り|削除し|足し|加え|下げ|戻し|改め|言い換え|言い直し)")
CHANGE_RE = re.compile(
    _CHANGE_V + r"(?:ます|る|ません)?か(?![らな])"
    + r"|" + _CHANGE_V + r"て(?:もらって|いただいて)?(?:も)?(?:よい|いい|大丈夫)(?:です)?か"
    r"|(?:おすすめ|推奨|推し|この案|案\s?[A-Z]?)(?:どおり|通り)?(?:で|に)[^。？?\n]{0,12}(?:よい|いい|当て|直|進め)")
# 今の文と直した文を見せている形
_SHOW_FENCE = re.compile(r"^\s*```", re.M)
_SHOW_QUOTE = re.compile(r"^\s*>\s?\S", re.M)
_LEAD = r"^\s*(?:[-*・]|\d+[.)])?\s*(?:\*\*)?"
_SHOW_NOW = re.compile(_LEAD + r"(?:今|現在|現行|元|旧|現|変更前|修正前|before|current)(?:の文|の題|の形)?(?:\*\*)?\s*[:：]", re.M | re.I)
_SHOW_NEW = re.compile(_LEAD + r"(?:案|新|後|直した文|直し|改|変更後|修正後|after|proposed)(?:の文|の題|の形)?(?:\*\*)?\s*[:：]", re.M | re.I)
_Q = r"[「『\"“`][^」』\"”`\n]{3,}[」』\"”`]"
_SHOW_ARROW = re.compile(_Q + r"\s*(?:→|⇒|->)\s*" + _Q)
_SHOW_ALT = re.compile(_Q + r"\s*(?:の)?まま[^\n]{0,40}?" + _Q + r"\s*(?:に|へ)")   # 「今の形」のまま … 「直した形」に


def shows_change(text: str) -> bool:
    """今の文と直した文の対を見せているか (行頭の 今: と 案: の組 / 「…」→「…」 / 「…」のまま …「…」に / 引用 / code block)。"""
    t = text or ""
    return bool(_SHOW_FENCE.search(t) or _SHOW_QUOTE.search(t) or (_SHOW_NOW.search(t) and _SHOW_NEW.search(t))
                or _SHOW_ARROW.search(t) or _SHOW_ALT.search(t))


def unshown_change_questions(units, whole: str) -> list:
    """区画の名と変更を問う語を同じ単位に持つ問いのうち、 返事の全体 (whole) が文の対を見せていないもの。
    別の session の問いの取り次ぎ (#local_ の link を持つ問い) は除く (その窓で問われている)。"""
    if shows_change(whole):
        return []
    return [u for u in units if CHANGE_RE.search(u) and SECTION_RE.search(u) and "(#local_" not in u]


def sections_named(units) -> list:
    found = []
    for u in units:
        for m in SECTION_RE.finditer(u):
            w = m.group(0)
            if w not in found:
                found.append(w)
    return found


def show_notice(units) -> str:
    return (f"{SHOW_MARK}: 原稿の {'・'.join(sections_named(units)[:4]) or '区画'} の文を変えるかを本人に問うていますが、"
            f" 今の文と直した文が返事にありません。 区画ごとに「今: <今の文をそのまま>」「案: <直した文>」 と、"
            f" 何が変わるかを 1 行で並べる。 変えないかを決める問いでも、 今の文はそのまま引く ({SHOW_RULE})")


def _user_text(e: dict) -> str:
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text") or "" for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def own_show_block_in_chain(entries) -> bool | None:
    """差し戻しの続き (stop_hook_active) で、 続きの差し戻しの行に自分の印 (SHOW_MARK) があるか。
    今の turn が差し戻しの行で始まっていなければ None (形が分からない = 黙る)。 hook-authoring.md#stop-hook-active-other-hooks"""
    from transcript_turns import is_real_user
    idx = [i for i, e in enumerate(entries) if is_real_user(e)]
    if not idx or not _user_text(entries[idx[-1]]).lstrip().startswith(FEEDBACK_PREFIX):
        return None
    for i in reversed(idx):
        text = _user_text(entries[i])
        if not text.lstrip().startswith(FEEDBACK_PREFIX):
            return False
        if SHOW_MARK in text:
            return True
    return False


def turn_box_parts(turn) -> tuple:
    """今の turn の箱と選択肢 UI の → (問いの文の list, 本人に出る全文)。"""
    asks, alltext = [], []
    for e in turn:
        if e.get("type") != "assistant":
            continue
        for b in ((e.get("message") or {}).get("content") or []):
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            name = b.get("name", "")
            text = tool_text(name, b.get("input"))
            if not text:
                continue
            alltext.append(text)
            if name.endswith("__wrap_up"):
                a = (b.get("input") or {}).get("ask")
                if isinstance(a, str) and a.strip():
                    asks.append(a)
            else:
                asks.append(text)
    return asks, "\n".join(alltext)


# ── hook の 3 つの面 ──────────────────────────────────────────

def stop_reason(inp: dict, terms, pointer):
    """作業側の語 (差し戻しの続きでは見ない) と、 変える文を見せない問い (差し戻しの続きも見る。 自分が差し戻した続きは見ない) を
    1 つの差し戻しにまとめる。"""
    rerun = bool(inp.get("stop_hook_active"))
    path = inp.get("transcript_path")
    if not path or not os.path.isfile(path):
        return None
    try:
        from transcript_turns import current_turn, load_entries, summarize
        entries = load_entries(path)
        turn = current_turn(entries)
        final, _ = summarize(turn)
        asks, boxtext = turn_box_parts(turn)
        skip_show = rerun and own_show_block_in_chain(entries) is not False
    except Exception:
        return None
    parts = []
    words = find_jargon(final, terms) if (final and terms and not rerun) else []
    if words:
        parts.append(notice(words, pointer) + "。 前の返事は本人の画面に出ているので本文は出し直さず、 問いの部分だけを普通の語で"
                     "短い追記に書く (符号を残すなら、 何の話かの説明を直後に添える)。 どの語にも説明が既に添えてあるなら、 その旨の 1 行で終了してよい。")
    refs = line_refs(final) if (final and not rerun) else []
    if refs:
        parts.append(line_notice(refs) + "。 場所でない (足した行数などの量・表の行の数) なら、 その旨の 1 行で終了してよい。")
    units = [] if skip_show else unshown_change_questions(
        (question_units(final) if final else []) + asks, (final or "") + "\n" + boxtext)
    if units:
        parts.append(show_notice(units) + "。 前の返事は出し直さず、 その対だけを短い追記に書く。 印刷・構成・別の窓の問いの取り次ぎのように"
                     "文の変更を問うていない、 または対が既に返事にあるなら、 その旨の 1 行で終了してよい。")
    return "\n\n".join(parts) or None


def tool_text(tool_name: str, tool_input) -> str | None:
    """本人に出る文だけを 1 つの文字列に。 対象外の tool は None。"""
    name = tool_name or ""
    if name == "AskUserQuestion":
        parts = []
        for q in (tool_input or {}).get("questions") or []:
            if not isinstance(q, dict):
                continue
            parts += [q.get("question", ""), q.get("header", "")]
            for o in q.get("options") or []:
                if isinstance(o, dict):
                    parts += [o.get("label", ""), o.get("description", "")]
        return "\n".join(p for p in parts if isinstance(p, str) and p)
    if name.endswith("__wrap_up"):
        ti = tool_input or {}
        parts = [ti.get("recap", ""), ti.get("ask", "")]
        for a in ti.get("actions") or []:
            if isinstance(a, dict):
                parts += [a.get("label", ""), a.get("message", "")]
        return "\n".join(p for p in parts if isinstance(p, str) and p)
    return None


def tool_asks(tool_name: str, tool_input) -> list:
    """変える文の検査に使う問いの文 (箱は ask の欄だけ = recap は済んだことの報告、 選択肢 UI は全部)。"""
    if (tool_name or "").endswith("__wrap_up"):
        a = (tool_input or {}).get("ask") if isinstance(tool_input, dict) else None
        return [a] if isinstance(a, str) and a.strip() else []
    text = tool_text(tool_name, tool_input)
    return [text] if text else []


def tool_output(inp: dict, terms, pointer):
    name, ti = inp.get("tool_name", ""), inp.get("tool_input")
    text = tool_text(name, ti)
    if not text:
        return None
    words = find_jargon(text, terms, as_question=True) if terms else []
    units = unshown_change_questions(tool_asks(name, ti), text)
    approvals = box_approval_asks(name, ti)
    if not words and not units and not approvals:
        return None
    msgs = ([notice(words, pointer)] if words else []) + ([show_notice(units)] if units else [])
    if approvals:
        msgs.append(f"{BOX_MARK} (「{approvals[0][:40]}」): 箱の後に書く本文は本人に見えないことがある = 本文を読まない承認になる。"
                    f" 文面・案・条件と問いは最終の返事の本文に書き、 箱は要約だけで閉じる (正本 = {BOX_RULE})")
    mode = os.environ.get("DECISION_QUESTION_JARGON_TOOL_MODE", "notice")
    if mode == "deny" or approvals:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": "。 ".join(msgs) + "。 問いと選択肢を書き直してから、 もう一度呼ぶ。"}}
    tail = []
    if words:
        tail.append("この問いはそのまま本人に出ます。 答えが返ったら、 次に問う文は普通の語で書く。")
    if units:
        tail.append("箱の問いは本人に先に出ます。 この後の締めの返事に、 その対を並べる (並べれば turn の終わりの検査は通る)。")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "additionalContext": "。 ".join(msgs) + "。 " + " ".join(tail)}}


def run_auto(inp: dict) -> int:
    if os.environ.get("DECISION_QUESTION_JARGON_DISABLE") == "1":
        return 0
    terms, pointer = all_terms()   # 語の一覧が無ければ語の検査だけを止める (変える文の検査は一覧に依らない)
    ev = inp.get("hook_event_name") or ("PreToolUse" if "tool_name" in inp else "Stop")
    out = None
    if ev == "Stop":
        r = stop_reason(inp, terms, pointer)
        if r:
            out = {"decision": "block", "reason": r}
    elif ev == "PreToolUse":
        out = tool_output(inp, terms, pointer)
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


# ── 校正 ──────────────────────────────────────────────────────

def calibrate(argv) -> int:
    import argparse
    from datetime import datetime, timezone
    ap = argparse.ArgumentParser(prog="decision-question-jargon.py calibrate")
    ap.add_argument("--since", required=True, help="YYYY-MM-DD (この日を含む)")
    ap.add_argument("--terms")
    ap.add_argument("--ext")
    ap.add_argument("--show", action="store_true", help="鳴った turn の問いの行を出す (private data、 公開の場所に貼らない)")
    ap.add_argument("--glob", help="transcript の glob (既定 = この機械の全部の設定フォルダ)")
    a = ap.parse_args(argv)
    from transcript_turns import load_entries, summarize, turns
    try:
        import claude_config_dirs as ccd
        files = ccd.transcript_paths(a.glob)
    except Exception:
        import glob as _g
        files = _g.glob(os.path.expanduser(a.glob or "~/.claude/projects/*/*.jsonl"))
    terms, pointer = all_terms(a.terms, a.ext)
    since = datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    def ts_of(e):
        t = e.get("timestamp") if isinstance(e, dict) else None
        try:
            return datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None
        except Exception:
            return None

    counts = {"stop": [0, 0], "ask": [0, 0], "wrap": [0, 0], "show_stop": [0, 0], "show_tool": [0, 0], "line": [0, 0]}
    per_term = {}
    shown = []
    show_hits = []
    line_hits = []
    for fp in files:
        try:
            if datetime.fromtimestamp(os.path.getmtime(fp), tz=timezone.utc) < since:
                continue
            entries = load_entries(fp)
        except OSError:
            continue
        sid = os.path.basename(fp)[:8]
        for turn in turns(entries):
            ts = next((ts_of(e) for e in turn if ts_of(e)), None)
            if ts and ts < since:
                continue
            final, _ = summarize(turn)
            if final:
                counts["line"][0] += 1
                refs = line_refs(final)
                if refs:
                    counts["line"][1] += 1
                    line_hits.append((sid, ts, refs, final))
            if final and question_units(final):
                counts["stop"][0] += 1
                words = find_jargon(final, terms)
                if words:
                    counts["stop"][1] += 1
                    for w in words:
                        per_term[w] = per_term.get(w, 0) + 1
                    shown.append(("stop", sid, ts, words, question_units(final)))
            asks, boxtext = turn_box_parts(turn)
            q = (question_units(final) if final else []) + asks
            if q:
                counts["show_stop"][0] += 1
                u = unshown_change_questions(q, (final or "") + "\n" + boxtext)
                if u:
                    counts["show_stop"][1] += 1
                    show_hits.append(("stop", sid, ts, u))
            for e in turn:
                if e.get("type") != "assistant":
                    continue
                for b in ((e.get("message") or {}).get("content") or []):
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    text = tool_text(b.get("name", ""), b.get("input"))
                    if text is None:
                        continue
                    kind = "ask" if b.get("name") == "AskUserQuestion" else "wrap"
                    counts[kind][0] += 1
                    words = find_jargon(text, terms, as_question=True)
                    if words:
                        counts[kind][1] += 1
                        for w in words:
                            per_term[w] = per_term.get(w, 0) + 1
                        shown.append((kind, sid, ts_of(e) or ts, words, [text]))
                    ta = tool_asks(b.get("name", ""), b.get("input"))
                    if ta:
                        counts["show_tool"][0] += 1
                        u = unshown_change_questions(ta, text)
                        if u:
                            counts["show_tool"][1] += 1
                            show_hits.append((kind, sid, ts_of(e) or ts, u))
    print(f"terms={len(terms)} pointer={pointer or '-'} files={len(files)} since={a.since}")
    for k, lab in (("stop", "問いを含む turn (Stop)"), ("ask", "AskUserQuestion"), ("wrap", "turn 終わりの箱 (wrap_up)"),
                   ("show_stop", "変える文の検査: 問いを含む turn (Stop)"), ("show_tool", "変える文の検査: 箱の ask・選択肢 UI"),
                   ("line", "本文の行番号の検査: 最終の返事 (Stop)")):
        n, h = counts[k]
        print(f"  {lab}: {n} 件中 {h} 件が鳴る" + (f" ({100.0 * h / n:.1f}%)" if n else ""))
    print("  語ごと (鳴った turn の数):")
    for w, n in sorted(per_term.items(), key=lambda kv: -kv[1]):
        print(f"    {n:3d}  {w}")
    if a.show:
        shown.sort(key=lambda r: (r[2].isoformat() if r[2] else ""))
        for kind, sid, ts, words, units in shown:
            print("=" * 80)
            print(kind, sid, ts.isoformat()[:19] if ts else "?", "・".join(words))
            for u in units:
                if any(p.search(u) for _l, p in terms):
                    print("   |", u[:300].replace("\n", " ⏎ "))
        show_hits.sort(key=lambda r: (r[2].isoformat() if r[2] else ""))
        for kind, sid, ts, units in show_hits:
            print("=" * 80)
            print("変える文", kind, sid, ts.isoformat()[:19] if ts else "?")
            for u in units:
                print("   |", u[:300].replace("\n", " ⏎ "))
        line_hits.sort(key=lambda r: (r[1].isoformat() if r[1] else ""))
        for sid, ts, refs, final in line_hits:
            print("=" * 80)
            print("行番号", sid, ts.isoformat()[:19] if ts else "?", "・".join(refs))
            for r in refs:
                i = final.find(r.split(" ")[0])
                print("   |", final[max(0, i - 50):i + len(r) + 25].replace("\n", " ⏎ "))
    return 0


# ── selftest ─────────────────────────────────────────────────

def selftest() -> int:
    import tempfile
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and cond

    tmp = tempfile.mkdtemp()
    tp = os.path.join(tmp, "terms.txt")
    with open(tp, "w", encoding="utf-8") as f:
        f.write("# test\nre:(?<![\\w./:-])(?:handover|accept|claim|submit)(?![\\w./:-])\n"
                "re:(?<![\\w-])(?!(?:[AB]\\d|M\\d|D[123]|[RH]\\d{1,2})(?![\\w.-]))[A-Z]{1,2}-?\\d{1,3}(?![\\w.-])\n"
                "re:追記\\s?\\d+\n")
    ep = os.path.join(tmp, "ext.txt")
    with open(ep, "w", encoding="utf-8") as f:
        f.write("pointer: personal/chat-style.md#x\nre:推す\\s*[=＝]\n呼び名A\n")
    terms, pointer = all_terms(tp, ep)
    check(len(terms) == 5 and pointer == "personal/chat-style.md#x", "一覧 2 本を読み、 pointer を取る")
    # 問いの行
    check(question_units("直しました。\n\nこの依頼を accept してよいですか？\n") == ["この依頼を accept してよいですか？"], "問いの行だけ")
    u = question_units("2. 案を当てるか**: 推す答えは次です。\n   - 例外 2 つ (W-3・X-7)\n   - 範囲外の直し\n次の段落")
    check(len(u) == 1 and "W-3" in u[0] and "次の段落" not in u[0], "問いの item の sub-bullet は同じ単位、 次の段落は別")
    check(question_units("どちらも push 済みです。") == [], "「どちらも」 は問いでない")
    check(question_units("1️⃣ **Q14 = 赤字 4 か所を外してよいか** → 推す答え = はい") != [], "「よいか** →」 も問い")
    check(question_units("URL は https://x/?a=1 です。") == [], "URL の ? は問いでない")
    # 当たり
    check(find_jargon("この依頼を accept してよいですか？", terms) == ["accept"], "掲示板の動詞")
    check(find_jargon("2. 案を当てるか**:\n   - 例外 2 つ (W-3・X-7)", terms) == ["W-3", "X-7"], "sub-bullet の符号")
    check(find_jargon("報告書 Q19 の追記 4–8 を確認しますか", terms) == ["Q19", "追記 4"], "台帳の符号と追記 N")
    check(find_jargon("どれにしますか。 推す = そのまま", terms) == ["推す ="], "個人の一覧の語")
    check(find_jargon("呼び名A の報告を読みますか", terms) == ["呼び名A"], "literal の語")
    # 通す
    check(find_jargon("commit W-3 を push しました。", terms) == [], "問いでない行は見ない")
    check(find_jargon("Q14 = 赤字の確認を外してよいか", terms) == [], "直後に = が続く符号は説明つき")
    check(find_jargon("別の件 (O6: 式の符号) を直してよいか", terms) == [], "直後に : が続く符号は説明つき")
    check(find_jargon("「accept」 という語を使わない方がよいですか", terms) == [], "「」 の中は例示")
    check(find_jargon("A4 で刷ってよいですか。 M5 の設定も切りますか。 R9 の調書を出しますか", terms) == [], "紙の大きさ・chip・元号は除く")
    check(find_jargon("Accept を押してよいですか", terms) == [], "大文字の Accept (UI のボタン名) は除く")
    check(find_jargon("some-claim-check.py を直してよいですか", terms) == [], "file 名の中の claim は除く")
    check(find_jargon("https://reviewer-feedback.example/x を押してください", terms) == [], "URL の中の語は除く")
    check(find_jargon("D10 の件を当てるか", terms) == ["D10"], "D10 は学年でなく符号")
    # tool の面
    ask = {"questions": [{"question": "reviewer を移して accept してよいですか？", "header": "x",
                          "options": [{"label": "移す", "description": "human handover で移す"}]}]}
    check(find_jargon(tool_text("AskUserQuestion", ask), terms, as_question=True) == ["accept", "handover"], "選択肢 UI の全部を見る")
    wrap = {"recap": "残りは Q19 の追記 4–8 の確認。", "ask": "一覧にしますか？", "actions": [{"label": "一覧に"}]}
    check(find_jargon(tool_text("mcp__ccd_turn__wrap_up", wrap), terms, as_question=True) == ["Q19", "追記 4"], "turn 終わりの箱の recap も見る")
    check(tool_text("Bash", {"command": "accept"}) is None, "対象外の tool は None")
    # 文面
    n = notice(["W-3"], pointer)
    check("W-3" in n and RULE in n and "personal/chat-style.md#x" in n, "注意文に語と正本 2 つ")
    # 変える文の検査 (文は合成)
    def uq(text, extra=""):
        return unshown_change_questions(question_units(text), text + "\n" + extra)
    check(len(uq("要旨の言い方を、 もっと控えめな形に変えますか？")) == 1, "変える文: 区画 + 変えますか、 対なし")
    check(len(uq("1. **題を見直しますか？** 推す案は「A new look at an old problem」 です。")) == 1,
          "変える文: 直した文を 1 つだけ引いた問いも対ではない")
    check(len(uq("2. **序論の最後の段落を残しますか？** 読み手は当たり前だと言っています。")) == 1, "変える文: 残しますか")
    check(len(uq("titleを短くしてもよいですか。 それとも title を変えますか？")) == 1, "変える文: 英語の区画名が日本語に隣っても当たる")
    check(len(uq("結論の段落はおすすめどおりで当ててよいですか")) == 1, "変える文: おすすめどおりで当てて")
    check(len(uq("3 件をおすすめどおり直してもらってよいですか")) == 0, "変える文: 区画の名が問いの行に無い形は見ない (既知の限界)")
    check(uq("要旨をこの案に直しますか？\n- 今: The old sentence stays here.\n- 案: The new sentence goes here.") == [],
          "変える文: 今: と 案: の組があれば通す")
    check(uq("要旨を「the old phrase here」→「the new phrase here」 に直しますか？") == [], "変える文: 「…」→「…」 は通す")
    check(uq("序論の文を次のように変えますか？\n> The new sentence goes here.") == [], "変える文: 行頭の > の引用は通す")
    check(uq("題は「短い題」のままにしますか？ それとも「長いほうの題」に直しますか？") == [], "変える文: のまま / に の 2 案は通す")
    check(uq("1. 副題を組み直す前の版です。 刷り直しますか？") == [], "変える文: 刷り直しは印刷の問い")
    check(uq("- [文面の精査](#local_abc): 要旨・序論の案を原稿に当ててよいか") == [], "変える文: 別の窓の問いの取り次ぎは除く")
    check(uq("別の窓には「要旨をこの案に差し替えてよいですか？」 の問いが残っていますが、 答えはここで出ています。") == [],
          "変える文: 別の窓に残った問いを「」 で引いて報告しただけの行は問いでない")
    check(uq("あちらに「要旨をこの案に差し替えてよいですか？」 が残っているので、 あの窓はまだ畳みません。") == [],
          "変える文: 引いた問いが文の途中にあっても問いでない")
    check(len(uq("「要旨をこの案に差し替えてよいですか？」 という問いに、 どう答えますか？")) == 1,
          "変える文: 引いた問いへの答えをこの返事で問う形は見る")
    check(len(uq("「要旨」 の文を変えますか？")) == 1, "変える文: 区画の名だけを「」 で引いた自分の問いは見る")
    check(not own_question("- 規則の文書を変えた: a.md — 追記 2: 「「終えた」 = 提出を受け取ったか依頼が閉じた、 か」→"
                           "「「終えた」 = 提出を受け取ったか依頼が閉じた、 か」 (既存の文「答えを閉じない」 の隣)"),
          "問いの行: 入れ子の引用の中の問いだけの報告の行は問いでない")
    check(own_question("「A」か「B」か。") and own_question("「「終えた」 の意味」 をどちらに直しますか？"),
          "問いの行: 引用の外の問いは入れ子でも見る")
    check(uq("この問題を直しますか？ 課題の文も変えますか？") == [], "変える文: 問題・課題の「題」 は区画でない")
    check(uq("subtitles の設定を変えますか？") == [], "変える文: 英字に埋まった title は区画でない")
    check(uq("このファイルを残しますか？") == [], "変える文: 区画の名が無い問いは見ない")
    check(uq("要旨は直しました。 結論はそのままです。") == [], "変える文: 問いでない行は見ない")
    check(uq("要旨を変えますか？", "```\nThe new abstract sentence.\n```") == [], "変える文: 箱の側・同じ返事の code block も対")
    wq = {"recap": "要旨の文をまだ当てていません。", "ask": "要旨の言い方を変えますか？", "actions": [{"label": "変える"}]}
    check(len(unshown_change_questions(tool_asks("mcp__ccd_turn__wrap_up", wq), tool_text("mcp__ccd_turn__wrap_up", wq))) == 1,
          "変える文: 箱の ask の欄を見る")
    wr = {"recap": "要旨をおすすめどおり当てて、 直しますか の案も消しました。", "actions": [{"label": "次へ"}]}
    check(tool_asks("mcp__ccd_turn__wrap_up", wr) == [], "変える文: 箱の recap は問いとして見ない")
    s = show_notice(uq("要旨と序論の文を変えますか？"))
    check(SHOW_MARK in s and SHOW_RULE in s and "要旨" in s and "今:" in s, "変える文: 注意文に印・区画・正本・対の形")
    # 本文の行番号 (2026-11-04、 文は合成)
    check(line_refs("序論の L1071 の文と、 l.119 の書き出しを直しました。 `paper.tex:540` も。") == ["L1071", "l.119", ".tex:540"],
          "行番号: L のあと 4 桁・l.N・.tex:N を拾う")
    check(line_refs("L2 ノルムと L1 の評価、 `script.py:42` を直した。 L^2 の空間。") == [],
          "行番号: 1 桁の L (ノルム)・code の file:行・L^2 は拾わない")
    check(line_refs("```\nL540: old\n```\n「L540 と言われても」 は例。") == [], "行番号: code block と「」 の中は見ない")
    # 日本語の形 (2026-11-09 に足した。 文は合成、 形は agent が実際に書いた返事から写した)
    check(line_refs("定義は main.tex の 526 行目にあります。 注の 9〜10 行目も直しました。") == ["526 行目", "9〜10 行目"],
          "行番号: 日本語の N 行目と、 2 桁を含む範囲の行目を拾う")
    check(line_refs("その項目が違います（`notes.tex` の 168 行目あたり）。") == ["168 行目"], "行番号: 引用した file の後の行目")
    check(line_refs("- 494 行の綴りが違います。\n- 488 行: 条件つきで正しい。\n- 第 1 章 517 行の帯と、 付録 A 1126 行の括弧。")
          == ["494 行", "488 行", "517 行", "1126 行"], "行番号: 名詞の「の」・箇条の頭・章と付録の後の単独の N 行")
    check(line_refs("112〜118 行の式と、 (304・306・527 行) を見た。") == ["112〜118 行", "304・306・527 行"], "行番号: 範囲と番号の並び")
    check(line_refs("`tool.py` の 238 行目を直します。") == ["238 行目"], "行番号: code の file でも本文の「の N 行目」 は拾う")
    check(line_refs("公開の層に足す 240 行に漏れはありません。 SESSION.md は 113 行から 34 行に縮まった。 13 行とも表にある。"
                    " 試験の前後で 481 行のまま。 上限 40 行で出す。 返事の 1 行目と表の 1 行目。 STATUS の WP07 行だけ。") == [],
          "行番号: 量・1 行目・英字に続く番号は拾わない")
    check(line_refs("ノートの表 36 行と原稿の印。 見た範囲 = 節の 29 行と engine。 - **止まっている 22 行:** 同じ script。") == [],
          "行番号: 表・節の行の数と、 箇条の頭でないコロンは拾わない (校正で量だった形)")
    check(line_refs("場所は [main.tex の 526 行目](main.tex#L526) と [tool.py:238](tool.py:238)。") == [],
          "行番号: 押せる link の中は見ない")
    ln = line_notice(["L1071"])
    check(LINE_MARK in ln and LINE_RULE in ln and "節の名" in ln, "行番号: 注意文に印・正本・言い直し方")
    # 箱の承認 (2026-11-04、 文は合成)
    def box(ask):
        return box_approval_asks("mcp__ccd_turn__wrap_up", {"recap": "下書きを作った。", "ask": ask})
    check(box("この文面で送ってよいですか？") and box("下の案で直しますか？") and box("推す条件で作りますか？")
          and box("返事の下書きを送りますか？"), "箱の承認: 送信の承認・本文の案・推す条件を指す問い")
    check(not box("どちらを先に直しますか？") and not box("commit しますか？")
          and box_approval_asks("AskUserQuestion", {"questions": [{"question": "この文面で送ってよいですか？"}]}) == [],
          "箱の承認: 文面を指さない問い・選択肢 UI は見ない")
    out = tool_output({"tool_name": "mcp__ccd_turn__wrap_up",
                       "tool_input": {"recap": "下書きを作った。", "ask": "この文面で送ってよいですか？"}}, [], None)
    dec = ((out or {}).get("hookSpecificOutput") or {})
    check(dec.get("permissionDecision") == "deny" and BOX_MARK in dec.get("permissionDecisionReason", "")
          and BOX_RULE in dec.get("permissionDecisionReason", ""), "箱の承認: TOOL_MODE に依らず箱を止める")
    print("--- decision-question-jargon selftest:", "PASS" if ok else "FAIL", "---")
    return 0 if ok else 1


def main(argv) -> int:
    if not argv or argv[0] in ("auto", "-"):
        try:
            inp = json.load(sys.stdin)
        except Exception:
            return 0
        if not isinstance(inp, dict):
            return 0
        try:
            return run_auto(inp)
        except Exception:
            return 0
    if argv[0] == "--selftest":
        return selftest()
    if argv[0] == "calibrate":
        return calibrate(argv[1:])
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
