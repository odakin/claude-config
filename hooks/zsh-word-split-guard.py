#!/usr/bin/env python3
"""zsh-word-split-guard.py — zsh で未 quote の複数語変数を for / set -- / -- / git の引数・command の位置 (と、 option を含む loop の語を command の引数) に渡す Bash と、 先頭が `=` の未 quote の語 (equals 展開で同じ行の残りが走らない) を含む Bash と、 素の `log show` など (zsh の組み込みの log に取られる) を含む Bash を実行前に止める (conventions/shell-env.md#claude-issued-shell-commands / #equals-word-expansion / #zsh-log-builtin)。

PreToolUse(Bash)。 zsh は未 quote の `$var` を単語分割しない (bash と逆) ので、
    v="a b"; for x in $v      → 1 回だけ回る ("a b")
    set -- $pair              → 引数 1 個
    git commit -- $F          → pathspec 1 個 ("a b c")
    F="python3 x.py --flag"; $F part.m4a → "python3 x.py --flag" という名前の command を探して失敗
が黙って別物を処理する。 規則 (shell-env.md の 1・5) を書いた後も同じ日に 3 回再発したので機械化した
(2026-09-12)。 分割されるのは ${=v}・配列・$(…) を直接書いたとき (2026-09-12 に zsh 5.9 で実測)。

述語 (誤検出を減らすため、 変数が複数語だと同じ command の中で見えるときだけ止める):
  文脈 = `for NAME in … $V …` / `set -- … $V …` / `… -- … $V …` / `git … $V …` / command の位置の `$V …`
         (command の位置は空白入りの文字列・loop 変数のときだけ。 V=$(command -v x) のような 1 語の出力は止めない)
         / 上のどれでもない引数の位置 = loop 変数で、 回す語に option (空白の後の `-`) があり、 command が echo / printf / print でないときだけ
         (`for t in "a.py --selftest" …; do python3 $t` = 分割が目的。 空白入りの file 名を回す loop は zsh の方が正しいので止めない。
          実例と同形: --selftest 付きの 4 本が file 名の誤りで走らず、 loop の末尾の echo が成功に見せた。
          `$(…)` を回す loop は見ない。 較正 (実測) = 30 日分の Bash で発火は 2 件、 2 件とも同じ誤り)
  $V   = 単独の語 (前後が空白・; | & ( ) 等) で quote されていない。 ${=V}・$V[…]・$V/… (path の連結)・
         特殊 param ($1 $@ …)・quote / heredoc の中は見ない
  複数語と分かる = 同じ command 内に
         V="…空白…" / V='…空白…'   (空白を含む文字列)
         V=$(…) / V=`…`             (command の出力 = 改行区切りのまま 1 語)
         for V in "… …" …           (空白入りの quoted 語を回す loop 変数)
  配列代入 V=( … ) が在れば止めない。 代入が見えない (= env 由来) なら止めない。
  command に bash -c / sh -c / bash <<  が居れば (中は bash の意味論) 何もしない。

2 つめの述語 (equals 展開、 shell-env.md#equals-word-expansion): zsh は未 quote の語の先頭の `=` を command の
path に展開し、 見つからないと `not found` で rc=1 になって同じ行の残りの command を走らせない
(`echo ===; B` は B が走らず、 出力には前半だけが出る = 失敗に見えない)。 区切りの見出しで再発を重ねたので機械化した。
  止める = 単独の語の先頭が `=` で、 次の文字がある (`===` / `==X` / `[ a == b ]` の `==` / `=SECTION`)
  見ない = quote / heredoc の中・[[ … ]] と (( … )) の中・語の途中の `=` (a==b / --opt==x)・`=` 1 文字だけ・`=(…)` (process 置換)
  (zsh 5.9 で実測: `echo ===` と `[ a == a ]` は not found で後続が走らない、 [[ ]] と (( )) と a==b と `=` 単独は通る)
  較正 (実測): 既存の会話記録の Bash に当てると、 発火した command のほぼ全部が実際に `not found` で止まっていた
  (誤検出は quote の対応の取り違えによる 1 件)。

3 つめの述語 (zsh の組み込みの log、 shell-env.md#zsh-log-builtin): zsh では素の `log` が組み込み (login の監視用) で、
引数を取らない。 macOS の unified log を読むつもりの `log show …` は `log: too many arguments` で失敗し、 `2>/dev/null` を
付けると黙って空の出力になって「該当する log が無い」 と読み違える (実測)。 規約に書いた後も再発したので機械化した。
  止める = command の位置 (行頭・; & | ( の後・$( と ` の中・do / then / time などの後・`VAR=x ` の代入の後) の `log` の直後に
          macOS の log の subcommand (show / stream / collect / config / stats / erase) がある
  見ない = `/usr/bin/log …` (full path)・`command log …` / `env log …` / `sudo log …` (外の command になる)・quote / heredoc の中・
          `git log`・`catalog show` のような語の一部・subcommand の無い `log`
  直し方は deny の理由に出す (= `/usr/bin/log show …`)。 書き換えて通すことはしない。
  較正 (実測): 30 日分の会話記録の Bash に当てると、 発火した command は全部、 実際に素の `log show` で失敗していた (誤検出 0)。
  `timeout 90 log show …` (外の command を通るので動く) は止めない。 zsh 5.9 で実測 = 止める形は全部 too many arguments、
  通す形 (full path・command・env) は全部 log を出した。

発火: 実行 shell が zsh のとき (CLAUDE_CODE_SHELL か SHELL)。 opt-out = CLAUDE_ZSH_SPLIT_GUARD=0 (=1 で shell 判定を飛ばす、 test 用)。
出力: permissionDecision=deny + 直し方。 誤検出のコストは書き直し 1 回。 fail-open (読めない入力は黙って通す)。
  例外 (2026-10-12 本人の承認): 問題が equals 展開だけで、 その語が全部 `==` で始まるなら (区切りの `======`、 `[ a == b ]`)
  止めずに、 その語を single quote で囲んだ command を updatedInput で返して通す (意味は変わらない = zsh 5.9 と bash で実測)。
  permissionDecision は付けない = 書き換えた command が通常の許可の判定を受ける (allow を付けると判定を飛ばして自動で通す、
  ask を付けると毎回 確認になる = hook-authoring.md 9.2)。 `=X` (= `=cmd` を意図しうる) と、 単語分割の問題は今まで通り止める。
"""
from __future__ import annotations

