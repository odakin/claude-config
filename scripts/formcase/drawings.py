"""openpyxl の save が落とす図形 (DrawingML) を、 元の workbook から sheet 名で移し直す。

openpyxl は textbox・autoshape・線を round-trip できず、 save で drawing part ごと落とす
(= office-automation.md#openpyxl-destroys-drawings)。 様式では標題・「外部資金」 の枠・様式番号・㊞ の丸・斜線が
図形なので、 openpyxl で save した temp をそのまま PDF にすると紙から消える (実測: 区分の枠と様式番号が build の
PDF に無いまま、 値・罫線の gate は全部通っていた)。

``graft_drawings(src, dst)`` = 同 convention の回避 2 (drawing XML の移植) を 4 条件つきで行う:
  ① anchor は cell 基準 = openpyxl は行・列・結合を保つので、 同じ workbook から移せば位置はずれない
  ② 移す drawing は standalone (= 画像等の別 part を参照しない)。 参照があれば止める
  ③ 移し先の sheet に drawing が既にあれば止める (rId・part 名の衝突を作らない)
  ④ ``<drawing>`` は ``xmlns:r`` を inline で宣言して挿す (openpyxl の worksheet root は ``xmlns:r`` を持たない)

1 行の label が雛形の枠に字幅ぎりぎりで作られ、 Excel の丸めで 1 字だけ折り返される (clip の枠では消える) 時は、
枠の左右の余白だけを入る分まで縮めて折り返しを止める (``_fit_single_line``。 枠・字の大きさは変えない。 固定ピッチの
MS 系 font の label だけ)。

form control (checkbox) は移さない: DrawingML 側は VML・ctrlProps・sheet の ``<controls>`` と対で、 片方だけでは
壊れた workbook になる。 旅費様式の checkbox は該当側の label に文字 ☑ を書く規則で扱う (fill-rules §14)。

移した後の検査 = ``check-xlsx-integrity.py`` (Excel の「修復」 ダイアログは PDF 化の osascript を止めるので、
開く前に決定論で落とす)。
"""
from __future__ import annotations

import posixpath
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_DRAWING = NS_R + "/drawing"
CT_DRAWING = "application/vnd.openxmlformats-officedocument.drawing+xml"
INTEGRITY = Path(__file__).resolve().parent.parent / "check-xlsx-integrity.py"

# CT_Worksheet の要素順で <drawing> より後に来るもの (= この手前に挿す)
_AFTER_DRAWING = ("legacyDrawing", "legacyDrawingHF", "drawingHF", "picture", "oleObjects", "controls",
                  "webPublishItems", "tableParts", "extLst")


class GraftError(RuntimeError):
    pass


