#!/usr/bin/env python3
"""zsh-word-split-guard.py — zsh で未 quote の複数語変数を for / set -- / -- / git の引数・command の位置 (と、 option を含む loop の語を command の引数) に渡す Bash と、 先頭が `=` の未 quote の語 (equals 展開で同じ行の残りが走らない) を含む Bash と、 素の `log show` など (zsh の組み込みの log に取られる) を含む Bash と、 波括弧で閉じていない変数の直後の `:` が修飾子に食われる形 (`git show $c:path`) を含む Bash と、 未 quote の glob で zsh が command 自体を走らせない形 (`--include=*.md`) を含む Bash を実行前に止め、 bash の `${PIPESTATUS[N]}` (zsh では空) は zsh の `${pipestatus[N+1]}` に書き換えて通す (conventions/shell-env.md#claude-issued-shell-commands / #equals-word-expansion / #zsh-log-builtin / #zsh-pipestatus-lowercase / #unquoted-glob-nomatch)。

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

4 つめの述語 (bash の PIPESTATUS、 shell-env.md#zsh-pipestatus-lowercase): zsh の pipeline の各段の終了値は `$pipestatus`
(小文字、 添字は 1 始まり) で、 bash の `${PIPESTATUS[0]}` は zsh では空になる。 `echo "exit=${PIPESTATUS[0]}"` は空欄を出し、
`[ "${PIPESTATUS[0]}" -eq 0 ]` のような検査は失敗を通す (実測)。 規約に書いた後も 1 session に 3 回踏んだので機械化した。
  書き換えて通す = `${PIPESTATUS[N]}` (N は数字) → `${pipestatus[N+1]}` / `${PIPESTATUS[@]}`・`[*]` → `${pipestatus[@]}`・`[*]` /
          `${#PIPESTATUS[@]}` → `${#pipestatus[@]}` / `${PIPESTATUS}`・`$PIPESTATUS` (bash では 0 番) → `${pipestatus[1]}`。
          double quote の中も書き換える (展開される場所なので)
  止める = 書き換えの意味が決まらない形: 変数の添字 (`${PIPESTATUS[$i]}`)・`${#PIPESTATUS}` (0 番の文字数)・
          `$PIPESTATUS[0]` (bash では 0 番の後に文字の `[0]` が続く = 意図が読めない)
  見ない = single quote・heredoc の本文・`bash -c` / `bash <<` を含む command (中は bash の意味論)
  較正 (実測): 会話記録の Bash で `${PIPESTATUS[` を使った実行のうち、 bash -c / bash << の中のものは 0 件 = ほぼ全部が zsh で空を見ていた。
  zsh 5.9 で実測 = `false | true; echo ${pipestatus[1]} ${pipestatus[2]}` は `1 0`、 `${PIPESTATUS[0]}` は空。

5 つめの述語 (変数の直後の `:` が修飾子に食われる、 shell-env.md の規則 4): 波括弧で閉じていない `$v` の直後の `:` を、
zsh は履歴修飾子として読む。 `git show $c:scripts/x.py` は `:s` (置換、 区切りは次の 1 文字) と読まれて残りを飲み、
error を出さずに別の対象 (commit 全体の diff 等) を渡す = 後段の grep はそれらしい行数を返す。 規約に書いた後も再発したので機械化した。
  止める = 波括弧なしの `$NAME` の直後が `:` + 修飾子の文字 + その後に word 文字が続く形 (`$c:scripts/x` / `$v:hello` / `$host:admin`)
  修飾子の文字 = a A c e h l P q Q r s t u (zsh 5.9 で実測。 p / f / g / w / x 等は食われない = `$host:port` は安全)
  見ない = `${v}:scripts/x` (波括弧 = 直し方)・`:port` `:8080` `:/abs` `:$b` (修飾子でない文字 = 実測して安全)・
          `$v:h` `$v:h:t` `$v:h/x` (修飾子として意図した形 = 壊れていない)・single quote / heredoc の本文・`bash -c` / `bash <<`
  ⚠️ double quote は効かない (`"$c:src/main.tex"` も食われる = 実測) ので double quote の中も見る。
  書き換えて通すことはしない (修飾子を意図した形と機械で見分けられないので、 波括弧を足すと意味が変わる場合がある)。
  較正 (実測): 30 日分の Bash に当てると、 発火した command はすべて `git show`・`git cat-file` の path を食われた
  本物の事故だった (誤検出 0)。

6 つめの述語 (未 quote の glob と nomatch、 shell-env.md#unquoted-glob-nomatch): zsh は glob が 1 つも一致しないと
**その command を実行しない** (`no matches found`)。 `;` で繋いだ前後の出力だけが残るので「検索したが 0 件」 と見分けがつかない。
⚠️ zsh は**語全体**を pattern にするので、 `--include=*.md` は `.md` の file が在っても一致しない (= 常に走らない。 zsh 5.9 で実測)。
`find . -name *.md` は一致する時に複数の file 名へ展開されて別の error になる (実測)。 この 2 形は cwd に依らず常に壊れる。
  止める = ① option の形の語 (`-` で始まる) に glob の記号がある (`--include=*.md` / `--exclude=*.pyc`)
          ② pattern を取る option の次の語 (-name / -iname / -path / -ipath / -regex / -iregex / --include / --exclude / --include-dir / --exclude-dir)
  見ない = quote 済み・部分 quote した語・heredoc の本文・`[[ … ]]` と `(( … ))` の中・`case … in` を含む command・
          `noglob` / nomatch を外した `setopt`・`$`・バッククォート・`{`・`#`・`^` や位置 0 でない `~` を含む語 (値・zsh 拡張 glob で判定できない)
  **cwd 依存の判定は持たない** (較正で落とした): 「この cwd で一致しないなら走らない」 は正しいが、 hook に渡る cwd と shell の
  実際の cwd は食い違う (Bash tool の cwd は call をまたいで持続する = shell-env.md#cwd-persists-across-calls) ので、
  正しい command を止めてしまう (較正で実測)。 `ls -d ~/dir/*語*` のような path の glob の nomatch は、 この guard の射程外。
  書き換えて通すことはしない (`ls *.py` のような「展開させたい glob」 と見分けられない)。
  較正 (実測): 30 日分の Bash に当てると、 発火はすべて `--include=*.<拡張子>` の未 quote で (= この形は常に走らないので誤検出 0)、
  落とす前の cwd 依存の判定は、 正しい command と部分 quote した語の残りを大量に拾っていた。

発火: 実行 shell が zsh のとき (CLAUDE_CODE_SHELL か SHELL)。 opt-out = CLAUDE_ZSH_SPLIT_GUARD=0 (=1 で shell 判定を飛ばす、 test 用)。
出力: permissionDecision=deny + 直し方。 誤検出のコストは書き直し 1 回。 fail-open (読めない入力は黙って通す)。
  例外 (2026-10-12 本人の承認): 問題が equals 展開だけで、 その語が全部 `==` で始まるなら (区切りの `======`、 `[ a == b ]`)
  止めずに、 その語を single quote で囲んだ command を updatedInput で返して通す (意味は変わらない = zsh 5.9 と bash で実測)。
  permissionDecision は付けない = 書き換えた command が通常の許可の判定を受ける (allow を付けると判定を飛ばして自動で通す、
  ask を付けると毎回 確認になる = hook-authoring.md 9.2)。 `=X` (= `=cmd` を意図しうる) と、 単語分割の問題は今まで通り止める。
  PIPESTATUS の書き換え (4 つめ) も同じ形で返す (`==` の quote と同じ command に両方あれば、 両方を当てて 1 回で返す)。
  止める問題 (単語分割・素の log・書き換えられない PIPESTATUS・書き換えられない `=X`) が 1 つでもあれば書き換えずに止める。
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
# heredoc = (始まりの行: `<<'EOF'` とその行の残り = shell の code) + (本文と終わりの行 = 文字)。 消すのは後者だけ
HEREDOC_BODY = re.compile(r"(<<-?\s*(['\"]?)(\w+)\2[^\n]*)(\n.*?\n[ \t]*\3[ \t]*(?=\n|$))", re.S)
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

# bash の PIPESTATUS (zsh では空) の参照。 ${…} の形と、 添字の無い素の $PIPESTATUS と、 素の $PIPESTATUS[ (意図が読めない形)。
# `\$` で escape した形は展開されない文字 (commit message や echo の説明に書いた語) なので見ない (実測: 当てた直後に、
# 説明に書いた `\${PIPESTATUS[0]}` を書き換えた)。 `\\$` (逃がした backslash の後の本物の $) は区別しない = 見ない側に倒す
PS_BRACE = re.compile(r"(?<!\\)\$\{(#?)PIPESTATUS(?:\[([^\]]*)\])?\}")
PS_BARE = re.compile(r"(?<!\\)\$PIPESTATUS(?![\w\[])")
PS_BARE_SUBSCRIPT = re.compile(r"(?<!\\)\$PIPESTATUS\[[^\]\s]*\]?")
PS_FIX = ("直し方: zsh では `${pipestatus[N+1]}` (小文字、 添字は 1 始まり。 全部は `${pipestatus[@]}`)。 "
          "bash の意味で書くなら `bash -c '…'` の中に。 正本 = claude-config/conventions/shell-env.md#zsh-pipestatus-lowercase")

# 変数の直後の `:` を食う修飾子の文字 (zsh 5.9 で実測。 p / f / g / w / x 等は食われない)
MOD_CHARS = "aAcehlPqQrstu"
# 波括弧なしの $NAME + `:修飾子` の連鎖 + その後に word 文字 (`$v:h` 単独・`$v:h:t`・`$v:h/x` は意図した用法なので当てない)。
# 理由文には食われた語の全体 (`$c:hooks/x.md`) を出す (`$c:h` だけ出すと、 書いた本人には `:h` を書いた覚えが無く読めない)
MOD_REF = re.compile(r"(?<![\w$\\])\$(" + NAME + r")(?::[" + MOD_CHARS + r"])+[A-Za-z0-9_][^\s;|&()<>'\"]*")
MOD_FIX = ("直し方: 波括弧で閉じる (`git show ${c}:scripts/x.py`)。 修飾子を使いたいなら `${v:h}` の形で書く "
           "(double quote で囲んでも食われる)。 "
           "正本 = claude-config/conventions/shell-env.md#claude-issued-shell-commands")

# glob の記号 (`[…]` は閉じている組だけ)
GLOB_META = re.compile(r"\*|\?|\[[^\]]*\]")
# 値が決まらない・zsh 拡張 glob の記号を含む語は判定しない
GLOB_UNSURE = ("$", "`", "{", "#", "^")
# pattern を取る option (値が展開されると別の引数になる = 一致しても壊れる)
PATTERN_OPTS = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex",
                "--include", "--exclude", "--include-dir", "--exclude-dir"}
NOGLOB = re.compile(r"(?:^|[;&|(\n]\s*)noglob\b|\bsetopt\s+[^;\n]*(?:nonomatch|nullglob|csh_null_glob)")
CASE_STMT = re.compile(r"(?:^|[;&|(\n]\s*)case\s+\S+\s+in\b")
SH_WORD = re.compile(r"[^\s;|&()<>]+")
GLOB_FIX = ("直し方: glob を quote する (`--include='*.md'` / `find . -name '*.md'`)。 "
            "正本 = claude-config/conventions/shell-env.md#unquoted-glob-nomatch")


FIX = ("直し方: 出力を行ごとに回す → `cmd | while read -r x; do …; done` / 空白で割る → `${=V}` / "
       "複数の path・引数 → 配列 `F=(a b c); git commit -- $F` か literal に並べる / "
       "command と固定の引数をまとめて何度も呼ぶ → 関数 `f() { python3 x.py --flag \"$@\"; }` か配列 `F=(python3 x.py --flag); $F …` / "
       "分割しないのが意図なら \"$V\" と quote して明示する。 "
       "正本 = claude-config/conventions/shell-env.md#claude-issued-shell-commands")


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _blank_heredoc_bodies(cmd: str) -> str:
    """heredoc の本文と終わりの行を同じ長さの空白にする。 始まりの行の残り (`cmd <<'EOF' 2>&1 | tail; echo ===`) は
    shell の code として残す (始まりの行ごと消すと、 その行の後半の誤りを見逃した = 較正で実測)。"""
    return HEREDOC_BODY.sub(lambda m: m.group(1) + re.sub(r"[^\n]", " ", m.group(4)), cmd)


def _masked(cmd: str) -> str:
    """heredoc の本文と quote の中身を同じ長さの空白にする (位置を保ったまま参照の対象から外す)。"""
    return QUOTED.sub(_blank, _blank_heredoc_bodies(cmd))


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


def _mask_single_and_heredoc(cmd: str) -> str:
    """heredoc の本文と single quote の中身だけを同じ長さの空白にする (double quote の中は展開されるので残す)。
    heredoc の始まりの行の残り (`<<'EOF' 2>&1 | tail; echo ${PIPESTATUS[0]}` の後半) は code として残す (_blank_heredoc_bodies)。"""
    return QUOTED.sub(lambda m: _blank(m) if m.group(0).startswith("'") else m.group(0), _blank_heredoc_bodies(cmd))


def pipestatus_rewrite(cmd: str) -> tuple[str | None, list[str]]:
    """bash の PIPESTATUS の参照を zsh の pipestatus に書き換えた command と、 書き換えの意味が決まらない参照の list。
    書き換えられない参照が 1 つでもあれば (None, その list)。 参照が無い・bash -c / bash << を含むなら (None, [])。"""
    if not cmd or "PIPESTATUS" not in cmd or BASH_INNER.search(cmd):
        return None, []
    masked = _mask_single_and_heredoc(cmd)
    edits, bad = [], []
    for m in PS_BRACE.finditer(masked):
        count, idx = m.group(1), m.group(2)
        if idx is None and not count:
            new = "${pipestatus[1]}"
        elif idx in ("@", "*"):
            new = "${" + count + "pipestatus[" + idx + "]}"
        elif idx is not None and idx.strip().isdigit() and not count:
            new = "${pipestatus[" + str(int(idx) + 1) + "]}"
        else:
            bad.append(cmd[m.start():m.end()])
            continue
        edits.append((m.start(), m.end(), new))
    for m in PS_BARE.finditer(masked):
        edits.append((m.start(), m.end(), "${pipestatus[1]}"))
    bad += [cmd[m.start():m.end()] for m in PS_BARE_SUBSCRIPT.finditer(masked)]
    if bad:
        return None, sorted(set(bad))
    if not edits:
        return None, []
    out = cmd
    for a, b, new in sorted(edits, reverse=True):
        out = out[:a] + new + out[b:]
    return out, []


def pipestatus_reason_text(refs: list[str]) -> str:
    items = " / ".join(f"`{r}`" for r in refs)
    return ("zsh では bash の PIPESTATUS は空で、 この参照は書き換えの意味が決まらない (変数の添字・文字数・`$PIPESTATUS[N]` の形): "
            + items + "。 " + PS_FIX)


def equals_reason_text(words: list[str]) -> str:
    items = " / ".join(f"`{w}`" for w in words)
    return ("zsh は未 quote の語の先頭の `=` を command の path に展開し、 見つからないと `not found` で止まって "
            "同じ行の残りの command を走らせない (出力には前半だけが出て、 失敗に見えない): " + items + "。 " + EQ_FIX)


def modifier_issues(cmd: str) -> list[str]:
    """`$v:<修飾子>…` の形で、 zsh が `:` 以降を修飾子として食う参照の list。 空なら問題なし。

    double quote の中も見る (`"$c:src/main.tex"` も食われる = 実測)。 single quote と heredoc の本文は見ない。
    """
    if not cmd or BASH_INNER.search(cmd):
        return []
    return sorted({m.group(0) for m in MOD_REF.finditer(_mask_single_and_heredoc(cmd))})


def modifier_reason_text(refs: list[str]) -> str:
    items = " / ".join(f"`{r}`" for r in refs)
    return ("zsh は波括弧で閉じていない変数の直後の `:` を履歴修飾子として読むので、 この参照は残りの文字を飲んで "
            "error を出さずに別の対象を渡す: " + items + "。 " + MOD_FIX)


def glob_issues(cmd: str) -> list[tuple[str, str]]:
    """未 quote の glob で zsh が command 自体を走らせない語の (語, 理由) の list。 空なら問題なし。

    cwd に依らず常に壊れる 2 形だけを見る (cwd 依存の判定を持たない理由は module の docstring)。
    """
    if not cmd or BASH_INNER.search(cmd) or NOGLOB.search(cmd) or CASE_STMT.search(cmd):
        return []
    masked = COND.sub(_blank, _masked(cmd))
    # 語の境界は元の command で取り、 masked で消えている語 (quote / heredoc / 条件式の中、 部分 quote) を外す
    words = [(m.group(0), m.start(), m.end()) for m in SH_WORD.finditer(cmd)]
    live = [(w, masked[a:b] == w) for w, a, b in words]
    out: list[tuple[str, str]] = []
    seen = set()
    for i, (w, is_live) in enumerate(live):
        if not is_live or len(w) > 200 or not GLOB_META.search(w):
            continue
        if any(t in w for t in GLOB_UNSURE) or "~" in w[1:]:
            continue
        prev = live[i - 1][0] if i else ""
        if w.startswith("-"):
            why = "option の形の語に glob がある (zsh は語全体を pattern にするので、 一致する file が在っても走らない)"
        elif prev in PATTERN_OPTS:
            why = f"pattern を取る option (`{prev}`) の値 (一致すると複数の file 名へ展開されて別の error になる)"
        else:
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append((w, why))
    return out


def glob_reason_text(words: list[tuple[str, str]]) -> str:
    items = " / ".join(f"`{w}` ({why})" for w, why in words)
    return ("zsh は glob が 1 つも一致しないとその command を実行しない (`no matches found`) ので、 "
            "`;` で繋いだ前後の出力だけが残って「検索したが 0 件」 と見分けがつかない: " + items + "。 " + GLOB_FIX)


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
    ps_fixed, ps_bad = pipestatus_rewrite(cmd)
    mod_refs = modifier_issues(cmd)
    glob_words = glob_issues(cmd)
    if (not issues and not eq_words and not log_subs and ps_fixed is None and not ps_bad
            and not mod_refs and not glob_words):
        return 0
    fixed, notes = None, []
    if not (issues or log_subs or ps_bad or mod_refs or glob_words):
        fixed = ps_fixed or cmd
        if ps_fixed is not None:
            notes.append("bash の `${PIPESTATUS[N]}` を zsh の `${pipestatus[N+1]}` に書き換えて実行した (zsh では PIPESTATUS は空、 "
                         "添字は 1 始まり)。 次からは最初から `${pipestatus[N+1]}` で書く (shell-env.md#zsh-pipestatus-lowercase)")
        if eq_words:
            fixed = equals_rewrite(fixed)
            if fixed is not None:
                notes.append("`==` で始まる語を quote して実行した (" + " / ".join(f"`{w}`" for w in eq_words)
                             + " → 'quote')。 次からは最初から quote するか `-----` で区切る (shell-env.md#equals-word-expansion)")
    if fixed is not None:
        # 止めずに書き換えて通す (2026-10-12 本人「1と2を実装しよう」、 PIPESTATUS は 2026-10-21)。 判断 (permissionDecision) は付けない =
        # 書き換えた command が通常の許可の判定 (allow rule・classifier) を受ける。 付けると判定を飛ばして通すので付けない。
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {**(data.get("tool_input") or {}), "command": fixed},
            "additionalContext": "zsh-word-split-guard: " + " / ".join(notes),
        }}, ensure_ascii=False))
        return 0
    reasons = (([reason_text(issues)] if issues else []) + ([equals_reason_text(eq_words)] if eq_words else [])
               + ([log_reason_text(log_subs)] if log_subs else []) + ([pipestatus_reason_text(ps_bad)] if ps_bad else [])
               + ([modifier_reason_text(mod_refs)] if mod_refs else [])
               + ([glob_reason_text(glob_words)] if glob_words else []))
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
    check("F=\"a b\"; cat <<'EOF' | git add -- $F\nx\nEOF", "--", "heredoc の始まりの行の残りは code として見る")
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
    eq("git commit -F - <<'EOF' 2>&1 | tail -3; echo ===\nmsg\n===\nEOF", True, "heredoc の始まりの行の残りの ===")
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
    lg("cat <<'EOF' > /dev/null; log show --last 1m\nlog stream\nEOF", True, "heredoc の始まりの行の残りの log show")
    lg("catalog show x; changelog stream", False, "語の一部")
    lg("log; log -h", False, "subcommand の無い log")
    lg("bash -c 'log show --last 1m'", False, "bash -c の中は bash の意味論")

    # bash の PIPESTATUS (実例と同形: `cmd | tail; echo "exit=${PIPESTATUS[0]}"` が zsh で空欄を出した)
    def ps(cmd: str, want: str | None, want_bad: bool, label: str) -> None:
        nonlocal fails
        got, bad = pipestatus_rewrite(cmd)
        ok = got == want and bool(bad) == want_bad
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got!r} bad={bad})"))
        fails += 0 if ok else 1

    ps('python3 x.py 2>&1 | tail -3; echo "exit=${PIPESTATUS[0]}"', 'python3 x.py 2>&1 | tail -3; echo "exit=${pipestatus[1]}"',
       False, "double quote の中の ${PIPESTATUS[0]} → ${pipestatus[1]}")
    ps("a | b | c; echo ${PIPESTATUS[2]} ${PIPESTATUS[@]} ${#PIPESTATUS[@]}",
       "a | b | c; echo ${pipestatus[3]} ${pipestatus[@]} ${#pipestatus[@]}", False, "数字・@・# の形")
    ps("a | b; rc=$PIPESTATUS; echo ${PIPESTATUS}", "a | b; rc=${pipestatus[1]}; echo ${pipestatus[1]}", False,
       "添字の無い形 (bash では 0 番)")
    ps('a | b; [ "${PIPESTATUS[0]}" -eq 0 ] && echo ok', 'a | b; [ "${pipestatus[1]}" -eq 0 ] && echo ok', False, "検査の中")
    ps("echo '${PIPESTATUS[0]}'", None, False, "single quote の中は見ない")
    ps("python3 - <<'EOF'\nprint('${PIPESTATUS[0]}')\nEOF", None, False, "heredoc の本文は見ない")
    ps("git commit -F - <<'EOF' 2>&1 | tail; echo \"rc=${PIPESTATUS[0]}\"\nmsg ${PIPESTATUS[0]}\nEOF",
       "git commit -F - <<'EOF' 2>&1 | tail; echo \"rc=${pipestatus[1]}\"\nmsg ${PIPESTATUS[0]}\nEOF", False,
       "heredoc の始まりの行の残りは code として書き換え、 本文は見ない")
    ps("bash -c 'a | b; echo ${PIPESTATUS[0]}'", None, False, "bash -c の中は bash の意味論")
    ps("a | b; echo ${PIPESTATUS[$i]}", None, True, "変数の添字は止める")
    ps("a | b; echo $PIPESTATUS[0]", None, True, "$PIPESTATUS[0] の形は止める")
    ps("a | b; echo ${#PIPESTATUS}", None, True, "${#PIPESTATUS} (0 番の文字数) は止める")
    ps("echo MY_PIPESTATUS ${MY_PIPESTATUS}", None, False, "別の名前の一部は見ない")
    ps('git commit -m "doc: \\${PIPESTATUS[0]} は空"', None, False, "\\ で escape した $ は文字 = 書き換えない")
    ps('echo "\\${PIPESTATUS[N]} \\$PIPESTATUS[0]"', None, False, "escape した形は止めもしない")
    ps('a | b; echo "\\${PIPESTATUS[0]}=${PIPESTATUS[0]}"', 'a | b; echo "\\${PIPESTATUS[0]}=${pipestatus[1]}"', False,
       "同じ行の escape した形は残し、 本物の参照だけを書き換える")

    # 変数の直後の `:` (実例と同形: `git show $c:scripts/x.py` が commit 全体の diff を渡した)
    def md(cmd: str, want: bool, label: str) -> None:
        nonlocal fails
        got = modifier_issues(cmd)
        ok = bool(got) == want
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got})"))
        fails += 0 if ok else 1

    md("for c in a b; do git show $c:scripts/x.py | grep -c y; done", True, "実例: $c:scripts/… (:s に食われる)")
    got_full = modifier_issues("git show $c:hooks/README.md | head -1")
    ok_full = got_full == ["$c:hooks/README.md"]
    print(("  ok   " if ok_full else "  FAIL ") + "理由に出す語は食われた語の全体" + ("" if ok_full else f"  (got {got_full})"))
    fails += 0 if ok_full else 1
    md('git show "$r:src/main.tex"', True, "double quote でも食われる (実測)")
    md("git cat-file --filters $base:todo/x.yaml", True, "$base:todo/… (:t に食われる)")
    md("git show $P:Paper-X/draft.tex", True, "$P:Paper-… (:P に食われる)")
    md("echo $v:hello", True, "$v:hello (:h に食われて ello が残る)")
    md('git show "${c}:scripts/x"', False, "波括弧で閉じた形 (直し方)")
    md("curl $host:port; curl $host:8080", False, "修飾子でない文字 (実測して安全)")
    md('echo "$v:/abs/path"; echo "$a:$b"', False, ": の次が / と $")
    md("print -r -- $v:h; print -r -- $v:h:t; print -r -- $v:h/x", False, "修飾子として意図した形は止めない")
    md("echo '$c:scripts/x'", False, "single quote の中")
    md("python3 - <<'EOF'\nprint('$c:scripts/x')\nEOF", False, "heredoc の本文")
    md("bash -c 'git show $c:scripts/x'", False, "bash -c の中は bash の意味論")

    # 未 quote の glob (実例と同形: `--include=*.md` を付けた grep が走らず、 前後の出力だけが残った)
    def gl(cmd: str, want: bool, label: str) -> None:
        nonlocal fails
        got = glob_issues(cmd)
        ok = bool(got) == want
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got})"))
        fails += 0 if ok else 1

    gl("grep -rn --include=*.md pat .", True, "option の形の語の glob (一致する .md が在っても走らない)")
    gl("rsync -a src/ dst/ --exclude=*.pyc", True, "--exclude=*.pyc")
    gl("find . -name *.md", True, "pattern を取る option の値 (一致すると別の引数に展開される)")
    gl("find . -iname *.TeX -o -path */build/*", True, "-iname と -path の値")
    gl("grep -rn --include='*.md' pat .", False, "quote 済みの option の値")
    gl("find . -name '*.md'", False, "quote 済みの pattern")
    gl("ls -d *.md; wc -l paper.tex appendix-*.tex", False, "path の glob は射程外 (cwd 依存の判定を持たない)")
    gl('ls -d "$B"/*/Extensions/x', False, "部分 quote した語の残りを拾わない (較正で実測した誤検出)")
    gl("ls -d $HOME/*.md", False, "$ を含む語は判定しない")
    gl("noglob grep -rn --include=*.md pat .", False, "noglob を前置した形")
    gl("[[ $f == *.md ]] && echo y", False, "[[ ]] の中の pattern")
    gl("case $f in *.md) echo y ;; esac", False, "case の pattern")
    gl("python3 - <<'EOF'\nglob.glob('--include=*.md')\nEOF", False, "heredoc の本文")
    gl("bash -c 'grep -rn --include=*.md pat .'", False, "bash -c の中は bash の意味論")
    gl("git commit -m 'fix --include=*.md handling'", False, "quote の中の glob の記号")
    gl("git log --format=%h; tar -xzf a.tgz --strip-components=1", False, "glob の記号が無い option")
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
