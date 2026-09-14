#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sot-registry-add.py — check-sot-drift.py の registry に topic を足す前に検査し、 通ったものだけ registry の書式で末尾に追記する

検査 (1 つでも落ちたら何も書かない):
  - home の実在・anchor id (home_section が slug 形なら `<a id="...">` を要求)・anchor token が home に literal で在る・topic 重複
  - 同じ engine の scan を新 topic だけで回し、 token が home 以外で pointer 無しに既に立っていれば拒否
    (= 登録した日から赤い topic を作らない)
  - 同じ engine の点検 (audit_registry) = 永久に鳴らない anchor / 語に見える anchor / 正本と結び付かない高頻度の
    pointer を拒否。 語に見える anchor は、 識別子・値・引用と読んで判断したら spec の audit_ack に理由を書けば通る
  書いた後に YAML として読めなければ元に戻す。

なぜ道具にしたか: 手書きで registry に足すたびに「token が home に literal で在るか」 を確かめ忘れると、
登録した瞬間から何も検出しない topic (= 永久に鳴らない検出器) が増える (実測)。
一般則 = claude-config/docs/convention-design-principles.md#literal-anchor-detector

使い方:

    sot-registry-add.py spec.json --base ROOT --registry REG.yaml            # 検査 + 追記
    sot-registry-add.py spec.json --base ROOT --registry REG.yaml --dry-run  # 検査だけ
    sot-registry-add.py --selftest

spec.json は 1 topic の object か、 その list:

    {"topic": "example-rule",
     "description": "…",
     "home": "docs/rules.md",
     "home_section": "example-rule",
     "anchor_tokens": ["規則を定義する文の固有の言い回し"],
     "pointer_patterns": ["example-rule"],
     "allow_globs": ["*/SESSION.md", "*/plans/*"],
     "audit_ack": {"識別子の形でない値": "値そのものを追う anchor"}}

- `home` は --base からの相対 path。
- `home_section` が slug 形 (英小文字・数字・`-`) でないとき (見出し文言や § 番号) は anchor id の存在検査をしない。
- `allow_globs` を省くと SESSION / SESSION-archive / plans の 3 つを入れる。 `pointer_patterns` を省くと topic 名。
- `--no-preview` で scan と点検を省く。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

DEFAULT_ALLOW = ["*/SESSION.md", "*/SESSION-archive.md", "*/plans/*"]
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def scalar(s) -> str:
    """plain YAML scalar when safe, single-quoted otherwise (digits alone would parse as int)."""
    s = str(s)
    return s if re.fullmatch(r"[A-Za-z][A-Za-z0-9._/-]*", s) else q(s)


def check(spec: dict, base: Path, registry_text: str) -> list[str]:
    errs = []
    for key in ("topic", "description", "home", "anchor_tokens"):
        if not spec.get(key):
            errs.append(f"missing {key}")
    if errs:
        return errs
    home = base / spec["home"]
    if not home.is_file():
        return [f"home not found: {spec['home']}"]
    text = home.read_text(encoding="utf-8", errors="replace")
    sec = spec.get("home_section", "")
    if sec and SLUG.match(str(sec)) and f'<a id="{sec}">' not in text:
        errs.append(f'anchor id <a id="{sec}"> not in {spec["home"]}')
    for tok in spec["anchor_tokens"]:
        if tok not in text:
            errs.append(f"anchor token not literally in home: {tok!r}")
    if re.search(rf"^- topic: {re.escape(spec['topic'])}\s*$", registry_text, re.M):
        errs.append(f"topic already registered: {spec['topic']}")
    return errs


def render(spec: dict) -> str:
    lines = [f"- topic: {spec['topic']}",
             f"  description: {q(spec['description'])}",
             f"  home: {spec['home']}",
             f"  home_section: {scalar(spec.get('home_section', '')) if spec.get('home_section') else ''}",
             "  anchor_tokens:"]
    lines += [f"  - {q(t)}" for t in spec["anchor_tokens"]]
    ptr = spec.get("pointer_patterns") or [spec["topic"]]
    lines += ["  pointer_patterns:"] + [f"  - {scalar(p)}" for p in ptr]
    lines += ["  allow_globs:"] + [f"  - {q(g)}" for g in (spec.get("allow_globs") or DEFAULT_ALLOW)]
    if spec.get("audit_ack"):
        lines += ["  audit_ack:"] + [f"    {q(k)}: {q(v)}" for k, v in spec["audit_ack"].items()]
    return "\n".join(lines) + "\n"


