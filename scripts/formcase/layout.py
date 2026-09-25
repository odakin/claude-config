"""刷る temp の体裁 (= 値は案件の workbook、 体裁は build の temp にだけ当てる。 案件の xlsx は変えない)。

体裁を 3 つの出どころに分け、 どれも「過去の案件の形」 を持たない (= それまで recipe に焼いていた行高・印刷範囲・scale
の定数は、 提出まで通った案件の形をそのまま持っていて、 長い値で崩れた実測がある):

1. **配布雛形の欠陥** (値の長さに依らない) = spec の ``render:`` (``apply_render_fixes``)。 表示書式・merge・罫線・
   label の行高の下限・揃え・白黒・印刷範囲 (雛形が印刷範囲を持たない様式)。 値で形が変わる欠陥は ``when``。
   各 entry に理由。
2. **page** = 印刷範囲 (``pages_for`` = render: の print_area か雛形の印刷範囲) を雛形の手動改ページで切った 1 まとまりを、
   紙 1 枚に収める (``one_page``)。 行を伸ばしても次の page に溢れず全体が縮む (縮み過ぎは build の gate が止める)。
3. **値の長さで決まる行高・折り返し** = 記入値 (数式は計算済みの値) × 雛形の列幅・font から見積もる
   (``fit_text``)。 結合セルに 1 行で入らない値は折り返しにし、 要る行数の高さまで行を伸ばす (縮めない)。 行の送りは
   font の行の高さから (``line_pitch`` = 游ゴシックは MS 系の 1.3 倍)。 見積りは控えめで、 真偽は PDF で決める: build が
   Excel の PDF を check-form-clipping (切れ・fan-out の欠け・罫線/点線/他の字との重なり・###・縮み過ぎ) で見て、
   引っかかった欄を伸ばして刷り直し、 それでも残れば出力を書かずに止める (recipes.Recipe.fit、 全様式)。

1 日 1 block の表 (``nittei``) の行高・点線は ``normalize_nittei`` (spec の nittei.layout に collapsed_row_max_pt が
ある様式だけ)。 潰した行 (3pt) は fit_text が伸ばさない。 どれも冪等。 openpyxl の worksheet を直接変える (temp 用)。
openpyxl で save すると図形が消える様式は ``snapshot`` → 体裁 → ``excel_ops`` で差分を取り、 Excel に当てる。
"""
from __future__ import annotations

import math
from copy import copy
from functools import lru_cache
from pathlib import Path

COLLAPSED_PT = 3.0
# 見積りの定数 (実測: 雛形の結合セル 9 欄に同じ字を並べて Mac Excel で PDF にし、 1 行の字数を数えた)。
#   列幅 1 字 = 5.25pt (7px) で見ると、 見積りの 1 行の字数は 9 欄とも実測より少なかった (実測 / 見積り = 1.05〜1.37)
#   = 行数を多めに見る側。 行の送り = font size × 1.3 (MS Pゴシック 12pt の折り返しで 15.4pt = 1.28)。
PT_PER_WIDTH_UNIT = 5.25
LINE_PITCH = 1.3
PAD_W, PAD_H = 3.0, 3.0
DFONTS = Path("/Applications/Microsoft Excel.app/Contents/Resources/DFonts")
FONT_FILES = ("msgothic.ttc", "msmincho.ttc", "YuGothR.ttc", "YuGothM.ttc", "YuGothB.ttc", "meiryo.ttc")


def _geom(spec: dict) -> dict:
    n = spec.get("nittei") or {}
    roles = n.get("roles") or {}
    return {"sheet": (n.get("sheet") or spec["meta"]["sheet"]), "anchors": [int(a) for a in n.get("anchors") or []],
            "date": roles.get("date", {}).get("col"), "duty": roles.get("duty", {}).get("col"),
            "place": roles.get("place", {}).get("col"), "days": roles.get("days", {}).get("col"),
            "collapsed_max": float((n.get("layout") or {}).get("collapsed_row_max_pt") or 5.0)}


