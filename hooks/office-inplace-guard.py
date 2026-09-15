#!/usr/bin/env python3
"""office-inplace-guard.py — PreToolUse(Bash): Excel / Word / PowerPoint に staging 外の path を開かせる・保存させる command を deny (office-automation.md#office-inplace-guard)

なぜ:
  macOS の Microsoft Office は App Sandbox で、 folder へ書く瞬間に folder ごとの「ファイル アクセスを許可」
  dialog を出す (remote 操作では押せず、 AppleScript には -1712 としてしか見えない)。 正本は
  「Office に触らせる file は事前 grant 済み staging dir (Office の group container) 経由」 だが、 規則が
  文章にしか無いと、 staging 導入前に書かれた案件ごとの driver を写した session が in-place で開き直し、
  dialog が繰り返し出る (実測)。 prompt で言わなくても既定で正しくなるよう、 実行前に止める。

止めるもの (どれも「Office を駆動する」 と読める command に限る):
  1. inline osascript  (`osascript -e '… tell application "Microsoft Excel" … open/save …'`、 heredoc 含む)
     で、 開く/保存する path の literal が staging root の外。
  2. `osascript <file>.applescript|.scpt [argv…]` / `#!/usr/bin/osascript` の直接実行 — script を読んで 1 と同じ判定
     (argv に渡した path も見る。 .scpt は osadecompile で読む)。
  3. `python3 x.py` / `bash|sh|zsh x.sh` / 直接実行 / `python3 -c` / `bash -c` / heredoc — script が Office を
     osascript / appscript / JXA で駆動 (open・save の動詞つき) していて、 staging helper を使っていない
     (python = `from office_staging import …` / `import office_staging`、 shell = `source|. …/office-staging.sh`)。
     script 内の path literal がすべて staging の内側なら通す。
  4. layer-1 wrapper (xlsx-to-pdf.sh / docx-to-pdf.sh / pptx-to-pdf.sh / affix-image-xlsx.py) の `--no-stage`、
     および Office を駆動する command への `CLAUDE_OFFICE_STAGING=0|no|off|false`。

通すもの:
  - layer-1 wrapper そのもの (既定で stage する) / `scripts/office-stage-run.sh` 配下の command
    (`{}` / `{dir}` は staged path として扱う)
  - staging root (`<HOME>/Library/Group Containers/UBF8T346G9.Office/claude-office-staging` と
    `CLAUDE_OFFICE_STAGING_DIR`) の内側の path
  - 明示の例外: script file の中、 または command の中 (末尾 comment 可) に `office-staging: exempt <理由>`
    (理由は必須)
  - 判定できないもの (path が未解決の変数・f-string、 読めない file、 壊れた JSON) = fail-open

射程外 (= 既知の穴): `open -a "Microsoft Excel" <file>` (人が見る用途と区別できない) / import した module の中の駆動 /
  Makefile・npm script 経由 / AppleScript 内で文字列連結した path / 変数に入った path (同じ command 内の代入は解決する)。

出力: permissionDecision=deny + 直し方。 `--selftest` = 述語の回帰、 `--canary` = このマシンの本番配線
  (settings.json の entry + install 済み hook) がカナリアを実際に deny するかを 1 行 (ARMED / NOT ARMED / 対象外)。
opt-out = CLAUDE_OFFICE_INPLACE_GUARD=0。

office-staging: exempt guard 自身の selftest fixture (in-place の例文を含む)
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
LIB = os.path.normpath(os.path.join(HERE, "..", "scripts", "lib"))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

SOT = "claude-config/conventions/office-automation.md#office-inplace-guard"
WRAPPERS = {"xlsx-to-pdf.sh", "docx-to-pdf.sh", "pptx-to-pdf.sh", "affix-image-xlsx.py"}
RUNNER = "office-stage-run.sh"
RUNNER_PATH = os.path.normpath(os.path.join(HERE, "..", "scripts", RUNNER))
MAX_READ = 2 * 1024 * 1024

APPS = r"Microsoft\s+(?:Excel|Word|PowerPoint)"
BUNDLE = r"com\.microsoft\.(?:Excel|Word|Powerpoint)"
Q = r"""\\?["']"""
TELL = re.compile(r"\btell\s+(?:application|app)\s+(?:id\s+)?" + Q + r"(" + APPS + r"|" + BUNDLE + r")", re.I)
OBJ = re.compile(r"(?:\bapp\(\s*(?:name\s*=\s*)?|\bApplication\(\s*|applicationWithBundleIdentifier_?\(\s*)"
                 + Q + r"(" + APPS + r"|" + BUNDLE + r")", re.I)
AS_VERB = re.compile(r"(?<![.\w$])(?:open\s+(?![-=])|save\b(?!\s*[=(])|saving\s+yes\b)", re.I)
OBJ_VERB = re.compile(r"\.(?:open|open_workbook|save|save_as|saveAs|save_workbook_as)\s*\(", re.I)
DOC_EXT = r"\.(?:xlsx|xlsm|xlsb|xls|xltx|csv|docx|docm|doc|dotx|rtf|pptx|pptm|ppt|potx|pdf)"
PATH_KW = re.compile(r"(?:POSIX\s+file|file\s+name|filename|alias|\bfile)\s*\(?\s*" + Q + r"([^\"'\n\\]+)" + Q, re.I)
STR_DOC = re.compile(Q + r"((?:/|~/|\$HOME\b|\$\{HOME\})[^\"'\n\\]*?" + DOC_EXT + r")" + Q, re.I)
HFS_DOC = re.compile(Q + r"([^\"'\n\\/:{}]+:[^\"'\n\\{}]+?" + DOC_EXT + r")" + Q, re.I)
EXEMPT = re.compile(r"office-staging:\s*exempt[ \t]+\S", re.I)
PY_HELPER = re.compile(r"^[ \t]*(?:from[ \t]+office_staging[ \t]+import\b|import[ \t]+office_staging\b)", re.M)
SH_HELPER = re.compile(r"^[ \t]*(?:source|\.)[ \t]+\S*office-staging\.sh\b", re.M)
STAGED_VARS = {"OFFICE_STAGED", "OFFICE_STAGE_DIR"}
DISABLE = re.compile(r"(?:^|[\s;&|(])(?:export\s+)?CLAUDE_OFFICE_STAGING=[\"']?(?:0|no|off|false)\b", re.I | re.M)
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
OSA_WORD = re.compile(r"(?:^|[\n;&|(`]|\$\()[ \t]*(?:[A-Za-z_]\w*=\S*[ \t]+)*(?:(?:exec|time|nohup|command|env)[ \t]+)*"
                      r"(?:\S*/)?osascript\b")
PREFIX_WORDS = {"exec", "time", "nohup", "command", "env", "sudo", "caffeinate"}


# ---------------------------------------------------------------- path helpers
def _lib():
    import office_staging  # noqa: E402  (path は上で追加)
    return office_staging


class Ctx:
    def __init__(self, cwd: str, env: dict, assigns: dict | None = None, runner: bool = False):
        self.cwd = cwd
        self.env = env
        self.assigns = assigns or {}
        self.runner = runner

    def child(self, **kw) -> "Ctx":
        c = Ctx(self.cwd, self.env, dict(self.assigns), self.runner)
        for k, v in kw.items():
            setattr(c, k, v)
        return c


def parse_assigns(text: str) -> dict:
    out: dict = {}
    for m in re.finditer(r"(?:^|[\s;&|(])(?:export\s+)?([A-Za-z_]\w*)=(\"[^\"\n]*\"|'[^'\n]*'|[^\s;&|)]*)", text):
        v = m.group(2)
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[m.group(1)] = v
    return out


def classify(raw: str, ctx: Ctx) -> str:
    """'staged' / 'inplace' / 'unknown'。"""
    s = raw.strip()
    if not s:
        return "unknown"
    if ctx.runner and ("{}" in s or "{dir}" in s):
        return "staged"
    names = re.findall(r"\$\{?(\w+)\}?", s)
    if any(n in STAGED_VARS for n in names):
        return "staged"
    if re.search(r"(?<!\$)\{[^}]*\}", s):          # python の f-string / format placeholder
        return "unknown"
    def sub(m: re.Match) -> str:
        n = m.group(1) or m.group(2)
        if n in ctx.assigns:
            return ctx.assigns[n]
        if n == "HOME":
            return ctx.env.get("HOME", os.path.expanduser("~"))
        if n == "PWD":
            return ctx.cwd
        return m.group(0)
    for _ in range(3):                             # 代入の値にさらに $HOME 等が入る分
        if "$" not in s:
            break
        s = re.sub(r"\$\{(\w+)\}|\$(\w+)", sub, s)
    if "$" in s or "`" in s:
        return "unknown"
    if not s.startswith(("/", "~")) and ":" in s and "/" not in s.split(":", 1)[0]:
        parts = [p for p in s.split(":")[1:]]
        s = "/" + "/".join(parts)                  # HFS path → POSIX (先頭の volume 名を落として ':' を '/' に)
    if s.startswith("~/") or s == "~":
        s = ctx.env.get("HOME", os.path.expanduser("~")) + s[1:]
    if not os.path.isabs(s):
        s = os.path.join(ctx.cwd, s)
    extra = [ctx.assigns["CLAUDE_OFFICE_STAGING_DIR"]] if ctx.assigns.get("CLAUDE_OFFICE_STAGING_DIR") else []
    return "staged" if _lib().is_staged_path(s, ctx.env, extra) else "inplace"


def _pathlike(c: str) -> bool:
    c = c.strip()
    return bool(c) and (c.startswith(("/", "~", "$", "{")) or ":" in c or re.search(DOC_EXT + r"$", c, re.I) is not None)


# ---------------------------------------------------------------- Office drive detection
def _tell_block(text: str, m: re.Match) -> str:
    start = m.start()
    eol = text.find("\n", m.end())
    eol = len(text) if eol < 0 else eol
    if re.match(r"""\\?["']?\s*to\b""", text[m.end():eol]):
        return text[start:eol]
    depth = 1
    for t in re.finditer(r"\bend\s+tell\b|\btell\b", text[m.end():]):
        if t.group(0).lower().startswith("end"):
            depth -= 1
            if depth == 0:
                return text[start:m.end() + t.end()]
        else:
            a = m.end() + t.end()
            line_end = text.find("\n", a)
            line_end = len(text) if line_end < 0 else line_end
            if not re.search(r"\bto\b", text[a:line_end]):
                depth += 1
    return text[start:min(len(text), m.end() + 4000)]


def office_blocks(text: str) -> list[tuple[str, str]]:
    """Office を open/save で駆動している block の list: (app 名, block text)。"""
    out = []
    for m in TELL.finditer(text):
        block = _tell_block(text, m)
        if AS_VERB.search(block[m.end() - m.start():]):
            out.append((m.group(1), block))
    for m in OBJ.finditer(text):
        block = text[max(0, m.start() - 300):m.end() + 2000]
        if OBJ_VERB.search(block) or AS_VERB.search(block[m.end() - max(0, m.start() - 300):]):
            out.append((m.group(1), block))
    return out


def path_candidates(block: str) -> list[str]:
    seen, out = set(), []
    for rx in (PATH_KW, STR_DOC, HFS_DOC):
        for m in rx.finditer(block):
            c = m.group(1).strip()
            if _pathlike(c) and c not in seen:
                seen.add(c)
                out.append(c)
    return out


def _app(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"(?i)^com\.microsoft\.", "Microsoft ", name))


