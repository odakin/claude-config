#!/usr/bin/env python3
"""sot-registry-edit.py — check-sot-drift.py の registry を topic 単位の操作で行ごと書き換える (comment と書式を保つ)

YAML を読み書きし直すと注釈 comment が消えるので、 対象 topic の list block だけを行単位で書き換え、
書き換え後に読み直して「期待した anchor / pointer / allow / audit_ack になっているか」 を照合する。
1 つでも検査に落ちたら何も書かない。 一般則 = claude-config/docs/convention-design-principles.md#literal-anchor-detector

usage:
  sot-registry-edit.py OPS.json --registry REG.yaml --base ROOT [--dry-run]
  sot-registry-edit.py --selftest

OPS = {"<topic>": {"anchor_remove": [...], "anchor_add": [...],
                   "pointer_remove": [...], "pointer_add": [...],
                   "allow_remove": [...], "allow_add": [...],
                   "ack": {"<対象>": "<理由>"},
                   "note": "<書き換えの理由。 各 block に comment として残す>"}}

検査:
  - topic が在る / remove 対象が現に在る / anchor_add が home の 1 行にそのまま在る
  - anchor_add が pointer 判定 (pointer_patterns・home の file 名・home_section) に含まれない (= 永久に鳴らない anchor を作らない)
  - 書き換え後に anchor が 0 にならない / YAML として読め、 topic 数が変わらず、 各 field が期待どおり
操作後は check-sot-drift.py (scan と点検) を回して finding を確かめる。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML が必要: pip install pyyaml")

BLOCKS = {"anchor": "anchor_tokens", "pointer": "pointer_patterns", "allow": "allow_globs"}


def q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def plan(ops: dict, reg: dict, base: Path) -> tuple[list[str], dict]:
    by = {t.get("topic"): t for t in reg.get("topics", []) or []}
    errs, expect = [], {}
    for tp, o in ops.items():
        t = by.get(tp)
        if not t:
            errs.append(f"{tp}: topic が無い")
            continue
        new = {}
        for key, field in BLOCKS.items():
            cur = [str(x) for x in (t.get(field) or [])]
            for x in o.get(f"{key}_remove", []):
                if x not in cur:
                    errs.append(f"{tp}: {field} に無い: {x!r}")
            new[field] = [x for x in cur if x not in o.get(f"{key}_remove", [])] + \
                [x for x in o.get(f"{key}_add", []) if x not in cur]
        if not new["anchor_tokens"]:
            errs.append(f"{tp}: anchor が 0 になる")
        home = base / str(t.get("home", ""))
        lines = home.read_text(encoding="utf-8", errors="replace").splitlines() if home.is_file() else []
        pps = new["pointer_patterns"] + [Path(str(t.get("home", ""))).name] + \
            ([str(t["home_section"])] if t.get("home_section") else [])
        for a in o.get("anchor_add", []):
            if not any(a in ln for ln in lines):
                errs.append(f"{tp}: anchor_add が home の 1 行に無い: {a!r}")
            hit = [pp for pp in pps if pp and pp in a]
            if hit:
                errs.append(f"{tp}: anchor_add が pointer 判定 {hit} を含み、 書き写しても鳴らない: {a!r}")
        new["audit_ack"] = dict(t.get("audit_ack") or {}, **o.get("ack", {}))
        expect[tp] = new
    return errs, expect


def rewrite(src: str, ops: dict) -> str:
    L = src.split("\n")
    out: list[str] = []
    i, cur = 0, None
    present: dict[str, set] = {}
    while i < len(L):
        line = L[i]
        if line.startswith("- topic: "):
            cur = line[len("- topic: "):].strip().strip("'\"")
            present[cur] = set()
        o = ops.get(cur)
        key = next((k for k, f in BLOCKS.items() if line in (f"  {f}:", f"  {f}: []")), None)
        if o and key:
            field = BLOCKS[key]
            present[cur].add(field)
            out.append(f"  {field}:")
            i += 1
            block = []
            while i < len(L) and (L[i].startswith("  - ") or L[i].startswith("  #")):
                block.append(L[i])
                i += 1
            rm = set(o.get(f"{key}_remove", []))
            kept = [b for b in block if b.startswith("  #") or str(yaml.safe_load(b[4:])) not in rm]
            existing = {str(yaml.safe_load(b[4:])) for b in kept if b.startswith("  - ")}
            adds = [x for x in o.get(f"{key}_add", []) if x not in existing]  # 既に在る値は足さない (plan と同じ)
            if (rm or adds) and o.get("note"):
                kept.append(f"  # {o['note']}")
            kept += ["  - " + q(x) for x in adds]
            if not any(k.startswith("  - ") for k in kept):
                out[-1] = f"  {field}: []"
                out += [k for k in kept if k.startswith("  #")]
            else:
                out += kept
            if key == "anchor" and o.get("ack") and not _has_ack_after(L, i):
                out.append("  audit_ack:")
                out += [f"    {q(k)}: {q(v)}" for k, v in o["ack"].items()]
            continue
        if o and line == "  audit_ack:" and o.get("ack"):
            out.append(line)
            i += 1
            while i < len(L) and L[i].startswith("    "):
                out.append(L[i])
                i += 1
            out += [f"    {q(k)}: {q(v)}" for k, v in o["ack"].items()]
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _has_ack_after(L: list[str], i: int) -> bool:
    """同じ topic block の後ろに audit_ack が既にあるか (あればそちらに追記する)。"""
    while i < len(L) and not L[i].startswith("- topic: "):
        if L[i] == "  audit_ack:":
            return True
        i += 1
    return False


def apply(ops: dict, registry: Path, base: Path, dry_run: bool) -> int:
    src = registry.read_text(encoding="utf-8")
    reg = yaml.safe_load(src) or {}
    errs, expect = plan(ops, reg, base)
    # list block を持たない topic への add は行単位で追記できないので拒否 (= 手で block を足してから)
    by = {t.get("topic"): t for t in reg.get("topics", []) or []}
    for tp, o in ops.items():
        for key, field in BLOCKS.items():
            if o.get(f"{key}_add") and tp in by and field not in by[tp]:
                errs.append(f"{tp}: {field} の block が無いので追記できない")
    if errs:
        for e in errs:
            print(f"[REFUSED] {e}")
        print("nothing written")
        return 1
    text = rewrite(src, ops)
    reg2 = yaml.safe_load(text) or {}
    by2 = {t.get("topic"): t for t in reg2.get("topics", []) or []}
    bad = []
    for tp, exp in expect.items():
        t = by2.get(tp) or {}
        got = {f: [str(x) for x in (t.get(f) or [])] for f in BLOCKS.values()}
        got["audit_ack"] = dict(t.get("audit_ack") or {})
        if got != exp:
            bad.append(tp)
    if bad or len(reg2.get("topics", [])) != len(reg.get("topics", [])):
        print(f"[REFUSED] 書き換え後の照合に失敗: {bad}")
        print("nothing written")
        return 2
    for tp in ops:
        print(f"[OK] {tp}")
    if not dry_run:
        registry.write_text(text, encoding="utf-8")
        print(f"rewrote {len(ops)} topic(s) in {registry}")
    return 0


def selftest() -> int:
    ok = True

    def c(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "doc.md").write_text('<a id="rule-a"></a>\n## Rule A\n規則を定義する文はここ。\n用語 用語 用語\n', encoding="utf-8")
        reg = base / "reg.yaml"
        reg.write_text(
            "window_lines: 15\ntopics:\n"
            "- topic: rule-a\n  home: doc.md\n  home_section: rule-a\n"
            "  anchor_tokens:\n  # anchor の注釈は残る\n  - '用語'\n"
            "  pointer_patterns:\n  - rule-a\n  - '§9'\n"
            "  allow_globs:\n  - '*/SESSION.md'\n", encoding="utf-8")
        good = {"rule-a": {"anchor_remove": ["用語"], "anchor_add": ["規則を定義する文はここ"],
                           "pointer_remove": ["§9"], "allow_add": ["*/plans/*"],
                           "ack": {"x": "理由"}, "note": "語から定義文へ"}}
        c("dry-run は書かない", apply(good, reg, base, True) == 0 and "'用語'" in reg.read_text())
        c("適用すると期待どおり", apply(good, reg, base, False) == 0)
        t = yaml.safe_load(reg.read_text())["topics"][0]
        c("anchor 置換", t["anchor_tokens"] == ["規則を定義する文はここ"])
        c("pointer 削除", t["pointer_patterns"] == ["rule-a"])
        c("allow 追加", t["allow_globs"] == ["*/SESSION.md", "*/plans/*"])
        c("audit_ack 追加", t["audit_ack"] == {"x": "理由"})
        c("既存の注釈 comment が残る", "# anchor の注釈は残る" in reg.read_text())
        c("note が comment に残る", "# 語から定義文へ" in reg.read_text())
        before = reg.read_text()
        c("home に無い anchor_add は拒否", apply({"rule-a": {"anchor_add": ["存在しない文"]}}, reg, base, False) == 1)
        c("pointer 判定に含まれる anchor_add は拒否 [never fires]",
          apply({"rule-a": {"anchor_add": ["rule-a"]}}, reg, base, False) == 1)
        (base / "doc.md").write_text(base.joinpath("doc.md").read_text() + "rule-a の説明文\n", encoding="utf-8")
        c("pointer を含む文も拒否", apply({"rule-a": {"anchor_add": ["rule-a の説明文"]}}, reg, base, False) == 1)
        c("無い対象の remove は拒否", apply({"rule-a": {"pointer_remove": ["nope"]}}, reg, base, False) == 1)
        c("anchor を 0 にする操作は拒否",
          apply({"rule-a": {"anchor_remove": ["規則を定義する文はここ"]}}, reg, base, False) == 1)
        c("拒否した操作は何も書かない", reg.read_text() == before)
        c("既に在る値の add は重複させない (照合も通る)",
          apply({"rule-a": {"allow_add": ["*/SESSION.md"]}}, reg, base, False) == 0
          and yaml.safe_load(reg.read_text())["topics"][0]["allow_globs"] == ["*/SESSION.md", "*/plans/*"])
        c("2 回目の ack は既存 audit_ack に追記",
          apply({"rule-a": {"ack": {"y": "理由2"}}}, reg, base, False) == 0
          and yaml.safe_load(reg.read_text())["topics"][0]["audit_ack"] == {"x": "理由", "y": "理由2"})
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("ops", nargs="?", type=Path)
    ap.add_argument("--registry", type=Path)
    ap.add_argument("--base", type=Path, help="home の相対 path の基点")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.ops and a.registry and a.base):
        ap.error("OPS.json と --registry と --base が必要 (or --selftest)")
    return apply(json.loads(a.ops.read_text(encoding="utf-8")), a.registry, a.base, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
