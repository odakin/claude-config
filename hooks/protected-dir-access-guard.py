#!/usr/bin/env python3
"""protected-dir-access-guard.py — PreToolUse(Bash / Grep / Glob): 保護を宣言した dir へ触れうる操作の前に確認を出す (ask)

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

確認を出す条件 (保護 dir D、 その親 dir の名前 P、 D の名前 B):
  Bash
    (a) command が D の path を書く (実体 path / home 直下 symlink 経由の別名 / `~` / `$HOME` 形) か `P/B` を書く、
        または `P/` の直後に glob を書く
    (b) command が D の上位 dir (… / home / `/`) を名指し、 かつ再帰する道具 (find / grep -r / rg / fd / du / tree /
        ls -R / rsync / tar / zip / cp -r / mdfind / locate / os.walk / rglob / `**/`) を使う
    (c) cwd が D の中
    (d) cwd が D の上位 dir で、 command が再帰する道具を使う
    (e) cwd が D の親 dir で、 command が B を語として書くか glob を使う
  Grep / Glob
    (f) 探す起点 (path、 無ければ cwd。 Glob は pattern の literal 部分を足す) が D の中か上位 dir、
        または Glob の pattern が `P/B` を含む

確認を出さないもの: B を含む文 (commit message・規約の grep)、 再帰しない一覧 (`ls <親>`)、 D の外の具体的な dir への
  再帰、 他の tool。 ⚠️ 射程外 = 変数に分けて組み立てた path、 script file の中の走査 (目的は事故の防止)。
ask にする理由 (deny にしない): 保護 dir の作業 session では、 中で作業するのが正当。 止まるのは仕様。

usage:
  (hook)                                   stdin = PreToolUse の JSON
  protected-dir-access-guard.py --canary   本番の settings.json と install 済み hook で、 宣言した dir の probe に
                                           確認が出るかを 1 行で報告 (ARMED / NOT ARMED / 未配線 / 対象外)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HOOK_NAME = "protected-dir-access-guard.py"
BOUND_END = r"""(?=/|["')\s;&|]|$)"""
BOUND_START = r"""(?:^|[\s"'=(:])"""
RECURSIVE_RE = re.compile(
    r"(?:^|[\s;&|(`])(?:find|rg|fd|ag|ack|du|tree|rsync|tar|zip|mdfind|locate)(?:\s|$)"
    r"|grep[^|;&]*\s(?:-[a-zA-Z]*[rR]|--recursive|-d\s*recurse)"
    r"|(?:^|[\s;&|(])ls[^|;&]*\s-[a-zA-Z]*R"
    r"|(?:^|[\s;&|(])cp[^|;&]*\s-[a-zA-Z]*[rRa]"
    r"|os\.walk|\.rglob\(|recursive\s*=\s*True|\*\*/"
)


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


def decide(payload: dict, home: str | None = None) -> str:
    """確認を出す理由 (空 = 出さない)。"""
    home = home or _home()
    dirs = load_dirs(home)
    if not dirs:
        return ""
    tool = payload.get("tool_name") or ""
    if tool not in ("Bash", "Grep", "Glob"):
        return ""
    ti = payload.get("tool_input") or {}
    aliases = _aliases(home)
    cwd = payload.get("cwd") or os.getcwd()
    ncwd = _norm(cwd, "/", home, aliases)
    for d in dirs:
        pr = Protected(d, home, aliases)
        if tool == "Bash":
            cmd = ti.get("command") or ""
            if not cmd:
                return ""
            recursive = bool(RECURSIVE_RE.search(cmd))
            if pr.path_re.search(cmd) or pr.pb_re.search(cmd) or pr.parent_glob_re.search(cmd):
                return f"command が保護 dir「{pr.name}」 の path を書いている"
            if recursive and pr.anc_re.search(cmd):
                return f"command が保護 dir「{pr.name}」 を含む上位 dir を再帰して辿る"
            if pr.inside(ncwd):
                return f"cwd が保護 dir「{pr.name}」 の中"
            if recursive and pr.ancestor(ncwd):
                return f"cwd が保護 dir「{pr.name}」 を含む上位 dir で、 command が再帰して辿る"
            if pr.is_parent(ncwd) and (pr.name_word_re.search(cmd) or re.search(r"[*?]", cmd)):
                return f"cwd が保護 dir「{pr.name}」 の親で、 command がその名前か glob を使う"
        else:
            base = ti.get("path") or cwd
            pat = ti.get("pattern") or ""
            if tool == "Glob" and pat:
                if pr.pb_re.search(pat):
                    return f"Glob の pattern が保護 dir「{pr.name}」 を名指す"
                lit = re.split(r"[*?\[]", pat, maxsplit=1)[0]
                lit = lit.rsplit("/", 1)[0] if "/" in lit else ""
                if lit:
                    base = lit if (lit.startswith("/") or lit.startswith("~")) else os.path.join(base, lit)
            nb = _norm(base, cwd, home, aliases)
            if pr.inside(nb):
                return f"{tool} の起点が保護 dir「{pr.name}」 の中"
            if pr.ancestor(nb):
                return f"{tool} の起点が保護 dir「{pr.name}」 を含む上位 dir (再帰で中に届く)"
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    try:
        reason = decide(payload)
    except Exception:  # noqa: BLE001  fail-open: guard の不調で作業を止めない (効いているかは --canary が見る)
        return 0
    if not reason:
        return 0
    sys.stderr.write(
        "🔒 protected-dir-access-guard: 保護を宣言した dir に触れる可能性があります\n"
        f"  理由: {reason}\n"
        "  意図せず当たったなら: 対象をその dir の外の具体的な dir に絞って出し直す (上位 dir から再帰しない)。\n"
        "  その dir の作業 session で意図して触るなら: user が許可する。\n"
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
                for t in ("Bash", "Grep", "Glob"):
                    try:
                        if re.fullmatch(ent.get("matcher", ""), t):
                            wired.add(t)
                    except re.error:
                        pass
    missing = {"Bash", "Grep", "Glob"} - wired
    if missing:
        print(f"NOT ARMED: protected-dir-access-guard (settings.json の PreToolUse に {'/'.join(sorted(missing))} の "
              "entry が無い → claude-config/scripts/sync-hook-settings.sh)")
        return 1
    if not (os.path.isfile(hook) and os.access(hook, os.X_OK)):
        print(f"NOT ARMED: protected-dir-access-guard (install 済み hook が無い / 実行不可: {hook})")
        return 1

    def run(tool: str, tool_input: dict, cwd: str) -> bool:
        data = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": cwd})
        try:
            p = subprocess.run([hook], input=data, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return '"permissionDecision": "ask"' in p.stdout

    bad = []
    for d in present:
        name = os.path.basename(d)
        if not run("Bash", {"command": f'ls "{d}"'}, "/"):
            bad.append(f"{name}: Bash の名指しに確認が出ない")
        if not run("Grep", {"pattern": "x", "path": os.path.dirname(d)}, "/"):
            bad.append(f"{name}: 親 dir を起点の Grep に確認が出ない")
        if run("Bash", {"command": "ls /"}, "/"):
            bad.append(f"{name}: 無関係な command に確認が出る")
    if bad:
        print("NOT ARMED: protected-dir-access-guard (" + " / ".join(bad) + ")")
        return 1
    print(f"ARMED: protected-dir-access-guard ({len(present)} dir、 Bash / Grep / Glob)")
    return 0


if __name__ == "__main__":
    if "--canary" in sys.argv:
        sys.exit(canary())
    sys.exit(main())
