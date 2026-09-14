"""permission_rules.py — settings.json の permission rule を宣言した形に揃える (engine)

settings.json は machine-local (git 非同期) なので、 あるマシンで直した rule は他マシンに
届かない。 本 module は「必ず在るべき rule」 と「絞る前の旧 rule → 置き換え先」 を宣言として
受け取り、 監査 (足りない / 旧 rule が残っている) と適用 (冪等に揃える) を提供する。
個人層の宣言 (= どの rule が必須か) を git に載せ、 session 開始の auto-apply 層から毎回
呼ぶ使い方を想定する。 規約 = conventions/multi-machine-state.md#gate-rules-reassert-every-session

spec の形 (kind = "ask" / "deny" / "allow"):
  {"ask": {"required": ["Bash(*mailer.py*--send*)"],
           "superseded": {"Bash(*mailer.py*)": "Bash(*mailer.py*--send*)"}}}

  required   = 在るべき rule (文字列完全一致)。 足りなければ末尾に追加
  superseded = 旧 rule → 置き換え先。 旧 rule は同じ位置で置き換える (置き換え先が既に在れば削除)
               ⚠️ rule を絞ったときは旧 rule を必ずここに書く。 新 rule を足すだけだと広い旧 rule が
               残り、 絞った意味が無い (ask なら誤爆が続く / allow なら広い許可が残る)

宣言に無い rule には触らない (= 他の層・user が足した rule を消さない)。 書き込みは symlink の
実体に対して行う (= 複数 config dir が 1 file を共有する構成を壊さない)。

CLI = scripts/sync-permission-rules.py。 python3 permission_rules.py で selftest。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

KINDS = ("allow", "ask", "deny")


def _rules(data: dict, kind: str) -> list:
    return ((data.get("permissions") or {}).get(kind)) or []


def audit(settings_path: Path, spec: dict) -> list[str]:
    """揃っていない点を 1 行ずつ返す (空 = 揃っている)。 読めなければ例外。"""
    data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    out = []
    for kind, s in spec.items():
        if kind not in KINDS:
            raise ValueError(f"未知の kind: {kind}")
        rules = _rules(data, kind)
        for r in s.get("required", []):
            if r not in rules:
                out.append(f"{kind} に無い: {r}")
        for old in s.get("superseded", {}):
            if old in rules:
                out.append(f"{kind} に旧 rule が残っている: {old}")
    return out


def apply(settings_path: Path, spec: dict) -> list[str]:
    """宣言どおりに揃えて変更内容を返す (空 = 変更なし、 冪等)。 読めなければ例外 (= 書かない)。"""
    p = Path(os.path.realpath(settings_path))
    data = json.loads(p.read_text(encoding="utf-8"))
    perms = data.setdefault("permissions", {})
    if not isinstance(perms, dict):
        raise ValueError("permissions が object でない")
    out = []
    for kind, s in spec.items():
        if kind not in KINDS:
            raise ValueError(f"未知の kind: {kind}")
        rules = perms.setdefault(kind, [])
        if not isinstance(rules, list):
            raise ValueError(f"permissions.{kind} が list でない")
        for old, new in s.get("superseded", {}).items():
            while old in rules:
                i = rules.index(old)
                if new in rules:
                    rules.pop(i)
                    out.append(f"{kind} から旧 rule を削除: {old} (= {new} が既に在る)")
                else:
                    rules[i] = new
                    out.append(f"{kind} の旧 rule を置換: {old} → {new}")
        for r in s.get("required", []):
            if r not in rules:
                rules.append(r)
                out.append(f"{kind} に追加: {r}")
    if out:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def forbidden_in_allow(paths: list[Path], pattern: str) -> list[tuple[Path, str]]:
    """allow に pattern (正規表現) を含む rule が残っている箇所を返す。 不在・読めない file は飛ばす。

    ask で守っている操作が allow にも書かれていると、 ask が消えた瞬間に確認なしで通る
    (= 過去の「常に許可」 の遺物が典型)。 自動削除はしない (= 報告用)。
    """
    rx = re.compile(pattern)
    hits = []
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for r in _rules(data, "allow"):
            if isinstance(r, str) and rx.search(r):
                hits.append((p, r))
    return hits


def selftest() -> int:
    import tempfile
    fails = []

    def ck(name, cond):
        if not cond:
            fails.append(name)

    new, old = "Bash(*mailer.py*--send*)", "Bash(*mailer.py*)"
    spec = {"ask": {"required": [new, "mcp__mail__send"], "superseded": {old: new}}}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        f = td / "s.json"
        f.write_text(json.dumps({"permissions": {"ask": ["x", old], "allow": ["Bash"]},
                                 "model": "m"}), encoding="utf-8")
        ck("audit: 旧 rule と欠落を報告", len(audit(f, spec)) == 3)
        ch = apply(f, spec)
        j = json.loads(f.read_text(encoding="utf-8"))
        ck("apply: 同じ位置で置換", j["permissions"]["ask"][:2] == ["x", new])
        ck("apply: 欠落を追加", "mcp__mail__send" in j["permissions"]["ask"])
        ck("apply: 他の key と rule を保持", j["model"] == "m" and j["permissions"]["allow"] == ["Bash"])
        ck("apply: 変更行", len(ch) == 2)
        ck("apply 後の audit は空", audit(f, spec) == [])
        ck("apply: 2 回目は空 (冪等)", apply(f, spec) == [])
        both = td / "b.json"
        both.write_text(json.dumps({"permissions": {"ask": [new, old]}}), encoding="utf-8")
        apply(both, spec)
        ck("apply: 旧新併存 → 旧を削除",
           json.loads(both.read_text(encoding="utf-8"))["permissions"]["ask"] == [new, "mcp__mail__send"])
        real, link = td / "real.json", td / "link.json"
        real.write_text(json.dumps({"permissions": {}}), encoding="utf-8")
        link.symlink_to(real)
        apply(link, spec)
        ck("apply: symlink を保ち実体を更新", link.is_symlink() and audit(real, spec) == [])
        broken = td / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        try:
            apply(broken, spec)
            ck("apply: 壊れた JSON は例外", False)
        except Exception:
            ck("apply: 壊れた JSON は書かない", broken.read_text(encoding="utf-8") == "{not json")
        try:
            apply(f, {"asks": {}})
            ck("apply: 未知の kind は例外", False)
        except ValueError:
            ck("apply: 未知の kind は ValueError", True)
        al = td / "allow.json"
        al.write_text(json.dumps({"permissions": {"allow": ["Bash", "mcp__mail__send"]}}), encoding="utf-8")
        hits = forbidden_in_allow([al, td / "none.json", broken], r"__send$")
        ck("forbidden_in_allow: 検出 + 不在/破損は飛ばす", hits == [(al, "mcp__mail__send")])
    if fails:
        print("permission_rules selftest FAIL:", fails)
        return 1
    print("permission_rules selftest: ALL PASS (12 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
