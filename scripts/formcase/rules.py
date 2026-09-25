"""お手本 spec の中の「規則」 (= id + summary を持つ entry) を集める。

規則の id = ``<form id>/<rule id>``。 規則になる entry:
  - ``cells[]`` のうち ``rule:`` を持つもの
  - ``nittei.rules[]`` / ``cross_checks[]`` のうち ``summary:`` か ``same_as:`` を持つもの
``same_as: "<form>/<rule>"`` は本文 (summary / history / superseded) を別の規則から借りる
(= 様式に依らない規則を 2 か所に書かない)。

規則の本文の唯一の home は spec。 doc の表・checklist は views.py がここから描く。
"""
from __future__ import annotations

from . import specs as S

KEYS = ("label", "summary", "history", "superseded", "markers", "values", "same_as", "group", "value", "state")


def _add(out, sid, rid, entry, kind, refs):
    key = f"{sid}/{rid}"
    if key in out:
        raise ValueError(f"規則 id が重複: {key}")
    r = {"id": key, "form": sid, "kind": kind, "refs": refs}
    for k in KEYS:
        if entry.get(k) is not None:
            r[k] = entry[k]
    out[key] = r


def all_rules() -> dict:
    out = {}
    for sid, spec in S.all_specs().items():
        for e in spec.get("cells") or []:
            if e.get("rule"):
                refs = e["ref"] if isinstance(e["ref"], list) else [e["ref"]]
                _add(out, sid, e["rule"], e, "cell", [str(x) for x in refs])
        for r in (spec.get("nittei") or {}).get("rules") or []:
            if r.get("summary") or r.get("same_as"):
                _add(out, sid, r["id"], r, "nittei", ["日程表"])
        for x in spec.get("cross_checks") or []:
            if x.get("summary") or x.get("same_as"):
                _add(out, sid, x["id"], x, "cross", [x.get("expr", "")])
        main = (spec.get("meta") or {}).get("sheet") or ""
        for c in spec.get("controls") or []:            # form control の箱 (D9): 規則の所在 = sheet!anchor の箱
            if c.get("rule"):
                _add(out, sid, c["rule"], c, "control", [f"{c.get('sheet') or main}!{c.get('anchor')} の箱"])
    # same_as の解決 (1 段。 連鎖は禁止 = 読む人が辿れなくなる)
    for key, r in out.items():
        tgt = r.get("same_as")
        if not tgt:
            continue
        if tgt not in out:
            raise ValueError(f"{key}: same_as {tgt!r} が存在しない")
        if out[tgt].get("same_as"):
            raise ValueError(f"{key}: same_as の先 {tgt} がさらに same_as (連鎖禁止)")
        for k in ("summary", "history", "superseded", "markers", "values"):
            if k not in r and k in out[tgt]:
                r[k] = out[tgt][k]
        r.setdefault("label", out[tgt].get("label"))
    for key, r in out.items():
        if not r.get("summary"):
            raise ValueError(f"規則 {key} に summary が無い")
    return out


def cells_of(form_id: str, refs: list) -> list:
    """form の cells から ref の一致する entry を ref の順で返す (cells view 用)。"""
    spec = S.get(form_id)
    if spec is None:
        raise ValueError(f"form {form_id!r} の spec が無い")
    idx = {}
    for e in spec.get("cells") or []:
        for r in (e["ref"] if isinstance(e["ref"], list) else [e["ref"]]):
            idx[str(r)] = e
    missing = [r for r in refs if r not in idx]
    if missing:
        raise ValueError(f"form {form_id}: cells に ref {missing} が無い")
    return [(r, idx[r]) for r in refs]