import json
import os
import re
import sys

NAME = r"[A-Za-z_]\w*"
# 未 quote・単独の語としての参照 (前後に語の一部になる文字が無い)。 ${=V} と $V[..] と $V/.. は当たらない
REF = re.compile(r"(?<![^\s;|&(])\$(?:\{(" + NAME + r")\}|(" + NAME + r"))(?![^\s;|&)])")
QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SEP = re.compile(r";|&&|\|\||\||\n")
LEADING_KW = re.compile(r"^(?:(?:do|then|else|elif|if|while|until|\{|\(|!|time)\s+)+")
BASH_INNER = re.compile(r"\b(?:ba)?sh\s+(?:-\w*c\b|<<)")
SPECIAL = {"argv"}
ECHO_LIKE = {"echo", "printf", "print"}
ARG_CTX = "引数 (loop の語が option を含む)"
# 単独の語の先頭の `=` (次に 1 文字以上、 `=(` は process 置換なので除く)
EQ_WORD = re.compile(r"(?<![^\s;|&])=(?!\()[^\s;|&)]+")
# [[ … ]] と (( … )) の中は equals 展開されない
COND = re.compile(r"\[\[.*?\]\]|\(\(.*?\)\)", re.S)
EQ_FIX = ("直し方: 区切りの見出しは `echo -----` (`-` で始める) か quote (`echo '==='`) / "
          "比較は `[ a = b ]` か `[[ a == b ]]` / `=cmd` (command の path) を意図したなら `$(command -v cmd)`。 "
          "正本 = claude-config/conventions/shell-env.md#equals-word-expansion")

# command の位置の素の `log` + macOS の log の subcommand (zsh では組み込みの log に取られる)
LOG_CMD = re.compile(
    r"(?:^|[;&|(`\n]|\$\()[ \t]*"
    r"(?:(?:do|then|else|elif|if|while|until|\{|!|time)[ \t]+|" + NAME + r"=[^\s;|&]*[ \t]+)*"
    r"log[ \t]+(show|stream|collect|config|stats|erase)\b")
