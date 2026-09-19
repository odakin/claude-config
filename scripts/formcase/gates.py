"""gate を group の範囲で回す (= 凍結 group の sheet を今日の spec で裁かない / build 対象外の group を巻き込まない)。

- 対象 group の sheet は照合する
- 凍結 group の sheet は ``--frozen=`` (🧊 凍結 = 照合対象外 と表示)
- build 対象でない draft group の sheet は ``--out-of-scope=`` (🧊 この build の対象外 と表示)
gate 本体は engine が持たない (= 様式の記入規則は instance のもの): 設定の ``gates`` が script を宣言し、
様式ごとにどれを回すかを spec の ``meta.gates`` / 設定の ``gates_by_form`` / ``default_gates`` が決める。
docx 様式は docx の欄と overlay を spec と照合する内蔵 gate (docx_form.gate) だけ。
"""
from __future__ import annotations

import subprocess
import sys

from . import config as CF
from . import manifest as M
from . import specs as S


def scope_sheets(m: M.Manifest, doc_id: str, targets) -> tuple:
    doc = m.doc(doc_id)
    spec = S.get(doc.get("form"))
    if spec is None:
        raise M.ManifestError(f"{doc_id}: form {doc.get('form')!r} の spec が無い")
    tgt, frozen, other = set(), set(), set()
    for gid in (spec.get("groups") or {}):
        sheets = set(S.group_sheets(spec, gid, with_depends=False))
        if gid in targets:
            tgt |= sheets
        elif gid in (doc.get("groups") or {}) and m.group_is_frozen(doc_id, gid):
            frozen |= sheets
        else:
            other |= sheets
    frozen -= tgt
    other -= tgt | frozen
    return sorted(tgt), sorted(frozen), sorted(other)


def run_scoped(m: M.Manifest, doc_id: str, targets, raise_on_fail: bool = True) -> bool:
    from .recipes import BuildError

    wb = m.workbook(doc_id)
    form = m.doc(doc_id).get("form")
    spec = S.get(form)
    from . import docx_form as DF

    if DF.is_docx(spec):                      # Word 様式 = docx の欄と overlay.yaml を spec と照合 (group は 1 つ = 全体)
        ok, lines = DF.gate(spec, S.template_path(spec), wb)
        print("── 記入内容 gate (docx、 お手本 spec)")
        print("\n".join("   " + x for x in lines))
        if not ok and raise_on_fail:
            raise BuildError("gate FAIL → 出力を書かずに中断 (spec の方が古いなら spec を直して根拠を書く)")
        return ok
    _tgt, frozen, other = scope_sheets(m, doc_id, targets)
    flags = [f"--frozen={s}" for s in frozen] + [f"--out-of-scope={s}" for s in other]
    flags.append("--scoped")                  # group を明示した = 未着手 group の推定をさせない
    ok = True
    gates = CF.gates_for(form, spec)
    if not gates:
        print("── 記入内容 gate: 設定に gate が無い (= 記入内容を機械照合していない)")
    for g in gates:
        if not g["script"].exists():
            raise BuildError(f"gate {g['id']} の script が無い: {g['script']}")
        argv = [sys.executable, str(g["script"]), str(wb)] + (flags if g["scope_flags"] else []) + g["args"]
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        print(f"── {g['label']}")
        print("\n".join("   " + x for x in r.stdout.rstrip().splitlines()))
        if r.returncode != 0:
            ok = False
    if not ok and raise_on_fail:
        raise BuildError("gate FAIL → 出力を書かずに中断 (spec の方が古いなら spec を直して根拠を書く)")
    return ok
