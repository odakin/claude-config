#!/usr/bin/env python3
"""seal_artifact.py — 画像の押印 (ハンコ画像) が入った成果物に、作る時に印を付け、出口で見つける。

なぜ要るか (規約 = conventions/office-automation.md#seal-artifact-marker):
    画像印影を埋めてよいのが「紙で出す成果物だけ」 という運用は、散文の規則だけだと守られない。
    印影が入っていることは「押す手間が済んでいる = このまま送れる」 と、禁止の条件そのものが
    準備完了の印として読まれる (実測)。 禁止の条件になる性質は**作る時に file へ書き込み**、
    file が相手の手に file のまま渡る**出口** (メール添付・共有・upload) で機械が見る。

判定の信号 (強い順):
    marker      PDF の Keywords に MARKER がある。 overlay-seal-pdf.py が書き、
                pdf-print-preflight.py --rasterize が raster 版へ引き継ぐ。
    seal-image  PDF の画像の透明度 (SMask)、 Office file (docx/xlsx/pptx) の media 画像の alpha、
                または添付された PNG 自体の alpha が、呼び出し側が渡す印影画像 (pool) の alpha と
                完全一致する (= 印影画像を直接貼った出力)。 乗算合成や raster 化で alpha が消えた
                出力には効かない (= marker と name+ink で拾う)。
    name+ink    file 名が呼び出し側の token に当たり、かつ頁に印影色のインクがある。
    name-only   file 名だけが当たる (弱い。 呼び出し側は警告に留める)。
    unreadable  暗号化・破損で中身を見られない (弱い)。

呼び出し側が持つもの: pool の場所、 file 名の token、 どの信号で止めるか、 宛先の扱い。
本 module は判定だけを持つ (送信・表示・方針は持たない)。

    sys.path.insert(0, str(<claude-config>/"scripts"/"lib"))
    from seal_artifact import MARKER, mark_doc, copy_marker, has_marker, load_pool, scan, strength

直接実行 = selftest。
"""
from __future__ import annotations

import hashlib
import os
import re
import zipfile

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - 呼び出し側で SKIP / エラー表示
    fitz = None

MARKER = "paper-only:seal-image"
STRONG = ("marker", "seal-image", "name+ink")
WEAK = ("name-only", "unreadable")
_META_KEYS = ("title", "author", "subject", "keywords", "creator", "producer",
              "creationDate", "modDate", "trapped")
_OFFICE_EXT = (".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm")
_MEDIA_RE = re.compile(r"^(word|xl|ppt)/media/[^/]+\.png$", re.I)


def _need_fitz():
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required")


# ---------------------------------------------------------------- marker (作る側)

def mark_doc(doc) -> None:
    """開いている fitz.Document の Keywords に MARKER を足す (既存の metadata は保つ)。 保存は呼び出し側。"""
    md = doc.metadata or {}
    kw = md.get("keywords") or ""
    if MARKER in kw:
        return
    new = {k: md[k] for k in _META_KEYS if md.get(k)}
    new["keywords"] = f"{kw}; {MARKER}" if kw else MARKER
    doc.set_metadata(new)


def copy_marker(src_doc, dst_doc) -> bool:
    """src に MARKER があれば dst にも付ける (raster 化・頁抽出で metadata が落ちる経路用)。 付けたら True。"""
    if MARKER in ((src_doc.metadata or {}).get("keywords") or ""):
        mark_doc(dst_doc)
        return True
    return False


def has_marker(path_or_doc) -> bool:
    _need_fitz()
    if isinstance(path_or_doc, (str, os.PathLike)):
        with fitz.open(path_or_doc) as d:
            return MARKER in ((d.metadata or {}).get("keywords") or "")
    return MARKER in ((path_or_doc.metadata or {}).get("keywords") or "")


# ---------------------------------------------------------------- pool (印影画像の指紋)

def _alpha_key(pm, mask: bool = False):
    """Pixmap の alpha 面の指紋 (w, h, sha256)。 mask=True = pm 自体が SMask (単一の濃度面)。 alpha が無ければ None。"""
    if mask and pm.n == 1 and not pm.alpha:
        plane = pm.samples
    elif pm.alpha:
        plane = pm.samples[pm.n - 1::pm.n]
    else:
        return None
    return (pm.width, pm.height, hashlib.sha256(plane).hexdigest())