def _sheet(wb, name):
    if name in wb.sheetnames:
        return wb[name]
    for n in wb.sheetnames:
        if n.strip() == name.strip():
            return wb[n]
    return None


def printed_sheets(spec: dict) -> list:
    """spec の group が刷る sheet (depends を除く)。"""
    out = []
    for g in (spec.get("groups") or {}).values():
        for s in g.get("sheets") or []:
            if s not in out:
                out.append(s)
    return out


# ---------------------------------------------------------------------------
# 1. 配布雛形の欠陥 (spec の render:)
# ---------------------------------------------------------------------------
def _refs(ref):
    return ref if isinstance(ref, list) else [ref]


def _set_bottom(cell, style):
    from openpyxl.styles import Border, Side

    b = cell.border
    if b.bottom is not None and b.bottom.style == style:
        return False
    cell.border = Border(left=copy(b.left), right=copy(b.right), top=copy(b.top), bottom=Side(style=style),
                         diagonal=copy(b.diagonal), diagonalUp=b.diagonalUp, diagonalDown=b.diagonalDown,
                         outline=b.outline, vertical=copy(b.vertical), horizontal=copy(b.horizontal))
    return True


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _when_holds(fx: dict, ws, wv) -> bool:
    """render entry の ``when: {empty: CELL}`` / ``when: {filled: CELL}`` (値で形が変わる雛形の欠陥)。
    値は wv (data_only = 数式の計算済み値) があればそれで、 無ければ ws で見る。"""
    cond = fx.get("when")
    if not cond:
        return True
    src = wv if wv is not None else ws
    if "empty" in cond:
        return _blank(src[cond["empty"]].value)
    if "filled" in cond:
        return not _blank(src[cond["filled"]].value)
    raise ValueError(f"render の when が読めない: {cond!r}")