# ---------------------------------------------------------------- checks (return None = ok / str = deny reason)
def check_applescript_text(text: str, ctx: Ctx, argv: list[str] | None = None, where: str = "inline osascript") -> str | None:
    if EXEMPT.search(text):
        return None
    blocks = office_blocks(text)
    if not blocks:
        return None
    for app, block in blocks:
        for c in path_candidates(block):
            if classify(c, ctx) == "inplace":
                return f"{where} が {_app(app)} に staging 外の path を開かせる/保存させる: {c}"
    for a in argv or []:
        if _pathlike(a) and re.search(DOC_EXT + r"$|/$", a, re.I) and classify(a, ctx) == "inplace":
            return f"{where} に staging 外の path を渡している ({_app(blocks[0][0])} を駆動): {a}"
    return None


def check_script_text(text: str, ctx: Ctx, where: str) -> str | None:
    if EXEMPT.search(text):
        return None
    blocks = office_blocks(text)
    if not blocks:
        return None
    if PY_HELPER.search(text) or SH_HELPER.search(text) or "claude-office-staging" in text:
        return None
    cands = [(app, c, classify(c, ctx)) for app, b in blocks for c in path_candidates(b)]
    bad = [(app, c) for app, c, k in cands if k == "inplace"]
    if bad:
        return f"{where} が {_app(bad[0][0])} に staging 外の path を開かせる/保存させる: {bad[0][1]}"
    if ctx.runner:
        return None                                     # office-stage-run.sh が stage 済みの path を渡す
    if cands and all(k == "staged" for _, _, k in cands):
        return None
    return (f"{where} は {_app(blocks[0][0])} を open/save で駆動しているのに staging helper を使っていない "
            f"(= in-place で開く。 staging 導入前の案件 driver を写した形)")


