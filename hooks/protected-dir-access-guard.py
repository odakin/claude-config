#!/usr/bin/env python3
"""protected-dir-access-guard.py — PreToolUse(Bash / Grep / Glob / Read / Edit / Write): 保護を宣言した dir を名指す操作に確認を出し (ask)、 上位 dir から再帰して中に届く操作は止める (exit 2)

なぜ:
  機密の作業 dir (remote を持たない作業リポ等) への「読むだけ」 のアクセスを止めたいとき、 settings の path rule
  (`Read(path)` / `Edit(path)` の ask / deny) だけでは足りない。 Bash で path rule が効くのは file を名指しする読み方
  (`cat` 等) だけで、 `find` / `grep -r` / `git -C` / script の中の走査は素通りする (実測: 横断 sweep が上位 dir からの find と loop で保護 dir に
  触れ、 確認は 0 回)。 上位 dir を再帰する検索は、 保護 dir の名前を 1 度も書かずに中へ届く。
  規約 = conventions/confidential-repo-boundary.md#protected-dir-access-guard

保護する dir (どれも任意、 無ければ何もしない = fail-open):
  - 環境変数 CLAUDE_PROTECTED_DIRS (os.pathsep 区切り。 指定すると下の 2 file は読まない = test 用)
  - ~/.claude/protected-dirs.txt       (1 行 1 dir、 `#` 以降は comment、 `~` 可)
  - ~/.claude/leak-pattern-sources.txt (check-confidential-leak.py の作業リポ登録 = remote に出してはいけない実体の
                                        置き場を、 触ってもいけない dir として使う。 二重管理にしないため)

判定 (保護 dir D、 その親 dir の名前 P、 D の名前 B)。 Bash の command は単純 command (改行・; & | ( ) で割った 1 片。
`\` 改行は継ぐ) ごとに shlex で語に分けて読む = 引用符の中の `/` (awk の "/"・sed の s/…/…/)・文の中の語は数えない。
heredoc の本文は command として読まず、 shell (`bash <<EOF`) と python (`python3 - <<EOF`) に流す本文だけを中身として読む。
`bash -c` / `sh -c` / `eval` の文字列は command として読み直す。 同じ command の `for … in` の並びと代入は変数の値として読む:
  確認を出す (ask = 本人が dialog の文字から「中に入る」 と読める)
    (a) 語が D の path を書く (実体 path / home 直下 symlink 経由の別名 / `~` / `$HOME` 形 / 同じ command で代入した変数。
        相対の語は直前の `cd` と cwd から読む) か `P/B` を書く、 または glob が親 P か名前 B を書いて D に当たる。
        python の code (-c・heredoc) の中の D の path も同じ。 除外の pattern の語・message の値 (`-m` など)・echo の引数・
        grep などの検索語は数えない。 除外を添えても名指しは名指し。 再帰の道具の起点が D の中
    (c) cwd が D の中
    (f) Grep の起点 (path、 無ければ cwd) が D の中・Grep の glob が B を書く・Glob の pattern が D を名指す
    (g) Read / Edit / Write / NotebookEdit の file が D の中
  止める (stop = exit 2、 理由と直し方を Claude に返す。 本人には何も出さない)
    (b) 片の先頭の語 (sudo / nice / timeout / env / stdbuf / caffeinate / xargs / `uv run` などの前置きは option ごと外す) が
        再帰の道具 (find / grep -r / ugrep / rg / fd / ag / ack / du / tree / ls -R / rsync / tar / zip / cp -r / scp -r / ditto)
        で、 その起点 (道具ごとに option の値・検索語・写し先を除いた位置引数。 find は -L などの前置きの後。 引数が無ければ
        cwd。 glob は広がる先) が D の上位 dir で、 D の中身を除く書き方 (下) が無い
    (b') mdfind (`-onlyin` が D の上位 dir か無い) / locate = 全体の索引を引く
    (b'') 上位 dir からの `**` の glob、 名を書かずに D か D の中まで広がる glob。 python (-c・heredoc) の走査
          (os.walk / rglob / copytree …) と上位 dir の path (`/` 1 文字と `/Users`・`Path.home() / "<下>"` は数えない) が同じ code
    (b''') 再帰の道具の起点が値の読めない変数・`$()`・xargs で、 その源 (xargs = 前の片、 ほか = for の並び・代入・echo の引数)
          に D の上位 dir を指す語がある
    (f') Grep の起点が D の上位 dir で glob が D を除かない / Glob の pattern が上位 dir からの `**` か、 名を書かずに D の中まで届く
  D の中身を除く書き方 (これだけを除外と数える。 D の dir だけを除く形 = `-not -name B`・`-not -path '*/B'`・grep の
    `--exclude=B` は数えない): find の `-path/-name <pat> -prune` と `-not -path '*/B/*'`、 grep の `--exclude-dir`、 rg の
    `-g '!…'`、 fd の `-E`、 ag の `--ignore(-dir)`、 ack の `--ignore-dir`、 tar・rsync の `--exclude`、 zip の `-x`、 du の
    `--exclude` / `-I`、 tree の `-I`、 ls の `--ignore`、 Grep の glob `!…`、 mdfind の `-onlyin <外>`、 python の `dirs[:] = …` で B を除く code。
  何もしない: B を含む文 (commit message・規約の grep)、 再帰しない一覧 (`ls <親>`)、 D の外の具体的な dir への再帰、
    除外つきの走査、 file を書くだけの heredoc の本文、 他の tool。
  ⚠️ 射程外 = script file の中の走査、 script の引数・`python -m` で渡す起点、 同じ command で定義していない変数
    (環境変数) の起点、 上の表に無い道具 (rclone・aws s3 sync・7z など)。 ⚠️ 版によって値を取ったり取らなかったりする
    option は値を取らない側に読む (値と読むと次の起点を読み飛ばす = 素通り)。 目的は事故の防止。
ask と stop を分ける理由: 名指し・cwd が中は、 保護 dir の作業 session では中で作業するのが正当 (止まるのは仕様、 本人が
  dialog の command から判断できる)。 上位 dir からの走査は、 本人が dialog から中に届くかを読めず、 ask にすると読まずに
  押される (実測: 確認の大半が文中の語の誤検出で、 その許可が下の「以後は通す」 を開いた session の大半は
  D を一度も名指していなかった)。 走査は Claude が起点を絞るか除外を足せば同じ結果が得られるので、 止めて直させる。
  確認を出すのは本人が dialog の文字だけで決められる操作だけ = conventions/claude-code-permissions.md#ask-only-owner-judgeable

session 内の 1 回限り (= 「一度許可したら、 その session では通し」):
  同じ session で毎回確認が出ると、 中で作業する session では人が読まずに押す儀式になる (= gate が壊れる)。
  そこで **PostToolUse で「実際に通った」 = user が許可した事実を記録**し、 以後その session ではその dir に
  ついて allow を返す (記録 = ~/.claude/protected-dir-unlock/<session_id>、 session ごと・dir ごと)。
  - 記録するのは PostToolUse (= tool が走った後) だけ。 PreToolUse は記録しない (= 拒否された call で開かない)
  - 開くのは確認 (ask) の判定の call が走ったときだけ。 止める (stop) 判定は開いた session でも止める
  - session_id の無い呼び出し (canary 等) は常に ask (= 記録も参照もしない)
  - 古い記録は書くときに間引く (既定 7 日)
  ⚠️ trade-off: 1 回許可すると、 その session の後続の call は確認なしで中に触れる (= 本人が意図した作業の
  ためだが、 その session に外部由来の指示が混ざれば同じ扉を通る)。 session をまたいでは開かない。

usage:
  (hook)                                   stdin = PreToolUse / PostToolUse の JSON
  protected-dir-access-guard.py --canary   本番の settings.json と install 済み hook で、 宣言した dir の probe に
                                           確認が出るか・上位 dir からの走査が止まるかを 1 行で報告 (ARMED / NOT ARMED / 未配線 / 対象外)
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time

HOOK_NAME = "protected-dir-access-guard.py"
BOUND_END = r"""(?=/|["')\s;&|]|$)"""
BOUND_START = r"""(?:^|[\s"'=(:])"""


def _home() -> str:
    return os.environ.get("HOME") or os.path.expanduser("~")


def _expand(p: str, home: str) -> str:
    for pre in ("${HOME}", "$HOME", "~"):
        if p == pre:
            return home
        if p.startswith(pre + "/"):
            return home + p[len(pre):]
    return p


def load_dirs(home: str) -> list[str]:
    env = os.environ.get("CLAUDE_PROTECTED_DIRS")
    raw: list[str] = []
    if env is not None:
        raw = [x for x in env.split(os.pathsep) if x.strip()]
    else:
        for name in ("protected-dirs.txt", "leak-pattern-sources.txt"):
            try:
                with open(os.path.join(home, ".claude", name), encoding="utf-8") as fh:
                    for line in fh:
                        line = line.split("#", 1)[0].strip()
                        if line:
                            raw.append(line)
            except OSError:
                pass
    out: list[str] = []
    for r in raw:
        p = os.path.normpath(_expand(r.strip(), home))
        if os.path.isabs(p) and p != "/" and p not in out:
            out.append(p)
    return out


def _aliases(home: str) -> list[tuple[str, str]]:
    """home 直下の symlink (例 ~/Dropbox → ~/Library/CloudStorage/Dropbox) = (別名, 実体)。 長い実体から。"""
    pairs = []
    try:
        names = os.listdir(home)
    except OSError:
        return pairs
    for n in names:
        link = os.path.join(home, n)
        if os.path.islink(link):
            real = os.path.realpath(link)
            if real != link and os.path.isdir(real):
                pairs.append((link, real))
    return sorted(pairs, key=lambda x: -len(x[1]))


def _physical(p: str, aliases: list[tuple[str, str]]) -> str:
    p = os.path.normpath(p)
    for link, real in aliases:
        if p == link or p.startswith(link + "/"):
            return real + p[len(link):]
    return p


class Protected:
    def __init__(self, d: str, home: str, aliases: list[tuple[str, str]]):
        parent = os.path.dirname(d)
        # 親だけを実体化する (保護 dir そのものには触れない)
        real_parent = os.path.realpath(parent) if os.path.isdir(parent) else _physical(parent, aliases)
        self.phys = os.path.join(real_parent, os.path.basename(d))
        self.name = os.path.basename(self.phys)
        self.parent_name = os.path.basename(real_parent)
        forms = {d, self.phys}
        for link, real in aliases:
            if self.phys.startswith(real + "/"):
                forms.add(link + self.phys[len(real):])
        self.forms = sorted(forms)
        self.path_re = re.compile("|".join(self._variants_re(f, home) for f in self.forms))
        self.pb_re = re.compile(re.escape(self.parent_name + "/" + self.name) + BOUND_END)
        self.parent_glob_re = re.compile(re.escape(self.parent_name) + r"""/[^/\s"']*[*?\[]""")
        ancestors = set()
        for f in self.forms:
            a = os.path.dirname(f)
            while True:
                ancestors.add(a)
                if a == "/":
                    break
                a = os.path.dirname(a)
        self.anc_re = re.compile(
            BOUND_START + "(?:" + "|".join(self._variants_plain(a, home) for a in sorted(ancestors, key=len, reverse=True))
            + r""")/?(?=["')\s;&|]|$)"""
        )
        self.name_word_re = re.compile(BOUND_START + re.escape(self.name) + BOUND_END)
        # python の走査の判定用 = `/` と `/Users` を除いた上位 dir (引用符・split('/') の `/` 1 文字を数えない)
        deep = [a for a in ancestors if a not in ("/", "/Users")]
        self.anc_home_re = re.compile(
            BOUND_START + "(?:" + "|".join(self._variants_plain(a, home) for a in sorted(deep, key=len, reverse=True))
            + r""")/?(?=["')\s;&|]|$)"""
        ) if deep else re.compile(r"(?!)")

    @staticmethod
    def _home_variants(p: str, home: str) -> list[str]:
        vs = [p]
        if p == home:
            vs += ["~", "$HOME", "${HOME}"]
        elif p.startswith(home + "/"):
            rel = p[len(home):]
            vs += ["~" + rel, "$HOME" + rel, "${HOME}" + rel]
        return vs

    def _variants_re(self, f: str, home: str) -> str:
        return BOUND_START + "(?:" + "|".join(re.escape(v) for v in self._home_variants(f, home)) + ")" + BOUND_END

    def _variants_plain(self, a: str, home: str) -> str:
        return "|".join(re.escape(v) for v in self._home_variants(a, home))

    def inside(self, p: str) -> bool:
        return p == self.phys or p.startswith(self.phys + "/")

    def ancestor(self, p: str) -> bool:
        return p == "/" or self.phys.startswith(p.rstrip("/") + "/")

    def is_parent(self, p: str) -> bool:
        return p == os.path.dirname(self.phys)


def _norm(p: str, cwd: str, home: str, aliases) -> str:
    p = _expand(p, home)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return _physical(os.path.normpath(p), aliases)


UNLOCK_DIR = "protected-dir-unlock"
UNLOCK_KEEP_DAYS = 7


def _unlock_file(home: str, sid: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sid)[:128]
    return os.path.join(home, ".claude", UNLOCK_DIR, safe)


def is_unlocked(home: str, sid: str, phys: str) -> bool:
    """この session で、 この保護 dir が既に許可されたか (session_id が無ければ常に False)。"""
    if not sid:
        return False
    try:
        with open(_unlock_file(home, sid), encoding="utf-8") as fh:
            return any(line.strip() == phys for line in fh)
    except OSError:
        return False


def record_unlock(home: str, sid: str, phys: str) -> bool:
    """許可された事実を記録する (冪等)。 書けたら True。 ついでに古い記録を間引く。"""
    if not sid:
        return False
    if is_unlocked(home, sid, phys):
        return False
    path = _unlock_file(home, sid)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(phys + "\n")
    except OSError:
        return False
    cutoff = time.time() - UNLOCK_KEEP_DAYS * 86400
    try:
        for n in os.listdir(os.path.dirname(path)):
            f = os.path.join(os.path.dirname(path), n)
            if f != path and os.path.getmtime(f) < cutoff:
                os.remove(f)
    except OSError:
        pass
    return True


ASK = "ask"    # 本人に確認を出す (保護 dir を名指す・cwd が中 = 中で作業する意図が command から読める)
STOP = "stop"  # exit 2 で止めて Claude に直させる (上位 dir から再帰して辿る = 本人は dialog から届くかを読めない)

# 単純 command の先頭に来る、 再帰の道具でない前置きの語。 後ろの option (値を取るものは値ごと) と数の引数ごと外す
PREFIX_WORDS = {"sudo", "doas", "time", "gtime", "nice", "nohup", "command", "builtin", "exec", "then", "do", "else",
                "elif", "if", "while", "until", "{", "}", "!", "stdbuf", "caffeinate", "ionice", "taskpolicy",
                "unbuffer", "noglob", "nocorrect", "chrt", "arch", "taskset"}
PREFIX_VALUE_OPTS = {
    "sudo": {"-u", "-g", "-C", "-h", "-p", "-U", "-r", "-t", "-D", "-R", "-T"},
    "doas": {"-u", "-C"},
    "nice": {"-n"},
    "caffeinate": {"-t", "-w"},
    "ionice": {"-c", "-n", "-p"},
    "time": {"-f", "-o"}, "gtime": {"-f", "-o"},
    "stdbuf": {"-i", "-o", "-e"},
    "taskpolicy": {"-c", "-d", "-g", "-t", "-l", "-p"},
}
RUNNERS = {"uv", "poetry", "pdm", "pipenv", "rye", "hatch", "conda", "mamba", "micromamba", "pixi"}  # `<x> run …`
RUNNER_VALUE_OPTS = {"--with", "--python", "-p", "--project", "--directory", "-n", "--name", "--prefix", "-e",
                     "--env", "--from", "--with-requirements"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
PY_EXE_RE = re.compile(r"^(?:python(?:\d+(?:\.\d+)?)?|pypy3?|py)$")
# 道具の別名 → 同じ読み方をする族
FAMILY = {"gfind": "find", "ggrep": "grep", "egrep": "grep", "fgrep": "grep", "ugrep": "grep", "ug": "grep",
          "gdu": "du", "gls": "ls", "gcp": "cp", "gtar": "tar", "bsdtar": "tar"}
RECURSE_ALWAYS = {"find", "rg", "fd", "ag", "ack", "du", "tree", "rsync", "tar", "zip", "ditto"}  # 族の名
# 値を取る option (値は起点でない)。 ⚠️ 版によって値を取らない option は入れない (入れると次の起点を読み飛ばす = 素通り)
VALUE_OPTS = {
    "grep": {"-e", "--regexp", "-f", "--file", "-m", "--max-count", "-A", "-B", "-C", "--include", "--exclude",
             "--exclude-dir", "--exclude-from", "-d", "--directories", "-D", "--devices", "--label"},
    "rg": {"-e", "--regexp", "-f", "--file", "-g", "--glob", "--iglob", "-t", "--type", "-T", "--type-not", "-m",
           "--max-count", "-A", "-B", "-C", "--context", "-d", "--max-depth", "--maxdepth", "-j", "--threads", "-E",
           "--encoding", "--type-add", "--type-clear", "-r", "--replace", "--sort", "--sortr", "-M", "--max-columns",
           "--ignore-file", "--pre", "--pre-glob", "--path-separator", "--max-filesize", "--color", "--colors",
           "--context-separator", "--field-match-separator", "--engine", "--dfa-size-limit", "--regex-size-limit"},
    "fd": {"-e", "--extension", "-E", "--exclude", "-t", "--type", "-d", "--max-depth", "--min-depth",
           "--exact-depth", "-j", "--threads", "-S", "--size", "--changed-within", "--changed-before", "-o",
           "--owner", "--base-directory", "--search-path", "-c", "--color", "--max-results", "--ignore-file",
           "--batch-size", "--format", "--path-separator"},
    "ag": {"-G", "--file-search-regex", "-g", "--ignore", "--ignore-dir", "-m", "--max-count", "--depth", "-p",
           "--path-to-ignore", "--pager", "-W", "--width"},
    "ack": {"--ignore-dir", "--ignore-directory", "--noignore-dir", "--type", "-t", "-m", "--max-count",
            "--ignore-file", "--match", "--output", "--pager"},
    "du": {"-d", "--max-depth", "-I", "--exclude", "-B", "--block-size", "-t", "--threshold", "--time-style", "-X",
           "--exclude-from", "--files0-from"},
    "tree": {"-L", "-I", "-P", "-o", "--filelimit", "-H", "-T", "--charset", "--sort", "--timefmt"},
    "tar": {"-f", "--file", "-C", "--directory", "--exclude", "-X", "--exclude-from", "-T", "--files-from", "-b",
            "--blocking-factor", "--format", "--use-compress-program", "-I", "--transform", "--strip-components"},
    "rsync": {"--exclude", "--include", "--exclude-from", "--include-from", "--filter", "-f", "-e", "--rsh",
              "--rsync-path", "--files-from", "--log-file", "--temp-dir", "-T", "--partial-dir", "--backup-dir",
              "--suffix", "--chmod", "--chown", "--timeout", "--bwlimit", "--max-size", "--min-size",
              "--compare-dest", "--copy-dest", "--link-dest", "--out-format", "--port", "--password-file", "-B",
              "--block-size", "-M", "--remote-option", "--usermap", "--groupmap", "--info", "--debug"},
    "zip": {"-b", "-n", "-t", "-tt", "-O", "--out", "-Z", "-P", "--password"},
    "cp": {"-t", "--target-directory", "-S", "--suffix"},
    "scp": {"-F", "-i", "-l", "-o", "-P", "-S", "-c", "-J"},
    "ls": {"--ignore", "--hide", "--block-size", "--format", "--sort", "--time", "--time-style", "--quoting-style",
           "--indicator-style", "--width", "--tabsize"},
    "ditto": {"--arch", "--bom"},
}
UGREP_VALUE_OPTS = {"-g", "--glob", "--iglob", "-O", "-t", "-M", "--file-extension", "--file-type", "--file-magic"}
PATTERN_FIRST = {"grep", "rg", "ag", "ack", "fd"}   # 最初の位置引数は検索語 (path でない)
DEST_LAST = {"rsync", "cp", "scp", "ditto"}         # 最後の位置引数は写し先 (走査の起点でない)
INDEX_TOOLS = {"mdfind", "locate"}  # 起点を書かなくても全体の索引を引く
PY_WALK_RE = re.compile(r"os\.f?walk\(|\.walk\(|\.rglob\(|recursive\s*=\s*True|shutil\.(?:copytree|rmtree|make_archive)\(")
# home をそのまま走査の起点にする python の書き方 (直後に `/`・`+`・`,` で下の dir をつなぐ形 = 具体的な dir は数えない)
HOME_FN_RE = re.compile(r"(?:Path\.home\(\)|os\.environ\[\s*['\"]HOME['\"]\s*\]|getenv\(\s*['\"]HOME['\"]\s*\))(?!\s*[/+,])")
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
GLOB_CHARS = re.compile(r"[*?\[]")
FIND_MATCH = {"-path", "-ipath", "-wholename", "-iwholename", "-name", "-iname"}
MESSAGE_OPTS = {"-m", "--message", "--subject", "--body", "--title", "--description"}  # 値は文 (path でない)
TEXT_ONLY = {"echo", "printf"}  # 引数は出力する文 (向き先の `>` の後の語だけが path)
REDIRECTS = {">", ">>", "<", "&>", "2>", ">|", "1>", "2>>"}


def _fam(w0: str) -> str:
    return FAMILY.get(w0, w0)


def _simple_commands(cmd: str) -> list[tuple[list[str], str, str]]:
    """command を単純 command ごとの (語の列, heredoc の本文, 直前の区切り) に分ける。
    `\\` 改行は 1 行に継ぐ。 行ごとに shlex (引用符の中の ; | / は割らない、 # 以降は捨てる)。 区切り = `|` / `&&` / `;` /
    `(` など (行の頭は改行 = "\\n")。 heredoc の本文は command として読まず、 `<<` を書いた片に本文として付ける
    (shell・python に渡す本文は呼び手が読む)。"""
    cmd = re.sub(r"\\\r?\n", " ", cmd)
    lines = cmd.split("\n")
    out: list[tuple[list[str], str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        tags = [(m.group(1) == "-", m.group(3)) for m in HEREDOC_RE.finditer(line)]
        try:
            lx = shlex.shlex(line, posix=True, punctuation_chars=True)
            lx.whitespace_split = True
            toks = list(lx)
        except ValueError:  # 閉じない引用符 = 空白で割るだけ
            toks = line.split()
        segs: list[tuple[list[str], str]] = []
        cur: list[str] = []
        sep = "\n"
        for t in toks:
            if t and set(t) <= set(";&|()"):
                if cur:
                    segs.append((cur, sep))
                cur = []
                sep = t
            else:
                cur.append(t)
        if cur:
            segs.append((cur, sep))
        bodies = []
        for dash, tag in tags:
            body = []
            while i < len(lines):
                ln = lines[i]
                i += 1
                if (ln.lstrip("\t") if dash else ln).strip() == tag:
                    break
                body.append(ln)
            bodies.append("\n".join(body))
        k = -1
        if bodies and segs:
            k = next((j for j, (s, _) in enumerate(segs) if any(w.startswith("<<") for w in s)), len(segs) - 1)
        for j, (s, sp) in enumerate(segs):
            out.append((s, "\n".join(bodies) if j == k else "", sp))
    return out


VAR_REF_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def _subst(word: str, vars_: dict, home: str) -> list[str] | None:
    """語の中の $NAME / ${NAME} を、 同じ command の for・代入で決まる値に置き換えた候補。
    読めない (定義の無い変数・値の読めない変数・$( ・` ・$1 など) なら None。"""
    w = word.replace("${HOME}", home).replace("$HOME", home)
    if "`" in w or "$(" in w:
        return None
    names = {a or b for a, b in VAR_REF_RE.findall(w)}
    if "$" in VAR_REF_RE.sub("", w):
        return None
    cands = [w]
    for name in names:
        vals = vars_.get(name)
        if vals is None:
            return None
        pat = re.compile(r"\$(?:\{" + re.escape(name) + r"\}|" + re.escape(name) + r"(?![A-Za-z0-9_]))")
        cands = [pat.sub(lambda _m, v=v: v, c) for c in cands for v in vals][:64]
    return cands


def _strip_prefix(words: list[str]) -> tuple[list[str], bool]:
    """環境変数の代入・sudo / nice / timeout N / env / `uv run` / xargs などの前置きを外す。
    返す = (残りの語, xargs を通したか = 起点が標準入力から来る)。"""
    w = list(words)
    fed = False
    while w:
        h = w[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", h):
            w = w[1:]
        elif h in PREFIX_WORDS:
            vopts = PREFIX_VALUE_OPTS.get(h, set())
            w = w[1:]
            while w and w[0].startswith("-") and w[0] != "-":
                opt = w[0]
                w = w[1:]
                if opt in vopts and w:
                    w = w[1:]
            while w and re.match(r"^\d+$", w[0]):  # chrt -f 10 / nice の数など
                w = w[1:]
        elif h in ("timeout", "gtimeout"):
            w = w[1:]
            while w and (w[0].startswith("-") or re.match(r"^\d+(\.\d+)?[smhd]?$", w[0])):
                w = w[1:]
        elif h == "env":
            w = w[1:]
            while w and (w[0].startswith("-") or "=" in w[0]):
                opt = w[0]
                w = w[1:]
                if opt in ("-u", "-C", "-S", "-P") and w:
                    w = w[1:]
        elif h in ("xargs", "parallel"):
            fed = True
            w = w[1:]
            while w and w[0].startswith("-"):
                takes = w[0] in ("-n", "-I", "-P", "-L", "-s", "-d", "-E", "-a", "-j", "-J", "-R", "-S")
                w = w[2:] if takes else w[1:]
        elif h in RUNNERS and len(w) > 1 and w[1] == "run":
            w = w[2:]
            while w and w[0].startswith("-"):
                opt = w[0].split("=", 1)[0]
                w = w[1:]
                if opt in RUNNER_VALUE_OPTS and "=" not in opt and w:
                    w = w[1:]
        else:
            break
    return w, fed


def _is_recursive(fam: str, w0: str, args: list[str]) -> bool:
    if fam in RECURSE_ALWAYS or w0 == "ug":
        return True
    shorts = "".join(a[1:] for a in args if re.match(r"^-[A-Za-z]+$", a))
    if fam == "grep":
        return bool(re.search(r"[rR]", shorts)) or "--recursive" in args or "--dereference-recursive" in args \
            or any(a in ("--directories=recurse", "-drecurse") for a in args) or ("-d" in args and "recurse" in args)
    if fam == "ls":
        return "R" in shorts or "--recursive" in args
    if fam == "cp":
        return bool(re.search(r"[rRa]", shorts)) or "--recursive" in args or "--archive" in args
    if fam == "scp":
        return "r" in shorts
    return False


def _find_starts(args: list[str]) -> list[str]:
    """find の起点 = 前置きの option (-H -L -P -E -X -s -x -d -O -D、 BSD の -f path) の後、 式の手前までの語。"""
    starts: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-H", "-L", "-P", "-E", "-X", "-s", "-x", "-d") or re.match(r"^-O\d*$", a):
            i += 1
        elif a == "-D":
            i += 2
        elif a == "-f" and i + 1 < len(args):
            starts.append(args[i + 1])
            i += 2
        else:
            break
    while i < len(args):
        a = args[i]
        if a.startswith("-") or a in ("(", "!", ")", ","):
            break
        starts.append(a)
        i += 1
    return starts


def _starts(fam: str, w0: str, args: list[str]) -> tuple[list[str], str | None]:
    """再帰の起点になりうる語と、 相対の起点を読む基準 (tar の -C。 無ければ None = 実効 cwd)。
    option・その値・検索語・写し先を除く。 ⚠️ 読み過ぎ (起点を飛ばす) は素通りになる = 迷う語は起点に残す。"""
    if fam == "find":
        return _find_starts(args), None
    vopts = set(VALUE_OPTS.get(fam, set()))
    if w0 in ("ugrep", "ug"):
        vopts |= UGREP_VALUE_OPTS
    pos: list[str] = []
    extra: list[str] = []
    base: str | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if fam == "zip" and a in ("-x", "-i"):  # 後ろの語は -@ か次の option まで全部が pattern
            i += 1
            while i < len(args) and not args[i].startswith("-"):
                i += 1
            continue
        if fam == "fd" and a in ("-x", "--exec", "-X", "--exec-batch"):  # 残りは実行する command
            break
        if a.startswith("-") and a != "-":
            name, eq, val = a.partition("=")
            if eq:
                if name in ("--search-path", "--base-directory"):
                    extra.append(val)
                elif fam == "tar" and name == "--directory":
                    base = val
                i += 1
                continue
            if name in vopts:
                if i + 1 < len(args):
                    if name in ("--search-path", "--base-directory"):
                        extra.append(args[i + 1])
                    elif fam == "tar" and name in ("-C", "--directory") and base is None:
                        base = args[i + 1]
                i += 2
                continue
            i += 1
            continue
        pos.append(a)
        i += 1
    if fam in PATTERN_FIRST and pos:
        explicit = any(a in ("-e", "--regexp", "-f", "--file") or a.startswith(("--regexp=", "--file="))
                       or (fam == "grep" and re.match(r"^-[A-Za-z]*[ef]$", a)) for a in args)
        if fam == "rg" and ("--files" in args or "--type-list" in args):
            explicit = True
        if fam in ("ag", "ack") and any(a in ("-g", "-f") for a in args):
            explicit = True
        if fam == "fd" or not explicit:
            pos = pos[1:]
    if fam in DEST_LAST and len(pos) >= 2 and not any(a in ("-t", "--target-directory") or
                                                       a.startswith("--target-directory=") for a in args):
        pos = pos[:-1]
    if fam == "zip" and pos:
        pos = pos[1:]  # 最初の位置引数は archive
    return pos + extra, base


def _resolve(p: str, cwd: str, home: str, aliases) -> str:
    p = p.replace("${HOME}", home).replace("$HOME", home)
    return _norm(p, cwd, home, aliases)


def _unresolved(word: str, home: str) -> bool:
    w = word.replace("${HOME}", home).replace("$HOME", home)
    return "$" in w or "`" in w


def _glob_target(v: str, cwd: str | None, pr: "Protected", home: str, aliases, path_only: bool = False) -> str:
    """glob を含む語の行き先: in (D の中か D を、 親 P か名前 B を書いて) / wild (D の中か D に、 名を書かずに広がる) /
    rec (上位 dir からの ** = 再帰) / anc (D の上位 dir に広がる) / 空。
    path_only = 当たった path だけを返す道具 (Glob tool): D そのもので止まる glob は中に届かないので空。"""
    p = _expand(v.replace("${HOME}", home).replace("$HOME", home), home)
    if not os.path.isabs(p):
        if cwd is None:
            return ""
        p = os.path.join(cwd, p)
    comps = p.split("/")
    k = next((i for i, c in enumerate(comps) if GLOB_CHARS.search(c)), len(comps))
    base = _physical(os.path.normpath("/".join(comps[:k]) or "/"), aliases)
    pats = [c for c in comps[k:] if c]
    if pr.inside(base):
        return "in"
    if not pr.ancestor(base):
        return ""
    if any("**" in c for c in pats):
        return "in" if pr.name in pats else "rec"
    rel = os.path.relpath(pr.phys, base).split("/")
    for i, c in enumerate(pats):
        if i >= len(rel):
            break
        if not fnmatch.fnmatchcase(rel[i], c):
            return ""
    if len(pats) < len(rel):
        return "anc"
    if path_only and len(pats) == len(rel):
        return ""
    literal = base == os.path.dirname(pr.phys) or pats[len(rel) - 1] == rel[-1]
    return "in" if literal else "wild"


def _word_target(v: str, cwd: str | None, pr: "Protected", home: str, aliases) -> str:
    """語 v (path として読む) の行き先: in / wild / rec / anc / 空 (_glob_target と同じ)。"""
    if not v or v.startswith("-") or _unresolved(v, home):
        return ""
    if GLOB_CHARS.search(v):
        return _glob_target(v, cwd, pr, home, aliases)
    if cwd is None and not (v.startswith("/") or v.startswith("~")):
        return ""
    rp = _resolve(v, cwd or "/", home, aliases)
    if pr.inside(rp):
        if re.search(r"\s", rp[len(pr.phys):]):  # D の後ろに空白 = path でなく文 (「<path> を直した」)
            return ""
        return "in"
    if pr.ancestor(rp):
        return "anc"
    return ""


def _gi_covers(g: str, comps: list[str], fold: bool = False) -> bool:
    """gitignore 風の除外 pattern g (rg -g '!…' / fd -E / Grep の glob) が D の中身を除くか。
    comps = 起点から D までの名前の列。 斜線を含まない pattern は途中のどの名前にも当たる、 含むものは起点からの path に当てる。"""
    g2 = g.strip().strip("/")
    if not g2:
        return False
    if fold:
        g2 = g2.lower()
        comps = [c.lower() for c in comps]
    if "/" not in g2:
        return any(fnmatch.fnmatchcase(c, g2) for c in comps)
    cands = ["/".join(comps[:k]) for k in range(1, len(comps) + 1)] + ["/".join(comps) + "/x"]
    return any(fnmatch.fnmatchcase(c, g2) or fnmatch.fnmatchcase("/" + c, g2) for c in cands)


def _exclusions(fam: str, args: list[str]) -> tuple[list[tuple[str, str]], set[int]]:
    """除外の書き方 = ([(種類, pattern)], pattern を書いた語の位置)。 位置は名指しの判定から外す
    (除く対象として D を書いた語は中に入る意図ではない)。 種類: comp (途中のどの名前に当ててもよい) / gi (gitignore 風) /
    find-prune-name / find-prune-path / find-neg-path / find-name (除外でない) / tar / zip。"""
    pats: list[tuple[str, str]] = []
    idx: set[int] = set()

    def vals(names: set[str]):
        for i, a in enumerate(args):
            name, eq, val = a.partition("=")
            if name in names:
                if eq:
                    idx.add(i)
                    yield i, val
                elif i + 1 < len(args):
                    idx.add(i + 1)
                    yield i + 1, args[i + 1]

    if fam == "find":
        for i, a in enumerate(args):
            if a in FIND_MATCH and i + 1 < len(args):
                idx.add(i + 1)
                window = []
                for t in args[i + 2:i + 7]:
                    if t in ("-o", "-or", ","):
                        break
                    window.append(t)
                pruned = "-prune" in window
                negated = i > 0 and args[i - 1] in ("-not", "!")
                fold = "i" if a.startswith("-i") else ""
                is_name = a.endswith("name")
                if pruned:
                    pats.append(((f"find-prune-name{fold}" if is_name else f"find-prune-path{fold}"), args[i + 1]))
                elif negated and not is_name:
                    pats.append((f"find-neg-path{fold}", args[i + 1]))
    elif fam == "grep":
        pats += [("comp", v) for _, v in vals({"--exclude-dir"})]
        list(vals({"--exclude", "--include"}))
    elif fam == "rg":
        for _, v in vals({"-g", "--glob"}):
            if v.startswith("!"):
                pats.append(("gi", v[1:]))
        for _, v in vals({"--iglob"}):
            if v.startswith("!"):
                pats.append(("gii", v[1:]))
    elif fam == "fd":
        pats += [("gi", v) for _, v in vals({"-E", "--exclude"})]
    elif fam == "ag":
        pats += [("comp", v) for _, v in vals({"--ignore", "--ignore-dir"})]
    elif fam == "ack":
        pats += [("comp", v) for _, v in vals({"--ignore-dir", "--ignore-directory"})]
    elif fam == "tar":
        pats += [("tar", v) for _, v in vals({"--exclude"})]
    elif fam == "rsync":
        pats += [("gi", v) for _, v in vals({"--exclude"})]
        list(vals({"--include"}))
    elif fam == "du":
        pats += [("comp", v) for _, v in vals({"--exclude", "-I"})]
    elif fam == "tree":
        for _, v in vals({"-I"}):
            pats += [("comp", x) for x in v.split("|") if x]
    elif fam == "ls":
        pats += [("comp", v) for _, v in vals({"--ignore", "--hide"})]
    elif fam == "zip":
        i = 0
        while i < len(args):
            if args[i] in ("-x", "-i"):
                excl = args[i] == "-x"
                i += 1
                while i < len(args) and not args[i].startswith("-"):
                    idx.add(i)
                    if excl:
                        pats.append(("zip", args[i]))
                    i += 1
                continue
            i += 1
    return pats, idx


def _excl_covers(pats: list[tuple[str, str]], start_word: str, start_phys: str, pr: "Protected", home: str) -> bool:
    """除外の pattern のどれかが、 起点 start から D の中身を除くか (D の dir そのものだけを除く形は数えない)。"""
    rel = os.path.relpath(pr.phys, start_phys)
    comps = rel.split("/")
    shown = _expand(start_word.replace("${HOME}", home).replace("$HOME", home), home).rstrip("/") or ""
    sample_dir = (shown or ".") + "/" + rel if shown != "/" else "/" + rel
    prefixes = [(shown or ".") + "/" + "/".join(comps[:k]) for k in range(1, len(comps) + 1)]
    for kind, pat in pats:
        p = _expand(pat.replace("${HOME}", home).replace("$HOME", home), home)
        fold = kind.endswith("i") and kind.startswith("find")
        f = (lambda s, q: fnmatch.fnmatchcase(s.lower(), q.lower())) if fold else fnmatch.fnmatchcase
        if kind.startswith("find-prune-name"):
            if any(f(c, p) for c in comps):
                return True
        elif kind.startswith("find-prune-path"):
            if any(f(x, p) for x in prefixes) or f(sample_dir + "/x", p):
                return True
        elif kind.startswith("find-neg-path"):
            if f(sample_dir + "/x", p):
                return True
        elif kind == "comp":
            if any(fnmatch.fnmatchcase(c, p.strip("/")) for c in comps):
                return True
        elif kind in ("gi", "gii"):
            if _gi_covers(p, comps, fold=(kind == "gii")):
                return True
        elif kind == "tar":
            q = p.strip("/")
            if any(fnmatch.fnmatchcase(c, q) for c in comps) or fnmatch.fnmatchcase(rel, "*" + q) \
                    or fnmatch.fnmatchcase(rel + "/x", q) or fnmatch.fnmatchcase(rel + "/x", "*/" + q):
                return True
        elif kind == "zip":
            stored = (start_word.lstrip("./").lstrip("/") + "/" if start_word not in (".", "./") else "") + rel
            stored_abs = sample_dir.lstrip("/")
            if any(fnmatch.fnmatchcase(s + "/x", p) for s in (stored, stored_abs)):
                return True
    return False


def _code_names(text: str, pr: "Protected") -> bool:
    """code (python の -c・heredoc の本文) が D の path を書くか。 文 (「<path> を直した」) は数えない =
    D の path の直後が空白でない (`/` か引用符で続く) か、 `P/B` が引用符・括弧の直後に来るときだけ。"""
    for m in pr.path_re.finditer(text):
        if not re.search(r"\s", text[m.end():m.end() + 1] or "x"):
            return True
    return bool(re.search(r"['\"(]" + re.escape(pr.parent_name + "/" + pr.name) + BOUND_END, text))


def _py_code(args: list[str], body: str) -> str:
    code = body or ""
    if "-c" in args:
        i = args.index("-c")
        if i + 1 < len(args):
            code = args[i + 1] + "\n" + code
    return code


def _bash_decision(cmd: str, ncwd: str, pr: "Protected", home: str, aliases, depth: int = 0) -> tuple[str, str]:
    """1 つの保護 dir について (kind, 理由)。 止める判定を先に返す。"""
    segs = _simple_commands(cmd)
    eff_cwd: str | None = ncwd
    named = False
    vars_: dict[str, list[str] | None] = {}   # 同じ command の for・代入で決まる変数の値 (None = 読めない)
    sources: list[tuple[str, str | None]] = []  # 値の読めない起点の源になりうる語 (for の並び・代入・echo の引数)
    unknown_tool = ""   # 起点が読めない (定義の無い変数・$()・xargs) 再帰の道具
    unknown_src: list[tuple[str, str | None]] | None = []  # その起点の源の候補 (xargs = 前の片、 None = 最後まで集めた sources 全部)
    prev: list[str] | None = None
    for words, body, sep in segs:
        feeder = prev if sep == "|" else None
        prev = words
        # for の並び・代入を記録する (起点の変数を値で読むため)
        if len(words) >= 3 and words[0] == "for" and words[2] == "in":
            vals = []
            for x in words[3:]:
                c = _subst(x, vars_, home)
                if c is None:
                    vals = None
                    break
                vals += c
            vars_[words[1]] = vals
            sources += [(x, eff_cwd) for x in words[3:]]
        elif words and words[0] in ("read",):
            for x in words[1:]:
                if not x.startswith("-"):
                    vars_[x] = None
        head = words[1:] if words and words[0] in ("export", "local", "declare", "typeset", "readonly") else words
        for wd in head:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", wd)
            if not m:
                break
            val = m.group(2)
            vars_[m.group(1)] = None if val in ("", "$") else _subst(val, vars_, home)
            sources.append((val, eff_cwd))
        w, fed = _strip_prefix(words)
        off = len(words) - len(w)
        w0 = os.path.basename(w[0]) if w else ""
        fam = _fam(w0)
        args = w[1:]
        excl, excl_idx = _exclusions(fam, args) if w else ([], set())
        skip: set[int] = {off + 1 + i for i in excl_idx}  # words の位置
        # 文 (commit message・echo の引数・grep の検索語) は path として数えない
        for i, a in enumerate(args):
            nm = a.partition("=")[0]
            if nm in MESSAGE_OPTS:
                skip.add(off + 1 + i if "=" in a else off + 2 + i)
        if fam in TEXT_ONLY:
            after_redirect = False
            for i, a in enumerate(args):
                if a in REDIRECTS:
                    after_redirect = True
                    continue
                if not after_redirect:
                    skip.add(off + 1 + i)
                    sources.append((a, eff_cwd))
                after_redirect = False
        if fam in PATTERN_FIRST and fam != "fd":
            pos = [i for i, a in enumerate(args) if not a.startswith("-")]
            explicit = any(a in ("-e", "--regexp", "-f", "--file") for a in args)
            if pos and not explicit:
                skip.add(off + 1 + pos[0])
        # 名指し (語ごと)
        for j, wd in enumerate(words):
            if j in skip:
                continue
            vals = [wd]
            if "=" in wd and (not wd.startswith("-") or wd.startswith("--")):
                vals.append(wd.split("=", 1)[1])
            for v in vals:
                cands = _subst(v, vars_, home) if "$" in v else [v]
                for c in cands or []:
                    t = _word_target(c, eff_cwd, pr, home, aliases)
                    if t == "rec":
                        return STOP, f"`**` の glob が保護 dir「{pr.name}」 を含む上位 dir から辿る ({v})"
                    if t == "wild":
                        return STOP, f"glob ({v}) が保護 dir「{pr.name}」 の名を書かずにその中まで広がる"
                    if t == "in":
                        named = True
                    elif not re.search(r"\s", c) and (pr.path_re.search(c) or pr.pb_re.search(c)):
                        named = True  # 引用符の中の code (python -c の open(…) など) に D の path を書く
                    elif re.search(r"\s", c) and _code_names(c, pr):
                        named = True  # 空白を含む語 (python -c の code など) の中の D の path
        if not w:
            continue
        if w0 in ("cd", "pushd"):
            tgt = next((a for a in args if not a.startswith("-")), "~")
            cands = _subst(tgt, vars_, home)
            if cands is None or len(cands) != 1 or GLOB_CHARS.search(cands[0]) \
                    or (eff_cwd is None and not cands[0].startswith(("/", "~"))):
                eff_cwd = None
                if cands:
                    sources += [(c, None) for c in cands]
            else:
                eff_cwd = _resolve(cands[0], eff_cwd or "/", home, aliases)
                if pr.inside(eff_cwd):
                    named = True
            continue
        if w0 in SHELLS or w0 == "eval":
            inner = ""
            if w0 == "eval":
                inner = " ".join(args)
            elif "-c" in args and args.index("-c") + 1 < len(args):
                inner = args[args.index("-c") + 1]
            elif body:
                inner = body
            if inner and depth < 4:
                k, r = _bash_decision(inner, eff_cwd or ncwd, pr, home, aliases, depth + 1)
                if k == STOP:
                    return k, r
                if k == ASK:
                    named = True
            continue
        if PY_EXE_RE.match(w0):
            code = _py_code(args, body)
            if body and _code_names(body, pr):
                named = True  # python に流す heredoc の本文が D の path を書く (open(…) など)
            if PY_WALK_RE.search(code):
                reach = pr.anc_home_re.search(code) or HOME_FN_RE.search(code) or any(
                    _word_target(a, eff_cwd, pr, home, aliases) == "anc" for a in args if not a.startswith("-"))
                excluded = pr.name in code and re.search(r"\[:\]\s*=", code)
                if reach and not excluded:
                    return STOP, f"python の走査 (os.walk / rglob / copytree) が保護 dir「{pr.name}」 を含む上位 dir から辿る"
            continue
        if w0 in INDEX_TOOLS:
            if w0 == "mdfind" and "-onlyin" in args:
                i = args.index("-onlyin")
                tgt = args[i + 1] if i + 1 < len(args) else "."
                cands = _subst(tgt, vars_, home)
                if cands is None:
                    unknown_tool, unknown_src = w0, None
                    continue
                rps = [_resolve(c, eff_cwd or ncwd, home, aliases) for c in cands]
                if all(not pr.ancestor(rp) or pr.inside(rp) for rp in rps):
                    continue
            return STOP, f"{w0} が保護 dir「{pr.name}」 を含む範囲の索引を引く"
        if not _is_recursive(fam, w0, args):
            continue
        starts, sbase = _starts(fam, w0, args)
        if fed:
            unknown_tool = w0
            unknown_src = [(x, eff_cwd) for x in (feeder[1:] if feeder else []) if not x.startswith("-")] \
                or ([(".", eff_cwd)] if feeder else None)
        if not starts and fam not in ("tar", "zip", "rsync", "cp", "scp", "ditto") and not fed:
            starts = ["."]
        base = eff_cwd
        if sbase is not None:
            bc = _subst(sbase, vars_, home)
            base = None if bc is None or len(bc) != 1 or (eff_cwd is None and not bc[0].startswith(("/", "~"))) \
                else _resolve(bc[0], eff_cwd or "/", home, aliases)
        anc_starts: list[tuple[str, str]] = []
        for s0 in starts:
            cands = _subst(s0, vars_, home)
            if cands is None:
                unknown_tool, unknown_src = w0, None
                continue
            for s in cands:
                if base is None and not s.startswith(("/", "~")):
                    unknown_tool, unknown_src = w0, None
                    continue
                if GLOB_CHARS.search(s):
                    t = _glob_target(s, base, pr, home, aliases)
                    if t == "in":
                        named = True
                    elif t in ("wild", "rec"):
                        return STOP, f"{w0} の起点の glob ({s0}) が保護 dir「{pr.name}」 の中まで広がる"
                    elif t == "anc":
                        p = _resolve(s, base or "/", home, aliases)
                        comps = p.split("/")
                        k = next(i for i, c in enumerate(comps) if GLOB_CHARS.search(c))
                        lit = _physical(os.path.normpath("/".join(comps[:k]) or "/"), aliases)
                        rel = os.path.relpath(pr.phys, lit).split("/")
                        depth_n = len([c for c in comps[k:] if c])
                        anc = os.path.join(lit, *rel[:depth_n])
                        anc_starts.append((anc, anc))
                    continue
                rp = _resolve(s, base or "/", home, aliases)
                if pr.inside(rp):
                    named = True
                elif pr.ancestor(rp):
                    anc_starts.append((s, rp))
        for sw, sp in anc_starts:
            if not _excl_covers(excl, sw, sp, pr, home):
                return STOP, f"{w0} が保護 dir「{pr.name}」 を含む上位 dir ({sw}) から再帰して辿る"
    if unknown_tool:
        for src, c in (sources if unknown_src is None else unknown_src):
            for x in (_subst(src, vars_, home) or []):
                if _word_target(x, c, pr, home, aliases) in ("anc", "in", "wild", "rec") or (
                        c is not None and x in (".", "./") and pr.ancestor(c)):
                    return STOP, (f"{unknown_tool} の起点が変数・$()・xargs で渡され (届く先を command から読めない)、 "
                                  f"その源に保護 dir「{pr.name}」 を含む上位 dir の path がある")
    if named:
        return ASK, f"command が保護 dir「{pr.name}」 の path を書いている"
    if pr.inside(ncwd):
        return ASK, f"cwd が保護 dir「{pr.name}」 の中"
    return "", ""


def decide(payload: dict, home: str | None = None) -> str:
    """確認を出すか止める理由 (空 = 何もしない)。"""
    return _decide(payload, home)[1]


FILE_TOOLS = ("Read", "Edit", "Write", "NotebookEdit")
GUARDED_TOOLS = ("Bash", "Grep", "Glob") + FILE_TOOLS


def _decide(payload: dict, home: str | None = None) -> tuple[str, str, str]:
    """(kind = ask / stop / 空, 理由, 当たった保護 dir の実体 path)。 止める判定を確認より先に返す。"""
    home = home or _home()
    dirs = load_dirs(home)
    if not dirs:
        return "", "", ""
    tool = payload.get("tool_name") or ""
    if tool not in GUARDED_TOOLS:
        return "", "", ""
    ti = payload.get("tool_input") or {}
    aliases = _aliases(home)
    cwd = payload.get("cwd") or os.getcwd()
    ncwd = _norm(cwd, "/", home, aliases)
    asked: tuple[str, str, str] = ("", "", "")
    for d in dirs:
        pr = Protected(d, home, aliases)
        kind, reason = "", ""
        if tool == "Bash":
            cmd = ti.get("command") or ""
            if not cmd:
                return "", "", ""
            kind, reason = _bash_decision(cmd, ncwd, pr, home, aliases)
        elif tool in FILE_TOOLS:
            fp = ti.get("file_path") or ti.get("notebook_path") or ""
            if fp and pr.inside(_norm(fp, cwd, home, aliases)):
                kind, reason = ASK, f"{tool} の file が保護 dir「{pr.name}」 の中"
        elif tool == "Glob":
            base = ti.get("path") or cwd
            pat = ti.get("pattern") or ""
            if pat:
                word = pat if pat.startswith(("/", "~")) else os.path.join(base, pat)
                if GLOB_CHARS.search(word):
                    t = _glob_target(word, ncwd, pr, home, aliases, path_only=True)
                else:
                    t = "in" if pr.inside(_norm(word, cwd, home, aliases)) else ""
                if t == "in":
                    kind, reason = ASK, f"Glob の pattern が保護 dir「{pr.name}」 を名指す"
                elif t in ("rec", "wild"):
                    kind, reason = STOP, f"Glob の pattern が保護 dir「{pr.name}」 を含む上位 dir から中まで辿る"
            else:
                nb = _norm(base, cwd, home, aliases)
                if pr.inside(nb):
                    kind, reason = ASK, f"Glob の起点が保護 dir「{pr.name}」 の中"
        else:  # Grep (ripgrep = 起点から再帰)
            nb = _norm(ti.get("path") or cwd, cwd, home, aliases)
            g = ti.get("glob") or ""
            if pr.inside(nb):
                kind, reason = ASK, f"Grep の起点が保護 dir「{pr.name}」 の中"
            elif pr.ancestor(nb):
                comps = os.path.relpath(pr.phys, nb).split("/")
                if g.startswith("!") and _gi_covers(g[1:], comps):
                    pass
                elif g and not g.startswith("!") and pr.name in re.split(r"[/{},]", g):
                    kind, reason = ASK, f"Grep の glob が保護 dir「{pr.name}」 を名指す"
                else:
                    kind, reason = STOP, f"Grep の起点が保護 dir「{pr.name}」 を含む上位 dir (再帰で中に届く)"
        if kind == STOP:
            return STOP, reason, pr.phys
        if kind == ASK and not asked[0]:
            asked = (ASK, reason, pr.phys)
    return asked


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    home = _home()
    sid = payload.get("session_id") or ""
    if (payload.get("hook_event_name") or "") == "PostToolUse" and sid:
        # 既に全 dir を許可済なら判定まで行かない (= 中で作業している session の毎 call の無駄を省く)
        try:
            with open(_unlock_file(home, sid), encoding="utf-8") as fh:
                done = {line.strip() for line in fh if line.strip()}
            if done and all(
                os.path.join(os.path.realpath(os.path.dirname(d)), os.path.basename(d)) in done
                for d in load_dirs(home)
            ):
                return 0
        except OSError:
            pass
    try:
        kind, reason, phys = _decide(payload, home)
    except Exception:  # noqa: BLE001  fail-open: guard の不調で作業を止めない (効いているかは --canary が見る)
        return 0
    if not kind:
        return 0
    if (payload.get("hook_event_name") or "") == "PostToolUse":
        # ここに来た = tool が実際に走った = user が許可した。 以後この session では聞かない。
        # 開くのは確認 (名指し・cwd が中) を許可したときだけ = 上位 dir からの走査は止める側なので開かない
        if kind == ASK:
            record_unlock(home, sid, phys)
        return 0
    if kind == STOP:
        # 本人に確認を出さず、 理由と直し方を Claude に返す (exit 2 の stderr は tool 結果として届く)。
        # 「以後は通す」 の session でも止める (開いたのは中の作業のためで、 上位からの走査のためではない)
        name = os.path.basename(phys)
        tool = payload.get("tool_name") or ""
        if tool == "Grep":
            fix = ("  - Grep の path をその dir の外の具体的な dir に絞る (例 ~/Dropbox でなく ~/Dropbox/<探す先>)\n"
                   f"  - または glob に '!**/{name}/**' を入れて保護 dir を除く (除いた呼び出しは通る)\n")
        elif tool == "Glob":
            fix = ("  - pattern の起点をその dir の外の具体的な dir に絞る (上位 dir から ** や */*/… を使わない)\n"
                   "  - 探す dir が決まっているなら、 その dir を path に書く\n")
        else:
            fix = ("  - 起点をその dir の外の具体的な dir に絞る (例 ~/Dropbox でなく ~/Dropbox/<探す先>)\n"
                   f"  - または保護 dir の中身を除く: find … -path '*/{name}' -prune -o … -print / grep -r --exclude-dir={name} … /\n"
                   f"    rg -g '!**/{name}/**' … / mdfind -onlyin <具体的な dir> … (除外を書いた command は通る。\n"
                   f"    -not -name {name}・grep の --exclude={name} は dir しか除かないので通らない)\n"
                   "  - 起点を変数・$()・xargs で渡したなら、 具体的な path を書いて打ち直す\n"
                   "  - python の走査なら、 起点を具体的な dir にするか、 dirs[:] で保護 dir を除く\n")
        sys.stderr.write(
            f"🔒 protected-dir-access-guard: 止めました (本人への確認は出していません)。 {reason}\n"
            "  上位 dir から再帰すると保護 dir の中に届くので、 形を直して打ち直してください:\n"
            + fix +
            "  保護 dir の中で作業する依頼なら、 その dir の path を名指して打ち直す (本人に確認が出る)。\n"
            "  規約: claude-config/conventions/confidential-repo-boundary.md#protected-dir-access-guard\n"
        )
        return 2
    if is_unlocked(home, sid, phys):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": f"この session では既に許可済み ({os.path.basename(phys)})",
        }}, ensure_ascii=False))
        return 0
    sys.stderr.write(
        "🔒 protected-dir-access-guard: 保護を宣言した dir に触れます\n"
        f"  理由: {reason}\n"
        "  意図せず当たったなら: 対象をその dir の外の具体的な dir に絞って出し直す。\n"
        "  その dir の作業 session で意図して触るなら: user が許可する (= 許可したら、 この session では\n"
        "  その dir について以後聞かない。 session をまたいでは開かない)。\n"
        "  規約: claude-config/conventions/confidential-repo-boundary.md#protected-dir-access-guard\n"
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask"}}, ensure_ascii=False))
    return 0


def canary() -> int:
    home = _home()
    dirs = load_dirs(home)
    if not dirs:
        print("未配線: protected-dir-access-guard (保護 dir の宣言が無い = ~/.claude/protected-dirs.txt / "
              "leak-pattern-sources.txt。 守りたい dir が在るなら宣言するまで guard は走らない)")
        return 0
    present = [d for d in dirs if os.path.isdir(os.path.dirname(d))]
    if not present:
        print(f"対象外: protected-dir-access-guard (宣言した {len(dirs)} dir の親がこのマシンに無い)")
        return 0
    settings = os.path.join(home, ".claude", "settings.json")
    try:
        with open(settings, encoding="utf-8") as fh:
            conf = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"NOT ARMED: protected-dir-access-guard (settings.json が読めない: {e})")
        return 1
    if conf.get("disableAllHooks") is True:
        print("NOT ARMED: protected-dir-access-guard (settings.json に disableAllHooks: true)")
        return 1
    hook = ""
    wired = set()
    for ent in (conf.get("hooks") or {}).get("PreToolUse") or []:
        for h in ent.get("hooks") or []:
            c = h.get("command", "")
            if HOOK_NAME in c:
                hook = os.path.expanduser(c.split()[0].replace("~", home, 1))
                for t in ("Bash", "Grep", "Glob", "Read", "Edit", "Write"):
                    try:
                        if re.fullmatch(ent.get("matcher", ""), t):
                            wired.add(t)
                    except re.error:
                        pass
    post_wired = False
    for ent in (conf.get("hooks") or {}).get("PostToolUse") or []:
        for h in ent.get("hooks") or []:
            if HOOK_NAME in h.get("command", ""):
                try:
                    post_wired = bool(re.fullmatch(ent.get("matcher", ""), "Bash"))
                except re.error:
                    post_wired = False
    missing = {"Bash", "Grep", "Glob", "Read", "Edit", "Write"} - wired
    if missing:
        print(f"NOT ARMED: protected-dir-access-guard (settings.json の PreToolUse に {'/'.join(sorted(missing))} の "
              "entry が無い → claude-config/scripts/sync-hook-settings.sh)")
        return 1
    if not (os.path.isfile(hook) and os.access(hook, os.X_OK)):
        print(f"NOT ARMED: protected-dir-access-guard (install 済み hook が無い / 実行不可: {hook})")
        return 1

    def run(tool: str, tool_input: dict, cwd: str) -> str:
        """install 済み hook の判定 = ask / stop / none (動かせなければ error)。"""
        data = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": cwd})
        try:
            p = subprocess.run([hook], input=data, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return "error"
        if p.returncode == 2:
            return "stop"
        return "ask" if '"permissionDecision": "ask"' in p.stdout else "none"

    bad = []
    for d in present:
        name = os.path.basename(d)
        if run("Bash", {"command": f'ls "{d}"'}, "/") != "ask":
            bad.append(f"{name}: Bash の名指しに確認が出ない")
        if run("Grep", {"pattern": "x", "path": os.path.dirname(d)}, "/") != "stop":
            bad.append(f"{name}: 親 dir を起点の Grep が止まらない")
        if run("Bash", {"command": f'find "{os.path.dirname(d)}" -name x'}, "/") != "stop":
            bad.append(f"{name}: 親 dir からの find が止まらない")
        if run("Read", {"file_path": os.path.join(d, "x.txt")}, "/") != "ask":
            bad.append(f"{name}: 中の file の Read に確認が出ない")
        if run("Bash", {"command": "ls /"}, "/") != "none":
            bad.append(f"{name}: 無関係な command に確認が出る")
    if bad:
        print("NOT ARMED: protected-dir-access-guard (" + " / ".join(bad) + ")")
        return 1
    note = "" if post_wired else (
        " ⚠️ session 内の 1 回限り許可は未配線 (= 毎回聞かれる。 PostToolUse の entry が無い "
        "→ claude-config/scripts/sync-hook-settings.sh)")
    print(f"ARMED: protected-dir-access-guard ({len(present)} dir、 Bash / Grep / Glob / Read / Edit / Write)" + note)
    return 0


if __name__ == "__main__":
    if "--canary" in sys.argv:
        sys.exit(canary())
    sys.exit(main())
