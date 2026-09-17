"""chat_file_refs.py — chat の最終発話にある file 参照 (markdown link の href と、 path に見える inline code) を、 Claude Code desktop app の右パネルと同じ基準で解決し、 開けないものに正しい path を添えて返す共通部品 (Stop hook chat-file-ref-enforce.sh と校正が共用)

解決の規則 (desktop app の bundle で確認、 正本 = conventions/claude-code-permissions.md#chat-link-resolution-base):
- 相対 path は **session を始めたときに選んだ folder** に連結する。 Bash の cd で harness が通知する
  「Primary working directory」 が変わっても、 この基準は変わらない。
- 絶対 path はそのまま、 `~/` は home に展開する。
- inline code の中身も、 `/` を含み拡張子で終わる形なら、 file が実在しなくても link として描かれる (実測。
  `CLAUDE.md` のような区切りの無い名前と `dir/` は描かれない)。 link の label の中の inline code は別の link に
  ならない (押すと href が開く) ので拾わない。
- 基準フォルダが git repo のとき、 app の本体は連結した先に file が無いと `git ls-files` (無ければ untracked) で
  path の末尾一致を探し、 1 件に決まればそれを開く。 この第 1 段を写している (git_suffix_matches)。 複数一致のときの
  本体の絞り込み (変更中の file に近いものを選ぶ) は写さず、 開けない側に数える。
- worktree に入った session で本体が worktree の path を先に試す挙動は写していない (正本の同節)。

検出の条件 (= 誤検出を避けるため狭くとる):
  (a) 開けない (基準 folder に連結すると存在しない / 基準の外に出る) ∧ 別の folder に連結すると存在する。
      別の folder = transcript に出た cwd (新しい順) → 基準 folder の直下の dir。
      どこにも無い path (例示の `path/to/file.md` など) は拾わない。
  (b) 意図と違う file が開く (reason = shadowed): 基準 folder に連結すると file が在るが、 直近の cwd (≠ 基準) にも
      同じ相対 path の別の file が在る (例: 親フォルダと repo の両方に在る CLAUDE.md を repo の中で書いた)。
"""
from __future__ import annotations

import os
import re
import subprocess
from urllib.parse import unquote

# session の基準フォルダ・cwd・追加フォルダ・entrypoint の読み出しは transcript の共通部品が持つ
from transcript_turns import (session_additional_dirs, session_entrypoint,  # noqa: F401
                              session_root_and_cwds)

# fence の前置きは桁数を問わず、 引用の `>` も許す (list の中で 4 桁以上 indent された fence と、 引用の中の fence も
# 描画上は code block。 広く取る側 = 検出が減る側なので、 取りすぎても誤検出にはならない)
# backtick の fence は info (同じ行の残り) に backtick を書けない = 行頭の inline な 3 連 backtick (```code``` は…) は
# fence ではない。 fence と取り違えると、 次の fence か末尾までの本物の参照を見逃す
FENCE_RE = re.compile(r"^[ \t>]*(`{3,}(?=[^`\n]*\n)|~{3,})[^\n]*\n.*?(?:^[ \t>]*\1[ \t]*$|\Z)", re.S | re.M)
CODE_SPAN_RE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
LINK_RE = re.compile(r"\[[^\]\n]*\]\(\s*<([^>\n]+)>[^)\n]*\)|\[[^\]\n]*\]\(\s*([^)\s]+)(?:\s+\"[^\"\n]*\")?\s*\)")
# scheme の判定は app と同じ式 (bundle の file 参照 parser)。 `SESSION.md:42` のような「区切りの無い名前 + 行番号」 は
# scheme ではなく file + 行番号 (class に `.` が無い + 行番号の後置は scheme にしない)
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+-]+:(?!\d+(?:[-:]\d+)?$)", re.I)
# inline code を link として描く形 = app の file 参照 parser の式を写したもの (読んだ版は正本の同節):
#   ^([L.()[\]-]*(?:/[L.()[\]-]+)*/[L()[\]-]*\.\w[\w.-]*)(?::(\d+)(?:-(\d+)|:\d+)?)?$   L = \p{L}\p{N}\p{M}_ 、 \w は ASCII
# 使える文字は文字・数字・結合文字・`_` `.` `-` `(` `)` `[` `]` だけ (空白・`~`・`@`・`+`・`$`・`*` を含むと link にならない)。
# python の re に \p{…} は無いので、 L = \w (Unicode の文字・数字・_) + 主な結合文字の範囲で近似する。
_L = r"\ẁ-ͯ᪰-᫿᷀-᷿⃐-⃿゙゚︠-︯"
CODE_PATH_RE = re.compile(
    rf"^[{_L}.()\[\]-]*(?:/[{_L}.()\[\]-]+)*/[{_L}()\[\]-]*\.[A-Za-z0-9_][A-Za-z0-9_.-]*(?::\d+(?:-\d+|:\d+)?)?$")
