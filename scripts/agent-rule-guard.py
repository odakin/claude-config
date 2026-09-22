#!/usr/bin/env python3
"""Protect agent-governance documents, enforcement configuration and declared gates; compatible approval/scan entry point.

# agent-authority:file

Normative owner: conventions/agent-rule-ownership.md. This module owns the
vendor-neutral authority predicate. The manuscript dispatcher imports it, so
Claude, Codex and Git keep one predicate and one approval store. Existing hook
commands remain compatible; this CLI forwards operational commands to that
dispatcher. --selftest exercises the generic predicate without real user data.

Built-in control paths are conservative: changing an instruction document or
permission/CI definition needs a reviewed candidate, even for a benign edit.
Ordinary application code and status/index prose are not blanket-protected.
Repositories add enforcement implementation paths in .agent-rule-guard.json;
the manifest has no exclusion/disable switch. Callers must union HEAD, index
and worktree declarations. A code file that mentions an engine is locked as a
whole unless every mention sits inside an explicit begin/end block; then the
blocks carry the lock and the rest is ordinary code (decision record and the
holes this leaves: conventions/agent-rule-ownership.md#wiring-scope). This is
not isolation from a malicious agent with write access to the checker/runtime
itself and does not interpret all prose.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import shlex
import sys

MANIFEST_REL = ".agent-rule-guard.json"
RULE_REF_TOKENS = tuple(name + "#rule" for name in (
    "agent-rule-ownership.md", "manuscript-claim-ownership.md",
))
ENGINE_TOKENS = ("agent-rule-guard", "agent_rule_guard",
                 "manuscript-claim-guard", "manuscript_claim_guard")
WIRING_SUFFIXES = {".py", ".sh", ".js", ".ts", ".json", ".toml", ".yaml", ".yml", ".rules", ""}
ENTRYPOINT_NAMES = {"AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CONVENTIONS.md"}
CONTROL_PATTERNS = (
    "conventions/*.md", ".claude/settings*.json", ".codex/config*.toml",
    ".codex/hooks.json", ".codex/rules/*.rules", ".github/workflows/*.yml",
    ".github/workflows/*.yaml", ".pre-commit-config.yaml", ".pre-commit-config.yml",
    ".git/config", ".git/hooks/*", ".claude/hooks/*", ".codex/hooks/*",
    MANIFEST_REL,
)
MARK_FILE_RE = re.compile(r"^\s*(?:#|//|%|<!--)\s*agent-authority:file\b", re.M)
MARK_BEGIN_RE = re.compile(r"^\s*(?:#|//|%|<!--)\s*agent-authority:begin\s+id=([A-Za-z0-9._-]+)", re.M)
MARK_END_TMPL = r"^\s*(?:#|//|%|<!--)\s*agent-authority:end\s+id={id}\b"


def parse_manifest(text: str | None) -> list[str]:
    """None means absent. Malformed or weakening-shaped declarations fail closed."""
    if text is None:
        return []
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) - {"version", "protect_paths"}:
        raise ValueError("invalid agent-rule guard manifest fields")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("unsupported agent-rule guard manifest version")
    paths = value.get("protect_paths")
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p or
            p.startswith(("/", "~")) or "\\" in p or ".." in PurePosixPath(p).parts for p in paths):
        raise ValueError("protect_paths must be repository-relative patterns")
    return paths


def protected_path(path: str, extra_paths: tuple[str, ...] | list[str] = ()) -> bool:
    rel = path.replace("\\", "/")
    if PurePosixPath(rel).name in ENTRYPOINT_NAMES:
        return True
    for pattern in CONTROL_PATTERNS:
        if fnmatch.fnmatchcase(rel, pattern) or fnmatch.fnmatchcase(rel, "*/" + pattern):
            return True
    return any(fnmatch.fnmatchcase(rel, p) for p in extra_paths)


def authority_regions(text: str, path: str, extra_paths: tuple[str, ...] | list[str] = ()) -> dict[str, str]:
    """Extract protected authority content without guessing whether an edit is good.

    Return stable region ids for the shared approval engine. Byte-sensitive
    content preserves code indentation/control flow. Compare old AND new maps
    so deleting a marker, reference, gate or manifest does not remove protection.
    """
    out: dict[str, str] = {}
    if text and (MARK_FILE_RE.search(text) or protected_path(path, extra_paths)):
        out["authority:file"] = text
    blocks: list[tuple[int, int]] = []  # body spans of explicit blocks (marker lines excluded)
    for begin in MARK_BEGIN_RE.finditer(text):
        rid = begin.group(1)
        end = re.compile(MARK_END_TMPL.format(id=re.escape(rid)), re.M).search(text, begin.end())
        stop = end.start() if end else len(text)
        key, n = "authority:" + rid, 2
        while key in out:  # a repeated id protects every block, not only the last one
            key, n = f"authority:{rid}~{n}", n + 1
        out[key] = text[begin.end():stop] if end else text[begin.end():] + "\n<<unterminated>>"
        blocks.append((begin.end(), stop))
    refs = sorted(re.sub(r"\s+", " ", line).strip() for line in text.splitlines()
                  if any(token in line for token in RULE_REF_TOKENS))
    if refs:
        out["authority:rule-ref"] = "\n".join(refs)
    if Path(path).suffix.lower() in WIRING_SUFFIXES and any(t in text for t in ENGINE_TOKENS):
        if not wiring_inside_blocks(text, blocks):
            out["authority:wiring"] = text
    if path.replace("\\", "/").endswith(".claude/manuscript-guard.json"):
        try:
            out["config"] = json.dumps(json.loads(text or "{}"), sort_keys=True)
        except ValueError:
            out["config"] = text
    return out


def wiring_inside_blocks(text: str, blocks: list[tuple[int, int]]) -> bool:
    """True when every engine-name mention lies inside the body of an explicit block.

    The blocks are regions of their own, so they carry the wiring lock and the
    rest of the file is ordinary code. A mention outside every block body,
    including one inside a marker line (for example in the block id), keeps the
    whole-file lock. Moving a file into this shape is itself a locked change.
    Bypasses that stay outside the block (an earlier exit, a replaced helper,
    a swallowed exit status) are not prevented here; the canary's liveness
    record surfaces them (conventions/agent-rule-ownership.md#wiring-scope).
    """
    if not blocks:
        return False
    for token in ENGINE_TOKENS:
        for hit in re.finditer(re.escape(token), text):
            if not any(start <= hit.start() and hit.end() <= stop for start, stop in blocks):
                return False
    return True


def shell_segments(command: str) -> list[list[str]]:
    """Tokenize the simple command forms we inspect, preserving quoted operators.

    Newlines outside quotes separate commands. Here-document bodies are data,
    not top-level commands. Expansion, aliases and arbitrary shell control flow
    are deliberately not evaluated. Raw quoting is removed only AFTER the
    operator/word distinction has been made.
    """
    segments: list[list[str]] = []
    current: list[str] = []
    raw: list[str] = []
    quote = None
    pending_docs: list[tuple[str, bool]] = []
    expect_doc: bool | None = None
    expect_target = False  # the next word is a redirection target, not an argument
    i = 0

    def flush_word():
        nonlocal expect_doc, expect_target
        if not raw:
            return
        parts = shlex.split("".join(raw), comments=False, posix=True)
        raw.clear()
        if len(parts) != 1:
            raise ValueError("unsupported shell token")
        if expect_doc is not None:
            pending_docs.append((parts[0], expect_doc))
            expect_doc = None
        elif expect_target:
            expect_target = False
        else:
            current.append(parts[0])

    def end_segment():
        flush_word()
        if expect_target:
            raise ValueError("incomplete redirection")
        if current:
            segments.append(current[:])
            current.clear()

    def redirect_target(pos: int) -> int:
        """After a redirection operator: `&fd` / `&-` duplicates are consumed here, a
        file name is the next word (dropped by flush_word). Redirections are not
        arguments: `2>/dev/null` after `commit -a` used to become a pathspec that
        matched nothing, so the commit was inspected as an empty selection."""
        nonlocal expect_target
        while pos < len(command) and command[pos] in " \t":
            pos += 1
        if pos < len(command) and command[pos] == "&":
            pos += 1
            while pos < len(command) and (command[pos].isdigit() or command[pos] == "-"):
                pos += 1
            return pos
        expect_target = True
        return pos

    while i < len(command):
        ch = command[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                if command[i + 1] != "\n":
                    raw.extend(command[i:i + 2])
                i += 2
                continue
            raw.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            raw.append(ch)
            i += 1
        elif ch == "\\" and i + 1 < len(command):
            if command[i + 1] != "\n":
                raw.extend(command[i:i + 2])
            i += 2
        elif ch in " \t\r":
            flush_word()
            i += 1
        elif ch == "#" and not raw:
            end = command.find("\n", i)
            i = len(command) if end < 0 else end
        elif ch == "\n":
            end_segment()
            i += 1
            for delimiter, strip_tabs in pending_docs:
                while i < len(command):
                    end = command.find("\n", i)
                    end = len(command) if end < 0 else end
                    line = command[i:end]
                    i = min(end + 1, len(command))
                    if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                        break
            pending_docs.clear()
        elif command.startswith("&>", i):  # &> file / &>> file (before & ends the segment)
            flush_word()
            i += 3 if command.startswith("&>>", i) else 2
            i = redirect_target(i)
        elif ch in ";&|()":
            end_segment()
            i += 1
        elif command.startswith("<<<", i):
            flush_word()
            current.append("<<<")
            i += 3
        elif command.startswith("<<", i):
            flush_word()
            strip_tabs = command.startswith("<<-", i)
            i += 3 if strip_tabs else 2
            expect_doc = strip_tabs
        elif ch in "<>":  # [fd]>, [fd]>>, >|, [fd]<, <> — then &fd or a target word
            if raw and "".join(raw).isdigit():
                raw.clear()  # an attached fd number belongs to the operator
            else:
                flush_word()
            two = command[i:i + 2]
            i += 2 if two in (">>", ">|", "<>") else 1
            i = redirect_target(i)
        else:
            raw.append(ch)
            i += 1
    if quote or expect_doc is not None:
        raise ValueError("incomplete shell quoting or heredoc")
    end_segment()  # flushes the last word (a pending redirection target is dropped there; a missing one raises)
    return segments


def executable_argv(segment: list[str]) -> tuple[list[str], list[str]]:
    """Remove ordinary assignment/env/command wrappers, not arbitrary arguments.

    Return argv plus env -C directory changes (local to this invocation).
    The commit scanner and bypass scanner share this executable-position test.
    """
    args = list(segment)
    directories = []
    while args:
        while args and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", args[0]):
            args.pop(0)
        if not args:
            break
        executable = Path(args[0]).name
        if executable == "env":
            args.pop(0)
            while args and (args[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", args[0])):
                opt = args.pop(0)
                if opt == "--":
                    break
                if opt in ("-u", "--unset") and args:
                    args.pop(0)
                elif opt in ("-C", "--chdir") and args:
                    directories.append(args.pop(0))
                elif opt.startswith("--chdir="):
                    directories.append(opt.partition("=")[2])
            continue
        if executable == "command":
            args.pop(0)
            while args and args[0].startswith("-"):
                opt = args.pop(0)
                if opt in ("-v", "-V"):
                    return [], []
            continue
        break
    return args, directories


def shell_script(args: list[str]) -> str | None:
    if not args or Path(args[0]).name not in ("bash", "sh", "zsh"):
        return None
    for i, arg in enumerate(args[1:-1], 1):
        if arg.startswith("-") and "c" in arg[1:]:
            return args[i + 1]
    return None


def git_operation_options(operation: str, args: list[str]) -> tuple[set[str], list[str]]:
    """Selection flags and paths, without mistaking option values for options."""
    rest = list(args)
    flags: set[str] = set()
    paths = []
    value_options = {"-m", "--message", "-F", "--file", "-C", "-c", "--reuse-message",
                     "--reedit-message", "--author", "--date", "--template", "-t",
                     "--fixup", "--squash", "--pathspec-from-file", "--cleanup", "--trailer", "--repo"}
    long_flags = {"--no-verify": "no_verify", "--all": "all", "--only": "only",
                  "--include": "include", "--dry-run": "dry_run", "--interactive": "interactive",
                  "--patch": "interactive", "--update": "update", "--force": "force"}
    while rest:
        arg, rest = rest[0], rest[1:]
        if arg == "--":
            paths.extend(rest)
            break
        if arg == "--pathspec-from-file" or arg.startswith("--pathspec-from-file="):
            flags.add("pathspec_file")
        if arg in value_options:
            rest = rest[1:]
            continue
        if arg.startswith("--") and arg.partition("=")[0] in value_options:
            continue
        if arg in long_flags:
            flags.add(long_flags[arg])
        elif operation == "add" and arg.startswith("-") and not arg.startswith("--"):
            for letter in arg[1:]:
                if letter in "Aufnpei":
                    flags.add({"A": "all", "u": "update", "f": "force", "n": "dry_run",
                               "p": "interactive", "e": "interactive", "i": "interactive"}[letter])
        elif operation == "commit" and arg.startswith("-") and not arg.startswith("--"):
            for i, letter in enumerate(arg[1:], 1):
                if letter in "mFtcCS":
                    if i == len(arg) - 1 and letter != "S":
                        rest = rest[1:]
                    break
                if letter in {"n", "a", "o", "i", "p"}:
                    flags.add({"n": "no_verify", "a": "all", "o": "only", "i": "include", "p": "interactive"}[letter])
        elif not arg.startswith("-"):
            paths.append(arg)
    return flags, paths


def git_bypass_attempts(command: str, depth: int = 0) -> list[str]:
    """Recognize literal Git hook suppression, not arbitrary shell semantics.

    Only inspect executable positions, so printing/searching an example is not
    blocked. Standard shell -c wrappers are inspected with a bounded recursion.
    Computed commands and programs which spawn Git remain outside this parser.
    """
    if depth > 4:
        return []
    try:
        segments = shell_segments(command)
    except ValueError:
        return []
    findings = []
    for segment in segments:
        args, _ = executable_argv(segment)
        if not args:
            continue
        inner = shell_script(args)
        if inner is not None:
            findings.extend(git_bypass_attempts(inner, depth + 1))
            continue
        executable = Path(args.pop(0)).name
        if executable != "git":
            continue
        redirected = False
        while args and args[0].startswith("-"):
            opt = args.pop(0)
            if opt in ("-C", "-c", "--config-env", "--git-dir", "--work-tree", "--namespace", "--exec-path") and args:
                value = args.pop(0)
                redirected |= opt in ("-c", "--config-env") and value.split("=", 1)[0].lower() == "core.hookspath"
            elif opt.startswith("-c"):
                redirected |= opt[2:].split("=", 1)[0].lower() == "core.hookspath"
            elif opt.startswith("--config-env="):
                redirected |= opt.partition("=")[2].split("=", 1)[0].lower() == "core.hookspath"
        if not args or args[0] not in ("commit", "push", "merge", "am"):
            continue
        operation = args[0]
        if redirected:
            findings.append("Git の実行時に core.hooksPath を差し替える")
        flags, _ = git_operation_options(operation, args[1:])
        if "no_verify" in flags:
            findings.append("Git の --no-verify / commit -n で既存 gate を省く")
    return sorted(set(findings))


def selftest() -> int:
    failures = []
    def check(name, ok):
        print(("PASS: " if ok else "FAIL: ") + name)
        if not ok:
            failures.append(name)
    def changed(path, old, new, extra=()):
        return authority_regions(old, path, extra) != authority_regions(new, path, extra)

    for path in ("AGENTS.md", "src/AGENTS.override.md", "CLAUDE.md", "CONVENTIONS.md", "conventions/deployment.md"):
        check("unmarked instructions cannot self-relax: " + path,
              changed(path, "Review is required before deployment.\n", "Deploy without review.\n"))
        check("deleting instructions remains visible: " + path,
              changed(path, "Review is required before deployment.\n", ""))
    cases = [
        (".claude/settings.json", '{"permissions":{"deny":["Write"]}}', '{"permissions":{"deny":[]}}'),
        (".codex/config.toml", '[features]\nhooks=true\n', '[features]\nhooks=false\n'),
        (".codex/rules/policy.rules", 'decision="forbidden"', 'decision="allow"'),
        (".github/workflows/checks.yml", 'run: check-release\n', 'run: true\n'),
        (".codex/hooks.json", '{"hooks":{"PreToolUse":[{}]}}', '{"hooks":{}}'),
        (".pre-commit-config.yaml", 'repos: [gate]\n', 'repos: []\n'),
        (".git/config", '[core]\nhooksPath=.hooks\n', '[core]\nhooksPath=/dev/null\n'),
    ]
    for path, old, new in cases:
        check("enforcement configuration protected: " + path, changed(path, old, new))
    for path in ("README.md", "SESSION.md", "src/app.py", "docs/progress.md", "data/config.json"):
        check("ordinary content is not a control file: " + path, not changed(path, "Old value\n", "New value\n"))
    check("declared gate implementation protected", changed("scripts/check-release.py", "check()\n", "pass\n", ["scripts/check-*.py"]))
    check("additive declaration does not remove builtin protection", protected_path("AGENTS.md", []))
    marker = "<!-- agent-authority:begin id=retention -->\nKeep backups.\n<!-- agent-authority:end id=retention -->\n"
    check("marked rule survives marker deletion", changed("docs/storage.md", marker, "Keep backups.\n"))
    call = "python3 agent-rule-guard.py git-precommit\n"
    check("early exit cannot retain only the call line", changed("scripts/check.sh", call, "exit 0\n" + call))
    # Block-scoped wiring (agent-rule-ownership.md#wiring-scope): the block is the lock, the rest is ordinary.
    boxed = ("#!/bin/sh\nrun() { \"$@\"; }\n"
             "# agent-authority:begin id=guard-canary\n"
             "run python3 manuscript-claim-guard.py --canary\n"
             "# agent-authority:end id=guard-canary\n"
             "echo ordinary diagnostics\n")
    check("wiring inside an explicit block: the rest of the file is ordinary",
          not changed("scripts/diagnostics.sh", boxed, boxed.replace("ordinary diagnostics", "other diagnostics")))
    check("wiring inside an explicit block: the block itself stays protected",
          changed("scripts/diagnostics.sh", boxed, boxed.replace("--canary", "--canary || true")))
    check("wiring inside an explicit block: removing the markers is protected",
          changed("scripts/diagnostics.sh", boxed,
                  boxed.replace("# agent-authority:begin id=guard-canary\n", "").replace("# agent-authority:end id=guard-canary\n", "")))
    check("block-scoped wiring does not emit the whole-file region",
          "authority:wiring" not in authority_regions(boxed, "scripts/diagnostics.sh"))
    loose = boxed + "# see manuscript-claim-guard.py\n"
    check("a mention outside every block keeps the whole-file lock",
          changed("scripts/diagnostics.sh", loose, loose.replace("ordinary diagnostics", "other diagnostics")))
    check("a mention inside the marker id is outside the block body: whole-file lock",
          "authority:wiring" in authority_regions(boxed.replace("id=guard-canary", "id=manuscript-claim-guard-canary"),
                                                  "scripts/diagnostics.sh"))
    unterminated = boxed.replace("# agent-authority:end id=guard-canary\n", "")
    check("an unterminated block reaches the end of the file",
          changed("scripts/diagnostics.sh", unterminated, unterminated.replace("ordinary diagnostics", "other diagnostics")))
    check("block scoping never overrides a declared or built-in file lock",
          changed("hooks/diagnostics.sh", boxed, boxed.replace("ordinary diagnostics", "other diagnostics"), ["hooks/*"]))
    twice = marker + "Other text.\n" + marker.replace("Keep backups.", "Keep logs.")
    check("a repeated block id protects every block",
          changed("docs/storage.md", twice, twice.replace("Keep backups.", "Drop backups.")))
    check("a repeated block id keeps distinct regions",
          {"authority:retention", "authority:retention~2"} <= set(authority_regions(twice, "docs/storage.md")))
    check("canonical pointer removal is protected", changed("SESSION.md", RULE_REF_TOKENS[0], ""))
    good = '{"version":1,"protect_paths":["scripts/check-*.py"]}'
    check("valid additive manifest", parse_manifest(good) == ["scripts/check-*.py"])
    for raw in ('', '[]', '{"version":true,"protect_paths":[]}', '{"version":1,"protect_paths":[],"disabled":true}',
                '{"version":1,"protect_paths":[],"exclude":["AGENTS.md"]}',
                '{"version":1,"protect_paths":["../outside"]}'):
        try:
            parse_manifest(raw)
        except (ValueError, TypeError):
            check("malformed/weakening manifest rejected", True)
        else:
            check("malformed/weakening manifest rejected", False)
    for cmd in ("git commit --no-verify -m test", "/usr/bin/git -C /tmp/example push --no-verify",
                "git -c core.hooksPath=/dev/null commit -m test", "git -ccore.hooksPath=empty commit -m test",
                "git --config-env=core.hooksPath=HOOK_DIR commit -m test",
                "git --git-dir /tmp/example/.git commit --no-verify -m test",
                "echo preparing\ngit push --no-verify", "git commit -m ';' --no-verify",
                "cat <<< 'example'\ngit push --no-verify",
                "echo ready\n# comment\ngit commit --no-verify", "git \\\n push --no-verify",
                "bash -lc 'git commit -n -m test'", "git commit -an -m test",
                "env -u CODEX_THREAD_ID git commit --no-verify"):
        check("literal gate bypass is rejected: " + cmd, bool(git_bypass_attempts(cmd)))
    # Redirections are shell syntax, not arguments (an attached fd, a dup, a target word, &>).
    for cmd, expect in (("git commit -am x > log.txt 2>&1", [["git", "commit", "-am", "x"]]),
                        ("git commit -m x 2>/dev/null", [["git", "commit", "-m", "x"]]),
                        ("git commit -m x &>> log", [["git", "commit", "-m", "x"]]),
                        ("git commit -m x >log <in", [["git", "commit", "-m", "x"]]),
                        ("git commit -m x 1>&2", [["git", "commit", "-m", "x"]]),
                        ("git commit -m x 2>&1 | tee log", [["git", "commit", "-m", "x"], ["tee", "log"]]),
                        ("git commit -m 'a > b' -- '2>'", [["git", "commit", "-m", "a > b", "--", "2>"]])):
        check("redirections are not arguments: " + cmd, shell_segments(cmd) == expect)
    check("literal gate bypass is rejected behind a redirection",
          bool(git_bypass_attempts("git commit --no-verify -m x > /dev/null 2>&1")))
    for cmd in ("git commit -m x >", "git commit -m x 2>; echo"):
        try:
            shell_segments(cmd)
        except ValueError:
            check("incomplete redirection is rejected: " + cmd, True)
        else:
            check("incomplete redirection is rejected: " + cmd, False)
    for cmd in ("git commit -m 'mention --no-verify in a message'", "git commit -m --no-verify",
                "git commit -mmention", "git commit -man", "git commit -Fnotes.txt",
                "git commit -am --no-verify", "git commit -Ssigningkey -m test",
                "git commit -m --never", "git commit -- --no-verify", "echo git commit --no-verify",
                "printf '%s\\n' ';' git push --no-verify",
                "printf '%s\\n' '&&' git push --no-verify",
                "printf '%s\\n' 'first\ngit push --no-verify'",
                "cat <<'EOF'\ngit push --no-verify\nEOF\necho done",
                "rg -- '--no-verify' scripts", "git status", "git push origin main"):
        check("inspection or ordinary Git stays allowed: " + cmd, not git_bypass_attempts(cmd))
    print(f"agent-rule-guard selftest: {len(failures)} failure(s)")
    return bool(failures)


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        raise SystemExit(selftest())
    # The compatible dispatcher owns sessions, quote verification and tool/Git
    # reconstruction; there is no second approval implementation here.
    dispatcher = Path(__file__).with_name("manuscript-claim-guard.py")
    runpy.run_path(str(dispatcher), run_name="__main__")
