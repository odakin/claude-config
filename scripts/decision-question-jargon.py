#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decision-question-jargon.py — 本人への問い (最終の返事の問いの行・選択肢 UI・turn 終わりの箱) に作業側の語 (掲示板の動詞・台帳の符号・event id・内輪の略語) が入っていたら 1 回だけ注意する engine (hook = hooks/decision-question-jargon-nudge.sh、 語 = hooks/decision-question-jargon-terms.txt + ~/.claude/decision-question-jargon-ext.txt、 校正 = `calibrate --since`、 --selftest。 conventions/concise-output.md#decision-questions)

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
  Stop        {"decision":"block","reason":…} を 1 回だけ (stop_hook_active = true なら沈黙)。 reason は「問いの部分だけを短い追記で
              書き直す」 を求め、 返事の全文の出し直しは求めない。 (Stop で model に届く経路は block しか無い = 「注意」 の実装は 1 回の block)
  PreToolUse  既定 = additionalContext (止めない。 ⚠️ 選択肢 UI と箱は本人に先に出るので、 注意が効くのは次の問いから)。
              env DECISION_QUESTION_JARGON_TOOL_MODE=deny なら permissionDecision=deny + reason (本人が見る前に書き直させる)。
  故障 (入力不正・transcript 不在・部品の import 失敗・語の一覧が無い) は沈黙 (exit 0)。

校正 (導入前と、 語を変えるたび): `decision-question-jargon.py calibrate --since YYYY-MM-DD [--show] [--terms F] [--ext F]`
  = この機械の全部の設定フォルダの transcript (lib/claude_config_dirs.py) の各 turn の最終発話・AskUserQuestion・wrap_up に
  本番と同じ述語を当て、 問いの turn の数・鳴った数・語ごとの数を出す。 ⚠️ transcript は private data、 --show の抜粋を公開の場所に貼らない。
  導入前の校正 (直近 2 週、 問いを含む turn ≈ 640 + 選択肢 UI 13 + 箱 217): 採った語と落とした語の理由は hooks/decision-question-jargon-terms.txt
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


def question_units(text: str) -> list:
    """問いの行 + その行より字下げの深い続きの行 (空行か同じ以下の字下げで止まる)。"""
    lines = (text or "").split("\n")
    units, i = [], 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if s and Q_RE.search(s):
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


# ── hook の 3 つの面 ──────────────────────────────────────────

def stop_reason(inp: dict, terms, pointer):
    if inp.get("stop_hook_active"):
        return None
    path = inp.get("transcript_path")
    if not path or not os.path.isfile(path):
        return None
    try:
        from transcript_turns import current_turn_final, load_entries
        final, _ = current_turn_final(load_entries(path))
    except Exception:
        return None
    if not final:
        return None
    words = find_jargon(final, terms)
    if not words:
        return None
    return (notice(words, pointer) + "。 前の返事は本人の画面に出ているので本文は出し直さず、 問いの部分だけを普通の語で"
            "短い追記に書く (符号を残すなら、 何の話かの説明を直後に添える)。 どの語にも説明が既に添えてあるなら、 その旨の 1 行で終了してよい。")


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


def tool_output(inp: dict, terms, pointer):
    text = tool_text(inp.get("tool_name", ""), inp.get("tool_input"))
    if not text:
        return None
    words = find_jargon(text, terms, as_question=True)
    if not words:
        return None
    mode = os.environ.get("DECISION_QUESTION_JARGON_TOOL_MODE", "notice")
    if mode == "deny":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": notice(words, pointer) + "。 問いと選択肢を普通の語で書き直してから、 もう一度呼ぶ。"}}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "additionalContext": notice(words, pointer) + "。 この問いはそのまま本人に出ます。 答えが返ったら、 次に問う文は普通の語で書く。"}}


def run_auto(inp: dict) -> int:
    if os.environ.get("DECISION_QUESTION_JARGON_DISABLE") == "1":
        return 0
    terms, pointer = all_terms()
    if not terms:
        return 0
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

    counts = {"stop": [0, 0], "ask": [0, 0], "wrap": [0, 0]}
    per_term = {}
    shown = []
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
            if final and question_units(final):
                counts["stop"][0] += 1
                words = find_jargon(final, terms)
                if words:
                    counts["stop"][1] += 1
                    for w in words:
                        per_term[w] = per_term.get(w, 0) + 1
                    shown.append(("stop", sid, ts, words, question_units(final)))
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
    print(f"terms={len(terms)} pointer={pointer or '-'} files={len(files)} since={a.since}")
    for k, lab in (("stop", "問いを含む turn (Stop)"), ("ask", "AskUserQuestion"), ("wrap", "turn 終わりの箱 (wrap_up)")):
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
