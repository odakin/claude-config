#!/usr/bin/env python3
"""codex-headless-launch-check.py — 掲示板の依頼の worker や盲検の判定 session を headless の `codex exec` で起こす Bash を止め、 Codex アプリに出る起こし方を出す (理由を書けば通す。 hook の engine)。

Why (実測、 CLI 0.159.2): `codex exec` の thread は Codex アプリのどこにも出ない (状態 DB に source=exec で入り、 アプリの
一覧は対話の種類だけを出す)。 本人が見ようとした Codex の仕事がアプリに何も出ず、 別の機械の session が同じ仕事を
起こしかけた。 Codex の worker はアプリに出る形で起こす: 掲示板の `request --to codex --to-session role-…` (既定 =
scripts/codex-app-launch.py で手元の共有 daemon に thread を作り、 アプリに開かせる)、 盲検の判定 session は
`codex-app-launch.py start --sealed --cwd <sandbox>`。 headless が要る事情 (アプリの無い機械など) は本人か依頼元が選ぶ。

述語 (PreToolUse の Bash):
  - command の語として `codex … exec` / `codex … e` がある (引用符の中・heredoc の本文は数えない = commit message や
    文書の中の言及は起動でない。 `caffeinate -i` / `nohup` / `env` / `timeout N` / 変数代入の後ろ、 app 同梱の path も拾う)。
  - かつ、 掲示板の worker か盲検の判定 session に見える: command か、 `$(cat <file>)` / `< <file>` で渡す起動文に
    hand-off の印 (`.handoff.txt`・"board worker"・`role-<…>`) か盲検の印 (`REVIEW-SPEC`・`review-sandbox`) がある、
    または exec の作業 dir (`-C` / `--cd` / 前の `cd <dir>` / hook の cwd) に `REVIEW-SPEC.md` がある、
    または `exec resume <id>` の thread の作業 dir に `REVIEW-SPEC.md` がある (Codex の手元の記録で引く)。
  - 理由が書いてあれば通す: command の頭の `CODEX_EXEC_REASON='<理由>'` (掲示板の `--surface background
    --headless-reason` が出す行の形) か、 `# [codex-exec-ok: <理由>]`。 空の理由は理由でない。
  - 止めるときは exit 2、 stderr に代わりの起こし方を出す。

故障は通す (読めない入力・例外 = exit 0)。 規約 = ai-collaboration board/CONTRACT.md#codex-worker-launch /
cold-eyes-isolation.md §2-5。 env: CODEX_HEADLESS_LAUNCH_CHECK_DISABLE=1 (一時無効)。
self-test: python3 scripts/codex-headless-launch-check.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
try:
    import codex_threads as ct  # noqa: E402
except Exception:  # pragma: no cover - partial checkout
    ct = None

RULE = "ai-collaboration/board/CONTRACT.md#codex-worker-launch"
LAUNCHER = os.path.join(HERE, "codex-app-launch.py")
PREFILTER = re.compile(r"codex")
QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SEP = re.compile(r"&&|\|\||;|\||&|\(|\)|\n")
LEADING = {"do", "then", "else", "elif", "if", "while", "until", "{", "!", "time", "command", "builtin", "exec", "env", "nohup", "nice"}
WRAP_WITH_ARG = {"timeout": 1}
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
VALUE_OPTS = {"-c", "--config", "-m", "--model", "-p", "--profile", "-s", "--sandbox", "-C", "--cd", "-a", "--ask-for-approval",
              "--enable", "--disable", "-i", "--image", "--add-dir", "--remote", "--remote-auth-token-env", "--local-provider",
              "-o", "--output-last-message", "--output-schema", "--color", "--thread-source"}
BOARD_MARK = re.compile(r"\.handoff\.txt|board worker|(?<![\w/-])role-[a-z0-9][a-z0-9-]{2,}")
BLIND_MARK = re.compile(r"REVIEW-SPEC|review-sandbox")
REASON = re.compile(r"(?:^|[\s;&|(])CODEX_EXEC_REASON=(\"[^\"]*\"|'[^']*'|[^\s;&|]+)")
OK_MARK = re.compile(r"\[codex-exec-ok:\s*([^\]]*?)\s*\]")
CWD_OPT = re.compile(r"(?:^|\s)(?:-C|--cd)(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)")
CD_CMD = re.compile(r"(?:^|[;&|(]\s*|\n\s*)cd\s+(\"[^\"]*\"|'[^']*'|[^\s;&|]+)")
PROMPT_FILE = re.compile(r"\$\(\s*cat\s+(\"[^\"]*\"|'[^']*'|[^\s)]+)\s*\)|(?:^|\s)<\s*(\"[^\"]*\"|'[^']*'|[^\s<>;&|]+)")


def _unq(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return os.path.expanduser(s)


def blanked(cmd: str) -> str:
    """Heredoc bodies and quoted strings blanked; a quoted value right after `=` stays one word (`X='a b'` → `X=Q`)."""
    out = HEREDOC.sub(" HEREDOC ", cmd)
    return re.sub(r"(=)?(" + QUOTED.pattern + ")", lambda m: "=Q" if m.group(1) else " Q ", out)


def exec_segments(cmd: str) -> list[list[str]]:
    """Token lists (after `exec`/`e`) of every `codex … exec` command word in the command."""
    found = []
    for seg in SEP.split(blanked(cmd)):
        toks = seg.split()
        i = 0
        while i < len(toks):
            t = toks[i]
            if t in LEADING or ASSIGN.match(t):
                i += 1
                continue
            if os.path.basename(t) == "caffeinate":
                i += 1
                while i < len(toks) and toks[i].startswith("-"):
                    i += 1
                continue
            if t in WRAP_WITH_ARG:
                i += 1 + WRAP_WITH_ARG[t]
                continue
            break
        if i >= len(toks) or os.path.basename(toks[i]) != "codex":
            continue
        j = i + 1
        while j < len(toks) and toks[j].startswith("-"):
            opt = toks[j]
            j += 2 if (opt in VALUE_OPTS and "=" not in opt) else 1
        if j < len(toks) and toks[j] in ("exec", "e"):
            found.append(toks[j + 1:])
    return found


def reason(cmd: str) -> str:
    m = REASON.search(cmd)
    if m and _unq(m.group(1)).strip():
        return _unq(m.group(1)).strip()
    m = OK_MARK.search(cmd)
    return m.group(1).strip() if m and m.group(1).strip() else ""


def exec_cwd(cmd: str, hook_cwd: str) -> str:
    m = CWD_OPT.search(cmd)
    if m:
        p = _unq(m.group(1))
        return p if os.path.isabs(p) else os.path.join(hook_cwd or os.getcwd(), p)
    cds = [_unq(x) for x in CD_CMD.findall(cmd)]
    base = hook_cwd or os.getcwd()
    for d in cds:
        base = d if os.path.isabs(d) else os.path.join(base, d)
    return base


def prompt_texts(cmd: str, cwd: str) -> list[str]:
    out = []
    for m in PROMPT_FILE.finditer(cmd):
        p = _unq(m.group(1) or m.group(2) or "")
        if not p:
            continue
        p = p if os.path.isabs(p) else os.path.join(cwd, p)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                out.append(fh.read(65536))
        except OSError:
            continue
    return out


def resume_cwds(segments: list[list[str]]) -> list[str]:
    cwds = []
    for toks in segments:
        if "resume" not in toks or ct is None:
            continue
        rest = toks[toks.index("resume") + 1:]
        ids = [t for t in rest if re.fullmatch(r"[0-9a-f][0-9a-f-]{7,35}", t)]
        for tid in ids[:1]:
            try:
                full = ct.resolve(tid)
                rows = ct.thread_rows([full]) if full else []
                if rows and rows[0].get("cwd"):
                    cwds.append(rows[0]["cwd"])
            except Exception:
                pass
    return cwds


def judge(cmd: str, hook_cwd: str = "") -> tuple[bool, str]:
    """(block?, why). Blocks a headless `codex exec` that starts a board worker or a sealed-review judge without a reason."""
    if not cmd or not PREFILTER.search(cmd):
        return False, ""
    segs = exec_segments(cmd)
    if not segs:
        return False, ""
    if reason(cmd):
        return False, ""
    cwd = exec_cwd(cmd, hook_cwd)
    texts = [cmd] + prompt_texts(cmd, cwd)
    why = []
    if any(BOARD_MARK.search(t) for t in texts):
        why.append("掲示板の worker の起動文 (hand-off) を渡している")
    if any(BLIND_MARK.search(t) for t in texts):
        why.append("盲検の spec (REVIEW-SPEC) を渡している")
    for d in [cwd] + resume_cwds(segs):
        if d and os.path.isfile(os.path.join(d, "REVIEW-SPEC.md")):
            why.append(f"作業 dir {d} が盲検の sandbox (REVIEW-SPEC.md がある)")
            break
    return (bool(why), "、 ".join(why))


def message(why: str) -> str:
    return (f"⛔ headless の codex exec で Codex の worker を起こそうとしている ({why})。 codex exec の thread は Codex アプリの"
            " どこにも出ない = 本人が見られない (実測)。 代わりに:\n"
            "  - 掲示板の依頼の worker: board.py request --to codex --to-session role-… (既定でアプリに出る形で起こす。"
            " 別の機械なら --launch-host <機械>、 その機械の session が board.py launch --request <id>)\n"
            f"  - 盲検の判定 session: python3 {LAUNCHER} start --sealed --cwd <sandbox> --prompt-file <起動文の file>"
            " --model <m> --effort <e> [--network] (sandbox の外の指示 file を読むなら止まる)\n"
            "  - 本人か依頼元が headless を選んだなら、 理由を command の頭に書く: CODEX_EXEC_REASON='<理由>' codex exec …"
            f" (または # [codex-exec-ok: <理由>])。 規約 = {RULE}")


def main() -> int:
    if os.environ.get("CODEX_HEADLESS_LAUNCH_CHECK_DISABLE") == "1":
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
        if data.get("tool_name") not in (None, "Bash", "shell", "exec_command"):
            return 0
        ti = data.get("tool_input") or {}
        cmd = ti.get("command") or ""
        if isinstance(cmd, list):
            cmd = " ".join(shlex.quote(str(x)) for x in cmd)
        block, why = judge(cmd, data.get("cwd") or "")
    except Exception:
        return 0
    if block:
        print(message(why), file=sys.stderr)
        return 2
    return 0


def _selftest() -> int:
    tmp = tempfile.mkdtemp(prefix="chlc-")
    sb = os.path.join(tmp, "sandbox")
    os.mkdir(sb)
    open(os.path.join(sb, "REVIEW-SPEC.md"), "w").close()
    task = os.path.join(tmp, "TASK.md")
    with open(task, "w", encoding="utf-8") as fh:
        fh.write("You are the board worker for role `role-x-y`, request `r`.\n")
    plain = os.path.join(tmp, "plain.md")
    with open(plain, "w", encoding="utf-8") as fh:
        fh.write("Summarise the log.\n")
    app = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
    cases = [
        ("codex exec 'say hi'", False),
        (f"codex exec --json -o out.txt \"$(cat {task})\"", True),
        (f"CODEX_EXEC_REASON='この機械に Codex アプリが無い' codex exec \"$(cat {task})\"", False),
        (f"CODEX_EXEC_REASON='' codex exec \"$(cat {task})\"", True),
        (f"cd {sb} && caffeinate -i {app} exec --json -o x 'Read the spec in this directory. token = T1'", True),
        (f"codex exec -C {sb} --skip-git-repo-check 'go'", True),
        (f"{app} -c model_reasoning_effort=\"high\" exec \"$(cat {plain})\"", False),
        (f"{app} -c model_reasoning_effort=\"high\" exec \"$(cat {task})\"", True),
        ("git commit -m 'avoid codex exec with REVIEW-SPEC and .handoff.txt'", False),
        ("codex queue --thread 01a1 --message 'role-x-y: posted'", False),
        ("codex e 'work for role-qproj-table'", True),
        (f"codex exec 'Read REVIEW-SPEC.md' # [codex-exec-ok: 本人が headless を指定]", False),
        (f"python3 {LAUNCHER} start --cwd {sb} --sealed --prompt-file p.txt", False),
        (f"nohup timeout 600 codex exec 'x' < {task} > log 2>&1 &", True),
    ]
    ok_all = True
    for cmd, want in cases:
        got, why = judge(cmd, hook_cwd=tmp)
        ok = got == want
        ok_all &= ok
        print(("PASS " if ok else "FAIL ") + f"{'block' if want else 'pass '} | {cmd[:90]}" + (f"  [{why}]" if got else ""))
    ok = "codex-app-launch.py start --sealed" in message("x")
    ok_all &= ok
    print(("PASS " if ok else "FAIL ") + "止める文に代わりの起こし方 (アプリに出る起動) がある")
    return 0 if ok_all else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--selftest"]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