LINE_SUFFIX_RE = re.compile(r":\d+(?:[-:]\d+)?$")


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def extract_refs(text: str) -> list[tuple[str, str, str]]:
    """最終発話 → [(kind, raw, path)]。 kind = "link" | "code"。 fenced block の中は描かれないので見ない。"""
    body = FENCE_RE.sub(_blank, text or "")
    blanked = CODE_SPAN_RE.sub(_blank, body)  # code span の中の [..](..) は link として描かれない (長さは保つ)
    links = [m for m in LINK_RE.finditer(blanked) if (m.group(1) or m.group(2) or "").strip()]
    refs: list[tuple[str, str, str]] = []
    for m in CODE_SPAN_RE.finditer(body):
        inner = m.group(2).strip()
        if not CODE_PATH_RE.match(inner):
            continue
        # link の label の中の inline code は別の link にならない (app は anchor の子を「link の中」 として描き、
        # 押すと href が開く)。 [`dir/file.md`](/絶対/path) を code の側で拾わない
        if any(lm.start() <= m.start() < lm.end() for lm in links):
            continue
        refs.append(("code", m.group(0), inner))
    for m in links:
        refs.append(("link", m.group(0), (m.group(1) or m.group(2)).strip()))
    return refs


def normalize(path: str) -> str | None:
    """href / code span → file system 上の相対 path。 対象外 (URL・anchor のみ・絶対・~/) は None。"""
    p = path.strip()
    if not p or p.startswith("#"):
        return None
    if SCHEME_RE.match(p) or p.startswith("//"):
        return None  # http: / mailto: / file: など
    p = p.split("#", 1)[0].split("?", 1)[0]
    p = LINE_SUFFIX_RE.sub("", p)
    p = unquote(p)
    if not p or p.startswith("/") or p == "~" or p.startswith("~/"):
        return None
    return p


def _inside(path: str, root: str) -> bool:
    rel = os.path.relpath(path, root)
    return rel != ".." and not rel.startswith(".." + os.sep)


def candidate_dirs(root: str, seen_cwds: list[str] | None = None) -> list[str]:
    """別の基準の候補。 transcript に出た cwd (呼び出し側が新しい順に渡す) → root 直下の dir。 重複は除く。"""
    out: list[str] = []
    for d in (seen_cwds or []):
        if d and os.path.isdir(d) and os.path.normpath(d) != os.path.normpath(root):
            out.append(os.path.normpath(d))
    try:
        for name in sorted(os.listdir(root)):
            if name.startswith("."):
                continue
            d = os.path.join(root, name)
            if os.path.isdir(d):
                out.append(os.path.normpath(d))
    except OSError:
        pass
    uniq: list[str] = []
    for d in out:
        if d not in uniq:
            uniq.append(d)
    return uniq