def apply_render_fixes(wb, spec: dict, wbv=None, sheets=None) -> list:
    """spec の ``render:`` を当てる (冪等)。 変えた箇所の説明を返す。

    entry の種類 (各 entry に why): ``merge`` / ``number_format`` / ``font_size`` / ``border_bottom`` /
    ``row_height`` (その行の高さの下限 = 雛形の label が行高に収まらない) / ``horizontal`` / ``vertical`` (揃え) /
    ``black_and_white`` (sheet の印刷を白黒に) / ``print_area`` (雛形に印刷範囲が無い・違う = page の元。
    ここでは当てず ``pages_for`` が読む) / ``drop_shape`` (雛形の図形のうち刷らないもの = 名前 〔cNvPr の name〕 の
    list。 openpyxl の worksheet は図形を持たないので wb に控え、 recipes._save の図形の移植が落とす。 例 = cell と
    同じ字の textbox が重なって二重に刷られる雛形の欠陥)。 ``when`` つきの entry は値の条件が成り立つ時だけ。"""
    from openpyxl.styles import Alignment
    from openpyxl.utils.cell import range_boundaries

    changed = []
    only = {s.strip() for s in sheets} if sheets is not None else None
    for fx in spec.get("render") or []:
        ws = _sheet(wb, fx["sheet"])
        if ws is None or (only is not None and fx["sheet"].strip() not in only):
            continue
        name = fx["sheet"].strip()
        if not _when_holds(fx, ws, _sheet(wbv, fx["sheet"]) if wbv is not None else None):
            continue
        if "black_and_white" in fx and bool(ws.page_setup.blackAndWhite) != bool(fx["black_and_white"]):
            ws.page_setup.blackAndWhite = bool(fx["black_and_white"])
            changed.append(f"{name} 白黒印刷 {bool(fx['black_and_white'])}")
        if fx.get("drop_shape"):
            names = fx["drop_shape"] if isinstance(fx["drop_shape"], list) else [fx["drop_shape"]]
            drops = wb.__dict__.setdefault("_formcase_drop_shapes", {})
            have = drops.setdefault(ws.title, set())
            for n in names:
                if n not in have:
                    have.add(n)
                    changed.append(f"{name} 図形 {n!r} を刷らない")
        if fx.get("row_height"):
            for r in (fx["row"] if isinstance(fx.get("row"), list) else [fx["row"]]):
                if _row_h(ws, int(r)) < float(fx["row_height"]):
                    ws.row_dimensions[int(r)].height = float(fx["row_height"])
                    changed.append(f"{name} 行 {r} の高さ {fx['row_height']} (下限)")
        if "ref" not in fx:
            continue
        for ref in _refs(fx["ref"]):
            if fx.get("horizontal") or fx.get("vertical"):
                cell = ws[ref.split(":")[0]]
                al = cell.alignment
                h, v = fx.get("horizontal") or al.horizontal, fx.get("vertical") or al.vertical
                if (h, v) != (al.horizontal, al.vertical):
                    cell.alignment = Alignment(horizontal=h, vertical=v, wrap_text=al.wrap_text,
                                               shrink_to_fit=al.shrink_to_fit, indent=al.indent,
                                               text_rotation=al.text_rotation)
                    changed.append(f"{name}!{cell.coordinate} 揃え {h}/{v}")
            if fx.get("merge"):
                want = fx["merge"]
                have = {str(m) for m in ws.merged_cells.ranges}
                if want not in have:
                    c0, r0, c1, r1 = range_boundaries(want)
                    for m in list(ws.merged_cells.ranges):
                        if m.min_col <= c1 and m.max_col >= c0 and m.min_row <= r1 and m.max_row >= r0:
                            ws.unmerge_cells(str(m))
                    ws.merge_cells(want)
                    changed.append(f"{name} merge {want}")
            if fx.get("number_format"):
                cell = ws[ref.split(":")[0]]
                if cell.number_format != fx["number_format"]:
                    cell.number_format = fx["number_format"]
                    changed.append(f"{name}!{cell.coordinate} 表示書式")
            if fx.get("font_size"):
                cell = ws[ref.split(":")[0]]
                if float(cell.font.sz or 0) != float(fx["font_size"]):
                    f = copy(cell.font)
                    f.sz = float(fx["font_size"])
                    cell.font = f
                    changed.append(f"{name}!{cell.coordinate} 字の大きさ {fx['font_size']}")
            if fx.get("border_bottom"):
                c0, r0, c1, r1 = range_boundaries(ref)
                for r in range(r0, r1 + 1):
                    for ci in range(c0, c1 + 1):
                        cell = ws.cell(r, ci)
                        try:
                            if _set_bottom(cell, fx["border_bottom"]):
                                changed.append(f"{name}!{cell.coordinate} 下罫線 {fx['border_bottom']}")
                        except AttributeError:          # MergedCell の一部は border を持てない
                            pass
    return changed


# ---------------------------------------------------------------------------
# 2. page = 雛形の印刷範囲 × 手動改ページ → 1 まとまり 1 枚
# ---------------------------------------------------------------------------
def template_pages(ws, area=None) -> list:
    """雛形の印刷範囲 (1 つ) を手動改ページで切った range の list (例 A1:AH93 + 改ページ 42 → A1:AH42, A43:AH93)。
    area = 印刷範囲を外から渡す (雛形に印刷範囲が無い様式 = spec の render: の print_area)。"""
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.cell import range_boundaries

    pa = area or ws.print_area
    area = (pa[0] if isinstance(pa, (list, tuple)) else pa) if pa else ws.calculate_dimension()
    area = str(area).split("!")[-1].replace("$", "")
    c0, r0, c1, r1 = range_boundaries(area)
    cuts = sorted(b.id for b in ws.row_breaks.brk if r0 <= b.id < r1)
    out, start = [], r0
    for b in cuts + [r1]:
        out.append(f"{get_column_letter(c0)}{start}:{get_column_letter(c1)}{b}")
        start = b + 1
    return out


