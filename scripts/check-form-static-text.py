#!/usr/bin/env python3
"""check-form-static-text.py — 様式の雛形が持つ図形の字 (標題・区分の枠・様式番号・㊞ 等) が出力 PDF に在るかを見る。

WHY (office-automation.md#openpyxl-destroys-drawings、 form-case-pipeline.md#drawings-survive-temp):
  様式の見出しの一部は cell でなく**図形** (DrawingML の textbox) に刷られている。 openpyxl で保存した workbook
  (記入した案件の xlsx でも、 PDF にするための使い捨ての temp でも) はその図形を落とし、 PDF から見出しが消える。
  既存の検査はどれも**書いたもの** (記入値の照合・字の切れ・記入要領の残置・label の上書き) を見ており、
  **雛形が元から紙に出すもの**を出力で確かめる段が無かった。 目視も「在るもの」 に目が行き、 無いものには
  比べる参照が無いと気づけない (実測: 見出しが消えたままの提出物が続き、 gate は全部通っていた)。
  この script はその参照を雛形から機械で作り、 出力 PDF と突き合わせる。

WHAT:
  - 雛形 xlsx の各 sheet の図形 (twoCellAnchor / oneCellAnchor / absoluteAnchor、 mc:AlternateContent の中も) から
    字のある textbox を集める (hidden の図形・--drop で名指しした図形・枠を切る設定で枠が 1 字より狭い図形 =
    雛形を刷っても字が出ないもの、 は除く)。 段落ごとに照合する
  - 対象 = --target の sheet (と印刷範囲)。 範囲を書かなければ雛形の印刷範囲、 それも無ければ sheet 全体。
    範囲の外に anchor がある図形 (記入例・作成上の注意など横に置かれた注記) は数えない
  - 対象ごとに PDF の頁を 1 つ選ぶ = 雛形のその範囲の cell の字 (label) が一番多く出ている頁
  - その頁の text 層 (NFKC・空白を除く) に図形の字が在るかを見る。 長い字から順に 1 回ずつ消し込むので、
    様式番号「甲-外部資金様式③-1」 が在っても区分の枠「外部資金」 が無ければ無いと言う。 枠で字が切れた
    (「⑥-2」 が「⑥-」) も無いと言う
  - 🔴 無い図形がある / ⚪ 対象の頁が PDF に見つからない (照合できない) / ✅ 全部在る

射程外 (= この検査が黙っても在るとは限らない):
  - 字の無い図形 (選択の丸・線・㊞ の枠だけの丸) = 数だけ出す。 紙に在るかは見ない
  - form control (checkbox) の箱 = 字を持たない (office-automation.md の ctrlProp 数の比較で見る)
  - 図形の位置のずれ・重なり・字が潰れる二重刷り = 在るかしか見ない
  - raster (画像だけ) の PDF = text 層が無いので ⚪
  - cell の label の消失・上書き = diff-form-xlsx.py (xlsx の段) の射程

使い方:
  check-form-static-text.py 雛形.xlsx 出力.pdf                                  # 全 sheet、 雛形の印刷範囲
  check-form-static-text.py 雛形.xlsx 出力.pdf --target '出張願!A1:AH60' --target '報告書'
  check-form-static-text.py 雛形.xlsx 出力.pdf --target 請求書 --drop '請求書!楕円 2'
  check-form-static-text.py ... --json      # 機械向け
  check-form-static-text.py ... --strict    # 対象の頁が見つからない (⚪) も exit 1
  check-form-static-text.py --selftest
exit: 0 = 全部在る (⚪ は --strict でなければ 0) / 1 = 無い図形がある / 2 = 使い方・読めない file
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}
REL_DRAWING = NS["r"] + "/drawing"
ANCHORS = ("twoCellAnchor", "oneCellAnchor", "absoluteAnchor")


def norm(s) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s or "")))


# ---------------------------------------------------------------------------
# 雛形の図形
# ---------------------------------------------------------------------------
def _resolve(base, target):
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


def _rels(z, part):
    name = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if name not in z.namelist():
        return []
    return [(r.get("Id"), r.get("Type"), r.get("Target")) for r in ET.fromstring(z.read(name))]


def sheet_parts(z) -> dict:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    by_id = {rid: _resolve("xl/workbook.xml", t) for rid, _ty, t in _rels(z, "xl/workbook.xml")}
    out = {}
    for s in wb.iter(f"{{{NS['m']}}}sheet"):
        rid = s.get(f"{{{NS['r']}}}id")
        if rid in by_id:
            out[s.get("name")] = by_id[rid]
    return out


def _anchor_elems(root):
    """wsDr 直下の anchor (mc:AlternateContent の中は mc:Choice の側)。"""
    for ch in root:
        tag = ch.tag.split("}")[-1]
        if tag in ANCHORS:
            yield ch
        elif tag == "AlternateContent":
            branch = ch.find("mc:Choice", NS)
            if branch is None:
                branch = ch.find("mc:Fallback", NS)
            for sub in (branch if branch is not None else []):
                if sub.tag.split("}")[-1] in ANCHORS:
                    yield sub


def _cell_of(anchor, which):
    el = anchor.find(f"xdr:{which}", NS)
    if el is None:
        return None
    return int(el.find("xdr:row", NS).text) + 1, int(el.find("xdr:col", NS).text) + 1


def _offs(anchor, which):
    el = anchor.find(f"xdr:{which}", NS)
    if el is None:
        return None
    return tuple(int(el.find(f"xdr:{k}", NS).text) for k in ("col", "colOff", "row", "rowOff"))


EMU_PT = 12700


def _col_pt(ws, ci):
    """列 ci (1 始まり) の幅 (pt、 近似)。 Excel の列幅は既定 font の数字幅 (≒ 7px) 単位 + 余白 5px。"""
    from openpyxl.utils import get_column_letter

    cd = ws.column_dimensions.get(get_column_letter(ci))
    if cd is not None and cd.hidden:
        return 0.0
    w = cd.width if cd is not None and cd.width else (ws.sheet_format.defaultColWidth or 8.43)
    return (float(w) * 7 + 5) * 0.75


def _row_pt(ws, ri):
    rd = ws.row_dimensions.get(ri)
    if rd is not None and rd.hidden:
        return 0.0
    if rd is not None and rd.height is not None:
        return float(rd.height)
    return float(ws.sheet_format.defaultRowHeight or 15)


def _box_pt(ws, anchor):
    """図形の外枠 (幅, 高さ) の pt。 one/absolute は ext から、 twoCellAnchor は列幅・行高から。 求まらなければ None。"""
    ext = anchor.find("xdr:ext", NS)
    if ext is not None:
        return int(ext.get("cx")) / EMU_PT, int(ext.get("cy")) / EMU_PT
    f, t = _offs(anchor, "from"), _offs(anchor, "to")
    if f is None or t is None or ws is None:
        return None
    w = sum(_col_pt(ws, c + 1) for c in range(f[0], t[0])) - f[1] / EMU_PT + t[1] / EMU_PT
    h = sum(_row_pt(ws, r + 1) for r in range(f[2], t[2])) - f[3] / EMU_PT + t[3] / EMU_PT
    return max(0.0, w), max(0.0, h)


def _invisible(sp, box) -> bool:
    """字が紙に出ない図形 = 枠の外を切る (clip) 設定で、 枠の内側が字 1 つ分より狭い (実測: 様式の旧版の見出しが
    幅 1 字未満の列に残り、 雛形を Excel で刷っても字が出ない)。 縦書きも幅と高さの両方に 1 字要る。"""
    if box is None:
        return False
    bp = sp.find("xdr:txBody/a:bodyPr", NS)
    if bp is None:
        return False
    sizes = [int(r.get("sz")) / 100 for r in sp.iter(f"{{{NS['a']}}}rPr") if r.get("sz")]
    em = max(sizes) if sizes else 11.0
    ins = {k: int(bp.get(k, d)) / EMU_PT for k, d in (("lIns", 91440), ("rIns", 91440), ("tIns", 45720), ("bIns", 45720))}
    narrow_w = bp.get("horzOverflow") == "clip" and box[0] - ins["lIns"] - ins["rIns"] < 0.6 * em
    narrow_h = bp.get("vertOverflow") == "clip" and box[1] - ins["tIns"] - ins["bIns"] < 0.6 * em
    return narrow_w or narrow_h


def shapes(template, book=None) -> dict:
    """sheet 名 → [{name, hidden, invisible, paras, from, to}] (字の無い図形は paras=[])。 book = 雛形の openpyxl
    workbook (列幅・行高から図形の大きさを出す = 字が出ない狭い図形を除くため。 無ければ大きさは見ない)。"""
    out = {}
    with zipfile.ZipFile(template) as z:
        for sheet, part in sheet_parts(z).items():
            ws = book[sheet] if book is not None and sheet in book.sheetnames else None
            items = []
            for _rid, typ, tgt in _rels(z, part):
                if typ != REL_DRAWING:
                    continue
                root = ET.fromstring(z.read(_resolve(part, tgt)))
                for a in _anchor_elems(root):
                    frm, to = _cell_of(a, "from"), _cell_of(a, "to")
                    box = _box_pt(ws, a)
                    for sp in a.iter(f"{{{NS['xdr']}}}sp"):
                        nv = sp.find("xdr:nvSpPr/xdr:cNvPr", NS)
                        name = nv.get("name") if nv is not None else "?"
                        hidden = nv is not None and nv.get("hidden") in ("1", "true")
                        paras = []
                        body = sp.find("xdr:txBody", NS)
                        if body is not None:
                            for p in body.findall("a:p", NS):
                                t = norm("".join(x.text or "" for x in p.iter(f"{{{NS['a']}}}t")))
                                if t:
                                    paras.append(t)
                        items.append({"name": name, "hidden": hidden, "invisible": _invisible(sp, box),
                                      "paras": paras, "from": frm, "to": to})
            out[sheet] = items
    return out


# ---------------------------------------------------------------------------
# 範囲・cell の label
# ---------------------------------------------------------------------------
def _bounds(rng: str):
    from openpyxl.utils.cell import range_boundaries

    rng = rng.split("!")[-1].replace("$", "").strip()
    c0, r0, c1, r1 = range_boundaries(rng)
    return c0, r0, c1, r1


def _find_sheet(names, want):
    for n in names:
        if n.strip() == want.strip():
            return n
    return None


def _template_book(template):
    import warnings

    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(template, data_only=False)


def _ranges_of(ws, rng):
    if rng:
        return [rng]
    pa = ws.print_area
    if pa:
        parts = pa if isinstance(pa, (list, tuple)) else str(pa).split(",")
        return [p.split("!")[-1].replace("$", "") for p in parts if p.strip()]
    return [ws.dimensions]


def _labels(ws, rng) -> list:
    c0, r0, c1, r1 = _bounds(rng)
    out = []
    for row in ws.iter_rows(min_row=r0, max_row=r1, min_col=c0, max_col=c1):
        for c in row:
            v = c.value
            if isinstance(v, str) and not v.startswith("="):
                t = norm(v)
                if len(t) >= 2:
                    out.append(t)
    return out


def _inside(cell, rng) -> bool:
    if cell is None:
        return False
    c0, r0, c1, r1 = _bounds(rng)
    r, c = cell
    return r0 <= r <= r1 and c0 <= c <= c1


# ---------------------------------------------------------------------------
# 照合
# ---------------------------------------------------------------------------
def page_texts(pdf) -> list:
    import fitz

    with fitz.open(pdf) as d:
        return [norm(p.get_text()) for p in d]


def _score(labels, text) -> int:
    return sum(1 for t in set(labels) if t in text)


def check(template, pdf, targets=None, drop=None) -> dict:
    """targets = [(sheet, range or None)] (None = 雛形の全 sheet)。 drop = {(sheet, 図形名)}。"""
    drop = {(s.strip(), n) for s, n in (drop or set())}
    wb = _template_book(template)
    shp = shapes(template, wb)
    texts = page_texts(pdf)
    if targets is None:
        targets = [(n, None) for n in wb.sheetnames]
    jobs = []
    for sheet, rng in targets:
        name = _find_sheet(wb.sheetnames, sheet)
        if name is None:
            raise ValueError(f"雛形に sheet {sheet!r} が無い")
        ws = wb[name]
        for r in _ranges_of(ws, rng):
            labels = _labels(ws, r)
            items = [s for s in shp.get(name, []) if _inside(s["from"], r)]
            outside = sum(1 for s in shp.get(name, []) if not _inside(s["from"], r))
            jobs.append({"sheet": name, "range": r, "labels": labels, "items": items, "outside": outside})
    # 頁の割り当て = label の出た数が多い順に、 1 頁 1 対象 (同じ sheet の別範囲も別の頁)
    pairs = sorted(((_score(j["labels"], t), -i, k) for i, j in enumerate(jobs) for k, t in enumerate(texts)),
                   reverse=True)
    taken_j, taken_p = set(), set()
    for sc, negi, k in pairs:
        i = -negi
        need = max(2, int(0.3 * len(set(jobs[i]["labels"]))))
        if i in taken_j or k in taken_p or sc < need:
            continue
        jobs[i]["page"], jobs[i]["score"] = k + 1, sc
        taken_j.add(i)
        taken_p.add(k)
    report = []
    for j in jobs:
        res = {"sheet": j["sheet"], "range": j["range"], "page": j.get("page"), "checked": 0, "missing": [],
               "textless": 0, "dropped": 0, "hidden": 0, "invisible": 0, "outside": j["outside"]}
        want = []
        for s in j["items"]:
            if (j["sheet"].strip(), s["name"]) in drop:
                res["dropped"] += 1
            elif s["hidden"]:
                res["hidden"] += 1
            elif s["invisible"] and s["paras"]:
                res["invisible"] += 1
            elif not s["paras"]:
                res["textless"] += 1
            else:
                want += [(p, s["name"]) for p in s["paras"]]
        res["checked"] = len(want)
        if res["page"] is not None:
            text = texts[res["page"] - 1]
            # cell の label が図形の字を含むなら、 その label の分を先に消す (= label で図形の代わりにしない)
            for lab in sorted(set(j["labels"]), key=len, reverse=True):
                if any(p in lab for p, _n in want) and lab in text:
                    text = text.replace(lab, "\0", 1)
            for p, n in sorted(want, key=lambda x: len(x[0]), reverse=True):
                if p in text:
                    text = text.replace(p, "\0", 1)
                else:
                    res["missing"].append({"name": n, "text": p})
        report.append(res)
    return {"template": str(template), "pdf": str(pdf), "targets": report,
            "missing_total": sum(len(r["missing"]) for r in report),
            "unmatched": sum(1 for r in report if r["page"] is None and r["checked"])}


def render(rep) -> list:
    lines = []
    for r in rep["targets"]:
        where = f"{r['sheet'].strip()}!{r['range']}"
        extra = []
        if r["textless"]:
            extra.append(f"字の無い図形 {r['textless']} (射程外)")
        if r["dropped"]:
            extra.append(f"drop {r['dropped']}")
        if r["invisible"]:
            extra.append(f"枠が 1 字より狭く字の出ない図形 {r['invisible']}")
        tail = f" [{' / '.join(extra)}]" if extra else ""
        if not r["checked"]:
            lines.append(f"   ・ {where}: 字のある図形なし{tail}")
        elif r["page"] is None:
            lines.append(f"   ⚪ {where}: 雛形のこの範囲の頁が PDF に見つからない = 図形の字 {r['checked']} 段落を照合できない{tail}")
        elif r["missing"]:
            ms = ", ".join(f"{m['name']}「{m['text'][:24]}」" for m in r["missing"])
            lines.append(f"   🔴 {where} (PDF {r['page']} 頁): 雛形の図形の字が無い {len(r['missing'])}/{r['checked']} — {ms}{tail}")
        else:
            lines.append(f"   ✅ {where} (PDF {r['page']} 頁): 図形の字 {r['checked']} 段落 全部在る{tail}")
    return lines


def _parse_targets(vals):
    out = []
    for v in vals or []:
        if "!" in v:
            s, r = v.rsplit("!", 1)
            out.append((s, r))
        else:
            out.append((v, None))
    return out or None


def _parse_drop(vals):
    out = set()
    for v in vals or []:
        if "!" not in v:
            raise SystemExit(f"--drop は 'sheet!図形名' の形: {v!r}")
        s, n = v.split("!", 1)
        out.add((s, n))
    return out


# ---------------------------------------------------------------------------
# selftest (合成の雛形 + 合成の PDF)
# ---------------------------------------------------------------------------
def _inject_drawing(xlsx, sheet_xml_part, anchors_xml):
    """openpyxl で作った xlsx の 1 sheet に drawing を差す (selftest 用)。"""
    import shutil
    import tempfile

    dr = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          f'<xdr:wsDr xmlns:xdr="{NS["xdr"]}" xmlns:a="{NS["a"]}">{anchors_xml}</xdr:wsDr>')
    tmp = tempfile.mktemp(suffix=".xlsx")
    with zipfile.ZipFile(xlsx) as zi, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for i in zi.infolist():
            b = zi.read(i.filename)
            if i.filename == "[Content_Types].xml":
                b = b.replace(b"</Types>", b'<Override PartName="/xl/drawings/drawing1.xml" ContentType='
                              b'"application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>')
            if i.filename == sheet_xml_part:
                s = b.decode()
                s = s.replace("</worksheet>", f'<drawing xmlns:r="{NS["r"]}" r:id="rIdD1"/></worksheet>')
                b = s.encode()
            zo.writestr(i, b)
        rels = posixpath.join(posixpath.dirname(sheet_xml_part), "_rels", posixpath.basename(sheet_xml_part) + ".rels")
        zo.writestr(rels, f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{NS["pr"]}">'
                          f'<Relationship Id="rIdD1" Type="{REL_DRAWING}" Target="../drawings/drawing1.xml"/></Relationships>')
        zo.writestr("xl/drawings/drawing1.xml", dr)
    shutil.move(tmp, xlsx)


def _anchor(name, row, col, text, kind="oneCellAnchor", hidden=False):
    frm = f"<xdr:from><xdr:col>{col - 1}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row - 1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
    size = '<xdr:ext cx="1000000" cy="200000"/>' if kind == "oneCellAnchor" else (
        f"<xdr:to><xdr:col>{col + 2}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>")
    paras = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in (text if isinstance(text, list) else [text]))
    body = f"<xdr:txBody><a:bodyPr/>{paras}</xdr:txBody>" if text else ""
    h = ' hidden="1"' if hidden else ""
    return (f"<xdr:{kind}>{frm}{size}<xdr:sp><xdr:nvSpPr><xdr:cNvPr id=\"2\" name=\"{name}\"{h}/><xdr:cNvSpPr/></xdr:nvSpPr>"
            f"<xdr:spPr/>{body}</xdr:sp><xdr:clientData/></xdr:{kind}>")


def selftest() -> int:
    import os
    import tempfile

    import fitz
    import openpyxl

    d = tempfile.mkdtemp(prefix="static-text-selftest-")
    tpl = os.path.join(d, "tpl.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "出張願"
    for coord, v in {"B3": "出張者", "B4": "所属", "B5": "氏名", "B6": "用務", "B7": "期間", "B8": "宿泊先",
                     "D3": "甲-外部資金様式の説明"}.items():
        ws[coord] = v
    ws.print_area = "A1:J20"
    ws2 = wb.create_sheet("報告書")
    for coord, v in {"B3": "報告者", "B4": "出張先", "B5": "成果", "B6": "日程"}.items():
        ws2[coord] = v
    wb.save(tpl)
    _inject_drawing(tpl, "xl/worksheets/sheet1.xml",
                    _anchor("Shape 1", 1, 1, "外部資金")
                    + _anchor("Shape 2", 1, 8, "甲-外部資金様式③-1", kind="twoCellAnchor")
                    + _anchor("Shape 3", 2, 30, "作成上の注意 横の注記")            # 印刷範囲の外
                    + _anchor("Shape 4", 10, 2, "")                                 # 字の無い丸
                    + _anchor("Shape 5", 11, 2, "隠れた字", hidden=True)
                    + _anchor("Shape 6", 12, 2, "回覧先の課")
                    + _anchor("Shape 7", 13, 2, ["複数", "段落の字"]))

    def pdf(name, pages):
        p = os.path.join(d, name)
        doc = fitz.open()
        for lines in pages:
            pg = doc.new_page()
            y = 60
            for t in lines:
                pg.insert_text((50, y), t, fontname="japan", fontsize=10)
                y += 16
        doc.save(p)
        return p

    labels1 = ["出張者", "所属", "氏名", "用務", "期間", "宿泊先", "甲-外部資金様式の説明"]
    labels2 = ["報告者", "出張先", "成果", "日程"]
    shapes_ok = ["外部資金", "甲-外部資金様式③-1", "回覧先の課", "複数", "段落の字"]
    cases = [
        ("全部在る", [labels1 + shapes_ok, labels2], {}, 0, 0),
        ("区分の枠だけ無い (様式番号と label の中の『外部資金』 で代わりにしない)",
         [labels1 + ["甲-外部資金様式③-1", "回覧先の課", "複数", "段落の字"], labels2], {}, 1, 1),
        ("様式番号の末尾が切れた (③-1 → ③-)",
         [labels1 + ["外部資金", "甲-外部資金様式③-", "回覧先の課", "複数", "段落の字"], labels2], {}, 1, 1),
        ("図形が全部落ちた", [labels1, labels2], {}, 1, 5),
        ("drop した図形は求めない", [labels1 + ["外部資金", "甲-外部資金様式③-1", "複数", "段落の字"], labels2],
         {"drop": {("出張願", "Shape 6")}}, 0, 0),
        ("頁の順が違っても label で頁を選ぶ", [labels2, labels1 + shapes_ok], {}, 0, 0),
        ("頁の text 層が無い (raster) = ⚪ で exit 0", [[], []], {}, 0, 0),
        ("頁の text 層が無い + strict = exit 1", [[], []], {"strict": True}, 1, 0),
    ]
    fails = 0
    for label, pages, opt, want_rc, want_missing in cases:
        p = pdf("out.pdf", pages)
        rep = check(tpl, p, targets=[("出張願", None), ("報告書", None)], drop=opt.get("drop"))
        rc = 1 if rep["missing_total"] or (opt.get("strict") and rep["unmatched"]) else 0
        ok = rc == want_rc and rep["missing_total"] == want_missing
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} {label}: rc={rc} missing={rep['missing_total']}")
        if not ok:
            print("\n".join(render(rep)))
    # 範囲の外・隠れた図形・字の無い図形は数えない
    rep = check(tpl, pdf("out.pdf", [labels1 + shapes_ok, labels2]), targets=[("出張願", None)])
    t = rep["targets"][0]
    ok = t["outside"] == 1 and t["hidden"] == 1 and t["textless"] == 1 and t["checked"] == 5
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} 範囲外 1 / 隠れ 1 / 字なし 1 / 照合 5 段落: {t}")
    print("ALL PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template", nargs="?")
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--target", action="append", help="'sheet' か 'sheet!A1:AH60' (繰り返し可)")
    ap.add_argument("--drop", action="append", help="'sheet!図形名' = 刷らないと決めた図形 (繰り返し可)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="対象の頁が見つからない (⚪) も exit 1")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.template or not a.pdf:
        ap.print_usage(sys.stderr)
        return 2
    try:
        rep = check(a.template, a.pdf, _parse_targets(a.target), _parse_drop(a.drop))
    except (ValueError, KeyError, zipfile.BadZipFile, FileNotFoundError) as e:
        print(f"check-form-static-text: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(f"雛形の図形の字 ({rep['template'].split('/')[-1]} → {rep['pdf'].split('/')[-1]}):")
        print("\n".join(render(rep)))
    return 1 if rep["missing_total"] or (a.strict and rep["unmatched"]) else 0


if __name__ == "__main__":
    sys.exit(main())