def read_script(path: str) -> str | None:
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_READ:
            return None
        if path.lower().endswith(".scpt"):
            exe = shutil.which("osadecompile")
            if not exe:
                return None
            p = subprocess.run([exe, path], capture_output=True, timeout=5)
            return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None
        with open(path, "rb") as fh:
            data = fh.read()
        if b"\x00" in data[:8192]:
            return None
        return data.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _resolve(tok: str, ctx: Ctx) -> str:
    t = re.sub(r"\$\{?HOME\}?", ctx.env.get("HOME", ""), tok)
    t = os.path.expanduser(t) if t.startswith("~") else t
    return t if os.path.isabs(t) else os.path.join(ctx.cwd, t)


def _is_wrapper(tok: str) -> bool:
    return os.path.basename(tok) in WRAPPERS


def check_segment(tokens: list[str], heredoc: str, ctx: Ctx, cmd_exempt: bool) -> str | None:
    i = 0
    while i < len(tokens) and (re.match(r"^[A-Za-z_]\w*=", tokens[i]) or os.path.basename(tokens[i]) in PREFIX_WORDS
                               or (i > 0 and os.path.basename(tokens[i - 1]) in {"caffeinate", "sudo", "env"} and tokens[i].startswith("-"))):
        i += 1
    tokens = tokens[i:]
    if not tokens:
        return None
    word = os.path.basename(tokens[0])

    if word == RUNNER:
        if "--" in tokens:
            sub = tokens[tokens.index("--") + 1:]
            return check_segment(sub, heredoc, ctx.child(runner=True), cmd_exempt)
        return None

    if word == "cd" and len(tokens) > 1:
        ctx.cwd = _resolve(tokens[1], ctx)
        return None

    # --no-stage (wrapper) — 本体の判定より先 (wrapper は下で通すため)
    if any(_is_wrapper(t) for t in tokens[:3]) and "--no-stage" in tokens and not cmd_exempt:
        return "layer-1 wrapper を --no-stage (= in-place) で呼んでいる"
    if word in WRAPPERS:
        return None

    kind, script, inline, argv = None, None, None, []
    if word == "osascript":
        e_parts, j = [], 1
        while j < len(tokens):
            t = tokens[j]
            if t == "-e" and j + 1 < len(tokens):
                e_parts.append(tokens[j + 1]); j += 2; continue
            if t in ("-l", "-s") and j + 1 < len(tokens):
                j += 2; continue
            if t.startswith("-") and t != "-":
                j += 1; continue
            break
        if e_parts or (j < len(tokens) and tokens[j] == "-") or (j >= len(tokens) and heredoc):
            kind, inline = "as", "\n".join(e_parts) + ("\n" + heredoc if heredoc else "")
            argv = tokens[j + (1 if j < len(tokens) and tokens[j] == "-" else 0):]
        elif j < len(tokens):
            kind, script, argv = "as", tokens[j], tokens[j + 1:]
    elif re.match(r"^(?:python(?:\d+(?:\.\d+)?)?w?|pypy3?)$", word) or (word == "uv" and len(tokens) > 1 and tokens[1] == "run"):
        j = 2 if word == "uv" else 1
        while j < len(tokens):
            t = tokens[j]
            if t == "-c" and j + 1 < len(tokens):
                kind, inline = "py", tokens[j + 1]; break
            if t == "-m":
                return None
            if t == "-":
                kind, inline = "py", heredoc; break
            if t in ("-W", "-X", "--with", "--python") and j + 1 < len(tokens):
                j += 2; continue
            if t.startswith("-"):
                j += 1; continue
            kind, script, argv = "py", t, tokens[j + 1:]; break
        else:
            if heredoc:
                kind, inline = "py", heredoc
    elif word in ("bash", "sh", "zsh", "dash", "ksh"):
        j = 1
        while j < len(tokens):
            t = tokens[j]
            if t == "-c" and j + 1 < len(tokens):
                kind, inline = "sh", tokens[j + 1]; break
            if t in ("-o", "+o") and j + 1 < len(tokens):
                j += 2; continue
            if t.startswith(("-", "+")):
                j += 1; continue
            kind, script, argv = "sh", t, tokens[j + 1:]; break
        else:
            if heredoc:
                kind, inline = "sh", heredoc
    elif re.search(r"\.(?:py|sh|zsh|bash|applescript|scpt)$", tokens[0], re.I):
        ext = tokens[0].rsplit(".", 1)[-1].lower()
        kind = {"py": "py", "applescript": "as", "scpt": "as"}.get(ext, "sh")
        script, argv = tokens[0], tokens[1:]

    if kind is None:
        return None
    if script is not None and _is_wrapper(script):
        return None
    where = "inline script"
    if script is not None:
        path = _resolve(script, ctx)
        inline = read_script(path)
        if inline is None:
            return None
        where = os.path.basename(path)
    if inline is None:
        return None
    if cmd_exempt:
        return None
    if kind == "as":
        return check_applescript_text(inline, ctx, argv, where if script else "inline osascript")
    return check_script_text(inline, ctx, where)


