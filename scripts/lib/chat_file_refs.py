"""chat_file_refs.py — chat の最終発話にある file 参照 (markdown link の href と、 path に見える inline code) を、 Claude Code desktop app の右パネルと同じ基準で解決し、 開けないものに正しい path を添えて返す共通部品 (Stop hook chat-file-ref-enforce.sh と校正が共用)

解決の規則 (desktop app の bundle で確認、 正本 = conventions/claude-code-permissions.md#chat-link-resolution-base):
- 相対 path は **session を始めたときに選んだ folder** に連結する。 Bash の cd で harness が通知する
  「Primary working directory」 が変わっても、 この基準は変わらない。
- 絶対 path はそのまま、 `~/` は home に展開する。
- inline code の中身も、 `/` を含み拡張子で終わる path なら link として描かれる (観測 n=1、 `CLAUDE.md` のような
  区切りの無い名前は描かれなかった)。

検出の条件 (= 誤検出を避けるため狭くとる):
  開けない (基準 folder に連結すると存在しない / 基準の外に出る) ∧ 別の folder に連結すると存在する。
  別の folder = transcript に出た cwd (新しい順) → 基準 folder の直下の dir。
  どこにも無い path (例示の `path/to/file.md` など) は拾わない。
"""
from __future__ import annotations

import os
import re
from urllib.parse import unquote

FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]{0,3}\1[ \t]*$|\Z)", re.S | re.M)
CODE_SPAN_RE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
LINK_RE = re.compile(r"\[[^\]\n]*\]\(\s*<([^>\n]+)>[^)\n]*\)|\[[^\]\n]*\]\(\s*([^)\s]+)(?:\s+\"[^\"\n]*\")?\s*\)")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# inline code を link 候補とみなす形: 空白を含まず、 `/` を含み、 拡張子で終わる (行番号の後置は許す)
CODE_PATH_RE = re.compile(r"^[^\s`<>|*?\"']*/[^\s`<>|*?\"']*\.[A-Za-z0-9]{1,10}(?::\d+(?:[-:]\d+)?)?$")
LINE_SUFFIX_RE = re.compile(r":\d+(?:[-:]\d+)?$")


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def extract_refs(text: str) -> list[tuple[str, str, str]]:
    """最終発話 → [(kind, raw, path)]。 kind = "link" | "code"。 fenced block の中は描かれないので見ない。"""
    body = FENCE_RE.sub(_blank, text or "")
    refs: list[tuple[str, str, str]] = []
    for m in CODE_SPAN_RE.finditer(body):
        inner = m.group(2).strip()
        if CODE_PATH_RE.match(inner):
            refs.append(("code", m.group(0), inner))
    body = CODE_SPAN_RE.sub(_blank, body)  # code span の中の [..](..) は link として描かれない
    for m in LINK_RE.finditer(body):
        href = (m.group(1) or m.group(2) or "").strip()
        if href:
            refs.append(("link", m.group(0), href))
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


def find_broken(text: str, root: str, seen_cwds: list[str] | None = None, limit: int = 3,
                extra_roots: list[str] | None = None) -> list[dict]:
    """開けない参照のうち、 別の基準なら存在するもの。 [{kind, raw, path, reason, candidates}] (candidates は絶対 path)。
    extra_roots = session に追加したフォルダ。 `../` で基準の外に出ても、 連結した先がこの中に在れば app は開くので拾わない。"""
    if not root or not os.path.isdir(root):
        return []
    root = os.path.normpath(root)
    extras = [os.path.normpath(os.path.expanduser(d)) for d in (extra_roots or []) if d]
    dirs = None
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
        if cands:
            findings.append({"kind": kind, "raw": raw, "path": p, "reason": reason, "candidates": cands})
    return findings


def _env_snapshots(entries: list[dict]):
    for e in entries:
        a = e.get("attachment") if isinstance(e, dict) else None
        if isinstance(a, dict) and a.get("type") == "environment" and isinstance(a.get("snapshot"), dict):
            yield a["snapshot"]