LOG_FIX = ("直し方: `/usr/bin/log show …` と full path で書く (script から呼ぶときも同じ)。 "
           "正本 = claude-config/conventions/shell-env.md#zsh-log-builtin")

FIX = ("直し方: 出力を行ごとに回す → `cmd | while read -r x; do …; done` / 空白で割る → `${=V}` / "
       "複数の path・引数 → 配列 `F=(a b c); git commit -- $F` か literal に並べる / "
       "command と固定の引数をまとめて何度も呼ぶ → 関数 `f() { python3 x.py --flag \"$@\"; }` か配列 `F=(python3 x.py --flag); $F …` / "
       "分割しないのが意図なら \"$V\" と quote して明示する。 "
       "正本 = claude-config/conventions/shell-env.md#claude-issued-shell-commands")


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _masked(cmd: str) -> str:
    """heredoc の本文と quote の中身を同じ長さの空白にする (位置を保ったまま参照の対象から外す)。"""
    return QUOTED.sub(_blank, HEREDOC.sub(_blank, cmd))


def multiword_reason(cmd: str, v: str) -> tuple[str, str] | None:
    """同じ command の中で v が複数語だと分かれば (種類, 根拠)。 分からない・配列なら None。

    種類 "subst" (= $(…) の出力) は 1 行の値 (c=$(git rev-parse HEAD) 等) も多いので、
    分割が目的の文脈 (for / set --) でだけ使う (find_issues 側で絞る。 2026-09-12 の校正で git の引数に 1 件誤検出)。
    """
    b = r"(?<![\w$])" + re.escape(v)
    if re.search(b + r"=\(", cmd):
        return None
    m = re.search(b + r"=(?:\"([^\"]*)\"|'([^']*)')", cmd)
    if m and re.search(r"\s", m.group(1) if m.group(1) is not None else m.group(2)):
        return ("string", f'{v}="… …" (空白を含む文字列)')
    m = re.search(r"\bfor\s+" + re.escape(v) + r"\s+in\s+([^;\n]*)", cmd)
    if m and re.search(r"\"[^\"]*\s[^\"]*\"|'[^']*\s[^']*'", m.group(1)):
        return ("loop", f'for {v} in "… …" (空白入りの語を回す loop 変数)')
    if re.search(b + r"=(?:\$\(|`)", cmd):
        return ("subst", f"{v}=$(…) (command の出力 = 改行を含んだまま 1 語)")
    return None


def _loop_items_have_option(cmd: str, v: str) -> bool:
    """loop の語が quote した literal で、 その 1 つに option (空白の後の `-`) がある = 語を argv に割るのが目的。
    `$(…)` を回す loop は見ない (中の quote の対応を取り違えて誤検出した = 30 日分の Bash で較正)。"""
    m = re.search(r"\bfor\s+" + re.escape(v) + r"\s+in\s+([^;\n]*)", cmd)
    if not m or "$(" in m.group(1) or "`" in m.group(1):
        return False
    return any(re.search(r"\s-", t.group(0)) for t in QUOTED.finditer(m.group(1)))


def _context(before: str) -> str | None:
    b = LEADING_KW.sub("", before.lstrip())
    if not b.strip():
        return "command の位置"
    if re.match(r"for\s+\w+\s+in\s", b):
        return "for … in"
    if re.match(r"set\s+--(?:\s|$)", b):
        return "set --"
    if re.search(r"(?:^|\s)--(?=\s)", b):
        return "--"
    if re.match(r"git\b", b):
        return "git の引数"
    return None


def find_issues(cmd: str) -> list[tuple[str, str, str]]:
    """(変数名, 文脈, 複数語の根拠) の list。 空なら問題なし。"""
    if not cmd or BASH_INNER.search(cmd):
        return []
    masked = _masked(cmd)
    seps = [0] + [m.end() for m in SEP.finditer(masked)]
    out: list[tuple[str, str, str]] = []
    seen = set()
    for m in REF.finditer(masked):
        v = m.group(1) or m.group(2)
        if v in SPECIAL:
            continue
        start = max(s for s in seps if s <= m.start())
        before = masked[start:m.start()]
        ctx = _context(before)
        if not ctx:
            words = LEADING_KW.sub("", before.lstrip()).split()
            if words and words[0] not in ECHO_LIKE and _loop_items_have_option(cmd, v):
                ctx = ARG_CTX
        if not ctx or (v, ctx) in seen:
            continue
        mw = multiword_reason(cmd, v)
        if not mw:
            continue
        kind, why = mw
        if ctx == ARG_CTX and kind != "loop":
            continue
        # command の位置で $(…) を止めないのは、 c=$(command -v python3); $c x.py のような 1 語の値が普通だから
        if kind == "subst" and ctx not in ("for … in", "set --"):
            continue
        seen.add((v, ctx))
        out.append((v, ctx, why))
    return out