# ---------------------------------------------------------------- command splitting
def _strip_comments(s: str) -> str:
    out, i, q = [], 0, None
    while i < len(s):
        ch = s[i]
        if q:
            out.append(ch)
            if ch == "\\" and q == '"' and i + 1 < len(s):
                out.append(s[i + 1]); i += 2; continue
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch; out.append(ch)
        elif ch == "\\" and i + 1 < len(s):
            out.append(ch); out.append(s[i + 1]); i += 2; continue
        elif ch == "#" and (i == 0 or s[i - 1] in " \t\n;&|("):
            j = s.find("\n", i)
            i = len(s) if j < 0 else j
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def split_segments(cmd: str) -> list[tuple[list[str], str]] | None:
    """(tokens, そこに付いた heredoc 本文) の list。 解析できなければ None。"""
    bodies: list[str] = []

    def keep(m: re.Match) -> str:
        bodies.append(m.group(3))
        return f"<<__HEREDOC_{len(bodies) - 1}__"
    skeleton = _strip_comments(HEREDOC.sub(keep, cmd))
    try:
        lex = shlex.shlex(skeleton, posix=True, punctuation_chars=";&|\n()")
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        lex.commenters = ""
        toks = list(lex)
    except ValueError:
        return None
    segs, cur, docs = [], [], []
    for t in toks + [";"]:
        if t and set(t) <= set(";&|\n()"):
            if cur:
                segs.append((cur, "\n".join(docs)))
            cur, docs = [], []
            continue
        m = re.match(r"^<<__HEREDOC_(\d+)__$", t)
        if m:
            docs.append(bodies[int(m.group(1))])
            continue
        if t in ("<<", "<<-"):
            continue
        cur.append(t)
    return segs


