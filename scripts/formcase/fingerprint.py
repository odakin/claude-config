"""凍結 sheet の書式の fingerprint v3 (``frozen.sheet_digest_v3``)。

v2 (manifest.sheet_digests_v2) の射程外だったもの = 罫線・塗り / 字の色・印刷範囲の中の空 cell の書式・0.5 未満の
行高 / 列幅の変化・条件付き書式・header / footer・図形と form control。 v3 はそれを持ち、 v1 / v2 の既存 issue は
そのまま有効 (re-freeze しない。 check は在る版のうち一番新しいものを照合する)。

**揺れの実測 (Mac Excel、 配布雛形 3 種と案件 workbook 3 冊)** — 何を「同じ」 と
見なすかの根拠 (form-case-pipeline.md #fingerprint-noise):

1. Windows の Excel が最後に保存した配布雛形を Mac Excel が初めて保存すると (= 96dpi の格子 → 72dpi の格子):
   - 列幅が Mac Excel の pixel の格子に丸め直される (1/8 字や 1/7 字の格子 → 1/6 字。 1.25 → 1.1640625)。
     ``defaultColWidth`` / ``baseColWidth`` も書き直される
   - **値の無い** cell の font 名・縦揃えが既定に戻る (雛形 1 冊で数百 cell。 値のある cell・罫線・塗り・表示書式は不変)
   - form control (checkbox) の anchor の pixel offset が × 0.75、 fitToPage の sheet の scale、 自動の行高 1 行 (18.75 → 19)
2. その後の Mac Excel の保存 = 0 件 (雛形 3 種 + 案件 workbook 3 冊)
3. openpyxl の保存 = 値・cell の書式・行高・列幅は 0 件だが、 **図形・form control・標題の drawing を落とす** (= 紙から消える
   本物の変化)。 docProps の Application を「Microsoft Excel Compatible / Openpyxl」 に書き換える
4. openpyxl が保存した後の Mac Excel の保存 = 幅の記録の無かった列に既定幅の列 entry が足される、
   隠れた comment の枠 (Note) が作り直される
5. 格子から外れた行高 / 列幅を Excel が保存すると格子に丸める: 行高 = 0.25pt (3.3 → 3.25、 30.33 → 30.25、
   61.7 → 61.75)、 列幅 = pixel (幅 × 6 を最も近い整数に、 .5 は切り捨て。 1.1 → 7px、 8.43 → 51px)

∴ 凍結は「最後の保存 = Mac Excel」 の workbook だけ (lifecycle.record_frozen が拒否し ``formcase.py normalize`` を案内。
formcase の fill は Excel で書くので通常は満たす)。 その上で 2・4・5 の揺れを吸う形で比べる:

   - 「Excel が保存しうる格子」 の上で比べる (= 閾値でなく app 自身の分解能)
   - 行高 = 0.25pt の格子、 列幅 = Mac Excel の pixel (列ごとに、 記録の無い列は sheet の既定幅)
   - comment の枠 (Note) は page setup が comment を印刷する時だけ。 fitToPage の時の scale は数えない
   - 値の無い cell は紙に出る性質だけ = 罫線・塗り・「選択範囲内で中央」 (隣の値の配置を変える)。
     font・表示書式・揃えは値が無ければ紙に出ない (値が入れば values の digest と値のある cell の書式が変わる)
   - pixel の格子 = 既定 font ごとの最大数字幅 (MDW)。 実測した font は ``MDW_PX``、 未測定の font は幅を
     1/256 字の生の値で持つ (= 厳しい側。 その font の workbook で初回保存の揺れが 🔴 に出たら表に足す)
"""
from __future__ import annotations

import hashlib
import math
import re
import warnings
import zipfile
from xml.etree import ElementTree as ET

# Mac Excel の最大数字幅 (pixel)。 key = 既定 font (workbook の font 0) の (名前, 大きさ)。 実測。
MDW_PX = {("游ゴシック", 11.0): 6, ("Calibri", 11.0): 6}


def _color(c):
    if c is None:
        return "-"
    t = getattr(c, "type", None)
    v = c.rgb if t == "rgb" else (c.theme if t == "theme" else (c.indexed if t == "indexed" else c.auto))
    tint = round(float(getattr(c, "tint", 0) or 0), 6)
    return f"{t}:{v}:{tint}"


def _side(s):
    if s is None or s.style is None:
        return "-"
    return f"{s.style}/{_color(s.color)}"