def preview(specs: list[dict], base: Path, registry: Path, engine: Path | None = None) -> list[str]:
    """登録した瞬間に check-sot-drift.py が出す finding を、 書く前に出す (= 初日から赤い topic を作らない)。"""
    eng = engine or Path(__file__).with_name("check-sot-drift.py")
    if not eng.is_file():
        print(f"[info] {eng.name} not found: preview skipped")
        return []
    spec = importlib.util.spec_from_file_location("check_sot_drift", eng)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit as e:                 # the engine exits when PyYAML is missing
        print(f"[info] preview skipped: {e}")
        return []
    files = mod.load_files(base, registry) if hasattr(mod, "load_files") else None
    findings, _warn = mod.scan(base, {"window_lines": 15, "topics": specs}, registry, files=files) \
        if files is not None else mod.scan(base, {"window_lines": 15, "topics": specs}, registry)
    out = [f"{f['topic']}: token {f['token']!r} already stands without a pointer at {f['rel']}:{f['lineno']}"
           for f in findings]
    # registry 自体の点検 (= 登録した日から鳴らない anchor / 語そのものの anchor / 広すぎる pointer を書く前に止める)。
    # 語に見える anchor は、 読んで正当 (識別子・値・引用) と判断したら spec の audit_ack に理由を書けば通る。
    if hasattr(mod, "audit_registry"):
        for a in mod.audit_registry(base, {"topics": specs}, registry, files=files):
            out.append(f"{a['topic']}: audit {a['kind']} {a['subject']!r}: {a['detail']}"
                       f" → {mod.AUDIT_ADVICE.get(a['kind'], '')}")
    return out