def find_issue(cmd: str, cwd: str, env: dict) -> str | None:
    if not cmd:
        return None
    cmd_exempt = bool(EXEMPT.search(cmd))
    ctx = Ctx(cwd or os.getcwd(), env, parse_assigns(cmd))
    segs = split_segments(cmd)
    if segs is None:
        if OSA_WORD.search(cmd) and not cmd_exempt:
            return check_applescript_text(cmd, ctx)
        return None
    for tokens, heredoc in segs:
        r = check_segment(tokens, heredoc, ctx, cmd_exempt)
        if r:
            return r
    if DISABLE.search(cmd) and not cmd_exempt:
        involved = any(_is_wrapper(t) for toks, _ in segs for t in toks) or bool(office_blocks(cmd)) \
            or "office_staging" in cmd or "office-staging.sh" in cmd
        if not involved:
            for toks, _ in segs:
                for t in toks:
                    if re.search(r"\.(?:py|sh)$", t):
                        txt = read_script(_resolve(t, ctx))
                        if txt and (PY_HELPER.search(txt) or SH_HELPER.search(txt)) and office_blocks(txt):
                            involved = True
        if involved:
            return "CLAUDE_OFFICE_STAGING=0 で staging を切って Office を駆動しようとしている"
    return None


def reason_text(issue: str, env: dict) -> str:
    try:
        root = _lib().staging_roots_for_match(env)[0]
    except Exception:  # noqa: BLE001
        root = "~/Library/Group Containers/UBF8T346G9.Office/claude-office-staging"
    return (
        f"[office-inplace-guard] {issue}。 macOS の Office は folder ごとに「ファイル アクセスを許可」 dialog を出す "
        f"(remote では押せず -1712 で止まる)。 直し方: "
        f"(1) PDF 化 / 画像貼付は layer-1 wrapper (xlsx-to-pdf.sh / docx-to-pdf.sh / pptx-to-pdf.sh / affix-image-xlsx.py) = 既定で staging。 "
        f"(2) 自前の osascript は `{RUNNER_PATH} <file> -- osascript fill.applescript {{}}` "
        f"(`{{}}` = staged copy、 成功時に書き戻し。 出力は `{{dir}}/out.pdf` + `--out out.pdf=<dest>`)。 "
        f"(3) script は helper を使う: python = `from office_staging import Stage` (sys.path に claude-config/scripts/lib)、 "
        f"bash = `source …/scripts/lib/office-staging.sh; office_stage_file <src>` → `$OFFICE_STAGED` を開く → copy back。 "
        f"staging root = {root}。 どうしても in-place が要るなら理由つきで `office-staging: exempt <理由>` を script に "
        f"(inline なら command 末尾の `# office-staging: exempt <理由>`)。 正本 = {SOT}"
    )


