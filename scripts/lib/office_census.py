"""office_census.py — OOXML package (xlsx / docx / pptx) が「紙に出すもの」 を、 道具に依らず zip の XML から数える。

WHY (conventions/form-case-pipeline.md#fidelity、 office-automation.md#openpyxl-destroys-drawings):
  openpyxl は図形・form control・拡張の入力規則を**読み込みの時点で捨てる**ので、 openpyxl で数えると保存で消える
  ものが最初から 0 に見える (実測: 他人の xlsx への書込み道具の --inspect が常に 0)。 python-docx も run の中の
  図・field・記号を run.text の書き換えで消す。 ∴ 「消す道具の目で数えない」: zip の部品の名前と XML の要素を
  正規表現で数える。 名前を知らない種類の損失も「数が減った」 として現れるように、 部品の種類ごとの数も持つ。

WHAT:
  census(path_or_bytes) -> {"kind": "xlsx"|"docx"|"pptx"|"?", "counts": {種類: 数}, "parts": {部品の型: 数}}
  losses(before, after, accept=()) -> [(種類, 前, 後, 紙に出るか)]   # 減った種類だけ (accept で宣言した種類は除く)
  lines(losses, note="") -> ["🔴 図形: 9 → 0 …", "⚪ 拡張の入力規則: 11 → 0 (紙に出ない)"]
  PAPER = 紙に出る種類 (🔴)。 他は ⚪ (情報)

種類 (xlsx): 図形 (drawing の anchor) / 図形の字 (a:t) / form control (ctrlProp) / VML / 画像 (media) / 条件付き書式 /
  拡張の入力規則 (x14) / 数式 / 数式の cache (f と v を両方持つ c) / comment / 印刷設定 (printerSettings) / 定義名
種類 (docx): 図 (w:drawing) / 図・textbox (w:pict) / textbox の字 (w:txbxContent) / field / 記号 (w:sym) / content control (w:sdt) /
  埋め込み object / header / footer / 画像 (media) / 表 / 段落
種類 (pptx): slide / 図形 (p:sp) / 画像 (media)

selftest: python3 office_census.py --selftest (合成の xlsx / docx、 Office 不要)
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile

# 紙に出る種類 (減ったら 🔴)。 それ以外は ⚪ (情報 = file を相手に渡す時だけ意味を持つ)
PAPER = {
    "図形", "図形の字", "form control", "VML", "画像", "条件付き書式", "数式の cache",
    "図", "図・textbox", "textbox の字", "field", "記号", "content control", "埋め込み object", "header", "footer",
    "slide", "図形 (slide)",
}

_XLSX_PART_KINDS = [
    ("図形", re.compile(r"^xl/drawings/drawing\d+\.xml$")),
    ("VML", re.compile(r"^xl/drawings/vmlDrawing\d+\.vml$")),
    ("form control", re.compile(r"^xl/ctrlProps/ctrlProp\d+\.xml$")),
    ("画像", re.compile(r"^xl/media/")),
    ("comment", re.compile(r"^xl/comments\d*\.xml$|^xl/comments/comment\d+\.xml$")),
    ("印刷設定", re.compile(r"^xl/printerSettings/")),
]
_ANCHOR = re.compile(r"<xdr:(?:twoCellAnchor|oneCellAnchor|absoluteAnchor)\b")
_A_T = re.compile(r"<a:t>[^<]+</a:t>")
# form control (checkbox 等) の DrawingML 側は mc:AlternateContent に包まれる = 図形とは別に数える (form control の part で数える)
_ALT = re.compile(r"<mc:AlternateContent\b.*?</mc:AlternateContent>", re.S)
# cell = <c …/> (空、 自己閉じ) か <c …>…</c>。 自己閉じを別に受けないと次の </c> まで読んで O(n²) に落ちる (実測)
_CELL = re.compile(r"<c\b[^>]*?(?:/>|>(.*?)</c>)", re.S)
_X14_DV = re.compile(r"<x14:dataValidation\b")
_CF = re.compile(r"<(?:x14:)?conditionalFormatting\b")
_DEFINED = re.compile(r"<definedName\b")

_DOCX_ELEMS = [
    ("図", "w:drawing"), ("図・textbox", "w:pict"), ("textbox の字", "w:txbxContent"), ("field", "w:fldChar"),
    ("field (簡易)", "w:fldSimple"), ("記号", "w:sym"), ("content control", "w:sdt"), ("埋め込み object", "w:object"),
    ("表", "w:tbl"), ("段落", "w:p"),
]


def _open(src) -> zipfile.ZipFile:
    if isinstance(src, (bytes, bytearray)):
        return zipfile.ZipFile(io.BytesIO(bytes(src)))
    return zipfile.ZipFile(str(src))


def _kind(names: set) -> str:
    if "xl/workbook.xml" in names:
        return "xlsx"
    if "word/document.xml" in names:
        return "docx"
    if any(n.startswith("ppt/slides/") for n in names):
        return "pptx"
    return "?"


def _part_kinds(names) -> dict:
    out = {}
    for n in names:
        k = re.sub(r"\d+", "N", n)
        out[k] = out.get(k, 0) + 1
    return out


def _text(z, n) -> str:
    return z.read(n).decode("utf-8", "replace")


def _xlsx_sheet_parts(z, names) -> dict:
    """sheet 名 → worksheet part。"""
    import posixpath
    import xml.etree.ElementTree as ET

    if "xl/workbook.xml" not in names:
        return {}
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            t = r.get("Target") or ""
            rels[r.get("Id")] = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join("xl", t))
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
        rid = sh.get("{%s}id" % ns_r)
        if rid in rels:
            out[sh.get("name")] = rels[rid]
    return out


def _reachable(z, names, parts) -> set:
    """parts (worksheet の part) から rels を辿って届く part (drawing / vml / ctrlProp / comment / media)。"""
    import posixpath
    import xml.etree.ElementTree as ET

    seen, todo = set(), list(parts)
    while todo:
        part = todo.pop()
        if part in seen:
            continue
        seen.add(part)
        rp = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        if rp not in names:
            continue
        for r in ET.fromstring(z.read(rp)):
            if r.get("TargetMode") == "External":
                continue
            t = r.get("Target") or ""
            tgt = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(part), t))
            if tgt in names:
                todo.append(tgt)
    return seen


def census(src, sheets=None) -> dict:
    """package の「紙に出るもの」 の数。 壊れた zip は zipfile.BadZipFile のまま (呼び元が扱う)。
    sheets = xlsx でこの名前の sheet だけを数える (= sheet を消した temp と読み込み元を同じ範囲で比べるため。 sheet から
    rels で届く drawing・VML・ctrlProp・comment・media だけを数える)。 None = 全部。"""
    with _open(src) as z:
        names = set(z.namelist())
        kind = _kind(names)
        counts: dict = {}
        keep = None
        if kind == "xlsx" and sheets is not None:
            sp = _xlsx_sheet_parts(z, names)
            want = {s.strip() for s in sheets}
            keep = _reachable(z, names, [p for n, p in sp.items() if n.strip() in want])
        if kind == "xlsx":
            for label, rx in _XLSX_PART_KINDS:
                counts[label] = sum(1 for n in names if rx.search(n) and (keep is None or n in keep))
            counts["図形の字"] = 0
            counts["拡張の入力規則"] = counts["条件付き書式"] = counts["数式"] = counts["数式の cache"] = 0
            counts["定義名"] = 0
            for n in sorted(names):
                if keep is not None and n not in keep and n != "xl/workbook.xml":
                    continue
                if re.match(r"^xl/drawings/drawing\d+\.xml$", n):
                    x = _ALT.sub("", _text(z, n))           # form control の anchor と caption は除く (別の種類で数える)
                    counts["図形"] = counts.get("図形", 0) - 1 + len(_ANCHOR.findall(x))   # part 数でなく anchor 数
                    counts["図形の字"] += len(_A_T.findall(x))
                elif re.match(r"^xl/worksheets/sheet\d+\.xml$", n):
                    x = _text(z, n)
                    counts["拡張の入力規則"] += len(_X14_DV.findall(x))
                    counts["条件付き書式"] += len(_CF.findall(x))
                    for body in _CELL.findall(x):
                        if body and "<f" in body:
                            counts["数式"] += 1
                            if "<v>" in body or "<v " in body:
                                counts["数式の cache"] += 1
                elif n == "xl/workbook.xml":
                    counts["定義名"] = len(_DEFINED.findall(_text(z, n)))
            counts["図形"] = max(0, counts["図形"])
        elif kind == "docx":
            body = "".join(_text(z, n) for n in sorted(names)
                           if re.match(r"^word/(document|header\d*|footer\d*)\.xml$", n))
            for label, tag in _DOCX_ELEMS:
                counts[label] = len(re.findall("<" + re.escape(tag) + r"\b", body))
            counts["header"] = sum(1 for n in names if re.match(r"^word/header\d*\.xml$", n))
            counts["footer"] = sum(1 for n in names if re.match(r"^word/footer\d*\.xml$", n))
            counts["画像"] = sum(1 for n in names if n.startswith("word/media/"))
        elif kind == "pptx":
            counts["slide"] = sum(1 for n in names if re.match(r"^ppt/slides/slide\d+\.xml$", n))
            counts["図形 (slide)"] = sum(len(re.findall(r"<p:sp\b", _text(z, n))) for n in names
                                       if re.match(r"^ppt/slides/slide\d+\.xml$", n))
            counts["画像"] = sum(1 for n in names if n.startswith("ppt/media/"))
        return {"kind": kind, "counts": counts, "parts": _part_kinds(names if keep is None else {n for n in names if n in keep})}


def losses(before, after, accept=()) -> list:
    """減った種類 = [(種類, 前, 後, 紙に出るか)]。 before / after = census() の結果か path / bytes。
    accept = 減ってよいと宣言した種類 (理由は呼び元の spec に)。 部品の型 (parts) の減少も「部品: <型>」 として出す
    (= 名前を知らない種類の損失を黙らせない)。"""
    b = before if isinstance(before, dict) and "counts" in before else census(before)
    a = after if isinstance(after, dict) and "counts" in after else census(after)
    acc = set(accept or ())
    out = []
    for k, bv in b["counts"].items():
        av = a["counts"].get(k, 0)
        if av < bv and k not in acc:
            out.append((k, bv, av, k in PAPER))
    seen = {k for k, *_ in out}
    for k, bv in b["parts"].items():
        av = a["parts"].get(k, 0)
        if av < bv and ("部品: " + k) not in acc and not _covered(k, seen):
            out.append(("部品: " + k, bv, av, False))
    return out


def _covered(part_kind: str, seen: set) -> bool:
    """部品の減少が、 上で数えた種類 (図形・form control・画像…) に既に現れているか。"""
    m = {"xl/drawings/drawingN.xml": "図形", "xl/drawings/vmlDrawingN.vml": "VML", "xl/ctrlProps/ctrlPropN.xml": "form control",
         "xl/media/": "画像", "xl/printerSettings/printerSettingsN.bin": "印刷設定"}
    for pfx, k in m.items():
        if part_kind.startswith(pfx.rstrip("/")) and k in seen:
            return True
    return part_kind.startswith("xl/comments") and "comment" in seen


class PaperLossError(RuntimeError):
    """openpyxl 等の保存で「紙に出るもの」 が減った (図形・form control・画像・条件付き書式…)。"""


def assert_no_paper_loss(before, after, accept=(), label: str = "", sheets=None) -> list:
    """保存の直後の関門 (D7、 2026-09-25): ``after`` (保存した file) を ``before`` (読み込み元の雛形) と比べ、 紙に出るものが
    減っていれば PaperLossError (行を message に)。 減っていなければ損失の list (紙に出ないものだけ) を返す。
    明示して通すには環境変数 ``OFFICE_CENSUS_ALLOW_LOSS=1`` (= 減ったと知って出す。 stderr に行を出す)。
    使い方 (openpyxl で保存する script の ``wb.save(OUT)`` の直後に 2 行):
        import office_census as OC; OC.assert_no_paper_loss(TEMPLATE, OUT, label=__file__)"""
    import os
    import sys

    lo = losses(census(before, sheets=sheets), census(after, sheets=sheets), accept=accept)
    paper = [x for x in lo if x[3]]
    if not paper:
        return lo
    msg = lines(paper, note=f"{label or after}: 保存で紙に出るものが減った (openpyxl の保存 = 層1 office-automation.md#openpyxl-destroys-drawings)")
    if os.environ.get("OFFICE_CENSUS_ALLOW_LOSS") == "1":
        print("\n".join("⚠️ (OFFICE_CENSUS_ALLOW_LOSS=1 で通す) " + m for m in msg), file=sys.stderr)
        return lo
    raise PaperLossError("\n".join(msg) + "\n→ Excel で書く経路 (drive-xlsx-set-cells.py / formcase の Excel の操作) へ。 "
                         "減ったと知って出すなら OFFICE_CENSUS_ALLOW_LOSS=1")


def lines(loss_list, note: str = "") -> list:
    out = []
    for k, bv, av, paper in loss_list:
        mark = "🔴" if paper else "⚪"
        tail = "" if paper else " (紙に出ない)"
        out.append(f"{mark} {k}: {bv} → {av}{tail}" + (f" {note}" if note and paper else ""))
    return out


# ---------------------------------------------------------------------------
# selftest (合成の package、 Office 不要)
# ---------------------------------------------------------------------------
def _mk_xlsx(with_drawing=True, with_ctrl=True, with_x14=True, cache=True, with_cf=True) -> bytes:
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>A1</f>' + ("<v>1</v>" if cache else "") + "</c></row></sheetData>"
             + ('<conditionalFormatting sqref="A1"><cfRule type="expression"/></conditionalFormatting>' if with_cf else "")
             + ('<extLst><ext><x14:dataValidations xmlns:x14="x"><x14:dataValidation/></x14:dataValidations></ext></extLst>' if with_x14 else "")
             + ('<controls><mc:AlternateContent xmlns:mc="mc"><mc:Choice Requires="x14"><control shapeId="4100" r:id="rIdC" name="Check Box 1">'
                '<controlPr><anchor moveWithCells="1"><from><xdr:col>6</xdr:col><xdr:colOff>238125</xdr:colOff><xdr:row>8</xdr:row><xdr:rowOff>9525</xdr:rowOff></from>'
                '<to><xdr:col>7</xdr:col><xdr:colOff>114300</xdr:colOff><xdr:row>8</xdr:row><xdr:rowOff>247650</xdr:rowOff></to></anchor></controlPr></control>'
                '</mc:Choice></mc:AlternateContent></controls>' if with_ctrl else "")
             + "</worksheet>")
    drawing = ('<xdr:wsDr xmlns:xdr="x" xmlns:a="a"><xdr:twoCellAnchor><xdr:sp><xdr:txBody><a:p><a:r><a:t>外部資金</a:t></a:r></a:p>'
               "</xdr:txBody></xdr:sp></xdr:twoCellAnchor><xdr:oneCellAnchor><xdr:sp/></xdr:oneCellAnchor></xdr:wsDr>")
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    P = "http://schemas.openxmlformats.org/package/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{R}">'
                   '<sheets><sheet name="Sheet" sheetId="1" r:id="rId1"/></sheets>'
                   '<definedNames><definedName name="a"/></definedNames></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        rels = ""
        if with_drawing:
            z.writestr("xl/drawings/drawing1.xml", drawing)
            z.writestr("xl/drawings/_rels/drawing1.xml.rels", f'<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/image" Target="../media/image1.png"/></Relationships>')
            z.writestr("xl/media/image1.png", b"\x89PNG")
            rels += f'<Relationship Id="rIdD" Type="{R}/drawing" Target="../drawings/drawing1.xml"/>'
        if with_ctrl:
            z.writestr("xl/ctrlProps/ctrlProp1.xml", '<formControlPr objectType="CheckBox" checked="Checked"/>')
            z.writestr("xl/drawings/vmlDrawing1.vml", "<xml/>")
            rels += (f'<Relationship Id="rIdC" Type="{R}/ctrlProp" Target="../ctrlProps/ctrlProp1.xml"/>'
                     f'<Relationship Id="rIdV" Type="{R}/vmlDrawing" Target="../drawings/vmlDrawing1.vml"/>')
        z.writestr("xl/worksheets/_rels/sheet1.xml.rels", f'<Relationships xmlns="{P}">{rels}</Relationships>')
    return buf.getvalue()


def _mk_docx(with_objects=True) -> bytes:
    body = "<w:document xmlns:w=\"w\"><w:body><w:p><w:r><w:t>見出し</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>"
    if with_objects:
        body += ("<w:p><w:r><w:drawing/></w:r><w:r><w:sym w:char=\"F0A8\"/></w:r><w:r><w:fldChar/></w:r></w:p>"
                 "<w:p><w:r><w:pict><w:txbxContent><w:p><w:r><w:t>枠の字</w:t></w:r></w:p></w:txbxContent></w:pict></w:r></w:p>"
                 "<w:sdt/>")
    body += "</w:body></w:document>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", body)
        z.writestr("word/footer1.xml", "<w:ftr xmlns:w=\"w\"><w:p><w:r><w:t>頁</w:t></w:r></w:p></w:ftr>")
        if with_objects:
            z.writestr("word/media/image1.png", b"\x89PNG")
    return buf.getvalue()


def selftest() -> int:
    fails = 0

    def expect(label, cond, detail=""):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + label + ("" if cond else f": {detail}"))
        fails += not cond

    full, bare = _mk_xlsx(), _mk_xlsx(with_drawing=False, with_ctrl=False, with_x14=False, cache=False)
    c = census(full)
    expect("xlsx: 図形は anchor の数 (2)、 字 1、 form control 1、 画像 1、 数式 1 (cache 1)、 拡張の入力規則 1",
           c["kind"] == "xlsx" and c["counts"]["図形"] == 2 and c["counts"]["図形の字"] == 1 and c["counts"]["form control"] == 1
           and c["counts"]["画像"] == 1 and c["counts"]["数式"] == 1 and c["counts"]["数式の cache"] == 1
           and c["counts"]["拡張の入力規則"] == 1 and c["counts"]["条件付き書式"] == 1, c["counts"])
    lo = losses(full, bare)
    got = {k: (b, a, p) for k, b, a, p in lo}
    expect("xlsx: 消えた種類が全部出る (図形・字・form control・VML・画像・数式の cache = 🔴 / 入力規則 = ⚪)",
           {"図形", "図形の字", "form control", "VML", "画像", "数式の cache", "拡張の入力規則"} <= set(got)
           and got["図形"][2] and got["form control"][2] and not got["拡張の入力規則"][2], got)
    expect("xlsx: 数式そのものは残っている (cache だけが減る)", "数式" not in got, got)
    expect("xlsx: accept で宣言した種類は出ない", not any(k == "form control" for k, *_ in losses(full, bare, accept=["form control"])))
    expect("xlsx: 同じ package なら損失なし", losses(full, full) == [])
    expect("xlsx: sheets= で無い sheet 名を指すと 0 (= sheet を消した temp と同じ範囲で比べられる)",
           census(full, sheets=["無い"])["counts"]["図形"] == 0 and census(full, sheets=["Sheet"])["counts"]["図形"] == 2,
           (census(full, sheets=["無い"])["counts"], census(full, sheets=["Sheet"])["counts"]))
    ls = lines(lo)
    expect("lines: 🔴 と ⚪ の印", any(x.startswith("🔴 図形:") for x in ls) and any(x.startswith("⚪ 拡張の入力規則:") for x in ls), ls)
    d1, d0 = _mk_docx(), _mk_docx(with_objects=False)
    cd = census(d1)
    expect("docx: 図 1・記号 1・field 1・textbox の字 1・content control 1・footer 1・画像 1",
           cd["kind"] == "docx" and cd["counts"]["図"] == 1 and cd["counts"]["記号"] == 1 and cd["counts"]["field"] == 1
           and cd["counts"]["textbox の字"] == 1 and cd["counts"]["content control"] == 1 and cd["counts"]["footer"] == 1
           and cd["counts"]["画像"] == 1, cd["counts"])
    gd = {k for k, *_ in losses(d1, d0)}
    expect("docx: run の中身が消えた損失が出る (図・記号・field・textbox の字・content control・画像)",
           {"図", "記号", "field", "textbox の字", "content control", "画像", "図・textbox"} <= gd, gd)
    expect("docx: footer は残っている", "footer" not in gd)
    # 保存の直後の関門 (D7): 紙に出るものが減れば PaperLossError、 OFFICE_CENSUS_ALLOW_LOSS=1 で通す
    import os
    import tempfile

    td = tempfile.mkdtemp(prefix="office-census-")
    pf, pb = os.path.join(td, "full.xlsx"), os.path.join(td, "bare.xlsx")
    with open(pf, "wb") as f:
        f.write(full)
    with open(pb, "wb") as f:
        f.write(bare)
    try:
        assert_no_paper_loss(pf, pb, label="t")
        expect("assert_no_paper_loss: 減れば止める", False)
    except PaperLossError as e:
        expect("assert_no_paper_loss: 減れば止める (行に 🔴 と案内)", "🔴 図形" in str(e) and "OFFICE_CENSUS_ALLOW_LOSS" in str(e), str(e)[:200])
    expect("assert_no_paper_loss: 減っていなければ通る (紙に出ない損失は返す)", isinstance(assert_no_paper_loss(pf, pf), list))
    os.environ["OFFICE_CENSUS_ALLOW_LOSS"] = "1"
    try:
        expect("assert_no_paper_loss: OFFICE_CENSUS_ALLOW_LOSS=1 なら通す", isinstance(assert_no_paper_loss(pf, pb), list))
    finally:
        del os.environ["OFFICE_CENSUS_ALLOW_LOSS"]
    # form control の一覧 (D9): sheet・名前・anchor (from の cell)・checked
    fc = form_controls(pf)
    expect("form_controls: sheet / 名前 / anchor G9 / checked を zip の XML から読む",
           len(fc) == 1 and fc[0]["sheet"] == "Sheet" and fc[0]["name"] == "Check Box 1" and fc[0]["anchor"] == "G9"
           and fc[0]["type"] == "CheckBox" and fc[0]["checked"] is True, fc)
    expect("find_control: sheet + anchor で引く (無ければ None)",
           find_control(fc, "Sheet", "g9")["name"] == "Check Box 1" and find_control(fc, "Sheet", "A1") is None
           and find_control(fc, "Sheet", "G9", index=1) is None)
    expect("form_controls: form control の無い package は空", form_controls(pb) == [])
    print("ALL PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


# ---------------------------------------------------------------------------
# form control (checkbox) の一覧 (D9、 2026-09-25) — zip の XML から (openpyxl は読む時点で捨てる)
# ---------------------------------------------------------------------------
def form_controls(src, sheets=None) -> list:
    """xlsx の form control (checkbox 等) = [{sheet, name, type, anchor, from, to, checked, part}]。
    anchor = 箱が載る cell (sheet の <controlPr><anchor><from> の col/row、 A1 形式)。 checked = ctrlProp の checked 属性。
    同じ anchor に複数の control が載ることがある (印字面が 2 つある雛形) = 呼び元は sheet + anchor + 並び (from の offset) で選ぶ。
    sheets = この名前の sheet だけ (None = 全部)。"""
    from openpyxl.utils import get_column_letter

    out = []
    with _open(src) as z:
        names = set(z.namelist())
        if "xl/workbook.xml" not in names:
            return out
        wbx = _text(z, "xl/workbook.xml")
        wrels = _text(z, "xl/_rels/workbook.xml.rels") if "xl/_rels/workbook.xml.rels" in names else ""
        rid2t = {m.group(1): m.group(2) for m in re.finditer(r'Id="([^"]+)"[^>]*Target="([^"]+)"', wrels)}
        for m in re.finditer(r'<sheet\b[^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', wbx):
            name, tgt = m.group(1), rid2t.get(m.group(2), "")
            if sheets is not None and name.strip() not in {str(s).strip() for s in sheets}:
                continue
            part = tgt.lstrip("/") if tgt.startswith("/") else "xl/" + tgt
            if part not in names:
                continue
            s = _text(z, part)
            relp = part.rsplit("/", 1)[0] + "/_rels/" + part.rsplit("/", 1)[1] + ".rels"
            rels = _text(z, relp) if relp in names else ""
            r2t = {mm.group(1): mm.group(2) for mm in re.finditer(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels)}
            for c in re.finditer(r'<control\b[^>]*?shapeId="(\d+)"[^>]*?r:id="([^"]+)"[^>]*?name="([^"]*)"[^>]*>(.*?)</control>', s, re.S):
                body = c.group(4)
                fr = re.search(r"<from>\s*<xdr:col>(\d+)</xdr:col>\s*<xdr:colOff>(-?\d+)</xdr:colOff>\s*<xdr:row>(\d+)</xdr:row>\s*<xdr:rowOff>(-?\d+)</xdr:rowOff>", body)
                to = re.search(r"<to>\s*<xdr:col>(\d+)</xdr:col>\s*<xdr:colOff>(-?\d+)</xdr:colOff>\s*<xdr:row>(\d+)</xdr:row>\s*<xdr:rowOff>(-?\d+)</xdr:rowOff>", body)
                cp = r2t.get(c.group(2), "")
                cpp = posixpath.normpath(posixpath.join(part.rsplit("/", 1)[0], cp)) if cp else ""
                cx = _text(z, cpp) if cpp in names else ""
                typ = re.search(r'objectType="(\w+)"', cx)
                out.append({"sheet": name, "name": c.group(3), "type": typ.group(1) if typ else None,
                            "anchor": f"{get_column_letter(int(fr.group(1)) + 1)}{int(fr.group(3)) + 1}" if fr else None,
                            "from": tuple(int(v) for v in fr.groups()) if fr else None,
                            "to": tuple(int(v) for v in to.groups()) if to else None,
                            "checked": bool(re.search(r'\bchecked="Checked"', cx)), "part": cpp})
    return out


def find_control(controls: list, sheet: str, anchor: str, index: int = 0, kind: str = "CheckBox") -> dict | None:
    """sheet + anchor (+ 同じ anchor の中の並び index = from の row/col の offset の順) で 1 つ選ぶ。 無ければ None。"""
    hits = [c for c in controls if c["sheet"].strip() == str(sheet).strip() and c["anchor"] == str(anchor).upper()
            and (kind is None or c["type"] == kind)]
    hits.sort(key=lambda c: (c["from"][2], c["from"][3], c["from"][0], c["from"][1]) if c["from"] else (0, 0, 0, 0))
    return hits[index] if 0 <= index < len(hits) else None


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        sys.exit(selftest())
    for p in sys.argv[1:]:
        c = census(p)
        print(f"{p}: {c['kind']} " + " / ".join(f"{k} {v}" for k, v in c["counts"].items()))
