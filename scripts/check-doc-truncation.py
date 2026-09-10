#!/usr/bin/env python3
"""check-doc-truncation.py — 台帳 doc の「黙って消える」削除を git 高水位で検出（表の行/list/見出し/entry の大幅減、[truncation-ok] で baseline reset、config 駆動）

なぜ要るか
----------
**消えたこと自体が何の信号も出さない削除**がある。表を 1 つ丸ごと落としても、link 検査は通り、
test も通り、build も通る。壊れるものが無いので誰も気づかない。後から見ると「元々無かった」の
と区別がつかない。

起源 (2026-09-10): 「赤入れ → 予防機構の対応表」を、別の節を pointer 化する編集のついでに
丸ごと消した。気づいたのは偶然 (行を追記しようとした編集 script の assert が落ちた)。
本 script を書いて実データに当てたところ、**手で「復元した」と言った直後の状態を不足で flag し、
3 節がまだ消えたままだったことが判明した** (= 手作業の復元より機械の方が正確だった)。

同型は繰り返し起きる:
  - 様式を組み直すと様式の骨格が黙って消える
  - 誤りと確定した旧値を表から消すと、残存を検査できなくなる (捨てた情報は検査できない)
  - ledger の entry が大量に消えて日単位で未検出

述語
----
working tree の「数えられる要素」数を、当該 file を触った直近 `window` commit の各 snapshot と
比較し、**過去のどこかの snapshot より閾値以上少なければ** 🔴。

  閾値 = max(drop_min, base × drop_frac)   ← **比例させるのが要点**
  固定値だけだと大きい doc で誤検出する (実測: 239 要素の doc で -5 は誤差)。

  - 復元すれば finding は自然に消える (truncated snapshot は max に寄与しない = self-heal)
  - 意図的な大量削除は commit message に `[truncation-ok]` を含めると、それより古い snapshot を
    baseline から外す
  - marker 規約より前の正当な削減は config の `acks:` で個別に許す (理由必須)

⚠️ **無差別に全 doc へ当てない**。memory file の縮退 (MOVE + pointer 化) のように、
**意図的に縮めるのが正しい運用**の doc がある。対象は config で明示する。

config (yaml):
    window: 20            # 遡る commit 数 (任意、既定 20)
    drop_min: 4           # 最低これだけ減ったら候補 (任意)
    drop_frac: 0.05       # base のこの割合以上減ったら候補 (任意)
    targets:
      - repo: <root からの repo 名>
        path: <repo 内の path>
        kind: md | yaml
        label: <何のための台帳か>
    acks:
      - path: <部分一致>
        reason: <なぜ減ってよいか。必須>

使い方: check-doc-truncation.py --config <config.yaml> [--root DIR] [--json] [--selftest]
終了コード 0 固定 (= surface のみ、呼び出し元を殺さない)。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RESET_MARKER = "[truncation-ok]"
# git-crypt の blob は `git show` だと暗号のまま返る (先頭 \0GITCRYPT)。数えると 0 になり、
# **黙って監視対象から外れる** = この script が防ごうとしている失敗そのもの。
# `git cat-file --filters` は smudge filter を通すので、unlock 済なら平文で読める。
_GITCRYPT = "\x00GITCRYPT"
# 履歴の走査は 1 file あたり window 回の subprocess になる。file と HEAD が変わらなければ
# 結果も変わらないので (repo HEAD, rel, size, mtime) を key に cache する。
CACHE = Path.home() / ".local/state/claude-doc-truncation/high-water.json"

_MD_TABLE = re.compile(r"^\s*\|")
_MD_SEP = re.compile(r"^\s*\|[\s:|-]+\|?\s*$")
_MD_LIST = re.compile(r"^\s*[-*] ")
_MD_HEAD = re.compile(r"^#{1,6} ")
_YAML_ITEM = re.compile(r"^\s{0,4}- ")


def count(text: str, kind: str) -> int:
    """数えられる構造要素の数。md = 表の行 + list + 見出し / yaml = 浅い list 項目。"""
    n = 0
    for ln in text.splitlines():
        if kind == "md":
            if _MD_TABLE.match(ln) and not _MD_SEP.match(ln):
                n += 1
            elif _MD_LIST.match(ln) or _MD_HEAD.match(ln):
                n += 1
        else:
            if _YAML_ITEM.match(ln):
                n += 1
    return n


def git(repo: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=25)
        return r.stdout if r.returncode == 0 else ""
    except Exception:                            # noqa: BLE001 — 呼び出し元を殺さない
        return ""


def _blob(repo: Path, sha: str, rel: str) -> str:
    """履歴の中身を平文で得る。git-crypt でも読めるよう smudge filter を通す。"""
    out = git(repo, "cat-file", "--filters", f"{sha}:{rel}")
    if out and not out.startswith(_GITCRYPT):
        return out
    out = git(repo, "show", f"{sha}:{rel}")
    return "" if out.startswith(_GITCRYPT) else out


def high_water(repo: Path, rel: str, kind: str, window: int) -> tuple[int, str]:
    log = git(repo, "log", f"-{window}", "--format=%H%x1f%s", "--", rel)
    best, best_sha = 0, ""
    for line in log.splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        if RESET_MARKER in subject:
            break                                # これより古い snapshot は見ない
        blob = _blob(repo, sha, rel)
        if not blob:
            continue
        c = count(blob, kind)
        if c > best:
            best, best_sha = c, sha[:8]
    return best, best_sha


def _cache_load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_save(c: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(c), encoding="utf-8")
    except Exception:
        pass


def audit(root: Path, config: dict, use_cache: bool = True) -> list[tuple]:
    window = int(config.get("window", 20))
    drop_min = int(config.get("drop_min", 4))
    drop_frac = float(config.get("drop_frac", 0.05))
    acks = [(str(a.get("path", "")), str(a.get("reason", "")))
            for a in (config.get("acks") or []) if a.get("path") and a.get("reason")]
    out = []
    cache = _cache_load() if use_cache else {}
    n0 = len(cache)
    heads: dict[str, str] = {}
    for t in config.get("targets") or []:
        repo_name, rel = t.get("repo", ""), t.get("path", "")
        kind = t.get("kind") or ("yaml" if rel.endswith((".yaml", ".yml")) else "md")
        label = t.get("label", "")
        f = root / repo_name / rel
        if not f.exists():
            continue                             # fail-open (未 clone の機械)
        cur = count(f.read_text(encoding="utf-8", errors="replace"), kind)
        repo_path = root / repo_name
        if repo_name not in heads:
            heads[repo_name] = git(repo_path, "rev-parse", "HEAD").strip()[:12]
        key = None
        if use_cache:
            try:
                st = f.stat()
                key = f"{repo_name}|{rel}|{heads[repo_name]}|{st.st_size}|{int(st.st_mtime)}|{window}"
            except OSError:
                key = None
        if key and key in cache:
            base, sha = cache[key]
        else:
            base, sha = high_water(repo_path, rel, kind, window)
            if key:
                cache[key] = [base, sha]
        if not base:
            continue
        thresh = max(drop_min, int(base * drop_frac))
        if cur > base - thresh:
            continue
        full = f"{repo_name}/{rel}"
        ack = next((r for p, r in acks if p and p in full), None)
        if ack:
            continue                             # 理由つきで許した削減
        out.append(("🔴", "DOC_TRUNCATED",
                    f"{full}{f' ({label})' if label else ''}: 要素 {cur} 件 — 直近 {window} "
                    f"commit の最大 {base} 件 ({sha}) より {base - cur} 件少ない "
                    f"(閾値 {thresh})。意図的なら commit message に {RESET_MARKER}、"
                    f"過去分なら config の acks に理由つきで"))
    if use_cache and len(cache) != n0:
        _cache_save(cache)
    return out


def selftest() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        ok = ok and cond

    md = "# H\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n- x\n- y\n"
    check("md: 表の行・list・見出しを数える", count(md, "md") == 6)
    check("md: 区切り行は数えない", count("|---|---|\n", "md") == 0)
    check("yaml: entry を数える",
          count("a:\n  - id: x\n  - id: y\nb:\n  - p\n", "yaml") == 3)

    # 閾値の比例: 固定値だけだと大きい doc で誤検出する
    for base, cur, want in [(72, 66, True), (239, 234, False), (81, 34, True), (20, 17, False)]:
        thresh = max(4, int(base * 0.05))
        got = cur <= base - thresh
        check(f"閾値: {base}→{cur} は {'発火' if want else '沈黙'}", got == want)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo = root / "r"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=False)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e"], check=False)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=False)
        doc = repo / "led.md"
        doc.write_text("\n".join(f"| r{i} | x |" for i in range(30)) + "\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "led.md"], check=False)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "full"], check=False)
        cfg = {"targets": [{"repo": "r", "path": "led.md", "kind": "md"}]}
        check("git: 減っていなければ silent", audit(root, cfg, use_cache=False) == [])
        doc.write_text("\n".join(f"| r{i} | x |" for i in range(20)) + "\n", encoding="utf-8")
        check("git: 高水位から減れば 🔴",
              [c for _, c, _ in audit(root, cfg, use_cache=False)] == ["DOC_TRUNCATED"])
        cfg_ack = dict(cfg, acks=[{"path": "r/led.md", "reason": "意図的"}])
        check("git: ack があれば黙る", audit(root, cfg_ack, use_cache=False) == [])
        subprocess.run(["git", "-C", str(repo), "add", "led.md"], check=False)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm",
                        f"slim {RESET_MARKER}"], check=False)
        check("git: [truncation-ok] 以降が baseline", audit(root, cfg, use_cache=False) == [])
        check("git: repo 不在は fail-open",
              audit(root, {"targets": [{"repo": "nope", "path": "x.md"}]},
                    use_cache=False) == [])
        check("git-crypt: 暗号 blob を平文と誤認しない",
              count("\x00GITCRYPT\x00binary", "md") == 0)

    print("\n" + ("✅ selftest PASS" if ok else "❌ selftest FAIL"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", type=Path)
    ap.add_argument("--root", type=Path, default=Path.home() / "Claude")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.config or not a.config.exists():
        print("--config <yaml> が要る (対象は明示する = 無差別に全 doc へ当てない)",
              file=sys.stderr)
        return 0
    try:
        import yaml
        cfg = yaml.safe_load(a.config.read_text(encoding="utf-8")) or {}
        f = audit(a.root, cfg)
    except Exception as e:                       # noqa: BLE001
        print(f"(check-doc-truncation: skip — {e})", file=sys.stderr)
        return 0
    if a.json:
        print(json.dumps([{"severity": s, "code": c, "message": m} for s, c, m in f],
                         ensure_ascii=False, indent=2))
        return 0
    if not f:
        return 0
    print("📉 台帳 doc の切り詰め (= 消えても壊れないので誰も気づかない削除)")
    for sev, code, msg in f:
        print(f"   {sev} {code}: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
