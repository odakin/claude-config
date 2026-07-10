#!/usr/bin/env python3
"""check-docx-integrity.py — docx の Word「破損」判定源を Word 不要・決定論で検出（single-quote 宣言 / checkbox 状態↔グリフ / bookmark / table grid / dangling r:id 等、 office-automation.md#docx-checkbox-content-control）
docx 整合チェッカー — Word の「破損しています / 開いて修復しますか?」判定を出荷前に機械検出。

python-docx や zipfile+document.xml 直編集で Word 製テンプレを fill すると、zip も
XML も well-formed なのに Word だけが「破損」と判定し、開くたびに修復ダイアログを出す
ことがある。原因はスキーマ / コンテンツモデル層の不整合で、`xmllint --noout`(well-formed
チェック)では捕まらない。本 script はその代表クラスを Word 不要・決定論的に検出する。

検出クラス:
  1. コンテンツコントロール checkbox(`<w:sdt><w14:checkbox>`)の状態↔表示グリフ不整合
     (例: `<w14:checked w14:val="0"/>`(未チェック) なのに表示グリフが ☑)
     ← グリフ文字だけを ☐→☑ 置換しコントロール状態を更新しない時に発生。office-automation.md#docx-checkbox-content-control
  2. bookmarkStart / bookmarkEnd の id 不均衡
  3. テーブル gridCol と各行の論理セル数(gridSpan 考慮)の不一致
  4. 空 run(`<w:r></w:r>`) / 空 hyperlink
  5. 全パーツ(.xml/.rels)の XML well-formedness
  6. document.xml の r:id 参照と document.xml.rels 定義の dangling
  7. 関係 Target の実在(Internal のみ)
  8. 空セル <w:tc>(段落 <w:p> なし) — OOXML 違反で Word が「破損」判定、修復で <w:p> を補う(2026-06-06 RCA)

使い方:
  python3 check-docx-integrity.py FILE.docx [FILE2.docx ...]
  終了コード: 0=全 clean, 1=1 件以上に問題, 2=実行エラー

注意: Word の「破損」判定を 100% 再現するものではない(Word の内部ヒューリスティックは
非公開)。高頻度・高信号のクラスのみを潰す gate。最終確認は実機で 1 度開く。
"""
import sys
import re
import zipfile
import posixpath
from xml.dom.minidom import parseString
from xml.parsers.expat import ExpatError

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"