def one_page(ws, area=None) -> None:
    """ws を紙 1 枚に収める (area 指定時はその範囲)。 行を伸ばしても次 page に溢れず全体が縮む。"""
    from openpyxl.worksheet.pagebreak import ColBreak, RowBreak
    from openpyxl.worksheet.properties import PageSetupProperties

    if area:
        ws.print_area = area
    if ws.sheet_properties.pageSetUpPr is None:
        ws.sheet_properties.pageSetUpPr = PageSetupProperties()
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.row_breaks = RowBreak()
    ws.col_breaks = ColBreak()


def pages_for(spec: dict, name: str) -> list:
    """sheet name の page (= 紙 1 枚ずつの range) = 印刷範囲を雛形の手動改ページで切ったもの。

    印刷範囲の出どころ = spec の ``render:`` の ``print_area`` (雛形に無い・雛形の範囲が様式の枠と違う時。 理由は
    entry の why) → 無ければ雛形の印刷範囲。 どちらも無ければ止める (= Excel の既定 〔使用範囲〕 で刷らない)。"""
    from . import specs as S

    wt = _sheet(_template_values(str(S.template_path(spec))), name)
    if wt is None:
        raise ValueError(f"雛形に sheet {name!r} が無い")
    area = next((fx["print_area"] for fx in spec.get("render") or []
                 if fx.get("print_area") and fx["sheet"].strip() == name.strip()), None)
    if area is None and not wt.print_area:
        raise ValueError(f"{name!r}: 雛形に印刷範囲が無く spec の render: にも print_area が無い")
    return template_pages(wt, area)


# ---------------------------------------------------------------------------
# Excel に当てる体裁の差分 (openpyxl で save すると図形が消える様式 = 標題・checkbox 等の drawing を持つ雛形)
# ---------------------------------------------------------------------------
def bbox(ranges) -> str:
    """range の list (紙 1 枚ずつの page) を 1 つの range に (snapshot / excel_ops の対象 = 刷る全域)。"""
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.cell import range_boundaries

    bs = [range_boundaries(str(r).replace("$", "")) for r in (ranges if isinstance(ranges, (list, tuple)) else [ranges])]
    c0, r0 = min(b[0] for b in bs), min(b[1] for b in bs)
    c1, r1 = max(b[2] for b in bs), max(b[3] for b in bs)
    return f"{get_column_letter(c0)}{r0}:{get_column_letter(c1)}{r1}"


def snapshot(ws, area: str) -> dict:
    """area の中の体裁 (行高・結合・折り返し・揃え・字の大きさ・表示書式・下罫線・上罫線・白黒) を控える。"""
    from openpyxl.cell.cell import MergedCell
    from openpyxl.utils.cell import range_boundaries

    c0, r0, c1, r1 = range_boundaries(area.replace("$", ""))
    cells = {}
    for row in ws.iter_rows(min_row=r0, max_row=r1, min_col=c0, max_col=c1):
        for c in row:
            if isinstance(c, MergedCell):
                continue
            a = c.alignment
            bd = c.border
            cells[c.coordinate] = (bool(a.wrap_text), a.horizontal, a.vertical,
                                   float(c.font.sz) if c.font is not None and c.font.sz else None, c.number_format,
                                   bd.bottom.style if bd is not None and bd.bottom is not None else None,
                                   bd.top.style if bd is not None and bd.top is not None else None)
    return {"rows": {r: ws.row_dimensions[r].height for r in range(r0, r1 + 1)},
            "merges": {str(m) for m in ws.merged_cells.ranges}, "cells": cells,
            "bw": bool(ws.page_setup.blackAndWhite)}


