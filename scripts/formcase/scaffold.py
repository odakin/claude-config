"""新しい案件を配布雛形から作る (= 前の案件の dir・driver・xlsx を写さない唯一の入口)。

``formcase.py new --form <spec id> --case <dir> --doc <id> [--workbook <name>.xlsx] [--todo <repo:id>]``:
  - <dir>/<workbook> = spec の配布雛形の copy (値は空)
  - <dir>/submission.yaml = document + spec の全 group (state draft、 出力名は recipe の既定)
  - <dir>/fill_<doc>.py = spec の「書く欄」 を全部並べた記入 stub (値は空 = 一次情報から埋める)
  - <dir>/README.md = 値の出典表の枠 (無ければ)
既に同じ document がある manifest には足さない (上書きしない)。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import config as CF
from . import manifest as M
from . import recipes as RC
from . import specs as S

STUB_HEAD = '''#!/usr/bin/env python3
"""{case} / {doc} の記入 (form {form})。 formcase.py new が生成した stub。

    python3 {name} [--group G]            # 値を Excel で書く (staging 経由) → 読み戻し → gate を回して結果を出す
    python3 {name} [--group G] --dry-run  # 書かずに、 空のまま残っている欄を一覧
  --group = その group の行だけ書き、 gate もその group だけ裁く (= 先に出す group / 後で出す group を分ける)

- 値は**一次情報** (主催者 program・本人回答・財源の登録値) から入れる。 前の案件の xlsx / driver から運ばない。
- 何を書くか・なぜ = お手本 spec ({spec}) の規則 (`formcase.py rules`)。 下の各行の comment は spec の label / summary の写しで、
  規則が変わったら spec が正 (= comment は生成時点の案内)。
- kind = text | number | date | textfmt (数値に見える文字列) | clear | formula | general (書式) | fontsize。 value=None の行は未記入 = 実行を止める。
  build の字の切れ gate (check-form-clipping) で止まった欄は (sheet, cell, 'fontsize', 7〜11, group) を足す。
  「書かない欄」 (空が正 / 雛形のまま) はここに出ない。 fixed の値は spec から入れてある。
- 住所・口座の値はこの file に書かない (workbook の欄にだけ入れる。 値の出所の pointer を comment に)。
- PDF を作る = `python3 {cli} build {case_rel} --doc {doc}`
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("{syspath}"))
from formcase.fill import run  # noqa: E402

DOC = "{doc}"
EDITS = [   # (sheet, cell, kind, value, group)
'''

STUB_TAIL = ''']

if __name__ == "__main__":
    sys.exit(run(__file__, DOC, EDITS))
