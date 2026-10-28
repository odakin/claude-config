#!/usr/bin/env python3
"""cli-binary-read-check.py — Claude Code 本体 (端末の CLI の binary・desktop の埋込 engine・app の bundle) を使い捨ての python / grep / strings で読む Bash command を見つけ、 既存の道具 claude-app-bundle.py を知らせる engine (PreToolUse の Bash の hook が呼ぶ、 知らせるだけで止めない。 --selftest)

なぜ: 本体の binary は 1 行が MB 級の minified JS を含み、 素の grep -o は時間切れ、 使い捨ての mmap の code は
  毎回書き直しになる。 そのための道具 scripts/claude-app-bundle.py (端末の CLI は `--engine <path>` を subcommand の
  前に) が在るのに、 知らない session が自前の code で読み直した (実測 2 回: 埋込 engine を 7 回、 端末の CLI の binary を
  「道具は読めない」 と思い込んで)。 規約 = conventions/claude-app-bundle-reading.md。
述語 (find_issues): command が本体の置き場所 (埋込 engine の claude-code/<版>、 端末の CLI の versions/、 app の
  app.asar・ion-dist、 `readlink … command -v claude`) を指し、 かつ読む道具 (python・grep・strings・xxd 等) を
  起動している。 claude-app-bundle.py 自身と、 この engine・hook・test の名前を含む command は除く。
hook mode (stdin = PreToolUse の JSON): 当たれば additionalContext に 1 回だけ知らせる (状態 =
  ~/.claude/state/cli-binary-read-nudge/<session>、 14 日で掃除)。 止めない (exit 0)。 読めない入力は黙る。
校正 = scripts/calibrate-bash-command-pattern.py --hook scripts/cli-binary-read-check.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

TARGET_RE = re.compile(
    r"Application Support/Claude/claude-code/"
    r"|/claude-code/\d+\.\d+\.\d+"
    r"|\.local/share/claude/versions"
    r"|Claude\.app/Contents/Resources/(?:app\.asar|ion-dist)"
    r"|readlink[^|;&\n]*(?:command -v|which) claude"
)
READER_RE = re.compile(
    r"(?:^|[\s;|&(`$])(?:python3?(?:\.\d+)?|strings|xxd|hexdump|od|perl|rg|grep|egrep|awk)(?=\s|$)"
)
SELF_RE = re.compile(r"claude-app-bundle\.py|cli-binary-read-(?:check|nudge)")
STATE_DIR = os.environ.get("CLI_BINARY_READ_NUDGE_STATE_DIR") or os.path.expanduser(
    "~/.claude/state/cli-binary-read-nudge")
TOOL = "~/Claude/claude-config/scripts/claude-app-bundle.py"
MESSAGE = (
    "🔎 Claude Code 本体 (端末の CLI の binary・desktop の埋込 engine・app の bundle) を読むなら、 使い捨ての code でなく道具がある:\n"
    f"  python3 {TOOL} version / grep '<語>' --where engine|asar|renderer / slice … --find '<語>' --len 3000\n"
    f"  端末の CLI の binary は `--engine \"$(readlink -f \"$(command -v claude)\")\"` を subcommand の前に渡す"
    f" (例: python3 {TOOL} --engine <path> grep '<語>' --where engine)\n"
    "  手順と落とし穴 = claude-config/conventions/claude-app-bundle-reading.md (知らせるのはこの session で 1 回だけ。 止めていない)"
)


def find_issues(command: str) -> list:
    if not isinstance(command, str) or SELF_RE.search(command):
        return []
    target = TARGET_RE.search(command)
    if not target or not READER_RE.search(command):
        return []
    return [f"reads the Claude Code binary or bundle ({target.group(0).strip()})"]


def _state_path(session: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session or "nosession")
    return os.path.join(STATE_DIR, safe)


def _seen_once(session: str) -> bool:
    """True if this session was already told; otherwise mark it. Old marks (14 days) are swept."""
    path = _state_path(session)
    if os.path.exists(path):
        return True
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        cutoff = time.time() - 14 * 86400
        for name in os.listdir(STATE_DIR):
            p = os.path.join(STATE_DIR, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.unlink(p)
            except OSError:
                pass
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("1\n")
    except OSError:
        pass
    return False


def hook(stdin_text: str) -> str:
    try:
        payload = json.loads(stdin_text)
    except ValueError:
        return ""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return ""
    command = (payload.get("tool_input") or {}).get("command")
    if not find_issues(command):
        return ""
    if _seen_once(str(payload.get("session_id") or "")):
        return ""
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": MESSAGE}},
                      ensure_ascii=False)


def selftest() -> int:
    import tempfile
    cases = [
        ("python3 - <<'EOF'\nimport mmap, os\nf=open(os.path.expanduser('~/Library/Application Support/Claude/claude-code/2.1.309/abc/claude.app/Contents/MacOS/claude'),'rb')\nEOF", True),
        ("grep -a -o 'hook.matcher.{0,80}' \"$(readlink -f \"$(command -v claude)\")\"", True),
        ("strings ~/.local/share/claude/versions/2.1.309 | grep remote-control", True),
        ("LC_ALL=C grep -c Foo /Applications/Claude.app/Contents/Resources/app.asar", True),
        ("python3 ~/Claude/claude-config/scripts/claude-app-bundle.py grep foo --where engine", False),
        ("ls ~/Library/Application\\ Support/Claude/claude-code/", False),
        ("ls \"$HOME/Library/Application Support/Claude/claude-code/2.1.309\"", False),
        ("readlink -f \"$(command -v claude)\"", False),
        ("claude --version", False),
        ("grep -n 'claude-code' conventions/hook-authoring.md", False),
        ("python3 scripts/cli-binary-read-check.py --selftest", False),
        ("python3 -c \"print(1)\"", False),
    ]
    fail = 0
    for command, want in cases:
        got = bool(find_issues(command))
        ok = got == want
        fail += not ok
        print(("PASS" if ok else "FAIL") + f": {'hit' if want else 'quiet'}: {command.splitlines()[0][:90]}")
    global STATE_DIR
    with tempfile.TemporaryDirectory() as tmp:
        STATE_DIR = tmp
        event = json.dumps({"tool_name": "Bash", "session_id": "s1",
                            "tool_input": {"command": cases[2][0]}})
        first, second = hook(event), hook(event)
        other = hook(json.dumps({"tool_name": "Bash", "session_id": "s2", "tool_input": {"command": "ls"}}))
        checks = [
            ("first hit in a session is told", "claude-app-bundle.py" in first and "additionalContext" in first),
            ("second hit in the same session is quiet", second == ""),
            ("non-hit is quiet", other == ""),
            ("broken input is quiet", hook("not json") == ""),
            ("non-Bash tool is quiet", hook(json.dumps({"tool_name": "Read", "tool_input": {}})) == ""),
        ]
    for name, ok in checks:
        fail += not ok
        print(("PASS" if ok else "FAIL") + f": {name}")
    print(f"failed={fail}")
    return 1 if fail else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    try:
        out = hook(sys.stdin.read())
    except Exception:  # never break the tool call
        return 0
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