# ---------------------------------------------------------------- entry points
def main() -> int:
    if os.environ.get("CLAUDE_OFFICE_INPLACE_GUARD", "") == "0":
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError, UnicodeDecodeError):
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not isinstance(cmd, str):
        return 0
    try:
        issue = find_issue(cmd, data.get("cwd") or os.getcwd(), dict(os.environ))
    except Exception:  # noqa: BLE001  (fail-open: guard の不調で作業を止めない。 実効性は --canary が見る)
        return 0
    if not issue:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason_text(issue, dict(os.environ)),
    }}, ensure_ascii=False))
    return 0


CANARY_INPLACE = ('osascript -e \'tell application "Microsoft Excel" to open POSIX file '
                  '"/tmp/office-inplace-guard-canary/form.xlsx"\'')


def canary(force: bool = False) -> int:
    """本番配線の実効性: settings.json の entry + install 済み hook がカナリアを deny し、 staged path を通すか。"""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    if not force:
        if platform.system() != "Darwin":
            print("対象外: office-inplace-guard (macOS でない = Office の folder-grant dialog が起きない)")
            return 0
        if not os.path.isdir(os.path.join(home, "Library", "Group Containers", "UBF8T346G9.Office")):
            print("対象外: office-inplace-guard (Office 未 install)")
            return 0
    settings = os.path.join(home, ".claude", "settings.json")
    try:
        with open(settings, encoding="utf-8") as fh:
            conf = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"NOT ARMED: office-inplace-guard (settings.json が読めない: {e})")
        return 1
    cmds = []
    for ent in ((conf.get("hooks") or {}).get("PreToolUse") or []):
        matcher = ent.get("matcher", "")
        try:
            if matcher and not re.fullmatch(matcher, "Bash"):
                continue
        except re.error:
            continue
        for h in ent.get("hooks") or []:
            c = h.get("command", "")
            if "office-inplace-guard.py" in c:
                cmds.append(c)
    if not cmds:
        print("NOT ARMED: office-inplace-guard (settings.json の PreToolUse(Bash) に entry が無い → "
              "claude-config/scripts/sync-hook-settings.sh)")
        return 1
    hook = os.path.expanduser(cmds[0].split()[0].replace("~", home, 1))
    if not (os.path.isfile(hook) and os.access(hook, os.X_OK)):
        print(f"NOT ARMED: office-inplace-guard (install 済み hook が無い / 実行不可: {hook})")
        return 1
    if "disableAllHooks" in conf and conf.get("disableAllHooks") is True:
        print("NOT ARMED: office-inplace-guard (settings.json に disableAllHooks: true)")
        return 1

    def run(command: str) -> str:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"})
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_OFFICE_INPLACE_GUARD"}
        try:
            p = subprocess.run([hook], input=payload, capture_output=True, text=True, timeout=20, env=env)
            return p.stdout
        except (OSError, subprocess.SubprocessError) as e:
            return f"ERROR {e}"
    staged_root = os.path.join(home, "Library", "Group Containers", "UBF8T346G9.Office", "claude-office-staging")
    good = CANARY_INPLACE.replace("/tmp/office-inplace-guard-canary", staged_root + "/canary")
    out_bad, out_good = run(CANARY_INPLACE), run(good)
    if '"deny"' not in out_bad:
        print(f"NOT ARMED: office-inplace-guard (install 済み hook がカナリアを deny しない: {out_bad.strip()[:200]!r})")
        return 1
    if out_good.strip():
        print(f"NOT ARMED: office-inplace-guard (staging 内の path まで止める: {out_good.strip()[:200]!r})")
        return 1
    print(f"ARMED: office-inplace-guard (settings entry + {hook} がカナリアを deny、 staging 内は通す)")
    return 0