def session_additional_dirs(entries: list[dict], settings_paths: list[str] | None = None) -> list[str]:
    """session に追加したフォルダ。 transcript の environment snapshot を優先し、 無ければ settings の additionalDirectories。"""
    out: list[str] = []
    for snap in _env_snapshots(entries):
        for d in snap.get("additionalWorkingDirectories") or []:
            if isinstance(d, str) and d not in out:
                out.append(d)
    if out:
        return out
    import json

    for sp in settings_paths if settings_paths is not None else [os.path.expanduser("~/.claude/settings.json")]:
        try:
            with open(sp, encoding="utf-8") as f:
                dirs = (json.load(f).get("permissions") or {}).get("additionalDirectories") or []
        except Exception:
            continue
        out.extend(d for d in dirs if isinstance(d, str) and d not in out)
    return out


def session_root_and_cwds(entries: list[dict]) -> tuple[str | None, list[str]]:
    """transcript → (session を始めた folder, 出現した cwd の新しい順の list)。
    session を始めた folder = 最初の environment snapshot の workingDirectory、 無ければ最初に現れた cwd。"""
    root = next((s.get("workingDirectory") for s in _env_snapshots(entries)
                 if isinstance(s.get("workingDirectory"), str)), None)
    order: list[str] = []
    for e in entries:
        c = e.get("cwd") if isinstance(e, dict) else None
        if not isinstance(c, str) or not c:
            continue
        if root is None:
            root = c
        if c in order:
            order.remove(c)
        order.append(c)
    return root, list(reversed(order))


def session_entrypoint(entries: list[dict]) -> str | None:
    for e in entries:
        ep = e.get("entrypoint") if isinstance(e, dict) else None
        if isinstance(ep, str) and ep:
            return ep
    return None


# ---- hook / 校正の入口 -------------------------------------------------------------

# 右パネルで file を開く frontend。 CLI (端末) には右パネルが無いので対象外。
PANEL_ENTRYPOINTS = ("claude-desktop", "claude-desktop-3p", "claude-vscode")  # 名前は engine の entrypoint 一覧で確認
DOC = "claude-config/conventions/claude-code-permissions.md#chat-link-resolution-base"
BT = chr(96)  # backtick


def _show(path: str, root: str) -> str:
    return os.path.relpath(path, root) if _inside(path, root) else path


def build_reason(findings: list[dict], root: str) -> str:
    lines = [
        f"🔗 chat-file-ref: 最終メッセージの file 参照 {len(findings)} 件が、 右パネルで開けません。 "
        f"desktop app は相対 path を session を始めたフォルダ ({root}) に連結します "
        f"(Bash の cd で変わる「作業ディレクトリ」 ではありません)。 "
        f"inline code の {BT}dir/file.ext{BT} もリンクとして描かれます。",
    ]
    for f in findings[:8]:
        kind = "link" if f["kind"] == "link" else "inline code"
        where = "フォルダの外" if f["reason"] == "outside" else "存在しない"
        cands = " / ".join(_show(c, root) for c in f["candidates"])
        lines.append(f"- {BT}{f['path']}{BT} ({kind}、 {where}) → {cands}")
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


def calibrate(days: float, show: int = 40) -> None:
    """過去の transcript の各 turn の最終発話に当て、 発火数と中身を出す (hook-authoring.md#text-pattern-stop-hook)。
    ⚠️ transcript は local の private data — 出力を公開の場所に貼らない。 file system は今の状態で判定する。"""
    import glob
    import time
    import transcript_turns as tt

    cut = time.time() - days * 86400
    files = sorted((f for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
                    if os.path.getmtime(f) >= cut), key=os.path.getmtime)
    n_turns = n_fire = n_link = shown = 0
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
            fs = find_broken(final, root, cwds, extra_roots=session_additional_dirs(upto)) if root else []
            if not fs:
                continue
            n_fire += 1
            n_link += any(x["kind"] == "link" for x in fs)
            if shown < show:
                shown += 1
                print(os.path.basename(f)[:8], [(x["kind"], x["path"], len(x["candidates"])) for x in fs])
    print(f"transcripts={len(files)} turns={n_turns} fired={n_fire} (link を含む {n_link})")


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
    elif len(sys.argv) == 3 and sys.argv[1] == "calibrate":
        calibrate(float(sys.argv[2]))
    else:
        print("usage: chat_file_refs.py hook <transcript.jsonl> | calibrate <days>", file=sys.stderr)
        sys.exit(2)