def _border(b):
    diag = ""
    if b.diagonal is not None and b.diagonal.style:
        diag = f"{_side(b.diagonal)}{'u' if b.diagonalUp else ''}{'d' if b.diagonalDown else ''}"
    return f"{_side(b.left)}|{_side(b.right)}|{_side(b.top)}|{_side(b.bottom)}|{diag}"


def _fill(fl):
    pt = getattr(fl, "patternType", None) or getattr(fl, "fill_type", None)
    if not pt or pt == "none":
        if getattr(fl, "type", None) == "gradient":
            return f"gradient:{fl.degree}:{[(_color(s.color), s.position) for s in (fl.stop or [])]}"
        return "-"
    return f"{pt}:{_color(fl.fgColor)}:{_color(fl.bgColor)}"


def _areas(ws):
    """印刷範囲 (複数可) を range 文字列の list で。 無ければ使っている範囲。"""
    pa = ws.print_area
    out = []
    for p in (pa if isinstance(pa, (list, tuple)) else [pa] if pa else []):
        for part in str(p).split(","):
            rng = part.split("!")[-1].replace("$", "").strip()
            if rng:
                out.append(rng)
    return out or [ws.calculate_dimension()]


def mdw_px(wb) -> int | None:
    try:
        f = wb._fonts[0]
        return MDW_PX.get((f.name, float(f.sz)))
    except Exception:  # noqa: BLE001
        return None


def _col_widths(ws, c0, c1, mdw):
    """列 index → (幅の格子値, hidden)。 openpyxl の column_dimensions は min..max の範囲 entry。"""
    dims = {}
    for d in ws.column_dimensions.values():
        lo, hi = d.min or 0, d.max or 0
        for ci in range(max(lo, c0), min(hi, c1) + 1):
            dims[ci] = d
    sf = ws.sheet_format
    if sf.defaultColWidth is not None:
        default_w = float(sf.defaultColWidth)
        default_px = math.ceil(default_w * mdw - 0.5) if mdw else None
    else:
        base = float(sf.baseColWidth if sf.baseColWidth is not None else 8)
        default_w = base
        default_px = int(base * mdw + 5) if mdw else None     # ECMA-376: baseColWidth 字 + 余白 4px + 罫線 1px
    out = []
    for ci in range(c0, c1 + 1):
        d = dims.get(ci)
        w = d.width if (d is not None and d.width is not None and (d.customWidth or d.width)) else None
        if mdw:
            px = math.ceil(float(w) * mdw - 0.5) if w is not None else default_px
            val = f"{px}px"
        else:
            val = f"{round(float(w if w is not None else default_w) * 256)}/256"
        out.append(f"{ci}:{val}:{bool(d is not None and d.hidden)}")
    return out


def _cf_items(ws):
    items = []
    for rng in ws.conditional_formatting:
        for r in rng.rules:
            dx = r.dxf
            fx = ""
            if dx is not None:
                fx = (f"{_color(dx.font.color) if dx.font else '-'}/{bool(dx.font and dx.font.b)}/"
                      f"{_fill(dx.fill) if dx.fill else '-'}/{_border(dx.border) if dx.border else '-'}")
            items.append(f"cf\t{rng.sqref}\t{r.type}\t{r.operator}\t{r.formula}\t{r.text}\t{fx}")
    return sorted(items)


def _hf_items(ws):
    out = []
    for name in ("oddHeader", "oddFooter", "evenHeader", "evenFooter", "firstHeader", "firstFooter"):
        hf = getattr(ws, name, None)
        if hf is None:
            continue
        parts = [getattr(getattr(hf, p, None), "text", None) for p in ("left", "center", "right")]
        if any(parts):
            out.append(f"hf\t{name}\t{parts}")
    return out


# --- 図形・form control (openpyxl は読まない = zip の XML から) -----------------------------------
_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
       "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
       "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _rels(z, part):
    d, name = part.rsplit("/", 1)
    rp = f"{d}/_rels/{name}.rels"
    if rp not in z.namelist():
        return {}
    root = ET.fromstring(z.read(rp))
    out = {}
    for r in root.findall("rel:Relationship", _NS):
        tgt = r.get("Target")
        if r.get("TargetMode") == "External":
            continue
        parts = (d + "/" + tgt).split("/") if not tgt.startswith("/") else tgt.lstrip("/").split("/")
        norm = []
        for p in parts:
            if p == "..":
                norm.pop()
            elif p and p != ".":
                norm.append(p)
        out[r.get("Id")] = ("/".join(norm), r.get("Type", "").rsplit("/", 1)[-1])
    return out


