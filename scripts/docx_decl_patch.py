"""docx_decl_patch.py — python-docx の Document.save() を auto-patch し XML 宣言を Word 形式(double-quote+CRLF)で書く（厳格 Word の「破損」回避、 save 時 source 修正・lazy import hook、 office-automation.md#docx-checkbox-content-control）
python-docx の Document.save() を自動 patch し、XML 宣言を Word ネイティブ形式で書く。

問題: python-docx (lxml) が save する OOXML パーツの宣言は
  <?xml version='1.0' encoding='UTF-8' standalone='yes'?>\\n   (single-quote + LF)
になる。厳格な macOS Word (実証 16.108) はこれを「破損しています。開いて修復しますか?」と
判定し開くたびにダイアログを出す (2026-06-05 ground-truth で確定)。Word 正規形
  <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\\r\\n (double-quote + CRLF)
に揃えると解消する。規約: claude-config/conventions/office-automation.md#docx-checkbox-content-control。

本 module を import すると lazy import hook が入り、**以後 python-docx (docx.document) が
import された時に Document.save が wrap され、保存のたびに宣言が自動正規化される**。
= source (save 時) で clean にするので race-free・取りこぼし不能・content 不変・idempotent。

machine-wide 自動適用: user site-packages に本 module + `docx_decl_patch.pth`
(`import docx_decl_patch` の 1 行) を置くと、全 python3 起動で auto-load される
(setup.sh が `site.getusersitepackages()` へ install)。lazy なので docx を使わない
script には overhead ほぼゼロ (= meta_path finder を 1 つ挿すだけ)。

standalone の path-based 正規化は normalize-docx-decl.py (= 既存 docx を後追い修正する CLI)。
本 module は save 時 source patch、 CLI は後追い、 check-docx-integrity.py は検出。3 者は
SINGLE/WORD 宣言定数を共有概念とする (= Word が書く literal なので drift しない)。
"""
import sys
import io
import os
import zipfile

_SINGLE = b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
_WORD = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def normalize_bytes(data):
    """docx の zip bytes を受け、single-quote 宣言を Word 形式に直した bytes を返す。
    変更不要なら同一 object をそのまま返す (= idempotent 判定用)。"""
    try:
        zin = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return data
    items = {n: zin.read(n) for n in zin.namelist()}
    changed = False
    for n, d in items.items():
        if (n.endswith(".xml") or n.endswith(".rels")) and d[: len(_SINGLE)] == _SINGLE:
            rest = d[len(_SINGLE):]
            if rest[:1] == b"\n":
                rest = b"\r\n" + rest[1:]
            items[n] = _WORD + rest
            changed = True
    if not changed:
        return data
    out = io.BytesIO()
    zo = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for n, d in items.items():
        zo.writestr(n, d)
    zo.close()
    return out.getvalue()


def _normalize_path(path):
    with open(path, "rb") as f:
        data = f.read()
    new = normalize_bytes(data)
    if new is data:
        return
    tmp = "%s.decltmp" % path
    with open(tmp, "wb") as f:
        f.write(new)
    os.replace(tmp, path)


def _patch(docx_document_module):
    Document = docx_document_module.Document
    if getattr(Document.save, "_word_clean", False):
        return
    _orig = Document.save

    def save(self, path_or_stream):
        _orig(self, path_or_stream)
        try:
            if isinstance(path_or_stream, (str, os.PathLike)):
                _normalize_path(os.fspath(path_or_stream))
            elif hasattr(path_or_stream, "getvalue") and hasattr(path_or_stream, "seek"):
                data = path_or_stream.getvalue()
                new = normalize_bytes(data)
                if new is not data:
                    path_or_stream.seek(0)
                    path_or_stream.truncate()
                    path_or_stream.write(new)
        except Exception:
            pass  # save を絶対に壊さない

    save._word_clean = True
    Document.save = save


# --- lazy install: docx.document が import された時にだけ patch (overhead 回避) ---
try:
    import importlib.abc
    import importlib.util

    class _WrapLoader(importlib.abc.Loader):
        def __init__(self, orig):
            self._orig = orig

        def create_module(self, spec):
            return self._orig.create_module(spec)

        def exec_module(self, module):
            self._orig.exec_module(module)
            try:
                _patch(module)
            except Exception:
                pass

    class _DocxFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name != "docx.document":
                return None
            try:
                sys.meta_path.remove(self)
            except ValueError:
                pass
            try:
                spec = importlib.util.find_spec(name)
            finally:
                if self not in sys.meta_path:
                    sys.meta_path.insert(0, self)
            if spec is None or spec.loader is None:
                return None
            spec.loader = _WrapLoader(spec.loader)
            return spec

    if "docx.document" in sys.modules:
        _patch(sys.modules["docx.document"])
    else:
        sys.meta_path.insert(0, _DocxFinder())
except Exception:
    pass  # patch 機構自体の失敗で python 起動を壊さない
