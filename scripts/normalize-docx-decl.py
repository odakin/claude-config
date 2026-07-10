#!/usr/bin/env python3
"""normalize-docx-decl.py — 既存 docx の XML 宣言を Word 形式へ後追い正規化する CLI（docx_decl_patch の path-based 版、 office-automation.md#docx-checkbox-content-control）
docx の XML 宣言を Word ネイティブ形式に正規化 — python-docx 出力の Word「破損」回避。

python-docx (lxml) が再シリアライズした OOXML パーツの XML 宣言は
  <?xml version='1.0' encoding='UTF-8' standalone='yes'?>\\n   (single-quote + LF)
になる。一方 Microsoft Word が書く正規形は
  <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\\r\\n (double-quote + CRLF)。
**ある macOS Word (実証: 16.108) は前者を「このファイルは破損しています。開いて修復しま
すか?」と判定し、開くたびにダイアログを出す** (= 2026-06-05 ground-truth で確定。zip も XML
も well-formed・全 deterministic check pass でも Word だけが flag)。宣言を Word 形式に
揃えると解消する。詳細は claude-config/conventions/office-automation.md#docx-checkbox-content-control。

⚠️ この症状は普遍ではない (python-docx は世界中で問題なく使われている) が、厳格な Word
個体で再現する。正規化は常に valid な OOXML なので副作用なく適用してよい (= idempotent)。

使い方:
  python3 normalize-docx-decl.py FILE.docx [FILE2.docx ...]   # in-place 正規化
  終了コード: 0=成功(変更有無問わず), 2=エラー
内容 (本文・スタイル等) は一切変えず、各パーツの宣言行のみ書き換える。
"""
import sys
import zipfile

SINGLE = b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
WORD = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def normalize(path):
    """path の docx を in-place 正規化。書き換えたパーツ数を返す。"""
    zin = zipfile.ZipFile(path)
    items = {n: zin.read(n) for n in zin.namelist()}
    zin.close()
    fixed = 0
    for n, data in list(items.items()):
        if not (n.endswith(".xml") or n.endswith(".rels")):
            continue
        if data[: len(SINGLE)] == SINGLE:
            rest = data[len(SINGLE):]
            if rest[:1] == b"\n":          # LF → CRLF (Word は宣言直後 CRLF)
                rest = b"\r\n" + rest[1:]
            items[n] = WORD + rest
            fixed += 1
    if fixed:
        tmp = path + ".normtmp"
        zout = zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED)
        for n, data in items.items():
            zout.writestr(n, data)
        zout.close()
        import os
        os.replace(tmp, path)
    return fixed


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    rc = 0
    for path in argv[1:]:
        try:
            n = normalize(path)
            print(f"{'🔧' if n else '✅'} {path}  (宣言正規化 {n} パーツ)")
        except Exception as e:
            print(f"⚠️  {path}: {e}")
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