def load_pool(paths) -> set:
    """印影画像 (PNG) の alpha 指紋の集合。 paths は file か dir (dir は直下の *.png)。 無い path は飛ばす。"""
    _need_fitz()
    keys = set()
    for p in paths or []:
        p = os.path.expanduser(str(p))
        files = ([os.path.join(p, f) for f in sorted(os.listdir(p)) if f.lower().endswith(".png")]
                 if os.path.isdir(p) else [p] if os.path.isfile(p) else [])
        for f in files:
            try:
                k = _alpha_key(fitz.Pixmap(f))
            except Exception:  # noqa: BLE001 - 壊れた pool 画像は判定に使わない
                continue
            if k:
                keys.add(k)
    return keys


# ---------------------------------------------------------------- 検出 (出口側)

def ink_pixels(doc, dpi: int = 36) -> int:
    """頁ごとに印影色 (赤系) の画素を数え、最大の頁の値を返す。 36 dpi で直径 9.5 mm の印 1 個 ≈ 40–80。"""
    best = 0
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
        s = pix.samples
        n = 0
        for i in range(0, len(s), 3):
            r, g, b = s[i], s[i + 1], s[i + 2]
            if r > 140 and r - g > 60 and r - b > 60:
                n += 1
        best = max(best, n)
    return best


def _pdf_seal_image(doc, pool) -> str | None:
    for page in doc:
        for im in page.get_images(full=True):
            smask = im[1]
            if not smask:
                continue
            try:
                k = _alpha_key(fitz.Pixmap(doc, smask), mask=True)
            except Exception:  # noqa: BLE001
                continue
            if k in pool:
                return f"page {page.number + 1} の画像 {im[2]}x{im[3]} の透明度が印影画像と一致"
    return None


def _office_seal_image(path, pool) -> str | None:
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not _MEDIA_RE.match(name):
                continue
            try:
                k = _alpha_key(fitz.Pixmap(z.read(name)))
            except Exception:  # noqa: BLE001
                continue
            if k in pool:
                return f"{name} の透明度が印影画像と一致"
    return None


def scan(path, pool=None, name_token=None, ink_threshold: int = 15) -> list:
    """1 file の信号を [{"signal": ..., "detail": ...}] で返す (空 = 印影の兆候なし)。

    pool = load_pool() の結果 / name_token = file 名に掛ける正規表現 (文字列か compile 済み) /
    ink_threshold = name+ink とみなす印影色の画素数 (36 dpi)。"""
    _need_fitz()
    out = []
    base = os.path.basename(str(path))
    tok = re.compile(name_token) if isinstance(name_token, str) and name_token else name_token
    name_hit = bool(tok and tok.search(base))
    low = base.lower()
    pool = pool or set()
    try:
        if low.endswith(".pdf"):
            with fitz.open(path) as d:
                if d.needs_pass or d.is_encrypted:
                    return [{"signal": "unreadable", "detail": "暗号化された PDF"}]
                if MARKER in ((d.metadata or {}).get("keywords") or ""):
                    out.append({"signal": "marker", "detail": f"Keywords に {MARKER}"})
                hit = _pdf_seal_image(d, pool) if pool else None
                if hit:
                    out.append({"signal": "seal-image", "detail": hit})
                if name_hit:
                    ink = ink_pixels(d)
                    if ink >= ink_threshold:
                        out.append({"signal": "name+ink", "detail": f"file 名が token に一致 + 印影色の画素 {ink}"})
        elif low.endswith(_OFFICE_EXT):
            hit = _office_seal_image(path, pool) if pool else None
            if hit:
                out.append({"signal": "seal-image", "detail": hit})
        elif low.endswith(".png") and pool:
            k = _alpha_key(fitz.Pixmap(str(path)))
            if k in pool:
                out.append({"signal": "seal-image", "detail": "印影画像そのもの"})
    except (zipfile.BadZipFile, RuntimeError, ValueError) as e:
        return [{"signal": "unreadable", "detail": f"{type(e).__name__}: {e}"}]
    if name_hit and not any(s["signal"] in STRONG for s in out):
        out.append({"signal": "name-only", "detail": "file 名だけが token に一致 (中身に印影の兆候なし)"})
    return out


def strength(signals) -> str | None:
    """'strong' / 'weak' / None。"""
    kinds = {s["signal"] for s in signals}
    if kinds & set(STRONG):
        return "strong"
    if kinds & set(WEAK):
        return "weak"
    return None


