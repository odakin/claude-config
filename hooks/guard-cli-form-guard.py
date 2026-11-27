#!/usr/bin/env python3
"""guard-cli-form-guard.py — PreToolUse(Bash): 規則保護の guard の承認 CLI を、 宣言済みの allow に当たらない形 (繋いだ形・相対 path) で打つ command を止める (tool-call-robustness.md#classifier-blocks-guard-approval-cli)

なぜ:
  auto mode で guard の承認 CLI (agent-rule-guard.py / manuscript-claim-guard.py) を classifier の判定から外すには、
  settings の allow `Bash(python3 <engine の絶対 path> *)` に当たる形で打つ必要がある。 cd・変数の代入・&& ; | と
  繋いだ形や、 engine を相対 path で書いた形は allow に当たらず classifier に回り、 Self-Modification で止められる
  (実測: allow が入った機械で、 繋いだ形・相対 path の記録が止められ、 単独・絶対 path の形は classifier を通らずに通った)。
  classifier に止められた後に自分で形を直して打ち直すのは「形を変えて試す」 に当たり、 本人の承認が要る。
  ∴ classifier に届く前に、 この hook が形を直させる (hook の停止は classifier の判定より前に起きる)。

止めるもの (python の interpreter の直後に engine が来る呼び出し、 または engine の直接実行に限る):
  1. command に shell の制御演算子 (&& || ; | & 改行) がある (引用の中は見ない)
  2. 先頭の語が `python3` でない (変数の代入・cd・別の interpreter・直接実行)
  3. engine の path が正本の絶対 path (この hook がある repo の scripts/) と一致しない
  engine の path を変数に代入し、 同じ command の中でその変数を interpreter の後か command の頭で使う形
  (`G=<engine>; python3 $G …`) も呼び出しと数える。 interpreter と engine (や変数) の間の option は飛ばして読む
  (`python3 -u <engine>`)。
通すもの:
  - engine を読むだけの command (grep / sed / cat …。 interpreter に渡していない)
  - engine の path を変数に代入するだけの語 (`S=<engine>; sed -n … "$S"`)
  - data と読める heredoc の本文の中の行 = 閉じている・展開が無い (区切りを引用した、 または本文に $( も ` も無い)・
    引用の外の $( )・` `・<( )・>( ) の中でない・本文を受け取る command が data の受け手の list (cat・tee・git など)
    にある・本文の外に pipe が無い・書いた file を同じ command の中で実行しない。 それ以外の本文 (`python3 - <<'EOF'`・
    `bash <<'EOF'`・`ssh host <<'EOF'`・`(cat <<'EOF' …) | sh` など、 code として実行されうる本文) は数える
  - この repo の hooks/ にある engine と同名の守りの hook を `--canary` / `--liveness` だけで起こす command (承認 CLI でない)
  - engine に触れない command
  - 解析できない command (引用が閉じていない等) = fail-open
  heredoc の本文の扱いは「止める → 通す」 の向きにしか答えを変えない (本文の外の一致は今までどおり数える)。

無効化: CLAUDE_GUARD_CLI_FORM_GUARD=0
試験: bash hooks/guard-cli-form-guard.test.sh
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

ENGINES = ("agent-rule-guard.py", "manuscript-claim-guard.py")
INTERPRETER_RE = re.compile(r"^python(\d+(\.\d+)?)?$")
CONTROL = {"&&", "||", ";", "|", "&", ";;", "|&", "\n"}
ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
VAR_RE = re.compile(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$")
# 同名の守りの hook (hooks/) の、 承認 CLI でない起動の option
HOOK_PROBE_FLAGS = {"--canary", "--liveness"}
HOOK_PROBE_VALUE_FLAGS = {"--caller", "--max-age-hours", "--silent-days"}
# heredoc の本文を data として受け取る受け手 (この list の外の受け手の本文は数える = wrapper・shell・interpreter・ssh …)
DATA_CONSUMERS = {
    "cat", "tee", "git", "gh", "pbcopy", "wc", "head", "tail", "sort", "uniq", "tr", "cut", "shasum", "sha256sum",
    "md5", "base64", "diff", "cmp", "jq", "column", "fold", "nl", "iconv",
}
# file を実行する語 (heredoc で書いた file を同じ command の中でこの語に渡すと、 本文は code)
FILE_EXECUTORS = {
    "bash", "sh", "zsh", "dash", "ksh", "fish", "source", ".", "exec", "node", "deno", "bun", "perl", "ruby", "php",
    "osascript", "lua", "Rscript", "julia", "wolframscript", "tclsh",
}
# python の option のうち値をとるもの (interpreter と engine の間を読むとき、 値も飛ばす)
PYTHON_VALUE_FLAGS = {"-W", "-X", "--check-hash-based-pycs"}
WORD_BREAK = set(" \t\n;&|<>()")
DOC = "claude-config/conventions/tool-call-robustness.md#classifier-blocks-guard-approval-cli"


def strip_comments(cmd: str) -> str:
    """shell の comment (語の頭の # から行の終わりまで) を落とす。

    shlex の comment は語の途中の # (`${x#y}`) でも行の残りを捨て、 その後の呼び出しが見えなくなる (実測) ので使わない。
    """
    out: list[str] = []
    i, n = 0, len(cmd)
    quote = None  # "'" / '"' / "$'"
    word_start = True
    while i < n:
        c = cmd[i]
        if quote:
            out.append(c)
            if c == "\\" and quote != "'" and i + 1 < n:
                out.append(cmd[i + 1])
                i += 2
                continue
            if c == quote[-1]:
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(cmd[i:i + 2])
            i += 2
            word_start = False
            continue
        if cmd.startswith("$'", i):
            quote = "$'"
            out.append("$'")
            i += 2
            word_start = False
            continue
        if c in "'\"":
            quote = c
            out.append(c)
            i += 1
            word_start = False
            continue
        if c == "#" and word_start:
            j = cmd.find("\n", i)
            i = n if j < 0 else j
            continue
        out.append(c)
        i += 1
        word_start = c in " \t\n;&|()"
    return "".join(out)


def tokens(command: str) -> list[str] | None:
    lex = shlex.shlex(strip_comments(command), posix=True, punctuation_chars=True)
    lex.whitespace = " \t\r"
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:
        return None


def is_control(tok: str) -> bool:
    return tok in CONTROL or (tok != "" and set(tok) <= set("&|;"))


def is_redirect(tok: str) -> bool:
    return tok != "" and set(tok) <= set("<>&") and ("<" in tok or ">" in tok)


def repo_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def canonical_engine(name: str) -> str:
    return os.path.join(repo_dir(), "scripts", name)


def is_hook_probe(toks: list[str], i: int) -> bool:
    """toks[i] がこの repo の hooks/ の同名の守りの hook で、 --canary / --liveness だけで起こしているか。"""
    name = os.path.basename(toks[i])
    hook = os.path.realpath(os.path.join(repo_dir(), "hooks", name))
    if os.path.realpath(os.path.expanduser(toks[i])) != hook:
        return False
    rest: list[str] = []
    for t in toks[i + 1:]:
        if is_control(t):
            break
        rest.append(t)
    if not set(rest) & HOOK_PROBE_FLAGS:
        return False
    j = 0
    while j < len(rest):
        t = rest[j]
        if t in HOOK_PROBE_FLAGS:
            j += 1
        elif t in HOOK_PROBE_VALUE_FLAGS and j + 1 < len(rest):
            j += 2
        elif is_redirect(t):
            j += 2
        elif t.isdigit() and j + 1 < len(rest) and is_redirect(rest[j + 1]):
            j += 1
        else:
            return False
    return True


def var_ref(toks: list[str], i: int) -> str | None:
    """toks[i] から始まる変数の参照の名前 (引用の中の `$G`・`${G}` は 1 語、 引用の外は shlex が `$` `G` / `$` `{` `G` `}` に切る)。"""
    v = VAR_RE.match(toks[i])
    if v:
        return v.group(1) or v.group(2)
    if toks[i] != "$" or i + 1 >= len(toks):
        return None
    nxt = toks[i + 1]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nxt):
        return nxt
    if nxt == "{" and i + 3 < len(toks) and toks[i + 3] == "}" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", toks[i + 2]):
        return toks[i + 2]
    return None


def invoked_engine(toks: list[str]) -> str | None:
    """engine を実行している呼び出しなら、 その engine の名前を返す (読むだけ・代入するだけなら None)。"""
    assigned: dict[str, str] = {}
    for i, tok in enumerate(toks):
        m = ASSIGN_RE.match(tok)
        if m:
            if os.path.basename(m.group(2)) in ENGINES:
                assigned[m.group(1)] = os.path.basename(m.group(2))
            continue  # 代入の値は実行されない
        ref = var_ref(toks, i)
        if ref is not None:
            name = assigned.get(ref)
            if name is None:
                continue
        else:
            name = os.path.basename(tok)
            if name not in ENGINES or is_hook_probe(toks, i):
                continue
        prev = toks[i - 1] if i > 0 else None
        if prev is None or is_control(prev):
            return name  # 直接実行
        word = prev_word(toks, i)
        if word is not None and INTERPRETER_RE.match(os.path.basename(word)):
            return name  # interpreter の後 (間の option は飛ばす: python3 -u <engine>)
    return None


def prev_word(toks: list[str], i: int) -> str | None:
    """toks[i] の前の、 option (と python の option の値) を飛ばした語。 command の頭まで戻ったら None。"""
    j = i - 1
    while j >= 0:
        t = toks[j]
        if is_control(t):
            return None
        if t.startswith("-") and t != "-":
            j -= 1
            continue
        if j >= 1 and toks[j - 1] in PYTHON_VALUE_FLAGS:
            j -= 2
            continue
        return t
    return None


def heredoc_consumer_is_data(head: str) -> bool:
    """heredoc を持つ単純 command の頭 (演算子 << の前まで) の語 (前置きの代入を除く) が data の受け手の list にあるか。

    list の外 (shell・interpreter・wrapper・ssh・変数の展開・解析できない頭) は data と見ない。
    """
    toks = tokens(head)
    if not toks:
        return False
    words = [t for t in toks if not is_control(t)]
    while words and ASSIGN_RE.match(words[0]):
        words.pop(0)
    if not words:
        return False
    return os.path.basename(words[0]) in DATA_CONSUMERS


def executes_written_file(toks: list[str]) -> bool:
    """同じ command の中で、 redirect (> >> >|) か tee で書いた file を、 実行する語に渡すか直接実行するか。"""
    written: set[str] = set()
    for i, t in enumerate(toks):
        if t in (">", ">>", ">|") and i + 1 < len(toks):
            written.add(os.path.normpath(os.path.expanduser(toks[i + 1])))
        elif os.path.basename(t) == "tee":
            for u in toks[i + 1:]:
                if is_control(u) or is_redirect(u):
                    break
                if not u.startswith("-"):
                    written.add(os.path.normpath(os.path.expanduser(u)))
    if not written:
        return False
    for i, t in enumerate(toks):
        if os.path.normpath(os.path.expanduser(t)) not in written:
            continue
        prev = toks[i - 1] if i > 0 else None
        if prev in (">", ">>", ">|"):
            continue  # 書く側の語
        if prev is None or is_control(prev):
            return True  # 直接実行
        word = prev_word(toks, i)
        if word is not None and (os.path.basename(word) in FILE_EXECUTORS or INTERPRETER_RE.match(os.path.basename(word))):
            return True
    return False


def strip_data_heredocs(cmd: str) -> tuple[str, int] | None:
    """data と読める heredoc の本文を落とした文と、 落とした本文の数を返す。 読めない・閉じていない heredoc があれば None。"""
    out: list[str] = []
    i, n = 0, len(cmd)
    quote = None  # "'" / '"' / "$'"
    pending: list[tuple[str, bool, bool, bool]] = []  # (区切り, <<-, 展開あり, data と読める)
    dropped = 0
    word_start = True
    cmd_start = 0  # 今の単純 command の頭の位置
    subst_depth = 0  # 引用の外の $( の深さ
    in_backtick = False
    while i < n:
        c = cmd[i]
        if quote == "'":
            out.append(c)
            i += 1
            if c == "'":
                quote = None
            continue
        if quote in ('"', "$'"):
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(cmd[i + 1])
                i += 2
                continue
            if (quote == '"' and c == '"') or (quote == "$'" and c == "'"):
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(cmd[i:i + 2])
            i += 2
            word_start = False
            continue
        if cmd.startswith("$'", i):
            quote = "$'"
            out.append("$'")
            i += 2
            word_start = False
            continue
        if c in "'\"":
            quote = c
            out.append(c)
            i += 1
            word_start = False
            continue
        if c == "`":
            in_backtick = not in_backtick
            out.append(c)
            i += 1
            word_start = False
            continue
        if c == "#" and word_start:
            j = cmd.find("\n", i)
            j = n if j < 0 else j
            out.append(cmd[i:j])
            i = j
            continue
        if (cmd.startswith("$(", i) and not cmd.startswith("$((", i)) or cmd[i:i + 2] in ("<(", ">("):
            subst_depth += 1  # command 置換・process 置換 = 外の受け手が分からない
            out.append(cmd[i:i + 2])
            i += 2
            cmd_start = i
            word_start = True
            continue
        if c == ")" and subst_depth:
            subst_depth -= 1
        redirect_amp = c == "&" and (cmd[i - 1:i] in (">", "<") or cmd[i + 1:i + 2] == ">")
        if c in ";&|()" and not pending and not redirect_amp:
            out.append(c)
            i += 1
            cmd_start = i
            word_start = True
            continue
        if cmd.startswith("<<<", i):
            out.append("<<<")
            i += 3
            word_start = True
            continue
        if cmd.startswith("<<", i):
            data_ok = subst_depth == 0 and not in_backtick and heredoc_consumer_is_data(cmd[cmd_start:i])
            out.append("<<")
            i += 2
            strip_tabs = False
            if i < n and cmd[i] == "-":
                strip_tabs = True
                out.append("-")
                i += 1
            while i < n and cmd[i] in " \t":
                out.append(cmd[i])
                i += 1
            j, delim, quoted, q = i, [], False, None
            while j < n:
                d = cmd[j]
                if q:
                    if d == q:
                        q = None
                    else:
                        delim.append(d)
                    j += 1
                    continue
                if d in "'\"":
                    q, quoted = d, True
                    j += 1
                    continue
                if d == "\\" and j + 1 < n:
                    quoted = True
                    delim.append(cmd[j + 1])
                    j += 2
                    continue
                if d in WORD_BREAK:
                    break
                delim.append(d)
                j += 1
            if q or not delim:
                return None
            out.append(cmd[i:j])
            i = j
            pending.append(("".join(delim), strip_tabs, not quoted, data_ok))
            word_start = False
            continue
        if c == "\n" and pending:
            out.append("\n")
            i += 1
            for delim, strip_tabs, expands, data_ok in pending:
                body: list[str] = []
                while True:
                    if i >= n:
                        return None  # 終わりの行が無い
                    j = cmd.find("\n", i)
                    end = n if j < 0 else j
                    line = cmd[i:end]
                    i = end + 1 if j >= 0 else n
                    if (line.lstrip("\t") if strip_tabs else line) == delim:
                        break
                    body.append(line)
                text = "\n".join(body)
                if data_ok and not (expands and ("$(" in text or "`" in text)):
                    dropped += 1
                else:
                    out.append(text + "\n")  # code か展開のある本文 = 数える
                out.append(line + ("\n" if j >= 0 else ""))
            pending = []
            cmd_start = i
            word_start = True
            continue
        out.append(c)
        i += 1
        if c == "\n":
            cmd_start = i
        word_start = c in " \t\n;&|()"
    if pending:
        return None
    return "".join(out), dropped


def only_in_data_heredocs(command: str) -> bool:
    """engine の呼び出しに読める一致が、 data と読める heredoc の本文の中にしか無いか。

    本文の外に pipe があるとき (本文が pipe の先で code になりうる) と、 書いた file を同じ command の中で実行するときは
    data と読まない。
    """
    stripped = strip_data_heredocs(command)
    if stripped is None or stripped[1] == 0:
        return False
    toks = tokens(stripped[0])
    if toks is None or any(t in ("|", "|&") for t in toks) or executes_written_file(toks):
        return False
    return invoked_engine(toks) is None


def problems(toks: list[str], canonical: str) -> list[str]:
    out = []
    if any(is_control(t) for t in toks):
        out.append("他の command と繋いでいる (&& ; | や改行)")
    if not toks or toks[0] != "python3":
        out.append(f"先頭が `python3` でない (先頭 = `{toks[0] if toks else ''}`: 変数の代入・cd・別の interpreter・直接実行)")
    elif len(toks) > 1 and toks[1].startswith("-"):
        out.append(f"python3 と engine の間に option がある (`{toks[1]}`。 allow は `python3 <engine の絶対 path>` で始まる形にだけ当たる)")
    elif len(toks) < 2 or toks[1] != canonical:
        out.append(f"engine が正本の絶対 path でない (`{toks[1] if len(toks) > 1 else ''}`)")
    return out


def main() -> int:
    if os.environ.get("CLAUDE_GUARD_CLI_FORM_GUARD", "1") == "0":
        return 0
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    command = ((data or {}).get("tool_input") or {}).get("command") or ""
    if not any(e in command for e in ENGINES):
        return 0
    toks = tokens(command)
    if not toks:
        return 0
    name = invoked_engine(toks)
    if name is None:
        return 0
    if only_in_data_heredocs(command):
        return 0
    canonical = canonical_engine(name)
    found = problems(toks, canonical)
    if not found:
        return 0
    lines = [
        "[guard-cli-form-guard] 規則保護の guard の承認 CLI は、 単独の 1 command・絶対 path で打つ:",
        f"  python3 {canonical} <引数…>",
        "  (cd・変数の代入・&& ; | と繋がない。 --file / --candidate も絶対 path で書く)",
        "この command の形:",
        *[f"  - {p}" for p in found],
        "繋いだ形・相対 path は宣言済みの allow に当たらず classifier に回り、 Self-Modification で止められる。",
        "この停止は classifier の判定より前なので、 上の形に直して打ち直す。",
    ]
    if any(p.startswith("engine が正本の絶対 path でない") for p in found):
        lines.append("engine の写し (候補・旧版) の起動で止まったときも、 名前を変えた写しで避けない (当てる前の確かめ方 = 下の正本の同じ節)。")
    if "<<" in command.replace("<<<", ""):
        lines.append("heredoc の本文に承認 CLI の行を書いただけなら、 本文は Write tool で file に書く。 本文を python や sh に code として渡しているなら、 その code を file に書いて実行する。")
    lines.append(f"正本 = {DOC}")
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
