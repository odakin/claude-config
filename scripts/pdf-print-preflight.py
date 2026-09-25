#!/usr/bin/env python3
"""印刷直前の PDF preflight — 「画面で見えた」 を印刷の保証にしない機械 gate (office-automation.md#print-preflight)。

検査 (1 つでも 🔴 なら exit 1):
  1. page 数     : --template <雛形.pdf> または --expect-pages N と一致するか (= 様式が 2 頁にはみ出す事故)。
                   ⚠️ 一致は「はみ出していない」 しか言わない。 どの頁を刷るかは 5.
  2. font        : PyMuPDF が描いた文字 (組み込み helv/tiro/japan/china-* 等 = 非埋め込み、 および
                   PyMuPDF 埋め込みの Type0/CFF) が残っていないか (= printer 側で文字化け、 OTF 埋め込みでも化けた実績)
  3. 色          : 画像 (認印等) が載っている PDF を raster 化するなら RGB で、 の注意 (情報)
  4. 用紙        : 頁の寸法と名前 (A4 等) を表示 (情報)。 ⚠️ lp の media 指定は本体の用紙設定を上書きしない
                   (実測) ので、 刷る前に本体の用紙サイズとトレイの紙を確認する。 --printer を付けると本体に IPP で聞き、
                   本体が報告するトレイの用紙が PDF の寸法と合わなければ 🔴 (lib/printer_media.py、 答えが無ければ ⚪ で通す)
  5. 頁の役割    : 全頁が「窓口に出す頁」 か (office-automation.md#print-submission-pages-only、 lib/print_pages.py)。
                   file に宣言 (作った道具が書く) があればそれを読み、 提出でない頁 (説明書き・記載例・控え・マスタ・白紙)
                   が入っていれば 🔴。 宣言が無ければ見出しから推定し、 記載例・控え・注意事項・白紙に見える頁と、
                   宣言の無い 2 頁以上の file は 🔴 (= どの頁を出すかを --pages で決めてから刷る)。 頁の一覧を毎回出す
  ※ 2. は PyMuPDF 製に限らない: headless browser の print-to-PDF が書く Type3 font も非埋め込み扱いで FAIL になる (実測)

オプション:
  --rasterize OUT.pdf [--dpi 600]  : 検査後に RGB raster 版を書き出す (font 問題を原理的に消す印刷用)
  --extract OUT.pdf                : 頁を選んだ vector 版を書き出す (Word / Excel が直接吐いた PDF 等、 raster が要らない時)
  --pages SPEC                     : OUT に入れる頁 (all / 1-2,4 / changed)。 入れた頁を「提出」 と宣言して OUT に書く。
                                     ⚠️ lp -o page-ranges は無視される queue がある (実測) = 刷る頁だけの file を作る
  --include-flagged REASON         : 説明書き・記載例等に見える頁を、 理由つきで OUT に残す (理由は宣言に記録)
  --changed-from OLD.pdf           : 前に刷った版と頁ごとに比べ、 変わった頁を出す (--pages changed = その頁だけ刷り直す)
  --printer [QUEUE]                : 本体にトレイの用紙を IPP で聞いて PDF と比べる (QUEUE 省略 = 既定の送信先)。
                                     queue の既定が両面ならそれも出す (本体の sides-default とは別物 = 実測で食い違った)
  --hook                           : PreToolUse(Bash) の hook として動く (入力 JSON を stdin から。 `lp`/`lpr` に渡す PDF を
                                     検査し、 FAIL なら exit 2 + 理由を stderr = 実行前に止まり理由が model に届く)。
                                     見るのは lp / lpr の引数の PDF だけ (同じ command の別の段 = 作る元の PDF は見ない)。
                                     同じ command で代入した変数と cd は追う。 追えない引数 ($f 等) があれば command 中の
                                     全 .pdf を見る (取りこぼさない側)。 PDF が通ったら -d の queue の本体に用紙を聞き、
                                     合わなければ止める (PRINT_PREFLIGHT_PRINTER=0 で聞かない)。
                                     配線例 = hook の command を `python3 <この script> --hook` に (個人層の shim でもよい)
  --selftest                       : 合成 PDF で FAIL/PASS の両方を確認

使い方:
  python3 pdf-print-preflight.py form_print.pdf --template blank.pdf
  python3 pdf-print-preflight.py form.pdf --rasterize form_print.pdf --pages 1-2      # 窓口に出す 2 頁だけ刷る
  python3 pdf-print-preflight.py new.pdf --changed-from printed.pdf --rasterize re.pdf --pages changed
  python3 pdf-print-preflight.py print.pdf --printer Office_Printer                    # 本体のトレイの用紙と比べる

設計: 同じ 1 枚の様式の刷り直しが続いた実測の RCA (2 頁はみ出し → 組み込み font 文字化け →
raster を gray にして認印が黒 → 値の位置ずれ) から。 各失敗は個別には既知だったが印刷前に**機械で**
確認する段が無かった。 本 script はその段。 視覚確認 (crop 画像) は別途必須 (= 位置ずれは font/頁数では出ない)。
5. は、 頁数の検査が様式付属の説明書きの頁まで「期待どおり」 と通した実測から (頁数は刷る頁の集合を問わない)。
"""
import argparse
import glob
import os
import re
import shlex
import sys
import tempfile

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    print("pdf-print-preflight: PyMuPDF (fitz) が必要: pip install pymupdf", file=sys.stderr)
    sys.exit(2)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from print_pages import ROLES, changed_pages, classify, parse_pages, problems, read_record, write_record  # noqa: E402