def _resolve(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def _rels_part(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def _rels(z: zipfile.ZipFile, part: str) -> list:
    name = _rels_part(part)
    if name not in z.namelist():
        return []
    root = ET.fromstring(z.read(name))
    return [(r.get("Id"), r.get("Type"), r.get("Target"), r.get("TargetMode")) for r in root]


def sheet_parts(z: zipfile.ZipFile) -> dict:
    """sheet 名 → worksheet part (zip 内の path)。"""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    by_id = {rid: _resolve("xl/workbook.xml", tgt) for rid, _t, tgt, _m in _rels(z, "xl/workbook.xml")}
    out = {}
    for s in wb.iter(f"{{{NS_MAIN}}}sheet"):
        rid = s.get(f"{{{NS_R}}}id")
        if rid in by_id:
            out[s.get("name")] = by_id[rid]
    return out


def _strip_alternate_content(xml: str) -> tuple:
    """最上位の mc:AlternateContent (= form control の DrawingML 側) を取り除く。 (残りの xml, 取り除いた数)。"""
    out, pos, removed = [], 0, 0
    tag = re.compile(r"<(/?)mc:AlternateContent\b[^>]*?(/?)>")
    while True:
        m = tag.search(xml, pos)
        if not m:
            out.append(xml[pos:])
            break
        if m.group(1):
            raise GraftError("drawing の mc:AlternateContent の入れ子が壊れている")
        out.append(xml[pos:m.start()])
        if m.group(2):                       # <mc:AlternateContent/> (空)
            pos, removed = m.end(), removed + 1
            continue
        depth, j = 1, m.end()
        while depth:
            n = tag.search(xml, j)
            if not n:
                raise GraftError("drawing の mc:AlternateContent が閉じていない")
            if n.group(1):
                depth -= 1
            elif not n.group(2):
                depth += 1
            j = n.end()
        pos, removed = j, removed + 1
    return "".join(out), removed


def _anchor_count(xml: str) -> int:
    return len(re.findall(r"<xdr:(?:twoCellAnchor|oneCellAnchor|absoluteAnchor)\b", xml))


_ANCHOR = re.compile(r"<xdr:(twoCellAnchor|oneCellAnchor|absoluteAnchor)\b.*?</xdr:\1>", re.S)


def _drop_named(xml: str, names: set, where: str) -> str:
    """名前 (anchor の最初の cNvPr の name) が names の anchor を取り除く。 無い名前は止める (雛形が変わった = spec を直す)。"""
    found = set()

    def repl(m):
        nm = re.search(r'<xdr:cNvPr\b[^>]*\bname="([^"]*)"', m.group(0))
        if nm and nm.group(1) in names:
            found.add(nm.group(1))
            return ""
        return m.group(0)

    xml = _ANCHOR.sub(repl, xml)
    if names - found:
        raise GraftError(f"{where}: spec の drop_shape {sorted(names - found)} が雛形の図形に無い (雛形が変わった?)")
    return xml


_FIXED_PITCH = ("MS Gothic", "ＭＳ ゴシック", "MS Mincho", "ＭＳ 明朝")
EMU_PT = 12700
_DEFAULT_INSET = 91440          # bodyPr の lIns / rIns の既定 (0.1 in)
_TIGHT = 0.95                   # 字幅 + 余白が枠の 95% を超えたら縮める (Mac Excel の実測: 99.5% で 1 字落ちた)


def _em_width(text: str) -> float:
    """固定ピッチの MS 系 font での字幅 (em)。 全角 = 1、 半角 (ASCII と半角カナ) = 0.5。"""
    return sum(0.5 if ord(c) < 0x100 or 0xFF61 <= ord(c) <= 0xFF9F else 1.0 for c in text)


def _fit_single_line(anchor: str) -> str:
    """1 行の label (段落 1 つ・改行なし・固定ピッチ font) が雛形の枠に入り切らず折り返される時だけ、 左右の余白を
    入る分まで縮める (枠の大きさ・字の大きさは変えない)。 雛形の枠は余白込みで字幅ぎりぎりに作られていて、
    Excel の字幅の丸めで 1 字だけ次の行に落ちる (実測: 枠 78pt に 16pt × 4 字 + 余白 7.2pt × 2 = 78.4pt で 4 字目が
    次の行へ。 枠の 99.5% を使う様式番号は末尾の 1 字が 2 行目に落ち、 雛形の vertOverflow="clip" で消えたまま刷られた)。"""
    body = re.search(r"<xdr:txBody>.*?</xdr:txBody>", anchor, re.S)
    ext = re.search(r'<xdr:ext cx="(\d+)"', anchor) or re.search(r'<a:ext cx="(\d+)"', anchor)
    if not body or not ext:
        return anchor
    tb = body.group(0)
    paras = [p for p in re.findall(r"<a:p>.*?</a:p>|<a:p\b[^>]*>.*?</a:p>", tb, re.S)
             if re.search(r"<a:t>[^<]+</a:t>", p)]
    if len(paras) != 1 or "<a:br" in paras[0]:
        return anchor
    text = "".join(re.findall(r"<a:t>([^<]*)</a:t>", paras[0]))
    faces = set(re.findall(r'<a:(?:latin|ea) typeface="([^"]*)"', paras[0]))
    sizes = [int(s) for s in re.findall(r"<a:rPr\b[^>]*\bsz=\"(\d+)\"", paras[0])]
    if not text.strip() or not sizes or not faces or not faces <= set(_FIXED_PITCH):
        return anchor
    need = _em_width(text) * max(sizes) / 100 * EMU_PT          # 字幅 (EMU)
    bp = re.search(r"<a:bodyPr\b[^>]*?/?>", tb)
    if not bp:
        return anchor
    l = int((re.search(r'\blIns="(\d+)"', bp.group(0)) or [None, _DEFAULT_INSET])[1])
    r = int((re.search(r'\brIns="(\d+)"', bp.group(0)) or [None, _DEFAULT_INSET])[1])
    box = int(ext.group(1)) * _TIGHT      # twoCellAnchor の実幅は列幅の丸めで ext より狭く出る = 逃げを見る
    if need + l + r <= box:
        return anchor
    ins = max(0, int((box - need) / 2))                          # 左右均等
    new = bp.group(0)
    for k in ("lIns", "rIns"):
        new = re.sub(rf'\b{k}="\d+"', f'{k}="{ins}"', new) if f"{k}=" in new else new.replace("<a:bodyPr", f'<a:bodyPr {k}="{ins}"', 1)
    # 1 行の label は折り返さない (雛形の vertOverflow="clip" だと 2 行目は黙って消える = 「⑥-2」 が「⑥-」)
    new = re.sub(r'\bwrap="\w+"', 'wrap="none"', new) if "wrap=" in new else new.replace("<a:bodyPr", '<a:bodyPr wrap="none"', 1)
    return anchor.replace(bp.group(0), new, 1)


def source_drawings(src, drop=None) -> dict:
    """src の sheet 名 → 移す drawing の xml (form control と drop の図形を除いて 1 つ以上ある sheet だけ)。
    drop = {sheet 名: {図形の名前, ...}} (spec の render: drop_shape)。"""
    out = {}
    drop = {k.strip(): set(v) for k, v in (drop or {}).items() if v}
    with zipfile.ZipFile(src) as z:
        parts = sheet_parts(z)
        missing = set(drop) - {n.strip() for n in parts}
        if missing:
            raise GraftError(f"{Path(src).name}: drop_shape の sheet {sorted(missing)} が無い")
        for name, part in parts.items():
            drels = [(rid, tgt) for rid, typ, tgt, _m in _rels(z, part) if typ == REL_DRAWING]
            if not drels:
                continue
            if len(drels) > 1:
                raise GraftError(f"{Path(src).name} の sheet {name!r} に drawing が {len(drels)} 個")
            dpart = _resolve(part, drels[0][1])
            xml = z.read(dpart).decode("utf-8")
            xml, _n = _strip_alternate_content(xml)
            if drop.get(name.strip()):
                xml = _drop_named(xml, drop[name.strip()], f"{Path(src).name} の sheet {name!r}")
            if _anchor_count(xml) == 0:
                continue
            xml = _ANCHOR.sub(lambda m: _fit_single_line(m.group(0)), xml)
            refs = re.findall(r'\br:(?:id|embed|link|pict)="([^"]+)"', xml)
            if refs:
                # ② 画像・hyperlink 等を参照する drawing は part を連れて行く必要がある = 未対応 (黙って落とさない)
                raise GraftError(f"{Path(src).name} の sheet {name!r} の drawing が別 part を参照する "
                                 f"({sorted(set(refs))}) = 移植は未対応")
            out[name] = xml
    return out


def graft_drawings(src, dst, drop=None) -> list:
    """dst (openpyxl で save した xlsx) の各 sheet に、 src の同名 sheet の図形を移す。 移した sheet 名の list。

    drop = {sheet 名: {図形の名前}} は移さない (spec の render: drop_shape = 雛形の欠陥)。 src に図形が無ければ
    何もしない。 移した後は check-xlsx-integrity.py を通し、 落ちたら GraftError。"""
    drawings = source_drawings(src, drop=drop)
    if not drawings:
        return []
    dst = Path(dst)
    with zipfile.ZipFile(dst) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
        names = set(z.namelist())
        parts = sheet_parts(z)
        rels_of = {p: _rels(z, p) for p in parts.values()}
    data = {i.filename: b for i, b in items}
    order = [i.filename for i, _b in items]
    ct = data["[Content_Types].xml"].decode("utf-8")
    done, k = [], 1
    for name, part in parts.items():
        xml = drawings.get(name)
        if xml is None:
            continue
        sheet = data[part].decode("utf-8")
        if re.search(r"<(?:\w+:)?drawing\b", sheet) or any(t == REL_DRAWING for _i, t, _g, _m in rels_of[part]):
            raise GraftError(f"{dst.name} の sheet {name!r} に drawing が既にある (③ 重ねると rId が衝突する)")
        while f"xl/drawings/drawing{k}.xml" in names:
            k += 1
        dpart = f"xl/drawings/drawing{k}.xml"
        names.add(dpart)
        data[dpart] = xml.encode("utf-8")
        order.append(dpart)
        ct = ct.replace("</Types>", f'<Override PartName="/{dpart}" ContentType="{CT_DRAWING}"/></Types>', 1)
        # sheet の rels に drawing の関係を足す
        rpart = _rels_part(part)
        ids = {i for i, _t, _g, _m in rels_of[part]}
        rid = next(f"rIdFcDrawing{n}" for n in range(1, 1000) if f"rIdFcDrawing{n}" not in ids)
        rel = f'<Relationship Id="{rid}" Type="{REL_DRAWING}" Target="/{dpart}"/>'
        if rpart in data:
            data[rpart] = data[rpart].decode("utf-8").replace("</Relationships>", rel + "</Relationships>", 1).encode("utf-8")
        else:
            data[rpart] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                           f'<Relationships xmlns="{NS_PKG}">{rel}</Relationships>').encode("utf-8")
            order.append(rpart)
        # ④ <drawing> は xmlns:r を inline で宣言し、 CT_Worksheet の順で後に来る要素の手前に挿す
        tail_from = sheet.find("</sheetData>")
        if tail_from < 0:
            raise GraftError(f"{dst.name} の sheet {name!r} に </sheetData> が無い")
        m = re.compile(r"<(?:" + "|".join(_AFTER_DRAWING) + r")\b").search(sheet, tail_from)
        at = m.start() if m else sheet.rindex("</worksheet>")
        tag = f'<drawing xmlns:r="{NS_R}" r:id="{rid}"/>'
        data[part] = (sheet[:at] + tag + sheet[at:]).encode("utf-8")
        done.append(name)
        k += 1
    data["[Content_Types].xml"] = ct.encode("utf-8")
    tmp = dst.with_name(dst.name + ".graft.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, data[n])
    tmp.replace(dst)
    r = subprocess.run([sys.executable, str(INTEGRITY), str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        raise GraftError(f"図形を移した {dst.name} が check-xlsx-integrity を通らない:\n{(r.stdout + r.stderr).strip()[-1500:]}")
    return done