'''


def _default_group(spec) -> str:
    """group を宣言していない cell は spec の最初の group (= 事前の書類) に属する。"""
    return next(iter(spec.get("groups") or {"-": None}))


def _kind(e) -> str:
    t = e.get("type")
    if t == "date":
        return "date"
    if t == "number":
        return "number"
    if t == "textfmt":
        return "textfmt"
    return "text"


def _looks_numeric_text(v) -> bool:
    """文字列だが Excel に渡すと数値・日付に化ける値 (実測: 数字だけの管理番号が数値になり gate FAIL)。"""
    return isinstance(v, str) and bool(re.fullmatch(r"[0-9０-９][0-9０-９/\-.]*", v.strip()))


def stub_text(spec, case_label, case_rel, doc, name, only_group: str | None = None) -> str:
    main = spec["meta"]["sheet"]
    lines = []
    for e in spec.get("cells") or []:
        st = e.get("state")
        if only_group and (e.get("group") or _default_group(spec)) != only_group:
            continue
        if e.get("font_size") and st not in ("filled", "fixed", "checkbox", "checkbox_pair", "checkbox_exclusive", "changed"):
            for r in (e["ref"] if isinstance(e["ref"], list) else [e["ref"]]):
                sheet, cell = (r.split("!", 1) if "!" in r else (main, r))
                lines.append(f"    ({sheet!r}, {cell!r}, 'fontsize', {e['font_size']}, "
                             f"{(e.get('group') or _default_group(spec))!r}),   # {e.get('label', '')}: 既定 font だと切れる")
            continue
        if st not in ("filled", "fixed", "checkbox", "checkbox_pair", "checkbox_exclusive", "changed"):
            continue
        refs = e["ref"] if isinstance(e["ref"], list) else [e["ref"]]
        expanded = []
        for r in refs:
            expanded.append(r)
        if st == "checkbox_pair":
            expanded += [e["pair"]] if isinstance(e.get("pair"), str) else list(e.get("pair") or [])
        note = e.get("summary") or e.get("label") or ""
        if e.get("when"):
            note += f"  (条件: {e['when']['cell']} == {e['when']['equals']} のとき)"
        grp = f" [group {e['group']}]" if e.get("group") else ""
        lines.append(f"    # --- {e.get('label', '')}{grp}: {' '.join(str(note).split())[:150]}")
        for r in expanded:
            if ":" in r and "!" not in r.split(":")[0]:
                lines.append(f"    # ({r} は範囲 = 必要な cell を個別に書く)")
                continue
            sheet, cell = (r.split("!", 1) if "!" in r else (main, r))
            grp_id = e.get("group") or _default_group(spec)
            if st == "fixed":
                val = repr(e.get("value"))
            elif st == "changed":
                lines.append(f"    # 雛形の値のままではいけない欄 (直し方 = spec の why: 数式なら kind 'formula'、 消すなら 'clear')")
                val = "None"
            else:
                val = "None"
            kind = "text" if st in ("fixed", "checkbox", "checkbox_pair", "checkbox_exclusive") else _kind(e)
            if st == "fixed" and (e.get("type") == "textfmt" or _looks_numeric_text(e.get("value"))):
                kind = "textfmt"      # 数字だけの文字列 (管理番号等) は Excel が数値に変える = 書式 @ で入れる
            if st == "fixed" and str(e.get("value") or "").startswith("="):
                kind = "formula"      # 雛形の欠陥を数式で直す欄。 書式 @ だと文字列で入る
                lines.append(f"    ({sheet!r}, {cell!r}, 'general', None, {grp_id!r}),")
            lines.append(f"    ({sheet!r}, {cell!r}, {kind!r}, {val}, {grp_id!r}),")
            if e.get("font_size"):
                lines.append(f"    ({sheet!r}, {cell!r}, 'fontsize', {e['font_size']}, {grp_id!r}),   # 既定 font だと切れる (spec の font_size)")
    n = spec.get("nittei") if only_group in (None, _default_group(spec)) else None
    if n:
        lines.append("    # --- 1 日 1 block の表 (block は日数に応じて上から使う) -------------------------------")
        lines.append(f"    # sheet = {n.get('sheet') or main!r} / block 先頭行 = {n.get('anchors')} / "
                     f"列 = {({k: v.get('col') for k, v in (n.get('roles') or {}).items()})}")
        for r in n.get("rules") or []:
            if r.get("summary"):
                lines.append(f"    #   規則 {r['id']}: {' '.join(r['summary'].split())[:150]}")
        lines.append("    #   例: (sheet, 'C10', 'text', None, '<group>'),  … 使わない block の placeholder は clear")
    head = STUB_HEAD.format(case=case_label, doc=doc, form=spec["meta"]["id"], name=name,
                            spec=spec["_path"].name, case_rel=case_rel, cli=CF.cli(),
                            syspath=CF.stub_sys_path())
    return head + "\n".join(lines) + "\n" + STUB_TAIL


README_TMPL = """# {case}

<!-- formcase:view kind=status -->
<!-- /formcase:view -->

- 状態 (どの書類を・いつ刷り・送り・出したか) の正本 = [`submission.yaml`](submission.yaml)。 上の表はその生成物で、 freeze / annotate / reopen が描き直す。 未提出・提出予定・印刷版・未決・返事待ちを README に手で書かない (`formcase.py lint` と pre-commit が止める。 状態の説明は `annotate --note`、 未決の問い・約束は案件の TODO)
- 何を書くか = お手本 spec `{spec_hint}` (`formcase.py rules`){process_hint}
- 記入 = `python3 fill_{doc}.py`、 PDF = `formcase.py build {case_rel} --doc {doc}`

## 値の出典 (規則は書かない = spec が正本。 ここは「その値をどこから取ったか」 だけ)

| 欄 | 値 | 出典 |
|---|---|---|
"""


def new_case(form_id: str, case_dir, doc: str, workbook: str | None = None, todo: str | None = None,
             group: str | None = None, from_doc: str | None = None) -> dict:
    """group = その group だけの document を作る。 from_doc = 同じ案件の document の workbook を base にする
    (= 後で出す group の sheet が先に出した group の sheet を数式参照する様式。 base にした workbook の copy を作る)。"""
    spec = S.get(form_id)
    if spec is None:
        raise M.ManifestError(f"form {form_id!r} の spec が無い (formcase.py rules で一覧)")
    rc = RC.recipe_for(form_id)
    if group is not None and group not in (spec.get("groups") or {}):
        raise M.ManifestError(f"spec {form_id!r} に group {group!r} が無い ({list(spec.get('groups') or {})})")
    case_dir = Path(case_dir).resolve()
    case_dir.mkdir(parents=True, exist_ok=True)
    mpath = case_dir / M.MANIFEST_NAME
    m = M.load(case_dir) if mpath.exists() else None
    notice = None
    if from_doc:
        if m is None or from_doc not in m.documents:
            raise M.ManifestError(f"--from-doc {from_doc!r} が {mpath} に無い (同じ案件の document から作る)")
        src_doc = m.doc(from_doc)
        if str(src_doc.get("form")) != str(form_id):
            raise M.ManifestError(f"--from-doc {from_doc} は form {src_doc.get('form')} (≠ {form_id})")
        base = m.workbook(from_doc)
        if base is None or not base.exists():
            raise M.ManifestError(f"--from-doc {from_doc} の workbook が無い")
        src_state = {g: (x.get("current") or {}).get("state") for g, x in (src_doc.get("groups") or {}).items()}
        if not any(s in M.FROZEN_STATES for s in src_state.values()):
            notice = (f"⚠️ {from_doc} はまだ提出の記録が無い ({src_state}) = base を直したらこの workbook も作り直す")
        suffix = (CF.scaffold_cfg().get("derived_workbook_suffix") or {}).get(str(group) or "", "")
        default_name = f"{base.stem}{suffix}{base.suffix}" if suffix else f"{doc}{base.suffix}"
    else:
        base = S.template_path(spec)
        if not base.exists():
            raise M.ManifestError(f"配布雛形が無い: {base}")
        default_name = f"{doc}{base.suffix}"
    wb_name = workbook or default_name
    wb_path = case_dir / wb_name
    if wb_path.exists():
        raise M.ManifestError(f"{wb_path.name} が既にある = 上書きしない")
    if m is not None:
        if doc in m.documents:
            raise M.ManifestError(f"document {doc!r} は既に manifest にある")
        data = m.data
    else:
        data = {"schema": M.SCHEMA, "case": case_dir.name, "documents": {}}
        if todo:
            data["todo"] = [todo]
    stem = Path(wb_name).stem
    outs = rc.default_outputs(stem)
    groups = {}
    for gid in (spec.get("groups") or {}):
        if group is not None and gid != group:
            continue
        cur = {"state": "draft"}
        if gid in outs:
            cur["outputs"] = outs[gid]
        else:
            cur["note"] = f"recipe {form_id} はこの group を作らない (旧 driver の型を使う。 form-case-pipeline.md #scope)"
        groups[gid] = {"current": cur}
    entry = {"form": str(form_id), "workbook": wb_name, "groups": groups}
    if from_doc:
        entry["base"] = f"document {from_doc} の workbook の copy ({base.name})"
    data["documents"][doc] = entry
    shutil.copy2(base, wb_path)
    M.Manifest(case_dir, data).save()
    stub = case_dir / f"fill_{doc}.py"
    rel = _case_rel(case_dir)
    if not stub.exists():
        from . import docx_form as DF

        text = (docx_stub_text(spec, case_dir.name, rel, doc, stub.name) if DF.is_docx(spec)
                else stub_text(spec, case_dir.name, rel, doc, stub.name, only_group=group))
        stub.write_text(text, encoding="utf-8")
    readme = case_dir / "README.md"
    if not readme.exists():
        sc = CF.scaffold_cfg()
        hint = str(sc.get("process_hint") or "")
        readme.write_text(README_TMPL.format(
            case=case_dir.name, case_rel=rel, doc=doc,
            spec_hint=str(sc.get("spec_hint") or "").format(spec=spec["_path"].name) or spec["_path"].name,
            process_hint=("、 " + hint if hint else "")), encoding="utf-8")
    from . import views as V
    V.refresh_case(case_dir)
    return {"workbook": wb_path, "manifest": mpath, "stub": stub, "readme": readme, "notice": notice}


DOCX_STUB_HEAD = '''#!/usr/bin/env python3
"""{case} / {doc} の記入 (Word 様式 {form})。 formcase.py new が生成した stub。

    python3 {name}             # 雛形から docx を作り直して FIELDS を打ち、 CHOICES / TEXTS を {doc}.overlay.yaml に書く → 読み戻し → gate
    python3 {name} --dry-run   # 書かずに、 空のまま残っている欄を一覧

- 値は**一次情報** (主催者の program・本人回答・財源の登録値) から入れる。 前の案件の docx / driver から運ばない。
- FIELDS = docx に打つ値 / CHOICES = PDF の上で ○ で囲む選択肢 / TEXTS = PDF の上で罫線の右に書く短い値
  (docx に打つと表の列幅が動いて頁がはみ出す欄。 置き方の正本 = お手本 spec {spec} の docx:)。
- 各行の comment は spec の label と例の写し (例は前の案件の値 = 同じとは限らない。 必ず直す)。 None の欄は未記入 = 実行が止まる。
- 認印は書かない (build が紙で出す版にだけ重ねる。 メールで出す版には入らない)。
- PDF を作る = `python3 {cli} build {case_rel} --doc {doc}`
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("{syspath}"))
from formcase.fill import run_docx  # noqa: E402

DOC = "{doc}"
'''


def _comment(item) -> str:
    bits = [str(item.get("label", item["id"]))]
    if item.get("optional"):
        bits.append("任意")
    if item.get("options"):
        bits.append("選択肢 " + " / ".join(map(str, item["options"])))
    if item.get("kind") == "paren":
        bits.append(f"True = 「（ ）{item.get('anchor', '')}」 に ○")
    if "example" in item:
        bits.append(f"例: {item['example']!r}")
    return "  # " + " — ".join(bits)


def docx_stub_text(spec, case_label, case_rel, doc, name) -> str:
    from . import docx_form as DF

    out = [DOCX_STUB_HEAD.format(case=case_label, doc=doc, form=spec["meta"]["id"], name=name, spec=spec["_path"].name,
                                 case_rel=case_rel, cli=CF.cli(), syspath=CF.stub_sys_path())]
    for var, items in (("FIELDS", DF.fields(spec)), ("CHOICES", DF.choices(spec)), ("TEXTS", DF.texts(spec))):
        out.append(f"{var} = {{")
        for it in items:
            val = repr(it["fixed"]) if "fixed" in it else "None"
            out.append(f"    {it['id']!r}: {val},{_comment(it)}")
        out.append("}\n")
    out.append('if __name__ == "__main__":\n    sys.exit(run_docx(__file__, DOC, FIELDS, CHOICES, TEXTS))\n')
    return "\n".join(out)


def _case_rel(case_dir: Path) -> str:
    return CF.show_path(case_dir)