from seal_artifact import MARKER, copy_marker, mark_doc  # noqa: E402
import printer_media  # noqa: E402

# PyMuPDF の組み込み font (非埋め込み)。 get_fonts() の basefont / ref 名に現れる。
BUILTIN_FONT_NAMES = {
    "helv", "heit", "hebo", "hebi", "tiro", "tibo", "tiit", "tibi", "cour", "cobo", "coit", "cobi",
    "symb", "zadb", "japan", "china-s", "china-t", "korea",
}
BUILTIN_BASEFONTS = {
    "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
    "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
    "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
    "Symbol", "ZapfDingbats", "Gothic", "Mincho", "Song", "Ming", "Dotum", "Batang",
}


# 寸法 (mm を丸めた短辺・長辺) → 名前
PAPER_NAMES = {(210, 297): "A4", (148, 210): "A5", (297, 420): "A3", (182, 257): "B5 JIS", (176, 250): "B5 ISO",
               (257, 364): "B4 JIS", (216, 279): "Letter", (100, 148): "はがき"}

PAGE_FIX = ("→ 窓口に出す頁だけの file を作って刷る: pdf-print-preflight.py <元の PDF> --extract <刷る.pdf> --pages <頁> "
            "(頁の一覧を見て全頁とも出す物だと確かめたなら --pages all。 "
            "⚠️ font が 🔴 のとき / 記号・数式の多い文書 / その queue で化けた実績があるときは "
            "--extract でなく --rasterize = font ✓ は raster 不要の判定ではない。 "
            "説明書き等に見える頁を残すなら --include-flagged '<理由>')")


def inspect(path, expect_pages=None, template=None, pages_check=True, fidelity=None):
    """return (findings:list[str], infos:list[str])。 fidelity = 雛形との照合の指定 (無ければ PDF の宣言から読む)。"""
    findings, infos = [], []
    doc = fitz.open(path)
    n = doc.page_count
    if template:
        tn = fitz.open(template).page_count
        if n != tn:
            findings.append(f"🔴 page 数 {n} ≠ 雛形 {tn} ({os.path.basename(template)}) — 様式がはみ出している")
        else:
            infos.append(f"page 数 {n} = 雛形 ✓ (= はみ出していない。 どの頁を刷るかは下の頁の一覧)")
    if expect_pages is not None:
        if n != expect_pages:
            findings.append(f"🔴 page 数 {n} ≠ 期待 {expect_pages}")
        else:
            infos.append(f"page 数 {n} = 期待 ✓ (= はみ出していない。 どの頁を刷るかは下の頁の一覧)")

    risky = []
    has_image = False
    for page in doc:
        for f in page.get_fonts(full=True):
            # (xref, ext, type, basefont, name, encoding, referencer)
            xref, ext, ftype, basefont, name = f[0], f[1], f[2], f[3], f[4]
            base = basefont.split("+")[-1]
            nonembedded = (ext == "n/a")
            if name in BUILTIN_FONT_NAMES or base in BUILTIN_BASEFONTS or nonembedded:
                risky.append(f"{basefont} ({ftype}, ref={name}, ext={ext})")
            elif ftype == "Type0" and "+" not in basefont:
                # PyMuPDF の insert_font(fontfile=) は subset prefix 無しの Type0 で埋め込む
                risky.append(f"{basefont} ({ftype}, PyMuPDF 埋め込みの疑い = printer で化けた実績あり)")
        if page.get_images():
            has_image = True
    if risky:
        uniq = sorted(set(risky))
        shown = "; ".join(uniq[:5]) + (f"; … 他 {len(uniq) - 5} 個" if len(uniq) > 5 else "")
        findings.append(f"🔴 printer で化けうる font が {len(uniq)} 個残っている (PyMuPDF 描画 / 非埋め込み): " + shown
                        + " → 印刷用は --rasterize で RGB raster 版を作って刷る")
    else:
        infos.append("font: PyMuPDF 描画 / 非埋め込み font なし ✓ "
                     "(= 既知の壊れ方が無いだけ。 printer の RIP が全 glyph を出す保証ではない "
                     "= 正しく subset 埋め込みされた CM Type1 でも laser queue が記号を落とした実測あり)")
    if has_image:
        infos.append("画像あり (認印等) — raster 化するなら RGB (gray にすると朱が黒になる)")
    sizes = sorted({(round(pg.rect.width * 25.4 / 72), round(pg.rect.height * 25.4 / 72)) for pg in doc})
    labels = []
    for w, h in sizes:
        nm = PAPER_NAMES.get((min(w, h), max(w, h)))
        labels.append(f"{w}×{h} mm" + (f" ({nm})" if nm else ""))
    infos.append("用紙: " + ", ".join(labels)
                 + " — lp の media 指定は本体の用紙設定を上書きしない = 本体の用紙サイズとトレイの紙を確認"
                 + " (本体に聞く = --printer <queue>)")
    if pages_check:
        blocking, lines = problems(doc)
        rec = read_record(doc)
        infos.append(f"頁の一覧 ({n} 頁" + (f"、 宣言 = {rec.get('src', '?')}" if rec else "、 宣言なし") + "):")
        infos.extend("   " + x for x in lines)
        for b in blocking:
            findings.append(f"🔴 頁: {b}")
        if blocking:
            findings.append("   " + PAGE_FIX)
        fid = (rec or {}).get("fidelity") if rec else None
        if fidelity:
            fid = fidelity
        if fid:
            f2, i2 = fidelity_check(path, fid)
            findings.extend(f2)
            infos.extend(i2)
    return findings, infos


