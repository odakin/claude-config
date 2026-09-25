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


def census(src) -> dict:
    """package の「紙に出るもの」 の数。 壊れた zip は zipfile.BadZipFile のまま (呼び元が扱う)。"""
    with _open(src) as z:
        names = set(z.namelist())
        kind = _kind(names)
        counts: dict = {}
        if kind == "xlsx":
            for label, rx in _XLSX_PART_KINDS:
                counts[label] = sum(1 for n in names if rx.search(n))
            counts["図形の字"] = 0
            counts["拡張の入力規則"] = counts["条件付き書式"] = counts["数式"] = counts["数式の cache"] = 0
            counts["定義名"] = 0
            for n in sorted(names):
                if re.match(r"^xl/drawings/drawing\d+\.xml$", n):
                    x = _text(z, n)
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
        return {"kind": kind, "counts": counts, "parts": _part_kinds(names)}


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
def _mk_xlsx(with_drawing=True, with_ctrl=True, with_x14=True, cache=True) -> bytes:
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>A1</f>' + ("<v>1</v>" if cache else "") + "</c></row></sheetData>"
             '<conditionalFormatting sqref="A1"><cfRule type="expression"/></conditionalFormatting>'
             + ('<extLst><ext><x14:dataValidations xmlns:x14="x"><x14:dataValidation/></x14:dataValidations></ext></extLst>' if with_x14 else "")
             + "</worksheet>")
    drawing = ('<xdr:wsDr xmlns:xdr="x" xmlns:a="a"><xdr:twoCellAnchor><xdr:sp><xdr:txBody><a:p><a:r><a:t>外部資金</a:t></a:r></a:p>'
               "</xdr:txBody></xdr:sp></xdr:twoCellAnchor><xdr:oneCellAnchor><xdr:sp/></xdr:oneCellAnchor></xdr:wsDr>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", '<workbook><definedNames><definedName name="a"/></definedNames></workbook>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        if with_drawing:
            z.writestr("xl/drawings/drawing1.xml", drawing)
            z.writestr("xl/media/image1.png", b"\x89PNG")
        if with_ctrl:
            z.writestr("xl/ctrlProps/ctrlProp1.xml", "<formControlPr/>")
            z.writestr("xl/drawings/vmlDrawing1.vml", "<xml/>")
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
    print("ALL PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        sys.exit(selftest())
    for p in sys.argv[1:]:
        c = census(p)
        print(f"{p}: {c['kind']} " + " / ".join(f"{k} {v}" for k, v in c["counts"].items()))
