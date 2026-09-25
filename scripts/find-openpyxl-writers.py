#!/usr/bin/env python3
"""find-openpyxl-writers.py — 「openpyxl で読んで保存する script」 × 「その script が読む雛形が図形・form control・画像を持つ」 を列挙する fleet 検出 (紙から黙って消える経路の棚卸し、 office-automation.md#openpyxl-destroys-drawings)。

WHY: openpyxl の save は図形 (標題・区分の枠・様式番号・㊞)・form control・画像・拡張の入力規則を落とす。 様式の案件 pipeline
  (formcase) の外にも、 研究費申請・推薦書・案件 dir の旧 driver など openpyxl で保存する script が残っており、 それぞれが
  同じ機構で紙から見出しを消しうる (実測: ある申請様式の提出 xlsx から雛形の図と入力規則が消えていた)。
  RCA のたびに症状の名前で個別に直すのでなく、 経路の集合を機械で棚卸しする。

WHAT: root 配下の *.py で ``load_workbook(`` と ``.save(`` を両方含むものを候補にし、 script の中の xlsx / xlsm の文字列
  (相対 path は script の dir → repo の root の順に解決、 glob 可) を雛形として census (lib/office_census.py) を取る。
    ⚠️  紙に出るもの (図形・図形の字・form control・画像・条件付き書式) を持つ雛形を openpyxl で保存する script
    ⚪  雛形の path が script から静的に決まらない (未判定 = 黙らない)
    ✅  (既定では出さない) 雛形に紙に出るものが無い / 図形を移植し直す (graft_drawings) script
  分類の印: ``legacy_guard(`` を含む = 案件 dir の旧 driver (凍結 group は止まるが draft は今も openpyxl 経路で刷れる) /
  ``graft_drawings`` or ``formcase.drawings`` を含む = 移植あり (図形は戻る、 form control・画像は戻らない = ⚠️ のまま数を出す)。
  --exclude GLOB (繰り返し可) = 読むだけ・検査用の temp を書く script (engine / gate) を外す。 走査対象の repo と除外は
  呼び元 (個人層の shim) が渡す = この engine は path を持たない。

使い方:
  find-openpyxl-writers.py ROOT [ROOT ...] [--exclude 'claude-config/scripts/**'] [--all] [--json]
  find-openpyxl-writers.py --selftest
exit: 0 (件数は出力で。 検出器 = 止めない)
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import office_census as OC  # noqa: E402

PAPER_KEYS = ("図形", "図形の字", "form control", "画像", "条件付き書式")
SKIP_DIRS = {".git", "node_modules", "__pycache__", "site-packages", ".venv", "venv", "SESSION-archive"}
_XLSX_LIT = re.compile(r"""["']([^"'\n]*?\.xls[xm])["']""")


def _candidates(roots) -> list:
    out = []
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in fns:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dp, fn)
                try:
                    with open(p, "rb") as fh:
                        raw = fh.read()
                except OSError:
                    continue
                if raw.startswith(b"\x00GITCRYPT"):
                    continue
                s = raw.decode("utf-8", "replace")
                if os.path.abspath(p) == os.path.abspath(__file__):
                    continue                                    # 自分 (selftest の文字列) は候補にしない
                if "load_workbook(" in s and ".save(" in s:
                    out.append((p, s))
    return out


def _repo_root(p: str) -> str | None:
    d = os.path.dirname(os.path.abspath(p))
    while d and d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return None


def _resolve(script: str, lit: str) -> list:
    """script の中の xlsx の文字列を実 file に。 相対 = script の dir → repo root。 glob 可。 無ければ []。"""
    lit = os.path.expanduser(lit)
    bases = [os.path.dirname(os.path.abspath(script))]
    rr = _repo_root(script)
    if rr:
        bases.append(rr)
    cands = [lit] if os.path.isabs(lit) else [os.path.join(b, lit) for b in bases]
    out = []
    for c in cands:
        hits = glob.glob(c) if any(ch in c for ch in "*?[") else ([c] if os.path.isfile(c) else [])
        out += [h for h in hits if os.path.isfile(h)]
        if out:
            break
    return sorted(set(out))


def classify(src: str) -> str:
    if "formcase: superseded" in src:
        return "案内済"                      # 冒頭に「新しい案件は formcase へ」 と書いた旧 fill = 再実行しない (2026-09-25 D7)
    if "graft_drawings" in src or "formcase.drawings" in src or "formcase import drawings" in src:
        return "移植あり"
    if "legacy_guard(" in src:
        return "旧 driver"
    return "生"


def scan(roots, exclude=()) -> list:
    """[{script, kind, templates: [{path, counts, paper}], unresolved: [lit], status}]。 status = warn / unknown / ok。"""
    items = []
    for p, s in _candidates(roots):
        rel = os.path.abspath(p)
        if any(fnmatch.fnmatch(rel, os.path.expanduser(g)) or fnmatch.fnmatch(rel, "*/" + g.lstrip("/")) for g in exclude):
            continue
        lits = sorted(set(_XLSX_LIT.findall(s)))
        tpls, unresolved = [], []
        for lit in lits:
            hits = _resolve(p, lit)
            if not hits:
                unresolved.append(lit)
                continue
            for h in hits[:5]:
                try:
                    c = OC.census(h)["counts"]
                except Exception as e:  # noqa: BLE001
                    unresolved.append(f"{lit} (読めない: {type(e).__name__})")
                    continue
                paper = {k: c.get(k, 0) for k in PAPER_KEYS if c.get(k, 0)}
                tpls.append({"path": h, "counts": c, "paper": paper})
        kind = classify(s)
        if kind == "案内済":
            status = "superseded"
        elif "assert_no_paper_loss(" in s and any(t["paper"] for t in tpls):
            status = "guarded"                # 保存の直後に census の関門 (減れば止まる) = 紙に出るものは守られる
        elif any(t["paper"] for t in tpls):
            status = "warn"
        elif not tpls:
            status = "unknown"
        else:
            status = "ok"
        items.append({"script": rel, "kind": kind, "templates": tpls, "unresolved": unresolved, "status": status})
    return items


def render(items, show_all=False, home=None) -> list:
    home = home or str(Path.home())

    def short(p):
        return p.replace(home, "~")

    out = []
    legacy = [it for it in items if it["kind"] == "旧 driver" and it["status"] != "ok"]
    superseded = [it for it in items if it["status"] == "superseded"]
    guarded = [it for it in items if it["status"] == "guarded"]
    for it in sorted(items, key=lambda x: (x["status"] != "warn", x["status"] != "unknown", x["script"])):
        if it["status"] == "ok" and not show_all:
            continue
        if (it in legacy or it in superseded or it in guarded) and not show_all:
            continue                                            # 下で 1 行に畳む (凍結 guard あり = 止まる経路 / 案内済 / 関門あり)
        tag = f" [{it['kind']}]" if it["kind"] != "生" else ""
        if it["status"] == "warn":
            for t in it["templates"]:
                if not t["paper"]:
                    continue
                keep = "図形は移植で戻る、 " if it["kind"] == "移植あり" else ""
                out.append(f"⚠️ {short(it['script'])}{tag}: openpyxl で保存 × 雛形 {os.path.basename(t['path'])} に "
                           + " / ".join(f"{k} {v}" for k, v in t["paper"].items())
                           + f" ({keep}保存で紙から消える。 保存の直後に census を入れるか、 Excel で書く経路へ)")
        elif it["status"] == "unknown":
            why = "雛形の path が script の中に無い" if not it["unresolved"] else "雛形が見つからない: " + ", ".join(it["unresolved"][:3])
            out.append(f"⚪ {short(it['script'])}{tag}: 未判定 ({why})")
        else:
            out.append(f"✅ {short(it['script'])}{tag}: 雛形に紙に出るものが無い")
    if guarded and not show_all:
        out.append(f"✅ 保存の直後に census の関門がある script {len(guarded)} 本 (紙に出るものが減れば止まる): "
                   + ", ".join(os.path.basename(it["script"]) for it in guarded[:8]) + (" …" if len(guarded) > 8 else ""))
    if superseded and not show_all:
        out.append(f"⚪ 案内済 (formcase へ、 再実行しない) {len(superseded)} 本: "
                   + ", ".join(os.path.basename(it["script"]) for it in superseded[:8]) + (" …" if len(superseded) > 8 else ""))
    if legacy and not show_all:
        dirs = sorted({os.path.basename(os.path.dirname(it["script"])) for it in legacy})
        out.append(f"⚪ 旧 driver (案件 dir、 凍結 guard あり) {len(legacy)} 本は openpyxl で保存する経路のまま: "
                   + ", ".join(dirs[:8]) + (" …" if len(dirs) > 8 else "")
                   + " (凍結 group は止まる。 draft を作り直すなら formcase.py build へ。 --all で 1 本ずつ)")
    return out


def selftest() -> int:
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="find-openpyxl-writers-"))
    (d / ".git").mkdir()
    full, bare = OC._mk_xlsx(), OC._mk_xlsx(with_drawing=False, with_ctrl=False, with_x14=False, with_cf=False)
    (d / "forms").mkdir()
    (d / "forms" / "with_shapes.xlsx").write_bytes(full)
    (d / "forms" / "plain.xlsx").write_bytes(bare)
    (d / "a_fill.py").write_text("from openpyxl import load_workbook\nwb = load_workbook('forms/with_shapes.xlsx')\nwb.save('out.xlsx')\n")
    (d / "b_plain.py").write_text("import openpyxl\nwb = openpyxl.load_workbook('forms/plain.xlsx')\nwb.save('o.xlsx')\n")
    (d / "c_dyn.py").write_text("import openpyxl, sys\nwb = openpyxl.load_workbook(sys.argv[1])\nwb.save(sys.argv[2])\n")
    (d / "d_graft.py").write_text("from formcase import drawings as DR\nfrom openpyxl import load_workbook\nwb = load_workbook('forms/with_shapes.xlsx')\nwb.save('t.xlsx')\nDR.graft_drawings('a', 't.xlsx')\n")
    (d / "e_read.py").write_text("from openpyxl import load_workbook\nwb = load_workbook('forms/with_shapes.xlsx')\nprint(wb.sheetnames)\n")
    (d / "f_super.py").write_text("# formcase: superseded — 新しい案件は formcase へ\nfrom openpyxl import load_workbook\nwb = load_workbook('forms/with_shapes.xlsx')\nwb.save('s.xlsx')\n")
    (d / "g_guard.py").write_text("from openpyxl import load_workbook\nwb = load_workbook('forms/with_shapes.xlsx')\nwb.save('g.xlsx')\nimport office_census as _oc; _oc.assert_no_paper_loss('forms/with_shapes.xlsx', 'g.xlsx')\n")
    (d / "engine").mkdir()
    (d / "engine" / "x.py").write_text("from openpyxl import load_workbook\nwb = load_workbook('../forms/with_shapes.xlsx')\nwb.save('z.xlsx')\n")
    items = scan([str(d)], exclude=[str(d / "engine" / "*")])
    by = {os.path.basename(i["script"]): i for i in items}
    fails = 0

    def expect(label, cond, detail=""):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + label + ("" if cond else f": {detail}"))
        fails += not cond

    expect("図形つき雛形 × openpyxl 保存 = warn", by.get("a_fill.py", {}).get("status") == "warn", by.get("a_fill.py"))
    expect("図形の無い雛形 = ok (既定では出さない)", by.get("b_plain.py", {}).get("status") == "ok", by.get("b_plain.py"))
    expect("path が静的に決まらない = 未判定", by.get("c_dyn.py", {}).get("status") == "unknown", by.get("c_dyn.py"))
    expect("移植ありは印つきで warn (form control・画像は戻らない)", by.get("d_graft.py", {}).get("kind") == "移植あり"
           and by["d_graft.py"]["status"] == "warn", by.get("d_graft.py"))
    expect("読むだけ (.save 無し) は候補にしない", "e_read.py" not in by, list(by))
    expect("冒頭に formcase: superseded = 案内済 (数えない)", by.get("f_super.py", {}).get("status") == "superseded", by.get("f_super.py"))
    expect("保存の直後に assert_no_paper_loss = 関門あり (⚠️ にしない)", by.get("g_guard.py", {}).get("status") == "guarded", by.get("g_guard.py"))
    lg = render(items)
    expect("render: 案内済と関門ありは 1 行ずつに畳む", any(x.startswith("⚪ 案内済") and "f_super.py" in x for x in lg)
           and any(x.startswith("✅ 保存の直後に census") and "g_guard.py" in x for x in lg), lg)
    expect("--exclude で engine を外す", "x.py" not in by, list(by))
    ls = render(items)
    expect("render: ⚠️ と ⚪ が出て、 ✅ は関門ありの 1 行だけ (紙に出るものが無い script は出ない)",
           any(x.startswith("⚠️") for x in ls) and any(x.startswith("⚪") for x in ls)
           and not any(x.startswith("✅") and "関門" not in x for x in ls), ls)
    print("ALL PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--exclude", action="append", default=[], help="glob (script の絶対 path に当てる、 繰り返し可)")
    ap.add_argument("--all", action="store_true", help="✅ (問題なし) も出す")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.roots:
        ap.error("ROOT を指定")
    items = scan([os.path.expanduser(r) for r in a.roots], exclude=a.exclude)
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0
    lines = render(items, show_all=a.all)
    if lines:
        n_warn = sum(1 for x in lines if x.startswith("⚠️"))
        n_unk = sum(1 for x in lines if x.startswith("⚪"))
        print(f"📎 openpyxl で保存する script × 図形を持つ雛形: ⚠️ {n_warn} / 未判定 ⚪ {n_unk} "
              "(層1 find-openpyxl-writers.py、 office-automation.md#openpyxl-destroys-drawings)")
        print("\n".join("   " + x for x in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