def _border_ranges(changes: list, anchors: set) -> list:
    """罫線の変更 [(coord, edge, style)] を、 同じ行・同じ縁・同じ style で列が続く分ごとに 1 つの range にまとめる
    (= AppleScript の行数を cell の数でなく行の数にする)。 間の列が snapshot に無い cell (結合の内側) なら続きとみなす。
    結合の内側も range に入れて Excel に当てる = 結合セルの縁の罫線が結合の全幅に付く (openpyxl は内側の cell に
    border を持てず、 anchor の cell にしか当たらなかった)。"""
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

    by = {}
    for coord, edge, style in changes:
        col, row = coordinate_from_string(coord)
        by.setdefault((row, edge, style), []).append(column_index_from_string(col))
    anchor_cols = {}
    for coord in anchors:
        col, row = coordinate_from_string(coord)
        anchor_cols.setdefault(row, set()).add(column_index_from_string(col))
    out = []
    for (row, edge, style), cols in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        cols = sorted(set(cols))
        runs, start, prev = [], cols[0], cols[0]
        for c in cols[1:]:
            gap = [x for x in range(prev + 1, c) if x in anchor_cols.get(row, set())]
            if gap:                     # 間に変えていない anchor の cell がある = 別の range
                runs.append((start, prev))
                start = c
            prev = c
        runs.append((start, prev))
        for a, b in runs:
            rng = f"{get_column_letter(a)}{row}:{get_column_letter(b)}{row}"
            out.append((f"border_{edge}", rng, style))
    return out


def excel_ops(before: dict, ws, area: str) -> list:
    """snapshot の後に openpyxl で当てた体裁の変更を、 Excel に当てる操作の list にする (excel.ops_lines の形)。
    罫線 (下・上) の変更は行ごとの range にまとめる (``_border_ranges``)。 spec の render: drop_shape は
    ("delete_shape", 名前) = Excel が staged copy の図形を落とす (保存しないので元は変わらない)。"""
    ops = [("delete_shape", n) for n in sorted((getattr(ws.parent, "_formcase_drop_shapes", None) or {}).get(ws.title, ()))]
    after = snapshot(ws, area)
    ops += [("unmerge", m) for m in sorted(before["merges"] - after["merges"])]
    ops += [("merge", m) for m in sorted(after["merges"] - before["merges"])]
    borders = []
    for coord, (w, h, v, sz, nf, bb, bt) in after["cells"].items():
        b = before["cells"].get(coord)
        if b is None:
            continue
        if nf != b[4]:
            ops.append(("number_format", coord, nf))
        if sz is not None and sz != b[3]:
            ops.append(("font_size", coord, sz))
        if h != b[1]:
            ops.append(("halign", coord, h or "general"))
        if v != b[2]:
            ops.append(("valign", coord, v or "bottom"))
        if w != b[0]:
            ops.append(("wrap", coord, w))
        if bb != b[5]:
            borders.append((coord, "bottom", bb))
        if bt != (b[6] if len(b) > 6 else None):
            borders.append((coord, "top", bt))
    ops += _border_ranges(borders, set(after["cells"]))
    ops += [("row_height", r, h) for r, h in after["rows"].items() if h is not None and h != before["rows"].get(r)]
    if after["bw"] != before["bw"]:
        ops.append(("black_and_white", after["bw"]))
    return ops


# ---------------------------------------------------------------------------
# 3. 値の長さで決まる行高・折り返し
# ---------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _fonts():
    """font 名 → (advance の dict, unitsPerEm)。 Excel 同梱の font を読む (無ければ空 = 既定の幅で見積もる)。"""
    out = {}
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except ImportError:
        return out
    for fn in FONT_FILES:
        p = DFONTS / fn
        if not p.exists():
            continue
        try:
            fonts = TTCollection(str(p)).fonts if p.suffix == ".ttc" else [TTFont(str(p))]
        except Exception:  # noqa: BLE001
            continue
        for t in fonts:
            names = {n.toUnicode() for n in t["name"].names if n.nameID in (1, 4)}
            for n in names:
                out.setdefault(n, t)
    return out


@lru_cache(maxsize=None)
def _advance(font_name: str, ch: str) -> float:
    """1 字の幅 (em)。 font が無い / 字が無い = 全角 1.0・半角 0.6 (広め)。"""
    t = _fonts().get(font_name or "")
    if t is not None:
        g = t.getBestCmap().get(ord(ch))
        if g is not None:
            return t["hmtx"][g][0] / t["head"].unitsPerEm
    return 0.6 if ord(ch) < 0x2E80 else 1.0