# ---------------------------------------------------------------- selftest

def _selftest() -> int:
    import tempfile
    if fitz is None:
        print("SKIP: seal_artifact selftest (PyMuPDF 未導入)")
        return 0
    d = tempfile.mkdtemp()
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'✅' if cond else '❌'} {label}")
        ok = ok and bool(cond)

    def seal_png(path, radius):
        # 合成の印影: 中心から radius 以内だけ不透明な赤、外は透明 (alpha 面が radius ごとに違う)
        w = h = 40
        buf = bytearray()
        for y in range(h):
            for x in range(w):
                inside = (x - 20) ** 2 + (y - 20) ** 2 <= radius ** 2
                buf += bytes((220, 40, 30, 255 if inside else 0))
        fitz.Pixmap(fitz.csRGB, w, h, bytes(buf), True).save(path)
        return path

    seal = seal_png(os.path.join(d, "seal.png"), 15)
    other = seal_png(os.path.join(d, "other.png"), 9)
    pool = load_pool([d + "/seal.png"])
    check("pool: alpha 指紋を 1 個読む", len(pool) == 1)
    check("pool: 無い path は飛ばす", load_pool([os.path.join(d, "none.png")]) == set())

    a = os.path.join(d, "a.pdf")
    doc = fitz.open(); pg = doc.new_page(); pg.insert_image(fitz.Rect(100, 100, 140, 140), filename=seal); doc.save(a)
    check("seal-image: 印影 PNG を直接貼った PDF", strength(scan(a, pool)) == "strong")
    b = os.path.join(d, "b.pdf")
    doc = fitz.open(); pg = doc.new_page(); pg.insert_image(fitz.Rect(100, 100, 140, 140), filename=other); doc.save(b)
    check("seal-image: 別の画像は当たらない", scan(b, pool) == [])

    c = os.path.join(d, "c.pdf")
    doc = fitz.open(); doc.new_page(); doc.set_metadata({"keywords": "既存の語"}); mark_doc(doc); doc.save(c)
    with fitz.open(c) as cd:
        kw = cd.metadata.get("keywords")
    check("marker: 既存の Keywords を保って足す", "既存の語" in kw and MARKER in kw)
    check("marker: has_marker / scan が strong", has_marker(c) and strength(scan(c)) == "strong")
    src = fitz.open(c); dst = fitz.open(); dst.new_page()
    check("copy_marker: 引き継ぐ", copy_marker(src, dst) and has_marker(dst))
    plain = fitz.open(); plain.new_page(); dst2 = fitz.open(); dst2.new_page()
    check("copy_marker: 印が無ければ何もしない", not copy_marker(plain, dst2) and not has_marker(dst2))

    red = os.path.join(d, "x_印刷提出用.pdf")
    doc = fitz.open(); pg = doc.new_page()
    pg.draw_circle(fitz.Point(200, 200), 14, color=(0.85, 0.2, 0.15), fill=(0.85, 0.2, 0.15)); doc.save(red)
    tok = r"印刷提出用|押印済"
    check("name+ink: token + 印影色", [s["signal"] for s in scan(red, pool, tok)] == ["name+ink"])
    blank = os.path.join(d, "y_印刷提出用.pdf")
    doc = fitz.open(); doc.new_page(); doc.save(blank)
    check("name-only: token だけ (インクなし) は weak", strength(scan(blank, pool, tok)) == "weak")
    red_noname = os.path.join(d, "poster.pdf")
    doc = fitz.open(); pg = doc.new_page()
    pg.draw_circle(fitz.Point(200, 200), 14, color=(0.85, 0.2, 0.15), fill=(0.85, 0.2, 0.15)); doc.save(red_noname)
    check("赤いだけ (token なし) は当たらない", scan(red_noname, pool, tok) == [])

    dx = os.path.join(d, "form.docx")
    with zipfile.ZipFile(dx, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.write(seal, "word/media/image1.png")
    check("seal-image: docx の media に印影画像", strength(scan(dx, pool)) == "strong")
    check("seal-image: PNG 自体を添付", strength(scan(seal, pool)) == "strong")
    bad = os.path.join(d, "broken.docx")
    with open(bad, "wb") as fh:
        fh.write(b"not a zip")
    check("unreadable: 壊れた Office file は weak", strength(scan(bad, pool)) == "weak")

    print(f"seal_artifact selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