STATIC_TEXT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check-form-static-text.py")


def fidelity_check(path, fid: dict) -> tuple:
    """6. 雛形との照合 (K3): 宣言 (formcase の build が書く {template, targets, drop, blank}) か --template-xlsx から雛形を引き、
    check-form-static-text.py を回す。 図形の字が無い = 🔴 (build と同じ = 止める) / 見出し・画像 = 情報 / 雛形が無い = ⚪ (照合できない、
    止めない = 別の機械で刷るとき。 conventions/form-case-pipeline.md#fidelity)。"""
    import json
    import subprocess

    findings, infos = [], []
    tpl = fid.get("template")
    if not tpl or not os.path.exists(tpl):
        infos.append(f"⚪ 雛形との照合: 雛形が無い ({tpl}) = 照合できない (作った機械で刷るか、 --template-xlsx で雛形を渡す)")
        return findings, infos
    args = [sys.executable, STATIC_TEXT, tpl, path, "--json"]
    for t in fid.get("targets") or []:
        args += ["--target", t]
    for dr in fid.get("drop") or []:
        args += ["--drop", dr]
    if fid.get("blank") and os.path.exists(fid["blank"]):
        args += ["--blank", fid["blank"]]
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
        rep = json.loads(r.stdout) if r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        rep = None
    if rep is None:
        infos.append(f"⚪ 雛形との照合が走らなかった ({os.path.basename(tpl)})")
        return findings, infos
    for t in rep.get("targets") or []:
        where = f"{str(t['sheet']).strip()}!{t['range']}" if rep.get("kind") != "docx" else "docx"
        if t["missing"]:
            ms = ", ".join(f"{m['name']}「{m['text'][:16]}」" for m in t["missing"][:4])
            findings.append(f"🔴 雛形の図形の字が無い {where}: {len(t['missing'])}/{t['checked']} — {ms} "
                            "(紙から見出し・区分の枠・様式番号が消える = 作り直す)")
        elif t["checked"]:
            infos.append(f"雛形の図形の字 {where}: {t['checked']} 段落 ✓")
        b = t.get("blank")
        if b and b.get("images") is not None and b["images"][1] < b["images"][0]:
            infos.append(f"⚠️ {where}: 素刷りより画像が少ない {b['images'][0]} → {b['images'][1]} (checkbox の箱・図)")
        if t.get("missing_labels"):
            infos.append(f"⚠️ {where}: 雛形の見出しが無い {len(t['missing_labels'])}/{t['labels_checked']}")
    return findings, infos


def _select(doc, spec, changed=None):
    """(頁番号 list, 入れた頁で推定が疑わしいもの, 宣言上は提出でない頁)"""
    if (spec or "").strip().lower() == "changed":
        if changed is None:
            raise ValueError("--pages changed には --changed-from が要る")
        if not changed:
            raise ValueError("変わった頁が無い = 刷り直す頁は無い")
        sel = list(changed)
    else:
        sel = parse_pages(spec, doc.page_count)
    rec = read_record(doc)
    decl = rec["pages"] if rec and len(rec["pages"]) == doc.page_count else None
    flagged, declared_off = [], []
    for k in sel:
        if decl and decl[k - 1]["role"] != "submit":
            declared_off.append(f"p.{k} {ROLES.get(decl[k - 1]['role'])} (宣言)")
            continue
        g = classify(doc[k - 1])
        if g["role"] and not decl:
            flagged.append(f"p.{k} {ROLES[g['role']]}? ({g['why']})")
    return sel, flagged, declared_off


def write_selected(src, out, sel, raster, dpi=600, src_label="", include_flagged=None):
    """src の sel 頁 (1 始まり) だけを out に書き、 「提出」 と宣言する。 raster = RGB で描き直す。"""
    doc = fitz.open(src)
    rec = read_record(doc)
    decl = rec["pages"] if rec and len(rec["pages"]) == doc.page_count else None
    o = fitz.open()
    labels = []
    for k in sel:
        page = doc[k - 1]
        g = classify(page)
        labels.append((decl[k - 1].get("label") if decl else "") or g["heading"])
        if raster:
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
            np_ = o.new_page(width=page.rect.width, height=page.rect.height)
            np_.insert_image(np_.rect, pixmap=pix)
        else:
            o.insert_pdf(doc, from_page=k - 1, to_page=k - 1)
    copy_marker(doc, o)  # 紙専用の印 (lib/seal_artifact.py) を引き継ぐ
    dropped = []
    for k in range(1, doc.page_count + 1):
        if k in sel:
            continue
        role = decl[k - 1]["role"] if decl else (classify(doc[k - 1])["role"] or "unselected")
        label = (decl[k - 1].get("label") if decl else "") or classify(doc[k - 1])["heading"]
        dropped.append({"from": k, "role": role, "label": label[:40]})
    src_name = os.path.basename(src)
    by = src_label or f"pdf-print-preflight --pages {','.join(map(str, sel))} ({src_name})"
    write_record(o, [{"role": "submit", "label": lb} for lb in labels], by, dropped=dropped,
                 include_flagged=include_flagged)
    o.save(out, garbage=3, deflate=True)
    return out


