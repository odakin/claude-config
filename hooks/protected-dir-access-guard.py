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

判定 (保護 dir D、 その親 dir の名前 P、 D の名前 B)。 Bash の command は単純 command (改行・; & | ( ) で割った 1 片) ごとに
shlex で語に分けて読む = 引用符の中の `/` (awk の "/"・sed の s/…/…/)・文の中の語 (commit message の tree / find) は数えない:
  確認を出す (ask = 本人が dialog の文字から「中に入る」 と読める)
    (a) 片が D の path を書く (実体 path / home 直下 symlink 経由の別名 / `~` / `$HOME` 形) か `P/B` を書く、
        または `P/` の直後に glob を書く。 再帰の道具の起点が D の中
    (c) cwd が D の中
    (e) cwd が D の親 dir で、 command が B を語として書くか glob を使う
    (f) Grep / Glob の起点 (path、 無ければ cwd。 Glob は pattern の literal 部分を足す) が D の中、 または Glob の pattern が `P/B` を含む
    (g) Read / Edit / Write の file_path が D の中
  止める (stop = exit 2、 理由と直し方を Claude に返す。 本人には何も出さない)
    (b) 片の先頭の語が再帰の道具 (find / grep -r / rg / fd / ag / ack / du / tree / ls -R / rsync / tar / zip / cp -r) で、
        その起点の引数 (grep・rg などの検索語は除く。 引数が無ければ cwd、 直前の片の `cd` の行き先を足す) が D の上位 dir
    (b') mdfind (`-onlyin` が D の上位 dir か無い) / locate = 全体の索引を引く
    (b'') zsh の再帰 glob (`<上位 dir>/**/…`)、 python の走査 (os.walk / rglob / recursive=True) と上位 dir の path
         (`/` 1 文字と `/Users` は数えない) が同じ command にある
    (f') Grep / Glob の起点が D の上位 dir
  何もしない: B を含む文 (commit message・規約の grep)、 再帰しない一覧 (`ls <親>`)、 D の外の具体的な dir への再帰、
    **D を除く書き方を添えた片** (`-prune` / `--exclude-dir` / `-not -path` / rg・fd の `-g '!…'` / `--ignore` の近くに B)、 他の tool。
  ⚠️ 射程外 = 変数に分けて組み立てた path (`find "$r"`)、 script file の中の走査 (目的は事故の防止)。
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

# 単純 command (改行・; & | ( ) で割った 1 片) の先頭に来る、 再帰の道具でない前置きの語
PREFIX_WORDS = {"sudo", "time", "nice", "nohup", "command", "builtin", "exec", "then", "do", "else", "elif",
                "if", "while", "until", "{", "}", "!"}
RECURSE_ALWAYS = {"find", "gfind", "rg", "fd", "ag", "ack", "du", "tree", "rsync", "tar", "zip"}
PATTERN_FIRST = {"grep", "egrep", "fgrep", "ggrep", "rg", "ag", "ack", "fd"}  # 最初の位置引数は検索語 (path でない)
INDEX_TOOLS = {"mdfind", "locate"}  # 起点を書かなくても全体の索引を引く
PY_WALK_RE = re.compile(r"os\.walk\(|\.rglob\(|recursive\s*=\s*True")
# 保護 dir を除く書き方 (この語の近くに保護 dir の名前があれば、 その片は除外つき = 通す)
EXCL_RE = re.compile(
    r"-prune\b|--exclude(?:-dir)?(?:=|\s)|(?:-not|!)\s+-(?:i?path|i?wholename|i?name)\b"
    r"|--glob(?:=|\s)!|(?<![\w-])-g\s*!|--ignore(?:-dir)?(?:=|\s)|(?<![\w-])-x\s"
)
EXCL_NEAR = 60  # 除外の語と保護 dir の名前の距離 (文字)


def _simple_commands(cmd: str) -> list[list[str]]:
    """command を単純 command ごとの語の列に分ける (行ごとに shlex。 引用符の中の ; | / は割らない、 # 以降は捨てる)。"""
    out: list[list[str]] = []
    for line in cmd.split("\n"):
        try:
            lx = shlex.shlex(line, posix=True, punctuation_chars=True)
            lx.whitespace_split = True
            toks = list(lx)
        except ValueError:  # 閉じない引用符 (heredoc の本文の python など) = 空白で割るだけ
            toks = line.split()
        cur: list[str] = []
        for t in toks:
            if t and set(t) <= set(";&|()"):
                if cur:
                    out.append(cur)
                cur = []
            else:
                cur.append(t)
        if cur:
            out.append(cur)
    return out


def _strip_prefix(words: list[str]) -> list[str]:
    """環境変数の代入・sudo / time / timeout N / xargs の option などの前置きを外す。"""
    w = list(words)
    while w:
        h = w[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", h) or h in PREFIX_WORDS:
            w = w[1:]
        elif h in ("timeout", "gtimeout"):
            w = w[1:]
            while w and (w[0].startswith("-") or re.match(r"^\d+[smhd]?$", w[0])):
                w = w[1:]
        elif h == "env":
            w = w[1:]
            while w and (w[0].startswith("-") or "=" in w[0]):
                w = w[1:]
        elif h == "xargs":
            w = w[1:]
            while w and w[0].startswith("-"):
                takes = w[0] in ("-n", "-I", "-P", "-L", "-s", "-d", "-E")
                w = w[2:] if takes else w[1:]
        else:
            break
    return w


def _is_recursive(w0: str, args: list[str]) -> bool:
    if w0 in RECURSE_ALWAYS:
        return True
    shorts = "".join(a[1:] for a in args if re.match(r"^-[A-Za-z]+$", a))
    if w0 in ("grep", "egrep", "fgrep", "ggrep"):
        return bool(re.search(r"[rR]", shorts)) or "--recursive" in args or "--dereference-recursive" in args \
            or any(a in ("--directories=recurse", "-drecurse") for a in args) or ("-d" in args and "recurse" in args)
    if w0 == "ls":
        return "R" in shorts or "--recursive" in args
    if w0 == "cp":
        return bool(re.search(r"[rRa]", shorts)) or "--recursive" in args
    return False


def _path_args(w0: str, args: list[str]) -> list[str]:
    """再帰の起点になりうる位置引数 (option と、 grep / rg などの検索語を除く。 find は式の手前まで)。"""
    pos: list[str] = []
    skip_value = False
    for a in args:
        if skip_value:
            skip_value = False
            continue
        if w0 in ("find", "gfind") and (a.startswith("-") or a in ("(", "!", ")")):
            break
        if a.startswith("-"):
            # 値を取る option (値が path でない) は値ごと飛ばす
            if a in ("-e", "--regexp", "-f", "--file", "-g", "--glob", "-t", "--type", "-m", "-A", "-B", "-C",
                     "--include", "--exclude", "--exclude-dir", "-L", "-I", "-d", "--max-depth", "-x"):
                skip_value = True
            continue
        pos.append(a)
    if w0 in PATTERN_FIRST and pos and not any(a in ("-e", "--regexp", "-f", "--file") for a in args):
        pos = pos[1:]
    return pos


def _resolve(p: str, cwd: str, home: str, aliases) -> str:
    p = p.replace("${HOME}", home).replace("$HOME", home)
    return _norm(p, cwd, home, aliases)


def _excluded(seg_text: str, pr: "Protected") -> bool:
    for m in EXCL_RE.finditer(seg_text):
        lo, hi = max(0, m.start() - EXCL_NEAR), m.end() + EXCL_NEAR
        if pr.name in seg_text[lo:hi]:
            return True
    return False


def _bash_decision(cmd: str, ncwd: str, pr: "Protected", home: str, aliases) -> tuple[str, str]:
    """1 つの保護 dir について (kind, 理由)。"""
    segs = _simple_commands(cmd)
    eff_cwd = ncwd
    named = False
    for words in segs:
        seg_text = " ".join(words)
        excl = _excluded(seg_text, pr)
        if not excl and (pr.path_re.search(seg_text) or pr.pb_re.search(seg_text) or pr.parent_glob_re.search(seg_text)):
            named = True
        w = _strip_prefix(words)
        if not w:
            continue
        w0 = os.path.basename(w[0])
        args = w[1:]
        if w0 in ("cd", "pushd"):
            tgt = next((a for a in args if not a.startswith("-")), "~")
            eff_cwd = _resolve(tgt, eff_cwd, home, aliases)
            continue
        if excl:
            continue
        if w0 in INDEX_TOOLS:
            if w0 == "mdfind" and "-onlyin" in args:
                i = args.index("-onlyin")
                tgt = _resolve(args[i + 1], eff_cwd, home, aliases) if i + 1 < len(args) else eff_cwd
                if not pr.ancestor(tgt):
                    continue
            return STOP, f"{w0} が保護 dir「{pr.name}」 を含む範囲の索引を引く"
        for a in args:  # zsh の再帰 glob (~/x/**/y)
            if "**/" in a:
                base = a.split("**", 1)[0] or "."
                if pr.ancestor(_resolve(base, eff_cwd, home, aliases)):
                    return STOP, f"`**/` の glob が保護 dir「{pr.name}」 を含む上位 dir から辿る"
        if not _is_recursive(w0, args):
            continue
        starts = _path_args(w0, args)
        if not starts and w0 not in ("tar", "zip", "rsync", "cp"):
            starts = ["."]
        for s in starts:
            rp = _resolve(s, eff_cwd, home, aliases)
            if pr.inside(rp):
                named = True
            elif pr.ancestor(rp):
                return STOP, f"{w0} が保護 dir「{pr.name}」 を含む上位 dir ({s}) から再帰して辿る"
    if PY_WALK_RE.search(cmd) and not _excluded(cmd, pr) and pr.anc_home_re.search(cmd):
        return STOP, f"python の走査 (os.walk / rglob) と、 保護 dir「{pr.name}」 を含む上位 dir の path が同じ command にある"
    if named:
        return ASK, f"command が保護 dir「{pr.name}」 の path を書いている"
    if pr.inside(ncwd):
        return ASK, f"cwd が保護 dir「{pr.name}」 の中"
    if pr.is_parent(ncwd) and (pr.name_word_re.search(cmd) or re.search(r"[*?]", cmd)):
        return ASK, f"cwd が保護 dir「{pr.name}」 の親で、 command がその名前か glob を使う"
    return "", ""


def decide(payload: dict, home: str | None = None) -> str:
    """確認を出すか止める理由 (空 = 何もしない)。"""
    return _decide(payload, home)[1]


def _decide(payload: dict, home: str | None = None) -> tuple[str, str, str]:
    """(kind = ask / stop / 空, 理由, 当たった保護 dir の実体 path)。 止める判定を確認より先に返す。"""
    home = home or _home()
    dirs = load_dirs(home)
    if not dirs:
        return "", "", ""
    tool = payload.get("tool_name") or ""
    if tool not in ("Bash", "Grep", "Glob", "Read", "Edit", "Write"):
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
        elif tool in ("Read", "Edit", "Write"):
            fp = ti.get("file_path") or ti.get("notebook_path") or ""
            if fp and pr.inside(_norm(fp, cwd, home, aliases)):
                kind, reason = ASK, f"{tool} の file が保護 dir「{pr.name}」 の中"
        else:
            base = ti.get("path") or cwd
            pat = ti.get("pattern") or ""
            if tool == "Glob" and pat:
                if pr.pb_re.search(pat):
                    kind, reason = ASK, f"Glob の pattern が保護 dir「{pr.name}」 を名指す"
                lit = re.split(r"[*?\[]", pat, maxsplit=1)[0]
                lit = lit.rsplit("/", 1)[0] if "/" in lit else ""
                if lit:
                    base = lit if (lit.startswith("/") or lit.startswith("~")) else os.path.join(base, lit)
            if not kind:
                nb = _norm(base, cwd, home, aliases)
                if pr.inside(nb):
                    kind, reason = ASK, f"{tool} の起点が保護 dir「{pr.name}」 の中"
                elif pr.ancestor(nb):
                    kind, reason = STOP, f"{tool} の起点が保護 dir「{pr.name}」 を含む上位 dir (再帰で中に届く)"
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
        sys.stderr.write(
            f"🔒 protected-dir-access-guard: 止めました (本人への確認は出していません)。 {reason}\n"
            "  上位 dir から再帰すると保護 dir の中に届くので、 形を直して打ち直してください:\n"
            "  - 起点をその dir の外の具体的な dir に絞る (例 ~/Dropbox でなく ~/Dropbox/<探す先>)\n"
            f"  - または保護 dir を除く: find … -path '*/{name}' -prune -o … -print / grep -r --exclude-dir={name} … /\n"
            f"    rg -g '!**/{name}/**' … / mdfind -onlyin <具体的な dir> … (除外を書いた command は通る)\n"
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