def git_listing(root: str) -> tuple[list[str], list[str]] | None:
    """基準フォルダが git の work tree なら (tracked, untracked) の相対 path、 違えば None。 app と同じ
    `git -c core.quotepath=false ls-files` (untracked は `--others --exclude-standard`) を基準フォルダで打つ。"""
    out = []
    for extra in ([], ["--others", "--exclude-standard"]):
        try:
            r = subprocess.run(["git", "-C", root, "-c", "core.quotepath=false", "ls-files", *extra],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        out.append(r.stdout.split("\n"))
    return out[0], out[1]


def git_suffix_matches(listing: tuple[list[str], list[str]] | None, p: str) -> list[str]:
    """app の末尾一致の第 1 段: tracked で `p` に等しいか `/p` で終わる path、 無ければ untracked で同じ。"""
    if listing is None:
        return []
    r = p[2:] if p.startswith("./") else p
    tail = "/" + r
    for names in listing:
        hits = sorted({n for n in names if n == r or n.endswith(tail)})
        if hits:
            return hits
    return []


def find_broken(text: str, root: str, seen_cwds: list[str] | None = None, limit: int = 3,
                extra_roots: list[str] | None = None, git_cache: dict | None = None) -> list[dict]:
    """開けない参照のうち、 別の基準なら存在するもの + 意図と違う file が開くもの。
    [{kind, raw, path, reason, candidates}] (reason = missing | outside | shadowed、 candidates は絶対 path)。
    extra_roots = session に追加したフォルダ。 `../` で基準の外に出ても、 連結した先がこの中に在れば app は開くので拾わない。"""
    if not root or not os.path.isdir(root):
        return []
    root = os.path.normpath(root)
    extras = [os.path.normpath(os.path.expanduser(d)) for d in (extra_roots or []) if d]
    cur = next((os.path.normpath(d) for d in (seen_cwds or []) if d), None)  # 直近の cwd
    dirs = None
    listing: tuple[list[str], list[str]] | None | bool = False  # False = まだ引いていない
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for kind, raw, ref in extract_refs(text):
        p = normalize(ref)
        if p is None or (kind, p) in seen:
            continue
        seen.add((kind, p))
        target = os.path.normpath(os.path.join(root, p))
        if not _inside(target, root):
            if os.path.exists(target) and any(_inside(target, d) for d in extras):
                continue
            reason = "outside"
        elif os.path.exists(target):
            # 開くが、 直近の cwd に同じ相対 path の別の file が在る = repo の中からの path のつもりで書いた可能性
            other = os.path.normpath(os.path.join(cur, p)) if cur and cur != root else None
            if (other and os.path.isfile(target) and os.path.isfile(other)
                    and os.path.realpath(other) != os.path.realpath(target)):
                findings.append({"kind": kind, "raw": raw, "path": p, "reason": "shadowed", "candidates": [other]})
            continue
        else:
            reason = "missing"
        if dirs is None:
            dirs = candidate_dirs(root, seen_cwds)
        # 基準の外に出た先が実在するなら、 それ自体が正しい相手 (絶対 path で示す)
        cands: list[str] = [target] if reason == "outside" and os.path.exists(target) else []
        for d in dirs:
            c = os.path.normpath(os.path.join(d, p))
            if os.path.exists(c) and c not in cands:
                cands.append(c)
                if len(cands) >= limit:
                    break
        if not cands:
            continue
        if reason == "missing":
            # git は候補が在る参照にだけ、 1 回の判定につき 1 度だけ聞く (例示の path や git でない基準では呼ばない / すぐ戻る)
            if listing is False:
                if git_cache is not None and root in git_cache:
                    listing = git_cache[root]
                else:
                    listing = git_listing(root)
                    if git_cache is not None:
                        git_cache[root] = listing  # 校正用 (同じ基準フォルダを何百 turn も引くので 1 回にする)
            if len(git_suffix_matches(listing, p)) == 1:
                continue  # 基準フォルダが git repo で末尾一致が 1 件 = app はそれを開く
        findings.append({"kind": kind, "raw": raw, "path": p, "reason": reason, "candidates": cands})
    return findings



# ---- hook / 校正の入口 -------------------------------------------------------------

# 右パネルで file を開く frontend。 CLI (端末) には右パネルが無いので対象外。
PANEL_ENTRYPOINTS = ("claude-desktop", "claude-desktop-3p", "claude-vscode")  # 名前は engine の entrypoint 一覧で確認
DOC = "claude-config/conventions/claude-code-permissions.md#chat-link-resolution-base"
BT = chr(96)  # backtick


def _show(path: str, root: str) -> str:
    return os.path.relpath(path, root) if _inside(path, root) else path


def build_reason(findings: list[dict], root: str) -> str:
    shadowed = any(f["reason"] == "shadowed" for f in findings)
    what = "右パネルで開けないか、 意図と違う file を開きます" if shadowed else "右パネルで開けません"
    lines = [
        f"🔗 chat-file-ref: 最終メッセージの file 参照 {len(findings)} 件が、 {what}。 "
        f"desktop app は相対 path を session を始めたフォルダ ({root}) に連結します "
        f"(Bash の cd で変わる「作業ディレクトリ」 ではありません)。 "
        f"inline code の {BT}dir/file.ext{BT} もリンクとして描かれます。",
    ]
    where_of = {"outside": "フォルダの外", "missing": "存在しない",
                "shadowed": "上のフォルダの同名の別 file が開く。 作業中のフォルダの file を指すなら"}
    for f in findings[:8]:
        kind = "link" if f["kind"] == "link" else "inline code"
        cands = " / ".join(_show(c, root) for c in f["candidates"])
        lines.append(f"- {BT}{f['path']}{BT} ({kind}、 {where_of[f['reason']]}) → {cands}")
    lines.append(
        "直し方: link の href は絶対 path か上のフォルダからの path に、 inline code は上のフォルダからの path に"
        "書き直して、 最終メッセージ全体を出し直してください (候補が複数なら意図した方)。 "
        "フォルダの外の file は絶対 path でも右パネルで開けないことがあります — "
        "その場合は内容を本文に出すか open で開く。 "
        "開けない形を例として見せたいだけなら fenced code block に入れる。 "
        f"正本 = {DOC}"
    )
    return "\n".join(lines)


def hook_reason(transcript_path: str) -> str:
    """Stop hook 用: 開けない参照があれば reason 文、 無ければ空文字。"""
    import transcript_turns as tt

    entries = tt.load_entries(transcript_path)
    if session_entrypoint(entries) not in PANEL_ENTRYPOINTS:
        return ""
    final, _ = tt.current_turn_final(entries)
    root, cwds = session_root_and_cwds(entries)
    if not final or not root:
        return ""
    findings = find_broken(final, root, cwds, extra_roots=session_additional_dirs(entries))
    return build_reason(findings, os.path.normpath(root)) if findings else ""


def calibrate(days: float, show: int = 40, context: bool = False) -> None:
    """過去の transcript の各 turn の最終発話に当て、 発火数と中身を出す (hook-authoring.md#text-pattern-stop-hook)。
    新しい session から順に show 件。 context=True で参照の前後の文も出す (目で仕分けるとき)。
    ⚠️ transcript は local の private data — 出力を公開の場所に貼らない。 file system は今の状態で判定する。"""
    import glob
    import time
    from collections import Counter

    import transcript_turns as tt

    cut = time.time() - days * 86400
    files = sorted((f for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
                    if os.path.getmtime(f) >= cut), key=os.path.getmtime, reverse=True)
    n_turns = n_fire = n_link = shown = 0
    reasons: Counter = Counter()
    git_cache: dict = {}
    for f in files:
        entries = tt.load_entries(f)
        if session_entrypoint(entries) not in PANEL_ENTRYPOINTS:
            continue
        upto: list[dict] = []
        for turn in tt.turns(entries):
            upto.extend(turn)
            final, _ = tt.summarize(turn)
            if not final:
                continue
            n_turns += 1
            root, cwds = session_root_and_cwds(upto)
            fs = find_broken(final, root, cwds, extra_roots=session_additional_dirs(upto),
                             git_cache=git_cache) if root else []
            if not fs:
                continue
            n_fire += 1
            n_link += any(x["kind"] == "link" for x in fs)
            reasons.update(f"{x['kind']}/{x['reason']}" for x in fs)
            if shown < show:
                shown += 1
                print(os.path.basename(f)[:8], [(x["kind"], x["reason"], x["path"], len(x["candidates"])) for x in fs])
                if context:
                    for x in fs:
                        i = final.find(x["raw"])
                        print("    …" + final[max(0, i - 80):i + len(x["raw"]) + 50].replace("\n", " ⏎ ") + "…")
    print(f"transcripts={len(files)} turns={n_turns} fired={n_fire} (link を含む {n_link}) 内訳={dict(reasons)}")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if len(sys.argv) == 3 and sys.argv[1] == "hook":
        try:
            out = hook_reason(sys.argv[2])
        except Exception:
            out = ""  # fail-open
        if out:
            print(out)
    elif len(sys.argv) in (3, 4) and sys.argv[1] == "calibrate" and sys.argv[3:] in ([], ["--context"]):
        calibrate(float(sys.argv[2]), context=bool(sys.argv[3:]))
    else:
        print("usage: chat_file_refs.py hook <transcript.jsonl> | calibrate <days> [--context]", file=sys.stderr)
        sys.exit(2)