def selftest() -> int:
    import tempfile
    fails = 0
    tmp = tempfile.mkdtemp(prefix="office-inplace-guard-selftest-")
    home = os.path.join(tmp, "home")
    root = os.path.join(home, "Library", "Group Containers", "UBF8T346G9.Office", "claude-office-staging")
    os.makedirs(os.path.join(root, "x"), exist_ok=True)
    env = {"HOME": home}
    proj = os.path.join(tmp, "example")
    os.makedirs(proj, exist_ok=True)

    def w(name: str, body: str) -> str:
        p = os.path.join(proj, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    TELL_X = 'tell application "Microsoft Excel"'
    w("inplace.applescript", f'{TELL_X}\n  set wbk to open workbook workbook file name (POSIX file "/tmp/example/form.xlsx")\n  save wbk\nend tell\n')
    w("argv.applescript", f'on run argv\n  {TELL_X}\n    open POSIX file (item 1 of argv)\n    save active workbook\n  end tell\nend run\n')
    w("staged.applescript", f'{TELL_X}\n  open POSIX file "{root}/x/form.xlsx"\nend tell\n')
    w("exempt.applescript", f'-- office-staging: exempt 検証用に原本の再計算が要る\n{TELL_X}\n  open POSIX file "/tmp/example/form.xlsx"\nend tell\n')
    w("driver.py", "import subprocess\ndef export(x, pdf):\n    s = f'''\n" + TELL_X + "\n  set w to open workbook workbook file name (POSIX file \"{x}\")\n"
      "  save as active sheet of w filename (POSIX file \"{pdf}\") file format PDF file format\nend tell\n'''\n"
      "    subprocess.run(['osascript', '-e', s], check=True)\n")
    w("driver_staged.py", "import sys, subprocess\nsys.path.insert(0, 'lib')\nfrom office_staging import Stage\n"
      "def export(x):\n    with Stage(x) as st:\n        s = f'" + TELL_X.replace('"', '\\"') + " to open POSIX file \"{st.paths[0]}\"'\n"
      "        subprocess.run(['osascript', '-e', s])\n")
    w("fonts.py", "FONT = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/YuGothR.ttc'\n"
      "import openpyxl\nwb = openpyxl.Workbook()\nwb.save('/tmp/example/out.xlsx')\nopen('x').read()\n")
    w("prefs.sh", "osascript -e 'tell application \"Microsoft Word\" to count of documents'\n"
      "osascript -e 'tell application \"Microsoft Word\" to quit'\n")
    w("wrapper_caller.py", "import subprocess\nsubprocess.run(['xlsx-to-pdf.sh', 'form.xlsx'])\n")
    w("fill.sh", "source ~/Claude/claude-config/scripts/lib/office-staging.sh\noffice_stage_file \"$1\"\n"
      "osascript -e \"tell application \\\"Microsoft Word\\\" to open POSIX file \\\"$OFFICE_STAGED\\\"\"\n")
    with open(os.path.join(proj, "bin.scpt"), "wb") as fh:
        fh.write(b"FasdUAS 1.101.10\x00\x00\xff\xfe" + os.urandom(64))

    def check(cmd: str, want_deny: bool, label: str) -> None:
        nonlocal fails
        try:
            got = find_issue(cmd, proj, env)
        except Exception as e:  # noqa: BLE001
            got, want_deny = f"EXCEPTION {e!r}", not want_deny
        ok = bool(got) == want_deny
        print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  (got {got!r})"))
        fails += 0 if ok else 1

    # 止める
    check("osascript -e 'tell application \"Microsoft Excel\" to open POSIX file \"/tmp/example/form.xlsx\"'", True, "inline tell … to open (in-place)")
    check("osascript -e 'tell application \"Microsoft Word\"' -e 'open file name \"/tmp/example/a.docx\"' -e 'end tell'", True, "inline -e 分割 (Word)")
    check("osascript <<'EOF'\ntell application \"Microsoft PowerPoint\"\n  open POSIX file \"~/Desktop/deck.pptx\"\nend tell\nEOF", True, "heredoc (PowerPoint, ~ path)")
    check("osascript -e 'tell application \"Microsoft Word\" to save as active document file name \"/tmp/example/out.pdf\" file format format PDF'", True, "save as PDF の出力先が staging 外")
    check("F=/tmp/example/form.xlsx; osascript -e \"tell application \\\"Microsoft Excel\\\" to open POSIX file \\\"$F\\\"\"", True, "同じ command 内の代入を解決")
    check("osascript -e 'tell application \"Microsoft Excel\" to open alias \"Macintosh HD:Users:someone:form.xlsx\"'", True, "HFS path")
    check("osascript -e \"tell application \\\"Microsoft Word\\\" to open POSIX file \\\"$PWD/a.docx\\\"\"", True, "$PWD は cwd として解決")
    check("osascript inplace.applescript", True, "applescript file (literal path)")
    check("osascript argv.applescript /tmp/example/form.xlsx", True, "applescript file + argv の path")
    check("python3 driver.py", True, "python driver (helper なし)")
    check("cd /tmp && python3 " + os.path.join(proj, "driver.py") + " --flag", True, "python driver (絶対 path + cd)")
    check("python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['osascript','-e','tell application \"Microsoft Excel\" to open POSIX file \"/x/y.xlsx\"'])\nEOF", True, "python heredoc")
    check("xlsx-to-pdf.sh --no-stage form.xlsx", True, "wrapper --no-stage")
    check("bash ~/Claude/claude-config/scripts/docx-to-pdf.sh --no-stage a.docx", True, "bash wrapper --no-stage")
    check("CLAUDE_OFFICE_STAGING=0 xlsx-to-pdf.sh form.xlsx", True, "wrapper を env で無効化")
    check("true && osascript -e 'tell app \"Microsoft Excel\" to save active workbook in \"/tmp/example/out.xlsx\"'", True, "tell app 省略形 + && の後")
    # 通す
    check("xlsx-to-pdf.sh form.xlsx", False, "wrapper (既定 staging)")
    check("zsh ~/Claude/claude-config/scripts/xlsx-to-pdf.sh /tmp/example/form.xlsx", False, "zsh wrapper")
    check(f"osascript -e 'tell application \"Microsoft Excel\" to open POSIX file \"{root}/x/form.xlsx\"'", False, "staging 内の path")
    check("osascript staged.applescript", False, "applescript (staging 内 literal)")
    check("osascript exempt.applescript", False, "script 内の exempt")
    check("osascript -e 'tell application \"Microsoft Excel\" to open POSIX file \"/tmp/example/form.xlsx\"' # office-staging: exempt 原本で再計算", False, "command の exempt comment")
    check("osascript -e 'tell application \"Microsoft Excel\" to open POSIX file \"/tmp/example/form.xlsx\"' # office-staging: exempt", True, "理由なし exempt は無効")
    check("xlsx-to-pdf.sh --no-stage form.xlsx # office-staging: exempt macro 付き様式の再保存を確認", False, "--no-stage + exempt")
    check("python3 driver_staged.py", False, "python driver (helper 使用)")
    check("bash fill.sh form.docx", False, "bash driver (helper を source)")
    check("python3 fonts.py", False, "Office.app の font path + openpyxl save (駆動ではない)")
    check("bash prefs.sh", False, "Word を count / quit するだけ")
    check("python3 wrapper_caller.py", False, "wrapper を呼ぶだけの script")
    check("osascript -e 'tell application \"Microsoft Excel\" to save active workbook'", False, "path の無い save (判定不能 = 通す)")
    check("osascript -e \"tell application \\\"Microsoft Excel\\\" to open POSIX file \\\"$OFFICE_STAGED\\\"\"", False, "$OFFICE_STAGED")
    check("osascript -e \"tell application \\\"Microsoft Excel\\\" to open POSIX file \\\"$UNKNOWN\\\"\"", False, "未解決の変数 (fail-open)")
    check("office-stage-run.sh form.xlsx -- osascript argv.applescript {}", False, "runner + argv applescript")
    check("office-stage-run.sh form.xlsx -- python3 driver.py {}", False, "runner + helper なし driver (runner が stage)")
    check("office-stage-run.sh form.xlsx -- osascript inplace.applescript {}", True, "runner でも literal in-place は止める")
    check("command grep -rn 'tell application \"Microsoft Excel\"' . | grep 'open POSIX file \"/tmp/x.xlsx\"'", False, "grep の引数 (実行ではない)")
    check("osascript bin.scpt", False, "読めない .scpt (fail-open)")
    check("python3 -m http.server", False, "python -m")
    check("echo 'unbalanced", False, "shlex が壊れる入力")
    check("open -a 'Microsoft Excel' /tmp/example/form.xlsx", False, "open -a (射程外)")
    check("osascript -e 'tell application \"Keynote\" to open POSIX file \"/tmp/example/a.key\"'", False, "Office 以外の app")
    shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--canary" in sys.argv:
        sys.exit(canary(force="--force-applicable" in sys.argv))
    sys.exit(main())
