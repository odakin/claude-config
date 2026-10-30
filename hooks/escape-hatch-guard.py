#!/usr/bin/env python3
"""escape-hatch-guard.py — PreToolUse(Bash): commit gate を外す操作 (CLAUDE_*_GUARD=0 / git の --no-verify・commit -n / core.hooksPath の差し替え) を、 本人がこの session で明示に指示し承認として記録していない限り deny

# agent-authority:file

なぜ:
  commit gate の多くは「誤検出で急ぐとき」 の escape hatch (env `CLAUDE_<名前>_GUARD=0`) を持ち、 止めた時の
  表示にもその書き方が出る。 agent は手元の例を真似る = 1 度 escape hatch で通した例があると、 次の session は
  それを普通の手順として写す (gate が少しずつ緩む)。 本人の裁定 (2026-09-29): escape hatch は本人の明示の指示が
  あるときだけ使う。 一般的な依頼 (「直して」「commit して」) は gate を外す指示ではない。

止めるもの (command の実行位置に書かれたものだけ。 echo・grep の引数、 commit message、 heredoc の本文は data):
  1. `CLAUDE_*_GUARD` に止める値 (0 / no / off / false、 または `$`・backtick を含む計算値) を入れる代入。
     command の前置 (`X=0 git commit`)・単独の代入文・`export` / `declare -x` / `typeset -x` / `local` / `readonly`・
     `env` / `sudo` 等の wrapper の後・`launchctl setenv`。 名前は形で当てる = 新しい gate を足しても本 hook は直さない。
     2026-09-29 時点で commit の経路が読むもの (runner を grep): DEGENERATE_TEXT / UNBRACED_MB_VAR / SESSION_SHAPE /
     SESSION_CRYPT / UNPUBLISHED / LEAK / ACTIVITY_FACTS / MD_LINKS / MEMORY_BUDGET / TODO_ENUM / STUDENT_ID。
     hook 自身の env で読む opt-out (ZSH_SPLIT / OFFICE_INPLACE) と Office の guard (OFFICE_APP) も同じ形なので当たる。
  2. git の hook を省く: commit / push / merge / am の `--no-verify` (git が受ける省略形 `--no-verif` 等を含む)、 commit の `-n`
     (flag の解釈は agent-rule-guard と共有。 省略形はこちらで正規の形に直してから渡す)。
  3. hook の置き場の差し替え: commit 系の git (下の 4 の一覧) への `git -c core.hooksPath=…` / `git config … core.hooksPath`
     の書き換え・削除 (読むだけの --get 等は通す。 持続する設定なので subcommand を問わない) /
     `GIT_CONFIG_PARAMETERS`・`GIT_CONFIG_KEY_<n>` で core.hooksPath を差し込む。
  4. gate の設定・承認の置き場を env で差し替えて同じ command で commit する: `CLAUDE_STUDENT_IDENTITY` /
     `CLAUDE_PII_FILENAME_PATTERNS` / `MANUSCRIPT_CLAIM_GUARD_STATE_DIR` / `HOME` の代入と、 commit 系の git
     (commit / push / merge / am / pull / rebase / cherry-pick / revert) が同じ command にあるとき。 前置の代入は
     その command 自身が commit 系のときだけ、 単独の代入文・export は同じ command のどこかに commit 系があるとき。
  中まで見る: `bash|sh|zsh|dash|ksh -c '…'` / `eval '…'` / `env -S '…'` / `$(…)` と backtick の中 / `xargs` の後の command /
  `{ …; }`・`if … then`・`for … do` の中。

通すもの (本人の指示の記録):
  本人が明示に指示した発言を、 agent-rule-guard の承認台帳 (manuscript-claim-guard と同じ、 session ごとの jsonl) に記録した
  とき。 条件 = 同じ session の記録 ∧ 領域 `section:guard-escape` ∧ 対象 file 名がこの hook ∧ 本人の発言と記録の時刻が
  30 分以内 ∧ `--change` に省く対象の名前 (env の名前 / `--no-verify` / `core.hooksPath`) を含む。 記録の command は
  deny の文面に出す。 記録は `--latest` か `--quote` で本人の発言に照合され、 Stop が最後の返事にその行を書かせる
  (= 本人の目に入る)。 ⚠️ 2 と `git -c core.hooksPath` は manuscript-claim-guard も承認に依らず止める
  (conventions/agent-rule-ownership.md#mechanism) = ここで記録してもそちらは通らない。

射程外 (既知の穴): 変数に入れた command・変数で組んだ env の名前 (`export $g=0`)・script file の中・python の subprocess・git の alias 経由 (`-c alias.x=commit` を含む)・`.git/hooks` の file を消す/書き換える shell
  操作・shell の rc file への書き込み・`GIT_CONFIG_GLOBAL` 等で core.hooksPath を書いた設定 file を読ませる経路・
  台帳への shell からの直接の追記 (承認の偽造)。

校正 (手元の transcript の Bash に当てた): 当たりは本物の repo で gate を外したもの (push --no-verify・
  DEGENERATE_TEXT_GUARD=0 の commit) と、 試験用の使い捨て repo の中のもの = --no-verify / commit への -c core.hooksPath
  (この 2 つは manuscript-claim-guard も止めている) と、 本 hook で新しく止まる `git config core.hooksPath`・gate の
  試験で env を差し替えた commit。 大半は使い捨て repo の中。 使い捨て repo には hook が入って
  いない (git init / clone は hook を写さない) = 外す必要が無いので、 deny の文面でそう伝える。
  `GIT_CONFIG_GLOBAL=/dev/null` (試験の定番、 この機械の global には core.hooksPath が無い) と worktree add / checkout への
  `-c core.hooksPath` は gate を外さないので当てない (当てると使い捨て repo の当たりが増えるだけ)。

失敗の扱い: 解析の部品 (scripts/agent-rule-guard.py) を読めない・hook の内部例外 = fail-open (その command は検査して
  いないことを 1 行出して通す)。 止める対象を見つけた後に承認台帳を読めない = deny (指示の有無を確かめられない)。

`--selftest` = 述語の回帰 (承認なしの判定)。 承認を含む end-to-end = hooks/escape-hatch-guard.test.sh。
校正 = scripts/calibrate-bash-command-pattern.py --hook hooks/escape-hatch-guard.py (find_issues を当てる)。
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
SCRIPTS = HERE.parent / "scripts"
if not (SCRIPTS / "agent-rule-guard.py").is_file():  # hook を copy で置く機械 (Windows) = 正規の置き場の repo を読む
    SCRIPTS = Path.home() / "Claude" / "claude-config" / "scripts"
RULE_GUARD = SCRIPTS / "agent-rule-guard.py"
DISPATCHER = SCRIPTS / "manuscript-claim-guard.py"
HOOK_NAME = "escape-hatch-guard.py"
REGION = "section:guard-escape"
WINDOW = _dt.timedelta(minutes=30)
SKEW = _dt.timedelta(minutes=5)
SOT = "conventions/agent-rule-ownership.md#mechanism"

FALSY = {"0", "no", "off", "false"}
GUARD_VAR = re.compile(r"^CLAUDE_[A-Z0-9_]*_GUARD$")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\+?=(.*)$", re.S)
GIT_KEY_VAR = re.compile(r"^GIT_CONFIG_KEY_[0-9]+$")
REDIRECT_VARS = ("CLAUDE_STUDENT_IDENTITY", "CLAUDE_PII_FILENAME_PATTERNS", "MANUSCRIPT_CLAIM_GUARD_STATE_DIR", "HOME")
GIT_HOOK_OPS = {"commit", "push", "merge", "am"}           # --no-verify を持ち、 agent-rule-guard が flag を読む
GIT_COMMITISH = GIT_HOOK_OPS | {"pull", "rebase", "cherry-pick", "revert"}
RESERVED = {"{", "}", "!", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "coproc",
            "noglob", "nocorrect"}
DECLARE = {"export", "declare", "typeset", "local", "readonly"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# wrapper → 値を取る option。 wrapper の後にも代入・command が続く (env / sudo は代入を受ける)
WRAPPERS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-P"},
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"},
    "doas": {"-u", "-C"},
    "command": set(), "builtin": set(), "exec": {"-a"}, "nohup": set(), "nice": {"-n"}, "time": set(),
    "timeout": {"-s", "-k", "--signal", "--kill-after"}, "gtimeout": {"-s", "-k", "--signal", "--kill-after"},
    "caffeinate": {"-t", "-w"}, "stdbuf": {"-i", "-o", "-e"}, "arch": set(), "chronic": set(), "unbuffer": set(),
    "xargs": {"-I", "-i", "-n", "-L", "-l", "-P", "-s", "-E", "-e", "-d", "-a", "-J", "-R", "-S"},
}
PREFILTER = re.compile(r"_GUARD|no-verify|hookspath|GIT_CONFIG|\bgit\b|HOME\s*=|CLAUDE_STUDENT_IDENTITY|"
                       r"CLAUDE_PII_FILENAME_PATTERNS|MANUSCRIPT_CLAIM_GUARD_STATE_DIR", re.I)

_RG = None


class EngineUnavailable(Exception):
    pass


def rule_guard():
    """shell の分解と git の flag の解釈は agent-rule-guard と共有する (同じ command を 2 つの guard が別々に読まない)。"""
    global _RG
    if _RG is None:
        path = Path(os.environ.get("ESCAPE_HATCH_GUARD_RULE_ENGINE") or RULE_GUARD)
        if not path.is_file():
            raise EngineUnavailable(str(path))
        spec = importlib.util.spec_from_file_location("agent_rule_guard_for_escape", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _RG = mod
    return _RG


# ---------------------------------------------------------------- 検出

class Finding:
    __slots__ = ("key", "label")

    def __init__(self, key: str, label: str):
        self.key, self.label = key, label

    def __eq__(self, other):
        return isinstance(other, Finding) and (self.key, self.label) == (other.key, other.label)

    def __hash__(self):
        return hash((self.key, self.label))


def _disabling(value: str) -> bool:
    v = value.strip()
    return v.lower() in FALSY or "$" in v or "`" in v


def _assignment(word: str):
    m = ASSIGN.match(word)
    return (m.group(1), m.group(2)) if m else None


class _Scan:
    """command 1 つの走査の状態。 設定の差し替え (REDIRECT_VARS) は、 前置の代入ならその command 自身 (中の bash -c 等を
    含む) が commit 系の git のときだけ、 持続する代入 (単独の代入文・export 等) なら同じ command のどこかに commit 系の
    git があるときだけ当てる (= 試験で一覧を差し替えて engine を直接走らせるのは通す)。"""

    def __init__(self):
        self.found: list[Finding] = []
        self.persistent_redirects: list[str] = []
        self.git_ops: list[str] = []

    def assignment(self, name: str, value: str) -> str | None:
        """止める代入なら found に足す。 設定の差し替えなら名前を返す (当てるかは呼び元が git の有無で決める)。"""
        if GUARD_VAR.match(name) and _disabling(value):
            self.found.append(Finding(name, f"{name}={value} (gate の escape hatch)"))
        elif name == "GIT_CONFIG_PARAMETERS" and "core.hookspath" in value.lower():
            self.found.append(Finding("core.hooksPath", "GIT_CONFIG_PARAMETERS で core.hooksPath を差し込む"))
        elif GIT_KEY_VAR.match(name) and value.strip().lower() == "core.hookspath":
            self.found.append(Finding("core.hooksPath", f"{name}=core.hooksPath で hook の置き場を差し込む"))
        elif name in REDIRECT_VARS:
            return name
        return None

    def redirect(self, name: str, op: str) -> None:
        self.found.append(Finding(name, f"{name}=… と git {op} を同じ command で (gate の設定・承認の置き場の差し替え)"))


QUOTED_HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"])([^'\"\n]+)\2")


def strip_quoted_heredocs(command: str) -> str:
    """quote した区切りの heredoc の本文を外す (本文は literal = 置換も起きない)。 近似: 演算子の位置の quote 状態は見ない。"""
    out, pos = [], 0
    for m in QUOTED_HEREDOC.finditer(command):
        if m.start() < pos:
            continue
        nl = command.find("\n", m.end())
        if nl < 0:
            break
        out.append(command[pos:nl + 1])
        strip_tabs, delim = m.group(1) == "-", m.group(3)
        i = nl + 1
        while i < len(command):
            end = command.find("\n", i)
            end = len(command) if end < 0 else end
            line = command[i:end]
            i = end + 1
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                out.append(line + "\n")
                break
        pos = i
    out.append(command[pos:])
    return "".join(out)


def command_substitutions(command: str) -> list[str]:
    """`$(…)` と backtick の中身 (single quote の外。 double quote の中も含む = shell が展開する所)。"""
    command = strip_quoted_heredocs(command)
    out: list[str] = []
    i, n, single = 0, len(command), False
    while i < n:
        ch = command[i]
        if single:
            if ch == "'":
                single = False
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "'":
            single = True
            i += 1
        elif command.startswith("$(", i) and not command.startswith("$((", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if command[j] == "(":
                    depth += 1
                elif command[j] == ")":
                    depth -= 1
                j += 1
            out.append(command[i + 2:j - 1] if depth == 0 else command[i + 2:])
            i = j
        elif ch == "`":
            j = command.find("`", i + 1)
            out.append(command[i + 1:] if j < 0 else command[i + 1:j])
            i = n if j < 0 else j + 1
        else:
            i += 1
    return out


def _strip_prefix(scan: _Scan, words: list[str], redirects: list[str]) -> list[str]:
    """先頭の予約語・代入・wrapper を外して実行される argv を返す。 代入は scan で判定し、 設定の差し替えは redirects へ。"""
    args = list(words)
    while args:
        w = args[0]
        if w in RESERVED:
            args.pop(0)
            continue
        a = _assignment(w)
        if a:
            r = scan.assignment(*a)
            if r:
                redirects.append(r)
            args.pop(0)
            continue
        name = Path(w).name
        if name in WRAPPERS:
            args.pop(0)
            takes = WRAPPERS[name]
            positional_left = 1 if name in ("timeout", "gtimeout") else 0
            while args:
                o = args[0]
                if o == "--":
                    args.pop(0)
                    break
                if name == "env" and (o in ("-S", "--split-string") or o.startswith("--split-string=")):
                    args.pop(0)
                    text = o.partition("=")[2] if o.startswith("--split-string=") else (args.pop(0) if args else "")
                    _scan_command(scan, text + " " + " ".join(_quote(x) for x in args), 1)
                    return []
                if o.startswith("-") and o != "-":
                    args.pop(0)
                    if o in takes and args:
                        args.pop(0)
                    if name == "command" and o in ("-v", "-V"):
                        return []
                    continue
                if positional_left:
                    positional_left -= 1
                    args.pop(0)
                    continue
                break
            continue
        break
    return args


def _quote(word: str) -> str:
    return "'" + word.replace("'", "'\"'\"'") + "'"


def _shell_script(args: list[str]):
    if not args or Path(args[0]).name not in SHELLS:
        return None
    for i, arg in enumerate(args[1:-1], 1):
        if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
            return args[i + 1]
    return None


def _git_config_hookspath_write(args: list[str]) -> bool:
    value_opts = {"-f", "--file", "--blob", "--type", "--default", "--comment", "--value", "-t"}
    read_ops = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list", "--get-color",
                "--get-colorbool", "get", "list"}
    write_ops = {"--unset", "--unset-all", "--replace-all", "--add", "--rename-section", "--remove-section",
                 "set", "unset", "rename-section", "remove-section"}
    positional: list[str] = []
    read = write = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in value_opts:
            i += 2
            continue
        if a.startswith("--") and a.partition("=")[0] in value_opts:
            i += 1
            continue
        if a in read_ops:
            read = True
        elif a in write_ops:
            write = True
        elif not a.startswith("-"):
            positional.append(a)
        i += 1
    keys = [k for k, p in enumerate(positional) if p.lower() == "core.hookspath"]
    if not keys:
        return write and any(p.lower() == "core" for p in positional)  # --remove-section core
    if write:
        return True
    if read:
        return False
    return len(positional) > keys[0] + 1  # key だけ = 読む / key + 値 = 書く


def _scan_git(scan: _Scan, args: list[str]) -> None:
    rest = list(args[1:])
    hooks_path = False
    while rest and rest[0].startswith("-"):
        opt = rest.pop(0)
        key = None
        if opt in ("-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix") and rest:
            rest.pop(0)
        elif opt in ("-c", "--config-env") and rest:
            key = rest.pop(0).split("=", 1)[0]
        elif opt.startswith("-c") and len(opt) > 2:
            key = opt[2:].split("=", 1)[0]
        elif opt.startswith("--config-env="):
            key = opt.partition("=")[2].split("=", 1)[0]
        if key is not None and key.strip().lower() == "core.hookspath":
            hooks_path = True
    if not rest:
        return
    op = rest[0]
    if op in GIT_COMMITISH:
        scan.git_ops.append(op)
        if hooks_path:
            scan.found.append(Finding("core.hooksPath", f"git -c core.hooksPath=… {op} (hook の置き場を差し替え)"))
    if op in GIT_HOOK_OPS:
        # git は一意な long option の省略を受ける (`--no-verif` で hook が走らないのを実測)。 共有の flag 解釈は完全一致だけ
        # なので、 --no-verify の省略形を正規の形に直してから渡す (値を取る option の値は向こうが飛ばすので直しても害が無い)
        opts = ["--no-verify" if a.startswith("--no-v") and "--no-verify".startswith(a) else a for a in rest[1:]]
        flags, _ = rule_guard().git_operation_options(op, opts)
        if "no_verify" in flags:
            scan.found.append(Finding("--no-verify", f"git {op} --no-verify / commit -n (hook を省く)"))
    elif op == "config" and _git_config_hookspath_write(rest[1:]):
        scan.found.append(Finding("core.hooksPath", "git config で core.hooksPath を書き換える・消す"))


def _scan_argv(scan: _Scan, args: list[str], depth: int) -> None:
    prefix: list[str] = []
    before = len(scan.git_ops)
    args = _strip_prefix(scan, args, prefix)
    if not args:  # 単独の代入文 = 以後の command に効く (HOME 等の export 済みの名前は子 process にも渡る)
        scan.persistent_redirects.extend(prefix)
        return
    name = Path(args[0]).name
    inner = _shell_script(args)
    if name in DECLARE:
        for w in args[1:]:
            a = _assignment(w)
            r = scan.assignment(*a) if a else None
            if r:
                scan.persistent_redirects.append(r)
    elif name == "launchctl" and len(args) >= 4 and args[1] == "setenv":
        r = scan.assignment(args[2], args[3])
        if r:
            scan.persistent_redirects.append(r)
    elif name == "eval":
        _scan_command(scan, " ".join(args[1:]), depth + 1)
    elif inner is not None:
        _scan_command(scan, inner, depth + 1)
    elif name == "git":
        _scan_git(scan, args)
    if prefix and len(scan.git_ops) > before:  # 前置の差し替えが効く command (中の bash -c 等を含む) が commit 系の git
        for r in dict.fromkeys(prefix):
            scan.redirect(r, scan.git_ops[before])


def _scan_command(scan: _Scan, command: str, depth: int) -> None:
    if depth > 6 or not command.strip():
        return
    try:
        segments = rule_guard().shell_segments(command)
    except ValueError:
        segments = []  # 閉じていない quote 等 = shell も実行できない形。 置換の中だけは下で見る
    for seg in segments:
        _scan_argv(scan, seg, depth)
    for sub in command_substitutions(command):
        _scan_command(scan, sub, depth + 1)


def find_escapes(command: str) -> list[Finding]:
    if not isinstance(command, str) or not PREFILTER.search(command):
        return []
    scan = _Scan()
    _scan_command(scan, command, 0)
    if scan.git_ops:
        for name in dict.fromkeys(scan.persistent_redirects):
            scan.redirect(name, scan.git_ops[0])
    return list(dict.fromkeys(scan.found))


def find_issues(command: str) -> list[str]:
    """calibrate-bash-command-pattern.py 用 (承認を見ない述語だけ)。"""
    return [f.label for f in find_escapes(command)]


# ---------------------------------------------------------------- 承認

def _utc(value) -> _dt.datetime | None:
    try:
        t = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return t if t.tzinfo else None


def approvals_file(sid: str) -> Path:
    """承認台帳の path は dispatcher の定義を使う (置き場の決め方を 2 箇所に持たない)。"""
    path = Path(os.environ.get("ESCAPE_HATCH_GUARD_DISPATCHER") or DISPATCHER)
    if not path.is_file():
        raise EngineUnavailable(str(path))
    spec = importlib.util.spec_from_file_location("manuscript_claim_guard_for_escape", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return Path(mod.approvals_path("claude", sid))


def load_entries(sid: str) -> list[dict]:
    out = []
    try:
        text = approvals_file(sid).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def fresh_approvals(sid: str, now: _dt.datetime | None = None) -> list[dict]:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    ok = []
    for e in load_entries(sid):
        if e.get("session") != f"claude:{sid}":
            continue
        regions = e.get("regions") if isinstance(e.get("regions"), list) else []
        if not any(isinstance(r, str) and r.strip().lower() == REGION for r in regions):
            continue
        if Path(str(e.get("file", ""))).name != HOOK_NAME:
            continue
        at, said = _utc(e.get("at")), _utc(e.get("quote_time"))
        times = [t for t in (at, said) if t is not None]
        if at is None or any(not (now - WINDOW <= t <= now + SKEW) for t in times):
            continue
        ok.append(e)
    return ok


def unapproved(found: list[Finding], sid: str) -> list[Finding]:
    if not found:
        return []
    if not SAFE_SID.match(sid or ""):
        return found
    entries = fresh_approvals(sid)
    left = []
    for f in found:
        named = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(f.key) + r"(?![A-Za-z0-9_])", re.I)
        if not any(named.search(str(e.get("change", ""))) for e in entries):
            left.append(f)
    return left


SAFE_SID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


# ---------------------------------------------------------------- 出力

def deny_reason(left: list[Finding], sid: str) -> str:
    keys = list(dict.fromkeys(f.key for f in left))
    rows = "\n".join(f"  - {f.label}" for f in left[:10])
    approve = (f"python3 {RULE_GUARD} approve --file {HERE / HOOK_NAME} --region {REGION} "
               f"--change '{' '.join(keys)}: <何を・なぜ省くか>' --latest")
    parts = [
        "🛑 escape-hatch-guard: commit gate を外す操作です。 本人の明示の指示が記録されていないので止めました。\n" + rows,
        "本人に聞く。 書き方を変えて通さない (別の env・wrapper・script 経由・gate の設定の差し替えも同じ扱い)。"
        " 誤検出が理由なら、 gate を外すのでなく検査の側 (一覧の allow 等) を直す案を本人に出す。"
        " 試験用の使い捨て repo (git init / clone したばかり) には hook が入っていない = 外さずにそのまま打てばよい。",
        "「直して」「commit して」 のような一般的な依頼は、 gate を外す指示ではない。",
        "本人が明示に指示したら、 その発言を承認として記録してから同じ command を打ち直す"
        " (記録は本人の発言から 30 分有効。 --change に省く対象の名前を入れる。 --latest = 本人の最新の発言そのもの):\n  " + approve,
    ]
    if any(f.key == "--no-verify" or f.label.startswith("git -c") for f in left):
        parts.append("⚠️ --no-verify / commit -n / git -c core.hooksPath は manuscript-claim-guard も承認に依らず止める"
                     f" ({SOT})。 ここで記録してもそちらは通らない。")
    if not SAFE_SID.match(sid or ""):
        parts.append("(この hook の入力に session id が無いので、 承認の記録を照合できない。)")
    return "\n".join(parts)


def emit_deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))


def emit_unchecked(why: str) -> None:
    msg = (f"⚠️ escape-hatch-guard: 内部エラー ({why}) — この command の escape hatch は検査していない (通した)。"
           f" 確認: python3 {HERE / HOOK_NAME} --selftest")
    print(msg, file=sys.stderr)
    print(json.dumps({"systemMessage": msg,
                      "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg}},
                     ensure_ascii=False))


def hook() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        emit_unchecked("入力を読めない: " + type(exc).__name__)
        return 0
    if not isinstance(event, dict) or event.get("tool_name") != "Bash":
        return 0
    ti = event.get("tool_input") or {}
    cmd = ti.get("command") if isinstance(ti, dict) else None
    if not isinstance(cmd, str) or not cmd:
        return 0
    sid = str(event.get("session_id") or "")
    try:
        found = find_escapes(cmd)
    except EngineUnavailable as exc:
        emit_unchecked("解析の部品が無い: " + Path(str(exc)).name)
        return 0
    except Exception as exc:  # noqa: BLE001 (fail-open: guard の不調で作業を止めない。 1 行は出す)
        emit_unchecked(type(exc).__name__)
        return 0
    if not found:
        return 0
    try:
        left = unapproved(found, sid)
    except Exception as exc:  # noqa: BLE001 (見つけた後に台帳を読めない = 指示を確かめられない → 止める)
        emit_deny(deny_reason(found, sid) + f"\n(承認の台帳を読めない: {type(exc).__name__}。 修復してから記録・再試行する)")
        return 0
    if left:
        emit_deny(deny_reason(left, sid))
    return 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    fails: list[str] = []

    def keys(cmd: str) -> list[str]:
        return sorted({f.key for f in find_escapes(cmd)})

    def check(cmd: str, want: list[str], why: str) -> None:
        got = keys(cmd)
        ok = got == sorted(want)
        print(f"  {'PASS' if ok else 'FAIL'} {why}" + ("" if ok else f" — got {got}, want {sorted(want)}"))
        if not ok:
            fails.append(why)

    S = "CLAUDE_STUDENT_ID_GUARD"
    # 止める (代入の形・quote・shell の違い)
    check(f"{S}=0 git commit -m x", [S], "前置の代入")
    check(f"{S}='0' git commit -m x", [S], "single quote の値")
    check(f'{S}="0" git commit -m x', [S], "double quote の値")
    check(f"{S}=$'0' git commit -m x", [S], "ANSI-C quote (bash / zsh) = 計算値として当てる")
    check(f'{S}="$(printf 0)" git commit -m x', [S], "計算値")
    check(f"{S}=off git commit -m x", [S], "off も止める値")
    check(f"export {S}=0; git commit -m x", [S], "export")
    check(f"typeset -x {S}=0 && git commit -m x", [S], "typeset -x (zsh)")
    check(f"{S}=0\ngit commit -m x", [S], "単独の代入文 (改行)")
    check(f"env {S}=0 git commit -m x", [S], "env の後")
    check(f"env -u FOO {S}=0 git commit -m x", [S], "env -u の値を飛ばす")
    check(f"timeout 60 env {S}=0 git commit -m x", [S], "timeout DURATION env")
    check(f"cd /tmp/r && {S}=0 git commit -m x", [S], "&& の後")
    check(f"( {S}=0 git commit -m x )", [S], "subshell")
    check(f"{{ {S}=0 git commit -m x; }}", [S], "group")
    check(f"if true; then {S}=0 git commit -m x; fi", [S], "if の then")
    check(f"bash -c '{S}=0 git commit -m x'", [S], "bash -c")
    check(f'zsh -lc "{S}=0 git commit -m x"', [S], "zsh -lc")
    check(f"eval '{S}=0 git commit -m x'", [S], "eval")
    check(f'out="$({S}=0 git commit -m x 2>&1)"', [S], "double quote の中の $(…)")
    check(f"out=`{S}=0 git commit -m x`", [S], "backtick")
    check(f"env -S '{S}=0 git commit -m x'", [S], "env -S")
    check(f"launchctl setenv {S} 0", [S], "launchctl setenv")
    check("CLAUDE_FUTURE_GATE_GUARD=0 git commit -m x", ["CLAUDE_FUTURE_GATE_GUARD"], "名前は形で当てる")
    check("git commit --no-verify -m x", ["--no-verify"], "--no-verify")
    check("git commit -nm x", ["--no-verify"], "commit -n (結合)")
    check("git -C /tmp/r push --no-verify origin main", ["--no-verify"], "push --no-verify")
    check("git commit --no-verif -m x", ["--no-verify"], "--no-verify の省略形 (git が受ける)")
    check("git commit -m --no-verif", [], "-m の値の省略形は値のまま")
    check("git -c core.hooksPath=/dev/null commit -m x", ["core.hooksPath"], "git -c core.hooksPath")
    check("git -ccore.hookspath=/dev/null push origin main", ["core.hooksPath"], "結合・小文字")
    check("git -C r -c core.hooksPath=/dev/null merge x", ["core.hooksPath"], "-C の後の -c")
    check("git config core.hooksPath /dev/null", ["core.hooksPath"], "git config で書く")
    check("git config --unset core.hooksPath", ["core.hooksPath"], "git config --unset")
    check("git config set core.hooksPath x", ["core.hooksPath"], "git config set (新しい形)")
    check("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x",
          ["core.hooksPath"], "GIT_CONFIG_KEY_n")
    check("GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='/dev/null'\" git commit -m x", ["core.hooksPath"],
          "GIT_CONFIG_PARAMETERS")
    check("CLAUDE_STUDENT_IDENTITY=/dev/null git commit -m x", ["CLAUDE_STUDENT_IDENTITY"], "一覧の差し替え + commit")
    check("export HOME=/tmp/h; git -C r commit -m x", ["HOME"], "HOME の差し替え + commit")
    check("ls | xargs env CLAUDE_LEAK_GUARD=0 git commit -m x", ["CLAUDE_LEAK_GUARD"], "xargs の後")
    check(f"time -p env {S}=0 git commit -m x", [S], "time -p")
    check("HOME=/tmp/h bash -c 'git commit -m x'", ["HOME"], "前置の差し替え + 中の commit")
    check("MANUSCRIPT_CLAIM_GUARD_STATE_DIR=/tmp/s; export MANUSCRIPT_CLAIM_GUARD_STATE_DIR; git commit -m x",
          ["MANUSCRIPT_CLAIM_GUARD_STATE_DIR"], "承認の置き場の差し替え (単独の代入文) + commit")
    # 通す (data・読むだけ・止めない値)
    check(f"echo {S}=0", [], "echo の引数")
    check(f"grep -rn '{S}=0' scripts", [], "grep の引数")
    check(f'git commit -m "escape hatch = {S}=0 を書いた"', [], "commit message の中")
    check(f"git commit -F - <<'EOF'\n{S}=0 git commit --no-verify\nEOF", [], "heredoc の本文")
    check(f"cat > /tmp/x.txt <<'EOF'\nexport {S}=0\nEOF", [], "heredoc の本文 (export)")
    check(f"echo '$({S}=0 git commit)'", [], "single quote の中の $(…)")
    check(f"git commit -m \"$(cat <<'EOF'\nmsg {S}=0 --no-verify\n$({S}=0 git commit)\nEOF\n)\"", [],
          "commit message を $(cat <<'EOF' …) で渡す定番の形 (本文は data)")
    check(f"cat <<EOF > /tmp/x\n$({S}=0 git commit -m y)\nEOF", [S], "quote しない heredoc の本文の $(…) は実行される")
    check(f"{S}=1 git commit -m x", [], "止めない値 (1)")
    check(f"{S}= git commit -m x", [], "空 = 既定 (止めない)")
    check("CLAUDE_ZSH_SPLIT_GUARD=1 true", [], "test 用の 1")
    check("git config --get core.hooksPath", [], "git config --get")
    check("git -c core.hooksPath=/dev/null worktree add ../wt origin/main", [], "commit 系でない subcommand への -c")
    check("export GIT_CONFIG_GLOBAL=/dev/null; git init -q r && git -C r commit -qm i", [], "GIT_CONFIG_GLOBAL (試験の定番)")
    check("git config core.hooksPath", [], "git config の key だけ = 読む")
    check("git push -n origin main", [], "push -n = dry-run")
    check("git commit -m '--no-verify'", [], "-m の値の --no-verify")
    check("CLAUDE_STUDENT_IDENTITY=/tmp/l.json python3 check-student-identifiers.py --tree /tmp/r", [],
          "一覧の差し替えだけ (commit なし = 試験)")
    check("HOME=/tmp/h ls", [], "HOME の差し替えだけ")
    check("HOME=/tmp/h ./run-test.sh; git -C r commit -m x", [], "前置の差し替えは別の command (commit) に効かない")
    check(f"git commit -F - <<'EOF'\nmsg $({S}=0 git commit)\nEOF", [], "quote した heredoc の本文の $(…)")
    check("ls -la; python3 x.py --selftest", [], "無関係")
    check("git status && git log --oneline -3", [], "git の読むだけ")
    print(f"escape-hatch-guard selftest: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        raise SystemExit(selftest())
    try:
        raise SystemExit(hook())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        emit_unchecked(type(exc).__name__)
        raise SystemExit(0)
