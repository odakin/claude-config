"""様式の忠実性 (form-case-pipeline.md#fidelity) = 出力を「雛形の宣言」 と「雛形の素刷り」 に突き合わせる段。

不変条件: 出力 (紙になる PDF) と、 雛形を道具を通さず同じ app で刷った素刷りとの差は、 記入の宣言 (記入欄 = 雛形との差 /
導出欄 = 数式 / 体裁 = spec の render: / drop_shape / accept_loss) で説明できるものしか無い。 説明できない差は止める
(図形の字) か行に出す (見出し・画像・census)。 参照を「前の出力」 にしない (docs/convention-design-principles.md#parity-against-own-output)。

この module が持つもの:
  - bind: spec の雛形の sha256 を sidecar ``<spec>.bind.json`` に記録する (``formcase.py bind <form>``。 JSON = spec の
    ``*.yaml`` の glob に掛からない)。 build は違えば
    ⚠️ (= 雛形が改訂された。 bind し直して差を見る)。 sidecar が無ければ ⚪ (記録なし)
  - blank: 素刷り = Excel で雛形の当該 sheet の印刷範囲を 1 枚に収めて刷った PDF (他 sheet は非表示、 openpyxl を通さない)。
    cache = ``~/.cache/formcase/blank/<sha256 の頭 16 桁>/``。 Excel が無い・失敗 = None (呼び元が ⚪ を出す)
  - check_group: 層1 check-form-static-text.py を --json で回し、 図形の字 (🔴 = build を止める) / 書き換えていない cell の
    見出し (⚠️) / 素刷りとの画像の数 (⚠️) / 増えた字 (⚪) の行にする
  - temp_census_lines: openpyxl で保存した temp の census (lib/office_census.py) を読み込み元と比べ、 紙に出る損失のうち
    spec の ``meta.accept_loss`` (理由つき) に無いものを ⚠️ に
  - fidelity_record: 出力 PDF の宣言 (print_pages の record) に載せる {template, sha256, targets, drop, blank} =
    刷る直前の preflight が同じ照合を回すため (K3)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import layout as LY
from . import specs as S

CC = Path(__file__).resolve().parent.parent
STATIC_TEXT = CC / "check-form-static-text.py"
sys.path.insert(0, str(CC / "lib"))
import office_census as OC  # noqa: E402

# temp (PDF にするための使い捨て) では紙に出ないので黙ってよい種類。 Excel が開けば再計算・作り直すもの
ACCEPT_TEMP = {"数式の cache", "印刷設定", "拡張の入力規則", "comment", "定義名", "VML"}
BLANK_ROOT = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "formcase" / "blank"


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# bind (雛形の identity)
# ---------------------------------------------------------------------------
def bind_file(spec: dict) -> Path:
    p = Path(spec["_path"])
    return p.with_name(p.stem + ".bind.json")


def read_bind(spec: dict) -> dict | None:
    p = bind_file(spec)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except ValueError:
        return {}


def bind_lines(spec: dict) -> tuple:
    """(行, 雛形が記録と違うか)。 sidecar が無ければ ⚪ の 1 行 (= 記録なし、 止めない)。"""
    tpl = S.template_path(spec)
    if not tpl.exists():
        return [f"🔴 雛形が無い: {tpl}"], True
    b = read_bind(spec)
    if not b:
        return [f"⚪ 雛形の bind 記録なし (formcase.py bind {spec['meta']['id']} で sha256 と素刷りを記録)"], False
    cur = sha256(tpl)
    if b.get("template_sha256") == cur:
        return [f"✅ 雛形 = bind の記録どおり ({tpl.name}, sha256 {cur[:12]}…, {b.get('bound', '?')})"], False
    return [f"⚠️ 雛形が bind の記録と違う ({tpl.name}: 記録 {str(b.get('template_sha256', ''))[:12]}… → 今 {cur[:12]}…) "
            f"= 雛形が改訂された (または差し替わった)。 formcase.py bind {spec['meta']['id']} で記録し直し、 差 (見出し・図形・欄) を見る"], True


def write_bind(spec: dict, blank: bool = True) -> dict:
    """sidecar を書く。 blank=True なら刷る sheet の印刷範囲ごとの素刷りを cache に作る (Excel)。"""
    import datetime as _dt

    tpl = S.template_path(spec)
    rec = {"template": spec["meta"]["template"], "template_sha256": sha256(tpl),
           "bound": _dt.date.today().isoformat(), "blank": {}}
    if blank:
        for sheet in LY.printed_sheets(spec):
            for area in LY.pages_for(spec, sheet):
                p = blank_pdf(spec, sheet, area)
                rec["blank"][f"{sheet}!{area}"] = str(p) if p else None
    rec["_note"] = "生成物 (formcase.py bind)。 雛形の identity と素刷りの cache の所在。 手で直さない"
    bind_file(spec).write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rec


# ---------------------------------------------------------------------------
# blank (素刷り)
# ---------------------------------------------------------------------------
def _safe(s: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", str(s))[:80]


def blank_dir(spec: dict) -> Path:
    return BLANK_ROOT / sha256(S.template_path(spec))[:16]


def blank_pdf(spec: dict, sheet: str, area: str | None):
    """雛形の sheet の印刷範囲 area を Excel で 1 枚に収めて刷った PDF (cache)。 Excel が失敗したら None。"""
    from . import excel as X

    tpl = S.template_path(spec)
    d = blank_dir(spec)
    out = d / f"{_safe(sheet)}__{_safe(area or 'print_area')}.pdf"
    if out.exists() and out.stat().st_size > 0:
        return out
    d.mkdir(parents=True, exist_ok=True)
    wt = LY._template_values(str(tpl))
    others = [n for n in wt.sheetnames if n.strip() != sheet.strip()]
    ops = [("hide_sheet", n) for n in others]
    if area:
        ops += [("print_area", area), ("one_page",)]
    try:
        X.export_pdf(str(tpl), str(out), X.ops_lines(sheet, ops))
    except X.ExcelError as e:
        print(f"   ⚪ 素刷りを作れない ({sheet}): {str(e)[:200]}")
        return None
    return out if out.exists() else None


def _group_targets(spec: dict, group: str) -> list:
    out = []
    for sh in S.group_sheets(spec, group, with_depends=False):
        for rng in LY.pages_for(spec, sh):
            out.append((sh, rng))
    return out


def _drops(spec: dict) -> list:
    out = []
    for fx in spec.get("render") or []:
        names = fx.get("drop_shape")
        for n in (names if isinstance(names, list) else [names] if names else []):
            out.append(f"{fx['sheet']}!{n}")
    return out


def group_blank(spec: dict, group: str, tmp: Path):
    """group の対象 (sheet, 範囲) ごとの素刷りを 1 本に並べた PDF (tmp に書く)。 1 つでも作れなければ None。"""
    import fitz

    parts = []
    for sh, rng in _group_targets(spec, group):
        p = blank_pdf(spec, sh, rng)
        if p is None:
            return None
        parts.append(p)
    out = Path(tmp) / f"blank_{_safe(group)}.pdf"
    o = fitz.open()
    for p in parts:
        o.insert_pdf(fitz.open(str(p)))
    o.save(str(out))
    return out


# ---------------------------------------------------------------------------
# 出力 PDF の照合
# ---------------------------------------------------------------------------
def controls_on(spec: dict, sheet: str, rng: str):
    """spec の controls (form control の箱、 D9) のうち sheet!rng に載る on の数。 controls の無い spec は None (= 期待を置かない)。"""
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, range_boundaries

    ctl = S.controls(spec)
    if not ctl:
        return None
    c0, r0, c1, r1 = range_boundaries(str(rng).replace("$", ""))
    n = 0
    for e in ctl:
        if e["sheet"].strip() != str(sheet).strip() or e["state"] != "on":
            continue
        col, row = coordinate_from_string(e["anchor"])
        if c0 <= column_index_from_string(col) <= c1 and r0 <= row <= r1:
            n += 1
    return n


def mark_boxes(spec: dict, pdf) -> dict:
    """印の入った箱 (control 自身の ✓) に太い黒の ✓ を PDF に重ねる (check-form-static-text --mark-checked、 検収 F1 2026-09-25:
    Mac Excel の control の ✓ は raster の灰色の小さな点で紙では読めない = 実測)。 controls の無い spec は {"marked": 0}。
    走らなかった時は {"error": …} で止めない (検査の故障を違反と同じにしない。 読めない印は check_group が止める)。"""
    if not S.controls(spec):
        return {"marked": 0, "pages": {}}
    args = [sys.executable, str(STATIC_TEXT), str(S.template_path(spec)), str(pdf), "--mark-checked", "--json"]
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if r.returncode != 0 or not r.stdout.strip():
        return {"error": (r.stderr or r.stdout).strip()[-300:] or f"exit {r.returncode}"}
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"error": r.stdout[-300:]}


def check_group(spec: dict, group: str, pdf, filled=None, blank=None) -> dict:
    """check-form-static-text --json。 走らなかった時は {"error": …}。"""
    args = [sys.executable, str(STATIC_TEXT), str(S.template_path(spec)), str(pdf), "--json"]
    for sh, rng in _group_targets(spec, group):
        args += ["--target", f"{sh}!{rng}"]
        n = controls_on(spec, sh, rng)
        if n is not None:
            args += ["--expect-checked", f"{sh}!{rng}={n}"]     # 選んだ箱の印が紙に在るか (D9)
    for dr in _drops(spec):
        args += ["--drop", dr]
    if filled:
        args += ["--filled", str(filled)]
    if blank:
        args += ["--blank", str(blank)]
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if r.returncode == 2 or not r.stdout.strip():
        return {"error": (r.stderr or r.stdout).strip()[-300:] or f"exit {r.returncode}"}
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"error": r.stdout[-300:]}


def report_lines(rep: dict, spec: dict | None = None) -> tuple:
    """(表示の行, 止める理由 or None)。 図形の字の欠け = 止める (J1)。 素刷りより画像が少ない (checkbox の箱・図が
    紙に無い) = 止める (D1、 2026-09-25。 spec の ``meta.accept_loss`` に form control を理由つきで宣言した様式 =
    openpyxl の temp で箱を落とすと決めた様式だけ ⚠️)。 見出し = ⚠️、 増えた字 = ⚪。"""
    if "error" in rep:
        return [f"⚪ 雛形との照合が走らなかった: {rep['error']}"], None
    lines = []
    image_loss = []
    box_bad = []
    accepted_images = "form control" in accept_loss(spec)
    for r in rep["targets"]:
        where = f"{r['sheet'].strip()}!{r['range']}"
        if r["page"] is None and (r["checked"] or r["labels_checked"]):
            lines.append(f"⚪ {where}: 雛形のこの範囲の頁が PDF に見つからない = 照合できない")
            continue
        if r["missing"]:
            ms = ", ".join(f"{m['name']}「{m['text'][:20]}」" for m in r["missing"])
            lines.append(f"🔴 {where}: 雛形の図形の字が無い {len(r['missing'])}/{r['checked']} — {ms}")
        elif r["checked"]:
            lines.append(f"✅ {where}: 図形の字 {r['checked']} 段落")
        if r.get("template_defect"):
            ms = ", ".join(f"{m['name']}「{m['text'][:20]}」" for m in r["template_defect"])
            lines.append(f"⚪ {where}: 雛形自身の欠陥 = 素刷りにも無い字 {len(r['template_defect'])} 段落 (枠が字幅に足りない等、"
                         f" formcase.py bind が一覧に出す) — {ms}")
        def ok(text):        # 同じ対象の ✅ 行に足す (無ければ新しい ✅ 行)
            if lines and lines[-1].startswith(f"✅ {where}:"):
                lines[-1] += f"、 {text}"
            else:
                lines.append(f"✅ {where}: {text}")

        if r["labels_checked"]:
            if r["missing_labels"]:
                ms = ", ".join(f"{m['cell']}「{m['text'][:14]}」" for m in r["missing_labels"][:6])
                lines.append(f"⚠️ {where}: 雛形の見出し (書き換えていない cell) が紙に無い {len(r['missing_labels'])}/{r['labels_checked']} — {ms}")
            else:
                ok(f"見出し {r['labels_checked']} cell")
        # checkbox の箱 (D9): 印のある箱の数と、 紙で読める印の数 (両方 = 選んだ数)。 素刷りが無くても出力の箱は数える (検収 F2)
        bx = r.get("boxes") or {}
        exp = bx.get("expected_checked")
        if exp is not None:
            if bx.get("out_checked") != exp:
                lines.append(f"🔴 {where}: 印のある箱 {bx.get('out_checked')} 個 ≠ 選んだ {exp} 個 (選んだ箱に印が無い / 選んでいない箱に印)")
                box_bad.append(f"{where} {bx.get('out_checked')} ≠ {exp}")
            elif bx.get("out_readable") != exp:
                lines.append(f"🔴 {where}: 印のある箱 {exp} 個のうち紙で読める印は {bx.get('out_readable')} 個 (control 自身の ✓ は灰色の小さな点"
                             " = 読めない。 build の ✓ の重ね描きが走っていないか効いていない)")
                box_bad.append(f"{where} 読める印 {bx.get('out_readable')} ≠ {exp}")
            else:
                ok(f"箱の印 {exp} 個 = 選んだ数 (紙で読める)")
        if bx.get("out_clipped"):
            lines.append(f"⚠️ {where}: 辺が欠けた箱 {bx['out_clipped']}/{bx['out']} (素刷り {bx.get('blank_clipped')}/{bx.get('blank')}。 control の枠が狭い"
                         " = Mac Excel の描画、 build は枠を広げて刷るので残るなら別の原因)")
        elif bx.get("blank_clipped"):
            lines.append(f"⚪ {where}: 素刷りの箱 {bx['blank_clipped']}/{bx['blank']} は辺が欠ける (雛形自身の欠陥 = control の枠が狭い)、 出力は欠けなし")
        b = r.get("blank")
        if b and b.get("images") is not None:
            bi, oi = b["images"]
            if oi < bi:
                mark = "⚠️" if accepted_images else "🔴"
                lines.append(f"{mark} {where}: 素刷りより画像が少ない {bi} → {oi} (checkbox の箱・図が紙に無い)")
                if not accepted_images:
                    image_loss.append(f"{where} {bi} → {oi}")
            else:
                ok(f"画像 {oi} = 素刷り")
            lay = b.get("layout") or {}
            if lay.get("pairs", 0) < 4:
                lines.append(f"⚪ {where}: 位置の写像 (段階 2) は label の組が {lay.get('pairs', 0)} で足りず見ていない")
            else:
                probs = []
                if lay.get("images_missing"):
                    probs.append(f"素刷りの位置に画像が無い {len(lay['images_missing'])} 個")
                if lay.get("images_moved"):
                    mv = lay["images_moved"][0]
                    probs.append(f"動いた画像 {len(lay['images_moved'])} 個 (例 Δ{mv[1]:+.1f}, {mv[2]:+.1f} pt)")
                if lay.get("hlines_missing"):
                    hm = lay["hlines_missing"]
                    probs.append(f"素刷りの水平の罫線が無い {len(hm)} 本 (最下 y={max(h[0] for h in hm)})")
                if lay.get("double"):
                    probs.append("二重刷り " + ", ".join(f"「{t[:10]}」" for t in lay["double"][:3]))
                cov = f"罫線 {lay.get('hlines_checked', 0)}/{lay.get('hlines_checked', 0) + lay.get('hlines_skipped', 0)} 本を照合"
                if probs:
                    lines.append(f"⚠️ {where}: 位置の写像 (label {lay['pairs']} 組、 {cov}): " + " / ".join(probs)
                                 + " (段階 2 = warn、 実物で誤検出を測る段階)")
                else:
                    ok(f"位置 (label {lay['pairs']} 組) 画像は素刷りどおり、 {cov}")
        if r.get("extra"):
            lines.append(f"⚪ {where}: 雛形にも記入値にも無い字 {len(r['extra'])} 片: "
                         + ", ".join(f"「{x[:10]}」" for x in r["extra"][:4]) + (" …" if len(r["extra"]) > 4 else ""))
    stop = None
    if rep.get("missing_total"):
        stop = (f"雛形の図形の字が PDF に無い ({rep['missing_total']} 段落) = 紙から見出し (区分の枠・様式番号・㊞ など) が消える。 "
                "刷らないと決めた図形なら spec の render: drop_shape に理由つきで (form-case-pipeline.md#fidelity)")
    elif box_bad:
        stop = (f"選んだ箱の印が紙と合わない ({'; '.join(box_bad)}) = 選んだのに印が無い、 選んでいない箱に印、 または印が紙で読めない (D9)。 "
                "fill_<doc>.py を回して spec の controls の値を Excel で箱に書き直す。 読めない印なら build の ✓ の重ね描き"
                " (check-form-static-text --mark-checked) を確かめる (form-case-pipeline.md#fidelity)")
    elif image_loss:
        stop = (f"素刷りより画像が少ない ({'; '.join(image_loss)}) = checkbox の箱・図が紙に無い (D1、 2026-09-25 から止める)。 "
                "Excel の操作の経路なら案件の workbook の図形・form control を雛形と比べる (openpyxl で保存した workbook は"
                "箱を失う = formcase.py normalize でなく雛形から作り直す)。 openpyxl の temp の経路で箱を落とすと決めた様式だけ"
                " spec の meta.accept_loss に form control を理由つきで (⚠️ に下がる、 form-case-pipeline.md#fidelity)")
    return lines, stop


# ---------------------------------------------------------------------------
# temp の census (W 層)
# ---------------------------------------------------------------------------
def accept_loss(spec: dict) -> set:
    """spec の meta.accept_loss = [{kind, why}] または [kind]。"""
    out = set()
    for a in ((spec or {}).get("meta") or {}).get("accept_loss") or []:
        out.add(str(a.get("kind") if isinstance(a, dict) else a))
    return out


def temp_census_lines(spec: dict | None, src, dst, dropped: int = 0) -> list:
    """openpyxl で保存した temp (dst) を読み込み元 (src) と比べ、 紙に出る損失のうち宣言に無いものを ⚠️ に。
    dropped = spec の drop_shape で落とした図形の数 (その分は減ってよい)。"""
    import zipfile

    try:
        # temp は sheet を消してあることが多い = 読み込み元を temp に残った sheet だけで数えて比べる
        with zipfile.ZipFile(str(dst)) as z:
            kept = list(OC._xlsx_sheet_parts(z, set(z.namelist())).keys())
        lo = OC.losses(OC.census(src, sheets=kept), OC.census(dst, sheets=kept), accept=ACCEPT_TEMP | accept_loss(spec))
    except Exception as e:  # noqa: BLE001
        return [f"⚪ temp の census を取れない ({type(e).__name__}: {e})"]
    out = []
    for k, b, a, paper in lo:
        if not paper:
            continue
        if k in ("図形", "図形の字") and a + dropped >= b:
            continue                                   # drop_shape で落とした分
        out.append(f"⚠️ temp で {k} が減った {b} → {a} (紙から消える。 受け入れるなら spec の meta.accept_loss に理由つきで、"
                   " form-case-pipeline.md#fidelity)")
    return out


# ---------------------------------------------------------------------------
# 出力 PDF に載せる宣言
# ---------------------------------------------------------------------------
def fidelity_record(spec: dict, group: str, blank=None) -> dict | None:
    """出力 PDF の宣言に載せる照合の指定。 雛形を持たない spec (合成の test 等) は None (= 載せない)。"""
    if not ((spec or {}).get("meta") or {}).get("template"):
        return None
    tpl = S.template_path(spec)
    try:
        targets = [f"{sh}!{rng}" for sh, rng in _group_targets(spec, group)]
    except Exception:  # noqa: BLE001  雛形が読めない・印刷範囲が無い = 対象なし (preflight は雛形の全 sheet で照合)
        targets = []
    return {"template": str(tpl), "sha256": sha256(tpl) if tpl.exists() else None,
            "targets": targets, "drop": _drops(spec), "blank": str(blank) if blank else None}