def _sheet_parts(z):
    wbx = ET.fromstring(z.read("xl/workbook.xml"))
    rels = _rels(z, "xl/workbook.xml")
    out = {}
    for s in wbx.findall("m:sheets/m:sheet", _NS):
        rid = s.get(f"{{{_NS['r']}}}id")
        if rid in rels:
            out[s.get("name")] = rels[rid][0]
    return out


def _anchor_pos(el, tag):
    p = el.find(f"xdr:{tag}", _NS)
    if p is None:
        return "-"
    return ",".join((p.findtext(f"xdr:{k}", default="", namespaces=_NS) or "") for k in ("col", "colOff", "row", "rowOff"))


def _drawing_items(z, part):
    root = ET.fromstring(z.read(part))
    rels = _rels(z, part)
    items = []
    for anc in list(root):
        kind = anc.tag.rsplit("}", 1)[-1]
        shapes = [x.tag.rsplit("}", 1)[-1] for x in anc if x.tag.rsplit("}", 1)[-1] in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp")]
        text = "".join(t.text or "" for t in anc.iter(f"{{{_NS['a']}}}t"))
        hidden = any(e.get("hidden") in ("1", "true") for e in anc.iter() if e.tag.endswith("}cNvPr"))
        img = ""
        for blip in anc.iter(f"{{{_NS['a']}}}blip"):
            rid = blip.get(f"{{{_NS['r']}}}embed")
            if rid in rels and rels[rid][0] in z.namelist():
                img = hashlib.sha256(z.read(rels[rid][0])).hexdigest()[:16]
        ext = anc.find("xdr:ext", _NS)
        size = f"{ext.get('cx')}x{ext.get('cy')}" if ext is not None else ""
        items.append(f"draw\t{kind}\t{_anchor_pos(anc, 'from')}\t{_anchor_pos(anc, 'to')}\t{size}\t{shapes}\t"
                     f"{text}\t{hidden}\t{img}")
    return items


_VML_ANCHOR = re.compile(r"<x:Anchor>\s*([^<]*)</x:Anchor>", re.S)


def _vml_items(z, part, with_notes=False):
    """legacy form control (checkbox 等) と、 印刷する設定の時だけ comment (Note)。 comment の枠は既定では紙に出ない
    (Excel は openpyxl の保存の後に隠れた Note を作り直す = 実測の揺れ)。"""
    raw = z.read(part).decode("utf-8", "replace")
    items = []
    for sh in re.findall(r"<v:shape\b.*?</v:shape>", raw, re.S):
        otype = re.search(r'ObjectType="([^"]+)"', sh)
        if otype and otype.group(1) == "Note" and not with_notes:
            continue
        anchor = _VML_ANCHOR.search(sh)
        checked = re.search(r"<x:Checked>\s*([^<]*)</x:Checked>", sh)
        visible = "visibility:hidden" not in sh
        text = re.sub(r"<[^>]+>", "", " ".join(re.findall(r"<v:textbox\b.*?</v:textbox>", sh, re.S)))
        items.append(f"vml\t{otype.group(1) if otype else '-'}\t{' '.join((anchor.group(1) if anchor else '').split())}\t"
                     f"{checked.group(1).strip() if checked else '-'}\t{visible}\t{' '.join(text.split())}")
    return sorted(items)


def _shape_items(workbook, sheet_name, with_notes=False):
    try:
        with zipfile.ZipFile(workbook) as z:
            parts = _sheet_parts(z)
            sp = parts.get(sheet_name)
            if sp is None:
                return []
            items = []
            for rid, (tgt, typ) in sorted(_rels(z, sp).items(), key=lambda x: x[1]):
                if tgt not in z.namelist():
                    continue
                if typ == "drawing":
                    items += _drawing_items(z, tgt)
                elif typ == "vmlDrawing":
                    items += _vml_items(z, tgt, with_notes)
                elif typ == "ctrlProp":
                    root = ET.fromstring(z.read(tgt))
                    items.append("ctrl\t" + "\t".join(f"{k}={root.get(k)}" for k in sorted(root.keys())))
            return sorted(items)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        return [f"shape-read-error\t{type(e).__name__}"]


def format_items(wb, ws, workbook_path) -> list:
    from openpyxl.utils import range_boundaries

    mdw = mdw_px(wb)
    items = [f"mdw\t{mdw or 'raw'}"]
    col_span = [None, None]
    row_span = [None, None]
    seen = set()
    for rng in _areas(ws):
        c0, r0, c1, r1 = range_boundaries(rng)
        col_span = [min(x for x in (col_span[0], c0) if x is not None), max(x for x in (col_span[1], c1) if x is not None)]
        row_span = [min(x for x in (row_span[0], r0) if x is not None), max(x for x in (row_span[1], r1) if x is not None)]
        for r in range(r0, r1 + 1):
            for ci in range(c0, c1 + 1):
                if (r, ci) in seen:
                    continue
                seen.add((r, ci))
                c = ws._cells.get((r, ci))
                if c is None:
                    continue                    # 記録の無い cell = 既定の書式 (値なし・罫線なし・塗りなし)
                empty = c.value is None or (isinstance(c.value, str) and c.value == "")
                b, fl, a = c.border, c.fill, c.alignment
                if empty:
                    bd, fi = _border(b), _fill(fl)
                    cc = a.horizontal == "centerContinuous"
                    if bd != "-|-|-|-|" or fi != "-" or cc:
                        items.append(f"e\t{c.coordinate}\t{bd}\t{fi}\t{cc}")
                    continue
                f = c.font
                items.append(f"c\t{c.coordinate}\t{c.number_format}\t{f.name}\t{f.sz}\t{bool(f.b)}\t{bool(f.i)}\t{f.u}\t"
                             f"{bool(f.strike)}\t{f.vertAlign}\t{_color(f.color)}\t{a.horizontal}\t{a.vertical}\t"
                             f"{bool(a.wrap_text)}\t{bool(a.shrink_to_fit)}\t{a.indent}\t{a.textRotation}\t"
                             f"{_border(b)}\t{_fill(fl)}")
    items += sorted(f"merge\t{m}" for m in ws.merged_cells.ranges)
    for r, d in sorted(ws.row_dimensions.items()):
        if row_span[0] is not None and not (row_span[0] <= r <= row_span[1]):
            continue
        if d.height is not None or d.hidden:
            h = None if d.height is None else round(float(d.height) * 4) / 4
            items.append(f"row\t{r}\t{h}\t{bool(d.hidden)}")
    if col_span[0] is not None:
        items += ["col\t" + x for x in _col_widths(ws, col_span[0], col_span[1], mdw)]
    ps, pm, po = ws.page_setup, ws.page_margins, ws.print_options
    fit = ws.sheet_properties.pageSetUpPr.fitToPage if ws.sheet_properties.pageSetUpPr else None
    scale = "fit" if fit else ps.scale      # fitToPage の時の scale は Excel が計算して書き直す値 (紙は fitTo が決める)
    items.append(f"print\t{ws.print_area}\t{ps.orientation}\t{ps.paperSize}\t{scale}\t{ps.fitToWidth}\t"
                 f"{ps.fitToHeight}\t{fit}\t{ps.blackAndWhite}\t{ps.draft}\t{ps.cellComments}\t{po.horizontalCentered}\t"
                 f"{po.verticalCentered}\t{po.gridLines}\t{ws.print_title_rows}\t{ws.print_title_cols}")
    items.append("margins\t" + "\t".join(f"{round(float(getattr(pm, k) or 0), 4)}"
                                          for k in ("left", "right", "top", "bottom", "header", "footer")))
    items += [f"rbreak\t{b.id}" for b in ws.row_breaks.brk] + [f"cbreak\t{b.id}" for b in ws.col_breaks.brk]
    items += _cf_items(ws) + _hf_items(ws)
    items += _shape_items(workbook_path, ws.title, with_notes=ps.cellComments in ("asDisplayed", "atEnd"))
    return items


def last_writer(workbook) -> str:
    """docProps/app.xml の Application (= 最後に書いた Office app。 openpyxl はこの値を読んだまま残す)。"""
    try:
        with zipfile.ZipFile(workbook) as z:
            m = re.search(rb"<Application>([^<]*)</Application>", z.read("docProps/app.xml"))
            return m.group(1).decode("utf-8", "replace") if m else ""
    except (KeyError, zipfile.BadZipFile):
        return ""


MAC_EXCEL = "Microsoft Macintosh Excel"


def sheet_digests_v3(workbook, sheets, v1: dict) -> dict:
    """sheet 名 → {"values": v1 の digest, "format": v3 の書式 digest}。 無い sheet は "missing"。"""
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(workbook)
    out = {}
    for name in sheets:
        if name not in wb.sheetnames:
            out[name] = "missing"
            continue
        items = format_items(wb, wb[name], workbook)
        out[name] = {"values": v1[name], "format": hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()[:24]}
    return out