def check(path):
    issues = []
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return [f"zip として開けない: {e}"]
    if z.testzip() is not None:
        issues.append("zip CRC 不良(ファイル破損)")
    parts = {n: z.read(n) for n in z.namelist()}

    for req in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
        if req not in parts:
            issues.append(f"必須パーツ欠落: {req}")
    doc = parts.get("word/document.xml", b"").decode("utf-8", "replace")

    # 0. XML 宣言が python-docx の single-quote 形式か
    #    (厳格 macOS Word〔実証 16.108〕が「破損/開いて修復」判定する確定源、2026-06-05 ground-truth)
    for n, data in parts.items():
        if (n.endswith(".xml") or n.endswith(".rels")) and data[:19] == b"<?xml version='1.0'":
            issues.append(
                "XML 宣言が single-quote (python-docx/lxml 形式) — 厳格 macOS Word が"
                "「破損/開いて修復」判定する確定源。normalize-docx-decl.py で Word 形式"
                "(double-quote + CRLF) に正規化せよ"
            )
            break

    # 5. 全パーツ well-formed
    for n, data in parts.items():
        if n.endswith(".xml") or n.endswith(".rels"):
            try:
                parseString(data)
            except ExpatError as e:
                issues.append(f"XML not well-formed: {n} ({e})")

    # 1. checkbox 状態↔グリフ
    for i, s in enumerate(re.findall(r"<w:sdt>.*?</w:sdt>", doc, re.S), 1):
        if "<w14:checkbox>" not in s:
            continue
        mc = re.search(r'<w14:checked w14:val="(\d)"', s)
        glyph = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", s))
        if mc:
            st = mc.group(1)
            if st == "0" and "☑" in glyph:
                issues.append(f"checkbox#{i}: 状態=未チェック(0) なのに表示グリフが ☑ (Word 破損判定源)")
            elif st == "1" and "☐" in glyph:
                issues.append(f"checkbox#{i}: 状態=チェック(1) なのに表示グリフが ☐ (Word 破損判定源)")

    # 2. bookmark 均衡
    bs = set(re.findall(r'<w:bookmarkStart[^>]*w:id="(\d+)"', doc))
    be = set(re.findall(r'<w:bookmarkEnd[^>]*w:id="(\d+)"', doc))
    if bs - be:
        issues.append(f"bookmarkEnd 欠落 id: {sorted(bs - be)}")
    if be - bs:
        issues.append(f"bookmarkStart 欠落 id: {sorted(be - bs)}")

    # 3. テーブル grid 整合
    for i, tbl in enumerate(re.findall(r"<w:tbl>.*?</w:tbl>", doc, re.S), 1):
        gridcols = len(re.findall(r"<w:gridCol\b", tbl))
        for ri, row in enumerate(re.findall(r"<w:tr\b.*?</w:tr>", tbl, re.S), 1):
            cells = len(re.findall(r"<w:tc>", row))
            spans = re.findall(r'<w:gridSpan w:val="(\d+)"', row)
            logical = cells - len(spans) + sum(int(x) for x in spans)
            if gridcols and logical != gridcols:
                issues.append(f"table#{i} row#{ri}: 論理列数 {logical} ≠ gridCol {gridcols}")

    # 4. 空 run / 空 hyperlink
    if re.search(r"<w:r\b[^>]*></w:r>", doc):
        issues.append("空の <w:r></w:r> が存在")
    if re.search(r"<w:hyperlink\b[^>]*></w:hyperlink>", doc):
        issues.append("空の <w:hyperlink></w:hyperlink> が存在")

    # 8. 空セル <w:tc>(block 要素 <w:p>/<w:tbl> なし) — OOXML 違反で macOS Word が「破損」判定
    #    (2026-06-06 RCA: python-docx 編集で段落の無い表セルが残ると、well-formed / grid 整合 /
    #     宣言 すべて通過するのに Word は破損ダイアログを出し、開いて修復で各空セルに <w:p> を補う。
    #     fix = 各空セルに <w:p/> を append。office-automation.md#docx-empty-cell)
    #    検出: <w:tc> の直後が(tcPr のみを挟んで)</w:tc> = block 不在。nested table 持ちは <w:tbl/<w:p で除外。
    empty_tc = re.findall(r"<w:tc>\s*(?:<w:tcPr(?:\s*/>|>.*?</w:tcPr>)\s*)?</w:tc>", doc, re.S)
    if empty_tc:
        issues.append(
            f"空セル <w:tc>(段落なし) が {len(empty_tc)} 個 — OOXML 違反で Word 破損判定源。"
            "各空セルに <w:p/> を append せよ (office-automation.md#docx-empty-cell)"
        )

    # 6. dangling r:id
    refs = set(re.findall(r"rId\d+", " ".join(re.findall(r'r:(?:id|embed|link)="[^"]+"', doc))))
    rels = parts.get("word/_rels/document.xml.rels", b"").decode("utf-8", "replace")
    defs = set(re.findall(r'Id="(rId\d+)"', rels))
    if refs - defs:
        issues.append(f"document.xml の dangling r:id: {sorted(refs - defs)}")

    # 7. Target 実在(Internal)
    for relname in [n for n in parts if n.endswith(".rels")]:
        base = posixpath.dirname(posixpath.dirname(relname))
        rels_xml = parts[relname].decode("utf-8", "replace")
        for m in re.finditer(r"<Relationship\b[^>]*>", rels_xml):
            tag = m.group(0)
            if 'TargetMode="External"' in tag:
                continue
            tm = re.search(r'Target="([^"]+)"', tag)
            if not tm:
                continue
            tgt = tm.group(1)
            full = (posixpath.normpath(posixpath.join(base, tgt))
                    if not tgt.startswith("/") else tgt.lstrip("/"))
            if full not in parts:
                issues.append(f"{relname}: Target 不在 {tgt}")

    return issues


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    rc = 0
    for path in argv[1:]:
        try:
            issues = check(path)
        except Exception as e:
            print(f"⚠️  {path}: 実行エラー {e}")
            rc = 2
            continue
        if issues:
            rc = max(rc, 1)
            print(f"❌ {path}  ({len(issues)} 件)")
            for it in issues:
                print(f"    - {it}")
        else:
            print(f"✅ {path}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