def add(specs: list[dict], base: Path, registry: Path, dry_run: bool, do_preview: bool = True,
        engine: Path | None = None) -> int:
    specs = [dict(s, allow_globs=s.get("allow_globs") or DEFAULT_ALLOW,
                  pointer_patterns=s.get("pointer_patterns") or [s.get("topic")]) for s in specs]
    reg_text = registry.read_text(encoding="utf-8")
    all_errs = {}
    seen = set()
    for s in specs:
        errs = check(s, base, reg_text)
        if s.get("topic") in seen:
            errs.append("topic duplicated within this spec")
        seen.add(s.get("topic"))
        if errs:
            all_errs[s.get("topic", "?")] = errs
    for t, errs in all_errs.items():
        for e in errs:
            print(f"[REFUSED] {t}: {e}")
    if not all_errs and do_preview:
        for line in preview(specs, base, registry, engine):
            all_errs.setdefault(line.split(":")[0], []).append(line.split(": ", 1)[1])
            print(f"[REFUSED] {line}")
        if all_errs:
            print("  fix: add a pointer next to that text, add the path to allow_globs, or pick a token only the home has")
    if all_errs:
        print("nothing written")
        return 1
    for s in specs:
        print(f"[OK] {s['topic']}: home, anchor, {len(s['anchor_tokens'])} token(s), not yet registered")
    if dry_run:
        return 0
    new_text = reg_text.rstrip("\n") + "\n" + "".join(render(s) for s in specs)
    backup = registry.read_bytes()
    registry.write_text(new_text, encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(registry.read_text(encoding="utf-8"))
        names = [t.get("topic") for t in data.get("topics", [])]
        missing = [s["topic"] for s in specs if s["topic"] not in names]
        if missing:
            raise ValueError(f"not visible after write: {missing}")
    except ImportError:
        print("[info] PyYAML not installed: parse check skipped")
    except Exception as e:                                          # noqa: BLE001
        registry.write_bytes(backup)
        print(f"[REFUSED] registry did not parse after the write, restored: {e}")
        return 1
    print(f"appended {len(specs)} topic(s) to {registry}")
    return 0


def selftest() -> int:
    ok = True

    def c(label, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "repo").mkdir()
        (base / "repo" / "doc.md").write_text('## <a id="rule-x"></a>Rule X\nthe distinctive phrase\n', encoding="utf-8")
        reg = base / "reg.yaml"
        reg.write_text("window_lines: 15\ntopics:\n- topic: existing\n  description: 'd'\n  home: repo/doc.md\n"
                       "  home_section: rule-x\n  anchor_tokens:\n  - 'the distinctive phrase'\n", encoding="utf-8")
        good = {"topic": "rule-x", "description": "it's a rule", "home": "repo/doc.md", "home_section": "rule-x",
                "anchor_tokens": ["the distinctive phrase"]}
        c("a valid spec passes and is appended", add([good], base, reg, False) == 0 and "- topic: rule-x" in reg.read_text())
        c("the same topic cannot be added twice", add([good], base, reg, False) == 1)
        bad_tok = dict(good, topic="t2", anchor_tokens=["a phrase that is not there"])
        c("a token absent from home is refused  [foil: silent topic]", add([bad_tok], base, reg, False) == 1)
        bad_anchor = dict(good, topic="t3", home_section="no-such-anchor")
        c("a slug home_section without its <a id> is refused", add([bad_anchor], base, reg, False) == 1)
        heading = dict(good, topic="t4", home_section="記法の節 (見出し文言の例)")
        c("a non-slug home_section (heading text) is accepted without an anchor check",
          add([heading], base, reg, True) == 0)
        missing_home = dict(good, topic="t5", home="repo/nope.md")
        c("a missing home file is refused", add([missing_home], base, reg, False) == 1)
        before = reg.read_text()
        mixed = [dict(good, topic="t6"), bad_tok]
        c("one bad spec in a batch writes nothing", add(mixed, base, reg, False) == 1 and reg.read_text() == before)
        c("single quotes in the description are YAML-escaped", "'it''s a rule'" in reg.read_text())
        try:
            import yaml  # type: ignore
            c("the registry still parses as YAML", len(yaml.safe_load(reg.read_text())["topics"]) == 2)
        except ImportError:
            print("[SKIP] PyYAML not installed")
        eng = Path(__file__).with_name("check-sot-drift.py")
        (base / "repo" / "rule.md").write_text('<a id="rule-y"></a>\nthe second phrase\n', encoding="utf-8")
        (base / "other").mkdir()
        (base / "other" / "copy.md").write_text("intro\nthe second phrase restated here\n", encoding="utf-8")
        y = {"topic": "rule-y", "description": "d", "home": "repo/rule.md", "home_section": "rule-y",
             "anchor_tokens": ["the second phrase"]}
        before = reg.read_text()
        c("a token that already stands elsewhere without a pointer is refused  [foil: red on arrival]",
          add([y], base, reg, False, True, eng) == 1 and reg.read_text() == before)
        (base / "other" / "copy.md").write_text("see rule-y\nthe second phrase restated here\n", encoding="utf-8")
        c("the same text next to a pointer is accepted", add([y], base, reg, True, True, eng) == 0)
        (base / "other" / "copy.md").write_text("intro\nthe second phrase restated here\n", encoding="utf-8")
        c("--no-preview skips that check", add([y], base, reg, True, False, eng) == 0)
        # --- registry 自体の点検 ---
        (base / "repo" / "z.md").write_text("## Rule Z heading\nRule Z heading explained once.\n"
                                            "語の例 と 語の例 と 語の例\n", encoding="utf-8")
        z = {"topic": "rule-z", "description": "d", "home": "repo/z.md", "home_section": "Rule Z heading",
             "anchor_tokens": ["Rule Z heading explained"]}
        c("an anchor containing the home_section is refused  [foil: never fires]",
          add([z], base, reg, True, True, eng) == 1)
        z2 = dict(z, topic="rule-z2", home_section="", anchor_tokens=["語の例"])
        c("an anchor repeated in home (term-like) is refused", add([z2], base, reg, True, True, eng) == 1)
        z3 = dict(z2, topic="rule-z3", audit_ack={"語の例": "テスト: 識別子として正当"})
        c("the same anchor with audit_ack is accepted", add([z3], base, reg, True, True, eng) == 0)
        z4 = dict(z, topic="rule-z4", home_section="", pointer_patterns=["intro"],
                  anchor_tokens=["Rule Z heading explained"])
        for k in range(5):
            (base / "other" / f"n{k}.md").write_text("intro text\n", encoding="utf-8")
        c("a frequent pointer unrelated to home is refused  [broad pointer]", add([z4], base, reg, True, True, eng) == 1)
    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec", nargs="?", type=Path)
    ap.add_argument("--base", type=Path, help="home の相対 path の基点 (必須、 --selftest 以外)")
    ap.add_argument("--registry", type=Path, help="registry YAML (必須、 --selftest 以外)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-preview", action="store_true", help="skip the check-sot-drift preview")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.spec:
        ap.error("spec file required (or --selftest)")
    if not a.base or not a.registry:
        ap.error("--base と --registry が必要")
    data = json.loads(a.spec.read_text(encoding="utf-8"))
    return add(data if isinstance(data, list) else [data], a.base, a.registry, a.dry_run, not a.no_preview)


if __name__ == "__main__":
    sys.exit(main())
