"""様式ごとの生成 recipe (= 値は spec と案件の workbook、 体裁は使い捨ての temp / staged copy にだけ当てる)。

build(m, doc_id, groups, out_dir) は:
  1. gate (gates.py) を group の範囲で回す。 FAIL なら何も書かない
  2. 体裁を当てて Excel で PDF 化 (元 xlsx は触らない)。 体裁の出どころは全様式で同じ 3 つ (layout.py、 form-case-pipeline.md #layout-3):
     配布雛形 (行高・印刷範囲・手動改ページ) / spec の ``render:`` (雛形の欠陥、 各 entry に理由) / 記入値の長さ (折り返し・行高)
  3. Excel の PDF を字の切れ・はみ出し gate (check-form-clipping) で見て、 引っかかった欄を折り返し → 行を伸ばして刷り直す
     (最大 FIT_ROUNDS 回)。 残れば出力を書かずに止める
  4. package から group の page を切り出し、 その group の page にだけ押印を overlay
  5. group の出力 (print = 紙で出す版 / confirm = 押印なし / 様式固有の派生) を書く
凍結 group は作らない (呼び元が弾く)。 押印の variant は group ごとに引くので、 他 group の出力は変わらない。

temp の作り方は雛形で 2 通り:
  - 図形が紙に出ない雛形 = openpyxl で temp workbook を作って Excel に PDF 化させる
  - 標題・checkbox が図形の雛形 (openpyxl で save すると消える) → 体裁は openpyxl の読み込みの上で計算し、
    差分だけを Excel の操作として staged copy に当てて PDF 化する (layout.snapshot / excel_ops、 excel.ops_lines)

**様式ごとの recipe はこの module が持たない** (= 雛形の page 構成・sheet 名・押印位置・出力名は呼び元のもの)。
呼び元は設定の ``recipes`` が指す python file で ``Recipe`` を継承したクラスを書き、 ``register(form_id, cls)``
で登録する。 docx 様式は spec から全部読めるので ``RecipeDocx`` が汎用に扱う。
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

from . import config as CF
from . import excel as X
from . import gates as GT
from . import layout as LY
from . import specs as S

CC = Path(__file__).resolve().parent.parent          # 同じ repo の scripts/
sys.path.insert(0, str(CC / "lib"))
import print_pages as PP  # noqa: E402  (刷る頁の宣言と推定、 conventions/office-automation.md#print-submission-pages-only)

SEAL_ENGINE = CC / "overlay-seal-pdf.py"
GUIDANCE_GATE = CC / "verify-form-guidance.py"
CLOSE_BOXES = CC / "close-pdf-form-boxes.py"
CLIPPING = CC / "check-form-clipping.py"


class BuildError(Exception):
    pass


def _run(argv, label):
    r = subprocess.run([str(a) for a in argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.stdout.strip():
        print("\n".join("   " + x for x in r.stdout.rstrip().splitlines()))
    if r.returncode != 0:
        raise BuildError(f"{label} FAIL → 出力を書かずに中断")


def _seal_image() -> str:
    """印影の画像 path (設定の ``seal_image_cmd`` が 1 行で印字する。 = どの印を押すかは呼び元のもの)。"""
    cmd = CF.seal_image_cmd()
    if not cmd:
        raise BuildError("押印のある出力を作るには設定の seal_image_cmd (印影の画像 path を最後の行に印字する command) が要る")
    argv = [sys.executable if x == "python3" else os.path.expanduser(str(x)) for x in cmd]
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise BuildError(f"seal_image_cmd が印影の path を返さない ({argv}): {r.stderr.strip()[-200:]}")
    return r.stdout.strip().splitlines()[-1]


def _extract(src_pdf, pages_1based, dst):
    import fitz

    d = fitz.open(src_pdf)
    o = fitz.open()
    for p in pages_1based:
        o.insert_pdf(d, from_page=p - 1, to_page=p - 1)
    o.save(dst)
    o.close()
    d.close()


def _close_boxes(src, dst):
    """Excel が PDF で落とす結合セルの下罫線を閉じる。 開いた枠が無いと engine は出力を書かない (実測: 枠が全部
    閉じている PDF で FileNotFoundError) = その時は入力をそのまま使う。"""
    _run([sys.executable, CLOSE_BOXES, src, dst], "枠の下端を閉じる (close-pdf-form-boxes)")
    if not Path(dst).exists():
        shutil.copy2(src, dst)
    return dst


def _raster(src, dst, dpi=600):
    """印刷用の raster PDF (subset font の printer 化け対策、 層1 #print-raster-pdf。 pdf_form_fill と同じ作り)。
    刷る頁の宣言 (層1 print_pages) を引き継ぐ (= raster は字が無く、 刷る直前の gate が中身を読めないため)。"""
    import fitz

    d = fitz.open(src)
    out = fitz.open()
    for pg in d:
        pix = pg.get_pixmap(dpi=dpi)
        np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, stream=pix.tobytes("png"))
    PP.copy_record(d, out)
    out.save(dst, deflate=True)
    return dst


# ---------------------------------------------------------------------------
# 刷る頁 (form-case-pipeline.md #page-roles) — 出力は group の pages (= 窓口に出す頁) だけ。 その宣言を出力に書き込む
# ---------------------------------------------------------------------------
def check_page_anchors(pdf, spec) -> list:
    """spec の page_roles の anchor が PDF のその頁に在るか。 [(頁, anchor)] = 見つからないもの (= 雛形の頁構成が spec と違う)。
    照合の実体 = 層1 print_pages.anchor_misses (空白と全角半角を無視)。"""
    import fitz

    return PP.anchor_misses(fitz.open(str(pdf)), S.page_roles(spec))


def declare_pages(pdf, spec, group, pages) -> list:
    """group の出力 PDF (pages = package の頁番号) に「全頁 = 窓口に出す頁」 の宣言を書く。 返り値 = 表示用の行。
    実体 = 層1 print_pages.declare_submit: spec の page_roles の無い頁 (Excel 様式) に記載例・控え・注意事項・白紙の推定が
    当たれば書かずに BuildError (= spec の page_roles に submit + anchor を書くか、 group の pages から外すかを決める)。
    page_roles で submit と宣言した頁は推定が疑わしくても止めない (anchor で中身を照合済み)、 行に出すだけ。"""
    import fitz

    roles = S.page_roles(spec)
    d = fitz.open(str(pdf))
    labels = [(roles.get(pp) or {}).get("label") if pp in roles else None for pp in pages]
    dropped = [{"from": k, "role": r.get("role"), "label": r.get("label", "")} for k, r in roles.items() if k not in pages]
    stop, lines = PP.declare_submit(d, labels, f"formcase {spec['meta']['id']}/{group}", dropped=dropped or None)
    if stop:
        raise BuildError(f"group {group} の出力に窓口に出さない頁に見える頁が入る (出力の頁番号): " + " / ".join(stop)
                         + "。 出す頁なら spec の page_roles に submit + anchor を書く、 出さないなら group の pages から外す "
                         "(form-case-pipeline.md #page-roles)")
    tmp = Path(str(pdf) + ".decl.pdf")
    d.save(str(tmp), garbage=3, deflate=True)
    d.close()
    tmp.replace(pdf)
    return [f"group {group}: {x}" for x in lines]


def _ensure_declared(src, like) -> Path:
    """src (出力) に宣言が無ければ like (宣言済みの group の PDF) から写した copy を返す。 頁数が違えば BuildError。"""
    import fitz

    d = fitz.open(str(src))
    if PP.read_record(d) is not None:
        return Path(src)
    ref = fitz.open(str(like))
    if ref.page_count != d.page_count:
        raise BuildError(f"{Path(src).name} の頁数 {d.page_count} が group の頁数 {ref.page_count} と違う = 刷る頁の宣言を写せない")
    if not PP.copy_record(ref, d):
        raise BuildError(f"{Path(src).name} に写す刷る頁の宣言が group の PDF に無い (declare_pages の後で書き換えられた)")
    out = Path(str(src) + ".decl.pdf")
    d.save(str(out), garbage=3, deflate=True)
    return out


def _seal(plain, sealed, places):
    """places = [(page_in_group, place_spec_without_page)]。"""
    argv = [sys.executable, SEAL_ENGINE, plain, "--out", sealed]
    for page, spec in places:
        argv += ["--place", f"page={page},{spec}", "--image", _seal_image()]
    _run(argv, "押印 overlay")


def _save(wb, dst):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb.save(dst)
    return dst


# ---------------------------------------------------------------------------
# 字の切れ・はみ出し gate (全様式共通)
# ---------------------------------------------------------------------------
def _load(path, data_only=False):
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(path, data_only=data_only)


def _require_cached(workbook):
    """数式の計算済み値が要る (字の切れ gate が、 数式で他 sheet に複製された欄も値として見る)。"""
    from . import fingerprint as FP

    w = FP.last_writer(workbook) or ""
    if "openpyxl" in w.lower():
        raise BuildError(f"{Path(workbook).name} の最後の保存が openpyxl ({w}) = 数式の計算済み値が無い → "
                         "`formcase.py normalize CASE DOC` で Excel に保存させてから build")


def _in_ranges(coord, ranges):
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string, range_boundaries

    col, row = coordinate_from_string(coord)
    ci = column_index_from_string(col)
    for rng in ranges:
        c0, r0, c1, r1 = range_boundaries(rng)
        if c0 <= ci <= c1 and r0 <= row <= r1:
            return True
    return False


def _clip_source(workbook, tpl, keep: dict, dst: Path) -> Path:
    """字の切れ検査に渡す workbook。 keep = {sheet: [range, ...]} (= この PDF に刷った範囲、 None = sheet 全体)。

    範囲の外の cell は雛形の値に戻す (check-form-clipping は記入値を PDF 全体で探すので、 刷っていない sheet の値が
    別の page に偶然現れて誤検出する = 実測、 同じ値の欄の数も数え過ぎる)。 数式は計算済みの値にして
    保存する (= 数式で他 sheet に複製された欄も記入値として照合される)。 元 workbook は触らない。"""
    from openpyxl.cell.cell import MergedCell

    wb, wt = _load(workbook, data_only=True), _load(tpl, data_only=True)
    keep = {k.strip(): v for k, v in keep.items()}
    for ws in wb.worksheets:
        kept = ws.title.strip() in keep
        ranges = keep.get(ws.title.strip())          # None = sheet 全体
        src = next((t for t in wt.worksheets if t.title.strip() == ws.title.strip()), None)
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c, MergedCell) or c.value is None:
                    continue
                if kept and (ranges is None or _in_ranges(c.coordinate, ranges)):
                    continue
                c.value = src[c.coordinate].value if src is not None else None
    return _save(wb, dst)


# 記入値の描画の倍率の下限 (= 描画の字の大きさ / cell の font size)。 提出して受理された紙で一番縮んでいた page が
# 0.61 倍だった実測から。 それ未満 = 行を伸ばし過ぎ・値が長過ぎで page が縮み過ぎ (form-case-pipeline.md #layout-3)。
MIN_SCALE = 0.6


def _clip_findings(tpl, src, pdf) -> dict:
    import json

    r = subprocess.run([sys.executable, str(CLIPPING), "--json", "--min-scale", str(MIN_SCALE), str(tpl), str(src), str(pdf)],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise BuildError(f"字の切れ gate の出力が読めない (exit {r.returncode}): {r.stdout[-300:]}")


def _clip_gate(workbook, tpl, keep, pdf, tmp, tag):
    _require_cached(workbook)
    src = _clip_source(workbook, tpl, keep, Path(tmp) / f"{tag}_clip_source.xlsx")
    _run([sys.executable, CLIPPING, "--min-scale", MIN_SCALE, tpl, src, pdf],
         "字の切れ・はみ出し・###・字の小ささ (check-form-clipping)")


def grow(wb, extra, found) -> list:
    """見つかった欄 (loc = sheet!cell、 fan-out は同じ値の全欄) の行を伸ばす量を extra に足す。 足した欄の説明を返す。

    まだ折り返していない欄 = まず折り返す (行は見積りで伸びる) / 折り返している欄 = 見えた字数から 1 行の字数を出し、
    欠けた字の行数 (はみ出し・字の小ささは 1 行) だけ行を足す。"""
    from openpyxl.utils import get_column_letter

    grown = []
    for kind, f in found:
        for loc in f["loc"].split(", "):
            sheet, coord = loc.rsplit("!", 1)
            ws = LY._sheet(wb, sheet)
            if ws is None:
                continue
            c0, r0, c1, r1, _merged = LY._box(ws, coord)
            tl = f"{get_column_letter(c0)}{r0}"
            key = (sheet.strip(), tl)
            ex = extra.setdefault(key, {})
            if not ws[tl].alignment.wrap_text and not ex.get("wrap"):
                ex["wrap"] = True
                grown.append(f"{sheet.strip()}!{tl} 折り返し")
                continue
            pitch = float(ws[tl].font.sz or 11) * LY.line_pitch(ws[tl].font.name)
            height = sum(LY._row_h(ws, r) for r in range(r0, r1 + 1))
            lines = 1
            if kind == "clip" and 0 < f["frag"] < f["len"]:   # 見えた字数から 1 行の字数を出し、 欠けた字の行数だけ
                per_line = max(1.0, f["frag"] / max(1, math.floor(height / pitch)))
                lines = min(4, math.ceil((f["len"] - f["frag"]) / per_line))
            ex["pt"] = float(ex.get("pt", 0)) + lines * pitch
            grown.append(f"{sheet.strip()}!{tl} +{lines * pitch:.1f}pt")
    return grown


# ---------------------------------------------------------------------------
# recipe 定義
# ---------------------------------------------------------------------------
class Recipe:
    form = ""
    outputs = {}        # group → {role: 名前の型 ({stem} = workbook の stem。 変数を足すのは name_vars)}
    seals = {}          # package page (1 始まり) → place spec (page= を除く)
    FIT_ROUNDS = 3      # Excel で刷る回数の上限 (= 刷り直しは FIT_ROUNDS - 1 回まで)

    def package(self, workbook: Path, tmp: Path) -> Path:
        raise NotImplementedError

    def package_for(self, group: str, workbook: Path, tmp: Path) -> Path:
        """group の page を含む package。 既定 = 全 group 共通の 1 本。
        group ごとに別の sheet を刷る様式は上書きする。"""
        if getattr(self, "_pkg", None) is None:
            self._pkg = self.package(workbook, tmp)
        return self._pkg

    def seals_for(self, group: str) -> dict:
        return self.seals

    def post_group(self, m, doc_id, group, plain: Path):
        """group の押印なし PDF に対する後処理と gate (recipe 固有)。"""

    def derive(self, group: str, role: str, plain: Path, workbook: Path, tmp: Path):
        """print / confirm 以外の出力 (raster・送付用 xlsx 等) を作って path を返す。 作らない role は None。"""
        return None

    def name_vars(self, stem: str) -> dict:
        """出力名の型に渡す変数。 既定 = ``{stem}`` だけ。 派生名の要る様式は足す (= 名づけは呼び元のもの)。"""
        return {"stem": stem}

    def default_outputs(self, stem: str) -> dict:
        v = self.name_vars(stem)
        return {g: {role: pat.format(**v) for role, pat in roles.items()}
                for g, roles in self.outputs.items()}

    # --- 刷り直しの loop (全様式共通) ----------------------------------------------------------
    def fit(self, label, render, findings):
        """render(extra, rnd) -> (体裁を当てた openpyxl workbook, PDF) / findings(PDF, rnd) -> [(kind, finding)]。
        切れ・はみ出しが無くなるか、 FIT_ROUNDS 回刷るか、 伸ばす欄が無くなるまで回し、 最後の PDF を返す
        (残った切れは呼び元の gate が止める = 出力を書かない)。"""
        extra = {}
        pdf = None
        for rnd in range(1, self.FIT_ROUNDS + 1):
            wb, pdf = render(extra, rnd)
            found = findings(pdf, rnd)
            if not found:
                return pdf
            if rnd == self.FIT_ROUNDS:
                print(f"   体裁{label}: {self.FIT_ROUNDS} 回刷っても切れ・はみ出しが残る (下の gate が止める)")
                return pdf
            grown = grow(wb, extra, found)
            if not grown:
                print(f"   体裁{label}: 切れ・はみ出し {len(found)} 件は伸ばせる欄に無い (下の gate が止める)")
                return pdf
            print(f"   体裁{label}: 切れ・はみ出し {len(found)} 件 → 行を伸ばして刷り直す ({rnd}/{self.FIT_ROUNDS - 1}): "
                  + ", ".join(grown))
        return pdf

    def found_in(self, workbook, tpl, keep, pdf, tmp, tag) -> list:
        src = _clip_source(workbook, tpl, keep, tmp / f"{tag}.xlsx")
        res = _clip_findings(tpl, src, pdf)
        return [("clip", c) for c in res["clip"]] + [("overflow", o) for o in res["overflow"]]


def _chunks_pdf(wb, sheet, chunks, tmp, tag):
    """sheet だけが残った wb を、 chunks (紙 1 枚ずつの range) ごとに 1 枚に収めて Excel で PDF にし、 並べる。"""
    import fitz

    ws = LY._sheet(wb, sheet)
    jobs = []
    for k, area in enumerate(chunks):
        LY.one_page(ws, area)
        x, p = tmp / f"{tag}_{k}.xlsx", tmp / f"{tag}_{k}.pdf"
        _save(wb, x)
        jobs.append((x, p))
    X.export_pdfs(jobs)
    out = fitz.open()
    for (_x, p), area in zip(jobs, chunks):
        d = fitz.open(p)
        if d.page_count != 1:
            raise BuildError(f"{sheet} {area} が紙 1 枚にならない ({d.page_count} page)")
        out.insert_pdf(d)
    raw = tmp / f"{tag}.pdf"
    out.save(raw)
    return raw


class RecipeDocx(Recipe):
    """Word (docx) 様式 (spec の meta.kind = docx、 form-case-pipeline.md #docx)。 group は spec の groups (1 つ = 全 page)。

    package = 案件の docx を Word で PDF → page 数を spec の meta.pages と照合 (autofit の表で頁がはみ出す様式 =
    はみ出したら止める) → 選択肢の ○ と短い値を overlay.yaml から重ねる。 押印の位置は spec の docx.seal から PDF で出す。
    出力 = print (押印、 紙専用の印) / raster (print の 600dpi RGB = 刷るのはこれ、 印を引き継ぐ) / confirm (押印なし)。
    出力名の型は spec の ``outputs:`` (無ければ下の既定。 = 名づけは呼び元のもの)。"""
    OUT = {"print": "{stem}_print.pdf", "raster": "{stem}_print_raster.pdf", "confirm": "{stem}_confirm.pdf"}

    def __init__(self, form_id):
        from . import docx_form as DF

        self.DF = DF
        self.form = str(form_id)
        self.spec = S.get(self.form)
        out = {str(k): str(v) for k, v in (self.spec.get("outputs") or {}).items()} or dict(self.OUT)
        self.outputs = {g: dict(out) for g in (self.spec.get("groups") or {})}
        self._pkg = None
        self._seals = {}
        self._sealed = {}

    def package_for(self, group, workbook, tmp):
        import fitz

        if self._pkg is not None:
            return self._pkg
        DF = self.DF
        try:
            raw = DF.to_pdf(Path(workbook), tmp / "word.pdf")
            n = fitz.open(raw).page_count
            if n != DF.pages(self.spec):
                raise BuildError(f"Word の PDF が {n} page (spec の meta.pages = {DF.pages(self.spec)}) = 値の長さで表の頁が"
                                 "はみ出した (層1 office-automation.md#docx-autofit-grid-overflow)。 欄の値を短くするか spec の "
                                 "docx.render で字を小さくする")
            miss = check_page_anchors(raw, self.spec)
            if miss:
                raise BuildError("Word の PDF の頁が spec の page_roles と合わない (頁の目印が無い): "
                                 + ", ".join(f"{k} 頁「{a}」" for k, a in miss)
                                 + " = 雛形が改訂されて頁の中身がずれた。 各頁を見て page_roles と groups の pages を直す "
                                 "(form-case-pipeline.md #page-roles)")
            pkg = tmp / "package.pdf"
            DF.overlay(raw, pkg, self.spec, DF.load_overlay(workbook))
            self._seals = DF.seal_places(pkg, self.spec)
        except DF.DocxFormError as e:
            raise BuildError(str(e))
        self._pkg = pkg
        return pkg

    def seals_for(self, group):
        return self._seals

    def derive(self, group, role, plain, workbook, tmp):
        if role != "raster":
            return None
        import fitz

        sys.path.insert(0, str(CC / "lib"))
        from seal_artifact import copy_marker

        sealed = tmp / f"{group}_sealed.pdf"
        src = sealed if sealed.exists() else plain
        d = fitz.open(src)
        out = fitz.open()
        for pg in d:
            pix = pg.get_pixmap(dpi=600, colorspace=fitz.csRGB)
            np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
            np_.insert_image(np_.rect, pixmap=pix)
        copy_marker(d, out)
        PP.copy_record(fitz.open(plain), out)   # 刷る頁の宣言 (build が group の頁に書いたもの) を raster へ
        dst = tmp / f"{group}_raster.pdf"
        out.save(dst, deflate=True)
        # 期待の頁数 = group の頁 (= 窓口に出す頁) の数。 meta.pages (Word が出す頁) ではない = 説明書きの頁まで「期待どおり」
        # と通した実測から (form-case-pipeline.md #page-roles)。 頁の役割 (宣言) も preflight が見る
        n = len(S.group_def(self.spec, group).get("pages") or [])
        _run([sys.executable, CC / "pdf-print-preflight.py", dst, "--expect-pages", n], "印刷の preflight (raster 版)")
        return dst


# 様式ごとの recipe の登録簿。 中身は呼び元が入れる (= engine は空で出荷する)
RECIPES: dict = {}
_FROM_FILE: set = set()          # file の load で入った form id (= 設定が変わったら捨てる。 直接の register は残す)
_LOADED_FROM = None


def register(form_id, cls):
    """様式 ``form_id`` の recipe を登録する (呼び元の設定 ``recipes`` が指す file から呼ぶ)。"""
    RECIPES[str(form_id)] = cls
    return cls


def load_instance_recipes() -> None:
    """設定の ``recipes`` が指す python file を読む (= その file が register を呼ぶ)。 設定が変わったら読み直す。"""
    global _LOADED_FROM

    key = str(CF.config_dir())
    if _LOADED_FROM == key:
        return
    import importlib.util

    for fid in _FROM_FILE:
        RECIPES.pop(fid, None)
    _FROM_FILE.clear()
    before = set(RECIPES)
    for f in CF.recipe_files():
        if not f.exists():
            raise BuildError(f"設定の recipes が指す file が無い: {f}")
        sp = importlib.util.spec_from_file_location(f"formcase_recipes_{abs(hash(str(f)))}", f)
        mod = importlib.util.module_from_spec(sp)
        sys.modules[sp.name] = mod
        sp.loader.exec_module(mod)
    _FROM_FILE.update(set(RECIPES) - before)
    _LOADED_FROM = key


def recipe_for(form_id):
    load_instance_recipes()
    cls = RECIPES.get(str(form_id))
    if cls is None:
        from . import docx_form as DF

        if DF.is_docx(S.get(form_id)):
            return RecipeDocx(form_id)
        raise BuildError(f"form {form_id!r} の生成 recipe が無い (設定の recipes が指す file に register する。 "
                         "form-case-pipeline.md #scope)")
    return cls()


def build(m, doc_id, groups, out_dir=None) -> dict:
    """group の出力を作る。 返り値 = {group: {role: path}}。 out_dir 指定時は案件 dir に書かない (照合用)。
    Excel の失敗 (excel.ExcelError、 osascript の標準エラーを逐語で含む) は BuildError にして出力を書かない。"""
    try:
        return _build(m, doc_id, groups, out_dir)
    except X.ExcelError as e:
        raise BuildError(str(e))


def _build(m, doc_id, groups, out_dir=None) -> dict:
    doc = m.doc(doc_id)
    rc = recipe_for(doc.get("form"))
    spec = S.get(doc.get("form"))
    wb = m.workbook(doc_id)
    if wb is None or not wb.exists():
        raise BuildError(f"{doc_id}: workbook が無い")
    unsupported = [g for g in groups if g not in rc.outputs]
    if unsupported:
        raise BuildError(f"recipe {rc.form} は group {unsupported} を作れない (form-case-pipeline.md #scope)")
    role_probs = S.page_role_problems(spec)              # 刷る頁の宣言の矛盾 (form-case-pipeline.md #page-roles)
    if role_probs:
        raise BuildError("spec の頁の役割が矛盾している: " + " / ".join(role_probs))
    GT.run_scoped(m, doc_id, groups)                     # FAIL なら BuildError
    written = {}
    with tempfile.TemporaryDirectory(prefix="formcase-build-") as td:
        tmp = Path(td)
        for g in groups:
            pkg = rc.package_for(g, wb, tmp)
            gdef = S.group_def(spec, g)
            pages = [int(p) for p in gdef.get("pages") or []]   # package 内の page (recipe の package 構成と一致させる)
            plain = tmp / f"{g}_plain.pdf"
            _extract(pkg, pages, plain)
            for line in declare_pages(plain, spec, g, pages):   # 出力の全頁 = 窓口に出す頁、 と宣言 (刷る直前の gate が読む)
                print("   " + line)
            rc.post_group(m, doc_id, g, plain)
            outs = (m.group(doc_id, g).get("current") or {}).get("outputs") or rc.default_outputs(wb.stem)[g]
            places = [(pages.index(pp) + 1, spec_) for pp, spec_ in rc.seals_for(g).items() if pp in pages]
            base = Path(out_dir) if out_dir else m.case_dir
            written[g] = {}
            if places:
                sealed = tmp / f"{g}_sealed.pdf"
                _seal(plain, sealed, places)
            for role, rel in outs.items():
                if role == "print":
                    src = sealed if places else plain
                elif role == "confirm":
                    src = plain
                else:
                    src = rc.derive(g, role, plain, wb, tmp)
                    if src is None:
                        raise BuildError(f"recipe {rc.form} は group {g} の出力 role {role!r} を作れない "
                                         "(manifest の outputs の役割名を recipe の既定に揃える)")
                if str(src).lower().endswith(".pdf"):
                    src = _ensure_declared(src, plain)      # 押印 engine 等が宣言を落としても出力には必ず載せる
                written[g][role] = _put(src, base / rel, m, out_dir)
    return written


def _put(src, dst: Path, m, out_dir):
    if out_dir is None and str(dst.resolve()) in m.frozen_outputs():
        raise BuildError(f"{dst.name} は凍結出力 = 書かない (formcase.py reopen で新しい issue を作る)")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst
