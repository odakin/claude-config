#!/usr/bin/env python3
"""check-xlsx-integrity.py — xlsx の Excel「破損」判定源を Excel 不要・決定論で検出（XML well-formed〔unbound prefix〕/ rels 両方向参照整合 / rId 重複 / Content_Types coverage。 zip 直編集 xlsx の納品前 gate、 office-automation.md#openpyxl-destroys-drawings）
check-xlsx-integrity.py — xlsx の Excel「破損」判定源を Excel 不要・決定論で検出する出荷前 gate

Usage:
    python3 check-xlsx-integrity.py FILE.xlsx [FILE2.xlsx ...]

zip 直編集 (= drawing 注入・cell 値置換等) した xlsx を納品する前に必ず通す。
`check-docx-integrity.py` の xlsx 版 sibling (= 同じ思想: Word/Excel の「開いて修復」
ダイアログは開くまで分からない → 決定論検査で事前に落とす)。

検出する破損源 (= いずれも実害 RCA 由来):
  1. zip 自体の破損 (= testzip)
  2. 全 .xml / .rels part の XML well-formedness — **unbound namespace prefix を含む**
     (= 2026-06-10 RCA: worksheet root に xmlns:r が無い file に <drawing r:id> を素で
      挿すと invalid XML、 Excel が「壊れている」 ダイアログ。 生成 tool 産 xlsx は
      root が xmlns のみのことがある)
  3. relationship の参照整合 (両方向):
     a. 各 .rels の Target (非 External) が実在 part を指す (= dangling rel)
     b. 各 part 内の r: 属性 (r:id / r:embed / r:link) が自分の .rels に存在する
        (= 未定義 rId 参照、 rId 重複・衝突事故の検出面)
  4. [Content_Types].xml が全 part を cover (= Override or Default 拡張子)

exit: 0 = pass / 1 = FAIL あり / 2 = 実行不能 (file 不在等)

⚠️ 必要条件であって十分条件ではない — schema/コンテンツモデル層の不整合は検出できない。
最終 ground truth は実機 Excel open (= docx と同じ教訓)。 AppleScript の open が
"opened" を返しても修復ダイアログの有無は戻り値に現れない点に注意。

規約 home: conventions/office-automation.md #openpyxl-destroys-drawings (= 注入 4 条件 + 本 gate)
"""

from __future__ import annotations

import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def rels_path_for(part: str) -> str:
    d, b = posixpath.split(part)
    return posixpath.join(d, "_rels", b + ".rels")


def resolve_target(part: str, target: str) -> str:
    """rels の Target を zip 内 part 名に正規化 (= 先頭 / は package root、 相対は part の dir 起点)。"""
    if target.startswith("/"):
        return target.lstrip("/")
    base = posixpath.dirname(part)
    return posixpath.normpath(posixpath.join(base, target))


def check_file(path: str) -> list[str]:
    fails: list[str] = []
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        return [f"zip として開けない: {e}"]

    # 1. zip 健全性
    bad = z.testzip()
    if bad:
        fails.append(f"zip entry 破損: {bad}")

    names = set(z.namelist())
    parsed: dict[str, ET.Element] = {}

    # 2. XML well-formedness (.vml は legacy 形式なので warn 扱いにせず skip しない: parse は試みる)
    for n in sorted(names):
        if n.endswith((".xml", ".rels")):
            try:
                parsed[n] = ET.fromstring(z.read(n))
            except ET.ParseError as e:
                fails.append(f"XML 不正 {n}: {e} (= unbound prefix なら r: 属性の xmlns 宣言漏れを疑う)")

    # 3a. rels Target → 実在 part
    rels_ids: dict[str, set[str]] = {}  # owner part -> rId set
    for n, root in parsed.items():
        if not n.endswith(".rels"):
            continue
        owner_dir = posixpath.dirname(posixpath.dirname(n))  # xl/worksheets/_rels/s.xml.rels -> xl/worksheets
        owner = posixpath.join(owner_dir, posixpath.basename(n)[:-5])  # sheet1.xml
        ids = set()
        for rel in root.iter(REL_NS + "Relationship"):
            rid = rel.get("Id", "")
            ids.add(rid)
            if rel.get("TargetMode") == "External":
                continue
            tgt = resolve_target(owner, rel.get("Target", ""))
            if tgt not in names:
                fails.append(f"dangling rel {n}: Id={rid} Target={rel.get('Target')} (= {tgt} が zip に無い)")
        if len(ids) != len(root.findall(REL_NS + "Relationship")):
            fails.append(f"rId 重複 {n} (= Excel が破損判定する既知事故)")
        rels_ids[owner] = ids

    # 3b. part 内の r: 属性 → 自分の rels に存在
    for n, root in parsed.items():
        if n.endswith(".rels"):
            continue
        used = set()
        for el in root.iter():
            for k, v in el.attrib.items():
                if k.startswith(R_NS):
                    used.add(v)
        if not used:
            continue
        have = rels_ids.get(n, set())
        missing = used - have
        if missing:
            fails.append(f"未定義 rId 参照 {n}: {sorted(missing)} (= {rels_path_for(n)} に無い)")

    # 4. [Content_Types].xml coverage
    ct = parsed.get("[Content_Types].xml")
    if ct is None:
        fails.append("[Content_Types].xml が無い / parse 不能")
    else:
        defaults = {d.get("Extension", "").lower() for d in ct.iter(CT_NS + "Default")}
        overrides = {o.get("PartName", "") for o in ct.iter(CT_NS + "Override")}
        for n in sorted(names):
            if n.endswith("/"):
                continue
            ext = n.rsplit(".", 1)[-1].lower() if "." in n else ""
            if ("/" + n) not in overrides and ext not in defaults:
                fails.append(f"[Content_Types] 未登録 part: {n} (= Override も Default 拡張子も無い)")
    return fails


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__.strip().splitlines()[0])
        print("usage: check-xlsx-integrity.py FILE.xlsx [...]")
        return 2
    any_fail = False
    for path in args:
        fails = check_file(path)
        if fails:
            any_fail = True
            print(f"❌ {path} — {len(fails)} 件:")
            for f in fails:
                print(f"   ✗ {f}")
        else:
            print(f"✓ {path} — 決定論検査 pass (最終 ground truth は実機 open)")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