def rasterize(src, out, dpi=600):
    """全頁を RGB raster に (頁を選ばない従来の経路)。 src の頁の宣言と紙専用の印を引き継ぐ。"""
    doc = fitz.open(src)
    o = fitz.open()
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
        np_ = o.new_page(width=page.rect.width, height=page.rect.height)
        np_.insert_image(np_.rect, pixmap=pix)
    copy_marker(doc, o)  # 紙専用の印 (lib/seal_artifact.py) を raster 版へ引き継ぐ (印影が画素に焼かれて見分けられなくなるため)
    rec = read_record(doc)
    if rec is not None and len(rec["pages"]) == doc.page_count:
        write_record(o, rec["pages"], rec.get("src", ""), rec.get("dropped"), rec.get("include_flagged"))
    o.save(out, deflate=True)
    return out


def selftest():
    d = tempfile.mkdtemp()
    # A: PyMuPDF 組み込み japan font で文字 → FAIL
    a = os.path.join(d, "a.pdf")
    doc = fitz.open(); p = doc.new_page(); p.insert_text((72, 72), "テスト", fontname="japan"); doc.save(a)
    fa, _ = inspect(a, expect_pages=1)
    assert any("font" in x for x in fa), fa
    # B: raster 版 → PASS
    b = os.path.join(d, "b.pdf"); rasterize(a, b, dpi=72)
    fb, ib = inspect(b, expect_pages=1)
    assert not fb, fb
    assert any("画像あり" in x for x in ib)
    # C: page 数不一致 → FAIL
    c = os.path.join(d, "c.pdf")
    doc = fitz.open(); doc.new_page(); doc.new_page(); doc.save(c)
    fc, _ = inspect(c, template=b)
    assert any("page 数" in x for x in fc), fc
    # D: 文字なし 1 頁 → 白紙として FAIL (頁の検査)、 頁の検査を外せば PASS
    e = os.path.join(d, "d.pdf"); doc = fitz.open(); doc.new_page(); doc.save(e)
    fd, idd = inspect(e, template=b)
    assert any("白紙" in x for x in fd), fd
    fd2, _ = inspect(e, template=b, pages_check=False)
    assert not fd2, fd2
    # E: PyMuPDF の新規頁 (既定 A4) に用紙名が付く
    assert any(x.startswith("用紙: 210×297 mm (A4)") for x in idd), idd
    # F: 紙専用の印 (seal_artifact.MARKER) は raster 版へ引き継がれ、 印の無い入力には付かない
    f = os.path.join(d, "f.pdf"); doc = fitz.open(); doc.new_page(); mark_doc(doc); doc.save(f)
    g = os.path.join(d, "g.pdf"); rasterize(f, g, dpi=36)
    assert MARKER in (fitz.open(g).metadata.get("keywords") or "")
    h = os.path.join(d, "h.pdf"); rasterize(e, h, dpi=36)
    assert MARKER not in (fitz.open(h).metadata.get("keywords") or "")
    # G: 様式 2 頁 + 説明書き 2 頁 (宣言なし) → 頁の検査が FAIL、 --pages 1-2 で作った file は PASS
    four = os.path.join(d, "four.pdf")
    doc = fitz.open()
    for title in ("甲 申請書", "研究計画書", "本制度について", "【表示例】"):
        p = doc.new_page(); p.insert_text((72, 72), title, fontname="japan", fontsize=16)
        p.insert_text((72, 110), "本文", fontname="japan")
        p.draw_line((60, 200), (500, 200))
    mark_doc(doc)
    doc.save(four)
    f4, i4 = inspect(four)
    assert any("宣言が無い" in x for x in f4) and any("p.4 記載例?" in x for x in f4), f4
    assert any("p.3 ⚠️ 説明書き?" in x for x in i4), i4
    two = os.path.join(d, "two.pdf")
    write_selected(four, two, [1, 2], raster=True, dpi=36)
    f2, i2 = inspect(two, expect_pages=2)
    assert not f2, f2
    rec = read_record(fitz.open(two))
    assert [x["role"] for x in rec["pages"]] == ["submit", "submit"] and len(rec["dropped"]) == 2, rec
    assert MARKER in (fitz.open(two).metadata.get("keywords") or "")
    # H: 疑わしい頁を選ぶと _select が名指しする / 宣言で提出でない頁は宣言側で名指し
    _, flagged, off = _select(fitz.open(four), "3-4")
    assert len(flagged) == 2 and not off, (flagged, off)
    bad = fitz.open(two)
    write_record(bad, [{"role": "submit"}, {"role": "instructions", "label": "説明"}], "selftest")
    _, flagged, off = _select(bad, "all")
    assert off and not flagged, (flagged, off)
    # I: 変わった頁だけ刷り直す
    newer = fitz.open(four)
    newer[1].insert_text((72, 150), "訂正", fontname="japan")
    nf = os.path.join(d, "new.pdf"); newer.save(nf)
    assert changed_pages(fitz.open(nf), fitz.open(four)) == [2]
    # J: 宣言つき raster (頁を選ばない経路) は宣言を引き継ぐ
    r2 = os.path.join(d, "r2.pdf"); rasterize(two, r2, dpi=36)
    assert read_record(fitz.open(r2)) is not None and not inspect(r2)[0]
    # K: --hook (PreToolUse の入力 JSON) = lp + 宣言の無い 4 頁は止める / 宣言つき・lp でない・lpstat・無い file は通す
    ev = lambda cmd: {"tool_name": "Bash", "cwd": d, "tool_input": {"command": cmd}}  # noqa: E731
    rc, msg = hook(ev(f"lp -d Office_Printer -o sides=one-sided {four}"))
    assert rc == 2 and "宣言が無い" in msg and "--pages" in msg, (rc, msg)
    E = {"PRINT_PREFLIGHT_PRINTER": "0"}  # 通る側の test は本体に聞かない (本物の queue に問い合わせない)
    assert hook(ev(f'lp -d X "{os.path.basename(two)}"'), env=E)[0] == 0   # 相対 path + 引用符 = cwd 基準
    assert hook(ev(f"ls {four}"))[0] == 0 and hook(ev(f"lpstat -o; echo {four}"))[0] == 0
    assert hook(ev(f"lp {os.path.join(d, 'nope.pdf')}"))[0] == 0 and hook({"tool_input": {}})[0] == 0
    assert hook(ev(f"lp {four}"), env={"PRINT_PREFLIGHT_DISABLE": "1"})[0] == 0
    # L: 見るのは lp の引数だけ = 同じ command で元の PDF から作って刷るのは通す。 代入・cd は追い、 追えない引数は全 .pdf を見る
    assert hook(ev(f"python3 pre.py {four} --rasterize {two} --pages 1-2 && lp -d Q {two}"), env=E)[0] == 0
    assert hook(ev(f"S={d}; cd / && lp -d Q $S/{os.path.basename(four)}"), env=E)[0] == 2
    assert hook(ev(f"cd {d} && lp -o VendorDuplex=None {os.path.basename(four)}"), env=E)[0] == 2
    assert hook(ev(f"for f in {four}; do lp $f; done"), env=E)[0] == 2
    # M: PDF が通ったら本体の用紙を聞く = 合わなければ止める / 答えが無ければ通す / PRINT_PREFLIGHT_PRINTER=0 で聞かない
    seen = []

    def fake(queue, sizes, opts, names=None):
        seen.append((queue, sizes, opts))
        return ["🔴 本体の用紙: 本体が報告するトレイの用紙 = B5 JIS (182×257 mm) / PDF = A4 (210×297 mm)"], []
    rc, msg = hook(ev(f"lp -d Q -o sides=one-sided {two}"), env={}, printer_check=fake)
    assert rc == 2 and "本体の用紙" in msg and seen == [("Q", {(210, 297)}, ["sides=one-sided"])], (rc, msg, seen)
    assert hook(ev(f"PRINT_PREFLIGHT_PRINTER=0 lp -d Q {two}"), env={}, printer_check=fake)[0] == 0
    assert hook(ev(f"lp -d Q {two}"), env={}, printer_check=lambda *x, **k: ([], ["⚪ 未確認"]))[0] == 0
    # N: 雛形との照合 (K3): 宣言に fidelity を持つ PDF は、 雛形の図形の字が無ければ止め、 在れば通す。 雛形が無ければ ⚪ で通す
    import importlib.util
    import openpyxl

    sp = importlib.util.spec_from_file_location("cfst", STATIC_TEXT)
    cfst = importlib.util.module_from_spec(sp); sp.loader.exec_module(cfst)
    tpl = os.path.join(d, "tpl.xlsx")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "様式"
    for coord, v in {"B3": "申請者", "B4": "所属", "B5": "用務"}.items():
        ws[coord] = v
    ws.print_area = "A1:J20"; wb.save(tpl)
    cfst._inject_drawing(tpl, "xl/worksheets/sheet1.xml", cfst._anchor("Shape 1", 1, 1, "外部資金"))

    def fpdf(name, words):
        p = os.path.join(d, name); doc = fitz.open(); pg = doc.new_page(); y = 60
        for t in words:
            pg.insert_text((50, y), t, fontname="japan", fontsize=10); y += 16
        write_record(doc, [{"role": "submit", "label": "様式"}], "selftest",
                     fidelity={"template": tpl, "targets": ["様式!A1:J20"], "drop": [], "blank": None})
        doc.save(p); return p
    ok_pdf = fpdf("fid_ok.pdf", ["申請者", "所属", "用務", "外部資金"])
    bad_pdf = fpdf("fid_bad.pdf", ["申請者", "所属", "用務"])
    # (合成 PDF は組み込み font なので font の 🔴 も出る = 雛形の行だけを見る)
    fo, io_ = inspect(ok_pdf)
    fb, _ = inspect(bad_pdf)
    assert not [f for f in fo if "雛形の図形の字" in f] and any("✓" in x for x in io_), (fo, io_)
    assert any("雛形の図形の字が無い" in f for f in fb), fb
    rb, mb = hook(ev(f"lp -d Q {bad_pdf}"), env=E)
    _ro, mo = hook(ev(f"lp -d Q {ok_pdf}"), env=E)
    assert rb == 2 and "雛形の図形の字が無い" in mb and "雛形の図形の字が無い" not in mo, (mb, mo)
    gone = fpdf("fid_gone.pdf", ["申請者"])
    doc = fitz.open(gone)
    write_record(doc, [{"role": "submit", "label": "様式"}], "selftest",
                 fidelity={"template": os.path.join(d, "no_such.xlsx"), "targets": [], "drop": [], "blank": None})
    doc.save(gone, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    fg, ig = inspect(gone)
    assert not [f for f in fg if "雛形" in f] and any("雛形が無い" in x for x in ig), (fg, ig)
    printer_media._selftest()
    print("pdf-print-preflight selftest: 14/14 PASS (printer_media 含む)")


HOOK_LP = re.compile(r"(^|[;&|\s])lpr?\s")
HOOK_PDF = re.compile(r"(\"[^\"]*\.pdf\"|'[^']*\.pdf'|[^\s\"']+\.pdf)")
HOOK_SEG = re.compile(r"&&|\|\||[;|\n]")
HOOK_PREFIX = {"command", "sudo", "env", "nohup", "time", "exec", "do", "then", "else", "{", "(", "!", "export"}
HOOK_VAR = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")


def _expand(tok, vars_):
    """$NAME / ${NAME} / 先頭の ~ を展開。 追えない変数・command 置換が残れば None。"""
    if "$(" in tok or "`" in tok:
        return None
    miss = []

    def rep(m):
        name = m.group(1) or m.group(2)
        if name in vars_:
            return vars_[name]
        if name in os.environ:
            return os.environ[name]
        miss.append(name)
        return ""
    out = HOOK_VAR.sub(rep, tok)
    if miss:
        return None
    return os.path.expanduser(out) if out.startswith("~") else out


def lp_targets(cmd, cwd=""):
    """command の中の lp / lpr の段 → (lp が見えたか, PDF の path, queue, -o の値, 追えない引数があったか, 代入された変数)。
    段は && || ; | 改行で切る。 同じ command の中の代入と cd を順に追う (= `S=...; cd dir && lp $S/x.pdf` を解決する)。"""
    vars_, pdfs, opts = {}, [], []
    queue, found, unresolved = None, False, False
    for seg in HOOK_SEG.split(cmd):
        try:
            words = shlex.split(seg, comments=True)
        except ValueError:
            words = seg.split()
        i = 0
        while i < len(words):
            m = re.match(r"^([A-Za-z_]\w*)=(.*)$", words[i])
            if m:
                val = _expand(m.group(2), vars_)
                if val is not None:
                    vars_[m.group(1)] = val
            elif words[i] not in HOOK_PREFIX:
                break
            i += 1
        rest = words[i:]
        if not rest:
            continue
        head = os.path.basename(rest[0])
        if head == "cd":
            dest = _expand(rest[1], vars_) if len(rest) > 1 else os.path.expanduser("~")
            if dest is not None:
                cwd = os.path.normpath(dest if os.path.isabs(dest) or not cwd else os.path.join(cwd, dest))
            continue
        if head not in ("lp", "lpr"):
            continue
        found = True
        qflag = "-d" if head == "lp" else "-P"
        args, j = rest[1:], 0
        while j < len(args):
            a = args[j]
            if a in (qflag, "-o") and j + 1 < len(args):
                if a == "-o":
                    opts.append(args[j + 1])
                else:
                    queue = args[j + 1]
                j += 2
                continue
            if a.startswith(qflag) and len(a) > 2:
                queue = a[2:]
            elif a.startswith("-o") and len(a) > 2:
                opts.append(a[2:])
            elif a.lower().endswith(".pdf") or "$" in a or any(c in a for c in "*?["):
                path = _expand(a, vars_)
                if path is None:
                    unresolved = True
                else:
                    if not os.path.isabs(path) and cwd:
                        path = os.path.join(cwd, path)
                    hits = sorted(glob.glob(path)) if any(c in path for c in "*?[") else [path]
                    pdfs.extend(h for h in hits if h.lower().endswith(".pdf"))
            j += 1
    return found, pdfs, queue, opts, unresolved, vars_


def pdf_sizes(path):
    """PDF の頁の寸法 → {(短辺 mm, 長辺 mm)} (本体の用紙と比べる用)。"""
    out = set()
    for pg in fitz.open(path):
        w, h = pg.rect.width * 25.4 / 72, pg.rect.height * 25.4 / 72
        out.add((round(min(w, h)), round(max(w, h))))
    return out


def hook(payload: dict, env=None, printer_check=None) -> tuple:
    """PreToolUse(Bash) の入力 → (exit code, stderr の文)。 `lp` / `lpr` に .pdf を渡す command だけを見て、 PDF ごとに
    inspect を回す。 1 本でも FAIL なら 2 (= 実行前に止め、 理由を model に返す)。 それ以外・読めない入力は 0 (fail-open)。
    PDF が通ったら、 lp の queue の本体にトレイの用紙を聞き (lib/printer_media.py)、 PDF の寸法と合わなければ 2。

    見るのは lp / lpr の引数の PDF だけ: 以前は command 中の全 .pdf を見ていたので、 `preflight 元.pdf --rasterize 刷る.pdf
    && lp 刷る.pdf` のように同じ command で作ってから刷ると、 作る元の (宣言の無い) PDF で止まった (実測)。 追えない引数
    ($f・command 置換) や lp が段の先頭に無い形 (xargs lp 等) では、 取りこぼさないよう従来どおり全 .pdf を見る。

    止め方を確認 (ask) にしないのは、 確認の dialog に理由が出ない build がある (conventions/hook-authoring.md
    #build-dependent-docs-drift) = user は理由を見ずに承認し、 model も直し方を知らないまま刷るため。"""
    env = os.environ if env is None else env
    if env.get("PRINT_PREFLIGHT_DISABLE") == "1":
        return 0, ""
    cmd = ((payload or {}).get("tool_input") or {}).get("command") or ""
    if ".pdf" not in cmd or not HOOK_LP.search(cmd):
        return 0, ""
    cwd = (payload or {}).get("cwd") or ""
    found, paths, queue, opts, unresolved, vars_ = lp_targets(cmd, cwd)
    if not found or unresolved:
        for m in HOOK_PDF.finditer(cmd):
            tok = m.group(1).strip("\"'")
            path = os.path.expanduser(tok) if tok.startswith("~/") else tok
            if not os.path.isabs(path) and cwd:
                path = os.path.join(cwd, path)
            paths.append(path)
    fails, sizes, seen = [], set(), set()
    for path in paths:
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        try:
            findings, infos = inspect(path)
            sizes |= pdf_sizes(path)
        except Exception as e:  # noqa: BLE001 - 読めない PDF は止めずに知らせない (fail-open、 lp 側が失敗を出す)
            print(f"pdf-print-preflight --hook: {path} を読めない ({type(e).__name__})", file=sys.stderr)
            continue
        if findings:
            fails.append(f"── {path}\n" + "\n".join(["  · " + i for i in infos] + ["  " + f for f in findings]))
    if not fails:
        if not (found and sizes) or "0" in (env.get("PRINT_PREFLIGHT_PRINTER"), vars_.get("PRINT_PREFLIGHT_PRINTER")):
            return 0, ""
        pf, _ = (printer_check or printer_media.check)(queue, sizes, opts, names=PAPER_NAMES)
        if not pf:
            return 0, ""
        return 2, "\n".join([
            "[print-preflight] 本体の用紙が PDF と合わない — このまま刷ると本体の設定どおりの紙に出る:",
            *["  " + f for f in pf], "",
            "対処: 本体 (操作パネル) の用紙サイズ設定とトレイの紙を PDF に合わせてから lp を打ち直す (user に頼む)。",
            "      意図して別の紙に刷る (縮小・拡大) 時と、 本体の報告が誤っていると現物で確かめた時だけ、 command の頭に PRINT_PREFLIGHT_PRINTER=0 を付ける (本体に聞かない)。",
            "正本: conventions/office-automation.md#printer-media-ipp",
        ])
    msg = "\n".join([
        "[print-preflight] 印刷前 preflight FAIL — この PDF はそのまま lp に渡さない (文字化け / 窓口に出さない頁 / どの頁を出すかの宣言なし):",
        *fails, "",
        "対処 (直してから lp を打ち直す):",
        "  - 頁: 窓口に出す頁だけの file を作る = pdf-print-preflight.py <元の PDF> --extract <刷る.pdf> --pages <頁>",
        "        (lp -o page-ranges は無視される queue がある = 頁は file で選ぶ。 説明書き・記載例・控え・マスタ・白紙は刷らない。",
        "         本当に要る頁なら --include-flagged '<理由>'。 様式の記入 map を持つ生成道具なら、 提出頁だけを出力するよう直す。",
        "         配布物のように全頁とも出す物だと頁の一覧で確かめたなら --pages all で『全頁を提出頁』 と宣言する)",
        "  - font: 🔴 のとき / 記号・数式の多い文書 / その queue で化けた実績があるときは --rasterize で",
        "        RGB 600dpi raster 版を作って刷る (認印は RGB でしか朱が残らない)。 ⚠️ font の ✓ は「既知の壊れ方が",
        "        無い」 であって RIP が全 glyph を出す保証ではない = 正しく subset 埋め込みされた CM Type1 でも",
        "        laser queue が記号 (slash・Greek) を落とした実測がある。 化けは 1 部目の現物でしか分からない。",
        "  - 刷る頁の一覧 (上) を user に 1 行で伝えてから刷る。 crop 目視 + remote の user には全頁 PNG。",
        "正本: conventions/office-automation.md#print-preflight / #print-submission-pages-only",
    ])
    return 2, msg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--template", help="雛形 PDF (page 数比較)")
    ap.add_argument("--expect-pages", type=int)
    ap.add_argument("--rasterize", metavar="OUT_PDF", help="検査後に RGB raster 版を書き出す")
    ap.add_argument("--extract", metavar="OUT_PDF", help="頁を選んだ vector 版を書き出す (--pages と使う)")
    ap.add_argument("--pages", help="OUT に入れる頁 = 窓口に出す頁 (all / 1-2,4 / changed)")
    ap.add_argument("--include-flagged", metavar="REASON", help="説明書き等に見える頁を理由つきで残す")
    ap.add_argument("--changed-from", metavar="OLD_PDF", help="前に刷った版と頁ごとに比べる")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--printer", nargs="?", const="", metavar="QUEUE",
                    help="本体にトレイの用紙を IPP で聞いて PDF と比べる (QUEUE 省略 = 既定の送信先)")
    ap.add_argument("--template-xlsx", metavar="雛形.xlsx", help="雛形との照合 (図形の字・見出し) を手で指定 (宣言が無い PDF 用)")
    ap.add_argument("--target", action="append", help="--template-xlsx の対象 'sheet' / 'sheet!A1:AH60' (繰り返し可)")
    ap.add_argument("--hook", action="store_true",
                    help="PreToolUse(Bash) hook として動く: 入力 JSON を stdin から読み、 lp に渡す PDF が FAIL なら exit 2")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return 0
    if a.hook:
        import json
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            return 0
        rc, msg = hook(payload)
        if msg:
            print(msg, file=sys.stderr)
        return rc
    if not a.pdf:
        ap.error("pdf を指定 (or --selftest)")
    rc = run_checks(a, ap)
    if a.printer is not None:
        pf, pi = printer_media.check(a.printer or None, pdf_sizes(a.pdf), names=PAPER_NAMES)
        for i in pi:
            print("  ·", i)
        for f in pf:
            print(" ", f)
        rc = rc or (1 if pf else 0)
    return rc