LINE_GAP = 1.04   # 行の送り ÷ font の行の高さ (hhea の ascent − descent + lineGap)。 実測: 游ゴシック 12pt の
                  # 折り返し = 20.0pt (Mac Excel の PDF、 行の高さ 1.602 em × 1.04)。 MS 系は行の高さ 1.0 em で、
                  # 実測 1.28 (= 下限 LINE_PITCH) の方が大きい


@lru_cache(maxsize=None)
def line_pitch(font_name: str) -> float:
    """行の送り ÷ font size。 font の行の高さ × LINE_GAP と LINE_PITCH の大きい方 (= 游ゴシック・メイリオの行は
    MS 系より 3 割高い。 一律 1.3 で見ると折り返した 2 行が行の上下の点線に掛かった実測がある)。"""
    t = _fonts().get(font_name or "")
    if t is None:
        return LINE_PITCH
    try:
        h = t["hhea"]
        em = (h.ascent - h.descent + h.lineGap) / t["head"].unitsPerEm
    except Exception:  # noqa: BLE001
        return LINE_PITCH
    return max(LINE_PITCH, em * LINE_GAP)


def text_lines(text: str, font_name: str, size: float, width_pt: float) -> int:
    avail = max(width_pt - PAD_W, size)
    n = 0
    for part in str(text).split("\n"):
        w = sum(_advance(font_name, ch) for ch in part) * size
        n += max(1, math.ceil(w / avail))
    return n


def _box(ws, coord):
    for m in ws.merged_cells.ranges:
        if coord in m:
            return m.min_col, m.min_row, m.max_col, m.max_row, True
    c = ws[coord]
    return c.column, c.row, c.column, c.row, False


def _col_width_units(ws, ci):
    from openpyxl.utils import get_column_letter

    d = ws.column_dimensions.get(get_column_letter(ci))
    for dim in ws.column_dimensions.values():
        if (dim.min or 0) <= ci <= (dim.max or 0) and dim.width:
            d = dim
            break
    if d is not None and d.width:
        return 0.0 if d.hidden else float(d.width)
    sf = ws.sheet_format
    return float(sf.defaultColWidth if sf.defaultColWidth is not None else (sf.baseColWidth or 8) + 0.71)


def _row_h(ws, r):
    h = ws.row_dimensions[r].height
    if h is not None:
        return float(h)
    d = ws.sheet_format.defaultRowHeight
    return float(d) if d else 13.5


def fit_text(wb, wbv, sheets, frozen_max=None, extra=None, base=None) -> list:
    """sheets の記入値 (wbv = data_only で読んだ同じ workbook) が収まるよう、 wb の折り返しと行高を変える。

    base = 雛形を data_only で読んだ workbook。 雛形と同じ値の cell (= label・注意書き) は触らない (雛形の作者が
    その幅で 1 行に収めた字を、 控えめな見積りで折り返さない)。 extra = {(sheet, top-left coord): dict} = 前回の
    PDF で切れ・はみ出しが出た欄 = {"wrap": 折り返しにする, "pt": 今の高さに足す}。 frozen_max = この高さ以下の行は
    伸ばさない (日程表の潰した行)。
    変えた箇所の説明を返す。"""
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter

    extra = extra or {}
    changed = []
    for name in sheets:
        ws, wv = _sheet(wb, name), _sheet(wbv, name)
        if ws is None or wv is None:
            continue
        wbase = _sheet(base, name) if base is not None else None
        key = ws.title.strip()
        seen = set()
        todo = []
        for row in wv.iter_rows():
            for c in row:
                if not isinstance(c.value, str) or not c.value.strip():
                    continue
                if wbase is not None and wbase[c.coordinate].value == c.value:
                    continue
                c0, r0, c1, r1, merged = _box(ws, c.coordinate)
                tl = f"{get_column_letter(c0)}{r0}"
                if tl in seen:
                    continue
                seen.add(tl)
                todo.append((tl, c.value, c0, r0, c1, r1, merged))
        for tl, text, c0, r0, c1, r1, merged in todo:
            cell = ws[tl]
            al = cell.alignment
            if al.horizontal in ("centerContinuous", "fill"):
                continue
            ex = extra.get((key, tl)) or {}
            add, force_wrap = float(ex.get("pt", 0) or 0), bool(ex.get("wrap"))
            if not merged and not al.wrap_text and not (add or force_wrap):
                continue                                   # 単独 cell の折り返さない値 = 隣へ伸びる前提の欄
            font = cell.font
            size = float(font.sz or 11)
            width = sum(_col_width_units(ws, ci) for ci in range(c0, c1 + 1)) * PT_PER_WIDTH_UNIT
            lines = text_lines(text, font.name, size, width)
            if (lines > 1 or add or force_wrap) and not al.wrap_text:
                cell.alignment = Alignment(horizontal=al.horizontal, vertical=al.vertical or "center", wrap_text=True,
                                           shrink_to_fit=al.shrink_to_fit, indent=al.indent,
                                           text_rotation=al.text_rotation)
                changed.append(f"{key}!{tl} 折り返し")
            rows = list(range(r0, r1 + 1))
            have = sum(_row_h(ws, r) for r in rows)
            # 1 行目 = 字の高さ (LINE_PITCH、 MS 系の実測) / 2 行目から = font の行の送り (游ゴシックは 1.67)。 1 行の値で
            # 行を伸ばさない (= 雛形の行は作者がその font の 1 行に合わせてある。 足りなければ PDF の gate が拾う)
            need = size * (LINE_PITCH + (lines - 1) * line_pitch(font.name)) + PAD_H
            if add:                                        # PDF で足りなかった欄 = 見積りでなく今の高さに足す
                need = max(need, have) + add
            grow = [r for r in rows if frozen_max is None or _row_h(ws, r) > frozen_max]
            if need <= have + 1e-6 or not grow:
                continue
            per = math.ceil((need - have) / len(grow) * 4) / 4       # Excel の行高の格子 (0.25pt)
            for r in grow:
                ws.row_dimensions[r].height = _row_h(ws, r) + per
            changed.append(f"{key}!{tl} 行 {r0}-{r1} +{per * len(grow):.2f}pt ({lines} 行)")
    return changed


# ---------------------------------------------------------------------------
# 日程表（予定） の正規化 (fill-rules §13)
# ---------------------------------------------------------------------------
def normalize_nittei(wb, spec: dict) -> list:
    """wb (openpyxl) の日程表（予定） を正規化する。 変えた箇所の説明を返す (空 = 何も変えていない)。

    - 使っている block の下段 slot (C{a+3} が空) の 3 行 → 3pt / 丸ごと使っていない block の 6 行 → 3pt
    - 日時欄〜所在地欄 (date 列 〜 days 列の手前) の hair 罫線 (top / bottom) を消す
    - 表下端 (最終 block の最終行) の bottom 罫線を表の右端 (days 列の merge の端) まで thin に揃える"""
    from openpyxl.styles import Border, Side
    from openpyxl.utils import column_index_from_string, get_column_letter

    g = _geom(spec)
    if ((spec.get("nittei") or {}).get("layout") or {}).get("collapsed_row_max_pt") is None:
        return []          # この様式の表に行を潰す規則が無い (= 雛形の block をそのまま刷る)
    ws = _sheet(wb, g["sheet"])
    if ws is None or not g["anchors"] or not g["date"] or not g["duty"]:
        return []
    changed = []
    anchors = g["anchors"]

    def text(coord):
        v = ws[coord].value
        return "" if v is None else str(v).strip()

    used = [a for a in anchors if text(f"{g['date']}{a}")]
    rows_to_collapse = []
    for a in anchors:
        if a in used:
            if not text(f"{g['date']}{a + 3}"):
                rows_to_collapse += [a + 3, a + 4, a + 5]
        else:
            rows_to_collapse += list(range(a, a + 6))
    for r in rows_to_collapse:
        h = ws.row_dimensions[r].height
        if h is None or abs(h - COLLAPSED_PT) > 1e-6:
            ws.row_dimensions[r].height = COLLAPSED_PT
            changed.append(f"r{r} 行高 {h} → {COLLAPSED_PT}")
    # hair 点線は日時欄〜所在地欄 (date 列 〜 days 列の手前) の全幅で消す (残すのは days 列の merge の内側だけ)
    c0 = column_index_from_string(g["date"])
    c1 = column_index_from_string(g["days"] or g["duty"])
    for r in range(anchors[0], anchors[-1] + 6):
        for col in range(c0, c1):
            cell = ws[f"{get_column_letter(col)}{r}"]
            b = cell.border
            top = b.top if not (b.top is not None and b.top.style == "hair") else Side(style=None)
            bottom = b.bottom if not (b.bottom is not None and b.bottom.style == "hair") else Side(style=None)
            if top is not b.top or bottom is not b.bottom:
                try:
                    cell.border = Border(left=copy(b.left), right=copy(b.right), top=top, bottom=bottom,
                                         diagonal=copy(b.diagonal), diagonalUp=b.diagonalUp,
                                         diagonalDown=b.diagonalDown, outline=b.outline,
                                         vertical=copy(b.vertical), horizontal=copy(b.horizontal))
                    changed.append(f"{cell.coordinate} hair 罫線を消す")
                except AttributeError:
                    pass
    last = anchors[-1] + 5
    right = column_index_from_string(g["days"]) + 2 if g.get("days") else c1   # days 列は 3 列の merge (AF:AH)
    for L in (get_column_letter(c) for c in range(c0, right + 1)):
        try:
            if _set_bottom(ws[f"{L}{last}"], "thin"):
                changed.append(f"{L}{last} 表下端を thin に")
        except AttributeError:
            pass
    return changed


@lru_cache(maxsize=None)
def _template_values(path: str):
    import warnings

    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(path, data_only=True)


def template_row_heights(wb, base, sheets) -> list:
    """刷る sheet の行高を雛形の行高に戻す (= 旧 driver が案件の xlsx に焼いた行高 〔全行 25pt 等〕 を体裁の出どころに
    しない。 行はこの後 fit_text が値の長さで伸ばす)。 変えた行の数を返す。"""
    changed = []
    for name in sheets:
        ws, wt = _sheet(wb, name), _sheet(base, name)
        if ws is None or wt is None:
            continue
        rows = set(ws.row_dimensions) | set(wt.row_dimensions)
        n = 0
        for r in rows:
            want = wt.row_dimensions[r].height if r in wt.row_dimensions else None
            if ws.row_dimensions[r].height != want:
                ws.row_dimensions[r].height = want
                n += 1
        if n:
            changed.append(f"{ws.title.strip()} 行高を雛形に戻す ({n} 行)")
    return changed


def prepare(wb, wbv, spec: dict, extra=None, sheets=None) -> list:
    """build の temp と日程表 gate (--layout-by-recipe) で共通の体裁 = 雛形の行高 → 雛形の欠陥 → 日程表の正規化 →
    値の行高。 page の設定 (1 まとまり 1 枚) は recipe が印刷範囲ごとに当てる。
    sheets = 当てる sheet (既定 = spec の group が刷る sheet 全部)。"""
    from . import specs as S

    tpl = S.template_path(spec)
    base = _template_values(str(tpl)) if tpl.exists() else None
    sheets = list(sheets) if sheets is not None else printed_sheets(spec)
    changed = template_row_heights(wb, base, sheets) if base is not None else []
    changed += apply_render_fixes(wb, spec, wbv=wbv, sheets=sheets)
    changed += normalize_nittei(wb, spec)
    changed += fit_text(wb, wbv, sheets, frozen_max=_geom(spec)["collapsed_max"], extra=extra, base=base)
    return changed