def equals_issues(cmd: str) -> list[str]:
    """先頭が `=` の未 quote の語 (zsh の equals 展開に掛かるもの) の list。 空なら問題なし。"""
    if not cmd:
        return []
    masked = COND.sub(_blank, _masked(cmd))
    return sorted({m.group(0) for m in EQ_WORD.finditer(masked)})


def equals_rewrite(cmd: str) -> str | None:
    """`==` で始まる未 quote の語を single quote で囲んだ command (意味は変わらない: echo の区切り `======` は同じ文字列、
    `[ a == b ]` は `[ a '==' b ]` で同じ真偽 = zsh 5.9 と bash で実測)。 書き換えられない語 (`=cmd` を意図しうる `=X`、
    語の中に quote 文字) が 1 つでもあれば None (= 今まで通り止める)。 問題の語が無ければ None。"""
    if not cmd:
        return None
    masked = COND.sub(_blank, _masked(cmd))
    spans = [(m.start(), m.end()) for m in EQ_WORD.finditer(masked)]
    if not spans:
        return None
    out = cmd
    for a, b in reversed(spans):
        word = cmd[a:b]
        if not word.startswith("==") or "'" in word or '"' in word or "\\" in word:
            return None
        out = out[:a] + "'" + word + "'" + out[b:]
    return out if not equals_issues(out) else None


def log_issues(cmd: str) -> list[str]:
    """command の位置で素の `log <subcommand>` を打っている subcommand の list。 空なら問題なし。"""
    if not cmd or BASH_INNER.search(cmd):
        return []
    return sorted({m.group(1) for m in LOG_CMD.finditer(_masked(cmd))})


def log_reason_text(subs: list[str]) -> str:
    items = " / ".join(f"`log {s}`" for s in subs)
    return ("zsh では素の `log` が組み込み (login の監視用) に取られ、 " + items + " は `log: too many arguments` で失敗する "
            "(`2>/dev/null` を付けると黙って空の出力になり、 「該当する log が無い」 と読み違える)。 " + LOG_FIX)


def equals_reason_text(words: list[str]) -> str:
    items = " / ".join(f"`{w}`" for w in words)
    return ("zsh は未 quote の語の先頭の `=` を command の path に展開し、 見つからないと `not found` で止まって "
            "同じ行の残りの command を走らせない (出力には前半だけが出て、 失敗に見えない): " + items + "。 " + EQ_FIX)


def reason_text(issues: list[tuple[str, str, str]]) -> str:
    items = " / ".join(f"`{ctx}` の `${v}` (根拠: {why})" for v, ctx, why in issues)
    return ("zsh は未 quote の変数を単語分割しない (bash と逆) ので、 この command は 1 語として渡して黙って別物を処理する: "
            + items + "。 " + FIX)


def main() -> int:
    flag = os.environ.get("CLAUDE_ZSH_SPLIT_GUARD", "")
    if flag == "0":
        return 0
    shell = os.path.basename(os.environ.get("CLAUDE_CODE_SHELL") or os.environ.get("SHELL") or "")
    if flag != "1" and shell != "zsh":
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    issues = find_issues(cmd)
    eq_words = equals_issues(cmd)
    log_subs = log_issues(cmd)
    if not issues and not eq_words and not log_subs:
        return 0
    fixed = None if (issues or log_subs) else equals_rewrite(cmd)
    if fixed is not None:
        # 止めずに書き換えて通す (2026-10-12 本人「1と2を実装しよう」)。 判断 (permissionDecision) は付けない =
        # 書き換えた command が通常の許可の判定 (allow rule・classifier) を受ける。 付けると判定を飛ばして通すので付けない。
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {**(data.get("tool_input") or {}), "command": fixed},
            "additionalContext": "zsh-word-split-guard: `==` で始まる語を quote して実行した (" + " / ".join(f"`{w}`" for w in eq_words)
                                 + " → 'quote')。 次からは最初から quote するか `-----` で区切る (shell-env.md#equals-word-expansion)",
        }}, ensure_ascii=False))
        return 0
    reasons = (([reason_text(issues)] if issues else []) + ([equals_reason_text(eq_words)] if eq_words else [])
               + ([log_reason_text(log_subs)] if log_subs else []))
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": " / ".join(reasons),
    }}, ensure_ascii=False))
    return 0


