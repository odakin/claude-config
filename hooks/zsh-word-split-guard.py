#!/usr/bin/env python3
"""zsh-word-split-guard.py — zsh で未 quote の複数語変数を for / set -- / -- / git の引数に渡す Bash を実行前に止める (conventions/shell-env.md#claude-issued-shell-commands)。

PreToolUse(Bash)。 zsh は未 quote の `$var` を単語分割しない (bash と逆) ので、
    v="a b"; for x in $v      → 1 回だけ回る ("a b")
    set -- $pair              → 引数 1 個
    git commit -- $F          → pathspec 1 個 ("a b c")
が黙って別物を処理する。 規則 (shell-env.md の 1・5) を書いた後も同じ日に 3 回再発したので機械化した
(2026-09-12)。 分割されるのは ${=v}・配列・$(…) を直接書いたとき (2026-09-12 に zsh 5.9 で実測)。

述語 (誤検出を減らすため、 変数が複数語だと同じ command の中で見えるときだけ止める):
  文脈 = `for NAME in … $V …` / `set -- … $V …` / `… -- … $V …` / `git … $V …`
  $V   = 単独の語 (前後が空白・; | & ( ) 等) で quote されていない。 ${=V}・$V[…]・$V/… (path の連結)・
         特殊 param ($1 $@ …)・quote / heredoc の中は見ない
  複数語と分かる = 同じ command 内に
         V="…空白…" / V='…空白…'   (空白を含む文字列)
         V=$(…) / V=`…`             (command の出力 = 改行区切りのまま 1 語)
         for V in "… …" …           (空白入りの quoted 語を回す loop 変数)
  配列代入 V=( … ) が在れば止めない。 代入が見えない (= env 由来) なら止めない。
  command に bash -c / sh -c / bash <<  が居れば (中は bash の意味論) 何もしない。

発火: 実行 shell が zsh のとき (CLAUDE_CODE_SHELL か SHELL)。 opt-out = CLAUDE_ZSH_SPLIT_GUARD=0 (=1 で shell 判定を飛ばす、 test 用)。
出力: permissionDecision=deny + 直し方。 誤検出のコストは書き直し 1 回。 fail-open (読めない入力は黙って通す)。
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

FIX = ("直し方: 出力を行ごとに回す → `cmd | while read -r x; do …; done` / 空白で割る → `${=V}` / "
       "複数の path・引数 → 配列 `F=(a b c); git commit -- $F` か literal に並べる / "
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


def _context(before: str) -> str | None:
    b = LEADING_KW.sub("", before.lstrip())
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
        ctx = _context(masked[start:m.start()])
        if not ctx or (v, ctx) in seen:
            continue
        mw = multiword_reason(cmd, v)
        if not mw:
            continue
        kind, why = mw
        if kind == "subst" and ctx not in ("for … in", "set --"):
            continue
        seen.add((v, ctx))
        out.append((v, ctx, why))
    return out


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
    if not issues:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason_text(issues),
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
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