def run_checks(a, ap):
    """--printer 以外の CLI の検査 (頁・font・用紙の寸法・書き出し) → exit code。"""
    if a.rasterize and a.extract:
        ap.error("--rasterize と --extract はどちらか 1 つ")
    out = a.rasterize or a.extract
    if a.pages and not out:
        ap.error("--pages は --rasterize か --extract と使う (刷る頁だけの file を作る)")

    changed = None
    if a.changed_from:
        changed = changed_pages(fitz.open(a.pdf), fitz.open(a.changed_from))
        same = [k for k in range(1, fitz.open(a.pdf).page_count + 1) if k not in changed]
        print(f"  · 前に刷った版 ({os.path.basename(a.changed_from)}) と比べて変わった頁: "
              + (", ".join(f"p.{k}" for k in changed) or "なし") + " / 同じ頁: " + (", ".join(f"p.{k}" for k in same) or "なし"))
        if changed and same:
            print("    → 刷り直すのは変わった頁だけでよい: --pages changed")

    if a.pages:
        src_doc = fitz.open(a.pdf)
        try:
            sel, flagged, off = _select(src_doc, a.pages, changed)
        except ValueError as e:
            print(f"  🔴 {e}")
            return 1
        if off:
            print("  🔴 宣言で窓口に出さないとされた頁を選んでいる: " + ", ".join(off))
            if not a.include_flagged:
                print("  ✗ 書かない。 本当に刷るなら --include-flagged '<理由>'")
                return 1
        if flagged and not a.include_flagged:
            print("  🔴 窓口に出さない頁に見える頁を選んでいる: " + ", ".join(flagged))
            print("  ✗ 書かない。 --pages から外す。 本当に窓口に出す (or 読むために刷る) なら --include-flagged '<理由>'")
            return 1
        write_selected(a.pdf, out, sel, raster=bool(a.rasterize), dpi=a.dpi, include_flagged=a.include_flagged)
        kind = f"raster 版 ({a.dpi} dpi RGB)" if a.rasterize else "vector 版"
        print(f"  ✅ {kind}: {out} ({os.path.getsize(out)//1024} KB、 元の {src_doc.page_count} 頁から "
              + ", ".join(f"p.{k}" for k in sel) + " を提出頁として宣言) — 印刷はこちらを lp に渡す")
        findings, infos = inspect(out, a.expect_pages, a.template)
        for i in infos:
            print("  ·", i)
        for f in findings:
            print(" ", f)
        return 1 if findings else 0

    fid = {"template": a.template_xlsx, "targets": a.target or [], "drop": [], "blank": None} if a.template_xlsx else None
    findings, infos = inspect(a.pdf, a.expect_pages, a.template, fidelity=fid)
    for i in infos:
        print("  ·", i)
    for f in findings:
        print(" ", f)
    if a.rasterize:
        out = rasterize(a.pdf, a.rasterize, a.dpi)
        print(f"  ✅ raster 版: {out} ({os.path.getsize(out)//1024} KB, {a.dpi} dpi RGB) — 印刷はこちらを lp に渡す")
        of, _ = inspect(out, a.expect_pages, a.template)
        page_bad = [f for f in of if f.startswith("🔴 頁:") or "page 数" in f]
        if page_bad:
            print("  ⚠️ この raster は頁の検査で止まる (lp の前の gate も同じ判定):")
            for f in page_bad:
                print("   ", f)
            print("   ", PAGE_FIX)
        return 0 if not any("page 数" in f or f.startswith("🔴 頁:") for f in of) else 1
    if a.extract:
        print("  🔴 --extract は --pages と使う")
        return 1
    if findings:
        print("  ✗ preflight FAIL — このまま lp に渡さない")
        return 1
    print("  ✓ preflight PASS (位置ずれは別途 crop 画像で目視)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