def selftest() -> int:
    fails = 0

    def check(cmd: str, want: str | None, label: str) -> None:
        nonlocal fails
        got = find_issues(cmd)
        ctxs = {c for _, c, _ in got}
        ok = (not got) if want is None else (want in ctxs)
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got})"))
        fails += 0 if ok else 1

    # 止める (2026-09-11〜12 の実例と同形)
    check('for pair in "odakin/a 0024b6f" "odakin/b 9ad7630b"; do set -- $pair; cd ~/Claude/$1; done',
          "set --", "loop 変数 (空白入りの語) を set -- で割る")
    check("ids=$(gh run list -q '.[]'); for id in $ids; do gh run watch \"$id\"; done",
          "for … in", "command の出力を変数に溜めて for で回す")
    check('F="a.md b.md"; git commit -q -- $F', "--", "pathspec を文字列 1 つに入れる")
    check('P="x y"; git add $P', "git の引数", "git の引数に文字列を渡す")
    check('v="a b"; for x in ${v}; do echo $x; done', "for … in", "${v} の形")
    check('v="a b"\nif true; then for x in $v; do :; done; fi', "for … in", "then の後の for")
    # 止めない
    check("arr=(a b); for x in $arr; do echo $x; done", None, "配列")
    check('v="a b"; for x in ${=v}; do :; done', None, "${=v}")
    check('v="a b"; for x in "$v"; do :; done', None, "quote 済み")
    check("SP=/tmp/x; for w in $SP/sweep/*-wt $SP/gm-fix; do :; done", None, "path の連結")
    check("F=single.md; git commit -- $F", None, "空白の無い値")
    check("for f in $FILES; do :; done", None, "代入が見えない (env 由来)")
    check("bash -c 'v=\"a b\"; for x in $v; do echo $x; done'", None, "bash -c の中は bash の意味論")
    check('for x in $(printf "a b"); do :; done', None, "$(…) を直接書く (分割される)")
    check("awk '{print $1}' f; set -- $1", None, "特殊 param")
    check("v=\"a b\"; python3 - <<'EOF'\nfor x in $v: pass\nEOF", None, "heredoc の本文")
    check("gh run list -q '.[]' | while read -r id; do gh run watch \"$id\"; done", None, "while read")
    check('msg="a b"; echo $msg', None, "文脈外 (echo)")
    check("c=$(git rev-parse HEAD); git log -1 $c", None, "$(…) の 1 行値を git に渡す (分割目的でない)")
    check("ns=$(git diff --numstat f); set -- $ns", "set --", "$(…) の出力を set -- で割る")
    # command の位置 (2026-10-07 の実例と同形: 背景の連鎖が 5 回とも command not found で、 末尾の echo DONE で成功に見えた)
    check('F="python3 scripts/x.py --with-bgm --force"; $F a.m4a --title t; $F b.m4a', "command の位置",
          "command と引数を文字列 1 つに入れて command として呼ぶ")
    check('R="python3 r.py"; for n in 1 2; do $R $n; done', "command の位置", "do の後の command の位置")
    check("B=(python3 x.py --flag); $B sub", None, "command の位置でも配列は止めない")
    check("P=/usr/bin/python3; $P x.py", None, "command の位置でも空白の無い値は止めない")
    check("c=$(command -v python3); $c x.py", None, "command の位置の $(…) の 1 語の値は止めない")
    check('EDITOR="code -w"; echo ok', None, "代入だけで参照が無い")
    # 引数の位置の loop 変数 (実例と同形: --selftest 付きの 4 本が file 名の誤りで走らなかった)
    check('for t in "a.py --selftest" "b.py --selftest"; do echo "== $t"; python3 $t > out 2>&1; done', ARG_CTX,
          "option を含む語を回す loop 変数を command の引数に渡す")
    check('for f in "My File.txt" "Other File.txt"; do cat $f; done', None, "空白入りの file 名 (zsh の方が正しい)")
    check('for t in "a.py --x" "b.py --y"; do echo $t; done', None, "引数の位置でも echo は止めない")
    check('for t in "a.py --x"; do python3 "$t"; done', None, "quote 済みの引数")
    check("for c in $(git log --since='a b' --format='%h' -- x); do cat $c; done", None,
          "$(…) を回す loop (中の quote の対応で誤検出しない)")

    # equals 展開 (実例と同形: 調査の chain の区切り `echo ===` で後続が走らなかった)
    def eq(cmd: str, want: bool, label: str) -> None:
        nonlocal fails
        got = equals_issues(cmd)
        ok = bool(got) == want
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got})"))
        fails += 0 if ok else 1

    eq("a; echo ===; b", True, "区切りの echo ===")
    eq("ls && echo ====SECTION && ls", True, "見出しの echo ====SECTION")
    eq('[ "$a" == b ] && echo y', True, "[ ] の中の ==")
    eq('echo "x" ==y', True, "語の先頭の ==")
    eq("echo '==='; echo \"=== X ===\"", False, "quote 済み")
    eq('[[ "$a" == b ]] && echo y', False, "[[ ]] の中")
    eq("(( n == 1 )) && echo y; echo $(( 1 == 1 ))", False, "(( )) の中")
    eq("echo a==b; git log --format==%H", False, "語の途中の =")
    eq("echo =; echo -----", False, "= 1 文字と - の区切り")
    eq("diff <(ls) =(ls)", False, "=(…) の process 置換")
    eq("python3 - <<'EOF'\nprint('==')\n==\nEOF", False, "heredoc の本文")
    eq("A= cmd; B=x cmd", False, "代入")

    def rw(cmd: str, want: str | None, label: str) -> None:
        nonlocal fails
        got = equals_rewrite(cmd)
        ok = got == want
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got!r})"))
        fails += 0 if ok else 1

    rw("a; echo ===; b", "a; echo '==='; b", "書き換え: 区切りの echo ===")
    rw('[ "$a" == b ] && echo y', '[ "$a" \'==\' b ] && echo y', "書き換え: [ ] の中の ==")
    rw("ls && echo ====SECTION && echo ======", "ls && echo '====SECTION' && echo '======'", "書き換え: 2 語")
    rw("echo =SECTION", None, "=X (=cmd を意図しうる) は書き換えない = 止める")
    rw("echo ===; echo =python3", None, "1 つでも書き換えられない語があれば全体を止める")
    rw("echo '==='", None, "問題の語が無ければ None")

    # zsh の組み込みの log (実例と同形: `log show … 2>/dev/null` が黙って空を返し、 該当なしと読み違えかけた)
    def lg(cmd: str, want: bool, label: str) -> None:
        nonlocal fails
        got = log_issues(cmd)
        ok = bool(got) == want
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got})"))
        fails += 0 if ok else 1

    lg("log show --last 15m --style compact --predicate 'process == \"x\"' 2>/dev/null | tail", True, "行頭の log show")
    lg("cd /tmp; echo a; log show --last 1h", True, "; の後の log show")
    lg("if true; then log stream --level info; fi", True, "then の後の log stream")
    lg("x=$(log show --last 1m | wc -l)", True, "$( の中の log show")
    lg("TZ=UTC log show --last 1m", True, "代入の後の log show")
    lg("time log collect --last 5m", True, "time の後の log collect")
    lg("/usr/bin/log show --last 1h", False, "full path")
    lg("command log show --last 1h; env log show --last 1h; sudo log stats", False, "command / env / sudo の後")
    lg("echo 'log show'; printf \"%s\" \"log show\"", False, "quote の中")
    lg("git log --oneline; git log show", False, "git log")
    lg("python3 - <<'EOF'\nlog show\nEOF", False, "heredoc の本文")
    lg("catalog show x; changelog stream", False, "語の一部")
    lg("log; log -h", False, "subcommand の無い log")
    lg("bash -c 'log show --last 1m'", False, "bash -c の中は bash の意味論")
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
